from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.services.premium_dossier.models import PremiumDossierRenderRequest, PremiumDossierRenderResult


def _fallback_playwright_python() -> str:
    explicit = str(os.getenv("PROPERTYQUARRY_PLAYWRIGHT_PYTHON") or "").strip()
    if explicit:
        return explicit
    for candidate in ("/tmp/pq-playwright/bin/python", "/docker/property/.venv/bin/python"):
        if Path(candidate).exists():
            return candidate
    return sys.executable


def _playwright_browser_env() -> dict[str, str]:
    env = dict(os.environ)
    if str(env.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip():
        return env
    cache_path = Path.home() / ".cache" / "ms-playwright"
    if cache_path.exists():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache_path)
    return env


def _playwright_helper_code() -> str:
    return """
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def _is_local_asset(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.startswith(("file://", "data:", "blob:", "about:blank"))

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
html_path = Path(request["html_path"])
pdf_path = Path(request["pdf_path"])
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    try:
        page = browser.new_page()
        page.route("**/*", lambda route: route.continue_() if _is_local_asset(route.request.url) else route.abort())
        page.goto(html_path.as_uri(), wait_until="load")
        page.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    finally:
        browser.close()
"""


def _allow_local_playwright_request(url: str) -> bool:
    normalized = str(url or "").strip().lower()
    return normalized.startswith(("file://", "data:", "blob:", "about:blank"))


def _configure_local_only_page(page) -> None:
    page.route(
        "**/*",
        lambda route: route.continue_() if _allow_local_playwright_request(getattr(route.request, "url", "")) else route.abort(),
    )


def _render_pdf_via_helper_python(
    helper_python: str,
    request: PremiumDossierRenderRequest,
    *,
    started: float,
) -> PremiumDossierRenderResult:
    with tempfile.TemporaryDirectory(prefix="pq-premium-dossier-helper-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        request_path = tmp_path / "request.json"
        html_path = tmp_path / "dossier.html"
        pdf_path = tmp_path / "dossier.pdf"
        request_path.write_text(
            json.dumps({"html_path": str(html_path), "pdf_path": str(pdf_path)}, sort_keys=True),
            encoding="utf-8",
        )
        html_path.write_text(request.html, encoding="utf-8")
        completed = subprocess.run(
            [helper_python, "-c", _playwright_helper_code(), str(request_path)],
            text=True,
            capture_output=True,
            check=False,
            env=_playwright_browser_env(),
        )
        if completed.returncode != 0:
            return PremiumDossierRenderResult(
                status="failed",
                renderer="playwright",
                error_code="playwright_render_failed",
                error_detail=(completed.stderr or completed.stdout or "playwright_helper_failed").strip()[:300],
            )
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
    if not pdf_bytes.startswith(b"%PDF"):
        return PremiumDossierRenderResult(status="failed", renderer="playwright", error_code="playwright_invalid_pdf", error_detail="playwright_did_not_return_pdf")
    return PremiumDossierRenderResult(
        status="rendered",
        renderer="playwright",
        pdf_bytes=pdf_bytes,
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        render_seconds=time.time() - started,
    )


def render_pdf_with_playwright(request: PremiumDossierRenderRequest) -> PremiumDossierRenderResult:
    started = time.time()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        helper_python = _fallback_playwright_python()
        if helper_python != sys.executable:
            try:
                return _render_pdf_via_helper_python(helper_python, request, started=started)
            except Exception as helper_exc:
                return PremiumDossierRenderResult(
                    status="failed",
                    renderer="playwright",
                    error_code="playwright_missing",
                    error_detail=str(helper_exc or exc or "playwright_missing")[:240],
                )
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
                    _configure_local_only_page(page)
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
