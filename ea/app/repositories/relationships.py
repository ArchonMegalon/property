from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import RelationshipEdge, now_utc_iso


class RelationshipRepository(Protocol):
    def upsert_relationship(
        self,
        *,
        principal_id: str,
        from_entity_id: str,
        to_entity_id: str,
        relationship_type: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> RelationshipEdge:
        ...

    def get(self, relationship_id: str) -> RelationshipEdge | None:
        ...

    def list_relationships(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        from_entity_id: str | None = None,
        to_entity_id: str | None = None,
        relationship_type: str | None = None,
    ) -> list[RelationshipEdge]:
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


class InMemoryRelationshipRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, RelationshipEdge] = {}
        self._order: List[str] = []
        self._identity_to_id: Dict[str, str] = {}

    def _identity(
        self,
        *,
        principal_id: str,
        from_entity_id: str,
        to_entity_id: str,
        relationship_type: str,
    ) -> str:
        return "::".join(
            [
                str(principal_id or "").strip(),
                str(from_entity_id or "").strip(),
                str(to_entity_id or "").strip(),
                str(relationship_type or "").strip().lower(),
            ]
        )

    def upsert_relationship(
        self,
        *,
        principal_id: str,
        from_entity_id: str,
        to_entity_id: str,
        relationship_type: str,
        attributes_json: dict[str, object] | None = None,
        confidence: float = 0.5,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> RelationshipEdge:
        identity = self._identity(
            principal_id=principal_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relationship_type=relationship_type,
        )
        ts = now_utc_iso()
        found_id = self._identity_to_id.get(identity)
        if found_id and found_id in self._rows:
            existing = self._rows[found_id]
            updated = RelationshipEdge(
                relationship_id=existing.relationship_id,
                principal_id=existing.principal_id,
                from_entity_id=existing.from_entity_id,
                to_entity_id=existing.to_entity_id,
                relationship_type=existing.relationship_type,
                attributes_json=dict(attributes_json or {}),
                confidence=_clamp_confidence(confidence),
                valid_from=str(valid_from or existing.valid_from or "") or None,
                valid_to=str(valid_to or existing.valid_to or "") or None,
                created_at=existing.created_at,
                updated_at=ts,
            )
            self._rows[found_id] = updated
            return updated
        row = RelationshipEdge(
            relationship_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            from_entity_id=str(from_entity_id or "").strip(),
            to_entity_id=str(to_entity_id or "").strip(),
            relationship_type=str(relationship_type or "unknown").strip() or "unknown",
            attributes_json=dict(attributes_json or {}),
            confidence=_clamp_confidence(confidence),
            valid_from=str(valid_from or "").strip() or None,
            valid_to=str(valid_to or "").strip() or None,
            created_at=ts,
            updated_at=ts,
        )
        self._rows[row.relationship_id] = row
        self._order.append(row.relationship_id)
        self._identity_to_id[identity] = row.relationship_id
        return row

    def get(self, relationship_id: str) -> RelationshipEdge | None:
        return self._rows.get(str(relationship_id or ""))

    def list_relationships(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        from_entity_id: str | None = None,
        to_entity_id: str | None = None,
        relationship_type: str | None = None,
    ) -> list[RelationshipEdge]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        from_filter = str(from_entity_id or "").strip()
        to_filter = str(to_entity_id or "").strip()
        rel_filter = str(relationship_type or "").strip().lower()
        rows = [self._rows[rid] for rid in reversed(self._order) if rid in self._rows]
        if principal_filter:
            rows = [row for row in rows if row.principal_id == principal_filter]
        if from_filter:
            rows = [row for row in rows if row.from_entity_id == from_filter]
        if to_filter:
            rows = [row for row in rows if row.to_entity_id == to_filter]
        if rel_filter:
            rows = [row for row in rows if row.relationship_type.lower() == rel_filter]
        return rows[:n]
