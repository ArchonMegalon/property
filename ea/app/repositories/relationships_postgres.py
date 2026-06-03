from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import RelationshipEdge, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


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


class PostgresRelationshipRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresRelationshipRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres relationship backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS relationships (
                        relationship_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        from_entity_id TEXT NOT NULL,
                        to_entity_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        attributes_json JSONB NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        valid_from TIMESTAMPTZ NULL,
                        valid_to TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE relationships ADD COLUMN IF NOT EXISTS attributes_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE relationships ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5"
                )
                cur.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ NULL")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_identity_unique
                    ON relationships(principal_id, from_entity_id, to_entity_id, relationship_type)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_relationships_principal_updated
                    ON relationships(principal_id, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_relationships_from_to
                    ON relationships(from_entity_id, to_entity_id, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> RelationshipEdge:
        (
            relationship_id,
            principal_id,
            from_entity_id,
            to_entity_id,
            relationship_type,
            attributes_json,
            confidence,
            valid_from,
            valid_to,
            created_at,
            updated_at,
        ) = row
        return RelationshipEdge(
            relationship_id=str(relationship_id),
            principal_id=str(principal_id),
            from_entity_id=str(from_entity_id),
            to_entity_id=str(to_entity_id),
            relationship_type=str(relationship_type),
            attributes_json=dict(attributes_json or {}),
            confidence=float(confidence or 0.0),
            valid_from=_to_iso(valid_from) if valid_from else None,
            valid_to=_to_iso(valid_to) if valid_to else None,
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
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
        ts = now_utc_iso()
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO relationships
                    (relationship_id, principal_id, from_entity_id, to_entity_id, relationship_type,
                     attributes_json, confidence, valid_from, valid_to, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, from_entity_id, to_entity_id, relationship_type) DO UPDATE
                    SET attributes_json = EXCLUDED.attributes_json,
                        confidence = EXCLUDED.confidence,
                        valid_from = EXCLUDED.valid_from,
                        valid_to = EXCLUDED.valid_to,
                        updated_at = EXCLUDED.updated_at
                    RETURNING relationship_id, principal_id, from_entity_id, to_entity_id, relationship_type,
                              attributes_json, confidence, valid_from, valid_to, created_at, updated_at
                    """,
                    (
                        row.relationship_id,
                        row.principal_id,
                        row.from_entity_id,
                        row.to_entity_id,
                        row.relationship_type,
                        self._json_value(row.attributes_json),
                        row.confidence,
                        row.valid_from,
                        row.valid_to,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, relationship_id: str) -> RelationshipEdge | None:
        key = str(relationship_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT relationship_id, principal_id, from_entity_id, to_entity_id, relationship_type,
                           attributes_json, confidence, valid_from, valid_to, created_at, updated_at
                    FROM relationships
                    WHERE relationship_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

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
        type_filter = str(relationship_type or "").strip()
        where: list[str] = []
        params: list[object] = []
        if principal_filter:
            where.append("principal_id = %s")
            params.append(principal_filter)
        if from_filter:
            where.append("from_entity_id = %s")
            params.append(from_filter)
        if to_filter:
            where.append("to_entity_id = %s")
            params.append(to_filter)
        if type_filter:
            where.append("relationship_type = %s")
            params.append(type_filter)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT relationship_id, principal_id, from_entity_id, to_entity_id, relationship_type, "
            "attributes_json, confidence, valid_from, valid_to, created_at, updated_at "
            "FROM relationships "
            f"{where_sql} "
            "ORDER BY updated_at DESC, relationship_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
