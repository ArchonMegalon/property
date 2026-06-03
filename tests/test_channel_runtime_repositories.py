from __future__ import annotations

from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.observation import InMemoryObservationEventRepository


def test_inmemory_observation_dedupe_key_returns_existing_row() -> None:
    repo = InMemoryObservationEventRepository()
    first = repo.append(
        principal_id="exec-1",
        channel="email",
        event_type="thread.opened",
        payload={"subject": "A"},
        dedupe_key="obs-1",
    )
    second = repo.append(
        principal_id="exec-1",
        channel="email",
        event_type="thread.opened",
        payload={"subject": "B"},
        dedupe_key="obs-1",
    )
    assert second.observation_id == first.observation_id
    assert len(repo.list_recent(limit=10)) == 1


def test_inmemory_outbox_idempotency_and_retry() -> None:
    repo = InMemoryDeliveryOutboxRepository()
    first = repo.enqueue(
        channel="slack",
        recipient="U1",
        content="hello",
        metadata={},
        idempotency_key="delivery-1",
    )
    second = repo.enqueue(
        channel="slack",
        recipient="U1",
        content="hello-again",
        metadata={},
        idempotency_key="delivery-1",
    )
    assert second.delivery_id == first.delivery_id

    failed = repo.mark_failed(first.delivery_id, error="temporary", next_attempt_at=None, dead_letter=False)
    assert failed is not None
    assert failed.status == "retry"
    assert failed.attempt_count == 1
    assert failed.last_error == "temporary"

    pending = repo.list_pending(limit=10)
    assert any(row.delivery_id == first.delivery_id for row in pending)
