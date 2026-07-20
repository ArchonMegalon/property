from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from propertyquarry_global_governance_test_support import (
    install_test_authority,
    signed_attestation,
)
from scripts import propertyquarry_global_governance_attestation as authority_verifier
from scripts.propertyquarry_global_governance_attestation import (
    GLOBAL_MARKET_GATE_ID,
    GlobalGovernanceAttestationError,
    verify_global_governance_attestation,
)
from scripts.propertyquarry_global_market_envelope import LIVE_RECEIPT_SCHEMA


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "89abcdef0123456789abcdef0123456789abcdef"
IMAGE = "sha256:89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567"
SOURCE = "sha256:123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0"
PAYLOAD = "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"


def _subject(*, commit: str = COMMIT) -> dict[str, object]:
    return {
        "gate_id": GLOBAL_MARKET_GATE_ID,
        "receipt_contract": LIVE_RECEIPT_SCHEMA,
        "release_commit_sha": commit,
        "release_image_digest": IMAGE,
        "source_digests": {"market_envelope_sha256": SOURCE},
        "payload_sha256": PAYLOAD,
    }


def _attestation() -> dict[str, object]:
    return signed_attestation(
        gate_id=GLOBAL_MARKET_GATE_ID,
        receipt_contract=LIVE_RECEIPT_SCHEMA,
        release_commit_sha=COMMIT,
        release_image_digest=IMAGE,
        source_digests={"market_envelope_sha256": SOURCE},
        payload_sha256=PAYLOAD,
        issued_at=NOW - timedelta(minutes=2),
    )


def test_valid_detached_attestation_resolves_only_external_trust(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_test_authority(tmp_path, monkeypatch)

    verified = verify_global_governance_attestation(
        _attestation(),
        expected_subject=_subject(),
        observed_at=NOW,
    )

    assert verified.gate_id == GLOBAL_MARKET_GATE_ID
    assert verified.receipt_contract == LIVE_RECEIPT_SCHEMA
    assert verified.payload_sha256 == PAYLOAD
    assert len(verified.public_key_sha256) == 64
    assert len(verified.trust_store_sha256) == 64


def test_forged_signature_is_rejected(tmp_path: Path, monkeypatch) -> None:
    install_test_authority(tmp_path, monkeypatch)
    attestation = _attestation()
    signature = bytearray(base64.b64decode(attestation["signature_base64"]))
    signature[-1] ^= 0x01
    attestation["signature_base64"] = base64.b64encode(signature).decode("ascii")

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_signature_invalid",
    ):
        verify_global_governance_attestation(
            attestation,
            expected_subject=_subject(),
            observed_at=NOW,
        )


def test_revoked_key_is_rejected_even_for_an_earlier_signature(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_test_authority(
        tmp_path,
        monkeypatch,
        revoked_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_key_revoked",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=_subject(),
            observed_at=NOW,
        )


def test_key_validity_window_must_cover_the_full_attestation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trust_path = install_test_authority(tmp_path, monkeypatch)
    trust_store = json.loads(trust_path.read_text(encoding="utf-8"))
    trust_store["keys"][0]["valid_until"] = "2026-07-19T12:30:00Z"
    trust_path.write_text(
        json.dumps(trust_store, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    trust_path.chmod(0o600)

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_authority_window_invalid",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=_subject(),
            observed_at=NOW,
        )


def test_attestation_cannot_be_replayed_for_another_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_test_authority(tmp_path, monkeypatch)

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_subject_mismatch",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=_subject(commit=OTHER_COMMIT),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("receipt_contract", "propertyquarry.other_live_receipt.v1"),
        (
            "source_digests",
            {"market_envelope_sha256": "sha256:" + "a" * 64},
        ),
        ("payload_sha256", "sha256:" + "b" * 64),
    ),
)
def test_attestation_binds_exact_contract_source_and_payload_digests(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: object,
) -> None:
    install_test_authority(tmp_path, monkeypatch)
    expected = _subject()
    expected[field] = value

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_subject_mismatch",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=expected,
            observed_at=NOW,
        )


def test_missing_external_trust_store_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv(
        "PROPERTYQUARRY_GLOBAL_GOVERNANCE_TRUST_STORE_FILE",
        raising=False,
    )
    monkeypatch.delenv(
        "PROPERTYQUARRY_GLOBAL_GOVERNANCE_TEST_TRUST_OWNER_UID",
        raising=False,
    )

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_trust_store_missing",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=_subject(),
            observed_at=NOW,
        )


def test_legacy_self_assertion_is_not_an_attestation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_test_authority(tmp_path, monkeypatch)
    legacy = {
        "independent": True,
        "authority": "independent_release_controller",
        "subject_commit_sha": COMMIT,
        "subject_image_digest": IMAGE,
        "subject_payload_digest": PAYLOAD,
    }

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_contract_invalid",
    ):
        verify_global_governance_attestation(
            legacy,
            expected_subject=_subject(),
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    "malformed",
    (
        b'{"contract_name":"first","contract_name":"second"}',
        b'{"contract_name":NaN}',
        b'{"contract_name":Infinity}',
        b'{"contract_name":1e100000}',
    ),
)
def test_duplicate_keys_and_nonfinite_json_are_rejected_before_trust(
    tmp_path: Path,
    monkeypatch,
    malformed: bytes,
) -> None:
    install_test_authority(tmp_path, monkeypatch)

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_attestation_contract_invalid",
    ):
        verify_global_governance_attestation(
            malformed,
            expected_subject=_subject(),
            observed_at=NOW,
        )


def test_spoofed_pytest_and_legacy_env_cannot_authorize_caller_owned_trust(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trust_path = install_test_authority(
        tmp_path,
        monkeypatch,
        patch_owner_resolution=False,
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "spoofed::test (call)")
    monkeypatch.setenv(
        "PROPERTYQUARRY_GLOBAL_GOVERNANCE_TEST_TRUST_OWNER_UID",
        str(os.geteuid()),
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_GLOBAL_GOVERNANCE_ALLOWED_OWNER_UID",
        str(os.geteuid()),
    )

    assert authority_verifier._trusted_owner_uids() == frozenset({0})

    if os.geteuid() == 0:
        untrusted_uid = 65_534
        key_path = trust_path.parent / "governance-key.v1.json"
        try:
            os.chown(key_path, untrusted_uid, -1)
            os.chown(trust_path, untrusted_uid, -1)
            os.chown(trust_path.parent, untrusted_uid, -1)
        except PermissionError:
            # Some rootless user namespaces report uid 0 but disallow chown.
            # The owner resolver assertion above still proves that no spoofed
            # environment value expanded the immutable root-only set.
            return

    with pytest.raises(
        GlobalGovernanceAttestationError,
        match="global_governance_trust_store_invalid",
    ):
        verify_global_governance_attestation(
            _attestation(),
            expected_subject=_subject(),
            observed_at=NOW,
        )
