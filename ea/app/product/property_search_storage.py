from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


_PROPERTY_SEARCH_RUN_TTL_SECONDS = 6 * 60 * 60
_PROPERTY_SEARCH_RUN_SCHEMA_LOCK = threading.Lock()
_PROPERTY_SEARCH_RUN_SCHEMA_READY = False

_PROPERTY_SOURCE_LISTING_CACHE_LOCK = threading.Lock()
_PROPERTY_SOURCE_LISTING_CACHE: dict[str, dict[str, object]] = {}
_PROPERTY_SOURCE_LISTING_CACHE_VERSION = "property_source_listing_cache_v1"
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_VERSION = 1
_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES = 256
_PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
_PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_LOCK = threading.Lock()
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _property_search_run_database_url() -> str:
    return str(os.environ.get("DATABASE_URL") or "").strip()


def _property_search_run_connect():  # type: ignore[no-untyped-def]
    database_url = _property_search_run_database_url()
    if not database_url:
        raise RuntimeError("database_url_missing")
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _quote_pg_identifier(value: str) -> str:
    return '"' + str(value or "").replace('"', '""') + '"'


def _property_search_run_primary_key_columns(cur) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS key_columns(attnum, ordinal) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_columns.attnum
        WHERE n.nspname = current_schema()
          AND t.relname = 'property_search_runs'
          AND i.indisprimary
        ORDER BY key_columns.ordinal
        """
    )
    return tuple(str(row[0]) for row in cur.fetchall())


def _ensure_property_search_run_primary_key(cur) -> None:  # type: ignore[no-untyped-def]
    desired_columns = ("principal_id", "run_id")
    if _property_search_run_primary_key_columns(cur) == desired_columns:
        return
    cur.execute(
        """
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'property_search_runs'::regclass
          AND contype = 'p'
        """
    )
    row = cur.fetchone()
    if row and row[0]:
        cur.execute(f"ALTER TABLE property_search_runs DROP CONSTRAINT {_quote_pg_identifier(str(row[0]))}")
    cur.execute(
        """
        DELETE FROM property_search_runs a
        USING property_search_runs b
        WHERE a.ctid < b.ctid
          AND a.principal_id = b.principal_id
          AND a.run_id = b.run_id
        """
    )
    cur.execute("ALTER TABLE property_search_runs ALTER COLUMN principal_id SET NOT NULL")
    cur.execute("ALTER TABLE property_search_runs ALTER COLUMN run_id SET NOT NULL")
    cur.execute("ALTER TABLE property_search_runs ADD PRIMARY KEY (principal_id, run_id)")


def _ensure_property_search_run_schema() -> None:
    global _PROPERTY_SEARCH_RUN_SCHEMA_READY
    if _PROPERTY_SEARCH_RUN_SCHEMA_READY or not _property_search_run_database_url():
        return
    with _PROPERTY_SEARCH_RUN_SCHEMA_LOCK:
        if _PROPERTY_SEARCH_RUN_SCHEMA_READY:
            return
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_search_runs (
                        principal_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (principal_id, run_id)
                    )
                    """
                )
                _ensure_property_search_run_primary_key(cur)
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_search_runs_updated
                    ON property_search_runs(updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_search_runs_principal_updated
                    ON property_search_runs(principal_id, updated_at DESC)
                    """
                )
        _PROPERTY_SEARCH_RUN_SCHEMA_READY = True


def _store_property_search_run_record(record: dict[str, object]) -> None:
    if not _property_search_run_database_url():
        return
    _ensure_property_search_run_schema()
    run_id = str(record.get("run_id") or "").strip()
    principal_id = str(record.get("principal_id") or "").strip()
    if not run_id or not principal_id:
        return
    from psycopg.types.json import Json

    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO property_search_runs (run_id, principal_id, payload_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (principal_id, run_id) DO UPDATE
                SET payload_json = EXCLUDED.payload_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    run_id,
                    principal_id,
                    Json(record),
                    str(record.get("created_at") or _now_iso()).strip() or _now_iso(),
                    str(record.get("updated_at") or _now_iso()).strip() or _now_iso(),
                ),
            )


def _load_property_search_run_record(*, run_id: str, principal_id: str) -> dict[str, object] | None:
    if not _property_search_run_database_url():
        return None
    _ensure_property_search_run_schema()
    normalized_run_id = str(run_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_run_id or not normalized_principal_id:
        return None
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
                (normalized_run_id, normalized_principal_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return dict(row[0] or {}) if isinstance(row[0], dict) else None


def _list_property_search_run_records(
    *,
    limit: int = 20,
    statuses: tuple[str, ...] = (),
    principal_id: str = "",
    admin: bool = False,
    registry: dict[str, dict[str, object]] | None = None,
) -> tuple[dict[str, object], ...]:
    normalized_limit = max(int(limit or 0), 1)
    normalized_statuses = tuple(
        sorted({str(value or "").strip().lower() for value in statuses if str(value or "").strip()})
    )
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id and not admin:
        return ()
    if not _property_search_run_database_url():
        rows = [dict(value) for value in (registry or {}).values() if isinstance(value, dict)]
        if normalized_principal_id:
            rows = [row for row in rows if str(row.get("principal_id") or "").strip() == normalized_principal_id]
        if normalized_statuses:
            rows = [row for row in rows if str(row.get("status") or "").strip().lower() in normalized_statuses]
        rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        return tuple(rows[:normalized_limit])
    _ensure_property_search_run_schema()
    query = "SELECT payload_json FROM property_search_runs"
    params: list[object] = []
    where_clauses: list[str] = []
    if normalized_principal_id:
        where_clauses.append("principal_id = %s")
        params.append(normalized_principal_id)
    if normalized_statuses:
        where_clauses.append("(payload_json->>'status') = ANY(%s)")
        params.append(list(normalized_statuses))
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY updated_at DESC LIMIT %s"
    params.append(normalized_limit)
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        payload = row[0] if row else None
        if isinstance(payload, dict):
            results.append(dict(payload))
    return tuple(results)


def _prune_property_search_run_records() -> None:
    if not _property_search_run_database_url():
        return
    _ensure_property_search_run_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_PROPERTY_SEARCH_RUN_TTL_SECONDS)).isoformat()
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM property_search_runs WHERE updated_at < %s", (cutoff,))


def _delete_property_search_run_record(
    *,
    run_id: str,
    principal_id: str,
    registry: dict[str, dict[str, object]] | None = None,
) -> bool:
    normalized_run_id = str(run_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_run_id or not normalized_principal_id:
        return False
    if not _property_search_run_database_url():
        if registry is None:
            return False
        record = registry.get(normalized_run_id)
        if str(dict(record or {}).get("principal_id") or "").strip() != normalized_principal_id:
            return False
        return registry.pop(normalized_run_id, None) is not None
    _ensure_property_search_run_schema()
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
                (normalized_run_id, normalized_principal_id),
            )
            return bool(cur.rowcount)


def _property_source_listing_cache_ttl_seconds() -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS") or "").strip()
    if not raw_value:
        return 15 * 60
    try:
        parsed = int(raw_value)
    except Exception:
        return 15 * 60
    return max(0, min(parsed, 24 * 60 * 60))


def _property_source_listing_cache_stale_max_seconds() -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS") or "").strip()
    if not raw_value:
        return 6 * 60 * 60
    try:
        parsed = int(raw_value)
    except Exception:
        return 6 * 60 * 60
    return max(0, min(parsed, 7 * 24 * 60 * 60))


def _property_source_listing_cache_path() -> Path | None:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH") or "").strip()
    if not raw_value or raw_value.lower() in {"0", "false", "no", "off", "disabled"}:
        return None
    return Path(raw_value).expanduser()


def _property_source_listing_cache_backend() -> str:
    raw_value = os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND")
    storage_backend = str(os.getenv("EA_STORAGE_BACKEND") or "").strip().lower()
    configured = str(raw_value or "").strip().lower()
    if configured not in {"", "auto", "memory", "file", "postgres"}:
        configured = "auto"
    if configured in {"memory", "file", "postgres"}:
        return configured
    if raw_value is None and storage_backend == "postgres" and _property_search_run_database_url():
        return "postgres"
    if configured == "auto" and _property_search_run_database_url():
        return "postgres"
    if raw_value is None and _property_source_listing_cache_path() is not None:
        return "file"
    if _property_source_listing_cache_path() is not None:
        return "file"
    return "memory"


def _property_source_listing_cache_key(*, source_url: str, source_spec: dict[str, object] | None = None) -> str:
    spec = dict(source_spec or {})
    configured = str(spec.get("provider_cache_key") or "").strip()
    if configured:
        return configured[:240]
    pushdown = dict(spec.get("provider_filter_pushdown") or {}) if isinstance(spec.get("provider_filter_pushdown"), dict) else {}
    pushdown_key = str(pushdown.get("cache_key") or "").strip()
    if pushdown_key:
        return pushdown_key[:240]
    return ""


def _property_source_listing_cache_normalize_row(raw_key: object, raw_row: object, *, now: float | None = None) -> dict[str, object]:
    cache_key = str(raw_key or "").strip()[:240]
    if not cache_key or not isinstance(raw_row, dict):
        return {}
    try:
        stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
    except Exception:
        stored_at = 0.0
    effective_now = float(now or time.time())
    urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
    if not urls:
        return {}
    return {
        "cache_key": cache_key,
        "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
        "listing_urls": urls[:250],
        "stored_at_epoch": stored_at or effective_now,
        "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
        if isinstance(raw_row.get("provider_filter_pushdown"), dict)
        else {},
    }


def _property_source_listing_cache_row_state(
    *,
    cache_key: str,
    row: dict[str, object],
    allow_stale: bool,
    persistence: str,
) -> tuple[tuple[str, ...], dict[str, object]]:
    now = time.time()
    ttl = _property_source_listing_cache_ttl_seconds()
    stale_max = _property_source_listing_cache_stale_max_seconds()
    try:
        stored_at = float(row.get("stored_at_epoch") or 0.0)
    except Exception:
        stored_at = 0.0
    age_seconds = max(0.0, now - stored_at)
    if not allow_stale and (ttl <= 0 or age_seconds > float(ttl)):
        return (), {}
    if allow_stale and (
        ttl <= 0
        or (age_seconds > float(ttl) and stale_max <= 0)
        or (stale_max > 0 and age_seconds > float(stale_max))
    ):
        return (), {}
    urls = tuple(str(value or "").strip() for value in list(row.get("listing_urls") or []) if str(value or "").strip())
    if not urls:
        return (), {}
    state = {
        "status": "stale_fallback" if ttl > 0 and age_seconds > float(ttl) else "hit",
        "cache_key": cache_key,
        "age_seconds": round(age_seconds, 2),
        "listing_total": len(urls),
        "persistence": persistence,
        "revalidation": "candidate_preview",
    }
    return urls, state


def _property_source_listing_cache_prune_locked() -> None:
    while len(_PROPERTY_SOURCE_LISTING_CACHE) > _PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES:
        oldest_key = min(
            _PROPERTY_SOURCE_LISTING_CACHE,
            key=lambda key: float(_PROPERTY_SOURCE_LISTING_CACHE.get(key, {}).get("stored_at_epoch") or 0.0),
        )
        _PROPERTY_SOURCE_LISTING_CACHE.pop(oldest_key, None)


def _property_source_listing_cache_snapshot_locked() -> dict[str, dict[str, object]]:
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    snapshot: dict[str, dict[str, object]] = {}
    for key, row in _PROPERTY_SOURCE_LISTING_CACHE.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        try:
            stored_at = float(row.get("stored_at_epoch") or 0.0)
        except Exception:
            stored_at = 0.0
        if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
            continue
        urls = [str(value or "").strip() for value in list(row.get("listing_urls") or []) if str(value or "").strip()]
        if not urls:
            continue
        snapshot[normalized_key] = {
            "cache_key": normalized_key,
            "source_url": urllib.parse.urldefrag(str(row.get("source_url") or "").strip())[0],
            "listing_urls": urls[:250],
            "stored_at_epoch": stored_at or now,
            "provider_filter_pushdown": dict(row.get("provider_filter_pushdown") or {})
            if isinstance(row.get("provider_filter_pushdown"), dict)
            else {},
        }
    return dict(
        sorted(
            snapshot.items(),
            key=lambda item: float(item[1].get("stored_at_epoch") or 0.0),
            reverse=True,
        )[:_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES]
    )


@contextlib.contextmanager
def _property_source_listing_cache_file_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass


def _property_source_listing_cache_quarantine_corrupt_file(path: Path, *, reason: str) -> str:
    if not path.exists():
        return ""
    suffix = f"corrupt-{int(time.time())}-{uuid4().hex[:12]}"
    quarantine_path = path.with_name(f"{path.name}.{suffix}.json")
    try:
        path.replace(quarantine_path)
    except Exception:
        return ""
    return f"{quarantine_path}:{reason}"


def _ensure_property_source_listing_cache_schema() -> bool:
    global _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY
    if _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY:
        return True
    if not _property_search_run_database_url():
        return False
    with _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_LOCK:
        if _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY:
            return True
        try:
            with _property_search_run_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS property_source_listing_cache (
                            cache_key TEXT PRIMARY KEY,
                            source_url TEXT NOT NULL DEFAULT '',
                            listing_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
                            provider_filter_pushdown JSONB NOT NULL DEFAULT '{}'::jsonb,
                            stored_at_epoch DOUBLE PRECISION NOT NULL,
                            stored_at TIMESTAMPTZ NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_property_source_listing_cache_stored_at
                        ON property_source_listing_cache(stored_at_epoch DESC)
                        """
                    )
        except Exception:
            return False
        _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY = True
        return True


def _property_source_listing_cache_prune_postgres() -> None:
    if not _ensure_property_source_listing_cache_schema():
        return
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                if retention_seconds > 0:
                    cur.execute(
                        "DELETE FROM property_source_listing_cache WHERE stored_at_epoch < %s",
                        (time.time() - float(retention_seconds),),
                    )
                cur.execute(
                    """
                    DELETE FROM property_source_listing_cache
                    WHERE cache_key IN (
                        SELECT cache_key
                        FROM property_source_listing_cache
                        ORDER BY stored_at_epoch DESC
                        OFFSET %s
                    )
                    """,
                    (_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES,),
                )
    except Exception:
        return


def _property_source_listing_cache_get_postgres(cache_key: str) -> dict[str, object]:
    normalized_key = str(cache_key or "").strip()[:240]
    if not normalized_key or not _ensure_property_source_listing_cache_schema():
        return {}
    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cache_key, source_url, listing_urls, provider_filter_pushdown, stored_at_epoch
                    FROM property_source_listing_cache
                    WHERE cache_key = %s
                    """,
                    (normalized_key,),
                )
                row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    return _property_source_listing_cache_normalize_row(
        row[0],
        {
            "source_url": row[1],
            "listing_urls": row[2],
            "provider_filter_pushdown": row[3],
            "stored_at_epoch": row[4],
        },
    )


def _property_source_listing_cache_put_postgres(row: dict[str, object]) -> bool:
    normalized = _property_source_listing_cache_normalize_row(row.get("cache_key"), row)
    if not normalized or not _ensure_property_source_listing_cache_schema():
        return False
    from psycopg.types.json import Json

    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_source_listing_cache (
                        cache_key,
                        source_url,
                        listing_urls,
                        provider_filter_pushdown,
                        stored_at_epoch,
                        stored_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (cache_key) DO UPDATE
                    SET source_url = EXCLUDED.source_url,
                        listing_urls = EXCLUDED.listing_urls,
                        provider_filter_pushdown = EXCLUDED.provider_filter_pushdown,
                        stored_at_epoch = EXCLUDED.stored_at_epoch,
                        stored_at = EXCLUDED.stored_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        normalized["cache_key"],
                        normalized["source_url"],
                        Json(list(normalized.get("listing_urls") or [])),
                        Json(dict(normalized.get("provider_filter_pushdown") or {})),
                        float(normalized.get("stored_at_epoch") or time.time()),
                    ),
                )
        _property_source_listing_cache_prune_postgres()
        return True
    except Exception:
        return False


def _property_source_listing_cache_persist_snapshot(snapshot: dict[str, dict[str, object]]) -> None:
    global _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME, _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH
    path = _property_source_listing_cache_path()
    if path is None:
        return
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    try:
        with _property_source_listing_cache_file_lock(path):
            merged_snapshot = dict(snapshot)
            try:
                existing_payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except Exception:
                _property_source_listing_cache_quarantine_corrupt_file(path, reason="persist_existing_json_invalid")
                existing_payload = {}
            existing_entries = existing_payload.get("entries") if isinstance(existing_payload, dict) else {}
            if isinstance(existing_entries, dict):
                for raw_key, raw_row in existing_entries.items():
                    cache_key = str(raw_key or "").strip()[:240]
                    if not cache_key or not isinstance(raw_row, dict):
                        continue
                    try:
                        stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
                    except Exception:
                        stored_at = 0.0
                    if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
                        continue
                    urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
                    if not urls:
                        continue
                    existing_row = dict(merged_snapshot.get(cache_key) or {})
                    try:
                        existing_stored_at = float(existing_row.get("stored_at_epoch") or 0.0)
                    except Exception:
                        existing_stored_at = 0.0
                    if existing_row and existing_stored_at >= stored_at:
                        continue
                    merged_snapshot[cache_key] = {
                        "cache_key": cache_key,
                        "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
                        "listing_urls": urls[:250],
                        "stored_at_epoch": stored_at or now,
                        "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
                        if isinstance(raw_row.get("provider_filter_pushdown"), dict)
                        else {},
                    }
            merged_snapshot = dict(
                sorted(
                    merged_snapshot.items(),
                    key=lambda item: float(item[1].get("stored_at_epoch") or 0.0),
                    reverse=True,
                )[:_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES]
            )
            payload = {
                "version": _PROPERTY_SOURCE_LISTING_CACHE_VERSION,
                "schema_version": _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_VERSION,
                "stored_at": _now_iso(),
                "stored_at_epoch": now,
                "entry_count": len(merged_snapshot),
                "max_entries": _PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES,
                "lock_strategy": "fcntl",
                "entries": merged_snapshot,
            }
            temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temp_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
                temp_path.replace(path)
                with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
                    _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = str(path)
                    try:
                        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = float(path.stat().st_mtime)
                    except Exception:
                        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        return


def _property_source_listing_cache_load() -> None:
    global _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME, _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH
    path = _property_source_listing_cache_path()
    path_text = str(path) if path is not None else ""
    try:
        path_mtime = float(path.stat().st_mtime) if path is not None and path.exists() else 0.0
    except Exception:
        path_mtime = 0.0
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        if (
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH == path_text
            and _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME == path_mtime
        ):
            return
    if path is None or path_mtime <= 0.0:
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = path_mtime
        return
    try:
        with _property_source_listing_cache_file_lock(path):
            parsed = json.loads(path.read_text(encoding="utf-8"))
            try:
                loaded_mtime = float(path.stat().st_mtime)
            except Exception:
                loaded_mtime = path_mtime
    except Exception:
        try:
            with _property_source_listing_cache_file_lock(path):
                _property_source_listing_cache_quarantine_corrupt_file(path, reason="load_json_invalid")
        except Exception:
            pass
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
        return
    entries = parsed.get("entries") if isinstance(parsed, dict) else {}
    if not isinstance(entries, dict):
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime
        return
    loaded_rows: dict[str, dict[str, object]] = {}
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    for raw_key, raw_row in entries.items():
        cache_key = str(raw_key or "").strip()[:240]
        if not cache_key or not isinstance(raw_row, dict):
            continue
        try:
            stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
        except Exception:
            stored_at = 0.0
        if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
            continue
        urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
        if not urls:
            continue
        loaded_rows[cache_key] = {
            "cache_key": cache_key,
            "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
            "listing_urls": urls[:250],
            "stored_at_epoch": stored_at or now,
            "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
            if isinstance(raw_row.get("provider_filter_pushdown"), dict)
            else {},
        }
    if not loaded_rows:
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime
        return
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        for key, row in loaded_rows.items():
            existing = dict(_PROPERTY_SOURCE_LISTING_CACHE.get(key) or {})
            try:
                existing_stored_at = float(existing.get("stored_at_epoch") or 0.0)
            except Exception:
                existing_stored_at = 0.0
            if existing and existing_stored_at >= float(row.get("stored_at_epoch") or 0.0):
                continue
            _PROPERTY_SOURCE_LISTING_CACHE[key] = row
        _property_source_listing_cache_prune_locked()
        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime


def _property_source_listing_cache_get(cache_key: str, *, allow_stale: bool = False) -> tuple[tuple[str, ...], dict[str, object]]:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return (), {}
    backend = _property_source_listing_cache_backend()
    if backend == "postgres":
        postgres_row = _property_source_listing_cache_get_postgres(normalized_key)
        if postgres_row:
            with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
                _PROPERTY_SOURCE_LISTING_CACHE[normalized_key] = postgres_row
            return _property_source_listing_cache_row_state(
                cache_key=normalized_key,
                row=postgres_row,
                allow_stale=allow_stale,
                persistence="postgres",
            )
    if backend == "file":
        _property_source_listing_cache_load()
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        row = dict(_PROPERTY_SOURCE_LISTING_CACHE.get(normalized_key) or {})
    if not row:
        return (), {}
    return _property_source_listing_cache_row_state(
        cache_key=normalized_key,
        row=row,
        allow_stale=allow_stale,
        persistence=backend if backend in {"file", "memory"} else "memory",
    )


def _property_source_listing_cache_put(
    cache_key: str,
    *,
    source_url: str,
    listing_urls: tuple[str, ...],
    source_spec: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return {"status": "disabled", "cache_key": "", "listing_total": len(listing_urls)}
    urls = tuple(str(value or "").strip() for value in listing_urls if str(value or "").strip())
    spec = dict(source_spec or {})
    row = {
        "cache_key": normalized_key,
        "source_url": urllib.parse.urldefrag(str(source_url or "").strip())[0],
        "listing_urls": list(urls[:250]),
        "stored_at_epoch": time.time(),
        "provider_filter_pushdown": dict(spec.get("provider_filter_pushdown") or {})
        if isinstance(spec.get("provider_filter_pushdown"), dict)
        else {},
    }
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        _PROPERTY_SOURCE_LISTING_CACHE[normalized_key] = row
        _property_source_listing_cache_prune_locked()
        snapshot = _property_source_listing_cache_snapshot_locked()
    backend = _property_source_listing_cache_backend()
    persisted_backend = backend
    if backend == "file":
        _property_source_listing_cache_persist_snapshot(snapshot)
    elif backend == "postgres":
        persisted_backend = "postgres" if _property_source_listing_cache_put_postgres(row) else "memory"
    return {
        "status": "stored",
        "cache_key": normalized_key,
        "listing_total": len(urls),
        "persistence": persisted_backend,
        "ttl_seconds": _property_source_listing_cache_ttl_seconds(),
    }
