# PropertyQuarry Controller State

Date: 2026-07-06
Controller: Codex
Goal: Calm, minimalistic flagship polish across billing/auth, research presentation, mobile/desktop behavior, and 3D-tour/walkthrough surfaces.

## Current repo truth

- The targeted redesign contract slice is green:
  - `pytest -x -q tests/test_propertyquarry_workspace_redesign.py -k "billing or sign_in or google or auth or research or inline or visual or walkthrough or tour"`
  - Result: `138 passed, 487 deselected`
- The browser journey for requesting a walkthrough from research and opening the resulting walkthrough is green:
  - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'walkthrough_request_is_user_initiated_in_real_browser'`
- The formerly failing ready-tour-versus-queued-walkthrough rail journey is now green:
  - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'`
  - Result: `1 passed, 83 deselected`
- The hosted-tour return path now restores the ready 3D-tour state correctly after back navigation:
  - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser'`
  - Result: `1 passed, 83 deselected`
- The wider visual-request browser slice that previously failed inside the Phase 7 gate is now green:
  - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'propertyquarry_3d_tour_request_is_user_initiated_in_real_browser or propertyquarry_walkthrough_request_is_user_initiated_in_real_browser or propertyquarry_visual_request_does_not_invent_eta_before_backend_supplies_one or propertyquarry_blocked_3d_tour_can_be_retried_from_research_packet_in_real_browser or propertyquarry_ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open'`
  - Result: `5 passed, 79 deselected`
- The Phase 7 exit gate is green:
  - `pytest -q tests/test_propertyquarry_phase7_exit_gate.py`
  - Result: `1 passed`
- The Phase 6 exit gate is green again:
  - `pytest -q tests/test_propertyquarry_phase6_exit_gate.py`
  - Result: `1 passed`
- The focused public-tour playback browser suite is green:
  - `pytest -q tests/e2e/test_propertyquarry_public_tour_browser.py`
  - Result: `9 passed`
- The focused account and billing browser slice is green:
  - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'signed_in_surfaces_prefer_verified_external_billing_handoff_in_live_browser or account_and_billing_hide_redundant_top_actions'`
  - Result: `2 passed, 82 deselected`
- The tester-gold wrapper is green:
  - `pytest -q tests/test_propertyquarry_tester_gold_gate.py`
  - Result: `1 passed in 1008.39s (0:16:48)`
- The master regression gate is green after the public sample/last-results guard:
  - `pytest -q tests/test_propertyquarry_master_regression_gate.py`
  - Result: `1 passed in 269.76s (0:04:29)`
- The consolidated gold-status receipt was refreshed:
  - `bash -lc 'set -a; source .env; set +a; PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py --write _completion/property_gold_status/latest.json >/tmp/pq-gold.out'`
  - Latest refresh: `2026-07-06T18:44:10+00:00`
  - Result: `_completion/property_gold_status/latest.json` has `tour_controls=pass`, `browser_rendered_3d=pass`, `walkthrough_quality=pass`, and `operator_import_manifest=pass`
  - Scene-video actionability is now green from the rebuilt API runtime: `_completion/scene_video_readiness/release-gate-verifier.json` has `status=pass`; Mootion uses `execution_lane=browseract_remote` with one enabled BrowserAct binding.
  - Scene-video provider runtime still reports separately: `provider_runtime_ready=false`, `provider_action_required=true`, `provider_blocked_count=3`, `blocked_providers=[magicfit, magic, omagic]`.
  - The OMagic model-upload adapter is implemented in `scripts/render_omagic_property_model_walkthrough.py`, wired into `ea/app/product/service.py` and `ea/app/services/tool_execution.py`, copied by both PropertyQuarry Dockerfiles, and now present in the rebuilt `propertyquarry-api` runtime. The remaining OMagic blockers are explicit in the API receipt: adapter disabled, endpoint/command target missing, OMagic/Magic credentials/accounts missing, and no proof render yet.
  - The provider-refresh packet now hardens the OMagic operator sequence: configure `PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT` or `PROPERTYQUARRY_OMAGIC_RENDER_COMMAND`, run a real model-upload proof render, verify `model_input_consumed=true` and `provider_backend_key=omagic`, then set `PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED=1` only after proof succeeds. `_completion/scene_video_readiness/provider-refresh-packet-verifier.json` has `status=pass`.
  - The provider-refresh packet now also hardens the MagicFit credit sequence: select a funded account with `PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX`, run a MagicFit proof render, verify `provider_backend_key=magicfit` plus a playable hosted walkthrough video, and clear `magicfit_insufficient_credits` only after that proof succeeds. `_completion/scene_video_readiness/provider-refresh-packet-verifier.json` has `status=pass` with `blockers=[]`.
  - The MagicFit render/import proof boundary now matches that packet contract: `render_magicfit_property_flythrough.py` emits `provider_backend_key=magicfit`, `render_status=completed`, and `hosted_walkthrough_video_url`; `import_magicfit_walkthrough.py` rejects target-matching receipts without `provider_backend_key=magicfit`, a completed render status, and a MagicFit-hosted video source before importing a playable local walkthrough.
  - The vendor-tooling receipt now records OMagic adapter package/deploy evidence without secrets. Current receipt `_completion/tours/property-tour-vendor-tooling-current.json` was generated against `propertyquarry-api` and reports `omagic_adapter.status=pass`, `runtime_script_ready=true`, and `runtime_script.path=/app/scripts/render_omagic_property_model_walkthrough.py`.
  - This means first-party tour hosting/playback controls and scene-video actionability are green, but Crezlo-level generated video/provider parity still requires refreshing MagicFit credits/account visibility, exposing Magic/OMagic accounts, configuring OMagic credentials plus endpoint/command, enabling the adapter only after a successful proof render, and refreshing readiness/gold receipts.
  - Remaining consolidated blockers are explicit: `scene_video_provider_runtime=action_required` and `release_hygiene=fail`. Release hygiene is fail-closed packaging posture; scene-video provider runtime is a real Crezlo-parity blocker until MagicFit/Magic/OMagic runtime gaps are cleared.
  - Gold-status unit coverage now proves that a scene-video actionability pass cannot make the aggregate pass when provider runtime readiness still has blocked providers or provider next actions.
- Runtime rebuild/deploy work completed:
  - `docker compose -f docker-compose.property.yml build propertyquarry-api`
  - Result: image `propertyquarry-web-runtime:latest` rebuilt and build step copied `scripts/render_omagic_property_model_walkthrough.py` to `/app/scripts/render_omagic_property_model_walkthrough.py`
  - `docker compose -f docker-compose.property.yml up -d --no-deps --force-recreate propertyquarry-api propertyquarry-scheduler`
  - Result: both containers healthy; `docker exec propertyquarry-api sh -lc 'test -f /app/scripts/render_omagic_property_model_walkthrough.py'` passes
- The OMagic adapter deploy-proof slice is green:
  - `python3 -m py_compile scripts/verify_property_tour_vendor_tooling.py scripts/propertyquarry_gold_status.py`
  - `pytest -q tests/test_property_tour_vendor_tooling.py`
  - Result: `16 passed`
  - `pytest -q tests/test_property_deploy_operator_contracts.py -k 'omagic or property_dockerfile_allowlists_runtime_scripts or property_web_dockerfile'`
  - Result: `2 passed, 24 deselected`
  - `pytest -q tests/test_propertyquarry_gold_status.py -k 'scene_video or passes_only_when_all_required_evidence_is_present'`
  - Result: `1 passed, 65 deselected`
- The focused scene-video actionability slice was updated and is green:
  - `python3 -m py_compile scripts/property_scene_video_readiness_report.py scripts/verify_property_scene_video_readiness.py`
  - `pytest -q tests/test_scene_video_contract.py tests/test_property_scene_video_readiness_report.py tests/test_property_scene_video_readiness_verifier.py`
  - Result: `25 passed`
  - `pytest -q tests/test_property_walkthrough_scene_video.py -k 'omagic'`
  - Result: `3 passed, 12 deselected`
  - The refreshed provider packet verifier is green: `_completion/scene_video_readiness/provider-refresh-packet-verifier.json` has `status=pass`
- The OMagic model-upload adapter slice is green:
  - `python3 -m py_compile scripts/render_omagic_property_model_walkthrough.py scripts/property_scene_video_readiness_report.py scripts/verify_property_scene_video_readiness.py scripts/materialize_scene_video_provider_refresh_packet.py ea/app/services/scene_video_contract.py ea/app/services/tool_execution.py ea/app/product/service.py`
  - `pytest -q tests/test_omagic_model_upload_adapter.py tests/test_scene_video_contract.py tests/test_property_scene_video_readiness_report.py tests/test_property_scene_video_readiness_verifier.py tests/test_property_walkthrough_scene_video.py tests/test_property_deploy_operator_contracts.py -k 'omagic or scene_video or property_dockerfile_allowlists_runtime_scripts or property_web_dockerfile'`
  - Result: `41 passed, 23 deselected`
  - `pytest -q tests/test_tool_execution.py -k 'omagic_uses_model_upload_adapter or blocks_before_delegate_when_runtime_not_ready or self_heals_missing_builtin_scene_video_generate_definition'`
  - Result: `3 passed, 132 deselected`
  - `pytest -q tests/test_scene_video_provider_refresh_packet.py`
  - Result: `13 passed`
  - MagicFit render/import proof coverage is green:
    - `python3 -m py_compile scripts/render_magicfit_property_flythrough.py scripts/import_magicfit_walkthrough.py scripts/verify_property_tour_controls.py`
    - `pytest -q tests/test_property_tour_export_importers.py`
    - Result: `36 passed`
    - `pytest -q tests/test_propertyquarry_magicfit_promo_contract.py -k 'renderer_receipt_binds_to_property_slug or renderer_fails_fast_on_credit_blocker'`
    - Result: `2 passed, 7 deselected`
- The release-hygiene receipt was refreshed:
  - `PYTHONPATH=ea python3 scripts/check_property_release_hygiene.py --write _completion/release_hygiene/property-release-hygiene-latest.json`
  - Result: fail, as intended before packaging/commit. Current failures are `tracked worktree must be clean before release` across the staged PQ work and `untracked release source files forbidden before release` for the handoff docs plus `scripts/refresh_propertyquarry_current_gold_receipts.sh`.
- The public sample shortlist rule is covered:
  - anonymous visitors can still open `/app/shortlist/run/public-demo-run` and `/app/shortlist/run/0a89ead9e0b048288cca22d1aac54fa7` as `Sample homes`
  - the fast ranked-run template now server-renders initial candidates when an initial payload exists, so the public sample routes expose a diorama thumbnail and visible `Open property` action before client-side hydration; no-JS copy stays generic as `Homes are ready` so signed-in latest results do not leak sample wording
  - authenticated visitors do not see public-entrypoint sample rows; they redirect to/latest real results when available and otherwise render the signed-in run shell without sample content
  - focused tests run:
    - `pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'fast_ranked_run_opaque_public_url or fast_ranked_run_renders_sample_homes_for_anonymous_visitors or home_shortlist_prefers_non_public_entrypoint_results_for_signed_in_users or home_shortlist_never_falls_back_to_sample_homes_for_signed_in_users'`
    - Result: `8 passed, 632 deselected`
    - `pytest -q tests/test_propertyquarry_workspace_redesign.py -k 'does_not_show_samples_for_authenticated_users_with_no_real_runs'`
    - Result: `1 passed, 639 deselected`
    - `pytest -q tests/test_property_live_public_smoke.py`
    - Result: `16 passed`
    - `pytest -q tests/e2e/test_propertyquarry_greenfield_browser.py -k 'public_shared_fast_ranked_run_shows_sample_homes_with_diorama_and_open_property or authenticated_shared_fast_ranked_run_opens_latest_results'`
    - Result: `2 passed, 83 deselected`
    - `python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097 --billing-base-url skip --write _completion/smoke/property-live-public-latest.json`
    - Result: `status=pass`, `failed_count=0`, `route_count=22`, latest refresh `2026-07-06T18:44:08.951215+00:00`, including `/app/shortlist/run/0a89ead9e0b048288cca22d1aac54fa7` with `public_fast_run_open_property=pass` and `public_fast_run_diorama_payload=pass`
    - `python3 scripts/propertyquarry_live_public_smoke.py --base-url http://127.0.0.1:8097 --route /app/shortlist/run/public-demo-run --route /app/shortlist/run/0a89ead9e0b048288cca22d1aac54fa7 --billing-base-url skip --write _completion/live/property-live-public-shared-runs-smoke.json`
    - Result: `status=pass`, `failed_count=0`, `route_count=2`, latest refresh `2026-07-06T18:44:09.645264+00:00`
- No currently failing blocker is recorded in the focused tour, walkthrough, public-tour, or account/billing slices above.
  - The latest recovered blocker was Phase 6 commercial visibility on `/app/properties`; it is now resolved.
  - Next continuation should either clear release hygiene by packaging/committing the intended worktree, clear the scene-video provider runtime gaps, or continue with receipt-driven release proof without reopening already-green tour/playback paths.

## Recent controller-side patches already in the worktree

- `ea/app/api/routes/landing_property_workspace_payload.py`
  - blocked walkthrough payload now reports an unavailable state instead of falling through to a request CTA
  - live walkthrough progress now reads the real hosted progress snapshot through `tour_runtime_url`
  - legacy external branded tour hosts now stay blocked without leaking a fake ready/missing state
- `ea/app/templates/app/_property_account_panel.html`
  - account action label normalized to `Billing account`
- `ea/app/api/routes/landing.py`
  - PropertyQuarry account-nav billing fallback now goes to `/app/billing` rather than the old in-page billing fragment
- `ea/app/api/routes/public_tours.py`
  - walkthrough shell playback got a stronger muted autoplay primer for flythrough opens
- `ea/app/templates/app/property_research_detail.html`
  - walkthrough readiness now only resolves from explicit walkthrough targets, and queued walkthroughs keep polling without overriding a ready 3D tour
  - ready 3D-tour button state now persists across hosted-tour opens and restores before the return-path resync fetch runs
- `ea/app/templates/app/_property_selected_review_panel.html`
  - finished property results now surface a contextual `Premium next step` offer block with real `Open checkout` entry points
  - the offer block only appears when a selected property/result context exists, so commercial prompts stay fail-closed on empty search surfaces
- `ea/app/templates/app/object_detail.html`
  - detail-surface walkthrough readiness and polling now match research detail behavior
- `ea/app/templates/app/_property_workbench_script.html`
  - shortlist/workbench walkthrough readiness now fails closed instead of inventing readiness from a ready tour URL
- `scripts/render_omagic_property_model_walkthrough.py`
  - new fail-closed OMagic/Magic model-upload adapter; supports endpoint and command adapter modes, records env names only, requires model input, and writes proof state for hosted walkthrough video output
- `ea/app/services/scene_video_contract.py`, `scripts/property_scene_video_readiness_report.py`, `scripts/verify_property_scene_video_readiness.py`
  - OMagic readiness now distinguishes missing script, disabled adapter, missing endpoint/command, and missing credentials
  - Mootion release proof now requires an explicit remote BrowserAct lane next-action when local fallback is present but not release-grade
- `ea/app/product/service.py`, `ea/app/services/tool_execution.py`
  - OMagic scene-video generation now invokes the model-upload adapter only after runtime readiness and model-input checks pass; failures remain user-visible and fail-closed
- `ea/Dockerfile.property`, `ea/Dockerfile.property-web`, `.env.example`
  - OMagic adapter is packaged and its endpoint/command env knobs are documented
- `scripts/verify_property_tour_vendor_tooling.py`, `scripts/propertyquarry_gold_status.py`
  - vendor tooling now emits an `omagic_adapter` section with source/runtime script proof, env-name-only config visibility, and a deploy next-action when a checked runtime is missing the adapter
  - gold status now blocks on refreshed runtime evidence if the checked API container is pre-adapter instead of relying on stale operator memory; current rebuilt API runtime proof is green
- `scripts/refresh_propertyquarry_current_gold_receipts.sh`, `scripts/property_release_gates.sh`
  - vendor-tooling receipt generation now runs from the host with `--runtime-container propertyquarry-api` so OMagic adapter deploy proof checks the API runtime where product rendering executes, not only the render-tools container

## Worker roster

- Worker A: browser visual-request state machine
  - handoff: [2026-07-06-worker-a-visual-request-state.md](./2026-07-06-worker-a-visual-request-state.md)
- Worker B: public tour playback shell and walkthrough open behavior
  - handoff: [2026-07-06-worker-b-public-tour-playback.md](./2026-07-06-worker-b-public-tour-playback.md)
- Worker C: account, billing, and auth surface consistency
  - handoff: [2026-07-06-worker-c-account-billing-auth.md](./2026-07-06-worker-c-account-billing-auth.md)

## Shared constraints

- Do not revert unrelated user or controller edits.
- Default to minimalistic, user-first wording.
- Keep UI noise down; do not add proofy or internal language.
- Prefer generic fixes over one-off test shims.
- Keep owned scope tight; if a fix requires broader edits, record that in the receipt.
