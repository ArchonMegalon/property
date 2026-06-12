from __future__ import annotations

import html
import json
import os
import urllib.parse
from typing import Any


_LEGACY_SITE_ID_ENV_BY_HOST = {
    "propertyquarry.com": "RYBBIT_IO_PROPERTYQUARRY_SITE_ID",
    "www.propertyquarry.com": "RYBBIT_IO_PROPERTYQUARRY_SITE_ID",
    "myexternalbrain.com": "RYBBIT_IO_MYEXTERNALBRAIN_SITE_ID",
    "www.myexternalbrain.com": "RYBBIT_IO_MYEXTERNALBRAIN_SITE_ID",
}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _safe_json_array(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        items = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        items = [str(item or "").strip() for item in str(value or "").split(",") if str(item or "").strip()]
    return json.dumps(items[:50], separators=(",", ":"))


def _request_hostname(request: Any | None) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", {})
    forwarded_host = str(headers.get("x-forwarded-host") or "").split(",", 1)[0].split(":", 1)[0].strip()
    if forwarded_host:
        return forwarded_host.lower().rstrip(".")
    header_host = str(headers.get("host") or "").split(":", 1)[0].strip()
    if header_host:
        return header_host.lower().rstrip(".")
    url = getattr(request, "url", None)
    return str(getattr(url, "hostname", "") or "").strip().lower().rstrip(".")


def _enabled() -> bool:
    return any(
        _truthy(os.getenv(env_name))
        for env_name in (
            "PROPERTYQUARRY_RYBBIT_ENABLED",
            "RYBBIT_ENABLED",
            "EA_ENABLE_RYBBIT",
            "EA_PUBLIC_RYBBIT_ENABLED",
        )
    )


def _site_id(hostname: str) -> str:
    direct = str(os.getenv("PROPERTYQUARRY_RYBBIT_SITE_ID") or os.getenv("RYBBIT_SITE_ID") or "").strip()
    if direct:
        return direct
    legacy_env = _LEGACY_SITE_ID_ENV_BY_HOST.get(str(hostname or "").strip().lower())
    if legacy_env:
        return str(os.getenv(legacy_env) or "").strip()
    return ""


def _script_url(base_url: str) -> str:
    legacy_script_src = str(os.getenv("EA_PUBLIC_RYBBIT_SCRIPT_SRC") or "").strip()
    if legacy_script_src:
        parsed_legacy = urllib.parse.urlparse(legacy_script_src)
        if parsed_legacy.scheme in {"https", "http"} and parsed_legacy.netloc:
            return legacy_script_src
    return f"{base_url}/api/script.js"


def rybbit_head_snippet(request: Any | None = None) -> str:
    if not _enabled():
        return ""
    site_id = _site_id(_request_hostname(request))
    if not site_id:
        return ""
    base_url = str(os.getenv("PROPERTYQUARRY_RYBBIT_BASE_URL") or os.getenv("RYBBIT_BASE_URL") or "https://app.rybbit.io").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return ""
    script_url = _script_url(base_url)
    attrs = [
        f'src="{html.escape(script_url, quote=True)}"',
        "async",
        f'data-site-id="{html.escape(site_id, quote=True)}"',
    ]
    skip_patterns = _safe_json_array(
        os.getenv("PROPERTYQUARRY_RYBBIT_SKIP_PATTERNS")
        or os.getenv("RYBBIT_SKIP_PATTERNS")
        or os.getenv("EA_PUBLIC_RYBBIT_SKIP_PATTERNS")
        or "/workspace-access/**,/app/api/**,/v1/**,/api/**,/tours/files/**"
    )
    mask_patterns = _safe_json_array(
        os.getenv("PROPERTYQUARRY_RYBBIT_MASK_PATTERNS")
        or os.getenv("RYBBIT_MASK_PATTERNS")
        or os.getenv("EA_PUBLIC_RYBBIT_MASK_PATTERNS")
        or "/workspace-access/**,/app/handoffs/**,/tours/**,/app/properties/**"
    )
    if skip_patterns != "[]":
        attrs.append(f"data-skip-patterns='{html.escape(skip_patterns, quote=True)}'")
    if mask_patterns != "[]":
        attrs.append(f"data-mask-patterns='{html.escape(mask_patterns, quote=True)}'")
    tag = str(os.getenv("PROPERTYQUARRY_RYBBIT_TAG") or os.getenv("RYBBIT_TAG") or os.getenv("EA_PUBLIC_RYBBIT_TAG") or "").strip()
    if tag:
        attrs.append(f'data-tag="{html.escape(tag, quote=True)}"')
    debounce = str(os.getenv("PROPERTYQUARRY_RYBBIT_DEBOUNCE_MS") or os.getenv("RYBBIT_DEBOUNCE_MS") or os.getenv("EA_PUBLIC_RYBBIT_DEBOUNCE") or "500").strip()
    if debounce.isdigit():
        attrs.append(f'data-debounce="{html.escape(debounce, quote=True)}"')
    return "<script " + " ".join(attrs) + "></script>"
