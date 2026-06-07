from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import (
    install_property_run,
    property_client_with_workspace,
    reset_packet_repo,
    seed_packet,
    seed_property_search_preferences,
)


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_packet_dashboard_renders_share_and_followup_state(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase1-browser", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase1-browser")
    share = client.post(
        f"/app/api/properties/packets/{publication_id}/shares",
        json={"audience_type": "family", "channel": "link", "recipients": [{"name": "Anna", "email": "anna@example.com"}]},
    )
    recipient_id = share.json()["share"]["recipients"][0]["recipient_id"]
    share_id = share.json()["share"]["share_id"]
    client.post(
        f"/app/api/properties/packets/{publication_id}/engagement-events",
        json={"share_id": share_id, "recipient_id": recipient_id, "event_type": "opened"},
    )

    page = client.get("/app/properties/packets")
    assert page.status_code == 200
    assert "Share packet" in page.text
    assert "Recipients" in page.text
    assert "Follow-ups" in page.text
    assert "Next best action:" in page.text


def test_workspace_shortlist_surfaces_packet_followup_entry(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase1-workspace", tmp_path=tmp_path)
    seed_property_search_preferences(client)
    install_property_run(monkeypatch, property_url="https://example.com/listing-1")
    page = client.get("/app/properties", params={"run_id": "run-phase1"})
    assert page.status_code == 200
    assert "Track packet follow-up" in page.text
    assert "Open feedback" in page.text
