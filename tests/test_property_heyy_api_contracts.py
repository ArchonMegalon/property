from __future__ import annotations

from app.services.fliplink.service import build_fliplink_packet_service
from tests.product_test_helpers import build_product_client


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
            "phone_number": "+436647916419",
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


def test_heyy_property_match_notification_endpoint_records_event(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-property-1",
            "delivery_status": "queued",
        },
    )

    response = client.post(
        "/app/api/integrations/heyy/notifications/property-match",
        json={
            "phone_number": "+436647916419",
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
    assert any(dict(row.get("payload_json") or {}).get("template_kind") == "property_match" for row in events)


def test_heyy_search_agent_digest_notification_endpoint_records_event(monkeypatch) -> None:
    client = build_product_client(principal_id="heyy-api-owner")

    monkeypatch.setattr(
        "app.api.routes.product_api.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "channel-1",
            "message_id": "msg-digest-1",
            "delivery_status": "queued",
        },
    )

    response = client.post(
        "/app/api/integrations/heyy/notifications/search-agent-digest",
        json={
            "phone_number": "+436647916419",
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
    assert any(dict(row.get("payload_json") or {}).get("template_kind") == "search_agent_digest" for row in events)
