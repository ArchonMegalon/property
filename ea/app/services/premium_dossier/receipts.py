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
        "page_count": int(quality_report.page_count or 0),
        "visual_preview_check": quality_report.visual_preview_check,
        "cover_dominance_check": quality_report.cover_dominance_check,
        "footer_band_check": quality_report.footer_band_check,
        "raw_url_text_check": quality_report.raw_url_text_check,
        "visual_preview_artifact_ref": quality_report.visual_preview_artifact_ref,
        "first_page_width_px": int(quality_report.first_page_width_px or 0),
        "first_page_height_px": int(quality_report.first_page_height_px or 0),
        "first_page_nonwhite_ratio": round(float(quality_report.first_page_nonwhite_ratio or 0.0), 4),
        "first_page_top_band_nonwhite_ratio": round(float(quality_report.first_page_top_band_nonwhite_ratio or 0.0), 4),
        "first_page_footer_band_nonwhite_ratio": round(float(quality_report.first_page_footer_band_nonwhite_ratio or 0.0), 4),
        "raw_url_text_hits": list(quality_report.raw_url_text_hits or []),
        "pdf_sha256": render_result.pdf_sha256,
        "source_pdf_size_bytes": len(render_result.pdf_bytes),
        "source_pdf_artifact_ref": pdf_path,
        "render_seconds": round(float(render_result.render_seconds or 0.0), 3),
        "provider_task_id": str(render_result.provider_task_id or "").strip(),
    }
