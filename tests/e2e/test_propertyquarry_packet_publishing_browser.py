from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


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
