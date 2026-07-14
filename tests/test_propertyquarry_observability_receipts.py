from __future__ import annotations

import copy
import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from propertyquarry_evidence_test_support import (
    EvidenceTestAuthority,
    CanonicalMonitoringTestIdentity,
    OperatorGatewayTestAuthority,
    install_test_canonical_monitoring_identity,
    install_test_authority,
    install_test_operator_gateway,
)
from scripts import propertyquarry_evidence_contract as contract
from scripts import propertyquarry_observability_receipts as receipts


RELEASE_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
REPLICA_IDS = ["api-a", "api-b"]
AUTHORITY: EvidenceTestAuthority
GATEWAY: OperatorGatewayTestAuthority
CANONICAL: CanonicalMonitoringTestIdentity


@pytest.fixture(autouse=True)
def _authenticated_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global AUTHORITY
    AUTHORITY = install_test_authority(
        monkeypatch,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        now=NOW + timedelta(minutes=1),
    )
    global GATEWAY
    GATEWAY = install_test_operator_gateway(
        monkeypatch,
        evidence_authority=AUTHORITY,
    )
    global CANONICAL
    CANONICAL = install_test_canonical_monitoring_identity(
        monkeypatch,
        directory=tmp_path / "canonical-monitoring",
    )


def _write(path: Path, payload: object) -> bytes:
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return raw


def _alert() -> dict[str, object]:
    return GATEWAY.acknowledgement(
        evidence_authority=AUTHORITY,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        labels={
            "alertname": "PropertyQuarryReleaseProof",
            "proof_nonce": AUTHORITY.challenge.nonce,
        },
        sent_at=NOW,
        delivered_at=NOW + timedelta(seconds=2),
    )


def _range_response() -> dict[str, object]:
    start = NOW - timedelta(days=30)
    sample_count = contract.RANGE_WINDOW_SECONDS // contract.RANGE_STEP_SECONDS + 1
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {
                        "__name__": "propertyquarry_http_requests_total",
                        "replica_id": replica_id,
                        "container_id": f"container-{replica_id}",
                        "release_commit_sha": RELEASE_SHA,
                        "release_image_digest": IMAGE_DIGEST,
                    },
                    "values": [
                        [
                            start.timestamp() + index * contract.RANGE_STEP_SECONDS,
                            str(index),
                        ]
                        for index in range(sample_count)
                    ],
                }
                for replica_id in REPLICA_IDS
            ],
        },
    }


def _range_receipt(
    response: dict[str, object], raw: bytes, *, snapshot_sha256: str
) -> dict[str, object]:
    start = NOW - timedelta(days=30)
    query_contract = {
        "expression": contract.PROMETHEUS_RANGE_QUERY,
        "start": receipts.isoformat(start),
        "end": receipts.isoformat(NOW),
        "step_seconds": 300,
    }
    result = response["data"]["result"]  # type: ignore[index]
    return AUTHORITY.authenticate(
        {
            "schema": receipts.RANGE_SCHEMA,
            "producer": receipts.RANGE_PRODUCER,
            "captured_at": receipts.isoformat(NOW),
            "release": {"commit_sha": RELEASE_SHA, "image_digest": IMAGE_DIGEST},
            "snapshot_bundle_sha256": snapshot_sha256,
            "query": {
                **query_contract,
                "contract_sha256": receipts.sha256_bytes(receipts.canonical_json_bytes(query_contract)),
            },
            "transport": {
                "endpoint_path": "/api/v1/query_range",
                "authenticated": True,
                "credential_persisted": False,
                "http_status": 200,
                "tls_verified": True,
                "connected_peer_ip": "10.0.0.20",
            },
            "prometheus_config_sha256": AUTHORITY.challenge.policy_hashes[
                "prometheus_config_sha256"
            ],
            "expected_replica_ids": REPLICA_IDS,
            "replicas": [
                {
                    "replica_id": replica_id,
                    "container_id": f"container-{replica_id}",
                    "container_image_id": IMAGE_DIGEST,
                    "release_commit_sha": RELEASE_SHA,
                    "release_image_digest": IMAGE_DIGEST,
                    "start_snapshot_sha256": "2" * 64,
                    "end_snapshot_sha256": "3" * 64,
                }
                for replica_id in REPLICA_IDS
            ],
            "series": {
                "result_type": "matrix",
                "count": len(result),
                "sha256": receipts.sha256_bytes(receipts.canonical_json_bytes(result)),
            },
            "range_response_sha256": receipts.sha256_bytes(raw),
            "range_response_bytes": len(raw),
        },
        domain=contract.RANGE_DOMAIN,
    )


def _monitoring(alert_raw: bytes, *, snapshot_sha256: str) -> dict[str, object]:
    return AUTHORITY.authenticate(
        {
            "schema_version": receipts.MONITORING_SCHEMA,
            "producer": receipts.MONITORING_PRODUCER,
            "captured_at": receipts.isoformat(NOW + timedelta(seconds=3)),
            "release": {"commit_sha": RELEASE_SHA, "image_digest": IMAGE_DIGEST},
            "snapshot_bundle_sha256": snapshot_sha256,
            "identity": {
                **CANONICAL.payload["identity"],  # type: ignore[dict-item]
                "operator_gateway_trust_sha256": GATEWAY.trust.file_sha256,
                "operator_gateway_key_id_sha256": receipts.sha256_bytes(
                    GATEWAY.trust.key_id.encode()
                ),
                "operator_gateway_audience_sha256": receipts.sha256_bytes(
                    GATEWAY.trust.audience.encode()
                ),
            },
            "prometheus": {
                "loaded_config_sha256": CANONICAL.payload["identity"][  # type: ignore[index]
                    "prometheus_config_sha256"
                ],
                "rules_sha256": CANONICAL.payload["identity"][  # type: ignore[index]
                    "alert_rules_sha256"
                ],
                "expected_replica_ids": REPLICA_IDS,
                "targets": [
                    {
                        "replica_id": replica_id,
                        "container_id": f"container-{replica_id}",
                        "container_image_id": IMAGE_DIGEST,
                        "release_commit_sha": RELEASE_SHA,
                        "release_image_digest": IMAGE_DIGEST,
                        "start_snapshot_sha256": "2" * 64,
                        "end_snapshot_sha256": "3" * 64,
                        "instance": f"10.0.0.{11 + index}:8090",
                        "health": "up",
                        "last_scrape_at": receipts.isoformat(NOW),
                        "scrape_url_sha256": "c" * 64,
                    }
                    for index, replica_id in enumerate(REPLICA_IDS)
                ],
            },
            "alertmanager": {
                "loaded_config_sha256": CANONICAL.payload["identity"][  # type: ignore[index]
                    "alertmanager_config_sha256"
                ],
                "status": "ready",
                "proof_secret_configured": True,
            },
            "alert_delivery_receipt_sha256": receipts.sha256_bytes(alert_raw),
            "started_at": receipts.isoformat(NOW - timedelta(seconds=1)),
            "completed_at": receipts.isoformat(NOW + timedelta(seconds=3)),
        },
        domain=contract.MONITORING_DOMAIN,
    )


def _snapshot() -> dict[str, object]:
    return receipts.add_payload_sha256(
        {
            "schema": "propertyquarry.metrics_snapshot_bundle.v2",
            "capture_tool": "propertyquarry.slo_metrics_capture.v2",
            "release_commit_sha": RELEASE_SHA,
            "release_image_digest": IMAGE_DIGEST,
            "window_start": receipts.isoformat(NOW - timedelta(minutes=1)),
            "window_end": receipts.isoformat(NOW),
            "window_seconds": 60.0,
            "replica_count": len(REPLICA_IDS),
            "replicas": [
                {
                    "container_id": f"container-{replica_id}",
                    "container_image_id": IMAGE_DIGEST,
                    "replica_id": replica_id,
                    "release_commit_sha": RELEASE_SHA,
                    "release_image_digest": IMAGE_DIGEST,
                    "docker_inspect_sha256": "1" * 64,
                    "start": {
                        "captured_at": receipts.isoformat(NOW - timedelta(minutes=1)),
                        "path": f"{replica_id}.start.prom",
                        "sha256": "2" * 64,
                        "bytes": 10,
                    },
                    "end": {
                        "captured_at": receipts.isoformat(NOW),
                        "path": f"{replica_id}.end.prom",
                        "sha256": "3" * 64,
                        "bytes": 11,
                    },
                }
                for replica_id in REPLICA_IDS
            ],
        }
    )


def _bundle(tmp_path: Path) -> dict[str, Path]:
    snapshot_path = tmp_path / "metrics.json"
    snapshot_raw = _write(snapshot_path, _snapshot())
    snapshot_sha256 = receipts.sha256_bytes(snapshot_raw)
    alert_path = tmp_path / "alert.json"
    alert_raw = _write(alert_path, _alert())
    response = _range_response()
    response_path = tmp_path / "range.json"
    response_raw = _write(response_path, response)
    range_path = tmp_path / "range-receipt.json"
    _write(
        range_path,
        _range_receipt(response, response_raw, snapshot_sha256=snapshot_sha256),
    )
    monitoring_path = tmp_path / "monitoring.json"
    _write(
        monitoring_path,
        _monitoring(alert_raw, snapshot_sha256=snapshot_sha256),
    )
    return {
        "snapshot": snapshot_path,
        "alert": alert_path,
        "response": response_path,
        "range": range_path,
        "monitoring": monitoring_path,
    }


def test_verifier_recomputes_and_cross_links_all_raw_receipts(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    result = receipts.verify_receipt_bundle(
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        monitoring_receipt_path=paths["monitoring"],
        metrics_snapshot_path=paths["snapshot"],
        prometheus_range_receipt_path=paths["range"],
        prometheus_range_response_path=paths["response"],
        alert_delivery_receipt_path=paths["alert"],
        now=NOW + timedelta(minutes=1),
    )

    assert result["status"] == "verified"
    assert result["replica_ids"] == REPLICA_IDS
    assert result["cross_receipt_links_verified"] is True
    assert result["payload_sha256"] == receipts.compute_payload_sha256(result)


def test_verifier_rejects_arbitrary_signed_monitoring_identity_hashes(
    tmp_path: Path,
) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["monitoring"].read_text(encoding="utf-8"))
    payload["identity"]["topology_contract_sha256"] = "f" * 64
    _write(
        paths["monitoring"],
        AUTHORITY.resign(payload, domain=contract.MONITORING_DOMAIN),
    )
    with pytest.raises(receipts.ReceiptValidationError, match="canonical topology"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def test_verifier_rejects_gateway_ack_with_minimal_alert_labels(
    tmp_path: Path,
) -> None:
    paths = _bundle(tmp_path)
    acknowledgement = json.loads(paths["alert"].read_text(encoding="utf-8"))
    minimal_labels = {"alertname": "PropertyQuarryReleaseProof"}
    acknowledgement["alert"]["labels"] = minimal_labels
    acknowledgement["alert"]["labels_sha256"] = receipts.sha256_bytes(
        receipts.canonical_json_bytes(minimal_labels)
    )
    acknowledgement["alert"]["fingerprint_sha256"] = (
        contract.alert_fingerprint_sha256(labels=minimal_labels, sent_at=NOW)
    )
    _write(paths["alert"], GATEWAY.sign_ack(acknowledgement))
    with pytest.raises(receipts.ReceiptValidationError, match="canonical proof route"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


@pytest.mark.parametrize("target", ["response", "alert", "monitoring"])
def test_verifier_rejects_tampered_raw_or_receipt_bytes(tmp_path: Path, target: str) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths[target].read_text(encoding="utf-8"))
    if target == "response":
        payload["data"]["result"][0]["values"][1][1] = "101"
    elif target == "alert":
        payload["delivery"]["delivered_at"] = receipts.isoformat(NOW + timedelta(seconds=4))
    else:
        payload["prometheus"]["targets"][0]["health"] = "down"
    _write(paths[target], payload)

    with pytest.raises(receipts.ReceiptValidationError):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def test_verifier_rejects_receipt_signed_by_swapped_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _bundle(tmp_path)
    attacker = install_test_authority(
        monkeypatch,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        now=NOW + timedelta(minutes=1),
        seed_byte=99,
        deployment_id=AUTHORITY.challenge.deployment_id,
        nonce=AUTHORITY.challenge.nonce,
    )
    payload = json.loads(paths["range"].read_text(encoding="utf-8"))
    _write(
        paths["range"],
        attacker.resign(payload, domain=contract.RANGE_DOMAIN),
    )

    # Restore the immutable release-control authority; attacker-signed bytes
    # must not validate against it.
    trusted = install_test_authority(
        monkeypatch,
        release_commit_sha=RELEASE_SHA,
        release_image_digest=IMAGE_DIGEST,
        now=NOW + timedelta(minutes=1),
    )
    assert trusted.anchor.key_id != attacker.anchor.key_id
    with pytest.raises(receipts.ReceiptValidationError, match="signer|signature"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def _rewrite_signed_range(
    paths: dict[str, Path],
    mutate: object,
) -> None:
    payload = json.loads(paths["range"].read_text(encoding="utf-8"))
    assert callable(mutate)
    mutate(payload)
    _write(paths["range"], AUTHORITY.resign(payload, domain=contract.RANGE_DOMAIN))


def _rebind_range_response(paths: dict[str, Path], response: dict[str, object]) -> None:
    raw = _write(paths["response"], response)

    def mutate(payload: dict[str, object]) -> None:
        result = response["data"]["result"]  # type: ignore[index]
        payload["range_response_sha256"] = receipts.sha256_bytes(raw)
        payload["range_response_bytes"] = len(raw)
        payload["series"]["sha256"] = receipts.sha256_bytes(  # type: ignore[index]
            receipts.canonical_json_bytes(result)
        )

    _rewrite_signed_range(paths, mutate)


@pytest.mark.parametrize("mutation", ["sparse", "interior_reset"])
def test_verifier_rejects_dense_cadence_and_interior_reset_bypasses(
    tmp_path: Path,
    mutation: str,
) -> None:
    paths = _bundle(tmp_path)
    response = json.loads(paths["response"].read_text(encoding="utf-8"))
    values = response["data"]["result"][0]["values"]
    midpoint = len(values) // 2
    if mutation == "sparse":
        values.pop(midpoint)
        expected = "sparse|continuity"
    else:
        values[midpoint][1] = "0"
        expected = "counter reset"
    _rebind_range_response(paths, response)

    with pytest.raises(receipts.ReceiptValidationError, match=expected):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def test_verifier_rejects_float_step_even_when_rehashed_and_resigned(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)

    def mutate(payload: dict[str, object]) -> None:
        query = payload["query"]
        assert isinstance(query, dict)
        query["step_seconds"] = 300.0
        contract_fields = {name: query[name] for name in ("expression", "start", "end", "step_seconds")}
        query["contract_sha256"] = receipts.sha256_bytes(
            receipts.canonical_json_bytes(contract_fields)
        )

    _rewrite_signed_range(paths, mutate)
    with pytest.raises(receipts.ReceiptValidationError, match="JSON integer"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def test_verifier_rejects_replaced_container_binding_even_when_resigned(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    payload = json.loads(paths["monitoring"].read_text(encoding="utf-8"))
    payload["prometheus"]["targets"][0]["container_id"] = "replacement-container"
    _write(
        paths["monitoring"],
        AUTHORITY.resign(payload, domain=contract.MONITORING_DOMAIN),
    )
    with pytest.raises(receipts.ReceiptValidationError, match="fresh container"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=1),
        )


def test_verifier_rejects_expired_challenge_before_reading_receipts(tmp_path: Path) -> None:
    paths = _bundle(tmp_path)
    with pytest.raises(receipts.ReceiptValidationError, match="stale or expired"):
        receipts.verify_receipt_bundle(
            release_commit_sha=RELEASE_SHA,
            release_image_digest=IMAGE_DIGEST,
            monitoring_receipt_path=paths["monitoring"],
            metrics_snapshot_path=paths["snapshot"],
            prometheus_range_receipt_path=paths["range"],
            prometheus_range_response_path=paths["response"],
            alert_delivery_receipt_path=paths["alert"],
            now=NOW + timedelta(minutes=20),
        )


def test_verification_output_is_atomic_private_and_non_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "verification.json"
    payload = receipts.add_payload_sha256({"status": "verified"})
    receipts.atomic_write_json(output, payload, overwrite=False)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(receipts.ReceiptValidationError):
        receipts.atomic_write_json(output, payload, overwrite=False)
