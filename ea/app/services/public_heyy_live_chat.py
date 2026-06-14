from __future__ import annotations

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from app.services.public_clickrank import request_hostname


_WIDGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")

_HOST_WIDGET_CONFIG = {
    "propertyquarry.com": ("PROPERTYQUARRY_HEYY_LIVE_CHAT_WIDGET_ID", "fwpDbT7l1XVbcKMl"),
    "www.propertyquarry.com": ("PROPERTYQUARRY_HEYY_LIVE_CHAT_WIDGET_ID", "fwpDbT7l1XVbcKMl"),
    "myexternalbrain.com": ("MYEXTERNALBRAIN_HEYY_LIVE_CHAT_WIDGET_ID", "3Tm7uqI7a4oGWwzQ"),
    "www.myexternalbrain.com": ("MYEXTERNALBRAIN_HEYY_LIVE_CHAT_WIDGET_ID", "3Tm7uqI7a4oGWwzQ"),
    "chummer.run": ("CHUMMER_RUN_HEYY_LIVE_CHAT_WIDGET_ID", "SUwtHggibqLQxh7y"),
    "www.chummer.run": ("CHUMMER_RUN_HEYY_LIVE_CHAT_WIDGET_ID", "SUwtHggibqLQxh7y"),
}

_MEMORIAL_WIDGET_CONFIG = {
    "manfred": ("MANFRED_MEMORIAL_HEYY_LIVE_CHAT_WIDGET_ID", "i5qjcywhoSuqynkF"),
}

_PRIVATE_PATH_PREFIXES = (
    "/app",
    "/api",
    "/v1",
    "/auth",
    "/admin",
    "/workspace-access",
    "/tours",
    "/results/files",
    "/memorials/files",
)

_PUBLIC_EXACT_PATHS = {
    "/",
    "/pricing",
    "/register",
    "/security",
    "/integrations",
    "/integrations/google",
    "/integrations/telegram",
    "/integrations/whatsapp",
    "/docs",
    "/get-started",
    "/workspace-link",
}

_PUBLIC_PREFIXES = (
    "/features/",
    "/guides/",
    "/markets/",
    "/blog/",
    "/compare/",
    "/channel/",
)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def heyy_live_chat_enabled() -> bool:
    return any(
        _truthy(os.getenv(env_name))
        for env_name in (
            "EA_PUBLIC_HEYY_LIVE_CHAT_ENABLED",
            "PROPERTYQUARRY_PUBLIC_HEYY_LIVE_CHAT_ENABLED",
            "HEYY_LIVE_CHAT_ENABLED",
        )
    )


def _normalize_hostname(hostname: str | None) -> str:
    return str(hostname or "").split(":", 1)[0].strip().lower().rstrip(".")


def _request_path(request: Any | None) -> str:
    if request is None:
        return "/"
    url = getattr(request, "url", None)
    return _normalize_path(getattr(url, "path", "/"))


def _normalize_path(path: object) -> str:
    normalized = "/" + str(path or "").split("?", 1)[0].split("#", 1)[0].lstrip("/")
    return normalized.rstrip("/") or "/"


def _memorial_slug_for_path(path: str) -> str:
    normalized = _normalize_path(path)
    parts = [part for part in normalized.split("/") if part]
    if len(parts) == 2 and parts[0] == "memorials":
        return parts[1].lower()
    return ""


def heyy_live_chat_route_allowed(path: object) -> bool:
    normalized = _normalize_path(path)
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in _PRIVATE_PATH_PREFIXES):
        return False
    if _memorial_slug_for_path(normalized) in _MEMORIAL_WIDGET_CONFIG:
        return True
    if normalized in _PUBLIC_EXACT_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _configured_widget_id(env_name: str, fallback: str) -> str:
    widget_id = str(os.getenv(env_name) or fallback).strip()
    if _WIDGET_ID_PATTERN.fullmatch(widget_id):
        return widget_id
    return ""


def heyy_live_chat_widget_id(*, hostname: str | None = None, path: object = "/") -> str:
    if not heyy_live_chat_enabled():
        return ""
    normalized_path = _normalize_path(path)
    if not heyy_live_chat_route_allowed(normalized_path):
        return ""
    memorial_slug = _memorial_slug_for_path(normalized_path)
    if memorial_slug:
        config = _MEMORIAL_WIDGET_CONFIG.get(memorial_slug)
        if config:
            return _configured_widget_id(*config)
    config = _HOST_WIDGET_CONFIG.get(_normalize_hostname(hostname))
    if not config:
        return ""
    return _configured_widget_id(*config)


def _base_url() -> str:
    raw = str(os.getenv("HEYY_LIVE_CHAT_BASE_URL") or "https://live-chat.heyy.io").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme == "https" and parsed.netloc:
        return raw
    return "https://live-chat.heyy.io"


def heyy_live_chat_head_snippet(
    request: Any | None = None,
    *,
    hostname: str | None = None,
    path: object | None = None,
) -> str:
    resolved_hostname = _normalize_hostname(hostname) or request_hostname(request)
    resolved_path = _request_path(request) if path is None else _normalize_path(path)
    widget_id = heyy_live_chat_widget_id(hostname=resolved_hostname, path=resolved_path)
    if not widget_id:
        return ""
    base_url = _base_url()
    script_src = "https://assets.heyy.io/live-chat/live-chat.js"
    widget_json = json.dumps(widget_id, ensure_ascii=True)
    base_url_json = json.dumps(base_url, ensure_ascii=True)
    script_src_json = json.dumps(script_src, ensure_ascii=True)
    return (
        '<script type="text/javascript" '
        f'data-heyy-live-chat="{html.escape(widget_id, quote=True)}">\n'
        "window.addEventListener('load', function(){\n"
        "  function loadHeyy(){\n"
        f"    window.heyySettings = {{widgetId: {widget_json}, baseUrl: {base_url_json}}};\n"
        "    var s = document.createElement('script');\n"
        "    s.type = 'text/javascript';\n"
        "    s.async = true;\n"
        f"    s.src = {script_src_json};\n"
        "    document.head.appendChild(s);\n"
        "  }\n"
        "  if ('requestIdleCallback' in window) { requestIdleCallback(loadHeyy); }\n"
        "  else { setTimeout(loadHeyy, 3000); }\n"
        "});\n"
        "</script>"
    )
