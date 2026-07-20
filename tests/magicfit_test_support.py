"""Reusable Ed25519 reviewer-authority fixtures for MagicFit tests.

The production verifier deliberately trusts only externally provisioned key
material.  Integration tests therefore need a realistic external trust store,
but repeated deliveries below one temporary root must not silently rotate the
reviewer key and invalidate an already accepted artifact.  This module creates
that material once, persists it with restrictive modes, and reuses it on every
subsequent provisioning call for the same root.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.property_magicfit_reviewer_authority import (
    REVIEWER_AUTHORIZATION_ALGORITHM,
    REVIEWER_AUTHORIZATION_CONTRACT,
    REVIEWER_PUBLIC_KEY_CONTRACT,
    REVIEWER_TRUST_STORE_CONTRACT,
    magicfit_reviewer_authorization_signing_bytes,
)


DEFAULT_TEST_KEY_ID = "reviewer-key-2026-01"
DEFAULT_TEST_AUTHORITY_ID = "propertyquarry-release-review"
DEFAULT_TEST_KEY_VALID_FROM = "2020-01-01T00:00:00Z"
DEFAULT_TEST_KEY_VALID_UNTIL = "2099-12-31T23:59:59Z"

_AUTHORITY_DIRECTORY = ".magicfit-reviewer-test-authority"
_PRIVATE_KEY_FILENAME = "reviewer-private-key.raw"
_TRUST_STORE_FILENAME = "trust-store.json"
_AUTHORIZATION_DIRECTORY = "authorizations"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"unsafe MagicFit test authority directory: {path}")
    path.chmod(0o700)


def _write_secure_bytes(path: Path, body: bytes, *, exclusive: bool = False) -> None:
    _ensure_private_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(body)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating MagicFit test authority material")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_secure_json(path: Path, payload: object) -> bytes:
    body = _canonical_json_bytes(payload)
    _write_secure_bytes(path, body)
    return body


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"MagicFit test authority JSON is not an object: {path}")
    return dict(payload)


def _assert_private_file(path: Path) -> None:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise RuntimeError(f"unsafe MagicFit test authority file: {path}")


def magicfit_reviewer_subject(
    *,
    delivery_digest: str,
    video_sha256: str,
    staged_manifest_sha256: str,
    browser_receipt_sha256: str,
    evidence_receipt_sha256: str,
    visual_review_sha256: str,
    contact_sheet_sha256: str,
    reviewed_at: str,
) -> dict[str, str]:
    """Build the exact subject shape consumed by the production verifier."""

    return {
        "delivery_digest": delivery_digest,
        "video_sha256": video_sha256,
        "staged_manifest_sha256": staged_manifest_sha256,
        "browser_receipt_sha256": browser_receipt_sha256,
        "evidence_receipt_sha256": evidence_receipt_sha256,
        "visual_review_sha256": visual_review_sha256,
        "contact_sheet_sha256": contact_sheet_sha256,
        "reviewed_at": reviewed_at,
    }


@dataclass(frozen=True)
class SignedMagicFitReviewerAuthorization:
    """A persisted detached authorization and its exact unsigned payload."""

    path: Path
    body: bytes
    subject: dict[str, str]
    unsigned_authorization: dict[str, object]


@dataclass(frozen=True)
class MagicFitReviewerTestAuthority:
    """Stable, persisted reviewer test authority scoped to one temporary root."""

    root: Path
    public_tour_root: Path
    key_id: str
    authority_id: str
    private_key_path: Path
    public_key_path: Path
    trust_store_path: Path
    authorization_root: Path

    @property
    def private_key_bytes(self) -> bytes:
        _assert_private_file(self.private_key_path)
        body = self.private_key_path.read_bytes()
        if len(body) != 32:
            raise RuntimeError("invalid persisted MagicFit test reviewer private key")
        return body

    @property
    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(self.private_key_bytes)

    @property
    def public_key_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def read_trust_store(self) -> dict[str, object]:
        _assert_private_file(self.trust_store_path)
        return _read_json_object(self.trust_store_path)

    def write_trust_store(self, payload: Mapping[str, object]) -> bytes:
        """Persist an exact trust-store payload with production-safe test modes."""

        return _write_secure_json(self.trust_store_path, dict(payload))

    def update_trust_key(
        self,
        *,
        revoked: bool | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> bytes:
        """Update only the configured key record without rotating its key."""

        trust_store = self.read_trust_store()
        keys = trust_store.get("keys")
        if not isinstance(keys, list) or len(keys) != 1 or not isinstance(keys[0], dict):
            raise RuntimeError("invalid persisted MagicFit test reviewer trust store")
        entry = dict(keys[0])
        if entry.get("key_id") != self.key_id:
            raise RuntimeError("unexpected persisted MagicFit test reviewer key")
        if revoked is not None:
            entry["revoked"] = revoked
        if valid_from is not None:
            entry["valid_from"] = valid_from
        if valid_until is not None:
            entry["valid_until"] = valid_until
        trust_store["keys"] = [entry]
        return self.write_trust_store(trust_store)

    def set_revoked(self, revoked: bool = True) -> bytes:
        return self.update_trust_key(revoked=revoked)

    def revoke(self) -> bytes:
        return self.set_revoked(True)

    def unrevoke(self) -> bytes:
        return self.set_revoked(False)

    def sign_authorization(
        self,
        *,
        subject: Mapping[str, str],
        issued_at: str,
        expires_at: str,
        reviewed_at: str | None = None,
        authorization_path: Path | None = None,
        key_id: str | None = None,
        authority_id: str | None = None,
        signature: bytes | None = None,
        extra_fields: Mapping[str, object] | None = None,
    ) -> SignedMagicFitReviewerAuthorization:
        """Sign and securely persist one exact delivery/evidence subject.

        ``reviewed_at`` may be supplied separately for call sites that build
        the seven digest fields first.  If the subject already carries a
        different value, fail rather than signing ambiguous review time.
        ``issued_at`` and ``expires_at`` are mandatory so tests never depend on
        the wall clock implicitly.
        """

        exact_subject = dict(subject)
        existing_reviewed_at = exact_subject.get("reviewed_at")
        if reviewed_at is not None:
            if existing_reviewed_at is not None and existing_reviewed_at != reviewed_at:
                raise ValueError("reviewed_at conflicts with the signed subject")
            exact_subject["reviewed_at"] = reviewed_at
        if not isinstance(exact_subject.get("reviewed_at"), str):
            raise ValueError("reviewed_at is required in the signed subject")

        unsigned_authorization: dict[str, object] = {
            "contract_name": REVIEWER_AUTHORIZATION_CONTRACT,
            "algorithm": REVIEWER_AUTHORIZATION_ALGORITHM,
            "key_id": key_id or self.key_id,
            "authority_id": authority_id or self.authority_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "subject": exact_subject,
        }
        signing_bytes = magicfit_reviewer_authorization_signing_bytes(
            unsigned_authorization
        )
        authorization: dict[str, object] = {
            **deepcopy(unsigned_authorization),
            "signature_base64": base64.b64encode(
                signature if signature is not None else self.private_key.sign(signing_bytes)
            ).decode("ascii"),
        }
        authorization.update(dict(extra_fields or {}))
        target = authorization_path or (
            self.authorization_root
            / f"{exact_subject.get('delivery_digest', 'authorization')}.json"
        )
        body = _write_secure_json(target, authorization)
        return SignedMagicFitReviewerAuthorization(
            path=target,
            body=body,
            subject={str(key): str(value) for key, value in exact_subject.items()},
            unsigned_authorization=deepcopy(unsigned_authorization),
        )


def provision_magicfit_reviewer_test_authority(
    root: Path,
    *,
    public_tour_root: Path | None = None,
    key_id: str = DEFAULT_TEST_KEY_ID,
    authority_id: str = DEFAULT_TEST_AUTHORITY_ID,
) -> MagicFitReviewerTestAuthority:
    """Create or reuse the sole persisted reviewer authority below ``root``."""

    test_root = root.absolute()
    authority_root = test_root / _AUTHORITY_DIRECTORY
    keys_root = authority_root / "keys"
    authorization_root = authority_root / _AUTHORIZATION_DIRECTORY
    _ensure_private_directory(keys_root)
    _ensure_private_directory(authorization_root)
    resolved_public_root = (public_tour_root or (test_root / "public-property-tours")).absolute()
    _ensure_private_directory(resolved_public_root)

    private_key_path = authority_root / _PRIVATE_KEY_FILENAME
    if private_key_path.exists():
        _assert_private_file(private_key_path)
        private_key_bytes = private_key_path.read_bytes()
        if len(private_key_bytes) != 32:
            raise RuntimeError("invalid persisted MagicFit test reviewer private key")
    else:
        private_key_bytes = Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        try:
            _write_secure_bytes(private_key_path, private_key_bytes, exclusive=True)
        except FileExistsError:
            _assert_private_file(private_key_path)
            private_key_bytes = private_key_path.read_bytes()
    if len(private_key_bytes) != 32:
        raise RuntimeError("invalid persisted MagicFit test reviewer private key")

    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_path = keys_root / f"{key_id}.json"
    expected_public_key = {
        "contract_name": REVIEWER_PUBLIC_KEY_CONTRACT,
        "algorithm": REVIEWER_AUTHORIZATION_ALGORITHM,
        "key_id": key_id,
        "authority_id": authority_id,
        "public_key_base64": base64.b64encode(public_key_bytes).decode("ascii"),
    }
    if public_key_path.exists():
        _assert_private_file(public_key_path)
        if _read_json_object(public_key_path) != expected_public_key:
            raise RuntimeError("persisted MagicFit test public key does not match its private key")
    else:
        _write_secure_bytes(
            public_key_path,
            _canonical_json_bytes(expected_public_key),
            exclusive=True,
        )

    trust_store_path = authority_root / _TRUST_STORE_FILENAME
    expected_key_entry = {
        "key_id": key_id,
        "authority_id": authority_id,
        "public_key_relpath": f"keys/{key_id}.json",
        "valid_from": DEFAULT_TEST_KEY_VALID_FROM,
        "valid_until": DEFAULT_TEST_KEY_VALID_UNTIL,
        "revoked": False,
    }
    if trust_store_path.exists():
        _assert_private_file(trust_store_path)
        trust_store = _read_json_object(trust_store_path)
        keys = trust_store.get("keys")
        if (
            trust_store.get("contract_name") != REVIEWER_TRUST_STORE_CONTRACT
            or not isinstance(keys, list)
            or len(keys) != 1
            or not isinstance(keys[0], dict)
            or keys[0].get("key_id") != key_id
            or keys[0].get("authority_id") != authority_id
            or keys[0].get("public_key_relpath") != expected_key_entry["public_key_relpath"]
        ):
            raise RuntimeError("persisted MagicFit test trust store is incompatible")
    else:
        _write_secure_bytes(
            trust_store_path,
            _canonical_json_bytes(
                {
                    "contract_name": REVIEWER_TRUST_STORE_CONTRACT,
                    "keys": [expected_key_entry],
                }
            ),
            exclusive=True,
        )

    return MagicFitReviewerTestAuthority(
        root=test_root,
        public_tour_root=resolved_public_root,
        key_id=key_id,
        authority_id=authority_id,
        private_key_path=private_key_path,
        public_key_path=public_key_path,
        trust_store_path=trust_store_path,
        authorization_root=authorization_root,
    )
