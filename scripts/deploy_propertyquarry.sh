#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROPERTYQUARRY_COMPOSE_FILE:-docker-compose.property.yml}"
PREFLIGHT_ONLY=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_propertyquarry.sh [--preflight-only]

Deploys the standalone PropertyQuarry runtime with operator preflight checks:
  - creates .env from .env.example when missing, then stops for credential setup
  - requires POSTGRES_PASSWORD before Docker build/compose interpolation
  - in prod, requires EA_SIGNING_SECRET and EA_API_TOKEN or Cloudflare Access
  - rejects EA_ALLOW_LOOPBACK_NO_AUTH=1 in prod
  - checks EA_HOST_PORT for obvious conflicts before rebuilding
  - starts docker-compose.property.yml in DB -> API -> scheduler order to avoid startup schema deadlocks
    and refreshes the render-tools runtime before gold verification
  - rejects web/scheduler processes that start with background nice priority
  - can add docker-compose.cloudflared.yml only for a dedicated PropertyQuarry tunnel token
  - supports isolated blue/green deploys via configurable Compose project/container names
  - probes /health, /health/ready, /version, public routes, PWA/SEO assets, and /app/properties auth

Environment:
  PROPERTYQUARRY_COMPOSE_FILE     Compose file path, default docker-compose.property.yml.
  PROPERTYQUARRY_ENABLE_CLOUDFLARED
                                  1|0|auto. Adds docker-compose.cloudflared.yml only when explicitly enabled
                                  or when PROPERTYQUARRY_CF_TUNNEL_TOKEN is present. Defaults to auto.
  PROPERTYQUARRY_CF_TUNNEL_TOKEN  Dedicated PropertyQuarry Cloudflare tunnel token.
  PROPERTYQUARRY_COMPOSE_PROJECT_NAME
                                   Optional Compose project name override.
  PROPERTYQUARRY_*_CONTAINER_NAME Optional container names for isolated deploys.
  EA_HOST_PORT                    Host port for the API, default 8090.
  PROPERTYQUARRY_DEPLOY_BASE_URL  Probe URL, default http://localhost:${EA_HOST_PORT}.
  PROPERTYQUARRY_DEPLOY_CORE_PROBE_TIMEOUT_SECONDS
                                  Timeout for /version, /, and auth-boundary curl probes. Default 20.
  PROPERTYQUARRY_DEPLOY_PROVIDER_E2E
                                  1 enables the full all-search-ready provider matrix with strict and
                                  soft-filter dispatch/readback checks after deploy. Default 0 keeps the
                                  lighter provider-catalog smoke without replacing the latest full
                                  targeted-matrix receipt when one exists.
                                  Deploy fails closed when provider/search implementation files changed
                                  since the live release and this is not enabled.
  PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E
                                  1 requires the composed live presentation E2E, 0 skips it, auto runs it
                                  only when PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1. Default auto. When this
                                  runs, browser-rendered 3D controls and walkthrough quality are also hard gates.
  PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES
                                  Optional comma-separated country list for focused provider verification,
                                  for example AT,DE,CR. When set with PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1,
                                  the deploy runs the strict/soft targeted matrix only for those countries
                                  instead of every search-ready country.
  PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED
                                  1 enables the Telegram gold-status notification. Defaults to 0.
  PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID
                                  Telegram notification principal for a green gold receipt.
                                  Defaults to EA_PRINCIPAL_ID or propertyquarry-operator.
  PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL
                                  Public URL included in the gold notification. Defaults to https://propertyquarry.com.
  PROPERTYQUARRY_GOLD_NOTIFICATION_STATE
                                  Send-once state file for green gold notifications.
  PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME
                                  Prefer the live API container for PropertyQuarry Telegram notifications
                                  before falling back to the host runtime. Defaults to 1 in this deploy lane.
  PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED
                                  1 enables the Telegram scene-video provider refresh notification when
                                  current runtime receipts still show actionable MagicFit/OMagic gaps.
                                  Defaults to 0.
  PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_PRINCIPAL_ID
                                  Telegram notification principal for the scene-video provider refresh ask.
                                  Defaults to EA_PRINCIPAL_ID or propertyquarry-operator.
  PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_BASE_URL
                                  Public URL included in the scene-video provider refresh notification.
                                  Defaults to https://propertyquarry.com.
  PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_STATE
                                  Send-once state file for scene-video provider refresh notifications.
  PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BOOTSTRAP_EDGE
                                  1|0|auto. When billing.propertyquarry.com is configured, keeps the
                                  Cloudflare billing worker aligned with the current billing host and
                                  bridge path. Default auto.
  PROPERTYQUARRY_BILLING_WORKER_BOOTSTRAP_TIMEOUT_SECONDS
                                  Hard timeout for the Cloudflare billing worker bootstrap. Default 120.
  PROPERTYQUARRY_DEPLOY_MAX_RUNTIME_NICE
                                  Maximum accepted host nice value for API, scheduler, and render-tools
                                  processes.
                                  Default 10; values above this are treated as a failed deploy.
  PROPERTYQUARRY_DEPLOY_STRICT_THREAD_NICE
                                  1 also fails when a secondary runtime thread remains above
                                  PROPERTYQUARRY_DEPLOY_MAX_RUNTIME_NICE after correction.
                                  Default 0 checks and corrects threads, but fails only when
                                  the main container process remains starved.
  PROPERTYQUARRY_DEPLOY_STRICT_RUNTIME_NICE
                                  Deprecated compatibility switch. Deploy now fails when the
                                  main API or scheduler process remains above
                                  PROPERTYQUARRY_DEPLOY_MAX_RUNTIME_NICE after correction.
  PROPERTYQUARRY_RUNTIME_CGROUP_PARENT
                                  Compose cgroup parent for PropertyQuarry runtime containers.
                                  Defaults to system.slice so deploys launched from a low-priority
                                  operator shell do not place production containers into a
                                  host-background low-priority cgroup.
  PROPERTYQUARRY_DEPLOY_TMP_DIR   Optional directory for transient deploy receipts. By default deploy
                                  creates a fresh mktemp directory and copies stable receipts into _completion.
  PROPERTYQUARRY_DEPLOY_PYTHON_BIN
                                  Optional Python interpreter for host deploy gates. When omitted, deploy
                                  auto-detects a Playwright-capable Python, including the invoking sudo user.
  PROPERTYQUARRY_WALKTHROUGH_QUALITY_PROCESS_TIMEOUT_SECONDS
                                  Hard timeout for the walkthrough-quality gate process. Default 180.
  PROPERTYQUARRY_WALKTHROUGH_QUALITY_FFPROBE_TIMEOUT_SECONDS
                                  Hard timeout for the gate's ffprobe metadata read. Default 20.
  PROPERTYQUARRY_WALKTHROUGH_QUALITY_FRAME_SAMPLE_TIMEOUT_SECONDS
                                  Hard timeout for the gate's ffmpeg frame sampling step. Default 45.
  PROPERTYQUARRY_WALKTHROUGH_QUALITY_TOUR_ROOT
                                  Optional walkthrough-quality tour root override. Defaults to
                                  state/public_property_tours and is useful when deploy gates run
                                  from an isolated worktree that should verify against the shared
                                  live tour asset root.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${APP_ROOT}"
scene_video_shared_env_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_FILE:-state/runtime/property_scene_video_shared.env}"
scene_video_shared_env_runtime_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_RUNTIME_FILE:-/home/ea/property_scene_video_shared.env}"

materialize_scene_video_shared_env() {
  python3 scripts/property_scene_video_shared_env.py --output "${scene_video_shared_env_file}" >/dev/null
}

copy_scene_video_shared_env_to_container() {
  local container="$1"
  if [[ ! -f "${scene_video_shared_env_file}" ]]; then
    echo "Missing scene-video shared env file: ${scene_video_shared_env_file}" >&2
    return 1
  fi
  docker exec -i "${container}" sh -lc '
    umask 077
    cat > "$1"
    chmod 600 "$1"
  ' sh "${scene_video_shared_env_runtime_file}" < "${scene_video_shared_env_file}"
}

docker_exec_scene_video_python() {
  local container="$1"
  shift
  copy_scene_video_shared_env_to_container "${container}" || return 1
  docker exec "${container}" sh -lc '
    set -a
    . "$1"
    set +a
    shift
    exec python "$@"
  ' sh "${scene_video_shared_env_runtime_file}" "$@"
}

normalise_deploy_process_priority() {
  local current_pid parent_pid pgid pid nice_value
  current_pid="${BASHPID:-$$}"
  pgid="$(ps -o pgid= -p "${current_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  nice_value="$(ps -o ni= -p "${current_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ -z "${nice_value}" || ! "${nice_value}" =~ ^-?[0-9]+$ ]]; then
    return 0
  fi
  if (( nice_value > 0 )) && [[ "$(id -u)" == "0" ]]; then
    echo "Deploy process started with host nice ${nice_value}; correcting to nice 0." >&2
    renice -n 0 -p "${current_pid}" >/dev/null || true
    if [[ -n "${pgid}" && "${pgid}" =~ ^[0-9]+$ ]]; then
      renice -n 0 -g "${pgid}" >/dev/null || true
      while IFS= read -r pid; do
        pid="$(printf '%s' "${pid}" | tr -d '[:space:]')"
        if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
          renice -n 0 -p "${pid}" >/dev/null || true
        fi
      done < <(ps -o pid= -g "${pgid}" 2>/dev/null || true)
    fi
    parent_pid="$(ps -o ppid= -p "${current_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
    while [[ -n "${parent_pid}" && "${parent_pid}" =~ ^[0-9]+$ && "${parent_pid}" != "0" && "${parent_pid}" != "1" ]]; do
      renice -n 0 -p "${parent_pid}" >/dev/null || true
      parent_pid="$(ps -o ppid= -p "${parent_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
    done
  fi
}

normalise_deploy_process_priority

deploy_tmp_dir="${PROPERTYQUARRY_DEPLOY_TMP_DIR:-}"
if [[ -n "${deploy_tmp_dir}" ]]; then
  mkdir -p "${deploy_tmp_dir}"
else
  deploy_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/propertyquarry-deploy.XXXXXX")"
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Compose file not found: ${COMPOSE_FILE}" >&2
  exit 2
fi

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo ".env is missing and .env.example is not available" >&2
    exit 2
  fi
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  cat >&2 <<'EOF'
Created .env from .env.example.
Fill the required production credentials, especially POSTGRES_PASSWORD, EA_SIGNING_SECRET,
and EA_API_TOKEN or Cloudflare Access settings, then rerun deploy.
EOF
  exit 2
fi

materialize_scene_video_shared_env

strip_env_value() {
  local value="${1//$'\r'/}"
  value="$(printf '%s' "${value}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s' "${value}"
}

env_file_value() {
  local key="$1"
  local line=""
  line="$(awk -v key="${key}" 'BEGIN { prefix = key "=" } index($0, prefix) == 1 { value = substr($0, length(prefix) + 1) } END { print value }' .env)"
  strip_env_value "${line}"
}

effective_env_value() {
  local key="$1"
  local value="${!key-}"
  if [[ -z "${value}" ]]; then
    value="$(env_file_value "${key}")"
  fi
  strip_env_value "${value}"
}

env_truthy() {
  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "${value}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

python_candidate_has_deploy_gate_modules() {
  local candidate="$1"
  if [[ -z "${candidate}" ]]; then
    return 1
  fi
  "${candidate}" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

required = ("playwright.sync_api", "PIL", "requests")
missing = [module for module in required if not importlib.util.find_spec(module)]
if missing:
    print("missing deploy gate module(s): " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY
}

python_candidate_has_playwright() {
  python_candidate_has_deploy_gate_modules "$1"
}

playwright_browsers_path_has_chromium() {
  local candidate="$1"
  if [[ -z "${candidate}" || ! -d "${candidate}" ]]; then
    return 1
  fi
  find "${candidate}" -maxdepth 4 -type f \( -name chrome-headless-shell -o -name chrome \) -print -quit 2>/dev/null | grep -q .
}

resolve_deploy_playwright_browsers_path() {
  local explicit candidate sudo_home
  explicit="$(effective_env_value PLAYWRIGHT_BROWSERS_PATH)"
  if [[ -n "${explicit}" ]]; then
    if playwright_browsers_path_has_chromium "${explicit}"; then
      printf '%s' "${explicit}"
      return 0
    fi
    echo "PLAYWRIGHT_BROWSERS_PATH does not contain a Chromium browser: ${explicit}" >&2
    exit 2
  fi

  local candidates=()
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    sudo_home="$(getent passwd "${SUDO_USER}" 2>/dev/null | awk -F: '{print $6}')"
    if [[ -n "${sudo_home}" ]]; then
      candidates+=("${sudo_home}/.cache/ms-playwright")
    fi
  fi
  candidates+=("${HOME:-}/.cache/ms-playwright")
  candidates+=("/ms-playwright")

  local seen=":"
  for candidate in "${candidates[@]}"; do
    if [[ -z "${candidate}" || "${seen}" == *":${candidate}:"* ]]; then
      continue
    fi
    seen="${seen}${candidate}:"
    if playwright_browsers_path_has_chromium "${candidate}"; then
      printf '%s' "${candidate}"
      return 0
    fi
  done

  return 1
}

resolve_deploy_python_bin() {
  local explicit candidate resolved sudo_home
  explicit="$(effective_env_value PROPERTYQUARRY_DEPLOY_PYTHON_BIN)"
  if [[ -n "${explicit}" ]]; then
    if resolved="$(command -v "${explicit}" 2>/dev/null)"; then
      :
    elif [[ -x "${explicit}" ]]; then
      resolved="${explicit}"
    else
      echo "PROPERTYQUARRY_DEPLOY_PYTHON_BIN is not executable or on PATH: ${explicit}" >&2
      exit 2
    fi
    if python_candidate_has_deploy_gate_modules "${resolved}"; then
      printf '%s' "${resolved}"
      return 0
    fi
    echo "PROPERTYQUARRY_DEPLOY_PYTHON_BIN cannot import required deploy gate modules: ${resolved}" >&2
    echo "Install Playwright, Pillow, and requests for that interpreter or point PROPERTYQUARRY_DEPLOY_PYTHON_BIN at the repo/user Python that has them." >&2
    exit 2
  fi

  local candidates=()
  candidates+=("${APP_ROOT}/.venv/bin/python")
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidates+=("${PYTHON_BIN}")
  fi
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    sudo_home="$(getent passwd "${SUDO_USER}" 2>/dev/null | awk -F: '{print $6}')"
    if [[ -n "${sudo_home}" ]]; then
      candidates+=("${sudo_home}/.local/bin/python3")
      candidates+=("${sudo_home}/.local/bin/python")
    fi
  fi

  local checked=""
  local seen=":"
  for candidate in "${candidates[@]}"; do
    if [[ -z "${candidate}" ]]; then
      continue
    fi
    if resolved="$(command -v "${candidate}" 2>/dev/null)"; then
      :
    elif [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    else
      continue
    fi
    if [[ "${seen}" == *":${resolved}:"* ]]; then
      continue
    fi
    seen="${seen}${resolved}:"
    checked="${checked} ${resolved}"
    if python_candidate_has_deploy_gate_modules "${resolved}"; then
      printf '%s' "${resolved}"
      return 0
    fi
  done

  echo "No Python with required PropertyQuarry deploy gate modules found." >&2
  echo "Checked:${checked:- none}" >&2
  echo "Set PROPERTYQUARRY_DEPLOY_PYTHON_BIN or install Playwright, Pillow, and requests for the deploy interpreter." >&2
  exit 2
}

require_nonempty() {
  local key="$1"
  local hint="$2"
  if [[ -z "$(effective_env_value "${key}")" ]]; then
    echo "${key} is required. ${hint}" >&2
    exit 2
  fi
}

runtime_mode="$(effective_env_value EA_RUNTIME_MODE)"
runtime_mode="${runtime_mode:-prod}"
runtime_mode="$(printf '%s' "${runtime_mode}" | tr '[:upper:]' '[:lower:]')"
host_port="$(effective_env_value EA_HOST_PORT)"
host_port="${host_port:-8090}"
api_token="$(effective_env_value EA_API_TOKEN)"
signing_secret="$(effective_env_value EA_SIGNING_SECRET)"
storage_backend="$(effective_env_value EA_STORAGE_BACKEND)"
database_url="$(effective_env_value DATABASE_URL)"
cf_access_team_domain="$(effective_env_value EA_CF_ACCESS_TEAM_DOMAIN)"
cf_access_aud="$(effective_env_value EA_CF_ACCESS_AUD)"
allow_loopback_no_auth="$(effective_env_value EA_ALLOW_LOOPBACK_NO_AUTH)"
telegram_bot_registry_json="$(effective_env_value EA_TELEGRAM_BOT_REGISTRY_JSON)"
telegram_bot_token="$(effective_env_value EA_TELEGRAM_BOT_TOKEN)"
telegram_bot_handle="$(effective_env_value EA_TELEGRAM_BOT_HANDLE)"
property_public_base_url="$(effective_env_value PROPERTYQUARRY_PUBLIC_BASE_URL)"
property_public_base_url="${property_public_base_url:-https://propertyquarry.com}"
release_repository="$(effective_env_value PROPERTYQUARRY_RELEASE_REPOSITORY)"
if [[ -z "${release_repository}" ]]; then
  release_repository="$(git config --get remote.propertyquarry.url 2>/dev/null || git config --get remote.origin.url 2>/dev/null || true)"
fi
release_branch="$(effective_env_value PROPERTYQUARRY_RELEASE_BRANCH)"
release_branch="${release_branch:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)}"
release_commit_sha="$(effective_env_value PROPERTYQUARRY_RELEASE_COMMIT_SHA)"
release_commit_sha="${release_commit_sha:-$(git rev-parse HEAD 2>/dev/null || true)}"
release_commit_short="${release_commit_sha:0:12}"
release_generated_at="$(effective_env_value PROPERTYQUARRY_RELEASE_GENERATED_AT)"
release_generated_at="${release_generated_at:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
release_deployment_id="$(effective_env_value PROPERTYQUARRY_RELEASE_DEPLOYMENT_ID)"
release_deployment_id="${release_deployment_id:-local-$(date -u +%Y%m%dT%H%M%SZ)-${release_commit_short:-unknown}}"
release_public_origin="$(effective_env_value PROPERTYQUARRY_RELEASE_PUBLIC_ORIGIN)"
release_public_origin="${release_public_origin:-${property_public_base_url}}"
release_artifact_set="$(effective_env_value PROPERTYQUARRY_RELEASE_ARTIFACT_SET)"
release_artifact_set="${release_artifact_set:-propertyquarry-web-runtime,propertyquarry-scheduler,propertyquarry-db,propertyquarry-cloudflared}"
release_label="$(effective_env_value PROPERTYQUARRY_RELEASE_LABEL)"
release_label="${release_label:-propertyquarry-live}"
export PROPERTYQUARRY_RELEASE_REPOSITORY="${release_repository}"
export PROPERTYQUARRY_RELEASE_BRANCH="${release_branch}"
export PROPERTYQUARRY_RELEASE_COMMIT_SHA="${release_commit_sha}"
export PROPERTYQUARRY_RELEASE_DEPLOYMENT_ID="${release_deployment_id}"
export PROPERTYQUARRY_RELEASE_PUBLIC_ORIGIN="${release_public_origin%/}"
export PROPERTYQUARRY_RELEASE_ARTIFACT_SET="${release_artifact_set}"
export PROPERTYQUARRY_RELEASE_LABEL="${release_label}"
export PROPERTYQUARRY_RELEASE_GENERATED_AT="${release_generated_at}"
bd_bootstrap_edge="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BOOTSTRAP_EDGE)"
bd_bootstrap_edge="${bd_bootstrap_edge:-auto}"
bd_billing_url="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL)"
bd_billing_dns_target="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET)"
bd_billing_fallback_urls="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_FALLBACK_URLS)"
bd_bridge_enabled="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_ENABLED)"
bd_bridge_url="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL)"
bd_bridge_secret="$(effective_env_value PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET)"

require_nonempty "POSTGRES_PASSWORD" "Set it in .env or export it for this deploy."

if [[ "${runtime_mode}" == "prod" ]]; then
  if [[ -z "${signing_secret}" ]]; then
    echo "EA_SIGNING_SECRET is required when EA_RUNTIME_MODE=prod." >&2
    exit 2
  fi
  if [[ -z "${api_token}" && ( -z "${cf_access_team_domain}" || -z "${cf_access_aud}" ) ]]; then
    echo "EA_RUNTIME_MODE=prod requires EA_API_TOKEN or Cloudflare Access via EA_CF_ACCESS_TEAM_DOMAIN and EA_CF_ACCESS_AUD." >&2
    exit 2
  fi
  if env_truthy "${allow_loopback_no_auth}"; then
    echo "EA_RUNTIME_MODE=prod forbids EA_ALLOW_LOOPBACK_NO_AUTH=1." >&2
    exit 2
  fi
fi

if env_truthy "${bd_bridge_enabled}"; then
  require_nonempty "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL" \
    "Set the signed billing bridge URL before enabling the bridge."
  require_nonempty "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET" \
    "Set a shared bridge secret before enabling the bridge."
fi

deploy_python_bin="$(resolve_deploy_python_bin)"
echo "Using deploy Python: ${deploy_python_bin}" >&2
deploy_playwright_browsers_path="$(resolve_deploy_playwright_browsers_path || true)"
if [[ -n "${deploy_playwright_browsers_path}" ]]; then
  export PLAYWRIGHT_BROWSERS_PATH="${deploy_playwright_browsers_path}"
  echo "Using Playwright browsers: ${PLAYWRIGHT_BROWSERS_PATH}" >&2
fi

if ! [[ "${host_port}" =~ ^[0-9]+$ ]] || (( host_port < 1 || host_port > 65535 )); then
  echo "EA_HOST_PORT must be a TCP port between 1 and 65535; got ${host_port}." >&2
  exit 2
fi

provider_search_change_pathspecs=(
  "ea/app/product/extractors.py"
  "ea/app/product/property_listing_extractors.py"
  "ea/app/product/property_search_*.py"
  "ea/app/product/property_location_research.py"
  "ea/app/product/property_worker_queues.py"
  "ea/app/services/provider_registry.py"
  "ea/app/api/routes/providers.py"
  "ea/app/api/routes/product_api.py"
  "scripts/property_live_provider_smoke.py"
  "scripts/property_provider_matrix_stage_runner.py"
  "scripts/willhaben_property_packet.py"
  "scripts/check_property_provider_governance.py"
  "tests/test_property_live_provider_smoke.py"
  "tests/test_property_listing_extractors.py"
  "tests/test_product_extractors.py"
  "tests/test_property_search_runs.py"
)

presentation_media_change_pathspecs=(
  "ea/app/product/property_tour_hosting.py"
  "ea/app/services/property_media_factory.py"
  "ea/app/api/routes/public_tours.py"
  "ea/app/api/routes/public_tour_payloads.py"
  "ea/app/api/routes/landing_property_research.py"
  "ea/app/templates/app/property_research_detail.html"
  "ea/app/templates/app/property_decision_workbench.html"
  "ea/app/templates/app/property_ranked_run_fast.html"
  "ea/app/templates/app/_property_workbench_script.html"
  "scripts/propertyquarry_live_presentation_e2e.py"
  "scripts/propertyquarry_3d_browser_gate.py"
  "scripts/propertyquarry_walkthrough_quality_gate.py"
  "scripts/import_3dvista_export.py"
  "scripts/attach_provider_tour_layer.py"
  "scripts/import_property_tour_exports.py"
  "scripts/generate_property_reconstruction.py"
  "scripts/import_magicfit_walkthrough.py"
  "scripts/discover_property_tour_exports.py"
  "scripts/materialize_property_tour_export_manifest.py"
  "scripts/verify_property_tour_controls.py"
  "tests/test_property_tour_control_verifier.py"
  "tests/test_property_tour_export_importers.py"
  "tests/test_property_generated_reconstruction.py"
  "tests/test_property_media_factory.py"
  "tests/e2e/test_propertyquarry_public_tour_browser.py"
)

live_release_commit_for_provider_guard() {
  local probe_url="$1"
  local body=""
  body="$(curl -fsS --connect-timeout 2 --max-time 8 "${probe_url%/}/version" 2>/dev/null || true)"
  if [[ -z "${body}" ]]; then
    return 0
  fi
  printf '%s' "${body}" | "${deploy_python_bin}" -c 'import json,sys; print(str((json.load(sys.stdin).get("release_commit_sha") or "")).strip())' 2>/dev/null || true
}

provider_search_changed_files_between() {
  local from_commit="$1"
  local to_commit="$2"
  if [[ -z "${from_commit}" || -z "${to_commit}" || "${from_commit}" == "${to_commit}" ]]; then
    return 0
  fi
  if ! git rev-parse --verify "${from_commit}^{commit}" >/dev/null 2>&1; then
    return 0
  fi
  if ! git rev-parse --verify "${to_commit}^{commit}" >/dev/null 2>&1; then
    return 0
  fi
  git diff --name-only "${from_commit}..${to_commit}" -- "${provider_search_change_pathspecs[@]}" 2>/dev/null || true
}

presentation_media_changed_files_between() {
  local from_commit="$1"
  local to_commit="$2"
  if [[ -z "${from_commit}" || -z "${to_commit}" || "${from_commit}" == "${to_commit}" ]]; then
    return 0
  fi
  if ! git rev-parse --verify "${from_commit}^{commit}" >/dev/null 2>&1; then
    return 0
  fi
  if ! git rev-parse --verify "${to_commit}^{commit}" >/dev/null 2>&1; then
    return 0
  fi
  git diff --name-only "${from_commit}..${to_commit}" -- "${presentation_media_change_pathspecs[@]}" 2>/dev/null || true
}

provider_country_scope_covers_current_markets() {
  local raw="$1"
  local normalized
  normalized=","
  raw="$(printf '%s' "${raw}" | tr '[:lower:]' '[:upper:]')"
  if [[ -z "$(printf '%s' "${raw}" | tr -d '[:space:],')" ]]; then
    return 0
  fi
  IFS=',' read -r -a provider_guard_country_items <<<"${raw}"
  for item in "${provider_guard_country_items[@]}"; do
    item="$(printf '%s' "${item}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    if [[ -n "${item}" ]]; then
      normalized="${normalized}${item},"
    fi
  done
  [[ "${normalized}" == *",AT,"* && "${normalized}" == *",DE,"* && "${normalized}" == *",CR,"* ]]
}

assert_provider_search_changes_have_targeted_e2e() {
  local probe_url="$1"
  local live_commit changed_files provider_e2e country_scope
  live_commit="$(live_release_commit_for_provider_guard "${probe_url}")"
  changed_files="$(provider_search_changed_files_between "${live_commit}" "${release_commit_sha}")"
  if [[ -z "${changed_files}" ]]; then
    return 0
  fi
  provider_e2e="$(effective_env_value PROPERTYQUARRY_DEPLOY_PROVIDER_E2E)"
  country_scope="$(effective_env_value PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES)"
  if env_truthy "${provider_e2e}" && provider_country_scope_covers_current_markets "${country_scope}"; then
    return 0
  fi
  echo "Provider/search implementation changed since the live release; deploy requires targeted provider E2E for AT,DE,CR." >&2
  echo "Set PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1 and PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES=AT,DE,CR before deploying." >&2
  echo "Live commit: ${live_commit:-unknown}" >&2
  echo "Target commit: ${release_commit_sha:-unknown}" >&2
  echo "Changed provider/search files:" >&2
  printf '%s\n' "${changed_files}" >&2
  exit 2
}

presentation_e2e_will_run_for_deploy() {
  local mode provider_e2e
  mode="$(effective_env_value PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E)"
  mode="${mode:-auto}"
  mode="$(printf '%s' "${mode}" | tr '[:upper:]' '[:lower:]')"
  provider_e2e="$(effective_env_value PROPERTYQUARRY_DEPLOY_PROVIDER_E2E)"
  if env_truthy "${mode}"; then
    return 0
  fi
  if [[ "${mode}" == "auto" ]] && env_truthy "${provider_e2e}"; then
    return 0
  fi
  return 1
}

assert_presentation_media_changes_have_e2e() {
  local probe_url="$1"
  local live_commit changed_files
  live_commit="$(live_release_commit_for_provider_guard "${probe_url}")"
  changed_files="$(presentation_media_changed_files_between "${live_commit}" "${release_commit_sha}")"
  if [[ -z "${changed_files}" ]]; then
    return 0
  fi
  if presentation_e2e_will_run_for_deploy; then
    return 0
  fi
  echo "Tour, media, or presentation code changed since the live release; deploy requires presentation E2E." >&2
  echo "Set PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E=1 before deploying, or run provider E2E which includes the presentation, 3D browser, and walkthrough quality gates." >&2
  echo "Live commit: ${live_commit:-unknown}" >&2
  echo "Target commit: ${release_commit_sha:-unknown}" >&2
  echo "Changed tour/media/presentation files:" >&2
  printf '%s\n' "${changed_files}" >&2
  exit 2
}

predeploy_base_url="$(effective_env_value PROPERTYQUARRY_DEPLOY_BASE_URL)"
predeploy_base_url="${predeploy_base_url:-http://localhost:${host_port}}"
assert_provider_search_changes_have_targeted_e2e "${predeploy_base_url%/}"
assert_presentation_media_changes_have_e2e "${predeploy_base_url%/}"

compose_project_name="$(effective_env_value PROPERTYQUARRY_COMPOSE_PROJECT_NAME)"
compose_project_name="${compose_project_name:-$(effective_env_value COMPOSE_PROJECT_NAME)}"
enable_cloudflared="$(effective_env_value PROPERTYQUARRY_ENABLE_CLOUDFLARED)"
enable_cloudflared="${enable_cloudflared:-auto}"
cf_tunnel_token="$(effective_env_value PROPERTYQUARRY_CF_TUNNEL_TOKEN)"

compose_probe_timeout="$(effective_env_value PROPERTYQUARRY_COMPOSE_PROBE_TIMEOUT_SECONDS)"
compose_probe_timeout="${compose_probe_timeout:-10}"

compose_probe() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "${compose_probe_timeout}s" "$@"
  else
    "$@"
  fi
}

docker_compose_detected=0
if command -v docker >/dev/null 2>&1; then
  docker_compose_detected=1
fi

if compose_probe docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
  if [[ -n "${compose_project_name}" ]]; then
    DC+=(-p "${compose_project_name}")
  fi
  DC+=(-f "${COMPOSE_FILE}")
elif command -v docker-compose >/dev/null 2>&1; then
  if ! compose_probe docker-compose version >/dev/null 2>&1; then
    echo "docker-compose is installed but did not answer within ${compose_probe_timeout}s." >&2
    echo "Repair Docker Compose on the host or set PROPERTYQUARRY_COMPOSE_PROBE_TIMEOUT_SECONDS to tune the probe." >&2
    exit 2
  fi
  DC=(docker-compose)
  if [[ -n "${compose_project_name}" ]]; then
    DC+=(-p "${compose_project_name}")
  fi
  DC+=(-f "${COMPOSE_FILE}")
else
  if [[ "${docker_compose_detected}" == "1" ]]; then
    echo "docker compose is installed but did not answer within ${compose_probe_timeout}s." >&2
    echo "Repair the Docker Compose plugin on the host or use a working docker-compose binary." >&2
  else
    echo "Docker Compose is required: install docker compose or docker-compose." >&2
  fi
  exit 2
fi

cloudflared_compose_file="docker-compose.cloudflared.yml"
should_enable_cloudflared=0
case "$(printf '%s' "${enable_cloudflared}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    should_enable_cloudflared=1
    ;;
  auto)
    if [[ -n "${cf_tunnel_token}" ]]; then
      should_enable_cloudflared=1
    fi
    ;;
esac

if (( should_enable_cloudflared )); then
  if [[ -z "${cf_tunnel_token}" ]]; then
    echo "PROPERTYQUARRY_ENABLE_CLOUDFLARED requires PROPERTYQUARRY_CF_TUNNEL_TOKEN for a dedicated PropertyQuarry tunnel." >&2
    exit 2
  fi
  if [[ ! -f "${cloudflared_compose_file}" ]]; then
    echo "Cloudflare overlay not found: ${cloudflared_compose_file}" >&2
    exit 2
  fi
  DC+=(-f "${cloudflared_compose_file}")
fi

api_service="${PROPERTYQUARRY_API_SERVICE:-$(effective_env_value PROPERTYQUARRY_API_SERVICE)}"
scheduler_service="${PROPERTYQUARRY_SCHEDULER_SERVICE:-$(effective_env_value PROPERTYQUARRY_SCHEDULER_SERVICE)}"
render_service="${PROPERTYQUARRY_RENDER_SERVICE:-$(effective_env_value PROPERTYQUARRY_RENDER_SERVICE)}"
db_service="${PROPERTYQUARRY_DB_SERVICE:-$(effective_env_value PROPERTYQUARRY_DB_SERVICE)}"
api_service="${api_service:-propertyquarry-api}"
scheduler_service="${scheduler_service:-propertyquarry-scheduler}"
render_service="${render_service:-propertyquarry-render-tools}"
db_service="${db_service:-propertyquarry-db}"
api_container_name="${PROPERTYQUARRY_API_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_API_CONTAINER_NAME)}"
scheduler_container_name="${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME)}"
render_container_name="${PROPERTYQUARRY_RENDER_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_RENDER_CONTAINER_NAME)}"
db_container_name="${PROPERTYQUARRY_DB_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_DB_CONTAINER_NAME)}"
cloudflared_container_name="${PROPERTYQUARRY_CLOUDFLARED_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_CLOUDFLARED_CONTAINER_NAME)}"
api_container_name="${api_container_name:-propertyquarry-api}"
scheduler_container_name="${scheduler_container_name:-propertyquarry-scheduler}"
render_container_name="${render_container_name:-propertyquarry-render-tools}"
db_container_name="${db_container_name:-propertyquarry-db-live}"
cloudflared_container_name="${cloudflared_container_name:-propertyquarry-cloudflared}"

port_owners="$(
  docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
    | awk -v port="${host_port}" 'index($0, ":" port "->") > 0 { print $1 }' \
    | sort -u
)"
if [[ -n "${port_owners}" ]]; then
  allowed_owner=0
  while IFS= read -r owner; do
    [[ -z "${owner}" ]] && continue
    if [[ "${owner}" == "${api_service}" || "${owner}" == "${api_container_name}" || "${owner}" == "propertyquarry-api" ]]; then
      allowed_owner=1
    else
      echo "EA_HOST_PORT=${host_port} is already published by container ${owner}." >&2
      echo "Set EA_HOST_PORT to a free port, or stop the conflicting container before deploy." >&2
      exit 2
    fi
  done <<<"${port_owners}"
  [[ "${allowed_owner}" == "1" ]] || true
elif command -v ss >/dev/null 2>&1 && ss -H -ltn "sport = :${host_port}" | grep -q .; then
  echo "EA_HOST_PORT=${host_port} is already in use by a non-Compose listener." >&2
  echo "Set EA_HOST_PORT to a free port before deploy." >&2
  exit 2
fi

if [[ "${PREFLIGHT_ONLY}" == "1" ]]; then
  echo "ok: PropertyQuarry deploy preflight"
  exit 0
fi

container_id_for_service() {
  local service="$1"
  local container_name="$2"
  local cid=""
  if [[ -n "${container_name}" ]]; then
    cid="$(docker ps -q --filter "name=^/${container_name}$" 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -z "${cid}" && "${container_name}" != "${service}" ]]; then
    cid="$(docker ps -q --filter "name=^/${service}$" 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -z "${cid}" ]]; then
    cid="$("${DC[@]}" ps -q "${service}" 2>/dev/null || true)"
  fi
  printf '%s' "${cid}"
}

container_state_line() {
  local cid="$1"
  docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || true
}

print_service_logs() {
  local service="$1"
  echo "Recent logs for ${service}:" >&2
  "${DC[@]}" logs --tail=80 "${service}" >&2 || true
}

max_thread_nice_for_pid() {
  local host_pid="$1"
  local max_nice=""
  local nice_value
  while IFS= read -r nice_value; do
    nice_value="$(printf '%s' "${nice_value}" | tr -d '[:space:]')"
    if [[ -n "${nice_value}" && "${nice_value}" =~ ^-?[0-9]+$ ]]; then
      if [[ -z "${max_nice}" ]] || (( nice_value > max_nice )); then
        max_nice="${nice_value}"
      fi
    fi
  done < <(timeout 3 ps -T -o ni= -p "${host_pid}" 2>/dev/null || true)
  if [[ -z "${max_nice}" ]]; then
    max_nice="$(timeout 3 ps -o ni= -p "${host_pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  fi
  printf '%s' "${max_nice}"
}

main_process_nice_for_pid() {
  local host_pid="$1"
  timeout 3 ps -o ni= -p "${host_pid}" 2>/dev/null | tr -d '[:space:]' || true
}

process_cgroup_for_pid() {
  local host_pid="$1"
  cat "/proc/${host_pid}/cgroup" 2>/dev/null || true
}

configured_runtime_cgroup_path() {
  local parent
  parent="$(effective_env_value PROPERTYQUARRY_RUNTIME_CGROUP_PARENT)"
  parent="${parent:-system.slice}"
  parent="${parent#/}"
  printf '/sys/fs/cgroup/%s/cgroup.procs' "${parent}"
}

move_process_to_configured_cgroup_if_needed() {
  local host_pid="$1"
  local cgroup_line="$2"
  local target
  if ! printf '%s\n' "${cgroup_line}" | grep -Eiq 'lowprio|background'; then
    return 0
  fi
  if [[ "$(id -u)" != "0" ]]; then
    return 1
  fi
  target="$(configured_runtime_cgroup_path)"
  if [[ ! -w "${target}" ]]; then
    return 1
  fi
  printf '%s\n' "${host_pid}" >"${target}" 2>/dev/null || return 1
  return 0
}

renice_process_threads_to_zero() {
  local host_pid="$1"
  local tid
  renice -n 0 -p "${host_pid}" >/dev/null || true
  while IFS= read -r tid; do
    tid="$(printf '%s' "${tid}" | tr -d '[:space:]')"
    if [[ -n "${tid}" && "${tid}" =~ ^[0-9]+$ ]]; then
      renice -n 0 -p "${tid}" >/dev/null || true
    fi
  done < <(timeout 3 ps -T -o tid= -p "${host_pid}" 2>/dev/null || true)
}

correct_service_runtime_priority_if_needed() {
  local service="$1"
  local container_name="$2"
  local max_nice="${3:-10}"
  local cid host_pid main_nice thread_nice strict_thread_nice strict_runtime_nice
  strict_thread_nice="$(effective_env_value PROPERTYQUARRY_DEPLOY_STRICT_THREAD_NICE)"
  strict_runtime_nice="$(effective_env_value PROPERTYQUARRY_DEPLOY_STRICT_RUNTIME_NICE)"
  cid="$(container_id_for_service "${service}" "${container_name}")"
  if [[ -z "${cid}" ]]; then
    return 0
  fi
  host_pid="$(docker inspect -f '{{.State.Pid}}' "${cid}" 2>/dev/null || true)"
  if [[ -z "${host_pid}" || "${host_pid}" == "0" ]]; then
    return 0
  fi
  local cgroup_line=""
  cgroup_line="$(process_cgroup_for_pid "${host_pid}")"
  move_process_to_configured_cgroup_if_needed "${host_pid}" "${cgroup_line}" || true
  main_nice="$(main_process_nice_for_pid "${host_pid}")"
  if [[ -z "${main_nice}" || ! "${main_nice}" =~ ^-?[0-9]+$ ]]; then
    return 0
  fi
  thread_nice="$(max_thread_nice_for_pid "${host_pid}")"
  if [[ -z "${thread_nice}" || ! "${thread_nice}" =~ ^-?[0-9]+$ ]]; then
    thread_nice="${main_nice}"
  fi
  if (( main_nice > max_nice || thread_nice > max_nice )) && [[ "$(id -u)" == "0" ]]; then
    if (( main_nice > max_nice )) || env_truthy "${strict_thread_nice}"; then
      echo "${service} started with host nice main=${main_nice} max_thread=${thread_nice}; correcting all runtime threads to nice 0." >&2
    fi
    renice_process_threads_to_zero "${host_pid}"
  fi
}

wait_for_service_ready() {
  local service="$1"
  local container_name="$2"
  local deadline=$((SECONDS + 180))
  local last_state=""
  while (( SECONDS < deadline )); do
    local cid
    cid="$(container_id_for_service "${service}" "${container_name}")"
    if [[ -n "${cid}" ]]; then
      correct_service_runtime_priority_if_needed "${service}" "${container_name}" "${max_runtime_nice:-10}"
      last_state="$(container_state_line "${cid}")"
      local status="${last_state%%|*}"
      local health="${last_state##*|}"
      if [[ "${status}" == "exited" || "${status}" == "dead" ]]; then
        echo "${service} exited during deploy." >&2
        print_service_logs "${service}"
        exit 1
      fi
      if [[ "${health}" == "healthy" || ( "${health}" == "none" && "${status}" == "running" ) ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  echo "${service} did not become healthy in time. Last state: ${last_state:-unknown}" >&2
  print_service_logs "${service}"
  exit 1
}

assert_service_runtime_priority() {
  local service="$1"
  local container_name="$2"
  local max_nice="${3:-10}"
  local cid=""
  local host_pid=""
  local main_nice=""
  local thread_nice=""
  local cgroup_line=""
  local priority_attempt=""
  cid="$(container_id_for_service "${service}" "${container_name}")"
  if [[ -z "${cid}" ]]; then
    echo "Could not resolve container for ${service} while checking runtime priority." >&2
    exit 1
  fi
  host_pid="$(docker inspect -f '{{.State.Pid}}' "${cid}" 2>/dev/null || true)"
  if [[ -z "${host_pid}" || "${host_pid}" == "0" ]]; then
    echo "Could not resolve host PID for ${service} while checking runtime priority." >&2
    exit 1
  fi
  cgroup_line="$(process_cgroup_for_pid "${host_pid}")"
  if printf '%s\n' "${cgroup_line}" | grep -Eiq 'lowprio|background'; then
    if [[ "$(id -u)" == "0" ]] && move_process_to_configured_cgroup_if_needed "${host_pid}" "${cgroup_line}"; then
      sleep 1
      cgroup_line="$(process_cgroup_for_pid "${host_pid}")"
    fi
    if printf '%s\n' "${cgroup_line}" | grep -Eiq 'lowprio|background'; then
      echo "${service} is running in a low-priority host cgroup:" >&2
      printf '%s\n' "${cgroup_line}" >&2
      echo "Set PROPERTYQUARRY_RUNTIME_CGROUP_PARENT=system.slice or another normal-priority slice before deploy." >&2
      exit 1
    fi
  fi
  for priority_attempt in 1 2 3 4 5; do
    main_nice="$(main_process_nice_for_pid "${host_pid}")"
    if [[ -z "${main_nice}" || ! "${main_nice}" =~ ^-?[0-9]+$ ]]; then
      echo "Could not read host thread nice value for ${service} pid ${host_pid}." >&2
      exit 1
    fi
    thread_nice="$(max_thread_nice_for_pid "${host_pid}")"
    if [[ -z "${thread_nice}" || ! "${thread_nice}" =~ ^-?[0-9]+$ ]]; then
      thread_nice="${main_nice}"
    fi
    if (( main_nice <= max_nice && thread_nice <= max_nice )); then
      break
    fi
    if [[ "$(id -u)" == "0" ]]; then
      if [[ "${priority_attempt}" == "1" ]]; then
        echo "${service} started with host nice main=${main_nice} max_thread=${thread_nice}; correcting all runtime threads to nice 0." >&2
      fi
      renice_process_threads_to_zero "${host_pid}"
      sleep 1
      main_nice="$(main_process_nice_for_pid "${host_pid}")"
      thread_nice="$(max_thread_nice_for_pid "${host_pid}")"
      if [[ -z "${thread_nice}" || ! "${thread_nice}" =~ ^-?[0-9]+$ ]]; then
        thread_nice="${main_nice}"
      fi
    else
      break
    fi
  done
  if (( main_nice > max_nice )); then
    echo "${service} host nice stayed at ${main_nice}, above allowed ${max_nice}, after correction." >&2
    echo "Web runtime would be CPU-starved under load; deploy is not production-clean." >&2
    exit 1
  fi
  if (( thread_nice > max_nice )); then
    echo "${service} has a runtime thread at nice ${thread_nice}, above allowed ${max_nice}, after correction." >&2
    exit 1
  fi
}

settle_runtime_priorities() {
  local attempts="${1:-3}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    correct_service_runtime_priority_if_needed "${api_service}" "${api_container_name}" "${max_runtime_nice}"
    correct_service_runtime_priority_if_needed "${scheduler_service}" "${scheduler_container_name}" "${max_runtime_nice}"
    correct_service_runtime_priority_if_needed "${render_service}" "${render_container_name}" "${max_runtime_nice}"
    if (( attempt < attempts )); then
      sleep 1
    fi
  done
  assert_service_runtime_priority "${api_service}" "${api_container_name}" "${max_runtime_nice}"
  assert_service_runtime_priority "${scheduler_service}" "${scheduler_container_name}" "${max_runtime_nice}"
  assert_service_runtime_priority "${render_service}" "${render_container_name}" "${max_runtime_nice}"
}

max_runtime_nice="$(effective_env_value PROPERTYQUARRY_DEPLOY_MAX_RUNTIME_NICE)"
max_runtime_nice="${max_runtime_nice:-10}"

"${DC[@]}" build "${api_service}" "${render_service}"
"${DC[@]}" up -d --remove-orphans "${db_service}"
wait_for_service_ready "${db_service}" "${db_container_name}"
"${DC[@]}" up -d --no-deps --force-recreate "${api_service}"
wait_for_service_ready "${api_service}" "${api_container_name}"
"${DC[@]}" up -d --no-deps --force-recreate "${scheduler_service}"
wait_for_service_ready "${scheduler_service}" "${scheduler_container_name}"
"${DC[@]}" up -d --no-deps --force-recreate "${render_service}"
wait_for_service_ready "${render_service}" "${render_container_name}"
if (( should_enable_cloudflared )); then
  "${DC[@]}" up -d --no-deps --force-recreate "${cloudflared_container_name}" 2>/dev/null || "${DC[@]}" up -d --no-deps --force-recreate propertyquarry-cloudflared 2>/dev/null || true
fi
settle_runtime_priorities 4

wait_for_service_ready "${db_service}" "${db_container_name}"
wait_for_service_ready "${api_service}" "${api_container_name}"
wait_for_service_ready "${scheduler_service}" "${scheduler_container_name}"
wait_for_service_ready "${render_service}" "${render_container_name}"
settle_runtime_priorities 3

base_url="$(effective_env_value PROPERTYQUARRY_DEPLOY_BASE_URL)"
base_url="${base_url:-http://localhost:${host_port}}"
base_url="${base_url%/}"

live_smoke_principal_id="$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_PRINCIPAL_ID)"
live_smoke_principal_id="${live_smoke_principal_id:-$(effective_env_value EA_PRINCIPAL_ID)}"
live_smoke_principal_id="${live_smoke_principal_id:-$(effective_env_value EA_TELEGRAM_DEFAULT_PRINCIPAL_ID)}"
live_smoke_principal_id="${live_smoke_principal_id:-pq-live-smoke}"
live_smoke_plan_label="$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL)"
live_smoke_plan_label="${live_smoke_plan_label:-Agent}"
live_smoke_country_code="$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE)"
live_smoke_country_code="${live_smoke_country_code:-AT}"
live_mobile_smoke_principal_id="$(effective_env_value PROPERTYQUARRY_LIVE_MOBILE_SMOKE_PRINCIPAL_ID)"
live_mobile_smoke_principal_id="${live_mobile_smoke_principal_id:-$(effective_env_value PROPERTYQUARRY_LIVE_PRINCIPAL_ID)}"
live_mobile_smoke_principal_id="${live_mobile_smoke_principal_id:-${live_smoke_principal_id}}"
live_market_scope_principal_id="$(effective_env_value PROPERTYQUARRY_LIVE_MARKET_SCOPE_PRINCIPAL_ID)"
live_market_scope_principal_id="${live_market_scope_principal_id:-${live_smoke_principal_id}}"
live_provider_smoke_principal_id="$(effective_env_value PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID)"
live_provider_smoke_principal_id="${live_provider_smoke_principal_id:-${live_smoke_principal_id}}"
live_presentation_e2e_principal_id="$(effective_env_value PROPERTYQUARRY_LIVE_PRESENTATION_E2E_PRINCIPAL_ID)"
live_presentation_e2e_principal_id="${live_presentation_e2e_principal_id:-${live_smoke_principal_id}}"

wait_for_http_ready() {
  local deadline=$((SECONDS + 120))
  local body=""
  while (( SECONDS < deadline )); do
    body="$(curl -sS --connect-timeout 2 --max-time 8 "${base_url}/health/ready" 2>/dev/null || true)"
    if printf '%s' "${body}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
      return 0
    fi
    sleep 2
  done
  echo "PropertyQuarry did not report ready at ${base_url}/health/ready." >&2
  print_service_logs "${api_service}"
  exit 1
}

curl -fsS --connect-timeout 2 --max-time 8 "${base_url}/health" >/dev/null
wait_for_http_ready

restart_existing_cloudflared_tunnel() {
  local cid=""
  cid="$(docker ps -q --filter "name=^/${cloudflared_container_name}$" 2>/dev/null | head -n 1 || true)"
  if [[ -z "${cid}" ]]; then
    return 0
  fi
  docker restart "${cid}" >/dev/null
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    local status
    status="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || true)"
    if [[ "${status}" == "running" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Cloudflare tunnel ${cloudflared_container_name} did not restart cleanly after API deploy." >&2
  docker logs --tail=80 "${cloudflared_container_name}" >&2 2>/dev/null || true
  exit 1
}

restart_existing_cloudflared_tunnel

bootstrap_billing_edge_worker() {
  local mode="$1"
  local lower_mode
  lower_mode="$(printf '%s' "${mode}" | tr '[:upper:]' '[:lower:]')"
  case "${lower_mode}" in
    0|false|no|off|disabled)
      return 0
      ;;
  esac
  if [[ -z "${bd_billing_url}" ]]; then
    return 0
  fi
  local worker_payload
  if ! worker_payload="$(
    BILLING_URL="${bd_billing_url}" \
    BILLING_DNS_TARGET="${bd_billing_dns_target}" \
    BILLING_FALLBACK_URLS="${bd_billing_fallback_urls}" \
    "${deploy_python_bin}" - <<'PY'
import json
import os
import urllib.parse

def host(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return str(parsed.hostname or "").strip().lower()

billing_url = str(os.getenv("BILLING_URL") or "").strip()
dns_target = str(os.getenv("BILLING_DNS_TARGET") or "").strip().lower().rstrip(".")
fallbacks = [item.strip() for item in str(os.getenv("BILLING_FALLBACK_URLS") or "").split(",") if item.strip()]
billing_host = host(billing_url)
target_host = dns_target or ""
if not target_host:
    for candidate in fallbacks:
        candidate_host = host(candidate)
        if candidate_host and candidate_host != billing_host:
            target_host = candidate_host
            break
print(json.dumps({"billing_host": billing_host, "target_host": target_host}))
PY
  )"; then
    if env_truthy "${lower_mode}"; then
      echo "Could not derive the billing worker host/target pair." >&2
      exit 1
    fi
    echo "Warning: could not derive the billing worker host/target pair." >&2
    return 0
  fi
  local billing_host=""
  local target_host=""
  billing_host="$("${deploy_python_bin}" - "${worker_payload}" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
print(str(payload.get("billing_host") or "").strip())
PY
)"
  target_host="$("${deploy_python_bin}" - "${worker_payload}" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
print(str(payload.get("target_host") or "").strip())
PY
)"
  if [[ -z "${billing_host}" || -z "${target_host}" ]]; then
    if env_truthy "${lower_mode}"; then
      echo "Billing worker bootstrap requires both a public billing host and an upstream billing target host." >&2
      exit 1
    fi
    echo "Warning: billing worker bootstrap skipped because the public host or upstream target host is missing." >&2
    return 0
  fi
  local worker_receipt="${deploy_tmp_dir}/propertyquarry_billing_edge_worker.json"
  local bridge_path="/sso/propertyquarry"
  if [[ -n "${bd_bridge_url}" ]]; then
    local parsed_bridge_path
    parsed_bridge_path="$(
      BRIDGE_URL="${bd_bridge_url}" "${deploy_python_bin}" - <<'PY'
import os
import urllib.parse
raw = str(os.getenv("BRIDGE_URL") or "").strip()
parsed = urllib.parse.urlparse(raw)
path = str(parsed.path or "").strip()
print(path or "/sso/propertyquarry")
PY
    )"
    bridge_path="${parsed_bridge_path:-/sso/propertyquarry}"
  fi
  local worker_timeout_seconds
  worker_timeout_seconds="$(effective_env_value PROPERTYQUARRY_BILLING_WORKER_BOOTSTRAP_TIMEOUT_SECONDS)"
  worker_timeout_seconds="${worker_timeout_seconds:-120}"
  if ! timeout --kill-after=10s "${worker_timeout_seconds}s" "${deploy_python_bin}" scripts/bootstrap_billing_handoff_worker.py \
    --host "${billing_host}" \
    --target-host "${target_host}" \
    --pricing-url "${property_public_base_url%/}/pricing" \
    --property-origin "${property_public_base_url}" \
    --bridge-path "${bridge_path}" >"${worker_receipt}"; then
    if env_truthy "${lower_mode}"; then
      echo "PropertyQuarry billing worker bootstrap failed." >&2
      cat "${worker_receipt}" >&2 2>/dev/null || true
      exit 1
    fi
    echo "Warning: PropertyQuarry billing worker bootstrap failed." >&2
    cat "${worker_receipt}" >&2 2>/dev/null || true
    return 0
  fi
}

bootstrap_billing_edge_worker "${bd_bootstrap_edge}"

core_probe_timeout_seconds="${PROPERTYQUARRY_DEPLOY_CORE_PROBE_TIMEOUT_SECONDS:-20}"
version_json="$(curl -fsS --connect-timeout 2 --max-time "${core_probe_timeout_seconds}" "${base_url}/version")"
if ! printf '%s' "${version_json}" | grep -q '"storage_backend"[[:space:]]*:[[:space:]]*"postgres"'; then
  echo "Expected /version to report storage_backend=postgres; got: ${version_json}" >&2
  exit 1
fi
release_manifest_check="$(
  "${deploy_python_bin}" - "${version_json}" "${release_commit_sha}" "${release_public_origin%/}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_commit = str(sys.argv[2] or "").strip()
expected_origin = str(sys.argv[3] or "").strip().rstrip("/")
failures = []
if payload.get("release_manifest_status") != "complete":
    failures.append(f"release_manifest_status={payload.get('release_manifest_status')!r}")
if expected_commit and str(payload.get("release_commit_sha") or "").strip() != expected_commit:
    failures.append(
        "release_commit_sha="
        + repr(payload.get("release_commit_sha"))
        + " expected="
        + repr(expected_commit)
    )
if expected_origin and str(payload.get("release_public_origin") or "").strip().rstrip("/") != expected_origin:
    failures.append(
        "release_public_origin="
        + repr(payload.get("release_public_origin"))
        + " expected="
        + repr(expected_origin)
    )
if failures:
    print("; ".join(failures))
    raise SystemExit(1)
print("ok")
PY
)" || {
  echo "Expected /version to expose the authoritative PropertyQuarry release manifest for this deploy." >&2
  printf '%s\n' "${release_manifest_check}" >&2
  printf '%s\n' "${version_json}" >&2
  exit 1
}

landing_html="$(curl -fsS --connect-timeout 2 --max-time "${core_probe_timeout_seconds}" "${base_url}/")"
if [[ "${landing_html}" != *PropertyQuarry* ]]; then
  echo "Landing page probe did not find PropertyQuarry branding." >&2
  exit 1
fi

settle_runtime_priorities 2

app_status="$(curl -sS --connect-timeout 2 --max-time "${core_probe_timeout_seconds}" -o "${deploy_tmp_dir}/propertyquarry_deploy_app_probe.html" -w '%{http_code}' "${base_url}/app/properties" || true)"
case "${app_status}" in
  401|302|303) ;;
  *)
    echo "Expected /app/properties to require auth; got HTTP ${app_status}." >&2
    exit 1
    ;;
esac

public_smoke_receipt="${deploy_tmp_dir}/propertyquarry_deploy_public_smoke.json"
public_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_PUBLIC_SMOKE_TIMEOUT_SECONDS:-8}"
settle_runtime_priorities 2
if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_live_public_smoke.py \
  --base-url "${base_url}" \
  --timeout-seconds "${public_smoke_timeout_seconds}" \
  --write "${public_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry public route smoke failed." >&2
  cat "${public_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
mkdir -p _completion/smoke
cp "${public_smoke_receipt}" _completion/smoke/property-live-public-latest.json

authenticated_smoke_receipt="${deploy_tmp_dir}/propertyquarry_deploy_authenticated_smoke.json"
authenticated_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_AUTHENTICATED_SMOKE_TIMEOUT_SECONDS:-20}"
settle_runtime_priorities 2
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_live_authenticated_smoke.py \
  --base-url "${base_url}" \
  --principal-id "${live_smoke_principal_id}" \
  --expected-plan-label "${live_smoke_plan_label}" \
  --country-code "${live_smoke_country_code}" \
  --timeout-seconds "${authenticated_smoke_timeout_seconds}" >"${authenticated_smoke_receipt}"; then
  echo "PropertyQuarry authenticated route smoke failed." >&2
  cat "${authenticated_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${authenticated_smoke_receipt}" _completion/smoke/property-live-authenticated-latest.json

mobile_smoke_receipt="${deploy_tmp_dir}/propertyquarry_deploy_mobile_smoke.json"
mobile_smoke_timeout_ms="${PROPERTYQUARRY_DEPLOY_MOBILE_SMOKE_TIMEOUT_MS:-30000}"
mobile_smoke_process_timeout_seconds="${PROPERTYQUARRY_DEPLOY_MOBILE_SMOKE_PROCESS_TIMEOUT_SECONDS:-300}"
configured_mobile_research_detail_route="$(effective_env_value PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE)"
mobile_research_detail_route="${configured_mobile_research_detail_route:-/app/research/perf-candidate-1020?run_id=run-gold-mobile}"
mobile_seed_research_detail_fixture="$(effective_env_value PROPERTYQUARRY_DEPLOY_MOBILE_SEED_RESEARCH_DETAIL_FIXTURE)"
if [[ -z "${configured_mobile_research_detail_route}" && -z "${mobile_seed_research_detail_fixture}" ]]; then
  mobile_seed_research_detail_fixture=1
fi
mobile_smoke_research_args=(--routes "/app/properties,/app/search,/app/shortlist,/app/agents,/app/alerts,/app/account,/app/billing,/app/settings/google,/app/settings/access,/app/settings/usage,/app/settings/support,/app/settings/trust,/app/settings/invitations,/app/research,/app/properties/packets,${mobile_research_detail_route}" --require-research-detail)
if env_truthy "${mobile_seed_research_detail_fixture}"; then
  mobile_smoke_research_args=(--seed-research-detail-fixture)
fi
rm -f "${mobile_smoke_receipt}"
settle_runtime_priorities 3
if ! timeout "${mobile_smoke_process_timeout_seconds}" env EA_API_TOKEN="${api_token}" PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_live_mobile_surface_smoke.py \
  --base-url "${base_url}" \
  --host-header "propertyquarry.com" \
  --api-token "${api_token}" \
  --principal-id "${live_mobile_smoke_principal_id}" \
  "${mobile_smoke_research_args[@]}" \
  --timeout-ms "${mobile_smoke_timeout_ms}" \
  --write "${mobile_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry mobile surface smoke failed." >&2
  cat "${mobile_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${mobile_smoke_receipt}" _completion/smoke/property-live-mobile-surface-latest.json
settle_runtime_priorities 2

map_preview_gate_receipt="${deploy_tmp_dir}/propertyquarry_deploy_map_preview_flagship.json"
map_preview_gate_timeout_seconds="${PROPERTYQUARRY_DEPLOY_MAP_PREVIEW_GATE_TIMEOUT_SECONDS:-60}"
settle_runtime_priorities 2
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_map_preview_flagship_gate.py \
  --base-url "${base_url}" \
  --host-header "propertyquarry.com" \
  --principal-id "${live_mobile_smoke_principal_id}" \
  --timeout-seconds "${map_preview_gate_timeout_seconds}" \
  --write "${map_preview_gate_receipt}" >/dev/null; then
  echo "PropertyQuarry map preview flagship gate failed." >&2
  cat "${map_preview_gate_receipt}" >&2 2>/dev/null || true
  cp "${map_preview_gate_receipt}" _completion/smoke/property-live-map-preview-flagship-latest.json 2>/dev/null || true
  exit 1
fi
cp "${map_preview_gate_receipt}" _completion/smoke/property-live-map-preview-flagship-latest.json
settle_runtime_priorities 2

market_scope_smoke_receipt="${deploy_tmp_dir}/propertyquarry_deploy_market_scope_smoke.json"
market_scope_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_MARKET_SCOPE_SMOKE_TIMEOUT_SECONDS:-8}"
settle_runtime_priorities 2
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_live_market_scope_smoke.py \
  --base-url "${base_url}" \
  --principal-id "${live_market_scope_principal_id}" \
  --timeout-seconds "${market_scope_smoke_timeout_seconds}" \
  --write "${market_scope_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry market-scope smoke failed." >&2
  cat "${market_scope_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${market_scope_smoke_receipt}" _completion/smoke/property-live-market-scope-latest.json

provider_smoke_receipt="${deploy_tmp_dir}/propertyquarry_deploy_provider_smoke.json"
provider_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_PROVIDER_SMOKE_TIMEOUT_SECONDS:-20}"
provider_search_run_timeout_seconds="${PROPERTYQUARRY_DEPLOY_PROVIDER_SEARCH_RUN_TIMEOUT_SECONDS:-60}"
provider_smoke_mode="catalog"
provider_smoke_scope_label="catalog"
provider_country_scope_raw="$(effective_env_value PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES)"
provider_country_scope_slug=""
provider_country_args=()
provider_smoke_scope_args=(--all-search-ready-countries)
if [[ -n "${provider_country_scope_raw}" ]]; then
  IFS=',' read -r -a provider_country_scope_items <<<"${provider_country_scope_raw}"
  normalized_provider_countries=()
  for raw_country in "${provider_country_scope_items[@]}"; do
    country_code="$(printf '%s' "${raw_country}" | tr '[:lower:]' '[:upper:]' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    if [[ -z "${country_code}" ]]; then
      continue
    fi
    if [[ ! "${country_code}" =~ ^[A-Z]{2}$ ]]; then
      echo "PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES must be a comma-separated list of two-letter country codes; got ${country_code}." >&2
      exit 2
    fi
    normalized_provider_countries+=("${country_code}")
    provider_country_args+=(--country "${country_code}")
  done
  if (( ${#normalized_provider_countries[@]} == 0 )); then
    echo "PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES was set but no valid country codes were found." >&2
    exit 2
  fi
  provider_country_scope_slug="$(printf '%s\n' "${normalized_provider_countries[@]}" | tr '[:upper:]' '[:lower:]' | paste -sd '-' -)"
  provider_smoke_scope_args=("${provider_country_args[@]}")
fi
provider_e2e_receipt="_completion/provider_smoke/production-e2e-provider-matrix-current.json"
if [[ -n "${provider_country_scope_slug}" ]]; then
  provider_e2e_receipt="_completion/provider_smoke/production-e2e-provider-matrix-${provider_country_scope_slug}-current.json"
fi
if env_truthy "$(effective_env_value PROPERTYQUARRY_DEPLOY_PROVIDER_E2E)"; then
  provider_smoke_mode="e2e"
  mkdir -p _completion/provider_smoke
  provider_smoke_scope_label="${provider_country_scope_slug:-all-search-ready}"
  settle_runtime_priorities 2
  if ! EA_API_TOKEN="${api_token}" \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${live_provider_smoke_principal_id}" \
    PYTHONPATH=ea "${deploy_python_bin}" scripts/property_live_provider_smoke.py \
    --base-url "${base_url}" \
    "${provider_smoke_scope_args[@]}" \
    --execute-search-matrix \
    --resume-from "${provider_e2e_receipt}" \
    --timeout-seconds "${provider_smoke_timeout_seconds}" \
    --search-run-timeout-seconds "${provider_search_run_timeout_seconds}" \
    --write "${provider_smoke_receipt}" >/dev/null; then
    echo "PropertyQuarry provider E2E matrix failed." >&2
    cat "${provider_smoke_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
  cp "${provider_smoke_receipt}" "${provider_e2e_receipt}"
else
  provider_smoke_scope_label="${provider_country_scope_slug:-catalog}"
  settle_runtime_priorities 2
  if ! EA_API_TOKEN="${api_token}" \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${live_provider_smoke_principal_id}" \
    PYTHONPATH=ea "${deploy_python_bin}" scripts/property_live_provider_smoke.py \
    --base-url "${base_url}" \
    "${provider_country_args[@]}" \
    --timeout-seconds "${provider_smoke_timeout_seconds}" \
    --write "${provider_smoke_receipt}" >/dev/null; then
    echo "PropertyQuarry provider catalog smoke failed." >&2
    cat "${provider_smoke_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
fi
if [[ "${provider_smoke_mode}" == "e2e" ]]; then
  cp "${provider_smoke_receipt}" _completion/smoke/property-live-provider-latest.json
else
  cp "${provider_smoke_receipt}" _completion/smoke/property-live-provider-catalog-latest.json
  if [[ -f "${provider_e2e_receipt}" ]]; then
    cp "${provider_e2e_receipt}" _completion/smoke/property-live-provider-latest.json
  else
    cp "${provider_smoke_receipt}" _completion/smoke/property-live-provider-latest.json
  fi
fi

presentation_e2e_mode="$(effective_env_value PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E)"
presentation_e2e_mode="${presentation_e2e_mode:-auto}"
presentation_e2e_mode="$(printf '%s' "${presentation_e2e_mode}" | tr '[:upper:]' '[:lower:]')"
run_presentation_e2e=0
if env_truthy "${presentation_e2e_mode}"; then
  run_presentation_e2e=1
elif [[ "${presentation_e2e_mode}" == "auto" && "${provider_smoke_mode}" == "e2e" ]]; then
  run_presentation_e2e=1
elif [[ "${presentation_e2e_mode}" != "0" && "${presentation_e2e_mode}" != "false" && "${presentation_e2e_mode}" != "no" && "${presentation_e2e_mode}" != "off" && "${presentation_e2e_mode}" != "auto" ]]; then
  echo "PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E must be 1, 0, or auto; got ${presentation_e2e_mode}." >&2
  exit 2
fi

service_generated_reconstruction_receipt="_completion/tours/property-service-generated-reconstruction-current.json"
service_generated_reconstruction_slug="${PROPERTYQUARRY_SERVICE_GENERATED_RECONSTRUCTION_SMOKE_SLUG:-service-generated-reconstruction-deploy-$(date +%Y%m%d%H%M%S)}"
service_generated_reconstruction_verified_for_walkthrough=0

if (( run_presentation_e2e == 1 )); then
  presentation_e2e_receipt="${deploy_tmp_dir}/propertyquarry_deploy_presentation_e2e.json"
  presentation_provider_matrix_args=()
  if [[ "${provider_smoke_mode}" == "e2e" ]]; then
    presentation_provider_matrix_args+=(--require-provider-matrix)
  fi
  settle_runtime_priorities 2
  if ! EA_API_TOKEN="${api_token}" \
    PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_live_presentation_e2e.py \
    --base-url "${base_url}" \
    --host-header "propertyquarry.com" \
    --principal-id "${live_presentation_e2e_principal_id}" \
    --provider-receipt _completion/smoke/property-live-provider-latest.json \
    "${presentation_provider_matrix_args[@]}" \
    --write "${presentation_e2e_receipt}" >/dev/null; then
    echo "PropertyQuarry live presentation E2E failed." >&2
    cat "${presentation_e2e_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
  cp "${presentation_e2e_receipt}" _completion/smoke/property-live-presentation-e2e-latest.json

  browser_3d_gate_receipt="${deploy_tmp_dir}/propertyquarry_deploy_3d_browser_gate.json"
  settle_runtime_priorities 2
  if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_3d_browser_gate.py \
    --base-url "${base_url}" \
    --host-header "propertyquarry.com" \
    --screenshots-dir _completion/smoke/property-live-3d-browser-gate-screenshots \
    --write "${browser_3d_gate_receipt}" >/dev/null; then
    echo "PropertyQuarry browser-rendered 3D gate failed." >&2
    cat "${browser_3d_gate_receipt}" >&2 2>/dev/null || true
    cp "${browser_3d_gate_receipt}" _completion/smoke/property-live-3d-browser-gate-latest.json 2>/dev/null || true
    exit 1
  fi
  cp "${browser_3d_gate_receipt}" _completion/smoke/property-live-3d-browser-gate-latest.json

  settle_runtime_priorities 2
  if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/property_service_generated_reconstruction_smoke.py \
    --container "${api_container_name}" \
    --slug "${service_generated_reconstruction_slug}" \
    --public-base-url "${base_url}" \
    --host-header "propertyquarry.com" \
    --require-public-contract \
    --require-browser-shell \
    --write "${service_generated_reconstruction_receipt}" >/dev/null; then
    echo "PropertyQuarry service generated-reconstruction smoke failed." >&2
    cat "${service_generated_reconstruction_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
  service_generated_reconstruction_verified_for_walkthrough=1

  walkthrough_quality_receipt="${deploy_tmp_dir}/propertyquarry_deploy_walkthrough_quality.json"
  walkthrough_quality_tour_root="${PROPERTYQUARRY_WALKTHROUGH_QUALITY_TOUR_ROOT:-state/public_property_tours}"
  walkthrough_quality_process_timeout_seconds="${PROPERTYQUARRY_WALKTHROUGH_QUALITY_PROCESS_TIMEOUT_SECONDS:-180}"
  walkthrough_quality_ffprobe_timeout_seconds="${PROPERTYQUARRY_WALKTHROUGH_QUALITY_FFPROBE_TIMEOUT_SECONDS:-20}"
  walkthrough_quality_frame_sample_timeout_seconds="${PROPERTYQUARRY_WALKTHROUGH_QUALITY_FRAME_SAMPLE_TIMEOUT_SECONDS:-45}"
  settle_runtime_priorities 2
  if ! PYTHONPATH=ea timeout "${walkthrough_quality_process_timeout_seconds}" "${deploy_python_bin}" scripts/propertyquarry_walkthrough_quality_gate.py \
    --tour-root "${walkthrough_quality_tour_root}" \
    --service-generated-reconstruction-receipt "${service_generated_reconstruction_receipt}" \
    --ffprobe-timeout-seconds "${walkthrough_quality_ffprobe_timeout_seconds}" \
    --frame-sample-timeout-seconds "${walkthrough_quality_frame_sample_timeout_seconds}" \
    --write "${walkthrough_quality_receipt}" >/dev/null; then
    echo "PropertyQuarry walkthrough quality gate failed." >&2
    cat "${walkthrough_quality_receipt}" >&2 2>/dev/null || true
    cp "${walkthrough_quality_receipt}" _completion/smoke/property-live-walkthrough-quality-latest.json 2>/dev/null || true
    exit 1
  fi
  cp "${walkthrough_quality_receipt}" _completion/smoke/property-live-walkthrough-quality-latest.json
fi

tour_control_receipt="_completion/tours/property-tour-controls-live-container-current.json"
export_discovery_receipt="_completion/tours/property-tour-export-discovery-full-current.json"
import_manifest_receipt="_completion/property_tour_exports/import-manifest-current.json"
scene_video_receipt="_completion/scene_video_readiness/release-gate.json"
scene_video_verifier_receipt="_completion/scene_video_readiness/release-gate-verifier.json"
scene_video_runtime_status_receipt="_completion/scene_video_readiness/runtime-status.json"
scene_video_refresh_packet="_completion/scene_video_readiness/provider-refresh-packet.json"
scene_video_refresh_packet_verifier="_completion/scene_video_readiness/provider-refresh-packet-verifier.json"
id_austria_receipt="_completion/id_austria/ID_AUSTRIA_PROVIDER_VERIFICATION.generated.json"
tour_control_release_gate_receipt="_completion/property_tour_controls/release-gate.json"
tour_export_discovery_container_receipt="/tmp/property-tour-export-discovery-full-current.json"
tour_import_manifest_container_receipt="/data/artifacts/property-tour-import-manifest-current.json"
scene_video_container_receipt="/data/artifacts/property-scene-video-readiness-current.json"
scene_video_verifier_container_receipt="/data/artifacts/property-scene-video-readiness-verifier-current.json"
scene_video_runtime_status_container_receipt="/data/artifacts/property-scene-video-runtime-status-current.json"
scene_video_refresh_packet_container_receipt="/data/artifacts/property-scene-video-provider-refresh-packet-current.json"
scene_video_refresh_packet_verifier_container_receipt="/data/artifacts/property-scene-video-provider-refresh-packet-verifier-current.json"

mkdir -p _completion/tours _completion/property_tour_controls _completion/property_tour_exports _completion/id_austria _completion/scene_video_readiness _completion/property_gold_status
settle_runtime_priorities 2
if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/verify_property_tour_controls.py \
  --base-url "${base_url}" \
  --host-header "propertyquarry.com" \
  --live-probe \
  --write "${tour_control_receipt}" \
  --summary-only >/dev/null; then
  echo "PropertyQuarry live tour-control verification failed." >&2
  cat "${tour_control_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${tour_control_receipt}" "${tour_control_release_gate_receipt}"

if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/verify_id_austria_provider.py >/dev/null; then
  echo "PropertyQuarry ID Austria verification failed." >&2
  cat "${id_austria_receipt}" >&2 2>/dev/null || true
  exit 1
fi

if ! docker inspect "${api_container_name}" >/dev/null 2>&1; then
  echo "PropertyQuarry API container ${api_container_name} is not available for live tour-export proof refresh." >&2
  exit 1
fi

settle_runtime_priorities 2
if ! docker exec "${api_container_name}" python /app/scripts/discover_property_tour_exports.py \
  --drop-dir /data/incoming_property_tours \
  --public-tour-dir /data/public_property_tours \
  --write "${tour_export_discovery_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live export discovery failed." >&2
  docker exec "${api_container_name}" cat "${tour_export_discovery_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
docker cp "${api_container_name}:${tour_export_discovery_container_receipt}" "${export_discovery_receipt}" >/dev/null

settle_runtime_priorities 2
if ! docker exec --user root "${api_container_name}" python /app/scripts/materialize_property_tour_export_manifest.py \
  --tour-root /data/public_property_tours \
  --incoming-root /data/incoming_property_tours \
  --prepare-dirs \
  --write "${tour_import_manifest_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live tour import-manifest refresh failed." >&2
  docker exec "${api_container_name}" cat "${tour_import_manifest_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
docker cp "${api_container_name}:${tour_import_manifest_container_receipt}" "${import_manifest_receipt}" >/dev/null

if (( service_generated_reconstruction_verified_for_walkthrough != 1 )); then
  settle_runtime_priorities 2
  if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/property_service_generated_reconstruction_smoke.py \
    --container "${api_container_name}" \
    --slug "${service_generated_reconstruction_slug}" \
    --public-base-url "${base_url}" \
    --host-header "propertyquarry.com" \
    --require-public-contract \
    --require-browser-shell \
    --write "${service_generated_reconstruction_receipt}" >/dev/null; then
    echo "PropertyQuarry service generated-reconstruction smoke failed." >&2
    cat "${service_generated_reconstruction_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
fi

settle_runtime_priorities 2
if ! docker_exec_scene_video_python "${api_container_name}" /app/scripts/property_scene_video_readiness_report.py \
  --output "${scene_video_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live scene-video readiness refresh failed." >&2
  docker exec "${api_container_name}" cat "${scene_video_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
if ! docker_exec_scene_video_python "${api_container_name}" /app/scripts/verify_property_scene_video_readiness.py \
  --receipt "${scene_video_container_receipt}" \
  --output "${scene_video_verifier_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live scene-video readiness verifier failed." >&2
  docker exec "${api_container_name}" cat "${scene_video_verifier_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
if ! docker_exec_scene_video_python "${api_container_name}" /app/scripts/property_scene_video_runtime_status.py \
  --receipt "${scene_video_container_receipt}" \
  --output "${scene_video_runtime_status_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live scene-video runtime-status refresh failed." >&2
  docker exec "${api_container_name}" cat "${scene_video_runtime_status_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
if ! docker_exec_scene_video_python "${api_container_name}" /app/scripts/materialize_scene_video_provider_refresh_packet.py \
  --receipt "${scene_video_container_receipt}" \
  --output "${scene_video_refresh_packet_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live scene-video provider refresh-packet generation failed." >&2
  docker exec "${api_container_name}" cat "${scene_video_refresh_packet_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
if ! docker_exec_scene_video_python "${api_container_name}" /app/scripts/verify_scene_video_provider_refresh_packet.py \
  --packet "${scene_video_refresh_packet_container_receipt}" \
  --output "${scene_video_refresh_packet_verifier_container_receipt}" >/dev/null; then
  echo "PropertyQuarry live scene-video provider refresh-packet verifier failed." >&2
  docker exec "${api_container_name}" cat "${scene_video_refresh_packet_verifier_container_receipt}" >&2 2>/dev/null || true
  exit 1
fi
docker cp "${api_container_name}:${scene_video_container_receipt}" "${scene_video_receipt}" >/dev/null
docker cp "${api_container_name}:${scene_video_verifier_container_receipt}" "${scene_video_verifier_receipt}" >/dev/null
docker cp "${api_container_name}:${scene_video_runtime_status_container_receipt}" "${scene_video_runtime_status_receipt}" >/dev/null
docker cp "${api_container_name}:${scene_video_refresh_packet_container_receipt}" "${scene_video_refresh_packet}" >/dev/null
docker cp "${api_container_name}:${scene_video_refresh_packet_verifier_container_receipt}" "${scene_video_refresh_packet_verifier}" >/dev/null

scene_video_refresh_notification_principal_id="$(effective_env_value PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_PRINCIPAL_ID)"
scene_video_refresh_notification_principal_id="${scene_video_refresh_notification_principal_id:-${EA_PRINCIPAL_ID:-propertyquarry-operator}}"
scene_video_refresh_notification_base_url="$(effective_env_value PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_BASE_URL)"
scene_video_refresh_notification_base_url="${scene_video_refresh_notification_base_url:-https://propertyquarry.com}"
notification_prefer_container_runtime="$(effective_env_value PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME)"
notification_prefer_container_runtime="${notification_prefer_container_runtime:-1}"
scene_video_refresh_notification_state="$(effective_env_value PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_STATE)"
scene_video_refresh_notification_state="${scene_video_refresh_notification_state:-_completion/scene_video_readiness/provider-refresh-telegram-state.json}"
scene_video_refresh_notification_report="_completion/scene_video_readiness/provider-refresh-telegram-report.json"
scene_video_refresh_notification_enabled="$(effective_env_value PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED)"
scene_video_refresh_notification_enabled="${scene_video_refresh_notification_enabled:-0}"
case "${scene_video_refresh_notification_enabled,,}" in
  1|true|yes|y|on|enabled)
    if ! DATABASE_URL="${database_url}" \
      EA_STORAGE_BACKEND="${storage_backend}" \
      EA_TELEGRAM_BOT_REGISTRY_JSON="${telegram_bot_registry_json}" \
      EA_TELEGRAM_BOT_TOKEN="${telegram_bot_token}" \
      EA_TELEGRAM_BOT_HANDLE="${telegram_bot_handle}" \
      PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME="${notification_prefer_container_runtime}" \
      PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_notify_scene_video_provider_refresh.py \
        --packet "${scene_video_refresh_packet}" \
        --verifier "${scene_video_refresh_packet_verifier}" \
        --runtime-status "${scene_video_runtime_status_receipt}" \
        --state-file "${scene_video_refresh_notification_state}" \
        --principal-id "${scene_video_refresh_notification_principal_id}" \
        --base-url "${scene_video_refresh_notification_base_url}" \
        --write "${scene_video_refresh_notification_report}" >/dev/null; then
      echo "Warning: PropertyQuarry scene-video provider refresh notification script failed." >&2
      cat "${scene_video_refresh_notification_report}" >&2 2>/dev/null || true
    fi
    ;;
  *)
    mkdir -p "$(dirname "${scene_video_refresh_notification_report}")"
    printf '{"status":"skipped","reason":"PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED_not_set"}\n' > "${scene_video_refresh_notification_report}"
    ;;
esac

settle_runtime_priorities 4

release_hygiene_receipt="_completion/release_hygiene/property-release-hygiene-latest.json"
if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/check_property_release_hygiene.py \
  --write "${release_hygiene_receipt}" >/dev/null; then
  echo "PropertyQuarry release-hygiene refresh failed." >&2
  cat "${release_hygiene_receipt}" >&2 2>/dev/null || true
  exit 1
fi

gold_status_receipt="_completion/property_gold_status/release-gate.json"
legacy_gold_status_receipt="_completion/propertyquarry-gold-status-latest.json"
if ! PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_gold_status.py \
  --tour-control-receipt "${tour_control_receipt}" \
  --export-discovery-receipt "${export_discovery_receipt}" \
  --import-manifest-receipt "${import_manifest_receipt}" \
  --release-hygiene-receipt "${release_hygiene_receipt}" \
  --provider-matrix-receipt _completion/smoke/property-live-provider-latest.json \
  --live-mobile-receipt _completion/smoke/property-live-mobile-surface-latest.json \
  --public-smoke-receipt _completion/smoke/property-live-public-latest.json \
  --authenticated-smoke-receipt _completion/smoke/property-live-authenticated-latest.json \
  --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json \
  --map-preview-flagship-receipt _completion/smoke/property-live-map-preview-flagship-latest.json \
  --browser-3d-gate-receipt _completion/smoke/property-live-3d-browser-gate-latest.json \
  --service-generated-reconstruction-receipt "${service_generated_reconstruction_receipt}" \
  --walkthrough-quality-receipt _completion/smoke/property-live-walkthrough-quality-latest.json \
  --scene-video-readiness-receipt "${scene_video_receipt}" \
  --scene-video-readiness-verifier-receipt "${scene_video_verifier_receipt}" \
  --scene-video-runtime-status-receipt "${scene_video_runtime_status_receipt}" \
  --scene-video-provider-refresh-packet "${scene_video_refresh_packet}" \
  --scene-video-provider-refresh-packet-verifier-receipt "${scene_video_refresh_packet_verifier}" \
  --id-austria-receipt "${id_austria_receipt}" \
  --write "${gold_status_receipt}" \
  --fail-on-blocked >/dev/null; then
  echo "PropertyQuarry gold-status verification failed." >&2
  cat "${gold_status_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${gold_status_receipt}" "${legacy_gold_status_receipt}"

gold_notification_principal_id="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID)"
gold_notification_principal_id="${gold_notification_principal_id:-${EA_PRINCIPAL_ID:-propertyquarry-operator}}"
gold_notification_base_url="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL)"
gold_notification_base_url="${gold_notification_base_url:-https://propertyquarry.com}"
gold_notification_state="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_STATE)"
gold_notification_state="${gold_notification_state:-_completion/propertyquarry-gold-notification-state.json}"
gold_notification_report="_completion/property_gold_status/telegram-notify-report.json"
gold_notification_enabled="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED)"
gold_notification_enabled="${gold_notification_enabled:-0}"
case "${gold_notification_enabled,,}" in
  1|true|yes|y|on|enabled)
    if ! DATABASE_URL="${database_url}" \
      EA_STORAGE_BACKEND="${storage_backend}" \
      EA_TELEGRAM_BOT_REGISTRY_JSON="${telegram_bot_registry_json}" \
      EA_TELEGRAM_BOT_TOKEN="${telegram_bot_token}" \
      EA_TELEGRAM_BOT_HANDLE="${telegram_bot_handle}" \
      PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME="${notification_prefer_container_runtime}" \
      PYTHONPATH=ea "${deploy_python_bin}" scripts/propertyquarry_notify_gold_status.py \
        --receipt "${gold_status_receipt}" \
        --state-file "${gold_notification_state}" \
        --principal-id "${gold_notification_principal_id}" \
        --base-url "${gold_notification_base_url}" \
        --write "${gold_notification_report}" >/dev/null; then
      echo "Warning: PropertyQuarry gold notification script failed." >&2
      cat "${gold_notification_report}" >&2 2>/dev/null || true
    fi
    ;;
  *)
    mkdir -p "$(dirname "${gold_notification_report}")"
    printf '{"status":"skipped","reason":"PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED_not_set"}\n' > "${gold_notification_report}"
    ;;
esac

echo "ok: PropertyQuarry deployed at ${base_url} (${provider_smoke_mode} provider verification: ${provider_smoke_scope_label})"
