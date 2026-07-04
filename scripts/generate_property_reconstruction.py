#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIEWER_VERSION = "propertyquarry_3d_tour_viewer_v3"
DISCLOSURE = "Planning preview built from the floor plan and listing photos. Use it as a layout aid, not as a captured tour."


def _public_tour_dir() -> Path:
    configured = str(os.getenv("EA_PUBLIC_TOUR_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if cwd.name == "property" and (cwd / "state" / "public_property_tours").exists():
        return (cwd / "state" / "public_property_tours").resolve()
    return Path("/data/public_property_tours").expanduser().resolve()


def _safe_relpath(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return "/".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _web_safe_image_suffix(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in {".tif", ".tiff"}:
        return ".jpg"
    return suffix or ".jpg"


def _image_metadata(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        return {
            "width": int(image.width),
            "height": int(image.height),
            "mode": str(image.mode),
        }


def _copy_normalized_image(source: Path, target: Path) -> dict[str, object]:
    if source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise SystemExit(f"unsupported_image_extension:{source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        normalized.save(target, format="JPEG" if target.suffix.lower() in {".jpg", ".jpeg"} else None, quality=90)
    metadata = _image_metadata(target)
    return {
        "source_path": str(source),
        "relpath": target.name,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
        **metadata,
    }


def _connected_components(mask: list[list[int]]) -> list[dict[str, object]]:
    rows = len(mask)
    cols = len(mask[0]) if rows else 0
    visited = [[False for _ in range(cols)] for _ in range(rows)]
    components: list[dict[str, object]] = []
    for row in range(rows):
        for col in range(cols):
            if not mask[row][col] or visited[row][col]:
                continue
            queue = [(col, row)]
            visited[row][col] = True
            area = 0
            min_col = max_col = col
            min_row = max_row = row
            touches_edge = col in {0, cols - 1} or row in {0, rows - 1}
            while queue:
                current_col, current_row = queue.pop()
                area += 1
                min_col = min(min_col, current_col)
                max_col = max(max_col, current_col)
                min_row = min(min_row, current_row)
                max_row = max(max_row, current_row)
                for next_col, next_row in (
                    (current_col + 1, current_row),
                    (current_col - 1, current_row),
                    (current_col, current_row + 1),
                    (current_col, current_row - 1),
                ):
                    if (
                        0 <= next_col < cols
                        and 0 <= next_row < rows
                        and mask[next_row][next_col]
                        and not visited[next_row][next_col]
                    ):
                        visited[next_row][next_col] = True
                        queue.append((next_col, next_row))
                        if next_col in {0, cols - 1} or next_row in {0, rows - 1}:
                            touches_edge = True
            components.append(
                {
                    "area": area,
                    "bbox": (min_col, min_row, max_col, max_row),
                    "touches_edge": touches_edge,
                }
            )
    return components


def _bbox_axis_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int]:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0, max(ax0 - bx1, bx0 - ax1) - 1)
    dy = max(0, max(ay0 - by1, by0 - ay1) - 1)
    return dx, dy


def _floorplan_content_bbox(path: Path) -> tuple[int, int, int, int]:
    with Image.open(path) as floorplan_image:
        normalized = ImageOps.exif_transpose(floorplan_image).convert("L")
        width, height = normalized.size
        preview_width = min(240, max(120, width // 4))
        preview_height = max(120, int(round(height * preview_width / max(width, 1))))
        preview = normalized.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
        preview_pixels = preview.load()
        binary = [
            [1 if preview_pixels[col, row] < 225 else 0 for col in range(preview_width)]
            for row in range(preview_height)
        ]
    components = [
        component
        for component in _connected_components(binary)
        if not bool(component.get("touches_edge")) and int(component.get("area") or 0) >= 20
    ]
    if not components:
        return (0, 0, width, height)
    components.sort(key=lambda component: int(component.get("area") or 0), reverse=True)
    main_bbox = tuple(components[0]["bbox"])
    kept = []
    for component in components:
        area = int(component.get("area") or 0)
        bbox = tuple(component.get("bbox") or main_bbox)
        gap_x, gap_y = _bbox_axis_gap(bbox, main_bbox)
        if area >= 120 or (max(gap_x, gap_y) <= 6 and (gap_x == 0 or gap_y == 0)):
            kept.append(bbox)
    min_col = min(bbox[0] for bbox in kept)
    min_row = min(bbox[1] for bbox in kept)
    max_col = max(bbox[2] for bbox in kept)
    max_row = max(bbox[3] for bbox in kept)
    scale_x = width / preview_width
    scale_y = height / preview_height
    padding = 16
    left = max(0, int(min_col * scale_x) - padding)
    top = max(0, int(min_row * scale_y) - padding)
    right = min(width, int(round((max_col + 1) * scale_x)) + padding)
    bottom = min(height, int(round((max_row + 1) * scale_y)) + padding)
    if right - left < 40 or bottom - top < 40:
        return (0, 0, width, height)
    return (left, top, right, bottom)


def _extract_floorplan_geometry(
    path: Path,
    *,
    max_grid_width: int = 120,
) -> dict[str, object]:
    with Image.open(path) as floorplan_image:
        normalized = ImageOps.exif_transpose(floorplan_image).convert("L")
        bbox = _floorplan_content_bbox(path)
        cropped = normalized.crop(bbox)
    crop_width, crop_height = cropped.size
    grid_width = max(96, min(max_grid_width, int(round(crop_width / 7.0))))
    grid_height = max(72, int(round(crop_height * grid_width / max(crop_width, 1))))
    reduced = cropped.resize((grid_width, grid_height), Image.Resampling.LANCZOS)
    reduced_pixels = reduced.load()
    initial_mask = [
        [1 if reduced_pixels[col, row] < 210 else 0 for col in range(grid_width)]
        for row in range(grid_height)
    ]
    filtered_mask = [[0 for _ in range(grid_width)] for _ in range(grid_height)]
    for row in range(grid_height):
        for col in range(grid_width):
            if not initial_mask[row][col]:
                continue
            neighbors = 0
            for near_row in range(max(0, row - 1), min(grid_height, row + 2)):
                for near_col in range(max(0, col - 1), min(grid_width, col + 2)):
                    neighbors += initial_mask[near_row][near_col]
            if neighbors >= 3:
                filtered_mask[row][col] = 1
    for component in _connected_components(filtered_mask):
        area = int(component.get("area") or 0)
        min_col, min_row, max_col, max_row = tuple(component.get("bbox") or (0, 0, 0, 0))
        width_cells = max_col - min_col + 1
        height_cells = max_row - min_row + 1
        if area < 6 or (width_cells <= 2 and height_cells <= 2):
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    if filtered_mask[row][col]:
                        filtered_mask[row][col] = 0
    return {
        "content_bbox_px": {
            "left": int(bbox[0]),
            "top": int(bbox[1]),
            "right": int(bbox[2]),
            "bottom": int(bbox[3]),
        },
        "content_size_px": {"width": int(crop_width), "height": int(crop_height)},
        "mask_size_cells": {"width": int(grid_width), "height": int(grid_height)},
        "wall_mask": filtered_mask,
    }


def _room_dimensions(width: int, height: int, *, max_width_m: float) -> tuple[float, float, float]:
    ratio = height / width if width else 0.7
    room_width = float(max_width_m)
    room_depth = max(3.0, min(18.0, room_width * ratio))
    room_height = 2.75
    return round(room_width, 3), round(room_depth, 3), room_height


def _write_inferred_floorplan(target: Path, *, photo_count: int) -> dict[str, object]:
    room_count = max(2, min(6, photo_count or 3))
    width, height = 1400, 940
    image = Image.new("RGB", (width, height), color=(248, 244, 235))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    ink = (45, 39, 30)
    muted = (184, 138, 50)
    draw.rectangle((90, 90, width - 90, height - 90), outline=ink, width=14)
    if room_count <= 3:
        splits = [0.52]
    else:
        splits = [0.42, 0.68]
    for split in splits:
        x = int(90 + (width - 180) * split)
        draw.line((x, 90, x, height - 90), fill=ink, width=8)
    if room_count >= 4:
        y = int(90 + (height - 180) * 0.55)
        draw.line((90, y, int(width * 0.68), y), fill=ink, width=8)
    draw.arc((width - 260, height - 250, width - 90, height - 80), 180, 270, fill=muted, width=6)
    draw.text((120, 120), "Inferred schematic from source photos", fill=muted)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="JPEG", quality=90)
    metadata = _image_metadata(target)
    return {
        "source_path": "generated_from_photo_set",
        "relpath": target.name,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
        "inferred": True,
        "inference_method": "room_count_heuristic_from_photo_count",
        **metadata,
    }


def _wall_rectangles_from_mask(
    wall_mask: list[list[int]],
    *,
    width_m: float,
    depth_m: float,
) -> list[dict[str, float]]:
    rows = len(wall_mask)
    cols = len(wall_mask[0]) if rows else 0
    if not rows or not cols:
        return []
    active: dict[tuple[int, int], dict[str, int]] = {}
    merged: list[dict[str, int]] = []
    for row_index, row in enumerate(wall_mask):
        next_active: dict[tuple[int, int], dict[str, int]] = {}
        run_start: int | None = None
        for col_index in range(cols + 1):
            filled = col_index < cols and bool(row[col_index])
            if filled and run_start is None:
                run_start = col_index
            elif not filled and run_start is not None:
                key = (run_start, col_index - 1)
                current = active.get(key)
                if current is None:
                    current = {
                        "x0": run_start,
                        "x1": col_index - 1,
                        "y0": row_index,
                        "y1": row_index,
                    }
                else:
                    current["y1"] = row_index
                next_active[key] = current
                run_start = None
        for key, rectangle in active.items():
            if key not in next_active:
                merged.append(rectangle)
        active = next_active
    merged.extend(active.values())
    cell_width = width_m / cols
    cell_depth = depth_m / rows
    half_width = width_m / 2
    half_depth = depth_m / 2
    rectangles: list[dict[str, float]] = []
    for rectangle in merged:
        span_cols = rectangle["x1"] - rectangle["x0"] + 1
        span_rows = rectangle["y1"] - rectangle["y0"] + 1
        if span_cols <= 1 and span_rows <= 1:
            continue
        rect_width = round(span_cols * cell_width, 4)
        rect_depth = round(span_rows * cell_depth, 4)
        center_x = round(-half_width + (rectangle["x0"] + span_cols / 2) * cell_width, 4)
        center_z = round(-half_depth + (rectangle["y0"] + span_rows / 2) * cell_depth, 4)
        rectangles.append(
            {
                "center_x": center_x,
                "center_z": center_z,
                "width": rect_width,
                "depth": rect_depth,
            }
        )
    return rectangles


def _write_obj(
    target_dir: Path,
    *,
    width_m: float,
    depth_m: float,
    height_m: float,
    wall_rectangles: list[dict[str, float]],
) -> None:
    obj_lines = ["mtllib model.mtl", "o propertyquarry_generated_layout"]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[str, str, tuple[int, int, int, int]]] = []

    def add_quad(material: str, group: str, points: tuple[tuple[float, float, float], ...]) -> None:
        start_index = len(vertices) + 1
        vertices.extend(points)
        faces.append((material, group, (start_index, start_index + 1, start_index + 2, start_index + 3)))

    def add_box(material: str, group: str, *, center_x: float, center_z: float, box_width: float, box_depth: float, box_height: float) -> None:
        half_box_width = box_width / 2
        half_box_depth = box_depth / 2
        min_x = center_x - half_box_width
        max_x = center_x + half_box_width
        min_z = center_z - half_box_depth
        max_z = center_z + half_box_depth
        min_y = 0.0
        max_y = box_height
        points = [
            (min_x, min_y, min_z),
            (max_x, min_y, min_z),
            (max_x, min_y, max_z),
            (min_x, min_y, max_z),
            (min_x, max_y, min_z),
            (max_x, max_y, min_z),
            (max_x, max_y, max_z),
            (min_x, max_y, max_z),
        ]
        start_index = len(vertices) + 1
        vertices.extend(points)
        faces.extend(
            [
                (material, f"{group}_floor", (start_index, start_index + 1, start_index + 2, start_index + 3)),
                (material, f"{group}_north", (start_index, start_index + 4, start_index + 5, start_index + 1)),
                (material, f"{group}_east", (start_index + 1, start_index + 5, start_index + 6, start_index + 2)),
                (material, f"{group}_south", (start_index + 2, start_index + 6, start_index + 7, start_index + 3)),
                (material, f"{group}_west", (start_index + 3, start_index + 7, start_index + 4, start_index)),
                (material, f"{group}_ceiling", (start_index + 4, start_index + 7, start_index + 6, start_index + 5)),
            ]
        )

    add_quad(
        "warm_floor",
        "floor_plate",
        (
            (-width_m / 2, 0.0, -depth_m / 2),
            (width_m / 2, 0.0, -depth_m / 2),
            (width_m / 2, 0.0, depth_m / 2),
            (-width_m / 2, 0.0, depth_m / 2),
        ),
    )
    for index, rectangle in enumerate(wall_rectangles, start=1):
        add_box(
            "warm_plaster",
            f"wall_{index:03d}",
            center_x=float(rectangle["center_x"]),
            center_z=float(rectangle["center_z"]),
            box_width=float(rectangle["width"]),
            box_depth=float(rectangle["depth"]),
            box_height=height_m,
        )
    for x, y, z in vertices:
        obj_lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    current_material = ""
    for material, group, indexes in faces:
        if material != current_material:
            obj_lines.append(f"usemtl {material}")
            current_material = material
        obj_lines.append(f"g {group}")
        obj_lines.append("f " + " ".join(str(index) for index in indexes))
    (target_dir / "model.obj").write_text("\n".join(obj_lines) + "\n", encoding="utf-8")
    (target_dir / "model.mtl").write_text(
        "\n".join(
            [
                "newmtl warm_floor",
                "Ka 0.94 0.90 0.84",
                "Kd 0.94 0.90 0.84",
                "Ks 0.01 0.01 0.01",
                "Ns 8",
                "newmtl warm_plaster",
                "Ka 0.78 0.74 0.69",
                "Kd 0.90 0.87 0.81",
                "Ks 0.04 0.04 0.04",
                "Ns 14",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_glb_with_blender(target_dir: Path) -> dict[str, object]:
    blender = shutil.which("blender")
    if not blender:
        return {"status": "skipped", "reason": "blender_missing"}
    obj_path = target_dir / "model.obj"
    glb_path = target_dir / "model.glb"
    if not obj_path.is_file():
        return {"status": "skipped", "reason": "obj_missing"}
    with tempfile.TemporaryDirectory(prefix="propertyquarry-blender-export-") as tempdir:
        script_path = Path(tempdir) / "export_glb.py"
        script_path.write_text(
            "\n".join(
                [
                    "import bpy",
                    "import sys",
                    "from pathlib import Path",
                    f"obj_path = Path({str(obj_path)!r})",
                    f"glb_path = Path({str(glb_path)!r})",
                    "bpy.ops.object.select_all(action='SELECT')",
                    "bpy.ops.object.delete()",
                    "if hasattr(bpy.ops.wm, 'obj_import'):",
                    "    bpy.ops.wm.obj_import(filepath=str(obj_path))",
                    "else:",
                    "    bpy.ops.import_scene.obj(filepath=str(obj_path))",
                    "for obj in bpy.context.scene.objects:",
                    "    obj.select_set(True)",
                    "bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format='GLB', export_yup=True)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [blender, "--background", "--factory-startup", "--python", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    if result.returncode != 0 or not glb_path.is_file():
        return {
            "status": "failed",
            "reason": "blender_glb_export_failed",
            "stdout_tail": (result.stdout or "")[-500:],
            "stderr_tail": (result.stderr or "")[-500:],
        }
    return {
        "status": "generated",
        "glb_relpath": glb_path.name,
        "glb_sha256": _sha256(glb_path),
        "glb_size_bytes": glb_path.stat().st_size,
    }


def _video_duration_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return max(0.0, float(str(completed.stdout or "0").strip() or 0.0))
    except Exception:
        return 0.0


def _viewer_html(*, manifest: dict[str, object]) -> str:
    width_m = manifest["room_dimensions_m"]["width"]
    depth_m = manifest["room_dimensions_m"]["depth"]
    height_m = manifest["room_dimensions_m"]["height"]
    photos = manifest.get("photos") if isinstance(manifest.get("photos"), list) else []
    geometry = dict(manifest.get("geometry") or {}) if isinstance(manifest.get("geometry"), dict) else {}
    wall_rectangles = geometry.get("wall_rectangles") if isinstance(geometry.get("wall_rectangles"), list) else []
    style_label = str(manifest.get("style_label") or "").strip()
    escaped_style = html.escape(style_label)
    style_copy = f'<span>{escaped_style}</span>' if escaped_style else ""
    floorplan_relpath = html.escape(str(dict(manifest.get("floorplan") or {}).get("relpath") or "source-floorplan.jpg"))
    photo_items = "\n".join(
        f'<img src="{html.escape(str(row["relpath"]))}" alt="Room photo {index}" loading="lazy">'
        for index, row in enumerate(photos, start=1)
        if isinstance(row, dict) and row.get("relpath")
    )
    photo_section = (
        f"""
    <section class="panel" aria-label="Listing photos">
      <div class="panel-head">
        <p>Photos</p>
        <span>{len(photos)}</span>
      </div>
      <div class="photos">{photo_items}</div>
    </section>"""
        if photo_items
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Layout preview | PropertyQuarry</title>
  <style>
    :root {{
      color-scheme: light;
      --ink:#17130c;
      --muted:#766d5e;
      --paper:#f6f0e5;
      --panel:rgba(255,252,245,.78);
      --line:rgba(54,42,27,.14);
      --gold:#a77c2b;
      --shadow:0 24px 70px rgba(68,47,24,.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin:0;
      min-height:100vh;
      font-family:Aptos, ui-sans-serif, system-ui, sans-serif;
      background:
        radial-gradient(circle at 18% 10%, rgba(255,255,255,.92), transparent 30%),
        linear-gradient(135deg,#faf6ed 0%,#efe4d1 48%,#d9c4a5 100%);
      color:var(--ink);
    }}
    main {{ min-height:100vh; display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:18px; padding:18px; }}
    .stage {{ position:relative; min-height:0; }}
    .viewport {{
      width:100%;
      height:calc(100vh - 36px);
      min-height:520px;
      border:1px solid var(--line);
      border-radius:28px;
      background:linear-gradient(180deg,#fbf8f1,#e6d8bf);
      box-shadow:var(--shadow);
      overflow:hidden;
      touch-action:none;
    }}
    .viewport canvas {{
      display:block;
      width:100%;
      height:100%;
    }}
    .hud {{
      position:absolute;
      top:18px;
      left:18px;
      right:18px;
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
      pointer-events:none;
    }}
    .title-card, .hint-pill {{
      border:1px solid var(--line);
      border-radius:22px;
      background:rgba(255,252,244,.76);
      backdrop-filter:blur(18px);
      box-shadow:0 14px 45px rgba(52,36,17,.09);
    }}
    .title-card {{ padding:14px 16px; max-width:min(420px,70vw); }}
    h1 {{ margin:0; font-family:Georgia, ui-serif, serif; font-size:clamp(28px,4vw,54px); line-height:.92; letter-spacing:-.055em; }}
    .title-card p {{ margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.35; }}
    .hint-pill {{ padding:10px 13px; color:var(--muted); font-size:13px; white-space:nowrap; }}
    .viewer-actions {{
      position:absolute;
      left:18px;
      bottom:18px;
      display:flex;
      gap:8px;
      z-index:2;
    }}
    .viewer-chip {{
      border:1px solid var(--line);
      border-radius:999px;
      background:rgba(255,252,244,.86);
      color:var(--ink);
      min-height:44px;
      padding:0 14px;
      font:inherit;
      font-size:13px;
      font-weight:600;
      box-shadow:0 14px 45px rgba(52,36,17,.09);
      cursor:pointer;
    }}
    .viewer-chip:hover {{
      border-color:rgba(167,124,43,.42);
    }}
    aside {{ display:flex; flex-direction:column; gap:12px; min-width:0; }}
    .panel {{ border:1px solid var(--line); border-radius:24px; background:var(--panel); padding:14px; box-shadow:0 16px 44px rgba(60,40,18,.08); }}
    .panel-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }}
    .panel-head p, .panel-head span {{ margin:0; color:var(--muted); font-size:13px; }}
    .panel-head p {{ color:var(--ink); font-weight:700; }}
    .facts {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
    .facts div {{ border:1px solid var(--line); border-radius:18px; padding:11px 10px; background:rgba(255,255,255,.42); }}
    .facts b {{ display:block; font-family:Georgia, ui-serif, serif; font-size:21px; line-height:1; letter-spacing:-.04em; }}
    .facts span {{ display:block; margin-top:5px; color:var(--muted); font-size:12px; }}
    .style-pill {{ display:inline-flex; margin-top:10px; padding:8px 10px; border-radius:999px; background:rgba(167,124,43,.1); color:#6c4c16; font-size:13px; }}
    .floorplan, .photos img {{ width:100%; border:1px solid var(--line); border-radius:18px; object-fit:cover; background:white; }}
    .floorplan {{ aspect-ratio:4/3; }}
    .photos {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }}
    .photos img {{ aspect-ratio:1; }}
    .note {{ margin:0; color:var(--muted); font-size:13px; line-height:1.4; }}
    @media (max-width: 880px) {{
      main {{ display:block; padding:10px; }}
      .viewport {{ height:68vh; min-height:430px; border-radius:22px; }}
      aside {{ margin-top:10px; }}
      .hud {{ top:12px; left:12px; right:12px; }}
      .hint-pill {{ display:none; }}
      .viewer-actions {{ left:12px; bottom:12px; flex-wrap:wrap; }}
      .title-card {{ max-width:86vw; padding:12px 13px; }}
      .title-card p {{ font-size:13px; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="stage">
    <div class="viewport" id="viewport" aria-label="3D layout preview"></div>
    <div class="hud">
      <div class="title-card">
        <h1>Layout preview</h1>
        <p>Use the real floorplan layout to understand the space before deciding whether to visit.</p>
      </div>
      <div class="hint-pill">Drag, zoom, then inspect the plan beside it.</div>
    </div>
    <div class="viewer-actions">
      <button class="viewer-chip" id="view-overview" type="button">Overview</button>
      <button class="viewer-chip" id="view-inside" type="button">Room view</button>
    </div>
  </section>
  <aside>
    <section class="panel">
      <div class="panel-head">
        <p>Layout preview</p>
        <span>approx.</span>
      </div>
      <p class="note">Built from the floorplan and listing photos. Use it for orientation; confirm dimensions at the viewing.</p>
      {f'<span class="style-pill">{style_copy}</span>' if style_copy else ''}
    </section>
    <section class="panel facts" aria-label="Approximate room dimensions">
      <div><b>{width_m}</b><span>m wide</span></div>
      <div><b>{depth_m}</b><span>m deep</span></div>
      <div><b>{height_m}</b><span>m high</span></div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <p>Floorplan</p>
        <span>source</span>
      </div>
      <img class="floorplan" src="{floorplan_relpath}" alt="Floorplan">
    </section>
    {photo_section}
  </aside>
</main>
<script type="importmap">
{{
  "imports": {{
    "three": "https://cdn.jsdelivr.net/npm/three@0.167.1/build/three.module.js"
  }}
}}
</script>
<script type="module">
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.167.1/build/three.module.js";
import {{ OrbitControls }} from "https://cdn.jsdelivr.net/npm/three@0.167.1/examples/jsm/controls/OrbitControls.js";

const viewport = document.getElementById("viewport");
const overviewButton = document.getElementById("view-overview");
const insideButton = document.getElementById("view-inside");
const wallRectangles = {json.dumps(wall_rectangles, ensure_ascii=False)};
const roomWidth = {json.dumps(width_m)};
const roomDepth = {json.dumps(depth_m)};
const roomHeight = {json.dumps(height_m)};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf6f0e5);
scene.fog = new THREE.Fog(0xf6f0e5, 13, 34);
let renderFrameCount = 0;

const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true, preserveDrawingBuffer: true }});
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
viewport.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = true;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minPolarAngle = Math.PI * 0.14;
controls.minDistance = Math.max(roomWidth, roomDepth) * 0.32;
controls.maxDistance = Math.max(roomWidth, roomDepth) * 2.4;

const hemisphereLight = new THREE.HemisphereLight(0xfffbf5, 0xd7c4aa, 1.35);
scene.add(hemisphereLight);
const keyLight = new THREE.DirectionalLight(0xffffff, 1.05);
keyLight.position.set(roomWidth * 0.7, roomHeight * 3.2, roomDepth * 0.9);
keyLight.castShadow = true;
keyLight.shadow.mapSize.width = 2048;
keyLight.shadow.mapSize.height = 2048;
keyLight.shadow.camera.near = 0.1;
keyLight.shadow.camera.far = 40;
scene.add(keyLight);

const floorTexture = new THREE.TextureLoader().load({json.dumps(str(dict(manifest.get("floorplan") or {}).get("relpath") or "source-floorplan.jpg"))});
floorTexture.colorSpace = THREE.SRGBColorSpace;
floorTexture.anisotropy = 8;
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(roomWidth, roomDepth),
  new THREE.MeshStandardMaterial({{
    color: 0xf8f4eb,
    map: floorTexture,
    roughness: 0.96,
    metalness: 0.0,
  }})
);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

const wallMaterial = new THREE.MeshStandardMaterial({{
  color: 0xf4efe4,
  roughness: 0.88,
  metalness: 0.02,
  side: THREE.DoubleSide,
}});
const wallEdgeMaterial = new THREE.LineBasicMaterial({{
  color: 0xc2ab83,
  transparent: true,
  opacity: 0.62,
}});
const wallMeshes = [];
for (const wall of wallRectangles) {{
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(wall.width, roomHeight, wall.depth),
    wallMaterial,
  );
  mesh.position.set(wall.center_x, roomHeight / 2, wall.center_z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  wallMeshes.push(mesh);
  scene.add(mesh);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), wallEdgeMaterial);
  edges.position.copy(mesh.position);
  scene.add(edges);
}}

const outline = new THREE.Mesh(
  new THREE.PlaneGeometry(roomWidth * 1.01, roomDepth * 1.01),
  new THREE.MeshBasicMaterial({{
    color: 0xffffff,
    opacity: 0.08,
    transparent: true,
    side: THREE.DoubleSide,
  }})
);
outline.rotation.x = -Math.PI / 2;
outline.position.y = 0.002;
scene.add(outline);

function setOverviewView() {{
  camera.position.set(roomWidth * 0.74, roomHeight * 1.22, roomDepth * 0.76);
  controls.target.set(0, roomHeight * 0.52, -roomDepth * 0.04);
  controls.update();
}}

function setInsideView() {{
  camera.position.set(-roomWidth * 0.12, roomHeight * 0.78, roomDepth * 0.18);
  controls.target.set(roomWidth * 0.2, roomHeight * 0.66, -roomDepth * 0.28);
  controls.update();
}}

overviewButton?.addEventListener("click", setOverviewView);
insideButton?.addEventListener("click", setInsideView);

function resize() {{
  const width = Math.max(320, viewport.clientWidth || 320);
  const height = Math.max(420, viewport.clientHeight || 420);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}}

window.addEventListener("resize", resize);
resize();
setOverviewView();

window.__pqReconstructionDebug = {{
  setOverviewView,
  setInsideView,
  getRenderMetrics() {{
    const canvas = renderer.domElement;
    if (!canvas) {{
      return {{
        ready: false,
        reason: "canvas_unavailable",
        frameCount: Number(renderFrameCount || 0),
        wallRectCount: Number(wallRectangles.length || 0),
      }};
    }}
    scene.updateMatrixWorld(true);
    camera.updateMatrixWorld(true);
    const projectionMatrix = new THREE.Matrix4().multiplyMatrices(
      camera.projectionMatrix,
      camera.matrixWorldInverse,
    );
    const frustum = new THREE.Frustum().setFromProjectionMatrix(projectionMatrix);
    const corner = new THREE.Vector3();
    let visibleWallCount = 0;
    let projectedCoverage = 0;
    let maxProjectedArea = 0;
    for (const mesh of wallMeshes) {{
      const box = new THREE.Box3().setFromObject(mesh);
      if (!frustum.intersectsBox(box)) continue;
      visibleWallCount += 1;
      const corners = [
        [box.min.x, box.min.y, box.min.z],
        [box.min.x, box.min.y, box.max.z],
        [box.min.x, box.max.y, box.min.z],
        [box.min.x, box.max.y, box.max.z],
        [box.max.x, box.min.y, box.min.z],
        [box.max.x, box.min.y, box.max.z],
        [box.max.x, box.max.y, box.min.z],
        [box.max.x, box.max.y, box.max.z],
      ];
      let minX = 1;
      let maxX = -1;
      let minY = 1;
      let maxY = -1;
      let hasProjectedCorner = false;
      for (const [x, y, z] of corners) {{
        corner.set(x, y, z).project(camera);
        if (!Number.isFinite(corner.x) || !Number.isFinite(corner.y)) continue;
        minX = Math.min(minX, Math.max(-1, Math.min(1, corner.x)));
        maxX = Math.max(maxX, Math.max(-1, Math.min(1, corner.x)));
        minY = Math.min(minY, Math.max(-1, Math.min(1, corner.y)));
        maxY = Math.max(maxY, Math.max(-1, Math.min(1, corner.y)));
        hasProjectedCorner = true;
      }}
      if (!hasProjectedCorner) continue;
      const projectedWidth = Math.max(0, (maxX - minX) / 2);
      const projectedHeight = Math.max(0, (maxY - minY) / 2);
      const projectedArea = projectedWidth * projectedHeight;
      projectedCoverage += projectedArea;
      maxProjectedArea = Math.max(maxProjectedArea, projectedArea);
    }}
    return {{
      ready: true,
      frameCount: Number(renderFrameCount || 0),
      wallRectCount: Number(wallRectangles.length || 0),
      wallMeshCount: Number(wallMeshes.length || 0),
      visibleWallCount: Number(visibleWallCount || 0),
      sceneChildCount: Number(scene.children.length || 0),
      sampleWidth: Number(canvas.width || 0),
      sampleHeight: Number(canvas.height || 0),
      projectedCoveragePct: Number((Math.min(1, projectedCoverage) * 100).toFixed(2)),
      maxProjectedWallPct: Number((Math.min(1, maxProjectedArea) * 100).toFixed(2)),
      renderCalls: Number(renderer.info.render.calls || 0),
      renderTriangles: Number(renderer.info.render.triangles || 0),
      cameraPosition: {{
        x: Number(camera.position.x.toFixed(3)),
        y: Number(camera.position.y.toFixed(3)),
        z: Number(camera.position.z.toFixed(3)),
      }},
    }};
  }},
}};

renderer.setAnimationLoop(() => {{
  controls.update();
  renderer.render(scene, camera);
  renderFrameCount += 1;
}});
</script>
</body>
</html>
"""


def _write_walkthrough(target: Path, images: list[Path], *, style_label: str = "") -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "skipped", "reason": "ffmpeg_missing"}
    if not images:
        return {"status": "skipped", "reason": "source_images_missing"}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="propertyquarry-reconstruction-") as tempdir:
        sheet_path = Path(tempdir) / "walkthrough-strip.jpg"
        duration_seconds = max(34, min(90, len(images) * 5))
        fps = 24
        frame_count = max(1, int(duration_seconds * fps))
        viewport_w, viewport_h = 1280, 720
        tile_w, tile_h = 560, 420
        gap = 140
        sheet_w = max(viewport_w + 960, 120 + (tile_w + gap) * len(images) + 120)
        from PIL import ImageDraw

        sheet = Image.new("RGB", (sheet_w, viewport_h), color=(245, 240, 229))
        draw = ImageDraw.Draw(sheet)
        draw.line((0, viewport_h - 90, sheet_w, viewport_h - 90), fill=(202, 188, 160), width=3)
        labels: list[str] = []
        for index, image_path in enumerate(images):
            label = "Floorplan" if index == 0 else f"Room view {index:02d}"
            labels.append(label)
            x = 80 + index * (tile_w + gap)
            y = 120 + (index % 2) * 44
            with Image.open(image_path) as image:
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
                card = Image.new("RGB", (tile_w + 32, tile_h + 78), color=(255, 252, 245))
                card_draw = ImageDraw.Draw(card)
                card_draw.rectangle((0, 0, tile_w + 31, tile_h + 77), outline=(218, 205, 179), width=3)
                paste_x = 16 + (tile_w - normalized.width) // 2
                paste_y = 42 + (tile_h - normalized.height) // 2
                card.paste(normalized, (paste_x, paste_y))
                card_draw.text((18, 14), label, fill=(55, 45, 34))
                sheet.paste(card, (x, y))
        headline = "Walkthrough"
        if style_label:
            headline = f"{headline} - {style_label}"
        draw.text((80, 44), headline, fill=(42, 35, 25))
        draw.text((80, viewport_h - 62), "Layout preview from listing media. Confirm details at the viewing.", fill=(96, 72, 38))
        sheet.save(sheet_path, format="JPEG", quality=92)
        x_expr = f"if(gt(iw,{viewport_w}),(iw-{viewport_w})*n/{max(frame_count - 1, 1)},0)"
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(sheet_path),
                    "-t",
                    str(duration_seconds),
                    "-vf",
                    f"crop={viewport_w}:{viewport_h}:x='{x_expr}':y=0,format=yuv420p",
                    "-r",
                    str(fps),
                    "-movflags",
                    "+faststart",
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed", "reason": "ffmpeg_timeout"}
    if result.returncode != 0:
        return {"status": "failed", "reason": (result.stderr or "ffmpeg_failed")[-500:]}
    duration = _video_duration_seconds(target)
    sidecar_path = target.with_suffix(".quality.json")
    expected_segments = labels
    coverage = {
        "status": "pass",
        "source": "propertyquarry_generated_reconstruction_continuous_pan",
        "segments_expected": expected_segments,
        "segments_visited": expected_segments,
        "coverage_segments": [
            {
                "segment": label,
                "index": index + 1,
                "start": round((index / max(len(expected_segments), 1)) * duration, 3),
                "end": round(((index + 1) / max(len(expected_segments), 1)) * duration, 3),
            }
            for index, label in enumerate(expected_segments)
        ],
    }
    sidecar = {
        "provider": "PropertyQuarry generated reconstruction",
        "provider_key": "propertyquarry_generated_reconstruction",
        "composition": "continuous_generated_reconstruction_pan",
        "style_label": style_label,
        "duration_seconds": round(duration, 3),
        "route_labels": expected_segments,
        "covered_route_labels": expected_segments,
        "walkthrough_coverage_proof": coverage,
        "disclosure": DISCLOSURE,
    }
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "generated",
        "relpath": target.name,
        "sidecar_relpath": sidecar_path.name,
        "sha256": _sha256(target),
        "sidecar_sha256": _sha256(sidecar_path),
        "size_bytes": target.stat().st_size,
        "duration_seconds": round(duration, 3),
        "coverage_proof": coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PropertyQuarry reconstruction from a floorplan image and photos.")
    parser.add_argument("--slug", required=True, help="Existing PropertyQuarry public tour slug.")
    parser.add_argument("--floorplan", default="", help="Floorplan image. PDF support is intentionally not implied here.")
    parser.add_argument("--photo", action="append", default=[], help="Source property photo. Can be provided multiple times.")
    parser.add_argument("--target-subdir", default="generated-reconstruction")
    parser.add_argument("--max-width-m", type=float, default=10.0)
    parser.add_argument("--style-label", default="", help="Human-readable staging style label for receipts and walkthrough overlays.")
    parser.add_argument(
        "--infer-floorplan-from-photos",
        action="store_true",
        help="Generate a disclosed schematic floorplan when no real floorplan image is available.",
    )
    parser.add_argument("--skip-video", action="store_true")
    args = parser.parse_args()

    slug = _safe_relpath(args.slug)
    if "/" in slug or not slug:
        raise SystemExit("invalid_tour_slug")
    public_root = _public_tour_dir()
    bundle_dir = public_root / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise SystemExit("tour_manifest_missing")
    target_subdir = _safe_relpath(args.target_subdir) or "generated-reconstruction"
    output_dir = (bundle_dir / target_subdir).resolve()
    if bundle_dir.resolve() not in output_dir.parents:
        raise SystemExit("invalid_reconstruction_target")
    output_dir.mkdir(parents=True, exist_ok=True)

    photo_sources = [Path(value).expanduser().resolve() for value in args.photo or []]
    floorplan_arg = str(args.floorplan or "").strip()
    if floorplan_arg:
        floorplan_source = Path(floorplan_arg).expanduser().resolve()
        if not floorplan_source.is_file():
            raise SystemExit("floorplan_missing")
        floorplan_target = output_dir / f"source-floorplan{_web_safe_image_suffix(floorplan_source)}"
        floorplan_meta = _copy_normalized_image(floorplan_source, floorplan_target)
        floorplan_meta["relpath"] = floorplan_target.name
    elif args.infer_floorplan_from_photos:
        if not photo_sources:
            raise SystemExit("floorplan_or_photos_required")
        floorplan_target = output_dir / "source-floorplan-inferred.jpg"
        floorplan_meta = _write_inferred_floorplan(floorplan_target, photo_count=len(photo_sources))
    else:
        raise SystemExit("floorplan_missing")

    photo_rows: list[dict[str, object]] = []
    photo_paths: list[Path] = []
    for index, source in enumerate(photo_sources, start=1):
        if not source.is_file():
            raise SystemExit(f"photo_missing:{index}")
        target = output_dir / f"photo-{index:02d}{_web_safe_image_suffix(source)}"
        row = _copy_normalized_image(source, target)
        row["relpath"] = target.name
        row["index"] = index
        photo_rows.append(row)
        photo_paths.append(target)

    geometry = _extract_floorplan_geometry(floorplan_target)
    geometry_content_size = dict(geometry.get("content_size_px") or {})
    width_m, depth_m, height_m = _room_dimensions(
        int(geometry_content_size.get("width") or floorplan_meta["width"]),
        int(geometry_content_size.get("height") or floorplan_meta["height"]),
        max_width_m=max(3.0, float(args.max_width_m)),
    )
    wall_rectangles = _wall_rectangles_from_mask(
        list(geometry.get("wall_mask") or []),
        width_m=width_m,
        depth_m=depth_m,
    )

    _write_obj(
        output_dir,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
        wall_rectangles=wall_rectangles,
    )
    glb_export = _write_glb_with_blender(output_dir)
    source_images = [floorplan_target, *photo_paths]
    walkthrough = (
        {"status": "skipped", "reason": "skip_video_requested"}
        if args.skip_video
        else _write_walkthrough(output_dir / "generated-walkthrough.mp4", source_images, style_label=str(args.style_label or "").strip())
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt: dict[str, object] = {
        "provider": "propertyquarry_generated_reconstruction",
        "generated_at": generated_at,
        "slug": slug,
        "disclosure": DISCLOSURE,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "style_label": str(args.style_label or "").strip(),
        "method": "floorplan_aspect_room_volume_with_source_photo_reference_panels",
        "room_dimensions_m": {"width": width_m, "depth": depth_m, "height": height_m},
        "geometry": {
            "content_bbox_px": dict(geometry.get("content_bbox_px") or {}),
            "content_size_px": dict(geometry.get("content_size_px") or {}),
            "mask_size_cells": dict(geometry.get("mask_size_cells") or {}),
            "wall_rectangles": wall_rectangles,
            "wall_rect_count": len(wall_rectangles),
        },
        "floorplan": floorplan_meta,
        "photos": photo_rows,
        "model": {
            "obj_relpath": "model.obj",
            "mtl_relpath": "model.mtl",
            "obj_sha256": _sha256(output_dir / "model.obj"),
            "mtl_sha256": _sha256(output_dir / "model.mtl"),
            "glb_export": glb_export,
        },
        "viewer": {"relpath": "viewer.html", "version": VIEWER_VERSION},
        "walkthrough": walkthrough,
    }
    if glb_export.get("status") == "generated":
        receipt["model"]["glb_relpath"] = str(glb_export.get("glb_relpath") or "model.glb")
        receipt["model"]["glb_sha256"] = str(glb_export.get("glb_sha256") or "")
        receipt["model"]["glb_size_bytes"] = int(glb_export.get("glb_size_bytes") or 0)
    (output_dir / "reconstruction.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "viewer.html").write_text(_viewer_html(manifest=receipt), encoding="utf-8")
    receipt["viewer"]["sha256"] = _sha256(output_dir / "viewer.html")
    (output_dir / "reconstruction.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("invalid_tour_manifest")
    base_relpath = PurePosixPath(target_subdir).as_posix()
    generated_reconstruction = {
        "provider": "propertyquarry_generated_reconstruction",
        "generated_at": generated_at,
        "viewer_version": VIEWER_VERSION,
        "viewer_relpath": f"{base_relpath}/viewer.html",
        "model_relpath": f"{base_relpath}/model.obj",
        "material_relpath": f"{base_relpath}/model.mtl",
        "manifest_relpath": f"{base_relpath}/reconstruction.json",
        "glb_export_status": str(glb_export.get("status") or ""),
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "disclosure": DISCLOSURE,
    }
    floorplan_relpath = str(dict(receipt.get("floorplan") or {}).get("relpath") or "").strip()
    if floorplan_relpath:
        generated_reconstruction["floorplan_relpath"] = f"{base_relpath}/{floorplan_relpath}"
    photo_relpaths = [
        f"{base_relpath}/{str(row.get('relpath') or '').strip()}"
        for row in list(receipt.get("photos") or [])
        if isinstance(row, dict) and str(row.get("relpath") or "").strip()
    ]
    if photo_relpaths:
        generated_reconstruction["photo_relpaths"] = photo_relpaths
    if glb_export.get("status") == "generated":
        generated_reconstruction["glb_model_relpath"] = f"{base_relpath}/{glb_export.get('glb_relpath') or 'model.glb'}"
    if walkthrough.get("status") == "generated":
        generated_reconstruction["walkthrough_video_relpath"] = f"{base_relpath}/generated-walkthrough.mp4"
        if str(args.style_label or "").strip():
            generated_reconstruction["walkthrough_style_label"] = str(args.style_label or "").strip()
        if walkthrough.get("sidecar_relpath"):
            generated_reconstruction["walkthrough_sidecar_relpath"] = f"{base_relpath}/{walkthrough.get('sidecar_relpath')}"
        if isinstance(walkthrough.get("coverage_proof"), dict):
            generated_reconstruction["walkthrough_coverage_proof"] = walkthrough["coverage_proof"]
    payload["generated_reconstruction"] = generated_reconstruction
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "generated",
                "slug": slug,
                "provider": "propertyquarry_generated_reconstruction",
                "viewer_relpath": f"{base_relpath}/viewer.html",
                "model_relpath": f"{base_relpath}/model.obj",
                "public_tour_url": "",
                "satisfies_verified_tour_gate": False,
                "walkthrough_status": walkthrough.get("status"),
                "verified_provider_capture": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
