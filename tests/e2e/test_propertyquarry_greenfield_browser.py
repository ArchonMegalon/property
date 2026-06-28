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
                "matterport_url": "https://my.matterport.com/show/?m=AltbauNearU6",
                "brand_name": "PropertyQuarry",
                "scene_strategy": "layout_first",
                "creation_mode": "hosted_floorplan_tour",
                "video_relpath": "tour.mp4",
                "video_provider": "manual_upload",
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
                "high_match_min_score": 60,
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
                                "tour_url": "/tours/altbau-u6/control/matterport",
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
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", browser_base_url)
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


def _assert_propertyquarry_billing_fallback_page(page: Page) -> None:
    expect(page.locator("body", has_text="Billing portal unavailable")).to_be_visible()
    expect(page.locator("body", has_text="billing portal is still being connected")).to_be_visible()
    expect(page.locator("body", has_text=re.compile(r"PropertyQuarry access (remains|stays) active", re.I))).to_be_visible()
    expect(page.get_by_role("link", name="Back to account")).to_be_visible()
    body_text = page.evaluate("() => document.body.innerText")
    assert "Billing history" not in body_text
    assert "Cancellation and refunds" not in body_text
    assert "When to upgrade" not in body_text


def test_propertyquarry_public_home_and_sign_in_capture_polish_screenshots(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    desktop = _new_public_context(browser, mobile=False, width=1440, height=820)
    mobile = _new_public_context(browser, mobile=True)
    signed_in = _new_public_context(browser, mobile=False, width=1440, height=820)
    try:
        desktop_page = desktop.new_page()
        response = desktop_page.goto(f"{base_url}/?home=1", wait_until="networkidle")
        assert response is not None and response.ok
        expect(desktop_page.get_by_role("heading", name="Search once. Rank the right homes. Decide with evidence.")).to_be_visible()
        expect(desktop_page.get_by_text("Example shortlist")).to_be_visible()
        expect(desktop_page.get_by_text("5 ranked · 22 filtered")).to_be_visible()
        expect(desktop_page.get_by_text("Hard filters stay hard")).to_be_visible()
        expect(desktop_page.get_by_text("Preferences score")).to_be_visible()
        _assert_no_horizontal_overflow(desktop_page)
        desktop_home_metrics = desktop_page.evaluate(
            """() => ({
                innerHeight: window.innerHeight,
                scrollHeight: document.scrollingElement ? document.scrollingElement.scrollHeight : 0,
                footerVisible: !!(document.querySelector('footer') && getComputedStyle(document.querySelector('footer')).display !== 'none'),
            })"""
        )
        assert desktop_home_metrics["scrollHeight"] <= desktop_home_metrics["innerHeight"] + 1, desktop_home_metrics
        assert desktop_home_metrics["footerVisible"] is False
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

        _issue_browser_workspace_session(client=client, context=signed_in, base_url=base_url)
        signed_page = signed_in.new_page()
        response = signed_page.goto(f"{base_url}/?home=1", wait_until="networkidle")
        assert response is not None and response.ok
        expect(signed_page.get_by_role("link", name="Open search").first).to_be_visible()
        expect(signed_page.get_by_role("link", name="Open latest run")).to_be_visible()
        expect(signed_page.locator(".topbar form[action='/app/actions/sign-out'] button", has_text="Log out")).to_be_visible()
        assert signed_page.get_by_text("Log out", exact=True).count() == 1
        assert signed_page.locator(".pq-hero-copy form[action='/app/actions/sign-out']").count() == 0
        response = signed_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        expect(signed_page.get_by_role("link", name="Open search").first).to_be_visible()
        assert signed_page.get_by_role("link", name="Open current session").count() == 0
        assert signed_page.get_by_text("Log out", exact=True).count() == 1
        response = signed_page.goto(f"{base_url}/pricing", wait_until="networkidle")
        assert response is not None and response.ok
        expect(signed_page.get_by_role("heading", name="Free")).to_be_visible()
        billing_links = signed_page.get_by_role("link", name="Open billing account")
        expect(billing_links).to_have_count(2)
        billing_hrefs = signed_page.evaluate(
            """() => Array.from(document.querySelectorAll('a'))
              .filter((node) => (node.textContent || '').trim() === 'Open billing account')
              .map((node) => node.getAttribute('href') || '')"""
        )
        assert billing_hrefs == ["/app/account#delivery", "/app/account#delivery"]
        assert signed_page.get_by_text("Create account", exact=True).count() == 0

        response = desktop_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        expect(desktop_page.get_by_role("heading", name="Sign in to continue your property search.")).to_be_visible()
        expect(desktop_page.get_by_text("Use a saved session, email link, or connected identity.")).to_be_visible()
        expect(desktop_page.get_by_role("link", name="Open current session")).to_be_visible()
        google_link = desktop_page.get_by_role("link", name="Continue with Google")
        assert desktop_page.get_by_role("button", name="Google unavailable").count() == 0
        facebook_link = desktop_page.get_by_role("link", name="Continue with Facebook")
        assert desktop_page.get_by_role("button", name="Facebook unavailable").count() == 0
        if google_link.count():
            desktop_page.evaluate(
                """() => {
                    const google = document.querySelector('a[href="/sign-in/google"]');
                    google?.addEventListener('click', (event) => event.preventDefault(), { capture: true });
                }"""
            )
            google_link.click(no_wait_after=True)
            opening_google = desktop_page.get_by_role("link", name="Opening Google...")
            expect(opening_google).to_be_visible()
            assert opening_google.get_attribute("aria-busy") == "true"
        response = desktop_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        _assert_no_horizontal_overflow(desktop_page)
        desktop_sign_in_metrics = desktop_page.evaluate(
            """() => {
                const panel = document.querySelector('.access-panel');
                const shell = document.querySelector('.access-shell');
                const intro = document.querySelector('.access-intro');
                const entry = document.querySelector('.access-entry');
                const heading = document.querySelector('.access-panel h1');
                const panelRect = panel ? panel.getBoundingClientRect() : null;
                const introRect = intro ? intro.getBoundingClientRect() : null;
                const entryRect = entry ? entry.getBoundingClientRect() : null;
                const headingRect = heading ? heading.getBoundingClientRect() : null;
                return {
                    panelWidth: panelRect ? panelRect.width : 0,
                    introWidth: introRect ? introRect.width : 0,
                    entryWidth: entryRect ? entryRect.width : 0,
                    shellColumns: shell ? window.getComputedStyle(shell).gridTemplateColumns.split(' ').filter(Boolean).length : 0,
                    headingHeight: headingRect ? headingRect.height : 0,
                };
            }"""
        )
        assert desktop_sign_in_metrics["panelWidth"] >= 780, desktop_sign_in_metrics
        assert desktop_sign_in_metrics["shellColumns"] == 2, desktop_sign_in_metrics
        assert desktop_sign_in_metrics["introWidth"] >= 260, desktop_sign_in_metrics
        assert desktop_sign_in_metrics["entryWidth"] >= 300, desktop_sign_in_metrics
        assert desktop_sign_in_metrics["headingHeight"] <= 270, desktop_sign_in_metrics
        sign_in_shot = tmp_path / "propertyquarry-sign-in-desktop.png"
        desktop_page.screenshot(path=str(sign_in_shot), full_page=True)
        assert sign_in_shot.exists()

        response = mobile_page.goto(f"{base_url}/sign-in", wait_until="networkidle")
        assert response is not None and response.ok
        expect(mobile_page.get_by_role("heading", name="Sign in to continue your property search.")).to_be_visible()
        assert mobile_page.get_by_role("link", name="Open current session").count() == 1
        _assert_no_horizontal_overflow(mobile_page)
        mobile_sign_in_shot = tmp_path / "propertyquarry-sign-in-mobile.png"
        mobile_page.screenshot(path=str(mobile_sign_in_shot), full_page=True)
        assert mobile_sign_in_shot.exists()

        response = mobile_page.goto(f"{base_url}/pricing", wait_until="networkidle")
        assert response is not None and response.ok
        expect(mobile_page.get_by_role("heading", name="Free")).to_be_visible()
        expect(mobile_page.get_by_role("heading", name="Plus")).to_be_visible()
        expect(mobile_page.get_by_role("heading", name="Agent")).to_be_visible()
        expect(mobile_page.get_by_text("35/100")).to_be_visible()
        expect(mobile_page.get_by_text("45/100")).to_be_visible()
        expect(mobile_page.get_by_text("60/100")).to_be_visible()
        _assert_no_horizontal_overflow(mobile_page)
        mobile_pricing_shot = tmp_path / "propertyquarry-pricing-mobile.png"
        mobile_page.screenshot(path=str(mobile_pricing_shot), full_page=True)
        assert mobile_pricing_shot.exists()
    finally:
        desktop.close()
        mobile.close()
        signed_in.close()


def test_propertyquarry_sign_in_desktop_uses_balanced_two_column_entry_surface(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_public_context(browser, mobile=False, width=1440, height=900)
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/sign-in?signing_in=1", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.get_by_role("heading", name="Sign in to continue your property search.")).to_be_visible()
        expect(page.get_by_role("link", name="Open current session")).to_be_visible()
        expect(page.get_by_text("Any provider below reopens the same account or creates it automatically on first use.")).to_be_visible()
        expect(page.get_by_text("Trusted device")).to_be_visible()
        _assert_no_horizontal_overflow(page)
        metrics = page.evaluate(
            """() => {
                const panel = document.querySelector('.access-panel');
                const shell = document.querySelector('.access-shell');
                const intro = document.querySelector('.access-intro');
                const entry = document.querySelector('.access-entry');
                const heading = document.querySelector('.access-panel h1');
                const panelRect = panel ? panel.getBoundingClientRect() : null;
                const introRect = intro ? intro.getBoundingClientRect() : null;
                const entryRect = entry ? entry.getBoundingClientRect() : null;
                const headingRect = heading ? heading.getBoundingClientRect() : null;
                return {
                    panelWidth: panelRect ? panelRect.width : 0,
                    introWidth: introRect ? introRect.width : 0,
                    entryWidth: entryRect ? entryRect.width : 0,
                    shellColumns: shell ? window.getComputedStyle(shell).gridTemplateColumns.split(' ').filter(Boolean).length : 0,
                    headingHeight: headingRect ? headingRect.height : 0,
                };
            }"""
        )
        assert metrics["panelWidth"] >= 780, metrics
        assert metrics["shellColumns"] == 2, metrics
        assert metrics["introWidth"] >= 260, metrics
        assert metrics["entryWidth"] >= 300, metrics
        assert metrics["headingHeight"] <= 270, metrics
    finally:
        context.close()


def test_propertyquarry_home_example_media_links_open_real_public_tour_targets(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    slug = "altbau-u6"
    signed_in = _new_public_context(browser, mobile=False, width=1440, height=820)
    try:
        _issue_browser_workspace_session(client=client, context=signed_in, base_url=base_url)
        page = signed_in.new_page()
        response = page.goto(f"{base_url}/?home=1", wait_until="networkidle")
        assert response is not None and response.ok
        tour_href = page.get_by_role("link", name="3D tour ready").get_attribute("href")
        walkthrough_href = page.get_by_role("link", name="Walkthrough ready").get_attribute("href")
        assert tour_href == f"/tours/{slug}/control/matterport"
        assert walkthrough_href == f"/tours/files/{slug}/tour.mp4"
        assert "#tour-preview" not in page.content()
        assert "#walkthrough-preview" not in page.content()
    finally:
        signed_in.close()


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


def _assert_mobile_topnav_tap_targets(page: Page) -> None:
    metrics = page.evaluate(
        """
        () => {
          const legacyDock = document.querySelector('[data-property-mobile-dock], .pq-mobile-nav');
          const nav = document.querySelector('[data-property-console-topnav], .pqx-primary-nav, .prd-primary-nav, .pq-pack-nav');
          if (!nav) return { navVisible: false, legacyDockVisible: Boolean(legacyDock), targets: [] };
          const navRect = nav.getBoundingClientRect();
          const targetNodes = Array.from(nav.querySelectorAll('a, button, span[aria-current="page"], span.is-active'));
          return {
            navVisible: navRect.width > 0 && navRect.height > 0,
            legacyDockVisible: Boolean(legacyDock && legacyDock.getBoundingClientRect().height > 0),
            navLeft: Math.round(navRect.left),
            navRight: Math.round(navRect.right),
            viewportWidth: window.innerWidth,
            targets: targetNodes.map((node) => {
              const rect = node.getBoundingClientRect();
              const style = window.getComputedStyle(node);
              return {
                text: String(node.textContent || node.getAttribute('aria-label') || '').trim().slice(0, 60),
                visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
              };
            }).filter((row) => row.visible && row.right > 0 && row.left < window.innerWidth),
          };
        }
        """
    )
    assert metrics["navVisible"] is True, metrics
    assert metrics["legacyDockVisible"] is False, metrics
    assert metrics["navLeft"] >= -1, metrics
    assert metrics["navRight"] <= metrics["viewportWidth"] + 1, metrics
    assert len(metrics["targets"]) >= 2, metrics
    undersized = [
        target
        for target in metrics["targets"]
        if target["height"] < 40 or target["width"] < 44 or max(target["left"], 0) >= min(target["right"], metrics["viewportWidth"])
    ]
    assert undersized == []


def _assert_mobile_surface_motor_accessible(page: Page) -> None:
    _assert_no_horizontal_overflow(page)
    metrics = page.evaluate(
        """
        () => {
          const topbar = document.querySelector('[data-property-research-topnav]');
          const selectors = [
            '.pqx-check',
            '.pqx-mode-button',
            '.pqx-button',
            '.pqx-link-button',
            '.console-action',
            'button',
            'summary',
            'select',
            'textarea',
            'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
          ];
          const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
          const offenders = [];
          for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            const hiddenByClosedDetails = node.closest('details:not([open])') && !node.closest('summary');
            if (
              hiddenByClosedDetails ||
              rect.width <= 0 ||
              rect.height <= 0 ||
              style.visibility === 'hidden' ||
              style.display === 'none'
            ) {
              continue;
            }
            const text = String(node.textContent || node.getAttribute('aria-label') || node.getAttribute('name') || node.tagName || '').trim();
            const relaxed = node.matches('.pqx-tooltip, .pqx-account-menu-form button');
            const allowedHorizontalRail = node.closest('[data-property-mobile-step-rail], .pqx-primary-nav, .prd-primary-nav');
            if (allowedHorizontalRail && (rect.left < -1 || rect.right > window.innerWidth + 1)) {
              continue;
            }
            const minHeight = relaxed ? 40 : 44;
            const minWidth = relaxed ? 40 : 44;
            if (rect.height < minHeight || rect.width < minWidth || rect.left < -1 || rect.right > window.innerWidth + 1) {
              offenders.push({
                tag: node.tagName.toLowerCase(),
                className: String(node.className || '').slice(0, 80),
                text: text.slice(0, 80),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
              });
            }
          }
          return {
            topbarVisible: Boolean(topbar && topbar.getBoundingClientRect().height > 0),
            viewportWidth: window.innerWidth,
            bodyWidth: document.documentElement.scrollWidth,
            offenderCount: offenders.length,
            offenders: offenders.slice(0, 12),
          };
        }
        """
    )
    assert metrics["topbarVisible"] is True, metrics
    assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, metrics
    assert metrics["offenders"] == [], metrics


def _goto_with_browser_budget(page: Page, url: str, *, wait_until: str, budget_ms: int) -> tuple[object, int]:
    started = time.perf_counter()
    response = page.goto(url, wait_until=wait_until)
    duration_ms = int((time.perf_counter() - started) * 1000)
    assert response is not None and response.ok
    assert duration_ms <= budget_ms, {"url": url, "duration_ms": duration_ms, "budget_ms": budget_ms}
    return response, duration_ms


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


def _assert_dark_mode_surfaces_stay_readable(page: Page, selectors: list[str]) -> None:
    offenders = page.evaluate(
        """
        ({ selectors }) => {
          const parseColor = (value) => {
            const match = String(value || '').match(/rgba?\\(([^)]+)\\)/);
            if (!match) return null;
            const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
            if (parts.length < 3) return null;
            return { r: parts[0], g: parts[1], b: parts[2], a: parts.length >= 4 ? parts[3] : 1 };
          };
          const light = (color) => color && color.a >= 0.65 && color.r >= 242 && color.g >= 242 && color.b >= 238;
          const lightBackgroundImage = (value) => {
            const colors = String(value || '').match(/rgba?\\([^)]+\\)/g) || [];
            return colors.some((entry) => light(parseColor(entry)));
          };
          const visible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width >= 8 && rect.height >= 8 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const effectiveBackground = (node) => {
            let current = node;
            while (current && current.nodeType === Node.ELEMENT_NODE) {
              const color = parseColor(window.getComputedStyle(current).backgroundColor);
              if (color && color.a > 0.08) return color;
              current = current.parentElement;
            }
            return parseColor(window.getComputedStyle(document.body).backgroundColor);
          };
          const rows = [];
          const nodesBySelector = new Map();
          for (const selector of ['body *', ...selectors]) {
            for (const node of document.querySelectorAll(selector)) {
              const matchedSelectors = nodesBySelector.get(node) || [];
              matchedSelectors.push(selector);
              nodesBySelector.set(node, matchedSelectors);
            }
          }
          for (const [node, matchedSelectors] of nodesBySelector.entries()) {
              if (!visible(node)) continue;
              if (node.closest('svg, img, picture, video, canvas, [data-pqx-map-thumbnail]')) continue;
              const style = window.getComputedStyle(node);
              const background = effectiveBackground(node);
              const color = parseColor(style.color);
              const text = (node.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 96);
              const selector = matchedSelectors.find((entry) => entry !== 'body *') || node.tagName.toLowerCase();
              if (light(background) || lightBackgroundImage(style.backgroundImage)) {
                rows.push({
                  selector,
                  text,
                  background: style.backgroundColor,
                  backgroundImage: style.backgroundImage,
                  effectiveBackground: `rgba(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)}, ${background.a})`,
                  color: style.color,
                });
              }
              if (text && light(background) && light(color)) {
                rows.push({
                  selector: `${selector} (light text on light surface)`,
                  text,
                  background: style.backgroundColor,
                  effectiveBackground: `rgba(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)}, ${background.a})`,
                  color: style.color,
                });
              }
          }
          return rows;
        }
        """,
        {"selectors": selectors},
    )
    assert offenders == []


def _assert_disabled_auth_provider_rows_are_intentional(page: Page) -> None:
    rows = page.evaluate(
        """
        () => {
          const parseColor = (value) => {
            const match = String(value || '').match(/rgba?\\(([^)]+)\\)/);
            if (!match) return null;
            const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
            if (parts.length < 3) return null;
            return { r: parts[0], g: parts[1], b: parts[2], a: parts.length >= 4 ? parts[3] : 1 };
          };
          const light = (color) => color && color.a >= 0.65 && color.r >= 242 && color.g >= 242 && color.b >= 238;
          const effectiveBackground = (node) => {
            let current = node;
            while (current && current.nodeType === Node.ELEMENT_NODE) {
              const color = parseColor(window.getComputedStyle(current).backgroundColor);
              if (color && color.a > 0.08) return color;
              current = current.parentElement;
            }
            return parseColor(window.getComputedStyle(document.body).backgroundColor);
          };
          return Array.from(document.querySelectorAll('[data-auth-provider-card][data-auth-provider-state="disabled"]'))
            .map((card) => {
              const icon = card.querySelector('.auth-provider-icon');
              const button = card.querySelector('.btn[disabled]');
              const cardStyle = window.getComputedStyle(card);
              const iconStyle = icon ? window.getComputedStyle(icon) : null;
              const buttonStyle = button ? window.getComputedStyle(button) : null;
              return {
                provider: card.getAttribute('data-auth-provider') || '',
                opacity: Number.parseFloat(cardStyle.opacity || '1'),
                links: card.querySelectorAll('a[href]').length,
                buttonDisabled: Boolean(button && button.disabled),
                buttonCursor: buttonStyle ? buttonStyle.cursor : '',
                cardBackgroundLight: light(effectiveBackground(card)),
                iconBackgroundLight: icon ? light(effectiveBackground(icon)) : true,
                buttonBackgroundLight: button ? light(effectiveBackground(button)) : true,
              };
            });
        }
        """
    )
    assert rows, "the sign-in fixture should exercise at least one unavailable provider"
    for row in rows:
        assert row["opacity"] >= 0.99, row
        assert row["links"] == 0, row
        assert row["buttonDisabled"] is True, row
        assert row["buttonCursor"] == "not-allowed", row
        assert row["cardBackgroundLight"] is False, row
        assert row["iconBackgroundLight"] is False, row
        assert row["buttonBackgroundLight"] is False, row


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
        assert 'data-property-mobile-dock' not in content
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-pq-theater' in content
        assert 'data-workbench-results-table' in content
        page.locator("[data-workbench-row]:visible").first.wait_for(timeout=5000)
        assert page.locator("[data-workbench-row]").first.is_visible()
        assert page.locator("[data-workbench-row][data-candidate-packet-url]").first.is_visible()
        assert page.locator("body", has_text=re.compile(r"shortlisted homes|ranked homes", re.I)).is_visible()
        assert "Altbau near U6" in content
        assert "Family flat near Tiergarten" in content
        assert page.locator("body", has_text="360 ready").is_visible()
        assert page.locator("body", has_text="Open property").is_visible()
        assert "360 ready" in content
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        page.locator("[data-workbench-row]", has_text="Altbau near U6").locator(".pqx-result-title").click()
        assert "/app/research/" in page.url
        assert "run_id=run-42" in page.url
        assert page.locator("body", has_text="Altbau near U6").is_visible()
    finally:
        context.close()


def test_propertyquarry_result_thumbnail_opens_lazy_evidence_atlas(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    page: Page = context.new_page()
    indexed_requests: list[str] = []
    page.on(
        "request",
        lambda request: indexed_requests.append(request.url)
        if any(marker in request.url.lower() for marker in ("newspaper", "article-index", "provider-coverage", "evidence-index"))
        else None,
    )
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        row = page.locator("[data-workbench-row]", has_text="Altbau near U6").first
        row.wait_for()
        before_url = page.url
        row.locator("[data-pqx-atlas-open]").click()
        atlas = page.locator("[data-pqx-evidence-atlas]")
        expect(atlas).to_be_visible()
        expect(atlas.locator("[data-pqx-evidence-atlas-title]")).to_contain_text("Altbau near U6")
        expect(atlas.get_by_text("Searches read cached Teable/Postgres evidence rollups")).to_be_visible()
        expect(atlas.get_by_role("button", name="Media")).to_be_visible()
        expect(atlas.get_by_role("button", name="Fiber")).to_be_visible()
        expect(atlas.get_by_role("button", name="Visuals")).to_be_visible()
        assert page.url == before_url
        atlas.get_by_role("button", name="Media").click()
        media_card = atlas.locator("[data-pqx-evidence-card='media']")
        expect(media_card).to_be_visible()
        expect(media_card.get_by_text("Newspaper statistics must")).to_be_visible()
        atlas.get_by_role("button", name="Fiber").click()
        fiber_card = atlas.locator("[data-pqx-evidence-card='fiber']")
        expect(fiber_card).to_be_visible()
        expect(fiber_card.get_by_text("Fiber coverage must use")).to_be_visible()
        metrics = page.evaluate(
            """() => {
              const atlas = document.querySelector('[data-pqx-evidence-atlas]');
              const card = document.querySelector('[data-pqx-evidence-atlas-card]');
              const rail = document.querySelector('[data-pqx-evidence-layer-rail]');
              const rect = card ? card.getBoundingClientRect() : null;
              const railStyle = rail ? window.getComputedStyle(rail) : null;
              return {
                bodyWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                atlasOpen: Boolean(atlas && atlas.open),
                cardRight: rect ? rect.right : 0,
                cardBottom: rect ? rect.bottom : 0,
                viewportHeight: window.innerHeight,
                railOverflowX: railStyle ? railStyle.overflowX : '',
              };
            }"""
        )
        assert metrics["atlasOpen"] is True
        assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1
        assert metrics["cardRight"] <= metrics["viewportWidth"] + 1
        assert metrics["cardBottom"] <= metrics["viewportHeight"] + 1
        assert metrics["railOverflowX"] in {"auto", "scroll"}
        assert indexed_requests == []
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
        assert page.locator("[data-pqx-filtered-open]:visible").count() == 0
        screenshot_path = tmp_path / "propertyquarry-shortlist-dark-mode.png"
        page.screenshot(path=str(screenshot_path), full_page=False, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 20_000
    finally:
        context.close()


def test_propertyquarry_dark_mode_covers_public_and_management_surfaces(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    public_selectors = [
        ".topbar",
        ".mobile-nav a",
        ".panel",
        ".summary",
        ".preview-top",
        ".preview-main > section",
        ".nav-card",
        ".nav-card a",
        ".mini-card",
        ".pill",
        ".tier-card",
        ".tier-card *",
        ".access-panel",
        ".access-panel *",
        ".access-card",
        ".access-card *",
        ".access-feedback",
        ".auth-provider-card",
        ".auth-provider-card *",
        ".auth-provider-icon",
        ".auth-provider-card .btn",
        ".btn",
    ]
    app_selectors = [
        ".pqx-topbar",
        ".pqx-shell *",
        ".pqx-primary-nav a",
        ".pqx-run-chip",
        ".pqx-button:not(.primary)",
        ".pqx-link-button:not(.primary)",
        ".pqx-card",
        ".pqx-workflow-step",
        ".pqx-disclosure-summary",
        ".pqx-field input:not([type='checkbox'])",
        ".pqx-field select",
        ".pqx-what-matters-panel",
        ".pqx-pref-row",
        ".pqx-account-card",
        ".pqx-account-channel-option",
        ".pqx-account-channel-detail",
        ".pqx-account-channel-detail input",
        ".pqx-billing-card",
        ".pqx-automation-card",
        ".pqx-automation-thumbnail",
        ".pqx-automation-summary-card",
        ".pqx-result",
        ".pqx-result-fact",
        ".pqx-progress-button",
        ".pqx-reliability-strip",
        ".pqx-worker-strip",
        ".pqx-worker-lane",
        ".pqx-source-progress",
        ".pqx-empty",
        ".pq-pack-shell",
        ".pq-pack-topbar",
        ".pq-pack-button",
        ".pq-pack-panel",
        ".pq-pack-stat",
        ".pq-pack-summary-card",
        ".pq-pack-card",
        ".pq-pack-decision-card",
        ".pq-pack-input",
        ".pq-pack-check",
        ".pq-pack-pill",
        ".pq-pack-feedback",
        ".pq-pack-review-actions textarea",
        ".pq-pack-empty",
    ]

    public_context = _new_public_context(browser, mobile=False, width=1366, height=960)
    public_context.add_init_script("window.localStorage.setItem('propertyquarry.theme', 'dark');")
    try:
        public_page = public_context.new_page()
        for route, screenshot_name in (
            ("/sign-in", "propertyquarry-sign-in-dark-surfaces.png"),
            ("/sign-in?signing_in=1", "propertyquarry-sign-in-loading-dark-surfaces.png"),
            ("/register", "propertyquarry-register-dark-surfaces.png"),
            ("/", "propertyquarry-root-dark-surfaces.png"),
            ("/?home=1", "propertyquarry-home-dark-surfaces.png"),
            ("/pricing", "propertyquarry-pricing-dark-surfaces.png"),
            ("/product", "propertyquarry-product-dark-surfaces.png"),
            ("/docs", "propertyquarry-docs-dark-surfaces.png"),
            ("/integrations", "propertyquarry-integrations-dark-surfaces.png"),
            ("/privacy", "propertyquarry-privacy-dark-surfaces.png"),
            ("/terms", "propertyquarry-terms-dark-surfaces.png"),
            ("/support", "propertyquarry-support-dark-surfaces.png"),
            ("/imprint", "propertyquarry-imprint-dark-surfaces.png"),
            ("/cookies", "propertyquarry-cookies-dark-surfaces.png"),
            ("/subprocessors", "propertyquarry-subprocessors-dark-surfaces.png"),
            ("/refunds", "propertyquarry-refunds-dark-surfaces.png"),
            ("/disclaimers", "propertyquarry-disclaimers-dark-surfaces.png"),
        ):
            response = public_page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None and response.ok
            expect(public_page.locator("html")).to_have_attribute("data-pq-theme", "dark")
            _assert_dark_mode_surfaces_stay_readable(public_page, public_selectors)
            if route == "/sign-in":
                _assert_disabled_auth_provider_rows_are_intentional(public_page)
                _assert_visible_component_contrast(
                    public_page,
                    [
                        '[data-auth-provider-card][data-auth-provider-state="disabled"]',
                        '[data-auth-provider-card][data-auth-provider-state="disabled"] .auth-provider-icon',
                        '[data-auth-provider-card][data-auth-provider-state="disabled"] .btn',
                    ],
                    minimum_ratio=3.0,
                )
            public_shot = tmp_path / screenshot_name
            public_page.screenshot(path=str(public_shot), full_page=False, animations="disabled", caret="hide")
            assert public_shot.exists() and public_shot.stat().st_size > 20_000
    finally:
        public_context.close()

    app_context = _new_context(browser, mobile=False, width=1366, height=960)
    app_context.add_init_script("window.localStorage.setItem('propertyquarry.theme', 'dark');")
    _issue_browser_workspace_session(client=client, context=app_context, base_url=base_url)
    try:
        page = app_context.new_page()
        for route, screenshot_name in (
            ("/app/search", "propertyquarry-search-dark-surfaces.png"),
            ("/app/properties", "propertyquarry-properties-dark-surfaces.png"),
            ("/app/account", "propertyquarry-account-dark-surfaces.png"),
            ("/app/billing", "propertyquarry-billing-dark-surfaces.png"),
            ("/app/alerts", "propertyquarry-alerts-dark-surfaces.png"),
            ("/app/agents", "propertyquarry-agents-dark-surfaces.png"),
            ("/app/shortlist?run_id=run-42", "propertyquarry-shortlist-management-dark-surfaces.png"),
            ("/app/settings/plan", "propertyquarry-settings-plan-dark-surfaces.png"),
            ("/app/settings/usage", "propertyquarry-settings-usage-dark-surfaces.png"),
            ("/app/settings/support", "propertyquarry-settings-support-dark-surfaces.png"),
            ("/app/settings/trust", "propertyquarry-settings-trust-dark-surfaces.png"),
            ("/app/settings/google", "propertyquarry-settings-google-dark-surfaces.png"),
            ("/app/settings/access", "propertyquarry-settings-access-dark-surfaces.png"),
            ("/app/settings/invitations", "propertyquarry-settings-invitations-dark-surfaces.png"),
            ("/app/settings/outcomes", "propertyquarry-settings-outcomes-dark-surfaces.png"),
            ("/app/properties/packets", "propertyquarry-packets-dark-surfaces.png"),
        ):
            response = page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None
            if route == "/app/billing":
                assert int(response.status) == 503
                _assert_no_horizontal_overflow(page)
                _assert_propertyquarry_billing_fallback_page(page)
            else:
                assert response.ok
                expect(page.locator("html")).to_have_attribute("data-pq-theme", "dark")
                _assert_dark_mode_surfaces_stay_readable(page, app_selectors)
            screenshot = tmp_path / screenshot_name
            page.screenshot(path=str(screenshot), full_page=False, animations="disabled", caret="hide")
            assert screenshot.exists() and screenshot.stat().st_size > 20_000
    finally:
        app_context.close()


def test_propertyquarry_score_viewer_renders_compact_public_iframe(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_public_context(browser, mobile=False, width=1366, height=960)
    context.add_init_script("window.localStorage.setItem('propertyquarry.theme', 'dark');")
    try:
        page = context.new_page()
        response = page.goto(f"{base_url}/how-it-works/score?language=de&country=AT", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.locator("html")).to_have_attribute("data-pq-theme", "dark")
        page.locator(".pqx-score-viewer-shell").wait_for(state="visible")
        expect(page.locator(".pqx-score-viewer-frame iframe")).to_have_attribute(
            "src",
            re.compile(r"/v1/integrations/fliplink/documents/score-methodology\.pdf\?language=de&country=AT"),
        )
        _assert_no_horizontal_overflow(page)
        _assert_dark_mode_surfaces_stay_readable(
            page,
            [
                ".pqx-score-viewer-shell",
                ".pqx-score-viewer-card",
                ".pqx-score-viewer-meta span",
                ".pqx-score-viewer-frame",
            ],
        )
        screenshot_path = tmp_path / "propertyquarry-score-viewer-dark.png"
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
        assert 'data-property-mobile-dock' not in content
        page.locator("[data-workbench-row]:visible").first.wait_for(timeout=5000)
        if page.locator('[data-workbench-mobile-mode="results"]').count():
            assert page.locator('[data-workbench-mobile-mode="results"]').is_visible()
            assert page.locator('[data-workbench-mobile-mode="property"]').is_visible()
            mode_box = page.locator('[data-workbench-mobile-mode="results"]').bounding_box()
            assert mode_box is not None and mode_box["width"] <= 430
        _assert_mobile_topnav_tap_targets(page)
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
        page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").click()
        assert "/app/research/" in page.url
        assert "run_id=run-42" in page.url
        assert page.locator("body", has_text="Family flat near Tiergarten").is_visible()
    finally:
        context.close()


def test_propertyquarry_all_customer_app_surfaces_are_motor_accessible_on_phone(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    page: Page = context.new_page()
    routes = [
        "/app/search",
        "/app/shortlist?run_id=run-42",
        "/app/alerts",
        "/app/account",
        "/app/billing",
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
    ]
    try:
        for route in routes:
            response = page.goto(f"{base_url}{route}", wait_until="domcontentloaded")
            assert response is not None, route
            if route == "/app/billing":
                assert int(response.status) == 503, route
                _assert_no_horizontal_overflow(page)
                _assert_propertyquarry_billing_fallback_page(page)
                billing_back_link = page.get_by_role("link", name="Back to account")
                box = billing_back_link.bounding_box()
                assert box is not None and box["height"] >= 44 and box["width"] >= 44
                continue
            assert response.ok, route
            page.locator("[data-property-research-topnav]").wait_for(state="visible", timeout=5000)
            _assert_mobile_surface_motor_accessible(page)
            _assert_mobile_topnav_tap_targets(page)

        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="domcontentloaded")
        assert response is not None and response.ok
        packet_href = page.locator('a[href*="/app/research/"]').first.get_attribute("href")
        assert packet_href
        response = page.goto(packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator("[data-property-research-detail]").wait_for(state="visible", timeout=5000)
        _assert_mobile_surface_motor_accessible(page)
    finally:
        context.close()


def test_propertyquarry_soft_only_empty_state_uses_neutral_empty_state_copy(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
        response = page.goto(f"{base_url}/app/properties?run_id=run-active-empty", wait_until="networkidle")
        assert response is not None and response.ok
        page.wait_for_selector("[data-pqx-empty-results]", timeout=7000)
        expect(page.locator("[data-pqx-empty-results]")).to_contain_text(re.compile(r"No shortlist yet|Change one hard rule", re.I), timeout=5000)
        expect(page.locator("[data-pqx-empty-results]")).not_to_contain_text(re.compile(r"below the shortlist score|Lower shortlist score|Review scored homes", re.I), timeout=5000)
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
        assert page.locator("body", has_text="Quick take").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        page.locator("summary", has_text="Preferences").first.click()
        answered_button = page.locator('[data-object-followups] [data-object-followup-action="answered"]:visible').first
        expect(answered_button).to_be_visible()
        answered_button.scroll_into_view_if_needed()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            answered_button.click()
        update_response = update_response_info.value
        assert update_response.ok, update_response.text()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        assert page.locator("body", has_text="Watch-outs").is_visible()
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
        page.locator("summary", has_text="Preferences").first.click()
        answered_button = page.locator('[data-object-followups] [data-object-followup-action="answered"]:visible').first
        expect(answered_button).to_be_visible()
        answered_button.scroll_into_view_if_needed()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            answered_button.click()
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
        page.get_by_text("Preferences", exact=True).click()
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
        assert page.locator("body", has_text="Quick take").is_visible()
        assert page.locator("body", has_text="Next move").is_visible()
        assert page.locator("body", has_text="Preferences").is_visible()
    finally:
        context.close()


def test_propertyquarry_active_run_auto_polls_notifies_and_renders_empty_result_desk(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "selected_platforms": ["willhaben"],
            "min_match_score": 60,
        },
    )
    assert stored.status_code == 200, stored.text
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
        assert page.locator("body", has_text=re.compile("Change one hard rule|No shortlist yet", re.I)).is_visible()
        assert page.locator("body", has_text=re.compile("Lower shortlist score|below the shortlist score", re.I)).count() == 0
        ranking_slider = page.locator('[data-pqx-empty-results] [data-pqx-filter-slider][data-pqx-filter-field="min_match_score"]').first
        assert ranking_slider.is_visible()
        ranking_action = page.locator('[data-pqx-empty-results] [data-pqx-counterfactual-action-kind="ranking_bar"]').first
        assert ranking_action.is_visible()
        expect(ranking_action).to_have_text(re.compile(r"Use \d+/100|Turn bar off", re.I))
        ranking_slider.evaluate(
            """(node) => {
          node.value = '0';
          node.dispatchEvent(new Event('input', { bubbles: true }));
        }"""
        )
        expect(ranking_action).to_have_text("Turn bar off")
        assert page.evaluate("window.localStorage.getItem('pq-test-notification-title')") == "PropertyQuarry results are ready"
        assert "0 ranked homes" in str(page.evaluate("window.localStorage.getItem('pq-test-notification-body')"))
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_browser_alert_button_toggles_enabled_state(
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
          window.localStorage.setItem('pq-test-notification-permission-requests', '0');
          class FakeNotification {
            static permission = 'granted';
            static requestPermission = async () => {
              const current = Number(window.localStorage.getItem('pq-test-notification-permission-requests') || '0');
              window.localStorage.setItem('pq-test-notification-permission-requests', String(current + 1));
              return 'granted';
            };
            constructor() {
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
        browser_alerts = page.get_by_role("button", name="Browser alerts on")
        expect(browser_alerts).to_be_visible()
        browser_alerts.click()
        expect(page.get_by_role("button", name="Browser alerts off")).to_be_visible()
        assert page.evaluate("window.localStorage.getItem('propertyquarry.browserNotifications.enabled')") is None
        assert page.evaluate("window.localStorage.getItem('pq-test-notification-permission-requests')") == "0"
        page.get_by_role("button", name="Browser alerts off").click()
        expect(page.get_by_role("button", name="Browser alerts on")).to_be_visible()
        assert page.evaluate("window.localStorage.getItem('propertyquarry.browserNotifications.enabled')") == "1"
        assert page.evaluate("window.localStorage.getItem('pq-test-notification-permission-requests')") == "0"
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
        progress_text = progress_target.inner_text().strip()
        assert progress_text
        assert "selected sources" not in progress_text.lower()
        assert "source update" not in progress_text.lower()
        assert "source lanes" not in progress_text.lower()
        assert re.search(r"\bproviders?\b|\bprovider checks?\b", progress_text, flags=re.IGNORECASE)
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
        expect(page.get_by_role("navigation", name="PropertyQuarry sections")).to_be_visible()
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


def test_propertyquarry_account_mobile_exposes_direct_logout(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=True, width=390, height=844)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/account", wait_until="networkidle")
        assert response is not None and response.ok
        logout_form = page.locator("[data-account-page-sign-out]")
        expect(logout_form).to_be_visible()
        logout_button = logout_form.get_by_role("button", name="Log out")
        expect(logout_button).to_be_visible()
        metrics = logout_button.evaluate(
            """(button) => {
              const rect = button.getBoundingClientRect();
              return {
                top: rect.top,
                bottom: rect.bottom,
                width: rect.width,
                height: rect.height,
                viewportWidth: window.innerWidth,
                bodyWidth: document.documentElement.scrollWidth,
                label: button.textContent || '',
              };
            }"""
        )
        assert metrics["height"] >= 48, metrics
        assert metrics["width"] >= 160, metrics
        assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, metrics
        assert "Log out" in metrics["label"]

        logout_button.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(100)
        assert page.locator("[data-account-page-sign-out]").count() == 0
        assert page.locator(".pqx-account-menu > summary").count() == 0
    finally:
        context.close()


def test_propertyquarry_account_notifications_save_multi_channel_preferences_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=False)
    access_token = _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/account", wait_until="networkidle")
        assert response is not None and response.ok
        delivery_card = page.locator("#delivery")
        expect(delivery_card).to_be_visible()

        email_checkbox = delivery_card.locator('input[name="notification_channels"][value="email"]')
        telegram_checkbox = delivery_card.locator('input[name="notification_channels"][value="telegram"]')
        whatsapp_checkbox = delivery_card.locator('input[name="notification_channels"][value="whatsapp"]')
        whatsapp_phone = delivery_card.locator("#whatsappAiSupportPhone")

        expect(email_checkbox).to_be_checked()
        telegram_checkbox.uncheck()
        whatsapp_checkbox.check()
        whatsapp_phone.fill("+43 664 791 6419")

        with page.expect_navigation(wait_until="networkidle"):
            delivery_card.get_by_role("button", name="Save").click()

        assert "/app/account?notifications_saved=1#delivery" in page.url
        expect(email_checkbox).to_be_checked()
        expect(telegram_checkbox).not_to_be_checked()
        expect(whatsapp_checkbox).to_be_checked()
        expect(whatsapp_phone).to_have_value("+436647916419")

        original_workspace_cookie = client.cookies.get("ea_workspace_session")
        client.cookies.set("ea_workspace_session", access_token)
        export = client.get("/app/api/property/account/export")
        if original_workspace_cookie:
            client.cookies.set("ea_workspace_session", original_workspace_cookie)
        else:
            client.cookies.pop("ea_workspace_session", None)
        assert export.status_code == 200
        preferences = export.json()["delivery_preferences"]["property_notifications"]
        assert preferences["selected_channels"] == ["email", "whatsapp"]
        assert preferences["preferred_channel"] == "email"
        assert preferences["whatsapp_ai_support_phone"] == "+436647916419"
    finally:
        context.close()


def test_propertyquarry_account_notifications_have_dedicated_phone_layout(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=True, width=390, height=844)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/account#delivery", wait_until="networkidle")
        assert response is not None and response.ok
        delivery_card = page.locator("#delivery")
        expect(delivery_card).to_be_visible()
        delivery_card.evaluate("(node) => { node.open = true; }")
        delivery_card.locator('input[name="notification_channels"][value="whatsapp"]').check()

        metrics = page.evaluate(
            """() => {
                const options = document.querySelector('.pqx-account-channel-options');
                const rows = Array.from(document.querySelectorAll('.pqx-account-channel-option'));
                const details = Array.from(document.querySelectorAll('.pqx-account-channel-detail'))
                    .filter((node) => {
                        const style = window.getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                    });
                const inputs = details.flatMap((detail) => Array.from(detail.querySelectorAll('input')));
                const rowRects = rows.map((row) => row.getBoundingClientRect());
                const detailRects = details.map((detail) => detail.getBoundingClientRect());
                const inputRects = inputs.map((input) => input.getBoundingClientRect());
                return {
                    viewportWidth: window.innerWidth,
                    columns: options ? window.getComputedStyle(options).gridTemplateColumns.split(' ').filter(Boolean).length : 0,
                    rowCount: rows.length,
                    minRowHeight: Math.min(...rowRects.map((rect) => rect.height)),
                    maxRowRight: Math.max(...rowRects.map((rect) => rect.right)),
                    visibleDetailCount: details.length,
                    maxDetailRight: Math.max(...detailRects.map((rect) => rect.right)),
                    minInputHeight: Math.min(...inputRects.map((rect) => rect.height)),
                    maxInputRight: Math.max(...inputRects.map((rect) => rect.right)),
                    bodyWidth: document.documentElement.scrollWidth,
                };
            }"""
        )
        assert metrics["columns"] == 1, metrics
        assert metrics["rowCount"] >= 3, metrics
        assert metrics["minRowHeight"] >= 52, metrics
        assert metrics["visibleDetailCount"] >= 2, metrics
        assert metrics["minInputHeight"] >= 48, metrics
        assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, metrics
        assert metrics["maxRowRight"] <= metrics["viewportWidth"] + 1, metrics
        assert metrics["maxDetailRight"] <= metrics["viewportWidth"] + 1, metrics
        assert metrics["maxInputRight"] <= metrics["viewportWidth"] + 1, metrics
    finally:
        context.close()


@pytest.mark.parametrize("route", ["/app/account", "/app/alerts"])
def test_propertyquarry_mobile_generic_folds_only_keep_one_panel_open(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    route: str,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=True, width=390, height=844)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}{route}", wait_until="networkidle")
        assert response is not None and response.ok

        metrics = page.evaluate(
            """() => {
                const folds = Array.from(document.querySelectorAll('details.pqx-mobile-fold'));
                folds.forEach((node) => { node.open = false; });
                if (folds.length >= 2) {
                    const summaries = folds.map((node) => node.querySelector('summary')).filter(Boolean);
                    summaries[0]?.click();
                    summaries[1]?.click();
                }
                return {
                    foldCount: folds.length,
                    openCount: folds.filter((node) => node.open).length,
                    secondOpen: Boolean(folds[1]?.open),
                    labels: folds.map((node) => (
                        node.querySelector('summary strong, summary h2')?.textContent || ''
                    ).trim()).filter(Boolean),
                };
            }"""
        )
        assert metrics["foldCount"] >= 2, metrics
        assert metrics["openCount"] == 1, metrics
        assert metrics["secondOpen"] is True, metrics
    finally:
        context.close()


@pytest.mark.parametrize("route", ["/app/settings/google", "/app/settings/support", "/app/settings/access", "/app/settings/invitations"])
def test_propertyquarry_mobile_settings_disclosures_keep_one_panel_open(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    route: str,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    context = _new_context(browser, mobile=True, width=390, height=844)
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}{route}", wait_until="networkidle")
        assert response is not None and response.ok

        metrics = page.evaluate(
            """() => {
                const disclosures = Array.from(document.querySelectorAll('.is-settings-surface details.object-disclosure'));
                const labelFor = (node) => (
                    node?.querySelector('summary strong, summary h2')?.textContent || ''
                ).trim();
                const openBefore = disclosures.filter((node) => node.open);
                const initialOpenLabel = labelFor(openBefore[0] || null);
                const target = disclosures.find((node) => labelFor(node) && labelFor(node) !== initialOpenLabel) || null;
                target?.querySelector('summary')?.click();
                const openAfter = disclosures.filter((node) => node.open);
                return {
                    disclosureCount: disclosures.length,
                    initialOpenCount: openBefore.length,
                    initialOpenLabel,
                    finalOpenCount: openAfter.length,
                    finalOpenLabel: labelFor(openAfter[0] || null),
                    labels: disclosures.map((node) => labelFor(node)).filter(Boolean),
                    sidebarLabelPresent: disclosures.some((node) => node.classList.contains('object-sidebar-disclosure')),
                };
            }"""
        )
        assert metrics["disclosureCount"] >= 2, metrics
        assert metrics["initialOpenCount"] == 1, metrics
        assert metrics["initialOpenLabel"], metrics
        if route == "/app/settings/google":
            assert metrics["initialOpenLabel"] == "Google sign-in", metrics
        if route == "/app/settings/access":
            assert metrics["initialOpenLabel"] in {"Create an access link", "Live access links"}, metrics
        if route == "/app/settings/invitations":
            assert metrics["initialOpenLabel"] == "Invite another person", metrics
        assert metrics["finalOpenCount"] == 1, metrics
        assert metrics["finalOpenLabel"], metrics
        assert metrics["finalOpenLabel"] != metrics["initialOpenLabel"], metrics
        assert metrics["sidebarLabelPresent"] is True or route in {"/app/settings/access", "/app/settings/invitations"}, metrics
    finally:
        context.close()


def test_propertyquarry_account_and_billing_hide_redundant_top_actions(
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
        response = page.goto(f"{base_url}/app/account", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.get_by_role("button", name="Dark mode")).to_be_visible()
        assert page.get_by_role("button", name=re.compile("Browser alerts", re.I)).count() == 0
        assert page.locator(".pqx-top-actions").get_by_role("link", name="Review").count() == 0
        assert page.locator(".pqx-top-actions").get_by_role("link", name="Edit search").count() == 0
        expect(page.locator(".pqx-account-menu")).to_have_count(0)
        expect(page.get_by_role("button", name="Log out")).to_be_visible()
        expect(page.get_by_role("link", name="Billing account")).to_be_visible()

        response = page.goto(f"{base_url}/app/billing", wait_until="networkidle")
        assert response is not None
        assert int(response.status) == 503
        _assert_propertyquarry_billing_fallback_page(page)
        expect(page.locator(".pqx-top-actions")).to_have_count(0)
        expect(page.locator(".pqx-account-menu")).to_have_count(0)
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
        assert preference_box and 108 <= preference_box["width"] <= 180
        assert distance_box and 88 <= distance_box["width"] <= 180
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
              const firstList = panel.querySelector('[data-what-matters-group][open] .pqx-pref-list');
              const firstListStyle = firstList ? window.getComputedStyle(firstList) : null;
              return {
                panelHeight: panelRect.height,
                panelWidth: panelRect.width,
                panelScrollWidth: panel.scrollWidth,
                bottomGap: panelRect.bottom - lastBottom,
                rowWidths,
                firstListOverflowY: firstListStyle ? firstListStyle.overflowY : '',
                firstListScrolls: firstList ? firstList.scrollHeight > firstList.clientHeight + 2 : false,
              };
            }
            """
        )
        assert float(mobile_metrics["panelHeight"]) <= 1600.0, mobile_metrics
        assert float(mobile_metrics["panelScrollWidth"]) <= float(mobile_metrics["panelWidth"]) + 1.0, mobile_metrics
        assert float(mobile_metrics["bottomGap"]) <= 28.0, mobile_metrics
        assert mobile_metrics["firstListOverflowY"] in {"auto", "scroll"}, mobile_metrics
        assert mobile_metrics["firstListScrolls"] is True, mobile_metrics
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
    mobile = _new_context(browser, mobile=True, width=390, height=844)
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
        keyword_states = (
            ("playground nearby", "nice_to_have"),
            ("Baumarkt nearby", "important"),
            ("shopping center nearby", "important"),
            ("flaniermeile nearby", "important"),
            ("theatre nearby", "important"),
        )
        for keyword, state in keyword_states:
            row = page.locator(f'[data-keyword-priority-row][data-keyword-value="{keyword}"]')
            row.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
            row.locator("[data-keyword-preference-select]").select_option(state)
            expect(row.locator("[data-keyword-distance-select]")).to_be_enabled()
            expect(row).to_have_attribute("data-preference-state", state)
        school_parent = page.locator('[data-school-priority-row][data-school-value="volksschule"]')
        school_parent.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
        school_parent.locator("[data-school-preference-select]").select_option("important")
        expect(school_parent).to_have_attribute("data-preference-state", "important")
        school_child = page.locator('[data-school-priority-row][data-school-value="ganztags_volksschule"]')
        expect(school_child).to_be_visible()
        expect(school_child).to_have_attribute("data-school-parent-active", "true")
        expect(school_parent).to_have_attribute("data-school-family-active", "true")
        school_distance_rows = (
            ("kindergarten", "nice_to_have", ""),
            ("ganztags_volksschule", "important", "volksschule"),
            ("halbtags_volksschule", "nice_to_have", "volksschule"),
        )
        kindergarten_parent = page.locator('[data-school-priority-row][data-school-value="kindergarten"]')
        kindergarten_parent.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
        kindergarten_parent.locator("[data-school-preference-select]").select_option("important")
        for value, state, parent_value in school_distance_rows:
            row = page.locator(f'[data-school-priority-row][data-school-value="{value}"]')
            row.evaluate("node => node.closest('details[data-what-matters-group]')?.setAttribute('open', '')")
            expect(row).to_be_visible()
            if parent_value:
                expect(row).to_have_attribute("data-school-parent-active", "true")
            row.locator("[data-school-preference-select]").select_option(state)
            expect(row.locator("[data-school-distance-select]")).to_be_enabled()
            expect(row).to_have_attribute("data-school-distance-enabled", "true")
            distance_field = row.locator("[data-school-distance-select]").get_attribute("data-distance-field")
            assert distance_field == f"max_distance_to_{value}_m"
        section = page.locator('[data-what-matters-group="daily_life"]')
        expect(section).to_have_attribute("data-active-distance-rows", "true")
        active_distance_row = page.locator('[data-keyword-priority-row][data-keyword-value="Baumarkt nearby"]')
        active_distance_row.scroll_into_view_if_needed()
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
              const offenders = Array.from(group?.querySelectorAll('*') || [])
                .map((node) => {
                  const rect = node.getBoundingClientRect();
                  return {
                    tag: node.tagName,
                    cls: node.className || '',
                    attr: node.getAttribute('data-keyword-value') || node.getAttribute('data-school-value') || '',
                    width: rect.width,
                    rightOver: groupRect ? rect.right - groupRect.right : 0,
                    scrollWidth: node.scrollWidth || 0,
                    clientWidth: node.clientWidth || 0,
                  };
                })
                .filter((item) => item.rightOver > 1 || item.scrollWidth > item.clientWidth + 1)
                .sort((a, b) => Math.max(b.rightOver, b.scrollWidth - b.clientWidth) - Math.max(a.rightOver, a.scrollWidth - a.clientWidth))
                .slice(0, 8);
              return {
                groupWidth: groupRect ? groupRect.width : 0,
                groupScrollWidth: group ? group.scrollWidth : 0,
                listWidth: listRect ? listRect.width : 0,
                listScrollWidth: list ? list.scrollWidth : 0,
                offenders,
              };
            }
            """
        )
        assert float(group_overflow["groupScrollWidth"]) <= float(group_overflow["groupWidth"]) + 1.0, json.dumps(group_overflow)
        assert float(group_overflow["listScrollWidth"]) <= float(group_overflow["listWidth"]) + 1.0, json.dumps(group_overflow)
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
                assert float(control["width"]) >= 90.0, row
                if inner_width >= 900:
                    assert float(control["width"]) <= 126.0, row
                assert float(control["left"]) >= -1.0, row
                assert float(control["right"]) >= -1.0, row
        school_rows = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('[data-school-priority-row][data-school-distance-enabled="true"]'))
              .filter((row) => row.offsetParent !== null)
              .map((row) => {
                const rowRect = row.getBoundingClientRect();
                const preference = row.querySelector('[data-school-preference-select]');
                const distance = row.querySelector('[data-school-distance-select]');
                const preferenceRect = preference?.getBoundingClientRect();
                const distanceRect = distance?.getBoundingClientRect();
                return {
                  value: row.getAttribute('data-school-value') || '',
                  rowWidth: rowRect.width,
                  rowScrollWidth: row.scrollWidth,
                  preferenceValue: preference?.value || '',
                  distanceDisabled: Boolean(distance?.disabled),
                  distanceField: distance?.getAttribute('data-distance-field') || '',
                  preferenceWidth: preferenceRect ? preferenceRect.width : 0,
                  distanceWidth: distanceRect ? distanceRect.width : 0,
                  preferenceLeft: preferenceRect ? preferenceRect.left - rowRect.left : -999,
                  distanceRight: distanceRect ? rowRect.right - distanceRect.right : -999,
                };
              })
            """
        )
        school_by_value = {row["value"]: row for row in school_rows}
        for value in ("kindergarten", "ganztags_volksschule", "halbtags_volksschule"):
            row = school_by_value.get(value)
            assert row, school_rows
            assert row["distanceDisabled"] is False, row
            assert row["distanceField"] == f"max_distance_to_{value}_m", row
            assert float(row["rowScrollWidth"]) <= float(row["rowWidth"]) + 1.0, row
            assert float(row["preferenceWidth"]) >= 90.0, row
            assert float(row["distanceWidth"]) >= 90.0, row
            if inner_width >= 900:
                assert float(row["preferenceWidth"]) <= 126.0, row
                assert float(row["distanceWidth"]) <= 126.0, row
            assert float(row["preferenceLeft"]) >= -1.0, row
            assert float(row["distanceRight"]) >= -1.0, row
        playground_clip = page.evaluate(
            """
            () => {
              const row = document.querySelector('[data-keyword-priority-row][data-keyword-value="playground nearby"]');
              const preference = row?.querySelector('[data-keyword-preference-select]');
              const select = row?.querySelector('[data-keyword-distance-select]');
              const list = row?.closest('.pqx-pref-list');
              row?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
              const rowRect = row?.getBoundingClientRect();
              const preferenceRect = preference?.getBoundingClientRect();
              const selectRect = select?.getBoundingClientRect();
              const listRect = list?.getBoundingClientRect();
              return {
                rowTop: rowRect ? rowRect.top : 0,
                rowBottom: rowRect ? rowRect.bottom : 0,
                preferenceWidth: preferenceRect ? preferenceRect.width : 0,
                preferenceRight: preferenceRect && rowRect ? rowRect.right - preferenceRect.right : -999,
                preferenceValue: preference?.value || '',
                selectWidth: selectRect ? selectRect.width : 0,
                selectTop: selectRect ? selectRect.top : 0,
                selectBottom: selectRect ? selectRect.bottom : 0,
                selectRight: selectRect && rowRect ? rowRect.right - selectRect.right : -999,
                listTop: listRect ? listRect.top : 0,
                listBottom: listRect ? listRect.bottom : 0,
                viewportWidth: window.innerWidth,
              };
            }
            """
        )
        assert playground_clip["preferenceValue"] == "nice_to_have", playground_clip
        assert playground_clip["selectTop"] >= playground_clip["rowTop"] - 1, playground_clip
        assert playground_clip["selectBottom"] <= playground_clip["rowBottom"] + 1, playground_clip
        assert playground_clip["selectTop"] >= playground_clip["listTop"] - 1, playground_clip
        assert playground_clip["selectBottom"] <= playground_clip["listBottom"] + 1, playground_clip
        if int(playground_clip["viewportWidth"]) >= 900:
            assert 90 <= float(playground_clip["preferenceWidth"]) <= 126, playground_clip
            assert 90 <= float(playground_clip["selectWidth"]) <= 126, playground_clip
            assert float(playground_clip["preferenceRight"]) >= -1.0, playground_clip
            assert float(playground_clip["selectRight"]) >= -1.0, playground_clip
        if int(page.evaluate("window.innerWidth")) <= 760:
            playground_viewport = page.evaluate(
                """
                () => {
                  const row = document.querySelector('[data-keyword-priority-row][data-keyword-value="playground nearby"]');
                  const preference = row?.querySelector('[data-keyword-preference-select]');
                  const distance = row?.querySelector('[data-keyword-distance-select]');
                  const group = row?.closest('[data-what-matters-group]');
                  row?.scrollIntoView({ block: 'center', inline: 'nearest' });
                  const rowRect = row?.getBoundingClientRect();
                  const distanceRect = distance?.getBoundingClientRect();
                  return {
                    preferenceValue: preference?.value || '',
                    distanceDisabled: Boolean(distance?.disabled),
                    distanceHeight: distanceRect ? distanceRect.height : 0,
                    distanceLeft: distanceRect ? distanceRect.left : -999,
                    distanceRight: distanceRect ? distanceRect.right : 999,
                    distanceTop: distanceRect ? distanceRect.top : -999,
                    distanceBottom: distanceRect ? distanceRect.bottom : 999,
                    rowTop: rowRect ? rowRect.top : -999,
                    rowBottom: rowRect ? rowRect.bottom : 999,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight,
                    bottomSafeTop: window.innerHeight,
                    groupOpen: Boolean(group?.open),
                    groupActive: group?.getAttribute('data-active-distance-rows') || '',
                    groupMobileActive: group?.getAttribute('data-mobile-distance-control-active') || '',
                  };
                }
                """
            )
            assert playground_viewport["preferenceValue"] == "nice_to_have", playground_viewport
            assert playground_viewport["distanceDisabled"] is False, playground_viewport
            assert float(playground_viewport["distanceHeight"]) >= 44.0, playground_viewport
            assert float(playground_viewport["distanceLeft"]) >= -1.0, playground_viewport
            assert float(playground_viewport["distanceRight"]) <= float(playground_viewport["viewportWidth"]) + 1.0, playground_viewport
            assert float(playground_viewport["distanceTop"]) >= 0.0, playground_viewport
            assert float(playground_viewport["distanceBottom"]) <= float(playground_viewport["bottomSafeTop"]) - 4.0, playground_viewport
            assert playground_viewport["groupOpen"] is True, playground_viewport
            assert playground_viewport["groupActive"] == "true", playground_viewport
            assert playground_viewport["groupMobileActive"] == "true", playground_viewport

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
        progress_text = progress_target.inner_text().strip()
        assert progress_text
        assert "selected sources" not in progress_text.lower()
        assert "source update" not in progress_text.lower()
        assert "source lanes" not in progress_text.lower()
        assert re.search(r"\bproviders?\b|\bprovider checks?\b", progress_text, flags=re.IGNORECASE)
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
        assert page.locator("body", has_text=re.compile(r"shortlisted homes|ranked homes", re.I)).is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        packet_href = page.locator('a[href*="/app/research/"]').first.get_attribute("href")
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="domcontentloaded")
        assert response is not None and response.ok
        assert page.locator(".prd-media-frame").is_visible()
        assert "Open the space before you read the rest" not in page.content()
        _assert_research_packet_360_first(page, min_stage_height=190, max_stage_height=380)
        page.wait_for_load_state("networkidle")
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
        assert page.get_by_text("Quick take").first.is_visible()
        decision_fit = page.evaluate(
            """
            () => {
              const panel = document.querySelector('[data-object-feedback]');
              const note = document.querySelector('[data-object-feedback-note]');
              const tune = Array.from(document.querySelectorAll('.prd-feedback-details'))
                .find((node) => (node.textContent || '').includes('Refine decision'));
              const rect = panel ? panel.getBoundingClientRect() : null;
              const noteRect = note ? note.getBoundingClientRect() : null;
              return {
                viewportHeight: window.innerHeight,
                panelHeight: rect ? Math.round(rect.height) : 0,
                noteHeight: noteRect ? Math.round(noteRect.height) : 0,
                fineTuneOpen: tune ? Boolean(tune.open) : true,
              };
            }
            """
        )
        assert 0 < decision_fit["panelHeight"] <= decision_fit["viewportHeight"] - 96
        assert decision_fit["noteHeight"] <= 86
        assert decision_fit["fineTuneOpen"] is False
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        page.evaluate(
            """
            () => {
              window.localStorage.setItem('propertyquarry.theme', 'dark');
              document.documentElement.setAttribute('data-pq-theme', 'dark');
            }
            """
        )
        page.wait_for_timeout(80)
        dark_backgrounds = page.evaluate(
            """
            () => {
              const selectors = ['.pq-appbar', '.prd-panel', '.prd-media-frame', '.prd-media-badge'];
              return selectors
                .filter((selector) => document.querySelector(selector))
                .map((selector) => {
                  const element = document.querySelector(selector);
                  return [selector, window.getComputedStyle(element).backgroundColor];
                });
            }
            """
        )
        assert dark_backgrounds
        for selector, background in dark_backgrounds:
            assert not str(background).startswith(("rgb(255", "rgba(255")), f"{selector} stayed light in dark mode: {background}"
        _assert_dark_mode_surfaces_stay_readable(
            page,
            [
                ".pq-appbar",
                ".prd-hero",
                ".prd-hero *",
                ".prd-panel",
                ".prd-panel *",
                ".prd-body",
                ".prd-body *",
                ".prd-actions",
                ".prd-actions *",
                ".prd-gallery-card",
                ".prd-gallery-card *",
            ],
        )
        dark_screenshot_path = tmp_path / "property_research_detail_first_screen_dark.png"
        page.screenshot(path=str(dark_screenshot_path), full_page=False, animations="disabled", caret="hide")
        assert dark_screenshot_path.exists() and dark_screenshot_path.stat().st_size > 20_000
    finally:
        context.close()


def test_propertyquarry_shortlist_and_research_have_browser_performance_budget(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=900)
    page: Page = context.new_page()
    try:
        _, shortlist_ms = _goto_with_browser_budget(
            page,
            f"{base_url}/app/shortlist?run_id=run-42",
            wait_until="networkidle",
            budget_ms=3200,
        )
        assert page.locator("body", has_text=re.compile(r"shortlisted homes|ranked homes", re.I)).is_visible()
        expect(page.locator("[data-property-app-shell]")).to_be_visible()
        expect(page.locator('a[href*="/app/research/"]').first).to_be_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        packet_href = page.locator('a[href*="/app/research/"]').first.get_attribute("href")
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        _, research_ms = _goto_with_browser_budget(
            page,
            packet_url,
            wait_until="networkidle",
            budget_ms=3600,
        )
        expect(page.locator("[data-property-research-detail]")).to_be_visible()
        expect(page.locator("[data-research-ranking-list]")).to_be_visible()
        expect(page.locator(".prd-media-frame")).to_be_visible()
        _assert_research_packet_360_first(page, min_stage_height=190, max_stage_height=380)
        _assert_no_horizontal_overflow(page)
        assert shortlist_ms > 0 and research_ms > 0
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
    visual_status_polls = 0

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
                    "eta_label": "about 10 min",
                    "progress_pct": 18,
                    "poll_after_seconds": 1,
                    "delivery_status": "skipped",
                    "blocked_reason": "",
                    "source_ref": visual_requests[-1].get("source_ref", ""),
                    "run_id": visual_requests[-1].get("run_id", ""),
                    "candidate_ref": visual_requests[-1].get("candidate_ref", ""),
                }
            ),
        )

    page.route("**/app/api/signals/willhaben/property-tour", _capture_visual_request)
    def _capture_visual_status(route) -> None:
        nonlocal visual_status_polls
        visual_status_polls += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "generated_at": "2026-06-21T10:00:03+00:00",
                    "status": "ready" if visual_status_polls >= 1 else "processing",
                    "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/listing-url-only-loft",
                    "title": "Listing URL only loft",
                    "request_kind": "flythrough",
                    "tour_url": "",
                    "tour_status": "pending",
                    "flythrough_url": "https://propertyquarry.com/tours/files/listing-url-only-loft/walkthrough.mp4",
                    "flythrough_status": "ready",
                    "status_label": "Open walkthrough",
                    "status_detail": "Walkthrough is ready on this page.",
                    "eta_label": "",
                    "progress_pct": 100,
                    "poll_after_seconds": 0,
                    "source_ref": "willhaben:listing-url-only-loft",
                    "run_id": "run-42",
                    "candidate_ref": "listing-url-only-loft",
                }
            ),
        )

    page.route("**/app/api/signals/property/visual-status?**", _capture_visual_status)
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
              const headline = document.querySelector('.prd-headline');
              const visualConsole = document.querySelector('.prd-visual-console');
              const summaryGrid = document.querySelector('.prd-current-read .prd-summary-grid');
              const summaryBoxes = Array.from(document.querySelectorAll('.prd-current-read .prd-summary-box'));
              const shell = document.querySelector('[data-property-research-detail]');
              const feedback = document.querySelector('[data-object-feedback]');
              const sections = document.querySelector('.prd-sections');
              const decision = document.querySelector('.prd-decision-workspace');
              const secondaryDetails = Array.from(document.querySelectorAll('[data-prd-mobile-secondary]'));
              const fineTune = Array.from(document.querySelectorAll('.prd-feedback-details'))
                .find((node) => (node.textContent || '').includes('Refine decision'));
              const optionalNote = Array.from(document.querySelectorAll('.prd-feedback-details'))
                .find((node) => (node.querySelector('summary')?.textContent || '').trim() === 'Add an optional note');
              const nextStepDrawer = Array.from(document.querySelectorAll('.prd-feedback-details'))
                .find((node) => (node.querySelector('summary')?.textContent || '').trim() === 'Next step');
              const savebar = document.querySelector('.prd-decision-savebar');
              const heroRect = hero ? hero.getBoundingClientRect() : null;
              const bodyRect = body ? body.getBoundingClientRect() : null;
              const mediaRect = media ? media.getBoundingClientRect() : null;
              const headlineRect = headline ? headline.getBoundingClientRect() : null;
              const visualConsoleRect = visualConsole ? visualConsole.getBoundingClientRect() : null;
              const summaryGridStyle = summaryGrid ? getComputedStyle(summaryGrid) : null;
              const summaryBoxRects = summaryBoxes.map((card) => card.getBoundingClientRect());
              const actionsStyle = actions ? getComputedStyle(actions) : null;
              const shellRect = shell ? shell.getBoundingClientRect() : null;
              const feedbackRect = feedback ? feedback.getBoundingClientRect() : null;
              const feedbackStyle = feedback ? getComputedStyle(feedback) : null;
              const sectionsRect = sections ? sections.getBoundingClientRect() : null;
              const decisionRect = decision ? decision.getBoundingClientRect() : null;
              const savebarRect = savebar ? savebar.getBoundingClientRect() : null;
              return {
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                shellWidth: shellRect ? shellRect.width : 0,
                heroWidth: heroRect ? heroRect.width : 0,
                heroBottom: heroRect ? Math.round(heroRect.bottom) : 0,
                bodyTop: bodyRect ? Math.round(bodyRect.top) : 0,
                mediaHeight: mediaRect ? Math.round(mediaRect.height) : 0,
                headlineTop: headlineRect ? Math.round(headlineRect.top) : 0,
                visualConsoleTop: visualConsoleRect ? Math.round(visualConsoleRect.top) : 0,
                actionsDisplay: actionsStyle ? actionsStyle.display : '',
                actionsColumns: actionsStyle ? actionsStyle.gridTemplateColumns : '',
                summaryDisplay: summaryGridStyle ? summaryGridStyle.display : '',
                summaryColumns: summaryGridStyle ? summaryGridStyle.gridTemplateColumns.split(' ').filter(Boolean).length : 0,
                summaryScrollWidth: summaryGrid ? summaryGrid.scrollWidth : 0,
                summaryClientWidth: summaryGrid ? summaryGrid.clientWidth : 0,
                summaryBoxCount: summaryBoxes.length,
                summaryShortestCard: Math.min(...summaryBoxRects.map((rect) => Math.round(rect.height))),
                summaryTallestCard: Math.max(0, ...summaryBoxRects.map((rect) => Math.round(rect.height))),
                summaryMaxRight: Math.max(0, ...summaryBoxRects.map((rect) => Math.round(rect.right))),
                decisionTop: decisionRect ? Math.round(decisionRect.top) : 0,
                sectionsTop: sectionsRect ? Math.round(sectionsRect.top) : 0,
                secondarySectionCount: secondaryDetails.length,
                closedSecondarySections: secondaryDetails.filter((node) => !node.open).length,
                visibleSecondarySummaries: secondaryDetails.filter((node) => {
                  const summary = node.querySelector('summary');
                  if (!summary) return false;
                  const rect = summary.getBoundingClientRect();
                  return rect.width > 0 && rect.height > 0 && getComputedStyle(summary).display !== 'none';
                }).length,
                feedbackHeight: feedbackRect ? Math.round(feedbackRect.height) : 0,
                feedbackBottom: feedbackRect ? Math.round(feedbackRect.bottom) : 0,
                feedbackOverflowY: feedbackStyle ? feedbackStyle.overflowY : '',
                feedbackScrolls: feedback ? feedback.scrollHeight > feedback.clientHeight + 2 : false,
                fineTuneOpen: fineTune ? Boolean(fineTune.open) : true,
                optionalNoteExists: Boolean(optionalNote),
                nextStepDrawerExists: Boolean(nextStepDrawer),
                savebarBottom: savebarRect ? Math.round(savebarRect.bottom) : 0,
              };
            }
            """
        )
        assert layout["shellWidth"] <= layout["viewportWidth"] + 1
        assert layout["heroWidth"] <= layout["viewportWidth"] + 1
        assert layout["heroBottom"] > 0
        assert layout["bodyTop"] > layout["heroBottom"]
        assert 150 <= layout["mediaHeight"] <= 320
        assert 0 < layout["headlineTop"] < layout["visualConsoleTop"]
        assert layout["actionsDisplay"] == "grid"
        assert "px" in layout["actionsColumns"]
        assert layout["summaryDisplay"] == "grid"
        assert 1 <= layout["summaryColumns"] <= 2
        assert layout["summaryScrollWidth"] <= layout["summaryClientWidth"] + 1
        assert layout["summaryBoxCount"] == 4
        if layout["summaryShortestCard"] > 0:
            assert layout["summaryShortestCard"] >= 68
            assert layout["summaryTallestCard"] <= 112
        assert layout["summaryMaxRight"] <= layout["viewportWidth"] + 1
        assert 0 < layout["decisionTop"] < layout["sectionsTop"]
        assert layout["secondarySectionCount"] >= 2
        assert layout["closedSecondarySections"] >= 2
        assert layout["visibleSecondarySummaries"] >= 2
        assert 180 <= layout["feedbackHeight"] <= min(420, layout["viewportHeight"] - 54)
        assert 0 < layout["savebarBottom"] <= layout["feedbackBottom"] + 1
        assert layout["feedbackOverflowY"] == "visible"
        assert layout["feedbackScrolls"] is False
        assert layout["fineTuneOpen"] is False
        assert layout["optionalNoteExists"] is False
        assert layout["nextStepDrawerExists"] is False
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
        expect(page.locator("[data-prd-visual-eta]")).to_contain_text("about 10 min")
        rail_fill = page.locator("[data-prd-visual-progress]").first.get_attribute("style") or ""
        assert "18%" in rail_fill
        page.wait_for_timeout(1300)
        assert visual_status_polls >= 1
        expect(page.locator("[data-prd-visual-status]")).to_contain_text("ready on this page")
        updated_button = page.get_by_role("button", name=re.compile("Open walkthrough", re.I)).first
        expect(updated_button).to_be_visible()
        updated_href = str(updated_button.get_attribute("data-pw-visual-href") or "").strip()
        assert updated_href
        assert "/tours/files/" in updated_href
        assert updated_href.endswith("/walkthrough.mp4")
    finally:
        context.close()


def test_propertyquarry_visual_request_does_not_invent_eta_before_backend_supplies_one(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    visual_requests: list[dict[str, object]] = []

    def _capture_visual_request(route) -> None:
        payload = route.request.post_data_json or {}
        visual_requests.append(payload if isinstance(payload, dict) else {})
        time.sleep(0.8)
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
                    "eta_label": "",
                    "progress_pct": 18,
                    "poll_after_seconds": 0,
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
        row = page.locator("[data-workbench-row]", has_text="Listing URL only loft").first
        row.wait_for(timeout=5000)
        packet_href = str(row.get_attribute("data-candidate-packet-url") or "").strip()
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        request_button = page.get_by_role("button", name=re.compile("Request walkthrough", re.I)).first
        request_button.click()
        page.wait_for_timeout(900)
        expect(page.locator("[data-prd-visual-status]")).to_contain_text("queued after your request", timeout=5000)
        assert (page.locator("[data-prd-visual-eta]").inner_text() or "").strip() == ""
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

        page.locator('[data-checkbox-group-clear-all="location_query"]').click()
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
        assert match_slider.get_attribute("min") == "0"
        assert match_slider.get_attribute("max") == "60"
        assert match_slider.get_attribute("data-range-selectable-max") == "35"
        assert match_slider.get_attribute("data-range-visual-max") == "60"
        tooltip = match_slider.get_attribute("title") or ""
        assert "stay in the run" in tooltip.lower()
        assert "off" in tooltip.lower()
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "Off"
        assert page.locator('[data-current-plan-cap]').filter(has_text="Plan cap 35").count() >= 1
        floorplan_filter = page.locator('input[name="require_floorplan"]')
        assert floorplan_filter.is_visible()
        assert page.locator('label', has_text="Serious listings only").count() >= 1
        match_slider.evaluate("(node) => { node.value = '60'; node.dispatchEvent(new Event('input', { bubbles: true })); }")
        assert match_slider.input_value() == "35"
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "35/60"
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
        mobile_page.select_option('select[name="country_code"]', "AT")
        mobile_page.select_option('select[name="region_code"]', "vienna")
        mobile_page.wait_for_function(
            """() => document.querySelector('[data-property-field-name="location_query"]')?.dataset.locationMapAvailable === 'true'"""
        )
        mobile_page.screenshot(path=str(mobile_shot), full_page=True)
        assert mobile_shot.exists()
        mobile_metrics = mobile_page.evaluate(
            """() => {
                const rail = document.querySelector('[data-property-mobile-step-rail]');
                const legacyDock = document.querySelector('[data-property-mobile-action-dock], [data-property-mobile-dock], .pq-mobile-nav');
                const drawer = document.querySelector('[data-workbench-brief-drawer]');
                const result = document.querySelector('[data-workbench-row]');
                const thumb = result?.querySelector('.pqx-thumb');
                const topbar = document.querySelector('.pqx-topbar');
                const topbarRect = topbar ? topbar.getBoundingClientRect() : null;
                const topnav = topbar?.querySelector('.pqx-primary-nav') || null;
                const topnavRect = topnav ? topnav.getBoundingClientRect() : null;
                const topnavFirst = topnav?.querySelector('a, span') || null;
                const topnavFirstRect = topnavFirst ? topnavFirst.getBoundingClientRect() : null;
                const topLaunch = topbar?.querySelector('[data-property-start-top]') || null;
                const topLaunchRect = topLaunch ? topLaunch.getBoundingClientRect() : null;
                const locationField = document.querySelector('[data-property-field-name="location_query"]');
                const stepActions = document.querySelector('.pqx-step-head-actions');
                const stepActionsRect = stepActions ? stepActions.getBoundingClientRect() : null;
                const stepNextButton = stepActions?.querySelector('[data-property-step-next]') || null;
                const stepNextRect = stepNextButton ? stepNextButton.getBoundingClientRect() : null;
                const stepSaveButton = stepActions?.querySelector('[data-property-save-top]') || null;
                const stepSaveRect = stepSaveButton ? stepSaveButton.getBoundingClientRect() : null;
                const stepStatus = stepActions?.querySelector('[data-property-launch-status]') || null;
                const stepStatusRect = stepStatus ? stepStatus.getBoundingClientRect() : null;
                const firstField = document.querySelector('.pqx-shell[data-pqx-surface="search"] .pqx-form-body > .pqx-field:not([hidden])');
                const firstFieldRect = firstField ? firstField.getBoundingClientRect() : null;
                const drawerScrollTopInitial = drawer ? drawer.scrollTop : 0;
                const areaRows = Array.from(locationField?.querySelectorAll('[data-pqx-check-grid="location_query"] .pqx-check') || []);
                const areaGrid = locationField?.querySelector('[data-pqx-check-grid="location_query"]') || null;
                const areaSummary = document.querySelector('[data-location-selected-summary]');
                const areaMapButton = locationField?.querySelector('[data-location-mode-button="map"]') || null;
                const areaListButton = locationField?.querySelector('[data-location-mode-button="list"]') || null;
                const areaMapButtonRect = areaMapButton ? areaMapButton.getBoundingClientRect() : null;
                const areaListButtonRect = areaListButton ? areaListButton.getBoundingClientRect() : null;
                const areaMapLaunch = locationField?.querySelector('[data-location-map-launch]') || null;
                const areaMapOpen = locationField?.querySelector('[data-location-map-open]') || null;
                const areaMapOpenRect = areaMapOpen ? areaMapOpen.getBoundingClientRect() : null;
                const areaSelectAllButton = locationField?.querySelector('[data-checkbox-group-select-all="location_query"]') || null;
                const areaClearButton = locationField?.querySelector('[data-checkbox-group-clear-all="location_query"]') || null;
                const areaDialog = locationField?.querySelector('[data-location-map-dialog]') || null;
                const availableScrollY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
                const requestedScrollY = Math.min(220, availableScrollY);
                window.scrollTo(0, requestedScrollY);
                const pageScrollBeforeMap = Math.round(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0);
                if (areaMapButton) areaMapButton.click();
                const areaModeInMapValue = locationField ? String(locationField.getAttribute('data-location-mode') || '') : '';
                const areaMapAvailableValue = locationField ? String(locationField.getAttribute('data-location-map-available') || '') : '';
                const areaGridDisplayInMapValue = areaGrid ? window.getComputedStyle(areaGrid).display : '';
                const areaMapLaunchDisplayValue = areaMapLaunch ? window.getComputedStyle(areaMapLaunch).display : '';
                const areaSelectAllDisplayInMapValue = areaSelectAllButton ? window.getComputedStyle(areaSelectAllButton).display : '';
                const areaClearDisplayInMapValue = areaClearButton ? window.getComputedStyle(areaClearButton).display : '';
                if (areaMapOpen) areaMapOpen.click();
                const areaMap = areaDialog?.querySelector('[data-location-map-picker]') || null;
                const areaMapViewport = areaDialog?.querySelector('[data-location-map-viewport]') || null;
                const areaDistricts = Array.from(areaDialog?.querySelectorAll('[data-location-map-district]') || []);
                const areaZoomButtons = Array.from(areaDialog?.querySelectorAll('[data-location-map-zoom]') || []);
                const areaCloseButtons = Array.from(areaDialog?.querySelectorAll('[data-location-map-close]') || []);
                const dialogLockOpen = document.documentElement.dataset.pqxLocationMapOpen === 'true';
                const htmlOverflowOpen = document.documentElement.style.overflow || '';
                const bodyOverflowOpen = document.body.style.overflow || '';
                const bodyPositionOpen = document.body.style.position || '';
                const bodyTopOpen = document.body.style.top || '';
                const railStyle = rail ? window.getComputedStyle(rail) : null;
                const summaryStyle = areaSummary ? window.getComputedStyle(areaSummary) : null;
                const areaMapDisplayValue = areaMap ? window.getComputedStyle(areaMap).display : '';
                const resultRect = result ? result.getBoundingClientRect() : null;
                const thumbRect = thumb ? thumb.getBoundingClientRect() : null;
                const mapRect = areaMap ? areaMap.getBoundingClientRect() : null;
                const mapViewportRect = areaMapViewport ? areaMapViewport.getBoundingClientRect() : null;
                const firstDistrict = areaDistricts[0] || null;
                if (firstDistrict) firstDistrict.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                const selectedDistrict = document.querySelector('[data-location-map-district].is-selected');
                const selectedInput = document.querySelector('input[name="location_query"]:checked');
                const selectedFill = selectedDistrict ? window.getComputedStyle(selectedDistrict).fill : '';
                const firstDistrictPath = firstDistrict ? String(firstDistrict.getAttribute('d') || '') : '';
                const mapLayer = areaDialog?.querySelector('[data-location-map-layer]') || null;
                const zoomToggle = areaDialog?.querySelector('[data-location-map-zoom="reset"]') || null;
                const initialTransform = String(mapLayer?.getAttribute('transform') || '');
                if (zoomToggle) zoomToggle.click();
                const zoomedTransform = String(mapLayer?.getAttribute('transform') || '');
                if (zoomToggle) zoomToggle.click();
                const parseScale = (transform) => {
                    const match = String(transform || '').match(/scale\\(([^)]+)\\)/i);
                    const value = match ? Number(match[1]) : 0;
                    return Number.isFinite(value) ? value : 0;
                };
                let areaPinchZoomChanged = false;
                if (areaMapViewport && mapLayer && typeof PointerEvent === 'function') {
                    const viewportRect = areaMapViewport.getBoundingClientRect();
                    const centerX = viewportRect.left + viewportRect.width / 2;
                    const centerY = viewportRect.top + viewportRect.height / 2;
                    const beforePinch = String(mapLayer.getAttribute('transform') || '');
                    const dispatchPinchPointer = (type, pointerId, clientX, clientY, isPrimary) => {
                        areaMapViewport.dispatchEvent(new PointerEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            composed: true,
                            pointerId,
                            pointerType: 'touch',
                            isPrimary,
                            clientX,
                            clientY,
                        }));
                    };
                    dispatchPinchPointer('pointerdown', 1, centerX - 26, centerY, true);
                    dispatchPinchPointer('pointerdown', 2, centerX + 26, centerY, false);
                    dispatchPinchPointer('pointermove', 1, centerX - 58, centerY, true);
                    dispatchPinchPointer('pointermove', 2, centerX + 58, centerY, false);
                    dispatchPinchPointer('pointerup', 1, centerX - 58, centerY, true);
                    dispatchPinchPointer('pointerup', 2, centerX + 58, centerY, false);
                    const afterPinch = String(mapLayer.getAttribute('transform') || '');
                    areaPinchZoomChanged = parseScale(afterPinch) > parseScale(beforePinch) + 0.08;
                }
                const dialogWasOpen = Boolean(areaDialog && areaDialog.open);
                const closeButton = areaDialog?.querySelector('[data-location-map-close]') || null;
                if (closeButton) closeButton.click();
                const dialogLockAfterClose = document.documentElement.dataset.pqxLocationMapOpen === 'true';
                const bodyOverflowAfterClose = document.body.style.overflow || '';
                const htmlOverflowAfterClose = document.documentElement.style.overflow || '';
                const bodyPositionAfterClose = document.body.style.position || '';
                const pageScrollAfterClose = Math.round(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0);
                if (areaListButton) areaListButton.click();
                const areaSelectAllDisplayAfterListValue = areaSelectAllButton ? window.getComputedStyle(areaSelectAllButton).display : '';
                const areaClearDisplayAfterListValue = areaClearButton ? window.getComputedStyle(areaClearButton).display : '';
                const areaRowsAfterList = Array.from(locationField?.querySelectorAll('[data-pqx-check-grid="location_query"] .pqx-check') || []);
                const areaRects = areaRowsAfterList.map((node) => node.getBoundingClientRect());
                const areaStyle = areaRowsAfterList[0] ? window.getComputedStyle(areaRowsAfterList[0]) : null;
                const areaGridStyle = areaGrid ? window.getComputedStyle(areaGrid) : null;
                if (areaGrid) {
                    areaGrid.scrollTop = areaGrid.scrollHeight;
                }
                const lastAreaRect = areaRowsAfterList.length ? areaRowsAfterList[areaRowsAfterList.length - 1].getBoundingClientRect() : null;
                const scrolledGridRect = areaGrid ? areaGrid.getBoundingClientRect() : null;
                return {
                    bodyWidth: document.documentElement.scrollWidth,
                    viewportWidth: window.innerWidth,
                    topbarRight: topbarRect ? topbarRect.right : 0,
                    topnavScrollWidth: topnav ? topnav.scrollWidth : 0,
                    topnavClientWidth: topnav ? topnav.clientWidth : 0,
                    topnavFirstLeft: topnavFirstRect ? topnavFirstRect.left : 0,
                    topLaunchWidth: topLaunchRect ? topLaunchRect.width : 0,
                    topLaunchRight: topLaunchRect ? topLaunchRect.right : 0,
                        drawerScrollTopBeforeInteraction: drawerScrollTopInitial,
                    railOverflowX: railStyle ? railStyle.overflowX : '',
                    railScrollWidth: rail ? rail.scrollWidth : 0,
                    railClientWidth: rail ? rail.clientWidth : 0,
                    railPosition: railStyle ? railStyle.position : '',
                    legacyDockVisible: Boolean(legacyDock && legacyDock.getBoundingClientRect().height > 0),
                    viewportHeight: window.innerHeight,
                    resultWidth: resultRect ? resultRect.width : 0,
                    thumbWidth: thumbRect ? thumbRect.width : 0,
                    areaModeInMap: areaModeInMapValue,
                    areaMapButtonText: areaMapButton ? areaMapButton.textContent || '' : '',
                    areaListButtonText: areaListButton ? areaListButton.textContent || '' : '',
                    areaMapButtonHeight: areaMapButtonRect ? areaMapButtonRect.height : 0,
                    areaListButtonHeight: areaListButtonRect ? areaListButtonRect.height : 0,
                    stepActionsHeight: stepActionsRect ? stepActionsRect.height : 0,
                    stepNextWidth: stepNextRect ? stepNextRect.width : 0,
                    stepSaveWidth: stepSaveRect ? stepSaveRect.width : 0,
                    stepSaveHeight: stepSaveRect ? stepSaveRect.height : 0,
                    stepActionsBottom: stepActionsRect ? stepActionsRect.bottom : 0,
                    stepStatusTop: stepStatusRect ? stepStatusRect.top : 0,
                    stepSaveTop: stepSaveRect ? stepSaveRect.top : 0,
                    firstFieldTopBeforeInteraction: firstFieldRect ? firstFieldRect.top : 0,
                    areaMapAvailable: areaMapAvailableValue,
                    areaGridDisplayInMap: areaGridDisplayInMapValue,
                    areaMapLaunchDisplay: areaMapLaunchDisplayValue,
                    areaMapOpenText: areaMapOpen ? areaMapOpen.textContent || '' : '',
                    areaMapOpenHeight: areaMapOpenRect ? areaMapOpenRect.height : 0,
                    areaSelectAllDisplayInMap: areaSelectAllDisplayInMapValue,
                    areaClearDisplayInMap: areaClearDisplayInMapValue,
                    areaDialogOpen: dialogWasOpen,
                    areaCloseButtonCount: areaCloseButtons.length,
                    dialogLockOpen,
                    htmlOverflowOpen,
                    bodyOverflowOpen,
                    bodyPositionOpen,
                    bodyTopOpen,
                    dialogLockAfterClose,
                    bodyOverflowAfterClose,
                    htmlOverflowAfterClose,
                    bodyPositionAfterClose,
                    pageScrollBeforeMap,
                    pageScrollAfterClose,
                    areaRowCount: areaRowsAfterList.length,
                    areaRowMinHeight: areaRects.length ? Math.min(...areaRects.map((rect) => rect.height)) : 0,
                    areaRowsClearOfViewport: areaRects.filter((rect) => rect.top >= 0 && rect.bottom <= window.innerHeight - 4).length,
                    areaRowMaxRight: areaRects.length ? Math.max(...areaRects.map((rect) => rect.right)) : 0,
                    areaRowGridColumns: areaStyle ? areaStyle.gridTemplateColumns : '',
                    areaRowBorderRadius: areaStyle ? areaStyle.borderRadius : '',
                    areaModeAfterList: locationField ? String(locationField.getAttribute('data-location-mode') || '') : '',
                    areaGridDisplayAfterList: areaGridStyle ? areaGridStyle.display : '',
                    areaSelectAllDisplayAfterList: areaSelectAllDisplayAfterListValue,
                    areaClearDisplayAfterList: areaClearDisplayAfterListValue,
                    areaGridOverflowY: areaGridStyle ? areaGridStyle.overflowY : '',
                    areaGridColumns: areaGridStyle ? areaGridStyle.gridTemplateColumns : '',
                    areaGridColumnCount: areaGridStyle ? areaGridStyle.gridTemplateColumns.split(' ').filter(Boolean).length : 0,
                    areaSummaryDisplay: summaryStyle ? summaryStyle.display : '',
                    areaSummaryText: areaSummary ? areaSummary.textContent || '' : '',
                    areaMapDisplay: areaMapDisplayValue,
                    areaMapHeight: mapRect ? mapRect.height : 0,
                    areaMapRight: mapRect ? mapRect.right : 0,
                    areaMapViewportHeight: mapViewportRect ? mapViewportRect.height : 0,
                    areaDistrictCount: areaDistricts.length,
                    areaZoomButtonCount: areaZoomButtons.length,
                    areaButtonZoomChanged: Boolean(zoomToggle && mapLayer && zoomedTransform !== initialTransform && zoomedTransform.includes('scale(')),
                    areaPinchZoomChanged,
                    firstDistrictPathLooksReal: firstDistrictPath.startsWith('M') && firstDistrictPath.split('L').length >= 8 && !firstDistrictPath.includes(' Q '),
                    selectedDistrictFill: selectedFill,
                    selectedMapMatchesInput: Boolean(selectedDistrict && selectedInput && selectedDistrict.getAttribute('data-location-value') === selectedInput.value),
                    areaGridScrolls: areaGrid ? areaGrid.scrollHeight > areaGrid.clientHeight + 2 : false,
                    areaGridBottomAfterScroll: scrolledGridRect ? scrolledGridRect.bottom : 0,
                    lastAreaBottomAfterScroll: lastAreaRect ? lastAreaRect.bottom : 0,
                    lastAreaTopAfterScroll: lastAreaRect ? lastAreaRect.top : 0,
                };
            }"""
        )
        assert mobile_metrics["bodyWidth"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["topbarRight"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["topnavScrollWidth"] >= mobile_metrics["topnavClientWidth"]
        assert mobile_metrics["topnavFirstLeft"] >= -1
        assert 44 <= mobile_metrics["topLaunchWidth"] <= 96
        assert mobile_metrics["topLaunchRight"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["drawerScrollTopBeforeInteraction"] <= 2
        assert mobile_metrics["railOverflowX"] in {"auto", "scroll"}
        assert mobile_metrics["railScrollWidth"] >= mobile_metrics["railClientWidth"]
        assert mobile_metrics["railPosition"] == "sticky"
        assert mobile_metrics["legacyDockVisible"] is False
        assert mobile_metrics["resultWidth"] <= mobile_metrics["viewportWidth"] + 1
        if mobile_metrics["thumbWidth"]:
            assert 84 <= mobile_metrics["thumbWidth"] <= 96
        assert mobile_metrics["areaModeInMap"] == "map"
        assert mobile_metrics["areaMapButtonText"].strip() == "Map"
        assert mobile_metrics["areaListButtonText"].strip() == "List"
        assert mobile_metrics["areaMapButtonHeight"] >= 52
        assert mobile_metrics["areaListButtonHeight"] >= 52
        assert mobile_metrics["stepActionsHeight"] <= 112
        assert mobile_metrics["stepNextWidth"] >= 120
        assert 88 <= mobile_metrics["stepSaveWidth"] <= 180
        assert 36 <= mobile_metrics["stepSaveHeight"] <= 46
        assert mobile_metrics["firstFieldTopBeforeInteraction"] >= mobile_metrics["stepActionsBottom"] + 4
        assert mobile_metrics["stepSaveTop"] <= mobile_metrics["stepStatusTop"]
        assert mobile_metrics["areaMapAvailable"] == "true"
        assert mobile_metrics["areaGridDisplayInMap"] == "none"
        assert mobile_metrics["areaMapLaunchDisplay"] != "none"
        assert "Open district map" in mobile_metrics["areaMapOpenText"]
        assert mobile_metrics["areaMapOpenHeight"] >= 60
        assert mobile_metrics["areaSelectAllDisplayInMap"] == "none"
        assert mobile_metrics["areaClearDisplayInMap"] == "none"
        assert mobile_metrics["areaDialogOpen"] is True
        assert mobile_metrics["areaCloseButtonCount"] >= 2
        assert mobile_metrics["dialogLockOpen"] is True
        assert mobile_metrics["htmlOverflowOpen"] == "hidden"
        assert mobile_metrics["bodyOverflowOpen"] == "hidden"
        assert mobile_metrics["bodyPositionOpen"] == "fixed"
        assert float(str(mobile_metrics["bodyTopOpen"]).replace("px", "") or 0) <= 0
        assert mobile_metrics["dialogLockAfterClose"] is False
        assert mobile_metrics["bodyOverflowAfterClose"] != "hidden"
        assert mobile_metrics["htmlOverflowAfterClose"] != "hidden"
        assert mobile_metrics["bodyPositionAfterClose"] != "fixed"
        assert abs(float(mobile_metrics["pageScrollAfterClose"]) - float(mobile_metrics["pageScrollBeforeMap"])) <= 2.0
        assert mobile_metrics["areaRowCount"] >= 6
        assert mobile_metrics["areaRowMinHeight"] >= 48
        assert mobile_metrics["areaRowsClearOfViewport"] >= 2
        assert mobile_metrics["areaRowMaxRight"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["areaModeAfterList"] == "list"
        assert mobile_metrics["areaGridDisplayAfterList"] != "none"
        assert mobile_metrics["areaSelectAllDisplayAfterList"] != "none"
        assert mobile_metrics["areaClearDisplayAfterList"] != "none"
        assert mobile_metrics["areaGridColumnCount"] == 1
        assert "34px" in mobile_metrics["areaRowGridColumns"]
        assert mobile_metrics["areaRowBorderRadius"] != "0px"
        assert mobile_metrics["areaSummaryDisplay"] != "none"
        assert "district" in mobile_metrics["areaSummaryText"].lower()
        assert mobile_metrics["areaMapDisplay"] == "grid"
        assert mobile_metrics["areaMapHeight"] >= 340
        assert mobile_metrics["areaMapRight"] <= mobile_metrics["viewportWidth"] + 1
        assert mobile_metrics["areaMapViewportHeight"] >= 260
        assert mobile_metrics["areaDistrictCount"] >= 6
        assert mobile_metrics["areaZoomButtonCount"] == 3
        assert mobile_metrics["areaButtonZoomChanged"] is True
        assert mobile_metrics["areaPinchZoomChanged"] is True
        assert mobile_metrics["firstDistrictPathLooksReal"] is True
        assert mobile_metrics["selectedMapMatchesInput"] is True
        assert "209" in mobile_metrics["selectedDistrictFill"] or "rgb" in mobile_metrics["selectedDistrictFill"]
        assert mobile_metrics["areaGridOverflowY"] in {"auto", "scroll"}
        assert mobile_metrics["areaGridBottomAfterScroll"] <= mobile_metrics["viewportHeight"] + 1
        assert mobile_metrics["lastAreaBottomAfterScroll"] <= mobile_metrics["viewportHeight"] + 1
        assert mobile_metrics["lastAreaTopAfterScroll"] >= 0
        _assert_no_horizontal_overflow(mobile_page)
    finally:
        desktop.close()
        mobile.close()


def test_propertyquarry_desktop_district_map_click_selects_shape_and_zoom_toggles(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=860)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="networkidle")
        assert response is not None and response.ok
        page.select_option('select[name="country_code"]', "AT")
        page.select_option('select[name="region_code"]', "vienna")
        page.wait_for_function(
            """() => document.querySelector('[data-property-field-name="location_query"]')?.dataset.locationMapAvailable === 'true'"""
        )
        page.locator('[data-location-mode-button="map"]').click()
        page.locator("[data-location-map-open]").click()
        district = page.locator("[data-location-map-district]").first
        district.wait_for(state="visible")
        value = str(district.get_attribute("data-location-value") or "")
        assert value
        before_checked = page.evaluate(
            """(value) => {
              const input = document.querySelector(`input[name="location_query"][value="${CSS.escape(value)}"]`);
              return Boolean(input && input.checked);
            }""",
            value,
        )
        box = district.bounding_box()
        assert box is not None
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_function(
            """([value, beforeChecked]) => {
              const input = document.querySelector(`input[name="location_query"][value="${CSS.escape(value)}"]`);
              return Boolean(input) && input.checked !== beforeChecked;
            }""",
            arg=[value, before_checked],
        )
        assert district.evaluate("(node) => node.classList.contains('is-selected')") is (not before_checked)

        layer = page.locator("[data-location-map-layer]")
        initial_transform = str(layer.get_attribute("transform") or "")
        zoom_toggle = page.locator('[data-location-map-zoom="reset"]')
        zoom_toggle.click()
        page.wait_for_function(
            """(initialTransform) => {
              const layer = document.querySelector('[data-location-map-layer]');
              return layer && String(layer.getAttribute('transform') || '') !== initialTransform;
            }""",
            arg=initial_transform,
        )
        zoomed_transform = str(layer.get_attribute("transform") or "")
        assert "scale(" in zoomed_transform and zoomed_transform != initial_transform
        expect(zoom_toggle).to_have_text(re.compile("fit", re.I))
        zoom_toggle.click()
        expect(zoom_toggle).to_have_text(re.compile("1x", re.I))
        assert "scale(1)" in str(layer.get_attribute("transform") or "")
    finally:
        context.close()


def test_propertyquarry_search_desktop_wheel_scroll_recovers_from_bottom(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=620)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="networkidle")
        assert response is not None and response.ok
        drawer = page.locator("[data-workbench-brief-drawer]")
        drawer.wait_for(state="visible")
        box = drawer.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        max_scroll = float(drawer.evaluate("(node) => Math.max(0, node.scrollHeight - node.clientHeight)"))
        scrollable = max_scroll > 0
        assert scrollable is True

        for _ in range(8):
            page.mouse.wheel(0, 720)
            page.wait_for_timeout(25)
        bottom_scroll = float(drawer.evaluate("(node) => node.scrollTop"))
        assert bottom_scroll >= max(8.0, max_scroll * 0.65)

        for _ in range(8):
            page.mouse.wheel(0, -720)
            page.wait_for_timeout(25)
        recovered_scroll = float(drawer.evaluate("(node) => node.scrollTop"))
        assert recovered_scroll <= max(2.0, bottom_scroll * 0.35)
    finally:
        context.close()


def test_propertyquarry_search_launch_strips_cross_country_provider_selection(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=900)
    page: Page = context.new_page()
    observed: dict[str, object] = {}
    try:
        def _capture_preferences(route):
            observed["preferences"] = route.request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "saved"}),
            )

        def _capture_run(route):
            observed["run"] = route.request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"run_id": "run-cross-country-provider"}),
            )

        page.route("**/v1/onboarding/property-search/preferences", _capture_preferences)
        page.route("**/app/api/property/search-runs**", _capture_run)
        response = page.goto(f"{base_url}/app/search", wait_until="networkidle")
        assert response is not None and response.ok
        page.select_option('select[name="country_code"]', "AT")
        page.evaluate(
            """
            () => {
              const grid = document.querySelector('[data-pqx-check-grid="selected_platforms"]');
              const stale = document.createElement('input');
              stale.type = 'checkbox';
              stale.name = 'selected_platforms';
              stale.value = 'otodom';
              stale.checked = true;
              stale.setAttribute('data-country-code', 'PL');
              grid?.appendChild(stale);
            }
            """
        )
        page.locator("[data-property-start-top]").click()
        expect(page).to_have_url(re.compile("run-cross-country-provider"), timeout=10000)

        preferences = observed.get("preferences")
        run = observed.get("run")
        assert isinstance(preferences, dict)
        assert isinstance(run, dict)
        assert preferences["country_code"] == "AT"
        assert "otodom" not in preferences.get("selected_platforms", [])
        assert "otodom" not in run.get("selected_platforms", [])
        assert "otodom" not in run.get("property_preferences", {}).get("selected_platforms", [])
    finally:
        context.close()


def test_propertyquarry_country_switch_replaces_out_of_market_provider_selection(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "Berlin",
            "selected_platforms": ["immoscout_de", "immowelt"],
        },
    )
    assert stored.status_code == 200, stored.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False, width=1440, height=900)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/search", wait_until="networkidle")
        assert response is not None and response.ok
        checked_before = page.locator('input[name="selected_platforms"]:checked')
        expect(checked_before).to_have_count(2)
        checked_before_values = page.eval_on_selector_all(
            'input[name="selected_platforms"]:checked',
            "(nodes) => nodes.map((node) => ({ value: node.value, country: node.getAttribute('data-country-code') || '' }))",
        )
        assert {row["value"] for row in checked_before_values} == {"immoscout_de", "immowelt"}

        page.select_option('select[name="country_code"]', "AT")
        page.wait_for_function(
            """
            () => {
              const checked = Array.from(document.querySelectorAll('input[name="selected_platforms"]:checked'));
              if (!checked.length) return false;
              const values = checked.map((node) => String(node.value || '').trim());
              return values.includes('willhaben') && !values.includes('immoscout_de') && !values.includes('immowelt');
            }
            """
        )

        checked_after = page.locator('input[name="selected_platforms"]:checked')
        expect(checked_after).to_have_count(3)
        checked_values = page.eval_on_selector_all(
            'input[name="selected_platforms"]:checked',
            "(nodes) => nodes.map((node) => ({ value: node.value, country: node.getAttribute('data-country-code') || '' }))",
        )
        assert "willhaben" in {row["value"] for row in checked_values}
        assert "immoscout_de" not in {row["value"] for row in checked_values}
        assert "immowelt" not in {row["value"] for row in checked_values}
        assert {str(row["country"] or "").upper() for row in checked_values} == {"AT"}
    finally:
        context.close()


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
                nonOverlayPreviewKinds: [...document.querySelectorAll('.pqx-automation-thumbnail')]
                  .map((thumb) => String(thumb.getAttribute('data-scope-preview-kind') || ''))
                  .filter((kind) => kind !== 'osm_district_overlay'),
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
        assert layout["nonOverlayPreviewKinds"] == []
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
        ("/app/shortlist?run_id=run-42", "Shortlist", "propertyquarry-shortlist-mobile.png"),
        ("/app/agents", "Saved searches", "propertyquarry-agents-mobile.png"),
        ("/app/alerts", "Alerts", "propertyquarry-alerts-mobile.png"),
        ("/app/account", "Account", "propertyquarry-account-mobile.png"),
        ("/app/billing", "Billing", "propertyquarry-billing-mobile.png"),
        ("/app/settings/google", "Google", "propertyquarry-google-settings-mobile.png"),
        ("/app/settings/access", "Access", "propertyquarry-access-settings-mobile.png"),
        ("/app/settings/usage", "Usage", "propertyquarry-usage-settings-mobile.png"),
        ("/app/settings/support", "Support", "propertyquarry-support-settings-mobile.png"),
        ("/app/settings/trust", "Trust", "propertyquarry-trust-settings-mobile.png"),
        ("/app/settings/invitations", "Invitations", "propertyquarry-invitations-settings-mobile.png"),
    ]
    try:
        page = context.new_page()
        for route, mobile_mode_name, screenshot_name in routes:
            response = page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None
            _assert_no_horizontal_overflow(page)
            if route == "/app/billing":
                assert int(response.status) == 503
                _assert_propertyquarry_billing_fallback_page(page)
                expect(page.locator("[data-property-mobile-dock]")).to_have_count(0)
                expect(page.locator('nav[aria-label="PropertyQuarry sections"]')).to_have_count(0)
                expect(page.locator("[data-pqx-launch-top]")).to_have_count(0)
                screenshot = tmp_path / screenshot_name
                page.screenshot(path=str(screenshot), full_page=True, animations="disabled", caret="hide")
                assert screenshot.exists() and screenshot.stat().st_size > 14_000
                continue
            assert response.ok
            _assert_property_shell_visual_gates(page, max_appbar_height=130)

            expect(page.locator("[data-property-mobile-dock]")).to_have_count(0)
            if route in {"/app/agents", "/app/alerts", "/app/account"} or route.startswith("/app/shortlist"):
                expect(page.locator('nav[aria-label="PropertyQuarry sections"]').first).to_be_hidden()
                expect(page.locator(".pqx-topbar")).to_be_visible()
            else:
                expect(page.locator('nav[aria-label="PropertyQuarry sections"]').first).to_be_visible()
            if page.get_by_role("button", name=mobile_mode_name).count():
                expect(page.get_by_role("button", name=mobile_mode_name)).to_be_visible()
            else:
                expect(page.locator("body", has_text=mobile_mode_name)).to_be_visible()
            _assert_mobile_topnav_tap_targets(page)
            expect(page.locator("[data-pqx-launch-top]")).to_have_count(0)
            density = page.evaluate(
                """() => {
                    const visibleCards = Array.from(document.querySelectorAll('.pqx-card, .pqx-panel, .pqx-result, .pqx-account-action-card, .pqx-billing-card, .pqx-billing-summary-card, .pqx-automation-card'))
                        .filter((node) => {
                            const rect = node.getBoundingClientRect();
                            const style = window.getComputedStyle(node);
                            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                        });
                    const heavyShadows = visibleCards.filter((node) => window.getComputedStyle(node).boxShadow !== 'none');
                    const appbar = document.querySelector('.pqx-topbar');
                    const brand = document.querySelector('.pqx-brand');
                    const themeToggle = document.querySelector('[data-pqx-theme-toggle]');
                    const accountSummary = document.querySelector('.pqx-account-menu summary');
                    const logoutButton = document.querySelector('[data-account-page-sign-out] button, .pqx-account-menu button[type="submit"]');
                    return {
                        cardCount: visibleCards.length,
                        heavyShadowCount: heavyShadows.length,
                        appbarHeight: appbar ? Math.round(appbar.getBoundingClientRect().height) : 0,
                        brandVisible: brand ? window.getComputedStyle(brand).display !== 'none' && brand.getBoundingClientRect().width > 0 : false,
                        themeVisible: themeToggle ? window.getComputedStyle(themeToggle).display !== 'none' && themeToggle.getBoundingClientRect().width > 0 : false,
                        accountSummaryVisible: accountSummary ? accountSummary.getBoundingClientRect().width > 0 : false,
                        logoutVisible: logoutButton ? logoutButton.getBoundingClientRect().width > 0 : false,
                    };
                }"""
            )
            assert density["cardCount"] <= 18
            assert density["heavyShadowCount"] <= 2
            assert density["appbarHeight"] <= 112
            assert density["brandVisible"] is False
            assert density["themeVisible"] is False
            if route in {"/app/agents", "/app/alerts", "/app/account"}:
                assert density["appbarHeight"] <= 60
            elif route.startswith("/app/settings/") or route == "/app/properties/packets":
                assert density["appbarHeight"] <= 52
            elif route.startswith("/app/shortlist"):
                assert density["appbarHeight"] <= 56
            if route in {"/app/agents", "/app/alerts"} or route.startswith("/app/shortlist"):
                assert density["accountSummaryVisible"] is True

            if route.startswith("/app/shortlist"):
                expect(page.locator("body", has_text=re.compile(r"Shortlist|No shortlist yet|Ranked homes", re.I))).to_be_visible()
                expect(page.locator("[data-property-mobile-dock]")).to_have_count(0)
                expect(page.locator("body", has_text=re.compile(r"Search|Research|Properties", re.I))).to_be_visible()
            elif route == "/app/agents":
                expect(page.locator("[data-property-search-agent-grid]")).to_be_visible()
                expect(page.locator(".pqx-automation-thumbnail").first).to_be_visible()
            elif route == "/app/alerts":
                expect(page.locator("body", has_text="Alerts")).to_be_visible()
                expect(page.locator("body", has_text="Notifications")).to_be_visible()
                alerts_mobile_metrics = page.evaluate(
                    """() => {
                        const rows = Array.from(document.querySelectorAll('.pqx-shell[data-pqx-surface="alerts"] .pqx-pref-row'));
                        const rowRects = rows.map((row) => row.getBoundingClientRect());
                        return {
                            viewportWidth: window.innerWidth,
                            rowCount: rows.length,
                            minRowHeight: Math.min(...rowRects.map((rect) => rect.height)),
                            maxRowRight: Math.max(0, ...rowRects.map((rect) => rect.right)),
                            multiColumnRows: rows.filter((row) => window.getComputedStyle(row).gridTemplateColumns.split(' ').filter(Boolean).length > 1).length,
                            actionColumns: Array.from(document.querySelectorAll('.pqx-shell[data-pqx-surface="alerts"] .pqx-pref-row .pqx-actions'))
                                .map((node) => window.getComputedStyle(node).gridTemplateColumns.split(' ').filter(Boolean).length),
                        };
                    }"""
                )
                assert alerts_mobile_metrics["rowCount"] >= 2
                assert alerts_mobile_metrics["minRowHeight"] >= 58
                assert alerts_mobile_metrics["multiColumnRows"] == 0
                assert alerts_mobile_metrics["maxRowRight"] <= alerts_mobile_metrics["viewportWidth"] + 1
                assert all(columns <= 1 for columns in alerts_mobile_metrics["actionColumns"])
            elif route == "/app/account":
                expect(page.locator("body", has_text="Notifications")).to_be_visible()
                expect(page.locator("body", has_text="Export account data")).to_be_visible()
                expect(page.get_by_role("link", name="Billing account")).to_be_visible()
                expect(page.locator("body", has_text="Access and shared pages")).to_be_visible()
                expect(page.locator("body", has_text="Sign-in and privacy")).to_be_visible()
                expect(page.locator("[data-account-page-sign-out] button")).to_be_visible()
                assert density["logoutVisible"] is True
            elif route == "/app/settings/google":
                expect(page.locator("body", has_text=re.compile(r"Google connection|PropertyQuarry account", re.I))).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"Connect Google|Add Google account", re.I))).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"account", re.I))).to_be_visible()
            elif route == "/app/settings/access":
                expect(page.locator("body", has_text=re.compile(r"Access|Sign-in and access", re.I))).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"Invite|access", re.I))).to_be_visible()
            elif route == "/app/settings/usage":
                expect(page.locator("body", has_text="Usage")).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"activation|usage", re.I))).to_be_visible()
            elif route == "/app/settings/support":
                expect(page.locator("body", has_text="Support at a glance")).to_be_visible()
                expect(page.locator("body", has_text="See what failed, what still works, and the next useful action.")).to_be_visible()
            elif route == "/app/settings/trust":
                expect(page.locator("body", has_text=re.compile(r"Reliability|Security", re.I))).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"privacy|recovery|access", re.I))).to_be_visible()
            else:
                expect(page.locator("body", has_text=re.compile(r"Invite|Invitations", re.I))).to_be_visible()
                expect(page.locator("body", has_text=re.compile(r"access|collaborator|share", re.I))).to_be_visible()

            screenshot_path = tmp_path / screenshot_name
            page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
            assert screenshot_path.exists() and screenshot_path.stat().st_size > 16_000
    finally:
        context.close()


def test_propertyquarry_mobile_dark_mode_covers_secondary_surfaces(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
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
                    "agent_id": "watch-1020-mobile-dark",
                    "name": "Leopoldstadt dark mobile watch",
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

    selectors = [
        ".pqx-topbar",
        ".pqx-shell *",
        ".pqx-primary-nav a",
        ".pqx-run-chip",
        ".pqx-button:not(.primary)",
        ".pqx-link-button:not(.primary)",
        ".pqx-card",
        ".pqx-field input:not([type='checkbox'])",
        ".pqx-field select",
        ".pqx-account-card",
        ".pqx-account-channel-option",
        ".pqx-account-channel-detail",
        ".pqx-account-channel-detail input",
        ".pqx-billing-card",
        ".pqx-automation-card",
        ".pqx-automation-thumbnail",
        ".pqx-empty",
        ".pqx-bottom-nav",
        ".pq-pack-shell",
        ".pq-pack-button",
        ".pq-pack-panel",
        ".pq-pack-card",
        ".pq-pack-input",
        ".pq-pack-pill",
        ".pq-pack-empty",
    ]

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    context.add_init_script("window.localStorage.setItem('propertyquarry.theme', 'dark');")
    _issue_browser_workspace_session(client=client, context=context, base_url=base_url)
    routes = [
        ("/app/search", "propertyquarry-search-mobile-dark.png"),
        ("/app/agents", "propertyquarry-agents-mobile-dark.png"),
        ("/app/account", "propertyquarry-account-mobile-dark.png"),
        ("/app/billing", "propertyquarry-billing-mobile-dark.png"),
        ("/app/settings/google", "propertyquarry-settings-google-mobile-dark.png"),
        ("/app/settings/access", "propertyquarry-settings-access-mobile-dark.png"),
        ("/app/settings/outcomes", "propertyquarry-settings-outcomes-mobile-dark.png"),
        ("/app/properties/packets", "propertyquarry-packets-mobile-dark.png"),
    ]
    try:
        page = context.new_page()
        for route, screenshot_name in routes:
            response = page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None
            _assert_no_horizontal_overflow(page)
            if route == "/app/billing":
                assert int(response.status) == 503
                _assert_propertyquarry_billing_fallback_page(page)
            else:
                assert response.ok
                expect(page.locator("html")).to_have_attribute("data-pq-theme", "dark")
                _assert_dark_mode_surfaces_stay_readable(page, selectors)
                if route != "/app/properties/packets":
                    _assert_property_shell_visual_gates(page, max_appbar_height=130)
            screenshot_path = tmp_path / screenshot_name
            page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
            assert screenshot_path.exists() and screenshot_path.stat().st_size > 14_000
    finally:
        context.close()


def test_propertyquarry_mobile_settings_surfaces_keep_consistent_top_navigation(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    routes = [
        ("/app/settings/plan", "propertyquarry-settings-plan-mobile-topnav.png"),
        ("/app/settings/google", "propertyquarry-settings-google-mobile-topnav.png"),
        ("/app/settings/access", "propertyquarry-settings-access-mobile-topnav.png"),
        ("/app/settings/outcomes", "propertyquarry-settings-outcomes-mobile-topnav.png"),
    ]
    expected_labels = ["Search", "Shortlist", "Research", "Account"]
    try:
        page = context.new_page()
        for route, screenshot_name in routes:
            response = page.goto(f"{base_url}{route}", wait_until="networkidle")
            assert response is not None and response.ok
            _assert_no_horizontal_overflow(page)
            _assert_property_shell_visual_gates(page, max_appbar_height=150)
            top_nav = page.locator("[data-property-console-topnav]").first
            expect(top_nav).to_be_visible()
            nav_labels = top_nav.locator("a, span").evaluate_all(
                "(nodes) => nodes.map((node) => node.textContent.trim()).filter(Boolean)"
            )
            assert nav_labels == expected_labels
            expect(top_nav.locator('[aria-current="page"]')).to_have_text("Account")
            metrics = top_nav.evaluate(
                """(node) => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    const active = node.querySelector('[aria-current="page"]');
                    const activeRect = active ? active.getBoundingClientRect() : null;
                    return {
                        display: style.display,
                        overflowX: style.overflowX,
                        width: rect.width,
                        viewportWidth: window.innerWidth,
                        activeTop: activeRect ? activeRect.top : 0,
                        activeBottom: activeRect ? activeRect.bottom : 0,
                        navTop: rect.top,
                        navBottom: rect.bottom,
                    };
                }"""
            )
            assert metrics["display"] == "flex"
            assert metrics["overflowX"] in {"auto", "scroll"}
            assert metrics["width"] <= metrics["viewportWidth"] + 1
            assert metrics["activeTop"] >= metrics["navTop"] - 1
            assert metrics["activeBottom"] <= metrics["navBottom"] + 1
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
        form = page.locator('[data-console-form-variant="property_search"]').first
        form.wait_for(state="visible")
        expect(form).to_have_attribute("data-property-active-step", "search")
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
            assert slider.get_attribute("max") in {"10", "60"}
        assert page.locator('input[name="max_results_per_source"]').get_attribute("data-range-selectable-max") == "2"
        assert page.locator('input[name="min_match_score"]').get_attribute("data-range-selectable-max") == "35"
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
    finally:
        context.close()


def test_propertyquarry_mobile_provider_family_controls_select_and_clear_cleanly(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
    tmp_path: Path,
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True, width=390, height=844)
    page: Page = context.new_page()
    screenshot_path = tmp_path / "propertyquarry-mobile-provider-family-controls.png"
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        form = page.locator('[data-console-form-variant="property_search"]').first
        form.wait_for(state="visible")
        expect(form).to_have_attribute("data-property-active-step", "search")
        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        _assert_no_horizontal_overflow(page)

        expected_provider_cap = page.locator('[data-console-form-variant="property_search"]').evaluate(
            """(form) => {
              const raw = String(form.getAttribute('data-console-form-meta') || '').trim();
              const meta = raw ? JSON.parse(raw) : {};
              return Number(meta?.commercial?.max_platforms || 0);
            }"""
        )
        assert isinstance(expected_provider_cap, int)
        assert expected_provider_cap > 0

        first_provider_family = page.locator('[data-provider-group-panel]').first
        first_provider_family.locator("summary").scroll_into_view_if_needed()
        first_provider_family.locator("summary").click()

        add_button = first_provider_family.get_by_role("button", name="Add family")
        clear_button = first_provider_family.get_by_role("button", name="Clear family")
        expect(add_button).to_be_visible()
        expect(clear_button).to_be_visible()

        button_metrics = page.evaluate(
            """() => {
              const add = [...document.querySelectorAll('[data-provider-group-panel] button')]
                .find((node) => (node.textContent || '').trim() === 'Add family');
              const clear = [...document.querySelectorAll('[data-provider-group-panel] button')]
                .find((node) => (node.textContent || '').trim() === 'Clear family');
              const addRect = add ? add.getBoundingClientRect() : null;
              const clearRect = clear ? clear.getBoundingClientRect() : null;
              return {
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                addRight: addRect ? addRect.right : 0,
                clearRight: clearRect ? clearRect.right : 0,
                addBottom: addRect ? addRect.bottom : 0,
                clearBottom: clearRect ? clearRect.bottom : 0,
              };
            }"""
        )
        assert button_metrics["addRight"] <= button_metrics["viewportWidth"] + 1
        assert button_metrics["clearRight"] <= button_metrics["viewportWidth"] + 1
        assert button_metrics["addBottom"] <= button_metrics["viewportHeight"] + 80
        assert button_metrics["clearBottom"] <= button_metrics["viewportHeight"] + 80

        family_provider_count = first_provider_family.locator('input[name="selected_platforms"]').count()
        assert family_provider_count > 0

        add_button.click()
        checked_family_provider_count = first_provider_family.locator('input[name="selected_platforms"]:checked').count()
        checked_total_after_family = page.locator('input[name="selected_platforms"]:checked').count()
        assert checked_family_provider_count == min(family_provider_count, expected_provider_cap)
        assert checked_total_after_family == checked_family_provider_count

        clear_button.click()
        expect(first_provider_family.locator('input[name="selected_platforms"]:checked')).to_have_count(0)
        expect(page.locator('input[name="selected_platforms"]:checked')).to_have_count(0)

        page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled", caret="hide")
        assert screenshot_path.exists() and screenshot_path.stat().st_size > 16_000
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
        page.locator("[data-property-start-top]").click()
        page.wait_for_function(
            """
            () => {
              const button = document.querySelector('[data-property-start-top]');
              const inlineError = document.querySelector('[data-property-inline-error]');
              const sawLoading = Boolean(
                button
                && button.getAttribute('aria-busy') === 'true'
                && button.getAttribute('data-pqx-loading') === 'true'
                && String(button.textContent || '').includes('Launching...')
              );
              const sawBackendFailure = Boolean(
                inlineError
                && String(inlineError.textContent || '').includes('Upgrade required for this run')
              );
              return sawLoading || sawBackendFailure;
            }
            """
        )
        inline_error = page.locator("[data-property-inline-error]")
        expect(inline_error).to_contain_text("Upgrade required for this run")
        expect(inline_error).to_contain_text("plus plan")
        expect(page.locator("[data-property-start-top]")).to_have_attribute("aria-busy", "false")
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
        page.locator('[data-keyword-priority-row][data-keyword-value="parking pressure check"] [data-keyword-preference-select]').select_option("high")
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
            page.locator("[data-property-start-top]").click()
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
        assert preferences["parking_pressure_preference"] == "high"
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
        assert preferences["min_match_score"] == 35
        assert preferences["require_floorplan"] is True
        assert len(observed["selected_platforms"]) == 3
        assert page.locator("body", has_text="Altbau near U6").is_visible()
        assert page.locator("body", has_text="Open property").is_visible()
        assert page.locator("body", has_text="360 ready").is_visible()
        page.locator("[data-workbench-row]", has_text="Altbau near U6").locator(".pqx-result-title").click()
        assert "/app/research/" in page.url
        assert urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get("run_id", [""])[0] == run_id
        assert page.locator("body", has_text="Altbau near U6").is_visible()
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
        expect(best_match.get_by_role("link", name="3D tour ready")).to_be_visible()
        expect(best_match.get_by_role("link", name="Open 3D tour")).to_have_count(0)
        open_360 = best_match.get_by_role("link", name="3D tour ready")
        tour_url = str(open_360.get_attribute("href") or "").strip()
        assert tour_url.endswith("/tours/altbau-u6/control/matterport")
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
                    "status_label": "Walkthrough queued",
                    "status_detail": "Walkthrough is queued after your request and will appear here when it is ready.",
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
        packet_href = str(family_row.get_attribute("data-candidate-packet-url") or "").strip()
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        request_button = page.get_by_role("button", name="Request walkthrough")
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
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        listing_only_row = page.locator("[data-workbench-row]", has_text="Listing URL only loft").first
        listing_only_row.wait_for(timeout=5000)
        assert visual_requests == []

        packet_href = str(listing_only_row.get_attribute("data-candidate-packet-url") or "").strip()
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        request_button = page.get_by_role("button", name="Request walkthrough")
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
        assert page.locator("body", has_text="Share property pages and keep the replies together.").is_visible()
        assert page.locator("body", has_text="Household reactions").is_visible()
        assert page.locator("body", has_text="Watch-outs").is_visible()
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
        assert page.locator("body", has_text=re.compile(r"shortlisted homes|ranked homes", re.I)).is_visible()
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
        assert page.locator("body", has_text="Quick take").is_visible()
        assert page.locator("body", has_text="Decision shortcut loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Question loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
    finally:
        context.close()
