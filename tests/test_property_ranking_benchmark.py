from __future__ import annotations

import subprocess
import sys

from scripts import check_property_ranking_benchmark as benchmark


def test_property_ranking_benchmark_passes() -> None:
    receipt = benchmark.build_benchmark_receipt()

    assert receipt["status"] == "ok"
    metrics = dict(receipt["metrics"])
    assert metrics["recall_at_20"] == 1.0
    assert metrics["hard_filter_violation_count"] == 0
    assert metrics["soft_filter_hitset_preserved"] is True
    assert metrics["top_candidate_ok"] is True
    assert metrics["low_score_notifications_suppressed"] is True
    assert metrics["soft_distance_gates_score_only"] is True
    assert metrics["hard_distance_gate_blocks"] is True
    assert receipt["actual_hard_filtered"] == ["wrong-1090", "wrong-1220", "wrong-salzburg"]
    assert receipt["hard_hitset"] == receipt["soft_hitset"]


def test_property_ranking_benchmark_executable_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_ranking_benchmark.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "propertyquarry.offline_ranking_benchmark.v1" in result.stdout


def test_property_ranking_benchmark_detects_wrong_area_leak(monkeypatch) -> None:
    original = benchmark.product_service._property_candidate_matches_requested_location

    def _leaky_location_match(**kwargs) -> bool:
        if "salzburg" in str(kwargs.get("property_url") or "").lower():
            return True
        return original(**kwargs)

    monkeypatch.setattr(
        benchmark.product_service,
        "_property_candidate_matches_requested_location",
        _leaky_location_match,
    )

    receipt = benchmark.build_benchmark_receipt()

    assert receipt["status"] == "failed"
    assert dict(receipt["metrics"])["hard_filter_violation_count"] > 0
