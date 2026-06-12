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
  - notification email and action-surface contracts
  - FlipLink packet privacy, publication, and webhook contracts
  - MagicFit-only promo packet contracts
  - PropertyQuarry Teable tenant/projection contracts
  - phase and master exit-gate specs plus flagship browser workflows
  - property workspace real-browser greenfield checks
  - property search run contracts
  - saved search-agent management contracts
  - property market catalog contracts
  - live provider smoke receipt contracts
  - property artifact provider and sent-link manifest contracts
  - privacy-safe Rybbit analytics snippet contracts
  - Telegram titled-link delivery contracts
  - property browser journey contracts
  - dossier writer, Dadan video request, media factory, and premium dossier contracts
EOF
  exit 0
fi

cd "${EA_ROOT}"
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_docs_links.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_security_posture.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_repo_isolation.py
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_property_deploy_operator_contracts.py \
  tests/test_property_notification_email_templates.py \
  tests/test_propertyquarry_teable_sync.py \
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
  tests/test_premium_dossier_contracts.py \
  tests/test_property_env_config_contracts.py \
  tests/test_public_rybbit.py \
  tests/test_telegram_delivery_service.py \
  tests/test_property_sent_links_manifest_gate.py \
  tests/test_property_search_runs.py::test_property_search_run_surfaces_and_updates_missing_fact_research_tasks
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'property_notification_preview or property_feedback'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_product_api_contracts.py -k 'telegram_property_link_bundle or property_scout_dossier_promotes_media or property_scout_hit_telegram_sends_dossier or property_scout_hit_email_prefers_public_dossier_link or property_alert_review_handoff_page_renders_research_packet'
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_propertyquarry_workspace_redesign.py \
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
  tests/test_property_live_provider_smoke.py \
  tests/test_product_browser_journeys.py -k 'properties_workspace_surface or propertyquarry_settings_hide_generic_google_sync_metrics'
