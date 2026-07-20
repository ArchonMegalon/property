from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import propertyquarry_walkthrough_provider_proof_gate as gate
from scripts.property_magicfit_public_eligibility import (
    clear_magicfit_public_eligibility_cache,
)
from tests.magicfit_test_support import provision_magicfit_reviewer_test_authority
from tests.test_property_tour_control_verifier import (
    _write_reproducible_magicfit_tour,
)


def _write_provider_bundle(root: Path, *, provider: str, model_consumed: bool = True) -> Path:
    slug = f"{provider}-proof-tour"
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True)
    video_relpath = (
        f"magicfit-media/tour-{provider}.{hashlib.sha256(provider.encode()).hexdigest()[:16]}.mp4"
        if provider == "magicfit"
        else f"tour-{provider}.mp4"
    )
    video_bytes = f"provider-video-{provider}".encode()
    (bundle_dir / video_relpath).parent.mkdir(parents=True, exist_ok=True)
    (bundle_dir / video_relpath).write_bytes(video_bytes)
    video_sha256 = hashlib.sha256(video_bytes).hexdigest()
    delivery_digest = hashlib.sha256(f"delivery:{slug}".encode()).hexdigest()
    sidecar_relpath = f".magicfit-deliveries/{delivery_digest}.json"
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": video_relpath,
                "video_provider_key": provider,
                "video_provider": provider,
                "video_provider_backend_key": provider,
                "video_render_provider": provider,
                "video_sidecar_relpath": sidecar_relpath if provider == "magicfit" else "tour.omagic.json",
                "magicfit_import": (
                    {"delivery_sidecar_relpath": sidecar_relpath}
                    if provider == "magicfit"
                    else None
                ),
                "flythrough_url": f"/tours/files/{slug}/{video_relpath}",
            }
        ),
        encoding="utf-8",
    )
    if provider == "magicfit":
        sidecar = {
            "contract_name": "propertyquarry.magicfit_accepted_delivery.v3",
            "provider": "MagicFit",
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "status": "accepted",
            "render_status": "completed",
            "acceptance_status": "accepted",
            "launch_eligible": True,
            "video_relpath": video_relpath,
            "video_sha256": video_sha256,
            "delivery_digest": delivery_digest,
        }
        sidecar_name = sidecar_relpath
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
    (bundle_dir / sidecar_name).parent.mkdir(parents=True, exist_ok=True)
    (bundle_dir / sidecar_name).write_text(json.dumps(sidecar), encoding="utf-8")
    return bundle_dir


def _stub_video_probe(monkeypatch, *, stub_magicfit_eligibility: bool = True) -> None:
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

    def _eligibility(bundle_dir: Path, payload: dict[str, object]) -> SimpleNamespace:
        sidecar_relpath = str(payload.get("video_sidecar_relpath") or "")
        sidecar = gate._load_json(Path(bundle_dir) / sidecar_relpath) if sidecar_relpath else {}
        declared = bool(
            str(payload.get("video_provider") or "").lower() == "magicfit"
            or sidecar_relpath.startswith(".magicfit-deliveries/")
        )
        eligible = bool(
            declared
            and sidecar.get("contract_name") == "propertyquarry.magicfit_accepted_delivery.v3"
            and sidecar.get("launch_eligible") is True
            and str(sidecar.get("acceptance_status") or "").lower() == "accepted"
        )
        return SimpleNamespace(
            declared=declared,
            eligible=eligible,
            reason="accepted_v4" if eligible else "magicfit_acceptance_invalid",
            video_relpath=str(payload.get("video_relpath") or "") if eligible else "",
            delivery_digest=str(sidecar.get("delivery_digest") or "") if eligible else "",
        )

    if stub_magicfit_eligibility:
        monkeypatch.setattr(
            gate, "evaluate_magicfit_public_eligibility", _eligibility
        )


def test_walkthrough_provider_proof_uses_real_signed_v4_magicfit_eligibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video_bytes = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        b"provider-proof-signed-v4"
    )
    _write_reproducible_magicfit_tour(
        tmp_path,
        "magicfit-proof-tour",
        video_bytes,
    )
    _write_provider_bundle(tmp_path, provider="omagic")
    _stub_video_probe(monkeypatch, stub_magicfit_eligibility=False)
    clear_magicfit_public_eligibility_cache()

    accepted = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert accepted["status"] == "pass"
    magicfit_result = next(
        row
        for row in accepted["provider_results"]
        if row["provider"] == "magicfit"
    )
    assert magicfit_result["status"] == "pass"
    assert any(
        check["name"] == "magicfit_exact_v4_public_eligible"
        and check["ok"] is True
        for check in magicfit_result["checks"]
    )

    authority = provision_magicfit_reviewer_test_authority(
        tmp_path.parent / f".{tmp_path.name}-reviewer-trust",
        public_tour_root=tmp_path,
    )
    authority.revoke()
    clear_magicfit_public_eligibility_cache()

    revoked = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert revoked["status"] == "fail"
    revoked_magicfit = next(
        row
        for row in revoked["provider_results"]
        if row["provider"] == "magicfit"
    )
    assert revoked_magicfit["status"] == "fail"
    assert any(
        check["name"] == "magicfit_exact_v4_public_eligible"
        and check["ok"] is False
        for check in revoked_magicfit["checks"]
    )


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


def test_walkthrough_provider_proof_gate_rejects_legacy_magicfit_sidecar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle_dir = tmp_path / "legacy-magicfit-proof-tour"
    bundle_dir.mkdir()
    (bundle_dir / "tour-magicfit.mp4").write_bytes(b"legacy")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": bundle_dir.name,
                "video_provider": "magicfit",
                "video_relpath": "tour-magicfit.mp4",
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "tour.magicfit.json").write_text(
        json.dumps(
            {
                "provider_key": "magicfit",
                "status": "rendered",
                "render_status": "completed",
                "video_relpath": "tour-magicfit.mp4",
            }
        ),
        encoding="utf-8",
    )
    _write_provider_bundle(tmp_path, provider="omagic")
    _stub_video_probe(monkeypatch)

    receipt = gate.build_walkthrough_provider_proof_receipt(tour_root=tmp_path)

    assert receipt["status"] == "fail"
    magicfit = next(row for row in receipt["provider_results"] if row["provider"] == "magicfit")
    failed_checks = {row["name"] for row in magicfit["checks"] if not row["ok"]}
    assert "magicfit_exact_v4_public_eligible" in failed_checks
    assert "accepted_sidecar_present" in failed_checks


def test_walkthrough_provider_proof_gate_propagates_hash_disqualification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rejected = _write_provider_bundle(tmp_path, provider="magicfit")
    rejected_manifest = json.loads((rejected / "tour.json").read_text(encoding="utf-8"))
    rejected_sidecar_path = rejected / str(rejected_manifest["video_sidecar_relpath"])
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
    assert "magicfit_exact_v4_public_eligible" in failed_checks
    assert receipt["disqualified_video_sha256s"] == []
