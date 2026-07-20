from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from scripts.property_magicfit_delivery_contract import (
    MagicFitContractError,
    coverage_proof_from_receipt,
    validate_magicfit_coverage_proof,
    validate_magicfit_source_receipt,
)
from scripts.property_magicfit_secure_io import (
    MagicFitSecureIOError,
    collect_bounded_magicfit_stage_orphans,
    copy_magicfit_stage_video,
    create_magicfit_stage_directory,
    remove_closed_magicfit_stage,
    remove_empty_magicfit_stage,
    require_complete_magicfit_stage,
    write_magicfit_stage_bytes,
)


SLUG = "strict-magicfit-tour"
HOSTED_URL = "https://media.powlcdn.com/magicfit/strict-tour.mp4?token=opaque"


def _source_receipt() -> dict[str, object]:
    return {
        "provider": "magicfit",
        "provider_backend_key": "magicfit",
        "provider_key": "magicfit",
        "render_status": "completed",
        "target_slug": SLUG,
        "property_slug": SLUG,
        "hosted_walkthrough_video_url": HOSTED_URL,
        "video_output_url": HOSTED_URL,
    }


def _coverage_proof() -> dict[str, object]:
    return {
        "status": "pass",
        "segments_expected": ["entry", "living"],
        "segments_visited": ["living", "entry"],
        "coverage_segments": [
            {"segment": "entry", "start": 0, "end": 3.5},
            {"segment": "living", "start": 3.5, "end": 9},
        ],
    }


def test_source_receipt_normalizes_equivalent_host_aliases() -> None:
    receipt = _source_receipt()
    receipt["hosted_walkthrough_video_url"] = (
        "HTTPS://MEDIA.POWLCDN.COM/magicfit/strict-tour.mp4?token=opaque"
    )

    assert validate_magicfit_source_receipt(receipt, slug=SLUG) == HOSTED_URL


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "MagicFit"),
        ("provider_backend_key", "magicfit "),
        ("provider_key", 1),
        ("render_status", "Completed"),
        ("target_slug", f"{SLUG}-other"),
        ("property_slug", f"{SLUG} "),
    ),
)
def test_source_receipt_rejects_any_conflicting_explicit_alias(
    field: str, value: object
) -> None:
    receipt = _source_receipt()
    receipt[field] = value

    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(receipt, slug=SLUG)


def test_source_receipt_allows_omitted_provider_identity_aliases() -> None:
    receipt = _source_receipt()
    for field in ("provider", "provider_backend_key", "provider_key"):
        receipt.pop(field)

    assert validate_magicfit_source_receipt(receipt, slug=SLUG) == HOSTED_URL


def test_source_contract_does_not_claim_importer_output_file_equality() -> None:
    receipt = _source_receipt()
    receipt["output_file"] = {"untrusted": "consumer-specific"}

    assert validate_magicfit_source_receipt(receipt, slug=SLUG) == HOSTED_URL


def test_source_receipt_requires_one_explicit_slug_alias() -> None:
    receipt = _source_receipt()
    receipt.pop("target_slug")
    receipt.pop("property_slug")

    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(receipt, slug=SLUG)


def test_source_receipt_rejects_empty_expected_and_declared_slug() -> None:
    receipt = _source_receipt()
    receipt["target_slug"] = ""
    receipt["property_slug"] = ""

    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(receipt, slug="")


@pytest.mark.parametrize(
    "url",
    (
        "http://media.powlcdn.com/magicfit/strict-tour.mp4",
        "https://user:secret@media.powlcdn.com/magicfit/strict-tour.mp4",
        "https://media.powlcdn.com:443/magicfit/strict-tour.mp4",
        "https://media.powlcdn.com.evil.example/magicfit/strict-tour.mp4",
        "https://media.powlcdn.com/not-magicfit/strict-tour.mp4",
        "https://media.powlcdn.com/magicfit/strict-tour.txt",
        "https://media.powlcdn.com/magicfit/strict-tour.mp4#ignored",
        "https://media.powlcdn.com/magicfit/%2e%2e/strict-tour.mp4",
        "https://media.powlcdn.com/magicfit/strict tour.mp4",
    ),
)
def test_source_receipt_rejects_unsafe_hosted_urls(url: str) -> None:
    receipt = _source_receipt()
    receipt["hosted_walkthrough_video_url"] = url
    receipt.pop("video_output_url")

    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(receipt, slug=SLUG)


def test_source_receipt_rejects_missing_or_ambiguous_hosted_url_aliases() -> None:
    missing = _source_receipt()
    missing.pop("hosted_walkthrough_video_url")
    missing.pop("video_output_url")
    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(missing, slug=SLUG)

    ambiguous = _source_receipt()
    ambiguous["video_output_url"] = (
        "https://cdn.pushowl.com/magicfit/different.webm"
    )
    with pytest.raises(MagicFitContractError):
        validate_magicfit_source_receipt(ambiguous, slug=SLUG)


def test_coverage_absence_is_empty_and_canonical_aliases_may_agree() -> None:
    assert coverage_proof_from_receipt(_source_receipt()) == {}
    proof = _coverage_proof()
    receipt = {
        **_source_receipt(),
        "coverage_proof": proof,
        "walkthrough_coverage_proof": dict(reversed(list(proof.items()))),
    }

    assert coverage_proof_from_receipt(receipt) == proof


def test_coverage_aliases_cannot_disagree_or_hide_malformed_values() -> None:
    receipt = {**_source_receipt(), "coverage_proof": _coverage_proof()}
    conflicting = _coverage_proof()
    conflicting["segments_visited"] = ["entry"]
    receipt["walkthrough_coverage_proof"] = conflicting
    with pytest.raises(MagicFitContractError):
        coverage_proof_from_receipt(receipt)

    receipt = {**_source_receipt(), "coverage_proof": None}
    with pytest.raises(MagicFitContractError):
        coverage_proof_from_receipt(receipt)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda proof: proof.update(status="failed"),
        lambda proof: proof.update(segments_expected="entry"),
        lambda proof: proof.update(segments_expected=("entry", "living")),
        lambda proof: proof.update(segments_expected=["entry", "entry"]),
        lambda proof: proof.update(segments_visited=["entry"]),
        lambda proof: proof.update(segments_visited=["entry", 2]),
        lambda proof: proof.update(coverage_segments=[]),
        lambda proof: proof["coverage_segments"][0].update(start=-1),
        lambda proof: proof["coverage_segments"][0].update(start=True),
        lambda proof: proof["coverage_segments"][0].update(end=float("inf")),
        lambda proof: proof["coverage_segments"][0].update(end=10**1000),
        lambda proof: proof["coverage_segments"][0].update(end=0),
        lambda proof: proof["coverage_segments"][0].update(extra="ambiguous"),
        lambda proof: proof["coverage_segments"][1].update(segment="entry"),
    ),
)
def test_coverage_rejects_failed_incomplete_or_malformed_proofs(mutate) -> None:
    proof = _coverage_proof()
    mutate(proof)

    with pytest.raises(MagicFitContractError):
        validate_magicfit_coverage_proof(proof)


def _stage_video(
    tmp_path: Path, bundle: Path, digest: str, *, suffix: str = ".mp4"
) -> str:
    source = tmp_path / f"source{suffix}"
    source.write_bytes(b"closed-stage-video")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    copy_magicfit_stage_video(
        source,
        bundle,
        digest,
        name=f"video{suffix}",
        expected_sha256=source_sha256,
        maximum_bytes=1024,
    )
    write_magicfit_stage_bytes(
        bundle,
        digest,
        name="tour.json",
        body=b'\n{"slug":"strict"}\n',
        maximum_bytes=1024,
    )
    require_complete_magicfit_stage(bundle, digest, video_name=f"video{suffix}")
    return source_sha256


def test_stage_lifecycle_uses_closed_lowercase_digest_layout(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    digest = "a" * 64

    assert create_magicfit_stage_directory(bundle, digest) is True
    expected_digest = _stage_video(tmp_path, bundle, digest)
    stage = bundle / ".magicfit-staging" / digest
    assert sorted(path.name for path in stage.iterdir()) == ["tour.json", "video.mp4"]
    assert hashlib.sha256((stage / "video.mp4").read_bytes()).hexdigest() == expected_digest
    assert remove_closed_magicfit_stage(bundle, digest) is True
    assert not stage.exists()

    with pytest.raises(MagicFitSecureIOError):
        create_magicfit_stage_directory(bundle, "A" * 64)


def test_stage_root_and_closed_files_never_follow_symlinks(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (bundle / ".magicfit-staging").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MagicFitSecureIOError):
        create_magicfit_stage_directory(bundle, "b" * 64)
    assert list(outside.iterdir()) == []

    (bundle / ".magicfit-staging").unlink()
    digest = "b" * 64
    create_magicfit_stage_directory(bundle, digest)
    outside_file = outside / "authority.json"
    outside_file.write_text("do-not-touch", encoding="utf-8")
    stage = bundle / ".magicfit-staging" / digest
    (stage / "tour.json").symlink_to(outside_file)
    assert remove_closed_magicfit_stage(bundle, digest) is False
    assert outside_file.read_text(encoding="utf-8") == "do-not-touch"
    with pytest.raises(MagicFitSecureIOError):
        write_magicfit_stage_bytes(
            bundle,
            digest,
            name="tour.json",
            body=b"{}\n",
            maximum_bytes=1024,
        )


def test_orphan_collection_is_bounded_and_protects_selected_digest(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    protected = "c" * 64
    orphan_one = "d" * 64
    orphan_two = "e" * 64
    for digest in (protected, orphan_one, orphan_two):
        create_magicfit_stage_directory(bundle, digest)
        _stage_video(tmp_path, bundle, digest)

    removed = collect_bounded_magicfit_stage_orphans(
        bundle,
        protected_digests={protected},
        scan_limit=16,
        removal_limit=1,
    )

    stage_root = bundle / ".magicfit-staging"
    assert removed == 1
    assert (stage_root / protected).is_dir()
    assert sum((stage_root / digest).exists() for digest in (orphan_one, orphan_two)) == 1


def test_empty_selected_stage_is_removed_without_recursive_deletion(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    digest = "f" * 64
    create_magicfit_stage_directory(bundle, digest)

    assert remove_empty_magicfit_stage(bundle, digest) is True
    assert not (bundle / ".magicfit-staging" / digest).exists()


def test_closed_stage_cleanup_refuses_hardlinked_unknown_authority(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    digest = "1" * 64
    create_magicfit_stage_directory(bundle, digest)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"authority")
    stage_file = bundle / ".magicfit-staging" / digest / "tour.json"
    os.link(outside, stage_file)

    assert remove_closed_magicfit_stage(bundle, digest) is False
    assert outside.read_bytes() == b"authority"
    assert stage_file.exists()
