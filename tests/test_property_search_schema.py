from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.product import property_search_schema as schema


def _relations_for(version: int) -> set[str]:
    if version == 1:
        return {
            "property_search_runs",
            "idx_property_search_runs_updated",
            "idx_property_search_runs_principal_updated",
            "idx_property_search_runs_status_updated",
            "idx_property_search_runs_principal_status_updated",
        }
    if version == 2:
        return {
            "property_search_work_jobs",
            "idx_property_search_work_idempotency",
            "idx_property_search_work_principal_run",
            "idx_property_search_work_claim",
        }
    if version == 3:
        return {
            "property_source_listing_cache",
            "idx_property_source_listing_cache_stored_at",
        }
    if version == 4:
        return {
            "delivery_outbox",
            "idx_delivery_outbox_status_created",
            "idx_delivery_outbox_principal_idempotency_unique",
            "idx_delivery_outbox_retry_schedule",
            "idx_delivery_outbox_principal_status_created",
            "idx_delivery_outbox_claim",
        }
    if version == 5:
        return {
            "property_content_jobs",
            "property_content_job_events",
            "property_content_webhook_events",
            "idx_property_content_jobs_status_updated",
            "idx_property_content_jobs_claim",
            "idx_property_content_job_events_packet_sequence",
            "idx_property_content_webhook_status_updated",
            "idx_property_content_webhook_claim",
        }
    raise AssertionError(f"unexpected migration version: {version}")


class _FakeDatabase:
    def __init__(self) -> None:
        self.ledger: dict[int, tuple[str, str]] = {}
        self.relations: set[str] = set()
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_migration_version = 0

    def connect(self, _database_url: str, *, autocommit: bool):
        return _FakeConnection(self, autocommit=autocommit)

    def seed_migration(self, version: int, *, checksum: str = "") -> None:
        migration = schema.PROPERTY_SEARCH_MIGRATIONS[version - 1]
        self.ledger[version] = (migration.name, checksum or migration.checksum)
        self.relations.update(_relations_for(version))
        self.relations.add(schema.SCHEMA_LEDGER_TABLE)


class _FakeConnection:
    def __init__(self, database: _FakeDatabase, *, autocommit: bool) -> None:
        self.database = database
        self.autocommit = autocommit
        self.closed = False
        self._snapshot = (
            deepcopy(database.ledger),
            set(database.relations),
        )

    def cursor(self):
        return _FakeCursor(self.database)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        self.close()
        return False

    def commit(self) -> None:
        self.database.commits += 1
        self._snapshot = (
            deepcopy(self.database.ledger),
            set(self.database.relations),
        )

    def rollback(self) -> None:
        self.database.rollbacks += 1
        self.database.ledger = deepcopy(self._snapshot[0])
        self.database.relations = set(self._snapshot[1])

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self, database: _FakeDatabase) -> None:
        self.database = database
        self._rows: list[tuple[object, ...]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def execute(self, sql: str, params=None) -> None:  # noqa: ANN001
        normalized = " ".join(str(sql).split())
        arguments = tuple(params or ())
        self.database.executed.append((normalized, arguments))
        self._rows = []
        if "pg_advisory_xact_lock" in normalized:
            self._rows = [(None,)]
            return
        if normalized.startswith("CREATE TABLE IF NOT EXISTS propertyquarry_schema_migrations"):
            self.database.relations.add(schema.SCHEMA_LEDGER_TABLE)
            return
        if normalized.startswith("SELECT version, migration_name, checksum_sha256"):
            self._rows = [
                (version, name, checksum)
                for version, (name, checksum) in sorted(self.database.ledger.items())
            ]
            return
        if normalized.startswith("INSERT INTO propertyquarry_schema_migrations"):
            version = int(arguments[1])
            self.database.ledger[version] = (str(arguments[2]), str(arguments[3]))
            return
        if normalized.startswith("SELECT to_regclass"):
            relation = str(arguments[0])
            self._rows = [(relation if relation in self.database.relations else None,)]
            return
        for migration in schema.PROPERTY_SEARCH_MIGRATIONS:
            if str(sql) == migration.sql:
                if self.database.fail_migration_version == migration.version:
                    raise RuntimeError(f"synthetic migration {migration.version} failure")
                self.database.relations.update(_relations_for(migration.version))
                return

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


def test_clean_install_is_transactional_ordered_and_advisory_locked() -> None:
    database = _FakeDatabase()

    result = schema.migrate_property_search_schema(
        "postgresql://test/property",
        applied_by="release-test",
        connect=database.connect,
    )

    assert result.previous_version == 0
    assert result.current_version == schema.LATEST_PROPERTY_SEARCH_SCHEMA_VERSION
    assert result.applied_versions == (1, 2, 3, 4, 5)
    assert database.commits == 1
    assert database.rollbacks == 0
    assert tuple(database.ledger) == (1, 2, 3, 4, 5)
    assert "pg_advisory_xact_lock" in database.executed[0][0]
    assert database.executed[0][1] == (schema.SCHEMA_LOCK_ID,)
    for migration in schema.PROPERTY_SEARCH_MIGRATIONS:
        assert database.ledger[migration.version] == (
            migration.name,
            migration.checksum,
        )


def test_upgrade_from_run_schema_applies_queue_and_cache_once() -> None:
    database = _FakeDatabase()
    database.seed_migration(1)

    first = schema.migrate_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    database.executed.clear()
    second = schema.migrate_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )

    assert first.previous_version == 1
    assert first.applied_versions == (2, 3, 4, 5)
    assert second.previous_version == 5
    assert second.applied_versions == ()
    assert not any(
        sql == " ".join(migration.sql.split())
        for sql, _params in database.executed
        for migration in schema.PROPERTY_SEARCH_MIGRATIONS
    )


def test_upgrade_from_schema_v4_installs_only_durable_content_ledger() -> None:
    database = _FakeDatabase()
    for version in (1, 2, 3, 4):
        database.seed_migration(version)

    result = schema.migrate_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )

    assert result.previous_version == 4
    assert result.current_version == 5
    assert result.applied_versions == (5,)
    assert _relations_for(5).issubset(database.relations)
    executed_migrations = {
        migration.version
        for sql, _params in database.executed
        for migration in schema.PROPERTY_SEARCH_MIGRATIONS
        if sql == " ".join(migration.sql.split())
    }
    assert executed_migrations == {5}


def test_checksum_drift_and_version_gaps_fail_before_any_migration() -> None:
    drifted = _FakeDatabase()
    drifted.seed_migration(1, checksum="0" * 64)

    with pytest.raises(
        schema.PropertySearchSchemaDriftError,
        match="property_search_migration_checksum_drift:1",
    ):
        schema.migrate_property_search_schema(
            "postgresql://test/property",
            connect=drifted.connect,
        )
    assert drifted.rollbacks == 1
    assert tuple(drifted.ledger) == (1,)

    gapped = _FakeDatabase()
    gapped.seed_migration(2)
    with pytest.raises(
        schema.PropertySearchSchemaDriftError,
        match="property_search_migration_gap",
    ):
        schema.migrate_property_search_schema(
            "postgresql://test/property",
            connect=gapped.connect,
        )


def test_failed_upgrade_rolls_back_ledger_and_all_schema_changes() -> None:
    database = _FakeDatabase()
    database.fail_migration_version = 2

    with pytest.raises(RuntimeError, match="synthetic migration 2 failure"):
        schema.migrate_property_search_schema(
            "postgresql://test/property",
            connect=database.connect,
        )

    assert database.commits == 0
    assert database.rollbacks == 1
    assert database.ledger == {}
    assert database.relations == set()


def test_readiness_reports_missing_pending_drift_relation_and_ready() -> None:
    database = _FakeDatabase()
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.ready is False
    assert status.reason == "migration_ledger_missing"

    database.seed_migration(1)
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.reason == "migration_pending"
    assert status.current_version == 1

    database.ledger[1] = (database.ledger[1][0], "f" * 64)
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.reason == "property_search_migration_checksum_drift:1"

    database = _FakeDatabase()
    for version in (1, 2, 3, 4, 5):
        database.seed_migration(version)
    database.relations.remove("idx_property_search_work_claim")
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.reason == "required_relation_missing:idx_property_search_work_claim"

    database.relations.add("idx_property_search_work_claim")
    database.relations.remove("idx_delivery_outbox_claim")
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.reason == "required_relation_missing:idx_delivery_outbox_claim"

    database.relations.add("idx_delivery_outbox_claim")
    database.relations.remove("idx_property_content_webhook_claim")
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.reason == "required_relation_missing:idx_property_content_webhook_claim"

    database.relations.add("idx_property_content_webhook_claim")
    status = schema.inspect_property_search_schema(
        "postgresql://test/property",
        connect=database.connect,
    )
    assert status.ready is True
    assert status.reason == "schema_ready"
    assert status.current_version == 5


def test_runtime_schema_access_fails_closed_without_running_ddl() -> None:
    database = _FakeDatabase()

    with pytest.raises(
        schema.PropertySearchSchemaNotReadyError,
        match="migration_ledger_missing",
    ):
        schema.require_property_search_schema_ready(
            "postgresql://test/property",
            connect=database.connect,
        )

    executed = "\n".join(sql for sql, _params in database.executed).upper()
    assert "CREATE TABLE" not in executed
    assert "ALTER TABLE" not in executed
    assert "CREATE INDEX" not in executed

    for path in (
        Path("ea/app/product/property_search_storage.py"),
        Path("ea/app/product/property_search_work_queue.py"),
        Path("ea/app/repositories/delivery_outbox_postgres.py"),
        Path("ea/app/services/property_content_job_ledger.py"),
    ):
        runtime_source = path.read_text(encoding="utf-8").upper()
        assert "CREATE TABLE" not in runtime_source
        assert "ALTER TABLE" not in runtime_source
        assert "CREATE INDEX" not in runtime_source


def test_schema_readiness_is_mandatory_in_prod_and_opt_in_for_dev() -> None:
    for role in ("api", "worker", "scheduler"):
        assert schema.property_search_schema_readiness_required(
            runtime_mode="prod",
            role=role,
        )
    assert not schema.property_search_schema_readiness_required(
        runtime_mode="dev",
        role="api",
    )
    assert schema.property_search_schema_readiness_required(
        runtime_mode="dev",
        role="api",
        explicit="true",
    )


def test_container_readiness_requires_current_schema_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.container import ReadinessService

    database = _FakeDatabase()
    fake_psycopg = SimpleNamespace(
        connect=lambda _url, **kwargs: database.connect(
            _url,
            autocommit=bool(kwargs.get("autocommit")),
        )
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.delenv(
        "PROPERTYQUARRY_SEARCH_SCHEMA_READINESS_REQUIRED",
        raising=False,
    )
    settings = SimpleNamespace(
        database_url="postgresql://test/property",
        storage=SimpleNamespace(database_url="postgresql://test/property"),
        runtime_mode="prod",
        role="api",
    )
    readiness = ReadinessService(settings)

    ready, reason = readiness._probe_database()
    assert ready is False
    assert reason == "property_search_schema_not_ready:migration_ledger_missing"

    for version in (1, 2, 3, 4, 5):
        database.seed_migration(version)
    ready, reason = readiness._probe_database()
    assert ready is True
    assert reason == "postgres_ready:property_search_schema_v5"


def test_migration_checksums_are_stable_and_unique() -> None:
    checksums = [migration.checksum for migration in schema.PROPERTY_SEARCH_MIGRATIONS]

    assert [migration.version for migration in schema.PROPERTY_SEARCH_MIGRATIONS] == [1, 2, 3, 4, 5]
    assert checksums == [
        "4938925d3679ca592f67de1fb5f5c5538ce0e2c93dd2435ffe1204674d02a37e",
        "9beb0cbc778018c9ea7ee5939cbd25a86830a904a8c2bfe8454a022219a078a6",
        "f89e047a0ed002e2da26884077001a91c7f69faa57e5719ac73881d68a14d93a",
        "b4a28da18a3d31d328ffa13c67b90a8ae1b1c3b1920c980dafc2343d226a20c3",
        "4f54431f5a138f03d697837b2c0940462a51ed3b6bafae754f316a4757edfe23",
    ]
