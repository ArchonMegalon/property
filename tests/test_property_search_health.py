from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes.landing_property_search_health import build_property_search_health_snapshot
from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def _diagnostics(state: str) -> dict[str, object]:
    if state == "ready":
        return {
            "readiness": {"ready": True, "risk_state": "healthy", "health_score": 100},
            "providers": {
                "provider_count": 3,
                "ready_count": 3,
                "degraded_count": 0,
                "failed_count": 0,
                "unknown_count": 0,
                "risk_state": "healthy",
            },
            "billing": {"current_plan_key": "free", "property_commercial": {"status": "active"}},
        }
    if state == "degraded":
        return {
            "readiness": {"ready": True, "risk_state": "watch", "health_score": 72},
            "providers": {
                "provider_count": 3,
                "ready_count": 2,
                "degraded_count": 1,
                "failed_count": 0,
                "unknown_count": 0,
                "risk_state": "watch",
            },
            "billing": {"current_plan_key": "free", "property_commercial": {"status": "active"}},
        }
    return {
        "readiness": {"ready": False, "risk_state": "critical", "health_score": 20},
        "providers": {
            "provider_count": 3,
            "ready_count": 2,
            "degraded_count": 0,
            "failed_count": 1,
            "unknown_count": 0,
            "risk_state": "critical",
        },
        "billing": {"current_plan_key": "free", "property_commercial": {"status": "active"}},
    }


@pytest.mark.parametrize(
    ("diagnostic_state", "expected_state", "expected_label"),
    (
        ("ready", "ready", "Ready"),
        ("degraded", "degraded", "Limited"),
        ("blocked", "blocked", "Unavailable"),
    ),
)
def test_property_search_health_derives_customer_state_from_live_evidence(
    diagnostic_state: str,
    expected_state: str,
    expected_label: str,
) -> None:
    now = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)

    snapshot = build_property_search_health_snapshot(
        _diagnostics(diagnostic_state),
        observed_at=now.isoformat(),
        now=now,
    )

    assert snapshot["state"] == expected_state
    assert snapshot["label"] == expected_label
    assert snapshot["freshness_state"] == "fresh"
    assert snapshot["freshness_label"] == "Checked just now"


@pytest.mark.parametrize(
    ("diagnostics", "observed_at", "expected_freshness"),
    (
        ({}, "", "missing"),
        (_diagnostics("ready"), "2026-07-13T09:50:00+00:00", "stale"),
    ),
)
def test_property_search_health_fails_closed_without_fresh_evidence(
    diagnostics: dict[str, object],
    observed_at: str,
    expected_freshness: str,
) -> None:
    snapshot = build_property_search_health_snapshot(
        diagnostics,
        observed_at=observed_at,
        now=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
        max_age_seconds=int(timedelta(minutes=5).total_seconds()),
    )

    assert snapshot["state"] == "blocked"
    assert snapshot["label"] == "Unavailable"
    assert snapshot["freshness_state"] == expected_freshness


def test_property_search_route_renders_evidence_backed_health_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "property-search-health-route"
    current_diagnostic_state = {"value": "ready"}
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("PROPERTYQUARRY_FIRST_PAINT_LOOKUP_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(
        ProductService,
        "workspace_diagnostics",
        lambda self, *, principal_id: _diagnostics(current_diagnostic_state["value"]),
    )
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    for diagnostic_state, expected_state, expected_label in (
        ("ready", "ready", "Ready"),
        ("degraded", "degraded", "Limited"),
        ("blocked", "blocked", "Unavailable"),
    ):
        current_diagnostic_state["value"] = diagnostic_state
        response = client.get("/app/search")

        assert response.status_code == 200, response.text
        assert "Search health" in response.text
        assert f'data-search-health-state="{expected_state}"' in response.text
        assert 'data-search-health-freshness="fresh"' in response.text
        assert f"<strong>{expected_label}</strong>" in response.text
