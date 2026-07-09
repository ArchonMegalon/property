from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import ensure_propertyquarry_render_bridge_runtime as runtime


def test_render_bridge_runtime_receipt_passes_when_container_is_already_healthy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.property.yml"
    compose.write_text("services:\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_docker_available", lambda: True)
    monkeypatch.setattr(
        runtime,
        "_container_state",
        lambda container: {"exists": True, "status": "running", "health": "healthy", "detail": ""},
    )
    monkeypatch.setattr(
        runtime,
        "_container_health_probe",
        lambda container, *, health_url: {"status": "pass", "url": health_url},
    )
    monkeypatch.setattr(runtime, "_runtime_code_parity", lambda container: {"status": "pass", "checks": []})

    receipt = runtime.build_render_bridge_runtime_receipt(
        container="propertyquarry-render-tools",
        service="propertyquarry-render-tools",
        compose_file=str(compose),
    )

    assert receipt["status"] == "pass"
    assert receipt["action"] == "already_ready"
    assert receipt["health_probe"]["status"] == "pass"


def test_render_bridge_runtime_receipt_recreates_runtime_when_container_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.property.yml"
    compose.write_text("services:\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_docker_available", lambda: True)
    monkeypatch.setattr(runtime, "_compose_command", lambda **_: ["docker", "compose", "-f", str(compose)])

    states = iter(
        [
            {"exists": False, "status": "", "health": "", "detail": ""},
            {"exists": False, "status": "", "health": "", "detail": ""},
            {"exists": True, "status": "running", "health": "healthy", "detail": ""},
        ]
    )
    monkeypatch.setattr(runtime, "_container_state", lambda container: next(states))
    monkeypatch.setattr(
        runtime,
        "_container_health_probe",
        lambda container, *, health_url: {"status": "pass", "url": health_url},
    )
    monkeypatch.setattr(runtime, "_runtime_code_parity", lambda container: {"status": "pass", "checks": []})

    observed: dict[str, object] = {}

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        observed["command"] = list(command)
        observed["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime, "_run", _fake_run)

    receipt = runtime.build_render_bridge_runtime_receipt(
        container="propertyquarry-render-tools",
        service="propertyquarry-render-tools",
        compose_file=str(compose),
    )

    assert receipt["status"] == "pass"
    assert receipt["action"] == "recreated_runtime"
    assert observed["command"][-6:] == ["up", "-d", "--build", "--no-deps", "--force-recreate", "propertyquarry-render-tools"]
    assert receipt["compose_up"]["build_requested"] is True


def test_render_bridge_runtime_receipt_rebuilds_when_running_container_code_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.property.yml"
    compose.write_text("services:\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_docker_available", lambda: True)
    monkeypatch.setattr(runtime, "_compose_command", lambda **_: ["docker", "compose", "-f", str(compose)])

    states = iter(
        [
            {"exists": True, "status": "running", "health": "healthy", "detail": ""},
            {"exists": True, "status": "running", "health": "healthy", "detail": ""},
            {"exists": True, "status": "running", "health": "healthy", "detail": ""},
        ]
    )
    monkeypatch.setattr(runtime, "_container_state", lambda container: next(states))
    monkeypatch.setattr(
        runtime,
        "_container_health_probe",
        lambda container, *, health_url: {"status": "pass", "url": health_url},
    )

    parity_rows = iter(
        [
            {"status": "failed", "mismatched_paths": ["/app/scripts/generate_property_reconstruction.py"]},
            {"status": "pass", "checks": []},
        ]
    )
    monkeypatch.setattr(runtime, "_runtime_code_parity", lambda container: next(parity_rows))

    observed: dict[str, object] = {}

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        observed["command"] = list(command)
        observed["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime, "_run", _fake_run)

    receipt = runtime.build_render_bridge_runtime_receipt(
        container="propertyquarry-render-tools",
        service="propertyquarry-render-tools",
        compose_file=str(compose),
    )

    assert receipt["status"] == "pass"
    assert receipt["action"] == "recreated_runtime"
    assert receipt["initial_code_parity"]["status"] == "failed"
    assert receipt["post_code_parity"]["status"] == "pass"
    assert observed["command"][-6:] == ["up", "-d", "--build", "--no-deps", "--force-recreate", "propertyquarry-render-tools"]
    assert receipt["compose_up"]["build_requested"] is True


def test_render_bridge_runtime_receipt_blocks_when_compose_file_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_docker_available", lambda: True)

    receipt = runtime.build_render_bridge_runtime_receipt(compose_file="/tmp/propertyquarry-missing-compose.yml")

    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "compose_file_missing"


def test_property_runtime_images_copy_three_vendor_assets() -> None:
    dockerfile = Path("ea/Dockerfile.property").read_text(encoding="utf-8")
    dockerfile_web = Path("ea/Dockerfile.property-web").read_text(encoding="utf-8")

    assert "COPY vendor/three /app/vendor/three" in dockerfile
    assert "COPY vendor/three /app/vendor/three" in dockerfile_web
