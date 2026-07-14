from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from app.domain.property.content_source_packet import canonical_json, now_utc_iso, sha256_json


_LEDGER_CONTRACT = "propertyquarry.content_job_ledger.v2"
_WEBHOOK_PROVIDER = "subscribr"
_WEBHOOK_TERMINAL_STATUSES = {
    "completed",
    "duplicate_ignored",
    "ignored",
    "received",
    "replay_conflict",
    "review_required",
}
_CONTENT_LOCK_SEED = 0x5051434A


class PropertyContentLedgerError(RuntimeError):
    """Base failure for the governed property-content ledger."""


class PropertyContentLedgerCorruptionError(PropertyContentLedgerError):
    """The file-backed development ledger is unreadable and was preserved."""


class PropertyContentJobClaimLostError(PropertyContentLedgerError):
    """A claimed job or webhook no longer belongs to this worker."""


def default_subscribr_completion_dir() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_SUBSCRIBR_COMPLETION_DIR") or "_completion/subscribr")


def default_property_content_ledger_path() -> Path:
    explicit = str(os.getenv("PROPERTYQUARRY_CONTENT_JOB_LEDGER") or "").strip()
    if explicit:
        return Path(explicit)
    return default_subscribr_completion_dir() / "property_content_jobs.json"


def _empty_ledger() -> dict[str, object]:
    return {
        "contract_name": _LEDGER_CONTRACT,
        "jobs": {},
        "job_events": [],
        "webhook_events": {},
        "next_event_sequence": 1,
    }


def _as_utc(value: datetime | str | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lease_active(row: dict[str, object], *, now: datetime) -> bool:
    owner = str(row.get("lease_owner") or "").strip()
    expires_at = str(row.get("lease_expires_at") or "").strip()
    if not owner or not expires_at:
        return False
    try:
        return _as_utc(expires_at) > now
    except (TypeError, ValueError) as exc:
        raise PropertyContentLedgerCorruptionError("property_content_lease_timestamp_invalid") from exc


def _job_idempotency_key(packet_id: str) -> str:
    return f"property-content-job:{str(packet_id or '').strip()}"


def _event_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(str(idempotency_key or "").encode("utf-8")).hexdigest()
    return f"content_evt_{digest[:24]}"


def _event_packet_id(payload: dict[str, object], event_id: str) -> str:
    packet_id = str(payload.get("packet_id") or payload.get("packetId") or "").strip()
    inline = payload.get("packet") if isinstance(payload.get("packet"), dict) else {}
    return packet_id or str(inline.get("packet_id") or "").strip() or f"webhook:{event_id}"


def _build_job_row(
    packet: dict[str, object],
    *,
    status: str,
    current: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
    observed_at: str | None = None,
) -> dict[str, object]:
    packet_id = str(packet.get("packet_id") or "").strip()
    if not packet_id:
        raise ValueError("property_content_packet_id_required")
    previous = dict(current or {})
    now = str(observed_at or now_utc_iso())
    row = {
        **previous,
        "packet_id": packet_id,
        "idempotency_key": _job_idempotency_key(packet_id),
        "content_mode": str(packet.get("content_mode") or ""),
        "channel_key": str(packet.get("subscribr_channel_key") or ""),
        "source_packet_json": dict(packet),
        "source_packet_sha256": str(packet.get("source_packet_sha256") or ""),
        "source_packet_canonical_sha256": sha256_json(packet),
        "status": str(status or "").strip() or "UNKNOWN",
        "updated_at": now,
        "created_at": str(previous.get("created_at") or now),
        "version": max(0, int(previous.get("version") or 0)) + 1,
        "production_allowed": False,
        "publication_allowed": False,
        "lease_owner": str(previous.get("lease_owner") or ""),
        "lease_expires_at": previous.get("lease_expires_at"),
        "claimed_at": previous.get("claimed_at"),
    }
    if extra:
        row.update(dict(extra))
    row.update(
        {
            "packet_id": packet_id,
            "idempotency_key": _job_idempotency_key(packet_id),
            "source_packet_json": dict(packet),
            "source_packet_canonical_sha256": sha256_json(packet),
            "production_allowed": False,
            "publication_allowed": False,
        }
    )
    return row


class _FilePropertyContentRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread_lock = threading.RLock()
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _locked(self, *, exclusive: bool):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self._lock_path.open("a+", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                try:
                    yield
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> dict[str, object]:
        if not self.path.exists():
            return _empty_ledger()
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PropertyContentLedgerCorruptionError("property_content_ledger_corrupt") from exc
        if not isinstance(parsed, dict):
            raise PropertyContentLedgerCorruptionError("property_content_ledger_not_object")
        jobs = parsed.get("jobs", {})
        webhook_events = parsed.get("webhook_events", {})
        job_events = parsed.get("job_events", [])
        if not isinstance(jobs, dict) or not isinstance(webhook_events, dict) or not isinstance(job_events, list):
            raise PropertyContentLedgerCorruptionError("property_content_ledger_shape_invalid")
        if any(not isinstance(row, dict) for row in jobs.values()):
            raise PropertyContentLedgerCorruptionError("property_content_job_row_invalid")
        if any(not isinstance(row, dict) for row in webhook_events.values()):
            raise PropertyContentLedgerCorruptionError("property_content_webhook_row_invalid")
        normalized = dict(parsed)
        normalized["contract_name"] = _LEDGER_CONTRACT
        normalized["jobs"] = jobs
        normalized["webhook_events"] = webhook_events
        normalized["job_events"] = job_events
        try:
            next_sequence = max(1, int(normalized.get("next_event_sequence") or 1))
        except (TypeError, ValueError):
            raise PropertyContentLedgerCorruptionError("property_content_ledger_sequence_invalid")
        observed_sequences: list[int] = []
        observed_event_ids: set[str] = set()
        observed_idempotency_keys: set[str] = set()
        for event in job_events:
            if not isinstance(event, dict):
                raise PropertyContentLedgerCorruptionError("property_content_job_event_invalid")
            try:
                sequence = int(event.get("event_sequence") or 0)
            except (TypeError, ValueError) as exc:
                raise PropertyContentLedgerCorruptionError("property_content_job_event_sequence_invalid") from exc
            event_id = str(event.get("event_id") or "").strip()
            idempotency_key = str(event.get("idempotency_key") or "").strip()
            if sequence < 1 or not event_id or not idempotency_key:
                raise PropertyContentLedgerCorruptionError("property_content_job_event_invalid")
            if event_id in observed_event_ids or idempotency_key in observed_idempotency_keys:
                raise PropertyContentLedgerCorruptionError("property_content_job_event_duplicate")
            observed_sequences.append(sequence)
            observed_event_ids.add(event_id)
            observed_idempotency_keys.add(idempotency_key)
        if observed_sequences != sorted(observed_sequences) or len(observed_sequences) != len(set(observed_sequences)):
            raise PropertyContentLedgerCorruptionError("property_content_job_event_order_invalid")
        normalized["next_event_sequence"] = max([next_sequence, *(value + 1 for value in observed_sequences)])
        return normalized

    def _write_unlocked(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
        )
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(self.path)
            directory_fd = os.open(str(self.path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if tmp.exists():
                tmp.unlink()

    def snapshot(self) -> dict[str, object]:
        with self._locked(exclusive=False):
            return self._load_unlocked()

    def _append_event_unlocked(
        self,
        data: dict[str, object],
        *,
        packet_id: str,
        event_type: str,
        status: str,
        payload: dict[str, object],
        idempotency_key: str,
        created_at: str,
    ) -> dict[str, object]:
        events = data.setdefault("job_events", [])
        if not isinstance(events, list):
            raise PropertyContentLedgerCorruptionError("property_content_job_events_invalid")
        existing = next(
            (
                dict(candidate)
                for candidate in events
                if isinstance(candidate, dict)
                and str(candidate.get("idempotency_key") or "") == idempotency_key
            ),
            None,
        )
        if existing is not None:
            return existing
        sequence = max(1, int(data.get("next_event_sequence") or 1))
        row = {
            "event_sequence": sequence,
            "event_id": _event_id(idempotency_key),
            "packet_id": str(packet_id or "").strip(),
            "event_type": str(event_type or "").strip(),
            "status": str(status or "").strip(),
            "idempotency_key": idempotency_key,
            "payload_json": dict(payload or {}),
            "created_at": created_at,
        }
        events.append(row)
        data["next_event_sequence"] = sequence + 1
        return row

    def get_job(self, packet_id: str) -> dict[str, object] | None:
        data = self.snapshot()
        jobs = data["jobs"]
        row = jobs.get(str(packet_id or "").strip())
        return dict(row) if isinstance(row, dict) else None

    def list_jobs(self, *, limit: int) -> list[dict[str, object]]:
        jobs = self.snapshot()["jobs"]
        rows = [dict(row) for row in jobs.values() if isinstance(row, dict)]
        rows.sort(
            key=lambda row: (str(row.get("updated_at") or ""), str(row.get("packet_id") or "")),
            reverse=True,
        )
        return rows[:limit]

    def upsert_job(
        self,
        packet: dict[str, object],
        *,
        status: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        packet_id = str(packet.get("packet_id") or "").strip()
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            jobs = data["jobs"]
            current = dict(jobs.get(packet_id) or {})
            row = _build_job_row(packet, status=status, current=current, extra=extra)
            jobs[packet_id] = row
            self._append_event_unlocked(
                data,
                packet_id=packet_id,
                event_type="job_upserted",
                status=str(row["status"]),
                payload={"version": row["version"], "status": row["status"]},
                idempotency_key=f"{_job_idempotency_key(packet_id)}:version:{row['version']}",
                created_at=str(row["updated_at"]),
            )
            self._write_unlocked(data)
            return dict(row)

    def record_provider_ids(
        self,
        *,
        packet_id: str,
        provider_channel_id: object = "",
        provider_idea_id: object = "",
        provider_script_id: object = "",
        status: str = "PROVIDER_JOB_CREATED",
        lease_owner: str = "",
    ) -> dict[str, object]:
        normalized_packet = str(packet_id or "").strip()
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            jobs = data["jobs"]
            current = dict(jobs.get(normalized_packet) or {})
            if not current:
                raise ValueError("property_content_job_not_found")
            owner = str(lease_owner or "").strip()
            if owner and str(current.get("lease_owner") or "") != owner:
                raise PropertyContentJobClaimLostError("property_content_job_claim_lost")
            now = now_utc_iso()
            row = {
                **current,
                "provider": _WEBHOOK_PROVIDER,
                "provider_channel_id": str(provider_channel_id or current.get("provider_channel_id") or ""),
                "provider_idea_id": str(provider_idea_id or current.get("provider_idea_id") or ""),
                "provider_script_id": str(provider_script_id or current.get("provider_script_id") or ""),
                "status": str(status or "PROVIDER_JOB_CREATED"),
                "updated_at": now,
                "version": max(0, int(current.get("version") or 0)) + 1,
                "lease_owner": "" if owner else str(current.get("lease_owner") or ""),
                "lease_expires_at": None if owner else current.get("lease_expires_at"),
            }
            jobs[normalized_packet] = row
            self._append_event_unlocked(
                data,
                packet_id=normalized_packet,
                event_type="provider_ids_recorded",
                status=str(row["status"]),
                payload={
                    "version": row["version"],
                    "provider_channel_id": row["provider_channel_id"],
                    "provider_idea_id": row["provider_idea_id"],
                    "provider_script_id": row["provider_script_id"],
                },
                idempotency_key=f"{_job_idempotency_key(normalized_packet)}:version:{row['version']}",
                created_at=now,
            )
            self._write_unlocked(data)
            return dict(row)

    def claim_job(
        self,
        packet_id: str,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        normalized_packet = str(packet_id or "").strip()
        owner = str(lease_owner or "").strip()
        if not normalized_packet or not owner:
            raise ValueError("property_content_job_claim_identity_required")
        observed = _as_utc(now)
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            jobs = data["jobs"]
            current = dict(jobs.get(normalized_packet) or {})
            if not current:
                return None
            if _lease_active(current, now=observed):
                return dict(current) if str(current.get("lease_owner") or "") == owner else None
            recovered = bool(str(current.get("lease_owner") or ""))
            claimed_at = observed.isoformat()
            row = {
                **current,
                "lease_owner": owner,
                "lease_expires_at": (observed + timedelta(seconds=max(1, int(lease_seconds or 1)))).isoformat(),
                "claimed_at": claimed_at,
                "claim_recovered": recovered,
                "updated_at": claimed_at,
                "version": max(0, int(current.get("version") or 0)) + 1,
            }
            jobs[normalized_packet] = row
            self._append_event_unlocked(
                data,
                packet_id=normalized_packet,
                event_type="job_claim_recovered" if recovered else "job_claimed",
                status=str(row.get("status") or ""),
                payload={"version": row["version"], "lease_owner": owner},
                idempotency_key=f"{_job_idempotency_key(normalized_packet)}:claim:{row['version']}",
                created_at=claimed_at,
            )
            self._write_unlocked(data)
            return dict(row)

    def update_claimed_job(
        self,
        packet_id: str,
        *,
        lease_owner: str,
        status: str,
        extra: dict[str, object] | None = None,
        release: bool = True,
    ) -> dict[str, object]:
        normalized_packet = str(packet_id or "").strip()
        owner = str(lease_owner or "").strip()
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            jobs = data["jobs"]
            current = dict(jobs.get(normalized_packet) or {})
            if not current:
                raise ValueError("property_content_job_not_found")
            if not owner or str(current.get("lease_owner") or "") != owner:
                raise PropertyContentJobClaimLostError("property_content_job_claim_lost")
            now = now_utc_iso()
            row = {**current, **dict(extra or {})}
            row.update(
                {
                    "packet_id": normalized_packet,
                    "idempotency_key": _job_idempotency_key(normalized_packet),
                    "status": str(status or current.get("status") or "UNKNOWN"),
                    "updated_at": now,
                    "version": max(0, int(current.get("version") or 0)) + 1,
                    "lease_owner": "" if release else owner,
                    "lease_expires_at": None if release else current.get("lease_expires_at"),
                }
            )
            jobs[normalized_packet] = row
            self._append_event_unlocked(
                data,
                packet_id=normalized_packet,
                event_type="job_claim_completed" if release else "job_claim_updated",
                status=str(row["status"]),
                payload={"version": row["version"], "status": row["status"]},
                idempotency_key=f"{_job_idempotency_key(normalized_packet)}:version:{row['version']}",
                created_at=now,
            )
            self._write_unlocked(data)
            return dict(row)

    def webhook_seen(self, event_id: str) -> bool:
        events = self.snapshot()["webhook_events"]
        return str(event_id or "").strip() in events

    def claim_webhook_event(
        self,
        *,
        event_id: str,
        payload: dict[str, object],
        extra: dict[str, object] | None,
        claim_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, object]:
        event_ref = str(event_id or "").strip()
        owner = str(claim_owner or "").strip()
        if not event_ref:
            raise ValueError("subscribr_webhook_event_id_required")
        if not owner:
            raise ValueError("subscribr_webhook_claim_owner_required")
        observed = _as_utc(now)
        observed_iso = observed.isoformat()
        payload_hash = sha256_json(payload)
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            events = data["webhook_events"]
            current = dict(events.get(event_ref) or {})
            recovered = False
            duplicate = False
            conflict = False
            if current:
                current["replayed_at"] = observed_iso
                current["replay_count"] = max(0, int(current.get("replay_count") or 0)) + 1
                current["version"] = max(0, int(current.get("version") or 0)) + 1
                if str(current.get("payload_sha256") or "") != payload_hash:
                    current["status"] = "replay_conflict"
                    current["last_error"] = "provider_event_payload_mismatch"
                    current["conflict_at"] = observed_iso
                    current["lease_owner"] = ""
                    current["lease_expires_at"] = None
                    conflict = True
                    duplicate = True
                elif current.get("processed_at") or str(current.get("status") or "") in _WEBHOOK_TERMINAL_STATUSES:
                    duplicate = True
                elif _lease_active(current, now=observed):
                    duplicate = True
                else:
                    recovered = True
            if not current:
                current = {
                    "provider": _WEBHOOK_PROVIDER,
                    "event_id": event_ref,
                    "event_type": str(payload.get("type") or payload.get("event") or payload.get("event_type") or ""),
                    "payload_sha256": payload_hash,
                    "payload_json": dict(payload),
                    "received_at": observed_iso,
                    "replay_count": 0,
                    "version": 1,
                }
            if not duplicate:
                current.update(
                    {
                        "status": "processing",
                        "lease_owner": owner,
                        "lease_expires_at": (
                            observed + timedelta(seconds=max(1, int(lease_seconds or 1)))
                        ).isoformat(),
                        "claimed_at": observed_iso,
                        "claim_recovered": recovered,
                        "updated_at": observed_iso,
                        **dict(extra or {}),
                    }
                )
            else:
                current["updated_at"] = observed_iso
            events[event_ref] = current
            if conflict:
                original_payload = dict(current.get("payload_json") or {})
                self._append_event_unlocked(
                    data,
                    packet_id=_event_packet_id(original_payload, event_ref),
                    event_type="webhook_replay_conflict",
                    status="replay_conflict",
                    payload={"event_id": event_ref, "replayed_payload_sha256": payload_hash},
                    idempotency_key=f"subscribr-webhook:{event_ref}:replay-conflict:{payload_hash}",
                    created_at=observed_iso,
                )
            elif not duplicate:
                packet_id = _event_packet_id(payload, event_ref)
                self._append_event_unlocked(
                    data,
                    packet_id=packet_id,
                    event_type="webhook_claim_recovered" if recovered else "webhook_received",
                    status="processing",
                    payload={"event_id": event_ref, "payload_sha256": payload_hash},
                    idempotency_key=(
                        f"subscribr-webhook:{event_ref}:recovered:{current['version']}"
                        if recovered
                        else f"subscribr-webhook:{event_ref}:received"
                    ),
                    created_at=observed_iso,
                )
            self._write_unlocked(data)
            return {
                "claimed": not duplicate,
                "duplicate": duplicate,
                "recovered": recovered,
                "conflict": conflict,
                "row": dict(current),
            }

    def complete_webhook_event(
        self,
        *,
        event_id: str,
        claim_owner: str,
        status: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        event_ref = str(event_id or "").strip()
        owner = str(claim_owner or "").strip()
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            events = data["webhook_events"]
            current = dict(events.get(event_ref) or {})
            if not current:
                raise ValueError("subscribr_webhook_event_not_found")
            if not owner or str(current.get("lease_owner") or "") != owner:
                raise PropertyContentJobClaimLostError("subscribr_webhook_claim_lost")
            now = now_utc_iso()
            row = {**current, **dict(extra or {})}
            row.update(
                {
                    "status": str(status or "completed"),
                    "processed_at": now,
                    "updated_at": now,
                    "lease_owner": "",
                    "lease_expires_at": None,
                    "version": max(0, int(current.get("version") or 0)) + 1,
                }
            )
            events[event_ref] = row
            packet_id = _event_packet_id(dict(row.get("payload_json") or {}), event_ref)
            self._append_event_unlocked(
                data,
                packet_id=packet_id,
                event_type="webhook_completed",
                status=str(row["status"]),
                payload={"event_id": event_ref, "version": row["version"]},
                idempotency_key=f"subscribr-webhook:{event_ref}:completed",
                created_at=now,
            )
            self._write_unlocked(data)
            return dict(row)

    def fail_webhook_event(
        self,
        *,
        event_id: str,
        claim_owner: str,
        error: str,
    ) -> dict[str, object]:
        event_ref = str(event_id or "").strip()
        owner = str(claim_owner or "").strip()
        with self._locked(exclusive=True):
            data = self._load_unlocked()
            events = data["webhook_events"]
            current = dict(events.get(event_ref) or {})
            if not current or str(current.get("lease_owner") or "") != owner:
                raise PropertyContentJobClaimLostError("subscribr_webhook_claim_lost")
            now = now_utc_iso()
            row = {
                **current,
                "status": "retry",
                "last_error": str(error or "webhook_processing_failed")[:300],
                "updated_at": now,
                "lease_owner": "",
                "lease_expires_at": None,
                "version": max(0, int(current.get("version") or 0)) + 1,
            }
            events[event_ref] = row
            self._write_unlocked(data)
            return dict(row)


class _PostgresPropertyContentRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = str(database_url or "").strip()
        if not self.database_url:
            raise PropertyContentLedgerError("property_content_database_url_required")
        from app.product.property_search_schema import require_property_search_schema_ready

        require_property_search_schema_ready(self.database_url)

    def _connect(self):  # type: ignore[no-untyped-def]
        import psycopg

        return psycopg.connect(self.database_url, autocommit=True, connect_timeout=5)

    @staticmethod
    def _json(value: dict[str, object]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    @staticmethod
    def _advisory_key(kind: str, identity: str) -> str:
        return f"property-content:{kind}:{identity}"

    def _lock_cursor(self, cur, *, kind: str, identity: str, try_lock: bool = False) -> bool:  # type: ignore[no-untyped-def]
        function = "pg_try_advisory_xact_lock" if try_lock else "pg_advisory_xact_lock"
        cur.execute(
            f"SELECT {function}(hashtextextended(%s, %s))",
            (self._advisory_key(kind, identity), _CONTENT_LOCK_SEED),
        )
        row = cur.fetchone()
        return bool(row and row[0]) if try_lock else True

    def _append_event_cursor(
        self,
        cur,  # type: ignore[no-untyped-def]
        *,
        packet_id: str,
        event_type: str,
        status: str,
        payload: dict[str, object],
        idempotency_key: str,
        created_at: str,
    ) -> None:
        cur.execute(
            """
            INSERT INTO property_content_job_events
                (event_id, packet_id, event_type, status, idempotency_key, payload_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                _event_id(idempotency_key),
                packet_id,
                event_type,
                status,
                idempotency_key,
                self._json(payload),
                created_at,
            ),
        )

    def snapshot(self) -> dict[str, object]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT packet_id, row_json FROM property_content_jobs ORDER BY updated_at DESC")
                jobs = {str(packet_id): dict(row or {}) for packet_id, row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT event_sequence, event_id, packet_id, event_type, status,
                           idempotency_key, payload_json, created_at
                    FROM property_content_job_events
                    ORDER BY event_sequence
                    """
                )
                job_events = [
                    {
                        "event_sequence": int(sequence),
                        "event_id": str(event_id),
                        "packet_id": str(packet_id),
                        "event_type": str(event_type),
                        "status": str(status),
                        "idempotency_key": str(idempotency_key),
                        "payload_json": dict(payload or {}),
                        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                    }
                    for sequence, event_id, packet_id, event_type, status, idempotency_key, payload, created_at in cur.fetchall()
                ]
                cur.execute(
                    "SELECT provider_event_id, row_json FROM property_content_webhook_events ORDER BY received_at"
                )
                webhook_events = {str(event_id): dict(row or {}) for event_id, row in cur.fetchall()}
        return {
            "contract_name": _LEDGER_CONTRACT,
            "jobs": jobs,
            "job_events": job_events,
            "webhook_events": webhook_events,
            "next_event_sequence": (job_events[-1]["event_sequence"] + 1) if job_events else 1,
        }

    def get_job(self, packet_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT row_json FROM property_content_jobs WHERE packet_id = %s",
                    (str(packet_id or "").strip(),),
                )
                row = cur.fetchone()
        return dict(row[0] or {}) if row else None

    def list_jobs(self, *, limit: int) -> list[dict[str, object]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT row_json FROM property_content_jobs ORDER BY updated_at DESC, packet_id DESC LIMIT %s",
                    (limit,),
                )
                rows = [dict(row or {}) for (row,) in cur.fetchall()]
        return rows

    def upsert_job(self, packet: dict[str, object], *, status: str, extra=None) -> dict[str, object]:  # type: ignore[no-untyped-def]
        packet_id = str(packet.get("packet_id") or "").strip()
        if not packet_id:
            raise ValueError("property_content_packet_id_required")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_cursor(cur, kind="job", identity=packet_id)
                    cur.execute(
                        "SELECT row_json FROM property_content_jobs WHERE packet_id = %s FOR UPDATE",
                        (packet_id,),
                    )
                    found = cur.fetchone()
                    current = dict(found[0] or {}) if found else {}
                    row = _build_job_row(packet, status=status, current=current, extra=extra)
                    cur.execute(
                        """
                        INSERT INTO property_content_jobs
                            (packet_id, idempotency_key, status, source_packet_json,
                             source_packet_sha256, row_json, version, lease_owner,
                             lease_expires_at, claimed_at, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (packet_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            source_packet_json = EXCLUDED.source_packet_json,
                            source_packet_sha256 = EXCLUDED.source_packet_sha256,
                            row_json = EXCLUDED.row_json,
                            version = EXCLUDED.version,
                            lease_owner = EXCLUDED.lease_owner,
                            lease_expires_at = EXCLUDED.lease_expires_at,
                            claimed_at = EXCLUDED.claimed_at,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            packet_id,
                            row["idempotency_key"],
                            row["status"],
                            self._json(dict(row["source_packet_json"])),
                            str(row["source_packet_canonical_sha256"]),
                            self._json(row),
                            row["version"],
                            row.get("lease_owner") or "",
                            row.get("lease_expires_at"),
                            row.get("claimed_at"),
                            row["created_at"],
                            row["updated_at"],
                        ),
                    )
                    self._append_event_cursor(
                        cur,
                        packet_id=packet_id,
                        event_type="job_upserted",
                        status=str(row["status"]),
                        payload={"version": row["version"], "status": row["status"]},
                        idempotency_key=f"{_job_idempotency_key(packet_id)}:version:{row['version']}",
                        created_at=str(row["updated_at"]),
                    )
        return row

    def _update_existing_job(
        self,
        *,
        packet_id: str,
        transform,  # type: ignore[no-untyped-def]
        event_type: str,
        lease_owner: str = "",
    ) -> dict[str, object]:
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_cursor(cur, kind="job", identity=packet_id)
                    cur.execute(
                        "SELECT row_json FROM property_content_jobs WHERE packet_id = %s FOR UPDATE",
                        (packet_id,),
                    )
                    found = cur.fetchone()
                    if not found:
                        raise ValueError("property_content_job_not_found")
                    current = dict(found[0] or {})
                    owner = str(lease_owner or "").strip()
                    if owner and str(current.get("lease_owner") or "") != owner:
                        raise PropertyContentJobClaimLostError("property_content_job_claim_lost")
                    row = transform(current)
                    cur.execute(
                        """
                        UPDATE property_content_jobs
                        SET status = %s, row_json = %s, version = %s,
                            lease_owner = %s, lease_expires_at = %s,
                            claimed_at = %s, updated_at = %s
                        WHERE packet_id = %s
                        """,
                        (
                            row["status"],
                            self._json(row),
                            row["version"],
                            row.get("lease_owner") or "",
                            row.get("lease_expires_at"),
                            row.get("claimed_at"),
                            row["updated_at"],
                            packet_id,
                        ),
                    )
                    self._append_event_cursor(
                        cur,
                        packet_id=packet_id,
                        event_type=event_type,
                        status=str(row["status"]),
                        payload={"version": row["version"], "status": row["status"]},
                        idempotency_key=f"{_job_idempotency_key(packet_id)}:version:{row['version']}",
                        created_at=str(row["updated_at"]),
                    )
        return row

    def record_provider_ids(self, *, packet_id: str, provider_channel_id="", provider_idea_id="", provider_script_id="", status="PROVIDER_JOB_CREATED", lease_owner=""):  # type: ignore[no-untyped-def]
        normalized_packet = str(packet_id or "").strip()

        def transform(current):  # type: ignore[no-untyped-def]
            now = now_utc_iso()
            owner = str(lease_owner or "").strip()
            return {
                **current,
                "provider": _WEBHOOK_PROVIDER,
                "provider_channel_id": str(provider_channel_id or current.get("provider_channel_id") or ""),
                "provider_idea_id": str(provider_idea_id or current.get("provider_idea_id") or ""),
                "provider_script_id": str(provider_script_id or current.get("provider_script_id") or ""),
                "status": str(status or "PROVIDER_JOB_CREATED"),
                "updated_at": now,
                "version": max(0, int(current.get("version") or 0)) + 1,
                "lease_owner": "" if owner else str(current.get("lease_owner") or ""),
                "lease_expires_at": None if owner else current.get("lease_expires_at"),
            }

        return self._update_existing_job(
            packet_id=normalized_packet,
            transform=transform,
            event_type="provider_ids_recorded",
            lease_owner=str(lease_owner or ""),
        )

    def claim_job(self, packet_id: str, *, lease_owner: str, lease_seconds: int, now=None):  # type: ignore[no-untyped-def]
        normalized_packet = str(packet_id or "").strip()
        owner = str(lease_owner or "").strip()
        observed = _as_utc(now)
        if not normalized_packet or not owner:
            raise ValueError("property_content_job_claim_identity_required")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if not self._lock_cursor(cur, kind="job-claim", identity=normalized_packet, try_lock=True):
                        return None
                    cur.execute(
                        "SELECT row_json FROM property_content_jobs WHERE packet_id = %s FOR UPDATE SKIP LOCKED",
                        (normalized_packet,),
                    )
                    found = cur.fetchone()
                    if not found:
                        return None
                    current = dict(found[0] or {})
                    if _lease_active(current, now=observed):
                        return current if str(current.get("lease_owner") or "") == owner else None
                    recovered = bool(str(current.get("lease_owner") or ""))
                    claimed_at = observed.isoformat()
                    row = {
                        **current,
                        "lease_owner": owner,
                        "lease_expires_at": (observed + timedelta(seconds=max(1, int(lease_seconds or 1)))).isoformat(),
                        "claimed_at": claimed_at,
                        "claim_recovered": recovered,
                        "updated_at": claimed_at,
                        "version": max(0, int(current.get("version") or 0)) + 1,
                    }
                    cur.execute(
                        """
                        UPDATE property_content_jobs
                        SET row_json = %s, version = %s, lease_owner = %s,
                            lease_expires_at = %s, claimed_at = %s, updated_at = %s
                        WHERE packet_id = %s
                        """,
                        (
                            self._json(row), row["version"], owner, row["lease_expires_at"],
                            claimed_at, claimed_at, normalized_packet,
                        ),
                    )
                    self._append_event_cursor(
                        cur,
                        packet_id=normalized_packet,
                        event_type="job_claim_recovered" if recovered else "job_claimed",
                        status=str(row.get("status") or ""),
                        payload={"version": row["version"], "lease_owner": owner},
                        idempotency_key=f"{_job_idempotency_key(normalized_packet)}:claim:{row['version']}",
                        created_at=claimed_at,
                    )
        return row

    def update_claimed_job(self, packet_id: str, *, lease_owner: str, status: str, extra=None, release=True):  # type: ignore[no-untyped-def]
        normalized_packet = str(packet_id or "").strip()
        owner = str(lease_owner or "").strip()

        def transform(current):  # type: ignore[no-untyped-def]
            now = now_utc_iso()
            row = {**current, **dict(extra or {})}
            row.update(
                {
                    "packet_id": normalized_packet,
                    "idempotency_key": _job_idempotency_key(normalized_packet),
                    "status": str(status or current.get("status") or "UNKNOWN"),
                    "updated_at": now,
                    "version": max(0, int(current.get("version") or 0)) + 1,
                    "lease_owner": "" if release else owner,
                    "lease_expires_at": None if release else current.get("lease_expires_at"),
                }
            )
            return row

        return self._update_existing_job(
            packet_id=normalized_packet,
            transform=transform,
            event_type="job_claim_completed" if release else "job_claim_updated",
            lease_owner=owner,
        )

    def webhook_seen(self, event_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM property_content_webhook_events WHERE provider = %s AND provider_event_id = %s",
                    (_WEBHOOK_PROVIDER, str(event_id or "").strip()),
                )
                return cur.fetchone() is not None

    def claim_webhook_event(self, *, event_id: str, payload: dict[str, object], extra, claim_owner: str, lease_seconds: int, now=None):  # type: ignore[no-untyped-def]
        event_ref = str(event_id or "").strip()
        owner = str(claim_owner or "").strip()
        if not event_ref or not owner:
            raise ValueError("subscribr_webhook_claim_identity_required")
        observed = _as_utc(now)
        observed_iso = observed.isoformat()
        payload_hash = sha256_json(payload)
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if not self._lock_cursor(cur, kind="webhook", identity=event_ref, try_lock=True):
                        return {"claimed": False, "duplicate": True, "recovered": False, "conflict": False, "row": {"event_id": event_ref, "status": "claim_contended"}}
                    cur.execute(
                        """
                        SELECT row_json
                        FROM property_content_webhook_events
                        WHERE provider = %s AND provider_event_id = %s
                        FOR UPDATE SKIP LOCKED
                        """,
                        (_WEBHOOK_PROVIDER, event_ref),
                    )
                    found = cur.fetchone()
                    current = dict(found[0] or {}) if found else {}
                    recovered = False
                    duplicate = False
                    conflict = False
                    if current:
                        current["replayed_at"] = observed_iso
                        current["replay_count"] = max(0, int(current.get("replay_count") or 0)) + 1
                        current["version"] = max(0, int(current.get("version") or 0)) + 1
                        if str(current.get("payload_sha256") or "") != payload_hash:
                            current["status"] = "replay_conflict"
                            current["last_error"] = "provider_event_payload_mismatch"
                            current["conflict_at"] = observed_iso
                            current["lease_owner"] = ""
                            current["lease_expires_at"] = None
                            conflict = True
                            duplicate = True
                        elif current.get("processed_at") or str(current.get("status") or "") in _WEBHOOK_TERMINAL_STATUSES:
                            duplicate = True
                        elif _lease_active(current, now=observed):
                            duplicate = True
                        else:
                            recovered = True
                    if not current:
                        current = {
                            "provider": _WEBHOOK_PROVIDER,
                            "event_id": event_ref,
                            "event_type": str(payload.get("type") or payload.get("event") or payload.get("event_type") or ""),
                            "payload_sha256": payload_hash,
                            "payload_json": dict(payload),
                            "received_at": observed_iso,
                            "replay_count": 0,
                            "version": 1,
                        }
                    if not duplicate:
                        current.update(
                            {
                                "status": "processing",
                                "lease_owner": owner,
                                "lease_expires_at": (observed + timedelta(seconds=max(1, int(lease_seconds or 1)))).isoformat(),
                                "claimed_at": observed_iso,
                                "claim_recovered": recovered,
                                "updated_at": observed_iso,
                                **dict(extra or {}),
                            }
                        )
                    else:
                        current["updated_at"] = observed_iso
                    if found:
                        cur.execute(
                            """
                            UPDATE property_content_webhook_events
                            SET event_type = %s, status = %s, row_json = %s, version = %s,
                                lease_owner = %s, lease_expires_at = %s, claimed_at = %s,
                                replayed_at = %s, updated_at = %s
                            WHERE provider = %s AND provider_event_id = %s
                            """,
                            (
                                current.get("event_type") or "", current.get("status") or "processing",
                                self._json(current), current["version"], current.get("lease_owner") or "",
                                current.get("lease_expires_at"), current.get("claimed_at"), current.get("replayed_at"),
                                current["updated_at"], _WEBHOOK_PROVIDER, event_ref,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO property_content_webhook_events
                                (provider, provider_event_id, event_type, status, payload_sha256,
                                 row_json, version, lease_owner, lease_expires_at, claimed_at,
                                 received_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (provider, provider_event_id) DO NOTHING
                            """,
                            (
                                _WEBHOOK_PROVIDER, event_ref, current["event_type"], current["status"],
                                payload_hash, self._json(current), current["version"], owner,
                                current["lease_expires_at"], observed_iso, observed_iso, observed_iso,
                            ),
                        )
                        if cur.rowcount != 1:
                            return {"claimed": False, "duplicate": True, "recovered": False, "conflict": False, "row": {"event_id": event_ref, "status": "claim_contended"}}
                    if conflict:
                        original_payload = dict(current.get("payload_json") or {})
                        self._append_event_cursor(
                            cur,
                            packet_id=_event_packet_id(original_payload, event_ref),
                            event_type="webhook_replay_conflict",
                            status="replay_conflict",
                            payload={"event_id": event_ref, "replayed_payload_sha256": payload_hash},
                            idempotency_key=f"subscribr-webhook:{event_ref}:replay-conflict:{payload_hash}",
                            created_at=observed_iso,
                        )
                    elif not duplicate:
                        self._append_event_cursor(
                            cur,
                            packet_id=_event_packet_id(payload, event_ref),
                            event_type="webhook_claim_recovered" if recovered else "webhook_received",
                            status="processing",
                            payload={"event_id": event_ref, "payload_sha256": payload_hash},
                            idempotency_key=(
                                f"subscribr-webhook:{event_ref}:recovered:{current['version']}"
                                if recovered
                                else f"subscribr-webhook:{event_ref}:received"
                            ),
                            created_at=observed_iso,
                        )
        return {"claimed": not duplicate, "duplicate": duplicate, "recovered": recovered, "conflict": conflict, "row": current}

    def _finish_webhook(self, *, event_id: str, claim_owner: str, status: str, extra=None, retry=False):  # type: ignore[no-untyped-def]
        event_ref = str(event_id or "").strip()
        owner = str(claim_owner or "").strip()
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    self._lock_cursor(cur, kind="webhook", identity=event_ref)
                    cur.execute(
                        """
                        SELECT row_json FROM property_content_webhook_events
                        WHERE provider = %s AND provider_event_id = %s
                        FOR UPDATE
                        """,
                        (_WEBHOOK_PROVIDER, event_ref),
                    )
                    found = cur.fetchone()
                    current = dict(found[0] or {}) if found else {}
                    if not current or str(current.get("lease_owner") or "") != owner:
                        raise PropertyContentJobClaimLostError("subscribr_webhook_claim_lost")
                    now = now_utc_iso()
                    row = {**current, **dict(extra or {})}
                    row.update(
                        {
                            "status": status,
                            "updated_at": now,
                            "lease_owner": "",
                            "lease_expires_at": None,
                            "version": max(0, int(current.get("version") or 0)) + 1,
                        }
                    )
                    if not retry:
                        row["processed_at"] = now
                    cur.execute(
                        """
                        UPDATE property_content_webhook_events
                        SET status = %s, row_json = %s, version = %s,
                            lease_owner = '', lease_expires_at = NULL,
                            processed_at = %s, updated_at = %s
                        WHERE provider = %s AND provider_event_id = %s
                        """,
                        (
                            status, self._json(row), row["version"], row.get("processed_at"), now,
                            _WEBHOOK_PROVIDER, event_ref,
                        ),
                    )
                    if not retry:
                        self._append_event_cursor(
                            cur,
                            packet_id=_event_packet_id(dict(row.get("payload_json") or {}), event_ref),
                            event_type="webhook_completed",
                            status=status,
                            payload={"event_id": event_ref, "version": row["version"]},
                            idempotency_key=f"subscribr-webhook:{event_ref}:completed",
                            created_at=now,
                        )
        return row

    def complete_webhook_event(self, *, event_id: str, claim_owner: str, status: str, extra=None):  # type: ignore[no-untyped-def]
        return self._finish_webhook(event_id=event_id, claim_owner=claim_owner, status=status, extra=extra)

    def fail_webhook_event(self, *, event_id: str, claim_owner: str, error: str):
        return self._finish_webhook(
            event_id=event_id,
            claim_owner=claim_owner,
            status="retry",
            extra={"last_error": str(error or "webhook_processing_failed")[:300]},
            retry=True,
        )


class PropertyContentJobLedger:
    """Governed content ledger with durable Postgres and locked file development modes."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        database_url: str = "",
        backend: str = "",
    ) -> None:
        resolved_backend = str(backend or os.getenv("EA_STORAGE_BACKEND") or "auto").strip().lower()
        resolved_url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
        if path is not None:
            self._repository = _FilePropertyContentRepository(Path(path))
            self._backend = "file"
        elif resolved_backend == "postgres" or (resolved_backend == "auto" and resolved_url):
            self._repository = _PostgresPropertyContentRepository(resolved_url)
            self._backend = "postgres"
        else:
            if str(os.getenv("EA_RUNTIME_MODE") or "dev").strip().lower() == "prod":
                raise PropertyContentLedgerError("property_content_postgres_required_in_prod")
            self._repository = _FilePropertyContentRepository(default_property_content_ledger_path())
            self._backend = "file"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def path(self) -> Path:
        return getattr(self._repository, "path", Path("postgres-property-content-ledger"))

    def _load(self) -> dict[str, object]:
        return self._repository.snapshot()

    def get_job(self, packet_id: str) -> dict[str, object] | None:
        return self._repository.get_job(packet_id)

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, object]]:
        normalized_limit = max(1, min(1000, int(limit or 100)))
        return self._repository.list_jobs(limit=normalized_limit)

    def upsert_job(self, packet: dict[str, object], *, status: str, extra=None) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return self._repository.upsert_job(packet, status=status, extra=extra)

    def record_provider_ids(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._repository.record_provider_ids(**kwargs)

    def claim_job(self, packet_id: str, *, lease_owner: str, lease_seconds: int, now=None):  # type: ignore[no-untyped-def]
        return self._repository.claim_job(
            packet_id,
            lease_owner=lease_owner,
            lease_seconds=lease_seconds,
            now=now,
        )

    def update_claimed_job(self, packet_id: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._repository.update_claimed_job(packet_id, **kwargs)

    def webhook_seen(self, event_id: str) -> bool:
        return self._repository.webhook_seen(event_id)

    def claim_webhook_event(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._repository.claim_webhook_event(**kwargs)

    def complete_webhook_event(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._repository.complete_webhook_event(**kwargs)

    def fail_webhook_event(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._repository.fail_webhook_event(**kwargs)

    def record_webhook_event(self, *, event_id: str, payload: dict[str, object], status: str, extra=None):  # type: ignore[no-untyped-def]
        owner = f"legacy-record:{os.getpid()}:{threading.get_ident()}:{uuid4().hex}"
        claim = self.claim_webhook_event(
            event_id=event_id,
            payload=payload,
            extra=extra,
            claim_owner=owner,
            lease_seconds=60,
        )
        if not bool(claim.get("claimed")):
            return dict(claim.get("row") or {})
        return self.complete_webhook_event(
            event_id=event_id,
            claim_owner=owner,
            status=status,
        )

    def write_receipt(self, *, packet_id: str, receipt: dict[str, object]) -> Path:
        safe_packet = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_"
            for ch in str(packet_id or "").strip()
        )[:180]
        if not safe_packet:
            raise ValueError("property_content_packet_id_required")
        path = default_subscribr_completion_dir() / f"propertyquarry_{safe_packet}.generated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(canonical_json(receipt))
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return path
