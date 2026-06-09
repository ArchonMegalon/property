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
        "docker compose",
        "DC+=(-f",
        "docker-compose.property.yml",
        "propertyquarry-api",
        "propertyquarry-scheduler",
        "propertyquarry-db",
        "/health",
        "/health/ready",
        "/version",
        "/app/properties",
        "PropertyQuarry",
        "storage_backend",
        "postgres",
        "--preflight-only",
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


def test_property_dockerfile_allowlists_runtime_scripts() -> None:
    dockerfile = _read("ea/Dockerfile.property")

    assert "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" in dockerfile
    assert "COPY scripts/render_magicfit_property_flythrough.py /app/scripts/render_magicfit_property_flythrough.py" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "for script in /tmp/src/scripts/*" not in dockerfile
    assert 'for script in "$APP_SRC"/scripts/*' not in dockerfile
    assert 'cp "$script" /app/scripts/' not in dockerfile
    assert "build_propertyquarry_magicfit_promo.py" not in dockerfile


def test_property_compose_container_names_are_recoverable() -> None:
    compose = _read("docker-compose.property.yml")

    assert 'container_name: "${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-propertyquarry-scheduler}"' in compose
    assert 'container_name: "${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-db}"' in compose
