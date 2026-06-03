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
