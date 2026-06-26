#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
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
        normalized.save(target, quality=90)
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


def _viewer_html(*, manifest: dict[str, object]) -> str:
    width_m = manifest["room_dimensions_m"]["width"]
    depth_m = manifest["room_dimensions_m"]["depth"]
    height_m = manifest["room_dimensions_m"]["height"]
    photos = manifest.get("photos") if isinstance(manifest.get("photos"), list) else []
    photo_items = "\n".join(
        f'<img src="{row["relpath"]}" alt="Source photo {index}" loading="lazy">'
        for index, row in enumerate(photos, start=1)
        if isinstance(row, dict) and row.get("relpath")
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Generated PropertyQuarry Reconstruction</title>
  <style>
    :root {{ color-scheme: light; --ink:#181611; --muted:#70695c; --paper:#f7f3ea; --line:#dfd6c4; --gold:#b88a32; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: ui-serif, Georgia, serif; background:var(--paper); color:var(--ink); }}
    main {{ min-height:100vh; display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:24px; padding:24px; }}
    canvas {{ width:100%; height:min(72vh,720px); border:1px solid var(--line); border-radius:24px; background:linear-gradient(180deg,#fbf8f0,#ebe1cf); touch-action:none; }}
    aside {{ display:flex; flex-direction:column; gap:16px; }}
    .card {{ border:1px solid var(--line); border-radius:22px; background:rgba(255,255,255,.58); padding:18px; box-shadow:0 18px 50px rgba(70,52,28,.08); }}
    h1 {{ margin:0 0 8px; font-size:24px; line-height:1.05; letter-spacing:-.03em; }}
    p {{ margin:0; color:var(--muted); line-height:1.45; }}
    .disclosure {{ color:#7f1d1d; font-family:ui-sans-serif, system-ui, sans-serif; font-size:13px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; font-family:ui-sans-serif, system-ui, sans-serif; }}
    .metrics div {{ border:1px solid var(--line); border-radius:16px; padding:10px; }}
    .metrics b {{ display:block; font-size:18px; color:var(--ink); }}
    .photos {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }}
    .photos img, .floorplan {{ width:100%; border-radius:14px; border:1px solid var(--line); object-fit:cover; }}
    .photos img {{ aspect-ratio:1; }}
    .floorplan {{ aspect-ratio:4/3; background:white; }}
    a {{ color:var(--ink); text-decoration-thickness:1px; text-underline-offset:4px; }}
    @media (max-width: 800px) {{ main {{ display:block; padding:12px; }} aside {{ margin-top:12px; }} canvas {{ height:62vh; border-radius:18px; }} }}
  </style>
</head>
<body>
<main>
  <canvas id="scene" width="1400" height="900" aria-label="Generated 3D room model preview"></canvas>
  <aside>
    <section class="card">
      <h1>Generated reconstruction</h1>
      <p class="disclosure">{DISCLOSURE}</p>
    </section>
    <section class="card metrics" aria-label="Room dimensions">
      <div><b>{width_m}</b><span>m wide</span></div>
      <div><b>{depth_m}</b><span>m deep</span></div>
      <div><b>{height_m}</b><span>m high</span></div>
    </section>
    <section class="card">
      <p>Floorplan source</p>
      <img class="floorplan" src="{manifest["floorplan"]["relpath"]}" alt="Source floorplan">
    </section>
    <section class="card">
      <p>Source photos</p>
      <div class="photos">{photo_items}</div>
    </section>
    <section class="card">
      <p><a href="model.obj">Download OBJ</a> · <a href="reconstruction.json">Open receipt</a></p>
    </section>
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
  ctx.fillStyle='rgba(24,22,17,.72)'; ctx.font='28px Georgia'; ctx.fillText('drag to inspect generated room volume', 34, 52);
}}
canvas.addEventListener('pointerdown', e => {{ dragging=true; lastX=e.clientX; lastY=e.clientY; canvas.setPointerCapture(e.pointerId); }});
canvas.addEventListener('pointermove', e => {{ if(!dragging) return; yaw += (e.clientX-lastX)*0.008; pitch = Math.max(-.7, Math.min(.8, pitch+(e.clientY-lastY)*0.006)); lastX=e.clientX; lastY=e.clientY; draw(); }});
canvas.addEventListener('pointerup', () => dragging=false);
draw();
</script>
</body>
</html>
"""


def _write_walkthrough(target: Path, images: list[Path]) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "skipped", "reason": "ffmpeg_missing"}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="propertyquarry-reconstruction-") as tempdir:
        list_path = Path(tempdir) / "frames.txt"
        lines: list[str] = []
        for image in images:
            escaped = str(image).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
            lines.append("duration 2")
        escaped_last = str(images[-1]).replace("'", "'\\''")
        lines.append(f"file '{escaped_last}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-r",
                "30",
                "-movflags",
                "+faststart",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        return {"status": "failed", "reason": (result.stderr or "ffmpeg_failed")[-500:]}
    return {"status": "generated", "relpath": target.name, "sha256": _sha256(target), "size_bytes": target.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PropertyQuarry reconstruction from a floorplan image and photos.")
    parser.add_argument("--slug", required=True, help="Existing PropertyQuarry public tour slug.")
    parser.add_argument("--floorplan", default="", help="Floorplan image. PDF support is intentionally not implied here.")
    parser.add_argument("--photo", action="append", default=[], help="Source property photo. Can be provided multiple times.")
    parser.add_argument("--target-subdir", default="generated-reconstruction")
    parser.add_argument("--max-width-m", type=float, default=10.0)
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
        floorplan_target = output_dir / f"source-floorplan{floorplan_source.suffix.lower()}"
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
        target = output_dir / f"photo-{index:02d}{source.suffix.lower()}"
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
    source_images = [floorplan_target, *photo_paths]
    walkthrough = (
        {"status": "skipped", "reason": "skip_video_requested"}
        if args.skip_video
        else _write_walkthrough(output_dir / "generated-walkthrough.mp4", source_images)
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt: dict[str, object] = {
        "provider": "propertyquarry_generated_reconstruction",
        "generated_at": generated_at,
        "slug": slug,
        "disclosure": DISCLOSURE,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "method": "floorplan_aspect_room_volume_with_source_photo_reference_panels",
        "room_dimensions_m": {"width": width_m, "depth": depth_m, "height": height_m},
        "floorplan": floorplan_meta,
        "photos": photo_rows,
        "model": {
            "obj_relpath": "model.obj",
            "mtl_relpath": "model.mtl",
            "obj_sha256": _sha256(output_dir / "model.obj"),
            "mtl_sha256": _sha256(output_dir / "model.mtl"),
        },
        "viewer": {"relpath": "viewer.html"},
        "walkthrough": walkthrough,
    }
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
        "viewer_relpath": f"{base_relpath}/viewer.html",
        "model_relpath": f"{base_relpath}/model.obj",
        "manifest_relpath": f"{base_relpath}/reconstruction.json",
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "disclosure": DISCLOSURE,
    }
    if walkthrough.get("status") == "generated":
        generated_reconstruction["walkthrough_video_relpath"] = f"{base_relpath}/generated-walkthrough.mp4"
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
