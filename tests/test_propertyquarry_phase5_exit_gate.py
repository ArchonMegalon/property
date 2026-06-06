from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import assert_phase_gate_shape, load_gate


def test_propertyquarry_phase5_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase5_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=5)
    assert "tests/test_propertyquarry_timeline_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_timeline_browser.py" in payload["required_test_modules"]["browser"]
