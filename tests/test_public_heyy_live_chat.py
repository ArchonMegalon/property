from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.public_heyy_live_chat import (
    heyy_live_chat_head_snippet,
    heyy_live_chat_route_allowed,
    heyy_live_chat_widget_id,
)


def _clear_heyy_live_chat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED",
        "PROPERTYQUARRY_PUBLIC_HEYY_LIVE_CHAT_ENABLED",
        "HEYY_LIVE_CHAT_ENABLED",
        "PROPERTYQUARRY_HEYY_LIVE_CHAT_WIDGET_ID",
        "MYEXTERNALBRAIN_HEYY_LIVE_CHAT_WIDGET_ID",
        "MANFRED_MEMORIAL_HEYY_LIVE_CHAT_WIDGET_ID",
        "CHUMMER_RUN_HEYY_LIVE_CHAT_WIDGET_ID",
        "HEYY_LIVE_CHAT_BASE_URL",
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_public_heyy_live_chat_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_heyy_live_chat_env(monkeypatch)

    assert heyy_live_chat_head_snippet(hostname="propertyquarry.com", path="/") == ""
    assert heyy_live_chat_widget_id(hostname="propertyquarry.com", path="/") == ""


def test_public_heyy_live_chat_uses_propertyquarry_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_heyy_live_chat_env(monkeypatch)
    monkeypatch.setenv("EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_LIVE_CHAT_WIDGET_ID", "property-widget-123")

    snippet = heyy_live_chat_head_snippet(hostname="propertyquarry.com", path="/pricing")

    assert snippet == ""


def test_public_heyy_live_chat_blocks_private_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_heyy_live_chat_env(monkeypatch)
    monkeypatch.setenv("EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED", "1")

    for path in ("/app/properties", "/api/health", "/v1/results", "/workspace-access/review-token", "/tours/private-tour"):
        assert not heyy_live_chat_route_allowed(path)
        assert heyy_live_chat_head_snippet(hostname="propertyquarry.com", path=path) == ""


def test_public_heyy_live_chat_uses_manfred_memorial_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_heyy_live_chat_env(monkeypatch)
    monkeypatch.setenv("EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED", "1")
    monkeypatch.setenv("MYEXTERNALBRAIN_HEYY_LIVE_CHAT_WIDGET_ID", "brain-widget-123")
    monkeypatch.setenv("MANFRED_MEMORIAL_HEYY_LIVE_CHAT_WIDGET_ID", "manfred-widget-123")

    assert heyy_live_chat_widget_id(hostname="myexternalbrain.com", path="/memorials/manfred") == ""
    assert heyy_live_chat_widget_id(hostname="myexternalbrain.com", path="/") == ""


def test_propertyquarry_public_page_omits_heyy_live_chat_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_heyy_live_chat_env(monkeypatch)
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    monkeypatch.setenv("EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_LIVE_CHAT_WIDGET_ID", "property-widget-123")

    from app.api.app import create_app

    client = TestClient(create_app())
    public_response = client.get("/", headers={"host": "propertyquarry.com"})
    app_response = client.get(
        "/app/properties",
        headers={"host": "propertyquarry.com", "X-EA-Principal-ID": "heyy-live-chat-test"},
    )

    assert public_response.status_code == 200
    assert "assets.heyy.io/live-chat/live-chat.js" not in public_response.text
    assert app_response.status_code == 200
    assert "assets.heyy.io/live-chat/live-chat.js" not in app_response.text
