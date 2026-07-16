#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

smoke_suffix="${PROPERTYQUARRY_POSTGRES_SMOKE_SUFFIX:-$$}"
if ! [[ "${smoke_suffix}" =~ ^[a-z0-9_-]+$ ]]; then
  echo "PROPERTYQUARRY_POSTGRES_SMOKE_SUFFIX must use only lowercase letters, digits, underscores, or hyphens" >&2
  exit 2
fi
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-propertyquarry-postgres-smoke-${smoke_suffix}}"
export PROPERTYQUARRY_API_CONTAINER_NAME="${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-postgres-smoke-api-${smoke_suffix}}"
export PROPERTYQUARRY_DB_CONTAINER_NAME="${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-postgres-smoke-db-${smoke_suffix}}"
export PROPERTYQUARRY_MIGRATE_CONTAINER_NAME="${PROPERTYQUARRY_MIGRATE_CONTAINER_NAME:-propertyquarry-postgres-smoke-migrate-${smoke_suffix}}"

run_browser_e2e=0
for arg in "$@"; do
  case "${arg}" in
    --browser-e2e)
      run_browser_e2e=1
      ;;
    --help|-h)
      cat <<'USAGE'
Usage: bash scripts/smoke_property_postgres.sh [--browser-e2e]

Boots the production-mode PropertyQuarry compose app against PostgreSQL and
verifies its public brand, authentication boundary, and storage backend.

Options:
  --browser-e2e  Also run the network-served PostgreSQL Playwright contract
                 with an internal-only ephemeral CI session.
USAGE
      exit 0
      ;;
    *)
      echo "unknown argument: ${arg}" >&2
      exit 2
      ;;
  esac
done

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f docker-compose.property.yml)
else
  DC=(docker-compose -f docker-compose.property.yml)
fi

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-propertyquarry_ci_postgres}"
export EA_HOST_PORT="${EA_HOST_PORT:-$((20000 + ($$ % 20000)))}"
export EA_API_TOKEN="${EA_API_TOKEN:-propertyquarry-ci-api-token}"
export PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN="${PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN:-propertyquarry-ci-render-bridge-token}"
base="http://localhost:${EA_HOST_PORT}"
api_container="${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"
created_env=0
env_had_file=0
env_backup=""
browser_session_dir=""
browser_session_file=""
container_browser_session_file="/tmp/propertyquarry-postgres-browser-session.json"

if [[ ! -f "${ROOT}/.env" ]]; then
  cp "${ROOT}/.env.example" "${ROOT}/.env"
  chmod 600 "${ROOT}/.env"
  created_env=1
else
  env_had_file=1
  env_backup="$(mktemp)"
  cp "${ROOT}/.env" "${env_backup}"
fi

cleanup() {
  "${DC[@]}" down -v >/dev/null 2>&1 || true
  if [[ -n "${browser_session_file}" ]]; then
    rm -f -- "${browser_session_file}"
  fi
  if [[ -n "${browser_session_dir}" ]]; then
    rmdir -- "${browser_session_dir}" 2>/dev/null || true
  fi
  if [[ "${env_had_file}" == "1" && -n "${env_backup}" && -f "${env_backup}" ]]; then
    cp "${env_backup}" "${ROOT}/.env"
    rm -f "${env_backup}"
  fi
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${ROOT}/.env"
  fi
}
trap cleanup EXIT

set_env_value() {
  local key="$1"
  local value="$2"
  local line=""
  local replaced=0
  local temp_file=""
  if ! [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    echo "invalid env key: ${key}" >&2
    return 2
  fi
  if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
    echo "multiline env values are not supported: ${key}" >&2
    return 2
  fi
  temp_file="$(mktemp "${ROOT}/.env.propertyquarry.XXXXXX")"
  chmod 600 "${temp_file}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == "${key}="* ]]; then
      if [[ "${replaced}" == "0" ]]; then
        printf '%s=%s\n' "${key}" "${value}" >> "${temp_file}"
        replaced=1
      fi
      continue
    fi
    printf '%s\n' "${line}" >> "${temp_file}"
  done < "${ROOT}/.env"
  if [[ "${replaced}" == "0" ]]; then
    printf '%s=%s\n' "${key}" "${value}" >> "${temp_file}"
  fi
  mv -- "${temp_file}" "${ROOT}/.env"
}

set_env_value "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD}"
set_env_value "DATABASE_URL" ""
set_env_value "EA_RUNTIME_MODE" "prod"
set_env_value "EA_STORAGE_BACKEND" "postgres"
set_env_value "EA_ALLOW_LOOPBACK_NO_AUTH" "0"
set_env_value "EA_API_TOKEN" "${EA_API_TOKEN}"
set_env_value "EA_SIGNING_SECRET" "propertyquarry-ci-signing-secret"
set_env_value "EMAILIT_API_KEY" ""
set_env_value "PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN" "${PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN}"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_SIDE_SURFACES" "0"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_RESULTS" "0"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS" "0"
set_env_value "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES" "0"

echo "== property-postgres-smoke: boot property compose =="
"${DC[@]}" up -d --build propertyquarry-db propertyquarry-api

echo "== property-postgres-smoke: wait for readiness =="
expected_ready_reason="$(PYTHONPATH=ea python3 -c 'from app.product.property_search_schema import LATEST_PROPERTY_SEARCH_SCHEMA_VERSION; print(f"postgres_ready:property_search_schema_v{LATEST_PROPERTY_SEARCH_SCHEMA_VERSION}")')"
ready_reason=""
for _ in $(seq 1 90); do
  ready_json="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/health/ready" 2>/dev/null || true)"
  ready_reason="$(python3 -c 'import json,sys
raw=(sys.argv[1] if len(sys.argv)>1 else "").strip()
try:
    payload=json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
print(str(payload.get("reason") or "")) if isinstance(payload, dict) else print("")' "${ready_json}")"
  if [[ "${ready_reason}" == "${expected_ready_reason}" ]]; then
    break
  fi
  sleep 1
done

if [[ "${ready_reason}" != "${expected_ready_reason}" ]]; then
  echo "expected ${expected_ready_reason}, got ${ready_reason:-empty}" >&2
  docker logs --tail 160 "${api_container}" >&2 || true
  exit 31
fi

echo "== property-postgres-smoke: verify public brand and auth boundary =="
landing="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/")"
if ! grep -q "PropertyQuarry" <<<"${landing}"; then
  echo "landing page did not render PropertyQuarry branding" >&2
  exit 32
fi

app_code="$(curl -sS --connect-timeout 2 --max-time 5 -o /tmp/propertyquarry_app_probe.html -w '%{http_code}' "${base}/app/properties" || true)"
if [[ "${app_code}" != "401" && "${app_code}" != "303" ]]; then
  echo "expected authenticated app boundary, got HTTP ${app_code}" >&2
  cat /tmp/propertyquarry_app_probe.html >&2 || true
  exit 33
fi

version_json="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/version")"
storage_backend="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("storage_backend",""))' "${version_json}")"
if [[ "${storage_backend}" != "postgres" ]]; then
  echo "expected postgres storage backend, got ${storage_backend}" >&2
  exit 34
fi

echo "== property-postgres-smoke: verify production runtime posture =="
runtime_mode="$(docker exec "${api_container}" /bin/sh -lc 'printf %s "${EA_RUNTIME_MODE:-}"')"
runtime_storage="$(docker exec "${api_container}" /bin/sh -lc 'printf %s "${EA_STORAGE_BACKEND:-}"')"
loopback_no_auth="$(docker exec "${api_container}" /bin/sh -lc 'printf %s "${EA_ALLOW_LOOPBACK_NO_AUTH:-}"')"
legacy_runtime_surfaces="$(docker exec "${api_container}" /bin/sh -lc 'printf %s "${PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES:-}"')"
api_token_configured="$(docker exec "${api_container}" /bin/sh -lc 'if [ -n "${EA_API_TOKEN:-}" ]; then printf configured; fi')"
if [[ "${runtime_mode}" != "prod" || "${runtime_storage}" != "postgres" ]]; then
  echo "expected prod/postgres runtime posture, got mode=${runtime_mode:-empty} storage=${runtime_storage:-empty}" >&2
  exit 35
fi
if [[ "${loopback_no_auth}" != "0" || "${legacy_runtime_surfaces}" != "0" ]]; then
  echo "expected loopback auth and legacy runtime surfaces disabled, got loopback=${loopback_no_auth:-empty} legacy=${legacy_runtime_surfaces:-empty}" >&2
  exit 36
fi
if [[ "${api_token_configured}" != "configured" ]]; then
  echo "expected the production API token to be configured" >&2
  exit 37
fi

if [[ "${run_browser_e2e}" == "1" ]]; then
  echo "== property-postgres-smoke: network-served Playwright contract =="
  docker exec "${api_container}" rm -f -- "${container_browser_session_file}"
  docker exec \
    -e PROPERTYQUARRY_POSTGRES_BROWSER_E2E=1 \
    "${api_container}" \
    python /app/scripts/propertyquarry_postgres_browser_bootstrap.py \
    --write "${container_browser_session_file}" \
    > /dev/null
  browser_session_dir="$(mktemp -d)"
  browser_session_file="${browser_session_dir}/session.json"
  docker cp "${api_container}:${container_browser_session_file}" "${browser_session_file}" >/dev/null
  docker exec "${api_container}" rm -f -- "${container_browser_session_file}"
  chmod 600 "${browser_session_file}"
  PROPERTYQUARRY_POSTGRES_BROWSER_E2E=1 \
    PROPERTYQUARRY_POSTGRES_BROWSER_BASE_URL="${base}" \
    PROPERTYQUARRY_POSTGRES_BROWSER_EXPECTED_READY_REASON="${expected_ready_reason}" \
    PROPERTYQUARRY_POSTGRES_BROWSER_SESSION_FILE="${browser_session_file}" \
    PYTHONPATH=ea \
    python3 -m pytest -q tests/e2e/test_propertyquarry_postgres_browser.py -p no:cacheprovider
fi

echo "property-postgres-smoke complete"
