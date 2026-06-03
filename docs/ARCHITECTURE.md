# Architecture

PropertyQuarry is now housed in its own repository and runnable runtime.

## Current state

This repo contains:

- branded public landing, onboarding, sign-in, and property workspace
- property search run orchestration
- country/provider/language market catalog
- shortlist ranking and review packet links
- feedback learning loop
- PayPal property plan upgrades
- Emailit-backed notification delivery
- Docker runtime, smoke scripts, and property contract tests

The application runtime still carries inherited EA infrastructure because that was the fastest safe extraction path:

- shared FastAPI app shell
- shared operator/runtime scaffolding
- shared queue/memory/provider framework
- shared responses and tool runtime spine

That means the product runtime is already standalone at repo level, but not yet fully pruned at code-surface level.

## Migration principle

The repository is now the source of truth for PropertyQuarry.

New property product work should land here first. The older EA repo should no longer be treated as the primary home of the property product lane.

## What still needs pruning

- non-property public routes that do not belong in the product
- unrelated memorial and assistant-specific surfaces
- overly broad design canon and release material copied across during the extraction
- inherited runtime scripts and tests that are not needed for the property product

## Recommended next isolation steps

1. Narrow public-route registration to property-facing surfaces by default.
2. Keep inherited authenticated runtime surfaces behind an explicit legacy flag.
3. Split property runtime tests from inherited assistant/runtime suites.
4. Rename service/container identities from `ea-*` to `propertyquarry-*`.
5. Separate product release receipts and docs from the inherited EA canon.
6. Move shared generic runtime pieces into a reusable base package only if duplication becomes expensive.

## Product capabilities preserved

- source scanning
- country-aware provider selection
- language-aware search posture
- ranking against profile preferences
- hosted property review pages
- research request escalation
- 360/tour handling when available
- free/paid commercial gating
- feedback learning loop
