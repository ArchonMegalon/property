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
  bash scripts/runtime_hard_exit_gates.sh

Runs the runtime-only hard exit bundle that a live deploy must pass:
  - smoke_help
  - smoke_api
  - verify_pocket_audio_archive

`smoke_api_tibor.sh` stays in the full hard-exit bundle because it mutates
deeper task-contract state and is not a live-deploy-safe probe.

Optional PropertyQuarry runtime lane:
  Set PROPERTYQUARRY_RUNTIME_GATES=1 to additionally run the deployed runtime
  public/authenticated/provider smokes against PROPERTYQUARRY_LIVE_SMOKE_BASE_URL
  (default http://localhost:8097). Authenticated/provider probes require
  EA_API_TOKEN and use PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL,
  PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE, and
  PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID when provided. In this mode,
  verify_pocket_audio_archive remains informative but will warn instead of
  failing the PropertyQuarry-specific runtime lane.
EOF
  exit 0
fi

propertyquarry_runtime_gates_enabled=0
case "$(printf '%s' "${PROPERTYQUARRY_RUNTIME_GATES:-0}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on|enabled|propertyquarry)
    propertyquarry_runtime_gates_enabled=1
    ;;
esac

propertyquarry_base_url="${PROPERTYQUARRY_LIVE_SMOKE_BASE_URL:-http://localhost:8097}"
propertyquarry_principal_id="${PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID:-${EA_PRINCIPAL_ID:-cf-email:tibor.girschele@gmail.com}}"

cd "${EA_ROOT}"
bash scripts/smoke_help.sh
env -u EA_API_TOKEN bash scripts/smoke_api.sh
if [[ "${propertyquarry_runtime_gates_enabled}" == "1" ]]; then
  if ! "${PYTHON_BIN}" scripts/verify_pocket_audio_archive.py; then
    echo "PROPERTYQUARRY_RUNTIME_GATES=1 active: verify_pocket_audio_archive.py failed, continuing because Pocket archive backfill is outside the PropertyQuarry runtime lane." >&2
  fi
else
  "${PYTHON_BIN}" scripts/verify_pocket_audio_archive.py
fi

if [[ "${propertyquarry_runtime_gates_enabled}" == "1" ]]; then
  PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_live_public_smoke.py \
    --base-url "${propertyquarry_base_url}" \
    --timeout-seconds 8

  if [[ -n "${EA_API_TOKEN:-}" ]]; then
    PYTHONPATH=ea EA_API_TOKEN="${EA_API_TOKEN}" "${PYTHON_BIN}" scripts/propertyquarry_live_authenticated_smoke.py \
      --base-url "${propertyquarry_base_url}" \
      --principal-id "${propertyquarry_principal_id}" \
      --expected-plan-label "${PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL:-Agent}" \
      --country-code "${PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE:-AT}" \
      --timeout-seconds 8

    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
      PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
      PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${propertyquarry_principal_id}" \
      PYTHONPATH=ea EA_API_TOKEN="${EA_API_TOKEN}" "${PYTHON_BIN}" scripts/property_live_provider_smoke.py \
      --base-url "${propertyquarry_base_url}" \
      --timeout-seconds 8
  else
    echo "PROPERTYQUARRY_RUNTIME_GATES=1 requested but EA_API_TOKEN is not set; skipping authenticated/provider PropertyQuarry runtime smokes." >&2
  fi
fi
