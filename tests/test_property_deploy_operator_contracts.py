from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_make_deploy_uses_hardened_propertyquarry_wrapper() -> None:
    makefile = _read("Makefile")

    assert "PROPERTYQUARRY_COMPOSE_FILE=docker-compose.property.yml bash scripts/deploy_propertyquarry.sh" in makefile
    assert "PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh" in makefile
    assert "docker compose -f docker-compose.property.yml up -d --build --remove-orphans" not in makefile


def test_propertyquarry_deploy_wrapper_preflights_prod_and_probes_runtime() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")

    for required in (
        "POSTGRES_PASSWORD",
        "EA_RUNTIME_MODE",
        "EA_SIGNING_SECRET",
        "EA_API_TOKEN",
        "EA_CF_ACCESS_TEAM_DOMAIN",
        "EA_CF_ACCESS_AUD",
        "EA_ALLOW_LOOPBACK_NO_AUTH",
        "EA_HOST_PORT",
        "PROPERTYQUARRY_COMPOSE_PROJECT_NAME",
        "PROPERTYQUARRY_COMPOSE_PROBE_TIMEOUT_SECONDS",
        "PROPERTYQUARRY_API_CONTAINER_NAME",
        "PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME",
        "PROPERTYQUARRY_DB_CONTAINER_NAME",
        "PROPERTYQUARRY_CLOUDFLARED_CONTAINER_NAME",
        "docker compose",
        "DC+=(-f",
        "docker-compose.property.yml",
        "propertyquarry-api",
        "propertyquarry-scheduler",
        "propertyquarry-db",
        "propertyquarry-cloudflared",
        "/health",
        "/health/ready",
        "/version",
        "/app/properties",
        "scripts/propertyquarry_live_public_smoke.py",
        "scripts/propertyquarry_live_authenticated_smoke.py",
        "scripts/property_live_provider_smoke.py",
        "propertyquarry_deploy_public_smoke.json",
        "propertyquarry_deploy_authenticated_smoke.json",
        "propertyquarry_deploy_provider_smoke.json",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0",
        "PropertyQuarry",
        "storage_backend",
        "postgres",
        "--preflight-only",
        "restart_existing_cloudflared_tunnel",
        "docker restart",
        "did not restart cleanly after API deploy",
    ):
        assert required in script

    assert re.search(r"EA_RUNTIME_MODE=prod requires EA_API_TOKEN or Cloudflare Access", script)
    assert re.search(r"EA_RUNTIME_MODE=prod forbids EA_ALLOW_LOOPBACK_NO_AUTH=1", script)
    assert re.search(r"Expected /app/properties to require auth", script)
    assert "timeout" in script
    assert "did not answer within" in script


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


def test_property_tour_export_scripts_share_container_incoming_path() -> None:
    discovery = _read("scripts/discover_property_tour_exports.py")
    manifest = _read("scripts/materialize_property_tour_export_manifest.py")

    assert 'or "/data/incoming_property_tours"' in discovery
    assert 'or "/data/incoming_property_tours"' in manifest
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


def test_property_release_gate_wires_tour_import_manifest_into_gold_status() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "scripts/materialize_property_tour_export_manifest.py" in release_gate
    assert "tour_export_incoming_dir=" in release_gate
    assert "property_api_container=\"${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}\"" in release_gate
    assert "docker exec \"${property_api_container}\" python /app/scripts/verify_property_tour_controls.py" in release_gate
    assert "--tour-root /data/public_property_tours" in release_gate
    assert "property-tour-controls-release-gate-live-container.json" in release_gate
    assert "docker cp \"${property_api_container}:/data/artifacts/property-tour-controls-release-gate-live-container.json\"" in release_gate
    assert "--drop-dir \"${tour_export_incoming_dir}\"" in release_gate
    assert "--incoming-root \"${tour_export_incoming_dir}\"" in release_gate
    assert "_completion/property_tour_exports/release-gate-import-manifest.json" in release_gate
    assert "--import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json" in release_gate


def test_property_release_gate_mentions_live_mobile_surface_smoke() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "required live mobile surface smoke" in release_gate
    assert "scripts/propertyquarry_live_mobile_surface_smoke.py" in release_gate
    assert "PROPERTYQUARRY_LIVE_MOBILE_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE" in release_gate
    assert "EA_API_TOKEN" in release_gate
    assert "--require-research-detail" in release_gate
    assert "_completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "--live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "tests/test_property_live_mobile_surface_smoke.py" in release_gate


def test_readme_documents_hardened_deploy_and_port_override() -> None:
    readme = _read("README.md")

    assert "make deploy" in readme
    assert "scripts/deploy_propertyquarry.sh" in readme
    assert "EA_HOST_PORT=8097 make deploy" in readme
    assert "PROPERTYQUARRY_COMPOSE_PROJECT_NAME=propertyquarry-next" in readme
    assert "PROPERTYQUARRY_API_CONTAINER_NAME=propertyquarry-api-next" in readme
    assert "POSTGRES_PASSWORD" in readme
    assert "EA_SIGNING_SECRET" in readme
    assert "EA_API_TOKEN or Cloudflare Access" in readme
    assert "PROPERTYQUARRY_RUNTIME_GATES=1" in readme
    assert "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL=http://localhost:8097" in readme


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
        "EA_API_TOKEN is not set; skipping authenticated/provider PropertyQuarry runtime smokes",
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
    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "COPY scripts/import_3dvista_export.py /app/scripts/import_3dvista_export.py" in dockerfile
    assert "COPY scripts/import_pano2vr_export.py /app/scripts/import_pano2vr_export.py" in dockerfile
    assert "COPY scripts/import_krpano_walkable_scene.py /app/scripts/import_krpano_walkable_scene.py" in dockerfile
    assert "COPY scripts/import_property_tour_exports.py /app/scripts/import_property_tour_exports.py" in dockerfile
    assert "COPY scripts/materialize_property_tour_export_manifest.py /app/scripts/materialize_property_tour_export_manifest.py" in dockerfile
    assert "COPY scripts/import_magicfit_walkthrough.py /app/scripts/import_magicfit_walkthrough.py" in dockerfile
    assert "COPY scripts/verify_property_tour_controls.py /app/scripts/verify_property_tour_controls.py" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "for script in /tmp/src/scripts/*" not in dockerfile
    assert 'for script in "$APP_SRC"/scripts/*' not in dockerfile
    assert 'cp "$script" /app/scripts/' not in dockerfile
    assert "build_propertyquarry_magicfit_promo.py" not in dockerfile


def test_property_runtime_copied_scripts_do_not_depend_on_fleet_paths() -> None:
    dockerfile = _read("ea/Dockerfile.property")
    copied_scripts = re.findall(r"COPY\s+scripts/([^\s]+)\s+/app/scripts/", dockerfile)

    assert copied_scripts == [
        "willhaben_property_packet.py",
        "render_magicfit_property_flythrough.py",
        "render_onemin_property_i2v_segment.py",
        "import_3dvista_export.py",
        "import_pano2vr_export.py",
        "import_krpano_walkable_scene.py",
        "import_property_tour_exports.py",
        "discover_property_tour_exports.py",
        "materialize_property_tour_export_manifest.py",
        "import_magicfit_walkthrough.py",
        "verify_property_tour_controls.py",
    ]
    for script_name in copied_scripts:
        body = _read(f"scripts/{script_name}")
        assert "/docker/fleet" not in body, script_name
        assert "/tmp/propertyquarry" not in body, script_name


def test_property_compose_container_names_are_recoverable() -> None:
    compose = _read("docker-compose.property.yml")

    assert 'container_name: "${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-propertyquarry-scheduler}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-db}"' in compose
    assert "EA_SCHEDULER_HEARTBEAT_PATH: /data/artifacts/propertyquarry-scheduler-heartbeat.json" in compose
    assert 'EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS: "${EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS:-900}"' in compose
    assert 'test: ["CMD", "python", "-m", "app.scheduler_healthcheck"]' in compose
    scheduler_section = compose.split("  propertyquarry-scheduler:", 1)[1].split("  propertyquarry-db:", 1)[0]
    assert "disable: true" not in scheduler_section
