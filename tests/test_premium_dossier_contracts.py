from __future__ import annotations

from pathlib import Path

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.premium_dossier import render_property_packet_pdf_via_premium_pipeline
from app.services.premium_dossier.compiler import compile_premium_dossier
from app.services.premium_dossier.html import render_premium_dossier_html
from app.services.premium_dossier.markupgo_adapter import render_pdf_with_markupgo
from app.services.premium_dossier.models import PremiumDossierRenderRequest, PremiumDossierRenderResult


def _sample_source() -> dict[str, object]:
    return {
        "title": "Premium Test Wohnung",
        "recommendation": "shortlist",
        "fit_summary": "Persönliche Passung 82/100",
        "facts": {
            "price": 285000,
            "area_sqm": 68.4,
            "rooms": 2,
            "heating_type": "Fernwärme",
            "has_lift": True,
            "nearest_transit_label": "Straßenbahn in 4 Gehminuten",
        },
        "photo_refs": ["https://propertyquarry.com/static/test-cover.jpg"],
        "floorplan_refs": ["https://propertyquarry.com/static/test-floorplan.jpg"],
        "match_reasons": ["Lift und Grundriss passen gut zum aktuellen Suchprofil."],
        "mismatch_reasons": ["Betriebskostenhistorie fehlt noch."],
        "daily_life_lines": ["Supermarkt in 280 m · ca. 4 Gehminuten"],
        "family_route_lines": ["Volksschule wirkt auf dem aktuellen Stand fußläufig erreichbar."],
        "risk_lines": ["Heizkostenhistorie ist noch nicht belegt."],
        "agent_questions": ["Bitte die letzten Betriebskostenabrechnungen senden."],
        "provenance_lines": ["Quelle: öffentlicher Listing-Import", "Privacy mode: family_review"],
        "source_virtual_tour_url": "https://propertyquarry.com/tours/test-tour",
        "flythrough_url": "https://propertyquarry.com/tours/test-tour?pane=flythrough-pane&autoplay=1",
        "review_url": "https://propertyquarry.com/app/research/test",
    }


def test_premium_dossier_html_contains_core_sections() -> None:
    compiled = compile_premium_dossier(
        source=_sample_source(),
        redacted_payload=_sample_source(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    html = render_premium_dossier_html(compiled)
    assert "Executive decision" in html
    assert "Hosted 360 and media" in html
    assert "Risk register and next proof" in html
    assert "Property portrait" in html
    assert "PropertyQuarry" in html


def test_markupgo_adapter_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_REMOTE_RENDER_ALLOWED", "1")
    monkeypatch.delenv("MARKUPGO_API_KEY", raising=False)
    result = render_pdf_with_markupgo(
        PremiumDossierRenderRequest(
            dossier_id="pub_test",
            renderer_version="v1_premium_markupgo_dossier",
            html="<html><body>Test</body></html>",
            title="Test",
            privacy_mode="family_review",
            packet_kind="family_review",
        )
    )
    assert result.status == "failed"
    assert result.error_code == "markupgo_api_key_missing"


def test_premium_pipeline_uses_configured_playwright_before_legacy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")

    def _fake_playwright(_request):
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=b"%PDF-1.4 PropertyQuarry Premium Test Wohnung Vertieft prufen",
            pdf_sha256="abc123",
            render_seconds=0.5,
        )

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_test",
        principal_id="cf-email:tibor@example.com",
        source=_sample_source(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=True,
        include_photos=True,
        legacy_renderer=lambda **kwargs: {"status": "legacy_should_not_run"},
    )
    assert Path(str(rendered["pdf_path"])).is_file()
    assert rendered["receipt"]["renderer_provider"] == "playwright"
