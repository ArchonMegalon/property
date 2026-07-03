from __future__ import annotations

from app.services.fliplink.service import build_fliplink_packet_service
from app.services.heyy_whatsapp_service import redact_phone_number
from tests.product_test_helpers import build_product_client, start_workspace


def test_heyy_whatsapp_channel_endpoint_returns_verified_channel(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.verify_channel",
        lambda self, channel_id="": {
            "status": "ready",
            "provider": "heyy",
            "channel_id": channel_id or "channel-1",
            "channel_type": "whatsapp",
            "channel_status": "active",
        },
    )

    response = client.get("/app/api/integrations/heyy/whatsapp/channel", params={"channel_id": "channel-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "heyy"
    assert body["channel_type"] == "whatsapp"
    assert body["channel_status"] == "active"


def test_heyy_whatsapp_templates_endpoint_returns_templates(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.list_templates",
        lambda self: {
            "status": "ready",
            "provider": "heyy",
            "templates": [{"template_id": "tmpl-1", "name": "property_match_ready", "status": "approved"}],
        },
    )

    response = client.get("/app/api/integrations/heyy/whatsapp/templates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "heyy"
    assert body["templates"][0]["name"] == "property_match_ready"


def test_heyy_whatsapp_send_template_endpoint_returns_send_receipt(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    start_workspace(client, mode="personal", workspace_name="Heyy API Office", selected_channels=["whatsapp"])
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-1",
            "delivery_status": "queued",
        },
    )

    response = client.post(
        "/app/api/integrations/heyy/whatsapp/send-template",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-1",
            "channel_id": "channel-1",
            "variables": [{"name": "property_title", "value": "Altbau near U6"}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "heyy"
    assert body["message_id"] == "msg-1"
    assert body["delivery_status"] == "queued"


def test_heyy_whatsapp_webhook_requires_secret_and_records_receipt(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_WEBHOOK_SECRET", "heyy-secret")

    denied = client.post("/v1/integrations/heyy/whatsapp/webhook", json={"type": "message.received"})
    assert denied.status_code == 403, denied.text

    accepted = client.post(
        "/v1/integrations/heyy/whatsapp/webhook",
        json={
            "type": "message.received",
            "message": {"id": "msg-1", "text": "STOP"},
            "metadata": {"principal_id": "heyy-api-owner", "property_ref": "property-scout:123"},
        },
        headers={"X-PropertyQuarry-Heyy-Secret": "heyy-secret"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["event_type"] == "heyy_whatsapp_message_received"

    packet_service = build_fliplink_packet_service(client.app.state.container)
    events = packet_service.list_events(principal_id="heyy-api-owner", event_type="heyy_whatsapp_message_received", limit=20)
    assert events
    payload = dict(events[0].get("payload_json") or {})
    assert payload["message_id"] == "msg-1"
    assert payload["property_ref"] == "property-scout:123"
    assert payload["opt_command"] == "STOP"
    assert payload["text_present"] is True
    assert payload["text_char_count"] == 4
    assert "text" not in payload
    assert "phone_number" not in payload


def test_heyy_whatsapp_send_template_endpoint_requires_opt_in(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")

    response = client.post(
        "/app/api/integrations/heyy/whatsapp/send-template",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-1",
            "channel_id": "channel-1",
            "variables": [{"name": "property_title", "value": "Altbau near U6"}],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"] == "heyy_whatsapp_not_opted_in"


def test_heyy_whatsapp_send_template_endpoint_requires_enabled_flag(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    start_workspace(client, mode="personal", workspace_name="Heyy API Office", selected_channels=["whatsapp"])
    monkeypatch.delenv("PROPERTYQUARRY_HEYY_ENABLED", raising=False)

    response = client.post(
        "/app/api/integrations/heyy/whatsapp/send-template",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-1",
            "channel_id": "channel-1",
            "variables": [{"name": "property_title", "value": "Altbau near U6"}],
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"] == "heyy_disabled"


def test_heyy_whatsapp_stop_blocks_templates_until_start(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    start_workspace(client, mode="personal", workspace_name="Heyy STOP Office", selected_channels=["whatsapp"])
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_WEBHOOK_SECRET", "heyy-secret")

    stopped = client.post(
        "/v1/integrations/heyy/whatsapp/webhook",
        json={
            "type": "message.received",
            "message": {"id": "msg-stop", "text": "STOP"},
            "contact": {"phoneNumber": "+43 660 0000000"},
            "metadata": {"principal_id": "heyy-api-owner"},
        },
        headers={"X-PropertyQuarry-Heyy-Secret": "heyy-secret"},
    )
    assert stopped.status_code == 200, stopped.text

    blocked = client.post(
        "/app/api/integrations/heyy/whatsapp/send-template",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-1",
            "channel_id": "channel-1",
            "variables": [{"name": "property_title", "value": "Altbau near U6"}],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["details"] == "heyy_whatsapp_stopped"

    restarted = client.post(
        "/v1/integrations/heyy/whatsapp/webhook",
        json={
            "type": "message.received",
            "message": {"id": "msg-start", "text": "START"},
            "contact": {"phoneNumber": "+43 660 0000000"},
            "metadata": {"principal_id": "heyy-api-owner"},
        },
        headers={"X-PropertyQuarry-Heyy-Secret": "heyy-secret"},
    )
    assert restarted.status_code == 200, restarted.text

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-after-start",
            "delivery_status": "queued",
            "phone_e164_hash": redact_phone_number("+43 660 0000000")["phone_e164_hash"],
            "phone_last4": "0000",
        },
    )
    allowed = client.post(
        "/app/api/integrations/heyy/whatsapp/send-template",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-1",
            "channel_id": "channel-1",
            "variables": [{"name": "property_title", "value": "Altbau near U6"}],
        },
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["message_id"] == "msg-after-start"


def test_heyy_property_match_notification_endpoint_records_event(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    start_workspace(client, mode="personal", workspace_name="Heyy Property Match Office", selected_channels=["whatsapp"])
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-property-1",
            "delivery_status": "queued",
            "phone_e164_hash": redact_phone_number("+43 660 0000000")["phone_e164_hash"],
            "phone_last4": "0000",
        },
    )

    response = client.post(
        "/app/api/integrations/heyy/notifications/property-match",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-property",
            "channel_id": "channel-1",
            "property_ref": "property-scout:123",
            "property_title": "Altbau near U6",
            "fit_score": "92/100",
            "reason": "Lift and transit fit",
            "missing_fact": "Operating costs",
        },
    )
    assert response.status_code == 200, response.text
    packet_service = build_fliplink_packet_service(client.app.state.container)
    events = packet_service.list_events(principal_id="heyy-api-owner", event_type="heyy_whatsapp_template_sent", limit=20)
    payloads = [dict(row.get("payload_json") or {}) for row in events]
    assert any(payload.get("template_kind") == "property_match" for payload in payloads)
    property_payload = next(payload for payload in payloads if payload.get("template_kind") == "property_match")
    assert property_payload["phone_last4"] == "0000"
    assert property_payload["phone_e164_hash"] == redact_phone_number("+43 660 0000000")["phone_e164_hash"]
    assert "phone_number" not in property_payload


def test_heyy_search_agent_digest_notification_endpoint_records_event(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")
    start_workspace(client, mode="personal", workspace_name="Heyy Search Digest Office", selected_channels=["whatsapp"])
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-digest-1",
            "delivery_status": "queued",
            "phone_e164_hash": redact_phone_number("+43 660 0000000")["phone_e164_hash"],
            "phone_last4": "0000",
        },
    )

    response = client.post(
        "/app/api/integrations/heyy/notifications/search-agent-digest",
        json={
            "phone_number": "+43 660 0000000",
            "template_id": "tmpl-digest",
            "channel_id": "channel-1",
            "search_agent_id": "agent-1",
            "agent_name": "Vienna rent watch",
            "homes_checked": "12",
            "ranked_count": "4",
            "top_fit_score": "91",
            "held_back_count": "8",
        },
    )
    assert response.status_code == 200, response.text
    packet_service = build_fliplink_packet_service(client.app.state.container)
    events = packet_service.list_events(principal_id="heyy-api-owner", event_type="heyy_whatsapp_template_sent", limit=20)
    payloads = [dict(row.get("payload_json") or {}) for row in events]
    assert any(payload.get("template_kind") == "search_agent_digest" for payload in payloads)
    digest_payload = next(payload for payload in payloads if payload.get("template_kind") == "search_agent_digest")
    assert digest_payload["phone_last4"] == "0000"
    assert digest_payload["phone_e164_hash"] == redact_phone_number("+43 660 0000000")["phone_e164_hash"]
    assert "phone_number" not in digest_payload
