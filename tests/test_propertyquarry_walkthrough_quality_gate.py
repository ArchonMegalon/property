from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import propertyquarry_walkthrough_quality_gate as gate


def _write_quality_bundle(root: Path) -> tuple[str, str, str]:
    slug = "magicfit-proof-tour"
    video_relpath = "magicfit-walkthrough.mp4"
    bundle = root / slug
    bundle.mkdir(parents=True)
    video_bytes = b"reviewed-magicfit-walkthrough"
    (bundle / video_relpath).write_bytes(video_bytes)
    (bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": video_relpath,
                "video_sidecar_relpath": "tour.magicfit.json",
            }
        ),
        encoding="utf-8",
    )
    (bundle / "tour.magicfit.json").write_text(
        json.dumps(
            {
                "route_labels": ["entry", "living room", "kitchen"],
                "covered_route_labels": ["entry", "living room", "kitchen"],
            }
        ),
        encoding="utf-8",
    )
    return slug, video_relpath, hashlib.sha256(video_bytes).hexdigest()


def _write_provider_proof(
    path: Path,
    *,
    slug: str,
    video_relpath: str,
    video_sha256: str,
    include_provenance_evidence: bool = True,
) -> Path:
    magicfit_provenance = {
        "key": "magicfit",
        "kind": "media_provider",
        "role": "walkthrough_media_provider",
        "status": "pass",
        "media_authorship": True,
    }
    if include_provenance_evidence:
        magicfit_provenance.update(
            {
                "evidence_bundle_slug": slug,
                "evidence_video_relpath": video_relpath,
                "evidence_video_sha256": video_sha256,
            }
        )
    path.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.walkthrough_provider_proof_gate.v1",
                "status": "pass",
                "provider_results": [
                    {
                        "provider": "magicfit",
                        "status": "pass",
                        "slug": slug,
                        "video_relpath": video_relpath,
                        "video_sha256": video_sha256,
                    },
                    {
                        "provider": "omagic",
                        "status": "pass",
                        "slug": "omagic-proof-tour",
                        "video_relpath": "omagic-walkthrough.mp4",
                        "video_sha256": "b" * 64,
                    },
                ],
                "provenance_index": [
                    {
                        "key": "ea",
                        "kind": "orchestrator",
                        "role": "governance_and_verification",
                        "status": "pass",
                        "media_authorship": False,
                    },
                    magicfit_provenance,
                    {
                        "key": "omagic",
                        "kind": "media_provider",
                        "role": "walkthrough_media_provider",
                        "status": "pass",
                        "media_authorship": True,
                        "evidence_bundle_slug": "omagic-proof-tour",
                        "evidence_video_relpath": "omagic-walkthrough.mp4",
                        "evidence_video_sha256": "b" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _stub_video_analysis(monkeypatch) -> None:
    monkeypatch.setattr(
        gate,
        "_video_metadata",
        lambda path, timeout_seconds=None: {
            "format": {"duration": "45.0", "size": str(path.stat().st_size)},
            "streams": [{"width": 1280, "height": 720, "duration": "45.0"}],
        },
    )
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda path, **kwargs: {
            "ok": True,
            "max_delta": 18.0,
            "sampled_frame_count": 30,
        },
    )


def _build(root: Path, proof: Path) -> dict[str, object]:
    return gate.build_walkthrough_quality_receipt(
        tour_root=str(root),
        demo_slug=gate.DEFAULT_DEMO_SLUG,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
        provider_proof_receipt_path=str(proof),
    )


def test_walkthrough_quality_binds_to_exact_magicfit_provider_media(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug, video_relpath, video_sha256 = _write_quality_bundle(tmp_path)
    proof = _write_provider_proof(
        tmp_path / "provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    _stub_video_analysis(monkeypatch)

    receipt = _build(tmp_path, proof)

    assert receipt["status"] == "pass"
    assert receipt["selection_source"] == "provider_proof_receipt"
    assert receipt["video_sha256"] == video_sha256
    assert receipt["provider_media_binding"] == {
        "provider": "magicfit",
        "bundle_slug": slug,
        "video_relpath": video_relpath,
        "bundle_media_path": f"{slug}/{video_relpath}",
        "video_sha256": video_sha256,
    }


def test_walkthrough_quality_rejects_media_tampered_after_provider_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug, video_relpath, video_sha256 = _write_quality_bundle(tmp_path)
    proof = _write_provider_proof(
        tmp_path / "provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    (tmp_path / slug / video_relpath).write_bytes(b"tampered-walkthrough")
    _stub_video_analysis(monkeypatch)

    receipt = _build(tmp_path, proof)

    assert receipt["status"] == "fail"
    failed = {row["name"] for row in receipt["checks"] if not row["ok"]}
    assert "walkthrough_provider_media_sha256_matches" in failed


def test_walkthrough_quality_does_not_fall_back_to_generated_reconstruction_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug, video_relpath, video_sha256 = _write_quality_bundle(tmp_path)
    bundle = tmp_path / slug
    (bundle / "tour.magicfit.json").write_text(
        json.dumps({"route_labels": [], "covered_route_labels": []}),
        encoding="utf-8",
    )
    manifest_path = bundle / "tour.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generated_reconstruction"] = {
        "walkthrough_video_relpath": video_relpath,
        "walkthrough_coverage_proof": {
            "status": "pass",
            "segments_expected": ["entry", "living room", "kitchen"],
            "segments_visited": ["entry", "living room", "kitchen"],
            "coverage_segments": [
                {"segment": "entry"},
                {"segment": "living room"},
                {"segment": "kitchen"},
            ],
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proof = _write_provider_proof(
        tmp_path / "provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    _stub_video_analysis(monkeypatch)

    receipt = _build(tmp_path, proof)

    assert receipt["status"] == "fail"
    assert receipt["walkthrough_candidate"] == "provider_proof_media"
    failed = {row["name"] for row in receipt["checks"] if not row["ok"]}
    assert "walkthrough_room_coverage_receipt_present" in failed
    assert "walkthrough_room_coverage_complete" in failed


def test_walkthrough_quality_rejects_unsafe_or_legacy_provider_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug, video_relpath, video_sha256 = _write_quality_bundle(tmp_path)
    unsafe_proof = _write_provider_proof(
        tmp_path / "unsafe-provider-proof.json",
        slug=slug,
        video_relpath="../outside.mp4",
        video_sha256=video_sha256,
    )
    legacy_proof = _write_provider_proof(
        tmp_path / "legacy-provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
        include_provenance_evidence=False,
    )
    duplicate_proof = _write_provider_proof(
        tmp_path / "duplicate-provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    duplicate_payload = json.loads(duplicate_proof.read_text(encoding="utf-8"))
    duplicate_payload["provider_results"].append(
        dict(duplicate_payload["provider_results"][0])
    )
    duplicate_proof.write_text(json.dumps(duplicate_payload), encoding="utf-8")
    _stub_video_analysis(monkeypatch)

    unsafe_receipt = _build(tmp_path, unsafe_proof)
    legacy_receipt = _build(tmp_path, legacy_proof)
    duplicate_receipt = _build(tmp_path, duplicate_proof)

    assert unsafe_receipt["status"] == "fail"
    assert legacy_receipt["status"] == "fail"
    for receipt in (unsafe_receipt, legacy_receipt):
        failed = {row["name"] for row in receipt["checks"] if not row["ok"]}
        assert "walkthrough_provider_media_provenance_matches" in failed
    duplicate_failed = {
        row["name"] for row in duplicate_receipt["checks"] if not row["ok"]
    }
    assert "walkthrough_provider_magicfit_result_unique" in duplicate_failed


def test_walkthrough_quality_rejects_bundle_symlink_outside_tour_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tour_root = tmp_path / "tour-root"
    tour_root.mkdir()
    slug, video_relpath, video_sha256 = _write_quality_bundle(tour_root)
    outside_bundle = tmp_path / "outside-bundle"
    (tour_root / slug).rename(outside_bundle)
    (tour_root / slug).symlink_to(outside_bundle, target_is_directory=True)
    proof = _write_provider_proof(
        tmp_path / "provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    _stub_video_analysis(monkeypatch)

    receipt = _build(tour_root, proof)

    assert receipt["status"] == "fail"
    failed = {row["name"] for row in receipt["checks"] if not row["ok"]}
    assert "walkthrough_bundle_path_inside_tour_root" in failed


def test_walkthrough_quality_rejects_noncanonical_manifest_media_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug, video_relpath, video_sha256 = _write_quality_bundle(tmp_path)
    manifest_path = tmp_path / slug / "tour.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["video_relpath"] = f" {video_relpath} "
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    proof = _write_provider_proof(
        tmp_path / "provider-proof.json",
        slug=slug,
        video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    _stub_video_analysis(monkeypatch)

    receipt = _build(tmp_path, proof)

    assert receipt["status"] == "fail"
    assert receipt["video_relpath"] == ""
    declared = next(
        row for row in receipt["checks"] if row["name"] == "walkthrough_video_declared"
    )
    assert declared["raw_video_relpath"] == f" {video_relpath} "
