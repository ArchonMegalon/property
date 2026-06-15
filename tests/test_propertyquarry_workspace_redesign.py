from __future__ import annotations

import re
from pathlib import Path

from app.api.routes import landing as landing_routes
from app.api.routes import public_tours
from app.api.routes import landing_view_models
from app.product.models import HandoffNote
from app.product.service import ProductService, _property_search_analysis_cap_per_source
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


def test_propertyquarry_results_prefer_real_media_over_generated_diorama_previews() -> None:
    candidate = {
        "preview_image_url": "https://propertyquarry.com/tours/files/demo-tour/diorama-preview.png",
        "property_facts": {
            "media_urls_json": [
                "https://cdn.example.com/provider/photo-1.jpg",
                "https://cdn.example.com/provider/photo-2.jpg",
            ]
        },
    }
    assert landing_view_models._property_candidate_preview_image(candidate) == "https://cdn.example.com/provider/photo-1.jpg"


def test_property_candidate_orientation_preview_uses_openstreetmap_backdrop_for_generic_locations(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_build_scope_boundary_preview", lambda **kwargs: {})
    monkeypatch.setattr(
        landing_view_models,
        "_openstreetmap_static_preview_data_url",
        lambda lat_key, lon_key, zoom=13: "data:image/png;base64,preview",
    )
    preview = landing_view_models._property_candidate_orientation_preview(
        {
            "property_facts": {
                "postal_name": "Graz",
                "map_lat": 47.0707,
                "map_lng": 15.4395,
            }
        }
    )
    assert preview["image_url"] == "data:image/png;base64,preview"
    assert preview["alt"] == "Wider area around Graz"


def test_property_candidate_orientation_preview_reuses_boundary_projection_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_build_scope_boundary_preview",
        lambda **kwargs: {
            "image_url": "data:image/png;base64,boundarypreview",
            "summary": "Leopoldstadt",
            "district_rows": [{"label": "Leopoldstadt", "selected": True, "path": "M1 1 L2 1 L2 2 Z"}],
        },
    )
    preview = landing_view_models._property_candidate_orientation_preview(
        {
            "property_facts": {
                "district": "Leopoldstadt",
                "postal_name": "Vienna",
                "country_code": "AT",
            }
        }
    )
    assert preview["image_url"] == "data:image/png;base64,boundarypreview"
    assert preview["caption"] == "Leopoldstadt"
    assert preview["district_rows"][0]["label"] == "Leopoldstadt"


def test_property_research_title_display_strips_provider_price_and_fact_noise() -> None:
    raw = "Super nette 2 Zimmer Wohnung (ideal für WG) in bester Lage für Unis, 60 m², € 1.150,-, (1090 Wien) - willhaben"
    assert landing_routes._property_research_title_display(raw) == "Super nette 2 Zimmer Wohnung (ideal für WG) in bester Lage für Unis"


def test_property_scope_preview_uses_generic_boundary_projection(monkeypatch) -> None:
    def fake_record(query: str) -> dict[str, object]:
        lowered = query.lower()
        if "vienna" in lowered:
            return {
                "display_name": "Vienna, Austria",
                "bounds": (16.18, 48.12, 16.55, 48.32),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.18, 48.12], [16.55, 48.12], [16.55, 48.32], [16.18, 48.32], [16.18, 48.12]]],
                },
            }
        if "1020" in lowered:
            return {
                "display_name": "Leopoldstadt, Vienna, Austria",
                "bounds": (16.39, 48.20, 16.46, 48.24),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.39, 48.20], [16.46, 48.20], [16.46, 48.24], [16.39, 48.24], [16.39, 48.20]]],
                },
            }
        if "1200" in lowered:
            return {
                "display_name": "Brigittenau, Vienna, Austria",
                "bounds": (16.35, 48.22, 16.41, 48.27),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.35, 48.22], [16.41, 48.22], [16.41, 48.27], [16.35, 48.27], [16.35, 48.22]]],
                },
            }
        return {}

    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", fake_record)
    monkeypatch.setattr(
        landing_view_models,
        "_cached_preview_data_url",
        lambda **kwargs: "data:image/png;base64,scopepreview",
    )
    preview = landing_view_models._property_scope_preview("AT", "vienna", "1020 Vienna, 1200 Vienna")
    assert preview["image_url"] == "data:image/png;base64,scopepreview"
    assert len(preview["district_rows"]) == 2
    assert all(str(row.get("path") or "").startswith("M") for row in preview["district_rows"])


def test_property_workbench_no_longer_embeds_vienna_district_mapping_js() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")
    assert "const districtMap = {" not in body
    assert "syncViennaScopeControls" not in body


def test_property_research_detail_uses_user_facing_visual_and_decision_copy() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_research_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "Current recommendation" not in body
    assert "Decision call" not in body
    assert "Open Magic Fit" not in body
    assert "Request missing documents" in body
    assert "Open question helper" in body
    assert "data-prd-map-overlay" in body
    assert "Questions worth asking next" in body


def test_base_public_template_exposes_public_seo_contract() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/base_public.html"
    body = template_path.read_text(encoding="utf-8")
    assert '<meta name="description"' in body
    assert '<link rel="canonical"' in body
    assert '<meta property="og:title"' in body
    assert 'application/ld+json' in body


def test_public_pages_are_indexable_but_sign_in_is_not(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-public-seo")
    home = client.get("/")
    assert home.status_code == 200, home.text
    assert home.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"

    pricing = client.get("/pricing")
    assert pricing.status_code == 200, pricing.text
    assert pricing.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"

    sign_in = client.get("/sign-in")
    assert sign_in.status_code == 200, sign_in.text
    assert sign_in.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive, nosnippet"

    robots = client.get("/robots.txt")
    assert robots.status_code == 200, robots.text
    assert "Allow: /" in robots.text
    assert "Disallow: /app/" in robots.text
    assert "Sitemap: https://propertyquarry.com/sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200, sitemap.text
    assert "<loc>https://propertyquarry.com/</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/pricing</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/guides/wohnung-kaufen-wien-checkliste</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/markets/vienna</loc>" in sitemap.text


def test_public_guide_and_market_pages_render_editorial_seo_surface() -> None:
    client = build_property_client(principal_id="pq-public-editorial")

    guide = client.get("/guides/wohnung-kaufen-wien-checkliste")
    assert guide.status_code == 200, guide.text
    assert "Wohnung kaufen in Wien" in guide.text
    assert 'data-rybbit-event="guide_open_propertyquarry"' in guide.text
    assert "FAQPage" in guide.text

    market = client.get("/markets/vienna")
    assert market.status_code == 200, market.text
    assert "Vienna apartment search" in market.text
    assert 'data-rybbit-event="market_start_search"' in market.text
    assert "FAQPage" in market.text


def test_public_ctas_and_selected_review_panel_expose_rybbit_events() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    home = (repo_root / "ea/app/templates/propertyquarry_home.html").read_text(encoding="utf-8")
    pricing = (repo_root / "ea/app/templates/pricing_page.html").read_text(encoding="utf-8")
    selected_review = (repo_root / "ea/app/templates/app/_property_selected_review_panel.html").read_text(encoding="utf-8")
    workbench_script = (repo_root / "ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")
    assert 'data-rybbit-event="home_create_account"' in home
    assert 'data-rybbit-event="pricing_checkout_start"' in pricing
    assert 'data-rybbit-event="property_open_page"' in selected_review
    assert 'data-rybbit-event="property_open_page"' in workbench_script
    assert 'data-rybbit-event="property_request_tour"' in workbench_script


def test_property_search_worker_slots_prioritize_distinct_providers() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 3},
            "sources": [
                {"source_label": "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna", "platform": "derstandard_at", "status": "in_progress"},
                {"source_label": "DER STANDARD Immobilien | Austria | Rent | 1020 Vienna", "platform": "derstandard_at", "status": "in_progress"},
                {"source_label": "immmo | Austria | Rent | 1010 Vienna", "platform": "immmo_at", "status": "in_progress"},
                {"source_label": "FindMyHome.at | Austria | Rent | 1010 Vienna", "platform": "findmyhome_at", "status": "queued"},
            ],
        },
        plan_key="plus",
    )

    providers = [row.get("provider") for row in worker_state.get("workers") or []]
    assert providers[:3] == [
        "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        "immmo | Austria | Rent | 1010 Vienna",
        "FindMyHome.at | Austria | Rent | 1010 Vienna",
    ]
    assert worker_state["workers"][0]["shard_count"] == 1


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
            "enable_commute_research": True,
            "commute_destination": "Berlin Hauptbahnhof",
            "max_commute_minutes_transit": 25,
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
    assert "Add family" in setup.text
    assert "Clear family" in setup.text
    assert "Select sources" in setup.text
    assert "Court and auction listings" in setup.text
    assert "Justiz Edikte" in setup.text
    assert 'data-property-advanced-panel="children"' in setup.text
    assert 'data-property-advanced-panel="commute"' in setup.text
    assert 'data-property-advanced-panel="location_research"' in setup.text
    assert 'class="pqx-disclosure-summary"' in setup.text
    assert 'class="pqx-disclosure-icon" aria-hidden="true">+</span>' in setup.text
    assert 'class="pqx-disclosure-summary pqx-disclosure-summary-secondary"' in setup.text
    assert ">Family<" in setup.text
    assert 'data-property-advanced-panel="location_research"' in setup.text
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
    assert 'data-property-pulse-strip' not in setup.text
    assert "Min area" in setup.text
    assert "Saved searches" in setup.text
    assert "Edit cadence, limits, and delivery in the dedicated view." in setup.text
    assert "Open saved searches" in setup.text
    assert "Last:" in setup.text
    assert "Next:" in setup.text
    assert "Sent 0/" in setup.text
    assert "Save limits" not in setup.text
    assert 'data-search-agent-action="resume"' not in setup.text
    assert 'data-search-agent-action="duplicate"' not in setup.text
    assert 'data-search-agent-action="delete"' not in setup.text
    assert 'data-search-agent-action="run"' not in setup.text

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
    assert '<article class="pqx-result pqx-card"' in search.text
    assert "Best homes first" in search.text
    assert "Match" in search.text
    assert "Source" in search.text
    assert "Map" in search.text
    assert 'data-pqx-route-preview-strip' in search.text
    assert "Your route" in search.text
    assert "Berlin Hauptbahnhof" in search.text
    assert "https://www.google.com/maps/search/?api=1" in search.text
    assert 'target="_blank" rel="noreferrer">Map</a>' in search.text
    assert "https://www.google.com/maps/dir/?api=1" in search.text
    assert "Evidence" in search.text
    assert "CART" in search.text
    assert "Supermarket" in search.text
    assert "280 m" in search.text
    assert 'class="pqx-route-evidence"' in search.text
    assert 'class="pqx-thumb"' in search.text
    assert "ranked homes" in search.text
    assert "price, layout, location, fit reason, and next action stay visible" in search.text
    assert 'class="pqx-result-reason"' in search.text
    assert 'class="pqx-status-line"' in search.text
    assert "Layout verified" in search.text
    assert "Layout needs check" in search.text
    assert "Altbau near U6" in search.text
    assert "Family flat near Tiergarten" in search.text
    assert "360 ready" in search.text
    assert "360 unavailable" in search.text
    assert "360 queued" in search.text
    assert "about 12 min" in search.text
    assert 'data-tour-status="queued"' in search.text
    assert 'data-tour-eta="about 12 min"' in search.text
    assert "still waiting on floorplans" in search.text
    assert "not scheduled yet" not in search.text
    assert "360 not ready" not in search.text
    assert "360" in search.text
    assert "Match" in search.text
    assert "EUR 420,000" in search.text
    assert "Layout" in search.text
    assert "Playground" in search.text
    assert "Supermarket" in search.text
    assert "Starbucks" in search.text
    assert "Fitness" in search.text
    assert "Cinema" in search.text
    assert "Bouldering" in search.text
    assert "SchoolAtlas" in search.text
    assert "Gymnasium path" in search.text
    assert "Property details" in search.text
    assert "Costs" in search.text
    assert "Why it made the shortlist" in search.text
    assert "Current read" in search.text
    assert "Optional context" in search.text
    assert "Artifact receipts" not in search.text
    assert "Share checklist" not in search.text
    assert "Would you pursue this property?" not in search.text
    assert "Save your decision" in search.text
    assert "Viewing requested" in search.text
    assert "Documents requested" in search.text
    assert "Offer candidate" in search.text
    assert "Save answer" in search.text
    assert "Next question to send" in search.text
    assert "Contradicted" in search.text
    assert "Resolved" in search.text
    assert "Delivery proof" not in search.text
    assert "NeuronWriter editorial pass" not in search.text
    assert "Telegram links" not in search.text
    assert "Generated asset receipts" not in search.text
    assert "repair check queued" not in search.text
    assert "Repair: ea_one_manager" not in search.text
    assert "still waiting on floorplans" in search.text
    assert "Pending layout proof" not in search.text
    assert "These homes are still being checked for a floorplan" in search.text
    assert "Repair provider extraction" not in search.text
    assert "Missing facts" not in search.text
    assert "Facts still being completed from floorplans" not in search.text
    assert "Room count not verified yet" in search.text
    assert "Save answer" not in search.text
    assert "Save fact" not in search.text
    assert 'data-pqx-progress-board' in search.text
    assert "Search in progress" in search.text or "Results are ready" in search.text
    assert 'data-pqx-progress-eta' in search.text
    assert 'class="pqx-source-progress"' in search.text
    assert 'class="pqx-source-list"' in search.text
    assert 'class="pqx-route-preview-strip"' in search.text
    assert 'data-research-task-id="mf_rooms_run_42"' not in search.text
    assert 'data-research-task-action="fill"' not in search.text
    assert 'data-research-task-action="dismiss"' not in search.text
    assert "EUR 5,385/m2" in search.text
    assert "Open 360" in search.text
    assert "Chosen ahead of the next option because it scored 5 points higher on the current brief" in search.text
    assert "Preferred because: Lift and transit fit." in search.text
    assert "Preferred because: Includes a live 360 source" not in search.text
    assert "Open property page" in search.text
    assert 'data-candidate-packet-url="/app/research/' in search.text
    assert 'data-pqx-notification-audit' not in search.text
    assert "Alert delivery" not in search.text
    assert "Filtered" in search.text
    assert "Search guard" not in search.text
    assert "Target area guard" not in search.text
    assert "Outside-area results suppressed" not in search.text
    assert "Source filters are limited" not in search.text
    assert "Provider filters needed cleanup" not in search.text
    assert "Missing floorplan evidence" in search.text
    assert "Floorplan gate" not in search.text
    assert "See more matching homes" in search.text
    assert "still waiting on floorplans" in search.text
    assert "These homes are still being checked for a floorplan" in search.text
    assert "Layout not verified" not in search.text
    assert "Missing floorplan evidence" in search.text
    assert 'data-pqx-filtered-dialog' in search.text
    assert "Lower the match bar" in search.text
    assert "Include nearby districts" in search.text
    assert "Raise the alert limit" in search.text
    assert "Floorplans medium" not in search.text
    assert "Filters partial" not in search.text
    assert "Verified 2026-06-13" not in search.text
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
    assert "Best homes first" in shortlist.text
    assert "Altbau near U6" in shortlist.text
    assert "Open property page" in shortlist.text
    assert "Hosted review" not in shortlist.text
    assert "Open feedback" not in shortlist.text

    research = client.get("/app/research", params={"run_id": "run-42"}, headers=headers)
    assert research.status_code == 200
    assert "Best homes first" in research.text
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
    assert packet.text.index("data-object-media-stage") < packet.text.index("At a glance")
    assert "Live 360 ready" in packet.text
    assert 'data-property-research-detail' in packet.text
    assert "At a glance" in packet.text
    assert "Current recommendation" not in packet.text
    assert "Why this was selected" not in packet.text
    assert "Supermarket" in packet.text
    assert "https://www.google.com/maps/dir/" not in packet.text
    assert "Open navigation" not in packet.text
    assert "Library" in packet.text
    assert "Underground" in packet.text
    assert "Current read" in packet.text
    assert "What to do next" in packet.text
    assert "Evidence added" in packet.text
    assert "Manual clearance required" in packet.text
    assert "Luftmessnetz: aktuelle Messdaten Wien" in packet.text
    assert "How the wider area reads today" in packet.text
    assert "Energy posture and heating" in packet.text
    assert "SchoolAtlas quality" in packet.text
    assert "Gymnasium progression" in packet.text
    assert "Buy-side underwriting view" in packet.text
    assert "Gross yield" in packet.text
    assert "Expected monthly rent" in packet.text
    assert "Compare next" in packet.text
    assert "Candidate" in packet.text
    assert "Layout" in packet.text
    assert "Family flat near Tiergarten" in packet.text
    assert "Listing" in packet.text
    assert "Review page" not in packet.text
    assert "Useful links" not in packet.text
    assert "Open listing" in packet.text
    assert "Would you pursue this home?" not in packet.text
    assert "Save your decision" in packet.text
    assert "Viewing requested" in packet.text
    assert "Request missing documents" in packet.text
    assert "Offer candidate" in packet.text
    assert "Extra tools" in packet.text
    assert "Open question helper" in packet.text
    assert "Ask agent next" not in packet.text
    assert "Tracked follow-up" in packet.text
    assert "What changed" in packet.text
    assert "What others flagged" in packet.text
    assert "Household alignment" in packet.text
    assert "Risk signals" in packet.text
    assert "Contradicted" in packet.text
    assert "Resolved" in packet.text
    assert 'data-object-feedback-reaction="like"' in packet.text
    assert 'data-object-feedback-save' in packet.text
    assert "Save answer" in packet.text
    assert "Manage preferences" in packet.text
    assert "rgba(18, 23, 34" not in packet.text
    assert "rgba(15, 19, 26" not in packet.text
    assert "background: var(--panel);" in packet.text

    profile = client.get("/app/profile", params={"run_id": "run-42"}, headers=headers)
    assert profile.status_code == 200
    assert "Account" in profile.text
    assert "Manage account, plan, and saved defaults." in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Account" in alerts.text
    assert "Manage account, plan, and saved defaults." in alerts.text

    notifications_preview = client.get("/app/properties/notifications/preview", params={"template": "property_match"}, headers=headers)
    assert notifications_preview.status_code == 200
    assert "Email preview" in notifications_preview.text
    assert "Property match: Altbau near U6" in notifications_preview.text
    assert "PropertyQuarry shortlisted a property match" in notifications_preview.text
    assert "No — tell us why" in notifications_preview.text

    workspace_preview = client.get("/app/properties/notifications/preview", params={"template": "workspace_invitation"}, headers=headers)
    assert workspace_preview.status_code == 200
    assert "Mara invited you to PropertyQuarry" in workspace_preview.text
    assert "Open invite" in workspace_preview.text

    billing = client.get("/app/billing", params={"run_id": "run-42"}, headers=headers)
    assert billing.status_code == 200
    assert "Account" in billing.text
    assert "Manage account, plan, and saved defaults." in billing.text


def test_property_packets_dashboard_uses_customer_facing_language() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_packets.html"
    body = template_path.read_text(encoding="utf-8")

    assert "Share polished property pages and track the replies." in body
    assert "Packet sharing" not in body
    assert "Sharing" in body
    assert "Ready to send" in body
    assert "Privacy checked · PDF ready · Sharing controls active" in body
    assert "Paste shared page link" in body
    assert "Copy response endpoint" in body
    assert "Which property pages can safely leave your account" in body
    assert "https://packets.propertyquarry.com/p/..." not in body
    assert "Copy response URL" not in body
    assert "Sharing cockpit" not in body
    assert "Publication queue" not in body
    assert "source_pdf_sha256" not in body
    assert "renderer_version" not in body
    assert "Share page" in body
    assert "Share packet" not in body
    assert "Household reactions" in body
    assert "Packet posture" not in body


def test_property_object_detail_feedback_script_avoids_magicfit_preview_innerhtml() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail_feedback_script.html"
    body = template_path.read_text(encoding="utf-8")

    render_magicfit_block = body.split("const renderMagicFitPreview = (scene) => {", 1)[1].split("const renderMagicFitReferenceList = () => {", 1)[0]
    assert "innerHTML" not in render_magicfit_block
    assert "document.createElement('img')" in render_magicfit_block
    assert "appendTextNode(" in render_magicfit_block

    legacy_template = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail.html"
    legacy_body = legacy_template.read_text(encoding="utf-8")
    legacy_block = legacy_body.split("const renderMagicFitPreview = (scene) => {", 1)[1].split("const renderMagicFitReferenceList = () => {", 1)[0]
    assert "innerHTML" not in legacy_block
    assert "document.createElement('img')" in legacy_block


def test_public_tour_allow_and_deny_extension_sets_do_not_overlap() -> None:
    overlap = public_tours._PUBLIC_TOUR_ALLOWED_ASSET_EXTENSIONS & public_tours._PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS
    assert overlap == frozenset()


def test_propertyquarry_public_product_copy_uses_property_page_language() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    product_page = (repo_root / "ea/app/templates/product_page.html").read_text(encoding="utf-8")
    pricing_page = (repo_root / "ea/app/templates/pricing_page.html").read_text(encoding="utf-8")

    assert "research packets" not in product_page
    assert "research packet" not in pricing_page
    assert "hosted packet" not in pricing_page
    assert "property page" in product_page
    assert "property page" in pricing_page


def test_propertyquarry_settings_and_onboarding_avoid_workspace_customer_copy() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    onboarding = (repo_root / "ea/app/services/onboarding.py").read_text(encoding="utf-8")
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "Finalize your workspace preferences" not in onboarding
    assert "Current workspace posture" not in view_models
    assert '"label": "Workspace"' not in view_models


def test_property_workbench_recent_reviews_do_not_render_fake_links() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "href=\"{{ packet.get('url') or '#' }}\"" not in body
    assert "packet.get('url')" in body
    assert "pqx-recent-review" in body
    assert "pqx-recent-review-static" in body
    assert "<span class=\"pqx-pill\">{{ packet.get('title') }}</span>" not in body
    assert ".pqx-recent-review" in body
    assert "overflow-wrap: anywhere;" not in body


def test_property_workbench_previous_search_cards_have_explicit_overflow_gate() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert 'data-pqx-previous-search-card' in body
    assert 'data-pqx-scope-preview' in body
    assert 'class="pqx-previous-scope-image"' in body
    assert 'class="pqx-previous-scope-trigger"' in body
    assert 'class="pqx-previous-title"' in body
    assert 'class="pqx-previous-actions"' in body
    assert 'data-pqx-scope-lightbox' in body
    assert ".pqx-previous-title" in body
    assert "-webkit-line-clamp: 1;" in body
    assert ".pqx-previous-scope-preview" in body
    assert "aspect-ratio: 16 / 8;" in body
    assert ".pqx-previous-search {" in body
    assert "grid-template-columns: minmax(0, 1fr);" in body
    assert "border-bottom: 1px solid var(--pq-line);" in body


def test_property_workspace_search_agents_have_explicit_overflow_gate() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_workspace.html"
    assert not template_path.exists()


def test_propertyquarry_pixefy_visual_watch_audits_periodic_screenshots() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts/propertyquarry_visual_watch.py"
    body = script.read_text(encoding="utf-8")

    assert "PROPERTYQUARRY_PIXEFY_INTERVAL_SECONDS" in body
    assert "page.screenshot" in body
    assert "escaped" in body
    assert "offscreenMedia" in body
    assert "screenFitTargets" in body
    assert "fitsViewport" in body
    assert "duplicateGraphics" in body
    assert "visual-watch-report.json" in body


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
    assert not template_path.exists()


def test_property_search_property_type_uses_checkbox_multi_select() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    templates = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/console_shell.html",
    ]

    for template_path in templates:
        body = template_path.read_text(encoding="utf-8")
        assert "field.name == 'property_type'" in body, f"{template_path.name} does not include property_type control branch"
        assert re.search(r'type="checkbox"\s*name="{{\s*field\.name\s*}}"', body), (
            f"{template_path.name} does not render property_type as checkbox"
        )
        assert '<select name="property_type"' not in body, f"{template_path.name} still renders property_type as select"


def test_property_search_agents_can_load_saved_filters_into_form() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "ea/app/templates/app/property_decision_workbench.html"
    agents_partial = repo_root / "ea/app/templates/app/_property_search_agents_panel.html"
    script_partial = repo_root / "ea/app/templates/app/_property_workbench_script.html"
    brief_script_partial = repo_root / "ea/app/templates/app/_property_workbench_brief_script.html"
    feedback_script_partial = repo_root / "ea/app/templates/app/_property_workbench_feedback_script.html"
    body = template_path.read_text(encoding="utf-8")
    agents_body = agents_partial.read_text(encoding="utf-8")
    script_body = script_partial.read_text(encoding="utf-8")
    brief_script_body = brief_script_partial.read_text(encoding="utf-8")
    feedback_script_body = feedback_script_partial.read_text(encoding="utf-8")

    assert '{% include "app/_property_search_agents_panel.html" %}' in body
    assert "data-search-agent-payload" in agents_body
    assert 'data-search-agent-action="load"' in agents_body
    assert ">Edit</button>" in agents_body
    assert "Load filters" not in body
    assert "applySearchAgentPayloadToForm" in script_body
    assert "resetSearchBriefForm" in script_body
    assert "resetSearchBriefForm();" in script_body
    assert "Saved search ready to edit. Tweak the filters or run it again." in script_body
    assert "data-search-agent-loaded-state" in body
    assert "Loaded: ${label}" in script_body
    assert "data-search-agent-dirty-label" in body
    assert "Unsaved changes in ${dirtyFields} field" in script_body
    assert "data-search-agent-save-current" in body
    assert "data-search-agent-save-new" in body
    assert "data-search-agent-reset" in body
    assert '{% include "app/_property_workbench_brief_script.html" %}' in script_body
    assert "'search_mode'" in brief_script_body
    assert "search_mode: fieldValue(form, 'search_mode') || 'strict'" in brief_script_body
    assert "Object.entries(source).forEach" in script_body or "Object.entries(source).forEach" in brief_script_body
    assert "Save as new" in body
    assert "credentials: 'same-origin'" in script_body
    assert "authHeaders()" not in script_body
    assert "load_agent" in script_body
    assert "propertyDecisionStateEndpoint" in script_body
    assert '{% include "app/_property_workbench_feedback_script.html" %}' in script_body
    assert "No saved decision yet. Choose Yes, Maybe, No, or Hide to start the decision trail." in feedback_script_body
    assert "Current state" in feedback_script_body
    assert "data-pw-agent-question-id" in feedback_script_body
    assert "data-pw-document-id" in feedback_script_body


def test_property_workspace_search_form_exposes_austria_evidence_and_eligibility_controls() -> None:
    template_body = (
        Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    ).read_text(encoding="utf-8")
    view_model_body = (
        Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py"
    ).read_text(encoding="utf-8")

    assert "School evidence priority" in view_model_body
    assert "Wiener Wohn-Ticket available" in view_model_body
    assert "Subsidized or cooperative supply only" in view_model_body
    assert "Require school evidence" in view_model_body
    assert "Require energy certificate evidence" in view_model_body
    assert "Require operating-cost evidence" in view_model_body
    assert "Court and auction review" in view_model_body
    assert "Require high-speed internet evidence" in view_model_body
    assert "Avoid noise-risk area" in view_model_body
    assert "Austria fit rule" in view_model_body
    assert "ganztag_required" in template_body
    assert "require_school_evidence" in template_body
    assert "wiener_wohnticket_available" in template_body
    assert "subsidized_required" in template_body
    assert "miete_mit_kaufoption" in template_body
    assert "eigenmittel_max_eur" in template_body
    assert "application_window_days" in template_body
    assert "require_energy_certificate" in template_body
    assert "require_operating_cost_statement" in template_body
    assert "enable_auction_legal_review" in template_body
    assert "platform_defaults_by_country_mode" in template_body
    assert "defaultPlatformsForCountryMode" in template_body
    assert "Official checks" in template_body
    assert "evidence_source_catalog_by_country" in template_body


def test_property_workspace_templates_expose_account_navigation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    console_shell = (repo_root / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    for body in (console_shell, workbench):
        assert "Account navigation" in body
        assert ">Upgrade<" in body
        assert ">Profile<" in body
        assert ">Settings<" in body
        assert ">Log out<" in body
        assert "account_nav.sign_out_action" in body


def test_property_workspace_hero_actions_use_visible_propertyquarry_surfaces() -> None:
    body = (
        Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py"
    ).read_text(encoding="utf-8")

    assert '{"href": f"/app/search{run_suffix}", "label": "Open search"}' in body
    assert '{"href": f"/app/properties{run_suffix}", "label": "Back to Home"}' in body
    assert '{"href": f"/app/agents{run_suffix}", "label": "Saved searches"}' in body
    assert '{"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "Choose the target areas.", "href": "/app/account#profile"}' in body


def test_property_workspace_sign_out_clears_workspace_session_cookie() -> None:
    principal_id = "pq-account-sign-out"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text
    access_body = access_session.json()

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")

    workspace = client.get("/app/properties")
    assert workspace.status_code == 200
    assert "Account navigation" in workspace.text
    assert "Upgrade" in workspace.text
    assert "Log out" in workspace.text

    signed_out = client.post("/app/actions/sign-out", data={"return_to": "/"}, follow_redirects=False)
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/"
    sign_out_cookie = str(signed_out.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in sign_out_cookie
    assert "Max-Age=0" in sign_out_cookie or "expires=" in sign_out_cookie.lower()
    assert not client.cookies.get("ea_workspace_session")

    signed_out_workspace = client.get("/app/properties")
    assert signed_out_workspace.status_code == 200


def test_property_search_form_defaults_to_discovery_after_thin_strict_run(monkeypatch) -> None:
    payload = landing_routes._property_workspace_payload(
        "properties",
        status={"workspace": {"name": "Discovery Default"}, "channels": {}},
        property_state={
            "preferences": {
                "country_code": "AT",
                "listing_mode": "rent",
                "region_code": "vienna",
                "location_query": "1020 Vienna",
                "search_mode": "strict",
            },
            "run": {
                "status": "completed",
                "summary": {
                    "ranked_total": 2,
                    "sources_total": 8,
                    "listing_total": 31,
                    "ranked_candidates": [
                        {"candidate_ref": "candidate-1", "title": "Candidate 1"},
                        {"candidate_ref": "candidate-2", "title": "Candidate 2"},
                    ],
                },
            },
            "commercial": {},
            "preference_bundle": {},
        },
    )

    search_mode_field = next(
        field
        for field in list((payload.get("console_form") or {}).get("fields") or [])
        if str(field.get("name") or "").strip() == "search_mode"
    )
    assert search_mode_field["value"] == "discovery"
    assert search_mode_field["options"] == [
        {"value": "strict", "label": "Strict shortlist"},
        {"value": "discovery", "label": "Discovery pass"},
    ]
    assert "turns school, family, and entertainment distance misses into ranking penalties" in str(search_mode_field.get("tooltip") or "")


def test_property_dashboard_renders_previous_searches_with_compact_finished_results(monkeypatch) -> None:
    principal_id = "pq-previous-searches"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Previous Search Office")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-finished",
                "principal_id": principal_id,
                "status": "completed",
                "updated_at": "2026-06-13T08:00:00+00:00",
                "property_search_preferences": {
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 12,
                    "listing_total": 21,
                    "notified_total": 2,
                    "top_fit_score": 68,
                    "filtered_floorplan_total": 4,
                    "ranked_candidates": [
                        {
                            "title": "Ruhige 2-Zimmer Wohnung mit Balkon",
                            "source_label": "Willhaben",
                            "fit_score": 68,
                            "compare_reason": "Strong district and layout fit.",
                            "packet_url": "/app/research/candidate-1?run_id=run-finished",
                        }
                    ],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/properties", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Continue where you left off." in page.text
    assert "1020 Vienna" in page.text
    assert "Open" in page.text
    assert "Delete" in page.text
    assert "filtered" in page.text


def test_property_dashboard_failed_previous_search_uses_customer_facing_copy(monkeypatch) -> None:
    principal_id = "pq-previous-search-failed-copy"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Failed Search Copy")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-failed-copy",
                "principal_id": principal_id,
                "status": "failed",
                "message": "Provider returned 403 while fetching Willhaben.",
                "updated_at": "2026-06-13T08:00:00+00:00",
                "property_search_preferences": {
                    "country_code": "AT",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 1,
                    "listing_total": 0,
                    "ranked_candidates": [],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/properties", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Needs attention" in page.text
    assert "Provider returned 403 while fetching Willhaben." in page.text
    assert ">Failed<" not in page.text


def test_property_search_agents_have_dedicated_management_page() -> None:
    principal_id = "pq-agent-management"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna apartments",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "buy",
                    "property_type": "apartment",
                    "notification_limit": 3,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "buy",
                        "property_type": "apartment",
                    },
                },
                {
                    "agent_id": "agent-monteverde",
                    "name": "Monteverde land",
                    "enabled": True,
                    "country_code": "CR",
                    "region_code": "puntarenas",
                    "location_query": "Monteverde",
                    "listing_mode": "buy",
                    "property_type": "land",
                    "notification_limit": 5,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "CR",
                        "region_code": "puntarenas",
                        "location_query": "Monteverde",
                        "listing_mode": "buy",
                        "property_type": "land",
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    page = client.get("/app/agents", headers={"host": "propertyquarry.com"})
    assert page.status_code == 200
    assert "Saved searches" in page.text
    assert "Vienna apartments" in page.text
    assert "Monteverde land" in page.text
    assert "Selected search" in page.text
    assert "Saved searches and workers are different limits" in page.text
    assert "Free" in page.text
    assert "Plus" in page.text
    assert "Agent" in page.text
    assert 'href="/app/agents"' in page.text
    assert ">Open</a>" in page.text
    assert "load_agent=agent-vienna" in page.text or "load_agent=agent-monteverde" in page.text


def test_property_search_agents_can_open_focused_cockpit_view(monkeypatch) -> None:
    principal_id = "pq-agent-focus"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Focus")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "notification_limit": 5,
                    "notification_period": "day",
                    "sent_in_current_window": 2,
                    "last_run_at": "2026-06-13T09:00:00+00:00",
                    "next_run_at": "2026-06-14T09:00:00+00:00",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-agent-1",
                "principal_id": principal_id,
                "active_search_agent_id": "agent-vienna",
                "status": "completed",
                "updated_at": "2026-06-13T09:10:00+00:00",
                "property_search_preferences": {
                    "active_search_agent_id": "agent-vienna",
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 7,
                    "listing_total": 24,
                    "notified_total": 2,
                    "top_fit_score": 71,
                    "filtered_floorplan_total": 5,
                    "filtered_area_total": 3,
                    "ranked_candidates": [
                        {
                            "title": "Courtyard flat",
                            "source_label": "Willhaben",
                            "fit_score": 71,
                            "packet_url": "/app/research/agent-candidate?run_id=run-agent-1",
                        }
                    ],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/agents?agent_id=agent-vienna", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna rent watch" in page.text
    assert "Latest finished run" in page.text
    assert "Ranked 1 | Sent 2 | Filtered 8" in page.text
    assert "load_agent=agent-vienna" in page.text


def test_property_workspace_setup_is_dashboard_first_and_compact() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "Continue where you left off." in body
    assert "data-pqx-previous-searches" in body
    assert ">Open</a>" in body
    assert 'data-pqx-delete-run="' in body
    assert "data-pqx-dashboard-summary" in body
    assert "Saved searches" in body
    assert "Start" in body
    assert "Recent decisions and reviews" in body
    assert "pqx-previous-scope-caption" in body
    assert "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);" in body
    assert "display: flex;" in body
    assert "<legend>Search flow</legend>" in body
    assert ".pqx-disclosure-summary {" in body
    assert ".pqx-disclosure-icon {" in body
    assert ".pqx-workflow-step:hover," in body
    assert ".pqx-field-tools .pqx-field-action {" in body
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in body
    assert '"label": "Market"' in view_model
    assert '"label": "Sources"' in view_model
    assert '"label": "Family"' in view_model
    assert '"label": "Commute"' in view_model
    assert '"label": "Research"' in view_model
    assert '"label": "State or metro area"' in view_model
    assert "font-size: 8px" not in body
    assert "font-size: 9px" not in body
    assert 'grid-template-columns: repeat(6, minmax(0, 1fr));' not in body
    assert "pqx-state-strip" not in body
    assert 'aria-label="Current search context"' not in body
    assert 'aria-label="Account navigation"' in body
    assert ">Me<" not in body
    assert "Tell us what to find." not in body


def test_property_workspace_previous_search_delete_uses_real_api_endpoint() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "data-pqx-delete-run" in body
    assert "Delete this previous search from the dashboard?" in body
    assert "method: 'DELETE'" in body
    assert "delete_run_template" in view_model
    assert "_property_scope_preview" in view_model
    assert '"scope_preview": scope_preview' in view_model


def test_property_finished_search_results_prioritize_main_list_and_filtered_disclosure() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "data-pqx-finished-compare" in body
    assert "Best homes first" in body
    assert "How this search was filtered" in body
    assert "Price, layout, fit, and the next action stay in the main list." in body


def test_property_decision_save_uses_canonical_endpoint_and_renders_consequences() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "propertyDecisionSaveEndpoint = () => '/app/api/property/decisions'" in body
    assert "renderSavedDecisionConsequences(body)" in body
    assert "agent_question_tasks" in body
    assert "document_intake" in body
    assert "suppression_explanation" in body
    assert "Saved durably" in body
    assert "propertyFeedbackSaveEndpoint" not in body


def test_property_workspace_running_state_explains_slow_provider_checks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "ea/app/templates/app/property_decision_workbench.html"
    running_partial = repo_root / "ea/app/templates/app/_property_running_panel.html"
    script_partial = repo_root / "ea/app/templates/app/_property_workbench_script.html"
    body = template_path.read_text(encoding="utf-8")
    running_body = running_partial.read_text(encoding="utf-8")
    script_body = script_partial.read_text(encoding="utf-8")

    assert "estimateRunEtaLabel" in script_body
    assert "formatEta" in script_body
    assert "data-pqx-progress-eta" in body
    assert "data-pqx-running-provider-state" not in body
    run_visible_branch = body.split("{% elif run_visible %}", 1)[1].split("{% elif run_terminal_no_results %}", 1)[0]
    assert '{% include "app/_property_running_panel.html" %}' in run_visible_branch
    assert '{% include "app/_property_workbench_script.html" %}' in body
    assert running_body.count("{{ progress_board(run, run_sources, research_task_counts) }}") == 1
    assert 'data-pqx-running-details' in running_body
    assert "Open only if you want the detailed search trail, worker lanes, and unresolved checks." in running_body
    assert "Provider checks" not in body
    assert "0 lanes in progress" not in body
    assert "lanes in progress" not in body


def test_propertyquarry_user_facing_copy_avoids_hosted_review_jargon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    checked_paths = [
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
            "full_region_scope": True,
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
            "message": "Scoring enriched candidate 2 of 4 for Willhaben | Austria | Buy | Wien.",
            "summary": {
                "sources_total": 4,
                "listing_total": 6,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "eta_label": "about 6 min",
                "sources": [],
            },
            "events": [
                {"step": "source_assessing", "message": "Scoring enriched candidate 2 of 4 for Willhaben | Austria | Buy | Wien.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    live = client.get("/app/properties", params={"run_id": "run-live"}, headers=headers)
    assert live.status_code == 200
    assert 'data-property-spa-shell' in live.text
    assert 'data-property-decision-workbench' in live.text
    assert 'data-pq-greenfield-shell' in live.text
    assert 'data-pqx-state="running"' in live.text
    assert "Looking for strong matches" in live.text
    assert 'class="pqx-run-head"' not in live.text
    assert live.text.count('class="pqx-progress-board"') == 1
    assert 'data-pqx-run-summary' in live.text
    assert "Search in progress" in live.text
    assert 'data-pqx-progress-board' in live.text
    assert 'data-pqx-progress-eta' in live.text
    assert "42% · about 6 min" in live.text
    assert 'class="pqx-source-progress"' in live.text
    assert 'class="pqx-source-list"' in live.text
    assert 'class="pqx-route-preview-strip"' in live.text
    assert "Scoring enriched candidate 2 of 4" in live.text
    assert "Launch search" not in live.text
    assert "Save defaults" not in live.text
    assert "Test a wider budget ceiling" not in live.text


def test_property_search_analysis_cap_defaults_to_top_k_slice(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_SEARCH_ANALYSIS_CAP_PER_SOURCE", raising=False)
    assert _property_search_analysis_cap_per_source(max_results=2, candidate_total=31) == 6
    assert _property_search_analysis_cap_per_source(max_results=5, candidate_total=31) == 12
    assert _property_search_analysis_cap_per_source(max_results=5, candidate_total=4) == 4


def test_property_search_analysis_cap_allows_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_ANALYSIS_CAP_PER_SOURCE", "9")
    assert _property_search_analysis_cap_per_source(max_results=2, candidate_total=31) == 9


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
    assert 'data-pqx-screenfit-target="run-progress"' in template
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
    assert "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);" in setup.group("body")
    assert "align-items: start;" in setup.group("body")
    assert "align-content: start;" in setup_intro.group("body")
    assert "padding: 18px 18px 14px;" in setup_intro.group("body")
    assert ".pqx-setup.pqx-surface-search" in template
    assert "min-height: 0;" in fact.group("body")
    assert "overflow-wrap: normal;" in fact_strong.group("body")
    assert "white-space: normal;" in fact_strong.group("body")
    assert "white-space: nowrap;" not in fact_strong.group("body")


def test_propertyquarry_workspace_supports_full_region_scope_toggle() -> None:
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
            "full_region_scope": True,
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
    assert "<h2>Search profile</h2>" not in search.text
    assert 'href="/app/account#profile">Open preferences</a>' in search.text
    assert "Prefer Outdoor Space (Soft Preference)" not in search.text
    assert 'name="full_region_scope" value="true" checked' in search.text


def test_propertyquarry_saved_brief_reload_does_not_backfill_custom_location_from_checkbox_scope() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "setFieldValue('custom_location_query', payload.location_query)" not in template


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
    assert "Previous searches" in response.text
    assert "Saved searches" in response.text
    assert "Saved searches" in response.text
    assert "Open saved searches" in response.text
    assert "Open preferences" in response.text
    assert "Build the brief. Then let the agents work." not in response.text


def test_property_workspace_search_controls_have_explicit_click_handlers() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert 'data-checkbox-group-select-all="{{ field.name }}"' in body
    assert "field.name == 'selected_platforms'" in body
    assert "form.querySelectorAll('[data-checkbox-group-select-all]').forEach((button) => {" in body
    assert "const groupSelect = event.target?.closest?.('[data-checkbox-group-select-scope]');" in body
    assert "const groupClear = event.target?.closest?.('[data-checkbox-group-clear-scope]');" in body
    assert "root.querySelectorAll('[data-pqx-delete-run]').forEach((button) => {" in body
    assert "loadSearchAgentRow(row, false)" in body
    assert "loadSearchAgentRow(row, true)" in body


def test_property_workspace_search_uses_groupboxes_and_default_profile_select() -> None:
    template_body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    view_model_body = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "pqx-choice-groupbox" in template_body
    assert "Family distances" in template_body
    assert "Shopping and errands" in template_body
    assert "Leisure and daily life" in template_body
    assert '"name": "preference_person_id"' in view_model_body
    assert '"type": "select"' in view_model_body
    assert '"label": "Default"' in view_model_body


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
    assert "Open to relax one rule and rerun the search." not in page.text
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
    assert "No hosted 3D tour yet" in packet.text
    assert "Floorplan missing" in packet.text
    assert "not scheduled yet" not in packet.text


def test_propertyquarry_settings_hide_generic_google_sync_metrics() -> None:
    client = build_property_client(principal_id="pq-redesign-settings")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    account = client.get("/app/account", headers={"host": "propertyquarry.com"})
    assert account.status_code == 200
    assert "Manage account, plan, and saved defaults." in account.text
    assert "Identity and return access" in account.text
    assert "Current search brief state" in account.text
    assert "Operating posture" in account.text
    assert 'id="settings"' in account.text
    assert 'id="plans"' in account.text
    assert 'id="profile"' in account.text
    assert "Open pricing" in account.text
    assert "Open security" in account.text
    assert "Sync runs" not in account.text
    assert "Last Google sync" not in account.text
    assert "Office signals ingested" not in account.text


def test_propertyquarry_shell_uses_the_new_surface_navigation() -> None:
    client = build_property_client(principal_id="pq-surface-nav")
    start_workspace(client, mode="personal", workspace_name="Surface Nav")

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert ">Home<" in response.text
    assert ">Search<" in response.text
    assert ">Saved searches<" in response.text
    assert ">Account<" in response.text
    assert ">Shortlist<" not in response.text
    assert 'href="/app/research"' not in response.text
    assert ">Alerts<" not in response.text
    assert ">Billing<" not in response.text
