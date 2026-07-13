"""Fail-closed validation for server-side HTTP targets.

DNS is checked immediately before each request and redirect. urllib/requests do
not reliably expose the connected peer address, so callers still have a small
DNS-rebinding window until transports are replaced with a peer-pinning client.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable


class OutboundUrlRejected(ValueError):
    """Raised when an outbound HTTP target is not safe to contact."""


AddressResolver = Callable[..., list[tuple[object, ...]]]


@dataclass(frozen=True)
class ValidatedOutboundUrl:
    url: str
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...] = ()


def _canonical_hostname(value: str) -> str:
    hostname = str(value or "").strip().rstrip(".").lower()
    if not hostname or "%" in hostname:
        raise OutboundUrlRejected("outbound_url_hostname_invalid")
    try:
        return hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise OutboundUrlRejected("outbound_url_hostname_invalid") from exc


def _allowed_hostname(value: object) -> str:
    normalized = str(value or "").strip().lower().lstrip(".").rstrip(".")
    if not normalized:
        return ""
    if "://" in normalized:
        try:
            normalized = str(urllib.parse.urlsplit(normalized).hostname or "")
        except ValueError:
            return ""
    try:
        return _canonical_hostname(normalized)
    except OutboundUrlRejected:
        return ""


def hostname_matches_allowlist(hostname: object, allowed_hosts: Iterable[object]) -> bool:
    try:
        canonical = _canonical_hostname(str(hostname or ""))
    except OutboundUrlRejected:
        return False
    for value in allowed_hosts:
        allowed = _allowed_hostname(value)
        if allowed and (canonical == allowed or canonical.endswith(f".{allowed}")):
            return True
    return False


def _public_ip_address(value: object) -> str:
    try:
        address = ipaddress.ip_address(str(value or "").split("%", 1)[0])
    except ValueError as exc:
        raise OutboundUrlRejected("outbound_url_address_invalid") from exc
    if not address.is_global:
        raise OutboundUrlRejected("outbound_url_address_non_public")
    return address.compressed


def validate_http_url(
    value: object,
    *,
    allowed_hosts: Iterable[object] | None = None,
    resolve_dns: bool = False,
    resolver: AddressResolver = socket.getaddrinfo,
) -> ValidatedOutboundUrl:
    normalized = str(value or "").strip()
    if not normalized or "\\" in normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise OutboundUrlRejected("outbound_url_invalid")
    try:
        parsed = urllib.parse.urlsplit(normalized)
        scheme = str(parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise OutboundUrlRejected("outbound_url_scheme_invalid")
        if parsed.username is not None or parsed.password is not None:
            raise OutboundUrlRejected("outbound_url_userinfo_forbidden")
        hostname = _canonical_hostname(str(parsed.hostname or ""))
        explicit_port = parsed.port
    except OutboundUrlRejected:
        raise
    except (TypeError, ValueError) as exc:
        raise OutboundUrlRejected("outbound_url_invalid") from exc

    default_port = 443 if scheme == "https" else 80
    if explicit_port is not None and explicit_port != default_port:
        raise OutboundUrlRejected("outbound_url_port_forbidden")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise OutboundUrlRejected("outbound_url_address_non_public")
    if allowed_hosts is not None and not hostname_matches_allowlist(hostname, allowed_hosts):
        raise OutboundUrlRejected("outbound_url_host_not_allowed")

    resolved: list[str] = []
    try:
        literal_address = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal_address = None
    if literal_address is not None:
        resolved.append(_public_ip_address(literal_address))
    elif resolve_dns:
        try:
            rows = resolver(hostname, default_port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise OutboundUrlRejected("outbound_url_dns_failed") from exc
        for row in rows:
            try:
                sockaddr = row[4]
                address_text = sockaddr[0]
            except (IndexError, TypeError) as exc:
                raise OutboundUrlRejected("outbound_url_dns_invalid") from exc
            resolved.append(_public_ip_address(address_text))
        if not resolved:
            raise OutboundUrlRejected("outbound_url_dns_empty")

    return ValidatedOutboundUrl(
        url=normalized,
        hostname=hostname,
        port=default_port,
        resolved_addresses=tuple(dict.fromkeys(resolved)),
    )


def canonical_http_hostname(value: object) -> str:
    try:
        return validate_http_url(value).hostname
    except OutboundUrlRejected:
        return ""


def validate_outbound_url(
    value: object,
    *,
    allowed_hosts: Iterable[object] | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
) -> ValidatedOutboundUrl:
    return validate_http_url(
        value,
        allowed_hosts=allowed_hosts,
        resolve_dns=True,
        resolver=resolver,
    )


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        *,
        allowed_hosts: Iterable[object] | None,
        resolver: AddressResolver,
    ) -> None:
        super().__init__()
        self._allowed_hosts = tuple(allowed_hosts) if allowed_hosts is not None else None
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        redirected = urllib.parse.urljoin(str(req.full_url), str(newurl or ""))
        validate_outbound_url(
            redirected,
            allowed_hosts=self._allowed_hosts,
            resolver=self._resolver,
        )
        return super().redirect_request(req, fp, code, msg, headers, redirected)


def open_guarded_url(
    request: urllib.request.Request | str,
    *,
    timeout: float,
    allowed_hosts: Iterable[object] | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
):
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    validate_outbound_url(url, allowed_hosts=allowed_hosts, resolver=resolver)
    opener = urllib.request.build_opener(
        _GuardedRedirectHandler(allowed_hosts=allowed_hosts, resolver=resolver)
    )
    return opener.open(request, timeout=float(timeout))


def request_get_with_guarded_redirects(
    requester: Callable[..., object],
    url: str,
    *,
    allowed_hosts: Iterable[object] | None = None,
    resolver: AddressResolver = socket.getaddrinfo,
    max_redirects: int = 5,
    **kwargs: object,
):
    current_url = str(url or "").strip()
    for redirect_count in range(max(0, int(max_redirects)) + 1):
        validate_outbound_url(
            current_url,
            allowed_hosts=allowed_hosts,
            resolver=resolver,
        )
        response = requester(current_url, allow_redirects=False, **kwargs)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in {301, 302, 303, 307, 308}:
            return response
        headers = getattr(response, "headers", {}) or {}
        location = str(headers.get("location") or headers.get("Location") or "").strip()
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if not location:
            raise OutboundUrlRejected("outbound_url_redirect_missing")
        if redirect_count >= max_redirects:
            raise OutboundUrlRejected("outbound_url_redirect_limit")
        current_url = urllib.parse.urljoin(current_url, location)
    raise OutboundUrlRejected("outbound_url_redirect_limit")
