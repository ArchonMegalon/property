from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import app.product.service as product_service
from app.domain.models import ToolInvocationResult
from app.services.propertyquarry_teable_projection import (
    PROPERTYQUARRY_TEABLE_TABLE_NAMES,
    build_propertyquarry_teable_projection_records,
)
from tests.product_test_helpers import build_product_client, start_workspace


def _propertyquarry_teable_mapping() -> dict[str, dict[str, str]]:
    return {
        table_name: {
            "table_id": f"tbl_{table_name}",
            "key_field": "projection_id",
            "field_key_type": "name",
        }
        for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
    }


def test_propertyquarry_teable_projection_covers_user_subscription_search_and_evaluations() -> None:
    records = build_propertyquarry_teable_projection_records(
        principal_id="pq-user-1",
        onboarding_status={
            "workspace": {"name": "PropertyQuarry Home", "mode": "personal", "region": "AT", "language": "de"},
            "timezone": "Europe/Vienna",
            "selected_channels": ["email", "telegram"],
            "property_search_preferences": {
                "country_code": "AT",
                "language_code": "de",
                "listing_mode": "rent",
                "property_type": "apartment",
                "location_query": "1020 Wien",
                "selected_platforms": ["willhaben"],
                "min_area_m2": 80,
                "active_search_agent_id": "agent-cr",
                "search_agents": [
                    {
                        "agent_id": "agent-cr",
                        "name": "Monteverde land search",
                        "enabled": True,
                        "country_code": "CR",
                        "region_code": "puntarenas",
                        "location_query": "Monteverde",
                        "listing_mode": "buy",
                        "property_type": "land",
                        "selected_platforms": ["re_cr_mls"],
                        "preferences_json": {
                            "country_code": "CR",
                            "region_code": "puntarenas",
                            "location_query": "Monteverde",
                            "property_type": "land",
                            "selected_platforms": ["re_cr_mls"],
                            "min_area_m2": 1200,
                        },
                    }
                ],
                "property_commercial": {
                    "active_plan_key": "plus",
                    "status": "active",
                    "active_until": "2999-01-01T00:00:00+00:00",
                    "plan_source": "payfunnels",
                    "payer_email": "billing@example.com",
                    "billing_email": "owner@example.com",
                    "internal_notes": "do-not-project",
                    "session_token": "secret-session-token",
                },
            },
        },
        search_runs=(
            {
                "run_id": "run-1",
                "principal_id": "pq-user-1",
                "status": "processed",
                "selected_platforms": ["willhaben"],
                "property_search_preferences": {"min_area_m2": 80, "selected_platforms": ["willhaben"]},
                "summary": {
                    "sources_total": 1,
                    "listing_total": 1,
                    "high_fit_total": 1,
                    "research_task_total": 1,
                    "sources": [
                        {
                            "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
                            "source_label": "Willhaben | Austria | Rent",
                            "preference_person_id": "self",
                            "provider_filter_pushdown": {
                                "version": "property_provider_filter_pushdown_v1",
                                "cache_key": "willhaben:rent:1020:min80",
                                "applied": {
                                    "min_area_m2": 80,
                                    "max_price_eur": 2200,
                                    "min_rooms": 3,
                                },
                            },
                            "provider_cache": {
                                "status": "hit",
                                "cache_key": "willhaben:rent:1020:min80",
                            },
                            "raw_listing_total": 25,
                            "scanned_listing_total": 8,
                            "listing_total": 1,
                            "filtered_area_total": 17,
                            "filtered_low_fit_total": 2,
                            "top_fit_score": 82.5,
                            "top_candidates": [
                                {
                                    "property_url": "https://www.willhaben.at/iad/object?adId=123",
                                    "listing_id": "123",
                                    "title": "Helle Wohnung",
                                    "fit_score": 82.5,
                                    "recommendation": "strong_fit",
                                    "review_url": "https://propertyquarry.com/workspace-access/review-123",
                                    "review_status": "existing",
                                    "review_task_id": "human_task:review-123",
                                    "review_task_status": "returned",
                                    "review_reused": True,
                                    "queue_item_ref": "human_task:review-123",
                                    "recommended_task_key": "crezlo_tours.create_property_tour",
                                    "tour_url": "https://propertyquarry.com/tours/123",
                                    "tour_status": "existing",
                                    "property_facts": {
                                        "area_sqm": 91,
                                        "rooms": 3,
                                        "total_rent_eur": 1850,
                                        "postal_name": "1020 Wien",
                                        "exact_address": "Praterstrasse 1",
                                        "lat": 48.21,
                                        "lng": 16.39,
                                        "cookie_state": "abc",
                                        "internal_debug": "diagnostic",
                                        "oauth_token": "sensitive",
                                    },
                                    "assessment": {"recommendation": "strong_fit"},
                                }
                            ],
                        }
                    ],
                    "research_tasks": [
                        {
                            "task_id": "run-1:123:rooms",
                            "status": "queued",
                            "field_key": "rooms",
                            "question": "How many rooms?",
                            "property_url": "https://www.willhaben.at/iad/object?adId=123",
                        }
                    ],
                },
                "research_tasks": [
                    {
                        "task_id": "run-1:123:rooms",
                        "status": "queued",
                        "field_key": "rooms",
                        "question": "How many rooms?",
                        "property_url": "https://www.willhaben.at/iad/object?adId=123",
                    }
                ],
            },
        ),
        decision_loop_rows={
            "propertyquarry_decision_ledger": [
                {
                    "decision_id": "decision-1",
                    "principal_id": "pq-user-1",
                    "person_id": "self",
                    "property_ref": "property:abc",
                    "decision_state": "needs_documents",
                    "reason_keys_json": ["no_floorplan"],
                    "source": "workbench",
                    "actor": "owner",
                    "confidence": 0.7,
                    "supersedes_decision_id": "",
                    "learning_applied": True,
                    "aggregate_candidate": False,
                    "created_at": "2026-06-13T08:00:00+00:00",
                }
            ],
            "propertyquarry_evidence_claims": [
                {
                    "claim_id": "claim-1",
                    "principal_id": "pq-user-1",
                    "person_id": "self",
                    "property_ref": "property:abc",
                    "decision_id": "decision-1",
                    "claim_type": "risk",
                    "text": "Missing or unclear: no floorplan.",
                    "source_type": "workbench",
                    "source_ref": "decision-1",
                    "confidence": "high",
                    "verification_state": "missing",
                    "privacy_class": "owner_private",
                    "allowed_outputs_json": ["owner_private", "agent_share"],
                    "expires_at": "",
                    "created_at": "2026-06-13T08:00:01+00:00",
                }
            ],
            "propertyquarry_agent_questions": [
                {
                    "task_id": "task-1",
                    "principal_id": "pq-user-1",
                    "person_id": "self",
                    "property_ref": "property:abc",
                    "decision_id": "decision-1",
                    "question_text": "Please send the floorplan with readable room dimensions.",
                    "reason_key": "no_floorplan",
                    "source_claim_id": "claim-1",
                    "status": "drafted",
                    "answer_source": "",
                    "updated_claim_id": "",
                    "created_at": "2026-06-13T08:00:02+00:00",
                }
            ],
            "propertyquarry_documents": [
                {
                    "document_id": "doc-1",
                    "principal_id": "pq-user-1",
                    "person_id": "self",
                    "property_ref": "property:abc",
                    "decision_id": "decision-1",
                    "document_type": "floorplan",
                    "source": "agent_request",
                    "privacy_class": "owner_private",
                    "verification_state": "missing",
                    "extracted_claims_json": [],
                    "missing_pages_json": [],
                    "redaction_state": "not_started",
                    "linked_risks_json": ["no_floorplan"],
                    "created_at": "2026-06-13T08:00:03+00:00",
                }
            ],
        },
    )

    assert records["propertyquarry_tenants"][0]["tenant_key"] == "propertyquarry"
    assert records["propertyquarry_users"][0]["principal_id"] == "pq-user-1"
    assert records["propertyquarry_subscriptions"][0]["current_plan_key"] == "plus"
    assert "payer_email" not in records["propertyquarry_subscriptions"][0]["commercial_json"]
    assert "billing_email" not in records["propertyquarry_subscriptions"][0]["commercial_json"]
    assert "internal_notes" not in records["propertyquarry_subscriptions"][0]["commercial_json"]
    assert "session_token" not in records["propertyquarry_subscriptions"][0]["commercial_json"]
    assert records["propertyquarry_preferences"][0]["min_area_m2"] == 80
    assert "property_commercial" not in records["propertyquarry_preferences"][0]["preferences_json"]
    assert "raw_preferences" not in records["propertyquarry_preferences"][0]["preferences_json"]
    projected_preferences = records["propertyquarry_preferences"][0]["preferences_json"]
    assert projected_preferences["active_search_agent_id"] == "agent-cr"
    assert projected_preferences["search_agents"][0]["preferences_json"]["location_query"] == "Monteverde"
    assert projected_preferences["search_agents"][0]["preferences_json"]["property_type"] == "land"
    assert records["propertyquarry_search_agents"][0]["agent_id"] == "agent-cr"
    assert records["propertyquarry_search_agents"][0]["name"] == "Monteverde land search"
    assert records["propertyquarry_search_agents"][0]["is_active"] is True
    assert records["propertyquarry_search_agents"][0]["country_code"] == "CR"
    assert records["propertyquarry_search_agents"][0]["region_code"] == "puntarenas"
    assert records["propertyquarry_search_agents"][0]["location_query"] == "Monteverde"
    assert records["propertyquarry_search_agents"][0]["property_type"] == "land"
    assert records["propertyquarry_search_agents"][0]["selected_platforms_json"] == ["re_cr_mls"]
    assert records["propertyquarry_search_agents"][0]["preferences_json"]["min_area_m2"] == 1200
    assert "property_commercial" not in records["propertyquarry_search_agents"][0]["preferences_json"]
    assert "raw_preferences" not in records["propertyquarry_search_agents"][0]["preferences_json"]
    assert records["propertyquarry_search_runs"][0]["run_id"] == "run-1"
    assert "property_commercial" not in records["propertyquarry_search_runs"][0]["preferences_json"]
    assert records["propertyquarry_provider_sources"][0]["platform"] == "willhaben"
    assert records["propertyquarry_provider_sources"][0]["provider_cache_status"] == "hit"
    assert records["propertyquarry_provider_sources"][0]["provider_cache_key"] == "willhaben:rent:1020:min80"
    assert records["propertyquarry_provider_sources"][0]["min_area_m2"] == 80
    assert records["propertyquarry_provider_sources"][0]["filtered_area_total"] == 17
    assert "top_candidates" not in records["propertyquarry_provider_sources"][0]["source_json"]
    assert records["propertyquarry_provider_sources"][0]["source_json"]["source_url"].startswith("https://www.willhaben.at/")
    assert records["propertyquarry_properties"][0]["area_sqm"] == 91
    assert "exact_address" not in records["propertyquarry_properties"][0]["facts_json"]
    assert "lat" not in records["propertyquarry_properties"][0]["facts_json"]
    assert "lng" not in records["propertyquarry_properties"][0]["facts_json"]
    assert "cookie_state" not in records["propertyquarry_properties"][0]["facts_json"]
    assert "internal_debug" not in records["propertyquarry_properties"][0]["facts_json"]
    assert "oauth_token" not in records["propertyquarry_properties"][0]["facts_json"]
    assert records["propertyquarry_property_evaluations"][0]["fit_score"] == 82.5
    assert "exact_address" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert "lat" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert "lng" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert records["propertyquarry_review_artifacts"][0]["review_reused"] is True
    assert records["propertyquarry_review_artifacts"][0]["review_task_status"] == "returned"
    assert records["propertyquarry_review_artifacts"][0]["tour_status"] == "existing"
    artifact_json = records["propertyquarry_review_artifacts"][0]["artifact_json"]
    artifact_dump = json.dumps(artifact_json)
    assert "exact_address" not in artifact_dump
    assert "lat" not in artifact_dump
    assert "lng" not in artifact_dump
    assert "cookie_state" not in artifact_dump
    assert "internal_debug" not in artifact_dump
    assert "oauth_token" not in artifact_dump
    assert records["propertyquarry_research_tasks"][0]["field_key"] == "rooms"
    assert records["propertyquarry_decision_ledger"][0]["decision_state"] == "needs_documents"
    assert records["propertyquarry_decision_ledger"][0]["reason_keys_json"] == ["no_floorplan"]
    assert records["propertyquarry_evidence_claims"][0]["claim_text"] == "Missing or unclear: no floorplan."
    assert records["propertyquarry_evidence_claims"][0]["privacy_class"] == "owner_private"
    assert records["propertyquarry_agent_questions"][0]["reason_key"] == "no_floorplan"
    assert records["propertyquarry_agent_questions"][0]["question_text"].startswith("Please send the floorplan")
    assert records["propertyquarry_documents"][0]["document_type"] == "floorplan"
    assert records["propertyquarry_documents"][0]["linked_risks_json"] == ["no_floorplan"]


def test_propertyquarry_teable_sync_preview_fails_closed_without_property_table_mapping(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    monkeypatch.delenv("TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    client = build_product_client(principal_id="pq-teable-preview")
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    response = client.get("/app/api/property/teable-sync-preview")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "propertyquarry_teable_table_sync_config_missing"
    assert set(body["provider"]["missing_tables"]) == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    assert body["projection_summary"]["projection_scope"] == "propertyquarry"


def test_propertyquarry_teable_sync_uses_dedicated_property_tables_when_ready(monkeypatch) -> None:
    client = build_product_client(principal_id="pq-teable-ready")
    container = client.app.state.container
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")
    monkeypatch.setenv("PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON", json.dumps(_propertyquarry_teable_mapping()))
    monkeypatch.delenv("TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    monkeypatch.setattr(
        container.provider_registry,
        "candidate_routes_by_capability_with_context",
        lambda **_: (
            SimpleNamespace(
                provider_key="teable",
                capability_key="table_sync",
                tool_name="provider.teable.table_sync",
                executable=True,
            ),
        ),
    )
    monkeypatch.setattr(
        container.provider_registry,
        "binding_state",
        lambda provider_key, principal_id=None: SimpleNamespace(
            provider_key=provider_key,
            display_name="Teable",
            state="ready",
            enabled=True,
            executable=True,
            binding_id=f"{principal_id}:teable",
            secret_configured=True,
            updated_at="2026-06-06T00:00:00Z",
        ),
    )
    monkeypatch.setattr(product_service.ProductService, "_teable_sync_runtime_available", lambda self, *, base_url: (True, ""))

    def _execute(invocation):
        assert invocation.tool_name == "provider.teable.table_sync"
        assert invocation.action_kind == "table.sync"
        assert invocation.payload_json["projection_scope"] == "propertyquarry"
        assert set(invocation.payload_json["tables_json"]) == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
        assert "propertyquarry_users" in invocation.payload_json["table_config_json"]
        assert "preference_review_queue" not in invocation.payload_json["table_config_json"]
        return ToolInvocationResult(
            tool_name=invocation.tool_name,
            action_kind=invocation.action_kind,
            target_ref="teable-sync:propertyquarry:propertyquarry",
            output_json={"synced_tables": list(PROPERTYQUARRY_TEABLE_TABLE_NAMES)},
            receipt_json={"status": "pass", "rows_upserted": 4},
        )

    monkeypatch.setattr(container.tool_execution, "execute_invocation", _execute)

    response = client.post("/app/api/property/teable-sync")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["sync_attempted"] is True
    assert body["sync_result"] == "sent"
    assert body["tool_execution"]["receipt_json"]["rows_upserted"] == 4


def test_propertyquarry_teable_bootstrap_preview_has_all_property_tables() -> None:
    script = Path("scripts/bootstrap_propertyquarry_teable_tenant.py")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "preview"
    assert set(payload["mapping_preview"]) == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    assert "propertyquarry_users" in payload["tables"]
    assert "propertyquarry_provider_sources" in payload["tables"]
    assert "propertyquarry_review_artifacts" in payload["tables"]
    assert payload["tables"]["propertyquarry_properties"][0]["name"] == "projection_id"
