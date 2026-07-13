from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.api.routes.public_tours import _tour_control_external_iframe_html
from scripts.verify_property_tour_controls import (
    _best_tour_root,
    _load_cli_env_defaults,
    _receipt_summary,
    _running_container_public_tour_dir,
    _runtime_container_live_probe_receipt,
    build_property_tour_control_receipt,
    main,
)


def _write_tour(root: Path, slug: str, payload: dict[str, object], files: dict[str, str | bytes] | None = None) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    body = {"slug": slug, "title": slug, **payload}
    (bundle / "tour.json").write_text(json.dumps(body), encoding="utf-8")
    for relpath, content in (files or {}).items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def _write_playable_mp4(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg is required for playable MagicFit verifier fixtures")
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:d=1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def _write_equirectangular_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2048, 1024), color=(28, 42, 36))
    image.save(path, format="JPEG")


def _clean_3dvista_proof() -> dict[str, object]:
    return {
        "three_d_vista_white_label_proof": {
            "source_project": "propertyquarry",
            "private_viewer_verified": True,
            "non_trial_export_verified": True,
            "propertyquarry_tour_metadata": True,
            "trial_branding_checked": True,
            "trial_branding_present": False,
        },
        "three_d_vista_browser_render_proof": {
            "provider": "3dvista",
            "status": "pass",
            "rendered_viewer": True,
        },
    }


def _clean_3dvista_private_viewer_proof() -> dict[str, object]:
    proof = _clean_3dvista_proof()
    proof.pop("three_d_vista_browser_render_proof", None)
    return proof


def test_best_tour_root_prefers_fresher_runtime_snapshot(tmp_path: Path) -> None:
    sparse = tmp_path / "sparse"
    rich = tmp_path / "rich"
    (sparse / "only-one").mkdir(parents=True)
    (rich / "one").mkdir(parents=True)
    (rich / "two").mkdir(parents=True)
    (sparse / "only-one" / "tour.json").write_text("{}", encoding="utf-8")
    (rich / "one" / "tour.json").write_text("{}", encoding="utf-8")
    (rich / "two" / "tour.json").write_text("{}", encoding="utf-8")
    sparse_mtime = (sparse / "only-one" / "tour.json").stat().st_mtime
    os.utime(rich / "two" / "tour.json", (sparse_mtime + 5, sparse_mtime + 5))

    assert _best_tour_root([sparse, rich]) == rich


def test_best_tour_root_prefers_earlier_candidate_when_freshness_matches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    runtime_root = tmp_path / "runtime"
    for root, slug in ((repo_root, "current"), (runtime_root, "archive")):
        bundle = root / slug
        bundle.mkdir(parents=True)
        (bundle / "tour.json").write_text("{}", encoding="utf-8")
    shared_mtime = (repo_root / "current" / "tour.json").stat().st_mtime
    os.utime(runtime_root / "archive" / "tour.json", (shared_mtime, shared_mtime))

    assert _best_tour_root([repo_root, runtime_root]) == repo_root


def test_running_container_public_tour_dir_reads_docker_mount(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-public-tours"
    runtime_root.mkdir()
    monkeypatch.setenv("PROPERTYQUARRY_RUNTIME_CONTAINER", "propertyquarry-api")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{runtime_root}\n", stderr=""),
    )

    assert _running_container_public_tour_dir() == runtime_root


def test_property_tour_control_verifier_live_probe_prefers_runtime_root_when_no_explicit_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    runtime_root = tmp_path / "runtime"
    _write_tour(
        host_root,
        "host-only-3dvista",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_private_viewer_proof()},
        {"3dvista/index.html": "<html><script src='tdvplayer.js'></script><div>tourviewer</div></html>"},
    )
    _write_tour(
        runtime_root,
        "runtime-matterport",
        {"matterport_url": "https://my.matterport.com/show/?m=READY123"},
    )
    monkeypatch.setattr("scripts.verify_property_tour_controls._tour_root", lambda: host_root)
    monkeypatch.setattr("scripts.verify_property_tour_controls._running_container_public_tour_dir", lambda *_args, **_kwargs: runtime_root)
    monkeypatch.setattr(
        "scripts.verify_property_tour_controls._probe_url",
        lambda *_args, **_kwargs: {"http_status": 200, "body_markers": {"matterport": True}},
    )

    receipt = build_property_tour_control_receipt(
        tour_root=None,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["tour_root"] == str(runtime_root.resolve())
    assert receipt["tour_root_source"] == "runtime_container"
    assert receipt["tour_count"] == 1
    assert receipt["tours"][0]["slug"] == "runtime-matterport"
    assert receipt["provider_counts"]["matterport"] == 1
    assert receipt["provider_counts"]["3dvista"] == 0


def test_property_tour_control_verifier_live_probe_uses_runtime_snapshot_when_mount_is_inaccessible(
    monkeypatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    runtime_root = tmp_path / "runtime-snapshot"
    _write_tour(
        host_root,
        "host-only-3dvista",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_private_viewer_proof()},
        {"3dvista/index.html": "<html><script src='tdvplayer.js'></script><div>tourviewer</div></html>"},
    )
    _write_tour(
        runtime_root,
        "runtime-matterport",
        {"matterport_url": "https://my.matterport.com/show/?m=READY123"},
    )

    class _SnapshotHandle:
        def cleanup(self) -> None:
            return None

    monkeypatch.setattr("scripts.verify_property_tour_controls._tour_root", lambda: host_root)
    monkeypatch.setattr("scripts.verify_property_tour_controls._running_container_public_tour_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "scripts.verify_property_tour_controls._snapshot_runtime_container_public_tours",
        lambda *_args, **_kwargs: (runtime_root, _SnapshotHandle()),
    )
    monkeypatch.setattr(
        "scripts.verify_property_tour_controls._probe_url",
        lambda *_args, **_kwargs: {"http_status": 200, "body_markers": {"matterport": True}},
    )

    receipt = build_property_tour_control_receipt(
        tour_root=None,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["tour_root"] == str(runtime_root.resolve())
    assert receipt["tour_root_source"] == "runtime_container_snapshot"
    assert receipt["tour_count"] == 1
    assert receipt["tours"][0]["slug"] == "runtime-matterport"
    assert receipt["provider_counts"]["matterport"] == 1


def test_public_tour_control_labels_manual_video_as_video_evidence_not_walkthrough() -> None:
    html_body = _tour_control_external_iframe_html(
        title="Manual media loft",
        iframe_src="https://my.matterport.com/show/?m=abc123",
        badge="3D Tour",
        payload={
            "slug": "manual-media-loft",
            "video_provider": "manual_upload",
            "video_relpath": "tour.mp4",
            "scenes": [{"name": "Living room", "asset_relpath": "living.jpg", "role": "photo"}],
        },
    )

    assert 'data-video-provider="manual_upload"' not in html_body
    assert 'data-walkthrough-ready="false"' not in html_body
    assert '<div class="card-label">Video</div>' not in html_body
    assert "Open walkthrough" in html_body
    assert "/tours/manual-media-loft/walkthrough" in html_body
    assert "MagicFit walkthrough" not in html_body
    assert '<div class="card-label">Walkthrough</div>' not in html_body
    assert "my.matterport.com" not in html_body
    assert 'data-src="about:blank"' in html_body


def test_public_tour_control_labels_magicfit_video_as_magicfit_walkthrough() -> None:
    html_body = _tour_control_external_iframe_html(
        title="Walkthrough loft",
        iframe_src="https://propertyquarry.com/tours/files/walkthrough-loft/matterport.html",
        badge="Matterport Control",
        payload={
            "slug": "walkthrough-loft",
            "video_provider": "magicfit",
            "video_relpath": "walkthrough.mp4",
            "scenes": [{"name": "Living room", "asset_relpath": "living.jpg", "role": "photo"}],
        },
    )

    assert 'data-video-provider="magicfit"' not in html_body
    assert 'data-walkthrough-ready="true"' not in html_body
    assert '<div class="card-label">Walkthrough</div>' not in html_body
    assert "Open walkthrough" in html_body
    assert "/tours/walkthrough-loft/walkthrough" in html_body
    assert "magicfit" not in html_body
    assert "MagicFit walkthrough" not in html_body
    assert "Video evidence" not in html_body


def test_property_tour_control_verifier_accepts_private_receipt_matterport_without_url_leak(tmp_path: Path) -> None:
    _write_tour(tmp_path, "private-matterport", {})
    private_receipt = tmp_path / "private-matterport" / "tour.private.json"
    private_receipt.write_text(
        json.dumps({"matterport_url": "https://my.matterport.com/show/?m=PRIVATE123"}),
        encoding="utf-8",
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["matterport"] == 1
    assert receipt["ready_provider_modes"] == ["matterport"]
    assert "PRIVATE123" not in json.dumps(receipt)


def test_property_tour_control_verifier_cli_loads_krpano_license_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("KRPANO_LICENSE_DOMAIN", raising=False)
    monkeypatch.delenv("KRPANO_LICENSE_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "KRPANO_LICENSE_DOMAIN=propertyquarry.com\nKRPANO_LICENSE_KEY=licensed-from-env-file\n",
        encoding="utf-8",
    )

    _load_cli_env_defaults()

    assert os.environ["KRPANO_LICENSE_DOMAIN"] == "propertyquarry.com"
    assert os.environ["KRPANO_LICENSE_KEY"] == "licensed-from-env-file"


def test_property_tour_control_verifier_accepts_private_receipt_3dvista_without_url_leak(tmp_path: Path) -> None:
    _write_tour(tmp_path, "private-3dvista", _clean_3dvista_proof())
    private_receipt = tmp_path / "private-3dvista" / "tour.private.json"
    private_receipt.write_text(
        json.dumps({"three_d_vista_url": "https://example.3dvista.com/tours/PRIVATE3D/index.html"}),
        encoding="utf-8",
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["3dvista"] == 1
    assert receipt["ready_provider_modes"] == ["3dvista"]
    assert "PRIVATE3D" not in json.dumps(receipt)


def test_property_tour_control_verifier_accepts_private_receipt_pano2vr_without_path_leak(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "private-pano2vr",
        {},
        {"pano2vr/private-entry.html": "<!doctype html><script src='tour.js'></script><div>Pano2VR</div>"},
    )
    private_receipt = tmp_path / "private-pano2vr" / "tour.private.json"
    private_receipt.write_text(
        json.dumps(
            {
                "pano2vr_entry_relpath": "pano2vr/private-entry.html",
                "listing_url": "https://private.example.test/pano2vr-source",
                "source_ref": "PRIVATEPANO2VR",
            }
        ),
        encoding="utf-8",
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["pano2vr"] == 1
    assert receipt["ready_provider_modes"] == ["pano2vr"]
    serialized = json.dumps(receipt)
    assert "PRIVATEPANO2VR" not in serialized
    assert "private.example.test" not in serialized
    assert "private-entry" not in serialized


def test_property_tour_control_verifier_summary_omits_tour_rows(tmp_path: Path) -> None:
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=SUMMARY123"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)
    summary = _receipt_summary(receipt)

    assert summary["status"] == "pass"
    assert summary["provider_counts"]["matterport"] == 1
    assert "tours" not in summary
    assert "SUMMARY123" not in json.dumps(summary)


def test_property_tour_control_verifier_next_actions_only_include_globally_missing_modes(tmp_path: Path) -> None:
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=READY123"})
    _write_tour(tmp_path, "blocked-gallery", {"scene_strategy": "photo_gallery_hosted"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["ready_provider_modes"] == ["matterport"]
    assert set(receipt["missing_provider_modes"]) == {"3dvista", "magicfit"}
    assert {row["provider"] for row in receipt["next_required_actions"]} == {
        "3dvista",
        "magicfit",
    }


def test_property_tour_control_verifier_can_require_all_provider_modes_for_gold_gate(tmp_path: Path) -> None:
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=READY123"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path, require_all_provider_modes=True)
    summary = _receipt_summary(receipt)

    assert receipt["status"] == "blocked_missing_provider_modes"
    assert receipt["require_all_provider_modes"] is True
    assert summary["require_all_provider_modes"] is True
    assert receipt["ready_provider_modes"] == ["matterport"]
    assert set(receipt["missing_provider_modes"]) == {"3dvista", "magicfit"}
    assert {row["provider"] for row in receipt["next_required_actions"]} == {
        "3dvista",
        "magicfit",
    }
    assert summary["provider_blockers"]["3dvista"]["blocked_count"] == 1
    assert summary["provider_blockers"]["3dvista"]["reasons"][0]["reason"] == "missing_3dvista_export"
    assert summary["provider_blockers"]["pano2vr"]["reasons"][0]["reason"] == "missing_pano2vr_export"
    assert summary["provider_blockers"]["magicfit"]["reasons"][0]["reason"] == "missing_magicfit_walkthrough"


def test_property_tour_control_verifier_cli_fails_closed_for_blocked_gold_gate(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=READY123"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_property_tour_controls.py",
            "--tour-root",
            str(tmp_path),
            "--require-all-provider-modes",
            "--fail-on-blocked",
            "--summary-only",
        ],
    )

    exit_code = main()

    assert exit_code == 2
    output = capsys.readouterr().out
    assert '"status": "blocked_missing_provider_modes"' in output
    assert '"missing_provider_modes"' in output


def test_property_tour_control_verifier_cli_delegates_live_probe_to_runtime_container_when_mount_is_inaccessible(
    monkeypatch,
    capsys,
) -> None:
    delegated_receipt = {
        "generated_at": "2026-07-04T21:20:00+00:00",
        "status": "pass",
        "tour_root": "/data/public_property_tours",
        "tour_root_source": "explicit",
        "tour_count": 1,
        "ready_tour_count": 1,
        "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 0, "krpano": 0, "magicfit": 1},
        "provider_blockers": {provider: {"blocked_count": 0, "reasons": []} for provider in ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")},
        "ready_provider_modes": ["3dvista", "magicfit", "matterport"],
        "required_provider_modes": ["matterport", "3dvista", "magicfit"],
        "missing_provider_modes": [],
        "next_required_actions": [],
        "live_probe": True,
        "base_url": "https://propertyquarry.example",
        "require_all_provider_modes": False,
        "tours": [],
    }
    monkeypatch.setattr("scripts.verify_property_tour_controls._running_container_public_tour_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "scripts.verify_property_tour_controls.build_property_tour_control_receipt",
        lambda **_kwargs: {
            "generated_at": "2026-07-04T21:19:00+00:00",
            "status": "blocked_no_tour_manifests",
            "tour_root": "/docker/property/state/public_property_tours",
            "tour_root_source": "preferred",
            "tour_count": 0,
            "ready_tour_count": 0,
            "provider_counts": {"matterport": 0, "3dvista": 0, "pano2vr": 0, "krpano": 0, "magicfit": 0},
            "provider_blockers": {
                provider: {"blocked_count": 0, "reasons": []}
                for provider in ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
            },
            "ready_provider_modes": [],
            "required_provider_modes": ["matterport", "3dvista", "magicfit"],
            "missing_provider_modes": ["matterport", "3dvista", "magicfit"],
            "next_required_actions": [],
            "live_probe": True,
            "base_url": "https://propertyquarry.example",
            "require_all_provider_modes": False,
            "tours": [],
        },
    )
    monkeypatch.setattr(
        "scripts.verify_property_tour_controls._runtime_container_live_probe_receipt",
        lambda **_kwargs: (dict(delegated_receipt), 0),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_property_tour_controls.py",
            "--base-url",
            "https://propertyquarry.example",
            "--live-probe",
            "--summary-only",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"status": "pass"' in output
    assert '"tour_root": "/data/public_property_tours"' in output


def test_runtime_container_live_probe_receipt_rewrites_loopback_base_url(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.verify_property_tour_controls.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("scripts.verify_property_tour_controls._runtime_container_name", lambda: "propertyquarry-api")

    def _run(command, **_kwargs):
        commands.append(list(command))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "generated_at": "2026-07-05T08:50:00+00:00",
                    "status": "pass",
                    "tour_root": "/data/public_property_tours",
                    "tour_root_source": "preferred",
                    "tour_count": 1,
                    "ready_tour_count": 1,
                    "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 0, "krpano": 0, "magicfit": 1},
                    "provider_blockers": {
                        provider: {"blocked_count": 0, "reasons": []}
                        for provider in ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
                    },
                    "ready_provider_modes": ["3dvista", "magicfit", "matterport"],
                    "required_provider_modes": ["matterport", "3dvista", "magicfit"],
                    "missing_provider_modes": [],
                    "next_required_actions": [],
                    "live_probe": True,
                    "base_url": "http://127.0.0.1:8090",
                    "require_all_provider_modes": False,
                    "tours": [],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("scripts.verify_property_tour_controls.subprocess.run", _run)

    receipt, exit_code = _runtime_container_live_probe_receipt(
        base_url="http://127.0.0.1:8097",
        host_header="propertyquarry.com",
        timeout_seconds=5.0,
        require_all_provider_modes=False,
    )

    assert exit_code == 0
    assert receipt is not None
    assert "--base-url" in commands[0]
    assert "http://127.0.0.1:8090" in commands[0]
    assert receipt["host_requested_base_url"] == "http://127.0.0.1:8097"
    assert receipt["container_probe_base_url"] == "http://127.0.0.1:8090"
    assert receipt["base_url"] == "http://127.0.0.1:8090"


def test_property_tour_control_verifier_counts_provider_gaps_on_ready_tours(tmp_path: Path) -> None:
    _write_tour(tmp_path, "matterport-only", {"matterport_url": "https://my.matterport.com/show/?m=READY123"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path, require_all_provider_modes=True)

    actions = {row["provider"]: row for row in receipt["next_required_actions"]}
    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert receipt["status"] == "blocked_missing_provider_modes"
    assert receipt["tours"][0]["status"] == "ready"
    assert set(receipt["required_provider_modes"]) == {"3dvista", "magicfit"}
    assert set(missing) == {"3dvista", "magicfit"}
    assert missing["3dvista"]["reason"] == "missing_3dvista_export"
    assert missing["magicfit"]["reason"] == "missing_magicfit_walkthrough"
    assert set(receipt["tours"][0]["missing_provider_modes"]) == {"3dvista", "magicfit"}
    assert actions["3dvista"]["blocked_tour_count"] == 1
    assert actions["magicfit"]["blocked_tour_count"] == 1


def test_property_tour_control_verifier_distinguishes_empty_provider_placeholder_fields(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "placeholder-fields",
        {
            "matterport_url": "https://my.matterport.com/show/?m=READY123",
            "three_d_vista_url": "",
            "pano2vr_entry_relpath": "",
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path, require_all_provider_modes=True)

    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert missing["3dvista"]["reason"] == "3dvista_placeholder_field_empty_or_unusable"
    assert "empty 3DVista placeholder" in missing["3dvista"]["action"]
    assert "pano2vr" not in missing
    assert {row["provider"] for row in receipt["tours"][0]["optional_missing_evidence"]} == {"pano2vr"}
    assert receipt["provider_blockers"]["pano2vr"]["reasons"][0]["reason"] == "pano2vr_placeholder_field_empty_or_unusable"


def test_property_tour_control_verifier_reports_all_verified_provider_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=abc"})
    _write_tour(
        tmp_path,
        "3dvista-tour",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_proof()},
        {
            "3dvista/index.html": "<html><script src='runtime/app.js'></script><div>3DVista shell</div></html>",
            "3dvista/runtime/app.js": "window.TDVPlayer = true;",
        },
    )
    _write_tour(
        tmp_path,
        "pano2vr-tour",
        {"pano2vr_entry_relpath": "pano/index.html"},
        {
            "pano/index.html": "<html><script src='assets/viewer.js'></script></html>",
            "pano/assets/viewer.js": "window.GGSKIN = true;",
        },
    )
    panorama = tmp_path / "verified-panorama.jpg"
    _write_equirectangular_image(panorama)
    _write_tour(
        tmp_path,
        "krpano-tour",
        {
            "scene_strategy": "walkable_panorama",
            "creation_mode": "hosted_walkable_360",
            "walkable_scene": {"projection": "equirectangular", "panorama_relpath": "krpano/panorama.jpg"},
        },
        {"krpano/panorama.jpg": panorama.read_bytes()},
    )
    playable_magicfit = tmp_path / "walkthrough.mp4"
    _write_playable_mp4(playable_magicfit)
    _write_tour(
        tmp_path,
        "magicfit-tour",
        {"video_provider": "magicfit", "video_relpath": "walkthrough.mp4"},
        {"walkthrough.mp4": playable_magicfit.read_bytes()},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"] == {
        "matterport": 1,
        "3dvista": 1,
        "pano2vr": 1,
        "krpano": 1,
        "magicfit": 1,
    }
    assert receipt["missing_provider_modes"] == []
    assert all("matterport.com/show" not in json.dumps(tour) for tour in receipt["tours"])


def test_property_tour_control_verifier_does_not_count_failed_live_probe_as_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "3dvista-tour",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_private_viewer_proof()},
        {"3dvista/index.html": "<html><script src='tdvplayer.js'></script><div>tourviewer</div></html>"},
    )

    def _failed_probe(*_args, **_kwargs) -> dict[str, object]:
        return {"http_status": 503, "error": "unavailable"}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _failed_probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["status"] == "fail"
    assert receipt["provider_counts"]["3dvista"] == 0
    assert "3dvista" not in receipt["ready_provider_modes"]
    assert "3dvista" in receipt["missing_provider_modes"]
    assert receipt["tours"][0]["controls"][0]["status"] == "probe_failed"


def test_property_tour_control_verifier_keeps_hidden_optional_pano2vr_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "matterport-with-hidden-pano2vr",
        {
            "matterport_url": "https://my.matterport.com/show/?m=READY123",
            "pano2vr_entry_relpath": "pano/index.html",
        },
        {"pano/index.html": "<!doctype html><script src='tour.js'></script><div>Pano2VR</div>"},
    )

    def _probe(url: str, *, provider: str = "", **_kwargs) -> dict[str, object]:
        if provider == "pano2vr":
            return {"http_status": 404, "error": "hidden", "error_code": "tour_control_panorama_export_hidden"}
        return {"http_status": 200, "body_markers": {"matterport": True}}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
        require_all_provider_modes=True,
    )

    controls = {row["provider"]: row for row in receipt["tours"][0]["controls"]}
    assert receipt["status"] == "blocked_missing_provider_modes"
    assert receipt["provider_counts"]["matterport"] == 1
    assert receipt["provider_counts"]["pano2vr"] == 1
    assert receipt["ready_provider_modes"] == ["matterport", "pano2vr"]
    assert receipt["hidden_ready_provider_modes"] == ["pano2vr"]
    assert set(receipt["missing_provider_modes"]) == {"3dvista", "magicfit"}
    assert controls["pano2vr"]["status"] == "ready"
    assert controls["pano2vr"]["route_visibility"] == "hidden_by_product_boundary"


def test_property_tour_control_verifier_keeps_hidden_optional_krpano_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "matterport-with-hidden-krpano",
        {
            "matterport_url": "https://my.matterport.com/show/?m=READY123",
            "walkable_scene": {"projection": "equirectangular", "panorama_relpath": "krpano/panorama.jpg"},
        },
    )
    _write_equirectangular_image(tmp_path / "matterport-with-hidden-krpano" / "krpano" / "panorama.jpg")
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "demo-license")

    def _probe(url: str, *, provider: str = "", **_kwargs) -> dict[str, object]:
        if provider == "krpano":
            return {"http_status": 404, "error": "hidden", "error_code": "tour_control_panorama_export_hidden"}
        return {"http_status": 200, "body_markers": {"matterport": True}}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
        require_all_provider_modes=True,
    )

    controls = {row["provider"]: row for row in receipt["tours"][0]["controls"]}
    assert receipt["status"] == "blocked_missing_provider_modes"
    assert receipt["provider_counts"]["matterport"] == 1
    assert receipt["provider_counts"]["krpano"] == 1
    assert receipt["ready_provider_modes"] == ["krpano", "matterport"]
    assert receipt["hidden_ready_provider_modes"] == ["krpano"]
    assert set(receipt["missing_provider_modes"]) == {"3dvista", "magicfit"}
    assert controls["krpano"]["status"] == "ready"
    assert controls["krpano"]["route_visibility"] == "hidden_by_product_boundary"


def test_property_tour_control_verifier_marks_optional_pano2vr_probe_failed_when_hidden_code_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "matterport-with-broken-pano2vr",
        {
            "matterport_url": "https://my.matterport.com/show/?m=READY123",
            "pano2vr_entry_relpath": "pano/index.html",
        },
        {"pano/index.html": "<!doctype html><script src='tour.js'></script><div>Pano2VR</div>"},
    )

    def _probe(url: str, *, provider: str = "", **_kwargs) -> dict[str, object]:
        if provider == "pano2vr":
            return {"http_status": 404, "error": "missing"}
        return {"http_status": 200, "body_markers": {"matterport": True}}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
        require_all_provider_modes=True,
    )

    controls = {row["provider"]: row for row in receipt["tours"][0]["controls"]}
    assert receipt["provider_counts"]["pano2vr"] == 0
    assert receipt["ready_provider_modes"] == ["matterport"]
    assert "hidden_ready_provider_modes" in receipt
    assert receipt["hidden_ready_provider_modes"] == []
    assert controls["pano2vr"]["status"] == "optional_probe_failed"


def test_property_tour_control_verifier_rejects_wrong_provider_live_probe_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "3dvista-tour",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_private_viewer_proof()},
        {"3dvista/index.html": "<html><script src='tdvplayer.js'></script><div>tourviewer</div></html>"},
    )

    def _wrong_provider_probe(*_args, **_kwargs) -> dict[str, object]:
        return {"http_status": 200, "body_markers": {"matterport": True, "3dvista": False}}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _wrong_provider_probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["status"] == "fail"
    assert receipt["provider_counts"]["3dvista"] == 0
    assert "3dvista" not in receipt["ready_provider_modes"]
    assert receipt["tours"][0]["controls"][0]["status"] == "probe_failed"


def test_property_tour_control_verifier_counts_successful_3dvista_live_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "3dvista-tour",
        {"three_d_vista_entry_relpath": "3dvista/index.html", **_clean_3dvista_private_viewer_proof()},
        {"3dvista/index.html": "<html><script src='tdvplayer.js'></script><div>tourviewer</div></html>"},
    )

    def _successful_3dvista_probe(*_args, **_kwargs) -> dict[str, object]:
        return {"http_status": 200, "body_markers": {"3dvista": True}}

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _successful_3dvista_probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["3dvista"] == 1
    assert receipt["ready_provider_modes"] == ["3dvista"]
    assert receipt["tours"][0]["controls"][0]["evidence"] == "local_3dvista_export_entry"


def test_property_tour_control_verifier_rejects_magicfit_placeholder_video(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "magicfit-placeholder",
        {"video_provider": "magicfit", "video_relpath": "walkthrough.mp4"},
        {"walkthrough.mp4": "video"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["magicfit"] == 0
    assert receipt["tours"][0]["blocked_reason"] == "missing_verified_provider_control"


def test_property_tour_control_verifier_rejects_magicfit_signature_only_stub(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "magicfit-stub",
        {"video_provider": "magicfit", "video_relpath": "walkthrough.mp4"},
        {"walkthrough.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["magicfit"] == 0
    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert missing["magicfit"]["reason"] == "magicfit_video_missing_or_unplayable"


def test_property_tour_control_verifier_requires_live_probe_for_remote_magicfit_video(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "remote-magicfit",
        {
            "video_provider": "magicfit",
            "video_url": "https://propertyquarry.com/tours/files/remote-magicfit/walkthrough.mp4",
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["magicfit"] == 0
    assert receipt["ready_provider_modes"] == []
    control = receipt["tours"][0]["controls"][0]
    assert control["provider"] == "magicfit"
    assert control["status"] == "probe_required"
    assert control["evidence"] == "allowlisted_magicfit_video_url_pending_probe"
    assert "_probe_url" not in control
    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert missing["magicfit"]["reason"] == "magicfit_remote_video_needs_live_probe"
    assert "remote-magicfit/walkthrough.mp4" not in json.dumps(receipt)


def test_property_tour_control_verifier_counts_remote_magicfit_after_successful_live_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "remote-magicfit-ready",
        {
            "video_provider": "magicfit",
            "video_url": "https://propertyquarry.com/tours/files/remote-magicfit-ready/walkthrough.mp4",
        },
    )
    seen_urls: list[str] = []

    def _successful_probe(url: str, *_args, **_kwargs) -> dict[str, object]:
        seen_urls.append(url)
        return {
            "http_status": 200,
            "content_type": "video/mp4",
            "playback_markers": {
                "video_content_type": True,
                "video_signature": True,
                "video_stream": True,
                "duration_positive": True,
            },
        }

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _successful_probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["magicfit"] == 1
    assert receipt["magicfit_playback"]["playback_ok"] is True
    assert receipt["magicfit_playback"]["playable_count"] == 1
    assert receipt["magicfit_playback"]["ready_count"] == 1
    assert receipt["ready_provider_modes"] == ["magicfit"]
    assert seen_urls == ["https://propertyquarry.com/tours/files/remote-magicfit-ready/walkthrough.mp4"]
    control = receipt["tours"][0]["controls"][0]
    assert control["status"] == "ready"
    assert control["evidence"] == "live_probed_magicfit_video_url"
    assert "_probe_url" not in control
    assert "remote-magicfit-ready/walkthrough.mp4" not in json.dumps(receipt)


def test_property_tour_control_verifier_rejects_remote_magicfit_failed_live_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_tour(
        tmp_path,
        "remote-magicfit-failed",
        {
            "video_provider": "magicfit",
            "video_url": "https://propertyquarry.com/tours/files/remote-magicfit-failed/walkthrough.mp4",
        },
    )

    def _failed_probe(*_args, **_kwargs) -> dict[str, object]:
        return {
            "http_status": 200,
            "content_type": "text/html",
            "playback_markers": {
                "video_content_type": False,
                "video_signature": False,
            },
        }

    monkeypatch.setattr("scripts.verify_property_tour_controls._probe_url", _failed_probe)

    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path,
        base_url="https://propertyquarry.example",
        live_probe=True,
    )

    assert receipt["status"] == "fail"
    assert receipt["provider_counts"]["magicfit"] == 0
    assert "magicfit" not in receipt["ready_provider_modes"]
    assert receipt["tours"][0]["status"] == "blocked_missing_verified_controls"
    assert receipt["tours"][0]["controls"][0]["status"] == "probe_failed"


def test_property_tour_control_verifier_rejects_placeholder_local_3d_exports(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "placeholder-3dvista",
        {"three_d_vista_entry_relpath": "3dvista/index.html"},
        {"3dvista/index.html": "<html><body>Coming soon</body></html>"},
    )
    _write_tour(
        tmp_path,
        "placeholder-pano2vr",
        {"pano2vr_entry_relpath": "pano/index.html"},
        {"pano/index.html": "<html><body>Static placeholder</body></html>"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["3dvista"] == 0
    assert receipt["provider_counts"]["pano2vr"] == 0
    assert {tour["blocked_reason"] for tour in receipt["tours"]} == {"missing_verified_provider_control"}


def test_property_tour_control_verifier_blocks_when_no_verified_controls(tmp_path: Path) -> None:
    _write_tour(tmp_path, "fallback-tour", {"scene_strategy": "pure_360_cube"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["ready_provider_modes"] == []
    assert receipt["tours"][0]["status"] == "blocked_missing_verified_controls"
    assert receipt["tours"][0]["blocked_reason"] == "generated_cube_not_verified_3d"
    assert set(receipt["missing_provider_modes"]) == {"3dvista", "magicfit"}


def test_property_tour_control_verifier_marks_photo_gallery_as_not_3d(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "gallery-tour",
        {
            "creation_mode": "hosted_photo_gallery_tour",
            "scene_strategy": "photo_gallery_hosted",
            "scenes": [{"asset_relpath": "photo-01.jpg", "role": "photo"}],
        },
        {"photo-01.jpg": "image"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"] == {
        "matterport": 0,
        "3dvista": 0,
        "pano2vr": 0,
        "krpano": 0,
        "magicfit": 0,
    }
    assert receipt["tours"][0]["blocked_reason"] == "gallery_only_not_3d"
    assert receipt["tours"][0]["controls"] == []
    assert receipt["tours"][0]["missing_evidence"] == []
    assert {row["provider"] for row in receipt["next_required_actions"]} == {
        "3dvista",
        "magicfit",
    }


def test_property_tour_control_verifier_reports_actionable_missing_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRPANO_LICENSE_DOMAIN", raising=False)
    monkeypatch.delenv("KRPANO_LICENSE_KEY", raising=False)
    _write_tour(
        tmp_path,
        "partial-provider-tour",
        {
            "matterport_url": "https://tracker.example/show/?m=abc",
            "three_d_vista_entry_relpath": "3dvista/index.html",
            "pano2vr_entry_relpath": "pano/index.html",
            "video_provider": "stock",
            "video_relpath": "walkthrough.mp4",
            "walkable_scene": {"rooms": []},
        },
        {
            "3dvista/index.html": "<html><body>placeholder</body></html>",
            "pano/index.html": "<html><body>placeholder</body></html>",
            "walkthrough.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert "matterport" not in missing
    assert receipt["provider_blockers"]["matterport"]["reasons"][0]["reason"] == "matterport_url_not_allowlisted_or_invalid"
    assert missing["3dvista"]["reason"] == "3dvista_entry_missing_or_not_verified"
    assert "pano2vr" not in missing
    assert receipt["provider_blockers"]["pano2vr"]["reasons"][0]["reason"] == "pano2vr_entry_missing_or_not_verified"
    assert "krpano" not in missing
    assert {row["provider"] for row in receipt["tours"][0]["optional_missing_evidence"]} == {"pano2vr", "krpano"}
    assert missing["magicfit"]["reason"] == "walkthrough_provider_not_magicfit"
    assert "tracker.example" not in json.dumps(receipt)


def test_property_tour_control_verifier_does_not_treat_private_or_missing_assets_as_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("KRPANO_LICENSE_DOMAIN", raising=False)
    monkeypatch.delenv("KRPANO_LICENSE_KEY", raising=False)
    _write_tour(
        tmp_path,
        "unsafe-tour",
        {
            "matterport_url": "https://tracker.example/show/?m=abc",
            "three_d_vista_entry_relpath": "../private/index.html",
            "pano2vr_entry_relpath": "missing/index.html",
            "video_provider": "magicfit",
            "video_relpath": "private.txt",
            "walkable_scene": {"rooms": []},
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"] == {
        "matterport": 0,
        "3dvista": 0,
        "pano2vr": 0,
        "krpano": 0,
        "magicfit": 0,
    }
