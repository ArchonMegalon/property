from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.verify_property_tour_vendor_tooling import (
    _find_installers,
    _find_installed_apps,
    _installer_search_roots,
    build_vendor_tooling_receipt,
)


def _write_base_tour(root: Path, slug: str) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    (bundle / "tour.json").write_text(json.dumps({"slug": slug, "display_title": slug}), encoding="utf-8")


def _write_equirectangular_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2048, 1024), color=(28, 42, 36)).save(path, format="JPEG")


def test_vendor_tooling_receipt_reports_missing_3dvista_and_pano2vr_exports(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    drop_dir = tmp_path / "incoming"
    wine_prefix = tmp_path / "wine"
    _write_base_tour(tour_root, "ready-krpano")
    _write_equirectangular_image(drop_dir / "ready-krpano" / "krpano" / "panorama.jpg")
    wine_prefix.mkdir()
    (wine_prefix / "system.reg").write_text("wine\n", encoding="utf-8")

    receipt = build_vendor_tooling_receipt(
        drop_dir=drop_dir,
        tour_root=tour_root,
        wine_prefix=wine_prefix,
        installer_roots=[tmp_path / "installers"],
        runtime_container="",
    )
    serialized = json.dumps(receipt).lower()

    assert receipt["status"] == "blocked_missing_verified_exports"
    assert "generated_tour_ready" in receipt
    assert {"krpanotools", "blender", "colmap", "meshlabserver", "ffmpeg", "exiftool", "imagemagick"} <= set(
        receipt["generated_tour_tools"]
    )
    assert receipt["runtime_generated_tour_ready"] is None
    assert receipt["runtime_generated_tour_tools"] == {}
    assert receipt["verified_export_ready_counts"] == {"3dvista": 0, "pano2vr": 0}
    assert receipt["missing_verified_exports"] == ["3dvista", "pano2vr"]
    assert {row["provider"] for row in receipt["official_installer_sources"]} == {"3dvista", "pano2vr"}
    assert any(
        row["area"] == "vendor_installers"
        and {source["provider"] for source in row["official_sources"]} == {"3dvista", "pano2vr"}
        for row in receipt["next_actions"]
    )
    export_actions = [row for row in receipt["next_actions"] if row["area"] == "verified_export"]
    assert {row["provider"] for row in export_actions} == {"3dvista", "pano2vr"}
    assert all("or a zip file inside either folder" in row["accepted_layouts"] for row in export_actions)
    assert "password" not in serialized
    assert "license_key" not in serialized
    assert "reset" not in serialized


def test_vendor_tooling_detects_local_desktop_installers(tmp_path: Path) -> None:
    installer_root = tmp_path / "installers"
    installer_root.mkdir()
    (installer_root / "Pano2VR-8.0.4-x64.exe").write_bytes(b"MZ")
    (installer_root / "3DVista-VTPro.exe").write_bytes(b"MZ")
    (installer_root / "3DVVirtualTour_x64.exe").write_bytes(b"MZ")

    installers = _find_installers([installer_root])

    assert [row["provider"] for row in installers].count("3dvista") == 2
    assert [row["provider"] for row in installers].count("pano2vr") == 1
    assert all(row["size_bytes"] == 2 for row in installers)


def test_vendor_tooling_distinguishes_cached_installer_from_installed_app(tmp_path: Path) -> None:
    installer_root = tmp_path / "installers"
    installer_root.mkdir()
    (installer_root / "3DVVirtualTour_x64.exe").write_bytes(b"MZ")
    wine_prefix = tmp_path / "wine-3dvista"
    installed_root = wine_prefix / "drive_c" / "Program Files" / "3DVista" / "3DVista Virtual Tour"
    installed_root.mkdir(parents=True)

    receipt_without_app = build_vendor_tooling_receipt(
        drop_dir=tmp_path / "incoming",
        tour_root=tmp_path / "public_tours",
        wine_prefix=wine_prefix,
        installer_roots=[installer_root],
        installed_app_roots=[wine_prefix],
        runtime_container="",
    )

    assert receipt_without_app["installer_counts"]["3dvista"] == 1
    assert receipt_without_app["installed_app_counts"]["3dvista"] == 0
    assert any(row["area"] == "vendor_desktop_apps" and "3dvista" in row["missing_providers"] for row in receipt_without_app["next_actions"])

    (installed_root / "3DVista Virtual Tour.exe").write_bytes(b"MZ")
    installed_apps = _find_installed_apps([wine_prefix])
    receipt_with_app = build_vendor_tooling_receipt(
        drop_dir=tmp_path / "incoming",
        tour_root=tmp_path / "public_tours",
        wine_prefix=wine_prefix,
        installer_roots=[installer_root],
        installed_app_roots=[wine_prefix],
        runtime_container="",
    )

    assert [row["provider"] for row in installed_apps] == ["3dvista"]
    assert receipt_with_app["installed_app_counts"]["3dvista"] == 1
    assert not any(row["area"] == "vendor_desktop_apps" and "3dvista" in row.get("missing_providers", []) for row in receipt_with_app["next_actions"])


def test_vendor_tooling_detects_portable_extracted_3dvista_app(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    portable_root = tmp_path / "state" / "vendor_apps" / "3dvista"
    portable_root.mkdir(parents=True)
    (portable_root / "3DVista Virtual Tour.exe").write_bytes(b"MZ")

    installed_apps = _find_installed_apps([portable_root])

    assert installed_apps == [
        {
            "provider": "3dvista",
            "path": str((portable_root / "3DVista Virtual Tour.exe").resolve()),
            "size_bytes": 2,
            "layout": "portable_extract",
        }
    ]


def test_vendor_tooling_default_installer_roots_do_not_scan_tmp() -> None:
    roots = _installer_search_roots([])

    assert Path("/tmp") not in roots


def test_vendor_tooling_runtime_only_skips_desktop_export_tooling_noise(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    drop_dir = tmp_path / "incoming"
    wine_prefix = tmp_path / "wine"
    _write_base_tour(tour_root, "ready-runtime")

    receipt = build_vendor_tooling_receipt(
        drop_dir=drop_dir,
        tour_root=tour_root,
        wine_prefix=wine_prefix,
        installer_roots=[],
        runtime_container="",
        runtime_only=True,
    )
    action_areas = {str(row["area"]) for row in receipt["next_actions"]}

    assert receipt["mode"] == "runtime"
    assert receipt["host_ready"] is None
    assert receipt["installer_counts"] == {"3dvista": 0, "pano2vr": 0}
    assert receipt["installed_app_counts"] == {"3dvista": 0, "pano2vr": 0}
    assert "host_tooling" not in action_areas
    assert "vendor_installers" not in action_areas
    assert "vendor_desktop_apps" not in action_areas
    assert {row["provider"] for row in receipt["next_actions"] if row["area"] == "verified_export"} == {"3dvista", "pano2vr"}
