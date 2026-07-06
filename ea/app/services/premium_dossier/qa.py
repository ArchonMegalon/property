from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from app.services.premium_dossier.models import PremiumDossierQualityReport


def _helper_python() -> str:
    explicit = str(os.getenv("PROPERTYQUARRY_DOSSIER_QA_PYTHON") or os.getenv("PROPERTYQUARRY_PLAYWRIGHT_PYTHON") or "").strip()
    if explicit:
        return explicit
    for candidate in ("/docker/property/.venv/bin/python", "/tmp/pq-playwright/bin/python"):
        if Path(candidate).exists():
            return candidate
    return sys.executable


def _qa_helper_code() -> str:
    return """
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

mode = sys.argv[1]
pdf_path = Path(sys.argv[2])
payload = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
artifact_bytes = pdf_path.read_bytes()

def extract_text(artifact_bytes):
    if not artifact_bytes.startswith(b"%PDF"):
        return ""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(BytesIO(artifact_bytes))
        pages_text = []
        for index, page in enumerate(pdf):
            if index >= 20:
                break
            pages_text.append(str(page.get_textpage().get_text_range() or ""))
        return "\\n".join(pages_text)
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(artifact_bytes))
        text = "\\n".join(str(page.extract_text() or "") for page in reader.pages[:20])
        return text.strip() and text or ""
    except Exception:
        return ""

def render_preview(artifact_bytes, output_path):
    if not artifact_bytes.startswith(b"%PDF"):
        return {"png_b64": "", "width": 0, "height": 0}
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(BytesIO(artifact_bytes))
        if len(pdf) < 1:
            return {"png_b64": "", "width": 0, "height": 0}
        page = pdf[0]
        bitmap = page.render(scale=1.5)
        image = bitmap.to_pil()
        width, height = image.size
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
        if output_path:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png_bytes)
        return {"png_b64": base64.b64encode(png_bytes).decode("ascii"), "width": width, "height": height}
    except Exception as exc:
        return {"png_b64": "", "width": 0, "height": 0, "error": str(exc)}

if mode == "text":
    print(json.dumps({"text": extract_text(artifact_bytes)}))
elif mode == "preview":
    print(json.dumps(render_preview(artifact_bytes, str(payload.get("output_path") or "").strip())))
else:
    raise SystemExit(f"unsupported mode: {mode}")
"""


def _run_helper(mode: str, artifact_bytes: bytes, *, output_path: str | Path | None = None) -> dict[str, object]:
    helper_python = _helper_python()
    helper_candidate = Path(helper_python).expanduser().absolute()
    current_python = Path(sys.executable).expanduser().absolute()
    if str(helper_candidate) == str(current_python):
        return {}
    with tempfile.TemporaryDirectory(prefix="pq-premium-dossier-qa-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        pdf_path = tmp_path / "artifact.pdf"
        request_path = tmp_path / "request.json"
        pdf_path.write_bytes(artifact_bytes)
        request_path.write_text(
            json.dumps({"output_path": str(output_path or "")}, sort_keys=True),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [helper_python, "-c", _qa_helper_code(), mode, str(pdf_path), str(request_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return {}
        try:
            return json.loads(completed.stdout.strip() or "{}")
        except Exception:
            return {}


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
    helper_payload = _run_helper("text", artifact_bytes)
    helper_text = str(helper_payload.get("text") or "")
    if helper_text.strip():
        return helper_text
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
        helper_payload = _run_helper("preview", artifact_bytes, output_path=output_path)
        png_b64 = str(helper_payload.get("png_b64") or "")
        if not png_b64:
            return b"", 0, 0
        try:
            png_bytes = base64.b64decode(png_b64.encode("ascii"))
        except Exception:
            return b"", 0, 0
        return png_bytes, int(helper_payload.get("width") or 0), int(helper_payload.get("height") or 0)


def _png_visual_metrics(png_bytes: bytes) -> tuple[float, float, float]:
    if not png_bytes:
        return 0.0, 0.0, 0.0
    try:
        from PIL import Image

        def _count_nonwhite(image: "Image.Image") -> tuple[int, int]:
            width, height = image.size
            if width <= 0 or height <= 0:
                return 0, 0
            pixels = image.load()
            total = width * height
            nonwhite = 0
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    if (r + g + b) < 740:
                        nonwhite += 1
            return nonwhite, total

        with Image.open(BytesIO(png_bytes)) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            nonwhite, total = _count_nonwhite(rgb)
            total = max(1, total)
            top_height = max(1, int(height * 0.45))
            top_nonwhite, top_total = _count_nonwhite(rgb.crop((0, 0, width, top_height)))
            top_total = max(1, top_total)
            footer_height = max(1, int(height * 0.08))
            footer_nonwhite, footer_total = _count_nonwhite(rgb.crop((0, max(0, height - footer_height), width, height)))
            footer_total = max(1, footer_total)
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
    supplemental_required_text: str = "",
    preview_output_path: str | Path | None = None,
    require_cover_visual_dominance: bool = False,
    require_footer_band: bool = False,
    forbid_raw_url_text: bool = False,
) -> PremiumDossierQualityReport:
    extracted_text = _extract_pdf_text(artifact_bytes)
    binary_text = artifact_bytes.decode("latin-1", errors="ignore")
    required_source = "\n".join(part for part in (extracted_text, supplemental_required_text) if str(part or "").strip())
    required_hits = [item for item in expected_text if _contains_text(required_source, str(item or ""))]
    decoded = "\n".join(part for part in (extracted_text, binary_text) if part)
    forbidden_hits = [item for item in forbidden_text if _contains_text(decoded, str(item or ""))]
    raw_url_source = (
        supplemental_required_text
        if str(supplemental_required_text or "").strip()
        else (extracted_text if str(extracted_text or "").strip() else binary_text)
    )
    raw_url_hits = _raw_url_text_hits(raw_url_source) if forbid_raw_url_text else []
    required_expected = [item for item in expected_text if str(item or "").strip()]
    all_required_ok = len(required_hits) == len(required_expected)
    required_ok = all_required_ok
    page_count = _pdf_page_count(artifact_bytes)
    preview_required = bool(preview_output_path or require_cover_visual_dominance or require_footer_band)
    preview_png, preview_width, preview_height = _render_pdf_first_page_png(artifact_bytes, output_path=preview_output_path)
    nonwhite_ratio, top_band_nonwhite_ratio, footer_band_nonwhite_ratio = _png_visual_metrics(preview_png)
    if preview_png:
        visual_preview_check = "passed" if nonwhite_ratio >= 0.02 and top_band_nonwhite_ratio >= 0.02 else "failed"
        cover_dominance_check = "passed" if (not require_cover_visual_dominance or top_band_nonwhite_ratio >= 0.08) else "failed"
        footer_band_check = "passed" if (not require_footer_band or footer_band_nonwhite_ratio >= 0.01) else "failed"
    else:
        visual_preview_check = "failed" if preview_required else "not_run"
        cover_dominance_check = "failed" if require_cover_visual_dominance else "not_run"
        footer_band_check = "failed" if require_footer_band else "not_run"
    raw_url_text_check = "passed" if not raw_url_hits else "failed"
    if all_required_ok:
        required_check = "passed"
    else:
        required_check = "failed"
    return PremiumDossierQualityReport(
        ok=required_ok
        and not forbidden_hits
        and not raw_url_hits
        and visual_preview_check != "failed"
        and cover_dominance_check != "failed"
        and footer_band_check != "failed",
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
