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
| Runtime commit SHA | `4b5007ebfeab9d7d561dfe63defc55d5d0c17e6f` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | local compose redeploy on 2026-06-25 after `make deploy` for residual live-run placeholder cleanup, current-best placeholder cleanup, minimal search-progress update rendering, billing handoff smoke-contract hardening, premium dossier PDF quality-gate repair, PropertyQuarry tester-gate product-first wording, cached evidence-overlay release-gate wiring, cached evidence-overlay research rendering, evidence-overlay registry gating, whole-project gold blocker scope extension, tour export readiness-state hardening, top-only mobile navigation receipt hardening, external billing handoff smoke alignment, coarse-pointer appbar touch targets, precise distance near-miss warnings, current live-container tour export evidence, mobile research-detail proof gating, and current gold-status blocker reconciliation |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The candidate at `4b5007e` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'current_best_omits_unknown_fact_placeholders or running_state_explains_slow_provider_checks'`
- `python3 - <<'PY' ... PY` verified active PropertyQuarry app templates no longer contain `Price not published`, `Still being verified`, `Still verifying`, `No detail yet.`, `Search trail`, or `Listing evidence`.
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- Residual live-run preview and run-update fallback copy now omits unknown price rows and uses `Search is still running.` instead of empty diagnostic phrasing.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `d6d416c` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'current_best_omits_unknown_fact_placeholders or running_state_explains_slow_provider_checks or research_packet_snapshot_normalizes_route_payload'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- `python3 - <<'PY' ... PY` verified touched templates no longer contain `Price not published` or `Still being verified`.
- Current-best cards now omit unknown price/layout rows instead of reserving screen space for placeholder copy, and the research detail surface uses `Listing facts` instead of the noisier `Listing evidence` label.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `e10f0f3` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'running_state_explains_slow_provider_checks or search_status_replaces_internal_suppression_only_compact_events or search_status_replaces_stale_status_refresh_noise'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- `python3 -m py_compile ea/app/api/routes/landing_property_workspace_payload.py ea/app/api/routes/product_api_delivery.py`
- Search-progress UI now renders `More updates` instead of `Search trail`, caps the visible update list at four useful rows, and hides internal repair receipts, `suppressed_generic_listing_page`, transient status-refresh failures, and stale “checking run status” messages in both server-rendered and live-polled states.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `f26f6ab` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_authenticated_smoke.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_mobile_surface_smoke.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_brilliant_directories_integration.py -k 'billing_handoff or property_billing_route_redirects'`
- `python3 -m py_compile scripts/propertyquarry_live_authenticated_smoke.py scripts/propertyquarry_live_mobile_surface_smoke.py`
- Authenticated and mobile billing smokes now accept only a governed external account-lane redirect or an explicit fail-closed recovery page for unresolved billing handoff DNS. Regressions back to a local signed-in pricing, plan, checkout, or billing-history board fail the smoke contract instead of passing as customer billing readiness.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `7e34e7e` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_fliplink_packet_privacy.py -k 'paid_market_report_redaction_is_market_level_only or fliplink_pdf_receipt_matches_pdf_hash or fliplink_pdf_uses_tour_fallback_when_redacted_payload_lacks_direct_tour_url or fliplink_pdf_can_embed_magic_fit_scene_for_private_packet'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_premium_dossier_contracts.py -k 'sanitized_manifest_for_required_text or quality_gate_rejects_visible_raw_urls or quality_gate_requires_real_pdf_text_extraction or text_manifest'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_phase7_exit_gate.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_tester_gold_gate.py`
- `python3 -m py_compile ea/app/services/premium_dossier/qa.py ea/app/services/premium_dossier/__init__.py`
- Premium dossier PDF rendering now uses the sanitized text manifest as required-text evidence when Chromium/Playwright PDFs have weak extractable text, while forbidden/private text and visible raw-URL checks remain fail-closed. FlipLink packet tests again prove PDF artifact paths, hashes, MagicFit scene payloads, market-level redaction, and tour fallback links.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_deploy_operator_contracts.py -k 'cached_evidence_overlay_contracts or phase_and_master_regressions or live_mobile_surface_smoke'`
- `bash -n scripts/property_release_gates.sh`
- The gold release bundle now runs `tests/test_property_evidence_overlays.py`, so unavailable/stale/verified overlay states and the no-inline-source-indexing guarantee cannot be skipped by a release-gate pass.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_evidence_overlays.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'research_packet_snapshot_normalizes_route_payload or research_packet_renders_cached_evidence_overlays'`
- `python3 -m py_compile ea/app/product/property_evidence_overlays.py ea/app/product/property_surface_state.py ea/app/product/models.py ea/app/api/routes/landing.py ea/app/api/routes/landing_property_research.py`
- Research detail now renders a cached-only evidence-overlay section for environmental quality, summer heat, traffic/noise, public mobility, school context, official safety context, media attention, and fiber/broadband. Missing rollups render unavailable instead of fake heatmaps, verified media rows can link original articles, stale rows are labeled stale, and search execution remains forbidden from inline source indexing.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_whole_project_scope.py`
- `PYTHONPATH=ea python3 scripts/check_property_whole_project_scope.py`
- `python3 -m json.tool docs/PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json`
- Evidence overlay scope now has an enforced registry contract for environmental quality, summer heat, traffic/noise, public mobility, school context, official aggregate safety context, media-attention statistics with article links, and fiber/broadband coverage. The contract requires async Teable-first ingestion, cached Postgres/read-model rollups, unavailable/stale/verified UI states, provenance/freshness fields, and no inline source indexing during search execution.
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Whole-project gold blockers are now explicitly tracked for implemented evidence overlays with Teable-backed ingestion, Rybbit dashboard/API receipts, continuous visual/accessibility release gates, and production security/supply-chain/RBAC hardening receipts.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_manifest.py tests/test_propertyquarry_gold_status.py -k 'materialize_property_tour_export_manifest or gold_status'`
- `python3 -m py_compile scripts/materialize_property_tour_export_manifest.py scripts/propertyquarry_gold_status.py`
- `docker exec --user root propertyquarry-api python /app/scripts/materialize_property_tour_export_manifest.py --tour-root /data/public_property_tours --incoming-root /data/incoming_property_tours --prepare-dirs --write /data/artifacts/property-tour-export-import-manifest-release-gate-live-container.json`
- Live-container export manifest now reports `status=waiting_for_verified_assets`, `import_count=3`, `drop_status_summary={"ready_for_import":0,"waiting_for_assets":3,"other":0}`, and providers `3dvista`, `krpano`, and `pano2vr`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --performance-receipt _completion/smoke/property-auth-performance-release-gate.json --tour-control-receipt _completion/property_tour_controls/release-gate.json --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json --write _completion/property_gold_status/release-gate.json`
- Current gold status remains `blocked`; operator import lanes are prepared but have zero ready importable provider assets, and gold still requires verified 3DVista, Pano2VR, and krpano evidence plus resolving `billing.propertyquarry.com`.
- `bash scripts/smoke_api.sh`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_mobile_surface_smoke.py tests/test_property_authenticated_performance_smoke.py tests/test_propertyquarry_workspace_redesign.py -k 'live_mobile_smoke or authenticated_performance_smoke or settings_subpages_keep_property_shell_and_top_mobile_nav'`
- `PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py` returned `status=pass`, `failed_count=0`, `route_count=15`, and verified `/app/billing` as a `303` external handoff redirect to the allowlisted local smoke host.
- `python3 -m py_compile scripts/propertyquarry_authenticated_performance_smoke.py scripts/propertyquarry_live_mobile_surface_smoke.py`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_surface_accessibility_gate.py tests/test_propertyquarry_workspace_redesign.py -k 'surface_accessibility_gate or shell_uses_the_new_surface_navigation or settings_subpages_keep_property_shell_and_top_mobile_nav'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `docker exec propertyquarry-api sh -lc "grep -n 'mobile-dock-target\|pq-appbar-mobile-nav a' /app/app/templates/base_console.html | head -20"` showed top appbar nav selectors and no `mobile-dock-target` token.
- `bash scripts/smoke_api.sh`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_search_runs.py -k 'distance_gate_records_relaxed_and_unknown_distances or property_filter_near_miss_feedback_buttons_fit_telegram_callback_limit or property_filter_near_miss_message or property_scout_queued_near_miss'`
- `python3 -m py_compile ea/app/product/service.py`
- `make deploy`
- `bash scripts/smoke_api.sh`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_mobile_surface_smoke.py tests/test_property_deploy_operator_contracts.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py tests/test_property_deploy_operator_contracts.py`
- `docker exec propertyquarry-api python /app/scripts/discover_property_tour_exports.py --drop-dir /data/incoming_property_tours --public-tour-dir /data/public_property_tours --write /data/artifacts/property-tour-export-discovery-release-gate-live-container.json`
- `docker exec --user root propertyquarry-api python /app/scripts/materialize_property_tour_export_manifest.py --tour-root /data/public_property_tours --incoming-root /data/incoming_property_tours --prepare-dirs --write /data/artifacts/property-tour-export-import-manifest-release-gate-live-container.json`
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --performance-receipt _completion/smoke/property-auth-performance-release-gate.json --tour-control-receipt _completion/property_tour_controls/release-gate.json --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json --write _completion/property_gold_status/release-gate.json`
- Current gold status remains `blocked` only for verified `3dvista`, `pano2vr`, and `krpano` tour evidence, missing verified export drops, and unresolved `billing.propertyquarry.com` DNS.

Prior candidate receipts retained below:

- `pytest -q tests/test_product_api_contracts.py -k 'pano2vr_route or pano2vr_requires_declared_entry or pano2vr_embeds_export_entry or pano2vr_spatial_review or compare_links_offer_pano2vr or compare_links_omit_placeholder_pano2vr'`
- `pytest -q tests/test_property_tour_export_importers.py -k 'pano2vr'`
- `python3 -m py_compile ea/app/api/routes/public_tours.py`
- `pytest -q tests/test_product_api_contracts.py -k '3dvista_route or 3dvista_requires_real_export or embeds_external_3dvista or rejects_3dvista_lookalike or compare_links_omit_missing_3dvista or provider_rule_exit_gate_requires_selected_provider_links'`
- `pytest -q tests/test_property_tour_export_importers.py -k '3dvista'`
- `python3 -m py_compile ea/app/api/routes/public_tours.py scripts/import_3dvista_export.py`
- `pytest -q tests/test_product_api_contracts.py -k 'krpano_requires_license or krpano_embeds_license_marker or krpano_rejects_placeholder or krpano_route or compare_links_offer_krpano or provider_rule_exit_gate_accepts_licensed_krpano'`
- `pytest -q tests/test_property_tour_export_importers.py tests/test_property_tour_control_verifier.py -k 'krpano'`
- `python3 -m py_compile ea/app/api/routes/public_tours.py`
- `pytest -q tests/test_product_api_contracts.py -k 'public_tour_control_krpano'`
- `pytest -q tests/test_propertyquarry_gold_status.py`
- `python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/latest.json --fail-on-blocked`
- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py::test_propertyquarry_research_detail_is_mobile_optimized_and_visuals_are_opt_in`
- `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py::test_propertyquarry_shortlist_and_research_surfaces_do_not_bleed_text`
- `EA_HOST_PORT=8097 make deploy`
- `docker compose -f docker-compose.property.yml exec -T propertyquarry-api sh -lc "grep -n 'prd-decision-savebar\|Add an optional note' /app/app/templates/app/property_research_detail.html"`
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
- `PYTHONPATH=ea pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'settings_subpages_keep_property_shell_and_top_mobile_nav or shell_uses_the_new_surface_navigation'`
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
- Authenticated mobile-origin smoke for `/app/billing` returned `200`, rendered `Plan and payments`, `White-label account lane`, `Local billing is active`, and `external account lane is not enabled`, hid `Brilliant Directories`/`brilliantdirectories`, and used the shared top navigation without a legacy bottom dock.
- Authenticated origin smoke for `/app/search` after Rybbit analytics sanitization rendered `pq.property.opened`, `pq.tour.opened`, and `pq.flythrough.opened`, did not render `data-rybbit-prop-candidate`, did not render old `data-rybbit-event="property_*"` app event names, and did not render `saved_search_id` analytics payloads.
- Public Cloudflare smoke for `https://propertyquarry.com` returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after deploy returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The current public bundle is explicitly classified as `gallery_only_not_3d`, so it is not allowed to count as a verified 3D tour. The receipt intentionally omits raw provider URLs.
- All-search-ready provider matrix dry-run after deploy returned `status=dry_run`, `country_scope=all_search_ready`, 17 countries, 121 search-ready providers, 242 cases, 121 strict no-soft-filter payloads, 121 soft-filter payloads, `payload_contracts_ok=True`, `agent_unlimited_results_ok=True`, `strict_without_soft_filters_ok=True`, and `soft_filters_present_ok=True`. Receipt written to `_completion/provider_smoke/all-search-ready-dry-run.json`.
- Deploy-gated authenticated smoke after compact first-paint returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Direct authenticated origin timings after compact first-paint were `/sign-in` 1.83s, `/app/account` 3.16s, and `/app/billing` 2.83s; before the fix the same surfaces were approximately 9.83s, 15.36s, and 17.03s under the same local-origin probe pattern.
- Local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget while also proving `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, top-navigation-only mobile behavior, and touch targets for search, agents, properties, shortlist, research, account, and billing.
- After the mobile What Matters non-clipping deploy, local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget: `/app/search` 0.304s, `/app/agents` 0.039s, `/app/properties` 0.045s, `/app/shortlist` 0.045s, `/app/research/<fixture>` 0.058s, `/app/account` 0.038s, and `/app/billing` 0.026s. The same receipt again proved `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, top-navigation-only mobile behavior, and touch targets on every measured app surface.
- Public Cloudflare smoke after the mobile What Matters deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the mobile What Matters deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and `blocked_reason=gallery_only_not_3d` for the only public bundle.
- After the research ranking-only deploy, authenticated origin smoke for `/app/research/77652d2eef381ed2?run_id=5cfe261fe72c4bf0b52ef49b0d584f0d` returned `200` in `1.387s`, rendered `Ranking from this run` and `data-research-ranking-list`, and did not render `prd-compare`, visible `Compare`, `Decision support`, `The next-best properties from this run`, or `Other ranked homes from this run`.
- Public Cloudflare smoke after the research ranking-only deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks. Authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget.
- MagicFit verifier hardening now requires local walkthrough video files to carry a playable MP4/M4V/MOV/WebM signature and live probes to return a `video/*` content type plus a valid video signature. Placeholder text `.mp4` assets no longer count as ready MagicFit walkthrough evidence.
- After redeploying from `454db63`, public Cloudflare smoke returned `status=pass`, `failed_count=0`, and 22 passing route checks. Authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and seven routes under the 1200 ms first-paint budget.
- Hardened hosted tour-control verifier after the `454db63` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and `blocked_reason=gallery_only_not_3d` for the only public bundle.
- After redeploying from `9eee54d`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `9eee54d` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`. The same receipt proved `mobile_viewport_meta`, `shared_top_navigation`, `property_app_shell`, top-navigation-only mobile behavior, and touch targets on every measured app surface, plus notification delivery controls, Google implicit-account creation copy, and access controls on their dedicated surfaces.
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
- Operator batch import pipeline now includes `scripts/import_property_tour_exports.py`, a manifest-driven wrapper for real 3DVista/Pano2VR exports. It delegates to the hardened single-export importers, writes one auditable receipt, rejects placeholder rows without false readiness, and is packaged in the PropertyQuarry runtime image for container-side promotion of real exports.
- Focused importer and verifier tests after `6670676` returned 9 passing tests across verified import materialization, placeholder rejection, Matterport/3DVista/Pano2VR/krpano/MagicFit readiness evidence, and fake-gallery/fake-video fail-closed behavior. Release-gate wiring tests returned 4 passing tests and now include `tests/test_property_tour_export_importers.py`.
- After redeploying from `6670676`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `6670676` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `6670676` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `6670676` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Operator import pipeline now includes `scripts/import_magicfit_walkthrough.py`. The importer rejects placeholder/unplayable videos before copying assets or mutating `tour.json`; verified imports copy a playable MP4/M4V/MOV/WebM, set `video_provider=magicfit`, set `video_coverage_proof=boundary_verified_frame_continuation`, and record a redacted sha256/size import receipt.
- Focused MagicFit importer and verifier tests after `7e1d041` returned 10 passing tests across verified import materialization, placeholder rejection, Matterport/3DVista/Pano2VR/krpano/MagicFit readiness evidence, and fake-gallery/fake-video fail-closed behavior. Release-gate wiring tests returned 4 passing tests.
- After redeploying from `7e1d041`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `7e1d041` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `7e1d041` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `7e1d041` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- MagicFit walkthrough imports now require a MagicFit render receipt by default. The importer rejects unplayable videos, missing receipts, non-MagicFit receipts, and receipt/output mismatches before copying assets or mutating `tour.json`; the explicit unreceipted flag is reserved for tests/operator fixtures.
- Focused MagicFit importer and verifier tests after `5365058` returned 10 passing tests across receipt-backed import materialization, placeholder rejection, unreceipted-video rejection, Matterport/3DVista/Pano2VR/krpano/MagicFit readiness evidence, and fake-gallery/fake-video fail-closed behavior.
- The first redeploy attempt from `5365058` reached API health but the built-in authenticated deploy smoke timed out on cold `/app/account`. A follow-up readiness check passed, the local authenticated multi-surface performance smoke passed all 10 routes, public Cloudflare smoke passed all 22 routes, and a second `EA_HOST_PORT=8097 make deploy` exited cleanly.
- Hosted tour-control verifier after the `5365058` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- The property runtime image now explicitly packages `/app/scripts/import_3dvista_export.py`, `/app/scripts/import_pano2vr_export.py`, and `/app/scripts/import_magicfit_walkthrough.py` without broad script copying. Container receipt after the `d738573` deploy listed all three importers and `python -m py_compile` succeeded inside `propertyquarry-api`.
- Focused deploy/operator contracts after `d738573` returned 6 passing tests for runtime script allowlisting, no fleet-path dependencies, and release-gate coverage. Focused tour importer/verifier tests returned 10 passing tests.
- After redeploying from `d738573`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `d738573` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `d738573` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Hosted tour-control verifier after the `d738573` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Provider E2E smoke now requires a readable search-run status receipt for every executed targeted provider case. A provider case no longer passes on POST dispatch alone; it must return a matching `run_id` from the status endpoint in addition to the strict/soft-filter payload contract.
- Focused provider-smoke tests after `a33bd8c` returned 8 passing tests, including strict and soft-filter targeted matrix execution, checkpoint receipt writing, agent-tier unlimited payloads, status-probe success, and status-probe failure handling.
- After redeploying from `a33bd8c`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `a33bd8c` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Public Cloudflare smoke after the `a33bd8c` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- All-search-ready provider matrix dry-run after the `a33bd8c` deploy returned `status=dry_run`, `country_scope=all_search_ready`, 17 countries, 121 search-ready providers, 242 cases, 121 strict no-soft-filter payloads, 121 soft-filter payloads, `payload_contracts_ok=True`, `agent_unlimited_results_ok=True`, `strict_without_soft_filters_ok=True`, `soft_filters_present_ok=True`, and a status-probe enforcement note for live executions.
- Hosted tour-control verifier after the `a33bd8c` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Mobile app surface hardening after `4e778d9` raised the phone mode-switch target from 34px to 44px, applied static-surface non-sticky/unclipped mobile panel behavior to `/app/alerts`, and extended the Playwright phone gate to `/app/agents`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access` with viewport, overflow, visual-shell, dock-size, and route-specific assertions.
- Focused browser mobile receipts after `4e778d9` returned `1 passed` for `test_propertyquarry_secondary_surfaces_have_phone_specific_layout` and `8 passed` for the broader mobile subset covering workspace mobile usability, running progress, research-detail mobile optimization, secondary surfaces, dark secondary surfaces, settings top navigation, numeric sliders, and provider-family controls.
- Release hygiene after `4e778d9` returned `ok: property release hygiene`. Local authenticated multi-surface performance smoke returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- After redeploying from `4e778d9`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `4e778d9` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `4e778d9` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `4e778d9` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Brilliant Directories local billing reconciliation after `871ad10` now requires an existing signed advisory event and an authenticated local reconciliation decision before any plan/access state changes. The public webhook remains advisory-only; approve/reject decisions write redacted reconciliation receipts, hash operator/note values, reject unpaid events, reject repeated reconciliation, and preserve PropertyQuarry as billing/entitlement source of truth.
- Focused Brilliant Directories tests after `871ad10` returned `7 passed` for webhook and local-reconciliation service cases, `3 passed` for route-level Brilliant Directories billing cases, and `37 passed` for the full `tests/test_brilliant_directories_integration.py` suite.
- `python3 -m py_compile ea/app/services/property_billing.py ea/app/api/routes/product_api_delivery.py` and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed after `871ad10`.
- After redeploying from `871ad10`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `871ad10` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Live public smoke against `http://127.0.0.1:8097` after the `871ad10` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `871ad10` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `871ad10` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Automatic listing-fact confirmation after `0143a99` now marks provider/listing-backed price, area, rooms, and location facts as `confirmed` with `requires_manual_confirmation=False`. Ranking cards render a compact `Facts confirmed` badge, and research fact rows tag confirmed budget/layout/location signals as `Confirmed` instead of leaving already-present facts in a vague confirmation state.
- Focused confirmation tests after `0143a99` returned `5 passed` for numeric price confirmation, listing-text price confirmation, core provider fact confirmation, research confirmed-row tags, and candidate snapshot serialization. `python3 -m py_compile` passed for the touched helper, payload, research, model, and surface-state modules.
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed after `0143a99`.
- After redeploying from `0143a99`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Authenticated multi-surface performance smoke after the `0143a99` deploy returned `status=pass`, `failed_count=0`, and 10 routes under the 1200 ms first-paint budget: `/app/search`, `/app/agents`, `/app/properties`, `/app/shortlist`, `/app/research/<fixture>`, `/app/alerts`, `/app/account`, `/app/billing`, `/app/settings/google`, and `/app/settings/access`.
- Live public smoke against `http://127.0.0.1:8097` after the `0143a99` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `0143a99` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `0143a99` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Browser performance gate after `7aae4ce` covers `/app/shortlist?run_id=run-42` under a 3200 ms Playwright `networkidle` budget and the first linked research-detail route under a 3600 ms Playwright `networkidle` budget while asserting the app shell, ranked research links, research ranking list, media frame, 360-first layout, and no horizontal overflow.
- Focused Playwright receipts after `7aae4ce` returned `1 passed` for `test_propertyquarry_shortlist_and_research_have_browser_performance_budget` and `3 passed` for the adjacent shortlist/research visual and mobile subset.
- Release hygiene and authenticated performance smoke passed after `7aae4ce`.
- After redeploying from `7aae4ce`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `7aae4ce` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `7aae4ce` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `7aae4ce` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The only public bundle remains classified as `gallery_only_not_3d`.
- Tour-control verifier hardening after `b8a1c9b` now requires local MagicFit video readiness to have `video_provider`, `video_provider_key`, or `video_render_provider` set to `magicfit`; a generic playable video file no longer counts as MagicFit evidence.
- Focused verifier tests after `b8a1c9b` returned `7 passed` and now prove blocked tours emit provider-specific `missing_evidence` plus aggregate `next_required_actions` for Matterport, 3DVista, Pano2VR, krpano, and MagicFit without leaking unsafe raw provider URLs.
- `python3 -m py_compile scripts/verify_property_tour_controls.py` and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed after `b8a1c9b`.
- After redeploying from `b8a1c9b`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `b8a1c9b` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `b8a1c9b` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `b8a1c9b` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls, and provider-specific next required actions for all five modes.
- Provider matrix receipt hardening after `d83c174` now reports `dispatch_accepted_count`, `dispatch_acceptance_complete`, `status_readback_required`, `status_readback_case_count`, `status_readback_ok_count`, `status_readback_complete`, and a capped `failed_cases` sample so full targeted live runs can be audited without reading every row.
- Focused provider smoke tests after `d83c174` returned `8 passed` and prove successful executed matrices require dispatch acceptance plus status readback for every strict/soft provider case, while unreadable status probes fail the matrix and emit bounded failed-case summaries.
- `python3 -m py_compile scripts/property_live_provider_smoke.py` and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed after `d83c174`.
- All-search-ready provider matrix dry-run after `d83c174` returned `status=dry_run`, `country_scope=all_search_ready`, 17 countries, 121 search-ready providers, 242 cases, 121 strict no-soft-filter payloads, 121 soft-filter payloads, `payload_contracts_ok=True`, `agent_unlimited_results_ok=True`, `dispatch_acceptance_complete=True`, `status_readback_required=False`, and `status_readback_complete=True`.
- After redeploying from `d83c174`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `d83c174` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `d83c174` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- Hosted tour-control verifier after the `d83c174` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls.
- Mobile settings audit expansion after `a4f398f` extends the phone-specific Playwright layout gate to `/app/settings/usage`, `/app/settings/support`, `/app/settings/trust`, and `/app/settings/invitations` in addition to agents, alerts, account, billing, Google settings, and access settings.
- Focused mobile browser receipts after `a4f398f` returned `1 passed` for the expanded secondary-surface phone audit and `3 passed` for the adjacent mobile subset covering secondary surfaces, mobile dark mode, and settings top navigation.
- Scheduler recovery heartbeat hardening after `3936f9e` wraps property search recovery in the existing scheduler heartbeat watchdog and adds `EA_SCHEDULER_PROPERTY_SEARCH_RECOVERY_TIMEOUT_SECONDS`, preventing long stale-run recovery work from making the scheduler container unhealthy.
- Focused runner receipts after `3936f9e` returned `3 passed` for scheduler heartbeat healthcheck, duplicate-safe heartbeat watchdog behavior, and property-search-recovery heartbeat wrapping.
- `python3 -m py_compile ea/app/runner.py ea/app/scheduler_healthcheck.py` and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed after `3936f9e`.
- A redeploy attempt before `3936f9e` failed because `propertyquarry-scheduler` stayed `unhealthy` with stale heartbeat output; after redeploying from `3936f9e`, `EA_HOST_PORT=8097 make deploy` exited cleanly and scheduler health returned `status=healthy`, `failing_streak=0`, `scheduler heartbeat ok`.
- After redeploying from `3936f9e`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `3936f9e` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `3936f9e` deploy returned `status=pass`, `failed_count=0`, and one-attempt `200` responses for `/app/account`, `/app/billing`, and `/sign-in` with security headers and paid-plan/sign-in checks intact.
- All-search-ready provider matrix dry-run after the `3936f9e` deploy returned `status=dry_run`, 17 countries, 121 search-ready providers, 242 cases, and `status_readback_complete=True` with live readback not required in dry-run mode.
- Hosted tour-control verifier after the `3936f9e` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls.
- Provider matrix execution after `3de07fa` can now resume from `--resume-from` checkpoint/final receipts. Passed strict/soft rows are reused with `resumed_from_checkpoint=True`, failures and missing rows rerun, and the summary reports `resumed_case_count`.
- Focused provider smoke tests after `3de07fa` returned `9 passed`, including resumable targeted-search execution, dispatch acceptance, status readback, unreadable-status failure, all-search-ready expansion, and dry-run payload contracts.
- A deploy attempt after provider resume failed the authenticated smoke because scheduler property recovery saturated the database during cold first-paint: `/app/account` and `/app/billing` timed out at 8s, with manual probes around 11-13s while many `property_search_runs` upserts were active.
- Scheduler cold-start deferral after `fe0eb25` delays property search recovery and property results finalization until after their first interval, preventing heavy background recovery from competing with deploy first-paint smoke.
- Focused runner/provider receipts after `fe0eb25` returned `3 passed` for scheduler heartbeat/recovery contracts and `9 passed` for provider smoke contracts. `python3 -m py_compile ea/app/runner.py scripts/property_live_provider_smoke.py` and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` passed.
- After redeploying from `fe0eb25`, `EA_HOST_PORT=8097 make deploy` exited cleanly, scheduler health returned `status=healthy`, `failing_streak=0`, and local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `fe0eb25` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `fe0eb25` deploy returned `status=pass`, `failed_count=0`, and one-attempt responses for `/app/account` in `824ms`, `/app/billing` in `1013ms`, and `/sign-in` in `617ms`.
- All-search-ready provider matrix dry-run after the `fe0eb25` deploy returned `status=dry_run`, `resume_source=_completion/provider_smoke/all-search-ready-dry-run.json`, 17 countries, 121 search-ready providers, 242 cases, `resumed_case_count=0`, and `status_readback_complete=True`.
- Hosted tour-control verifier after the `fe0eb25` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls.
- Dispatch-only search-run startup after `a95e100` now returns the persisted queued payload before starting the heavy provider worker. Focused tests returned `1 passed` for `tests/test_property_search_runs.py -k dispatch_only`, `9 passed` for `tests/test_property_live_provider_smoke.py`, `python3 -m py_compile ea/app/product/service.py scripts/property_live_provider_smoke.py` passed, and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` returned `ok: property release hygiene`.
- After redeploying from `a95e100`, `EA_HOST_PORT=8097 make deploy` exited cleanly and local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `a95e100` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks across public pages, PWA/SEO assets, app auth boundary, and Google/Facebook sign-in redirects.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `a95e100` deploy returned `status=pass`, `failed_count=0`, and one-attempt responses for `/app/account` in `1476ms`, `/app/billing` in `1320ms`, and `/sign-in` in `1024ms`.
- Focused live dispatch probes after the `a95e100` deploy reran the previously failing `broker_direct_at` and `leitgoeb_wohnbau_at` strict/soft cases. All four returned queued status and successful status readback: dispatch ACKs took `7331ms`, `8837ms`, `11903ms`, and `10260ms`; status readbacks were under `220ms`.
- The resumed all-search-ready live provider matrix after `a95e100` reached `83/242` targeted strict/soft cases with `83` pass, `0` fail, and `48` resumed from checkpoint. This is progress evidence, not a final live-matrix pass receipt.
- Local authenticated performance smoke after the `a95e100` deploy initially returned two over-budget cold in-process routes (`/app/properties` `1341ms`, `/app/research/<fixture>` `1940ms`) against a `1200ms` budget, but the focused pytest performance gate rerun returned `1 passed`. Treat first-paint performance as improved but still requiring repeatable live/browser receipts before gold.
- Hosted tour-control verifier with `.env` loaded and live probing after the `a95e100` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The krpano license environment is present, but the only public tour bundle still lacks a real `walkable_scene`; the same bundle also lacks verified Matterport/3DVista/Pano2VR exports and a receipt-backed playable MagicFit walkthrough.
- Provider matrix probe mode after `5d0284f` adds a private `X-PropertyQuarry-Dispatch-Probe` header path used by `scripts/property_live_provider_smoke.py`; normal customer `dispatch_only` still starts the worker, while probe mode persists and reads back a queued run without starting the heavy provider crawler. Focused contracts returned `2 passed` for dispatch-only/probe behavior, `9 passed` for provider smoke contracts, `python3 -m py_compile ea/app/api/routes/product_api_delivery.py ea/app/product/service.py scripts/property_live_provider_smoke.py` passed, and `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py` returned `ok: property release hygiene`.
- After redeploying from `5d0284f`, `EA_HOST_PORT=8097 make deploy` exited cleanly and local readiness returned `{"status":"ready","reason":"postgres_ready"}`.
- Live public smoke against `http://127.0.0.1:8097` after the `5d0284f` deploy returned `status=pass`, `failed_count=0`, and 22 passing route checks.
- Live authenticated smoke against `http://127.0.0.1:8097` after the `5d0284f` deploy returned `status=pass`, `failed_count=0`, and one-attempt responses for `/app/account` in `1536ms`, `/app/billing` in `1273ms`, and `/sign-in` in `895ms`.
- Local authenticated performance smoke after the `5d0284f` deploy returned `status=pass`, `failed_count=0`, and 10 app routes under the `1200ms` first-paint budget, including search, agents, properties, shortlist, research, alerts, account, billing, Google settings, and access settings.
- Full all-search-ready live provider matrix after the `5d0284f` deploy returned `status=pass`, `targeted_search_matrix_status=pass`, `complete=True`, 17 countries, 121 search-ready providers, 242 targeted cases, `242` executed, `242` passed, `0` failed, `103` resumed, `dispatch_acceptance_complete=True`, `status_readback_complete=True`, `payload_contracts_ok=True`, and `agent_unlimited_results_ok=True`.
- Hosted tour-control verifier with `.env` loaded and live probing after the `5d0284f` deploy still returned `status=blocked_missing_verified_controls`, `tour_count=1`, `ready_tour_count=0`, and zero ready Matterport, 3DVista, Pano2VR, krpano, or MagicFit controls. The remaining gold blocker is verified tour/walkthrough asset evidence, not provider search dispatch.
- Private-receipt Matterport control rendering after `78f4334` keeps raw provider URLs out of `/tours/{slug}.json` while allowing `/tours/{slug}/control/matterport` to render the verified Matterport iframe from `tour.private.json`.
- After redeploying from `78f4334`, local readiness returned `{"status":"ready","reason":"postgres_ready"}` and the live Matterport control route returned `200` with `Matterport Control` plus the Matterport iframe marker.
- Hosted tour-control verifier with private receipt merging and live probing after the `78f4334` deploy returned `status=pass`, `tour_count=1`, `ready_tour_count=1`, `provider_counts.matterport=1`, and `missing_provider_modes=["3dvista","pano2vr","krpano","magicfit"]`. This unlocks Matterport only; the remaining tour/walkthrough blockers are verified 3DVista export/URL, verified Pano2VR export, real krpano `walkable_scene`, and receipt-backed playable MagicFit walkthrough.
- Property runtime packaging after `06f5628` includes `/app/scripts/verify_property_tour_controls.py`, so live tour-control receipts can be generated inside `propertyquarry-api` against the actual mounted `/data/public_property_tours` volume instead of host-side `state/` only.
- Tour verifier output after `c54c2c2` supports `--summary-only`, keeping full JSON artifacts on disk while printing concise deploy-readable counts/actions.
- After redeploying from `c54c2c2`, local readiness returned `{"status":"ready","reason":"postgres_ready"}`. In-container live tour verification wrote `/data/artifacts/property-tour-controls-live-container.json` and printed `status=pass`, `tour_count=176`, `ready_tour_count=35`, `provider_counts={"matterport":29,"krpano":1,"magicfit":8,"3dvista":0,"pano2vr":0}`, `ready_provider_modes=["krpano","magicfit","matterport"]`, and `missing_provider_modes=["3dvista","pano2vr"]`. The remaining tour-provider gold blocker is now narrowed to verified 3DVista and Pano2VR coverage.
- 3DVista private-receipt activation after `676f07c` is covered by route and verifier tests: a real allowlisted `three_d_vista_url` in `tour.private.json` renders `/tours/{slug}/control/3dvista`, remains absent from `/tours/{slug}.json`, and counts as `provider_counts.3dvista=1` without leaking the raw URL into verifier receipts. No live 3DVista asset is present in `/data/public_property_tours` yet, so production inventory remains at `3dvista=0` until a real export or allowlisted URL is imported.
- Pano2VR private-receipt verifier activation now mirrors the privacy-safe 3DVista path: a verified local Pano2VR export entry referenced from `tour.private.json` counts as `provider_counts.pano2vr=1` without leaking private source URLs, source refs, or private entry filenames into verifier receipts. This does not create live Pano2VR inventory; production remains `pano2vr=0` until a real export is imported into `/data/public_property_tours`.
- Explicit shortlist mobile coverage after `734daea` adds `/app/shortlist?run_id=run-42` to the phone-specific Playwright layout audit. The focused browser gate returned `1 passed`, the static route-coverage guard returned `1 passed`, and the live authenticated performance smoke returned `status=pass`, `failed_count=0`, `route_count=10`; the live shortlist route passed viewport, shared top navigation, app shell, top-navigation-only mobile behavior, and touch-target checks in `35ms`.
- Authenticated performance smoke now covers the full account/settings mobile loop: search, agents, properties, shortlist, research, alerts, account, billing, Google, access, usage, support, trust, and invitations. The focused smoke test module returned `4 passed`, and the local receipt returned `status=pass`, `failed_count=0`, `route_count=14`; all measured routes passed shared top navigation, viewport, app shell, top-navigation-only mobile behavior, no generic EA copy, and no customer-jargon checks.
- Research detail evidence after the confirmed-facts smoke hardening renders a compact `Confirmed facts` band from `research_score_rows` on the actual packet page. The authenticated smoke now seeds a saved shortlist fallback, rejects research redirects, and requires visible `Facts confirmed`, `confirmed automatically from provider evidence`, `Budget signal`, and `EUR 1,290` on `/app/research/perf-candidate-1020`; focused tests returned `4 passed` for the smoke module and `1 passed` for auto-confirmed research rows.
- MagicFit walkthrough proof is now stricter than container-signature presence. The importer and hosted tour verifier use `ffprobe` when available to require a decodable video stream with positive duration; signature-only `ftyp` stubs are rejected. Focused importer/verifier tests returned `16 passed` with a generated real MP4 fixture and explicit placeholder/stub rejection.
- Rybbit app analytics privacy is now part of the authenticated runtime smoke across 14 app routes. The gate requires no Rybbit identify calls, only approved app taxonomy events, only approved Rybbit data attributes, and no candidate/run/listing/saved-search/principal/email/phone tokens in serialized Rybbit attributes.
- Mobile What Matters hardening now proves the reported Playground `Nice to have` interaction in a 390px phone viewport: the distance combobox becomes enabled, remains a full-width 44px tap target, stays inside the viewport, and is not hidden behind a bottom mobile overlay. Focused static and Playwright checks returned `2 passed`.
- Visual self-healing now clears stale `tour_*_repair_*` / `flythrough_*_repair_*` markers when a terminal visual-status resolution is persisted, so blocked/skipped media no longer carries old repair-running metadata. Focused visual-status repair tests returned `5 passed`.
- Billing white-label quality is now part of the authenticated runtime smoke: `/app/billing` must show plan/payment/history/invoice surfaces while hiding PayFunnels, Brilliant Directories, provider endpoint strings, billing-truth jargon, invoice-handoff wording, and internal plan-limit labels.
- Sign-in quality is now part of the authenticated runtime smoke: `/sign-in` must render as a mobile-ready PropertyQuarry auth surface, state that first-time provider sign-in creates the account automatically, and avoid leaking raw OAuth configuration errors in normal copy.
- Account notification quality is now part of the authenticated runtime smoke: `/app/account` must render Email, Telegram, WhatsApp destination controls, primary-channel routing, opt-in copy for strong matches and near-miss follow-ups, and no raw Telegram secret or delivery-receipt payload names.
- Research visual-media quality is now part of the authenticated runtime smoke: `/app/research/<listing>` must render separate 3D tour and walkthrough cards, expose honest request controls when visual media is unevidenced, and avoid fake ready/open states for missing provider evidence.
- Mobile motor-accessibility is now covered by a browser gate across `/app/search`, shortlist, alerts, account, billing, Google/access/usage/support/trust/invitations settings, and research detail. The phone gate rejects horizontal page overflow and visible controls below the touch-target floor, including search district rows, result action pills, settings actions, and research feedback buttons.

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

The previous billing payload carried roughly 16.6 MB of account/form state and the previous shortlist payload carried roughly 30.7 MB of raw account/run state. The current runtime trims those hidden payloads while preserving customer-visible account, billing, shortlist, and selected-review state. Saved-shortlist lookup now reuses already-loaded onboarding status and measured 0.012s-0.035s after the cold run. Full-page `/app/shortlist` is much closer to the premium target and now has a Playwright browser performance-budget gate, but the same gate still needs to run against the production public domain after every release candidate before a gold claim.

## Gold Blockers

- Full-page `/app/shortlist` improved from 7-11s repeated probes to roughly 1.2-2.4s warmed probes after a 3.75s cold request and now has a Playwright browser performance-budget gate; gold still needs the same gate run against the production public domain/Cloudflare after every release candidate.
- The user-referenced research detail route improved from repeated 21-25s origin responses and a 14.02s post-compact-context cold request to 1.3-1.7s origin responses after removing redundant feedback reads and no-op search-run rewrites, and the shortlist-to-research Playwright budget gate now covers research detail navigation; gold still needs the user-referenced live route to have a verified 360 source or playable walkthrough.
- The release gate now verifies the live container tour volume. Current live inventory has 176 hosted tours, 35 ready tours, ready Matterport and MagicFit provider modes, and no verified 3DVista, Pano2VR, or krpano provider mode. Visual-media gold remains blocked until real 3DVista/Pano2VR/krpano evidence is imported and the live verifier reports all required modes ready.
- Provider matrix generation now covers every search-ready country/provider in dry-run mode, live execution requires dispatch-acceptance and status-readback completeness receipts, interrupted runs can resume from passed checkpoint rows, and the full all-search-ready live matrix passed after `5d0284f` with `242/242` targeted strict/soft cases. Gold still requires the broader release blockers, especially verified tour/walkthrough controls, to be resolved.
- The user-referenced research detail route now renders an honest unavailable/skipped visual state, but still has no live 360 source or playable walkthrough for that listing.
- Brilliant Directories billing is in the active gold goal only as a governed handoff; timestamped HMAC verification, replay protection, public advisory webhook routing, local advisory receipt persistence, disabled webhook entitlement mutation, and authenticated local reconciliation are covered by tests. Gold remains blocked because the configured billing handoff host `billing.propertyquarry.com` does not resolve DNS, so `/app/billing` must fail closed instead of pretending the external account lane is live.
- Rybbit app analytics now use taxonomy-style app events and strip candidate identifiers from app Rybbit attributes, but wider conversion/support-loop analytics still need end-to-end dashboard receipts before gold.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, documentation separation, and current-HEAD release evidence.
- Evidence-map overlays remain a whole-project gold blocker until environmental quality, summer heat, traffic/noise, public mobility, school context, official aggregate safety context, media-attention statistics with article links, and fiber/broadband coverage are implemented from source registries through Teable ingestion, cached read models, unavailable/stale/verified UI states, and search-performance receipts proving no inline source indexing.
- Rybbit remains a whole-project gold blocker until dashboard/API receipts prove the approved taxonomy arrives for public conversion, authenticated product engagement, billing handoff, tour/walkthrough interaction, support/recovery, and search activation without private candidate/listing/contact payloads.
- Release hardening remains a whole-project gold blocker until visual regression, axe/accessibility, keyboard/focus, high-zoom/mobile, empty/error/loading state, and first-value performance-budget gates run as continuous CI or release gates.
- Production security remains a whole-project gold blocker until default runtime/container hardening, locked supply chain, dependency/container scans, SBOM, durable RBAC/session revocation, key rotation posture, and disabled production loopback/principal-header override receipts are current.
- The public domain has a current Cloudflare smoke receipt from 2026-06-25, but must still be re-smoked through Cloudflare after each deploy.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
