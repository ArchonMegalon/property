from __future__ import annotations

from datetime import datetime, timezone
import os
import threading
from uuid import uuid4

import pytest

from app.product.property_search_schema import migrate_property_search_schema
from app.repositories.delivery_outbox_postgres import PostgresDeliveryOutboxRepository


def _database_url() -> str:
    value = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not value:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    return value


def test_postgres_advisory_claim_is_replica_safe_and_idempotent() -> None:
    database_url = _database_url()
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    namespace = f"delivery_outbox_contract_{uuid4().hex}"
    isolated_url = make_conninfo(
        database_url,
        options=f"-csearch_path={namespace},public",
    )
    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
    try:
        migrate_property_search_schema(
            isolated_url,
            applied_by="delivery-outbox-postgres-contract",
        )
        first_repository = PostgresDeliveryOutboxRepository(isolated_url)
        second_repository = PostgresDeliveryOutboxRepository(isolated_url)
        row = first_repository.enqueue(
            channel="email",
            recipient="principal@example.com",
            content='{"digest_key":"memo"}',
            metadata={
                "principal_id": "principal-1",
                "provider_idempotency_supported": True,
                "max_attempts": 3,
            },
            principal_id="principal-1",
            idempotency_key="morning-memo:principal-1:2026-07-13",
        )
        duplicate = second_repository.enqueue(
            channel="email",
            recipient="principal@example.com",
            content='{"digest_key":"memo"}',
            metadata={"principal_id": "principal-1"},
            principal_id="principal-1",
            idempotency_key="morning-memo:principal-1:2026-07-13",
        )
        assert duplicate.delivery_id == row.delivery_id

        barrier = threading.Barrier(3)
        claims = []
        observed_at = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)

        def claim(repository, owner: str) -> None:  # noqa: ANN001
            barrier.wait()
            claims.append(
                repository.claim(
                    row.delivery_id,
                    lease_owner=owner,
                    lease_seconds=60,
                    now=observed_at,
                )
            )

        threads = [
            threading.Thread(target=claim, args=(first_repository, "scheduler-a")),
            threading.Thread(target=claim, args=(second_repository, "scheduler-b")),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        winners = [candidate for candidate in claims if candidate is not None]
        assert len(winners) == 1
        assert winners[0].lease_owner in {"scheduler-a", "scheduler-b"}
    finally:
        with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(namespace)
                    )
                )
