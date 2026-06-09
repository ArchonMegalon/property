from __future__ import annotations

from app.services.premium_dossier.models import PremiumDossierQualityReport


def inspect_rendered_artifact(
    *,
    artifact_bytes: bytes,
    expected_text: list[str],
    forbidden_text: list[str],
) -> PremiumDossierQualityReport:
    decoded = artifact_bytes.decode("latin-1", errors="ignore")
    required_hits = [item for item in expected_text if str(item or "").strip() and str(item) in decoded]
    forbidden_hits = [item for item in forbidden_text if str(item or "").strip() and str(item) in decoded]
    return PremiumDossierQualityReport(
        ok=len(required_hits) == len([item for item in expected_text if str(item or "").strip()]) and not forbidden_hits,
        required_text_check="passed" if len(required_hits) == len([item for item in expected_text if str(item or "").strip()]) else "failed",
        forbidden_text_check="passed" if not forbidden_hits else "failed",
        required_text_hits=required_hits,
        forbidden_text_hits=forbidden_hits,
    )

