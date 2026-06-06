from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import assert_phase_gate_shape, load_gate


def test_propertyquarry_phase1_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase1_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=1)
    assert "tests/test_property_packet_engagement_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_packet_engagement_browser.py" in payload["required_test_modules"]["browser"]
