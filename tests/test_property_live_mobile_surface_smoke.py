from __future__ import annotations

from scripts.propertyquarry_live_mobile_surface_smoke import (
    DEFAULT_ROUTES,
    SEEDED_RESEARCH_DETAIL_ROUTE,
    build_live_mobile_surface_receipt,
    build_mobile_coverage_checks,
    evaluate_mobile_metrics,
    route_is_research_detail,
    routes_require_api_auth,
    seeded_research_detail_payload,
)


def _base_metrics() -> dict[str, object]:
    return {
        "status_code": 200,
        "body_width": 390,
        "viewport_width": 390,
        "topbar_height": 72,
        "topnav_visible": True,
        "min_action_height": 46,
        "visible_card_count": 12,
        "heavy_shadow_count": 0,
        "district_picker_available": True,
        "district_map_popup_available": True,
        "district_list_hidden_in_map_mode": True,
        "district_map_modal_opened": True,
        "district_map_click_selected": True,
        "district_map_zoom_changed": True,
        "district_map_close_restored_scroll": True,
        "mobile_what_matters_single_open": True,
        "account_logout_strip_visible": True,
        "logout_button_count": 1,
        "research_detail_workspace": True,
        "research_detail_decision_after_aside": True,
        "research_detail_media_stage": True,
        "research_detail_visual_controls": True,
        "research_detail_fake_visual_ready": False,
        "research_detail_generated_reconstruction_honest": True,
    }


def _failed_names(route: str, metrics: dict[str, object]) -> set[str]:
    return {str(row["name"]) for row in evaluate_mobile_metrics(route, metrics) if not row["ok"]}


def test_live_mobile_smoke_accepts_compact_search_surface_metrics() -> None:
    assert _failed_names("/app/search", _base_metrics()) == set()


def test_live_mobile_smoke_accepts_empty_shortlist_with_top_navigation_only() -> None:
    metrics = _base_metrics()

    assert _failed_names("/app/shortlist", metrics) == set()


def test_live_mobile_smoke_accepts_external_billing_handoff() -> None:
    metrics = _base_metrics()
    metrics.update({"status_code": 303, "redirect_location": "https://billing.propertyquarry.com/account"})

    assert _failed_names("/app/billing", metrics) == set()


def test_live_mobile_smoke_accepts_fail_closed_billing_recovery() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 503,
            "billing_visible_text": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        }
    )

    assert _failed_names("/app/billing", metrics) == set()


def test_live_mobile_smoke_rejects_local_billing_page() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 503,
            "billing_visible_text": "PropertyQuarry Plan Agent Billing history Compare plans Open pricing",
        }
    )

    assert _failed_names("/app/billing", metrics) == {
        "billing_fail_closed_recovery",
        "billing_local_page_deleted",
    }


def test_live_mobile_smoke_rejects_local_billing_redirect_loop() -> None:
    metrics = _base_metrics()
    metrics.update({"status_code": 303, "redirect_location": "/app/billing"})

    assert _failed_names("/app/billing", metrics) == {"billing_external_handoff"}


def test_live_mobile_smoke_accepts_research_and_packets_surfaces_without_search_controls() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "district_picker_available": False,
            "district_map_popup_available": False,
            "district_list_hidden_in_map_mode": False,
        }
    )

    assert _failed_names("/app/research", metrics) == set()
    assert _failed_names("/app/properties/packets", metrics) == set()


def test_live_mobile_smoke_requires_real_research_detail_layout() -> None:
    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", _base_metrics()) == set()
    metrics = _base_metrics()
    metrics.update(
        {
            "research_detail_workspace": False,
            "research_detail_decision_after_aside": False,
            "research_detail_media_stage": False,
            "research_detail_visual_controls": False,
            "research_detail_fake_visual_ready": True,
            "research_detail_generated_reconstruction_honest": False,
        }
    )

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_workspace",
        "research_detail_decision_after_aside",
        "research_detail_media_stage",
        "research_detail_visual_controls",
        "research_detail_no_fake_visual_ready",
        "research_detail_generated_reconstruction_honest",
    }


def test_live_mobile_smoke_rejects_generated_reconstruction_without_verified_tour_path() -> None:
    metrics = _base_metrics()
    metrics["research_detail_generated_reconstruction_honest"] = False

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_generated_reconstruction_honest",
    }


def test_live_mobile_smoke_default_routes_cover_settings_surfaces() -> None:
    assert {
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
    }.issubset(set(DEFAULT_ROUTES))


def test_live_mobile_smoke_blocks_app_routes_without_api_token_before_playwright() -> None:
    assert routes_require_api_auth(("/app/search",)) is True
    assert routes_require_api_auth(("/pricing",)) is False

    receipt = build_live_mobile_surface_receipt(
        base_url="http://localhost:8097",
        api_token="",
        principal_id="pq-live-mobile-smoke",
        routes=("/app/search",),
    )

    assert receipt["status"] == "blocked"
    assert receipt["routes"] == []
    assert receipt["coverage_checks"] == [
        {
            "name": "api_token_present_for_app_routes",
            "ok": False,
            "reason": "Live mobile app-surface smoke requires EA_API_TOKEN or --api-token; otherwise protected pages render sign-in redirects instead of the app UI.",
        }
    ]


def test_live_mobile_smoke_can_require_current_research_detail_route() -> None:
    assert route_is_research_detail("/app/research") is False
    assert route_is_research_detail("/app/research/current-result?run_id=run-gold") is True

    missing = build_mobile_coverage_checks(DEFAULT_ROUTES, require_research_detail=True)
    assert missing == [
        {
            "name": "research_detail_route_configured",
            "ok": False,
            "required_route_prefix": "/app/research/",
            "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
        }
    ]

    covered = build_mobile_coverage_checks(
        (*DEFAULT_ROUTES, "/app/research/current-result?run_id=run-gold"),
        require_research_detail=True,
    )
    assert covered[0]["ok"] is True


def test_live_mobile_smoke_seeded_research_detail_payload_is_valid_detail_fixture() -> None:
    payload = seeded_research_detail_payload()
    candidates = list(payload["saved_shortlist_candidates"])
    candidate = dict(candidates[0])

    assert route_is_research_detail(SEEDED_RESEARCH_DETAIL_ROUTE) is True
    assert payload["location_query"] == "1020 Vienna"
    assert candidate["candidate_ref"] == "perf-candidate-1020"
    assert candidate["saved_from_run_id"] == "run-gold-mobile"
    assert candidate["packet_url"] == "/app/research/perf-candidate-1020"
    assert dict(candidate["property_facts"])["listing_fact_confirmation"]["status"] == "confirmed"


def test_live_mobile_smoke_rejects_horizontal_overflow_and_noisy_chrome() -> None:
    metrics = _base_metrics()
    metrics.update({"body_width": 420, "topbar_height": 140, "heavy_shadow_count": 5})

    assert _failed_names("/app/search", metrics) == {
        "no_horizontal_overflow",
        "compact_topbar",
        "low_shadow_noise",
    }


def test_live_mobile_smoke_requires_search_district_picker_popup() -> None:
    metrics = _base_metrics()
    metrics.update({"district_map_popup_available": False, "district_list_hidden_in_map_mode": False})

    assert _failed_names("/app/search", metrics) == {
        "district_map_popup_available",
        "district_list_not_visible_in_map_mode",
    }


def test_live_mobile_smoke_requires_interactive_search_district_map() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "district_map_modal_opened": False,
            "district_map_click_selected": False,
            "district_map_zoom_changed": False,
            "district_map_close_restored_scroll": False,
        }
    )

    assert _failed_names("/app/search", metrics) == {
        "district_map_modal_opens",
        "district_map_click_selects_shape",
        "district_map_zoom_toggle_changes_scale",
        "district_map_close_restores_scroll",
    }


def test_live_mobile_smoke_requires_single_open_what_matters_group() -> None:
    metrics = _base_metrics()
    metrics.update({"mobile_what_matters_single_open": False})

    assert _failed_names("/app/search", metrics) == {"mobile_what_matters_single_open_section"}


def test_live_mobile_smoke_requires_single_account_logout() -> None:
    metrics = _base_metrics()
    metrics.update({"logout_button_count": 2})

    assert _failed_names("/app/account", metrics) == {"single_logout_action"}


def test_live_mobile_smoke_rejects_small_packet_touch_targets() -> None:
    metrics = _base_metrics()
    metrics.update({"min_action_height": 40})

    assert _failed_names("/app/properties/packets", metrics) == {"primary_touch_targets"}
