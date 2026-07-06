from __future__ import annotations

import json

from app.api.routes import landing as landing_routes


def _run_without_distance_preferences() -> dict[str, object]:
    return {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1010 Vienna, 1020 Vienna",
        "selected_location_values": ["1010 Vienna", "1020 Vienna"],
        "active_search_agent_id": "agent-active",
        "keywords": "",
        "keyword_preferences": {},
        "keyword_preferences_json": "{}",
    }


def _candidate_with_location_scope() -> dict[str, object]:
    return {
        "location_label": "",
        "property_facts": {
            "postal_name": "1010 Wien",
            "address": "1010 Wien",
            "source_scope_location": "1010 Vienna",
        },
    }


def test_property_research_search_agent_distance_overlay_prefers_newer_matching_agent_when_scope_ties() -> None:
    preferences = {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1020 Vienna",
        "active_search_agent_id": "agent-active",
        "search_agents": [
            {
                "agent_id": "agent-active",
                "enabled": False,
                "is_active": True,
                "location_query": "1020 Vienna",
                "selected_location_values": ["1020 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1020 Vienna",
                    "selected_location_values": ["1020 Vienna"],
                    "keyword_preferences_json": "{}",
                },
            },
            {
                "agent_id": "agent-stale",
                "enabled": False,
                "is_active": False,
                "last_run_at": "2026-06-28T10:00:00+00:00",
                "location_query": "1010 Vienna, 1020 Vienna",
                "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1010 Vienna, 1020 Vienna",
                    "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                    "keyword_preferences_json": json.dumps(
                        {
                            "supermarket nearby": "nice_to_have",
                            "pharmacy nearby": "nice_to_have",
                        }
                    ),
                    "max_distance_to_supermarket_m": 900,
                    "max_distance_to_medical_care_m": 1000,
                },
            },
            {
                "agent_id": "agent-recent",
                "enabled": False,
                "is_active": False,
                "last_run_at": "2026-07-06T10:00:00+00:00",
                "location_query": "1010 Vienna, 1020 Vienna",
                "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1010 Vienna, 1020 Vienna",
                    "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                    "keyword_preferences_json": json.dumps(
                        {
                            "supermarket nearby": "important",
                            "pharmacy nearby": "important",
                        }
                    ),
                    "max_distance_to_supermarket_m": 500,
                    "max_distance_to_medical_care_m": 450,
                },
            },
        ],
    }

    overlay = landing_routes._property_research_search_agent_distance_overlay(
        preferences=preferences,
        run_preferences=_run_without_distance_preferences(),
        candidate=_candidate_with_location_scope(),
    )

    assert overlay["max_distance_to_supermarket_m"] == 500
    assert overlay["max_distance_to_medical_care_m"] == 450
    assert json.loads(str(overlay["keyword_preferences_json"]))["pharmacy nearby"] == "important"


def test_property_research_search_agent_distance_overlay_prefers_narrower_matching_scope_when_scores_tie() -> None:
    preferences = {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1020 Vienna",
        "active_search_agent_id": "agent-active",
        "search_agents": [
            {
                "agent_id": "agent-active",
                "enabled": False,
                "is_active": True,
                "location_query": "1020 Vienna",
                "selected_location_values": ["1020 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1020 Vienna",
                    "selected_location_values": ["1020 Vienna"],
                },
            },
            {
                "agent_id": "agent-broad",
                "enabled": False,
                "is_active": False,
                "location_query": "1010 Vienna, 1020 Vienna, 1090 Vienna",
                "selected_location_values": ["1010 Vienna", "1020 Vienna", "1090 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1010 Vienna, 1020 Vienna, 1090 Vienna",
                    "selected_location_values": ["1010 Vienna", "1020 Vienna", "1090 Vienna"],
                    "keyword_preferences_json": json.dumps({"supermarket nearby": "nice_to_have"}),
                    "max_distance_to_supermarket_m": 900,
                    "max_distance_to_playground_m": 1000,
                },
            },
            {
                "agent_id": "agent-narrow",
                "enabled": False,
                "is_active": False,
                "location_query": "1010 Vienna, 1020 Vienna",
                "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                "preferences_json": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "location_query": "1010 Vienna, 1020 Vienna",
                    "selected_location_values": ["1010 Vienna", "1020 Vienna"],
                    "keyword_preferences_json": json.dumps({"supermarket nearby": "important"}),
                    "max_distance_to_supermarket_m": 500,
                    "max_distance_to_playground_m": 600,
                },
            },
        ],
    }

    overlay = landing_routes._property_research_search_agent_distance_overlay(
        preferences=preferences,
        run_preferences=_run_without_distance_preferences(),
        candidate=_candidate_with_location_scope(),
    )

    assert overlay["max_distance_to_supermarket_m"] == 500
    assert overlay["max_distance_to_playground_m"] == 600
    assert json.loads(str(overlay["keyword_preferences_json"]))["supermarket nearby"] == "important"
