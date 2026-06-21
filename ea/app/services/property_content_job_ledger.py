from __future__ import annotations

import json
import os
from pathlib import Path

from app.domain.property.content_source_packet import canonical_json, now_utc_iso, sha256_json


def default_subscribr_completion_dir() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_SUBSCRIBR_COMPLETION_DIR") or "_completion/subscribr")


def default_property_content_ledger_path() -> Path:
    explicit = str(os.getenv("PROPERTYQUARRY_CONTENT_JOB_LEDGER") or "").strip()
    if explicit:
        return Path(explicit)
    return default_subscribr_completion_dir() / "property_content_jobs.json"


class PropertyContentJobLedger:
    def __init__(self, *, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else default_property_content_ledger_path()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, object]:
        if not self._path.exists():
            return {"contract_name": "propertyquarry.content_job_ledger.v1", "jobs": {}, "webhook_events": {}}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"contract_name": "propertyquarry.content_job_ledger.v1", "jobs": {}, "webhook_events": {}}
        return parsed if isinstance(parsed, dict) else {"contract_name": "propertyquarry.content_job_ledger.v1", "jobs": {}, "webhook_events": {}}

    def _write(self, payload: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def get_job(self, packet_id: str) -> dict[str, object] | None:
        data = self._load()
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        row = jobs.get(str(packet_id))
        return dict(row) if isinstance(row, dict) else None

    def upsert_job(self, packet: dict[str, object], *, status: str, extra: dict[str, object] | None = None) -> dict[str, object]:
        packet_id = str(packet.get("packet_id") or "").strip()
        if not packet_id:
            raise ValueError("property_content_packet_id_required")
        data = self._load()
        jobs = data.setdefault("jobs", {})
        if not isinstance(jobs, dict):
            jobs = {}
            data["jobs"] = jobs
        current = dict(jobs.get(packet_id) or {})
        created_at = str(current.get("created_at") or now_utc_iso())
        row = {
            **current,
            "packet_id": packet_id,
            "content_mode": str(packet.get("content_mode") or ""),
            "channel_key": str(packet.get("subscribr_channel_key") or ""),
            "source_packet_json": packet,
            "source_packet_sha256": str(packet.get("source_packet_sha256") or ""),
            "source_packet_canonical_sha256": sha256_json(packet),
            "status": status,
            "updated_at": now_utc_iso(),
            "created_at": created_at,
            "production_allowed": False,
            "publication_allowed": False,
        }
        if extra:
            row.update(extra)
        jobs[packet_id] = row
        self._write(data)
        return row

    def record_provider_ids(
        self,
        *,
        packet_id: str,
        provider_channel_id: object = "",
        provider_idea_id: object = "",
        provider_script_id: object = "",
        status: str = "PROVIDER_JOB_CREATED",
    ) -> dict[str, object]:
        current = self.get_job(packet_id)
        if not current:
            raise ValueError("property_content_job_not_found")
        data = self._load()
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        row = dict(jobs.get(packet_id) or current)
        row.update(
            {
                "provider": "subscribr",
                "provider_channel_id": str(provider_channel_id or row.get("provider_channel_id") or ""),
                "provider_idea_id": str(provider_idea_id or row.get("provider_idea_id") or ""),
                "provider_script_id": str(provider_script_id or row.get("provider_script_id") or ""),
                "status": status,
                "updated_at": now_utc_iso(),
            }
        )
        jobs[packet_id] = row
        data["jobs"] = jobs
        self._write(data)
        return row

    def webhook_seen(self, event_id: str) -> bool:
        data = self._load()
        events = data.get("webhook_events") if isinstance(data.get("webhook_events"), dict) else {}
        return str(event_id or "") in events

    def record_webhook_event(
        self,
        *,
        event_id: str,
        payload: dict[str, object],
        status: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        event_ref = str(event_id or "").strip()
        if not event_ref:
            raise ValueError("subscribr_webhook_event_id_required")
        data = self._load()
        events = data.setdefault("webhook_events", {})
        if not isinstance(events, dict):
            events = {}
            data["webhook_events"] = events
        if event_ref in events:
            row = dict(events[event_ref])
            row["replayed_at"] = now_utc_iso()
            events[event_ref] = row
            self._write(data)
            return row
        row = {
            "event_id": event_ref,
            "status": status,
            "received_at": now_utc_iso(),
            "event_type": str(payload.get("type") or payload.get("event") or payload.get("event_type") or ""),
            "payload_sha256": sha256_json(payload),
        }
        if extra:
            row.update(extra)
        events[event_ref] = row
        self._write(data)
        return row

    def write_receipt(self, *, packet_id: str, receipt: dict[str, object]) -> Path:
        safe_packet = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(packet_id or "").strip())[:180]
        if not safe_packet:
            raise ValueError("property_content_packet_id_required")
        path = default_subscribr_completion_dir() / f"propertyquarry_{safe_packet}.generated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(receipt), encoding="utf-8")
        return path
