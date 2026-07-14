from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import propertyquarry_walkthrough_provider_proof_gate as gate


def _write_provider_bundle(root: Path, *, provider: str, model_consumed: bool = True) -> Path:
    slug = f"{provider}-proof-tour"
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True)
    video_relpath = f"tour-{provider}.mp4"
    video_bytes = f"provider-video-{provider}".encode()
    (bundle_dir / video_relpath).write_bytes(video_bytes)
    video_sha256 = hashlib.sha256(video_bytes).hexdigest()
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": video_relpath,
                "video_provider_key": provider,
                "video_provider": provider,
                "flythrough_url": f"/tours/files/{slug}/{video_relpath}",
            }
        ),
        encoding="utf-8",
    )
    if provider == "magicfit":
        sidecar = {
            "provider": "MagicFit",
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "status": "rendered",
            "render_status": "completed",
            "video_relpath": video_relpath,
            "composition": "boundary_verified_frame_continuation",
            "segment_count": 2,
            "duration_seconds": 30.0,
            "required_duration_seconds": 30.0,
            "route_labels": ["entry", "living room"],
            "covered_route_labels": ["entry", "living room"],
            "video_sha256": video_sha256,
        }
        sidecar_name = "tour.magicfit.json"
    else:
        sidecar = {
            "provider_key": "omagic",
            "provider_backend_key": "omagic",
            "status": "rendered",
            "render_status": "completed",
            "video_relpath": video_relpath,
            "model_path": "generated-reconstruction/model.glb",
            "model_input_consumed": model_consumed,
            "model_input_consumption_proof": "omagic-command-adapter",
            "video_sha256": video_sha256,
        }
        sidecar_name = "tour.omagic.json"
    (bundle_dir / sidecar_name).write_text(json.dumps(sidecar), encoding="utf-8")
    return bundle_dir


def _stub_video_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        gate,
        "_video_metadata",
        lambda path, timeout_seconds=20.0: {
            "ok": True,
            "duration_seconds": 30.0,
            "width": 1280,
            "height": 720,
            "size_bytes": path.stat().st_size,
            "error": "",
        },
    )
    monkeypatch.setattr(gate, "_video_decodes", lambda path, timeout_seconds=30.0: (True, ""))


def test_walkthrough_provider_proof_gate_requires_real_magicfit_and_omagic_bundle_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_provider_bundle(tmp_path, provider="magicfit")
    _write_provider_bundle(tmp_path, provider="omagic")
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["verified_providers"] == ["magicfit", "omagic"]
    assert receipt["verified_orchestrators"] == ["ea"]
    assert receipt["indexed_participants"] == ["ea", "magicfit", "omagic"]
    assert receipt["missing_providers"] == []
    assert receipt["failed_count"] == 0
    ea = receipt["provenance_index"][0]
    assert ea == {
        "key": "ea",
        "kind": "orchestrator",
        "role": "governance_and_verification",
        "status": "pass",
        "media_authorship": False,
        "evidence_contract": "propertyquarry.walkthrough_provider_proof_gate.v1",
    }
    media_rows = receipt["provenance_index"][1:]
    assert [row["key"] for row in media_rows] == ["magicfit", "omagic"]
    assert all(row["media_authorship"] is True for row in media_rows)
    results_by_provider = {
        row["provider"]: row for row in receipt["provider_results"]
    }
    for row in media_rows:
        result = results_by_provider[row["key"]]
        assert row["evidence_bundle_slug"] == result["slug"]
        assert row["evidence_video_relpath"] == result["video_relpath"]
        assert row["evidence_video_sha256"] == result["video_sha256"]


def test_walkthrough_provider_proof_gate_does_not_treat_readiness_or_magicfit_only_as_parity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_provider_bundle(tmp_path, provider="magicfit")
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "fail"
    assert receipt["verified_providers"] == ["magicfit"]
    assert receipt["verified_orchestrators"] == []
    assert receipt["indexed_participants"] == ["ea", "magicfit", "omagic"]
    assert receipt["provenance_index"][0]["status"] == "fail"
    assert receipt["missing_providers"] == ["omagic"]
    omagic = next(row for row in receipt["provider_results"] if row["provider"] == "omagic")
    assert omagic["status"] == "fail"


def test_walkthrough_provider_proof_gate_rejects_omagic_without_explicit_model_consumption(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_provider_bundle(tmp_path, provider="magicfit")
    _write_provider_bundle(tmp_path, provider="omagic", model_consumed=False)
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "fail"
    omagic = next(row for row in receipt["provider_results"] if row["provider"] == "omagic")
    failed_checks = {row["name"] for row in omagic["checks"] if not row["ok"]}
    assert failed_checks == {"omagic_model_input_consumed"}


def test_walkthrough_provider_proof_gate_rejects_malformed_magicfit_numeric_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_dir = _write_provider_bundle(tmp_path, provider="magicfit")
    _write_provider_bundle(tmp_path, provider="omagic")
    sidecar_path = bundle_dir / "tour.magicfit.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["segment_count"] = "not-a-number"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "fail"
    magicfit = next(row for row in receipt["provider_results"] if row["provider"] == "magicfit")
    failed_checks = {row["name"] for row in magicfit["checks"] if not row["ok"]}
    assert failed_checks == {"magicfit_segment_count"}


def test_walkthrough_provider_proof_gate_propagates_hash_disqualification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rejected = _write_provider_bundle(tmp_path, provider="magicfit")
    duplicate = tmp_path / "magicfit-duplicate-proof-tour"
    duplicate.mkdir()
    for source in rejected.iterdir():
        (duplicate / source.name).write_bytes(source.read_bytes())
    duplicate_video_path = duplicate / "tour-magicfit.mp4"
    duplicate_video_path.write_bytes(b"re-encoded-provider-video-magicfit")
    duplicate_sidecar_path = duplicate / "tour.magicfit.json"
    duplicate_sidecar = json.loads(duplicate_sidecar_path.read_text(encoding="utf-8"))
    duplicate_sidecar["video_sha256"] = hashlib.sha256(
        b"re-encoded-provider-video-magicfit"
    ).hexdigest()
    duplicate_sidecar_path.write_text(json.dumps(duplicate_sidecar), encoding="utf-8")
    rejected_sidecar_path = rejected / "tour.magicfit.json"
    rejected_sidecar = json.loads(rejected_sidecar_path.read_text(encoding="utf-8"))
    rejected_sidecar["acceptance_status"] = "disqualified"
    rejected_sidecar["launch_eligible"] = False
    rejected_sidecar_path.write_text(json.dumps(rejected_sidecar), encoding="utf-8")
    _write_provider_bundle(tmp_path, provider="omagic")
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "fail"
    assert receipt["verified_orchestrators"] == []
    magicfit = next(row for row in receipt["provider_results"] if row["provider"] == "magicfit")
    assert magicfit["media_disqualified"] is True
    failed_checks = {row["name"] for row in magicfit["checks"] if not row["ok"]}
    assert failed_checks == {"media_not_disqualified"}
    assert receipt["disqualified_video_sha256s"] == [hashlib.sha256(b"provider-video-magicfit").hexdigest()]
    assert len(receipt["disqualified_walkthrough_family_fingerprints"]) == 1
