# PropertyQuarry Property-Search Schema Migrations

Property-search database changes are deploy operations, not application
startup behavior. API, worker, and scheduler processes only verify the schema
ledger and required relations; they never create or alter the run, durable
queue, source-cache, delivery-outbox, or property-content ledger schema.

## Versioned contract

`app.product.property_search_schema` owns the ordered migration manifest:

1. `property_search_runs_tenant_schema`
2. `property_search_durable_work_queue`
3. `property_source_listing_cache`
4. `replica_safe_delivery_outbox`
5. `durable_property_content_job_ledger`

Each immutable migration has a SHA-256 checksum. Applied versions are recorded
in `propertyquarry_schema_migrations` under component `property_search`. The
deploy command acquires a transaction-scoped PostgreSQL advisory lock before
creating the ledger, validates every existing name and checksum, applies all
pending migrations in order, writes their ledger rows, and commits once. A
failed statement rolls back the complete batch. A changed checksum, version
gap, or unknown future version fails closed; never repair those conditions by
editing the ledger.

## Deploy phase

The standalone Compose topology includes a one-shot
`propertyquarry-migrate` service. Both the API and scheduler require it to
finish successfully:

```bash
POSTGRES_PASSWORD='<from-secret-store>' \
  docker compose -f docker-compose.property.yml up -d --build
```

For a separately orchestrated deployment, run the same boundary explicitly
after the database is healthy and before starting any application role:

```bash
PYTHONPATH=ea DATABASE_URL='<private-postgres-dsn>' \
  python3 scripts/migrate_property_search_storage.py
```

The command is idempotent. A successful no-op reports the current version and
`applied=none`. Do not put the database URL in shell history, logs, receipts,
or checked-in configuration.

Verify source contracts without contacting a database:

```bash
PYTHONPATH=ea env -u DATABASE_URL \
  python3 scripts/check_property_search_storage_schema.py
```

With `DATABASE_URL` deliberately supplied, the check performs read-only ledger
and relation probes. It does not migrate.

## Runtime readiness

Production API, worker, and scheduler roles require the current schema
version. `/health/ready` returns `503` with a bounded
`property_search_schema_not_ready:<reason>` until the ledger, checksums,
versions, tables, and indexes pass. Application repositories enforce the same
read-only boundary before issuing run or queue queries.

Migration 4 is also the scheduler delivery-safety boundary. Morning memo and
assistant-nudge sends are inserted under a stable daily idempotency key before
provider dispatch. A scheduler replica must atomically own the row lease and
record `dispatching` before making the outbound call. Email recovery reuses the
same provider idempotency key after a lease expires. Telegram does not expose a
provider idempotency key, so an expired `dispatching` Telegram row is moved to
`dead_lettered` for reconciliation instead of being sent again. This favors a
visible missed delivery over a duplicate message when the provider outcome is
unknown.

Migration 5 is the Property Content Studio durability boundary. Content jobs,
their ordered append-only events, and Subscribr provider event IDs live in
PostgreSQL in production. Stable job/provider idempotency keys and transaction
advisory locks make claims replica-safe; row leases permit recovery after a
worker crash, while stale owners cannot update a recovered claim. A replayed
provider event with the same ID but different canonical payload hash fails closed for
operator investigation. If a worker crashes after provider dispatch begins,
the job moves to `PROVIDER_RECONCILIATION_REQUIRED` rather than repeating an
external request whose outcome is unknown.

Memory mode and development without `DATABASE_URL` remain database-free.
The development JSON compatibility ledger uses cross-process locking, fsync,
and atomic replace; malformed data is preserved and raises a bounded
corruption error instead of being reset to an empty ledger.
Development PostgreSQL is also check-only: run the migration command against a
disposable development database first. Set
`PROPERTYQUARRY_SEARCH_SCHEMA_READINESS_REQUIRED=1` to exercise the production
readiness gate in development.

## Incident boundary

- `migration_ledger_missing` or `migration_pending`: stop traffic promotion and
  run the candidate release's deploy migration against the intended database.
- `property_search_migration_checksum_drift`: restore the exact released
  migration source and investigate; do not update the stored checksum.
- `property_search_schema_ahead`: deploy compatible application code; do not
  delete future ledger rows.
- `required_relation_missing`: treat it as schema damage. Preserve evidence and
  follow the database recovery runbook rather than recreating objects from an
  application process.

Migrations are additive and have no automatic down path. Release rollback must
use the guarded rollback procedure and a version known to tolerate the current
schema.
