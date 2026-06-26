#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def build_runtime_reconstruction_receipt(*, container: str, slug: str) -> dict[str, object]:
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if not shutil.which("docker"):
        return {"status": "blocked", "reason": "docker_missing", "generated_at": started_at}

    setup_script = f"""
set -eu
slug={slug!r}
bundle="/data/public_property_tours/$slug"
src="/tmp/propertyquarry-runtime-reconstruction-$slug"
rm -rf "$bundle" "$src"
mkdir -p "$bundle" "$src"
python - <<'PY'
import json
from pathlib import Path
from PIL import Image, ImageDraw
slug = {slug!r}
bundle = Path('/data/public_property_tours') / slug
src = Path('/tmp') / f'propertyquarry-runtime-reconstruction-{{slug}}'
(bundle / 'tour.json').write_text(json.dumps({{'slug': slug, 'display_title': 'Runtime reconstruction smoke'}}, indent=2), encoding='utf-8')
floor = Image.new('RGB', (1200, 800), color=(248, 244, 235))
d = ImageDraw.Draw(floor)
d.rectangle((80, 80, 1120, 720), outline=(42, 36, 28), width=12)
d.line((620, 80, 620, 720), fill=(42, 36, 28), width=8)
d.line((80, 420, 620, 420), fill=(42, 36, 28), width=8)
floor.save(src / 'floorplan.jpg', format='JPEG')
for name, color in [('living.jpg', (126, 108, 82)), ('kitchen.jpg', (86, 104, 112))]:
    img = Image.new('RGB', (900, 700), color=color)
    dd = ImageDraw.Draw(img)
    dd.rectangle((80, 100, 820, 620), outline=(255, 255, 255), width=8)
    img.save(src / name, format='JPEG')
PY
python /app/scripts/generate_property_reconstruction.py \
  --slug "$slug" \
  --floorplan "$src/floorplan.jpg" \
  --photo "$src/living.jpg" \
  --photo "$src/kitchen.jpg" \
  --skip-video
"""
    generated = _run(["docker", "exec", container, "sh", "-lc", setup_script], timeout=180)
    if generated.returncode != 0:
        return {
            "status": "failed",
            "generated_at": started_at,
            "container": container,
            "slug": slug,
            "reason": "runtime_reconstruction_command_failed",
            "returncode": generated.returncode,
            "stdout_tail": (generated.stdout or "")[-1000:],
            "stderr_tail": (generated.stderr or "")[-1000:],
        }

    inspect_script = f"""
set -eu
slug={slug!r}
base="/data/public_property_tours/$slug"
python - <<'PY'
import json
from pathlib import Path
slug = {slug!r}
base = Path('/data/public_property_tours') / slug
manifest = json.loads((base / 'tour.json').read_text(encoding='utf-8'))
receipt = json.loads((base / 'generated-reconstruction' / 'reconstruction.json').read_text(encoding='utf-8'))
paths = {{
  'viewer': base / 'generated-reconstruction' / 'viewer.html',
  'obj': base / 'generated-reconstruction' / 'model.obj',
  'mtl': base / 'generated-reconstruction' / 'model.mtl',
  'glb': base / 'generated-reconstruction' / 'model.glb',
  'receipt': base / 'generated-reconstruction' / 'reconstruction.json',
}}
print(json.dumps({{
  'manifest_generated_reconstruction': manifest.get('generated_reconstruction') or {{}},
  'receipt_provider': receipt.get('provider'),
  'verified_provider_capture': receipt.get('verified_provider_capture'),
  'satisfies_verified_tour_gate': receipt.get('satisfies_verified_tour_gate'),
  'glb_export_status': (receipt.get('model') or {{}}).get('glb_export', {{}}).get('status'),
  'paths': {{key: {{'exists': value.is_file(), 'size_bytes': value.stat().st_size if value.exists() else 0}} for key, value in paths.items()}},
}}, sort_keys=True))
PY
"""
    inspected = _run(["docker", "exec", container, "sh", "-lc", inspect_script], timeout=30)
    if inspected.returncode != 0:
        return {
            "status": "failed",
            "generated_at": started_at,
            "container": container,
            "slug": slug,
            "reason": "runtime_reconstruction_inspection_failed",
            "stdout_tail": (inspected.stdout or "")[-1000:],
            "stderr_tail": (inspected.stderr or "")[-1000:],
        }
    try:
        details = json.loads((inspected.stdout or "").strip().splitlines()[-1])
    except Exception as exc:
        return {
            "status": "failed",
            "generated_at": started_at,
            "container": container,
            "slug": slug,
            "reason": "runtime_reconstruction_inspection_unparseable",
            "error": type(exc).__name__,
            "stdout_tail": (inspected.stdout or "")[-1000:],
        }

    paths = details.get("paths") if isinstance(details.get("paths"), dict) else {}
    generated_reconstruction = (
        details.get("manifest_generated_reconstruction")
        if isinstance(details.get("manifest_generated_reconstruction"), dict)
        else {}
    )
    required_paths_ok = all(bool((paths.get(key) or {}).get("exists")) for key in ("viewer", "obj", "mtl", "glb", "receipt"))
    glb_non_empty = int((paths.get("glb") or {}).get("size_bytes") or 0) > 0
    honest_disclosure_ok = (
        details.get("receipt_provider") == "propertyquarry_generated_reconstruction"
        and details.get("verified_provider_capture") is False
        and details.get("satisfies_verified_tour_gate") is False
        and generated_reconstruction.get("verified_provider_capture") is False
        and generated_reconstruction.get("satisfies_verified_tour_gate") is False
    )
    glb_manifest_ok = (
        details.get("glb_export_status") == "generated"
        and generated_reconstruction.get("glb_export_status") == "generated"
        and str(generated_reconstruction.get("glb_model_relpath") or "").endswith("/model.glb")
    )
    status = "pass" if required_paths_ok and glb_non_empty and honest_disclosure_ok and glb_manifest_ok else "failed"
    return {
        "status": status,
        "generated_at": started_at,
        "container": container,
        "slug": slug,
        "duration_seconds": round(time.time() - datetime.fromisoformat(started_at).timestamp(), 3),
        "required_paths_ok": required_paths_ok,
        "glb_non_empty": glb_non_empty,
        "honest_disclosure_ok": honest_disclosure_ok,
        "glb_manifest_ok": glb_manifest_ok,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the deployed PropertyQuarry runtime generated reconstruction path.")
    parser.add_argument("--container", default="propertyquarry-api")
    parser.add_argument("--slug", default="runtime-reconstruction-smoke")
    parser.add_argument("--write", default="_completion/tours/property-runtime-reconstruction-smoke-current.json")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    receipt = build_runtime_reconstruction_receipt(container=args.container, slug=args.slug)
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if args.fail_on_error and receipt.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
