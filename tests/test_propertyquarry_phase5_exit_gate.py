from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_workflow_checks,
    load_gate,
)


def test_propertyquarry_phase5_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase5_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=5)
    assert "tests/test_propertyquarry_timeline_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_timeline_browser.py" in payload["required_test_modules"]["browser"]
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
        ["Stakeholder timeline", "Property timeline", "Open loops section"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        ["timeline is just raw event dump and not readable", "follow-up ownership is hidden or missing"],
        field_name="fail_closed_conditions",
    )
