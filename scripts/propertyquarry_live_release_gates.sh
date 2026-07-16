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

cd "${EA_ROOT}"
live_base_url="${PROPERTYQUARRY_LIVE_MOBILE_BASE_URL:-${PROPERTYQUARRY_LIVE_SMOKE_BASE_URL:-}}"
research_detail_route="${PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE:-}"
live_principal_id="${PROPERTYQUARRY_LIVE_PRINCIPAL_ID:-}"
expected_release_commit_sha="${PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA:-}"

if [[ -z "${live_base_url}" ]]; then
  echo "error: set PROPERTYQUARRY_LIVE_MOBILE_BASE_URL or PROPERTYQUARRY_LIVE_SMOKE_BASE_URL" >&2
  exit 2
fi
if [[ -z "${research_detail_route}" ]]; then
  echo "error: set PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE to a current /app/research/{id}?run_id=... route" >&2
  exit 2
fi
if [[ -z "${live_principal_id}" ]]; then
  echo "error: set PROPERTYQUARRY_LIVE_PRINCIPAL_ID to the principal that owns the research-detail route" >&2
  exit 2
fi
if [[ -z "${EA_API_TOKEN:-}" ]]; then
  echo "error: set EA_API_TOKEN for protected authenticated live release probes" >&2
  exit 2
fi
if ! [[ "${expected_release_commit_sha}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "error: set PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA to the manifest runtime full Git commit SHA" >&2
  exit 2
fi

mkdir -p _completion/smoke
export PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE="${research_detail_route}"
export PROPERTYQUARRY_ACCESSIBILITY_RESEARCH_DETAIL_ROUTE="${research_detail_route}"

PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_release_provenance.py \
  --base-url "${live_base_url}" \
  --expected-commit-sha "${expected_release_commit_sha}" \
  --expected-branch "${PROPERTYQUARRY_EXPECTED_RELEASE_BRANCH:-main}" \
  --write _completion/smoke/property-live-release-provenance.json \
  > /dev/null

PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_mobile_surface_smoke.py \
  --base-url "${live_base_url}" \
  --principal-id "${live_principal_id}" \
  --proof-mode browser-all \
  --required-browser-engines "${PROPERTYQUARRY_LIVE_MOBILE_REQUIRED_BROWSER_ENGINES:-chromium,firefox,webkit}" \
  --require-research-detail \
  --write _completion/smoke/property-live-mobile-release-gate.json \
  > /dev/null
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_accessibility_gate.py \
  --base-url "${live_base_url}" \
  --browser-engines "${PROPERTYQUARRY_LIVE_MOBILE_REQUIRED_BROWSER_ENGINES:-chromium,firefox,webkit}" \
  --axe-core-path "${PROPERTYQUARRY_AXE_CORE_PATH:-node_modules/axe-core/axe.min.js}" \
  --principal-id "${live_principal_id}" \
  --write _completion/smoke/property-live-accessibility-release-gate.json \
  > /dev/null
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_map_preview_flagship_gate.py \
  --base-url "${live_base_url}" \
  --host-header "${PROPERTYQUARRY_LIVE_HOST_HEADER:-propertyquarry.com}" \
  --principal-id "${live_principal_id}" \
  --no-canonical-fallback \
  --write _completion/smoke/property-live-map-preview-flagship-release-gate.json \
  > /dev/null
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_public_smoke.py \
  --base-url "${live_base_url}" \
  --write _completion/smoke/property-live-public-release-gate.json \
  > /dev/null
PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_authenticated_smoke.py \
  --base-url "${live_base_url}" \
  --principal-id "${live_principal_id}" \
  --expected-plan-label "${PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL:-Free}" \
  --write _completion/smoke/property-live-authenticated-release-gate.json \
  > /dev/null
