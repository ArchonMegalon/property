from __future__ import annotations

from scripts.propertyquarry_live_mobile_surface_smoke import DEFAULT_ROUTES, evaluate_mobile_metrics


def _base_metrics() -> dict[str, object]:
    return {
        "status_code": 200,
        "body_width": 390,
        "viewport_width": 390,
        "topbar_height": 72,
        "topnav_visible": True,
        "mobile_dock_visible": True,
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
    }


def _failed_names(route: str, metrics: dict[str, object]) -> set[str]:
    return {str(row["name"]) for row in evaluate_mobile_metrics(route, metrics) if not row["ok"]}


def test_live_mobile_smoke_accepts_compact_search_surface_metrics() -> None:
    assert _failed_names("/app/search", _base_metrics()) == set()


def test_live_mobile_smoke_accepts_empty_shortlist_without_mode_dock() -> None:
    metrics = _base_metrics()
    metrics.update({"mobile_dock_visible": False})

    assert _failed_names("/app/shortlist", metrics) == set()


def test_live_mobile_smoke_accepts_research_and_packets_surfaces_without_search_controls() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "mobile_dock_visible": False,
            "district_picker_available": False,
            "district_map_popup_available": False,
            "district_list_hidden_in_map_mode": False,
        }
    )

    assert _failed_names("/app/research", metrics) == set()
    assert _failed_names("/app/properties/packets", metrics) == set()


def test_live_mobile_smoke_default_routes_cover_settings_surfaces() -> None:
    assert {
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
    }.issubset(set(DEFAULT_ROUTES))


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
