from __future__ import annotations

import copy
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.product.property_location_research as property_location_research
import app.product.service as product_service
from app.api.dependencies import RequestContext
from app.api.routes.product_api_contracts import PropertyFactEnrichmentOut
from app.api.routes.product_api_delivery import _require_property_fact_same_origin
from app.product.property_fact_enrichment import (
    PROPERTY_FACT_DISTANCE_SPECS,
    PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION,
    property_fact_distance_specs,
    property_fact_requirement_plan,
    property_fact_score_projection,
)
from app.product.service import (
    ProductService,
    _property_fact_fresh_geo_snapshot,
    _property_fact_location_query_is_exact,
    _property_fact_retry_remaining_seconds,
    _property_fact_safe_job_payload,
    _property_search_ranked_candidates_from_sources,
)
from tests.product_test_helpers import build_property_operator_client


def _candidate(*, candidate_ref: str = "candidate-facts") -> dict[str, object]:
    return {
        "candidate_ref": candidate_ref,
        "title": "Family home",
        "property_url": "https://www.willhaben.at/iad/immobilien/d/family-home-1234567890/",
        "source_ref": "property-scout:1234567890",
        "source_label": "Willhaben",
        "fit_score": 60.0,
        "ranking_score": 60.0,
        "assessment": {"domain": "willhaben", "fit_score": 60.0, "recommendation": "mention"},
        "property_facts": {},
    }


def _run_record(*, principal_id: str, run_id: str, candidate: dict[str, object]) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": run_id,
        "principal_id": principal_id,
        "status": "processed",
        "created_at": now,
        "updated_at": now,
        "property_search_preferences": {"prefer_supermarket_nearby": True},
        "summary": {
            "status": "processed",
            "ranked_candidates": [dict(candidate)],
            "sources": [
                {
                    "source_label": "Willhaben",
                    "source_url": "https://www.willhaben.at/iad/immobilien/",
                    "top_candidates": [dict(candidate)],
                    "research_candidates": [dict(candidate)],
                }
            ],
        },
        "events": [],
    }


def _seed_run(record: dict[str, object]) -> None:
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[str(record["run_id"])] = dict(record)


def _clear_run(run_id: str) -> None:
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY.pop(run_id, None)


def _resolved_geo_facts(*, include_playground: bool = True) -> dict[str, object]:
    observed_at = datetime.now(timezone.utc)
    facts: dict[str, object] = {
        "map_lat": 48.2082,
        "map_lng": 16.3738,
        "map_location_precision": "address",
        "map_location_source": "listing",
        "house_number": "12",
        "nearest_supermarket_m": 280,
        "nearest_pharmacy_m": 530,
        "nearest_medical_care_m": 570,
        "nearest_subway_m": 640,
        "property_fact_evidence": {
            "nearest_supermarket_m": {
                "provider": "openstreetmap_overpass",
                "method": "straight_line_osm",
                "observed_at": observed_at.isoformat(),
                "expires_at": (observed_at + timedelta(hours=24)).isoformat(),
                "freshness": "fresh",
                "confidence": 0.95,
                "source_key": "nearest_supermarket_m",
                "source_fingerprint": "sha256:" + "b" * 64,
                "coordinate_basis": "candidate_listing_coordinates",
                "coordinate_observed_at": observed_at.isoformat(),
                "coordinate_precision": "address",
                "coordinate_source": "listing",
                "coordinate_exact": True,
            }
        },
    }
    if include_playground:
        facts["nearest_playground_m"] = 410
    return facts


def test_fact_priority_preserves_unknown_and_holds_required_facts_out_of_ranking() -> None:
    required_plan = property_fact_requirement_plan(
        facts={},
        preferences={},
        preference_nodes=(
            {
                "category": "soft_preference",
                "key": "prefer_supermarket_nearby",
                "strength": "high",
                "value": True,
            },
        ),
    )
    supermarket = next(row for row in required_plan if row["key"] == "nearest_supermarket_m")
    projection = property_fact_score_projection(
        candidate={"fit_score": 77},
        plan=required_plan,
        preferences={},
    )

    assert supermarket["state"] == "unknown"
    assert supermarket["priority"] == "required"
    assert supermarket["value"] is None
    assert projection["state"] == "evaluating"
    assert projection["current"] is None
    assert projection["ranking_eligible"] is False


def test_nice_to_have_unknown_is_provisional_and_distance_alias_resolves() -> None:
    plan = property_fact_requirement_plan(
        facts={"distance_supermarket_m": 325},
        preferences={"prefer_supermarket_nearby": True},
    )
    supermarket = next(row for row in plan if row["key"] == "nearest_supermarket_m")
    projection = property_fact_score_projection(
        candidate={"fit_score": 64},
        plan=plan,
        preferences={"prefer_supermarket_nearby": True},
    )

    assert supermarket["state"] == "resolved"
    assert supermarket["source_key"] == "distance_supermarket_m"
    assert supermarket["display_value"] == "325 m"
    assert projection["state"] == "provisional"
    assert projection["current"] == 64.0
    assert projection["ranking_eligible"] is True


def test_distance_fact_registry_exhaustively_covers_search_preferences() -> None:
    expected_search_preferences = {
        "max_distance_to_supermarket_m",
        "max_distance_to_pharmacy_m",
        "max_distance_to_subway_m",
        "max_distance_to_kindergarten_m",
        "max_distance_to_ganztags_volksschule_m",
        "max_distance_to_halbtags_volksschule_m",
        "max_distance_to_playground_m",
        "max_distance_to_library_m",
        "max_distance_to_zoo_m",
        "max_distance_to_market_m",
        "max_distance_to_hardware_store_m",
        "max_distance_to_shopping_center_m",
        "max_distance_to_shopping_street_m",
        "max_distance_to_theatre_m",
        "max_distance_to_public_pool_m",
        "max_distance_to_medical_care_m",
        "max_distance_to_starbucks_m",
        "max_distance_to_fitness_center_m",
        "max_distance_to_cinema_m",
        "max_distance_to_bouldering_m",
        "max_distance_to_dog_park_m",
        "max_distance_to_good_cafe_m",
    }
    registry = property_fact_distance_specs(search_supported_only=True)
    actual_preferences = {
        str(preference_key)
        for spec in registry
        for preference_key in list(spec["preference_keys"])
        if str(preference_key).startswith("max_distance_to_")
    }

    assert actual_preferences == expected_search_preferences
    assert len(actual_preferences) == len(registry)
    assert len({str(spec["key"]) for spec in registry}) == len(registry)
    assert all(spec["aliases"] for spec in registry)
    assert all(str(spec["label"]).strip() for spec in registry)
    assert all(str(spec["search_label"]).strip() for spec in registry)
    assert all(spec["poi_keys"] for spec in registry)
    assert all(str(spec["provider"]).strip() for spec in registry)


def test_every_search_distance_preference_maps_to_required_or_lazy_plan() -> None:
    for spec in property_fact_distance_specs(search_supported_only=True):
        preference_key = next(
            str(value)
            for value in list(spec["preference_keys"])
            if str(value).startswith("max_distance_to_")
        )
        required_plan = property_fact_requirement_plan(
            facts={},
            preferences={preference_key: 750},
        )
        required = next(row for row in required_plan if row["key"] == spec["key"])
        assert required["priority"] == "required", preference_key
        assert required["state"] == "unknown", preference_key

        lazy_plan = property_fact_requirement_plan(
            facts={},
            preferences={
                preference_key: 750,
                f"{preference_key[:-2]}_importance": "nice_to_have",
            },
        )
        lazy = next(row for row in lazy_plan if row["key"] == spec["key"])
        assert lazy["priority"] == "lazy", preference_key
        assert lazy["state"] == "unknown", preference_key


def test_distance_fact_registry_accessor_returns_defensive_copies() -> None:
    first = property_fact_distance_specs()
    first[0]["aliases"].append("mutated_alias")
    second = property_fact_distance_specs()

    assert "mutated_alias" not in second[0]["aliases"]
    assert isinstance(PROPERTY_FACT_DISTANCE_SPECS, tuple)


def test_quality_cafe_and_school_classification_require_honest_provenance() -> None:
    observed_at = datetime.now(timezone.utc)

    def _evidence(provider: str) -> dict[str, object]:
        return {
            "provider": provider,
            "observed_at": observed_at.isoformat(),
            "expires_at": (observed_at + timedelta(hours=24)).isoformat(),
            "source_fingerprint": "sha256:" + "c" * 64,
            "coordinate_exact": True,
        }

    school_preferences = {"max_distance_to_ganztags_volksschule_m": 900}
    school_from_osm = property_fact_requirement_plan(
        facts={
            "nearest_full_day_primary_school_m": 420,
            "property_fact_evidence": {
                "nearest_full_day_primary_school_m": _evidence("openstreetmap_overpass"),
            },
        },
        preferences=school_preferences,
    )
    school_row = next(
        row for row in school_from_osm if row["key"] == "nearest_full_day_primary_school_m"
    )
    assert school_row["state"] == "stale"

    schoolatlas = property_fact_requirement_plan(
        facts={
            "nearest_full_day_primary_school_m": 420,
            "property_fact_evidence": {
                "nearest_full_day_primary_school_m": _evidence("schoolatlas"),
            },
        },
        preferences=school_preferences,
    )
    assert next(
        row for row in schoolatlas if row["key"] == "nearest_full_day_primary_school_m"
    )["state"] == "resolved"

    cafe_preferences = {"max_distance_to_good_cafe_m": 700}
    generic_cafe = property_fact_requirement_plan(
        facts={
            "nearest_good_cafe_m": 180,
            "property_fact_evidence": {
                "nearest_good_cafe_m": _evidence("openstreetmap_overpass"),
            },
        },
        preferences=cafe_preferences,
    )
    cafe_row = next(row for row in generic_cafe if row["key"] == "nearest_good_cafe_m")
    assert cafe_row["label"] == "Quality-verified café distance"
    assert cafe_row["state"] == "stale"

    verified_cafe = property_fact_requirement_plan(
        facts={
            "nearest_good_cafe_m": 180,
            "property_fact_evidence": {
                "nearest_good_cafe_m": _evidence("quality_verified_cafe_source"),
            },
        },
        preferences=cafe_preferences,
    )
    assert next(
        row for row in verified_cafe if row["key"] == "nearest_good_cafe_m"
    )["state"] == "resolved"


def test_nearby_provider_queries_supported_specialty_pois_but_not_unverified_good_cafes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_request: dict[str, str] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "elements": [
                    {"lat": 48.2090, "lon": 16.3738, "tags": {"brand": "Starbucks"}},
                    {"lat": 48.2100, "lon": 16.3738, "tags": {"leisure": "fitness_centre"}},
                    {"lat": 48.2110, "lon": 16.3738, "tags": {"amenity": "cinema"}},
                    {"lat": 48.2120, "lon": 16.3738, "tags": {"sport": "bouldering"}},
                    {"lat": 48.2130, "lon": 16.3738, "tags": {"leisure": "dog_park"}},
                ]
            }

    def _post(url: str, *, data: str, headers: dict[str, str], timeout: float):
        observed_request.update({"url": url, "data": data})
        return _Response()

    property_location_research._property_research_nearby_pois.cache_clear()
    monkeypatch.setattr(property_location_research.requests, "post", _post)
    result = property_location_research._property_research_nearby_pois(48.2082, 16.3738)
    property_location_research._property_research_nearby_pois.cache_clear()

    assert {
        "nearest_starbucks_m",
        "nearest_fitness_center_m",
        "nearest_cinema_m",
        "nearest_bouldering_m",
        "nearest_dog_park_m",
    }.issubset(result)
    decoded_query = urllib.parse.unquote(observed_request["data"])
    assert '["brand"~"^starbucks$",i]' in decoded_query
    assert '["leisure"="fitness_centre"]' in decoded_query
    assert '["amenity"="cinema"]' in decoded_query
    assert '["sport"~"^(climbing|bouldering)$"]' in decoded_query
    assert '["leisure"="dog_park"]' in decoded_query
    assert '["amenity"="cafe"]' not in decoded_query


@pytest.mark.parametrize("importance", ("must_have", "strong_wish", "avoid"))
def test_explicit_blocking_distance_importance_holds_ranking(
    importance: str,
) -> None:
    preferences = {
        "max_distance_to_supermarket_m": 300,
        "max_distance_to_supermarket_importance": importance,
    }
    plan = property_fact_requirement_plan(facts={}, preferences=preferences)
    supermarket = next(row for row in plan if row["key"] == "nearest_supermarket_m")
    projection = property_fact_score_projection(
        candidate={"fit_score": 75},
        plan=plan,
        preferences=preferences,
    )

    assert supermarket["priority"] == "required"
    assert projection["state"] == "evaluating"
    assert projection["ranking_eligible"] is False


def test_explicit_nice_to_have_distance_stays_lazy_over_stored_profile_default() -> None:
    preferences = {
        "max_distance_to_supermarket_m": 300,
        "max_distance_to_supermarket_importance": "nice_to_have",
    }
    plan = property_fact_requirement_plan(
        facts={},
        preferences=preferences,
        preference_nodes=(
            {
                "category": "constraint",
                "key": "prefer_supermarket_nearby",
                "strength": "high",
                "value": True,
            },
        ),
    )
    supermarket = next(row for row in plan if row["key"] == "nearest_supermarket_m")
    projection = property_fact_score_projection(
        candidate={"fit_score": 75},
        plan=plan,
        preferences=preferences,
    )

    assert supermarket["priority"] == "lazy"
    assert projection["state"] == "provisional"
    assert projection["ranking_eligible"] is True


def test_rank_projection_excludes_evaluating_candidate() -> None:
    ready = {**_candidate(candidate_ref="ready"), "score_state": "provisional", "ranking_eligible": True}
    evaluating = {
        **_candidate(candidate_ref="evaluating"),
        "fit_score": 99,
        "score_state": "evaluating",
        "ranking_eligible": False,
    }

    ranked = _property_search_ranked_candidates_from_sources(
        [
            {
                "source_label": "Willhaben",
                "top_candidates": [ready],
                "research_candidates": [ready, evaluating],
            }
        ]
    )

    assert [row["candidate_ref"] for row in ranked] == ["ready"]
    assert ranked[0]["rank"] == 1


def test_query_inferred_address_coordinates_cannot_finalize_required_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(timezone.utc)
    facts: dict[str, object] = {
        "map_lat": 48.2082,
        "map_lng": 16.3738,
        "map_location_precision": "address",
        "map_location_source": "nominatim_query_inferred",
    }
    monkeypatch.setattr(
        product_service,
        "_property_research_nearby_pois",
        lambda _lat, _lng: {"nearest_supermarket_m": 240},
    )

    nearby, coordinate_meta = _property_fact_fresh_geo_snapshot(
        property_url="https://www.willhaben.at/iad/immobilien/d/example-1234567890/",
        facts=facts,
    )
    facts.update(nearby)
    facts["property_fact_evidence"] = {
        "nearest_supermarket_m": {
            "provider": "openstreetmap_overpass",
            "observed_at": observed_at.isoformat(),
            "expires_at": (observed_at + timedelta(hours=24)).isoformat(),
            "source_fingerprint": "sha256:" + "a" * 64,
            **coordinate_meta,
        }
    }
    plan = property_fact_requirement_plan(
        facts=facts,
        preferences={"max_distance_to_supermarket_m": 800},
    )
    supermarket = next(row for row in plan if row["key"] == "nearest_supermarket_m")
    projection = property_fact_score_projection(
        candidate={"fit_score": 91.0},
        plan=plan,
        preferences={"max_distance_to_supermarket_m": 800},
    )

    assert coordinate_meta["coordinate_exact"] is False
    assert supermarket["state"] == "stale"
    assert supermarket["priority"] == "required"
    assert projection["state"] == "evaluating"
    assert projection["current"] is None
    assert projection["ranking_eligible"] is False


def test_fact_enrichment_job_is_idempotent_persistent_and_recomputes_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-facts-job"
    run_id = "run-property-facts-job"
    candidate = _candidate()
    candidate["property_facts"] = {
        "map_lat": 48.2082,
        "map_lng": 16.3738,
        "map_location_precision": "address",
        "map_location_source": "listing",
        "house_number": "12",
    }
    client = build_property_operator_client(principal_id=principal_id)
    service = ProductService(client.app.state.container)
    _seed_run(_run_record(principal_id=principal_id, run_id=run_id, candidate=candidate))
    calls = {"research": 0}

    def _research(_latitude: float, _longitude: float) -> dict[str, object]:
        calls["research"] += 1
        return {
            "nearest_supermarket_m": 280,
            "nearest_supermarket_name": "Daily Market",
            "nearest_playground_m": 410,
            "nearest_pharmacy_m": 530,
            "nearest_medical_care_m": 570,
            "nearest_subway_m": 640,
        }

    monkeypatch.setattr(product_service, "_property_research_nearby_pois", _research)
    monkeypatch.setattr(
        product_service,
        "_property_fact_validated_source_url",
        lambda url: str(url),
    )
    monkeypatch.setattr(
        ProductService,
        "preview_preference_candidate",
        lambda self, **kwargs: {
            "domain": "willhaben",
            "fit_score": 68.0,
            "recommendation": "shortlist",
            "match_reasons_json": ["Nearby facts verified."],
        },
    )
    try:
        first = service.start_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-facts",
        )
        second = service.start_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-facts",
        )
        assert first["job_id"] == second["job_id"]

        deadline = time.monotonic() + 4.0
        status: dict[str, object] | None = None
        while time.monotonic() < deadline:
            status = service.get_property_candidate_fact_enrichment(
                principal_id=principal_id,
                run_id=run_id,
                candidate_ref="candidate-facts",
            )
            if status and status["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)

        assert status is not None
        assert status["schema_version"] == PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION
        assert status["status"] == "succeeded"
        assert calls["research"] == 1
        assert status["score"]["state"] == "final"
        assert status["score"]["previous"] == 60.0
        assert status["score"]["current"] == 68.0
        assert status["score"]["delta"] == 8.0
        supermarket = next(row for row in status["fields"] if row["key"] == "nearest_supermarket_m")
        assert supermarket["display_value"] == "280 m"
        assert supermarket["provenance"]["provider"] == "openstreetmap_overpass"
        assert supermarket["provenance"]["method"] == "straight_line_osm"
        assert supermarket["provenance"]["coordinate_exact"] is True
        assert supermarket["provenance"]["observed_at"]
        assert supermarket["provenance"]["expires_at"]
        assert PropertyFactEnrichmentOut(**status).status == "succeeded"

        joined = service.start_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-facts",
        )
        assert joined["job_id"] == first["job_id"]
        assert joined["status"] == "succeeded"
        assert calls["research"] == 1
    finally:
        _clear_run(run_id)


def test_fact_enrichment_no_work_returns_complete_resolved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-facts-no-work"
    run_id = "run-property-facts-no-work"
    candidate = _candidate(candidate_ref="candidate-no-work")
    candidate["property_facts"] = _resolved_geo_facts()
    client = build_property_operator_client(principal_id=principal_id)
    service = ProductService(client.app.state.container)
    _seed_run(_run_record(principal_id=principal_id, run_id=run_id, candidate=candidate))
    monkeypatch.setattr(product_service, "_property_fact_validated_source_url", lambda url: str(url))
    launched: list[str] = []
    monkeypatch.setattr(
        ProductService,
        "_launch_property_candidate_fact_enrichment",
        lambda self, **kwargs: launched.append(str(kwargs.get("job_id") or "")),
    )
    try:
        started = service.start_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-no-work",
        )
        polled = service.get_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-no-work",
        )

        assert launched == []
        assert started["status"] == "succeeded"
        assert polled is not None
        assert polled["status"] == "succeeded"
        expected_keys = {
            "nearest_supermarket_m",
            "nearest_playground_m",
            "nearest_pharmacy_m",
            "nearest_medical_care_m",
            "nearest_subway_m",
        }
        for payload in (started, polled):
            assert {row["key"] for row in payload["fields"]} == expected_keys
            assert len(payload["fields"]) == 5
            assert all(row["state"] == "resolved" for row in payload["fields"])
            assert PropertyFactEnrichmentOut(**payload).status == "succeeded"

        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            record = product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id]
            stale_candidate = dict(candidate)
            stale_facts = copy.deepcopy(candidate["property_facts"])
            supermarket_evidence = dict(
                dict(stale_facts["property_fact_evidence"])["nearest_supermarket_m"]
            )
            supermarket_evidence["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
            stale_facts["property_fact_evidence"] = {
                "nearest_supermarket_m": supermarket_evidence,
            }
            stale_candidate["property_facts"] = stale_facts
            assert product_service._property_fact_update_candidate_copies(
                record,
                candidate_ref="candidate-no-work",
                updated_candidate=stale_candidate,
            )

        stale = service.get_property_candidate_fact_enrichment(
            principal_id=principal_id,
            run_id=run_id,
            candidate_ref="candidate-no-work",
        )
        assert stale is not None
        assert stale["status"] == "retryable_error"
        assert stale["retryable"] is True
        assert len(stale["fields"]) == 5
        stale_supermarket = next(
            row for row in stale["fields"] if row["key"] == "nearest_supermarket_m"
        )
        assert stale_supermarket["state"] == "retryable_error"
        assert stale_supermarket["error"]["code"] == "fact_enrichment_requires_retry"
        assert not any(
            row["state"] in {"unknown", "stale", "queued", "running"}
            for row in stale["fields"]
        )
        assert PropertyFactEnrichmentOut(**stale).status == "retryable_error"
    finally:
        _clear_run(run_id)


def test_fact_enrichment_partial_retry_api_preserves_complete_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-facts-partial-retry"
    run_id = "run-property-facts-partial-retry"
    candidate = _candidate(candidate_ref="candidate-partial-retry")
    candidate["property_facts"] = _resolved_geo_facts(include_playground=False)
    client = build_property_operator_client(principal_id=principal_id)
    _seed_run(_run_record(principal_id=principal_id, run_id=run_id, candidate=candidate))
    monkeypatch.setattr(product_service, "_property_fact_validated_source_url", lambda url: str(url))
    monkeypatch.setattr(ProductService, "_launch_property_candidate_fact_enrichment", lambda self, **kwargs: None)
    endpoint = (
        f"/app/api/signals/property/search/run/{run_id}/candidates/"
        "candidate-partial-retry/fact-enrichment"
    )
    same_origin_headers = {
        "origin": "https://propertyquarry.com",
        "sec-fetch-site": "same-origin",
    }
    try:
        started = client.post(
            endpoint,
            json={"retry_failed": False},
            headers=same_origin_headers,
        )
        assert started.status_code == 202, started.text
        started_payload = started.json()
        assert len(started_payload["fields"]) == 5
        assert next(
            row for row in started_payload["fields"] if row["key"] == "nearest_playground_m"
        )["state"] == "queued"

        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            record = product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id]
            summary = dict(record.get("summary") or {})
            jobs = dict(summary.get("fact_enrichment_jobs") or {})
            job = dict(jobs[started_payload["job_id"]])
            playground = next(
                dict(row)
                for row in list(job.get("fields") or [])
                if isinstance(row, dict) and row.get("key") == "nearest_playground_m"
            )
            playground.update(
                {
                    "state": "retryable_error",
                    "error": {
                        "code": "provider_timeout",
                        "message": "Nearby provider timed out.",
                        "retry_after_seconds": 0,
                    },
                }
            )
            job.update(
                {
                    "status": "retryable_error",
                    "retryable": True,
                    "fields": [playground],
                    "result_facts_digest": job["facts_digest"],
                }
            )
            jobs[started_payload["job_id"]] = job
            summary["fact_enrichment_jobs"] = jobs
            record["summary"] = summary

        failed_payload = client.get(endpoint).json()
        assert len(failed_payload["fields"]) == 5
        failed_supermarket = next(
            row for row in failed_payload["fields"] if row["key"] == "nearest_supermarket_m"
        )
        failed_playground = next(
            row for row in failed_payload["fields"] if row["key"] == "nearest_playground_m"
        )
        assert failed_supermarket["state"] == "resolved"
        assert failed_supermarket["value"] == 280
        assert failed_supermarket["provenance"]["provider"] == "openstreetmap_overpass"
        assert failed_playground["state"] == "retryable_error"
        assert failed_playground["error"]["code"] == "provider_timeout"

        retried = client.post(
            endpoint,
            json={"retry_failed": True},
            headers=same_origin_headers,
        )
        assert retried.status_code == 202, retried.text
        retried_payload = retried.json()
        assert len(retried_payload["fields"]) == 5
        retried_supermarket = next(
            row for row in retried_payload["fields"] if row["key"] == "nearest_supermarket_m"
        )
        retried_playground = next(
            row for row in retried_payload["fields"] if row["key"] == "nearest_playground_m"
        )
        assert retried_supermarket["state"] == "resolved"
        assert retried_supermarket["value"] == 280
        assert retried_supermarket["provenance"]["provider"] == "openstreetmap_overpass"
        assert retried_playground["state"] == "queued"
        assert retried_playground["error"]["code"] == ""
    finally:
        _clear_run(run_id)


def test_fact_enrichment_retry_backoff_and_exhaustion_are_bounded() -> None:
    now = datetime.now(timezone.utc)
    retryable_job = {
        "job_id": "pfe_" + "a" * 24,
        "status": "retryable_error",
        "attempt": 2,
        "retryable": True,
        "updated_at": (now - timedelta(seconds=17)).isoformat(),
        "fields": [
            {
                "key": "nearest_supermarket_m",
                "label": "Supermarket distance",
                "state": "retryable_error",
                "priority": "lazy",
                "affects_score": True,
                "value": None,
                "display_value": "",
                "provenance": {},
                "error": {
                    "code": "fact_provider_temporarily_unavailable",
                    "message": "Map provider unavailable.",
                    "retry_after_seconds": 60,
                },
            }
        ],
        "score": {},
    }

    assert _property_fact_retry_remaining_seconds(retryable_job, now=now) == 43
    safe_retryable = _property_fact_safe_job_payload(retryable_job)
    assert safe_retryable["status"] == "retryable_error"
    assert safe_retryable["retryable"] is True
    assert safe_retryable["fields"][0]["error"]["retry_after_seconds"] in {42, 43}

    exhausted_job = {**retryable_job, "attempt": 3}
    assert _property_fact_retry_remaining_seconds(exhausted_job, now=now) is None
    safe_exhausted = _property_fact_safe_job_payload(exhausted_job)
    assert safe_exhausted["status"] == "terminal_error"
    assert safe_exhausted["retryable"] is False
    assert safe_exhausted["fields"][0]["state"] == "unavailable"
    assert safe_exhausted["fields"][0]["error"]["code"] == "fact_enrichment_attempts_exhausted"


def test_fact_enrichment_run_mutation_retries_durable_compare_and_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-facts-cas"
    run_id = "run-property-facts-cas"
    stored = _run_record(principal_id=principal_id, run_id=run_id, candidate=_candidate())
    calls = {"cas": 0}

    monkeypatch.setattr(product_service, "_property_search_run_database_url", lambda: "postgresql://durable.test/property")
    monkeypatch.setattr(
        product_service,
        "_load_property_search_run_record_storage",
        lambda **kwargs: copy.deepcopy(stored),
    )

    def _cas(**kwargs: object) -> dict[str, object]:
        calls["cas"] += 1
        if calls["cas"] == 1:
            return {"status": "record_changed", "record_sha256": "changed"}
        updated = copy.deepcopy(kwargs["updated_record"])
        return {"status": "applied", "record": updated, "record_sha256": "applied"}

    monkeypatch.setattr(product_service, "_compare_and_swap_property_search_run_record", _cas)
    try:
        result = product_service._property_fact_mutate_run_record(
            principal_id=principal_id,
            run_id=run_id,
            mutate=lambda record: record.setdefault("fact_test_marker", "stored"),
        )

        assert result == "stored"
        assert calls["cas"] == 2
        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            assert product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id]["fact_test_marker"] == "stored"
    finally:
        _clear_run(run_id)


def test_fact_enrichment_api_is_authenticated_same_origin_and_never_accepts_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = "exec-property-facts-api"
    run_id = "run-property-facts-api"
    client = build_property_operator_client(principal_id=principal_id)
    _seed_run(_run_record(principal_id=principal_id, run_id=run_id, candidate=_candidate()))
    monkeypatch.setattr(product_service, "_property_fact_validated_source_url", lambda url: str(url))
    monkeypatch.setattr(ProductService, "_launch_property_candidate_fact_enrichment", lambda self, **kwargs: None)
    endpoint = f"/app/api/signals/property/search/run/{run_id}/candidates/candidate-facts/fact-enrichment"
    try:
        authorization = client.headers.pop("authorization")
        assert client.get(endpoint).status_code == 401
        assert client.post(endpoint, json={"retry_failed": False}).status_code == 401
        client.headers["authorization"] = authorization

        cross_origin = client.post(
            endpoint,
            json={"retry_failed": False},
            headers={"origin": "https://attacker.example", "sec-fetch-site": "cross-site"},
        )
        assert cross_origin.status_code == 403

        arbitrary_url = client.post(
            endpoint,
            json={"retry_failed": False, "property_url": "http://127.0.0.1/private"},
            headers={"origin": "https://propertyquarry.com"},
        )
        assert arbitrary_url.status_code == 422

        token_without_origin = client.post(endpoint, json={"retry_failed": False})
        assert token_without_origin.status_code == 202, token_without_origin.text

        started = client.post(
            endpoint,
            json={"retry_failed": False},
            headers={"origin": "https://propertyquarry.com", "sec-fetch-site": "same-origin"},
        )
        assert started.status_code == 202, started.text
        payload = started.json()
        assert payload["status"] == "queued"
        assert payload["candidate_ref"] == "candidate-facts"
        assert "property_url" not in payload

        with product_service._PROPERTY_SEARCH_RUN_LOCK:
            record = product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id]
            summary = dict(record.get("summary") or {})
            jobs = dict(summary.get("fact_enrichment_jobs") or {})
            job = dict(jobs[payload["job_id"]])
            job["status"] = "retryable_error"
            job["retryable"] = True
            jobs[payload["job_id"]] = job
            summary["fact_enrichment_jobs"] = jobs
            record["summary"] = summary

        retried = client.post(
            endpoint,
            json={"retry_failed": True},
            headers={"origin": "https://propertyquarry.com", "sec-fetch-site": "same-origin"},
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["job_id"] == payload["job_id"]
        assert retried.json()["attempt"] == 2
        assert retried.json()["status"] == "queued"

        polled = client.get(endpoint)
        assert polled.status_code == 200
        assert polled.json()["job_id"] == payload["job_id"]
    finally:
        _clear_run(run_id)
