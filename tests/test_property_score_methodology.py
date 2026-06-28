from __future__ import annotations

from pathlib import Path

from app.product.property_score_methodology import (
    build_property_score_methodology,
    build_property_score_methodology_pdf_source,
    build_property_score_methodology_for_supported_languages,
    supported_property_score_methodology_languages,
)
from scripts.check_property_bts_methodology_contract import build_bts_methodology_contract_receipt
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
        assert payload["calculation_title"]
        assert payload["calculation_rows"][-1]["delta"] == "=58"
        assert "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58" in payload["calculation_rows"][-1]["why"]
        assert payload["calculation_detail_title"]
        assert len(payload["calculation_detail_rows"]) >= 8
        assert payload["weight_ladder_title"]
        assert len(payload["weight_ladder_rows"]) >= 5
        assert payload["source_sections_label"]
        assert len(payload["source_sections"]) >= 5
        detail_blob = " ".join(
            " ".join(str(row.get(key) or "") for key in ("label", "delta", "source", "rule", "alternatives"))
            for row in payload["calculation_detail_rows"]
        )
        assert "+8" in detail_blob
        assert "+10" in detail_blob
        assert "+6" in detail_blob
        assert "-8" in detail_blob
        if payload["language_code"] != "en":
            assert not str(payload["summary"]).startswith("The score is not portal popularity")
            assert not str(payload["calculation_title"]).startswith("Example calculation")
            assert not str(payload["calculation_detail_title"]).startswith("Where each number comes from")
            assert not str(payload["weight_ladder_title"]).startswith("How preference strength")
            assert not any(str(row.get("label") or "") == "Final score" for row in payload["calculation_rows"])


def test_score_methodology_pdf_source_localizes_demo_signals_for_every_language() -> None:
    english_phrases = {
        "Selected area is respected.",
        "Confirmed costs, floorplan, and 360 evidence raise confidence.",
        "Commute and daily-life preferences score well.",
        "One soft preference is missing and lowers rank without excluding.",
        "Heating detail still needs confirmation before a final decision.",
        "Check the remaining gap with the agent.",
        "Compare the route and noise evidence during an actual viewing.",
        "Example budget",
        "Demo market",
    }

    for language_code in supported_property_score_methodology_languages():
        source = build_property_score_methodology_pdf_source(language_code=language_code)
        assert source["fit_score"] == 62
        assert source["score_methodology"]["calculation_rows"][-1]["delta"] == "=58"
        if language_code == "en":
            continue
        rendered_values = {
            *[str(value) for value in source["match_reasons"]],
            *[str(value) for value in source["mismatch_reasons"]],
            *[str(value) for value in source["viewing_questions"]],
            str(source["property_facts"]["price_display"]),
            str(source["property_facts"]["postal_name"]),
        }
        assert not english_phrases.intersection(rendered_values), language_code


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
    assert payload["calculation_title"] == "Beispielrechnung: warum dieses Objekt bei 58 landet"
    assert payload["calculation_rows"][-1]["delta"] == "=58"
    assert "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58" in payload["calculation_rows"][-1]["why"]
    assert payload["calculation_detail_title"] == "Wo jede Zahl herkommt"
    assert any(row["label"] == "Harte Regeln bestanden" and row["delta"] == "+8" for row in payload["calculation_detail_rows"])
    location_rows = [row for row in payload["calculation_detail_rows"] if row["label"] == "Lage geprüft"]
    assert location_rows and location_rows[0]["delta"] == "+0"
    location_copy = " ".join(str(location_rows[0].get(key) or "") for key in ("source", "rule", "alternatives"))
    assert "Randlage" in location_copy
    assert "nicht belohnt" in location_copy
    assert any("starker Wunsch etwa +12" in row["alternatives"] for row in payload["calculation_detail_rows"])
    assert any("Wünschenswert etwa -3" in row["alternatives"] for row in payload["calculation_detail_rows"])
    assert any(row["level"] == "Starker Wunsch" for row in payload["weight_ladder_rows"])
    assert "persönliche Passung" in payload["subtitle"]
    assert "präferenz" in payload["weight_ladder_title"].lower()


def test_score_methodology_english_copy_avoids_verification_jargon() -> None:
    payload = build_property_score_methodology(language_code="en")

    examples_blob = " ".join(
        " ".join(str(row.get(key) or "") for key in ("title", "detail"))
        for row in payload["examples"]
    )
    detail_blob = " ".join(
        " ".join(str(row.get(key) or "") for key in ("label", "source", "rule", "alternatives"))
        for row in payload["calculation_detail_rows"]
    )
    source_sections_blob = " ".join(
        " ".join(str(row.get(key) or "") for key in ("title", "detail"))
        for row in payload["source_sections"]
    )

    assert "verified listing facts" not in payload["summary"]
    assert "confirmed listing facts" in payload["summary"]
    assert "verified 360 source" not in examples_blob
    assert "real 360 source" in examples_blob
    assert "verification rules" not in source_sections_blob.lower()
    assert "how facts are checked" in source_sections_blob.lower()
    assert "open verification risk" not in detail_blob.lower()
    assert "open questions" in detail_blob.lower()


def test_bts_methodology_contract_proves_sources_and_no_district_reward() -> None:
    receipt = build_bts_methodology_contract_receipt()

    assert receipt["status"] == "pass"
    assert receipt["source_section_count"] >= 5
    assert {"en", "de"}.issubset(set(receipt["languages"]))
    assert "data.gv.at" in receipt["required_source_tokens"]
    assert any("district reward" in token for token in receipt["required_district_policy_tokens"])


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
    assert "Beispielrechnung: warum dieses Objekt bei 58 landet" in html
    assert "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58" in html
    assert "Wo jede Zahl herkommt" in html
    assert "Harte Regeln bestanden" in html
    assert "starker Wunsch etwa +12" in html
    assert "Wie die Präferenzstärke ein Delta verändert" in html
    assert "Falscher Bezirk" in html
    assert "Echte 360-Tour vorhanden." in html


def test_results_bts_exposes_score_pdf_action() -> None:
    template = (ROOT / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")

    assert "/how-it-works/score" in template
    assert "&country=" in template
    assert "Open score guide" in template


def test_selected_property_score_cards_keep_score_pdf_out_of_property_cards() -> None:
    desktop = (ROOT / "ea/app/templates/app/_property_selected_review_panel.html").read_text(encoding="utf-8")
    mobile = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    results_bts = (ROOT / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")

    assert "/app/api/properties/score-methodology/pdf" not in desktop
    assert desktop.count("Open score guide") == 0
    assert mobile.count("Open score guide") == 0
    assert results_bts.count("Open score guide") == 1
