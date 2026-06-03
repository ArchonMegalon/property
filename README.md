# PropertyQuarry

PropertyQuarry is a standalone property discovery product: cross-platform search, ranking, research packets, hosted review pages, feedback learning, and paid research tiers.

This repository now contains the runnable product runtime that had previously lived inside the broader EA codebase. The goal of this repo is not a docs mirror. It is the source of truth for the PropertyQuarry app, tests, deployment scripts, and branded public surfaces.

## What is in this repo

- public product surface for `propertyquarry.com`
- onboarding, sign-in, and authenticated property workspace
- property search runs across supported providers and countries
- shortlist ranking, hosted review packets, and 360 tour links
- feedback learning loop and preference profile updates
- PayPal plan upgrades and Emailit-based client notifications
- Docker runtime, smoke scripts, and property-facing tests

## Product entrypoints

- landing page: `/`
- onboarding: `/register`
- sign-in: `/sign-in`
- property desk: `/app/properties`

The repo defaults to the PropertyQuarry brand even on non-production hostnames.

## Run it

```bash
cp .env.example .env
# fill in the runtime credentials you actually use
bash scripts/deploy.sh
```

Then open:

- `http://localhost:8090/`
- `http://localhost:8090/register`
- `http://localhost:8090/app/properties`

## Runtime modes

PropertyQuarry keeps the inherited runtime-mode contract because deploy and smoke gates depend on it:

- `EA_RUNTIME_MODE=dev|test|prod`
- `EA_RUNTIME_MODE=prod` must fail fast when durable runtime prerequisites are missing
- `bash scripts/smoke_postgres.sh` verifies the Postgres-backed path and the prod fail-fast behavior

Runtime and environment details live in:

- [ENVIRONMENT_MATRIX.md](/docker/property/ENVIRONMENT_MATRIX.md)
- [HTTP_EXAMPLES.http](/docker/property/HTTP_EXAMPLES.http)
- [RELEASE_CHECKLIST.md](/docker/property/RELEASE_CHECKLIST.md)

Operator scripts can be pointed at non-default compose service names with:

- `PROPERTYQUARRY_API_SERVICE`
- `PROPERTYQUARRY_WORKER_SERVICE`
- `PROPERTYQUARRY_SCHEDULER_SERVICE`
- `PROPERTYQUARRY_DB_SERVICE`

This alias layer also applies to support exports such as `bash scripts/support_bundle.sh`.

Support export baseline:

- `SUPPORT_INCLUDE_DB_VOLUME=0 bash scripts/support_bundle.sh`
- support bundles can include `ea-db mount/volume attribution`
- expected runtime volume remains `ea_pgdata`
- expected container mount remains `/var/lib/postgresql/data`

## DB operator lane

Runtime DB visibility and retention helpers remain part of the standalone release surface:

- `bash scripts/db_bootstrap.sh`
- `bash scripts/db_status.sh`
- `bash scripts/db_size.sh`
- `bash scripts/db_retention.sh`

Supported controls include:

- `EA_RETENTION_PROFILE=aggressive|standard|conservative`
- `EA_RETENTION_TABLES`
- `EA_RETENTION_SKIP_TABLES`
- `EA_DB_SIZE_SCHEMA=<schema>`
- `EA_DB_SIZE_SORT_KEY=total|table|index`
- `EA_DB_SIZE_TABLE_PREFIX=<prefix>`
- `EA_DB_SIZE_MIN_MB=<n>`
- `SUPPORT_INCLUDE_DB_SIZE=0`
- `SUPPORT_DB_SIZE_LIMIT=<n>`

## Key docs

- product brief: [docs/PRODUCT_BRIEF.md](/docker/property/docs/PRODUCT_BRIEF.md)
- architecture: [docs/ARCHITECTURE.md](/docker/property/docs/ARCHITECTURE.md)
- brand: [docs/BRAND.md](/docker/property/docs/BRAND.md)
- pricing: [docs/PRICING.md](/docker/property/docs/PRICING.md)
- domain rollout: [docs/DOMAIN_ROLLOUT.md](/docker/property/docs/DOMAIN_ROLLOUT.md)
- runbook: [RUNBOOK.md](/docker/property/RUNBOOK.md)

## Migration status

This repo now includes:

- `ea/` application runtime
- `scripts/` operator and deploy scripts
- `tests/` runtime and product contract coverage
- `docker-compose*.yml` deployment stack
- config, provider templates, and VPN overlay support

The active migration principle is simple: new PropertyQuarry work lands here first. The old EA repo is no longer the intended home for this product surface.
