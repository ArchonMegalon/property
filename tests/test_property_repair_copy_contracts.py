from pathlib import Path


def test_property_surface_state_repair_copy_mentions_provider_page_changes() -> None:
    body = Path("/docker/property/ea/app/product/property_surface_state.py").read_text(encoding="utf-8")
    assert "def _resolved_customer_repair_reason(" in body
    assert "This source changed and the current check could not confirm the listing reliably." in body
    assert "_resolved_customer_repair_reason(run_summary, message_value=run_message)" in body
    assert "def _calm_customer_repair_copy(" in body
    assert 'return "One source changed, so PropertyQuarry is retrying it."' in body


def test_property_workbench_script_uses_repair_reason_for_failed_run_copy() -> None:
    body = Path("/docker/property/ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")
    assert "const repairCustomerReason = (summary, rawMessage = '') => {" in body
    assert "return 'This source changed and the current check could not confirm the listing reliably.';" in body
    assert "const calmRepairCustomerCopy = (summary, rawMessage = '') => {" in body
    assert "return customerStatus || calmRepairCopy || 'A replacement search run is checking the saved brief.';" in body
    assert "if (customerStatus || calmRepairCopy || repairReason) {" in body


def test_alerts_and_delivery_copy_stay_customer_facing() -> None:
    payload_body = Path("/docker/property/ea/app/api/routes/landing_property_workspace_payload.py").read_text(encoding="utf-8")
    governance_body = Path("/docker/property/ea/app/product/property_delivery_governance.py").read_text(encoding="utf-8")
    view_model_body = Path("/docker/property/ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    surface_state_body = Path("/docker/property/ea/app/product/property_surface_state.py").read_text(encoding="utf-8")

    assert "No list follow-up is active right now." in payload_body
    assert "Pick only the channels you actually want to hear from." in payload_body
    assert 'return "Search update"' in payload_body
    assert "address confirmed" in governance_body
    assert "verified destination" not in governance_body
    assert "Connect Google sign-in if you want a faster return path and account access without another sign-up." in view_model_body
    assert "Community-sourced hits should stay separate until a human confirms identity, freshness, and legitimacy." in view_model_body
    assert "def _property_run_progress_fallback_message(" in surface_state_body
    assert 'return "Preparing providers."' in surface_state_body
    assert "Preparing provider checks." not in surface_state_body


def test_property_search_service_drops_removed_match_bar_copy_at_source() -> None:
    body = Path("/docker/property/ea/app/product/service.py").read_text(encoding="utf-8")
    assert "Lower-ranked for this source; kept visible in the full ranking." in body
    assert "match bar" not in body
