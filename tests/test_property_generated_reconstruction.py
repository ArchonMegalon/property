from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.api.routes.public_tour_payloads import public_tour_allowed_asset_paths
from app.product import property_tour_hosting
from app.product import service as product_service
from scripts import generate_property_reconstruction as reconstruction_script
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
    env.setdefault("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP", "5")
    timeout_seconds = int(str(env.get("PROPERTYQUARRY_GENERATED_RECONSTRUCTION_TEST_TIMEOUT_SECONDS") or "600").strip() or "600")
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_property_reconstruction.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run_generator_with_env(
    tmp_path: Path,
    *args: str,
    env_overrides: dict[str, str | None],
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(tmp_path / "public_tours")
    env.setdefault("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP", "5")
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    timeout_seconds = int(str(env.get("PROPERTYQUARRY_GENERATED_RECONSTRUCTION_TEST_TIMEOUT_SECONDS") or "600").strip() or "600")
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_property_reconstruction.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _mean_rgb(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    averaged = image.crop(box).convert("RGB").resize((1, 1), Image.Resampling.BOX)
    pixel = averaged.getpixel((0, 0))
    return float(pixel[0]), float(pixel[1]), float(pixel[2])


@contextmanager
def _serve_directory(root: Path):
    class _QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for_playwright_condition(page, predicate: str, *, timeout_ms: int = 15_000) -> None:
    deadline = time.monotonic() + (max(int(timeout_ms), 1) / 1000)
    while time.monotonic() < deadline:
        if bool(page.evaluate(predicate)):
            return
        page.wait_for_timeout(250)
    raise AssertionError("playwright_condition_timeout")


def _viewer_accessibility_receipt(page) -> dict[str, object]:
    return page.evaluate(
        """() => {
            const visibleButtons = Array.from(document.querySelectorAll('button')).filter((button) => {
              const style = getComputedStyle(button);
              const rect = button.getBoundingClientRect();
              return !button.hidden && style.display !== 'none' && style.visibility !== 'hidden'
                && rect.width > 0 && rect.height > 0;
            });
            const targets = visibleButtons.map((button) => {
              const rect = button.getBoundingClientRect();
              return {
                className: String(button.className || ''),
                label: String(button.getAttribute('aria-label') || button.textContent || '').trim(),
                width: Number(rect.width.toFixed(1)),
                height: Number(rect.height.toFixed(1)),
              };
            });
            const mapTargets = Array.from(document.querySelectorAll('.floorplan-stop')).map((button) => {
              const rect = button.getBoundingClientRect();
              return { index: String(button.dataset.routeIndex || ''), rect };
            });
            const overlaps = [];
            for (let index = 0; index < mapTargets.length; index += 1) {
              for (let otherIndex = index + 1; otherIndex < mapTargets.length; otherIndex += 1) {
                const first = mapTargets[index];
                const second = mapTargets[otherIndex];
                const overlapWidth = Math.min(first.rect.right, second.rect.right)
                  - Math.max(first.rect.left, second.rect.left);
                const overlapHeight = Math.min(first.rect.bottom, second.rect.bottom)
                  - Math.max(first.rect.top, second.rect.top);
                if (overlapWidth > 0.5 && overlapHeight > 0.5) {
                  overlaps.push(`${first.index}:${second.index}`);
                }
              }
            }
            return {
              targetCount: targets.length,
              undersizedTargets: targets.filter((target) => target.width < 44 || target.height < 44),
              floorplanTargetOverlaps: overlaps,
              horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
            };
        }"""
    )


def _expected_default_walkthrough_contract() -> tuple[str, str, str]:
    if reconstruction_script._playwright_chromium_capture_available():
        return (
            "viewer_route_storyboard",
            "threejs_layout_flythrough",
            "viewer_capture_floorplan_inset_active_stop",
        )
    return (
        "route_focused_stop_cards",
        "ken_burns_route_cards",
        "floorplan_inset_active_stop",
    )


def test_generated_reconstruction_walkthrough_stop_card_embeds_floorplan_route_context(tmp_path: Path) -> None:
    floorplan = tmp_path / "floorplan.jpg"
    hero = tmp_path / "hero.jpg"
    support = tmp_path / "support.jpg"
    _write_floorplan(floorplan)
    _write_photo(hero, (126, 108, 82))
    _write_photo(support, (86, 104, 112))
    with Image.open(floorplan) as image:
        floorplan_thumb = image.convert("RGB").resize(
            (
                reconstruction_script.WALKTHROUGH_MAP_BOX[2] - reconstruction_script.WALKTHROUGH_MAP_BOX[0],
                reconstruction_script.WALKTHROUGH_MAP_BOX[3] - reconstruction_script.WALKTHROUGH_MAP_BOX[1],
            )
        )
    route_markers = [
        {"label": "entry/hall", "x_pct": 18.0, "y_pct": 46.0},
        {"label": "living room", "x_pct": 52.0, "y_pct": 51.0},
        {"label": "bedroom", "x_pct": 76.0, "y_pct": 66.0},
    ]
    with_map = reconstruction_script._render_walkthrough_stop_card(
        stop_index=1,
        label="living room",
        expected_segments=["entry/hall", "living room", "bedroom"],
        source_path=hero,
        supporting_path=support,
        floorplan_thumb=floorplan_thumb,
        route_markers=route_markers,
        style_label="warm scandinavian",
    )
    without_map = reconstruction_script._render_walkthrough_stop_card(
        stop_index=1,
        label="living room",
        expected_segments=["entry/hall", "living room", "bedroom"],
        source_path=hero,
        supporting_path=support,
        floorplan_thumb=None,
        route_markers=route_markers,
        style_label="warm scandinavian",
    )

    assert with_map.size == reconstruction_script.WALKTHROUGH_CARD_SIZE
    assert without_map.size == reconstruction_script.WALKTHROUGH_CARD_SIZE
    map_box = reconstruction_script.WALKTHROUGH_MAP_BOX
    assert with_map.crop(map_box).tobytes() != without_map.crop(map_box).tobytes()
    header_mean = _mean_rgb(with_map, (72, 40, 330, 124))
    hero_mean = _mean_rgb(with_map, (180, 230, 520, 470))
    route_panel_mean = _mean_rgb(with_map, (984, 170, 1328, 690))
    footer_mean = _mean_rgb(with_map, (84, 736, 760, 792))
    assert sum(abs(header_mean[index] - hero_mean[index]) for index in range(3)) > 18.0
    assert sum(abs(route_panel_mean[index] - hero_mean[index]) for index in range(3)) > 24.0
    assert sum(abs(footer_mean[index] - hero_mean[index]) for index in range(3)) > 14.0


def test_generated_reconstruction_render_tools_runtime_defaults_to_stop_card_walkthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    floorplan = tmp_path / "floorplan.jpg"
    hero = tmp_path / "hero.jpg"
    viewer = tmp_path / "viewer.html"
    target = tmp_path / "generated-walkthrough.mp4"
    _write_floorplan(floorplan)
    _write_photo(hero, (126, 108, 82))
    viewer.write_text("<html></html>\n", encoding="utf-8")
    monkeypatch.setenv("EA_ROLE", "render-tools")
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_DISABLE_VIEWER_WALKTHROUGH", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_ENABLE_VIEWER_WALKTHROUGH", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_VIEWER_WALKTHROUGH_REQUIRED", raising=False)
    monkeypatch.setattr(reconstruction_script, "sync_playwright", object())

    observed = {"viewer": 0, "stop_card": 0}

    def _fake_viewer(*args, **kwargs):
        observed["viewer"] += 1
        return {"status": "generated", "composition": "viewer_route_storyboard", "motion_style": "threejs_layout_flythrough"}

    def _fake_stop_card(*args, **kwargs):
        observed["stop_card"] += 1
        return {
            "status": "generated",
            "relpath": target.name,
            "sidecar_relpath": "generated-walkthrough.quality.json",
            "sha256": "x",
            "sidecar_sha256": "y",
            "size_bytes": 1,
            "duration_seconds": 5.0,
            "composition": "route_focused_stop_cards",
            "motion_style": "ken_burns_route_cards",
            "coverage_proof": {"status": "pass"},
        }

    monkeypatch.setattr(reconstruction_script, "_write_viewer_walkthrough", _fake_viewer)
    monkeypatch.setattr(reconstruction_script, "_write_stop_card_walkthrough", _fake_stop_card)

    receipt = reconstruction_script._write_walkthrough(
        target,
        [floorplan, hero],
        route_labels=["entry/hall", "living room"],
        room_count=2,
        walkable_scene={"route": [{"label": "entry/hall"}, {"label": "living room"}]},
        viewer_path=viewer,
    )

    assert observed == {"viewer": 0, "stop_card": 1}
    assert receipt["status"] == "generated"
    assert receipt["composition"] == "route_focused_stop_cards"


def test_generated_reconstruction_diorama_preview_reads_as_staged_layout_composition(tmp_path: Path) -> None:
    floorplan = tmp_path / "floorplan.jpg"
    hero = tmp_path / "hero.jpg"
    support = tmp_path / "support.jpg"
    detail = tmp_path / "detail.jpg"
    preview = tmp_path / "diorama-preview.png"
    _write_floorplan(floorplan)
    _write_photo(hero, (126, 108, 82))
    _write_photo(support, (86, 104, 112))
    _write_photo(detail, (132, 118, 84))
    walkable_scene = reconstruction_script._reconstruction_walkable_scene(
        route_labels=["entry/hall", "living room", "bedroom"],
        width_m=10.0,
        depth_m=7.4,
        height_m=2.8,
    )

    receipt = reconstruction_script._write_generated_reconstruction_diorama_preview(
        preview,
        floorplan_path=floorplan,
        photo_paths=[hero, support, detail],
        walkable_scene=walkable_scene,
        style_label="warm scandinavian",
    )

    assert receipt["status"] == "generated", receipt
    rendered = Image.open(preview).convert("RGB")
    assert rendered.size == (1600, 1100)
    background_mean = _mean_rgb(rendered, (24, 24, 144, 144))
    title_mean = _mean_rgb(rendered, (110, 96, 320, 210))
    stage_mean = _mean_rgb(rendered, (520, 630, 1040, 860))
    hero_mean = _mean_rgb(rendered, (700, 160, 940, 320))
    right_panel_mean = _mean_rgb(rendered, (1180, 240, 1360, 380))
    route_rail_mean = _mean_rgb(rendered, (1190, 590, 1450, 900))

    assert sum(abs(title_mean[index] - background_mean[index]) for index in range(3)) > 18.0
    assert sum(abs(stage_mean[index] - background_mean[index]) for index in range(3)) > 30.0
    assert sum(abs(hero_mean[index] - stage_mean[index]) for index in range(3)) > 35.0
    assert sum(abs(right_panel_mean[index] - hero_mean[index]) for index in range(3)) > 20.0
    assert sum(abs(route_rail_mean[index] - background_mean[index]) for index in range(3)) > 24.0

    pixels = rendered.load()
    accent_pixels = 0
    dark_structure_pixels = 0
    for y in range(0, rendered.height, 3):
        for x in range(0, rendered.width, 3):
            r, g, b = pixels[x, y]
            if r >= 150 and 90 <= g <= 190 and b <= 150:
                accent_pixels += 1
            if r <= 96 and g <= 96 and b <= 96:
                dark_structure_pixels += 1
    assert accent_pixels > 130
    assert dark_structure_pixels > 340


def test_generated_reconstruction_walkable_scene_snaps_route_stops_to_open_floorplan_cells() -> None:
    wall_mask = [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ]

    walkable_scene = reconstruction_script._reconstruction_walkable_scene(
        route_labels=["entry/hall", "living room", "bedroom"],
        width_m=10.0,
        depth_m=7.0,
        height_m=2.8,
        geometry={"wall_mask": wall_mask},
    )

    route = list(walkable_scene["route"])
    assert len(route) == 3
    seen_cells: set[tuple[int, int]] = set()
    rows = len(wall_mask)
    cols = len(wall_mask[0])
    inner_width = max(1.2, 10.0 * 0.34)
    inner_depth = max(1.2, 7.0 * 0.34)
    for stop in route:
        focus = dict(stop["focus"])
        col = min(cols - 1, max(0, int((((float(focus["x"]) / inner_width) + 0.5) * cols))))
        row = min(rows - 1, max(0, int((((float(focus["z"]) / inner_depth) + 0.5) * rows))))
        assert wall_mask[row][col] == 0
        seen_cells.add((row, col))
    assert len(seen_cells) == len(route)


def test_generated_reconstruction_declutters_flagship_floorplan_route_targets() -> None:
    positions = [(50.0, 50.0)] * 13

    displayed = reconstruction_script._declutter_floorplan_stop_positions(positions)

    assert len(displayed) == len(positions)
    assert all(8.0 <= left <= 92.0 and 10.0 <= top <= 90.0 for left, top in displayed)
    for index, (left, top) in enumerate(displayed):
        for other_left, other_top in displayed[index + 1 :]:
            assert abs(left - other_left) >= 15.5 or abs(top - other_top) >= 20.0


def test_generated_reconstruction_materializes_model_viewer_receipt_and_walkthrough(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug = "generated-reconstruction-target"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path / "public_tours"))
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
    assert body["viewer_relpath"] == "generated-reconstruction/viewer.html"
    assert body["diorama_preview_relpath"] == "diorama-preview.png"
    assert body["telegram_preview_relpath"] == "telegram-preview.png"
    assert body["public_tour_url"] == ""
    assert body["satisfies_verified_tour_gate"] is False
    output_dir = bundle_dir / "generated-reconstruction"
    for filename in ("diorama-preview.png", "telegram-preview.png"):
        assert (bundle_dir / filename).is_file(), filename
    for filename in (
        "source-floorplan.jpg",
        "photo-01.jpg",
        "photo-02.jpg",
        "model.obj",
        "model.mtl",
        "viewer.html",
        "reconstruction.json",
        "vendor/three.module.js",
        "vendor/examples/jsm/controls/OrbitControls.js",
    ):
        assert (output_dir / filename).is_file(), filename
    viewer_html = (output_dir / "viewer.html").read_text(encoding="utf-8")
    assert "<title>Layout preview | PropertyQuarry</title>" in viewer_html
    assert '<link rel="icon" href="data:,">' in viewer_html
    assert "<h1>Layout preview</h1>" in viewer_html
    assert "Layout preview" in viewer_html
    assert "Built from the floorplan and listing photos" in viewer_html
    assert "three.module.js" in viewer_html
    assert "OrbitControls" in viewer_html
    assert "cdn.jsdelivr.net" not in viewer_html
    assert '"three": "./vendor/three.module.js"' in viewer_html
    assert 'import * as THREE from "three";' in viewer_html
    assert 'import { OrbitControls } from "./vendor/examples/jsm/controls/OrbitControls.js";' in viewer_html
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
    assert "Room route" in viewer_html
    assert "routeButtons" in viewer_html
    assert "floorplan-map" in viewer_html
    assert "floorplan-stop" in viewer_html
    assert "route-hotspot" in viewer_html
    assert "floorplan-route-overlay" in viewer_html
    assert "min-height:34px" not in viewer_html
    assert "min-height:38px" not in viewer_html
    assert "letter-spacing:-" not in viewer_html
    assert "view-dollhouse" in viewer_html
    assert "setDollhouseView" in viewer_html
    assert "easeInOutCubic" in viewer_html
    assert "startCameraTransition" in viewer_html
    assert "view-guided-route" in viewer_html
    assert "capture-route-card" in viewer_html
    assert "captureMode" in viewer_html
    assert "guidedQueryEnabled" in viewer_html
    assert "startGuidedRoute" in viewer_html
    assert "renderCaptureFrame" in viewer_html
    assert "isTransitioning" in viewer_html
    assert "transitionProgressPct" in viewer_html
    assert "wallHeightScale" in viewer_html
    assert "applyCutawayWallVisibility" in viewer_html
    assert "hiddenCutawayWallCount" in viewer_html
    assert "addGeneratedStagingForStop" in viewer_html
    assert "generated-sofa-seat" in viewer_html
    assert "stagingObjectCount" in viewer_html
    assert "Tap a numbered stop on the plan to move through the route." in viewer_html
    assert "photoPanelSpecs" in viewer_html
    assert "photoPanelCount" in viewer_html
    assert "loadedPhotoTextureCount" in viewer_html
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
    assert receipt["walkable_scene"]["kind"] == "generated_reconstruction_layout"
    assert len(receipt["walkable_scene"]["route"]) >= 1
    assert len(receipt["walkable_scene"]["rooms"]) == len(receipt["walkable_scene"]["route"])
    assert receipt["geometry"]["content_size_px"]["width"] < receipt["floorplan"]["width"]
    assert receipt["geometry"]["content_size_px"]["height"] < receipt["floorplan"]["height"]
    assert len(receipt["photos"]) == 2
    assert len(receipt["photo_reference_panels"]) == len(receipt["photos"])
    assert receipt["viewer"]["photo_reference_panel_count"] == len(receipt["photo_reference_panels"])
    assert receipt["photo_reference_panels"][0]["photo_relpath"] == "photo-01.jpg"
    assert receipt["photo_reference_panels"][1]["photo_relpath"] == "photo-02.jpg"
    assert {panel["wall_side"] for panel in receipt["photo_reference_panels"]} <= {"north", "south", "east", "west"}
    assert all(isinstance(panel["route_index"], int) and panel["route_index"] >= 0 for panel in receipt["photo_reference_panels"])
    assert receipt["bundle_preview_assets"]["diorama"]["status"] == "generated"
    assert receipt["bundle_preview_assets"]["diorama"]["bundle_relpath"] == "diorama-preview.png"
    assert receipt["bundle_preview_assets"]["telegram"]["status"] == "generated"
    assert receipt["bundle_preview_assets"]["telegram"]["bundle_relpath"] == "telegram-preview.png"
    assert len(receipt["walkthrough_route_labels"]) >= len(receipt["route_labels"])
    assert receipt["model"]["glb_export"]["status"] in {"generated", "failed", "skipped"}
    if receipt["model"]["glb_export"]["status"] == "generated":
        assert receipt["model"]["glb_relpath"] == "model.glb"
        assert (output_dir / "model.glb").is_file()
    assert receipt["walkthrough"]["status"] in {"generated", "failed", "skipped"}
    if receipt["walkthrough"]["status"] == "generated":
        expected_composition, expected_motion_style, expected_route_context_mode = _expected_default_walkthrough_contract()
        assert (output_dir / "generated-walkthrough.mp4").is_file()
        assert (output_dir / "generated-walkthrough.quality.json").is_file()
        walkthrough_sidecar = json.loads((output_dir / "generated-walkthrough.quality.json").read_text(encoding="utf-8"))
        assert receipt["walkthrough"]["duration_seconds"] >= float(walkthrough_sidecar["seconds_per_stop"])
        assert receipt["walkthrough"]["composition"] == expected_composition
        assert receipt["walkthrough"]["motion_style"] == expected_motion_style
        assert receipt["walkthrough"]["coverage_proof"]["status"] == "pass"
        assert walkthrough_sidecar["route_map_embedded"] is True
        assert walkthrough_sidecar["route_context_mode"] == expected_route_context_mode

    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    generated_reconstruction = manifest["generated_reconstruction"]
    assert generated_reconstruction["viewer_relpath"] == "generated-reconstruction/viewer.html"
    assert generated_reconstruction["model_relpath"] == "generated-reconstruction/model.obj"
    assert generated_reconstruction["material_relpath"] == "generated-reconstruction/model.mtl"
    assert generated_reconstruction["floorplan_relpath"] in {
        "generated-reconstruction/source-floorplan.jpg",
        "generated-reconstruction/source-floorplan-inferred.jpg",
    }
    assert generated_reconstruction["diorama_preview_bundle_relpath"] == "diorama-preview.png"
    assert generated_reconstruction["telegram_preview_bundle_relpath"] == "telegram-preview.png"
    assert generated_reconstruction["photo_relpaths"] == [
        "generated-reconstruction/photo-01.jpg",
        "generated-reconstruction/photo-02.jpg",
    ]
    assert generated_reconstruction["glb_export_status"] in {"generated", "failed", "skipped"}
    if generated_reconstruction["glb_export_status"] == "generated":
        assert generated_reconstruction["glb_model_relpath"] == "generated-reconstruction/model.glb"
    assert generated_reconstruction["viewer_version"] == "propertyquarry_3d_tour_viewer_v3"
    assert len(generated_reconstruction["walkthrough_route_labels"]) >= len(generated_reconstruction["route_labels"])
    assert generated_reconstruction["photo_reference_panel_count"] == len(receipt["photo_reference_panels"])
    assert generated_reconstruction["walkable_scene_kind"] == "generated_reconstruction_layout"
    assert generated_reconstruction["walkable_scene"]["kind"] == "generated_reconstruction_layout"
    assert len(generated_reconstruction["walkable_scene"]["route"]) >= 1
    if receipt["walkthrough"]["status"] == "generated":
        expected_composition, expected_motion_style, _expected_route_context_mode = _expected_default_walkthrough_contract()
        assert generated_reconstruction["walkthrough_sidecar_relpath"] == "generated-reconstruction/generated-walkthrough.quality.json"
        assert generated_reconstruction["walkthrough_composition"] == expected_composition
        assert generated_reconstruction["walkthrough_motion_style"] == expected_motion_style
        assert generated_reconstruction["walkthrough_coverage_proof"]["status"] == "pass"
    assert generated_reconstruction["verified_provider_capture"] is False
    assert generated_reconstruction["disclosure"] == receipt["disclosure"]
    for provider_name in ("Matterport", "3DVista", "Pano2VR", "krpano", "MagicFit", "verified provider"):
        assert provider_name not in generated_reconstruction["disclosure"]
    assert "control_mode" not in manifest
    assert "walkable_scene" not in manifest
    assert "viewer_provider" not in manifest
    assert manifest["diorama_preview_relpath"] == "diorama-preview.png"
    assert manifest["preview_relpath"] == "diorama-preview.png"
    assert manifest["telegram_preview_relpath"] == "telegram-preview.png"
    assert manifest["scenes"][0]["role"] == "diorama"
    assert manifest["scenes"][0]["asset_relpath"] == "diorama-preview.png"
    assert {row["path"] for row in manifest["public_assets"] if isinstance(row, dict)} >= {
        "diorama-preview.png",
        "telegram-preview.png",
        "generated-reconstruction/vendor/three.module.js",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
    }
    assert public_tour_allowed_asset_paths(manifest) >= {
        "generated-reconstruction/viewer.html",
        "generated-reconstruction/vendor/three.module.js",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
    }
    if receipt["walkthrough"]["status"] == "generated":
        assert manifest["video_provider"] == "propertyquarry_generated_reconstruction"
        assert manifest["video_provider_key"] == "propertyquarry_generated_reconstruction"
        assert manifest["video_render_provider"] == "propertyquarry_generated_reconstruction"
        assert manifest["video_source"] == "propertyquarry_generated_reconstruction"
        assert manifest["video_relpath"] == "generated-reconstruction/generated-walkthrough.mp4"
        assert manifest["video_sidecar_relpath"] == "generated-reconstruction/generated-walkthrough.quality.json"
        assert manifest["video_coverage_proof"] == "boundary_verified_frame_continuation"
        assert property_tour_hosting._hosted_property_tour_walkthrough_asset_url(
            f"https://propertyquarry.com/tours/{slug}"
        ) == f"https://propertyquarry.com/tours/files/{slug}/generated-reconstruction/generated-walkthrough.mp4"
    assert property_tour_hosting._hosted_property_tour_generated_reconstruction_bundle_ready(
        f"https://propertyquarry.com/tours/{slug}"
    ) is True


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
    assert set(receipt["missing_provider_modes"]) == {"matterport", "3dvista", "magicfit"}
    assert receipt["optional_provider_modes"] == ["pano2vr", "krpano"]


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


def test_generated_reconstruction_public_allowlist_exposes_viewer_but_not_raw_model_debug_assets() -> None:
    payload = {
        "slug": "generated-public-assets",
        "diorama_preview_relpath": "diorama-preview.png",
        "preview_relpath": "diorama-preview.png",
        "telegram_preview_relpath": "telegram-preview.png",
        "public_assets": [
            {
                "path": "generated-reconstruction/vendor/three.module.js",
                "privacy_class": "generated_reconstruction_public",
                "role": "generated_reconstruction_viewer_asset",
                "mime_type": "text/javascript",
            },
            {
                "path": "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
                "privacy_class": "generated_reconstruction_public",
                "role": "generated_reconstruction_viewer_asset",
                "mime_type": "text/javascript",
            },
        ],
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

    assert "diorama-preview.png" in allowed
    assert "telegram-preview.png" in allowed
    assert "generated-reconstruction/viewer.html" in allowed
    assert "generated-reconstruction/vendor/three.module.js" in allowed
    assert "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js" in allowed
    assert "generated-reconstruction/model.obj" not in allowed
    assert "generated-reconstruction/model.mtl" not in allowed
    assert "generated-reconstruction/source-floorplan.jpg" in allowed
    assert "generated-reconstruction/photo-01.jpg" in allowed
    assert "generated-reconstruction/photo-02.jpg" in allowed
    assert "generated-reconstruction/model.glb" not in allowed
    assert "generated-reconstruction/generated-walkthrough.mp4" in allowed
    assert "generated-reconstruction/reconstruction.json" not in allowed
    assert "generated-reconstruction/private-debug.html" not in public_tour_allowed_asset_paths(
        {"public_assets": [{"relpath": "generated-reconstruction/private-debug.html"}]}
    )


def test_generated_reconstruction_manifest_whitelists_viewer_vendor_assets(tmp_path: Path) -> None:
    slug = "generated-viewer-vendor-assets"
    bundle_dir = _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo = tmp_path / "living.jpg"
    tool_path = tmp_path / "tool-bin"
    tool_path.mkdir()
    _write_floorplan(floorplan)
    _write_photo(photo, (122, 106, 84))

    generated = _run_generator_with_env(
        tmp_path,
        "--slug",
        slug,
        "--floorplan",
        str(floorplan),
        "--photo",
        str(photo),
        "--skip-video",
        env_overrides={
            "PATH": str(tool_path),
        },
    )

    assert generated.returncode == 0, generated.stderr
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    public_asset_paths = {row["path"] for row in manifest["public_assets"] if isinstance(row, dict)}

    assert public_asset_paths >= {
        "diorama-preview.png",
        "telegram-preview.png",
        "generated-reconstruction/vendor/three.module.js",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
    }
    assert public_tour_allowed_asset_paths(manifest) >= {
        "generated-reconstruction/viewer.html",
        "generated-reconstruction/vendor/three.module.js",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
    }


def test_generated_reconstruction_runtime_sync_timeout_returns_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = tmp_path / "public_tours" / "runtime-timeout"
    bundle_dir.mkdir(parents=True)

    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=kwargs.get("timeout") or 0)

    monkeypatch.setattr(reconstruction_script.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(reconstruction_script.subprocess, "run", _fake_run)

    receipt = reconstruction_script._sync_bundle_to_runtime_container(bundle_dir, slug="runtime-timeout")

    assert receipt["status"] == "runtime_mkdir_timeout"
    assert receipt["slug"] == "runtime-timeout"
    assert receipt["container"] == "propertyquarry-api"


def test_generated_reconstruction_required_runtime_publish_failure_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "generated-reconstruction-runtime-publish-required"
    bundle_dir = _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo = tmp_path / "living.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo, (122, 106, 84))
    monkeypatch.setenv("PATH", "")

    generated = _run_generator_with_env(
        tmp_path,
        "--slug",
        slug,
        "--floorplan",
        str(floorplan),
        "--photo",
        str(photo),
        env_overrides={
            "PROPERTYQUARRY_RECONSTRUCTION_REQUIRE_RUNTIME_PUBLISH": "1",
            "PROPERTYQUARRY_RECONSTRUCTION_ALLOW_LOCAL_ONLY": None,
        },
    )

    assert generated.returncode == 1, generated.stdout or generated.stderr
    body = json.loads(generated.stdout)
    assert body["status"] == "failed"
    assert body["reason"] == "runtime_publish_failed"
    assert body["local_bundle_generated"] is True
    assert body["runtime_publish_required"] is True
    assert body["runtime_publish"]["status"] == "docker_unavailable"
    receipt = json.loads(
        (bundle_dir / "generated-reconstruction" / "reconstruction.json").read_text(encoding="utf-8")
    )
    assert receipt["runtime_publish_required"] is True
    assert receipt["runtime_publish_ok"] is False
    assert receipt["runtime_publish"]["status"] == "docker_unavailable"


def test_generated_reconstruction_render_tools_shared_public_volume_does_not_require_runtime_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ROLE", "render-tools")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", "/data/public_property_tours")
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_ALLOW_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_REQUIRE_RUNTIME_PUBLISH", raising=False)

    assert reconstruction_script._runtime_publish_required() is False


def test_generated_reconstruction_walkthrough_uses_explicit_room_labels_for_duration_and_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "generated-reconstruction-room-route"
    bundle_dir = _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "bedroom.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo_a, (122, 106, 84))
    _write_photo(photo_b, (88, 104, 118))

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
        "--room-label",
        "entry/hall",
        "--room-label",
        "living room",
        "--room-label",
        "bedroom",
    )

    assert generated.returncode == 0, generated.stderr
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert manifest["generated_reconstruction"]["route_labels"] == ["entry/hall", "living room", "bedroom"]
    assert manifest["generated_reconstruction"]["room_stop_count"] == 3
    assert [stop["label"] for stop in manifest["generated_reconstruction"]["walkable_scene"]["route"]] == [
        "entry/hall",
        "living room",
        "bedroom",
    ]
    assert manifest["room_visit_plan"] == ["entry/hall", "living room", "bedroom"]
    assert manifest["covered_route_labels"] == ["entry/hall", "living room", "bedroom"]
    output_dir = bundle_dir / "generated-reconstruction"
    receipt = json.loads((output_dir / "reconstruction.json").read_text(encoding="utf-8"))
    assert receipt["route_labels"] == ["entry/hall", "living room", "bedroom"]
    assert [stop["label"] for stop in receipt["walkable_scene"]["route"]] == ["entry/hall", "living room", "bedroom"]
    if receipt["walkthrough"]["status"] != "generated":
        return

    expected_composition, expected_motion_style, expected_route_context_mode = _expected_default_walkthrough_contract()
    assert receipt["walkthrough"]["composition"] == expected_composition
    assert receipt["walkthrough"]["motion_style"] == expected_motion_style
    sidecar = json.loads((output_dir / "generated-walkthrough.quality.json").read_text(encoding="utf-8"))
    transition_duration = float(sidecar["transition_duration_seconds"])
    segment_duration = float(sidecar["seconds_per_stop"])
    if sidecar["composition"] == "viewer_route_storyboard":
        expected_duration = sidecar["seconds_per_stop"] * sidecar["room_stop_count"]
    else:
        expected_duration = (sidecar["seconds_per_stop"] * sidecar["room_stop_count"]) - (
            transition_duration * max(0, sidecar["room_stop_count"] - 1)
        )
    assert receipt["walkthrough"]["duration_seconds"] == pytest.approx(expected_duration, abs=0.25)
    assert sidecar["composition"] == expected_composition
    assert sidecar["motion_style"] == expected_motion_style
    assert sidecar["seconds_per_stop"] == 5.0
    assert sidecar["room_stop_count"] == 3
    assert sidecar["walkthrough_card_count"] == 3
    assert sidecar["route_map_embedded"] is True
    assert sidecar["route_context_mode"] == expected_route_context_mode
    assert sidecar["route_labels"] == ["entry/hall", "living room", "bedroom"]
    assert sidecar["walkthrough_coverage_proof"]["segments_expected"] == ["entry/hall", "living room", "bedroom"]
    coverage_segments = sidecar["walkthrough_coverage_proof"]["coverage_segments"]
    if sidecar["composition"] == "viewer_route_storyboard":
        coverage_step_seconds = sidecar["seconds_per_stop"]
        expected_segments = [
            ("entry/hall", 1, 0.0, segment_duration),
            ("living room", 2, coverage_step_seconds, coverage_step_seconds + segment_duration),
            ("bedroom", 3, coverage_step_seconds * 2, coverage_step_seconds * 2 + segment_duration),
        ]
    else:
        coverage_step_seconds = sidecar["seconds_per_stop"] - transition_duration
        expected_segments = [
            ("entry/hall", 1, 0.0, segment_duration),
            ("living room", 2, coverage_step_seconds, coverage_step_seconds + segment_duration),
            ("bedroom", 3, coverage_step_seconds * 2, min(expected_duration, (coverage_step_seconds * 2) + segment_duration)),
        ]
    for observed, (segment, index, start, end) in zip(coverage_segments, expected_segments):
        assert observed["segment"] == segment
        assert observed["index"] == index
        assert observed["start"] == pytest.approx(round(start, 3), abs=0.01)
        assert observed["end"] == pytest.approx(round(end, 3), abs=0.01)


def test_generated_reconstruction_walkthrough_expands_human_route_to_cover_full_photo_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug = "generated-reconstruction-photo-coverage"
    bundle_dir = _write_base_tour(tmp_path, slug)
    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    manifest["facts"] = {
        "has_floorplan": True,
        "has_balcony": True,
        "has_terrace": True,
    }
    manifest["photo_count"] = 5
    manifest["media"] = {"source_photos": {"count": 5}}
    (bundle_dir / "tour.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    floorplan = tmp_path / "floorplan.jpg"
    _write_floorplan(floorplan)
    photo_paths: list[Path] = []
    colors = [
        (122, 106, 84),
        (88, 104, 118),
        (118, 96, 74),
        (96, 118, 102),
        (132, 116, 88),
    ]
    for index, color in enumerate(colors, start=1):
        photo = tmp_path / f"photo-{index:02d}.jpg"
        _write_photo(photo, color)
        photo_paths.append(photo)

    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP", "5")
    generated = _run_generator(
        tmp_path,
        "--slug",
        slug,
        "--floorplan",
        str(floorplan),
        *[arg for photo in photo_paths for arg in ("--photo", str(photo))],
    )

    assert generated.returncode == 0, generated.stderr
    refreshed_manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    generated_reconstruction = dict(refreshed_manifest["generated_reconstruction"])
    assert generated_reconstruction["route_labels"] == [
        "entry/hall",
        "living area",
        "sleeping area",
        "balcony/terrace",
    ]
    assert generated_reconstruction["walkthrough_route_labels"] == [
        "entry/hall",
        "living area",
        "sleeping area",
        "balcony/terrace",
        "living area detail 2",
    ]
    assert generated_reconstruction["room_stop_count"] == 4
    assert generated_reconstruction["walkthrough_stop_count"] == 5
    assert refreshed_manifest["room_visit_plan"] == [
        "entry/hall",
        "living area",
        "sleeping area",
        "balcony/terrace",
    ]
    output_dir = bundle_dir / "generated-reconstruction"
    receipt = json.loads((output_dir / "reconstruction.json").read_text(encoding="utf-8"))
    assert receipt["route_labels"] == generated_reconstruction["route_labels"]
    assert receipt["walkthrough_route_labels"] == generated_reconstruction["walkthrough_route_labels"]
    assert [panel["route_index"] for panel in receipt["photo_reference_panels"]] == [0, 0, 1, 2, 3]
    if receipt["walkthrough"]["status"] != "generated":
        return

    sidecar = json.loads((output_dir / "generated-walkthrough.quality.json").read_text(encoding="utf-8"))
    assert sidecar["seconds_per_stop"] == 5.0
    assert sidecar["walkthrough_card_count"] == 5
    assert sidecar["route_labels"] == generated_reconstruction["walkthrough_route_labels"]
    assert sidecar["walkthrough_coverage_proof"]["segments_expected"] == generated_reconstruction["walkthrough_route_labels"]


def test_generated_reconstruction_viewer_guided_route_runs_in_real_browser(tmp_path: Path) -> None:
    if not reconstruction_script._playwright_chromium_capture_available():
        pytest.skip("playwright_missing")

    slug = "generated-reconstruction-guided-viewer"
    bundle_dir = _write_base_tour(tmp_path, slug)
    floorplan = tmp_path / "floorplan.jpg"
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "bedroom.jpg"
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
        "--room-label",
        "entry/hall",
        "--room-label",
        "living room",
        "--room-label",
        "bedroom",
        "--skip-video",
    )

    assert generated.returncode == 0, generated.stderr
    viewer_path = bundle_dir / "generated-reconstruction" / "viewer.html"
    assert viewer_path.is_file()
    public_root = tmp_path / "public_tours"
    viewer_relpath = viewer_path.relative_to(public_root).as_posix()

    with _serve_directory(public_root) as base_url:
        with reconstruction_script.sync_playwright() as playwright:
            launch_kwargs = reconstruction_script._playwright_chromium_launch_kwargs(playwright)
            browser = playwright.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
            try:
                page.goto(f"{base_url}/{viewer_relpath}?guided=1", wait_until="domcontentloaded")
                _wait_for_playwright_condition(
                    page,
                    """() => {
                        const metrics = window.__pqReconstructionDebug?.getRenderMetrics?.() || {};
                        return Boolean(metrics.ready)
                          && Number(metrics.frameCount || 0) >= 2
                          && Number(metrics.renderTriangles || 0) > 0;
                    }""",
                    timeout_ms=20_000,
                )
                initial_metrics = page.evaluate("() => window.__pqReconstructionDebug?.getRenderMetrics?.() || null")
                assert isinstance(initial_metrics, dict)
                assert initial_metrics["ready"] is True
                assert initial_metrics["frameCount"] >= 2
                assert initial_metrics["renderTriangles"] > 0
                desktop_accessibility = _viewer_accessibility_receipt(page)
                assert desktop_accessibility["targetCount"] >= 10
                assert desktop_accessibility["undersizedTargets"] == []
                assert desktop_accessibility["floorplanTargetOverlaps"] == []
                assert desktop_accessibility["horizontalOverflowPx"] == 0
                _wait_for_playwright_condition(
                    page,
                    """() => {
                        const metrics = window.__pqReconstructionDebug?.getRenderMetrics?.() || {};
                        return Boolean(metrics.guidedQueryEnabled)
                          && Boolean(metrics.guidedRouteActive)
                          && String(document.getElementById('view-guided-route')?.textContent || '').includes('Stop');
                    }""",
                    timeout_ms=20_000,
                )
                _wait_for_playwright_condition(
                    page,
                    """() => {
                        const debug = window.__pqReconstructionDebug;
                        const metrics = debug?.getRenderMetrics?.() || {};
                        return Boolean(metrics.guidedQueryEnabled)
                          && Number(metrics.activeRouteIndex || -1) >= 1;
                    }""",
                    timeout_ms=20_000,
                )
                metrics = page.evaluate("() => window.__pqReconstructionDebug.getRenderMetrics()")
                assert isinstance(metrics, dict)
                assert metrics["guidedQueryEnabled"] is True
                assert metrics["activeRouteIndex"] >= 1
                assert metrics["guidedRouteCurrentIndex"] >= 1

                stopped_metrics = page.evaluate(
                    """() => {
                        const debug = window.__pqReconstructionDebug;
                        const button = document.getElementById('view-guided-route');
                        const before = debug?.getRenderMetrics?.() || null;
                        const wasActive = Boolean(before?.guidedRouteActive);
                        if (wasActive && button) {
                            button.click();
                        }
                        return {
                            wasActive,
                            metrics: debug?.getRenderMetrics?.() || null,
                            label: String(button?.textContent || ''),
                        };
                    }"""
                )
                assert isinstance(stopped_metrics, dict)
                assert isinstance(stopped_metrics["metrics"], dict)
                assert stopped_metrics["metrics"]["guidedRouteActive"] is False
                assert "Guide me" in str(stopped_metrics["label"])

                page.evaluate(
                    """() => {
                        const button = document.getElementById('view-guided-route');
                        if (button) {
                            button.click();
                        }
                    }"""
                )
                restarted_metrics = page.evaluate(
                    """() => ({
                        metrics: window.__pqReconstructionDebug?.getRenderMetrics?.() || null,
                        label: String(document.getElementById('view-guided-route')?.textContent || ''),
                    })"""
                )
                assert isinstance(restarted_metrics, dict)
                assert isinstance(restarted_metrics["metrics"], dict)
                assert restarted_metrics["metrics"]["guidedRouteActive"] is True
                assert "Stop" in str(restarted_metrics["label"])

                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(400)
                mobile_accessibility = _viewer_accessibility_receipt(page)
                assert mobile_accessibility["targetCount"] >= 10
                assert mobile_accessibility["undersizedTargets"] == []
                assert mobile_accessibility["floorplanTargetOverlaps"] == []
                assert mobile_accessibility["horizontalOverflowPx"] == 0
            finally:
                browser.close()


def test_service_generated_reconstruction_bundle_persists_multi_floor_route_labels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public_root = tmp_path / "public_tours"
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP", "1")
    floorplan = tmp_path / "floorplan.jpg"
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "bedroom.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo_a, (126, 108, 82))
    _write_photo(photo_b, (86, 104, 112))

    asset_map = {
        "https://img.example.test/floorplan.jpg": floorplan,
        "https://img.example.test/living.jpg": photo_a,
        "https://img.example.test/bedroom.jpg": photo_b,
    }

    monkeypatch.setattr(
        product_service,
        "_download_property_reconstruction_image",
        lambda url, target_dir, *, stem: asset_map.get(str(url or "").strip()),
    )

    payload = product_service._write_generated_reconstruction_property_tour_bundle(
        principal_id="property-tour-route-proof",
        title="Maisonette with balcony",
        listing_id="listing-route-proof-1",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/maisonette-route-proof-1",
        variant_key="layout_first",
        media_urls=["https://img.example.test/living.jpg", "https://img.example.test/bedroom.jpg"],
        floorplan_urls=["https://img.example.test/floorplan.jpg"],
        property_facts_json={
            "rooms": 3,
            "description": "Maisonette mit Treppe, Balkon und separatem WC.",
        },
        source_host="www.willhaben.at",
        source_ref="willhaben:maisonette-route-proof-1",
        external_id="maisonette-route-proof-1",
        recipient_email="owner@example.test",
        diorama_style_hint="Ikea",
    )

    generated_reconstruction = dict(payload.get("generated_reconstruction") or {})
    route_labels = list(generated_reconstruction.get("route_labels") or [])
    assert "staircase" in route_labels
    assert "balcony/terrace" in route_labels
    assert generated_reconstruction["room_stop_count"] == len(route_labels)
    assert [stop["label"] for stop in generated_reconstruction["walkable_scene"]["route"]] == route_labels
    assert generated_reconstruction["walkthrough_video_relpath"] == "generated-reconstruction/generated-walkthrough.mp4"
    assert generated_reconstruction["walkthrough_sidecar_relpath"] == "generated-reconstruction/generated-walkthrough.quality.json"
    assert payload["video_relpath"] == "generated-reconstruction/generated-walkthrough.mp4"
    assert payload["video_provider"] == "propertyquarry_generated_reconstruction"
    assert payload["video_provider_key"] == "propertyquarry_generated_reconstruction"
    assert payload["video_coverage_proof"] == "boundary_verified_frame_continuation"
    walkthrough_url = property_tour_hosting._hosted_property_tour_walkthrough_asset_url(
        f"https://propertyquarry.com/tours/{payload['slug']}"
    )
    assert walkthrough_url.endswith("/generated-reconstruction/generated-walkthrough.mp4")
    video_delivery = product_service._hosted_property_tour_video_delivery(
        f"https://propertyquarry.com/tours/{payload['slug']}"
    )
    assert video_delivery["video_url"].endswith("/generated-reconstruction/generated-walkthrough.mp4")
    assert video_delivery["provider_key"] == "propertyquarry_generated_reconstruction"
    assert float(video_delivery["duration_seconds"]) > 0.0
    assert "staircase" in list(video_delivery.get("covered_route_labels") or [])
    assert "balcony/terrace" in list(video_delivery.get("covered_route_labels") or [])

    context = product_service._property_walkthrough_scene_video_context(
        f"https://propertyquarry.com/tours/{payload['slug']}"
    )
    assert "staircase" in context["route_labels"]
    assert "balcony/terrace" in context["route_labels"]


def test_service_generated_reconstruction_uses_render_bridge_when_local_walkthrough_tooling_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public_root = tmp_path / "public_tours"
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    monkeypatch.delenv("PROPERTYQUARRY_GENERATED_RECONSTRUCTION_SKIP_VIDEO", raising=False)
    floorplan = tmp_path / "floorplan.jpg"
    photo_a = tmp_path / "living.jpg"
    photo_b = tmp_path / "bedroom.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo_a, (126, 108, 82))
    _write_photo(photo_b, (86, 104, 112))

    asset_map = {
        "https://img.example.test/floorplan.jpg": floorplan,
        "https://img.example.test/living.jpg": photo_a,
        "https://img.example.test/bedroom.jpg": photo_b,
    }

    monkeypatch.setattr(
        product_service,
        "_download_property_reconstruction_image",
        lambda url, target_dir, *, stem: asset_map.get(str(url or "").strip()),
    )
    monkeypatch.setattr(product_service.shutil, "which", lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}")

    observed: dict[str, object] = {}

    def _fake_bridge(*, slug, floorplan_path, photo_paths, style_label, room_count, route_labels, skip_video):
        observed["slug"] = slug
        observed["floorplan_path"] = str(floorplan_path or "")
        observed["photo_paths"] = [str(path) for path in photo_paths]
        observed["style_label"] = style_label
        observed["room_count"] = room_count
        observed["route_labels"] = list(route_labels)
        observed["skip_video"] = skip_video
        bundle_dir = public_root / slug
        generated_dir = bundle_dir / "generated-reconstruction"
        generated_dir.mkdir(parents=True, exist_ok=True)
        for source, name in (
            (floorplan, "source-floorplan.jpg"),
            (photo_a, "photo-01.jpg"),
            (photo_b, "photo-02.jpg"),
        ):
            source_bytes = Path(source).read_bytes()
            (generated_dir / name).write_bytes(source_bytes)
        (generated_dir / "viewer.html").write_text("<html></html>\n", encoding="utf-8")
        (generated_dir / "model.obj").write_text("o model\n", encoding="utf-8")
        (generated_dir / "model.mtl").write_text("newmtl m\n", encoding="utf-8")
        (generated_dir / "generated-walkthrough.mp4").write_bytes(b"video")
        sidecar = {
            "route_labels": [
                "entry/hall",
                "living area",
                "sleeping area",
                "balcony/terrace",
                "living area detail 2",
            ],
            "walkthrough_coverage_proof": {
                "status": "pass",
                "segments_expected": [
                    "entry/hall",
                    "living area",
                    "sleeping area",
                    "balcony/terrace",
                    "living area detail 2",
                ],
            },
        }
        (generated_dir / "generated-walkthrough.quality.json").write_text(json.dumps(sidecar), encoding="utf-8")
        receipt = {
            "provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "disclosure": "Planning preview built from the floor plan and listing photos. Use it as a layout aid, not as a captured tour.",
            "viewer": {"version": "propertyquarry_3d_tour_viewer_v3", "photo_reference_panel_count": 2},
            "walkable_scene": {
                "kind": "generated_reconstruction_layout",
                "rooms": [{"label": "entry/hall"}, {"label": "living area"}, {"label": "sleeping area"}, {"label": "balcony/terrace"}],
                "route": [
                    {"label": "entry/hall"},
                    {"label": "living area"},
                    {"label": "sleeping area"},
                    {"label": "balcony/terrace"},
                ],
            },
            "walkthrough": {
                "status": "generated",
                "composition": "route_focused_stop_cards",
                "motion_style": "ken_burns_route_cards",
                "coverage_proof": {"status": "pass", "segments_expected": sidecar["route_labels"]},
            },
            "route_labels": ["entry/hall", "living area", "sleeping area", "balcony/terrace"],
            "walkthrough_route_labels": list(sidecar["route_labels"]),
            "photo_reference_panels": [
                {"photo_relpath": "photo-01.jpg", "route_index": 1, "wall_side": "south"},
                {"photo_relpath": "photo-02.jpg", "route_index": 2, "wall_side": "north"},
            ],
            "photos": [
                {"relpath": "photo-01.jpg"},
                {"relpath": "photo-02.jpg"},
            ],
            "model": {"glb_export": {"status": "skipped"}},
        }
        (generated_dir / "reconstruction.json").write_text(json.dumps(receipt), encoding="utf-8")
        manifest_path = bundle_dir / "tour.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["generated_reconstruction"] = {
            "provider": "propertyquarry_generated_reconstruction",
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "model_relpath": "generated-reconstruction/model.obj",
            "material_relpath": "generated-reconstruction/model.mtl",
            "floorplan_relpath": "generated-reconstruction/source-floorplan.jpg",
            "photo_relpaths": [
                "generated-reconstruction/photo-01.jpg",
                "generated-reconstruction/photo-02.jpg",
            ],
            "viewer_version": "propertyquarry_3d_tour_viewer_v3",
            "walkable_scene_kind": "generated_reconstruction_layout",
            "walkable_scene": receipt["walkable_scene"],
            "route_labels": receipt["route_labels"],
            "walkthrough_route_labels": receipt["walkthrough_route_labels"],
            "room_stop_count": 4,
            "walkthrough_stop_count": 5,
            "photo_reference_panel_count": 2,
            "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
            "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
            "walkthrough_coverage_proof": receipt["walkthrough"]["coverage_proof"],
            "walkthrough_composition": "route_focused_stop_cards",
            "walkthrough_motion_style": "ken_burns_route_cards",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "disclosure": receipt["disclosure"],
            "glb_export_status": "skipped",
        }
        manifest["video_provider"] = "propertyquarry_generated_reconstruction"
        manifest["video_provider_key"] = "propertyquarry_generated_reconstruction"
        manifest["video_render_provider"] = "propertyquarry_generated_reconstruction"
        manifest["video_source"] = "propertyquarry_generated_reconstruction"
        manifest["video_relpath"] = "generated-reconstruction/generated-walkthrough.mp4"
        manifest["video_sidecar_relpath"] = "generated-reconstruction/generated-walkthrough.quality.json"
        manifest["video_coverage_proof"] = "boundary_verified_frame_continuation"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "generated"}

    monkeypatch.setattr(product_service, "_run_property_reconstruction_render_bridge", _fake_bridge)

    payload = product_service._write_generated_reconstruction_property_tour_bundle(
        principal_id="property-tour-render-bridge",
        title="Bridge-backed maisonette",
        listing_id="listing-render-bridge-1",
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/bridge-backed-maisonette-1",
        variant_key="layout_first",
        media_urls=["https://img.example.test/living.jpg", "https://img.example.test/bedroom.jpg"],
        floorplan_urls=["https://img.example.test/floorplan.jpg"],
        property_facts_json={
            "rooms": 3,
            "description": "Maisonette mit Balkon und Wohnbereich.",
        },
        source_host="www.willhaben.at",
        diorama_style_hint="Ikea",
    )

    assert payload["video_relpath"] == "generated-reconstruction/generated-walkthrough.mp4"
    assert payload["video_provider"] == "propertyquarry_generated_reconstruction"
    assert observed["slug"] == payload["slug"]
    assert observed["style_label"] == "Ikea"
    assert observed["skip_video"] is False
    assert str(observed["floorplan_path"]).startswith(str((public_root / payload["slug"]).resolve()))
    assert len(list(observed["photo_paths"])) == 2


def test_hosted_property_tour_video_delivery_falls_back_to_sidecar_duration_when_ffprobe_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug = "generated-reconstruction-duration-fallback"
    public_root = tmp_path / "public_tours"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    generated_dir = bundle_dir / "generated-reconstruction"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "generated-walkthrough.mp4").write_bytes(b"video")
    (generated_dir / "generated-walkthrough.quality.json").write_text(
        json.dumps(
            {
                "duration_seconds": 6.25,
                "covered_route_labels": ["entry/hall", "living area"],
                "walkthrough_coverage_proof": {
                    "status": "pass",
                    "coverage_segments": [
                        {"segment": "entry/hall", "start": 0.0, "end": 2.0},
                        {"segment": "living area", "start": 2.0, "end": 4.0},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                "video_provider": "propertyquarry_generated_reconstruction",
                "video_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                "video_coverage_proof": "boundary_verified_frame_continuation",
                "generated_reconstruction": {
                    "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                    "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                    "walkthrough_coverage_proof": {"status": "pass"},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_service, "_video_duration_seconds", lambda value: 0.0)

    delivery = product_service._hosted_property_tour_video_delivery(f"https://propertyquarry.com/tours/{slug}")

    assert delivery["duration_seconds"] == pytest.approx(6.25)


def test_hosted_property_tour_video_delivery_falls_back_to_coverage_segments_when_sidecar_duration_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    slug = "generated-reconstruction-coverage-fallback"
    public_root = tmp_path / "public_tours"
    bundle_dir = _write_base_tour(tmp_path, slug)
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    generated_dir = bundle_dir / "generated-reconstruction"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "generated-walkthrough.mp4").write_bytes(b"video")
    (generated_dir / "generated-walkthrough.quality.json").write_text(
        json.dumps(
            {
                "covered_route_labels": ["entry/hall", "living area", "sleeping area"],
                "walkthrough_coverage_proof": {
                    "status": "pass",
                    "coverage_segments": [
                        {"segment": "entry/hall", "start": 0.0, "end": 1.25},
                        {"segment": "living area", "start": 1.25, "end": 3.5},
                        {"segment": "sleeping area", "start": 3.5, "end": 5.75},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                "video_provider": "propertyquarry_generated_reconstruction",
                "video_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                "video_coverage_proof": "boundary_verified_frame_continuation",
                "generated_reconstruction": {
                    "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                    "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                    "walkthrough_coverage_proof": {"status": "pass"},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_service, "_video_duration_seconds", lambda value: 0.0)

    delivery = product_service._hosted_property_tour_video_delivery(f"https://propertyquarry.com/tours/{slug}")

    assert delivery["duration_seconds"] == pytest.approx(5.75)


def test_service_generated_reconstruction_raises_when_render_bridge_returns_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public_root = tmp_path / "public_tours"
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_root))
    floorplan = tmp_path / "floorplan.jpg"
    photo = tmp_path / "living.jpg"
    _write_floorplan(floorplan)
    _write_photo(photo, (126, 108, 82))
    asset_map = {
        "https://img.example.test/floorplan.jpg": floorplan,
        "https://img.example.test/living.jpg": photo,
    }

    monkeypatch.setattr(
        product_service,
        "_download_property_reconstruction_image",
        lambda url, target_dir, *, stem: asset_map.get(str(url or "").strip()),
    )
    monkeypatch.setattr(product_service.shutil, "which", lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}")

    def _fail_bridge(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("property_reconstruction_render_bridge_failed:generator_exit_nonzero")

    monkeypatch.setattr(product_service, "_run_property_reconstruction_render_bridge", _fail_bridge)

    with pytest.raises(RuntimeError, match="property_reconstruction_render_bridge_failed:generator_exit_nonzero"):
        product_service._write_generated_reconstruction_property_tour_bundle(
            principal_id="property-tour-render-bridge-fail",
            title="Bridge-backed maisonette",
            listing_id="listing-render-bridge-fail-1",
            property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/bridge-backed-maisonette-fail-1",
            variant_key="layout_first",
            media_urls=["https://img.example.test/living.jpg"],
            floorplan_urls=["https://img.example.test/floorplan.jpg"],
            property_facts_json={"rooms": 2},
            source_host="www.willhaben.at",
        )


def test_run_property_reconstruction_render_bridge_uses_request_timeout_buffer(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_URL", "http://bridge.example/generate-reconstruction")
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_TIMEOUT_SECONDS", "480")
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_REQUEST_TIMEOUT_SECONDS", raising=False)
    observed: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"status":"generated","result":{"status":"generated"}}'

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        observed["timeout"] = timeout
        observed["url"] = request.full_url
        return _Response()

    monkeypatch.setattr(product_service.urllib.request, "urlopen", _fake_urlopen)

    result = product_service._run_property_reconstruction_render_bridge(
        slug="bridge-timeout-test",
        floorplan_path=None,
        photo_paths=[],
        style_label="",
        room_count=0,
        route_labels=[],
        skip_video=False,
    )

    assert observed["url"] == "http://bridge.example/generate-reconstruction"
    assert observed["timeout"] == 540
    assert result["status"] == "generated"


def test_property_reconstruction_bundle_generation_timeout_scales_for_video_complexity(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_TIMEOUT_SECONDS", raising=False)

    assert (
        product_service._property_reconstruction_bundle_generation_timeout_seconds(
            skip_video=False,
            route_stop_count=6,
            photo_count=2,
            room_count=6,
        )
        == 600
    )
    assert (
        product_service._property_reconstruction_bundle_generation_timeout_seconds(
            skip_video=True,
            route_stop_count=6,
            photo_count=2,
            room_count=6,
        )
        == 420
    )


def test_run_property_reconstruction_render_bridge_forwards_walkthrough_seconds_per_stop(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_URL", "http://bridge.example/generate-reconstruction")
    monkeypatch.setenv("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP", "8")
    observed: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"status":"generated","result":{"status":"generated"}}'

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        observed["body"] = json.loads(request.data.decode("utf-8"))
        observed["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(product_service.urllib.request, "urlopen", _fake_urlopen)

    result = product_service._run_property_reconstruction_render_bridge(
        slug="bridge-walkthrough-duration-test",
        floorplan_path=None,
        photo_paths=[],
        style_label="",
        room_count=0,
        route_labels=[],
        skip_video=False,
    )

    assert result["status"] == "generated"
    assert observed["body"]["walkthrough_seconds_per_stop"] == 8.0
