from __future__ import annotations

import json
import importlib
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.product.service as product_service
import app.product.property_search_storage as property_search_storage
import app.product.property_investment_external_data as property_investment_external_data
from app.product.service import ProductService
from app.product.service import _property_alert_personal_fit_snapshot, _property_candidate_google_maps_url, _property_candidate_is_generic_listing_page, _property_candidate_matches_requested_location, _property_candidate_url_has_exact_location_probe, _property_candidate_url_has_location_probe, _property_search_location_hints
from app.product.service import _property_investment_underwriting_payload
from app.services.fliplink import build_fliplink_packet_service
from app.services.property_billing import property_billing_event_updates, property_billing_invoice_handoffs, property_commercial_snapshot, property_worker_cap
from app.services import property_market_catalog
from app.services.heyy_whatsapp_service import redact_phone_number
from tests.product_test_helpers import build_product_client, build_property_client, seed_product_state, start_workspace


def _poll_property_search_run_status(client, run_id: str) -> dict[str, object]:
    latest_status: dict[str, object] = {}
    for _ in range(120):
        response = client.get(f"/app/api/signals/property/search/run/{run_id}")
        assert response.status_code == 200, response.text
        latest_status = response.json()
        if str(latest_status.get("status") or "").strip() in {"processed", "completed_partial", "failed", "noop", "cancelled"}:
            return latest_status
        time.sleep(0.02)
    return latest_status


def test_free_property_plan_stays_narrower_than_paid_lanes() -> None:
    snapshot = property_commercial_snapshot({})

    assert snapshot["current_plan_key"] == "free"
    assert snapshot["research_depth"] == "standard"
    assert snapshot["investment_research_level"] == "none"
    assert snapshot["max_platforms"] == 3
    assert snapshot["max_results_per_source"] == 2
    assert snapshot["max_match_score"] == 35


def test_agent_property_plan_exposes_unlimited_results_per_provider() -> None:
    snapshot = property_commercial_snapshot(
        {"property_commercial": {"active_plan_key": "agent", "active_until": "2999-01-01T00:00:00+00:00"}}
    )

    assert snapshot["current_plan_key"] == "agent"
    assert snapshot["max_results_per_source"] == 0


def test_property_notification_price_signal_uses_catalog_currencies() -> None:
    assert product_service._property_candidate_notification_price_signal(  # type: ignore[attr-defined]
        {},
        listing_mode="buy",
        title="Sydney apartment | AUD 1,250,000 | 96 m2",
    ) == "AUD 1,250,000"


def test_property_search_compact_run_preserves_repair_lifecycle_fields() -> None:
    compact = property_search_storage._compact_property_search_run_record(  # type: ignore[attr-defined]
        {
            "run_id": "repair-run",
            "principal_id": "repair-principal",
            "status": "failed",
            "summary": {
                "status": "failed",
                "repair_status": "repairing",
                "repair_status_label": "Repairing",
                "repair_step_label": "Started a replacement search run from the saved brief.",
                "repair_outcome_summary": "Repair is retrying the interrupted search.",
                "repair_attempt_count": 1,
                "repair_replacement_run_id": "repair-run-retry",
                "repair_replacement_status_url": "/app/api/signals/property/search/run/repair-run-retry",
                "repair_resolved_total": 1,
                "repair_receipts": [
                    {
                        "run_id": "repair-run",
                        "filter_key": "run_worker_exception",
                        "resolution": "worker_exception_restart_required",
                    }
                ],
                "provider_repair_task_opened_total": 1,
                "provider_repair_task_existing_total": 0,
                "provider_repair_tasks": [
                    {
                        "status": "returned",
                        "filter_key": "run_worker_exception",
                        "resolution": "worker_exception_restart_required",
                    }
                ],
                "can_auto_repair": True,
            },
        }
    )

    summary = dict(compact["summary"])
    assert summary["repair_status"] == "repairing"
    assert summary["repair_step_label"] == "Started a replacement search run from the saved brief."
    assert summary["repair_replacement_run_id"] == "repair-run-retry"
    assert summary["repair_replacement_status_url"] == "/app/api/signals/property/search/run/repair-run-retry"
    assert summary["repair_resolved_total"] == 1
    assert summary["repair_receipts"][0]["resolution"] == "worker_exception_restart_required"
    assert summary["provider_repair_task_opened_total"] == 1
    assert summary["provider_repair_tasks"][0]["filter_key"] == "run_worker_exception"
    assert summary["can_auto_repair"] is True


def test_property_plan_investment_research_levels_follow_tier() -> None:
    plus = property_commercial_snapshot(
        {"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}}
    )
    agent = property_commercial_snapshot(
        {"property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}}
    )

    assert plus["investment_research_level"] == "preview"
    assert plus["research_depth"] == "deep"
    assert plus["max_platforms"] == 8
    assert plus["max_match_score"] == 45
    assert plus["magic_fit_scene_period"] == "day"
    assert plus["magic_fit_video_period"] == "day"
    assert agent["investment_research_level"] == "full"
    assert agent["research_depth"] == "deep"
    assert agent["max_platforms"] == 0
    assert agent["max_match_score"] == 60
    assert agent["magic_fit_scene_period"] == "none"
    assert agent["magic_fit_video_period"] == "none"


def test_property_billing_invoice_handoff_preserves_vat_and_document_state() -> None:
    updates = property_billing_event_updates(
        {},
        provider="payfunnels",
        event_type="payment.completed",
        event_id="evt-invoice-vat",
        plan_key="plus",
        order_id="pf-plus-vat",
        invoice_id="inv-vat-123",
        invoice_url="https://billing.example.test/invoices/inv-vat-123.pdf",
        invoice_status="issued",
        accounting_status="invoice_pending",
        payment_status="completed",
        currency="EUR",
        amount_eur="3.00",
        net_amount_eur="2.52",
        vat_amount_eur="0.48",
        vat_rate="20%",
    )

    handoffs = property_billing_invoice_handoffs({"billing_events_json": updates["billing_events_json"]})

    assert handoffs == [
        {
            "event_id": "evt-invoice-vat",
            "provider": "payfunnels",
            "plan_key": "plus",
            "order_id": "pf-plus-vat",
            "invoice_id": "inv-vat-123",
            "invoice_url": "https://billing.example.test/invoices/inv-vat-123.pdf",
            "state": "issued",
            "accounting_status": "invoice_pending",
            "invoice_status": "issued",
            "payment_status": "completed",
            "currency": "EUR",
            "amount_eur": "3.00",
            "net_amount_eur": "2.52",
            "vat_amount_eur": "0.48",
            "vat_rate": "20%",
            "recorded_at": handoffs[0]["recorded_at"],
        }
    ]


def test_property_search_preferences_use_school_evidence_priority_with_legacy_alias() -> None:
    normalized = property_market_catalog.normalize_property_search_preferences(
        {
            "school_evidence_priority": "very_important",
            "school_quality_priority": "important",
            "school_stage_preferences": ["volksschule"],
        }
    )
    legacy = property_market_catalog.normalize_property_search_preferences(
        {
            "school_quality_priority": "important",
            "school_stage_preferences": ["volksschule"],
        }
    )

    assert normalized["school_evidence_priority"] == "very_important"
    assert legacy["school_evidence_priority"] == "important"
    assert "school_quality_priority" not in normalized
    assert "school_quality_priority" not in legacy


def test_property_search_preferences_normalizer_drops_stale_agent_result_cap() -> None:
    normalized = property_market_catalog.normalize_property_search_preferences(
        {
            "max_results_per_source": 50,
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        }
    )

    assert "max_results_per_source" not in normalized


def test_property_search_preferences_normalizer_clamps_paid_result_cap_to_plan() -> None:
    normalized = property_market_catalog.normalize_property_search_preferences(
        {
            "max_results_per_source": 50,
            "property_commercial": {
                "active_plan_key": "plus",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        }
    )

    assert normalized["max_results_per_source"] == 5


def test_property_candidate_google_maps_url_prefers_listing_snapshot_locality_over_source_scope_placeholder() -> None:
    candidate = {
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

    url = _property_candidate_google_maps_url(candidate)

    assert "Brunnthalgasse%201B%2C%201020%20Wien" in url


def test_property_candidate_google_maps_url_uses_listing_text_postal_over_dirty_source_scope() -> None:
    candidate = {
        "title": "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD",
        "summary": "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
        "property_facts": {
            "postal_name": "1010 Vienna",
            "district": "1010 Vienna",
            "address": "1010 Vienna",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "source_city": "Vienna",
        },
    }

    url = _property_candidate_google_maps_url(candidate)

    assert "1220%20Wien" in url
    assert "1010%20Vienna" not in url


def test_property_worker_caps_follow_plan() -> None:
    assert property_worker_cap("free") == 1
    assert property_worker_cap("plus") == 2
    assert property_worker_cap("agent") == 4


def test_ranked_candidates_prefer_explicit_ranking_score_when_present() -> None:
    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Source A",
                "top_candidates": [
                    {"source_ref": "a", "fit_score": 92, "ranking_score": 48, "title": "Home-biased high fit"},
                    {"source_ref": "b", "fit_score": 70, "ranking_score": 83, "title": "Better investment score"},
                ],
            }
        ]
    )

    assert [row["source_ref"] for row in ranked[:2]] == ["b", "a"]


def test_ranked_candidates_exclude_false_positive_and_repair_only_rows() -> None:
    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Source A",
                "top_candidates": [
                    {"source_ref": "good", "fit_score": 92, "title": "Real ranked home"},
                    {"source_ref": "maybe", "fit_score": 99, "title": "Maybe false", "maybe_false": True},
                    {"source_ref": "repair", "fit_score": 98, "title": "Repair only", "flagged_for_repair": True},
                    {"source_ref": "filtered", "fit_score": 97, "title": "Hard filtered", "hard_filter_reason": "area_mismatch"},
                    {"source_ref": "status", "fit_score": 96, "title": "Status false positive", "candidate_status": "false_positive"},
                ],
            }
        ]
    )

    assert [row["source_ref"] for row in ranked] == ["good"]


def test_ranked_candidates_keep_soft_filter_reasons_but_exclude_hard_reasons() -> None:
    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Source A",
                "top_candidates": [
                    {
                        "source_ref": "soft",
                        "fit_score": 66,
                        "ranking_score": 66,
                        "title": "Soft preference miss",
                        "filter_reason": "playground_too_far_score_only",
                    },
                    {
                        "source_ref": "hard",
                        "fit_score": 98,
                        "ranking_score": 98,
                        "title": "Outside area",
                        "filter_reason": "outside_selected_area",
                    },
                    {
                        "source_ref": "hard-explicit",
                        "fit_score": 97,
                        "ranking_score": 97,
                        "title": "Hard filtered",
                        "hard_filter_reason": "area_mismatch",
                    },
                ],
            }
        ]
    )

    assert [row["source_ref"] for row in ranked] == ["soft"]
    assert ranked[0]["rank"] == 1


def test_ranked_candidates_exclude_unmarked_postal_conflicts_from_exact_source_scope() -> None:
    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                "source_scope_label": "Willhaben | Austria | Rent | 1010 Vienna",
                "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1010+Vienna",
                "top_candidates": [
                    {
                        "source_ref": "outside-scope",
                        "fit_score": 98,
                        "ranking_score": 98,
                        "title": "Terrassenwohnung auf der Hohen Warte, 66 m2, EUR 1.599, (1190 Wien)",
                        "property_facts": {
                            "postal_name": "1190 Wien",
                            "source_scope_location": "1010 Vienna",
                            "listing_postal_evidence": [
                                {"postal_code": "1190", "postal_name": "1190 Wien"},
                            ],
                        },
                    },
                    {
                        "source_ref": "inside-scope",
                        "fit_score": 77,
                        "ranking_score": 77,
                        "title": "Wohnung mieten in 1010 Wien | 70 m2 | 2 Zimmer",
                        "property_facts": {
                            "postal_name": "1010 Wien",
                            "source_scope_location": "1010 Vienna",
                            "listing_postal_evidence": [
                                {"postal_code": "1010", "postal_name": "1010 Wien"},
                            ],
                        },
                    },
                ],
            }
        ]
    )

    assert [row["source_ref"] for row in ranked] == ["inside-scope"]
    assert ranked[0]["rank"] == 1


def test_ranked_candidates_merge_top_and_research_rows_and_keep_stable_candidate_ref() -> None:
    ranked = product_service._property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "source_ref": "property-scout:1900851485",
                        "property_url": "https://example.test/listing/1900851485",
                        "review_url": "https://propertyquarry.test/app/research/packet-1",
                        "title": "Luxury Residence",
                        "fit_score": 53,
                        "tour_url": "https://propertyquarry.test/tours/luxury-residence",
                        "tour_status": "created",
                    }
                ],
                "research_candidates": [
                    {
                        "source_ref": "property-scout:1900851485",
                        "property_url": "https://example.test/listing/1900851485",
                        "review_url": "https://propertyquarry.test/app/research/packet-1",
                        "title": "Luxury Residence",
                        "fit_score": 53,
                        "flythrough_url": "https://propertyquarry.test/tours/files/luxury-residence/video.mp4",
                        "flythrough_status": "rendered",
                    }
                ],
            }
        ]
    )

    assert len(ranked) == 1
    assert ranked[0]["source_ref"] == "property-scout:1900851485"
    assert ranked[0]["tour_url"] == "https://propertyquarry.test/tours/luxury-residence"
    assert ranked[0]["flythrough_url"] == "https://propertyquarry.test/tours/files/luxury-residence/video.mp4"
    assert ranked[0]["candidate_ref"]


def test_property_scout_notification_source_hides_search_scope_metadata() -> None:
    text = product_service._property_alert_review_telegram_text(
        title="Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | EUR 1.090",
        summary="2-Zimmer Wohnung mit Traumblick in 1220 Wien.",
        counterparty="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
        personal_fit_assessment={"fit_score": 54.0, "recommendation": "ask_for_clarification"},
    )

    assert "Source: DER STANDARD Immobilien" in text
    assert "Source: DER STANDARD Immobilien | Austria | Rent | 1010 Vienna" not in text

    willhaben = product_service._property_alert_review_telegram_text(
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich",
        summary="Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        personal_fit_assessment={"fit_score": 54.0, "recommendation": "ask_for_clarification"},
    )

    assert "Source: Willhaben" in willhaben
    assert "1010 Vienna" not in willhaben
    assert "Austria | Rent" not in willhaben

    willhaben_german_scope = product_service._property_alert_review_telegram_text(
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse",
        summary="Penthouse-Charakter in Stadt Salzburg.",
        counterparty="Willhaben | AT | Miete | 1010 Wien, Innere Stadt",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        personal_fit_assessment={"fit_score": 54.0, "recommendation": "ask_for_clarification"},
    )

    assert "Source: Willhaben" in willhaben_german_scope
    assert "1010" not in willhaben_german_scope
    assert "Innere Stadt" not in willhaben_german_scope
    assert "Miete" not in willhaben_german_scope

    cooperative = product_service._property_alert_review_telegram_text(
        title="Geförderte Wohnung",
        summary="Review candidate.",
        counterparty="Genossenschaften | Austria | Rent | 1010 Vienna | GESIBA Wohnungen",
        account_email="",
        property_url="https://example.test/listing",
        personal_fit_assessment={"fit_score": 64.0, "recommendation": "mention"},
    )

    assert "Source: Genossenschaften · GESIBA Wohnungen" in cooperative
    assert "1010 Vienna" not in cooperative


def test_property_requested_location_match_keeps_title_postal_match_even_when_scope_shares_same_postal() -> None:
    assert _property_candidate_matches_requested_location(
        location_hints=("8055 Graz",),
        property_url="https://www.willhaben.at/example",
        title="Erstbezugswohnung, 47,57 m², € 613,49, (8055 Graz) - willhaben",
        summary="Modern rental apartment in Graz.",
        property_facts={
            "postal_name": "8055 Graz",
            "source_scope_location": "8055 Graz",
            "source_postal_code": "8055",
            "country_code": "AT",
        },
        country_code="AT",
        region_code="steiermark",
    )


def test_property_search_analysis_cap_expands_for_exact_scope() -> None:
    assert product_service._property_search_analysis_cap_per_source(
        max_results=5,
        candidate_total=40,
        exact_scope=False,
    ) == 12
    assert product_service._property_search_analysis_cap_per_source(
        max_results=5,
        candidate_total=40,
        exact_scope=True,
    ) == 30
    assert product_service._property_search_analysis_cap_per_source(
        max_results=5,
        candidate_total=40,
        exact_scope=True,
        focused_scope=True,
    ) == 40
    assert product_service._property_search_has_exact_scope(
        request_preferences={"selected_districts": []},
        location_hints=("1210 Wien",),
    )
    assert not product_service._property_search_has_exact_scope(
        request_preferences={"selected_districts": []},
        location_hints=("Wien",),
    )


def test_property_search_location_matching_treats_wien_as_broad_vienna_scope() -> None:
    assert _property_candidate_matches_requested_location(
        location_hints=("Vienna",),
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/demo",
        title="Wohnung mieten in 1020 Wien | 74 m² | 3 Zimmer",
        summary="Wohnung im 2. Bezirk.",
        property_facts={"postal_name": "1020 Wien"},
        country_code="AT",
        region_code="vienna",
    )
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/demo",
        title="Wohnung mieten in 1020 Wien | 74 m² | 3 Zimmer",
        summary="Wohnung im 2. Bezirk.",
        property_facts={"postal_name": "1020 Wien"},
        country_code="AT",
        region_code="vienna",
    )


def test_investment_underwriting_payload_exposes_dimensions_and_confidence() -> None:
    payload = _property_investment_underwriting_payload(
        title="Apartment near U-Bahn",
        summary="Clean apartment with floorplan and stable tenant demand.",
        facts={
            "has_floorplan": True,
            "tenant_status": "vacant",
            "energy_certificate_present": True,
            "map_lat": 48.21,
            "map_lng": 16.38,
            "nearest_subway_m": 240,
            "nearest_supermarket_m": 180,
            "nearest_medical_care_m": 700,
            "source_trust_tier": "high",
            "source_access_level": "direct",
            "future_change_research": {
                "planning_confidence": "high",
                "investment_impact": "positive tailwind",
                "future_value_drivers": ["subway upgrade", "office employment growth"],
            },
            "official_risk_evidence": {
                "sources": [{"risk_key": "flood_risk", "verification_state": "needs_review"}],
            },
        },
        preferences={
            "search_goal": "investment",
            "investment_strategy": "best_overall",
            "min_gross_yield_pct": 4,
        },
        snapshot={
            "gross_yield_pct": 4.8,
            "market_buy_delta_pct": -7.5,
            "expected_monthly_rent_eur": 1450.0,
            "payback_years": 20.3,
            "current_price_eur": 362000.0,
            "current_area_sqm": 67.0,
            "current_price_per_sqm_eur": 5400.0,
            "market_buy_per_sqm_eur": 5838.0,
            "market_rent_per_sqm_eur": 18.1,
            "buy_sample_count": 5,
            "rent_sample_count": 4,
        },
    )

    assert payload["score"] > 0
    assert payload["confidence_label"] in {"High confidence", "Partial evidence"}
    assert payload["gross_yield_display"] == "4.8% gross yield"
    assert payload["market_delta_display"] == "7.5% below local buy median"
    assert payload["score_display"].endswith("institutional score")
    assert len(payload["dimensions"]) == 7
    assert {row["key"] for row in payload["dimensions"]} == {"return", "value", "demand", "liquidity", "risk", "execution", "evidence"}
    assert payload["net_yield_display"]
    assert payload["cap_rate_display"]


def test_investment_external_snapshot_falls_back_honestly_without_live_feeds(monkeypatch) -> None:
    monkeypatch.setattr(property_investment_external_data, "_fetch_external_feed", lambda prefix, request_payload: {})
    snapshot = property_investment_external_data.property_investment_external_snapshot(
        country_code="AT",
        property_url="https://example.test/listing/1",
        title="Fallback investment case",
        facts={"area_m2": 80, "operating_costs_monthly": 260, "map_lat": 48.2, "map_lng": 16.38},
        preferences={"equity_available_eur": 140000, "loan_term_years": 25, "vacancy_reserve_pct": 5, "capex_reserve_pct": 6},
        snapshot={
            "current_price_eur": 420000,
            "current_area_sqm": 80,
            "expected_monthly_rent_eur": 1450,
            "expected_annual_rent_eur": 17400,
        },
    )

    assert snapshot["feed_status_label"] == "Fallback underwriting model"
    assert snapshot["confidence_label"] == "Fallback assumptions"
    assert snapshot["rent_roll"]["source_mode"] == "comp_fallback"
    assert snapshot["operating_costs"]["source_mode"] in {"listing_fact", "assumption"}
    assert snapshot["taxes"]["source_mode"] == "country_default"
    assert snapshot["financing"]["source_mode"] == "assumption"
    assert snapshot["net_yield_pct"] is not None
    assert snapshot["cap_rate_pct"] is not None


def test_investment_external_feed_rejects_insecure_http_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", "http://example.test/feed")

    def _unexpected_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not run for insecure feed URLs")

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", _unexpected_urlopen)
    payload = property_investment_external_data._fetch_external_feed(
        "EA_PROPERTY_RENT_ROLL_FEED",
        {"country_code": "AT", "purchase_price_eur": 300000},
    )

    assert payload == {}


def test_investment_external_feed_rejects_https_host_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", "https://example.test/feed")
    monkeypatch.delenv("EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS", raising=False)

    def _unexpected_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not run for non-allowlisted https feed URLs")

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", _unexpected_urlopen)
    payload = property_investment_external_data._fetch_external_feed(
        "EA_PROPERTY_RENT_ROLL_FEED",
        {"country_code": "AT", "purchase_price_eur": 300000},
    )

    assert payload == {}


def test_investment_external_feed_allows_only_exact_or_wildcard_subdomains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", "https://rent.data.example.test/feed")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS", "example.test, *.data.example.test")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH", str(tmp_path / "investment_cache.json"))
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_TTL_SECONDS", "60")
    calls: list[str] = []

    class _Response:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/json"}
            self._sent = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return b'{"annual_rent_eur": 18000, "source_label": "Approved data feed"}'

    def _urlopen(request, *args, **kwargs):
        calls.append(str(request.full_url))
        return _Response()

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", _urlopen)

    payload = property_investment_external_data._fetch_external_feed(
        "EA_PROPERTY_RENT_ROLL_FEED",
        {"country_code": "AT", "purchase_price_eur": 300000},
    )

    assert calls
    assert payload["annual_rent_eur"] == 18000
    assert payload["source_mode"] == "live_feed"


def test_investment_external_feed_wildcard_does_not_match_apex_or_lookalike_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS", "*.data.example.test")

    def _unexpected_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not run for non-matching wildcard feed hosts")

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", _unexpected_urlopen)

    for url in (
        "https://data.example.test/feed",
        "https://evil-data.example.test/feed",
        "https://data.example.test.evil.test/feed",
    ):
        monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", url)
        payload = property_investment_external_data._fetch_external_feed(
            "EA_PROPERTY_RENT_ROLL_FEED",
            {"country_code": "AT", "purchase_price_eur": 300000, "url": url},
        )
        assert payload == {}


def test_investment_external_feed_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", "https://example.test/feed")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS", "example.test")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_MAX_RESPONSE_BYTES", "64")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH", str(tmp_path / "investment_cache.json"))

    class _Response:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/json", "Content-Length": "512"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            return b'{"annual_rent_eur": 18000}'

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", lambda *args, **kwargs: _Response())
    payload = property_investment_external_data._fetch_external_feed(
        "EA_PROPERTY_RENT_ROLL_FEED",
        {"country_code": "AT", "purchase_price_eur": 300000},
    )

    assert payload == {}


def test_investment_external_feed_rejects_streamed_oversized_response_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_PROPERTY_RENT_ROLL_FEED_URL", "https://example.test/feed")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_ALLOWED_HOSTS", "example.test")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_MAX_RESPONSE_BYTES", "64")
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH", str(tmp_path / "investment_cache.json"))

    class _Response:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/json"}
            self._body = b'{"annual_rent_eur": 18000, "source_label": "' + (b"a" * 5000) + b'"}'
            self._offset = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(self._body):
                return b""
            if size is None or size < 0:
                size = len(self._body) - self._offset
            chunk = self._body[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    monkeypatch.setattr(property_investment_external_data.urllib.request, "urlopen", lambda *args, **kwargs: _Response())
    payload = property_investment_external_data._fetch_external_feed(
        "EA_PROPERTY_RENT_ROLL_FEED",
        {"country_code": "AT", "purchase_price_eur": 300000},
    )

    assert payload == {}


def test_investment_external_cache_path_defaults_to_durable_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH", raising=False)

    assert property_investment_external_data._cache_path() == Path("/docker/property/state/property_investment_external_cache.json")


def test_investment_external_cache_file_is_private(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "investment_cache.json"
    monkeypatch.setenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH", str(cache_path))

    property_investment_external_data._put_cached_feed_payload(
        lane="EA_PROPERTY_RENT_ROLL_FEED",
        request_payload={"country_code": "AT"},
        data={"annual_rent_eur": 18000},
    )

    assert cache_path.exists()
    assert oct(cache_path.stat().st_mode & 0o777) == "0o600"


def test_findmyhome_entry_links_are_not_treated_as_supported_property_listings() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/immo/wohnung-kaufen/wien?id=13&entry=20&sort=&dir=ASC&pp=20&vars=id%3A13%3Bw_e%3A1%3Bland%3AAT%3Bbl%3A9%3B&lang=de&module=select&list="
    )


def test_findmyhome_search_page_is_not_treated_as_property_listing() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/immo/wohnung-kaufen/wien"
    )


def test_findmyhome_search_state_urls_stay_unsupported_after_sanitization() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://findmyhome.at/immo/wohnung-kaufen/wien?id=14&entry=10&sort=sort_fl&dir=ASC&pp=10&vars=&lang=&module=&list='/'"
    )


def test_findmyhome_short_detail_url_is_treated_as_supported_listing() -> None:
    assert product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/5620769?tl=1"
    )


def test_findmyhome_result_cards_extract_short_detail_urls() -> None:
    html = '''
    <div class="row margin-top-20">
      <div class="col-xs-12 col-sm-9 col-md-9 col-lg-9">
        <h3 class="obj_list">
          <strong><span style="color:#c30a32">TOP: </span></strong>
          <a href='/5620769?tl=1' class='btnHeadlineErgebnisliste'>Helle 2-Zimmer Wohnung, Nähe Meiselmarkt</a>
        </h3>
      </div>
    </div>
    '''

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.findmyhome.at/immo/wohnung-kaufen/wien",
        html=html,
        source_spec={"provider_filter_pushdown": {"requested": {}, "applied": {}}},
    )

    assert urls == ("https://www.findmyhome.at/5620769?tl=1",)


def test_free_property_plan_uses_declared_visual_generation_caps() -> None:
    snapshot = property_commercial_snapshot({})

    assert snapshot["magic_fit_scene_limit"] == 1
    assert snapshot["magic_fit_video_limit"] == 1
    assert snapshot["magic_fit_scene_period"] == "week"
    assert snapshot["magic_fit_video_period"] == "day"
    free_plan = next(plan for plan in snapshot["plan_catalog"] if plan["plan_key"] == "free")
    assert "one 3D reconstruction floor plan per week and one interior flythrough per day" in free_plan["features"]


class _QuotaRow:
    def __init__(self, *, event_type: str, created_at: str, channel: str = "product") -> None:
        self.channel = channel
        self.event_type = event_type
        self.created_at = created_at


class _QuotaRuntime:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def list_recent_observations(self, limit: int = 4000, principal_id: str = "") -> list[object]:
        return list(self._rows)[:limit]


class _QuotaOnboarding:
    def __init__(self, preferences: dict[str, object]) -> None:
        self._preferences = preferences

    def status(self, principal_id: str = "") -> dict[str, object]:
        return {"property_search_preferences": dict(self._preferences)}


class _QuotaContainer:
    def __init__(self, preferences: dict[str, object], rows: list[object]) -> None:
        self.onboarding = _QuotaOnboarding(preferences)
        self.channel_runtime = _QuotaRuntime(rows)


class _PreviewCacheRuntime:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def ingest_observation(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        dedupe_key: str = "",
        **_kwargs,
    ) -> object:
        row = SimpleNamespace(
            principal_id=principal_id,
            channel=channel,
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            dedupe_key=dedupe_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            observation_id=str(uuid.uuid4()),
        )
        self.rows.insert(0, row)
        return row

    def list_recent_observations(self, limit: int = 4000, principal_id: str = "") -> list[object]:
        rows = [
            row
            for row in self.rows
            if not principal_id or str(getattr(row, "principal_id", "") or "").strip() == str(principal_id or "").strip()
        ]
        return rows[:limit]


class _PreviewCacheContainer:
    def __init__(self) -> None:
        self.channel_runtime = _PreviewCacheRuntime()


def test_property_visual_quota_enforces_free_daily_magic_fit_limit() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _QuotaContainer(
        {},
        [
            _QuotaRow(
                event_type="property_magic_fit_scene_created",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )

    with pytest.raises(ValueError, match="property_magic_fit_upgrade_required:plus"):
        service._enforce_property_visual_quota(
            principal_id="cf-email:quota-free@example.test",
            property_preferences={},
            quota_kind="scene",
        )


def test_property_visual_quota_enforces_plus_daily_video_limit() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _QuotaContainer(
        {"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}},
        [
            _QuotaRow(event_type="generic_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
            _QuotaRow(event_type="willhaben_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
            _QuotaRow(event_type="generic_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
        ],
    )

    with pytest.raises(ValueError, match="property_tour_upgrade_required:agent"):
        service._enforce_property_visual_quota(
            principal_id="cf-email:quota-plus@example.test",
            property_preferences={"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}},
            quota_kind="video",
        )


def test_property_preview_timeout_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    started = {"value": False}

    def _slow_preview(property_url: str, prefer_fast: bool = False) -> dict[str, object]:
        started["value"] = True
        time.sleep(0.2)
        return {"property_url": property_url, "property_facts_json": {}}

    monkeypatch.setattr(product_service, "_property_scout_page_preview", _slow_preview)
    monkeypatch.setattr(product_service, "_property_search_preview_timeout_seconds", lambda *, prefer_fast: 0.05)

    with pytest.raises(TimeoutError, match="property_preview_timeout:fast"):
        product_service._property_scout_page_preview_with_timeout("https://example.com/listing", prefer_fast=True)

    assert started["value"] is True


def test_floorplan_recovery_workers_store_recovered_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProductService.__new__(ProductService)
    stored: dict[str, dict[str, object]] = {}

    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_FLOORPLAN_RECOVERY_LIMIT", "4")
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_PREVIEW_TIMEOUT_SECONDS", "1")

    def _fake_preview(property_url: str, prefer_fast: bool = False) -> dict[str, object]:
        return {
            "property_url": property_url,
            "title": "Recovered floorplan listing",
            "summary": "Floorplan PDF found",
            "property_facts_json": {"floorplan_urls_json": [f"{property_url}/floorplan.pdf"]},
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)
    monkeypatch.setattr(
        service,
        "_property_public_preview_cache_store",
        lambda *, cache_index, property_url, preview: stored.setdefault(property_url, dict(preview)),
    )

    recovered = service._recover_floorplans_for_candidates(
        candidates=[
            {"property_url": "https://example.com/listing-1"},
            {"property_url": "https://example.com/listing-2"},
        ],
        cache_index={},
        plan_key="plus",
    )

    assert set(recovered) == {"https://example.com/listing-1", "https://example.com/listing-2"}
    assert set(stored) == {"https://example.com/listing-1", "https://example.com/listing-2"}


def test_propertyquarry_public_urls_do_not_inherit_external_brain_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", raising=False)
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.delenv("EA_PUBLIC_TOUR_BASE_URL", raising=False)

    assert product_service._public_app_base_url() == "https://propertyquarry.com"

    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")

    assert product_service._property_public_app_base_url() == "https://propertyquarry.com"
    assert product_service._property_public_tour_base_url() == "https://propertyquarry.com/tours"

    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_APP_BASE_URL", "https://app.propertyquarry.test")

    assert product_service._property_public_app_base_url() == "https://app.propertyquarry.test"


def test_property_public_preview_cache_reuses_sanitized_public_facts() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _PreviewCacheContainer()
    cache_index: dict[str, dict[str, object]] = {}
    stored = service._property_public_preview_cache_store(
        cache_index=cache_index,
        property_url="https://example.test/listing/1",
        preview={
            "property_url": "https://example.test/listing/1",
            "listing_id": "listing-1",
            "title": "Quiet courtyard flat",
            "summary": "Useful public preview facts.",
            "property_facts_json": {
                "provider_channel": "findmyhome_at",
                "postal_name": "1200 Wien",
                "rooms": 3,
                "has_floorplan": True,
                "exact_address": "Hidden 1",
                "lat": 48.2,
                "cookie_debug": "nope",
            },
            "floorplan_urls_json": ["https://cdn.example.test/floorplan.png"],
        },
    )

    assert stored["property_facts_json"]["provider_channel"] == "findmyhome_at"
    assert "exact_address" not in stored["property_facts_json"]
    assert "lat" not in stored["property_facts_json"]
    assert "cookie_debug" not in stored["property_facts_json"]

    indexed = service._property_public_preview_cache_index()
    loaded = service._property_public_preview_cache_lookup(
        cache_index=indexed,
        property_url="https://example.test/listing/1",
    )

    assert loaded is not None
    assert loaded["title"] == "Quiet courtyard flat"
    assert loaded["property_facts_json"]["has_floorplan"] is True


def test_austria_noise_preference_uses_layout_quiet_signal_only_as_weak_hint() -> None:
    adjustment, notes = product_service._property_austria_preference_score_adjustment(
        preferences={"country_code": "AT", "avoid_noise_risk_area": True},
        property_facts={"quiet_layout_signal": "weak_positive"},
        title="Wohnung",
        summary="Ruhige Lage",
    )

    assert adjustment == -2.0
    assert "noise evidence missing" in notes
    assert "layout-derived quiet signal" in notes


def test_property_public_preview_workers_warm_multiple_provider_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProductService.__new__(ProductService)
    service._container = _PreviewCacheContainer()
    cache_index: dict[str, dict[str, object]] = {}
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_WARM_LIMIT", "2")

    preview_calls: list[str] = []

    def _fake_preview(property_url: str, prefer_fast: bool = False) -> dict[str, object]:
        preview_calls.append(property_url)
        return {
            "property_url": property_url,
            "listing_id": property_url.rsplit("/", 1)[-1],
            "title": f"Preview for {property_url.rsplit('/', 1)[-1]}",
            "summary": "Reusable public facts.",
            "property_facts_json": {
                "provider_channel": "provider",
                "has_floorplan": property_url.endswith("1"),
            },
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_compat", _fake_preview)

    result = service._warm_property_public_preview_cache_for_sources(
        specs=[
            {"platform": "derstandard_at", "label": "DER STANDARD", "url": "https://example.test/derstandard", "source_access_level": "browser"},
            {"platform": "immmo_at", "label": "immmo", "url": "https://example.test/immmo", "source_access_level": "public"},
        ],
        prefetched_source_results={
            ("derstandard_at", "https://example.test/derstandard"): {
                "listing_urls": [
                    "https://example.test/listing/1",
                    "https://example.test/listing/2",
                ]
            },
            ("immmo_at", "https://example.test/immmo"): {
                "listing_urls": [
                    "https://example.test/listing/3",
                    "https://example.test/listing/4",
                ]
            },
        },
        cache_index=cache_index,
        plan_key="plus",
    )

    assert result["enabled"] is True
    assert result["worker_concurrency"] == 2
    assert result["warm_limit"] == 2
    assert result["warmed_total"] == 4
    assert result["sources_touched"] == 2
    assert set(preview_calls) == {
        "https://example.test/listing/1",
        "https://example.test/listing/2",
        "https://example.test/listing/3",
        "https://example.test/listing/4",
    }
    assert service._property_public_preview_cache_lookup(
        cache_index=cache_index,
        property_url="https://example.test/listing/3",
    ) is not None


def test_property_adjacent_area_radius_uses_boundary_distance_before_centroid(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [16.3600, 48.2000],
            [16.3700, 48.2000],
            [16.3700, 48.2100],
            [16.3600, 48.2100],
            [16.3600, 48.2000],
        ]],
    }

    monkeypatch.setattr(
        product_service,
        "_property_research_boundary_record",
        lambda query: {
            "display_name": query,
            "geojson": boundary_geojson,
            "bounds": (16.3600, 48.2000, 16.3700, 48.2100),
            "lat": 48.2050,
            "lon": 16.3650,
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_research_forward_geocode",
        lambda query: {"lat": 48.2050, "lon": 16.3650},
    )

    assert product_service._property_candidate_within_adjacent_area_radius(
        location_hints=("1020 Vienna",),
        property_facts={"map_lat": 48.2050, "map_lng": 16.3714},
        country_code="AT",
        region_code="vienna",
        adjacent_area_radius_m=200,
    ) is True


def test_property_adjacent_area_radius_falls_back_to_reference_point_when_boundary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(product_service, "_property_research_boundary_record", lambda query: {})
    monkeypatch.setattr(
        product_service,
        "_property_research_forward_geocode",
        lambda query: {"lat": 48.2050, "lon": 16.3650},
    )

    assert product_service._property_candidate_within_adjacent_area_radius(
        location_hints=("1020 Vienna",),
        property_facts={"map_lat": 48.2050, "map_lng": 16.3655},
        country_code="AT",
        region_code="vienna",
        adjacent_area_radius_m=100,
    ) is True


def test_property_search_interleave_by_provider_group_spreads_same_provider_shards() -> None:
    ordered = product_service._property_search_interleave_by_provider_group(
        [
            {"platform": "derstandard_at", "label": "DER STANDARD | 1010 Vienna"},
            {"platform": "derstandard_at", "label": "DER STANDARD | 1020 Vienna"},
            {"platform": "immmo_at", "label": "immmo | 1010 Vienna"},
            {"platform": "findmyhome_at", "label": "FindMyHome | 1010 Vienna"},
            {"platform": "derstandard_at", "label": "DER STANDARD | 1080 Vienna"},
        ]
    )

    assert [row["platform"] for row in ordered[:4]] == [
        "derstandard_at",
        "immmo_at",
        "findmyhome_at",
        "derstandard_at",
    ]


def test_property_search_provider_total_collapses_source_variants() -> None:
    provider_specs = [
        {"provider_source_key": "willhaben:vienna", "platform": "kalandra"},
        {"provider_source_key": "willhaben:salzburg", "provider_key": "WILLHABEN"},
        {"provider_key": "kalandra", "label": "Kalandra | Vienna"},
        {"source_provider_key": "derstandard:vienna", "platform": "derstandard_at"},
        {"source_provider_key": "derstandard:1220", "provider_family": "cooperative"},
    ]

    assert product_service._property_search_provider_total(provider_specs) == 3


def test_property_search_run_status_fixes_provider_total_from_source_variants() -> None:
    principal_id = "exec-property-run-provider-count-fix"
    client = build_product_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"provider-total-fix-{uuid.uuid4().hex}"
    now_iso = datetime.now(timezone.utc).isoformat()

    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "created_at": now_iso,
            "updated_at": now_iso,
            "selected_platforms": ["willhaben", "kalandra", "wiener_wohnen"],
            "summary": {
                "provider_total": 156,
                "source_variant_total": 156,
                "sources": [
                    {
                        "provider_source_key": "willhaben:vienna",
                        "source_label": "Willhaben | Vienna",
                    },
                    {
                        "provider_source_key": "willhaben:salzburg",
                        "source_label": "Willhaben | Salzburg",
                    },
                    {
                        "source_provider_key": "wiener_wohnen:wien",
                        "source_label": "Wiener Wohnen",
                    },
                    {
                        "source_provider_key": "kalandra:wien",
                        "source_label": "Kalandra Wien",
                    },
                ],
            },
        }

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert int(dict(status.get("summary") or {}).get("provider_total") or 0) == 3
    assert int(dict(status.get("summary") or {}).get("source_variant_total") or 0) == 156


def test_property_visual_state_does_not_cross_update_same_source_ref_different_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-visual-state-provider-collision"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"visual-state-collision-{uuid.uuid4().hex}"
    shared_source_ref = "provider:shared-listing-id"
    first_url = "https://provider-a.example/listings/shared"
    second_url = "https://provider-b.example/listings/shared"
    now_iso = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(product_service, "_store_property_search_run_record", lambda payload: None)

    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        previous_registry = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "processed",
            "created_at": now_iso,
            "updated_at": now_iso,
            "summary": {
                "sources": [
                    {
                        "source_label": "Provider A",
                        "top_candidates": [
                            {
                                "title": "Shared listing from provider A",
                                "source_ref": shared_source_ref,
                                "property_url": first_url,
                            }
                        ],
                    },
                    {
                        "source_label": "Provider B",
                        "top_candidates": [
                            {
                                "title": "Shared listing from provider B",
                                "source_ref": shared_source_ref,
                                "property_url": second_url,
                            }
                        ],
                    },
                ],
                "ranked_candidates": [],
            },
        }
    try:
        service._persist_property_search_visual_state(  # noqa: SLF001
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="",
            source_ref=shared_source_ref,
            property_url=second_url,
            visual_state={"tour_status": "pending", "flythrough_status": "queued"},
        )
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            sources = list(dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id]["summary"]).get("sources") or [])
        first_candidate = dict(dict(sources[0]).get("top_candidates")[0])
        second_candidate = dict(dict(sources[1]).get("top_candidates")[0])
        assert "tour_status" not in first_candidate
        assert first_candidate["property_url"] == first_url
        assert second_candidate["property_url"] == second_url
        assert second_candidate["tour_status"] == "pending"
        assert second_candidate["flythrough_status"] == "queued"
    finally:
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.update(previous_registry)


def test_property_tour_event_lookup_does_not_reuse_same_source_ref_for_other_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-tour-event-url-collision"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    shared_source_ref = "provider:shared-listing-id"
    first_url = "https://provider-a.example/listings/shared"
    second_url = "https://provider-b.example/listings/shared"
    rows = [
        SimpleNamespace(
            principal_id=principal_id,
            channel="product",
            event_type="generic_property_tour_created",
            source_id=shared_source_ref,
            payload={
                "property_url": first_url,
                "tour_url": "https://propertyquarry.com/tours/provider-a-shared",
            },
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    ]

    monkeypatch.setattr(
        client.app.state.container.channel_runtime,
        "list_recent_observations",
        lambda limit=4000, principal_id="": rows[:limit],
    )

    assert (
        service._latest_property_tour_event(  # noqa: SLF001
            principal_id=principal_id,
            source_ref=shared_source_ref,
            property_url=second_url,
        )
        is None
    )
    matched = service._latest_property_tour_event(  # noqa: SLF001
        principal_id=principal_id,
        source_ref=shared_source_ref,
        property_url=first_url,
    )
    assert matched is not None
    assert dict(matched["payload"])["tour_url"].endswith("/provider-a-shared")


def test_property_scout_listing_ref_host_qualifies_weak_provider_ids() -> None:
    willhaben_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/test-123456789/"
    provider_a_url = "https://provider-a.example/listings/123456789/"
    provider_b_url = "https://provider-b.example/listings/123456789/"

    assert product_service._property_scout_listing_ref("123456789", willhaben_url) == "123456789"  # type: ignore[attr-defined]
    assert (  # type: ignore[attr-defined]
        product_service._property_scout_listing_ref("123456789", provider_a_url) == "provider-a.example:123456789"
    )
    assert (  # type: ignore[attr-defined]
        product_service._property_scout_listing_ref("123456789", provider_b_url) == "provider-b.example:123456789"
    )
    assert product_service._property_scout_listing_ref("", provider_a_url) == "provider-a.example:123456789"  # type: ignore[attr-defined]
    assert product_service._property_scout_listing_ref("provider:123", provider_a_url) == "provider:123"  # type: ignore[attr-defined]


def test_property_search_run_status_fixes_inflated_provider_total_when_source_rows_missing() -> None:
    principal_id = "exec-property-run-provider-count-no-sources"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"provider-total-no-sources-{uuid.uuid4().hex}"

    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "selected_platforms": ["willhaben", "kalandra", "wiener_wohnen"],
            "summary": {
                "provider_total": 156,
                "source_variant_total": 156,
                "sources": [],
            },
        }

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert int(dict(status.get("summary") or {}).get("provider_total") or 0) == 3


def test_property_search_run_status_lightweight_fixes_inflated_provider_total(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-run-provider-count-lightweight"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"provider-total-lightweight-{uuid.uuid4().hex}"

    compact_run = {
        "run_id": run_id,
        "principal_id": principal_id,
        "status": "in_progress",
        "selected_platforms": ["willhaben", "kalandra", "wiener_wohnen"],
        "summary": {
            "provider_total": 156,
            "source_variant_total": 156,
            "sources_total": 104,
        },
    }

    def _fake_load_compact_record(*, run_id: str, principal_id: str) -> dict[str, object] | None:
        if str(run_id or "").strip() == compact_run["run_id"] and str(principal_id or "").strip() == compact_run["principal_id"]:
            return dict(compact_run)
        return None

    monkeypatch.setattr(product_service, "_load_property_search_run_compact_record", _fake_load_compact_record)
    status = service.get_property_search_run_status(
        principal_id=principal_id,
        run_id=run_id,
        lightweight=True,
    )

    assert status is not None
    assert int(dict(status.get("summary") or {}).get("provider_total") or 0) == 3
    assert int(dict(status.get("summary") or {}).get("source_variant_total") or 0) == 156


def test_property_search_location_matching_prefers_requested_districts() -> None:
    hints = _property_search_location_hints({"location_query": "1200 Vienna, 1020 Vienna, 1090"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=1",
        title="Wohnung in 1200 Wien mit Lift",
        summary="Nahe U6 und familienfreundlich.",
        property_facts={"postal_name": "1200 Wien"},
    ) is True
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=2",
        title="Wohnung in 1130 Wien",
        summary="Altbau",
        property_facts={"postal_name": "1130 Wien"},
    ) is False


def test_property_search_location_matching_rejects_unselected_vienna_districts() -> None:
    hints = _property_search_location_hints(
        {
            "location_query": (
                "1020 Vienna, 1070 Vienna, 1090 Vienna, 1100 Vienna, 1110 Vienna, "
                "1180 Vienna, 1200 Vienna, 1220 Vienna, Aspern"
            )
        }
    )

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1150-rudolfsheim-fuenfhaus/top-lage-naehe-westbahnhof",
        title="Top Lage Nähe Westbahnhof, 69 m², € 838,13, (1150 Wien) - willhaben",
        summary="Provider result page was queried from a selected Vienna source scope.",
        property_facts={"source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/familienwohnung",
        title="Helle Familienwohnung, 69 m², € 938,13, (1020 Wien) - willhaben",
        summary="Provider result page was queried from a selected Vienna source scope.",
        property_facts={"source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is True


def test_property_search_area_accepts_adjacent_districts_for_fuzzy_scope_only() -> None:
    strict_preferences = {
        "country_code": "AT",
        "region_code": "vienna",
        "location_query": "Wien",
        "selected_districts": ["1010 Vienna"],
    }
    fuzzy_preferences = {
        **strict_preferences,
        "adjacent_area_radius_m": 750,
    }
    hints = _property_search_location_hints(strict_preferences)

    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=strict_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/fuzzy-adjacent/",
        title="Wohnung mieten in 1020 Wien | 70 m² | 3 Zimmer",
        summary="Concrete listing evidence says Leopoldstadt.",
        property_facts={"postal_name": "1020 Wien"},
    ) is False
    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=fuzzy_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/fuzzy-adjacent/",
        title="Wohnung mieten in 1020 Wien | 70 m² | 3 Zimmer",
        summary="Concrete listing evidence says Leopoldstadt.",
        property_facts={"postal_name": "1020 Wien"},
    ) is True
    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=fuzzy_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
        title="Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer",
        summary="Concrete listing evidence says Donaustadt.",
        property_facts={"postal_name": "1220 Wien"},
    ) is False
    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=fuzzy_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/fuzzy-far/",
        title="Moderne Zwei-Zimmer Wohnung mit Terrasse in Salzburg",
        summary="Concrete listing evidence says Salzburg.",
        property_facts={"postal_name": "5020 Salzburg"},
    ) is False


def test_property_search_area_keeps_selected_district_scope_hard_without_radius() -> None:
    strict_preferences = {
        "country_code": "AT",
        "region_code": "vienna",
        "location_query": "Wien",
        "selected_districts": ["1010 Vienna"],
        "search_mode": "discovery",
    }
    hints = _property_search_location_hints(strict_preferences)

    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=strict_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/adjacent/",
        title="Wohnung mieten in 1020 Wien | 70 m² | 3 Zimmer",
        summary="Concrete listing evidence says Leopoldstadt.",
        property_facts={"postal_name": "1020 Wien"},
    ) is False
    assert product_service._property_candidate_matches_search_area(
        location_hints=hints,
        request_preferences=strict_preferences,
        source_spec={"country_code": "AT"},
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1220-donaustadt/neighbor/",
        title="Wohnung mieten in 1220 Wien | 62 m² | 2 Zimmer",
        summary="Concrete listing evidence says Donaustadt.",
        property_facts={"postal_name": "1220 Wien"},
    ) is False


def test_property_search_location_hints_prefer_selected_districts_over_broad_location_query() -> None:
    assert _property_search_location_hints(
        {
            "location_query": "Wien",
            "selected_districts": ["1010 Vienna"],
        }
    ) == ("1010 Vienna",)

    assert _property_search_location_hints(
        {
            "location_query": "Wien",
            "raw_preferences": {"selected_districts": ["1010 Vienna"]},
        }
    ) == ("1010 Vienna",)


def test_property_exact_source_scope_location_hints_only_use_postal_scopes() -> None:
    assert product_service._property_exact_source_scope_location_hints(
        source_label="Willhaben | Austria | Rent | 1010 Vienna",
    ) == ("1010 Vienna",)
    assert product_service._property_exact_source_scope_location_hints(
        source_label="Provider | Austria | Rent | 8055 Graz",
    ) == ("8055 Graz",)
    assert product_service._property_exact_source_scope_location_hints(
        source_label="Willhaben Vienna",
    ) == ()


def test_property_source_scope_location_extracts_all_postal_url_scopes_cleanly() -> None:
    assert product_service._property_search_source_scope_location(
        source_url="https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70",
        source_label="Raiffeisen WohnBau | Austria | Rent",
    ) == "1090 Vienna"
    assert product_service._property_search_source_scope_location(
        source_url="https://example.at/search/8055-graz/results",
        source_label="Provider | Austria | Rent",
    ) == "8055 Graz"
    assert product_service._property_search_source_scope_location(
        source_url="https://example.at/search/5020-salzburg/results",
        source_label="Provider | Austria | Rent",
    ) == "5020 Salzburg"
    assert product_service._property_search_source_scope_location(
        source_url="https://example.at/search/4780-schaerding/results",
        source_label="Provider | Austria | Rent",
    ) == "4780 Schaerding"
    assert product_service._property_search_source_scope_location(
        source_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/linz/demo-dirty-scope/",
        source_label="Willhaben | Austria | Rent | 8055 Graz",
    ) == "8055 Graz"


def test_property_exact_source_scope_hints_strip_url_path_tail_for_all_postals() -> None:
    assert product_service._property_exact_source_scope_location_hints(
        source_url="https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70",
        source_label="Raiffeisen WohnBau | Austria | Rent",
    ) == ("1090 Vienna",)
    assert product_service._property_exact_source_scope_location_hints(
        source_url="https://example.at/search/8055-graz/results",
        source_label="Provider | Austria | Rent",
    ) == ("8055 Graz",)


def test_property_search_location_matching_rejects_explicit_non_vienna_marker() -> None:
    hints = _property_search_location_hints({"location_query": "Vienna"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://example.test/listing/waidhofen",
        title="Altbau apartment in Waidhofen an der Ybbs",
        summary="Austria buy opportunity.",
        property_facts={"postal_name": "Waidhofen an der Ybbs"},
    ) is False


def test_property_investment_price_eur_parses_localized_thousand_separators() -> None:
    assert product_service._property_investment_price_eur({"price_display": "EUR 669.000,-"}) == 669000.0
    assert product_service._property_investment_price_eur({"price_display": "€ 1.250.000"}) == 1250000.0


def test_property_investment_underwriting_display_uses_listing_currency() -> None:
    payload = product_service._property_investment_underwriting_payload(
        title="Two bedroom flat",
        summary="Investment candidate.",
        facts={"country_code": "GB", "currency_code": "GBP", "area_sqm": 80, "price_display": "GBP 420000"},
        preferences={},
        snapshot={
            "gross_yield_pct": 4.8,
            "expected_monthly_rent_eur": 1650,
            "current_price_per_sqm_eur": 5250,
            "market_buy_per_sqm_eur": 5400,
            "market_rent_per_sqm_eur": 22.25,
        },
    )

    assert payload["expected_rent_display"] == "Rent model about GBP 1 650/mo"
    assert payload["price_per_sqm"] == "Buy side about GBP 5 250/m2"
    assert payload["market_buy_per_sqm_display"] == "Local buy median about GBP 5 400/m2"
    assert payload["market_rent_per_sqm_display"] == "Local rent median about GBP 22.25/m2"
    assert "EUR" not in " ".join(
        str(payload.get(key) or "")
        for key in (
            "expected_rent_display",
            "price_per_sqm",
            "market_buy_per_sqm_display",
            "market_rent_per_sqm_display",
        )
    )


def test_property_listing_mode_mismatch_uses_transaction_text_not_parser_price_field() -> None:
    enriched_rent_mode = product_service._property_enrich_facts_from_listing_text(
        facts={"property_type": "apartment", "postal_name": "1010 Wien"},
        title="Eigentumswohnung in 1010 Wien | 77 m² | € 669.000",
        summary="Kaufpreis laut Expose.",
        listing_mode="rent",
    )

    assert enriched_rent_mode.get("total_rent_eur") == 669000.0
    assert product_service._property_candidate_listing_mode_mismatch(
        listing_mode="rent",
        property_url="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/wien/wien-1010-innere-stadt/example/",
        title="Eigentumswohnung in 1010 Wien | 77 m² | € 669.000",
        summary="Kaufpreis laut Expose.",
        property_facts=enriched_rent_mode,
    ) is True
    assert product_service._property_candidate_listing_mode_mismatch(
        listing_mode="buy",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/example/",
        title="Mietwohnung in 1010 Wien | 77 m² | € 1.598",
        summary="Gesamtmiete laut Expose.",
        property_facts={"property_type": "apartment", "price_eur": 1598.0, "postal_name": "1010 Wien"},
    ) is True


def test_property_listing_mode_mismatch_treats_generic_price_as_neutral_for_rent_preview() -> None:
    assert product_service._property_candidate_listing_mode_mismatch(
        listing_mode="rent",
        property_url="https://www.willhaben.at/iad/object?adId=1775972917",
        title="All-inclusive living, Balkon, U-Bahn, Lift vorhanden",
        summary="",
        property_facts={"property_type": "apartment", "price_display": "€ 1.017,09", "postal_name": "1010 Vienna"},
    ) is False

    assert product_service._property_candidate_listing_mode_mismatch(
        listing_mode="rent",
        property_url="https://www.willhaben.at/iad/object?adId=1775972917",
        title="Eigentumswohnung mit Balkon",
        summary="",
        property_facts={"property_type": "apartment", "price_display": "€ 669.000", "postal_name": "1010 Vienna"},
    ) is True


def test_property_search_location_matching_rejects_source_scope_only_for_exact_postal_scope() -> None:
    hints = _property_search_location_hints({"location_query": "1200 Vienna, 1020 Vienna, 1090"})
    facts = product_service._property_facts_with_source_scope(
        facts={"street_address": "Rotensterngasse 21", "provider_channel": "justiz_edikte_at"},
        source_url=(
            "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/suchedi?"
            "retfields=%5BVPLZ%5D=1020;%5BVOrt%5D=Wien"
        ),
        source_label="Justiz Edikte Auctions | Austria | Buy | 1020 Vienna",
    )

    assert facts["source_scope_location"] == "1020 Vienna"
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        title="BG Leopoldstadt, 082 25 E 89/25g",
        summary="Sparse judicial auction detail page.",
        property_facts=facts,
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example-1020-wien!OpenDocument",
        title="BG Leopoldstadt, 1020 Wien, 082 25 E 89/25g",
        summary="Sparse judicial auction detail page.",
        property_facts=facts,
    ) is True


def test_property_provider_greenfield_api_returns_country_scoped_catalog_with_austria_and_cr_regression_coverage() -> None:
    client = build_property_client(principal_id="exec-provider-catalog-germany")
    de_body = client.get("/app/api/property/providers?country=DE").json()

    assert any(row["value"] == "core_portals_de" and row["family"] == "core_portal" for row in de_body["providers"])
    assert any(row["value"] == "shared_housing_de" and row["family"] == "shared_housing" for row in de_body["providers"])
    assert any(row["value"] == "corporate_landlords_de" and row["family"] == "corporate_landlord" for row in de_body["providers"])
    assert any(row["value"] == "municipal_housing_de" and row["family"] == "municipal_housing" for row in de_body["providers"])
    assert any(row["value"] == "immoscout_de" for row in de_body["providers"])
    assert any(row["value"] == "wg_gesucht_de" and row["family"] == "shared_housing" for row in de_body["providers"])
    assert any(row["value"] == "vonovia_de" and row["family"] == "corporate_landlord" for row in de_body["providers"])
    assert any(row["value"] == "neubaukompass_de" and row["family"] == "developer_projects" for row in de_body["providers"])
    assert any(row["value"] == "auctions_de" and row["family"] == "distressed_sales" for row in de_body["providers"])
    assert any(row["value"] == "broker_direct_de" and row["family"] == "broker_direct" for row in de_body["providers"])
    assert any(row["value"] == "furnished_relocation_de" and row["family"] == "furnished_relocation" for row in de_body["providers"])
    assert any(row["value"] == "ohne_makler_de" and row["family"] == "broker_direct" for row in de_body["providers"])
    assert any(row["value"] == "von_poll_de" and row["family"] == "broker_direct" for row in de_body["providers"])

    at_body = client.get("/app/api/property/providers?country=AT").json()

    assert any(row["value"] == "public_housing_at" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "genossenschaften_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "wohnberatung_wien" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "wiener_wohnen" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "gesiba_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "oesw_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "egw_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "zvginfo_at" and row["family"] == "distressed_sales" for row in at_body["providers"])
    assert any(row["value"] == "school_directories_de" for row in de_body["evidence_sources"])
    assert any(row["value"] == "statatlas_schulen_at" for row in at_body["evidence_sources"])


def test_property_provider_greenfield_api_returns_mode_aware_default_platforms() -> None:
    client = build_property_client(principal_id="exec-provider-catalog-mode-aware")

    at_buy_body = client.get(
        "/app/api/property/providers",
        params={"country": "AT", "listing_mode": "buy", "property_type": "apartment"},
    ).json()
    at_land_body = client.get(
        "/app/api/property/providers",
        params={"country": "AT", "listing_mode": "buy", "property_type": "land"},
    ).json()
    de_buy_body = client.get(
        "/app/api/property/providers",
        params={"country": "DE", "listing_mode": "buy", "property_type": "apartment"},
    ).json()

    assert at_buy_body["listing_mode"] == "buy"
    assert at_buy_body["property_type"] == "apartment"
    assert at_buy_body["default_platforms"] == [
        "willhaben",
        "immmo",
        "immoscout_at",
        "derstandard_at",
        "broker_direct_at",
        "developer_projects_at",
    ]
    assert at_land_body["default_platforms"] == [
        "willhaben",
        "immmo",
        "immoscout_at",
        "broker_direct_at",
    ]
    assert de_buy_body["default_platforms"] == [
        "core_portals_de",
        "new_build_de",
        "broker_direct_de",
    ]


def test_austria_generated_source_defaults_use_public_and_cooperative_lanes_for_rent() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Vienna",
        },
        selected_platforms=(),
        principal_id="exec-property-at-rent-defaults",
        default_person_id="self",
        max_results=4,
    )

    platforms = {str(row["platform"]) for row in specs}

    assert "public_housing_at" in platforms
    assert "genossenschaften_at" in platforms


def test_generated_source_specs_use_selected_districts_over_broad_location_query() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "1010 Vienna, 1020 Vienna, 1090 Vienna, 1190 Vienna, 1200 Vienna, 1220 Vienna",
            "selected_districts": ["1010 Vienna"],
            "property_type": ["apartment"],
            "max_price_eur": 1000,
            "min_rooms": 2,
            "min_area_m2": 60,
        },
        selected_platforms=("willhaben",),
        principal_id="exec-property-selected-district-source-scope",
        default_person_id="self",
        max_results=4,
    )

    labels = [str(row.get("label") or "") for row in specs]
    urls = [str(row.get("url") or "") for row in specs]
    assert labels == ["Willhaben | Austria | Rent | 1010 Vienna"]
    assert len(urls) == 1
    assert "q=1010+Vienna" in urls[0]
    assert "1020" not in urls[0]
    assert specs[0]["provider_filter_pushdown"]["applied"]["location_query"] == "1010 Vienna"


def test_generated_source_specs_skip_region_incompatible_austria_grouped_sources() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "property_type": ["apartment"],
            "min_area_m2": 60,
        },
        selected_platforms=("genossenschaften_at", "salzburg_wohnbau_at", "ooe_wohnbau_at", "wag_at"),
        principal_id="exec-property-region-compatible-source-scope",
        default_person_id="self",
        max_results=4,
    )

    labels = [str(row.get("label") or "") for row in specs]
    joined = "\n".join(labels)
    assert labels
    assert all("1010 Vienna" in label for label in labels)
    assert "Salzburg Wohnbau" not in joined
    assert "OÖ Wohnbau" not in joined
    assert "WAG Wohngebiete" not in joined


def test_austria_generated_source_defaults_use_broker_and_project_lanes_for_buy() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Vienna",
        },
        selected_platforms=(),
        principal_id="exec-property-at-buy-defaults",
        default_person_id="self",
        max_results=4,
    )

    platforms = {str(row["platform"]) for row in specs}

    assert "broker_direct_at" in platforms
    assert "developer_projects_at" in platforms


def test_germany_generated_source_defaults_use_live_buy_lanes_only() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Berlin",
        },
        selected_platforms=(),
        principal_id="exec-property-de-buy-defaults",
        default_person_id="self",
        max_results=4,
    )

    platforms = {str(row["platform"]) for row in specs}
    urls = [str(row["url"]) for row in specs]

    assert "core_portals_de" in platforms
    assert "new_build_de" in platforms
    assert "broker_direct_de" in platforms
    assert "corporate_landlords_de" not in platforms
    assert any("ohne-makler.net/immobilien/berlin/berlin/" in url for url in urls)
    assert any("neubaukompass.com/new-build-real-estate/berlin/" in url for url in urls)


def test_germany_auction_sources_require_buy_or_explicit_distressed_signal_mode() -> None:
    rent_specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Berlin",
        },
        selected_platforms=("auctions_de", "zvg_de"),
        principal_id="exec-property-de-auctions-rent",
        default_person_id="self",
        max_results=3,
    )
    distressed_specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Berlin",
            "include_distressed_sale_signals": True,
        },
        selected_platforms=("auctions_de",),
        principal_id="exec-property-de-auctions-distressed",
        default_person_id="self",
        max_results=3,
    )

    assert rent_specs == ()
    assert distressed_specs
    assert all(str(row["listing_mode"]) == "buy" for row in distressed_specs)


def test_property_search_location_matching_rejects_source_scope_only_location() -> None:
    hints = _property_search_location_hints({"country_code": "CR", "region_code": "puntarenas", "location_query": "Monteverde"})
    facts = product_service._property_facts_with_source_scope(
        facts={"provider_channel": "re_cr_mls"},
        source_url="https://re.cr/en/search?country=CR&q=Monteverde",
        source_label="RE.cr Costa Rica MLS | Costa Rica | Buy | Monteverde",
    )

    assert facts["source_scope_location"] == "Monteverde"
    assert facts["source_city"] == "Monteverde"
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://re.cr/en/listing/sparse-card",
        title="Mountain view home",
        summary="Sparse provider card.",
        property_facts=facts,
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://re.cr/en/listing/monteverde-home",
        title="Mountain view home in Monteverde",
        summary="Sparse provider card with concrete listing locality in Monteverde.",
        property_facts=facts,
        country_code="CR",
        region_code="puntarenas",
    ) is True


def test_property_search_location_matching_rejects_concrete_cr_location_conflict() -> None:
    hints = _property_search_location_hints({"country_code": "CR", "region_code": "puntarenas", "location_query": "Monteverde"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.re.cr/en/real-estate/heredia-costa-rica",
        title="Properties for sale and for rent in Heredia, Costa Rica",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.realtor.com/international/cr/limon-talamanca-puerto-viejo-limon-310108049873/",
        title="Limón Talamanca Puerto Viejo, Limon 70403 Apartment for Sale",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.re.cr/en/real-estate/lake-arenal",
        title="Lake Arenal Real Estate",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.realtor.com/international/cr/bella-vista-nuevo-arenal-lake-arenal-guanacaste-310101836907/",
        title="Bella Vista Nuevo Arenal Lake Arenal Guanacaste House for Sale",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False


def test_property_search_location_matching_rejects_source_scope_postal_conflict() -> None:
    hints = _property_search_location_hints({"location_query": "1020 Vienna, 1030 Vienna, Wien"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=2098041582",
        title="Neubau 2 Zimmer Traum mit Balkon, 51,81 m², € 1.099,-, (3400 Klosterneuburg)",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://propertyquarry.com/tours/gefrderte-2-zimmer-mietwohnung-mit-balkon-und-carport-in-jagerberg-layout-first-828b943ae4",
        title="Geförderte 2 Zimmer Mietwohnung mit Balkon und Carport in Jagerberg",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "8091 Jagerberg", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/oberoesterreich/gmunden/wohnung-mit-seeblick",
        title="Wohnung mit Seeblick in Gmunden",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "4810 Gmunden", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/einfamilienhaus/niederoesterreich/hollabrunn/familienhaus",
        title="Familienhaus in Hollabrunn",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "2020 Hollabrunn", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-4020-linz",
        title="Wohnung mieten in 4020 Linz | 48.38 m² | 2 Zimmer",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "4020 Linz", "source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.immobilienscout24.at/expose/natters-top-05",
        title="Wohnhausanlage Osteräcker 01 - Natters | TOP 05",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "6161 Natters", "source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False


def test_property_search_location_matching_rejects_non_vienna_title_even_with_vienna_source_scope() -> None:
    hints = _property_search_location_hints({"location_query": "Wien"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/gmunden/seeblick",
        title="Moderne Wohnung mit Seeblick in Gmunden",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/haus/niederoesterreich/hollabrunn/familienhaus",
        title="Familienhaus in Hollabrunn mit Garten",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False


def test_property_search_location_matching_rejects_catalog_alias_conflict_before_source_scope() -> None:
    hints = _property_search_location_hints(
        {
            "country_code": "AT",
            "region_code": "vienna",
            "location_query": "1010 Vienna",
        }
    )

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://familienwohnbau.at/wohnen-naehe-u4-huetteldorf",
        title="WOHNEN NÄHE U4 HÜTTELDORF | Familienwohnbau",
        summary="Provider result page was queried from a selected 1010 source scope.",
        property_facts={
            "source_scope_location": "1010 Vienna",
            "source_city": "Vienna",
            "country_code": "AT",
            "region_code": "vienna",
        },
        country_code="AT",
        region_code="vienna",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://example.test/1010-inner-city",
        title="Innere Stadt apartment, 1010 Wien",
        summary="Sparse provider card.",
        property_facts={
            "source_scope_location": "1010 Vienna",
            "source_city": "Vienna",
            "country_code": "AT",
            "region_code": "vienna",
        },
        country_code="AT",
        region_code="vienna",
    ) is True


def test_property_search_location_hints_ignore_broad_austria_scope() -> None:
    assert _property_search_location_hints({"location_query": "Österreich"}) == ()
    assert _property_search_location_hints({"location_query": "All Austria"}) == ()
    assert _property_search_location_hints({"location_query": "Niederösterreich"}) == ("Niederösterreich",)


def test_property_distance_gate_records_relaxed_and_unknown_distances() -> None:
    relaxed_facts = {"nearest_supermarket_m": 420}

    assert product_service._property_apply_distance_gate(
        relaxed_facts,
        request_preferences={
            "max_distance_to_supermarket_m": 200,
            "max_distance_to_supermarket_importance": "important",
        },
        preference_key="max_distance_to_supermarket_m",
        fact_key="nearest_supermarket_m",
        label="supermarket",
    ) is True
    assert relaxed_facts["distance_relaxations_json"] == [
        {"label": "supermarket", "requested_m": 200, "actual_m": 420}
    ]

    unknown_facts: dict[str, object] = {}
    assert product_service._property_apply_distance_gate(
        unknown_facts,
        request_preferences={
            "max_distance_to_playground_m": 300,
            "max_distance_to_playground_importance": "must_have",
        },
        preference_key="max_distance_to_playground_m",
        fact_key="nearest_playground_m",
        label="playground",
    ) is True
    assert unknown_facts["distance_unknowns_json"] == [
        {"label": "playground", "requested_m": 300}
    ]

    outside_facts = {"nearest_library_m": 1200}
    assert product_service._property_apply_distance_gate(
        outside_facts,
        request_preferences={
            "max_distance_to_library_m": 300,
            "max_distance_to_library_importance": "must_have",
        },
        preference_key="max_distance_to_library_m",
        fact_key="nearest_library_m",
        label="Library",
    ) is False
    assert "distance_relaxations_json" not in outside_facts


def test_property_distance_gate_treats_non_hard_preferences_as_score_only() -> None:
    outside_facts = {"nearest_library_m": 1200}
    assert product_service._property_apply_distance_gate(
        outside_facts,
        request_preferences={
            "max_distance_to_library_m": 300,
            "max_distance_to_library_importance": "important",
        },
        preference_key="max_distance_to_library_m",
        fact_key="nearest_library_m",
        label="Library",
    ) is True
    assert "distance_relaxations_json" not in outside_facts

    soft_unknown_facts: dict[str, object] = {}
    assert product_service._property_apply_distance_gate(
        soft_unknown_facts,
        request_preferences={
            "max_distance_to_playground_m": 500,
            "max_distance_to_playground_importance": "nice_to_have",
        },
        preference_key="max_distance_to_playground_m",
        fact_key="nearest_playground_m",
        label="playground",
    ) is True
    assert soft_unknown_facts["distance_unknowns_json"] == [
        {"label": "playground", "requested_m": 500}
    ]


def test_property_distance_preference_score_adjustment_rewards_and_penalizes_soft_matches() -> None:
    positive_adjustment, positive_notes = product_service._property_distance_preference_score_adjustment(
        preferences={
            "max_distance_to_library_m": 500,
            "max_distance_to_library_importance": "important",
            "max_distance_to_playground_m": 800,
            "max_distance_to_playground_importance": "nice_to_have",
        },
        property_facts={
            "nearest_library_m": 240,
            "nearest_playground_m": 620,
        },
    )

    assert positive_adjustment > 0
    assert "library close by" in positive_notes
    assert "playground nearby" in positive_notes

    negative_adjustment, negative_notes = product_service._property_distance_preference_score_adjustment(
        preferences={
            "max_distance_to_library_m": 400,
            "max_distance_to_library_importance": "important",
            "max_distance_to_playground_m": 500,
            "max_distance_to_playground_importance": "nice_to_have",
        },
        property_facts={
            "nearest_library_m": 1800,
        },
    )

    assert negative_adjustment < 0
    assert "library farther away than wished" in negative_notes
    assert "playground distance missing" in negative_notes

    avoid_adjustment, avoid_notes = product_service._property_distance_preference_score_adjustment(
        preferences={
            "max_distance_to_shopping_center_m": 500,
            "max_distance_to_shopping_center_importance": "avoid",
            "max_distance_to_theatre_m": 700,
            "max_distance_to_theatre_importance": "strong_wish",
        },
        property_facts={
            "nearest_shopping_center_m": 220,
            "nearest_theatre_m": 360,
        },
    )

    assert avoid_adjustment == 0
    assert "shopping center too close for avoid preference" in avoid_notes
    assert "theatre close by" in avoid_notes


def test_property_candidate_effective_fit_score_prefers_adjusted_rank_score() -> None:
    assert (
        product_service._property_candidate_effective_fit_score(
            assessment_fit_score=38,
            ranked_fit_score=51,
        )
        == 51.0
    )
    assert (
        product_service._property_candidate_effective_fit_score(
            assessment_fit_score=62,
            ranked_fit_score=51,
        )
        == 62.0
    )


def test_property_distance_gate_can_avoid_nearby_locations() -> None:
    too_close_facts = {"nearest_shopping_center_m": 220}
    assert product_service._property_apply_distance_gate(
        too_close_facts,
        request_preferences={
            "max_distance_to_shopping_center_m": 500,
            "max_distance_to_shopping_center_importance": "avoid_nearby",
        },
        preference_key="max_distance_to_shopping_center_m",
        fact_key="nearest_shopping_center_m",
        label="shopping center",
    ) is True
    assert too_close_facts["distance_avoidances_json"] == [
        {"label": "shopping center", "requested_m": 500, "actual_m": 220}
    ]

    far_enough_facts = {"nearest_shopping_center_m": 1400}
    assert product_service._property_apply_distance_gate(
        far_enough_facts,
        request_preferences={
            "max_distance_to_shopping_center_m": 500,
            "max_distance_to_shopping_center_importance": "avoid_nearby",
        },
        preference_key="max_distance_to_shopping_center_m",
        fact_key="nearest_shopping_center_m",
        label="shopping center",
    ) is True


def test_property_search_prefetch_listing_urls_records_timings_and_errors(monkeypatch) -> None:
    def _fake_listing_urls_for_source(*, source_url: str, source_spec: dict[str, object], force_refresh: bool):
        if source_spec.get("platform") == "bad":
            raise RuntimeError("fetch_failed")
        return (("https://example.com/listing-1",), {"status": "miss"})

    monkeypatch.setattr(product_service, "_property_scout_listing_urls_for_source", _fake_listing_urls_for_source)

    prefetched = product_service._property_search_prefetch_listing_urls(
        specs=[
            {"url": "https://example.com/good", "platform": "good", "provider_family": "core_portal"},
            {"url": "https://example.com/bad", "platform": "bad", "provider_family": "core_portal"},
        ],
        force_refresh=False,
    )

    good = prefetched[("good", "https://example.com/good")]
    bad = prefetched[("bad", "https://example.com/bad")]
    assert good["listing_urls"] == ("https://example.com/listing-1",)
    assert good["provider_cache_state"]["status"] == "miss"
    assert float(good["timing_ms"]["provider_fetch"]) >= 0.0
    assert bad["error"] == "fetch_failed"
    assert float(bad["timing_ms"]["provider_fetch"]) >= 0.0


def test_property_filter_feedback_patch_disables_filter_and_reruns_search(monkeypatch) -> None:
    principal_id = "exec-property-filter-feedback-patch"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Feedback Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "max_distance_to_supermarket_m": 200,
            "max_distance_to_supermarket_importance": "important",
            "property_search_enabled": True,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    prompt = service._prepare_notification_feedback_prompt(
        principal_id=principal_id,
        notification_kind="property_scout_filter_near_miss",
        person_id="self",
        domain="property_search",
        object_type="property_listing",
        object_id="https://www.willhaben.at/iad/object?adId=near-miss",
        source_ref="property-scout:near-miss",
        raw_signal_json={"failed_filter_key": "max_distance_to_supermarket_m"},
        interpreted_signal_json={},
        suggestion_options=[
            {
                "key": "disable_max_distance_to_supermarket_m",
                "label": "Disable supermarket radius",
                "event_type": "property_filter_disable_requested",
                "reply_text": "Noted. I disabled that one search filter and started a fresh search.",
                "property_search_preference_patch": {"max_distance_to_supermarket_m": None},
                "property_search_rerun": True,
            }
        ],
    )
    service._record_notification_feedback_prompt(
        principal_id=principal_id,
        prompt=prompt,
        delivery_channel="telegram",
        telegram_chat_ref="42",
        telegram_message_ids=["77"],
    )
    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["principal_id"] = principal_id
        observed["actor"] = actor
        observed["force_refresh"] = force_refresh
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {"status": "processed", "listing_total": 2}

    monkeypatch.setattr(service, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    result = service.record_notification_feedback(
        principal_id=principal_id,
        notification_key=str(prompt["notification_key"]),
        feedback_key="disable_max_distance_to_supermarket_m",
        actor="telegram_test",
        chat_id="42",
    )

    assert result["status"] == "recorded"
    assert result["property_search_preference_patch_status"] == "patched"
    assert result["property_search_rerun_status"] == "processed"
    assert observed["principal_id"] == principal_id
    assert observed["actor"] == "telegram_filter_feedback"
    assert observed["force_refresh"] is True
    updated = client.app.state.container.onboarding.status(principal_id=principal_id)["property_search_preferences"]
    raw = updated["raw_preferences"]
    assert raw["max_distance_to_supermarket_m"] is None
    assert raw["max_distance_to_supermarket_importance"] == "nice_to_have"


def test_property_filter_feedback_patch_ignores_unsupported_keys() -> None:
    principal_id = "exec-property-filter-feedback-unsupported"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Unsupported Office")
    service = ProductService(client.app.state.container)

    result = service._apply_property_search_feedback_patch(
        principal_id=principal_id,
        patch={"selected_platforms": [], "max_distance_to_playground_m": None},
    )

    assert result["status"] == "patched"
    assert result["patched_keys"] == ["max_distance_to_playground_m"]
    updated = client.app.state.container.onboarding.status(principal_id=principal_id)["property_search_preferences"]
    assert updated["raw_preferences"]["max_distance_to_playground_m"] is None
    assert "selected_platforms" in updated["raw_preferences"]


def test_property_filter_near_miss_feedback_buttons_fit_telegram_callback_limit(monkeypatch) -> None:
    principal_id = "exec-property-filter-near-miss-buttons"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Button Office")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    service = ProductService(client.app.state.container)
    sent: dict[str, object] = {}

    def _fake_send_telegram_message_for_principal(*args, **kwargs):
        sent.update(kwargs)
        return SimpleNamespace(chat_id="1354554303", message_ids=("7",))

    monkeypatch.setattr(product_service, "send_telegram_message_for_principal", _fake_send_telegram_message_for_principal)

    result = service._send_property_scout_filter_near_miss_telegram(
        principal_id=principal_id,
        actor="test",
        title="Near miss apartment",
        summary="Strong candidate",
        counterparty="Willhaben",
        property_url="https://www.willhaben.at/iad/object?adId=near-miss",
        source_ref="property-scout:near-miss",
        preference_person_id="self",
        failed_filter_key="max_distance_to_supermarket_m",
        failed_filter_label="supermarket radius",
        prefilter_score=86.0,
    )

    assert result["status"] == "sent"
    inline_buttons = list(sent["inline_buttons"])
    callback_values = [
        str(callback_data)
        for row in inline_buttons
        for _label, callback_data in row
    ]
    assert callback_values
    assert all(len(value.encode("utf-8")) <= 64 for value in callback_values)
    assert any("|df_super|" in value for value in callback_values)
    assert any("|kf_super|" in value for value in callback_values)


def test_property_filter_near_miss_sender_suppresses_location_conflicts(monkeypatch) -> None:
    principal_id = "exec-property-filter-near-miss-location-sender"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Location Gate Office")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("7",)),
    )

    result = service._send_property_scout_filter_near_miss_telegram(
        principal_id=principal_id,
        actor="test",
        title="Wohnung mieten in 4020 Linz | 48.38 m2 | 2 Zimmer",
        summary="Outside Vienna.",
        counterparty="DER STANDARD Immobilien | Austria | Buy | 1020 Vienna",
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-4020-linz",
        source_ref="property-scout:linz-near-miss",
        preference_person_id="self",
        failed_filter_key="min_area_m2",
        failed_filter_label="minimum area",
        prefilter_score=86.0,
        requested_location_hints=("1020 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []


def test_property_scout_hit_sender_suppresses_location_conflicts_and_opens_repair(monkeypatch) -> None:
    principal_id = "exec-property-hit-location-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Scout Hit Location Gate Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("7",)),
    )

    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title="WOHNEN NÄHE U4 HÜTTELDORF | Familienwohnbau",
        summary="Generic project page surfaced from a 1010 scope.",
        counterparty="Genossenschaften | Austria | Rent | 1010 Vienna | Familienwohnbau Angebote",
        account_email="",
        property_url="https://example.invalid/angebote/huetteldorf",
        source_ref="property-scout:huetteldorf-mismatch",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        fit_score=50.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://example.invalid/angebote/huetteldorf",
                "listing_title": "WOHNEN NÄHE U4 HÜTTELDORF | Familienwohnbau",
                "summary": "Scout update candidate",
                "source_platform": "genossenschaften",
                "source_family": "housing_coop",
                "property_facts_json": {
                    "postal_name": "1140 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "district": "Hütteldorf",
                },
            },
        ),
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert repair_tasks[0].priority == "urgent"
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "location_scope"
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"
    assert repair_tasks[0].status in {"pending", "returned"}


def test_property_scout_hit_sender_suppresses_low_score_direct_calls(monkeypatch) -> None:
    principal_id = "exec-property-hit-low-score-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Scout Low Score Gate Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    monkeypatch.setenv("PROPERTYQUARRY_SCOUT_OUTBOUND_MIN_SCORE", "60")
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("low-score scout hit must not notify")),
    )

    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title="Wohnung mieten in 1010 Wien | 60 m² | 2 Zimmer | EUR 1.090",
        summary="2-Zimmer Wohnung im 1. Bezirk, 60 m2, Gesamtmiete EUR 1.090.",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/low-score/",
        source_ref="property-scout:low-score-1010",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        fit_score=50.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/low-score/",
                "listing_title": "Wohnung mieten in 1010 Wien | 60 m² | 2 Zimmer | EUR 1.090",
                "summary": "2-Zimmer Wohnung im 1. Bezirk, 60 m2, Gesamtmiete EUR 1.090.",
                "source_platform": "willhaben",
                "source_family": "marketplace",
                "property_facts_json": {
                    "postal_name": "1010 Wien",
                    "location": "1010 Wien, Innere Stadt",
                    "street_address": "Kärntner Straße 12, 1010 Wien",
                    "exact_address": "Kärntner Straße 12, 1010 Wien",
                    "area_sqm": 60,
                    "rooms": 2,
                    "total_rent_eur": 1090,
                },
            },
        ),
        render_dossier=False,
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "fit_below_outbound_threshold"
    assert result["fit_score"] == 50.0
    assert result["min_score"] == 60.0
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks == []


def test_property_scout_outbound_min_score_env_cannot_lower_sixty_floor(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_SCOUT_OUTBOUND_MIN_SCORE", "50")

    assert product_service._property_scout_outbound_notification_min_score() == 60.0

    monkeypatch.setenv("PROPERTYQUARRY_SCOUT_OUTBOUND_MIN_SCORE", "72")

    assert product_service._property_scout_outbound_notification_min_score() == 72.0


def test_property_source_scope_placeholder_detection_keeps_street_addresses_concrete() -> None:
    facts = {
        "postal_name": "1010 Wien",
        "location": "1010 Wien, Innere Stadt",
        "street_address": "Kärntner Straße 12, 1010 Wien",
        "exact_address": "Kärntner Straße 12, 1010 Wien",
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
    }

    assert product_service._property_candidate_has_concrete_location(facts)


def test_property_location_match_uses_listing_postal_evidence_over_source_scope() -> None:
    dirty_scope_facts = {
        "postal_name": "1010 Vienna",
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
    }
    title = "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD"
    summary = "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien."

    enriched = product_service._property_enrich_facts_from_listing_text(
        facts=dirty_scope_facts,
        title=title,
        summary=summary,
        listing_mode="rent",
    )

    assert enriched["postal_name"] == "1220 Wien"
    assert [row["postal_code"] for row in enriched["listing_postal_evidence"]] == ["1220"]
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url="https://www.derstandard.at/immobilien/wohnung-1220-wien",
        title=title,
        summary=summary,
        property_facts=dirty_scope_facts,
        country_code="AT",
        region_code="vienna",
    )
    assert _property_candidate_matches_requested_location(
        location_hints=("1220 Vienna",),
        property_url="https://www.derstandard.at/immobilien/wohnung-1220-wien",
        title=title,
        summary=summary,
        property_facts=dirty_scope_facts,
        country_code="AT",
        region_code="vienna",
    )


def test_property_location_match_uses_url_slug_postal_evidence_over_source_scope() -> None:
    dirty_scope_facts = {
        "postal_name": "1010 Vienna",
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
    }

    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url="https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70?quot%3B%2Fn=",
        title="Augasse 17",
        summary="Provider card was returned from a selected 1010 source scope.",
        property_facts=dirty_scope_facts,
        country_code="AT",
        region_code="vienna",
    )
    assert _property_candidate_matches_requested_location(
        location_hints=("1090 Vienna",),
        property_url="https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70?quot%3B%2Fn=",
        title="Augasse 17",
        summary="Provider card was returned from a selected 1090 source scope.",
        property_facts=dirty_scope_facts,
        country_code="AT",
        region_code="vienna",
    )

    assert not _property_candidate_matches_requested_location(
        location_hints=("90210 Beverly Hills",),
        property_url="https://example.test/apartment-10001-new-york",
        title="Apartment in 10001 New York | 70 m2 | USD 3,200",
        summary="Sunny apartment in 10001 New York.",
        property_facts={
            "postal_name": "90210 Beverly Hills",
            "source_scope_location": "90210 Beverly Hills",
            "source_postal_code": "90210",
            "source_city": "Beverly Hills",
        },
        country_code="US",
        region_code="ny",
    )
    assert _property_candidate_matches_requested_location(
        location_hints=("10001 New York",),
        property_url="https://example.test/apartment-10001-new-york",
        title="Apartment in 10001 New York | 70 m2 | USD 3,200",
        summary="Sunny apartment in 10001 New York.",
        property_facts={},
        country_code="US",
        region_code="ny",
    )


def test_property_postal_extraction_ignores_source_scope_locality_noise() -> None:
    assert product_service._property_postal_location_evidence("selected 1010 source scope") == ()
    assert product_service._property_postal_location_evidence("requested 1010 search area") == ()


def test_property_notification_location_evidence_kind_never_treats_source_scope_as_listing_truth() -> None:
    source_scope_facts = {
        "postal_name": "1010 Vienna",
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
    }

    source_scope_only = product_service._property_candidate_notification_location_evidence_kind(
        property_url="https://www.willhaben.at/iad/object?adId=1631373932",
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung",
        summary="Provider card from selected search scope.",
        property_facts=source_scope_facts,
    )
    assert source_scope_only == "source_scope_only"
    assert not product_service._property_candidate_notification_location_evidence_is_concrete(source_scope_only)

    listing_postal = product_service._property_candidate_notification_location_evidence_kind(
        property_url="https://www.derstandard.at/immobilien/wohnung-1220-wien",
        title="Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer",
        summary="2-Zimmer Wohnung mit Traumblick in 1220 Wien.",
        property_facts=source_scope_facts,
    )
    assert listing_postal == "listing_postal"
    assert product_service._property_candidate_notification_location_evidence_is_concrete(listing_postal)

    url_postal = product_service._property_candidate_notification_location_evidence_kind(
        property_url="https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70",
        title="Augasse 17",
        summary="Provider card from selected search scope.",
        property_facts=source_scope_facts,
    )
    assert url_postal == "url_postal"
    assert product_service._property_candidate_notification_location_evidence_is_concrete(url_postal)

    street_address = product_service._property_candidate_notification_location_evidence_kind(
        property_url="https://example.test/listing",
        title="Wohnung beim Stephansplatz",
        summary="2-Zimmer Wohnung.",
        property_facts={**source_scope_facts, "street_address": "Kärntner Straße 12, 1010 Wien"},
    )
    assert street_address == "listing_concrete"
    assert product_service._property_candidate_notification_location_evidence_is_concrete(street_address)

    url_region = product_service._property_candidate_notification_location_evidence_kind(
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung",
        summary="Provider card from selected search scope.",
        property_facts=source_scope_facts,
    )
    assert url_region == "url_region"
    assert not product_service._property_candidate_notification_location_evidence_is_concrete(url_region)


def test_property_objective_review_boost_ignores_source_scope_location_without_listing_location() -> None:
    source_scope_only = product_service._property_scout_objective_review_boost(
        property_url="https://example.invalid/listing-with-source-scope-only",
        preview={"property_facts_json": {"source_scope_location": "1010 Vienna", "source_city": "Vienna"}},
    )
    listing_location = product_service._property_scout_objective_review_boost(
        property_url="https://example.invalid/listing-with-postal-name",
        preview={"property_facts_json": {"postal_name": "1010 Wien"}},
    )

    assert source_scope_only == 0.0
    assert listing_location == 2.0


@pytest.mark.parametrize(
    ("title", "summary", "property_url", "expected_postal"),
    [
        (
            "Wohnung mieten in 1200 Wien, Brigittenau | 81.98 m² | 3 Zimmer | € 1.649",
            "Stilvolle 3-Zimmer-Wohnung mit Garten & Terrasse im 20. Bezirk, Miete €1.649,- in 1200 Wien.",
            "https://immobilien.derstandard.at/detail/wohnung-mieten-in-1200-wien-brigittenau",
            "1200",
        ),
        (
            "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD",
            "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
            "https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
            "1220",
        ),
        (
            "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich",
            "Moderne Zwei-Zimmer Wohnung mit Terrasse in Salzburg.",
            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo",
            "",
        ),
        (
            "Einziehen sorgenfrei starten - Ihre Traumwohnung mit Balkon",
            "Unbefristeter Vertrag ab sofort verfügbar in Schärding.",
            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/schaerding/demo",
            "",
        ),
        (
            "Traumwohnung mit Balkon in Schärding | 84 m² | 3 Zimmer",
            "Sofort verfügbare Mietwohnung in 4780 Schärding.",
            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/schaerding/demo",
            "4780",
        ),
    ],
)
def test_property_location_match_rejects_reported_off_scope_austrian_hits(
    title: str,
    summary: str,
    property_url: str,
    expected_postal: str,
) -> None:
    dirty_scope_facts = {
        "postal_name": "1010 Vienna",
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
        "country_code": "AT",
        "region_code": "vienna",
    }

    enriched = product_service._property_enrich_facts_from_listing_text(
        facts=dirty_scope_facts,
        title=title,
        summary=summary,
        listing_mode="rent",
        property_url=property_url,
    )

    if expected_postal:
        assert any(
            str(row.get("postal_code") or "") == expected_postal
            for row in list(enriched.get("listing_postal_evidence") or [])
            if isinstance(row, dict)
        )
    else:
        assert enriched.get("postal_name") != "1010 Vienna"
        assert enriched.get("source_scope_location_placeholder_cleared") is True
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url=property_url,
        title=title,
        summary=summary,
        property_facts=dirty_scope_facts,
        country_code="AT",
        region_code="vienna",
    )


def test_property_url_location_probe_rejects_off_scope_willhaben_detail_paths() -> None:
    salzburg_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/"
    vienna_1220_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1220-donaustadt/demo-1631373932/"
    vienna_1010_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/demo-1631373932/"
    opaque_url = "https://www.willhaben.at/iad/object?adId=1631373932"

    assert _property_candidate_url_has_location_probe(salzburg_url)
    assert _property_candidate_url_has_location_probe(vienna_1220_url)
    assert _property_candidate_url_has_location_probe(vienna_1010_url)
    assert not _property_candidate_url_has_location_probe(opaque_url)
    assert not _property_candidate_url_has_exact_location_probe(salzburg_url)
    assert _property_candidate_url_has_exact_location_probe(vienna_1220_url)
    assert _property_candidate_url_has_exact_location_probe(vienna_1010_url)
    assert not _property_candidate_url_has_exact_location_probe(opaque_url)
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url=salzburg_url,
        country_code="AT",
        region_code="vienna",
    )
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url=vienna_1220_url,
        country_code="AT",
        region_code="vienna",
    )
    assert _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url=vienna_1010_url,
        country_code="AT",
        region_code="vienna",
    )


def test_property_scout_hit_sender_suppresses_dirty_source_scope_when_listing_postal_conflicts(monkeypatch) -> None:
    principal_id = "exec-property-hit-dirty-postal-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Dirty Postal Gate Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["derstandard_at"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("8",)),
    )

    title = "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD"
    summary = "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien."
    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title=title,
        summary=summary,
        counterparty="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.derstandard.at/immobilien/wohnung-1220-wien",
        source_ref="property-scout:derstandard-1220-dirty-scope",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        fit_score=50.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.derstandard.at/immobilien/wohnung-1220-wien",
                "listing_title": title,
                "summary": summary,
                "source_platform": "derstandard_at",
                "source_family": "broker_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.090",
                },
            },
        ),
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "location_scope"


def test_property_scout_hit_sender_validates_matching_candidate_not_first_shortlist_item(monkeypatch) -> None:
    principal_id = "exec-property-hit-matching-candidate-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Matching Candidate Gate")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["derstandard_at"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("12",)),
    )

    current_title = "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD"
    current_summary = "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien."
    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title=current_title,
        summary=current_summary,
        counterparty="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.derstandard.at/immobilien/wohnung-1220-wien",
        source_ref="property-scout:derstandard-1220",
        assessment={"fit_score": 54.0, "recommendation": "review"},
        fit_score=54.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.derstandard.at/immobilien/wohnung-1010-wien",
                "listing_title": "Wohnung mieten in 1010 Wien | 55 m² | 2 Zimmer | € 1.250",
                "summary": "Zentrale Mietwohnung in 1010 Wien.",
                "property_facts": {
                    "postal_name": "1010 Wien",
                    "price_display": "€ 1.250",
                },
            },
            {
                "property_url": "https://www.derstandard.at/immobilien/wohnung-1220-wien",
                "listing_title": current_title,
                "summary": current_summary,
                "source_ref": "property-scout:derstandard-1220",
                "property_facts": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.090",
                },
            },
        ),
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []


def test_property_scout_hit_sender_suppresses_source_scope_only_exact_area_match(monkeypatch) -> None:
    principal_id = "exec-property-hit-source-scope-only-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Source Scope Only Gate")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("9",)),
    )

    title = "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse"
    summary = "Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben."
    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title=title,
        summary=summary,
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        source_ref="property-scout:willhaben-salzburg-dirty-scope",
        assessment={"fit_score": 54.0, "recommendation": "review"},
        fit_score=54.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
                "listing_title": title,
                "summary": summary,
                "source_platform": "willhaben",
                "source_family": "core_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.190",
                },
            },
        ),
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_generic_listing_page"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    diagnostics = dict(repair_tasks[0].input_json or {}).get("diagnostics") or {}
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "generic_listing_page"
    assert diagnostics["provider_host"] == "www.willhaben.at"


def test_property_scout_hit_sender_suppresses_source_scope_only_sparse_card(monkeypatch) -> None:
    principal_id = "exec-property-hit-source-scope-only-sparse"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Source Scope Sparse Gate")
    service = ProductService(client.app.state.container)
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("source-scope-only cards must not notify Telegram"),
    )

    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title="Moderne 2-Zimmer Wohnung mit Terrasse",
        summary="Sparse provider card without a concrete listing location.",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/object?adId=1631373932",
        source_ref="property-scout:source-scope-only-sparse",
        assessment={"fit_score": 82.0, "recommendation": "review"},
        fit_score=82.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/object?adId=1631373932",
                "listing_title": "Moderne 2-Zimmer Wohnung mit Terrasse",
                "summary": "Sparse provider card without a concrete listing location.",
                "source_platform": "willhaben",
                "source_family": "core_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.190",
                },
            },
        ),
        requested_location_hints=(),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "location_scope"


def test_property_generic_listing_page_detector_overrides_detail_shaped_url_for_search_count_snippets() -> None:
    assert _property_candidate_is_generic_listing_page(
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse",
        summary="Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
        property_facts={
            "postal_name": "1010 Vienna",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "source_city": "Vienna",
            "price_display": "€ 1.190",
        },
    )

    assert not _property_candidate_is_generic_listing_page(
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/demo-1631373932/",
        title="Moderne Zwei-Zimmer Wohnung mit Terrasse",
        summary="Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
        property_facts={
            "postal_name": "1010 Vienna",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "source_city": "Vienna",
            "price_display": "€ 1.190",
            "listing_id": "1631373932",
        },
    )

    assert not _property_candidate_is_generic_listing_page(
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-848017019/",
        title=(
            "PROVISIONSFREI - MIETE RUHELAGE SALZBURG PARSCH: "
            "Geräumige 79 m² 3-Zimmer-Wohnung, € 1.398,64, (5020 Salzburg) - willhaben"
        ),
        summary="Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
        property_facts={"rooms": 3, "has_floorplan": True},
    )


def test_property_source_scope_metadata_is_current_run_context_not_cached_listing_truth() -> None:
    stale_facts = {
        "source_scope_location": "1010 Vienna",
        "source_postal_code": "1010",
        "source_city": "Vienna",
        "rooms": 2,
    }

    refreshed = product_service._property_facts_with_source_scope(
        facts=stale_facts,
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?isNavigation=true&q=8010+Waltendorf",
        source_label="Willhaben | Austria | Rent | 8010 Waltendorf",
    )

    assert refreshed["source_scope_location"] == "8010 Waltendorf"
    assert refreshed["source_postal_code"] == "8010"
    assert refreshed["source_city"] == "Waltendorf"


def test_property_scout_hit_sender_uses_source_scope_as_notification_location_fallback(monkeypatch) -> None:
    principal_id = "exec-property-hit-source-scope-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Source Scope Fallback Gate")
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("9",)),
    )

    title = "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich"
    summary = "Moderne Zwei-Zimmer Wohnung mit Terrasse in Salzburg."
    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title=title,
        summary=summary,
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
        source_ref="property-scout:willhaben-salzburg-dirty-scope",
        assessment={"fit_score": 54.0, "recommendation": "review"},
        fit_score=54.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
                "listing_title": title,
                "summary": summary,
                "source_platform": "willhaben",
                "source_family": "core_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.190",
                },
            },
        ),
        requested_location_hints=(),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    diagnostics = dict(repair_tasks[0].input_json or {}).get("diagnostics") or {}
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "location_scope"
    assert diagnostics["location_hints"] == ["1010 Vienna"]


def test_property_scout_hit_email_suppresses_source_scope_only_exact_area_match(monkeypatch) -> None:
    principal_id = "cf-email:source-scope-email-gate@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Source Scope Email Gate")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    monkeypatch.setattr(
        product_service,
        "send_property_match_email",
        lambda **kwargs: pytest.fail("source-scope-only mismatches must not send email"),
    )

    title = "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse"
    summary = "Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben."
    result = service._send_property_scout_hit_email(
        principal_id=principal_id,
        actor="test",
        title=title,
        summary=summary,
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        source_ref="property-scout:willhaben-salzburg-dirty-scope-email",
        assessment={"fit_score": 54.0, "recommendation": "review"},
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
                "listing_title": title,
                "summary": summary,
                "source_platform": "willhaben",
                "source_family": "core_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.190",
                },
            },
        ),
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_generic_listing_page"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    diagnostics = dict(repair_tasks[0].input_json or {}).get("diagnostics") or {}
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "generic_listing_page"
    assert diagnostics["provider_host"] == "www.willhaben.at"


def test_property_scout_hit_email_uses_source_scope_as_notification_location_fallback(monkeypatch) -> None:
    principal_id = "exec-property-hit-email-source-scope-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Email Source Scope Fallback Gate")
    service = ProductService(client.app.state.container)

    title = "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD"
    summary = "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien."
    result = service._send_property_scout_hit_email(
        principal_id=principal_id,
        actor="test",
        title=title,
        summary=summary,
        counterparty="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
        source_ref="property-scout:derstandard-1220-dirty-scope",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        candidate_properties=(
            {
                "property_url": "https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
                "listing_title": title,
                "summary": summary,
                "source_platform": "derstandard_at",
                "source_family": "broker_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "€ 1.090",
                },
            },
        ),
        requested_location_hints=(),
        requested_country_code="AT",
        requested_region_code="vienna",
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"


def test_property_scout_hit_sender_suppresses_generic_pages_missing_concrete_facts(monkeypatch) -> None:
    principal_id = "exec-property-hit-generic-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Scout Hit Generic Gate Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("7",)),
    )

    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title="Familienwohnbau Angebote",
        summary="Ihr Immobilienmakler für Wien. Verkauf, Vermietung, Preis-Check.",
        counterparty="Genossenschaften | Austria | Rent | 1010 Vienna | Familienwohnbau Angebote",
        account_email="",
        property_url="https://example.invalid/immobilien/angebote",
        source_ref="property-scout:generic-offer-page",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        fit_score=50.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://example.invalid/immobilien/angebote",
                "listing_title": "Familienwohnbau Angebote",
                "summary": "Ihr Immobilienmakler für Wien. Verkauf, Vermietung, Preis-Check.",
                "source_platform": "genossenschaften",
                "source_family": "housing_coop",
                "property_facts_json": {
                    "source_scope_location": "1010 Vienna",
                },
            },
        ),
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_generic_listing_page"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert repair_tasks[0].priority == "urgent"
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"
    assert repair_tasks[0].status in {"pending", "returned"}


def test_property_scout_hit_sender_suppresses_architecture_competition_pages(monkeypatch) -> None:
    principal_id = "exec-property-hit-architecture-competition-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Scout Hit Architecture Competition Gate Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["genossenschaften"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("7",)),
    )

    result = service._send_property_scout_hit_telegram(
        principal_id=principal_id,
        actor="test",
        title="Ausschreibungen Architekturwettbewerbe",
        summary="Erhalten Sie alle Informationen zu den neuesten Architekturwettbewerben der Heimat Österreich!",
        counterparty="Genossenschaften | Austria | Rent | 1010 Vienna | Heimat Österreich",
        account_email="",
        property_url="https://example.invalid/ausschreibungen/architekturwettbewerbe",
        source_ref="property-scout:heimat-oesterreich-architecture-competition",
        assessment={"fit_score": 50.0, "recommendation": "review"},
        fit_score=50.0,
        preference_person_id="self",
        candidate_properties=(
            {
                "property_url": "https://example.invalid/ausschreibungen/architekturwettbewerbe",
                "listing_title": "Ausschreibungen Architekturwettbewerbe",
                "summary": "Erhalten Sie alle Informationen zu den neuesten Architekturwettbewerben der Heimat Österreich!",
                "source_platform": "genossenschaften",
                "source_family": "housing_coop",
                "property_facts_json": {
                    "source_scope_location": "1010 Vienna",
                },
            },
        ),
        render_dossier=False,
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_generic_listing_page"
    assert sent == []
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert repair_tasks[0].priority == "urgent"
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"
    assert repair_tasks[0].status in {"pending", "returned"}


def test_property_provider_repair_task_dedupes_across_transient_source_refs() -> None:
    principal_id = "exec-property-provider-repair-dedupe"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Dedupe Office")
    service = ProductService(client.app.state.container)

    first = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://familienwohnbau.at/de/objekt/wohnen-naehe-u4-huetteldorf-e8fd5b2b",
        title="WOHNEN NÄHE U4 HÜTTELDORF | Familienwohnbau",
        source_url="https://familienwohnbau.at/de/objekt/wohnen-naehe-u4-huetteldorf-e8fd5b2b",
        source_label="Familienwohnbau",
        source_platform="familienwohnbau",
        source_family="housing_coop",
        filter_key="require_floorplan",
        diagnostics={"provider_host": "familienwohnbau.at"},
        source_ref="property-scout:run-a-candidate-1",
    )
    second = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://familienwohnbau.at/de/objekt/wohnen-naehe-u4-huetteldorf-e8fd5b2b",
        title="WOHNEN NÄHE U4 HÜTTELDORF | Familienwohnbau",
        source_url="https://familienwohnbau.at/de/objekt/wohnen-naehe-u4-huetteldorf-e8fd5b2b",
        source_label="Familienwohnbau",
        source_platform="familienwohnbau",
        source_family="housing_coop",
        filter_key="require_floorplan",
        diagnostics={"provider_host": "familienwohnbau.at"},
        source_ref="property-scout:run-b-candidate-9",
    )

    assert first["status"] == "opened"
    assert second["status"] == "existing"
    assert second["human_task_id"] == first["human_task_id"]
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(repair_tasks) == 1
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"


def test_property_provider_repair_copy_uses_propertyquarry_language() -> None:
    principal_id = "exec-property-provider-repair-copy"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Copy Office")
    service = ProductService(client.app.state.container)

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://www.gesiba.at/wohnen/demo",
        title="GESIBA demo listing",
        source_url="https://www.gesiba.at/wohnen/demo",
        source_label="GESIBA",
        source_platform="gesiba",
        source_family="housing_coop",
        filter_key="require_floorplan",
        diagnostics={"provider_host": "www.gesiba.at"},
        source_ref="property-scout:copy-guard",
    )

    assert opened["status"] == "opened"
    assert opened["queue_lane"] == "repair"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(repair_tasks) == 1
    task = repair_tasks[0]
    assert dict(task.input_json or {})["queue_lane"] == "repair"
    assert dict(task.input_json or {})["queue_max_attempts"] >= 1
    assert dict(task.input_json or {})["queue_timeout_seconds"] >= 30
    task_text = json.dumps(
        {
            "brief": task.brief,
            "why_human": task.why_human,
            "input_json": task.input_json,
        },
        ensure_ascii=False,
    )
    assert "PropertyQuarry provider repair" in task_text
    assert "EA Provider OODA" not in task_text

    events = [
        row
        for row in client.app.state.container.channel_runtime.list_recent_observations(
            limit=20,
            principal_id=principal_id,
        )
        if row.event_type == "property_provider_repair_task_created"
    ]
    assert len(events) == 1
    assert dict(events[0].payload or {})["queue_lane"] == "repair"
    assert "EA Provider OODA" not in json.dumps(events[0].payload or {}, ensure_ascii=False)


def test_existing_returned_provider_repair_records_receipt_for_new_run() -> None:
    principal_id = "exec-property-provider-repair-existing-receipt"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Existing Receipt Office")
    service = ProductService(client.app.state.container)
    property_url = "https://wohnberatung.example.invalid/search"

    first = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url=property_url,
        title="Wohnberatung Wien",
        source_url=property_url,
        source_label="Wohnberatung Wien | Austria | Rent | Vienna",
        source_platform="wohnberatung_wien",
        source_family="public_housing",
        filter_key="source_fetch",
        diagnostics={"provider_host": "wohnberatung.example.invalid", "error": "HTTP Error 403: Forbidden"},
        run_id="first-repair-run",
    )
    assert first["repair_status"] == "returned"

    run_id = f"existing-repair-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "summary": {
                "sources": [
                    {
                        "source_url": property_url,
                        "source_label": "Wohnberatung Wien | Austria | Rent | Vienna",
                        "provider_repair_task_opened_total": 1,
                    }
                ]
            },
        }

    second = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url=property_url,
        title="Wohnberatung Wien",
        source_url=property_url,
        source_label="Wohnberatung Wien | Austria | Rent | Vienna",
        source_platform="wohnberatung_wien",
        source_family="public_housing",
        filter_key="source_fetch",
        diagnostics={"provider_host": "wohnberatung.example.invalid", "error": "HTTP Error 403: Forbidden"},
        run_id=run_id,
    )

    assert second["status"] == "existing"
    assert second["repair_status"] == "returned"
    snapshot = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    summary = dict(dict(snapshot or {}).get("summary") or {})
    assert summary["repair_resolved_total"] == 1
    assert summary["repair_receipts"][0]["run_id"] == run_id
    assert summary["sources"][0]["repair_status"] == "returned"


def test_property_provider_repair_auto_resolves_generic_listing_pages(monkeypatch) -> None:
    principal_id = "exec-property-provider-auto-resolve"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Auto Resolve Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)

    class _Resp:
        ok = True
        text = """
        <html><head><title>Familienwohnbau Angebote</title></head>
        <body>
        Familienwohnbau Angebote
        Ihr Immobilienmakler für Wien. Verkauf, Vermietung, Preis-Check.
        </body></html>
        """

    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: _Resp())

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://example.invalid/immobilien/angebote",
        title="Familienwohnbau Angebote",
        source_url="https://example.invalid/immobilien/angebote",
        source_label="Familienwohnbau",
        source_platform="familienwohnbau",
        source_family="housing_coop",
        filter_key="missing_price",
        diagnostics={"provider_host": "example.invalid"},
        source_ref="property-scout:generic-offer-page",
    )

    assert opened["status"] == "opened"
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    assert tasks[0].status == "returned"
    assert tasks[0].resolution == "suppressed_generic_listing_page"


def test_property_provider_repair_auto_resolves_generic_listing_page_key_and_records_receipt(monkeypatch) -> None:
    principal_id = "exec-property-provider-generic-key-receipt"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Generic Repair Receipt Office")
    service = ProductService(client.app.state.container)
    property_url = "https://example.invalid/immobilien/angebote"
    run_id = f"generic-repair-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "summary": {
                "sources": [
                    {
                        "source_url": property_url,
                        "source_label": "Familienwohnbau | Austria | Rent | 1010 Vienna",
                        "provider_repair_task_opened_total": 1,
                    }
                ]
            },
        }

    class _Resp:
        ok = True
        text = """
        <html><head><title>Familienwohnbau Angebote</title></head>
        <body>
        Familienwohnbau Angebote
        Ihr Immobilienmakler für Wien. Verkauf, Vermietung, Preis-Check.
        </body></html>
        """

    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: _Resp())

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url=property_url,
        title="Familienwohnbau Angebote",
        source_url=property_url,
        source_label="Familienwohnbau | Austria | Rent | 1010 Vienna",
        source_platform="familienwohnbau",
        source_family="housing_coop",
        filter_key="generic_listing_page",
        diagnostics={"provider_host": "example.invalid"},
        source_ref="property-scout:generic-offer-page",
        run_id=run_id,
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "suppressed_generic_listing_page"
    snapshot = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    summary = dict(dict(snapshot or {}).get("summary") or {})
    assert summary["repair_resolved_total"] == 1
    assert summary["repair_receipts"][0]["filter_key"] == "generic_listing_page"
    assert summary["repair_receipts"][0]["resolution"] == "suppressed_generic_listing_page"
    assert summary["sources"][0]["repair_status"] == "returned"
    assert summary["sources"][0]["repair_resolution"] == "suppressed_generic_listing_page"


def test_property_provider_repair_auto_resolves_provider_scoped_generic_listing_page() -> None:
    principal_id = "exec-property-provider-scoped-generic-repair"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Scoped Generic Repair Office")
    service = ProductService(client.app.state.container)
    run_id = f"provider-scoped-generic-{uuid.uuid4().hex}"
    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1010+Vienna"
    example_url = "https://www.willhaben.at/iad/object?adId=755995091"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "summary": {
                "sources": [
                    {
                        "source_url": source_url,
                        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                        "provider_repair_task_opened_total": 1,
                    }
                ]
            },
        }

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="propertyquarry://provider/willhaben/generic-listing-page",
        title="Willhaben generic listing-page extraction drift",
        source_url=source_url,
        source_label="Willhaben | Austria | Rent | 1010 Vienna",
        source_platform="willhaben",
        source_family="core_portal",
        filter_key="generic_listing_page",
        diagnostics={
            "provider_host": "www.willhaben.at",
            "source_url": source_url,
            "example_property_url": example_url,
            "title": "Wohnen im Zentrum von Graz - Uhrturmblick - willhaben",
            "postal_name": "8020 Graz",
            "source_scope_location": "1010 Vienna",
        },
        source_ref="property-provider:willhaben:generic-listing-page",
        run_id=run_id,
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "suppressed_generic_listing_page"
    snapshot = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    summary = dict(dict(snapshot or {}).get("summary") or {})
    assert summary["repair_receipts"][0]["filter_key"] == "generic_listing_page"
    assert summary["repair_receipts"][0]["resolution"] == "suppressed_generic_listing_page"
    assert summary["repair_receipts"][0]["source_url"] == source_url


def test_property_provider_repair_auto_resolves_generic_listing_scope_from_diagnostics() -> None:
    principal_id = "exec-property-provider-generic-scope-diagnostics"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Generic Scope Repair Office")
    service = ProductService(client.app.state.container)

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://www.egw.at/suche/3789-2-zimmer-wohnung-mit-balkon-top-19",
        title="2-Zimmer-Wohnung mit Balkon in 2630 Ternitz",
        source_url="https://www.egw.at/suche/3789-2-zimmer-wohnung-mit-balkon-top-19",
        source_label="Genossenschaften | Austria | Rent | 1010 Vienna | EGW Immobiliensuche",
        source_platform="egw",
        source_family="housing_coop",
        filter_key="generic_listing_page",
        diagnostics={
            "title": "2-Zimmer-Wohnung mit Balkon in 2630 Ternitz",
            "postal_name": "2630 Ternitz",
            "source_scope_location": "1010 Vienna",
            "provider_host": "www.egw.at",
        },
        source_ref="property-scout:egw:generic-listing-page",
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "suppressed_location_scope"


def test_property_provider_repair_uses_task_scope_over_current_preferences() -> None:
    principal_id = "exec-property-provider-task-scope-over-current"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Task Scope Repair Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1220 Vienna",
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://www.oesw.at/immobilienangebot/projektdetail/mhimmo/anzeigen/Wohnhaus/1220-wien-berresgasse.html",
        title="ProjektDetail",
        source_url="https://www.oesw.at/immobilienangebot/projektdetail/mhimmo/anzeigen/Wohnhaus/1220-wien-berresgasse.html",
        source_label="Genossenschaften | Austria | Rent | 1010 Vienna | ÖSW Sofort verfügbar",
        source_platform="oesw",
        source_family="housing_coop",
        filter_key="generic_listing_page",
        diagnostics={
            "title": "ProjektDetail",
            "source_scope_location": "1010 Vienna",
            "provider_host": "www.oesw.at",
        },
        source_ref="property-scout:oesw:generic-listing-page",
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "suppressed_location_scope"


def test_property_provider_repair_auto_resolves_stale_run_without_claiming_patch() -> None:
    principal_id = "exec-property-provider-stale-run-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Stale Run Repair Office")
    service = ProductService(client.app.state.container)
    run_id = f"stale-run-fallback-{uuid.uuid4().hex}"

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url=f"propertyquarry://search-run/{run_id}",
        title="Search interrupted",
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1010+Vienna",
        source_label="Willhaben | Austria | Rent | 1010 Vienna",
        source_platform="willhaben",
        source_family="core_portal",
        filter_key="run_interrupted_stale",
        diagnostics={"run_id": run_id, "failure_class": "run_interrupted_stale"},
        source_ref=f"property-search-run:{run_id}:stale",
        run_id=run_id,
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "stale_run_restart_required"


def test_property_provider_repair_auto_resolves_walkthrough_without_retrying_render() -> None:
    principal_id = "exec-property-provider-walkthrough-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Walkthrough Repair Office")
    service = ProductService(client.app.state.container)

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://www.willhaben.at/iad/object?adId=1530201253",
        title="Attraktive Wohnung im 2. Bezirk",
        source_url="https://www.willhaben.at/iad/object?adId=1530201253",
        source_label="Willhaben | Austria | Rent | 1010 Vienna",
        source_platform="willhaben",
        source_family="core_portal",
        filter_key="walkthrough_video",
        diagnostics={
            "raw_status": "failed",
            "failure_reason": "onemin_segment_subprocess_timeout",
            "video_url_present": False,
        },
        source_ref="property-tour:walkthrough-video",
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "walkthrough_video_auto_generation_disabled"


def test_property_provider_repair_does_not_cross_resolve_floorplan_into_location_scope(monkeypatch) -> None:
    principal_id = "exec-property-provider-floorplan-semantic-fence"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Semantic Fence Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["kalandra"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)

    class _Resp:
        ok = True
        text = """
        <html><head><title>Wohnung in 1160 Wien</title></head>
        <body>
        Lage: 1160 Wien
        2 Zimmer
        58 m2
        EUR 1.250
        </body></html>
        """

    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: _Resp())

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://example.invalid/listing/1160-no-floorplan",
        title="Wohnung in 1160 Wien",
        source_url="https://example.invalid/search",
        source_label="Kalandra | Austria | Rent | 1010 Vienna",
        source_platform="kalandra",
        source_family="core_portal",
        filter_key="require_floorplan",
        diagnostics={"provider_host": "example.invalid"},
        source_ref="property-scout:kalandra-floorplan",
    )

    assert opened["status"] == "opened"
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    task = service._assign_property_provider_repair_task(
        principal_id=principal_id,
        task=tasks[0],
        actor="ea_one_manager",
        operator_id="ea_one_manager",
    )
    result = service._auto_resolve_property_provider_repair_task(
        principal_id=principal_id,
        task=task,
        actor="ea_one_manager",
    )

    refreshed = [
        row
        for row in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if row.task_type == "property_provider_repair_ooda"
    ][0]
    assert result["status"] == "deferred"
    assert refreshed.status == "pending"
    assert refreshed.resolution == ""


def test_property_provider_repair_snapshot_uses_generic_postal_evidence(monkeypatch) -> None:
    principal_id = "exec-property-provider-repair-generic-postal"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Generic Postal Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)

    class _Resp:
        ok = True
        text = """
        <html><head><title>Moderne Wohnung mit Terrasse</title></head>
        <body>
        Lage: 5020 Salzburg
        2 Zimmer
        58 m2
        EUR 1.250
        </body></html>
        """

    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: _Resp())

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://example.invalid/listing/opaque-123",
        title="Moderne Wohnung mit Terrasse",
        source_url="https://example.invalid/search",
        source_label="Willhaben | Austria | Rent | 1010 Vienna",
        source_platform="willhaben",
        source_family="core_portal",
        filter_key="location_scope",
        diagnostics={
            "provider_host": "example.invalid",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "source_city": "Vienna",
        },
        source_ref="property-scout:generic-postal-repair",
    )

    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"
    assert opened["resolution"] == "suppressed_location_scope"
    refreshed = [
        row
        for row in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if row.task_type == "property_provider_repair_ooda"
    ][0]
    assert refreshed.status == "returned"
    assert refreshed.resolution == "suppressed_location_scope"


def test_property_search_source_fetch_failure_opens_provider_repair_task(monkeypatch) -> None:
    principal_id = "exec-property-source-fetch-repair"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Source Fetch Repair Office")
    service = ProductService(client.app.state.container)

    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": "https://wohnberatung.example.invalid/search",
                "label": "Wohnberatung Wien | Austria | Rent | Vienna",
                "platform": "wohnberatung_wien",
                "provider_family": "public_housing",
                "country_code": "AT",
                "max_results": 4,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("wohnberatung_wien", "https://wohnberatung.example.invalid/search"): {
                "error": "HTTP Error 403: Forbidden",
                "listing_urls": [],
                "provider_cache_state": {"status": "failed", "cache_key": "wohnberatung:vienna"},
            }
        },
    )
    monkeypatch.setattr(
        ProductService,
        "_warm_property_public_preview_cache_for_sources",
        lambda self, **kwargs: {},
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("wohnberatung_wien",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "Vienna",
        },
        max_results_per_source=2,
        force_refresh=True,
    )

    assert result["failed_total"] == 1
    assert result["provider_repair_task_opened_total"] == 1
    assert result["sources"][0]["provider_repair_task_opened_total"] == 1
    assert result["sources"][0]["error"] == "HTTP Error 403: Forbidden"
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    assert tasks[0].priority == "urgent"
    assert tasks[0].assigned_operator_id == "ea_one_manager"
    repair_input = dict(tasks[0].input_json or {})
    assert repair_input["filter_key"] == "source_fetch"
    assert repair_input["diagnostics"]["error"] == "HTTP Error 403: Forbidden"


def test_scheduler_property_results_finalize_processes_provider_repair_tasks(monkeypatch) -> None:
    principal_id = "exec-property-provider-repair-scheduler"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Repair Scheduler Office")
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))
    app_runner = importlib.import_module("app.runner")
    monkeypatch.setattr(app_runner, "_scheduler_property_scout_principal_ids", lambda container: (principal_id,))
    monkeypatch.setattr(
        ProductService,
        "reconcile_property_search_results_delivery",
        lambda self, limit=40: {"attempted": 0, "finalized": 0, "emailed": 0, "pending": 0},
    )
    monkeypatch.setattr(
        ProductService,
        "process_property_provider_repair_tasks",
        lambda self, *, principal_id, actor, limit=40: {
            "generated_at": product_service._now_iso(),
            "resolved_total": 1 if principal_id == "exec-property-provider-repair-scheduler" else 0,
            "deferred_total": 2 if principal_id == "exec-property-provider-repair-scheduler" else 0,
            "resolved": [],
        },
    )

    summary = app_runner._run_scheduler_property_results_finalize(client.app.state.container, SimpleNamespace(exception=lambda *a, **k: None))

    assert summary["repair_resolved_total"] == 1
    assert summary["repair_deferred_total"] == 2


def test_scheduler_property_search_recovery_adopts_stale_in_progress_runs(monkeypatch) -> None:
    principal_id = "exec-property-search-recovery-scheduler"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Recovery Scheduler Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))
    app_runner = importlib.import_module("app.runner")
    service = product_service.build_product_service(client.app.state.container)
    replacement_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        ProductService,
        "_start_property_search_repair_replacement_run",
        lambda self, **kwargs: replacement_calls.append(dict(kwargs)) or {"run_id": "scheduler-stale-repair"},
    )
    run_id = "scheduler-stale-run"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "location_query": "1010 Vienna",
            "max_results_per_source": 1,
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
        force_refresh=False,
    )
    state["status"] = "in_progress"
    state["current_step"] = "source_previewing"
    state["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state["events"] = [
        {
            "at": state["updated_at"],
            "step": "source_previewing",
            "status": "in_progress",
            "message": "Reviewing candidate 12 of 19 for Willhaben.",
        }
    ]
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)
    product_service._store_property_search_run_record(dict(state))

    summary = app_runner._run_scheduler_property_search_recovery(
        client.app.state.container,
        SimpleNamespace(exception=lambda *a, **k: None),
    )

    assert summary["stale_total"] == 1
    assert summary["repaired"] == 1
    assert summary["replacement_started"] == 1
    assert replacement_calls
    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status["status"] == "failed"
    assert status["summary"]["repair_replacement_run_id"] == "scheduler-stale-repair"
    assert any(event["step"] == "run_repair_queued" for event in status["events"])
    assert replacement_calls[0]["max_results_per_source"] is None


def test_property_search_recovery_picks_up_stale_replacement_run(monkeypatch) -> None:
    principal_id = "exec-property-search-recovery-replacement"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Recovery Replacement Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")
    service = product_service.build_product_service(client.app.state.container)
    monkeypatch.setattr(ProductService, "_best_effort_propertyquarry_teable_sync", lambda *args, **kwargs: None)
    replacement_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        ProductService,
        "_start_property_search_repair_replacement_run",
        lambda self, **kwargs: replacement_calls.append(dict(kwargs)) or {"run_id": "unexpected-nested-repair"},
    )
    scout_calls: list[dict[str, object]] = []

    def _fake_sync_direct_property_scout(self, **kwargs):
        scout_calls.append(dict(kwargs))
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            progress_callback(
                step="source_started",
                message="Checking recovered replacement source.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 1},
            )
        return {
            "status": "processed",
            "sources_total": 1,
            "sources": [{"source_label": "Willhaben", "status": "processed"}],
            "listing_total": 0,
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)
    parent_run_id = "scheduler-parent-stale-run"
    replacement_run_id = "scheduler-replacement-stale-run"
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    parent_state = product_service._new_property_search_run_record(
        run_id=parent_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "location_query": "1010 Vienna",
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
        force_refresh=False,
    )
    parent_state["status"] = "failed"
    parent_state["summary"] = {
        **dict(parent_state.get("summary") or {}),
        "repair_replacement_run_id": replacement_run_id,
        "repair_replacement_status_url": f"/app/api/signals/property/search/run/{replacement_run_id}",
    }
    replacement_state = product_service._new_property_search_run_record(
        run_id=replacement_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "location_query": "1010 Vienna",
            "max_results_per_source": 1,
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
        force_refresh=True,
    )
    replacement_state["status"] = "starting"
    replacement_state["current_step"] = "starting"
    replacement_state["message"] = "Starting property search run."
    replacement_state["updated_at"] = stale_timestamp
    replacement_state["events"] = [
        {
            "at": stale_timestamp,
            "step": "starting",
            "status": "starting",
            "message": "Starting property search run.",
        }
    ]
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[parent_run_id] = dict(parent_state)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[replacement_run_id] = dict(replacement_state)
    product_service._store_property_search_run_record(dict(parent_state))
    product_service._store_property_search_run_record(dict(replacement_state))

    summary = service.reconcile_stale_property_search_runs(principal_id=principal_id, limit=20)

    assert summary["stale_total"] == 1
    assert summary["repaired"] == 1
    assert summary["replacement_started"] == 0
    assert summary["recovered"][0]["execution_pickup_status"] == "started"
    for _ in range(60):
        status = service.get_property_search_run_status(principal_id=principal_id, run_id=replacement_run_id)
        if status and str(status.get("status") or "") == "processed":
            break
        time.sleep(0.02)
    assert status is not None
    assert status["status"] == "processed"
    assert status["summary"]["execution_pickup_status"] == "completed"
    assert status["summary"]["execution_pickup_reason"] == "replacement_run_stale"
    assert status["summary"]["repair_parent_run_ids"] == [parent_run_id]
    assert any(event["step"] == "recovery_pickup_started" for event in status["events"])
    assert scout_calls
    assert scout_calls[0]["max_results_per_source"] is None
    assert scout_calls[0]["property_search_preferences"]["__property_search_run_id__"] == replacement_run_id
    assert replacement_calls == []


def test_property_search_recovery_pickup_failure_opens_repair_task(monkeypatch) -> None:
    principal_id = "exec-property-search-recovery-pickup-failure"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Recovery Pickup Failure Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")
    service = product_service.build_product_service(client.app.state.container)
    monkeypatch.setattr(ProductService, "_best_effort_propertyquarry_teable_sync", lambda *args, **kwargs: None)

    def _raise_pickup_failure(self, **kwargs):
        raise RuntimeError("pickup worker crashed before source rows existed")

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _raise_pickup_failure)
    parent_run_id = "scheduler-parent-pickup-failure"
    replacement_run_id = "scheduler-replacement-pickup-failure"
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    parent_state = product_service._new_property_search_run_record(
        run_id=parent_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "1010 Vienna"},
        force_refresh=False,
    )
    parent_state["status"] = "failed"
    parent_state["summary"] = {
        **dict(parent_state.get("summary") or {}),
        "repair_replacement_run_id": replacement_run_id,
    }
    replacement_state = product_service._new_property_search_run_record(
        run_id=replacement_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "1010 Vienna", "max_results_per_source": 1},
        force_refresh=True,
    )
    replacement_state["status"] = "starting"
    replacement_state["current_step"] = "starting"
    replacement_state["updated_at"] = stale_timestamp
    replacement_state["events"] = [
        {
            "at": stale_timestamp,
            "step": "starting",
            "status": "starting",
            "message": "Starting property search run.",
        }
    ]
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[parent_run_id] = dict(parent_state)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[replacement_run_id] = dict(replacement_state)
    product_service._store_property_search_run_record(dict(parent_state))
    product_service._store_property_search_run_record(dict(replacement_state))

    summary = service.reconcile_stale_property_search_runs(principal_id=principal_id, limit=20)

    assert summary["stale_total"] == 1
    assert summary["repaired"] == 1
    for _ in range(60):
        status = service.get_property_search_run_status(principal_id=principal_id, run_id=replacement_run_id)
        if status and str(status.get("status") or "") == "failed":
            break
        time.sleep(0.02)
    assert status is not None
    assert status["status"] == "failed"
    assert status["summary"]["execution_pickup_status"] == "failed"
    assert status["summary"]["repair_status"] == "repairing"
    assert status["summary"]["provider_repair_task_opened_total"] == 1
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    repair_input = dict(tasks[0].input_json or {})
    assert repair_input["filter_key"] == "run_worker_exception"
    assert repair_input["run_id"] == replacement_run_id
    assert repair_input["diagnostics"]["recovery_reason"] == "replacement_run_stale"
    assert repair_input["diagnostics"]["repair_parent_run_ids"] == [parent_run_id]


def test_property_search_run_status_enriches_source_fetch_repairs() -> None:
    principal_id = "exec-property-run-status-repair-enrichment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Run Status Repair Enrichment Office")
    service = ProductService(client.app.state.container)
    run_id = f"repair-status-{uuid.uuid4().hex}"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fetch blocked")))
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["wohnberatung_wien"],
            "progress": 36,
            "message": "Fetching source page for Wohnberatung Wien.",
            "summary": {
                "status": "in_progress",
                "sources_total": 1,
                "reviewed_listing_total": 0,
                "sources": [
                    {
                        "source_url": "https://wohnberatung.example.invalid/search",
                        "source_label": "Wohnberatung Wien | Austria | Rent | Vienna",
                        "error": "HTTP Error 403: Forbidden",
                    }
                ],
            },
        }
    service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://wohnberatung.example.invalid/search",
        title="Wohnberatung Wien | Austria | Rent | Vienna",
        source_url="https://wohnberatung.example.invalid/search",
        source_label="Wohnberatung Wien | Austria | Rent | Vienna",
        source_platform="wohnberatung_wien",
        source_family="public_housing",
        filter_key="source_fetch",
        diagnostics={"provider_host": "wohnberatung.example.invalid", "error": "HTTP Error 403: Forbidden"},
        source_ref="property-source:test",
    )
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    source = status["summary"]["sources"][0]
    assert source["status"] == "repaired"
    assert source["repair_status"] == "returned"
    assert source["provider_repair_tasks"][0]["resolution"] == "suppressed_source_fetch_forbidden"
    monkeypatch.undo()


def test_property_search_run_terminal_receives_repair_receipt_without_task_scan(monkeypatch) -> None:
    principal_id = "exec-property-run-terminal-repair-receipt"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Terminal Repair Receipt Office")
    service = ProductService(client.app.state.container)
    run_id = f"repair-receipt-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "completed_partial",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["wohnberatung_wien"],
            "progress": 100,
            "message": "Current shortlist is still available.",
            "summary": {
                "status": "completed_partial",
                "sources_total": 2,
                "ranked_candidates": [{"candidate_ref": "cand-1", "title": "Recovered hit"}],
                "sources": [
                    {
                        "source_url": "https://wohnberatung.example.invalid/search",
                        "source_label": "Wohnberatung Wien | Austria | Rent | Vienna",
                        "status": "failed",
                        "error": "HTTP Error 403: Forbidden",
                    }
                ],
            },
        }
    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fetch blocked")))
    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://wohnberatung.example.invalid/search",
        title="Wohnberatung Wien | Austria | Rent | Vienna",
        source_url="https://wohnberatung.example.invalid/search",
        source_label="Wohnberatung Wien | Austria | Rent | Vienna",
        source_platform="wohnberatung_wien",
        source_family="public_housing",
        filter_key="source_fetch",
        diagnostics={"provider_host": "wohnberatung.example.invalid", "error": "HTTP Error 403: Forbidden"},
        source_ref="property-source:test",
        run_id=run_id,
    )
    assert opened["status"] in {"opened", "existing"}

    monkeypatch.setattr(
        client.app.state.container.orchestrator,
        "list_human_tasks",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal status should not scan repair tasks")),
    )
    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    summary = dict(status.get("summary") or {})
    source = dict((summary.get("sources") or [])[0])
    assert source["status"] == "repaired"
    assert source["repair_status"] == "returned"
    assert source["repair_resolution"] == "suppressed_source_fetch_forbidden"
    receipts = [dict(row) for row in list(summary.get("repair_receipts") or []) if isinstance(row, dict)]
    assert len(receipts) == 1
    assert receipts[0]["run_id"] == run_id
    assert receipts[0]["resolution"] == "suppressed_source_fetch_forbidden"


def test_property_search_run_final_event_applies_early_source_fetch_repair_receipt(monkeypatch) -> None:
    principal_id = "exec-property-run-early-repair-receipt"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Early Repair Receipt Office")
    service = ProductService(client.app.state.container)
    run_id = f"early-repair-receipt-{uuid.uuid4().hex}"
    now = product_service._now_iso()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": now,
            "updated_at": now,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["wohnberatung_wien", "willhaben"],
            "progress": 18,
            "message": "Fetching source page for Wohnberatung Wien.",
            "summary": {
                "status": "in_progress",
                "sources_total": 2,
                "sources": [],
            },
        }
    monkeypatch.setattr(product_service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fetch blocked")))

    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url="https://wohnberatung.example.invalid/search",
        title="Wohnberatung Wien | Austria | Rent | Vienna",
        source_url="https://wohnberatung.example.invalid/search",
        source_label="Wohnberatung Wien | Austria | Rent | Vienna",
        source_platform="wohnberatung_wien",
        source_family="public_housing",
        filter_key="source_fetch",
        diagnostics={"provider_host": "wohnberatung.example.invalid", "error": "HTTP Error 403: Forbidden"},
        source_ref="property-source:test",
        run_id=run_id,
    )
    assert opened["status"] == "opened"
    assert opened["repair_status"] == "returned"

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="completed",
        message="Search run completed with partial coverage.",
        status="completed_partial",
        steps_delta=0,
        force_status="completed_partial",
        summary_updates={
            "status": "completed_partial",
            "sources_total": 2,
            "failed_total": 1,
            "ranked_candidates": [{"candidate_ref": "cand-1", "title": "Usable hit"}],
            "sources": [
                {
                    "source_url": "https://wohnberatung.example.invalid/search",
                    "source_label": "Wohnberatung Wien | Austria | Rent | Vienna",
                    "status": "failed",
                    "error": "HTTP Error 403: Forbidden",
                    "provider_repair_task_opened_total": 1,
                    "provider_repair_tasks": [
                        {
                            "status": "opened",
                            "filter_key": "source_fetch",
                            "human_task_id": opened["human_task_id"],
                            "queue_item_ref": opened["queue_item_ref"],
                        }
                    ],
                },
                {
                    "source_url": "https://www.willhaben.at/iad/immobilien/",
                    "source_label": "Willhaben | Austria | Rent | Vienna",
                    "status": "completed",
                    "listing_total": 1,
                },
            ],
        },
    )

    monkeypatch.setattr(
        client.app.state.container.orchestrator,
        "list_human_tasks",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal status should use repair receipts")),
    )
    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    summary = dict(status.get("summary") or {})
    source = dict((summary.get("sources") or [])[0])
    assert source["status"] == "repaired"
    assert source["repair_status"] == "returned"
    assert source["repair_resolution"] == "suppressed_source_fetch_forbidden"
    assert source["error"] == ""
    assert source["original_error"] == "HTTP Error 403: Forbidden"
    assert source["provider_repair_tasks"][0]["status"] == "returned"
    receipts = [dict(row) for row in list(summary.get("repair_receipts") or []) if isinstance(row, dict)]
    assert len(receipts) == 1
    assert receipts[0]["run_id"] == run_id


def test_recent_property_source_fetch_repair_memory_returns_latest_returned_source_fetch_resolution(monkeypatch) -> None:
    principal_id = "exec-property-repair-memory"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Repair Memory Office")
    service = ProductService(client.app.state.container)
    older = SimpleNamespace(
        task_type="property_provider_repair_ooda",
        status="returned",
        resolution="suppressed_source_fetch_missing",
        updated_at="2026-06-16T09:00:00Z",
        created_at="2026-06-16T08:00:00Z",
        human_task_id="older-task",
        input_json={
            "filter_key": "source_fetch",
            "source_url": "https://www.kalandra.at/search",
            "source_label": "Kalandra | Austria | Rent | 1010 Vienna",
        },
        returned_payload_json={"reason": "older"},
    )
    latest = SimpleNamespace(
        task_type="property_provider_repair_ooda",
        status="returned",
        resolution="suppressed_source_fetch_forbidden",
        updated_at=product_service._now_iso(),
        created_at=product_service._now_iso(),
        human_task_id="latest-task",
        input_json={
            "filter_key": "source_fetch",
            "source_url": "https://www.kalandra.at/search",
            "source_label": "Kalandra | Austria | Rent | 1010 Vienna",
        },
        returned_payload_json={"reason": "provider blocked"},
    )
    monkeypatch.setattr(
        client.app.state.container.orchestrator,
        "list_human_tasks",
        lambda **kwargs: [older, latest],
    )

    memory = service._recent_property_source_fetch_repair_memory(principal_id=principal_id)
    key = service._property_source_repair_memory_key(
        source_url="https://www.kalandra.at/search",
        source_label="Kalandra | Austria | Rent | 1010 Vienna",
    )

    assert memory[key]["resolution"] == "suppressed_source_fetch_forbidden"
    assert memory[key]["reason"] == "provider blocked"
    assert memory[key]["human_task_id"] == "latest-task"


def test_property_search_sparse_auction_floorplan_area_scores_above_review_threshold() -> None:
    preview = {
        "title": "BG Leopoldstadt, 082 25 E 89/25g",
        "summary": "Sparse judicial auction detail page.",
        "property_facts_json": {
            "area_sqm": 126.59,
            "floorplan_count": 1,
            "floorplan_urls_json": ["https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/0/example/$file/Gutachten.pdf"],
            "provider_channel": "justiz_edikte_at",
            "sale_channel": "judicial_auction",
            "source_scope_location": "1020 Vienna",
        },
    }
    assessment = {
        "fit_score": 47.96,
        "upstream_personalization": {"adjusted_fit_score": 45.46},
    }

    score = product_service._property_scout_rank_score(
        property_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        assessment=assessment,
        preview=preview,
        ordinal=6,
    )

    assert score >= 54.0


def test_property_search_keeps_review_candidate_when_only_score_threshold_fails(monkeypatch) -> None:
    principal_id = "exec-property-soft-score-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Soft Score Fallback Office")
    service = ProductService(client.app.state.container)

    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt",
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 1,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/review-but-low-score-1/"
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"): {
                "listing_urls": [listing_url],
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:soft-score"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview_with_timeout",
        lambda property_url, *, prefer_fast=False: {
            "listing_id": "soft-score-1",
            "title": "Mietwohnung in 1020 Wien mit Balkon",
            "summary": "78 m2, 3 Zimmer, Gesamtmiete EUR 1.650, Balkon.",
            "property_facts_json": {
                "postal_name": "1020 Wien",
                "area_sqm": 78,
                "rooms": 3,
                "total_rent_eur": 1650,
                "has_balcony": True,
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_alert_personal_fit_from_facts",
        lambda **kwargs: {
            "fit_score": 12.0,
            "recommendation": "review",
            "match_reasons_json": [],
            "mismatch_reasons_json": ["Soft preference mismatch"],
            "unknowns_json": [],
        },
    )
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "property_type": "apartment",
            "min_match_score": 95,
            "require_floorplan": False,
        },
        max_results_per_source=1,
        force_refresh=True,
    )

    assert result["listing_total"] == 1
    assert result["high_fit_total"] == 0
    assert result["filtered_low_fit_total"] == 1
    candidate = dict(result["sources"][0]["top_candidates"][0])
    assert candidate["property_url"] == listing_url
    assert 0 < float(candidate["fit_score"]) < 95
    assert candidate["recommendation"] == "review"
    assert candidate["score_demoted"] is True
    assert candidate["below_match_threshold"] is True
    assert "kept for ranking" in candidate["score_demotion_reason"]
    assert dict(candidate["property_facts"])["score_demoted_by_match_threshold"] is True


def test_property_search_alert_scoring_respects_stored_feedback_toggle(monkeypatch) -> None:
    principal_id = "exec-property-alert-neutral-personalization"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Alert Neutral Personalization Office")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/neutral-alert-score/"
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 1,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": [listing_url],
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:neutral-alert"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview_with_timeout",
        lambda property_url, *, prefer_fast=False: {
            "listing_id": "neutral-alert-score",
            "title": "Mietwohnung in 1020 Wien mit Balkon",
            "summary": "78 m2, 3 Zimmer, Gesamtmiete EUR 1.650, Balkon.",
            "property_facts_json": {
                "postal_name": "1020 Wien",
                "area_sqm": 78,
                "rooms": 3,
                "total_rent_eur": 1650,
                "has_balcony": True,
            },
        },
    )
    observed_profile_flags: list[bool] = []

    def _fake_fit(**kwargs) -> dict[str, object]:
        use_profile_preferences = bool(kwargs.get("use_profile_preferences", True))
        observed_profile_flags.append(use_profile_preferences)
        return {
            "fit_score": 91.0 if use_profile_preferences else 52.0,
            "recommendation": "strong_fit" if use_profile_preferences else "review",
            "match_reasons_json": [],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "stored_feedback_preferences_used": use_profile_preferences,
        }

    monkeypatch.setattr(product_service, "_property_alert_personal_fit_from_facts", _fake_fit)
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {"status": "opened", "editor_url": "/app/research/neutral-alert-score"},
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "property_type": "apartment",
            "min_match_score": 40,
            "require_floorplan": False,
            "use_stored_feedback_preferences": False,
        },
        max_results_per_source=1,
        force_refresh=True,
    )

    assert observed_profile_flags
    assert observed_profile_flags == [False]
    assert result["listing_total"] == 1
    candidate = dict(result["sources"][0]["top_candidates"][0])
    assert candidate["property_url"] == listing_url
    assert 52.0 <= float(candidate["fit_score"]) < 91.0
    assert dict(candidate["assessment"])["stored_feedback_preferences_used"] is False


def test_property_search_keeps_demoted_soft_mismatch_candidates_in_remaining_shortlist_slots(monkeypatch) -> None:
    principal_id = "exec-property-soft-mismatch-shortlist-slots"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Soft Mismatch Shortlist Office")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"
    strong_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/high-fit/"
    demoted_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/soft-mismatch/"
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 3,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": [strong_url, demoted_url],
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:soft-mismatch-shortlist"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )

    def _fake_preview(property_url: str, *, prefer_fast: bool = False) -> dict[str, object]:
        if property_url == strong_url:
            return {
                "listing_id": "strong-shortlist",
                "title": "Familienwohnung nahe Park",
                "summary": "78 m2, 3 Zimmer, Gesamtmiete EUR 1.650, Balkon.",
                "property_facts_json": {
                    "postal_name": "1020 Wien",
                    "area_sqm": 78,
                    "rooms": 3,
                    "total_rent_eur": 1650,
                    "has_balcony": True,
                },
            }
        return {
            "listing_id": "demoted-shortlist",
            "title": "Helle Wohnung mit Lift und Balkon",
            "summary": "71 m2, 2 Zimmer, Gesamtmiete EUR 1.540, Lift, Balkon.",
            "property_facts_json": {
                "postal_name": "1020 Wien",
                "area_sqm": 71,
                "rooms": 2,
                "total_rent_eur": 1540,
                "has_lift": True,
                "has_balcony": True,
            },
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)

    def _fake_fit(**kwargs) -> dict[str, object]:
        listing_id = str(kwargs.get("listing_id") or kwargs.get("object_id") or "")
        score = 81.0 if listing_id == "strong-shortlist" else 12.0
        return {
            "fit_score": score,
            "confidence": 0.76,
            "predicted_reaction": "consider",
            "recommendation": "shortlist" if score >= 65 else "review",
            "match_reasons_json": ["Above the matching threshold."] if score >= 65 else ["Worth a look despite softer mismatches."],
            "mismatch_reasons_json": [] if score >= 65 else ["Below the matching threshold."],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        }

    monkeypatch.setattr(product_service, "_property_alert_personal_fit_from_facts", _fake_fit)
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {"status": "opened", "editor_url": f"/app/research/{kwargs.get('source_ref') or 'candidate'}"},
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "property_type": "apartment",
            "min_match_score": 65,
            "require_floorplan": False,
        },
        max_results_per_source=3,
        force_refresh=True,
    )

    titles = [row["title"] for row in result["sources"][0]["top_candidates"]]
    assert result["listing_total"] == 2
    assert result["sources"][0]["filtered_low_fit_total"] == 1
    assert titles == ["Familienwohnung nahe Park", "Helle Wohnung mit Lift und Balkon"]
    assert result["sources"][0]["top_candidates"][1]["below_match_threshold"] is True


def test_agent_property_search_keeps_all_ranked_results_per_provider(monkeypatch) -> None:
    principal_id = "exec-property-agent-unlimited-provider-results"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Agent Unlimited Provider Results")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"
    listing_urls = [
        f"https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/unlimited-{index}/"
        for index in range(12)
    ]
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 3,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": list(listing_urls),
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:agent-unlimited"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )

    def _fake_preview(property_url: str, *, prefer_fast: bool = False) -> dict[str, object]:
        slug = property_url.rstrip("/").rsplit("/", 1)[-1]
        return {
            "listing_id": slug,
            "title": f"Mietwohnung {slug}",
            "summary": "78 m2, 3 Zimmer, Gesamtmiete EUR 1.650, Balkon.",
            "property_facts_json": {
                "postal_name": "1020 Wien",
                "area_sqm": 78,
                "rooms": 3,
                "total_rent_eur": 1650,
                "has_balcony": True,
            },
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)
    monkeypatch.setattr(
        product_service,
        "_property_alert_personal_fit_from_facts",
        lambda **kwargs: {
            "fit_score": 84.0,
            "confidence": 0.82,
            "predicted_reaction": "consider",
            "recommendation": "strong_fit",
            "match_reasons_json": ["Strong fit"],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
            "blocking_constraints_json": [],
        },
    )
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {"status": "opened", "editor_url": f"/app/research/{kwargs.get('source_ref') or 'candidate'}"},
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "property_type": "apartment",
            "min_match_score": 40,
            "require_floorplan": False,
            "max_results_per_source": 1,
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
        force_refresh=True,
    )

    source = dict(result["sources"][0])
    assert result["listing_total"] == len(listing_urls)
    assert source["listing_total"] == len(listing_urls)
    assert len(source["top_candidates"]) == len(listing_urls)
    assert len(source["research_candidates"]) == len(listing_urls)
    assert {row["property_url"] for row in source["top_candidates"]} == set(listing_urls)


def test_property_search_soft_filters_do_not_change_discovered_hit_set(monkeypatch) -> None:
    principal_id = "exec-property-soft-filter-equivalence"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Soft Filter Equivalence Office")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"
    listing_urls = [
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/soft-filter-a/",
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/soft-filter-b/",
    ]
    facts_by_url = {
        listing_urls[0]: {
            "postal_name": "1020 Wien",
            "area_sqm": 78,
            "rooms": 3,
            "total_rent_eur": 1650,
            "nearest_library_m": 1800,
            "nearest_playground_m": 1200,
            "nearest_shopping_center_m": 160,
            "nearest_theatre_m": 900,
            "nearest_supermarket_m": 700,
        },
        listing_urls[1]: {
            "postal_name": "1020 Wien",
            "area_sqm": 82,
            "rooms": 3,
            "total_rent_eur": 1720,
            "nearest_library_m": 220,
            "nearest_playground_m": 420,
            "nearest_shopping_center_m": 900,
            "nearest_theatre_m": 350,
            "nearest_supermarket_m": 180,
        },
    }

    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 5,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": list(listing_urls),
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:soft-filter-equivalence"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )

    def _fake_preview(property_url: str, *, prefer_fast: bool = False) -> dict[str, object]:
        facts = dict(facts_by_url[property_url])
        return {
            "listing_id": property_url.rsplit("/", 2)[-2],
            "title": f"Mietwohnung in 1020 Wien {property_url.rsplit('/', 2)[-2]}",
            "summary": "78 m2, 3 Zimmer, Gesamtmiete EUR 1.650, Balkon.",
            "property_facts_json": facts,
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)

    def _fake_fit(**kwargs) -> dict[str, object]:
        property_url = str(kwargs.get("property_url") or "")
        return {
            "fit_score": 54.0 if property_url.endswith("soft-filter-a/") else 58.0,
            "recommendation": "review",
            "match_reasons_json": ["Hard search basics match"],
            "mismatch_reasons_json": ["Some soft preferences differ"],
            "unknowns_json": [],
        }

    monkeypatch.setattr(product_service, "_property_alert_personal_fit_from_facts", _fake_fit)
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {
            "status": "opened",
            "editor_url": f"/app/research/{str(kwargs.get('source_ref') or 'candidate').split(':')[-1]}",
        },
    )

    hard_preferences = {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1020 Vienna",
        "property_type": "apartment",
        "min_match_score": 95,
        "require_floorplan": False,
    }
    soft_preferences = {
        **hard_preferences,
        "max_distance_to_library_m": 500,
        "max_distance_to_library_importance": "strong_wish",
        "max_distance_to_playground_m": 500,
        "max_distance_to_playground_importance": "nice_to_have",
        "max_distance_to_shopping_center_m": 500,
        "max_distance_to_shopping_center_importance": "avoid",
        "max_distance_to_theatre_m": 700,
        "max_distance_to_theatre_importance": "strong_wish",
        "max_distance_to_supermarket_m": 300,
        "max_distance_to_supermarket_importance": "nice_to_have",
        "avoid_noise_risk_area": True,
        "require_high_speed_internet_evidence": True,
        "check_parking_situation": True,
        "avoid_flood_risk_area": True,
    }

    plain_result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences=hard_preferences,
        max_results_per_source=5,
        force_refresh=True,
    )
    soft_result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences=soft_preferences,
        max_results_per_source=5,
        force_refresh=True,
    )

    def _urls(result: dict[str, object]) -> set[str]:
        rows = list(dict(list(result.get("sources") or [])[0]).get("research_candidates") or [])
        return {str(row.get("property_url") or "") for row in rows}

    assert _urls(plain_result) == set(listing_urls)
    assert _urls(soft_result) == set(listing_urls)
    assert _urls(soft_result) == _urls(plain_result)
    soft_rows = list(dict(list(soft_result.get("sources") or [])[0]).get("research_candidates") or [])
    assert any(dict(dict(row).get("property_facts") or {}).get("distance_preference_notes") for row in soft_rows)


def test_property_search_neutral_filter_importance_keeps_distance_candidates(monkeypatch) -> None:
    principal_id = "exec-property-neutral-filter-preserve-candidates"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Neutral Filter Preserves Hits")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1220-brigittenau"
    listing_urls = [
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1220-brigittenau/neutral-filter-a/",
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1220-brigittenau/neutral-filter-b/",
    ]
    facts_by_url = {
        listing_urls[0]: {
            "postal_name": "1220 Wien",
            "area_sqm": 74,
            "rooms": 2,
            "total_rent_eur": 1300,
            "nearest_library_m": 2200,
            "nearest_supermarket_m": 2800,
            "nearest_playground_m": 1900,
        },
        listing_urls[1]: {
            "postal_name": "1220 Wien",
            "area_sqm": 68,
            "rooms": 2,
            "total_rent_eur": 1280,
            "nearest_library_m": 2600,
            "nearest_supermarket_m": 2500,
            "nearest_playground_m": 1700,
        },
    }

    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1220 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 6,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": list(listing_urls),
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:neutral-filter-preserve"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )

    def _fake_preview(property_url: str, *, prefer_fast: bool = False) -> dict[str, object]:
        facts = dict(facts_by_url[property_url])
        return {
            "listing_id": property_url.rsplit("/", 2)[-2],
            "title": f"Mietwohnung in 1220 Wien {property_url.rsplit('/', 2)[-2]}",
            "summary": "68 m², 2 Zimmer, Gesamtmiete EUR 1.300, Balkon.",
            "property_facts_json": facts,
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)

    def _fake_fit(**kwargs) -> dict[str, object]:
        property_url = str(kwargs.get("property_url") or "")
        return {
            "fit_score": 52.0 if property_url.endswith("neutral-filter-a/") else 57.0,
            "recommendation": "review",
            "match_reasons_json": ["Hard search basics match"],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
        }

    monkeypatch.setattr(product_service, "_property_alert_personal_fit_from_facts", _fake_fit)
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {
            "status": "opened",
            "editor_url": f"/app/research/{str(kwargs.get('source_ref') or 'candidate').split(':')[-1]}",
        },
    )

    base_preferences = {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1220 Vienna",
        "property_type": "apartment",
        "require_floorplan": False,
    }
    neutral_preferences = {
        **base_preferences,
        "max_distance_to_library_m": 500,
        "max_distance_to_library_importance": "neutral",
        "max_distance_to_supermarket_m": 500,
        "max_distance_to_supermarket_importance": "neutral",
        "max_distance_to_playground_m": 500,
        "max_distance_to_playground_importance": "neutral",
    }

    neutral_result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences=neutral_preferences,
        max_results_per_source=6,
        force_refresh=True,
    )

    def _captured_urls(result: dict[str, object]) -> set[str]:
        rows = list(dict(list(result.get("sources") or [])[0]).get("research_candidates") or [])
        return {str(row.get("property_url") or "") for row in rows}

    assert _captured_urls(neutral_result) == set(listing_urls)
def test_property_search_filters_dirty_source_scope_postal_conflict_before_shortlist(monkeypatch) -> None:
    principal_id = "exec-property-run-dirty-postal-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Run Dirty Postal Gate Office")
    service = ProductService(client.app.state.container)

    source_url = "https://www.derstandard.at/immobilien/mieten/wien/1010"
    listing_url = "https://www.derstandard.at/immobilien/wohnung-1220-wien"
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
                "platform": "derstandard_at",
                "provider_family": "broker_portal",
                "country_code": "AT",
                "max_results": 1,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("derstandard_at", source_url): {
                "listing_urls": [listing_url],
                "provider_cache_state": {"status": "miss", "cache_key": "derstandard:dirty-postal"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview_with_timeout",
        lambda property_url, *, prefer_fast=False: {
            "listing_id": "derstandard-1220",
            "title": "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD",
            "summary": "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
            "property_facts_json": {
                "postal_name": "1010 Vienna",
                "source_scope_location": "1010 Vienna",
                "source_postal_code": "1010",
                "source_city": "Vienna",
                "area_sqm": 60,
                "rooms": 2,
                "total_rent_eur": 1090,
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_alert_personal_fit_from_facts",
        lambda **kwargs: {
            "fit_score": 94.0,
            "recommendation": "strong_fit",
            "match_reasons_json": ["Would otherwise rank highly."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
        },
    )
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("outside-area candidate must not notify")),
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("derstandard_at",),
        property_search_preferences={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "property_type": "apartment",
            "min_match_score": 50,
            "require_floorplan": False,
        },
        max_results_per_source=1,
        force_refresh=True,
    )

    assert result["listing_total"] == 0
    assert result["high_fit_total"] == 0
    assert result["review_created_total"] == 0
    source = dict(result["sources"][0])
    assert source["raw_listing_total"] == 1
    assert source["scanned_listing_total"] == 1
    assert source["top_candidates"] == []
    assert source["location_mismatch_candidate_total"] >= 1
    assert source["location_mismatch_reason"] == "provider_returned_candidates_outside_selected_location"


def test_property_search_full_region_does_not_treat_generated_district_source_as_hard_scope(monkeypatch) -> None:
    principal_id = "exec-property-run-full-region-source-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Run Full Region Source Scope Office")
    service = ProductService(client.app.state.container)

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen?isNavigation=true&q=1010+Vienna"
    listing_url = "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/full-region-1020/"
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1010 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 1,
                "notify_telegram": False,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": [listing_url],
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:full-region-source-scope"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_page_preview_with_timeout",
        lambda property_url, *, prefer_fast=False: {
            "listing_id": "full-region-1020",
            "title": "Wohnung mieten in 1020 Wien | 74 m² | 3 Zimmer",
            "summary": "Wohnung im 2. Bezirk, aber innerhalb der gewählten Stadt Wien.",
            "property_facts_json": {
                "postal_name": "1020 Wien",
                "area_sqm": 74,
                "rooms": 3,
                "total_rent_eur": 990,
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_property_alert_personal_fit_from_facts",
        lambda **kwargs: {
            "fit_score": 72.0,
            "recommendation": "review",
            "match_reasons_json": ["The listing is inside Vienna."],
            "mismatch_reasons_json": [],
            "unknowns_json": [],
        },
    )
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {
            "status": "opened",
            "editor_url": "/app/research/full-region-1020",
        },
    )

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "Vienna",
            "full_region_scope": True,
            "property_type": "apartment",
            "min_match_score": 50,
            "require_floorplan": False,
        },
        max_results_per_source=1,
        force_refresh=True,
    )

    assert result["listing_total"] == 1
    source = dict(result["sources"][0])
    assert source["filtered_area_total"] == 0
    assert source["location_mismatch_candidate_total"] == 0
    assert [row["property_url"] for row in source["research_candidates"]] == [listing_url]


def test_property_search_type_filter_blocks_garage_for_residential_searches() -> None:
    garage_title = "Garagenplatz zu vermieten, 10 m2, EUR 190,-, (1030 Wien) - willhaben"

    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/object?adId=1835567057",
            title=garage_title,
            summary="Garagenplatz zu vermieten.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="house",
            property_url="https://www.willhaben.at/iad/object?adId=1835567057",
            title=garage_title,
            summary="Garagenplatz zu vermieten.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/object?adId=1",
            title="Wohnung mit Balkon und optionalem Garagenplatz",
            summary="Helle Wohnung, Lift, Terrasse, Garagenplatz optional anmietbar.",
            property_facts={"property_type": "apartment"},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="office",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/immobilien/d/gewerbeimmobilien/buero",
            title="Bürofläche mit Balkon nahe U-Bahn",
            summary="Gewerbefläche mit Teeküche, Besprechungszimmern und Lift.",
            property_facts={"property_type": "office"},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="any",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is False
    )


def test_property_search_type_filter_supports_building_land() -> None:
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="land",
            property_url="https://www.willhaben.at/iad/object?adId=land-one",
            title="Baugrundstück mit Seezugang in Niederösterreich",
            summary="Bauland, aufgeschlossen, ruhige Lage.",
            property_facts={},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="land",
            property_url="https://www.willhaben.at/iad/object?adId=flat-one",
            title="Wohnung mit Garten und Balkon",
            summary="Helle Wohnung, kein Baugrund.",
            property_facts={"property_type": "apartment"},
        )
        is False
    )


def test_property_scout_listing_url_cache_reuses_provider_result_lists(monkeypatch) -> None:
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "memory")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", "")
    fetch_calls: list[str] = []

    def _fake_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        fetch_calls.append(url)
        return "<html>provider source</html>"

    def _fake_extract_listing_urls(
        *,
        source_url: str,
        html: str,
        source_spec: dict[str, object] | None = None,
    ) -> tuple[str, ...]:
        return (
            "https://www.willhaben.at/iad/object?adId=cache-1",
            "https://www.willhaben.at/iad/object?adId=cache-2",
        )

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(product_service, "_property_scout_extract_listing_urls", _fake_extract_listing_urls)
    source_spec = {
        "platform": "willhaben",
        "provider_cache_key": "willhaben:test-cache-key",
        "provider_filter_pushdown": {"cache_key": "willhaben:test-cache-key"},
    }

    first_urls, first_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
    )
    second_urls, second_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
    )
    refreshed_urls, refreshed_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
        force_refresh=True,
    )

    assert first_cache["status"] == "miss"
    assert second_cache["status"] == "hit"
    assert refreshed_cache["status"] == "refresh"
    assert first_urls == second_urls == refreshed_urls
    assert len(fetch_calls) == 2


def test_property_scout_listing_url_cache_persists_provider_result_lists(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")
    fetch_calls: list[str] = []

    def _fake_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        fetch_calls.append(url)
        return "<html>provider source</html>"

    def _fake_extract_listing_urls(
        *,
        source_url: str,
        html: str,
        source_spec: dict[str, object] | None = None,
    ) -> tuple[str, ...]:
        return (
            "https://www.willhaben.at/iad/object?adId=persist-1",
            "https://www.willhaben.at/iad/object?adId=persist-2",
        )

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(product_service, "_property_scout_extract_listing_urls", _fake_extract_listing_urls)
    source_spec = {
        "platform": "willhaben",
        "provider_cache_key": "willhaben:persistent-cache-key",
        "provider_filter_pushdown": {"cache_key": "willhaben:persistent-cache-key"},
    }

    first_urls, first_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=90",
        source_spec=source_spec,
    )
    assert first_cache["status"] == "miss"
    assert first_cache["persistence"] == "file"
    assert cache_path.exists()

    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0

    def _blocked_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        raise AssertionError("persistent provider-list cache should satisfy this request")

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _blocked_fetch_html)
    second_urls, second_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=90",
        source_spec=source_spec,
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert persisted["version"] == "property_source_listing_cache_v1"
    assert persisted["schema_version"] == 1
    assert persisted["entry_count"] == 1
    assert persisted["lock_strategy"] == "fcntl"
    assert "willhaben:persistent-cache-key" in persisted["entries"]
    assert cache_path.with_name(f"{cache_path.name}.lock").exists()
    assert second_cache["status"] == "hit"
    assert second_cache["persistence"] == "file"
    assert second_urls == first_urls
    assert len(fetch_calls) == 1


def test_property_scout_listing_url_cache_uses_source_fallback_when_provider_fetch_fails(monkeypatch) -> None:
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "memory")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", "")
    observed: dict[str, object] = {}

    def _blocked_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        observed["timeout_seconds"] = timeout_seconds
        raise TimeoutError("remax upstream timeout")

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _blocked_fetch_html)
    source_spec = {
        "platform": "remax_at",
        "provider_cache_key": "remax_at:fallback-cache-key",
        "provider_filter_pushdown": {"cache_key": "remax_at:fallback-cache-key"},
        "fetch_timeout_seconds": 8,
        "fallback_listing_urls": ["https://www.remax.at/de/ib/remax-first-wien/immobilien"],
    }

    urls, cache_state = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.remax.at/en/properties/propertysearch?q=Wien&minArea=35",
        source_spec=source_spec,
        force_refresh=True,
    )

    assert observed["timeout_seconds"] == 8
    assert urls == ("https://www.remax.at/de/ib/remax-first-wien/immobilien",)
    assert cache_state["status"] == "fallback"
    assert cache_state["fallback_reason"] == "source_fetch_failed"


def test_property_scout_listing_url_cache_merges_existing_persistent_entries(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": "property_source_listing_cache_v1",
                "entries": {
                    "willhaben:other-worker-key": {
                        "cache_key": "willhaben:other-worker-key",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=other",
                        "listing_urls": ["https://www.willhaben.at/iad/object?adId=other-1"],
                        "stored_at_epoch": time.time(),
                        "provider_filter_pushdown": {"cache_key": "willhaben:other-worker-key"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")

    product_service._property_source_listing_cache_put(
        "willhaben:this-worker-key",
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?q=this",
        listing_urls=("https://www.willhaben.at/iad/object?adId=this-1",),
        source_spec={"provider_filter_pushdown": {"cache_key": "willhaben:this-worker-key"}},
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "willhaben:other-worker-key" in persisted["entries"]
    assert "willhaben:this-worker-key" in persisted["entries"]
    assert persisted["entry_count"] == 2


def test_property_scout_listing_url_cache_quarantines_corrupt_persistent_snapshot(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text("{not valid json", encoding="utf-8")
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")

    product_service._property_source_listing_cache_put(
        "willhaben:recovered-cache-key",
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?q=recovered",
        listing_urls=("https://www.willhaben.at/iad/object?adId=recovered-1",),
        source_spec={"provider_filter_pushdown": {"cache_key": "willhaben:recovered-cache-key"}},
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    corrupt_files = sorted(tmp_path.glob("provider-listings.json.corrupt-*.json"))
    assert corrupt_files
    assert persisted["version"] == "property_source_listing_cache_v1"
    assert persisted["schema_version"] == 1
    assert persisted["lock_strategy"] == "fcntl"
    assert "willhaben:recovered-cache-key" in persisted["entries"]


def test_property_scout_listing_url_cache_rejects_overstale_persistent_fallback(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": "property_source_listing_cache_v1",
                "entries": {
                    "willhaben:old-cache-key": {
                        "cache_key": "willhaben:old-cache-key",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
                        "listing_urls": ["https://www.willhaben.at/iad/object?adId=old-1"],
                        "stored_at_epoch": time.time() - 3600,
                        "provider_filter_pushdown": {"cache_key": "willhaben:old-cache-key"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "1")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "60")

    cached_urls, cached_state = product_service._property_source_listing_cache_get(
        "willhaben:old-cache-key",
        allow_stale=True,
    )

    assert cached_urls == ()
    assert cached_state == {}


def test_hosted_property_tour_bundle_reuses_existing_manifest(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    title = "Reusable listing"
    listing_id = "reuse-1"
    property_url = "https://www.willhaben.at/iad/object?adId=reuse-1"
    variant_key = "layout_first"
    slug = product_service._hosted_property_tour_slug(
        title=title,
        listing_id=listing_id,
        property_url=property_url,
        variant_key=variant_key,
    )
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "floorplan-01.pdf").write_bytes(b"%PDF-1.4\n")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "creation_mode": "hosted_floorplan_tour",
                "scenes": [{"asset_relpath": "floorplan-01.pdf", "role": "floorplan"}],
            }
        ),
        encoding="utf-8",
    )

    def _blocked_download(*args, **kwargs) -> str:
        raise AssertionError("existing hosted tour should not download assets again")

    monkeypatch.setattr(product_service, "_download_public_tour_asset_with_type", _blocked_download)

    payload = product_service._write_hosted_floorplan_property_tour_bundle(
        principal_id="exec-reuse",
        title=title,
        listing_id=listing_id,
        property_url=property_url,
        variant_key=variant_key,
        floorplan_urls=("https://cdn.example.com/floorplan.pdf",),
        property_facts_json={},
        source_host="willhaben.at",
    )


def test_hosted_property_tour_bundle_splits_public_manifest_from_private_receipt(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    def _fake_download(url: str, target) -> str:
        target.write_bytes(b"%PDF-1.4\n")
        return "application/pdf"

    monkeypatch.setattr("app.product.property_tour_hosting._download_public_tour_asset_with_type", _fake_download)

    payload = product_service._write_hosted_floorplan_property_tour_bundle(
        principal_id="exec-private-tour",
        title="Private floorplan tour",
        listing_id="private-floorplan-1",
        property_url="https://www.willhaben.at/iad/object?adId=private-floorplan-1",
        variant_key="layout_first",
        floorplan_urls=("https://cdn.example.com/floorplan.pdf",),
        property_facts_json={
            "address_lines": ["1200 Wien"],
            "exact_address": "Private Street 1, 1200 Wien",
            "map_lat": 48.2,
            "map_lng": 16.3,
            "personal_fit_assessment": {
                "fit_score": 81,
                "good_fit_reasons": ["Strong layout signal"],
                "preference_nodes": [{"key": "private-node"}],
            },
            "public_preference_snapshot": {
                "profile": {"principal_id": "exec-private-tour"},
                "preference_nodes": [{"key": "prefer_balcony", "value_json": True}],
            },
        },
        source_host="willhaben.at",
        source_ref="property-scout:private-floorplan-1",
        external_id="ext-private-floorplan-1",
        recipient_email="anna@example.com",
    )

    bundle_dir = tmp_path / str(payload["slug"])
    public_manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    private_manifest = json.loads((bundle_dir / "tour.private.json").read_text(encoding="utf-8"))

    assert public_manifest["hosted_url"] == f"/tours/{payload['slug']}"
    assert "principal_id" not in public_manifest
    assert "recipient_email" not in public_manifest
    assert "source_ref" not in public_manifest
    assert "external_id" not in public_manifest
    assert "listing_url" not in public_manifest
    assert "property_url" not in public_manifest
    serialized_public_manifest = json.dumps(public_manifest, sort_keys=True)
    for private_marker in (
        "exec-private-tour",
        "anna@example.com",
        "property-scout:private-floorplan-1",
        "ext-private-floorplan-1",
        "Private Street 1",
        "source_url",
        "listing_url",
        "property_url",
        "map_lat",
        "map_lng",
        "public_preference_snapshot",
        "preference_nodes",
    ):
        assert private_marker not in serialized_public_manifest
    assert private_manifest["principal_id"] == "exec-private-tour"
    assert private_manifest["recipient_email"] == "anna@example.com"
    assert private_manifest["source_ref"] == "property-scout:private-floorplan-1"
    assert private_manifest["external_id"] == "ext-private-floorplan-1"


def test_hosted_property_tour_public_manifest_has_no_private_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    def _fake_download(url: str, target) -> str:
        target.write_bytes(b"%PDF-1.4\n")
        return "application/pdf"

    monkeypatch.setattr("app.product.property_tour_hosting._download_public_tour_asset_with_type", _fake_download)

    payload = product_service._write_hosted_floorplan_property_tour_bundle(
        principal_id="exec-manifest-safety",
        title="Manifest-safe floorplan tour",
        listing_id="safety-floorplan-1",
        property_url="https://www.willhaben.at/iad/object?adId=private-floorplan-2",
        variant_key="layout_first",
        floorplan_urls=("https://cdn.example.com/floorplan.pdf",),
        property_facts_json={
            "address_lines": ["1200 Wien"],
            "map_lat": 48.2,
            "map_lng": 16.3,
            "exact_address": "Private Street 12, 1200 Wien",
            "source_url": "https://www.willhaben.at/iad/object?adId=private-floorplan-2",
        },
        source_host="willhaben.at",
        source_ref="property-scout:private-floorplan-2",
        external_id="ext-private-floorplan-2",
        recipient_email="private@example.com",
    )

    bundle_dir = tmp_path / str(payload["slug"])
    public_manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    serialized_public_manifest = json.dumps(public_manifest, sort_keys=True)
    assert "brief" not in public_manifest
    for private_key in (
        "map_lat",
        "map_lng",
        "listing_url",
        "property_url",
        "source_url",
        "exact_address",
        "principal_id",
        "source_ref",
        "external_id",
        "private_recipient_email",
        "recipient_email",
        "public_preference_snapshot",
        "preference_nodes",
    ):
        assert private_key not in serialized_public_manifest


def test_hosted_live_provider_tour_manifest_keeps_safe_embed_without_private_listing_data(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    live_url = "https://my.matterport.com/show/?m=BmVWxvZQZLq"
    payload = product_service._write_hosted_feelestate_pure_360_property_tour_bundle(
        principal_id="exec-live-provider-private",
        title="Matterport writer coverage",
        listing_id="matterport-writer-1",
        property_url="https://www.willhaben.at/iad/object?adId=matterport-writer-1",
        variant_key="layout_first",
        source_virtual_tour_url=live_url,
        property_facts_json={
            "has_360": True,
            "exact_address": "Private Matterport Street 1, 1200 Wien",
            "map_lat": 48.2,
            "map_lng": 16.3,
        },
        source_host="willhaben.at",
        source_ref="property-scout:matterport-writer-1",
        external_id="ext-matterport-writer-1",
        recipient_email="owner@example.com",
    )

    bundle_dir = tmp_path / str(payload["slug"])
    public_manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    private_manifest = json.loads((bundle_dir / "tour.private.json").read_text(encoding="utf-8"))

    assert "source_virtual_tour_url" not in public_manifest
    assert "source_virtual_tour_origin" not in public_manifest
    assert "matterport_url" not in public_manifest
    assert public_manifest["control_mode"] == "matterport"
    assert public_manifest["scenes"][0]["role"] == "live_360"
    serialized_public_manifest = json.dumps(public_manifest, sort_keys=True)
    for private_marker in (
        "willhaben.at/iad/object",
        "exec-live-provider-private",
        "property-scout:matterport-writer-1",
        "ext-matterport-writer-1",
        "owner@example.com",
        "Private Matterport Street",
        "map_lat",
        "map_lng",
        "listing_url",
        "property_url",
        "source_ref",
        "external_id",
        "recipient_email",
    ):
        assert private_marker not in serialized_public_manifest
    assert private_manifest["property_url"].endswith("adId=matterport-writer-1")
    assert private_manifest["source_virtual_tour_url"] == live_url
    assert private_manifest["source_virtual_tour_origin"] == live_url
    assert private_manifest["matterport_url"] == live_url

    client = build_property_client(principal_id="exec-live-provider-page")
    page = client.get(f"/tours/{payload['slug']}", headers={"host": "propertyquarry.com"})
    assert page.status_code == 200, page.text
    assert live_url in page.text
    assert "Open Listing" not in page.text
    assert "Private Matterport Street" not in page.text


def test_hosted_property_tour_bundle_rejects_post_download_invalid_asset_suffix(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    def _fake_download(url: str, target) -> str:
        target.write_text("<html>not a floorplan</html>", encoding="utf-8")
        return "application/octet-stream"

    monkeypatch.setattr("app.product.property_tour_hosting._download_public_tour_asset_with_type", _fake_download)

    with pytest.raises(RuntimeError, match="floorplan_assets_unavailable"):
        product_service._write_hosted_floorplan_property_tour_bundle(
            principal_id="exec-invalid-floorplan-suffix",
            title="Bad floorplan asset",
            listing_id="bad-floorplan-1",
            property_url="https://www.willhaben.at/iad/object?adId=bad-floorplan-1",
            variant_key="layout_first",
            floorplan_urls=("https://cdn.example.com/floorplan.html",),
            property_facts_json={},
            source_host="willhaben.at",
        )


@pytest.mark.parametrize(
    ("asset_url", "content_type"),
    (
        ("https://cdn.example.com/floorplan.html", "text/html"),
        ("https://cdn.example.com/floorplan.zip", "application/octet-stream"),
        ("https://cdn.example.com/floorplan.json", "application/octet-stream"),
    ),
)
def test_hosted_property_tour_bundle_rejects_hostile_asset_suffix_after_content_type_detection(
    monkeypatch, tmp_path, asset_url, content_type
) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.com/tours")

    def _fake_download(url: str, target) -> str:
        target.write_text("<html>not a floorplan</html>", encoding="utf-8")
        return content_type

    monkeypatch.setattr("app.product.property_tour_hosting._download_public_tour_asset_with_type", _fake_download)

    with pytest.raises(RuntimeError, match="floorplan_assets_unavailable"):
        product_service._write_hosted_floorplan_property_tour_bundle(
            principal_id="exec-invalid-floorplan-suffix",
            title="Bad floorplan asset",
            listing_id="bad-floorplan-2",
            property_url="https://www.willhaben.at/iad/object?adId=bad-floorplan-2",
            variant_key="layout_first",
            floorplan_urls=(asset_url,),
            property_facts_json={},
            source_host="willhaben.at",
        )


def test_public_tour_asset_download_enforces_max_bytes(monkeypatch, tmp_path) -> None:
    class _FakeResponse:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/pdf", "Content-Length": "8"}
            self._chunks = [b"1234", b"5678"]

        def read(self, size: int = -1) -> bytes:
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setenv("PROPERTYQUARRY_TOUR_ASSET_MAX_BYTES", "4")
    monkeypatch.setattr("app.product.property_tour_hosting.urllib.request.urlopen", lambda *args, **kwargs: _FakeResponse())

    with pytest.raises(RuntimeError, match="tour_asset_too_large"):
        product_service._download_public_tour_asset_with_type(
            "https://cdn.example.com/floorplan.pdf",
            tmp_path / "floorplan.pdf",
        )


def test_property_alert_review_reuses_returned_review_packet() -> None:
    principal_id = "exec-property-review-packet-reuse"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Reuse Office")
    seed_product_state(client, principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    property_url = "https://www.willhaben.at/iad/object?adId=reuse-returned-1"

    first = service._open_property_alert_review(
        principal_id=principal_id,
        title="Reusable returned review flat",
        summary="A completed review packet should remain reusable.",
        source_ref="property-scout:reuse-returned-1",
        external_id=property_url,
        counterparty="Willhaben",
        account_email="",
        property_url=property_url,
        actor="test",
        notify_telegram=False,
        personal_fit_assessment={"fit_score": 76.0, "recommendation": "shortlist"},
        preference_person_id="self",
        tour_url="https://propertyquarry.com/tours/reuse-returned-1",
    )
    task_id = str(first["human_task_id"]).split(":", 1)[1]
    returned = client.app.state.container.orchestrator.return_human_task(
        task_id,
        principal_id=principal_id,
        operator_id="operator-office",
        resolution="reviewed",
        returned_payload_json={"resolution": "reviewed"},
        provenance_json={"source": "test"},
    )
    assert returned is not None
    assert returned.status == "returned"

    second = service._open_property_alert_review(
        principal_id=principal_id,
        title="Reusable returned review flat",
        summary="Same listing in a later search.",
        source_ref="property-scout:reuse-returned-1",
        external_id=property_url,
        counterparty="Willhaben",
        account_email="",
        property_url=property_url,
        actor="test",
        notify_telegram=False,
        personal_fit_assessment={"fit_score": 78.0, "recommendation": "shortlist"},
        preference_person_id="self",
        tour_url="https://propertyquarry.com/tours/reuse-returned-1-refresh",
    )

    all_reviews = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]
    assert second["status"] == "existing"
    assert second["human_task_id"] == first["human_task_id"]
    assert second["review_task_status"] == "returned"
    assert second["review_reused"] is True
    assert second["tour_url"] == "https://propertyquarry.com/tours/reuse-returned-1-refresh"
    assert len(all_reviews) == 1
    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_reused"})
    assert events.status_code == 200
    reused_events = [
        item
        for item in events.json()["items"]
        if item["payload"]["human_task_id"] == first["human_task_id"]
    ]
    assert reused_events
    assert reused_events[0]["payload"]["review_task_status"] == "returned"


def test_property_alert_review_suppresses_candidate_outside_active_location() -> None:
    principal_id = "exec-property-alert-location-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Location Gate Office")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "flatbee"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Familienfreundliche 3-Zimmer-Wohnung im Zentrum von Gmunden",
        summary="Provider result was queried from a Vienna source scope.",
        source_ref="property-scout:https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
        external_id="flatbee-gmunden",
        counterparty="Flatbee",
        account_email="",
        property_url="https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
                "listing_title": "Familienfreundliche 3-Zimmer-Wohnung im Zentrum von Gmunden - Oberösterreich - 4810",
                "property_facts_json": {"postal_name": "4810 Gmunden", "source_scope_location": "Wien", "source_city": "Wien"},
            },
        ),
        personal_fit_assessment={"fit_score": 92.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert not [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]
    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_suppressed_location_mismatch"})
    assert events.status_code == 200
    assert any("Gmunden" in str(item["payload"]) for item in events.json()["items"])


def test_property_alert_review_suppresses_candidate_outside_selected_district_even_when_location_query_is_broad(monkeypatch) -> None:
    principal_id = "exec-property-alert-selected-district-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review District Gate Office")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["derstandard_at"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service.ProductService,
        "_fetch_property_provider_repair_snapshot",
        lambda self, *, property_url: {},
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Wohnung mieten in 1200 Wien, Brigittenau | 81.98 m² | 3 Zimmer | EUR 1.649",
        summary="Provider result was queried from a selected 1010 source scope.",
        source_ref="property-scout:https://immobilien.derstandard.at/detail/1200-brigittenau",
        external_id="derstandard-1200",
        counterparty="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://immobilien.derstandard.at/detail/1200-brigittenau",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://immobilien.derstandard.at/detail/1200-brigittenau",
                "listing_title": "Wohnung mieten in 1200 Wien, Brigittenau | 81.98 m² | 3 Zimmer | EUR 1.649",
                "summary": "Stilvolle 3-Zimmer-Wohnung mit Garten & Terrasse im 20. Bezirk.",
                "property_facts_json": {
                    "postal_name": "1200 Wien",
                    "source_scope_location": "1010 Vienna",
                    "source_city": "Vienna",
                },
            },
        ),
        personal_fit_assessment={"fit_score": 92.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert dict(result["repair_task"])["task_type"] == "property_provider_repair_ooda"
    assert dict(result["repair_task"])["filter_key"] == "location_scope"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    repair_input = dict(repair_tasks[0].input_json or {})
    assert repair_input["filter_key"] == "location_scope"
    assert dict(repair_input["diagnostics"])["postal_name"] == "1200 Wien"
    assert dict(repair_input["diagnostics"])["location_hints"] == ["1010 Vienna"]


def test_property_alert_review_accepts_search_run_candidate_inside_adjacent_area_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-alert-adjacent-radius-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Adjacent Radius Gate Office")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_districts": ["1010 Vienna"],
            "adjacent_area_radius_m": 200,
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    boundary_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [16.3600, 48.2000],
            [16.3700, 48.2000],
            [16.3700, 48.2100],
            [16.3600, 48.2100],
            [16.3600, 48.2000],
        ]],
    }
    monkeypatch.setattr(
        product_service,
        "_property_research_boundary_record",
        lambda query: {
            "display_name": query,
            "geojson": boundary_geojson,
            "bounds": (16.3600, 48.2000, 16.3700, 48.2100),
            "lat": 48.2050,
            "lon": 16.3650,
        },
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_fetch_property_provider_repair_snapshot",
        lambda self, *, property_url: pytest.fail("adjacent-radius match must not open provider repair"),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Wohnung mieten in 1200 Wien | 70 m² | 3 Zimmer | EUR 1.450",
        summary="Listing text is outside 1010 but the map point sits just over the selected-area boundary.",
        source_ref="property-scout:adjacent-radius-1200",
        external_id="willhaben-adjacent-radius-1200",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1200-brigittenau/adjacent-radius/",
        actor="test",
        notify_telegram=False,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1200-brigittenau/adjacent-radius/",
                "listing_title": "Wohnung mieten in 1200 Wien | 70 m² | 3 Zimmer | EUR 1.450",
                "summary": "Helle Wohnung in 1200 Wien, knapp neben dem Suchgebiet.",
                "property_facts_json": {
                    "postal_name": "1200 Wien",
                    "map_lat": 48.2050,
                    "map_lng": 16.3714,
                    "source_scope_location": "1010 Vienna",
                    "source_city": "Vienna",
                },
            },
        ),
        personal_fit_assessment={"fit_score": 92.0, "recommendation": "shortlist"},
        preference_person_id="self",
        requested_location_hints=("1010 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
    )

    assert result["status"] == "opened"
    assert result.get("reason") != "property_location_conflicts_with_active_search"
    assert [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]


def test_property_alert_review_suppresses_salzburg_listing_under_vienna_source_scope(monkeypatch) -> None:
    principal_id = "exec-property-alert-salzburg-source-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Salzburg Source Scope Guard")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("Salzburg listing under 1010 source scope must not notify"),
    )
    monkeypatch.setattr(
        product_service.ProductService,
        "_fetch_property_provider_repair_snapshot",
        lambda self, *, property_url: {},
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse in Salzburg",
        summary="Moderne schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich in Salzburg Stadt.",
        source_ref="property-scout:https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
        external_id="willhaben-salzburg-source-scope",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
                "listing_title": "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse in Salzburg",
                "summary": "Moderne Zwei-Zimmer Wohnung mit Terrasse in Salzburg Stadt.",
                "source_platform": "willhaben",
                "source_family": "core_portal",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "EUR 1.190",
                },
            },
        ),
        personal_fit_assessment={"fit_score": 88.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    repair_input = dict(repair_tasks[0].input_json or {})
    assert repair_input["filter_key"] == "location_scope"
    diagnostics = dict(repair_input["diagnostics"])
    assert diagnostics["location_evidence_kind"] in {"url_region", "listing_concrete", "listing_postal"}
    assert diagnostics["postal_name"] != "1010 Vienna"
    assert "Salzburg" in diagnostics["summary"] or "Salzburg" in diagnostics["title"]


def test_property_alert_review_suppresses_low_score_telegram_even_when_review_opens(monkeypatch) -> None:
    principal_id = "exec-property-alert-low-score-telegram-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Low Score Telegram Gate")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setenv("PROPERTYQUARRY_SCOUT_OUTBOUND_MIN_SCORE", "60")
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("low-score review must not notify")),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Wohnung mieten in 1010 Wien | 60 m² | 2 Zimmer | EUR 1.090",
        summary="2-Zimmer Wohnung im 1. Bezirk, 60 m2, Gesamtmiete EUR 1.090.",
        source_ref="property-scout:review-low-score-1010",
        external_id="review-low-score-1010",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/review-low-score/",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/review-low-score/",
                "listing_title": "Wohnung mieten in 1010 Wien | 60 m² | 2 Zimmer | EUR 1.090",
                "summary": "2-Zimmer Wohnung im 1. Bezirk, 60 m2, Gesamtmiete EUR 1.090.",
                "property_facts_json": {
                    "postal_name": "1010 Wien",
                    "street_address": "Kärntner Straße 12, 1010 Wien",
                    "area_sqm": 60,
                    "rooms": 2,
                    "total_rent_eur": 1090,
                },
            },
        ),
        personal_fit_assessment={"fit_score": 50.0, "recommendation": "review"},
        preference_person_id="self",
    )

    assert result["status"] == "opened"
    assert result["telegram_delivery_status"] == "suppressed"
    assert result["telegram_delivery_error"] == "fit_below_outbound_threshold"
    assert result["telegram_min_score"] == 60.0
    events = client.get(
        "/app/api/events",
        params={"channel": "product", "event_type": "property_alert_review_telegram_suppressed"},
    )
    assert events.status_code == 200
    assert any(dict(item["payload"]).get("reason") == "fit_below_outbound_threshold" for item in events.json()["items"])


def test_property_alert_review_uses_exact_source_scope_when_saved_location_is_missing(monkeypatch) -> None:
    principal_id = "exec-property-alert-source-scope-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Source Scope Fallback Office")
    seed_product_state(client, principal_id=principal_id)
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("outside-source-scope alert must not notify")),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich",
        summary="Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
        source_ref="gmail-thread:willhaben:salzburg-returned-from-1010",
        external_id="gmail-message:willhaben:salzburg-returned-from-1010",
        counterparty="Willhaben | Austria | Rent | 1010 Vienna",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/demo-1631373932/",
                "listing_title": "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich",
                "summary": "Wählen Sie aus 113.217 Angeboten. Immobilien suchen und finden auf willhaben.",
                "property_facts_json": {
                    "postal_name": "1010 Vienna",
                    "source_scope_location": "1010 Vienna",
                    "source_postal_code": "1010",
                    "source_city": "Vienna",
                    "price_display": "EUR 1.190",
                },
            },
        ),
        personal_fit_assessment={"fit_score": 92.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert result["location_hints"] == ["1010 Vienna"]
    assert result["source_scope_location_hints"] == ["1010 Vienna"]
    assert not [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]


def test_property_alert_review_exact_source_scope_fallback_applies_to_non_vienna_postcodes() -> None:
    principal_id = "exec-property-alert-source-scope-all-postals"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Source Scope All Postals")
    seed_product_state(client, principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Moderne Wohnung mit Loggia",
        summary="Provider result was queried from a selected Graz source scope.",
        source_ref="gmail-thread:willhaben:linz-returned-from-8055",
        external_id="gmail-message:willhaben:linz-returned-from-8055",
        counterparty="Willhaben | Austria | Rent | 8055 Graz",
        account_email="",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/linz/demo-dirty-scope/",
        actor="test",
        notify_telegram=False,
        candidate_properties=(
            {
                "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/linz/demo-dirty-scope/",
                "listing_title": "Moderne Wohnung mit Loggia",
                "summary": "Moderne Wohnung mit Loggia und heller Küche.",
                "property_facts_json": {
                    "postal_name": "8055 Graz",
                    "source_scope_location": "8055 Graz",
                    "source_postal_code": "8055",
                    "source_city": "Graz",
                },
            },
        ),
        personal_fit_assessment={"fit_score": 88.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert result["location_hints"] == ["8055 Graz"]


def test_property_search_run_status_reconstructs_missing_status_url() -> None:
    principal_id = "exec-property-search-missing-status-url"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"legacy-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "in_progress",
            "status_url": "",
            "selected_platforms": ["willhaben"],
            "progress": 25,
            "current_step": "source_started",
            "message": "Scanning source.",
            "stages_total": 4,
            "steps_completed": 1,
            "summary": {"sources_total": 1},
            "events": [],
            "property_search_preferences": {},
        }

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status_url"] == f"/app/api/signals/property/search/run/{run_id}"


def test_property_search_run_progress_stays_monotonic_when_stage_totals_expand() -> None:
    principal_id = "exec-property-search-progress-monotonic"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"progress-{uuid.uuid4().hex}"
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["willhaben"],
            "progress": 41,
            "current_step": "source_previewing",
            "message": "Reviewing candidate 4 of 31.",
            "stages_total": 120,
            "steps_completed": 49,
            "summary": {
                "sources_total": 10,
                "sources": [{"source_label": f"Source {index}"} for index in range(4)],
            },
            "events": [],
            "property_search_preferences": {},
            "eta_seconds": 0,
            "eta_label": "",
            "eta_seconds_smoothed": 0,
        }

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="source_extracting",
        message="Extracting listing candidates from the next source.",
        status="in_progress",
        steps_delta=1,
        summary_updates={"sources_total": 10},
        stages_total_override=220,
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status is not None
    assert int(status["progress"]) >= 41
    assert str(status.get("eta_label") or "").startswith("about") or str(status.get("eta_label") or "").startswith("under")


def test_property_search_run_status_synthesizes_ranked_candidates_and_filtered_totals_from_sources() -> None:
    principal_id = "exec-property-search-synthesized-shortlist"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"synth-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "processed",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["immoscout_de"],
            "progress": 100,
            "current_step": "completed",
            "message": "The final results email was sent. Refreshing this page will continue to show the completed result desk.",
            "stages_total": 4,
            "steps_completed": 4,
            "summary": {
                "sources_total": 1,
                "raw_listing_total": 1,
                "filtered_low_fit_total": 5,
                "sources": [
                    {
                        "source_label": "ImmoScout24 Germany",
                        "status": "processed",
                        "raw_listing_total": 12,
                        "reviewed_listing_total": 11,
                        "location_mismatch_candidate_total": 3,
                        "top_candidates": [
                            {
                                "title": "Altbau near U6",
                                "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
                                "fit_score": 92,
                                "fit_summary": "Personal fit 92/100",
                                "property_facts": {
                                    "price_display": "EUR 420,000",
                                    "area_m2": 78,
                                },
                            }
                        ],
                    }
                ],
            },
            "events": [
                {
                    "step": "results_email_sent",
                    "message": "The final results email was sent. Refreshing this page will continue to show the completed result desk.",
                    "status": "processed",
                }
            ],
            "property_search_preferences": {},
        }

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["message"] == "The final results email was sent. The completed result desk is ready."
    assert dict(list(status.get("events") or [])[0])["message"] == "The final results email was sent. The completed result desk is ready."
    summary = dict(status.get("summary") or {})
    assert int(summary.get("held_back_total") or 0) == 0
    assert int(summary.get("filtered_total") or 0) == 0
    assert int(summary.get("filtered_low_fit_total") or 0) == 5
    assert int(summary.get("raw_listing_total") or 0) == 12
    assert int(summary.get("scanned_listing_total") or 0) == 11
    assert int(summary.get("location_mismatch_candidate_total") or 0) == 3
    ranked = [dict(row) for row in list(summary.get("ranked_candidates") or []) if isinstance(row, dict)]
    assert len(ranked) == 1
    assert ranked[0]["title"] == "Altbau near U6"


def test_property_search_run_status_rederives_ranked_candidates_from_source_scope_rows(monkeypatch) -> None:
    principal_id = "exec-property-search-rerank-source-scope"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"rerank-source-scope-{uuid.uuid4().hex}"
    source_row = {
        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
        "source_scope_label": "Willhaben | Austria | Rent | 1010 Vienna",
        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1010+Vienna",
        "status": "processed",
        "top_candidates": [
            {
                "source_ref": "outside-scope",
                "title": "Terrassenwohnung auf der Hohen Warte, 66 m2, EUR 1.599, (1190 Wien)",
                "property_url": "https://example.test/1190",
                "fit_score": 98,
                "property_facts": {
                    "postal_name": "1190 Wien",
                    "source_scope_location": "1010 Vienna",
                    "listing_postal_evidence": [{"postal_code": "1190", "postal_name": "1190 Wien"}],
                },
            },
            {
                "source_ref": "inside-scope",
                "title": "Wohnung mieten in 1010 Wien | 70 m2 | 2 Zimmer",
                "property_url": "https://example.test/1010",
                "fit_score": 77,
                "property_facts": {
                    "postal_name": "1010 Wien",
                    "source_scope_location": "1010 Vienna",
                    "listing_postal_evidence": [{"postal_code": "1010", "postal_name": "1010 Wien"}],
                },
            },
        ],
    }
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "completed_partial",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["willhaben"],
            "progress": 100,
            "current_step": "processed",
            "message": "Current shortlist is still available.",
            "summary": {
                "sources_total": 1,
                "ranked_candidates": [dict(source_row["top_candidates"][0])],
                "sources": [source_row],
            },
            "events": [],
            "property_search_preferences": {},
        }
    monkeypatch.setattr(service, "persist_property_saved_shortlist_candidates", lambda **kwargs: None)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    ranked = [
        dict(row)
        for row in list(dict(status.get("summary") or {}).get("ranked_candidates") or [])
        if isinstance(row, dict)
    ]
    assert [row["source_ref"] for row in ranked] == ["inside-scope"]
    assert ranked[0]["rank"] == 1


def test_property_search_run_status_skips_provider_repair_task_scan_for_terminal_runs(monkeypatch) -> None:
    principal_id = "exec-property-search-terminal-skip-repairs"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"terminal-skip-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "completed_partial",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["kalandra"],
            "progress": 100,
            "current_step": "run_interrupted",
            "message": "Current shortlist is still available.",
            "stages_total": 10,
            "steps_completed": 10,
            "summary": {
                "sources_total": 2,
                "ranked_candidates": [
                    {
                        "candidate_ref": "cand-1",
                        "title": "Ranked One",
                        "property_url": "https://example.test/listing/1",
                        "fit_score": 61,
                    }
                ],
                "sources": [
                    {
                        "source_label": "Source One",
                        "status": "failed",
                        "source_url": "https://example.test/source/1",
                        "top_candidates": [],
                    }
                ],
            },
            "events": [],
            "property_search_preferences": {},
        }

    monkeypatch.setattr(
        client.app.state.container.orchestrator,
        "list_human_tasks",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal runs should not scan provider repair tasks")),
    )
    monkeypatch.setattr(service, "persist_property_saved_shortlist_candidates", lambda **kwargs: None)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status"] == "completed_partial"
    assert len(list((status.get("summary") or {}).get("ranked_candidates") or [])) == 1


def test_property_search_run_status_api_synthesizes_ranked_candidates_from_source_rows(monkeypatch) -> None:
    principal_id = "exec-property-search-status-api-synth"
    os.environ["EA_API_TOKEN"] = ""
    client = build_property_client(principal_id=principal_id)
    top_candidates = [
        {
            "title": f"Altbau near U6 #{index}",
            "property_url": f"https://www.immobilienscout24.de/expose/altbau-u6-{index}",
            "fit_score": 200 - index,
        }
        for index in range(60)
    ]

    def _fake_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "exec-property-search-status-api-synth"
        assert run_id == "run-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "processed",
            "progress": 100,
            "summary": {
                "sources_total": 1,
                "filtered_low_fit_total": 7,
                "sources": [
                    {
                        "source_label": "ImmoScout24 Germany",
                        "status": "processed",
                        "top_candidates": top_candidates,
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_status)

    response = client.get("/app/api/signals/property/search/run/run-42")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert int(payload["summary"].get("held_back_total") or 0) == 0
    assert int(payload["summary"].get("filtered_total") or 0) == 0
    assert int(payload["summary"].get("filtered_low_fit_total") or 0) == 7
    ranked = [dict(row) for row in list(payload["summary"].get("ranked_candidates") or []) if isinstance(row, dict)]
    assert len(ranked) == 60
    assert ranked[0]["title"] == "Altbau near U6 #0"
    assert ranked[-1]["title"] == "Altbau near U6 #59"
    assert ranked[-1]["rank"] == 60


def test_property_search_run_status_api_accepts_lightweight_query(monkeypatch) -> None:
    principal_id = "exec-property-search-status-api-lightweight"
    os.environ["EA_API_TOKEN"] = ""
    client = build_property_client(principal_id=principal_id)
    calls: list[bool] = []

    def _fake_status(self, *, principal_id: str, run_id: str, lightweight: bool = False):
        assert principal_id == "exec-property-search-status-api-lightweight"
        assert run_id == "run-light"
        calls.append(lightweight)
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "progress": 42,
            "summary": {"sources_total": 2},
            "events": [],
            "selected_platforms": ["willhaben"],
            "updated_at": "2026-06-23T12:00:00+00:00",
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_status)

    response = client.get("/app/api/signals/property/search/run/run-light?lightweight=1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == [True]
    assert body["generated_at"] == "2026-06-23T12:00:00+00:00"
    assert body["summary"]["sources_total"] == 2


def test_property_search_run_progress_records_sources_completed_and_eta_summary() -> None:
    principal_id = "exec-property-search-progress-eta"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"progress-{uuid.uuid4().hex}"
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=18)).isoformat()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["immowelt_at"],
            "progress": 0,
            "current_step": "sources_resolved",
            "message": "Resolved 6 provider(s) for scanning.",
            "stages_total": 120,
            "steps_completed": 2,
            "summary": {
                "sources_total": 6,
                "sources": [{"source_label": "Source A"}, {"source_label": "Source B"}],
            },
            "events": [],
            "property_search_preferences": {},
            "eta_seconds": 0,
            "eta_label": "",
            "eta_seconds_smoothed": 0,
        }

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="source_assessing",
        message="Enriching top 6 candidate(s) out of 31 for immowelt Austria.",
        status="in_progress",
        steps_delta=1,
        summary_updates={"sources_total": 6},
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status is not None
    assert int(status["summary"]["sources_completed"]) == 2
    assert int(status["summary"]["eta_seconds"]) > 0
    assert str(status["summary"]["eta_label"])


def test_property_search_run_surfaces_and_updates_missing_fact_research_tasks() -> None:
    principal_id = "exec-property-search-research-queue"
    client = build_property_client(principal_id=principal_id)
    run_id = f"research-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "in_progress",
            "status_url": "",
            "selected_platforms": ["justiz_edikte_at"],
            "progress": 65,
            "current_step": "source_review_packet",
            "message": "Preparing review packets.",
            "stages_total": 8,
            "steps_completed": 5,
            "summary": {
                "sources_total": 1,
                "sources": [
                    {
                        "source_label": "Justiz Edikte Auctions",
                        "top_candidates": [
                            {
                                "source_ref": "property-scout:auction-1",
                                "property_url": "https://edikte2.justiz.gv.at/example",
                                "title": "Auction apartment with floorplan",
                                "fit_score": 72.0,
                                "review_url": "/app/handoffs/human_task:auction-review",
                                "property_facts": {
                                    "has_floorplan": True,
                                    "missing_fact_research": {
                                        "status": "queued",
                                        "updated_at": "2026-06-06T01:00:00+00:00",
                                        "items": [
                                            {
                                                "field": "rooms",
                                                "label": "Rooms",
                                                "status": "research_needed",
                                                "display_value": "Rooms under research",
                                                "evidence": "Floorplan exists but no structured room count.",
                                                "ooda": {
                                                    "observe": "Room count is missing.",
                                                    "act": "Parse the downloadable floorplan bundle.",
                                                },
                                                "next_actions": ["Parse ZIP/PDF bundle.", "Run floorplan OCR."],
                                            }
                                        ],
                                    },
                                },
                            }
                        ],
                    }
                ],
            },
            "events": [],
            "property_search_preferences": {},
        }

    status = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["research_task_total"] == 1
    assert body["open_research_task_total"] == 1
    task = body["research_tasks"][0]
    assert task["field"] == "rooms"
    assert task["priority"] == "high"
    assert task["status"] == "queued"
    assert task["review_url"] == "/app/handoffs/human_task:auction-review"

    filled = client.post(
        f"/app/api/signals/property/search/run/{run_id}/research-tasks/{task['task_id']}",
        json={"action": "fill", "value": "4 rooms", "note": "Read from the valuation PDF."},
    )
    assert filled.status_code == 200, filled.text
    updated = filled.json()
    assert updated["filled_research_task_total"] == 1
    assert updated["open_research_task_total"] == 0
    updated_task = updated["research_tasks"][0]
    assert updated_task["status"] == "filled"
    assert updated_task["display_value"] == "4 rooms"
    assert updated_task["owner_note"] == "Read from the valuation PDF."
    assert any(event["step"] == "research_task_updated" for event in updated["events"])


def test_property_alert_personal_fit_snapshot_times_out_fast(monkeypatch) -> None:
    class _Profiles:
        def assess_candidate(self, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.2)
            return {"fit_score": 50}

    monkeypatch.setenv("EA_PROPERTY_ALERT_ASSESSMENT_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(
        product_service,
        "_property_alert_facts_for_url",
        lambda url: ({"postal_name": "1200 Wien"}, "listing-1"),
    )

    assessment, facts, listing_id = _property_alert_personal_fit_snapshot(
        preference_profiles=_Profiles(),
        principal_id="exec-timeout",
        person_id="self",
        property_url="https://www.willhaben.at/iad/object?adId=1",
    )

    assert assessment is None
    assert facts == {}
    assert listing_id == ""


def test_property_candidate_supports_live_tour_detects_360() -> None:
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"has_360": True}}
    ) is True
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"source_virtual_tour_url": "https://example.com/tour"}}
    ) is True
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"has_floorplan": True}}
    ) is False
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"has_360": False}}
    ) is False


def test_property_candidate_supports_live_tour_rejects_willhaben_tracking_endpoint() -> None:
    assert product_service._property_candidate_supports_live_tour(
        {
            "property_facts": {
                "has_360": True,
                "source_virtual_tour_url": "https://api.willhaben.at/restapi/v2/logevent/atz/1134225012/virtual-tour-link-clicked",
            }
        }
    ) is True
    assert product_service._safe_provider_live_360_url(
        "https://api.willhaben.at/restapi/v2/logevent/atz/1134225012/virtual-tour-link-clicked"
    ) == ""


def test_willhaben_packet_source_virtual_tour_url_falls_back_to_attribute_map_links() -> None:
    packet = {
        "property_facts_json": {
            "attribute_map": {
                "INFOLINK/NAME": ["3D Rundgang"],
                "INFOLINK/URL": ["https://my.matterport.com/show/?m=BmVWxvZQZLq"],
                "VIRTUAL_VIEW_LINK/URL": ["https://my.matterport.com/show/?m=BmVWxvZQZLq"],
            }
        }
    }

    assert (
        product_service._willhaben_packet_source_virtual_tour_url(packet)
        == "https://my.matterport.com/show/?m=BmVWxvZQZLq"
    )


def test_willhaben_packet_source_virtual_tour_url_rejects_tracking_link() -> None:
    packet = {
        "source_virtual_tour_url": "https://api.willhaben.at/restapi/v2/logevent/atz/1134225012/virtual-tour-link-clicked",
        "property_facts_json": {
            "source_virtual_tour_url": "https://api.willhaben.at/restapi/v2/logevent/atz/1134225012/virtual-tour-link-clicked",
        },
    }

    assert product_service._willhaben_packet_source_virtual_tour_url(packet) == ""


def test_property_search_run_starts_with_explicit_platform_and_tracks_progress(monkeypatch) -> None:
    principal_id = "exec-property-search-run-explicit"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Office")
    seed_product_state(client, principal_id=principal_id)

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["principal_id"] = principal_id
        observed["actor"] = actor
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        observed["force_refresh"] = bool(force_refresh)
        observed["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mock scout step",
                status="in_progress",
                steps_delta=2,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
                    "source_label": "Willhaben Rentals",
                    "preference_person_id": "self",
                    "listing_total": 1,
                    "review_created_total": 1,
                    "review_existing_total": 0,
                    "notified_total": 0,
                    "tour_created_total": 0,
                    "tour_existing_total": 0,
                    "high_fit_total": 0,
                    "watch_notified_total": 0,
                    "top_fit_score": 0.0,
                }
            ],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"preference_person_id": "elisabeth", "min_match_score": 80, "require_floorplan": True},
            "force_refresh": True,
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text

    started_body = started.json()
    run_id = started_body["run_id"]
    assert run_id
    assert started_body["selected_platforms"] == ["willhaben"]
    assert started_body["status_url"] == f"/app/api/signals/property/search/run/{run_id}"

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1
    assert status["steps_completed"] > 0
    assert status["progress"] >= 0
    assert status["principal_id"] == principal_id
    assert observed["selected_platforms"] == ("willhaben",)
    assert observed["force_refresh"] is True
    assert observed["max_results_per_source"] == 2
    assert observed["property_search_preferences"]["preference_person_id"] == "elisabeth"
    assert observed["property_search_preferences"]["min_match_score"] == 35.0
    assert observed["property_search_preferences"]["require_floorplan"] is True


def test_property_search_run_api_passes_normalized_merged_preferences_to_worker(monkeypatch) -> None:
    principal_id = "exec-property-search-run-normalized-merged"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Normalization Office")
    seed_product_state(client, principal_id=principal_id)

    saved = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "property_type": ["apartment"],
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
        },
    )
    assert saved.status_code == 200, saved.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 0,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {
                "property_type": ["land"],
                "require_floorplan": True,
                "require_energy_certificate": True,
                "require_operating_cost_statement": True,
                "investment_require_floorplan": True,
                "require_barrier_free": True,
                "min_rooms": 4,
                "keywords": "lift, balcony, playground nearby",
                "avoid_keywords": "barrier-free",
                "keyword_preferences": {
                    "lift": "must_have",
                    "barrier-free": "avoid",
                    "playground nearby": "nice_to_have_1km",
                },
            },
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text

    status = _poll_property_search_run_status(client, started.json()["run_id"])
    assert status["status"] == "processed"

    payload = dict(observed["property_search_preferences"])
    assert observed["selected_platforms"] == ("willhaben",)
    assert payload["property_type"] == ["land"]
    assert payload["require_floorplan"] is False
    assert payload["require_energy_certificate"] is False
    assert payload["require_operating_cost_statement"] is False
    assert payload["investment_require_floorplan"] is False
    assert payload["require_barrier_free"] is False
    assert "min_rooms" not in payload
    assert payload["keywords"] == ""
    assert payload["avoid_keywords"] == ""
    assert payload["keyword_preferences"] == {"playground nearby": "nice_to_have_1km"}


def test_property_search_run_greenfield_api_wraps_legacy_signal_contract(monkeypatch) -> None:
    principal_id = "exec-property-search-run-greenfield-api"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Greenfield API")

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        if callable(progress_callback):
            progress_callback(
                step="sources_resolved",
                message="Resolved sources for greenfield API.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "email_notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"country_code": "AT", "min_area_m2": 80},
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text
    body = started.json()
    run_id = body["run_id"]
    assert body["status_url"] == f"/app/api/property/search-runs/{run_id}"

    latest: dict[str, object] = {}
    for _ in range(120):
        status = client.get(f"/app/api/property/search-runs/{run_id}")
        assert status.status_code == 200, status.text
        latest = status.json()
        if latest["status"] == "processed":
            break
        time.sleep(0.02)
    assert latest["status"] == "processed"
    assert latest["status_url"] == f"/app/api/property/search-runs/{run_id}"

    events = client.get(f"/app/api/property/search-runs/{run_id}/events")
    assert events.status_code == 200, events.text
    events_body = events.json()
    assert events_body["run_id"] == run_id
    assert events_body["status_url"] == f"/app/api/property/search-runs/{run_id}"
    assert any(item["step"] == "sources_resolved" for item in events_body["events"])

    legacy_status = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert legacy_status.status_code == 200, legacy_status.text
    assert legacy_status.json()["status_url"] == f"/app/api/signals/property/search/run/{run_id}"


def test_property_search_run_worker_preserves_provider_repair_receipts_before_terminal(monkeypatch) -> None:
    principal_id = "exec-property-search-run-repair-before-terminal"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Repair Worker Office")

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        if callable(progress_callback):
            progress_callback(
                step="source_repair_needed",
                message="Provider returned a repairable extraction issue.",
                status="in_progress",
                steps_delta=1,
                summary_updates={
                    "sources_total": 1,
                    "sources": [
                        {
                            "source_url": "https://provider.example/search",
                            "source_label": "Provider Example",
                            "provider_repair_task_opened_total": 1,
                            "provider_repair_tasks": [{"status": "pending", "filter_key": "missing_price"}],
                        }
                    ],
                },
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "email_notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_url": "https://provider.example/search",
                    "source_label": "Provider Example",
                    "provider_repair_task_opened_total": 1,
                    "provider_repair_tasks": [{"status": "pending", "filter_key": "missing_price"}],
                }
            ],
        }

    def _fake_process_property_provider_repair_tasks(self, *, principal_id: str, actor: str, limit: int = 40) -> dict[str, object]:
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            active = [
                state
                for state in product_service._PROPERTY_SEARCH_RUN_REGISTRY.values()
                if isinstance(state, dict)
                and str(state.get("principal_id") or "").strip() == principal_id
                and str(state.get("status") or "").strip().lower() == "in_progress"
            ]
            assert active
            state = active[-1]
            summary = dict(state.get("summary") or {})
            summary["repair_receipts"] = [
                {
                    "at": product_service._now_iso(),
                    "run_id": state["run_id"],
                    "source_url": "https://provider.example/search",
                    "source_label": "Provider Example",
                    "filter_key": "missing_price",
                    "resolution": "suppressed_missing_price",
                    "reason": "provider page still lacks a concrete price",
                    "actor": actor,
                    "human_task_id": "human_task:repair-before-terminal",
                    "repair_workflow": "ea_provider_ooda",
                }
            ]
            summary["repair_resolved_total"] = 1
            state["summary"] = summary
        return {"generated_at": product_service._now_iso(), "resolved_total": 1, "deferred_total": 0, "resolved": []}

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)
    monkeypatch.setattr(ProductService, "process_property_provider_repair_tasks", _fake_process_property_provider_repair_tasks)

    started = client.post(
        "/app/api/property/search-runs",
        json={"selected_platforms": ["willhaben"], "property_preferences": {"country_code": "AT"}},
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)

    assert status["status"] == "processed"
    summary = dict(status["summary"])
    assert summary["repair_resolved_total"] == 1
    source = dict(summary["sources"][0])
    assert source["repair_status"] == "returned"
    assert source["provider_repair_tasks"][0]["status"] == "returned"
    assert source["provider_repair_tasks"][0]["resolution"] == "suppressed_missing_price"


def test_property_provider_greenfield_api_returns_country_scoped_catalog() -> None:
    client = build_property_client(principal_id="exec-property-provider-greenfield-api")

    at_response = client.get("/app/api/property/providers", params={"country": "AT"})
    uk_response = client.get("/app/api/property/providers", params={"country": "UK"})
    cr_response = client.get("/app/api/property/providers", params={"country": "CR"})

    assert at_response.status_code == 200, at_response.text
    assert uk_response.status_code == 200, uk_response.text
    assert cr_response.status_code == 200, cr_response.text
    at_body = at_response.json()
    uk_body = uk_response.json()
    cr_body = cr_response.json()
    assert at_body["country_code"] == "AT"
    assert cr_body["country_code"] == "CR"
    assert any(row["value"] == "willhaben" for row in at_body["providers"])
    assert any(row["value"] == "immowelt_at" and "immowelt" in row["label"].lower() for row in at_body["providers"])
    assert any(row["value"] == "findmyhome_at" and "FindMyHome" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "derstandard_at" and "STANDARD" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "remax_at" and "RE/MAX Austria" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "wag_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "heimat_oesterreich_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "bwsg_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "arwag_at" and row["family"] == "developer_projects" for row in at_body["providers"])
    assert any(row["value"] == "raiffeisen_wohnbau_at" and row["family"] == "developer_projects" for row in at_body["providers"])
    assert all("Willhaben" not in row["label"] for row in uk_body["providers"])
    assert any(row["value"] == "rightmove" for row in uk_body["providers"])
    assert any(row["value"] == "encuentra24_cr" for row in cr_body["providers"])
    assert any(row["value"] == "re_cr_mls" for row in cr_body["providers"])
    assert any(row["value"] == "theagency_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "krain_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "desarrollos_cr" and row["family"] == "developer_projects" for row in cr_body["providers"])
    assert any(row["value"] == "tierraverde_cr" and row["family"] == "developer_projects" for row in cr_body["providers"])
    assert any(row["value"] == "propertiesincostarica_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "costaricarealestateservice_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "twocostaricarealestate_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])


def test_property_search_run_can_be_deleted_from_api(monkeypatch) -> None:
    principal_id = "exec-property-search-run-delete"
    client = build_property_client(principal_id=principal_id)

    def _fake_sync_direct_property_scout(self, *, principal_id: str, selected_platforms, property_search_preferences, force_refresh: bool = False):
        return {
            "summary": {
                "ranked_candidates": [],
                "sources": [],
                "sources_total": 0,
                "listing_total": 0,
            }
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"country_code": "AT"},
            "max_results_per_source": 1,
        },
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]

    deleted = client.delete(f"/app/api/property/search-runs/{run_id}")
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["run_id"] == run_id
    assert body["deleted"] is True

    missing = client.get(f"/app/api/property/search-runs/{run_id}")
    assert missing.status_code == 404, missing.text


def test_property_search_runs_can_be_cleared_for_current_principal_only() -> None:
    principal_id = "exec-property-search-run-clear"
    other_principal_id = "exec-property-search-run-clear-other"
    client = build_property_client(principal_id=principal_id)
    current_run_id = "clear-current-run"
    other_run_id = "clear-other-run"
    current_form_run_id = "clear-current-form-run"

    current_record = product_service._new_property_search_run_record(
        run_id=current_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        force_refresh=False,
    )
    other_record = product_service._new_property_search_run_record(
        run_id=other_run_id,
        principal_id=other_principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        force_refresh=False,
    )
    current_form_record = product_service._new_property_search_run_record(
        run_id=current_form_run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        force_refresh=False,
    )
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        previous_registry = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[current_run_id] = current_record
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[other_run_id] = other_record
    try:
        cleared = client.delete("/app/api/property/search-runs")
        assert cleared.status_code == 200, cleared.text
        body = cleared.json()
        assert body["deleted_count"] == 1
        assert body["run_ids"] == [current_run_id]
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            assert current_run_id not in product_service._PROPERTY_SEARCH_RUN_REGISTRY
            assert other_run_id in product_service._PROPERTY_SEARCH_RUN_REGISTRY

        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            product_service._PROPERTY_SEARCH_RUN_REGISTRY[current_form_run_id] = current_form_record
        form_cleared = client.post("/app/api/property/search-runs/clear", follow_redirects=False)
        assert form_cleared.status_code == 303, form_cleared.text
        assert form_cleared.headers["location"] == "/app/account?history_cleared=1#data-export"
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            assert current_form_run_id not in product_service._PROPERTY_SEARCH_RUN_REGISTRY
            assert other_run_id in product_service._PROPERTY_SEARCH_RUN_REGISTRY
    finally:
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.update(previous_registry)


def test_property_search_runs_keep_recent_history_but_prune_stale_payloads_by_default(monkeypatch) -> None:
    monkeypatch.delenv("EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS", raising=False)
    assert product_service._property_search_run_retention_seconds() == 90 * 24 * 60 * 60
    assert property_search_storage.property_search_run_retention_policy() == {
        "property_search_run_retention_status": "enabled",
        "property_search_run_retention_seconds": "7776000",
        "property_search_run_retention_days": "90.0",
        "property_search_run_retention_env": "EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS",
        "property_search_run_retention_default_seconds": "7776000",
    }
    run_id = "retained-recent-run"
    stale_run_id = "pruned-stale-run"
    principal_id = "exec-property-search-run-retained"
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    old_record = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        force_refresh=False,
    )
    old_record["created_at"] = old_timestamp
    old_record["updated_at"] = old_timestamp
    stale_record = dict(old_record)
    stale_record["run_id"] = stale_run_id
    stale_record["created_at"] = stale_timestamp
    stale_record["updated_at"] = stale_timestamp

    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        previous_registry = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = old_record
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[stale_run_id] = stale_record
    try:
        product_service._prune_property_search_runs()
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            assert run_id in product_service._PROPERTY_SEARCH_RUN_REGISTRY
            assert stale_run_id in product_service._PROPERTY_SEARCH_RUN_REGISTRY
            stale_saved_result = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY[stale_run_id])
            assert stale_saved_result["payload_retention_status"] == "compact_only"
            assert stale_saved_result["run_id"] == stale_run_id
            assert stale_saved_result["principal_id"] == principal_id
            assert "summary" in stale_saved_result
            assert "selected_platforms" in stale_saved_result
    finally:
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.update(previous_registry)


def test_property_search_run_retention_env_allows_explicit_admin_pruning(monkeypatch) -> None:
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS", "60")
    run_id = "explicit-retention-old-run"
    principal_id = "exec-property-search-run-explicit-retention"
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    old_record = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        force_refresh=False,
    )
    old_record["created_at"] = old_timestamp
    old_record["updated_at"] = old_timestamp

    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        previous_registry = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY)
        product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = old_record
    try:
        product_service._prune_property_search_runs()
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            assert run_id in product_service._PROPERTY_SEARCH_RUN_REGISTRY
            saved_result = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id])
            assert saved_result["payload_retention_status"] == "compact_only"
            assert saved_result["run_id"] == run_id
            assert saved_result["principal_id"] == principal_id
    finally:
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.clear()
            product_service._PROPERTY_SEARCH_RUN_REGISTRY.update(previous_registry)


def test_property_provider_catalog_generates_remax_austria_sources() -> None:
    rows = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "listing_mode": "buy",
            "location_query": "Wien",
            "min_area_m2": 70,
        },
        selected_platforms=("remax",),
        principal_id="exec-property-remax-source",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "remax_at"
    assert row["provider_family"] == "broker_direct"
    assert row["url"].startswith("https://www.remax.at/en/properties/propertysearch")
    assert "q=Wien" in row["url"]
    assert row["fetch_timeout_seconds"] == 8
    assert "https://www.remax.at/de/ib/remax-first-wien/immobilien" in row["fallback_listing_urls"]
    assert row["provider_filter_pushdown"]["applied"]["min_area_m2"] == 70


def test_property_search_run_rejects_invalid_platform_and_enforces_run_principal_scope(monkeypatch) -> None:
    principal_id = "exec-property-search-run-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Scope Office")

    response = client.post(
        "/app/api/signals/property/search/run",
        json={"selected_platforms": ["not-a-real-platform"]},
    )
    assert response.status_code == 400

    observed_sync: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed_sync["called"] = True
        observed_sync["selected_platforms"] = tuple(selected_platforms)
        observed_sync["force_refresh"] = bool(force_refresh)
        observed_sync["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mocked from onboarding prefs",
                status="in_progress",
                steps_delta=3,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 1,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 1,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    owner = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 2,
            "property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert owner.status_code == 200, owner.text

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert observed_sync.get("called") is True
    assert set(observed_sync.get("selected_platforms") or ()) == {"willhaben", "kalandra"}

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1

    intruder = build_property_client(principal_id="intruder-property-search-run-scope")
    intruder_status = intruder.get(f"/app/api/signals/property/search/run/{run_id}")
    assert intruder_status.status_code == 404


def test_property_search_run_requests_market_initialization_for_unsupported_country() -> None:
    principal_id = "cf-email:bootstrap.market@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Bootstrap Request Office")

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "property_preferences": {
                "country_code": "NO",
                "language_code": "en",
                "listing_mode": "buy",
                "location_query": "Oslo",
            }
        },
    )
    assert started.status_code == 200, started.text

    body = started.json()
    assert body["status"] == "initialization_required"
    assert body["run_id"] == ""
    assert body["bootstrap_required"] is True
    assert body["bootstrap_country_code"] == "NO"
    assert body["bootstrap_country_label"] == "NO"
    assert body["bootstrap_eta_hours"] == 3
    assert body["bootstrap_handoff_ref"].startswith("human_task:")
    assert body["status_url"] == ""

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    bootstrap = next(item for item in handoffs.json() if item["task_type"] == "property_market_bootstrap")
    assert bootstrap["id"] == body["bootstrap_handoff_ref"]
    assert "Initialize PropertyQuarry market" in bootstrap["summary"]


def test_property_search_run_sends_results_ready_email_when_processed(monkeypatch) -> None:
    principal_id = "cf-email:results.ready@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Ready Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-1"
        accepted_at = "2026-06-04T12:00:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )
    monkeypatch.setattr(product_service.time, "sleep", lambda _seconds: None)

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 3,
            "review_created_total": 2,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 1,
            "tour_existing_total": 1,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_label": "Willhaben",
                    "top_candidates": [
                        {
                            "title": "Best floorplan flat",
                            "fit_score": 88.0,
                            "fit_summary": "Personal fit 88/100",
                            "review_url": "https://propertyquarry.com/workspace-access/review-token?return_to=%2Fapp%2Fhandoffs%2Fhuman_task%3Areview-1",
                            "tour_url": "https://propertyquarry.com/tours/best-floorplan-flat",
                            "tour_status": "created",
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"selected_platforms": ["willhaben"], "property_preferences": {"country_code": "AT", "location_query": "Wien"}},
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert sent
    assert sent[0]["recipient_email"] == "results.ready@example.com"
    assert sent[0]["result_total"] == 3
    assert sent[0]["hosted_tour_total"] == 2
    assert urllib.parse.quote(f"/app/properties?run_id={run_id}", safe="/") in str(sent[0]["results_url"])
    assert sent[0]["top_properties"][0]["title"] == "Best floorplan flat"
    assert sent[0]["top_properties"][0]["review_url"].startswith("https://propertyquarry.com/workspace-access/")
    assert str(sent[0]["top_properties"][0]["review_url"]).endswith("return_to=%2Fapp%2Fhandoffs%2Fhuman_task%3Areview-1")
    assert "return_to=%2Ftours%2Fbest-floorplan-flat" in str(sent[0]["top_properties"][0]["tour_url"])


def test_property_search_results_ready_email_waits_for_tour_completion(monkeypatch) -> None:
    principal_id = "cf-email:tour.wait@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Finalization Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-2"
        accepted_at = "2026-06-04T12:05:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )
    monkeypatch.setattr(product_service.time, "sleep", lambda _seconds: None)

    poll_state = {"calls": 0}

    def _fake_latest_property_tour_event(self, *, principal_id: str, source_ref: str, property_url: str = ""):  # type: ignore[no-untyped-def]
        poll_state["calls"] += 1
        if poll_state["calls"] < 2:
            return None
        return {
            "event_type": "generic_property_tour_created",
            "payload": {
                "tour_url": "https://propertyquarry.com/tours/final-tour",
                "vendor_tour_url": "https://vendor.example/tour",
            },
            "created_at": product_service._now_iso(),
        }

    monkeypatch.setattr(ProductService, "_latest_property_tour_event", _fake_latest_property_tour_event)

    service = product_service.build_product_service(client.app.state.container)
    result = {
        "status": "processed",
        "listing_total": 1,
        "sources": [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "source_ref": "property-scout:test-1",
                        "tour_status": "queued",
                        "tour_url": "",
                        "blocked_reason": "",
                        "property_facts": {"has_360": True},
                    }
                ],
            }
        ],
    }

    service._await_property_search_results_delivery_ready(
        principal_id=principal_id,
        run_id="run-final-1",
        result=result,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert sent
    assert sent[0]["hosted_tour_total"] == 1


def test_property_search_run_status_snapshot_finishes_results_email_after_restart(monkeypatch) -> None:
    principal_id = "cf-email:tour.restart@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Restart Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-3"
        accepted_at = "2026-06-04T12:10:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )

    container = client.app.state.container
    service = product_service.build_product_service(container)
    run_id = "run-final-2"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "processed"
    state["summary"] = {
        "status": "processed",
        "listing_total": 1,
        "sources": [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "source_ref": "property-scout:test-2",
                        "tour_status": "queued",
                        "tour_url": "",
                        "blocked_reason": "",
                        "property_facts": {"has_360": True},
                    }
                ],
            }
        ],
    }
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    monkeypatch.setattr(
        ProductService,
        "_latest_property_tour_event",
        lambda self, *, principal_id, source_ref, property_url="": {
            "event_type": "generic_property_tour_created",
            "payload": {"tour_url": "https://propertyquarry.com/tours/recovered-tour"},
            "created_at": product_service._now_iso(),
        },
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert sent
    assert sent[0]["hosted_tour_total"] == 1
    assert status["summary"]["ready_tour_total"] == 1


def test_property_search_run_status_marks_stale_active_run_failed(monkeypatch) -> None:
    principal_id = "cf-email:stale.run@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Stale Run Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")

    container = client.app.state.container
    service = product_service.build_product_service(container)
    replacement_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        ProductService,
        "_start_property_search_repair_replacement_run",
        lambda self, **kwargs: replacement_calls.append(dict(kwargs)) or {"run_id": "run-stale-1-repair"},
    )
    run_id = "run-stale-1"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "in_progress"
    state["progress"] = 1
    state["events"] = [
        {
            "step": "source_previewing",
            "status": "in_progress",
            "message": "Reviewing candidate 25 of 60 for Willhaben | Austria | Rent | 1010 Vienna.",
        }
    ]
    state["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status"] == "failed"
    assert status["progress"] == 100
    assert status["summary"]["interrupted"] is True
    assert status["summary"]["repair_status"] == "repairing"
    assert status["summary"]["repair_status_label"] == "Repairing"
    assert status["summary"]["repair_replacement_run_id"] == "run-stale-1-repair"
    assert status["summary"]["repair_replacement_status_url"] == "/app/api/signals/property/search/run/run-stale-1-repair"
    assert status["summary"]["provider_repair_task_opened_total"] == 1
    assert any(event["step"] == "run_interrupted" for event in status["events"])
    assert any(event["step"] == "run_repair_queued" for event in status["events"])

    tasks = [
        task
        for task in container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    assert tasks[0].priority == "urgent"
    repair_input = dict(tasks[0].input_json or {})
    assert repair_input["filter_key"] == "run_interrupted_stale"
    assert repair_input["run_id"] == run_id
    assert repair_input["source_label"] == "Willhaben | Austria | Rent | 1010 Vienna"
    assert repair_input["diagnostics"]["failure_class"] == "run_interrupted_stale"
    assert replacement_calls
    assert replacement_calls[0]["selected_platforms"] == ("willhaben",)
    assert replacement_calls[0]["property_search_preferences"]["location_query"] == "Vienna"

    status_again = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status_again is not None
    assert len(replacement_calls) == 1
    tasks_again = [
        task
        for task in container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks_again) == 1


def test_property_search_run_status_marks_source_previewing_stale_by_last_progress_event_even_if_repair_updates_row(monkeypatch) -> None:
    principal_id = "cf-email:stale.source.previewing@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Stale Source Previewing Repair Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")

    container = client.app.state.container
    service = product_service.build_product_service(container)
    replacement_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        ProductService,
        "_start_property_search_repair_replacement_run",
        lambda self, **kwargs: replacement_calls.append(dict(kwargs)) or {"run_id": "run-source-previewing-stale-repair"},
    )
    run_id = "run-source-previewing-stale"
    stale_event_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "1010 Vienna"},
        force_refresh=False,
    )
    state["status"] = "in_progress"
    state["progress"] = 23
    state["current_step"] = "source_previewing"
    state["events"] = [
        {
            "at": stale_event_at,
            "step": "source_previewing",
            "status": "in_progress",
            "message": "Reviewing candidate 20 of 24 for Willhaben | Austria | Rent | 1010 Vienna.",
        }
    ]
    state["summary"] = {
        **dict(state.get("summary") or {}),
        "repair_receipts": [
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "filter_key": "require_floorplan",
                "resolution": "provider_quarantined_retry_budget_exhausted",
            }
        ],
    }
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status"] == "failed"
    assert status["summary"]["interrupted"] is True
    assert status["summary"]["repair_status"] == "repairing"
    assert status["summary"]["repair_replacement_run_id"] == "run-source-previewing-stale-repair"
    assert any(event["step"] == "run_interrupted" for event in status["events"])
    assert any(event["step"] == "run_repair_queued" for event in status["events"])
    assert replacement_calls


def test_property_search_run_worker_exception_opens_generic_repair_task(monkeypatch) -> None:
    principal_id = "cf-email:worker.exception@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Worker Exception Repair Office")
    service = product_service.build_product_service(client.app.state.container)

    def _raise_worker_failure(self, **kwargs):
        raise RuntimeError("provider merge crashed before source rows existed")

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _raise_worker_failure)
    run = service.start_property_search_run(
        principal_id=principal_id,
        actor="test",
        selected_platforms=("willhaben",),
        property_search_preferences={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
        },
        force_refresh=True,
        max_results_per_source=1,
    )

    status = _poll_property_search_run_status(client, str(run["run_id"]))

    assert status["status"] == "failed"
    assert status["summary"]["repair_status"] == "repairing"
    assert status["summary"]["repair_step_label"] == "Repairing interrupted run."
    assert status["summary"]["provider_repair_task_opened_total"] == 1
    assert any(event["step"] == "run_repair_queued" for event in status["events"])
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    assert tasks[0].priority == "urgent"
    assert tasks[0].assigned_operator_id == "ea_one_manager"
    repair_input = dict(tasks[0].input_json or {})
    assert repair_input["filter_key"] == "run_worker_exception"
    assert repair_input["run_id"] == run["run_id"]
    assert repair_input["diagnostics"]["failure_class"] == "run_worker_exception"
    assert repair_input["diagnostics"]["error"] == "provider merge crashed before source rows existed"
    replacement_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        ProductService,
        "_start_property_search_repair_replacement_run",
        lambda self, **kwargs: replacement_calls.append(dict(kwargs)) or {"run_id": f"{run['run_id']}-repair"},
    )
    repair_summary = service.process_property_provider_repair_tasks(
        principal_id=principal_id,
        actor="test",
        limit=5,
    )
    assert repair_summary["resolved_total"] == 1
    assert repair_summary["deferred_total"] == 0
    assert repair_summary["resolved"][0]["resolution"] == "worker_exception_restart_required"
    assert repair_summary["resolved"][0]["replacement_run_id"] == f"{run['run_id']}-repair"
    assert replacement_calls
    assert replacement_calls[0]["selected_platforms"] == ("willhaben",)
    assert replacement_calls[0]["property_search_preferences"]["location_query"] == "1010 Vienna"

    repaired_status = service.get_property_search_run_status(principal_id=principal_id, run_id=str(run["run_id"]))
    assert repaired_status["summary"]["repair_replacement_run_id"] == f"{run['run_id']}-repair"
    assert repaired_status["summary"]["repair_replacement_status_url"] == f"/app/api/signals/property/search/run/{run['run_id']}-repair"
    assert repaired_status["summary"]["repair_receipts"][0]["resolution"] == "worker_exception_restart_required"


def test_property_provider_repair_quarantines_stale_deferred_source_fetch(monkeypatch) -> None:
    principal_id = "cf-email:provider.quarantine@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Provider Quarantine Repair Office")
    service = ProductService(client.app.state.container)
    run_id = f"provider-quarantine-{uuid.uuid4().hex}"
    source_url = "https://kalandra.example.invalid/search"
    now = product_service._now_iso()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": now,
            "updated_at": now,
            "status": "failed",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["kalandra", "willhaben"],
            "progress": 100,
            "message": "Search stopped before all provider checks finished.",
            "summary": {
                "status": "failed",
                "ranked_candidates": [{"candidate_ref": "cand-1", "title": "Recovered Willhaben hit"}],
                "sources": [
                    {
                        "source_url": source_url,
                        "source_label": "Kalandra | Austria | Rent | 1010 Vienna",
                        "status": "failed",
                        "error": "temporary fetch failed",
                    }
                ],
            },
        }
    opened = service._open_property_provider_repair_task(
        principal_id=principal_id,
        property_url=source_url,
        title="Kalandra source fetch failed",
        source_url=source_url,
        source_label="Kalandra | Austria | Rent | 1010 Vienna",
        source_platform="kalandra",
        source_family="private_portal",
        filter_key="source_fetch",
        diagnostics={"provider_host": "kalandra.example.invalid", "error": "timeout", "repair_attempts": 3},
        source_ref="property-source:kalandra",
        run_id=run_id,
    )
    assert opened["status"] == "opened"
    tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status="pending",
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(tasks) == 1
    monkeypatch.setenv("EA_PROPERTY_PROVIDER_REPAIR_RETRY_BUDGET_SECONDS", "60")
    monkeypatch.setattr(
        ProductService,
        "_auto_resolve_property_provider_repair_task",
        lambda self, *, principal_id, task, actor: {"status": "deferred", "reason": "manual_provider_patch_required"},
    )

    repair_summary = service.process_property_provider_repair_tasks(
        principal_id=principal_id,
        actor="test",
        limit=5,
    )

    assert repair_summary["resolved_total"] == 1
    assert repair_summary["deferred_total"] == 0
    assert repair_summary["resolved"][0]["resolution"] == "provider_quarantined_retry_budget_exhausted"
    task_after = client.app.state.container.orchestrator.list_human_tasks(
        principal_id=principal_id,
        status="returned",
        limit=20,
    )[0]
    assert task_after.resolution == "provider_quarantined_retry_budget_exhausted"

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status["status"] == "completed_partial"
    summary = dict(status["summary"])
    source = dict(summary["sources"][0])
    assert source["status"] == "repaired"
    assert source["repair_status"] == "returned"
    assert source["repair_resolution"] == "provider_quarantined_retry_budget_exhausted"
    assert source["original_error"] == "temporary fetch failed"
    assert summary["repair_receipts"][0]["resolution"] == "provider_quarantined_retry_budget_exhausted"
    assert summary["repair_resolved_total"] == 1


def test_property_search_run_state_builds_stale_failure_event() -> None:
    event = product_service._state_property_search_run_stale_failure_event(
        {"status": "in_progress"},
        stale_seconds=20 * 60,
    )

    assert event["step"] == "run_interrupted"
    assert event["status"] == "failed"
    assert "more than 20 minutes" in str(event["message"])
    assert dict(event["summary_updates"]) == {
        "interrupted": True,
        "stale_after_seconds": 1200,
        "last_known_status": "in_progress",
    }
    assert event["force_status"] == "failed"


def test_property_search_run_state_builds_stale_partial_event_when_shortlist_exists() -> None:
    event = product_service._state_property_search_run_stale_failure_event(
        {
            "status": "in_progress",
            "summary": {
                "listing_total": 26,
                "ranked_candidates": [{"title": "Recovered hit"}],
            },
        },
        stale_seconds=20 * 60,
    )

    assert event["step"] == "run_interrupted"
    assert event["status"] == "completed_partial"
    assert "current shortlist is still available" in str(event["message"])
    assert dict(event["summary_updates"])["repair_status"] == "degraded"
    assert dict(event["summary_updates"])["repair_status_label"] == "Partial coverage"
    assert event["force_status"] == "completed_partial"


def test_property_search_run_status_marks_stale_partial_run_completed_partial(monkeypatch) -> None:
    principal_id = "cf-email:stale.partial@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Stale Partial Run Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")

    container = client.app.state.container
    service = product_service.build_product_service(container)
    run_id = "run-stale-partial-1"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "in_progress"
    state["progress"] = 86
    state["summary"] = {
        "listing_total": 26,
        "ranked_candidates": [{"title": "Recovered hit"}],
    }
    state["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status"] == "completed_partial"
    assert status["progress"] == 100
    assert status["summary"]["interrupted"] is True
    assert status["summary"]["repair_status"] == "degraded"
    assert any(event["step"] == "run_interrupted" for event in status["events"])


def test_property_search_run_terminal_outcome_prefers_partial_success_for_mixed_sources() -> None:
    assert product_service._state_property_search_run_terminal_outcome(
        sources_total=5,
        failed_total=2,
        successful_source_total=3,
    ) == "completed_partial"
    assert product_service._state_property_search_run_terminal_outcome(
        sources_total=5,
        failed_total=0,
        successful_source_total=5,
    ) == "processed"
    assert product_service._state_property_search_run_terminal_outcome(
        sources_total=5,
        failed_total=5,
        successful_source_total=0,
    ) == "failed"


def test_property_search_provider_totals_distinguish_integrations_from_groups() -> None:
    specs = [
        {
            "platform": "willhaben",
            "provider_family": "core_portal",
            "label": "Willhaben | Austria | Rent | 1010 Vienna",
            "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1010+Vienna",
        },
        {
            "platform": "willhaben",
            "provider_family": "core_portal",
            "label": "Willhaben | Austria | Rent | 1020 Vienna",
            "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=1020+Vienna",
        },
        {
            "platform": "derstandard_at",
            "provider_family": "core_portal",
            "label": "DER STANDARD Immobilien | Austria | Rent | 1020 Vienna",
            "url": "https://immobilien.derstandard.at/search/1020",
        },
        {
            "platform": "gesiba_at",
            "provider_family": "housing_coop",
            "label": "GESIBA | Austria | Rent | 1020 Vienna",
            "url": "https://www.gesiba.at/search/1020",
        },
        {
            "platform": "oesw_at",
            "provider_family": "housing_coop",
            "label": "ÖSW | Austria | Rent | 1020 Vienna",
            "url": "https://www.oesw.at/search/1020",
        },
    ]

    assert product_service._property_search_provider_total(specs) == 4
    assert product_service._property_search_provider_group_total(specs) == 2


def test_property_search_run_state_syncs_summary_projection() -> None:
    summary = product_service._state_property_search_run_sync_summary(
        state={"status": "in_progress", "progress": 42},
        summary={"listing_total": 3},
        terminal_statuses={"processed", "completed", "failed", "cancelled", "noop"},
        eta_seconds=360,
        eta_label="about 6 min",
    )

    assert summary["status"] == "in_progress"
    assert summary["progress"] == 42
    assert summary["progress_percent"] == 42
    assert summary["eta_seconds"] == 360
    assert summary["eta_label"] == "about 6 min"


def test_property_search_run_progress_stays_zero_during_early_bootstrap_without_real_source_output() -> None:
    progress, eta_seconds, eta_label = product_service._property_search_run_progress_projection(
        state={
            "created_at": "2026-01-01T00:00:00Z",
            "progress": 0,
        },
        step="source_fetching",
        status="in_progress",
        summary={
            "sources_total": 8,
            "sources": [],
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
        },
        stages_total=120,
        steps_completed=14,
    )

    assert progress == 0
    assert eta_seconds == 0
    assert eta_label == ""


def test_property_search_run_progress_stays_zero_during_bootstrap_before_sources_are_materialized() -> None:
    progress, eta_seconds, eta_label = product_service._property_search_run_progress_projection(
        state={
            "created_at": "2026-01-01T00:00:00Z",
            "progress": 0,
        },
        step="starting",
        status="in_progress",
        summary={
            "sources_total": 0,
            "sources": [],
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
        },
        stages_total=12,
        steps_completed=1,
    )

    assert progress == 0
    assert eta_seconds == 0
    assert eta_label == ""


def test_property_search_run_progress_advances_once_real_source_output_exists() -> None:
    progress, eta_seconds, eta_label = product_service._property_search_run_progress_projection(
        state={
            "created_at": "2026-01-01T00:00:00Z",
            "progress": 0,
        },
        step="source_extracting",
        status="in_progress",
        summary={
            "sources_total": 8,
            "sources": [{"source_label": "Willhaben"}],
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
        },
        stages_total=120,
        steps_completed=15,
    )

    assert progress > 0
    assert isinstance(eta_seconds, int)
    assert isinstance(eta_label, str)


def test_property_search_run_state_applies_event_and_caps_history() -> None:
    state = {
        "status": "queued",
        "progress": 0,
        "stages_total": 4,
        "steps_completed": 0,
        "summary": {"sources_total": 2, "sources": [{"source": "a"}]},
        "events": [{"at": f"2026-01-01T00:00:{index:02d}Z", "step": "queued", "message": "queued", "status": "queued"} for index in range(240)],
    }

    updated = product_service._state_property_search_run_apply_event(
        state=state,
        step="source_started",
        message="Scanning source.",
        status="in_progress",
        steps_delta=1,
        summary_updates={"listing_total": 3},
        force_status="",
        stages_total_override=None,
        terminal_statuses={"processed", "completed", "failed", "cancelled", "noop"},
        default_stages_total=4,
        now_iso=lambda: "2026-01-01T01:00:00Z",
        compact_text=product_service.compact_text,
        progress_projection=product_service._property_search_run_progress_projection,
        sync_summary=product_service._state_property_search_run_sync_summary,
    )

    assert updated["status"] == "in_progress"
    assert updated["current_step"] == "source_started"
    assert updated["message"] == "Scanning source."
    assert updated["steps_completed"] == 1
    assert updated["summary"]["listing_total"] == 3
    assert updated["summary"]["status"] == "in_progress"
    assert isinstance(updated["summary"]["progress_percent"], int)
    assert len(updated["events"]) == 240
    assert updated["events"][-1]["step"] == "source_started"
    assert updated["updated_at"] == "2026-01-01T01:00:00Z"


def test_property_search_run_event_syncs_summary_status_and_progress() -> None:
    principal_id = "cf-email:summary.sync@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Summary Sync Office")
    service = product_service.build_product_service(client.app.state.container)
    run_id = "run-summary-sync-1"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="source_started",
        message="Scanning source.",
        status="in_progress",
        steps_delta=1,
    )

    updated = dict(product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id])
    assert updated["summary"]["status"] == "in_progress"
    assert isinstance(updated["summary"]["progress_percent"], int)


def test_property_alert_review_open_timeout_returns_failed_payload(monkeypatch) -> None:
    principal_id = "cf-email:timeout@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Timeout Office")
    service = product_service.build_product_service(client.app.state.container)
    monkeypatch.setenv("EA_PROPERTY_SEARCH_REVIEW_OPEN_TIMEOUT_SECONDS", "1")

    recorded: list[dict[str, object]] = []

    def _fake_record_product_event(self, *, principal_id: str, event_type: str, payload: dict[str, object], source_id: str = "", dedupe_key: str = "") -> None:  # type: ignore[no-untyped-def]
        recorded.append(
            {
                "principal_id": principal_id,
                "event_type": event_type,
                "payload": dict(payload),
                "source_id": source_id,
                "dedupe_key": dedupe_key,
            }
        )

    def _fake_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(1.2)
        return {"status": "opened"}

    monkeypatch.setattr(ProductService, "_record_product_event", _fake_record_product_event)
    monkeypatch.setattr(ProductService, "_open_property_alert_review", _fake_open)

    result = service._open_property_alert_review_with_timeout(
        principal_id=principal_id,
        title="Delayed packet",
        summary="This review creation hangs.",
        source_ref="property-scout:timeout",
        external_id="https://example.com/listing",
        counterparty="Willhaben",
        account_email="timeout@example.com",
        property_url="https://example.com/listing",
        actor="property_scout",
        notify_telegram=False,
    )

    assert result["status"] == "failed"
    assert result["reason"] == "property_alert_review_open_timeout"
    assert recorded
    assert any(row["event_type"] == "property_alert_review_open_timeout" for row in recorded)


def test_property_search_run_status_survives_registry_loss_via_persisted_record(monkeypatch) -> None:
    principal_id = "exec-property-search-run-persisted"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Persisted Office")

    persisted: dict[str, dict[str, object]] = {}

    def _fake_store(record: dict[str, object]) -> None:
        persisted[str(record.get("run_id") or "")] = dict(record)

    def _fake_load(*, run_id: str, principal_id: str = "") -> dict[str, object] | None:
        row = persisted.get(run_id)
        if principal_id and str(dict(row or {}).get("principal_id") or "").strip() != str(principal_id or "").strip():
            return None
        return dict(row) if isinstance(row, dict) else None

    monkeypatch.setattr(product_service, "_store_property_search_run_record", _fake_store)
    monkeypatch.setattr(product_service, "_load_property_search_run_record", _fake_load)

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="persisted status event",
                status="in_progress",
                steps_delta=2,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"selected_platforms": ["willhaben"]})
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"

    product_service._PROPERTY_SEARCH_RUN_REGISTRY.pop(run_id, None)

    reloaded = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["status"] == "processed"


def test_property_search_run_can_finish_completed_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-run-completed-partial"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Partial Run Office")

    persisted: dict[str, dict[str, object]] = {}

    def _fake_store(record: dict[str, object]) -> None:
        persisted[str(record.get("run_id") or "")] = dict(record)

    def _fake_load(*, run_id: str, principal_id: str = "") -> dict[str, object] | None:
        row = persisted.get(run_id)
        if principal_id and str(dict(row or {}).get("principal_id") or "").strip() != str(principal_id or "").strip():
            return None
        return dict(row) if isinstance(row, dict) else None

    monkeypatch.setattr(product_service, "_store_property_search_run_record", _fake_store)
    monkeypatch.setattr(product_service, "_load_property_search_run_record", _fake_load)

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        if callable(progress_callback):
            progress_callback(
                step="source_failed",
                message="One provider degraded but others finished.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 3, "failed_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "completed_partial",
            "sources_total": 3,
            "listing_total": 12,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 2,
            "watch_notified_total": 0,
            "failed_total": 1,
            "repair_status": "degraded",
            "sources": [{"source_label": "Willhaben"}, {"source_label": "Gesiba", "error": "provider degraded"}],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"selected_platforms": ["willhaben"]})
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "completed_partial"
    assert status["summary"]["failed_total"] == 1


def test_property_search_preferences_persist_and_merge_into_run(monkeypatch) -> None:
    principal_id = "exec-property-search-run-merge"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Merge Office")
    seed_product_state(client, principal_id=principal_id)

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 50,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["property_search_preferences"]["max_results_per_source"] is None

    status_snapshot = client.get("/v1/onboarding/property-search/preferences")
    assert status_snapshot.status_code == 200
    assert set(status_snapshot.json()["property_search_preferences"]["selected_platforms"]) == {"willhaben", "kalandra"}


def test_agent_property_search_preferences_drop_stale_result_cap_when_saved() -> None:
    principal_id = "exec-property-agent-preferences-unlimited"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Agent Unlimited")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben"],
            "max_results_per_source": 7,
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
    )

    assert stored.status_code == 200, stored.text
    assert stored.json()["property_search_preferences"]["max_results_per_source"] is None


def test_plus_property_search_preferences_clamp_stale_result_cap_when_saved() -> None:
    principal_id = "exec-property-plus-preferences-clamped"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Plus Clamp")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben"],
            "max_results_per_source": 50,
            "property_commercial": {
                "active_plan_key": "plus",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
    )

    assert stored.status_code == 200, stored.text
    assert stored.json()["property_search_preferences"]["max_results_per_source"] == 5


def test_property_search_preferences_persist_full_region_scope_as_hard_location_scope() -> None:
    principal_id = "exec-property-search-all-vienna-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Vienna Scope")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "full_region_scope": True,
            "location_query": "",
            "selected_platforms": ["willhaben"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )

    assert stored.status_code == 200, stored.text
    preferences = stored.json()["property_search_preferences"]
    assert preferences["country_code"] == "AT"
    assert preferences["region_code"] == "vienna"
    assert preferences["full_region_scope"] is True
    assert preferences["location_query"] == "Vienna"


def test_property_search_preferences_normalize_country_names_before_saving() -> None:
    principal_id = "exec-property-search-country-name-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Name Scope")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "Costa Rica",
            "listing_mode": "sale",
            "property_type": "land",
            "location_query": "Tamarindo",
            "selected_platforms": ["encuentra24_cr"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )

    assert stored.status_code == 200, stored.text
    preferences = stored.json()["property_search_preferences"]
    assert preferences["country_code"] == "CR"
    assert preferences["language_code"] == "es"
    assert preferences["listing_mode"] == "buy"
    assert preferences["property_type"] == "land"
    assert preferences["location_query"] == "Tamarindo"


def test_direct_property_scout_uses_saved_preferences_and_respects_disabled_flag(monkeypatch) -> None:
    principal_id = "exec-property-direct-saved-preferences"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Direct Saved Preferences")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": False,
            "alert_frequency": "disabled",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    service = product_service.build_product_service(client.app.state.container)
    disabled = service.sync_direct_property_scout(principal_id=principal_id, actor="scheduler")

    assert disabled["status"] == "noop"
    assert disabled["noop_reason"] == "property_search_disabled"

    enabled = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert enabled.status_code == 200, enabled.text
    observed: dict[str, object] = {}

    def _fake_generated_specs(**kwargs):
        observed["preferences"] = dict(kwargs.get("preferences") or {})
        observed["selected_platforms"] = tuple(kwargs.get("selected_platforms") or ())
        return ()

    monkeypatch.setattr(product_service, "generated_property_source_specs", _fake_generated_specs)

    result = service.sync_direct_property_scout(principal_id=principal_id, actor="scheduler")

    assert result["status"] == "noop"
    assert observed["preferences"]["location_query"] == "Wien"
    assert observed["preferences"]["listing_mode"] == "rent"
    assert observed["selected_platforms"] == ()
    assert result["timing_receipts"]["sources_resolved_at"]
    assert result["timing_receipts"]["results_delivery_ready_at"]
    assert result["timing_receipts"]["completed_at"]


def test_property_search_run_uses_saved_platforms_before_family_toggles(monkeypatch) -> None:
    principal_id = "exec-property-search-saved-platforms"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Saved Platforms")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "immmo", "immoscout_at", "remax_at", "kalandra", "broker_direct_at"],
            "include_broker_direct_sources": True,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"selected_platforms": []})
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    assert set(observed.get("selected_platforms") or ()) >= {
        "willhaben",
        "immmo",
        "immoscout_at",
        "derstandard_at",
        "remax_at",
        "kalandra",
        "broker_direct_at",
    }


def test_property_search_run_updates_active_search_agent_lifecycle(monkeypatch) -> None:
    principal_id = "exec-property-search-agent-lifecycle"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Agent Lifecycle")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "search_agent_enabled": True,
            "search_agent_notification_limit": 3,
            "search_agent_notification_period": "day",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service,
        "generated_property_source_specs",
        lambda *, preferences, selected_platforms, principal_id, default_person_id, max_results: (
            {
                "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien",
                "label": "Willhaben Vienna",
                "platform": "willhaben",
                "principal_id": principal_id,
                "preference_person_id": default_person_id,
                "notify_telegram": False,
                "max_results": 1,
            },
        ),
    )
    monkeypatch.setattr(product_service, "_property_scout_listing_urls_for_source", lambda **kwargs: ((), {"status": "miss"}))
    service = product_service.build_product_service(client.app.state.container)

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="scheduler",
        selected_platforms=("willhaben",),
        max_results_per_source=1,
        force_refresh=True,
    )

    lifecycle = dict(result.get("search_agent_lifecycle") or {})
    assert lifecycle["notification_period"] == "day"
    assert lifecycle["notification_limit"] == 3
    assert lifecycle["last_run_at"]
    assert lifecycle["next_run_at"]
    state = client.app.state.container.onboarding.status(principal_id=principal_id)
    agents = list(dict(state.get("property_search_preferences") or {}).get("search_agents") or [])
    assert agents[0]["last_run_at"] == lifecycle["last_run_at"]
    assert agents[0]["next_run_at"] == lifecycle["next_run_at"]
    assert agents[0]["sent_in_current_window"] == 0


def test_direct_property_scout_emits_timing_receipts_even_when_sources_are_empty(monkeypatch) -> None:
    principal_id = "exec-property-scout-timing"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Timing")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien",
                "label": "Willhaben Vienna",
                "platform": "willhaben",
                "provider_family": "core_portal",
                "principal_id": principal_id,
                "preference_person_id": "self",
                "notify_telegram": False,
                "max_results": 1,
            }
        ],
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_listing_urls_for_source",
        lambda **kwargs: ((), {"status": "miss"}),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="scheduler",
        selected_platforms=("willhaben",),
        max_results_per_source=1,
        force_refresh=True,
    )

    assert result["status"] == "processed"
    assert float(dict(result.get("timing_ms") or {}).get("run_total") or 0.0) >= 0.0
    assert float(dict(result.get("timing_ms") or {}).get("provider_fetch_total") or 0.0) >= 0.0
    assert len(result["sources"]) == 1
    assert float(dict(result["sources"][0].get("timing_ms") or {}).get("provider_fetch") or 0.0) >= 0.0


def test_property_search_run_explicit_empty_keywords_clear_saved_keywords(monkeypatch) -> None:
    principal_id = "exec-property-search-clear-keywords"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Clear Keywords")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "keywords": "supermarket nearby, underground nearby, no gas",
            "custom_keywords": "quiet, bright",
            "selected_platforms": ["willhaben"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"property_preferences": {"keywords": "", "custom_keywords": ""}},
    )
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    assert observed["property_search_preferences"]["keywords"] == ""
    assert observed["property_search_preferences"]["custom_keywords"] == ""


def test_property_search_preferences_update_preserves_existing_commercial_state(monkeypatch) -> None:
    principal_id = "pq-commercial-preserve"
    client = build_property_client(principal_id=principal_id)
    started = client.post("/v1/onboarding/start", json={"workspace_name": "Commercial Preserve", "workspace_mode": "personal"})
    assert started.status_code == 200

    seeded = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert seeded.status_code == 200

    updated = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "genossenschaften_at"],
            "investment_research_mode": "auto",
            "use_stored_feedback_preferences": False,
        },
    )
    assert updated.status_code == 200
    commercial = updated.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "agent"
    assert commercial["status"] == "active"

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["preference_person_id"] = str((property_search_preferences or {}).get("preference_person_id") or "").strip()
        observed["use_stored_feedback_preferences"] = bool((property_search_preferences or {}).get("use_stored_feedback_preferences"))
        observed["max_results_per_source"] = max_results_per_source
        observed["force_refresh"] = bool(force_refresh)
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"property_preferences": {"preference_person_id": "override"}},
    )
    assert started.status_code == 200
    assert set(observed.get("selected_platforms") or ()) == {"willhaben", "genossenschaften_at"}
    assert observed.get("preference_person_id") == "override"
    assert observed.get("use_stored_feedback_preferences") is False
    assert observed.get("max_results_per_source") is None


def test_property_search_run_does_not_reapply_stale_saved_agent_area_filter(monkeypatch) -> None:
    principal_id = "exec-property-search-stale-agent-merge"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Stale Agent Merge")
    seed_product_state(client, principal_id=principal_id)

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "CR",
            "listing_mode": "buy",
            "property_type": "house",
            "location_query": "Monteverde",
            "min_area_m2": 80,
            "require_floorplan": True,
            "min_match_score": 40,
            "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
            "search_agents": [
                {
                    "agent_id": "agent-monteverde-buy",
                    "name": "Monteverde buy",
                    "country_code": "CR",
                    "listing_mode": "buy",
                    "property_type": "house",
                    "location_query": "Monteverde",
                    "min_area_m2": 80,
                    "require_floorplan": True,
                    "min_match_score": 40,
                    "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
                }
            ],
            "active_search_agent_id": "agent-monteverde-buy",
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
            "property_preferences": {
                "country_code": "CR",
                "listing_mode": "buy",
                "property_type": "house",
                "location_query": "Monteverde",
                "min_area_m2": 0,
                "require_floorplan": False,
                "min_match_score": 25,
                "search_agents": stored.json()["property_search_preferences"]["search_agents"],
                "active_search_agent_id": "agent-monteverde-buy",
                "raw_preferences": {"min_area_m2": 80},
            },
        },
    )
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    preferences = dict(observed["property_search_preferences"])
    assert "re_cr_mls" in tuple(observed["selected_platforms"] or ())
    assert preferences.get("min_area_m2") not in {80, "80"}
    assert preferences["require_floorplan"] is False
    assert preferences["min_match_score"] == 25


def test_property_search_execution_preferences_relax_only_floorplan_for_discovery_mode() -> None:
    request_preferences, execution_policy = product_service._property_search_execution_preferences(
        {
            "search_mode": "discovery",
            "max_price_eur": 500000,
            "min_area_m2": 80,
            "require_floorplan": True,
            "floorplan_requirement_mode": "hard",
        }
    )

    assert request_preferences["search_mode"] == "discovery"
    assert request_preferences["require_floorplan"] is True
    assert request_preferences["floorplan_requirement_mode"] == "soft"
    assert request_preferences["max_price_eur"] == 500000
    assert request_preferences["min_area_m2"] == 80
    assert execution_policy["search_mode"] == "discovery"
    assert execution_policy["require_floorplan"] is True
    assert execution_policy["enforce_floorplan_filter"] is False
    assert execution_policy["discovery_relaxed_filters"] == ["require_floorplan", "min_area_m2"]


def test_property_search_effective_min_match_score_uses_discovery_floor() -> None:
    assert product_service._property_search_effective_min_match_score({"search_mode": "discovery", "min_match_score": 60}) == 1.0


def test_property_search_run_defaults_platforms_from_country_preferences(monkeypatch) -> None:
    principal_id = "exec-property-search-country-defaults"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Defaults")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "rent",
            "location_query": "London",
            "selected_platforms": [],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert set(observed.get("selected_platforms") or ()) == {"rightmove", "zoopla", "onthemarket"}
    assert observed["property_search_preferences"]["country_code"] == "UK"
    assert observed["property_search_preferences"]["location_query"] == "London"


def test_property_search_run_drops_saved_providers_from_wrong_country(monkeypatch) -> None:
    principal_id = "exec-property-search-country-provider-guard"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Provider Guard")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "selected_platforms": ["re_cr_mls", "encuentra24_cr"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert "re_cr_mls" not in observed["selected_platforms"]
    assert "encuentra24_cr" not in observed["selected_platforms"]
    assert set(observed["selected_platforms"]) >= {"willhaben", "immmo", "immoscout_at"}
    preferences = observed["property_search_preferences"]
    assert preferences["provider_selection_filter_applied"] is True
    assert set(preferences["provider_selection_filter_removed"]) == {"re_cr_mls", "encuentra24_cr"}


def test_property_search_run_drops_saved_unready_and_mode_mismatched_providers(monkeypatch) -> None:
    principal_id = "exec-property-search-provider-readiness-guard"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Provider Readiness Guard")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Berlin",
            "selected_platforms": ["core_portals_de", "corporate_landlords_de", "community_signals_at"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert observed["selected_platforms"] == ("core_portals_de",)
    preferences = observed["property_search_preferences"]
    assert preferences["provider_selection_filter_applied"] is True
    assert set(preferences["provider_selection_filter_removed"]) == {"corporate_landlords_de", "community_signals_at"}


def test_reconcile_property_search_results_delivery_completes_unsent_ready_run(monkeypatch) -> None:
    client = build_property_client(principal_id="exec-property-search-reconcile")
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"run-reconcile-ready-{uuid.uuid4().hex}"
    state = {
        "run_id": run_id,
        "principal_id": "exec-property-search-reconcile",
        "created_at": product_service._now_iso(),
        "updated_at": product_service._now_iso(),
        "status": "processed",
        "summary": {
            "sources_total": 1,
            "listing_total": 1,
            "eligible_tour_total": 1,
            "pending_tour_total": 0,
            "ready_tour_total": 1,
            "blocked_tour_total": 0,
            "top_candidates": [
                {
                    "title": "Ready candidate",
                    "source_ref": "source-1",
                    "listing_id": "listing-1",
                    "tour_status": "ready",
                    "tour_url": "https://propertyquarry.com/tours/ready-candidate",
                }
            ],
        },
        "events": [],
        "selected_platforms": ["willhaben"],
    }
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)
    product_service._store_property_search_run_record(state)
    observed: dict[str, object] = {}

    def _fake_notify(self, *, principal_id: str, run_id: str, result: dict[str, object]) -> None:
        observed["principal_id"] = principal_id
        observed["run_id"] = run_id
        observed["result"] = dict(result)
        self._record_product_event(
            principal_id=principal_id,
            event_type="property_search_results_ready_email_sent",
            payload={"run_id": run_id},
            source_id=run_id,
            dedupe_key=f"{principal_id}|{run_id}|property-search-results-ready-email",
        )

    monkeypatch.setattr(ProductService, "_notify_property_search_results_ready", _fake_notify)

    summary = service.reconcile_property_search_results_delivery(
        principal_id="exec-property-search-reconcile",
        limit=10,
    )

    assert summary["attempted"] >= 1
    assert summary["finalized"] >= 1
    assert summary["emailed"] >= 1
    assert observed["principal_id"] == "exec-property-search-reconcile"
    assert observed["run_id"] == run_id


def test_property_search_results_ready_can_send_heyy_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-search-heyy"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Heyy Office", selected_channels=["whatsapp"])
    onboarding = client.app.state.container.onboarding
    state = onboarding._ensure_state(principal_id)  # noqa: SLF001
    onboarding._replace_channel_pref(  # noqa: SLF001
        state,
        "whatsapp",
        {"mode": "business", "phone_number": "+436647916419"},
        status="in_progress",
    )
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_SEARCH_AGENT_DIGEST", "tmpl-search-digest")
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: observed.update(kwargs) or {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "",
            "message_id": "msg-search-digest-1",
            "delivery_status": "queued",
        },
    )

    service = product_service.build_product_service(client.app.state.container)
    result = service._notify_property_search_results_ready_heyy(
        principal_id=principal_id,
        run_id="run-heyy-1",
        result={
            "listing_total": 12,
            "high_fit_total": 4,
            "notification_budget_suppressed_total": 8,
            "ranked_candidates": [{"fit_score": 91.0}],
            "search_agent_lifecycle": {"agent_name": "Vienna rent watch"},
        },
    )
    assert result["status"] == "sent"
    assert observed["phone_number"] == "+436647916419"
    assert observed["template_id"] == "tmpl-search-digest"
    assert any(item.get("name") == "agent_name" and item.get("value") == "Vienna rent watch" for item in list(observed.get("variables") or []))
    assert any(item.get("name") == "top_fit_score" and item.get("value") == "91" for item in list(observed.get("variables") or []))
    packet_service = build_fliplink_packet_service(client.app.state.container)
    events = packet_service.list_events(principal_id=principal_id, event_type="heyy_whatsapp_template_sent", limit=10)
    payload = next(dict(row.get("payload_json") or {}) for row in events if dict(row.get("payload_json") or {}).get("template_kind") == "search_agent_digest")
    assert payload["phone_last4"] == "6419"
    assert payload["phone_e164_hash"] == redact_phone_number("+436647916419")["phone_e164_hash"]
    assert "phone_number" not in payload


def test_property_search_results_ready_heyy_digest_honors_stop_command(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-search-heyy-stopped"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Heyy Stopped Office", selected_channels=["whatsapp"])
    onboarding = client.app.state.container.onboarding
    state = onboarding._ensure_state(principal_id)  # noqa: SLF001
    onboarding._replace_channel_pref(  # noqa: SLF001
        state,
        "whatsapp",
        {"mode": "business", "phone_number": "+436647916419"},
        status="in_progress",
    )
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_SEARCH_AGENT_DIGEST", "tmpl-search-digest")
    packet_service = build_fliplink_packet_service(client.app.state.container)
    packet_service._repo.record_event(  # noqa: SLF001
        {
            "publication_id": "",
            "principal_id": principal_id,
            "event_type": "heyy_whatsapp_message_received",
            "actor": "heyy",
            "payload_json": {
                "opt_command": "STOP",
                **redact_phone_number("+436647916419"),
            },
        }
    )
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: pytest.fail("service-level Heyy digest ignored STOP"),
    )

    service = product_service.build_product_service(client.app.state.container)
    result = service._notify_property_search_results_ready_heyy(
        principal_id=principal_id,
        run_id="run-heyy-stopped",
        result={
            "listing_total": 12,
            "high_fit_total": 4,
            "notification_budget_suppressed_total": 8,
            "ranked_candidates": [{"fit_score": 91.0}],
            "search_agent_lifecycle": {"agent_name": "Vienna rent watch"},
        },
    )

    assert result == {"status": "suppressed", "reason": "heyy_whatsapp_stopped"}


def test_property_scout_queued_alert_routes_to_selected_whatsapp_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-scout-whatsapp-preference"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout WhatsApp Preference")
    headers = {"host": "propertyquarry.com"}
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    updated = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "whatsapp", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers=headers,
        follow_redirects=False,
    )
    assert updated.status_code == 303, updated.text
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_PROPERTY_MATCH", "tmpl-property-match")
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("WhatsApp-selected scout alert must not call Telegram"),
    )
    monkeypatch.setattr(
        product_service,
        "send_property_match_email",
        lambda **kwargs: pytest.fail("WhatsApp-selected scout alert must not call email"),
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: observed.update(kwargs)
        or {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "",
            "message_id": "msg-whatsapp-alert-1",
            "delivery_status": "queued",
        },
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._send_property_scout_queued_notification(
        kind="hit",
        kwargs={
            "principal_id": principal_id,
            "actor": "test",
            "title": "Wohnung mieten in 1010 Wien | 85 m² | 3 Zimmer | EUR 1.900",
            "summary": "3-Zimmer Wohnung im 1. Bezirk, 85 m2, Gesamtmiete EUR 1.900.",
            "counterparty": "Willhaben | Austria | Rent | 1010 Vienna",
            "account_email": "",
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/high-fit/",
            "source_ref": "property-scout:whatsapp-alert-1010",
            "assessment": {"fit_score": 91.0, "recommendation": "shortlist"},
            "fit_score": 91.0,
            "preference_person_id": "self",
            "review_url": "/app/research/high-fit",
            "tour_result": {"status": "skipped", "tour_url": ""},
            "candidate_properties": (
                {
                    "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/high-fit/",
                    "listing_title": "Wohnung mieten in 1010 Wien | 85 m² | 3 Zimmer | EUR 1.900",
                    "summary": "3-Zimmer Wohnung im 1. Bezirk, 85 m2, Gesamtmiete EUR 1.900.",
                    "property_facts": {
                        "postal_name": "1010 Wien",
                        "street_address": "Kärntner Straße 12, 1010 Wien",
                        "area_sqm": 85,
                        "rooms": 3,
                        "total_rent_eur": 1900,
                    },
                },
            ),
            "requested_location_hints": ("1010 Vienna",),
            "requested_country_code": "AT",
            "requested_region_code": "vienna",
        },
    )

    assert result["status"] == "sent"
    assert result["message_id"] == "msg-whatsapp-alert-1"
    assert observed["phone_number"] == "+436647916419"
    assert observed["template_id"] == "tmpl-property-match"
    assert any(item.get("name") == "fit_score" and item.get("value") == "91/100" for item in list(observed.get("variables") or []))
    packet_service = build_fliplink_packet_service(client.app.state.container)
    sent_events = packet_service.list_events(principal_id=principal_id, event_type="heyy_whatsapp_template_sent", limit=10)
    payload = dict(sent_events[0].get("payload_json") or {})
    assert payload["template_kind"] == "property_match"
    assert payload["phone_last4"] == "6419"
    assert "phone_number" not in payload


def test_property_scout_queued_whatsapp_suppresses_wrong_area_and_opens_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-scout-whatsapp-wrong-area"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout WhatsApp Wrong Area")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "selected_districts": ["1010 Vienna"],
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    updated = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "whatsapp", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )
    assert updated.status_code == 303, updated.text
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_PROPERTY_MATCH", "tmpl-property-match")
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: pytest.fail("wrong-area WhatsApp scout alert must not be sent"),
    )
    service = product_service.build_product_service(client.app.state.container)

    title = "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit großem Ess- & Wohnbereich"
    summary = "Moderne Zwei-Zimmer Wohnung mit Terrasse in Salzburg."
    result = service._send_property_scout_queued_notification(
        kind="hit",
        kwargs={
            "principal_id": principal_id,
            "actor": "test",
            "title": title,
            "summary": summary,
            "counterparty": "Willhaben | Austria | Rent | 1010 Vienna",
            "account_email": "",
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
            "source_ref": "property-scout:whatsapp-salzburg-dirty-scope",
            "assessment": {"fit_score": 82.0, "recommendation": "review"},
            "fit_score": 82.0,
            "preference_person_id": "self",
            "review_url": "/app/research/wrong-area",
            "tour_result": {"status": "skipped", "tour_url": ""},
            "candidate_properties": (
                {
                    "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/demo-1631373932/",
                    "listing_title": title,
                    "summary": summary,
                    "source_platform": "willhaben",
                    "source_family": "core_portal",
                    "property_facts_json": {
                        "postal_name": "1010 Vienna",
                        "source_scope_location": "1010 Vienna",
                        "source_postal_code": "1010",
                        "source_city": "Vienna",
                        "price_display": "€ 1.190",
                    },
                },
            ),
            "requested_location_hints": (),
            "requested_country_code": "AT",
            "requested_region_code": "vienna",
        },
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert repair_tasks
    assert repair_tasks[0].priority == "urgent"
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "location_scope"
    diagnostics = dict(repair_tasks[0].input_json or {}).get("diagnostics") or {}
    assert diagnostics["location_hints"] == ["1010 Vienna"]
    assert diagnostics["location_evidence_kind"] == "url_region"
    packet_service = build_fliplink_packet_service(client.app.state.container)
    sent_events = packet_service.list_events(principal_id=principal_id, event_type="heyy_whatsapp_template_sent", limit=10)
    assert sent_events == []


def test_property_scout_queued_near_miss_respects_nontelegram_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-scout-near-miss-whatsapp-preference"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Near Miss Preference")
    updated = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "whatsapp", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )
    assert updated.status_code == 303, updated.text
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("near-miss prompts must not leak to Telegram when WhatsApp is selected"),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._send_property_scout_queued_notification(
        kind="near_miss",
        kwargs={
            "principal_id": principal_id,
            "actor": "test",
            "title": "Near miss",
            "summary": "Strong candidate held by a soft filter.",
            "counterparty": "Willhaben",
            "property_url": "https://example.test/property",
            "source_ref": "property-scout:near-miss",
            "preference_person_id": "self",
            "failed_filter_key": "max_distance_to_supermarket_m",
            "failed_filter_label": "supermarket distance",
            "prefilter_score": 84.0,
        },
    )

    assert result == {"status": "suppressed", "reason": "preferred_channel_whatsapp"}


def test_property_scout_queued_hit_delivers_to_all_selected_channels_with_explicit_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "cf-email:multichannel-primary@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Multichannel Primary")
    updated = client.post(
        "/app/api/property/account/notifications",
        data={
            "notification_channels": ["email", "whatsapp"],
            "preferred_channel": "whatsapp",
            "whatsapp_ai_support_phone": "+43 664 791 6419",
        },
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )
    assert updated.status_code == 303, updated.text
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_PROPERTY_MATCH", "tmpl-property-match")
    observed_email: dict[str, object] = {}
    observed_whatsapp: dict[str, object] = {}
    monkeypatch.setattr(product_service, "email_delivery_enabled", lambda: True)
    monkeypatch.setattr(
        product_service,
        "send_property_match_email",
        lambda **kwargs: observed_email.update(kwargs) or SimpleNamespace(provider="test-email", message_id="email-1"),
    )
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: observed_whatsapp.update(kwargs)
        or {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "",
            "message_id": "msg-whatsapp-multi-1",
            "delivery_status": "queued",
        },
    )
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("telegram must not receive a hit when it is not selected"),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._send_property_scout_queued_notification(
        kind="hit",
        kwargs={
            "principal_id": principal_id,
            "actor": "test",
            "title": "Wohnung mieten in 1010 Wien | 85 m² | 3 Zimmer | EUR 1.900",
            "summary": "3-Zimmer Wohnung im 1. Bezirk, 85 m2, Gesamtmiete EUR 1.900.",
            "counterparty": "Willhaben | Austria | Rent | 1010 Vienna",
            "account_email": "",
            "property_url": "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1010-innere-stadt/high-fit/",
            "source_ref": "property-scout:multichannel-hit",
            "assessment": {"fit_score": 91.0, "recommendation": "shortlist"},
            "fit_score": 91.0,
            "preference_person_id": "self",
            "review_url": "/app/research/high-fit",
            "tour_result": {"status": "skipped", "tour_url": ""},
            "candidate_properties": (),
            "requested_location_hints": ("1010 Vienna",),
            "requested_country_code": "AT",
            "requested_region_code": "vienna",
        },
    )

    assert result["status"] == "sent"
    assert result["channel"] in {"whatsapp", "email"}
    assert set(result["delivery_results"]) == {"email", "whatsapp"}
    assert result["delivery_results"]["email"]["status"] == "sent"
    assert result["delivery_results"]["whatsapp"]["status"] == "sent"
    assert observed_whatsapp["phone_number"] == "+436647916419"


def test_property_scout_queued_near_miss_uses_explicit_primary_not_checkbox_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-scout-near-miss-explicit-primary"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Near Miss Explicit Primary")
    updated = client.post(
        "/app/api/property/account/notifications",
        data={
            "notification_channels": ["telegram", "whatsapp"],
            "preferred_channel": "whatsapp",
            "whatsapp_ai_support_phone": "+43 664 791 6419",
        },
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )
    assert updated.status_code == 303, updated.text
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: pytest.fail("near-miss prompts must respect explicit primary, not checkbox order"),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service._send_property_scout_queued_notification(
        kind="near_miss",
        kwargs={
            "principal_id": principal_id,
            "actor": "test",
            "title": "Near miss",
            "summary": "Strong candidate held by a soft filter.",
            "counterparty": "Willhaben",
            "property_url": "https://example.test/property",
            "source_ref": "property-scout:near-miss-explicit-primary",
            "preference_person_id": "self",
            "failed_filter_key": "max_distance_to_supermarket_m",
            "failed_filter_label": "supermarket distance",
            "prefilter_score": 84.0,
        },
    )

    assert result == {"status": "suppressed", "reason": "preferred_channel_whatsapp"}


def test_property_search_run_postgres_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(property_search_storage, "_PROPERTY_SEARCH_RUN_SCHEMA_READY", False)
    run_id = f"run-postgres-round-trip-{uuid.uuid4().hex}"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id="exec-property-postgres-round-trip",
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "processed"
    state["progress"] = 100

    product_service._store_property_search_run_record(state)
    loaded = product_service._load_property_search_run_record(
        run_id=run_id,
        principal_id="exec-property-postgres-round-trip",
    )
    listed = product_service._list_property_search_run_records(
        limit=5,
        statuses=("processed",),
        principal_id="exec-property-postgres-round-trip",
    )

    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["principal_id"] == "exec-property-postgres-round-trip"
    assert loaded["property_search_preferences"]["country_code"] == "AT"
    assert any(row.get("run_id") == run_id for row in listed)


def test_property_search_run_postgres_retention_compacts_without_deleting_saved_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS", "60")
    monkeypatch.setattr(property_search_storage, "_PROPERTY_SEARCH_RUN_SCHEMA_READY", False)
    run_id = f"run-postgres-retention-{uuid.uuid4().hex}"
    principal_id = "exec-property-postgres-retention"
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "1010 Vienna"},
        force_refresh=False,
    )
    state["status"] = "completed"
    state["created_at"] = old_timestamp
    state["updated_at"] = old_timestamp
    state["summary"] = {
        "status": "completed",
        "ranked_total": 1,
        "ranked_candidates": [{"candidate_ref": "saved-result", "title": "Saved result"}],
        "sources": [{"source_label": "Willhaben", "source_html": "<html>discard me</html>"}],
    }

    try:
        product_service._store_property_search_run_record(state)
        property_search_storage._prune_property_search_run_records()

        loaded = product_service._load_property_search_run_record(run_id=run_id, principal_id=principal_id)
        listed = product_service._list_property_search_run_records(
            limit=5,
            principal_id=principal_id,
            lightweight=True,
        )
    finally:
        product_service._delete_property_search_run_record(run_id=run_id, principal_id=principal_id)

    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["principal_id"] == principal_id
    assert loaded["payload_retention_status"] == "compact_only"
    assert loaded["summary"]["ranked_candidates"] == [{"candidate_ref": "saved-result", "title": "Saved result"}]
    assert "sources" not in loaded["summary"]
    assert any(row.get("run_id") == run_id for row in listed)


def test_property_search_run_listing_requires_principal_unless_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    registry = {
        "run-1": {"run_id": "run-1", "principal_id": "principal-a", "status": "processed", "updated_at": "2026-06-18T00:00:00+00:00"},
        "run-2": {"run_id": "run-2", "principal_id": "principal-b", "status": "processed", "updated_at": "2026-06-18T00:01:00+00:00"},
    }

    assert property_search_storage._list_property_search_run_records(limit=10, registry=registry) == ()
    principal_rows = property_search_storage._list_property_search_run_records(
        limit=10,
        principal_id="principal-a",
        registry=registry,
    )
    admin_rows = property_search_storage._list_property_search_run_records(
        limit=10,
        admin=True,
        registry=registry,
    )

    assert [row["run_id"] for row in principal_rows] == ["run-1"]
    assert [row["run_id"] for row in admin_rows] == ["run-2", "run-1"]


def test_property_search_run_lightweight_listing_strips_source_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    registry = {
        "run-compact": {
            "run_id": "run-compact",
            "principal_id": "principal-a",
            "status": "completed_partial",
            "updated_at": "2026-06-18T00:00:00+00:00",
            "property_search_preferences": {
                "country_code": "AT",
                "location_query": "1010 Vienna",
                "raw_preferences": {"huge": "x" * 1000},
                "saved_shortlist_candidates": [{"candidate_ref": "saved"}],
                "search_agents": [{"id": "agent"}],
            },
            "summary": {
                "status": "completed_partial",
                "sources_total": 104,
                "listing_total": 304,
                "ranked_total": 2,
                "filtered_total": 270,
                "ranked_candidates": [{"candidate_ref": "ranked-1", "title": "Kept"}],
                "sources": [
                    {
                        "source_label": "Willhaben",
                        "source_html": "<html>" + ("x" * 1000) + "</html>",
                        "top_candidates": [{"candidate_ref": "source-cand"}],
                    }
                ],
                "events": [{"message": "large diagnostic"}],
            },
        }
    }

    rows = property_search_storage._list_property_search_run_records(
        limit=10,
        principal_id="principal-a",
        lightweight=True,
        registry=registry,
    )

    assert len(rows) == 1
    summary = rows[0]["summary"]
    assert rows[0]["run_id"] == "run-compact"
    assert rows[0]["property_search_preferences"]["location_query"] == "1010 Vienna"
    assert "raw_preferences" not in rows[0]["property_search_preferences"]
    assert "saved_shortlist_candidates" not in rows[0]["property_search_preferences"]
    assert "search_agents" not in rows[0]["property_search_preferences"]
    assert summary["sources_total"] == 104
    assert summary["ranked_candidates"] == [{"candidate_ref": "ranked-1", "title": "Kept"}]
    assert "sources" not in summary
    assert "events" not in summary


def test_property_search_run_upsert_does_not_change_existing_owner() -> None:
    source = Path(property_search_storage.__file__).read_text(encoding="utf-8")

    assert "PRIMARY KEY (principal_id, run_id)" in source
    assert "ALTER TABLE property_search_runs ADD PRIMARY KEY (principal_id, run_id)" in source
    assert "SET principal_id = EXCLUDED.principal_id" not in source
    assert "ON CONFLICT (run_id)" not in source
    assert "ON CONFLICT (principal_id, run_id) DO UPDATE" in source
    assert "payload_retention_status" in source
    assert "compact_only" in source
    assert "UPDATE property_search_runs AS runs" in source
    assert "DELETE FROM property_search_runs WHERE updated_at < %s" not in source


def test_property_source_listing_cache_postgres_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "postgres")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")
    monkeypatch.setattr(property_search_storage, "_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY", False)
    cache_key = f"willhaben:postgres-round-trip:{uuid.uuid4().hex}"
    listing_urls = (
        "https://www.willhaben.at/iad/object?adId=postgres-cache-1",
        "https://www.willhaben.at/iad/object?adId=postgres-cache-2",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0

    stored = product_service._property_source_listing_cache_put(
        cache_key,
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=85",
        listing_urls=listing_urls,
        source_spec={"provider_filter_pushdown": {"cache_key": cache_key, "min_area_m2": 85}},
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()

    cached_urls, cached_state = product_service._property_source_listing_cache_get(cache_key)

    assert stored["persistence"] == "postgres"
    assert cached_urls == listing_urls
    assert cached_state["status"] == "hit"
    assert cached_state["persistence"] == "postgres"
    assert cached_state["listing_total"] == 2


def test_property_search_storage_schema_scripts() -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")

    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = "ea"

    migrate = subprocess.run(
        ["python3", "scripts/migrate_property_search_storage.py"],
        cwd="/docker/property",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrate.returncode == 0, migrate.stderr or migrate.stdout

    check = subprocess.run(
        ["python3", "scripts/check_property_search_storage_schema.py"],
        cwd="/docker/property",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout


def test_property_search_storage_schema_check_enforces_tenant_primary_key() -> None:
    source = Path("scripts/check_property_search_storage_schema.py").read_text(encoding="utf-8")

    assert "idx_property_search_runs_principal_updated" in source
    assert "_check_source_contracts()" in source
    assert "ON CONFLICT (principal_id, run_id) DO UPDATE" in source
    assert "payload_retention_status" in source
    assert "compact_only" in source
    assert "UPDATE property_search_runs AS runs" in source
    assert "SET principal_id = EXCLUDED.principal_id" in source
    assert "forbidden_storage_contract" in source
    assert "if not normalized_principal_id and not admin:" in source
    assert "run_primary_key != (\"principal_id\", \"run_id\")" in source
    assert "invalid_primary_key:property_search_runs" in source


def test_property_search_storage_schema_check_runs_source_contracts_without_database() -> None:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = "ea"

    result = subprocess.run(
        ["python3", "scripts/check_property_search_storage_schema.py"],
        cwd="/docker/property",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "source contracts look ready" in result.stdout
