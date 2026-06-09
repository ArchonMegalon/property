from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request

from functools import lru_cache

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.premium_dossier.models import PremiumDossierCompileResult


@lru_cache(maxsize=1)
def _environment() -> Environment:
    template_root = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_root)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


@lru_cache(maxsize=1)
def _premium_css() -> str:
    css_path = Path(__file__).resolve().parent / "static" / "premium_dossier.css"
    return css_path.read_text(encoding="utf-8")


def _api_safe_token(value: object, fallback: str = "ref") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in str(value or "").strip()).strip("-._")
    return cleaned[:120] or fallback


def _magic_fit_reference_root(*, principal_id: str) -> Path:
    artifact_root = Path(str(os.getenv("EA_ARTIFACTS_DIR") or "/tmp/ea_artifacts")).resolve()
    return artifact_root / "magic_fit_refs" / _api_safe_token(principal_id, "principal")


def _resolve_magic_fit_reference_file(*, principal_id: str, url: str) -> tuple[Path, str] | None:
    parsed = urlparse(str(url or "").strip())
    path = str(parsed.path or "").strip()
    marker = "/app/api/property/magic-fit-reference-files/"
    if marker not in path:
        return None
    reference_id = path.rsplit("/", 1)[-1].strip()
    if not reference_id:
        return None
    root = _magic_fit_reference_root(principal_id=principal_id)
    meta_path = root / f"{_api_safe_token(reference_id)}.json"
    if not meta_path.exists():
        return None
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    file_name_on_disk = str(metadata.get("file_name_on_disk") or "").strip()
    if not file_name_on_disk:
        return None
    file_path = root / file_name_on_disk
    if not file_path.exists():
        return None
    mime_type = str(metadata.get("mime_type") or mimetypes.guess_type(file_path.name)[0] or "image/jpeg").strip()
    return file_path, mime_type


def _data_url_for_private_reference(*, principal_id: str, url: str) -> str:
    resolved = _resolve_magic_fit_reference_file(principal_id=principal_id, url=url)
    if resolved is None:
        return url
    file_path, mime_type = resolved
    data = file_path.read_bytes()
    if not data:
        return url
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _max_inline_image_bytes() -> int:
    raw = str(os.getenv("PROPERTYQUARRY_DOSSIER_INLINE_IMAGE_MAX_BYTES") or str(12 * 1024 * 1024)).strip()
    try:
        return max(int(raw or 0), 1024)
    except Exception:
        return 12 * 1024 * 1024


def _data_url_for_remote_image(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized or normalized.startswith("data:"):
        return normalized
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized
    request = urllib.request.Request(
        normalized,
        headers={"User-Agent": "PropertyQuarry-PremiumDossier/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                return normalized
            data = response.read(_max_inline_image_bytes() + 1)
    except (urllib.error.URLError, ValueError, OSError):
        return normalized
    if not data or len(data) > _max_inline_image_bytes():
        return normalized
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _inline_private_magic_fit_reference_urls(*, html: str, compiled: PremiumDossierCompileResult, principal_id: str) -> str:
    payload = dict(compiled.redacted_payload or {})
    scene = dict(payload.get("magic_fit_scene") or {}) if isinstance(payload.get("magic_fit_scene"), dict) else {}
    urls = [str(item or "").strip() for item in list(scene.get("reference_urls") or []) if str(item or "").strip()]
    urls.extend(str(item or "").strip() for item in list(payload.get("personal_reference_urls") or []) if str(item or "").strip())
    rendered = html
    for url in urls:
        if "/app/api/property/magic-fit-reference-files/" not in url:
            continue
        rendered = rendered.replace(url, _data_url_for_private_reference(principal_id=principal_id, url=url))
    return rendered


def _inline_remote_image_urls(*, html: str, compiled: PremiumDossierCompileResult) -> str:
    payload = dict(compiled.redacted_payload or {})
    urls: list[str] = []
    diorama_scene = dict(payload.get("diorama_scene") or {}) if isinstance(payload.get("diorama_scene"), dict) else {}
    magic_fit_scene = dict(payload.get("magic_fit_scene") or {}) if isinstance(payload.get("magic_fit_scene"), dict) else {}
    urls.append(compiled.hero_image_url)
    urls.extend(list(compiled.gallery_urls))
    urls.extend(list(compiled.floorplan_urls))
    urls.append(str(diorama_scene.get("image_url") or "").strip())
    urls.append(str(magic_fit_scene.get("image_url") or "").strip())
    rendered = html
    seen: set[str] = set()
    for url in urls:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized.startswith("data:") or "/app/api/property/magic-fit-reference-files/" in normalized:
            continue
        data_url = _data_url_for_remote_image(normalized)
        if data_url != normalized:
            rendered = rendered.replace(normalized, data_url)
    return rendered


def render_premium_dossier_html(compiled: PremiumDossierCompileResult, *, principal_id: str = "") -> str:
    template = _environment().get_template("propertyquarry_dossier.html.j2")
    rendered = template.render(
        dossier=compiled,
        css_text=_premium_css(),
        payload=compiled.redacted_payload,
    )
    if principal_id:
        rendered = _inline_private_magic_fit_reference_urls(
            html=rendered,
            compiled=compiled,
            principal_id=principal_id,
        )
    rendered = _inline_remote_image_urls(
        html=rendered,
        compiled=compiled,
    )
    return rendered
