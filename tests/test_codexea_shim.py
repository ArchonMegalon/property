from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
CODEXEA = ROOT / "scripts" / "codexea"


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "CODEXEA_STATE_DIR": str(tmp_path / "state"),
            "CODEXEA_USE_LIVE_PROFILE_MODELS": "0",
            "CODEXEA_TRACE_STARTUP": "0",
            "CODEXEA_STARTUP_STATUS": "0",
            "CODEXEA_POST_AUDIT": "0",
            "CODEXEA_PREFER_RUNTIME_AUTH": "0",
            "EA_MCP_BASE_URL": "http://127.0.0.1:8090",
            "EA_BASE_URL": "http://127.0.0.1:8090",
            "CODEXEA_STATUS_URL": "http://127.0.0.1:8090/v1/codex/status",
            "CODEXEA_PROFILES_URL": "http://127.0.0.1:8090/v1/codex/profiles",
        }
    )
    return env


def _fake_codex(tmp_path: Path) -> Path:
    capture_path = tmp_path / "argv.json"
    fake_codex = tmp_path / "fake-codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                f"with open({capture_path.as_posix()!r}, 'w', encoding='utf-8') as handle:",
                "    json.dump(sys.argv[1:], handle)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    return fake_codex


def test_codexea_rejects_unsafe_base_url(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["EA_MCP_BASE_URL"] = "javascript:alert(1)"
    env["EA_BASE_URL"] = "javascript:alert(1)"
    env["CODEXEA_REAL_CODEX"] = "/bin/true"

    completed = subprocess.run(
        ["bash", str(CODEXEA), "core", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Unsafe EA_BASE_URL" in completed.stderr


def test_codexea_rejects_control_chars_in_auth_headers(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["EA_API_TOKEN"] = "bad\nvalue"
    env["CODEXEA_REAL_CODEX"] = "/bin/true"

    completed = subprocess.run(
        ["bash", str(CODEXEA), "core", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Unsafe EA_AUTH_TOKEN" in completed.stderr


def test_codexea_escapes_config_payload_values_before_invoking_codex(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)

    env = _base_env(tmp_path)
    env["CODEXEA_REAL_CODEX"] = str(fake_codex)
    env["EA_PRINCIPAL_ID"] = 'alpha"beta'
    env["EA_API_TOKEN"] = 'tok"en'

    completed = subprocess.run(
        ["bash", str(CODEXEA), "core", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    headers_arg = next(item for item in argv if item.startswith("model_providers.ea.http_headers="))
    assert '"X-EA-Principal-ID"="alpha\\"beta"' in headers_arg
    assert '"Authorization"="Bearer tok\\"en"' in headers_arg


def test_codexea_easy_defaults_to_responses_fast_lane(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)

    env = _base_env(tmp_path)
    env["CODEXEA_REAL_CODEX"] = str(fake_codex)

    completed = subprocess.run(
        ["bash", str(CODEXEA), "easy", "design a dashboard"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    assert 'model_provider="ea"' in argv
    assert 'model="ea-coder-fast"' in argv


def test_codexea_falls_back_to_local_ea_when_default_ingress_is_unavailable(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env = _base_env(tmp_path)
        env["CODEXEA_REAL_CODEX"] = str(fake_codex)
        env["CODEXEA_DEFAULT_BASE_URL"] = "http://127.0.0.1:9"
        env["CODEXEA_LOCAL_FALLBACK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        env["CODEXEA_RUNTIME_ENV_DEFAULTS"] = "0"
        env.pop("EA_MCP_BASE_URL", None)
        env.pop("EA_BASE_URL", None)
        env.pop("CODEXEA_STATUS_URL", None)
        env.pop("CODEXEA_PROFILES_URL", None)

        completed = subprocess.run(
            ["bash", str(CODEXEA), "core", "--version"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    assert f'model_providers.ea.base_url="http://127.0.0.1:{server.server_port}/v1"' in argv


def test_codexea_keeps_primary_ingress_when_probe_returns_401(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"auth required"}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env = _base_env(tmp_path)
        env["CODEXEA_REAL_CODEX"] = str(fake_codex)
        env["CODEXEA_DEFAULT_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        env["CODEXEA_LOCAL_FALLBACK_BASE_URL"] = "http://127.0.0.1:9"
        env["CODEXEA_RUNTIME_ENV_DEFAULTS"] = "0"
        env.pop("EA_MCP_BASE_URL", None)
        env.pop("EA_BASE_URL", None)
        env.pop("CODEXEA_STATUS_URL", None)
        env.pop("CODEXEA_PROFILES_URL", None)

        completed = subprocess.run(
            ["bash", str(CODEXEA), "core", "--version"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    assert f'model_providers.ea.base_url="http://127.0.0.1:{server.server_port}/v1"' in argv


def test_codexea_falls_back_to_local_ea_when_primary_probe_returns_404(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)
    primary_hits: list[str] = []

    class PrimaryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            primary_hits.append(self.path)
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"missing"}')

        def log_message(self, format: str, *args: object) -> None:
            return

    class FallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: object) -> None:
            return

    primary_server = ThreadingHTTPServer(("127.0.0.1", 0), PrimaryHandler)
    fallback_server = ThreadingHTTPServer(("127.0.0.1", 0), FallbackHandler)
    primary_thread = threading.Thread(target=primary_server.serve_forever, daemon=True)
    fallback_thread = threading.Thread(target=fallback_server.serve_forever, daemon=True)
    primary_thread.start()
    fallback_thread.start()

    try:
        env = _base_env(tmp_path)
        env["CODEXEA_REAL_CODEX"] = str(fake_codex)
        env["CODEXEA_DEFAULT_BASE_URL"] = f"http://127.0.0.1:{primary_server.server_port}"
        env["CODEXEA_LOCAL_FALLBACK_BASE_URL"] = f"http://127.0.0.1:{fallback_server.server_port}"
        env["CODEXEA_RUNTIME_ENV_DEFAULTS"] = "0"
        env.pop("EA_MCP_BASE_URL", None)
        env.pop("EA_BASE_URL", None)
        env.pop("CODEXEA_STATUS_URL", None)
        env.pop("CODEXEA_PROFILES_URL", None)

        completed = subprocess.run(
            ["bash", str(CODEXEA), "core", "--version"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        primary_server.shutdown()
        primary_server.server_close()
        primary_thread.join(timeout=2)
        fallback_server.shutdown()
        fallback_server.server_close()
        fallback_thread.join(timeout=2)

    assert completed.returncode == 0
    assert primary_hits == ["/v1/codex/status?probe=1"]
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    assert f'model_providers.ea.base_url="http://127.0.0.1:{fallback_server.server_port}/v1"' in argv


def test_codexea_runtime_env_transport_does_not_disable_probe_fallback(tmp_path: Path) -> None:
    capture_path = tmp_path / "argv.json"
    fake_codex = _fake_codex(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime_env = tmp_path / ".env"
    runtime_env.write_text(
        "\n".join(
            [
                "EA_BASE_URL=http://127.0.0.1:9",
                "CODEXEA_STATUS_URL=http://127.0.0.1:9/v1/codex/status",
                "CODEXEA_PROFILES_URL=http://127.0.0.1:9/v1/codex/profiles",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        env = _base_env(tmp_path)
        env["CODEXEA_REAL_CODEX"] = str(fake_codex)
        env["CODEXEA_DEFAULT_BASE_URL"] = "http://127.0.0.1:8"
        env["CODEXEA_LOCAL_FALLBACK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        env["CODEXEA_RUNTIME_EA_ENV_PATH"] = str(runtime_env)
        env.pop("EA_MCP_BASE_URL", None)
        env.pop("EA_BASE_URL", None)
        env.pop("CODEXEA_STATUS_URL", None)
        env.pop("CODEXEA_PROFILES_URL", None)

        completed = subprocess.run(
            ["bash", str(CODEXEA), "core", "--version"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0
    argv = json.loads(capture_path.read_text(encoding="utf-8"))
    assert f'model_providers.ea.base_url="http://127.0.0.1:{server.server_port}/v1"' in argv
