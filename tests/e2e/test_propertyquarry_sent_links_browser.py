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
                assert (
                    tour_page.locator("#cube").count() > 0
                    or "Floorplan" in tour_page.locator("#tour-status").inner_text(timeout=3000)
                ), f"{title}: hosted 3D lane did not open cleanly"
                tour_page.close()

                fly_page = context.new_page()
                fly_page.goto(flythrough_url, wait_until="networkidle", timeout=30000)
                fly_page.wait_for_timeout(1500)
                assert fly_page.locator("#flythrough-video").count() > 0, f"{title}: flythrough video element missing"
                status_text = fly_page.locator("#tour-status").inner_text(timeout=3000)
                assert "Flythrough" in status_text, f"{title}: flythrough lane did not report itself as active"
                fly_page.close()
        finally:
            browser.close()
