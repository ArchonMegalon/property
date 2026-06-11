from __future__ import annotations

import base64

import pytest

from app.repositories import property_packet_publications
from app.repositories.property_packet_publications import build_property_packet_publication_repository
from tests.product_test_helpers import build_property_client, start_workspace


@pytest.fixture(autouse=True)
def _reset_packet_repo(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv("PROPERTYQUARRY_DADAN_ENABLED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_DADAN_MODE", raising=False)
    monkeypatch.delenv("DADAN_API_KEY", raising=False)
    monkeypatch.delenv("DADAN_WEBHOOK_SECRET", raising=False)
    repo = property_packet_publications._MEMORY_REPO
    repo._publications.clear()
    repo._publication_order.clear()
    repo._events.clear()
    repo._event_order.clear()


def test_dadan_recording_request_is_disabled_by_default() -> None:
    client = build_property_client(principal_id="dadan-disabled-owner")
    start_workspace(client, mode="personal", workspace_name="Dadan Disabled")

    response = client.post(
        "/app/api/property-video/requests/dadan",
        json={
            "property_ref": "listing-123",
            "request_kind": "agent_missing_fact",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "dadan_disabled"


def test_dadan_dry_run_request_records_safe_video_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DADAN_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DADAN_MODE", "api_dry_run")
    client = build_property_client(principal_id="dadan-dry-owner")
    start_workspace(client, mode="personal", workspace_name="Dadan Dry Run")

    response = client.post(
        "/app/api/property-video/requests/dadan",
        json={
            "property_ref": "listing-123",
            "property_url": "https://example.invalid/listing-123",
            "request_kind": "agent_missing_fact",
            "audience_type": "agent",
            "title": "Missing-fact check",
            "instructions": "Please show the heating system.",
            "metadata": {"exact_address": "Private Street 4", "nested": {"drop": True}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    request = body["request"]
    assert body["status"] == "created"
    assert request["dadan_request_code"].startswith("dry_")
    assert request["trust_state"] == "operator_requested"
    assert request["metadata_json"] == {"exact_address": "Private Street 4"}

    events = build_property_packet_publication_repository(client.app.state.container.settings).list_events(
        principal_id="dadan-dry-owner",
        event_type="property_video_request_created",
    )
    assert events
    assert events[0]["payload_json"]["status"] == "dry_run"


def test_dadan_recording_webhook_requires_secret_and_stores_untrusted_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_DADAN_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_DADAN_MODE", "api_dry_run")
    monkeypatch.setenv("DADAN_WEBHOOK_SECRET", "dadan-secret")
    client = build_property_client(principal_id="dadan-webhook-owner")
    start_workspace(client, mode="personal", workspace_name="Dadan Webhook")

    created = client.post(
        "/app/api/property-video/requests/dadan",
        json={"property_ref": "listing-123", "request_kind": "family_review", "audience_type": "family"},
    )
    assert created.status_code == 200, created.text
    code = created.json()["request"]["dadan_request_code"]

    denied = client.post(
        "/v1/integrations/dadan/webhooks/recording-submitted",
        json={"requestCode": code, "recordingUrl": "https://dadan.io/watch/abc"},
    )
    assert denied.status_code == 401

    oversized = client.post(
        "/v1/integrations/dadan/webhooks/recording-submitted",
        headers={"x-propertyquarry-webhook-secret": "dadan-secret", "content-type": "application/json"},
        content=b'{"requestCode":"' + code.encode("utf-8") + b'","blob":"' + (b"x" * 65_000) + b'"}',
    )
    assert oversized.status_code == 413

    accepted = client.post(
        "/v1/integrations/dadan/webhooks/recording-submitted",
        headers={"x-propertyquarry-webhook-secret": "dadan-secret"},
        json={
            "recordingTitle": "Family review",
            "recordingUrl": "https://dadan.io/watch/abc",
            "requestCode": code,
            "submittedAt": "2026-06-10T20:00:00Z",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["trust"] == "untrusted_external"
    assert accepted.json()["review_state"] == "pending_owner_review"

    basic = base64.b64encode(b"dadan:dadan-secret").decode("ascii")
    basic_accepted = client.post(
        "/v1/integrations/dadan/webhooks/recording-submitted",
        headers={"authorization": f"Basic {basic}"},
        json={
            "recordingTitle": "Family review",
            "recordingUrl": "https://dadan.io/watch/def",
            "requestCode": code,
            "submittedAt": "2026-06-10T20:01:00Z",
        },
    )
    assert basic_accepted.status_code == 200, basic_accepted.text

    events = build_property_packet_publication_repository(client.app.state.container.settings).list_events(
        principal_id="dadan-webhook-owner",
        event_type="property_video_response_received",
    )
    assert events
    payload = events[0]["payload_json"]
    assert payload["trust_state"] == "untrusted_external"
    assert payload["review_state"] == "pending_owner_review"
    assert payload["dadan_recording_url"].startswith("https://dadan.io/watch/")


def test_dadan_webhook_records_unmatched_without_learning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DADAN_WEBHOOK_SECRET", "dadan-secret")
    client = build_property_client(principal_id="dadan-unmatched-owner")
    start_workspace(client, mode="personal", workspace_name="Dadan Unmatched")

    accepted = client.post(
        "/v1/integrations/dadan/webhooks/recording-submitted",
        headers={"x-propertyquarry-webhook-secret": "dadan-secret"},
        json={
            "recordingTitle": "Unmatched",
            "recordingUrl": "https://dadan.io/watch/unmatched",
            "requestCode": "unknown",
            "submittedAt": "2026-06-10T20:00:00Z",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted_unmatched"
    events = build_property_packet_publication_repository(client.app.state.container.settings).list_events(
        event_type="property_video_response_received",
    )
    assert events[0]["payload_json"]["principal_id"] == ""
    assert events[0]["payload_json"]["trust_state"] == "untrusted_external"
