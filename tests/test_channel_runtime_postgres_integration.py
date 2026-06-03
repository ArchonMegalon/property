from __future__ import annotations

import os
import uuid

import pytest

from app.repositories.delivery_outbox_postgres import PostgresDeliveryOutboxRepository
from app.repositories.observation_postgres import PostgresObservationEventRepository


def _db_url() -> str:
    db_url = (os.environ.get("EA_TEST_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_DATABASE_URL is not set")
    return db_url


def test_postgres_observation_dedupe_key_returns_existing_row() -> None:
    repo = PostgresObservationEventRepository(_db_url())
    dedupe_key = f"obs-{uuid.uuid4()}"

    first = repo.append(
        principal_id="exec-1",
        channel="email",
        event_type="thread.opened",
        payload={"subject": "A"},
        source_id="gmail",
        external_id=str(uuid.uuid4()),
        dedupe_key=dedupe_key,
    )
    second = repo.append(
        principal_id="exec-1",
        channel="email",
        event_type="thread.opened",
        payload={"subject": "B"},
        source_id="gmail",
        external_id=str(uuid.uuid4()),
        dedupe_key=dedupe_key,
    )

    assert second.observation_id == first.observation_id
    listed = repo.list_recent(limit=10)
    assert any(row.observation_id == first.observation_id for row in listed)


def test_postgres_outbox_idempotency_and_retry() -> None:
    repo = PostgresDeliveryOutboxRepository(_db_url())
    idempotency_key = f"delivery-{uuid.uuid4()}"

    first = repo.enqueue(
        channel="slack",
        recipient="U1",
        content="hello",
        metadata={},
        idempotency_key=idempotency_key,
    )
    second = repo.enqueue(
        channel="slack",
        recipient="U1",
        content="hello-again",
        metadata={},
        idempotency_key=idempotency_key,
    )

    assert second.delivery_id == first.delivery_id

    failed = repo.mark_failed(first.delivery_id, error="temporary", next_attempt_at=None, dead_letter=False)
    assert failed is not None
    assert failed.status == "retry"
    assert failed.attempt_count == 1
    assert failed.last_error == "temporary"

    pending = repo.list_pending(limit=10)
    assert any(row.delivery_id == first.delivery_id for row in pending)
