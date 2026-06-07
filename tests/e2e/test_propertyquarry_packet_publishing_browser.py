from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet
from tests.e2e.test_propertyquarry_greenfield_browser import browser, propertyquarry_browser_server


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_packet_dashboard_shows_variant_and_republish_controls(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase4-browser", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase4-browser")
    client.post(
        f"/app/api/properties/packets/{publication_id}/variants",
        json={"audience_type": "family", "base_variant_key": "family-v2", "title_override": "Family Review Packet"},
    )
    page = client.get("/app/properties/packets")
    assert page.status_code == 200
    assert "Share journey:" in page.text
    assert "Republish revised packet" in page.text


def test_packet_dashboard_republishes_variant_in_real_browser(
    browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    publication_id = seed_packet(client, property_ref="listing-phase4-browser")
    variant = client.post(
        f"/app/api/properties/packets/{publication_id}/variants",
        json={"audience_type": "family", "base_variant_key": "family-v2", "title_override": "Family Review Packet"},
    )
    assert variant.status_code == 200, variant.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = browser.new_context(
        viewport={"width": 1440, "height": 1100},
        extra_http_headers={"X-EA-Principal-ID": "pq-greenfield-browser"},
    )
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties/packets", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("[data-property-packets-dashboard]").is_visible()
        assert page.locator("body", has_text="Family Review Packet").is_visible()
        assert page.locator("body", has_text="Republish revised packet").is_visible()
        with page.expect_response("**/app/api/properties/packets/*/republish") as republish_response_info:
            page.locator(f'[data-republish-publication][data-publication-id="{publication_id}"]').click()
        republish_response = republish_response_info.value
        assert republish_response.ok, republish_response.text()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Share journey:").is_visible()
        assert page.locator("body", has_text="Family Review Packet").is_visible()
    finally:
        context.close()
