from __future__ import annotations

import urllib.parse
from typing import Any, Callable


def _positive_int(value: object, *, default: int = 0) -> int:
    try:
        parsed = int(float(value or 0))
    except Exception:
        parsed = 0
    return parsed if parsed > 0 else default


def _safe_agent_load_payload(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in dict(value or {}).items()
        if key not in {"search_agents", "active_search_agent_id", "raw_preferences", "property_commercial"}
    }


def format_property_search_agent(
    raw_agent: dict[str, object],
    *,
    property_preferences: dict[str, object],
    selected_platforms: list[str],
    selected_listing_mode: str,
    search_mode_requested: str,
    default_duration_days: int,
    default_notification_limit: int,
    default_notification_period: str,
    normalize_property_type_values: Callable[[object], list[str]],
    scope_preview_builder: Callable[[str, str, str], dict[str, object]],
) -> dict[str, object]:
    saved_preferences = (
        dict(raw_agent.get("preferences_json") or {})
        if isinstance(raw_agent.get("preferences_json"), dict)
        else {}
    )
    agent_duration_days = _positive_int(raw_agent.get("duration_days"), default=default_duration_days)
    agent_duration_days = max(7, min(365, agent_duration_days or default_duration_days))
    agent_notification_limit = _positive_int(raw_agent.get("notification_limit"), default=default_notification_limit)
    agent_notification_limit = max(1, min(50, agent_notification_limit or default_notification_limit))
    agent_notification_period = str(raw_agent.get("notification_period") or default_notification_period).strip().lower()
    if agent_notification_period not in {"day", "week"}:
        agent_notification_period = default_notification_period
    agent_selected_platforms = (
        saved_preferences.get("selected_platforms")
        if isinstance(saved_preferences.get("selected_platforms"), list)
        else (raw_agent.get("selected_platforms") if isinstance(raw_agent.get("selected_platforms"), list) else selected_platforms)
    )
    agent_enabled = bool(raw_agent.get("enabled"))
    agent_listing_mode = str(saved_preferences.get("listing_mode") or raw_agent.get("listing_mode") or selected_listing_mode).strip().lower() or selected_listing_mode
    agent_country_code = str(saved_preferences.get("country_code") or raw_agent.get("country_code") or property_preferences.get("country_code") or "AT").strip().upper()
    agent_location_query = str(saved_preferences.get("location_query") or raw_agent.get("location_query") or property_preferences.get("location_query") or "").strip()
    agent_property_types = normalize_property_type_values(saved_preferences.get("property_type") or raw_agent.get("property_type") or property_preferences.get("property_type"))
    agent_region_code = str(saved_preferences.get("region_code") or raw_agent.get("region_code") or property_preferences.get("region_code") or "").strip().lower()
    agent_name = str(raw_agent.get("name") or "").strip()
    if not agent_name:
        agent_name = f"{agent_listing_mode.title()} search · {agent_location_query or agent_country_code}"
    last_run_at = str(raw_agent.get("last_run_at") or "").strip()
    next_run_at = str(raw_agent.get("next_run_at") or "").strip()
    sent_in_current_window = _positive_int(raw_agent.get("sent_in_current_window"), default=0)
    remaining_notifications = max(agent_notification_limit - sent_in_current_window, 0)
    area_label = agent_location_query or agent_country_code or "No area saved"
    notification_label = f"{agent_notification_limit} per {('week' if agent_notification_period == 'week' else 'day')}"
    scope_preview = scope_preview_builder(
        agent_country_code,
        agent_region_code,
        agent_location_query,
    )
    return {
        "agent_id": str(raw_agent.get("agent_id") or "current").strip() or "current",
        "name": agent_name,
        "enabled": agent_enabled,
        "is_active": bool(raw_agent.get("is_active")),
        "status_label": "Active" if agent_enabled else "Paused",
        "duration_days": agent_duration_days,
        "duration_label": (
            "1 week"
            if agent_duration_days == 7
            else "1 year"
            if agent_duration_days == 365
            else f"{agent_duration_days} days"
        ),
        "notification_limit": agent_notification_limit,
        "notification_period": agent_notification_period,
        "notification_period_label": "week" if agent_notification_period == "week" else "day",
        "location_query": agent_location_query,
        "listing_mode": agent_listing_mode,
        "country_code": agent_country_code,
        "region_code": agent_region_code,
        "property_type": ", ".join(agent_property_types),
        "provider_count": len(agent_selected_platforms),
        "last_run_label": last_run_at or "not run yet",
        "next_run_label": next_run_at or ("waiting for scheduler" if agent_enabled else "paused"),
        "sent_in_current_window": sent_in_current_window,
        "remaining_notifications": remaining_notifications,
        "area_label": area_label,
        "scope_label": f"{agent_listing_mode.title()} · {area_label} · {agent_country_code}",
        "scope_preview": scope_preview,
        "notification_label": notification_label,
        "run_label": f"Last: {last_run_at or 'not run yet'} · Next: {next_run_at or ('waiting for scheduler' if agent_enabled else 'paused')}",
        "delivery_label": f"Sent {sent_in_current_window}/{agent_notification_limit} this {('week' if agent_notification_period == 'week' else 'day')}",
        "load_payload": (
            _safe_agent_load_payload(saved_preferences)
            if saved_preferences
            else {
                "country_code": agent_country_code,
                "region_code": agent_region_code,
                "location_query": agent_location_query,
                "listing_mode": agent_listing_mode,
                "property_type": agent_property_types,
                "search_mode": str(raw_agent.get("search_mode") or search_mode_requested or "strict").strip().lower() or "strict",
                "selected_platforms": list(agent_selected_platforms or []),
                "search_agent_enabled": agent_enabled,
                "search_agent_duration_days": agent_duration_days,
                "search_agent_notification_limit": agent_notification_limit,
                "search_agent_notification_period": agent_notification_period,
            }
        ),
    }


def build_property_search_agents(
    property_preferences: dict[str, object],
    *,
    selected_platforms: list[str],
    selected_listing_mode: str,
    search_mode_requested: str,
    default_duration_days: int,
    default_notification_limit: int,
    default_notification_period: str,
    normalize_property_type_values: Callable[[object], list[str]],
    scope_preview_builder: Callable[[str, str, str], dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    explicit_agent_list = isinstance(property_preferences.get("search_agents"), list)
    raw_property_search_agents = property_preferences.get("search_agents") if explicit_agent_list else []
    property_search_agents = [
        format_property_search_agent(
            agent,
            property_preferences=property_preferences,
            selected_platforms=selected_platforms,
            selected_listing_mode=selected_listing_mode,
            search_mode_requested=search_mode_requested,
            default_duration_days=default_duration_days,
            default_notification_limit=default_notification_limit,
            default_notification_period=default_notification_period,
            normalize_property_type_values=normalize_property_type_values,
            scope_preview_builder=scope_preview_builder,
        )
        for agent in raw_property_search_agents
        if isinstance(agent, dict)
    ]
    if not property_search_agents and not explicit_agent_list:
        property_search_agents = [
            format_property_search_agent(
                {
                    "agent_id": str(property_preferences.get("active_search_agent_id") or "current").strip() or "current",
                    "enabled": bool(property_preferences.get("search_agent_enabled")),
                    "duration_days": default_duration_days,
                    "notification_limit": default_notification_limit,
                    "notification_period": default_notification_period,
                    "location_query": str(property_preferences.get("location_query") or "").strip(),
                    "listing_mode": selected_listing_mode,
                    "country_code": str(property_preferences.get("country_code") or "AT").strip().upper(),
                    "selected_platforms": selected_platforms,
                    "is_active": True,
                },
                property_preferences=property_preferences,
                selected_platforms=selected_platforms,
                selected_listing_mode=selected_listing_mode,
                search_mode_requested=search_mode_requested,
                default_duration_days=default_duration_days,
                default_notification_limit=default_notification_limit,
                default_notification_period=default_notification_period,
                normalize_property_type_values=normalize_property_type_values,
                scope_preview_builder=scope_preview_builder,
            )
        ]
    active_agent = next(
        (agent for agent in property_search_agents if agent.get("is_active")),
        property_search_agents[0] if property_search_agents else {},
    )
    return property_search_agents, active_agent


def build_agent_management_rows(
    property_search_agents: list[dict[str, object]],
    *,
    run_id: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for agent in property_search_agents:
        if not isinstance(agent, dict):
            continue
        agent_id = urllib.parse.quote(str(agent.get("agent_id") or "current").strip() or "current", safe="")
        edit_href = f"/app/properties?load_agent={agent_id}"
        open_href = f"/app/agents?agent_id={agent_id}"
        if run_id:
            suffix = urllib.parse.quote(run_id, safe="")
            edit_href = f"{edit_href}&run_id={suffix}"
            open_href = f"{open_href}&run_id={suffix}"
        label = str(agent.get("name") or agent.get("area_label") or "Saved search").strip() or "Saved search"
        detail_parts = [
            str(agent.get("scope_label") or "").strip(),
            str(agent.get("notification_label") or "").strip(),
            str(agent.get("run_label") or "").strip(),
        ]
        rows.append(
            {
                "title": label,
                "detail": " | ".join(part for part in detail_parts if part) or "Saved search settings can be edited from the search desk.",
                "tag": "Active" if bool(agent.get("enabled")) else "Paused",
                "action_href": open_href,
                "action_method": "get",
                "action_label": "Open",
                "secondary_action_href": edit_href,
                "secondary_action_method": "get",
                "secondary_action_label": "Edit",
            }
        )
    return rows


def select_property_search_agent(
    property_search_agents: list[dict[str, object]],
    *,
    requested_agent_id: str,
    previous_runs: list[dict[str, object]],
    run_id: str,
) -> dict[str, Any]:
    selected_agent = next((agent for agent in property_search_agents if str(agent.get("agent_id") or "").strip() == requested_agent_id), None)
    if selected_agent is None:
        selected_agent = next((agent for agent in property_search_agents if agent.get("is_active")), property_search_agents[0] if property_search_agents else None)
    selected_agent_id = str((selected_agent or {}).get("agent_id") or "").strip()
    selected_agent_runs = [
        row
        for row in previous_runs
        if isinstance(row, dict)
        and (
            (selected_agent_id and str(row.get("agent_id") or "").strip() == selected_agent_id)
            or (
                selected_agent
                and not str(row.get("agent_id") or "").strip()
                and str(row.get("title") or "").strip() == str(selected_agent.get("location_query") or "").strip()
            )
        )
    ]
    latest_run = selected_agent_runs[0] if selected_agent_runs else {}
    open_href = ""
    edit_href = ""
    if selected_agent_id:
        open_href = f"/app/agents?agent_id={urllib.parse.quote(selected_agent_id, safe='')}"
        edit_href = f"/app/properties?load_agent={urllib.parse.quote(selected_agent_id, safe='')}"
        if run_id:
            suffix = urllib.parse.quote(run_id, safe="")
            open_href = f"{open_href}&run_id={suffix}"
            edit_href = f"{edit_href}&run_id={suffix}"
    return {
        "selected_agent": selected_agent,
        "selected_agent_id": selected_agent_id,
        "selected_agent_runs": selected_agent_runs,
        "selected_agent_latest_run": latest_run,
        "selected_agent_open_href": open_href,
        "selected_agent_edit_href": edit_href,
    }
