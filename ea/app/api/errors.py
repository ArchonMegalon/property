from __future__ import annotations

import logging
import urllib.parse
import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

try:
    from psycopg import InterfaceError as PsycopgInterfaceError
    from psycopg import OperationalError as PsycopgOperationalError
except Exception:  # pragma: no cover - psycopg is optional in some test modes
    PsycopgInterfaceError = None
    PsycopgOperationalError = None


_LOG = logging.getLogger(__name__)

_BROWSER_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_BROWSER_MUTATION_PATH_PREFIXES = ("/app/", "/admin/")

_DEFAULT_BROWSER_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://app.rybbit.io https://js.clickrank.ai; "
        "connect-src 'self' https: wss:; "
        "frame-src 'self' https:; "
        "media-src 'self' blob: https:; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
}


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or uuid.uuid4())


def _error_payload(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    safe_details = jsonable_encoder(
        details,
        custom_encoder={
            Exception: lambda value: str(value),
            type(ValueError()): lambda value: str(value),
        },
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": str(code or "error"),
                "message": str(message or "request_failed"),
                "details": safe_details,
                "correlation_id": _correlation_id(request),
            }
        },
    )


def _code_from_http(status_code: int, detail: Any) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    return "request_failed"


def _browser_auth_redirect(request: Request, *, code: str) -> RedirectResponse | None:
    if str(code or "").strip() != "auth_required":
        return None
    method = str(request.method or "").upper()
    if method not in {"GET", "HEAD"}:
        return None
    path = str(request.url.path or "").strip()
    if not path.startswith("/app") and not path.startswith("/admin"):
        return None
    if path.startswith("/app/api") or path.startswith("/admin/api"):
        return None
    accept = str(request.headers.get("accept") or "").lower()
    sec_fetch_dest = str(request.headers.get("sec-fetch-dest") or "").lower()
    wants_html = "text/html" in accept or sec_fetch_dest == "document"
    if not wants_html:
        return None
    query = str(request.url.query or "").strip()
    return_to = f"{path}?{query}" if query else path
    target = "/sign-in?" + urllib.parse.urlencode({"return_to": return_to})
    response = RedirectResponse(target, status_code=303)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


def _request_is_https(request: Request) -> bool:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    tokens = {token.strip() for token in forwarded_proto.split(",") if token.strip()}
    if "https" in tokens or "wss" in tokens:
        return True
    if tokens:
        return False
    return str(getattr(request.url, "scheme", "") or "").strip().lower() in {"https", "wss"}


def _request_origin(request: Request) -> str:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    scheme_tokens = [token.strip() for token in forwarded_proto.split(",") if token.strip()]
    scheme = "https" if "https" in scheme_tokens or "wss" in scheme_tokens else ""
    if not scheme:
        scheme = scheme_tokens[0] if scheme_tokens else str(getattr(request.url, "scheme", "") or "http").strip().lower()
    if scheme == "wss":
        scheme = "https"
    forwarded_host = str(request.headers.get("x-forwarded-host") or "").strip()
    host = forwarded_host.split(",", 1)[0].strip() if forwarded_host else str(request.headers.get("host") or request.url.netloc or "").strip()
    return f"{scheme}://{host}".rstrip("/")


def _origin_of_url(raw_value: str) -> str:
    normalized = str(raw_value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urllib.parse.urlsplit(normalized)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")


def _browser_mutation_request_is_cross_site(request: Request) -> bool:
    method = str(request.method or "").upper()
    if method not in _BROWSER_MUTATION_METHODS:
        return False
    path = str(request.url.path or "").strip()
    if not any(path.startswith(prefix) for prefix in _BROWSER_MUTATION_PATH_PREFIXES):
        return False
    expected = _request_origin(request).lower()
    origin = _origin_of_url(str(request.headers.get("origin") or ""))
    if origin:
        return origin != expected
    referer = _origin_of_url(str(request.headers.get("referer") or ""))
    if referer:
        return referer != expected
    return False


def _apply_default_browser_security_headers(request: Request, response: Any) -> None:
    for name, value in _DEFAULT_BROWSER_SECURITY_HEADERS.items():
        if name not in response.headers:
            response.headers[name] = value
    if _request_is_https(request) and "Strict-Transport-Security" not in response.headers:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"


def install_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        if _browser_mutation_request_is_cross_site(request):
            response = _error_payload(
                request=request,
                status_code=403,
                code="cross_site_browser_mutation",
                message="cross-site browser mutation blocked",
                details="unsafe browser requests must originate from the same site",
            )
            response.headers["x-correlation-id"] = _correlation_id(request)
            _apply_default_browser_security_headers(request, response)
            return response
        response = await call_next(request)
        response.headers["x-correlation-id"] = _correlation_id(request)
        _apply_default_browser_security_headers(request, response)
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
        code = _code_from_http(exc.status_code, exc.detail)
        redirect = _browser_auth_redirect(request, code=code)
        if redirect is not None:
            return redirect
        message = str(exc.detail or code)
        return _error_payload(
            request=request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details=exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return _error_payload(
            request=request,
            status_code=422,
            code="validation_error",
            message="request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(PermissionError)
    async def permission_exception_handler(request: Request, exc: PermissionError):  # type: ignore[no-untyped-def]
        detail = str(exc or "forbidden").strip() or "forbidden"
        return _error_payload(
            request=request,
            status_code=403,
            code=_code_from_http(403, detail),
            message=detail,
            details=detail,
        )

    async def _database_unavailable_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        correlation_id = _correlation_id(request)
        _LOG.warning(
            "database_unavailable correlation_id=%s error_type=%s detail=%s",
            correlation_id,
            exc.__class__.__name__,
            str(exc or "").strip(),
        )
        response = _error_payload(
            request=request,
            status_code=503,
            code="database_unavailable",
            message="temporary service interruption",
            details="database_temporarily_unavailable",
        )
        response.headers["Retry-After"] = "5"
        return response

    if PsycopgOperationalError is not None:
        app.add_exception_handler(PsycopgOperationalError, _database_unavailable_handler)
    if PsycopgInterfaceError is not None:
        app.add_exception_handler(PsycopgInterfaceError, _database_unavailable_handler)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        return _error_payload(
            request=request,
            status_code=500,
            code="internal_error",
            message="internal server error",
            details=exc.__class__.__name__,
        )
