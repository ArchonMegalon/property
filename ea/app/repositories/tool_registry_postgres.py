from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.models import ToolDefinition, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresToolRegistryRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresToolRegistryRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres tool registry backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_registry (
                        tool_name TEXT PRIMARY KEY,
                        version TEXT NOT NULL,
                        input_schema_json JSONB NOT NULL,
                        output_schema_json JSONB NOT NULL,
                        policy_json JSONB NOT NULL,
                        allowed_channels_json JSONB NOT NULL,
                        approval_default TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_tool_registry_enabled_updated
                    ON tool_registry(enabled, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> ToolDefinition:
        (
            tool_name,
            version,
            input_schema_json,
            output_schema_json,
            policy_json,
            allowed_channels_json,
            approval_default,
            enabled,
            updated_at,
        ) = row
        channels = tuple(str(v) for v in (allowed_channels_json or []))
        return ToolDefinition(
            tool_name=str(tool_name),
            version=str(version),
            input_schema_json=dict(input_schema_json or {}),
            output_schema_json=dict(output_schema_json or {}),
            policy_json=dict(policy_json or {}),
            allowed_channels=channels,
            approval_default=str(approval_default),
            enabled=bool(enabled),
            updated_at=_to_iso(updated_at),
        )

    def upsert(self, row: ToolDefinition) -> ToolDefinition:
        tool_name = str(row.tool_name or "").strip()
        if not tool_name:
            raise ValueError("tool_name is required")
        updated = ToolDefinition(
            tool_name=tool_name,
            version=str(row.version or "v1"),
            input_schema_json=dict(row.input_schema_json or {}),
            output_schema_json=dict(row.output_schema_json or {}),
            policy_json=dict(row.policy_json or {}),
            allowed_channels=tuple(str(v) for v in row.allowed_channels),
            approval_default=str(row.approval_default or "none"),
            enabled=bool(row.enabled),
            updated_at=now_utc_iso(),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_registry
                    (tool_name, version, input_schema_json, output_schema_json, policy_json, allowed_channels_json,
                     approval_default, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tool_name) DO UPDATE
                    SET version = EXCLUDED.version,
                        input_schema_json = EXCLUDED.input_schema_json,
                        output_schema_json = EXCLUDED.output_schema_json,
                        policy_json = EXCLUDED.policy_json,
                        allowed_channels_json = EXCLUDED.allowed_channels_json,
                        approval_default = EXCLUDED.approval_default,
                        enabled = EXCLUDED.enabled,
                        updated_at = EXCLUDED.updated_at
                    RETURNING tool_name, version, input_schema_json, output_schema_json, policy_json, allowed_channels_json,
                              approval_default, enabled, updated_at
                    """,
                    (
                        updated.tool_name,
                        updated.version,
                        self._json_value(updated.input_schema_json),
                        self._json_value(updated.output_schema_json),
                        self._json_value(updated.policy_json),
                        self._json_value(list(updated.allowed_channels)),
                        updated.approval_default,
                        updated.enabled,
                        updated.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return updated
        tool = self._from_row(out)
        return tool

    def get(self, tool_name: str) -> ToolDefinition | None:
        key = str(tool_name or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tool_name, version, input_schema_json, output_schema_json, policy_json, allowed_channels_json,
                           approval_default, enabled, updated_at
                    FROM tool_registry
                    WHERE tool_name = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_enabled(self, limit: int = 100) -> list[ToolDefinition]:
        n = max(1, min(500, int(limit or 100)))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tool_name, version, input_schema_json, output_schema_json, policy_json, allowed_channels_json,
                           approval_default, enabled, updated_at
                    FROM tool_registry
                    WHERE enabled = TRUE
                    ORDER BY updated_at DESC, tool_name DESC
                    LIMIT %s
                    """,
                    (n,),
                )
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
