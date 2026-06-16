from __future__ import annotations

import re
from pathlib import Path

from app.api.routes import landing as landing_routes
from app.api.routes.landing_property_surface_contracts import PropertySurfaceScope
from app.api.routes import landing_property_workspace_helpers
from app.api.routes import landing_property_research
from app.api.routes import landing_property_saved_searches
from app.api.routes import landing_property_shortlist_panel
from app.api.routes import public_tours
from app.api.routes import landing_view_models
from app.services import property_market_catalog
from app.product import property_surface_state
from app.product.models import HandoffNote
from app.product.service import ProductService, _property_search_analysis_cap_per_source
from tests.product_test_helpers import build_property_client, start_workspace


def _read_workbench_bundle() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/app/_property_results_list.html",
        repo_root / "ea/app/templates/app/_property_running_panel.html",
        repo_root / "ea/app/templates/app/_property_search_agents_panel.html",
        repo_root / "ea/app/templates/app/_property_selected_review_panel.html",
        repo_root / "ea/app/templates/app/_property_workbench_script.html",
        repo_root / "ea/app/templates/app/_property_workbench_brief_script.html",
        repo_root / "ea/app/templates/app/_property_workbench_feedback_script.html",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.exists())


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


def test_propertyquarry_object_detail_template_exposes_user_facing_optional_tools() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "Open question helper" in body
    assert "Visualize furnished living" in body
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


def test_propertyquarry_search_route_does_not_use_generic_workspace_search(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-route")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _explode(*args, **kwargs):
        raise AssertionError("generic workspace search should not run for PropertyQuarry /app/search")

    monkeypatch.setattr(ProductService, "search_workspace", _explode)

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert 'data-property-decision-workbench' in response.text
    assert "Search people, threads, commitments, decisions, deadlines, evidence, rules, and handoffs." not in response.text


def test_propertyquarry_properties_route_redirects_to_search_without_a_run() -> None:
    client = build_property_client(principal_id="pq-properties-redirects-to-search")
    start_workspace(client, mode="personal", workspace_name="Search First Office")

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"


def test_property_provider_options_expose_homepage_links() -> None:
    options = property_market_catalog.provider_options(country_code="AT")
    willhaben = next(option for option in options if option["value"] == "willhaben")
    assert willhaben["homepage_url"] == "https://www.willhaben.at"


def test_property_surface_state_normalizes_search_run_snapshot() -> None:
    snapshot = property_surface_state.normalize_property_search_run_snapshot(
        {
            "run_id": "run-123",
            "summary": {"status": "completed", "listing_total": 12},
            "preferences": {"country_code": "AT"},
            "active_search_agent_id": "agent-1",
        }
    )
    assert snapshot["run_id"] == "run-123"
    assert snapshot["status"] == "completed"
    assert snapshot["property_search_preferences"] == {"country_code": "AT"}
    assert snapshot["active_search_agent_id"] == "agent-1"


def test_property_surface_state_builds_billing_truth_snapshot() -> None:
    snapshot = property_surface_state.build_property_billing_truth_snapshot(
        commercial={
            "current_plan_label": "Agent",
            "current_plan_key": "agent",
            "research_depth": "deep",
            "max_platforms": 12,
            "max_results_per_source": 5,
        },
        default_billing_plan="agent",
        billing_enabled_plans=["plus", "agent"],
        billing_order_endpoints_by_plan={"agent": "/billing/order"},
        billing_provider_labels_by_plan={"agent": "PayFunnels"},
        fleet_digest={"summary": "Visible"},
    )
    assert snapshot["current_plan_label"] == "Agent"
    assert snapshot["checkout_provider"] == "payfunnels"
    assert snapshot["order_endpoint"] == "/billing/order"
    assert snapshot["fleet_digest"] == {"summary": "Visible"}


def test_property_surface_state_builds_preference_manager_snapshot() -> None:
    snapshot = property_surface_state.build_property_preference_manager_snapshot(
        person_id="self",
        raw_preference_nodes=[
            {
                "node_id": "node-1",
                "domain": "willhaben",
                "category": "constraint",
                "key": "budget_max",
                "value_json": 900000,
                "strength": "high",
                "status": "active",
            }
        ],
        include_full_manager=True,
        schema={"keys": ["budget_max"]},
    )
    assert snapshot["person_id"] == "self"
    assert snapshot["schema"] == {"keys": ["budget_max"]}
    assert snapshot["nodes"][0]["label"] == "Budget Max (Constraint)"
    assert snapshot["active_nodes"][0]["node_id"] == "node-1"


def test_property_surface_state_builds_run_health_snapshot() -> None:
    snapshot = property_surface_state.build_property_run_health_snapshot(
        {
            "run_id": "run-123",
            "status": "in_progress",
            "progress": 42,
            "eta_label": "about 3 min",
            "summary": {
                "sources_total": 4,
                "listing_total": 18,
                "filtered_low_fit_total": 6,
            },
            "open_research_task_total": 2,
            "research_task_total": 5,
        }
    )
    assert snapshot["run_id"] == "run-123"
    assert snapshot["status"] == "in_progress"
    assert snapshot["status_label"] == "Running"
    assert snapshot["progress"] == 42
    assert snapshot["in_progress"] is True
    assert snapshot["source_total"] == 4
    assert snapshot["listing_total"] == 18
    assert snapshot["filtered_total"] == 6
    assert snapshot["research_task_total"] == 5
    assert snapshot["open_research_task_total"] == 2


def test_property_surface_state_previous_run_summary_uses_status_copy() -> None:
    summary = property_surface_state.build_property_previous_run_summary(
        {
            "run_id": "run-9",
            "status": "failed",
            "message": "stalled",
            "summary": {"status": "failed"},
            "preferences": {"country_code": "AT", "location_query": "Vienna", "listing_mode": "buy"},
        },
        include_scope_preview=False,
        scope_preview_builder=lambda country, region, location: {"summary": f"{country}:{region}:{location}"},
        compact_provider_label=lambda label: label,
        candidate_maps_url_builder=lambda candidate: "",
    )
    assert summary["status_label"] == "Search failed"
    assert summary["status_note"] == "stalled"
    assert summary["is_finished"] is True


def test_property_surface_state_builds_shortlist_snapshot_and_reorders_selected() -> None:
    snapshot = property_surface_state.build_property_shortlist_snapshot(
        [
            {"candidate_ref": "a", "title": "A"},
            {"candidate_ref": "b", "title": "B"},
            {"candidate_ref": "c", "title": "C"},
        ],
        selected_candidate_ref="b",
    )
    assert snapshot["selected_candidate_ref"] == "b"
    assert snapshot["selected"]["title"] == "B"
    assert [row["candidate_ref"] for row in snapshot["results"]] == ["b", "a", "c"]
    assert snapshot["results_total"] == 3
    assert snapshot["has_results"] is True


def test_property_search_agent_selection_snapshot_is_typed_and_linked() -> None:
    snapshot = landing_property_saved_searches.select_property_search_agent(
        [
            {"agent_id": "agent-a", "location_query": "Vienna", "is_active": False},
            {"agent_id": "agent-b", "location_query": "Graz", "is_active": True},
        ],
        requested_agent_id="agent-b",
        previous_runs=[
            {"agent_id": "agent-b", "title": "Graz", "run_id": "run-1"},
            {"agent_id": "agent-a", "title": "Vienna", "run_id": "run-2"},
        ],
        run_id="run-live",
    )
    assert snapshot["selected_agent_id"] == "agent-b"
    assert snapshot["selected_agent"]["location_query"] == "Graz"
    assert snapshot["selected_agent_latest_run"]["run_id"] == "run-1"
    assert "agent_id=agent-b" in snapshot["selected_agent_open_href"]
    assert "run_id=run-live" in snapshot["selected_agent_edit_href"]


def test_property_workbench_candidate_snapshot_carries_detail_state() -> None:
    snapshot = property_surface_state.build_property_workbench_candidate_snapshot(
        candidate_ref="cand-1",
        rank=1,
        title="Lead candidate",
        source_label="Willhaben",
        location_label="Vienna",
        price_display="EUR 650,000",
        costs_display="Costs EUR 320/mo",
        price_per_sqm_display="EUR 8,200/m2",
        layout_display="3 rooms | 79 m2",
        layout_verification_label="verified",
        fit_score=86,
        fit_label="Strong fit",
        fit_summary="Good light and transit.",
        tour={"status": "ready"},
        orientation_preview={"caption": "Leopoldstadt"},
        ooda={"summary": "Walkable"},
        risk={"level": "low", "summary": "No major blocker"},
        investment={"enabled": True},
        match_reasons=["Transit"],
        mismatch_reasons=["Needs kitchen refresh"],
        review_page_neuronwriter={"status": "ready"},
        packet_url="/app/research/cand-1",
        review_url="",
        property_url="https://example.com/listing",
        map_url="https://maps.example.com",
        source_url="https://example.com/listing",
        property_facts={"postal_name": "Vienna"},
        assessment={"fit_score": 86},
        objection_rows=[{"title": "Risk", "detail": "Minor"}],
        timeline_rows=[{"title": "Ranked", "detail": "Now"}],
        household_rows=[{"title": "Parent", "detail": "Yes"}],
        risk_signal_rows=[{"title": "Signal", "detail": "Low"}],
        followup_rows=[{"title": "Ask", "detail": "Broker"}],
        recent_change_rows=[{"title": "Update", "detail": "Fresh"}],
        official_evidence_rows=[{"title": "Cadastre", "detail": "Linked"}],
        official_posture_rows=[{"title": "Risk", "detail": "Clear"}],
        object_rows=[{"title": "Rooms", "detail": "3"}],
        cost_rows=[{"title": "Costs", "detail": "320"}],
        feature_values=[{"title": "Balcony", "detail": "Yes"}],
        description_text="Clean description",
        location_text="Near Prater",
        energy_rows=[{"title": "EPC", "detail": "B"}],
        household_alignment_score=72,
        household_alignment_label="aligned",
        recovered_by_filter=True,
        relaxed_filter_label="Match bar",
        preview_image_url="https://img.example.com/1.jpg",
    )
    assert snapshot["candidate_ref"] == "cand-1"
    assert snapshot["rank"] == 1
    assert snapshot["tour"]["status"] == "ready"
    assert snapshot["official_evidence_rows"][0]["title"] == "Cadastre"
    assert snapshot["household_alignment_label"] == "aligned"


def test_property_console_context_skips_feedback_and_profile_hydration_on_properties(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-fast-properties")

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            return []

        def get_property_search_run_status(self, *, principal_id: str, run_id: str):
            return {
                "run_id": run_id,
                "status": "in_progress",
                "summary": {
                    "status": "in_progress",
                    "sources": [
                        {
                            "source_label": "Willhaben",
                            "top_candidates": [{"candidate_ref": "cand-1", "title": "Lead"}],
                        }
                    ],
                },
            }

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            raise AssertionError("properties surface should not hydrate preference profiles")

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            raise AssertionError("properties surface should not hydrate learning summaries")

        def list_handoffs(self, *, principal_id: str, limit: int = 12, status=None):
            raise AssertionError("properties surface should not hydrate recent match handoffs")

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())
    monkeypatch.setattr(
        landing_routes,
        "build_fliplink_packet_service",
        lambda container: (_ for _ in ()).throw(AssertionError("properties surface should not build packet feedback")),
    )

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-fast-properties",
        status={"property_search_preferences": {"country_code": "AT"}},
        run_id="run-1",
        surface_mode="properties",
    )

    candidate = context["run"]["summary"]["sources"][0]["top_candidates"][0]
    assert context["preference_bundle"] == {}
    assert "feedback_summary" not in candidate
    assert "feedback_rows" not in candidate


def test_property_console_context_keeps_preference_profile_hydration_on_search(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-learning")
    seen = {"profile": 0}

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            return []

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            seen["profile"] += 1
            return {"preference_nodes": [{"node_id": "node-1", "key": "budget_max", "value_json": 900000}]}

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            return {"summary": "Learning ready"}

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-search-learning",
        status={"property_search_preferences": {"country_code": "AT"}},
        surface_mode="search",
    )

    assert seen["profile"] == 1
    assert context["preference_bundle"]["preference_nodes"][0]["node_id"] == "node-1"


def test_property_console_context_keeps_preference_profile_hydration_on_account(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-account-profile")
    seen = {"profile": 0, "learning": 0}

    class _Product:
        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            seen["profile"] += 1
            return {"preference_nodes": [{"node_id": "node-1", "key": "budget_max", "value_json": 900000}]}

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            seen["learning"] += 1
            return {"summary": "Learning ready"}

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-account-profile",
        status={"property_search_preferences": {"country_code": "AT"}},
        surface_mode="account",
    )

    assert seen["profile"] == 1
    assert seen["learning"] == 0
    assert context["preference_bundle"]["preference_nodes"][0]["node_id"] == "node-1"
    assert context["learning_summary"] == {}


def test_property_properties_surface_skips_search_agent_snapshot_build(monkeypatch) -> None:
    principal_id = "pq-properties-skip-search-agents"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    monkeypatch.setattr(
        landing_view_models,
        "build_property_search_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("properties surface should not build search agent snapshots")),
    )

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200


def test_property_research_packet_snapshot_normalizes_route_payload() -> None:
    snapshot = property_surface_state.build_property_research_packet_snapshot(
        title="Lead home",
        summary="EUR 650,000 · 79 m² · Vienna",
        source_label="Willhaben",
        price="EUR 650,000",
        area="79 m²",
        rooms="3 rooms",
        location="Vienna",
        media={"tour_url": "https://example.com/tour"},
        preview_image={"image_url": "https://img.example.com/1.jpg"},
        gallery_items=[{"kind": "image", "url": "https://img.example.com/1.jpg"}],
        location_preview={"title": "Leopoldstadt"},
        actions=[{"label": "Open listing", "href": "https://example.com/listing"}],
        visual_status_line="3D tour is ready.",
        source_ref="src-1",
        run_id="run-1",
        candidate_ref="cand-1",
        overview_rows=[{"label": "Price", "value": "EUR 650,000"}],
        sections=[{"eyebrow": "At a glance", "title": "Why this stayed"}],
        match_reasons=["Transit"],
        mismatch_reasons=["Kitchen refresh"],
        listing_rows=[{"label": "Rooms", "value": "3"}],
        cost_rows=[{"label": "Costs", "value": "320"}],
        feature_values=[{"label": "Balcony", "value": "Yes"}],
        description_text="Bright flat",
        location_text="Near Prater",
        energy_rows=[{"label": "EPC", "value": "B"}],
        missing_rows=[{"title": "Land register", "detail": "Still missing"}],
        decision_rows=[{"title": "Next step", "detail": "Call broker"}],
        compare_rows=[{"title": "Comp A", "detail": "Open next"}],
        compare_table_rows=[{"candidate": {"title": "Comp A"}}],
        compare_headers=["Candidate", "Fit"],
        official_evidence_rows=[{"title": "Cadastre", "detail": "Linked"}],
        official_posture_rows=[{"title": "Risk", "detail": "Clear"}],
        future_research_rows=[{"title": "School", "detail": "Atlas linked"}],
        provenance_rows=[{"title": "Source", "detail": "Listing"}],
        timeline_rows=[{"title": "Ranked", "detail": "Now"}],
        everyday_fit_rows=[{"title": "Transit", "detail": "Strong"}],
        risk_fit_rows=[{"title": "Flood", "detail": "Low"}],
        investment_rows=[{"title": "Yield", "detail": "4.1%"}],
        investment_risk_rows=[{"title": "Tax", "detail": "Verify"}],
        next_best_question="Ask about reserves",
        feedback={"save_endpoint": "/app/api/property-feedback"},
        neuronwriter={"status": "ready"},
        objection_rows=[{"title": "Risk", "detail": "Minor"}],
        household_rows=[{"title": "Parent", "detail": "Yes"}],
        risk_signal_rows=[{"title": "Signal", "detail": "Low"}],
    )
    assert snapshot["research_title"] == "Lead home"
    assert snapshot["research_candidate_ref"] == "cand-1"
    assert snapshot["research_gallery_items"][0]["kind"] == "image"
    assert snapshot["research_feedback"]["save_endpoint"] == "/app/api/property-feedback"
    assert snapshot["research_official_evidence_rows"][0]["title"] == "Cadastre"


def test_property_workbench_templates_render_provider_homepage_links_in_new_tabs() -> None:
    bundle = _read_workbench_bundle()
    assert 'data-provider-homepage-link' in bundle
    assert 'target="_blank"' in bundle
    assert 'rel="noopener noreferrer"' in bundle


def test_property_surface_scope_owns_loading_rules() -> None:
    properties_scope = PropertySurfaceScope.for_section("properties")
    search_scope = PropertySurfaceScope.for_section("search")
    billing_scope = PropertySurfaceScope.for_section("billing")
    shortlist_scope = PropertySurfaceScope.for_section("shortlist")

    assert properties_scope.wants_recent_runs is True
    assert properties_scope.wants_run_state is True
    assert properties_scope.wants_recent_matches is False
    assert properties_scope.wants_search_runs is False

    assert search_scope.wants_recent_runs is True
    assert search_scope.wants_run_state is False
    assert search_scope.wants_credit_digest is False

    assert billing_scope.wants_credit_digest is True
    assert billing_scope.wants_recent_runs is False
    assert billing_scope.wants_run_views is False

    assert shortlist_scope.wants_run_state is True
    assert shortlist_scope.wants_run_views is True


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


def test_property_scope_preview_without_boundary_data_uses_local_layout_fallback(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    preview = landing_view_models._property_scope_preview("AT", "vienna", "1020 Vienna")
    assert str(preview["image_url"]).startswith("data:image/svg+xml")
    assert preview["district_rows"] == []


def test_property_lookup_candidate_falls_back_to_shortlist_candidates_from_context() -> None:
    property_context = {
        "run": {
            "run_id": "run-1",
            "summary": {
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Buy | Vienna",
                        "top_candidates": [
                            {
                                "title": "Vienna apartment",
                                "property_url": "https://example.com/listing/1",
                                "source_ref": "property-scout:1",
                                "review_url": "",
                                "property_facts": {},
                            }
                        ],
                    }
                ],
            },
        }
    }
    candidate = dict(property_context["run"]["summary"]["sources"][0]["top_candidates"][0])
    candidate["source_label"] = "Willhaben | Austria | Buy | Vienna"
    candidate_ref = landing_property_research._property_candidate_ref(candidate)
    found = landing_property_research._property_lookup_candidate(property_context=property_context, candidate_ref=candidate_ref)
    assert found is not None
    assert found["property_url"] == "https://example.com/listing/1"


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


def test_base_console_identifies_rybbit_with_opaque_principal_id() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/base_console.html"
    body = template_path.read_text(encoding="utf-8")
    assert "analytics_principal_id" in body
    assert "rybbit.identify({{ analytics_principal_id|tojson }}" in body
    assert "rybbit.identify({{ principal_id|tojson }}" not in body


def test_property_customer_run_summary_strips_operator_only_fields() -> None:
    summary = landing_view_models._property_customer_run_summary(
        {
            "sources_total": 2,
            "timing_receipts": {"first_shortlist_ready_at": "2026-06-15T10:00:00+00:00"},
            "research_tasks": [{"task_id": "t-1"}],
            "sources": [
                {
                    "source_label": "Provider A",
                    "provider_quality": {"floorplan_reliability": "high"},
                    "listing_total": 12,
                    "high_fit_total": 3,
                    "timing_ms": {"provider_preview": 10.5},
                }
            ],
        }
    )
    assert "research_tasks" not in summary
    assert summary["timing_receipts"]["first_shortlist_ready_at"] == "2026-06-15T10:00:00+00:00"
    assert "provider_quality" not in summary["sources"][0]
    assert summary["sources"][0]["listing_total"] == 12


def test_property_search_worker_slots_prioritize_distinct_providers() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 2},
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
    assert providers[:2] == [
        "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        "immmo | Austria | Rent | 1010 Vienna",
    ]
    labels = [row.get("label") for row in worker_state.get("workers") or []]
    assert labels[:2] == ["DER STANDARD", "immmo"]
    assert worker_state["workers"][0]["shard_count"] == 1


def test_property_search_worker_slots_only_show_real_lanes_instead_of_plan_fillers() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 4},
            "progress": 12,
            "status": "running",
            "sources": [
                {"source_label": "Willhaben | Austria | Buy | Vienna", "platform": "willhaben_at", "status": "in_progress"},
                {"source_label": "immmo | Austria | Buy | Vienna", "platform": "immmo_at", "status": "failed", "error": "HTTP 410"},
            ],
        },
        plan_key="agent",
    )

    assert worker_state["visible_workers"] == 2
    assert len(worker_state["workers"]) == 2
    assert [row.get("status_label") for row in worker_state["workers"]] == ["Running", "Retrying"]
    assert all(row.get("label") != "Preparing sources" for row in worker_state["workers"])


def test_property_run_reliability_summary_surfaces_repair_and_eta_state() -> None:
    reliability = landing_property_workspace_helpers._property_run_reliability_summary(
        {
            "status": "running",
            "progress": 42,
            "message": "Retrying one provider while the shortlist stays visible.",
            "eta_label": "about 6m",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                ],
                "filtered_out_total": 7,
            },
        },
        results_total=3,
    )
    assert reliability["health_label"] == "Repairing"
    assert reliability["repair_step_label"] == "Retrying 1 source"
    assert reliability["coverage_label"] == "2/4 sources checked · 2 still running"
    assert reliability["result_label"] == "3 ranked results ready"
    assert reliability["filtered_label"] == "7 filtered by active rules"
    assert reliability["repair"]["repair_status"] == "repairing"
    assert reliability["repair"]["can_auto_repair"] is True


def test_property_run_reliability_summary_surfaces_completed_partial_state() -> None:
    reliability = landing_property_workspace_helpers._property_run_reliability_summary(
        {
            "status": "completed_partial",
            "message": "One provider stayed degraded.",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                    {"source_label": "C", "status": "completed"},
                    {"source_label": "D", "status": "completed"},
                ],
            },
        },
        results_total=4,
    )

    assert reliability["health_label"] == "Partial coverage"
    assert reliability["health_tone"] == "warn"
    assert reliability["customer_status_message"] == "One provider stayed degraded."
    assert reliability["repair"]["repair_status"] == "degraded"
    assert reliability["repair"]["repair_status_label"] == "Partial coverage"


def test_property_surface_state_builds_run_repair_snapshot() -> None:
    repair = property_surface_state.build_property_run_repair_snapshot(
        {
            "status": "running",
            "progress": 44,
            "eta_label": "about 6m",
            "summary": {
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                ],
            },
        },
        results_total=2,
    )

    assert repair["repair_status"] == "repairing"
    assert repair["repair_status_label"] == "Repairing"
    assert repair["repair_step_label"] == "Retrying 1 source"
    assert repair["repair_outcome_summary"] == "Some sources are retrying, but the current shortlist is already usable."
    assert repair["eta_confidence_label"] == "Medium"
    assert repair["can_auto_repair"] is True


def test_property_surface_state_builds_run_reliability_snapshot() -> None:
    reliability = property_surface_state.build_property_run_reliability_snapshot(
        {
            "status": "completed_partial",
            "message": "One provider stayed degraded.",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                    {"source_label": "C", "status": "completed"},
                    {"source_label": "D", "status": "completed"},
                ],
            },
        },
        results_total=4,
    )

    assert reliability["health_label"] == "Partial coverage"
    assert reliability["repair_step_label"] == "Retrying 1 source"
    assert reliability["repair"]["repair_status"] == "degraded"
    assert reliability["customer_status_message"] == "One provider stayed degraded."


def test_property_surface_state_builds_search_form_state_snapshot() -> None:
    snapshot = property_surface_state.build_property_search_form_state_snapshot(
        {
            "country_code": "at",
            "search_goal": "investment",
            "listing_mode": "rent",
            "investment_research_mode": "off",
            "investment_strategy": "cash_flow",
            "include_public_housing_signals": True,
            "include_distressed_sale_signals": True,
            "max_distance_to_playground_m": 500,
            "use_stored_feedback_preferences": False,
            "loan_term_years": "41",
            "min_dscr": "4.0",
            "vacancy_reserve_pct": "-3",
        },
        selected_listing_mode="rent",
    )

    assert snapshot["selected_country_code"] == "AT"
    assert snapshot["selected_search_goal"] == "investment"
    assert snapshot["selected_listing_mode"] == "buy"
    assert snapshot["property_is_investment_search"] is True
    assert snapshot["show_investment_underwriting_controls"] is False
    assert snapshot["show_public_housing_policy_controls"] is False
    assert snapshot["show_distressed_review_controls"] is True
    assert snapshot["show_playground_importance_controls"] is False
    assert snapshot["show_preference_profile_controls"] is False
    assert snapshot["loan_term_years"] == 40
    assert snapshot["min_dscr"] == 3.0
    assert snapshot["vacancy_reserve_pct"] == 0


def test_propertyquarry_results_template_marks_top_rank_and_watch_out_copy() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")
    assert "is-top-ranked" in body
    assert "Watch-out:" in body
    assert "Why it ranks:" in body


def test_propertyquarry_workspace_routes_render_greenfield_surfaces(monkeypatch) -> None:
    principal_id = "pq-redesign-browser"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PAYPAL_CHECKOUT", "1")
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
    monkeypatch.setattr(landing_property_research, "_property_investment_research_access_level", lambda *args, **kwargs: "full")
    monkeypatch.setattr(
        landing_property_research,
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
    assert ">Daily life<" in setup.text
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
    assert "Automation" in setup.text
    assert "Recurring searches, delivery, reports, and repair policy live in the dedicated automation view." in setup.text
    assert "Open automation" in setup.text
    assert "Last:" not in setup.text
    assert "Next:" not in setup.text
    assert "Sent 0/" not in setup.text
    assert "Save limits" not in setup.text
    assert 'data-search-agent-action="resume"' not in setup.text
    assert 'data-search-agent-action="duplicate"' not in setup.text
    assert 'data-search-agent-action="delete"' not in setup.text
    assert 'data-search-agent-action="run"' not in setup.text

    search_surface = client.get("/app/search", headers=headers)
    assert search_surface.status_code == 200
    assert 'data-property-decision-workbench' in search_surface.text
    assert "Search people, threads, commitments, decisions, deadlines, evidence, rules, and handoffs." not in search_surface.text

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
    assert "Price, layout, fit, and the strongest reason stay in the main list." in search.text
    assert 'class="pqx-result-reason"' in search.text
    assert 'class="pqx-status-line"' in search.text
    assert "Altbau near U6" in search.text
    assert "Family flat near Tiergarten" in search.text
    assert "360 ready" in search.text
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
    assert "Property details" in search.text
    assert "Why it made the shortlist" in search.text
    assert "Current read" in search.text
    assert "Optional context" in search.text
    assert "Artifact receipts" not in search.text
    assert "Share checklist" not in search.text
    assert "Would you pursue this property?" not in search.text
    assert "Save your decision" in search.text
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
    assert "Lift and transit fit." in search.text
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
    assert "What the wider evidence says" in packet.text
    assert "Energy posture and heating" in packet.text
    assert "School context" in packet.text
    assert "Gymnasium progression" in packet.text
    assert "Return and costs" in packet.text
    assert "Gross yield" in packet.text
    assert "Expected monthly rent" in packet.text
    assert "Decision support" in packet.text
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
    assert "Identity, defaults, delivery." in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Account" in alerts.text
    assert "Identity, defaults, delivery." in alerts.text

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
    assert "Billing" in billing.text
    assert "Plan and limits" in billing.text


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
    reference_block = legacy_body.split("const renderMagicFitReferenceList = () => {", 1)[1].split("renderMagicFitPreview(payload.magic_fit_scene || {});", 1)[0]
    assert "innerHTML" not in reference_block
    followup_block = legacy_body.split("const renderFollowups = (rows) => {", 1)[1].split("renderFollowups(payload.followup_rows || []);", 1)[0]
    assert "innerHTML" not in followup_block
    clippy_block = legacy_body.split("const renderClippy = (body) => {", 1)[1].split("clippyAskButton?.addEventListener", 1)[0]
    assert "innerHTML" not in clippy_block


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
    assert 'class="pqx-previous-delete"' in body
    assert 'class="pqx-previous-open-link"' in body
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
    body = _read_workbench_bundle()

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
    template_body = _read_workbench_bundle()
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
    assert "Ganztag matters" not in view_model_body
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
    assert '{"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"}' in body
    assert '{"href": f"/app/agents{run_suffix}", "label": "Automation"}' in body
    assert '{"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "Choose the target areas.", "href": f"/app/search{run_suffix}"}' in body


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


def test_property_workspace_payload_returns_decision_workbench_contract_shape() -> None:
    payload = landing_routes._property_workspace_payload(
        "billing",
        status={"workspace": {"name": "Contract Shape"}, "channels": {}},
        property_state={
            "preferences": {"country_code": "AT", "listing_mode": "buy"},
            "commercial": {"current_plan_label": "Agent", "current_plan_key": "agent"},
            "preference_bundle": {},
        },
    )

    assert payload["title"] == "Billing"
    assert isinstance(payload["decision_workbench"], dict)
    assert isinstance(payload["decision_workbench"]["run"], dict)
    assert isinstance(payload["decision_workbench"]["brief"], dict)
    assert payload["current_plan_label"] == "Agent"


def test_property_billing_payload_skips_full_preference_manager_build(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_property_preference_schema",
        lambda: (_ for _ in ()).throw(AssertionError("billing surface should not build the full preference manager schema")),
    )

    payload = landing_routes._property_workspace_payload(
        "billing",
        status={"workspace": {"name": "Billing Scope"}, "channels": {}},
        property_state={
            "preferences": {"country_code": "AT", "listing_mode": "buy"},
            "commercial": {"current_plan_label": "Agent", "current_plan_key": "agent"},
            "preference_bundle": {
                "preference_nodes": [
                    {"node_id": "node-1", "status": "active", "key": "budget_max", "value_json": 900000}
                ]
            },
        },
    )

    preference_manager = dict(payload.get("preference_manager") or {})
    assert preference_manager.get("schema") == {}
    assert preference_manager.get("nodes") == []
    assert len(list(preference_manager.get("active_nodes") or [])) == 1


def test_property_search_posture_summary_hides_child_rows_when_parent_toggles_are_off() -> None:
    payload = landing_routes._property_workspace_payload(
        "properties",
        status={"workspace": {"name": "Summary Hygiene"}, "channels": {}},
        property_state={
            "preferences": {
                "country_code": "AT",
                "search_goal": "investment",
                "listing_mode": "buy",
                "investment_research_mode": "off",
                "investment_strategy": "cash_flow",
                "min_gross_yield_pct": 6,
                "equity_available_eur": 250000,
                "min_dscr": 1.35,
                "enable_commute_research": False,
                "commute_destination": "Stephansplatz",
                "additional_reachability_targets": "Praterstern",
                "enable_lifestyle_research": False,
                "university_name": "WU Wien",
                "school_stage_preferences": ["volksschule"],
                "require_school_evidence": True,
                "school_quality_priority": "very_important",
                "include_developer_project_signals": False,
                "desired_project_stages": ["planned", "waitlist"],
                "include_public_housing_signals": False,
                "wiener_wohnticket_available": True,
                "subsidized_required": True,
                "miete_mit_kaufoption": True,
                "eigenmittel_max_eur": 25000,
                "application_window_days": 14,
                "include_distressed_sale_signals": False,
                "enable_auction_legal_review": True,
            },
            "commercial": {},
            "preference_bundle": {},
        },
    )

    search_posture_card = next(
        card
        for card in list(payload.get("primary_cards") or [])
        if str(card.get("eyebrow") or "").strip() == "Search posture"
    )
    labels = {
        str(item.get("title") or "").strip()
        for item in list(search_posture_card.get("items") or [])
        if isinstance(item, dict)
    }
    assert "Investment strategy" not in labels
    assert "Minimum gross yield" not in labels
    assert "Equity available" not in labels
    assert "Minimum DSCR" not in labels
    assert "Commute destination" not in labels
    assert "Additional destinations" not in labels
    assert "University focus" not in labels
    assert "Children" not in labels
    assert "School evidence" not in labels
    assert "School evidence priority" not in labels
    assert "Accepted project stages" not in labels
    assert "Wiener Wohn-Ticket" not in labels
    assert "Subsidized supply" not in labels
    assert "Miete mit Kaufoption" not in labels
    assert "Eigenmittel ceiling" not in labels
    assert "Application window" not in labels
    assert "Auction legal review" not in labels


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
                            "price_display": "EUR 1,150",
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
    assert "Open the right surface for the next decision." in page.text
    assert "1020 Vienna" in page.text
    assert "ranked" in page.text
    assert "EUR 1,150" in page.text
    assert "/app/shortlist?run_id=run-finished" in page.text
    assert "aria-label=\"Delete previous search\"" in page.text
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
    assert "Search failed" in page.text
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
    assert "Automation" in page.text
    assert "Vienna apartments" in page.text
    assert "Monteverde land" in page.text
    assert "Selected watch" in page.text
    assert "Limits" in page.text
    assert "Free" in page.text
    assert "Plus" in page.text
    assert "Agent" in page.text
    assert 'href="/app/agents"' in page.text
    assert "Delete</button>" in page.text
    assert "Run now</button>" in page.text
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

    assert "Open the right surface for the next decision." in body
    assert "data-pqx-previous-searches" in body
    assert 'class="pqx-previous-open-link"' in body
    assert 'data-pqx-delete-run="' in body
    assert "data-pqx-dashboard-summary" in body
    assert "Automation" in body
    assert "Start" in body
    assert "Recent decisions and reviews" in body
    assert "pqx-previous-scope-caption" in body
    assert "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);" in body
    assert "display: flex;" in body
    assert "<legend>Search flow</legend>" in body
    assert ".pqx-disclosure-summary {" in body
    assert ".pqx-disclosure-icon {" in body
    assert ".pqx-workflow-step:hover," in body


def test_property_shortlist_surface_is_single_column_and_results_first() -> None:
    body = _read_workbench_bundle()

    assert "pqx-results-single" in body
    assert "open one home for the full property page" in body
    assert "review it on the right" not in body
    assert "No price published" in body
    assert "pqx-state-strip" not in body
    assert 'aria-label="Current search context"' not in body
    assert 'aria-label="Account navigation"' in body
    assert ">Me<" not in body
    assert "Tell us what to find." not in body


def test_property_workspace_previous_search_delete_uses_real_api_endpoint() -> None:
    body = _read_workbench_bundle()
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "data-pqx-delete-run" in body
    assert "Delete this previous search from the dashboard?" in body
    assert "method: 'DELETE'" in body
    assert "delete_run_template" in view_model
    assert "_property_scope_preview" in view_model
    assert '"scope_preview": scope_preview' in view_model


def test_property_finished_search_results_prioritize_main_list_and_filtered_disclosure() -> None:
    body = _read_workbench_bundle()

    assert "data-pqx-finished-compare" in body
    assert "Best homes first" in body
    assert "Relax one filter" in body
    assert "Price, layout, fit, and the strongest reason stay in the main list." in body


def test_property_decision_save_uses_canonical_endpoint_and_renders_consequences() -> None:
    body = _read_workbench_bundle()

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


def test_propertyquarry_properties_auto_opens_latest_active_run_when_run_id_missing(monkeypatch) -> None:
    principal_id = "pq-live-run-auto-open"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Auto Open")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_list_runs(self, *, principal_id: str, limit: int = 8):
        assert principal_id == "pq-live-run-auto-open"
        return [
            {"run_id": "run-active-42", "status": "in_progress", "summary": {"status": "in_progress"}},
            {"run_id": "run-finished-1", "status": "processed", "summary": {"status": "processed"}},
        ]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-live-run-auto-open"
        assert run_id == "run-active-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "progress": 18,
            "message": "Checking fresh rental listings for Vienna.",
            "summary": {
                "status": "in_progress",
                "sources_total": 3,
                "listing_total": 7,
                "eta_label": "about 4 min",
                "sources": [],
            },
            "events": [
                {"step": "source_fetch", "message": "Checking fresh rental listings for Vienna.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_list_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    live = client.get("/app/properties", headers=headers)
    assert live.status_code == 200
    assert "Search in progress" in live.text
    assert "Checking fresh rental listings for Vienna." in live.text
    assert "Open a saved search or launch a new brief" not in live.text
    assert "run-active-42" in live.text


def test_propertyquarry_suppression_rows_use_summary_fallback_and_show_active_rule() -> None:
    rows = landing_property_workspace_helpers._property_suppression_rows(
        run_summary={
            "filtered_low_fit_total": 9,
            "filtered_area_total": 4,
            "filtered_location_total": 3,
        },
        source_rows=[],
        preferences={
            "min_match_score": 82,
            "min_area_m2": 70,
            "adjacent_area_radius_m": 500,
            "location_query": "Vienna",
        },
    )
    low_fit_row = next(row for row in rows if row.get("rule_key") == "Below fit threshold")
    assert "Current match bar: 82." in str(low_fit_row.get("detail") or "")
    location_row = next(row for row in rows if row.get("rule_key") == "Outside selected area")
    assert "Vienna" in str(location_row.get("detail") or "")
    assert "500 m spillover" in str(location_row.get("detail") or "")


def test_propertyquarry_shortlist_uses_run_search_goal_over_saved_defaults(monkeypatch) -> None:
    principal_id = "pq-run-goal-overrides-saved-defaults"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "investment",
            "investment_research_mode": "auto",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-run-goal-overrides-saved-defaults"
        assert run_id == "run-home-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "property_search_preferences": {
                "country_code": "AT",
                "language_code": "de",
                "listing_mode": "buy",
                "search_goal": "home",
                "investment_research_mode": "off",
                "location_query": "Vienna",
                "selected_platforms": ["willhaben"],
            },
            "summary": {
                "status": "processed",
                "ranked_candidates": [
                    {
                        "title": "Vienna family flat",
                        "property_url": "https://example.test/vienna-family-flat",
                        "fit_summary": "Strong home fit near parks and daily errands.",
                        "match_reasons": ["Parks and daily errands stay close."],
                        "property_facts": {
                            "price_display": "EUR 520,000",
                            "rooms": 3,
                            "area_m2": 82,
                            "postal_name": "1020 Wien",
                        },
                    }
                ],
                "sources": [],
            },
            "events": [{"step": "completed", "message": "Property scouting run completed.", "status": "processed"}],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    shortlist = client.get("/app/shortlist", params={"run_id": "run-home-42"}, headers={"host": "propertyquarry.com"})
    assert shortlist.status_code == 200
    assert '"search_goal": "home"' in shortlist.text
    assert "Find a home" in shortlist.text
    assert "ranked opportunities" not in shortlist.text
    assert "Why this ranks" not in shortlist.text
    assert "Open the investment read." not in shortlist.text


def test_propertyquarry_shortlist_panel_builds_cards_and_actions() -> None:
    def _priority_reason(match_reasons: list[str], mismatch_reasons: list[str], fit_summary: str) -> str:
        if match_reasons:
            return match_reasons[0]
        if mismatch_reasons:
            return mismatch_reasons[0]
        return fit_summary

    rows, cards = landing_property_shortlist_panel.build_property_shortlist_panel(
        property_summary={
            "sources": [
                {
                    "source_label": "Willhaben",
                    "top_candidates": [
                        {
                            "title": "Vienna family flat",
                            "fit_summary": "Strong home fit near parks and daily errands.",
                            "match_reasons": ["Near parks"],
                            "mismatch_reasons": ["Needs a second bathroom"],
                            "recommendation": "shortlist",
                            "review_url": "https://example.test/review",
                            "tour_url": "https://example.test/360",
                            "property_url": "https://example.test/source",
                            "property_facts": {
                                "nearest_starbucks_m": 240,
                                "future_change_research": {
                                    "school_atlas_progression_summary": "Strong local AHS transition.",
                                    "school_atlas_evidence_type": "verified",
                                },
                            },
                            "feedback_rows": [{"label": "Daily life works"}],
                        }
                    ],
                }
            ]
        },
        property_preferences={},
        active_run_id="run-42",
        wants_run_views=True,
        clean_candidate_copy=landing_view_models._clean_property_candidate_copy,
        candidate_priority_reason=_priority_reason,
        property_candidate_ref=landing_view_models._property_candidate_ref,
    )

    assert len(rows) == 1
    assert len(cards) == 1
    assert rows[0]["action_label"] == "Open property page"
    assert rows[0]["secondary_action_label"] == "Open listing"
    assert rows[0]["tertiary_action_label"] == "Open 360"
    assert rows[0]["quaternary_action_label"] == "Source"
    assert cards[0]["packet_url"].endswith("?run_id=run-42")
    assert cards[0]["lifestyle_highlights"][0]["label"] == "Starbucks"
    assert cards[0]["research_highlights"][0]["label"] == "School transition"
    source_rows = landing_property_shortlist_panel.build_property_source_rows(
        property_summary={
            "sources": [
                {
                    "source_label": "Willhaben",
                    "listing_total": 12,
                    "high_fit_total": 3,
                    "filtered_floorplan_total": 2,
                    "tour_created_total": 1,
                    "notified_total": 1,
                    "email_notified_total": 1,
                    "top_fit_score": 87.5,
                }
            ]
        }
    )
    assert source_rows == [
        {
            "title": "Willhaben",
            "detail": "12 listings | 3 high-fit | 2 still waiting on floorplans | 1 hosted tours | 1 client alerts | 1 email | top score 87.50",
            "tag": "Scanned",
        }
    ]


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


def test_propertyquarry_workspace_supports_area_select_all_actions() -> None:
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
    assert 'data-checkbox-group-select-all="location_query"' in search.text
    assert 'data-checkbox-group-clear-all="location_query"' in search.text
    assert 'name="full_region_scope" value="true" checked' in search.text


def test_propertyquarry_workspace_exposes_adjacent_area_radius_control() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    brief_script = (repo_root / "ea/app/templates/app/_property_workbench_brief_script.html").read_text(encoding="utf-8")
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert '"name": "adjacent_area_radius_value"' in view_models
    assert '"name": "adjacent_area_radius_unit"' in view_models
    assert 'data-range-unit-field="{{ field.get(\'unit_field\') or \'\' }}"' in template
    assert "adjacent_area_radius_m: adjacentAreaRadiusMeters" in brief_script


def test_propertyquarry_workspace_exposes_investment_goal_and_guardrails() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    brief_script = (repo_root / "ea/app/templates/app/_property_workbench_brief_script.html").read_text(encoding="utf-8")
    workbench_script = (repo_root / "ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")

    assert '"name": "search_goal"' in view_models
    assert '"label": "What are you looking for?"' in view_models
    assert '"name": "investment_strategy"' in view_models
    assert '"name": "min_gross_yield_pct"' in view_models
    assert '"name": "equity_available_eur"' in view_models
    assert '"name": "loan_term_years"' in view_models
    assert '"name": "max_interest_rate_pct"' in view_models
    assert '"name": "min_dscr"' in view_models
    assert '"name": "vacancy_reserve_pct"' in view_models
    assert '"name": "capex_reserve_pct"' in view_models
    assert '"name": "investment_require_legal_clarity"' in view_models
    assert '"name": "investment_require_tenant_clarity"' in view_models
    assert '"name": "investment_avoid_major_renovation"' in view_models
    assert "Choose the thesis first." in view_models
    assert "Use this as a hard floor for expected gross yield" in view_models
    assert "debt coverage and cash-on-cash yield" in view_models
    assert "A DSCR floor lets you exclude deals" in view_models
    assert "search_goal: searchGoal" in brief_script
    assert "const investmentResearchEnabled = searchGoal === 'investment' && investmentResearchMode !== 'off';" in brief_script
    assert "investment_strategy: investmentResearchEnabled" in brief_script
    assert "min_dscr: investmentResearchEnabled" in brief_script
    assert "const searchGoalField = form.querySelector('select[name=\"search_goal\"]');" in workbench_script
    assert "form.dataset.propertyExcludedSteps = 'children,reachability';" in workbench_script
    assert "const resyncSearchFormState = () => {" in workbench_script
    assert "}).finally(resyncSearchFormState);" in workbench_script
    assert "const lifestyleDetailWraps = [" in workbench_script
    assert "input[name=\"enable_lifestyle_research\"]')?.addEventListener('change', syncSearchGoalControls);" in workbench_script
    assert "university_name: Boolean(form.querySelector('input[name=\"enable_lifestyle_research\"]')?.checked)" in brief_script


def test_propertyquarry_workspace_surfaces_institutional_underwriting_language() -> None:
    bundle = _read_workbench_bundle()
    lowered = bundle.lower()
    assert "Institutional read" in bundle
    assert "institutional score" in lowered
    assert "return, value, demand, liquidity, risk control, execution effort, and evidence confidence" in lowered
    assert "External model" in bundle


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
    assert 'data-property-field-name="investment_research_mode" hidden' in search.text


def test_propertyquarry_workspace_hides_investment_research_for_home_buy() -> None:
    principal_id = "pq-home-buy-no-investment-filter"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Buy Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "investment_research_mode": "auto",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="investment_research_mode" hidden' in search.text
    assert 'data-property-field-name="investment_strategy" hidden' in search.text


def test_propertyquarry_workspace_hides_underwriting_controls_when_investment_depth_is_off() -> None:
    principal_id = "pq-investment-depth-off"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Investment Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "investment",
            "investment_research_mode": "off",
            "investment_strategy": "cash_flow",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="investment_research_mode"' in search.text
    assert 'data-property-field-name="investment_strategy" hidden' in search.text
    assert 'data-property-field-name="min_gross_yield_pct" hidden' in search.text
    assert 'data-property-field-name="equity_available_eur" hidden' in search.text
    assert 'data-property-field-name="loan_term_years" hidden' in search.text
    assert 'data-property-field-name="max_interest_rate_pct" hidden' in search.text
    assert 'data-property-field-name="min_dscr" hidden' in search.text
    assert 'data-property-field-name="vacancy_reserve_pct" hidden' in search.text
    assert 'data-property-field-name="capex_reserve_pct" hidden' in search.text
    assert 'data-property-field-name="investment_require_floorplan" hidden' in search.text
    assert 'data-property-field-name="investment_require_legal_clarity" hidden' in search.text


def test_propertyquarry_workspace_hides_rent_only_controls_for_investment_search() -> None:
    principal_id = "pq-investment-no-rent-lapse"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Investment Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "investment",
            "investment_research_mode": "off",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_public_housing_signals": True,
            "wiener_wohnticket_available": True,
            "subsidized_required": True,
            "miete_mit_kaufoption": True,
            "eigenmittel_max_eur": 50000,
            "application_window_days": 14,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="listing_mode" hidden' in search.text
    assert 'data-property-field-name="include_public_housing_signals" hidden' in search.text
    assert 'data-property-field-name="wiener_wohnticket_available" hidden' in search.text
    assert 'data-property-field-name="subsidized_required" hidden' in search.text
    assert 'data-property-field-name="miete_mit_kaufoption" hidden' in search.text
    assert 'data-property-field-name="eigenmittel_max_eur" hidden' in search.text
    assert 'data-property-field-name="application_window_days" hidden' in search.text


def test_propertyquarry_workspace_hides_buy_only_provider_controls_for_rent_search() -> None:
    principal_id = "pq-rent-no-buy-controls"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Rent Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_distressed_sale_signals": True,
            "enable_auction_legal_review": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_distressed_sale_signals" hidden' in search.text
    assert 'data-property-field-name="enable_auction_legal_review" hidden' in search.text


def test_propertyquarry_workspace_hides_community_validation_when_community_signals_are_off() -> None:
    principal_id = "pq-home-no-community-validation"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Community Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_community_signals": False,
            "require_manual_validation_for_community": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_community_signals"' in search.text
    assert 'data-property-field-name="require_manual_validation_for_community" hidden' in search.text


def test_propertyquarry_workspace_hides_public_housing_child_controls_when_public_housing_signals_are_off() -> None:
    principal_id = "pq-rent-no-public-housing-children"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Public Housing Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_public_housing_signals": False,
            "wiener_wohnticket_available": True,
            "subsidized_required": True,
            "miete_mit_kaufoption": True,
            "eigenmittel_max_eur": 50000,
            "application_window_days": 14,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_public_housing_signals"' in search.text
    assert 'data-property-field-name="wiener_wohnticket_available" hidden' in search.text
    assert 'data-property-field-name="subsidized_required" hidden' in search.text
    assert 'data-property-field-name="miete_mit_kaufoption" hidden' in search.text
    assert 'data-property-field-name="eigenmittel_max_eur" hidden' in search.text
    assert 'data-property-field-name="application_window_days" hidden' in search.text


def test_propertyquarry_workspace_hides_project_stage_controls_when_developer_signals_are_off() -> None:
    principal_id = "pq-no-developer-project-stage-children"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Developer Pipeline Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_developer_project_signals": False,
            "desired_project_stages": ["planned", "waitlist"],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_developer_project_signals"' in search.text
    assert 'data-property-field-name="desired_project_stages" hidden' in search.text


def test_propertyquarry_workspace_hides_recurring_search_details_when_recurring_search_is_off() -> None:
    principal_id = "pq-no-recurring-search-details"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Recurring Search Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "search_agent_enabled": False,
            "search_agent_duration_days": 90,
            "search_agent_notification_limit": 9,
            "search_agent_notification_period": "week",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="search_agent_enabled"' in search.text
    assert 'data-property-field-name="search_agent_duration_days" hidden' in search.text
    assert 'data-property-field-name="search_agent_notification_limit" hidden' in search.text
    assert 'data-property-field-name="search_agent_notification_period" hidden' in search.text


def test_propertyquarry_workspace_hides_preference_profile_when_stored_feedback_is_off() -> None:
    principal_id = "pq-no-stored-feedback-profile"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Feedback Profile Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "use_stored_feedback_preferences": False,
            "preference_person_id": "partner-profile",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="use_stored_feedback_preferences"' in search.text
    assert 'data-property-field-name="preference_person_id" hidden' in search.text


def test_propertyquarry_workspace_hides_auction_review_when_distressed_signals_are_off() -> None:
    principal_id = "pq-buy-no-distressed-review"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Auction Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_distressed_sale_signals": False,
            "enable_auction_legal_review": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_distressed_sale_signals"' in search.text
    assert 'data-property-field-name="enable_auction_legal_review" hidden' in search.text


def test_propertyquarry_workspace_hides_lifestyle_detail_controls_when_lifestyle_research_is_off() -> None:
    principal_id = "pq-home-no-lifestyle-detail"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Lifestyle Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "enable_lifestyle_research": False,
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "university_name": "WU",
            "max_distance_to_university_m": 500,
            "max_distance_to_starbucks_m": 300,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="enable_lifestyle_research"' in search.text
    assert 'data-property-field-name="university_name" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_university_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_starbucks_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_fitness_center_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_cinema_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_bouldering_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_dog_park_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_good_cafe_m" hidden' in search.text


def test_propertyquarry_workspace_hides_school_evidence_priority_when_school_evidence_is_inactive() -> None:
    principal_id = "pq-home-no-school-evidence-priority"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="School Evidence Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "school_quality_priority": "very_important",
            "require_school_evidence": False,
            "school_stage_preferences": [],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="school_quality_priority" hidden' in search.text


def test_propertyquarry_workspace_hides_distance_importance_controls_without_distance_caps() -> None:
    principal_id = "pq-home-no-distance-importance"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Distance Importance Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "max_distance_to_playground_m": 0,
            "max_distance_to_playground_importance": "must_have",
            "max_distance_to_library_m": 0,
            "max_distance_to_library_importance": "must_have",
            "max_distance_to_supermarket_m": 0,
            "max_distance_to_supermarket_importance": "must_have",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="max_distance_to_playground_importance" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_library_importance" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_supermarket_importance" hidden' in search.text


def test_propertyquarry_workspace_setup_stays_user_facing() -> None:
    principal_id = "pq-provider-quality"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Property Office")
    response = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert response.status_code == 200
    assert "Run" in response.text
    assert "Automation" in response.text
    assert "Open automation" in response.text
    assert "Open preferences" in response.text
    assert "Build the brief. Then let the agents work." not in response.text


def test_property_workspace_search_controls_have_explicit_click_handlers() -> None:
    body = _read_workbench_bundle()

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
        landing_property_research,
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
    assert "Institutional underwriting score" in packet.text


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
    monkeypatch.setattr(landing_property_research, "_property_investment_research_snapshot", lambda **kwargs: {})

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
    monkeypatch.setattr(landing_property_research, "_property_investment_research_snapshot", lambda **kwargs: {})

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
    assert "Identity, defaults, delivery." in account.text
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

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert ">Search<" in response.text
    assert ">Run<" not in response.text
    assert ">Shortlist<" in response.text
    assert ">Automation<" in response.text
    assert ">Account<" in response.text
    assert 'href="/app/research"' not in response.text
    assert ">Alerts<" not in response.text
    assert ">Billing<" in response.text
