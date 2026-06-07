from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_phase_gate_shape,
    assert_workflow_checks,
    load_gate,
)


def test_propertyquarry_phase4_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase4_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=4)
    assert "tests/test_property_packet_variant_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_packet_publishing_browser.py" in payload["required_test_modules"]["browser"]
    assert_workflow_checks(
        payload,
        workflow_name="create_audience_variant",
        expected_checks=[
            "operator can create family variant",
            "operator can create agent variant",
            "variant entries appear in packet dashboard",
        ],
    )
    assert_contains_strings(
        payload["required_ui_affordances"],
        ["Create family variant", "Create agent variant", "Republish revised packet"],
        field_name="required_ui_affordances",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        ["variants exist internally but not in UI", "republish breaks or loses lineage"],
        field_name="fail_closed_conditions",
    )
