from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import app.product.service as product_service
import app.services.propertyquarry_teable_projection as pq_teable_projection
from app.domain.models import ToolInvocationResult
from app.services.propertyquarry_teable_projection import (
    PROPERTYQUARRY_TEABLE_TABLE_NAMES,
    build_propertyquarry_teable_projection_records,
    discover_propertyquarry_teable_table_config,
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
            "delivery_preferences": {
                "property_notifications": {
                    "preferred_channel": "whatsapp",
                    "preferred_label": "WhatsApp",
                    "notification_scope": "scout_updates",
                    "whatsapp_notification_opt_in": True,
                    "whatsapp_ai_support_phone": "+436641234567",
                    "whatsapp_ai_support_purpose": "propertyquarry_ai_support_only",
                    "signal_status": "coming_soon",
                    "telegram_bot": {"status_label": "Open the bot and send /start"},
                }
            },
            "property_search_preferences": {
                "country_code": "AT",
                "language_code": "de",
                "listing_mode": "rent",
                "property_type": "apartment",
                "location_query": "1020 Wien",
                "selected_platforms": ["willhaben"],
                "min_area_m2": 80,
                "saved_shortlist_candidates": [
                    {
                        "candidate_ref": "saved-123",
                        "property_url": "https://www.willhaben.at/iad/object?adId=123",
                        "listing_id": "123",
                        "title": "Helle Wohnung",
                        "source_label": "Willhaben",
                        "fit_score": 82.5,
                        "rank": 1,
                        "review_url": "https://propertyquarry.com/workspace-access/review-123",
                        "public_packet_url": "https://propertyquarry.com/p/packet-123",
                        "tour_url": "https://propertyquarry.com/tours/123",
                        "tour_status": "existing",
                        "walkthrough_url": "https://propertyquarry.com/walkthroughs/123",
                        "walkthrough_status": "ready",
                        "saved_from_run_id": "run-previous",
                        "property_facts": {
                            "area_sqm": 91,
                            "rooms": 3,
                            "exact_address": "Praterstrasse 1",
                            "lat": 48.21,
                            "lng": 16.39,
                            "oauth_token": "do-not-sync",
                        },
                    }
                ],
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
                                    "public_packet_url": "https://propertyquarry.com/p/packet-123",
                                    "review_task_id": "human_task:review-123",
                                    "review_task_status": "returned",
                                    "review_reused": True,
                                    "queue_item_ref": "human_task:review-123",
                                    "recommended_task_key": "crezlo_tours.create_property_tour",
                                    "tour_url": "https://propertyquarry.com/tours/123",
                                    "tour_status": "existing",
                                    "walkthrough_url": "https://propertyquarry.com/walkthroughs/123",
                                    "walkthrough_status": "ready",
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
                    "property_ref": "https://www.willhaben.at/iad/object?adId=123",
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
                    "property_ref": "https://www.willhaben.at/iad/object?adId=123",
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
                    "property_ref": "https://www.willhaben.at/iad/object?adId=123",
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
                    "property_ref": "https://www.willhaben.at/iad/object?adId=123",
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
    assert records["propertyquarry_delivery_settings"][0]["principal_id"] == "pq-user-1"
    assert records["propertyquarry_delivery_settings"][0]["preferred_channel"] == "whatsapp"
    assert records["propertyquarry_delivery_settings"][0]["whatsapp_notification_opt_in"] is True
    assert records["propertyquarry_delivery_settings"][0]["whatsapp_enabled"] is True
    assert records["propertyquarry_delivery_settings"][0]["whatsapp_ai_support_phone"] == "+436641234567"
    assert records["propertyquarry_delivery_settings"][0]["whatsapp_ai_support_phone_last4"] == "4567"
    assert records["propertyquarry_delivery_settings"][0]["whatsapp_ai_support_purpose"] == "ai_support_only"
    assert records["propertyquarry_delivery_settings"][0]["settings_json"]["whatsapp_ai_support_purpose"] == "ai_support_only"
    assert records["propertyquarry_delivery_settings"][0]["signal_status"] == "coming_soon"
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
    assert records["propertyquarry_search_agents"][0]["principal_id"].startswith("principal:")
    assert records["propertyquarry_search_agents"][0]["principal_id"] != "pq-user-1"
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
    assert records["propertyquarry_saved_shortlist"][0]["title"] == "Helle Wohnung"
    assert records["propertyquarry_saved_shortlist"][0]["saved_from_run_id"] == "run-previous"
    assert (
        records["propertyquarry_saved_shortlist"][0]["property_ref"]
        == records["propertyquarry_property_evaluations"][0]["property_ref"]
    )
    assert "exact_address" not in records["propertyquarry_saved_shortlist"][0]["facts_json"]
    assert "lat" not in records["propertyquarry_saved_shortlist"][0]["facts_json"]
    assert "lng" not in records["propertyquarry_saved_shortlist"][0]["facts_json"]
    assert "oauth_token" not in records["propertyquarry_saved_shortlist"][0]["facts_json"]
    assert "exact_address" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert "lat" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert "lng" not in records["propertyquarry_property_evaluations"][0]["facts_json"]
    assert records["propertyquarry_review_artifacts"][0]["review_reused"] is True
    assert records["propertyquarry_review_artifacts"][0]["review_task_status"] == "returned"
    assert records["propertyquarry_review_artifacts"][0]["tour_status"] == "existing"
    shared_artifact_kinds = {
        row["artifact_kind"]
        for row in records["propertyquarry_shared_artifacts"]
        if row["property_ref"] == records["propertyquarry_property_evaluations"][0]["property_ref"]
    }
    assert {"review", "public_packet", "tour", "walkthrough"}.issubset(shared_artifact_kinds)
    assert all(row["visibility"] in {"private_workspace", "signed_public"} for row in records["propertyquarry_shared_artifacts"])
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
    assert records["propertyquarry_decision_ledger"][0]["principal_id"].startswith("principal:")
    assert records["propertyquarry_decision_ledger"][0]["person_id"].startswith("person:")
    assert (
        records["propertyquarry_decision_ledger"][0]["property_ref"]
        == records["propertyquarry_property_evaluations"][0]["property_ref"]
    )
    assert records["propertyquarry_decision_ledger"][0]["reason_keys_json"] == ["no_floorplan"]
    assert records["propertyquarry_evidence_claims"][0]["claim_text"] == "Missing or unclear: no floorplan."
    assert (
        records["propertyquarry_evidence_claims"][0]["property_ref"]
        == records["propertyquarry_property_evaluations"][0]["property_ref"]
    )
    assert records["propertyquarry_evidence_claims"][0]["source_ref"].startswith("source:")
    assert records["propertyquarry_evidence_claims"][0]["privacy_class"] == "owner_private"
    assert records["propertyquarry_agent_questions"][0]["reason_key"] == "no_floorplan"
    assert (
        records["propertyquarry_agent_questions"][0]["property_ref"]
        == records["propertyquarry_property_evaluations"][0]["property_ref"]
    )
    assert records["propertyquarry_agent_questions"][0]["question_text"].startswith("Please send the floorplan")
    assert records["propertyquarry_documents"][0]["document_type"] == "floorplan"
    assert (
        records["propertyquarry_documents"][0]["property_ref"]
        == records["propertyquarry_property_evaluations"][0]["property_ref"]
    )
    assert records["propertyquarry_documents"][0]["linked_risks_json"] == ["no_floorplan"]


def test_propertyquarry_teable_schema_has_unique_field_names() -> None:
    for table_name, fields in pq_teable_projection.PROPERTYQUARRY_TEABLE_TABLE_FIELDS.items():
        field_names = [str(field.get("name") or "").strip() for field in fields]
        assert len(field_names) == len(set(field_names)), table_name


def test_propertyquarry_teable_sync_redacts_raw_human_feedback_claim_text() -> None:
    records = build_propertyquarry_teable_projection_records(
        principal_id="pq-user-1",
        onboarding_status={},
        decision_loop_rows={
            "propertyquarry_evidence_claims": [
                {
                    "claim_id": "claim-human-1",
                    "principal_id": "pq-user-1",
                    "person_id": "self",
                    "property_ref": "property:abc",
                    "decision_id": "decision-1",
                    "claim_type": "human_feedback",
                    "text": "The owner said the bedroom feels unsafe and too noisy.",
                    "source_type": "workbench",
                    "source_ref": "decision-1",
                    "confidence": "medium",
                    "verification_state": "pending",
                    "privacy_class": "owner_private",
                    "allowed_outputs_json": ["owner_private"],
                    "created_at": "2026-06-13T08:00:01+00:00",
                }
            ]
        },
    )

    assert records["propertyquarry_evidence_claims"][0]["claim_text"] == ""
    assert records["propertyquarry_evidence_claims"][0]["principal_id"].startswith("principal:")
    assert records["propertyquarry_evidence_claims"][0]["property_ref"] == "property:abc"


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


def test_propertyquarry_teable_sync_discovers_property_tables_from_base_credentials(monkeypatch) -> None:
    client = build_product_client(principal_id="pq-teable-discovery")
    container = client.app.state.container
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")
    monkeypatch.delenv("PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    monkeypatch.delenv("TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    monkeypatch.setenv("TEABLE_API_KEY", "teable-key")
    monkeypatch.delenv("PROPERTYQUARRY_TEABLE_BASE_ID", raising=False)
    monkeypatch.delenv("TEABLE_BASE_ID", raising=False)
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable.example")
    discovery_calls: list[dict[str, object]] = []

    def _discover(**kwargs):
        discovery_calls.append(dict(kwargs))
        return _propertyquarry_teable_mapping()

    monkeypatch.setattr(
        product_service,
        "discover_propertyquarry_teable_table_config",
        _discover,
    )
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
            updated_at="2026-06-21T00:00:00Z",
        ),
    )
    monkeypatch.setattr(product_service.ProductService, "_teable_sync_runtime_available", lambda self, *, base_url: (True, ""))

    response = client.get("/app/api/property/teable-sync-preview")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["provider"]["table_sync_configured"] is True
    assert body["provider"]["missing_tables"] == []
    assert set(body["sync_payload_json"]["table_config_json"]) == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    assert discovery_calls[0]["base_id"] == ""
    assert discovery_calls[0]["base_name"] == "PropertyQuarry"


def test_propertyquarry_teable_table_discovery_resolves_propertyquarry_base_by_name(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, payload: object) -> None:
            self._payload = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return self._payload

    def _urlopen(request, timeout=20):  # noqa: ANN001
        url = str(getattr(request, "full_url", request))
        if url == "https://teable.example/api/space":
            return _FakeResponse({"spaces": [{"id": "space-1", "role": "owner"}]})
        if url == "https://teable.example/api/space/space-1/base":
            return _FakeResponse(
                {
                    "data": [
                        {"id": "base-other", "name": "Other"},
                        {"id": "base-pq", "name": "PropertyQuarry"},
                    ]
                }
            )
        if url == "https://teable.example/api/base/base-pq/table":
            return _FakeResponse(
                {"tables": [{"id": f"tbl_{table_name}", "name": table_name} for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES]}
            )
        raise AssertionError(f"unexpected Teable URL: {url}")

    monkeypatch.setattr(pq_teable_projection.urllib.request, "urlopen", _urlopen)

    config = discover_propertyquarry_teable_table_config(
        base_url="https://teable.example",
        api_key="teable-key",
        base_id="",
        base_name="PropertyQuarry",
    )

    assert set(config) == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    assert config["propertyquarry_delivery_settings"]["table_id"] == "tbl_propertyquarry_delivery_settings"


def test_propertyquarry_teable_sync_keeps_projection_state_when_migrating_teable_host(monkeypatch) -> None:
    client = build_product_client(principal_id="pq-teable-portable")
    container = client.app.state.container
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    monkeypatch.setenv("PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON", json.dumps(_propertyquarry_teable_mapping()))
    monkeypatch.delenv("TEABLE_TABLE_SYNC_CONFIG_JSON", raising=False)
    monkeypatch.setenv("TEABLE_API_KEY", "teable-key-host-a")
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable-primary.example")
    monkeypatch.setenv("PROPERTYQUARRY_TEABLE_AUTO_SYNC", "1")

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

    captured_payloads: list[dict[str, object]] = []

    def _runtime_available(self: product_service.ProductService, *, base_url: str) -> tuple[bool, str]:
        return True, ""

    def _execute(invocation):
        captured_payloads.append(
            {
                "tool_name": invocation.tool_name,
                "action_kind": invocation.action_kind,
                "context_json": dict(invocation.context_json or {}),
                "payload_json": dict(invocation.payload_json or {}),
            }
        )
        return ToolInvocationResult(
            tool_name=invocation.tool_name,
            action_kind=invocation.action_kind,
            target_ref="teable-sync:propertyquarry:propertyquarry",
            output_json={"synced_tables": list(PROPERTYQUARRY_TEABLE_TABLE_NAMES)},
            receipt_json={"status": "pass", "rows_upserted": 4},
        )

    monkeypatch.setattr(product_service.ProductService, "_teable_sync_runtime_available", _runtime_available)
    monkeypatch.setattr(container.tool_execution, "execute_invocation", _execute)

    volatile_payload_fields = {"last_projected_at", "last_synced_at", "created_at", "updated_at", "updated_time"}

    def _stable_payload(payload_json: dict[str, object]) -> dict[str, list[dict[str, object]]]:
        tables_payload = payload_json["tables_json"]
        stable: dict[str, list[dict[str, object]]] = {}
        for table_name, rows in tables_payload.items():
            stable_rows: list[dict[str, object]] = []
            for raw_row in rows:
                row = dict(raw_row)  # type: ignore[arg-type]
                for volatile_key in volatile_payload_fields:
                    row.pop(volatile_key, None)
                stable_rows.append(row)
            stable[table_name] = stable_rows
        return stable

    first_preview = client.get("/app/api/property/teable-sync-preview")
    assert first_preview.status_code == 200
    first_payload = first_preview.json()["sync_payload_json"]
    first_preview_body = first_preview.json()

    first_sync = client.post("/app/api/property/teable-sync")
    assert first_sync.status_code == 200
    first_sync_body = first_sync.json()

    assert first_preview_body["status"] == "ready"
    assert first_preview_body["provider"]["base_url"] == "https://teable-primary.example"
    assert first_sync_body["sync_attempted"] is True
    assert first_sync_body["sync_result"] == "sent"

    assert first_sync_body["tool_execution"]["receipt_json"]["rows_upserted"] == 4
    assert len(captured_payloads) == 1
    assert captured_payloads[0]["payload_json"]["projection_scope"] == "propertyquarry"
    assert "teable-key-host-a" not in json.dumps(captured_payloads[0]["payload_json"])

    # simulate migration: only Teable credentials/endpoint changed
    monkeypatch.setenv("TEABLE_API_KEY", "teable-key-host-b")
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable-secondary.example")

    second_preview = client.get("/app/api/property/teable-sync-preview")
    assert second_preview.status_code == 200
    second_preview_body = second_preview.json()

    second_sync = client.post("/app/api/property/teable-sync")
    assert second_sync.status_code == 200
    second_sync_body = second_sync.json()

    assert second_preview_body["provider"]["base_url"] == "https://teable-secondary.example"
    assert second_sync_body["sync_result"] == "sent"
    assert second_sync_body["tool_execution"]["receipt_json"]["rows_upserted"] == 4
    assert len(captured_payloads) == 2
    assert captured_payloads[1]["payload_json"]["projection_scope"] == "propertyquarry"
    assert _stable_payload(captured_payloads[1]["payload_json"]) == _stable_payload(first_payload)
    assert "teable-key-host-b" not in json.dumps(captured_payloads[1]["payload_json"])

    assert (
        second_preview_body["projection_summary"]
        == first_preview_body["projection_summary"]
    )


def test_propertyquarry_teable_restore_bundle_recovers_results_and_delivery_settings() -> None:
    namespace = runpy.run_path("scripts/restore_propertyquarry_from_teable.py", run_name="__test__")
    build_restore_bundle = namespace["build_restore_bundle"]
    principal_alias = namespace["_projection_alias"]("pq-restore-user", prefix="principal")
    person_alias = namespace["_projection_alias"]("self", prefix="person")

    bundle = build_restore_bundle(
        principal_id="pq-restore-user",
        records_by_table={
            "propertyquarry_users": [
                {
                    "principal_id": "pq-restore-user",
                    "workspace_name": "Restored PropertyQuarry",
                    "workspace_mode": "personal",
                    "region": "AT",
                    "language": "de",
                    "timezone": "Europe/Vienna",
                    "selected_channels_json": ["email"],
                }
            ],
            "propertyquarry_delivery_settings": [
                {
                    "principal_id": "pq-restore-user",
                    "preferred_channel": "whatsapp",
                    "preferred_label": "WhatsApp",
                    "notification_scope": "scout_updates",
                    "selected_channels_json": ["email", "whatsapp"],
                    "whatsapp_notification_opt_in": True,
                    "whatsapp_ai_support_phone": "+436641234567",
                    "whatsapp_ai_support_purpose": "propertyquarry_ai_support_only",
                    "signal_status": "coming_soon",
                }
            ],
            "propertyquarry_preferences": [
                {
                    "principal_id": "pq-restore-user",
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "location_query": "1020 Wien",
                    "selected_platforms_json": ["willhaben"],
                    "preferences_json": {"min_area_m2": 80},
                }
            ],
            "propertyquarry_subscriptions": [
                {
                    "principal_id": "pq-restore-user",
                    "current_plan_key": "plus",
                    "status": "active",
                    "active_until": "2999-01-01T00:00:00+00:00",
                    "is_paid": True,
                    "plan_source": "paypal",
                    "last_order_id": "ORDER-RESTORE-1",
                    "last_payment_status": "captured",
                    "commercial_json": {
                        "active_plan_key": "plus",
                        "status": "active",
                        "active_until": "2999-01-01T00:00:00+00:00",
                        "last_order_id": "ORDER-RESTORE-1",
                        "last_payment_status": "captured",
                        "plan_source": "paypal",
                    },
                }
            ],
            "propertyquarry_search_agents": [
                {
                    "principal_id": principal_alias,
                    "agent_id": "agent-vienna-family",
                    "name": "Vienna family watch",
                    "enabled": True,
                    "is_active": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Wien",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "selected_platforms_json": ["willhaben"],
                    "duration_days": 30,
                    "notification_limit": 5,
                    "notification_period": "day",
                    "sent_in_current_window": 2,
                    "preferences_json": {
                        "country_code": "AT",
                        "location_query": "1020 Wien",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "selected_platforms": ["willhaben"],
                        "min_area_m2": 80,
                    },
                }
            ],
            "propertyquarry_properties": [
                {
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "listing_id": "restore-1",
                    "title": "Restored flat",
                    "source_label": "Willhaben",
                    "facts_json": {"area_sqm": 91, "rooms": 3, "postal_name": "1020 Wien"},
                }
            ],
            "propertyquarry_property_evaluations": [
                {
                    "principal_id": "pq-restore-user",
                    "run_id": "lost-run",
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "source_label": "Willhaben",
                    "fit_score": 84,
                    "recommendation": "strong_fit",
                    "fit_summary": "Strong fit",
                    "review_url": "https://propertyquarry.com/app/research/restore-1",
                    "tour_url": "https://propertyquarry.com/tours/restore-1",
                    "tour_status": "ready",
                    "facts_json": {"area_sqm": 91, "rooms": 3, "postal_name": "1020 Wien"},
                }
            ],
            "propertyquarry_review_artifacts": [
                {
                    "principal_id": "pq-restore-user",
                    "run_id": "lost-run",
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "source_label": "Willhaben",
                    "review_url": "https://propertyquarry.com/app/research/restore-1",
                    "review_status": "ready",
                    "review_task_id": "human_task:restore-review",
                    "review_task_status": "returned",
                    "review_reused": True,
                    "queue_item_ref": "queue:restore-review",
                    "recommended_task_key": "request_floorplan",
                    "tour_url": "https://propertyquarry.com/tours/restore-1",
                    "tour_status": "ready",
                    "tour_blocked_reason": "",
                    "artifact_json": {
                        "review_status": "ready",
                        "review_task_status": "returned",
                        "compare_reason": "Best restored review candidate",
                    },
                }
            ],
            "propertyquarry_shared_artifacts": [
                {
                    "principal_id": "pq-restore-user",
                    "run_id": "lost-run",
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "artifact_kind": "public_packet",
                    "artifact_url": "https://propertyquarry.com/p/restore-1",
                    "artifact_status": "ready",
                    "visibility": "signed_public",
                },
                {
                    "principal_id": "pq-restore-user",
                    "run_id": "lost-run",
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "artifact_kind": "walkthrough",
                    "artifact_url": "https://propertyquarry.com/walkthroughs/restore-1",
                    "artifact_status": "ready",
                    "visibility": "private_workspace",
                },
            ],
            "propertyquarry_research_tasks": [
                {
                    "principal_id": "pq-restore-user",
                    "run_id": "lost-run",
                    "task_id": "research-restore-rooms",
                    "status": "open",
                    "field_key": "rooms",
                    "label": "Rooms",
                    "question": "Verify the room count from the provider detail page.",
                    "property_ref": "property:restore-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=restore-1",
                    "task_json": {
                        "task_id": "research-restore-rooms",
                        "status": "open",
                        "field_key": "rooms",
                        "priority": "high",
                    },
                }
            ],
            "propertyquarry_decision_ledger": [
                {
                    "principal_id": principal_alias,
                    "person_id": person_alias,
                    "decision_id": "decision-restore-1",
                    "property_ref": "property:restore-1",
                    "decision_state": "needs_documents",
                    "reason_keys_json": ["no_floorplan"],
                    "source": "workbench",
                    "actor": "browser",
                    "confidence": 0.7,
                    "learning_applied": True,
                    "aggregate_candidate": False,
                    "created_at": "2026-06-20T10:00:00+00:00",
                }
            ],
            "propertyquarry_evidence_claims": [
                {
                    "principal_id": principal_alias,
                    "person_id": person_alias,
                    "claim_id": "claim-restore-1",
                    "property_ref": "property:restore-1",
                    "decision_id": "decision-restore-1",
                    "claim_type": "risk",
                    "claim_text": "Missing or unclear: no floorplan.",
                    "source_type": "workbench",
                    "source_ref": "decision-restore-1",
                    "confidence": "high",
                    "verification_state": "missing",
                    "privacy_class": "owner_private",
                    "allowed_outputs_json": ["owner_private", "agent_share"],
                    "created_at": "2026-06-20T10:00:01+00:00",
                }
            ],
            "propertyquarry_agent_questions": [
                {
                    "principal_id": principal_alias,
                    "person_id": person_alias,
                    "task_id": "question-restore-1",
                    "property_ref": "property:restore-1",
                    "decision_id": "decision-restore-1",
                    "question_text": "Please send the floorplan with readable room dimensions.",
                    "reason_key": "no_floorplan",
                    "source_claim_id": "claim-restore-1",
                    "status": "drafted",
                    "created_at": "2026-06-20T10:00:02+00:00",
                }
            ],
            "propertyquarry_documents": [
                {
                    "principal_id": principal_alias,
                    "person_id": person_alias,
                    "document_id": "document-restore-1",
                    "property_ref": "property:restore-1",
                    "decision_id": "decision-restore-1",
                    "document_type": "floorplan",
                    "source": "agent_request",
                    "privacy_class": "owner_private",
                    "verification_state": "missing",
                    "linked_risks_json": ["no_floorplan"],
                    "created_at": "2026-06-20T10:00:03+00:00",
                }
            ],
        },
    )

    state = bundle["onboarding_state"]
    assert bundle["saved_result_count"] == 1
    assert state["workspace_name"] == "Restored PropertyQuarry"
    assert state["selected_channels"] == ["email", "whatsapp"]
    notifications = state["channel_preferences_json"]["property_notifications"]
    assert notifications["preferred_channel"] == "whatsapp"
    assert notifications["whatsapp_ai_support_phone"] == "+436641234567"
    preferences = state["property_search_preferences_json"]
    assert preferences["location_query"] == "1020 Wien"
    assert preferences["selected_platforms"] == ["willhaben"]
    assert preferences["property_commercial"]["active_plan_key"] == "plus"
    assert preferences["property_commercial"]["status"] == "active"
    assert preferences["property_commercial"]["last_order_id"] == "ORDER-RESTORE-1"
    assert preferences["property_commercial"]["last_payment_status"] == "captured"
    assert bundle["subscription_restored"] is True
    assert preferences["active_search_agent_id"] == "agent-vienna-family"
    assert preferences["search_agents"][0]["agent_id"] == "agent-vienna-family"
    assert preferences["search_agents"][0]["is_active"] is True
    assert preferences["search_agents"][0]["selected_platforms"] == ["willhaben"]
    assert preferences["search_agents"][0]["preferences_json"]["min_area_m2"] == 80
    assert preferences["saved_shortlist_candidates"][0]["title"] == "Restored flat"
    assert preferences["saved_shortlist_candidates"][0]["saved_from_run_id"] == "lost-run"
    assert preferences["saved_shortlist_candidates"][0]["review_task_id"] == "human_task:restore-review"
    assert preferences["saved_shortlist_candidates"][0]["review_task_status"] == "returned"
    assert preferences["saved_shortlist_candidates"][0]["queue_item_ref"] == "queue:restore-review"
    assert preferences["saved_shortlist_candidates"][0]["compare_reason"] == "Best restored review candidate"
    assert preferences["saved_shortlist_candidates"][0]["public_packet_url"] == "https://propertyquarry.com/p/restore-1"
    assert preferences["saved_shortlist_candidates"][0]["walkthrough_url"] == "https://propertyquarry.com/walkthroughs/restore-1"
    assert preferences["saved_shortlist_candidates"][0]["walkthrough_status"] == "ready"
    assert preferences["saved_shortlist_candidates"][0]["research_task_total"] == 1
    assert preferences["saved_shortlist_candidates"][0]["open_research_task_total"] == 1
    assert preferences["saved_shortlist_candidates"][0]["research_tasks"][0]["field_key"] == "rooms"
    assert preferences["saved_shortlist_candidates"][0]["research_tasks"][0]["priority"] == "high"
    assert preferences["restored_research_tasks"][0]["task_id"] == "research-restore-rooms"
    assert bundle["review_artifact_count"] == 1
    assert bundle["shared_artifact_count"] == 2
    assert bundle["research_task_count"] == 1
    assert bundle["decision_loop_counts"] == {
        "propertyquarry_agent_questions": 1,
        "propertyquarry_decision_ledger": 1,
        "propertyquarry_documents": 1,
        "propertyquarry_evidence_claims": 1,
    }
    decision_rows = bundle["decision_loop_rows"]["propertyquarry_decision_ledger"]
    assert decision_rows[0]["principal_id"] == "pq-restore-user"
    assert decision_rows[0]["person_id"] == "self"
    assert decision_rows[0]["decision_state"] == "needs_documents"
    assert bundle["decision_loop_rows"]["propertyquarry_agent_questions"][0]["question_text"].startswith(
        "Please send the floorplan"
    )
    assert bundle["decision_loop_rows"]["propertyquarry_documents"][0]["document_type"] == "floorplan"


def test_propertyquarry_teable_restore_recovers_saved_shortlist_without_runs() -> None:
    namespace = runpy.run_path("scripts/restore_propertyquarry_from_teable.py", run_name="__test__")
    build_restore_bundle = namespace["build_restore_bundle"]

    bundle = build_restore_bundle(
        principal_id="pq-restore-saved",
        records_by_table={
            "propertyquarry_users": [
                {
                    "principal_id": "pq-restore-saved",
                    "workspace_name": "Saved Results",
                    "workspace_mode": "personal",
                    "selected_channels_json": ["email"],
                }
            ],
            "propertyquarry_preferences": [
                {
                    "principal_id": "pq-restore-saved",
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "location_query": "1020 Wien",
                    "selected_platforms_json": ["willhaben"],
                    "preferences_json": {"min_area_m2": 80},
                }
            ],
            "propertyquarry_saved_shortlist": [
                {
                    "principal_id": "pq-restore-saved",
                    "property_ref": "property:saved-1",
                    "candidate_ref": "saved-1",
                    "property_url": "https://www.willhaben.at/iad/object?adId=saved-1",
                    "listing_id": "saved-1",
                    "title": "Saved flat",
                    "source_label": "Willhaben",
                    "fit_score": 91,
                    "rank": 1,
                    "saved_from_run_id": "old-run",
                    "review_url": "https://propertyquarry.com/app/research/saved-1",
                    "tour_url": "https://propertyquarry.com/tours/saved-1",
                    "tour_status": "ready",
                    "facts_json": {"area_sqm": 88, "rooms": 3, "postal_name": "1020 Wien"},
                    "candidate_json": {"recommendation": "strong_fit"},
                    "saved_at": "2026-06-20T10:00:00+00:00",
                }
            ],
            "propertyquarry_property_evaluations": [],
            "propertyquarry_search_runs": [],
        },
    )

    preferences = bundle["onboarding_state"]["property_search_preferences_json"]
    assert bundle["saved_result_count"] == 1
    assert preferences["saved_shortlist_candidates"][0]["property_ref"] == "property:saved-1"
    assert preferences["saved_shortlist_candidates"][0]["title"] == "Saved flat"
    assert preferences["saved_shortlist_candidates"][0]["saved_from_run_id"] == "old-run"
    assert preferences["saved_shortlist_candidates"][0]["recommendation"] == "strong_fit"
    assert preferences["saved_shortlist_candidates"][0]["property_facts"]["area_sqm"] == 88


def test_propertyquarry_teable_restore_contract_covers_every_projected_table() -> None:
    namespace = runpy.run_path("scripts/restore_propertyquarry_from_teable.py", run_name="__test__")
    recoverable_tables = set(namespace["RECOVERABLE_TEABLE_TABLES"])
    intentionally_lossy_tables = set(namespace["INTENTIONALLY_LOSSY_TEABLE_TABLES"])

    assert namespace["TEABLE_RESTORE_CONTRACT_VERSION"] == "propertyquarry.teable_restore_coverage.v1"
    assert recoverable_tables.isdisjoint(intentionally_lossy_tables)
    assert recoverable_tables | intentionally_lossy_tables == set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    assert "propertyquarry_saved_shortlist" in recoverable_tables
    assert "propertyquarry_property_evaluations" in recoverable_tables
    assert "propertyquarry_review_artifacts" in recoverable_tables
    assert "propertyquarry_shared_artifacts" in recoverable_tables
    assert "propertyquarry_research_tasks" in recoverable_tables
    assert "propertyquarry_search_agents" in recoverable_tables
    assert "propertyquarry_subscriptions" in recoverable_tables
    assert "propertyquarry_search_runs" in intentionally_lossy_tables
    assert "saved results" in namespace["INTENTIONALLY_LOSSY_TEABLE_TABLES"]["propertyquarry_search_runs"]


def test_propertyquarry_teable_portability_gate_reports_restore_coverage() -> None:
    script = Path("scripts/check_property_teable_portability.py")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "pass"
    assert payload["restore_contract_version"] == "propertyquarry.teable_restore_coverage.v1"
    assert payload["recoverable_table_count"] >= 14
    assert set(payload["intentionally_lossy_tables"]) == {
        "propertyquarry_tenants",
        "propertyquarry_search_runs",
        "propertyquarry_provider_sources",
    }
    resume = dict(payload["new_host_resume"])
    assert resume["operator_edits"] == [
        "TEABLE_API_KEY",
        "TEABLE_BASE_URL",
    ]
    assert resume["optional_overrides"] == [
        "PROPERTYQUARRY_TEABLE_BASE_ID",
        "PROPERTYQUARRY_TEABLE_TENANT_NAME",
    ]
    assert "discovers the default PropertyQuarry Teable base by name" in resume["base_discovery"]
    assert "restore_propertyquarry_from_teable.py" in resume["restore_command"]
    assert "propertyquarry_saved_shortlist" in set(resume["recoverable"])
    assert "propertyquarry_review_artifacts" in set(resume["recoverable"])
    assert "propertyquarry_shared_artifacts" in set(resume["recoverable"])
    assert "propertyquarry_search_runs" in set(resume["intentionally_lost"])
    assert "saved results" in resume["result_policy"]
    assert "live runs" in resume["result_policy"]


def test_propertyquarry_teable_restore_apply_writes_decision_loop_rows(monkeypatch) -> None:
    namespace = runpy.run_path("scripts/restore_propertyquarry_from_teable.py", run_name="__test__")
    apply_decision_loop_restore_bundle = namespace["apply_decision_loop_restore_bundle"]
    executed: list[tuple[str, tuple[object, ...]]] = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            executed.append((sql, params))

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return _Cursor()

    class _Repo:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://restore/db"

        def _connect(self):
            return _Connection()

        def _json_value(self, value):
            return value

    import app.repositories.property_decision_loop_postgres as decision_repo

    monkeypatch.setattr(decision_repo, "PostgresPropertyDecisionLoopRepository", _Repo)

    result = apply_decision_loop_restore_bundle(
        database_url="postgresql://restore/db",
        bundle={
            "decision_loop_rows": {
                "propertyquarry_decision_ledger": [
                    {
                        "decision_id": "decision-restore-1",
                        "principal_id": "pq-restore-user",
                        "person_id": "self",
                        "property_ref": "property:restore-1",
                        "decision_state": "needs_documents",
                        "reason_keys_json": ["no_floorplan"],
                    }
                ],
                "propertyquarry_evidence_claims": [
                    {
                        "claim_id": "claim-restore-1",
                        "principal_id": "pq-restore-user",
                        "person_id": "self",
                        "property_ref": "property:restore-1",
                        "decision_id": "decision-restore-1",
                        "claim_type": "risk",
                        "claim_text": "Missing or unclear: no floorplan.",
                    }
                ],
                "propertyquarry_agent_questions": [
                    {
                        "task_id": "question-restore-1",
                        "principal_id": "pq-restore-user",
                        "person_id": "self",
                        "property_ref": "property:restore-1",
                        "decision_id": "decision-restore-1",
                        "question_text": "Please send the floorplan.",
                    }
                ],
                "propertyquarry_documents": [
                    {
                        "document_id": "document-restore-1",
                        "principal_id": "pq-restore-user",
                        "person_id": "self",
                        "property_ref": "property:restore-1",
                        "decision_id": "decision-restore-1",
                        "document_type": "floorplan",
                    }
                ],
            }
        },
    )

    assert result == {
        "propertyquarry_agent_questions": 1,
        "propertyquarry_decision_ledger": 1,
        "propertyquarry_documents": 1,
        "propertyquarry_evidence_claims": 1,
    }
    assert len(executed) == 4
    assert any("property_decision_ledger" in sql for sql, _ in executed)
    assert any("property_evidence_claims" in sql for sql, _ in executed)
    assert any("property_agent_question_tasks" in sql for sql, _ in executed)
    assert any("property_documents" in sql for sql, _ in executed)


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


def test_propertyquarry_teable_priority_materializer_has_stable_product_rows() -> None:
    namespace = runpy.run_path("scripts/materialize_propertyquarry_teable_priorities.py", run_name="__test__")
    priorities = list(namespace["PRIORITIES"])
    fields = list(namespace["FIELDS"])

    projection_ids = [str(row.get("projection_id") or "") for row in priorities]
    assert len(priorities) >= 10
    assert len(projection_ids) == len(set(projection_ids))
    assert {str(row.get("priority") or "") for row in priorities} >= {"P0", "P1", "P2"}
    assert "pq-priority-search-location-hard-filters" in projection_ids
    assert "pq-priority-payfunnels-commercial-lifecycle" in projection_ids
    assert "pq-priority-property-passport" in projection_ids
    assert "pq-priority-search-run-tenancy-schema" in projection_ids
    assert "pq-priority-dedicated-worker-queues" in projection_ids
    assert "pq-priority-notification-governance" in projection_ids
    assert "pq-priority-ranking-benchmark" in projection_ids
    assert "pq-priority-market-readiness-localization" in projection_ids
    assert "pq-priority-billing-invoice-vat-lifecycle" in projection_ids
    assert [field["name"] for field in fields] == [
        "projection_id",
        "priority",
        "area",
        "title",
        "status",
        "user_visible",
        "owner_lane",
        "current_state",
        "next_action",
        "source",
        "updated_at",
    ]
