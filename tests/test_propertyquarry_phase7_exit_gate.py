from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_test_modules_exist,
    assert_workflow_checks,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_phase7_exit_gate_is_green() -> None:
    payload = load_gate("propertyquarry_phase7_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=7)
    assert_test_modules_exist(payload["required_test_modules"]["contract"])
    assert_test_modules_exist(payload["required_test_modules"]["browser"])
    assert_workflow_checks(
        payload,
        workflow_name="hosted_tour_opens_white_labeled",
        expected_checks=[
            "user can open hosted tour page",
            "panorama or explicit white-label fallback is visible",
            "floorplan lane opens from the same hosted surface",
        ],
    )
    assert_workflow_checks(
        payload,
        workflow_name="flythrough_decodes_without_black_frame",
        expected_checks=[
            "flythrough pane opens in a real browser",
            "video currentTime advances after play",
            "decoded frame is not visually black",
            "mobile viewport also decodes a visible frame",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        [
            "Open floor plan",
            "Play flythrough",
            "Familienroute und schulische Selbstständigkeit section",
            "Sicherheit, Kriminalität und Klimarisiko section",
            "Gebietsausblick und künftige Infrastruktur section",
        ],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "hosted tour opens to a broken or non-white-label surface",
            "flythrough renders as audio-only or black video",
            "dossier remains a thin fact sheet with no neighbourhood or risk context",
        ],
        field_name="fail_closed_conditions",
    )
    run_pytest_modules(
        [
            "tests/test_fliplink_packet_privacy.py",
            "tests/e2e/test_propertyquarry_public_tour_browser.py",
        ]
    )
