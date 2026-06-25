from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.materialize_property_tour_export_manifest import build_export_manifest, prepare_export_drop_dirs


ROOT = Path(__file__).resolve().parents[1]


def _write_base_tour(root: Path, slug: str) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    (bundle / "tour.json").write_text(json.dumps({"slug": slug, "display_title": slug}), encoding="utf-8")


def test_materialize_property_tour_export_manifest_writes_operator_drop_paths(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "needs-exports")

    manifest = build_export_manifest(tour_root=tour_root, incoming_root=incoming_root, limit_per_provider=1)

    assert manifest["status"] == "ready_for_exports"
    assert manifest["tour_root"] == str(tour_root.resolve())
    assert manifest["incoming_root"] == str(incoming_root.resolve())
    assert set(manifest["providers"]) == {"3dvista", "pano2vr", "krpano", "magicfit"}
    assert manifest["import_count"] == 4
    imports = {(row["provider"], row["slug"]): row for row in manifest["imports"]}
    assert imports[("3dvista", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "3dvista")
    assert imports[("pano2vr", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "pano2vr")
    assert imports[("krpano", "needs-exports")]["asset_dir"] == str(incoming_root.resolve() / "needs-exports" / "krpano")
    assert imports[("magicfit", "needs-exports")]["asset_dir"] == str(incoming_root.resolve() / "needs-exports" / "magicfit")
    assert "import_property_tour_exports.py" in manifest["next_command"]


def test_materialize_property_tour_export_manifest_prioritizes_ready_tour_gaps(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "blocked-needs-exports")
    ready_bundle = tour_root / "matterport-ready"
    ready_bundle.mkdir(parents=True)
    (ready_bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": "matterport-ready",
                "display_title": "Matterport Ready",
                "matterport_url": "https://my.matterport.com/show/?m=READY123",
            }
        ),
        encoding="utf-8",
    )

    manifest = build_export_manifest(tour_root=tour_root, incoming_root=incoming_root, limit_per_provider=1)

    assert manifest["status"] == "ready_for_exports"
    assert manifest["import_count"] == 4
    assert {row["slug"] for row in manifest["imports"]} == {"matterport-ready"}
    assert {row["current_control_providers"] for row in manifest["imports"]} == {"matterport"}
    assert {row["title"] for row in manifest["imports"]} == {"Matterport Ready"}


def test_materialize_property_tour_export_manifest_prepares_drop_dir_readmes(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "needs-exports")

    manifest = build_export_manifest(tour_root=tour_root, incoming_root=incoming_root, limit_per_provider=1)
    prepared = prepare_export_drop_dirs(manifest)

    assert len(prepared) == 4
    for row in prepared:
        readme = Path(row["readme"])
        assert readme.is_file()
        body = readme.read_text(encoding="utf-8")
        assert "PropertyQuarry provider export drop folder" in body
        assert f"Slug: {row['slug']}" in body
        assert f"Provider: {row['provider']}" in body
        assert "Do not copy placeholder HTML" in body
        assert "import_property_tour_exports.py" in body
        assert "Single-provider dry import example:" in body
        assert "Gold only passes when verify_property_tour_controls reports ready provider modes" in body
        if row["provider"] == "3dvista":
            assert "tdvplayer" in body
            assert "Copy the complete 3DVista export folder" in body
            assert "import_3dvista_export.py" in body
        if row["provider"] == "pano2vr":
            assert "tour.js" in body
            assert "Copy the complete Pano2VR output folder" in body
            assert "import_pano2vr_export.py" in body
        if row["provider"] == "krpano":
            assert "equirectangular" in body
            assert "cube-face-1" in body
            assert "KRPANO_LICENSE_DOMAIN=propertyquarry.com" in body
            assert "import_krpano_walkable_scene.py" in body
        if row["provider"] == "magicfit":
            assert "MagicFit render receipt" in body
            assert "magicfit-walkthrough.mp4" in body
            assert "magicfit-receipt.json" in body
            assert "import_magicfit_walkthrough.py" in body


def test_materialize_property_tour_export_manifest_cli_writes_receipt(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    output = tmp_path / "manifest.json"
    _write_base_tour(tour_root, "cli-needs-exports")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_property_tour_export_manifest.py"),
            "--tour-root",
            str(tour_root),
            "--incoming-root",
            str(incoming_root),
            "--write",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["status"] == "ready_for_exports"
    assert manifest["import_count"] == 4
    assert "cli-needs-exports" in result.stdout


def test_materialize_property_tour_export_manifest_cli_can_prepare_drop_dirs(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    output = tmp_path / "manifest.json"
    _write_base_tour(tour_root, "cli-prepares-exports")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_property_tour_export_manifest.py"),
            "--tour-root",
            str(tour_root),
            "--incoming-root",
            str(incoming_root),
            "--prepare-dirs",
            "--write",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert len(manifest["prepared_drop_dirs"]) == 4
    assert all(Path(row["readme"]).is_file() for row in manifest["prepared_drop_dirs"])
