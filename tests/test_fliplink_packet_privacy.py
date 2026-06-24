from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import _claim_bound_dossier_sections, render_property_packet_pdf, render_property_packet_pdf_legacy
from app.services.fliplink.privacy import redact_property_packet
from app.services.premium_dossier.models import PremiumDossierRenderResult
from app.services.premium_dossier.qa import _extract_pdf_text


def _source_payload() -> dict[str, object]:
    return {
        "principal_id": "owner-secret",
        "recipient_email": "private@example.com",
        "title": "1020 Vienna apartment",
        "property_ref": "listing:vienna-1020",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
        "tour_url": "https://propertyquarry.com/tours/test-demo-tour",
        "review_url": "https://propertyquarry.com/app/research/property-scout:test-demo?run_id=run-demo",
        "fit_summary": "Strong family fit near daily-life infrastructure.",
        "compare_reason": "Chosen ahead of the next option because it includes a floorplan and stays closer to the current brief.",
        "match_reasons": ["Floorplan, lift, and usable outdoor space."],
        "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
        "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
        "public_preference_snapshot": {"prefer_balcony": True},
        "property_facts": {
            "rooms": 3,
            "area_m2": 82,
            "price_display": "EUR 520,000",
            "street_address": "Exact Street 12",
            "map_lat": 48.2,
            "map_lng": 16.3,
            "postal_name": "1020 Wien",
            "has_floorplan": True,
            "nearest_supermarket_m": 300,
            "nearest_library_m": 420,
            "nearest_medical_care_m": 650,
            "nearest_hospital_m": 1100,
            "nearest_tram_bus_m": 210,
            "nearest_running_m": 540,
            "nearest_cycleway_m": 180,
            "building_type": "Altbau apartment building",
            "year_built": 1912,
            "crime_risk": True,
            "official_risk_evidence": {
                "sources": [
                    {
                        "risk_key": "crime_risk",
                        "label": "Crime burden",
                        "verification_state": "needs_review",
                        "summary": "Official crime statistics should still be checked before treating quarter-level safety as solved.",
                    }
                ]
            },
            "future_change_research": {
                "planned_infrastructure_projects": ["Tram corridor capacity upgrade around the quarter."],
                "future_value_drivers": ["Public-space and station-area upgrades are under discussion."],
                "future_value_risks": ["Construction disruption may temporarily affect calm and access."],
                "planning_confidence": "Medium",
            },
            "school_atlas_quality_summary": "Nearest transition-capable school is within practical reach and has a stable public-school profile.",
            "school_atlas_progression_summary": "A visible share of children continue into Gymnasium, but the exact route burden still needs on-site review.",
            "school_atlas_selected_school": {
                "name": "Volksschule Sachsenplatz",
                "type": "Volksschule",
                "distance_m": 480,
            },
            "internal_source_diagnostics": {"cookie": "secret"},
        },
    }


def _pdf_visible_text(pdf_bytes: bytes) -> str:
    extracted = _extract_pdf_text(pdf_bytes)
    return extracted if str(extracted or "").strip() else pdf_bytes.decode("latin-1", errors="ignore")


def test_claim_bound_dossier_sections_omit_internal_writer_status() -> None:
    sections = _claim_bound_dossier_sections(
        {
            "dossier_writer": {
                "status": "verified",
                "generated_by": "propertyquarry_dossier_writer.claim_bound.v1",
                "claim_coverage": {"claims_used": 9, "unsupported_sentences": 0},
                "neuronwriter": {"status": "disabled", "reason": "neuronwriter_disabled"},
                "sections": [
                    {
                        "section_key": "executive_decision",
                        "title": "Executive read",
                        "body_markdown": "This property remains worth a controlled review.",
                        "claims_used": ["fact.layout"],
                    }
                ],
            }
        }
    )

    rendered = "\n".join(
        [str(section.get("title") or "") for section in sections]
        + [str(item or "") for section in sections for item in list(section.get("items") or [])]
    )
    assert "Executive read" in rendered
    assert "Dossier writer:" not in rendered
    assert "Claim coverage:" not in rendered
    assert "NeuronWriter:" not in rendered
    assert "Provenance / QA" not in rendered


def test_fliplink_packet_redacts_private_keys_and_exact_address_by_default() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        include_exact_address=False,
    )

    assert "principal_id" not in redacted.payload
    assert "public_preference_snapshot" not in redacted.payload
    facts = redacted.payload["facts"]
    assert facts["rooms"] == 3
    assert facts["has_floorplan"] is True
    assert facts["nearest_supermarket_m"] == 300
    assert facts["nearest_medical_care_m"] == 650
    assert facts["crime_risk"] is True
    assert facts["school_atlas_selected_school"]["name"] == "Volksschule Sachsenplatz"
    assert "street_address" not in facts
    assert "map_lat" not in facts
    assert "internal_source_diagnostics" not in facts
    assert "facts.street_address" in redacted.receipt["removed_fields"]
    assert "principal_id" in redacted.receipt["removed_fields"]


def test_fliplink_owner_private_can_keep_exact_address_but_not_secrets() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        include_exact_address=True,
    )

    facts = redacted.payload["facts"]
    assert facts["street_address"] == "Exact Street 12"
    assert facts["map_lat"] == 48.2
    assert "principal_id" not in redacted.payload
    assert "public_preference_snapshot" not in redacted.payload


def test_fliplink_packet_media_flags_remove_floorplans_and_photos() -> None:
    redacted = redact_property_packet(
        source=_source_payload(),
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        include_floorplan=False,
        include_photos=False,
    )

    assert "floorplan_refs" not in redacted.payload
    assert "photo_refs" not in redacted.payload
    assert "floorplan_refs" in redacted.receipt["removed_fields"]


def test_fliplink_packet_allows_magicfit_still_photo_refs_even_when_tour_slug_contains_layout() -> None:
    source = _source_payload()
    source["photo_refs"] = [
        "https://propertyquarry.com/tours/files/neu-08-06-layout-first-demo/magicfit-still-1.jpg",
        "https://propertyquarry.com/tours/files/neu-08-06-layout-first-demo/magicfit-still-2.jpg",
    ]
    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        include_floorplan=True,
        include_photos=True,
    )
    assert redacted.payload["photo_refs"][:2] == [
        "https://propertyquarry.com/tours/files/neu-08-06-layout-first-demo/magicfit-still-1.jpg",
        "https://propertyquarry.com/tours/files/neu-08-06-layout-first-demo/magicfit-still-2.jpg",
    ]


def test_fliplink_packet_media_refs_are_host_allowlisted(monkeypatch) -> None:
    source = {
        **_source_payload(),
        "floorplan_refs": [
            "https://packets.propertyquarry.com/assets/floorplan.pdf",
            "https://tracker.example/floorplan.pdf",
            "http://packets.propertyquarry.com/plain-http.pdf",
        ],
        "photo_refs": [
            "https://view.propertyquarry.com/assets/photo.jpg",
            "https://cdn.example/photo.jpg?token=secret",
        ],
    }

    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        include_exact_address=False,
    )

    assert redacted.payload["floorplan_refs"] == ["https://packets.propertyquarry.com/assets/floorplan.pdf"]
    assert redacted.payload["photo_refs"] == ["https://view.propertyquarry.com/assets/photo.jpg"]
    removed = "\n".join(redacted.receipt["removed_fields"])
    assert "host_not_allowed:tracker.example" in removed
    assert "non_https_media_ref" in removed
    assert "sensitive_media_query" in removed
    assert "*.propertyquarry.com" in redacted.receipt["media_allowed_hosts"]

    monkeypatch.setenv("FLIPLINK_PACKET_MEDIA_ALLOWED_HOSTS", "cdn.example")
    custom = redact_property_packet(
        source={"photo_refs": ["https://cdn.example/photo.jpg"], "title": "Custom CDN"},
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
    )
    assert custom.payload["photo_refs"] == ["https://cdn.example/photo.jpg"]


def test_fliplink_packet_media_refs_allow_common_listing_cdn_hosts() -> None:
    redacted = redact_property_packet(
        source={
            "title": "Kalandra listing",
            "property_url": "https://www.kalandra.at/objekt/16465915",
            "photo_urls": [
                "https://storage.justimmo.at/thumb/photo-1.jpg",
                "https://storage.justimmo.at/thumb/photo-2.jpg",
            ],
        },
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
    )

    assert redacted.payload["photo_refs"] == [
        "https://storage.justimmo.at/thumb/photo-1.jpg",
        "https://storage.justimmo.at/thumb/photo-2.jpg",
    ]
    assert "storage.justimmo.at" in redacted.receipt["media_allowed_hosts"]


def test_paid_market_report_redaction_is_market_level_only(tmp_path: Path) -> None:
    source = {
        "title": "Exact Street 12 investment flat",
        "market_report_title": "1020 Vienna buy-to-let market report",
        "property_ref": "listing:private-owner-home",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/private-owner-home",
        "source_url": "https://www.willhaben.at/iad/immobilien/d/private-owner-home",
        "fit_summary": "Owner loves this exact flat because it is near school.",
        "summary": "Private owner-specific summary.",
        "match_reasons": ["Owner preference snapshot says this exact listing is a match."],
        "viewing_questions": ["Ask why the owner is selling."],
        "floorplan_refs": ["https://packets.propertyquarry.com/private/floorplan.pdf"],
        "photo_refs": ["https://packets.propertyquarry.com/private/photo.jpg"],
        "market_scope": "1020 Vienna",
        "market_summary": "District-level pricing and rent signal for 1020 Vienna.",
        "market_observations": ["Median asking prices are above adjacent districts."],
        "market_examples": ["Comparable two-bedroom segment, 70-90 m2, renovated stock."],
        "market_exclusions": ["No individual owner notes or private listing URLs."],
        "property_facts": {
            "street_address": "Exact Street 12",
            "map_lat": 48.2,
            "map_lng": 16.3,
            "rooms": 3,
            "area_m2": 82,
            "purchase_price_eur": 520000,
            "market_scope": "1020 Vienna",
            "freshness_date": "2026-06-06",
            "listing_count": 42,
            "median_price_per_sqm_eur": "EUR 6,400",
            "median_rent_per_sqm_eur": "EUR 18",
            "methodology": "Provider scan and redacted comparable aggregation.",
            "data_sources": ["Willhaben", "PropertyQuarry cache"],
            "legal_disclaimer": "Informational market report, not a valuation.",
        },
    }

    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.PAID_CUSTOMER,
        packet_kind=PropertyPacketKind.PAID_MARKET_REPORT,
        include_exact_address=True,
    )

    payload_text = str(redacted.payload)
    assert redacted.payload["title"] == "1020 Vienna buy-to-let market report"
    assert redacted.payload["market_scope"] == "1020 Vienna"
    assert "property_ref" not in redacted.payload
    assert "property_url" not in redacted.payload
    assert "floorplan_refs" not in redacted.payload
    assert "photo_refs" not in redacted.payload
    assert "viewing_questions" not in redacted.payload
    assert "Exact Street 12" not in payload_text
    assert "private-owner-home" not in payload_text
    assert "Owner loves this exact flat" not in payload_text
    facts = redacted.payload["facts"]
    assert facts["market_scope"] == "1020 Vienna"
    assert facts["listing_count"] == 42
    assert facts["median_price_per_sqm_eur"] == "EUR 6,400"
    assert "purchase_price_eur" not in facts
    assert "rooms" not in facts
    assert "area_m2" not in facts
    assert "street_address" not in facts
    assert "map_lat" not in facts
    removed = "\n".join(redacted.receipt["removed_fields"])
    assert "property_url" in removed
    assert "property_ref" in removed
    assert "floorplan_refs.paid_market_report_omitted" in removed
    assert "facts.purchase_price_eur" in removed
    assert redacted.receipt["paid_market_report_market_level_only"] is True
    assert redacted.receipt["source_refs"] == []

    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_paid_market",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.PAID_MARKET_REPORT,
        privacy_mode=PacketPrivacyMode.PAID_CUSTOMER,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=True,
    )
    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    pdf_text = _pdf_visible_text(pdf_bytes)
    assert "1020 Vienna buy-to-let market report" in pdf_text
    assert "Media appendix" not in pdf_text
    assert "Viewing checklist" not in pdf_text
    assert "Exact Street 12" not in pdf_text
    assert "private-owner-home" not in pdf_text
    assert "Owner loves this exact flat" not in pdf_text
    assert "media_appendix" not in rendered["receipt"]["visual_elements"]
    assert rendered["receipt"]["media_link_count"] == 0
    assert rendered["redacted_payload"] == redacted.payload


def test_fliplink_pdf_receipt_matches_pdf_hash(tmp_path: Path) -> None:
    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_test",
        principal_id="owner-1",
        source=_source_payload(),
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.FLIPBOOK_3D,
    )

    pdf_path = Path(str(rendered["pdf_path"]))
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert hashlib.sha256(pdf_bytes).hexdigest() == rendered["pdf_sha256"]
    assert rendered["receipt"]["pdf_sha256"] == rendered["pdf_sha256"]
    assert rendered["receipt"]["source_pdf_size_bytes"] == len(pdf_bytes)
    assert rendered["receipt"]["renderer_version"] in {"v1_premium_playwright_dossier", "v7_agency_comparison_dossier_pdf"}
    assert rendered["receipt"].get("renderer_provider") in {"playwright", None}
    assert any(item in rendered["receipt"]["visual_elements"] for item in ("hero_cover", "cover"))


def test_fliplink_pdf_appendix_mode_renders_compact_telegram_appendix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER", "playwright")
    monkeypatch.setenv("PROPERTYQUARRY_DOSSIER_RENDERER_FALLBACK", "legacy")
    monkeypatch.delenv("PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW", raising=False)

    def _fake_playwright(request):
        pdf_bytes = ("%PDF-1.4 " + request.html).encode("utf-8")
        return PremiumDossierRenderResult(
            status="rendered",
            renderer="playwright",
            pdf_bytes=pdf_bytes,
            pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            render_seconds=0.1,
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
    source = {
        **_source_payload(),
        "appendix_mode": "telegram_pdf_appendix",
        "source_pdf_filename": "wohnung-expose.pdf",
        "title": "Uploaded Wohnung expose",
        "tour_url": "https://propertyquarry.com/tours/pdf-upload-tour",
        "flythrough_url": "https://propertyquarry.com/tours/files/pdf-upload-tour/tour.mp4",
        "dossier_writer": {
            "status": "verified",
            "generated_by": "propertyquarry_dossier_writer.claim_bound.v1",
            "claim_coverage": {"claims_used": 3, "unsupported_sentences": 0},
            "neuronwriter": {"status": "pending", "mode": "api_live", "query_id": "nw-appendix"},
            "sections": [
                {
                    "section_key": "risk_register",
                    "title": "Risk Register",
                    "body_markdown": "Operating-cost history is not yet available. Heating source is not confirmed in the current evidence set.",
                    "bullets": ["Ask the agent for the last 24 months of operating-cost statements."],
                    "cta": "Ask the agent for the last 24 months of operating-cost statements.",
                    "claims_used": ["risk.operating_cost_history_missing", "risk.heating_source_unclear"],
                }
            ],
        },
        "property_facts_json": {
            "missing_fact_research": {
                "items": [
                    {
                        "label": "Operating costs",
                        "status": "research_needed",
                        "evidence": "Verify cost-line history against the expose.",
                    }
                ]
            }
        },
    }

    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        include_exact_address=False,
    )

    assert redacted.payload["appendix_mode"] == "telegram_pdf_appendix"
    assert redacted.payload["source_pdf_filename"] == "wohnung-expose.pdf"

    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_appendix",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.OWNER_REVIEW,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    extracted_text = _extract_pdf_text(pdf_bytes)
    appendix_text = extracted_text if str(extracted_text or "").strip() else pdf_bytes.decode("latin-1", errors="ignore")
    assert "Viewing Appendix" in appendix_text
    assert "Appendix to uploaded PDF: wohnung-expose.pdf" in appendix_text
    assert "Deep research results" in appendix_text
    assert "Operating-cost history is not yet available" in appendix_text
    assert "Open 3D control" in appendix_text
    assert "Play fly-through" in appendix_text
    assert "Artifact status" not in appendix_text
    assert "RISK REGISTER" not in appendix_text
    assert "Comparison snapshot" not in appendix_text
    assert "COMPARISON SNAPSHOT" not in appendix_text


def test_fliplink_pdf_omits_comparison_snapshot_from_rendered_dossier(tmp_path: Path) -> None:
    source = {
        **_source_payload(),
        "comparison_rows": [
            {
                "title": "Pärchenhit 2-Zimmer Wohnung, 68 m², U-Bahn Nähe in 1200 Wien",
                "price": 285000,
                "rooms": 2,
                "area_sqm": 68.46,
                "recommendation": "Benchmark buy-side alternative",
                "compare_reason": "Bigger footprint and buy-side upside, but it sits in a different affordability lane than the active rental brief.",
                "property_url": "https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1200-brigittenau/paerchenhit-2-zimmer-wohnung-68-m-u-bahn-naehe-in-1200-wien-1335192243",
            },
            {
                "title": "Donaustadt market benchmark",
                "price": "district overview",
                "rooms": "2-3",
                "area_sqm": "district level",
                "recommendation": "Market context only",
                "compare_reason": "Used as district-level context because the provided Donaustadt URL is a market overview rather than a single comparable unit.",
                "property_url": "https://www.willhaben.at/iad/immobilien/eigentumswohnung/wien/wien-1220-donaustadt/?fromExpiredAdId=2004425961",
            },
        ],
    }

    redacted = redact_property_packet(
        source=source,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        include_exact_address=False,
    )

    assert len(redacted.payload["comparison_rows"]) == 2
    assert redacted.payload["comparison_rows"][0]["title"].startswith("Pärchenhit")

    rendered = render_property_packet_pdf_legacy(
        artifact_root=tmp_path,
        publication_id="pub_compare",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.OWNER_REVIEW,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    pdf_text = _pdf_visible_text(pdf_bytes)
    assert rendered["redacted_payload"]["comparison_rows"][0]["title"].startswith("Pärchenhit")
    assert any(item in rendered["receipt"]["visual_elements"] for item in ("hero_cover", "cover"))
    assert any(item in rendered["receipt"]["visual_elements"] for item in ("tour_spread", "section_cards"))
    assert "comparison_snapshot" not in rendered["receipt"]["visual_elements"]
    assert rendered["receipt"]["media_link_count"] == 2
    assert rendered["receipt"]["embedded_media_refs"] == {"floorplans": 1, "photos": 1}
    assert "propertyquarry" in pdf_text.replace(" ", "").casefold()
    assert "Media appendix" not in pdf_text
    assert "Vergleichsbild" not in pdf_text
    assert "v5_agency_dossier_pdf" not in pdf_text
    assert "flipbook_3d" not in pdf_text
    assert "packets.propertyquarry.com/assets/floorplan.pdf" not in pdf_text
    assert "packets.propertyquarry.com/assets/photo.jpg" not in pdf_text
    normalized_pdf_text = pdf_text.replace(" ", "").casefold()
    assert "executivedecision" in normalized_pdf_text or rendered["receipt"]["renderer_version"] == "v7_agency_comparison_dossier_pdf"
    assert "Open 3D reconstruction" in pdf_text
    assert "Pärchenhit" not in pdf_text
    assert "Floorplan" in pdf_text


def test_fliplink_pdf_renders_listing_media_and_fact_json_shapes(tmp_path: Path) -> None:
    source = {
        "title": "Moderne, sonnige 2-Zimmer-Wohnung am Sachsenplatz",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1200-brigittenau/moderne-sonnige-2-zimmer-wohnung-provisionsfrei-mit-balkon-und-loggia-am-sachsenplatz-1406309127/",
        "tour_url": "https://propertyquarry.com/tours/test-floorplan?pane=floorplan-pane",
        "flythrough_url": "https://propertyquarry.com/tours/test-floorplan?pane=flythrough-pane",
        "review_url": "https://propertyquarry.com/app/research/property-scout:test?mode=review",
        "property_facts_json": {
            "rooms": 2.0,
            "area_sqm": 48.0,
            "total_rent_eur": 1095.0,
            "availability": "01.07.2026",
            "postal_name": "Wien, 20. Bezirk, Brigittenau",
            "country": "Österreich",
            "floorplan_count": 1,
        },
        "media_urls_json": [
            "https://cache.willhaben.at/mmo/7/140/630/9127_-948051133_hoved.jpg",
            "https://cache.willhaben.at/mmo/7/140/630/9127_-822616482_hoved.jpg",
        ],
        "floorplan_urls_json": [
            "https://cache.willhaben.at/mmo/7/140/630/9127_1035960641.jpg",
        ],
    }

    rendered = render_property_packet_pdf_legacy(
        artifact_root=tmp_path,
        publication_id="pub_json_shapes",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.OWNER_REVIEW,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    pdf_text = _pdf_visible_text(pdf_bytes)
    assert "1.095" in pdf_text
    assert "48" in pdf_text
    assert "Wien, 20. Bezirk, Brigittenau" in pdf_text
    assert "Open 3D reconstruction" in pdf_text
    assert rendered["receipt"]["embedded_media_refs"] == {"floorplans": 1, "photos": 2}
    assert any(item in rendered["receipt"]["visual_elements"] for item in ("hero_cover", "cover"))
    assert any(item in rendered["receipt"]["visual_elements"] for item in ("tour_spread", "section_cards"))


def test_fliplink_pdf_uses_tour_fallback_when_redacted_payload_lacks_direct_tour_url(tmp_path: Path) -> None:
    source = _source_payload()
    source.pop("tour_url", None)
    source["vendor_tour_url"] = "https://propertyquarry.com/tours/fallback-tour"

    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_tour_fallback",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.FAMILY_REVIEW,
        fliplink_format=FlipLinkFormat.FLIPBOOK_3D,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    pdf_text = _pdf_visible_text(pdf_bytes)
    assert "Open 3D reconstruction" in pdf_text
    assert rendered["receipt"].get("renderer_provider") in {"playwright", None}


def test_fliplink_pdf_can_embed_magic_fit_scene_for_private_packet(tmp_path: Path) -> None:
    source = _source_payload()
    source["magic_fit_scene"] = {
        "scene_id": "magicfit-1",
        "scene_type": "breakfast",
        "room_hint": "living room",
        "summary": "Family breakfast scene in the staged living and dining area.",
        "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Wm1cAAAAASUVORK5CYII=",
        "visual_simulation": True,
        "share_with_packet_pdf": True,
        "generated_at": "2026-06-08T09:00:00+00:00",
    }
    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_magicfit",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.OWNER_REVIEW,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=True,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    pdf_text = _pdf_visible_text(pdf_bytes)
    assert rendered["receipt"].get("renderer_provider") in {"playwright", None}
    assert rendered["receipt"].get("private_reference_media_included") in {False, None}
    assert rendered["redacted_payload"]["magic_fit_scene"]["scene_type"] == "breakfast"
