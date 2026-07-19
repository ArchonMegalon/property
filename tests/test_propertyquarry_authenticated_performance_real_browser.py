from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.propertyquarry_release_probe import (
    propertyquarry_release_probe_signature,
)
from scripts import propertyquarry_authenticated_performance_smoke as performance


REAL_BROWSER_EXECUTABLE_ENV = (
    "PROPERTYQUARRY_REAL_CHROMIUM_EXECUTABLE_PATH"
)
REQUIRE_REAL_BROWSER_ENV = (
    "PROPERTYQUARRY_REQUIRE_REAL_CHROMIUM_INTEGRATION"
)
RELEASE_PROBE_SECRET = (
    "propertyquarry-real-browser-release-probe-secret-0123456789abcdef"
)
EXPECTED_RELEASE_IDENTITY = {
    "commit_sha": "a1b2c3d4e5f678901234567890abcdef12345678",
    "image_digest": "sha256:" + ("19ab" * 16),
    "deployment_id": "propertyquarry-real-browser-cache-proof",
    "manifest_sha256": "2f7c" * 16,
}
REPLICA_ID = "propertyquarry-real-browser-cache-proof-1"
RELEASE_PROBE_HEADER_NAMES = (
    "x-propertyquarry-release-probe-timestamp",
    "x-propertyquarry-release-probe-nonce",
    "x-propertyquarry-release-probe-signature",
)
CACHEABLE_STYLESHEET = (
    "/* PropertyQuarry real HTTP-cache integration proof. */\n"
    + (".pq-cache-proof{color:#173b2d}\n" * 2048)
).encode("utf-8")
AUTHENTICATED_DOCUMENT = b"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="/app/assets/cache-proof.css">
  </head>
  <body>
    <main data-property-app-shell>Authenticated PropertyQuarry cache proof</main>
  </body>
</html>
"""


class _CacheProofHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lock = threading.Lock()
    document_requests = 0
    asset_requests = 0
    signed_asset_requests = 0
    observed_nonces: set[str] = set()

    def log_message(self, *_args: object) -> None:
        return

    def _send_body(
        self,
        *,
        status: int,
        content_type: str,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/app/assets/cache-proof.css":
            signed = any(self.headers.get(name) for name in RELEASE_PROBE_HEADER_NAMES)
            with self.lock:
                type(self).asset_requests += 1
                if signed:
                    type(self).signed_asset_requests += 1
            self._send_body(
                status=400 if signed else 200,
                content_type="text/css; charset=utf-8",
                body=b"signed subresource forbidden" if signed else CACHEABLE_STYLESHEET,
                headers={
                    "Cache-Control": "public, max-age=3600, immutable",
                    "ETag": '"propertyquarry-real-cache-proof-v1"',
                },
            )
            return

        if self.path != "/app/search":
            self.send_error(404)
            return

        timestamp = str(
            self.headers.get("x-propertyquarry-release-probe-timestamp") or ""
        )
        nonce = str(
            self.headers.get("x-propertyquarry-release-probe-nonce") or ""
        )
        signature = str(
            self.headers.get("x-propertyquarry-release-probe-signature") or ""
        )
        origin = f"http://127.0.0.1:{self.server.server_port}"
        expected_signature = propertyquarry_release_probe_signature(
            secret=RELEASE_PROBE_SECRET,
            origin=origin,
            method="GET",
            path="/app/search",
            query_string="",
            timestamp=timestamp,
            nonce=nonce,
        )
        try:
            timestamp_is_fresh = abs(int(time.time()) - int(timestamp)) <= 60
        except (TypeError, ValueError):
            timestamp_is_fresh = False
        with self.lock:
            nonce_is_unique = nonce not in type(self).observed_nonces
            if nonce and nonce_is_unique:
                type(self).observed_nonces.add(nonce)
        if not (
            nonce
            and nonce_is_unique
            and timestamp_is_fresh
            and hmac.compare_digest(signature, expected_signature)
        ):
            self.send_error(401)
            return

        with self.lock:
            type(self).document_requests += 1
        nonce_sha256 = hashlib.sha256(
            f"propertyquarry-release-probe\0{nonce}".encode("utf-8")
        ).hexdigest()
        self._send_body(
            status=200,
            content_type="text/html; charset=utf-8",
            body=AUTHENTICATED_DOCUMENT,
            headers={
                "Cache-Control": "no-store",
                "X-PropertyQuarry-Release-Commit": EXPECTED_RELEASE_IDENTITY[
                    "commit_sha"
                ],
                "X-PropertyQuarry-Release-Image": EXPECTED_RELEASE_IDENTITY[
                    "image_digest"
                ],
                "X-PropertyQuarry-Release-Deployment": EXPECTED_RELEASE_IDENTITY[
                    "deployment_id"
                ],
                "X-PropertyQuarry-Release-Manifest-Status": "complete",
                "X-PropertyQuarry-Release-Manifest-Sha256": (
                    EXPECTED_RELEASE_IDENTITY["manifest_sha256"]
                ),
                "X-PropertyQuarry-Replica-Id": REPLICA_ID,
                "X-PropertyQuarry-Release-Probe-Nonce-Sha256": nonce_sha256,
            },
        )


def _installed_chromium_executable() -> Path:
    required = str(os.getenv(REQUIRE_REAL_BROWSER_ENV) or "0").strip()
    if required not in {"0", "1"}:
        pytest.fail(f"{REQUIRE_REAL_BROWSER_ENV} must be exactly 0 or 1")
    configured = str(os.getenv(REAL_BROWSER_EXECUTABLE_ENV) or "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
    else:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            if required == "1":
                pytest.fail(
                    "Required Playwright Chromium integration is unavailable: "
                    f"{type(exc).__name__}"
                )
            pytest.skip(f"Playwright unavailable: {type(exc).__name__}")
        with sync_playwright() as playwright:
            candidate = Path(playwright.chromium.executable_path).resolve()
    if not candidate.is_file() and (configured or required == "1"):
        pytest.fail(
            "Required real Chromium executable is unavailable after browser "
            "installation."
        )
    if not candidate.is_file():
        pytest.skip(
            "A real Chromium executable is required; install Playwright Chromium "
            f"or set {REAL_BROWSER_EXECUTABLE_ENV}."
        )
    return candidate


def test_explicit_real_chromium_path_absence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        REAL_BROWSER_EXECUTABLE_ENV,
        str(tmp_path / "missing-chromium"),
    )
    monkeypatch.delenv(REQUIRE_REAL_BROWSER_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception, match="Required real Chromium"):
        _installed_chromium_executable()


def test_real_chromium_signed_document_navigation_preserves_http_cache() -> None:
    executable = _installed_chromium_executable()
    _CacheProofHandler.document_requests = 0
    _CacheProofHandler.asset_requests = 0
    _CacheProofHandler.signed_asset_requests = 0
    _CacheProofHandler.observed_nonces = set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CacheProofHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        receipt = performance.collect_constrained_client_browser_evidence(
            target_url=f"http://127.0.0.1:{server.server_port}/app/search",
            authentication_bootstrap_url="",
            release_probe_secret=RELEASE_PROBE_SECRET,
            profile=performance.ConstrainedClientProfile(),
            expected_release_identity=EXPECTED_RELEASE_IDENTITY,
            expected_chromium_executable_path=str(executable),
            expected_chromium_executable_sha256=performance._sha256_file(
                executable
            ),
            browser_engine="chromium",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert receipt.get("status") == "pass", receipt
    assert receipt["authentication"] == {
        "method": "signed_release_probe_per_navigation",
        "navigation_signing_mechanism": (
            "chromium_cdp_Fetch.requestPaused_document_only"
        ),
        "playwright_routing_used": False,
        "subresource_http_cache_preserved": True,
        "signed_navigation_count": 2,
        "distinct_nonce_count": 2,
        "target_surface_observed": True,
        "release_probe_secret_persisted": False,
    }
    assert _CacheProofHandler.document_requests == 2
    assert _CacheProofHandler.asset_requests == 1
    assert _CacheProofHandler.signed_asset_requests == 0
    assert len(_CacheProofHandler.observed_nonces) == 2

    cold = receipt["measurements"]["cold"]
    warm = receipt["measurements"]["warm"]
    assert cold["cache_hit_count"] == 0
    assert cold["subresource_cache_hit_count"] == 0
    assert cold["transferred_bytes"] > 0
    assert cold["failed_request_count"] == 0
    assert cold["incomplete_request_count"] == 0
    assert cold["ok"] is True
    assert warm["cache_hit_count"] >= 1
    assert warm["subresource_cache_hit_count"] >= 1
    assert warm["transferred_bytes"] < cold["transferred_bytes"]
    assert warm["failed_request_count"] == 0
    assert warm["incomplete_request_count"] == 0
    assert warm["ok"] is True
