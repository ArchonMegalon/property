from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import DeliveryPreference, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "disabled"}:
        return raw
    return "active"


class PostgresDeliveryPreferenceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresDeliveryPreferenceRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres delivery-preference backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS delivery_preferences (
                        preference_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        recipient_ref TEXT NOT NULL,
                        cadence TEXT NOT NULL,
                        quiet_hours_json JSONB NOT NULL,
                        format_json JSONB NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS quiet_hours_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute(
                    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS format_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                )
                cur.execute("ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_preferences_identity_unique
                    ON delivery_preferences(principal_id, channel, recipient_ref)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_delivery_preferences_principal_status
                    ON delivery_preferences(principal_id, status, updated_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> DeliveryPreference:
        (
            preference_id,
            principal_id,
            channel,
            recipient_ref,
            cadence,
            quiet_hours_json,
            format_json,
            status,
            created_at,
            updated_at,
        ) = row
        return DeliveryPreference(
            preference_id=str(preference_id),
            principal_id=str(principal_id),
            channel=str(channel),
            recipient_ref=str(recipient_ref),
            cadence=str(cadence),
            quiet_hours_json=dict(quiet_hours_json or {}),
            format_json=dict(format_json or {}),
            status=str(status or "active"),
            created_at=_to_iso(created_at),
            updated_at=_to_iso(updated_at),
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
        row = DeliveryPreference(
            preference_id=str(preference_id or "").strip() or str(uuid.uuid4()),
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO delivery_preferences
                    (preference_id, principal_id, channel, recipient_ref, cadence,
                     quiet_hours_json, format_json, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_id, channel, recipient_ref) DO UPDATE
                    SET cadence = EXCLUDED.cadence,
                        quiet_hours_json = EXCLUDED.quiet_hours_json,
                        format_json = EXCLUDED.format_json,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING preference_id, principal_id, channel, recipient_ref, cadence,
                              quiet_hours_json, format_json, status, created_at, updated_at
                    """,
                    (
                        row.preference_id,
                        row.principal_id,
                        row.channel,
                        row.recipient_ref,
                        row.cadence,
                        self._json_value(row.quiet_hours_json),
                        self._json_value(row.format_json),
                        row.status,
                        row.created_at,
                        row.updated_at,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, preference_id: str) -> DeliveryPreference | None:
        key = str(preference_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT preference_id, principal_id, channel, recipient_ref, cadence,
                           quiet_hours_json, format_json, status, created_at, updated_at
                    FROM delivery_preferences
                    WHERE preference_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_preferences(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[DeliveryPreference]:
        principal = str(principal_id or "").strip()
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        where = "WHERE principal_id = %s"
        params: list[object] = [principal]
        if status_filter:
            where += " AND status = %s"
            params.append(status_filter)
        query = (
            "SELECT preference_id, principal_id, channel, recipient_ref, cadence, "
            "quiet_hours_json, format_json, status, created_at, updated_at "
            "FROM delivery_preferences "
            f"{where} "
            "ORDER BY updated_at DESC, preference_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]
