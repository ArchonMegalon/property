from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any, Iterable, Mapping


BRILLIANT_DIRECTORIES_PROVIDER_KEY = "brilliant_directories"
BRILLIANT_DIRECTORIES_CONTRACT_NAME = "propertyquarry.brilliant_directories_projection.v1"
BRILLIANT_DIRECTORIES_VERIFICATION_CONTRACT_NAME = "propertyquarry.brilliant_directories_provider_verification.v1"
BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS = 300
BRILLIANT_DIRECTORIES_WHITE_LABEL_BLOCKLIST = ("brilliantdirectories", "brilliant-directories")
BRILLIANT_DIRECTORIES_DNS_OVER_HTTPS_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)
BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_LENGTH = 32
BRILLIANT_DIRECTORIES_MEMBER_LOGIN_ALLOWED_QUERY_KEYS = frozenset(
    {
        "property[]",
        "property_value[]",
        "limit",
    }
)
BRILLIANT_DIRECTORIES_MEMBER_CREATE_ALLOWED_FIELDS = frozenset(
    {
        "email",
        "password",
        "token",
        "first_name",
        "last_name",
        "active",
        "subscription_id",
    }
)
BRILLIANT_DIRECTORIES_MEMBER_UPDATE_ALLOWED_FIELDS = frozenset(
    {
        "user_id",
        "token",
        "first_name",
        "last_name",
        "active",
    }
)
BRILLIANT_DIRECTORIES_PLACEHOLDER_PRICING_TOKENS = (
    ("choose a plan, sign up, and you", "stock_plan_hero"),
    ("membership plan benefit", "stock_membership_benefit"),
    ("this is a frequently asked question", "stock_faq_copy"),
    ("click to join", "stock_cta"),
)


def _dns_query_answers(name: str, qtype: str) -> list[dict[str, object]]:
    normalized_name = str(name or "").strip().lower().rstrip(".")
    if not normalized_name:
        return []
    answers: list[dict[str, object]] = []
    for endpoint in BRILLIANT_DIRECTORIES_DNS_OVER_HTTPS_ENDPOINTS:
        query = urllib.parse.urlencode({"name": normalized_name, "type": qtype})
        request = urllib.request.Request(
            f"{endpoint}?{query}",
            headers={
                "Accept": "application/dns-json",
                "User-Agent": "PropertyQuarryBillingDnsVerifier/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            continue
        for row in payload.get("Answer") or []:
            if not isinstance(row, dict):
                continue
            answer_name = str(row.get("name") or "").strip().lower().rstrip(".")
            answer_data = str(row.get("data") or "").strip().lower().rstrip(".")
            answer_type = int(row.get("type") or 0)
            if answer_name == normalized_name and answer_data:
                answers.append({"type": answer_type, "data": answer_data, "endpoint": endpoint})
    return answers


def _dns_over_https_addresses(name: str) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for qtype in ("A", "AAAA"):
        for row in _dns_query_answers(name, qtype):
            if int(row.get("type") or 0) not in {1, 28}:
                continue
            data = str(row.get("data") or "").strip()
            if not data:
                continue
            norm = data.rstrip(".").lower()
            if norm in seen:
                continue
            try:
                ip_address(norm)
            except Exception:
                continue
            seen.add(norm)
            addresses.append(norm)
    return addresses


def _resolve_host_with_public_dns(name: str) -> list[str]:
    addresses: list[str] = []
    answers = _dns_query_answers(name, "CNAME")
    cname_answers = [row for row in answers if int(row.get("type") or 0) == 5]
    for row in cname_answers:
        target = str(row.get("data") or "").strip().lower().rstrip(".")
        addresses.extend(_dns_over_https_addresses(target))
    addresses.extend(_dns_over_https_addresses(name))
    return [address for address in addresses if address]


def _parse_http_response_bytes(payload: bytes) -> tuple[int, dict[str, str], bytes]:
    header_end = payload.find(b"\r\n\r\n")
    if header_end < 0:
        return 0, {}, b""
    head = payload[:header_end].decode("utf-8", errors="replace").split("\r\n")
    status_line = head[0].strip() if head else ""
    pieces = status_line.split()
    status_code = int(pieces[1]) if len(pieces) >= 2 and pieces[1].isdigit() else 0
    headers: dict[str, str] = {}
    for raw_line in head[1:]:
        if ":" not in raw_line:
            continue
        name, value = raw_line.split(":", 1)
        headers[name.strip()] = value.strip()
    return status_code, headers, payload[header_end + 4 :]


def _is_cloudflare_transport_error(body: str) -> bool:
    normalized = body.replace("\n", " ").replace("\r", " ").lower()
    return "error code:" in normalized


def _cloudflare_error_code(body: str) -> str:
    match = re.search(r"error code:\s*(\d{3,4})", str(body or ""), flags=re.IGNORECASE)
    return str(match.group(1) or "").strip() if match else ""


def _is_login_probe(redirect_location: str, body: str) -> bool:
    login_target = redirect_location.lower()
    body_lower = body.lower()
    return (
        "/login" in login_target
        or "login_direct_url" in login_target
        or ("<title" in body_lower and "login" in body_lower and ("email" in body_lower or "password" in body_lower))
    )


def _http_request_via_public_address(handoff_url: str, *, timeout_seconds: float, public_addresses: list[str]) -> dict[str, object]:
    parsed = urllib.parse.urlparse(handoff_url)
    host = str(parsed.hostname or "").strip().lower()
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    request_headers = {
        "Accept": "text/html,application/json,*/*",
        "User-Agent": "PropertyQuarryBillingHandoffVerifier/1.0",
        "Host": host,
        "Connection": "close",
    }
    body = ""
    for address in public_addresses:
        try:
            with socket.create_connection((address, 443), timeout=timeout_seconds) as raw_socket:
                context = ssl.create_default_context()
                with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                    request_bytes = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"Accept: {request_headers['Accept']}\r\n"
                        f"User-Agent: {request_headers['User-Agent']}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("utf-8")
                    tls_socket.sendall(request_bytes)
                    chunks: list[bytes] = []
                    while True:
                        piece = tls_socket.recv(16_384)
                        if not piece:
                            break
                        chunks.append(piece)
        except Exception as exc:
            continue
        response_bytes = b"".join(chunks)
        status_code, headers, raw_body = _parse_http_response_bytes(response_bytes)
        if status_code <= 0:
            continue
        body = raw_body[:16_384].decode("utf-8", errors="replace").lower()
        redirect_location = str(headers.get("Location") or "")
        requires_login = _is_login_probe(redirect_location or path, body)
        is_cf_block = _is_cloudflare_transport_error(body)
        cf_error_code = _cloudflare_error_code(body) if is_cf_block else ""
        return {
            "status_code": status_code,
            "redirect_location": redirect_location,
            "requires_login": requires_login,
            "cloudflare_transport_error": is_cf_block,
            "cloudflare_error_code": cf_error_code,
            "body": body,
            "used_public_address": address,
            "raw_host": host,
            "raw_status_line_address": address,
        }
    return {
        "status_code": 0,
        "redirect_location": "",
            "requires_login": True,
            "cloudflare_transport_error": False,
            "cloudflare_error_code": "",
            "body": body,
    }


def _billing_handoff_probe_error(*, status_code: int, requires_login: bool, cloudflare_error_code: str = "") -> str:
    if requires_login:
        return "billing_handoff_requires_separate_login"
    if cloudflare_error_code:
        return f"billing_handoff_cloudflare_error_{cloudflare_error_code}"
    if status_code > 0:
        return f"billing_handoff_http_{status_code}"
    return "billing_handoff_probe_failed"


def _billing_handoff_allowed_redirect_hosts() -> tuple[str, ...]:
    return _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or "")


def _billing_handoff_follow_redirect_url(current_url: str, redirect_location: str) -> str:
    next_url = urllib.parse.urljoin(str(current_url or "").strip(), str(redirect_location or "").strip())
    parsed = urllib.parse.urlparse(next_url)
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme != "https" or not host:
        return ""
    allowed_hosts = _billing_handoff_allowed_redirect_hosts()
    current_host = str(urllib.parse.urlparse(str(current_url or "").strip()).hostname or "").strip().lower()
    if host == current_host:
        return next_url
    if allowed_hosts and host in allowed_hosts:
        return next_url
    return ""

BRILLIANT_DIRECTORIES_PUBLIC_PROFILE_FIELDS = frozenset(
    {
        "profile_id",
        "display_name",
        "category",
        "public_url",
        "city",
        "region",
        "country_code",
        "summary",
        "tags",
    }
)

BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "email",
    "phone",
    "mobile",
    "whatsapp",
    "telegram",
    "street",
    "address",
    "lat",
    "lng",
    "geo",
    "payment",
    "billing",
    "invoice",
    "property_fact",
    "listing_truth",
    "ranking",
    "score",
    "fit_score",
    "threshold",
    "min_match",
    "max_match",
    "search_run",
    "preference",
    "medical",
    "family",
    "child",
    "commute",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def brilliant_directories_enabled() -> bool:
    return (
        _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED")
        and _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED")
        and not _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED")
    )


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in str(raw or "").split(",") if item.strip())


def _split_csv_values(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())


def _safe_public_url(raw_url: str, *, allowed_hosts: tuple[str, ...]) -> str:
    raw = str(raw_url or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https":
        return ""
    host = str(parsed.hostname or "").strip().lower()
    if not host or parsed.username or parsed.password:
        return ""
    if allowed_hosts and host not in allowed_hosts:
        return ""
    return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path.rstrip("/") or "/", "", parsed.query, "")).strip()


def _safe_white_label_handoff_url(raw_url: str, *, allowed_hosts: tuple[str, ...]) -> str:
    normalized = _safe_public_url(raw_url, allowed_hosts=allowed_hosts)
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    host = str(parsed.hostname or "").strip().lower()
    if any(marker in host for marker in BRILLIANT_DIRECTORIES_WHITE_LABEL_BLOCKLIST):
        return ""
    return normalized


def _principal_email_hint(principal_id: str) -> str:
    normalized = str(principal_id or "").strip()
    if normalized.startswith("cf-email:"):
        candidate = normalized.partition(":")[2].strip().lower()
        if "@" in candidate:
            return candidate
    return ""


def _display_name_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    parts = [part for part in re.split(r"[._+-]+", local) if part]
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def _sha256_short(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class BrilliantDirectoriesApiError(RuntimeError):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class BrilliantDirectoriesConfig:
    enabled: bool
    base_url: str
    host: str
    allowed_hosts: tuple[str, ...]
    api_key_header: str
    api_key: str = field(default="", repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.host)

    @property
    def api_key_fingerprint(self) -> str:
        return _sha256_short(self.api_key)

    def as_receipt(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "base_url": self.base_url,
            "host": self.host,
            "allowed_hosts": list(self.allowed_hosts),
            "api_key_header": self.api_key_header,
            "api_key_fingerprint": self.api_key_fingerprint,
        }


@dataclass(frozen=True)
class BrilliantDirectoriesDirectoryProfile:
    profile_id: str
    display_name: str
    category: str = ""
    public_url: str = ""
    city: str = ""
    region: str = ""
    country_code: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
        }
        for key in ("category", "public_url", "city", "region", "country_code", "summary"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class BrilliantDirectoriesProjectionPacket:
    purpose: str
    projection_mode: str
    profiles: tuple[BrilliantDirectoriesDirectoryProfile, ...]
    generated_at: str = field(default_factory=_utc_now_iso)

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_name": BRILLIANT_DIRECTORIES_CONTRACT_NAME,
            "provider": BRILLIANT_DIRECTORIES_PROVIDER_KEY,
            "purpose": self.purpose,
            "projection_mode": self.projection_mode,
            "generated_at": self.generated_at,
            "profile_count": len(self.profiles),
            "profiles": [profile.as_dict() for profile in self.profiles],
            "allowed_profile_fields": sorted(BRILLIANT_DIRECTORIES_PUBLIC_PROFILE_FIELDS),
            "forbidden_key_markers": list(BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS),
            "propertyquarry_source_of_truth": True,
            "publication_allowed": False,
            "direct_property_truth_mutation_allowed": False,
        }


@dataclass(frozen=True)
class BrilliantDirectoriesApiRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None

    def redacted_receipt(self) -> dict[str, object]:
        redacted_headers = dict(self.headers)
        for key in tuple(redacted_headers):
            if key.lower() in {"authorization", "x-api-key", "api-key"} or "key" in key.lower():
                redacted_headers[key] = "[redacted]"
        return {
            "method": self.method,
            "url": self.url,
            "headers": redacted_headers,
            "body_sha256": hashlib.sha256(self.body or b"").hexdigest() if self.body is not None else "",
        }


class _BrilliantDirectoriesNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "brilliant_directories_redirect_blocked", headers, fp)


def load_brilliant_directories_config() -> BrilliantDirectoriesConfig:
    enabled = brilliant_directories_enabled()
    api_key_header = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER") or "X-Api-Key").strip()
    if not api_key_header:
        api_key_header = "X-Api-Key"
    if not enabled:
        return BrilliantDirectoriesConfig(
            enabled=False,
            base_url="",
            host="",
            allowed_hosts=_split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or ""),
            api_key_header=api_key_header,
            api_key="",
        )

    base_url = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL") or "").strip().rstrip("/")
    api_key = str(
        os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY")
        or os.getenv("BRILLIANT_DIRECTORIES_API_KEY")
        or ""
    ).strip()
    allowed_hosts = _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or "")
    if not base_url:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_base_url_missing")
    if not api_key:
        raise BrilliantDirectoriesApiError(503, "brilliant_directories_api_key_missing")
    if not allowed_hosts:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_allowed_hosts_missing")
    parsed = urllib.parse.urlparse(base_url)
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme != "https":
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_https_required")
    if parsed.username or parsed.password:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_base_url_credentials_forbidden")
    if not host or host not in allowed_hosts:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_host_not_allowed")
    normalized = urllib.parse.urlunparse(("https", parsed.netloc, parsed.path.rstrip("/"), "", "", "")).rstrip("/")
    return BrilliantDirectoriesConfig(
        enabled=True,
        base_url=normalized,
        host=host,
        allowed_hosts=allowed_hosts,
        api_key_header=api_key_header,
        api_key=api_key,
    )


def brilliant_directories_billing_handoff_url(config: BrilliantDirectoriesConfig | None = None) -> str:
    urls = brilliant_directories_billing_handoff_urls(config)
    return urls[0] if urls else ""


def brilliant_directories_billing_handoff_urls(config: BrilliantDirectoriesConfig | None = None) -> tuple[str, ...]:
    resolved_config = config
    allowed_hosts: tuple[str, ...] = ()
    if resolved_config is None:
        try:
            resolved_config = load_brilliant_directories_config()
        except BrilliantDirectoriesApiError:
            resolved_config = None
            allowed_hosts = _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or "")
    if resolved_config is not None:
        allowed_hosts = tuple(resolved_config.allowed_hosts)
    if not allowed_hosts:
        return ()

    urls: list[str] = []

    def add_candidate(raw_url: str) -> None:
        normalized = _safe_white_label_handoff_url(raw_url, allowed_hosts=allowed_hosts)
        if normalized and normalized not in urls:
            urls.append(normalized)

    add_candidate(str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL") or "").strip())
    for raw_url in _split_csv_values(
        str(
            os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_FALLBACK_URLS")
            or os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_FALLBACK_URL")
            or ""
        ).strip()
    ):
        add_candidate(raw_url)
    return tuple(urls)


def brilliant_directories_billing_sso_bridge_enabled() -> bool:
    return _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_ENABLED")


def brilliant_directories_member_login_token_enabled() -> bool:
    return _env_flag("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_ENABLED")


def brilliant_directories_billing_sso_bridge_secret() -> str:
    return str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET") or "").strip()


def brilliant_directories_member_login_token_secret() -> str:
    return str(
        os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET")
        or brilliant_directories_billing_sso_bridge_secret()
        or ""
    ).strip()


def brilliant_directories_member_login_subscription_id() -> str:
    raw = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_SUBSCRIPTION_ID") or "").strip()
    return raw if re.fullmatch(r"[0-9]{1,12}", raw) else ""


def _billing_sso_bridge_allowed_hosts(
    config: BrilliantDirectoriesConfig | None = None,
) -> tuple[str, ...]:
    explicit_hosts = _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_ALLOWED_HOSTS") or "")
    if explicit_hosts:
        return explicit_hosts
    resolved_config = config
    if resolved_config is None:
        try:
            resolved_config = load_brilliant_directories_config()
        except BrilliantDirectoriesApiError:
            resolved_config = None
    if resolved_config is not None and resolved_config.allowed_hosts:
        return tuple(resolved_config.allowed_hosts)
    return _split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or "")


def brilliant_directories_billing_sso_bridge_url(
    config: BrilliantDirectoriesConfig | None = None,
) -> str:
    allowed_hosts = _billing_sso_bridge_allowed_hosts(config)
    if not allowed_hosts:
        return ""
    raw_url = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL") or "").strip()
    return _safe_public_url(raw_url, allowed_hosts=allowed_hosts)


def _bridge_host_resolution_receipt(
    bridge_url: str,
    *,
    resolver: object | None = None,
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(bridge_url)
    host = str(parsed.hostname or "").strip().lower()
    if not bridge_url:
        return {
            "url": "",
            "host": "",
            "host_resolves": False,
            "error": "billing_sso_bridge_url_missing",
            "next_action": "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL to an HTTPS allowlisted bridge endpoint",
        }
    if not host:
        return {
            "url": bridge_url,
            "host": "",
            "host_resolves": False,
            "error": "billing_sso_bridge_host_missing",
            "next_action": "replace PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL with an HTTPS URL containing a host",
        }
    resolve = resolver or socket.getaddrinfo
    try:
        resolve(host, 443)
        return {
            "url": bridge_url,
            "host": host,
            "host_resolves": True,
            "error": "",
            "next_action": "keep the bridge endpoint on an allowlisted HTTPS host and verify that it exchanges the signed token for a billing session",
            "resolution_source": "local_resolver",
        }
    except OSError as exc:
        local_error = f"billing_sso_bridge_host_unresolved:{exc.__class__.__name__}"
        public_dns = {} if resolver is not None else _public_dns_handoff_receipt(host=host, dns_target="")
        host_resolves = bool(public_dns.get("host_resolves"))
        return {
            "url": bridge_url,
            "host": host,
            "host_resolves": host_resolves,
            "error": "" if host_resolves else local_error,
            "next_action": (
                "keep the bridge endpoint on an allowlisted HTTPS host and verify that it exchanges the signed token for a billing session"
                if host_resolves
                else f"create DNS for {host} before enabling the Brilliant Directories billing bridge"
            ),
            "resolution_source": "public_dns_over_https" if host_resolves else "local_resolver",
            "local_resolver_error": local_error,
            "public_dns": public_dns,
        }


def build_brilliant_directories_billing_sso_bridge_receipt(
    *,
    resolver: object | None = None,
    config: BrilliantDirectoriesConfig | None = None,
    verify_exchange: bool = False,
    exchange_opener: object | None = None,
) -> dict[str, object]:
    enabled = brilliant_directories_billing_sso_bridge_enabled()
    allowed_hosts = _billing_sso_bridge_allowed_hosts(config)
    bridge_url = brilliant_directories_billing_sso_bridge_url(config)
    secret = brilliant_directories_billing_sso_bridge_secret()
    secret_configured = bool(secret)
    if not enabled:
        return {
            "enabled": False,
            "configured": False,
            "ready": False,
            "url": bridge_url,
            "host": str(urllib.parse.urlparse(bridge_url).hostname or "").strip().lower(),
            "host_resolves": False,
            "allowed_hosts": list(allowed_hosts),
            "secret_configured": secret_configured,
            "secret_fingerprint": _sha256_short(secret),
            "token_ttl_seconds": BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS,
            "error": "",
            "next_action": "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_ENABLED=1 and configure the bridge URL and secret before using a billing-session bridge",
        }
    if not allowed_hosts:
        return {
            "enabled": True,
            "configured": False,
            "ready": False,
            "url": bridge_url,
            "host": str(urllib.parse.urlparse(bridge_url).hostname or "").strip().lower(),
            "host_resolves": False,
            "allowed_hosts": [],
            "secret_configured": secret_configured,
            "secret_fingerprint": _sha256_short(secret),
            "token_ttl_seconds": BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS,
            "error": "billing_sso_bridge_allowed_hosts_missing",
            "next_action": "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_ALLOWED_HOSTS or reuse PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS",
        }
    if not bridge_url:
        raw_url = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL") or "").strip()
        return {
            "enabled": True,
            "configured": False,
            "ready": False,
            "url": raw_url,
            "host": str(urllib.parse.urlparse(raw_url).hostname or "").strip().lower(),
            "host_resolves": False,
            "allowed_hosts": list(allowed_hosts),
            "secret_configured": secret_configured,
            "secret_fingerprint": _sha256_short(secret),
            "token_ttl_seconds": BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS,
            "error": "billing_sso_bridge_url_invalid",
            "next_action": "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_URL to an HTTPS URL on an allowlisted host",
        }
    resolution = _bridge_host_resolution_receipt(bridge_url, resolver=resolver)
    error = str(resolution.get("error") or "").strip()
    if not secret_configured and not error:
        error = "billing_sso_bridge_secret_missing"
    config_ready = bool(secret_configured and resolution.get("host_resolves") and not error)
    exchange_probe: dict[str, object] = {}
    if config_ready and verify_exchange:
        exchange_probe = _billing_sso_bridge_exchange_probe(
            bridge_url,
            opener=exchange_opener,
        )
        if exchange_probe.get("usable") is not True:
            error = str(exchange_probe.get("error") or "billing_sso_bridge_exchange_unusable").strip()
    ready = bool(config_ready and not error)
    return {
        "enabled": True,
        "configured": True,
        "ready": ready,
        "config_ready": config_ready,
        "url": bridge_url,
        "host": str(resolution.get("host") or "").strip().lower(),
        "host_resolves": bool(resolution.get("host_resolves")),
        "allowed_hosts": list(allowed_hosts),
        "secret_configured": secret_configured,
        "secret_fingerprint": _sha256_short(secret),
        "token_ttl_seconds": BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS,
        "error": error,
        "next_action": (
            "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET before enabling the billing-session bridge"
            if error == "billing_sso_bridge_secret_missing"
            else (
                "configure the Brilliant Directories SSO endpoint to accept the PropertyQuarry signed token and create a "
                "billing session, or switch on the member-login token lane by setting "
                "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY, PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER, "
                "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_ENABLED=1, and "
                "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET; the current bridge falls through to the vendor login page"
                if error == "billing_sso_bridge_exchange_requires_login"
                else str(resolution.get("next_action") or "")
            )
        ),
        "resolution_source": resolution.get("resolution_source"),
        "local_resolver_error": resolution.get("local_resolver_error"),
        "public_dns": resolution.get("public_dns"),
        "exchange_checked": bool(verify_exchange),
        "exchange_usable": exchange_probe.get("usable") if verify_exchange else None,
        "exchange_probe": exchange_probe,
    }


def _billing_sso_bridge_exchange_probe(
    bridge_url: str,
    *,
    opener: object | None = None,
) -> dict[str, object]:
    if not bridge_url:
        return {
            "checked": False,
            "usable": False,
            "error": "billing_sso_bridge_url_missing",
        }
    try:
        launch_url = build_brilliant_directories_billing_sso_bridge_launch_url(
            principal_id="billing-bridge-probe@propertyquarry.local",
            access_email="billing-bridge-probe@propertyquarry.local",
            return_to="/app/account",
            bridge_url=bridge_url,
        )
    except RuntimeError as exc:
        return {
            "checked": False,
            "usable": False,
            "error": str(exc),
        }
    request = urllib.request.Request(
        launch_url,
        headers={
            "Accept": "text/html,application/json,*/*",
            "User-Agent": "PropertyQuarryBillingBridgeVerifier/1.0",
        },
    )
    http_opener = opener or urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    try:
        response = http_opener.open(request, timeout=10.0)
        status_code = int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)
        final_url = str(getattr(response, "url", "") or launch_url)
        body = response.read(16_384).decode("utf-8", errors="replace").lower()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code or 0)
        final_url = str(getattr(exc, "url", "") or launch_url)
        body = exc.read(16_384).decode("utf-8", errors="replace").lower()
    except Exception as exc:
        return {
            "checked": True,
            "usable": False,
            "status_code": 0,
            "final_host": str(urllib.parse.urlparse(bridge_url).hostname or "").strip().lower(),
            "final_path": "",
            "redirected_to_login": False,
            "error": f"billing_sso_bridge_exchange_probe_failed:{type(exc).__name__}",
        }
    parsed_final = urllib.parse.urlparse(final_url)
    final_path = parsed_final.path or "/"
    redirected_to_login = _is_login_probe(final_url, body)
    usable = bool(status_code and 200 <= status_code < 400 and not redirected_to_login)
    return {
        "checked": True,
        "usable": usable,
        "status_code": status_code,
        "final_host": str(parsed_final.hostname or "").strip().lower(),
        "final_path": final_path,
        "redirected_to_login": redirected_to_login,
        "error": "" if usable else ("billing_sso_bridge_exchange_requires_login" if redirected_to_login else _billing_handoff_probe_error(status_code=status_code, requires_login=False)),
    }


def build_brilliant_directories_member_login_token_receipt(
    *,
    config: BrilliantDirectoriesConfig | None = None,
) -> dict[str, object]:
    enabled = brilliant_directories_member_login_token_enabled()
    resolved_config = config
    config_error = ""
    if resolved_config is None:
        try:
            resolved_config = load_brilliant_directories_config()
        except BrilliantDirectoriesApiError as exc:
            config_error = str(exc)
            resolved_config = BrilliantDirectoriesConfig(
                enabled=False,
                base_url="",
                host="",
                allowed_hosts=_split_csv(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS") or ""),
                api_key_header=str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER") or "X-Api-Key").strip()
                or "X-Api-Key",
                api_key="",
            )
    handoff_url = brilliant_directories_billing_handoff_url(resolved_config)
    secret = brilliant_directories_member_login_token_secret()
    if not enabled:
        return {
            "enabled": False,
            "configured": False,
            "ready": False,
            "url": handoff_url,
            "host": str(urllib.parse.urlparse(handoff_url).hostname or "").strip().lower(),
            "secret_configured": bool(secret),
            "secret_fingerprint": _sha256_short(secret),
            "error": "",
            "next_action": (
                "generate a Brilliant Directories API key in the admin backend, confirm the member-login token account lane, "
                "then set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY, PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER, "
                "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_ENABLED=1, and "
                "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET before using a member-session handoff"
            ),
        }
    error = ""
    if config_error:
        error = config_error
    elif not resolved_config.configured:
        error = "brilliant_directories_not_configured"
    elif not handoff_url:
        error = "billing_handoff_url_missing"
    elif not secret:
        error = "billing_member_login_token_secret_missing"
    return {
        "enabled": True,
        "configured": not bool(error),
        "ready": not bool(error),
        "url": handoff_url,
        "host": str(urllib.parse.urlparse(handoff_url).hostname or "").strip().lower(),
        "secret_configured": bool(secret),
        "secret_fingerprint": _sha256_short(secret),
        "error": error,
        "next_action": (
            "generate a Brilliant Directories API key in the admin backend and set "
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY, PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER, "
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS, and PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL "
            "before using a member-session handoff"
            if error in {"brilliant_directories_not_configured", "brilliant_directories_base_url_missing", "brilliant_directories_api_key_missing", "brilliant_directories_allowed_hosts_missing", "billing_handoff_url_missing"}
            else (
                "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET or PROPERTYQUARRY_BRILLIANT_DIRECTORIES_SSO_BRIDGE_SECRET before using a member-session handoff"
                if error == "billing_member_login_token_secret_missing"
                else ""
            )
        ),
    }


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _propertyquarry_public_base_url() -> str:
    raw = (
        os.getenv("PROPERTY_PUBLIC_BASE_URL")
        or os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL")
        or "https://propertyquarry.com"
    )
    parsed = urllib.parse.urlparse(str(raw or "").strip())
    if parsed.scheme == "https" and parsed.netloc:
        return urllib.parse.urlunparse(("https", parsed.netloc, "", "", "", "")).rstrip("/")
    return "https://propertyquarry.com"


def _safe_bridge_return_to(return_to: str, bridge_url: str = "", public_base_url: str = "") -> str:
    default_value = "/app/account"
    raw = str(return_to or "").strip()
    if not raw:
        return default_value
    parsed = urllib.parse.urlparse(raw)
    property_origin = _propertyquarry_public_base_url()
    if public_base_url:
        parsed_property_origin = urllib.parse.urlparse(str(public_base_url or "").strip())
        if parsed_property_origin.scheme == "https" and parsed_property_origin.netloc:
            property_origin = urllib.parse.urlunparse(
                ("https", parsed_property_origin.netloc, "", "", "", "")
            ).rstrip("/")
    if parsed.scheme or parsed.netloc:
        property_host = str(urllib.parse.urlparse(property_origin).hostname or "").strip().lower()
        if parsed.scheme != "https" or str(parsed.hostname or "").strip().lower() != property_host:
            return default_value
        if not parsed.path.startswith("/"):
            return default_value
        return urllib.parse.urlunparse(("", "", parsed.path, "", parsed.query, ""))
    path = parsed.path or default_value
    if not path.startswith("/") or path.startswith("//"):
        return default_value
    return urllib.parse.urlunparse(("", "", path, "", parsed.query, ""))


def _billing_sso_bridge_payload(
    *,
    principal_id: str,
    access_email: str = "",
    return_to: str = "",
    issued_at: int | None = None,
    bridge_url: str = "",
    public_base_url: str = "",
) -> dict[str, object]:
    issued_epoch = int(issued_at if issued_at is not None else time.time())
    normalized_public_base_url = _propertyquarry_public_base_url()
    if public_base_url:
        parsed = urllib.parse.urlparse(str(public_base_url or "").strip())
        if parsed.scheme == "https" and parsed.netloc:
            normalized_public_base_url = urllib.parse.urlunparse(("https", parsed.netloc, "", "", "", "")).rstrip("/")
    return {
        "aud": "propertyquarry.billing_sso_bridge",
        "iss": "propertyquarry.com",
        "principal_id": str(principal_id or "").strip(),
        "access_email": str(access_email or "").strip().lower(),
        "return_to_origin": normalized_public_base_url,
        "return_to": _safe_bridge_return_to(return_to, bridge_url, normalized_public_base_url),
        "issued_at": issued_epoch,
        "expires_at": issued_epoch + BRILLIANT_DIRECTORIES_BILLING_SSO_BRIDGE_TOKEN_TTL_SECONDS,
    }


def sign_brilliant_directories_billing_sso_bridge_token(
    *,
    principal_id: str,
    access_email: str = "",
    return_to: str = "",
    issued_at: int | None = None,
    secret: str | None = None,
    bridge_url: str | None = None,
    public_base_url: str | None = None,
) -> str:
    signing_secret = str(secret if secret is not None else brilliant_directories_billing_sso_bridge_secret()).strip()
    if not signing_secret:
        raise RuntimeError("billing_sso_bridge_secret_missing")
    resolved_bridge_url = str(bridge_url if bridge_url is not None else brilliant_directories_billing_sso_bridge_url()).strip()
    payload = _billing_sso_bridge_payload(
        principal_id=principal_id,
        access_email=access_email,
        return_to=return_to,
        issued_at=issued_at,
        bridge_url=resolved_bridge_url,
        public_base_url=str(public_base_url or _propertyquarry_public_base_url()).strip(),
    )
    encoded = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _urlsafe_b64encode(
        hmac.new(signing_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def verify_brilliant_directories_billing_sso_bridge_token(
    token: str,
    *,
    now: int | None = None,
    secret: str | None = None,
) -> dict[str, object]:
    signing_secret = str(secret if secret is not None else brilliant_directories_billing_sso_bridge_secret()).strip()
    if not signing_secret:
        raise RuntimeError("billing_sso_bridge_secret_missing")
    raw = str(token or "").strip()
    if "." not in raw:
        raise RuntimeError("billing_sso_bridge_token_invalid")
    encoded, signature = raw.split(".", 1)
    expected_signature = _urlsafe_b64encode(
        hmac.new(signing_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise RuntimeError("billing_sso_bridge_token_signature_invalid")
    try:
        payload = json.loads(_urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("billing_sso_bridge_token_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("billing_sso_bridge_token_invalid")
    if str(payload.get("aud") or "").strip() != "propertyquarry.billing_sso_bridge":
        raise RuntimeError("billing_sso_bridge_token_audience_invalid")
    expires_at = int(payload.get("expires_at") or 0)
    current_time = int(now if now is not None else time.time())
    if expires_at <= current_time:
        raise RuntimeError("billing_sso_bridge_token_expired")
    raw_return_to_origin = str(payload.get("return_to_origin") or "").strip()
    payload["return_to_origin"] = _propertyquarry_public_base_url()
    parsed_return_to_origin = urllib.parse.urlparse(raw_return_to_origin)
    if parsed_return_to_origin.scheme == "https" and parsed_return_to_origin.netloc:
        payload["return_to_origin"] = urllib.parse.urlunparse(
            ("https", parsed_return_to_origin.netloc, "", "", "", "")
        ).rstrip("/")
    payload["return_to"] = _safe_bridge_return_to(
        str(payload.get("return_to") or ""),
        public_base_url=str(payload.get("return_to_origin") or ""),
    )
    return payload


def build_brilliant_directories_billing_sso_bridge_launch_url(
    *,
    principal_id: str,
    access_email: str = "",
    return_to: str = "",
    bridge_url: str | None = None,
    issued_at: int | None = None,
    public_base_url: str | None = None,
) -> str:
    resolved_bridge_url = str(bridge_url if bridge_url is not None else brilliant_directories_billing_sso_bridge_url()).strip()
    if not resolved_bridge_url:
        raise RuntimeError("billing_sso_bridge_url_missing")
    resolved_access_email = str(access_email or "").strip().lower() or _principal_email_hint(principal_id)
    token = sign_brilliant_directories_billing_sso_bridge_token(
        principal_id=principal_id,
        access_email=resolved_access_email,
        return_to=return_to,
        issued_at=issued_at,
        bridge_url=resolved_bridge_url,
        public_base_url=public_base_url,
    )
    parsed = urllib.parse.urlparse(resolved_bridge_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("pq_bridge", token))
    query.append(("source", "propertyquarry"))
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def _build_brilliant_directories_member_private_api_request(
    config: BrilliantDirectoriesConfig,
    method: str,
    suffix: str,
    *,
    payload: dict[str, object] | None = None,
    allowed_payload_fields: frozenset[str] | None = None,
    query: dict[str, object] | None = None,
    allowed_query_fields: frozenset[str] | None = None,
) -> BrilliantDirectoriesApiRequest:
    if not config.configured:
        raise BrilliantDirectoriesApiError(503, "brilliant_directories_not_configured")
    url = f"{config.base_url}{_brilliant_directories_api_v2_path(config, suffix)}"
    safe_query: dict[str, object] = {}
    for key, value in dict(query or {}).items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if allowed_query_fields is not None and normalized_key not in allowed_query_fields:
            raise BrilliantDirectoriesApiError(400, f"brilliant_directories_member_query_field_not_allowed:{normalized_key}")
        if value is None or value == "":
            continue
        safe_query[normalized_key] = value
    if safe_query:
        url = f"{url}?{urllib.parse.urlencode(safe_query, doseq=True)}"
    safe_payload: dict[str, object] = {}
    for key, value in dict(payload or {}).items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if allowed_payload_fields is not None and normalized_key not in allowed_payload_fields:
            raise BrilliantDirectoriesApiError(400, f"brilliant_directories_member_payload_field_not_allowed:{normalized_key}")
        if value is None or value == "":
            continue
        if normalized_key == "email":
            normalized_value = str(value or "").strip().lower()
            if "@" not in normalized_value:
                raise BrilliantDirectoriesApiError(400, "brilliant_directories_member_email_invalid")
            safe_payload[normalized_key] = normalized_value
        elif normalized_key == "token":
            normalized_value = str(value or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9]{32,96}", normalized_value):
                raise BrilliantDirectoriesApiError(400, "brilliant_directories_member_token_invalid")
            safe_payload[normalized_key] = normalized_value
        else:
            safe_payload[normalized_key] = _string(value, max_length=500)
    body = urllib.parse.urlencode(_flatten_form_payload(safe_payload), doseq=True).encode("utf-8") if safe_payload else None
    headers = {
        "Accept": "application/json",
        config.api_key_header: config.api_key,
        "User-Agent": "PropertyQuarry-BrilliantDirectoriesMemberHandoff/1.0",
    }
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return BrilliantDirectoriesApiRequest(
        method=str(method or "GET").strip().upper() or "GET",
        url=url,
        headers=headers,
        body=body,
    )


def build_brilliant_directories_member_lookup_request(
    config: BrilliantDirectoriesConfig,
    *,
    email: str,
) -> BrilliantDirectoriesApiRequest:
    normalized_email = str(email or "").strip().lower()
    if "@" not in normalized_email:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_member_email_invalid")
    return _build_brilliant_directories_member_private_api_request(
        config,
        "GET",
        "user/get",
        query={
            "property[]": ["email"],
            "property_value[]": [normalized_email],
            "limit": 1,
        },
        allowed_query_fields=BRILLIANT_DIRECTORIES_MEMBER_LOGIN_ALLOWED_QUERY_KEYS,
    )


def build_brilliant_directories_member_create_request(
    config: BrilliantDirectoriesConfig,
    *,
    email: str,
    password: str,
    token: str,
    first_name: str = "",
    last_name: str = "",
    active: str = "",
    subscription_id: str = "",
) -> BrilliantDirectoriesApiRequest:
    return _build_brilliant_directories_member_private_api_request(
        config,
        "POST",
        "user/create",
        payload={
            "email": str(email or "").strip().lower(),
            "password": str(password or "").strip(),
            "token": str(token or "").strip(),
            "first_name": str(first_name or "").strip(),
            "last_name": str(last_name or "").strip(),
            "active": str(active or "").strip(),
            "subscription_id": str(subscription_id or brilliant_directories_member_login_subscription_id()).strip(),
        },
        allowed_payload_fields=BRILLIANT_DIRECTORIES_MEMBER_CREATE_ALLOWED_FIELDS,
    )


def build_brilliant_directories_member_update_request(
    config: BrilliantDirectoriesConfig,
    *,
    user_id: str,
    token: str,
    first_name: str = "",
    last_name: str = "",
    active: str = "",
) -> BrilliantDirectoriesApiRequest:
    normalized_user_id = _string(user_id, max_length=96)
    if not normalized_user_id:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_member_user_id_missing")
    return _build_brilliant_directories_member_private_api_request(
        config,
        "PUT",
        "user/update",
        payload={
            "user_id": normalized_user_id,
            "token": str(token or "").strip(),
            "first_name": str(first_name or "").strip(),
            "last_name": str(last_name or "").strip(),
            "active": str(active or "").strip(),
        },
        allowed_payload_fields=BRILLIANT_DIRECTORIES_MEMBER_UPDATE_ALLOWED_FIELDS,
    )


def _brilliant_directories_member_rows_from_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("message")
    if rows is None:
        rows = payload.get("data")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _brilliant_directories_member_login_token_for_email(email: str, *, secret: str) -> str:
    normalized_email = str(email or "").strip().lower()
    digest = hmac.new(
        secret.encode("utf-8"),
        normalized_email.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_LENGTH]


def _brilliant_directories_member_password_for_email(email: str, *, secret: str) -> str:
    normalized_email = str(email or "").strip().lower()
    digest = hmac.new(
        secret.encode("utf-8"),
        f"password:{normalized_email}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"Pq{digest[:28]}Aa9"


def _brilliant_directories_member_name_parts(display_name: str, email: str) -> tuple[str, str]:
    normalized_display_name = " ".join(str(display_name or "").strip().split())
    if not normalized_display_name:
        normalized_display_name = _display_name_from_email(email)
    if not normalized_display_name:
        return "", ""
    parts = normalized_display_name.split()
    if len(parts) == 1:
        return parts[0][:70], ""
    return parts[0][:70], " ".join(parts[1:])[:70]


def build_brilliant_directories_member_login_token_url(
    *,
    token: str,
    config: BrilliantDirectoriesConfig | None = None,
    account_path: str = "/home",
) -> str:
    normalized_token = str(token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{32,96}", normalized_token):
        raise RuntimeError("billing_member_login_token_invalid")
    resolved_config = config or load_brilliant_directories_config()
    handoff_url = brilliant_directories_billing_handoff_url(resolved_config)
    parsed = urllib.parse.urlparse(handoff_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("billing_handoff_url_missing")
    normalized_account_path = "/" + str(account_path or "").strip().lstrip("/")
    if normalized_account_path.startswith("//"):
        normalized_account_path = "/account"
    return urllib.parse.urlunparse(
        (
            "https",
            parsed.netloc,
            f"/login/token/{urllib.parse.quote(normalized_token, safe='')}{normalized_account_path}",
            "",
            "",
            "",
        )
    )


def build_brilliant_directories_member_login_token_handoff_url(
    *,
    principal_id: str,
    access_email: str = "",
    display_name: str = "",
    config: BrilliantDirectoriesConfig | None = None,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> str:
    readiness = build_brilliant_directories_member_login_token_receipt(config=config)
    if not readiness.get("ready"):
        raise RuntimeError(str(readiness.get("error") or "billing_member_login_token_not_ready"))
    resolved_config = config or load_brilliant_directories_config()
    resolved_email = str(access_email or "").strip().lower() or _principal_email_hint(principal_id)
    if "@" not in resolved_email:
        raise RuntimeError("billing_member_login_email_missing")
    secret = brilliant_directories_member_login_token_secret()
    if not secret:
        raise RuntimeError("billing_member_login_token_secret_missing")
    token = _brilliant_directories_member_login_token_for_email(resolved_email, secret=secret)
    password = _brilliant_directories_member_password_for_email(resolved_email, secret=secret)
    first_name, last_name = _brilliant_directories_member_name_parts(display_name, resolved_email)
    lookup_payload = execute_brilliant_directories_api_request(
        build_brilliant_directories_member_lookup_request(resolved_config, email=resolved_email),
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    rows = _brilliant_directories_member_rows_from_payload(lookup_payload)
    if rows:
        user_id = _string(rows[0].get("user_id") or rows[0].get("id"), max_length=96)
        if not user_id:
            raise RuntimeError("billing_member_login_user_id_missing")
        execute_brilliant_directories_api_request(
            build_brilliant_directories_member_update_request(
                resolved_config,
                user_id=user_id,
                token=token,
                first_name=first_name,
                last_name=last_name,
                active="2",
            ),
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
    else:
        execute_brilliant_directories_api_request(
            build_brilliant_directories_member_create_request(
                resolved_config,
                email=resolved_email,
                password=password,
                token=token,
                first_name=first_name,
                last_name=last_name,
                active="2",
                subscription_id=brilliant_directories_member_login_subscription_id(),
            ),
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
    return build_brilliant_directories_member_login_token_url(
        token=token,
        config=resolved_config,
    )


def build_brilliant_directories_billing_handoff_receipt(
    handoff_url: str,
    *,
    resolver: object | None = None,
) -> dict[str, object]:
    return _billing_handoff_dns_receipt(handoff_url, resolver=resolver)


def _billing_handoff_dns_receipt(
    handoff_url: str,
    *,
    resolver: object | None = None,
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(handoff_url)
    host = str(parsed.hostname or "").strip().lower()
    dns_target = str(os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET") or "").strip()
    required_dns_record = {
        "name": host,
        "type": "CNAME" if dns_target else "CNAME or A/AAAA",
        "target": dns_target or "the Brilliant Directories white-label billing host assigned to this account",
        "purpose": "make /app/billing redirect only to a resolving HTTPS white-label account lane",
    }
    if not handoff_url:
        return {
            "configured": False,
            "url": "",
            "host": "",
            "host_resolves": False,
            "account_handoff_usable": False,
            "error": "",
            "required_dns_record": {},
            "next_action": "set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL to an HTTPS allowlisted white-label account URL",
        }
    if not host:
        return {
            "configured": True,
            "url": handoff_url,
            "host": "",
            "host_resolves": False,
            "account_handoff_usable": False,
            "error": "billing_handoff_host_missing",
            "required_dns_record": {},
            "next_action": "replace PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_URL with an HTTPS URL containing a host",
        }
    resolve = resolver or socket.getaddrinfo
    local_error = ""
    try:
        resolve(host, 443)
    except OSError as exc:
        local_error = f"billing_handoff_host_unresolved:{exc.__class__.__name__}"
        public_dns = {} if resolver is not None else _public_dns_handoff_receipt(host=host, dns_target=dns_target)
        if public_dns.get("host_resolves"):
            account_probe = _billing_handoff_account_probe(handoff_url)
            return {
                "configured": True,
                "url": handoff_url,
                "host": host,
                "host_resolves": True,
                **account_probe,
                "error": "" if account_probe.get("account_handoff_usable") else str(account_probe.get("account_handoff_error") or "billing_handoff_requires_separate_login"),
                "required_dns_record": required_dns_record,
                "next_action": (
                    "keep the resolving HTTPS billing handoff under the allowlisted white-label host"
                    if account_probe.get("account_handoff_usable")
                    else "configure Brilliant Directories SSO or a signed account handoff before redirecting signed-in PropertyQuarry users"
                ),
                "resolution_source": "public_dns_over_https",
                "local_resolver_error": local_error,
                "public_dns": public_dns,
            }
        if public_dns.get("matched_target") and public_dns.get("target_resolves") is False:
            next_action = (
                f"replace PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET and the {host} CNAME "
                "with the resolving white-label billing target shown in Brilliant Directories Domain Manager"
            )
        else:
            next_action = f"create DNS for {host} before enabling the Brilliant Directories billing handoff"
        return {
            "configured": True,
            "url": handoff_url,
            "host": host,
            "host_resolves": False,
            "account_handoff_usable": False,
            "error": local_error,
            "required_dns_record": required_dns_record,
            "next_action": next_action,
            "resolution_source": "local_resolver",
            "local_resolver_error": local_error,
            "public_dns": public_dns,
        }
    account_probe = _billing_handoff_account_probe(handoff_url)
    return {
        "configured": True,
        "url": handoff_url,
        "host": host,
        "host_resolves": True,
        **account_probe,
        "error": "" if account_probe.get("account_handoff_usable") else str(account_probe.get("account_handoff_error") or "billing_handoff_requires_separate_login"),
        "required_dns_record": required_dns_record,
        "next_action": (
            "keep the resolving HTTPS billing handoff under the allowlisted white-label host"
            if account_probe.get("account_handoff_usable")
            else "configure Brilliant Directories SSO or a signed account handoff before redirecting signed-in PropertyQuarry users"
        ),
        "resolution_source": "local_resolver",
    }


def _billing_handoff_account_probe(
    handoff_url: str,
    *,
    timeout_seconds: float = 5.0,
    _visited_urls: tuple[str, ...] = (),
) -> dict[str, object]:
    parsed = urllib.parse.urlparse(str(handoff_url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return {
            "account_handoff_usable": False,
            "account_handoff_status_code": 0,
            "account_handoff_error": "billing_handoff_url_not_https",
        }

    def _result(
        *,
        status_code: int,
        redirect_location: str,
        body: str,
        cloudflare_error_code: str = "",
    ) -> dict[str, object]:
        login_target = redirect_location or urllib.parse.urlparse(handoff_url).path
        requires_login = _is_login_probe(login_target, body)
        usable = 200 <= status_code < 400 and not requires_login and not cloudflare_error_code
        base = {
            "account_handoff_usable": usable,
            "account_handoff_status_code": status_code,
            "account_handoff_redirect_location": redirect_location,
            "account_handoff_error": "" if usable else _billing_handoff_probe_error(
                status_code=status_code,
                requires_login=requires_login,
                cloudflare_error_code=cloudflare_error_code,
            ),
            "account_handoff_warning": "",
        }
        if not redirect_location:
            return base
        if not usable:
            return {
                **base,
                "account_handoff_redirect_chain": [urllib.parse.urljoin(handoff_url, redirect_location)],
            }
        if len(_visited_urls) >= 2:
            return {
                **base,
                "account_handoff_usable": False,
                "account_handoff_error": "billing_handoff_too_many_redirects",
            }
        next_url = _billing_handoff_follow_redirect_url(handoff_url, redirect_location)
        if not next_url:
            return {**base, "account_handoff_redirect_chain": [urllib.parse.urljoin(handoff_url, redirect_location)]}
        if next_url in _visited_urls:
            return {
                **base,
                "account_handoff_usable": False,
                "account_handoff_error": "billing_handoff_redirect_loop",
                "account_handoff_redirect_chain": [next_url],
            }
        downstream = _billing_handoff_account_probe(
            next_url,
            timeout_seconds=timeout_seconds,
            _visited_urls=(*_visited_urls, handoff_url),
        )
        redirect_chain = [next_url, *list(downstream.get("account_handoff_redirect_chain") or [])]
        if downstream.get("account_handoff_usable") is False:
            return {
                "account_handoff_usable": False,
                "account_handoff_status_code": int(downstream.get("account_handoff_status_code") or status_code),
                "account_handoff_redirect_location": str(downstream.get("account_handoff_redirect_location") or redirect_location),
                "account_handoff_error": str(downstream.get("account_handoff_error") or "billing_handoff_requires_separate_login"),
                "account_handoff_warning": "",
                "account_handoff_redirect_chain": redirect_chain,
            }
        return {
            **downstream,
            "account_handoff_redirect_chain": redirect_chain,
        }

    request = urllib.request.Request(
        handoff_url,
        headers={
            "Accept": "text/html,application/json,*/*",
            "User-Agent": "PropertyQuarryBillingHandoffVerifier/1.0",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(),
        _BrilliantDirectoriesNoRedirectHandler(),
    )
    status_code = 0
    redirect_location = ""
    body = ""
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            body = response.read(16_384).decode("utf-8", errors="replace").lower()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        redirect_location = str(exc.headers.get("Location") or "").strip()
        server_header = str(exc.headers.get("Server") or "").lower()
        try:
            body = exc.read(16_384).decode("utf-8", errors="replace").lower()
        except Exception:
            body = ""
        cloudflare_error_code = (
            _cloudflare_error_code(body)
            if status_code == 403 and "cloudflare" in server_header and not _is_login_probe(redirect_location or urllib.parse.urlparse(handoff_url).path, body)
            else ""
        )
        return _result(
            status_code=status_code,
            redirect_location=redirect_location,
            body=body,
            cloudflare_error_code=cloudflare_error_code,
        )
    except Exception as exc:
        public_addresses = _resolve_host_with_public_dns(parsed.hostname or "")
        if public_addresses:
            public_probe = _http_request_via_public_address(
                handoff_url,
                timeout_seconds=timeout_seconds,
                public_addresses=public_addresses,
            )
            status_code = int(public_probe.get("status_code") or 0)
            redirect_location = str(public_probe.get("redirect_location") or "").strip()
            body = str(public_probe.get("body") or "").strip().lower()
            if status_code > 0:
                cloudflare_error_code = str(public_probe.get("cloudflare_error_code") or "").strip()
                if not cloudflare_error_code and bool(public_probe.get("cloudflare_transport_error")):
                    cloudflare_error_code = _cloudflare_error_code(body)
                return _result(
                    status_code=status_code,
                    redirect_location=redirect_location,
                    body=body,
                    cloudflare_error_code=cloudflare_error_code,
                )
            return {
                "account_handoff_usable": False,
                "account_handoff_status_code": 0,
                "account_handoff_error": f"billing_handoff_probe_failed:{type(exc).__name__}",
            }
        return {
            "account_handoff_usable": False,
            "account_handoff_status_code": 0,
            "account_handoff_error": f"billing_handoff_probe_failed:{type(exc).__name__}",
        }
    cloudflare_error_code = _cloudflare_error_code(body) if status_code == 403 and not _is_login_probe(redirect_location or urllib.parse.urlparse(handoff_url).path, body) else ""
    return _result(
        status_code=status_code,
        redirect_location=redirect_location,
        body=body,
        cloudflare_error_code=cloudflare_error_code,
    )


def _billing_handoff_login_probe_url(account_probe: Mapping[str, object]) -> str:
    redirect_chain = [str(item or "").strip() for item in list(account_probe.get("account_handoff_redirect_chain") or [])]
    for candidate in reversed(redirect_chain):
        if "/login" in candidate.lower():
            return candidate
    redirect_location = str(account_probe.get("account_handoff_redirect_location") or "").strip()
    if "/login" in redirect_location.lower():
        return redirect_location
    return ""


def _billing_handoff_pricing_surface_url(handoff_url: str) -> str:
    normalized_handoff_url = str(handoff_url or "").strip()
    parsed = urllib.parse.urlparse(normalized_handoff_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/join", "", "", ""))


def _billing_handoff_login_form_probe(
    login_url: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    normalized_login_url = str(login_url or "").strip()
    parsed = urllib.parse.urlparse(normalized_login_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {
            "login_url": normalized_login_url,
            "configured": False,
            "recaptcha_required": False,
            "error": "billing_handoff_login_url_not_https",
        }
    request_headers = {
        "Accept": "text/html,application/json,*/*",
        "User-Agent": "PropertyQuarryBillingLoginProbe/1.0",
    }
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(),
        _BrilliantDirectoriesNoRedirectHandler(),
    )
    try:
        with opener.open(urllib.request.Request(normalized_login_url, headers=request_headers), timeout=timeout_seconds) as response:
            login_page = response.read(128_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        login_page = exc.read(128_000).decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "login_url": normalized_login_url,
            "configured": False,
            "recaptcha_required": False,
            "error": f"billing_handoff_login_probe_failed:{type(exc).__name__}",
        }

    login_page_lower = login_page.lower()
    form_match = re.search(
        r'<form[^>]+action="([^"]+)"[^>]*>(.*?)</form>',
        login_page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not form_match:
        return {
            "login_url": normalized_login_url,
            "configured": False,
            "recaptcha_required": "g-recaptcha" in login_page_lower,
            "error": "billing_handoff_login_form_missing",
        }

    form_action_url = urllib.parse.urljoin(normalized_login_url, str(form_match.group(1) or "").strip())
    form_body = str(form_match.group(2) or "")
    payload_items: list[tuple[str, str]] = []
    field_names: set[str] = set()
    for input_match in re.finditer(r"<input[^>]*>", form_body, flags=re.IGNORECASE | re.DOTALL):
        input_tag = str(input_match.group(0) or "")
        name_match = re.search(r"""\bname=(["'])(.*?)\1""", input_tag, flags=re.IGNORECASE | re.DOTALL)
        value_match = re.search(r"""\bvalue=(["'])(.*?)\1""", input_tag, flags=re.IGNORECASE | re.DOTALL)
        name = str(name_match.group(2) or "").strip() if name_match else ""
        if not name:
            continue
        field_names.add(name)
        if name in {"email", "pass", "password"}:
            continue
        payload_items.append((name, str(value_match.group(2) or "").strip() if value_match else ""))
    password_field = "pass" if "pass" in field_names else ("password" if "password" in field_names else "")
    if "email" not in field_names or not password_field:
        return {
            "login_url": normalized_login_url,
            "login_form_url": form_action_url,
            "configured": False,
            "recaptcha_required": "g-recaptcha" in login_page_lower or "recaptcha" in field_names,
            "error": "billing_handoff_login_form_fields_missing",
        }

    payload_items.append(("email", "propertyquarry-billing-probe@example.com"))
    payload_items.append((password_field, "invalid-login-probe"))
    if "recaptcha" in field_names:
        payload_items.append(("recaptcha", ""))
    request_body = urllib.parse.urlencode(payload_items).encode("utf-8")
    submit_headers = {
        **request_headers,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Referer": normalized_login_url,
    }
    try:
        with opener.open(
            urllib.request.Request(form_action_url, data=request_body, headers=submit_headers, method="POST"),
            timeout=timeout_seconds,
        ) as response:
            response_text = response.read(16_384).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_text = exc.read(16_384).decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "login_url": normalized_login_url,
            "login_form_url": form_action_url,
            "configured": True,
            "recaptcha_required": "g-recaptcha" in login_page_lower or "recaptcha" in field_names,
            "error": f"billing_handoff_login_submit_failed:{type(exc).__name__}",
        }

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        payload = {}
    message = str(payload.get("message") or "").strip()
    normalized_message = message.lower()
    recaptcha_required = "invalid recaptcha response or setup" in normalized_message
    error = ""
    if recaptcha_required:
        error = "billing_handoff_login_recaptcha_required"
    elif payload.get("result") in {False, "error"}:
        error = "billing_handoff_login_invalid_credentials"
    elif not payload:
        error = "billing_handoff_login_probe_unclassified"
    return {
        "login_url": normalized_login_url,
        "login_form_url": form_action_url,
        "configured": True,
        "recaptcha_required": recaptcha_required,
        "error": error,
        "message": message,
    }


def _billing_handoff_pricing_surface_probe(
    pricing_url: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    normalized_pricing_url = str(pricing_url or "").strip()
    parsed = urllib.parse.urlparse(normalized_pricing_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {
            "pricing_url": normalized_pricing_url,
            "configured": False,
            "placeholder": False,
            "error": "billing_pricing_surface_url_not_https",
        }
    request_headers = {
        "Accept": "text/html,application/json,*/*",
        "User-Agent": "PropertyQuarryBillingPricingProbe/1.0",
    }
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(),
        _BrilliantDirectoriesNoRedirectHandler(),
    )
    status_code = 0
    try:
        with opener.open(urllib.request.Request(normalized_pricing_url, headers=request_headers), timeout=timeout_seconds) as response:
            status_code = int(response.status)
            pricing_page = response.read(128_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        pricing_page = exc.read(128_000).decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "pricing_url": normalized_pricing_url,
            "configured": False,
            "placeholder": False,
            "error": f"billing_pricing_surface_probe_failed:{type(exc).__name__}",
        }

    pricing_page_lower = pricing_page.lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", pricing_page, flags=re.IGNORECASE | re.DOTALL)
    title = " ".join(str(title_match.group(1) or "").split()) if title_match else ""
    placeholder_hits = [
        label
        for token, label in BRILLIANT_DIRECTORIES_PLACEHOLDER_PRICING_TOKENS
        if token in pricing_page_lower
    ]
    if "plan 1" in pricing_page_lower and "plan 2" in pricing_page_lower and "plan 3" in pricing_page_lower:
        placeholder_hits.append("stock_plan_numbering")
    placeholder_hits = sorted(set(placeholder_hits))
    placeholder = len(placeholder_hits) >= 2
    error = ""
    if status_code >= 400:
        error = f"billing_pricing_surface_http_{status_code}"
    elif placeholder:
        error = "billing_pricing_surface_placeholder"
    return {
        "pricing_url": normalized_pricing_url,
        "configured": True,
        "status_code": status_code,
        "placeholder": placeholder,
        "placeholder_hits": placeholder_hits,
        "error": error,
        "title": title,
    }


def _public_dns_handoff_receipt(*, host: str, dns_target: str) -> dict[str, object]:
    normalized_host = str(host or "").strip().lower().rstrip(".")
    normalized_target = str(dns_target or "").strip().lower().rstrip(".")
    if not normalized_host:
        return {"checked": False, "host_resolves": False, "reason": "host_missing"}

    cname_answers = [
        row
        for row in _dns_query_answers(normalized_host, "CNAME")
        if int(row.get("type") or 0) == 5
    ]
    address_answers = [
        row
        for qtype in ("A", "AAAA")
        for row in _dns_query_answers(normalized_host, qtype)
        if int(row.get("type") or 0) in {1, 28}
    ]
    if normalized_target:
        matched = any(str(row.get("data") or "").strip().lower().rstrip(".") == normalized_target for row in cname_answers)
        target_answers = [row for row in _dns_query_answers(normalized_target, "A") if int(row.get("type") or 0) == 1] if matched else []
        if not target_answers:
            target_answers.extend(
                row for row in _dns_query_answers(normalized_target, "AAAA") if int(row.get("type") or 0) == 28
            )
        target_resolves = bool(target_answers)
        return {
            "checked": True,
            "host_resolves": matched and target_resolves,
            "required_target": normalized_target,
            "matched_target": matched,
            "target_resolves": target_resolves,
            "answers": cname_answers[:5],
            "target_answers": target_answers[:5],
        }
    return {
        "checked": True,
        "host_resolves": bool(cname_answers or address_answers),
        "answers": (cname_answers or address_answers)[:5],
    }


def _assert_no_forbidden_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key or "").strip().lower()
            if any(marker in normalized_key for marker in BRILLIANT_DIRECTORIES_FORBIDDEN_KEY_MARKERS):
                raise BrilliantDirectoriesApiError(422, f"brilliant_directories_private_field_blocked:{path}.{key}")
            _assert_no_forbidden_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_keys(child, path=f"{path}[{index}]")


def _string(value: object, *, max_length: int = 500) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:max_length]


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(_string(item, max_length=48) for item in value if _string(item, max_length=48))[:12]
    if isinstance(value, str):
        return tuple(_string(item, max_length=48) for item in value.split(",") if _string(item, max_length=48))[:12]
    return ()


def _safe_directory_public_url(value: object, *, allowed_hosts: tuple[str, ...] = ()) -> str:
    raw = _string(value, max_length=500)
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme or parsed.netloc:
        host = str(parsed.hostname or "").strip().lower()
        if parsed.scheme != "https" or not host or host not in allowed_hosts:
            return ""
        return urllib.parse.urlunparse(("https", parsed.netloc, parsed.path, "", parsed.query, "")).strip()
    if raw.startswith("//") or "\\" in raw or ".." in raw.split("/"):
        return ""
    return raw.lstrip("/")


def _public_profile_dict(
    raw_profile: Mapping[str, object],
    *,
    include_summary: bool = True,
    allowed_url_hosts: tuple[str, ...] = (),
) -> dict[str, object]:
    first_name = _string(raw_profile.get("first_name"), max_length=70)
    last_name = _string(raw_profile.get("last_name"), max_length=70)
    full_name = " ".join(item for item in (first_name, last_name) if item)
    profile: dict[str, object] = {
        "profile_id": raw_profile.get("profile_id")
        or raw_profile.get("member_id")
        or raw_profile.get("id")
        or raw_profile.get("user_id"),
        "display_name": raw_profile.get("display_name")
        or raw_profile.get("name")
        or raw_profile.get("company_name")
        or raw_profile.get("company")
        or raw_profile.get("title")
        or full_name,
        "category": raw_profile.get("category")
        or raw_profile.get("profession")
        or raw_profile.get("service")
        or raw_profile.get("profession_name"),
        "public_url": _safe_directory_public_url(
            raw_profile.get("public_url")
            or raw_profile.get("url")
            or raw_profile.get("profile_url")
            or raw_profile.get("filename"),
            allowed_hosts=allowed_url_hosts,
        ),
        "city": raw_profile.get("city"),
        "region": raw_profile.get("region") or raw_profile.get("state") or raw_profile.get("province") or raw_profile.get("state_ln"),
        "country_code": raw_profile.get("country_code") or raw_profile.get("country"),
        "tags": raw_profile.get("tags") or raw_profile.get("specialties"),
    }
    if include_summary:
        profile["summary"] = raw_profile.get("summary") or raw_profile.get("description") or raw_profile.get("bio")
    return profile


def build_directory_profile_projection(
    raw_profile: dict[str, object],
    *,
    strict_private_keys: bool = True,
    include_summary: bool = True,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesDirectoryProfile:
    if strict_private_keys:
        _assert_no_forbidden_keys(raw_profile)
        projected_profile: Mapping[str, object] = raw_profile
    else:
        projected_profile = _public_profile_dict(
            raw_profile,
            include_summary=include_summary,
            allowed_url_hosts=allowed_url_hosts,
        )
    profile_id = _string(
        projected_profile.get("profile_id")
        or projected_profile.get("member_id")
        or projected_profile.get("id")
        or projected_profile.get("user_id"),
        max_length=96,
    )
    display_name = _string(
        projected_profile.get("display_name")
        or projected_profile.get("name")
        or projected_profile.get("company_name")
        or projected_profile.get("title"),
        max_length=140,
    )
    if not profile_id or not display_name:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_identity_missing")
    public_url = _string(
        projected_profile.get("public_url") or projected_profile.get("url") or projected_profile.get("profile_url"),
        max_length=500,
    )
    if public_url:
        parsed = urllib.parse.urlparse(public_url)
        if parsed.scheme not in {"https", ""}:
            raise BrilliantDirectoriesApiError(422, "brilliant_directories_profile_url_not_https")
    return BrilliantDirectoriesDirectoryProfile(
        profile_id=profile_id,
        display_name=display_name,
        category=_string(
            projected_profile.get("category") or projected_profile.get("profession") or projected_profile.get("service"),
            max_length=96,
        ),
        public_url=public_url,
        city=_string(projected_profile.get("city"), max_length=96),
        region=_string(projected_profile.get("region") or projected_profile.get("state") or projected_profile.get("province"), max_length=96),
        country_code=_string(projected_profile.get("country_code") or projected_profile.get("country"), max_length=12).upper(),
        summary=_string(projected_profile.get("summary") or projected_profile.get("description") or projected_profile.get("bio"), max_length=500),
        tags=_tags(projected_profile.get("tags") or projected_profile.get("specialties")),
    )


def build_directory_profile_projection_from_provider(raw_profile: dict[str, object]) -> BrilliantDirectoriesDirectoryProfile:
    return build_directory_profile_projection(raw_profile, strict_private_keys=False, include_summary=False)


def build_directory_profile_projection_from_configured_provider(
    raw_profile: dict[str, object],
    *,
    allowed_url_hosts: tuple[str, ...],
    include_summary: bool = False,
) -> BrilliantDirectoriesDirectoryProfile:
    return build_directory_profile_projection(
        raw_profile,
        strict_private_keys=False,
        include_summary=include_summary,
        allowed_url_hosts=allowed_url_hosts,
    )


def build_brilliant_directories_projection_packet(
    profiles: Iterable[BrilliantDirectoriesDirectoryProfile],
    *,
    purpose: str,
    projection_mode: str = "public_directory_profile",
) -> BrilliantDirectoriesProjectionPacket:
    normalized_profiles = tuple(profiles)
    if not normalized_profiles:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_projection_profiles_missing")
    purpose_text = _string(purpose, max_length=140)
    if not purpose_text:
        raise BrilliantDirectoriesApiError(422, "brilliant_directories_projection_purpose_missing")
    return BrilliantDirectoriesProjectionPacket(
        purpose=purpose_text,
        projection_mode=_string(projection_mode, max_length=96) or "public_directory_profile",
        profiles=normalized_profiles,
    )


def _flatten_form_payload(payload: dict[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            raise BrilliantDirectoriesApiError(400, "brilliant_directories_nested_form_payload_not_allowed")
        if isinstance(value, (list, tuple, set)):
            safe_values: list[str] = []
            for item in value:
                if isinstance(item, (dict, list, tuple, set)):
                    raise BrilliantDirectoriesApiError(400, "brilliant_directories_nested_form_payload_not_allowed")
                safe_values.append(_string(item, max_length=500))
            flattened[str(key)] = safe_values
        else:
            flattened[str(key)] = _string(value, max_length=500)
    return flattened


def build_brilliant_directories_api_request(
    config: BrilliantDirectoriesConfig,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    query: dict[str, object] | None = None,
    body_format: str = "form",
) -> BrilliantDirectoriesApiRequest:
    if not config.configured:
        raise BrilliantDirectoriesApiError(503, "brilliant_directories_not_configured")
    normalized_method = str(method or "").strip().upper()
    if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_method_not_allowed")
    normalized_path = "/" + str(path or "").strip().lstrip("/")
    parsed_path = urllib.parse.urlparse(normalized_path)
    if parsed_path.scheme or parsed_path.netloc or ".." in normalized_path.split("/"):
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_path_not_allowed")
    url = f"{config.base_url}{urllib.parse.quote(parsed_path.path, safe='/')}"
    if query:
        safe_query = {key: value for key, value in query.items() if value not in {None, ""}}
        if safe_query:
            url = f"{url}?{urllib.parse.urlencode(safe_query)}"
    body = None
    content_type = ""
    if payload is not None:
        _assert_no_forbidden_keys(payload)
        normalized_body_format = str(body_format or "").strip().lower()
        if normalized_body_format == "form":
            body = urllib.parse.urlencode(_flatten_form_payload(payload), doseq=True).encode("utf-8")
            content_type = "application/x-www-form-urlencoded"
        elif normalized_body_format == "json":
            body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            content_type = "application/json"
        else:
            raise BrilliantDirectoriesApiError(400, "brilliant_directories_body_format_not_allowed")
    headers = {
        "Accept": "application/json",
        config.api_key_header: config.api_key,
        "User-Agent": "PropertyQuarry-BrilliantDirectories/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return BrilliantDirectoriesApiRequest(
        method=normalized_method,
        url=url,
        headers=headers,
        body=body,
    )


def execute_brilliant_directories_api_request(
    request: BrilliantDirectoriesApiRequest,
    *,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> dict[str, object]:
    normalized_url = str(request.url or "").strip()
    parsed = urllib.parse.urlparse(normalized_url)
    if parsed.scheme != "https":
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_https_required")
    opener = opener or urllib.request.build_opener(_BrilliantDirectoriesNoRedirectHandler())
    urllib_request = urllib.request.Request(
        normalized_url,
        data=request.body,
        headers=dict(request.headers or {}),
        method=str(request.method or "GET").upper(),
    )
    try:
        response = opener.open(urllib_request, timeout=float(timeout_seconds or 30.0))  # type: ignore[attr-defined]
    except urllib.error.HTTPError as exc:
        reason = str(getattr(exc, "reason", "") or getattr(exc, "msg", "") or exc or "")
        detail = (
            "brilliant_directories_redirect_blocked"
            if int(exc.code) in {301, 302, 303, 307, 308} and "brilliant_directories_redirect_blocked" in reason
            else f"brilliant_directories_http_{int(exc.code)}"
        )
        raise BrilliantDirectoriesApiError(int(exc.code), detail) from exc
    except urllib.error.URLError as exc:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_unreachable") from exc

    content_type = ""
    try:
        content_type = str(response.getheader("Content-Type", "") or "").lower()
    except Exception:
        content_type = "application/json"
    if content_type and "json" not in content_type:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_unexpected_content_type")
    try:
        body = response.read(BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES + 1)
    except TypeError:
        body = response.read()
    if len(body) > BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_response_too_large")
    if not body:
        return {}
    try:
        parsed_body = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_invalid_json") from exc
    if isinstance(parsed_body, dict):
        return parsed_body
    if isinstance(parsed_body, list):
        return {"message": parsed_body}
    return {"value": parsed_body}


def _brilliant_directories_api_v2_path(config: BrilliantDirectoriesConfig, suffix: str) -> str:
    parsed = urllib.parse.urlparse(config.base_url)
    normalized_path = "/" + str(parsed.path or "").strip("/")
    if normalized_path.rstrip("/").endswith("/api/v2"):
        return "/" + str(suffix or "").strip().lstrip("/")
    return "/api/v2/" + str(suffix or "").strip().lstrip("/")


def build_brilliant_directories_member_search_request(
    config: BrilliantDirectoriesConfig,
    *,
    keyword: str = "",
    category: str = "",
    city: str = "",
    country_code: str = "",
    page: int = 1,
    limit: int = 25,
) -> BrilliantDirectoriesApiRequest:
    payload: dict[str, object] = {
        "q": _string(keyword, max_length=140),
        "category": _string(category, max_length=96),
        "city": _string(city, max_length=96),
        "country_code": _string(country_code, max_length=12).upper(),
        "page": max(1, int(page or 1)),
        "limit": min(100, max(1, int(limit or 25))),
    }
    payload = {key: value for key, value in payload.items() if value not in {"", None}}
    return build_brilliant_directories_api_request(
        config,
        "POST",
        _brilliant_directories_api_v2_path(config, "user/search"),
        payload=payload,
        body_format="form",
    )


def build_brilliant_directories_member_profile_request(
    config: BrilliantDirectoriesConfig,
    *,
    profile_id: str,
) -> BrilliantDirectoriesApiRequest:
    normalized_profile_id = _string(profile_id, max_length=96)
    if not normalized_profile_id or not all(char.isalnum() or char in {"-", "_", ".", ":"} for char in normalized_profile_id):
        raise BrilliantDirectoriesApiError(400, "brilliant_directories_profile_id_invalid")
    return build_brilliant_directories_api_request(
        config,
        "GET",
        _brilliant_directories_api_v2_path(config, f"user/get/{normalized_profile_id}"),
    )


def fetch_brilliant_directories_member_projection_packet(
    config: BrilliantDirectoriesConfig,
    *,
    purpose: str,
    keyword: str = "",
    category: str = "",
    city: str = "",
    country_code: str = "",
    page: int = 1,
    limit: int = 25,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> BrilliantDirectoriesProjectionPacket:
    request = build_brilliant_directories_member_search_request(
        config,
        keyword=keyword,
        category=category,
        city=city,
        country_code=country_code,
        page=page,
        limit=limit,
    )
    response_payload = execute_brilliant_directories_api_request(
        request,
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    return build_brilliant_directories_projection_packet_from_search_response(
        response_payload,
        purpose=purpose,
        allowed_url_hosts=config.allowed_hosts,
    )


def fetch_brilliant_directories_member_profile_projection_packet(
    config: BrilliantDirectoriesConfig,
    *,
    profile_id: str,
    purpose: str,
    timeout_seconds: float = 30.0,
    opener: object | None = None,
) -> BrilliantDirectoriesProjectionPacket:
    request = build_brilliant_directories_member_profile_request(config, profile_id=profile_id)
    response_payload = execute_brilliant_directories_api_request(
        request,
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    return build_brilliant_directories_projection_packet_from_profile_response(
        response_payload,
        purpose=purpose,
        allowed_url_hosts=config.allowed_hosts,
    )


def build_brilliant_directories_projection_packet_from_search_response(
    response_payload: dict[str, object],
    *,
    purpose: str,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesProjectionPacket:
    rows = response_payload.get("message")
    if rows is None and isinstance(response_payload.get("data"), list):
        rows = response_payload.get("data")
    if not isinstance(rows, list):
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_search_response_rows_missing")
    profiles = tuple(
        build_directory_profile_projection_from_configured_provider(row, allowed_url_hosts=allowed_url_hosts)
        for row in rows
        if isinstance(row, dict)
    )
    return build_brilliant_directories_projection_packet(profiles, purpose=purpose)


def build_brilliant_directories_projection_packet_from_profile_response(
    response_payload: dict[str, object],
    *,
    purpose: str,
    allowed_url_hosts: tuple[str, ...] = (),
) -> BrilliantDirectoriesProjectionPacket:
    row = response_payload.get("message")
    if row is None:
        row = response_payload.get("data")
    if isinstance(row, list):
        row = row[0] if row and isinstance(row[0], dict) else None
    if not isinstance(row, dict):
        raise BrilliantDirectoriesApiError(502, "brilliant_directories_profile_response_row_missing")
    profile = build_directory_profile_projection_from_configured_provider(
        row,
        allowed_url_hosts=allowed_url_hosts,
        include_summary=True,
    )
    return build_brilliant_directories_projection_packet((profile,), purpose=purpose, projection_mode="public_directory_profile_detail")


def build_brilliant_directories_verification_receipt(
    *,
    billing_handoff_resolver: object | None = None,
    verify_bridge_exchange: bool = False,
) -> dict[str, object]:
    try:
        config = load_brilliant_directories_config()
        status = "dry_verified_configured" if config.configured else "disabled"
        error = ""
    except BrilliantDirectoriesApiError as exc:
        config = BrilliantDirectoriesConfig(False, "", "", (), "X-Api-Key")
        status = "blocked"
        error = str(exc)
    handoff_url = ""
    if not error:
        handoff_url = brilliant_directories_billing_handoff_url(config)
    billing_sso_bridge = build_brilliant_directories_billing_sso_bridge_receipt(
        resolver=billing_handoff_resolver,
        config=config,
        verify_exchange=verify_bridge_exchange,
    )
    member_login_token_handoff = build_brilliant_directories_member_login_token_receipt(config=config)
    billing_handoff = build_brilliant_directories_billing_handoff_receipt(
        handoff_url,
        resolver=billing_handoff_resolver,
    )
    direct_handoff_blocked = (
        billing_handoff.get("configured") is True
        and billing_handoff.get("host_resolves") is True
        and billing_handoff.get("account_handoff_usable") is False
    )
    login_recaptcha_required = False
    pricing_placeholder = False
    if billing_handoff["configured"] and (
        not billing_handoff["host_resolves"]
        or (
            billing_handoff.get("account_handoff_usable") is False
            and member_login_token_handoff.get("ready") is not True
            and billing_sso_bridge.get("ready") is not True
        )
    ):
        status = "blocked"
        error = str(
            billing_handoff.get("error")
            or billing_handoff.get("account_handoff_error")
            or "billing_handoff_host_unresolved"
        )
    if direct_handoff_blocked:
        login_probe_url = _billing_handoff_login_probe_url(billing_handoff)
        if login_probe_url:
            login_form_probe = _billing_handoff_login_form_probe(login_probe_url)
            billing_handoff["login_form_probe"] = login_form_probe
            if login_form_probe.get("recaptcha_required"):
                login_recaptcha_required = True
    pricing_probe_url = _billing_handoff_pricing_surface_url(str(billing_handoff.get("url") or handoff_url))
    if billing_handoff.get("configured") is True and billing_handoff.get("host_resolves") is True and pricing_probe_url:
        pricing_surface_probe = _billing_handoff_pricing_surface_probe(pricing_probe_url)
        billing_handoff["pricing_surface_probe"] = pricing_surface_probe
        if pricing_surface_probe.get("placeholder") is True:
            pricing_placeholder = True
            status = "blocked"
            if not error:
                error = "billing_pricing_surface_placeholder"
    if direct_handoff_blocked and billing_sso_bridge.get("ready") is True and not pricing_placeholder:
        billing_handoff["next_action"] = (
            "keep /app/billing on the signed PropertyQuarry billing bridge; the vendor account lane still asks for "
            "another sign-in, so it remains advisory only"
        )
    elif login_recaptcha_required and pricing_placeholder:
        billing_handoff["next_action"] = (
            "configure live reCAPTCHA keys for the billing domain or disable Brilliant Directories member-login reCAPTCHA, "
            "or configure a trusted SSO/account handoff, "
            "and replace the stock Brilliant Directories join page with real PropertyQuarry plan names, benefits, "
            "and support copy before exposing billing"
        )
    elif login_recaptcha_required:
        billing_handoff["next_action"] = (
            "configure live reCAPTCHA keys for the billing domain or disable Brilliant Directories member-login reCAPTCHA, "
            "or configure the member-login token handoff with PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY and "
            "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET "
            "before redirecting signed-in PropertyQuarry users"
        )
    elif pricing_placeholder:
        billing_handoff["next_action"] = (
            "replace the stock Brilliant Directories join page with real PropertyQuarry plan names, benefits, "
            "and support copy before exposing billing"
        )
    if (
        direct_handoff_blocked
        and member_login_token_handoff.get("ready") is True
        and not login_recaptcha_required
        and not pricing_placeholder
    ):
        billing_handoff["next_action"] = (
            "verify the PropertyQuarry member-token billing handoff against the live Brilliant Directories account lane "
            "before redirecting signed-in users there"
        )
    elif (
        direct_handoff_blocked
        and billing_sso_bridge.get("ready") is True
        and not login_recaptcha_required
        and not pricing_placeholder
    ):
        billing_handoff["next_action"] = (
            "verify the custom PropertyQuarry billing bridge against the live Brilliant Directories account lane "
            "before redirecting signed-in users there"
        )
    return {
        "contract_name": BRILLIANT_DIRECTORIES_VERIFICATION_CONTRACT_NAME,
        "generated_at": _utc_now_iso(),
        "provider": BRILLIANT_DIRECTORIES_PROVIDER_KEY,
        "status": status,
        "error": error,
        "config": config.as_receipt(),
        "billing_handoff": billing_handoff,
        "billing_sso_bridge": billing_sso_bridge,
        "member_login_token_handoff": member_login_token_handoff,
        "live_network_called": False,
        "verified_capabilities": {
            "api_key_config_contract": True,
            "https_base_url_required": True,
            "allowed_host_required": True,
            "json_response_executor_contract": True,
            "response_byte_limit": BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES,
            "redirects_blocked": True,
            "form_encoded_request_contract": True,
            "public_member_search_projection_contract": True,
            "public_member_profile_projection_contract": True,
            "public_profile_projection_contract": True,
            "public_profile_url_host_allowlist": True,
            "private_property_truth_blocked": True,
            "private_provider_contact_fields_stripped": True,
            "direct_publication_disabled": True,
            "white_label_billing_handoff_host_allowlist": True,
            "billing_source_of_truth_stays_propertyquarry": True,
            "brilliant_directories_billing_events_advisory_only": True,
            "billing_webhooks_must_be_signed_and_reconciled": True,
            "billing_webhook_timestamped_hmac_contract": True,
            "billing_webhook_replay_guard_contract": True,
            "billing_webhook_entitlement_mutation_disabled": True,
            "billing_handoff_dns_resolution_required": True,
            "white_label_pricing_surface_not_stock_template_required": True,
            "custom_sso_bridge_contract": True,
        },
        "sources": [
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000101842-brilliant-directories-api-endpoints-technical-reference",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000108047-api-reference-users",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000088768-developer-hub-generate-api-key-overview",
            "https://bootstrap.brilliantdirectories.com/support/solutions/articles/12000083005-developer-hub-webhooks",
            "https://support.brilliantdirectories.com/support/solutions/articles/12000036189-how-to-login-as-member",
            "https://support.brilliantdirectories.com/support/solutions/articles/12000050980-settings-general-settings-integrations-tab",
        ],
    }
