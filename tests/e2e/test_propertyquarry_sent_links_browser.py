from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


def _manifest_path() -> Path:
    raw = str(os.environ.get("PROPERTYQUARRY_SENT_LINKS_MANIFEST") or "").strip()
    if not raw:
        pytest.skip("PROPERTYQUARRY_SENT_LINKS_MANIFEST not set")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"sent-links manifest not found: {path}")
    return path


def test_sent_property_links_open_in_real_browser() -> None:
    items = json.loads(_manifest_path().read_text(encoding="utf-8"))
    assert isinstance(items, list) and items, "sent-links manifest must contain at least one item"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            for item in items:
                title = str(item.get("title") or item.get("key") or "property").strip()
                tour_url = str(item.get("tour_url") or "").strip()
                flythrough_url = str(item.get("flythrough_url") or "").strip()
                assert tour_url, f"{title}: missing tour_url"
                assert flythrough_url, f"{title}: missing flythrough_url"

                tour_page = context.new_page()
                tour_page.goto(tour_url, wait_until="networkidle", timeout=30000)
                tour_page.wait_for_timeout(1200)
                hosted_cube = tour_page.locator("#cube").count() > 0
                live_iframe = tour_page.locator("iframe[src*='matterport.com']").count() > 0
                status_text = ""
                if tour_page.locator("#tour-status").count() > 0:
                    status_text = tour_page.locator("#tour-status").inner_text(timeout=3000)
                assert hosted_cube or live_iframe or "Floorplan" in status_text or "Panorama" in status_text, (
                    f"{title}: hosted 3D lane did not open cleanly"
                )
                tour_page.close()

                fly_page = context.new_page()
                fly_page.goto(flythrough_url, wait_until="networkidle", timeout=30000)
                fly_page.wait_for_timeout(1500)
                video_locator = fly_page.locator("#tour-video")
                if video_locator.count() == 0:
                    video_locator = fly_page.locator("#flythrough-video")
                assert video_locator.count() > 0, f"{title}: flythrough video element missing"
                status_text = ""
                if fly_page.locator("#tour-status").count() > 0:
                    status_text = fly_page.locator("#tour-status").inner_text(timeout=3000)
                assert "Flythrough" in status_text or video_locator.get_attribute("poster"), (
                    f"{title}: flythrough lane did not report itself as active"
                )
                fly_page.close()
        finally:
            browser.close()


def test_sent_direct_property_links_open_in_real_browser() -> None:
    items = json.loads(_manifest_path().read_text(encoding="utf-8"))
    assert isinstance(items, list) and items, "sent-links manifest must contain at least one item"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            for item in items:
                title = str(item.get("title") or item.get("key") or "property").strip()
                direct_tour_url = str(item.get("direct_tour_url") or "").strip()
                direct_flythrough_url = str(item.get("direct_flythrough_url") or "").strip()
                if not direct_tour_url and not direct_flythrough_url:
                    continue

                if direct_tour_url:
                    direct_tour_page = context.new_page()
                    response = direct_tour_page.goto(direct_tour_url, wait_until="domcontentloaded", timeout=30000)
                    assert response and response.ok, f"{title}: direct 3D tour button target did not load"
                    direct_tour_page.wait_for_timeout(1500)
                    assert "matterport.com" in direct_tour_page.url or "propertyquarry.com" in direct_tour_page.url, (
                        f"{title}: direct 3D tour target opened an unexpected host"
                    )
                    direct_tour_page.close()

                if direct_flythrough_url:
                    fly_page = context.new_page()
                    response = fly_page.goto(direct_flythrough_url, wait_until="domcontentloaded", timeout=30000)
                    assert response and response.ok, f"{title}: direct flythrough target did not load"
                    content_type = str(response.headers.get("content-type") or "").lower()
                    assert content_type.startswith("video/"), f"{title}: direct flythrough target was not a video asset"
                    fly_page.close()
        finally:
            browser.close()
