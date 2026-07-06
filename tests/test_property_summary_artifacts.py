from __future__ import annotations

from pathlib import Path

import pytest

from app.services.fliplink.service import build_fliplink_packet_service
from tests.propertyquarry_phase_helpers import property_client_with_workspace, reset_packet_repo, seed_packet


@pytest.fixture(autouse=True)
def _reset_repo() -> None:
    reset_packet_repo()


def test_summary_artifact_generation_and_attachment_contract(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase3-contract", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase3")
    artifact = client.post(
        "/app/api/property-summaries/generate",
        json={"subject_type": "property", "subject_id": "listing-phase3", "artifact_type": "why_shortlisted", "audience_type": "family"},
    )
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["artifact"]["artifact_id"]

    fetched = client.get(f"/app/api/property-summaries/{artifact_id}")
    assert fetched.status_code == 200
    assert fetched.json()["artifact"]["artifact_type"] == "why_shortlisted"

    attached = client.post(
        f"/app/api/properties/packets/{publication_id}/attach-summary",
        json={"artifact_id": artifact_id},
    )
    assert attached.status_code == 200, attached.text

    packet = client.get(f"/app/api/properties/packets/{publication_id}")
    assert packet.status_code == 200
    assert packet.json()["publication"]["attached_summaries"][0]["artifact_id"] == artifact_id


def test_summary_artifact_copy_uses_customer_facing_share_language(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase3-copy", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase3-copy")
    assert publication_id

    service = build_fliplink_packet_service(client.app.state.container)
    artifact = service.generate_summary_artifact(
        principal_id="pq-phase3-copy",
        subject_type="property",
        subject_id="listing-phase3-copy",
        artifact_type="why_shortlisted",
    )

    body = str(artifact.get("body_markdown") or artifact.get("body") or "")
    assert "review-ready" not in body
    assert "shareable packet" not in body
    assert "This home is worth sharing now." in body
