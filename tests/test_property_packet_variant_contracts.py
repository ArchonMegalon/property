from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_variant_creation_republish_and_share_journey_contract(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase4-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase4")

    variant = client.post(
        f"/app/api/properties/packets/{publication_id}/variants",
        json={"audience_type": "agent", "base_variant_key": "agent-v1", "title_override": "Agent Review Packet"},
    )
    assert variant.status_code == 200, variant.text
    assert variant.json()["variant"]["packet_summary_json"]["audience_type"] == "agent"

    republished = client.post(f"/app/api/properties/packets/{publication_id}/republish")
    assert republished.status_code == 200, republished.text

    journey = client.get(f"/app/api/properties/packets/{publication_id}/share-journey")
    assert journey.status_code == 200
    assert journey.json()["state"] in {"drafted", "published", "followup_needed", "decision_ready"}
    assert journey.json()["variants"]
