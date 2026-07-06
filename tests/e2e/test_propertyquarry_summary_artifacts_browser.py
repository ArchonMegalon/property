from __future__ import annotations

from pathlib import Path

import pytest

from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_packet_dashboard_renders_attached_summary(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase3-browser", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase3-browser")
    artifact = client.post(
        "/app/api/property-summaries/generate",
        json={"subject_type": "property", "subject_id": "listing-phase3-browser", "artifact_type": "why_shortlisted"},
    )
    artifact_id = artifact.json()["artifact"]["artifact_id"]
    client.post(f"/app/api/properties/packets/{publication_id}/attach-summary", json={"artifact_id": artifact_id})

    page = client.get("/app/properties/packets")
    assert page.status_code == 200
    assert "Added summaries" in page.text
    assert "Why Shortlisted" in page.text or "Why shortlisted" in page.text
