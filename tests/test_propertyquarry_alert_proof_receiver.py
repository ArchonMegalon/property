from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from propertyquarry_evidence_test_support import (
    EvidenceTestAuthority,
    OperatorGatewayTestAuthority,
    install_test_authority,
    install_test_operator_gateway,
)
from scripts import propertyquarry_alert_proof_receiver as receiver
from scripts import propertyquarry_evidence_contract as contract
from scripts import propertyquarry_observability_receipts as receipts


RELEASE_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64
NONCE = "c" * 32
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
AUTHORITY: EvidenceTestAuthority
GATEWAY: OperatorGatewayTestAuthority


@pytest.fixture(autouse=True)
def _authenticated_authorities(monkeypatch: pytest.MonkeyPatch) -> None:
    global AUTHORITY, GATEWAY
    AUTHORITY = install_test_authority(
        monkeypatch,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        now=NOW,
        nonce=NONCE,
    )
    GATEWAY = install_test_operator_gateway(
        monkeypatch,
        evidence_authority=AUTHORITY,
    )


def _labels() -> dict[str, str]:
    return {
        "alertname": "PropertyQuarryReleaseProof",
        "service": "propertyquarry",
        "proof_nonce": NONCE,
    }


def _ack(
    *,
    sent_at: datetime = NOW,
    delivered_at: datetime | None = None,
) -> dict[str, object]:
    return GATEWAY.acknowledgement(
        evidence_authority=AUTHORITY,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        labels=_labels(),
        sent_at=sent_at,
        delivered_at=delivered_at or sent_at + timedelta(seconds=2),
    )


def _raw(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def test_receiver_only_caches_distinct_gateway_signed_acknowledgement() -> None:
    result = receiver.build_alert_delivery_receipt(
        _raw(_ack()),
        receiver_instance_sha256="d" * 64,
        received_at=NOW + timedelta(seconds=3),
    )

    assert result["schema_version"] == contract.OPERATOR_GATEWAY_ACK_SCHEMA
    assert result["producer"] == contract.OPERATOR_GATEWAY_ACK_PRODUCER
    assert result["audience"] == GATEWAY.trust.audience
    assert result["delivery"]["channel"] == "telegram"
    assert result["delivery"]["status"] == "acknowledged"
    receipts.validate_alert_delivery_receipt(
        result,
        expected_commit_sha=RELEASE_SHA,
        expected_image_digest=IMAGE_DIGEST,
        operator_gateway_trust=GATEWAY.trust,
        challenge=AUTHORITY.challenge,
        now=NOW + timedelta(seconds=3),
    )


def test_forged_operator_receiver_string_cannot_create_acknowledgement() -> None:
    forged = {
        "receiver": "propertyquarry-operator",
        "status": "firing",
        "alerts": [{"labels": _labels()}],
    }
    with pytest.raises(receiver.ProofReceiverError):
        receiver.build_alert_delivery_receipt(
            _raw(forged),
            receiver_instance_sha256="d" * 64,
            received_at=NOW,
        )


def test_evidence_proof_key_cannot_sign_operator_gateway_ack() -> None:
    payload = copy.deepcopy(_ack())
    payload.pop("payload_sha256")
    payload["authentication"] = {
        "scheme": contract.AUTH_SCHEME,
        "key_id": AUTHORITY.anchor.key_id,
    }
    payload = receipts.add_payload_sha256(payload)
    authentication = dict(payload["authentication"])
    authentication["signature"] = AUTHORITY.sign(
        contract.OPERATOR_GATEWAY_ACK_DOMAIN,
        payload,
    )
    payload["authentication"] = authentication

    with pytest.raises(receiver.ProofReceiverError, match="pinned operator gateway"):
        receiver.build_alert_delivery_receipt(
            _raw(payload),
            receiver_instance_sha256="d" * 64,
            received_at=NOW + timedelta(seconds=3),
        )


def test_stale_and_replayed_acknowledgements_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _ack(
        sent_at=NOW - timedelta(minutes=3),
        delivered_at=NOW - timedelta(minutes=3) + timedelta(seconds=2),
    )
    with pytest.raises(receiver.ProofReceiverError, match="predates|stale"):
        receiver.build_alert_delivery_receipt(
            _raw(stale),
            receiver_instance_sha256="d" * 64,
            received_at=NOW,
        )

    old_ack = _ack()
    replacement = install_test_authority(
        monkeypatch,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        now=NOW,
        seed_byte=29,
        deployment_id="deploy-test-002",
        nonce="e" * 32,
    )
    install_test_operator_gateway(
        monkeypatch,
        evidence_authority=replacement,
    )
    with pytest.raises(receiver.ProofReceiverError, match="challenge binding"):
        receiver.build_alert_delivery_receipt(
            _raw(old_ack),
            receiver_instance_sha256="d" * 64,
            received_at=NOW + timedelta(seconds=3),
        )


def test_receiver_blocks_when_gateway_trust_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*, evidence_anchor: object) -> object:
        del evidence_anchor
        raise contract.EvidenceContractError("operator gateway unavailable")

    monkeypatch.setattr(contract, "load_operator_gateway_trust", unavailable)
    with pytest.raises(receiver.ProofReceiverError, match="operator gateway unavailable"):
        receiver.build_alert_delivery_receipt(
            _raw(_ack()),
            receiver_instance_sha256="d" * 64,
            received_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize("address", ["0.0.0.0", "::"])
def test_receiver_rejects_wildcard_bind_addresses(address: str) -> None:
    with pytest.raises(receiver.ProofReceiverError, match="loopback or private"):
        receiver._private_bind_address(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "10.0.0.5", "fd00::5"])
def test_receiver_accepts_explicit_private_bind_addresses(address: str) -> None:
    assert receiver._private_bind_address(address)
