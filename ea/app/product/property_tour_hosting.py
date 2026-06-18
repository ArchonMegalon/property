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
from pathlib import Path
from uuid import uuid4

from app.product.projections import compact_text

_PROPERTY_SCOUT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36"
_PROPERTY_SCOUT_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_PROPERTY_SCOUT_FLOORPLAN_ASSET_EXTENSIONS = (*_PROPERTY_SCOUT_IMAGE_EXTENSIONS, ".pdf")
_PROPERTY_PUBLIC_TOUR_PRIVATE_MANIFEST = "tour.private.json"


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
    from app.api.routes.public_tour_payloads import redacted_public_tour_payload

    normalized_payload = dict(payload or {})
    slug = str(normalized_payload.get("slug") or "").strip()
    bundle_dir = _public_tour_dir() / slug if slug else None
    return redacted_public_tour_payload(
        normalized_payload,
        expose_asset_relpaths=True,
        url_allowed=lambda _url: False,
        bundle_dir_resolver=lambda requested_slug: bundle_dir if bundle_dir and str(requested_slug or "").strip() == slug else None,
    )


def _public_tour_private_receipt(payload: dict[str, object]) -> dict[str, object]:
    return {
        "principal_id": str(payload.get("principal_id") or "").strip(),
        "listing_url": str(payload.get("listing_url") or "").strip(),
        "property_url": str(payload.get("property_url") or "").strip(),
        "source_ref": str(payload.get("source_ref") or "").strip(),
        "external_id": str(payload.get("external_id") or "").strip(),
        "recipient_email": str(payload.get("recipient_email") or "").strip().lower(),
        "crezlo_public_url": str(payload.get("crezlo_public_url") or "").strip(),
        "source_virtual_tour_url": str(payload.get("source_virtual_tour_url") or "").strip(),
        "source_virtual_tour_origin": str(payload.get("source_virtual_tour_origin") or "").strip(),
        "panorama_source": str(payload.get("panorama_source") or "").strip(),
        "three_d_vista_url": str(payload.get("three_d_vista_url") or "").strip(),
        "matterport_url": str(payload.get("matterport_url") or "").strip(),
    }


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
    return str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "https://myexternalbrain.com").strip().rstrip("/")

def _property_public_app_base_url() -> str:
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

def _resolve_property_tour_urls(structured_output: dict[str, object]) -> tuple[str, str]:
    hosted_url = _first_non_empty_text(structured_output.get("hosted_url"))
    public_url = _first_non_empty_text(structured_output.get("public_url"))
    share_url = _first_non_empty_text(structured_output.get("share_url"))
    crezlo_public_url = _first_non_empty_text(structured_output.get("crezlo_public_url"))

    branded_tour_url = _first_non_empty_text(
        hosted_url if _is_branded_public_tour_url(hosted_url) else "",
        public_url if _is_branded_public_tour_url(public_url) else "",
        crezlo_public_url if _is_branded_public_tour_url(crezlo_public_url) else "",
        share_url if _is_branded_public_tour_url(share_url) else "",
    )
    vendor_tour_url = _first_non_empty_text(
        public_url if public_url != branded_tour_url else "",
        share_url if share_url != branded_tour_url else "",
        crezlo_public_url if crezlo_public_url != branded_tour_url else "",
    )
    return branded_tour_url, vendor_tour_url

def _property_tour_payload_is_disabled_fallback(structured_output: dict[str, object]) -> bool:
    normalized = dict(structured_output or {})
    if str(normalized.get("scene_strategy") or "").strip() == "generated_listing_summary":
        return True
    if str(normalized.get("creation_mode") or "").strip() == "hosted_listing_fallback":
        return True
    scenes = [dict(entry) for entry in (normalized.get("scenes") or []) if isinstance(entry, dict)]
    if any(str(scene.get("role") or "").strip() == "generated_overview" for scene in scenes):
        return True
    return False

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
            "variant_label": "3DVista" if is_3dvista else "live 360",
            "scene_strategy": "live_360_embed",
            "control_mode": "3dvista" if is_3dvista else "external_live_360",
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
