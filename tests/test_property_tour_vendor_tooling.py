from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.verify_property_tour_vendor_tooling import (
    _find_installers,
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


def test_vendor_tooling_default_installer_roots_do_not_scan_tmp() -> None:
    roots = _installer_search_roots([])

    assert Path("/tmp") not in roots
