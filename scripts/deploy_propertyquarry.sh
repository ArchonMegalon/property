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
  - starts docker-compose.property.yml and waits for API, scheduler, and DB health
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
  PROPERTYQUARRY_DEPLOY_PROVIDER_E2E
                                  1 enables the full all-search-ready provider matrix with strict and
                                  soft-filter dispatch/readback checks after deploy. Default 0 keeps the
                                  lighter provider-catalog smoke.
  PROPERTYQUARRY_DEPLOY_PRESENTATION_E2E
                                  1 requires the composed live presentation E2E, 0 skips it, auto runs it
                                  only when PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1. Default auto. When this
                                  runs, browser-rendered 3D controls and walkthrough quality are also hard gates.
  PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES
                                  Optional comma-separated country list for focused provider verification,
                                  for example AT,DE,CR. When set with PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1,
                                  the deploy runs the strict/soft targeted matrix only for those countries
                                  instead of every search-ready country.
  PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID
                                  Telegram notification principal for a green gold receipt.
                                  Defaults to EA_PRINCIPAL_ID or propertyquarry-operator.
  PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL
                                  Public URL included in the gold notification. Defaults to https://propertyquarry.com.
  PROPERTYQUARRY_GOLD_NOTIFICATION_STATE
                                  Send-once state file for green gold notifications.
  PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BOOTSTRAP_EDGE
                                  1|0|auto. When billing.propertyquarry.com is configured, keeps the
                                  Cloudflare billing worker aligned with the current billing host and
                                  bridge path. Default auto.
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

if ! [[ "${host_port}" =~ ^[0-9]+$ ]] || (( host_port < 1 || host_port > 65535 )); then
  echo "EA_HOST_PORT must be a TCP port between 1 and 65535; got ${host_port}." >&2
  exit 2
fi

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
db_service="${PROPERTYQUARRY_DB_SERVICE:-$(effective_env_value PROPERTYQUARRY_DB_SERVICE)}"
api_service="${api_service:-propertyquarry-api}"
scheduler_service="${scheduler_service:-propertyquarry-scheduler}"
db_service="${db_service:-propertyquarry-db}"
api_container_name="${PROPERTYQUARRY_API_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_API_CONTAINER_NAME)}"
scheduler_container_name="${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME)}"
db_container_name="${PROPERTYQUARRY_DB_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_DB_CONTAINER_NAME)}"
cloudflared_container_name="${PROPERTYQUARRY_CLOUDFLARED_CONTAINER_NAME:-$(effective_env_value PROPERTYQUARRY_CLOUDFLARED_CONTAINER_NAME)}"
api_container_name="${api_container_name:-propertyquarry-api}"
scheduler_container_name="${scheduler_container_name:-propertyquarry-scheduler}"
db_container_name="${db_container_name:-propertyquarry-db}"
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

"${DC[@]}" up -d --build --remove-orphans

container_id_for_service() {
  local service="$1"
  local container_name="$2"
  local cid=""
  cid="$("${DC[@]}" ps -q "${service}" 2>/dev/null || true)"
  if [[ -z "${cid}" ]]; then
    cid="$(docker ps -q --filter "name=^/${container_name}$" 2>/dev/null | head -n 1 || true)"
  fi
  if [[ -z "${cid}" && "${container_name}" != "${service}" ]]; then
    cid="$(docker ps -q --filter "name=^/${service}$" 2>/dev/null | head -n 1 || true)"
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

wait_for_service_ready() {
  local service="$1"
  local container_name="$2"
  local deadline=$((SECONDS + 180))
  local last_state=""
  while (( SECONDS < deadline )); do
    local cid
    cid="$(container_id_for_service "${service}" "${container_name}")"
    if [[ -n "${cid}" ]]; then
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

wait_for_service_ready "${db_service}" "${db_container_name}"
wait_for_service_ready "${api_service}" "${api_container_name}"
wait_for_service_ready "${scheduler_service}" "${scheduler_container_name}"

base_url="$(effective_env_value PROPERTYQUARRY_DEPLOY_BASE_URL)"
base_url="${base_url:-http://localhost:${host_port}}"
base_url="${base_url%/}"

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
    python3 - <<'PY'
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
  billing_host="$(python3 - <<'PY' "${worker_payload}"
import json, sys
payload = json.loads(sys.argv[1])
print(str(payload.get("billing_host") or "").strip())
PY
)"
  target_host="$(python3 - <<'PY' "${worker_payload}"
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
  local worker_receipt="/tmp/propertyquarry_billing_edge_worker.json"
  local bridge_path="/sso/propertyquarry"
  if [[ -n "${bd_bridge_url}" ]]; then
    local parsed_bridge_path
    parsed_bridge_path="$(
      BRIDGE_URL="${bd_bridge_url}" python3 - <<'PY'
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
  if ! python3 scripts/bootstrap_billing_handoff_worker.py \
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

version_json="$(curl -fsS --connect-timeout 2 --max-time 8 "${base_url}/version")"
if ! printf '%s' "${version_json}" | grep -q '"storage_backend"[[:space:]]*:[[:space:]]*"postgres"'; then
  echo "Expected /version to report storage_backend=postgres; got: ${version_json}" >&2
  exit 1
fi

landing_html="$(curl -fsS --connect-timeout 2 --max-time 8 "${base_url}/")"
if [[ "${landing_html}" != *PropertyQuarry* ]]; then
  echo "Landing page probe did not find PropertyQuarry branding." >&2
  exit 1
fi

app_status="$(curl -sS --connect-timeout 2 --max-time 8 -o /tmp/propertyquarry_deploy_app_probe.html -w '%{http_code}' "${base_url}/app/properties" || true)"
case "${app_status}" in
  401|302|303) ;;
  *)
    echo "Expected /app/properties to require auth; got HTTP ${app_status}." >&2
    exit 1
    ;;
esac

public_smoke_receipt="/tmp/propertyquarry_deploy_public_smoke.json"
public_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_PUBLIC_SMOKE_TIMEOUT_SECONDS:-8}"
if ! PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py \
  --base-url "${base_url}" \
  --timeout-seconds "${public_smoke_timeout_seconds}" \
  --write "${public_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry public route smoke failed." >&2
  cat "${public_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
mkdir -p _completion/smoke
cp "${public_smoke_receipt}" _completion/smoke/property-live-public-latest.json

authenticated_smoke_receipt="/tmp/propertyquarry_deploy_authenticated_smoke.json"
authenticated_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_AUTHENTICATED_SMOKE_TIMEOUT_SECONDS:-20}"
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py \
  --base-url "${base_url}" \
  --principal-id "${EA_PRINCIPAL_ID:-pq-live-smoke}" \
  --expected-plan-label "${PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL:-Agent}" \
  --country-code "${PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE:-AT}" \
  --timeout-seconds "${authenticated_smoke_timeout_seconds}" >"${authenticated_smoke_receipt}"; then
  echo "PropertyQuarry authenticated route smoke failed." >&2
  cat "${authenticated_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${authenticated_smoke_receipt}" _completion/smoke/property-live-authenticated-latest.json

mobile_smoke_receipt="/tmp/propertyquarry_deploy_mobile_smoke.json"
mobile_smoke_timeout_ms="${PROPERTYQUARRY_DEPLOY_MOBILE_SMOKE_TIMEOUT_MS:-30000}"
mobile_smoke_principal_id="${PROPERTYQUARRY_LIVE_MOBILE_SMOKE_PRINCIPAL_ID:-pq-live-mobile-smoke}"
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea python3 scripts/propertyquarry_live_mobile_surface_smoke.py \
  --base-url "${base_url}" \
  --host-header "propertyquarry.com" \
  --api-token "${api_token}" \
  --principal-id "${mobile_smoke_principal_id}" \
  --seed-research-detail-fixture \
  --timeout-ms "${mobile_smoke_timeout_ms}" \
  --write "${mobile_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry mobile surface smoke failed." >&2
  cat "${mobile_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${mobile_smoke_receipt}" _completion/smoke/property-live-mobile-surface-latest.json

map_preview_gate_receipt="/tmp/propertyquarry_deploy_map_preview_flagship.json"
map_preview_gate_timeout_seconds="${PROPERTYQUARRY_DEPLOY_MAP_PREVIEW_GATE_TIMEOUT_SECONDS:-12}"
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea python3 scripts/propertyquarry_map_preview_flagship_gate.py \
  --base-url "${base_url}" \
  --host-header "propertyquarry.com" \
  --principal-id "${mobile_smoke_principal_id}" \
  --timeout-seconds "${map_preview_gate_timeout_seconds}" \
  --write "${map_preview_gate_receipt}" >/dev/null; then
  echo "PropertyQuarry map preview flagship gate failed." >&2
  cat "${map_preview_gate_receipt}" >&2 2>/dev/null || true
  cp "${map_preview_gate_receipt}" _completion/smoke/property-live-map-preview-flagship-latest.json 2>/dev/null || true
  exit 1
fi
cp "${map_preview_gate_receipt}" _completion/smoke/property-live-map-preview-flagship-latest.json

market_scope_smoke_receipt="/tmp/propertyquarry_deploy_market_scope_smoke.json"
market_scope_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_MARKET_SCOPE_SMOKE_TIMEOUT_SECONDS:-8}"
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea python3 scripts/propertyquarry_live_market_scope_smoke.py \
  --base-url "${base_url}" \
  --principal-id "${EA_PRINCIPAL_ID:-pq-live-market-scope}" \
  --timeout-seconds "${market_scope_smoke_timeout_seconds}" \
  --write "${market_scope_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry market-scope smoke failed." >&2
  cat "${market_scope_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
cp "${market_scope_smoke_receipt}" _completion/smoke/property-live-market-scope-latest.json

provider_smoke_receipt="/tmp/propertyquarry_deploy_provider_smoke.json"
provider_smoke_timeout_seconds="${PROPERTYQUARRY_DEPLOY_PROVIDER_SMOKE_TIMEOUT_SECONDS:-20}"
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
  if ! EA_API_TOKEN="${api_token}" \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${EA_PRINCIPAL_ID:-pq-live-provider-smoke}" \
    PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py \
    --base-url "${base_url}" \
    "${provider_smoke_scope_args[@]}" \
    --execute-search-matrix \
    --resume-from "${provider_e2e_receipt}" \
    --timeout-seconds "${provider_smoke_timeout_seconds}" \
    --write "${provider_smoke_receipt}" >/dev/null; then
    echo "PropertyQuarry provider E2E matrix failed." >&2
    cat "${provider_smoke_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
  cp "${provider_smoke_receipt}" "${provider_e2e_receipt}"
else
  provider_smoke_scope_label="${provider_country_scope_slug:-catalog}"
  if ! EA_API_TOKEN="${api_token}" \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
    PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${EA_PRINCIPAL_ID:-pq-live-provider-smoke}" \
    PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py \
    --base-url "${base_url}" \
    "${provider_country_args[@]}" \
    --timeout-seconds "${provider_smoke_timeout_seconds}" \
    --write "${provider_smoke_receipt}" >/dev/null; then
    echo "PropertyQuarry provider catalog smoke failed." >&2
    cat "${provider_smoke_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
fi
cp "${provider_smoke_receipt}" _completion/smoke/property-live-provider-latest.json

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

if (( run_presentation_e2e == 1 )); then
  presentation_e2e_receipt="/tmp/propertyquarry_deploy_presentation_e2e.json"
  presentation_provider_matrix_args=()
  if [[ "${provider_smoke_mode}" == "e2e" ]]; then
    presentation_provider_matrix_args+=(--require-provider-matrix)
  fi
  if ! EA_API_TOKEN="${api_token}" \
    PYTHONPATH=ea python3 scripts/propertyquarry_live_presentation_e2e.py \
    --base-url "${base_url}" \
    --host-header "propertyquarry.com" \
    --principal-id "${EA_PRINCIPAL_ID:-pq-live-presentation-e2e}" \
    --provider-receipt _completion/smoke/property-live-provider-latest.json \
    "${presentation_provider_matrix_args[@]}" \
    --write "${presentation_e2e_receipt}" >/dev/null; then
    echo "PropertyQuarry live presentation E2E failed." >&2
    cat "${presentation_e2e_receipt}" >&2 2>/dev/null || true
    exit 1
  fi
  cp "${presentation_e2e_receipt}" _completion/smoke/property-live-presentation-e2e-latest.json

  browser_3d_gate_receipt="/tmp/propertyquarry_deploy_3d_browser_gate.json"
  if ! PYTHONPATH=ea python3 scripts/propertyquarry_3d_browser_gate.py \
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

  walkthrough_quality_receipt="/tmp/propertyquarry_deploy_walkthrough_quality.json"
  if ! PYTHONPATH=ea python3 scripts/propertyquarry_walkthrough_quality_gate.py \
    --tour-root state/public_property_tours \
    --write "${walkthrough_quality_receipt}" >/dev/null; then
    echo "PropertyQuarry walkthrough quality gate failed." >&2
    cat "${walkthrough_quality_receipt}" >&2 2>/dev/null || true
    cp "${walkthrough_quality_receipt}" _completion/smoke/property-live-walkthrough-quality-latest.json 2>/dev/null || true
    exit 1
  fi
  cp "${walkthrough_quality_receipt}" _completion/smoke/property-live-walkthrough-quality-latest.json
fi

gold_status_receipt="_completion/property_gold_status/release-gate.json"
legacy_gold_status_receipt="_completion/propertyquarry-gold-status-latest.json"
PYTHONPATH=ea python3 scripts/propertyquarry_gold_status.py \
  --live-mobile-receipt _completion/smoke/property-live-mobile-surface-latest.json \
  --public-smoke-receipt _completion/smoke/property-live-public-latest.json \
  --authenticated-smoke-receipt _completion/smoke/property-live-authenticated-latest.json \
  --billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json \
  --map-preview-flagship-receipt _completion/smoke/property-live-map-preview-flagship-latest.json \
  --browser-3d-gate-receipt _completion/smoke/property-live-3d-browser-gate-latest.json \
  --walkthrough-quality-receipt _completion/smoke/property-live-walkthrough-quality-latest.json \
  --write "${gold_status_receipt}" >/dev/null || true
cp "${gold_status_receipt}" "${legacy_gold_status_receipt}"

gold_notification_principal_id="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID)"
gold_notification_principal_id="${gold_notification_principal_id:-${EA_PRINCIPAL_ID:-propertyquarry-operator}}"
gold_notification_base_url="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL)"
gold_notification_base_url="${gold_notification_base_url:-https://propertyquarry.com}"
gold_notification_state="$(effective_env_value PROPERTYQUARRY_GOLD_NOTIFICATION_STATE)"
gold_notification_state="${gold_notification_state:-_completion/propertyquarry-gold-notification-state.json}"
gold_notification_report="_completion/property_gold_status/telegram-notify-report.json"
if ! DATABASE_URL="${database_url}" \
  EA_STORAGE_BACKEND="${storage_backend}" \
  EA_TELEGRAM_BOT_REGISTRY_JSON="${telegram_bot_registry_json}" \
  EA_TELEGRAM_BOT_TOKEN="${telegram_bot_token}" \
  EA_TELEGRAM_BOT_HANDLE="${telegram_bot_handle}" \
  PYTHONPATH=ea python3 scripts/propertyquarry_notify_gold_status.py \
    --receipt "${gold_status_receipt}" \
    --state-file "${gold_notification_state}" \
    --principal-id "${gold_notification_principal_id}" \
    --base-url "${gold_notification_base_url}" \
    --write "${gold_notification_report}" >/dev/null; then
  echo "Warning: PropertyQuarry gold notification script failed." >&2
  cat "${gold_notification_report}" >&2 2>/dev/null || true
fi

echo "ok: PropertyQuarry deployed at ${base_url} (${provider_smoke_mode} provider verification: ${provider_smoke_scope_label})"
