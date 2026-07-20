"""Test-only signing authority for global-governance gate tests.

The deterministic private key below is deliberately confined to test code.
Production gates only receive the external public trust store path and never
ship or synthesize an authority key or a canonical evidence receipt.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import propertyquarry_global_governance_attestation as authority_verifier
from scripts.propertyquarry_global_governance_attestation import (
    ALLOWED_GATE_IDS,
    ATTESTATION_ALGORITHM,
    ATTESTATION_CONTRACT,
    PUBLIC_KEY_CONTRACT,
    TRUST_STORE_CONTRACT,
    TRUST_STORE_ENV,
    global_governance_attestation_signing_bytes,
)


TEST_KEY_ID = "propertyquarry-global-governance-test-key-2026"
TEST_AUTHORITY_ID = "propertyquarry-global-governance-test-authority"
_TEST_PRIVATE_SEED = hashlib.sha256(
    b"PropertyQuarry global governance Ed25519 TEST KEY ONLY v1"
).digest()


def _stamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_TEST_PRIVATE_SEED)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def install_test_authority(
    root: Path,
    monkeypatch,
    *,
    revoked_at: datetime | None = None,
    patch_owner_resolution: bool = True,
) -> Path:
    """Install a test authority and optionally patch the private owner seam."""

    authority_root = root / "global-governance-test-authority"
    authority_root.mkdir(mode=0o700)
    authority_root.chmod(0o700)

    public_key = _private_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_record = {
        "contract_name": PUBLIC_KEY_CONTRACT,
        "algorithm": ATTESTATION_ALGORITHM,
        "key_id": TEST_KEY_ID,
        "authority_id": TEST_AUTHORITY_ID,
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
    }
    key_body = _json_bytes(key_record)
    key_path = authority_root / "governance-key.v1.json"
    key_path.write_bytes(key_body)
    key_path.chmod(0o600)

    trust_store = {
        "contract_name": TRUST_STORE_CONTRACT,
        "keys": [
            {
                "algorithm": ATTESTATION_ALGORITHM,
                "key_id": TEST_KEY_ID,
                "authority_id": TEST_AUTHORITY_ID,
                "public_key_relpath": key_path.name,
                "public_key_record_sha256": (
                    f"sha256:{hashlib.sha256(key_body).hexdigest()}"
                ),
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_until": "2030-01-01T00:00:00Z",
                "revoked_at": _stamp(revoked_at) if revoked_at else None,
                "allowed_gate_ids": sorted(ALLOWED_GATE_IDS),
            }
        ],
    }
    trust_path = authority_root / "trust-store.v1.json"
    trust_path.write_bytes(_json_bytes(trust_store))
    trust_path.chmod(0o600)

    monkeypatch.setenv(TRUST_STORE_ENV, str(trust_path))
    if patch_owner_resolution:
        test_owners = frozenset({0, os.geteuid()})
        monkeypatch.setattr(
            authority_verifier,
            "_trusted_owner_uids",
            lambda: test_owners,
        )
    return trust_path


def signed_attestation(
    *,
    gate_id: str,
    receipt_contract: str,
    release_commit_sha: str,
    release_image_digest: str,
    source_digests: Mapping[str, str],
    payload_sha256: str,
    issued_at: datetime,
    expires_at: datetime | None = None,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "contract_name": ATTESTATION_CONTRACT,
        "algorithm": ATTESTATION_ALGORITHM,
        "key_id": TEST_KEY_ID,
        "authority_id": TEST_AUTHORITY_ID,
        "issued_at": _stamp(issued_at),
        "expires_at": _stamp(expires_at or (issued_at + timedelta(hours=1))),
        "subject": {
            "gate_id": gate_id,
            "receipt_contract": receipt_contract,
            "release_commit_sha": release_commit_sha,
            "release_image_digest": release_image_digest,
            "source_digests": dict(source_digests),
            "payload_sha256": payload_sha256,
        },
    }
    signature = _private_key().sign(
        global_governance_attestation_signing_bytes(unsigned)
    )
    return {
        **unsigned,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
