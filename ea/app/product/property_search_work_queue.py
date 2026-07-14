from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
import threading
from typing import Callable
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = str(value or "").strip().replace("Z", "+00:00")
        if not normalized:
            return None
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(os.environ.get(name) or default).strip())
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def property_search_work_lease_seconds() -> int:
    return _env_int(
        "PROPERTYQUARRY_SEARCH_WORK_LEASE_SECONDS",
        300,
        minimum=30,
        maximum=3600,
    )


def property_search_work_heartbeat_seconds() -> int:
    configured = _env_int(
        "PROPERTYQUARRY_SEARCH_WORK_HEARTBEAT_SECONDS",
        30,
        minimum=5,
        maximum=300,
    )
    return min(configured, max(5, property_search_work_lease_seconds() // 3))


def property_search_work_max_attempts() -> int:
    return _env_int(
        "PROPERTYQUARRY_SEARCH_WORK_MAX_ATTEMPTS",
        3,
        minimum=1,
        maximum=10,
    )


def property_search_work_backoff_seconds(attempt_count: int) -> int:
    base = _env_int(
        "PROPERTYQUARRY_SEARCH_WORK_BACKOFF_BASE_SECONDS",
        15,
        minimum=1,
        maximum=3600,
    )
    maximum = _env_int(
        "PROPERTYQUARRY_SEARCH_WORK_BACKOFF_MAX_SECONDS",
        300,
        minimum=base,
        maximum=86400,
    )
    exponent = max(0, int(attempt_count or 0) - 1)
    return min(maximum, base * (2**exponent))


def property_search_work_idempotency_key(
    *,
    principal_id: str,
    run_id: str,
    requested_key: str = "",
) -> str:
    normalized_principal = str(principal_id or "").strip()
    normalized_run = str(run_id or "").strip()
    normalized_requested = str(requested_key or "").strip()
    source = (
        f"request\0{normalized_principal}\0{normalized_requested}"
        if normalized_requested
        else f"run\0{normalized_principal}\0{normalized_run}"
    )
    return "property-search:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PropertySearchWorkJob:
    job_id: str
    principal_id: str
    run_id: str
    idempotency_key: str
    payload_json: dict[str, object]
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_owner: str = ""
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {"completed", "failed"}


@dataclass(frozen=True)
class PropertySearchWorkEnqueueResult:
    job: PropertySearchWorkJob
    created: bool


class InMemoryPropertySearchWorkQueue:
    """Deterministic development/test implementation of the lease state machine."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utc_now,
        backoff_seconds: Callable[[int], int] = property_search_work_backoff_seconds,
    ) -> None:
        self._now = now
        self._backoff_seconds = backoff_seconds
        self._lock = threading.Lock()
        self._jobs: dict[str, PropertySearchWorkJob] = {}
        self._idempotency: dict[str, str] = {}
        self._runs: dict[tuple[str, str], str] = {}

    def enqueue_run(
        self,
        *,
        run_record: dict[str, object],
        payload_json: dict[str, object],
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> PropertySearchWorkEnqueueResult:
        principal_id = str(run_record.get("principal_id") or "").strip()
        run_id = str(run_record.get("run_id") or "").strip()
        if not principal_id or not run_id or not str(idempotency_key or "").strip():
            raise ValueError("property_search_work_identity_required")
        now = self._now()
        with self._lock:
            existing_id = self._idempotency.get(idempotency_key) or self._runs.get((principal_id, run_id))
            if existing_id:
                return PropertySearchWorkEnqueueResult(job=self._jobs[existing_id], created=False)
            job = PropertySearchWorkJob(
                job_id=uuid4().hex,
                principal_id=principal_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
                payload_json=dict(payload_json or {}),
                status="queued",
                attempt_count=0,
                max_attempts=max(1, int(max_attempts or 1)),
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.job_id] = job
            self._idempotency[idempotency_key] = job.job_id
            self._runs[(principal_id, run_id)] = job.job_id
            return PropertySearchWorkEnqueueResult(job=job, created=True)

    def claim(self, *, lease_owner: str, lease_seconds: int) -> PropertySearchWorkJob | None:
        owner = str(lease_owner or "").strip()
        if not owner:
            raise ValueError("property_search_work_lease_owner_required")
        now = self._now()
        with self._lock:
            for job_id, job in tuple(self._jobs.items()):
                if (
                    job.status == "leased"
                    and job.lease_expires_at is not None
                    and job.lease_expires_at <= now
                    and job.attempt_count >= job.max_attempts
                ):
                    self._jobs[job_id] = replace(
                        job,
                        status="failed",
                        lease_owner="",
                        lease_expires_at=None,
                        last_error=job.last_error or "lease_expired_after_max_attempts",
                        updated_at=now,
                        completed_at=now,
                    )
            candidates = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if (
                        (job.status == "queued" and job.available_at <= now)
                        or (
                            job.status == "leased"
                            and job.lease_expires_at is not None
                            and job.lease_expires_at <= now
                            and job.attempt_count < job.max_attempts
                        )
                    )
                ),
                key=lambda item: (item.available_at, item.created_at or item.available_at, item.job_id),
            )
            if not candidates:
                return None
            found = candidates[0]
            claimed = replace(
                found,
                status="leased",
                attempt_count=found.attempt_count + 1,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=max(1, int(lease_seconds or 1))),
                heartbeat_at=now,
                updated_at=now,
            )
            self._jobs[claimed.job_id] = claimed
            return claimed

    def heartbeat(self, *, job_id: str, lease_owner: str, lease_seconds: int) -> bool:
        now = self._now()
        with self._lock:
            found = self._jobs.get(str(job_id or ""))
            if (
                found is None
                or found.status != "leased"
                or found.lease_owner != str(lease_owner or "").strip()
                or found.lease_expires_at is None
                or found.lease_expires_at <= now
            ):
                return False
            self._jobs[found.job_id] = replace(
                found,
                lease_expires_at=now + timedelta(seconds=max(1, int(lease_seconds or 1))),
                heartbeat_at=now,
                updated_at=now,
            )
            return True

    def complete(self, *, job_id: str, lease_owner: str) -> PropertySearchWorkJob | None:
        now = self._now()
        with self._lock:
            found = self._jobs.get(str(job_id or ""))
            if found is None or found.status != "leased" or found.lease_owner != str(lease_owner or "").strip():
                return None
            completed = replace(
                found,
                status="completed",
                lease_owner="",
                lease_expires_at=None,
                heartbeat_at=now,
                updated_at=now,
                completed_at=now,
            )
            self._jobs[completed.job_id] = completed
            return completed

    def fail(self, *, job_id: str, lease_owner: str, error: str) -> PropertySearchWorkJob | None:
        now = self._now()
        with self._lock:
            found = self._jobs.get(str(job_id or ""))
            if found is None or found.status != "leased" or found.lease_owner != str(lease_owner or "").strip():
                return None
            terminal = found.attempt_count >= found.max_attempts
            failed = replace(
                found,
                status="failed" if terminal else "queued",
                available_at=(
                    now
                    if terminal
                    else now + timedelta(seconds=max(0, int(self._backoff_seconds(found.attempt_count))))
                ),
                lease_owner="",
                lease_expires_at=None,
                last_error=str(error or "property search work failed")[:2000],
                updated_at=now,
                completed_at=now if terminal else None,
            )
            self._jobs[failed.job_id] = failed
            return failed

    def get(self, job_id: str) -> PropertySearchWorkJob | None:
        with self._lock:
            return self._jobs.get(str(job_id or ""))

    def list_jobs(self) -> tuple[PropertySearchWorkJob, ...]:
        with self._lock:
            return tuple(self._jobs.values())


class PostgresPropertySearchWorkQueue:
    _RETURNING_COLUMNS = """
        job_id, principal_id, run_id, idempotency_key, payload_json, status,
        attempt_count, max_attempts, available_at, lease_owner, lease_expires_at,
        heartbeat_at, last_error, created_at, updated_at, completed_at
    """
    _RETURNING_JOB_COLUMNS = """
        jobs.job_id, jobs.principal_id, jobs.run_id, jobs.idempotency_key, jobs.payload_json, jobs.status,
        jobs.attempt_count, jobs.max_attempts, jobs.available_at, jobs.lease_owner, jobs.lease_expires_at,
        jobs.heartbeat_at, jobs.last_error, jobs.created_at, jobs.updated_at, jobs.completed_at
    """

    def __init__(
        self,
        database_url: str,
        *,
        backoff_seconds: Callable[[int], int] = property_search_work_backoff_seconds,
    ) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url_required")
        self._backoff_seconds = backoff_seconds
        from app.product.property_search_schema import require_property_search_schema_ready

        require_property_search_schema_ready(self._database_url)

    def _connect(self):  # type: ignore[no-untyped-def]
        import psycopg

        return psycopg.connect(self._database_url, autocommit=False, connect_timeout=5)

    @staticmethod
    def _from_row(row) -> PropertySearchWorkJob:  # type: ignore[no-untyped-def]
        return PropertySearchWorkJob(
            job_id=str(row[0] or ""),
            principal_id=str(row[1] or ""),
            run_id=str(row[2] or ""),
            idempotency_key=str(row[3] or ""),
            payload_json=dict(row[4] or {}),
            status=str(row[5] or ""),
            attempt_count=int(row[6] or 0),
            max_attempts=int(row[7] or 1),
            available_at=_aware_utc(row[8]) or _utc_now(),
            lease_owner=str(row[9] or ""),
            lease_expires_at=_aware_utc(row[10]),
            heartbeat_at=_aware_utc(row[11]),
            last_error=str(row[12] or ""),
            created_at=_aware_utc(row[13]),
            updated_at=_aware_utc(row[14]),
            completed_at=_aware_utc(row[15]),
        )

    def enqueue_run(
        self,
        *,
        run_record: dict[str, object],
        payload_json: dict[str, object],
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> PropertySearchWorkEnqueueResult:
        from psycopg.types.json import Json

        from app.product.property_search_storage import (
            _compact_property_search_run_record,
            _property_search_run_canonicalize_record,
        )

        normalized = _property_search_run_canonicalize_record(dict(run_record or {}))
        principal_id = str(normalized.get("principal_id") or "").strip()
        run_id = str(normalized.get("run_id") or "").strip()
        key = str(idempotency_key or "").strip()
        if not principal_id or not run_id or not key:
            raise ValueError("property_search_work_identity_required")
        compact = _compact_property_search_run_record(normalized)
        inserted_run = False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_search_runs
                        (principal_id, run_id, payload_json, status, compact_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING run_id
                    """,
                    (
                        principal_id,
                        run_id,
                        Json(normalized),
                        str(compact.get("status") or "").strip() or None,
                        Json(compact),
                        str(normalized.get("created_at") or _utc_now().isoformat()),
                        str(normalized.get("updated_at") or _utc_now().isoformat()),
                    ),
                )
                inserted_run = cur.fetchone() is not None
                cur.execute(
                    f"""
                    INSERT INTO property_search_work_jobs
                        (job_id, principal_id, run_id, idempotency_key, payload_json, status,
                         attempt_count, max_attempts, available_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'queued', 0, %s, NOW(), NOW(), NOW())
                    ON CONFLICT DO NOTHING
                    RETURNING {self._RETURNING_COLUMNS}
                    """,
                    (
                        uuid4().hex,
                        principal_id,
                        run_id,
                        key,
                        Json(dict(payload_json or {})),
                        max(1, int(max_attempts or 1)),
                    ),
                )
                row = cur.fetchone()
                created = row is not None
                if row is None:
                    cur.execute(
                        f"""
                        SELECT {self._RETURNING_COLUMNS}
                        FROM property_search_work_jobs
                        WHERE idempotency_key = %s OR (principal_id = %s AND run_id = %s)
                        ORDER BY (idempotency_key = %s) DESC
                        LIMIT 1
                        """,
                        (key, principal_id, run_id, key),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError("property_search_work_enqueue_conflict_unresolved")
                    if inserted_run and str(row[2] or "") != run_id:
                        cur.execute(
                            """
                            DELETE FROM property_search_runs AS runs
                            WHERE runs.principal_id = %s AND runs.run_id = %s
                              AND NOT EXISTS (
                                  SELECT 1 FROM property_search_work_jobs AS jobs
                                  WHERE jobs.principal_id = runs.principal_id AND jobs.run_id = runs.run_id
                              )
                            """,
                            (principal_id, run_id),
                        )
                conn.commit()
        return PropertySearchWorkEnqueueResult(job=self._from_row(row), created=created)

    def claim(self, *, lease_owner: str, lease_seconds: int) -> PropertySearchWorkJob | None:
        owner = str(lease_owner or "").strip()
        if not owner:
            raise ValueError("property_search_work_lease_owner_required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE property_search_work_jobs
                    SET status = 'failed',
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        last_error = COALESCE(NULLIF(last_error, ''), 'lease_expired_after_max_attempts'),
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE status = 'leased'
                      AND lease_expires_at <= NOW()
                      AND attempt_count >= max_attempts
                    """
                )
                cur.execute(
                    f"""
                    WITH candidate AS (
                        SELECT job_id
                        FROM property_search_work_jobs
                        WHERE (
                            (status = 'queued' AND available_at <= NOW())
                            OR (
                                status = 'leased'
                                AND lease_expires_at <= NOW()
                                AND attempt_count < max_attempts
                            )
                        )
                        ORDER BY available_at ASC, created_at ASC, job_id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE property_search_work_jobs AS jobs
                    SET status = 'leased',
                        attempt_count = jobs.attempt_count + 1,
                        lease_owner = %s,
                        lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                        heartbeat_at = NOW(),
                        updated_at = NOW()
                    FROM candidate
                    WHERE jobs.job_id = candidate.job_id
                    RETURNING {self._RETURNING_JOB_COLUMNS}
                    """,
                    (owner, max(1, int(lease_seconds or 1))),
                )
                row = cur.fetchone()
                conn.commit()
        return self._from_row(row) if row is not None else None

    def heartbeat(self, *, job_id: str, lease_owner: str, lease_seconds: int) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE property_search_work_jobs
                    SET heartbeat_at = NOW(),
                        lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                        updated_at = NOW()
                    WHERE job_id = %s
                      AND status = 'leased'
                      AND lease_owner = %s
                      AND lease_expires_at > NOW()
                    """,
                    (max(1, int(lease_seconds or 1)), str(job_id or ""), str(lease_owner or "").strip()),
                )
                changed = cur.rowcount == 1
                conn.commit()
        return changed

    def complete(self, *, job_id: str, lease_owner: str) -> PropertySearchWorkJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE property_search_work_jobs
                    SET status = 'completed',
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NOW(),
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE job_id = %s AND status = 'leased' AND lease_owner = %s
                    RETURNING {self._RETURNING_COLUMNS}
                    """,
                    (str(job_id or ""), str(lease_owner or "").strip()),
                )
                row = cur.fetchone()
                conn.commit()
        return self._from_row(row) if row is not None else None

    def fail(self, *, job_id: str, lease_owner: str, error: str) -> PropertySearchWorkJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT attempt_count, max_attempts
                    FROM property_search_work_jobs
                    WHERE job_id = %s AND status = 'leased' AND lease_owner = %s
                    FOR UPDATE
                    """,
                    (str(job_id or ""), str(lease_owner or "").strip()),
                )
                attempts_row = cur.fetchone()
                if attempts_row is None:
                    conn.commit()
                    return None
                attempt_count = int(attempts_row[0] or 0)
                max_attempts = int(attempts_row[1] or 1)
                terminal = attempt_count >= max_attempts
                delay_seconds = 0 if terminal else max(0, int(self._backoff_seconds(attempt_count)))
                cur.execute(
                    f"""
                    UPDATE property_search_work_jobs
                    SET status = %s,
                        available_at = NOW() + (%s * INTERVAL '1 second'),
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        last_error = %s,
                        completed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                        updated_at = NOW()
                    WHERE job_id = %s AND status = 'leased' AND lease_owner = %s
                    RETURNING {self._RETURNING_COLUMNS}
                    """,
                    (
                        "failed" if terminal else "queued",
                        delay_seconds,
                        str(error or "property search work failed")[:2000],
                        terminal,
                        str(job_id or ""),
                        str(lease_owner or "").strip(),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
        return self._from_row(row) if row is not None else None

    def get(self, job_id: str) -> PropertySearchWorkJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {self._RETURNING_COLUMNS} FROM property_search_work_jobs WHERE job_id = %s",
                    (str(job_id or ""),),
                )
                row = cur.fetchone()
        return self._from_row(row) if row is not None else None
