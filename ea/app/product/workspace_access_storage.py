from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from threading import RLock
from typing import Any


_MEMORY_LOCK = RLock()
_MEMORY_SESSIONS: dict[tuple[str, str], dict[str, object]] = {}
_SCHEMA_LOCK = RLock()
_SCHEMA_READY_DATABASE_URLS: set[str] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: object, *, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _workspace_access_hash_secret(secret: object = "") -> str:
    return str(
        secret
        or os.getenv("PROPERTYQUARRY_WORKSPACE_ACCESS_HASH_SECRET")
        or os.getenv("EA_SIGNING_SECRET")
        or os.getenv("EA_PROVIDER_SECRET_KEY")
        or ""
    ).strip()


def _workspace_access_legacy_sha256(token: object) -> str:
    normalized = str(token or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def workspace_access_token_hash(token: object, *, secret: object = "") -> str:
    normalized = str(token or "").strip()
    if not normalized:
        return ""
    hash_secret = _workspace_access_hash_secret(secret)
    if hash_secret:
        digest = hmac.new(hash_secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"
    return _workspace_access_legacy_sha256(normalized)


def workspace_access_token_hash_candidates(token: object, *, secret: object = "") -> tuple[str, ...]:
    normalized = str(token or "").strip()
    if not normalized:
        return ()
    candidates: list[str] = []
    keyed = workspace_access_token_hash(normalized, secret=secret)
    if keyed:
        candidates.append(keyed)
    legacy = _workspace_access_legacy_sha256(normalized)
    if legacy and legacy not in candidates:
        candidates.append(legacy)
    prefixed_legacy = f"sha256:{legacy}" if legacy else ""
    if prefixed_legacy and prefixed_legacy not in candidates:
        candidates.append(prefixed_legacy)
    return tuple(candidates)


def workspace_access_token_last4(token: object) -> str:
    normalized = str(token or "").strip()
    return normalized[-4:] if len(normalized) >= 4 else normalized


def _normalized_workspace_access_session(payload: dict[str, object]) -> dict[str, object]:
    row = dict(payload or {})
    principal_id = _clean(row.get("principal_id"), limit=200)
    session_id = _clean(row.get("session_id"), limit=200)
    if not principal_id or not session_id:
        return {}
    status = _clean(row.get("status") or "active", limit=40).lower() or "active"
    access_token = _clean(row.get("access_token"), limit=5000)
    access_launch_token = _clean(row.get("access_launch_token"), limit=5000)
    access_token_hash = _clean(row.get("access_token_hash") or workspace_access_token_hash(access_token), limit=128)
    access_launch_token_hash = _clean(row.get("access_launch_token_hash") or workspace_access_token_hash(access_launch_token), limit=128)
    normalized: dict[str, object] = {
        "session_id": session_id,
        "principal_id": principal_id,
        "email": _clean(row.get("email"), limit=320).lower(),
        "role": _clean(row.get("role") or "principal", limit=80).lower() or "principal",
        "display_name": _clean(row.get("display_name"), limit=200),
        "operator_id": _clean(row.get("operator_id"), limit=200),
        "source_kind": _clean(row.get("source_kind"), limit=120),
        "issued_at": _clean(row.get("issued_at"), limit=80),
        "status": status,
        "revoked_at": _clean(row.get("revoked_at"), limit=80),
        "revoked_by": _clean(row.get("revoked_by"), limit=200),
        "expires_at": _clean(row.get("expires_at"), limit=80),
        "opened_at": _clean(row.get("opened_at"), limit=80),
        "opened_by": _clean(row.get("opened_by"), limit=200),
        "last_seen_at": _clean(row.get("last_seen_at"), limit=80),
        "access_token": "",
        "access_url": "",
        "access_launch_token": "",
        "access_launch_url": "",
        "access_token_hash": access_token_hash,
        "access_token_last4": _clean(row.get("access_token_last4") or workspace_access_token_last4(access_token), limit=16),
        "access_launch_token_hash": access_launch_token_hash,
        "access_launch_token_last4": _clean(row.get("access_launch_token_last4") or workspace_access_token_last4(access_launch_token), limit=16),
        "access_launch_token_used_at": _clean(row.get("access_launch_token_used_at"), limit=80),
        "default_target": _clean(row.get("default_target"), limit=500),
        "updated_at": _clean(row.get("updated_at") or _now_iso(), limit=80),
    }
    if normalized["role"] != "operator":
        normalized["operator_id"] = ""
    if normalized["status"] not in {"active", "revoked", "expired"}:
        normalized["status"] = "active"
    return normalized


def _connect(database_url: str):  # type: ignore[no-untyped-def]
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is required for postgres workspace access storage") from exc
    return psycopg.connect(str(database_url or "").strip(), autocommit=True)


def _json_value(value: dict[str, object]):  # type: ignore[no-untyped-def]
    from psycopg.types.json import Json

    return Json(value)


def _ensure_workspace_access_schema(database_url: str) -> bool:
    normalized_database_url = str(database_url or "").strip()
    if not normalized_database_url:
        return False
    with _SCHEMA_LOCK:
        if normalized_database_url in _SCHEMA_READY_DATABASE_URLS:
            return True
        with _connect(normalized_database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_access_sessions (
                        principal_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        payload_json JSONB NOT NULL,
                        email TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'active',
                        issued_at TEXT NOT NULL DEFAULT '',
                        expires_at TEXT NOT NULL DEFAULT '',
                        revoked_at TEXT NOT NULL DEFAULT '',
                        opened_at TEXT NOT NULL DEFAULT '',
                        last_seen_at TEXT NOT NULL DEFAULT '',
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (principal_id, session_id)
                    )
                    """
                )
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS payload_json JSONB NOT NULL DEFAULT '{}'::jsonb")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS issued_at TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS expires_at TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS revoked_at TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS opened_at TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS last_seen_at TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE workspace_access_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workspace_access_sessions_session
                    ON workspace_access_sessions(session_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_workspace_access_sessions_principal_updated
                    ON workspace_access_sessions(principal_id, updated_at DESC)
                    """
                )
        _SCHEMA_READY_DATABASE_URLS.add(normalized_database_url)
    return True


def put_workspace_access_session_record(
    payload: dict[str, object],
    *,
    database_url: str = "",
) -> dict[str, object]:
    row = _normalized_workspace_access_session(payload)
    if not row:
        return {}
    if str(database_url or "").strip():
        try:
            if _ensure_workspace_access_schema(database_url):
                with _connect(database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO workspace_access_sessions (
                                principal_id, session_id, payload_json, email, role, status,
                                issued_at, expires_at, revoked_at, opened_at, last_seen_at, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (principal_id, session_id) DO UPDATE
                            SET payload_json = EXCLUDED.payload_json,
                                email = EXCLUDED.email,
                                role = EXCLUDED.role,
                                status = EXCLUDED.status,
                                issued_at = EXCLUDED.issued_at,
                                expires_at = EXCLUDED.expires_at,
                                revoked_at = EXCLUDED.revoked_at,
                                opened_at = EXCLUDED.opened_at,
                                last_seen_at = EXCLUDED.last_seen_at,
                                updated_at = NOW()
                            """,
                            (
                                row["principal_id"],
                                row["session_id"],
                                _json_value(row),
                                row["email"],
                                row["role"],
                                row["status"],
                                row["issued_at"],
                                row["expires_at"],
                                row["revoked_at"],
                                row["opened_at"],
                                row["last_seen_at"],
                            ),
                        )
                return row
        except Exception:
            pass
    with _MEMORY_LOCK:
        _MEMORY_SESSIONS[(str(row["principal_id"]), str(row["session_id"]))] = dict(row)
    return row


def update_workspace_access_session_record(
    *,
    principal_id: str,
    session_id: str,
    updates: dict[str, object],
    database_url: str = "",
) -> dict[str, object]:
    current = get_workspace_access_session_record(
        principal_id=principal_id,
        session_id=session_id,
        database_url=database_url,
    )
    if not current:
        current = {
            "principal_id": str(principal_id or "").strip(),
            "session_id": str(session_id or "").strip(),
        }
    merged = dict(current)
    merged.update(dict(updates or {}))
    merged["updated_at"] = _now_iso()
    return put_workspace_access_session_record(merged, database_url=database_url)


def _postgres_rows(database_url: str, query: str, params: tuple[object, ...]) -> tuple[dict[str, object], ...]:
    if not _ensure_workspace_access_schema(database_url):
        return ()
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    rendered: list[dict[str, object]] = []
    for (payload_json,) in rows:
        if isinstance(payload_json, dict):
            normalized = _normalized_workspace_access_session(dict(payload_json))
            if normalized:
                rendered.append(normalized)
    return tuple(rendered)


def get_workspace_access_session_record(
    *,
    principal_id: str,
    session_id: str,
    database_url: str = "",
) -> dict[str, object] | None:
    normalized_principal = str(principal_id or "").strip()
    normalized_session = str(session_id or "").strip()
    if not normalized_principal or not normalized_session:
        return None
    if str(database_url or "").strip():
        try:
            rows = _postgres_rows(
                database_url,
                """
                SELECT payload_json
                FROM workspace_access_sessions
                WHERE principal_id = %s AND session_id = %s
                LIMIT 1
                """,
                (normalized_principal, normalized_session),
            )
            if rows:
                return dict(rows[0])
        except Exception:
            pass
    with _MEMORY_LOCK:
        row = _MEMORY_SESSIONS.get((normalized_principal, normalized_session))
        return dict(row) if row else None


def get_workspace_access_session_record_by_session_id(
    *,
    session_id: str,
    database_url: str = "",
) -> dict[str, object] | None:
    normalized_session = str(session_id or "").strip()
    if not normalized_session:
        return None
    if str(database_url or "").strip():
        try:
            rows = _postgres_rows(
                database_url,
                """
                SELECT payload_json
                FROM workspace_access_sessions
                WHERE session_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (normalized_session,),
            )
            if rows:
                return dict(rows[0])
        except Exception:
            pass
    with _MEMORY_LOCK:
        for (_principal_id, current_session_id), row in sorted(
            _MEMORY_SESSIONS.items(),
            key=lambda item: str(item[1].get("updated_at") or ""),
            reverse=True,
        ):
            if current_session_id == normalized_session:
                return dict(row)
    return None


def list_workspace_access_session_records(
    *,
    principal_id: str,
    status: str = "",
    limit: int = 100,
    database_url: str = "",
) -> tuple[dict[str, object], ...]:
    normalized_principal = str(principal_id or "").strip()
    wanted_status = str(status or "").strip().lower()
    bounded_limit = max(1, min(int(limit or 100), 1000))
    if not normalized_principal:
        return ()
    if str(database_url or "").strip():
        try:
            if wanted_status:
                rows = _postgres_rows(
                    database_url,
                    """
                    SELECT payload_json
                    FROM workspace_access_sessions
                    WHERE principal_id = %s AND status = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (normalized_principal, wanted_status, bounded_limit),
                )
            else:
                rows = _postgres_rows(
                    database_url,
                    """
                    SELECT payload_json
                    FROM workspace_access_sessions
                    WHERE principal_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (normalized_principal, bounded_limit),
                )
            if rows:
                return rows
        except Exception:
            pass
    with _MEMORY_LOCK:
        rows = [
            dict(row)
            for (row_principal, _session_id), row in _MEMORY_SESSIONS.items()
            if row_principal == normalized_principal
        ]
    if wanted_status:
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == wanted_status]
    rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("session_id") or "")), reverse=True)
    return tuple(rows[:bounded_limit])
