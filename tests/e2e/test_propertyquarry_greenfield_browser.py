from __future__ import annotations

import json
import re
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app
from app.product.models import HandoffNote
from app.product.service import ProductService


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/sign-in", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


def _write_floorplan_png(path: Path) -> None:
    image = Image.new("RGB", (1280, 900), (248, 246, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1200, 820), outline=(42, 42, 42), width=8)
    draw.line((420, 80, 420, 820), fill=(58, 58, 58), width=6)
    draw.line((80, 410, 1200, 410), fill=(58, 58, 58), width=6)
    draw.rectangle((450, 120, 1110, 360), outline=(148, 68, 48), width=6)
    draw.rectangle((110, 120, 380, 360), outline=(73, 108, 170), width=6)
    draw.rectangle((110, 450, 380, 770), outline=(73, 108, 170), width=6)
    draw.rectangle((450, 450, 1110, 770), outline=(148, 68, 48), width=6)
    draw.text((150, 210), "Entry", fill=(30, 30, 30))
    draw.text((690, 220), "Living", fill=(30, 30, 30))
    draw.text((160, 600), "Bath", fill=(30, 30, 30))
    draw.text((720, 600), "Bedroom", fill=(30, 30, 30))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_cube_face_png(path: Path, *, label: str, fill: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (1024, 1024), fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((36, 36, 988, 988), outline=(248, 245, 240), width=14)
    draw.text((84, 104), "PropertyQuarry", fill=(255, 255, 255))
    draw.text((84, 180), label, fill=(250, 247, 242))
    draw.rectangle((120, 280, 904, 760), outline=(255, 255, 255), width=10)
    draw.rectangle((180, 340, 500, 720), fill=(235, 231, 224))
    draw.rectangle((548, 340, 840, 720), fill=(198, 166, 122))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_h264_flythrough(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#d8d0c4:s=1280x720:d=3",
        "-vf",
        (
            "drawbox=x=0:y=0:w=iw:h=110:color=#181a1dcc:t=fill,"
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            "text='PropertyQuarry Flythrough':fontcolor=white:fontsize=34:x=48:y=40,"
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
            "text='Best-match route':fontcolor=#ece6df:fontsize=20:x=52:y=82,"
            "drawbox=x='120+220*t':y='250+30*sin(t*2)':w=820:h=210:color=#a46842:t=6,"
            "drawbox=x='170+220*t':y='300+28*sin(t*2)':w=330:h=110:color=#5a7bb2:t=fill,"
            "drawbox=x='560+220*t':y='300+20*sin(t*2)':w=250:h=110:color=#e7e3dc:t=fill,"
            "drawbox=x='845+220*t':y='300+14*sin(t*2)':w=90:h=110:color=#88a36f:t=fill"
        ),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _video_frame_brightness(page: Page) -> float:
    return float(
        page.evaluate(
            """() => {
                const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
                if (!video || !video.videoWidth || !video.videoHeight) return 0;
                const canvas = document.createElement('canvas');
                canvas.width = Math.min(video.videoWidth, 160);
                canvas.height = Math.min(video.videoHeight, 90);
                const ctx = canvas.getContext('2d');
                if (!ctx) return 0;
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                let total = 0;
                for (let index = 0; index < data.length; index += 4) {
                    total += (data[index] + data[index + 1] + data[index + 2]) / 3;
                }
                return total / (data.length / 4);
            }"""
        )
    )


@pytest.fixture()
def propertyquarry_browser_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, object]]:
    from tests.product_test_helpers import build_product_client, start_workspace

    monkeypatch.setenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret")
    monkeypatch.setenv("FLIPLINK_WEBHOOK_SECRET", "webhook-secret")
    bundle_root = tmp_path / "public_tours"
    slug = "altbau-u6"
    bundle_dir = bundle_root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write_floorplan_png(bundle_dir / "floorplan-01.png")
    _write_h264_flythrough(bundle_dir / "tour.mp4")
    _write_cube_face_png(bundle_dir / "scene-01.png", label="Living room", fill=(108, 82, 59))
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Altbau near U6",
                "display_title": "Altbau near U6",
                "hosted_url": f"/tours/{slug}",
                "public_url": f"/tours/{slug}",
                "brand_name": "PropertyQuarry",
                "scene_strategy": "layout_first",
                "creation_mode": "hosted_floorplan_tour",
                "video_relpath": "tour.mp4",
                "scenes": [
                    {
                        "scene_id": "panorama-1",
                        "name": "Living room anchor",
                        "role": "photo",
                        "asset_relpath": "scene-01.png",
                        "image_url": "scene-01.png",
                        "mime_type": "image/png",
                    },
                    {
                        "scene_id": "floorplan-1",
                        "name": "Main floorplan",
                        "role": "floorplan",
                        "asset_relpath": "floorplan-01.png",
                        "mime_type": "image/png",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(bundle_root))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    client = build_product_client(principal_id="pq-greenfield-browser")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text

    run_status_calls: dict[str, int] = {}

    def _fake_empty_run_status(*, run_id: str, principal_id: str, processed: bool) -> dict[str, object]:
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed" if processed else "in_progress",
            "generated_at": "2026-06-05T07:00:00+00:00",
            "updated_at": "2026-06-05T07:01:00+00:00" if processed else "2026-06-05T07:00:15+00:00",
            "progress": 100 if processed else 12,
            "message": "No strong matches met the selected threshold." if processed else "Scanning cooperative providers.",
            "summary": {
                "sources_total": 2,
                "listing_total": 14 if processed else 3,
                "filtered_low_fit_total": 14 if processed else 0,
                "high_fit_total": 0,
                "high_match_min_score": 80,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Genossenschaften Austria",
                        "status": "scanned",
                        "listing_total": 8 if processed else 2,
                        "high_fit_total": 0,
                        "filtered_low_fit_total": 8 if processed else 0,
                    },
                    {
                        "source_label": "Justiz Edikte Austria",
                        "status": "scanned",
                        "listing_total": 6 if processed else 1,
                        "high_fit_total": 0,
                        "filtered_low_fit_total": 6 if processed else 0,
                    },
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 provider(s) for scanning.", "status": "in_progress"},
                {
                    "step": "completed" if processed else "provider_scan",
                    "message": "No strong matches met the selected threshold." if processed else "Scanning cooperative providers.",
                    "status": "processed" if processed else "in_progress",
                },
            ],
        }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-greenfield-browser"
        if run_id == "run-active-empty":
            calls = run_status_calls.get(run_id, 0)
            run_status_calls[run_id] = calls + 1
            return _fake_empty_run_status(run_id=run_id, principal_id=principal_id, processed=calls > 0)
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "held_back_total": 2,
            "summary": {
                "sources_total": 2,
                "listing_total": 7,
                "held_back_total": 2,
                "tour_created_total": 1,
                "tour_existing_total": 1,
                "sources": [
                    {
                        "source_label": "ImmoScout24 Germany",
                        "listing_total": 4,
                        "high_fit_total": 2,
                        "tour_created_total": 1,
                        "notified_total": 1,
                        "top_candidates": [
                            {
                                "title": "Altbau near U6",
                                "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
                                "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
                                "recommendation": "shortlist",
                                "review_url": "/app/handoffs/human_task:review-1",
                                "tour_url": "/tours/altbau-u6",
                                "match_reasons": ["Lift and transit fit."],
                                "mismatch_reasons": [],
                                "property_facts": {
                                    "price_display": "EUR 420,000",
                                    "price_eur": 420000.0,
                                    "rooms": 3,
                                    "area_m2": 78,
                                    "postal_name": "Berlin Mitte",
                                    "nearest_supermarket_m": 280,
                                    "nearest_pharmacy_m": 410,
                                    "nearest_playground_m": 520,
                                    "nearest_subway_m": 1200,
                                },
                            },
                            {
                                "title": "Family flat near Tiergarten",
                                "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
                                "fit_summary": "Personal fit 87/100 · shortlist · Larger layout and quieter block.",
                                "recommendation": "shortlist",
                                "review_url": "/app/handoffs/human_task:review-2",
                                "tour_url": "",
                                "match_reasons": ["Larger layout and quieter block."],
                                "mismatch_reasons": ["No 360 tour yet."],
                                "property_facts": {
                                    "price_display": "EUR 465,000",
                                    "price_eur": 465000.0,
                                    "rooms": 4,
                                    "area_m2": 92,
                                    "postal_name": "Berlin Tiergarten",
                                },
                            },
                            {
                                "title": "Listing URL only loft",
                                "listing_url": "https://www.immobilienscout24.de/expose/listing-url-only-loft",
                                "fit_summary": "Personal fit 84/100 · shortlist · Source adapter only supplied listing_url.",
                                "recommendation": "shortlist",
                                "review_url": "/app/handoffs/human_task:review-listing-only",
                                "tour_url": "",
                                "match_reasons": ["Valid listing URL is available."],
                                "mismatch_reasons": ["No 360 tour yet."],
                                "property_facts": {
                                    "price_display": "EUR 455,000",
                                    "price_eur": 455000.0,
                                    "rooms": 3,
                                    "area_m2": 82,
                                    "postal_name": "Berlin Charlottenburg",
                                },
                            },
                        ],
                    }
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 provider(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-greenfield-browser"
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for Auhofstrasse shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="/tours/auhofstrasse-14997053",
            ),
        )

    def _fake_persist_decision_loop(self, *, principal_id: str, person_id: str, snapshot: object) -> dict[str, object]:
        assert principal_id == "pq-greenfield-browser"
        return {
            "persisted": True,
            "decision_id": str(getattr(getattr(snapshot, "decision", None), "decision_id", "")),
            "person_id": person_id,
            "source": "browser_fixture",
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)
    monkeypatch.setattr(ProductService, "_persist_property_decision_loop", _fake_persist_decision_loop)

    app = create_app()
    test_client = TestClient(app, base_url="https://propertyquarry.com")
    test_client.headers.update({"X-EA-Principal-ID": "pq-greenfield-browser", "host": "propertyquarry.com"})

    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    local_base_url = f"http://127.0.0.1:{port}"
    browser_base_url = f"http://propertyquarry.com:{port}"
    _wait_for_http(local_base_url)
    try:
        yield {"base_url": browser_base_url, "client": test_client}
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--host-resolver-rules=MAP propertyquarry.com 127.0.0.1",
                "--no-proxy-server",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def _new_context(
    browser: Browser,
    *,
    mobile: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> BrowserContext:
    return browser.new_context(
        viewport={
            "width": width if width is not None else (430 if mobile else 1440),
            "height": height if height is not None else (932 if mobile else 1100),
        },
        extra_http_headers={"X-EA-Principal-ID": "pq-greenfield-browser"},
    )


def _issue_browser_workspace_session(
    *,
    client: TestClient,
    context: BrowserContext,
    base_url: str,
) -> str:
    session_response = client.post(
        "/app/api/access-sessions",
        json={
            "email": "alice@example.com",
            "role": "principal",
            "display_name": "Alice",
            "expires_in_hours": 4,
        },
    )
    assert session_response.status_code == 200, session_response.text
    access_token = session_response.json().get("access_token", "")
    assert isinstance(access_token, str) and access_token.strip(), session_response.text
    context.add_cookies(
        [
            {
                "name": "ea_workspace_session",
                "value": access_token,
                "url": base_url,
            }
        ]
    )
    return access_token


def _new_public_context(
    browser: Browser,
    *,
    mobile: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> BrowserContext:
    return browser.new_context(
        viewport={
            "width": width if width is not None else (430 if mobile else 1440),
            "height": height if height is not None else (932 if mobile else 1000),
        },
    )


def _assert_no_horizontal_overflow(page: Page) -> None:
    overflow = page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
            offenders: Array.from(document.querySelectorAll('body *'))
              .map((node) => {
                const rect = node.getBoundingClientRect();
                return {
                  tag: node.tagName,
                  className: String(node.className || ''),
                  text: String(node.textContent || '').trim().slice(0, 90),
                  left: Math.round(rect.left),
                  right: Math.round(rect.right),
                  width: Math.round(rect.width),
                };
              })
              .filter((row) => row.right > window.innerWidth + 1 || row.left < -1)
              .slice(0, 8),
        })"""
    )
    assert overflow["scrollWidth"] <= overflow["innerWidth"] + 1, overflow
    assert overflow["bodyScrollWidth"] <= overflow["innerWidth"] + 1, overflow


def test_propertyquarry_public_home_and_sign_in_capture_polish_screenshots(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    desktop = _new_public_context(browser, mobile=False, width=1440, height=1050)
    mobile = _new_public_context(browser, mobile=True)
    try:
        desktop_page = desktop.new_page()
        response = desktop_page.goto(f"{base_url}/?home=1", wait_until="networkidle")
        assert response is not None and response.ok
        expect(desktop_page.get_by_role("heading", name="Search once. Rank the right homes. Decide with evidence.")).to_be_visible()
        expect(desktop_page.get_by_text("Vienna family search")).to_be_visible()
        _assert_no_horizontal_overflow(desktop_page)
        desktop_home = tmp_path / "propertyquarry-public-home-desktop.png"
        desktop_page.screenshot(path=str(desktop_home), full_page=True)
        assert desktop_home.exists()

        mobile_page = mobile.new_page()
        response = mobile_page.goto(f"{base_url}/?home=1", wait_until="networkidle")
        assert response is not None and response.ok
        expect(mobile_page.get_by_role("heading", name="Search once. Rank the right homes. Decide with evidence.")).to_be_visible()
        expect(mobile_page.locator(".pq-hero-copy .btn.primary", has_text="Create account")).to_be_visible()
        expect(mobile_page.locator(".topbar .nav")).to_be_hidden()
        expect(mobile_page.locator(".mobile-nav")).to_be_hidden()
        expect(mobile_page.locator(".topbar .actions .btn", has_text="Sign in")).to_be_visible()
        mobile_header_metrics = mobile_page.evaluate(
            """() => {
                const action = document.querySelector('.topbar .actions .btn');
                const brand = document.querySelector('.topbar .brand');
                const actionRect = action ? action.getBoundingClientRect() : null;
                const brandRect = brand ? brand.getBoundingClientRect() : null;
                return {
                    actionRight: actionRect ? actionRect.right : 0,
                    actionLeft: actionRect ? actionRect.left : 0,
                    brandLeft: brandRect ? brandRect.left : 0,
                    viewportWidth: window.innerWidth,
                };
            }"""
        )
        assert mobile_header_metrics["brandLeft"] >= 0
        assert mobile_header_metrics["actionLeft"] >= 0
        assert mobile_header_metrics["actionRight"] <= mobile_header_metrics["viewportWidth"] + 1
        _assert_no_horizontal_overflow(mobile_page)
        mobile_home = tmp_path / "propertyquarry-public-home-mobile.png"
        mobile_page.screenshot(path=str(mobile_home), full_page=True)
        assert mobile_home.exists()

        response = desktop_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        expect(desktop_page.get_by_role("heading", name="Sign in to continue your property search.")).to_be_visible()
        expect(desktop_page.get_by_text("Use your current session, secure email link, or connected identity.")).to_be_visible()
        expect(desktop_page.get_by_role("link", name="Open current session")).to_be_visible()
        expect(desktop_page.get_by_role("button", name="Continue with Google")).to_be_visible()
        expect(desktop_page.get_by_role("button", name="Continue with Facebook")).to_have_count(0)
        _assert_no_horizontal_overflow(desktop_page)
        sign_in_shot = tmp_path / "propertyquarry-sign-in-desktop.png"
        desktop_page.screenshot(path=str(sign_in_shot), full_page=True)
        assert sign_in_shot.exists()

        response = mobile_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        expect(mobile_page.get_by_role("heading", name="Sign in to continue your property search.")).to_be_visible()
        expect(mobile_page.get_by_role("button", name="Continue with Google")).to_be_visible()
        _assert_no_horizontal_overflow(mobile_page)
        mobile_sign_in_shot = tmp_path / "propertyquarry-sign-in-mobile.png"
        mobile_page.screenshot(path=str(mobile_sign_in_shot), full_page=True)
        assert mobile_sign_in_shot.exists()

        response = mobile_page.goto(f"{base_url}/pricing", wait_until="networkidle")
        assert response is not None and response.ok
        expect(mobile_page.get_by_role("heading", name="Pricing")).to_be_visible()
        _assert_no_horizontal_overflow(mobile_page)
        mobile_pricing_shot = tmp_path / "propertyquarry-pricing-mobile.png"
        mobile_page.screenshot(path=str(mobile_pricing_shot), full_page=True)
        assert mobile_pricing_shot.exists()
    finally:
        desktop.close()
        mobile.close()


def _assert_property_shell_visual_gates(page: Page, *, max_appbar_height: int) -> None:
    appbar = page.locator(".pq-appbar, .pqx-topbar").first
    if appbar.count() == 0:
        return
    appbar_box = appbar.bounding_box()
    assert appbar_box is not None
    assert appbar_box["height"] <= max_appbar_height
    offenders = page.evaluate(
        """
        () => {
          const boxSelectors = ['.pq-appbar', '.pqx-topbar', '.pq-hero', '.pq-card', '.pq-shortlist-card', '.object-panel', '.pqx-panel', '.pqx-card', '.pqx-table-card'];
          const textSelectors = ['h1', 'h2', 'h3', 'p', 'small', '.pq-copy', '.pq-shortlist-meta', '.pq-shortlist-copy', '.object-copy', '.pqx-note', '.pqx-small'];
          const rows = [];
          for (const box of document.querySelectorAll(boxSelectors.join(','))) {
            const boxRect = box.getBoundingClientRect();
            if (boxRect.width <= 0 || boxRect.height <= 0) continue;
            for (const child of box.querySelectorAll(textSelectors.join(','))) {
              const closedDetails = child.closest('details:not([open])');
              if (closedDetails && !child.closest('summary')) continue;
              const childRect = child.getBoundingClientRect();
              if (childRect.width <= 0 || childRect.height <= 0) continue;
              if (
                childRect.left < boxRect.left - 1 ||
                childRect.right > boxRect.right + 1 ||
                childRect.top < boxRect.top - 1 ||
                childRect.bottom > boxRect.bottom + 1
              ) {
                rows.push({
                  box: box.className,
                  text: (child.textContent || '').trim().slice(0, 100),
                  deltaRight: Math.round(childRect.right - boxRect.right),
                  deltaBottom: Math.round(childRect.bottom - boxRect.bottom),
                });
              }
            }
          }
          return rows;
        }
        """
    )
    assert offenders == []


def _assert_visible_component_contrast(page: Page, selectors: list[str], *, minimum_ratio: float) -> None:
    offenders = page.evaluate(
        """
        ({ selectors, minimumRatio }) => {
          const parseColor = (value) => {
            const match = String(value || '').match(/rgba?\\(([^)]+)\\)/);
            if (!match) return null;
            const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
            if (parts.length < 3) return null;
            return { r: parts[0], g: parts[1], b: parts[2], a: parts.length >= 4 ? parts[3] : 1 };
          };
          const channel = (value) => {
            const scaled = value / 255;
            return scaled <= 0.03928 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4);
          };
          const luminance = (color) => 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
          const contrast = (first, second) => {
            const a = luminance(first);
            const b = luminance(second);
            const lighter = Math.max(a, b);
            const darker = Math.min(a, b);
            return (lighter + 0.05) / (darker + 0.05);
          };
          const effectiveBackground = (node) => {
            let current = node;
            while (current && current.nodeType === Node.ELEMENT_NODE) {
              const color = parseColor(window.getComputedStyle(current).backgroundColor);
              if (color && color.a > 0.01) return color;
              current = current.parentElement;
            }
            return parseColor(window.getComputedStyle(document.body).backgroundColor);
          };
          const rows = [];
          for (const selector of selectors) {
            for (const node of document.querySelectorAll(selector)) {
              const rect = node.getBoundingClientRect();
              if (rect.width <= 0 || rect.height <= 0) continue;
              const style = window.getComputedStyle(node);
              const text = parseColor(style.color);
              const background = effectiveBackground(node);
              if (!text || !background) continue;
              const ratio = contrast(text, background);
              if (ratio < minimumRatio) {
                rows.push({
                  selector,
                  text: (node.textContent || '').trim().slice(0, 80),
                  ratio: Math.round(ratio * 100) / 100,
                  color: style.color,
                  background: window.getComputedStyle(node).backgroundColor,
                });
              }
            }
          }
          return rows;
        }
        """,
        {"selectors": selectors, "minimumRatio": minimum_ratio},
    )
    assert offenders == []


def _assert_research_packet_360_first(page: Page, *, min_stage_height: int, max_stage_height: int | None = None) -> None:
    media = page.locator("[data-object-media-stage]").first
    ooda = page.get_by_text("Property details").first
    assert media.is_visible()
    assert ooda.is_visible()
    media_box = media.bounding_box()
    ooda_box = ooda.bounding_box()
    assert media_box is not None
    assert ooda_box is not None
    assert media_box["y"] < ooda_box["y"]
    assert media_box["height"] >= min_stage_height
    if max_stage_height is not None:
        assert media_box["height"] <= max_stage_height


def test_propertyquarry_greenfield_workspace_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-spa-shell' in content
        assert 'data-property-mobile-dock' in content
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-pq-theater' in content
        assert 'data-workbench-results-table' in content
        page.locator("[data-workbench-row]:visible").first.wait_for(timeout=5000)
        assert page.locator("[data-workbench-row]").first.is_visible()
        assert page.locator("[data-workbench-row][data-candidate-packet-url]").first.is_visible()
        assert page.locator("body", has_text=re.compile(r"ranked homes", re.I)).is_visible()
        assert "Altbau near U6" in content
        assert "Family flat near Tiergarten" in content
        assert page.locator("body", has_text="360 ready").is_visible()
        assert page.locator("body", has_text="Open property").is_visible()
        assert "360 ready" in content
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        page.locator("[data-workbench-row]", has_text="Altbau near U6").click()
        assert "/app/shortlist" in page.url
        assert page.locator("[data-workbench-row][aria-selected='true']", has_text="Altbau near U6").is_visible()
    finally:
        context.close()


def test_propertyquarry_dark_mode_keeps_shortlist_cards_readable(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=1100)
    context.add_init_script("window.localStorage.setItem('propertyquarry.theme', 'dark');")
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.locator("html")).to_have_attribute("data-pq-theme", "dark")
        page.locator("[data-workbench-row]:visible").first.wait_for(timeout=5000)
        _assert_no_horizontal_overflow(page)
        _assert_visible_component_contrast(
            page,
            [
                ".pqx-card",
                ".pqx-result",
                ".pqx-result-fact",
                ".pqx-result-open",
                ".pqx-progress-button",
                ".pqx-pill",
                ".pqx-event-card",
                ".pqx-source-card",
                ".pqx-route-preview-card",
                ".pqx-empty",
            ],
            minimum_ratio=3.0,
        )
        page.locator("[data-pqx-filtered-open]:visible").first.click()
        page.wait_for_function(
            """
            () => {
              const dialog = document.querySelector('[data-pqx-filtered-dialog]');
              const details = document.querySelector('details#pqx-filtered-breakdown');
              return Boolean((dialog && dialog.open) || (details && details.open));
            }
            """,
            timeout=5000,
        )
        if page.locator("[data-pqx-filtered-dialog][open]").count():
            _assert_visible_component_contrast(
                page,
                [
                    ".pqx-filtered-dialog-card",
                    ".pqx-filtered-dialog-rule",
                    ".pqx-filtered-dialog-close",
                ],
                minimum_ratio=3.0,
            )
        else:
            _assert_visible_component_contrast(page, ["details#pqx-filtered-breakdown"], minimum_ratio=3.0)
        screenshot_path = tmp_path / "propertyquarry-shortlist-dark-mode.png"
        page.screenshot(path=str(screenshot_path), full_page=False, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 20_000
    finally:
        context.close()


def test_propertyquarry_greenfield_workspace_is_mobile_usable(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-property-mobile-dock' in content
        page.locator("[data-workbench-row]:visible").first.wait_for(timeout=5000)
        assert page.locator('[data-workbench-mobile-mode="results"]').is_visible()
        assert page.locator('[data-workbench-mobile-mode="property"]').is_visible()
        mode_box = page.locator('[data-workbench-mobile-mode="results"]').bounding_box()
        assert mode_box is not None and mode_box["width"] <= 430
        mobile_dock = page.locator("[data-property-mobile-dock]")
        assert mobile_dock.is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
        page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").click()
        assert "/app/shortlist" in page.url
        assert "run_id=run-42" in page.url
        assert "candidate=" in page.url
        assert page.locator('[data-workbench-mobile-mode="property"]').is_visible()
        assert page.locator("body", has_text="Family flat near Tiergarten").is_visible()
    finally:
        context.close()


def test_propertyquarry_results_filtered_link_opens_filtered_breakdown_when_no_relax_dialog_rules(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        filtered_button = page.locator('[data-pqx-filtered-open]').first
        filtered_button.wait_for(timeout=5000)
        expect(filtered_button).to_contain_text(re.compile(r"\d+\s+filtered|relax this brief", re.I), timeout=5000)
        filtered_button.click()
        page.wait_for_function(
            """
            () => {
              const dialog = document.querySelector('[data-pqx-filtered-dialog]');
              const details = [...document.querySelectorAll('details')]
                .find((node) => ((node.textContent || '').toLowerCase().includes('why homes stayed out')));
              return Boolean((dialog && dialog.open) || (details && details.open));
            }
            """,
            timeout=5000,
        )
    finally:
        context.close()


def test_propertyquarry_search_goal_toggle_keeps_underwriting_controls_hidden_until_enabled_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="networkidle")
        assert response is not None and response.ok
        investment_mode = page.locator('[data-property-field-name="investment_research_mode"]').first
        listing_mode = page.locator('[data-property-field-name="listing_mode"]').first
        investment_strategy = page.locator('[data-property-field-name="investment_strategy"]').first
        investment_equity = page.locator('[data-property-field-name="equity_available_eur"]').first
        investment_loan_term = page.locator('[data-property-field-name="loan_term_years"]').first
        investment_rate = page.locator('[data-property-field-name="max_interest_rate_pct"]').first
        investment_dscr = page.locator('[data-property-field-name="min_dscr"]').first
        investment_vacancy = page.locator('[data-property-field-name="vacancy_reserve_pct"]').first
        investment_floorplan = page.locator('[data-property-field-name="investment_require_floorplan"]').first
        public_housing = page.locator('[data-property-field-name="include_public_housing_signals"]').first
        wohnticket = page.locator('[data-property-field-name="wiener_wohnticket_available"]').first
        distressed = page.locator('[data-property-field-name="include_distressed_sale_signals"]').first
        assert investment_mode.evaluate("(node) => node.hidden") is True
        assert investment_strategy.evaluate("(node) => node.hidden") is True
        assert investment_equity.evaluate("(node) => node.hidden") is True
        assert investment_loan_term.evaluate("(node) => node.hidden") is True
        assert investment_rate.evaluate("(node) => node.hidden") is True
        assert investment_dscr.evaluate("(node) => node.hidden") is True
        assert investment_vacancy.evaluate("(node) => node.hidden") is True
        assert investment_floorplan.evaluate("(node) => node.hidden") is True

        page.locator('select[name="search_goal"]').select_option("investment")

        page.wait_for_function(
            """
            () => {
              const mode = document.querySelector('[data-property-field-name="investment_research_mode"]');
              const listingMode = document.querySelector('[data-property-field-name="listing_mode"]');
              const strategy = document.querySelector('[data-property-field-name="investment_strategy"]');
              const equity = document.querySelector('[data-property-field-name="equity_available_eur"]');
              const loanTerm = document.querySelector('[data-property-field-name="loan_term_years"]');
              const rate = document.querySelector('[data-property-field-name="max_interest_rate_pct"]');
              const dscr = document.querySelector('[data-property-field-name="min_dscr"]');
              const vacancy = document.querySelector('[data-property-field-name="vacancy_reserve_pct"]');
              const floorplan = document.querySelector('[data-property-field-name="investment_require_floorplan"]');
              const publicHousing = document.querySelector('[data-property-field-name="include_public_housing_signals"]');
              const wohnticket = document.querySelector('[data-property-field-name="wiener_wohnticket_available"]');
              return Boolean(
                mode && listingMode && strategy && equity && loanTerm && rate && dscr && vacancy && floorplan && publicHousing && wohnticket
                && !mode.hidden
                && listingMode.hidden
                && strategy.hidden
                && equity.hidden
                && loanTerm.hidden
                && rate.hidden
                && dscr.hidden
                && vacancy.hidden
                && floorplan.hidden
                && publicHousing.hidden
                && wohnticket.hidden
              );
            }
            """
        )
        assert listing_mode.evaluate("(node) => node.hidden") is True
        assert investment_mode.evaluate("(node) => node.hidden") is False
        assert investment_strategy.evaluate("(node) => node.hidden") is True
        assert investment_equity.evaluate("(node) => node.hidden") is True
        assert investment_loan_term.evaluate("(node) => node.hidden") is True
        assert investment_rate.evaluate("(node) => node.hidden") is True
        assert investment_dscr.evaluate("(node) => node.hidden") is True
        assert investment_vacancy.evaluate("(node) => node.hidden") is True
        assert investment_floorplan.evaluate("(node) => node.hidden") is True
        assert public_housing.evaluate("(node) => node.hidden") is True
        assert wohnticket.evaluate("(node) => node.hidden") is True

        page.locator('select[name="investment_research_mode"]').select_option("auto")

        page.wait_for_function(
            """
            () => {
              const strategy = document.querySelector('[data-property-field-name="investment_strategy"]');
              const equity = document.querySelector('[data-property-field-name="equity_available_eur"]');
              const loanTerm = document.querySelector('[data-property-field-name="loan_term_years"]');
              const rate = document.querySelector('[data-property-field-name="max_interest_rate_pct"]');
              const dscr = document.querySelector('[data-property-field-name="min_dscr"]');
              const vacancy = document.querySelector('[data-property-field-name="vacancy_reserve_pct"]');
              const floorplan = document.querySelector('[data-property-field-name="investment_require_floorplan"]');
              return Boolean(strategy && equity && loanTerm && rate && dscr && vacancy && floorplan && !strategy.hidden && !equity.hidden && !loanTerm.hidden && !rate.hidden && !dscr.hidden && !vacancy.hidden && floorplan.hidden);
            }
            """
        )
        assert investment_strategy.evaluate("(node) => node.hidden") is False
        assert investment_equity.evaluate("(node) => node.hidden") is False
        assert investment_loan_term.evaluate("(node) => node.hidden") is False
        assert investment_rate.evaluate("(node) => node.hidden") is False
        assert investment_dscr.evaluate("(node) => node.hidden") is False
        assert investment_vacancy.evaluate("(node) => node.hidden") is False
        assert investment_floorplan.evaluate("(node) => node.hidden") is True

        page.locator('[data-property-step-next]').click()

        page.wait_for_function(
            """
            () => {
              const floorplan = document.querySelector('[data-property-field-name="investment_require_floorplan"]');
              return Boolean(floorplan && !floorplan.hidden);
            }
            """
        )
        assert investment_floorplan.evaluate("(node) => node.hidden") is False

        page.locator('[data-property-step-trigger="search"]').click()
        page.wait_for_function(
            """
            () => {
              const searchGoal = document.querySelector('select[name="search_goal"]');
              return Boolean(searchGoal && !searchGoal.hidden && searchGoal.offsetParent !== null);
            }
            """
        )
        page.locator('select[name="search_goal"]').select_option("home")
        page.locator('select[name="listing_mode"]').select_option("rent")

        page.wait_for_function(
            """
            () => {
              const mode = document.querySelector('[data-property-field-name="investment_research_mode"]');
              const strategy = document.querySelector('[data-property-field-name="investment_strategy"]');
              const equity = document.querySelector('[data-property-field-name="equity_available_eur"]');
              const loanTerm = document.querySelector('[data-property-field-name="loan_term_years"]');
              const rate = document.querySelector('[data-property-field-name="max_interest_rate_pct"]');
              const dscr = document.querySelector('[data-property-field-name="min_dscr"]');
              const vacancy = document.querySelector('[data-property-field-name="vacancy_reserve_pct"]');
              const floorplan = document.querySelector('[data-property-field-name="investment_require_floorplan"]');
              const distressed = document.querySelector('[data-property-field-name="include_distressed_sale_signals"]');
              const progress = document.querySelector('[data-property-step-progress]');
              const workflowStep = [...document.querySelectorAll('[data-property-step-trigger] strong')].map((node) => node.textContent || '');
                  return Boolean(
                    mode && strategy && equity && loanTerm && rate && dscr && vacancy && floorplan && distressed && progress
                    && mode.hidden
                    && strategy.hidden
                    && equity.hidden
                && loanTerm.hidden
                && rate.hidden
                && dscr.hidden
                    && vacancy.hidden
                    && floorplan.hidden
                    && distressed.hidden
                    && String(progress.textContent || '').includes('Where')
                    && workflowStep.includes('What')
                    && workflowStep.includes('What matters')
                    && workflowStep.includes('Reachability')
                    && workflowStep.includes('Research depth')
                  );
                }
                """
        )
        assert investment_mode.evaluate("(node) => node.hidden") is True
        assert investment_strategy.evaluate("(node) => node.hidden") is True
        assert investment_equity.evaluate("(node) => node.hidden") is True
        assert investment_loan_term.evaluate("(node) => node.hidden") is True
        assert investment_rate.evaluate("(node) => node.hidden") is True
        assert investment_dscr.evaluate("(node) => node.hidden") is True
        assert investment_vacancy.evaluate("(node) => node.hidden") is True
        assert investment_floorplan.evaluate("(node) => node.hidden") is True
        assert distressed.evaluate("(node) => node.hidden") is True
    finally:
        context.close()


def test_propertyquarry_workbench_tracks_household_and_followup_state_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    first = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": property_ref,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "source": "clippy_agent_brief",
            "followup_status": "asked",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-jonas",
            "stakeholder_label": "Jonas",
            "property_ref": property_ref,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Street noise still feels risky.",
            "source": "packet",
            "decision_state": "rejected",
        },
    )
    assert second.status_code == 200, second.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert packet_path
        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Current read").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            page.get_by_role("button", name="Answered").first.click()
        update_response = update_response_info.value
        assert update_response.ok, update_response.text()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        assert page.locator("body", has_text="Risk signals").is_visible()
    finally:
        context.close()


def test_propertyquarry_packet_tracks_followup_state_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    seeded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": property_ref,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "source": "clippy_agent_brief",
            "followup_status": "asked",
        },
    )
    assert seeded.status_code == 200, seeded.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert packet_path
        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            page.get_by_role("button", name="Answered").first.click()
        update_response = update_response_info.value
        assert update_response.ok, update_response.text()
        assert page.locator("body", has_text="Follow-up marked answered").is_visible()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Answered").is_visible()
    finally:
        context.close()


def test_propertyquarry_decision_to_clippy_to_packet_followup_flow_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        candidate_ref = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-ref")
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert candidate_ref
        assert packet_path

        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        with page.expect_response("**/preference-profile/property-feedback") as save_response_info:
            page.get_by_role("button", name="No", exact=True).click()
            page.locator("[data-object-feedback-save]").click()
        save_response = save_response_info.value
        assert save_response.ok, save_response.text()
        assert page.locator("body", has_text="Tracked follow-up").is_visible()

        assert page.locator("body", has_text="Tracked follow-up").is_visible()
        assert page.locator("body", has_text="Current read").is_visible()
        assert page.locator("body", has_text="Record the outcome").is_visible()
    finally:
        context.close()


def test_propertyquarry_active_run_auto_polls_notifies_and_renders_empty_result_desk(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    page.add_init_script(
        """
        (() => {
          try { Object.defineProperty(window, 'isSecureContext', { get: () => true, configurable: true }); } catch (_err) {}
          window.localStorage.setItem('propertyquarry.browserNotifications.enabled', '1');
          class FakeNotification {
            static permission = 'granted';
            static requestPermission = async () => 'granted';
            constructor(title, options) {
              window.localStorage.setItem('pq-test-notification-title', String(title || ''));
              window.localStorage.setItem('pq-test-notification-body', String((options && options.body) || ''));
              this.close = () => {};
            }
          }
          try { Object.defineProperty(window, 'Notification', { value: FakeNotification, configurable: true }); }
          catch (_err) { window.Notification = FakeNotification; }
        })();
        """
    )
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-active-empty", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "window.localStorage.getItem('propertyquarry.browserNotifications.run.run-active-empty.processed') === '1'",
            timeout=7000,
        )
        page.wait_for_selector("[data-pqx-empty-results]", timeout=7000)
        assert page.locator("[data-pqx-empty-results]", has_text=re.compile("No strong matches|No valid homes|No shortlist|current brief|search finished", re.I)).is_visible()
        assert page.locator("body", has_text="Ways to get more matches").is_visible()
        assert page.locator("[data-pqx-counterfactuals]").is_visible()
        assert page.get_by_role("button", name=re.compile("Apply|Allow|Use|Raise|Relax|Reopen")).first.is_visible()
        page.locator("[data-pqx-filtered-open]:visible").first.click()
        page.wait_for_function(
            """
            () => {
              const breakdown = document.querySelector('[data-pqx-source-breakdown]');
              const details = document.querySelector('details#pqx-filtered-breakdown');
              const dialog = document.querySelector('[data-pqx-filtered-dialog]');
              return Boolean(
                (dialog && dialog.open)
                ||
                (details && details.open)
                || (breakdown && /Genossenschaften Austria/i.test(String(breakdown.textContent || '')))
              );
            }
            """,
            timeout=5000,
        )
        assert (
            page.locator("[data-pqx-filtered-dialog][open]").is_visible()
            or page.locator("[data-pqx-source-breakdown]", has_text="Genossenschaften Austria").is_visible()
        )
        assert page.evaluate("window.localStorage.getItem('pq-test-notification-title')") == "PropertyQuarry results are ready"
        assert "0 high-fit matches" in str(page.evaluate("window.localStorage.getItem('pq-test-notification-body')"))
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_running_progress_panel_fits_the_first_viewport(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    screenshot_path = tmp_path / "property_running_progress_desktop.png"
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-active-empty", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_selector('[data-pqx-screenfit-target="run-progress"]', timeout=5000)
        assert page.locator('[data-pqx-screenfit-target="run-progress"] :is(h1, h2)').first.is_visible()
        progress_target = page.locator('[data-pqx-screenfit-target="run-progress"]').first
        assert progress_target.inner_text().strip()
        page.screenshot(path=str(screenshot_path), full_page=False)
        layout = page.evaluate(
            """
            () => {
              const target = document.querySelector('[data-pqx-screenfit-target="run-progress"]');
              const board = document.querySelector('[data-pqx-progress-board]');
              if (!target) return null;
              const targetBox = target.getBoundingClientRect();
              const boardBox = board ? board.getBoundingClientRect() : targetBox;
              return {
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth,
                targetBottom: Math.round(targetBox.bottom),
                targetRight: Math.round(targetBox.right),
                boardBottom: Math.round(boardBox.bottom),
                boardRight: Math.round(boardBox.right),
                targetFitsViewport: targetBox.bottom <= window.innerHeight + 2 && targetBox.right <= window.innerWidth + 2,
                boardFitsViewport: boardBox.bottom <= window.innerHeight + 2 && boardBox.right <= window.innerWidth + 2,
                etaLabel: (document.querySelector('[data-pqx-progress-eta]')?.textContent || '').trim(),
              };
            }
            """
        )
        assert layout is not None
        assert layout["targetFitsViewport"] is True
        assert layout["boardFitsViewport"] is True
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_setup_header_stays_minimal_and_single_row(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=False)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    screenshot_path = tmp_path / "propertyquarry-setup-header.png"
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_selector(".pqx-topbar", timeout=5000)
        page.screenshot(path=str(screenshot_path), full_page=False)
        assert page.locator("[data-property-pulse-strip]").count() == 0
        assert page.get_by_role("navigation", name="PropertyQuarry sections").get_by_text("Account", exact=True).count() == 1
        assert page.locator(".pqx-account-menu > summary").count() == 1
        assert page.locator(".pqx-account-menu > summary").inner_text().strip() != "Account"
        _assert_property_shell_visual_gates(page, max_appbar_height=84)
    finally:
        context.close()


def test_propertyquarry_workspace_sign_out_works_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=False)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        account_summary = page.locator(".pqx-account-menu > summary")
        expect(account_summary).to_be_visible()

        account_summary.click()
        logout_button = page.locator(".pqx-account-menu-form button", has_text="Log out")
        expect(logout_button).to_be_visible()

        logout_button.click()
        page.wait_for_load_state("domcontentloaded")
        assert page.url.startswith(f"{base_url}") or page.url.startswith("http://propertyquarry.com:")
        assert page.url != f"{base_url}/app/shortlist?run_id=run-42"

        # Signed-out pages should no longer expose the account menu.
        page.wait_for_timeout(100)
        assert page.locator(".pqx-account-menu > summary").count() == 0
    finally:
        context.close()


def test_propertyquarry_what_matters_section_renders_as_comboboxes_in_live_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    desktop = _new_context(browser, mobile=False, width=1440, height=1400)
    mobile = _new_context(browser, mobile=True)
    desktop_shot = tmp_path / "propertyquarry-what-matters-desktop.png"
    mobile_shot = tmp_path / "propertyquarry-what-matters-mobile.png"
    try:
        desktop_page = desktop.new_page()
        console_errors: list[str] = []
        desktop_page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        response = desktop_page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        desktop_page.locator('[data-property-step-trigger="children"]').click()
        section = desktop_page.locator('[data-property-what-matters-panel]')
        section.wait_for(state="visible")
        assert section.locator("select").count() >= 8
        assert section.locator('input[type="checkbox"]').count() == 0
        assert " nearby" not in section.inner_text().lower()
        expect(desktop_page.locator('[data-property-field-name="use_stored_feedback_preferences"]')).to_have_count(0)
        expect(desktop_page.locator('[data-property-field-name="preference_person_id"]')).to_have_count(0)
        for field_name in (
            "require_school_evidence",
            "school_stage_preferences",
            "max_distance_to_hardware_store_m",
            "max_distance_to_shopping_center_m",
            "avoid_noise_risk_area",
            "require_high_speed_internet",
        ):
            expect(desktop_page.locator(f'[data-property-field-name="{field_name}"]')).to_be_hidden()
        baugrund_row = section.locator('[data-keyword-priority-row][data-keyword-value="baugrund"]')
        expect(baugrund_row).to_be_hidden()
        desktop_page.locator('[data-property-step-trigger="what"]').click()
        desktop_page.locator('input[name="property_type"][value="land"]').check()
        desktop_page.locator('[data-property-step-trigger="children"]').click()
        expect(baugrund_row).to_be_visible()
        distance_row = section.locator('[data-keyword-priority-row]:has([data-keyword-distance-select])').first
        distance_preference = distance_row.locator('[data-keyword-preference-select]')
        distance_select = distance_row.locator('[data-keyword-distance-select]')
        distance_preference.select_option("nice_to_have")
        expect(distance_select).to_be_enabled()
        assert distance_row.evaluate("node => node.dataset.keywordDistanceEnabled") == "true"
        assert distance_row.evaluate("node => node.closest('[data-what-matters-group]')?.dataset.activeDistanceRows") == "true"
        preference_box = distance_preference.bounding_box()
        distance_box = distance_select.bounding_box()
        assert preference_box and preference_box["width"] >= 128
        assert distance_box and distance_box["width"] >= 108
        school_parent = section.locator('[data-school-priority-row][data-school-value="volksschule"] [data-school-preference-select]')
        school_detail = section.locator('[data-school-priority-row][data-school-parent-value="volksschule"]').first
        expect(school_detail).to_be_hidden()
        school_parent.select_option("nice_to_have")
        expect(school_detail).to_be_visible()
        assert school_parent.evaluate("node => node.closest('[data-school-priority-row]')?.dataset.schoolFamilyActive") == "true"
        assert school_detail.evaluate("node => node.dataset.schoolParentActive") == "true"
        actionable_console_errors = [
            message for message in console_errors
            if "Cross-Origin-Opener-Policy header has been ignored" not in message
        ]
        assert actionable_console_errors == []
        section.screenshot(path=str(desktop_shot))
        assert desktop_shot.exists()

        mobile_page = mobile.new_page()
        response = mobile_page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        mobile_page.locator('[data-property-step-trigger="children"]').click()
        mobile_section = mobile_page.locator('[data-property-what-matters-panel]')
        mobile_section.wait_for(state="visible")
        assert mobile_section.locator("select").count() >= 8
        assert mobile_section.locator('input[type="checkbox"]').count() == 0
        assert " nearby" not in mobile_section.inner_text().lower()
        mobile_metrics = mobile_section.evaluate(
            """
            (panel) => {
              const visibleRows = Array.from(
                panel.querySelectorAll(
                  '[data-keyword-priority-row], [data-school-priority-row], .pqx-what-matters-head, .pqx-what-matters-group-summary'
                )
              ).filter((node) => node.offsetParent !== null);
              const panelRect = panel.getBoundingClientRect();
              const lastBottom = visibleRows.reduce((bottom, node) => {
                const rect = node.getBoundingClientRect();
                return Math.max(bottom, rect.bottom);
              }, panelRect.top);
              const rowWidths = visibleRows.map((node) => {
                const rect = node.getBoundingClientRect();
                return {
                  width: rect.width,
                  scrollWidth: node.scrollWidth,
                };
              });
              return {
                panelHeight: panelRect.height,
                panelWidth: panelRect.width,
                panelScrollWidth: panel.scrollWidth,
                bottomGap: panelRect.bottom - lastBottom,
                rowWidths,
              };
            }
            """
        )
        assert float(mobile_metrics["panelHeight"]) <= 2300.0, mobile_metrics
        assert float(mobile_metrics["panelScrollWidth"]) <= float(mobile_metrics["panelWidth"]) + 1.0, mobile_metrics
        assert float(mobile_metrics["bottomGap"]) <= 28.0, mobile_metrics
        for row_metric in mobile_metrics["rowWidths"]:
            assert float(row_metric["scrollWidth"]) <= float(row_metric["width"]) + 1.0, row_metric
        mobile_section.scroll_into_view_if_needed()
        mobile_page.screenshot(path=str(mobile_shot))
        assert mobile_shot.exists()
    finally:
        desktop.close()
        mobile.close()


def test_propertyquarry_search_wizard_steps_replace_visible_controls_without_accumulating(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1360, height=1000)
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator('[data-console-form-variant="property_search"]').wait_for(state="visible")
        expect(page.locator('[data-property-start-top]')).to_be_visible()
        expect(page.locator('[data-property-step-nav]')).to_be_visible()
        expected_fields = {
            "search": "country_code",
            "what": "property_type",
            "children": "keywords",
            "reachability": "enable_commute_research",
            "research": None,
            "providers": "selected_platforms",
        }
        for step, field_name in expected_fields.items():
            page.locator(f'[data-property-step-trigger="{step}"]').click()
            page.wait_for_function(
                """(step) => document.querySelector('[data-console-form-variant="property_search"]')?.dataset.propertyActiveStep === step""",
                arg=step,
            )
            visible_steps = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('.pqx-field[data-property-field-step]'))
                  .filter((node) => node.offsetParent !== null && !node.hidden)
                  .map((node) => node.getAttribute('data-property-field-step'))
                  .filter(Boolean)
                """
            )
            assert visible_steps, step
            assert set(visible_steps) == {step}, {"clicked": step, "visible_steps": visible_steps}
            if field_name:
                expect(page.locator(f'[data-property-field-name="{field_name}"]')).to_be_visible()
            assert page.locator(".pqx-workflow-step.active").count() == 1
            nav_box = page.locator('[data-property-step-nav]').bounding_box()
            assert nav_box is not None
            assert nav_box["y"] >= 0
            assert nav_box["y"] < 220
        page.locator('[data-property-step-trigger="search"]').click()
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.locator('[data-property-step-next]').click()
        page.wait_for_function(
            """() => document.querySelector('[data-console-form-variant="property_search"]')?.dataset.propertyActiveStep === 'what'"""
        )
        nav_box = page.locator('[data-property-step-nav]').bounding_box()
        assert nav_box is not None
        assert nav_box["y"] >= 0
        assert nav_box["y"] < 220
    finally:
        context.close()


def test_propertyquarry_search_wizard_step_navigation_is_keyboard_operable(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1360, height=1000)
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator('[data-console-form-variant="property_search"]').wait_for(state="visible")

        reached_step = ""
        for _ in range(50):
            page.keyboard.press("Tab")
            reached_step = str(
                page.evaluate(
                    "() => document.activeElement?.getAttribute('data-property-step-trigger') || ''"
                )
            )
            if reached_step == "what":
                break
        assert reached_step == "what"

        focused_button = page.locator('[data-property-step-trigger="what"]')
        focus_style = focused_button.evaluate(
            """
            (node) => {
              const style = window.getComputedStyle(node);
              return {
                outlineStyle: style.outlineStyle,
                outlineWidth: style.outlineWidth,
                boxShadow: style.boxShadow,
              };
            }
            """
        )
        assert focus_style["outlineStyle"] != "none" or focus_style["boxShadow"] != "none"

        page.keyboard.press("Enter")
        page.wait_for_function(
            """() => document.querySelector('[data-console-form-variant="property_search"]')?.dataset.propertyActiveStep === 'what'"""
        )
        expect(page.locator('[data-property-step-trigger="what"]')).to_have_attribute("aria-current", "step")
        expect(page.locator('[data-property-step-trigger="search"]')).not_to_have_attribute("aria-current", "step")
        expect(page.locator('[data-property-field-name="property_type"]')).to_be_visible()

        page.locator('[data-property-step-next]').focus()
        page.keyboard.press("Space")
        page.wait_for_function(
            """() => document.querySelector('[data-console-form-variant="property_search"]')?.dataset.propertyActiveStep === 'children'"""
        )
        expect(page.locator('[data-property-step-trigger="children"]')).to_have_attribute("aria-current", "step")
        expect(page.locator('[data-property-field-name="keywords"]')).to_be_visible()
    finally:
        context.close()


def test_propertyquarry_what_matters_distance_comboboxes_expand_without_clipping(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    desktop = _new_context(browser, mobile=False, width=1120, height=1200)
    mobile = _new_context(browser, mobile=True, width=430, height=1200)
    desktop_shot = tmp_path / "propertyquarry-what-matters-distance-desktop.png"
    mobile_shot = tmp_path / "propertyquarry-what-matters-distance-mobile.png"

    def _assert_distance_rows_fit(page: Page, screenshot_path: Path) -> None:
        response = page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator('[data-property-step-trigger="children"]').click()
        page.wait_for_function(
            "document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'children'"
        )
        for field_name in (
            "max_distance_to_market_m",
            "max_distance_to_hardware_store_m",
            "max_distance_to_shopping_center_m",
            "max_distance_to_theatre_m",
            "avoid_flood_risk_area",
        ):
            expect(page.locator(f'[data-property-field-name="{field_name}"]')).to_be_hidden()
        for keyword in ("Baumarkt nearby", "shopping center nearby", "flaniermeile nearby", "theatre nearby"):
            row = page.locator(f'[data-keyword-priority-row][data-keyword-value="{keyword}"]')
            row.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
            row.locator("[data-keyword-preference-select]").select_option("important")
            expect(row.locator("[data-keyword-distance-select]")).to_be_enabled()
            expect(row).to_have_attribute("data-preference-state", "important")
        school_parent = page.locator('[data-school-priority-row][data-school-value="volksschule"]')
        school_parent.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
        school_parent.locator("[data-school-preference-select]").select_option("important")
        expect(school_parent).to_have_attribute("data-preference-state", "important")
        school_child = page.locator('[data-school-priority-row][data-school-value="ganztags_volksschule"]')
        expect(school_child).to_be_visible()
        expect(school_child).to_have_attribute("data-school-parent-active", "true")
        expect(school_parent).to_have_attribute("data-school-family-active", "true")
        section = page.locator('[data-what-matters-group="daily_life"]')
        expect(section).to_have_attribute("data-active-distance-rows", "true")
        section.scroll_into_view_if_needed()
        section.screenshot(path=str(screenshot_path))
        assert screenshot_path.exists()
        group_overflow = page.evaluate(
            """
            () => {
              const group = document.querySelector('[data-what-matters-group="daily_life"]');
              const list = group?.querySelector('.pqx-pref-list');
              const groupRect = group?.getBoundingClientRect();
              const listRect = list?.getBoundingClientRect();
              return {
                groupWidth: groupRect ? groupRect.width : 0,
                groupScrollWidth: group ? group.scrollWidth : 0,
                listWidth: listRect ? listRect.width : 0,
                listScrollWidth: list ? list.scrollWidth : 0,
              };
            }
            """
        )
        assert float(group_overflow["groupScrollWidth"]) <= float(group_overflow["groupWidth"]) + 1.0, group_overflow
        assert float(group_overflow["listScrollWidth"]) <= float(group_overflow["listWidth"]) + 1.0, group_overflow
        rows = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('[data-keyword-priority-row][data-keyword-distance-enabled="true"]'))
              .filter((row) => row.offsetParent !== null)
              .map((row) => {
                const rowRect = row.getBoundingClientRect();
                return {
                  value: row.getAttribute('data-keyword-value') || '',
                  rowWidth: rowRect.width,
                  rowScrollWidth: row.scrollWidth,
                  controls: Array.from(row.querySelectorAll('select')).map((select) => {
                    const rect = select.getBoundingClientRect();
                    return {
                      name: select.getAttribute('name') || '',
                      width: rect.width,
                      left: rect.left - rowRect.left,
                      right: rowRect.right - rect.right,
                    };
                  }),
                };
              })
            """
        )
        assert len(rows) >= 4
        inner_width = int(page.evaluate("window.innerWidth"))
        group_width = float(section.bounding_box()["width"] or 0)
        if inner_width >= 900:
            assert group_width >= 680.0
        for row in rows:
            assert float(row["rowScrollWidth"]) <= float(row["rowWidth"]) + 1.0, row
            if inner_width >= 900:
                assert float(row["rowWidth"]) >= 320.0, row
            for control in row["controls"]:
                assert float(control["width"]) >= 104.0, row
                assert float(control["left"]) >= -1.0, row
                assert float(control["right"]) >= -1.0, row

    try:
        _assert_distance_rows_fit(desktop.new_page(), desktop_shot)
        _assert_distance_rows_fit(mobile.new_page(), mobile_shot)
    finally:
        desktop.close()
        mobile.close()


def test_propertyquarry_search_where_step_keeps_area_selection_visible(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=1200)
    screenshot_path = tmp_path / "propertyquarry-where-step-areas.png"
    try:
        page = context.new_page()
        response = page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
        assert response is not None and response.ok
        location_field = page.locator('[data-property-field-name="location_query"]')
        location_field.wait_for(state="visible")
        assert location_field.locator('input[name="location_query"]').count() >= 1
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        location_field.screenshot(path=str(screenshot_path))
        assert screenshot_path.exists()
    finally:
        context.close()


def test_propertyquarry_running_progress_panel_fits_the_first_mobile_viewport(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-active-empty", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_selector('[data-pqx-screenfit-target="run-progress"]', timeout=5000)
        assert page.locator('[data-pqx-screenfit-target="run-progress"] :is(h1, h2)').first.is_visible()
        progress_target = page.locator('[data-pqx-screenfit-target="run-progress"]').first
        assert progress_target.inner_text().strip()
        layout = page.evaluate(
            """
            () => {
              const target = document.querySelector('[data-pqx-screenfit-target="run-progress"]');
              const board = document.querySelector('[data-pqx-progress-board]');
              if (!target) return null;
              const targetBox = target.getBoundingClientRect();
              const boardBox = board ? board.getBoundingClientRect() : targetBox;
              return {
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth,
                targetBottom: Math.round(targetBox.bottom),
                targetRight: Math.round(targetBox.right),
                boardBottom: Math.round(boardBox.bottom),
                boardRight: Math.round(boardBox.right),
                targetFitsViewport: targetBox.bottom <= window.innerHeight + 2 && targetBox.right <= window.innerWidth + 2,
                boardFitsViewport: boardBox.bottom <= window.innerHeight + 2 && boardBox.right <= window.innerWidth + 2,
                etaLabel: (document.querySelector('[data-pqx-progress-eta]')?.textContent || '').trim(),
              };
            }
            """
        )
        assert layout is not None
        assert layout["targetBottom"] <= layout["viewportHeight"] + 112
        assert layout["boardBottom"] <= layout["viewportHeight"] + 112
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
    finally:
        context.close()


def test_propertyquarry_shortlist_and_research_surfaces_do_not_bleed_text(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=900)
    page: Page = context.new_page()
    screenshot_path = tmp_path / "property_research_detail_first_screen.png"
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text=re.compile(r"ranked homes", re.I)).is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        packet_href = page.locator('a[href*="/app/research/"]').first.get_attribute("href")
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator(".prd-media-frame").is_visible()
        assert "Open the space before you read the rest" not in page.content()
        _assert_research_packet_360_first(page, min_stage_height=220, max_stage_height=380)
        body_box = page.locator(".prd-body").first.bounding_box()
        assert body_box is not None
        viewport_height = page.viewport_size["height"] if page.viewport_size else 900
        assert body_box["y"] < viewport_height
        first_screen = page.evaluate(
            """
            () => {
              const hero = document.querySelector('[data-pqx-screenfit-target="research-detail-hero"]');
              const body = document.querySelector('.prd-body');
              const media = document.querySelector('.prd-media-frame');
              const actions = document.querySelector('.prd-actions');
              const gallery = document.querySelector('.prd-hero-gallery');
              const heroRect = hero ? hero.getBoundingClientRect() : null;
              const bodyRect = body ? body.getBoundingClientRect() : null;
              const mediaRect = media ? media.getBoundingClientRect() : null;
              const actionsRect = actions ? actions.getBoundingClientRect() : null;
              const galleryRect = gallery ? gallery.getBoundingClientRect() : null;
              return {
                viewportHeight: window.innerHeight,
                heroBottom: heroRect ? Math.round(heroRect.bottom) : 0,
                bodyTop: bodyRect ? Math.round(bodyRect.top) : 0,
                mediaHeight: mediaRect ? Math.round(mediaRect.height) : 0,
                actionsBottom: actionsRect ? Math.round(actionsRect.bottom) : 0,
                galleryBottom: galleryRect ? Math.round(galleryRect.bottom) : 0,
              };
            }
            """
        )
        assert first_screen["heroBottom"] <= first_screen["viewportHeight"] + 1
        assert first_screen["bodyTop"] <= first_screen["viewportHeight"] - 32
        assert first_screen["mediaHeight"] <= 380
        assert first_screen["actionsBottom"] <= first_screen["viewportHeight"] + 1
        if first_screen["galleryBottom"]:
            assert first_screen["galleryBottom"] <= first_screen["viewportHeight"] + 1
        page.screenshot(path=str(screenshot_path), full_page=False, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 20_000
        assert page.get_by_text("At a glance").first.is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_research_detail_is_mobile_optimized_and_visuals_are_opt_in(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    page: Page = context.new_page()
    visual_requests: list[dict[str, object]] = []

    def _capture_visual_request(route) -> None:
        request = route.request
        payload = request.post_data_json
        visual_requests.append(payload if isinstance(payload, dict) else {})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "generated_at": "2026-06-21T10:00:00+00:00",
                    "status": "created",
                    "property_url": visual_requests[-1].get("property_url", ""),
                    "title": "Listing URL only loft",
                    "request_kind": visual_requests[-1].get("request_kind", "flythrough"),
                    "tour_url": "",
                    "flythrough_url": "",
                    "flythrough_status": "pending",
                    "status_label": "Walkthrough queued",
                    "status_detail": "Walkthrough is queued after your request.",
                    "delivery_status": "skipped",
                    "blocked_reason": "",
                    "source_ref": visual_requests[-1].get("source_ref", ""),
                    "run_id": visual_requests[-1].get("run_id", ""),
                    "candidate_ref": visual_requests[-1].get("candidate_ref", ""),
                }
            ),
        )

    page.route("**/app/api/signals/willhaben/property-tour", _capture_visual_request)
    screenshot_path = tmp_path / "property-research-detail-mobile.png"
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        row = page.locator("[data-workbench-row]", has_text="Listing URL only loft").first
        row.wait_for(timeout=5000)
        packet_href = str(row.get_attribute("data-candidate-packet-url") or "").strip()
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"

        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.locator("[data-property-research-detail]")).to_be_visible()
        expect(page.locator(".prd-media-frame")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("Request walkthrough", re.I))).to_be_visible()
        assert visual_requests == []
        _assert_no_horizontal_overflow(page)
        layout = page.evaluate(
            """
            () => {
              const hero = document.querySelector('[data-pqx-screenfit-target="research-detail-hero"]');
              const body = document.querySelector('.prd-body');
              const media = document.querySelector('.prd-media-frame');
              const actions = document.querySelector('.prd-actions');
              const meta = document.querySelector('.prd-summary-stack .prd-meta');
              const metaCards = Array.from(document.querySelectorAll('.prd-summary-stack .prd-meta-card'));
              const shell = document.querySelector('[data-property-research-detail]');
              const heroRect = hero ? hero.getBoundingClientRect() : null;
              const bodyRect = body ? body.getBoundingClientRect() : null;
              const mediaRect = media ? media.getBoundingClientRect() : null;
              const actionsStyle = actions ? getComputedStyle(actions) : null;
              const metaStyle = meta ? getComputedStyle(meta) : null;
              const shellRect = shell ? shell.getBoundingClientRect() : null;
              return {
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                shellWidth: shellRect ? shellRect.width : 0,
                heroWidth: heroRect ? heroRect.width : 0,
                heroBottom: heroRect ? Math.round(heroRect.bottom) : 0,
                bodyTop: bodyRect ? Math.round(bodyRect.top) : 0,
                mediaHeight: mediaRect ? Math.round(mediaRect.height) : 0,
                actionsDisplay: actionsStyle ? actionsStyle.display : '',
                actionsColumns: actionsStyle ? actionsStyle.gridTemplateColumns : '',
                metaColumns: metaStyle ? metaStyle.gridTemplateColumns.split(' ').length : 0,
                metaCardCount: metaCards.length,
                metaTallestCard: Math.max(0, ...metaCards.map((card) => Math.round(card.getBoundingClientRect().height))),
              };
            }
            """
        )
        assert layout["shellWidth"] <= layout["viewportWidth"] + 1
        assert layout["heroWidth"] <= layout["viewportWidth"] + 1
        assert layout["heroBottom"] > 0
        assert layout["bodyTop"] > layout["heroBottom"]
        assert 220 <= layout["mediaHeight"] <= 360
        assert layout["actionsDisplay"] == "grid"
        assert "px" in layout["actionsColumns"]
        assert layout["metaColumns"] == 2
        assert layout["metaCardCount"] >= 4
        assert layout["metaTallestCard"] <= 76
        page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 20_000

        request_button = page.get_by_role("button", name=re.compile("Request walkthrough", re.I)).first
        request_button.click()
        page.wait_for_timeout(500)
        assert len(visual_requests) == 1
        payload = visual_requests[0]
        assert payload["request_kind"] == "flythrough"
        assert payload["auto_deliver"] is False
        assert payload["allow_floorplan_only"] is True
        assert payload["run_id"] == "run-42"
        assert str(payload["property_url"]).endswith("/listing-url-only-loft")
        expect(page.locator("[data-prd-visual-status]")).to_contain_text("queued after your request")
    finally:
        context.close()


def test_propertyquarry_setup_wizard_changes_visible_controls_and_collapses_all_vienna(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        page.set_default_timeout(10000)
        response = page.goto(f"{base_url}/app/properties", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator('[data-console-form-variant="property_search"]').wait_for(state="visible")
        page.locator('[data-property-field-name="country_code"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="country_code"]').is_visible()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()

        page.select_option('select[name="country_code"]', "AT")
        assert page.locator('[data-property-field-name="region_code"]').is_visible()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()

        page.get_by_role("button", name="Select all areas", exact=True).click()
        total_areas = page.locator('input[name="location_query"]').count()
        assert total_areas > 0
        assert page.locator('input[name="location_query"]:checked').count() == total_areas
        assert page.locator('input[name="full_region_scope"]').is_checked()

        page.get_by_role("button", name="Deselect all areas", exact=True).click()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()
        assert page.locator('input[name="location_query"]:checked').count() == 0
        assert page.locator('input[name="full_region_scope"]').is_checked() is False

        page.locator("[data-property-step-next]").click()
        assert page.locator('[data-property-field-name="country_code"]').is_hidden()
        assert page.locator('[data-property-field-name="region_code"]').is_hidden()
        assert page.locator('[data-property-field-name="location_query"]').is_hidden()
        assert page.locator('[data-property-field-name="property_type"]').is_visible()

        page.locator('[data-property-step-trigger="children"]').click()
        assert page.locator('[data-property-field-name="school_stage_preferences"]').count() >= 1
        assert page.locator('[data-property-what-matters-panel]').is_visible()
        assert page.locator('details[data-property-advanced-panel="children"]').count() == 0
        assert page.locator('details[data-property-advanced-panel="children_distances"]').count() == 0

        page.locator('[data-property-step-trigger="search"]').click()
        page.select_option('select[name="region_code"]', "lower_austria")
        page.locator('[data-property-step-trigger="children"]').click()

        page.locator('[data-property-step-trigger="reachability"]').click()
        page.locator('input[name="enable_commute_research"]').wait_for(state="visible")
        assert page.locator('input[name="enable_commute_research"]').is_visible()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_hidden()
        page.locator('input[name="enable_commute_research"]').check()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_visible()
        page.locator('details[data-property-advanced-panel="commute"] summary').click()
        assert page.locator('[data-property-field-name="commute_destination"]').is_visible()
        assert page.locator('[data-property-field-name="preferred_reachability_modes"]').is_visible()
        page.locator('input[name="enable_commute_research"]').uncheck()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_hidden()

        page.locator('[data-property-step-trigger="children"]').click()
        assert page.locator('[data-property-what-matters-panel]').is_visible()
        assert page.locator('[data-keyword-priority-row][data-keyword-value="market nearby"]').is_visible()
        assert page.locator('[data-keyword-priority-row][data-keyword-value="good air quality"]').is_visible()
        assert page.locator('[data-keyword-priority-row][data-keyword-value="avoid flood-risk area"]').is_visible()

        page.locator('[data-property-step-trigger="providers"]').click()
        page.locator('input[name="min_match_score"]').wait_for(state="visible")
        assert page.locator('label', has_text="Willhaben").count() >= 1
        assert page.locator('label', has_text="ImmoScout24 Austria").count() >= 1
        assert page.locator('label', has_text="Zillow").count() == 0
        match_slider = page.locator('input[name="min_match_score"]')
        assert match_slider.is_visible()
        assert match_slider.get_attribute("max") == "80"
        assert match_slider.get_attribute("data-range-selectable-max") == "45"
        assert match_slider.get_attribute("data-range-visual-max") == "80"
        tooltip = match_slider.get_attribute("title") or ""
        assert "backend" in tooltip.lower()
        assert "slower" in tooltip.lower()
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "45/80"
        assert page.locator('[data-current-plan-cap]').filter(has_text="Plan cap 45").count() >= 1
        floorplan_filter = page.locator('input[name="require_floorplan"]')
        assert floorplan_filter.is_visible()
        assert page.locator('label', has_text="Serious listings only").count() >= 1
        match_slider.evaluate("(node) => { node.value = '80'; node.dispatchEvent(new Event('input', { bubbles: true })); }")
        assert match_slider.input_value() == "45"
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "45/80"
    finally:
        context.close()


def test_propertyquarry_search_setup_fits_desktop_viewport_and_captures_screenshots(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    desktop = _new_context(browser, mobile=False, width=1600, height=1200)
    mobile = _new_context(browser, mobile=True)
    desktop_shot = tmp_path / "property_search_setup_desktop.png"
    mobile_shot = tmp_path / "property_search_setup_mobile.png"
    try:
        desktop_page = desktop.new_page()
        response = desktop_page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        desktop_page.locator("[data-workbench-brief-drawer]").wait_for(state="visible")
        desktop_page.screenshot(path=str(desktop_shot), full_page=True)
        metrics = desktop_page.evaluate(
            """() => {
                const drawer = document.querySelector('[data-workbench-brief-drawer]');
                const workflow = document.querySelector('.pqx-workflow');
                const propertyType = document.querySelector('[data-property-field-name="property_type"]');
                const drawerRect = drawer ? drawer.getBoundingClientRect() : null;
                const workflowRect = workflow ? workflow.getBoundingClientRect() : null;
                const propertyTypeRect = propertyType ? propertyType.getBoundingClientRect() : null;
                return {
                    innerHeight: window.innerHeight,
                    scrollHeight: document.scrollingElement ? document.scrollingElement.scrollHeight : 0,
                    drawerBottom: drawerRect ? drawerRect.bottom : 0,
                    workflowHeight: workflowRect ? workflowRect.height : 0,
                    propertyTypeHeight: propertyTypeRect ? propertyTypeRect.height : 0,
                    propertyTypeBottom: propertyTypeRect ? propertyTypeRect.bottom : 0,
                };
            }"""
        )
        assert metrics["drawerBottom"] <= metrics["innerHeight"] + 1
        assert metrics["scrollHeight"] <= metrics["innerHeight"] + 1
        assert metrics["workflowHeight"] <= 84
        assert metrics["propertyTypeHeight"] <= 170
        assert metrics["propertyTypeBottom"] <= metrics["innerHeight"] + 1
        assert desktop_shot.exists()

        mobile_page = mobile.new_page()
        response = mobile_page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        mobile_page.locator("[data-workbench-brief-drawer]").wait_for(state="visible")
        mobile_page.screenshot(path=str(mobile_shot), full_page=True)
        assert mobile_shot.exists()
        mobile_metrics = mobile_page.evaluate(
            """() => {
                const rail = document.querySelector('[data-property-mobile-step-rail]');
                const dock = document.querySelector('[data-property-mobile-action-dock]');
                const result = document.querySelector('[data-workbench-row]');
                const thumb = result?.querySelector('.pqx-thumb');
                const areaRows = Array.from(document.querySelectorAll('[data-pqx-check-grid="location_query"] .pqx-check'));
                const railStyle = rail ? window.getComputedStyle(rail) : null;
                const dockStyle = dock ? window.getComputedStyle(dock) : null;
                const dockRect = dock ? dock.getBoundingClientRect() : null;
                const resultRect = result ? result.getBoundingClientRect() : null;
                const thumbRect = thumb ? thumb.getBoundingClientRect() : null;
                const areaRects = areaRows.map((node) => node.getBoundingClientRect());
                const areaStyle = areaRows[0] ? window.getComputedStyle(areaRows[0]) : null;
                return {
                    bodyWidth: document.documentElement.scrollWidth,
                    viewportWidth: window.innerWidth,
                    railOverflowX: railStyle ? railStyle.overflowX : '',
                    railScrollWidth: rail ? rail.scrollWidth : 0,
                    railClientWidth: rail ? rail.clientWidth : 0,
                    railPosition: railStyle ? railStyle.position : '',
                    dockPosition: dockStyle ? dockStyle.position : '',
                    dockBottom: dockStyle ? dockStyle.bottom : '',
                    dockVisible: Boolean(dock && dock.offsetParent !== null),
                    resultWidth: resultRect ? resultRect.width : 0,
                    thumbWidth: thumbRect ? thumbRect.width : 0,
                    areaRowCount: areaRows.length,
                    areaRowMinHeight: areaRects.length ? Math.min(...areaRects.map((rect) => rect.height)) : 0,
                    areaRowsClearOfDock: dockRect ? areaRects.filter((rect) => rect.top >= 0 && rect.bottom <= dockRect.top - 4).length : 0,
                    areaRowMaxRight: areaRects.length ? Math.max(...areaRects.map((rect) => rect.right)) : 0,
                    areaRowGridColumns: areaStyle ? areaStyle.gridTemplateColumns : '',
                    areaRowBorderRadius: areaStyle ? areaStyle.borderRadius : '',
                };
            }"""
        )
        assert mobile_metrics["bodyWidth"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["railOverflowX"] in {"auto", "scroll"}
        assert mobile_metrics["railScrollWidth"] >= mobile_metrics["railClientWidth"]
        assert mobile_metrics["railPosition"] == "sticky"
        assert mobile_metrics["dockVisible"] is True
        assert mobile_metrics["dockPosition"] == "sticky"
        assert "env(safe-area-inset-bottom" in mobile_metrics["dockBottom"] or mobile_metrics["dockBottom"] != "auto"
        assert mobile_metrics["resultWidth"] <= mobile_metrics["viewportWidth"] + 1
        if mobile_metrics["thumbWidth"]:
            assert 96 <= mobile_metrics["thumbWidth"] <= 120
        assert mobile_metrics["areaRowCount"] >= 6
        assert 44 <= mobile_metrics["areaRowMinHeight"] <= 50
        assert mobile_metrics["areaRowsClearOfDock"] >= 8
        assert mobile_metrics["areaRowMaxRight"] <= mobile_metrics["viewportWidth"] + 1
        assert "24px" in mobile_metrics["areaRowGridColumns"]
        assert mobile_metrics["areaRowBorderRadius"] != "0px"
        _assert_no_horizontal_overflow(mobile_page)
    finally:
        desktop.close()
        mobile.close()


def test_propertyquarry_automation_page_uses_compact_card_cockpit(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    client = propertyquarry_browser_server["client"]
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "selected_platforms": ["willhaben", "derstandard_at"],
            "active_search_agent_id": "watch-1020",
            "search_agents": [
                {
                    "agent_id": "watch-1020",
                    "name": "Leopoldstadt rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "duration_days": 90,
                    "notification_limit": 3,
                    "notification_period": "day",
                    "last_run_at": "2026-06-18T08:00:00+02:00",
                    "next_run_at": "2026-06-19T08:00:00+02:00",
                    "sent_in_current_window": 1,
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben", "derstandard_at"],
                    },
                },
                {
                    "agent_id": "watch-1130",
                    "name": "Hietzing buy watch",
                    "enabled": False,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1130 Vienna",
                    "listing_mode": "buy",
                    "property_type": "apartment",
                    "duration_days": 180,
                    "notification_limit": 5,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1130 Vienna",
                        "listing_mode": "buy",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben"],
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, width=1440, height=900)
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/agents", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.locator("[data-property-search-agent-grid]")).to_be_visible()
        screenshot_path = tmp_path / "automation-premium-cockpit.png"
        page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 20_000

        layout = page.evaluate(
            """
            () => {
              const cards = [...document.querySelectorAll('.pqx-automation-card')];
              const board = document.querySelector('[data-property-search-agent-management]');
              const grid = document.querySelector('[data-property-search-agent-grid]');
              const cardBoxes = cards.map((card) => card.getBoundingClientRect());
              return {
                cardCount: cards.length,
                thumbnailCount: document.querySelectorAll('.pqx-automation-thumbnail').length,
                overlayThumbCount: document.querySelectorAll('.pqx-automation-thumbnail[data-scope-overlay="true"]').length,
                osmThumbCount: document.querySelectorAll('.pqx-automation-thumbnail[data-scope-preview-kind="osm_district_overlay"]').length,
                previewUrlCount: [...document.querySelectorAll('.pqx-automation-thumbnail img')]
                  .filter((img) => {
                    const src = String(img.getAttribute('src') || '');
                    return src.startsWith('/app/api/property/map-previews/') && src.endsWith('.png');
                  }).length,
                deleteCount: document.querySelectorAll('.pqx-automation-delete[data-search-agent-action="delete"]').length,
                formCount: document.querySelectorAll('form.pqx-form').length,
                tableCount: document.querySelectorAll('.pqx-automation-table').length,
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                boardBottom: board?.getBoundingClientRect().bottom || 0,
                gridBottom: grid?.getBoundingClientRect().bottom || 0,
                viewportHeight: window.innerHeight,
                maxCardHeight: Math.max(...cardBoxes.map((box) => box.height)),
                maxCardRight: Math.max(...cardBoxes.map((box) => box.right)),
              };
            }
            """
        )
        assert layout["cardCount"] == 2
        assert layout["thumbnailCount"] == 2
        assert layout["overlayThumbCount"] == 2
        assert layout["osmThumbCount"] == 2
        assert layout["previewUrlCount"] == 2
        assert layout["deleteCount"] == 2
        assert layout["formCount"] == 0
        assert layout["tableCount"] == 0
        assert layout["horizontalOverflow"] is False
        assert layout["gridBottom"] <= layout["viewportHeight"]
        assert layout["boardBottom"] <= layout["viewportHeight"]
        assert layout["maxCardHeight"] <= 210
        assert layout["maxCardRight"] <= 1440

        with page.expect_navigation(wait_until="domcontentloaded"):
            page.locator(".pqx-automation-thumbnail").first.click()
        assert "/app/search" in page.url
        assert "load_agent=watch-1020" in page.url
    finally:
        context.close()


def test_propertyquarry_secondary_surfaces_have_phone_specific_layout(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    client = propertyquarry_browser_server["client"]
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "selected_platforms": ["willhaben", "derstandard_at"],
            "search_agents": [
                {
                    "agent_id": "watch-1020-mobile",
                    "name": "Leopoldstadt mobile watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "duration_days": 90,
                    "notification_limit": 3,
                    "notification_period": "day",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben", "derstandard_at"],
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    routes = [
        ("/app/agents", "Automation", "propertyquarry-agents-mobile.png"),
        ("/app/account", "Account", "propertyquarry-account-mobile.png"),
        ("/app/billing", "Billing", "propertyquarry-billing-mobile.png"),
    ]
    try:
        page = context.new_page()
        for route, mobile_mode_name, screenshot_name in routes:
            response = page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None and response.ok
            _assert_no_horizontal_overflow(page)
            _assert_property_shell_visual_gates(page, max_appbar_height=130)

            switch = page.locator("[data-property-mobile-dock]").first
            expect(switch).to_be_visible()
            expect(page.get_by_role("button", name=mobile_mode_name)).to_be_visible()
            expect(page.locator("[data-pqx-launch-top]")).to_have_count(0)

            if route == "/app/agents":
                expect(page.locator("[data-property-search-agent-grid]")).to_be_visible()
                expect(page.locator(".pqx-automation-thumbnail").first).to_be_visible()
            elif route == "/app/account":
                expect(page.locator("body", has_text="Notification type")).to_be_visible()
                expect(page.locator("body", has_text="Export account data")).to_be_visible()
            else:
                expect(page.locator("body", has_text="Billing history")).to_be_visible()
                expect(page.locator("body", has_text="Cancellation and refunds")).to_be_visible()
                billing_mobile_metrics = page.evaluate(
                    """() => {
                        const summary = document.querySelector('.pqx-billing-summary');
                        const cards = Array.from(document.querySelectorAll('.pqx-billing-summary-card'));
                        const genericLinks = cards
                            .flatMap((card) => Array.from(card.querySelectorAll('.pqx-link-button')))
                            .filter((link) => {
                                const style = window.getComputedStyle(link);
                                return style.display !== 'none' && style.visibility !== 'hidden';
                            });
                        return {
                            columns: summary ? window.getComputedStyle(summary).gridTemplateColumns.split(' ').length : 0,
                            cardCount: cards.length,
                            visibleGenericLinks: genericLinks.length,
                            tallestCard: Math.max(0, ...cards.map((card) => card.getBoundingClientRect().height)),
                        };
                    }"""
                )
                assert billing_mobile_metrics["columns"] == 2
                assert billing_mobile_metrics["cardCount"] >= 4
                assert billing_mobile_metrics["visibleGenericLinks"] == 0
                assert billing_mobile_metrics["tallestCard"] <= 120

            screenshot_path = tmp_path / screenshot_name
            page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
            assert screenshot_path.exists() and screenshot_path.stat().st_size > 16_000
    finally:
        context.close()


def test_propertyquarry_setup_summary_tiles_do_not_clip_and_sideframe_stays_compact(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.locator(".pqx-setup").wait_for(state="visible")
        page.evaluate(
            """
            () => {
              const list = document.querySelector('[data-pqx-previous-searches]');
              if (!list || list.querySelector('[data-pqx-previous-search-card]')) return;
              const card = document.createElement('article');
              card.className = 'pqx-previous-search';
              card.setAttribute('data-pqx-previous-search-card', '');
              const longTitle = 'Review apartment alert: Ruhige und moderne 2-Zimmer Wohnung - sehr gepflegt - optimale Raumaufteilung / Top Innenhoflage mit extra langem Titel fuer Layout Gate';
              const scopeSvg = encodeURIComponent(`
                <svg xmlns="http://www.w3.org/2000/svg" width="320" height="184" viewBox="0 0 320 184" fill="none">
                  <rect width="320" height="184" rx="18" fill="#1E1A15"/>
                  <rect x="12" y="12" width="296" height="160" rx="14" fill="#F3ECDD"/>
                  <rect x="38" y="34" width="44" height="24" rx="8" fill="#D7D0C3" stroke="#BBAF9B"/>
                  <rect x="92" y="42" width="66" height="42" rx="10" fill="#D44F4F" fill-opacity="0.42" stroke="#F2A3A3" stroke-width="2"/>
                  <rect x="166" y="62" width="58" height="34" rx="10" fill="#D7D0C3" stroke="#BBAF9B"/>
                  <rect x="122" y="98" width="76" height="32" rx="10" fill="#D7D0C3" stroke="#BBAF9B"/>
                </svg>`);
              card.innerHTML = `
                <div class="pqx-previous-scope-preview">
                  <div class="pqx-previous-district-hotspots" aria-hidden="true">
                    <button
                      class="pqx-previous-district-hotspot"
                      type="button"
                      data-label="1020 Vienna"
                      data-pqx-scope-open
                      data-pqx-scope-image="data:image/svg+xml;utf8,${scopeSvg}"
                      data-pqx-scope-alt="Search area preview for 1020 Vienna"
                      data-pqx-scope-title="1020 Vienna"
                      data-pqx-scope-caption="1020 Vienna, 1030 Vienna"
                      style="left: 31.1%; top: 26.25%; width: 22.297%; height: 26.25%;"></button>
                    <button
                      class="pqx-previous-district-hotspot is-selected"
                      type="button"
                      data-label="1030 Vienna"
                      data-pqx-scope-open
                      data-pqx-scope-image="data:image/svg+xml;utf8,${scopeSvg}"
                      data-pqx-scope-alt="Search area preview for 1020 Vienna"
                      data-pqx-scope-title="1030 Vienna"
                      data-pqx-scope-caption="1020 Vienna, 1030 Vienna"
                      style="left: 56.081%; top: 38.75%; width: 19.595%; height: 21.25%;"></button>
                  </div>
                  <button
                    class="pqx-previous-scope-trigger"
                    type="button"
                    data-pqx-scope-open
                    data-pqx-scope-image="data:image/svg+xml;utf8,${scopeSvg}"
                    data-pqx-scope-alt="Search area preview for 1020 Vienna"
                    data-pqx-scope-title="${longTitle}"
                    data-pqx-scope-caption="1020 Vienna, 1030 Vienna">
                    <img class="pqx-previous-scope-image" data-pqx-scope-preview src="data:image/svg+xml;utf8,${scopeSvg}" alt="Search area preview for 1020 Vienna">
                  </button>
                  <div class="pqx-previous-scope-hover" aria-hidden="true">
                    <img src="data:image/svg+xml;utf8,${scopeSvg}" alt="Search area preview for 1020 Vienna">
                    <span class="pqx-note">1020 Vienna, 1030 Vienna</span>
                  </div>
                  <div class="pqx-previous-scope-caption">
                    <span class="pqx-note">1020 Vienna, 1030 Vienna</span>
                  </div>
                </div>
                <div class="pqx-previous-body">
                  <div class="pqx-previous-search-head">
                    <div>
                      <strong class="pqx-previous-title">${longTitle}</strong>
                      <span class="pqx-note">Buy · Vienna · AT</span>
                    </div>
                  </div>
                  <div class="pqx-previous-metrics">
                    <span><b>4</b> ranked</span>
                    <span><b>2</b> sent</span>
                    <span>best <b>64</b></span>
                  </div>
                  <div class="pqx-note">Best match is still below the shortlist threshold.</div>
                </div>
                <div class="pqx-previous-actions">
                  <a class="pqx-link-button primary" href="#">Open</a>
                  <button class="pqx-link-button subtle" type="button">Delete</button>
                </div>`;
              list.prepend(card);
            }
            """
        )

        layout = page.evaluate(
            """
            () => {
              const stage = document.querySelector('.pqx-setup');
              const intro = document.querySelector('.pqx-setup-intro');
              const command = document.querySelector('.pqx-command');
              const rows = Array.from(document.querySelectorAll('.pqx-setup-intro .pqx-dashboard-row'));
              const previousCards = Array.from(document.querySelectorAll('[data-pqx-previous-search-card]'));
              const previews = Array.from(document.querySelectorAll('[data-pqx-scope-preview]'));
              const overflowRows = rows.filter((node) => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1);
              const strongOverflow = rows
                .map((node) => node.querySelector('strong'))
                .filter(Boolean)
                .filter((node) => node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1);
              const previousCardHorizontalOverflow = previousCards.filter((node) => {
                const hoveredOverlay = node.querySelector('.pqx-previous-scope-hover');
                const visibleWidth = hoveredOverlay ? hoveredOverlay.getBoundingClientRect().width : 0;
                return node.scrollWidth > node.clientWidth + Math.max(1, visibleWidth);
              });
              const previewFailures = previews.filter((node) => !(node.complete && node.naturalWidth > 0 && node.clientHeight > 0));
              const previousTitleVisibleOverflow = previousCards
                .flatMap((card) => {
                  const cardBox = card.getBoundingClientRect();
                  return Array.from(card.querySelectorAll('.pqx-previous-title')).map((node) => ({
                    cardBox,
                    nodeBox: node.getBoundingClientRect(),
                  }));
                })
                .filter(({ cardBox, nodeBox }) => nodeBox.left < cardBox.left - 1 || nodeBox.right > cardBox.right + 1);
              const previousPreviewPlacementFailures = previousCards
                .map((card) => {
                  const preview = card.querySelector('.pqx-previous-scope-preview');
                  const body = card.querySelector('.pqx-previous-body');
                  if (!preview || !body) return true;
                  return preview.getBoundingClientRect().top > body.getBoundingClientRect().top + 1;
                })
                .filter(Boolean);
              const stageBox = stage?.getBoundingClientRect();
              const introBox = intro?.getBoundingClientRect();
              const commandBox = command?.getBoundingClientRect();
              return {
                stageWidth: stageBox?.width || 0,
                introWidth: introBox?.width || 0,
                commandWidth: commandBox?.width || 0,
                overflowRowCount: overflowRows.length,
                strongOverflowCount: strongOverflow.length,
                previousCardCount: previousCards.length,
                previousCardHorizontalOverflowCount: previousCardHorizontalOverflow.length,
                previewFailureCount: previewFailures.length,
                previousTitleVisibleOverflowCount: previousTitleVisibleOverflow.length,
                previousPreviewPlacementFailureCount: previousPreviewPlacementFailures.length,
                visibleRowLabels: rows.map((node) => (node.querySelector('span')?.textContent || '').trim()),
                visibleRowValues: rows.map((node) => (node.querySelector('strong')?.textContent || '').trim()),
              };
            }
            """
        )

        assert layout["stageWidth"] > 0
        assert layout["introWidth"] / layout["stageWidth"] <= 0.36
        assert layout["commandWidth"] / layout["stageWidth"] >= 0.58
        assert layout["overflowRowCount"] == 0
        assert layout["strongOverflowCount"] == 0
        assert layout["previousCardCount"] >= 1
        assert layout["previousCardHorizontalOverflowCount"] == 0
        assert layout["previewFailureCount"] == 0
        assert layout["previousTitleVisibleOverflowCount"] == 0
        assert layout["previousPreviewPlacementFailureCount"] == 0
        assert "Saved searches" in set(layout["visibleRowLabels"])
        assert len([value for value in layout["visibleRowValues"] if value]) >= 2
        page.locator('[data-pqx-scope-open]').first.click()
        page.locator('[data-pqx-scope-lightbox]').wait_for(state="visible")
        lightbox_state = page.evaluate(
            """
            () => {
              const dialog = document.querySelector('[data-pqx-scope-lightbox]');
              const image = dialog?.querySelector('[data-pqx-scope-lightbox-image]');
              return {
                open: Boolean(dialog && dialog.open),
                width: image?.naturalWidth || 0,
                src: image?.getAttribute('src') || '',
              };
            }
            """
        )
        assert lightbox_state["open"] is True
        assert lightbox_state["width"] > 0
        assert lightbox_state["src"].startswith("data:image/svg+xml")
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_setup_wizard_numeric_sliders_are_mobile_friendly(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'search'")
        page.locator('[data-property-step-trigger="what"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'what'")

        expected_search_sliders = {
            "max_price_eur": "Any budget",
            "min_rooms": "Any rooms",
            "min_area_m2": "Any size",
        }
        for name, empty_label in expected_search_sliders.items():
            shell = page.locator(f'[data-range-control="{name}"]')
            slider = shell.locator('input[type="range"]')
            assert shell.is_visible()
            assert slider.is_visible()
            assert slider.get_attribute("data-range-empty-label") == empty_label
            shell_box = shell.bounding_box()
            slider_box = slider.bounding_box()
            assert shell_box is not None and shell_box["width"] <= 430
            assert slider_box is not None and slider_box["height"] >= 32

        price_slider = page.locator('input[name="max_price_eur"]')
        assert price_slider.get_attribute("max") == "6000"
        assert page.locator('[data-range-value-for="max_price_eur"]').inner_text().strip() == "Any budget"
        page.locator('[data-property-step-trigger="search"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'search'")
        page.select_option('select[name="listing_mode"]', "buy")
        page.locator('[data-property-step-trigger="what"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'what'")
        assert price_slider.get_attribute("max") == "2000000"
        assert page.locator('[data-range-control="max_price_eur"] [data-range-scale-max]').inner_text().strip() == "EUR 2M"

        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        for name in ("max_results_per_source", "min_match_score"):
            slider = page.locator(f'input[name="{name}"]')
            assert slider.is_visible()
            slider_box = slider.bounding_box()
            assert slider_box is not None and slider_box["height"] >= 34
            assert slider.get_attribute("max") in {"10", "80"}
        assert page.locator('input[name="max_results_per_source"]').get_attribute("data-range-selectable-max") == "2"
        assert page.locator('input[name="min_match_score"]').get_attribute("data-range-selectable-max") == "45"
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
    finally:
        context.close()


def test_propertyquarry_start_failure_explains_backend_reason(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        def _delayed_failure(route):
            time.sleep(1.2)
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "property_plan_upgrade_required:plus"}),
            )

        page.route(
            "**/v1/onboarding/property-search/preferences",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "saved"}),
            ),
        )
        page.route("**/app/api/property/search-runs**", _delayed_failure)
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.select_option('select[name="country_code"]', "AT")
        page.get_by_role("button", name="Select all areas", exact=True).click()
        page.locator('[data-property-step-trigger="providers"]').click()
        expect(page.locator('[data-console-form-variant="property_search"]')).to_have_attribute(
            "data-property-active-step",
            "providers",
        )
        start_button = page.locator("[data-property-start]")
        page.locator("[data-property-start-top]").click()
        page.wait_for_function(
            """
            () => {
              const button = document.querySelector('[data-property-start]');
              return Boolean(
                button
                && button.getAttribute('aria-busy') === 'true'
                && button.getAttribute('data-pqx-loading') === 'true'
                && String(button.textContent || '').includes('Launching...')
              );
            }
            """
        )
        inline_error = page.locator("[data-property-inline-error]")
        expect(inline_error).to_contain_text("Upgrade required for this run")
        expect(inline_error).to_contain_text("plus plan")
        expect(start_button).to_have_attribute("aria-busy", "false")
    finally:
        context.close()


def test_propertyquarry_launch_posts_real_start_payload_and_shows_run_status(
    monkeypatch: pytest.MonkeyPatch,
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["principal_id"] = principal_id
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        observed["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="sources_resolved",
                message="Resolved 1 source for launch smoke.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": "2026-06-05T00:00:00+00:00",
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "email_notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.select_option('select[name="country_code"]', "AT")
        page.get_by_role("button", name="Select all areas", exact=True).click()
        page.locator('[data-property-step-trigger="children"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'children'")
        assert page.locator('[data-property-field-name="enable_family_mode"]').count() == 0
        page.locator('[data-keyword-priority-row][data-keyword-value="good air quality"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="low crime area"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="parking pressure check"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="water and groundwater check"] [data-keyword-preference-select]').select_option("must_have")
        page.locator('[data-keyword-priority-row][data-keyword-value="avoid septic risk"] [data-keyword-preference-select]').select_option("avoid")
        page.locator('[data-keyword-priority-row][data-keyword-value="winter driving check"] [data-keyword-preference-select]').select_option("must_have")
        page.locator('[data-keyword-priority-row][data-keyword-value="avoid flood-risk area"] [data-keyword-preference-select]').select_option("avoid")
        page.locator('[data-keyword-priority-row][data-keyword-value="market nearby"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="market nearby"] [data-keyword-distance-select]').select_option("1000")
        page.locator('[data-keyword-priority-row][data-keyword-value="Baumarkt nearby"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="Baumarkt nearby"] [data-keyword-distance-select]').select_option("2000")
        page.locator('[data-keyword-priority-row][data-keyword-value="shopping center nearby"] [data-keyword-preference-select]').select_option("avoid")
        page.locator('[data-keyword-priority-row][data-keyword-value="shopping center nearby"] [data-keyword-distance-select]').select_option("500")
        page.locator('[data-keyword-priority-row][data-keyword-value="library nearby"] [data-keyword-preference-select]').select_option("nice_to_have")
        page.locator('[data-keyword-priority-row][data-keyword-value="library nearby"] [data-keyword-distance-select]').select_option("1000")
        page.locator('[data-keyword-priority-row][data-keyword-value="medical care nearby"] [data-keyword-preference-select]').select_option("important")
        page.locator('[data-keyword-priority-row][data-keyword-value="medical care nearby"] [data-keyword-distance-select]').select_option("1000")
        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        providerCount = page.locator('input[name="selected_platforms"]').count()
        expectedProviderCap = page.locator('[data-console-form-variant="property_search"]').evaluate(
            """(form) => {
              const raw = String(form.getAttribute('data-console-form-meta') || '').trim();
              const meta = raw ? JSON.parse(raw) : {};
              return Number(meta?.commercial?.max_platforms || 0);
            }"""
        )
        assert isinstance(expectedProviderCap, int)
        assert expectedProviderCap > 0
        allSourcesButton = page.locator('[data-checkbox-group-select-all="selected_platforms"]')
        assert allSourcesButton.is_visible()
        assert f"Select {expectedProviderCap} of {providerCount}" in allSourcesButton.inner_text()
        firstProviderFamily = page.locator('[data-provider-group-panel]').first
        firstProviderFamily.locator("summary").click()
        assert firstProviderFamily.get_by_role("button", name="Add family").is_visible()
        assert firstProviderFamily.get_by_role("button", name="Clear family").is_visible()
        familyProviderCount = firstProviderFamily.locator('input[name="selected_platforms"]').count()
        assert familyProviderCount > 0
        firstProviderFamily.get_by_role("button", name="Add family").click()
        checkedFamilyProviderCount = firstProviderFamily.locator('input[name="selected_platforms"]:checked').count()
        checkedTotalAfterFamily = page.locator('input[name="selected_platforms"]:checked').count()
        assert checkedFamilyProviderCount == min(familyProviderCount, expectedProviderCap)
        assert checkedTotalAfterFamily == checkedFamilyProviderCount
        allSourcesButton.click()
        checkedProviderCount = page.locator('input[name="selected_platforms"]:checked').count()
        assert providerCount > checkedProviderCount
        assert checkedProviderCount == expectedProviderCap
        assert page.locator('[data-provider-group-panel][open]').count() >= 1
        assert page.locator('[data-property-inline-status]', has_text=f"Selected {expectedProviderCap} of {providerCount} providers").is_visible()
        page.locator('input[name="min_match_score"]').evaluate(
            "(node) => { node.value = '45'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('input[name="require_floorplan"]').check()

        with page.expect_response("**/app/api/property/search-runs") as start_response:
            page.locator("[data-property-start]").click()
        response = start_response.value
        assert response.ok
        try:
            page.wait_for_url("**/app/properties?run_id=*", timeout=5000)
        except Exception:
            page.wait_for_load_state("networkidle")
        run_id = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get("run_id", [""])[0]
        page.wait_for_selector(
            "[data-pqx-finished-compare], [data-pqx-empty-results], [data-pqx-screenfit-target=\"run-progress\"], [data-workbench-results-table]",
            timeout=10000,
        )
        assert "Could not start property search" not in page.locator("body").inner_text()
        deadline = time.time() + 5.0
        while "property_search_preferences" not in observed and time.time() < deadline:
            time.sleep(0.05)
        assert observed["principal_id"] == "pq-greenfield-browser"
        preferences = dict(observed["property_search_preferences"])
        assert preferences["country_code"] == "AT"
        assert preferences["region_code"] == "vienna"
        assert preferences["full_region_scope"] is True
        assert preferences["location_query"] == "Vienna"
        assert preferences["prefer_good_air_quality"] is True
        assert preferences["prefer_low_crime_area"] is True
        assert preferences["require_parking_pressure_check"] is True
        assert preferences["require_drinking_water_quality_research"] is True
        assert preferences["avoid_cesspit_or_septic_risk"] is True
        assert preferences["require_winter_access_research"] is True
        assert preferences["avoid_flood_risk_area"] is True
        assert preferences["max_distance_to_market_m"] == 1000
        assert preferences["max_distance_to_market_importance"] == "important"
        assert preferences["max_distance_to_hardware_store_m"] == 2000
        assert preferences["max_distance_to_hardware_store_importance"] == "important"
        assert preferences["max_distance_to_shopping_center_m"] == 500
        assert preferences["max_distance_to_shopping_center_importance"] == "avoid"
        assert preferences["max_distance_to_medical_care_m"] == 1000
        assert preferences["max_distance_to_medical_care_importance"] == "important"
        assert preferences["max_distance_to_library_m"] == 1000
        assert preferences["max_distance_to_library_importance"] == "nice_to_have"
        assert preferences["min_match_score"] == 45
        assert preferences["require_floorplan"] is True
        assert len(observed["selected_platforms"]) == 3
        assert page.locator("body", has_text="Altbau near U6").is_visible()
        assert page.locator("body", has_text="Open property").is_visible()
        assert page.locator("body", has_text="360 ready").is_visible()
        page.locator("[data-workbench-row]", has_text="Altbau near U6").click()
        assert "/app/shortlist" in page.url
        assert page.locator("[data-workbench-row][aria-selected='true']", has_text="Altbau near U6").is_visible()
        assert urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get("candidate", [""])[0]
        assert page.locator("body", has_text="Open property").is_visible()
    finally:
        context.close()


def test_propertyquarry_best_match_opens_hosted_3d_tour_and_flythrough_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        best_match = page.locator("[data-workbench-row]", has_text="Altbau near U6").first
        best_match.wait_for()
        best_match.click()
        open_360 = best_match.get_by_role("link", name="360 ready")
        tour_url = str(open_360.get_attribute("href") or "").strip()
        assert tour_url.endswith("/tours/altbau-u6")
        tour_entry = tour_url if tour_url.startswith("http") else f"{base_url}{tour_url}"
        response = page.goto(f"{tour_entry}?pane=floorplan-pane", wait_until="networkidle")
        assert response is not None and response.ok
        page.locator("h1").wait_for()
        assert page.locator("body", has_text="PROPERTY TOUR").is_visible()
        assert page.locator("body", has_text="Altbau near U6").is_visible()
        page.locator('#role-filter button[data-role="floorplan"]').click()
        assert page.locator("#stage-role").inner_text().lower() == "floorplan"
        assert page.locator("#stage-image").is_visible()
        natural_width = page.evaluate("() => document.getElementById('stage-image')?.naturalWidth || 0")
        assert natural_width >= 1000

        response = page.goto(f"{tour_entry}?pane=flythrough-pane&autoplay=1", wait_until="networkidle")
        assert response is not None and response.ok
        video = page.locator("#tour-video")
        video.wait_for()
        assert video.is_visible()
        page.evaluate("() => document.getElementById('tour-video')?.play()?.catch(() => null)")
        page.wait_for_timeout(1800)
        state = page.evaluate(
            """() => {
                const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
                return video ? {
                    currentTime: video.currentTime,
                    duration: video.duration,
                    readyState: video.readyState,
                    videoWidth: video.videoWidth,
                } : null;
            }"""
        )
        assert state is not None
        assert state["readyState"] >= 2
        assert state["videoWidth"] >= 640
        assert state["currentTime"] > 0.2
        assert state["duration"] >= 2.5
        assert _video_frame_brightness(page) > 10.0
        assert page.locator("#tour-video source").get_attribute("type") == "video/mp4"
        assert not [
            message
            for message in console_errors
            if "decode" in message.lower()
            or "media" in message.lower()
            or "refused" in message.lower()
            or "failed to load resource" in message.lower()
        ]
    finally:
        context.close()


def test_propertyquarry_walkthrough_request_is_user_initiated_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    visual_requests: list[dict[str, object]] = []

    def _capture_visual_request(route) -> None:
        request = route.request
        payload = request.post_data_json
        visual_requests.append(payload if isinstance(payload, dict) else {})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "generated_at": "2026-06-19T10:00:00+00:00",
                    "status": "created",
                    "property_url": visual_requests[-1].get("property_url", ""),
                    "title": "Family flat near Tiergarten",
                    "request_kind": "flythrough",
                    "tour_url": "/tours/family-tiergarten",
                    "flythrough_url": "",
                    "flythrough_status": "pending",
                    "status_label": "Flythrough queued",
                    "status_detail": "Flythrough is queued after your request and will appear here when it is ready.",
                    "delivery_status": "skipped",
                    "blocked_reason": "",
                    "source_ref": visual_requests[-1].get("source_ref", ""),
                    "run_id": visual_requests[-1].get("run_id", ""),
                    "candidate_ref": visual_requests[-1].get("candidate_ref", ""),
                }
            ),
        )

    page.route("**/app/api/signals/willhaben/property-tour", _capture_visual_request)
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        page.locator("[data-workbench-row]").first.wait_for(timeout=5000)
        assert visual_requests == []

        family_row = page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").first
        family_row.click()
        request_button = family_row.get_by_role("button", name="Request walkthrough")
        expect(request_button).to_be_visible()
        request_button.click()
        page.wait_for_timeout(750)
        assert visual_requests, page.locator("body").inner_text()[:1000]
        body_after_request = page.locator("body").inner_text()
        assert "Walkthrough queued" in body_after_request, body_after_request[:2000]

        assert len(visual_requests) == 1
        payload = visual_requests[0]
        assert payload["request_kind"] == "flythrough"
        assert payload["auto_deliver"] is False
        assert payload["allow_floorplan_only"] is True
        assert payload["run_id"] == "run-42"
        assert str(payload["property_url"]).endswith("/family-tiergarten")
    finally:
        context.close()


def test_propertyquarry_visual_request_uses_listing_url_fallback_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    visual_requests: list[dict[str, object]] = []

    def _capture_visual_request(route) -> None:
        request = route.request
        payload = request.post_data_json
        visual_requests.append(payload if isinstance(payload, dict) else {})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "generated_at": "2026-06-19T10:00:00+00:00",
                    "status": "created",
                    "property_url": visual_requests[-1].get("property_url", ""),
                    "title": "Listing URL only loft",
                    "request_kind": "flythrough",
                    "tour_url": "",
                    "flythrough_url": "",
                    "flythrough_status": "pending",
                    "status_label": "Flythrough queued",
                    "status_detail": "Flythrough is queued after your request.",
                    "delivery_status": "skipped",
                    "blocked_reason": "",
                    "source_ref": visual_requests[-1].get("source_ref", ""),
                    "run_id": visual_requests[-1].get("run_id", ""),
                    "candidate_ref": visual_requests[-1].get("candidate_ref", ""),
                }
            ),
        )

    page.route("**/app/api/signals/willhaben/property-tour", _capture_visual_request)
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        listing_only_row = page.locator("[data-workbench-row]", has_text="Listing URL only loft").first
        listing_only_row.wait_for(timeout=5000)
        assert visual_requests == []

        request_button = listing_only_row.get_by_role("button", name="Request walkthrough")
        expect(request_button).to_be_visible()
        assert str(request_button.get_attribute("data-property-url") or "").endswith("/listing-url-only-loft")
        request_button.click()
        page.wait_for_timeout(750)

        assert len(visual_requests) == 1
        payload = visual_requests[0]
        assert payload["request_kind"] == "flythrough"
        assert payload["auto_deliver"] is False
        assert payload["allow_floorplan_only"] is True
        assert payload["run_id"] == "run-42"
        assert str(payload["property_url"]).endswith("/listing-url-only-loft")
        assert "Walkthrough queued" in page.locator("body").inner_text()
    finally:
        context.close()


def test_propertyquarry_austria_region_selection_keeps_region_specific_area_choices(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?autolocate=1", wait_until="networkidle")
        assert response is not None and response.ok

        page.select_option('select[name="country_code"]', "AT")
        page.select_option('select[name="region_code"]', "salzburg")
        page.wait_for_timeout(250)
        assert page.locator('select[name="region_code"]').input_value() == "salzburg"
        page.locator('[data-property-field-name="location_query"]').wait_for(state="visible")
        assert page.locator('label.pqx-check', has_text='Hallein').count() >= 1

        page.select_option('select[name="region_code"]', "lower_austria")
        page.wait_for_timeout(250)
        assert page.locator('select[name="region_code"]').input_value() == "lower_austria"
        page.locator('[data-property-field-name="location_query"]').wait_for(state="visible")
        assert page.locator('label.pqx-check', has_text='Baden').count() >= 1
    finally:
        context.close()


def test_propertyquarry_packet_dashboard_supports_real_browser_share_and_replication_actions(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    publication = client.post(
        "/app/api/properties/listing-browser-packet/packets/render",
        json={
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "fliplink_format": "flipbook_3d",
            "property_payload": {
                "title": "Family flat near Augarten",
                "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
                "match_reasons": ["Floorplan and family fit."],
                "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
                "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
                "property_facts": {
                    "rooms": 3,
                    "area_m2": 84,
                    "street_address": "Private Street 4",
                    "map_lat": 48.2,
                    "map_lng": 16.3,
                    "has_floorplan": True,
                    "postal_name": "1020 Wien",
                },
                "public_preference_snapshot": {"prefer_balcony": True},
            },
        },
    )
    assert publication.status_code == 200, publication.text
    publication_id = publication.json()["publication"]["publication_id"]
    feedback_one = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": "listing-browser-packet",
            "publication_id": publication_id,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "followup_status": "asked",
        },
    )
    assert feedback_one.status_code == 200, feedback_one.text
    feedback_two = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-jonas",
            "stakeholder_label": "Jonas",
            "property_ref": "listing-browser-packet",
            "publication_id": publication_id,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Street noise is a blocker.",
            "decision_state": "rejected",
        },
    )
    assert feedback_two.status_code == 200, feedback_two.text
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties/packets", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("[data-property-packets-dashboard]").is_visible()
        assert page.locator("body", has_text="Share polished property pages and track the replies.").is_visible()
        assert page.locator("body", has_text="Household reactions").is_visible()
        assert page.locator("body", has_text="Risk signals").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        page.locator('[data-packet-share-form] input[name="recipient_name"]').first.fill("Anna")
        page.locator('[data-packet-share-form] input[name="recipient_email"]').first.fill("anna@example.com")
        page.locator('[data-packet-share-form] input[name="relationship"]').first.fill("Sister")
        with page.expect_response("**/app/api/properties/packets/*/shares") as share_response_info:
            page.locator('[data-packet-share-form] button[type="submit"]').first.click()
        share_response = share_response_info.value
        assert share_response.ok, share_response.text()

        page.locator('[data-fliplink-analytics-form] input[name="views"]').first.fill("8")
        page.locator('[data-fliplink-analytics-form] input[name="unique_visitors"]').first.fill("2")
        page.locator('[data-fliplink-analytics-form] input[name="average_time_seconds"]').first.fill("55")
        with page.expect_response("**/app/api/properties/packets/*/fliplink/analytics-snapshot") as analytics_response_info:
            page.locator('[data-fliplink-analytics-form] button[type="submit"]').first.click()
        analytics_response = analytics_response_info.value
        assert analytics_response.ok, analytics_response.text()

        with page.expect_response("**/app/api/properties/packets/*/republish") as republish_response_info:
            page.locator(f'[data-republish-publication][data-publication-id="{publication_id}"]').click()
        republish_response = republish_response_info.value
        assert republish_response.ok, republish_response.text()

        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Anna · family · link").is_visible()
        assert page.locator("[data-analytics-summary]", has_text="8 views").is_visible()
        assert page.locator("[data-analytics-summary]", has_text="2 visitors").is_visible()
        assert page.locator("body", has_text="Optimization recommendations").is_visible()
        assert page.locator("body", has_text="What changed").is_visible()
        assert page.locator("body", has_text="Street noise is a blocker.").is_visible()

        preview_expectations = {
            "search_results_ready": ("PropertyQuarry found 2 strong matches", "Open shortlist"),
            "property_match": ("Property match: Altbau near U6", "No — tell us why"),
            "tour_ready": ("Apartment tour ready: Family flat near Augarten", "No — tell us why"),
            "investment_research_ready": ("Investment research ready", "Pass — too risky"),
            "workspace_invitation": ("Mara invited you to PropertyQuarry", "Open invite"),
            "workspace_access": ("Your access link for PropertyQuarry account", "Open access link"),
            "google_connect": ("Connect Google to PropertyQuarry account", "Connect Google"),
            "market_ready": ("PropertyQuarry market ready: Vienna", "Open PropertyQuarry"),
        }
        for template_key, (subject_text, cta_text) in preview_expectations.items():
            response = page.goto(f"{base_url}/app/properties/notifications/preview?template={template_key}", wait_until="networkidle")
            assert response is not None and response.ok
            assert page.locator("body", has_text="Email preview").is_visible()
            assert page.locator("body", has_text=subject_text).is_visible()
            assert page.frame_locator("iframe").locator("body", has_text=cta_text).is_visible()
    finally:
        context.close()


def test_propertyquarry_flagship_operating_loop_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    seeded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "advisor-anna",
            "stakeholder_label": "Anna",
            "property_ref": property_ref,
            "category": "concern",
            "sentiment": "negative",
            "importance": 4,
            "text": "Operating costs still need proof before a viewing.",
            "source": "advisor_packet_review",
            "decision_state": "documents_requested",
        },
    )
    assert seeded.status_code == 200, seeded.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text=re.compile(r"ranked homes", re.I)).is_visible()
        candidate_ref = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-ref")
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert candidate_ref
        assert packet_path
        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        with page.expect_response("**/preference-profile/property-feedback") as save_response_info:
            page.get_by_role("button", name="No", exact=True).click()
            page.locator("[data-object-feedback-save]").click()
        assert save_response_info.value.ok
        assert page.locator("body", has_text="Question 1").is_visible()
        packet_render = client.post(
            f"/app/api/properties/{urllib.parse.quote(property_ref, safe='')}/packets/render",
            json={
                "packet_kind": "family_review",
                "privacy_mode": "family_review",
                "fliplink_format": "flipbook_3d",
                "property_payload": {
                    "title": "Altbau near U6",
                    "property_url": property_ref,
                    "match_reasons": ["Lift and transit fit."],
                    "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
                    "property_facts": {
                        "rooms": 3,
                        "area_m2": 78,
                        "street_address": "Private Street 4",
                        "map_lat": 48.2,
                        "map_lng": 16.3,
                        "has_floorplan": True,
                        "postal_name": "1020 Wien",
                    },
                },
            },
        )
        assert packet_render.status_code == 200, packet_render.text
        response = page.goto(f"{base_url}/app/properties/packets", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Household reactions").is_visible()
        assert page.locator("body", has_text="What changed").is_visible()
        share_form = page.locator('[data-packet-share-form]').first
        share_form.locator('input[name="recipient_name"]').fill("Anna")
        share_form.locator('input[name="recipient_email"]').fill("anna@example.com")
        share_form.locator('input[name="relationship"]').fill("Advisor")
        share_form.locator('select[name="audience_type"]').select_option("advisor")
        with page.expect_response("**/app/api/properties/packets/*/shares") as share_response_info:
            share_form.locator('button[type="submit"]').click()
        assert share_response_info.value.ok
        response = page.goto(f"{base_url}/app/properties/notifications/preview?template=property_match", wait_until="networkidle")
        assert response is not None and response.ok
        no_link = page.frame_locator("iframe").get_by_role("link", name="No — tell us why")
        href = no_link.get_attribute("href")
        assert href and "decision=no" in href and "clippy=1" in href
        packet_url = f"{base_url}{packet_path}"
        separator = "&" if "?" in packet_url else "?"
        response = page.goto(f"{packet_url}{separator}run_id=run-42&decision=no&clippy=1&prompt=What%20is%20the%20strongest%20blocker%20here%3F", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="At a glance").is_visible()
        assert page.locator("body", has_text="Decision shortcut loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Clippy prompt loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
    finally:
        context.close()
