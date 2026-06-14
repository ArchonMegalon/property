from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from app.services.premium_dossier.models import PremiumDossierQualityReport


def _pdf_page_count(artifact_bytes: bytes) -> int:
    # Works for normal unencrypted PDFs and is intentionally conservative.
    return artifact_bytes.count(b"/Type /Page") + artifact_bytes.count(b"/Type/Page")


def _extract_pdf_text(artifact_bytes: bytes) -> str:
    if not artifact_bytes.startswith(b"%PDF"):
        return ""
    try:
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
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(artifact_bytes))
        text = "\n".join(str(page.extract_text() or "") for page in reader.pages[:20])
        if text.strip():
            return text
    except Exception:
        pass
    return ""


def _render_pdf_first_page_png(artifact_bytes: bytes, *, output_path: str | Path | None = None) -> tuple[bytes, int, int]:
    if not artifact_bytes.startswith(b"%PDF"):
        return b"", 0, 0
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(BytesIO(artifact_bytes))
        if len(pdf) < 1:
            return b"", 0, 0
        page = pdf[0]
        bitmap = page.render(scale=1.5)
        image = bitmap.to_pil()
        width, height = image.size
        png_buffer = BytesIO()
        image.save(png_buffer, format="PNG")
        png_bytes = png_buffer.getvalue()
        if output_path:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png_bytes)
        return png_bytes, int(width), int(height)
    except Exception:
        return b"", 0, 0


def _png_visual_metrics(png_bytes: bytes) -> tuple[float, float, float]:
    if not png_bytes:
        return 0.0, 0.0, 0.0
    try:
        from PIL import Image

        with Image.open(BytesIO(png_bytes)) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            pixels = list(rgb.getdata())
            total = max(1, len(pixels))
            nonwhite = sum(1 for (r, g, b) in pixels if (r + g + b) < 740)
            top_height = max(1, int(height * 0.45))
            top_pixels = list(rgb.crop((0, 0, width, top_height)).getdata())
            top_total = max(1, len(top_pixels))
            top_nonwhite = sum(1 for (r, g, b) in top_pixels if (r + g + b) < 740)
            footer_height = max(1, int(height * 0.08))
            footer_pixels = list(rgb.crop((0, max(0, height - footer_height), width, height)).getdata())
            footer_total = max(1, len(footer_pixels))
            footer_nonwhite = sum(1 for (r, g, b) in footer_pixels if (r + g + b) < 740)
            return round(nonwhite / total, 4), round(top_nonwhite / top_total, 4), round(footer_nonwhite / footer_total, 4)
    except Exception:
        return 0.0, 0.0, 0.0


def _raw_url_text_hits(decoded_text: str) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(https?://[^\s<>()]+|www\.[^\s<>()]+)", str(decoded_text or ""), flags=re.IGNORECASE):
        value = str(match.group(1) or "").strip().rstrip(".,);")
        if value and value not in seen:
            seen.add(value)
            hits.append(value[:200])
    return hits


def _text_variants(value: str) -> set[str]:
    raw = str(value or "")
    collapsed = re.sub(r"\s+", " ", raw).strip()
    compact = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", raw).casefold()
    return {item for item in {raw, collapsed, compact} if item}


def _contains_text(haystack: str, needle: str) -> bool:
    if not str(needle or "").strip():
        return False
    haystack_text = str(haystack or "")
    haystack_collapsed = re.sub(r"\s+", " ", haystack_text).strip().casefold()
    haystack_compact = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", haystack_text).casefold()
    needle_text = str(needle or "")
    needle_collapsed = re.sub(r"\s+", " ", needle_text).strip().casefold()
    needle_compact = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", needle_text).casefold()
    return bool(
        (needle_text and needle_text in haystack_text)
        or (needle_collapsed and needle_collapsed in haystack_collapsed)
        or (needle_compact and needle_compact in haystack_compact)
    )


def inspect_rendered_artifact(
    *,
    artifact_bytes: bytes,
    expected_text: list[str],
    forbidden_text: list[str],
    preview_output_path: str | Path | None = None,
    require_cover_visual_dominance: bool = False,
    require_footer_band: bool = False,
    forbid_raw_url_text: bool = False,
) -> PremiumDossierQualityReport:
    extracted_text = _extract_pdf_text(artifact_bytes)
    binary_text = artifact_bytes.decode("latin-1", errors="ignore")
    required_hits = [item for item in expected_text if _contains_text(extracted_text, str(item or ""))]
    decoded = "\n".join(part for part in (extracted_text, binary_text) if part)
    forbidden_hits = [item for item in forbidden_text if _contains_text(decoded, str(item or ""))]
    raw_url_source = extracted_text if str(extracted_text or "").strip() else binary_text
    raw_url_hits = _raw_url_text_hits(raw_url_source) if forbid_raw_url_text else []
    required_expected = [item for item in expected_text if str(item or "").strip()]
    all_required_ok = len(required_hits) == len(required_expected)
    required_ok = all_required_ok
    page_count = _pdf_page_count(artifact_bytes)
    preview_png, preview_width, preview_height = _render_pdf_first_page_png(artifact_bytes, output_path=preview_output_path)
    nonwhite_ratio, top_band_nonwhite_ratio, footer_band_nonwhite_ratio = _png_visual_metrics(preview_png)
    if preview_png:
        visual_preview_check = "passed" if nonwhite_ratio >= 0.02 and top_band_nonwhite_ratio >= 0.02 else "failed"
        cover_dominance_check = "passed" if (not require_cover_visual_dominance or top_band_nonwhite_ratio >= 0.08) else "failed"
        footer_band_check = "passed" if (not require_footer_band or footer_band_nonwhite_ratio >= 0.01) else "failed"
    else:
        visual_preview_check = "not_run"
        cover_dominance_check = "not_run"
        footer_band_check = "not_run"
    raw_url_text_check = "passed" if not raw_url_hits else "failed"
    if all_required_ok:
        required_check = "passed"
    else:
        required_check = "failed"
    return PremiumDossierQualityReport(
        ok=required_ok and not forbidden_hits and not raw_url_hits and visual_preview_check != "failed" and cover_dominance_check != "failed" and footer_band_check != "failed",
        required_text_check=required_check,
        forbidden_text_check="passed" if not forbidden_hits else "failed",
        page_count=page_count,
        visual_preview_check=visual_preview_check,
        cover_dominance_check=cover_dominance_check,
        footer_band_check=footer_band_check,
        raw_url_text_check=raw_url_text_check,
        visual_preview_artifact_ref=str(preview_output_path or "").strip(),
        first_page_width_px=preview_width,
        first_page_height_px=preview_height,
        first_page_nonwhite_ratio=nonwhite_ratio,
        first_page_top_band_nonwhite_ratio=top_band_nonwhite_ratio,
        first_page_footer_band_nonwhite_ratio=footer_band_nonwhite_ratio,
        required_text_hits=required_hits,
        forbidden_text_hits=forbidden_hits,
        raw_url_text_hits=raw_url_hits,
    )
