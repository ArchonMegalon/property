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
    assert routes["/app/agents"]["duration_ms"] <= routes["/app/agents"]["budget_ms"]
    assert routes["/app/research/perf-candidate-1020"]["duration_ms"] <= routes["/app/research/perf-candidate-1020"]["budget_ms"]
    for route in routes.values():
        check_names = {str(check["name"]): bool(check["ok"]) for check in route["checks"]}
        assert check_names["mobile_viewport_meta"]
        assert check_names["shared_top_navigation"]
        assert check_names["property_app_shell"]
        assert check_names["mobile_dock_target"]
    assert any(check["name"] == "map_only_thumbnails" and check["ok"] for check in routes["/app/agents"]["checks"])
    assert any(check["name"] == "media_requests_explicit" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])


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
    assert '"shared_top_navigation"' in result.stdout
    assert '"mobile_dock_target"' in result.stdout


def test_property_authenticated_performance_smoke_budget_override_applies_to_default_routes() -> None:
    assert _route_budget_for("/app/search", route_budget_ms=250) == 250
    assert _route_budget_for("/app/agents", route_budget_ms=250) == 250
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
