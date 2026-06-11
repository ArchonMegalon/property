from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.privacy import REDACTION_POLICY_VERSION, redact_property_packet
from app.services.premium_dossier.compiler import compile_premium_dossier
from app.services.premium_dossier.html import render_premium_dossier_html
from app.services.premium_dossier.markupgo_adapter import render_pdf_with_markupgo
from app.services.premium_dossier.models import PremiumDossierQualityReport, PremiumDossierRenderRequest, PremiumDossierRenderResult
from app.services.premium_dossier.playwright_adapter import render_pdf_with_playwright
from app.services.premium_dossier.qa import inspect_rendered_artifact
from app.services.premium_dossier.receipts import build_premium_receipt


PREMIUM_DOSSIER_RENDERER_VERSION = "v1_premium_markupgo_dossier"
PREMIUM_DOSSIER_FALLBACK_VERSION = "v1_premium_playwright_dossier"


def _renderer_chain() -> list[str]:
    primary = str(os.getenv("PROPERTYQUARRY_DOSSIER_RENDERER") or "").strip().lower()
    fallback = str(os.getenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK") or "").strip().lower()
    if not primary:
        primary = "playwright"
    chain: list[str] = []
    legacy_allowed = str(os.getenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW") or "").strip().lower() in {"1", "true", "yes", "on"}
    for name in (primary, fallback):
        if name and name not in chain:
            if name == "legacy" and not legacy_allowed:
                continue
            chain.append(name)
    return chain


def _payload_has_private_reference_media(payload: dict[str, object]) -> bool:
    if payload.get("personal_reference_urls"):
        return True
    magic_fit_scene = payload.get("magic_fit_scene")
    if isinstance(magic_fit_scene, dict) and magic_fit_scene.get("reference_urls"):
        return True
    return False


def _private_reference_remote_allowed() -> bool:
    return str(os.getenv("PROPERTYQUARRY_DOSSIER_ALLOW_PRIVATE_REFERENCES_REMOTE") or "").strip().lower() in {"1", "true", "yes", "on"}


def render_property_packet_pdf_via_premium_pipeline(
    *,
    artifact_root: Path,
    publication_id: str,
    principal_id: str,
    source: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    include_exact_address: bool,
    include_floorplan: bool,
    include_photos: bool,
    legacy_renderer: Callable[..., dict[str, object]],
) -> dict[str, object]:
    redaction = redact_property_packet(
        source=source,
        privacy_mode=privacy_mode,
        packet_kind=packet_kind,
        include_exact_address=include_exact_address,
        include_floorplan=include_floorplan,
        include_photos=include_photos,
    )
    if str(redaction.payload.get("appendix_mode") or "").strip().lower() == "telegram_pdf_appendix":
        return legacy_renderer(
            artifact_root=artifact_root,
            publication_id=publication_id,
            principal_id=principal_id,
            source=source,
            packet_kind=packet_kind,
            privacy_mode=privacy_mode,
            fliplink_format=fliplink_format,
            include_exact_address=include_exact_address,
            include_floorplan=include_floorplan,
            include_photos=include_photos,
        )
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=redaction.payload,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        renderer_version=PREMIUM_DOSSIER_RENDERER_VERSION,
    )
    private_reference_media_included = _payload_has_private_reference_media(source) or _payload_has_private_reference_media(redaction.payload)
    html = render_premium_dossier_html(compiled, principal_id=principal_id)
    request = PremiumDossierRenderRequest(
        dossier_id=publication_id,
        renderer_version=PREMIUM_DOSSIER_RENDERER_VERSION,
        html=html,
        title=compiled.title,
        privacy_mode=privacy_mode.value,
        packet_kind=packet_kind.value,
        metadata={"publication_id": publication_id},
        expected_text=["PropertyQuarry", compiled.title, compiled.recommendation or "Vertieft prüfen"],
        forbidden_text=["principal_id", "token", "session", "cookie"],
    )
    render_result: PremiumDossierRenderResult | None = None
    quality_report: PremiumDossierQualityReport | None = None
    render_failures: list[dict[str, object]] = []
    for renderer_name in _renderer_chain():
        if renderer_name == "markupgo":
            if private_reference_media_included and not _private_reference_remote_allowed():
                render_failures.append(
                    {
                        "renderer": "markupgo",
                        "error_code": "markupgo_private_reference_media_blocked",
                        "error_detail": "Private reference media requires local rendering unless explicit remote consent is enabled.",
                    }
                )
                continue
            result = render_pdf_with_markupgo(request)
        elif renderer_name == "playwright":
            result = render_pdf_with_playwright(request)
        else:
            break
        if result.status == "rendered":
            candidate_quality = inspect_rendered_artifact(
                artifact_bytes=result.pdf_bytes,
                expected_text=request.expected_text,
                forbidden_text=request.forbidden_text,
            )
            if candidate_quality.ok:
                render_result = result
                quality_report = candidate_quality
                break
            render_failures.append(
                {
                    "renderer": result.renderer,
                    "error_code": "premium_pdf_quality_gate_failed",
                    "required_text_check": candidate_quality.required_text_check,
                    "forbidden_text_check": candidate_quality.forbidden_text_check,
                    "forbidden_hits": candidate_quality.forbidden_text_hits[:3],
                }
            )
        elif result.error_code:
            render_failures.append({"renderer": result.renderer, "error_code": result.error_code, "error_detail": result.error_detail})
    if render_result is None:
        if str(os.getenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError(
                "premium_dossier_render_failed:"
                + ",".join(str(item.get("error_code") or item.get("renderer") or "unknown") for item in render_failures[:5])
            )
        legacy_rendered = legacy_renderer(
            artifact_root=artifact_root,
            publication_id=publication_id,
            principal_id=principal_id,
            source=source,
            packet_kind=packet_kind,
            privacy_mode=privacy_mode,
            fliplink_format=fliplink_format,
            include_exact_address=include_exact_address,
            include_floorplan=include_floorplan,
            include_photos=include_photos,
        )
        if isinstance(legacy_rendered, dict) and render_failures:
            receipt = legacy_rendered.get("receipt") if isinstance(legacy_rendered.get("receipt"), dict) else {}
            receipt = {**dict(receipt), "premium_render_failures": render_failures[:5]}
            legacy_rendered = {**legacy_rendered, "receipt": receipt}
        return legacy_rendered
    principal_token = "".join(ch if ch.isalnum() else "-" for ch in principal_id.lower())[:80].strip("-") or "principal"
    publication_token = "".join(ch if ch.isalnum() else "-" for ch in publication_id.lower())[:80].strip("-") or "packet"
    target_dir = artifact_root / "property_packets" / principal_token
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{publication_token}.pdf"
    receipt_path = target_dir / f"{publication_token}.receipt.json"
    pdf_path.write_bytes(render_result.pdf_bytes)
    if quality_report is None:
        quality_report = inspect_rendered_artifact(
            artifact_bytes=render_result.pdf_bytes,
            expected_text=request.expected_text,
            forbidden_text=request.forbidden_text,
        )
    base_receipt = {
        **dict(redaction.receipt or {}),
        "visual_elements": [
            "hero_cover",
            "executive_read",
            "fact_grid",
            "tour_spread",
            "risk_register",
            "provenance_footer",
        ],
        "media_link_count": len(compiled.gallery_urls) + len(compiled.floorplan_urls),
        "embedded_media_refs": {
            "floorplans": len(compiled.floorplan_urls),
            "photos": len(compiled.gallery_urls),
        },
        "private_reference_media_included": private_reference_media_included,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
        "premium_render_failures": render_failures[:5],
    }
    receipt = build_premium_receipt(
        renderer_version=PREMIUM_DOSSIER_RENDERER_VERSION if render_result.renderer == "markupgo" else PREMIUM_DOSSIER_FALLBACK_VERSION,
        render_result=render_result,
        quality_report=quality_report,
        base_receipt=base_receipt,
        pdf_path=str(pdf_path),
    )
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "pdf_path": str(pdf_path),
        "receipt_path": str(receipt_path),
        "pdf_sha256": render_result.pdf_sha256 or hashlib.sha256(render_result.pdf_bytes).hexdigest(),
        "pdf_size_bytes": len(render_result.pdf_bytes),
        "receipt": receipt,
        "redacted_payload": redaction.payload,
        "recommended_title": compiled.recommended_title,
    }
