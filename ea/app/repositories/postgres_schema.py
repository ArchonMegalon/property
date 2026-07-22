from __future__ import annotations

import os


DEFAULT_SCHEMA_LOCK_TIMEOUT_MS = 1500
DEFAULT_SCHEMA_STATEMENT_TIMEOUT_MS = 7000
_PRODUCTION_RUNTIME_MODES = frozenset({"prod", "production"})
_SCHEMA_DDL_ROLES = frozenset(
    {
        "bootstrap",
        "migrate",
        "migration",
        "property-search-migrate",
    }
)


def repository_schema_ddl_enabled(
    *,
    runtime_mode: str | None = None,
    role: str | None = None,
) -> bool:
    """Keep repository DDL out of long-lived production processes.

    Local development retains the historical self-bootstrap behavior. In
    production, only a dedicated one-shot migration/bootstrap role may create
    or alter schema objects; API, worker, scheduler, and other runtime roles
    must start with data-plane privileges only.
    """

    resolved_mode = str(
        runtime_mode
        if runtime_mode is not None
        else os.environ.get("EA_RUNTIME_MODE") or ""
    ).strip().lower()
    if resolved_mode not in _PRODUCTION_RUNTIME_MODES:
        return True
    resolved_role = str(
        role if role is not None else os.environ.get("EA_ROLE") or ""
    ).strip().lower()
    return resolved_role in _SCHEMA_DDL_ROLES


def configure_schema_timeouts(
    conn,  # type: ignore[no-untyped-def]
    *,
    lock_timeout_ms: int = DEFAULT_SCHEMA_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_SCHEMA_STATEMENT_TIMEOUT_MS,
) -> None:
    lock_ms = max(1, int(lock_timeout_ms))
    statement_ms = max(1, int(statement_timeout_ms))
    with conn.cursor() as cur:
        cur.execute(f"SET lock_timeout = '{lock_ms}ms'")
        cur.execute(f"SET statement_timeout = '{statement_ms}ms'")


def column_exists(cur, table_name: str, column_name: str, *, schema_name: str = "public") -> bool:  # type: ignore[no-untyped-def]
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (schema_name, table_name, column_name),
    )
    return cur.fetchone() is not None


def add_column_if_missing(cur, table_name: str, column_name: str, ddl: str) -> None:  # type: ignore[no-untyped-def]
    if column_exists(cur, table_name, column_name):
        return
    cur.execute(ddl)


def index_exists(cur, index_name: str, *, schema_name: str = "public") -> bool:  # type: ignore[no-untyped-def]
    cur.execute("SELECT to_regclass(%s)", (f"{schema_name}.{index_name}",))
    row = cur.fetchone()
    return bool(row and row[0])


def create_index_if_missing(cur, index_name: str, ddl: str) -> None:  # type: ignore[no-untyped-def]
    if index_exists(cur, index_name):
        return
    cur.execute(ddl)


def drop_index_if_present(cur, index_name: str, ddl: str) -> None:  # type: ignore[no-untyped-def]
    if not index_exists(cur, index_name):
        return
    cur.execute(ddl)
