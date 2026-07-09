from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import property_reconstruction_render_bridge as bridge


def test_build_generator_command_rejects_paths_outside_public_tour_dir(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    public_root.mkdir()
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setattr(bridge, "_script_path", lambda: script_path)

    with pytest.raises(ValueError, match="path_outside_public_tour_dir"):
        bridge._build_generator_command(
            {
                "slug": "unsafe",
                "floorplan_path": str(tmp_path / "outside.jpg"),
                "photo_paths": [],
            }
        )


def test_run_generation_request_invokes_generator_with_shared_paths(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    bundle_root = public_root / "safe-slug" / ".reconstruction-source"
    bundle_root.mkdir(parents=True)
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    floorplan = bundle_root / "floorplan.jpg"
    photo = bundle_root / "photo-01.jpg"
    floorplan.write_bytes(b"floorplan")
    photo.write_bytes(b"photo")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setattr(bridge, "_script_path", lambda: script_path)

    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        captured["env_public_tour_dir"] = dict(kwargs.get("env") or {}).get("EA_PUBLIC_TOUR_DIR")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"status": "generated"}) + "\n", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.run_generation_request(
        {
            "slug": "safe-slug",
            "floorplan_path": str(floorplan),
            "photo_paths": [str(photo)],
            "style_label": "Ikea",
            "room_count": 3,
            "route_labels": ["entry/hall", "living area", "bedroom"],
            "skip_video": False,
        }
    )

    assert result["status"] == "generated"
    command = list(captured["command"])
    assert command[:3] == [bridge.sys.executable, str(script_path), "--slug"]
    assert "--floorplan" in command
    assert "--photo" in command
    assert "--style-label" in command
    assert "--room-count" in command
    assert command.count("--room-label") == 3
    assert captured["cwd"] == "/app"
    assert captured["env_public_tour_dir"] == str(public_root.resolve())


def test_run_generation_request_forwards_walkthrough_seconds_per_stop_env(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    bundle_root = public_root / "safe-slug" / ".reconstruction-source"
    bundle_root.mkdir(parents=True)
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    floorplan = bundle_root / "floorplan.jpg"
    floorplan.write_bytes(b"floorplan")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setattr(bridge, "_script_path", lambda: script_path)

    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:  # type: ignore[no-untyped-def]
        captured["env"] = dict(kwargs.get("env") or {})
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"status": "generated"}) + "\n", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.run_generation_request(
        {
            "slug": "safe-slug",
            "floorplan_path": str(floorplan),
            "photo_paths": [],
            "walkthrough_seconds_per_stop": 8.0,
        }
    )

    assert result["status"] == "generated"
    assert captured["env"]["PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP"] == "8.0"


def test_run_generation_request_reports_generator_timeout(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    bundle_root = public_root / "safe-slug" / ".reconstruction-source"
    bundle_root.mkdir(parents=True)
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    floorplan = bundle_root / "floorplan.jpg"
    floorplan.write_bytes(b"floorplan")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_TIMEOUT_SECONDS", "480")
    monkeypatch.setattr(bridge, "_script_path", lambda: script_path)

    captured: dict[str, object] = {}

    def _fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:  # type: ignore[no-untyped-def]
        captured["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(command, timeout=kwargs.get("timeout") or 0)

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.run_generation_request(
        {
            "slug": "safe-slug",
            "floorplan_path": str(floorplan),
            "photo_paths": [],
        }
    )

    assert captured["timeout"] == 480
    assert result["status"] == "failed"
    assert result["reason"] == "generator_timeout"
    assert result["timeout_seconds"] == 480


def test_run_generation_request_rejects_generator_reported_failure(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    bundle_root = public_root / "safe-slug" / ".reconstruction-source"
    bundle_root.mkdir(parents=True)
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    floorplan = bundle_root / "floorplan.jpg"
    floorplan.write_bytes(b"floorplan")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setattr(bridge, "_script_path", lambda: script_path)

    def _fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "failed", "reason": "runtime_publish_failed"}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    result = bridge.run_generation_request(
        {
            "slug": "safe-slug",
            "floorplan_path": str(floorplan),
            "photo_paths": [],
        }
    )

    assert result["status"] == "failed"
    assert result["reason"] == "generator_reported_failure"
    assert result["detail"] == "runtime_publish_failed"
    assert result["result"]["reason"] == "runtime_publish_failed"
