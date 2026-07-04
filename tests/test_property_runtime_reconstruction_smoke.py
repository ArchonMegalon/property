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


def test_runtime_reconstruction_smoke_passes_without_glb_when_glb_is_not_required(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        script = command[-1]
        if "generate_property_reconstruction.py" in script:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"generated"}\n', stderr="")
        payload = {
            "manifest_generated_reconstruction": {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "glb_export_status": "skipped",
            },
            "receipt_provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "glb_export_status": "skipped",
            "paths": {
                "viewer": {"exists": True, "size_bytes": 10},
                "obj": {"exists": True, "size_bytes": 10},
                "mtl": {"exists": True, "size_bytes": 10},
                "glb": {"exists": False, "size_bytes": 0},
                "receipt": {"exists": True, "size_bytes": 10},
            },
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr(smoke, "_run", _fake_run)

    receipt = smoke.build_runtime_reconstruction_receipt(container="propertyquarry-api", slug="runtime-smoke")

    assert receipt["status"] == "pass"
    assert receipt["required_paths_ok"] is True
    assert receipt["glb_non_empty"] is False
    assert receipt["glb_manifest_ok"] is False
    assert receipt["glb_required"] is False
    assert receipt["glb_capability_ok"] is True


def test_runtime_reconstruction_smoke_fails_without_glb_when_glb_is_required(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        script = command[-1]
        if "generate_property_reconstruction.py" in script:
            return subprocess.CompletedProcess(command, 0, stdout='{"status":"generated"}\n', stderr="")
        payload = {
            "manifest_generated_reconstruction": {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "glb_export_status": "skipped",
            },
            "receipt_provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "glb_export_status": "skipped",
            "paths": {
                "viewer": {"exists": True, "size_bytes": 10},
                "obj": {"exists": True, "size_bytes": 10},
                "mtl": {"exists": True, "size_bytes": 10},
                "glb": {"exists": False, "size_bytes": 0},
                "receipt": {"exists": True, "size_bytes": 10},
            },
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    monkeypatch.setattr(smoke, "_run", _fake_run)

    receipt = smoke.build_runtime_reconstruction_receipt(
        container="propertyquarry-api",
        slug="runtime-smoke",
        require_glb=True,
    )

    assert receipt["status"] == "failed"
    assert receipt["required_paths_ok"] is False
    assert receipt["glb_required"] is True
    assert receipt["glb_capability_ok"] is False


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


def test_runtime_reconstruction_smoke_fails_when_required_public_contract_base_url_missing(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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

    receipt = smoke.build_runtime_reconstruction_receipt(
        container="propertyquarry-api",
        slug="runtime-smoke",
        require_browser=True,
    )

    assert receipt["status"] == "failed"
    assert receipt["public_route_contract_ok"] is False
    assert receipt["public_route_contract"]["reason"] == "public_base_url_missing"


def test_runtime_reconstruction_smoke_requires_public_route_rejection_when_public_base_url_is_set(monkeypatch) -> None:
    monkeypatch.setattr(smoke.shutil, "which", lambda command: "/usr/bin/docker" if command == "docker" else None)

    def _fake_run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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

    observed: dict[str, str] = {}

    def _fake_public_contract(*, public_base_url: str, slug: str) -> dict[str, object]:
        observed["public_base_url"] = public_base_url
        observed["slug"] = slug
        return {"status": "failed", "failures": ["viewer_not_redirected"]}

    monkeypatch.setattr(smoke, "_run", _fake_run)
    monkeypatch.setattr(smoke, "_check_generated_reconstruction_public_contract", _fake_public_contract)

    receipt = smoke.build_runtime_reconstruction_receipt(
        container="propertyquarry-api",
        slug="runtime-smoke",
        public_base_url="https://propertyquarry.com",
    )

    assert observed == {"public_base_url": "https://propertyquarry.com", "slug": "runtime-smoke"}
    assert receipt["status"] == "failed"
    assert receipt["public_route_contract_ok"] is False
    assert receipt["public_route_contract"]["failures"] == ["viewer_not_redirected"]


def test_generated_reconstruction_public_contract_requires_redirect_unavailable_and_gone(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_probe(url: str) -> dict[str, object]:
        calls.append(url)
        if url.endswith("/generated-reconstruction/viewer.html"):
            return {"status_code": 302, "location": "/tours/runtime-smoke", "body_excerpt": ""}
        if url.endswith("/generated-reconstruction/model.obj"):
            return {"status_code": 410, "location": "", "body_excerpt": "This generated model is not a public 3D tour."}
        return {
            "status_code": 404,
            "location": "",
            "body_excerpt": "This link pointed to an older generated layout preview, not a real 3D tour.",
        }

    monkeypatch.setattr(smoke, "_http_probe", _fake_probe)

    receipt = smoke._check_generated_reconstruction_public_contract(
        public_base_url="https://propertyquarry.com",
        slug="runtime-smoke",
    )

    assert receipt["status"] == "pass"
    assert len(calls) == 3
