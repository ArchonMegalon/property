from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_test_modules_exist,
    assert_workflow_checks,
    load_gate,
    run_pytest_args,
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
    assert_workflow_checks(
        payload,
        workflow_name="request_driven_visual_generation_stays_honest",
        expected_checks=[
            "requesting a 3D tour or walkthrough requires a style choice before queueing",
            "queued visual state stays honest and does not invent readiness",
            "retryable blocked 3D tour state remains actionable after reload",
            "ready 3D tour opens the hosted tour directly with no fake intermediate viewer step",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        [
            "Open floor plan",
            "Play flythrough",
            "Request 3D tour",
            "Request walkthrough",
            "Choose style",
            "Retry 3D tour",
            "Open 3D tour",
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
            "3D tour or walkthrough requests can queue without the required style choice",
            "retryable visual request state disappears after reload",
            "ready hosted tour inserts an extra fake viewer or provider interstitial",
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
    run_pytest_args(
        [
            "tests/e2e/test_propertyquarry_greenfield_browser.py",
            "-k",
            "propertyquarry_3d_tour_request_is_user_initiated_in_real_browser or "
            "propertyquarry_walkthrough_request_is_user_initiated_in_real_browser or "
            "propertyquarry_visual_request_does_not_invent_eta_before_backend_supplies_one or "
            "propertyquarry_blocked_3d_tour_can_be_retried_from_research_packet_in_real_browser or "
            "propertyquarry_ready_tour_rail_stays_on_tour_while_walkthrough_queue_is_open",
        ]
    )
