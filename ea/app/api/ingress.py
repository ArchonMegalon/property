from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
import ipaddress
import math
import os
import threading
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import RequestContext, get_request_context
from app.observability import get_runtime_metrics
from app.product.service import build_product_service


_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_BYPASS_PATHS = {
    "/health",
    "/healthz",
    "/health/live",
    "/health/ready",
    "/internal/metrics",
    "/metrics",
}
_DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.0/8", "::1/128")


class RequestBodyLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class IngressRouteRule:
    name: str
    cost_units: int
    high_cost: bool = False
    active_search: bool = False
    max_body_bytes: int | None = None


_ROUTE_RULES: dict[tuple[str, str], IngressRouteRule] = {
    ("POST", "/app/api/property/search-runs"): IngressRouteRule(
        "property_search_start",
        25,
        high_cost=True,
        active_search=True,
    ),
    ("POST", "/app/api/signals/property/search/run"): IngressRouteRule(
        "property_search_start_legacy",
        25,
        high_cost=True,
        active_search=True,
    ),
    ("POST", "/app/api/signals/property/scout"): IngressRouteRule(
        "property_scout_sync",
        25,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/willhaben/property-tour"): IngressRouteRule(
        "property_tour_create",
        25,
        high_cost=True,
    ),
    ("POST", "/app/api/property/decision-copilot"): IngressRouteRule(
        "property_decision_copilot",
        12,
        high_cost=True,
    ),
    ("POST", "/app/api/property/magic-fit-scenes"): IngressRouteRule(
        "property_magic_fit_scene",
        25,
        high_cost=True,
    ),
    ("POST", "/app/api/property/magic-fit-reference-files"): IngressRouteRule(
        "property_magic_fit_upload",
        10,
        high_cost=True,
        max_body_bytes=40_000_000,
    ),
    ("POST", "/app/api/signals/google/photos/session"): IngressRouteRule(
        "google_photos_session",
        5,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/photos/sync"): IngressRouteRule(
        "google_photos_sync",
        15,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/sync"): IngressRouteRule(
        "google_workspace_sync",
        15,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/willhaben-sync"): IngressRouteRule(
        "google_property_sync",
        15,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/property-sync"): IngressRouteRule(
        "google_property_sync",
        15,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/location-history/sync"): IngressRouteRule(
        "google_location_sync",
        15,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/ingest"): IngressRouteRule(
        "office_signal_ingest",
        5,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/pocket/import-local"): IngressRouteRule(
        "pocket_import",
        10,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/noneverbia/import-local"): IngressRouteRule(
        "noneverbia_import",
        10,
        high_cost=True,
    ),
    ("POST", "/app/api/signals/google/location-history/import"): IngressRouteRule(
        "google_location_import",
        10,
        high_cost=True,
    ),
    ("POST", "/v1/responses"): IngressRouteRule(
        "responses_create",
        20,
        high_cost=True,
    ),
}


def _optional_bool(raw: str | None, *, default: bool) -> bool:
    normalized = str(raw or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError("propertyquarry_ingress_boolean_invalid")


def _bounded_env_int(
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


def parse_trusted_proxy_cidrs(raw: str | None) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    values = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    if not values:
        values = list(_DEFAULT_TRUSTED_PROXY_CIDRS)
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise RuntimeError("propertyquarry_trusted_proxy_cidr_invalid") from exc
    return tuple(networks)


@dataclass(frozen=True)
class IngressPolicy:
    quotas_enabled: bool
    max_body_bytes: int = 8_388_608
    max_upload_body_bytes: int = 40_000_000
    window_seconds: int = 60
    ip_request_limit: int = 600
    account_request_limit: int = 240
    ip_cost_limit: int = 1_000
    account_cost_limit: int = 300
    high_cost_ip_concurrency: int = 8
    high_cost_account_concurrency: int = 2
    active_search_limit: int = 1
    trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @classmethod
    def from_environ(
        cls,
        *,
        runtime_mode: str,
        environ: Mapping[str, str] | None = None,
    ) -> IngressPolicy:
        env = environ if environ is not None else os.environ
        production_default = str(runtime_mode or "").strip().lower() == "prod"
        return cls(
            quotas_enabled=_optional_bool(
                env.get("PROPERTYQUARRY_INGRESS_QUOTAS_ENABLED"),
                default=production_default,
            ),
            max_body_bytes=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_MAX_BODY_BYTES",
                default=8_388_608,
                minimum=1_024,
                maximum=134_217_728,
            ),
            max_upload_body_bytes=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_MAX_UPLOAD_BODY_BYTES",
                default=40_000_000,
                minimum=1_024,
                maximum=134_217_728,
            ),
            window_seconds=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_QUOTA_WINDOW_SECONDS",
                default=60,
                minimum=1,
                maximum=3_600,
            ),
            ip_request_limit=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_IP_REQUEST_LIMIT",
                default=600,
                minimum=1,
                maximum=1_000_000,
            ),
            account_request_limit=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_ACCOUNT_REQUEST_LIMIT",
                default=240,
                minimum=1,
                maximum=1_000_000,
            ),
            ip_cost_limit=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_IP_COST_LIMIT",
                default=1_000,
                minimum=1,
                maximum=10_000_000,
            ),
            account_cost_limit=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_ACCOUNT_COST_LIMIT",
                default=300,
                minimum=1,
                maximum=10_000_000,
            ),
            high_cost_ip_concurrency=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_HIGH_COST_IP_CONCURRENCY",
                default=8,
                minimum=1,
                maximum=1_000,
            ),
            high_cost_account_concurrency=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_HIGH_COST_ACCOUNT_CONCURRENCY",
                default=2,
                minimum=1,
                maximum=1_000,
            ),
            active_search_limit=_bounded_env_int(
                env,
                "PROPERTYQUARRY_INGRESS_ACTIVE_SEARCH_LIMIT",
                default=1,
                minimum=1,
                maximum=20,
            ),
            trusted_proxy_cidrs=parse_trusted_proxy_cidrs(
                env.get("PROPERTYQUARRY_TRUSTED_PROXY_CIDRS")
            ),
        )


def _parse_ip(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    normalized = str(value or "").strip().strip('"').strip("[]")
    if not normalized or len(normalized) > 64:
        return None
    if normalized.lower().startswith("for="):
        normalized = normalized[4:].strip().strip('"').strip("[]")
    if "]" in normalized:
        normalized = normalized.split("]", 1)[0].lstrip("[")
    elif normalized.count(":") == 1 and "." in normalized:
        normalized = normalized.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(normalized)
    except ValueError:
        return None


def _ip_is_trusted(
    value: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    return any(value.version == network.version and value in network for network in networks)


def resolve_client_ip(
    *,
    peer_host: object,
    headers: Mapping[str, str],
    trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> str:
    peer = _parse_ip(peer_host)
    if peer is None:
        return "unknown"
    if not _ip_is_trusted(peer, trusted_proxy_cidrs):
        return peer.compressed

    connecting_ip = _parse_ip(headers.get("cf-connecting-ip"))
    forwarded: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    if connecting_ip is not None:
        forwarded = [connecting_ip]
    else:
        raw_xff = str(headers.get("x-forwarded-for") or "")[:2_048]
        for part in raw_xff.split(",")[-16:]:
            parsed = _parse_ip(part)
            if parsed is not None:
                forwarded.append(parsed)
    for candidate in reversed([*forwarded, peer]):
        if _ip_is_trusted(candidate, trusted_proxy_cidrs):
            continue
        return candidate.compressed
    return peer.compressed


class FixedWindowQuota:
    def __init__(
        self,
        *,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 8_192,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.clock = clock
        self.max_keys = max(1, int(max_keys))
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def consume(self, key: str, *, units: int, limit: int) -> tuple[bool, int]:
        now = max(0.0, float(self.clock()))
        window = int(now // self.window_seconds)
        retry_after = max(1, int(math.ceil(((window + 1) * self.window_seconds) - now)))
        normalized_key = str(key or "unknown")
        requested_units = max(1, int(units or 1))
        with self._lock:
            if normalized_key not in self._buckets and len(self._buckets) >= self.max_keys:
                stale = [
                    name
                    for name, (bucket_window, _) in self._buckets.items()
                    if bucket_window != window
                ]
                for name in stale:
                    self._buckets.pop(name, None)
                if len(self._buckets) >= self.max_keys:
                    # Never evict a live bucket: key flooding must not reset an
                    # already-accounted caller's quota. New keys fail closed
                    # until the fixed window rolls over.
                    return False, retry_after
            previous_window, used = self._buckets.get(normalized_key, (window, 0))
            if previous_window != window:
                used = 0
            if used + requested_units > max(1, int(limit)):
                self._buckets[normalized_key] = (window, used)
                return False, retry_after
            self._buckets[normalized_key] = (window, used + requested_units)
        return True, retry_after


class InflightGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ip_counts: dict[str, int] = {}
        self._account_counts: dict[str, int] = {}

    def acquire(
        self,
        *,
        ip_key: str,
        account_key: str,
        ip_limit: int,
        account_limit: int,
    ) -> tuple[bool, str]:
        with self._lock:
            if self._ip_counts.get(ip_key, 0) >= max(1, int(ip_limit)):
                return False, "ip"
            if account_key and self._account_counts.get(account_key, 0) >= max(1, int(account_limit)):
                return False, "account"
            self._ip_counts[ip_key] = self._ip_counts.get(ip_key, 0) + 1
            if account_key:
                self._account_counts[account_key] = self._account_counts.get(account_key, 0) + 1
            return True, ""

    def release(self, *, ip_key: str, account_key: str) -> None:
        with self._lock:
            ip_count = self._ip_counts.get(ip_key, 0) - 1
            if ip_count > 0:
                self._ip_counts[ip_key] = ip_count
            else:
                self._ip_counts.pop(ip_key, None)
            if account_key:
                account_count = self._account_counts.get(account_key, 0) - 1
                if account_count > 0:
                    self._account_counts[account_key] = account_count
                else:
                    self._account_counts.pop(account_key, None)


def _headers_from_scope(scope: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        name = bytes(raw_name).decode("latin-1").strip().lower()
        value = bytes(raw_value).decode("latin-1").strip()
        if name in headers:
            headers[name] = f"{headers[name]},{value}"
        else:
            headers[name] = value
    return headers


def _route_rule(method: str, path: str, *, policy: IngressPolicy) -> IngressRouteRule | None:
    normalized_path = str(path or "/").rstrip("/") or "/"
    configured = _ROUTE_RULES.get((method, normalized_path))
    if configured is None:
        if method not in _MUTATION_METHODS:
            return None
        return IngressRouteRule("mutation", 1)
    if configured.max_body_bytes is None:
        return configured
    return IngressRouteRule(
        configured.name,
        configured.cost_units,
        high_cost=configured.high_cost,
        active_search=configured.active_search,
        max_body_bytes=policy.max_upload_body_bytes,
    )


def _hashed_account_key(context: RequestContext | None) -> str:
    principal_id = str(getattr(context, "principal_id", "") or "").strip()
    if not principal_id:
        return ""
    return hashlib.sha256(principal_id.encode("utf-8")).hexdigest()


def _request_context_sync(request: Request) -> RequestContext | None:
    container = getattr(request.app.state, "container", None)
    if container is None:
        return None
    return get_request_context(request=request, container=container)


def _active_property_search_count_sync(request: Request, context: RequestContext, *, limit: int) -> int:
    container = getattr(request.app.state, "container", None)
    if container is None:
        return 0
    service = build_product_service(container)
    if int(limit) <= 1:
        active = service.find_active_property_search_run(
            principal_id=context.principal_id,
            limit=8,
        )
        return 1 if isinstance(active, dict) and active else 0
    rows = service.list_property_search_runs(
        principal_id=context.principal_id,
        limit=max(int(limit) + 8, 12),
        hydrate=False,
    )
    terminal = {
        "completed",
        "completed_partial",
        "processed",
        "failed",
        "cancelled",
        "deleted",
        "noop",
        "not started",
    }
    active = 0
    for row in list(rows or []):
        summary = dict(row.get("summary") or {}) if isinstance(row.get("summary"), dict) else {}
        status = str(row.get("status") or summary.get("status") or "").strip().lower()
        if status and status in terminal:
            continue
        active += 1
    return active


class IngressAbuseMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        policy: IngressPolicy,
        clock: Callable[[], float] = time.monotonic,
        context_resolver: Callable[[Request], RequestContext | None] | None = None,
        active_search_counter: Callable[[Request, RequestContext, int], int] | None = None,
    ) -> None:
        self.app = app
        self.policy = policy
        self._quota = FixedWindowQuota(window_seconds=policy.window_seconds, clock=clock)
        self._inflight = InflightGate()
        self._context_resolver = context_resolver or _request_context_sync
        self._active_search_counter = active_search_counter

    async def _send_error(
        self,
        *,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
        status_code: int,
        code: str,
        message: str,
        dimension: str,
        retry_after: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        state = scope.setdefault("state", {})
        correlation_id = str(state.get("correlation_id") or uuid.uuid4())
        state["correlation_id"] = correlation_id
        error_details = dict(details or {})
        if retry_after is not None:
            error_details.setdefault("retry_after_seconds", max(1, int(retry_after)))
        response = JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": error_details,
                    "correlation_id": correlation_id,
                }
            },
        )
        response.headers["Cache-Control"] = "no-store"
        if retry_after is not None:
            response.headers["Retry-After"] = str(max(1, int(retry_after)))
        app = scope.get("app")
        if app is not None:
            get_runtime_metrics(app).record_ingress_rejection(reason=code, dimension=dimension)
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

        method = str(scope.get("method") or "GET").strip().upper()
        path = str(scope.get("path") or "/").strip() or "/"
        normalized_path = path.rstrip("/") or "/"
        headers = _headers_from_scope(scope)
        rule = _route_rule(method, normalized_path, policy=self.policy)
        body_limit = int(rule.max_body_bytes if rule and rule.max_body_bytes else self.policy.max_body_bytes)
        raw_content_length = str(headers.get("content-length") or "").strip()
        content_length = 0
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=400,
                    code="invalid_content_length",
                    message="request Content-Length is invalid",
                    dimension="body",
                )
                return
            if content_length < 0:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=400,
                    code="invalid_content_length",
                    message="request Content-Length is invalid",
                    dimension="body",
                )
                return
        if content_length > body_limit:
            await self._send_error(
                scope=scope,
                receive=receive,
                send=send,
                status_code=413,
                code="request_body_too_large",
                message="request body exceeds the configured limit",
                dimension="body",
                details={"max_body_bytes": body_limit},
            )
            return
        if headers.get("content-encoding", "").lower() not in {"", "identity"}:
            await self._send_error(
                scope=scope,
                receive=receive,
                send=send,
                status_code=415,
                code="request_content_encoding_unsupported",
                message="compressed request bodies are not accepted",
                dimension="body",
            )
            return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body") or b"")
                if received_bytes > body_limit:
                    raise RequestBodyLimitExceeded("request_body_too_large")
            return message

        bypass = method == "OPTIONS" or normalized_path in _BYPASS_PATHS
        if not self.policy.quotas_enabled or bypass:
            try:
                await self.app(scope, limited_receive, send)
            except RequestBodyLimitExceeded:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=413,
                    code="request_body_too_large",
                    message="request body exceeds the configured limit",
                    dimension="body",
                    details={"max_body_bytes": body_limit},
                )
            return

        peer = (scope.get("client") or ("", 0))[0]
        client_ip = resolve_client_ip(
            peer_host=peer,
            headers=headers,
            trusted_proxy_cidrs=self.policy.trusted_proxy_cidrs,
        )
        scope.setdefault("state", {})["client_ip"] = client_ip
        allowed, retry_after = self._quota.consume(
            f"request:ip:{client_ip}",
            units=1,
            limit=self.policy.ip_request_limit,
        )
        if not allowed:
            await self._send_error(
                scope=scope,
                receive=receive,
                send=send,
                status_code=429,
                code="ingress_rate_limit_exceeded",
                message="request rate limit exceeded",
                dimension="ip",
                retry_after=retry_after,
            )
            return

        context: RequestContext | None = None
        account_key = ""
        if rule is not None:
            request = Request(scope, receive=limited_receive)
            try:
                context = await asyncio.to_thread(self._context_resolver, request)
            except HTTPException:
                # Let the normal authentication dependency produce its canonical
                # response while retaining the anonymous/IP ingress controls.
                context = None
            except Exception:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=503,
                    code="ingress_identity_check_unavailable",
                    message="request identity could not be checked",
                    dimension="account",
                    retry_after=5,
                )
                return
            account_key = _hashed_account_key(context)
            if account_key:
                allowed, retry_after = self._quota.consume(
                    f"request:account:{account_key}",
                    units=1,
                    limit=self.policy.account_request_limit,
                )
                if not allowed:
                    await self._send_error(
                        scope=scope,
                        receive=receive,
                        send=send,
                        status_code=429,
                        code="ingress_rate_limit_exceeded",
                        message="account request rate limit exceeded",
                        dimension="account",
                        retry_after=retry_after,
                    )
                    return

        cost_units = int(rule.cost_units if rule is not None else 0)
        if content_length > 0:
            cost_units += max(0, int(math.ceil(content_length / 262_144)) - 1)
        if cost_units > 0:
            allowed, retry_after = self._quota.consume(
                f"cost:ip:{client_ip}",
                units=cost_units,
                limit=self.policy.ip_cost_limit,
            )
            if not allowed:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=429,
                    code="ingress_cost_quota_exceeded",
                    message="request cost quota exceeded",
                    dimension="ip",
                    retry_after=retry_after,
                )
                return
            if account_key:
                allowed, retry_after = self._quota.consume(
                    f"cost:account:{account_key}",
                    units=cost_units,
                    limit=self.policy.account_cost_limit,
                )
                if not allowed:
                    await self._send_error(
                        scope=scope,
                        receive=receive,
                        send=send,
                        status_code=429,
                        code="ingress_cost_quota_exceeded",
                        message="account request cost quota exceeded",
                        dimension="account",
                        retry_after=retry_after,
                    )
                    return
            app = scope.get("app")
            if app is not None:
                get_runtime_metrics(app).record_ingress_cost(
                    route_class=rule.name if rule is not None else "mutation",
                    cost_units=cost_units,
                )

        acquired = False
        if rule is not None and rule.high_cost:
            account_concurrency = (
                min(
                    self.policy.active_search_limit,
                    self.policy.high_cost_account_concurrency,
                )
                if rule.active_search
                else self.policy.high_cost_account_concurrency
            )
            acquired, dimension = self._inflight.acquire(
                ip_key=client_ip,
                account_key=account_key,
                ip_limit=self.policy.high_cost_ip_concurrency,
                account_limit=account_concurrency,
            )
            if not acquired:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=429,
                    code="ingress_concurrency_limit_exceeded",
                    message="too many high-cost requests are already active",
                    dimension=dimension,
                    retry_after=1,
                )
                return
            app = scope.get("app")
            if app is not None:
                get_runtime_metrics(app).adjust_ingress_inflight(
                    route_class=rule.name,
                    delta=1,
                )

        request_for_active_check: Request | None = None
        try:
            if rule is not None and rule.active_search and context is not None and account_key:
                request_for_active_check = Request(scope, receive=limited_receive)
                try:
                    if self._active_search_counter is not None:
                        active_count = await asyncio.to_thread(
                            self._active_search_counter,
                            request_for_active_check,
                            context,
                            self.policy.active_search_limit,
                        )
                    else:
                        active_count = await asyncio.to_thread(
                            _active_property_search_count_sync,
                            request_for_active_check,
                            context,
                            limit=self.policy.active_search_limit,
                        )
                except Exception:
                    await self._send_error(
                        scope=scope,
                        receive=receive,
                        send=send,
                        status_code=503,
                        code="active_search_check_unavailable",
                        message="active search capacity could not be checked",
                        dimension="account",
                        retry_after=5,
                    )
                    return
                if active_count >= self.policy.active_search_limit:
                    await self._send_error(
                        scope=scope,
                        receive=receive,
                        send=send,
                        status_code=429,
                        code="active_search_limit_exceeded",
                        message="an active property search is already running",
                        dimension="account",
                        retry_after=max(5, self.policy.window_seconds),
                        details={"active_search_limit": self.policy.active_search_limit},
                    )
                    return
            try:
                await self.app(scope, limited_receive, send)
            except RequestBodyLimitExceeded:
                await self._send_error(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status_code=413,
                    code="request_body_too_large",
                    message="request body exceeds the configured limit",
                    dimension="body",
                    details={"max_body_bytes": body_limit},
                )
        finally:
            if acquired and rule is not None:
                self._inflight.release(ip_key=client_ip, account_key=account_key)
                app = scope.get("app")
                if app is not None:
                    get_runtime_metrics(app).adjust_ingress_inflight(
                        route_class=rule.name,
                        delta=-1,
                    )
