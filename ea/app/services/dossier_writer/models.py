from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DossierClaimType = Literal[
    "fact",
    "risk",
    "missing_fact",
    "investment_assumption",
    "household_feedback",
    "location_signal",
    "agent_question",
]

DossierPrivacyMode = Literal[
    "owner_private",
    "family_review",
    "agent_share",
    "paid_customer",
    "anonymous_public",
]

DossierPacketKind = Literal[
    "owner_review",
    "family_review",
    "agent_brief",
    "paid_market_report",
    "public_city_guide",
    "investment_report",
]


class DossierEvidenceClaim(BaseModel):
    claim_id: str
    section_key: str
    claim_text: str
    claim_type: DossierClaimType
    confidence: Literal["high", "medium", "low"] = "medium"
    source_refs: list[str] = Field(default_factory=list)
    source_labels: list[str] = Field(default_factory=list)
    allowed_privacy_modes: list[DossierPrivacyMode]
    forbidden_privacy_modes: list[DossierPrivacyMode] = Field(default_factory=list)
    next_action: str = ""


class DossierSectionDraft(BaseModel):
    section_key: str
    title: str
    subtitle: str = ""
    claims_used: list[str]
    body_markdown: str
    bullets: list[str] = Field(default_factory=list)
    cta: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class DossierNarrativeDraft(BaseModel):
    dossier_id: str
    privacy_mode: DossierPrivacyMode
    packet_kind: DossierPacketKind
    language: str = "German"
    tone: str = "premium_analytical"
    sections: list[DossierSectionDraft]
    forbidden_text: list[str] = Field(default_factory=list)
    generated_by: str = "propertyquarry_dossier_writer"


class DossierOutlineSection(BaseModel):
    section_key: str
    title: str
    claim_types: list[DossierClaimType] = Field(default_factory=list)


class DossierOutline(BaseModel):
    packet_kind: DossierPacketKind
    sections: list[DossierOutlineSection]


class NeuronWriterRecommendation(BaseModel):
    status: Literal["disabled", "blocked", "ready", "pending", "failed"] = "disabled"
    mode: str = "none"
    query_id: str = ""
    query_url: str = ""
    share_url: str = ""
    readonly_url: str = ""
    headings: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    reason: str = ""
    raw: dict[str, object] = Field(default_factory=dict)


class VerifiedDossierNarrative(BaseModel):
    draft: DossierNarrativeDraft
    status: Literal["verified", "rejected"]
    unsupported_sentences: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)
    claim_coverage: dict[str, object] = Field(default_factory=dict)
    neuronwriter: NeuronWriterRecommendation | None = None
