from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Iterator

import pytest

from scripts import propertyquarry_live_authenticated_smoke as authenticated_smoke
from scripts import propertyquarry_live_mobile_surface_smoke as mobile_smoke
from scripts import propertyquarry_map_preview_flagship_gate as map_gate
from scripts.propertyquarry_live_http_security import normalized_origin, validated_live_base_origin


@contextmanager
def _http_server(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_base_origin_requires_https_except_exact_loopback() -> None:
    assert validated_live_base_origin("https://propertyquarry.com") == "https://propertyquarry.com"
    assert validated_live_base_origin("http://127.0.0.1:8090") == "http://127.0.0.1:8090"
    with pytest.raises(ValueError, match="requires_https"):
        validated_live_base_origin("http://propertyquarry.com")
    with pytest.raises(ValueError, match="origin_only"):
        validated_live_base_origin("https://propertyquarry.com/app")
    with pytest.raises(ValueError, match="port_invalid"):
        validated_live_base_origin("https://propertyquarry.com:0")


def test_authenticated_billing_bridge_never_fetches_cross_origin_absolute_path() -> None:
    destination_requests: list[dict[str, str]] = []

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            destination_requests.append({str(key): str(value) for key, value in self.headers.items()})
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    with _http_server(DestinationHandler) as destination_origin:
        with _http_server(SourceHandler) as source_origin:
            fetch_calls: list[str] = []

            def credentialed_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
                fetch_calls.append(url)
                return authenticated_smoke.fetch_url(
                    url,
                    timeout_seconds=timeout_seconds,
                    api_token="sentinel-billing-token",
                    principal_id="principal-sensitive",
                    country_code="AT",
                )

            location = f"{destination_origin}/app/api/property/billing/bridge-launch"
            result = authenticated_smoke._resolve_billing_external_handoff(
                base_url=source_origin,
                location=location,
                fetcher=credentialed_fetcher,
                timeout_seconds=3,
            )

    assert result["external_location"] == location
    assert result["bridge_launch_used"] is False
    assert fetch_calls == []
    assert destination_requests == []


def test_mobile_authenticated_redirect_never_reaches_second_origin() -> None:
    destination_requests: list[dict[str, str]] = []
    source_requests: list[dict[str, str]] = []

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            destination_requests.append({str(key): str(value) for key, value in self.headers.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"destination")

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    with _http_server(DestinationHandler) as destination_origin:
        class SourceHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                source_requests.append({str(key): str(value) for key, value in self.headers.items()})
                self.send_response(302)
                self.send_header("Location", f"{destination_origin}/capture")
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        with _http_server(SourceHandler) as source_origin:
            result = mobile_smoke._http_get_for_smoke(
                f"{source_origin}/start",
                headers={
                    "Authorization": "Bearer sentinel-mobile-token",
                    "X-EA-API-Token": "sentinel-mobile-token",
                    "X-EA-Principal-ID": "principal-sensitive",
                },
                timeout_seconds=3,
                follow_redirects=True,
                authorized_origin=normalized_origin(source_origin),
            )

    assert result["status_code"] == 302
    assert result["redirect_blocked"] == "cross_origin"
    assert source_requests[0]["Authorization"] == "Bearer sentinel-mobile-token"
    assert destination_requests == []


def test_map_gate_authenticated_redirect_never_reaches_second_origin() -> None:
    destination_requests: list[dict[str, str]] = []

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            destination_requests.append({str(key): str(value) for key, value in self.headers.items()})
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    with _http_server(DestinationHandler) as destination_origin:
        class SourceHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", f"{destination_origin}/capture")
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        with _http_server(SourceHandler) as source_origin:
            result = map_gate._fetch(
                f"{source_origin}/start",
                timeout_seconds=3,
                api_token="sentinel-map-token",
                principal_id="principal-sensitive",
                authorized_origin=normalized_origin(source_origin),
            )

    assert result["status_code"] == 302
    assert result["redirect_blocked"] == "cross_origin"
    assert destination_requests == []


def test_map_gate_live_discovery_keeps_only_same_origin_previews(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "http://127.0.0.1:8090"
    same_path = "/app/api/property/map-previews/" + "a" * 40 + ".png"
    external_url = "https://images.example.test/app/api/property/map-previews/" + "b" * 40 + ".png"

    monkeypatch.setattr(
        map_gate,
        "_fetch",
        lambda *_args, **_kwargs: {
            "status_code": 200,
            "body": f'<img src="{same_path}"><img src="{external_url}">'.encode(),
        },
    )

    assert map_gate._discover_preview_urls(
        base_url=base_url,
        routes=["/app/search"],
        timeout_seconds=3,
        host_header="",
        api_token="sentinel-token",
        principal_id="principal",
    ) == [f"{base_url}{same_path}"]


def test_playwright_route_adds_auth_only_on_exact_origin() -> None:
    class Route:
        def __init__(self, url: str, *, inherited_auth: bool = False) -> None:
            request_headers = {"accept": "text/html"}
            if inherited_auth:
                request_headers.update(
                    {
                        "authorization": "Bearer inherited-browser-token",
                        "x-ea-api-token": "inherited-browser-token",
                        "x-ea-principal-id": "inherited-principal",
                    }
                )
            self.request = SimpleNamespace(url=url, headers=request_headers)
            self.calls: list[dict[str, object]] = []

        def continue_(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    headers = {
        "Authorization": "Bearer sentinel-browser-token",
        "X-EA-API-Token": "sentinel-browser-token",
        "X-EA-Principal-ID": "principal-sensitive",
    }
    same_origin = Route("https://propertyquarry.com/app/search")
    other_origin = Route("https://images.example.test/pixel.png", inherited_auth=True)

    mobile_smoke._continue_playwright_route_with_origin_scoped_headers(
        same_origin,
        authorized_origin="https://propertyquarry.com",
        headers=headers,
    )
    mobile_smoke._continue_playwright_route_with_origin_scoped_headers(
        other_origin,
        authorized_origin="https://propertyquarry.com",
        headers=headers,
    )

    assert same_origin.calls[0]["headers"]["Authorization"] == "Bearer sentinel-browser-token"
    assert other_origin.calls == [{"headers": {"accept": "text/html"}}]


def test_authenticated_receipt_redacts_reflected_concrete_token() -> None:
    token = "sentinel-reflected-api-token"

    def _fetcher(_url: str, _timeout: float) -> dict[str, object]:
        return {
            "status_code": 200,
            "headers": {
                "Content-Type": "text/html",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=(), microphone=()",
            },
            "body": f"reflected {token}".encode(),
            "final_url": f"https://propertyquarry.com/probe?echo={token}",
            "error": f"upstream reflected {token}",
        }

    receipt = authenticated_smoke.build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token=token,
        principal_id="principal-test",
        routes=("/probe",),
        retry_count=0,
        fetcher=_fetcher,
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert token not in serialized
    assert "[redacted-secret]" in serialized


@pytest.mark.parametrize(
    "route",
    (
        "/app/research/candidate.secret",
        "/app/research/candidate%2Fsecret",
        "/app/research/~candidate-secret",
        "/app/research/candidate.secret%2F~opaque?run_id=run-secret#fragment-secret",
        "/app/research/candidate-secret#fragment-secret",
    ),
)
def test_research_detail_route_is_redacted_in_logs_and_receipts(route: str) -> None:
    assert mobile_smoke._route_log_label(route) == "/app/research/[redacted]"
    assert mobile_smoke._redact_sensitive_receipt_text(route) == "/app/research/[redacted]"
