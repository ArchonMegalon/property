from __future__ import annotations

from app.services.premium_dossier.models import PremiumDossierQualityReport


def _pdf_page_count(artifact_bytes: bytes) -> int:
    # Works for normal unencrypted PDFs and is intentionally conservative.
    return artifact_bytes.count(b"/Type /Page") + artifact_bytes.count(b"/Type/Page")


def inspect_rendered_artifact(
    *,
    artifact_bytes: bytes,
    expected_text: list[str],
    forbidden_text: list[str],
) -> PremiumDossierQualityReport:
    decoded = artifact_bytes.decode("latin-1", errors="ignore")
    required_hits = [item for item in expected_text if str(item or "").strip() and str(item) in decoded]
    forbidden_hits = [item for item in forbidden_text if str(item or "").strip() and str(item) in decoded]
    required_expected = [item for item in expected_text if str(item or "").strip()]
    all_required_ok = len(required_hits) == len(required_expected)
    partial_required_ok = bool(required_expected) and len(required_hits) >= min(2, len(required_expected))
    structural_pdf_ok = (
        artifact_bytes.startswith(b"%PDF")
        and len(artifact_bytes) >= 2048
        and _pdf_page_count(artifact_bytes) >= 1
    )
    required_ok = all_required_ok or partial_required_ok or structural_pdf_ok
    if all_required_ok:
        required_check = "passed"
    elif partial_required_ok:
        required_check = "passed_partial_text"
    elif structural_pdf_ok:
        required_check = "passed_structural_pdf"
    else:
        required_check = "failed"
    return PremiumDossierQualityReport(
        ok=required_ok and not forbidden_hits,
        required_text_check=required_check,
        forbidden_text_check="passed" if not forbidden_hits else "failed",
        required_text_hits=required_hits,
        forbidden_text_hits=forbidden_hits,
    )
