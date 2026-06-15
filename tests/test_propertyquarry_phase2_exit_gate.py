from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_test_modules_exist,
    assert_workflow_checks,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_phase2_exit_gate_is_green() -> None:
    payload = load_gate("propertyquarry_phase2_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=2)
    assert_test_modules_exist(payload["required_test_modules"]["contract"])
    assert_test_modules_exist(payload["required_test_modules"]["browser"])
    assert_workflow_checks(
        payload,
        workflow_name="record_structured_feedback_from_packet_context",
        expected_checks=[
            "operator can open packet feedback surface",
            "operator can submit categorized feedback",
            "feedback row becomes visible immediately",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Feedback table", "Dealbreaker visual state", "Before you decide section"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "structured feedback exists only in API but not in UI",
            "dealbreakers do not affect visible decision context",
        ],
        field_name="fail_closed_conditions",
    )
    run_pytest_modules(
        [
            "tests/test_property_feedback_spine_contracts.py",
            "tests/e2e/test_propertyquarry_feedback_browser.py",
        ]
    )
