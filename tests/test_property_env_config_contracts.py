from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_lists_flagship_property_provider_switches() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "PROPERTYQUARRY_DEFAULT_BRAND" not in env

    for required in (
        "PROPERTYQUARRY_NEURONWRITER_ENABLED=0",
        "PROPERTYQUARRY_NEURONWRITER_REQUIRED=0",
        "PROPERTYQUARRY_NEURONWRITER_DOSSIER_MODE=public_only",
        "NEURONWRITER_API_KEY=",
        "PROPERTYQUARRY_DADAN_ENABLED=0",
        "PROPERTYQUARRY_DADAN_WEBHOOK_ALLOW_BASIC_AUTH=0",
        "DADAN_API_KEY=",
        "DADAN_WEBHOOK_SECRET=",
        "MATTERPORT_API_KEY=",
        "PROPERTYQUARRY_MATTERPORT_LIVE_SMOKE=0",
        "THREEDVISTA_LOGIN_EMAIL=",
        "THREEDVISTA_LICENSE_EMAIL=",
        "PROPERTYQUARRY_3DVISTA_EXPORT_ROOT=",
        "PROPERTYQUARRY_3DVISTA_LIVE_SMOKE=0",
        "MAGICFIT_EMAIL=",
        "MAGICFIT_PASSWORD=",
        "PROPERTYQUARRY_MAGICFIT_EMAIL=",
        "PROPERTYQUARRY_MAGICFIT_PASSWORD=",
        "PROPERTYQUARRY_MAGICFIT_LIVE_SMOKE=0",
        "ONEMIN_AI_API_KEY=",
        "PROPERTYQUARRY_ONEMIN_LIVE_SMOKE=0",
        "JOGG_API_KEY=",
        "PROPERTYQUARRY_JOGG_LIVE_SMOKE=0",
        "PIXEFY_API_KEY=",
        "PROPERTYQUARRY_PIXEFY_LIVE_SMOKE=0",
        "RAFTER_API_KEY=",
        "PROPERTYQUARRY_RAFTER_LIVE_SMOKE=0",
        "PROPERTYQUARRY_3DVISTA_EXPORT_ROOT=/docker/property/state/public_property_tours/3dvista",
        "PROPERTYQUARRY_FASTESTVPN_ON_DEMAND_ENABLED=0",
        "PROPERTYQUARRY_FASTESTVPN_AUTO_STOP_AFTER_REFRESH=1",
    ):
        assert required in env


def test_env_example_keeps_property_source_cache_inside_property_repo() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "EA_PROPERTY_SOURCE_LISTING_CACHE_PATH=/docker/property/state/property_source_listing_cache.json" in env
    assert "/docker/fleet/state/property_source_listing_cache.json" not in env
    assert "EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS=7776000" in env
    assert "search-run history is kept until the user deletes it" not in env


def test_property_public_tour_scripts_default_to_property_state() -> None:
    backfill = (ROOT / "scripts/backfill_public_tour_research_snapshots.py").read_text(encoding="utf-8")
    comparison = (ROOT / "scripts/build_comparison_dossiers.py").read_text(encoding="utf-8")
    crezlo_publish = (ROOT / "scripts/publish_crezlo_property_tours.py").read_text(encoding="utf-8")
    crezlo_public = (ROOT / "scripts/publish_crezlo_public_tours.py").read_text(encoding="utf-8")
    crezlo_worker = (ROOT / "scripts/crezlo_property_tour_worker.py").read_text(encoding="utf-8")

    for body in (backfill, comparison, crezlo_publish, crezlo_public):
        assert "/docker/property/state/public_property_tours" in body
        assert "/docker/fleet/state/public_property_tours" not in body
    for body in (crezlo_publish, crezlo_public, crezlo_worker):
        assert "PropertyQuarry-Crezlo" in body
        assert "EA-Crezlo" not in body
    assert "PROPERTYQUARRY_CREZLO_PLAYWRIGHT_IMAGE" in crezlo_worker
    assert "PROPERTYQUARRY_CREZLO_WORKSPACE_DOMAIN" in crezlo_worker
    assert "propertyquarry-tours.crezlotours.com" in crezlo_worker
    assert "ea-property-tours" not in crezlo_worker
    assert "PropertyQuarry-hosted" in crezlo_publish
    assert "EA-hosted" not in crezlo_publish


def test_property_release_gate_runs_repair_fleet_canary() -> None:
    gate = (ROOT / "scripts/property_release_gates.sh").read_text(encoding="utf-8")

    assert "scripts/propertyquarry_repair_fleet_canary.py" in gate


def test_env_example_keeps_external_investment_feeds_fail_closed_and_durable() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS=" in env
    assert "EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH=/docker/property/state/property_investment_external_cache.json" in env
    assert "EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOW_INSECURE_HTTP=1" not in env
    assert "/tmp/propertyquarry/state/property_investment_external_cache.json" not in env


def test_local_env_example_keeps_browseract_state_inside_property_repo() -> None:
    env = (ROOT / ".env.local.example").read_text(encoding="utf-8")

    assert "BROWSERACT_CHATPLAYGROUND_AUDIT_WORKFLOW_QUERY=propertyquarry_chatplayground_audit_live" in env
    assert (
        "BROWSERACT_CHATPLAYGROUND_AUDIT_RESULT_PATH="
        "/docker/property/state/browseract_bootstrap/runtime/propertyquarry_chatplayground_audit_live/result.json"
    ) in env
    assert "ea_chatplayground_audit_live" not in env
    assert "/docker/fleet" not in env


def test_release_hygiene_forbids_tracked_live_env_files() -> None:
    script = (ROOT / "scripts/check_property_release_hygiene.py").read_text(encoding="utf-8")

    assert 'tracked live env file forbidden' in script
    assert '".env"' in script
    assert '".env.local"' in script


def test_prod_compose_keeps_fastestvpn_repo_local_and_default_off() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "/docker/property" in compose
    assert "EA_FASTESTVPN_ON_DEMAND_ENABLED: ${PROPERTYQUARRY_FASTESTVPN_ON_DEMAND_ENABLED:-0}" in compose
    assert "${EA_FASTESTVPN_ON_DEMAND_ENABLED" not in compose
