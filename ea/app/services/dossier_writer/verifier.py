from __future__ import annotations

import re

from app.services.dossier_writer.models import DossierEvidenceClaim, DossierNarrativeDraft, NeuronWriterRecommendation, VerifiedDossierNarrative
from app.services.dossier_writer.style import FORBIDDEN_UNSUPPORTED_PHRASES


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text or "").strip()) if part.strip()]


def verify_dossier_narrative(
    draft: DossierNarrativeDraft,
    *,
    claims: list[DossierEvidenceClaim],
    neuronwriter: NeuronWriterRecommendation | None = None,
    forbidden_text: list[str] | None = None,
) -> VerifiedDossierNarrative:
    claim_map = {claim.claim_id: claim for claim in claims}
    unsupported: list[str] = []
    forbidden_hits: list[str] = []
    forbidden = [*FORBIDDEN_UNSUPPORTED_PHRASES, *list(forbidden_text or []), *draft.forbidden_text]
    for section in draft.sections:
        section_claim_text = " ".join(claim_map[claim_id].claim_text for claim_id in section.claims_used if claim_id in claim_map).lower()
        for sentence in _sentences(section.body_markdown):
            lowered = sentence.lower()
            if any(hit.lower() in lowered for hit in forbidden if hit):
                forbidden_hits.append(sentence)
            factualish = any(char.isdigit() for char in sentence) or any(token in lowered for token in ("cost", "heating", "risk", "price", "yield", "school", "route", "betriebskosten"))
            if factualish and not any(word and word in section_claim_text for word in re.findall(r"[a-zA-ZÄÖÜäöüß0-9-]{5,}", lowered)[:8]):
                unsupported.append(sentence)
    used = {claim_id for section in draft.sections for claim_id in section.claims_used}
    status = "verified" if not unsupported and not forbidden_hits else "rejected"
    return VerifiedDossierNarrative(
        draft=draft,
        status=status,  # type: ignore[arg-type]
        unsupported_sentences=unsupported,
        forbidden_hits=forbidden_hits,
        claim_coverage={
            "claims_total": len(claims),
            "claims_used": len(used),
            "unsupported_sentences": len(unsupported),
            "forbidden_hits": len(forbidden_hits),
        },
        neuronwriter=neuronwriter,
    )
