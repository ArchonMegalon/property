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
cf_access_team_domain="$(effective_env_value EA_CF_ACCESS_TEAM_DOMAIN)"
cf_access_aud="$(effective_env_value EA_CF_ACCESS_AUD)"
allow_loopback_no_auth="$(effective_env_value EA_ALLOW_LOOPBACK_NO_AUTH)"

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
if ! PYTHONPATH=ea python3 scripts/propertyquarry_live_public_smoke.py \
  --base-url "${base_url}" \
  --timeout-seconds 8 \
  --write "${public_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry public route smoke failed." >&2
  cat "${public_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi

authenticated_smoke_receipt="/tmp/propertyquarry_deploy_authenticated_smoke.json"
if ! EA_API_TOKEN="${api_token}" PYTHONPATH=ea python3 scripts/propertyquarry_live_authenticated_smoke.py \
  --base-url "${base_url}" \
  --principal-id "${EA_PRINCIPAL_ID:-cf-email:tibor.girschele@gmail.com}" \
  --expected-plan-label "${PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL:-Agent}" \
  --country-code "${PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE:-AT}" \
  --timeout-seconds 8 >"${authenticated_smoke_receipt}"; then
  echo "PropertyQuarry authenticated route smoke failed." >&2
  cat "${authenticated_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi
mkdir -p _completion/smoke
cp "${authenticated_smoke_receipt}" _completion/smoke/property-live-authenticated-latest.json

provider_smoke_receipt="/tmp/propertyquarry_deploy_provider_smoke.json"
if ! EA_API_TOKEN="${api_token}" \
  PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1 \
  PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0 \
  PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID="${EA_PRINCIPAL_ID:-cf-email:tibor.girschele@gmail.com}" \
  PYTHONPATH=ea python3 scripts/property_live_provider_smoke.py \
  --base-url "${base_url}" \
  --write "${provider_smoke_receipt}" >/dev/null; then
  echo "PropertyQuarry provider catalog smoke failed." >&2
  cat "${provider_smoke_receipt}" >&2 2>/dev/null || true
  exit 1
fi

echo "ok: PropertyQuarry deployed at ${base_url}"
