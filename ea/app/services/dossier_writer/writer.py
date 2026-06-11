from __future__ import annotations

from collections import defaultdict

from app.services.dossier_writer.models import (
    DossierEvidenceClaim,
    DossierNarrativeDraft,
    DossierPacketKind,
    DossierPrivacyMode,
    DossierSectionDraft,
)
from app.services.dossier_writer.planner import plan_dossier_outline
from app.services.dossier_writer.redaction import redact_claims_for_privacy
from app.services.dossier_writer.style import premium_sentence


def _section_body(claims: list[DossierEvidenceClaim]) -> str:
    sentences = [premium_sentence(claim.claim_text) for claim in claims if claim.claim_text]
    actions = [premium_sentence(claim.next_action) for claim in claims if claim.next_action]
    body = " ".join(sentence for sentence in sentences if sentence)
    if actions:
        body = f"{body} Next action: {' '.join(actions)}".strip()
    return body


def write_claim_bound_dossier(
    *,
    dossier_id: str,
    claims: list[DossierEvidenceClaim],
    packet_kind: DossierPacketKind,
    privacy_mode: DossierPrivacyMode,
    language: str = "German",
    tone: str = "premium_analytical",
) -> DossierNarrativeDraft:
    safe_claims = redact_claims_for_privacy(claims, privacy_mode=privacy_mode)
    by_section: dict[str, list[DossierEvidenceClaim]] = defaultdict(list)
    for claim in safe_claims:
        by_section[claim.section_key].append(claim)
    outline = plan_dossier_outline(packet_kind)
    sections: list[DossierSectionDraft] = []
    for outline_section in outline.sections:
        section_claims = list(by_section.get(outline_section.section_key) or [])
        if not section_claims:
            section_claims = [
                claim
                for claim in safe_claims
                if claim.claim_type in outline_section.claim_types and claim.claim_id not in {used for section in sections for used in section.claims_used}
            ][:4]
        if not section_claims:
            continue
        confidence_order = {"high": 3, "medium": 2, "low": 1}
        confidence = min(section_claims, key=lambda claim: confidence_order.get(claim.confidence, 2)).confidence
        sections.append(
            DossierSectionDraft(
                section_key=outline_section.section_key,
                title=outline_section.title,
                claims_used=[claim.claim_id for claim in section_claims],
                body_markdown=_section_body(section_claims),
                bullets=[claim.claim_text for claim in section_claims[:5]],
                cta=next((claim.next_action for claim in section_claims if claim.next_action), ""),
                confidence=confidence,
            )
        )
    return DossierNarrativeDraft(
        dossier_id=dossier_id,
        privacy_mode=privacy_mode,
        packet_kind=packet_kind,
        language=language,
        tone=tone,
        sections=sections,
        forbidden_text=[],
        generated_by="propertyquarry_dossier_writer.claim_bound.v1",
    )
