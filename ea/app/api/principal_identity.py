from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import os
import re
import threading
import time
import urllib.parse
import uuid
from typing import Any

from fastapi.responses import JSONResponse

from app.observability import get_runtime_metrics
from app.propertyquarry_release_probe import (
    PROPERTYQUARRY_RELEASE_PROBE_NONCE_HEADER,
    PROPERTYQUARRY_RELEASE_PROBE_SIGNATURE_HEADER,
    PROPERTYQUARRY_RELEASE_PROBE_TIMESTAMP_HEADER,
    normalized_propertyquarry_release_probe_origin,
    propertyquarry_release_probe_request_allowed,
    propertyquarry_release_probe_research_detail_route_valid,
    propertyquarry_release_probe_shortlist_run_path_valid,
    propertyquarry_release_probe_signature,
)


PRINCIPAL_ID_HEADER = "x-ea-principal-id"
PRINCIPAL_ASSERTION_TIMESTAMP_HEADER = "x-ea-principal-assertion-timestamp"
PRINCIPAL_ASSERTION_NONCE_HEADER = "x-ea-principal-assertion-nonce"
PRINCIPAL_ASSERTION_AUDIENCE_HEADER = "x-ea-principal-assertion-audience"
PRINCIPAL_ASSERTION_SIGNATURE_HEADER = "x-ea-principal-assertion-signature"
VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY = "verified_principal_assertion"

_PRINCIPAL_ASSERTION_HEADERS = {
    PRINCIPAL_ASSERTION_TIMESTAMP_HEADER,
    PRINCIPAL_ASSERTION_NONCE_HEADER,
    PRINCIPAL_ASSERTION_AUDIENCE_HEADER,
    PRINCIPAL_ASSERTION_SIGNATURE_HEADER,
}
_PROPERTYQUARRY_RELEASE_PROBE_HEADERS = {
    PROPERTYQUARRY_RELEASE_PROBE_TIMESTAMP_HEADER,
    PROPERTYQUARRY_RELEASE_PROBE_NONCE_HEADER,
    PROPERTYQUARRY_RELEASE_PROBE_SIGNATURE_HEADER,
}
_IDENTITY_OVERRIDE_HEADERS = {
    PRINCIPAL_ID_HEADER,
    "x-principal-id",
    "x-ea-tenant-id",
    "x-tenant-id",
    "x-ea-operator-id",
    "x-operator-id",
}
_STRIPPED_IDENTITY_HEADERS = (
    _IDENTITY_OVERRIDE_HEADERS
    | _PRINCIPAL_ASSERTION_HEADERS
    | _PROPERTYQUARRY_RELEASE_PROBE_HEADERS
)
_API_AUTH_HEADERS = {
    "authorization",
    "cf-access-authenticated-user-email",
    "cf-access-jwt-assertion",
    "cookie",
    "x-api-token",
    "x-ea-api-token",
}
_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SIGNATURE_RE = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class VerifiedPrincipalAssertion:
    principal_id: str
    audience: str
    nonce_hash: str
    issued_at: int
    auth_source: str = "edge_principal_assertion"


def _bounded_int(
    environ: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(environ.get(name) or "").strip()
    try:
        parsed = int(raw or str(default))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name.lower()}_invalid") from exc
    if parsed < minimum or parsed > maximum:
        raise RuntimeError(f"{name.lower()}_out_of_range")
    return parsed


@dataclass(frozen=True)
class PrincipalIdentityPolicy:
    runtime_mode: str
    trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    assertion_secret: str = ""
    assertion_audience: str = ""
    assertion_max_age_seconds: int = 120
    assertion_future_skew_seconds: int = 15
    assertion_nonce_capacity: int = 16_384
    release_probe_secret: str = ""
    release_probe_principal_id: str = ""
    release_probe_origin: str = ""
    release_probe_research_detail_route: str = ""
    release_probe_shortlist_run_path: str = ""

    @property
    def loopback_override_compatible(self) -> bool:
        return str(self.runtime_mode or "").strip().lower() != "prod"

    @classmethod
    def from_environ(
        cls,
        *,
        runtime_mode: str,
        trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
        environ: Mapping[str, str] | None = None,
    ) -> PrincipalIdentityPolicy:
        env = environ if environ is not None else os.environ
        secret = str(env.get("EA_EDGE_PRINCIPAL_ASSERTION_SECRET") or "").strip()
        audience = str(env.get("EA_EDGE_PRINCIPAL_ASSERTION_AUDIENCE") or "").strip()
        release_probe_secret = str(env.get("PROPERTYQUARRY_RELEASE_PROBE_SECRET") or "").strip()
        release_probe_principal_id = str(
            env.get("PROPERTYQUARRY_RELEASE_PROBE_PRINCIPAL_ID") or ""
        ).strip()
        release_probe_origin_raw = str(
            env.get("PROPERTYQUARRY_RELEASE_PROBE_ORIGIN") or ""
        ).strip()
        try:
            release_probe_origin = (
                normalized_propertyquarry_release_probe_origin(release_probe_origin_raw)
                if release_probe_origin_raw
                else ""
            )
        except ValueError as exc:
            raise RuntimeError("propertyquarry_release_probe_origin_invalid") from exc
        release_probe_research_detail_route = str(
            env.get("PROPERTYQUARRY_RELEASE_PROBE_RESEARCH_DETAIL_ROUTE") or ""
        ).strip()
        release_probe_shortlist_run_path = str(
            env.get("PROPERTYQUARRY_RELEASE_PROBE_SHORTLIST_RUN_PATH") or ""
        ).strip()
        if bool(secret) != bool(audience):
            raise RuntimeError("edge_principal_assertion_configuration_incomplete")
        if secret and len(secret.encode("utf-8")) < 32:
            raise RuntimeError("edge_principal_assertion_secret_too_short")
        for shared_secret_name in ("EA_API_TOKEN", "EA_SIGNING_SECRET"):
            shared_secret = str(env.get(shared_secret_name) or "").strip()
            if secret and shared_secret and hmac.compare_digest(secret, shared_secret):
                raise RuntimeError("edge_principal_assertion_secret_must_be_separate")
        if len(audience) > 200:
            raise RuntimeError("edge_principal_assertion_audience_too_long")
        release_probe_values = (
            release_probe_secret,
            release_probe_principal_id,
            release_probe_origin,
            release_probe_research_detail_route,
            release_probe_shortlist_run_path,
        )
        if any(release_probe_values) and not all(release_probe_values):
            raise RuntimeError("propertyquarry_release_probe_configuration_incomplete")
        if release_probe_secret and len(release_probe_secret.encode("utf-8")) < 32:
            raise RuntimeError("propertyquarry_release_probe_secret_too_short")
        if release_probe_principal_id and not _PRINCIPAL_RE.fullmatch(release_probe_principal_id):
            raise RuntimeError("propertyquarry_release_probe_principal_invalid")
        if release_probe_origin and str(runtime_mode or "").strip().lower() == "prod":
            parsed_release_probe_origin = urllib.parse.urlsplit(release_probe_origin)
            release_probe_hostname = str(parsed_release_probe_origin.hostname or "").strip().lower()
            release_probe_loopback = release_probe_hostname == "localhost"
            if not release_probe_loopback:
                try:
                    release_probe_loopback = ipaddress.ip_address(release_probe_hostname).is_loopback
                except ValueError:
                    release_probe_loopback = False
            if parsed_release_probe_origin.scheme != "https" and not release_probe_loopback:
                raise RuntimeError("propertyquarry_release_probe_origin_requires_https")
        if (
            release_probe_research_detail_route
            and not propertyquarry_release_probe_research_detail_route_valid(
                release_probe_research_detail_route
            )
        ):
            raise RuntimeError("propertyquarry_release_probe_research_detail_route_invalid")
        if (
            release_probe_shortlist_run_path
            and not propertyquarry_release_probe_shortlist_run_path_valid(
                release_probe_shortlist_run_path
            )
        ):
            raise RuntimeError("propertyquarry_release_probe_shortlist_run_path_invalid")
        for shared_secret_name, shared_secret in (
            ("EA_API_TOKEN", str(env.get("EA_API_TOKEN") or "").strip()),
            ("EA_SIGNING_SECRET", str(env.get("EA_SIGNING_SECRET") or "").strip()),
            ("EA_EDGE_PRINCIPAL_ASSERTION_SECRET", secret),
        ):
            if (
                release_probe_secret
                and shared_secret
                and hmac.compare_digest(release_probe_secret, shared_secret)
            ):
                raise RuntimeError(
                    "propertyquarry_release_probe_secret_must_be_separate:"
                    f"{shared_secret_name.lower()}"
                )
        return cls(
            runtime_mode=str(runtime_mode or "dev").strip().lower() or "dev",
            trusted_proxy_cidrs=trusted_proxy_cidrs,
            assertion_secret=secret,
            assertion_audience=audience,
            assertion_max_age_seconds=_bounded_int(
                env,
                "EA_EDGE_PRINCIPAL_ASSERTION_MAX_AGE_SECONDS",
                default=120,
                minimum=15,
                maximum=900,
            ),
            assertion_future_skew_seconds=_bounded_int(
                env,
                "EA_EDGE_PRINCIPAL_ASSERTION_FUTURE_SKEW_SECONDS",
                default=15,
                minimum=0,
                maximum=120,
            ),
            assertion_nonce_capacity=_bounded_int(
                env,
                "EA_EDGE_PRINCIPAL_ASSERTION_NONCE_CAPACITY",
                default=16_384,
                minimum=256,
                maximum=1_000_000,
            ),
            release_probe_secret=release_probe_secret,
            release_probe_principal_id=release_probe_principal_id,
            release_probe_origin=release_probe_origin,
            release_probe_research_detail_route=release_probe_research_detail_route,
            release_probe_shortlist_run_path=release_probe_shortlist_run_path,
        )


class PrincipalAssertionReplayGuard:
    def __init__(self, *, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self._expires_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, key: str, *, now: float, expires_at: float) -> bool:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return False
        with self._lock:
            expired = [name for name, expiry in self._expires_at.items() if expiry < now]
            for name in expired:
                self._expires_at.pop(name, None)
            if normalized_key in self._expires_at:
                return False
            if len(self._expires_at) >= self.capacity:
                return False
            self._expires_at[normalized_key] = max(float(expires_at), float(now))
            return True


def principal_assertion_signature(
    *,
    secret: str,
    method: str,
    path: str,
    query_string: str,
    principal_id: str,
    timestamp: int | str,
    nonce: str,
    audience: str,
) -> str:
    canonical = "\n".join(
        (
            "v1",
            str(method or "GET").strip().upper(),
            str(path or "/"),
            str(query_string or ""),
            str(principal_id or "").strip(),
            str(timestamp).strip(),
            str(nonce or "").strip(),
            str(audience or "").strip(),
        )
    )
    return hmac.new(
        str(secret or "").encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _parse_ip(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    normalized = str(value or "").strip().strip('"').strip("[]")
    if not normalized or len(normalized) > 64:
        return None
    try:
        return ipaddress.ip_address(normalized)
    except ValueError:
        return None


def _peer_is_trusted(
    peer_host: object,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    peer = _parse_ip(peer_host)
    if peer is None:
        return False
    return any(peer.version == network.version and peer in network for network in networks)


def _peer_is_development_loopback(peer_host: object) -> bool:
    normalized = str(peer_host or "").strip().lower()
    if normalized in {"localhost", "testclient"}:
        return True
    peer = _parse_ip(normalized)
    return bool(peer is not None and peer.is_loopback)


def _release_probe_path_allowed(
    *,
    path: object,
    query_string: object,
    policy: PrincipalIdentityPolicy,
) -> bool:
    return propertyquarry_release_probe_request_allowed(
        path=str(path or "/"),
        query_string=bytes(query_string or b"").decode("latin-1"),
        configured_routes=(
            policy.release_probe_research_detail_route,
            policy.release_probe_shortlist_run_path,
        ),
    )


def _header_values(scope: dict[str, Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        name = bytes(raw_name).decode("latin-1").strip().lower()
        value = bytes(raw_value).decode("latin-1").strip()
        values.setdefault(name, []).append(value)
    return values


def _release_probe_request_origin(
    *,
    scope: dict[str, Any],
    headers: dict[str, list[str]],
) -> str:
    host_values = headers.get("host", [])
    forwarded_proto_values = headers.get("x-forwarded-proto", [])
    if len(host_values) != 1 or len(forwarded_proto_values) > 1:
        return ""
    scheme = (
        str(forwarded_proto_values[0] or "").strip().lower()
        if forwarded_proto_values
        else str(scope.get("scheme") or "").strip().lower()
    )
    if scheme not in {"http", "https"} or "," in scheme:
        return ""
    try:
        return normalized_propertyquarry_release_probe_origin(
            f"{scheme}://{str(host_values[0] or '').strip()}"
        )
    except ValueError:
        return ""


def _strip_identity_headers(scope: dict[str, Any]) -> tuple[str, ...]:
    kept: list[tuple[bytes, bytes]] = []
    stripped: list[str] = []
    for raw_name, raw_value in scope.get("headers") or []:
        name = bytes(raw_name).decode("latin-1").strip().lower()
        if name in _STRIPPED_IDENTITY_HEADERS:
            stripped.append(name)
            continue
        kept.append((bytes(raw_name), bytes(raw_value)))
    scope["headers"] = kept
    return tuple(sorted(set(stripped)))


class PrincipalIdentityMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        policy: PrincipalIdentityPolicy,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.policy = policy
        self.clock = clock
        self._replay_guard = PrincipalAssertionReplayGuard(
            capacity=policy.assertion_nonce_capacity,
        )
        self._release_probe_replay_guard = PrincipalAssertionReplayGuard(
            capacity=policy.assertion_nonce_capacity,
        )

    async def _send_error(
        self,
        *,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
        reason: str,
    ) -> None:
        state = scope.setdefault("state", {})
        correlation_id = str(state.get("correlation_id") or uuid.uuid4())
        state["correlation_id"] = correlation_id
        response = JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "principal_assertion_invalid",
                    "message": "principal identity assertion was rejected",
                    "details": {"reason": str(reason or "invalid")},
                    "correlation_id": correlation_id,
                }
            },
        )
        response.headers["Cache-Control"] = "no-store"
        app = scope.get("app")
        if app is not None:
            get_runtime_metrics(app).record_ingress_rejection(
                reason="principal_assertion_invalid",
                dimension="identity",
            )
        await response(scope, receive, send)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = _header_values(scope)
        assertion_header_present = any(name in headers for name in _PRINCIPAL_ASSERTION_HEADERS)
        release_probe_attempted = any(
            name in headers for name in _PROPERTYQUARRY_RELEASE_PROBE_HEADERS
        )
        principal_values = headers.get(PRINCIPAL_ID_HEADER, [])
        assertion_attempted = assertion_header_present
        peer_host = (scope.get("client") or ("", 0))[0]

        if release_probe_attempted:
            conflicting_identity = any(
                name in headers
                for name in (_IDENTITY_OVERRIDE_HEADERS | _PRINCIPAL_ASSERTION_HEADERS | _API_AUTH_HEADERS)
            )
            method = str(scope.get("method") or "GET").strip().upper()
            path = str(scope.get("path") or "/")
            query_string = bytes(scope.get("query_string") or b"").decode("latin-1")
            request_origin = _release_probe_request_origin(scope=scope, headers=headers)
            if any(
                len(headers.get(name, [])) != 1
                for name in _PROPERTYQUARRY_RELEASE_PROBE_HEADERS
            ):
                reason = "release_probe_headers_incomplete_or_duplicated"
            elif conflicting_identity:
                reason = "release_probe_auth_conflict"
            elif not all(
                (
                    self.policy.release_probe_secret,
                    self.policy.release_probe_principal_id,
                    self.policy.release_probe_origin,
                    self.policy.release_probe_research_detail_route,
                    self.policy.release_probe_shortlist_run_path,
                )
            ):
                reason = "release_probe_not_configured"
            elif not request_origin or not hmac.compare_digest(
                request_origin,
                self.policy.release_probe_origin,
            ):
                reason = "release_probe_origin_forbidden"
            elif method not in {"GET", "HEAD"}:
                reason = "release_probe_read_only"
            elif not _release_probe_path_allowed(
                path=path,
                query_string=scope.get("query_string") or b"",
                policy=self.policy,
            ):
                reason = "release_probe_path_forbidden"
            else:
                reason = ""
            timestamp_raw = str(
                (headers.get(PROPERTYQUARRY_RELEASE_PROBE_TIMESTAMP_HEADER) or [""])[0]
            ).strip()
            nonce = str(
                (headers.get(PROPERTYQUARRY_RELEASE_PROBE_NONCE_HEADER) or [""])[0]
            ).strip()
            signature = str(
                (headers.get(PROPERTYQUARRY_RELEASE_PROBE_SIGNATURE_HEADER) or [""])[0]
            ).strip()
            if not reason:
                if not timestamp_raw.isdigit() or len(timestamp_raw) > 16:
                    reason = "release_probe_timestamp_invalid"
                elif not _NONCE_RE.fullmatch(nonce):
                    reason = "release_probe_nonce_invalid"
                elif not _SIGNATURE_RE.fullmatch(signature):
                    reason = "release_probe_signature_invalid"
            now = float(self.clock())
            nonce_hash = ""
            if not reason:
                issued_at = int(timestamp_raw)
                if issued_at < int(now) - self.policy.assertion_max_age_seconds:
                    reason = "release_probe_timestamp_expired"
                elif issued_at > int(now) + self.policy.assertion_future_skew_seconds:
                    reason = "release_probe_timestamp_in_future"
                else:
                    expected = propertyquarry_release_probe_signature(
                        secret=self.policy.release_probe_secret,
                        origin=request_origin,
                        method=method,
                        path=path,
                        query_string=query_string,
                        timestamp=timestamp_raw,
                        nonce=nonce,
                    )
                    if not hmac.compare_digest(signature.lower(), expected):
                        reason = "release_probe_signature_invalid"
            if not reason:
                nonce_hash = hashlib.sha256(
                    f"propertyquarry-release-probe\0{nonce}".encode("utf-8")
                ).hexdigest()
                if not self._release_probe_replay_guard.claim(
                    nonce_hash,
                    now=now,
                    expires_at=(
                        int(timestamp_raw)
                        + self.policy.assertion_max_age_seconds
                        + self.policy.assertion_future_skew_seconds
                    ),
                ):
                    reason = "release_probe_nonce_replayed_or_capacity_exhausted"
            stripped = _strip_identity_headers(scope)
            if reason:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason=reason,
                )
                return
            state = scope.setdefault("state", {})
            state[VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY] = VerifiedPrincipalAssertion(
                principal_id=self.policy.release_probe_principal_id,
                audience="propertyquarry-release-probe-v1",
                nonce_hash=nonce_hash,
                issued_at=int(timestamp_raw),
                auth_source="propertyquarry_release_probe",
            )
            state["identity_headers_stripped"] = stripped
            async def _send_release_probe_response(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    response_headers = [
                        (name, value)
                        for name, value in list(message.get("headers") or [])
                        if bytes(name).lower() != b"cache-control"
                    ]
                    response_headers.append((b"cache-control", b"no-store"))
                    message["headers"] = response_headers
                await send(message)

            await self.app(scope, receive, _send_release_probe_response)
            return

        if assertion_attempted:
            required_names = (PRINCIPAL_ID_HEADER, *_PRINCIPAL_ASSERTION_HEADERS)
            if any(len(headers.get(name, [])) != 1 for name in required_names):
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason="headers_incomplete_or_duplicated",
                )
                return
            if not self.policy.assertion_secret or not self.policy.assertion_audience:
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason="assertion_not_configured",
                )
                return
            if not _peer_is_trusted(peer_host, self.policy.trusted_proxy_cidrs):
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason="untrusted_proxy_peer",
                )
                return

            principal_id = principal_values[0].strip()
            timestamp_raw = headers[PRINCIPAL_ASSERTION_TIMESTAMP_HEADER][0].strip()
            nonce = headers[PRINCIPAL_ASSERTION_NONCE_HEADER][0].strip()
            audience = headers[PRINCIPAL_ASSERTION_AUDIENCE_HEADER][0].strip()
            signature = headers[PRINCIPAL_ASSERTION_SIGNATURE_HEADER][0].strip()
            if not _PRINCIPAL_RE.fullmatch(principal_id):
                reason = "principal_invalid"
            elif not timestamp_raw.isdigit() or len(timestamp_raw) > 16:
                reason = "timestamp_invalid"
            elif not _NONCE_RE.fullmatch(nonce):
                reason = "nonce_invalid"
            elif not hmac.compare_digest(audience, self.policy.assertion_audience):
                reason = "audience_invalid"
            elif not _SIGNATURE_RE.fullmatch(signature):
                reason = "signature_invalid"
            else:
                reason = ""
            if reason:
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason=reason,
                )
                return

            issued_at = int(timestamp_raw)
            now = float(self.clock())
            if issued_at < int(now) - self.policy.assertion_max_age_seconds:
                reason = "timestamp_expired"
            elif issued_at > int(now) + self.policy.assertion_future_skew_seconds:
                reason = "timestamp_in_future"
            else:
                expected = principal_assertion_signature(
                    secret=self.policy.assertion_secret,
                    method=str(scope.get("method") or "GET"),
                    path=str(scope.get("path") or "/"),
                    query_string=bytes(scope.get("query_string") or b"").decode("latin-1"),
                    principal_id=principal_id,
                    timestamp=timestamp_raw,
                    nonce=nonce,
                    audience=audience,
                )
                reason = "" if hmac.compare_digest(signature.lower(), expected) else "signature_invalid"
            if reason:
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason=reason,
                )
                return

            nonce_hash = hashlib.sha256(f"{audience}\0{nonce}".encode("utf-8")).hexdigest()
            if not self._replay_guard.claim(
                nonce_hash,
                now=now,
                expires_at=issued_at
                + self.policy.assertion_max_age_seconds
                + self.policy.assertion_future_skew_seconds,
            ):
                _strip_identity_headers(scope)
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    reason="nonce_replayed_or_capacity_exhausted",
                )
                return
            stripped = _strip_identity_headers(scope)
            state = scope.setdefault("state", {})
            state[VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY] = VerifiedPrincipalAssertion(
                principal_id=principal_id,
                audience=audience,
                nonce_hash=nonce_hash,
                issued_at=issued_at,
            )
            state["identity_headers_stripped"] = stripped
            await self.app(scope, receive, send)
            return

        if principal_values or any(name in headers for name in _IDENTITY_OVERRIDE_HEADERS):
            if self.policy.loopback_override_compatible and _peer_is_development_loopback(peer_host):
                await self.app(scope, receive, send)
                return
            stripped = _strip_identity_headers(scope)
            scope.setdefault("state", {})["identity_headers_stripped"] = stripped

        await self.app(scope, receive, send)
