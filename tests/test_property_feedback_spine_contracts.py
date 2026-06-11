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
    assert "household_review" in summary.json()
    assert "risk_signal_candidates" in summary.json()

    preferences = client.get("/app/api/stakeholders/family-anna/preferences")
    assert preferences.status_code == 200
    assert preferences.json()["summary"]["concerns"] >= 1


def test_property_feedback_followup_status_and_household_alignment_contract(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase2-followup", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase2-followup")

    first = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": "listing-phase2-followup",
            "publication_id": publication_id,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "source": "clippy_agent_brief",
            "followup_status": "asked",
        },
    )
    assert first.status_code == 200, first.text
    feedback_id = first.json()["feedback"]["feedback_id"]

    second = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-jonas",
            "stakeholder_label": "Jonas",
            "property_ref": "listing-phase2-followup",
            "publication_id": publication_id,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Street noise feels like a blocker.",
            "source": "packet",
            "decision_state": "rejected",
        },
    )
    assert second.status_code == 200, second.text

    updated = client.post(
        f"/app/api/property-feedback/{feedback_id}/followup-status",
        json={"followup_status": "answered", "note": "Agent sent the cost history."},
    )
    assert updated.status_code == 200, updated.text

    listing = client.get("/app/api/property-feedback", params={"property_ref": "listing-phase2-followup"})
    assert listing.status_code == 200
    question_row = next(item for item in listing.json()["items"] if item["feedback_id"] == feedback_id)
    assert question_row["followup_status"] == "answered"

    summary = client.get("/app/api/properties/listing-phase2-followup/feedback-summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["household_review"]["alignment_label"] in {"split", "blocked", "aligned"}
    assert body["decision_state_counts"]["rejected"] >= 1
    assert isinstance(body["risk_signal_candidates"], list)


def test_structured_property_feedback_accepts_decision_lifecycle_states(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-phase2-lifecycle", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-phase2-lifecycle")

    recorded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": "listing-phase2-lifecycle",
            "publication_id": publication_id,
            "category": "priority",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Viewing is worth requesting now.",
            "source": "decision_lifecycle",
            "decision_state": "viewing_requested",
        },
    )
    assert recorded.status_code == 200, recorded.text

    summary = client.get("/app/api/properties/listing-phase2-lifecycle/feedback-summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["decision_state_counts"]["viewing_requested"] >= 1


def test_dadan_video_feedback_normalizes_into_structured_property_signals(tmp_path: Path) -> None:
    client = property_client_with_workspace(principal_id="pq-dadan-feedback", tmp_path=tmp_path)
    publication_id = seed_packet(client, property_ref="listing-dadan")

    recorded = client.post(
        "/app/api/property-feedback/dadan",
        json={
            "property_ref": "listing-dadan",
            "publication_id": publication_id,
            "stakeholder_id": "viewer-mara",
            "stakeholder_label": "Mara",
            "submission_id": "dadan-submission-1",
            "answers": [
                {"question": "What did you like?", "answer": "I like the bright kitchen and balcony."},
                {"question": "What did you not like?", "answer": "The bathroom feels small and might be a blocker."},
                {"question": "What should we ask?", "answer": "Can the agent confirm operating costs?"},
            ],
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["source"] == "dadan_video_feedback"
    assert body["total"] == 3
    assert {item["category"] for item in body["recorded"]} == {"love", "dealbreaker", "question"}

    listing = client.get("/app/api/property-feedback", params={"property_ref": "listing-dadan"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 3
