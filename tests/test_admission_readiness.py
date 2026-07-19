from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import app.container as container_module
from app.container import ReadinessService
from app.services.admission_control import AdmissionBackendUnavailable


class _Cursor:
    def __init__(self, lane: str) -> None:
        self.lane = lane
        self._row: tuple[object, ...] | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, _params: object = ()) -> None:
        normalized = " ".join(sql.split())
        if normalized == "SELECT 1":
            self._row = (1,)
        elif "FROM property_search_erasure_key_state" in normalized:
            self._row = ("expected-key-id",)
        else:
            self._row = None

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, lane: str) -> None:
        self.lane = lane

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.lane)


def _settings(primary_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        runtime_mode="prod",
        role="api",
        database_url=primary_url,
    )


def test_prod_api_readiness_probes_admission_with_the_dedicated_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_url = "postgresql://api-runtime/property"
    admission_url = "postgresql://api-admission/property"
    connections: list[tuple[str, dict[str, object]]] = []

    def connect(database_url: str, **kwargs: object) -> _Connection:
        connections.append((database_url, dict(kwargs)))
        lane = "admission" if database_url == admission_url else "primary"
        return _Connection(lane)

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    monkeypatch.setenv(
        "PROPERTYQUARRY_API_ADMISSION_DATABASE_URL",
        admission_url,
    )
    from app.product import property_search_schema
    from app.product import property_search_storage

    monkeypatch.setattr(
        property_search_schema,
        "property_search_schema_readiness_required",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        property_search_schema,
        "inspect_property_search_schema_cursor",
        lambda _cursor: SimpleNamespace(
            ready=True,
            reason="ready",
            current_version=16,
        ),
    )
    monkeypatch.setattr(
        property_search_storage,
        "_property_search_erasure_key_id",
        lambda: "expected-key-id",
    )

    def probe(cursor: _Cursor) -> None:
        assert cursor.lane == "admission"

    monkeypatch.setattr(container_module, "probe_admission_cursor", probe)

    assert ReadinessService(_settings(primary_url))._probe_database() == (
        True,
        "postgres_ready:property_search_schema_v16",
    )
    assert connections == [
        (primary_url, {"autocommit": True}),
        (
            admission_url,
            {
                "autocommit": True,
                "connect_timeout": 5,
                "application_name": "propertyquarry-api-admission-readiness",
            },
        ),
    ]


def test_prod_api_readiness_fails_before_database_io_without_admission_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_connect(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing dedicated admission configuration reached database I/O")

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=forbidden_connect),
    )
    monkeypatch.delenv(
        "PROPERTYQUARRY_API_ADMISSION_DATABASE_URL",
        raising=False,
    )

    assert ReadinessService(
        _settings("postgresql://api-runtime/property")
    )._probe_database() == (
        False,
        "propertyquarry_admission_not_ready:"
        "propertyquarry_api_admission_database_url_required",
    )


def test_prod_api_readiness_preserves_bounded_admission_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_url = "postgresql://api-runtime/property"
    admission_url = "postgresql://api-admission/property"

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(
            connect=lambda database_url, **_kwargs: _Connection(
                "admission" if database_url == admission_url else "primary"
            )
        ),
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_API_ADMISSION_DATABASE_URL",
        admission_url,
    )
    from app.product import property_search_schema
    from app.product import property_search_storage

    monkeypatch.setattr(
        property_search_schema,
        "property_search_schema_readiness_required",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        property_search_schema,
        "inspect_property_search_schema_cursor",
        lambda _cursor: SimpleNamespace(
            ready=True,
            reason="ready",
            current_version=16,
        ),
    )
    monkeypatch.setattr(
        property_search_storage,
        "_property_search_erasure_key_id",
        lambda: "expected-key-id",
    )

    def fail_probe(_cursor: _Cursor) -> None:
        raise AdmissionBackendUnavailable("admission_backend_role_elevated")

    monkeypatch.setattr(
        container_module,
        "probe_admission_cursor",
        fail_probe,
    )

    assert ReadinessService(_settings(primary_url))._probe_database() == (
        False,
        "propertyquarry_admission_not_ready:admission_backend_role_elevated",
    )
