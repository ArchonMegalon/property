from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_packet_share_and_engagement_snapshot_contract(monkeypatch, tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase1-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase1")

    share = client.post(
        f"/app/api/properties/packets/{publication_id}/shares",
        json={
            "audience_type": "family",
            "channel": "link",
            "variant_key": "family-v1",
            "recipients": [{"name": "Anna", "email": "anna@example.com", "relationship": "sister"}],
        },
    )
    assert share.status_code == 200, share.text
    share_id = share.json()["share"]["share_id"]
    recipient_id = share.json()["share"]["recipients"][0]["recipient_id"]

    opened = client.post(
        f"/app/api/properties/packets/{publication_id}/engagement-events",
        json={"share_id": share_id, "recipient_id": recipient_id, "event_type": "opened"},
    )
    assert opened.status_code == 200, opened.text
    snapshot = opened.json()["engagement"]
    assert snapshot["summary"]["opened"] == 1
    assert snapshot["summary"]["next_best_action"] == "request_feedback"

    feedback = client.post(
        f"/app/api/properties/packets/{publication_id}/engagement-events",
        json={"share_id": share_id, "recipient_id": recipient_id, "event_type": "submitted_feedback"},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["engagement"]["summary"]["responded"] == 1
    assert feedback.json()["engagement"]["summary"]["next_best_action"] == "review_feedback"


def test_archived_packet_rejects_new_share(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase1-archive", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase1-archive")
    archived = client.post(f"/app/api/properties/packets/{publication_id}/archive", json={"note": "done"})
    assert archived.status_code == 200, archived.text
    rejected = client.post(
        f"/app/api/properties/packets/{publication_id}/shares",
        json={"audience_type": "family", "channel": "link", "recipients": [{"name": "A", "email": "a@example.com"}]},
    )
    assert rejected.status_code == 422
