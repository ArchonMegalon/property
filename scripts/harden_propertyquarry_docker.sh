#!/usr/bin/env bash
set -euo pipefail

ROOT="${PROPERTYQUARRY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="${ROOT}/artifacts"
LOG_FILE="${LOG_DIR}/propertyquarry_docker_recovery.log"
DOCKER_START_TIMEOUT_SECONDS="${DOCKER_START_TIMEOUT_SECONDS:-300}"
PROPERTYQUARRY_HOST_RECOVERY_ALLOW="${PROPERTYQUARRY_HOST_RECOVERY_ALLOW:-0}"
PROPERTYQUARRY_HOST_RECOVERY_DRY_RUN="${PROPERTYQUARRY_HOST_RECOVERY_DRY_RUN:-0}"

mkdir -p "${LOG_DIR}"

if [[ "${PROPERTYQUARRY_HOST_RECOVERY_ALLOW}" != "1" ]]; then
  echo "Refusing host-level Docker recovery without PROPERTYQUARRY_HOST_RECOVERY_ALLOW=1" >&2
  exit 2
fi

log() {
  printf '[propertyquarry-docker] %s\n' "$1" | tee -a "${LOG_FILE}"
}

run() {
  log "running: $*"
  if [[ "${PROPERTYQUARRY_HOST_RECOVERY_DRY_RUN}" == "1" ]]; then
    return 0
  fi
  "$@" 2>&1 | tee -a "${LOG_FILE}"
}

sudo_ready() {
  sudo -n true >/dev/null 2>&1
}

probe_docker() {
  timeout 15s docker info >/dev/null 2>&1
}

probe_compose() {
  timeout 15s docker compose version >/dev/null 2>&1
}

wait_for_docker_ready() {
  local deadline=$((SECONDS + DOCKER_START_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if probe_docker && probe_compose; then
      return 0
    fi
    sleep 5
  done
  return 1
}

collect_docker_diagnostics() {
  log "collecting docker diagnostics"
  run systemctl status docker --no-pager -n 80 || true
  run journalctl -u docker --no-pager -n 120 || true
}

collect_containerd_diagnostics() {
  log "collecting containerd diagnostics"
  run systemctl status containerd --no-pager -n 80 || true
  run journalctl -u containerd --no-pager -n 120 || true
}

cleanup_stale_runtime_state() {
  log "cleaning stale runtime state"
  mapfile -t stale_ids < <(
    journalctl -u docker -u containerd --no-pager -n 4000 2>/dev/null \
      | grep -Eo '[a-f0-9]{64}' \
      | sort -u
  )
  for id in "${stale_ids[@]}"; do
    [[ ${#id} -eq 64 ]] || continue
    run sudo rm -rf "/run/containerd/io.containerd.runtime.v2.task/moby/${id}" || true
    run sudo rm -rf "/var/run/docker/runtime-runc/moby/${id}" || true
    run sudo rm -rf "/run/docker/runtime-runc/moby/${id}" || true
  done
}

force_recycle_docker_daemon() {
  log "forcing docker daemon recycle"
  run sudo systemctl stop docker.socket || true
  run sudo systemctl stop docker || true
  run sudo systemctl kill --kill-who=main --signal=SIGKILL docker || true
  run sudo pkill -9 -x dockerd || true
  run sudo systemctl stop containerd || true
  while IFS= read -r shim_pid; do
    [[ -n "${shim_pid}" ]] || continue
    run sudo kill -9 "${shim_pid}" || true
  done < <(pgrep -f '^containerd-shim' || true)
  while IFS= read -r runc_pid; do
    [[ -n "${runc_pid}" ]] || continue
    run sudo kill -9 "${runc_pid}" || true
  done < <(pgrep -x runc || true)
  run sudo pkill -9 -x containerd || true
  run sudo rm -f /var/run/docker.pid
  run sudo rm -f /run/containerd/containerd.sock
  cleanup_stale_runtime_state
  run sudo systemctl reset-failed docker
  run sudo systemctl reset-failed containerd
  run sudo systemctl start containerd
  sleep 5
  if ! timeout 15s sudo systemctl is-active --quiet containerd; then
    log "containerd did not become active"
    collect_containerd_diagnostics
    exit 4
  fi
  run sudo systemctl start docker.socket
  run sudo systemctl start docker || true
  if ! wait_for_docker_ready; then
    log "docker did not become ready within ${DOCKER_START_TIMEOUT_SECONDS}s after forced recycle"
    collect_docker_diagnostics
    collect_containerd_diagnostics
    exit 5
  fi
}

log "starting recovery"
run date
run docker --version

if ! probe_docker || ! probe_compose; then
  log "docker or compose probe failed; restarting docker"
  if ! sudo_ready; then
    log "sudo credentials are required before docker can be restarted"
    log "run: sudo -v"
    exit 2
  fi
  run sudo systemctl restart docker || true
  if ! wait_for_docker_ready; then
    log "docker restart did not become ready within ${DOCKER_START_TIMEOUT_SECONDS}s; attempting forced daemon recycle"
    collect_docker_diagnostics
    force_recycle_docker_daemon
  fi
fi

log "verifying docker daemon"
run timeout 15s docker version

log "verifying compose plugin"
run timeout 15s docker compose version

log "running propertyquarry deploy preflight"
run bash "${ROOT}/scripts/deploy_propertyquarry.sh" --preflight-only

log "deploying propertyquarry"
run make -C "${ROOT}" deploy

log "completed successfully"
