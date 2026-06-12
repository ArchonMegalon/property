from __future__ import annotations

from app.services.property_decision_loop import (
    build_property_decision_loop_snapshot,
    decision_state_for_feedback,
)


def test_decision_loop_maps_feedback_to_durable_decision_states() -> None:
    assert decision_state_for_feedback("like", []) == "shortlisted"
    assert decision_state_for_feedback("dislike", ["gas_heating"]) == "rejected"
    assert decision_state_for_feedback("hide", []) == "archived"
    assert decision_state_for_feedback("maybe", ["heating_unclear"]) == "needs_documents"
    assert decision_state_for_feedback("maybe", ["noise_risk"]) == "needs_agent_answer"


def test_decision_loop_creates_evidence_agent_questions_and_document_intake() -> None:
    snapshot = build_property_decision_loop_snapshot(
        property_ref="listing-123",
        reaction="maybe",
        reason_keys=["operating_costs_missing", "heating_unclear"],
        note="Need Betriebskosten and heating proof before viewing.",
        actor="owner",
        property_facts={"has_floorplan": False},
        learning_applied=True,
        aggregate_candidate=False,
    )

    assert snapshot.decision.property_ref == "listing-123"
    assert snapshot.decision.decision_state == "needs_documents"
    assert snapshot.decision.learning_applied is True
    assert any(claim.claim_type == "decision" for claim in snapshot.evidence_claims)
    assert any(claim.claim_type == "human_feedback" for claim in snapshot.evidence_claims)
    assert any(task.reason_key == "operating_costs_missing" for task in snapshot.agent_question_tasks)
    assert any(task.reason_key == "heating_unclear" for task in snapshot.agent_question_tasks)
    assert {document.document_type for document in snapshot.document_records} >= {
        "operating_cost_statement",
        "energy_certificate",
        "floorplan",
    }
    assert snapshot.suppression_explanation == [
        "Do not suppress permanently until the missing document request is answered."
    ]


def test_rejected_decision_marks_aggregate_candidate_without_public_claims() -> None:
    snapshot = build_property_decision_loop_snapshot(
        property_ref="listing-456",
        reaction="dislike",
        reason_keys=["noise_risk"],
        note="Bedroom seems too loud.",
        source="telegram",
        aggregate_candidate=True,
    )

    assert snapshot.decision.decision_state == "rejected"
    assert snapshot.decision.aggregate_candidate is True
    assert "Future searches can down-rank similar listings after owner review." in snapshot.suppression_explanation
    human_claims = [claim for claim in snapshot.evidence_claims if claim.claim_type == "human_feedback"]
    assert human_claims
    assert human_claims[0].privacy_class == "owner_private"
    assert human_claims[0].allowed_outputs == ["owner_private"]

