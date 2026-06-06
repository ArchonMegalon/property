from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import assert_phase_gate_shape, load_gate


def test_propertyquarry_phase6_exit_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_phase6_exit_gate.yaml")
    assert_phase_gate_shape(payload, phase=6)
    assert "tests/test_propertyquarry_offer_and_optimization_contracts.py" in payload["required_test_modules"]["contract"]
    assert "tests/e2e/test_propertyquarry_commercial_optimization_browser.py" in payload["required_test_modules"]["browser"]
