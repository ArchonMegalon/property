from __future__ import annotations

import ipaddress
import os
from typing import Any
from urllib.parse import urlparse


_CLICKRANK_HOST_CONFIG = {
    "myexternalbrain.com": ("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", ""),
    "www.myexternalbrain.com": ("CLICKRANK_AI_MYEXTERNALBRAIN_SITE_ID", ""),
}

_RYBBIT_HOST_CONFIG = {
    "propertyquarry.com": ("RYBBIT_IO_PROPERTYQUARRY_SITE_ID", ""),
    "www.propertyquarry.com": ("RYBBIT_IO_PROPERTYQUARRY_SITE_ID", ""),
    "myexternalbrain.com": ("RYBBIT_IO_MYEXTERNALBRAIN_SITE_ID", ""),
    "www.myexternalbrain.com": ("RYBBIT_IO_MYEXTERNALBRAIN_SITE_ID", ""),
}


def _normalize_hostname(hostname: str | None) -> str:
    return str(hostname or "").strip().lower().rstrip(".")


def _clickrank_enabled() -> bool:
    for env_name in ("EA_ENABLE_CLICKRANK", "EA_PUBLIC_CLICKRANK_ENABLED"):
        if str(os.getenv(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _rybbit_enabled() -> bool:
    for env_name in ("EA_ENABLE_RYBBIT", "EA_PUBLIC_RYBBIT_ENABLED"):
        if str(os.getenv(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _configured_public_base_hostname() -> str:
    return _normalize_hostname(urlparse(str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "")).hostname or "")


def _hostname_can_fallback_to_public_base_url(hostname: str) -> bool:
    normalized = _normalize_hostname(hostname)
    if not normalized:
        return True
    if normalized == "localhost":
        return False
    if normalized.endswith((".internal", ".local", ".localhost")):
        return True
    if "." not in normalized:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


def request_hostname(request: Any) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", {})
    forwarded_host = str(headers.get("x-forwarded-host") or "").split(",", 1)[0].split(":", 1)[0].strip()
    if forwarded_host:
        return _normalize_hostname(forwarded_host)
    header_host = str(headers.get("host") or "").split(":", 1)[0].strip()
    if header_host:
        normalized_header_host = _normalize_hostname(header_host)
        configured_base_host = _configured_public_base_hostname()
        has_proxy_signal = bool(headers.get("x-forwarded-for") or headers.get("cf-connecting-ip") or headers.get("cf-ray"))
        if (
            normalized_header_host not in _CLICKRANK_HOST_CONFIG
            and _hostname_can_fallback_to_public_base_url(normalized_header_host)
            and configured_base_host in _CLICKRANK_HOST_CONFIG
            and has_proxy_signal
        ):
            return configured_base_host
        return normalized_header_host
    url = getattr(request, "url", None)
    return _normalize_hostname(getattr(url, "hostname", ""))


def clickrank_site_id_for_hostname(hostname: str | None) -> str:
    if not _clickrank_enabled():
        return ""
    normalized = _normalize_hostname(hostname)
    config = _CLICKRANK_HOST_CONFIG.get(normalized)
    if config is None and _hostname_can_fallback_to_public_base_url(normalized):
        configured_base_host = _configured_public_base_hostname()
        config = _CLICKRANK_HOST_CONFIG.get(configured_base_host)
    if not config:
        return ""
    env_name, fallback = config
    return str(os.getenv(env_name) or fallback).strip()


def rybbit_site_id_for_hostname(hostname: str | None) -> str:
    if not _rybbit_enabled():
        return ""
    normalized = _normalize_hostname(hostname)
    config = _RYBBIT_HOST_CONFIG.get(normalized)
    if config is None and _hostname_can_fallback_to_public_base_url(normalized):
        configured_base_host = _configured_public_base_hostname()
        config = _RYBBIT_HOST_CONFIG.get(configured_base_host)
    if not config:
        return ""
    env_name, fallback = config
    return str(os.getenv(env_name) or fallback).strip()


def clickrank_head_snippet(hostname: str | None) -> str:
    snippets: list[str] = []
    clickrank_site_id = clickrank_site_id_for_hostname(hostname)
    if clickrank_site_id:
        snippets.append(
            "<script>\n"
            'var clickRankAi = document.createElement("script");\n'
            f'clickRankAi.src = "https://js.clickrank.ai/seo/{clickrank_site_id}/script?" + new Date().getTime();\n'
            "clickRankAi.async = true;\n"
            "document.head.appendChild(clickRankAi);\n"
            "</script>"
        )
    rybbit_site_id = rybbit_site_id_for_hostname(hostname)
    if rybbit_site_id:
        snippets.append(
            f'<script src="https://app.rybbit.io/api/script.js" async defer data-site-id="{rybbit_site_id}"></script>'
        )
    return "\n".join(snippets)
