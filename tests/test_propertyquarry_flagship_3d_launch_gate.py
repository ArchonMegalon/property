from __future__ import annotations

from scripts.propertyquarry_flagship_3d_launch_gate import (
    build_flagship_3d_launch_receipt,
)


def _browser(*, viewport_width: int, median_fps: float = 58.7) -> dict[str, object]:
    return {
        "status": "pass",
        "providers": ["3dvista"],
        "provider_results": [
            {
                "provider": "3dvista",
                "status": "pass",
                "state": {
                    "same_origin_frame_inspected": True,
                    "visible_canvas_count": 2,
                    "loading_indicator_count": 0,
                },
                "ux_state": {
                    "viewport_width": viewport_width,
                    "body_scroll_width": viewport_width,
                    "undersized_controls": [],
                    "reduced_motion": True,
                },
                "recovery_state": {
                    "recovery_controls_ok": True,
                    "retry_ready": True,
                    "rendered_after_retry": True,
                },
                "frame_metrics": {
                    "sample_count": 180,
                    "median_fps": median_fps,
                    "p95_frame_interval_ms": 20.1,
                },
            }
        ],
        "console_errors": [],
        "page_errors": [],
        "failures": [],
    }


def _styles() -> dict[str, object]:
    return {
        "status": "pass",
        "style_count": 5,
        "accepted_count": 5,
        "checks": {
            "all_requested_styles_rendered": True,
            "all_full_decodes_passed": True,
            "all_visual_reviews_passed": True,
            "all_accepted_videos_delivered_to_telegram": True,
        },
    }


def _build(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "desktop_browser": _browser(viewport_width=1440),
        "mobile_browser": _browser(viewport_width=390, median_fps=48.0),
        "style_matrix": _styles(),
        "gold_status": {"status": "pass", "ready_for_notification": True},
        "canary": {"status": "pass", "soak_hours": 48.0, "failed_count": 0, "blockers": []},
    }
    values.update(overrides)
    return build_flagship_3d_launch_receipt(**values)  # type: ignore[arg-type]


def test_flagship_3d_launch_gate_passes_only_complete_3dvista_evidence() -> None:
    receipt = _build()

    assert receipt["contract_name"] == "propertyquarry.flagship_3d_launch_gate.v2"
    assert receipt["status"] == "pass"
    assert receipt["launch_ready"] is True
    assert receipt["active_interactive_provider"] == "3dvista"
    assert receipt["historical_providers_launch_critical"] == []
    assert receipt["failed_count"] == 0
    assert receipt["blockers"] == []


def test_flagship_3d_launch_gate_rejects_matterport_in_active_browser_scope() -> None:
    desktop = _browser(viewport_width=1440)
    desktop["providers"] = ["matterport", "3dvista"]
    desktop["provider_results"] = [
        {"provider": "matterport", "status": "pass"},
        *list(desktop["provider_results"]),
    ]

    receipt = _build(desktop_browser=desktop)

    assert receipt["launch_ready"] is False
    assert "desktop_3dvista_only_scope" in receipt["blockers"]


def test_flagship_3d_launch_gate_rejects_external_or_blank_3dvista_frame() -> None:
    mobile = _browser(viewport_width=390, median_fps=48.0)
    provider = dict(list(mobile["provider_results"])[0])
    provider["state"] = {
        "same_origin_frame_inspected": False,
        "visible_canvas_count": 0,
        "loading_indicator_count": 1,
    }
    mobile["provider_results"] = [provider]

    receipt = _build(mobile_browser=mobile)

    assert receipt["launch_ready"] is False
    assert "mobile_same_origin_canvas_rendered" in receipt["blockers"]


def test_flagship_3d_launch_gate_enforces_desktop_and_mobile_performance() -> None:
    desktop = _browser(viewport_width=1440, median_fps=54.9)
    mobile = _browser(viewport_width=390, median_fps=44.9)

    receipt = _build(desktop_browser=desktop, mobile_browser=mobile)

    assert receipt["launch_ready"] is False
    assert "desktop_median_fps" in receipt["blockers"]
    assert "mobile_median_fps" in receipt["blockers"]


def test_flagship_3d_launch_gate_rejects_missing_canary_and_gold() -> None:
    receipt = _build(
        gold_status={"status": "blocked", "ready_for_notification": False},
        canary={},
    )

    assert receipt["launch_ready"] is False
    assert "gold_status_pass" in receipt["blockers"]
    assert "canary_receipt_pass" in receipt["blockers"]
    assert "canary_duration" in receipt["blockers"]
    assert "canary_blockers_absent" in receipt["blockers"]
