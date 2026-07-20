from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import urlparse


ANALYTICS_CONSENT_COOKIE = "propertyquarry_analytics_consent"
ANALYTICS_CONSENT_CSRF_COOKIE = "propertyquarry_analytics_consent_csrf"
ANALYTICS_CONSENT_VERSION = "v1"
ANALYTICS_CONSENT_GRANTED = f"granted-{ANALYTICS_CONSENT_VERSION}"
ANALYTICS_CONSENT_DENIED = f"denied-{ANALYTICS_CONSENT_VERSION}"
ANALYTICS_CONSENT_MAX_AGE_SECONDS = 180 * 24 * 60 * 60

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CONSENT_UI_PRIVATE_PATH_PREFIXES = (
    "/admin",
    "/api",
    "/app",
    "/auth",
    "/results",
    "/tours",
    "/v1",
    "/workspace-access",
)


def _headers(request: Any | None) -> Any:
    return getattr(request, "headers", {}) if request is not None else {}


def _cookies(request: Any | None) -> Any:
    return getattr(request, "cookies", {}) if request is not None else {}


def browser_privacy_signal_enabled(request: Any | None) -> bool:
    headers = _headers(request)
    global_privacy_control = str(headers.get("sec-gpc") or "").strip() == "1"
    do_not_track = str(headers.get("dnt") or "").strip().lower() in {"1", "yes"}
    return global_privacy_control or do_not_track


def analytics_consent_state(request: Any | None) -> str:
    if browser_privacy_signal_enabled(request):
        return "denied_by_browser_signal"
    value = str(_cookies(request).get(ANALYTICS_CONSENT_COOKIE) or "").strip()
    if value == ANALYTICS_CONSENT_GRANTED:
        return "granted"
    if value == ANALYTICS_CONSENT_DENIED:
        return "denied"
    return "unset"


def analytics_consent_granted(request: Any | None) -> bool:
    return analytics_consent_state(request) == "granted"


def _request_path(request: Any | None) -> str:
    if request is None:
        return ""
    url = getattr(request, "url", None)
    raw_path = str(getattr(url, "path", "") or getattr(request, "scope", {}).get("path", "")).strip()
    if not raw_path:
        return ""
    path = "/" + raw_path.lstrip("/")
    return path.rstrip("/") or "/"


def consent_ui_allowed(request: Any | None) -> bool:
    path = _request_path(request)
    if not path:
        return False
    return not any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _CONSENT_UI_PRIVATE_PATH_PREFIXES
    )


def consent_ui_context(
    request: Any | None,
    *,
    csrf_token: str = "",
) -> dict[str, object]:
    state = analytics_consent_state(request)
    browser_signal = browser_privacy_signal_enabled(request)
    path = _request_path(request) or "/"
    allowed = consent_ui_allowed(request)
    return {
        "state": state,
        "browser_signal": browser_signal,
        "can_grant": not browser_signal,
        "show_banner": allowed and state == "unset" and path != "/cookies",
        "show_settings": allowed and path == "/cookies",
        "csrf_token": csrf_token if valid_consent_csrf_token(csrf_token) else "",
        "return_to": path,
    }


def valid_consent_csrf_token(value: object) -> bool:
    return bool(_TOKEN_PATTERN.fullmatch(str(value or "").strip()))


def consent_csrf_token_for_request(request: Any | None) -> str:
    value = str(_cookies(request).get(ANALYTICS_CONSENT_CSRF_COOKIE) or "").strip()
    return value if valid_consent_csrf_token(value) else ""


def new_consent_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def request_uses_secure_scheme(request: Any | None) -> bool:
    headers = _headers(request)
    forwarded = [
        token.strip().lower()
        for token in str(headers.get("x-forwarded-proto") or "").split(",")
        if token.strip()
    ]
    if forwarded:
        return "https" in forwarded or "wss" in forwarded
    url = getattr(request, "url", None)
    return str(getattr(url, "scheme", "") or "").strip().lower() in {"https", "wss"}


def consent_cookie_kwargs(request: Any | None) -> dict[str, object]:
    return {
        "httponly": True,
        "secure": request_uses_secure_scheme(request),
        "samesite": "strict",
        "path": "/",
        "max_age": ANALYTICS_CONSENT_MAX_AGE_SECONDS,
    }


def consent_csrf_cookie_kwargs(request: Any | None) -> dict[str, object]:
    return {
        "httponly": True,
        "secure": request_uses_secure_scheme(request),
        "samesite": "strict",
        "path": "/",
    }


def _normalized_origin(value: object) -> tuple[str, str]:
    parsed = urlparse(str(value or "").strip())
    scheme = str(parsed.scheme or "").strip().lower()
    hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    if scheme not in {"http", "https"} or not hostname:
        return "", ""
    try:
        port = parsed.port
    except ValueError:
        return "", ""
    default_port = 443 if scheme == "https" else 80
    authority = hostname if port in {None, default_port} else f"{hostname}:{port}"
    return scheme, authority


def consent_request_is_same_origin(request: Any | None) -> bool:
    if request is None:
        return False
    headers = _headers(request)
    request_url = getattr(request, "url", None)
    request_scheme = str(getattr(request_url, "scheme", "") or "").strip().lower()
    forwarded_proto = [
        token.strip().lower()
        for token in str(headers.get("x-forwarded-proto") or "").split(",")
        if token.strip()
    ]
    if forwarded_proto:
        request_scheme = "https" if "https" in forwarded_proto else forwarded_proto[0]
    forwarded_host = str(headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
    request_host = forwarded_host or str(headers.get("host") or "").strip()
    expected = _normalized_origin(f"{request_scheme}://{request_host}")
    if not all(expected):
        return False

    origin = str(headers.get("origin") or "").strip()
    if origin:
        return _normalized_origin(origin) == expected
    referer = str(headers.get("referer") or "").strip()
    if referer:
        return _normalized_origin(referer) == expected
    return str(headers.get("sec-fetch-site") or "").strip().lower() in {
        "same-origin",
        "none",
    }
