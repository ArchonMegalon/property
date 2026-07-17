from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assert_external_deploy_controller_handoff(script: str) -> None:
    for required in (
        "/usr/libexec/propertyquarry-release-control/propertyquarry-deploy-controller",
        "/etc/propertyquarry/release-control/external-deploy-controller.v1.json",
        "--controller-self-fd",
        "--external-manifest-fd",
        "--signed-request-fd",
        "--candidate-root-fd",
        "--controller-owns-all-privileged-actions",
        "--contain-before-candidate-validation",
        "--forbid-caller-compose",
        "--forbid-candidate-output-authority",
        "/usr/bin/env -i",
    ):
        assert required in script
    for forbidden in (
        "propertyquarry_deploy_controller_guard.py",
        "docker compose",
        "docker-compose",
        "psql",
        "PROPERTYQUARRY_DEPLOY_PYTHON_BIN",
    ):
        assert forbidden not in script


def _workflow_job(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    start = workflow.index(marker)
    body_start = start + len(marker)
    next_job = re.search(r"^  [a-zA-Z0-9_-]+:\n", workflow[body_start:], flags=re.MULTILINE)
    end = body_start + next_job.start() if next_job else len(workflow)
    return workflow[start:end]


def _run_schema_quiesce_scenario(
    tmp_path: Path,
    *,
    scenario: str,
    api_state: str,
    scheduler_state: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    event_log = tmp_path / "events.log"
    shell = r'''
set -euo pipefail

declare -A SERVICE_STATE=(
  [api]="${INITIAL_API_STATE}"
  [scheduler]="${INITIAL_SCHEDULER_STATE}"
  [render]="stopped"
  [migrate]="stopped"
)

event() {
  printf '%s\n' "$*" >> "${EVENT_LOG}"
}

container_state_line() {
  local service="${1#cid-}"
  local state="${SERVICE_STATE[${service}]:-missing}"
  case "${state}" in
    running) printf 'running|healthy' ;;
    restarting) printf 'restarting|starting' ;;
    paused) printf 'paused|healthy' ;;
    created) printf 'created|none' ;;
    removing) printf 'removing|none' ;;
    stopped) printf 'exited|none' ;;
    dead) printf 'dead|none' ;;
  esac
}

fake_compose() {
  local action="$1"
  local skip_next=0
  local arg=""
  local service=""
  shift
  if [[ "${action}" == "ps" ]]; then
    for arg in "$@"; do
      service="${arg}"
    done
    if [[ "${SERVICE_STATE[${service}]:-missing}" != "missing" ]]; then
      printf 'cid-%s' "${service}"
    fi
    return 0
  fi
  event "compose ${action} $*"
  if [[ "${SCENARIO}" == "quiesce-failure" && "${action}" == "stop" ]]; then
    SERVICE_STATE[api]="stopped"
    return 1
  fi
  if [[ "${SCENARIO}" == "paused-writer-stuck" && "${action}" == "stop" ]]; then
    SERVICE_STATE[scheduler]="stopped"
    return 0
  fi
  case "${action}" in
    stop)
      for arg in "$@"; do
        if [[ "${skip_next}" == "1" ]]; then
          skip_next=0
          continue
        fi
        if [[ "${arg}" == "--timeout" ]]; then
          skip_next=1
          continue
        fi
        SERVICE_STATE["${arg}"]="stopped"
      done
      ;;
    start)
      for arg in "$@"; do
        SERVICE_STATE["${arg}"]="running"
      done
      ;;
    *)
      return 2
      ;;
  esac
}

DC=(fake_compose)
source "${QUIESCE_HELPER}"
PROPERTYQUARRY_ALLOWED_DATABASE_WRITER_CONTAINER_NAMES=(api scheduler)
database_writer_inventory_lines() {
  if [[ "${SERVICE_STATE[api]}" != "stopped" ]]; then printf 'cid-api|api\n'; fi
  if [[ "${SERVICE_STATE[scheduler]}" != "stopped" ]]; then printf 'cid-scheduler|scheduler\n'; fi
}
database_writer_session_inventory_lines() { return 0; }
stop_database_writer_container() { return 0; }
database_writer_container_is_active() { return 1; }
propertyquarry_install_schema_quiesce_traps
propertyquarry_quiesce_schema_writers \
  api api scheduler scheduler render render migrate migrate 30 2

case "${SCENARIO}" in
  success)
    event migration-completed
    propertyquarry_mark_schema_migration_committed
    SERVICE_STATE[api]="running"
    event candidate-api-ready
    SERVICE_STATE[scheduler]="running"
    event candidate-scheduler-ready
    propertyquarry_finish_schema_quiesce
    ;;
  precommit-failure)
    SERVICE_STATE[migrate]="running"
    event migration-failed
    false
    ;;
  paused-migrator-failure)
    SERVICE_STATE[migrate]="paused"
    event migration-failed
    false
    ;;
  postcommit-failure)
    event migration-completed
    propertyquarry_mark_schema_migration_committed
    SERVICE_STATE[api]="running"
    event candidate-api-started
    false
    ;;
  *)
    exit 64
    ;;
esac
'''
    env = {
        **os.environ,
        "QUIESCE_HELPER": str(ROOT / "scripts/propertyquarry_deploy_quiesce.sh"),
        "EVENT_LOG": str(event_log),
        "SCENARIO": scenario,
        "INITIAL_API_STATE": api_state,
        "INITIAL_SCHEDULER_STATE": scheduler_state,
    }
    completed = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    events = event_log.read_text(encoding="utf-8").splitlines() if event_log.exists() else []
    return completed, events


def test_make_deploy_uses_hardened_propertyquarry_wrapper() -> None:
    makefile = _read("Makefile")

    assert "./scripts/deploy_propertyquarry.sh" in makefile
    assert "PROPERTYQUARRY_COMPOSE_FILE" not in makefile.split("\ndeploy:\n", 1)[1].split(
        "\n\ndeploy-legacy-ea-stack:", 1
    )[0]
    assert "PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh" in makefile
    assert "docker compose -f docker-compose.property.yml up -d --build --remove-orphans" not in makefile


def test_smoke_runtime_runs_unprivileged_local_propertyquarry_browser_contracts() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    browser_test = _read("tests/e2e/test_propertyquarry_greenfield_browser.py")
    browser_job = _workflow_job(workflow, "propertyquarry-browser-contracts")
    product_browser_job = _workflow_job(workflow, "product-browser-e2e")

    assert workflow.count("\n  product-browser-e2e:\n") == 1
    assert "\n  push:\n" in workflow
    assert "\n  pull_request:\n" in workflow
    assert "\n  workflow_dispatch:\n" in workflow
    assert "permissions:\n      contents: read" in browser_job
    assert "persist-credentials: false" in browser_job
    assert "python -m playwright install --with-deps chromium" in browser_job
    assert re.findall(r"tests/e2e/test_propertyquarry_[a-z0-9_]+\.py", browser_job) == [
        "tests/e2e/test_propertyquarry_greenfield_browser.py",
        "tests/e2e/test_propertyquarry_public_tour_browser.py",
    ]
    assert "python -m pytest -q" in browser_job
    assert "make property-release-gates" not in browser_job
    assert "secrets." not in browser_job
    assert "vars." not in browser_job
    assert "\n    environment:" not in browser_job
    assert "\n    if:" not in browser_job
    assert "permissions:\n      contents: read" in product_browser_job
    assert "runs-on: ubuntu-latest" in product_browser_job
    assert "fail-fast: false" in product_browser_job
    assert "browser-engine: [chromium, firefox, webkit]" in product_browser_job
    assert "persist-credentials: false" in product_browser_job
    assert 'python -m playwright install --with-deps "${{ matrix.browser-engine }}"' in product_browser_job
    assert "PROPERTYQUARRY_CORE_BROWSER_ENGINE: ${{ matrix.browser-engine }}" in product_browser_job
    assert "PYTHONPATH=ea EA_STORAGE_BACKEND=memory python -m pytest -q" in product_browser_job
    assert (
        "tests/e2e/test_propertyquarry_greenfield_browser.py::"
        "test_propertyquarry_workbench_candidate_history_stays_in_place"
        in product_browser_job
    )
    assert (
        "tests/e2e/test_propertyquarry_greenfield_browser.py::"
        "test_propertyquarry_flagship_operating_loop_in_browser"
        in product_browser_job
    )
    assert browser_test.count('browser_base_url = f"http://propertyquarry.localhost:{port}"') == 1
    assert 'monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", browser_base_url)' in browser_test
    assert 'browser_base_url = f"http://propertyquarry.com:{port}"' not in browser_test
    assert 'browser_base_url = f"http://127.0.0.1:{port}"' not in browser_test
    assert "/etc/hosts" not in product_browser_job
    assert 'echo "127.0.0.1 propertyquarry.com"' not in product_browser_job
    assert "--host-resolver-rules" not in browser_test
    assert "network.dns.localDomains" not in browser_test
    assert "secrets." not in product_browser_job
    assert "vars." not in product_browser_job
    assert "\n    environment:" not in product_browser_job
    assert "\n    if:" not in product_browser_job
    assert "propertyquarry-live-release-gates" not in product_browser_job


def test_smoke_runtime_runs_fail_closed_postgres_production_storage_browser_lane() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    job = _workflow_job(workflow, "propertyquarry-postgres-browser-e2e")
    smoke = _read("scripts/smoke_property_postgres.sh")
    browser_test = _read("tests/e2e/test_propertyquarry_postgres_browser.py")
    bootstrap = _read("scripts/propertyquarry_postgres_browser_bootstrap.py")
    property_web_dockerfile = _read("ea/Dockerfile.property-web")

    assert workflow.count("\n  propertyquarry-postgres-browser-e2e:\n") == 1
    assert "permissions:\n      contents: read" in job
    assert "runs-on: ubuntu-latest" in job
    assert "timeout-minutes: 45" in job
    assert "persist-credentials: false" in job
    assert "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES: \"0\"" in job
    assert "EA_API_TOKEN: propertyquarry-postgres-browser-${{ github.run_id }}-${{ github.run_attempt }}" in job
    assert "POSTGRES_PASSWORD: propertyquarry-browser-${{ github.run_id }}-${{ github.run_attempt }}" in job
    assert "python -m playwright install --with-deps chromium" in job
    assert "bash scripts/smoke_property_postgres.sh --browser-e2e" in job
    assert "continue-on-error:" not in job
    assert "|| true" not in job
    assert "secrets." not in job
    assert "vars." not in job

    for required in (
        "set -euo pipefail",
        "docker-compose.property.yml",
        'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-propertyquarry-postgres-smoke-${smoke_suffix}}"',
        'PROPERTYQUARRY_API_CONTAINER_NAME="${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-postgres-smoke-api-${smoke_suffix}}"',
        'PROPERTYQUARRY_DB_CONTAINER_NAME="${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-postgres-smoke-db-${smoke_suffix}}"',
        'PROPERTYQUARRY_MIGRATE_CONTAINER_NAME="${PROPERTYQUARRY_MIGRATE_CONTAINER_NAME:-propertyquarry-postgres-smoke-migrate-${smoke_suffix}}"',
        'set_env_value "EA_RUNTIME_MODE" "prod"',
        'set_env_value "EA_STORAGE_BACKEND" "postgres"',
        'set_env_value "EA_ALLOW_LOOPBACK_NO_AUTH" "0"',
        'set_env_value "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES" "0"',
        'if [[ "${ready_reason}" == "${expected_ready_reason}" ]]',
        'runtime_mode="$(docker exec',
        'runtime_storage="$(docker exec',
        'legacy_runtime_surfaces="$(docker exec',
        "PROPERTYQUARRY_POSTGRES_BROWSER_E2E=1",
        "propertyquarry_postgres_browser_bootstrap.py",
        "PROPERTYQUARRY_POSTGRES_BROWSER_SESSION_FILE",
        "tests/e2e/test_propertyquarry_postgres_browser.py",
    ):
        assert required in smoke
    assert "postgres_ready*" not in smoke
    assert "sed -i" not in smoke
    assert "multiline env values are not supported" in smoke

    for required in (
        "PROPERTYQUARRY_POSTGRES_BROWSER_BASE_URL",
        "PROPERTYQUARRY_POSTGRES_BROWSER_EXPECTED_READY_REASON",
        "PROPERTYQUARRY_POSTGRES_BROWSER_SESSION_FILE",
        'session_receipt.get("provisioning_scope") == "internal_ci_only"',
        'client.get("/health/ready")',
        'ready.get("reason") == expected_ready_reason',
        'version.get("storage_backend") == "postgres"',
        'registration.status_code == 503',
        '"verification_token" not in registration.text',
        'client.get("/app/properties")',
        '"X-EA-API-Token": api_token',
        '"ea_workspace_session": access_token',
        '"/v1/onboarding/property-search/preferences"',
        'authenticated_page.goto(f"{base_url}/app/search"',
        'authenticated_page.goto(f"{base_url}/app/properties"',
        'authenticated_page.locator("[data-property-decision-workbench]")',
    ):
        assert required in browser_test
    assert "TestClient" not in browser_test
    assert "create_app" not in browser_test
    assert 'client.post("/v1/register/verify"' not in browser_test

    for required in (
        "PROPERTYQUARRY_POSTGRES_BROWSER_E2E",
        'runtime_mode != "prod" or storage_backend != "postgres"',
        "container.onboarding.start_workspace",
        "issue_workspace_access_session",
        'source_kind="postgres_browser_internal_ci_bootstrap"',
        '"provisioning_scope": "internal_ci_only"',
        "_secure_write",
        "os.O_EXCL",
        'getattr(os, "O_NOFOLLOW", 0)',
    ):
        assert required in bootstrap
    assert (
        "COPY scripts/propertyquarry_postgres_browser_bootstrap.py "
        "/app/scripts/propertyquarry_postgres_browser_bootstrap.py"
        in property_web_dockerfile
    )


def test_smoke_runtime_bootstraps_clean_runner_dependencies_and_release_parent() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    security_job = _workflow_job(workflow, "security-static")
    api_job = _workflow_job(workflow, "smoke-runtime-api")
    browser_job = _workflow_job(workflow, "propertyquarry-browser-contracts")
    postgres_smoke_job = _workflow_job(workflow, "smoke-runtime-postgres")
    postgres_contract_job = _workflow_job(workflow, "postgres-runtime-contracts")

    assert "fetch-depth: 0" in security_job
    assert "Release hygiene audits every commit between the manifest candidate and HEAD." in security_job
    assert "pytest==9.0.2" in api_job
    assert "httpx==0.28.1" in api_job
    assert "opencv-python-headless==4.13.0.92" in api_job
    assert "sudo apt-get install --yes ffmpeg" in api_job
    assert "python -m playwright install --with-deps chromium" in api_job
    assert "pytest==9.0.2" in browser_job
    assert "httpx==0.28.1" in browser_job
    assert "sudo apt-get install --yes ffmpeg" in browser_job
    assert "POSTGRES_PASSWORD: propertyquarry-ci-${{ github.run_id }}" in postgres_smoke_job
    assert "docker volume create property_propertyquarry_public_tours" in postgres_smoke_job
    assert "POSTGRES_PASSWORD: propertyquarry-ci-${{ github.run_id }}" in postgres_contract_job
    assert "pytest==9.0.2" in postgres_contract_job
    assert "httpx==0.28.1" in postgres_contract_job


def test_smoke_runtime_pins_external_actions_to_immutable_commits() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    action_uses_lines = [
        line.strip()
        for line in workflow.splitlines()
        if re.match(r"^\s*(?:-\s+)?uses:\s+", line)
    ]

    assert action_uses_lines

    def assert_immutable_action(declaration: str) -> None:
        action_declaration, _, version_comment = declaration.partition("#")
        action_ref = action_declaration.split("uses:", 1)[1].strip().strip("'\"")
        if action_ref.startswith("./"):
            return

        assert re.fullmatch(
            r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+@[0-9a-f]{40}",
            action_ref,
        ), f"external action must use an immutable 40-hex commit SHA: {action_ref}"
        assert re.fullmatch(
            r"v[1-9][0-9]*",
            version_comment.strip(),
        ), f"pinned external action must retain its major version comment: {declaration}"

    for action_uses_line in action_uses_lines:
        assert_immutable_action(action_uses_line)

    assert_immutable_action("uses: ./.github/actions/local-contract")


def test_legacy_compose_forwards_postgres_password_into_database_container() -> None:
    compose = _read("docker-compose.yml")

    assert 'POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:-}"' in compose


def test_smoke_runtime_protects_live_propertyquarry_release_gates() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    live_job = _workflow_job(workflow, "propertyquarry-live-release-gates")

    assert (
        "if: ${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' "
        "&& needs['propertyquarry-ordinary-ci-success'].result == 'success' "
        "&& needs['propertyquarry-flagship-security'].result == 'success' "
        "&& needs['propertyquarry-continuous-ux'].result == 'success' }}"
        in live_job
    )
    assert live_job.count("if:") == 2
    assert "if: ${{ always() }}" in live_job
    assert "environment:\n      name: propertyquarry-production" in live_job
    assert "permissions:\n      contents: read" in live_job
    assert "persist-credentials: false" in live_job
    assert (
        "PROPERTYQUARRY_LIVE_MOBILE_BASE_URL: ${{ vars.PROPERTYQUARRY_LIVE_MOBILE_BASE_URL }}"
        in live_job
    )
    assert (
        "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE: ${{ secrets.PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE }}"
        in live_job
    )
    assert "PROPERTYQUARRY_LIVE_PRINCIPAL_ID: ${{ secrets.PROPERTYQUARRY_LIVE_PRINCIPAL_ID }}" in live_job
    assert (
        "PROPERTYQUARRY_LIVE_TELEGRAM_BOT_TOKEN: ${{ secrets.PROPERTYQUARRY_LIVE_TELEGRAM_BOT_TOKEN }}"
        in live_job
    )
    assert (
        "PROPERTYQUARRY_LIVE_TELEGRAM_CHAT_ID: ${{ secrets.PROPERTYQUARRY_LIVE_TELEGRAM_CHAT_ID }}"
        in live_job
    )
    assert (
        "PROPERTYQUARRY_LIVE_PROBE_SECRET: ${{ secrets.PROPERTYQUARRY_LIVE_PROBE_SECRET }}"
        in live_job
    )
    for protected_rybbit_binding in (
        "PROPERTYQUARRY_RYBBIT_SITE_API_URL: \"${{ format('{0}/api/sites/{1}', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
        "PROPERTYQUARRY_RYBBIT_HAS_DATA_API_URL: \"${{ format('{0}/api/sites/{1}/has-data', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
        "PROPERTYQUARRY_RYBBIT_EVENTS_API_URL: \"${{ format('{0}/api/sites/{1}/events?"
        "page_size=50&past_minutes_start=10&past_minutes_end=0', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
    ):
        assert protected_rybbit_binding in live_job
    assert "vars.PROPERTYQUARRY_RYBBIT_SITE_API_URL" not in live_job
    assert "vars.PROPERTYQUARRY_RYBBIT_HAS_DATA_API_URL" not in live_job
    assert "vars.PROPERTYQUARRY_RYBBIT_EVENTS_API_URL" not in live_job
    assert "EA_API_TOKEN: ${{ secrets.PROPERTYQUARRY_LIVE_API_TOKEN }}" not in live_job
    assert "PROPERTYQUARRY_RELEASE_PROBE_SECRET" not in live_job
    assert "PROPERTYQUARRY_RELEASE_PROBE_PRINCIPAL_ID" not in live_job
    assert "PROPERTYQUARRY_WORKFLOW_HEAD_SHA: ${{ github.sha }}" in live_job
    assert "release_manifest_runtime_sha" in live_job
    assert 'echo "PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA=${runtime_sha}" >> "${GITHUB_ENV}"' in live_job
    assert "property-live-workflow-binding.json" in live_job
    assert "property-live-release-provenance.json" in live_job
    assert "property-live-mobile-release-gate.json" in live_job
    assert "property-live-accessibility-release-gate.json" in live_job
    assert "property-live-map-preview-flagship-release-gate.json" in live_job
    assert "property-live-public-release-gate.json" in live_job
    assert "property-live-authenticated-release-gate.json" in live_job
    assert "property-live-notification-delivery.json" in live_job
    assert (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4"
        in live_job
    )
    assert "if-no-files-found: error" in live_job
    assert "set -euo pipefail" in live_job
    preflight_markers = (
        ': "${PROPERTYQUARRY_LIVE_MOBILE_BASE_URL:?Missing GitHub environment variable '
        'PROPERTYQUARRY_LIVE_MOBILE_BASE_URL}"',
        ': "${PROPERTYQUARRY_LIVE_PROBE_SECRET:?Missing protected release-probe credential}"',
    )
    release_gate = live_job.index("bash scripts/propertyquarry_live_release_gates.sh")
    assert all(marker in live_job for marker in preflight_markers)
    assert all(live_job.index(marker) < release_gate for marker in preflight_markers)
    assert (
        live_job.index(
            "env:\n          PROPERTYQUARRY_LIVE_PROBE_SECRET: "
            "${{ secrets.PROPERTYQUARRY_LIVE_PROBE_SECRET }}"
        )
        < release_gate
    )
    assert "make property-release-gates" not in live_job
    assert "docker compose" not in live_job
    assert "POSTGRES_PASSWORD" not in live_job
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE" not in live_job
    assert "continue-on-error:" not in live_job
    assert "|| true" not in live_job


def test_smoke_runtime_requires_ordinary_ci_before_live_release_and_live_release_before_activation() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    aggregate_job = _workflow_job(workflow, "propertyquarry-ordinary-ci-success")
    live_job = _workflow_job(workflow, "propertyquarry-live-release-gates")
    activation_job = _workflow_job(workflow, "propertyquarry-live-activation-to-value")

    for required_job in (
        "property-security-posture",
        "security-static",
        "smoke-runtime-api",
        "propertyquarry-browser-contracts",
        "product-browser-e2e",
        "propertyquarry-postgres-browser-e2e",
        "propertyquarry-continuous-ux",
        "propertyquarry-accessibility-contracts",
        "propertyquarry-failure-state-contracts",
        "propertyquarry-activation-contracts",
        "smoke-runtime-postgres",
        "postgres-runtime-contracts",
    ):
        assert f"      - {required_job}\n" in aggregate_job
    assert "if: ${{ always() }}" in aggregate_job
    assert "details.get(\"result\") != \"success\"" in aggregate_job
    assert "secrets." not in aggregate_job
    assert "      - propertyquarry-ordinary-ci-success\n" in live_job
    assert "needs: propertyquarry-live-release-gates" in activation_job
    assert "needs['propertyquarry-live-release-gates'].result == 'success'" in activation_job
    assert "fetch-depth: 0" in activation_job
    assert "Bind activation to the immutable manifest runtime candidate" in activation_job
    assert "release_manifest_runtime_sha" in activation_job
    assert '--release-sha "${PROPERTYQUARRY_RELEASE_COMMIT_SHA}"' in activation_job

    assert "propertyquarry-release-security-${{ github.run_id }}-${{ github.run_attempt }}" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_REPOSITORY: ArchonMegalon/property" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_PUBLIC_ORIGIN" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_DEPLOYMENT_ID" in live_job
    assert "PROPERTYQUARRY_RELEASE_DEPLOYMENT_ID" not in live_job
    assert (
        "PROPERTYQUARRY_EXPECTED_RELEASE_DEPLOYMENT_ID=propertyquarry-governed-deploy-"
        "${runtime_sha:0:12}"
    ) in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_ARTIFACT_SET" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_LABEL" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_GENERATED_AT" in live_job
    assert "PROPERTYQUARRY_EXPECTED_REPLICA_ID" in live_job
    assert "PROPERTYQUARRY_EXPECTED_WEB_IMAGE" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RENDER_IMAGE" in live_job
    assert "PROPERTYQUARRY_RELEASE_SECURITY_RECEIPT" in live_job
    assert "PROPERTYQUARRY_RELEASE_SECURITY_WORKFLOW_BINDING" in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_IMAGE_DIGEST=" in live_job


def test_smoke_runtime_withholds_launch_authority_without_same_run_activation_and_attested_controller() -> None:
    workflow = _read(".github/workflows/smoke-runtime.yml")
    preflight = _workflow_job(workflow, "propertyquarry-launch-controller-preflight")
    launch_gold = _workflow_job(workflow, "propertyquarry-launch-gold")

    assert "run_launch_authority:" in workflow
    assert "type: boolean" in workflow.split("run_launch_authority:", 1)[1].split("jobs:", 1)[0]
    assert "      - propertyquarry-live-release-gates\n" in preflight
    assert "      - propertyquarry-live-activation-to-value\n" in preflight
    assert "always()" in preflight
    assert "inputs.run_launch_authority == true" in preflight
    assert '[[ "${PROPERTYQUARRY_LIVE_RELEASE_RESULT}" != "success" ]]' in preflight
    assert '[[ "${PROPERTYQUARRY_LIVE_ACTIVATION_RESULT}" != "success" ]]' in preflight
    assert '[[ "${PROPERTYQUARRY_RELEASE_CONTROLLER_READY}" != "true" ]]' in preflight
    assert "PROPERTYQUARRY_RELEASE_CONTROLLER_BUNDLE_SHA256" in preflight
    assert "^[0-9a-f]{64}$" in preflight
    assert "|| true" not in preflight
    assert "needs: propertyquarry-launch-controller-preflight" in launch_gold
    assert "needs['propertyquarry-launch-controller-preflight'].result == 'success'" in launch_gold
    assert "runs-on: [self-hosted, propertyquarry-release-controller]" in launch_gold
    assert "environment:\n      name: propertyquarry-production" in launch_gold
    assert "propertyquarry-release-security-${{ github.run_id }}-${{ github.run_attempt }}" in launch_gold
    assert "propertyquarry-continuous-ux-${{ github.sha }}" in launch_gold
    assert "propertyquarry-live-activation-${{ github.run_id }}-${{ github.run_attempt }}" in launch_gold
    assert (
        "propertyquarry-live-release-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}"
        in launch_gold
    )
    assert "PROPERTYQUARRY_RELEASE_CONTROLLER_BUNDLE_PATH" in launch_gold
    for protected_rybbit_binding in (
        "PROPERTYQUARRY_RYBBIT_SITE_API_URL: \"${{ format('{0}/api/sites/{1}', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
        "PROPERTYQUARRY_RYBBIT_HAS_DATA_API_URL: \"${{ format('{0}/api/sites/{1}/has-data', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
        "PROPERTYQUARRY_RYBBIT_EVENTS_API_URL: \"${{ format('{0}/api/sites/{1}/events?"
        "page_size=50&past_minutes_start=10&past_minutes_end=0', "
        "vars.PROPERTYQUARRY_RYBBIT_ORIGIN, secrets.PROPERTYQUARRY_RYBBIT_SITE_ID) }}\"",
    ):
        assert protected_rybbit_binding in launch_gold
    assert "vars.PROPERTYQUARRY_RYBBIT_SITE_API_URL" not in launch_gold
    assert "vars.PROPERTYQUARRY_RYBBIT_HAS_DATA_API_URL" not in launch_gold
    assert "vars.PROPERTYQUARRY_RYBBIT_EVENTS_API_URL" not in launch_gold
    assert "bash scripts/property_release_gates.sh" in launch_gold
    assert "--activate-snapshot" in launch_gold
    assert "--restore-activation" in launch_gold
    assert "trap 'rollback_overlay $?' ERR" in launch_gold
    assert "trap 'rollback_overlay 130' INT" in launch_gold
    assert "trap 'rollback_overlay 143' TERM" in launch_gold
    assert "scripts/propertyquarry_launch_authority.py" in launch_gold
    for required_authority_flag in (
        "--candidate-sha",
        "--workflow-head-sha",
        "--workflow-run-id",
        "--workflow-run-attempt",
        "--authority-phase",
        "--activation-authority",
        "--gold-status",
        "--live-provenance",
        "--activation-receipt",
        "--overlay-receipt",
        "--expected-teable-origin",
        "--expected-teable-base-id-sha256",
        "--expected-rybbit-public-origin",
        "--expected-rybbit-analytics-origin",
        "--expected-rybbit-site-id-sha256",
        "--rybbit-receipt",
        "--security-receipt",
        "--security-workflow-binding",
        "--controller-bundle",
        "--expected-controller-bundle-sha256",
    ):
        assert required_authority_flag in launch_gold
    preactivation = launch_gold.index("--authority-phase preactivation")
    pointer_activation = launch_gold.index("--activate-snapshot")
    final_authority = launch_gold.index("--authority-phase final")
    assert launch_gold.index("bash scripts/property_release_gates.sh") < preactivation
    assert preactivation < pointer_activation < final_authority
    assert launch_gold.count("--activation-authority") >= 2
    assert launch_gold.count("bash scripts/property_release_gates.sh") == 1
    assert "_completion/property_gold_status/activation-authority.json" in launch_gold
    assert "propertyquarry-launch-authority-${{ github.sha }}-${{ github.run_id }}" in launch_gold
    assert "if-no-files-found: error" in launch_gold
    assert "|| true" not in launch_gold


def test_property_web_image_contains_the_canonical_release_manifest() -> None:
    dockerfile = _read("ea/Dockerfile.property-web")

    assert (
        "COPY docs/PROPERTYQUARRY_RELEASE_MANIFEST.md "
        "/app/docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"
    ) in dockerfile


def test_protected_live_release_gate_is_remote_only_and_fail_closed() -> None:
    script = _read("scripts/propertyquarry_live_release_gates.sh")

    assert "PROPERTYQUARRY_LIVE_MOBILE_BASE_URL" in script
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE" in script
    assert "PROPERTYQUARRY_LIVE_PRINCIPAL_ID" in script
    assert "PROPERTYQUARRY_LIVE_TELEGRAM_BOT_TOKEN" in script
    assert "PROPERTYQUARRY_LIVE_TELEGRAM_CHAT_ID" in script
    assert "EA_API_TOKEN" in script
    assert "--require-research-detail" in script
    assert "propertyquarry_live_mobile_surface_smoke.py" in script
    assert "propertyquarry_map_preview_flagship_gate.py" in script
    assert "propertyquarry_live_public_smoke.py" in script
    assert "propertyquarry_live_authenticated_smoke.py" in script
    assert "propertyquarry_live_telegram_delivery.py" in script
    assert "property-live-notification-delivery.json" in script
    assert "propertyquarry_live_release_provenance.py" in script
    assert script.index("propertyquarry_live_release_provenance.py") < script.index(
        "propertyquarry_live_mobile_surface_smoke.py"
    )
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA" in script
    assert "--no-canonical-fallback" in script
    assert "--seed-research-detail-fixture" not in script
    assert "--api-token" not in script
    assert "docker" not in script
    assert "compose" not in script
    assert "POSTGRES_PASSWORD" not in script
    assert "ensure_propertyquarry_render_bridge_runtime.py" not in script
    assert "--stage-only" in script
    assert "--activate-snapshot" not in script
    assert "PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN" in script
    assert "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256" in script
    assert 'expected_phase="staged"' in script
    for required_option in (
        "--expected-repository",
        "--expected-public-origin",
        "--expected-branch",
        "--expected-commit-sha",
        "--expected-deployment-id",
        "--expected-artifact-set",
        "--expected-release-label",
        "--expected-release-generated-at",
        "--expected-image-digest",
        "--expected-replica-id",
        "--expected-web-image",
        "--expected-render-image",
        "--security-receipt",
        "--security-workflow-binding",
        "--expected-workflow-head-sha",
        "--expected-workflow-run-id",
        "--expected-workflow-run-attempt",
    ):
        assert required_option in script

    release_bundle = _read("scripts/property_release_gates.sh")
    assert 'PYTHON_BIN="${PYTHON_BIN}" bash scripts/propertyquarry_live_release_gates.sh' in release_bundle


def test_propertyquarry_deploy_missing_live_provenance_forces_targeted_e2e() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "--require-controller-self-attestation" in script
    assert "--require-external-monotonic-cas" in script
    assert "git rev-parse" not in script


def test_propertyquarry_deploy_fails_closed_on_dirty_release_provenance() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert script.index("--controller-owns-all-privileged-actions") < script.index(
        "--contain-before-candidate-validation"
    )
    assert "git status" not in script


def test_propertyquarry_docker_context_excludes_ignored_secret_and_runtime_files() -> None:
    dockerignore = set(_read(".dockerignore").splitlines())

    assert {
        ".env",
        ".env.*",
        "**/.env",
        "**/.env.*",
        "*.pem",
        "**/*.pem",
        "*.key",
        "**/*.key",
        "*.ovpn",
        "**/*.ovpn",
        "attachments/",
        "daemon-gogcli-config/",
        "data-*/",
        "memorial_data/",
        "config/*.local.yml",
        "config/onemin_api_keys.local.json",
        "config/onemin_slot_owners.local.json",
        "*.py[cod]",
        "**/*.py[cod]",
    } <= dockerignore


def test_property_runtime_image_copies_reconstruction_playwright_dependency() -> None:
    dockerfile = _read("ea/Dockerfile.property")
    runtime_copy = (
        "COPY scripts/propertyquarry_playwright_runtime.py "
        "/app/scripts/propertyquarry_playwright_runtime.py"
    )
    generator_copy = (
        "COPY scripts/generate_property_reconstruction.py "
        "/app/scripts/generate_property_reconstruction.py"
    )

    assert dockerfile.count(runtime_copy) == 1
    assert dockerfile.count(generator_copy) == 1
    assert dockerfile.index(runtime_copy) < dockerfile.index(generator_copy)
    assert dockerfile.index(generator_copy) < dockerfile.index("COPY ea/app /app/app")


def test_propertyquarry_deploy_wrapper_preflights_prod_and_probes_runtime(
    tmp_path: Path,
) -> None:
    script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(script)
    assert 'operation="${operation%-run}-preflight"' in script
    assert "--read-only" in script
    assert "--forbid-containment" in script
    assert "--forbid-state-mutation" in script
    assert "--require-explicit-preflight-disposition" in script
    assert "propertyquarry-deploy-preflight-request.json" in script
    assert "propertyquarry-deploy-run-request.json" in script
    assert "A preflight request cannot" in script
    assert "must never be reused for a deploy run" in script
    assert "PROPERTYQUARRY_DEPLOY_PYTHON_BIN" not in script
    assert "docker compose" not in script

    marker = tmp_path / "hostile-startup-executed"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    fake = hostile_bin / "bash"
    fake.write_text(
        f"#!/bin/sh\nprintf '%s\\n' hostile >> '{marker}'\nexit 97\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    for name in ("dirname", "pwd", "env"):
        (hostile_bin / name).write_bytes(fake.read_bytes())
        (hostile_bin / name).chmod(0o755)
    bash_env = tmp_path / "BASH_ENV"
    bash_env.write_text(
        f"builtin printf '%s\\n' BASH_ENV >> '{marker}'\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [str(ROOT / "scripts" / "deploy_propertyquarry.sh"), "--help"],
        cwd=ROOT,
        env={"PATH": str(hostile_bin), "BASH_ENV": str(bash_env), "ENV": str(bash_env)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Usage:" in completed.stdout
    assert not marker.exists()

def test_propertyquarry_schema_migration_quiesces_existing_writers_before_commit(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="success",
        api_state="running",
        scheduler_state="running",
    )

    assert completed.returncode == 0, completed.stderr
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "migration-completed",
        "candidate-api-ready",
        "candidate-scheduler-ready",
    ]


def test_propertyquarry_schema_migration_failure_aborts_migrator_then_restores_prior_runtime(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="precommit-failure",
        api_state="running",
        scheduler_state="stopped",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "migration-failed",
        "compose stop --timeout 30 migrate",
        "compose start api",
    ]
    assert "restoring only API, scheduler, and render containers that were running before quiesce" in completed.stderr


def test_propertyquarry_candidate_resolution_never_claims_live_default_containers(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "global-docker-events.log"
    shell = r'''
set -euo pipefail

candidate_compose() {
  if [[ "$1" == "ps" ]]; then
    return 0
  fi
  return 2
}

docker() {
  printf 'global-docker %s\n' "$*" >> "${EVENT_LOG}"
  case "$*" in
    *propertyquarry-api*) printf 'cid-live-default-api' ;;
    *propertyquarry-scheduler*) printf 'cid-live-default-scheduler' ;;
  esac
}

container_state_line() {
  printf 'running|healthy'
}

DC=(candidate_compose)
source "${QUIESCE_HELPER}"
api_cid="$(container_id_for_service propertyquarry-api propertyquarry-api)"
scheduler_cid="$(container_id_for_service propertyquarry-scheduler propertyquarry-scheduler)"
[[ -z "${api_cid}" ]]
[[ -z "${scheduler_cid}" ]]
'''
    completed = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env={
            **os.environ,
            "QUIESCE_HELPER": str(ROOT / "scripts/propertyquarry_deploy_quiesce.sh"),
            "EVENT_LOG": str(event_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not event_log.exists()


def test_propertyquarry_paused_writer_does_not_satisfy_quiesce_assertion(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="paused-writer-stuck",
        api_state="paused",
        scheduler_state="running",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "compose start scheduler",
    ]
    assert "api container cid-api is still active" in completed.stderr
    assert "recovery will not activate a prior non-running writer" in completed.stderr


def test_propertyquarry_paused_migrator_is_aborted_before_writer_restoration(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="paused-migrator-failure",
        api_state="running",
        scheduler_state="stopped",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "migration-failed",
        "compose stop --timeout 30 migrate",
        "compose start api",
    ]
    assert events.index("compose stop --timeout 30 migrate") < events.index("compose start api")


def test_propertyquarry_quiesce_treats_every_nonterminal_container_state_as_active() -> None:
    shell = r'''
set -euo pipefail

container_state_line() {
  printf '%s|none' "${1#cid-}"
}

DC=(false)
source "${QUIESCE_HELPER}"
for status in created running paused restarting removing unknown; do
  propertyquarry_schema_container_is_active "cid-${status}"
done
for status in exited dead; do
  if propertyquarry_schema_container_is_active "cid-${status}"; then
    exit 1
  fi
done
'''
    completed = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env={
            **os.environ,
            "QUIESCE_HELPER": str(ROOT / "scripts/propertyquarry_deploy_quiesce.sh"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_propertyquarry_partial_quiesce_failure_restores_the_complete_prior_runtime(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="quiesce-failure",
        api_state="running",
        scheduler_state="running",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "compose start api",
        "compose start scheduler",
    ]
    assert "Could not stop every pre-migration PropertyQuarry schema writer" in completed.stderr


def test_propertyquarry_postcommit_failure_holds_candidate_writers_stopped(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="postcommit-failure",
        api_state="running",
        scheduler_state="running",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "migration-completed",
        "candidate-api-started",
        "compose stop --timeout 30 api scheduler render",
    ]
    assert not any(event.startswith("compose start ") for event in events)
    assert "Do not restart the previous image" in completed.stderr


def test_propertyquarry_first_deploy_migration_failure_has_no_runtime_to_restore(
    tmp_path: Path,
) -> None:
    completed, events = _run_schema_quiesce_scenario(
        tmp_path,
        scenario="precommit-failure",
        api_state="stopped",
        scheduler_state="stopped",
    )

    assert completed.returncode != 0
    assert events == [
        "compose stop --timeout 30 api scheduler render",
        "migration-failed",
        "compose stop --timeout 30 migrate",
    ]
    assert "no prior API, scheduler, or render containers to restore" in completed.stderr


def test_propertyquarry_deploy_wires_quiesce_around_governed_migration() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "--require-server-derived-database-identity" in script
    assert "--require-signed-disposable-or-allowed-database-target" in script
    assert "--database-fence-policy" in script
    assert "propertyquarry_deploy_quiesce.sh" not in script


def test_propertyquarry_deploy_wrapper_supports_focused_provider_country_matrix() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "--signed-request-fd" in script
    assert "PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES" not in script


def test_propertyquarry_deploy_catalog_probe_is_read_only() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "--read-only" in script
    assert "--forbid-state-mutation" in script
    assert "--require-explicit-preflight-disposition" in script


def test_propertyquarry_deploy_wrapper_requires_presentation_e2e_for_tour_media_changes() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "--candidate-root-fd" in script
    assert "--forbid-candidate-output-authority" in script


def test_propertyquarry_deploy_wrapper_resolves_live_smoke_identity_from_env_file() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "EA_RUNTIME_MODE" in script
    assert "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST" in script
    assert "EA_API_TOKEN" not in script


def test_propertyquarry_deploy_mobile_smoke_covers_customer_app_surfaces() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(script)
    assert "/app/" not in script


def test_propertyquarry_deploy_wrapper_stays_property_only() -> None:
    script = _read("scripts/deploy_propertyquarry.sh").lower()

    for forbidden in (
        "ea-openvoice",
        "openvoice",
        "ea-responses-proxy",
        "ea-teable-relay",
        "/docker/chummercomplete",
        "chummer-playwright",
        "/mnt/onedrive",
        "/mnt/pcloud",
    ):
        assert forbidden not in script


def test_propertyquarry_compose_mounts_operator_tour_export_drop() -> None:
    compose = _read("docker-compose.property.yml")

    assert "PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR: /data/incoming_property_tours" in compose
    assert "PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR: /data/incoming_property_tours" in compose
    assert "./state/incoming_property_tours:/data/incoming_property_tours" in compose


def test_propertyquarry_runtime_images_use_image_baked_app_code_not_repo_bind_mounts() -> None:
    compose = _read("docker-compose.property.yml")

    assert "./config:/app/config:ro" in compose
    assert "./ea:/app" not in compose
    assert "./scripts:/app/scripts" not in compose
    assert ".:/app" not in compose


def test_propertyquarry_render_runtime_keeps_playwright_for_magicfit_render_lane() -> None:
    dockerfile = _read("ea/Dockerfile.property")

    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "chown -R ea:ea /ms-playwright" in dockerfile


def test_property_tour_export_scripts_share_container_incoming_path() -> None:
    discovery = _read("scripts/discover_property_tour_exports.py")
    manifest = _read("scripts/materialize_property_tour_export_manifest.py")

    assert 'or "/data/incoming_property_tours"' in discovery
    assert 'Path("/data/incoming_property_tours")' in manifest
    assert '"state" / "incoming_property_tours"' in manifest
    assert "/data/property_tour_export_drop" not in discovery


def test_property_release_gate_runs_payfunnels_billing_contracts() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "PayFunnels checkout, webhook, refund, mismatch, and billing-surface contracts" in release_gate
    assert "tests/test_product_api_contracts.py -k 'payfunnels'" in release_gate


def test_property_release_gate_runs_heyy_whatsapp_contracts() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "Heyy WhatsApp adapter, opt-in, STOP/START, webhook, and receipt contracts" in release_gate
    assert "tests/test_property_heyy_adapter_contracts.py" in release_gate
    assert "tests/test_property_heyy_api_contracts.py" in release_gate


def test_property_release_gate_runs_id_austria_readiness_contract() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "ID Austria OIDC readiness receipt and Austrian-IP sign-in gating" in release_gate
    assert "scripts/verify_id_austria_provider.py" in release_gate


def test_property_release_gate_runs_offline_ranking_benchmark() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "offline ranking benchmark for hard filters, soft scoring, ordering, and scout thresholds" in release_gate
    assert "scripts/check_property_ranking_benchmark.py" in release_gate


def test_propertyquarry_release_and_deploy_fail_closed_on_release_bound_dr_evidence() -> None:
    release_gate = _read("scripts/property_release_gates.sh")
    deploy = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy)
    for required in (
        "PROPERTYQUARRY_DR_BACKUP_RECEIPT",
        "PROPERTYQUARRY_DR_RESTORE_RECEIPT",
        "PROPERTYQUARRY_RELEASE_COMMIT_SHA",
        "PROPERTYQUARRY_RELEASE_IMAGE_DIGEST",
        "PROPERTYQUARRY_DR_RELEASE_MAX_AGE_SECONDS",
        "scripts/propertyquarry_postgres_dr.py release-gate",
        "_completion/disaster_recovery/release-gate.json",
    ):
        assert required in release_gate
    assert "tests/test_propertyquarry_postgres_dr.py" in release_gate
    assert release_gate.index("scripts/propertyquarry_postgres_dr.py release-gate") < release_gate.index(
        "bash scripts/propertyquarry_live_release_gates.sh"
    )
    assert "--controller-owns-all-privileged-actions" in deploy
    assert "--database-fence-policy" in deploy
    assert "--require-server-derived-database-identity" in deploy
    assert "propertyquarry_postgres_dr.py" not in deploy
    assert "PROPERTYQUARRY_DR_BACKUP_RECEIPT" not in deploy

def test_property_release_gate_runs_cached_evidence_overlay_contracts() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert (
        "authenticated eight-table Teable to atomic Postgres evidence-overlay receipt, cached "
        "unavailable/stale/verified states, and no inline source indexing"
    ) in release_gate
    assert "tests/test_property_evidence_overlays.py" in release_gate


def test_property_release_gate_wires_tour_import_manifest_into_gold_status() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "scripts/materialize_property_tour_export_manifest.py" in release_gate
    assert "tour_export_incoming_dir=" in release_gate
    assert "property_api_container=\"${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}\"" in release_gate
    assert "docker exec \"${property_api_container}\" python /app/scripts/verify_property_tour_controls.py" in release_gate
    assert "--tour-root /data/public_property_tours" in release_gate
    assert "property-tour-controls-release-gate-live-container.json" in release_gate
    assert "docker cp \"${property_api_container}:/data/artifacts/property-tour-controls-release-gate-live-container.json\"" in release_gate
    assert "docker exec \"${property_api_container}\" python /app/scripts/discover_property_tour_exports.py" in release_gate
    assert "--drop-dir /data/incoming_property_tours" in release_gate
    assert "--public-tour-dir /data/public_property_tours" in release_gate
    assert "property-tour-export-discovery-release-gate-live-container.json" in release_gate
    assert "docker exec --user root \"${property_api_container}\" python /app/scripts/materialize_property_tour_export_manifest.py" in release_gate
    assert "--incoming-root /data/incoming_property_tours" in release_gate
    assert "property-tour-export-import-manifest-release-gate-live-container.json" in release_gate
    assert "property_render_container=\"${PROPERTYQUARRY_RENDER_CONTAINER_NAME:-propertyquarry-render-tools}\"" in release_gate
    assert "scripts/verify_property_tour_vendor_tooling.py" in release_gate
    assert '--runtime-container "${property_api_container}"' in release_gate
    assert 'runtime_reconstruction_container="${PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER:-${property_render_container}}"' in release_gate
    assert 'runtime_reconstruction_container="${PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER:-${property_api_container}}"' not in release_gate
    assert "--runtime-only" in release_gate
    assert "_completion/tours/property-tour-vendor-tooling-current.json" in release_gate
    assert "--drop-dir \"${tour_export_incoming_dir}\"" in release_gate
    assert "--public-tour-dir \"${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}\"" in release_gate
    assert "--tour-root \"${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}\"" in release_gate
    assert "--incoming-root \"${tour_export_incoming_dir}\"" in release_gate
    assert "_completion/property_tour_exports/release-gate-import-manifest.json" in release_gate
    assert "--import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json" in release_gate
    assert "--vendor-tooling-receipt _completion/tours/property-tour-vendor-tooling-current.json" in release_gate
    assert "_completion/provider_smoke/production-e2e-provider-matrix-current.json" in release_gate


def test_property_deploy_wrapper_uses_durable_api_artifact_path_for_import_manifest() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--canonical-compose-plan" in deploy_script
    assert "docker exec" not in deploy_script
    assert "docker cp" not in deploy_script


def test_property_deploy_wrapper_refreshes_release_hygiene_before_gold_status() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--forbid-candidate-output-authority" in deploy_script
    assert "check_property_release_hygiene.py" not in deploy_script
    assert "propertyquarry_gold_status.py" not in deploy_script


def test_property_deploy_wrapper_rebuilds_and_recreates_render_tools_runtime() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--canonical-compose-plan" in deploy_script
    assert '"${DC[@]}"' not in deploy_script


def test_property_release_gate_mentions_live_mobile_surface_smoke() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "required live mobile surface smoke" in release_gate
    assert "scripts/propertyquarry_live_mobile_surface_smoke.py" in release_gate
    assert "PROPERTYQUARRY_LIVE_MOBILE_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL" in release_gate


def test_property_gold_refresh_checks_omagic_adapter_in_api_runtime() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")

    assert "Vendor-tooling receipt from host with API runtime adapter proof" in refresh_script
    assert '--runtime-container "${API_CONTAINER}"' in refresh_script
    assert "--runtime-container ''" not in refresh_script
    assert "Vendor-tooling receipt from render container" not in refresh_script


def test_property_deploy_requires_existing_mobile_research_detail_without_seeding() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--signed-request-fd" in deploy_script
    assert "seed-research-detail-fixture" not in deploy_script


def test_property_deploy_refreshes_scene_video_receipts_before_gold_status() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")
    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--forbid-candidate-output-authority" in deploy_script
    assert "scene_video_readiness" not in deploy_script


def test_property_release_gate_wires_scene_video_refresh_packet_verifier_into_gold_status() -> None:
    release_gate = _read("scripts/property_release_gates.sh")
    live_release_gate = _read("scripts/propertyquarry_live_release_gates.sh")

    for required in (
        'scene_video_shared_env_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_FILE:-state/runtime/property_scene_video_shared.env}"',
        'scene_video_shared_env_runtime_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_RUNTIME_FILE:-/home/ea/property_scene_video_shared.env}"',
        "copy_scene_video_shared_env_to_container",
        "docker_exec_scene_video_python",
        "scripts/property_scene_video_shared_env.py",
        "scripts/verify_property_scene_video_readiness.py",
        "--output /data/artifacts/property-scene-video-readiness-release-gate-verifier-live-container.json",
        "--load-shared-env",
        "--output _completion/scene_video_readiness/release-gate-verifier.json",
        "scripts/property_scene_video_runtime_status.py",
        "--output /data/artifacts/property-scene-video-runtime-status-release-gate-live-container.json",
        "--output _completion/scene_video_readiness/runtime-status.json",
        "scripts/materialize_scene_video_provider_refresh_packet.py",
        "scripts/verify_scene_video_provider_refresh_packet.py",
        "scripts/propertyquarry_notify_scene_video_provider_refresh.py",
        "_completion/scene_video_readiness/runtime-status.json",
        "--scene-video-runtime-status-receipt _completion/scene_video_readiness/runtime-status.json",
        "_completion/scene_video_readiness/provider-refresh-packet.json",
        "_completion/scene_video_readiness/provider-refresh-packet-verifier.json",
        "_completion/scene_video_readiness/provider-refresh-telegram-report.json",
        "--scene-video-provider-refresh-packet _completion/scene_video_readiness/provider-refresh-packet.json",
        "--scene-video-provider-refresh-packet-verifier-receipt _completion/scene_video_readiness/provider-refresh-packet-verifier.json",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_PRINCIPAL_ID",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_BASE_URL",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_STATE",
        "PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME",
    ):
        assert required in release_gate

    assert release_gate.index('scene_video_refresh_notification_report="_completion/scene_video_readiness/provider-refresh-telegram-report.json"') < release_gate.index('PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_gold_status.py')
    assert "> /data/artifacts/property-scene-video-readiness-release-gate-verifier-live-container.json" not in release_gate
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE" in live_release_gate
    assert "EA_API_TOKEN" in live_release_gate
    assert "--require-research-detail" in live_release_gate
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE" not in live_release_gate
    assert "--seed-research-detail-fixture" not in live_release_gate
    assert "PROPERTYQUARRY_LIVE_MOBILE_TIMEOUT_MS" in _read("scripts/propertyquarry_live_mobile_surface_smoke.py")
    assert "_completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "--live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "scripts/propertyquarry_live_public_smoke.py" in live_release_gate
    assert "scripts/propertyquarry_live_authenticated_smoke.py" in live_release_gate
    assert '--expected-plan-label "${PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL:-Free}"' in live_release_gate
    assert "_completion/smoke/property-live-public-release-gate.json" in release_gate
    assert "_completion/smoke/property-live-authenticated-release-gate.json" in release_gate
    assert "--public-smoke-receipt _completion/smoke/property-live-public-release-gate.json" in release_gate
    assert "--authenticated-smoke-receipt _completion/smoke/property-live-authenticated-release-gate.json" in release_gate
    assert "scripts/verify_property_tour_provider_ownership.py" in release_gate
    assert "_completion/property_tour_ownership/release-gate.json" in release_gate
    assert "--tour-provider-ownership-receipt _completion/property_tour_ownership/release-gate.json" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED" in release_gate
    assert "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED" in release_gate
    assert "tests/test_property_live_mobile_surface_smoke.py" in release_gate
    assert "tests/test_property_live_http_security.py" in release_gate
    assert "tests/test_property_live_presentation_security.py" in release_gate
    assert "tests/test_property_live_release_provenance.py" in release_gate
    assert "tests/test_propertyquarry_live_telegram_delivery.py" in release_gate
    assert "tests/test_property_public_tour_provider_retirement.py" in release_gate


def test_property_gold_refresh_wires_scene_video_runtime_status_into_gold_status() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")

    for required in (
        'scene_video_shared_env_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_FILE:-state/runtime/property_scene_video_shared.env}"',
        'scene_video_shared_env_runtime_file="${PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_RUNTIME_FILE:-/home/ea/property_scene_video_shared.env}"',
        "copy_scene_video_shared_env_to_container",
        "docker_exec_scene_video_python",
        "refresh_scene_video_receipts",
        "scripts/property_scene_video_shared_env.py",
        "scripts/property_scene_video_runtime_status.py",
        "property-scene-video-runtime-status-current.json",
        "_completion/scene_video_readiness/runtime-status.json",
        "--scene-video-runtime-status-receipt",
    ):
        assert required in refresh_script


def test_property_gold_refresh_can_send_scene_video_provider_refresh_notification() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")

    for required in (
        "scripts/propertyquarry_notify_scene_video_provider_refresh.py",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_PRINCIPAL_ID",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_BASE_URL",
        "PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_STATE",
        "PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME",
        "_completion/scene_video_readiness/provider-refresh-telegram-report.json",
        '--packet "${scene_video_refresh_packet}"',
        '--verifier "${scene_video_refresh_packet_verifier}"',
        '--runtime-status "${scene_video_runtime_status_receipt}"',
        'printf \'{"status":"skipped","reason":"PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_REFRESH_NOTIFICATION_ENABLED_not_set"}\\n\' > "${scene_video_refresh_notification_report}"',
        "Scene-video provider refresh notification failed",
    ):
        assert required in refresh_script

    assert refresh_script.index('scene_video_refresh_notification_report="_completion/scene_video_readiness/provider-refresh-telegram-report.json"') < refresh_script.index('log_step "Gold-status receipt"')


def test_property_gold_refresh_catalog_probe_is_read_only() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")
    catalog_step = refresh_script.index('"Provider catalog smoke receipt"')
    matrix_step = refresh_script.index('"Provider E2E matrix receipt"')

    assert catalog_step < refresh_script.index("--no-execute-search-matrix", catalog_step) < matrix_step
    assert catalog_step < refresh_script.index("--no-cross-country-sanitization", catalog_step) < matrix_step
    assert matrix_step < refresh_script.index("--execute-search-matrix", matrix_step)


def test_property_release_gate_runs_generated_reconstruction_glb_smoke() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "scripts/ensure_propertyquarry_render_bridge_runtime.py" in release_gate
    assert "live generated-reconstruction GLB export smoke" in release_gate
    assert "service-owned generated-reconstruction smoke" in release_gate
    assert "scripts/property_runtime_reconstruction_smoke.py" in release_gate
    assert "scripts/property_service_generated_reconstruction_smoke.py" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_SMOKE_SLUG" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_SERVICE_GENERATED_RECONSTRUCTION_SMOKE_SLUG" in release_gate
    assert "PROPERTYQUARRY_SERVICE_GENERATED_RECONSTRUCTION_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_LIVE_HOST_HEADER" in release_gate
    assert "--require-public-contract" in release_gate
    assert "scripts/property_service_generated_reconstruction_smoke.py" in release_gate
    assert '--host-header "${PROPERTYQUARRY_LIVE_HOST_HEADER:-propertyquarry.com}"' in release_gate
    assert "--require-browser-shell" in release_gate
    assert "--require-browser-shell" in release_gate
    assert '--host-header "${PROPERTYQUARRY_LIVE_HOST_HEADER:-propertyquarry.com}"' in release_gate
    assert "--require-glb" in release_gate
    assert "_completion/tours/property-render-bridge-runtime-release-gate.json" in release_gate
    assert "_completion/tours/property-runtime-reconstruction-release-gate.json" in release_gate
    assert "_completion/tours/property-service-generated-reconstruction-release-gate.json" in release_gate
    assert "--runtime-reconstruction-receipt _completion/tours/property-runtime-reconstruction-release-gate.json" in release_gate
    assert "--service-generated-reconstruction-receipt _completion/tours/property-service-generated-reconstruction-release-gate.json" in release_gate
    assert "--fail-on-error" in release_gate


def test_property_gold_refresh_runs_generated_reconstruction_browser_shell_smoke() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")

    assert "scripts/ensure_propertyquarry_render_bridge_runtime.py" in refresh_script
    assert "scripts/property_runtime_reconstruction_smoke.py" in refresh_script
    assert "scripts/property_service_generated_reconstruction_smoke.py" in refresh_script
    assert "--public-base-url \"${BASE_URL}\"" in refresh_script
    assert '--host-header "${HOST_HEADER}"' in refresh_script
    assert "--require-public-contract" in refresh_script
    assert "--require-browser-shell" in refresh_script
    assert "--require-browser-shell" in refresh_script
    assert "--require-glb" in refresh_script
    assert "_completion/tours/property-render-bridge-runtime-current.json" in refresh_script
    assert "_completion/tours/property-runtime-reconstruction-release-gate.json" in refresh_script
    assert "PROPERTYQUARRY_SERVICE_GENERATED_RECONSTRUCTION_SMOKE_SLUG" in refresh_script
    assert "_completion/tours/property-service-generated-reconstruction-current.json" in refresh_script
    assert "--service-generated-reconstruction-receipt" in refresh_script
    assert '--runtime-container "${API_CONTAINER}"' in refresh_script


def test_property_gold_refresh_runs_walkthrough_quality_on_host_toolchain() -> None:
    refresh_script = _read("scripts/refresh_propertyquarry_current_gold_receipts.sh")

    provider_index = refresh_script.index(
        "scripts/propertyquarry_walkthrough_provider_proof_gate.py"
    )
    quality_index = refresh_script.index(
        "scripts/propertyquarry_walkthrough_quality_gate.py"
    )
    stale_receipt_clear_index = refresh_script.index(
        'rm -f "${walkthrough_provider_proof_receipt}" "${walkthrough_quality_receipt}"'
    )
    assert stale_receipt_clear_index < provider_index
    assert provider_index < quality_index
    assert "PROPERTYQUARRY_WALKTHROUGH_PROVIDER_PROOF_TIMEOUT_SECONDS" in refresh_script
    assert "PROPERTYQUARRY_WALKTHROUGH_QUALITY_PROCESS_TIMEOUT_SECONDS" in refresh_script
    assert "PROPERTYQUARRY_WALKTHROUGH_QUALITY_FFPROBE_TIMEOUT_SECONDS" in refresh_script
    assert "PROPERTYQUARRY_WALKTHROUGH_QUALITY_FRAME_SAMPLE_TIMEOUT_SECONDS" in refresh_script
    assert refresh_script.count('--tour-root "${walkthrough_tour_root}"') == 2
    assert '--provider-proof-receipt "${walkthrough_provider_proof_receipt}"' in refresh_script
    assert '"--walkthrough-provider-proof-receipt" "${walkthrough_provider_proof_receipt}"' in refresh_script
    assert "python /app/scripts/propertyquarry_walkthrough_quality_gate.py" not in refresh_script


def test_property_release_gate_binds_quality_to_provider_proof_on_one_tour_root() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    provider_index = release_gate.index(
        "scripts/propertyquarry_walkthrough_provider_proof_gate.py"
    )
    quality_index = release_gate.index(
        "scripts/propertyquarry_walkthrough_quality_gate.py"
    )
    assert provider_index < quality_index
    assert release_gate.count('--tour-root "${walkthrough_provider_proof_tour_root}"') == 2
    assert (
        "--provider-proof-receipt _completion/smoke/"
        "property-live-walkthrough-provider-proof-release-gate.json"
    ) in release_gate


def test_property_release_gate_invokes_launch_gold_with_full_explicit_receipts() -> None:
    release_gate = _read("scripts/property_release_gates.sh")
    gold_call = release_gate.split(
        'PYTHONPATH=ea "${PYTHON_BIN}" scripts/propertyquarry_gold_status.py \\\n',
        1,
    )[1].split("  --fail-on-blocked", 1)[0]

    for required_flag in (
        "--profile launch",
        "--performance-receipt",
        "--continuous-ux-receipt",
        "--live-mobile-receipt",
        "--accessibility-receipt",
        "--failure-state-receipt",
        "--activation-to-value-receipt",
        "--public-smoke-receipt",
        "--authenticated-smoke-receipt",
        "--billing-receipt",
        "--whole-project-scope-receipt",
        "--security-posture-receipt",
        "--release-hygiene-receipt",
        "--id-austria-receipt",
        "--provider-catalog-receipt",
        "--provider-matrix-receipt",
        "--slo-metrics-snapshot",
        "--slo-metrics-probe",
        "--monitoring-runtime-receipt",
        "--prometheus-range-receipt",
        "--prometheus-range-response",
        "--alert-delivery-receipt",
        "--require-launch-evidence",
        "--expected-release-sha",
        "--expected-image-digest",
        "--expected-teable-origin",
        "--expected-teable-base-id-sha256",
        "--expected-evidence-overlay-phase",
    ):
        assert required_flag in gold_call
    for required_env in (
        "PROPERTYQUARRY_CONTINUOUS_UX_RECEIPT",
        "PROPERTYQUARRY_FAILURE_STATE_RECEIPT",
        "PROPERTYQUARRY_ACTIVATION_TO_VALUE_RECEIPT",
        "PROPERTYQUARRY_PROVIDER_CATALOG_RECEIPT",
    ):
        assert required_env in release_gate
    assert (
        'expected_public_origin="${PROPERTYQUARRY_PUBLIC_ORIGIN:-'
        '${PROPERTYQUARRY_EXPECTED_RELEASE_PUBLIC_ORIGIN:-}}"'
    ) in release_gate
    assert "PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN" in release_gate
    assert "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256" in release_gate
    gold_index = release_gate.index("scripts/propertyquarry_gold_status.py")
    for receipt_writer in (
        "property-security-posture-release-gate.json",
        "property-release-hygiene-release-gate.json",
        "property-whole-project-scope-release-gate.json",
    ):
        assert release_gate.index(receipt_writer) < gold_index


def test_property_deploy_refreshes_service_generated_reconstruction_before_gold_status() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    _assert_external_deploy_controller_handoff(deploy_script)
    assert "--forbid-candidate-output-authority" in deploy_script
    assert "property_service_generated_reconstruction_smoke.py" not in deploy_script


def test_property_release_gate_sends_gold_notification_when_green() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "scripts/propertyquarry_notify_gold_status.py" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_STATE" in release_gate
    assert "PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME" in release_gate
    assert "_completion/property_gold_status/telegram-notify-report.json" in release_gate
    assert "warning: PropertyQuarry gold notification script failed." in release_gate


def test_readme_separates_disposable_compose_from_production_handoff() -> None:
    readme = " ".join(_read("README.md").split())

    assert "make deploy" in readme
    assert "scripts/deploy_propertyquarry.sh" in readme
    assert "## Disposable local development" in readme
    assert (
        "EA_RUNTIME_MODE=dev docker compose -f docker-compose.property.yml up -d --build"
        in readme
    )
    assert "## Production release handoff" in readme
    assert "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST" in readme
    assert "propertyquarry-deploy-preflight-request.json" in readme
    assert "./scripts/deploy_propertyquarry.sh --preflight-only" in readme
    assert "A preflight request is operation-bound and non-authorizing" in readme
    assert "propertyquarry-deploy-run-request.json" in readme
    assert "independently installed release controller" in readme
    assert "The caller must remain unprivileged, have no Docker daemon authority" in readme
    assert "docs/PROPERTYQUARRY_RELEASE_CONTROL_PROTOCOL_V1.md" in readme
    assert "make propertyquarry-release-protocol-contracts" in readme
    assert "does not verify signatures, establish trust, authorize an operation" in readme
    assert "There is no local Compose fallback." in readme
    assert "POSTGRES_PASSWORD" in readme
    assert "EA_SIGNING_SECRET" in readme
    assert "EA_API_TOKEN or local access settings" in readme
    assert "PROPERTYQUARRY_RUNTIME_GATES=1" in readme
    assert "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL=http://localhost:8097" in readme
    assert "EA_HOST_PORT=8097 make deploy" not in readme
    assert "PROPERTYQUARRY_COMPOSE_PROJECT_NAME=propertyquarry-next" not in readme
    assert "PROPERTYQUARRY_API_CONTAINER_NAME=propertyquarry-api-next" not in readme
    assert "PROPERTYQUARRY_DEPLOY_PROVIDER_E2E=1" not in readme


def test_schema_migration_docs_reserve_production_for_signed_controller() -> None:
    migration_docs = _read("docs/PROPERTYQUARRY_SCHEMA_MIGRATIONS.md")
    production = " ".join(
        migration_docs.split("## Production deploy phase\n", 1)[1]
        .split("## Disposable development and test targets\n", 1)[0]
        .split()
    )
    disposable = " ".join(
        migration_docs.split("## Disposable development and test targets\n", 1)[1]
        .split("## Runtime readiness\n", 1)[0]
        .split()
    )

    assert "candidate checkout has no production migration authority" in production
    assert "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST" in production
    assert "propertyquarry-deploy-preflight-request.json" in production
    assert "./scripts/deploy_propertyquarry.sh --preflight-only" in production
    assert "preflight request is operation-bound and cannot authorize mutation" in production
    assert "distinct, fresh `deploy-run` signed request" in production
    assert (
        "Direct Compose and Python migration commands are not a production fallback"
        in production
    )
    assert "docker compose" not in production
    assert "migrate_property_search_storage.py" not in production
    assert "disposable local development database" in disposable
    assert "EA_RUNTIME_MODE=dev" in disposable
    assert "docker compose -f docker-compose.property.yml up -d --build" in disposable
    assert "python3 scripts/migrate_property_search_storage.py" in disposable
    assert "run the candidate release's deploy migration" not in migration_docs


def test_environment_matrix_separates_local_compose_from_production_handoff() -> None:
    matrix = _read("ENVIRONMENT_MATRIX.md")

    assert "docker-compose.property.yml` directly only for a disposable local development target" in matrix
    assert "EA_RUNTIME_MODE=dev" in matrix
    assert "`make deploy` invokes the unprivileged production handoff" in matrix
    assert "operation-bound signed request" in matrix
    assert "independently installed release controller" in matrix
    assert "Use `docker-compose.property.yml` or `make deploy`" not in matrix


def test_release_checklist_requires_distinct_preflight_and_deploy_requests() -> None:
    checklist = _read("RELEASE_CHECKLIST.md")

    assert "propertyquarry-deploy-preflight-request.json" in checklist
    assert "It must bind `deploy-preflight`, cannot authorize mutation" in checklist
    assert "never reused for deployment" in checklist
    assert "distinct fresh `deploy-run` request" in checklist
    assert "propertyquarry-deploy-run-request.json" in checklist


def test_runtime_hard_exit_gates_can_extend_into_propertyquarry_live_runtime() -> None:
    script = _read("scripts/runtime_hard_exit_gates.sh")
    smoke_help = _read("scripts/smoke_help.sh")

    for required in (
        "PROPERTYQUARRY_RUNTIME_GATES=1",
        "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID",
        "scripts/propertyquarry_live_public_smoke.py",
        "scripts/propertyquarry_live_authenticated_smoke.py",
        "scripts/property_live_provider_smoke.py",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0",
        "verify_pocket_audio_archive.py failed, continuing because Pocket archive backfill is outside the PropertyQuarry runtime lane",
        "EA_API_TOKEN is not set; skipping authenticated/mobile/provider PropertyQuarry runtime smokes",
    ):
        assert required in script

    for required in (
        "scripts/deploy_propertyquarry.sh",
        "scripts/propertyquarry_live_public_smoke.py",
        "scripts/propertyquarry_live_authenticated_smoke.py",
        "scripts/property_live_provider_smoke.py",
    ):
        assert required in smoke_help


def test_property_dockerfile_allowlists_runtime_scripts() -> None:
    dockerfile = _read("ea/Dockerfile.property")

    assert "COPY . /tmp/src" not in dockerfile
    assert "COPY ea/requirements.txt /app/requirements.txt" in dockerfile
    assert "COPY ea/requirements.lock /app/requirements.lock" in dockerfile
    assert dockerfile.index("COPY ea/requirements.txt /app/requirements.txt") < dockerfile.index("pip install --no-cache-dir")
    assert dockerfile.index("pip install --no-cache-dir") < dockerfile.index("COPY ea/app /app/app")
    assert "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" in dockerfile
    assert "COPY scripts/property_magicfit_env.py /app/scripts/property_magicfit_env.py" in dockerfile
    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "COPY scripts/render_omagic_property_model_walkthrough.py /app/scripts/render_omagic_property_model_walkthrough.py" in dockerfile
    assert "COPY scripts/render_magicai_model_upload_adapter.py /app/scripts/render_magicai_model_upload_adapter.py" in dockerfile
    assert "COPY scripts/property_scene_video_readiness_report.py /app/scripts/property_scene_video_readiness_report.py" in dockerfile
    assert "COPY scripts/verify_property_scene_video_readiness.py /app/scripts/verify_property_scene_video_readiness.py" in dockerfile
    assert "COPY scripts/materialize_scene_video_provider_refresh_packet.py /app/scripts/materialize_scene_video_provider_refresh_packet.py" in dockerfile
    assert "COPY scripts/verify_scene_video_provider_refresh_packet.py /app/scripts/verify_scene_video_provider_refresh_packet.py" in dockerfile
    assert "COPY scripts/merge_scene_video_provider_accounts_env.py /app/scripts/merge_scene_video_provider_accounts_env.py" in dockerfile
    assert "COPY scripts/import_3dvista_export.py /app/scripts/import_3dvista_export.py" in dockerfile
    assert "COPY scripts/import_pano2vr_export.py /app/scripts/import_pano2vr_export.py" in dockerfile
    assert "COPY scripts/import_krpano_walkable_scene.py /app/scripts/import_krpano_walkable_scene.py" in dockerfile
    assert "COPY scripts/import_property_tour_exports.py /app/scripts/import_property_tour_exports.py" in dockerfile
    assert "COPY scripts/attach_provider_tour_layer.py /app/scripts/attach_provider_tour_layer.py" in dockerfile
    assert "COPY scripts/materialize_property_tour_export_manifest.py /app/scripts/materialize_property_tour_export_manifest.py" in dockerfile
    assert "COPY scripts/property_tour_runtime_paths.py /app/scripts/property_tour_runtime_paths.py" in dockerfile
    assert "COPY scripts/generate_property_reconstruction.py /app/scripts/generate_property_reconstruction.py" in dockerfile
    assert "COPY scripts/property_reconstruction_render_bridge.py /app/scripts/property_reconstruction_render_bridge.py" in dockerfile
    assert "COPY scripts/import_magicfit_walkthrough.py /app/scripts/import_magicfit_walkthrough.py" in dockerfile
    assert "COPY scripts/verify_property_tour_controls.py /app/scripts/verify_property_tour_controls.py" in dockerfile
    assert "COPY scripts/verify_property_tour_vendor_tooling.py /app/scripts/verify_property_tour_vendor_tooling.py" in dockerfile
    assert "COPY scripts/intake_3dvista_gold_artifact.py /app/scripts/intake_3dvista_gold_artifact.py" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "for script in /tmp/src/scripts/*" not in dockerfile
    assert 'for script in "$APP_SRC"/scripts/*' not in dockerfile
    assert 'cp "$script" /app/scripts/' not in dockerfile
    assert "build_propertyquarry_magicfit_promo.py" not in dockerfile


def test_runtime_dockerfiles_fail_closed_for_worker_and_scheduler_health() -> None:
    for path in ("Dockerfile", "ea/Dockerfile", "ea/Dockerfile.property"):
        dockerfile = _read(path)
        healthcheck = dockerfile[dockerfile.index("HEALTHCHECK") :]

        assert 'worker|scheduler) exec python -m app.scheduler_healthcheck' in healthcheck
        assert 'worker|scheduler) exit 0' not in healthcheck


def test_property_web_dockerfile_keeps_reconstruction_lightweight_and_excludes_browser_payloads() -> None:
    dockerfile = _read("ea/Dockerfile.property-web")

    assert "COPY . /tmp/src" not in dockerfile
    assert "COPY ea/requirements.txt /app/requirements.txt" in dockerfile
    assert "COPY ea/requirements.lock /app/requirements.lock" in dockerfile
    assert "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" in dockerfile
    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "COPY scripts/render_onemin_property_i2v_segment.py /app/scripts/render_onemin_property_i2v_segment.py" in dockerfile
    assert "COPY scripts/render_omagic_property_model_walkthrough.py /app/scripts/render_omagic_property_model_walkthrough.py" in dockerfile
    assert "COPY scripts/render_magicai_model_upload_adapter.py /app/scripts/render_magicai_model_upload_adapter.py" in dockerfile
    assert "COPY scripts/property_scene_video_readiness_report.py /app/scripts/property_scene_video_readiness_report.py" in dockerfile
    assert "COPY scripts/discover_property_tour_exports.py /app/scripts/discover_property_tour_exports.py" in dockerfile
    assert "COPY scripts/materialize_property_tour_export_manifest.py /app/scripts/materialize_property_tour_export_manifest.py" in dockerfile
    assert "COPY scripts/generate_property_reconstruction.py /app/scripts/generate_property_reconstruction.py" in dockerfile
    assert "COPY scripts/verify_property_tour_vendor_tooling.py /app/scripts/verify_property_tour_vendor_tooling.py" not in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" not in dockerfile
    assert "python -m playwright install --with-deps chromium" not in dockerfile
    assert "blender" not in dockerfile.lower()
    assert "colmap" not in dockerfile.lower()
    assert "meshlab" not in dockerfile.lower()
    assert "ffmpeg" not in dockerfile.lower()
    assert "espeak" not in dockerfile.lower()
    assert "imagemagick" not in dockerfile.lower()
    assert "libimage-exiftool-perl" not in dockerfile.lower()
    assert "for script in /tmp/src/scripts/*" not in dockerfile
    assert 'cp "$script" /app/scripts/' not in dockerfile


def test_property_runtime_copied_scripts_do_not_depend_on_fleet_paths() -> None:
    dockerfile = _read("ea/Dockerfile.property")
    copied_scripts = re.findall(r"COPY\s+scripts/([^\s]+)\s+/app/scripts/", dockerfile)

    assert copied_scripts == [
        "willhaben_property_packet.py",
        "property_magicfit_env.py",
        "mootion_movie_worker.py",
        "render_magicfit_property_flythrough.py",
        "render_onemin_property_i2v_segment.py",
        "render_omagic_property_model_walkthrough.py",
        "render_magicai_model_upload_adapter.py",
        "property_scene_video_readiness_report.py",
        "verify_property_scene_video_readiness.py",
        "materialize_scene_video_provider_refresh_packet.py",
        "verify_scene_video_provider_refresh_packet.py",
        "merge_scene_video_provider_accounts_env.py",
        "import_3dvista_export.py",
        "import_pano2vr_export.py",
        "import_krpano_walkable_scene.py",
        "import_property_tour_exports.py",
        "attach_provider_tour_layer.py",
        "discover_property_tour_exports.py",
        "materialize_property_tour_export_manifest.py",
        "property_tour_runtime_paths.py",
        "propertyquarry_playwright_runtime.py",
        "generate_property_reconstruction.py",
        "property_reconstruction_render_bridge.py",
        "import_magicfit_walkthrough.py",
        "verify_property_tour_controls.py",
        "verify_property_tour_vendor_tooling.py",
        "intake_3dvista_gold_artifact.py",
    ]
    for script_name in copied_scripts:
        body = _read(f"scripts/{script_name}")
        assert "/docker/fleet" not in body, script_name
        assert "/tmp/propertyquarry" not in body, script_name


def test_property_compose_container_names_are_recoverable() -> None:
    compose = _read("docker-compose.property.yml")

    assert "dockerfile: ea/Dockerfile.property-web" in compose
    assert 'image: "${PROPERTYQUARRY_WEB_IMAGE:-propertyquarry-web-runtime:latest}"' in compose
    assert "propertyquarry-render-tools:" in compose
    assert "dockerfile: ea/Dockerfile.property" in compose
    assert 'image: "${PROPERTYQUARRY_RENDER_IMAGE:-propertyquarry-render-runtime:latest}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-propertyquarry-scheduler}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-db-live}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_RENDER_CONTAINER_NAME:-propertyquarry-render-tools}"' in compose
    assert compose.count("path: ./state/runtime/property_scene_video_shared.env") == 3
    migration_section = compose.split("  propertyquarry-migrate:", 1)[1].split(
        "  propertyquarry-scheduler:", 1
    )[0]
    assert "property_scene_video_shared.env" not in migration_section
    assert "env_file:" not in migration_section
    assert "EA_ROLE: property-search-migrate" in migration_section
    assert 'command: ["python", "-m", "app.product.property_search_schema", "migrate"]' in migration_section
    assert 'restart: "no"' in migration_section
    assert "EA_SCHEDULER_HEARTBEAT_PATH: /data/artifacts/propertyquarry-scheduler-heartbeat.json" in compose
    assert 'EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS: "${EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS:-900}"' in compose
    assert 'test: ["CMD", "python", "-m", "app.scheduler_healthcheck"]' in compose
    scheduler_section = compose.split("  propertyquarry-scheduler:", 1)[1].split("  propertyquarry-db:", 1)[0]
    assert "disable: true" not in scheduler_section
    render_section = compose.split("  propertyquarry-render-tools:", 1)[1].split("  propertyquarry-db:", 1)[0]
    assert "profiles:" not in render_section
    assert "- render-tools" not in render_section
    assert 'command: ["python", "/app/scripts/property_reconstruction_render_bridge.py"]' in render_section
    assert 'PROPERTYQUARRY_RECONSTRUCTION_RENDER_HOST: "0.0.0.0"' in render_section
    assert (
        'PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN: '
        '"${PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN:?'
    ) in render_section
    assert "command -v ffmpeg" in render_section
    assert "command -v blender" in render_section
    assert "command -v colmap" in render_section
    assert "command -v exiftool" in render_section
    assert "command -v convert" in render_section
    assert "python -c 'import numpy'" in render_section
    assert "http://127.0.0.1:8091/health" in render_section
    assert "http://127.0.0.1:8090/health/live" not in render_section
