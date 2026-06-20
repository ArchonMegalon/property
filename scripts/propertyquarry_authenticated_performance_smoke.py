#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.product.service import ProductService, _now_iso


DEFAULT_ROUTE_BUDGET_MS = {
    "/app/search": 1200,
    "/app/agents": 1200,
    "/app/properties": 1200,
    "/app/shortlist": 1200,
    "/app/account": 1200,
    "/app/billing": 1200,
}


def _seed_workspace(client: TestClient) -> None:
    response = client.post(
        "/v1/onboarding/start",
        json={
            "workspace_name": "PropertyQuarry Performance Smoke",
            "mode": "personal",
            "workspace_mode": "personal",
            "timezone": "Europe/Vienna",
            "region": "AT",
            "language": "en",
            "selected_channels": ["google"],
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"workspace_seed_failed:{response.status_code}:{response.text[:280]}")


def _seed_saved_agents(client: TestClient) -> None:
    response = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "selected_platforms": ["willhaben", "derstandard_at"],
            "active_search_agent_id": "perf-watch-1020",
            "search_agents": [
                {
                    "agent_id": "perf-watch-1020",
                    "name": "Leopoldstadt rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "notification_limit": 3,
                    "notification_period": "day",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben", "derstandard_at"],
                    },
                },
                {
                    "agent_id": "perf-watch-1130",
                    "name": "Hietzing buy watch",
                    "enabled": False,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1130 Vienna",
                    "listing_mode": "buy",
                    "property_type": "apartment",
                    "notification_limit": 5,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1130 Vienna",
                        "listing_mode": "buy",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben"],
                    },
                },
            ],
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"saved_agents_seed_failed:{response.status_code}:{response.text[:280]}")


def _synthetic_search_result(*args: object, **kwargs: object) -> dict[str, object]:
    progress_callback = kwargs.get("progress_callback")
    if callable(progress_callback):
        progress_callback(
            step="sources_resolved",
            message="Resolved synthetic performance smoke source.",
            status="in_progress",
            steps_delta=1,
            summary_updates={"sources_total": 1, "source_variant_total": 1, "provider_total": 1},
        )
    candidate = {
        "candidate_ref": "perf-candidate-1020",
        "rank": 1,
        "title": "Performance smoke apartment in 1020 Vienna",
        "source_label": "Willhaben | Austria | Rent | 1020 Vienna",
        "source_platform": "willhaben",
        "property_url": "https://example.invalid/propertyquarry/performance-smoke",
        "packet_url": "/app/research/perf-candidate-1020",
        "review_url": "/app/research/perf-candidate-1020",
        "fit_score": 91,
        "score": 91,
        "fit_summary": "Transit, area, layout and budget fit the seeded brief.",
        "match_reasons": ["1020 Vienna matches the seeded search area.", "The synthetic listing keeps route and layout data compact."],
        "mismatch_reasons": ["Operating-cost evidence still needs a provider document."],
        "property_facts": {
            "postal_code": "1020",
            "district": "1020 Vienna",
            "price_eur": 1290,
            "area_m2": 72,
            "rooms": 3,
            "has_floorplan": True,
            "has_balcony": True,
            "operating_costs_status": "missing",
        },
        "route_evidence": [
            {"label": "Transit", "distance": "350 m", "icon": "U"},
            {"label": "School", "distance": "650 m", "icon": "S"},
        ],
    }
    return {
        "generated_at": _now_iso(),
        "status": "processed",
        "sources_total": 1,
        "source_variant_total": 1,
        "provider_total": 1,
        "listing_total": 1,
        "raw_listing_total": 1,
        "reviewed_listing_total": 1,
        "ranked_total": 1,
        "filtered_total": 0,
        "held_back_total": 0,
        "review_created_total": 1,
        "review_existing_total": 0,
        "notified_total": 0,
        "email_notified_total": 0,
        "tour_created_total": 0,
        "tour_existing_total": 0,
        "high_fit_total": 1,
        "watch_notified_total": 0,
        "ranked_candidates": [candidate],
        "top_candidates": [candidate],
        "sources": [
            {
                "source_label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "status": "completed",
                "listing_total": 1,
                "ranked_total": 1,
            }
        ],
    }


def _start_synthetic_run(client: TestClient) -> str:
    original: Callable[..., dict[str, object]] = ProductService.sync_direct_property_scout
    ProductService.sync_direct_property_scout = _synthetic_search_result  # type: ignore[method-assign]
    try:
        response = client.post(
            "/app/api/property/search-runs",
            json={
                "selected_platforms": ["willhaben"],
                "property_preferences": {
                    "country_code": "AT",
                    "region_code": "vienna",
                    "listing_mode": "rent",
                    "property_type": ["apartment"],
                    "location_query": "1020 Vienna",
                    "min_area_m2": 60,
                    "max_price_eur": 1600,
                },
                "max_results_per_source": 1,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"synthetic_run_start_failed:{response.status_code}:{response.text[:280]}")
        run_id = str(response.json().get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError("synthetic_run_missing_run_id")
        for _ in range(160):
            status = client.get(f"/app/api/property/search-runs/{run_id}")
            if status.status_code == 200 and str(status.json().get("status") or "").lower() in {"processed", "completed"}:
                return run_id
            time.sleep(0.025)
        raise RuntimeError(f"synthetic_run_timeout:{run_id}")
    finally:
        ProductService.sync_direct_property_scout = original  # type: ignore[method-assign]


def _measure_route(client: TestClient, path: str, *, budget_ms: int) -> dict[str, object]:
    started = time.perf_counter()
    response = client.get(path, headers={"host": "propertyquarry.com"})
    duration_ms = round((time.perf_counter() - started) * 1000)
    body = response.text or ""
    checks = [
        {"name": "status_200", "ok": response.status_code == 200},
        {"name": "under_budget", "ok": duration_ms <= budget_ms},
        {"name": "contains_propertyquarry", "ok": "PropertyQuarry" in body},
        {"name": "no_generic_ea_copy", "ok": "Executive Assistant" not in body and "Morning Memo" not in body},
    ]
    if path == "/app/agents":
        checks.extend(
            (
                {"name": "agent_cards", "ok": "Leopoldstadt rent watch" in body and "Hietzing buy watch" in body},
                {"name": "map_only_thumbnails", "ok": "osm_district_overlay" in body and "Map preview unavailable" not in body},
            )
        )
    if path.startswith("/app/research/"):
        checks.extend(
            (
                {"name": "research_candidate", "ok": "Performance smoke apartment in 1020 Vienna" in body},
                {"name": "media_requests_explicit", "ok": "Request" in body and "tour" in body.lower()},
            )
        )
    return {
        "path": path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "budget_ms": budget_ms,
        "ok": all(bool(row["ok"]) for row in checks),
        "checks": checks,
    }


def build_authenticated_performance_receipt(*, route_budget_ms: int = 1200) -> dict[str, object]:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES"] = "1"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    principal_id = "pq-auth-performance-smoke"
    client = TestClient(create_app(), base_url="https://propertyquarry.com")
    client.headers.update({"X-EA-Principal-ID": principal_id, "host": "propertyquarry.com"})
    _seed_workspace(client)
    _seed_saved_agents(client)
    run_id = _start_synthetic_run(client)
    routes = [
        "/app/search",
        "/app/agents",
        f"/app/properties?run_id={run_id}",
        f"/app/shortlist?run_id={run_id}",
        f"/app/research/perf-candidate-1020?run_id={run_id}",
        "/app/account",
        "/app/billing",
    ]
    rows = [
        _measure_route(client, route, budget_ms=int(DEFAULT_ROUTE_BUDGET_MS.get(route.split("?", 1)[0], route_budget_ms)))
        for route in routes
    ]
    failed = [row for row in rows if not row.get("ok")]
    return {
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "principal_id": principal_id,
        "run_id": run_id,
        "route_count": len(rows),
        "failed_count": len(failed),
        "routes": rows,
        "notes": [
            "This smoke is local, authenticated, provider-free and non-networked.",
            "It guards first-paint route budgets for search, agents, results, research, account and billing surfaces.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run authenticated PropertyQuarry route performance smoke.")
    parser.add_argument("--route-budget-ms", type=int, default=1200)
    args = parser.parse_args()
    receipt = build_authenticated_performance_receipt(route_budget_ms=max(100, int(args.route_budget_ms or 1200)))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
