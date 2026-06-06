from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import assert_master_gate_shape, load_gate


def test_propertyquarry_master_regression_gate_spec_is_complete() -> None:
    payload = load_gate("propertyquarry_master_regression_gate.yaml")
    assert_master_gate_shape(payload)
    assert "tests/e2e/test_propertyquarry_phase_regression_browser.py" in payload["required_test_modules"]
