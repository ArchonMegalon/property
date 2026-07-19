from __future__ import annotations

import pytest

from app.product import privacy_lifecycle_storage as storage


@pytest.fixture(autouse=True)
def _clear_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    storage.clear_privacy_lifecycle_memory_for_tests()
    monkeypatch.setenv("PROPERTYQUARRY_PRIVACY_LOOKUP_SECRET", "privacy-storage-test-secret")


def _record(*, request_id: str = "erase_test", idempotency: str = "idem_test") -> dict[str, object]:
    return {
        "principal_key": f"hmac-sha256:{'a' * 64}",
        "request_id": request_id,
        "idempotency_key_hash": f"hmac-sha256:{'b' * 64}" if idempotency else "",
        "status": "awaiting_confirmation",
        "created_at": "2026-07-19T10:00:00+00:00",
        "updated_at": "2026-07-19T10:00:00+00:00",
        "retention_tombstone": {
            "contains_raw_account_identifier": False,
            "backup_restore_action": "reapply_tombstone_before_service_start",
        },
    }


def test_privacy_storage_requires_an_explicit_backend_and_forbids_prod_memory() -> None:
    assert storage.resolve_privacy_lifecycle_storage_backend(
        storage_backend="memory",
        runtime_mode="test",
    ) == "memory"
    assert storage.resolve_privacy_lifecycle_storage_backend(
        database_url="postgresql://disposable/privacy",
        storage_backend="auto",
        runtime_mode="dev",
    ) == "postgres"

    with pytest.raises(RuntimeError, match="propertyquarry_privacy_storage_backend_required"):
        storage.resolve_privacy_lifecycle_storage_backend(
            storage_backend="auto",
            runtime_mode="dev",
        )
    with pytest.raises(RuntimeError, match="propertyquarry_privacy_postgres_required"):
        storage.resolve_privacy_lifecycle_storage_backend(
            storage_backend="memory",
            runtime_mode="prod",
        )
    with pytest.raises(RuntimeError, match="propertyquarry_privacy_database_url_required"):
        storage.resolve_privacy_lifecycle_storage_backend(
            storage_backend="postgres",
            runtime_mode="test",
        )
    with pytest.raises(RuntimeError, match="propertyquarry_privacy_storage_backend_invalid"):
        storage.resolve_privacy_lifecycle_storage_backend(
            database_url="postgresql://disposable/privacy",
            storage_backend="sqlite",
            runtime_mode="prod",
        )


def test_explicit_memory_storage_is_deep_copied_and_idempotent() -> None:
    first = storage.put_privacy_request_record(
        _record(),
        storage_backend="memory",
        runtime_mode="test",
    )
    duplicate = storage.put_privacy_request_record(
        _record(request_id="erase_duplicate"),
        storage_backend="memory",
        runtime_mode="test",
    )
    assert duplicate["request_id"] == first["request_id"]

    loaded = storage.get_privacy_request_record(
        principal_key=str(first["principal_key"]),
        request_id=str(first["request_id"]),
        storage_backend="memory",
        runtime_mode="test",
    )
    assert loaded == first
    assert loaded is not first


def test_postgres_read_and_write_failures_never_fall_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = storage.put_privacy_request_record(
        _record(),
        storage_backend="memory",
        runtime_mode="test",
    )

    def unavailable(_database_url: str):
        raise RuntimeError("postgres-unavailable")

    monkeypatch.setattr(storage, "_connect", unavailable)
    postgres = {
        "database_url": "postgresql://disposable/privacy",
        "storage_backend": "postgres",
        "runtime_mode": "test",
    }

    with pytest.raises(RuntimeError, match="postgres-unavailable"):
        storage.put_privacy_request_record(_record(request_id="erase_write"), **postgres)
    with pytest.raises(RuntimeError, match="postgres-unavailable"):
        storage.get_privacy_request_record(
            principal_key=str(row["principal_key"]),
            request_id=str(row["request_id"]),
            **postgres,
        )
    with pytest.raises(RuntimeError, match="postgres-unavailable"):
        storage.find_privacy_request_by_idempotency(
            principal_key=str(row["principal_key"]),
            idempotency_key_hash=str(row["idempotency_key_hash"]),
            **postgres,
        )
    with pytest.raises(RuntimeError, match="postgres-unavailable"):
        storage.list_privacy_request_records(
            principal_key=str(row["principal_key"]),
            **postgres,
        )


def test_postgres_runtime_issues_no_ddl_and_empty_reads_do_not_use_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_row = storage.put_privacy_request_record(
        _record(),
        storage_backend="memory",
        runtime_mode="test",
    )
    statements: list[str] = []

    class Cursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, _params: object = None) -> None:
            statements.append(" ".join(str(sql).split()))

        def fetchall(self) -> list[object]:
            return []

        def fetchone(self) -> None:
            return None

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(storage, "_connect", lambda _database_url: Connection())
    monkeypatch.setattr(storage, "_json_value", lambda value: value)
    postgres = {
        "database_url": "postgresql://disposable/privacy",
        "storage_backend": "postgres",
        "runtime_mode": "test",
    }

    storage.put_privacy_request_record(_record(request_id="erase_postgres"), **postgres)
    assert storage.get_privacy_request_record(
        principal_key=str(memory_row["principal_key"]),
        request_id=str(memory_row["request_id"]),
        **postgres,
    ) is None
    assert storage.list_privacy_request_records(
        principal_key=str(memory_row["principal_key"]),
        **postgres,
    ) == ()

    assert statements
    assert all(not statement.startswith(("CREATE ", "ALTER ", "DROP ")) for statement in statements)
