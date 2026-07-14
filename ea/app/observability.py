from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import socket
import threading
import time
from typing import Mapping


_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_MAX_HEARTBEAT_BYTES = 64 * 1024
_DELIVERY_OUTBOX_METRIC_OUTCOMES = (
    "queued",
    "claimed",
    "claim_conflicts",
    "sent",
    "retried",
    "dead_lettered",
    "failed",
)
_CONTENT_LEDGER_METRIC_OUTCOMES = (
    "claimed",
    "recovered",
    "duplicate",
    "replay_conflict",
    "completed",
    "failed",
    "corruption",
)
_INGRESS_LABEL_RE = re.compile(r"[^a-z0-9_]+")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPLICA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _label_value(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return format(float(value), ".9g")


def _ingress_label(value: str, *, fallback: str) -> str:
    normalized = _INGRESS_LABEL_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return (normalized or fallback)[:64]


def route_template(request) -> str:  # type: ignore[no-untyped-def]
    route = request.scope.get("route")
    path = str(getattr(route, "path", "") or "").strip()
    return path if path.startswith("/") else "unmatched"


def normalized_method(value: str) -> str:
    method = str(value or "").strip().upper()
    return method if method in _KNOWN_METHODS else "OTHER"


def runtime_build_identity(
    environ: Mapping[str, str] | None = None,
    *,
    hostname: str | None = None,
) -> dict[str, str]:
    """Return the process-observed release and Docker replica identity.

    The capture lane independently checks these values against Docker inspect;
    they are runtime claims, not launch authority by themselves.
    """

    env = environ if environ is not None else os.environ
    commit_sha = str(env.get("PROPERTYQUARRY_RELEASE_COMMIT_SHA") or "").strip().lower()
    image_digest = str(env.get("PROPERTYQUARRY_RELEASE_IMAGE_DIGEST") or "").strip().lower()
    replica_id = str(hostname if hostname is not None else socket.gethostname()).strip()
    return {
        "release_commit_sha": commit_sha if _GIT_SHA_RE.fullmatch(commit_sha) else "",
        "release_image_digest": (
            image_digest if _IMAGE_DIGEST_RE.fullmatch(image_digest) else ""
        ),
        "replica_id": replica_id if _REPLICA_ID_RE.fullmatch(replica_id) else "",
    }


class RuntimeMetrics:
    """Small bounded-label Prometheus registry for one API process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._errors: dict[tuple[str, str, str], int] = defaultdict(int)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
        self._ingress_rejections: dict[tuple[str, str], int] = defaultdict(int)
        self._ingress_cost: dict[str, int] = defaultdict(int)
        self._ingress_inflight: dict[str, int] = defaultdict(int)
        self._content_ledger_events: dict[str, int] = defaultdict(int)

    def record_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        safe_method = normalized_method(method)
        safe_route = route if str(route or "").startswith("/") else "unmatched"
        status = int(status_code or 500)
        status_class = f"{max(0, min(9, status // 100))}xx"
        duration = max(0.0, float(duration_seconds or 0.0))
        request_key = (safe_method, safe_route, status_class)
        duration_key = (safe_method, safe_route)
        with self._lock:
            self._requests[request_key] += 1
            if status >= 400:
                self._errors[request_key] += 1
            self._duration_count[duration_key] += 1
            self._duration_sum[duration_key] += duration
            for bucket in _LATENCY_BUCKETS:
                if duration <= bucket:
                    self._duration_buckets[(safe_method, safe_route, bucket)] += 1

    def record_ingress_rejection(self, *, reason: str, dimension: str) -> None:
        safe_reason = _ingress_label(reason, fallback="unknown")
        safe_dimension = _ingress_label(dimension, fallback="unknown")
        with self._lock:
            self._ingress_rejections[(safe_reason, safe_dimension)] += 1

    def record_ingress_cost(self, *, route_class: str, cost_units: int) -> None:
        safe_route_class = _ingress_label(route_class, fallback="other")
        with self._lock:
            self._ingress_cost[safe_route_class] += max(0, int(cost_units or 0))

    def adjust_ingress_inflight(self, *, route_class: str, delta: int) -> None:
        safe_route_class = _ingress_label(route_class, fallback="other")
        with self._lock:
            updated = self._ingress_inflight.get(safe_route_class, 0) + int(delta or 0)
            self._ingress_inflight[safe_route_class] = max(0, updated)

    def record_content_ledger_event(self, *, outcome: str) -> None:
        safe_outcome = _ingress_label(outcome, fallback="failed")
        if safe_outcome not in _CONTENT_LEDGER_METRIC_OUTCOMES:
            safe_outcome = "failed"
        with self._lock:
            self._content_ledger_events[safe_outcome] += 1

    def render_prometheus(
        self,
        *,
        readiness_ready: bool,
        environ: Mapping[str, str] | None = None,
        now_epoch: float | None = None,
    ) -> str:
        with self._lock:
            requests = dict(self._requests)
            errors = dict(self._errors)
            duration_count = dict(self._duration_count)
            duration_sum = dict(self._duration_sum)
            duration_buckets = dict(self._duration_buckets)
            ingress_rejections = dict(self._ingress_rejections)
            ingress_cost = dict(self._ingress_cost)
            ingress_inflight = dict(self._ingress_inflight)
            content_ledger_events = dict(self._content_ledger_events)

        lines = [
            "# HELP propertyquarry_http_requests_total HTTP requests completed by bounded route template.",
            "# TYPE propertyquarry_http_requests_total counter",
        ]
        for (method, route, status_class), count in sorted(requests.items()):
            lines.append(
                'propertyquarry_http_requests_total{method="%s",route="%s",status_class="%s"} %d'
                % (_label_value(method), _label_value(route), _label_value(status_class), count)
            )
        lines.extend(
            [
                "# HELP propertyquarry_http_request_errors_total HTTP responses with status 4xx or 5xx.",
                "# TYPE propertyquarry_http_request_errors_total counter",
            ]
        )
        for (method, route, status_class), count in sorted(errors.items()):
            lines.append(
                'propertyquarry_http_request_errors_total{method="%s",route="%s",status_class="%s"} %d'
                % (_label_value(method), _label_value(route), _label_value(status_class), count)
            )
        lines.extend(
            [
                "# HELP propertyquarry_http_request_duration_seconds HTTP request latency by bounded route template.",
                "# TYPE propertyquarry_http_request_duration_seconds histogram",
            ]
        )
        for method, route in sorted(duration_count):
            for bucket in _LATENCY_BUCKETS:
                count = duration_buckets.get((method, route, bucket), 0)
                lines.append(
                    'propertyquarry_http_request_duration_seconds_bucket{method="%s",route="%s",le="%s"} %d'
                    % (_label_value(method), _label_value(route), _metric_float(bucket), count)
                )
            count = duration_count[(method, route)]
            lines.append(
                'propertyquarry_http_request_duration_seconds_bucket{method="%s",route="%s",le="+Inf"} %d'
                % (_label_value(method), _label_value(route), count)
            )
            lines.append(
                'propertyquarry_http_request_duration_seconds_sum{method="%s",route="%s"} %s'
                % (_label_value(method), _label_value(route), _metric_float(duration_sum[(method, route)]))
            )
            lines.append(
                'propertyquarry_http_request_duration_seconds_count{method="%s",route="%s"} %d'
                % (_label_value(method), _label_value(route), count)
            )

        lines.extend(
            [
                "# HELP propertyquarry_ingress_rejections_total Requests rejected by bounded ingress abuse controls.",
                "# TYPE propertyquarry_ingress_rejections_total counter",
            ]
        )
        for (reason, dimension), count in sorted(ingress_rejections.items()):
            lines.append(
                'propertyquarry_ingress_rejections_total{reason="%s",dimension="%s"} %d'
                % (_label_value(reason), _label_value(dimension), count)
            )
        lines.extend(
            [
                "# HELP propertyquarry_ingress_cost_units_total Admitted ingress cost units by bounded route class.",
                "# TYPE propertyquarry_ingress_cost_units_total counter",
            ]
        )
        for route_class, cost_units in sorted(ingress_cost.items()):
            lines.append(
                'propertyquarry_ingress_cost_units_total{route_class="%s"} %d'
                % (_label_value(route_class), cost_units)
            )
        lines.extend(
            [
                "# HELP propertyquarry_ingress_high_cost_inflight High-cost requests currently admitted in this API process.",
                "# TYPE propertyquarry_ingress_high_cost_inflight gauge",
            ]
        )
        for route_class, count in sorted(ingress_inflight.items()):
            lines.append(
                'propertyquarry_ingress_high_cost_inflight{route_class="%s"} %d'
                % (_label_value(route_class), count)
            )

        lines.extend(
            [
                "# HELP propertyquarry_content_ledger_events_total Governed property-content ledger outcomes.",
                "# TYPE propertyquarry_content_ledger_events_total counter",
            ]
        )
        for outcome in _CONTENT_LEDGER_METRIC_OUTCOMES:
            lines.append(
                'propertyquarry_content_ledger_events_total{outcome="%s"} %d'
                % (_label_value(outcome), max(0, int(content_ledger_events.get(outcome, 0))))
            )

        lines.extend(
            [
                "# HELP propertyquarry_readiness Whether the API readiness gates currently pass.",
                "# TYPE propertyquarry_readiness gauge",
                f"propertyquarry_readiness {1 if readiness_ready else 0}",
            ]
        )
        heartbeat_env = environ if environ is not None else os.environ
        build_identity = runtime_build_identity(heartbeat_env)
        lines.extend(
            [
                "# HELP propertyquarry_runtime_build_info Process-observed release, image, and replica identity.",
                "# TYPE propertyquarry_runtime_build_info gauge",
                (
                    'propertyquarry_runtime_build_info{release_commit_sha="%s",'
                    'release_image_digest="%s",replica_id="%s"} 1'
                )
                % (
                    _label_value(build_identity["release_commit_sha"]),
                    _label_value(build_identity["release_image_digest"]),
                    _label_value(build_identity["replica_id"]),
                ),
            ]
        )
        expected_replicas = _expected_api_replicas(heartbeat_env)
        lines.extend(
            [
                "# HELP propertyquarry_expected_api_replicas Expected API replicas for per-target scrape coverage.",
                "# TYPE propertyquarry_expected_api_replicas gauge",
                f"propertyquarry_expected_api_replicas {expected_replicas}",
            ]
        )
        heartbeat_now = float(now_epoch if now_epoch is not None else time.time())
        samples = [_heartbeat_sample(role, heartbeat_env, heartbeat_now) for role in ("worker", "scheduler")]
        required_roles = {
            role: _heartbeat_required(role, heartbeat_env) for role in ("worker", "scheduler")
        }
        lines.extend(
            [
                "# HELP propertyquarry_runtime_heartbeat_required Whether the runtime role is required for this deployment.",
                "# TYPE propertyquarry_runtime_heartbeat_required gauge",
            ]
        )
        for role in ("worker", "scheduler"):
            lines.append(
                'propertyquarry_runtime_heartbeat_required{role="%s"} %d'
                % (_label_value(role), 1 if required_roles[role] else 0)
            )
        lines.extend(
            [
                "# HELP propertyquarry_runtime_heartbeat_age_seconds Age of the last role heartbeat; NaN when missing or invalid.",
                "# TYPE propertyquarry_runtime_heartbeat_age_seconds gauge",
            ]
        )
        for sample in samples:
            lines.append(
                'propertyquarry_runtime_heartbeat_age_seconds{role="%s"} %s'
                % (_label_value(sample.role), _metric_float(sample.age_seconds))
            )
        lines.extend(
            [
                "# HELP propertyquarry_runtime_heartbeat_present Whether a heartbeat file exists and parses.",
                "# TYPE propertyquarry_runtime_heartbeat_present gauge",
            ]
        )
        for sample in samples:
            lines.append(
                'propertyquarry_runtime_heartbeat_present{role="%s"} %d'
                % (_label_value(sample.role), 1 if sample.present else 0)
            )
        lines.extend(
            [
                "# HELP propertyquarry_runtime_heartbeat_stale Whether a heartbeat is missing, invalid, future-dated, or too old.",
                "# TYPE propertyquarry_runtime_heartbeat_stale gauge",
            ]
        )
        for sample in samples:
            lines.append(
                'propertyquarry_runtime_heartbeat_stale{role="%s"} %d'
                % (_label_value(sample.role), 1 if sample.stale else 0)
            )
        scheduler_sample = next(sample for sample in samples if sample.role == "scheduler")
        delivery_totals = dict(scheduler_sample.delivery_outbox_totals)
        lines.extend(
            [
                "# HELP propertyquarry_scheduler_delivery_outbox_events_total Scheduler delivery outbox outcomes reported by the latest heartbeat.",
                "# TYPE propertyquarry_scheduler_delivery_outbox_events_total counter",
            ]
        )
        for outcome in _DELIVERY_OUTBOX_METRIC_OUTCOMES:
            lines.append(
                'propertyquarry_scheduler_delivery_outbox_events_total{outcome="%s"} %d'
                % (_label_value(outcome), max(0, int(delivery_totals.get(outcome, 0))))
            )
        return "\n".join(lines) + "\n"


def get_runtime_metrics(app) -> RuntimeMetrics:  # type: ignore[no-untyped-def]
    registry = getattr(app.state, "runtime_metrics", None)
    if isinstance(registry, RuntimeMetrics):
        return registry
    registry = RuntimeMetrics()
    app.state.runtime_metrics = registry
    return registry


@dataclass(frozen=True)
class HeartbeatSample:
    role: str
    present: bool
    age_seconds: float
    stale: bool
    delivery_outbox_totals: tuple[tuple[str, int], ...] = ()


def _positive_float(raw: str, default: float) -> float:
    try:
        value = float(str(raw or "").strip())
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _heartbeat_required(role: str, environ: Mapping[str, str]) -> bool:
    normalized_role = str(role or "").strip().lower()
    default = normalized_role == "scheduler"
    key = f"PROPERTYQUARRY_{normalized_role.upper()}_HEARTBEAT_REQUIRED"
    value = str(environ.get(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _expected_api_replicas(environ: Mapping[str, str]) -> int:
    raw = str(environ.get("PROPERTYQUARRY_EXPECTED_API_REPLICAS") or "1").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if 1 <= value <= 100 else 0


def _heartbeat_sample(role: str, environ: Mapping[str, str], now_epoch: float) -> HeartbeatSample:
    normalized_role = str(role or "").strip().lower()
    prefix = "EA_SCHEDULER" if normalized_role == "scheduler" else "EA_WORKER"
    default_path = f"/data/artifacts/propertyquarry-{normalized_role}-heartbeat.json"
    path = Path(str(environ.get(f"{prefix}_HEARTBEAT_PATH") or default_path).strip())
    max_age = _positive_float(environ.get(f"{prefix}_HEARTBEAT_MAX_AGE_SECONDS", ""), 900.0)
    try:
        if not path.is_file() or path.stat().st_size > _MAX_HEARTBEAT_BYTES:
            return HeartbeatSample(normalized_role, False, math.nan, True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return HeartbeatSample(normalized_role, False, math.nan, True)
        epoch = float(payload.get("epoch"))
        recorded_role = str(payload.get("role") or "").strip().lower()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return HeartbeatSample(normalized_role, False, math.nan, True)
    if not math.isfinite(epoch) or recorded_role != normalized_role:
        return HeartbeatSample(normalized_role, True, math.nan, True)
    raw_age = float(now_epoch) - epoch
    if raw_age < -5.0:
        return HeartbeatSample(normalized_role, True, math.nan, True)
    age = max(0.0, raw_age)
    raw_delivery_totals = payload.get("delivery_outbox")
    delivery_totals: list[tuple[str, int]] = []
    if normalized_role == "scheduler" and isinstance(raw_delivery_totals, dict):
        for outcome in _DELIVERY_OUTBOX_METRIC_OUTCOMES:
            try:
                value = max(0, int(raw_delivery_totals.get(outcome) or 0))
            except (TypeError, ValueError):
                value = 0
            delivery_totals.append((outcome, value))
    return HeartbeatSample(
        normalized_role,
        True,
        age,
        age > max_age,
        tuple(delivery_totals),
    )
