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


def test_packet_engagement_metadata_is_sanitized_and_bounded(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase1-metadata", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase1-metadata")

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
        json={
            "share_id": share_id,
            "recipient_id": recipient_id,
            "event_type": "opened",
            "metadata_json": {
                "surface": "packet_dashboard",
                "session_token": "drop-me",
                "unknown_key": "drop-me-too",
                "viewport": {"width": 1440, "height": 900, "oauth_token": "blocked"},
            },
        },
    )
    assert opened.status_code == 200, opened.text
    event = opened.json()["event"]["payload_json"]
    assert event["metadata_json"]["surface"] == "packet_dashboard"
    assert "session_token" not in event["metadata_json"]
    assert "unknown_key" not in event["metadata_json"]
    assert "oauth_token" not in event["metadata_json"]["viewport"]

    oversized = client.post(
        f"/app/api/properties/packets/{publication_id}/engagement-events",
        json={
            "share_id": share_id,
            "recipient_id": recipient_id,
            "event_type": "opened",
            "metadata_json": {
                "target": "x" * 5000,
            },
        },
    )
    assert oversized.status_code == 422
