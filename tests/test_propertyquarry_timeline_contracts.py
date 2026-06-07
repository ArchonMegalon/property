from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_stakeholder_and_property_timelines_with_followup_assignment(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase5-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase5")
    share = client.post(
        f"/app/api/properties/packets/{publication_id}/shares",
        json={"audience_type": "family", "channel": "link", "recipients": [{"name": "Nina", "email": "nina@example.com"}]},
    )
    followup_id = client.get(f"/app/api/properties/packets/{publication_id}/engagement").json()["followups"][0]["task_id"]

    assigned = client.post(f"/app/api/followups/{followup_id}/assign", json={"owner": "operator-office"})
    assert assigned.status_code == 200, assigned.text
    resolved = client.post(f"/app/api/followups/{followup_id}/resolve", json={"resolution": "sent follow-up"})
    assert resolved.status_code == 200, resolved.text

    stakeholder_id = share.json()["share"]["recipients"][0]["recipient_id"]
    stakeholder_timeline = client.get(f"/app/api/stakeholders/{stakeholder_id}/timeline")
    assert stakeholder_timeline.status_code == 200
    assert stakeholder_timeline.json()["total"] >= 1

    property_timeline = client.get("/app/api/properties/listing-phase5/timeline")
    assert property_timeline.status_code == 200
    assert property_timeline.json()["total"] >= 1
