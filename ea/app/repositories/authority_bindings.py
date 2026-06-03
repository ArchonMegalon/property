from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import AuthorityBinding, now_utc_iso


class AuthorityBindingRepository(Protocol):
    def upsert_binding(
        self,
        *,
        principal_id: str,
        subject_ref: str,
        action_scope: str,
        approval_level: str = "manager",
        channel_scope: tuple[str, ...] = (),
        policy_json: dict[str, object] | None = None,
        status: str = "active",
        binding_id: str | None = None,
    ) -> AuthorityBinding:
        ...

    def get(self, binding_id: str) -> AuthorityBinding | None:
        ...

    def list_bindings(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[AuthorityBinding]:
        ...



def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "disabled"}:
        return raw
    return "active"


class InMemoryAuthorityBindingRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, AuthorityBinding] = {}
        self._order: List[str] = []
        self._identity_to_id: Dict[str, str] = {}

    def _identity(self, *, principal_id: str, subject_ref: str, action_scope: str) -> str:
        return "::".join(
            [
                str(principal_id or "").strip(),
                str(subject_ref or "").strip().lower(),
                str(action_scope or "").strip().lower(),
            ]
        )

    def upsert_binding(
        self,
        *,
        principal_id: str,
        subject_ref: str,
        action_scope: str,
        approval_level: str = "manager",
        channel_scope: tuple[str, ...] = (),
        policy_json: dict[str, object] | None = None,
        status: str = "active",
        binding_id: str | None = None,
    ) -> AuthorityBinding:
        now = now_utc_iso()
        candidate_id = str(binding_id or "").strip()
        existing = self._rows.get(candidate_id) if candidate_id else None
        identity = self._identity(principal_id=principal_id, subject_ref=subject_ref, action_scope=action_scope)
        if not existing:
            found_id = self._identity_to_id.get(identity)
            if found_id:
                existing = self._rows.get(found_id)
        if existing:
            updated = AuthorityBinding(
                binding_id=existing.binding_id,
                principal_id=existing.principal_id,
                subject_ref=existing.subject_ref,
                action_scope=existing.action_scope,
                approval_level=str(approval_level or existing.approval_level).strip() or existing.approval_level,
                channel_scope=tuple(str(v) for v in (channel_scope or existing.channel_scope)),
                policy_json=dict(policy_json or {}),
                status=_normalize_status(status),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.binding_id] = updated
            self._identity_to_id[identity] = existing.binding_id
            return updated
        row = AuthorityBinding(
            binding_id=candidate_id or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            subject_ref=str(subject_ref or "").strip(),
            action_scope=str(action_scope or "").strip(),
            approval_level=str(approval_level or "manager").strip() or "manager",
            channel_scope=tuple(str(v) for v in channel_scope),
            policy_json=dict(policy_json or {}),
            status=_normalize_status(status),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.binding_id] = row
        self._order.append(row.binding_id)
        self._identity_to_id[identity] = row.binding_id
        return row

    def get(self, binding_id: str) -> AuthorityBinding | None:
        return self._rows.get(str(binding_id or ""))

    def list_bindings(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[AuthorityBinding]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[bid] for bid in reversed(self._order) if bid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
