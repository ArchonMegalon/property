from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import _resolve_pdf_flythrough_url
from app.services.premium_dossier import render_property_packet_pdf_via_premium_pipeline
from app.services.premium_dossier.compiler import _google_maps_url, compile_premium_dossier
from app.services.premium_dossier.html import render_premium_dossier_html
from app.services.premium_dossier.markupgo_adapter import render_pdf_with_markupgo
from app.services.premium_dossier.models import PremiumDossierRenderRequest, PremiumDossierRenderResult
from app.services.premium_dossier.qa import inspect_rendered_artifact


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
            "street_address": "Testgasse 12, 1020 Wien",
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
        "dossier_writer": {
            "status": "verified",
            "neuronwriter": {
                "status": "ready",
                "share_url": "https://app.neuronwriter.com/share/query-1",
                "questions": ["Which unresolved cost line still needs proof?"],
            },
            "sections": [
                {
                    "section_key": "evidence_summary",
                    "title": "Evidence Summary",
                    "body_markdown": "The current packet is strongest on layout and transit fit.",
                    "bullets": ["Lift and layout fit are already visible.", "Transit access is already plausible."],
                    "cta": "Keep the next owner action focused on costs and proof.",
                },
                {
                    "section_key": "risk_register",
                    "title": "Risk Register",
                    "body_markdown": "Operating costs still need owner-reviewed proof.",
                    "bullets": ["Operating-cost history is still missing."],
                    "cta": "Ask for the last 24 months of statements.",
                },
            ],
        },
        "route_context": {
            "provider": "AvoMap",
            "rows": [
                {
                    "label": "Your route",
                    "href": "https://maps.example.test/route/home",
                    "detail": "School route prepared from the property.",
                }
            ],
        },
        "dadan_context": {
            "enabled": True,
            "mode": "manual",
            "request_status": "created",
            "request_url": "https://app.dadan.io/request/demo",
            "request_kind": "agent_missing_fact",
            "response_status": "pending_owner_review",
            "recording_url": "https://app.dadan.io/recording/demo",
        },
    }


def test_premium_dossier_google_maps_url_prefers_listing_snapshot_locality_over_source_scope_placeholder() -> None:
    url = _google_maps_url(
        {
            "title": "expat flat",
            "property_facts": {
                "postal_name": "1010 Vienna",
                "source_scope_location": "1010 Vienna",
                "source_postal_code": "1010",
                "listing_research_snapshot": {
                    "address": "Brunnthalgasse 1B, 1020 Wien",
                    "postal_name": "1020 Wien",
                },
            },
        }
    )

    assert "Brunnthalgasse%201B%2C%201020%20Wien" in url


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
    assert "Route context" in html
    assert "Video feedback follow-up" in html
    assert "PropertyQuarry" in html
    assert "Open Google Maps" in html
    assert "https://www.google.com/maps/search/?api=1" in html


def test_premium_dossier_prefers_scene_render_as_hero_over_stock_gallery_order() -> None:
    source = _sample_source()
    source["magic_fit_scene"] = {
        "scene_id": "magicfit-hero-1",
        "scene_type": "family_evening",
        "summary": "Believable family evening render inside the property.",
        "image_url": "https://propertyquarry.com/static/magicfit-scene.jpg",
        "share_with_packet_pdf": True,
        "visual_simulation": True,
    }
    source["photo_refs"] = [
        "https://propertyquarry.com/static/test-cover.jpg",
        "https://propertyquarry.com/static/test-detail.jpg",
    ]
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    assert compiled.hero_image_url == "https://propertyquarry.com/static/magicfit-scene.jpg"
    assert compiled.portrait_image_url == "https://propertyquarry.com/static/magicfit-scene.jpg"
    assert compiled.property_image_url == "https://propertyquarry.com/static/test-cover.jpg"
    html = render_premium_dossier_html(compiled)
    assert "Property-fitting visual simulation" in html
    assert "https://propertyquarry.com/static/magicfit-scene.jpg" in html


def test_premium_dossier_html_surfaces_avomap_dadan_and_neuronwriter_context() -> None:
    compiled = compile_premium_dossier(
        source=_sample_source(),
        redacted_payload=_sample_source(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    html = render_premium_dossier_html(compiled)
    assert "AvoMap route read" in html
    assert "Open routes" in html
    assert "Dadan follow-up state" in html
    assert "Open Dadan request" in html
    assert "NeuronWriter guidance: ready" in html
    assert "Which unresolved cost line still needs proof?" in html


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
        pdf_text = "%PDF-1.4 " + " ".join(_request.expected_text)
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_text.encode("utf-8"),
            pdf_sha256="abc123",
            render_seconds=0.5,
        )

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    monkeypatch.setattr(
        "app.services.premium_dossier.inspect_rendered_artifact",
        lambda **kwargs: type(
            "Report",
            (),
            {
                "ok": True,
                "required_text_check": "passed",
                "forbidden_text_check": "passed",
                "page_count": 1,
                "visual_preview_check": "passed",
                "cover_dominance_check": "passed",
                "footer_band_check": "passed",
                "raw_url_text_check": "passed",
                "visual_preview_artifact_ref": "",
                "first_page_width_px": 0,
                "first_page_height_px": 0,
                "first_page_nonwhite_ratio": 0.0,
                "first_page_top_band_nonwhite_ratio": 0.0,
                "first_page_footer_band_nonwhite_ratio": 0.0,
                "required_text_hits": list(kwargs.get("expected_text") or []),
                "forbidden_text_hits": [],
                "raw_url_text_hits": [],
            },
        )(),
    )
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


def test_premium_pipeline_blocks_markupgo_for_private_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "markupgo")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "playwright")
    monkeypatch.delenv("PROPERTYQUARRY_DOSSIER_ALLOW_PRIVATE_REFERENCES_REMOTE", raising=False)
    source = _sample_source()
    source["personal_reference_urls"] = ["/app/api/property/magic-fit-reference-files/magicfitref_private"]

    def _markupgo_should_not_run(_request):
        raise AssertionError("MarkupGo must not receive private reference media by default")

    def _fake_playwright(_request):
        pdf_text = "%PDF-1.4 " + " ".join(_request.expected_text)
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_text.encode("utf-8"),
            pdf_sha256="abc123",
            render_seconds=0.5,
        )

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_markupgo", _markupgo_should_not_run)
    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    monkeypatch.setattr(
        "app.services.premium_dossier.inspect_rendered_artifact",
        lambda **kwargs: type(
            "Report",
            (),
            {
                "ok": True,
                "required_text_check": "passed",
                "forbidden_text_check": "passed",
                "page_count": 1,
                "visual_preview_check": "passed",
                "cover_dominance_check": "passed",
                "footer_band_check": "passed",
                "raw_url_text_check": "passed",
                "visual_preview_artifact_ref": "",
                "first_page_width_px": 0,
                "first_page_height_px": 0,
                "first_page_nonwhite_ratio": 0.0,
                "first_page_top_band_nonwhite_ratio": 0.0,
                "first_page_footer_band_nonwhite_ratio": 0.0,
                "required_text_hits": list(kwargs.get("expected_text") or []),
                "forbidden_text_hits": [],
                "raw_url_text_hits": [],
            },
        )(),
    )
    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_private_refs",
        principal_id="cf-email:tibor@example.com",
        source=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=True,
        include_photos=True,
        legacy_renderer=lambda **kwargs: {"status": "legacy_should_not_run"},
    )

    assert rendered["receipt"]["renderer_provider"] == "playwright"
    assert rendered["receipt"]["private_reference_media_included"] is True
    assert rendered["receipt"]["premium_render_failures"][0]["error_code"] == "markupgo_private_reference_media_blocked"


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
    assert "Scene render" in html
    assert "Property-fitting visual simulation" in html
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
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_INLINE_REMOTE_IMAGES", "1")
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


def test_premium_dossier_html_keeps_remote_image_urls_by_default() -> None:
    source = _sample_source()
    source["photo_refs"] = ["https://cdn.example.com/property-photo.jpg"]
    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="v1_premium_markupgo_dossier",
    )
    html = render_premium_dossier_html(compiled)
    assert "https://cdn.example.com/property-photo.jpg" in html


def test_premium_dossier_quality_gate_rejects_tiny_binary_pdf_without_markers() -> None:
    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4\n\x00\x01binary-stream",
        expected_text=["PropertyQuarry", "1050 live"],
        forbidden_text=["token", "session"],
    )
    assert report.required_text_check == "failed"
    assert report.forbidden_text_check == "passed"
    assert report.ok is False


def test_premium_dossier_quality_gate_rejects_structural_binary_pdf_without_extractable_text() -> None:
    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4\n1 0 obj <</Type /Page>> endobj\n" + (b"0" * 2048),
        expected_text=["PropertyQuarry", "1050 live"],
        forbidden_text=["token", "session"],
    )
    assert report.required_text_check == "failed"
    assert report.forbidden_text_check == "passed"
    assert report.ok is False


def test_premium_dossier_quality_gate_records_visual_preview_metadata(monkeypatch, tmp_path: Path) -> None:
    preview_path = tmp_path / "page-1.png"

    monkeypatch.setattr(
        "app.services.premium_dossier.qa._render_pdf_first_page_png",
        lambda artifact_bytes, output_path=None: (b"fake-png", 1200, 1800),
    )
    monkeypatch.setattr(
        "app.services.premium_dossier.qa._png_visual_metrics",
        lambda png_bytes: (0.41, 0.27, 0.03),
    )

    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4 PropertyQuarry Premium Test Wohnung",
        expected_text=["PropertyQuarry", "Premium Test Wohnung"],
        forbidden_text=["token", "session"],
        preview_output_path=preview_path,
        require_cover_visual_dominance=True,
        require_footer_band=True,
        forbid_raw_url_text=True,
    )

    assert report.visual_preview_check == "passed"
    assert report.cover_dominance_check == "passed"
    assert report.footer_band_check == "passed"
    assert report.raw_url_text_check == "passed"
    assert report.visual_preview_artifact_ref == str(preview_path)
    assert report.first_page_width_px == 1200
    assert report.first_page_height_px == 1800
    assert report.first_page_nonwhite_ratio == 0.41
    assert report.first_page_top_band_nonwhite_ratio == 0.27
    assert report.first_page_footer_band_nonwhite_ratio == 0.03


def test_premium_dossier_quality_gate_rejects_visible_raw_urls() -> None:
    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4 PropertyQuarry https://example.com/raw-url",
        expected_text=["PropertyQuarry"],
        forbidden_text=["token", "session"],
        forbid_raw_url_text=True,
    )

    assert report.raw_url_text_check == "failed"
    assert report.raw_url_text_hits == ["https://example.com/raw-url"]


def test_premium_dossier_quality_gate_ignores_raw_url_only_in_binary_stream(monkeypatch) -> None:
    monkeypatch.setattr("app.services.premium_dossier.qa._extract_pdf_text", lambda artifact_bytes: "PropertyQuarry")
    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4 https://example.com/raw-url",
        expected_text=["PropertyQuarry"],
        forbidden_text=["token", "session"],
        forbid_raw_url_text=True,
    )

    assert report.raw_url_text_check == "passed"
    assert report.raw_url_text_hits == []


def test_premium_dossier_quality_gate_requires_real_pdf_text_extraction(monkeypatch) -> None:
    monkeypatch.setattr("app.services.premium_dossier.qa._extract_pdf_text", lambda artifact_bytes: "")
    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4 PropertyQuarry Premium Test Wohnung",
        expected_text=["PropertyQuarry", "Premium Test Wohnung"],
        forbidden_text=[],
    )

    assert report.required_text_check == "failed"
    assert report.required_text_hits == []
    assert report.ok is False


def test_premium_dossier_quality_gate_rejects_missing_cover_or_footer_when_required(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.premium_dossier.qa._render_pdf_first_page_png",
        lambda artifact_bytes, output_path=None: (b"fake-png", 1200, 1800),
    )
    monkeypatch.setattr(
        "app.services.premium_dossier.qa._png_visual_metrics",
        lambda png_bytes: (0.41, 0.03, 0.004),
    )

    report = inspect_rendered_artifact(
        artifact_bytes=b"%PDF-1.4 PropertyQuarry Premium Test Wohnung",
        expected_text=["PropertyQuarry", "Premium Test Wohnung"],
        forbidden_text=["token", "session"],
        require_cover_visual_dominance=True,
        require_footer_band=True,
    )

    assert report.visual_preview_check == "passed"
    assert report.cover_dominance_check == "failed"
    assert report.footer_band_check == "failed"
    assert report.ok is False


def test_premium_pipeline_falls_back_to_legacy_when_rendered_pdf_fails_quality_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")
    monkeypatch.delenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", raising=False)

    def _bad_playwright(_request):
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=b"%PDF-1.4\n\x00bad",
            pdf_sha256="bad",
            render_seconds=0.1,
        )

    def _legacy_renderer(**kwargs):  # noqa: ANN003
        return {"status": "legacy_rendered", "receipt": {"renderer_provider": "legacy"}}

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _bad_playwright)
    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_quality_fallback",
        principal_id="cf-email:tibor@example.com",
        source=_sample_source(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=True,
        include_photos=True,
        legacy_renderer=_legacy_renderer,
    )

    assert rendered["status"] == "legacy_rendered"
    assert rendered["receipt"]["premium_render_failures"][0]["error_code"] == "premium_pdf_quality_gate_failed"


def test_premium_pipeline_writes_visual_preview_receipt_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")

    def _fake_playwright(_request):
        pdf_text = "%PDF-1.4 " + " ".join(_request.expected_text)
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_text.encode("utf-8"),
            pdf_sha256="preview123",
            render_seconds=0.2,
        )

    def _fake_inspect(
        *,
        artifact_bytes,
        expected_text,
        forbidden_text,
        preview_output_path=None,
        require_cover_visual_dominance=False,
        require_footer_band=False,
        forbid_raw_url_text=False,
    ):
        if preview_output_path:
            Path(preview_output_path).write_bytes(b"png")
        return type("Report", (), {
            "ok": True,
            "required_text_check": "passed",
            "forbidden_text_check": "passed",
            "page_count": 3,
            "visual_preview_check": "passed",
            "cover_dominance_check": "passed",
            "footer_band_check": "passed",
            "raw_url_text_check": "passed",
            "visual_preview_artifact_ref": str(preview_output_path or ""),
            "first_page_width_px": 1200,
            "first_page_height_px": 1800,
            "first_page_nonwhite_ratio": 0.42,
            "first_page_top_band_nonwhite_ratio": 0.31,
            "first_page_footer_band_nonwhite_ratio": 0.03,
            "required_text_hits": list(expected_text),
            "forbidden_text_hits": [],
            "raw_url_text_hits": [],
        })()

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    monkeypatch.setattr("app.services.premium_dossier.inspect_rendered_artifact", _fake_inspect)

    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_visual_receipt",
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

    assert rendered["preview_path"].endswith(".page-1.png")
    assert Path(str(rendered["preview_path"])).is_file()
    assert rendered["text_manifest_path"].endswith(".text-manifest.txt")
    assert Path(str(rendered["text_manifest_path"])).is_file()
    assert rendered["receipt"]["visual_preview_check"] == "passed"
    assert rendered["receipt"]["cover_dominance_check"] == "passed"
    assert rendered["receipt"]["footer_band_check"] == "passed"
    assert rendered["receipt"]["raw_url_text_check"] == "passed"
    assert rendered["receipt"]["visual_preview_artifact_ref"].endswith(".page-1.png")
    assert rendered["receipt"]["page_count"] == 3


def test_premium_pipeline_keeps_text_manifest_outside_pdf_bytes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")

    def _fake_playwright(_request):
        pdf_text = "%PDF-1.4 " + " ".join(_request.expected_text)
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_text.encode("utf-8"),
            pdf_sha256="manifest123",
            render_seconds=0.2,
        )

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    monkeypatch.setattr(
        "app.services.premium_dossier.inspect_rendered_artifact",
        lambda **kwargs: type(
            "Report",
            (),
            {
                "ok": True,
                "required_text_check": "passed",
                "forbidden_text_check": "passed",
                "page_count": 1,
                "visual_preview_check": "passed",
                "cover_dominance_check": "passed",
                "footer_band_check": "passed",
                "raw_url_text_check": "passed",
                "visual_preview_artifact_ref": "",
                "first_page_width_px": 0,
                "first_page_height_px": 0,
                "first_page_nonwhite_ratio": 0.0,
                "first_page_top_band_nonwhite_ratio": 0.0,
                "first_page_footer_band_nonwhite_ratio": 0.0,
                "required_text_hits": list(kwargs.get("expected_text") or []),
                "forbidden_text_hits": [],
                "raw_url_text_hits": [],
            },
        )(),
    )
    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_text_manifest",
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

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    assert b"%PQ_TEXT_BEGIN" not in pdf_bytes
    text_manifest = Path(str(rendered["text_manifest_path"])).read_text(encoding="utf-8")
    assert "PropertyQuarry" in text_manifest


def test_playwright_renderer_blocks_remote_network_requests(monkeypatch, tmp_path: Path) -> None:
    from app.services.premium_dossier import playwright_adapter

    observed: dict[str, object] = {"route_pattern": "", "allowed": [], "blocked": []}

    class _FakeRoute:
        def __init__(self, url: str) -> None:
            self.request = type("Request", (), {"url": url})()

        def continue_(self) -> None:
            observed["allowed"].append(self.request.url)

        def abort(self) -> None:
            observed["blocked"].append(self.request.url)

    class _FakePage:
        def route(self, pattern, handler) -> None:
            observed["route_pattern"] = pattern
            handler(_FakeRoute("file:///tmp/dossier.html"))
            handler(_FakeRoute("https://cdn.example.test/hero.jpg"))

        def goto(self, url, wait_until="load") -> None:
            observed["goto_url"] = url

        def pdf(self, *, path: str, **kwargs) -> None:
            Path(path).write_bytes(b"%PDF-1.4 PropertyQuarry")

    class _FakeBrowser:
        def new_page(self):
            return _FakePage()

        def close(self) -> None:
            return None

    class _FakePlaywright:
        chromium = type("Chromium", (), {"launch": staticmethod(lambda **kwargs: _FakeBrowser())})()

    class _FakeContextManager:
        def __enter__(self):
            return _FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(playwright_adapter, "sync_playwright", lambda: _FakeContextManager())
    result = playwright_adapter.render_pdf_with_playwright(
        PremiumDossierRenderRequest(
            dossier_id="pub_local_only",
            renderer_version="v1_premium_playwright_dossier",
            html="<html><body>PropertyQuarry</body></html>",
            title="PropertyQuarry",
            privacy_mode="family_review",
            packet_kind="family_review",
        )
    )

    assert result.status == "rendered"
    assert observed["route_pattern"] == "**/*"
    assert observed["allowed"] == ["file:///tmp/dossier.html"]
    assert observed["blocked"] == ["https://cdn.example.test/hero.jpg"]


def test_premium_pipeline_records_quality_failure_when_legacy_fallback_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")
    monkeypatch.delenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", raising=False)

    def _bad_playwright(_request):
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=b"%PDF-1.4\n\x00bad",
            pdf_sha256="bad",
            render_seconds=0.1,
        )

    def _legacy_renderer(**kwargs):  # noqa: ANN003
        return {"status": "legacy_rendered", "receipt": {"renderer_provider": "legacy"}}

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _bad_playwright)
    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_quality_fallback",
        principal_id="cf-email:tibor@example.com",
        source=_sample_source(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=True,
        include_photos=True,
        legacy_renderer=_legacy_renderer,
    )

    assert rendered["status"] == "legacy_rendered"
    assert rendered["receipt"]["premium_render_failures"][0]["error_code"] == "premium_pdf_quality_gate_failed"


def test_telegram_appendix_uses_premium_pipeline_before_legacy_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")
    monkeypatch.delenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", raising=False)

    source = _sample_source()
    source["appendix_mode"] = "telegram_pdf_appendix"
    legacy_called = {"value": False}

    def _fake_playwright(_request):
        pdf_text = "%PDF-1.4 " + " ".join(_request.expected_text)
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_text.encode("utf-8"),
            pdf_sha256="telegram-premium",
            render_seconds=0.2,
        )

    def _legacy_renderer(**kwargs):  # noqa: ANN003
        legacy_called["value"] = True
        return {"status": "legacy_rendered", "receipt": {"renderer_provider": "legacy"}}

    monkeypatch.setattr("app.services.premium_dossier.render_pdf_with_playwright", _fake_playwright)
    monkeypatch.setattr(
        "app.services.premium_dossier.inspect_rendered_artifact",
        lambda **kwargs: type(
            "Report",
            (),
            {
                "ok": True,
                "required_text_check": "passed",
                "forbidden_text_check": "passed",
                "page_count": 1,
                "visual_preview_check": "passed",
                "cover_dominance_check": "passed",
                "footer_band_check": "passed",
                "raw_url_text_check": "passed",
                "visual_preview_artifact_ref": "",
                "first_page_width_px": 0,
                "first_page_height_px": 0,
                "first_page_nonwhite_ratio": 0.0,
                "first_page_top_band_nonwhite_ratio": 0.0,
                "first_page_footer_band_nonwhite_ratio": 0.0,
                "required_text_hits": list(kwargs.get("expected_text") or []),
                "forbidden_text_hits": [],
                "raw_url_text_hits": [],
            },
        )(),
    )

    rendered = render_property_packet_pdf_via_premium_pipeline(
        artifact_root=tmp_path,
        publication_id="pub_telegram_appendix",
        principal_id="cf-email:tibor@example.com",
        source=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=True,
        include_photos=True,
        legacy_renderer=_legacy_renderer,
    )

    assert Path(str(rendered["pdf_path"])).is_file()
    assert rendered["receipt"]["renderer_provider"] == "playwright"
    assert legacy_called["value"] is False


def test_pdf_flythrough_url_does_not_fallback_to_tour_pane_without_real_clip() -> None:
    source = {
        "tour_url": "https://propertyquarry.com/tours/test-tour#live-360",
        "hosted_url": "https://propertyquarry.com/tours/test-tour#live-360",
    }
    payload = {
        "tour_url": "https://propertyquarry.com/tours/test-tour#live-360",
    }
    assert _resolve_pdf_flythrough_url(source=source, payload=payload) == ""
