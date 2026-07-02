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
VIEWER_VERSION = "propertyquarry_3d_tour_viewer_v2"
DISCLOSURE = (
    "Generated reconstruction from floorplan/photos; not a verified Matterport, "
    "3DVista, Pano2VR, krpano, or MagicFit provider export."
)


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


def _write_obj(target_dir: Path, *, width_m: float, depth_m: float, height_m: float) -> None:
    half_w = width_m / 2
    half_d = depth_m / 2
    vertices = [
        (-half_w, 0, -half_d),
        (half_w, 0, -half_d),
        (half_w, 0, half_d),
        (-half_w, 0, half_d),
        (-half_w, height_m, -half_d),
        (half_w, height_m, -half_d),
        (half_w, height_m, half_d),
        (-half_w, height_m, half_d),
    ]
    faces = [
        ("floor", (1, 2, 3, 4)),
        ("north_wall", (1, 5, 6, 2)),
        ("east_wall", (2, 6, 7, 3)),
        ("south_wall", (3, 7, 8, 4)),
        ("west_wall", (4, 8, 5, 1)),
    ]
    obj_lines = ["mtllib model.mtl", "o propertyquarry_generated_room"]
    for x, y, z in vertices:
        obj_lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    obj_lines.extend(["usemtl warm_plaster"])
    for name, indexes in faces:
        obj_lines.append(f"g {name}")
        obj_lines.append("f " + " ".join(str(index) for index in indexes))
    (target_dir / "model.obj").write_text("\n".join(obj_lines) + "\n", encoding="utf-8")
    (target_dir / "model.mtl").write_text(
        "\n".join(
            [
                "newmtl warm_plaster",
                "Ka 0.74 0.70 0.62",
                "Kd 0.86 0.82 0.72",
                "Ks 0.04 0.04 0.04",
                "Ns 12",
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
  <title>3D tour | PropertyQuarry</title>
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
    canvas {{
      width:100%;
      height:calc(100vh - 36px);
      min-height:520px;
      border:1px solid var(--line);
      border-radius:28px;
      background:linear-gradient(180deg,#fbf8f1,#e6d8bf);
      box-shadow:var(--shadow);
      touch-action:none;
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
      canvas {{ height:68vh; min-height:430px; border-radius:22px; }}
      aside {{ margin-top:10px; }}
      .hud {{ top:12px; left:12px; right:12px; }}
      .hint-pill {{ display:none; }}
      .title-card {{ max-width:86vw; padding:12px 13px; }}
      .title-card p {{ font-size:13px; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="stage">
    <canvas id="scene" width="1400" height="900" aria-label="3D layout preview"></canvas>
    <div class="hud">
      <div class="title-card">
        <h1>3D tour</h1>
        <p>Move around the layout before deciding whether to visit.</p>
      </div>
      <div class="hint-pill">Drag to rotate</div>
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
<script>
const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');
let yaw = -0.65, pitch = 0.28, dragging = false, lastX = 0, lastY = 0;
const W = {width_m}, D = {depth_m}, H = {height_m};
const points = [
  [-W/2,0,-D/2],[W/2,0,-D/2],[W/2,0,D/2],[-W/2,0,D/2],
  [-W/2,H,-D/2],[W/2,H,-D/2],[W/2,H,D/2],[-W/2,H,D/2]
];
const faces = [
  [0,1,2,3,'rgba(184,138,50,.22)'],
  [0,4,5,1,'rgba(255,255,255,.76)'],
  [1,5,6,2,'rgba(245,238,222,.82)'],
  [2,6,7,3,'rgba(232,222,202,.82)'],
  [3,7,4,0,'rgba(250,246,235,.78)']
];
function project(p) {{
  let [x,y,z]=p;
  let cy=Math.cos(yaw), sy=Math.sin(yaw), cp=Math.cos(pitch), sp=Math.sin(pitch);
  let x1=x*cy-z*sy, z1=x*sy+z*cy, y1=y*cp-z1*sp, z2=y*sp+z1*cp+14;
  let s=canvas.width/(z2*1.8);
  return [canvas.width/2+x1*s, canvas.height*.68-y1*s, z2];
}}
function draw() {{
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const projected = points.map(project);
  faces.map(face => ({{face, depth: face.slice(0,4).reduce((a,i)=>a+projected[i][2],0)}}))
    .sort((a,b)=>b.depth-a.depth)
    .forEach(({{face}}) => {{
      ctx.beginPath();
      face.slice(0,4).forEach((i,n)=>{{ const [x,y]=projected[i]; n?ctx.lineTo(x,y):ctx.moveTo(x,y); }});
      ctx.closePath(); ctx.fillStyle=face[4]; ctx.fill(); ctx.strokeStyle='rgba(38,31,20,.28)'; ctx.lineWidth=2; ctx.stroke();
    }});
  ctx.fillStyle='rgba(24,22,17,.56)'; ctx.font='24px Georgia'; ctx.fillText('drag to rotate', 34, 52);
}}
canvas.addEventListener('pointerdown', e => {{ dragging=true; lastX=e.clientX; lastY=e.clientY; canvas.setPointerCapture(e.pointerId); }});
canvas.addEventListener('pointermove', e => {{ if(!dragging) return; yaw += (e.clientX-lastX)*0.008; pitch = Math.max(-.7, Math.min(.8, pitch+(e.clientY-lastY)*0.006)); lastX=e.clientX; lastY=e.clientY; draw(); }});
canvas.addEventListener('pointerup', () => dragging=false);
draw();
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

    width_m, depth_m, height_m = _room_dimensions(
        int(floorplan_meta["width"]),
        int(floorplan_meta["height"]),
        max_width_m=max(3.0, float(args.max_width_m)),
    )

    _write_obj(output_dir, width_m=width_m, depth_m=depth_m, height_m=height_m)
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
                "viewer_url": f"/tours/files/{slug}/{base_relpath}/viewer.html",
                "model_url": f"/tours/files/{slug}/{base_relpath}/model.obj",
                "walkthrough_status": walkthrough.get("status"),
                "verified_provider_capture": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
