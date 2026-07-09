#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_HOST = os.getenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_PORT") or "8091")


def _public_tour_dir() -> Path:
    return Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours")).expanduser().resolve()


def _script_path() -> Path:
    return Path("/app/scripts/generate_property_reconstruction.py").resolve()


def _bridge_token() -> str:
    return str(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN") or "").strip()


def _generation_timeout_seconds(raw_value: object = "") -> int:
    requested_value = str(raw_value or "").strip()
    raw_value = str(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_TIMEOUT_SECONDS") or "").strip()
    try:
        parsed = int(float(requested_value or raw_value or "420"))
    except Exception:
        parsed = 420
    return min(max(parsed, 120), 1800)


def _safe_shared_file(raw_path: object, *, root: Path) -> Path:
    candidate = Path(str(raw_path or "")).expanduser().resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("path_outside_public_tour_dir")
    if not candidate.is_file():
        raise ValueError("shared_input_missing")
    return candidate


def _build_generator_command(payload: dict[str, object]) -> list[str]:
    slug = str(payload.get("slug") or "").strip()
    if not slug:
        raise ValueError("slug_missing")
    script_path = _script_path()
    if not script_path.is_file():
        raise ValueError("generator_script_missing")
    root = _public_tour_dir()
    command = [sys.executable, str(script_path), "--slug", slug]
    if bool(payload.get("skip_video")):
        command.append("--skip-video")
    floorplan_path = str(payload.get("floorplan_path") or "").strip()
    if floorplan_path:
        command.extend(["--floorplan", str(_safe_shared_file(floorplan_path, root=root))])
    else:
        command.append("--infer-floorplan-from-photos")
    photo_paths = payload.get("photo_paths")
    if not isinstance(photo_paths, list):
        photo_paths = []
    for photo_path in photo_paths:
        command.extend(["--photo", str(_safe_shared_file(photo_path, root=root))])
    style_label = str(payload.get("style_label") or "").strip()
    if style_label:
        command.extend(["--style-label", style_label])
    room_count = max(0, int(payload.get("room_count") or 0))
    if room_count > 0:
        command.extend(["--room-count", str(room_count)])
    route_labels = payload.get("route_labels")
    if isinstance(route_labels, list):
        for route_label in route_labels:
            normalized_label = str(route_label or "").strip()
            if normalized_label:
                command.extend(["--room-label", normalized_label])
    return command


def run_generation_request(payload: dict[str, object]) -> dict[str, object]:
    command = _build_generator_command(payload)
    timeout_seconds = _generation_timeout_seconds(payload.get("timeout_seconds"))
    env = {**os.environ, "EA_PUBLIC_TOUR_DIR": str(_public_tour_dir())}
    try:
        walkthrough_seconds_per_stop = float(payload.get("walkthrough_seconds_per_stop") or 0.0)
    except Exception:
        walkthrough_seconds_per_stop = 0.0
    if walkthrough_seconds_per_stop > 0.0:
        env["PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP"] = str(walkthrough_seconds_per_stop)
    try:
        completed = subprocess.run(
            command,
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "reason": "generator_timeout",
            "timeout_seconds": timeout_seconds,
            "detail": str(exc)[:500],
        }
    if completed.returncode != 0:
        return {
            "status": "failed",
            "reason": "generator_exit_nonzero",
            "returncode": int(completed.returncode),
            "detail": str((completed.stderr or completed.stdout or "").strip())[-500:],
        }
    raw_stdout = str(completed.stdout or "").strip()
    try:
        result = json.loads(raw_stdout or "{}")
    except Exception:
        result = {}
    if not isinstance(result, dict):
        return {
            "status": "failed",
            "reason": "generator_unparseable",
            "detail": "generator_result_not_object",
        }
    if str(result.get("status") or "").strip() != "generated":
        return {
            "status": "failed",
            "reason": "generator_reported_failure",
            "detail": str(result.get("reason") or result.get("status") or "generator_reported_non_generated_status")[:500],
            "result": result,
        }
    return {
        "status": "generated",
        "result": result,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "PropertyReconstructionRenderBridge/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _write_json(self, status_code: int, payload: dict[str, object]) -> None:
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self) -> bool:
        expected = _bridge_token()
        if not expected:
            return True
        header = str(self.headers.get("Authorization") or "").strip()
        return header == f"Bearer {expected}"

    def do_GET(self) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/health":
            self._write_json(404, {"status": "not_found"})
            return
        self._write_json(
            200,
            {
                "status": "pass",
                "bridge": "property_reconstruction_render_bridge",
                "public_tour_dir": str(_public_tour_dir()),
                "script_ready": _script_path().is_file(),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/generate-reconstruction":
            self._write_json(404, {"status": "not_found"})
            return
        if not self._authorized():
            self._write_json(403, {"status": "forbidden", "reason": "invalid_bridge_token"})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except Exception:
            content_length = 0
        raw_body = self.rfile.read(max(0, content_length)).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_body or "{}")
        except Exception:
            self._write_json(400, {"status": "rejected", "reason": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._write_json(400, {"status": "rejected", "reason": "json_root_not_object"})
            return
        try:
            result = run_generation_request(payload)
        except ValueError as exc:
            self._write_json(422, {"status": "rejected", "reason": str(exc)})
            return
        except Exception as exc:
            self._write_json(500, {"status": "failed", "reason": type(exc).__name__, "detail": str(exc)[:500]})
            return
        status = str(result.get("status") or "").strip()
        self._write_json(200 if status == "generated" else 502, result)


def main() -> int:
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
