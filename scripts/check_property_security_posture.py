#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _normalized_requirement_name(line: str) -> str:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return ""
    name = re.split(r"[<>=!~\[]", raw, maxsplit=1)[0].strip().lower()
    return name


def _lock_package_names(lock_text: str) -> set[str]:
    names: set[str] = set()
    for line in lock_text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "==" not in raw:
            continue
        names.add(raw.split("==", 1)[0].strip().lower().replace("_", "-"))
    return names


def build_security_posture_receipt() -> dict[str, object]:
    failures: list[str] = []
    env_example = _read(".env.example")
    if "property@propertyquery.com" in env_example:
        failures.append(".env.example still references property@propertyquery.com")
    if re.search(r"^EA_REGISTRATION_EMAIL_FROM_FALLBACK=.+", env_example, flags=re.MULTILINE):
        failures.append(".env.example should not advertise a non-PropertyQuarry fallback sender")
    for env_name in ("EA_API_TOKEN", "EA_SIGNING_SECRET", "EA_CF_ACCESS_TEAM_DOMAIN", "EA_CF_ACCESS_AUD"):
        if not re.search(rf"^{re.escape(env_name)}=", env_example, flags=re.MULTILINE):
            failures.append(f".env.example must list prod auth/signing placeholder {env_name}")
    expected_service_aliases = {
        "PROPERTYQUARRY_API_SERVICE": "propertyquarry-api",
        "PROPERTYQUARRY_SCHEDULER_SERVICE": "propertyquarry-scheduler",
        "PROPERTYQUARRY_DB_SERVICE": "propertyquarry-db",
        "PROPERTYQUARRY_API_CONTAINER_NAME": "propertyquarry-api",
        "PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME": "propertyquarry-scheduler",
        "PROPERTYQUARRY_DB_CONTAINER_NAME": "propertyquarry-db-live",
        "PROPERTYQUARRY_RENDER_CONTAINER_NAME": "propertyquarry-render-tools",
    }
    for env_name, expected_value in expected_service_aliases.items():
        if not re.search(rf"^{re.escape(env_name)}={re.escape(expected_value)}$", env_example, flags=re.MULTILINE):
            failures.append(f".env.example must default {env_name}={expected_value}")

    compose = _read("docker-compose.property.yml")
    forbidden_compose_tokens = (
        "ea-openvoice",
        "openvoice",
        "ea-responses-proxy",
        "ea-teable-relay",
        "memorial",
        "/var/run/docker.sock",
        "/mnt/onedrive",
        "/mnt/pcloud",
    )
    for token in forbidden_compose_tokens:
        if token in compose.lower():
            failures.append(f"docker-compose.property.yml contains inherited surface: {token}")
    for service_name in ("propertyquarry-api", "propertyquarry-scheduler", "propertyquarry-db"):
        if service_name not in compose:
            failures.append(f"docker-compose.property.yml missing {service_name}")
    expected_container_name_envs = (
        'container_name: "${PROPERTYQUARRY_API_CONTAINER_NAME:-propertyquarry-api}"',
        'container_name: "${PROPERTYQUARRY_SCHEDULER_CONTAINER_NAME:-propertyquarry-scheduler}"',
        'container_name: "${PROPERTYQUARRY_DB_CONTAINER_NAME:-propertyquarry-db-live}"',
        'container_name: "${PROPERTYQUARRY_RENDER_CONTAINER_NAME:-propertyquarry-render-tools}"',
    )
    for expected in expected_container_name_envs:
        if expected not in compose:
            failures.append(f"docker-compose.property.yml must keep recoverable container alias {expected}")
    if "propertyquarry-worker" in compose or "PROPERTYQUARRY_WORKER_PROFILE" in compose:
        failures.append("docker-compose.property.yml must not start the inherited idle worker by default")
    if "POSTGRES_HOST_AUTH_METHOD" in compose or ":-trust" in compose:
        failures.append("docker-compose.property.yml must not default Postgres to trust auth")
    if 'POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?' not in compose:
        failures.append("docker-compose.property.yml must require POSTGRES_PASSWORD")
    if 'EA_RUNTIME_MODE: "${EA_RUNTIME_MODE:-prod}"' not in compose:
        failures.append("docker-compose.property.yml must default EA_RUNTIME_MODE to prod")
    if 'PROPERTYQUARRY_SCHEDULER_PROFILE: "${PROPERTYQUARRY_SCHEDULER_PROFILE:-property_only}"' not in compose:
        failures.append("docker-compose.property.yml must default the scheduler to property_only")
    if "dockerfile: ea/Dockerfile.property-web" not in compose:
        failures.append("docker-compose.property.yml must run API/scheduler from the lightweight web runtime")
    if 'image: "${PROPERTYQUARRY_WEB_IMAGE:-propertyquarry-web-runtime:latest}"' not in compose:
        failures.append("docker-compose.property.yml must name the lightweight web runtime image")
    if "propertyquarry-render-tools:" not in compose or "render-tools" not in compose:
        failures.append("docker-compose.property.yml must expose an explicit render-tools profile")
    if 'image: "${PROPERTYQUARRY_RENDER_IMAGE:-propertyquarry-render-runtime:latest}"' not in compose:
        failures.append("docker-compose.property.yml must name the render tooling image separately")
    if re.search(r"^\s+user:\s*[\"']?0(?::0)?[\"']?\s*$", compose, flags=re.MULTILINE):
        failures.append("docker-compose.property.yml must not run property web services as root")
    if "SYS_NICE" in compose:
        failures.append("docker-compose.property.yml must not grant SYS_NICE to property web services")

    dockerfile = _read("ea/Dockerfile.property")
    if not re.search(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\s*$", dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property must pin its base image by digest")
    if " docker.io" in dockerfile or "docker-compose" in dockerfile or "docker-29." in dockerfile:
        failures.append("ea/Dockerfile.property must not install Docker tooling")
    if not re.search(r"^USER\s+ea\s*$", dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property must run as USER ea")
    if "requirements.lock" not in dockerfile or "-c requirements.lock" not in dockerfile:
        failures.append("ea/Dockerfile.property must install with requirements.lock constraints")
    if "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" not in dockerfile:
        failures.append("ea/Dockerfile.property must explicitly copy the Willhaben packet helper")
    if "for script in /tmp/src/scripts/*" in dockerfile or 'cp "$script" /app/scripts/' in dockerfile:
        failures.append("ea/Dockerfile.property must not bulk-copy scripts into the runtime image")
    web_dockerfile = _read("ea/Dockerfile.property-web")
    if not re.search(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\s*$", web_dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property-web must pin its base image by digest")
    if " docker.io" in web_dockerfile or "docker-compose" in web_dockerfile or "docker-29." in web_dockerfile:
        failures.append("ea/Dockerfile.property-web must not install Docker tooling")
    if not re.search(r"^USER\s+ea\s*$", web_dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property-web must run as USER ea")
    if "requirements.lock" not in web_dockerfile or "-c requirements.lock" not in web_dockerfile:
        failures.append("ea/Dockerfile.property-web must install with requirements.lock constraints")
    if "COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py" not in web_dockerfile:
        failures.append("ea/Dockerfile.property-web must explicitly copy the Willhaben packet helper")
    if "for script in /tmp/src/scripts/*" in web_dockerfile or 'cp "$script" /app/scripts/' in web_dockerfile:
        failures.append("ea/Dockerfile.property-web must not bulk-copy scripts into the runtime image")
    for forbidden_native_tool in (
        "blender",
        "colmap",
        "espeak",
        "ffmpeg",
        "imagemagick",
        "libimage-exiftool-perl",
        "meshlab",
        "meshlabserver",
    ):
        if forbidden_native_tool in web_dockerfile.lower():
            failures.append(f"ea/Dockerfile.property-web must not install native media/render tool {forbidden_native_tool}")
    for forbidden_browser_payload in ("PLAYWRIGHT_BROWSERS_PATH=/ms-playwright", "python -m playwright install --with-deps chromium"):
        if forbidden_browser_payload in web_dockerfile:
            failures.append("ea/Dockerfile.property-web must not install browser payloads in the request-serving image")
    if not re.search(r"image:\s+\S+@sha256:[0-9a-f]{64}", compose):
        failures.append("docker-compose.property.yml must pin sidecar images by digest")

    public_tours = _read("ea/app/api/routes/public_tours.py")
    if "tour-action-tokens" in public_tours or "tourActionTokens" in public_tours:
        failures.append("public tours must not emit bearer-style action tokens into HTML")
    if "record_property_feedback(" in public_tours:
        failures.append("public tour feedback must not directly mutate owner learning profiles")
    if "request_property_tour_detail_refresh(" in public_tours:
        failures.append("public tour request-details must not queue owner work from public links")
    if 'request.headers.get("x-forwarded-for")' in public_tours and "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR" not in public_tours:
        failures.append("public tour feedback must not trust x-forwarded-for without explicit opt-in")
    if 'except Exception:\n        pass' in public_tours:
        failures.append("public tour feedback must not silently swallow persistence failures")
    if '"status": "not_captured"' not in public_tours:
        failures.append("public tour feedback must report persistence failures honestly")
    public_tour_payload_match = re.search(
        r"def public_tour_payload\(slug: str\).*?(?=\n\n@router\.)",
        public_tours,
        flags=re.DOTALL,
    )
    public_tour_payload_body = public_tour_payload_match.group(0) if public_tour_payload_match else ""
    if (
        "_redacted_public_tour_payload(" not in public_tour_payload_body
        or "expose_asset_relpaths=False" not in public_tour_payload_body
        or "include_external_tour_urls=False" not in public_tour_payload_body
    ):
        failures.append("public tour JSON must use the redacted public payload builder")
    if "_PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS" not in public_tours or "_public_tour_manifest(payload)" not in public_tours or "safe_relpath not in manifest" not in public_tours:
        failures.append("public tour file serving must use a manifest-backed asset allowlist with denied sidecar extensions")
    forbidden_public_render_fetchers = (
        "_fetch_listing_research",
        "_reverse_geocode",
        "_fetch_nearby_poi_research",
        "nominatim.openstreetmap.org",
        "overpass-api.de",
    )
    for token in forbidden_public_render_fetchers:
        if token in public_tours:
            failures.append("public tour render routes must use stored research snapshots, not live listing/geospatial fetches")
            break
    if "PROPERTYQUARRY_PUBLIC_MEDIA_ALLOWED_HOSTS" not in public_tours or "_public_tour_static_media_url_allowed" not in public_tours:
        failures.append("public tour scene media must use a static external-media host allowlist")
    if "_PUBLIC_TOUR_EXACT_LOCATION_FACT_KEYS" not in public_tours or "_redacted_public_tour_facts" not in public_tours:
        failures.append("public tour facts must use mode-aware exact-location redaction")
    if "_public_tour_external_media_url_allowed" not in public_tours:
        failures.append("public tour scene media must pass through the external-media URL guard")
    if "_PUBLIC_TOUR_PUBLIC_PDF_PRIVACY_CLASSES" not in public_tours or "floorplan_pdf_public" not in public_tours:
        failures.append("public tour PDFs must require an explicit public floorplan privacy class")
    if "PROPERTYQUARRY_PUBLIC_RATE_LIMIT_FAIL_CLOSED" not in public_tours or "_public_tour_prod_mode_enabled()" not in public_tours:
        failures.append("public tour durable rate-limit failures must fail closed in prod")
    if "_public_tour_security_headers" not in public_tours or "Content-Security-Policy" not in public_tours:
        failures.append("public tours must set public page/file security headers")

    requirements = _read("ea/requirements.txt")
    lock_text = _read("ea/requirements.lock")
    lock_names = _lock_package_names(lock_text)
    for line in requirements.splitlines():
        name = _normalized_requirement_name(line)
        if not name:
            continue
        if name.replace("_", "-") not in lock_names:
            failures.append(f"ea/requirements.lock missing direct requirement {name}")
    for line in lock_text.splitlines():
        raw = line.strip()
        if raw and not raw.startswith("#") and "==" not in raw:
            failures.append(f"ea/requirements.lock contains an unpinned row: {raw}")

    required_checks = [
        "property_env_placeholders",
        "property_service_aliases",
        "property_compose_isolation",
        "non_root_pinned_runtime_image",
        "lightweight_web_runtime_split",
        "web_runtime_browser_payload_isolation",
        "render_tooling_profile",
        "web_runtime_non_root_compose",
        "web_runtime_no_sys_nice",
        "no_docker_tooling_in_property_runtime",
        "sidecar_images_pinned_by_digest",
        "public_tour_secret_and_mutation_guards",
        "public_tour_redacted_payloads",
        "public_tour_manifest_asset_allowlist",
        "public_tour_no_live_research_fetches",
        "public_tour_media_host_allowlist",
        "public_tour_exact_location_redaction",
        "public_tour_pdf_privacy_class",
        "public_tour_rate_limit_fail_closed",
        "public_tour_security_headers",
        "locked_direct_requirements",
    ]
    return {
        "schema": "propertyquarry.security_posture_receipt.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "pass" if not failures else "fail",
        "required_checks": required_checks,
        "failure_count": len(failures),
        "failures": failures,
        "note": "Static production-security posture gate for the isolated PropertyQuarry deployment plane.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check PropertyQuarry production security posture.")
    parser.add_argument("--write", default="", help="Optional path for a JSON receipt.")
    args = parser.parse_args()

    receipt = build_security_posture_receipt()
    failures = list(receipt.get("failures") or [])
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failures:
        print("property security posture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property security posture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
