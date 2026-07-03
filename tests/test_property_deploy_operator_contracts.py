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
        "scripts/propertyquarry_live_market_scope_smoke.py",
        "scripts/property_live_provider_smoke.py",
        "scripts/propertyquarry_gold_status.py",
        "scripts/propertyquarry_notify_gold_status.py",
        "propertyquarry_deploy_public_smoke.json",
        "propertyquarry_deploy_authenticated_smoke.json",
        "propertyquarry_deploy_market_scope_smoke.json",
        "propertyquarry_deploy_provider_smoke.json",
        "_completion/property_gold_status/release-gate.json",
        "propertyquarry-gold-status-latest.json",
        "_completion/property_gold_status/telegram-notify-report.json",
        "PROPERTYQUARRY_DEPLOY_PUBLIC_SMOKE_TIMEOUT_SECONDS:-8",
        "PROPERTYQUARRY_DEPLOY_AUTHENTICATED_SMOKE_TIMEOUT_SECONDS:-20",
        "PROPERTYQUARRY_DEPLOY_MARKET_SCOPE_SMOKE_TIMEOUT_SECONDS:-8",
        "PROPERTYQUARRY_DEPLOY_PROVIDER_SMOKE_TIMEOUT_SECONDS:-20",
        "PROPERTYQUARRY_DEPLOY_PROVIDER_SEARCH_RUN_TIMEOUT_SECONDS:-60",
        "PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES",
        "PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID",
        "PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL",
        "PROPERTYQUARRY_GOLD_NOTIFICATION_STATE",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BOOTSTRAP_EDGE",
        "PROPERTYQUARRY_DEPLOY_MAX_RUNTIME_NICE",
        "PROPERTYQUARRY_DEPLOY_TMP_DIR",
        "PROPERTYQUARRY_DEPLOY_PYTHON_BIN",
        "resolve_deploy_python_bin",
        "python_candidate_has_deploy_gate_modules",
        "python_candidate_has_playwright",
        "playwright.sync_api",
        '"PIL"',
        '"requests"',
        "Using deploy Python",
        "resolve_deploy_playwright_browsers_path",
        "playwright_browsers_path_has_chromium",
        "PLAYWRIGHT_BROWSERS_PATH",
        "Using Playwright browsers",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET",
        "scripts/bootstrap_billing_handoff_worker.py",
        "propertyquarry_billing_edge_worker.json",
        "PropertyQuarry billing worker bootstrap failed.",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1",
        "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN=0",
        "PropertyQuarry",
        "storage_backend",
        "postgres",
        "--preflight-only",
        "restart_existing_cloudflared_tunnel",
        "docker restart",
        "did not restart cleanly after API deploy",
        "normalise_deploy_process_priority",
        "BASHPID",
        "Deploy process started with host nice",
        'renice -n 0 -g "${pgid}"',
        'ps -o pid= -g "${pgid}"',
        'ps -o ppid= -p "${current_pid}"',
        "max_thread_nice_for_pid",
        "renice_process_threads_to_zero",
        "settle_runtime_priorities",
        'ps -T -o ni= -p "${host_pid}"',
        'ps -T -o tid= -p "${host_pid}"',
        "correcting all runtime threads to nice 0",
        "correct_service_runtime_priority_if_needed",
        "assert_service_runtime_priority",
        "correcting to nice 0",
        'renice -n 0 -p "${host_pid}"',
        "container_id_for_service",
        'docker ps -q --filter "name=^/${container_name}$"',
        "Web runtime would be CPU-starved under load",
        'up -d --remove-orphans "${db_service}"',
        'up -d --no-deps --force-recreate "${api_service}"',
        'up -d --no-deps --force-recreate "${scheduler_service}"',
        "Warning: PropertyQuarry gold notification script failed.",
        "--live-mobile-receipt _completion/smoke/property-live-mobile-surface-latest.json",
        "--public-smoke-receipt _completion/smoke/property-live-public-latest.json",
        "--authenticated-smoke-receipt _completion/smoke/property-live-authenticated-latest.json",
        "--billing-receipt _completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json",
    ):
        assert required in script

    assert re.search(r"EA_RUNTIME_MODE=prod requires EA_API_TOKEN or Cloudflare Access", script)
    assert re.search(r"EA_RUNTIME_MODE=prod forbids EA_ALLOW_LOOPBACK_NO_AUTH=1", script)
    assert re.search(r"Expected /app/properties to require auth", script)
    assert "timeout" in script
    assert "did not answer within" in script


def test_propertyquarry_deploy_wrapper_supports_focused_provider_country_matrix() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")

    assert "PROPERTYQUARRY_DEPLOY_PROVIDER_COUNTRIES" in script
    assert "provider_smoke_scope_args=(--all-search-ready-countries)" in script
    assert 'provider_country_args+=(--country "${country_code}")' in script
    assert '"${provider_smoke_scope_args[@]}"' in script
    assert "production-e2e-provider-matrix-${provider_country_scope_slug}-current.json" in script
    assert "provider verification: ${provider_smoke_scope_label}" in script


def test_propertyquarry_deploy_wrapper_resolves_live_smoke_identity_from_env_file() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")

    assert "live_smoke_principal_id=\"$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_PRINCIPAL_ID)\"" in script
    assert "live_smoke_principal_id=\"${live_smoke_principal_id:-$(effective_env_value EA_PRINCIPAL_ID)}\"" in script
    assert "live_smoke_principal_id=\"${live_smoke_principal_id:-$(effective_env_value EA_TELEGRAM_DEFAULT_PRINCIPAL_ID)}\"" in script
    assert "--principal-id \"${live_smoke_principal_id}\"" in script
    assert "live_smoke_plan_label=\"$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL)\"" in script
    assert "--expected-plan-label \"${live_smoke_plan_label}\"" in script
    assert "live_smoke_country_code=\"$(effective_env_value PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE)\"" in script
    assert "--country-code \"${live_smoke_country_code}\"" in script
    assert "live_provider_smoke_principal_id=\"$(effective_env_value PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID)\"" in script
    assert "PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID=\"${live_provider_smoke_principal_id}\"" in script
    assert "--principal-id \"${live_presentation_e2e_principal_id}\"" in script


def test_propertyquarry_deploy_mobile_smoke_covers_customer_app_surfaces() -> None:
    script = _read("scripts/deploy_propertyquarry.sh")

    for route in (
        "/app/properties",
        "/app/search",
        "/app/shortlist",
        "/app/agents",
        "/app/alerts",
        "/app/account",
        "/app/billing",
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
        "/app/research",
        "/app/properties/packets",
    ):
        assert route in script


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


def test_property_release_gate_runs_cached_evidence_overlay_contracts() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "cached evidence-overlay contracts for unavailable/stale/verified states and no inline source indexing" in release_gate
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
    assert "docker exec \"${property_render_container}\" python /app/scripts/verify_property_tour_vendor_tooling.py" in release_gate
    assert 'runtime_reconstruction_container="${PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER:-${property_render_container}}"' in release_gate
    assert 'runtime_reconstruction_container="${PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER:-${property_api_container}}"' not in release_gate
    assert "--runtime-only" in release_gate
    assert "property-tour-vendor-tooling-release-gate-live-container.json" in release_gate
    assert "docker cp \"${property_render_container}:/data/artifacts/property-tour-vendor-tooling-release-gate-live-container.json\"" in release_gate
    assert "_completion/tours/property-tour-vendor-tooling-current.json" in release_gate
    assert "--drop-dir \"${tour_export_incoming_dir}\"" in release_gate
    assert "--public-tour-dir \"${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}\"" in release_gate
    assert "--tour-root \"${EA_PUBLIC_TOUR_DIR:-${EA_ROOT}/state/public_property_tours}\"" in release_gate
    assert "--incoming-root \"${tour_export_incoming_dir}\"" in release_gate
    assert "_completion/property_tour_exports/release-gate-import-manifest.json" in release_gate
    assert "--import-manifest-receipt _completion/property_tour_exports/release-gate-import-manifest.json" in release_gate
    assert "--vendor-tooling-receipt _completion/tours/property-tour-vendor-tooling-current.json" in release_gate
    assert "_completion/provider_smoke/production-e2e-provider-matrix-current.json" in release_gate


def test_property_release_gate_mentions_live_mobile_surface_smoke() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "required live mobile surface smoke" in release_gate
    assert "scripts/propertyquarry_live_mobile_surface_smoke.py" in release_gate
    assert "PROPERTYQUARRY_LIVE_MOBILE_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_LIVE_SMOKE_BASE_URL" in release_gate


def test_property_deploy_seeds_default_mobile_research_detail_fixture() -> None:
    deploy_script = _read("scripts/deploy_propertyquarry.sh")

    assert "configured_mobile_research_detail_route=\"$(effective_env_value PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE)\"" in deploy_script
    assert "PROPERTYQUARRY_DEPLOY_MOBILE_SEED_RESEARCH_DETAIL_FIXTURE" in deploy_script
    assert 'if [[ -z "${configured_mobile_research_detail_route}" && -z "${mobile_seed_research_detail_fixture}" ]]; then' in deploy_script
    assert "mobile_seed_research_detail_fixture=1" in deploy_script
    assert "mobile_smoke_research_args=(--seed-research-detail-fixture)" in deploy_script


def test_property_release_gate_wires_scene_video_refresh_packet_verifier_into_gold_status() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    for required in (
        "scripts/verify_property_scene_video_readiness.py",
        "--output /data/artifacts/property-scene-video-readiness-release-gate-verifier-live-container.json",
        "--output _completion/scene_video_readiness/release-gate-verifier.json",
        "scripts/materialize_scene_video_provider_refresh_packet.py",
        "scripts/verify_scene_video_provider_refresh_packet.py",
        "_completion/scene_video_readiness/provider-refresh-packet.json",
        "_completion/scene_video_readiness/provider-refresh-packet-verifier.json",
        "--scene-video-provider-refresh-packet _completion/scene_video_readiness/provider-refresh-packet.json",
        "--scene-video-provider-refresh-packet-verifier-receipt _completion/scene_video_readiness/provider-refresh-packet-verifier.json",
    ):
        assert required in release_gate

    assert "> /data/artifacts/property-scene-video-readiness-release-gate-verifier-live-container.json" not in release_gate
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE" in release_gate
    assert "PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE" in release_gate
    assert "EA_API_TOKEN" in release_gate
    assert "--require-research-detail" in release_gate
    assert "--seed-research-detail-fixture" in release_gate
    assert "PROPERTYQUARRY_LIVE_MOBILE_TIMEOUT_MS" in _read("scripts/propertyquarry_live_mobile_surface_smoke.py")
    assert "_completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "--live-mobile-receipt _completion/smoke/property-live-mobile-release-gate.json" in release_gate
    assert "scripts/propertyquarry_live_public_smoke.py" in release_gate
    assert "scripts/propertyquarry_live_authenticated_smoke.py" in release_gate
    assert "_completion/smoke/property-live-public-release-gate.json" in release_gate
    assert "_completion/smoke/property-live-authenticated-release-gate.json" in release_gate
    assert "--public-smoke-receipt _completion/smoke/property-live-public-release-gate.json" in release_gate
    assert "--authenticated-smoke-receipt _completion/smoke/property-live-authenticated-release-gate.json" in release_gate
    assert "scripts/verify_property_tour_provider_ownership.py" in release_gate
    assert "_completion/property_tour_ownership/release-gate.json" in release_gate
    assert "--tour-provider-ownership-receipt _completion/property_tour_ownership/release-gate.json" in release_gate
    assert "tests/test_property_live_mobile_surface_smoke.py" in release_gate


def test_property_release_gate_runs_generated_reconstruction_glb_smoke() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "live generated-reconstruction GLB export smoke" in release_gate
    assert "scripts/property_runtime_reconstruction_smoke.py" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_CONTAINER" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_SMOKE_SLUG" in release_gate
    assert "PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_BASE_URL" in release_gate
    assert "--require-browser" in release_gate
    assert "--require-glb" in release_gate
    assert "_completion/tours/property-runtime-reconstruction-release-gate.json" in release_gate
    assert "--runtime-reconstruction-receipt _completion/tours/property-runtime-reconstruction-release-gate.json" in release_gate
    assert "--fail-on-error" in release_gate


def test_property_release_gate_sends_gold_notification_when_green() -> None:
    release_gate = _read("scripts/property_release_gates.sh")

    assert "scripts/propertyquarry_notify_gold_status.py" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_PRINCIPAL_ID" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_BASE_URL" in release_gate
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_STATE" in release_gate
    assert "_completion/property_gold_status/telegram-notify-report.json" in release_gate
    assert "warning: PropertyQuarry gold notification script failed." in release_gate


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


def test_property_web_dockerfile_keeps_reconstruction_lightweight_and_excludes_browser_payloads() -> None:
    dockerfile = _read("ea/Dockerfile.property-web")

    assert "COPY . /tmp/src" not in dockerfile
    assert "COPY ea/requirements.txt /app/requirements.txt" in dockerfile
    assert "COPY ea/requirements.lock /app/requirements.lock" in dockerfile
    assert "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" in dockerfile
    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "COPY scripts/render_onemin_property_i2v_segment.py /app/scripts/render_onemin_property_i2v_segment.py" in dockerfile
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
        "generate_property_reconstruction.py",
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
    assert "image: propertyquarry-web-runtime:latest" in compose
    assert "propertyquarry-render-tools:" in compose
    assert "dockerfile: ea/Dockerfile.property" in compose
    assert "image: propertyquarry-render-runtime:latest" in compose
    assert "profiles:" in compose
    assert "- render-tools" in compose
    assert 'container_name: "${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-propertyquarry-scheduler}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-db-live}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_RENDER_CONTAINER_NAME:-propertyquarry-render-tools}"' in compose
    assert "EA_SCHEDULER_HEARTBEAT_PATH: /data/artifacts/propertyquarry-scheduler-heartbeat.json" in compose
    assert 'EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS: "${EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS:-900}"' in compose
    assert 'test: ["CMD", "python", "-m", "app.scheduler_healthcheck"]' in compose
    scheduler_section = compose.split("  propertyquarry-scheduler:", 1)[1].split("  propertyquarry-db:", 1)[0]
    assert "disable: true" not in scheduler_section
    render_section = compose.split("  propertyquarry-render-tools:", 1)[1].split("  propertyquarry-db:", 1)[0]
    assert "command -v ffmpeg" in render_section
    assert "command -v blender" in render_section
    assert "command -v colmap" in render_section
    assert "command -v exiftool" in render_section
    assert "command -v convert" in render_section
    assert "python -c 'import numpy'" in render_section
    assert "http://127.0.0.1:8090/health/live" not in render_section
