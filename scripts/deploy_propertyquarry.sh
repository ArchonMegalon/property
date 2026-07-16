#!/bin/bash -p
PATH=/usr/sbin:/usr/bin:/sbin:/bin
IFS=$' \t\n'
LANG=C
LC_ALL=C
builtin export PATH IFS LANG LC_ALL
builtin unset \
  BASH_ENV ENV CDPATH GLOBIGNORE \
  LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT GCONV_PATH \
  PYTHONPATH PYTHONHOME PERL5LIB RUBYLIB
# These Bash-generated variables are readonly; -p ignores inherited values and
# removing their export attribute prevents propagation to the controller.
builtin export -n SHELLOPTS BASHOPTS 2>/dev/null || :
builtin umask 077
set -euo pipefail

# Bash privileged-startup mode is required even though this process must stay
# unprivileged: it prevents BASH_ENV and exported functions from running before
# line 2. The fixed environment above uses only builtins.

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  builtin printf '%s\n' "Refusing sourced execution of the release handoff." >&2
  return 2
fi

# This checkout is an unprivileged handoff client. It never imports candidate
# Python, reads candidate receipts, opens Docker/PostgreSQL, starts a service,
# or switches traffic. Every production and disposable-candidate action lives
# in the independently installed release controller.

PROPERTYQUARRY_ENTRYPOINT_SOURCE="${BASH_SOURCE[0]}"
if [[ "${PROPERTYQUARRY_ENTRYPOINT_SOURCE}" != /* ]]; then
  PROPERTYQUARRY_ENTRYPOINT_SOURCE="${PWD}/${PROPERTYQUARRY_ENTRYPOINT_SOURCE}"
fi
PROPERTYQUARRY_ENTRYPOINT_DIRECTORY="${PROPERTYQUARRY_ENTRYPOINT_SOURCE%/*}"
if [[ "${PROPERTYQUARRY_ENTRYPOINT_DIRECTORY}" == "${PROPERTYQUARRY_ENTRYPOINT_SOURCE}" ]]; then
  PROPERTYQUARRY_ENTRYPOINT_DIRECTORY="${PWD}"
fi
APP_ROOT="${PROPERTYQUARRY_ENTRYPOINT_DIRECTORY%/*}"
[[ -n "${APP_ROOT}" ]] || APP_ROOT="/"
PREFLIGHT_ONLY=0

PROPERTYQUARRY_RELEASE_CONTROL_UID=0
PROPERTYQUARRY_RELEASE_CONTROL_GID=0
PROPERTYQUARRY_EXTERNAL_CONTROLLER_PATH="/usr/libexec/propertyquarry-release-control/propertyquarry-deploy-controller"
PROPERTYQUARRY_EXTERNAL_CONTROLLER_MANIFEST="/etc/propertyquarry/release-control/external-deploy-controller.v1.json"
PROPERTYQUARRY_EXTERNAL_CONTROLLER_PIN="/etc/propertyquarry/release-control/external-deploy-controller.sha256"
PROPERTYQUARRY_EXTERNAL_COMPOSE_PLAN="/etc/propertyquarry/release-control/deploy-compose-plan.v1.json"
PROPERTYQUARRY_EXTERNAL_DATABASE_POLICY="/etc/propertyquarry/release-control/database-fence-policy.v1.json"
PROPERTYQUARRY_EXTERNAL_DRAIN_KEYRING="/etc/propertyquarry/release-control/deploy-drain-keyring.v2.json"
PROPERTYQUARRY_EXTERNAL_OPERATOR_GATEWAY_TRUST="/etc/propertyquarry/operator-gateway-trust.v1.json"
PROPERTYQUARRY_EXTERNAL_MONITORING_TOPOLOGY="/etc/propertyquarry/monitoring-topology.v1.json"
PROPERTYQUARRY_EXTERNAL_MONITORING_TOOLS="/etc/propertyquarry/monitoring-tools.v1.json"

usage() {
  /usr/bin/cat <<'EOF'
Usage:
  # Read-only disposition (non-authorizing request):
  EA_RUNTIME_MODE=prod \
  PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST="${XDG_RUNTIME_DIR}/propertyquarry-deploy-preflight-request.json" \
    ./scripts/deploy_propertyquarry.sh --preflight-only

  # Mutating release (distinct fresh request):
  EA_RUNTIME_MODE=prod \
  PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST="${XDG_RUNTIME_DIR}/propertyquarry-deploy-run-request.json" \
    ./scripts/deploy_propertyquarry.sh

This checkout performs no deployment action itself. It opens the fixed,
root-controlled external controller, manifest and digest pin, a private
untrusted request transport, and the candidate directory; verifies file
identity and the controller hash; then replaces itself with the controller
through /proc/self/fd.

`--preflight-only` invokes the controller's read-only preflight operation. It
forbids containment, fence, journal, receipt, Docker, database, and traffic
mutation and must return an explicit disposition.

The controller—not this checkout—owns the fixed deploy lock, crash
reconciliation, canonical Compose plan, server-derived database identity,
durable role fence, migrations, evidence verification, immutable Cloudflared
image/config, promotion authorization, traffic, and external monotonic seals.

Environment consumed by this handoff is intentionally narrow:
  EA_RUNTIME_MODE
      prod|production for the production operation; dev|development|test|
      staging|candidate for a signed disposable-candidate operation.
  PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST
      Absolute path to an invoking-user-owned, single-link, mode-0400 request
      transport. It is untrusted input; only the installed controller may
      authenticate its signature, challenge, nonce, freshness, and authority.
      The signature must bind the exact operation. A preflight request cannot
      authorize mutation and must never be reused for a deploy run.

Caller-selected Compose files, Python interpreters, Docker contexts, database
URLs, tunnel tokens, public-tour volume paths, verifier paths, receipt outputs,
and trust/key paths are ignored or rejected.
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

propertyquarry_secure_root_directory() {
  local path="$1"
  local metadata=""
  local uid=""
  local mode=""
  if [[ -L "${path}" || ! -d "${path}" ]]; then
    echo "Release-control parent is missing, not a directory, or a symlink: ${path}" >&2
    return 1
  fi
  metadata="$(/usr/bin/stat -c '%u:%a' -- "${path}")" || return 1
  uid="${metadata%%:*}"
  mode="${metadata##*:}"
  if [[ "${uid}" != "${PROPERTYQUARRY_RELEASE_CONTROL_UID}" ]] || \
    (( (8#${mode} & 8#022) != 0 )); then
    echo "Release-control parent is not authority-owned and non-writable: ${path}" >&2
    return 1
  fi
}

propertyquarry_secure_parent_chain() {
  local current="${1%/*}"
  [[ -n "${current}" ]] || current="/"
  while :; do
    propertyquarry_secure_root_directory "${current}" || return 1
    [[ "${current}" == "/" ]] && return 0
    current="${current%/*}"
    [[ -n "${current}" ]] || current="/"
  done
}

propertyquarry_secure_external_file() {
  local path="$1"
  local required_mode="$2"
  local label="$3"
  local metadata=""
  if [[ -L "${path}" || ! -f "${path}" ]]; then
    echo "${label} is missing, not a regular file, or a symlink." >&2
    return 1
  fi
  metadata="$(/usr/bin/stat -c '%u:%g:%a:%h:%F' -- "${path}")" || return 1
  if [[ "${metadata}" != \
    "${PROPERTYQUARRY_RELEASE_CONTROL_UID}:${PROPERTYQUARRY_RELEASE_CONTROL_GID}:${required_mode}:1:regular file" ]]; then
    echo "${label} must be authority-owned, single-link, mode ${required_mode}, and regular." >&2
    return 1
  fi
}

propertyquarry_secure_request_transport() {
  local path="$1"
  local metadata=""
  local size=""
  if [[ -L "${path}" || ! -f "${path}" ]]; then
    echo "Signed request transport is missing, not a regular file, or a symlink." >&2
    return 1
  fi
  metadata="$(/usr/bin/stat -c '%u:%a:%h:%F' -- "${path}")" || return 1
  if [[ "${metadata}" != "${EUID}:400:1:regular file" ]]; then
    echo "Signed request transport must be invoking-user-owned, single-link, mode 0400, and regular." >&2
    return 1
  fi
  size="$(/usr/bin/stat -c '%s' -- "${path}")" || return 1
  if [[ ! "${size}" =~ ^[0-9]+$ ]] || (( size < 1 || size > 1048576 )); then
    echo "Signed request transport must contain between 1 byte and 1 MiB." >&2
    return 1
  fi
}

propertyquarry_open_verified_fd() {
  local path="$1"
  local descriptor_name="$2"
  local path_identity=""
  local fd_identity=""
  local descriptor=""
  exec {descriptor}<"${path}"
  printf -v "${descriptor_name}" '%s' "${descriptor}"
  path_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "${path}")"
  fd_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "/proc/self/fd/${descriptor}")"
  if [[ "${path_identity}" != "${fd_identity}" ]]; then
    echo "External handoff file changed while it was opened: ${path}" >&2
    return 1
  fi
}

propertyquarry_controller_pin_sha() {
  local pin_fd="$1"
  local pin_size=""
  local -a pin_lines=()
  pin_size="$(/usr/bin/stat -Lc '%s' -- "/proc/self/fd/${pin_fd}")"
  if [[ "${pin_size}" != "65" ]]; then
    echo "External controller digest pin must contain exactly one SHA-256 line." >&2
    return 1
  fi
  mapfile -t pin_lines < "/proc/self/fd/${pin_fd}"
  if [[ "${#pin_lines[@]}" != "1" || ! "${pin_lines[0]}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "External controller digest pin is invalid." >&2
    return 1
  fi
  printf '%s' "${pin_lines[0]}"
}

propertyquarry_exec_external_controller() {
  local requested_mode="${EA_RUNTIME_MODE:-prod}"
  local signed_request="${PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST:-}"
  local operation=""
  local controller_fd=""
  local manifest_fd=""
  local controller_pin_fd=""
  local request_fd=""
  local candidate_root_fd=""
  local controller_identity=""
  local manifest_identity=""
  local controller_pin_identity=""
  local request_identity=""
  local expected_controller_sha=""
  local actual_controller_sha=""
  local request_sha=""
  local controller_magic=""
  local mode_args=()

  requested_mode="${requested_mode,,}"
  case "${requested_mode}" in
    prod|production)
      operation="deploy-run"
      ;;
    dev|development|test|staging|candidate)
      operation="candidate-run"
      ;;
    *)
      echo "EA_RUNTIME_MODE must select production or a signed disposable-candidate mode." >&2
      return 2
      ;;
  esac
  if [[ "${PREFLIGHT_ONLY}" == "1" ]]; then
    operation="${operation%-run}-preflight"
    mode_args=(
      --read-only
      --forbid-containment
      --forbid-state-mutation
      --require-explicit-preflight-disposition
    )
  else
    mode_args=(
      --controller-owns-all-privileged-actions
      --contain-before-candidate-validation
    )
  fi

  if (( EUID == 0 )); then
    echo "Refusing to run candidate checkout code with release privilege." >&2
    echo "Invoke the installed controller directly as the privileged operator." >&2
    return 2
  fi
  if [[ -n "${DOCKER_HOST:-}" || -n "${DOCKER_CONTEXT:-}" || \
    ( -S /var/run/docker.sock && -w /var/run/docker.sock ) ]]; then
    echo "Candidate handoff must not have Docker daemon authority." >&2
    return 2
  fi
  if [[ -n "${DATABASE_URL:-}" || -n "${POSTGRES_PASSWORD:-}" || \
    -n "${PGHOST:-}" || -n "${PGSERVICE:-}" || \
    -n "${PROPERTYQUARRY_CF_TUNNEL_TOKEN:-}" ]]; then
    echo "Database and traffic credentials belong only to the installed controller." >&2
    return 2
  fi
  if [[ -n "${EA_PUBLIC_TOUR_DIR:-}" ]]; then
    echo "The public-tour volume path belongs only to the installed controller." >&2
    return 2
  fi
  if [[ -z "${signed_request}" || "${signed_request}" != /* ]]; then
    echo "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST must be an absolute external signed-request path." >&2
    return 2
  fi

  propertyquarry_secure_parent_chain "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PATH}" || return 2
  propertyquarry_secure_parent_chain "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_MANIFEST}" || return 2
  propertyquarry_secure_parent_chain "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PIN}" || return 2
  propertyquarry_secure_external_file \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PATH}" 555 "External deploy controller" || return 2
  propertyquarry_secure_external_file \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_MANIFEST}" 444 "External controller manifest" || return 2
  propertyquarry_secure_external_file \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PIN}" 444 "External controller digest pin" || return 2
  propertyquarry_secure_request_transport "${signed_request}" || return 2

  propertyquarry_open_verified_fd \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PATH}" controller_fd || return 2
  propertyquarry_open_verified_fd \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_MANIFEST}" manifest_fd || return 2
  propertyquarry_open_verified_fd \
    "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PIN}" controller_pin_fd || return 2
  propertyquarry_open_verified_fd "${signed_request}" request_fd || return 2
  exec {candidate_root_fd}<"${APP_ROOT}"

  controller_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "/proc/self/fd/${controller_fd}")"
  manifest_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "/proc/self/fd/${manifest_fd}")"
  controller_pin_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "/proc/self/fd/${controller_pin_fd}")"
  request_identity="$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "/proc/self/fd/${request_fd}")"
  expected_controller_sha="$(propertyquarry_controller_pin_sha "${controller_pin_fd}")" || {
    echo "External controller digest-pin validation failed." >&2
    return 2
  }
  actual_controller_sha="$(/usr/bin/sha256sum "/proc/self/fd/${controller_fd}")"
  actual_controller_sha="${actual_controller_sha%% *}"
  request_sha="$(/usr/bin/sha256sum "/proc/self/fd/${request_fd}")"
  request_sha="${request_sha%% *}"
  controller_magic="$(/usr/bin/od -An -N4 -tx1 "/proc/self/fd/${controller_fd}" | /usr/bin/tr -d '[:space:]')"
  if [[ "${controller_magic}" != "7f454c46" ]]; then
    echo "External deploy controller must be a pinned native ELF entrypoint." >&2
    return 2
  fi
  if [[ "${actual_controller_sha}" != "${expected_controller_sha}" ]]; then
    echo "External deploy controller does not match its root-owned digest pin." >&2
    return 2
  fi
  if [[ "$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PATH}")" != "${controller_identity}" || \
    "$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_MANIFEST}")" != "${manifest_identity}" || \
    "$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "${PROPERTYQUARRY_EXTERNAL_CONTROLLER_PIN}")" != "${controller_pin_identity}" || \
    "$(/usr/bin/stat -Lc '%d:%i:%u:%g:%a:%h:%s:%F:%y:%z' -- "${signed_request}")" != "${request_identity}" ]]; then
    echo "External handoff identity changed after hashing." >&2
    return 2
  fi

  exec /usr/bin/env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/nonexistent \
    LANG=C \
    "/proc/self/fd/${controller_fd}" "${operation}" \
    --controller-self-fd "${controller_fd}" \
    --external-manifest-fd "${manifest_fd}" \
    --controller-pin-fd "${controller_pin_fd}" \
    --signed-request-fd "${request_fd}" \
    --signed-request-sha256 "${request_sha}" \
    --require-signed-request-fd-stable-read-and-signature \
    --candidate-root-fd "${candidate_root_fd}" \
    --candidate-root-device-inode "$(/usr/bin/stat -Lc '%d:%i' -- "/proc/self/fd/${candidate_root_fd}")" \
    --requested-runtime-mode "${requested_mode}" \
    --canonical-compose-plan "${PROPERTYQUARRY_EXTERNAL_COMPOSE_PLAN}" \
    --database-fence-policy "${PROPERTYQUARRY_EXTERNAL_DATABASE_POLICY}" \
    --drain-keyring "${PROPERTYQUARRY_EXTERNAL_DRAIN_KEYRING}" \
    --operator-gateway-trust "${PROPERTYQUARRY_EXTERNAL_OPERATOR_GATEWAY_TRUST}" \
    --monitoring-topology "${PROPERTYQUARRY_EXTERNAL_MONITORING_TOPOLOGY}" \
    --monitoring-tools "${PROPERTYQUARRY_EXTERNAL_MONITORING_TOOLS}" \
    --require-controller-self-attestation \
    --require-external-monotonic-cas \
    --require-root-pinned-monitoring-runtime \
    --require-server-derived-database-identity \
    --require-signed-disposable-or-allowed-database-target \
    --require-cloudflared-immutable-digest-and-config-binding \
    --require-public-tour-volume-profile-v1 \
    --forbid-caller-compose \
    --forbid-candidate-output-authority \
    "${mode_args[@]}"
}

propertyquarry_exec_external_controller
