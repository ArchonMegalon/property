from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_omagic_model_upload_adapter_command_mode_consumes_model_input(tmp_path: Path, monkeypatch) -> None:
    model_path = tmp_path / "model.glb"
    model_path.write_bytes(b"glTF")
    out_path = tmp_path / "walkthrough.mp4"
    state_path = tmp_path / "state.json"
    fake_adapter = tmp_path / "fake_omagic_adapter.py"
    fake_adapter.write_text(
        """
from __future__ import annotations

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--request-json", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--state-json", required=True)
args = parser.parse_args()
request = json.loads(Path(args.request_json).read_text(encoding="utf-8"))
assert request["provider_key"] == "omagic"
assert request["model_path"].endswith("model.glb")
Path(args.out).write_bytes(b"fake-mp4")
state = {
    "render_status": "completed",
    "video_path": args.out,
    "model_input_consumed": True,
    "model_input_consumption_proof": "fake-command-adapter",
}
Path(args.state_json).write_text(json.dumps(state), encoding="utf-8")
print(json.dumps(state))
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_RENDER_COMMAND", f"{sys.executable} {fake_adapter}")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_omagic_property_model_walkthrough.py"),
            "--prompt",
            "Render a model-backed apartment walkthrough.",
            "--model-path",
            str(model_path),
            "--out",
            str(out_path),
            "--state-json",
            str(state_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert out_path.read_bytes() == b"fake-mp4"
    assert state["provider_key"] == "omagic"
    assert state["provider_backend_key"] == "omagic"
    assert state["model_input_consumed"] is True
    assert state["model_input_consumption_proof"] == "fake-command-adapter"
    assert state["adapter_mode"] == "command"
    assert "secret" not in json.dumps(state).lower()


def test_omagic_model_upload_adapter_fails_closed_without_target(tmp_path: Path, monkeypatch) -> None:
    model_path = tmp_path / "model.glb"
    model_path.write_bytes(b"glTF")
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED", "1")
    monkeypatch.delenv("PROPERTYQUARRY_OMAGIC_RENDER_COMMAND", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT", raising=False)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_omagic_property_model_walkthrough.py"),
            "--prompt",
            "Render a model-backed apartment walkthrough.",
            "--model-path",
            str(model_path),
            "--out",
            str(tmp_path / "walkthrough.mp4"),
            "--state-json",
            str(state_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["reason"] == "omagic_model_upload_endpoint_missing"
