from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from app.services.premium_dossier.models import PremiumDossierRenderRequest, PremiumDossierRenderResult


def markupgo_enabled() -> bool:
    return bool(str(os.getenv("PROPERTYQUARRY_DOSSIER_REMOTE_RENDER_ALLOWED") or "").strip() in {"1", "true", "yes"})


def markupgo_api_key() -> str:
    return str(os.getenv("MARKUPGO_API_KEY") or "").strip()


def markupgo_base_url() -> str:
    return str(os.getenv("MARKUPGO_BASE_URL") or "https://api.markupgo.com/api/v1").strip().rstrip("/")


def render_pdf_with_markupgo(request: PremiumDossierRenderRequest) -> PremiumDossierRenderResult:
    if not markupgo_enabled():
        return PremiumDossierRenderResult(status="failed", renderer="markupgo", error_code="markupgo_disabled", error_detail="remote_render_disabled")
    api_key = markupgo_api_key()
    if not api_key:
        return PremiumDossierRenderResult(status="failed", renderer="markupgo", error_code="markupgo_api_key_missing", error_detail="markupgo_api_key_missing")
    started = time.time()
    endpoint = str(os.getenv("MARKUPGO_PDF_BUFFER_ENDPOINT") or f"{markupgo_base_url()}/pdf/buffer").strip()
    body = {
        "html": request.html,
        "metadata": {
            "title": request.title,
            "dossier_id": request.dossier_id,
            "renderer_version": request.renderer_version,
        },
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "PropertyQuarry-MarkupGo/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(int(str(os.getenv("PROPERTYQUARRY_DOSSIER_MAX_RENDER_SECONDS") or "90").strip() or "90"), 5)) as response:
            pdf_bytes = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        return PremiumDossierRenderResult(status="failed", renderer="markupgo", error_code=f"markupgo_http_{exc.code}", error_detail=detail or "markupgo_http_error")
    except Exception as exc:
        return PremiumDossierRenderResult(status="failed", renderer="markupgo", error_code="markupgo_transport_error", error_detail=str(exc or "markupgo_transport_error")[:300])
    if not pdf_bytes.startswith(b"%PDF"):
        return PremiumDossierRenderResult(status="failed", renderer="markupgo", error_code="markupgo_invalid_pdf", error_detail="markupgo_did_not_return_pdf")
    return PremiumDossierRenderResult(
        status="rendered",
        renderer="markupgo",
        pdf_bytes=pdf_bytes,
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        render_seconds=time.time() - started,
    )

