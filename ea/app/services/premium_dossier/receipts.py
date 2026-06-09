from __future__ import annotations

from app.services.premium_dossier.models import PremiumDossierQualityReport, PremiumDossierRenderResult


def build_premium_receipt(
    *,
    renderer_version: str,
    render_result: PremiumDossierRenderResult,
    quality_report: PremiumDossierQualityReport,
    base_receipt: dict[str, object],
    pdf_path: str,
) -> dict[str, object]:
    return {
        **dict(base_receipt or {}),
        "renderer_version": renderer_version,
        "renderer_provider": render_result.renderer,
        "renderer_kind": "premium_dossier_html_pdf" if render_result.renderer in {"markupgo", "playwright"} else "branded_visual_pdf",
        "fallback_used": render_result.renderer != "markupgo",
        "required_text_check": quality_report.required_text_check,
        "forbidden_text_check": quality_report.forbidden_text_check,
        "pdf_sha256": render_result.pdf_sha256,
        "source_pdf_size_bytes": len(render_result.pdf_bytes),
        "source_pdf_artifact_ref": pdf_path,
        "render_seconds": round(float(render_result.render_seconds or 0.0), 3),
        "provider_task_id": str(render_result.provider_task_id or "").strip(),
    }

