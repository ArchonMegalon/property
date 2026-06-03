from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import CommunicationPolicy, now_utc_iso


class CommunicationPolicyRepository(Protocol):
    def upsert_policy(
        self,
        *,
        principal_id: str,
        scope: str,
        preferred_channel: str = "",
        tone: str = "neutral",
        max_length: int = 1200,
        quiet_hours_json: dict[str, object] | None = None,
        escalation_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        policy_id: str | None = None,
    ) -> CommunicationPolicy:
        ...

    def get(self, policy_id: str) -> CommunicationPolicy | None:
        ...

    def list_policies(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[CommunicationPolicy]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class InMemoryCommunicationPolicyRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, CommunicationPolicy] = {}
        self._order: List[str] = []

    def upsert_policy(
        self,
        *,
        principal_id: str,
        scope: str,
        preferred_channel: str = "",
        tone: str = "neutral",
        max_length: int = 1200,
        quiet_hours_json: dict[str, object] | None = None,
        escalation_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        policy_id: str | None = None,
    ) -> CommunicationPolicy:
        now = now_utc_iso()
        key = str(policy_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = CommunicationPolicy(
                policy_id=existing.policy_id,
                principal_id=existing.principal_id,
                scope=str(scope or existing.scope).strip() or existing.scope,
                preferred_channel=str(preferred_channel or existing.preferred_channel).strip(),
                tone=str(tone or existing.tone).strip() or existing.tone,
                max_length=max(1, int(max_length or existing.max_length)),
                quiet_hours_json=dict(quiet_hours_json or {}),
                escalation_json=dict(escalation_json or {}),
                status=_normalize_status(status),
                notes=str(notes or "").strip(),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.policy_id] = updated
            return updated
        row = CommunicationPolicy(
            policy_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            scope=str(scope or "").strip(),
            preferred_channel=str(preferred_channel or "").strip(),
            tone=str(tone or "neutral").strip() or "neutral",
            max_length=max(1, int(max_length or 1200)),
            quiet_hours_json=dict(quiet_hours_json or {}),
            escalation_json=dict(escalation_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.policy_id] = row
        self._order.append(row.policy_id)
        return row

    def get(self, policy_id: str) -> CommunicationPolicy | None:
        return self._rows.get(str(policy_id or ""))

    def list_policies(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[CommunicationPolicy]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[pid] for pid in reversed(self._order) if pid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
