from __future__ import annotations

import html
import json
import os
import urllib.parse


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _safe_json_array(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        items = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        items = [str(item or "").strip() for item in str(value or "").split(",") if str(item or "").strip()]
    return json.dumps(items[:50], separators=(",", ":"))


def rybbit_head_snippet() -> str:
    if not _truthy(os.getenv("PROPERTYQUARRY_RYBBIT_ENABLED") or os.getenv("RYBBIT_ENABLED")):
        return ""
    site_id = str(os.getenv("PROPERTYQUARRY_RYBBIT_SITE_ID") or os.getenv("RYBBIT_SITE_ID") or "").strip()
    if not site_id:
        return ""
    base_url = str(os.getenv("PROPERTYQUARRY_RYBBIT_BASE_URL") or os.getenv("RYBBIT_BASE_URL") or "https://app.rybbit.io").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return ""
    script_url = f"{base_url}/api/script.js"
    attrs = [
        f'src="{html.escape(script_url, quote=True)}"',
        "async",
        f'data-site-id="{html.escape(site_id, quote=True)}"',
    ]
    skip_patterns = _safe_json_array(
        os.getenv("PROPERTYQUARRY_RYBBIT_SKIP_PATTERNS")
        or os.getenv("RYBBIT_SKIP_PATTERNS")
        or "/workspace-access/**,/app/api/**,/v1/**,/api/**,/tours/files/**"
    )
    mask_patterns = _safe_json_array(
        os.getenv("PROPERTYQUARRY_RYBBIT_MASK_PATTERNS")
        or os.getenv("RYBBIT_MASK_PATTERNS")
        or "/workspace-access/**,/app/handoffs/**,/tours/**,/app/properties/**"
    )
    if skip_patterns != "[]":
        attrs.append(f"data-skip-patterns='{html.escape(skip_patterns, quote=True)}'")
    if mask_patterns != "[]":
        attrs.append(f"data-mask-patterns='{html.escape(mask_patterns, quote=True)}'")
    debounce = str(os.getenv("PROPERTYQUARRY_RYBBIT_DEBOUNCE_MS") or os.getenv("RYBBIT_DEBOUNCE_MS") or "500").strip()
    if debounce.isdigit():
        attrs.append(f'data-debounce="{html.escape(debounce, quote=True)}"')
    return "<script " + " ".join(attrs) + "></script>"
