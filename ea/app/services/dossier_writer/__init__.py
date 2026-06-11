from __future__ import annotations

from app.services.dossier_writer.evidence import claims_from_deep_research
from app.services.dossier_writer.models import (
    DossierEvidenceClaim,
    DossierNarrativeDraft,
    DossierSectionDraft,
    NeuronWriterRecommendation,
    VerifiedDossierNarrative,
)
from app.services.dossier_writer.neuronwriter_adapter import recommend_for_draft
from app.services.dossier_writer.verifier import verify_dossier_narrative
from app.services.dossier_writer.writer import write_claim_bound_dossier


def write_verified_dossier_from_research(
    *,
    dossier_id: str,
    research: dict[str, object],
    packet_kind: str,
    privacy_mode: str,
    language: str = "German",
    neuronwriter_query_id: str = "",
) -> VerifiedDossierNarrative:
    claims = claims_from_deep_research(research)
    draft = write_claim_bound_dossier(
        dossier_id=dossier_id,
        claims=claims,
        packet_kind=packet_kind,  # type: ignore[arg-type]
        privacy_mode=privacy_mode,  # type: ignore[arg-type]
        language=language,
    )
    neuronwriter = recommend_for_draft(draft, query_id=neuronwriter_query_id)
    return verify_dossier_narrative(draft, claims=claims, neuronwriter=neuronwriter)


__all__ = [
    "DossierEvidenceClaim",
    "DossierNarrativeDraft",
    "DossierSectionDraft",
    "NeuronWriterRecommendation",
    "VerifiedDossierNarrative",
    "claims_from_deep_research",
    "recommend_for_draft",
    "verify_dossier_narrative",
    "write_claim_bound_dossier",
    "write_verified_dossier_from_research",
]
