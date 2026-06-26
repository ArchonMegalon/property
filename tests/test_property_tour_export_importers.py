from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

from scripts.discover_property_tour_exports import build_discovery_receipt
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


def _write_sixteen_by_nine_image(path: Path) -> None:
    image = Image.new("RGB", (1280, 720), color=(28, 36, 42))
    image.save(path, format="JPEG")


def _write_square_image(path: Path) -> None:
    image = Image.new("RGB", (1024, 1024), color=(42, 36, 28))
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
        "<!doctype html><script src='runtime/app.js'></script><div>3DVista export shell</div>",
        encoding="utf-8",
    )
    (verified_export / "runtime").mkdir()
    (verified_export / "runtime" / "app.js").write_text("window.TDVPlayer = true;", encoding="utf-8")

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
    assert manifest["three_d_vista_export_root_relpath"] == "3dvista"
    assert (bundle_dir / "3dvista" / "runtime" / "app.js").exists()


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
        "<!doctype html><script src='assets/viewer.js'></script><div>Pano2VR export shell</div>",
        encoding="utf-8",
    )
    (verified_export / "assets").mkdir()
    (verified_export / "assets" / "viewer.js").write_text("window.GGSKIN = true;", encoding="utf-8")

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
    assert (bundle_dir / "pano2vr" / "assets" / "viewer.js").exists()


def test_tour_export_discovery_accepts_vendor_named_export_folders(tmp_path: Path) -> None:
    slug = "vendor-named-tour-export"
    _write_base_tour(tmp_path, slug)
    drop_root = tmp_path / "incoming"
    tour_drop = drop_root / slug
    three_dvista_export = tour_drop / "3DVista VT Pro Export"
    pano2vr_export = tour_drop / "Pano2VR 8 Pro Output"
    three_dvista_export.mkdir(parents=True)
    pano2vr_export.mkdir(parents=True)
    (three_dvista_export / "index.htm").write_text(
        "<!doctype html><script src='tdvplayer.js'></script>",
        encoding="utf-8",
    )
    (three_dvista_export / "tdvplayer.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    (pano2vr_export / "index.html").write_text(
        "<!doctype html><script src='tour.js'></script>",
        encoding="utf-8",
    )
    (pano2vr_export / "tour.js").write_text("window.GGSKIN = true;", encoding="utf-8")

    receipt = build_discovery_receipt(drop_dir=drop_root, public_tour_dir=tmp_path / "public_tours")

    imports = {(row["provider"], row["slug"]): row for row in receipt["imports"]}
    assert receipt["status"] == "ready"
    assert imports[("3dvista", slug)]["export_dir"] == str(three_dvista_export.resolve())
    assert imports[("3dvista", slug)]["entry"] == "index.htm"
    assert imports[("pano2vr", slug)]["export_dir"] == str(pano2vr_export.resolve())
    assert imports[("pano2vr", slug)]["entry"] == "index.html"


def test_krpano_importer_requires_real_equirectangular_panorama(tmp_path: Path, monkeypatch) -> None:
    slug = "verified-krpano-panorama-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")
    flat_image = tmp_path / "flat.jpg"
    Image.new("RGB", (1024, 768), color=(21, 31, 26)).save(flat_image, format="JPEG")

    rejected = _run_importer(
        "import_krpano_walkable_scene.py",
        tmp_path,
        "--slug",
        slug,
        "--panorama",
        str(flat_image),
    )

    assert rejected.returncode != 0
    assert "krpano_panorama_not_equirectangular" in rejected.stderr
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert "walkable_scene" not in manifest

    panorama = tmp_path / "panorama.jpg"
    _write_equirectangular_image(panorama)
    imported = _run_importer(
        "import_krpano_walkable_scene.py",
        tmp_path,
        "--slug",
        slug,
        "--panorama",
        str(panorama),
    )

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["control_url"] == f"/tours/{slug}/control/krpano"
    assert body["asset_count"] == 1
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["control_mode"] == "krpano"
    assert manifest["viewer_provider"] == "krpano"
    assert manifest["scene_strategy"] == "walkable_panorama"
    assert manifest["creation_mode"] == "hosted_walkable_360"
    assert manifest["walkable_scene"]["projection"] == "equirectangular"
    assert manifest["walkable_scene"]["panorama_relpath"] == "krpano/panorama.jpg"
    assert manifest["krpano_import"]["license_domain"] == "propertyquarry.com"
    assert "license-key" not in json.dumps(manifest)
    verifier = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert verifier["provider_counts"]["krpano"] == 1
    assert verifier["ready_provider_modes"] == ["krpano"]


def test_krpano_importer_rejects_16_9_still_named_panorama(tmp_path: Path, monkeypatch) -> None:
    slug = "reject-flat-panorama-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")
    still = tmp_path / "panorama.jpg"
    _write_sixteen_by_nine_image(still)

    rejected = _run_importer(
        "import_krpano_walkable_scene.py",
        tmp_path,
        "--slug",
        slug,
        "--panorama",
        str(still),
    )

    assert rejected.returncode != 0
    assert "krpano_panorama_not_equirectangular" in rejected.stderr
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert "walkable_scene" not in manifest


def test_krpano_importer_accepts_six_real_cube_faces(tmp_path: Path, monkeypatch) -> None:
    slug = "verified-krpano-cube-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")
    faces = []
    for index in range(6):
        face = tmp_path / f"face-{index}.jpg"
        _write_square_image(face)
        faces.extend(["--cube-face", str(face)])

    imported = _run_importer("import_krpano_walkable_scene.py", tmp_path, "--slug", slug, *faces)

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["scene_strategy"] == "walkable_cube"
    assert body["asset_count"] == 6
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["walkable_scene"]["projection"] == "cubemap"
    assert len(manifest["walkable_scene"]["cube_faces"]) == 6
    assert all((bundle_dir / relpath).is_file() for relpath in manifest["walkable_scene"]["cube_faces"].values())
    verifier = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert verifier["provider_counts"]["krpano"] == 1


def test_krpano_importer_can_materialize_existing_cube_face_scene(tmp_path: Path, monkeypatch) -> None:
    slug = "verified-krpano-existing-scene-import"
    bundle_dir = _write_base_tour(tmp_path, slug)
    manifest_path = bundle_dir / "tour.json"
    face_relpaths: dict[str, str] = {}
    for face_key in ("f", "b", "l", "r", "u", "d"):
        relpath = f"panorama/source/tablet_{face_key}.jpg"
        face_path = bundle_dir / relpath
        face_path.parent.mkdir(parents=True, exist_ok=True)
        _write_square_image(face_path)
        face_relpaths[face_key] = relpath
    manifest_path.write_text(
        json.dumps(
            {
                "slug": slug,
                "display_title": "Existing cube scene",
                "scenes": [{"name": "Living room", "cube_faces": face_relpaths}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")

    imported = _run_importer(
        "import_krpano_walkable_scene.py",
        tmp_path,
        "--slug",
        slug,
        "--from-existing-scene",
        "0",
    )

    assert imported.returncode == 0, imported.stderr
    body = json.loads(imported.stdout)
    assert body["scene_strategy"] == "walkable_cube"
    assert body["asset_count"] == 6
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["control_mode"] == "krpano"
    assert manifest["viewer_provider"] == "krpano"
    assert manifest["walkable_scene"]["projection"] == "cubemap"
    assert set(manifest["walkable_scene"]["cube_faces"]) == {"f", "b", "l", "r", "u", "d"}
    assert all((bundle_dir / relpath).is_file() for relpath in manifest["walkable_scene"]["cube_faces"].values())
    verifier = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")
    assert verifier["provider_counts"]["krpano"] == 1
    assert verifier["ready_provider_modes"] == ["krpano"]


def test_batch_tour_export_importer_materializes_verified_3dvista_and_pano2vr_exports(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "batch-3dvista")
    _write_base_tour(tmp_path, "batch-pano2vr")
    vista_export = tmp_path / "batch_vista_export"
    vista_export.mkdir()
    (vista_export / "index.html").write_text(
        "<!doctype html><script src='runtime/app.js'></script><div>3DVista export shell</div>",
        encoding="utf-8",
    )
    (vista_export / "runtime").mkdir()
    (vista_export / "runtime" / "app.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    pano_export = tmp_path / "batch_pano_export"
    pano_export.mkdir()
    (pano_export / "index.html").write_text(
        "<!doctype html><script src='assets/viewer.js'></script><div>Pano2VR export shell</div>",
        encoding="utf-8",
    )
    (pano_export / "assets").mkdir()
    (pano_export / "assets" / "viewer.js").write_text("window.GGSKIN = true;", encoding="utf-8")
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


def test_batch_tour_export_importer_accepts_verified_3dvista_and_pano2vr_zips(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "zip-3dvista")
    _write_base_tour(tmp_path, "zip-pano2vr")
    vista_export = tmp_path / "vista_zip_src" / "vista-export"
    vista_export.mkdir(parents=True)
    (vista_export / "index.html").write_text(
        "<!doctype html><script src='runtime/app.js'></script><div>3DVista export shell</div>",
        encoding="utf-8",
    )
    (vista_export / "runtime").mkdir()
    (vista_export / "runtime" / "app.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    pano_export = tmp_path / "pano_zip_src" / "pano-export"
    pano_export.mkdir(parents=True)
    (pano_export / "index.html").write_text(
        "<!doctype html><script src='assets/viewer.js'></script><div>Pano2VR export shell</div>",
        encoding="utf-8",
    )
    (pano_export / "assets").mkdir()
    (pano_export / "assets" / "viewer.js").write_text("window.GGSKIN = true;", encoding="utf-8")
    vista_zip = tmp_path / "vista-export.zip"
    pano_zip = tmp_path / "pano-export.zip"
    for source_dir, target_zip in ((vista_export, vista_zip), (pano_export, pano_zip)):
        with zipfile.ZipFile(target_zip, "w") as archive:
            for path in sorted(source_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source_dir.parent).as_posix())
    manifest_path = tmp_path / "tour-imports.json"
    receipt_path = tmp_path / "tour-import-receipt.json"
    manifest_path.write_text(
        json.dumps(
            {
                "imports": [
                    {"slug": "zip-3dvista", "provider": "3dvista", "export_zip": str(vista_zip)},
                    {"slug": "zip-pano2vr", "provider": "pano2vr", "export_zip": str(pano_zip)},
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
    verifier = build_property_tour_control_receipt(tour_root=public_root)
    assert verifier["provider_counts"]["3dvista"] == 1
    assert verifier["provider_counts"]["pano2vr"] == 1


def test_3dvista_zip_importer_rejects_placeholder_zip(tmp_path: Path) -> None:
    slug = "zip-placeholder-3dvista"
    _write_base_tour(tmp_path, slug)
    placeholder = tmp_path / "placeholder-vista"
    placeholder.mkdir()
    (placeholder / "index.html").write_text("<!doctype html><title>Coming soon</title>", encoding="utf-8")
    placeholder_zip = tmp_path / "placeholder-vista.zip"
    with zipfile.ZipFile(placeholder_zip, "w") as archive:
        archive.write(placeholder / "index.html", "index.html")

    rejected = _run_importer(
        "import_3dvista_export.py",
        tmp_path,
        "--slug",
        slug,
        "--export-zip",
        str(placeholder_zip),
    )

    assert rejected.returncode != 0
    assert "3dvista_export_entry_unverified" in rejected.stderr


def test_batch_tour_export_importer_materializes_krpano_and_magicfit_assets(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "batch-krpano")
    _write_base_tour(tmp_path, "batch-magicfit")
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")

    krpano_assets = tmp_path / "incoming" / "batch-krpano" / "krpano"
    krpano_assets.mkdir(parents=True)
    _write_equirectangular_image(krpano_assets / "panorama.jpg")

    magicfit_assets = tmp_path / "incoming" / "batch-magicfit" / "magicfit"
    magicfit_assets.mkdir(parents=True)
    video_path = magicfit_assets / "magicfit-walkthrough.mp4"
    _write_playable_mp4(video_path)
    receipt_path = magicfit_assets / "magicfit-receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "provider": "magicfit",
                "target_slug": "batch-magicfit",
                "output_file": str(video_path.resolve()),
            }
        ),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "tour-imports.json"
    receipt_out = tmp_path / "tour-import-receipt.json"
    manifest_path.write_text(
        json.dumps(
            {
                "imports": [
                    {"slug": "batch-krpano", "provider": "krpano", "asset_dir": str(krpano_assets)},
                    {"slug": "batch-magicfit", "provider": "magicfit", "asset_dir": str(magicfit_assets)},
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
            str(receipt_out),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert imported.returncode == 0, imported.stderr
    receipt = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["imported_count"] == 2
    krpano_manifest = json.loads((public_root / "batch-krpano" / "tour.json").read_text(encoding="utf-8"))
    magicfit_manifest = json.loads((public_root / "batch-magicfit" / "tour.json").read_text(encoding="utf-8"))
    assert krpano_manifest["control_mode"] == "krpano"
    assert krpano_manifest["walkable_scene"]["panorama_relpath"] == "krpano/panorama.jpg"
    assert magicfit_manifest["video_provider"] == "magicfit"
    assert magicfit_manifest["video_relpath"] == "magicfit-walkthrough.mp4"
    verifier = build_property_tour_control_receipt(tour_root=public_root)
    assert verifier["provider_counts"]["krpano"] == 1
    assert verifier["provider_counts"]["magicfit"] == 1


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
    assert receipt["magicfit_playback"]["playback_ok"] is True
    assert receipt["magicfit_playback"]["playable_count"] == 1
    assert receipt["magicfit_playback"]["ready_count"] == 1
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


def test_krpano_control_rejects_16_9_stills_as_fake_panorama(tmp_path: Path, monkeypatch) -> None:
    slug = "reject-16-9-krpano"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")
    manifest_path = bundle_dir / "tour.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "scene_strategy": "walkable_panorama",
            "creation_mode": "hosted_walkable_360",
            "walkable_scene": {"projection": "equirectangular", "panorama_relpath": "still-16-9.jpg"},
        }
    )
    _write_sixteen_by_nine_image(bundle_dir / "still-16-9.jpg")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    receipt = build_property_tour_control_receipt(tour_root=tmp_path / "public_tours")

    assert receipt["provider_counts"]["krpano"] == 0
    missing = receipt["tours"][0]["missing_evidence"]
    assert any(row["provider"] == "krpano" and row["reason"] == "walkable_scene_asset_missing_or_not_360" for row in missing)


def test_tour_export_discovery_emits_manifest_for_verified_drop_folders(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-3dvista")
    _write_base_tour(tmp_path, "discover-pano2vr")
    _write_base_tour(tmp_path, "discover-krpano")
    _write_base_tour(tmp_path, "discover-magicfit")
    drop_dir = tmp_path / "drop"
    vista_export = drop_dir / "discover-3dvista" / "3dvista"
    vista_export.mkdir(parents=True)
    (vista_export / "index.html").write_text(
        "<!doctype html><script src='runtime/app.js'></script><div>3DVista export shell</div>",
        encoding="utf-8",
    )
    (vista_export / "runtime").mkdir()
    (vista_export / "runtime" / "app.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    pano_export = drop_dir / "pano2vr" / "discover-pano2vr"
    pano_export.mkdir(parents=True)
    (pano_export / "index.html").write_text(
        "<!doctype html><script src='assets/viewer.js'></script><div>Pano2VR export shell</div>",
        encoding="utf-8",
    )
    (pano_export / "assets").mkdir()
    (pano_export / "assets" / "viewer.js").write_text("window.GGSKIN = true;", encoding="utf-8")
    krpano_assets = drop_dir / "discover-krpano" / "krpano"
    krpano_assets.mkdir(parents=True)
    _write_equirectangular_image(krpano_assets / "panorama.jpg")
    magicfit_assets = drop_dir / "magicfit" / "discover-magicfit"
    magicfit_assets.mkdir(parents=True)
    magicfit_video = magicfit_assets / "magicfit-walkthrough.mp4"
    _write_playable_mp4(magicfit_video)
    (magicfit_assets / "magicfit-receipt.json").write_text(
        json.dumps({"provider": "magicfit", "target_slug": "discover-magicfit", "output_file": str(magicfit_video)}),
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
    assert receipt["import_count"] == 4
    assert receipt["rejected_count"] == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {row["provider"] for row in manifest["imports"]} == {"3dvista", "pano2vr", "krpano", "magicfit"}
    assert {row["slug"] for row in manifest["imports"]} == {
        "discover-3dvista",
        "discover-pano2vr",
        "discover-krpano",
        "discover-magicfit",
    }
    assert {
        row["entry"]
        for row in manifest["imports"]
        if row["provider"] in {"3dvista", "pano2vr"}
    } == {"index.html"}
    assert any(row["provider"] == "krpano" and row["panorama"].endswith("panorama.jpg") for row in manifest["imports"])
    assert any(row["provider"] == "magicfit" and row["video"].endswith("magicfit-walkthrough.mp4") for row in manifest["imports"])


def test_tour_export_discovery_emits_explicit_krpano_cube_faces(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-krpano-cube")
    drop_dir = tmp_path / "drop"
    krpano_assets = drop_dir / "discover-krpano-cube" / "krpano"
    krpano_assets.mkdir(parents=True)
    for index in range(1, 7):
        _write_square_image(krpano_assets / f"cube-face-{index}.jpg")
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["imports"][0]
    assert row["provider"] == "krpano"
    assert "panorama" not in row
    assert {row[f"cube_face_{index}"].rsplit("/", 1)[-1] for index in range(1, 7)} == {
        f"cube-face-{index}.jpg" for index in range(1, 7)
    }


def test_tour_export_discovery_accepts_verified_provider_zips(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-zip-3dvista")
    _write_base_tour(tmp_path, "discover-zip-pano2vr")
    drop_dir = tmp_path / "drop"
    vista_src = tmp_path / "vista-src" / "export"
    vista_src.mkdir(parents=True)
    (vista_src / "index.html").write_text("<script src='runtime/app.js'></script>", encoding="utf-8")
    (vista_src / "runtime").mkdir()
    (vista_src / "runtime" / "app.js").write_text("window.TDVPlayer = true;", encoding="utf-8")
    pano_src = tmp_path / "pano-src" / "export"
    pano_src.mkdir(parents=True)
    (pano_src / "index.html").write_text("<script src='assets/viewer.js'></script>", encoding="utf-8")
    (pano_src / "assets").mkdir()
    (pano_src / "assets" / "viewer.js").write_text("window.GGSKIN = true;", encoding="utf-8")
    vista_drop = drop_dir / "discover-zip-3dvista" / "3dvista"
    pano_drop = drop_dir / "discover-zip-pano2vr" / "pano2vr"
    vista_drop.mkdir(parents=True)
    pano_drop.mkdir(parents=True)
    for source_dir, target_zip in ((vista_src, vista_drop / "export.zip"), (pano_src, pano_drop / "export.zip")):
        with zipfile.ZipFile(target_zip, "w") as archive:
            for path in sorted(source_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source_dir.parent).as_posix())
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = {(row["slug"], row["provider"]): row for row in manifest["imports"]}
    assert rows[("discover-zip-3dvista", "3dvista")]["export_zip"].endswith("export.zip")
    assert rows[("discover-zip-pano2vr", "pano2vr")]["export_zip"].endswith("export.zip")


def test_tour_export_discovery_rejects_16_9_krpano_panorama_candidates(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-flat-krpano")
    drop_dir = tmp_path / "drop"
    krpano_assets = drop_dir / "discover-flat-krpano" / "krpano"
    krpano_assets.mkdir(parents=True)
    _write_sixteen_by_nine_image(krpano_assets / "panorama.jpg")
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
    handoff_path = receipt_path.with_name("discovery.handoff.md")
    assert handoff_path.is_file()
    handoff = handoff_path.read_text(encoding="utf-8")
    assert "PropertyQuarry Tour Export Handoff" in handoff
    assert "Gold remains blocked until real provider assets are copied into the drop folders" in handoff
    assert receipt["status"] == "blocked_no_verified_exports"
    assert receipt["rejected"][0]["reason"] == "krpano_assets_missing"
    assert receipt["repair_manifest"][0]["reason"] == "krpano_assets_missing"


def test_tour_export_discovery_rejects_magicfit_receipt_mismatch_before_import(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "discover-magicfit")
    drop_dir = tmp_path / "drop"
    magicfit_assets = drop_dir / "discover-magicfit" / "magicfit"
    magicfit_assets.mkdir(parents=True)
    magicfit_video = magicfit_assets / "magicfit-walkthrough.mp4"
    _write_playable_mp4(magicfit_video)
    (magicfit_assets / "magicfit-receipt.json").write_text(
        json.dumps({"provider": "magicfit", "target_slug": "different-tour", "output_file": str(magicfit_video)}),
        encoding="utf-8",
    )
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
    assert len(receipt["rejected"]) == 1
    assert receipt["repair_count"] == 1
    rejection = receipt["rejected"][0]
    assert rejection["slug"] == "discover-magicfit"
    assert rejection["provider"] == "magicfit"
    assert rejection["reason"] == "magicfit_receipt_target_mismatch"
    assert "target_slug" in rejection["action"]
    assert "magicfit-walkthrough" in rejection["drop_layout"]
    repair = receipt["repair_manifest"][0]
    assert repair["status"] == "waiting_for_verified_assets"
    assert repair["reason"] == "magicfit_receipt_target_mismatch"
    assert "import_magicfit_walkthrough.py" in repair["import_command_after_assets_arrive"]
    assert "magicfit-receipt.json" in repair["import_command_after_assets_arrive"]


def test_tour_export_discovery_rejects_placeholders_and_missing_tour_manifests(tmp_path: Path) -> None:
    public_root = tmp_path / "public_tours"
    _write_base_tour(tmp_path, "placeholder-tour")
    drop_dir = tmp_path / "drop"
    placeholder = drop_dir / "placeholder-tour" / "pano2vr"
    placeholder.mkdir(parents=True)
    (placeholder / "index.html").write_text("<!doctype html><title>Coming soon</title>", encoding="utf-8")
    krpano_placeholder = drop_dir / "placeholder-tour" / "krpano"
    krpano_placeholder.mkdir(parents=True)
    magicfit_placeholder = drop_dir / "placeholder-tour" / "magicfit"
    magicfit_placeholder.mkdir(parents=True)
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
        "krpano_assets_missing",
        "magicfit_video_missing",
        "pano2vr_export_entry_unverified",
        "tour_manifest_missing",
    }
    assert receipt["repair_count"] == 4
    assert {row["reason"] for row in receipt["repair_manifest"]} == {
        "krpano_assets_missing",
        "magicfit_video_missing",
        "pano2vr_export_entry_unverified",
        "tour_manifest_missing",
    }
    for row in receipt["rejected"]:
        assert row["action"]
        assert row["drop_layout"]
        assert row["drop_path"]
    pano_rejection = next(row for row in receipt["rejected"] if row["provider"] == "pano2vr")
    assert pano_rejection["file_count"] == 1
    assert pano_rejection["present_sample"] == ["index.html"]
    assert pano_rejection["entry_candidates"] == ["index.html"]
    assert pano_rejection["missing"] == ["pano2vr_runtime_marker"]
    assert pano_rejection["missing_markers"] == ["ggpkg", "ggskin", "pano.xml", "tour.js"]
    for row in receipt["repair_manifest"]:
        assert row["status"] == "waiting_for_verified_assets"
        assert row["required_action"]
        assert row["drop_layout"]
        assert row["drop_path"]
    pano_repair = next(row for row in receipt["repair_manifest"] if row["provider"] == "pano2vr")
    assert pano_repair["file_count"] == 1
    assert pano_repair["present_sample"] == ["index.html"]
    assert pano_repair["missing_markers"] == ["ggpkg", "ggskin", "pano.xml", "tour.js"]
    assert any("import_pano2vr_export.py" in row["import_command_after_assets_arrive"] for row in receipt["repair_manifest"])
    assert any("import_krpano_walkable_scene.py" in row["import_command_after_assets_arrive"] for row in receipt["repair_manifest"])
    assert any("import_magicfit_walkthrough.py" in row["import_command_after_assets_arrive"] for row in receipt["repair_manifest"])
    assert any("ggpkg" in row["action"] for row in receipt["rejected"] if row["provider"] == "pano2vr")
    assert any("panorama" in row["action"] for row in receipt["rejected"] if row["provider"] == "krpano")
    handoff_path = receipt_path.with_name("discovery.handoff.md")
    assert handoff_path.is_file()
    handoff = handoff_path.read_text(encoding="utf-8")
    assert "pano2vr · placeholder-tour" in handoff
    assert "Files found: `1`" in handoff
    assert "Present sample: `index.html`" in handoff
    assert "Required markers/evidence: `ggpkg, ggskin, pano.xml, tour.js`" in handoff
    assert "import_pano2vr_export.py" in handoff
