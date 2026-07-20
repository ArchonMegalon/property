from __future__ import annotations

from typing import Any

from app.services.public_analytics_consent import analytics_consent_granted


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
}

_PUBLIC_PREFIXES = (
    "/features/",
    "/guides/",
    "/markets/",
    "/blog/",
    "/compare/",
    "/channel/",
)


def heyy_live_chat_enabled() -> bool:
    return False


def _normalize_path(path: object) -> str:
    normalized = "/" + str(path or "").split("?", 1)[0].split("#", 1)[0].lstrip("/")
    return normalized.rstrip("/") or "/"


def _request_path(request: Any | None) -> str:
    if request is None:
        return "/"
    url = getattr(request, "url", None)
    return _normalize_path(getattr(url, "path", "/"))


def heyy_live_chat_route_allowed(path: object) -> bool:
    normalized = _normalize_path(path)
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in _PRIVATE_PATH_PREFIXES):
        return False
    if normalized in _PUBLIC_EXACT_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def heyy_live_chat_widget_id(*, hostname: str | None = None, path: object = "/") -> str:
    _ = hostname, path
    return ""


def heyy_live_chat_head_snippet(
    request: Any | None = None,
    *,
    hostname: str | None = None,
    path: object | None = None,
) -> str:
    if not analytics_consent_granted(request):
        return ""
    _ = hostname
    resolved_path = _request_path(request) if path is None else _normalize_path(path)
    _ = resolved_path
    return ""
