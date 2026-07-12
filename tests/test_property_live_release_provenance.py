from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from scripts.propertyquarry_live_release_provenance import build_live_release_provenance_receipt


@contextmanager
def _version_server(payload: dict[str, object], *, redirect_to: str = "") -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if redirect_to:
                self.send_response(302)
                self.send_header("Location", redirect_to)
                self.end_headers()
                return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_release_provenance_requires_exact_commit_branch_and_deployment() -> None:
    commit_sha = "a" * 40
    with _version_server(
        {
            "release_commit_sha": commit_sha,
            "release_branch": "main",
            "release_deployment_id": "deploy-1",
        }
    ) as origin:
        receipt = build_live_release_provenance_receipt(
            base_url=origin,
            expected_commit_sha=commit_sha,
        )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_release_provenance_rejects_stale_or_symbolic_commit() -> None:
    with _version_server(
        {
            "release_commit_sha": "b" * 40,
            "release_branch": "main",
            "release_deployment_id": "deploy-1",
        }
    ) as origin:
        stale = build_live_release_provenance_receipt(
            base_url=origin,
            expected_commit_sha="a" * 40,
        )
        symbolic = build_live_release_provenance_receipt(
            base_url=origin,
            expected_commit_sha="HEAD",
        )

    assert stale["status"] == "fail"
    assert symbolic["status"] == "blocked"


def test_live_release_provenance_does_not_follow_redirects() -> None:
    with _version_server({}) as destination:
        with _version_server({}, redirect_to=f"{destination}/version") as source:
            receipt = build_live_release_provenance_receipt(
                base_url=source,
                expected_commit_sha="a" * 40,
            )

    assert receipt["status"] == "fail"
    assert any(check["name"] == "version_status_ok" and not check["ok"] for check in receipt["checks"])
