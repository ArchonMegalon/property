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
| Runtime commit SHA | `66706760f4873c97fcae82c5387fffbb51cfdb82` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-25 after `EA_HOST_PORT=8097 make deploy` for compact authenticated first paint, deploy-smoke retry hardening, visual-state self-healing, deploy-probe, mobile What Matters non-clipped distance controls, research ranking-only detail pages with no compare cards, MagicFit playable-video verifier hardening, expanded mobile/settings smoke coverage, Brilliant Directories timestamped-HMAC billing receipt/replay hardening with public advisory webhook route, stricter 3DVista/Pano2VR local-export verifier gates and verified importers, mobile navigation, notification routing, billing handoff recovery, Rybbit analytics privacy, hosted tour-control verifier, and all-search-ready provider matrix candidate |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `6670676` passed:

- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `PYTHONPATH=ea python3 scripts/check_property_security_posture.py`
- `PYTHONPATH=ea pytest -q tests/test_property_live_authenticated_smoke.py tests/test_property_authenticated_performance_smoke.py`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'account_and_billing_templates_keep_controls_minimal or billing_surface_stays_compact or static_property_surfaces_skip_full_fleet_digest_on_first_paint'`
- `python3 -m py_compile ea/app/services/onboarding.py ea/app/api/routes/landing.py`
- `EA_HOST_PORT=8097 make deploy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready`
- `PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url https://propertyquarry.com --timeout-seconds 12`
- `PYTHONPATH=ea pytest -q tests/test_property_tour_control_verifier.py tests/test_property_repo_isolation_contracts.py -k 'tour_control_verifier or release_gates_include_phase'`
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
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'mobile_what_matters_distance_rows_are_not_clipped or search_route_renders_what_matters_as_comboboxes'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'settings_subpages_keep_property_shell_and_mobile_dock or shell_uses_the_new_surface_navigation'`
- `PYTHONPATH=ea pytest -q tests/test_property_packet_publications.py`
- `PYTHONPATH=ea pytest -q tests/test_property_search_runs.py -k 'schema_ready_does_not_backfill_existing_compact_columns or upsert_skips_noop_conflict_updates or lightweight_listing_strips_source_payloads or status_lightweight_fixes_inflated_provider_total'`
- `PYTHONPATH=ea pytest -q tests/test_property_search_runs.py -k 'visual_state_does_not_cross_update_same_source_ref_different_provider or schema_ready_does_not_backfill_existing_compact_columns or upsert_skips_noop_conflict_updates'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'property_candidate_feedback_skips_empty_feedback_summary_hydration or property_console_context_shortlist_preserves_all_source_candidates_while_run_is_active or property_console_context_uses_lightweight_status_for_explicit_research_run or research_route_uses_research_surface_contract or research_packet'`
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'research_packet or research_route_uses_research_surface_contract'`
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
- Public Cloudflare smoke for `https://propertyquarry.com` returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after deploy returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The current public bundle is explicitly classified as `gallery_only_not_3d`, so it is not allowed to count as a verified 3D tour. The receipt intentionally omits raw provider URLs.
- All-search-ready provider matrix dry-run after deploy returned `status=dry_run`, `country_scope=all_search_ready`, 17 countries, 121 search-ready providers, 242 cases, 121 strict no-soft-filter payloads, 121 soft-filter payloads, `payload_contracts_ok=True`, `agent_unlimited_results_ok=True`, `strict_without_soft_filters_ok=True`, and `soft_filters_present_ok=True`. Receipt written to `_completion/provider_smoke/all-search-ready-dry-run.json`.
- Deploy-gated authenticated smoke after compact first-paint returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Direct authenticated origin timings after compact first-paint were `/sign-in` 1.83s, `/app/account` 3.16s, and `/app/billing` 2.83s; before the fix the same surfaces were approximately 9.83s, 15.36s, and 17.03s under the same local-origin probe pattern.
- Local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget while also proving `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, and `mobile_dock_target` for search, agents, properties, shortlist, research, account, and billing.
- After the mobile What Matters non-clipping deploy, local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget: `/app/search` 0.304s, `/app/agents` 0.039s, `/app/properties` 0.045s, `/app/shortlist` 0.045s, `/app/research/<fixture>` 0.058s, `/app/account` 0.038s, and `/app/billing` 0.026s. The same receipt again proved `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, and `mobile_dock_target` on every measured app surface.
- Public Cloudflare smoke after the mobile What Matters deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the mobile What Matters deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and `blocked_reason=gallery_only_not_3d` for the only public bundle.
- After the research ranking-only deploy, authenticated origin smoke for `/app/research/77652d2eef381ed2?run_id=5cfe261fe72c4bf0b52ef49b0d584f0d` returned `200` in `1.387s`, rendered `Ranking from this run` and `data-research-ranking-list`, and did not render `prd-compare`, visible `Compare`, `Decision support`, `The next-best properties from this run`, or `Other ranked homes from this run`.
- Public Cloudflare smoke after the research ranking-only deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks. Authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget.
- MagicFit verifier hardening now requires local walkthrough video files to carry a playable MP4/M4V/MOV/WebM signature and live probes to return a `video/*` content type plus a valid video signature. Placeholder text `.mp4` assets no longer count as ready MagicFit walkthrough evidence.
- After redeploying from `454db63`, public Cloudflare smoke returned `status=pass`, `failed_count=0`, and 22 passing route checks. Authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget.
- Hardened hosted tour-control verifier after the `454db63` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and `blocked_reason=gallery_only_not_3d` for the only public bundle.
- After redeploying from `9eee54d`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `9eee54d` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`. The same receipt proved `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, and `mobile_dock_target` on every measured app surface, plus notification delivery controls, Google implicit-account creation copy, and access controls on their dedicated surfaces.
- Public Cloudflare smoke after the `9eee54d` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `9eee54d` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Brilliant Directories billing hardening now has a timestamped HMAC contract, stale timestamp rejection, replay detection against local billing event IDs, redacted advisory receipts, and a tested invariant that Brilliant Directories billing callbacks cannot directly activate plans or entitlements.
- Focused billing hardening tests after `2ccb471` returned 6 passing tests across `tests/test_brilliant_directories_integration.py` and `tests/test_property_search_runs.py` for billing webhook signatures, advisory receipts, replay handling, existing billing handoff receipts, and VAT invoice handoffs.
- After redeploying from `2ccb471`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `2ccb471` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `2ccb471` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `2ccb471` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Brilliant Directories now has a public advisory billing webhook route at `/app/api/signals/property/billing/brilliant-directories/webhook`. Route tests prove it accepts signed callbacks without app auth, persists only local advisory billing events, rejects bad signatures without persistence, treats duplicate event IDs as replayed, and keeps `current_plan_key=free` with entitlement mutation disabled.
- Focused public webhook route tests after `66ca1fa` returned 3 passing tests across the Brilliant Directories route and the existing public PayFunnels callback boundary. Focused service billing tests returned 6 passing tests for billing webhook signatures, advisory receipts, replay handling, existing billing handoff receipts, and VAT invoice handoffs.
- After redeploying from `66ca1fa`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `66ca1fa` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `66ca1fa` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `66ca1fa` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Hosted tour-control verifier hardening now rejects placeholder local 3DVista and Pano2VR entry files. Local 3DVista exports must contain provider/export markers such as `3dvista`, `tdvplayer`, `tdvplayerapi`, `tourviewer`, or `panorama`; local Pano2VR exports must contain markers such as `pano2vr`, `ggpkg`, `ggskin`, `pano.xml`, or `tour.js`.
- Focused verifier tests after `d34b2ba` returned 7 passing tests and prove Matterport, 3DVista, Pano2VR, krpano, and MagicFit can pass only with verified evidence, while MagicFit placeholder videos, local 3DVista/Pano2VR placeholder HTML, pure cube fallbacks, unsafe private paths, and photo-gallery tours fail closed.
- After redeploying from `d34b2ba`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `d34b2ba` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `d34b2ba` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `d34b2ba` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Operator import pipeline now includes `scripts/import_pano2vr_export.py` and a hardened `scripts/import_3dvista_export.py`. Both importers reject placeholder entry HTML before copying assets or mutating `tour.json`; verified imports materialize the declared public control entry and update the manifest for `/control/3dvista` or `/control/pano2vr`.
- Focused importer and verifier tests after `6670676` returned 9 passing tests across verified import materialization, placeholder rejection, Matterport/3DVista/Pano2VR/krpano/MagicFit readiness evidence, and fake-gallery/fake-video fail-closed behavior. Release-gate wiring tests returned 4 passing tests and now include `tests/test_property_tour_export_importers.py`.
- After redeploying from `6670676`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `6670676` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `6670676` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `6670676` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.

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
- The release gate now runs `scripts/verify_property_tour_controls.py`; current hosted tour inventory has zero verified Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls, and the only public bundle is a photo gallery classified as `gallery_only_not_3d`, so visual-media gold remains blocked until real provider controls/assets are imported and the verifier returns ready modes.
- Provider matrix generation now covers every search-ready country/provider in dry-run mode, but live execution against `/app/api/property/search-runs` remains blocked until the full all-search-ready matrix is run with `PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1` and passes without provider/runtime failures.
- The user-referenced research detail route now renders an honest unavailable/skipped visual state, but still has no live 360 source or playable walkthrough for that listing.
- Brilliant Directories billing is in the active gold goal only as a governed handoff; timestamped HMAC verification, replay protection, public advisory webhook routing, local advisory receipt persistence, and disabled entitlement mutation are now covered by tests. Local entitlement reconciliation receipts and an explicit human/operator reconciliation workflow remain release blockers before any Brilliant Directories callback can affect user-visible billing or access state.
- Rybbit app analytics now use taxonomy-style app events and strip candidate identifiers from app Rybbit attributes, but wider conversion/support-loop analytics still need end-to-end dashboard receipts before gold.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, documentation separation, and current-HEAD release evidence.
- The public domain has a current Cloudflare smoke receipt from 2026-06-25, but must still be re-smoked through Cloudflare after each deploy.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
