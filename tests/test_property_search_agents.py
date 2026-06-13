from __future__ import annotations

from tests.product_test_helpers import build_property_client, start_workspace


def test_property_search_agents_can_be_managed_independently() -> None:
    client = build_property_client(principal_id="exec-property-search-agents")
    start_workspace(client, mode="personal", workspace_name="Property office")

    created = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "wien",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "immobilienscout24_at"],
            "search_agent_enabled": True,
            "search_agent_duration_days": 90,
            "search_agent_notification_limit": 3,
            "search_agent_notification_period": "day",
        },
    )
    assert created.status_code == 200, created.text
    preferences = created.json()["property_search_preferences"]
    agents = preferences["search_agents"]
    assert len(agents) == 1
    agent_id = agents[0]["agent_id"]
    assert agents[0]["enabled"] is True
    assert agents[0]["notification_limit"] == 3

    duplicated = client.post(
        f"/v1/onboarding/property-search/agents/{agent_id}",
        json={"action": "duplicate"},
    )
    assert duplicated.status_code == 200, duplicated.text
    agents = duplicated.json()["property_search_preferences"]["search_agents"]
    assert len(agents) == 2
    duplicate_id = next(agent["agent_id"] for agent in agents if agent["agent_id"] != agent_id)
    duplicate = next(agent for agent in agents if agent["agent_id"] == duplicate_id)
    assert duplicate["enabled"] is False

    saved = client.post(
        f"/v1/onboarding/property-search/agents/{duplicate_id}",
        json={
            "action": "save",
            "patch": {
                "name": "Vienna weekly shortlist",
                "notification_limit": 9,
                "notification_period": "week",
                "duration_days": 365,
                "last_run_at": "2026-06-12T08:00:00+02:00",
                "next_run_at": "2026-06-13T08:00:00+02:00",
                "sent_in_current_window": 4,
            },
        },
    )
    assert saved.status_code == 200, saved.text
    duplicate = next(
        agent
        for agent in saved.json()["property_search_preferences"]["search_agents"]
        if agent["agent_id"] == duplicate_id
    )
    assert duplicate["name"] == "Vienna weekly shortlist"
    assert duplicate["notification_limit"] == 9
    assert duplicate["notification_period"] == "week"
    assert duplicate["duration_days"] == 365
    assert duplicate["last_run_at"] == "2026-06-12T08:00:00+02:00"
    assert duplicate["next_run_at"] == "2026-06-13T08:00:00+02:00"
    assert duplicate["sent_in_current_window"] == 4

    paused = client.post(
        f"/v1/onboarding/property-search/agents/{agent_id}",
        json={"action": "pause"},
    )
    assert paused.status_code == 200, paused.text
    original = next(
        agent
        for agent in paused.json()["property_search_preferences"]["search_agents"]
        if agent["agent_id"] == agent_id
    )
    assert original["enabled"] is False

    resumed = client.post(
        f"/v1/onboarding/property-search/agents/{duplicate_id}",
        json={"action": "resume"},
    )
    assert resumed.status_code == 200, resumed.text
    preferences = resumed.json()["property_search_preferences"]
    assert preferences["active_search_agent_id"] == duplicate_id
    resumed_agent = next(agent for agent in preferences["search_agents"] if agent["agent_id"] == duplicate_id)
    assert resumed_agent["enabled"] is True

    deleted = client.post(
        f"/v1/onboarding/property-search/agents/{agent_id}",
        json={"action": "delete"},
    )
    assert deleted.status_code == 200, deleted.text
    agents = deleted.json()["property_search_preferences"]["search_agents"]
    assert [agent["agent_id"] for agent in agents] == [duplicate_id]


def test_property_search_agent_loads_saved_filters_into_current_preferences() -> None:
    client = build_property_client(principal_id="exec-property-search-agent-load")
    start_workspace(client, mode="personal", workspace_name="Property office")

    created = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "1020 Wien",
            "selected_platforms": ["willhaben"],
            "min_area_m2": 70,
            "max_price_eur": 650000,
            "search_agent_enabled": True,
            "search_agent_duration_days": 90,
            "search_agent_notification_limit": 3,
            "search_agent_notification_period": "day",
        },
    )
    assert created.status_code == 200, created.text
    first_agent_id = created.json()["property_search_preferences"]["search_agents"][0]["agent_id"]
    duplicated = client.post(f"/v1/onboarding/property-search/agents/{first_agent_id}", json={"action": "duplicate"})
    assert duplicated.status_code == 200, duplicated.text
    second_agent_id = next(
        agent["agent_id"]
        for agent in duplicated.json()["property_search_preferences"]["search_agents"]
        if agent["agent_id"] != first_agent_id
    )

    saved = client.post(
        f"/v1/onboarding/property-search/agents/{second_agent_id}",
        json={
            "action": "save",
            "patch": {
                "name": "Costa Rica land search",
                "country_code": "CR",
                "region_code": "puntarenas",
                "location_query": "Monteverde",
                "listing_mode": "buy",
                "property_type": "land",
                "selected_platforms": ["re_cr_mls"],
                "duration_days": 365,
                "notification_limit": 6,
                "notification_period": "week",
                "preferences_json": {
                    "country_code": "CR",
                    "region_code": "puntarenas",
                    "location_query": "Monteverde",
                    "listing_mode": "buy",
                    "property_type": "land",
                    "selected_platforms": ["re_cr_mls"],
                    "min_area_m2": 1200,
                    "max_price_eur": 350000,
                    "keywords": "seezugang, jungle",
                    "search_agent_enabled": False,
                    "search_agent_duration_days": 365,
                    "search_agent_notification_limit": 6,
                    "search_agent_notification_period": "week",
                },
            },
        },
    )
    assert saved.status_code == 200, saved.text

    loaded = client.post(f"/v1/onboarding/property-search/agents/{second_agent_id}", json={"action": "load"})
    assert loaded.status_code == 200, loaded.text
    preferences = loaded.json()["property_search_preferences"]
    assert preferences["active_search_agent_id"] == second_agent_id
    assert preferences["country_code"] == "CR"
    assert preferences["region_code"] == "puntarenas"
    assert preferences["location_query"] == "Monteverde"
    assert preferences["property_type"] == "land"
    assert preferences["selected_platforms"] == ["re_cr_mls"]
    assert preferences["min_area_m2"] == 1200
    assert preferences["max_price_eur"] == 350000
    assert preferences["keywords"] == "seezugang, jungle"
    assert preferences["search_agent_duration_days"] == 365
    assert preferences["search_agent_notification_limit"] == 6
    assert preferences["search_agent_notification_period"] == "week"


def test_property_search_agent_update_rejects_unknown_agent() -> None:
    client = build_property_client(principal_id="exec-property-search-agent-missing")
    start_workspace(client, mode="personal", workspace_name="Property office")

    missing = client.post(
        "/v1/onboarding/property-search/agents/does-not-exist",
        json={"action": "pause"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "property_search_agent_not_found"
