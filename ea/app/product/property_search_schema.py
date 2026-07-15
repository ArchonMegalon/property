from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import threading
from typing import Callable, Sequence


SCHEMA_COMPONENT = "property_search"
SCHEMA_LEDGER_TABLE = "propertyquarry_schema_migrations"
SCHEMA_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"propertyquarry:property_search:migrations:v1").digest()[:8],
    byteorder="big",
    signed=True,
)


@dataclass(frozen=True)
class PropertySearchMigration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        payload = (
            f"{SCHEMA_COMPONENT}\0{self.version}\0{self.name}\0{self.sql.strip()}\n"
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PropertySearchSchemaStatus:
    ready: bool
    reason: str
    current_version: int
    required_version: int
    applied_versions: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "component": SCHEMA_COMPONENT,
            "ready": self.ready,
            "reason": self.reason,
            "current_version": self.current_version,
            "required_version": self.required_version,
            "applied_versions": list(self.applied_versions),
        }


@dataclass(frozen=True)
class PropertySearchMigrationResult:
    previous_version: int
    current_version: int
    applied_versions: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "component": SCHEMA_COMPONENT,
            "previous_version": self.previous_version,
            "current_version": self.current_version,
            "applied_versions": list(self.applied_versions),
        }


class PropertySearchSchemaError(RuntimeError):
    """Base failure for the governed property-search schema boundary."""


class PropertySearchSchemaDriftError(PropertySearchSchemaError):
    """The migration ledger no longer matches the immutable source contract."""


class PropertySearchSchemaNotReadyError(PropertySearchSchemaError):
    """Runtime access was attempted before the deploy migration completed."""


_RUN_SCHEMA_V1 = r"""
CREATE TABLE IF NOT EXISTS property_search_runs (
    principal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT,
    compact_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (principal_id, run_id)
);

ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS principal_id TEXT;
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS payload_json JSONB DEFAULT '{}'::jsonb;
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS compact_json JSONB DEFAULT '{}'::jsonb;
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE property_search_runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE property_search_runs
SET payload_json = '{}'::jsonb
WHERE payload_json IS NULL;

UPDATE property_search_runs
SET status = COALESCE(status, payload_json->>'status', payload_json#>>'{summary,status}'),
    compact_json = CASE
        WHEN compact_json IS NULL OR compact_json = '{}'::jsonb
        THEN jsonb_strip_nulls(payload_json)
        ELSE compact_json
    END,
    created_at = COALESCE(created_at, NOW()),
    updated_at = COALESCE(updated_at, created_at, NOW());

ALTER TABLE property_search_runs ALTER COLUMN payload_json SET DEFAULT '{}'::jsonb;
ALTER TABLE property_search_runs ALTER COLUMN payload_json SET NOT NULL;
ALTER TABLE property_search_runs ALTER COLUMN compact_json SET DEFAULT '{}'::jsonb;
ALTER TABLE property_search_runs ALTER COLUMN compact_json SET NOT NULL;
ALTER TABLE property_search_runs ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE property_search_runs ALTER COLUMN updated_at SET NOT NULL;

DO $property_search_runs_primary_key$
DECLARE
    primary_key_name TEXT;
    primary_key_columns TEXT[];
BEGIN
    SELECT constraint_row.conname,
           array_agg(attribute_row.attname ORDER BY key_column.ordinality)
    INTO primary_key_name, primary_key_columns
    FROM pg_constraint AS constraint_row
    JOIN unnest(constraint_row.conkey) WITH ORDINALITY
      AS key_column(attnum, ordinality) ON TRUE
    JOIN pg_attribute AS attribute_row
      ON attribute_row.attrelid = constraint_row.conrelid
     AND attribute_row.attnum = key_column.attnum
    WHERE constraint_row.conrelid = 'property_search_runs'::regclass
      AND constraint_row.contype = 'p'
    GROUP BY constraint_row.conname;

    IF primary_key_columns IS DISTINCT FROM ARRAY['principal_id', 'run_id']::TEXT[] THEN
        IF primary_key_name IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE property_search_runs DROP CONSTRAINT %I',
                primary_key_name
            );
        END IF;
        DELETE FROM property_search_runs AS older
        USING property_search_runs AS newer
        WHERE older.ctid < newer.ctid
          AND older.principal_id = newer.principal_id
          AND older.run_id = newer.run_id;
        ALTER TABLE property_search_runs ALTER COLUMN principal_id SET NOT NULL;
        ALTER TABLE property_search_runs ALTER COLUMN run_id SET NOT NULL;
        ALTER TABLE property_search_runs
            ADD CONSTRAINT property_search_runs_pkey PRIMARY KEY (principal_id, run_id);
    END IF;
END
$property_search_runs_primary_key$;

CREATE INDEX IF NOT EXISTS idx_property_search_runs_updated
    ON property_search_runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_search_runs_principal_updated
    ON property_search_runs(principal_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_search_runs_status_updated
    ON property_search_runs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_search_runs_principal_status_updated
    ON property_search_runs(principal_id, status, updated_at DESC);
"""


_WORK_QUEUE_SCHEMA_V2 = r"""
CREATE TABLE IF NOT EXISTS property_search_work_jobs (
    job_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_property_search_work_idempotency
    ON property_search_work_jobs(idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_property_search_work_principal_run
    ON property_search_work_jobs(principal_id, run_id);
CREATE INDEX IF NOT EXISTS idx_property_search_work_claim
    ON property_search_work_jobs(status, available_at, lease_expires_at, created_at);

DO $property_search_work_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'property_search_work_jobs'::regclass
          AND conname = 'property_search_work_jobs_status_check'
    ) THEN
        ALTER TABLE property_search_work_jobs
            ADD CONSTRAINT property_search_work_jobs_status_check
            CHECK (status IN ('queued', 'leased', 'completed', 'failed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'property_search_work_jobs'::regclass
          AND conname = 'property_search_work_jobs_attempt_count_check'
    ) THEN
        ALTER TABLE property_search_work_jobs
            ADD CONSTRAINT property_search_work_jobs_attempt_count_check
            CHECK (attempt_count >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'property_search_work_jobs'::regclass
          AND conname = 'property_search_work_jobs_max_attempts_check'
    ) THEN
        ALTER TABLE property_search_work_jobs
            ADD CONSTRAINT property_search_work_jobs_max_attempts_check
            CHECK (max_attempts >= 1);
    END IF;
END
$property_search_work_constraints$;
"""


_SOURCE_CACHE_SCHEMA_V3 = r"""
CREATE TABLE IF NOT EXISTS property_source_listing_cache (
    cache_key TEXT PRIMARY KEY,
    source_url TEXT NOT NULL DEFAULT '',
    listing_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_filter_pushdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    stored_at_epoch DOUBLE PRECISION NOT NULL,
    stored_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_property_source_listing_cache_stored_at
    ON property_source_listing_cache(stored_at_epoch DESC);
"""


_DELIVERY_OUTBOX_SCHEMA_V4 = r"""
CREATE TABLE IF NOT EXISTS delivery_outbox (
    delivery_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ NULL,
    idempotency_key TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NULL,
    last_error TEXT NOT NULL DEFAULT '',
    receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dead_lettered_at TIMESTAMPTZ NULL,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TIMESTAMPTZ NULL,
    claimed_at TIMESTAMPTZ NULL,
    dispatch_started_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS principal_id TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS idempotency_key TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NULL;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS last_error TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ NULL;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS lease_owner TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ NULL;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ NULL;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS dispatch_started_at TIMESTAMPTZ NULL;
ALTER TABLE delivery_outbox ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE delivery_outbox
SET principal_id = COALESCE(NULLIF(metadata_json->>'principal_id', ''), principal_id, ''),
    updated_at = COALESCE(updated_at, sent_at, created_at, NOW())
WHERE COALESCE(principal_id, '') = '' OR updated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_status_created
    ON delivery_outbox(status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_outbox_principal_idempotency_unique
    ON delivery_outbox(principal_id, idempotency_key)
    WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_retry_schedule
    ON delivery_outbox(status, next_attempt_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_principal_status_created
    ON delivery_outbox(principal_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_claim
    ON delivery_outbox(status, next_attempt_at, lease_expires_at, created_at, delivery_id);
"""


_PROPERTY_CONTENT_LEDGER_SCHEMA_V5 = r"""
CREATE TABLE IF NOT EXISTS property_content_jobs (
    packet_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    source_packet_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_packet_sha256 CHAR(64) NOT NULL,
    row_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TIMESTAMPTZ NULL,
    claimed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (packet_id <> ''),
    CHECK (idempotency_key <> ''),
    CHECK (status <> ''),
    CHECK (source_packet_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (version >= 1)
);

CREATE TABLE IF NOT EXISTS property_content_job_events (
    event_sequence BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    packet_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (event_id <> ''),
    CHECK (packet_id <> ''),
    CHECK (event_type <> ''),
    CHECK (status <> ''),
    CHECK (idempotency_key <> '')
);

CREATE TABLE IF NOT EXISTS property_content_webhook_events (
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    row_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TIMESTAMPTZ NULL,
    claimed_at TIMESTAMPTZ NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    replayed_at TIMESTAMPTZ NULL,
    processed_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, provider_event_id),
    CHECK (provider <> ''),
    CHECK (provider_event_id <> ''),
    CHECK (status <> ''),
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_property_content_jobs_status_updated
    ON property_content_jobs(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_content_jobs_claim
    ON property_content_jobs(status, lease_expires_at, updated_at, packet_id);
CREATE INDEX IF NOT EXISTS idx_property_content_job_events_packet_sequence
    ON property_content_job_events(packet_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_property_content_webhook_status_updated
    ON property_content_webhook_events(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_content_webhook_claim
    ON property_content_webhook_events(status, lease_expires_at, received_at, provider_event_id);
"""


_RUN_DELIVERY_PROJECTION_SCHEMA_V6 = r"""
ALTER TABLE property_search_runs
    ADD COLUMN IF NOT EXISTS compact_schema_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE property_search_runs
    ADD COLUMN IF NOT EXISTS delivery_pending BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE property_search_runs
    ADD COLUMN IF NOT EXISTS delivery_checked_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_property_search_runs_delivery_work_updated
    ON property_search_runs(
        status,
        compact_schema_version,
        delivery_checked_at ASC NULLS FIRST,
        updated_at ASC
    )
    WHERE delivery_pending OR compact_schema_version < 2;
CREATE INDEX IF NOT EXISTS idx_property_search_runs_principal_delivery_work_updated
    ON property_search_runs(
        principal_id,
        status,
        compact_schema_version,
        delivery_checked_at ASC NULLS FIRST,
        updated_at ASC
    )
    WHERE delivery_pending OR compact_schema_version < 2;
"""


PROPERTY_SEARCH_MIGRATIONS: tuple[PropertySearchMigration, ...] = (
    PropertySearchMigration(1, "property_search_runs_tenant_schema", _RUN_SCHEMA_V1),
    PropertySearchMigration(2, "property_search_durable_work_queue", _WORK_QUEUE_SCHEMA_V2),
    PropertySearchMigration(3, "property_source_listing_cache", _SOURCE_CACHE_SCHEMA_V3),
    PropertySearchMigration(4, "replica_safe_delivery_outbox", _DELIVERY_OUTBOX_SCHEMA_V4),
    PropertySearchMigration(5, "durable_property_content_job_ledger", _PROPERTY_CONTENT_LEDGER_SCHEMA_V5),
    PropertySearchMigration(6, "bounded_run_delivery_projection", _RUN_DELIVERY_PROJECTION_SCHEMA_V6),
)
LATEST_PROPERTY_SEARCH_SCHEMA_VERSION = PROPERTY_SEARCH_MIGRATIONS[-1].version

_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_LEDGER_TABLE} (
    component TEXT NOT NULL,
    version INTEGER NOT NULL,
    migration_name TEXT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (component, version),
    CHECK (version > 0),
    CHECK (checksum_sha256 ~ '^[0-9a-f]{{64}}$')
)
"""

_REQUIRED_RELATIONS = (
    "property_search_runs",
    "idx_property_search_runs_updated",
    "idx_property_search_runs_principal_updated",
    "idx_property_search_runs_status_updated",
    "idx_property_search_runs_principal_status_updated",
    "idx_property_search_runs_delivery_work_updated",
    "idx_property_search_runs_principal_delivery_work_updated",
    "property_search_work_jobs",
    "idx_property_search_work_idempotency",
    "idx_property_search_work_principal_run",
    "idx_property_search_work_claim",
    "property_source_listing_cache",
    "idx_property_source_listing_cache_stored_at",
    "delivery_outbox",
    "idx_delivery_outbox_status_created",
    "idx_delivery_outbox_principal_idempotency_unique",
    "idx_delivery_outbox_retry_schedule",
    "idx_delivery_outbox_principal_status_created",
    "idx_delivery_outbox_claim",
    "property_content_jobs",
    "property_content_job_events",
    "property_content_webhook_events",
    "idx_property_content_jobs_status_updated",
    "idx_property_content_jobs_claim",
    "idx_property_content_job_events_packet_sequence",
    "idx_property_content_webhook_status_updated",
    "idx_property_content_webhook_claim",
)

_SCHEMA_READY_LOCK = threading.Lock()
_SCHEMA_READY_DATABASES: set[str] = set()


def _migration_by_version() -> dict[int, PropertySearchMigration]:
    return {migration.version: migration for migration in PROPERTY_SEARCH_MIGRATIONS}


def _validate_applied_rows(
    rows: Sequence[Sequence[object]],
) -> tuple[int, ...]:
    expected = _migration_by_version()
    observed: dict[int, tuple[str, str]] = {}
    for row in rows:
        version = int(row[0])
        name = str(row[1] or "")
        checksum = str(row[2] or "").strip().lower()
        if version in observed:
            raise PropertySearchSchemaDriftError(
                f"duplicate_property_search_migration_version:{version}"
            )
        observed[version] = (name, checksum)
    for version, (name, checksum) in sorted(observed.items()):
        migration = expected.get(version)
        if migration is None:
            raise PropertySearchSchemaDriftError(
                f"property_search_schema_ahead:{version}"
            )
        if name != migration.name or checksum != migration.checksum:
            raise PropertySearchSchemaDriftError(
                f"property_search_migration_checksum_drift:{version}"
            )
    versions = tuple(sorted(observed))
    if versions and versions != tuple(range(1, versions[-1] + 1)):
        raise PropertySearchSchemaDriftError("property_search_migration_gap")
    return versions


def _connect(database_url: str, *, autocommit: bool):  # type: ignore[no-untyped-def]
    import psycopg

    return psycopg.connect(
        database_url,
        autocommit=autocommit,
        connect_timeout=5,
    )


def migrate_property_search_schema(
    database_url: str,
    *,
    applied_by: str = "deploy",
    connect: Callable[..., object] | None = None,
) -> PropertySearchMigrationResult:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        raise PropertySearchSchemaError("database_url_required")
    connector = connect or _connect
    conn = connector(normalized_url, autocommit=False)
    try:
        with conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
            cur.execute(_LEDGER_DDL)
            cur.execute(
                f"""
                SELECT version, migration_name, checksum_sha256
                FROM {SCHEMA_LEDGER_TABLE}
                WHERE component = %s
                ORDER BY version
                """,
                (SCHEMA_COMPONENT,),
            )
            before = _validate_applied_rows(cur.fetchall())
            before_set = set(before)
            applied: list[int] = []
            for migration in PROPERTY_SEARCH_MIGRATIONS:
                if migration.version in before_set:
                    continue
                cur.execute(migration.sql)
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA_LEDGER_TABLE}
                        (component, version, migration_name, checksum_sha256, applied_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        SCHEMA_COMPONENT,
                        migration.version,
                        migration.name,
                        migration.checksum,
                        str(applied_by or "deploy").strip()[:120] or "deploy",
                    ),
                )
                applied.append(migration.version)
        conn.commit()  # type: ignore[attr-defined]
    except Exception:
        conn.rollback()  # type: ignore[attr-defined]
        raise
    finally:
        conn.close()  # type: ignore[attr-defined]
    with _SCHEMA_READY_LOCK:
        _SCHEMA_READY_DATABASES.discard(normalized_url)
    return PropertySearchMigrationResult(
        previous_version=before[-1] if before else 0,
        current_version=LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
        applied_versions=tuple(applied),
    )


def inspect_property_search_schema_cursor(cur) -> PropertySearchSchemaStatus:  # type: ignore[no-untyped-def]
    cur.execute("SELECT to_regclass(%s)", (SCHEMA_LEDGER_TABLE,))
    ledger_row = cur.fetchone()
    if not ledger_row or ledger_row[0] is None:
        return PropertySearchSchemaStatus(
            False,
            "migration_ledger_missing",
            0,
            LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
            (),
        )
    cur.execute(
        f"""
        SELECT version, migration_name, checksum_sha256
        FROM {SCHEMA_LEDGER_TABLE}
        WHERE component = %s
        ORDER BY version
        """,
        (SCHEMA_COMPONENT,),
    )
    try:
        versions = _validate_applied_rows(cur.fetchall())
    except PropertySearchSchemaDriftError as exc:
        return PropertySearchSchemaStatus(
            False,
            str(exc),
            0,
            LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
            (),
        )
    current = versions[-1] if versions else 0
    if current != LATEST_PROPERTY_SEARCH_SCHEMA_VERSION:
        return PropertySearchSchemaStatus(
            False,
            "migration_pending",
            current,
            LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
            versions,
        )
    for relation in _REQUIRED_RELATIONS:
        cur.execute("SELECT to_regclass(%s)", (relation,))
        relation_row = cur.fetchone()
        if not relation_row or relation_row[0] is None:
            return PropertySearchSchemaStatus(
                False,
                f"required_relation_missing:{relation}",
                current,
                LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
                versions,
            )
    return PropertySearchSchemaStatus(
        True,
        "schema_ready",
        current,
        LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
        versions,
    )


def inspect_property_search_schema(
    database_url: str,
    *,
    connect: Callable[..., object] | None = None,
) -> PropertySearchSchemaStatus:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        return PropertySearchSchemaStatus(
            False,
            "database_url_missing",
            0,
            LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
            (),
        )
    connector = connect or _connect
    try:
        conn = connector(normalized_url, autocommit=True)
        try:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                return inspect_property_search_schema_cursor(cur)
        finally:
            conn.close()  # type: ignore[attr-defined]
    except Exception as exc:
        return PropertySearchSchemaStatus(
            False,
            f"schema_probe_failed:{exc.__class__.__name__}",
            0,
            LATEST_PROPERTY_SEARCH_SCHEMA_VERSION,
            (),
        )


def require_property_search_schema_ready(
    database_url: str,
    *,
    connect: Callable[..., object] | None = None,
) -> None:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        raise PropertySearchSchemaNotReadyError("database_url_missing")
    if connect is None:
        with _SCHEMA_READY_LOCK:
            if normalized_url in _SCHEMA_READY_DATABASES:
                return
    status = inspect_property_search_schema(normalized_url, connect=connect)
    if not status.ready:
        raise PropertySearchSchemaNotReadyError(
            f"property_search_schema_not_ready:{status.reason}"
        )
    if connect is None:
        with _SCHEMA_READY_LOCK:
            _SCHEMA_READY_DATABASES.add(normalized_url)


def property_search_schema_readiness_required(
    *,
    runtime_mode: str,
    role: str,
    explicit: str = "",
) -> bool:
    normalized_mode = str(runtime_mode or "dev").strip().lower()
    normalized_role = str(role or "api").strip().lower()
    if normalized_mode == "prod" and normalized_role in {"api", "worker", "scheduler"}:
        return True
    normalized_explicit = str(explicit or "").strip().lower()
    return normalized_explicit in {"1", "true", "yes", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Governed PropertyQuarry property-search schema boundary."
    )
    parser.add_argument("operation", choices=("migrate", "check"))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--applied-by", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    database_url = str(args.database_url or os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print(json.dumps({"status": "failed", "reason": "database_url_missing"}))
        return 2
    if args.operation == "migrate":
        try:
            result = migrate_property_search_schema(
                database_url,
                applied_by=(
                    str(args.applied_by or "").strip()
                    or str(
                        os.environ.get("PROPERTYQUARRY_RELEASE_COMMIT_SHA") or ""
                    ).strip()
                    or str(os.environ.get("EA_ROLE") or "deploy").strip()
                    or "deploy"
                ),
            )
        except PropertySearchSchemaError as exc:
            print(json.dumps({"status": "failed", "reason": str(exc)}))
            return 2
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "reason": f"migration_failed:{exc.__class__.__name__}",
                    }
                )
            )
            return 2
        print(json.dumps({"status": "migrated", **result.as_dict()}, sort_keys=True))
        return 0
    status = inspect_property_search_schema(database_url)
    print(json.dumps({"status": "ready" if status.ready else "not_ready", **status.as_dict()}, sort_keys=True))
    return 0 if status.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
