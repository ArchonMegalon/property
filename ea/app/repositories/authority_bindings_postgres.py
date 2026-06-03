from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import AuthorityBinding, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "disabled"}:
        return raw
    return "active"


class PostgresAuthorityBindingRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresAuthorityBindingRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres authority-binding backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any] | list[str]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS authority_bindings (
                        binding_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        subject_ref TEXT NOT NULL,
                        action_scope TEXT NOT NULL,
                        approval_level TEXT NOT NULL,
                        channel_scope_json JSONB NOT NULL,
                        policy_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE authority_bindings ADD COLUMN IF NOT EXISTS channel_scope_json JSONB NOT NULL DEFAULT '[]'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE authority_bindings ADD COLUMN IF NOT EXISTS policy_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE authority_bindings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_authority_bindings_identity_unique
                    ON authority_bindings(principal_id, subject_ref, action_scope)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_authority_bindings_principal_status
                    ON authority_bindings(principal_id, status, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> AuthorityBinding:
        (
            binding_id,
            principal_id,
            subject_ref,
            action_scope,
            approval_level,
            channel_scope_json,
            policy_json,
            status,
            created_at,
            updated_at,
        ) = row
        return AuthorityBinding(
            binding_id=str(binding_id),
            principal_id=str(principal_id),
            subject_ref=str(subject_ref),
            action_scope=str(action_scope),
            approval_level=str(approval_level),
            channel_scope=tuple(str(v) for v in (channel_scope_json or [])),
            policy_json=dict(policy_json or {}),
            status=str(status or "active"),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
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
        row = AuthorityBinding(
            binding_id=str(binding_id or "").strip() or str(uuid.uuid4()),
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO authority_bindings
                    (binding_id, principal_id, subject_ref, action_scope, approval_level,
                     channel_scope_json, policy_json, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, subject_ref, action_scope) DO UPDATE
                    SET approval_level = EXCLUDED.approval_level,
                        channel_scope_json = EXCLUDED.channel_scope_json,
                        policy_json = EXCLUDED.policy_json,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING binding_id, principal_id, subject_ref, action_scope, approval_level,
                              channel_scope_json, policy_json, status, created_at, updated_at
                    """,
                    (
                        row.binding_id,
                        row.principal_id,
                        row.subject_ref,
                        row.action_scope,
                        row.approval_level,
                        self._json_value(list(row.channel_scope)),
                        self._json_value(row.policy_json),
                        row.status,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, binding_id: str) -> AuthorityBinding | None:
        key = str(binding_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT binding_id, principal_id, subject_ref, action_scope, approval_level,
                           channel_scope_json, policy_json, status, created_at, updated_at
                    FROM authority_bindings
                    WHERE binding_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_bindings(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[AuthorityBinding]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT binding_id, principal_id, subject_ref, action_scope, approval_level, "
            "channel_scope_json, policy_json, status, created_at, updated_at "
            "FROM authority_bindings "
            f"{where} "
            "ORDER BY updated_at DESC, binding_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
