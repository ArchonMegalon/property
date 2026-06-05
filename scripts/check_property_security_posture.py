#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
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


def main() -> int:
    failures: list[str] = []
    env_example = _read(".env.example")
    if "property@propertyquery.com" in env_example:
        failures.append(".env.example still references property@propertyquery.com")
    if re.search(r"^EA_REGISTRATION_EMAIL_FROM_FALLBACK=.+", env_example, flags=re.MULTILINE):
        failures.append(".env.example should not advertise a non-PropertyQuarry fallback sender")

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
    for service_name in ("propertyquarry-api", "propertyquarry-worker", "propertyquarry-scheduler", "propertyquarry-db"):
        if service_name not in compose:
            failures.append(f"docker-compose.property.yml missing {service_name}")

    dockerfile = _read("ea/Dockerfile.property")
    if " docker.io" in dockerfile or "docker-compose" in dockerfile or "docker-29." in dockerfile:
        failures.append("ea/Dockerfile.property must not install Docker tooling")
    if not re.search(r"^USER\s+ea\s*$", dockerfile, flags=re.MULTILINE):
        failures.append("ea/Dockerfile.property must run as USER ea")
    if "requirements.lock" not in dockerfile or "-c requirements.lock" not in dockerfile:
        failures.append("ea/Dockerfile.property must install with requirements.lock constraints")

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

    if failures:
        print("property security posture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property security posture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
