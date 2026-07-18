# PropertyQuarry Release Manifest

This file is the concise, current release authority. Detailed dated notes are archived in [`archive/PROPERTYQUARRY_RELEASE_HISTORY_2026-07-16.md`](archive/PROPERTYQUARRY_RELEASE_HISTORY_2026-07-16.md); they never override this manifest.

## Current state

PropertyQuarry is a source/browser candidate, not a production launch:

- The published candidate receipt covers `8/8` source cases, `16/16` real-browser cases, and all eight required product journeys. The candidate includes explicit hosted/generated/blocked/expired 3D-tour truth, attributable unavailable/stale/verified area-evidence states, in-place shortlist history, protected Telegram delivery proof, production-mode PostgreSQL storage/browser parity with internal-only CI session provisioning, immutable CI actions, fail-closed production registration delivery, and a signed controller profile that preserves the canonical public-tour volume and permits only journaled ownership repair.
- Candidate/browser proof does not prove deployment, production storage, authentication, external delivery, observability, rollback, or disaster recovery.
- The public edge currently returns `200` for `/` after a narrow generated-tour permission repair. `/health/ready` responds, while `/version` still reports an incomplete release manifest without canonical release identity; those runtime checks are not deployment proof for this candidate.
- Production promotion remains blocked on the independent release-controller artifact, an approved `propertyquarry-security` runner, and distinct digest-pinned web/render images.
- ID Austria is optional and unconfigured. Another supported sign-in path still needs protected live activation proof.
- External notification release evidence is Telegram-only. WhatsApp is outside the current launch evidence.

## Candidate binding

The marked JSON object is the single canonical release authority consumed by the runtime and release verifier. Its exact field set and canonical SHA-256 fail closed on missing, duplicate, unexpected, empty, or mismatched fields.

<!-- propertyquarry-release-manifest-json:start -->
```json
{
  "release_artifact_set": "propertyquarry-generated-release-artifacts-v1@sha256:006e107f214513516a43a33727b10249ec8c6508326c6b7886462f65099a86e2",
  "release_branch": "main",
  "release_candidate_status": "source-browser-candidate-pending-protected-live-evidence",
  "release_commit_sha": "73b18a8c3d7c04816a29026fda61f7fe174326ff",
  "release_deployment_id": "propertyquarry-governed-deploy-73b18a8c3d7c",
  "release_generated_at": "2026-07-18T06:29:27Z",
  "release_label": "propertyquarry-source-browser-candidate-73b18a8c3d7c",
  "release_manifest_schema": "propertyquarry.release_manifest.v1",
  "release_mirror_origin": "https://github.com/ArchonMegalon/propertyquarry.git",
  "release_mirror_repository": "ArchonMegalon/propertyquarry",
  "release_product": "PropertyQuarry",
  "release_public_origin": "https://propertyquarry.com",
  "release_repository": "ArchonMegalon/property",
  "release_repository_origin": "https://github.com/ArchonMegalon/property.git",
  "release_verification_commands": "bash scripts/verify_release_assets.sh && python3 scripts/verify_flagship_release_readiness.py && python3 scripts/verify_generated_release_artifacts_clean.py"
}
```
<!-- propertyquarry-release-manifest-json:end -->

The artifact-set identity covers the exact tracked bytes of the flagship release receipt, weekly product pulse, and browser workflow proof named by the verifier. The runtime SHA is the source candidate recorded by the flagship receipt; it is intentionally not a self-reference to the later documentation/envelope commit. Any missing, duplicate, empty, or mismatched authority field blocks verification.

## Launch blockers

Production stays fail-closed until every item is bound to the exact runtime candidate:

1. Both ordinary hosted CI lanes are terminal and green for the final runtime and receipt envelope.
2. The independently produced `propertyquarry-release-controller-v1` bundle is installed through the governed intake lane and enforces `PROPERTYQUARRY_PUBLIC_TOUR_VOLUME_PROFILE_V1.md`, including canonical-volume identity, pre/post manifests, ownership-only repair, mode preservation, and rollback evidence.
3. The protected environment has an approved `propertyquarry-security` runner and distinct digest-pinned `PROPERTYQUARRY_WEB_IMAGE` and `PROPERTYQUARRY_RENDER_IMAGE` inputs.
4. Dependency, container, policy, and SBOM scans pass without stale databases or weakened gates.
5. The governed deployment preserves the canonical public-tour inventory, repairs only journaled legacy ownership, and completes; `/version` reports the approved runtime SHA and complete manifest; `/` remains healthy without generated-bundle permission errors or path disclosure.
6. A supported sign-in path, lifecycle controls, Telegram delivery, PostgreSQL durability, and the customer search-to-decision journeys pass protected live verification.
7. Observability, alerting, rollback, disaster recovery, post-promotion smoke, and Cloudflare/public-origin receipts pass.
8. Billing, provider-media, analytics, and Gold limitations are either resolved with evidence or excluded from the launch claim.

## Whole-project Gold boundary

- Evidence-map overlay source and browser UI proof is green for unavailable, stale, and verified states. Whole-project Gold remains blocked until protected live authenticated source coverage and candidate-bound cache-recency, source-time/reference-period, and performance receipts cover environmental quality, heat, traffic/noise, mobility, schools, official aggregate safety context, media-attention statistics with article links, and fiber/broadband coverage.
- Rybbit remains a whole-project gold blocker until dashboard/API receipts prove the approved taxonomy across conversion, product engagement, billing, tours, support/recovery, and activation without private candidate, listing, or contact payloads.
- Production security remains a whole-project gold blocker until runtime/container hardening, reproducible supply chain, dependency/container scans, SBOM, durable RBAC/session revocation, key rotation, and disabled production override receipts are current.
- Remote candidate CI and deployed/live receipts remain required before launch authority can be granted.

## Rules

- Update this file only from current candidate and production evidence.
- Treat a tracked-`main`/runtime SHA mismatch as blocked until governed deployment reconciles it.
- Store detailed machine receipts in completion artifacts or CI, not in this document.
- Never include credentials, tokens, cookies, license keys, or customer data.
- Never bypass the release controller, security runner, provenance, rollback, or disaster-recovery gates.
