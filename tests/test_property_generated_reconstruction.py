from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from app.api.routes.public_tour_payloads import public_tour_allowed_asset_paths
from scripts.verify_property_tour_controls import build_property_tour_control_receipt


ROOT = Path(__file__).resolve().parents[1]


def _write_base_tour(tmp_path: Path, slug: str) -> Path:
    bundle_dir = tmp_path / "public_tours" / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps({"slug": slug, "display_title": "Generated target"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return bundle_dir


def _write_floorplan(path: Path) -> None:
    image = Image.new("RGB", (1200, 800), color=(248, 244, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1120, 720), outline=(42, 36, 28), width=12)
    draw.line((620, 80, 620, 720), fill=(42, 36, 28), width=8)
    draw.line((80, 420, 620, 420), fill=(42, 36, 28), width=8)
    image.save(path, format="JPEG")


def _write_photo(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (900, 700), color=color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 820, 620), outline=(255, 255, 255), width=8)
    image.save(path, format="JPEG")


def _run_generator(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(tmp_path / "public_tours")
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_property_reconstruction.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_generated_reconstruction_materializes_model_viewer_receipt_and_walkthrough(tmp_path: Path) -> None:
    slug = "generated-reconstruction-target"
    bundle_dir = _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "kitchen.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo_a, (126, 108, 82))
    _write_photo(photo_b, (86, 104, 112))

    generated = _run_generator(
        tmp_path,
        "--slug",
        slug,
        "--floorplan",
        str(floorplan),
        "--photo",
        str(photo_a),
        "--photo",
        str(photo_b),
    )

    assert generated.returncode == 0, generated.stderr
    body = json.loads(generated.stdout)
    assert body["status"] == "generated"
    assert body["provider"] == "propertyquarry_generated_reconstruction"
    assert body["viewer_url"] == f"/tours/files/{slug}/generated-reconstruction/viewer.html"
    output_dir = bundle_dir / "generated-reconstruction"
    for filename in (
        "source-floorplan.jpg",
        "photo-01.jpg",
        "photo-02.jpg",
        "model.obj",
        "model.mtl",
        "viewer.html",
        "reconstruction.json",
    ):
        assert (output_dir / filename).is_file(), filename
    viewer_html = (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert "<title>3D tour | PropertyQuarry</title>" in viewer_html
    assert "<h1>3D tour</h1>" in viewer_html
    assert "Layout preview" in viewer_html
    assert "Built from the floorplan and listing photos" in viewer_html
    assert "three.module.js" in viewer_html
    assert "OrbitControls" in viewer_html
    assert "wallRectangles" in viewer_html
    assert "const points = [" not in viewer_html
    assert "Generated reconstruction" not in viewer_html
    assert "not a verified" not in viewer_html
    assert "Matterport" not in viewer_html
    assert "3DVista" not in viewer_html
    assert "Pano2VR" not in viewer_html
    assert "krpano" not in viewer_html
    assert "MagicFit" not in viewer_html
    assert "Download OBJ" not in viewer_html
    assert "Download GLB" not in viewer_html
    assert "receipt stored" not in viewer_html
    assert "propertyquarry_generated_layout" in (output_dir / "model.obj").read_text(encoding="utf-8")
    receipt = json.loads((output_dir / "reconstruction.json").read_text(encoding="utf-8"))
    assert receipt["verified_provider_capture"] is False
    assert receipt["satisfies_verified_tour_gate"] is False
    assert receipt["disclosure"] == "Planning preview built from the floor plan and listing photos. Use it as a layout aid, not as a captured tour."
    for provider_name in ("Matterport", "3DVista", "Pano2VR", "krpano", "MagicFit", "verified provider"):
        assert provider_name not in receipt["disclosure"]
    assert receipt["viewer"]["version"] == "propertyquarry_3d_tour_viewer_v3"
    assert receipt["room_dimensions_m"]["width"] == 10.0
    assert receipt["room_dimensions_m"]["depth"] < 10.0
    assert receipt["geometry"]["wall_rect_count"] > 0
    assert len(receipt["geometry"]["wall_rectangles"]) == receipt["geometry"]["wall_rect_count"]
    assert receipt["geometry"]["content_size_px"]["width"] < receipt["floorplan"]["width"]
    assert receipt["geometry"]["content_size_px"]["height"] < receipt["floorplan"]["height"]
    assert len(receipt["photos"]) == 2
    assert receipt["model"]["glb_export"]["status"] in {"generated", "failed", "skipped"}
    if receipt["model"]["glb_export"]["status"] == "generated":
        assert receipt["model"]["glb_relpath"] == "model.glb"
        assert (output_dir / "model.glb").is_file()
    assert receipt["walkthrough"]["status"] in {"generated", "failed", "skipped"}
    if receipt["walkthrough"]["status"] == "generated":
        assert (output_dir / "generated-walkthrough.mp4").is_file()
        assert (output_dir / "generated-walkthrough.quality.json").is_file()
        assert receipt["walkthrough"]["duration_seconds"] >= 30.0
        assert receipt["walkthrough"]["coverage_proof"]["status"] == "pass"

    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    generated_reconstruction = manifest["generated_reconstruction"]
    assert generated_reconstruction["viewer_relpath"] == "generated-reconstruction/viewer.html"
    assert generated_reconstruction["model_relpath"] == "generated-reconstruction/model.obj"
    assert generated_reconstruction["material_relpath"] == "generated-reconstruction/model.mtl"
    assert generated_reconstruction["floorplan_relpath"] in {
        "generated-reconstruction/source-floorplan.jpg",
        "generated-reconstruction/source-floorplan-inferred.jpg",
    }
    assert generated_reconstruction["photo_relpaths"] == [
        "generated-reconstruction/photo-01.jpg",
        "generated-reconstruction/photo-02.jpg",
    ]
    assert generated_reconstruction["glb_export_status"] in {"generated", "failed", "skipped"}
    if generated_reconstruction["glb_export_status"] == "generated":
        assert generated_reconstruction["glb_model_relpath"] == "generated-reconstruction/model.glb"
    assert generated_reconstruction["viewer_version"] == "propertyquarry_3d_tour_viewer_v3"
    if receipt["walkthrough"]["status"] == "generated":
        assert generated_reconstruction["walkthrough_sidecar_relpath"] == "generated-reconstruction/generated-walkthrough.quality.json"
        assert generated_reconstruction["walkthrough_coverage_proof"]["status"] == "pass"
    assert generated_reconstruction["verified_provider_capture"] is False
    assert generated_reconstruction["disclosure"] == receipt["disclosure"]
    for provider_name in ("Matterport", "3DVista", "Pano2VR", "krpano", "MagicFit", "verified provider"):
        assert provider_name not in generated_reconstruction["disclosure"]
    assert "control_mode" not in manifest
    assert "viewer_provider" not in manifest
    assert "video_provider" not in manifest
    assert "video_relpath" not in manifest
    assert "walkable_scene" not in manifest


def test_generated_reconstruction_does_not_satisfy_verified_provider_gate(tmp_path: Path, monkeypatch) -> None:
    slug = "generated-reconstruction-not-provider"
    _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo = tmp_path / "photo.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo, (108, 92, 74))
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "license-key")

    generated = _run_generator(
        tmp_path,
        "--slug",
        slug,
        "--floorplan",
        str(floorplan),
        "--photo",
        str(photo),
        "--skip-video",
    )

    assert generated.returncode == 0, generated.stderr
    receipt = build_property_tour_control_receipt(
        tour_root=tmp_path / "public_tours",
        require_all_provider_modes=True,
    )
    assert receipt["status"] == "blocked_missing_provider_modes"
    assert receipt["provider_counts"]["3dvista"] == 0
    assert receipt["provider_counts"]["pano2vr"] == 0
    assert receipt["provider_counts"]["krpano"] == 0
    assert receipt["provider_counts"]["magicfit"] == 0
    assert set(receipt["missing_provider_modes"]) == {"matterport", "3dvista", "krpano", "magicfit"}
    assert receipt["optional_provider_modes"] == ["pano2vr"]


def test_generated_reconstruction_can_disclose_inferred_floorplan_from_photos(tmp_path: Path) -> None:
    slug = "generated-reconstruction-inferred-floorplan"
    bundle_dir = _write_base_tour(tmp_path, slug)
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "bedroom.jpg"
    _write_photo(photo_a, (118, 102, 88))
    _write_photo(photo_b, (92, 108, 118))

    generated = _run_generator(
        tmp_path,
        "--slug",
        slug,
        "--infer-floorplan-from-photos",
        "--photo",
        str(photo_a),
        "--photo",
        str(photo_b),
        "--skip-video",
    )

    assert generated.returncode == 0, generated.stderr
    output_dir = bundle_dir / "generated-reconstruction"
    receipt = json.loads((output_dir / "reconstruction.json").read_text(encoding="utf-8"))
    assert receipt["floorplan"]["relpath"] == "source-floorplan-inferred.jpg"
    assert receipt["floorplan"]["inferred"] is True
    assert receipt["floorplan"]["source_path"] == "generated_from_photo_set"
    assert (output_dir / "source-floorplan-inferred.jpg").is_file()
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["generated_reconstruction"]["satisfies_verified_tour_gate"] is False


def test_generated_reconstruction_public_allowlist_exposes_viewer_model_and_video_not_receipt() -> None:
    payload = {
        "slug": "generated-public-assets",
        "generated_reconstruction": {
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "model_relpath": "generated-reconstruction/model.obj",
            "material_relpath": "generated-reconstruction/model.mtl",
            "floorplan_relpath": "generated-reconstruction/source-floorplan.jpg",
            "photo_relpaths": [
                "generated-reconstruction/photo-01.jpg",
                "generated-reconstruction/photo-02.jpg",
            ],
            "glb_model_relpath": "generated-reconstruction/model.glb",
            "manifest_relpath": "generated-reconstruction/reconstruction.json",
            "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
        },
    }

    allowed = public_tour_allowed_asset_paths(payload)

    assert "generated-reconstruction/viewer.html" in allowed
    assert "generated-reconstruction/model.obj" in allowed
    assert "generated-reconstruction/model.mtl" in allowed
    assert "generated-reconstruction/source-floorplan.jpg" in allowed
    assert "generated-reconstruction/photo-01.jpg" in allowed
    assert "generated-reconstruction/photo-02.jpg" in allowed
    assert "generated-reconstruction/model.glb" in allowed
    assert "generated-reconstruction/generated-walkthrough.mp4" in allowed
    assert "generated-reconstruction/reconstruction.json" not in allowed
    assert "generated-reconstruction/private-debug.html" not in public_tour_allowed_asset_paths(
        {"public_assets": [{"relpath": "generated-reconstruction/private-debug.html"}]}
    )
