#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


PROVIDER_MODES = ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
PUBLIC_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}


def _tour_root() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/property/state/public_property_tours").expanduser().resolve()


def _safe_asset_relpath(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        return ""
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        return ""
    return "/".join(parts)


def _safe_http_url(value: object, *, allowed_hosts: Iterable[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed_host = str(allowed or "").strip().lower().rstrip(".")
        if host == allowed_host or host.endswith(f".{allowed_host}"):
            return raw
    return ""


def _pano2vr_entry_relpath(payload: dict[str, object]) -> str:
    for key in ("pano2vr_entry_relpath", "pano2vr_export_entry_relpath"):
        relpath = _safe_asset_relpath(payload.get(key))
        if relpath:
            return relpath
    return ""


def _three_d_vista_entry_relpath(payload: dict[str, object]) -> str:
    for key in ("three_d_vista_entry_relpath", "threedvista_entry_relpath", "3dvista_entry_relpath"):
        relpath = _safe_asset_relpath(payload.get(key))
        if relpath:
            return relpath
    return ""


def _magicfit_video_relpath(payload: dict[str, object]) -> str:
    for key in ("video_relpath", "flythrough_video_relpath", "magicfit_video_relpath"):
        relpath = _safe_asset_relpath(payload.get(key))
        if relpath and PurePosixPath(relpath).suffix.lower() in PUBLIC_VIDEO_EXTENSIONS:
            return relpath
    return ""


def _magicfit_video_url(payload: dict[str, object]) -> str:
    provider = str(
        payload.get("video_provider")
        or payload.get("video_provider_key")
        or payload.get("video_render_provider")
        or ""
    ).strip().lower()
    if provider != "magicfit":
        return ""
    return _safe_http_url(payload.get("video_url"), allowed_hosts=("propertyquarry.com", "myexternalbrain.com"))


def _file_exists(bundle_dir: Path, relpath: str) -> bool:
    if not relpath:
        return False
    candidate = (bundle_dir / relpath).resolve()
    return bundle_dir.resolve() in candidate.parents and candidate.is_file()


def _control_candidates(*, slug: str, bundle_dir: Path, payload: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    matterport_url = ""
    for key in ("matterport_url", "source_virtual_tour_url", "crezlo_public_url"):
        matterport_url = _safe_http_url(payload.get(key), allowed_hosts=("matterport.com",))
        if matterport_url:
            break
    if matterport_url:
        rows.append(
            {
                "provider": "matterport",
                "status": "ready",
                "control_path": f"/tours/{slug}/control/matterport",
                "evidence": "allowlisted_matterport_url",
            }
        )

    three_d_vista_url = ""
    for key in ("three_d_vista_url", "threedvista_url", "3dvista_url", "source_virtual_tour_url", "crezlo_public_url"):
        three_d_vista_url = _safe_http_url(payload.get(key), allowed_hosts=("3dvista.com",))
        if three_d_vista_url:
            break
    three_d_vista_entry = _three_d_vista_entry_relpath(payload)
    if three_d_vista_url or _file_exists(bundle_dir, three_d_vista_entry):
        rows.append(
            {
                "provider": "3dvista",
                "status": "ready",
                "control_path": f"/tours/{slug}/control/3dvista",
                "evidence": "allowlisted_3dvista_url" if three_d_vista_url else "local_3dvista_export_entry",
            }
        )

    pano2vr_entry = _pano2vr_entry_relpath(payload)
    if _file_exists(bundle_dir, pano2vr_entry):
        rows.append(
            {
                "provider": "pano2vr",
                "status": "ready",
                "control_path": f"/tours/{slug}/control/pano2vr",
                "evidence": "local_pano2vr_export_entry",
            }
        )

    if os.getenv("KRPANO_LICENSE_DOMAIN") and os.getenv("KRPANO_LICENSE_KEY") and isinstance(payload.get("walkable_scene"), dict):
        rows.append(
            {
                "provider": "krpano",
                "status": "ready",
                "control_path": f"/tours/{slug}/control/krpano",
                "evidence": "licensed_krpano_walkable_scene",
            }
        )

    magicfit_relpath = _magicfit_video_relpath(payload)
    magicfit_url = _magicfit_video_url(payload)
    if magicfit_url or _file_exists(bundle_dir, magicfit_relpath):
        rows.append(
            {
                "provider": "magicfit",
                "status": "ready",
                "control_path": f"/tours/files/{slug}/{magicfit_relpath}" if magicfit_relpath else "",
                "evidence": "local_magicfit_video" if magicfit_relpath else "allowlisted_magicfit_video_url",
            }
        )
    return rows


def _probe_url(url: str, *, timeout_seconds: float) -> dict[str, object]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "PropertyQuarry-tour-control-verifier/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(80_000).decode("utf-8", errors="replace")
            return {
                "http_status": int(getattr(response, "status", 0) or 0),
                "body_markers": {
                    "matterport": "Matterport Control" in body,
                    "3dvista": "3DVista Control" in body,
                    "pano2vr": "Pano2VR Control" in body,
                    "krpano": "krpano" in body and "krpano-license" in body,
                },
            }
    except urllib.error.HTTPError as exc:
        return {"http_status": int(exc.code), "error": str(exc.reason or exc)}
    except Exception as exc:
        return {"http_status": 0, "error": f"{type(exc).__name__}: {exc}"}


def build_property_tour_control_receipt(
    *,
    tour_root: Path | None = None,
    base_url: str = "",
    live_probe: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    root = (tour_root or _tour_root()).expanduser().resolve()
    manifests = sorted(root.glob("*/tour.json")) if root.is_dir() else []
    tours: list[dict[str, object]] = []
    provider_counts = {provider: 0 for provider in PROVIDER_MODES}
    failed_probes = 0
    for manifest_path in manifests:
        bundle_dir = manifest_path.parent.resolve()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            tours.append({"slug": manifest_path.parent.name, "status": "invalid_manifest", "error": f"{type(exc).__name__}: {exc}"})
            failed_probes += 1
            continue
        if not isinstance(payload, dict):
            tours.append({"slug": manifest_path.parent.name, "status": "invalid_manifest"})
            failed_probes += 1
            continue
        slug = str(payload.get("slug") or manifest_path.parent.name).strip()
        controls = _control_candidates(slug=slug, bundle_dir=bundle_dir, payload=payload)
        for control in controls:
            provider = str(control.get("provider") or "").strip().lower()
            if provider in provider_counts:
                provider_counts[provider] += 1
            if live_probe and base_url and control.get("control_path"):
                probe_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", str(control["control_path"]).lstrip("/"))
                probe = _probe_url(probe_url, timeout_seconds=timeout_seconds)
                control["probe"] = probe
                if int(probe.get("http_status") or 0) != 200:
                    control["status"] = "probe_failed"
                    failed_probes += 1
        tours.append(
            {
                "slug": slug,
                "title": str(payload.get("display_title") or payload.get("title") or slug).strip()[:160],
                "status": "ready" if controls else "blocked_missing_verified_controls",
                "controls": controls,
            }
        )
    ready_provider_modes = sorted(provider for provider, count in provider_counts.items() if count > 0)
    status = (
        "blocked_no_tour_manifests"
        if not manifests
        else "fail"
        if failed_probes
        else "pass"
        if ready_provider_modes
        else "blocked_missing_verified_controls"
    )
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "tour_root": str(root),
        "tour_count": len(manifests),
        "ready_tour_count": sum(1 for tour in tours if tour.get("status") == "ready"),
        "provider_counts": provider_counts,
        "ready_provider_modes": ready_provider_modes,
        "required_provider_modes": list(PROVIDER_MODES),
        "missing_provider_modes": [provider for provider in PROVIDER_MODES if provider not in ready_provider_modes],
        "live_probe": bool(live_probe),
        "base_url": base_url if live_probe else "",
        "tours": tours,
        "notes": [
            "Matterport, 3DVista, Pano2VR, and krpano are ready only when a hosted control route can be justified from manifest evidence.",
            "MagicFit is ready only when the manifest points to a local public video asset or an allowlisted PropertyQuarry-hosted video URL with provider=magicfit.",
            "The receipt intentionally omits raw external provider URLs and private listing/source fields.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PropertyQuarry hosted 3D tour and walkthrough control readiness.")
    parser.add_argument("--tour-root", default="", help="Tour root. Defaults to EA_PUBLIC_TOUR_DIR or state/public_property_tours.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_TOUR_CONTROL_BASE_URL") or "http://localhost:8097")
    parser.add_argument("--live-probe", action="store_true", help="Probe ready control paths over HTTP.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--write", default="", help="Optional JSON receipt path.")
    args = parser.parse_args()
    receipt = build_property_tour_control_receipt(
        tour_root=Path(args.tour_root) if str(args.tour_root or "").strip() else None,
        base_url=str(args.base_url or "").strip(),
        live_probe=bool(args.live_probe),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if str(receipt.get("status") or "").startswith(("pass", "blocked")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
