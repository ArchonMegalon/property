from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


class _FakeUrlopenResponse:
    def __init__(self, payload: bytes, content_type: str = "image/jpeg") -> None:
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._payload
        return self._payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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


def test_premium_dossier_html_can_embed_personal_magicfit_scene() -> None:
    source = _sample_source()
    source["magic_fit_scene"] = {
        "scene_id": "magicfit-1",
        "scene_type": "breakfast",
        "summary": "Personal morning scene for the packet.",
        "image_url": "https://propertyquarry.com/static/magicfit-scene.jpg",
        "reference_urls": ["/app/api/property/magic-fit-reference-files/magicfitref_test"],
        "share_with_packet_pdf": True,
        "visual_simulation": True,
    }
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    html = render_premium_dossier_html(compiled)
    assert "Personal lifestyle scene" in html
    assert "https://propertyquarry.com/static/magicfit-scene.jpg" in html
    assert "/app/api/property/magic-fit-reference-files/magicfitref_test" in html


def test_premium_dossier_html_inlines_private_magicfit_reference_urls(monkeypatch, tmp_path: Path) -> None:
    principal_id = "cf-email:tibor@example.com"
    root = tmp_path / "magic_fit_refs" / "cf-email-tibor-example.com"
    root.mkdir(parents=True, exist_ok=True)
    (root / "magicfitref_test.jpg").write_bytes(b"fake-jpeg-bits")
    (root / "magicfitref_test.json").write_text(
        json.dumps(
            {
                "reference_id": "magicfitref_test",
                "file_name": "family-ref.jpg",
                "mime_type": "image/jpeg",
                "file_name_on_disk": "magicfitref_test.jpg",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    source = _sample_source()
    source["personal_reference_urls"] = ["/app/api/property/magic-fit-reference-files/magicfitref_test"]
    source["magic_fit_scene"] = {
        "scene_id": "magicfit-1",
        "scene_type": "breakfast",
        "summary": "Personal morning scene for the packet.",
        "image_url": "https://propertyquarry.com/static/magicfit-scene.jpg",
        "reference_urls": ["/app/api/property/magic-fit-reference-files/magicfitref_test"],
        "share_with_packet_pdf": True,
        "visual_simulation": True,
    }
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    html = render_premium_dossier_html(compiled, principal_id=principal_id)
    assert "data:image/jpeg;base64," in html


def test_premium_dossier_html_inlines_remote_images_and_diorama(monkeypatch) -> None:
    source = _sample_source()
    source["photo_refs"] = ["https://cdn.example.com/property-photo.jpg"]
    source["floorplan_refs"] = ["https://cdn.example.com/floorplan.jpg"]
    source["diorama_scene"] = {
        "image_url": "https://cdn.example.com/diorama.jpg",
        "summary": "Comic-style spatial preview.",
    }
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    fake_image = b"\xff\xd8\xff\xe0fakejpeg"
    with patch("app.services.premium_dossier.html.urllib.request.urlopen", return_value=_FakeUrlopenResponse(fake_image)):
        html = render_premium_dossier_html(compiled)
    assert "Diorama preview" in html
    assert "data:image/jpeg;base64," in html
    assert "https://cdn.example.com/property-photo.jpg" not in html
