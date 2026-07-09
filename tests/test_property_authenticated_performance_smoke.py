from __future__ import annotations

import subprocess
import sys
import os
import json

from scripts.propertyquarry_authenticated_performance_smoke import (
    PERFORMANCE_SMOKE_MAX_PRICE_EUR,
    build_authenticated_performance_receipt,
    _synthetic_candidate,
    _property_preferences_payload,
    _route_budget_for,
)


SMOKE_SUBPROCESS_TIMEOUT_SECONDS = 120


def test_property_authenticated_performance_seeded_preferences_include_budget() -> None:
    payload = _property_preferences_payload()

    assert payload["max_price_eur"] == PERFORMANCE_SMOKE_MAX_PRICE_EUR
    primary_agent = payload["search_agents"][0]
    assert primary_agent["max_price_eur"] == PERFORMANCE_SMOKE_MAX_PRICE_EUR
    assert primary_agent["preferences_json"]["max_price_eur"] == PERFORMANCE_SMOKE_MAX_PRICE_EUR


def test_property_authenticated_performance_synthetic_candidate_preseeds_location_research() -> None:
    candidate = _synthetic_candidate()
    facts = candidate["property_facts"]

    assert facts["map_location_precision"] == "address"
    assert facts["map_lat"] == 48.22317
    assert facts["map_lng"] == 16.39594
    assert facts["nearest_playground_m"] == 310
    assert facts["nearest_supermarket_name"] == "BILLA Praterstern"
    assert facts["nearest_subway_name"] == "Praterstern"
    assert facts["nearest_flowing_water_name"] == "Donaukanal"


def test_property_authenticated_performance_smoke_receipt_passes() -> None:
    receipt = build_authenticated_performance_receipt(route_budget_ms=1200)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    routes = {str(row["path"]).split("?", 1)[0]: row for row in receipt["routes"]}
    expected_mobile_surfaces = {
        "/sign-in",
        "/app/search",
        "/app/agents",
        "/app/properties",
        "/app/shortlist",
        "/app/research/perf-candidate-1020",
        "/app/alerts",
        "/app/account",
        "/app/billing",
    }
    settings_mobile_surfaces = {
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
    }
    assert expected_mobile_surfaces.issubset(routes)
    assert routes["/app/agents"]["duration_ms"] <= routes["/app/agents"]["budget_ms"]
    assert routes["/app/research/perf-candidate-1020"]["duration_ms"] <= routes["/app/research/perf-candidate-1020"]["budget_ms"]
    content_first_mobile_surfaces = {
        "/app/agents",
        "/app/alerts",
        "/app/account",
        "/app/billing",
    }
    for route in routes.values():
        check_names = {str(check["name"]): bool(check["ok"]) for check in route["checks"]}
        route_path = str(route["path"]).split("?", 1)[0]
        assert check_names["no_visible_internal_proof_copy"]
        if route_path == "/app/billing" and (
            check_names.get("billing_external_handoff_redirect") or check_names.get("billing_fail_closed_recovery")
            or check_names.get("billing_internal_account_fallback")
        ):
            continue
        assert check_names["mobile_viewport_meta"]
        if route_path == "/sign-in":
            assert check_names["public_auth_surface"]
            continue
        assert check_names["shared_top_navigation"]
        assert check_names["property_app_shell"]
        if route_path in content_first_mobile_surfaces:
            assert check_names["mobile_content_first_surface"]
            assert check_names["mobile_static_switch_suppressed"]
        elif route_path in settings_mobile_surfaces:
            assert check_names["mobile_settings_surface"]
        else:
            assert check_names["mobile_top_navigation_only"]
            assert check_names["mobile_top_navigation_touch_targets"]
        assert check_names["rybbit_no_identify"]
        assert check_names["rybbit_taxonomy_events_only"]
        assert check_names["rybbit_allowed_attributes_only"]
        assert check_names["rybbit_no_private_payload"]
    assert any(check["name"] == "map_only_thumbnails" and check["ok"] for check in routes["/app/agents"]["checks"])
    assert any(check["name"] == "media_requests_explicit" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_visual_cards_present" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_visual_requests_honest" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_no_fake_visual_ready" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_listing_facts" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_listed_price_signal" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_ranking_only_no_compare_cards" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_mobile_open_property_compact_layout" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_mobile_visual_frame_compact" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "results_ranking_only_no_compare_cards" and check["ok"] for check in routes["/app/properties"]["checks"])
    assert any(check["name"] == "results_ranking_only_no_compare_cards" and check["ok"] for check in routes["/app/shortlist"]["checks"])
    assert any(check["name"] == "results_ranked_not_compare_copy" and check["ok"] for check in routes["/app/properties"]["checks"])
    assert any(check["name"] == "search_gzip_delivery" and check["ok"] for check in routes["/app/search"]["checks"])
    assert any(check["name"] == "search_gzip_vary_accept_encoding" and check["ok"] for check in routes["/app/search"]["checks"])
    payload_budget_check = next(
        check for check in routes["/app/search"]["checks"] if check["name"] == "search_compressed_payload_under_budget"
    )
    assert payload_budget_check["ok"]
    assert 0 < int(payload_budget_check["compressed_bytes"]) <= int(payload_budget_check["max_bytes"])
    assert any(check["name"] == "what_matters_distance_controls_compact" and check["ok"] for check in routes["/app/search"]["checks"])
    assert any(check["name"] == "what_matters_school_distance_controls" and check["ok"] for check in routes["/app/search"]["checks"])
    assert any(check["name"] == "delivery_controls" and check["ok"] for check in routes["/app/alerts"]["checks"])
    assert any(check["name"] == "connected_identity_implicit_account_creation" and check["ok"] for check in routes["/sign-in"]["checks"])
    assert any(check["name"] == "connected_identity_copy_is_customer_safe" and check["ok"] for check in routes["/sign-in"]["checks"])
    assert any(
        check["name"] in {"billing_external_handoff_redirect", "billing_fail_closed_recovery", "billing_internal_account_fallback"} and check["ok"]
        for check in routes["/app/billing"]["checks"]
    )
    assert any(check["name"] == "notification_destination_controls" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "notification_primary_channel_controls" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "notification_opt_in_copy" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "notification_secret_safe" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "account_direct_logout_strip" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "account_single_logout_action" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "account_no_top_dropdown_duplicate_logout" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "account_logout_mobile_target" and check["ok"] for check in routes["/app/account"]["checks"])
    assert any(check["name"] == "implicit_account_creation_copy" and check["ok"] for check in routes["/app/settings/google"]["checks"])
    assert any(check["name"] == "account_access_controls" and check["ok"] for check in routes["/app/settings/access"]["checks"])
    assert any(check["name"] == "usage_metrics_visible" and check["ok"] for check in routes["/app/settings/usage"]["checks"])
    assert any(check["name"] == "support_recovery_controls" and check["ok"] for check in routes["/app/settings/support"]["checks"])
    assert any(check["name"] == "trust_evidence_visible" and check["ok"] for check in routes["/app/settings/trust"]["checks"])
    assert any(check["name"] == "invitation_controls_visible" and check["ok"] for check in routes["/app/settings/invitations"]["checks"])


def test_property_authenticated_performance_smoke_script_emits_receipt() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "scripts/propertyquarry_authenticated_performance_smoke.py"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=SMOKE_SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert '"status": "pass"' in result.stdout
    assert '"/sign-in"' in result.stdout
    assert '"/app/agents"' in result.stdout
    assert '"/app/alerts' in result.stdout
    assert '"/app/settings/google"' in result.stdout
    assert '"/app/settings/access"' in result.stdout
    assert '"/app/settings/usage"' in result.stdout
    assert '"/app/settings/support"' in result.stdout
    assert '"/app/settings/trust"' in result.stdout
    assert '"/app/settings/invitations"' in result.stdout
    assert '"shared_top_navigation"' in result.stdout
    assert '"mobile_top_navigation_only"' in result.stdout
    assert '"mobile_top_navigation_touch_targets"' in result.stdout
    assert '"mobile_content_first_surface"' in result.stdout
    assert '"mobile_static_switch_suppressed"' in result.stdout
    assert '"mobile_settings_surface"' in result.stdout
    assert (
        '"billing_external_handoff_redirect"' in result.stdout
        or '"billing_fail_closed_recovery"' in result.stdout
        or '"billing_internal_account_fallback"' in result.stdout
    )
    assert '"research_mobile_open_property_compact_layout"' in result.stdout
    assert '"research_mobile_visual_frame_compact"' in result.stdout
    assert '"connected_identity_implicit_account_creation"' in result.stdout
    assert '"research_visual_requests_honest"' in result.stdout
    assert '"research_no_fake_visual_ready"' in result.stdout
    assert '"research_ranking_only_no_compare_cards"' in result.stdout
    assert '"results_ranking_only_no_compare_cards"' in result.stdout
    assert '"search_gzip_delivery"' in result.stdout
    assert '"search_gzip_vary_accept_encoding"' in result.stdout
    assert '"search_compressed_payload_under_budget"' in result.stdout
    assert '"what_matters_distance_controls_compact"' in result.stdout
    assert '"what_matters_school_distance_controls"' in result.stdout
    assert '"notification_destination_controls"' in result.stdout
    assert '"account_direct_logout_strip"' in result.stdout
    assert '"account_single_logout_action"' in result.stdout
    assert '"rybbit_taxonomy_events_only"' in result.stdout
    assert '"rybbit_no_private_payload"' in result.stdout
    assert '"no_visible_internal_proof_copy"' in result.stdout


def test_property_authenticated_performance_smoke_script_writes_receipt(tmp_path) -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    receipt_path = tmp_path / "property-auth-performance.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/propertyquarry_authenticated_performance_smoke.py",
            "--write",
            str(receipt_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=SMOKE_SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert receipt_path.exists()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["failed_count"] == 0
    assert payload["route_count"] == 15
    assert '"status": "pass"' in result.stdout


def test_property_authenticated_performance_smoke_budget_override_applies_to_default_routes() -> None:
    assert _route_budget_for("/app/search", route_budget_ms=250) == 250
    assert _route_budget_for("/sign-in", route_budget_ms=250) == 250
    assert _route_budget_for("/app/agents", route_budget_ms=250) == 250
    assert _route_budget_for("/app/alerts?run_id=abc", route_budget_ms=250) == 250
    assert _route_budget_for("/app/settings/google", route_budget_ms=250) == 250
    assert _route_budget_for("/app/settings/usage", route_budget_ms=250) == 250
    assert _route_budget_for("/app/settings/support", route_budget_ms=250) == 250
    assert _route_budget_for("/app/settings/trust", route_budget_ms=250) == 250
    assert _route_budget_for("/app/settings/invitations", route_budget_ms=250) == 250
    assert _route_budget_for("/app/research/perf-candidate-1020?run_id=abc", route_budget_ms=250) == 250


def test_property_authenticated_performance_smoke_script_fails_under_tight_budget() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "scripts/propertyquarry_authenticated_performance_smoke.py", "--route-budget-ms", "1"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=SMOKE_SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 1
    assert '"status": "fail"' in result.stdout
    assert '"under_budget"' in result.stdout
