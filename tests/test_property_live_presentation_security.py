from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

from scripts import propertyquarry_live_presentation_e2e as presentation_e2e
from scripts.propertyquarry_live_http_security import normalized_origin


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


def test_presentation_authenticated_redirect_never_reaches_second_origin() -> None:
    destination_requests: list[dict[str, str]] = []
    source_requests: list[dict[str, str]] = []

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
                source_requests.append({str(key): str(value) for key, value in self.headers.items()})
                self.send_response(302)
                self.send_header("Location", f"{destination_origin}/capture")
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        with _http_server(SourceHandler) as source_origin:
            result = presentation_e2e._fetch(
                f"{source_origin}/start",
                timeout_seconds=3,
                api_token="sentinel-presentation-token",
                principal_id="principal-sensitive",
                authorized_origin=normalized_origin(source_origin),
            )

    assert result["status_code"] == 302
    assert result["redirect_blocked"] == "cross_origin"
    assert source_requests[0]["Authorization"] == "Bearer sentinel-presentation-token"
    assert destination_requests == []


def test_presentation_receipt_requires_existing_route_without_seeding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider_receipt = tmp_path / "provider.json"
    provider_receipt.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    monkeypatch.setattr(
        presentation_e2e,
        "_fetch",
        lambda *_args, **_kwargs: {"status_code": 404, "headers": {}, "body": "", "final_url": ""},
    )
    monkeypatch.setattr(
        presentation_e2e,
        "seed_research_detail_fixture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("live seeding must not run")),
    )

    receipt = presentation_e2e.build_live_presentation_e2e_receipt(
        base_url="http://127.0.0.1:8097",
        host_header="propertyquarry.com",
        api_token="sentinel-presentation-token",
        principal_id="principal-sensitive",
        provider_receipt_path=str(provider_receipt),
        require_provider_matrix=False,
        demo_slug="demo",
        timeout_seconds=3,
        seed_research_detail=False,
        research_detail_route="",
    )

    route_check = next(row for row in receipt["checks"] if row["name"] == "app_research_detail_route_configured")
    assert route_check["ok"] is False
    assert receipt["status"] == "fail"


def test_presentation_receipt_requires_3dvista_and_retired_matterport(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider_receipt = tmp_path / "provider.json"
    provider_receipt.write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    def fake_fetch(url: str, **kwargs):
        if url.endswith("/?home=1"):
            body = (
                'Danube Flats demo '
                'href="/app/example/shortlist?candidate=danube-flats-demo#danube-flats-demo" '
                '3D tour available /tours/demo/control/3dvista '
                'Walkthrough available /tours/files/demo/magicfit-walkthrough.mp4'
            )
            return {"status_code": 200, "headers": {}, "body": body, "final_url": url}
        if url.endswith("/tours/demo/control/matterport"):
            return {"status_code": 404, "headers": {}, "body": "provider retired", "final_url": url}
        if url.endswith("/tours/demo/control/3dvista") or url.endswith("/tours/demo"):
            body = (
                '3D Tour provider-frame /tours/3dvista/demo/3dvista/index.htm '
                'href="/tours/demo/walkthrough" Open walkthrough'
            )
            return {
                "status_code": 200,
                "headers": {},
                "body": body,
                "final_url": "http://127.0.0.1:8097/tours/demo/control/3dvista",
            }
        if url.endswith("magicfit-walkthrough.mp4"):
            return {
                "status_code": 200,
                "headers": {"Content-Type": "video/mp4", "Content-Length": "1500000"},
                "body": "",
                "final_url": url,
            }
        if "/app/research/" in url:
            return {
                "status_code": 200,
                "headers": {},
                "body": (
                    'data-pw-visual-request="tour" data-pw-visual-request="flythrough" '
                    'data-pw-walkthrough-provider="magicfit"'
                ),
                "final_url": url,
            }
        raise AssertionError(f"unexpected presentation URL: {url}")

    monkeypatch.setattr(presentation_e2e, "_fetch", fake_fetch)
    receipt = presentation_e2e.build_live_presentation_e2e_receipt(
        base_url="http://127.0.0.1:8097",
        host_header="propertyquarry.com",
        api_token="sentinel-presentation-token",
        principal_id="principal-sensitive",
        provider_receipt_path=str(provider_receipt),
        require_provider_matrix=False,
        demo_slug="demo",
        timeout_seconds=3,
        seed_research_detail=False,
        research_detail_route="/app/research/existing?run_id=existing",
    )

    checks = {str(row["name"]): bool(row["ok"]) for row in receipt["checks"]}
    assert receipt["status"] == "pass"
    assert checks["demo_tour_has_verified_3dvista_control"] is True
    assert checks["demo_tour_hides_retired_matterport"] is True
    assert checks["matterport_control_retired"] is True


def test_presentation_seed_failure_redacts_reflected_token(monkeypatch, tmp_path: Path) -> None:
    token = "sentinel-reflected-presentation-token"
    provider_receipt = tmp_path / "provider.json"
    provider_receipt.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    monkeypatch.setattr(
        presentation_e2e,
        "_fetch",
        lambda *_args, **_kwargs: {"status_code": 404, "headers": {}, "body": "", "final_url": ""},
    )
    monkeypatch.setattr(
        presentation_e2e,
        "seed_research_detail_fixture",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(f"upstream reflected {token}")),
    )

    receipt = presentation_e2e.build_live_presentation_e2e_receipt(
        base_url="http://127.0.0.1:8097",
        host_header="propertyquarry.com",
        api_token=token,
        principal_id="principal-sensitive",
        provider_receipt_path=str(provider_receipt),
        require_provider_matrix=False,
        demo_slug="demo",
        timeout_seconds=3,
        seed_research_detail=True,
        research_detail_route="",
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert token not in serialized
    assert "[redacted-secret]" in serialized
