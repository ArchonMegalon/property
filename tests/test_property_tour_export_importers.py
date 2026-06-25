from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from scripts.verify_property_tour_controls import build_property_tour_control_receipt


ROOT = Path(__file__).resolve().parents[1]


def _run_importer(script_name: str, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(tmp_path / "public_tours")
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _write_base_tour(tmp_path: Path, slug: str) -> Path:
    bundle_dir = tmp_path / "public_tours" / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps({"slug": slug, "display_title": "Import target"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return bundle_dir


def _write_playable_mp4(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AssertionError("ffmpeg is required for playable MagicFit importer fixtures")
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
    image = Image.new("RGB", (2048, 1024), color=(28, 42, 36))
    image.save(path, format="JPEG")


def test_3dvista_importer_requires_verified_export_markers(tmp_path: Path) -> None:
    slug = "verified-3dvista-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    placeholder_export = tmp_path / "placeholder_3dvista"
    placeholder_export.mkdir()
    (placeholder_export / "index.html").write_text("<!doctype html><title>Coming soon</title>", encoding="utf-8")

    rejected = _run_importer(
        "import_3dvista_export.py",
        tmp_path,
        "--slug",
        slug,
        "--export-dir",
        str(placeholder_export),
    )

    assert rejected.returncode != 0
    assert "3dvista_export_entry_unverified" in rejected.stderr
    assert not (bundle_dir / "3dvista" / "index.html").exists()
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert "three_d_vista_entry_relpath" not in manifest

    verified_export = tmp_path / "verified_3dvista"
    verified_export.mkdir()
    (verified_export / "index.html").write_text(
        "<!doctype html><script src='tdvplayer.js'></script><div>3DVista tourviewer</div>",
        encoding="utf-8",
    )
    (verified_export / "tdvplayer.js").write_text("window.TDVPlayer = true;", encoding="utf-8")

    imported = _run_importer(
        "import_3dvista_export.py",
        tmp_path,
        "--slug",
        slug,
        "--export-dir",
        str(verified_export),
    )

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["control_url"] == f"/tours/{slug}/control/3dvista"
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["control_mode"] == "3dvista"
    assert manifest["viewer_provider"] == "3dvista_vt_pro"
    assert manifest["three_d_vista_entry_relpath"] == "3dvista/index.html"
    assert (bundle_dir / "3dvista" / "tdvplayer.js").exists()


def test_pano2vr_importer_materializes_verified_export_and_rejects_placeholders(tmp_path: Path) -> None:
    slug = "verified-pano2vr-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    placeholder_export = tmp_path / "placeholder_pano2vr"
    placeholder_export.mkdir()
    (placeholder_export / "index.html").write_text("<!doctype html><title>Static placeholder</title>", encoding="utf-8")

    rejected = _run_importer(
        "import_pano2vr_export.py",
        tmp_path,
        "--slug",
        slug,
        "--export-dir",
        str(placeholder_export),
    )

    assert rejected.returncode != 0
    assert "pano2vr_export_entry_unverified" in rejected.stderr
    assert not (bundle_dir / "pano2vr" / "index.html").exists()
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert "pano2vr_entry_relpath" not in manifest

    verified_export = tmp_path / "verified_pano2vr"
    verified_export.mkdir()
    (verified_export / "index.html").write_text(
        "<!doctype html><script src='tour.js'></script><div>Pano2VR</div>",
        encoding="utf-8",
    )
    (verified_export / "tour.js").write_text("window.GGSKIN = true;", encoding="utf-8")

    imported = _run_importer(
        "import_pano2vr_export.py",
        tmp_path,
        "--slug",
        slug,
        "--export-dir",
        str(verified_export),
    )

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["control_url"] == f"/tours/{slug}/control/pano2vr"
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["control_mode"] == "pano2vr"
    assert manifest["viewer_provider"] == "pano2vr"
    assert manifest["pano2vr_entry_relpath"] == "pano2vr/index.html"
    assert (bundle_dir / "pano2vr" / "tour.js").exists()


def test_batch_tour_export_importer_materializes_verified_3dvista_and_pano2vr_exports(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "batch-3dvista")
    _write_base_tour(tmp_path, "batch-pano2vr")
    vista_export = tmp_path / "batch_vista_export"
    vista_export.mkdir()
    (vista_export / "index.html").write_text(
        "<!doctype html><script src='tdvplayer.js'></script><div>3DVista tourviewer</div>",
        encoding="utf-8",
    )
    (vista_export / "tdvplayer.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    pano_export = tmp_path / "batch_pano_export"
    pano_export.mkdir()
    (pano_export / "index.html").write_text(
        "<!doctype html><script src='tour.js'></script><div>Pano2VR</div>",
        encoding="utf-8",
    )
    (pano_export / "tour.js").write_text("window.GGSKIN = true;", encoding="utf-8")
    manifest_path = tmp_path / "tour-imports.json"
    receipt_path = tmp_path / "tour-import-receipt.json"
    manifest_path.write_text(
        json.dumps(
            {
                "imports": [
                    {"slug": "batch-3dvista", "provider": "3dvista", "export_dir": str(vista_export)},
                    {"slug": "batch-pano2vr", "provider": "pano2vr", "export_dir": str(pano_export)},
                ]
            }
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(public_root)
    imported = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "import_property_tour_exports.py"),
            "--manifest",
            str(manifest_path),
            "--write",
            str(receipt_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert imported.returncode == 0, imported.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["imported_count"] == 2
    assert {row["provider"] for row in receipt["imports"]} == {"3dvista", "pano2vr"}
    assert all(row["status"] == "imported" for row in receipt["imports"])
    assert "batch_vista_export" not in json.dumps(receipt)
    vista_manifest = json.loads((public_root / "batch-3dvista" / "tour.json").read_text(encoding="utf-8"))
    pano_manifest = json.loads((public_root / "batch-pano2vr" / "tour.json").read_text(encoding="utf-8"))
    assert vista_manifest["control_mode"] == "3dvista"
    assert pano_manifest["control_mode"] == "pano2vr"
    verifier = build_property_tour_control_receipt(tour_root=public_root)
    assert verifier["provider_counts"]["3dvista"] == 1
    assert verifier["provider_counts"]["pano2vr"] == 1


def test_batch_tour_export_importer_fails_placeholder_rows_without_false_ready(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "batch-placeholder")
    placeholder_export = tmp_path / "placeholder_export"
    placeholder_export.mkdir()
    (placeholder_export / "index.html").write_text("<!doctype html><title>Coming soon</title>", encoding="utf-8")
    manifest_path = tmp_path / "tour-imports.json"
    receipt_path = tmp_path / "tour-import-receipt.json"
    manifest_path.write_text(
        json.dumps({"imports": [{"slug": "batch-placeholder", "provider": "pano2vr", "export_dir": str(placeholder_export)}]}),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(public_root)
    rejected = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "import_property_tour_exports.py"),
            "--manifest",
            str(manifest_path),
            "--write",
            str(receipt_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert rejected.returncode == 1
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "fail"
    assert receipt["failed_count"] == 1
    assert receipt["imports"][0]["error"] == "pano2vr_export_entry_unverified"
    verifier = build_property_tour_control_receipt(tour_root=public_root)
    assert verifier["provider_counts"]["pano2vr"] == 0


def test_magicfit_importer_materializes_playable_walkthrough_and_rejects_placeholders(tmp_path: Path) -> None:
    slug = "verified-magicfit-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    placeholder_video = tmp_path / "placeholder.mp4"
    placeholder_video.write_bytes(b"not a playable video")

    rejected = _run_importer(
        "import_magicfit_walkthrough.py",
        tmp_path,
        "--slug",
        slug,
        "--video-path",
        str(placeholder_video),
    )

    assert rejected.returncode != 0
    assert "magicfit_video_unverified" in rejected.stderr
    assert not (bundle_dir / "magicfit-walkthrough.mp4").exists()
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert "video_relpath" not in manifest
    assert "magicfit_import" not in manifest

    stub_video = tmp_path / "signature-only.mp4"
    stub_video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    stub_rejected = _run_importer(
        "import_magicfit_walkthrough.py",
        tmp_path,
        "--slug",
        slug,
        "--video-path",
        str(stub_video),
        "--allow-unreceipted-test-asset",
    )

    assert stub_rejected.returncode != 0
    assert "magicfit_video_unverified" in stub_rejected.stderr
    assert not (bundle_dir / "magicfit-walkthrough.mp4").exists()

    playable_video = tmp_path / "walkthrough.mp4"
    _write_playable_mp4(playable_video)
    unreceipted = _run_importer(
        "import_magicfit_walkthrough.py",
        tmp_path,
        "--slug",
        slug,
        "--video-path",
        str(playable_video),
    )

    assert unreceipted.returncode != 0
    assert "magicfit_receipt_missing" in unreceipted.stderr
    assert not (bundle_dir / "magicfit-walkthrough.mp4").exists()

    receipt_path = tmp_path / "walkthrough.magicfit.json"
    receipt_path.write_text(
        json.dumps(
            {
                "provider": "MagicFit",
                "video_output_url": "https://media.powlcdn.com/magicfit/example.mp4",
                "output_file": str(playable_video),
                "target_slug": "different-tour",
                "generated_at": "2026-06-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    mismatched = _run_importer(
        "import_magicfit_walkthrough.py",
        tmp_path,
        "--slug",
        slug,
        "--video-path",
        str(playable_video),
        "--source-receipt",
        str(receipt_path),
    )

    assert mismatched.returncode != 0
    assert "magicfit_receipt_target_mismatch" in mismatched.stderr
    assert not (bundle_dir / "magicfit-walkthrough.mp4").exists()

    receipt_path.write_text(
        json.dumps(
            {
                "provider": "MagicFit",
                "video_output_url": "https://media.powlcdn.com/magicfit/example.mp4",
                "output_file": str(playable_video),
                "target_slug": slug,
                "property_slug": slug,
                "property_title": "Import target",
                "generated_at": "2026-06-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    imported = _run_importer(
        "import_magicfit_walkthrough.py",
        tmp_path,
        "--slug",
        slug,
        "--video-path",
        str(playable_video),
        "--target-relpath",
        "walkthrough/final.mp4",
        "--source-receipt",
        str(receipt_path),
    )

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["video_url"] == f"/tours/files/{slug}/walkthrough/final.mp4"
    assert body["provider"] == "magicfit"
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["video_provider"] == "magicfit"
    assert manifest["video_relpath"] == "walkthrough/final.mp4"
    assert manifest["video_coverage_proof"] == "boundary_verified_frame_continuation"
    assert manifest["magicfit_import"]["source"] == "magicfit_rendered_walkthrough"
    assert manifest["magicfit_import"]["source_receipt_path"] == str(receipt_path)
    assert manifest["magicfit_import"]["size_bytes"] == playable_video.stat().st_size
    assert len(manifest["magicfit_import"]["sha256"]) == 64
    assert (bundle_dir / "walkthrough" / "final.mp4").read_bytes() == playable_video.read_bytes()

    receipt = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert receipt["provider_counts"]["magicfit"] == 1
    assert receipt["ready_provider_modes"] == ["magicfit"]
    assert receipt["tours"][0]["controls"][0]["evidence"] == "local_magicfit_playable_video"


def test_krpano_control_requires_real_walkable_360_asset(tmp_path: Path, monkeypatch) -> None:
    slug = "verified-krpano-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")

    manifest_path = bundle_dir / "tour.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "scene_strategy": "photo_gallery_hosted",
            "creation_mode": "hosted_photo_gallery_tour",
            "walkable_scene": {"projection": "equirectangular", "panorama_relpath": "flat-photo.jpg"},
        }
    )
    (bundle_dir / "flat-photo.jpg").write_bytes(b"not actually inspected as panorama, but forbidden strategy blocks it")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rejected = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert rejected["provider_counts"]["krpano"] == 0
    missing = rejected["tours"][0]["missing_evidence"]
    assert any(row["provider"] == "krpano" and row["reason"] == "walkable_scene_asset_missing_or_not_360" for row in missing)

    manifest.update(
        {
            "scene_strategy": "walkable_panorama",
            "creation_mode": "hosted_walkable_360",
            "walkable_scene": {"projection": "equirectangular", "panorama_relpath": "panorama.jpg"},
        }
    )
    _write_equirectangular_image(bundle_dir / "panorama.jpg")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    accepted = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert accepted["provider_counts"]["krpano"] == 1
    assert accepted["ready_provider_modes"] == ["krpano"]
    assert accepted["tours"][0]["controls"][0]["evidence"] == "licensed_krpano_walkable_scene"


def test_tour_export_discovery_emits_manifest_for_verified_drop_folders(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-3dvista")
    _write_base_tour(tmp_path, "discover-pano2vr")
    drop_dir = tmp_path / "drop"
    vista_export = drop_dir / "discover-3dvista" / "3dvista"
    vista_export.mkdir(parents=True)
    (vista_export / "index.html").write_text(
        "<!doctype html><script src='tdvplayer.js'></script><div>tourviewer</div>",
        encoding="utf-8",
    )
    pano_export = drop_dir / "pano2vr" / "discover-pano2vr"
    pano_export.mkdir(parents=True)
    (pano_export / "index.html").write_text(
        "<!doctype html><script src='tour.js'></script><div>ggskin</div>",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "discovery.json"
    manifest_path = tmp_path / "imports.json"

    discovered = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "discover_property_tour_exports.py"),
            "--drop-dir",
            str(drop_dir),
            "--public-tour-dir",
            str(public_root),
            "--write",
            str(receipt_path),
            "--manifest-write",
            str(manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert discovered.returncode == 0, discovered.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "ready"
    assert receipt["import_count"] == 2
    assert receipt["rejected_count"] == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {row["provider"] for row in manifest["imports"]} == {"3dvista", "pano2vr"}
    assert {row["slug"] for row in manifest["imports"]} == {"discover-3dvista", "discover-pano2vr"}
    assert all(row["entry"] == "index.html" for row in manifest["imports"])


def test_tour_export_discovery_rejects_placeholders_and_missing_tour_manifests(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "placeholder-tour")
    drop_dir = tmp_path / "drop"
    placeholder = drop_dir / "placeholder-tour" / "pano2vr"
    placeholder.mkdir(parents=True)
    (placeholder / "index.html").write_text("<!doctype html><title>Coming soon</title>", encoding="utf-8")
    orphan = drop_dir / "orphan-tour" / "3dvista"
    orphan.mkdir(parents=True)
    (orphan / "index.html").write_text("<!doctype html><script src='tdvplayer.js'></script>", encoding="utf-8")
    receipt_path = tmp_path / "discovery.json"

    discovered = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "discover_property_tour_exports.py"),
            "--drop-dir",
            str(drop_dir),
            "--public-tour-dir",
            str(public_root),
            "--write",
            str(receipt_path),
            "--fail-on-blocked",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert discovered.returncode == 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked_no_verified_exports"
    assert receipt["import_count"] == 0
    assert {row["reason"] for row in receipt["rejected"]} == {
        "pano2vr_export_entry_unverified",
        "tour_manifest_missing",
    }
