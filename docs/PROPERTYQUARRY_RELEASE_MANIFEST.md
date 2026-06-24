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
| Runtime commit SHA | `efd9d814e32c2dd53b2206741e2685f03495b6e9` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-25 after `EA_HOST_PORT=8097 make deploy` |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `efd9d81` passed:

- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `PYTHONPATH=ea pytest -q tests/test_property_packet_publications.py`
- `PYTHONPATH=ea pytest -q tests/test_property_search_runs.py -k 'schema_ready_does_not_backfill_existing_compact_columns or lightweight_listing_strips_source_payloads or status_lightweight_fixes_inflated_provider_total'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'property_candidate_feedback_skips_empty_feedback_summary_hydration or property_console_context_shortlist_preserves_all_source_candidates_while_run_is_active or property_console_context_uses_lightweight_status_for_explicit_research_run or research_route_uses_research_surface_contract or research_packet'`
- Fresh-process server-side profile for the user-referenced research detail route returned `200` in `3.770s` after caching packet feedback reads and skipping empty feedback hydration. The same profile was `17.536s` immediately before this patch.
- Authenticated origin smoke for the user-referenced research detail route returned `200` in `2.769s`; unauthenticated origin smoke returned `401` in `0.004s`.
- Three authenticated origin timing probes for the user-referenced research detail route returned `200` in `2.719s`, `1.699s`, and `1.723s`.
- Origin krpano route smoke against the current hosted walkable bundle `/tours/neu-10-06-neubau-mit-stil-3-zimmer-mit-balkon-und-hipper-wohnkche-sowie-parkett-badewanne-und-au-layout-first-099b3c310c/control/krpano` returned `200` in `0.010s` and rendered `data-viewer="krpano"`, `krpano Licensed Viewer`, and `id="krpano-license"`.
- The user-referenced listing still reports no source 360 and a queued walkthrough.

Observed route timings after the latest deploy:

| Route | Latest observed timing |
| --- | --- |
| `/app/search` | 1.87s single cross-surface probe |
| `/app/billing` | 1.62s single cross-surface probe; authenticated smoke observed 1.29s |
| `/app/account` | 2.26s single cross-surface probe; authenticated smoke observed 1.65s |
| `/sign-in` | authenticated smoke observed 1.00s |
| `/app/shortlist` | 3.75s cold probe, then 2.02s, 1.49s, 1.20s, 2.39s warmed probes; 1.58s single cross-surface probe |
| `/app/research/<listing>` | authenticated origin smoke observed 2.77s first measured request after deploy, then 2.72s, 1.70s, and 1.72s for the user-referenced route |

Internal payload probes after the latest deploy:

| Surface | Context mean | Payload-build mean | Payload object size |
| --- | ---: | ---: | ---: |
| `/app/billing` | 0.003s | 0.012s | 19,020 chars |
| `/app/shortlist` | 0.193s after cold run | 0.030s after cold run | 212,393 chars |

The previous billing payload carried roughly 16.6 MB of account/form state and the previous shortlist payload carried roughly 30.7 MB of raw account/run state. The current runtime trims those hidden payloads while preserving customer-visible account, billing, shortlist, and selected-review state. Saved-shortlist lookup now reuses already-loaded onboarding status and measured 0.012s-0.035s after the cold run. Full-page `/app/shortlist` is much closer to the premium target, but still needs browser/performance-budget receipts before a gold claim.

## Gold Blockers

- Full-page `/app/shortlist` improved from 7-11s repeated probes to roughly 1.2-2.4s warmed probes after a 3.75s cold request, but still needs browser/performance-budget receipts before gold.
- The user-referenced research detail route improved from repeated 21-25s origin responses and a 14.02s post-compact-context cold request to 1.7-2.8s origin responses, but still needs browser/performance-budget receipts before gold.
- Licensed krpano walkable control has a current origin receipt, but verified Matterport, 3DVista, Pano2VR, and MagicFit walkthrough readiness still require complete current-HEAD receipts.
- The user-referenced research detail route still has no live 360 source or playable walkthrough for that listing.
- Brilliant Directories billing is allowed only as a governed handoff; signature verification, replay protection, receipt logging, and local entitlement reconciliation remain release blockers before any webhook-driven state change.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, and documentation separation.
- The public domain should be re-smoked through Cloudflare after each deploy, not only through local origin.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
