from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


PROPERTYQUARRY_TEABLE_TABLE_NAMES = (
    "propertyquarry_tenants",
    "propertyquarry_users",
    "propertyquarry_delivery_settings",
    "propertyquarry_subscriptions",
    "propertyquarry_preferences",
    "propertyquarry_search_agents",
    "propertyquarry_saved_shortlist",
    "propertyquarry_search_runs",
    "propertyquarry_provider_sources",
    "propertyquarry_properties",
    "propertyquarry_property_evaluations",
    "propertyquarry_review_artifacts",
    "propertyquarry_shared_artifacts",
    "propertyquarry_research_tasks",
    "propertyquarry_decision_ledger",
    "propertyquarry_evidence_claims",
    "propertyquarry_agent_questions",
    "propertyquarry_documents",
)

PROPERTYQUARRY_WHATSAPP_AI_SUPPORT_PURPOSE = "ai_support_only"


PROPERTYQUARRY_TEABLE_TABLE_FIELDS: dict[str, list[dict[str, object]]] = {
    "propertyquarry_tenants": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "tenant_name", "type": "singleLineText"},
        {"name": "source_system", "type": "singleLineText"},
        {"name": "privacy_scope", "type": "singleLineText"},
        {"name": "sync_version", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_users": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "workspace_name", "type": "singleLineText"},
        {"name": "workspace_mode", "type": "singleLineText"},
        {"name": "region", "type": "singleLineText"},
        {"name": "language", "type": "singleLineText"},
        {"name": "timezone", "type": "singleLineText"},
        {"name": "selected_channels_json", "type": "longText"},
        {"name": "current_plan_key", "type": "singleLineText"},
        {"name": "subscription_status", "type": "singleLineText"},
        {"name": "is_paid", "type": "checkbox"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_delivery_settings": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "preferred_channel", "type": "singleLineText"},
        {"name": "preferred_label", "type": "singleLineText"},
        {"name": "notification_scope", "type": "singleLineText"},
        {"name": "selected_channels_json", "type": "longText"},
        {"name": "email_enabled", "type": "checkbox"},
        {"name": "telegram_enabled", "type": "checkbox"},
        {"name": "telegram_bot_status", "type": "singleLineText"},
        {"name": "whatsapp_enabled", "type": "checkbox"},
        {"name": "whatsapp_notification_opt_in", "type": "checkbox"},
        {"name": "whatsapp_ai_support_enabled", "type": "checkbox"},
        {"name": "whatsapp_ai_support_phone", "type": "singleLineText"},
        {"name": "whatsapp_ai_support_phone_last4", "type": "singleLineText"},
        {"name": "whatsapp_ai_support_purpose", "type": "singleLineText"},
        {"name": "signal_status", "type": "singleLineText"},
        {"name": "settings_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_subscriptions": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "current_plan_key", "type": "singleLineText"},
        {"name": "current_plan_label", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "active_until", "type": "singleLineText"},
        {"name": "is_paid", "type": "checkbox"},
        {"name": "pending_plan_key", "type": "singleLineText"},
        {"name": "plan_source", "type": "singleLineText"},
        {"name": "last_order_id", "type": "singleLineText"},
        {"name": "last_capture_id", "type": "singleLineText"},
        {"name": "last_payment_status", "type": "singleLineText"},
        {"name": "last_payment_amount_eur", "type": "singleLineText"},
        {"name": "captured_at", "type": "singleLineText"},
        {"name": "commercial_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_preferences": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "country_code", "type": "singleLineText"},
        {"name": "language_code", "type": "singleLineText"},
        {"name": "listing_mode", "type": "singleLineText"},
        {"name": "property_type", "type": "singleLineText"},
        {"name": "location_query", "type": "singleLineText"},
        {"name": "keywords", "type": "singleLineText"},
        {"name": "selected_platforms_json", "type": "longText"},
        {"name": "max_price_eur", "type": "number"},
        {"name": "min_rooms", "type": "number"},
        {"name": "min_area_m2", "type": "number"},
        {"name": "max_results_per_source", "type": "number"},
        {"name": "use_stored_feedback_preferences", "type": "checkbox"},
        {"name": "alert_frequency", "type": "singleLineText"},
        {"name": "preferences_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_search_agents": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "agent_id", "type": "singleLineText"},
        {"name": "name", "type": "singleLineText"},
        {"name": "enabled", "type": "checkbox"},
        {"name": "is_active", "type": "checkbox"},
        {"name": "country_code", "type": "singleLineText"},
        {"name": "region_code", "type": "singleLineText"},
        {"name": "location_query", "type": "singleLineText"},
        {"name": "listing_mode", "type": "singleLineText"},
        {"name": "property_type", "type": "singleLineText"},
        {"name": "selected_platforms_json", "type": "longText"},
        {"name": "duration_days", "type": "number"},
        {"name": "notification_limit", "type": "number"},
        {"name": "notification_period", "type": "singleLineText"},
        {"name": "sent_in_current_window", "type": "number"},
        {"name": "last_run_at", "type": "singleLineText"},
        {"name": "next_run_at", "type": "singleLineText"},
        {"name": "preferences_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_saved_shortlist": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "candidate_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "listing_id", "type": "singleLineText"},
        {"name": "title", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "fit_score", "type": "number"},
        {"name": "rank", "type": "number"},
        {"name": "saved_from_run_id", "type": "singleLineText"},
        {"name": "review_url", "type": "longText"},
        {"name": "tour_url", "type": "longText"},
        {"name": "tour_status", "type": "singleLineText"},
        {"name": "facts_json", "type": "longText"},
        {"name": "candidate_json", "type": "longText"},
        {"name": "saved_at", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_search_runs": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "status_url", "type": "singleLineText"},
        {"name": "selected_platforms_json", "type": "longText"},
        {"name": "preferences_json", "type": "longText"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "updated_at", "type": "singleLineText"},
        {"name": "generated_at", "type": "singleLineText"},
        {"name": "sources_total", "type": "number"},
        {"name": "listing_total", "type": "number"},
        {"name": "high_fit_total", "type": "number"},
        {"name": "review_created_total", "type": "number"},
        {"name": "review_existing_total", "type": "number"},
        {"name": "tour_created_total", "type": "number"},
        {"name": "tour_existing_total", "type": "number"},
        {"name": "provider_cache_hit_total", "type": "number"},
        {"name": "provider_cache_refresh_total", "type": "number"},
        {"name": "filtered_area_total", "type": "number"},
        {"name": "filtered_low_fit_total", "type": "number"},
        {"name": "research_task_total", "type": "number"},
        {"name": "open_research_task_total", "type": "number"},
        {"name": "summary_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_provider_sources": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "source_url", "type": "longText"},
        {"name": "platform", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "provider_cache_key", "type": "singleLineText"},
        {"name": "provider_cache_status", "type": "singleLineText"},
        {"name": "provider_cache_stale", "type": "checkbox"},
        {"name": "raw_listing_total", "type": "number"},
        {"name": "scanned_listing_total", "type": "number"},
        {"name": "listing_total", "type": "number"},
        {"name": "duplicate_listing_total", "type": "number"},
        {"name": "filtered_area_total", "type": "number"},
        {"name": "filtered_low_fit_total", "type": "number"},
        {"name": "filtered_floorplan_total", "type": "number"},
        {"name": "high_fit_total", "type": "number"},
        {"name": "top_fit_score", "type": "number"},
        {"name": "scan_truncated", "type": "checkbox"},
        {"name": "min_area_m2", "type": "number"},
        {"name": "max_price_eur", "type": "number"},
        {"name": "min_rooms", "type": "number"},
        {"name": "provider_filter_pushdown_json", "type": "longText"},
        {"name": "provider_cache_json", "type": "longText"},
        {"name": "source_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_properties": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "listing_id", "type": "singleLineText"},
        {"name": "title", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "area_sqm", "type": "number"},
        {"name": "rooms", "type": "number"},
        {"name": "total_rent_eur", "type": "number"},
        {"name": "purchase_price_eur", "type": "number"},
        {"name": "postal_name", "type": "singleLineText"},
        {"name": "property_type", "type": "singleLineText"},
        {"name": "facts_json", "type": "longText"},
        {"name": "last_seen_run_id", "type": "singleLineText"},
        {"name": "last_seen_at", "type": "singleLineText"},
    ],
    "propertyquarry_property_evaluations": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "fit_score", "type": "number"},
        {"name": "recommendation", "type": "singleLineText"},
        {"name": "fit_summary", "type": "singleLineText"},
        {"name": "review_url", "type": "longText"},
        {"name": "tour_url", "type": "longText"},
        {"name": "tour_status", "type": "singleLineText"},
        {"name": "match_reasons_json", "type": "longText"},
        {"name": "mismatch_reasons_json", "type": "longText"},
        {"name": "assessment_json", "type": "longText"},
        {"name": "facts_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_review_artifacts": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "review_url", "type": "longText"},
        {"name": "review_status", "type": "singleLineText"},
        {"name": "review_task_id", "type": "singleLineText"},
        {"name": "review_task_status", "type": "singleLineText"},
        {"name": "review_reused", "type": "checkbox"},
        {"name": "queue_item_ref", "type": "singleLineText"},
        {"name": "recommended_task_key", "type": "singleLineText"},
        {"name": "tour_url", "type": "longText"},
        {"name": "tour_status", "type": "singleLineText"},
        {"name": "tour_blocked_reason", "type": "singleLineText"},
        {"name": "fit_score", "type": "number"},
        {"name": "recommendation", "type": "singleLineText"},
        {"name": "preference_person_id", "type": "singleLineText"},
        {"name": "artifact_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_shared_artifacts": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "candidate_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "title", "type": "singleLineText"},
        {"name": "source_label", "type": "singleLineText"},
        {"name": "artifact_kind", "type": "singleLineText"},
        {"name": "artifact_url", "type": "longText"},
        {"name": "artifact_status", "type": "singleLineText"},
        {"name": "visibility", "type": "singleLineText"},
        {"name": "artifact_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_research_tasks": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "run_id", "type": "singleLineText"},
        {"name": "task_id", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "field_key", "type": "singleLineText"},
        {"name": "label", "type": "singleLineText"},
        {"name": "question", "type": "longText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "property_url", "type": "longText"},
        {"name": "value", "type": "singleLineText"},
        {"name": "note", "type": "longText"},
        {"name": "task_json", "type": "longText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_decision_ledger": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "person_id", "type": "singleLineText"},
        {"name": "decision_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "decision_state", "type": "singleLineText"},
        {"name": "reason_keys_json", "type": "longText"},
        {"name": "source", "type": "singleLineText"},
        {"name": "actor", "type": "singleLineText"},
        {"name": "confidence", "type": "number"},
        {"name": "supersedes_decision_id", "type": "singleLineText"},
        {"name": "learning_applied", "type": "checkbox"},
        {"name": "aggregate_candidate", "type": "checkbox"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_evidence_claims": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "person_id", "type": "singleLineText"},
        {"name": "claim_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "decision_id", "type": "singleLineText"},
        {"name": "claim_type", "type": "singleLineText"},
        {"name": "claim_text", "type": "longText"},
        {"name": "source_type", "type": "singleLineText"},
        {"name": "source_ref", "type": "singleLineText"},
        {"name": "confidence", "type": "singleLineText"},
        {"name": "verification_state", "type": "singleLineText"},
        {"name": "privacy_class", "type": "singleLineText"},
        {"name": "allowed_outputs_json", "type": "longText"},
        {"name": "expires_at", "type": "singleLineText"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_agent_questions": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "person_id", "type": "singleLineText"},
        {"name": "task_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "decision_id", "type": "singleLineText"},
        {"name": "question_text", "type": "longText"},
        {"name": "reason_key", "type": "singleLineText"},
        {"name": "source_claim_id", "type": "singleLineText"},
        {"name": "status", "type": "singleLineText"},
        {"name": "answer_source", "type": "singleLineText"},
        {"name": "updated_claim_id", "type": "singleLineText"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
    "propertyquarry_documents": [
        {"name": "projection_id", "type": "singleLineText", "notNull": True, "unique": True},
        {"name": "tenant_key", "type": "singleLineText"},
        {"name": "principal_id", "type": "singleLineText"},
        {"name": "person_id", "type": "singleLineText"},
        {"name": "document_id", "type": "singleLineText"},
        {"name": "property_ref", "type": "singleLineText"},
        {"name": "decision_id", "type": "singleLineText"},
        {"name": "document_type", "type": "singleLineText"},
        {"name": "source", "type": "singleLineText"},
        {"name": "privacy_class", "type": "singleLineText"},
        {"name": "verification_state", "type": "singleLineText"},
        {"name": "extracted_claims_json", "type": "longText"},
        {"name": "missing_pages_json", "type": "longText"},
        {"name": "redaction_state", "type": "singleLineText"},
        {"name": "linked_risks_json", "type": "longText"},
        {"name": "created_at", "type": "singleLineText"},
        {"name": "last_projected_at", "type": "singleLineText"},
    ],
}


def propertyquarry_teable_tenant_key() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TEABLE_TENANT_KEY") or "propertyquarry").strip() or "propertyquarry"


def propertyquarry_teable_tenant_name() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TEABLE_TENANT_NAME") or "PropertyQuarry").strip() or "PropertyQuarry"


def propertyquarry_teable_table_config_from_table_ids(table_ids: dict[str, str]) -> dict[str, dict[str, object]]:
    return {
        table_name: {
            "table_id": str(table_ids.get(table_name) or "").strip(),
            "key_field": "projection_id",
            "field_key_type": "name",
        }
        for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
        if str(table_ids.get(table_name) or "").strip()
    }


def _teable_items(payload: object, keys: tuple[str, ...]) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _teable_request_json(*, base_url: str, api_key: str, path: str, timeout: int = 20) -> object:
    normalized_base_url = str(base_url or "https://app.teable.ai").strip().rstrip("/")
    normalized_api_key = str(api_key or "").strip()
    if not normalized_api_key:
        return {}
    request = urllib.request.Request(
        f"{normalized_base_url}{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {normalized_api_key}",
            "Accept": "application/json",
            "User-Agent": "PropertyQuarryTeableDiscovery/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _propertyquarry_teable_table_ids_for_base(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
) -> dict[str, str]:
    normalized_base_id = str(base_id or "").strip()
    if not normalized_base_id:
        return {}
    loaded = _teable_request_json(
        base_url=base_url,
        api_key=api_key,
        path=f"/api/base/{urllib.parse.quote(normalized_base_id)}/table",
    )
    table_ids: dict[str, str] = {}
    for item in _teable_items(loaded, ("tables", "data", "items")):
        name = str(item.get("name") or item.get("tableName") or "").strip()
        table_id = str(item.get("id") or item.get("tableId") or "").strip()
        if name and table_id:
            table_ids[name] = table_id
    return table_ids


def discover_propertyquarry_teable_base_id(
    *,
    base_url: str,
    api_key: str,
    base_name: str = "",
) -> str:
    target_name = str(base_name or propertyquarry_teable_tenant_name()).strip().lower() or "propertyquarry"
    spaces_payload = _teable_request_json(base_url=base_url, api_key=api_key, path="/api/space")
    spaces = [
        item
        for item in _teable_items(spaces_payload, ("spaces", "data", "items"))
        if str(item.get("id") or "").strip()
    ]
    candidate_bases: list[dict[str, object]] = []
    for space in spaces:
        space_id = str(space.get("id") or "").strip()
        bases_payload = _teable_request_json(
            base_url=base_url,
            api_key=api_key,
            path=f"/api/space/{urllib.parse.quote(space_id)}/base",
        )
        candidate_bases.extend(_teable_items(bases_payload, ("bases", "data", "items")))
    normalized_candidates = [
        {
            "id": str(item.get("id") or item.get("baseId") or "").strip(),
            "name": str(item.get("name") or item.get("baseName") or "").strip(),
        }
        for item in candidate_bases
        if str(item.get("id") or item.get("baseId") or "").strip()
    ]
    for item in normalized_candidates:
        if str(item.get("name") or "").strip().lower() == target_name:
            return str(item.get("id") or "").strip()
    for item in normalized_candidates:
        base_id = str(item.get("id") or "").strip()
        table_ids = _propertyquarry_teable_table_ids_for_base(
            base_url=base_url,
            api_key=api_key,
            base_id=base_id,
        )
        if all(str(table_ids.get(table_name) or "").strip() for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES):
            return base_id
    if len(normalized_candidates) == 1:
        return str(normalized_candidates[0].get("id") or "").strip()
    return ""


def discover_propertyquarry_teable_table_config(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
    base_name: str = "",
) -> dict[str, dict[str, object]]:
    normalized_api_key = str(api_key or "").strip()
    normalized_base_id = str(base_id or "").strip() or discover_propertyquarry_teable_base_id(
        base_url=base_url,
        api_key=normalized_api_key,
        base_name=base_name,
    )
    if not normalized_api_key or not normalized_base_id:
        return {}
    table_ids = _propertyquarry_teable_table_ids_for_base(
        base_url=base_url,
        api_key=normalized_api_key,
        base_id=normalized_base_id,
    )
    return propertyquarry_teable_table_config_from_table_ids(table_ids)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_commercial_json(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {"last_payer_email", "payer_email", "email", "billing_email"}
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        result[normalized] = value
    return result


def _safe_teable_facts(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {"exact_address", "street_address", "house_number", "map_lat", "map_lng", "lat", "lng"}
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        result[normalized] = value
    return result


def _safe_teable_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    blocked_exact = {
        "property_commercial",
        "payer_email",
        "billing_email",
        "email",
        "raw_notes",
        "notes",
        "consent_note",
    }
    blocked_markers = ("token", "secret", "cookie", "session", "oauth", "internal", "debug", "credential")
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized = str(key or "").strip()
        lowered = normalized.lower()
        if normalized in blocked_exact:
            continue
        if any(marker in lowered for marker in blocked_markers):
            continue
        if "email" in lowered:
            continue
        if isinstance(value, dict):
            result[normalized] = _safe_teable_preferences(value)
            continue
        if isinstance(value, list):
            items: list[Any] = []
            for item in value[:50]:
                if isinstance(item, dict):
                    items.append(_safe_teable_preferences(item))
                else:
                    items.append(item)
            result[normalized] = items
            continue
        result[normalized] = value
    return result


def _safe_review_artifact(candidate: dict[str, Any] | None, *, safe_facts: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate or {})
    return {
        "property_url": _text(payload.get("property_url"), limit=1000),
        "listing_id": _text(payload.get("listing_id"), limit=200),
        "title": _text(payload.get("title"), limit=240),
        "fit_score": _number(payload.get("fit_score")),
        "recommendation": _text(payload.get("recommendation"), limit=160),
        "review_status": _text(payload.get("review_status"), limit=80),
        "review_task_status": _text(payload.get("review_task_status"), limit=80),
        "review_reused": bool(payload.get("review_reused")),
        "tour_status": _text(payload.get("tour_status"), limit=80),
        "facts_json": dict(safe_facts),
    }


def _shared_artifacts_from_candidate(
    candidate: dict[str, Any] | None,
    *,
    tenant_key: str,
    principal_id: str,
    run_id: str,
    property_ref: str,
    property_url: str,
    candidate_ref: str,
    title: str,
    source_label: str,
    projected_at: str,
) -> dict[str, dict[str, object]]:
    payload = dict(candidate or {})
    artifact_specs = (
        ("review", "review_url", "review_status", "private_workspace"),
        ("packet", "packet_url", "packet_status", "private_workspace"),
        ("public_packet", "public_packet_url", "packet_status", "signed_public"),
        ("public_packet", "share_url", "share_status", "signed_public"),
        ("tour", "tour_url", "tour_status", "signed_public"),
        ("walkthrough", "walkthrough_url", "walkthrough_status", "private_workspace"),
        ("video", "video_url", "video_status", "private_workspace"),
    )
    rows: dict[str, dict[str, object]] = {}
    seen_urls: set[tuple[str, str]] = set()
    for artifact_kind, url_key, status_key, visibility in artifact_specs:
        artifact_url = _text(payload.get(url_key), limit=1000)
        if not artifact_url:
            continue
        dedupe_key = (artifact_kind, artifact_url)
        if dedupe_key in seen_urls:
            continue
        seen_urls.add(dedupe_key)
        artifact_ref = _stable_ref(f"{principal_id}:{property_ref}:{artifact_kind}:{artifact_url}", prefix="artifact")
        artifact_status = _text(payload.get(status_key), limit=80)
        if not artifact_status:
            artifact_status = "ready"
        rows[f"shared_artifact:{tenant_key}:{artifact_ref}"] = {
            "projection_id": f"shared_artifact:{tenant_key}:{artifact_ref}",
            "tenant_key": tenant_key,
            "principal_id": principal_id,
            "run_id": run_id,
            "property_ref": property_ref,
            "candidate_ref": candidate_ref,
            "property_url": property_url,
            "title": title,
            "source_label": source_label,
            "artifact_kind": artifact_kind,
            "artifact_url": artifact_url,
            "artifact_status": artifact_status,
            "visibility": visibility,
            "artifact_json": {
                "artifact_kind": artifact_kind,
                "artifact_url": artifact_url,
                "artifact_status": artifact_status,
                "visibility": visibility,
                "source_field": url_key,
            },
            "last_projected_at": projected_at,
        }
    return rows


def _safe_source_summary(source: dict[str, Any] | None, *, source_label: str, platform: str, source_url: str) -> dict[str, Any]:
    payload = dict(source or {})
    return {
        "source_label": source_label,
        "platform": platform,
        "source_url": source_url,
        "raw_listing_total": payload.get("raw_listing_total"),
        "scanned_listing_total": payload.get("scanned_listing_total"),
        "listing_total": payload.get("listing_total"),
        "duplicate_listing_total": payload.get("duplicate_listing_total"),
        "filtered_area_total": payload.get("filtered_area_total"),
        "filtered_low_fit_total": payload.get("filtered_low_fit_total"),
        "filtered_floorplan_total": payload.get("filtered_floorplan_total"),
        "high_fit_total": payload.get("high_fit_total"),
        "top_fit_score": payload.get("top_fit_score"),
        "scan_truncated": bool(payload.get("scan_truncated")),
    }


def _text(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def _number(value: object) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)


def _stable_ref(value: object, *, prefix: str) -> str:
    raw = str(value or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _projection_alias(value: object, *, prefix: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = f"{prefix}:unknown"
    return _stable_ref(raw, prefix=prefix)


def _property_projection_ref(value: object, *, fallback: object = "") -> str:
    raw = str(value or "").strip()
    if raw.startswith("property:") and len(raw) > len("property:"):
        return raw
    if not raw:
        raw = str(fallback or "").strip()
    return _stable_ref(raw, prefix="property")


def _safe_decision_claim_text(row: dict[str, Any] | None) -> str:
    payload = dict(row or {})
    claim_type = _text(payload.get("claim_type"), limit=80).lower()
    privacy_class = _text(payload.get("privacy_class"), limit=80).lower()
    if claim_type in {"human_feedback", "household_feedback"}:
        return ""
    if privacy_class in {"owner_private", "private"} and claim_type in {"preference", "note"}:
        return ""
    return _text(payload.get("text") or payload.get("claim_text"), limit=1200)


def _property_commercial_snapshot(preferences: dict[str, object]) -> dict[str, object]:
    try:
        from app.services.property_billing import property_commercial_snapshot

        return dict(property_commercial_snapshot(preferences))
    except Exception:
        commercial = dict(preferences.get("property_commercial") or {}) if isinstance(preferences.get("property_commercial"), dict) else {}
        plan_key = _text(commercial.get("active_plan_key") or commercial.get("plan_key") or "free", limit=80) or "free"
        status = _text(commercial.get("status") or ("free" if plan_key == "free" else "active"), limit=80)
        return {
            "current_plan_key": plan_key,
            "current_plan_label": plan_key.title(),
            "status": status,
            "active_until": _text(commercial.get("active_until"), limit=120),
            "is_paid": plan_key != "free",
            "pending_plan_key": _text(commercial.get("pending_plan_key"), limit=80),
            "property_commercial": commercial,
        }


def _table_rows(rows_by_id: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [dict(rows_by_id[key]) for key in sorted(rows_by_id)]


def _candidate_rows_from_run(run: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(run.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = _text(source.get("source_label"), limit=160)
        for candidate in list(source.get("top_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            item = dict(candidate)
            item.setdefault("source_label", source_label)
            rows.append(item)
    return rows


def _source_rows_from_run(run: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(run.get("summary") or {})
    rows: list[dict[str, object]] = []
    for source in list(summary.get("sources") or []):
        if isinstance(source, dict):
            rows.append(dict(source))
    return rows


def build_propertyquarry_teable_projection_records(
    *,
    principal_id: str,
    onboarding_status: dict[str, object] | None = None,
    search_runs: tuple[dict[str, object], ...] = (),
    decision_loop_rows: dict[str, list[dict[str, object]]] | None = None,
    tenant_key: str = "",
    tenant_name: str = "",
) -> dict[str, list[dict[str, object]]]:
    normalized_principal = _text(principal_id, limit=240)
    normalized_tenant = _text(tenant_key or propertyquarry_teable_tenant_key(), limit=120)
    normalized_tenant_name = _text(tenant_name or propertyquarry_teable_tenant_name(), limit=200)
    projected_at = _now_iso()
    status = dict(onboarding_status or {})
    workspace = dict(status.get("workspace") or {})
    preferences = dict(status.get("property_search_preferences") or {})
    delivery_preferences = dict(status.get("delivery_preferences") or {})
    property_notifications = (
        dict(delivery_preferences.get("property_notifications") or {})
        if isinstance(delivery_preferences.get("property_notifications"), dict)
        else {}
    )
    raw_preferences = dict(preferences.get("raw_preferences") or {}) if isinstance(preferences.get("raw_preferences"), dict) else {}
    effective_preferences = raw_preferences or preferences
    safe_preferences = _safe_teable_preferences(effective_preferences)
    commercial = _property_commercial_snapshot(effective_preferences)
    commercial_json = dict(commercial.get("property_commercial") or {})
    safe_commercial_json = _safe_commercial_json(commercial_json)
    preference_person_id = _text(effective_preferences.get("preference_person_id") or "self", limit=120) or "self"

    tenants: dict[str, dict[str, object]] = {
        f"tenant:{normalized_tenant}": {
            "projection_id": f"tenant:{normalized_tenant}",
            "tenant_key": normalized_tenant,
            "tenant_name": normalized_tenant_name,
            "source_system": "propertyquarry",
            "privacy_scope": "operator_private",
            "sync_version": "propertyquarry_teable_projection_v1",
            "last_projected_at": projected_at,
        }
    }
    users: dict[str, dict[str, object]] = {}
    delivery_settings: dict[str, dict[str, object]] = {}
    subscriptions: dict[str, dict[str, object]] = {}
    preference_rows: dict[str, dict[str, object]] = {}
    search_agent_rows: dict[str, dict[str, object]] = {}
    saved_shortlist_rows: dict[str, dict[str, object]] = {}
    search_run_rows: dict[str, dict[str, object]] = {}
    provider_source_rows: dict[str, dict[str, object]] = {}
    property_rows: dict[str, dict[str, object]] = {}
    evaluation_rows: dict[str, dict[str, object]] = {}
    review_artifact_rows: dict[str, dict[str, object]] = {}
    shared_artifact_rows: dict[str, dict[str, object]] = {}
    research_task_rows: dict[str, dict[str, object]] = {}
    decision_rows: dict[str, dict[str, object]] = {}
    evidence_rows: dict[str, dict[str, object]] = {}
    agent_question_rows: dict[str, dict[str, object]] = {}
    document_rows: dict[str, dict[str, object]] = {}

    if normalized_principal:
        selected_channels = [
            _text(value, limit=80)
            for value in list(status.get("selected_channels") or [])
            if _text(value, limit=80)
        ]
        preferred_channel = _text(property_notifications.get("preferred_channel") or "email", limit=80) or "email"
        whatsapp_ai_support_phone = _text(property_notifications.get("whatsapp_ai_support_phone"), limit=80)
        whatsapp_ai_support_digits = "".join(ch for ch in whatsapp_ai_support_phone if ch.isdigit())
        whatsapp_ai_support_purpose = PROPERTYQUARRY_WHATSAPP_AI_SUPPORT_PURPOSE if whatsapp_ai_support_phone else ""
        telegram_bot = (
            dict(property_notifications.get("telegram_bot") or {})
            if isinstance(property_notifications.get("telegram_bot"), dict)
            else {}
        )
        settings_json = {
            "preferred_channel": preferred_channel,
            "preferred_label": _text(property_notifications.get("preferred_label") or preferred_channel.title(), limit=120),
            "notification_scope": _text(property_notifications.get("notification_scope") or "scout_updates", limit=120),
            "selected_channels": selected_channels,
            "email_enabled": "email" in selected_channels or preferred_channel == "email",
            "telegram_enabled": "telegram" in selected_channels or preferred_channel == "telegram",
            "telegram_bot_status": _text(telegram_bot.get("status_label"), limit=120),
            "whatsapp_enabled": "whatsapp" in selected_channels or preferred_channel == "whatsapp" or bool(whatsapp_ai_support_phone),
            "whatsapp_notification_opt_in": bool(property_notifications.get("whatsapp_notification_opt_in")),
            "whatsapp_ai_support_enabled": bool(whatsapp_ai_support_phone),
            "whatsapp_ai_support_phone_last4": whatsapp_ai_support_digits[-4:],
            "whatsapp_ai_support_purpose": whatsapp_ai_support_purpose,
            "signal_status": _text(property_notifications.get("signal_status") or "coming_soon", limit=80),
        }
        users[f"user:{normalized_tenant}:{normalized_principal}"] = {
            "projection_id": f"user:{normalized_tenant}:{normalized_principal}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "workspace_name": _text(workspace.get("name"), limit=200),
            "workspace_mode": _text(status.get("workspace_mode") or workspace.get("mode"), limit=80),
            "region": _text(status.get("region") or workspace.get("region"), limit=80),
            "language": _text(status.get("language") or workspace.get("language"), limit=80),
            "timezone": _text(status.get("timezone") or workspace.get("timezone"), limit=80),
            "selected_channels_json": list(status.get("selected_channels") or []),
            "current_plan_key": _text(commercial.get("current_plan_key"), limit=80),
            "subscription_status": _text(commercial.get("status"), limit=80),
            "is_paid": bool(commercial.get("is_paid")),
            "last_projected_at": projected_at,
        }
        delivery_settings[f"delivery:{normalized_tenant}:{normalized_principal}:property_alerts"] = {
            "projection_id": f"delivery:{normalized_tenant}:{normalized_principal}:property_alerts",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "preferred_channel": preferred_channel,
            "preferred_label": _text(property_notifications.get("preferred_label") or preferred_channel.title(), limit=120),
            "notification_scope": _text(property_notifications.get("notification_scope") or "scout_updates", limit=120),
            "selected_channels_json": selected_channels,
            "email_enabled": "email" in selected_channels or preferred_channel == "email",
            "telegram_enabled": "telegram" in selected_channels or preferred_channel == "telegram",
            "telegram_bot_status": _text(telegram_bot.get("status_label"), limit=120),
            "whatsapp_enabled": "whatsapp" in selected_channels or preferred_channel == "whatsapp" or bool(whatsapp_ai_support_phone),
            "whatsapp_notification_opt_in": bool(property_notifications.get("whatsapp_notification_opt_in")),
            "whatsapp_ai_support_enabled": bool(whatsapp_ai_support_phone),
            "whatsapp_ai_support_phone": whatsapp_ai_support_phone,
            "whatsapp_ai_support_phone_last4": whatsapp_ai_support_digits[-4:],
            "whatsapp_ai_support_purpose": whatsapp_ai_support_purpose,
            "signal_status": _text(property_notifications.get("signal_status") or "coming_soon", limit=80),
            "settings_json": settings_json,
            "last_projected_at": projected_at,
        }
        subscriptions[f"subscription:{normalized_tenant}:{normalized_principal}"] = {
            "projection_id": f"subscription:{normalized_tenant}:{normalized_principal}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "current_plan_key": _text(commercial.get("current_plan_key"), limit=80),
            "current_plan_label": _text(commercial.get("current_plan_label"), limit=120),
            "status": _text(commercial.get("status"), limit=80),
            "active_until": _text(commercial.get("active_until"), limit=120),
            "is_paid": bool(commercial.get("is_paid")),
            "pending_plan_key": _text(commercial.get("pending_plan_key"), limit=80),
            "plan_source": _text(safe_commercial_json.get("plan_source"), limit=120),
            "last_order_id": _text(safe_commercial_json.get("last_order_id"), limit=160),
            "last_capture_id": _text(safe_commercial_json.get("last_capture_id"), limit=160),
            "last_payment_status": _text(safe_commercial_json.get("last_payment_status"), limit=120),
            "last_payment_amount_eur": _text(safe_commercial_json.get("last_payment_amount_eur"), limit=80),
            "captured_at": _text(safe_commercial_json.get("captured_at"), limit=120),
            "commercial_json": safe_commercial_json,
            "last_projected_at": projected_at,
        }
        preference_rows[f"preferences:{normalized_tenant}:{normalized_principal}:{preference_person_id}"] = {
            "projection_id": f"preferences:{normalized_tenant}:{normalized_principal}:{preference_person_id}",
            "tenant_key": normalized_tenant,
            "principal_id": normalized_principal,
            "preference_person_id": preference_person_id,
            "country_code": _text(effective_preferences.get("country_code"), limit=20),
            "language_code": _text(effective_preferences.get("language_code"), limit=20),
            "listing_mode": _text(effective_preferences.get("listing_mode"), limit=40),
            "property_type": _text(effective_preferences.get("property_type"), limit=80),
            "location_query": _text(effective_preferences.get("location_query"), limit=240),
            "keywords": _text(effective_preferences.get("keywords"), limit=240),
            "selected_platforms_json": list(effective_preferences.get("selected_platforms") or []),
            "max_price_eur": _number(effective_preferences.get("max_price_eur")),
            "min_rooms": _number(effective_preferences.get("min_rooms")),
            "min_area_m2": _number(effective_preferences.get("min_area_m2")),
            "max_results_per_source": _number(effective_preferences.get("max_results_per_source")),
            "use_stored_feedback_preferences": bool(effective_preferences.get("use_stored_feedback_preferences", True)),
            "alert_frequency": _text(effective_preferences.get("alert_frequency"), limit=80),
            "preferences_json": safe_preferences,
            "last_projected_at": projected_at,
        }
        active_agent_id = _text(effective_preferences.get("active_search_agent_id"), limit=180)
        for agent in list(effective_preferences.get("search_agents") or []):
            if not isinstance(agent, dict):
                continue
            agent_id = _text(agent.get("agent_id") or agent.get("id"), limit=180)
            if not agent_id:
                continue
            agent_preferences = (
                dict(agent.get("preferences_json") or {})
                if isinstance(agent.get("preferences_json"), dict)
                else {}
            )
            safe_agent_preferences = _safe_teable_preferences(agent_preferences)
            selected_platforms = agent.get("selected_platforms")
            if not selected_platforms:
                selected_platforms = agent_preferences.get("selected_platforms")
            projection_id = f"search_agent:{normalized_tenant}:{normalized_principal}:{agent_id}"
            search_agent_rows[projection_id] = {
                "projection_id": projection_id,
                "tenant_key": normalized_tenant,
                "principal_id": _projection_alias(normalized_principal, prefix="principal"),
                "agent_id": agent_id,
                "name": _text(agent.get("name") or agent_preferences.get("name") or "Saved search", limit=200),
                "enabled": bool(agent.get("enabled", True)),
                "is_active": bool(agent.get("is_active")) or bool(active_agent_id and agent_id == active_agent_id),
                "country_code": _text(agent.get("country_code") or agent_preferences.get("country_code"), limit=20),
                "region_code": _text(agent.get("region_code") or agent_preferences.get("region_code"), limit=80),
                "location_query": _text(agent.get("location_query") or agent_preferences.get("location_query"), limit=240),
                "listing_mode": _text(agent.get("listing_mode") or agent_preferences.get("listing_mode"), limit=40),
                "property_type": _text(agent.get("property_type") or agent_preferences.get("property_type"), limit=80),
                "selected_platforms_json": list(selected_platforms or []),
                "duration_days": _number(agent.get("duration_days") or agent_preferences.get("search_agent_duration_days")),
                "notification_limit": _number(
                    agent.get("notification_limit")
                    or agent.get("max_notifications")
                    or agent_preferences.get("search_agent_notification_limit")
                ),
                "notification_period": _text(
                    agent.get("notification_period") or agent_preferences.get("search_agent_notification_period"),
                    limit=40,
                ),
                "sent_in_current_window": _number(agent.get("sent_in_current_window")),
                "last_run_at": _text(agent.get("last_run_at"), limit=120),
                "next_run_at": _text(agent.get("next_run_at"), limit=120),
                "preferences_json": safe_agent_preferences,
                "last_projected_at": projected_at,
            }
        for index, candidate in enumerate(list(effective_preferences.get("saved_shortlist_candidates") or [])[:200], start=1):
            if not isinstance(candidate, dict):
                continue
            candidate_payload = dict(candidate)
            property_url = _text(
                candidate_payload.get("property_url")
                or candidate_payload.get("source_url")
                or candidate_payload.get("listing_url"),
                limit=1000,
            )
            property_ref = _property_projection_ref(
                candidate_payload.get("property_ref") or property_url or candidate_payload.get("candidate_ref"),
                fallback=candidate_payload.get("candidate_ref") or f"saved:{index}",
            )
            if not property_ref:
                continue
            facts = (
                dict(candidate_payload.get("property_facts") or {})
                if isinstance(candidate_payload.get("property_facts"), dict)
                else {}
            )
            safe_facts = _safe_teable_facts(facts)
            safe_candidate = _safe_review_artifact(candidate_payload, safe_facts=safe_facts)
            projection_id = f"saved_shortlist:{normalized_tenant}:{normalized_principal}:{property_ref}"
            saved_shortlist_rows[projection_id] = {
                "projection_id": projection_id,
                "tenant_key": normalized_tenant,
                "principal_id": normalized_principal,
                "property_ref": property_ref,
                "candidate_ref": _text(candidate_payload.get("candidate_ref") or property_ref, limit=240),
                "property_url": property_url,
                "listing_id": _text(candidate_payload.get("listing_id") or property_url, limit=200),
                "title": _text(candidate_payload.get("title"), limit=240),
                "source_label": _text(candidate_payload.get("source_label"), limit=200),
                "fit_score": _number(candidate_payload.get("fit_score")),
                "rank": _number(candidate_payload.get("rank") or index),
                "saved_from_run_id": _text(candidate_payload.get("saved_from_run_id") or candidate_payload.get("run_id"), limit=240),
                "review_url": _text(candidate_payload.get("review_url"), limit=1000),
                "tour_url": _text(candidate_payload.get("tour_url"), limit=1000),
                "tour_status": _text(candidate_payload.get("tour_status"), limit=80),
                "facts_json": safe_facts,
                "candidate_json": safe_candidate,
                "saved_at": _text(candidate_payload.get("saved_at") or candidate_payload.get("updated_at"), limit=120),
                "last_projected_at": projected_at,
            }
            shared_artifact_rows.update(
                _shared_artifacts_from_candidate(
                    candidate_payload,
                    tenant_key=normalized_tenant,
                    principal_id=normalized_principal,
                    run_id=_text(candidate_payload.get("saved_from_run_id") or candidate_payload.get("run_id"), limit=240),
                    property_ref=property_ref,
                    property_url=property_url,
                    candidate_ref=_text(candidate_payload.get("candidate_ref") or property_ref, limit=240),
                    title=_text(candidate_payload.get("title"), limit=240),
                    source_label=_text(candidate_payload.get("source_label"), limit=200),
                    projected_at=projected_at,
                )
            )

    for run in search_runs:
        if not isinstance(run, dict):
            continue
        run_id = _text(run.get("run_id"), limit=180)
        if not run_id:
            continue
        run_principal = _text(run.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and run_principal != normalized_principal:
            continue
        summary = dict(run.get("summary") or {})
        run_preferences = dict(run.get("property_search_preferences") or {})
        safe_run_preferences = _safe_teable_preferences(run_preferences)
        search_run_rows[f"search_run:{run_id}"] = {
            "projection_id": f"search_run:{run_id}",
            "tenant_key": normalized_tenant,
            "principal_id": run_principal,
            "run_id": run_id,
            "status": _text(run.get("status"), limit=80),
            "status_url": _text(run.get("status_url"), limit=240),
            "selected_platforms_json": list(run.get("selected_platforms") or []),
            "preferences_json": safe_run_preferences,
            "created_at": _text(run.get("created_at"), limit=120),
            "updated_at": _text(run.get("updated_at"), limit=120),
            "generated_at": _text(run.get("generated_at"), limit=120),
            "sources_total": _number(summary.get("sources_total")),
            "listing_total": _number(summary.get("listing_total")),
            "high_fit_total": _number(summary.get("high_fit_total")),
            "review_created_total": _number(summary.get("review_created_total")),
            "review_existing_total": _number(summary.get("review_existing_total")),
            "tour_created_total": _number(summary.get("tour_created_total")),
            "tour_existing_total": _number(summary.get("tour_existing_total")),
            "provider_cache_hit_total": _number(summary.get("provider_cache_hit_total")),
            "provider_cache_refresh_total": _number(summary.get("provider_cache_refresh_total")),
            "filtered_area_total": _number(summary.get("filtered_area_total")),
            "filtered_low_fit_total": _number(summary.get("filtered_low_fit_total")),
            "research_task_total": _number(run.get("research_task_total") or summary.get("research_task_total")),
            "open_research_task_total": _number(run.get("open_research_task_total") or summary.get("open_research_task_total")),
            "summary_json": summary,
            "last_projected_at": projected_at,
        }
        for source_index, source in enumerate(_source_rows_from_run(run), start=1):
            source_url = _text(source.get("source_url"), limit=1000)
            source_label = _text(source.get("source_label"), limit=200)
            source_ref = _stable_ref(source_url or f"{run_id}:{source_label}:{source_index}", prefix="source")
            provider_filter_pushdown = (
                dict(source.get("provider_filter_pushdown") or {})
                if isinstance(source.get("provider_filter_pushdown"), dict)
                else {}
            )
            provider_cache = dict(source.get("provider_cache") or {}) if isinstance(source.get("provider_cache"), dict) else {}
            applied_pushdown = (
                dict(provider_filter_pushdown.get("applied") or {})
                if isinstance(provider_filter_pushdown.get("applied"), dict)
                else {}
            )
            cache_key = _text(
                source.get("provider_cache_key")
                or provider_cache.get("cache_key")
                or provider_filter_pushdown.get("cache_key"),
                limit=240,
            )
            platform = _text(source.get("platform"), limit=120)
            if not platform and ":" in cache_key:
                platform = _text(cache_key.split(":", 1)[0], limit=120)
            provider_source_rows[f"provider_source:{run_id}:{source_ref}"] = {
                "projection_id": f"provider_source:{run_id}:{source_ref}",
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "source_ref": source_ref,
                "source_label": source_label,
                "source_url": source_url,
                "platform": platform,
                "preference_person_id": _text(source.get("preference_person_id") or preference_person_id, limit=120),
                "provider_cache_key": cache_key,
                "provider_cache_status": _text(provider_cache.get("status"), limit=80),
                "provider_cache_stale": bool(provider_cache.get("stale") or provider_cache.get("status") == "stale_fallback"),
                "raw_listing_total": _number(source.get("raw_listing_total")),
                "scanned_listing_total": _number(source.get("scanned_listing_total")),
                "listing_total": _number(source.get("listing_total")),
                "duplicate_listing_total": _number(source.get("duplicate_listing_total")),
                "filtered_area_total": _number(source.get("filtered_area_total")),
                "filtered_low_fit_total": _number(source.get("filtered_low_fit_total")),
                "filtered_floorplan_total": _number(source.get("filtered_floorplan_total")),
                "high_fit_total": _number(source.get("high_fit_total")),
                "top_fit_score": _number(source.get("top_fit_score")),
                "scan_truncated": bool(source.get("scan_truncated")),
                "min_area_m2": _number(source.get("min_area_m2") or applied_pushdown.get("min_area_m2")),
                "max_price_eur": _number(applied_pushdown.get("max_price_eur")),
                "min_rooms": _number(applied_pushdown.get("min_rooms")),
                "provider_filter_pushdown_json": provider_filter_pushdown,
                "provider_cache_json": provider_cache,
                "source_json": _safe_source_summary(
                    source,
                    source_label=source_label,
                    platform=platform,
                    source_url=source_url,
                ),
                "last_projected_at": projected_at,
            }
        for candidate in _candidate_rows_from_run(run):
            property_url = _text(candidate.get("property_url"), limit=1000)
            if not property_url:
                continue
            property_ref = _stable_ref(property_url, prefix="property")
            facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
            safe_facts = _safe_teable_facts(facts)
            property_rows[property_ref] = {
                "projection_id": property_ref,
                "tenant_key": normalized_tenant,
                "property_ref": property_ref,
                "property_url": property_url,
                "listing_id": _text(candidate.get("listing_id") or property_url, limit=200),
                "title": _text(candidate.get("title"), limit=240),
                "source_label": _text(candidate.get("source_label"), limit=200),
                "area_sqm": _number(safe_facts.get("area_sqm") or safe_facts.get("living_area_sqm")),
                "rooms": _number(safe_facts.get("rooms") or safe_facts.get("room_count")),
                "total_rent_eur": _number(safe_facts.get("total_rent_eur") or safe_facts.get("rent_eur")),
                "purchase_price_eur": _number(safe_facts.get("purchase_price_eur") or safe_facts.get("price_eur")),
                "postal_name": _text(safe_facts.get("postal_name") or safe_facts.get("district") or safe_facts.get("location"), limit=160),
                "property_type": _text(safe_facts.get("property_type"), limit=120),
                "facts_json": safe_facts,
                "last_seen_run_id": run_id,
                "last_seen_at": _text(run.get("updated_at") or run.get("generated_at") or projected_at, limit=120),
            }
            evaluation_id = f"evaluation:{run_principal}:{run_id}:{property_ref}"
            evaluation_rows[evaluation_id] = {
                "projection_id": evaluation_id,
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "property_ref": property_ref,
                "property_url": property_url,
                "source_ref": _text(candidate.get("source_ref"), limit=240),
                "source_label": _text(candidate.get("source_label"), limit=200),
                "fit_score": _number(candidate.get("fit_score")),
                "recommendation": _text(candidate.get("recommendation"), limit=160),
                "fit_summary": _text(candidate.get("fit_summary"), limit=240),
                "review_url": _text(candidate.get("review_url"), limit=1000),
                "tour_url": _text(candidate.get("tour_url"), limit=1000),
                "tour_status": _text(candidate.get("tour_status"), limit=80),
                "match_reasons_json": list(candidate.get("match_reasons") or []),
                "mismatch_reasons_json": list(candidate.get("mismatch_reasons") or []),
                "assessment_json": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                "facts_json": safe_facts,
                "last_projected_at": projected_at,
            }
            review_url = _text(candidate.get("review_url"), limit=1000)
            tour_url = _text(candidate.get("tour_url"), limit=1000)
            review_task_id = _text(candidate.get("review_task_id") or candidate.get("human_task_id"), limit=240)
            if review_url or tour_url or review_task_id:
                review_status = _text(candidate.get("review_status"), limit=80)
                if not review_status and review_url:
                    review_status = "ready"
                review_artifact_id = f"review_artifact:{run_principal}:{run_id}:{property_ref}"
                review_artifact_rows[review_artifact_id] = {
                    "projection_id": review_artifact_id,
                    "tenant_key": normalized_tenant,
                    "principal_id": run_principal,
                    "run_id": run_id,
                    "property_ref": property_ref,
                    "property_url": property_url,
                    "source_ref": _text(candidate.get("source_ref"), limit=240),
                    "source_label": _text(candidate.get("source_label"), limit=200),
                    "review_url": review_url,
                    "review_status": review_status,
                    "review_task_id": review_task_id,
                    "review_task_status": _text(candidate.get("review_task_status"), limit=80),
                    "review_reused": bool(candidate.get("review_reused")),
                    "queue_item_ref": _text(candidate.get("queue_item_ref"), limit=240),
                    "recommended_task_key": _text(candidate.get("recommended_task_key"), limit=240),
                    "tour_url": tour_url,
                    "tour_status": _text(candidate.get("tour_status"), limit=80),
                    "tour_blocked_reason": _text(candidate.get("blocked_reason") or candidate.get("tour_blocked_reason"), limit=240),
                    "fit_score": _number(candidate.get("fit_score")),
                    "recommendation": _text(candidate.get("recommendation"), limit=160),
                    "preference_person_id": _text(candidate.get("preference_person_id") or preference_person_id, limit=120),
                    "artifact_json": _safe_review_artifact(candidate, safe_facts=safe_facts),
                    "last_projected_at": projected_at,
                }
            shared_artifact_rows.update(
                _shared_artifacts_from_candidate(
                    candidate,
                    tenant_key=normalized_tenant,
                    principal_id=run_principal,
                    run_id=run_id,
                    property_ref=property_ref,
                    property_url=property_url,
                    candidate_ref=_text(candidate.get("candidate_ref") or property_ref, limit=240),
                    title=_text(candidate.get("title"), limit=240),
                    source_label=_text(candidate.get("source_label"), limit=200),
                    projected_at=projected_at,
                )
            )
        for task in list(run.get("research_tasks") or summary.get("research_tasks") or []):
            if not isinstance(task, dict):
                continue
            task_id = _text(task.get("task_id") or task.get("id"), limit=240)
            if not task_id:
                continue
            property_url = _text(task.get("property_url"), limit=1000)
            property_ref = _stable_ref(property_url or f"{run_id}:{task_id}", prefix="property")
            research_task_rows[f"research_task:{run_id}:{task_id}"] = {
                "projection_id": f"research_task:{run_id}:{task_id}",
                "tenant_key": normalized_tenant,
                "principal_id": run_principal,
                "run_id": run_id,
                "task_id": task_id,
                "status": _text(task.get("status"), limit=80),
                "field_key": _text(task.get("field_key") or task.get("key"), limit=160),
                "label": _text(task.get("label"), limit=240),
                "question": _text(task.get("question"), limit=1000),
                "property_ref": property_ref,
                "property_url": property_url,
                "value": _text(task.get("value"), limit=240),
                "note": _text(task.get("note"), limit=1000),
                "task_json": task,
                "last_projected_at": projected_at,
            }

    decision_loop_payload = dict(decision_loop_rows or {})
    for row in list(decision_loop_payload.get("propertyquarry_decision_ledger") or []):
        if not isinstance(row, dict):
            continue
        decision_id = _text(row.get("decision_id"), limit=240)
        if not decision_id:
            continue
        row_principal = _text(row.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and row_principal != normalized_principal:
            continue
        projection_id = f"decision:{normalized_tenant}:{row_principal}:{decision_id}"
        decision_rows[projection_id] = {
            "projection_id": projection_id,
            "tenant_key": normalized_tenant,
            "principal_id": _projection_alias(row_principal, prefix="principal"),
            "person_id": _projection_alias(row.get("person_id") or "self", prefix="person"),
            "decision_id": decision_id,
            "property_ref": _property_projection_ref(row.get("property_ref"), fallback=decision_id),
            "decision_state": _text(row.get("decision_state"), limit=80),
            "reason_keys_json": list(row.get("reason_keys_json") or row.get("reason_keys") or []),
            "source": _text(row.get("source"), limit=80),
            "actor": _text(row.get("actor"), limit=120),
            "confidence": _number(row.get("confidence")),
            "supersedes_decision_id": _text(row.get("supersedes_decision_id"), limit=240),
            "learning_applied": bool(row.get("learning_applied")),
            "aggregate_candidate": bool(row.get("aggregate_candidate")),
            "created_at": _text(row.get("created_at"), limit=120),
            "last_projected_at": projected_at,
        }

    for row in list(decision_loop_payload.get("propertyquarry_evidence_claims") or []):
        if not isinstance(row, dict):
            continue
        claim_id = _text(row.get("claim_id"), limit=240)
        if not claim_id:
            continue
        row_principal = _text(row.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and row_principal != normalized_principal:
            continue
        projection_id = f"evidence_claim:{normalized_tenant}:{row_principal}:{claim_id}"
        evidence_rows[projection_id] = {
            "projection_id": projection_id,
            "tenant_key": normalized_tenant,
            "principal_id": _projection_alias(row_principal, prefix="principal"),
            "person_id": _projection_alias(row.get("person_id") or "self", prefix="person"),
            "claim_id": claim_id,
            "property_ref": _property_projection_ref(row.get("property_ref"), fallback=claim_id),
            "decision_id": _text(row.get("decision_id"), limit=240),
            "claim_type": _text(row.get("claim_type"), limit=80),
            "claim_text": _safe_decision_claim_text(row),
            "source_type": _text(row.get("source_type"), limit=120),
            "source_ref": _stable_ref(row.get("source_ref") or claim_id, prefix="source"),
            "confidence": _text(row.get("confidence"), limit=40),
            "verification_state": _text(row.get("verification_state"), limit=80),
            "privacy_class": _text(row.get("privacy_class"), limit=80),
            "allowed_outputs_json": list(row.get("allowed_outputs_json") or row.get("allowed_outputs") or []),
            "expires_at": _text(row.get("expires_at"), limit=120),
            "created_at": _text(row.get("created_at"), limit=120),
            "last_projected_at": projected_at,
        }

    for row in list(decision_loop_payload.get("propertyquarry_agent_questions") or []):
        if not isinstance(row, dict):
            continue
        task_id = _text(row.get("task_id"), limit=240)
        if not task_id:
            continue
        row_principal = _text(row.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and row_principal != normalized_principal:
            continue
        projection_id = f"agent_question:{normalized_tenant}:{row_principal}:{task_id}"
        agent_question_rows[projection_id] = {
            "projection_id": projection_id,
            "tenant_key": normalized_tenant,
            "principal_id": _projection_alias(row_principal, prefix="principal"),
            "person_id": _projection_alias(row.get("person_id") or "self", prefix="person"),
            "task_id": task_id,
            "property_ref": _property_projection_ref(row.get("property_ref"), fallback=task_id),
            "decision_id": _text(row.get("decision_id"), limit=240),
            "question_text": _text(row.get("question_text"), limit=1200),
            "reason_key": _text(row.get("reason_key"), limit=120),
            "source_claim_id": _text(row.get("source_claim_id"), limit=240),
            "status": _text(row.get("status"), limit=80),
            "answer_source": _text(row.get("answer_source"), limit=120),
            "updated_claim_id": _text(row.get("updated_claim_id"), limit=240),
            "created_at": _text(row.get("created_at"), limit=120),
            "last_projected_at": projected_at,
        }

    for row in list(decision_loop_payload.get("propertyquarry_documents") or []):
        if not isinstance(row, dict):
            continue
        document_id = _text(row.get("document_id"), limit=240)
        if not document_id:
            continue
        row_principal = _text(row.get("principal_id") or normalized_principal, limit=240)
        if normalized_principal and row_principal != normalized_principal:
            continue
        projection_id = f"document:{normalized_tenant}:{row_principal}:{document_id}"
        document_rows[projection_id] = {
            "projection_id": projection_id,
            "tenant_key": normalized_tenant,
            "principal_id": _projection_alias(row_principal, prefix="principal"),
            "person_id": _projection_alias(row.get("person_id") or "self", prefix="person"),
            "document_id": document_id,
            "property_ref": _property_projection_ref(row.get("property_ref"), fallback=document_id),
            "decision_id": _text(row.get("decision_id"), limit=240),
            "document_type": _text(row.get("document_type"), limit=120),
            "source": _text(row.get("source"), limit=120),
            "privacy_class": _text(row.get("privacy_class"), limit=80),
            "verification_state": _text(row.get("verification_state"), limit=80),
            "extracted_claims_json": list(row.get("extracted_claims_json") or row.get("extracted_claims") or []),
            "missing_pages_json": list(row.get("missing_pages_json") or row.get("missing_pages") or []),
            "redaction_state": _text(row.get("redaction_state"), limit=80),
            "linked_risks_json": list(row.get("linked_risks_json") or row.get("linked_risks") or []),
            "created_at": _text(row.get("created_at"), limit=120),
            "last_projected_at": projected_at,
        }

    return {
        "propertyquarry_tenants": _table_rows(tenants),
        "propertyquarry_users": _table_rows(users),
        "propertyquarry_delivery_settings": _table_rows(delivery_settings),
        "propertyquarry_subscriptions": _table_rows(subscriptions),
        "propertyquarry_preferences": _table_rows(preference_rows),
        "propertyquarry_search_agents": _table_rows(search_agent_rows),
        "propertyquarry_saved_shortlist": _table_rows(saved_shortlist_rows),
        "propertyquarry_search_runs": _table_rows(search_run_rows),
        "propertyquarry_provider_sources": _table_rows(provider_source_rows),
        "propertyquarry_properties": _table_rows(property_rows),
        "propertyquarry_property_evaluations": _table_rows(evaluation_rows),
        "propertyquarry_review_artifacts": _table_rows(review_artifact_rows),
        "propertyquarry_shared_artifacts": _table_rows(shared_artifact_rows),
        "propertyquarry_research_tasks": _table_rows(research_task_rows),
        "propertyquarry_decision_ledger": _table_rows(decision_rows),
        "propertyquarry_evidence_claims": _table_rows(evidence_rows),
        "propertyquarry_agent_questions": _table_rows(agent_question_rows),
        "propertyquarry_documents": _table_rows(document_rows),
    }


def build_propertyquarry_teable_projection_summary(records: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {
        "projection_scope": "propertyquarry",
        "tenant_key": propertyquarry_teable_tenant_key(),
        "api_key_present": bool(str(os.environ.get("TEABLE_API_KEY") or "").strip()),
        "tables": [
            {
                "table_name": table_name,
                "record_count": len(records.get(table_name) or []),
                "sample_keys": sorted((records.get(table_name) or [{}])[0].keys()) if records.get(table_name) else [],
            }
            for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
        ],
    }
