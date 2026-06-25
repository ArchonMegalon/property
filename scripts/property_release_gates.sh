#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${EA_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${EA_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/property_release_gates.sh

Runs the focused PropertyQuarry release bundle:
  - property workspace redesign browser contracts
  - browser surface link/action contracts and design-system registry gates
  - notification email and action-surface contracts
  - Heyy WhatsApp adapter, opt-in, STOP/START, webhook, and receipt contracts
  - FlipLink packet privacy, publication, and webhook contracts
  - MagicFit-only promo packet contracts
  - PropertyQuarry Teable tenant/projection contracts
  - phase and master exit-gate specs plus flagship browser workflows
  - property workspace real-browser greenfield checks
  - property search run contracts
  - cached evidence-overlay contracts for unavailable/stale/verified states and no inline source indexing
  - offline ranking benchmark for hard filters, soft scoring, ordering, and scout thresholds
  - property search storage schema guard
  - saved search-agent management contracts
  - property market catalog contracts
  - PayFunnels checkout, webhook, refund, mismatch, and billing-surface contracts
  - workspace access token redaction, keyed hashes, revocation, and one-time launch-link contracts
  - ID Austria OIDC readiness receipt and Austrian-IP sign-in gating
  - live provider smoke receipt contracts
  - hosted tour control readiness receipts for Matterport, 3DVista, Pano2VR, krpano, and MagicFit
  - consolidated PropertyQuarry gold-status receipt for mobile/performance, provider matrix, tour controls, repair, and export discovery
  - required live mobile surface smoke: scripts/propertyquarry_live_mobile_surface_smoke.py against a deployed stack, including a current /app/research/{id} detail route
  - property artifact provider and sent-link manifest contracts
  - Brilliant Directories public-directory projection contracts
  - privacy-safe Rybbit analytics snippet contracts
  - Telegram titled-link delivery contracts
  - property browser journey contracts
  - dossier writer, Dadan video request, media factory, and premium dossier screenshot/quality contracts
  - public tour privacy, live-360, Matterport/3DVista, and asset hardening contracts
  - optional local visual-watch screenshot gate when PROPERTYQUARRY_VISUAL_WATCH_URL is set
EOF
  exit 0
fi

cd "${EA_ROOT}"
tour_export_incoming_dir="${PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR:-${PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR:-${EA_ROOT}/state/incoming_property_tours}}"
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_docs_links.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_security_posture.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_repo_isolation.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_release_hygiene.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_whole_project_scope.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_surface_accessibility.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_provider_governance.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_ranking_benchmark.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_teable_portability.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_search_storage_schema.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_public_tour_manifest_contract.py
mkdir -p _completion/property_tour_controls _completion/property_tour_exports _completion/smoke _completion/property_gold_status _completion/repair _completion/provider_smoke
PYTHONPATH=ea "${PYTHON_BIN}" scripts/verify_property_tour_controls.py \
  --require-all-provider-modes \
  --write _completion/property_tour_controls/release-gate.json \
  --summary-only
property_api_container="${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"
if command -v docker >/dev/null 2>&1 && docker inspect "${property_api_container}" >/dev/null 2>&1; then
  docker exec "${property_api_container}" python /app/scripts/verify_property_tour_controls.py \
    --tour-root /data/public_property_tours \
    --require-all-provider-modes \
    --write /data/artifacts/property-tour-controls-release-gate-live-container.json \
    --summary-only
  docker cp "${property_api_container}:/data/artifacts/property-tour-controls-release-gate-live-container.json" \
    _completion/property_tour_controls/release-gate.json
  docker exec "${property_api_container}" python /app/scripts/discover_property_tour_exports.py \
    --drop-dir /data/incoming_property_tours \
    --public-tour-dir /data/public_property_tours \
    --write /data/artifacts/property-tour-export-discovery-release-gate-live-container.json
  docker cp "${property_api_container}:/data/artifacts/property-tour-export-discovery-release-gate-live-container.json" \
    _completion/property_tour_exports/release-gate-discovery.json
  docker exec --user root "${property_api_container}" python /app/scripts/materialize_property_tour_export_manifest.py \
    --tour-root /data/public_property_tours \
    --incoming-root /data/incoming_property_tours \
    --prepare-dirs \
    --write /data/artifacts/property-tour-export-import-manifest-release-gate-live-container.json
  docker cp "${property_api_container}:/data/artifacts/property-tour-export-import-manifest-release-gate-live-container.json" \
    _completion/property_tour_exports/release-gate-import-manifest.json
else
  PYTHONPATH=ea "${PYTHON_BIN}" scripts/discover_property_tour_exports.py \
    --drop-dir "${tour_export_incoming_dir}" \
    --public-tour-dir "${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}" \
    --write _completion/property_tour_exports/release-gate-discovery.json
  PYTHONPATH=ea "${PYTHON_BIN}" scripts/materialize_property_tour_export_manifest.py \
    --tour-root "${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}" \
    --incoming-root "${tour_export_incoming_dir}" \
    --prepare-dirs \
    --write _completion/property_tour_exports/release-gate-import-manifest.json
fi
PYTHONPATH=ea "${PYTHON_BIN}" scripts/verify_brilliant_directories_provider.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/verify_id_austria_provider.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_authenticated_performance_smoke.py \
  --write _completion/smoke/property-auth-performance-release-gate.json >/dev/null
live_mobile_base_url="${PROPERTYQUARRY_LIVE_MOBILE_BASE_URL:-${PROPERTYQUARRY_LIVE_SMOKE_BASE_URL:-}}"
if [[ -z "${live_mobile_base_url}" ]]; then
  echo "error: set PROPERTYQUARRY_LIVE_MOBILE_BASE_URL or PROPERTYQUARRY_LIVE_SMOKE_BASE_URL before running the gold release gate" >&2
  exit 2
fi
if [[ -z "${EA_API_TOKEN:-}" ]]; then
  echo "error: set EA_API_TOKEN before running the live mobile gold release gate" >&2
  exit 2
fi
live_mobile_seed_args=()
if [[ -z "${PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE:-}" ]]; then
  if [[ "${PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE:-0}" == "1" ]]; then
    live_mobile_seed_args+=(--seed-research-detail-fixture)
  else
    echo "error: set PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE to a current /app/research/{id}?run_id=... or set PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE=1 before running the gold release gate" >&2
    exit 2
  fi
fi
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_mobile_surface_smoke.py \
  --base-url "${live_mobile_base_url}" \
  --api-token "${EA_API_TOKEN}" \
  --require-research-detail \
  "${live_mobile_seed_args[@]}" \
  --write _completion/smoke/property-live-mobile-release-gate.json \
  > /dev/null
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_repair_fleet_canary.py \
  > _completion/repair/propertyquarry-repair-canary-release-gate.json
if [[ -f _completion/provider_smoke/all-search-ready-current-resumed.json ]]; then
  cp _completion/provider_smoke/all-search-ready-current-resumed.json _completion/provider_smoke/release-gate-provider-matrix.json
elif [[ -f _completion/provider_smoke/all-search-ready-live.json ]]; then
  cp _completion/provider_smoke/all-search-ready-live.json _completion/provider_smoke/release-gate-provider-matrix.json
else
  PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=1 \
    PYTHONPATH=ea "${PYTHON_BIN}" scripts/property_live_provider_smoke.py \
    --all-search-ready-countries \
    --no-execute-search-matrix \
    --write _completion/provider_smoke/release-gate-provider-matrix.json \
    > /dev/null
fi
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_gold_status.py \
  --performance-receipt _completion/smoke/property-auth-performance-release-gate.json \
  --tour-control-receipt _completion/property_tour_controls/release-gate.json \
  --export-discovery-receipt _completion/property_tour_exports/release-gate-discovery.json \
  --import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json \
  --repair-canary-receipt _completion/repair/propertyquarry-repair-canary-release-gate.json \
  --provider-matrix-receipt _completion/provider_smoke/release-gate-provider-matrix.json \
  --live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json \
  --write _completion/property_gold_status/release-gate.json \
  --fail-on-blocked
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_property_deploy_operator_contracts.py \
  tests/test_property_live_mobile_surface_smoke.py \
  tests/test_property_worker_queues.py \
  tests/test_property_evidence_overlays.py \
  tests/test_property_delivery_governance.py \
  tests/test_property_heyy_adapter_contracts.py \
  tests/test_property_heyy_api_contracts.py \
  tests/test_property_notification_email_templates.py \
  tests/test_propertyquarry_teable_sync.py \
  tests/test_browser_surface_contracts.py \
  tests/test_propertyquarry_design_system_gate.py \
  tests/test_propertyquarry_magicfit_promo_contract.py \
  tests/test_fliplink_packet_privacy.py \
  tests/test_property_packet_publications.py \
  tests/test_fliplink_webhook_contracts.py \
  tests/test_property_missing_facts_ooda.py \
  tests/test_property_packet_engagement_contracts.py \
  tests/test_property_feedback_spine_contracts.py \
  tests/test_property_decision_loop.py \
  tests/test_property_summary_artifacts.py \
  tests/test_property_packet_variant_contracts.py \
  tests/test_propertyquarry_timeline_contracts.py \
  tests/test_propertyquarry_offer_and_optimization_contracts.py \
  tests/test_propertyquarry_phase1_exit_gate.py \
  tests/test_propertyquarry_phase2_exit_gate.py \
  tests/test_propertyquarry_phase3_exit_gate.py \
  tests/test_propertyquarry_phase4_exit_gate.py \
  tests/test_propertyquarry_phase5_exit_gate.py \
  tests/test_propertyquarry_phase6_exit_gate.py \
  tests/test_propertyquarry_phase7_exit_gate.py \
  tests/test_propertyquarry_master_regression_gate.py \
  tests/test_propertyquarry_tester_gold_gate.py \
  tests/test_dossier_writer.py \
  tests/test_dadan_video_request_workflow.py \
  tests/test_property_media_factory.py \
  tests/test_property_artifact_contracts.py \
  tests/test_property_integration_governance.py \
  tests/test_brilliant_directories_integration.py \
  tests/test_subscribr_client_contracts.py \
  tests/test_property_content_source_packets.py \
  tests/test_property_content_validation.py \
  tests/test_property_content_privacy.py \
  tests/test_property_content_studio.py \
  tests/test_property_subscribr_receipts.py \
  tests/e2e/test_property_content_studio_workflow.py \
  tests/test_crezlo_public_tour_publish.py \
  tests/test_property_tour_export_importers.py \
  tests/test_premium_dossier_contracts.py \
  tests/test_property_env_config_contracts.py \
  tests/test_public_rybbit.py \
  tests/test_telegram_delivery_service.py \
  tests/test_property_sent_links_manifest_gate.py \
  tests/test_property_search_runs.py::test_property_search_run_surfaces_and_updates_missing_fact_research_tasks
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'property_notification_preview or property_feedback'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'payfunnels'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'workspace_access'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'telegram_property_link_bundle or property_scout_dossier_promotes_media or property_scout_hit_telegram_sends_dossier or property_scout_hit_email_prefers_public_dossier_link or property_alert_review_handoff_page_renders_research_packet'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'hosted_property_tour_writer_keeps_raw_public_manifest_narrow or hosted_floorplan_tour_revalidates_asset_suffix_after_content_type or willhaben_property_tour_route_accepts_external_live_360_source_when_panorama_images_are_absent or matterport_hosted_pure_360_bundle_uses_http_thumb_preview or 3dvista_hosted_pure_360_bundle_preserves_provider_url or kalandra_cube_360_bundle_generation_is_disabled or willhaben_property_tour_route_blocks_when_only_flat_listing_photos_exist_and_360_is_required'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_providers_api_contracts.py -k 'public_tour_json_never_exposes_listing_or_source_urls or public_tour_routes_ignore_unsafe_live_360_source_urls or public_tour_page_does_not_fetch_live_listing_research_at_render_time or public_tour_routes_drop_untrusted_external_scene_media or public_tour_routes_embed_live_360_source_when_present or public_tour_routes_allow_matterport_thumb_preview_for_live_360'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_propertyquarry_workspace_redesign.py \
  tests/e2e/test_propertyquarry_soft_filter_equivalence.py \
  tests/e2e/test_propertyquarry_greenfield_browser.py \
  tests/e2e/test_propertyquarry_public_tour_browser.py \
  tests/e2e/test_propertyquarry_packet_engagement_browser.py \
  tests/e2e/test_propertyquarry_feedback_browser.py \
  tests/e2e/test_propertyquarry_summary_artifacts_browser.py \
  tests/e2e/test_propertyquarry_packet_publishing_browser.py \
  tests/e2e/test_propertyquarry_timeline_browser.py \
  tests/e2e/test_propertyquarry_commercial_optimization_browser.py \
  tests/e2e/test_propertyquarry_phase_regression_browser.py
if [[ -n "${PROPERTYQUARRY_SENT_LINKS_MANIFEST:-}" ]]; then
  PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q tests/e2e/test_propertyquarry_sent_links_browser.py
fi
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_property_search_runs.py \
  tests/test_property_search_agents.py \
  tests/test_property_market_catalog.py \
  tests/test_property_live_public_smoke.py \
  tests/test_property_live_authenticated_smoke.py \
  tests/test_property_live_provider_smoke.py \
  tests/test_product_browser_journeys.py -k 'properties_workspace_surface or propertyquarry_settings_hide_generic_google_sync_metrics'
if [[ -n "${PROPERTYQUARRY_VISUAL_WATCH_URL:-}" ]]; then
  visual_watch_base="${PROPERTYQUARRY_VISUAL_WATCH_URL}"
  visual_watch_out="${PROPERTYQUARRY_VISUAL_WATCH_OUTPUT_DIR:-${EA_ROOT}/_completion/pixefy/property_release_gate}"
  PROPERTYQUARRY_ROOT="${EA_ROOT}" PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_visual_watch.py \
    "${visual_watch_base}" \
    --samples "${PROPERTYQUARRY_VISUAL_WATCH_SAMPLES:-2}" \
    --interval-seconds "${PROPERTYQUARRY_VISUAL_WATCH_INTERVAL_SECONDS:-2}" \
    --viewport "${PROPERTYQUARRY_VISUAL_WATCH_VIEWPORT:-1440x1000}" \
    --output-dir "${visual_watch_out}/desktop"
  PROPERTYQUARRY_ROOT="${EA_ROOT}" PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_visual_watch.py \
    "${visual_watch_base}" \
    --samples "${PROPERTYQUARRY_VISUAL_WATCH_SAMPLES:-2}" \
    --interval-seconds "${PROPERTYQUARRY_VISUAL_WATCH_INTERVAL_SECONDS:-2}" \
    --viewport "${PROPERTYQUARRY_VISUAL_WATCH_MOBILE_VIEWPORT:-390x844}" \
    --output-dir "${visual_watch_out}/mobile"
fi
