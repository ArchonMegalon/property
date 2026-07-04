#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
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


def _generated_reconstruction_canonical_url(*, public_base_url: str, slug: str) -> str:
    normalized_base = str(public_base_url or "").strip().rstrip("/")
    normalized_slug = str(slug or "").strip().strip("/")
    if not normalized_base or not normalized_slug:
        return ""
    return f"{normalized_base}/tours/{urllib.parse.quote(normalized_slug, safe='')}"


def _generated_reconstruction_model_url(*, public_base_url: str, slug: str) -> str:
    normalized_base = str(public_base_url or "").strip().rstrip("/")
    normalized_slug = str(slug or "").strip().strip("/")
    if not normalized_base or not normalized_slug:
        return ""
    return f"{normalized_base}/tours/files/{urllib.parse.quote(normalized_slug, safe='')}/generated-reconstruction/model.obj"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None

    def http_error_301(self, req, fp, code, msg, headers):  # type: ignore[no-untyped-def]
        return fp

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _http_probe(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "PropertyQuarry release gate"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read(65_536)
            return {
                "status_code": int(response.getcode() or 0),
                "location": str(response.headers.get("location") or ""),
                "body_excerpt": body.decode("utf-8", errors="replace")[:65_536],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(65_536)
        return {
            "status_code": int(exc.code or 0),
            "location": str(exc.headers.get("location") or ""),
            "body_excerpt": body.decode("utf-8", errors="replace")[:65_536],
        }
    except Exception as exc:
        return {"status_code": 0, "error": type(exc).__name__, "detail": str(exc)[:500]}


def _check_generated_reconstruction_public_contract(*, public_base_url: str, slug: str) -> dict[str, object]:
    viewer_url = _generated_reconstruction_viewer_url(public_base_url=public_base_url, slug=slug)
    canonical_url = _generated_reconstruction_canonical_url(public_base_url=public_base_url, slug=slug)
    model_url = _generated_reconstruction_model_url(public_base_url=public_base_url, slug=slug)
    if not viewer_url or not canonical_url or not model_url:
        return {"status": "skipped", "reason": "public_base_url_missing"}

    viewer = _http_probe(viewer_url)
    canonical = _http_probe(canonical_url)
    model = _http_probe(model_url)
    expected_canonical_path = urllib.parse.urlparse(canonical_url).path
    failures: list[str] = []
    viewer_location = str(viewer.get("location") or "")
    if int(viewer.get("status_code") or 0) not in {302, 307}:
        failures.append("viewer_not_redirected")
    if viewer_location and urllib.parse.urlparse(viewer_location).path != expected_canonical_path:
        failures.append("viewer_redirect_target_wrong")
    if int(canonical.get("status_code") or 0) != 404:
        failures.append("canonical_not_unavailable")
    if "older generated layout preview" not in str(canonical.get("body_excerpt") or ""):
        failures.append("canonical_missing_honest_message")
    if "generated-reconstruction/viewer.html" in str(canonical.get("body_excerpt") or ""):
        failures.append("canonical_leaks_fake_viewer_url")
    if int(model.get("status_code") or 0) != 410:
        failures.append("model_not_gone")
    return {
        "status": "pass" if not failures else "failed",
        "failures": failures,
        "viewer_url": viewer_url,
        "canonical_url": canonical_url,
        "model_url": model_url,
        "viewer": viewer,
        "canonical": canonical,
        "model": model,
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
    public_contract_receipt: dict[str, object] = {}
    public_contract_ok = True
    if public_base_url:
        public_contract_receipt = _check_generated_reconstruction_public_contract(
            public_base_url=public_base_url,
            slug=slug,
        )
        public_contract_ok = public_contract_receipt.get("status") == "pass"
    elif require_browser:
        public_contract_ok = False
        public_contract_receipt = {"status": "blocked", "reason": "public_base_url_missing"}
    status = (
        "pass"
        if required_paths_ok and honest_disclosure_ok and glb_capability_ok and public_contract_ok
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
        "public_route_contract_ok": public_contract_ok,
        "public_route_contract": public_contract_receipt,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the deployed PropertyQuarry runtime generated reconstruction path.")
    parser.add_argument("--container", default=os.getenv("PROPERTYQUARRY_RENDER_CONTAINER_NAME") or DEFAULT_RENDER_CONTAINER)
    parser.add_argument("--slug", default="runtime-reconstruction-smoke")
    parser.add_argument("--public-base-url", default=os.getenv("PROPERTYQUARRY_RUNTIME_RECONSTRUCTION_PUBLIC_BASE_URL") or "")
    parser.add_argument(
        "--require-browser",
        action="store_true",
        help="Deprecated name; now requires the public generated-reconstruction rejection contract.",
    )
    parser.add_argument(
        "--require-public-contract",
        action="store_true",
        help="Require public routes to reject generated reconstructions as tours.",
    )
    parser.add_argument("--require-glb", action="store_true")
    parser.add_argument("--write", default="_completion/tours/property-runtime-reconstruction-smoke-current.json")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    receipt = build_runtime_reconstruction_receipt(
        container=args.container,
        slug=args.slug,
        public_base_url=args.public_base_url,
        require_browser=bool(args.require_browser or args.require_public_contract),
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
