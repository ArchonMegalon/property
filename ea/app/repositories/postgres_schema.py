from __future__ import annotations


DEFAULT_SCHEMA_LOCK_TIMEOUT_MS = 1500
DEFAULT_SCHEMA_STATEMENT_TIMEOUT_MS = 7000


def configure_schema_timeouts(
    conn,  # type: ignore[no-untyped-def]
    *,
    lock_timeout_ms: int = DEFAULT_SCHEMA_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_SCHEMA_STATEMENT_TIMEOUT_MS,
) -> None:
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = %s", (f"{max(1, int(lock_timeout_ms))}ms",))
        cur.execute("SET statement_timeout = %s", (f"{max(1, int(statement_timeout_ms))}ms",))


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
