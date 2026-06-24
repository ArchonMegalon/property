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
| Runtime commit SHA | `0576d5c8cc1cfa9869fb6a564842981e6f323db0` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-24 after `EA_HOST_PORT=8097 make deploy` |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `0576d5c` passed:

- `curl -H 'Host: propertyquarry.com' http://127.0.0.1:8097/health/ready`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py --base-url http://127.0.0.1:8097 --expected-plan-label Agent --country-code AT`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `PYTHONPATH=ea python3 scripts/check_property_public_tour_manifest_contract.py`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'billing or account or authenticated_app or top_nav or navigation or shortlist'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'heavy_run_payload or payload_compacts or billing_payload or saved_shortlist or mobile_top_nav_scrolls or mobile_what_matters_distance_rows'`

Observed route timings after the latest deploy:

| Route | Latest observed timing |
| --- | --- |
| `/app/search` | 0.78s, 1.82s, 1.35s repeated probes |
| `/app/billing` | 1.37s, 2.24s, 1.50s repeated probes; authenticated smoke observed 1.18s |
| `/app/account` | 2.60s, 2.59s, 1.40s repeated probes; authenticated smoke observed 1.40s |
| `/app/shortlist` | 4.04s, 2.72s, 2.23s repeated probes before receipt redeploy; 6.54s cold probe and 4.25s, 4.58s, 3.89s, 4.29s, 3.73s warmed probes after receipt redeploy |

Internal payload probes after the latest deploy:

| Surface | Context mean | Payload-build mean | Payload object size |
| --- | ---: | ---: | ---: |
| `/app/billing` | 0.003s | 0.012s | 19,020 chars |
| `/app/shortlist` | 0.468s | 0.012s | 220,571 chars |

The previous billing payload carried roughly 16.6 MB of account/form state and the previous shortlist payload carried roughly 30.7 MB of raw account/run state. The current runtime trims those hidden payloads while preserving customer-visible account, billing, shortlist, and selected-review state. Backend saved-shortlist filtering now measured `1.643s` mean over five in-container probes; full-page `/app/shortlist` improved but remains over the premium target and needs another pass.

## Gold Blockers

- Full-page `/app/shortlist` improved from 7-11s repeated probes to roughly 3.7-4.6s warmed probes, but still needs another latency pass plus browser/performance-budget receipts before gold.
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
