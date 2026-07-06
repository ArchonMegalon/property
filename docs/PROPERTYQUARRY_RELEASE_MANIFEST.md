# PropertyQuarry Release Manifest

This manifest records the last verified runtime candidate for branch/deployment reconciliation and points at the current gold-proof receipts. It remains the operator-facing release manifest rather than the sole gold authority; the current aggregate gold claim lives in `_completion/property_gold_status/latest.json` and `_completion/property_gold_status/release-gate.json`. If tracked `main` moves after the runtime commit below, branch/deployment reconciliation remains open until a fresh deploy receipt updates this manifest.

## Current Live Correction

The latest live recheck on 2026-06-27 supersedes the earlier provisional Brilliant Directories billing pass. The current edge proof is narrower and more accurate:

- `billing.propertyquarry.com` now resolves and stays first-party.
- `https://billing.propertyquarry.com/account` now redirects only to `https://billing.propertyquarry.com/login?login_direct_url=%2Faccount`.
- The Cloudflare billing handoff worker now keeps `/join` off the stock Brilliant Directories pricing surface by returning `302` to `https://propertyquarry.com/pricing`.
- PropertyQuarry now fails `/app/billing` closed unless the handoff is actually usable; a bridge-only state no longer pretends the external account lane is ready.
- The proxied white-label login form still submits through `billing.propertyquarry.com`, but the remaining external blocker is now only on the Brilliant Directories account-login side:
  - the live login probe still returns `Invalid recaptcha response or setup.` until BD reCAPTCHA is disabled for this lane or a trusted SSO/account handoff exists.
- The backend repair lane at `https://propertyquarry.directoryup.com/admin/login` is reachable without reCAPTCHA and exposes a password-recovery URL, but the locally seeded shared account did not authenticate there on 2026-06-27; the remaining self-service repair dependency is the real Brilliant Directories admin username/password or a completed backend password reset.
- The PropertyQuarry runtime Telegram notification path is verified separately for `cf-email:person@example.test`, but gold/deploy scripts do not send messages by default. Set `PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED=1` for an explicit operator notification run; otherwise `_completion/property_gold_status/telegram-notify-report.json` records a skipped notification.
- `scripts/check_property_release_hygiene.py` was rerun after the 2026-07-01 live proof-copy polish deploy so the manifest can track the current deployed candidate commit again instead of the earlier 2026-06-27 billing-handoff candidate.
- The latest 2026-07-06 live deploy now runs commit `8598c091` locally and through the PropertyQuarry release remotes; it keeps the research-detail nearby-distance backfill live, retries sparse nearby facts when cached postal-area map coordinates exist without `nearest_*` rows, removes the generic nearby-distance fallback rail when a run saved no nearby filters, preserves the selected-distance rail when a run did save nearby filters, restores the generic `3D Tour` marker on the public Matterport control shell, and accepts hosted flythrough-pane walkthrough chips in the presentation gate.
- The current 2026-07-06 gold-status proof still fails closed on scene-video provider runtime readiness until MagicFit/Magic/OMagic account visibility, credit posture, credentials, and OMagic upload-endpoint evidence are refreshed.
- The 2026-07-01 live proof-copy polish deploy removed the default score-guide block, duplicate score explanation cards, visible proof-style selected-property badges, and stale proof-heavy public-tour/dossier/PDF fallback wording.
- The later 2026-07-01 minimal-copy deploy tightened the packet dashboard, workbench research tasks, save feedback, and public-tour language again: visible `Analytics`, `Engagement`, `Next best action`, `Share state`, `Reviewed feedback`, `Optimization recommendations`, `Saved durably`, and `Watch-outs` labels were replaced with calmer customer-facing labels such as `Views`, `Replies`, `Next step`, `Responses`, `Page ideas`, `Saved`, and `Check first`.

That means the billing account lane still requires a second vendor login even though the first-party billing host and redirect contract are now correct. Any earlier receipt lines claiming `billing_handoff.account_handoff_usable=true` should be treated as stale; the refreshed gold receipts keep `billing_handoff.status=ready` while recording the separate-login limitation explicitly.

## Candidate

| Field | Value |
| --- | --- |
| Product | PropertyQuarry |
| Release label | `propertyquarry-gold-board-working-candidate` |
| Status | `working-candidate-with-current-gold-receipt` |
| Repository | `/docker/property` |
| Public origin | `https://github.com/ArchonMegalon/property.git` |
| Secondary origin | `https://github.com/ArchonMegalon/propertyquarry.git` |
| Branch | `main` |
| Runtime commit SHA | `8598c091fbc1376c61007398d95732783a3450cb` |
| Deployment endpoint | `http://127.0.0.1:8097` with `Host: propertyquarry.com` origin smoke |
| Public domain | `https://propertyquarry.com` |
| Deployment ID | `local-20260706T213230Z-8598c091fbc1`; current integrated local/live candidate with nearby-distance backfill on research detail, sparse-nearby retry from cached map coordinates, no-fallback nearby rail when a run saved no nearby filters, selected-distance rail preservation when a run did save nearby filters, hosted walkthrough-chip gate parity, public tour-shell marker repair, public/auth shared-run smoke coverage, presentation and 3D browser gates, account/billing/auth polish, OMagic adapter packaging, and explicit fail-closed scene-video provider-runtime blockers |
| Artifact set | app runtime, templates, tests, docs, compose deployment, smoke scripts |

## Latest Verification

The live no-fallback nearby-distance rail deploy on 2026-07-06 verified:

- Commit `8598c091` is the current deployed runtime candidate for removing the generic nearby-distance fallback rail from research detail pages when a run saved no nearby filters, while preserving the selected-distance rail for runs that did.
- Focused regressions passed:
  - `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_replaces_other_homes_with_selected_distance_checks tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_hides_nearby_distance_panel_when_no_filters_selected` returned `2 passed`.
  - `pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'selected_distance_rows_follow_selected_nearby_filters or backfill_source_research_for_selected_distance_checks or retry_missing_nearby_rows_after_location_hint_attempt or stale_run_distance_detail'` returned `4 passed`.
- `PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E=1 make deploy` rebuilt the live `propertyquarry-api` image and restarted `propertyquarry-api` plus `propertyquarry-scheduler`; the deploy wrapper then passed public smoke, authenticated smoke, mobile smoke, presentation E2E, 3D browser, walkthrough quality, and map-preview gates, and failed only on the explicit `scene_video_provider_runtime` gold blocker that remains external-state-bound.
- `curl -fsS http://127.0.0.1:8097/version` returned `release_commit_sha=8598c091fbc1376c61007398d95732783a3450cb` with deployment id `local-20260706T213230Z-8598c091fbc1`.
- Authenticated origin probe on `http://127.0.0.1:8097/app/research/26abb3749ce943c0?run_id=5aa064d3f2cd480782d0006e8314dd0d` with `Host: propertyquarry.com` returned no `Nearby distances`, no `data-research-selected-distances`, and no `Other homes`, which matches the saved run truth: that run carries no selected nearby filters.
- Authenticated origin probe on `http://127.0.0.1:8097/app/research/ee90d4d412e13d64?run_id=aaae9ddc9d4d476fb039784e51f51efb` with `Host: propertyquarry.com` still returned `Nearby distances`, `data-research-selected-distances`, `selected limit`, `Nearest supermarket`, and `Nearest playground`, proving the selected-distance rail remains live for runs that actually saved nearby filters.

The live run-scoped distance-filter correction on 2026-07-06 verified:

- Commit `7fd2aa34` is the current deployed runtime candidate for preserving run-selected nearby distance filters on research detail pages even when the run snapshot is marked stale relative to the user’s current onboarding brief.
- `python3 -m py_compile ea/app/api/routes/landing.py ea/app/api/routes/landing_property_research.py` passed.
- Focused regressions passed:
  - `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_selected_distance_rows_follow_selected_nearby_filters tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_selected_distance_rows_support_legacy_nearby_preference_flags tests/test_propertyquarry_workspace_redesign.py::test_property_enriched_candidate_facts_backfill_source_research_for_selected_distance_checks tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_replaces_other_homes_with_selected_distance_checks tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_uses_run_distance_filters_even_when_run_snapshot_is_stale tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_right_rail_stays_compact tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_workspace_routes_render_greenfield_surfaces --tb=short` returned `7 passed`.
- `PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E=1 EA_HOST_PORT=8097 make deploy` rebuilt the live `propertyquarry-api` image and restarted `propertyquarry-api` plus `propertyquarry-scheduler`; the wrapper stayed quiet after the healthy restarts and was interrupted, so the deployment was verified manually through readiness, version, and authenticated origin probes.
- `curl -fsS http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}` after the restart, and `/version` returned `release_commit_sha=7fd2aa346c8e37fb1fdefaff8ba32e6b16c7133a` with deployment id `local-20260706T201531Z-7fd2aa346c8e`.
- Authenticated origin probe on `http://127.0.0.1:8097/app/research/ee90d4d412e13d64?run_id=aaae9ddc9d4d476fb039784e51f51efb` with `Host: propertyquarry.com` returned `Nearby distances`, `data-research-selected-distances`, and run-scoped missing-distance rows such as `Nearest supermarket distance is not listed yet; selected limit 1000 m.` and `Nearest playground distance is not listed yet; selected limit 1000 m.`
- The earlier sparse route `http://127.0.0.1:8097/app/research/26abb3749ce943c0?run_id=5aa064d3f2cd480782d0006e8314dd0d` still truthfully renders no distance rail because that run snapshot carries no selected nearby filters and the candidate still exposes only coarse `1010 Wien` location evidence.

The live research-detail/sidebar correction on 2026-07-06 verified:

- Commit `43d14aa3` is the current deployed runtime candidate for replacing the research-detail sibling-home rail with nearby-distance checks and for forcing `Open property` back onto first-party `/app/research/...` packet URLs.
- `python3 -m py_compile ea/app/api/routes/landing.py ea/app/api/routes/landing_property_research.py` passed.
- Focused regressions passed:
  - `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_workspace_routes_render_greenfield_surfaces tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_selected_distance_rows_follow_selected_nearby_filters tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_replaces_other_homes_with_selected_distance_checks tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_right_rail_stays_compact --tb=short` returned `4 passed`.
  - `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_research_everyday_fit_rows_use_named_confirmed_distances tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_research_missing_rows_respect_confirmed_distance_aliases tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_research_missing_rows_use_concrete_open_check_copy tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_normalized_mismatch_reasons_use_confirmed_distance_details tests/test_property_research_packet_renders_cached_evidence_overlays tests/test_property_research_packet_snapshot_normalizes_route_payload --tb=short` returned `6 passed`.
- `PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E=1 EA_HOST_PORT=8097 make deploy` rebuilt the live `propertyquarry-api` image and restarted `propertyquarry-api` plus `propertyquarry-scheduler`; the wrapper stayed quiet after the healthy restarts and was interrupted, so the deployment was verified manually through container health and authenticated origin probes.
- `curl -fsS http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}` after the restart, and `/version` returned `release_commit_sha=43d14aa35f7258ed78dee6661277339aca767e3d` with deployment id `local-20260706T195708Z-43d14aa35f72`.
- Authenticated origin probe on `http://127.0.0.1:8097/app/research/26abb3749ce943c0?run_id=5aa064d3f2cd480782d0006e8314dd0d` with `Host: propertyquarry.com` returned no `Other homes` copy and no `data-research-ranking-list` marker.
- The same live run truthfully still renders no `Nearby distances` panel because its saved `property_search_preferences` contain no selected nearby filters and the candidate currently exposes only `1010 Wien` location data, not exact-address or `nearest_*` amenity facts.
- Authenticated origin probe on `http://127.0.0.1:8097/app/properties?run_id=5aa064d3f2cd480782d0006e8314dd0d` confirmed `Open property` links and `data-candidate-packet-url` values now point to first-party `/app/research/...` packet routes rather than `/app/handoffs/...`.

The local/live proof pass on 2026-07-03 verified:

- Commit `9bb14a8c` is the current runtime candidate for the search-history score cleanup. It replaces previous-search `best <score>` and `top fit <score>` chips with a non-numeric `top match` label on search/history and agent surfaces.
- Search-history copy regressions passed: `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py::test_property_workspace_setup_is_dashboard_first_and_compact` returned `1 passed`, and `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_design_system_gate.py::test_propertyquarry_public_copy_avoids_proof_heavy_language` returned `1 passed`.
- Commit `dbdf284a` is the current runtime candidate for the research-sidebar score cleanup. It removes the raw `Score {{ row.get('score') }}` subtitle from `More from this search` and keeps only source plus optional fit summary.
- Research-sidebar copy regressions passed: `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py::test_property_research_detail_right_rail_stays_compact tests/test_propertyquarry_design_system_gate.py::test_propertyquarry_public_copy_avoids_proof_heavy_language` returned `2 passed`.
- Commit `6318a3bd` is the current runtime candidate for the area-layer popup copy pass. It replaces the user-visible `Only ready layers are shown.` wording with `Showing available layers.` and adds `ready layers` to the premium public-copy forbidden phrase gate.
- Area-layer copy regressions passed: `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py::test_property_workbench_evidence_atlas_avoids_internal_storage_language tests/test_propertyquarry_design_system_gate.py::test_propertyquarry_public_copy_avoids_proof_heavy_language` returned `2 passed`.
- Commit `9965ff85` is the current runtime candidate for the registration/auth copy pass. It removes bare full magic-link URLs from the fallback registration note, replaces visible `magic link` / `verification mail` wording with `secure verification link` / `verification email`, and adds a registration-template copy contract.
- Registration regressions passed: `PYTHONPATH=ea python3 -m pytest -q tests/test_registration_contracts.py` returned `60 passed`.
- Commit `4b50da55` is the current runtime candidate for the public-tour cleanup pass. It removes the customer-facing cube-fallback interstitial from the tour renderer, makes direct pure-cube renderer calls fail closed with `tour_disabled_fallback`, and returns neutral unavailable copy for removed cube assets.
- Focused public-tour regressions passed: `PYTHONPATH=ea python3 -m pytest -q tests/test_product_api_contracts.py::test_public_tour_customer_code_has_no_cube_fallback_interstitial_copy tests/test_product_api_contracts.py::test_public_tour_landing_blocks_cube_payload_even_when_pano2vr_entry_exists tests/test_product_api_contracts.py::test_public_tour_page_blocks_photo_gallery_fallback_bundle tests/test_product_api_contracts.py::test_public_tour_control_rejects_removed_cube_viewer tests/test_product_api_contracts.py::test_hosted_property_tour_verified_open_url_rejects_gallery_and_cube_fallbacks tests/test_providers_api_contracts.py::test_public_tour_routes_render_pure_360_cube_with_continuing_links tests/test_providers_api_contracts.py::test_public_tour_removed_cube_file_gate_respects_privacy_mode` returned `7 passed`.
- Commit `1030bcf8` is the current runtime candidate for the refreshed flagship-gate pass, including deploy-side provider-matrix receipt preservation, token-redacted billing handoff smoke receipts, explicit billing readiness-path reporting (`ready_via=member_login_token` when the signed member-token handoff is what passed), optional/hidden Pano2VR release-gate wording, generated-cube-fallback rejection in tour import instructions, and canonical live-container tour-control receipt selection.
- `python3 -m pytest -q tests/test_propertyquarry_gold_status.py tests/test_property_live_authenticated_smoke.py` returned `87 passed`.
- The refreshed gold-status receipt now distinguishes the direct account URL from the signed account handoff: direct `/account` can remain `direct_account_handoff_usable=false` while the signed lane must prove `signed_handoff_usable=true`, `ready_via=member_login_token` or `ready_via=sso_bridge`, and live smoke checks for external handoff plus no second login.
- `python3 -m pytest -q tests/test_property_tour_export_manifest.py tests/test_propertyquarry_gold_status.py` returned `73 passed`.
- `docker exec propertyquarry-api python /app/scripts/verify_property_tour_controls.py --tour-root /data/public_property_tours --live-probe --base-url http://127.0.0.1:8090 --host-header propertyquarry.com --require-all-provider-modes --write /data/artifacts/property-tour-controls-live-container-current.json --summary-only --fail-on-blocked` returned `status=pass`, required modes `matterport`, `3dvista`, `krpano`, and `magicfit`, optional mode `pano2vr`, and no missing provider modes.
- `python3 scripts/propertyquarry_gold_status.py --write _completion/propertyquarry/gold-status-current.json` returned `status=pass`, `blockers=[]`, and selected `_completion/tours/property-tour-controls-live-container-current.json` as the tour-control receipt.
- `PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1 PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 python3 scripts/property_live_provider_smoke.py --base-url http://127.0.0.1:8097 --country AT --country DE --country CR --execute-search-matrix --search-run-timeout-seconds 30 --write _completion/provider_smoke/production-e2e-provider-matrix-current.refreshing.json` returned `status=pass`, `targeted_search_matrix_status=pass`, `targeted_search_matrix_count=160`, `passed_case_count=160`, `failed_case_count=0`, `strict_case_count=80`, `soft_filter_case_count=80`, `dispatch_acceptance_complete=true`, `status_readback_complete=true`, and `cross_country_sanitization_summary.status_counts={"pass":3}`.
- The fresh provider matrix was promoted to `_completion/provider_smoke/production-e2e-provider-matrix-current.json` and `_completion/smoke/property-live-provider-latest.json`.
- `python3 scripts/propertyquarry_live_mobile_surface_smoke.py --base-url http://127.0.0.1:8097 --host-header propertyquarry.com --seed-research-detail-fixture --require-research-detail --write _completion/smoke/property-live-mobile-current.json` returned `status=pass`, `failed_count=0`, and verified the seeded research-detail visual controls, mobile What Matters behavior, district-map modal controls, and account logout sheet.
- `python3 scripts/propertyquarry_map_preview_flagship_gate.py --base-url http://127.0.0.1:8097 --host-header propertyquarry.com --write _completion/smoke/property-live-map-preview-flagship-current.json` returned `status=pass` with a visible map backdrop and controlled selected-area overlay.
- `python3 scripts/propertyquarry_3d_browser_gate.py --base-url http://127.0.0.1:8097 --host-header propertyquarry.com --write _completion/smoke/property-live-3d-browser-gate-current.json` returned `status=pass` for Matterport and 3DVista browser-rendered controls.
- `python3 scripts/propertyquarry_live_presentation_e2e.py --base-url http://127.0.0.1:8097 --host-header propertyquarry.com --write _completion/smoke/property-live-presentation-e2e-current.json` returned `status=pass`, including hero example links, direct Matterport open, 3DVista control, walkthrough video, and research-detail request controls.
- `python3 scripts/propertyquarry_walkthrough_quality_gate.py --tour-root state/public_property_tours --write _completion/smoke/property-live-walkthrough-quality-current.json` returned `status=pass` for the generated walkthrough coverage/continuity gate.
- `python3 scripts/verify_brilliant_directories_provider.py` refreshed `_completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json`; the billing lane remains configured and ready, while account-login/SSO limitations are still reported explicitly instead of hidden.
- `python3 scripts/propertyquarry_gold_status.py --write _completion/propertyquarry/gold-status-current.json` now reports all refreshed product/provider/mobile/map/tour/walkthrough/billing/security receipts green and leaves only release hygiene before this manifest commit.
- Focused local regressions passed for OneMinute-first provider ordering, LTD inventory safety, provider-matrix/gold-status aggregation, live mobile smoke contracts, tour controls/export importers, public tour controls, generated reconstruction, runtime reconstruction, and walkthrough scene-video gates.

The live polish pass on 2026-07-01 verified:

- Commit `3fd23daa` is the current deployed runtime candidate for the latest minimal-copy pass.
- `make deploy` rebuilt the live `propertyquarry-api` image and restarted `propertyquarry-api` plus `propertyquarry-scheduler`; the wrapper was interrupted after scheduler start because the compose process was quiet, so the deployment was verified manually through container health and smoke rather than by a zero-exit deploy wrapper.
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}` after the restart.
- `PYTHONPATH=ea .venv/bin/python -m pytest tests/test_propertyquarry_design_system_gate.py tests/test_propertyquarry_workspace_redesign.py::test_property_packets_dashboard_uses_customer_facing_language tests/test_propertyquarry_workspace_redesign.py::test_property_decision_save_uses_canonical_endpoint_and_renders_consequences tests/e2e/test_propertyquarry_feedback_browser.py tests/e2e/test_propertyquarry_packet_engagement_browser.py::test_packet_dashboard_renders_share_and_followup_state tests/e2e/test_propertyquarry_commercial_optimization_browser.py::test_workspace_and_packet_dashboard_show_commercial_and_page_idea_language tests/e2e/test_propertyquarry_packet_publishing_browser.py::test_packet_dashboard_shows_variant_and_republish_controls tests/test_fliplink_webhook_contracts.py -q` returned `28 passed`.
- `rg` over production templates/API/exit-gate docs found no remaining visible hits for the removed labels: `Analytics:`, `Engagement:`, `Next best action`, `Share state:`, `Reviewed feedback`, `Optimization recommendations`, `Saved durably`, `No risk summary captured yet`, `Current answer`, `Household reactions`, `Watch-outs`, `Record analytics`, or `Sharing status:`.
- `PYTHONPATH=ea .venv/bin/python scripts/propertyquarry_live_public_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-public-post-minimal-proof-copy-3fd23daa.json` returned `status=pass`, `failed_count=0`, and `route_count=22`.

- Commit `49db36e6` was the previous deployed runtime candidate for the first 2026-07-01 proof-copy pass.
- `make deploy` completed successfully and rebuilt the live `propertyquarry-api` / `propertyquarry-scheduler` stack on `http://localhost:8097`.
- The default ranking/score guide block was removed from first-party result surfaces.
- Duplicate score explanation panels were removed from selected-property desktop and mobile detail surfaces.
- Public tour summaries, premium dossiers, and PDF fallback labels now use calmer copy such as `Quick take`, `Best points`, and `Fit read` instead of proof-heavy ranking language.
- Focused proof-copy gates passed: `tests/test_propertyquarry_design_system_gate.py::test_propertyquarry_public_copy_avoids_proof_heavy_language`, `tests/test_propertyquarry_workspace_redesign.py::test_property_shortlist_results_stay_minimal_in_template_and_rehydration_bundle`, `tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_customer_surfaces_avoid_operator_jargon`, and `tests/test_propertyquarry_workspace_redesign.py::test_property_current_best_omits_unknown_fact_placeholders`.
- Broader public copy and live canary gates passed with `49 passed` across `tests/test_propertyquarry_design_system_gate.py`, `tests/test_browser_surface_contracts.py`, `tests/test_property_live_public_smoke.py`, and `tests/test_property_live_run_status_canary.py`.
- The post-deploy public smoke receipt `_completion/smoke/property-live-public-post-minimal-proof-copy.json` reports `status=pass`, `failed_count=0`, and `route_count=22`.

The local audit pass on 2026-07-01 verified:

- Commit `9cd1a87b` is the current runtime candidate for this repo audit.
- The premium UI exit gate is now defined in `docs/PROPERTYQUARRY_PREMIUM_UI_EXIT_GATE.md` and enforced by `tests/test_propertyquarry_premium_ui_exit_gate.py`.
- The design-system gate links to the premium gate so visual quality, mobile ergonomics, loading behavior, interaction clarity, copy restraint, dark-mode contrast, and proof-language removal are checked as one release boundary.
- `PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py --write _completion/smoke/property-auth-performance-latest.json` returned `status=pass`, `failed_count=0`, and `route_count=15`.
- Focused local regressions passed for authenticated performance smoke, Brilliant Directories integration, design-system quality, premium UI quality, deploy-operator contracts, gold-status aggregation, release security posture, Python compilation, and whitespace hygiene.
- Tour export discovery, tour provider ownership, and PropertyQuarry security-posture receipts were refreshed for the current candidate.
- The base PropertyQuarry compose posture no longer grants the API or scheduler root execution, `SYS_NICE`, or nice-level runtime priority overrides.
- The request-serving `ea/Dockerfile.property-web` image now installs only `ca-certificates` and `curl`; native media/render packages remain out of the web image and are guarded by deploy-contract and security-posture checks.
- The web framework runtime is pinned to the verified FastAPI/Pydantic/Starlette versions after the newer lock combination stalled `app.main` import during container startup.

The local audit pass on 2026-06-29 verified:

- Commit `9c49c40e` is the current runtime candidate for this repo audit.
- Search-area map previews now render the selected district polygon plus the saved adjacent-area radius in the red coverage overlay, so thumbnails no longer understate briefs that allow matches outside district borders.
- `/app/properties` now keeps the canonical run ranking uncapped while bounding first-paint result cards and stripping heavy candidate arrays from the properties-surface serialized run summary.
- Focused radius regressions passed in `tests/test_propertyquarry_workspace_redesign.py`; broader scope-preview and saved-search-agent regressions passed locally.
- Paintit.ai provider-account metadata is synced into the private PropertyQuarry Teable base with secret env-key references only; the raw password remains in the untracked local secret layer.
- `python3 scripts/propertyquarry_authenticated_performance_smoke.py --write _completion/smoke/property-auth-performance-latest.json` returned `status=pass`, `failed_count=0`, and verified warmed `/app/search`, `/app/properties`, `/app/account`, `/app/billing`, and settings surfaces under the 1200 ms route budget.
- `python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json --fail-on-blocked` now leaves only release hygiene before the manifest update; all product, mobile, analytics privacy, tour delivery, map preview, walkthrough, provider matrix, self-healing, scope, security, BTS methodology, and furniture-style contract gates are green.
- Focused local regressions passed for Brilliant Directories handoff cleanup, scene-video provider account merging, Chummer scene-video delivery routing, public tour CSP/Matterport/3DVista contracts, ranked search visibility, deploy-smoke principal resolution from `.env`, furniture-style gate alignment, and PropertyQuarry gold status aggregation.

The live rollout on 2026-06-28 verified:

- `make deploy` completed successfully and rebuilt the live `propertyquarry-api` / `propertyquarry-scheduler` stack on `http://localhost:8097`.
- Commit `b4e894ab` is the currently deployed branch/deployment candidate; the live runtime behavior remains the research-detail hero polish and first-party Brilliant Directories handoff scrub introduced in `7837fa61`, and this redeploy reconciled the branch with the authoritative release manifest.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url https://propertyquarry.com --write _completion/smoke/property-live-public-release-after-7837fa61.json` returned `status=pass`, `failed_count=0`, and `route_count=20`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py --base-url https://propertyquarry.com --principal-id cf-email:person@example.test --expected-plan-label Agent --write _completion/smoke/property-live-authenticated-release-after-7837fa61.json` returned `status=pass`, `failed_count=0`, and `route_count=3`, with `/app/billing` resolving through `https://billing.propertyquarry.com/sso/propertyquarry?...` and `billing_external_handoff_usable=true`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_mobile_surface_smoke.py --base-url https://propertyquarry.com --host-header propertyquarry.com --principal-id cf-email:person@example.test --seed-research-detail-fixture --require-research-detail --write _completion/smoke/property-live-mobile-release-after-7837fa61.json` returned `status=pass`, `failed_count=0`, `route_count=16`, and `covered_surface_count=18`, including the seeded live research-detail route `/app/research/perf-candidate-1020?run_id=run-gold-mobile`.
- `https://billing.propertyquarry.com/join` still redirects with `HTTP/2 302` to `https://propertyquarry.com/pricing`, and direct live checks against `https://billing.propertyquarry.com/login` plus `https://billing.propertyquarry.com/account` no longer return public score-filter language such as `Score ceiling`, `Per provider`, `All ranked`, `35/100`, `45/100`, `60/100`, or `score gate`.
- Focused regressions for ranked-home visibility and empty-state ranking-bar recovery passed locally: `tests/test_propertyquarry_workspace_redesign.py::test_property_run_live_board_prefers_ranked_candidates_when_high_fit_total_is_zero`, `tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_ranked_results_render_even_when_high_fit_total_is_zero`, `tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_shortlist_panel_builds_cards_and_actions`, `tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_empty_state_promotes_ranking_bar_control`, and `tests/e2e/test_propertyquarry_greenfield_browser.py::test_propertyquarry_active_run_auto_polls_notifies_and_renders_empty_result_desk`.
- Focused regressions for the shared mobile account sheet and research-detail top-nav hooks passed locally: `tests/test_propertyquarry_workspace_redesign.py -k 'mobile_top_nav_uses_core_loop_instead_of_noisy_tab_strip or research_detail_mobile_nav_uses_shared_mobile_nav_hook'` and `tests/test_property_live_mobile_surface_smoke.py -k 'requires_compact_account_menu_sheet or requires_real_research_detail_layout'`.
- Focused regressions for the new research-detail hero composition and first-party Brilliant Directories handoff scrub passed locally: `PYTHONPATH=ea python3 -m pytest tests/test_propertyquarry_workspace_redesign.py -k 'research_detail_right_rail_stays_compact or research_detail_places_visual_console_under_media_stage or research_detail_uses_user_facing_visual_and_decision_copy or research_detail_collapses_secondary_mobile_sections or research_detail_decision_fits_one_screen_by_default'`, `PYTHONPATH=ea python3 -m pytest tests/e2e/test_propertyquarry_greenfield_browser.py -k 'shortlist_and_research_surfaces_do_not_bleed_text or propertyquarry_research_detail_is_mobile_optimized_and_visuals_are_opt_in'`, and `PYTHONPATH=ea python3 -m pytest -q tests/test_brilliant_directories_integration.py -k 'billing_handoff_worker or pricing_surface_probe_detects_stock_placeholder_copy or verification_receipt_surfaces_placeholder_pricing_next_action'`.
- `PYTHONPATH=ea .venv/bin/python scripts/propertyquarry_authenticated_performance_smoke.py --write _completion/smoke/property-auth-performance-release-gate.json` now reports `status=pass`, `failed_count=0`, and confirms the compact What Matters distance controls, customer-safe notifications copy, fail-closed `/app/billing`, and `Usage and activation` customer wording.
- The ranking bar now stays score-only across the customer surfaces: below-bar homes remain visible in ranked results, run-summary counts prefer real ranked candidates over `high_fit_total`, and empty-result recovery still exposes the ranking-bar control after a live run finishes with no hard-rule conflicts.

The live rollout on 2026-06-27 verified:

- `make deploy` completed successfully and rebuilt the live `propertyquarry-api` / `propertyquarry-scheduler` stack on `http://localhost:8097`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url https://propertyquarry.com --write _completion/smoke/property-live-public-20260627-postdeploy.json` returned `status=pass`, `failed_count=0`, and `route_count=22`.
- `_completion/smoke/property-live-authenticated-latest.json` reports `status=pass`, `failed_count=0`, and `route_count=3`.
- `_completion/smoke/property-live-mobile-surface-latest.json` reports `status=pass`, `failed_count=0`, `route_count=16`, and `covered_surface_count=18`.
- `_completion/smoke/property-live-market-scope-latest.json` reports `status=pass`, `failed_count=0`.
- `PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1 PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py --base-url http://localhost:8097 --all-search-ready-countries --execute-search-matrix --resume-from _completion/provider_smoke/production-e2e-provider-matrix-current.json --write _completion/provider_smoke/production-e2e-provider-matrix-20260627-postdeploy.json` returned `status=pass`, `targeted_search_matrix_status=pass`, `executed_case_count=140`, `failed_case_count=0`, `status_readback_ok_count=140`, and `cross_country_sanitization_summary.status_counts={"pass":3}`.
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py --write _completion/release_hygiene/property-release-hygiene-latest.json` now reports `status=pass`, `manifest_runtime_commit=ad4dd9372ae36543e1c36a8ed7a01092e2cc96c5`, and `head_commit=ad4dd9372ae36543e1c36a8ed7a01092e2cc96c5`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/latest.json` now reports `status=pass` and `blockers=[]` against the refreshed live receipts.
- `_completion/property_gold_status/telegram-notify-report.json` reports either an explicit notification send or `status="skipped"` when `PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED` is not set.
- `PYTHONPATH=ea python3 scripts/verify_brilliant_directories_provider.py` now keeps `billing_handoff.status=ready`, `host_resolves=true`, `account_handoff_usable=false`, and `account_handoff_error=billing_handoff_requires_separate_login` for `billing.propertyquarry.com`.

The live operator import and verifier hardening on 2026-06-26 verified:

- `PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py --base-url http://localhost:8097 --all-search-ready-countries --execute-search-matrix --resume-from _completion/provider_smoke/production-e2e-provider-matrix-current.json --write _completion/provider_smoke/production-e2e-provider-matrix-current.json` now reports `status=pass` on the narrowed customer-search scope `AT/DE/CR`, with `targeted_search_matrix_status=pass`, `executed_case_count=140`, `failed_case_count=0`, and `cross_country_sanitization_summary.status_counts={"pass":3}`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/propertyquarry-gold-status-current-manual.json` now writes a current aggregate receipt with `blockers=[]` after the billing handoff repair and current provider-matrix rerun.
- `python3 scripts/bootstrap_billing_handoff_worker.py` deployed the `propertyquarry-billing-handoff` Cloudflare Worker on route `billing.propertyquarry.com/*`, set the billing DNS record to proxied mode, and wrote `_completion/brilliant_directories/billing-edge-worker-current.json`.
- Historical edge proof on 2026-06-26 showed the first-party billing host returning `HTTP/2 302`; the later 2026-06-27 recheck superseded the earlier direct-to-account interpretation and now treats the separate login as the active state.
- `PYTHONPATH=ea python3 scripts/verify_brilliant_directories_provider.py` was refreshed by the 2026-06-27 live correction and no longer treats the external account lane as directly usable; the current receipt keeps `billing_handoff.status=ready`, `account_handoff_usable=false`, and `account_handoff_error=billing_handoff_requires_separate_login`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_mobile_surface_smoke.py --base-url http://localhost:8097 --seed-research-detail-fixture --require-research-detail --write _completion/smoke/property-live-mobile-registry-coverage-current.json` returned `status=pass`, `failed_count=0`, `route_count=16`, and `coverage_checks.registry_mobile_customer_surfaces_covered=true` with `covered_surface_count=18`.
- `_completion/property_gold_status/mobile-registry-coverage-current.json` reports `live_mobile_surfaces.status=pass`, `required_route_count=15`, `route_count=16`, no missing routes, no missing detail routes, no failed coverage checks, and the only current gold blocker remains `verified_tour_provider_modes=["3dvista"]`.
- The 3DVista private-viewer runtime is now present locally at `/home/tibor/.wine/drive_c/users/tibor/AppData/Roaming/tdv.show/Local Store/tdvplayer_dir/default`; `tdvplayer.json` reports runtime minor version `2347`.
- The PropertyQuarry tour bundle `luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557` now carries `three_d_vista_white_label_proof.private_viewer_verified=true`, `non_trial_export_verified=true`, and `trial_branding_present=false`.
- `scripts/verify_property_tour_controls.py` now treats trial-branded local 3DVista exports as not premium-ready even when real `tdvplayer` runtime markers are present.
- `scripts/discover_property_tour_exports.py` now rejects trial-branded 3DVista export folders with `3dvista_trial_branding_present` so operator tooling no longer reports them as verified exports.
- `curl -H 'Host: propertyquarry.com' http://127.0.0.1:8097/tours/luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557/control/3dvista` now returns `HTTP 200`; the live export entry no longer contains the trial marker or `www.3dvista.com`.
- `_completion/tours/property-tour-controls-private-viewer-current.json` now reports `status=pass`, `ready_provider_modes=["3dvista","krpano","magicfit","matterport","pano2vr"]`, and `missing_provider_modes=[]`.
- `_completion/tours/property-tour-vendor-tooling-current.json` now reports `status=pass`, `missing_verified_exports=[]`, `live_bundle_verified_export_ready_counts={"3dvista":1,"pano2vr":1}`, and `verified_export_ready_counts={"3dvista":1,"pano2vr":2}`.
- `_completion/propertyquarry-gold-status-current-manual.json` now reports `blockers=[]` after the live billing handoff repair, narrowed provider-matrix rerun, and private-viewer-backed 3DVista control refresh.
- `PYTHONPATH=. pytest -q tests/test_property_tour_export_importers.py -k '3dvista_importer_requires_verified_export_markers or 3dvista_trial_branded_export_is_not_premium_ready or discovery_rejects_trial_branded_3dvista_export or batch_tour_export_importer_materializes_verified_3dvista'` returned `4 passed`.
- `python3 -m py_compile scripts/discover_property_tour_exports.py scripts/verify_property_tour_controls.py scripts/verify_property_tour_vendor_tooling.py` passed.

- 3DVista VT Pro launched under Wine/Xvfb, created a new project, imported the prepared 360 panorama, and published a real Web/Mobile export into `state/wine-3dvista/drive_c/users/tibor/Desktop/propertyquarry-3dvista-export`.
- The generated 3DVista export contains `index.htm`, `lib/tdvplayer.js`, `lib/tdvplayer.json`, `script.js`, `script_general.js`, and generated WebP panorama tiles under `media/`.
- The generated 3DVista export was imported inside `propertyquarry-api` with `scripts/import_3dvista_export.py`, producing `/tours/luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557/control/3dvista`.
- Live HTTP smoke returned `200` for the 3DVista control route, `200` for `/tours/3dvista/.../3dvista/index.htm`, `200` for `/tours/3dvista/.../3dvista/lib/tdvplayer.js`, and `200` for `/tours/3dvista/.../3dvista/script.js`.
- Historical caveat: the generated 3DVista `index.htm` contains 3DVista trial branding. That still proves a real generated export, but it is no longer accepted as premium/gold evidence.

- Pano2VR 8 Pro was installed under Wine, accepted the local registered license, loaded the prepared 360 panorama, saved a `.p2vr` project, and generated a real Web output containing `index.html`, `pano.xml`, `pano2vr_player.js`, and `gginfo.json`.
- The generated Pano2VR export was imported into the live public tour volume for `luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557` with `scripts/import_pano2vr_export.py`, producing `/tours/luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557/control/pano2vr`.
- Live HTTP smoke returned `200` for the Pano2VR control route, `200` for `/tours/pano2vr/.../pano2vr/index.html`, `200` for `/tours/pano2vr/.../pano2vr/pano.xml`, and `200` for `/tours/pano2vr/.../pano2vr/pano2vr_player.js`.
- `docker exec propertyquarry-api python /app/scripts/verify_property_tour_controls.py --tour-root /data/public_property_tours` wrote `_completion/tours/property-tour-controls-after-pano2vr-import-current.json` and reported `provider_counts.pano2vr=1`, ready modes `krpano`, `magicfit`, `matterport`, and `pano2vr`, and missing provider modes narrowed to only `3dvista`.
- Focused route/import/verifier tests returned `4 passed` for Pano2VR route contracts and `54 passed` for tour control verifier, export importer, and vendor tooling contracts.
- Current aggregate gold receipts are clear, but the whole-project premium/gold objective still requires broader presentation-grade review and deploy authority beyond these receipt-only gates.

## Cross-Project 3DVista Pattern Learned From Chummer RunSite

Chummer RunSite/Horizon work should be treated as a reusable tour-delivery pattern, not as direct PropertyQuarry proof. The relevant Chummer receipt currently records `status=blocked` for 3DVista delivery because no authenticated 3DVista account upload automation, hosted-tour API binding, or local 3DVista project export is configured in that workspace. Its useful pattern is the contract shape:

- `ready_payload`: public-safe caption, generated media path, poster path, source viewer URL, and manifest URL.
- `blocked_reason`: one concise operator-facing reason when the tour cannot be promoted.
- `required_to_send`: authenticated 3DVista session, hosted-tour/project upload target, and the chosen delivery role.

PropertyQuarry should mirror that discipline for 3DVista and Matterport/krpano/Pano2VR/MagicFit integrations:

- Do not promote provider sample viewers, Chummer demo tours, trial-branded exports, or marketing fly-throughs as PropertyQuarry-ready tours.
- Accept only a playable PropertyQuarry-specific hosted 3DVista URL, private-viewer bundle, or self-hosted VT Pro export that passes the existing non-trial export verifier.
- Keep source-of-truth separation explicit: the tour viewer presents visual walkthrough assets; PropertyQuarry owns listing facts, ranking, evidence, pricing, entitlement, and customer decisions.
- Reuse Chummer's receipt vocabulary for future private-viewer arrival: `ready_payload`, `blocked_reason`, `required_to_send`, and public-safe manifest URLs.

The candidate at `a60f0e6f` passed:

- `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_search_route_renders_what_matters_as_comboboxes tests/test_product_api_contracts.py::test_property_search_preferences_enable_new_research_and_source_flags tests/test_product_api_contracts.py::test_property_official_risk_evidence_for_austria_includes_school_noise_and_broadband tests/test_product_api_contracts.py::test_property_austria_preference_adjustment_scores_heat_resilience tests/test_property_score_methodology.py tests/test_fliplink_webhook_contracts.py::test_score_methodology_pdf_endpoint_uses_requested_language tests/test_property_market_catalog.py::test_austria_official_sources_are_evidence_not_listing_providers` returned `12 passed`.
- `python3 -m py_compile ea/app/api/routes/landing_view_models.py ea/app/product/property_location_research.py ea/app/product/property_score_methodology.py ea/app/product/service.py ea/app/services/property_market_catalog.py ea/app/services/fliplink/pdf_renderer.py`
- `git diff --check`
- What Matters now includes `Bleibt im Sommer kühl` / `Stays cool in summer` under the customer-facing `Check before deciding` group with multilingual helper metadata and an explicit `?` helper tooltip.
- The heat-resilience preference normalizes to `prefer_heat_resilient_home` and affects ranking through Austria scoring: penalties for Dachgeschoss/top floor, large south-facing windows, inner-city heat-island heuristic, and official/extracted heat risk; bonuses for cooling, Altbau/thick-wall signal, external shading, tree/courtyard shade, and attached official climate evidence.
- Official evidence lanes now include Vienna `Klimaanalysekarte` heat evidence, data.gv.at-backed Breitbandatlas, air quality, noise, traffic, green shade, schools, childcare through existing controls, and flood/water context without inventing duplicate user-facing filters.
- The BTS score PDF now explains where information comes from and no longer awards points merely for being in the selected district; selected district remains an eligibility/location-verification rule with `+0` example delta.

The candidate at `67875b37` passed:

- `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_search_route_does_not_use_generic_workspace_search tests/test_product_api_contracts.py::test_property_tour_followup_tasks_auto_process_user_visual_requests tests/test_product_api_contracts.py::test_request_property_visual_asset_keeps_explicit_workbench_floorplan` returned `3 passed`.
- `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_account_does_not_embed_full_raw_preference_payload tests/test_product_api_contracts.py::test_property_tour_followup_tasks_auto_process_user_visual_requests tests/test_product_api_contracts.py::test_request_property_visual_asset_keeps_explicit_workbench_floorplan tests/test_product_api_contracts.py::test_request_property_visual_asset_rejects_workbench_floorplan_default` returned `4 passed`.
- `pytest -q tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_search_route_does_not_use_generic_workspace_search tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_search_route_renders_what_matters_as_comboboxes tests/test_propertyquarry_workspace_redesign.py::test_propertyquarry_search_route_skips_first_paint_side_effects` returned `3 passed`.
- `python3 -m py_compile ea/app/api/routes/landing_view_models.py ea/app/api/routes/product_api_contracts.py ea/app/api/routes/product_api_delivery.py ea/app/product/service.py`
- `git diff --check`
- Furniture-style preferences now expose five render-style choices with examples: Warm Scandinavian, IKEA practical, Urban jungle, Landhaus, and Trump gold.
- Furniture-style gold gating now verifies the five visible style choices, free/plus/agent style caps of 1/3/5, visible example swatches, UI handoff into visual requests, and style-aware MagicFit scene cache reuse so one style cannot incorrectly satisfy another.
- Compact account, agents, alerts, and billing surfaces now render the static mobile-switch suppression selectors and account logout touch-target CSS in the compact stylesheet used by those routes; the authenticated performance smoke returned `status=pass`, `failed_count=0`, and `route_count=15` after the repair.
- Plan limits are explicit: Free can preference one generated style, Plus three, Agent five. Already-rendered style assets remain viewer-accessible independent of plan.
- Visual requests and queued property-tour follow-up tasks preserve `diorama_style_hint`, so generated tours and walkthroughs use the selected style instead of dropping back to the generic prompt.

The candidate at `1c7352b8` passed:

- `PYTHONPATH=ea pytest -q tests/test_extract_3dvista_desktop_app.py tests/test_property_tour_vendor_tooling.py --tb=short` returned `8 passed`.
- `PYTHONPATH=ea python3 scripts/extract_3dvista_desktop_app.py --write _completion/tours/3dvista-desktop-app-current.json --fail-on-missing` returned `status=ready`.
- The 3DVista desktop app receipt proves the official extracted app at `state/vendor_apps/3dvista`, AIR version label `2026.0.3`, and helper CLIs `tdvtools_v2`, `three_d_tools`, `tdv_server`, `zip_sign`, and `file_picker_cli`.
- The same receipt deliberately records `headless_publish_cli_ready=false` and `verified_export_required=true`; 3DVista desktop readiness is not accepted as verified hosted-tour evidence.
- Current gold status remains `blocked` because verified 3DVista/Pano2VR export/control evidence is still missing.

The candidate at `b7d8b44` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_tool_execution.py -k 'teable_table_sync or request_json_uses_browser_style_headers'` returned `3 passed, 116 deselected`.
- `python3 -m py_compile ea/app/services/tool_execution_teable_adapter.py`
- `git diff --check`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- Live authenticated `POST /app/api/property/teable-sync?limit=5` as `cf-email:person@example.test` returned `status=ready`, `sync_attempted=true`, `sync_result=sent`, `target_ref=teable-sync:propertyquarry:propertyquarry`, `table_count=18`, `created_count=6`, and `updated_count=7`.
- The Teable adapter now compacts oversized string/JSON fields before writes, preventing one large preferences row from blocking delivery settings and other PropertyQuarry projections.
- Operator's WhatsApp notification preference is stored in Postgres and was directly upserted to the configured PropertyQuarry Teable `propertyquarry_delivery_settings` table with last4 `0000`; WhatsApp send remains blocked because the live WhatsApp Web session reports `qr_required`.
- PropertyQuarry duplicate records were removed from the EA Teable WhatsApp/persona tables after backup receipts; shared EA tables were preserved because they contain non-PropertyQuarry data.
- Teable base reconciliation remains open: the local app env contains writable configured PropertyQuarry table IDs, but Teable API base enumeration returned no visible bases and did not prove those tables are in the user-visible `propertyquarry.com` base that currently shows only `runners`.
- Current gold status remains `blocked` because verified 3DVista/Pano2VR export/control evidence is still missing, the Brilliant Directories handoff still needs final local/BD-side verification, and Teable base authority must be reconciled to the visible `propertyquarry.com` base.

The candidate at `ec9cbdd` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'listing_fact_confirmation or everyday_fit_rows or route_previews_require_values or browser_route_preview_uses_confirmed_distance or missing_rows_respect_confirmed_distance'` returned `7 passed, 392 deselected`.
- `python3 -m py_compile ea/app/api/routes/landing_property_workspace_helpers.py`
- `git diff --check`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-public-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=22`.
- `PYTHONPATH=ea EA_API_TOKEN=[redacted] python3 scripts/propertyquarry_live_mobile_surface_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-mobile-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=14`.
- Route previews now suppress invalid/unknown/no-value distance warnings and label unnamed positive-distance evidence as `Nearest confirmed <label>` instead of vague labels such as `Supermarket`.
- Cloudflare DNS now has `billing.propertyquarry.com` as a DNS-only `CNAME` to `members.brilliantdirectories.com` with TTL `300`; public resolvers returned the CNAME immediately, while the local system resolver had not propagated at verification time.
- Current gold status remains `blocked` because verified 3DVista/Pano2VR export/control evidence is still missing, and the Brilliant Directories billing handoff still needs local resolver/BD-side custom-domain/SSL verification before `/app/billing` can redirect externally.

The candidate at `ae0750a` passed:

- `python3 -m py_compile scripts/discover_property_tour_exports.py scripts/import_property_tour_exports.py scripts/import_3dvista_export.py scripts/import_pano2vr_export.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_importers.py`
- `PYTHONPATH=ea python3 scripts/discover_property_tour_exports.py --drop-dir state/incoming_property_tours --public-tour-dir /var/lib/docker/volumes/property_propertyquarry_public_tours/_data --write _completion/property_tour_exports/release-gate-discovery.json --manifest-write _completion/property_tour_exports/release-gate-import-manifest.json`
- Tour export discovery now accepts vendor-labelled export folders such as `3DVista VT Pro Export` and `Pano2VR 8 Pro Output`, while still requiring real provider runtime markers before a row becomes importable.
- The current incoming drop still reports `status=blocked_no_verified_exports`, `import_count=0`, and `rejected_count=7`; the existing placeholders contain no verified 3DVista/Pano2VR exports.
- No app runtime redeploy was required for this candidate because the change is release/import tooling only.
- Current gold status remains `blocked` because verified 3DVista/Pano2VR export/control evidence and `billing.propertyquarry.com` DNS are still missing.

The candidate at `35736fa` passed:

- `python3 -m py_compile scripts/verify_property_tour_provider_ownership.py scripts/propertyquarry_gold_status.py ea/app/api/routes/landing.py`
- `bash -n scripts/property_release_gates.sh`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_provider_ownership.py tests/test_propertyquarry_gold_status.py tests/test_property_deploy_operator_contracts.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'register_surface_uses_property_search_language'`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- A live session-cookie pricing smoke against `http://127.0.0.1:8097/pricing` returned `status=200`, no `Start free`, no `Create account`, no `/register`, and confirmed `Open search`, `Open billing`, and `Your account is already active.` for an active `ea_workspace_session`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-public-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=22`.
- The pricing page now treats a resolved PropertyQuarry principal as an active account session: logged-in users see `Open search` and billing/account-lane CTAs instead of `/register` or `Create account`.
- The tour ownership gate now writes `_completion/property_tour_ownership/release-gate.json` from local ignored environment configuration and receipt metadata without printing or tracking secrets. This proves 3DVista/Pano2VR ownership/config presence only; it is not export/playback evidence.
- A broader `tests/test_propertyquarry_workspace_redesign.py` run still has unrelated residual failures for stale trust/research/workbench copy expectations and Brilliant Directories DNS-gated billing redirects; those remain outside this pricing/ownership patch.
- Current gold status remains `blocked` because ownership proof does not replace the required verified 3DVista/Pano2VR export/control evidence and `billing.propertyquarry.com` DNS remains unresolved.

The candidate at `0e3c364` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_ltd_critical_entries_gate.py tests/test_ltd_flagship_subset_gate.py tests/test_ltd_inventory_markdown.py`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Pano2VR ownership is now receipt-verified in `LTDs.md` from Garden Gnome order `#38984` dated 2026-06-24 for Product `pano2vr-8x-pro`, ID `nferpd44`, paid by PayPal for EUR 598.80 including VAT.
- The normalized local `.env` Pano2VR license key was checked against the receipt without printing it; tracked files intentionally store only receipt metadata, not the key.
- 3DVista ownership is now receipt-verified in `LTDs.md` from 2026-06-10 order emails for `3DVista VT Pro` and `Branded Pack`; invoice IDs `60076` and `60074` are recorded without storing passwords, reset tokens, invoice signatures, or private invoice links in tracked files.
- The local ignored `.env` contains 3DVista control-panel credentials for later login/export verification; tracked files intentionally store only receipt metadata.
- Current gold status remains `blocked` because ownership proof does not replace the required verified 3DVista/Pano2VR export/control evidence. The remaining blockers are still missing verified `3dvista` and `pano2vr` tour evidence/export drops and unresolved `billing.propertyquarry.com` DNS.
- No app runtime redeploy was required for this candidate because the change was non-secret LTD receipt metadata.

The candidate at `43b7808` passed:

- `bash -n scripts/property_release_gates.sh`
- `python3 scripts/propertyquarry_live_public_smoke.py -h`
- `python3 scripts/propertyquarry_live_authenticated_smoke.py -h`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_deploy_operator_contracts.py tests/test_property_live_public_smoke.py tests/test_property_live_authenticated_smoke.py`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py`
- `python3 -m py_compile scripts/propertyquarry_gold_status.py`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-public-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=22`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py --base-url http://localhost:8097 --write _completion/smoke/property-live-authenticated-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=3`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py --write _completion/smoke/property-auth-performance-release-gate.json` returned `status=pass`, `failed_count=0`, and `route_count=15`.
- `PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py --base-url http://localhost:8097 --all-search-ready-countries --execute-search-matrix --resume-from _completion/provider_smoke/release-gate-provider-matrix.json --write _completion/provider_smoke/release-gate-provider-matrix.json` returned `status=pass`, `targeted_search_matrix_count=242`, and `cross_country_sanitization_summary.case_count=17`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --performance-receipt _completion/smoke/property-auth-performance-release-gate.json --tour-control-receipt _completion/property_tour_controls/release-gate.json --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json --public-smoke-receipt _completion/smoke/property-live-public-release-gate.json --authenticated-smoke-receipt _completion/smoke/property-live-authenticated-release-gate.json --write _completion/property_gold_status/release-gate.json`
- The current gold receipt reports pass areas `performance`, `analytics_privacy`, `live_mobile_surfaces`, `public_auth_surfaces`, `authenticated_customer_surfaces`, `provider_targeted_search_matrix`, `self_healing`, and `receipt_freshness`.
- Current gold status remains `blocked` only for missing verified `3dvista` and `pano2vr` tour evidence/export drops and unresolved `billing.propertyquarry.com` DNS.
- No app runtime redeploy was required for this candidate because the changes were release-gate receipt wiring and gold-status reporting.

The candidate at `7a5795c` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_importers.py -k 'zip or discovery_accepts_verified_provider_zips or batch_tour_export_importer_materializes_verified_3dvista'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_manifest.py -k 'prepares_drop_dir_readmes'`
- `python3 -m py_compile scripts/import_3dvista_export.py scripts/import_pano2vr_export.py scripts/import_property_tour_exports.py scripts/discover_property_tour_exports.py scripts/materialize_property_tour_export_manifest.py`
- `PYTHONPATH=ea python3 scripts/discover_property_tour_exports.py --drop-dir state/incoming_property_tours --public-tour-dir /var/lib/docker/volumes/property_propertyquarry_public_tours/_data --write _completion/tours/property-tour-export-discovery-current.json --manifest-write _completion/tours/property-tour-export-import-discovered-current.json` returned `status=blocked_no_verified_exports`, `import_count=0`, and `rejected_count=7`, proving no real 3DVista/Pano2VR export is currently present.
- `PYTHONPATH=ea python3 scripts/materialize_property_tour_export_manifest.py --tour-root /var/lib/docker/volumes/property_propertyquarry_public_tours/_data --incoming-root state/incoming_property_tours --providers 3dvista,pano2vr --prepare-dirs --write _completion/property_tour_exports/import-manifest-current.json` returned `status=waiting_for_verified_assets`, `providers=['3dvista','pano2vr']`, and recorded permission errors for existing host-side drop READMEs instead of aborting.
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- Current gold status remains `blocked`; verified 3DVista and Pano2VR evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `740d58e` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_importers.py -k 'krpano_importer'`
- `python3 -m py_compile scripts/import_krpano_walkable_scene.py`
- `docker exec propertyquarry-api python /app/scripts/import_krpano_walkable_scene.py --slug 360-tour-balkon-wohnung-in-neustift-layout-first-44feb8a525 --from-existing-scene 0` returned `status=imported`, `provider=krpano`, `scene_strategy=walkable_cube`, and `asset_count=6`.
- `curl -H 'Host: propertyquarry.com' http://localhost:8097/tours/360-tour-balkon-wohnung-in-neustift-layout-first-44feb8a525/control/krpano` returned `HTTP 200`; the response contained `krpano Licensed Viewer`, `data-viewer="krpano"`, `krpano-license`, and the six local cube-face assets.
- `PYTHONPATH=ea python3 scripts/verify_property_tour_controls.py --tour-root /var/lib/docker/volumes/property_propertyquarry_public_tours/_data --require-all-provider-modes --write _completion/tours/property-tour-controls-live-container-current.json`
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json`
- The current tour-control receipt reports `ready_provider_modes=['krpano', 'magicfit', 'matterport']`, provider counts `krpano=1`, `magicfit=8`, `matterport=29`, and missing provider modes only `3dvista` and `pano2vr`.
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- Current gold status remains `blocked`; verified 3DVista and Pano2VR evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `55a2da3` passed:

- `bash -n scripts/deploy_propertyquarry.sh`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_deploy_operator_contracts.py -k 'deploy_wrapper_preflights'`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- The deploy-authenticated smoke preserved `_completion/smoke/property-live-authenticated-latest.json` with `status=pass`, `failed_count=0`, and `route_count=3`; `/app/account` returned `200`, `/app/billing` returned `303`, and `/sign-in` returned `200`.
- The deploy-provider smoke preserved `_completion/smoke/property-live-provider-latest.json`; catalog checks for `AT` and `CR` passed, and cross-country sanitization passed for both cases by removing `immoweb` from AT and `willhaben` from CR.
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `3daed35` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py -k 'cli_defaults or authenticated_billing_surface or billing_handoff'`
- `python3 -m py_compile scripts/propertyquarry_gold_status.py`
- `bash -n scripts/deploy_propertyquarry.sh`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py tests/test_property_live_authenticated_smoke.py -k 'authenticated_billing_surface or billing_handoff or live_authenticated_smoke'`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py --base-url http://localhost:8097 --principal-id "$EA_PRINCIPAL_ID" --expected-plan-label "$PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL" --country-code "$PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE" --timeout-seconds 20 > _completion/smoke/property-live-authenticated-latest.json` returned `status=pass`, `failed_count=0`, and `route_count=3`.
- The authenticated smoke receipt proves `/app/account` returned `200`, `/app/billing` returned `303`, and `/sign-in` returned `200`; the `/app/billing` row proves `billing_external_handoff`, `billing_local_board_deleted`, and `billing_no_customer_noise`.
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json`
- The gold receipt now includes `authenticated_customer_surfaces` from `_completion/smoke/property-live-authenticated-latest.json`; current values are `status=pass`, `failed_count=0`, `route_count=3`, `billing_checks_ok=true`, `billing_status_code=303`, and no missing or failed billing checks.
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`.
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `d640b5b` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py`
- `python3 -m py_compile scripts/propertyquarry_gold_status.py`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097 --write _completion/smoke/property-live-public-latest.json`
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json`
- The gold receipt now includes `public_auth_surfaces` from `_completion/smoke/property-live-public-latest.json`; current values are `status=pass`, `failed_count=0`, `route_count=22`, `sign_in_checks_ok=true`, and no missing or failed sign-in checks.
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `b041caa` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_authenticated_smoke.py tests/test_property_live_public_smoke.py`
- `python3 -m py_compile scripts/propertyquarry_live_authenticated_smoke.py scripts/propertyquarry_live_public_smoke.py`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097 --write _completion/smoke/property-live-public-latest.json` returned `status=pass`, `failed_count=0`, and `route_count=22`; the `/sign-in` row now proves `sign_in_provider_creates_account`, `sign_in_no_unavailable_auth_copy`, provider button state, and provider opening feedback.
- Authenticated live smoke was not run in this shell because `EA_API_TOKEN` was not set; the authenticated smoke unit suite covers the same sign-in account-creation and unavailable-copy regressions.
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `8f4f149` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'provider_sign_in_errors_use_customer_safe_language or email_link_unavailable or public_get_started_and_sign_in'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- Live origin smoke for `/sign-in?link_error=workspace_sign_in_email_delivery_not_configured&link_status=failed` with `Host: propertyquarry.com` proved the page now says `Email link delivery needs setup.`, keeps `First-time provider sign-in still creates the account automatically.`, omits `Email sign-in links are temporarily unavailable.`, and does not leak `workspace_sign_in_email_delivery_not_configured`.
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `2cad5c6` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_control_verifier.py -k 'summary_omits_tour_rows or require_all_provider_modes or counts_provider_gaps or actionable_missing_evidence'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py -k 'missing_tour_action_excludes_already_verified_modes or magicfit_ready_lacks_playback_proof'`
- `python3 -m py_compile scripts/verify_property_tour_controls.py scripts/propertyquarry_gold_status.py`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- Live-container tour verification now includes compact `provider_blockers` reason counts without raw provider URLs: 3DVista has 153 missing exports and 23 placeholder fields, Pano2VR has 176 missing exports, and krpano has 175 missing walkable scenes plus 1 non-360/missing asset case.
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `9f1c76a` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_export_importers.py -k 'magicfit'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_tour_control_verifier.py -k 'magicfit'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py -k 'magicfit_ready_lacks_playback_proof or passes_only_when_all_required_evidence_is_present or missing_tour_action_excludes'`
- `PYTHONPATH=ea python3 scripts/verify_property_tour_controls.py --tour-root /var/lib/docker/volumes/property_propertyquarry_public_tours/_data --require-all-provider-modes --write _completion/tours/property-tour-controls-live-container-current.json`
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json`
- MagicFit playback is now an explicit gold-gate proof: every ready MagicFit control must have local playable video evidence or a live-probed allowlisted hosted video URL. The current live tour receipt reports `playback_ok: true`, `playable_count: 8`, and `ready_count: 8`.
- `make deploy`
- `curl -fsS http://localhost:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `dec00cf` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_gold_status.py -k 'provider_matrix or cross_country or resolving_url_only'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_live_provider_smoke.py -k 'cross_country or provider_country_scope'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_product_api_contracts.py -k 'cross_country_provider_mismatch or rejects_cross_country_provider_mismatch or realestate_au'`
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/release-gate.json`
- Gold status now requires explicit cross-country provider sanitization evidence before pass; the current provider matrix reports `cross_country_sanitization_ok: true` across 17 cases, so Austrian searches cannot silently dispatch `realestate_au` or other wrong-country providers.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `c8a7584` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_search_runs.py -k 'status_polling_retries_refresh_failures'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'current_best_omits_unknown_fact_placeholders or search_status_replaces_stale_status_refresh_noise or running_state_explains_slow_provider_checks'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- Search status retry copy now stays quiet and useful instead of showing `Status refresh` or `Could not load property search status.`; property feedback fallbacks no longer render `No detail yet.`.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `8b9109e` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'account_and_billing_templates_keep_controls_minimal or settings_hide_generic_google_sync_metrics or billing_surface'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_authenticated_performance_smoke.py -k 'receipt_passes or script_emits_receipt'`
- `PYTHONPATH=ea python3 scripts/check_property_surface_accessibility.py`
- Account now labels the plan CTA as `Billing account` and states that payment management opens in the external account lane; fallback billing-panel copy now says `Plan access` instead of local plan/payment/history language.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `30cfeea` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'billing_surface or static_surfaces_do_not_inline or active_workspace_nav_item or static_property_surfaces_skip_full_fleet_digest or account_surfaces_use_persisted_property_plan'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_authenticated_performance_smoke.py -k 'receipt_passes or script_emits_receipt'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_product_api_contracts.py -k 'property_billing_surface_is_not_local_payment_state'`
- Signed-in account/settings payload copy now avoids `Open pricing` and `Compare plans`; `/app/billing` contracts accept only an external Brilliant Directories handoff or a small fail-closed recovery page.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

The candidate at `daa98fe` passed:

- `PYTHONPATH=ea python3 -m pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'provider_sign_in_errors_use_customer_safe_language or public_get_started_and_sign_in'`
- `PYTHONPATH=ea python3 -m pytest -q tests/test_property_authenticated_performance_smoke.py -k 'receipt_passes or script_emits_receipt'`
- `python3 - <<'PY' ... PY` verified provider sign-in recovery copy no longer says Google/Facebook/ID Austria sign-in is temporarily unavailable and keeps automatic first account creation explicit.
- Provider sign-in error recovery now says the provider could not open on this attempt, offers retry or secure email link, and confirms first-time provider sign-in still creates the account automatically.
- `make deploy`
- `docker inspect --format='{{.State.Health.Status}}' propertyquarry-api` returned `healthy`
- `curl -fsS --max-time 5 http://127.0.0.1:8097/health/ready` returned `{"status":"ready","reason":"postgres_ready"}`
- `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py`
- Current gold status remains `blocked`; verified 3DVista, Pano2VR, and krpano tour evidence/export drops are still missing, and `billing.propertyquarry.com` still must resolve before the Brilliant Directories account lane can be proven live.

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
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --performance-receipt _completion/smoke/property-auth-performance-release-gate.json --tour-control-receipt _completion/property_tour_controls/release-gate.json --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json --public-smoke-receipt _completion/smoke/property-live-public-release-gate.json --authenticated-smoke-receipt _completion/smoke/property-live-authenticated-release-gate.json --write _completion/property_gold_status/release-gate.json`
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
- `PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --performance-receipt _completion/smoke/property-auth-performance-release-gate.json --tour-control-receipt _completion/property_tour_controls/release-gate.json --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json --public-smoke-receipt _completion/smoke/property-live-public-release-gate.json --authenticated-smoke-receipt _completion/smoke/property-live-authenticated-release-gate.json --write _completion/property_gold_status/release-gate.json`
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
- Brilliant Directories billing is in the active gold goal only as a governed handoff; timestamped HMAC verification, replay protection, public advisory webhook routing, local advisory receipt persistence, disabled webhook entitlement mutation, and authenticated local reconciliation are covered by tests. Gold remains blocked because `billing.propertyquarry.com` resolves but still lands on a second login, and the live member-login lane currently returns `Invalid recaptcha response or setup.` until BD reCAPTCHA is disabled for this lane or a trusted session handoff replaces it.
- Rybbit app analytics now use taxonomy-style app events and strip candidate identifiers from app Rybbit attributes, but wider conversion/support-loop analytics still need end-to-end dashboard receipts before gold.
- The documentation.ai whole-project audit P0/P1 findings remain in scope: runtime privilege, branch/deployment authority, reproducible builds, durable RBAC/session hardening, CI/security/accessibility/visual gates, public-network posture, documentation separation, and current-HEAD release evidence.
- Evidence-map overlays remain a whole-project gold blocker until environmental quality, summer heat, traffic/noise, public mobility, school context, official aggregate safety context, media-attention statistics with article links, and fiber/broadband coverage are implemented from source registries through Teable ingestion, cached read models, unavailable/stale/verified UI states, and search-performance receipts proving no inline source indexing.
- Rybbit remains a whole-project gold blocker until dashboard/API receipts prove the approved taxonomy arrives for public conversion, authenticated product engagement, billing handoff, tour/walkthrough interaction, support/recovery, and search activation without private candidate/listing/contact payloads.
- Release hardening remains a whole-project gold blocker until visual regression, axe/accessibility, keyboard/focus, high-zoom/mobile, empty/error/loading state, and first-value performance-budget gates run as continuous CI or release gates.
- Production security remains a whole-project gold blocker until default runtime/container hardening, locked supply chain, dependency/container scans, SBOM, durable RBAC/session revocation, key rotation posture, and disabled production loopback/principal-header override receipts are current.
- The gold-status receipt now consumes current machine-readable `propertyquarry.security_posture_receipt.v1` and `propertyquarry.release_hygiene_receipt.v1` outputs, so security posture and release-manifest authority regressions are explicit gold blockers rather than documentation-only scope.
- The public domain has a current Cloudflare smoke receipt from 2026-06-25, but must still be re-smoked through Cloudflare after each deploy.

## Manifest Rules

- Update this file whenever `main` is pushed and deployed.
- Treat a mismatch between latest tracked `main` and the runtime commit SHA as a release blocker until deployment is reconciled.
- Do not mark a candidate gold unless all P0 blockers are fixed or formally declared out of the PropertyQuarry release plane.
- Keep secrets, credentials, session cookies, license keys, and private customer data out of this file.
- Store detailed machine receipts in completion artifacts or CI output, not in tracked docs when they contain sensitive runtime context.
