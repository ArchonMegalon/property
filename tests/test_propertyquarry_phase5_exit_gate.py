from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_test_modules_exist,
    assert_workflow_checks,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_phase5_exit_gate_is_green() -> None:
    payload = load_gate("propertyquarry_phase5_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=5)
    assert_test_modules_exist(payload["required_test_modules"]["contract"])
    assert_test_modules_exist(payload["required_test_modules"]["browser"])
    assert_workflow_checks(
        payload,
        workflow_name="assign_and_resolve_followup",
        expected_checks=[
            "operator can assign follow-up owner",
            "operator can resolve follow-up",
            "timeline reflects both actions",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Stakeholder timeline", "Property timeline", "More context section"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        ["timeline is just raw event dump and not readable", "follow-up ownership is hidden or missing"],
        field_name="fail_closed_conditions",
    )
    run_pytest_modules(
        [
            "tests/test_propertyquarry_timeline_contracts.py",
            "tests/e2e/test_propertyquarry_timeline_browser.py",
        ]
    )
