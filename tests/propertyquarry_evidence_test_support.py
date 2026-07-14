"""Deterministic external-authority stand-in for authenticated evidence tests.

This helper never participates in production execution.  Tests inject its
public challenge object at the fixed-authority boundary and use the private
key only as an out-of-process signer stand-in.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import propertyquarry_evidence_contract as contract
from scripts import propertyquarry_observability_receipts as receipts


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class EvidenceTestAuthority:
    private_key: Ed25519PrivateKey
    anchor: contract.TrustAnchor
    challenge: contract.EvidenceChallenge

    def sign(self, domain: str, unsigned_payload: Mapping[str, object]) -> str:
        return _b64url(
            self.private_key.sign(
                contract.authenticated_signature_message(domain, unsigned_payload)
            )
        )

    def authenticate(
        self,
        payload: Mapping[str, object],
        *,
        domain: str,
    ) -> dict[str, object]:
        return receipts.authenticate_payload(
            payload,
            domain=domain,
            anchor=self.anchor,
            challenge=self.challenge,
            signature_provider=self.sign,
        )

    def resign(
        self,
        payload: Mapping[str, object],
        *,
        domain: str,
    ) -> dict[str, object]:
        unsigned = copy.deepcopy(dict(payload))
        unsigned.pop("payload_sha256", None)
        unsigned.pop("authentication", None)
        unsigned.pop("deployment_id", None)
        unsigned.pop("challenge_nonce", None)
        return self.authenticate(unsigned, domain=domain)


@dataclass(frozen=True)
class OperatorGatewayTestAuthority:
    private_key: Ed25519PrivateKey
    trust: contract.OperatorGatewayTrust

    def sign_ack(self, payload: Mapping[str, object]) -> dict[str, object]:
        unsigned = copy.deepcopy(dict(payload))
        unsigned["authentication"] = {
            "scheme": contract.AUTH_SCHEME,
            "key_id": self.trust.key_id,
        }
        unsigned = receipts.add_payload_sha256(unsigned)
        signature = _b64url(
            self.private_key.sign(
                contract.authenticated_signature_message(
                    contract.OPERATOR_GATEWAY_ACK_DOMAIN,
                    unsigned,
                )
            )
        )
        authentication = dict(unsigned["authentication"])
        authentication["signature"] = signature
        unsigned["authentication"] = authentication
        return unsigned

    def acknowledgement(
        self,
        *,
        evidence_authority: EvidenceTestAuthority,
        release_commit_sha: str,
        release_image_digest: str,
        labels: Mapping[str, str],
        sent_at: datetime,
        delivered_at: datetime,
    ) -> dict[str, object]:
        canonical_labels = contract.canonical_release_proof_labels(
            release_commit_sha=release_commit_sha,
            release_image_digest=release_image_digest,
            deployment_id=evidence_authority.challenge.deployment_id,
            nonce=evidence_authority.challenge.nonce,
            challenge_sha256=evidence_authority.challenge.artifact_sha256,
        )
        canonical_labels.update({str(key): str(value) for key, value in labels.items()})
        labels = canonical_labels
        fingerprint = contract.alert_fingerprint_sha256(
            labels=labels,
            sent_at=sent_at,
        )
        delivery_id = receipts.sha256_bytes(
            receipts.canonical_json_bytes(
                {
                    "key_id": self.trust.key_id,
                    "audience": self.trust.audience,
                    "deployment_id": evidence_authority.challenge.deployment_id,
                    "nonce": evidence_authority.challenge.nonce,
                    "alert_fingerprint_sha256": fingerprint,
                    "delivered_at": receipts.isoformat(delivered_at),
                }
            )
        )
        return self.sign_ack(
            {
                "schema_version": contract.OPERATOR_GATEWAY_ACK_SCHEMA,
                "producer": contract.OPERATOR_GATEWAY_ACK_PRODUCER,
                "audience": self.trust.audience,
                "gateway": {
                    "endpoint_origin": self.trust.endpoint_origin,
                    "tls_spki_sha256": self.trust.tls_spki_sha256,
                },
                "deployment_id": evidence_authority.challenge.deployment_id,
                "challenge_nonce": evidence_authority.challenge.nonce,
                "challenge_sha256": evidence_authority.challenge.artifact_sha256,
                "release": {
                    "commit_sha": release_commit_sha,
                    "image_digest": release_image_digest,
                },
                "nonce": evidence_authority.challenge.nonce,
                "alert": {
                    "alertname": "PropertyQuarryReleaseProof",
                    "labels": dict(labels),
                    "fingerprint_sha256": fingerprint,
                    "labels_sha256": receipts.sha256_bytes(
                        receipts.canonical_json_bytes(labels)
                    ),
                    "sent_at": receipts.isoformat(sent_at),
                },
                "delivery": {
                    "channel": "telegram",
                    "status": "acknowledged",
                    "delivered_at": receipts.isoformat(delivered_at),
                    "delivery_id_sha256": delivery_id,
                },
            }
        )


def install_test_operator_gateway(
    monkeypatch: object,
    *,
    evidence_authority: EvidenceTestAuthority,
    seed_byte: int = 71,
    key_id: str = "test-operator-gateway-1",
    audience: str = "propertyquarry-operator-telegram",
    endpoint_origin: str = "https://10.0.0.30:9443",
    tls_spki_sha256: str = "7" * 64,
) -> OperatorGatewayTestAuthority:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes([seed_byte]) * 32)
    public_key = private_key.public_key()
    origin, socket_identity = contract.canonical_endpoint_origin(
        endpoint_origin,
        field="test operator gateway endpoint",
        require_https=True,
    )
    trust = contract.OperatorGatewayTrust(
        key_id=key_id,
        audience=audience,
        endpoint_origin=origin,
        endpoint_socket_identity=socket_identity,
        tls_spki_sha256=tls_spki_sha256,
        public_key=public_key,
        file_sha256=hashlib.sha256(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).hexdigest(),
    )
    authority = OperatorGatewayTestAuthority(private_key, trust)

    def load_operator_gateway_trust(
        *, evidence_anchor: contract.TrustAnchor | None = None
    ) -> contract.OperatorGatewayTrust:
        if evidence_anchor is not None and evidence_anchor.key_id == trust.key_id:
            raise contract.EvidenceContractError(
                "operator gateway and evidence authority must use distinct keys"
            )
        return trust

    monkeypatch.setattr(
        contract,
        "load_operator_gateway_trust",
        load_operator_gateway_trust,
    )
    return authority


@dataclass(frozen=True)
class CanonicalMonitoringTestIdentity:
    payload: Mapping[str, object]
    topology_path: Path
    tool_manifest_path: Path


def install_test_canonical_monitoring_identity(
    monkeypatch: object,
    *,
    directory: Path,
) -> CanonicalMonitoringTestIdentity:
    directory.mkdir(parents=True, exist_ok=True)
    topology_path = directory / "canonical-monitoring-topology.json"
    source_monitoring_root = next(iter(contract.CANONICAL_POLICY_PATHS.values())).parent
    topology_path.write_bytes(
        (source_monitoring_root / "propertyquarry_monitoring_topology.v1.json").read_bytes()
    )
    tools: dict[str, object] = {
        "schema_version": "propertyquarry.monitoring-tools.v1",
        "tools": {},
    }
    for name, version in (("promtool", "3.5.0"), ("amtool", "0.28.1")):
        binary = directory / name
        binary.write_bytes(f"fd-bound-{name}".encode("utf-8"))
        binary.chmod(0o500)
        tools["tools"][name] = {  # type: ignore[index]
            "path": str(binary),
            "version": version,
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        }
    manifest_path = directory / "canonical-monitoring-tools.json"
    manifest_path.write_text(
        json.dumps(tools, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    payload = contract.compute_canonical_monitoring_identity(
        topology_path=topology_path,
        tool_manifest_path=manifest_path,
        _test_allow_insecure_tools=True,
    )

    def load_canonical_monitoring_identity() -> dict[str, object]:
        return copy.deepcopy(dict(payload))

    monkeypatch.setattr(
        contract,
        "load_canonical_monitoring_identity",
        load_canonical_monitoring_identity,
    )
    return CanonicalMonitoringTestIdentity(payload, topology_path, manifest_path)


def install_test_authority(
    monkeypatch: object,
    *,
    release_commit_sha: str,
    release_image_digest: str,
    now: datetime,
    seed_byte: int = 17,
    deployment_id: str = "deploy-test-001",
    nonce: str = "c" * 32,
) -> EvidenceTestAuthority:
    """Install a deterministic authority only at the loader seam used by tests."""

    private_key = Ed25519PrivateKey.from_private_bytes(bytes([seed_byte]) * 32)
    public_key = private_key.public_key()
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = f"test-release-authority-{seed_byte}"
    issued_at = now.astimezone(timezone.utc) - timedelta(minutes=2)
    expires_at = issued_at + timedelta(minutes=14)
    unsigned_challenge: dict[str, object] = {
        "schema_version": contract.CHALLENGE_SCHEMA,
        "producer": contract.CHALLENGE_PRODUCER,
        "key_id": key_id,
        "deployment_id": deployment_id,
        "nonce": nonce,
        "issued_at": contract.isoformat(issued_at),
        "expires_at": contract.isoformat(expires_at),
        "release": {
            "commit_sha": release_commit_sha,
            "image_digest": release_image_digest,
        },
        "policy": contract.canonical_policy_hashes(),
    }
    signed_challenge = {
        **unsigned_challenge,
        "signature": _b64url(
            private_key.sign(
                contract.authenticated_signature_message(
                    contract.CHALLENGE_DOMAIN,
                    unsigned_challenge,
                )
            )
        ),
    }
    challenge_raw = (
        json.dumps(signed_challenge, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    anchor = contract.TrustAnchor(
        key_id=key_id,
        public_key=public_key,
        file_sha256=hashlib.sha256(public_raw).hexdigest(),
        device=1,
        inode=1,
    )
    challenge = contract.EvidenceChallenge(
        key_id=key_id,
        deployment_id=deployment_id,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
        release_commit_sha=release_commit_sha,
        release_image_digest=release_image_digest,
        artifact_sha256=hashlib.sha256(challenge_raw).hexdigest(),
        policy_hashes=contract.canonical_policy_hashes(),
    )
    authority = EvidenceTestAuthority(private_key, anchor, challenge)

    def load_evidence_challenge(
        *,
        expected_commit_sha: str,
        expected_image_digest: str,
        now: datetime,
    ) -> tuple[contract.TrustAnchor, contract.EvidenceChallenge]:
        checked_at = now.astimezone(timezone.utc)
        if (
            expected_commit_sha != release_commit_sha
            or expected_image_digest != release_image_digest
        ):
            raise contract.EvidenceContractError(
                "evidence challenge belongs to another release"
            )
        if checked_at >= challenge.expires_at:
            raise contract.EvidenceContractError("evidence challenge is stale or expired")
        if challenge.issued_at > checked_at + timedelta(
            seconds=contract.MAX_FUTURE_SKEW_SECONDS
        ):
            raise contract.EvidenceContractError("evidence challenge is future-dated")
        return anchor, challenge

    monkeypatch.setattr(contract, "load_evidence_challenge", load_evidence_challenge)
    return authority
