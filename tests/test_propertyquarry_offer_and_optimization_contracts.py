from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_offer_checkout_and_optimization_contract(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase6-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase6")
    share = client.post(
        f"/app/api/properties/packets/{publication_id}/shares",
        json={"audience_type": "family", "channel": "link", "recipients": [{"name": "Omar", "email": "omar@example.com"}]},
    )
    share_id = share.json()["share"]["share_id"]
    recipient_id = share.json()["share"]["recipients"][0]["recipient_id"]
    client.post(
        f"/app/api/properties/packets/{publication_id}/engagement-events",
        json={"share_id": share_id, "recipient_id": recipient_id, "event_type": "opened"},
    )
    client.post(
        f"/app/api/properties/packets/{publication_id}/fliplink/analytics-snapshot",
        json={"views": 12, "unique_visitors": 4, "average_time_seconds": 90, "device_breakdown": {"mobile": 7, "desktop": 2}},
    )

    offers = client.get("/app/api/offers", params={"publication_id": publication_id})
    assert offers.status_code == 200
    assert offers.json()["total"] >= 1

    checkout = client.post(f"/app/api/offers/{offers.json()['items'][0]['offer_id']}/checkout", params={"publication_id": publication_id})
    assert checkout.status_code == 200
    assert checkout.json()["status"] == "checkout_started"

    optimization = client.get(f"/app/api/properties/packets/{publication_id}/optimization")
    assert optimization.status_code == 200
    recommendation_id = optimization.json()["items"][0]["recommendation_id"]
    ack = client.post(f"/app/api/properties/packets/{publication_id}/optimization/ack", json={"recommendation_id": recommendation_id})
    assert ack.status_code == 200
    assert any(item["status"] == "acknowledged" for item in ack.json()["items"])
