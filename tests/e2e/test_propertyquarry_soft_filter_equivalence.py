from __future__ import annotations

import time

import app.product.service as product_service
from app.product.service import ProductService
from tests.product_test_helpers import build_property_client, start_workspace


def _poll_search_run(client, run_id: str) -> dict[str, object]:
    latest: dict[str, object] = {}
    for _ in range(160):
        response = client.get(f"/app/api/property/search-runs/{run_id}")
        assert response.status_code == 200, response.text
        latest = response.json()
        if str(latest.get("status") or "") in {"processed", "completed_partial", "failed", "cancelled"}:
            return latest
        time.sleep(0.02)
    return latest


def _candidate_urls(status: dict[str, object]) -> set[str]:
    summary = dict(status.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        rows.extend(row for row in list(source.get("research_candidates") or []) if isinstance(row, dict))
    if not rows:
        for row in list(summary.get("ranked_candidates") or []):
            if isinstance(row, dict):
                rows.append(row)
    return {str(row.get("property_url") or "").strip() for row in rows if str(row.get("property_url") or "").strip()}


def _candidate_fact_rows(status: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(status.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        for row in list(source.get("research_candidates") or []):
            if isinstance(row, dict):
                rows.append(row)
    for row in list(summary.get("ranked_candidates") or []):
        if isinstance(row, dict):
            rows.append(row)
    return rows


def test_propertyquarry_e2e_soft_preferences_preserve_search_hits(monkeypatch) -> None:
    principal_id = "exec-property-e2e-soft-filter-equivalence"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Soft Filter E2E Equivalence")

    source_url = "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-1020-leopoldstadt"
    listing_urls = [
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/e2e-soft-filter-a/",
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/e2e-soft-filter-b/",
        "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/e2e-soft-filter-c/",
    ]
    facts_by_url = {
        listing_urls[0]: {
            "postal_name": "1020 Wien",
            "area_sqm": 76,
            "rooms": 3,
            "total_rent_eur": 1640,
            "nearest_library_m": 1800,
            "nearest_playground_m": 1200,
            "nearest_shopping_center_m": 160,
            "nearest_theatre_m": 900,
            "nearest_supermarket_m": 700,
        },
        listing_urls[1]: {
            "postal_name": "1020 Wien",
            "area_sqm": 82,
            "rooms": 3,
            "total_rent_eur": 1720,
            "nearest_library_m": 220,
            "nearest_playground_m": 420,
            "nearest_shopping_center_m": 900,
            "nearest_theatre_m": 350,
            "nearest_supermarket_m": 180,
        },
        listing_urls[2]: {
            "postal_name": "1020 Wien",
            "area_sqm": 88,
            "rooms": 4,
            "total_rent_eur": 1850,
            "nearest_library_m": 760,
            "nearest_playground_m": 80,
            "nearest_shopping_center_m": 1400,
            "nearest_theatre_m": 1400,
            "nearest_supermarket_m": 110,
        },
    }

    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": source_url,
                "label": "Willhaben | Austria | Rent | 1020 Vienna",
                "platform": "willhaben",
                "provider_family": "marketplace",
                "country_code": "AT",
                "max_results": 5,
            }
        ],
    )
    monkeypatch.setattr(product_service, "_property_search_interleave_by_provider_group", lambda specs: list(specs))
    monkeypatch.setattr(
        product_service,
        "_property_search_prefetch_listing_urls",
        lambda **kwargs: {
            ("willhaben", source_url): {
                "listing_urls": list(listing_urls),
                "provider_cache_state": {"status": "miss", "cache_key": "willhaben:e2e-soft-filter-equivalence"},
                "timing_ms": {"provider_fetch": 1.0},
            }
        },
    )

    def _fake_preview(property_url: str, *, prefer_fast: bool = False) -> dict[str, object]:
        facts = dict(facts_by_url[property_url])
        return {
            "listing_id": property_url.rsplit("/", 2)[-2],
            "title": f"Mietwohnung in 1020 Wien {property_url.rsplit('/', 2)[-2]}",
            "summary": "Mietwohnung in 1020 Wien mit Balkon, Lift und guter Anbindung.",
            "property_facts_json": facts,
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_with_timeout", _fake_preview)

    def _fake_fit(**kwargs) -> dict[str, object]:
        property_url = str(kwargs.get("property_url") or "")
        score = 44.0 if property_url.endswith("e2e-soft-filter-a/") else 58.0
        if property_url.endswith("e2e-soft-filter-c/"):
            score = 52.0
        return {
            "fit_score": score,
            "recommendation": "review",
            "match_reasons_json": ["Hard search basics match"],
            "mismatch_reasons_json": ["Optional daily-life preferences differ"],
            "unknowns_json": [],
        }

    monkeypatch.setattr(product_service, "_property_alert_personal_fit_from_facts", _fake_fit)
    monkeypatch.setattr(ProductService, "_warm_property_public_preview_cache_for_sources", lambda self, **kwargs: {})
    monkeypatch.setattr(
        ProductService,
        "_open_property_alert_review_with_timeout",
        lambda self, **kwargs: {
            "status": "opened",
            "editor_url": f"/app/research/{str(kwargs.get('source_ref') or 'candidate').split(':')[-1]}",
        },
    )

    hard_preferences = {
        "country_code": "AT",
        "listing_mode": "rent",
        "location_query": "1020 Vienna",
        "selected_districts": ["1020"],
        "property_type": "apartment",
        "search_mode": "discovery",
        "min_match_score": 90,
        "require_floorplan": False,
        "property_commercial": {
            "active_plan_key": "agent",
            "status": "active",
            "active_until": "2999-01-01T00:00:00+00:00",
        },
    }
    soft_preferences = {
        **hard_preferences,
        "max_distance_to_library_m": 500,
        "max_distance_to_library_importance": "strong_wish",
        "max_distance_to_playground_m": 500,
        "max_distance_to_playground_importance": "nice_to_have",
        "max_distance_to_shopping_center_m": 500,
        "max_distance_to_shopping_center_importance": "avoid",
        "max_distance_to_theatre_m": 700,
        "max_distance_to_theatre_importance": "strong_wish",
        "max_distance_to_supermarket_m": 300,
        "max_distance_to_supermarket_importance": "nice_to_have",
        "avoid_noise_risk_area": True,
        "require_high_speed_internet_evidence": True,
        "check_parking_situation": True,
        "avoid_flood_risk_area": True,
    }

    plain_started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": hard_preferences,
            "force_refresh": True,
            "max_results_per_source": 5,
        },
    )
    assert plain_started.status_code == 200, plain_started.text
    soft_started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": soft_preferences,
            "force_refresh": True,
            "max_results_per_source": 5,
        },
    )
    assert soft_started.status_code == 200, soft_started.text

    plain_status = _poll_search_run(client, plain_started.json()["run_id"])
    soft_status = _poll_search_run(client, soft_started.json()["run_id"])

    assert plain_status["status"] == "processed"
    assert soft_status["status"] == "processed"
    assert _candidate_urls(plain_status) == set(listing_urls)
    assert _candidate_urls(soft_status) == set(listing_urls)
    assert _candidate_urls(soft_status) == _candidate_urls(plain_status)
    assert any(
        dict(row.get("property_facts") or {}).get("distance_preference_notes")
        or dict(row.get("property_facts") or {}).get("score_demoted_by_match_threshold")
        for row in _candidate_fact_rows(soft_status)
    )
