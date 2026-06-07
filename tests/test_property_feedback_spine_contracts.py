from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_structured_property_feedback_and_clusters_contract(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase2-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase2")

    recorded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-anna",
            "stakeholder_label": "Anna",
            "property_ref": "listing-phase2",
            "publication_id": publication_id,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Too far from school.",
        },
    )
    assert recorded.status_code == 200, recorded.text

    listing = client.get("/app/api/property-feedback", params={"property_ref": "listing-phase2"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    clusters = client.post("/app/api/property-feedback/cluster", params={"property_ref": "listing-phase2"})
    assert clusters.status_code == 200, clusters.text
    assert clusters.json()["clusters"][0]["theme"] == "location"

    summary = client.get("/app/api/properties/listing-phase2/feedback-summary")
    assert summary.status_code == 200
    assert summary.json()["dealbreaker_count"] == 1

    preferences = client.get("/app/api/stakeholders/family-anna/preferences")
    assert preferences.status_code == 200
    assert preferences.json()["summary"]["concerns"] >= 1
