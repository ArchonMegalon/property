# PropertyQuarry Release Manifest

This manifest records the last verified runtime candidate for branch/deployment reconciliation. It is a working release receipt, not a gold claim. If tracked `main` moves after the runtime commit below, branch/deployment reconciliation remains open until a fresh deploy receipt updates this manifest.

## Candidate

| Field | Value |
| --- | --- |
| Product | PropertyQuarry |
| Release label | `propertyquarry-gold-board-working-candidate` |
| Status | `working-candidate-blocked` |
| Repository | `/docker/property` |
| Public origin | `https://github.com/ArchonMegalon/property.git` |
| Secondary origin | `https://github.com/ArchonMegalon/propertyquarry.git` |
| Branch | `main` |
| Runtime commit SHA | `57ac4b3908374dc5c9c9049e2f32e247fae5d2f2` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-24 |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `57ac4b3` passed:

- `curl -H 'Host: propertyquarry.com' http://127.0.0.1:8097/health/ready`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py --base-url http://127.0.0.1:8097 --expected-plan-label Agent --country-code AT`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `PYTHONPATH=ea python3 scripts/check_property_public_tour_manifest_contract.py`

Observed route timings after the latest deploy:

| Route | Latest observed timing |
| --- | --- |
| `/app/search` | 2.06s single probe; 2.21s, 2.99s, 4.43s repeated probes |
| `/app/billing` | 2.41s single probe; 2.78s, 4.61s, 5.04s repeated probes |
| `/app/shortlist` | 2.48s single probe; 7.20s, 11.07s, 7.02s repeated probes |

Backend saved-shortlist filtering improved from an earlier mean near 12s to `1.165s` over five in-container probes, but full-page `/app/shortlist` is still not gold-grade.

## Gold Blockers

- Full-page app latency still fluctuates above the premium target, especially `/app/shortlist`.
- Verified Matterport, 3DVista, Pano2VR/krpano, and MagicFit walkthrough readiness still require complete current-HEAD receipts.
- Brilliant Directories billing is allowed only as a governed handoff; signature verification, replay protection, receipt logging, and local entitlement reconciliation remain release blockers before any webhook-driven state change.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, and documentation separation.
- The public domain should be re-smoked through Cloudflare after each deploy, not only through local origin.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
