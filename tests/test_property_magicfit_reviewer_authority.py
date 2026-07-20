from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from magicfit_test_support import (
    MagicFitReviewerTestAuthority,
    magicfit_reviewer_subject,
    provision_magicfit_reviewer_test_authority,
)
from scripts.property_magicfit_reviewer_authority import (
    MagicFitReviewerAuthorityError,
    REVIEWER_AUTHORIZATION_ALGORITHM,
    REVIEWER_AUTHORIZATION_CONTRACT,
    REVIEWER_AUTHORIZATION_DOMAIN,
    REVIEWER_TEST_OWNER_UID_ENV,
    magicfit_reviewer_test_allowed_owner_uids,
    magicfit_reviewer_authorization_signing_bytes,
    verify_magicfit_reviewer_authorization,
    verify_magicfit_reviewer_authorization_bytes,
)


NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_secure_json(path: Path, payload: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(body)
    path.chmod(0o600)
    return body


@dataclass
class ReviewerBundle:
    authority: MagicFitReviewerTestAuthority
    subject: dict[str, str]
    unsigned_authorization: dict[str, object]
    authorization_path: Path

    @property
    def private_key(self):
        return self.authority.private_key

    @property
    def trust_store_path(self) -> Path:
        return self.authority.trust_store_path

    @property
    def public_key_path(self) -> Path:
        return self.authority.public_key_path

    @property
    def public_root(self) -> Path:
        return self.authority.public_tour_root

    def write_authorization(
        self,
        unsigned: dict[str, object] | None = None,
        *,
        signature: bytes | None = None,
        extra_fields: dict[str, object] | None = None,
    ) -> bytes:
        payload = deepcopy(unsigned or self.unsigned_authorization)
        subject = payload.get("subject")
        assert isinstance(subject, dict)
        signed = self.authority.sign_authorization(
            subject=subject,
            reviewed_at=str(subject["reviewed_at"]),
            issued_at=str(payload["issued_at"]),
            expires_at=str(payload["expires_at"]),
            authorization_path=self.authorization_path,
            key_id=str(payload["key_id"]),
            authority_id=str(payload["authority_id"]),
            signature=signature,
            extra_fields=extra_fields,
        )
        return signed.body

    def verify(self, **kwargs: object):
        kwargs.setdefault("allowed_owner_uids", [os.geteuid()])
        return verify_magicfit_reviewer_authorization(
            self.authorization_path,
            expected_subject=self.subject,
            trust_store_path=self.trust_store_path,
            public_tour_root=self.public_root,
            observed_at=NOW,
            **kwargs,
        )


@pytest.fixture
def reviewer_bundle(tmp_path: Path) -> ReviewerBundle:
    key_id = "reviewer-key-2026-01"
    authority_id = "propertyquarry-release-review"
    subject = magicfit_reviewer_subject(
        delivery_digest=_digest("delivery"),
        video_sha256=_digest("video"),
        staged_manifest_sha256=_digest("manifest"),
        browser_receipt_sha256=_digest("browser"),
        evidence_receipt_sha256=_digest("evidence"),
        visual_review_sha256=_digest("visual"),
        contact_sheet_sha256=_digest("contact-sheet"),
        reviewed_at="2026-07-20T11:30:00Z",
    )
    unsigned_authorization: dict[str, object] = {
        "contract_name": REVIEWER_AUTHORIZATION_CONTRACT,
        "algorithm": REVIEWER_AUTHORIZATION_ALGORITHM,
        "key_id": key_id,
        "authority_id": authority_id,
        "issued_at": "2026-07-20T11:45:00Z",
        "expires_at": "2026-07-20T13:00:00Z",
        "subject": subject,
    }
    public_root = tmp_path / "public-property-tours"
    authority = provision_magicfit_reviewer_test_authority(
        tmp_path,
        public_tour_root=public_root,
        key_id=key_id,
        authority_id=authority_id,
    )
    bundle = ReviewerBundle(
        authority=authority,
        subject=subject,
        unsigned_authorization=unsigned_authorization,
        authorization_path=tmp_path / "review-authorizations" / "authorization.json",
    )
    bundle.write_authorization()
    return bundle


def _assert_reason(expected: str, exc_info: pytest.ExceptionInfo[MagicFitReviewerAuthorityError]) -> None:
    assert exc_info.value.reason == expected


def test_valid_authorization_returns_small_audit_projection(
    reviewer_bundle: ReviewerBundle,
) -> None:
    projection = reviewer_bundle.verify()

    authorization_body = reviewer_bundle.authorization_path.read_bytes()
    trust_store_body = reviewer_bundle.trust_store_path.read_bytes()
    key_record_body = reviewer_bundle.public_key_path.read_bytes()
    signing_bytes = magicfit_reviewer_authorization_signing_bytes(
        reviewer_bundle.unsigned_authorization
    )
    public_key_bytes = reviewer_bundle.authority.public_key_bytes

    assert signing_bytes.startswith(REVIEWER_AUTHORIZATION_DOMAIN)
    assert projection.delivery_digest == reviewer_bundle.subject["delivery_digest"]
    assert projection.key_id == "reviewer-key-2026-01"
    assert projection.authority_id == "propertyquarry-release-review"
    assert projection.reviewed_at == "2026-07-20T11:30:00Z"
    assert projection.authorization_sha256 == hashlib.sha256(
        authorization_body
    ).hexdigest()
    assert projection.signing_payload_sha256 == hashlib.sha256(
        signing_bytes
    ).hexdigest()
    assert projection.trust_store_sha256 == hashlib.sha256(
        trust_store_body
    ).hexdigest()
    assert projection.public_key_record_sha256 == hashlib.sha256(
        key_record_body
    ).hexdigest()
    assert projection.public_key_sha256 == hashlib.sha256(public_key_bytes).hexdigest()
    assert set(projection.as_dict()) == {
        "contract_name",
        "algorithm",
        "key_id",
        "authority_id",
        "delivery_digest",
        "reviewed_at",
        "issued_at",
        "expires_at",
        "authorization_sha256",
        "signing_payload_sha256",
        "subject_sha256",
        "trust_store_sha256",
        "public_key_record_sha256",
        "public_key_sha256",
    }


def test_bounded_bytes_api_supports_descriptor_read_public_artifact(
    reviewer_bundle: ReviewerBundle,
) -> None:
    authorization_bytes = reviewer_bundle.authorization_path.read_bytes()
    public_authorization_path = reviewer_bundle.public_root / "authorization.json"
    _write_secure_json(
        public_authorization_path,
        json.loads(authorization_bytes.decode("utf-8")),
    )

    projection = verify_magicfit_reviewer_authorization_bytes(
        public_authorization_path.read_bytes(),
        expected_subject=reviewer_bundle.subject,
        trust_store_path=reviewer_bundle.trust_store_path,
        public_tour_root=reviewer_bundle.public_root,
        observed_at=NOW,
        allowed_owner_uids=[os.geteuid()],
    )

    assert projection.authorization_sha256 == hashlib.sha256(
        authorization_bytes
    ).hexdigest()
    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        verify_magicfit_reviewer_authorization(
            public_authorization_path,
            expected_subject=reviewer_bundle.subject,
            trust_store_path=reviewer_bundle.trust_store_path,
            public_tour_root=reviewer_bundle.public_root,
            observed_at=NOW,
            allowed_owner_uids=[os.geteuid()],
        )
    _assert_reason("magicfit_reviewer_authorization_public_root_forbidden", exc_info)


def test_bad_signature_fails_closed(reviewer_bundle: ReviewerBundle) -> None:
    reviewer_bundle.write_authorization(signature=b"\0" * 64)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_signature_invalid", exc_info)


def test_wrong_delivery_subject_fails_before_trust(
    reviewer_bundle: ReviewerBundle,
) -> None:
    wrong_subject = {**reviewer_bundle.subject, "delivery_digest": _digest("other")}

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        verify_magicfit_reviewer_authorization(
            reviewer_bundle.authorization_path,
            expected_subject=wrong_subject,
            trust_store_path=reviewer_bundle.trust_store_path,
            public_tour_root=reviewer_bundle.public_root,
            observed_at=NOW,
            allowed_owner_uids=[os.geteuid()],
        )

    _assert_reason("magicfit_reviewer_authorization_subject_mismatch", exc_info)


def test_unknown_key_fails_closed(reviewer_bundle: ReviewerBundle) -> None:
    unsigned = deepcopy(reviewer_bundle.unsigned_authorization)
    unsigned["key_id"] = "unknown-reviewer-key"
    reviewer_bundle.write_authorization(unsigned)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_key_unknown", exc_info)


def test_expired_authorization_fails_closed(reviewer_bundle: ReviewerBundle) -> None:
    unsigned = deepcopy(reviewer_bundle.unsigned_authorization)
    unsigned["issued_at"] = "2026-07-20T10:00:00Z"
    unsigned["expires_at"] = "2026-07-20T11:00:00Z"
    reviewer_bundle.write_authorization(unsigned)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_expired_or_invalid", exc_info)


def test_authorization_exceeding_maximum_ttl_fails_closed(
    reviewer_bundle: ReviewerBundle,
) -> None:
    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify(maximum_ttl_seconds=60 * 60)

    _assert_reason("magicfit_reviewer_authorization_expired_or_invalid", exc_info)


def test_authority_validity_window_binds_review_and_authorization(
    reviewer_bundle: ReviewerBundle,
) -> None:
    reviewer_bundle.authority.update_trust_key(
        valid_from="2026-07-20T11:31:00Z"
    )

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_authority_window_invalid", exc_info)


def test_revoked_key_fails_closed(reviewer_bundle: ReviewerBundle) -> None:
    reviewer_bundle.authority.revoke()

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_key_revoked", exc_info)


@pytest.mark.parametrize(
    ("target_name", "expected_reason"),
    [
        ("trust_store", "magicfit_reviewer_trust_store_invalid"),
        ("public_key", "magicfit_reviewer_public_key_invalid"),
    ],
)
def test_symlinked_trust_material_fails_closed(
    reviewer_bundle: ReviewerBundle,
    target_name: str,
    expected_reason: str,
) -> None:
    target = (
        reviewer_bundle.trust_store_path
        if target_name == "trust_store"
        else reviewer_bundle.public_key_path
    )
    real_target = target.with_name(f"real-{target.name}")
    target.rename(real_target)
    target.symlink_to(real_target.name)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason(expected_reason, exc_info)


@pytest.mark.parametrize(
    ("target_name", "expected_reason"),
    [
        ("trust_store", "magicfit_reviewer_trust_store_invalid"),
        ("public_key", "magicfit_reviewer_public_key_invalid"),
    ],
)
def test_writable_trust_material_fails_closed(
    reviewer_bundle: ReviewerBundle,
    target_name: str,
    expected_reason: str,
) -> None:
    target = (
        reviewer_bundle.trust_store_path
        if target_name == "trust_store"
        else reviewer_bundle.public_key_path
    )
    target.chmod(0o660)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason(expected_reason, exc_info)


def test_authorization_cannot_supply_its_own_trust_anchor(
    reviewer_bundle: ReviewerBundle,
) -> None:
    reviewer_bundle.write_authorization(
        extra_fields={"public_key_base64": base64.b64encode(b"x" * 32).decode("ascii")}
    )

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_authorization_contract_invalid", exc_info)


def test_reusable_test_authority_preserves_key_trust_state_and_exact_signature(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "stable-authority"
    public_root = tmp_path / "stable-public"
    first = provision_magicfit_reviewer_test_authority(
        authority_root,
        public_tour_root=public_root,
    )
    subject = magicfit_reviewer_subject(
        delivery_digest=_digest("stable-delivery"),
        video_sha256=_digest("stable-video"),
        staged_manifest_sha256=_digest("stable-manifest"),
        browser_receipt_sha256=_digest("stable-browser"),
        evidence_receipt_sha256=_digest("stable-evidence"),
        visual_review_sha256=_digest("stable-visual"),
        contact_sheet_sha256=_digest("stable-contact-sheet"),
        reviewed_at="2026-07-20T11:30:00Z",
    )
    authorization_path = authority_root / "signed-review.json"
    first_signed = first.sign_authorization(
        subject=subject,
        reviewed_at="2026-07-20T11:30:00Z",
        issued_at="2026-07-20T11:45:00Z",
        expires_at="2026-07-20T13:00:00Z",
        authorization_path=authorization_path,
    )
    original_private_key = first.private_key_bytes
    first.revoke()

    second = provision_magicfit_reviewer_test_authority(
        authority_root,
        public_tour_root=public_root,
    )

    assert second.private_key_bytes == original_private_key
    assert second.private_key_path == first.private_key_path
    assert second.public_key_path == first.public_key_path
    assert second.trust_store_path == first.trust_store_path
    trust_store = second.read_trust_store()
    keys = trust_store["keys"]
    assert isinstance(keys, list)
    assert isinstance(keys[0], dict)
    assert keys[0]["revoked"] is True

    second.unrevoke()
    second_signed = second.sign_authorization(
        subject=subject,
        reviewed_at="2026-07-20T11:30:00Z",
        issued_at="2026-07-20T11:45:00Z",
        expires_at="2026-07-20T13:00:00Z",
        authorization_path=authorization_path,
    )
    assert second_signed.body == first_signed.body
    authorization = json.loads(second_signed.body.decode("utf-8"))
    assert authorization["subject"] == subject
    assert authorization["issued_at"] == "2026-07-20T11:45:00Z"
    assert authorization["expires_at"] == "2026-07-20T13:00:00Z"

    for path in (
        second.private_key_path,
        second.public_key_path,
        second.trust_store_path,
        authorization_path,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for path in (
        second.private_key_path.parent,
        second.public_key_path.parent,
        second.authorization_root,
        public_root,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_test_owner_override_is_explicit_and_forbidden_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REVIEWER_TEST_OWNER_UID_ENV, str(os.geteuid()))
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        magicfit_reviewer_test_allowed_owner_uids()

    _assert_reason("magicfit_reviewer_test_owner_override_invalid", exc_info)


def test_special_permission_bits_on_trust_material_fail_closed(
    reviewer_bundle: ReviewerBundle,
) -> None:
    reviewer_bundle.authority.trust_store_path.chmod(0o4600)

    with pytest.raises(MagicFitReviewerAuthorityError) as exc_info:
        reviewer_bundle.verify()

    _assert_reason("magicfit_reviewer_trust_store_invalid", exc_info)
