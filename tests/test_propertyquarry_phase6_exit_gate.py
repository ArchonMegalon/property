from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_test_modules_exist,
    assert_workflow_checks,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_phase6_exit_gate_is_green() -> None:
    payload = load_gate("propertyquarry_phase6_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=6)
    assert_test_modules_exist(payload["required_test_modules"]["contract"])
    assert_test_modules_exist(payload["required_test_modules"]["browser"])
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
    run_pytest_modules(
        [
            "tests/test_propertyquarry_offer_and_optimization_contracts.py",
            "tests/e2e/test_propertyquarry_commercial_optimization_browser.py",
        ]
    )
