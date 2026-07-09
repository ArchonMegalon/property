from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_master_gate_shape,
    assert_test_modules_exist,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_master_regression_gate_is_green() -> None:
    payload = load_gate("propertyquarry_master_regression_gate.yaml")
    assert_master_gate_shape(payload)
    browser_modules = assert_test_modules_exist(payload["required_test_modules"])
    assert_contains_strings(
        payload["required_browser_workflows"],
        [
            "mobile_flagship_search_to_walkthrough_flow",
            "mobile_flagship_walkthrough_decodes_nonblack_frame",
            "shortlist_page_loads",
            "packet_dashboard_loads",
            "settings_and_billing_surfaces_load",
        ],
        field_name="required_browser_workflows",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "any core product route fails to render",
            "any prior-phase primary affordance disappears",
            "browser proof comes from stale image-baked runtime containers whose /version release manifest does not match the candidate commit",
        ],
        field_name="fail_closed_conditions",
    )
    assert_contains_strings(
        payload["exit_criteria"],
        [
            "browser regression suite passes after every phase",
            "runtime/browser proof comes from rebuilt or restarted containers whose /version release manifest matches the candidate commit",
        ],
        field_name="exit_criteria",
    )
    run_pytest_modules(browser_modules)
