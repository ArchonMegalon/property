from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import yaml

from app.product import service as product_service
from app.services import property_governed_render as governed
from app.services.scene_video_contract import resolve_property_walkthrough_runtime_provider


_ENDPOINT = (
    "https://run-services.internal.example/"
    "api/internal/propertyquarry/apartment-videos/artifact-requests"
)
_ORIGIN = "https://run-services.internal.example"
_SIGNING_SECRET = "governed-consent-test-secret-with-more-than-32-bytes"
_API_TOKEN = "governed-render-api-token-with-more-than-32-bytes"


def _configure_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_API_URL", _ENDPOINT)
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_ALLOWED_ORIGIN", _ORIGIN)
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN", _API_TOKEN)
    monkeypatch.setenv(
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET",
        _SIGNING_SECRET,
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_STORE_DIR",
        str(tmp_path / "governed-consents"),
    )
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_LOCALE", "en-US")


def _issued_request(
    *,
    principal_id: str = "customer@example.test",
    property_slug: str = "vienna-family-home",
    property_id: str = "vienna-family-home",
    provider_key: str = "magicfit",
    locale: str = "de-AT",
    tour_revision: str = "",
) -> dict[str, object]:
    revision = tour_revision or hashlib.sha256(
        f"{property_slug}:server-publication-v1".encode("utf-8")
    ).hexdigest()
    work_item_id = governed.governed_property_video_work_item_id(
        slug=property_slug,
        provider_key=provider_key,
        tour_revision=revision,
    )
    receipt, error = governed.issue_governed_render_consent_receipt(
        granted=True,
        principal_id=principal_id,
        property_slug=property_slug,
        property_id=property_id,
        tour_revision=revision,
        provider_key=provider_key,
        work_item_id=work_item_id,
        locale=locale,
    )
    assert error == ""
    assert receipt.startswith("pqc2.")
    return {
        "slug": property_slug,
        "title": "Kärntner Straße 1, 1010 Wien",
        "principal_id": principal_id,
        "actor": "property.visual.request",
        "preferred_provider_key": provider_key,
        "property_id": property_id,
        "tour_revision": revision,
        "locale": locale,
        "external_processing_consent_receipt": receipt,
    }


def _accepted_response(body: dict[str, object]) -> SimpleNamespace:
    source_ref = (
        "propertyquarry:apartment-video:"
        f"{body['propertyId']}:{body['workItemId']}"
    )
    receipt = {
        "requestId": "horizon-artifact-0123456789abcdef",
        "status": "accepted",
        "horizonId": "propertyquarry",
        "capabilityId": governed.PROPERTY_APARTMENT_VIDEO_CAPABILITY,
        "sourceRef": source_ref,
        "requestedByUserId": body["userId"],
        "visibility": "private",
        "externalProcessingConsent": True,
        "blockedReasons": [],
        "quotaTracked": True,
        "quota": {"remaining": 2},
        "governedRenderRequest": {
            "contractName": governed.GOVERNED_RENDER_CONTRACT,
            "contractVersion": governed.GOVERNED_RENDER_CONTRACT_VERSION,
            "orchestrationLane": governed.GOVERNED_RENDER_LANE,
            "horizonId": "propertyquarry",
            "capabilityId": governed.PROPERTY_APARTMENT_VIDEO_CAPABILITY,
            "sourceRef": source_ref,
            "workItemId": body["workItemId"],
            "requestedBy": body["requestedBy"],
            "subject": body["subject"],
            "audience": body["audience"],
            "locale": body["locale"],
            "preferredProvider": body["preferredProvider"],
            "truthRefs": body["truthRefs"],
            "evidenceRefs": body["evidenceRefs"],
            "artifacts": body["artifacts"],
        },
    }
    return SimpleNamespace(
        status_code=200,
        content=json.dumps(
            {
                "payload": {"consumeQuota": True},
                "artifactRequestReceipt": receipt,
            }
        ).encode("utf-8"),
    )


def test_governed_property_video_readiness_ignores_generic_and_provider_credentials(
    monkeypatch,
) -> None:
    for name in (
        "PROPERTYQUARRY_GOVERNED_RENDER_API_URL",
        "PROPERTYQUARRY_GOVERNED_RENDER_ALLOWED_ORIGIN",
        "PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN",
        "PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN_FILE",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET_FILE",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_STORE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EA_GOVERNED_RENDER_API_TOKEN", "must-not-authorize")
    monkeypatch.setenv("FLEET_INTERNAL_API_TOKEN", "must-not-authorize")
    monkeypatch.setenv("EA_SIGNING_SECRET", "must-not-sign-governed-consent")
    monkeypatch.setenv("MAGICFIT_EMAIL", "provider@example.test")
    monkeypatch.setenv("MAGICFIT_PASSWORD", "must-not-authorize-web-runtime")

    readiness = governed.governed_property_video_runtime_readiness()

    assert readiness["ready"] is False
    assert readiness["execution_lane"] == "ea_governed_render"
    assert readiness["checks"]["provider_execution_in_web_process"] is False
    assert readiness["checks"]["one_time_transactional_consumption"] is True
    assert readiness["blockers"] == [
        "governed_render_endpoint_missing",
        "governed_render_allowed_origin_missing",
        "governed_render_internal_token_missing",
        "governed_render_consent_signing_secret_missing",
        "governed_render_consent_store_missing",
    ]


def test_governed_property_video_readiness_requires_exact_allowlisted_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PROPERTYQUARRY_GOVERNED_RENDER_API_URL",
        "https://attacker.example/api/internal/propertyquarry/apartment-videos/artifact-requests",
    )

    readiness = governed.governed_property_video_runtime_readiness()

    assert readiness["ready"] is False
    assert "governed_render_endpoint_invalid" in readiness["blockers"]
    assert readiness["checks"]["endpoint_origin_allowlisted"] is False


def test_governed_property_video_readiness_rejects_weak_dedicated_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN", "too-short")

    readiness = governed.governed_property_video_runtime_readiness()

    assert readiness["ready"] is False
    assert "governed_render_internal_token_missing" in readiness["blockers"]


def test_governed_property_video_readiness_rejects_invalid_locale(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_LOCALE", "not_a_locale")

    readiness = governed.governed_property_video_runtime_readiness()

    assert readiness["ready"] is False
    assert "governed_render_locale_invalid" in readiness["blockers"]
    assert readiness["checks"]["locale_configured"] is False


def test_governed_consent_readiness_rejects_dangling_store_symlinks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    store_root = tmp_path / "governed-consents"
    store_root.symlink_to(tmp_path / "missing-store", target_is_directory=True)
    root_readiness = governed.governed_property_video_runtime_readiness()
    assert root_readiness["ready"] is False
    assert "governed_render_consent_store_invalid" in root_readiness["blockers"]

    store_root.unlink()
    store_root.mkdir(mode=0o700)
    (store_root / "consent-receipts.sqlite3").symlink_to(
        tmp_path / "missing-database"
    )
    database_readiness = governed.governed_property_video_runtime_readiness()
    assert database_readiness["ready"] is False
    assert "governed_render_consent_store_invalid" in database_readiness["blockers"]


def test_governed_property_video_readiness_rejects_corrupt_consent_store(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    store = tmp_path / "governed-consents"
    store.mkdir()
    (store / "consent-receipts.sqlite3").write_bytes(b"not-a-sqlite-database")

    readiness = governed.governed_property_video_runtime_readiness()

    assert readiness["ready"] is False
    assert "governed_render_consent_store_invalid" in readiness["blockers"]


def test_governed_consent_issuer_rejects_store_symlink_without_chmod_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    target = tmp_path / "must-not-be-mutated"
    target.mkdir(mode=0o755)
    store = tmp_path / "governed-consents"
    store.symlink_to(target, target_is_directory=True)
    before_mode = target.stat().st_mode & 0o777
    revision = hashlib.sha256(b"server-revision").hexdigest()
    work_item_id = governed.governed_property_video_work_item_id(
        slug="vienna-family-home",
        provider_key="magicfit",
        tour_revision=revision,
    )

    receipt, error = governed.issue_governed_render_consent_receipt(
        granted=True,
        principal_id="subject-1",
        property_slug="vienna-family-home",
        property_id="vienna-family-home",
        tour_revision=revision,
        provider_key="magicfit",
        work_item_id=work_item_id,
        locale="en-US",
    )

    assert receipt == ""
    assert error == "governed_render_consent_store_failed"
    assert target.stat().st_mode & 0o777 == before_mode
    assert list(target.iterdir()) == []


def test_governed_property_video_request_is_private_server_bound_and_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    observed: dict[str, object] = {}

    def _post(url: str, **kwargs: object) -> SimpleNamespace:
        observed["url"] = url
        observed.update(kwargs)
        return _accepted_response(dict(kwargs["json"]))

    request = _issued_request()
    opaque_receipt = str(request["external_processing_consent_receipt"])
    result = governed.submit_governed_property_video_request(**request, post=_post)

    assert result.status == "pending"
    assert result.request_id == "horizon-artifact-0123456789abcdef"
    assert result.as_dict()["video_url"] == ""
    assert result.as_dict()["public_ready"] is False
    body = dict(observed["json"])
    assert observed["url"] == _ENDPOINT
    assert body["propertyId"] == "vienna-family-home"
    assert body["locale"] == "de-AT"
    assert body["visibility"] == "private"
    assert body["externalProcessingConsent"] is True
    assert body["consumeQuota"] is True
    artifact = dict(list(body["artifacts"])[0])
    artifact_payload = json.loads(str(artifact["payload"]))
    assert artifact_payload["property_slug"] == "vienna-family-home"
    versioned_packet_ref = (
        "propertyquarry:property-packet:vienna-family-home:revision:"
        f"{request['tour_revision']}"
    )
    assert artifact_payload["prompt_ref"] == versioned_packet_ref
    assert versioned_packet_ref in body["truthRefs"]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "customer@example.test" not in serialized
    assert "Kärntner Straße" not in serialized
    assert opaque_receipt not in serialized
    assert governed.EXTERNAL_PROCESSING_CONSENT_VERSION not in serialized
    assert f"propertyquarry:tour-revision:{request['tour_revision']}" in body["evidenceRefs"]
    assert any(
        str(value).startswith("propertyquarry:external-processing-consent:")
        for value in body["evidenceRefs"]
    )
    assert dict(observed["headers"])["Authorization"] == f"Bearer {_API_TOKEN}"
    assert observed["allow_redirects"] is False
    assert observed["stream"] is True


def test_governed_property_video_does_not_use_ambient_proxy_or_netrc_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy-attacker.example")
    observed: dict[str, object] = {"closed": False}

    class _Session:
        trust_env = True

        def post(self, url: str, **kwargs: object) -> SimpleNamespace:
            observed["trust_env"] = self.trust_env
            observed["url"] = url
            return _accepted_response(dict(kwargs["json"]))

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(governed.requests, "Session", _Session)

    result = governed.submit_governed_property_video_request(**_issued_request())

    assert result.status == "pending"
    assert observed == {
        "closed": True,
        "trust_env": False,
        "url": _ENDPOINT,
    }


def test_governed_property_video_requires_principal_and_stable_provider() -> None:
    missing_principal = governed.submit_governed_property_video_request(
        slug="vienna-family-home",
        title="Vienna family home",
        principal_id="",
        actor="property.visual.request",
        post=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("request must not be sent")
        ),
    )
    invalid_provider = governed.submit_governed_property_video_request(
        slug="vienna-family-home",
        title="Vienna family home",
        principal_id="subject-1",
        actor="property.visual.request",
        preferred_provider_key="magicfit\r\nX-Injected: true",
        post=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("request must not be sent")
        ),
    )

    assert missing_principal.reason == "governed_render_principal_missing"
    assert invalid_provider.reason == "governed_render_provider_invalid"


def test_governed_property_video_rejects_forgery_before_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    request = _issued_request(principal_id="subject-1")
    token = str(request["external_processing_consent_receipt"])
    prefix, encoded_payload, signature = token.split(".")
    payload = json.loads(
        base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
    )
    payload["property_id"] = "forged-property"
    forged_payload = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    request["external_processing_consent_receipt"] = f"{prefix}.{forged_payload}.{signature}"
    network_calls: list[object] = []

    result = governed.submit_governed_property_video_request(
        **request,
        post=lambda *args, **kwargs: network_calls.append((args, kwargs)),
    )

    assert result.status == "blocked"
    assert result.reason == "governed_render_external_processing_consent_invalid"
    assert network_calls == []


def test_governed_property_video_rejects_cross_tenant_and_property_binding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    request = _issued_request(principal_id="subject-1")
    network_calls: list[object] = []
    mismatches = {
        "principal_id": "subject-2",
        "slug": "another-owned-tour",
        "property_id": "another-property",
        "tour_revision": hashlib.sha256(b"different-revision").hexdigest(),
        "preferred_provider_key": "omagic",
        "locale": "en-US",
    }
    for field, value in mismatches.items():
        mutated = {**request, field: value}
        result = governed.submit_governed_property_video_request(
            **mutated,
            post=lambda *args, **kwargs: network_calls.append((args, kwargs)),
        )

        assert result.status == "blocked"
        assert result.reason == "governed_render_external_processing_consent_binding_mismatch"
    assert network_calls == []


def test_governed_property_video_receipt_is_one_time_and_replay_fails_before_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    request = _issued_request(principal_id="subject-1")
    calls: list[object] = []

    def _post(_url: str, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return _accepted_response(dict(kwargs["json"]))

    first = governed.submit_governed_property_video_request(**request, post=_post)
    replay = governed.submit_governed_property_video_request(**request, post=_post)

    assert first.status == "pending"
    assert replay.status == "blocked"
    assert replay.reason == "governed_render_external_processing_consent_replayed"
    assert len(calls) == 1


def test_governed_consent_issuer_refuses_fresh_receipt_for_same_bound_work(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    request = _issued_request(principal_id="subject-no-reissue")
    first = governed.submit_governed_property_video_request(
        **request,
        post=lambda _url, **kwargs: _accepted_response(dict(kwargs["json"])),
    )
    work_item_id = governed.governed_property_video_work_item_id(
        slug=str(request["slug"]),
        provider_key=str(request["preferred_provider_key"]),
        tour_revision=str(request["tour_revision"]),
    )
    replacement, error = governed.issue_governed_render_consent_receipt(
        granted=True,
        principal_id=str(request["principal_id"]),
        property_slug=str(request["slug"]),
        property_id=str(request["property_id"]),
        tour_revision=str(request["tour_revision"]),
        provider_key=str(request["preferred_provider_key"]),
        work_item_id=work_item_id,
        locale=str(request["locale"]),
    )

    assert first.status == "pending"
    assert replacement == ""
    assert error == "governed_render_external_processing_consent_already_issued"


def test_governed_consent_same_binding_recovers_after_receipt_lease_expires(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    revision = hashlib.sha256(b"recoverable-bound-work").hexdigest()
    work_item_id = governed.governed_property_video_work_item_id(
        slug="recoverable-home",
        provider_key="magicfit",
        tour_revision=revision,
    )
    issued_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    arguments = {
        "granted": True,
        "principal_id": "recoverable-subject",
        "property_slug": "recoverable-home",
        "property_id": "recoverable-home",
        "tour_revision": revision,
        "provider_key": "magicfit",
        "work_item_id": work_item_id,
        "locale": "en-US",
    }

    first, first_error = governed.issue_governed_render_consent_receipt(
        **arguments,
        now=issued_at,
    )
    replacement, replacement_error = governed.issue_governed_render_consent_receipt(
        **arguments,
        now=issued_at + timedelta(minutes=15, seconds=1),
    )

    assert first_error == ""
    assert replacement_error == ""
    assert replacement and replacement != first


def test_governed_consent_legacy_schema_migrates_once_under_concurrent_issuers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    store_root = tmp_path / "governed-consents"
    store_root.mkdir(mode=0o700)
    database_path = store_root / "consent-receipts.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE governed_render_consents ("
        "consent_id TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, "
        "expires_at INTEGER NOT NULL, state TEXT NOT NULL, consumed_at INTEGER)"
    )
    connection.commit()
    connection.close()
    database_path.chmod(0o600)
    revision = hashlib.sha256(b"legacy-concurrent-work").hexdigest()
    work_item_id = governed.governed_property_video_work_item_id(
        slug="legacy-home",
        provider_key="magicfit",
        tour_revision=revision,
    )

    def issue(_index: int) -> tuple[str, str]:
        return governed.issue_governed_render_consent_receipt(
            granted=True,
            principal_id="legacy-owner",
            property_slug="legacy-home",
            property_id="legacy-home",
            tour_revision=revision,
            provider_key="magicfit",
            work_item_id=work_item_id,
            locale="en-US",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(issue, range(8)))

    assert sum(bool(token) for token, _error in results) == 1
    assert sorted(error for token, error in results if not token) == [
        "governed_render_external_processing_consent_already_issued"
    ] * 7


def test_governed_consent_sqlite_connection_is_anchored_against_path_swap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    _issued_request(property_slug="anchor-initial-home")
    store_root = tmp_path / "governed-consents"
    database_path = store_root / "consent-receipts.sqlite3"
    validated_inode_path = store_root / "validated-inode.sqlite3"
    attacker_path = tmp_path / "attacker.sqlite3"
    attacker_connection = sqlite3.connect(attacker_path)
    attacker_connection.execute("CREATE TABLE attacker_marker(value TEXT)")
    attacker_connection.commit()
    attacker_connection.close()
    original_connect = sqlite3.connect
    swapped = False

    def swap_after_descriptor_open(database: object, *args: object, **kwargs: object):
        nonlocal swapped
        if not swapped and str(database).startswith("/proc/self/fd/"):
            database_path.rename(validated_inode_path)
            database_path.symlink_to(attacker_path)
            swapped = True
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        "app.services.property_governed_consent.sqlite3.connect",
        swap_after_descriptor_open,
    )
    request = _issued_request(property_slug="anchor-second-home")

    assert request["external_processing_consent_receipt"]
    assert swapped is True
    target_connection = original_connect(attacker_path)
    target_tables = {
        row[0]
        for row in target_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    target_connection.close()
    assert target_tables == {"attacker_marker"}


def test_governed_property_video_rejects_untrusted_receipt_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)

    def _post(_url: str, **kwargs: object) -> SimpleNamespace:
        response = _accepted_response(dict(kwargs["json"]))
        payload = json.loads(response.content)
        payload["artifactRequestReceipt"]["governedRenderRequest"]["orchestrationLane"] = "direct_provider"
        response.content = json.dumps(payload).encode("utf-8")
        return response

    result = governed.submit_governed_property_video_request(
        **_issued_request(principal_id="subject-1"),
        post=_post,
    )

    assert result.status == "blocked"
    assert result.reason == "governed_render_receipt_invalid"


def test_governed_property_video_rejects_context_added_by_bridge(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)

    def _post(_url: str, **kwargs: object) -> SimpleNamespace:
        response = _accepted_response(dict(kwargs["json"]))
        payload = json.loads(response.content)
        payload["artifactRequestReceipt"]["governedRenderRequest"]["evidenceRefs"].append(
            "propertyquarry:other-tenant:injected"
        )
        response.content = json.dumps(payload).encode("utf-8")
        return response

    result = governed.submit_governed_property_video_request(
        **_issued_request(principal_id="subject-1"),
        post=_post,
    )

    assert result.status == "blocked"
    assert result.reason == "governed_render_receipt_invalid"


def test_governed_property_video_rejects_ambiguous_bridge_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    for index, content in enumerate((
        b'{"payload":{"consumeQuota":true,"consumeQuota":false}}',
        b'{"payload":{"consumeQuota":NaN}}',
    )):
        result = governed.submit_governed_property_video_request(
            **_issued_request(
                principal_id="subject-1",
                tour_revision=hashlib.sha256(
                    f"ambiguous-bridge-{index}".encode("utf-8")
                ).hexdigest(),
            ),
            post=lambda _url, **_kwargs: SimpleNamespace(
                status_code=200,
                content=content,
            ),
        )

        assert result.status == "blocked"
        assert result.reason == "governed_render_request_failed"


def test_governed_property_video_projects_receipt_allowlist_without_bridge_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    expected_receipt_sha256 = ""

    def _post(_url: str, **kwargs: object) -> SimpleNamespace:
        nonlocal expected_receipt_sha256
        response = _accepted_response(dict(kwargs["json"]))
        payload = json.loads(response.content)
        receipt = payload["artifactRequestReceipt"]
        receipt["providerCredential"] = "bridge-secret-token"
        receipt["otherCustomerPayload"] = {"email": "other-customer@example.test"}
        receipt["quota"]["internalBillingSecret"] = "billing-secret"
        receipt["governedRenderRequest"]["providerResponse"] = {
            "rawProviderId": "private-provider-id"
        }
        payload["payload"]["internalBridgeSecret"] = "payload-secret"
        expected_receipt_sha256 = hashlib.sha256(
            json.dumps(
                receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        response.content = json.dumps(payload).encode("utf-8")
        return response

    result = governed.submit_governed_property_video_request(
        **_issued_request(principal_id="subject-1"),
        post=_post,
    )

    assert result.status == "pending"
    receipt = dict(result.as_dict()["governed_render_receipt"])
    assert set(receipt) == {
        "request_id",
        "status",
        "contract_name",
        "contract_version",
        "horizon_id",
        "capability_id",
        "orchestration_lane",
        "visibility",
        "quota_tracked",
        "consume_quota",
        "artifact_ids",
        "receipt_sha256",
    }
    assert receipt["artifact_ids"] == ["walkthrough"]
    assert receipt["receipt_sha256"] == expected_receipt_sha256
    serialized = json.dumps(result.as_dict())
    for forbidden in (
        "sourceRef",
        "workItemId",
        "preferredProvider",
        "bridge-secret-token",
        "other-customer@example.test",
        "billing-secret",
        "private-provider-id",
        "payload-secret",
    ):
        assert forbidden not in serialized


def test_property_walkthrough_runtime_resolution_uses_complete_governed_lane(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    monkeypatch.delenv("MAGICFIT_EMAIL", raising=False)
    monkeypatch.delenv("MAGICFIT_PASSWORD", raising=False)

    resolution = resolve_property_walkthrough_runtime_provider("magicfit")

    readiness = dict(resolution["runtime_readiness_json"])
    assert resolution["selected_via"] == "governed_render_explicit"
    assert readiness["ready"] is True
    assert readiness["execution_lane"] == "ea_governed_render"
    assert readiness["checks"]["server_issued_consent_enabled"] is True
    assert readiness["checks"]["provider_execution_in_web_process"] is False


def _owned_bundle(tmp_path: Path, *, slug: str, owner: str) -> Path:
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps({"slug": slug, "scene_count": 2, "locale": "attacker-locale"}),
        encoding="utf-8",
    )
    (bundle_dir / "tour.private.json").write_text(
        json.dumps({"principal_id": owner, "property_url": "https://listing.example/1"}),
        encoding="utf-8",
    )
    return bundle_dir


def test_customer_property_render_derives_owned_identity_and_revision_under_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    slug = "governed-customer-home"
    bundle_dir = _owned_bundle(tmp_path, slug=slug, owner="customer-1")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_LOCALE", "de-AT")
    issued: dict[str, object] = {}
    submitted: dict[str, object] = {}

    def _issue(**kwargs: object) -> tuple[str, str]:
        issued.update(kwargs)
        return "server-issued-opaque-receipt", ""

    def _submit(**kwargs: object) -> governed.GovernedPropertyVideoRequestResult:
        submitted.update(kwargs)
        return governed.GovernedPropertyVideoRequestResult(
            status="pending",
            reason="governed_render_request_accepted",
            request_id="horizon-artifact-fedcba9876543210",
            provider_key="magicfit",
            receipt={"status": "accepted"},
        )

    monkeypatch.setattr(governed, "issue_governed_render_consent_receipt", _issue)
    monkeypatch.setattr(governed, "submit_governed_property_video_request", _submit)
    monkeypatch.setattr(
        product_service.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider subprocess must not run")
        ),
    )

    consent_receipt, consent_error = (
        product_service._issue_owned_governed_property_flythrough_consent(
            tour_url=f"https://propertyquarry.com/tours/{slug}",
            principal_id="customer-1",
            preferred_provider_key="magicfit",
            external_processing_consent_granted=True,
        )
    )
    assert consent_error == ""
    result = product_service._render_property_flythrough_into_hosted_tour(
        tour_url=f"https://propertyquarry.com/tours/{slug}",
        title="Governed customer home",
        principal_id="customer-1",
        actor="property.visual.request",
        property_facts={"private_exact_address": "must not be sent"},
        preferred_provider_key="magicfit",
        tour_context_json={
            "governed_render_property_id": "forged-property",
            "tour_revision": "forged-revision",
            "locale": "forged-locale",
        },
        external_processing_consent_receipt=consent_receipt,
    )

    expected_manifest = {"slug": slug, "scene_count": 2, "locale": "attacker-locale"}
    public_digest = hashlib.sha256(
        json.dumps(
            expected_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    private_digest = hashlib.sha256(
        json.dumps(
            {
                "principal_id": "customer-1",
                "property_url": "https://listing.example/1",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    expected_revision = hashlib.sha256(
        json.dumps(
            {
                "private_packet_sha256": private_digest,
                "public_manifest_sha256": public_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert result["status"] == "pending"
    assert result["execution_lane"] == "ea_governed_render"
    assert issued["principal_id"] == "customer-1"
    assert issued["property_id"] == slug
    assert issued["tour_revision"] == expected_revision
    assert issued["locale"] == "de-AT"
    assert submitted["property_id"] == slug
    assert submitted["tour_revision"] == expected_revision
    assert submitted["locale"] == "de-AT"
    assert submitted["external_processing_consent_receipt"] == "server-issued-opaque-receipt"
    assert "tour_context_json" not in submitted
    assert "property_facts" not in submitted
    progress = json.loads(
        (bundle_dir / "tour.walkthrough.progress.json").read_text(encoding="utf-8")
    )
    assert progress["status"] == "pending"
    assert progress["provider_key"] == "governed_render"


def test_customer_property_render_rejects_cross_tenant_before_issuing_consent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    slug = "governed-customer-home"
    _owned_bundle(tmp_path, slug=slug, owner="customer-1")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setattr(
        governed,
        "issue_governed_render_consent_receipt",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cross-tenant request must not issue consent")
        ),
    )

    consent_receipt, consent_error = (
        product_service._issue_owned_governed_property_flythrough_consent(
            tour_url=f"https://propertyquarry.com/tours/{slug}",
            principal_id="customer-2",
            preferred_provider_key="magicfit",
            external_processing_consent_granted=True,
        )
    )
    assert consent_receipt == ""
    assert consent_error == "governed_render_property_owner_mismatch"
    result = product_service._render_property_flythrough_into_hosted_tour(
        tour_url=f"https://propertyquarry.com/tours/{slug}",
        title="Another customer's home",
        principal_id="customer-2",
        actor="property.visual.request",
        external_processing_consent_receipt="forged-opaque-receipt",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "governed_render_property_owner_mismatch"


def test_customer_property_consent_rejects_private_packet_context_substitution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_runtime(monkeypatch, tmp_path)
    slug = "private-context-home"
    bundle_dir = _owned_bundle(tmp_path, slug=slug, owner="customer-1")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    first_binding, first_error = (
        product_service._owned_governed_property_flythrough_binding(
            tour_url=f"https://propertyquarry.com/tours/{slug}",
            principal_id="customer-1",
            preferred_provider_key="magicfit",
        )
    )
    assert first_error == ""
    receipt, receipt_error = governed.issue_governed_render_consent_receipt(
        granted=True,
        principal_id=first_binding["principal_id"],
        property_slug=first_binding["slug"],
        property_id=first_binding["property_id"],
        tour_revision=first_binding["tour_revision"],
        provider_key=first_binding["provider_key"],
        work_item_id=first_binding["work_item_id"],
        locale=first_binding["locale"],
    )
    assert receipt_error == ""
    (bundle_dir / "tour.private.json").write_text(
        json.dumps(
            {
                "principal_id": "customer-1",
                "property_url": "https://listing.example/substituted",
            }
        ),
        encoding="utf-8",
    )
    second_binding, second_error = (
        product_service._owned_governed_property_flythrough_binding(
            tour_url=f"https://propertyquarry.com/tours/{slug}",
            principal_id="customer-1",
            preferred_provider_key="magicfit",
        )
    )
    network_calls: list[object] = []
    result = governed.submit_governed_property_video_request(
        slug=second_binding["slug"],
        title="Substituted context",
        principal_id=second_binding["principal_id"],
        actor="property.visual.request",
        preferred_provider_key=second_binding["provider_key"],
        property_id=second_binding["property_id"],
        tour_revision=second_binding["tour_revision"],
        locale=second_binding["locale"],
        external_processing_consent_receipt=receipt,
        post=lambda *args, **kwargs: network_calls.append((args, kwargs)),
    )

    assert second_error == ""
    assert second_binding["tour_revision"] != first_binding["tour_revision"]
    assert result.status == "blocked"
    assert result.reason == "governed_render_external_processing_consent_binding_mismatch"
    assert network_calls == []


def test_live_product_consent_receipt_bypasses_persisted_task_input(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    service = SimpleNamespace(
        _record_product_event=lambda **_kwargs: None,
        _run_scene_video_skill=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("one-time consent receipt must not enter task input")
        ),
    )
    monkeypatch.setattr(
        product_service,
        "_property_walkthrough_scene_video_context",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        product_service,
        "_hosted_property_tour_video_delivery",
        lambda _tour_url: {},
    )
    monkeypatch.setattr(
        "app.services.scene_video_contract.resolve_property_walkthrough_runtime_provider",
        lambda _provider: {
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "runtime_readiness_json": {
                "ready": True,
                "status": "ready",
                "blockers": [],
            },
        },
    )
    monkeypatch.setattr(
        product_service,
        "_issue_owned_governed_property_flythrough_consent",
        lambda **_kwargs: ("opaque-one-time-receipt", ""),
    )

    def direct_render(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "pending",
            "provider_key": "magicfit",
            "execution_lane": "ea_governed_render",
        }

    monkeypatch.setattr(
        product_service,
        "_render_property_flythrough_into_hosted_tour",
        direct_render,
    )
    result = product_service.ProductService._maybe_render_property_scout_flythrough(
        service,
        principal_id="customer-1",
        actor="property.visual.request",
        title="Private walkthrough",
        property_url="https://listing.example/1",
        source_ref="listing:1",
        tour_result={"tour_url": "https://property.example/tours/private-home"},
        property_facts={},
        fit_score=100,
        allow_below_threshold=True,
        walkthrough_provider_key="magicfit",
        external_processing_consent_granted=True,
    )

    assert result["status"] == "pending"
    assert captured["external_processing_consent_receipt"] == "opaque-one-time-receipt"
    assert "input_json" not in captured


def test_customer_property_render_requires_explicit_authenticated_grant(
    monkeypatch,
    tmp_path: Path,
) -> None:
    slug = "governed-customer-home"
    _owned_bundle(tmp_path, slug=slug, owner="customer-1")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_GOVERNED_RENDER_LOCALE", "en-US")

    consent_receipt, consent_error = (
        product_service._issue_owned_governed_property_flythrough_consent(
            tour_url=f"https://propertyquarry.com/tours/{slug}",
            principal_id="customer-1",
            preferred_provider_key="magicfit",
            external_processing_consent_granted=False,
        )
    )
    assert consent_receipt == ""
    assert consent_error == "governed_render_external_processing_consent_not_granted"
    result = product_service._render_property_flythrough_into_hosted_tour(
        tour_url=f"https://propertyquarry.com/tours/{slug}",
        title="Governed customer home",
        principal_id="customer-1",
        actor="property.visual.request",
        external_processing_consent_receipt="",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "governed_render_external_processing_consent_missing"


def test_governed_render_compose_authority_is_scoped_to_live_api_dispatch() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.property.yml").read_text(encoding="utf-8"))
    services = dict(compose["services"])
    authority_keys = {
        "PROPERTYQUARRY_GOVERNED_RENDER_API_URL",
        "PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN",
        "PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN_FILE",
        "PROPERTYQUARRY_GOVERNED_RENDER_ALLOWED_ORIGIN",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_SIGNING_SECRET_FILE",
        "PROPERTYQUARRY_GOVERNED_RENDER_CONSENT_STORE_DIR",
        "PROPERTYQUARRY_GOVERNED_RENDER_LOCALE",
    }

    api_environment = dict(services["propertyquarry-api"]["environment"])
    assert authority_keys.issubset(api_environment)
    assert "PROPERTYQUARRY_GOVERNED_RENDER_PROPERTY_ID" not in api_environment
    for service_name in (
        "propertyquarry-worker",
        "propertyquarry-scheduler",
        "propertyquarry-render-tools",
    ):
        service_environment = dict(services[service_name].get("environment") or {})
        assert {key: service_environment.get(key) for key in authority_keys} == {
            key: "" for key in authority_keys
        }
        assert all(
            "propertyquarry_governed_render_consents" not in str(volume)
            for volume in list(services[service_name].get("volumes") or [])
        )
    api_volumes = [str(value) for value in services["propertyquarry-api"]["volumes"]]
    assert (
        "propertyquarry_governed_render_consents:/data/governed-render-consents"
        in api_volumes
    )
    assert "propertyquarry_governed_render_consents" in dict(compose["volumes"])
