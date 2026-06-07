from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_workflow_checks,
    load_gate,
)


def test_propertyquarry_phase3_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase3_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=3)
    assert "tests/test_property_summary_artifacts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_summary_artifacts_browser.py" in payload["required_test_modules"]["browser"]
    assert_workflow_checks(
        payload,
        workflow_name="generate_summary_from_workbench",
        expected_checks=[
            "operator can open workbench",
            "operator can trigger summary generation",
            "artifact appears in UI",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Generate explanation", "Generate what changed", "Attached summaries section"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "artifacts generate but are not rendered in product UI",
            "artifacts are API-only and not operator-visible",
        ],
        field_name="fail_closed_conditions",
    )
