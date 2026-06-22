from __future__ import annotations

from pathlib import Path

from app.product.property_score_methodology import (
    build_property_score_methodology,
    build_property_score_methodology_for_supported_languages,
    supported_property_score_methodology_languages,
)
from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.privacy import redact_property_packet
from app.services.premium_dossier.compiler import compile_premium_dossier
from app.services.premium_dossier.html import render_premium_dossier_html
from app.services.property_market_catalog import COUNTRIES


ROOT = Path(__file__).resolve().parents[1]


def test_score_methodology_languages_cover_country_provider_catalog() -> None:
    expected_languages = tuple(sorted({country.default_language.lower() for country in COUNTRIES}))

    assert supported_property_score_methodology_languages() == expected_languages

    payloads = build_property_score_methodology_for_supported_languages()
    assert [payload["language_code"] for payload in payloads] == list(expected_languages)
    for payload in payloads:
        assert payload["contract_name"] == "propertyquarry.score_methodology.v1"
        assert payload["pdf_title"]
        assert len(payload["principles"]) >= 5
        assert len(payload["steps"]) >= 6
        assert len(payload["examples"]) >= 5
        assert payload["score_bands"][-1] == {"range": "60+", "meaning": payload["score_bands"][-1]["meaning"]}
        if payload["language_code"] != "en":
            assert not str(payload["summary"]).startswith("The score is not portal popularity")


def test_score_methodology_applies_candidate_signals_and_band() -> None:
    payload = build_property_score_methodology(
        language_code="de",
        country_code="AT",
        candidate={
            "fit_score": 62,
            "match_reasons": ["Echte 360-Tour vorhanden.", "Betriebskosten sind belegt."],
            "mismatch_reasons": ["Heizungsdetail fehlt noch."],
        },
    )

    assert payload["country_code"] == "AT"
    assert payload["candidate_application"]["fit_score"] == 62
    assert payload["candidate_application"]["band_label"] == "Starke Passung"
    assert payload["candidate_application"]["positive_signals"] == ["Echte 360-Tour vorhanden.", "Betriebskosten sind belegt."]
    assert payload["candidate_application"]["negative_signals"] == ["Heizungsdetail fehlt noch."]


def test_score_methodology_survives_redaction_and_renders_in_premium_html() -> None:
    score_methodology = build_property_score_methodology(
        language_code="de",
        candidate={
            "fit_score": 62,
            "match_reasons": ["Echte 360-Tour vorhanden."],
            "mismatch_reasons": ["Heizungsdetail fehlt noch."],
        },
    )
    source = {
        "title": "Demo apartment",
        "fit_score": 62,
        "recommendation": "Strong fit",
        "match_reasons": ["Echte 360-Tour vorhanden."],
        "mismatch_reasons": ["Heizungsdetail fehlt noch."],
        "property_facts": {"rooms": 3, "area_m2": 82, "postal_name": "Demo market"},
        "score_methodology": score_methodology,
    }

    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
    )
    assert redacted.payload["fit_score"] == 62.0
    assert redacted.payload["score_methodology"]["language_code"] == "de"

    compiled = compile_premium_dossier(
        source=source,
        redacted_payload=redacted.payload,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        renderer_version="test",
    )
    html = render_premium_dossier_html(compiled, principal_id="tester")

    assert "Wie der PropertyQuarry-Score berechnet wird" in html
    assert "62/100" in html
    assert "Falscher Bezirk" in html
    assert "Echte 360-Tour vorhanden." in html


def test_results_bts_exposes_score_pdf_action() -> None:
    template = (ROOT / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")

    assert "/app/api/properties/score-methodology/pdf" in template
    assert "&country=" in template
    assert "Open score PDF" in template


def test_selected_property_score_cards_expose_score_pdf_action() -> None:
    desktop = (ROOT / "ea/app/templates/app/_property_selected_review_panel.html").read_text(encoding="utf-8")
    mobile = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "/app/api/properties/score-methodology/pdf" in desktop
    assert "/app/api/properties/score-methodology/pdf" in mobile
    assert desktop.count("Open score PDF") >= 1
    assert mobile.count("Open score PDF") >= 1
