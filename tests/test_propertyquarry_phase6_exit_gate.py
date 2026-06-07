from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_workflow_checks,
    load_gate,
)


def test_propertyquarry_phase6_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase6_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=6)
    assert "tests/test_propertyquarry_offer_and_optimization_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_commercial_optimization_browser.py" in payload["required_test_modules"]["browser"]
    assert_workflow_checks(
        payload,
        workflow_name="contextual_offer_visibility",
        expected_checks=[
            "user or operator can open workspace",
            "premium next-step offer appears only in valid context",
            "checkout path can be opened",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Premium next step or offer block", "Checkout entry point", "Optimization recommendation block"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "commercial offers are detached from real user intent",
            "optimization appears only as raw metrics with no action",
        ],
        field_name="fail_closed_conditions",
    )
