from __future__ import annotations

from app.product import workspace_access_storage


class _FakeCursor:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, _params: object = None) -> None:
        self._calls.append(" ".join(str(sql).split()))


class _FakeConnection:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._calls)


def test_workspace_access_schema_is_cached_per_database_url(monkeypatch) -> None:
    calls: list[str] = []
    workspace_access_storage._SCHEMA_READY_DATABASE_URLS.clear()
    monkeypatch.setattr(workspace_access_storage, "_connect", lambda _database_url: _FakeConnection(calls))

    assert workspace_access_storage._ensure_workspace_access_schema("postgresql://example/db") is True
    first_call_count = len(calls)
    assert first_call_count > 1

    assert workspace_access_storage._ensure_workspace_access_schema("postgresql://example/db") is True
    assert len(calls) == first_call_count

    assert workspace_access_storage._ensure_workspace_access_schema("postgresql://example/other") is True
    assert len(calls) > first_call_count
