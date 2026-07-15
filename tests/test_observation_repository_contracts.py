from __future__ import annotations

from app.repositories.observation import InMemoryObservationEventRepository
from app.repositories.observation_postgres import PostgresObservationEventRepository


def test_in_memory_matching_filters_before_limit() -> None:
    repository = InMemoryObservationEventRepository()
    target = repository.append(
        "principal-a",
        "support",
        "support_request_created",
        {"request_id": "support_target"},
    )
    for index in range(20):
        repository.append(
            "principal-a",
            "product",
            "unrelated_event",
            {"index": index},
        )

    rows = repository.list_recent_matching(
        limit=1,
        principal_id="principal-a",
        channel="support",
        event_types=("support_request_created",),
    )

    assert rows == [target]


def test_postgres_matching_applies_filters_before_limit() -> None:
    executed: dict[str, object] = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            executed["query"] = query
            executed["params"] = params

        def fetchall(self) -> list[tuple[object, ...]]:
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self) -> Cursor:
            return Cursor()

    repository = object.__new__(PostgresObservationEventRepository)
    repository._database_url = "postgresql://unused"  # type: ignore[attr-defined]
    repository._connect = lambda: Connection()  # type: ignore[method-assign]

    rows = repository.list_recent_matching(
        limit=8,
        principal_id="principal-a",
        channel="support",
        event_types=("support_request_created",),
    )

    query = str(executed["query"])
    assert rows == []
    assert query.index("AND channel = %s") < query.index("LIMIT %s")
    assert query.index("AND event_type = ANY(%s)") < query.index("LIMIT %s")
    assert executed["params"] == (
        "principal-a",
        "support",
        ["support_request_created"],
        8,
    )
