from __future__ import annotations

import json
import hashlib
import hmac
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.brilliant_directories import (
    BrilliantDirectoriesApiError,
    build_brilliant_directories_api_request,
    build_brilliant_directories_member_profile_request,
    build_brilliant_directories_member_search_request,
    build_brilliant_directories_projection_packet_from_profile_response,
    build_brilliant_directories_projection_packet_from_search_response,
    build_brilliant_directories_projection_packet,
    build_brilliant_directories_verification_receipt,
    build_directory_profile_projection,
    brilliant_directories_billing_handoff_url,
    execute_brilliant_directories_api_request,
    fetch_brilliant_directories_member_profile_projection_packet,
    fetch_brilliant_directories_member_projection_packet,
    load_brilliant_directories_config,
)
from app.services import brilliant_directories as brilliant_directories_service
from app.services.property_billing import (
    brilliant_directories_billing_webhook_receipt,
    normalize_property_commercial,
    reconcile_brilliant_directories_billing_event,
    verify_brilliant_directories_billing_webhook_signature,
)
from tests.product_test_helpers import build_property_client, start_workspace


ROOT = Path(__file__).resolve().parents[1]


class _FakeBrilliantDirectoriesResponse:
    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        self._body = body
        self._content_type = content_type

    def getheader(self, name: str, default: str = "") -> str:
        if name.lower() == "content-type":
            return self._content_type
        return default

    def read(self, size: int = -1) -> bytes:
        if size is not None and size >= 0:
            return self._body[:size]
        return self._body


class _FakeBrilliantDirectoriesOpener:
    def __init__(self, response: _FakeBrilliantDirectoriesResponse) -> None:
        self.response = response
        self.requests: list[object] = []

    def open(self, request, timeout: float = 0):  # noqa: ANN001
        self.requests.append(request)
        return self.response


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_PUBLIC_SITE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_PRICING_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_WEBHOOK_SECRET",
        "BRILLIANT_DIRECTORIES_API_KEY",
        "BRILLIANT_DIRECTORIES_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _bd_signature(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()


def test_brilliant_directories_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)

    config = load_brilliant_directories_config()
    receipt = build_brilliant_directories_verification_receipt()

    assert config.enabled is False
    assert config.configured is False
    assert receipt["status"] == "disabled"
    assert receipt["live_network_called"] is False


def test_brilliant_directories_enabled_config_requires_https_allowed_host_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")

    with pytest.raises(BrilliantDirectoriesApiError) as missing_base:
        load_brilliant_directories_config()
    assert str(missing_base.value) == "brilliant_directories_base_url_missing"

    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "http://directory.example/api")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "secret")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    with pytest.raises(BrilliantDirectoriesApiError) as non_https:
        load_brilliant_directories_config()
    assert str(non_https.value) == "brilliant_directories_https_required"

    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://evil.example/api")
    with pytest.raises(BrilliantDirectoriesApiError) as bad_host:
        load_brilliant_directories_config()
    assert str(bad_host.value) == "brilliant_directories_host_not_allowed"


def test_brilliant_directories_request_builder_keeps_api_key_out_of_url_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    config = load_brilliant_directories_config()
    request = build_brilliant_directories_api_request(
        config,
        "POST",
        "/members/search",
        payload={"category": "relocation advisor"},
        query={"limit": 10},
    )

    assert request.url == "https://directory.example/api/v2/members/search?limit=10"
    assert request.headers["X-Api-Key"] == "bd-secret-token"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"bd-secret-token" not in (request.body or b"")
    assert request.body == b"category=relocation+advisor"
    assert "bd-secret-token" not in request.url
    assert request.redacted_receipt()["headers"]["X-Api-Key"] == "[redacted]"


def test_brilliant_directories_billing_handoff_requires_white_label_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.propertyquarry.com,billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")

    config = load_brilliant_directories_config()

    assert brilliant_directories_billing_handoff_url(config) == "https://billing.propertyquarry.com/account"

    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.brilliantdirectories.com/account")
    assert brilliant_directories_billing_handoff_url(config) == ""


def test_brilliant_directories_billing_handoff_allows_url_only_white_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")

    config = load_brilliant_directories_config()

    assert not config.configured
    assert brilliant_directories_billing_handoff_url(config) == "https://billing.propertyquarry.com/account"


def test_brilliant_directories_verifier_blocks_unresolved_billing_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET", "members.brilliantdirectories.com")

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("missing dns")

    receipt = build_brilliant_directories_verification_receipt(billing_handoff_resolver=unresolved)

    assert receipt["status"] == "blocked"
    assert receipt["error"].startswith("billing_handoff_host_unresolved")
    assert receipt["billing_handoff"]["configured"] is True
    assert receipt["billing_handoff"]["host"] == "billing.propertyquarry.com"
    assert receipt["billing_handoff"]["host_resolves"] is False
    assert receipt["billing_handoff"]["required_dns_record"] == {
        "name": "billing.propertyquarry.com",
        "type": "CNAME",
        "target": "members.brilliantdirectories.com",
        "purpose": "make /app/billing redirect only to a resolving HTTPS white-label account lane",
    }
    assert "create DNS for billing.propertyquarry.com" in receipt["billing_handoff"]["next_action"]


def test_brilliant_directories_verifier_accepts_resolving_billing_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")

    def resolved(_host: str, _port: int) -> list[tuple[object, ...]]:
        return [(object(),)]

    receipt = build_brilliant_directories_verification_receipt(billing_handoff_resolver=resolved)

    assert receipt["status"] == "disabled"
    assert receipt["error"] == ""
    assert receipt["billing_handoff"]["configured"] is True
    assert receipt["billing_handoff"]["host_resolves"] is True
    assert receipt["billing_handoff"]["required_dns_record"]["name"] == "billing.propertyquarry.com"
    assert receipt["billing_handoff"]["next_action"].startswith("keep the resolving HTTPS billing handoff")


def test_brilliant_directories_verifier_accepts_public_dns_when_local_resolver_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET", "members.brilliantdirectories.com")

    def stale_local_resolver(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def dns_response(request, timeout=0):
        url = str(getattr(request, "full_url", request))
        if "name=billing.propertyquarry.com" in url:
            return _DnsResponse(
                {
                    "Status": 0,
                    "Answer": [
                        {
                            "name": "billing.propertyquarry.com.",
                            "type": 5,
                            "data": "members.brilliantdirectories.com.",
                        }
                    ],
                }
            )
        if "name=members.brilliantdirectories.com" in url and "type=A" in url:
            return _DnsResponse(
                {
                    "Status": 0,
                    "Answer": [
                        {
                            "name": "members.brilliantdirectories.com.",
                            "type": 1,
                            "data": "203.0.113.20",
                        }
                    ],
                }
            )
        return _DnsResponse({"Status": 0, "Answer": []})

    monkeypatch.setattr(urllib.request, "urlopen", dns_response)
    monkeypatch.setattr(brilliant_directories_service.socket, "getaddrinfo", stale_local_resolver)

    receipt = build_brilliant_directories_verification_receipt()

    assert receipt["status"] == "disabled"
    assert receipt["error"] == ""
    assert receipt["billing_handoff"]["host_resolves"] is True
    assert receipt["billing_handoff"]["resolution_source"] == "public_dns_over_https"
    assert receipt["billing_handoff"]["local_resolver_error"].startswith("billing_handoff_host_unresolved")
    assert receipt["billing_handoff"]["public_dns"]["matched_target"] is True
    assert receipt["billing_handoff"]["public_dns"]["target_resolves"] is True


def test_brilliant_directories_verifier_rejects_public_dns_target_without_address_records(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET", "members.brilliantdirectories.com")

    def stale_local_resolver(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def dns_response(request, timeout=0):
        url = str(getattr(request, "full_url", request))
        if "name=billing.propertyquarry.com" in url:
            return _DnsResponse(
                {
                    "Status": 0,
                    "Answer": [
                        {
                            "name": "billing.propertyquarry.com.",
                            "type": 5,
                            "data": "members.brilliantdirectories.com.",
                        }
                    ],
                }
            )
        return _DnsResponse({"Status": 3, "Answer": []})

    monkeypatch.setattr(urllib.request, "urlopen", dns_response)
    monkeypatch.setattr(brilliant_directories_service.socket, "getaddrinfo", stale_local_resolver)

    receipt = build_brilliant_directories_verification_receipt()

    assert receipt["status"] == "blocked"
    assert receipt["billing_handoff"]["host_resolves"] is False
    assert receipt["billing_handoff"]["public_dns"]["matched_target"] is True
    assert receipt["billing_handoff"]["public_dns"]["target_resolves"] is False
    assert "Brilliant Directories Domain Manager" in receipt["billing_handoff"]["next_action"]


def test_brilliant_directories_verifier_rejects_public_dns_target_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET", "members.brilliantdirectories.com")

    def stale_local_resolver(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "Status": 0,
                    "Answer": [
                        {
                            "name": "billing.propertyquarry.com.",
                            "type": 5,
                            "data": "wrong.example.com.",
                        }
                    ],
                }
            ).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: _DnsResponse())
    monkeypatch.setattr(brilliant_directories_service.socket, "getaddrinfo", stale_local_resolver)

    receipt = build_brilliant_directories_verification_receipt()

    assert receipt["status"] == "blocked"
    assert receipt["billing_handoff"]["host_resolves"] is False
    assert receipt["billing_handoff"]["public_dns"]["matched_target"] is False


def test_property_billing_route_redirects_to_allowlisted_brilliant_directories_account(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.propertyquarry.com,billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setattr(
        "app.api.routes.landing.brilliant_directories_service.build_brilliant_directories_verification_receipt",
        lambda: {
            "status": "dry_verified_configured",
            "billing_handoff": {
                "configured": True,
                "url": "https://billing.propertyquarry.com/account",
                "host": "billing.propertyquarry.com",
                "host_resolves": True,
                "error": "",
            },
        },
    )
    client = build_property_client(principal_id="exec-bd-billing-direct")
    start_workspace(client, mode="personal", workspace_name="BD Billing Direct Office")

    response = client.get("/app/billing", headers={"host": "propertyquarry.com"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "https://billing.propertyquarry.com/account"


def test_property_billing_route_fails_closed_when_brilliant_directories_host_does_not_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.propertyquarry.com,billing.propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL", "https://billing.propertyquarry.com/account")
    monkeypatch.setattr(
        "app.api.routes.landing.brilliant_directories_service.build_brilliant_directories_verification_receipt",
        lambda: {
            "status": "blocked",
            "error": "billing_handoff_host_unresolved:gaierror",
            "billing_handoff": {
                "configured": True,
                "url": "https://billing.propertyquarry.com/account",
                "host": "billing.propertyquarry.com",
                "host_resolves": False,
                "error": "billing_handoff_host_unresolved:gaierror",
            },
        },
    )
    client = build_property_client(principal_id="exec-bd-billing-unresolved")
    start_workspace(client, mode="personal", workspace_name="BD Billing Unresolved Office")

    response = client.get("/app/billing", headers={"host": "propertyquarry.com"}, follow_redirects=False)

    assert response.status_code == 503
    assert "Billing handoff unavailable" in response.text
    assert "billing.propertyquarry.com/account" not in response.text


def test_brilliant_directories_receipt_records_billing_as_advisory_white_label_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)

    receipt = build_brilliant_directories_verification_receipt()
    capabilities = receipt["verified_capabilities"]

    assert capabilities["white_label_billing_handoff_host_allowlist"] is True
    assert capabilities["billing_source_of_truth_stays_propertyquarry"] is True
    assert capabilities["brilliant_directories_billing_events_advisory_only"] is True
    assert capabilities["billing_webhooks_must_be_signed_and_reconciled"] is True
    assert capabilities["billing_webhook_timestamped_hmac_contract"] is True
    assert capabilities["billing_webhook_replay_guard_contract"] is True
    assert capabilities["billing_webhook_entitlement_mutation_disabled"] is True


def test_brilliant_directories_billing_webhook_requires_timestamped_hmac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_WEBHOOK_SECRET", "bd-webhook-secret")
    body = b'{"event_id":"bd_evt_1","event_type":"invoice.paid","plan_key":"agent"}'
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    signature = _bd_signature("bd-webhook-secret", timestamp, body)

    assert verify_brilliant_directories_billing_webhook_signature(
        body_bytes=body,
        signature=signature,
        timestamp=timestamp,
        now=now,
    )
    assert verify_brilliant_directories_billing_webhook_signature(
        body_bytes=body,
        signature=f"sha256={signature}",
        timestamp=timestamp,
        now=now,
    )
    assert not verify_brilliant_directories_billing_webhook_signature(
        body_bytes=body,
        signature="bad-signature",
        timestamp=timestamp,
        now=now,
    )
    assert not verify_brilliant_directories_billing_webhook_signature(
        body_bytes=body,
        signature=signature,
        timestamp=timestamp - 301,
        now=now,
    )


def test_brilliant_directories_billing_webhook_receipt_is_advisory_and_needs_local_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_WEBHOOK_SECRET", "bd-webhook-secret")
    payload = {
        "event_id": "bd_evt_invoice_1",
        "event_type": "invoice.paid",
        "plan_key": "agent",
        "order_id": "bd_order_1",
        "invoice_id": "bd_invoice_1",
        "invoice_url": "https://billing.propertyquarry.com/invoices/bd_invoice_1",
        "payment_status": "paid",
        "amount_eur": "99.00",
        "currency": "EUR",
    }
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    signature = _bd_signature("bd-webhook-secret", timestamp, body)

    receipt = brilliant_directories_billing_webhook_receipt(
        {},
        payload=payload,
        body_bytes=body,
        signature=signature,
        timestamp=timestamp,
        now=now,
    )

    assert receipt["status"] == "accepted_advisory_receipt"
    assert receipt["signature_verified"] is True
    assert receipt["advisory_only"] is True
    assert receipt["entitlement_mutation_allowed"] is False
    assert receipt["local_reconciliation_required"] is True
    assert receipt["body_sha256"] == hashlib.sha256(body).hexdigest()
    updates = receipt["billing_event_updates"]
    assert updates["last_billing_event_id"] == "bd_evt_invoice_1"
    assert updates["billing_events_json"][-1]["provider"] == "brilliant_directories"
    assert updates["billing_events_json"][-1]["accounting_status"] == "external_advisory"
    assert "invoice_url" in receipt["payload_keys"]
    public_receipt = {key: value for key, value in receipt.items() if key != "billing_event_updates"}
    assert "bd_invoice_1" not in json.dumps(public_receipt)

    commercial_after = normalize_property_commercial(updates)
    assert commercial_after["active_plan_key"] == "free"
    assert commercial_after["status"] == "free"


def test_brilliant_directories_billing_webhook_replay_does_not_append_or_mutate_entitlements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_WEBHOOK_SECRET", "bd-webhook-secret")
    payload = {
        "event_id": "bd_evt_replayed",
        "event_type": "invoice.paid",
        "plan_key": "plus",
        "payment_status": "paid",
        "amount": "3.00",
    }
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    signature = _bd_signature("bd-webhook-secret", timestamp, body)
    existing = {
        "billing_events_json": [
            {
                "event_id": "bd_evt_replayed",
                "event_type": "invoice.paid",
                "provider": "brilliant_directories",
                "recorded_at": "2026-06-25T11:59:00+00:00",
            }
        ],
    }

    receipt = brilliant_directories_billing_webhook_receipt(
        existing,
        payload=payload,
        body_bytes=body,
        signature=signature,
        timestamp=timestamp,
        now=now,
    )

    assert receipt["status"] == "replayed"
    assert receipt["signature_verified"] is True
    assert receipt["replayed"] is True
    assert receipt["billing_event_updates"] == {}
    commercial = normalize_property_commercial(existing)
    assert commercial["active_plan_key"] == "free"
    assert len(commercial["billing_events_json"]) == 1


def test_brilliant_directories_local_reconciliation_approves_signed_advisory_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    existing = {
        "billing_events_json": [
            {
                "event_id": "bd_evt_reconcile_1",
                "event_type": "invoice.paid",
                "provider": "brilliant_directories",
                "plan_key": "agent",
                "order_id": "bd_order_1",
                "invoice_id": "bd_invoice_1",
                "accounting_status": "external_advisory",
                "payment_status": "paid",
                "amount_eur": "99.00",
                "recorded_at": "2026-06-25T11:59:00+00:00",
            }
        ],
    }
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)

    receipt = reconcile_brilliant_directories_billing_event(
        existing,
        event_id="bd_evt_reconcile_1",
        decision="approve",
        reconciled_by="operator@propertyquarry.com",
        note="Invoice and account match local customer.",
        now=now,
    )
    commercial = normalize_property_commercial({**existing, **receipt["updates"]})

    assert receipt["status"] == "approved_local_entitlement"
    assert receipt["entitlement_mutation"] == "activated"
    assert receipt["reconciliation"]["note_sha256"]
    assert "operator@propertyquarry.com" not in json.dumps(receipt)
    assert commercial["active_plan_key"] == "agent"
    assert commercial["status"] == "active"
    assert commercial["plan_source"] == "brilliant_directories_local_reconciliation"
    assert commercial["billing_reconciliations_json"][-1]["decision"] == "approve"
    assert commercial["billing_events_json"][-1]["accounting_status"] == "local_reconciled"


def test_brilliant_directories_local_reconciliation_can_reject_without_entitlement_mutation() -> None:
    existing = {
        "active_plan_key": "free",
        "billing_events_json": [
            {
                "event_id": "bd_evt_reject_1",
                "event_type": "invoice.paid",
                "provider": "brilliant_directories",
                "plan_key": "plus",
                "accounting_status": "external_advisory",
                "payment_status": "paid",
            }
        ],
    }

    receipt = reconcile_brilliant_directories_billing_event(
        existing,
        event_id="bd_evt_reject_1",
        decision="reject",
        reconciled_by="billing-operator",
        note="Customer mismatch.",
    )
    commercial = normalize_property_commercial({**existing, **receipt["updates"]})

    assert receipt["status"] == "rejected_no_entitlement_change"
    assert receipt["entitlement_mutation"] == "none"
    assert commercial["active_plan_key"] == "free"
    assert commercial["billing_reconciliations_json"][-1]["decision"] == "reject"
    assert commercial["billing_events_json"][-1]["accounting_status"] == "local_rejected"


def test_brilliant_directories_local_reconciliation_rejects_unpaid_or_replayed_event() -> None:
    existing = {
        "billing_events_json": [
            {
                "event_id": "bd_evt_failed_1",
                "provider": "brilliant_directories",
                "plan_key": "plus",
                "payment_status": "failed",
            },
            {
                "event_id": "bd_evt_done_1",
                "provider": "brilliant_directories",
                "plan_key": "plus",
                "payment_status": "paid",
            },
        ],
        "billing_reconciliations_json": [
            {
                "event_id": "bd_evt_done_1",
                "provider": "brilliant_directories",
                "decision": "approve",
                "status": "approved_local_entitlement",
            }
        ],
    }

    with pytest.raises(ValueError, match="payment_not_paid"):
        reconcile_brilliant_directories_billing_event(
            existing,
            event_id="bd_evt_failed_1",
            decision="approve",
            reconciled_by="billing-operator",
        )
    with pytest.raises(ValueError, match="already_reconciled"):
        reconcile_brilliant_directories_billing_event(
            existing,
            event_id="bd_evt_done_1",
            decision="reject",
            reconciled_by="billing-operator",
        )


def test_brilliant_directories_request_builder_supports_explicit_json_without_making_it_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_api_request(
        load_brilliant_directories_config(),
        "POST",
        "/widgets/render",
        payload={"widget": "public_directory"},
        body_format="json",
    )

    assert request.headers["Content-Type"] == "application/json"
    assert request.body == b'{"widget": "public_directory"}'


def test_brilliant_directories_member_search_request_uses_official_form_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_search_request(
        load_brilliant_directories_config(),
        keyword="relocation",
        category="advisor",
        city="Vienna",
        country_code="at",
        limit=250,
    )

    assert request.method == "POST"
    assert request.url == "https://directory.example/api/v2/user/search"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert request.body is not None
    body = request.body.decode("utf-8")
    assert "q=relocation" in body
    assert "category=advisor" in body
    assert "city=Vienna" in body
    assert "country_code=AT" in body
    assert "limit=100" in body


def test_brilliant_directories_member_search_request_does_not_duplicate_api_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_search_request(
        load_brilliant_directories_config(),
        keyword="relocation",
    )

    assert request.url == "https://directory.example/api/v2/user/search"
    assert "/api/v2/api/v2/" not in request.url


def test_brilliant_directories_member_profile_request_uses_official_get_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_profile_request(
        load_brilliant_directories_config(),
        profile_id="24",
    )

    assert request.method == "GET"
    assert request.url == "https://directory.example/api/v2/user/get/24"
    assert request.body is None

    with pytest.raises(BrilliantDirectoriesApiError) as invalid_profile:
        build_brilliant_directories_member_profile_request(load_brilliant_directories_config(), profile_id="../24")
    assert str(invalid_profile.value) == "brilliant_directories_profile_id_invalid"


def test_brilliant_directories_member_profile_fetch_projects_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(
            b'{"message":{"user_id":"24","company":"Vienna Relocation Advisors","profession":"Relocation"}}'
        )
    )

    packet = fetch_brilliant_directories_member_profile_projection_packet(
        load_brilliant_directories_config(),
        profile_id="24",
        purpose="Public profile detail",
        opener=opener,
    )

    assert opener.requests[0].get_full_url() == "https://directory.example/api/v2/user/get/24"
    assert packet.as_dict()["profiles"][0]["display_name"] == "Vienna Relocation Advisors"


def test_brilliant_directories_executor_reads_json_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    config = load_brilliant_directories_config()
    request = build_brilliant_directories_member_search_request(config, keyword="relocation")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(b'{"message":[{"user_id":"7","company":"Public Advisor"}]}')
    )

    payload = execute_brilliant_directories_api_request(request, opener=opener)

    assert payload["message"][0]["company"] == "Public Advisor"  # type: ignore[index]
    assert opener.requests
    sent = opener.requests[0]
    assert sent.get_full_url() == "https://directory.example/api/v2/user/search"
    assert sent.get_header("X-api-key") == "bd-secret-token" or sent.get_header("X-Api-Key") == "bd-secret-token"
    assert request.redacted_receipt()["headers"]["X-Api-Key"] == "[redacted]"
    assert "bd-secret-token" not in json.dumps(request.redacted_receipt())


def test_brilliant_directories_executor_rejects_non_json_and_oversized_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    request = build_brilliant_directories_member_search_request(load_brilliant_directories_config())

    with pytest.raises(BrilliantDirectoriesApiError) as content_type_error:
        execute_brilliant_directories_api_request(
            request,
            opener=_FakeBrilliantDirectoriesOpener(
                _FakeBrilliantDirectoriesResponse(b"<html></html>", content_type="text/html")
            ),
        )
    assert str(content_type_error.value) == "brilliant_directories_unexpected_content_type"

    monkeypatch.setattr(brilliant_directories_service, "BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES", 8)
    with pytest.raises(BrilliantDirectoriesApiError) as oversized_error:
        execute_brilliant_directories_api_request(
            request,
            opener=_FakeBrilliantDirectoriesOpener(
                _FakeBrilliantDirectoriesResponse(b'{"message":[1,2,3]}')
            ),
        )
    assert str(oversized_error.value) == "brilliant_directories_response_too_large"


def test_brilliant_directories_executor_blocks_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    request = build_brilliant_directories_member_search_request(load_brilliant_directories_config())

    class _RedirectingOpener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            import urllib.error

            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "brilliant_directories_redirect_blocked",
                {},
                None,
            )

    with pytest.raises(BrilliantDirectoriesApiError) as redirect_error:
        execute_brilliant_directories_api_request(request, opener=_RedirectingOpener())
    assert str(redirect_error.value) == "brilliant_directories_redirect_blocked"


def test_brilliant_directories_projection_allows_public_directory_fields() -> None:
    profile = build_directory_profile_projection(
        {
            "member_id": 42,
            "name": "Vienna Relocation Advisors",
            "category": "Relocation",
            "profile_url": "https://directory.example/vienna-relocation",
            "city": "Vienna",
            "region": "Vienna",
            "country_code": "AT",
            "description": "English and German relocation guidance.",
            "tags": ["relocation", "renters"],
        }
    )
    packet = build_brilliant_directories_projection_packet([profile], purpose="Public relocation directory")
    payload = packet.as_dict()

    assert payload["contract_name"] == "propertyquarry.brilliant_directories_projection.v1"
    assert payload["profile_count"] == 1
    assert payload["publication_allowed"] is False
    assert payload["direct_property_truth_mutation_allowed"] is False
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"


def test_brilliant_directories_projection_rejects_private_property_and_contact_fields() -> None:
    with pytest.raises(BrilliantDirectoriesApiError) as contact_error:
        build_directory_profile_projection({"id": "1", "name": "Agent", "email": "agent@example.test"})
    assert "private_field_blocked" in str(contact_error.value)

    with pytest.raises(BrilliantDirectoriesApiError) as ranking_error:
        build_directory_profile_projection({"id": "1", "name": "Agent", "property_facts": {"price": 1000}})
    assert "private_field_blocked" in str(ranking_error.value)

    for forbidden in ("billing", "payment", "invoice"):
        with pytest.raises(BrilliantDirectoriesApiError) as billing_error:
            build_directory_profile_projection({"id": "1", "name": "Agent", forbidden: "private"})
        assert "private_field_blocked" in str(billing_error.value)


def test_brilliant_directories_search_response_strips_private_member_fields() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {
                    "user_id": "17",
                    "company": "Vienna Relocation Advisors",
                    "email": "agent@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "lat": "48.2",
                    "lon": "16.3",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                    "search_description": "Public profile text with no contact detail.",
                }
            ],
        },
        purpose="Public relocation directory",
    )

    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert payload["profiles"][0]["public_url"] == "austria/vienna/vienna-relocation-advisors"
    assert "agent@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized
    assert "16.3" not in serialized
    assert "Public profile text" not in serialized


def test_brilliant_directories_search_response_strips_unapproved_external_profile_urls() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {
                    "user_id": "91",
                    "company": "Approved Directory Advisor",
                    "profile_url": "https://directory.example/austria/vienna/approved-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
                {
                    "user_id": "92",
                    "company": "External Directory Advisor",
                    "profile_url": "https://tracking.example/profile/external-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
                {
                    "user_id": "93",
                    "company": "Relative Directory Advisor",
                    "filename": "austria/vienna/relative-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
            ],
        },
        purpose="Public relocation directory",
        allowed_url_hosts=("directory.example",),
    )

    profiles = packet.as_dict()["profiles"]
    assert profiles[0]["public_url"] == "https://directory.example/austria/vienna/approved-advisor"
    assert "public_url" not in profiles[1]
    assert profiles[2]["public_url"] == "austria/vienna/relative-advisor"


def test_brilliant_directories_search_response_strips_unsafe_relative_profile_urls() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {"user_id": "81", "company": "Traversal Advisor", "filename": "../private/profile"},
                {"user_id": "82", "company": "Protocol Relative Advisor", "filename": "//evil.example/profile"},
            ],
        },
        purpose="Public relocation directory",
    )

    profiles = packet.as_dict()["profiles"]
    assert "public_url" not in profiles[0]
    assert "public_url" not in profiles[1]


def test_brilliant_directories_profile_response_projects_public_detail_only() -> None:
    packet = build_brilliant_directories_projection_packet_from_profile_response(
        {
            "status": "success",
            "message": {
                "user_id": "24",
                "company": "Vienna Relocation Advisors",
                "profession": "Relocation",
                "description": "Helps international renters prepare a Vienna search.",
                "specialties": "relocation,renters",
                "email": "private@example.test",
                "phone_number": "+43 1 555",
                "address1": "Secret Street 1",
                "lat": "48.2",
                "lon": "16.3",
                "filename": "austria/vienna/vienna-relocation-advisors",
                "city": "Vienna",
                "state_ln": "Vienna",
                "country_code": "AT",
            },
        },
        purpose="Public profile detail",
        allowed_url_hosts=("directory.example",),
    )

    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)
    profile = payload["profiles"][0]
    assert payload["projection_mode"] == "public_directory_profile_detail"
    assert profile["profile_id"] == "24"
    assert profile["display_name"] == "Vienna Relocation Advisors"
    assert profile["summary"] == "Helps international renters prepare a Vienna search."
    assert "relocation" in profile["tags"]
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized


def test_brilliant_directories_live_style_search_projection_uses_public_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(
            json.dumps(
                {
                    "message": [
                        {
                            "user_id": "24",
                            "company": "Vienna Relocation Advisors",
                            "email": "private@example.test",
                            "phone_number": "+43 1 555",
                            "filename": "austria/vienna/vienna-relocation-advisors",
                            "city": "Vienna",
                            "state_ln": "Vienna",
                            "country_code": "AT",
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )

    packet = fetch_brilliant_directories_member_projection_packet(
        load_brilliant_directories_config(),
        purpose="Public relocation directory",
        keyword="relocation",
        city="Vienna",
        country_code="AT",
        opener=opener,
    )
    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)

    assert opener.requests[0].get_full_url() == "https://directory.example/api/v2/user/search"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized


def test_brilliant_directories_runtime_route_reports_disabled_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-disabled")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/brilliant-directories/members?city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert "provider" not in payload
    assert "brilliant_directories" not in serialized
    assert payload["status"] == "disabled"
    assert payload["profile_count"] == 0
    assert payload["profiles"] == []
    assert payload["publication_allowed"] is False
    assert payload["direct_property_truth_mutation_allowed"] is False


def test_property_directory_members_route_is_white_label_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-directory-disabled")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/members?city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert payload["status"] == "disabled"
    assert payload["profile_count"] == 0
    assert payload["profiles"] == []
    assert "brilliant_directories" not in serialized
    assert "brilliant directories" not in serialized.lower()
    assert "brilliantdirectories" not in serialized.lower()


def test_brilliant_directories_runtime_route_fetches_public_member_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    captured_requests: list[object] = []

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        captured_requests.append(request)
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "lat": "48.2",
                    "lon": "16.3",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-runtime")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/brilliant-directories/members"
        "?keyword=relocation&category=advisor&city=Vienna&country_code=AT&limit=8",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "ready"
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert "provider" not in payload
    assert "brilliant_directories" not in serialized
    assert "brilliant directories" not in serialized.lower()
    assert "brilliantdirectories" not in serialized.lower()
    assert "directory.example" not in serialized
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized
    assert "16.3" not in serialized
    assert captured_requests
    sent = captured_requests[0]
    assert sent.url == "https://directory.example/api/v2/user/search"
    assert b"q=relocation" in (sent.body or b"")
    assert b"category=advisor" in (sent.body or b"")
    assert b"city=Vienna" in (sent.body or b"")
    assert b"country_code=AT" in (sent.body or b"")
    assert b"limit=8" in (sent.body or b"")
    assert b"bd-secret-token" not in (sent.body or b"")

    route_source = Path("ea/app/api/routes/product_api.py").read_text(encoding="utf-8")
    assert '@router.get("/property/directories/brilliant-directories/members", include_in_schema=False)' in route_source


def test_property_directory_members_route_returns_white_label_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        assert getattr(request, "url", "") == "https://directory.example/api/v2/user/search"
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "profession": "Relocation",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-directory-white-label")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/members?keyword=relocation&city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert payload["status"] == "ready"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert "brilliant_directories" not in serialized
    assert "brilliant directories" not in serialized.lower()
    assert "brilliantdirectories" not in serialized.lower()
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized


def test_brilliant_directories_public_directory_page_is_white_label_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-public-disabled")

    response = client.get("/directory", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in response.text
    assert response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"
    assert "PropertyQuarry Directory" in response.text
    assert "Property advisors." in response.text
    assert "Reviewed public profiles for relocation, financing, inspections, and local support." in response.text
    assert "Directory is temporarily unavailable" in response.text
    assert "governed directory lane" not in response.text
    assert "another branded site" not in response.text
    assert "</style>\n</style>" not in response.text
    assert "Search directory" not in response.text
    assert ">Reset<" not in response.text
    assert "Brilliant Directories" not in response.text
    assert "brilliantdirectories.com" not in response.text.lower()
    assert "credentials" not in response.text
    assert "not active on this host" not in response.text
    assert "provider returned" not in response.text.lower()
    assert "provider stores" not in response.text.lower()

    profile_response = client.get("/directory/profile/sample", headers={"host": "propertyquarry.com"})
    assert profile_response.status_code == 200
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in profile_response.text
    assert profile_response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"
    assert "another branded site" not in profile_response.text


def test_brilliant_directories_sitemap_hides_unconfigured_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-sitemap-disabled")

    response = client.get("/sitemap.xml", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "<loc>https://propertyquarry.com/</loc>" in response.text
    assert "<loc>https://propertyquarry.com/pricing</loc>" in response.text
    assert "<loc>https://propertyquarry.com/directory</loc>" not in response.text
    assert "directory.example" not in response.text


def test_brilliant_directories_sitemap_includes_configured_white_label_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    client = build_property_client(principal_id="pq-brilliant-directories-sitemap-ready")

    response = client.get("/sitemap.xml", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "<loc>https://propertyquarry.com/directory</loc>" in response.text
    assert "directory.example" not in response.text
    assert "bd-secret-token" not in response.text


def test_brilliant_directories_public_directory_page_renders_sanitized_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        request_url = str(getattr(request, "url", "") or "")
        if request_url == "https://directory.example/api/v2/user/get/24":
            return {
                "message": {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "profession": "Relocation",
                    "description": "Helps international renters prepare a Vienna search.",
                    "specialties": "relocation,renters",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            }
        assert request_url == "https://directory.example/api/v2/user/search"
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-public-ready")

    response = client.get(
        "/directory?keyword=relocation&city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    serialized = response.text
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in serialized
    assert response.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"
    assert "Vienna Relocation Advisors" in serialized
    assert "/directory/profile/24" in serialized
    assert "https://directory.example/austria/vienna/vienna-relocation-advisors" not in serialized
    assert "target=\"_blank\"" not in serialized
    assert "1 public profile shown" in serialized
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized

    profile_response = client.get("/directory/profile/24", headers={"host": "propertyquarry.com"})
    assert profile_response.status_code == 200
    assert "<title>Vienna Relocation Advisors | PropertyQuarry Directory</title>" in profile_response.text
    assert (
        '<meta name="description" content="Helps international renters prepare a Vienna search.">'
        in profile_response.text
    )
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in profile_response.text
    assert profile_response.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"
    assert "Vienna Relocation Advisors" in profile_response.text
    assert "Helps international renters prepare a Vienna search." in profile_response.text
    assert "Relocation" in profile_response.text
    assert "private@example.test" not in profile_response.text
    assert "+43 1 555" not in profile_response.text
    assert "Secret Street" not in profile_response.text
    assert "directory.example" not in profile_response.text
    assert "Brilliant Directories" not in profile_response.text


def test_brilliant_directories_public_directory_page_noindexes_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del request, timeout_seconds, opener
        return {"message": []}

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-public-empty")

    response = client.get("/directory?keyword=missing", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "No public profiles matched" in response.text
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in response.text
    assert response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"


def test_brilliant_directories_pricing_stays_propertyquarry_white_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-pricing")

    response = client.get("/pricing", headers={"host": "propertyquarry.com"}, follow_redirects=False)

    assert response.status_code == 200
    assert "Open search" in response.text
    assert "Create account" not in response.text
    assert "Open account, then activate from billing." not in response.text
    assert "directory.example" not in response.text
    assert "Brilliant Directories" not in response.text
    assert "brilliantdirectories" not in response.text.lower()


def test_brilliant_directories_script_writes_disabled_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR", str(tmp_path))

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_brilliant_directories_provider.py")],
        cwd=ROOT,
        env={**dict(os.environ), "PYTHONPATH": str(ROOT / "ea"), "PROPERTYQUARRY_SKIP_DOTENV": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    out_path = Path(completed.stdout.strip())
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["provider"] == "brilliant_directories"
    assert payload["status"] == "disabled"
    assert payload["live_network_called"] is False
    assert payload["verified_capabilities"]["form_encoded_request_contract"] is True
    assert payload["verified_capabilities"]["private_provider_contact_fields_stripped"] is True
    dns_handoff = out_path.with_name("BRILLIANT_DIRECTORIES_BILLING_DNS_HANDOFF.md")
    assert dns_handoff.is_file()
    dns_body = dns_handoff.read_text(encoding="utf-8")
    assert "PropertyQuarry Billing DNS Handoff" in dns_body
    assert "Gold remains blocked until the Brilliant Directories billing handoff host resolves." in dns_body


def test_brilliant_directories_script_writes_billing_dns_handoff_for_unresolved_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR", str(tmp_path))

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_brilliant_directories_provider.py")],
        cwd=ROOT,
        env={
            **dict(os.environ),
            "PYTHONPATH": str(ROOT / "ea"),
            "PROPERTYQUARRY_SKIP_DOTENV": "1",
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS": "billing-unresolved.propertyquarry.invalid",
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL": "https://billing-unresolved.propertyquarry.invalid/account",
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET": "members.brilliantdirectories.com",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    out_path = Path(completed.stdout.strip())
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    dns_body = out_path.with_name("BRILLIANT_DIRECTORIES_BILLING_DNS_HANDOFF.md").read_text(encoding="utf-8")
    assert payload["status"] == "blocked"
    assert "- Host: `billing-unresolved.propertyquarry.invalid`" in dns_body
    assert "- URL: `https://billing-unresolved.propertyquarry.invalid/account`" in dns_body
    assert "- Resolves now: `no`" in dns_body
    assert "- Required DNS record type: `CNAME`" in dns_body
    assert "- Required DNS target: `members.brilliantdirectories.com`" in dns_body
    assert "Do not enable `/app/billing` as an external redirect until this host resolves over HTTPS." in dns_body
