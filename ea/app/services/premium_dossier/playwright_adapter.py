from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

from app.services.premium_dossier.models import PremiumDossierRenderRequest, PremiumDossierRenderResult


def render_pdf_with_playwright(request: PremiumDossierRenderRequest) -> PremiumDossierRenderResult:
    started = time.time()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return PremiumDossierRenderResult(status="failed", renderer="playwright", error_code="playwright_missing", error_detail=str(exc or "playwright_missing")[:240])
    try:
        with tempfile.TemporaryDirectory(prefix="pq-premium-dossier-") as tmp_dir:
            html_path = Path(tmp_dir) / "dossier.html"
            pdf_path = Path(tmp_dir) / "dossier.pdf"
            html_path.write_text(request.html, encoding="utf-8")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                try:
                    page = browser.new_page()
                    page.goto(html_path.as_uri(), wait_until="load")
                    page.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
                finally:
                    browser.close()
            pdf_bytes = pdf_path.read_bytes()
    except Exception as exc:
        return PremiumDossierRenderResult(status="failed", renderer="playwright", error_code="playwright_render_failed", error_detail=str(exc or "playwright_render_failed")[:300])
    if not pdf_bytes.startswith(b"%PDF"):
        return PremiumDossierRenderResult(status="failed", renderer="playwright", error_code="playwright_invalid_pdf", error_detail="playwright_did_not_return_pdf")
    return PremiumDossierRenderResult(
        status="rendered",
        renderer="playwright",
        pdf_bytes=pdf_bytes,
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        render_seconds=time.time() - started,
    )
