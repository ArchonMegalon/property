from __future__ import annotations

import ast
from pathlib import Path

from app.repositories.postgres_schema import (
    add_column_if_missing,
    create_index_if_missing,
    drop_index_if_present,
    repository_schema_ddl_enabled,
)


ROOT = Path(__file__).resolve().parents[1]
DDL_MARKERS = ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX", "DROP INDEX")


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


def test_repository_schema_ddl_is_fail_closed_for_production_runtime_roles() -> None:
    for role in ("", "api", "worker", "scheduler", "render-tools", "unknown-runtime"):
        assert not repository_schema_ddl_enabled(runtime_mode="prod", role=role)
        assert not repository_schema_ddl_enabled(runtime_mode="production", role=role)


def test_repository_schema_ddl_remains_available_to_bootstrap_and_non_production() -> None:
    for role in ("bootstrap", "migrate", "migration", "property-search-migrate"):
        assert repository_schema_ddl_enabled(runtime_mode="prod", role=role)
    assert repository_schema_ddl_enabled(runtime_mode="dev", role="api")
    assert repository_schema_ddl_enabled(runtime_mode="test", role="worker")
    assert repository_schema_ddl_enabled(runtime_mode="", role="scheduler")


def test_provider_binding_constructor_does_not_connect_for_production_runtime_roles(monkeypatch) -> None:
    from app.repositories.provider_bindings_postgres import (
        PostgresProviderBindingRepository,
    )

    def _unexpected_connect(_self):  # type: ignore[no-untyped-def]
        raise AssertionError("production runtime attempted repository schema DDL")

    monkeypatch.setattr(PostgresProviderBindingRepository, "_connect", _unexpected_connect)
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")
    for role in ("api", "worker", "scheduler"):
        monkeypatch.setenv("EA_ROLE", role)
        repository = PostgresProviderBindingRepository(
            "postgresql://runtime.invalid/property"
        )

        assert repository._database_url == "postgresql://runtime.invalid/property"


def test_every_runtime_schema_initializer_has_production_role_guard() -> None:
    guarded: list[str] = []
    unguarded: list[str] = []
    for path in sorted((ROOT / "ea" / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in {"__init__", "_ensure_schema", "ensure_schema"}:
                continue
            strings = (
                value.value.upper()
                for value in ast.walk(node)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
            if not any(marker in sql for sql in strings for marker in DDL_MARKERS):
                continue
            label = f"{path.relative_to(ROOT)}:{node.name}"
            calls = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            if "repository_schema_ddl_enabled" in calls:
                guarded.append(label)
            else:
                unguarded.append(label)

    assert guarded
    assert unguarded == []
