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
| Runtime commit SHA | `966eda037d7ac7aefaa670754c649adeb4d3e875` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-25 after `EA_HOST_PORT=8097 make deploy` for visual-state self-healing, deploy-probe, and mobile What Matters candidate |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `966eda0` passed:

- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `bash -n scripts/deploy_propertyquarry.sh`
- `PYTHONPATH=ea pytest -q tests/test_property_deploy_operator_contracts.py`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'what_matters_as_comboboxes'`
- `PYTHONPATH=ea pytest -q tests/test_property_packet_publications.py`
- `PYTHONPATH=ea pytest -q tests/test_property_search_runs.py -k 'schema_ready_does_not_backfill_existing_compact_columns or upsert_skips_noop_conflict_updates or lightweight_listing_strips_source_payloads or status_lightweight_fixes_inflated_provider_total'`
- `PYTHONPATH=ea pytest -q tests/test_property_search_runs.py -k 'visual_state_does_not_cross_update_same_source_ref_different_provider or schema_ready_does_not_backfill_existing_compact_columns or upsert_skips_noop_conflict_updates'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'property_candidate_feedback_skips_empty_feedback_summary_hydration or property_console_context_shortlist_preserves_all_source_candidates_while_run_is_active or property_console_context_uses_lightweight_status_for_explicit_research_run or research_route_uses_research_surface_contract or research_packet'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'terminal_walkthrough_reason_is_not_rendered_as_queued or renders_request_actions_when_hosted_tour_is_not_ready or shows_ready_walkthrough_inside_visual_console or prefers_ready_ranked_visual_state_over_stale_source_copy'`
- `PYTHONPATH=ea pytest -q tests/test_product_api_contracts.py -k 'visual_status_hides_internal_skip_reason_for_walkthrough or visual_status_prefers_latest_followup_resolution_over_stale_snapshot or visual_status_retries_stale_visual_requests or visual_status_queues_background_repair_when_stale_repair_is_slow'`
- `python3 -m py_compile ea/app/product/service.py ea/app/api/routes/landing.py ea/app/api/routes/landing_property_research.py`
- Fresh-process server-side profile for the user-referenced research detail route returned `200` in `3.770s` after caching packet feedback reads and skipping empty feedback hydration. The same profile was `17.536s` immediately before this patch.
- Authenticated origin smoke for the user-referenced research detail route returned `200` in `2.769s`; unauthenticated origin smoke returned `401` in `0.004s`.
- Three authenticated origin timing probes for the user-referenced research detail route returned `200` in `2.719s`, `1.699s`, and `1.723s`.
- After adding no-op conflict-update guards for `property_search_runs`, active repeated upserts disappeared from `pg_stat_activity`; three authenticated origin probes returned `200` in `1.696s`, `1.344s`, and `1.357s`.
- Origin krpano route smoke against the current hosted walkable bundle `/tours/neu-10-06-neubau-mit-stil-3-zimmer-mit-balkon-und-hipper-wohnkche-sowie-parkett-badewanne-und-au-layout-first-099b3c310c/control/krpano` returned `200` in `0.010s` and rendered `data-viewer="krpano"`, `krpano Licensed Viewer`, and `id="krpano-license"`.
- Origin visual-status smoke for `/app/api/signals/property/visual-status?run_id=5cfe261fe72c4bf0b52ef49b0d584f0d&request_kind=flythrough&candidate_ref=77652d2eef381ed2` returned a terminal honest state: `status=skipped`, `flythrough_status=skipped`, `tour_status=blocked`, `status_label=Walkthrough unavailable`, no ETA, no playable walkthrough URL, and no internal `fit_below_threshold` reason exposed.
- Stored source and ranked candidate snapshots for the user-referenced listing self-healed to `tour_status=blocked`, `tour_blocked_reason=property_tour_execution_failed`, `flythrough_status=skipped`, blank flythrough reason, progress `0`, and blank ETA.
- Authenticated origin smoke for the user-referenced research detail route returned `200` in `0.812s`; the script-stripped visible page rendered `Walkthrough unavailable`, did not render visible `Walkthrough queued`, did not expose `fit_below_threshold`, and disabled the skipped walkthrough action with a blank ETA.
- Additional authenticated origin smoke after the gold-board scope deploy returned `200` in `4.657s` with the same visible terminal state. Treat this as another reason the route still needs browser/performance-budget receipts before gold.

Observed route timings after the latest deploy:

| Route | Latest observed timing |
| --- | --- |
| `/app/search` | 1.87s single cross-surface probe |
| `/app/billing` | 1.62s single cross-surface probe; authenticated smoke observed 1.29s |
| `/app/account` | 2.26s single cross-surface probe; authenticated smoke observed 1.65s |
| `/sign-in` | authenticated smoke observed 1.00s |
| `/app/shortlist` | 3.75s cold probe, then 2.02s, 1.49s, 1.20s, 2.39s warmed probes; 1.58s single cross-surface probe |
| `/app/research/<listing>` | authenticated origin smoke observed 1.70s, 1.34s, and 1.36s after removing repeated write contention; terminal-visual smokes observed 0.812s and 4.657s for the user-referenced route |

Internal payload probes after the latest deploy:

| Surface | Context mean | Payload-build mean | Payload object size |
| --- | ---: | ---: | ---: |
| `/app/billing` | 0.003s | 0.012s | 19,020 chars |
| `/app/shortlist` | 0.193s after cold run | 0.030s after cold run | 212,393 chars |

The previous billing payload carried roughly 16.6 MB of account/form state and the previous shortlist payload carried roughly 30.7 MB of raw account/run state. The current runtime trims those hidden payloads while preserving customer-visible account, billing, shortlist, and selected-review state. Saved-shortlist lookup now reuses already-loaded onboarding status and measured 0.012s-0.035s after the cold run. Full-page `/app/shortlist` is much closer to the premium target, but still needs browser/performance-budget receipts before a gold claim.

## Gold Blockers

- Full-page `/app/shortlist` improved from 7-11s repeated probes to roughly 1.2-2.4s warmed probes after a 3.75s cold request, but still needs browser/performance-budget receipts before gold.
- The user-referenced research detail route improved from repeated 21-25s origin responses and a 14.02s post-compact-context cold request to 1.3-1.7s origin responses after removing redundant feedback reads and no-op search-run rewrites, but still needs browser/performance-budget receipts before gold.
- Licensed krpano walkable control has a current origin receipt, but verified Matterport, 3DVista, Pano2VR, and MagicFit walkthrough readiness still require complete current-HEAD receipts.
- The user-referenced research detail route now renders an honest unavailable/skipped visual state, but still has no live 360 source or playable walkthrough for that listing.
- Brilliant Directories billing is in the active gold goal only as a governed handoff; signature verification, replay protection, receipt logging, local entitlement reconciliation, mobile billing recovery, and PropertyQuarry-owned plan/invoice/access truth remain release blockers before any webhook-driven or handoff-driven state change.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, documentation separation, and current-HEAD release evidence.
- The public domain should be re-smoked through Cloudflare after each deploy, not only through local origin.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
