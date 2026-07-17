from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from scripts.accept_magicfit_delivery import _video_probe
from scripts.verify_property_tour_controls import build_property_tour_control_receipt


ROOT = Path(__file__).resolve().parents[1]
SLUG = "locally-reviewed-magicfit"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    script: str,
    tour_root: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(tour_root)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_playable_mp4(path: Path, *, color: str = "black") -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg is required for MagicFit acceptance fixtures"
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=32x32:d=1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _materialize_pending(
    root: Path, *, color: str = "black"
) -> dict[str, Path]:
    tour_root = root / "public_tours"
    bundle = tour_root / SLUG
    bundle.mkdir(parents=True, exist_ok=True)
    manifest = bundle / "tour.json"
    if not manifest.exists():
        manifest.write_text(
            json.dumps({"slug": SLUG, "display_title": "Local review target"}),
            encoding="utf-8",
        )
    video = root / f"walkthrough-{color}.mp4"
    _write_playable_mp4(video, color=color)
    source_receipt = root / f"provider-receipt-{color}.json"
    source_receipt.write_text(
        json.dumps(
            {
                "provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "render_status": "completed",
                "target_slug": SLUG,
                "output_file": str(video.resolve()),
                "hosted_walkthrough_video_url": (
                    f"https://media.powlcdn.com/magicfit/local-review-{color}.mp4"
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    imported = _run(
        "import_magicfit_walkthrough.py",
        tour_root,
        "--slug",
        SLUG,
        "--video-path",
        str(video),
        "--source-receipt",
        str(source_receipt),
    )
    assert imported.returncode == 0, imported.stderr

    pending_path = bundle / "tour.magicfit.pending.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    staged_video = bundle / pending["staged_video_relpath"]
    final_video = bundle / pending["video_relpath"]
    accepted_sidecar = bundle / pending["accepted_sidecar_relpath"]
    probe = _video_probe(staged_video)
    contact_sheet = root / f"contact-sheet-{color}.png"
    Image.new("RGB", (96, 54), color=(28, 36, 42)).save(contact_sheet, format="PNG")
    authority = root / f"reviewer-authority-{color}.pem"
    authority.write_text(
        "-----BEGIN PUBLIC KEY-----\nfixture-local-authority\n-----END PUBLIC KEY-----\n",
        encoding="utf-8",
    )
    browser_receipt = root / f"browser-receipt-{color}.json"
    browser_receipt.write_text(
        json.dumps(
            {
                "schema": "propertyquarry.magicfit_browser_playback.v1",
                "status": "pass",
                "provider": "magicfit",
                "target_slug": SLUG,
                "observed_at": pending["generated_at"],
                "route": (
                    "operator-review://propertyquarry/magicfit/"
                    f"{SLUG}/{pending['video_sha256']}"
                ),
                "http_status": 200,
                "video_sha256": pending["video_sha256"],
                "duration_seconds": probe["duration_seconds"],
                "final_current_time": probe["duration_seconds"],
                "playback_to_end": True,
                "video_error": None,
                "console_errors": [],
                "request_failures": [],
                "benign_request_aborts": [
                    {
                        "failure": "net::ERR_ABORTED",
                        "method": "GET",
                        "resource_type": "media",
                        "route": (
                            "operator-review://propertyquarry/magicfit/"
                            f"{SLUG}/{pending['video_sha256']}"
                        ),
                    }
                ],
                "bad_responses": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    evidence = root / f"evidence-{color}.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "propertyquarry.magicfit_e2e_evidence.v1",
                "status": "pass",
                "provider": "magicfit",
                "target_slug": SLUG,
                "observed_at": pending["generated_at"],
                "source_receipt_sha256": pending["source_receipt_sha256"],
                "video": {
                    "sha256": pending["video_sha256"],
                    "size_bytes": probe["size_bytes"],
                    "duration_seconds": probe["duration_seconds"],
                },
                "checklist": {
                    "playback_to_end": True,
                    "continuous_walkthrough": True,
                    "no_visible_rotation_jump": True,
                    "intended_property_and_scope": True,
                    "no_sensitive_or_trial_branding": True,
                },
                "artifacts": {
                    "contact_sheet_sha256": _sha256(contact_sheet),
                    "browser_receipt_sha256": _sha256(browser_receipt),
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "tour_root": tour_root,
        "bundle": bundle,
        "manifest": manifest,
        "staged_video": staged_video,
        "final_video": final_video,
        "pending": pending_path,
        "accepted_sidecar": accepted_sidecar,
        "source_receipt": source_receipt,
        "contact_sheet": contact_sheet,
        "browser_receipt": browser_receipt,
        "evidence": evidence,
        "authority": authority,
    }


def _accept(
    paths: dict[str, Path], *, failpoint: str = ""
) -> subprocess.CompletedProcess[str]:
    return _run(
        "accept_magicfit_delivery.py",
        paths["tour_root"],
        "--slug",
        SLUG,
        "--source-receipt",
        str(paths["source_receipt"]),
        "--evidence-receipt",
        str(paths["evidence"]),
        "--contact-sheet",
        str(paths["contact_sheet"]),
        "--browser-receipt",
        str(paths["browser_receipt"]),
        "--reviewer-authority",
        str(paths["authority"]),
        extra_env=(
            {"PROPERTYQUARRY_MAGICFIT_ACTIVATION_FAILPOINT": failpoint}
            if failpoint
            else None
        ),
    )


def test_magicfit_acceptance_binds_exact_pending_delivery_and_evidence(
    tmp_path: Path,
) -> None:
    paths = _materialize_pending(tmp_path)
    manifest_before = paths["manifest"].read_bytes()
    video_before = paths["staged_video"].read_bytes()

    # Import is private staging only: neither the active manifest nor a public
    # media path changes before the evidence-backed acceptance commit.
    assert json.loads(manifest_before) == {
        "slug": SLUG,
        "display_title": "Local review target",
    }
    assert not paths["final_video"].exists()
    assert not paths["accepted_sidecar"].exists()

    accepted = _accept(paths)

    assert accepted.returncode == 0, accepted.stderr
    result = json.loads(accepted.stdout)
    assert result["status"] == "delivery_accepted"
    assert result["reviewer_authority_sha256"] == _sha256(paths["authority"])
    assert result["evidence_sha256"] == _sha256(paths["evidence"])
    assert paths["manifest"].read_bytes() != manifest_before
    active_manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert active_manifest["video_relpath"] == result["video_relpath"]
    assert active_manifest["magicfit_import"]["proof_status"] == "delivery_accepted"
    assert paths["final_video"].read_bytes() == video_before
    assert paths["final_video"].stat().st_mode & 0o777 == 0o644
    assert not paths["staged_video"].exists()
    assert not paths["pending"].exists()
    sidecar = json.loads(
        paths["accepted_sidecar"].read_text(encoding="utf-8")
    )
    assert sidecar["status"] == "delivery_accepted"
    assert sidecar["acceptance_status"] == "accepted"
    assert sidecar["launch_eligible"] is True
    assert sidecar["review"]["subject"]["tour_slug"] == SLUG
    assert all(sidecar["review"]["checklist"].values())
    assert paths["accepted_sidecar"].stat().st_mode & 0o777 == 0o600

    verifier = build_property_tour_control_receipt(tour_root=paths["tour_root"])
    assert verifier["provider_counts"]["magicfit"] == 1
    assert verifier["ready_provider_modes"] == ["magicfit"]


def test_magicfit_acceptance_rejects_mismatched_or_incomplete_evidence(
    tmp_path: Path,
) -> None:
    cases = (
        "wrong_video_digest",
        "failed_checklist",
        "browser_not_ended",
        "browser_arbitrary_abort",
        "changed_source_receipt",
    )
    for case in cases:
        paths = _materialize_pending(tmp_path / case)
        pending_before = paths["pending"].read_bytes()
        manifest_before = paths["manifest"].read_bytes()
        if case == "wrong_video_digest":
            evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            evidence["video"]["sha256"] = "0" * 64
            paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")
        elif case == "failed_checklist":
            evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            evidence["checklist"]["continuous_walkthrough"] = False
            paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")
        elif case == "browser_not_ended":
            browser = json.loads(paths["browser_receipt"].read_text(encoding="utf-8"))
            browser["playback_to_end"] = False
            paths["browser_receipt"].write_text(json.dumps(browser), encoding="utf-8")
            evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            evidence["artifacts"]["browser_receipt_sha256"] = _sha256(
                paths["browser_receipt"]
            )
            paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")
        elif case == "browser_arbitrary_abort":
            browser = json.loads(paths["browser_receipt"].read_text(encoding="utf-8"))
            browser["benign_request_aborts"][0]["route"] = "/unrelated"
            paths["browser_receipt"].write_text(json.dumps(browser), encoding="utf-8")
            evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
            evidence["artifacts"]["browser_receipt_sha256"] = _sha256(
                paths["browser_receipt"]
            )
            paths["evidence"].write_text(json.dumps(evidence), encoding="utf-8")
        else:
            paths["source_receipt"].write_text(
                paths["source_receipt"].read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

        rejected = _accept(paths)

        assert rejected.returncode != 0, case
        assert paths["pending"].read_bytes() == pending_before
        assert paths["manifest"].read_bytes() == manifest_before
        assert not paths["final_video"].exists()
        assert not paths["accepted_sidecar"].exists()
        verifier = build_property_tour_control_receipt(tour_root=paths["tour_root"])
        assert verifier["provider_counts"]["magicfit"] == 0


def test_magicfit_activation_crash_boundaries_preserve_old_accepted_bundle(
    tmp_path: Path,
) -> None:
    for failpoint in ("after_final_video", "after_sidecar", "after_manifest"):
        case_root = tmp_path / failpoint
        first = _materialize_pending(case_root, color="black")
        assert _accept(first).returncode == 0

        old_manifest_bytes = first["manifest"].read_bytes()
        old_manifest = json.loads(old_manifest_bytes)
        old_video = first["bundle"] / old_manifest["video_relpath"]
        old_sidecar = first["bundle"] / old_manifest["video_sidecar_relpath"]
        old_video_bytes = old_video.read_bytes()
        old_sidecar_bytes = old_sidecar.read_bytes()

        replacement = _materialize_pending(case_root, color="blue")
        assert replacement["manifest"].read_bytes() == old_manifest_bytes
        assert old_video.read_bytes() == old_video_bytes
        assert old_sidecar.read_bytes() == old_sidecar_bytes
        before = build_property_tour_control_receipt(
            tour_root=replacement["tour_root"]
        )
        assert before["provider_counts"]["magicfit"] == 1

        interrupted = _accept(replacement, failpoint=failpoint)
        assert interrupted.returncode != 0
        assert f"magicfit_activation_test_failpoint:{failpoint}" in interrupted.stderr
        assert old_video.read_bytes() == old_video_bytes
        assert old_sidecar.read_bytes() == old_sidecar_bytes
        assert replacement["pending"].is_file()

        interrupted_manifest = json.loads(
            replacement["manifest"].read_text(encoding="utf-8")
        )
        if failpoint == "after_manifest":
            assert interrupted_manifest["video_relpath"] == str(
                replacement["final_video"].relative_to(replacement["bundle"])
            )
        else:
            assert replacement["manifest"].read_bytes() == old_manifest_bytes
            assert interrupted_manifest["video_relpath"] == old_manifest["video_relpath"]

        during = build_property_tour_control_receipt(
            tour_root=replacement["tour_root"]
        )
        assert during["provider_counts"]["magicfit"] == 1

        recovered = _accept(replacement)
        assert recovered.returncode == 0, recovered.stderr
        assert not replacement["pending"].exists()
        active = json.loads(replacement["manifest"].read_text(encoding="utf-8"))
        assert active["video_relpath"] == json.loads(recovered.stdout)["video_relpath"]
        assert active["video_relpath"] != old_manifest["video_relpath"]
        assert old_video.read_bytes() == old_video_bytes
        assert old_sidecar.read_bytes() == old_sidecar_bytes
        after = build_property_tour_control_receipt(
            tour_root=replacement["tour_root"]
        )
        assert after["provider_counts"]["magicfit"] == 1
