from __future__ import annotations

import re
from pathlib import Path

from app.api.routes import landing as landing_routes
from app.product.models import HandoffNote
from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def test_propertyquarry_app_templates_do_not_reintroduce_legacy_dark_theme_tokens() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_paths = [
        repo_root / "ea/app/templates/base_console.html",
        repo_root / "ea/app/templates/console_shell.html",
        repo_root / "ea/app/templates/app/object_detail.html",
        repo_root / "ea/app/templates/app/people_detail.html",
        repo_root / "ea/app/templates/app/commitment_candidate_review.html",
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
    ]
    forbidden_tokens = (
        "rgba(18, 23, 34",
        "rgba(15, 19, 26",
        "rgba(49, 60, 77",
        "#070a10",
        "#0a0d14",
        "#0b1017",
        "360 not ready",
        "not scheduled yet",
    )
    for template_path in template_paths:
        body = template_path.read_text(encoding="utf-8")
        assert "background: var(--panel);" in body or "background: var(--pq-paper);" in body
        for token in forbidden_tokens:
            assert token not in body, f"{token!r} leaked into {template_path.relative_to(repo_root)}"


def test_propertyquarry_object_detail_template_exposes_opt_in_magic_fit_panel() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "Open Magic Fit" in body
    assert "Upload reference photos" in body
    assert "Use Google Photos Picker" in body
    assert "Attach the generated still to the packet PDF dossier" in body


def test_propertyquarry_workspace_routes_render_greenfield_surfaces(monkeypatch) -> None:
    principal_id = "pq-redesign-browser"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text
    profile_node = client.post(
        "/app/api/people/elisabeth/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "prefer_balcony",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.9,
        },
    )
    assert profile_node.status_code == 200, profile_node.text

    top_candidate = {
        "title": "Altbau near U6",
        "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
        "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
        "compare_reason": "Chosen ahead of the next option because it scored 5 points higher on the current brief; it includes a floorplan while the next option does not.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-1",
        "tour_url": "https://propertyquarry.com/tours/altbau-u6",
        "match_reasons": [
            "Includes a live 360 source, which supports remote review after the core fit is already acceptable.",
            "Lift and transit fit.",
        ],
        "mismatch_reasons": [],
        "property_facts": {
            "price_display": "EUR 420,000",
            "price_eur": 420000.0,
            "rooms": 3,
            "area_m2": 78,
            "postal_name": "Berlin Mitte",
            "street_address": "Invalidenstrasse 14",
            "map_lat": 52.531,
            "map_lng": 13.384,
            "nearest_supermarket_m": 280,
            "nearest_supermarket_name": "Demo Supermarket",
            "nearest_supermarket_lat": 52.532,
            "nearest_supermarket_lng": 13.385,
            "nearest_pharmacy_m": 410,
            "nearest_library_m": 360,
            "nearest_running_m": 640,
            "nearest_tram_bus_m": 190,
            "nearest_playground_m": 520,
            "nearest_starbucks_m": 340,
            "nearest_fitness_center_m": 460,
            "nearest_cinema_m": 690,
            "nearest_bouldering_m": 880,
            "nearest_subway_m": 1200,
            "listing_research_snapshot": {
                "street_address": "Invalidenstrasse 14",
                "nearest_supermarket_m": 280,
                "map_lat": 52.531,
            },
            "listing_research_meta": {
                "strategy": "provider_html_plus_geo",
            },
            "official_risk_evidence": {
                "country_code": "AT",
                "updated_at": "2026-06-08T18:30:00+00:00",
                "sources": [
                    {
                        "label": "Air quality",
                        "authority_label": "Stadt Wien",
                        "provider": "data.gv.at / Stadt Wien",
                        "source_label": "Luftmessnetz: aktuelle Messdaten Wien",
                        "source_url": "https://www.data.gv.at/datasets/d9ae1245-158e-4d79-86a4-2d9b3defbedc?locale=de",
                        "availability": "official_dataset",
                        "verification_state": "flagged",
                        "confidence": "medium",
                        "summary": "Official city air-quality measurements should anchor the pollution read for this micro-location.",
                        "required_next_step": "Cross-check the nearest station before treating air burden as resolved.",
                    },
                    {
                        "label": "Flood exposure",
                        "authority_label": "Hochwasserrichtlinie",
                        "provider": "data.gv.at / Hochwasserrichtlinie",
                        "source_label": "Überflutungsflächen HQ30, HWRL",
                        "source_url": "https://www.data.gv.at/datasets/84372374-996a-4d7c-a7ee-9b063d9a7282?locale=de",
                        "availability": "official_dataset",
                        "verification_state": "needs_review",
                        "confidence": "high",
                        "summary": "Official HQ30 and flood-zone evidence should anchor the flood-risk read.",
                    },
                    {
                        "label": "Parking pressure",
                        "authority_label": "Municipal parking authority",
                        "provider": "municipal parking data",
                        "source_label": "Municipal parking-regulation evidence required",
                        "availability": "municipal_gap",
                        "verification_state": "source_gap",
                        "confidence": "low",
                        "summary": "A municipality-specific parking source is still missing for this micro-location.",
                        "required_next_step": "Attach a municipality-specific parking-zone source before clearing parking pressure.",
                    },
                ],
            },
            "future_change_research": {
                "school_atlas_quality_summary": "Nearby SchoolAtlas schools: Volksschule Beispiel (VS, 280 m, 240 students)",
                "school_atlas_progression_summary": "Nearest transition-capable school Volksschule Beispiel shows 64 disclosed outgoing transitions; about 62.5% lead to Gymnasium/AHS.",
                "school_atlas_evidence_type": "hard_public_data",
                "school_atlas_source_url": "https://www.statistik.at/atlas/schulen/",
            },
        },
    }
    second_candidate = {
        "title": "Family flat near Tiergarten",
        "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
        "fit_summary": "Personal fit 87/100 · shortlist · Larger layout and quieter block.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-2",
        "tour_url": "",
        "tour_status": "skipped",
        "match_reasons": ["Larger layout and quieter block."],
        "mismatch_reasons": ["No 360 tour yet."],
        "property_facts": {
            "price_display": "EUR 465,000",
            "price_eur": 465000.0,
            "rooms": 4,
            "area_m2": 92,
            "postal_name": "Berlin Tiergarten",
            "has_floorplan": False,
            "floorplan_count": 0,
        },
    }
    queued_candidate = {
        "title": "Courtyard loft with pending tour",
        "property_url": "https://www.immobilienscout24.de/expose/courtyard-loft",
        "fit_summary": "Personal fit 83/100 · shortlist · Quiet courtyard and strong transit.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-3",
        "tour_url": "",
        "tour_status": "queued",
        "tour_eta_minutes": 12,
        "match_reasons": ["Quiet courtyard and strong transit."],
        "mismatch_reasons": ["Hosted 360 is not ready yet."],
        "property_facts": {
            "price_display": "EUR 438,000",
            "price_eur": 438000.0,
            "rooms": 3,
            "area_m2": 81,
            "postal_name": "Berlin Moabit",
            "has_floorplan": True,
            "has_360": True,
        },
    }
    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-redesign-browser"
        assert run_id == "run-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "research_task_total": 1,
            "open_research_task_total": 1,
            "filled_research_task_total": 0,
            "dismissed_research_task_total": 0,
            "research_tasks": [
                {
                    "task_id": "mf_rooms_run_42",
                    "field": "rooms",
                    "label": "Rooms",
                    "status": "queued",
                    "priority": "high",
                    "title": "Family flat near Tiergarten",
                    "source_label": "ImmoScout24 Germany",
                    "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-2",
                    "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
                    "fit_score": 87,
                    "display_value": "Room count not verified yet",
                    "evidence": "Floorplan exists, but no structured room count was extracted yet.",
                    "next_actions": ["Parse the floorplan and source PDF bundle."],
                }
            ],
            "summary": {
                "sources_total": 2,
                "listing_total": 7,
                "tour_created_total": 1,
                "tour_existing_total": 1,
                "review_created_total": 1,
                "packet_created_total": 1,
                "telegram_sent_total": 1,
                "research_task_total": 1,
                "open_research_task_total": 1,
                "dossier_writer_neuronwriter_status": "pending",
                "notification_budget": {
                    "limit": 1,
                    "period": "day",
                    "sent_in_window": 0,
                    "remaining_after_run": 0,
                },
                "notification_budget_suppressed_total": 2,
                "sources": [
                        {
                            "source_label": "ImmoScout24 Germany",
                            "listing_total": 4,
                            "high_fit_total": 2,
                            "tour_created_total": 1,
                            "notified_total": 1,
                            "filtered_low_fit_total": 3,
                            "filtered_floorplan_total": 1,
                            "location_mismatch_candidate_total": 2,
                            "location_mismatch_reason": "provider_returned_candidates_outside_selected_location",
                            "review_created_total": 1,
                            "provider_repair_task_opened_total": 1,
                            "provider_repair_task_existing_total": 0,
                            "provider_repair_tasks": [{"repair_owner": "ea_one_manager"}],
                            "provider_filter_pushdown": {
                                "filter_strength": "weak_search_then_post_filter",
                                "post_filter_only": ["min_area_m2"],
                            },
                            "provider_quality": {
                                "floorplan_reliability": "medium",
                                "filter_pushdown_strength": "partial",
                                "last_verified": "2026-06-13",
                            },
                            "dossier_writer_neuronwriter_status": "pending",
                            "notification_budget_suppressed_total": 2,
                            "top_candidates": [top_candidate, second_candidate, queued_candidate],
                        }
                    ],
                },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 source(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-browser"
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for Auhofstrasse shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="https://propertyquarry.com/tours/auhofstrasse-14997053",
            ),
        )

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)
    monkeypatch.setattr(landing_routes, "_property_investment_research_access_level", lambda *args, **kwargs: "full")
    monkeypatch.setattr(
        landing_routes,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 420000.0,
            "current_area_sqm": 78.0,
            "current_price_per_sqm_eur": 5384.62,
            "market_buy_per_sqm_eur": 5600.0,
            "market_buy_delta_pct": -3.8,
            "market_rent_per_sqm_eur": 19.5,
            "expected_monthly_rent_eur": 1521.0,
            "gross_yield_pct": 4.35,
            "payback_years": 23.0,
            "buy_sample_count": 3,
            "rent_sample_count": 2,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 5600.0, "source_label": "ImmoScout24 Germany"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 19.5, "source_label": "ImmoScout24 Germany"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    setup = client.get("/app/properties", headers=headers)
    assert setup.status_code == 200
    assert 'data-range-control="max_price_eur"' in setup.text
    assert 'data-range-control="min_rooms"' in setup.text
    assert 'data-range-control="min_area_m2"' in setup.text
    assert 'data-range-control="available_within_years"' in setup.text
    assert 'data-range-control="max_results_per_source"' in setup.text
    assert 'data-range-control="min_match_score"' in setup.text
    assert 'data-range-format="currency_eur"' in setup.text
    assert 'data-range-format="area_m2"' in setup.text
    assert 'data-range-empty-label="Any budget"' in setup.text
    assert 'data-range-preset="listing_mode_price"' in setup.text
    assert "Max budget" in setup.text
    assert 'value="office"' in setup.text
    assert "Office" in setup.text
    assert 'data-tooltip-trigger' in setup.text
    assert 'aria-expanded="false"' in setup.text
    assert "Set a hard budget ceiling. Leave it at Any budget when you want PropertyQuarry to rank first and filter price later." in setup.text
    assert 'data-school-stage-variant' in setup.text
    assert 'data-school-stage-parent' in setup.text
    assert 'data-kindergarten-parent' in setup.text
    assert 'data-kindergarten-variant' in setup.text
    assert "Checked school types are treated as OR matches." in setup.text
    assert "Select Volksschule to reveal Ganztags- and Halbtagsvolksschule variants." in setup.text
    assert "Select Kindergarten to reveal public and private kindergarten options." in setup.text
    assert 'data-checkbox-group-select-all="selected_platforms"' in setup.text
    assert "Select all" in setup.text
    assert "Notverkauf und Justiz" in setup.text
    assert "Justiz Edikte" in setup.text
    assert 'data-property-advanced-panel="children"' in setup.text
    assert 'data-property-advanced-panel="commute"' in setup.text
    assert 'data-property-advanced-panel="location_research"' in setup.text
    assert "Erweiterte Kinder- und Familienfilter" in setup.text
    assert "Erweiterte Lage- und Researchfilter" in setup.text
    assert 'name="max_distance_to_library_m"' in setup.text
    assert 'name="max_distance_to_library_importance"' in setup.text
    assert 'name="max_distance_to_playground_importance"' in setup.text
    assert 'name="max_distance_to_supermarket_m"' in setup.text
    assert 'name="max_distance_to_supermarket_importance"' in setup.text
    assert "Supermarket nearby means" in setup.text
    assert "If good matches are scarce" in setup.text
    assert 'name="max_distance_to_zoo_m"' in setup.text
    assert 'name="max_distance_to_market_m"' in setup.text
    assert 'name="max_distance_to_hardware_store_m"' in setup.text
    assert 'name="max_distance_to_shopping_center_m"' in setup.text
    assert 'name="max_distance_to_shopping_street_m"' in setup.text
    assert 'name="max_distance_to_theatre_m"' in setup.text
    assert 'name="max_distance_to_public_pool_m"' in setup.text
    assert 'name="max_distance_to_medical_care_m"' in setup.text
    assert 'name="prefer_good_air_quality"' in setup.text
    assert 'name="prefer_low_crime_area"' in setup.text
    assert 'name="require_drinking_water_quality_research"' in setup.text
    assert 'name="require_parking_pressure_check"' in setup.text
    assert 'name="avoid_cesspit_or_septic_risk"' in setup.text
    assert 'name="require_winter_access_research"' in setup.text
    assert 'name="avoid_flood_risk_area"' in setup.text
    assert 'name="school_stage_preferences"' in setup.text
    assert 'value="volksschule"' in setup.text
    assert 'value="kindergarten"' in setup.text
    assert 'value="public_kindergarten"' in setup.text
    assert 'value="private_kindergarten"' in setup.text
    assert 'value="ganztags_volksschule"' in setup.text
    assert 'value="halbtags_volksschule"' in setup.text
    assert 'data-property-show-unavailable' in setup.text
    assert 'No practical zoo or Tiergarten signal is configured for this market yet.' in setup.text
    assert "Min area" in setup.text
    assert "Search agents" in setup.text
    assert "Keep a search running, cap the number of messages" in setup.text
    assert "Last:" in setup.text
    assert "Next:" in setup.text
    assert "Sent 0/" in setup.text
    assert "Resume" in setup.text
    assert "Save limits" in setup.text
    assert "Duplicate" in setup.text
    assert "Delete" in setup.text
    assert "Run now" in setup.text
    assert 'data-search-agent-id="' in setup.text
    assert 'data-search-agent-action="resume"' in setup.text
    assert 'data-search-agent-action="duplicate"' in setup.text
    assert 'data-search-agent-action="delete"' in setup.text
    assert 'data-search-agent-action="run"' in setup.text

    search = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert search.status_code == 200
    assert 'data-property-app-shell' in search.text
    assert 'data-property-spa-shell' in search.text
    assert 'data-property-pulse-strip' in search.text
    assert 'data-property-mobile-dock' in search.text
    assert 'data-property-decision-workbench' in search.text
    assert 'data-pq-greenfield-shell' in search.text
    assert 'data-pq-theater' in search.text
    assert 'data-workbench-results-table' in search.text
    assert 'data-workbench-dossier' in search.text
    assert 'data-workbench-row' in search.text
    assert '<a class="pqx-result"' not in search.text
    assert '<button class="pqx-result"' in search.text
    assert "Best homes first" in search.text
    assert "Match" in search.text
    assert "Source" in search.text
    assert "Map" in search.text
    assert "https://www.google.com/maps/search/?api=1" in search.text
    assert "https://www.google.com/maps/dir/?api=1" in search.text
    assert "Evidence" in search.text
    assert "CART" in search.text
    assert "Supermarket" in search.text
    assert "280 m" in search.text
    assert 'class="pqx-route-evidence"' in search.text
    assert 'class="pqx-thumb"' in search.text
    assert "ranked homes" in search.text
    assert "price, layout, location, fit reason, and next action stay visible" in search.text
    assert "Altbau near U6" in search.text
    assert "Family flat near Tiergarten" in search.text
    assert "360 ready" in search.text
    assert "360 unavailable" in search.text
    assert "360 queued" in search.text
    assert "about 12 min" in search.text
    assert 'data-tour-status="queued"' in search.text
    assert 'data-tour-eta="about 12 min"' in search.text
    assert "Floorplan missing" in search.text
    assert "not scheduled yet" not in search.text
    assert "360 not ready" not in search.text
    assert "360" in search.text
    assert "Match" in search.text
    assert "Price" in search.text
    assert "Layout" in search.text
    assert "Quick read" in search.text
    assert "Playground" in search.text
    assert "Supermarket" in search.text
    assert "Starbucks" in search.text
    assert "Fitness" in search.text
    assert "Cinema" in search.text
    assert "Bouldering" in search.text
    assert "SchoolAtlas" in search.text
    assert "Gymnasium path" in search.text
    assert "Why it fits" in search.text
    assert "What to check" in search.text
    assert "Official checks" in search.text
    assert "Manual clearance required" in search.text
    assert "How this result was prepared" in search.text
    assert 'data-pw-artifact-receipts' in search.text
    assert "Send checklist" in search.text
    assert "Artifact receipts" not in search.text
    assert "What must be true before a packet is sent" in search.text
    assert "Fallback cube viewers are forbidden" in search.text
    assert "Every outbound link must be sent as a titled hyperlink" in search.text
    assert "Your decision" in search.text
    assert "Would you pursue this property?" in search.text
    assert "Viewing requested" in search.text
    assert "Documents requested" in search.text
    assert "Offer candidate" in search.text
    assert "Save decision" in search.text
    assert "Ask a question" in search.text
    assert "Household review" in search.text
    assert "Agent follow-up" in search.text
    assert "Contradicted" in search.text
    assert "Resolved" in search.text
    assert "What changed" in search.text
    assert "Top objections" in search.text
    assert "Market warnings" in search.text
    assert "Timeline" in search.text
    assert "Source quality" in search.text
    assert "Delivery status" in search.text
    assert "Delivery proof" not in search.text
    assert "Writing quality check" in search.text
    assert "Message links" in search.text
    assert "Generated files" in search.text
    assert "NeuronWriter editorial pass" not in search.text
    assert "Telegram links" not in search.text
    assert "Generated asset receipts" not in search.text
    assert "repair check queued" not in search.text
    assert "Repair: ea_one_manager" not in search.text
    assert "layout check" in search.text or "layout not verified" in search.text
    assert "Repair provider extraction" not in search.text
    assert "Missing facts" not in search.text
    assert "Facts still being completed from floorplans" not in search.text
    assert "Needs verification" in search.text
    assert "Items that can change the decision" in search.text
    assert "Room count not verified yet" in search.text
    assert "Save answer" in search.text
    assert "Save fact" not in search.text
    assert 'data-pqx-progress-board' in search.text
    assert "Concierge is assembling the evidence" in search.text or "Evidence assembled" in search.text
    assert 'class="pqx-source-radar"' in search.text
    assert 'class="pqx-funnel"' in search.text
    assert 'class="pqx-evidence-stack"' in search.text
    assert 'class="pqx-route-trace"' in search.text
    assert 'class="pqx-floorplan-scan"' in search.text
    assert 'class="pqx-dossier-rail"' in search.text
    assert 'data-research-task-id="mf_rooms_run_42"' in search.text
    assert 'data-research-task-action="fill"' in search.text
    assert 'data-research-task-action="dismiss"' in search.text
    assert "EUR 5,385/m2" in search.text
    assert "Open 360" in search.text
    assert "Chosen ahead of the next option because it scored 5 points higher on the current brief" in search.text
    assert "Preferred because: Lift and transit fit." in search.text
    assert "Preferred because: Includes a live 360 source" not in search.text
    assert "Review details" in search.text
    assert 'data-candidate-packet-url="/app/research/' in search.text
    assert 'data-pqx-notification-audit' in search.text
    assert "Alert delivery" in search.text
    assert "Held back" in search.text
    assert "2 candidates held back after ranking" in search.text
    assert "Search guard" in search.text
    assert "Target area guard" in search.text
    assert "Outside-area results suppressed" in search.text
    assert "Provider filters needed cleanup" in search.text
    assert "Floorplan gate" in search.text
    assert "Held back by rules" in search.text
    assert "Missing floorplan" in search.text
    assert "Below fit threshold" in search.text
    assert "Outside selected area" in search.text
    assert "Alert budget" in search.text
    assert "Floorplans medium" in search.text
    assert "Filters partial" in search.text
    assert "Verified 2026-06-13" in search.text
    assert "Manage saved search" in search.text
    assert "Launch search" not in search.text
    assert "Morning Memo" not in search.text
    assert "Office signals ingested" not in search.text
    family_candidate_ref = landing_routes._property_candidate_ref(
        {
            "title": str(second_candidate.get("title") or "").strip(),
            "property_url": str(second_candidate.get("property_url") or "").strip(),
            "review_url": str(second_candidate.get("review_url") or "").strip(),
            "tour_url": str(second_candidate.get("tour_url") or "").strip(),
            "source_label": "ImmoScout24 Germany",
        }
    )
    selected_candidate = client.get(
        "/app/properties",
        params={"run_id": "run-42", "candidate": family_candidate_ref},
        headers=headers,
    )
    assert selected_candidate.status_code == 200
    assert re.search(r'data-pw-title>\s*Family flat near Tiergarten\s*<', selected_candidate.text) is not None

    shortlist = client.get("/app/shortlist", params={"run_id": "run-42"}, headers=headers)
    assert shortlist.status_code == 200
    assert "Review the properties that deserve attention now." in shortlist.text
    assert "Compare the top shortlist before opening deeper packets" in shortlist.text
    assert "Altbau near U6" in shortlist.text
    assert "Review packet" in shortlist.text
    assert "Review details" in shortlist.text
    assert "Packet follow-up" in shortlist.text
    assert "Hosted review" not in shortlist.text
    assert "Track packet follow-up" not in shortlist.text
    assert "Open feedback" not in shortlist.text

    research = client.get("/app/research", params={"run_id": "run-42"}, headers=headers)
    assert research.status_code == 200
    assert "Inspect the evidence before you open the raw listing." in research.text
    assert "Hosted 3D page for Auhofstrasse shortlist" in research.text
    assert "/app/research/" in research.text
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-42"', research.text)
    assert packet_match is not None

    packet = client.get(packet_match.group(1), params={"run_id": "run-42", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Internal property dossier with fit reasoning" not in packet.text
    assert "Open the space before you read the rest" not in packet.text
    assert "360 review first" not in packet.text
    assert 'data-object-media-stage' in packet.text
    assert 'title="Property 360 review"' in packet.text
    assert packet.text.index("data-object-media-stage") < packet.text.index("Decision summary")
    assert "Live 360 ready" in packet.text
    assert "Decision summary" in packet.text
    assert "Why this was selected" in packet.text
    assert "Nearest supermarket" in packet.text
    assert "https://www.google.com/maps/dir/" not in packet.text
    assert "Open navigation" not in packet.text
    assert "Library" in packet.text
    assert "Nearest run or green space" in packet.text
    assert "Straßenbahn / Bus" in packet.text
    assert "Underground" in packet.text
    assert "Nearest underground" in packet.text
    assert "Decision call" in packet.text
    assert "Why now" in packet.text
    assert "Missing-data severity" in packet.text
    assert "Decision scorecard" in packet.text
    assert "Evidence and provenance" in packet.text
    assert "Authority posture" in packet.text
    assert "Manual clearance required" in packet.text
    assert "Official risk evidence" in packet.text
    assert "Luftmessnetz: aktuelle Messdaten Wien" in packet.text
    assert "Alltagsfit" in packet.text
    assert "Risikofit" in packet.text
    assert "Future-change research" in packet.text
    assert "SchoolAtlas quality" in packet.text
    assert "Gymnasium progression" in packet.text
    assert "Investment research" in packet.text
    assert "Gross yield" in packet.text
    assert "Expected monthly rent" in packet.text
    assert "Open questions" in packet.text
    assert "Compare next" in packet.text
    assert "Candidate" in packet.text
    assert "Layout" in packet.text
    assert "Family flat near Tiergarten" in packet.text
    assert "Researched" in packet.text
    assert "Review page" in packet.text
    assert "Original listing" in packet.text
    assert "Decision feedback" in packet.text
    assert "Decision pipeline" in packet.text
    assert "Official risk evidence" in packet.text
    assert "Would you pursue this property?" in packet.text
    assert "Viewing requested" in packet.text
    assert "Documents requested" in packet.text
    assert "Offer candidate" in packet.text
    assert "Open Clippy" in packet.text
    assert "Ask agent next" in packet.text
    assert "Tracked follow-up" in packet.text
    assert "Decision timeline" in packet.text
    assert "Top objections" in packet.text
    assert "Household review" in packet.text
    assert "Risk signals" in packet.text
    assert "What changed" in packet.text
    assert "Contradicted" in packet.text
    assert "Resolved" in packet.text
    assert 'data-object-feedback-reaction="like"' in packet.text
    assert 'data-object-feedback-save' in packet.text
    assert "Save decision" in packet.text
    assert "Manage preferences" in packet.text
    assert "rgba(18, 23, 34" not in packet.text
    assert "rgba(15, 19, 26" not in packet.text
    assert "background: var(--panel);" in packet.text

    profile = client.get("/app/profile", params={"run_id": "run-42"}, headers=headers)
    assert profile.status_code == 200
    assert "Make the learning loop visible and editable." in profile.text
    assert 'data-property-learning-list' in profile.text
    assert 'data-property-preference-manager' in profile.text
    assert "Prefer Balcony (Soft Preference)" in profile.text
    assert 'data-preference-remove' in profile.text
    assert 'data-preference-add-form' in profile.text
    assert 'name="key" list="pq-preference-key-options"' in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Recent outbound property follow-ups" in alerts.text
    assert "The alert lane should still expose the search brief driving it" in alerts.text

    notifications_preview = client.get("/app/properties/notifications/preview", params={"template": "property_match"}, headers=headers)
    assert notifications_preview.status_code == 200
    assert "Email preview" in notifications_preview.text
    assert "Property match: Altbau near U6" in notifications_preview.text
    assert "PropertyQuarry shortlisted a property match" in notifications_preview.text
    assert "No — tell us why" in notifications_preview.text

    workspace_preview = client.get("/app/properties/notifications/preview", params={"template": "workspace_invitation"}, headers=headers)
    assert workspace_preview.status_code == 200
    assert "Mara invited you to PropertyQuarry" in workspace_preview.text
    assert "Review workspace invite" in workspace_preview.text

    billing = client.get("/app/billing", params={"run_id": "run-42"}, headers=headers)
    assert billing.status_code == 200
    assert "Current commercial state" in billing.text
    assert "Open pricing" in billing.text


def test_property_packets_dashboard_uses_customer_facing_language() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_packets.html"
    body = template_path.read_text(encoding="utf-8")

    assert "Send polished property packets and track the replies." in body
    assert "Packet sharing" in body
    assert "Ready to send" in body
    assert "Privacy checked · PDF ready · Sharing controls active" in body
    assert "Paste shared packet link" in body
    assert "Copy response endpoint" in body
    assert "https://packets.propertyquarry.com/p/..." not in body
    assert "Copy response URL" not in body
    assert "Sharing cockpit" not in body
    assert "Publication queue" not in body
    assert "source_pdf_sha256" not in body
    assert "renderer_version" not in body


def test_property_workbench_recent_reviews_do_not_render_fake_links() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "href=\"{{ packet.get('url') or '#' }}\"" not in body
    assert "packet.get('url')" in body
    assert "pqx-recent-review" in body
    assert "pqx-recent-review-static" in body
    assert "<span class=\"pqx-pill\">{{ packet.get('title') }}</span>" not in body
    assert ".pqx-recent-review" in body
    assert "overflow-wrap: anywhere;" in body


def test_property_workbench_sparse_candidates_do_not_display_raw_urls() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "candidate.get('title') or candidate.get('property_url')" not in body
    assert "candidate?.title || candidate?.property_url" not in body
    assert "source?.source_label || source?.platform || source?.source_url" not in body
    assert "candidate.get('title') or 'Property candidate'" in body
    assert "candidate?.title || 'Property candidate'" in body


def test_property_workspace_source_cards_do_not_display_raw_source_urls() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_workspace.html"
    body = template_path.read_text(encoding="utf-8")

    assert "source.source_label || source.source_url" not in body
    assert "source.source_label || source.platform || 'Provider'" in body


def test_property_search_agents_can_load_saved_filters_into_form() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "data-search-agent-payload" in body
    assert 'data-search-agent-action="load"' in body
    assert "Load filters" in body
    assert "applySearchAgentPayloadToForm" in body
    assert "Saved search loaded. Tweak the filters or run it again." in body
    assert "data-search-agent-loaded-state" in body
    assert "Loaded: ${label}" in body


def test_property_workspace_setup_is_dashboard_first_and_compact() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "Your property search desk." in body
    assert "data-pqx-dashboard-summary" in body
    assert "Saved searches" in body
    assert "Latest run" in body
    assert "Next action" in body
    assert "Recent decisions and reviews" in body
    assert "grid-template-columns: minmax(220px, 320px) minmax(640px, 1fr);" in body
    assert "Tell us what to find." not in body


def test_property_workspace_running_state_explains_slow_provider_checks() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "data-pqx-running-provider-state" in body
    assert "Sources checking" in body
    assert "Checking {{ active_provider_lanes }} source" in body
    assert "area, price, size, and layout rules" in body
    assert "Waiting for the first source result" in body
    assert "The first real source result will replace this message automatically." in body
    assert "Provider checks" not in body
    assert "0 lanes in progress" not in body
    assert "lanes in progress" not in body


def test_propertyquarry_user_facing_copy_avoids_hosted_review_jargon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    checked_paths = [
        repo_root / "ea/app/templates/app/property_workspace.html",
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/propertyquarry_home.html",
        repo_root / "ea/app/templates/pricing_page.html",
        repo_root / "ea/app/api/routes/landing.py",
        repo_root / "ea/app/api/routes/landing_view_models.py",
        repo_root / "ea/app/services/registration_email.py",
    ]

    for path in checked_paths:
        body = path.read_text(encoding="utf-8")
        assert "Hosted review" not in body, str(path)
        assert "hosted-review" not in body, str(path)


def test_propertyquarry_customer_surfaces_avoid_operator_jargon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    checked_paths = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/app/object_detail.html",
        repo_root / "ea/app/api/routes/landing.py",
        repo_root / "ea/app/api/routes/landing_view_models.py",
        repo_root / "ea/app/api/routes/landing_objects.py",
    ]
    forbidden = (
        "Artifact receipts",
        "Delivery proof",
        "NeuronWriter editorial pass",
        "Telegram links",
        "Generated asset receipts",
        "Missing-fact OODA queued.",
        "Open the packet to inspect OODA.",
        '"OODA"',
        ">OODA<",
    )

    for path in checked_paths:
        body = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in body, f"{phrase!r} leaked in {path}"


def test_propertyquarry_project_shape_docs_define_flagship_loop_and_design_gate() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_map = repo_root / "docs/PROPERTYQUARRY_SOURCE_OF_TRUTH_MAP.md"
    tone_guide = repo_root / "docs/PROPERTYQUARRY_TONE_GUIDE.md"
    dossier_art = repo_root / "docs/PREMIUM_DOSSIER_ART_DIRECTION.md"
    design_gate = repo_root / "docs/PROPERTYQUARRY_DESIGN_SYSTEM_GATE.md"
    retention = repo_root / "docs/PROPERTYQUARRY_DATA_RETENTION.md"
    analytics = repo_root / "docs/PROPERTYQUARRY_ANALYTICS_TAXONOMY.md"
    provider_quality = repo_root / "docs/PROPERTYQUARRY_PROVIDER_QUALITY.md"
    failure_ux = repo_root / "docs/PROPERTYQUARRY_FAILURE_UX.md"
    for path in (source_map, tone_guide, dossier_art, design_gate, retention, analytics, provider_quality, failure_ux):
        assert path.exists(), str(path)
        assert path.read_text(encoding="utf-8").strip(), str(path)

    source_body = source_map.read_text(encoding="utf-8")
    assert "Brief -> Search -> Compare -> Dossier -> Tour -> Decide -> Explain why -> Learn" in source_body
    assert "property_decision_ledger" in source_body
    assert "property_evidence_graph" in source_body
    assert "NeuronWriter" in source_body
    assert "private owner/family/agent packets by default" in source_body

    tone_body = tone_guide.read_text(encoding="utf-8")
    assert "raw URLs in message text" in tone_body
    assert "OODA summary" in tone_body
    assert "Decision summary" in tone_body

    dossier_body = dossier_art.read_text(encoding="utf-8")
    assert "cover image or poster visible on page one" in dossier_body
    assert "no artifact status tables" in dossier_body

    design_body = design_gate.read_text(encoding="utf-8")
    assert "no plaintext URLs in Telegram or email body text" in design_body
    assert "show suppressed-candidate summaries" in design_body

    retention_body = retention.read_text(encoding="utf-8")
    assert "private PDFs and signed packet links must be revocable" in retention_body
    assert "raw household feedback is owner-private by default" in retention_body

    analytics_body = analytics.read_text(encoding="utf-8")
    assert "pq.search.started" in analytics_body
    assert "pq.decision.saved" in analytics_body
    assert "signed link token" in analytics_body

    provider_quality_body = provider_quality.read_text(encoding="utf-8")
    assert "floorplan_reliability" in provider_quality_body
    assert "filter_pushdown_strength" in provider_quality_body
    assert "last_verified" in provider_quality_body

    failure_body = failure_ux.read_text(encoding="utf-8")
    assert "human message" in failure_body
    assert "operator detail" in failure_body
    assert "fallback action" in failure_body


def test_propertyquarry_in_progress_run_hides_search_form_and_shows_live_run(monkeypatch) -> None:
    principal_id = "pq-live-run-focus"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Run Focus")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "all_of_vienna": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben", "genossenschaften_at"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "progress": 42,
            "message": "Scoring shortlist candidate 2 of 4 for Willhaben | Austria | Buy | Wien.",
            "summary": {
                "sources_total": 4,
                "listing_total": 6,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [],
            },
            "events": [
                {"step": "source_assessing", "message": "Scoring shortlist candidate 2 of 4 for Willhaben | Austria | Buy | Wien.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    live = client.get("/app/properties", params={"run_id": "run-live"}, headers=headers)
    assert live.status_code == 200
    assert 'data-property-spa-shell' in live.text
    assert 'data-property-decision-workbench' in live.text
    assert 'data-pq-greenfield-shell' in live.text
    assert 'data-pqx-state="running"' in live.text
    assert "Search is running. Inputs are locked." in live.text
    assert 'class="pqx-run-head"' in live.text
    assert live.text.index("data-pqx-progress-ring") < live.text.index("Search is running. Inputs are locked.")
    assert "Search progress" in live.text
    assert "Concierge is assembling the evidence" in live.text
    assert 'data-pqx-progress-board' in live.text
    assert 'class="pqx-source-radar"' in live.text
    assert 'class="pqx-route-trace"' in live.text
    assert "Scoring shortlist candidate 2 of 4" in live.text
    assert "Launch search" not in live.text
    assert "Save defaults" not in live.text


def test_propertyquarry_running_progress_ring_stays_compact_and_top_aligned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    run_hero = re.search(r"\.pqx-run-hero \{(?P<body>.*?)\n    \}", template, re.S)
    assert run_hero is not None
    assert ".pqx-run-head" in template
    assert "grid-template-columns: auto minmax(0, 1fr);" in template
    assert "width: clamp(86px, 10vw, 118px);" in template
    assert "width: 78px;" in template
    assert ".pqx-progress-board" in template
    assert "@keyframes pqxPulseSlide" in template
    assert "@keyframes pqxRouteTrace" in template
    assert "@keyframes pqxScanSweep" in template
    assert "@media (prefers-reduced-motion: reduce)" in template
    assert "align-content: space-between;" not in run_hero.group("body")
    assert "width: min(260px, 58vw);" not in template


def test_propertyquarry_setup_intro_is_compact_and_allows_fact_text_to_wrap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    setup = re.search(r"\.pqx-setup \{(?P<body>.*?)\n    \}", template, re.S)
    setup_intro = re.search(r"\.pqx-setup-intro \{(?P<body>.*?)\n    \}", template, re.S)
    fact = re.search(r"\.pqx-fact \{(?P<body>.*?)\n    \}", template, re.S)
    fact_strong = re.search(r"\.pqx-fact strong \{(?P<body>.*?)\n    \}", template, re.S)

    assert setup is not None
    assert setup_intro is not None
    assert fact is not None
    assert fact_strong is not None
    assert "grid-template-columns: minmax(220px, 320px) minmax(640px, 1fr);" in setup.group("body")
    assert "align-items: start;" in setup.group("body")
    assert "align-content: start;" in setup_intro.group("body")
    assert "padding: clamp(16px, 2vw, 26px);" in setup_intro.group("body")
    assert "min-height: 0;" in fact.group("body")
    assert "overflow-wrap: anywhere;" in fact_strong.group("body")
    assert "white-space: normal;" in fact_strong.group("body")
    assert "white-space: nowrap;" not in fact_strong.group("body")


def test_propertyquarry_workspace_supports_all_of_vienna_toggle() -> None:
    principal_id = "pq-vienna-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Vienna Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "all_of_vienna": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text
    profile_node = client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "prefer_outdoor_space",
            "value_json": True,
            "strength": "high",
            "confidence": 1.0,
        },
    )
    assert profile_node.status_code == 200, profile_node.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-workbench-brief-drawer' in search.text
    assert 'data-property-preference-manager' in search.text
    assert "Search profile" in search.text
    assert "Prefer Outdoor Space (Soft Preference)" in search.text
    assert 'data-preference-remove' in search.text
    assert 'data-preference-add-form' in search.text
    assert 'name="key" list="pqx-preference-key-options"' in search.text
    assert 'name="all_of_vienna" value="true" checked' in search.text
    assert 'name="use_stored_feedback_preferences" value="true" checked' in search.text
    assert "Use stored feedback preferences" in search.text
    assert "Manage feedback preferences" in search.text
    assert "All of Vienna" in search.text
    assert "Freizeit und Alltag" in search.text
    assert "Max distance to Starbucks" in search.text
    assert "Max distance to fitness center" in search.text
    assert "Max distance to cinema" in search.text
    assert "Max distance to bouldering gym" in search.text
    assert "Max distance to dog park" in search.text
    assert "Max distance to good cafe" in search.text
    assert "Research modes" in search.text
    assert "Family mode" in search.text
    assert "Commute reality research" in search.text
    assert "Accepted project stages" in search.text
    assert "Action-readiness research" in search.text
    assert 'name="location_query"' in search.text
    assert re.search(
        r'data-property-field-step="areas" data-property-field-name="location_query" hidden>\s*<div class="pqx-field-title">Target areas</div>',
        search.text,
    )


def test_propertyquarry_workspace_hides_investment_research_for_rent() -> None:
    principal_id = "pq-rent-no-investment-filter"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Rent Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "investment_research_mode": "auto",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'name="investment_research_mode"' not in search.text


def test_propertyquarry_workspace_setup_stays_user_facing() -> None:
    principal_id = "pq-provider-quality"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Property Office")
    response = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert response.status_code == 200
    assert "Your property search desk." in response.text
    assert "Saved searches" in response.text
    assert "Latest run" in response.text
    assert "Build the brief. Then let the agents work." not in response.text


def test_propertyquarry_failed_run_stays_on_activity_surface(monkeypatch) -> None:
    principal_id = "pq-failed-run-visible"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Failed Run Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "Provider returned 403 while fetching Willhaben.",
            "summary": {"sources_total": 1, "listing_total": 0, "tour_created_total": 0, "tour_existing_total": 0, "sources": []},
            "events": [
                {"step": "source_fetching", "message": "Fetching source page for Willhaben.", "status": "in_progress"},
                {"step": "failed", "message": "Provider returned 403 while fetching Willhaben.", "status": "failed"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    page = client.get("/app/properties", params={"run_id": "run-failed"}, headers=headers)
    assert page.status_code == 200
    assert 'data-pqx-state="empty_results"' in page.text
    assert "The search could not finish." in page.text
    assert "Best matches" in page.text
    assert "Provider returned 403 while fetching Willhaben." in page.text
    assert "Ways to get more matches" in page.text
    assert ("Lower the match threshold" in page.text) or ("Reopen the brief with broader constraints" in page.text)
    assert "Search progress" in page.text
    assert 'data-workbench-brief-drawer' not in page.text
    assert "Tell us what to find." not in page.text


def test_propertyquarry_packet_enriches_sparse_candidate_facts_for_investment(monkeypatch) -> None:
    principal_id = "pq-packet-fact-enrichment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Packet Enrichment")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    sparse_candidate = {
        "title": "Familien-Maisonette mit weitläufiger Terrasse und drei Zimmern, 88,48 m², € 659.000,-, (1160 Wien) - willhaben",
        "property_url": "https://www.willhaben.at/iad/object?adId=2113641102",
        "fit_summary": "Sparse candidate facts should still allow underwriting.",
        "recommendation": "shortlist",
        "review_url": "",
        "tour_url": "",
        "match_reasons": ["Location and layout fit."],
        "mismatch_reasons": [],
        "property_facts": {"has_360": False},
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [sparse_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(
        landing_routes,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 659000.0,
            "current_area_sqm": 88.48,
            "current_price_per_sqm_eur": 7448.01,
            "market_buy_per_sqm_eur": 7000.0,
            "market_buy_delta_pct": 6.4,
            "market_rent_per_sqm_eur": 18.5,
            "expected_monthly_rent_eur": 1636.88,
            "gross_yield_pct": 2.98,
            "payback_years": 33.5,
            "buy_sample_count": 4,
            "rent_sample_count": 3,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 7000.0, "source_label": "Willhaben"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 18.5, "source_label": "Willhaben"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-88"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-88"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-88", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Investment research is waiting on core facts" not in packet.text
    assert "Current underwriting base" in packet.text
    assert "Buy-side benchmark" in packet.text
    assert "Gross yield" in packet.text


def test_propertyquarry_workspace_search_surface_keeps_internal_review_link(monkeypatch) -> None:
    principal_id = "pq-redesign-no-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-no-fallback"
        return (
            HandoffNote(
                id="human_task:tour-2",
                queue_item_ref="queue:tour-2",
                summary="Review shortlisted property packet",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_alert_review",
                delivery_reason="Research page is still pending.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="",
            ),
        )

    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Review shortlisted property packet" in response.text


def test_propertyquarry_research_packet_shows_auction_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-auction-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["justiz_edikte_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    auction_candidate = {
        "title": "BG Innere Stadt Wien, 001 50 E 30/25a",
        "summary": "",
        "property_url": "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        "fit_score": 37.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "court": "BG Innere Stadt Wien",
            "court_file_reference": "001 50 E 30/25a",
            "valuation_display": "EUR 310,000",
            "reserve_price_display": "EUR 155,000",
            "occupancy_status": "occupied",
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Justiz Edikte Auctions | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [auction_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_routes, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-auction"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-auction"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-auction", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Court process" in packet.text
    assert "Case reference" in packet.text
    assert "Judicial valuation" in packet.text
    assert "Reserve or deposit" in packet.text
    assert "Judicial sale diligence" in packet.text


def test_propertyquarry_research_packet_shows_cooperative_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-coop-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["genossenschaften_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    coop_candidate = {
        "title": "1210 Wien | Antonie-Lehr-Straße 18 / Leopoldauer Haide Gasse 12",
        "summary": "Miete | 144 units | August 2026 | 37486 registrations",
        "property_url": "https://angebote.sozialbau.at/sobitvX/htmlprospect/home.xhtml?pq_listing=1",
        "fit_score": 52.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "tour_status": "skipped",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "provider_group": "genossenschaften_at",
            "provider_channel": "sozialbau",
            "marketing_type": "Miete",
            "availability_label": "August 2026",
            "registration_count": 37486,
            "postal_name": "1210 Wien",
            "has_floorplan": False,
            "floorplan_count": 0,
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Genossenschaften | Austria | Buy | Wien | Sozialbau Projekte in Bau",
                        "listing_total": 1,
                        "top_candidates": [coop_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_routes, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-coop"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-coop"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-coop", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Provider lane" in packet.text
    assert "Offer posture" in packet.text
    assert "Applicant pressure" in packet.text
    assert "Rental-led cooperative lane" in packet.text
    assert "Extremely high applicant pressure" in packet.text
    assert "360 unavailable" in packet.text
    assert "Floorplan missing" in packet.text
    assert "not scheduled yet" not in packet.text


def test_propertyquarry_settings_hide_generic_google_sync_metrics() -> None:
    client = build_property_client(principal_id="pq-redesign-settings")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    settings = client.get("/app/settings", headers={"host": "propertyquarry.com"})
    assert settings.status_code == 200
    assert "Identity and return access" in settings.text
    assert "Current search brief state" in settings.text
    assert "Operating posture" in settings.text
    assert "Open pricing" in settings.text
    assert "Open security" in settings.text
    assert "Sync runs" not in settings.text
    assert "Last Google sync" not in settings.text
    assert "Office signals ingested" not in settings.text
