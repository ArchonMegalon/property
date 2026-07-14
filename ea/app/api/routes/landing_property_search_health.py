from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


_BLOCKED_BILLING_STATES = {
    "blocked",
    "locked",
    "past_due_locked",
    "suspended",
}
_DEGRADED_BILLING_STATES = {
    "action_required",
    "past_due",
    "pending",
    "unknown",
}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(value: object) -> datetime | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _billing_state(billing: Mapping[str, object]) -> str:
    commercial = _mapping(billing.get("property_commercial"))
    return str(
        commercial.get("billing_state")
        or commercial.get("status")
        or billing.get("billing_state")
        or billing.get("status")
        or ""
    ).strip().lower()


def build_property_search_health_snapshot(
    diagnostics: object,
    *,
    observed_at: object = "",
    now: datetime | None = None,
    max_age_seconds: int = 300,
) -> dict[str, object]:
    """Project live workspace diagnostics into a fail-closed search status."""
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    aggregate = _mapping(diagnostics)
    aggregate_observed_at = (
        aggregate.get("observed_at")
        or aggregate.get("generated_at")
        or aggregate.get("checked_at")
        or observed_at
    )
    observed_time = _timestamp(aggregate_observed_at)
    observed_iso = observed_time.isoformat() if observed_time is not None else ""

    def snapshot(
        *,
        state: str,
        freshness_state: str,
        label: str,
        detail: str,
        freshness_label: str,
        age_seconds: int | None,
        reasons: list[str],
    ) -> dict[str, object]:
        return {
            "state": state,
            "tone": "good" if state == "ready" else "warn",
            "label": label,
            "detail": detail,
            "freshness_state": freshness_state,
            "freshness_label": freshness_label,
            "observed_at": observed_iso,
            "age_seconds": age_seconds,
            "reasons": reasons,
        }

    if not aggregate or observed_time is None:
        return snapshot(
            state="blocked",
            freshness_state="missing",
            label="Unavailable",
            detail="Search status could not be confirmed. Please try again shortly.",
            freshness_label="Status not checked",
            age_seconds=None,
            reasons=["missing_evidence"],
        )

    age_seconds = max(int((current_time - observed_time).total_seconds()), 0)
    future_seconds = int((observed_time - current_time).total_seconds())
    if future_seconds > 60 or age_seconds > max(int(max_age_seconds), 0):
        return snapshot(
            state="blocked",
            freshness_state="stale",
            label="Unavailable",
            detail="Search status is being refreshed. Please try again shortly.",
            freshness_label="Status needs refresh",
            age_seconds=age_seconds,
            reasons=["stale_evidence"],
        )
    freshness_label = "Checked just now" if age_seconds < 60 else f"Checked {max(age_seconds // 60, 1)} min ago"

    readiness = _mapping(aggregate.get("readiness"))
    providers = _mapping(aggregate.get("providers"))
    billing = _mapping(aggregate.get("billing"))
    if not readiness or not providers or not billing:
        return snapshot(
            state="blocked",
            freshness_state="fresh",
            label="Unavailable",
            detail="Search status could not be confirmed. Please try again shortly.",
            freshness_label=freshness_label,
            age_seconds=age_seconds,
            reasons=["incomplete_evidence"],
        )

    readiness_risk = str(readiness.get("risk_state") or "").strip().lower()
    provider_risk = str(providers.get("risk_state") or "").strip().lower()
    provider_count = _integer(providers.get("provider_count"))
    ready_count = _integer(providers.get("ready_count"))
    billing_state = _billing_state(billing)
    billing_access_blocked = (
        ("search_enabled" in billing and billing.get("search_enabled") is False)
        or ("access_active" in billing and billing.get("access_active") is False)
        or billing_state in _BLOCKED_BILLING_STATES
    )

    blocked_reasons: list[str] = []
    if readiness.get("ready") is not True or readiness_risk in {"blocked", "critical", "failed"}:
        blocked_reasons.append("runtime_not_ready")
    if provider_count <= 0 or ready_count <= 0 or provider_risk in {"blocked", "critical", "failed"}:
        blocked_reasons.append("providers_not_ready")
    if billing_access_blocked:
        blocked_reasons.append("billing_access_blocked")
    if blocked_reasons:
        return snapshot(
            state="blocked",
            freshness_state="fresh",
            label="Unavailable",
            detail="Search is not available right now. Please try again shortly.",
            freshness_label=freshness_label,
            age_seconds=age_seconds,
            reasons=blocked_reasons,
        )

    degraded_reasons: list[str] = []
    if readiness_risk in {"attention", "degraded", "watch"}:
        degraded_reasons.append("runtime_degraded")
    if (
        provider_risk in {"attention", "degraded", "watch"}
        or _integer(providers.get("degraded_count")) > 0
        or _integer(providers.get("failed_count")) > 0
        or _integer(providers.get("unknown_count")) > 0
    ):
        degraded_reasons.append("provider_coverage_degraded")
    if billing_state in _DEGRADED_BILLING_STATES:
        degraded_reasons.append("billing_needs_attention")

    if degraded_reasons:
        return snapshot(
            state="degraded",
            freshness_state="fresh",
            label="Limited",
            detail="Some search sites need attention. Available sites can still be searched.",
            freshness_label=freshness_label,
            age_seconds=age_seconds,
            reasons=degraded_reasons,
        )
    return snapshot(
        state="ready",
        freshness_state="fresh",
        label="Ready",
        detail="Search sites and account access are available.",
        freshness_label=freshness_label,
        age_seconds=age_seconds,
        reasons=[],
    )
