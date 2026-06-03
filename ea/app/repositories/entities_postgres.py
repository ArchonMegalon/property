from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import Entity, now_utc_iso


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


class PostgresEntityRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresEntityRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres entity backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS entities (
                        entity_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        canonical_name TEXT NOT NULL,
                        attributes_json JSONB NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS attributes_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5"
                )
                cur.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_identity_unique
                    ON entities(principal_id, entity_type, lower(canonical_name))
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_entities_principal_updated
                    ON entities(principal_id, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> Entity:
        (
            entity_id,
            principal_id,
            entity_type,
            canonical_name,
            attributes_json,
            confidence,
            status,
            created_at,
            updated_at,
        ) = row
        return Entity(
            entity_id=str(entity_id),
            principal_id=str(principal_id),
            entity_type=str(entity_type),
            canonical_name=str(canonical_name),
            attributes_json=dict(attributes_json or {}),
            confidence=float(confidence or 0.0),
            status=str(status or "active"),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
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
        ts = now_utc_iso()
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO entities
                    (entity_id, principal_id, entity_type, canonical_name, attributes_json,
                     confidence, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, entity_type, lower(canonical_name)) DO UPDATE
                    SET attributes_json = EXCLUDED.attributes_json,
                        confidence = EXCLUDED.confidence,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING entity_id, principal_id, entity_type, canonical_name, attributes_json,
                              confidence, status, created_at, updated_at
                    """,
                    (
                        row.entity_id,
                        row.principal_id,
                        row.entity_type,
                        row.canonical_name,
                        self._json_value(row.attributes_json),
                        row.confidence,
                        row.status,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, entity_id: str) -> Entity | None:
        key = str(entity_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_id, principal_id, entity_type, canonical_name, attributes_json,
                           confidence, status, created_at, updated_at
                    FROM entities
                    WHERE entity_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_entities(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        entity_type: str | None = None,
    ) -> list[Entity]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        type_filter = str(entity_type or "").strip()
        where: list[str] = []
        params: list[object] = []
        if principal_filter:
            where.append("principal_id = %s")
            params.append(principal_filter)
        if type_filter:
            where.append("entity_type = %s")
            params.append(type_filter)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT entity_id, principal_id, entity_type, canonical_name, attributes_json, "
            "confidence, status, created_at, updated_at "
            "FROM entities "
            f"{where_sql} "
            "ORDER BY updated_at DESC, entity_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
