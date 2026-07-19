from __future__ import annotations

import copy
import hashlib
import hmac
import os
from datetime import datetime, timezone
from threading import RLock


_MEMORY_LOCK = RLock()
_MEMORY_REQUESTS: dict[tuple[str, str], dict[str, object]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: object, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _privacy_lookup_secret(secret: object = "") -> str:
    return str(
        secret
        or os.getenv("PROPERTYQUARRY_PRIVACY_LOOKUP_SECRET")
        or os.getenv("EA_SIGNING_SECRET")
        or os.getenv("EA_PROVIDER_SECRET_KEY")
        or ""
    ).strip()


def privacy_subject_key(principal_id: object, *, secret: object = "") -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return ""
    lookup_secret = _privacy_lookup_secret(secret)
    if lookup_secret:
        digest = hmac.new(lookup_secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def privacy_idempotency_key(value: object, *, secret: object = "") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    lookup_secret = _privacy_lookup_secret(secret)
    if lookup_secret:
        digest = hmac.new(lookup_secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def _normalized_request(payload: dict[str, object]) -> dict[str, object]:
    row = copy.deepcopy(dict(payload or {}))
    request_id = _clean(row.get("request_id"), limit=160)
    principal_key = _clean(row.get("principal_key"), limit=160)
    if not request_id or not principal_key:
        return {}
    status = _clean(row.get("status") or "awaiting_confirmation", limit=80).lower()
    if status not in {
        "awaiting_confirmation",
        "processing",
        "completed",
        "completed_with_provider_followup",
        "cancelled",
        "expired",
        "failed",
    }:
        status = "awaiting_confirmation"
    row.update(
        {
            "request_id": request_id,
            "principal_key": principal_key,
            "subject_ref_digest": _clean(row.get("subject_ref_digest") or principal_key, limit=160),
            "idempotency_key_hash": _clean(row.get("idempotency_key_hash"), limit=160),
            "status": status,
            "created_at": _clean(row.get("created_at") or _now_iso(), limit=80),
            "updated_at": _clean(row.get("updated_at") or _now_iso(), limit=80),
            "confirmation_expires_at": _clean(row.get("confirmation_expires_at"), limit=80),
            "confirmed_at": _clean(row.get("confirmed_at"), limit=80),
            "cancelled_at": _clean(row.get("cancelled_at"), limit=80),
            "completed_at": _clean(row.get("completed_at"), limit=80),
            "last_error_code": _clean(row.get("last_error_code"), limit=160),
        }
    )
    # A workflow lookup never needs the raw account identifier or a confirmation phrase.
    for forbidden in ("principal_id", "email", "access_token", "token", "confirmation_phrase"):
        row.pop(forbidden, None)
    return row


def _connect(database_url: str):  # type: ignore[no-untyped-def]
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is required for postgres privacy lifecycle storage") from exc
    return psycopg.connect(str(database_url or "").strip(), autocommit=True)


def _json_value(value: dict[str, object]):  # type: ignore[no-untyped-def]
    from psycopg.types.json import Json

    return Json(value)


def resolve_privacy_lifecycle_storage_backend(
    *,
    database_url: str = "",
    storage_backend: str = "",
    runtime_mode: str = "",
) -> str:
    """Resolve one explicit privacy store without permitting fallback.

    Production always requires Postgres. Memory is intentionally limited to an
    explicitly configured development or test backend; an implicit ``auto``
    backend with no database is not a durable privacy-lifecycle contract.
    """

    normalized_database_url = str(database_url or "").strip()
    normalized_backend = str(
        storage_backend or os.getenv("EA_STORAGE_BACKEND") or ""
    ).strip().lower()
    normalized_mode = str(
        runtime_mode or os.getenv("EA_RUNTIME_MODE") or "dev"
    ).strip().lower()

    if normalized_backend not in {"", "auto", "memory", "postgres"}:
        raise RuntimeError("propertyquarry_privacy_storage_backend_invalid")

    if normalized_mode == "prod":
        if normalized_backend == "memory":
            raise RuntimeError("propertyquarry_privacy_postgres_required")
        if not normalized_database_url:
            raise RuntimeError("propertyquarry_privacy_database_url_required")
        return "postgres"

    if normalized_backend == "memory":
        if normalized_mode not in {"dev", "test"}:
            raise RuntimeError("propertyquarry_privacy_memory_backend_forbidden")
        return "memory"

    if normalized_backend == "postgres" or (
        normalized_backend in {"", "auto"} and normalized_database_url
    ):
        if not normalized_database_url:
            raise RuntimeError("propertyquarry_privacy_database_url_required")
        return "postgres"

    raise RuntimeError("propertyquarry_privacy_storage_backend_required")


def put_privacy_request_record(
    payload: dict[str, object],
    *,
    database_url: str = "",
    storage_backend: str = "",
    runtime_mode: str = "",
) -> dict[str, object]:
    row = _normalized_request(payload)
    if not row:
        return {}
    backend = resolve_privacy_lifecycle_storage_backend(
        database_url=database_url,
        storage_backend=storage_backend,
        runtime_mode=runtime_mode,
    )
    if backend == "postgres":
        with _connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_account_privacy_requests (
                        principal_key, request_id, idempotency_key_hash, status,
                        payload_json, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::timestamptz, NOW())
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        row["principal_key"],
                        row["request_id"],
                        row["idempotency_key_hash"],
                        row["status"],
                        _json_value(row),
                        row["created_at"],
                    ),
                )
                inserted = bool(cur.rowcount)
                if not inserted:
                    cur.execute(
                        """
                        UPDATE property_account_privacy_requests
                        SET idempotency_key_hash = %s,
                            status = %s,
                            payload_json = %s,
                            updated_at = NOW()
                        WHERE principal_key = %s AND request_id = %s
                        """,
                        (
                            row["idempotency_key_hash"],
                            row["status"],
                            _json_value(row),
                            row["principal_key"],
                            row["request_id"],
                        ),
                    )
                    if not cur.rowcount and row["idempotency_key_hash"]:
                        cur.execute(
                            """
                            SELECT payload_json
                            FROM property_account_privacy_requests
                            WHERE principal_key = %s AND idempotency_key_hash = %s
                            LIMIT 1
                            """,
                            (row["principal_key"], row["idempotency_key_hash"]),
                        )
                        found = cur.fetchone()
                        if found and isinstance(found[0], dict):
                            normalized_found = _normalized_request(dict(found[0]))
                            if normalized_found:
                                return normalized_found
        return row
    with _MEMORY_LOCK:
        if row["idempotency_key_hash"]:
            for (candidate_principal, _candidate_request), existing in _MEMORY_REQUESTS.items():
                if (
                    candidate_principal == row["principal_key"]
                    and existing.get("idempotency_key_hash") == row["idempotency_key_hash"]
                    and existing.get("request_id") != row["request_id"]
                ):
                    return copy.deepcopy(existing)
        _MEMORY_REQUESTS[(str(row["principal_key"]), str(row["request_id"]))] = copy.deepcopy(row)
    return row


def _postgres_records(database_url: str, query: str, params: tuple[object, ...]) -> tuple[dict[str, object], ...]:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    records: list[dict[str, object]] = []
    for (payload_json,) in rows:
        if isinstance(payload_json, dict):
            normalized = _normalized_request(dict(payload_json))
            if normalized:
                records.append(normalized)
    return tuple(records)


def get_privacy_request_record(
    *,
    principal_key: str,
    request_id: str,
    database_url: str = "",
    storage_backend: str = "",
    runtime_mode: str = "",
) -> dict[str, object] | None:
    normalized_principal = str(principal_key or "").strip()
    normalized_request = str(request_id or "").strip()
    if not normalized_principal or not normalized_request:
        return None
    backend = resolve_privacy_lifecycle_storage_backend(
        database_url=database_url,
        storage_backend=storage_backend,
        runtime_mode=runtime_mode,
    )
    if backend == "postgres":
        rows = _postgres_records(
            database_url,
            """
            SELECT payload_json
            FROM property_account_privacy_requests
            WHERE principal_key = %s AND request_id = %s
            LIMIT 1
            """,
            (normalized_principal, normalized_request),
        )
        return dict(rows[0]) if rows else None
    with _MEMORY_LOCK:
        row = _MEMORY_REQUESTS.get((normalized_principal, normalized_request))
        return copy.deepcopy(row) if row else None


def find_privacy_request_by_idempotency(
    *,
    principal_key: str,
    idempotency_key_hash: str,
    database_url: str = "",
    storage_backend: str = "",
    runtime_mode: str = "",
) -> dict[str, object] | None:
    normalized_principal = str(principal_key or "").strip()
    normalized_key = str(idempotency_key_hash or "").strip()
    if not normalized_principal or not normalized_key:
        return None
    backend = resolve_privacy_lifecycle_storage_backend(
        database_url=database_url,
        storage_backend=storage_backend,
        runtime_mode=runtime_mode,
    )
    if backend == "postgres":
        rows = _postgres_records(
            database_url,
            """
            SELECT payload_json
            FROM property_account_privacy_requests
            WHERE principal_key = %s AND idempotency_key_hash = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (normalized_principal, normalized_key),
        )
        return dict(rows[0]) if rows else None
    with _MEMORY_LOCK:
        for (candidate_principal, _request_id), row in reversed(tuple(_MEMORY_REQUESTS.items())):
            if candidate_principal == normalized_principal and row.get("idempotency_key_hash") == normalized_key:
                return copy.deepcopy(row)
    return None


def list_privacy_request_records(
    *,
    principal_key: str,
    limit: int = 20,
    database_url: str = "",
    storage_backend: str = "",
    runtime_mode: str = "",
) -> tuple[dict[str, object], ...]:
    normalized_principal = str(principal_key or "").strip()
    bounded_limit = max(1, min(int(limit or 20), 100))
    if not normalized_principal:
        return ()
    backend = resolve_privacy_lifecycle_storage_backend(
        database_url=database_url,
        storage_backend=storage_backend,
        runtime_mode=runtime_mode,
    )
    if backend == "postgres":
        return _postgres_records(
            database_url,
            """
            SELECT payload_json
            FROM property_account_privacy_requests
            WHERE principal_key = %s
            ORDER BY updated_at DESC, request_id DESC
            LIMIT %s
            """,
            (normalized_principal, bounded_limit),
        )
    with _MEMORY_LOCK:
        rows = [
            copy.deepcopy(row)
            for (candidate_principal, _request_id), row in _MEMORY_REQUESTS.items()
            if candidate_principal == normalized_principal
        ]
    rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("request_id") or "")), reverse=True)
    return tuple(rows[:bounded_limit])


def clear_privacy_lifecycle_memory_for_tests() -> None:
    with _MEMORY_LOCK:
        _MEMORY_REQUESTS.clear()
