from __future__ import annotations

import json
import subprocess

from scripts import property_runtime_reconstruction_smoke as smoke


def test_runtime_reconstruction_smoke_passes_when_container_generates_glb(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    calls: list[list[str]] = []

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        script = command[-1]
        if "generate_property_reconstruction.py" in script:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"generated"}\n', stderr="")
        payload = {
            "manifest_generated_reconstruction": {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "glb_export_status": "generated",
                "glb_model_relpath": "generated-reconstruction/model.glb",
            },
            "receipt_provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "glb_export_status": "generated",
            "paths": {
                "viewer": {"exists": True, "size_bytes": 10},
                "obj": {"exists": True, "size_bytes": 10},
                "mtl": {"exists": True, "size_bytes": 10},
                "glb": {"exists": True, "size_bytes": 128},
                "receipt": {"exists": True, "size_bytes": 10},
            },
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr(smoke, "_run", _fake_run)

    receipt = smoke.build_runtime_reconstruction_receipt(container="propertyquarry-api", slug="runtime-smoke")

    assert receipt["status"] == "pass"
    assert receipt["required_paths_ok"] is True
    assert receipt["glb_non_empty"] is True
    assert receipt["honest_disclosure_ok"] is True
    assert receipt["glb_manifest_ok"] is True
    assert len(calls) == 2


def test_runtime_reconstruction_smoke_fails_when_generated_asset_claims_verified(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        script = command[-1]
        if "generate_property_reconstruction.py" in script:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"generated"}\n', stderr="")
        payload = {
            "manifest_generated_reconstruction": {
                "verified_provider_capture": True,
                "satisfies_verified_tour_gate": True,
                "glb_export_status": "generated",
                "glb_model_relpath": "generated-reconstruction/model.glb",
            },
            "receipt_provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": True,
            "satisfies_verified_tour_gate": True,
            "glb_export_status": "generated",
            "paths": {
                "viewer": {"exists": True, "size_bytes": 10},
                "obj": {"exists": True, "size_bytes": 10},
                "mtl": {"exists": True, "size_bytes": 10},
                "glb": {"exists": True, "size_bytes": 128},
                "receipt": {"exists": True, "size_bytes": 10},
            },
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr(smoke, "_run", _fake_run)

    receipt = smoke.build_runtime_reconstruction_receipt(container="propertyquarry-api", slug="runtime-smoke")

    assert receipt["status"] == "failed"
    assert receipt["honest_disclosure_ok"] is False
