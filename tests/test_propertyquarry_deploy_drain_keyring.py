from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import propertyquarry_deploy_drain_keyring as keyring


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _key(
    key_id: str,
    epoch: int,
    byte: int,
    activates_at: str,
    *,
    accept_until: str | None,
    revoked_at: str | None = None,
) -> dict[str, object]:
    raw = bytes([byte]) * 32
    return {
        "key_id": key_id,
        "epoch": epoch,
        "public_key": _b64(raw),
        "public_key_sha256": hashlib.sha256(raw).hexdigest(),
        "activates_at": activates_at,
        "accept_until": accept_until,
        "revoked_at": revoked_at,
    }


@pytest.fixture
def active_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    secure = tmp_path / "secure"
    tracked = secure / "tracked" / "keyring.json"
    external = secure / "external" / "keyring.json"
    tracked.parent.mkdir(parents=True, mode=0o700)
    external.parent.mkdir(parents=True, mode=0o700)
    payload: dict[str, object] = {
        "schema": keyring.SCHEMA,
        "authority": keyring.AUTHORITY,
        "algorithm": "Ed25519",
        "status": "active",
        "rotation_epoch": 2,
        "minimum_accepted_epoch": 1,
        "keys": [
            _key(
                "drain-old",
                1,
                1,
                "2026-01-01T00:00:00Z",
                accept_until="2026-03-01T00:00:00Z",
            ),
            _key(
                "drain-new",
                2,
                2,
                "2026-02-01T00:00:00Z",
                accept_until=None,
            ),
        ],
    }
    tracked.write_bytes(_canonical(payload))
    external.write_bytes(_canonical(payload))
    external.chmod(0o444)
    monkeypatch.setattr(keyring, "SECURE_PATH_ROOT", secure)
    monkeypatch.setattr(keyring, "TRACKED_KEYRING_PATH", tracked)
    monkeypatch.setattr(keyring, "EXTERNAL_KEYRING_PATH", external)
    monkeypatch.setattr(keyring, "REQUIRED_UID", os.getuid())
    monkeypatch.setattr(keyring, "KEYRING_STATUS", "active")
    monkeypatch.setattr(keyring, "KEYRING_ROTATION_EPOCH", 2)
    monkeypatch.setattr(keyring, "KEYRING_MINIMUM_ACCEPTED_EPOCH", 1)
    monkeypatch.setattr(
        keyring,
        "KEYRING_MANIFEST_SHA256",
        hashlib.sha256(_canonical(payload)).hexdigest(),
    )
    return payload


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_default_keyring_is_unconfigured() -> None:
    payload = json.loads(keyring.TRACKED_KEYRING_PATH.read_text(encoding="utf-8"))
    assert payload["status"] == "UNCONFIGURED"
    with pytest.raises(keyring.DrainKeyringError, match="UNCONFIGURED"):
        keyring.load_keyring()


def test_activation_and_overlap_boundaries(active_keyring: dict[str, object]) -> None:
    assert keyring.select_trusted_key("drain-old", at=_at("2026-01-15T00:00:00Z")).epoch == 1
    with pytest.raises(keyring.DrainKeyringError, match="not active yet"):
        keyring.select_trusted_key("drain-new", at=_at("2026-01-15T00:00:00Z"))

    assert keyring.select_trusted_key("drain-old", at=_at("2026-02-15T00:00:00Z")).epoch == 1
    assert keyring.select_trusted_key("drain-new", at=_at("2026-02-15T00:00:00Z")).epoch == 2
    with pytest.raises(keyring.DrainKeyringError, match="overlap window has ended"):
        keyring.select_trusted_key("drain-old", at=_at("2026-03-01T00:00:00Z"))


def test_revocation_cutoff_rejects_old_key(
    active_keyring: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = dict(active_keyring)
    keys = [dict(item) for item in active_keyring["keys"]]  # type: ignore[index]
    keys[0]["revoked_at"] = "2026-02-10T00:00:00Z"
    payload["keys"] = keys
    keyring.TRACKED_KEYRING_PATH.write_bytes(_canonical(payload))
    keyring.EXTERNAL_KEYRING_PATH.chmod(0o644)
    keyring.EXTERNAL_KEYRING_PATH.write_bytes(_canonical(payload))
    keyring.EXTERNAL_KEYRING_PATH.chmod(0o444)
    monkeypatch.setattr(
        keyring,
        "KEYRING_MANIFEST_SHA256",
        hashlib.sha256(_canonical(payload)).hexdigest(),
    )

    with pytest.raises(keyring.DrainKeyringError, match="revoked"):
        keyring.select_trusted_key("drain-old", at=_at("2026-02-10T00:00:00Z"))


def test_rotation_epoch_rollback_is_rejected_even_with_valid_files(
    active_keyring: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rolled_back = dict(active_keyring)
    rolled_back["rotation_epoch"] = 1
    rolled_back["keys"] = [dict(active_keyring["keys"][0])]  # type: ignore[index]
    keyring.TRACKED_KEYRING_PATH.write_bytes(_canonical(rolled_back))
    keyring.EXTERNAL_KEYRING_PATH.chmod(0o644)
    keyring.EXTERNAL_KEYRING_PATH.write_bytes(_canonical(rolled_back))
    keyring.EXTERNAL_KEYRING_PATH.chmod(0o444)
    monkeypatch.setattr(
        keyring,
        "KEYRING_MANIFEST_SHA256",
        hashlib.sha256(_canonical(rolled_back)).hexdigest(),
    )

    with pytest.raises(keyring.DrainKeyringError, match="epoch rollback"):
        keyring.load_keyring()
