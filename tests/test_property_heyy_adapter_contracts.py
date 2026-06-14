from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.heyy_whatsapp_service import HeyyWhatsAppBridgeService, heyy_enabled
from tests.product_test_helpers import build_product_client


class _FakeUrlopenResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._payload
        return self._payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_heyy_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_HEYY_ENABLED", raising=False)
    assert heyy_enabled() is False


def test_heyy_verify_channel_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_HEYY_API_KEY", raising=False)
    client = build_product_client(principal_id="heyy-owner")
    service = HeyyWhatsAppBridgeService(tool_runtime=client.app.state.container.tool_runtime)
    with pytest.raises(RuntimeError, match="heyy_api_key_missing"):
        service.verify_channel(channel_id="channel-1")


def test_heyy_plan_channel_binding_records_whatsapp_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_product_client(principal_id="heyy-owner")
    service = HeyyWhatsAppBridgeService(tool_runtime=client.app.state.container.tool_runtime)
    binding = service.plan_channel_binding(
        principal_id="heyy-owner",
        channel_id="channel-1",
        phone_number="+436647916419",
        label="PropertyQuarry WhatsApp",
    )
    assert binding.connector_name == "whatsapp_heyy"
    assert binding.external_account_ref == "+436647916419"
    assert binding.scope_json["channel_id"] == "channel-1"


def test_heyy_verify_channel_uses_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_API_KEY", "secret-token")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_BASE_URL", "https://api.heyy.test/api/v2.0")
    observed: dict[str, object] = {}

    def _fake_urlopen(request, timeout=0):  # noqa: ANN001
        observed["url"] = request.full_url
        observed["authorization"] = request.headers.get("Authorization")
        return _FakeUrlopenResponse({"data": {"id": "channel-1", "type": "whatsapp", "status": "active"}})

    client = build_product_client(principal_id="heyy-owner")
    service = HeyyWhatsAppBridgeService(tool_runtime=client.app.state.container.tool_runtime)
    with patch("app.services.heyy_whatsapp_service.urllib.request.urlopen", _fake_urlopen):
        result = service.verify_channel(channel_id="channel-1")
    assert observed["url"] == "https://api.heyy.test/api/v2.0/channels/channel-1"
    assert observed["authorization"] == "Bearer secret-token"
    assert result["channel_type"] == "whatsapp"
    assert result["channel_status"] == "active"


def test_heyy_send_template_posts_whatsapp_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_API_KEY", "secret-token")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_BASE_URL", "https://api.heyy.test/api/v2.0")
    observed: dict[str, object] = {}

    def _fake_urlopen(request, timeout=0):  # noqa: ANN001
        observed["url"] = request.full_url
        observed["authorization"] = request.headers.get("Authorization")
        observed["payload"] = json.loads((request.data or b"{}").decode("utf-8"))
        return _FakeUrlopenResponse({"data": {"id": "msg-1", "status": "queued"}})

    client = build_product_client(principal_id="heyy-owner")
    service = HeyyWhatsAppBridgeService(tool_runtime=client.app.state.container.tool_runtime)
    with patch("app.services.heyy_whatsapp_service.urllib.request.urlopen", _fake_urlopen):
        result = service.send_template(
            phone_number="+436647916419",
            template_id="tmpl-1",
            channel_id="channel-1",
            variables=[{"name": "property_title", "value": "Altbau near U6"}],
        )
    assert observed["url"] == "https://api.heyy.test/api/v2.0/channel-1/whatsapp_messages/send"
    assert observed["authorization"] == "Bearer secret-token"
    assert observed["payload"]["phoneNumber"] == "+436647916419"
    assert observed["payload"]["messageTemplateId"] == "tmpl-1"
    assert result["message_id"] == "msg-1"
    assert result["delivery_status"] == "queued"
    assert result["phone_last4"] == "6419"
    assert "phone_e164_hash" in result
