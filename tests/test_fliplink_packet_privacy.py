from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import render_property_packet_pdf
from app.services.fliplink.privacy import redact_property_packet


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
    assert "photo_refs" in redacted.receipt["removed_fields"]
    assert redacted.receipt["include_floorplan"] is False
    assert redacted.receipt["include_photos"] is False


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
    assert b"Market scope" in pdf_bytes
    assert b"Pricing signals" in pdf_bytes
    assert b"Media appendix" not in pdf_bytes
    assert b"Viewing checklist" not in pdf_bytes
    assert b"Exact Street 12" not in pdf_bytes
    assert b"private-owner-home" not in pdf_bytes
    assert b"Owner loves this exact flat" not in pdf_bytes
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
    assert rendered["receipt"]["renderer_version"] == "v7_agency_comparison_dossier_pdf"
    assert rendered["receipt"]["renderer_kind"] == "branded_visual_pdf"
    assert "section_cards" in rendered["receipt"]["visual_elements"]


def test_fliplink_pdf_can_render_comparison_snapshot(tmp_path: Path) -> None:
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

    rendered = render_property_packet_pdf(
        artifact_root=tmp_path,
        publication_id="pub_compare",
        principal_id="owner-1",
        source=source,
        packet_kind=PropertyPacketKind.OWNER_REVIEW,
        privacy_mode=PacketPrivacyMode.OWNER_PRIVATE,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
    )

    pdf_bytes = Path(str(rendered["pdf_path"])).read_bytes()
    assert b"Contents" in pdf_bytes
    assert b"Comparison snapshot" in pdf_bytes
    assert rendered["redacted_payload"]["comparison_rows"][0]["title"].startswith("Pärchenhit")
    assert "comparison_snapshot" in rendered["receipt"]["visual_elements"]
    assert "photo_gallery" in rendered["receipt"]["visual_elements"]
    assert rendered["receipt"]["media_link_count"] == 2
    assert rendered["receipt"]["embedded_media_refs"] == {"floorplans": 1, "photos": 1}
    assert b"PropertyQuarry" in pdf_bytes
    assert b"Media appendix" not in pdf_bytes
    assert b"v5_agency_dossier_pdf" not in pdf_bytes
    assert b"flipbook_3d" not in pdf_bytes
    assert b"https://packets.propertyquarry.com/assets/floorplan.pdf" not in pdf_bytes
    assert b"https://packets.propertyquarry.com/assets/photo.jpg" not in pdf_bytes
    assert b"Executive summary" in pdf_bytes
    assert b"https://propertyquarry.com/tours/test-demo-tour" in pdf_bytes
    assert b"Chosen ahead" in pdf_bytes
    assert b"next option" in pdf_bytes
    assert b"includes a floorplan" in pdf_bytes
    assert b"roughly" in pdf_bytes
    assert b"4 minutes" in pdf_bytes
    assert b"on foot" in pdf_bytes
    assert b"Family and school route" in pdf_bytes
    assert b"Official risk and safety context" in pdf_bytes
    assert b"Crime burden" in pdf_bytes
    assert b"Medical care" in pdf_bytes
    assert b"Area change and future infrastructure" in pdf_bytes
    assert b" re f" in pdf_bytes


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
    assert b"Open 3D reconstruction floor plan" in pdf_bytes
    assert b"https://propertyquarry.com/tours/fallback-tour" in pdf_bytes


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
    assert b"Lifestyle scene" in pdf_bytes
    assert b"Visual simulation" in pdf_bytes
    assert "magic_fit_scene" in rendered["receipt"]["visual_elements"]
    assert rendered["redacted_payload"]["magic_fit_scene"]["scene_type"] == "breakfast"
