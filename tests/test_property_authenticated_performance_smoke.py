from __future__ import annotations

import subprocess
import sys
import os

from scripts.propertyquarry_authenticated_performance_smoke import build_authenticated_performance_receipt


def test_property_authenticated_performance_smoke_receipt_passes() -> None:
    receipt = build_authenticated_performance_receipt(route_budget_ms=1200)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    routes = {str(row["path"]).split("?", 1)[0]: row for row in receipt["routes"]}
    assert routes["/app/agents"]["duration_ms"] <= routes["/app/agents"]["budget_ms"]
    assert routes["/app/research/perf-candidate-1020"]["duration_ms"] <= routes["/app/research/perf-candidate-1020"]["budget_ms"]
    assert any(check["name"] == "map_only_thumbnails" and check["ok"] for check in routes["/app/agents"]["checks"])
    assert any(check["name"] == "media_requests_explicit" and check["ok"] for check in routes["/app/research/perf-candidate-1020"]["checks"])


def test_property_authenticated_performance_smoke_script_emits_receipt() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/propertyquarry_authenticated_performance_smoke.py"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "ea"},
    )

    assert result.returncode == 0, result.stderr
    assert '"status": "pass"' in result.stdout
    assert '"/app/agents"' in result.stdout
