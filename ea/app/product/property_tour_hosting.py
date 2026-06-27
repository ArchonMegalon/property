from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.product.projections import compact_text

_PROPERTY_SCOUT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36"
_PROPERTY_SCOUT_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_PROPERTY_SCOUT_FLOORPLAN_ASSET_EXTENSIONS = (*_PROPERTY_SCOUT_IMAGE_EXTENSIONS, ".pdf")
_PROPERTY_PUBLIC_TOUR_PRIVATE_MANIFEST = "tour.private.json"
_3DVISTA_EXPORT_MARKERS = ("tdvplayer", "tdvplayerapi", "tourviewer")
_PANO2VR_EXPORT_MARKERS = ("ggpkg", "ggskin", "pano.xml", "tour.js")
_KRPANO_PANORAMA_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_KRPANO_FORBIDDEN_SCENE_STRATEGIES = {"generated_listing_summary", "photo_gallery_hosted", "floorplan_hosted", "pure_360_cube"}
_KRPANO_FORBIDDEN_CREATION_MODES = {"hosted_listing_fallback", "hosted_photo_gallery_tour"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_non_empty_text(*values: object) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _public_tour_dir() -> Path:
    raw_value = str(os.getenv("EA_PUBLIC_TOUR_DIR") or "").strip()
    if raw_value:
        return Path(raw_value).expanduser()
    return Path("/docker/property/state/public_property_tours").expanduser()


def _public_tour_private_manifest_path(bundle_dir: Path) -> Path:
    return bundle_dir / _PROPERTY_PUBLIC_TOUR_PRIVATE_MANIFEST


def _public_tour_asset_max_bytes() -> int:
    raw_value = str(os.getenv("PROPERTYQUARRY_TOUR_ASSET_MAX_BYTES") or "").strip()
    if not raw_value:
        return 25_000_000
    try:
        parsed = int(raw_value)
    except Exception:
        return 25_000_000
    return max(1, min(parsed, 250_000_000))


def _public_tour_asset_content_type_allowed(content_type: str) -> bool:
    normalized = str(content_type or "").strip().lower()
    if not normalized:
        return True
    return (
        normalized.startswith("image/")
        or normalized.startswith("video/")
        or normalized in {"application/pdf", "application/octet-stream"}
    )


def _public_tour_public_payload(payload: dict[str, object]) -> dict[str, object]:
    from app.api.routes.public_tour_payloads import build_public_tour_manifest

    normalized_payload = dict(payload or {})
    slug = str(normalized_payload.get("slug") or "").strip()
    bundle_dir = _public_tour_dir() / slug if slug else None
    public_payload = build_public_tour_manifest(
        normalized_payload,
        expose_asset_relpaths=True,
        url_allowed=lambda _url: False,
        bundle_dir_resolver=lambda requested_slug: bundle_dir if bundle_dir and str(requested_slug or "").strip() == slug else None,
    ).as_dict()
    live_url = _safe_live_property_tour_url(
        normalized_payload.get("source_virtual_tour_url")
        or normalized_payload.get("source_virtual_tour_origin")
    )
    live_provider = _property_tour_provider_host_kind(live_url)
    if live_provider:
        if live_provider == "matterport":
            public_payload["control_mode"] = "matterport"
        elif live_provider == "3dvista":
            public_payload["control_mode"] = "3dvista"
        if not public_payload.get("scenes"):
            public_payload["scenes"] = [
                {
                    "name": "Matterport Tour" if live_provider == "matterport" else "3DVista Tour",
                    "role": "live_360",
                    "image_url": _matterport_thumb_url(live_url) if live_provider == "matterport" else "",
                    "mime_type": "image/jpeg",
                }
            ]
    return public_payload


def _public_tour_private_receipt(payload: dict[str, object]) -> dict[str, object]:
    from app.api.routes.public_tour_payloads import PrivateTourReceipt

    return PrivateTourReceipt.from_payload(payload).as_dict()


def _write_hosted_property_tour_payload(bundle_dir: Path, payload: dict[str, object]) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    public_payload = _public_tour_public_payload(payload)
    private_payload = _public_tour_private_receipt(payload)
    (bundle_dir / "tour.json").write_text(json.dumps(public_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _public_tour_private_manifest_path(bundle_dir).write_text(
        json.dumps(private_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_hosted_property_tour_payload(bundle_dir: Path) -> dict[str, object]:
    manifest_path = bundle_dir / "tour.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    private_manifest_path = _public_tour_private_manifest_path(bundle_dir)
    if private_manifest_path.exists():
        try:
            private_payload = json.loads(private_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            private_payload = {}
        if isinstance(private_payload, dict):
            payload = {**dict(payload), **dict(private_payload)}
    return payload


def revoke_hosted_property_tour_bundle(*, slug: str, principal_id: str = "", actor: str = "") -> dict[str, object]:
    normalized_slug = str(slug or "").strip()
    if not normalized_slug or "/" in normalized_slug or ".." in normalized_slug:
        return {"status": "not_found", "slug": normalized_slug}
    public_dir = _public_tour_dir()
    root = public_dir.resolve()
    bundle_dir = (public_dir / normalized_slug).resolve()
    if bundle_dir == root or root not in bundle_dir.parents or not bundle_dir.exists() or not bundle_dir.is_dir():
        return {"status": "not_found", "slug": normalized_slug}
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.exists():
        return {"status": "not_found", "slug": normalized_slug}
    payload = _load_hosted_property_tour_payload(bundle_dir)
    owner_principal = str(payload.get("principal_id") or "").strip()
    requested_principal = str(principal_id or "").strip()
    if requested_principal and owner_principal and owner_principal != requested_principal:
        return {"status": "not_found", "slug": normalized_slug}
    revoked_at = _now_iso()
    file_count = sum(1 for path in bundle_dir.rglob("*") if path.is_file())
    receipt_dir = public_dir / ".revocations"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / f"{normalized_slug}.json").write_text(
        json.dumps(
            {
                "slug": normalized_slug,
                "status": "revoked",
                "revoked_at": revoked_at,
                "principal_id_sha256": hashlib.sha256(owner_principal.encode("utf-8")).hexdigest() if owner_principal else "",
                "actor": str(actor or "").strip()[:120],
                "removed_file_count": file_count,
                "previous_public_url": str(payload.get("hosted_url") or payload.get("public_url") or "").strip(),
                "previous_title": str(payload.get("display_title") or payload.get("title") or "").strip()[:220],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    shutil.rmtree(bundle_dir, ignore_errors=True)
    return {
        "status": "revoked",
        "slug": normalized_slug,
        "revoked_at": revoked_at,
        "removed_file_count": file_count,
    }


def _configured_public_tour_hosts() -> tuple[str, ...]:
    hosts: list[str] = []
    for raw in (
        str(os.getenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL") or "").strip(),
        str(os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL") or "").strip(),
        str(os.getenv("EA_PUBLIC_TOUR_BASE_URL") or "").strip(),
        str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip(),
    ):
        if not raw:
            continue
        parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
        host = str(parsed.netloc or parsed.path or "").strip().lower()
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)

def _public_app_base_url() -> str:
    return str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "https://propertyquarry.com").strip().rstrip("/")

def _property_public_app_base_url() -> str:
    explicit = str(os.getenv("PROPERTYQUARRY_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    explicit = str(os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return "https://propertyquarry.com"

def _property_public_tour_base_url() -> str:
    explicit = str(os.getenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"{_property_public_app_base_url()}/tours"

def _hosted_property_tour_public_base_url() -> str:
    explicit = str(os.getenv("EA_PUBLIC_TOUR_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    public_app = str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if public_app:
        return f"{public_app}/tours"
    return _property_public_tour_base_url()

def _workspace_access_public_base_url() -> str:
    explicit = str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    redirect_uri = str(os.getenv("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if redirect_uri:
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return _public_app_base_url()

def _is_crezlo_tour_host(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = str(parsed.netloc or parsed.path or "").strip().lower()
    return "crezlo" in host

def _is_branded_public_tour_url(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = str(parsed.netloc or parsed.path or "").strip().lower()
    if not host:
        return False
    configured_hosts = _configured_public_tour_hosts()
    if configured_hosts:
        return host in configured_hosts
    if (host.endswith("myexternalbrain.com") or host.endswith("propertyquarry.com")) and "/tours/" in normalized:
        return not _is_crezlo_tour_host(normalized)
    return False

def _resolve_property_tour_urls(
    structured_output: dict[str, object],
    *,
    allow_unverified_branded: bool = False,
) -> tuple[str, str]:
    hosted_url = _first_non_empty_text(structured_output.get("hosted_url"))
    public_url = _first_non_empty_text(structured_output.get("public_url"))
    share_url = _first_non_empty_text(structured_output.get("share_url"))
    crezlo_public_url = _first_non_empty_text(structured_output.get("crezlo_public_url"))
    source_live_360_url = _embedded_live_360_source_url(structured_output)
    source_live_360_provider = _property_tour_provider_host_kind(source_live_360_url)
    branded_candidates = [
        candidate
        for candidate in (
            hosted_url,
            public_url,
            crezlo_public_url,
            share_url,
        )
        if _is_branded_public_tour_url(candidate)
    ]
    non_branded_vendor_candidates = [
        candidate
        for candidate in (
            public_url,
            share_url,
            crezlo_public_url,
        )
        if candidate and not _is_branded_public_tour_url(candidate)
    ]
    branded_tour_url = ""
    for candidate in branded_candidates:
        if allow_unverified_branded or _hosted_property_tour_verified_open_url(candidate):
            branded_tour_url = candidate
            break
    vendor_tour_url = _first_non_empty_text(
        source_live_360_url,
        public_url if public_url and not _is_branded_public_tour_url(public_url) and public_url != branded_tour_url else "",
        share_url if share_url and not _is_branded_public_tour_url(share_url) and share_url != branded_tour_url else "",
        crezlo_public_url
        if crezlo_public_url and not _is_branded_public_tour_url(crezlo_public_url) and crezlo_public_url != branded_tour_url
        else "",
    )
    return branded_tour_url, vendor_tour_url

def _property_tour_payload_is_disabled_fallback(structured_output: dict[str, object]) -> bool:
    normalized = dict(structured_output or {})
    scene_strategy = str(normalized.get("scene_strategy") or "").strip().lower()
    creation_mode = str(normalized.get("creation_mode") or "").strip().lower()
    control_mode = str(normalized.get("control_mode") or "").strip().lower()
    if scene_strategy in {"generated_listing_summary", "photo_gallery_hosted", "floorplan_hosted", "pure_360_cube"}:
        return True
    if creation_mode == "hosted_listing_fallback":
        return True
    if control_mode == "walkable_3d":
        return True
    scenes = [dict(entry) for entry in (normalized.get("scenes") or []) if isinstance(entry, dict)]
    if any(str(scene.get("role") or "").strip() == "generated_overview" for scene in scenes):
        return True
    return False


def _hosted_property_tour_slug_from_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urllib.parse.urlparse(normalized)
    except Exception:
        return ""
    path_parts = [part for part in str(parsed.path or "").split("/") if part]
    for index, part in enumerate(path_parts):
        if part == "tours" and index + 1 < len(path_parts):
            return str(path_parts[index + 1] or "").strip()
    return ""


def _hosted_property_tour_payload_for_url(tour_url: object) -> dict[str, object]:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return {}
    parsed = urllib.parse.urlparse(normalized_url)
    if parsed.scheme or parsed.netloc:
        if not _is_branded_public_tour_url(normalized_url):
            return {}
    elif not str(parsed.path or "").startswith("/tours/"):
        return {}
    slug = _hosted_property_tour_slug_from_url(normalized_url)
    if not slug:
        return {}
    payload = _load_hosted_property_tour_payload(_public_tour_dir() / slug)
    return dict(payload) if isinstance(payload, dict) else {}


def _hosted_property_tour_control_url(tour_url: object, *, viewer: str = "") -> str:
    normalized = str(tour_url or "").strip()
    if not normalized:
        return ""
    viewer_slug = str(viewer or "").strip().lower()
    if viewer_slug == "metaport":
        viewer_slug = "matterport"
    if viewer_slug in {"pano_2_vr", "pano-2-vr"}:
        viewer_slug = "pano2vr"
    if viewer_slug in {"kr_pano", "kr-pano"}:
        viewer_slug = "krpano"
    if viewer_slug not in {"", "matterport", "3dvista", "pano2vr", "krpano"}:
        viewer_slug = ""
    try:
        parsed = urllib.parse.urlparse(normalized)
        path = str(parsed.path or "").rstrip("/")
        if any(path.endswith(f"/control/{mode}") for mode in ("matterport", "3dvista", "pano2vr", "krpano")):
            path = path.rsplit("/control/", 1)[0]
        elif path.endswith("/control"):
            path = path[: -len("/control")]
        path = f"{path}/control/{viewer_slug}" if viewer_slug else f"{path}/control"
        return urllib.parse.urlunparse(parsed._replace(path=path, query="", fragment=""))
    except Exception:
        base = normalized.rstrip("/")
        return f"{base}/control/{viewer_slug}" if viewer_slug else f"{base}/control"


def _hosted_property_tour_has_matterport_export(tour_url: object) -> bool:
    payload = _hosted_property_tour_payload_for_url(tour_url)
    for key in ("matterport_url", "source_virtual_tour_url", "crezlo_public_url"):
        value = str(payload.get(key) or "").strip()
        if value and _property_tour_provider_host_kind(value) == "matterport":
            return True
    return False


def _hosted_property_tour_entry_has_marker(bundle_dir: Path, relpath: object, *, markers: tuple[str, ...]) -> bool:
    raw_relpath = str(relpath or "").strip().replace("\\", "/")
    if not raw_relpath or raw_relpath.startswith("/") or "://" in raw_relpath or "\x00" in raw_relpath:
        return False
    path = PurePosixPath(raw_relpath)
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    if path.suffix.lower() not in {".htm", ".html"}:
        return False
    candidate = (bundle_dir / "/".join(path.parts)).resolve()
    resolved_bundle = bundle_dir.resolve()
    if candidate == resolved_bundle or resolved_bundle not in candidate.parents or not candidate.is_file():
        return False
    try:
        body = candidate.read_text(encoding="utf-8", errors="replace")[:200_000].lower()
    except OSError:
        return False
    return any(marker in body for marker in markers)


def _hosted_property_tour_has_3dvista_export(tour_url: object) -> bool:
    payload = _hosted_property_tour_payload_for_url(tour_url)
    for key in ("three_d_vista_url", "threedvista_url", "3dvista_url", "source_virtual_tour_url", "crezlo_public_url"):
        value = str(payload.get(key) or "").strip()
        if value and _property_tour_provider_host_kind(value) == "3dvista":
            return True
    slug = _hosted_property_tour_slug_from_url(tour_url)
    if not slug:
        return False
    bundle_dir = (_public_tour_dir() / slug).resolve()
    for key in ("three_d_vista_entry_relpath", "threedvista_entry_relpath", "3dvista_entry_relpath"):
        entry_relpath = str(payload.get(key) or "").strip().lstrip("/")
        if not entry_relpath:
            continue
        if _hosted_property_tour_entry_has_marker(bundle_dir, entry_relpath, markers=_3DVISTA_EXPORT_MARKERS):
            return True
    return False


def _hosted_property_tour_has_pano2vr_export(tour_url: object) -> bool:
    payload = _hosted_property_tour_payload_for_url(tour_url)
    slug = _hosted_property_tour_slug_from_url(tour_url)
    if not payload or not slug:
        return False
    bundle_dir = (_public_tour_dir() / slug).resolve()
    for key in ("pano2vr_entry_relpath", "pano2vr_export_entry_relpath"):
        if _hosted_property_tour_entry_has_marker(bundle_dir, payload.get(key), markers=_PANO2VR_EXPORT_MARKERS):
            return True
    return False


def _hosted_property_tour_file_exists(bundle_dir: Path, relpath: object) -> bool:
    return _hosted_property_tour_asset_path(bundle_dir, relpath) is not None


def _hosted_property_tour_asset_path(bundle_dir: Path, relpath: object) -> Path | None:
    normalized = str(relpath or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    if not parts:
        return None
    safe_relpath = "/".join(parts)
    candidate = (bundle_dir / safe_relpath).resolve()
    if bundle_dir.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _hosted_property_tour_image_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return (0, 0)


def _hosted_property_tour_is_equirectangular_image(bundle_dir: Path, relpath: object) -> bool:
    candidate = _hosted_property_tour_asset_path(bundle_dir, relpath)
    if candidate is None or PurePosixPath(str(relpath or "")).suffix.lower() not in _KRPANO_PANORAMA_IMAGE_EXTENSIONS:
        return False
    width, height = _hosted_property_tour_image_dimensions(candidate)
    if width < 1024 or height < 512:
        return False
    ratio = width / height if height else 0
    return 1.75 <= ratio <= 2.25


def _hosted_property_tour_is_cube_face_image(bundle_dir: Path, relpath: object) -> bool:
    candidate = _hosted_property_tour_asset_path(bundle_dir, relpath)
    if candidate is None or PurePosixPath(str(relpath or "")).suffix.lower() not in _KRPANO_PANORAMA_IMAGE_EXTENSIONS:
        return False
    width, height = _hosted_property_tour_image_dimensions(candidate)
    if width < 512 or height < 512:
        return False
    ratio = width / height if height else 0
    return 0.9 <= ratio <= 1.1


def _hosted_property_tour_has_walkable_360_asset(*, bundle_dir: Path, payload: dict[str, object]) -> bool:
    scene_strategy = str(payload.get("scene_strategy") or "").strip().lower()
    creation_mode = str(payload.get("creation_mode") or "").strip().lower()
    if scene_strategy in _KRPANO_FORBIDDEN_SCENE_STRATEGIES or creation_mode in _KRPANO_FORBIDDEN_CREATION_MODES:
        return False
    walkable_scene = payload.get("walkable_scene")
    if not isinstance(walkable_scene, dict) or not walkable_scene:
        return False
    projection = str(walkable_scene.get("projection") or walkable_scene.get("type") or "").strip().lower()
    if projection and projection not in {"equirectangular", "panorama", "cubemap", "cube"}:
        return False
    for key in ("panorama_relpath", "equirect_relpath", "image_relpath", "asset_relpath"):
        relpath = str(walkable_scene.get(key) or "").strip()
        if relpath and _hosted_property_tour_is_equirectangular_image(bundle_dir, relpath):
            return True
    cube_faces = walkable_scene.get("cube_faces")
    if isinstance(cube_faces, dict):
        values = list(cube_faces.values())
    elif isinstance(cube_faces, list):
        values = cube_faces
    else:
        values = []
    valid_faces = [
        value
        for value in values
        if _hosted_property_tour_is_cube_face_image(bundle_dir, value)
    ]
    return len(valid_faces) >= 6


def _krpano_license_runtime_config() -> dict[str, str]:
    domain = str(os.getenv("KRPANO_LICENSE_DOMAIN") or "").strip()
    key = str(os.getenv("KRPANO_LICENSE_KEY") or "").strip()
    if not domain or not key:
        return {}
    return {"domain": domain, "key": key}


def _hosted_property_tour_has_krpano_control(tour_url: object) -> bool:
    payload = _hosted_property_tour_payload_for_url(tour_url)
    slug = _hosted_property_tour_slug_from_url(tour_url)
    if not payload or not slug or not _krpano_license_runtime_config():
        return False
    scenes = [dict(entry) for entry in (payload.get("scenes") or []) if isinstance(entry, dict)]
    if any(str(scene.get("role") or "").strip() == "generated_overview" for scene in scenes):
        return False
    bundle_dir = (_public_tour_dir() / slug).resolve()
    return _hosted_property_tour_has_walkable_360_asset(bundle_dir=bundle_dir, payload=payload)


def _hosted_property_tour_verified_provider(tour_url: object) -> str:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return ""
    direct_provider = _property_tour_provider_host_kind(normalized_url)
    if direct_provider:
        return direct_provider
    payload = _hosted_property_tour_payload_for_url(normalized_url)
    if not payload:
        return ""
    if not _property_tour_payload_is_disabled_fallback(payload):
        if _hosted_property_tour_has_matterport_export(normalized_url):
            return "matterport"
        if _hosted_property_tour_has_3dvista_export(normalized_url):
            return "3dvista"
        if _hosted_property_tour_has_pano2vr_export(normalized_url):
            return "pano2vr"
    if _hosted_property_tour_has_krpano_control(normalized_url):
        return "krpano"
    return ""


def _hosted_property_tour_verified_open_url(tour_url: object) -> str:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return ""
    provider = _hosted_property_tour_verified_provider(normalized_url)
    if not provider:
        return ""
    if _property_tour_provider_host_kind(normalized_url) == provider:
        return normalized_url
    return _hosted_property_tour_control_url(normalized_url, viewer=provider)


def _hosted_property_tour_walkthrough_asset_url(tour_url: object) -> str:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return ""
    slug = _hosted_property_tour_slug_from_url(normalized_url)
    if not slug:
        return ""
    bundle_dir = _public_tour_dir() / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.exists():
        return ""
    payload = _load_hosted_property_tour_payload(bundle_dir)
    if not payload or not isinstance(payload, dict):
        return ""
    video_relpath = str(payload.get("video_relpath") or "").strip().lstrip("/")
    if not video_relpath:
        return ""
    video_path = (bundle_dir / video_relpath).resolve()
    if bundle_dir.resolve() not in video_path.parents or not video_path.exists() or not video_path.is_file():
        return ""
    provider_key = str(
        payload.get("video_provider")
        or payload.get("video_provider_key")
        or payload.get("video_render_provider")
        or ""
    ).strip().lower()
    if not provider_key:
        return ""
    coverage_proof = str(payload.get("video_coverage_proof") or "").strip()
    generated_video_providers = {"magicfit", "onemin_i2v", "ea_one_manager_onemin_i2v", "poppy_ai"}
    if provider_key in generated_video_providers and coverage_proof != "boundary_verified_frame_continuation":
        return ""
    return _hosted_public_tour_asset_url(normalized_url, slug=slug, asset_relpath=video_relpath)


def _hosted_property_tour_generated_reconstruction_asset_url(tour_url: object, *, asset_key: str = "viewer_relpath") -> str:
    normalized_url = str(tour_url or "").strip()
    normalized_key = str(asset_key or "viewer_relpath").strip()
    if not normalized_url or normalized_key not in {
        "viewer_relpath",
        "model_relpath",
        "material_relpath",
        "glb_model_relpath",
        "walkthrough_video_relpath",
    }:
        return ""
    slug = _hosted_property_tour_slug_from_url(normalized_url)
    if not slug:
        return ""
    bundle_dir = _public_tour_dir() / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.exists():
        return ""
    payload = _load_hosted_property_tour_payload(bundle_dir)
    if not payload or not isinstance(payload, dict):
        return ""
    generated_reconstruction = payload.get("generated_reconstruction")
    if not isinstance(generated_reconstruction, dict):
        return ""
    provider = str(generated_reconstruction.get("provider") or "").strip().lower()
    if provider != "propertyquarry_generated_reconstruction":
        return ""
    if bool(generated_reconstruction.get("verified_provider_capture")):
        return ""
    relpath = str(generated_reconstruction.get(normalized_key) or "").strip().lstrip("/")
    if not relpath:
        return ""
    asset_path = (bundle_dir / relpath).resolve()
    if bundle_dir.resolve() not in asset_path.parents or not asset_path.exists() or not asset_path.is_file():
        return ""
    return _hosted_public_tour_asset_url(normalized_url, slug=slug, asset_relpath=relpath)


def _published_walkthrough_asset_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urllib.parse.urlparse(normalized)
    except Exception:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    if Path(str(parsed.path or "")).suffix.lower() not in {".mp4", ".m4v", ".mov", ".webm"}:
        return ""
    path_parts = [part for part in str(parsed.path or "").split("/") if part]
    if len(path_parts) >= 4 and path_parts[0] == "tours" and path_parts[1] == "files":
        slug = str(path_parts[2] or "").strip()
        hosted_tour_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, f"/tours/{slug}", "", "", ""))
        if _is_branded_public_tour_url(hosted_tour_url):
            manifest_payload = _hosted_property_tour_payload_for_url(hosted_tour_url)
            verified_asset_url = _hosted_property_tour_walkthrough_asset_url(hosted_tour_url)
            canonical_candidate_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
            if manifest_payload and (not verified_asset_url or canonical_candidate_url != verified_asset_url):
                return ""
            if not manifest_payload:
                return canonical_candidate_url
            return verified_asset_url
    return normalized

def _existing_hosted_property_tour_url(structured_output: dict[str, object]) -> str:
    slug = str(structured_output.get("slug") or "").strip()
    if not slug:
        return ""
    base_url = _hosted_property_tour_public_base_url()
    public_dir = _public_tour_dir()
    bundle_dir = public_dir / slug
    bundle_manifest = public_dir / slug / "tour.json"
    if not bundle_manifest.exists():
        return ""
    payload = _load_hosted_property_tour_payload(bundle_dir)
    if not payload:
        return ""
    scenes = [dict(entry) for entry in (payload.get("scenes") or []) if isinstance(entry, dict)]
    source_virtual_tour_url = str(payload.get("source_virtual_tour_url") or "").strip()
    hosted_url = f"{base_url}/{slug}"
    if source_virtual_tour_url and not scenes:
        return f"{hosted_url}#live-360"
    if not scenes:
        return ""
    has_asset = False
    for scene in scenes:
        asset_relpath = str(scene.get("asset_relpath") or "").strip()
        if not asset_relpath:
            continue
        candidate = (bundle_dir / asset_relpath).resolve()
        if bundle_dir.resolve() not in candidate.parents:
            continue
        if candidate.exists() and candidate.is_file():
            has_asset = True
            break
    if not has_asset:
        if source_virtual_tour_url:
            return f"{hosted_url}#live-360"
        return ""
    if source_virtual_tour_url:
        return f"{hosted_url}#live-360"
    return hosted_url

def _existing_hosted_property_tour_payload(slug: str) -> dict[str, object]:
    normalized_slug = str(slug or "").strip()
    if not normalized_slug:
        return {}
    hosted_url = _existing_hosted_property_tour_url({"slug": normalized_slug})
    if not hosted_url:
        return {}
    public_dir = _public_tour_dir()
    manifest_path = public_dir / normalized_slug / "tour.json"
    payload = _load_hosted_property_tour_payload(public_dir / normalized_slug)
    if not payload:
        return {}
    payload = dict(payload)
    payload["slug"] = normalized_slug
    payload["hosted_url"] = hosted_url
    payload["public_url"] = hosted_url
    payload["tour_cache_status"] = "existing"
    payload.setdefault("creation_mode", "hosted_property_tour")
    return payload


def _normalized_property_tour_identity_url(value: object) -> str:
    return urllib.parse.urldefrag(str(value or "").strip())[0]


def _existing_hosted_property_tour_url_for_identity(
    *,
    property_url: object = "",
    source_ref: object = "",
    external_id: object = "",
    slug: object = "",
) -> str:
    normalized_slug = str(slug or "").strip()
    if normalized_slug:
        hosted_url = _existing_hosted_property_tour_url({"slug": normalized_slug})
        if hosted_url:
            return hosted_url
    normalized_property_url = _normalized_property_tour_identity_url(property_url)
    normalized_source_ref = str(source_ref or "").strip()
    normalized_external_id = str(external_id or "").strip()
    if not normalized_property_url and not normalized_source_ref and not normalized_external_id:
        return ""
    public_dir = _public_tour_dir()
    try:
        bundle_dirs = sorted(
            (path for path in public_dir.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name,
        )
    except Exception:
        return ""
    for bundle_dir in bundle_dirs:
        payload = _load_hosted_property_tour_payload(bundle_dir)
        if not payload:
            continue
        payload_property_urls = {
            _normalized_property_tour_identity_url(payload.get("property_url")),
            _normalized_property_tour_identity_url(payload.get("listing_url")),
        }
        payload_property_urls.discard("")
        payload_source_ref = str(payload.get("source_ref") or "").strip()
        payload_external_id = str(payload.get("external_id") or "").strip()
        if normalized_property_url and normalized_property_url in payload_property_urls:
            hosted_url = _existing_hosted_property_tour_url({"slug": bundle_dir.name})
            if hosted_url:
                return hosted_url
        if normalized_source_ref and normalized_source_ref == payload_source_ref:
            hosted_url = _existing_hosted_property_tour_url({"slug": bundle_dir.name})
            if hosted_url:
                return hosted_url
        if normalized_external_id and normalized_external_id == payload_external_id:
            hosted_url = _existing_hosted_property_tour_url({"slug": bundle_dir.name})
            if hosted_url:
                return hosted_url
    return ""

def _safe_live_property_tour_url(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return normalized

def _property_tour_provider_host_kind(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urllib.parse.urlparse(normalized)
    except Exception:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    if host == "matterport.com" or host.endswith(".matterport.com"):
        return "matterport"
    if host == "3dvista.com" or host.endswith(".3dvista.com"):
        return "3dvista"
    return ""

def _prefer_hosted_live_360_embed(source_virtual_tour_url: object) -> bool:
    normalized = _safe_live_property_tour_url(source_virtual_tour_url)
    if not normalized:
        return False
    return bool(_property_tour_provider_host_kind(normalized))

def _hosted_property_tour_slug(*, title: str, listing_id: str, property_url: str, variant_key: str) -> str:
    seed = _first_non_empty_text(title, listing_id, property_url, "property tour")
    normalized = seed.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "property-tour"
    variant = re.sub(r"[^a-z0-9]+", "-", str(variant_key or "layout_first").lower()).strip("-") or "layout-first"
    digest = hashlib.sha256(f"{property_url}|{listing_id}|{variant}".encode("utf-8")).hexdigest()[:10]
    return f"{base[:96].strip('-') or 'property-tour'}-{variant}-{digest}"

def _download_public_tour_asset_with_type(url: str, target: Path) -> str:
    request = urllib.request.Request(str(url), headers={"User-Agent": _PROPERTY_SCOUT_USER_AGENT})
    content_type = ""
    total_bytes = 0
    max_bytes = _public_tour_asset_max_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=180) as response:
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if not _public_tour_asset_content_type_allowed(content_type):
            raise RuntimeError("tour_asset_content_type_unsupported")
        try:
            content_length = int(str(response.headers.get("Content-Length") or "0").strip() or "0")
        except Exception:
            content_length = 0
        if content_length > max_bytes:
            raise RuntimeError("tour_asset_too_large")
        with target.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise RuntimeError("tour_asset_too_large")
                handle.write(chunk)
    if total_bytes <= 0 or not target.exists():
        raise RuntimeError("tour_asset_empty")
    return content_type


def _download_public_tour_asset(url: str, target: Path) -> None:
    _download_public_tour_asset_with_type(url, target)

def _hosted_property_tour_asset_suffix(*, url: str, content_type: str) -> str:
    suffix = Path(urllib.parse.urlparse(str(url or "")).path).suffix.lower()
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in {"application/octet-stream", "binary/octet-stream"} and suffix:
        return suffix
    guessed = mimetypes.guess_extension(normalized_type)
    if guessed:
        return guessed
    return suffix or ".bin"

def _write_hosted_floorplan_property_tour_bundle(
    *,
    principal_id: str,
    title: str,
    listing_id: str,
    property_url: str,
    variant_key: str,
    floorplan_urls: list[str] | tuple[str, ...],
    property_facts_json: dict[str, object],
    source_host: str,
    source_ref: str = "",
    external_id: str = "",
    recipient_email: str = "",
) -> dict[str, object]:
    normalized_urls = [
        _safe_live_property_tour_url(value)
        for value in list(floorplan_urls or [])
        if _safe_live_property_tour_url(value)
    ]
    if not normalized_urls:
        raise RuntimeError("floorplan_assets_missing")
    base_url = _hosted_property_tour_public_base_url()
    public_dir = _public_tour_dir()
    slug = _hosted_property_tour_slug(title=title, listing_id=listing_id, property_url=property_url, variant_key=variant_key)
    existing_payload = _existing_hosted_property_tour_payload(slug)
    if existing_payload:
        return existing_payload
    bundle_dir = public_dir / slug
    staging_dir = public_dir / f".{slug}.tmp-{uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    scenes: list[dict[str, object]] = []
    try:
        for ordinal, asset_url in enumerate(normalized_urls[:12], start=1):
            try:
                suffix = _hosted_property_tour_asset_suffix(url=asset_url, content_type="")
                if suffix.lower() not in _PROPERTY_SCOUT_FLOORPLAN_ASSET_EXTENSIONS:
                    suffix = ".pdf"
                relpath = f"floorplan-{ordinal:02d}{suffix}"
                content_type = _download_public_tour_asset_with_type(asset_url, staging_dir / relpath)
                suffix = _hosted_property_tour_asset_suffix(url=asset_url, content_type=content_type)
                if suffix.lower() not in _PROPERTY_SCOUT_FLOORPLAN_ASSET_EXTENSIONS:
                    (staging_dir / relpath).unlink(missing_ok=True)
                    continue
                if suffix and not relpath.endswith(suffix):
                    corrected_relpath = f"floorplan-{ordinal:02d}{suffix}"
                    (staging_dir / relpath).rename(staging_dir / corrected_relpath)
                    relpath = corrected_relpath
                scenes.append(
                    {
                        "ordinal": ordinal,
                        "name": f"Floorplan {ordinal}",
                        "role": "floorplan",
                        "privacy_class": "floorplan_pdf_public" if relpath.lower().endswith(".pdf") else "public",
                        "asset_relpath": relpath,
                        "source_url": asset_url,
                        "property_url": property_url,
                        "mime_type": content_type or mimetypes.guess_type(relpath)[0] or "application/octet-stream",
                    }
                )
            except Exception:
                continue
        if not scenes:
            raise RuntimeError("floorplan_assets_unavailable")
        facts = dict(property_facts_json or {})
        existing_address_lines = [str(value or "").strip() for value in list(facts.get("address_lines") or []) if str(value or "").strip()]
        existing_teasers = [str(value or "").strip() for value in list(facts.get("teaser_attributes") or []) if str(value or "").strip()]
        facts.update(
            {
                "has_floorplan": True,
                "floorplan_count": max(int(facts.get("floorplan_count") or 0), len(scenes)),
                "floorplan_urls_json": normalized_urls,
                "tour_media_mode": "floorplan_hosted",
                "address_lines": existing_address_lines or ([source_host] if source_host else []),
                "teaser_attributes": existing_teasers or ["Hosted floorplan review", f"{len(scenes)} floorplan document(s)"],
            }
        )
        display_title = compact_text(title, fallback="Property Floorplan Tour", limit=180)
        payload = {
            "slug": slug,
            "hosted_url": f"{base_url}/{slug}",
            "public_url": f"{base_url}/{slug}",
            "principal_id": str(principal_id or "").strip(),
            "listing_url": property_url,
            "property_url": property_url,
            "source_ref": str(source_ref or "").strip(),
            "external_id": str(external_id or "").strip(),
            "recipient_email": str(recipient_email or "").strip().lower(),
            "title": f"{display_title} - floorplan tour",
            "display_title": display_title,
            "tour_title": f"{display_title} - floorplan tour",
            "tour_id": None,
            "variant_key": variant_key,
            "variant_label": "floorplan",
            "scene_strategy": "floorplan_hosted",
            "scene_count": len(scenes),
            "facts": facts,
            "brief": {
                "theme_name": "clean_light",
                "tour_style": "hosted_floorplan_review",
                "audience": "property_screening",
                "creative_brief": "Render source floorplan documents directly inside the PropertyQuarry hosted tour page.",
                "call_to_action": "Review the floorplan.",
            },
            "editor_url": "",
            "crezlo_public_url": "",
            "scenes": scenes,
            "generated_at": _now_iso(),
            "creation_mode": "hosted_floorplan_tour",
        }
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        staging_dir.rename(bundle_dir)
        _write_hosted_property_tour_payload(bundle_dir, payload)
        return payload
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

def _write_hosted_photo_gallery_property_tour_bundle(
    *,
    principal_id: str,
    title: str,
    listing_id: str,
    property_url: str,
    variant_key: str,
    media_urls: list[str] | tuple[str, ...],
    property_facts_json: dict[str, object],
    source_host: str,
    source_ref: str = "",
    external_id: str = "",
    recipient_email: str = "",
) -> dict[str, object]:
    normalized_urls = [
        _safe_live_property_tour_url(value)
        for value in list(media_urls or [])
        if _safe_live_property_tour_url(value)
    ]
    if not normalized_urls:
        raise RuntimeError("gallery_assets_missing")
    base_url = _hosted_property_tour_public_base_url()
    public_dir = _public_tour_dir()
    slug = _hosted_property_tour_slug(title=title, listing_id=listing_id, property_url=property_url, variant_key=variant_key)
    existing_payload = _existing_hosted_property_tour_payload(slug)
    if existing_payload:
        return existing_payload
    bundle_dir = public_dir / slug
    staging_dir = public_dir / f".{slug}.tmp-{uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    scenes: list[dict[str, object]] = []
    try:
        for ordinal, asset_url in enumerate(normalized_urls[:12], start=1):
            try:
                suffix = _hosted_property_tour_asset_suffix(url=asset_url, content_type="")
                if suffix.lower() not in _PROPERTY_SCOUT_IMAGE_EXTENSIONS:
                    suffix = ".jpg"
                relpath = f"photo-{ordinal:02d}{suffix}"
                content_type = _download_public_tour_asset_with_type(asset_url, staging_dir / relpath)
                suffix = _hosted_property_tour_asset_suffix(url=asset_url, content_type=content_type)
                if suffix.lower() not in _PROPERTY_SCOUT_IMAGE_EXTENSIONS:
                    (staging_dir / relpath).unlink(missing_ok=True)
                    continue
                if suffix and not relpath.endswith(suffix):
                    corrected_relpath = f"photo-{ordinal:02d}{suffix}"
                    (staging_dir / relpath).rename(staging_dir / corrected_relpath)
                    relpath = corrected_relpath
                scenes.append(
                    {
                        "ordinal": ordinal,
                        "name": f"Photo {ordinal}",
                        "role": "photo",
                        "privacy_class": "public",
                        "asset_relpath": relpath,
                        "source_url": asset_url,
                        "property_url": property_url,
                        "mime_type": content_type or mimetypes.guess_type(relpath)[0] or "application/octet-stream",
                    }
                )
            except Exception:
                continue
        if not scenes:
            raise RuntimeError("gallery_assets_unavailable")
        facts = dict(property_facts_json or {})
        existing_address_lines = [str(value or "").strip() for value in list(facts.get("address_lines") or []) if str(value or "").strip()]
        existing_teasers = [str(value or "").strip() for value in list(facts.get("teaser_attributes") or []) if str(value or "").strip()]
        facts.update(
            {
                "tour_media_mode": "flat_images",
                "media_count": max(int(facts.get("media_count") or 0), len(normalized_urls), len(scenes)),
                "gallery_image_count": len(scenes),
                "media_urls_json": normalized_urls,
                "address_lines": existing_address_lines or ([source_host] if source_host else []),
                "teaser_attributes": existing_teasers or ["Hosted photo tour", f"{len(scenes)} listing photo(s)"],
            }
        )
        display_title = compact_text(title, fallback="Property Photo Tour", limit=180)
        payload = {
            "slug": slug,
            "hosted_url": f"{base_url}/{slug}",
            "public_url": f"{base_url}/{slug}",
            "principal_id": str(principal_id or "").strip(),
            "listing_url": property_url,
            "property_url": property_url,
            "source_ref": str(source_ref or "").strip(),
            "external_id": str(external_id or "").strip(),
            "recipient_email": str(recipient_email or "").strip().lower(),
            "title": f"{display_title} - photo tour",
            "display_title": display_title,
            "tour_title": f"{display_title} - photo tour",
            "tour_id": None,
            "variant_key": variant_key,
            "variant_label": "gallery",
            "scene_strategy": "photo_gallery_hosted",
            "scene_count": len(scenes),
            "facts": facts,
            "brief": {
                "theme_name": "clean_light",
                "tour_style": "hosted_photo_gallery",
                "audience": "property_screening",
                "creative_brief": "Render listing photos directly inside the PropertyQuarry hosted tour page.",
                "call_to_action": "Review the listing photos.",
            },
            "editor_url": "",
            "crezlo_public_url": "",
            "scenes": scenes,
            "generated_at": _now_iso(),
            "creation_mode": "hosted_photo_gallery_tour",
        }
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        staging_dir.rename(bundle_dir)
        _write_hosted_property_tour_payload(bundle_dir, payload)
        return payload
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

def _write_hosted_feelestate_pure_360_property_tour_bundle(
    *,
    principal_id: str,
    title: str,
    listing_id: str,
    property_url: str,
    variant_key: str,
    source_virtual_tour_url: str,
    floorplan_urls: list[str] | tuple[str, ...] = (),
    property_facts_json: dict[str, object],
    source_host: str,
    source_ref: str = "",
    external_id: str = "",
    recipient_email: str = "",
) -> dict[str, object]:
    live_url = _safe_live_property_tour_url(source_virtual_tour_url)
    parsed_live = urllib.parse.urlparse(live_url)
    live_host = str(parsed_live.hostname or "").strip().lower()
    live_provider = _property_tour_provider_host_kind(live_url)
    if live_provider:
        base_url = _hosted_property_tour_public_base_url()
        public_dir = _public_tour_dir()
        slug = _hosted_property_tour_slug(title=title, listing_id=listing_id, property_url=property_url, variant_key=variant_key)
        existing_payload = _existing_hosted_property_tour_payload(slug)
        if existing_payload:
            return existing_payload
        bundle_dir = public_dir / slug
        bundle_dir.mkdir(parents=True, exist_ok=True)
        facts = dict(property_facts_json or {})
        existing_address_lines = [str(value or "").strip() for value in list(facts.get("address_lines") or []) if str(value or "").strip()]
        existing_teasers = [str(value or "").strip() for value in list(facts.get("teaser_attributes") or []) if str(value or "").strip()]
        facts.update(
            {
                "has_360": True,
                "tour_media_mode": "panorama_360",
                "source_virtual_tour_url": live_url,
                "panorama_source": live_host,
                "address_lines": existing_address_lines or ([source_host] if source_host else []),
                "teaser_attributes": existing_teasers or ["Live 360 tour", "Embedded external panorama"],
            }
        )
        is_3dvista = live_provider == "3dvista"
        is_matterport = live_provider == "matterport"
        display_title = compact_text(title, fallback="Live 360 Property Tour", limit=180)
        payload = {
            "slug": slug,
            "hosted_url": f"{base_url}/{slug}",
            "public_url": f"{base_url}/{slug}",
            "principal_id": str(principal_id or "").strip(),
            "listing_url": property_url,
            "property_url": property_url,
            "source_ref": str(source_ref or "").strip(),
            "external_id": str(external_id or "").strip(),
            "recipient_email": str(recipient_email or "").strip().lower(),
            "source_virtual_tour_url": live_url,
            "source_virtual_tour_origin": live_url,
            "title": f"{display_title} - live 360",
            "display_title": display_title,
            "tour_title": f"{display_title} - live 360",
            "tour_id": None,
            "variant_key": variant_key,
            "variant_label": "3DVista" if is_3dvista else ("Matterport" if is_matterport else "live 360"),
            "scene_strategy": "live_360_embed",
            "control_mode": "3dvista" if is_3dvista else ("matterport" if is_matterport else "external_live_360"),
            "scene_count": 1,
            "facts": facts,
            "brief": {
                "theme_name": "3DVista" if is_3dvista else "clean_light",
                "tour_style": "embedded_3dvista" if is_3dvista else "embedded_live_360",
                "audience": "tenant_screening",
                "creative_brief": "Render the 3DVista viewer directly inside the PropertyQuarry hosted tour page." if is_3dvista else "Render the live 360 viewer directly inside the PropertyQuarry hosted tour page.",
                "call_to_action": "Open 3DVista tour." if is_3dvista else "Open live 360 tour.",
            },
            "editor_url": "",
            "crezlo_public_url": live_url,
            "matterport_url": live_url if is_matterport else "",
            "three_d_vista_url": live_url if is_3dvista else "",
            "scenes": [
                {
                    "ordinal": 1,
                    "name": "3DVista Tour" if is_3dvista else "Live 360",
                    "role": "live_360",
                    "image_url": _matterport_thumb_url(live_url)
                    or "",
                    "source_url": live_url,
                    "property_url": property_url,
                    "mime_type": "image/jpeg",
                }
            ],
            "generated_at": _now_iso(),
            "creation_mode": "embedded_live_360",
        }
        _write_hosted_property_tour_payload(bundle_dir, payload)
        return payload
    if "360.kalandra.at" not in live_host and "feelestate" not in live_host:
        raise RuntimeError("pure_360_source_unsupported")
    raise RuntimeError("property_tour_cube_fallback_disabled")

def _embedded_live_360_source_url(payload: dict[str, object]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("source_virtual_tour_url", "source_virtual_tour_origin"):
        normalized = _safe_live_property_tour_url(str(payload.get(key) or "").strip())
        if normalized:
            return normalized
    return ""

def _hosted_property_tour_direct_360_url(tour_url: str) -> str:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return ""
    parsed = urllib.parse.urlparse(normalized_url)
    path_parts = [part for part in str(parsed.path or "").split("/") if part]
    if len(path_parts) < 2 or path_parts[-2] != "tours":
        return ""
    slug = str(path_parts[-1] or "").strip()
    if not slug:
        return ""
    public_dir = _public_tour_dir()
    manifest_path = public_dir / slug / "tour.json"
    if not manifest_path.exists():
        return ""
    payload = _load_hosted_property_tour_payload(public_dir / slug)
    return _embedded_live_360_source_url(payload if isinstance(payload, dict) else {})

def _matterport_thumb_url(source_virtual_tour_url: str) -> str:
    normalized = str(source_virtual_tour_url or "").strip()
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    if _property_tour_provider_host_kind(normalized) != "matterport":
        return ""
    model_id = str(urllib.parse.parse_qs(parsed.query).get("m", [""])[0] or "").strip()
    if not model_id:
        return ""
    return f"https://my.matterport.com/api/v2/player/models/{model_id}/thumb/"

def _property_tour_generated_preview_url(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    path = urllib.parse.urlparse(normalized).path.lower()
    filename = Path(path).name
    return (
        filename.startswith("telegram-preview")
        or filename.startswith("diorama-preview")
    )

def _hosted_public_tour_asset_url(tour_url: str, *, slug: str, asset_relpath: str) -> str:
    normalized_url = str(tour_url or "").strip()
    safe_slug = str(slug or "").strip()
    safe_relpath = str(asset_relpath or "").strip().lstrip("/")
    if not normalized_url or not safe_slug or not safe_relpath:
        return ""
    parsed = urllib.parse.urlparse(normalized_url)
    if not parsed.scheme and not parsed.netloc and str(parsed.path or "").startswith("/tours/"):
        return f"/tours/files/{safe_slug}/{safe_relpath}"
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"/tours/files/{safe_slug}/{safe_relpath}",
            "",
            "",
            "",
        )
    )

def _hosted_property_tour_preview_image_url(tour_url: str) -> str:
    normalized_url = str(tour_url or "").strip()
    if not normalized_url:
        return ""
    parsed = urllib.parse.urlparse(normalized_url)
    path_parts = [part for part in str(parsed.path or "").split("/") if part]
    if len(path_parts) < 2 or path_parts[-2] != "tours":
        return ""
    slug = str(path_parts[-1] or "").strip()
    if not slug:
        return ""
    public_dir = _public_tour_dir()
    bundle_dir = public_dir / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.exists():
        return ""
    payload = _load_hosted_property_tour_payload(bundle_dir)
    if not payload:
        return ""

    role_priority = {
        "diorama": 0,
        "generated_overview": 1,
        "overview": 2,
        "floorplan": 3,
        "panorama_360": 4,
    }
    scenes = list(payload.get("scenes") or []) if isinstance(payload.get("scenes"), list) else []
    ranked_scenes = sorted(
        (scene for scene in scenes if isinstance(scene, dict)),
        key=lambda scene: (
            role_priority.get(str(scene.get("role") or "").strip().lower(), 10),
            int(scene.get("ordinal") or 9999),
        ),
    )
    for scene in ranked_scenes:
        image_url = _safe_live_property_tour_url(str(scene.get("image_url") or "").strip())
        if image_url and image_url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            return image_url
        asset_relpath = str(scene.get("asset_relpath") or "").strip()
        if asset_relpath and asset_relpath.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            asset_path = (bundle_dir / asset_relpath).resolve()
            if bundle_dir.resolve() in asset_path.parents and asset_path.exists() and asset_path.is_file():
                return _hosted_public_tour_asset_url(normalized_url, slug=slug, asset_relpath=asset_relpath)
    return ""
