from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_workflow_checks,
    load_gate,
)


def test_propertyquarry_phase1_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase1_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=1)
    assert "tests/test_property_packet_engagement_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_packet_engagement_browser.py" in payload["required_test_modules"]["browser"]
    assert_workflow_checks(
        payload,
        workflow_name="share_packet_from_packet_dashboard",
        expected_checks=[
            "operator can open packet dashboard",
            "operator can create share with at least one named recipient",
            "recipient row becomes visible after submit",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Share packet", "Next best action", "Track follow-up entry point from workspace"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "packets can be shared but engagement is not visible in UI",
            "engagement can be logged but does not change next_best_action",
        ],
        field_name="fail_closed_conditions",
    )
