from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import Entity, now_utc_iso


class EntityRepository(Protocol):
    def upsert_entity(
        self,
        *,
        principal_id: str,
        entity_type: str,
        canonical_name: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        status: str = "active",
    ) -> Entity:
        ...

    def get(self, entity_id: str) -> Entity | None:
        ...

    def list_entities(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        entity_type: str | None = None,
    ) -> list[Entity]:
        ...



def _clamp_confidence(value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.5
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


class InMemoryEntityRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, Entity] = {}
        self._order: List[str] = []
        self._identity_to_id: Dict[str, str] = {}

    def _identity(self, *, principal_id: str, entity_type: str, canonical_name: str) -> str:
        return "::".join(
            [
                str(principal_id or "").strip(),
                str(entity_type or "").strip().lower(),
                str(canonical_name or "").strip().lower(),
            ]
        )

    def upsert_entity(
        self,
        *,
        principal_id: str,
        entity_type: str,
        canonical_name: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        status: str = "active",
    ) -> Entity:
        identity = self._identity(
            principal_id=principal_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
        )
        ts = now_utc_iso()
        found_id = self._identity_to_id.get(identity)
        if found_id and found_id in self._rows:
            existing = self._rows[found_id]
            updated = Entity(
                entity_id=existing.entity_id,
                principal_id=existing.principal_id,
                entity_type=existing.entity_type,
                canonical_name=existing.canonical_name,
                attributes_json=dict(attributes_json or {}),
                confidence=_clamp_confidence(confidence),
                status=str(status or existing.status).strip() or existing.status,
                created_at=existing.created_at,
                updated_at=ts,
            )
            self._rows[found_id] = updated
            return updated
        row = Entity(
            entity_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            entity_type=str(entity_type or "unknown").strip() or "unknown",
            canonical_name=str(canonical_name or "").strip(),
            attributes_json=dict(attributes_json or {}),
            confidence=_clamp_confidence(confidence),
            status=str(status or "active").strip() or "active",
            created_at=ts,
            updated_at=ts,
        )
        self._rows[row.entity_id] = row
        self._order.append(row.entity_id)
        self._identity_to_id[identity] = row.entity_id
        return row

    def get(self, entity_id: str) -> Entity | None:
        return self._rows.get(str(entity_id or ""))

    def list_entities(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        entity_type: str | None = None,
    ) -> list[Entity]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        type_filter = str(entity_type or "").strip().lower()
        rows = [self._rows[eid] for eid in reversed(self._order) if eid in self._rows]
        if principal_filter:
            rows = [row for row in rows if row.principal_id == principal_filter]
        if type_filter:
            rows = [row for row in rows if row.entity_type.lower() == type_filter]
        return rows[:n]
