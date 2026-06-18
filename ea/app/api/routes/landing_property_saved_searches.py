from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from app.product.property_surface_state import (
    build_property_recurring_watch_snapshot,
    build_property_search_agent_selection_snapshot,
)


def _positive_int(value: object, *, default: int = 0) -> int:
    try:
        parsed = int(float(value or 0))
    except Exception:
        parsed = 0
    return parsed if parsed > 0 else default


def _safe_agent_load_payload(value: dict[str, object]) -> dict[str, object]:
    blocked_keys = {
        "active_search_agent_id",
        "property_commercial",
        "raw_preferences",
        "saved_shortlist_candidates",
        "search_agents",
        "preferences_json",
    }

    def _safe_value(item: object, *, depth: int = 0) -> object:
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            text = item.strip()
            return text if len(text) <= 2048 else ""
        if isinstance(item, list):
            return [
                safe_item
                for safe_item in (_safe_value(child, depth=depth + 1) for child in item[:100])
                if safe_item not in ("", [], {})
            ]
        if isinstance(item, dict) and depth < 2:
            return {
                str(key): safe_child
                for key, child in item.items()
                if str(key).strip() and str(key).strip() not in blocked_keys and len(str(key).strip()) <= 80
                for safe_child in [_safe_value(child, depth=depth + 1)]
                if safe_child not in ("", [], {})
            }
        return ""

    return {
        str(key): safe_item
        for key, item in dict(value or {}).items()
        if str(key).strip() and str(key).strip() not in blocked_keys and len(str(key).strip()) <= 80
        for safe_item in [_safe_value(item)]
        if safe_item not in ("", [], {})
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
    return build_property_recurring_watch_snapshot(
        raw_agent,
        property_preferences=property_preferences,
        selected_platforms=selected_platforms,
        selected_listing_mode=selected_listing_mode,
        search_mode_requested=search_mode_requested,
        default_duration_days=default_duration_days,
        default_notification_limit=default_notification_limit,
        default_notification_period=default_notification_period,
        normalize_property_type_values=normalize_property_type_values,
        scope_preview_builder=scope_preview_builder,
        safe_agent_load_payload=_safe_agent_load_payload,
    )


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
    return build_property_search_agent_selection_snapshot(
        property_search_agents,
        requested_agent_id=requested_agent_id,
        previous_runs=previous_runs,
        run_id=run_id,
    )
