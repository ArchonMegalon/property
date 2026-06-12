from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


DecisionState = Literal[
    "unseen",
    "reviewing",
    "shortlisted",
    "blocked",
    "needs_documents",
    "needs_agent_answer",
    "viewing_requested",
    "offer_candidate",
    "rejected",
    "archived",
]

DecisionSource = Literal["workbench", "telegram", "email", "dadan", "packet", "tour", "system"]

ClaimType = Literal[
    "fact",
    "source",
    "risk",
    "media",
    "human_feedback",
    "authority",
    "investment_assumption",
    "decision",
]

VerificationState = Literal[
    "confirmed",
    "likely",
    "unclear",
    "missing",
    "needs_owner_review",
    "official_source_backed",
    "provider_only",
    "user_reported",
]

PrivacyClass = Literal["owner_private", "family_review", "agent_share", "paid_customer", "anonymous_public"]

AgentQuestionStatus = Literal["drafted", "sent", "answered", "verified", "contradicted", "ignored"]
DocumentVerificationState = Literal["missing", "uploaded", "extracted", "verified", "rejected"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, *, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _hash(value: object) -> str:
    text = _clean(value, limit=2000)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class PropertyDecisionLedgerEntry(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"pdl_{uuid4().hex}")
    property_ref: str
    decision_state: DecisionState
    reason_keys: list[str] = Field(default_factory=list)
    source: DecisionSource = "workbench"
    actor: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=_now)
    supersedes_decision_id: str = ""
    learning_applied: bool = False
    aggregate_candidate: bool = False


class PropertyEvidenceClaim(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"pec_{uuid4().hex}")
    property_ref: str
    claim_type: ClaimType
    text: str
    source_type: str = "propertyquarry"
    source_ref: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    verification_state: VerificationState = "unclear"
    privacy_class: PrivacyClass = "owner_private"
    allowed_outputs: list[str] = Field(default_factory=list)
    expires_at: str = ""
    created_at: str = Field(default_factory=_now)


class AgentQuestionTask(BaseModel):
    task_id: str = Field(default_factory=lambda: f"aqt_{uuid4().hex}")
    property_ref: str
    question_text: str
    reason_key: str = ""
    source_claim_id: str = ""
    status: AgentQuestionStatus = "drafted"
    answer_source: str = ""
    updated_claim_id: str = ""
    created_at: str = Field(default_factory=_now)


class PropertyDocumentRecord(BaseModel):
    document_id: str = Field(default_factory=lambda: f"pdoc_{uuid4().hex}")
    property_ref: str
    document_type: str
    source: str = ""
    privacy_class: PrivacyClass = "owner_private"
    verification_state: DocumentVerificationState = "missing"
    extracted_claims: list[str] = Field(default_factory=list)
    missing_pages: list[str] = Field(default_factory=list)
    redaction_state: str = "not_started"
    linked_risks: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)


class PropertyDecisionLoopSnapshot(BaseModel):
    property_ref: str
    decision: PropertyDecisionLedgerEntry
    evidence_claims: list[PropertyEvidenceClaim] = Field(default_factory=list)
    agent_question_tasks: list[AgentQuestionTask] = Field(default_factory=list)
    document_records: list[PropertyDocumentRecord] = Field(default_factory=list)
    suppression_explanation: list[str] = Field(default_factory=list)


_REACTION_DECISION: dict[str, DecisionState] = {
    "like": "shortlisted",
    "maybe": "needs_agent_answer",
    "dislike": "rejected",
    "hide": "archived",
}

_DOCUMENT_REASON_MAP = {
    "no_floorplan": ("floorplan", "Please send the floorplan with readable room dimensions."),
    "floorplan_missing": ("floorplan", "Please send the floorplan with readable room dimensions."),
    "operating_costs_missing": ("operating_cost_statement", "Please send the latest operating-cost statement and recurring extras."),
    "betriebskosten_missing": ("operating_cost_statement", "Please send the latest Betriebskostenabrechnung."),
    "energy_certificate_missing": ("energy_certificate", "Please send the current energy certificate."),
    "heating_unclear": ("energy_certificate", "Please confirm the heating source and share the energy certificate."),
    "gas_heating": ("energy_certificate", "Please confirm the heating source and share the energy certificate."),
}


def decision_state_for_feedback(reaction: str, reason_keys: list[str] | tuple[str, ...]) -> DecisionState:
    normalized_reaction = _clean(reaction, limit=40).lower()
    normalized_reasons = {_clean(item, limit=80).lower() for item in reason_keys if _clean(item, limit=80)}
    if normalized_reaction == "maybe":
        if normalized_reasons & set(_DOCUMENT_REASON_MAP):
            return "needs_documents"
        return "needs_agent_answer"
    return _REACTION_DECISION.get(normalized_reaction, "reviewing")


def build_property_decision_loop_snapshot(
    *,
    property_ref: str,
    reaction: str,
    reason_keys: list[str] | tuple[str, ...] = (),
    note: str = "",
    source: DecisionSource = "workbench",
    actor: str = "",
    property_facts: dict[str, object] | None = None,
    learning_applied: bool = False,
    aggregate_candidate: bool = False,
) -> PropertyDecisionLoopSnapshot:
    normalized_ref = _clean(property_ref, limit=500) or "property"
    normalized_reasons = [_clean(item, limit=80).lower() for item in reason_keys if _clean(item, limit=80)]
    decision_state = decision_state_for_feedback(reaction, normalized_reasons)
    decision = PropertyDecisionLedgerEntry(
        property_ref=normalized_ref,
        decision_state=decision_state,
        reason_keys=normalized_reasons,
        source=source,
        actor=_clean(actor, limit=120),
        confidence=0.9 if reaction in {"like", "dislike", "hide"} else 0.7,
        learning_applied=learning_applied,
        aggregate_candidate=aggregate_candidate,
    )

    claims: list[PropertyEvidenceClaim] = [
        PropertyEvidenceClaim(
            claim_id=f"decision.{_hash(normalized_ref + ':' + decision.decision_id)}",
            property_ref=normalized_ref,
            claim_type="decision",
            text=f"Decision state is {decision_state}.",
            source_type=source,
            source_ref=decision.decision_id,
            confidence="high",
            verification_state="user_reported",
            privacy_class="owner_private",
            allowed_outputs=["owner_private", "family_review"],
        )
    ]
    note_text = _clean(note, limit=500)
    if note_text:
        claims.append(
            PropertyEvidenceClaim(
                claim_id=f"human_feedback.{_hash(normalized_ref + ':' + note_text)}",
                property_ref=normalized_ref,
                claim_type="human_feedback",
                text=note_text,
                source_type=source,
                source_ref=decision.decision_id,
                confidence="medium",
                verification_state="user_reported",
                privacy_class="owner_private",
                allowed_outputs=["owner_private"],
            )
        )

    facts = dict(property_facts or {})
    if str(facts.get("has_floorplan")).strip().lower() in {"false", "0", "no"} or int(facts.get("floorplan_count") or 0) <= 0:
        if "no_floorplan" not in normalized_reasons and "floorplan_missing" not in normalized_reasons:
            normalized_reasons.append("floorplan_missing")

    questions: list[AgentQuestionTask] = []
    documents: list[PropertyDocumentRecord] = []
    for reason in normalized_reasons:
        mapped = _DOCUMENT_REASON_MAP.get(reason)
        if not mapped:
            continue
        document_type, question = mapped
        source_claim_id = f"missing.{reason}.{_hash(normalized_ref)}"
        claims.append(
            PropertyEvidenceClaim(
                claim_id=source_claim_id,
                property_ref=normalized_ref,
                claim_type="risk",
                text=f"Missing or unclear: {reason.replace('_', ' ')}.",
                source_type=source,
                source_ref=decision.decision_id,
                confidence="high",
                verification_state="missing",
                privacy_class="owner_private",
                allowed_outputs=["owner_private", "agent_share"],
            )
        )
        questions.append(
            AgentQuestionTask(
                property_ref=normalized_ref,
                question_text=question,
                reason_key=reason,
                source_claim_id=source_claim_id,
            )
        )
        if document_type not in {row.document_type for row in documents}:
            documents.append(
                PropertyDocumentRecord(
                    property_ref=normalized_ref,
                    document_type=document_type,
                    source="agent_request",
                    verification_state="missing",
                    linked_risks=[reason],
                )
            )

    suppression = []
    if decision_state == "rejected":
        suppression.append("Future searches can down-rank similar listings after owner review.")
    if documents:
        suppression.append("Do not suppress permanently until the missing document request is answered.")

    return PropertyDecisionLoopSnapshot(
        property_ref=normalized_ref,
        decision=decision,
        evidence_claims=claims,
        agent_question_tasks=questions,
        document_records=documents,
        suppression_explanation=suppression,
    )

