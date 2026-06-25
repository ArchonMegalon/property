from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.materialize_property_tour_export_manifest import (
    build_drop_status_rows,
    build_export_manifest,
    prepare_export_drop_dirs,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_equirectangular_image(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2048, 1024), color=(28, 42, 36)).save(path, format="JPEG")


def _write_base_tour(root: Path, slug: str) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    (bundle / "tour.json").write_text(json.dumps({"slug": slug, "display_title": slug}), encoding="utf-8")


def test_materialize_property_tour_export_manifest_writes_operator_drop_paths(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "needs-exports")

    manifest = build_export_manifest(tour_root=tour_root, incoming_root=incoming_root, limit_per_provider=1)

    assert manifest["status"] == "waiting_for_verified_assets"
    assert manifest["tour_root"] == str(tour_root.resolve())
    assert manifest["incoming_root"] == str(incoming_root.resolve())
    assert set(manifest["providers"]) == {"3dvista", "pano2vr", "krpano", "magicfit"}
    assert manifest["import_count"] == 4
    imports = {(row["provider"], row["slug"]): row for row in manifest["imports"]}
    assert imports[("3dvista", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "3dvista")
    assert imports[("pano2vr", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "pano2vr")
    assert imports[("krpano", "needs-exports")]["asset_dir"] == str(incoming_root.resolve() / "needs-exports" / "krpano")
    assert imports[("magicfit", "needs-exports")]["asset_dir"] == str(incoming_root.resolve() / "needs-exports" / "magicfit")
    assert len(manifest["drop_status"]) == 4
    assert {row["status"] for row in manifest["drop_status"]} == {"waiting_for_assets"}
    assert {row["missing"][0] for row in manifest["drop_status"]} == {"drop_folder"}
    assert manifest["drop_status_summary"] == {"ready_for_import": 0, "waiting_for_assets": 4, "other": 0}
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

    assert manifest["status"] == "waiting_for_verified_assets"
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
        assert "Current drop status: waiting_for_assets" in body
        assert "Missing now:" in body
        assert "import_property_tour_exports.py" in body
        assert "Single-provider dry import example:" in body
        assert "Gold only passes when verify_property_tour_controls reports ready provider modes" in body
        if row["provider"] == "3dvista":
            assert "tdvplayer" in body
            assert "3DVista .zip export" in body
            assert "import_3dvista_export.py" in body
            assert "--export-zip" in body
        if row["provider"] == "pano2vr":
            assert "tour.js" in body
            assert "Pano2VR .zip export" in body
            assert "import_pano2vr_export.py" in body
            assert "--export-zip" in body
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
        assert row["drop_status"]["status"] == "waiting_for_assets"
        assert row["drop_status"]["missing"]


def test_materialize_property_tour_export_manifest_falls_back_when_drop_readme_is_unwritable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    artifact_root = tmp_path / "artifacts"
    _write_base_tour(tour_root, "needs-exports")
    monkeypatch.setenv("EA_ARTIFACT_DIR", str(artifact_root))
    original_write_text = Path.write_text

    def write_text_with_drop_permission_error(self: Path, *args, **kwargs):
        if self.name == "README.propertyquarry-export.txt" and incoming_root in self.parents:
            raise PermissionError("drop readme is not writable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text_with_drop_permission_error)

    manifest = build_export_manifest(
        tour_root=tour_root,
        incoming_root=incoming_root,
        providers={"3dvista"},
        limit_per_provider=1,
    )
    prepared = prepare_export_drop_dirs(manifest)

    assert len(prepared) == 1
    row = prepared[0]
    assert row["provider"] == "3dvista"
    assert "PermissionError" in row["readme_write_error"]
    assert row["artifact_readme_write_error"] == ""
    assert Path(row["readme"]) == Path(row["artifact_readme"])
    assert Path(row["artifact_readme"]).is_file()
    body = Path(row["artifact_readme"]).read_text(encoding="utf-8")
    assert "PropertyQuarry provider export drop folder" in body
    assert "Copy the complete 3DVista export folder" in body
    assert "import_3dvista_export.py" in body


def test_materialize_property_tour_export_manifest_uses_repo_local_readme_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    artifact_root = tmp_path / "unwritable_artifacts"
    _write_base_tour(tour_root, "needs-exports")
    monkeypatch.setenv("EA_ARTIFACT_DIR", str(artifact_root))
    monkeypatch.chdir(tmp_path)
    original_write_text = Path.write_text

    def write_text_with_permission_errors(self: Path, *args, **kwargs):
        if self.name == "README.propertyquarry-export.txt" and (
            incoming_root in self.parents or artifact_root in self.parents
        ):
            raise PermissionError("configured readme target is not writable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text_with_permission_errors)

    manifest = build_export_manifest(
        tour_root=tour_root,
        incoming_root=incoming_root,
        providers={"pano2vr"},
        limit_per_provider=1,
    )
    prepared = prepare_export_drop_dirs(manifest)

    assert len(prepared) == 1
    row = prepared[0]
    assert row["provider"] == "pano2vr"
    assert Path(row["readme"]) == tmp_path / "_completion" / "property_tour_exports" / "drop-readmes" / "needs-exports" / "pano2vr" / "README.propertyquarry-export.txt"
    assert row["artifact_readme"] == row["readme"]
    assert row["artifact_readme_write_error"] == ""
    body = Path(row["readme"]).read_text(encoding="utf-8")
    assert "Copy the complete Pano2VR output folder" in body
    assert "import_pano2vr_export.py" in body


def test_materialize_property_tour_export_manifest_reports_ready_drop_status(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "needs-krpano")
    manifest = build_export_manifest(
        tour_root=tour_root,
        incoming_root=incoming_root,
        providers={"krpano"},
        limit_per_provider=1,
    )
    krpano_row = next(row for row in manifest["imports"] if row["provider"] == "krpano")
    asset_dir = Path(krpano_row["asset_dir"])
    asset_dir.mkdir(parents=True)
    _write_equirectangular_image(asset_dir / "panorama.jpg")

    status_rows = build_drop_status_rows({"imports": [krpano_row]})

    assert status_rows == [
        {
            "slug": "needs-krpano",
            "provider": "krpano",
            "export_dir": str(asset_dir.resolve()),
            "status": "ready_for_import",
            "file_count": 1,
            "present_sample": ["panorama.jpg"],
            "missing": [],
            "accepted_entry": "panorama.jpg",
        }
    ]


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
    assert manifest["status"] == "waiting_for_verified_assets"
    assert manifest["import_count"] == 4
    assert len(manifest["drop_status"]) == 4
    assert manifest["drop_status_summary"] == {"ready_for_import": 0, "waiting_for_assets": 4, "other": 0}
    assert '"drop_status_summary"' in result.stdout
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
    assert all(row["drop_status"]["status"] == "waiting_for_assets" for row in manifest["prepared_drop_dirs"])
