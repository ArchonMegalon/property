from __future__ import annotations

from tests.propertyquarry_exit_gate_helpers import (
    assert_contains_strings,
    assert_master_gate_shape,
    assert_test_modules_exist,
    load_gate,
    run_pytest_modules,
)


def test_propertyquarry_tester_gold_gate_is_green() -> None:
    payload = load_gate("propertyquarry_tester_gold_gate.yaml")
    assert_master_gate_shape(payload)
    modules = assert_test_modules_exist(payload["required_test_modules"])
    assert_contains_strings(
        payload["required_browser_workflows"],
        [
            "greenfield_setup_and_search_workbench",
            "packet_share_and_feedback_loop",
            "timeline_and_followup_visibility",
            "hosted_tour_and_flythrough_review",
            "premium_dossier_context_and_comparison",
            "notification_preview_and_action_surface",
            "optimization_and_offer_surface",
        ],
        field_name="required_browser_workflows",
    )
    assert_contains_strings(
        payload["fail_closed_conditions"],
        [
            "any core office loop route fails in a real browser",
            "any packet or dossier lane regresses to a thin fact export",
            "hosted tour or flythrough breaks while packet and research still appear healthy",
            "sharing, feedback, or timeline state is not persisted across reload",
        ],
        field_name="fail_closed_conditions",
    )
    run_pytest_modules(modules)
