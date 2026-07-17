from __future__ import annotations

import json
import urllib.parse
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

import scripts.propertyquarry_rybbit_evidence as rybbit_evidence
from scripts.propertyquarry_rybbit_evidence import (
    MAX_RYBBIT_API_RESPONSE_BYTES,
    PROBE_EVENT_NAME,
    REQUIRED_PRIVACY_CHECKS,
    _collector_payload_privacy,
    _http_json,
    _request_payload_binds_event,
    _sha256_text,
    build_receipt,
    verify_receipt,
)


CANDIDATE_SHA = "a" * 40
PUBLIC_ORIGIN = "https://propertyquarry.com"
ANALYTICS_ORIGIN = "https://app.rybbit.io"
SITE_ID = "propertyquarry-production"
GENERATED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _api_provenance(digest_digit: str) -> dict[str, object]:
    request_digest = digest_digit * 64
    return {
        "response_sha256": request_digest,
        "response_size_bytes": 120,
        "response_limit_bytes": MAX_RYBBIT_API_RESPONSE_BYTES,
        "content_type": "application/json",
        "requested_url_origin": ANALYTICS_ORIGIN,
        "final_url_origin": ANALYTICS_ORIGIN,
        "requested_url_sha256": request_digest,
        "final_url_sha256": request_digest,
        "same_request_url": True,
        "redirected": False,
    }


def _valid_receipt() -> dict[str, object]:
    sent_at = GENERATED_AT - timedelta(seconds=5)
    observed_at = GENERATED_AT - timedelta(seconds=4)
    browser: dict[str, object] = {
        "script": {
            "url": f"{ANALYTICS_ORIGIN}/api/script.js",
            "status_code": 200,
            "sha256": "1" * 64,
            "size_bytes": 42_000,
            "site_id_bound": True,
        },
        "collector": {
            "url_origin": ANALYTICS_ORIGIN,
            "url_path": "/api/track",
            "url_sha256": "2" * 64,
            "method": "POST",
            "status_code": 204,
            "response_sha256": "3" * 64,
            "size_bytes": 0,
            "request_payload_sha256": "7" * 64,
            "request_payload_size_bytes": 74,
            "event_name_bound": True,
            "observed_at": observed_at.isoformat(),
        },
        "event": {
            "name": PROBE_EVENT_NAME,
            "sent_at": sent_at.isoformat(),
            "anonymous": True,
            "attribute_count": 0,
        },
        "privacy": {check: True for check in REQUIRED_PRIVACY_CHECKS},
    }
    api: dict[str, object] = {
        "auth": {"kind": "bearer_api_key", "secret_in_receipt": False},
        "site": {
            "status_code": 200,
            **_api_provenance("4"),
            "site_id_bound": True,
        },
        "has_data": {
            "status_code": 200,
            **_api_provenance("5"),
            "has_data": True,
        },
        "events": {
            "status_code": 200,
            **_api_provenance("6"),
            "event_name": PROBE_EVENT_NAME,
            "event_count": 1,
            "last_seen_at": observed_at.isoformat(),
            "observed_after_probe": True,
        },
    }
    return build_receipt(
        candidate_sha=CANDIDATE_SHA,
        public_origin=PUBLIC_ORIGIN,
        analytics_origin=ANALYTICS_ORIGIN,
        site_id=SITE_ID,
        browser=browser,
        api=api,
        generated_at=GENERATED_AT,
    )


def _verify(receipt: dict[str, object], *, now: datetime = GENERATED_AT) -> list[str]:
    return verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_public_origin=PUBLIC_ORIGIN,
        expected_analytics_origin=ANALYTICS_ORIGIN,
        expected_site_id_sha256=_sha256_text(SITE_ID),
        max_age_minutes=15,
        now=now,
    )


def test_rybbit_delivery_receipt_proves_browser_collector_and_authenticated_api_arrival() -> None:
    receipt = _valid_receipt()

    assert receipt["status"] == "pass"
    assert receipt["failures"] == []
    assert _verify(receipt) == []
    assert SITE_ID not in str(receipt)


def test_rybbit_event_timestamp_accepts_current_get_events_response_shape() -> None:
    observed_at = GENERATED_AT - timedelta(seconds=4)
    payload = {
        "data": [
            {
                "timestamp": observed_at.isoformat().replace("+00:00", "Z"),
                "type": "custom_event",
                "event_name": PROBE_EVENT_NAME,
            }
        ]
    }

    row = rybbit_evidence._event_record(payload, PROBE_EVENT_NAME)

    assert rybbit_evidence._event_timestamp(row) == observed_at


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        (("browser", "collector", "status_code", 500), "collector did not accept"),
        (("browser", "script", "size_bytes", 0), "script was not delivered"),
        (("api", "has_data", "has_data", False), "site has data"),
        (("api", "events", "event_count", 0), "did not prove arrival"),
        (("api", "site", "redirected", True), "URL provenance"),
        (("api", "events", "content_type", "text/html"), "bounds or content type"),
        (("browser", "collector", "url_path", "/api/other"), "URL or response digest"),
    ],
)
def test_rybbit_delivery_receipt_rejects_missing_delivery_or_dashboard_proof(
    mutation: tuple[str, str, str, object],
    expected_failure: str,
) -> None:
    receipt = _valid_receipt()
    section, row, field, value = mutation
    section_payload = receipt[section]
    assert isinstance(section_payload, dict)
    row_payload = section_payload[row]
    assert isinstance(row_payload, dict)
    row_payload[field] = value

    failures = _verify(receipt)

    assert any(expected_failure in failure for failure in failures)


def test_rybbit_delivery_receipt_rejects_candidate_mismatch() -> None:
    receipt = deepcopy(_valid_receipt())
    receipt["candidate_sha"] = "b" * 40

    assert "Rybbit receipt candidate SHA mismatch" in _verify(receipt)


def test_rybbit_delivery_receipt_rejects_stale_evidence() -> None:
    receipt = _valid_receipt()

    failures = _verify(receipt, now=GENERATED_AT + timedelta(minutes=16))

    assert "Rybbit receipt is stale" in failures


def test_rybbit_collector_payload_requires_exact_event_field_binding() -> None:
    assert _request_payload_binds_event(
        json.dumps({"eventName": PROBE_EVENT_NAME}).encode(),
        PROBE_EVENT_NAME,
    )
    assert _request_payload_binds_event(
        f"event_name={PROBE_EVENT_NAME}".encode(),
        PROBE_EVENT_NAME,
    )
    assert not _request_payload_binds_event(
        json.dumps({"message": PROBE_EVENT_NAME}).encode(),
        PROBE_EVENT_NAME,
    )
    assert not _request_payload_binds_event(
        json.dumps({"eventName": f"{PROBE_EVENT_NAME}_historical"}).encode(),
        PROBE_EVENT_NAME,
    )


def test_rybbit_collector_payload_derives_redacted_privacy_claims() -> None:
    payload = json.dumps(
        {
            "eventName": PROBE_EVENT_NAME,
            "eventData": {},
            "pathname": "/",
        }
    ).encode()

    privacy = _collector_payload_privacy(payload, PROBE_EVENT_NAME)

    assert privacy == {
        "collector_payload_parsed": True,
        "anonymous_event_no_attributes": True,
        "no_identify": True,
        "no_principal": True,
        "no_email": True,
        "no_private_candidate_listing_contact_fields": True,
        "no_custom_attributes": True,
    }
    assert PROBE_EVENT_NAME not in str(privacy)
    assert "/" not in str(privacy)


@pytest.mark.parametrize(
    ("private_fragment", "expected_claim"),
    [
        ({"principal_id": "private-principal"}, "no_principal"),
        ({"email": "person@example.test"}, "no_email"),
        ({"pathname": "/search/person@example.test"}, "no_email"),
        ({"type": "identify"}, "no_identify"),
        ({"candidate_ref": "candidate-private"}, "no_private_candidate_listing_contact_fields"),
        ({"listing_id": "listing-private"}, "no_private_candidate_listing_contact_fields"),
        ({"contact_phone": "+431234567"}, "no_private_candidate_listing_contact_fields"),
        ({"property_url": "https://portal.invalid/private"}, "no_private_candidate_listing_contact_fields"),
        ({"eventData": {"search": "private"}}, "no_custom_attributes"),
        ({"attributes": {"search": "private"}}, "no_custom_attributes"),
    ],
)
def test_rybbit_collector_payload_rejects_sensitive_fields_or_custom_attributes(
    private_fragment: dict[str, object],
    expected_claim: str,
) -> None:
    payload = json.dumps(
        {"eventName": PROBE_EVENT_NAME, **private_fragment}
    ).encode()

    privacy = _collector_payload_privacy(payload, PROBE_EVENT_NAME)

    assert privacy[expected_claim] is False
    assert privacy["anonymous_event_no_attributes"] is False
    assert "private-principal" not in str(privacy)
    assert "person@example.test" not in str(privacy)


def test_rybbit_collector_form_payload_inspects_nested_sensitive_fields() -> None:
    payload = urllib.parse.urlencode(
        {
            "event_name": PROBE_EVENT_NAME,
            "event_data": json.dumps({"contact_email": "person@example.test"}),
        }
    ).encode()

    privacy = _collector_payload_privacy(payload, PROBE_EVENT_NAME)

    assert privacy["collector_payload_parsed"] is True
    assert privacy["no_email"] is False
    assert privacy["no_private_candidate_listing_contact_fields"] is False
    assert privacy["no_custom_attributes"] is False
    assert privacy["anonymous_event_no_attributes"] is False


def test_rybbit_delivery_receipt_rejects_unbound_collector_payload() -> None:
    receipt = _valid_receipt()
    browser = receipt["browser"]
    assert isinstance(browser, dict)
    collector = browser["collector"]
    assert isinstance(collector, dict)
    collector["event_name_bound"] = False

    failures = _verify(receipt)

    assert any("not bound to the exact probe event" in failure for failure in failures)


@pytest.mark.parametrize("last_seen_at", ["", "2026-07-16T11:59:00+00:00"])
def test_rybbit_delivery_receipt_rejects_missing_or_historical_api_event(
    last_seen_at: str,
) -> None:
    receipt = _valid_receipt()
    api = receipt["api"]
    assert isinstance(api, dict)
    events = api["events"]
    assert isinstance(events, dict)
    events["last_seen_at"] = last_seen_at
    events["observed_after_probe"] = True

    failures = _verify(receipt)

    assert any("did not prove arrival" in failure for failure in failures)


@pytest.mark.parametrize("max_age_minutes", [float("nan"), float("inf"), float("-inf")])
def test_rybbit_delivery_receipt_rejects_nonfinite_age_policy(max_age_minutes: float) -> None:
    receipt = _valid_receipt()

    failures = verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_public_origin=PUBLIC_ORIGIN,
        expected_analytics_origin=ANALYTICS_ORIGIN,
        expected_site_id_sha256=_sha256_text(SITE_ID),
        max_age_minutes=max_age_minutes,
        now=GENERATED_AT,
    )

    assert "Rybbit receipt maximum age policy is invalid" in failures


@pytest.mark.parametrize(
    ("public_origin", "analytics_origin", "expected_failure"),
    [
        ("http://propertyquarry.com", ANALYTICS_ORIGIN, "public origin mismatch"),
        (PUBLIC_ORIGIN, "http://app.rybbit.io", "analytics origin mismatch"),
    ],
)
def test_rybbit_delivery_receipt_rejects_http_protected_origins(
    public_origin: str,
    analytics_origin: str,
    expected_failure: str,
) -> None:
    receipt = _valid_receipt()

    failures = verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_public_origin=public_origin,
        expected_analytics_origin=analytics_origin,
        expected_site_id_sha256=_sha256_text(SITE_ID),
        max_age_minutes=15,
        now=GENERATED_AT,
    )

    assert any(expected_failure in failure for failure in failures)


class _FakeResponse:
    def __init__(
        self,
        *,
        body: bytes = b'{"ok":true}',
        content_type: str = "application/json",
        final_url: str = f"{ANALYTICS_ORIGIN}/api/events",
    ) -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._body = body
        self._final_url = final_url

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.authorization = ""

    def open(self, request, *, timeout: float):  # type: ignore[no-untyped-def]
        assert timeout == 3.0
        self.authorization = str(request.get_header("Authorization") or "")
        return self.response


def _fake_http(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _FakeOpener:
    opener = _FakeOpener(response)
    handlers: list[object] = []

    def _build_opener(*values: object) -> _FakeOpener:
        handlers.extend(values)
        return opener

    monkeypatch.setattr(rybbit_evidence.urllib.request, "build_opener", _build_opener)
    status, payload, metadata = _http_json(
        url=f"{ANALYTICS_ORIGIN}/api/events",
        expected_origin=ANALYTICS_ORIGIN,
        api_key="test-key",
        timeout_seconds=3.0,
    )
    assert status == 200
    assert payload == {"ok": True}
    assert metadata["same_request_url"] is True
    assert opener.authorization == "Bearer test-key"
    assert len(handlers) == 1
    assert handlers[0].redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.invalid") is None  # type: ignore[attr-defined]
    return opener


def test_rybbit_api_probe_uses_no_redirect_handler_and_retains_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_http(monkeypatch, _FakeResponse())


@pytest.mark.parametrize(
    ("response", "expected_failure"),
    [
        (
            _FakeResponse(final_url="https://elsewhere.invalid/api/events"),
            "final URL differs",
        ),
        (
            _FakeResponse(content_type="text/html"),
            "content type is not JSON",
        ),
    ],
)
def test_rybbit_api_probe_rejects_changed_final_url_or_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse,
    expected_failure: str,
) -> None:
    opener = _FakeOpener(response)
    monkeypatch.setattr(
        rybbit_evidence.urllib.request,
        "build_opener",
        lambda *handlers: opener,
    )

    with pytest.raises(ValueError, match=expected_failure):
        _http_json(
            url=f"{ANALYTICS_ORIGIN}/api/events",
            expected_origin=ANALYTICS_ORIGIN,
            api_key="test-key",
            timeout_seconds=3.0,
        )


def test_rybbit_api_probe_reads_max_plus_one_and_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rybbit_evidence, "MAX_RYBBIT_API_RESPONSE_BYTES", 8)
    opener = _FakeOpener(_FakeResponse(body=b"123456789"))
    monkeypatch.setattr(
        rybbit_evidence.urllib.request,
        "build_opener",
        lambda *handlers: opener,
    )

    with pytest.raises(ValueError, match="exceeds the bounded"):
        _http_json(
            url=f"{ANALYTICS_ORIGIN}/api/events",
            expected_origin=ANALYTICS_ORIGIN,
            api_key="test-key",
            timeout_seconds=3.0,
        )
