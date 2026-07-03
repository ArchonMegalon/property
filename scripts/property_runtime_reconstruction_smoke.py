#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_RENDER_CONTAINER = "propertyquarry-render-tools"


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def _generated_reconstruction_viewer_url(*, public_base_url: str, slug: str) -> str:
    normalized_base = str(public_base_url or "").strip().rstrip("/")
    normalized_slug = str(slug or "").strip().strip("/")
    if not normalized_base or not normalized_slug:
        return ""
    return f"{normalized_base}/tours/files/{urllib.parse.quote(normalized_slug, safe='')}/generated-reconstruction/viewer.html"


def _browser_check_generated_reconstruction_viewer(*, viewer_url: str) -> dict[str, object]:
    normalized_url = str(viewer_url or "").strip()
    if not normalized_url:
        return {"status": "skipped", "reason": "viewer_url_missing"}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local tool install
        return {"status": "blocked", "reason": "playwright_unavailable", "error": type(exc).__name__}

    threshold_failures: list[str] = []
    contexts: dict[str, object] = {}

    def _context_metrics(page) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return dict(
            page.evaluate(
                """async () => {
                    const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
                    const debug = window.__pqReconstructionDebug;
                    if (!debug || typeof debug.getRenderMetrics !== 'function') {
                        return { ready: false, reason: 'debug_hook_missing' };
                    }
                    const before = debug.getRenderMetrics();
                    const insideButton = document.querySelector('#view-inside');
                    const rect = insideButton ? insideButton.getBoundingClientRect() : null;
                    if (insideButton) {
                        insideButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                    }
                    await wait(700);
                    const after = debug.getRenderMetrics();
                    const overflow = Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth);
                    const controls = [...document.querySelectorAll('button,a')].map((el) => {
                        const r = el.getBoundingClientRect();
                        return {
                            text: String(el.textContent || '').trim(),
                            width: Number(r.width || 0),
                            height: Number(r.height || 0),
                            pointerEvents: getComputedStyle(el).pointerEvents,
                        };
                    });
                    return {
                        ready: Boolean(before?.ready && after?.ready),
                        before,
                        after,
                        overflow,
                        insideButtonRect: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null,
                        controls,
                    };
                }"""
            )
            or {}
        )

    def _validate_context(label: str, metrics: dict[str, object], *, mobile: bool) -> None:
        before = dict(metrics.get("before") or {}) if isinstance(metrics.get("before"), dict) else {}
        after = dict(metrics.get("after") or {}) if isinstance(metrics.get("after"), dict) else {}
        controls = list(metrics.get("controls") or []) if isinstance(metrics.get("controls"), list) else []
        camera_before = dict(before.get("cameraPosition") or {}) if isinstance(before.get("cameraPosition"), dict) else {}
        camera_after = dict(after.get("cameraPosition") or {}) if isinstance(after.get("cameraPosition"), dict) else {}
        if not metrics.get("ready"):
            threshold_failures.append(f"{label}:viewer_not_ready")
        if float(before.get("wallRectCount") or 0) < 20 or float(after.get("wallRectCount") or 0) < 20:
            threshold_failures.append(f"{label}:wall_rect_count_low")
        if float(before.get("wallMeshCount") or 0) < 20 or float(after.get("wallMeshCount") or 0) < 20:
            threshold_failures.append(f"{label}:wall_mesh_count_low")
        if float(before.get("visibleWallCount") or 0) < 8:
            threshold_failures.append(f"{label}:startup_visible_wall_count_low")
        if float(after.get("visibleWallCount") or 0) < 4:
            threshold_failures.append(f"{label}:inside_visible_wall_count_low")
        if float(before.get("sceneChildCount") or 0) < 4 or float(after.get("sceneChildCount") or 0) < 4:
            threshold_failures.append(f"{label}:scene_child_count_low")
        if float(before.get("renderCalls") or 0) < 10 or float(after.get("renderCalls") or 0) < 10:
            threshold_failures.append(f"{label}:render_calls_low")
        if float(before.get("renderTriangles") or 0) < 150 or float(after.get("renderTriangles") or 0) < 150:
            threshold_failures.append(f"{label}:render_triangles_low")
        if float(before.get("projectedCoveragePct") or 0) < (4 if mobile else 5):
            threshold_failures.append(f"{label}:projected_coverage_low")
        if float(before.get("maxProjectedWallPct") or 0) > (55 if mobile else 50):
            threshold_failures.append(f"{label}:startup_wall_projection_too_dominant")
        if int(float(metrics.get("overflow") or 0)) > 1:
            threshold_failures.append(f"{label}:horizontal_overflow")
        if mobile:
            too_small = [
                str(row.get("text") or "control")
                for row in controls
                if isinstance(row, dict)
                and (float(row.get("width") or 0) < 44 or float(row.get("height") or 0) < 44)
            ]
            if too_small:
                threshold_failures.append(f"{label}:control_target_too_small:{','.join(too_small[:4])}")
        if camera_before and camera_after and camera_before == camera_after:
            threshold_failures.append(f"{label}:inside_button_did_not_move_camera")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            for label, viewport, mobile in (
                ("desktop", {"width": 1366, "height": 900}, False),
                ("mobile", {"width": 390, "height": 844}, True),
            ):
                context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
                page = context.new_page()
                errors: list[str] = []
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(normalized_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function(
                    "() => !!document.querySelector('#viewport canvas') && !!window.__pqReconstructionDebug?.getRenderMetrics",
                    timeout=60_000,
                )
                page.wait_for_timeout(500)
                metrics = _context_metrics(page)
                metrics["errors"] = errors[:8]
                contexts[label] = metrics
                if errors:
                    threshold_failures.append(f"{label}:browser_errors")
                _validate_context(label, metrics, mobile=mobile)
                context.close()
            browser.close()
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "browser_render_exception",
            "viewer_url": normalized_url,
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
            "contexts": contexts,
        }

    return {
        "status": "pass" if not threshold_failures else "failed",
        "viewer_url": normalized_url,
        "failures": threshold_failures,
        "contexts": contexts,
    }


def build_runtime_reconstruction_receipt(
    *,
    container: str,
    slug: str,
    public_base_url: str = "",
    require_browser: bool = False,
    require_glb: bool = False,
) -> dict[str, object]:
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
d.line((320, 80, 320, 420), fill=(42, 36, 28), width=8)
d.line((620, 250, 1120, 250), fill=(42, 36, 28), width=8)
d.line((870, 250, 870, 720), fill=(42, 36, 28), width=8)
d.rectangle((118, 118, 282, 382), outline=(73, 108, 170), width=6)
d.rectangle((358, 118, 582, 382), outline=(148, 68, 48), width=6)
d.rectangle((666, 118, 826, 212), outline=(73, 108, 170), width=6)
d.rectangle((910, 296, 1082, 680), outline=(148, 68, 48), width=6)
d.rectangle((666, 466, 826, 680), outline=(73, 108, 170), width=6)
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
    required_path_keys = ("viewer", "obj", "mtl", "receipt", *(() if not require_glb else ("glb",)))
    required_paths_ok = all(bool((paths.get(key) or {}).get("exists")) for key in required_path_keys)
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
    glb_capability_ok = bool(glb_manifest_ok or not require_glb)
    viewer_url = _generated_reconstruction_viewer_url(public_base_url=public_base_url, slug=slug)
    browser_receipt: dict[str, object] = {}
    browser_ok = True
    if viewer_url:
        browser_receipt = _browser_check_generated_reconstruction_viewer(viewer_url=viewer_url)
        browser_ok = browser_receipt.get("status") == "pass"
    elif require_browser:
        browser_ok = False
        browser_receipt = {"status": "blocked", "reason": "public_base_url_missing"}
    status = (
        "pass"
        if required_paths_ok and honest_disclosure_ok and glb_capability_ok and browser_ok
        else "failed"
    )
    return {
        "status": status,
        "generated_at": started_at,
        "container": container,
        "slug": slug,
        "viewer_url": viewer_url,
        "duration_seconds": round(time.time() - datetime.fromisoformat(started_at).timestamp(), 3),
        "required_paths_ok": required_paths_ok,
        "glb_non_empty": glb_non_empty,
        "honest_disclosure_ok": honest_disclosure_ok,
        "glb_manifest_ok": glb_manifest_ok,
        "glb_required": bool(require_glb),
        "glb_capability_ok": glb_capability_ok,
        "browser_render_ok": browser_ok,
        "browser_render": browser_receipt,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the deployed PropertyQuarry runtime generated reconstruction path.")
    parser.add_argument("--container", default=os.getenv("PROPERTYQUARRY_RENDER_CONTAINER_NAME") or DEFAULT_RENDER_CONTAINER)
    parser.add_argument("--slug", default="runtime-reconstruction-smoke")
    parser.add_argument("--public-base-url", default=os.getenv("PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_PUBLIC_BASE_URL") or "")
    parser.add_argument("--require-browser", action="store_true")
    parser.add_argument("--require-glb", action="store_true")
    parser.add_argument("--write", default="_completion/tours/property-runtime-reconstruction-smoke-current.json")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    receipt = build_runtime_reconstruction_receipt(
        container=args.container,
        slug=args.slug,
        public_base_url=args.public_base_url,
        require_browser=bool(args.require_browser),
        require_glb=bool(args.require_glb),
    )
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
