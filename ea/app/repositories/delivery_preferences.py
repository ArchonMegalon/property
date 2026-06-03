from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import DeliveryPreference, now_utc_iso


class DeliveryPreferenceRepository(Protocol):
    def upsert_preference(
        self,
        *,
        principal_id: str,
        channel: str,
        recipient_ref: str,
        cadence: str = "normal",
        quiet_hours_json: dict[str, object] | None = None,
        format_json: dict[str, object] | None = None,
        status: str = "active",
        preference_id: str | None = None,
    ) -> DeliveryPreference:
        ...

    def get(self, preference_id: str) -> DeliveryPreference | None:
        ...

    def list_preferences(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeliveryPreference]:
        ...



def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "disabled"}:
        return raw
    return "active"


class InMemoryDeliveryPreferenceRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, DeliveryPreference] = {}
        self._order: List[str] = []
        self._identity_to_id: Dict[str, str] = {}

    def _identity(self, *, principal_id: str, channel: str, recipient_ref: str) -> str:
        return "::".join(
            [
                str(principal_id or "").strip(),
                str(channel or "").strip().lower(),
                str(recipient_ref or "").strip().lower(),
            ]
        )

    def upsert_preference(
        self,
        *,
        principal_id: str,
        channel: str,
        recipient_ref: str,
        cadence: str = "normal",
        quiet_hours_json: dict[str, object] | None = None,
        format_json: dict[str, object] | None = None,
        status: str = "active",
        preference_id: str | None = None,
    ) -> DeliveryPreference:
        now = now_utc_iso()
        candidate_id = str(preference_id or "").strip()
        existing = self._rows.get(candidate_id) if candidate_id else None
        identity = self._identity(principal_id=principal_id, channel=channel, recipient_ref=recipient_ref)
        if not existing:
            found_id = self._identity_to_id.get(identity)
            if found_id:
                existing = self._rows.get(found_id)
        if existing:
            updated = DeliveryPreference(
                preference_id=existing.preference_id,
                principal_id=existing.principal_id,
                channel=existing.channel,
                recipient_ref=existing.recipient_ref,
                cadence=str(cadence or existing.cadence).strip() or existing.cadence,
                quiet_hours_json=dict(quiet_hours_json or {}),
                format_json=dict(format_json or {}),
                status=_normalize_status(status),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.preference_id] = updated
            self._identity_to_id[identity] = existing.preference_id
            return updated
        row = DeliveryPreference(
            preference_id=candidate_id or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            channel=str(channel or "").strip(),
            recipient_ref=str(recipient_ref or "").strip(),
            cadence=str(cadence or "normal").strip() or "normal",
            quiet_hours_json=dict(quiet_hours_json or {}),
            format_json=dict(format_json or {}),
            status=_normalize_status(status),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.preference_id] = row
        self._order.append(row.preference_id)
        self._identity_to_id[identity] = row.preference_id
        return row

    def get(self, preference_id: str) -> DeliveryPreference | None:
        return self._rows.get(str(preference_id or ""))

    def list_preferences(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeliveryPreference]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[pid] for pid in reversed(self._order) if pid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
