from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse


_BLOCKED_HOST_SUFFIXES = (
    ".home",
    ".internal",
    ".lan",
    ".local",
    ".localhost",
)


def _host_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    normalized = str(host or "").strip().casefold().rstrip(".")
    if not normalized:
        return None
    try:
        return ipaddress.ip_address(normalized)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(normalized))
    except (OSError, ValueError):
        return None


def public_http_url_is_safe(value: object) -> bool:
    """Accept only absolute HTTP(S) URLs that cannot directly name a private host."""

    url = str(value or "").strip()
    if not url:
        return False
    if "\\" in url or any(ord(character) < 0x21 or ord(character) == 0x7F for character in url):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        _ = parsed.port
        raw_host = str(parsed.hostname or "").strip()
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not raw_host
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw_host):
        return False
    try:
        decoded_host = urllib.parse.unquote(raw_host, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    if (
        "%" in decoded_host
        or "\\" in decoded_host
        or any(character in decoded_host for character in "/@?#")
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in decoded_host)
    ):
        return False
    decoded_host = decoded_host.casefold().rstrip(".")
    literal = _host_ip_literal(decoded_host)
    if literal is not None:
        return literal.is_global
    try:
        host = decoded_host.encode("idna").decode("ascii").casefold().rstrip(".")
    except (UnicodeError, ValueError):
        return False
    if (
        not host
        or "." not in host
        or len(host) > 253
        or any(not label or len(label) > 63 for label in host.split("."))
    ):
        return False
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False
    literal = _host_ip_literal(host)
    if literal is not None and not literal.is_global:
        return False
    return True


def safe_public_http_url(value: object) -> str:
    url = str(value or "").strip()
    return url if public_http_url_is_safe(url) else ""
