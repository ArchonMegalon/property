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
- PayFunnels bootstrap helper: `python3 scripts/bootstrap_payfunnels_propertyquarry.py --help`
- Emailit bootstrap helper: `python3 scripts/bootstrap_emailit_propertyquarry.py --help`
- Docker runtime, smoke scripts, and property-facing tests

Emailit requires the sender domain to be verified before `property@propertyquarry.com` can deliver successfully.

## Product entrypoints

- landing page: `/`
- onboarding: `/register`
- sign-in: `/sign-in`
- property desk: `/app/properties`

The repo defaults to the PropertyQuarry brand even on non-production hostnames.

## Run it

```bash
cp .env.example .env
# fill in the runtime credentials you actually use, including POSTGRES_PASSWORD
docker compose -f docker-compose.property.yml up -d --build
```

That topology starts only `propertyquarry-api`, `propertyquarry-scheduler`, and `propertyquarry-db`.
It builds `ea/Dockerfile.property`, which omits Docker CLI tooling and runs the app process as the non-root `ea` user.

`docker-compose.property.yml` defaults `EA_RUNTIME_MODE=prod`, requires `POSTGRES_PASSWORD`, disables public result/tour side surfaces by default, and runs the scheduler with `PROPERTYQUARRY_SCHEDULER_PROFILE=property_only`.
The inherited generic worker is intentionally not part of the default topology until a dedicated PropertyQuarry job lane exists.

The inherited EA mega-stack deploy script remains in the repo for migration and compatibility work. Do not use it for the standalone public PropertyQuarry runtime unless you explicitly need legacy assistant services:

```bash
PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh
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

- [ENVIRONMENT_MATRIX.md](ENVIRONMENT_MATRIX.md)
- [HTTP_EXAMPLES.http](HTTP_EXAMPLES.http)
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)

Operator scripts can be pointed at non-default compose service names with:

- `PROPERTYQUARRY_API_SERVICE`
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

## Property release gates

Use the product-only release bundle when validating the standalone PropertyQuarry surface:

- `make property-release-gates`
- `bash scripts/property_release_gates.sh`

This bundle includes docs links, runtime security posture, repo-isolation checks, browser contracts, and property run/catalog contracts.

## Key docs

- product brief: [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md)
- architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- repo isolation: [docs/REPO_ISOLATION.md](docs/REPO_ISOLATION.md)
- greenfield redesign plan: [docs/GREENFIELD_REDESIGN_PLAN.md](docs/GREENFIELD_REDESIGN_PLAN.md)
- decision workbench implementation guide: [docs/PROPERTY_DECISION_WORKBENCH_GUIDE.md](docs/PROPERTY_DECISION_WORKBENCH_GUIDE.md)
- brand: [docs/BRAND.md](docs/BRAND.md)
- pricing: [docs/PRICING.md](docs/PRICING.md)
- domain rollout: [docs/DOMAIN_ROLLOUT.md](docs/DOMAIN_ROLLOUT.md)
- runbook: [RUNBOOK.md](RUNBOOK.md)

## Migration status

This repo now includes:

- `ea/` application runtime
- `scripts/` operator and deploy scripts
- `tests/` runtime and product contract coverage
- `docker-compose*.yml` deployment stack
- config, provider templates, and VPN overlay support

The active migration principle is simple: new PropertyQuarry work lands here first. The old EA repo is no longer the intended home for this product surface.
