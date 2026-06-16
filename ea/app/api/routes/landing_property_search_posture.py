from __future__ import annotations

from typing import Callable


def build_property_market_summary_items(
    *,
    row_item: Callable[[str, str, str], dict[str, str]],
    property_country_label: str,
    property_language_label: str,
    property_search_goal_label: str,
    property_type_label: str,
    property_listing_mode_label: str,
    property_is_investment_search: bool,
    show_investment_underwriting_controls: bool,
    property_investment_strategy_label: str,
    min_gross_yield_pct: int,
    equity_available_eur: int,
    min_dscr: float,
    property_investment_research_mode_label: str,
    property_available_within_years_value: int,
    property_preferences: dict[str, object],
    custom_keywords: str,
    show_lifestyle_research_controls: bool,
    show_developer_project_stage_controls: bool,
    show_public_housing_policy_controls: bool,
    show_distressed_review_controls: bool,
) -> list[dict[str, str]]:
    items = [
        row_item("Country", property_country_label, "Market"),
        row_item("Browser language", property_language_label, "Research"),
        row_item("Search goal", property_search_goal_label, "Goal"),
        row_item("Property type", property_type_label, "Type"),
    ]
    if not property_is_investment_search:
        items.insert(3, row_item("Search mode", property_listing_mode_label, "Mode"))
    if property_is_investment_search and show_investment_underwriting_controls:
        items.append(row_item("Investment strategy", property_investment_strategy_label, "Thesis"))
        if min_gross_yield_pct > 0:
            items.append(row_item("Minimum gross yield", f"{min_gross_yield_pct}%", "Return"))
        if equity_available_eur > 0:
            items.append(row_item("Equity available", f"EUR {equity_available_eur:,.0f}".replace(",", " "), "Financing"))
        if min_dscr > 0:
            items.append(row_item("Minimum DSCR", f"{min_dscr:.2f}x", "Financing"))
    if property_is_investment_search:
        items.append(row_item("Investment research", property_investment_research_mode_label, "Underwriting"))
    if property_available_within_years_value > 0:
        items.append(
            row_item(
                "Move-in deadline",
                "Within 1 year" if property_available_within_years_value == 1 else f"Within {property_available_within_years_value} years",
                "Timing",
            )
        )
    if str(property_preferences.get("location_query") or "").strip():
        items.append(row_item("Location query", str(property_preferences.get("location_query") or "").strip(), "Target"))
    if str(property_preferences.get("keywords") or "").strip():
        items.append(row_item("Research focus", str(property_preferences.get("keywords") or "").strip(), "Focus"))
    if custom_keywords:
        items.append(row_item("Custom priorities", custom_keywords, "Custom"))
    if bool(property_preferences.get("enable_commute_research")) and str(property_preferences.get("commute_destination") or "").strip():
        items.append(row_item("Commute destination", str(property_preferences.get("commute_destination") or "").strip(), "Route"))
    if bool(property_preferences.get("enable_commute_research")) and str(property_preferences.get("additional_reachability_targets") or "").strip():
        items.append(row_item("Additional destinations", str(property_preferences.get("additional_reachability_targets") or "").strip(), "Route"))
    if show_lifestyle_research_controls and str(property_preferences.get("university_name") or "").strip():
        items.append(row_item("University focus", str(property_preferences.get("university_name") or "").strip(), "Research"))

    school_stage_preferences = [
        str(item or "").strip().replace("_", " ")
        for item in list(property_preferences.get("school_stage_preferences") or [])
        if str(item or "").strip()
    ]
    school_evidence_controls_enabled = bool(school_stage_preferences) or bool(property_preferences.get("require_school_evidence"))
    if not property_is_investment_search and school_stage_preferences:
        items.append(row_item("Children", ", ".join(school_stage_preferences), "Family"))
    if not property_is_investment_search and bool(property_preferences.get("ganztag_required")):
        items.append(row_item("All-day school", "Required", "Family"))
    if not property_is_investment_search and bool(property_preferences.get("require_school_evidence")):
        items.append(row_item("School evidence", "Required", "Evidence"))
    if not property_is_investment_search and school_evidence_controls_enabled and str(property_preferences.get("school_quality_priority") or "any") not in {"", "any"}:
        items.append(
            row_item(
                "School evidence priority",
                str(property_preferences.get("school_quality_priority") or "any").replace("_", " ").title(),
                "Evidence",
            )
        )

    desired_project_stages = [
        str(item or "").strip().replace("_", " ")
        for item in list(property_preferences.get("desired_project_stages") or [])
        if str(item or "").strip()
    ]
    if show_developer_project_stage_controls and desired_project_stages:
        items.append(row_item("Accepted project stages", ", ".join(desired_project_stages), "Pipeline"))
    if bool(property_preferences.get("prefer_good_air_quality")):
        items.append(row_item("Air quality", "Prefer stronger station-backed air quality", "Risk"))
    if bool(property_preferences.get("avoid_noise_risk_area")):
        items.append(row_item("Noise posture", "Avoid noise-risk areas", "Risk"))
    if bool(property_preferences.get("require_high_speed_internet")):
        items.append(row_item("Home office", "High-speed internet required", "Infrastructure"))
    if bool(property_preferences.get("require_energy_certificate")):
        items.append(row_item("Energy certificate", "Required", "Documents"))
    if bool(property_preferences.get("require_operating_cost_statement")):
        items.append(row_item("Operating costs", "Statement required", "Documents"))
    if show_public_housing_policy_controls and bool(property_preferences.get("wiener_wohnticket_available")):
        items.append(row_item("Wiener Wohn-Ticket", "Available", "Eligibility"))
    if show_public_housing_policy_controls and bool(property_preferences.get("subsidized_required")):
        items.append(row_item("Subsidized supply", "Required", "Eligibility"))
    if show_public_housing_policy_controls and bool(property_preferences.get("miete_mit_kaufoption")):
        items.append(row_item("Miete mit Kaufoption", "Accepted", "Eligibility"))
    if show_public_housing_policy_controls and int(property_preferences.get("eigenmittel_max_eur") or 0) > 0:
        items.append(
            row_item(
                "Eigenmittel ceiling",
                f"EUR {int(property_preferences.get('eigenmittel_max_eur') or 0):,}".replace(",", ","),
                "Eligibility",
            )
        )
    if show_public_housing_policy_controls and int(property_preferences.get("application_window_days") or 0) > 0:
        items.append(
            row_item(
                "Application window",
                f"Within {int(property_preferences.get('application_window_days') or 0)} days",
                "Eligibility",
            )
        )
    if show_distressed_review_controls and bool(property_preferences.get("enable_auction_legal_review")):
        items.append(row_item("Auction legal review", "Required when auction evidence appears", "Legal"))
    return items
