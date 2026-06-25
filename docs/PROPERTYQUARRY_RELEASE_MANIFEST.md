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
| Runtime commit SHA | `7a71d31d085c64535db93368724066e88a8d2d94` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-25 after `EA_HOST_PORT=8097 make deploy` for compact authenticated first paint, deploy-smoke retry hardening, visual-state self-healing, deploy-probe, mobile What Matters, mobile navigation, notification routing, billing handoff recovery, Rybbit analytics privacy, hosted tour-control verifier, and all-search-ready provider matrix candidate |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `7a71d31` passed:

- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `PYTHONPATH=ea pytest -q tests/test_property_live_authenticated_smoke.py tests/test_property_authenticated_performance_smoke.py`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'account_and_billing_templates_keep_controls_minimal or billing_surface_stays_compact or static_property_surfaces_skip_full_fleet_digest_on_first_paint'`
- `python3 -m py_compile ea/app/services/onboarding.py ea/app/api/routes/landing.py`
- `EA_HOST_PORT=8097 make deploy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready`
- `PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py`
- `bash -n scripts/deploy_propertyquarry.sh`
- `PYTHONPATH=ea pytest -q tests/test_property_deploy_operator_contracts.py`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'account_and_billing_templates_keep_controls_minimal or account_lifecycle_controls'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'billing_surface_stays_compact or billing_surface_embeds_white_label_commercial_lane or billing_surface_keeps_local_board'`
- `PYTHONPATH=ea pytest -q tests/test_brilliant_directories_integration.py -k 'billing_handoff or receipt_records_billing'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'public_ctas_and_selected_review_panel_expose_rybbit_events or base_console_never_identifies_rybbit_principals'`
- `PYTHONPATH=ea pytest -q tests/test_public_rybbit.py`
- `PYTHONPATH=ea pytest -q tests/test_property_tour_control_verifier.py tests/test_property_repo_isolation_contracts.py -k 'tour_control_verifier or release_gates_include_phase'`
- `PYTHONPATH=ea python3 scripts/verify_property_tour_controls.py --write _completion/property_tour_controls/latest.json`
- `PYTHONPATH=ea pytest -q tests/test_property_live_provider_smoke.py tests/test_property_env_config_contracts.py -k 'live_provider_smoke or env_example'`
- `PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=1 PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py --all-search-ready-countries --write _completion/provider_smoke/all-search-ready-dry-run.json`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'what_matters_as_comboboxes'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'settings_subpages_keep_property_shell_and_mobile_dock or shell_uses_the_new_surface_navigation'`
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
- Authenticated mobile-origin smoke for `/app/billing` returned `200`, rendered `Plan and payments`, `White-label account lane`, `Local billing is active`, and `external account lane is not enabled`, hid `Brilliant Directories`/`brilliantdirectories`, and included the mobile dock.
- Authenticated origin smoke for `/app/search` after Rybbit analytics sanitization rendered `pq.property.opened`, `pq.tour.opened`, and `pq.flythrough.opened`, did not render `data-rybbit-prop-candidate`, did not render old `data-rybbit-event="property_*"` app event names, and did not render `saved_search_id` analytics payloads.
- Hosted tour-control verifier after deploy returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The live-probe receipt was written to `_completion/property_tour_controls/latest-live.json` and intentionally omits raw provider URLs.
- All-search-ready provider matrix dry-run after deploy returned `status=dry_run`, `country_scope=all_search_ready`, 17 countries, 121 search-ready providers, 242 cases, 121 strict no-soft-filter payloads, 121 soft-filter payloads, `payload_contracts_ok=True`, `agent_unlimited_results_ok=True`, `strict_without_soft_filters_ok=True`, and `soft_filters_present_ok=True`. Receipt written to `_completion/provider_smoke/all-search-ready-dry-run.json`.
- Deploy-gated authenticated smoke after compact first-paint returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Direct authenticated origin timings after compact first-paint were `/sign-in` 1.83s, `/app/account` 3.16s, and `/app/billing` 2.83s; before the fix the same surfaces were approximately 9.83s, 15.36s, and 17.03s under the same local-origin probe pattern.
- Local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget while also proving `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, and `mobile_dock_target` for search, agents, properties, shortlist, research, account, and billing.

Observed route timings after the latest deploy:

| Route | Latest observed timing |
| --- | --- |
| `/app/search` | 1.87s single cross-surface probe |
| `/app/billing` | direct authenticated origin probe 2.83s; deploy-smoke observed 2.92s; local first-paint gate 0.024s |
| `/app/account` | direct authenticated origin probe 3.16s; deploy-smoke observed 3.96s; local first-paint gate 0.032s |
| `/sign-in` | direct authenticated origin probe 1.83s; deploy-smoke observed 1.66s |
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
- The release gate now runs `scripts/verify_property_tour_controls.py`; current hosted tour inventory has zero verified Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls, so visual-media gold remains blocked until real provider controls/assets are imported and the verifier returns ready modes.
- Provider matrix generation now covers every search-ready country/provider in dry-run mode, but live execution against `/app/api/property/search-runs` remains blocked until the full all-search-ready matrix is run with `PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1` and passes without provider/runtime failures.
- The user-referenced research detail route now renders an honest unavailable/skipped visual state, but still has no live 360 source or playable walkthrough for that listing.
- Brilliant Directories billing is in the active gold goal only as a governed handoff; the local billing surface now shows fail-closed account-lane recovery, but signature verification, replay protection, receipt logging, local entitlement reconciliation, and PropertyQuarry-owned plan/invoice/access truth remain release blockers before any webhook-driven or handoff-driven state change.
- Rybbit app analytics now use taxonomy-style app events and strip candidate identifiers from app Rybbit attributes, but wider conversion/support-loop analytics still need end-to-end dashboard receipts before gold.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, documentation separation, and current-HEAD release evidence.
- The public domain should be re-smoked through Cloudflare after each deploy, not only through local origin.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
