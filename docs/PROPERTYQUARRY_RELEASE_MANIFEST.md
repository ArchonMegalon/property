# PropertyQuarry Release Manifest

This file is the concise, current release authority. Detailed dated notes are archived in [`archive/PROPERTYQUARRY_RELEASE_HISTORY_2026-07-16.md`](archive/PROPERTYQUARRY_RELEASE_HISTORY_2026-07-16.md); they never override this manifest.

## Current state

PropertyQuarry is a source/browser candidate, not a production launch:

- The published candidate receipt covers `7/7` source cases, `9/9` real-browser cases, and all eight required product journeys. The candidate includes in-place shortlist history, protected Telegram delivery proof, production-mode PostgreSQL storage/browser parity with internal-only CI session provisioning, immutable CI actions, and fail-closed production registration delivery.
- Candidate/browser proof does not prove deployment, production storage, authentication, external delivery, observability, rollback, or disaster recovery.
- The public edge returns `403` for `/`. `/health/ready` responds, while `/version` has no release SHA or complete manifest.
- Production promotion remains blocked on the independent release-controller artifact, an approved `propertyquarry-security` runner, and distinct digest-pinned web/render images.
- ID Austria is optional and unconfigured. Another supported sign-in path still needs protected live activation proof.
- External notification release evidence is Telegram-only. WhatsApp is outside the current launch evidence.

## Candidate binding

| Field | Value |
| --- | --- |
| Product | PropertyQuarry |
| Status | `source-browser-candidate-pending-protected-live-evidence` |
| Branch | `main` |
| Runtime commit SHA | `b43dde0815ede9fab8948bb5363ec9427e70576a` |
| Release envelope | tracked `main`; protected receipts record the workflow-head SHA separately |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | `pending-governed-production-deploy` |

## Launch blockers

Production stays fail-closed until every item is bound to the exact runtime candidate:

1. Both ordinary hosted CI lanes are terminal and green for the final runtime and receipt envelope.
2. The independently produced `propertyquarry-release-controller-v1` bundle is installed through the governed intake lane.
3. The protected environment has an approved `propertyquarry-security` runner and distinct digest-pinned `PROPERTYQUARRY_WEB_IMAGE` and `PROPERTYQUARRY_RENDER_IMAGE` inputs.
4. Dependency, container, policy, and SBOM scans pass without stale databases or weakened gates.
5. The governed deployment completes; `/version` reports the approved runtime SHA and complete manifest; `/` no longer returns the stale `403`.
6. A supported sign-in path, lifecycle controls, Telegram delivery, PostgreSQL durability, and the customer search-to-decision journeys pass protected live verification.
7. Observability, alerting, rollback, disaster recovery, post-promotion smoke, and Cloudflare/public-origin receipts pass.
8. Billing, provider-media, analytics, and Gold limitations are either resolved with evidence or excluded from the launch claim.

## Whole-project Gold boundary

- Evidence-map overlays remain a whole-project gold blocker until source registries, Teable ingestion, cached read models, unavailable/stale/verified UI states, and performance receipts cover environmental quality, heat, mobility, schools, official aggregate safety context, media-attention statistics with article links, and fiber/broadband coverage.
- Rybbit remains a whole-project gold blocker until dashboard/API receipts prove the approved taxonomy across conversion, product engagement, billing, tours, support/recovery, and activation without private candidate, listing, or contact payloads.
- Production security remains a whole-project gold blocker until runtime/container hardening, reproducible supply chain, dependency/container scans, SBOM, durable RBAC/session revocation, key rotation, and disabled production override receipts are current.
- Remote candidate CI and deployed/live receipts remain required before launch authority can be granted.

## Rules

- Update this file only from current candidate and production evidence.
- Treat a tracked-`main`/runtime SHA mismatch as blocked until governed deployment reconciles it.
- Store detailed machine receipts in completion artifacts or CI, not in this document.
- Never include credentials, tokens, cookies, license keys, or customer data.
- Never bypass the release controller, security runner, provenance, rollback, or disaster-recovery gates.
