from __future__ import annotations

from scripts.propertyquarry_matterport_sdk_walkthrough_gate import (
    _frame_metrics,
    _safe_url,
    _sanitize_text,
)


def test_sdk_browser_gate_redacts_application_keys() -> None:
    url = "https://example.test/tour?m=MODEL123&applicationKey=top-secret&pane=3d"

    assert _safe_url(url) == (
        "https://example.test/tour?m=MODEL123&applicationKey=%5Bredacted%5D&pane=3d"
    )
    assert "top-secret" not in _sanitize_text(url)
    assert "applicationKey=[redacted]" in _sanitize_text(url)


def test_sdk_browser_gate_reports_frame_quality() -> None:
    metrics = _frame_metrics([16.0, 17.0, 16.5, 40.0, 0.0, 1200.0, "bad"])

    assert metrics["sample_count"] == 4
    assert metrics["mean_fps"] == 44.69
    assert metrics["p95_frame_interval_ms"] == 40.0
    assert metrics["long_frame_count"] == 1
