#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


PROVIDER_MODES = ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
PUBLIC_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}
PANORAMA_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
TEXT_RUNTIME_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".json", ".xml"}
MAX_MARKER_SCAN_BYTES = 1_000_000
MAX_MARKER_SCAN_FILES = 240
KRPANO_FORBIDDEN_SCENE_STRATEGIES = {"generated_listing_summary", "photo_gallery_hosted", "floorplan_hosted", "pure_360_cube"}
KRPANO_FORBIDDEN_CREATION_MODES = {"hosted_listing_fallback", "hosted_photo_gallery_tour"}
EQUIRECTANGULAR_MIN_RATIO = 1.9
EQUIRECTANGULAR_MAX_RATIO = 2.1
CLI_ENV_KEYS = {"KRPANO_LICENSE_DOMAIN", "KRPANO_LICENSE_KEY"}


def _tour_root() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/property/state/public_property_tours").expanduser().resolve()


def _load_cli_env_defaults() -> None:
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for env_path in candidate_paths:
        if not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key not in CLI_ENV_KEYS or os.getenv(key):
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
        break


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


def _has_key(payload: dict[str, object], *keys: str) -> bool:
    return any(key in payload for key in keys)


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
    return _local_asset_path(bundle_dir, relpath) is not None


def _local_asset_path(bundle_dir: Path, relpath: str) -> Path | None:
    if not relpath:
        return None
    candidate = (bundle_dir / relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _local_image_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return (0, 0)


def _local_equirectangular_image_ready(bundle_dir: Path, relpath: str) -> bool:
    if not relpath or PurePosixPath(relpath).suffix.lower() not in PANORAMA_IMAGE_EXTENSIONS:
        return False
    candidate = _local_asset_path(bundle_dir, relpath)
    if candidate is None:
        return False
    width, height = _local_image_dimensions(candidate)
    if width < 1024 or height < 512:
        return False
    ratio = width / height if height else 0
    return EQUIRECTANGULAR_MIN_RATIO <= ratio <= EQUIRECTANGULAR_MAX_RATIO


def _local_cube_face_ready(bundle_dir: Path, relpath: str) -> bool:
    if not relpath or PurePosixPath(relpath).suffix.lower() not in PANORAMA_IMAGE_EXTENSIONS:
        return False
    candidate = _local_asset_path(bundle_dir, relpath)
    if candidate is None:
        return False
    width, height = _local_image_dimensions(candidate)
    if width < 512 or height < 512:
        return False
    ratio = width / height if height else 0
    return 0.9 <= ratio <= 1.1


def _walkable_scene_has_real_360_asset(bundle_dir: Path, payload: dict[str, object]) -> bool:
    scene_strategy = str(payload.get("scene_strategy") or "").strip().lower()
    creation_mode = str(payload.get("creation_mode") or "").strip().lower()
    if scene_strategy in KRPANO_FORBIDDEN_SCENE_STRATEGIES or creation_mode in KRPANO_FORBIDDEN_CREATION_MODES:
        return False
    walkable_scene = payload.get("walkable_scene")
    if not isinstance(walkable_scene, dict) or not walkable_scene:
        return False
    projection = str(walkable_scene.get("projection") or walkable_scene.get("type") or "").strip().lower()
    if projection and projection not in {"equirectangular", "panorama", "cubemap", "cube"}:
        return False
    for key in ("panorama_relpath", "equirect_relpath", "image_relpath", "asset_relpath"):
        relpath = _safe_asset_relpath(walkable_scene.get(key))
        if _local_equirectangular_image_ready(bundle_dir, relpath):
            return True
    cube_faces = walkable_scene.get("cube_faces")
    if isinstance(cube_faces, dict):
        values = list(cube_faces.values())
    elif isinstance(cube_faces, list):
        values = cube_faces
    else:
        values = []
    face_relpaths = [_safe_asset_relpath(value) for value in values]
    valid_faces = [
        relpath
        for relpath in face_relpaths
        if _local_cube_face_ready(bundle_dir, relpath)
    ]
    return len(valid_faces) >= 6


def _ffprobe_video_markers(target: str | Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"ffprobe_available": False}
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,duration:format=duration",
                "-of",
                "json",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {"ffprobe_available": True, "ffprobe_error": f"{type(exc).__name__}: {exc}"}
    if result.returncode != 0:
        return {"ffprobe_available": True, "ffprobe_error": (result.stderr or "ffprobe_failed")[:200]}
    try:
        payload = json.loads(result.stdout or "{}")
    except Exception as exc:
        return {"ffprobe_available": True, "ffprobe_error": f"json_{type(exc).__name__}"}
    streams = [row for row in list(payload.get("streams") or []) if isinstance(row, dict)]
    has_video_stream = any(str(row.get("codec_type") or "").strip().lower() == "video" for row in streams)
    durations: list[float] = []
    for value in [payload.get("format", {}).get("duration") if isinstance(payload.get("format"), dict) else None]:
        try:
            durations.append(float(value))
        except Exception:
            pass
    for row in streams:
        try:
            durations.append(float(row.get("duration")))
        except Exception:
            pass
    duration_seconds = max(durations) if durations else 0.0
    return {
        "ffprobe_available": True,
        "video_stream": has_video_stream,
        "duration_seconds": round(duration_seconds, 3),
        "duration_positive": duration_seconds > 0.0,
    }


def _local_html_asset_has_marker(bundle_dir: Path, relpath: str, *, markers: Iterable[str]) -> bool:
    if not relpath:
        return False
    bundle_root = bundle_dir.resolve()
    entry = (bundle_dir / relpath).resolve()
    if bundle_root not in entry.parents or not entry.is_file():
        return False
    if PurePosixPath(relpath).suffix.lower() not in {".html", ".htm"}:
        return False
    normalized_markers = tuple(str(marker or "").strip().lower() for marker in markers if str(marker or "").strip())
    if not normalized_markers:
        return False
    scan_root = entry.parent
    candidates = [entry]
    for candidate in sorted(scan_root.rglob("*")):
        if len(candidates) >= MAX_MARKER_SCAN_FILES:
            break
        resolved = candidate.resolve()
        if (
            candidate.is_file()
            and candidate.suffix.lower() in TEXT_RUNTIME_SUFFIXES
            and bundle_root in resolved.parents
            and resolved not in candidates
        ):
            candidates.append(resolved)
    for candidate in candidates:
        try:
            if candidate.stat().st_size > MAX_MARKER_SCAN_BYTES:
                continue
            body = candidate.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(marker in body for marker in normalized_markers):
            return True
    return False


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
    signature_ok = False
    if suffix in {".mp4", ".m4v", ".mov"}:
        signature_ok = b"ftyp" in header[:32]
    elif suffix == ".webm":
        signature_ok = header.startswith(b"\x1aE\xdf\xa3")
    if not signature_ok:
        return False
    markers = _ffprobe_video_markers(candidate)
    if not markers.get("ffprobe_available"):
        return True
    return bool(markers.get("video_stream") and markers.get("duration_positive"))


def _magicfit_local_video_ready(bundle_dir: Path, payload: dict[str, object]) -> bool:
    return _magicfit_provider_declared(payload) and _local_video_asset_is_playable(bundle_dir, _magicfit_video_relpath(payload))


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
        "pano2vr_entry_relpath",
        "pano2vr_export_entry_relpath",
        "pano2vr_export_root_relpath",
        "pano2vr_root_relpath",
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
        markers=("tdvplayer", "tdvplayerapi", "tourviewer"),
    )
    if not (three_d_vista_url_ready or three_d_vista_entry_ready):
        if three_d_vista_entry:
            reason = "3dvista_entry_missing_or_not_verified"
            action = "import a real 3DVista export whose entry HTML contains 3DVista runtime markers"
        elif _has_key(payload, "three_d_vista_url", "threedvista_url", "3dvista_url"):
            reason = "3dvista_placeholder_field_empty_or_unusable"
            action = "replace the empty 3DVista placeholder field with an allowlisted 3dvista.com URL or import a verified 3DVista export"
        else:
            reason = "missing_3dvista_export"
            action = "run import_3dvista_export.py with a verified 3DVista export or add an allowlisted 3dvista.com URL"
        rows.append({"provider": "3dvista", "reason": reason, "action": action})

    pano2vr_entry = _pano2vr_entry_relpath(payload)
    pano2vr_entry_ready = _local_html_asset_has_marker(
        bundle_dir,
        pano2vr_entry,
        markers=("ggpkg", "ggskin", "pano.xml", "tour.js"),
    )
    if not pano2vr_entry_ready:
        if pano2vr_entry:
            reason = "pano2vr_entry_missing_or_not_verified"
            action = "import a real Pano2VR export whose entry HTML contains Pano2VR runtime markers"
        elif _has_key(payload, "pano2vr_entry_relpath", "pano2vr_export_entry_relpath", "pano2vr_export_root_relpath", "pano2vr_root_relpath"):
            reason = "pano2vr_placeholder_field_empty_or_unusable"
            action = "replace the empty Pano2VR placeholder field with a verified local Pano2VR export entry"
        else:
            reason = "missing_pano2vr_export"
            action = "run import_pano2vr_export.py with a verified Pano2VR export"
        rows.append({"provider": "pano2vr", "reason": reason, "action": action})

    krpano_license_ready = bool(os.getenv("KRPANO_LICENSE_DOMAIN") and os.getenv("KRPANO_LICENSE_KEY"))
    krpano_asset_ready = _walkable_scene_has_real_360_asset(bundle_dir, payload)
    if not (krpano_license_ready and krpano_asset_ready):
        if not isinstance(payload.get("walkable_scene"), dict):
            reason = "missing_walkable_scene"
            action = "generate or import a real walkable_scene before enabling the licensed krpano control"
        elif not krpano_license_ready:
            reason = "missing_krpano_license_environment"
            action = "set KRPANO_LICENSE_DOMAIN and KRPANO_LICENSE_KEY for the property runtime"
        else:
            reason = "walkable_scene_asset_missing_or_not_360"
            action = "attach a real local equirectangular panorama or six cube-face assets before enabling krpano"
        rows.append({"provider": "krpano", "reason": reason, "action": action})

    magicfit_relpath = _magicfit_video_relpath(payload)
    magicfit_url = _magicfit_video_url(payload)
    if not _magicfit_local_video_ready(bundle_dir, payload):
        provider = str(
            payload.get("video_provider")
            or payload.get("video_provider_key")
            or payload.get("video_render_provider")
            or ""
        ).strip().lower()
        if provider and provider != "magicfit":
            reason = "walkthrough_provider_not_magicfit"
            action = "render and import a MagicFit walkthrough with provider=magicfit"
        elif magicfit_url:
            reason = "magicfit_remote_video_needs_live_probe"
            action = "run verify_property_tour_controls.py with --live-probe or import the MagicFit video as a local playable asset"
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
        markers=("tdvplayer", "tdvplayerapi", "tourviewer"),
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
        markers=("ggpkg", "ggskin", "pano.xml", "tour.js"),
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

    if os.getenv("KRPANO_LICENSE_DOMAIN") and os.getenv("KRPANO_LICENSE_KEY") and _walkable_scene_has_real_360_asset(bundle_dir, payload):
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
    if _magicfit_local_video_ready(bundle_dir, payload):
        rows.append(
            {
                "provider": "magicfit",
                "status": "ready",
                "control_path": f"/tours/files/{slug}/{magicfit_relpath}",
                "evidence": "local_magicfit_playable_video",
            }
        )
    elif magicfit_url:
        rows.append(
            {
                "provider": "magicfit",
                "status": "probe_required",
                "control_path": "",
                "evidence": "allowlisted_magicfit_video_url_pending_probe",
                "_probe_url": magicfit_url,
            }
        )
    return rows


def _summarize_provider_blockers(reason_counts: dict[str, dict[str, dict[str, object]]]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for provider in PROVIDER_MODES:
        rows = []
        for reason, payload in sorted(
            reason_counts.get(provider, {}).items(),
            key=lambda item: (-int(item[1].get("count") or 0), item[0]),
        ):
            rows.append(
                {
                    "reason": reason,
                    "count": int(payload.get("count") or 0),
                    "action": str(payload.get("action") or "").strip(),
                }
            )
        summary[provider] = {
            "blocked_count": sum(int(row["count"]) for row in rows),
            "reasons": rows,
        }
    return summary


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
                ffprobe_markers = _ffprobe_video_markers(url)
                playback_markers = {
                    "video_content_type": content_type.startswith("video/"),
                    "video_signature": signature_ok,
                }
                if ffprobe_markers.get("ffprobe_available"):
                    playback_markers["video_stream"] = bool(ffprobe_markers.get("video_stream"))
                    playback_markers["duration_positive"] = bool(ffprobe_markers.get("duration_positive"))
                return {
                    "http_status": int(getattr(response, "status", 0) or 0),
                    "content_type": content_type,
                    "playback_markers": playback_markers,
                    "ffprobe": ffprobe_markers,
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
    require_all_provider_modes: bool = False,
) -> dict[str, object]:
    root = (tour_root or _tour_root()).expanduser().resolve()
    manifests = sorted(root.glob("*/tour.json")) if root.is_dir() else []
    tours: list[dict[str, object]] = []
    provider_counts = {provider: 0 for provider in PROVIDER_MODES}
    action_counts = {provider: 0 for provider in PROVIDER_MODES}
    provider_blocker_reason_counts: dict[str, dict[str, dict[str, object]]] = {provider: {} for provider in PROVIDER_MODES}
    magicfit_playback_evidence_count = 0
    magicfit_playback_evidence: list[dict[str, object]] = []
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
            internal_probe_url = str(control.pop("_probe_url", "") or "").strip()
            if live_probe and ((base_url and control.get("control_path")) or internal_probe_url):
                probe_url = internal_probe_url or urllib.parse.urljoin(base_url.rstrip("/") + "/", str(control["control_path"]).lstrip("/"))
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
                elif str(control.get("status") or "").strip().lower() == "probe_required":
                    control["status"] = "ready"
                    control["evidence"] = "live_probed_magicfit_video_url"
            if provider in provider_counts and str(control.get("status") or "").strip().lower() == "ready":
                provider_counts[provider] += 1
                if provider == "magicfit" and str(control.get("evidence") or "").strip() in {
                    "local_magicfit_playable_video",
                    "live_probed_magicfit_video_url",
                }:
                    magicfit_playback_evidence_count += 1
                    magicfit_playback_evidence.append(
                        {
                            "slug": slug,
                            "evidence": str(control.get("evidence") or "").strip(),
                            "control_path": str(control.get("control_path") or "").strip(),
                        }
                    )
        ready_control_providers = {
            str(control.get("provider") or "").strip().lower()
            for control in controls
            if str(control.get("status") or "").strip().lower() == "ready"
        }
        missing_evidence = [
            row
            for row in _provider_missing_evidence(bundle_dir, payload)
            if str(row.get("provider") or "").strip().lower() not in ready_control_providers
        ]
        for row in missing_evidence:
            provider = str(row.get("provider") or "").strip().lower()
            if provider in action_counts:
                action_counts[provider] += 1
                reason = str(row.get("reason") or "unknown").strip() or "unknown"
                existing = provider_blocker_reason_counts[provider].setdefault(
                    reason,
                    {"count": 0, "action": str(row.get("action") or "").strip()},
                )
                existing["count"] = int(existing.get("count") or 0) + 1
        ready_controls = [
            control
            for control in controls
            if str(control.get("status") or "").strip().lower() == "ready"
        ]
        missing_public_evidence = missing_evidence if require_all_provider_modes else ([] if ready_controls else missing_evidence)
        tour_missing_provider_modes = sorted(
            {
                str(row.get("provider") or "").strip().lower()
                for row in missing_evidence
                if str(row.get("provider") or "").strip().lower() in PROVIDER_MODES
            }
        )
        tours.append(
            {
                "slug": slug,
                "title": str(payload.get("display_title") or payload.get("title") or slug).strip()[:160],
                "status": "ready" if ready_controls else "blocked_missing_verified_controls",
                "blocked_reason": "" if ready_controls else _blocked_control_reason(payload),
                "controls": controls,
                "missing_evidence": missing_public_evidence,
                "missing_provider_modes": tour_missing_provider_modes,
            }
        )
    ready_provider_modes = sorted(provider for provider, count in provider_counts.items() if count > 0)
    missing_provider_modes = [provider for provider in PROVIDER_MODES if provider not in ready_provider_modes]
    status = (
        "blocked_no_tour_manifests"
        if not manifests
        else "fail"
        if failed_probes
        else "blocked_missing_provider_modes"
        if require_all_provider_modes and missing_provider_modes
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
        "provider_blockers": _summarize_provider_blockers(provider_blocker_reason_counts),
        "magicfit_playback": {
            "playback_ok": provider_counts.get("magicfit", 0) == 0 or magicfit_playback_evidence_count == provider_counts.get("magicfit", 0),
            "playable_count": magicfit_playback_evidence_count,
            "ready_count": provider_counts.get("magicfit", 0),
            "evidence": magicfit_playback_evidence[:12],
        },
        "ready_provider_modes": ready_provider_modes,
        "required_provider_modes": list(PROVIDER_MODES),
        "missing_provider_modes": missing_provider_modes,
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
            if provider in missing_provider_modes
        ],
        "live_probe": bool(live_probe),
        "base_url": base_url if live_probe else "",
        "require_all_provider_modes": bool(require_all_provider_modes),
        "tours": tours,
        "notes": [
            "Matterport, 3DVista, Pano2VR, and krpano are ready only when a hosted control route can be justified from manifest evidence.",
            "MagicFit is ready only when the manifest points to a local playable video asset or a live-probed allowlisted hosted video URL with provider=magicfit.",
            "The receipt intentionally omits raw external provider URLs and private listing/source fields.",
        ],
    }


def _receipt_summary(receipt: dict[str, object]) -> dict[str, object]:
    return {
        "generated_at": receipt.get("generated_at"),
        "status": receipt.get("status"),
        "tour_root": receipt.get("tour_root"),
        "tour_count": receipt.get("tour_count"),
        "ready_tour_count": receipt.get("ready_tour_count"),
        "provider_counts": receipt.get("provider_counts"),
        "provider_blockers": receipt.get("provider_blockers"),
        "ready_provider_modes": receipt.get("ready_provider_modes"),
        "required_provider_modes": receipt.get("required_provider_modes"),
        "missing_provider_modes": receipt.get("missing_provider_modes"),
        "next_required_actions": receipt.get("next_required_actions"),
        "live_probe": receipt.get("live_probe"),
        "base_url": receipt.get("base_url"),
        "require_all_provider_modes": receipt.get("require_all_provider_modes"),
    }


def main() -> int:
    _load_cli_env_defaults()
    parser = argparse.ArgumentParser(description="Verify PropertyQuarry hosted 3D tour and walkthrough control readiness.")
    parser.add_argument("--tour-root", default="", help="Tour root. Defaults to EA_PUBLIC_TOUR_DIR or state/public_property_tours.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_TOUR_CONTROL_BASE_URL") or "http://localhost:8097")
    parser.add_argument("--live-probe", action="store_true", help="Probe ready control paths over HTTP.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--write", default="", help="Optional JSON receipt path.")
    parser.add_argument("--summary-only", action="store_true", help="Print only top-level counts/actions; --write still stores the full receipt.")
    parser.add_argument("--require-all-provider-modes", action="store_true", help="Return blocked status until every required provider mode has at least one verified live-ready control.")
    parser.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Return a non-zero exit code for blocked_* receipts. Use this for gold/release gates.",
    )
    args = parser.parse_args()
    receipt = build_property_tour_control_receipt(
        tour_root=Path(args.tour_root) if str(args.tour_root or "").strip() else None,
        base_url=str(args.base_url or "").strip(),
        live_probe=bool(args.live_probe),
        timeout_seconds=float(args.timeout_seconds),
        require_all_provider_modes=bool(args.require_all_provider_modes),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(output + "\n", encoding="utf-8")
    printed_receipt = _receipt_summary(receipt) if args.summary_only else receipt
    print(json.dumps(printed_receipt, indent=2, sort_keys=True))
    status = str(receipt.get("status") or "")
    if status == "pass":
        return 0
    if status.startswith("blocked"):
        return 2 if args.fail_on_blocked else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
