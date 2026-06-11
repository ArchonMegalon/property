from __future__ import annotations

import re

from app.services.premium_dossier.models import PremiumDossierQualityReport


def _pdf_page_count(artifact_bytes: bytes) -> int:
    # Works for normal unencrypted PDFs and is intentionally conservative.
    return artifact_bytes.count(b"/Type /Page") + artifact_bytes.count(b"/Type/Page")


def _extract_pdf_text(artifact_bytes: bytes) -> str:
    if not artifact_bytes.startswith(b"%PDF"):
        return ""
    try:
        from io import BytesIO

        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(BytesIO(artifact_bytes))
        pages_text: list[str] = []
        for index, page in enumerate(pdf):
            if index >= 20:
                break
            pages_text.append(str(page.get_textpage().get_text_range() or ""))
        return "\n".join(pages_text)
    except Exception:
        pass
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(artifact_bytes))
        return "\n".join(str(page.extract_text() or "") for page in reader.pages[:20])
    except Exception:
        return ""


def _text_variants(value: str) -> set[str]:
    raw = str(value or "")
    collapsed = re.sub(r"\s+", " ", raw).strip()
    compact = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", raw).casefold()
    return {item for item in {raw, collapsed, compact} if item}


def _contains_text(haystack: str, needle: str) -> bool:
    if not str(needle or "").strip():
        return False
    haystack_variants = _text_variants(haystack)
    needle_variants = _text_variants(needle)
    return any(
        variant in haystack
        or variant in haystack_variants
        or (variant and any(variant in hay_variant for hay_variant in haystack_variants))
        for variant in needle_variants
    )


def inspect_rendered_artifact(
    *,
    artifact_bytes: bytes,
    expected_text: list[str],
    forbidden_text: list[str],
) -> PremiumDossierQualityReport:
    decoded = "\n".join(
        part
        for part in (
            _extract_pdf_text(artifact_bytes),
            artifact_bytes.decode("latin-1", errors="ignore"),
        )
        if part
    )
    required_hits = [item for item in expected_text if _contains_text(decoded, str(item or ""))]
    forbidden_hits = [item for item in forbidden_text if _contains_text(decoded, str(item or ""))]
    required_expected = [item for item in expected_text if str(item or "").strip()]
    all_required_ok = len(required_hits) == len(required_expected)
    required_ok = all_required_ok
    if all_required_ok:
        required_check = "passed"
    else:
        required_check = "failed"
    return PremiumDossierQualityReport(
        ok=required_ok and not forbidden_hits,
        required_text_check=required_check,
        forbidden_text_check="passed" if not forbidden_hits else "failed",
        required_text_hits=required_hits,
        forbidden_text_hits=forbidden_hits,
    )
