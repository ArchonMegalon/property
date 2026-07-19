from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.product import privacy_lifecycle_storage as storage
from app.product.property_search_schema import migrate_property_search_schema


def _database_url() -> str:
    value = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not value:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    return value


def test_disposable_postgres_privacy_lifecycle_is_migrated_durable_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    namespace = f"property_privacy_{uuid4().hex}"
    scoped_url = make_conninfo(
        database_url,
        # Keep the disposable namespace closed. A previously migrated public
        # schema must not satisfy an unqualified lookup after this test drops
        # its own durable table for the fail-closed assertion below.
        options=f"-csearch_path={namespace}",
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_PROPERTY_SEARCH_ERASURE_SECRET",
        "privacy-postgres-erasure-secret-at-least-32-bytes",
    )
    storage.clear_privacy_lifecycle_memory_for_tests()

    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
    try:
        # Reproduce the exact table shape created by the removed runtime DDL so
        # migration v15 proves that it safely adopts an existing durable store.
        with psycopg.connect(scoped_url, autocommit=True, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE property_account_privacy_requests (
                        principal_key TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        idempotency_key_hash TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'awaiting_confirmation',
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (principal_key, request_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX idx_property_privacy_request_idempotency
                    ON property_account_privacy_requests(principal_key, idempotency_key_hash)
                    WHERE idempotency_key_hash <> ''
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX idx_property_privacy_request_status_updated
                    ON property_account_privacy_requests(status, updated_at DESC)
                    """
                )
        result = migrate_property_search_schema(scoped_url, applied_by="privacy-postgres-test")
        assert result.current_version >= 15

        record = {
            "principal_key": f"hmac-sha256:{'a' * 64}",
            "request_id": "erase_postgres",
            "idempotency_key_hash": f"hmac-sha256:{'b' * 64}",
            "status": "completed",
            "created_at": "2026-07-19T10:00:00+00:00",
            "updated_at": "2026-07-19T10:01:00+00:00",
            "retention_tombstone": {
                "customer_data_access_blocked_at": "2026-07-19T10:01:00+00:00",
                "contains_raw_account_identifier": False,
            },
        }
        postgres = {
            "database_url": scoped_url,
            "storage_backend": "postgres",
            "runtime_mode": "test",
        }
        saved = storage.put_privacy_request_record(record, **postgres)
        assert saved["request_id"] == "erase_postgres"
        assert storage.get_privacy_request_record(
            principal_key=str(record["principal_key"]),
            request_id="erase_postgres",
            **postgres,
        ) == saved
        assert storage.find_privacy_request_by_idempotency(
            principal_key=str(record["principal_key"]),
            idempotency_key_hash=str(record["idempotency_key_hash"]),
            **postgres,
        ) == saved
        assert storage.list_privacy_request_records(
            principal_key=str(record["principal_key"]),
            **postgres,
        ) == (saved,)

        with psycopg.connect(scoped_url, autocommit=True, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json->'retention_tombstone'->>'contains_raw_account_identifier'
                    FROM property_account_privacy_requests
                    WHERE principal_key = %s AND request_id = %s
                    """,
                    (record["principal_key"], record["request_id"]),
                )
                assert cur.fetchone() == ("false",)

        storage.put_privacy_request_record(
            record,
            storage_backend="memory",
            runtime_mode="test",
        )
        with psycopg.connect(scoped_url, autocommit=True, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE property_account_privacy_requests")
        with pytest.raises(psycopg.Error):
            storage.get_privacy_request_record(
                principal_key=str(record["principal_key"]),
                request_id="erase_postgres",
                **postgres,
            )
    finally:
        with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(namespace)
                    )
                )
