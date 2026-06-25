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
    if not _magicfit_provider_declared(payload):
        return ""
    return _safe_http_url(payload.get("video_url"), allowed_hosts=("propertyquarry.com", "myexternalbrain.com"))


def _magicfit_provider_declared(payload: dict[str, object]) -> bool:
    provider = str(
        payload.get("video_provider")
        or payload.get("video_provider_key")
        or payload.get("video_render_provider")
        or ""
    ).strip().lower()
    return provider == "magicfit"


def _file_exists(bundle_dir: Path, relpath: str) -> bool:
    if not relpath:
        return False
    candidate = (bundle_dir / relpath).resolve()
    return bundle_dir.resolve() in candidate.parents and candidate.is_file()


def _local_html_asset_has_marker(bundle_dir: Path, relpath: str, *, markers: Iterable[str]) -> bool:
    if not relpath:
        return False
    candidate = (bundle_dir / relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.is_file():
        return False
    if PurePosixPath(relpath).suffix.lower() not in {".html", ".htm"}:
        return False
    try:
        body = candidate.read_text(encoding="utf-8", errors="replace")[:200_000].lower()
    except OSError:
        return False
    return any(str(marker or "").strip().lower() in body for marker in markers if str(marker or "").strip())


def _local_video_asset_is_playable(bundle_dir: Path, relpath: str) -> bool:
    if not relpath:
        return False
    candidate = (bundle_dir / relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.is_file():
        return False
    suffix = PurePosixPath(relpath).suffix.lower()
    try:
        header = candidate.read_bytes()[:64]
    except OSError:
        return False
    if len(header) < 12:
        return False
    if suffix in {".mp4", ".m4v", ".mov"}:
        return b"ftyp" in header[:32]
    if suffix == ".webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    return False


def _load_provider_receipt(bundle_dir: Path) -> dict[str, object]:
    receipt_path = bundle_dir / "tour.private.json"
    if not receipt_path.is_file():
        return {}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(receipt, dict):
        return {}
    allowed_keys = {
        "crezlo_public_url",
        "source_virtual_tour_url",
        "source_virtual_tour_origin",
        "three_d_vista_url",
        "matterport_url",
    }
    return {key: receipt.get(key) for key in allowed_keys if str(receipt.get(key) or "").strip()}


def _payload_with_private_provider_receipt(bundle_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    receipt = _load_provider_receipt(bundle_dir)
    if not receipt:
        return payload
    return {**payload, **receipt}


def _provider_missing_evidence(bundle_dir: Path, payload: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    matterport_candidate = any(
        str(payload.get(key) or "").strip()
        for key in ("matterport_url", "source_virtual_tour_url", "crezlo_public_url")
    )
    if matterport_candidate:
        reason = "matterport_url_not_allowlisted_or_invalid"
        action = "replace with a public Matterport URL on my.matterport.com or matterport.com"
    else:
        reason = "missing_matterport_url"
        action = "add matterport_url or source_virtual_tour_url from a real Matterport model"
    if not any(
        _safe_http_url(payload.get(key), allowed_hosts=("matterport.com",))
        for key in ("matterport_url", "source_virtual_tour_url", "crezlo_public_url")
    ):
        rows.append({"provider": "matterport", "reason": reason, "action": action})

    three_d_vista_entry = _three_d_vista_entry_relpath(payload)
    three_d_vista_url_ready = any(
        _safe_http_url(payload.get(key), allowed_hosts=("3dvista.com",))
        for key in ("three_d_vista_url", "threedvista_url", "3dvista_url", "source_virtual_tour_url", "crezlo_public_url")
    )
    three_d_vista_entry_ready = _local_html_asset_has_marker(
        bundle_dir,
        three_d_vista_entry,
        markers=("3dvista", "tdvplayer", "tdvplayerapi", "tourviewer", "panorama"),
    )
    if not (three_d_vista_url_ready or three_d_vista_entry_ready):
        if three_d_vista_entry:
            reason = "3dvista_entry_missing_or_not_verified"
            action = "import a real 3DVista export whose entry HTML contains 3DVista runtime markers"
        else:
            reason = "missing_3dvista_export"
            action = "run import_3dvista_export.py with a verified 3DVista export or add an allowlisted 3dvista.com URL"
        rows.append({"provider": "3dvista", "reason": reason, "action": action})

    pano2vr_entry = _pano2vr_entry_relpath(payload)
    pano2vr_entry_ready = _local_html_asset_has_marker(
        bundle_dir,
        pano2vr_entry,
        markers=("pano2vr", "ggpkg", "ggskin", "pano.xml", "tour.js"),
    )
    if not pano2vr_entry_ready:
        if pano2vr_entry:
            reason = "pano2vr_entry_missing_or_not_verified"
            action = "import a real Pano2VR export whose entry HTML contains Pano2VR runtime markers"
        else:
            reason = "missing_pano2vr_export"
            action = "run import_pano2vr_export.py with a verified Pano2VR export"
        rows.append({"provider": "pano2vr", "reason": reason, "action": action})

    if not (os.getenv("KRPANO_LICENSE_DOMAIN") and os.getenv("KRPANO_LICENSE_KEY") and isinstance(payload.get("walkable_scene"), dict)):
        if not isinstance(payload.get("walkable_scene"), dict):
            reason = "missing_walkable_scene"
            action = "generate or import a real walkable_scene before enabling the licensed krpano control"
        else:
            reason = "missing_krpano_license_environment"
            action = "set KRPANO_LICENSE_DOMAIN and KRPANO_LICENSE_KEY for the property runtime"
        rows.append({"provider": "krpano", "reason": reason, "action": action})

    magicfit_relpath = _magicfit_video_relpath(payload)
    magicfit_url = _magicfit_video_url(payload)
    if not (magicfit_url or (_magicfit_provider_declared(payload) and _local_video_asset_is_playable(bundle_dir, magicfit_relpath))):
        provider = str(
            payload.get("video_provider")
            or payload.get("video_provider_key")
            or payload.get("video_render_provider")
            or ""
        ).strip().lower()
        if provider and provider != "magicfit":
            reason = "walkthrough_provider_not_magicfit"
            action = "render and import a MagicFit walkthrough with provider=magicfit"
        elif magicfit_relpath:
            reason = "magicfit_video_missing_or_unplayable"
            action = "run import_magicfit_walkthrough.py with a receipt-backed playable MP4/M4V/MOV/WebM"
        else:
            reason = "missing_magicfit_walkthrough"
            action = "render and import a receipt-backed playable MagicFit walkthrough"
        rows.append({"provider": "magicfit", "reason": reason, "action": action})

    return rows


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
    three_d_vista_entry_ready = _local_html_asset_has_marker(
        bundle_dir,
        three_d_vista_entry,
        markers=("3dvista", "tdvplayer", "tdvplayerapi", "tourviewer", "panorama"),
    )
    if three_d_vista_url or three_d_vista_entry_ready:
        rows.append(
            {
                "provider": "3dvista",
                "status": "ready",
                "control_path": f"/tours/{slug}/control/3dvista",
                "evidence": "allowlisted_3dvista_url" if three_d_vista_url else "local_3dvista_export_entry",
            }
        )

    pano2vr_entry = _pano2vr_entry_relpath(payload)
    pano2vr_entry_ready = _local_html_asset_has_marker(
        bundle_dir,
        pano2vr_entry,
        markers=("pano2vr", "ggpkg", "ggskin", "pano.xml", "tour.js"),
    )
    if pano2vr_entry_ready:
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
    if magicfit_url or (_magicfit_provider_declared(payload) and _local_video_asset_is_playable(bundle_dir, magicfit_relpath)):
        rows.append(
            {
                "provider": "magicfit",
                "status": "ready",
                "control_path": f"/tours/files/{slug}/{magicfit_relpath}" if magicfit_relpath else "",
                "evidence": "local_magicfit_playable_video" if magicfit_relpath else "allowlisted_magicfit_video_url",
            }
        )
    return rows


def _blocked_control_reason(payload: dict[str, object]) -> str:
    scene_strategy = str(payload.get("scene_strategy") or "").strip().lower()
    creation_mode = str(payload.get("creation_mode") or "").strip().lower()
    if scene_strategy == "photo_gallery_hosted" or creation_mode == "hosted_photo_gallery_tour":
        return "gallery_only_not_3d"
    if scene_strategy == "pure_360_cube":
        return "generated_cube_not_verified_3d"
    if creation_mode in {"hosted_listing_fallback", "generated_listing_summary"}:
        return "listing_summary_not_verified_3d"
    return "missing_verified_provider_control"


def _probe_url(url: str, *, timeout_seconds: float, provider: str = "") -> dict[str, object]:
    normalized_provider = str(provider or "").strip().lower()
    request_headers = {"User-Agent": "PropertyQuarry-tour-control-verifier/1.0"}
    if normalized_provider == "magicfit":
        request_headers["Accept"] = "video/mp4,video/webm,video/*;q=0.9,*/*;q=0.1"
    request = urllib.request.Request(url, method="GET", headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if normalized_provider == "magicfit":
                content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                sample = response.read(64)
                suffix = PurePosixPath(urllib.parse.urlparse(url).path).suffix.lower()
                signature_ok = (
                    (suffix in {".mp4", ".m4v", ".mov"} and b"ftyp" in sample[:32])
                    or (suffix == ".webm" and sample.startswith(b"\x1aE\xdf\xa3"))
                )
                return {
                    "http_status": int(getattr(response, "status", 0) or 0),
                    "content_type": content_type,
                    "playback_markers": {
                        "video_content_type": content_type.startswith("video/"),
                        "video_signature": signature_ok,
                    },
                }
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
    action_counts = {provider: 0 for provider in PROVIDER_MODES}
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
        payload = _payload_with_private_provider_receipt(bundle_dir, payload)
        slug = str(payload.get("slug") or manifest_path.parent.name).strip()
        controls = _control_candidates(slug=slug, bundle_dir=bundle_dir, payload=payload)
        for control in controls:
            provider = str(control.get("provider") or "").strip().lower()
            if provider in provider_counts:
                provider_counts[provider] += 1
            if live_probe and base_url and control.get("control_path"):
                probe_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", str(control["control_path"]).lstrip("/"))
                probe = _probe_url(
                    probe_url,
                    timeout_seconds=timeout_seconds,
                    provider=str(control.get("provider") or ""),
                )
                control["probe"] = probe
                playback_markers = dict(probe.get("playback_markers") or {})
                playback_failed = bool(playback_markers) and not all(bool(value) for value in playback_markers.values())
                if int(probe.get("http_status") or 0) != 200 or playback_failed:
                    control["status"] = "probe_failed"
                    failed_probes += 1
        missing_evidence = [] if controls else _provider_missing_evidence(bundle_dir, payload)
        for row in missing_evidence:
            provider = str(row.get("provider") or "").strip().lower()
            if provider in action_counts:
                action_counts[provider] += 1
        tours.append(
            {
                "slug": slug,
                "title": str(payload.get("display_title") or payload.get("title") or slug).strip()[:160],
                "status": "ready" if controls else "blocked_missing_verified_controls",
                "blocked_reason": "" if controls else _blocked_control_reason(payload),
                "controls": controls,
                "missing_evidence": missing_evidence,
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
        "next_required_actions": [
            {
                "provider": provider,
                "blocked_tour_count": action_counts[provider],
                "action": {
                    "matterport": "add a verified Matterport model URL to at least one hosted tour manifest",
                    "3dvista": "import a verified 3DVista export or add an allowlisted 3dvista.com tour URL",
                    "pano2vr": "import a verified Pano2VR export",
                    "krpano": "provide a real walkable_scene and krpano license environment",
                    "magicfit": "import a receipt-backed playable MagicFit walkthrough video",
                }[provider],
            }
            for provider in PROVIDER_MODES
            if action_counts[provider] > 0
        ],
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
