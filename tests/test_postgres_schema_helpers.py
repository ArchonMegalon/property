from __future__ import annotations

from app.repositories.postgres_schema import (
    add_column_if_missing,
    create_index_if_missing,
    drop_index_if_present,
)


class _Cursor:
    def __init__(self, *, columns: set[tuple[str, str]] | None = None, indexes: set[str] | None = None) -> None:
        self.columns = columns or set()
        self.indexes = indexes or set()
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self._next_result: tuple[object, ...] | None = None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if "information_schema.columns" in normalized:
            table = str((params or ("", "", ""))[1])
            column = str((params or ("", "", ""))[2])
            self._next_result = (1,) if (table, column) in self.columns else None
            return
        if "to_regclass" in normalized:
            ref = str((params or ("",))[0])
            index_name = ref.rsplit(".", 1)[-1]
            self._next_result = (ref,) if index_name in self.indexes else (None,)
            return
        self._next_result = None

    def fetchone(self) -> tuple[object, ...] | None:
        return self._next_result


def test_add_column_if_missing_skips_existing_column() -> None:
    cur = _Cursor(columns={("observation_events", "source_id")})

    add_column_if_missing(cur, "observation_events", "source_id", "ALTER TABLE observation_events ADD COLUMN source_id TEXT")

    assert [sql for sql, _params in cur.executed if sql.startswith("ALTER TABLE")] == []


def test_add_column_if_missing_runs_ddl_for_missing_column() -> None:
    cur = _Cursor()

    add_column_if_missing(cur, "observation_events", "source_id", "ALTER TABLE observation_events ADD COLUMN source_id TEXT")

    assert any(sql == "ALTER TABLE observation_events ADD COLUMN source_id TEXT" for sql, _params in cur.executed)


def test_index_helpers_skip_existing_indexes_and_drop_only_present_indexes() -> None:
    cur = _Cursor(indexes={"idx_observation_events_created", "idx_old"})

    create_index_if_missing(cur, "idx_observation_events_created", "CREATE INDEX idx_observation_events_created")
    drop_index_if_present(cur, "idx_missing", "DROP INDEX idx_missing")
    drop_index_if_present(cur, "idx_old", "DROP INDEX idx_old")

    statements = [sql for sql, _params in cur.executed]
    assert "CREATE INDEX idx_observation_events_created" not in statements
    assert "DROP INDEX idx_missing" not in statements
    assert "DROP INDEX idx_old" in statements
