from __future__ import annotations

from app.services.dossier_writer.models import DossierEvidenceClaim, DossierPrivacyMode


PRIVATE_MARKERS = (
    "principal",
    "household",
    "private preference",
    "exact address",
    "raw source",
    "unpublished",
    "personal",
)


def claim_allowed_for_privacy(claim: DossierEvidenceClaim, privacy_mode: DossierPrivacyMode) -> bool:
    if privacy_mode in claim.forbidden_privacy_modes:
        return False
    return privacy_mode in claim.allowed_privacy_modes


def redact_claims_for_privacy(
    claims: list[DossierEvidenceClaim],
    *,
    privacy_mode: DossierPrivacyMode,
) -> list[DossierEvidenceClaim]:
    return [claim for claim in claims if claim_allowed_for_privacy(claim, privacy_mode)]


def public_safe_topic_text(value: object, *, limit: int = 4000) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split()).strip()
    for marker in PRIVATE_MARKERS:
        text = text.replace(marker, "")
    return text[:limit].strip()
