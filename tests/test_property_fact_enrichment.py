from __future__ import annotations

import time
import copy
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.product.service as product_service
from app.api.dependencies import RequestContext
from app.api.routes.product_api_contracts import PropertyFactEnrichmentOut
from app.api.routes.product_api_delivery import _require_property_fact_same_origin
from app.product.property_fact_enrichment import (
    PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION,
    property_fact_requirement_plan,
    property_fact_score_projection,
)
from app.product.service import (
    ProductService,
    _property_fact_location_query_is_exact,
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
