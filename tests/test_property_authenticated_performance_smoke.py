from __future__ import annotations

import subprocess
import sys
import os

from scripts.propertyquarry_authenticated_performance_smoke import build_authenticated_performance_receipt, _route_budget_for


def test_property_authenticated_performance_smoke_receipt_passes() -> None:
    receipt = build_authenticated_performance_receipt(route_budget_ms=1200)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    routes = {str(row["path"]).split("?", 1)[0]: row for row in receipt["routes"]}
    expected_mobile_surfaces = {
        "/app/search",
        "/app/agents",
        "/app/properties",
        "/app/shortlist",
        "/app/research/perf-candidate-1020",
        "/app/alerts",
        "/app/account",
        "/app/billing",
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
    for route in routes.values():
        check_names = {str(check["name"]): bool(check["ok"]) for check in route["checks"]}
        assert check_names["mobile_viewport_meta"]
        assert check_names["shared_top_navigation"]
        assert check_names["property_app_shell"]
        assert check_names["mobile_dock_target"]
        assert check_names["rybbit_no_identify"]
        assert check_names["rybbit_taxonomy_events_only"]
        assert check_names["rybbit_allowed_attributes_only"]
        assert check_names["rybbit_no_private_payload"]
    assert any(check["name"] == "map_only_thumbnails" and check["ok"] for check in routes["/app/agents"]["checks"])
    assert any(check["name"] == "media_requests_explicit" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_confirmed_listing_facts" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "research_confirmed_price_signal" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])
    assert any(check["name"] == "delivery_controls" and check["ok"] for check in routes["/app/alerts"]["checks"])
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
    )

    assert result.returncode == 0, result.stderr
    assert '"status": "pass"' in result.stdout
    assert '"/app/agents"' in result.stdout
    assert '"/app/alerts' in result.stdout
    assert '"/app/settings/google"' in result.stdout
    assert '"/app/settings/access"' in result.stdout
    assert '"/app/settings/usage"' in result.stdout
    assert '"/app/settings/support"' in result.stdout
    assert '"/app/settings/trust"' in result.stdout
    assert '"/app/settings/invitations"' in result.stdout
    assert '"shared_top_navigation"' in result.stdout
    assert '"mobile_dock_target"' in result.stdout
    assert '"rybbit_taxonomy_events_only"' in result.stdout
    assert '"rybbit_no_private_payload"' in result.stdout


def test_property_authenticated_performance_smoke_budget_override_applies_to_default_routes() -> None:
    assert _route_budget_for("/app/search", route_budget_ms=250) == 250
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
    )

    assert result.returncode == 1
    assert '"status": "fail"' in result.stdout
    assert '"under_budget"' in result.stdout
