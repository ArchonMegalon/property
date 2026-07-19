from __future__ import annotations

import os
from queue import Empty
import secrets
import threading
import time
from uuid import uuid4

import pytest

from app.product import property_search_schema as schema
from app.services.admission_control import (
    ADMISSION_CAPACITY_STATE_TABLE,
    AdmissionBackendUnavailable,
    ConcurrencyDimension,
    PostgresAdmissionBackend,
    QuotaCharge,
)


def _close_backend_pool(backend: PostgresAdmissionBackend) -> None:
    while True:
        try:
            connection = backend._pool._idle.get_nowait()
        except Empty:
            return
        connection.close()


def _database_url() -> str:
    value = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not value:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    return value


def test_postgres_admission_is_atomic_across_backend_instances() -> None:
    database_url = _database_url()
    import psycopg
    from psycopg import sql

    namespace = f"propertyquarry_admission_{uuid4().hex}"

    def isolated_connect(_database_url: str, *, autocommit: bool):
        connection = psycopg.connect(
            database_url,
            autocommit=autocommit,
            connect_timeout=5,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(namespace)
                )
            )
        # The backend deliberately rolls every pooled connection back before
        # returning it to idle. Commit session initialization so that the test
        # schema remains authoritative after a readiness probe.
        connection.commit()
        return connection

    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
    try:
        with isolated_connect(database_url, autocommit=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema.PROPERTY_SEARCH_MIGRATIONS[15].sql)
            connection.commit()

        first_backend = PostgresAdmissionBackend(
            database_url,
            connect=isolated_connect,
            pool_size=1,
        )
        second_backend = PostgresAdmissionBackend(
            database_url,
            connect=isolated_connect,
            pool_size=1,
        )
        first_backend.probe()
        second_backend.probe()
        with isolated_connect(database_url, autocommit=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM propertyquarry_admission_quota_buckets"
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute("SELECT COUNT(*) FROM propertyquarry_admission_leases")
                assert cursor.fetchone()[0] == 0

        def read_only_connect(_database_url: str, *, autocommit: bool):
            return psycopg.connect(
                database_url,
                autocommit=autocommit,
                connect_timeout=5,
                options=(
                    f"-c search_path={namespace},public "
                    "-c default_transaction_read_only=on"
                ),
            )

        read_only_backend = PostgresAdmissionBackend(
            database_url,
            connect=read_only_connect,
            pool_size=1,
        )
        with pytest.raises(AdmissionBackendUnavailable):
            read_only_backend.probe()

        quota_barrier = threading.Barrier(2)
        quota_results: list[bool] = []
        quota_errors: list[Exception] = []

        def consume(backend: PostgresAdmissionBackend) -> None:
            try:
                quota_barrier.wait(timeout=5)
                quota_results.append(
                    backend.consume(
                        QuotaCharge(
                            key="integration:quota:shared",
                            units=1,
                            limit=1,
                            window_seconds=60,
                        )
                    ).allowed
                )
            except Exception as exc:  # pragma: no cover - asserted below
                quota_errors.append(exc)

        quota_threads = [
            threading.Thread(target=consume, args=(first_backend,)),
            threading.Thread(target=consume, args=(second_backend,)),
        ]
        for thread in quota_threads:
            thread.start()
        for thread in quota_threads:
            thread.join(timeout=10)

        assert not any(thread.is_alive() for thread in quota_threads)
        assert quota_errors == []
        assert sorted(quota_results) == [False, True]

        lease_barrier = threading.Barrier(2)
        lease_results = []
        lease_errors: list[Exception] = []

        def acquire(backend: PostgresAdmissionBackend) -> None:
            try:
                lease_barrier.wait(timeout=5)
                lease_results.append(
                    backend.acquire(
                        (ConcurrencyDimension("integration:lease:shared", 1),),
                        lease_seconds=60,
                    )
                )
            except Exception as exc:  # pragma: no cover - asserted below
                lease_errors.append(exc)

        lease_threads = [
            threading.Thread(target=acquire, args=(first_backend,)),
            threading.Thread(target=acquire, args=(second_backend,)),
        ]
        for thread in lease_threads:
            thread.start()
        for thread in lease_threads:
            thread.join(timeout=10)

        assert not any(thread.is_alive() for thread in lease_threads)
        assert lease_errors == []
        assert sorted(result.allowed for result in lease_results) == [False, True]
        winning_lease = next(result.lease_id for result in lease_results if result.allowed)
        first_backend.release(winning_lease)
        replacement = second_backend.acquire(
            (ConcurrencyDimension("integration:lease:shared", 1),),
            lease_seconds=60,
        )
        assert replacement.allowed
        second_backend.release(replacement.lease_id)

        strict = first_backend.acquire(
            (ConcurrencyDimension("integration:lease:drift", 1),),
            lease_seconds=60,
        )
        assert strict.allowed
        assert not second_backend.acquire(
            (ConcurrencyDimension("integration:lease:drift", 10),),
            lease_seconds=60,
        ).allowed
        first_backend.release(strict.lease_id)
        after_drain = second_backend.acquire(
            (ConcurrencyDimension("integration:lease:drift", 10),),
            lease_seconds=60,
        )
        assert after_drain.allowed
        second_backend.release(after_drain.lease_id)

        lax_first = second_backend.acquire(
            (ConcurrencyDimension("integration:lease:rolling-drift", 10),),
            lease_seconds=60,
        )
        assert lax_first.allowed
        assert not first_backend.acquire(
            (ConcurrencyDimension("integration:lease:rolling-drift", 1),),
            lease_seconds=60,
        ).allowed
        assert not second_backend.acquire(
            (ConcurrencyDimension("integration:lease:rolling-drift", 10),),
            lease_seconds=60,
        ).allowed
        second_backend.release(lax_first.lease_id)

        renewable = first_backend.acquire(
            (ConcurrencyDimension("integration:lease:renew", 1),),
            lease_seconds=1,
        )
        assert renewable.allowed
        assert first_backend.renew(renewable.lease_id, lease_seconds=30)
        time.sleep(1.1)
        assert not second_backend.acquire(
            (ConcurrencyDimension("integration:lease:renew", 1),),
            lease_seconds=1,
        ).allowed
        first_backend.release(renewable.lease_id)
        assert not first_backend.renew(renewable.lease_id, lease_seconds=30)
    finally:
        with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(namespace)
                    )
                )


def test_postgres_strict_role_timeouts_and_cleanup_in_disposable_database() -> None:
    database_url = _database_url()
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    suffix = uuid4().hex[:12]
    disposable_database = f"pq_admission_{suffix}"
    owner_role = f"pq_admission_owner_{suffix}"
    capacity_owner_role = f"pq_admission_capacity_{suffix}"
    runtime_role = f"pq_admission_runtime_{suffix}"
    runtime_schema = f"pq_admission_{suffix}"
    runtime_password = secrets.token_urlsafe(32)
    base_params = conninfo_to_dict(database_url)
    original_database = str(base_params.get("dbname") or "postgres")
    created_database = False
    created_owner_role = False
    created_capacity_owner_role = False
    created_runtime_role = False
    backends: list[PostgresAdmissionBackend] = []

    def _connect_params(*, database: str, role: str = "", password: str = "") -> dict[str, str]:
        params = dict(base_params)
        params["dbname"] = database
        if role:
            params["user"] = role
            params["password"] = password
        params["options"] = f"-c search_path={runtime_schema}"
        return params

    try:
        with psycopg.connect(
            **_connect_params(database=original_database),
            autocommit=True,
        ) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(owner_role))
                )
                created_owner_role = True
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(capacity_owner_role))
                )
                created_capacity_owner_role = True
                cursor.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(capacity_owner_role),
                        sql.Identifier(owner_role),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(runtime_role),
                        sql.Literal(runtime_password),
                    )
                )
                created_runtime_role = True
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(disposable_database),
                        sql.Identifier(owner_role),
                    )
                )
                created_database = True
                cursor.execute(
                    sql.SQL(
                        "REVOKE ALL PRIVILEGES ON DATABASE {} FROM PUBLIC"
                    ).format(sql.Identifier(disposable_database))
                )
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(disposable_database),
                        sql.Identifier(runtime_role),
                    )
                )

        with psycopg.connect(
            **_connect_params(database=disposable_database),
            autocommit=False,
        ) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(owner_role),
                    )
                )
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(
                        sql.Identifier(owner_role)
                    )
                )
                cursor.execute(
                    sql.SQL("SET LOCAL search_path TO {}").format(
                        sql.Identifier(runtime_schema)
                    )
                )
                cursor.execute(schema.PROPERTY_SEARCH_MIGRATIONS[15].sql)
                cursor.execute(
                    "SELECT set_config("
                    "'propertyquarry.admission_capacity_owner_role', %s, TRUE"
                    ")",
                    (capacity_owner_role,),
                )
                cursor.execute(schema.PROPERTY_SEARCH_MIGRATIONS[16].sql)
                cursor.execute("RESET ROLE")
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_role),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                        "{}.propertyquarry_admission_quota_buckets, "
                        "{}.propertyquarry_admission_leases TO {}"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_role),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT ON TABLE {}.{} TO {}"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                        sql.Identifier(runtime_role),
                    )
                )
            admin.commit()

        runtime_params = _connect_params(
            database=disposable_database,
            role=runtime_role,
            password=runtime_password,
        )

        def runtime_connect(_database_url: str, *, autocommit: bool):
            return psycopg.connect(**runtime_params, autocommit=autocommit)

        backend = PostgresAdmissionBackend(
            "postgresql://strict-runtime/disposable",
            connect=runtime_connect,
            pool_size=1,
            require_least_privilege=True,
            capacity_owner_role=capacity_owner_role,
            lock_timeout_ms=150,
            statement_timeout_ms=500,
            idle_transaction_timeout_ms=2_000,
        )
        backends.append(backend)
        backend.probe()

        admin_params = _connect_params(database=disposable_database)

        def elevated_connect(_database_url: str, *, autocommit: bool):
            return psycopg.connect(**admin_params, autocommit=autocommit)

        elevated = PostgresAdmissionBackend(
            "postgresql://elevated/disposable",
            connect=elevated_connect,
            pool_size=1,
            require_least_privilege=True,
        )
        backends.append(elevated)
        with pytest.raises(
            AdmissionBackendUnavailable,
            match="admission_backend_role_elevated",
        ):
            elevated.probe()

        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.propertyquarry_admission_quota_buckets "
                        "(bucket_key, window_index, window_seconds, used_units, "
                        "limit_units, expires_at, updated_at) "
                        "SELECT 'capacity:bulk:quota:' || value, 0, 60, 0, 1, "
                        "clock_timestamp() + interval '1 hour', clock_timestamp() "
                        "FROM generate_series(1, 25) AS value"
                    ).format(sql.Identifier(runtime_schema))
                )
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.propertyquarry_admission_leases "
                        "(lease_id, dimension_key, limit_units, acquired_at, expires_at) "
                        "SELECT md5('capacity:bulk:lease:' || value)::uuid, "
                        "'capacity:bulk:lease:' || value, 1, clock_timestamp(), "
                        "clock_timestamp() + interval '1 hour' "
                        "FROM generate_series(1, 25) AS value"
                    ).format(sql.Identifier(runtime_schema))
                )
            admin.commit()

        concurrent_barrier = threading.Barrier(8)
        concurrent_errors: list[Exception] = []

        def insert_concurrent_quota(index: int) -> None:
            try:
                with psycopg.connect(
                    **runtime_params,
                    autocommit=False,
                ) as connection:
                    with connection.cursor() as cursor:
                        concurrent_barrier.wait(timeout=5)
                        cursor.execute(
                            "INSERT INTO propertyquarry_admission_quota_buckets "
                            "(bucket_key, window_index, window_seconds, used_units, "
                            "limit_units, expires_at, updated_at) "
                            "VALUES (%s, 0, 60, 0, 1, "
                            "clock_timestamp() + interval '1 hour', "
                            "clock_timestamp())",
                            (f"capacity:concurrent:quota:{index}",),
                        )
                    connection.commit()
            except Exception as exc:  # pragma: no cover - asserted below
                concurrent_errors.append(exc)

        concurrent_threads = [
            threading.Thread(target=insert_concurrent_quota, args=(index,))
            for index in range(8)
        ]
        for thread in concurrent_threads:
            thread.start()
        for thread in concurrent_threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in concurrent_threads)
        assert concurrent_errors == []

        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "DELETE FROM {}.propertyquarry_admission_quota_buckets "
                        "WHERE bucket_key LIKE 'capacity:bulk:quota:%'"
                    ).format(sql.Identifier(runtime_schema))
                )
                cursor.execute(
                    sql.SQL(
                        "DELETE FROM {}.propertyquarry_admission_leases "
                        "WHERE dimension_key LIKE 'capacity:bulk:lease:%'"
                    ).format(sql.Identifier(runtime_schema))
                )
                cursor.execute(
                    sql.SQL(
                        "SELECT capacity_key, row_count FROM {}.{} "
                        "ORDER BY capacity_key"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                    )
                )
                assert cursor.fetchall() == [("lease", 0), ("quota", 8)]
                cursor.execute(
                    sql.SQL(
                        "TRUNCATE TABLE "
                        "{}.propertyquarry_admission_quota_buckets, "
                        "{}.propertyquarry_admission_leases"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_schema),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "SELECT capacity_key, row_count FROM {}.{} "
                        "ORDER BY capacity_key"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                    )
                )
                assert cursor.fetchall() == [("lease", 0), ("quota", 0)]
            admin.commit()

        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "UPDATE {}.{} SET row_count = row_limit "
                        "WHERE capacity_key = 'quota'"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                    )
                )
            admin.commit()
        with psycopg.connect(**runtime_params, autocommit=False) as runtime:
            with pytest.raises(psycopg.Error) as capacity_error:
                with runtime.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO propertyquarry_admission_quota_buckets "
                        "(bucket_key, window_index, window_seconds, used_units, "
                        "limit_units, expires_at, updated_at) "
                        "VALUES ('capacity:must-rollback', 0, 60, 0, 1, "
                        "clock_timestamp() + interval '1 hour', clock_timestamp())"
                    )
            assert capacity_error.value.sqlstate == "54000"
            runtime.rollback()
        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT COUNT(*) FROM "
                        "{}.propertyquarry_admission_quota_buckets "
                        "WHERE bucket_key = 'capacity:must-rollback'"
                    ).format(sql.Identifier(runtime_schema))
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    sql.SQL(
                        "UPDATE {}.{} SET row_count = 0 "
                        "WHERE capacity_key = 'quota'"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                    )
                )
            admin.commit()
        backend.probe()

        locked_key = "integration:quota:bounded-lock-wait"
        with psycopg.connect(**admin_params, autocommit=False) as blocker:
            with blocker.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"propertyquarry_admission:quota:{locked_key}",),
                )
                started = time.monotonic()
                with pytest.raises(AdmissionBackendUnavailable):
                    backend.consume(
                        QuotaCharge(
                            key=locked_key,
                            units=1,
                            limit=1,
                            window_seconds=60,
                        )
                    )
                elapsed = time.monotonic() - started
                assert 0.05 <= elapsed < 2.0
            blocker.rollback()

        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "CREATE FUNCTION {}.admission_timeout_trigger() "
                        "RETURNS trigger LANGUAGE plpgsql AS $$ "
                        "BEGIN PERFORM pg_sleep(2); RETURN NEW; END $$"
                    ).format(sql.Identifier(runtime_schema))
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE TRIGGER admission_timeout_trigger "
                        "BEFORE INSERT ON {}.propertyquarry_admission_quota_buckets "
                        "FOR EACH ROW EXECUTE FUNCTION "
                        "{}.admission_timeout_trigger()"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_schema),
                    )
                )
            admin.commit()
        try:
            with pytest.raises(
                AdmissionBackendUnavailable,
                match="admission_backend_capacity_trigger_drift",
            ):
                backend.probe()
            started = time.monotonic()
            with pytest.raises(AdmissionBackendUnavailable):
                backend.consume(
                    QuotaCharge(
                        key="integration:quota:bounded-statement",
                        units=1,
                        limit=1,
                        window_seconds=60,
                    )
                )
            assert 0.20 <= (time.monotonic() - started) < 2.0
        finally:
            with psycopg.connect(**admin_params, autocommit=False) as admin:
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL(
                            "DROP TRIGGER admission_timeout_trigger ON "
                            "{}.propertyquarry_admission_quota_buckets"
                        ).format(sql.Identifier(runtime_schema))
                    )
                    cursor.execute(
                        sql.SQL(
                            "DROP FUNCTION {}.admission_timeout_trigger()"
                        ).format(sql.Identifier(runtime_schema))
                    )
                admin.commit()
        backend.probe()

        expired_key = "integration:quota:expired-denial-cleanup"
        with psycopg.connect(**admin_params, autocommit=False) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.propertyquarry_admission_quota_buckets "
                        "(bucket_key, window_index, window_seconds, used_units, "
                        "limit_units, expires_at, updated_at) "
                        "VALUES (%s, 0, 60, 0, 1, "
                        "clock_timestamp() - interval '1 second', clock_timestamp())"
                    ).format(sql.Identifier(runtime_schema)),
                    (expired_key,),
                )
            admin.commit()
        denied = backend.consume(
            QuotaCharge(
                key=expired_key,
                units=2,
                limit=1,
                window_seconds=60,
            )
        )
        assert denied.allowed is False
        with psycopg.connect(**admin_params, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT COUNT(*) FROM "
                        "{}.propertyquarry_admission_quota_buckets "
                        "WHERE bucket_key = %s"
                    ).format(sql.Identifier(runtime_schema)),
                    (expired_key,),
                )
                assert cursor.fetchone()[0] == 0

                cursor.execute(
                    sql.SQL(
                        "SELECT capacity_key, row_count, row_limit FROM {}.{} "
                        "ORDER BY capacity_key"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(ADMISSION_CAPACITY_STATE_TABLE),
                    )
                )
                capacity_rows = cursor.fetchall()
                cursor.execute(
                    sql.SQL(
                        "SELECT "
                        "(SELECT COUNT(*) FROM "
                        "{}.propertyquarry_admission_leases), "
                        "(SELECT COUNT(*) FROM "
                        "{}.propertyquarry_admission_quota_buckets)"
                    ).format(
                        sql.Identifier(runtime_schema),
                        sql.Identifier(runtime_schema),
                    )
                )
                lease_count, quota_count = cursor.fetchone()
                assert capacity_rows == [
                    ("lease", lease_count, 100_000),
                    ("quota", quota_count, 1_000_000),
                ]
        assert backend.capacity_snapshot() == (
            ("lease", lease_count, 100_000),
            ("quota", quota_count, 1_000_000),
        )

        expired_lease = backend.acquire(
            (ConcurrencyDimension("integration:lease:expired-cleanup", 1),),
            lease_seconds=1,
        )
        assert expired_lease.allowed
        time.sleep(1.1)
        assert backend.renew(expired_lease.lease_id, lease_seconds=30) is False
        with psycopg.connect(**admin_params, autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT COUNT(*) FROM "
                        "{}.propertyquarry_admission_leases "
                        "WHERE lease_id = %s::uuid"
                    ).format(sql.Identifier(runtime_schema)),
                    (expired_lease.lease_id,),
                )
                assert cursor.fetchone()[0] == 0

        oversized_schema = f"{runtime_schema}_oversized"
        oversized_schema_created = False
        try:
            with psycopg.connect(**admin_params, autocommit=True) as admin:
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                            sql.Identifier(oversized_schema),
                            sql.Identifier(owner_role),
                        )
                    )
                    oversized_schema_created = True
            with psycopg.connect(**admin_params, autocommit=False) as admin:
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("SET LOCAL ROLE {}").format(
                            sql.Identifier(owner_role)
                        )
                    )
                    cursor.execute(
                        sql.SQL("SET LOCAL search_path TO {}").format(
                            sql.Identifier(oversized_schema)
                        )
                    )
                    cursor.execute(schema.PROPERTY_SEARCH_MIGRATIONS[15].sql)
                    cursor.execute(
                        "INSERT INTO propertyquarry_admission_leases "
                        "(lease_id, dimension_key, limit_units, acquired_at, expires_at) "
                        "SELECT md5('oversized:' || value)::uuid, "
                        "'oversized:' || value, 1, clock_timestamp(), "
                        "clock_timestamp() + interval '1 hour' "
                        "FROM generate_series(1, 100001) AS value"
                    )
                admin.commit()
            with psycopg.connect(**admin_params, autocommit=False) as admin:
                with pytest.raises(psycopg.Error) as migration_error:
                    with admin.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("SET LOCAL ROLE {}").format(
                                sql.Identifier(owner_role)
                            )
                        )
                        cursor.execute(
                            sql.SQL("SET LOCAL search_path TO {}").format(
                                sql.Identifier(oversized_schema)
                            )
                        )
                        cursor.execute(
                            "SELECT set_config("
                            "'propertyquarry.admission_capacity_owner_role', "
                            "%s, TRUE)",
                            (capacity_owner_role,),
                        )
                        cursor.execute(schema.PROPERTY_SEARCH_MIGRATIONS[16].sql)
                assert migration_error.value.sqlstate == "54000"
                admin.rollback()
            with psycopg.connect(**admin_params, autocommit=True) as admin:
                with admin.cursor() as cursor:
                    cursor.execute(
                        "SELECT to_regclass("
                        "pg_catalog.format('%%I.%%I', %s::text, %s::text)"
                        ") IS NULL",
                        (oversized_schema, ADMISSION_CAPACITY_STATE_TABLE),
                    )
                    assert cursor.fetchone()[0] is True
                    cursor.execute(
                        sql.SQL(
                            "SELECT COUNT(*) FROM "
                            "{}.propertyquarry_admission_leases"
                        ).format(sql.Identifier(oversized_schema))
                    )
                    assert cursor.fetchone()[0] == 100_001
        finally:
            if oversized_schema_created:
                with psycopg.connect(**admin_params, autocommit=True) as admin:
                    with admin.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(oversized_schema)
                            )
                        )
    finally:
        for backend in backends:
            _close_backend_pool(backend)
        with psycopg.connect(
            **_connect_params(database=original_database),
            autocommit=True,
        ) as admin:
            with admin.cursor() as cursor:
                if created_database:
                    cursor.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                            sql.Identifier(disposable_database)
                        )
                    )
                if created_runtime_role:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(runtime_role)
                        )
                    )
                if created_owner_role:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(owner_role)
                        )
                    )
                if created_capacity_owner_role:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(capacity_owner_role)
                        )
                    )

    with psycopg.connect(
        **_connect_params(database=original_database),
        autocommit=True,
    ) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                """
                SELECT NOT EXISTS (
                           SELECT 1 FROM pg_database WHERE datname = %s
                       ),
                       NOT EXISTS (
                           SELECT 1 FROM pg_roles WHERE rolname = %s
                       ),
                       NOT EXISTS (
                           SELECT 1 FROM pg_roles WHERE rolname = %s
                       ),
                       NOT EXISTS (
                           SELECT 1 FROM pg_roles WHERE rolname = %s
                       )
                """,
                (
                    disposable_database,
                    runtime_role,
                    owner_role,
                    capacity_owner_role,
                ),
            )
            assert cursor.fetchone() == (True, True, True, True)
