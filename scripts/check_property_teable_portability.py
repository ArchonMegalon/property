from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ea"))

from app.services.propertyquarry_teable_projection import (  # noqa: E402
    PROPERTYQUARRY_TEABLE_TABLE_FIELDS,
    PROPERTYQUARRY_TEABLE_TABLE_NAMES,
)


REQUIRED_TABLE_FIELDS: dict[str, set[str]] = {
    "propertyquarry_users": {
        "principal_id",
        "workspace_name",
        "workspace_mode",
        "selected_channels_json",
        "current_plan_key",
    },
    "propertyquarry_delivery_settings": {
        "principal_id",
        "preferred_channel",
        "notification_scope",
        "selected_channels_json",
        "telegram_enabled",
        "whatsapp_enabled",
        "whatsapp_notification_opt_in",
        "whatsapp_ai_support_phone",
        "signal_status",
    },
    "propertyquarry_subscriptions": {
        "principal_id",
        "current_plan_key",
        "status",
        "active_until",
        "last_order_id",
        "last_payment_status",
    },
    "propertyquarry_preferences": {
        "principal_id",
        "country_code",
        "listing_mode",
        "property_type",
        "location_query",
        "selected_platforms_json",
        "preferences_json",
    },
    "propertyquarry_search_agents": {
        "principal_id",
        "agent_id",
        "name",
        "enabled",
        "location_query",
        "preferences_json",
    },
    "propertyquarry_search_runs": {
        "principal_id",
        "run_id",
        "status",
        "listing_total",
        "high_fit_total",
        "summary_json",
    },
    "propertyquarry_provider_sources": {
        "principal_id",
        "run_id",
        "source_label",
        "source_url",
        "provider_cache_key",
        "source_json",
    },
    "propertyquarry_properties": {
        "property_ref",
        "property_url",
        "listing_id",
        "title",
        "facts_json",
        "last_seen_run_id",
    },
    "propertyquarry_property_evaluations": {
        "principal_id",
        "run_id",
        "property_ref",
        "fit_score",
        "review_url",
        "tour_url",
        "facts_json",
    },
    "propertyquarry_review_artifacts": {
        "principal_id",
        "run_id",
        "property_ref",
        "review_url",
        "review_status",
        "tour_status",
        "artifact_json",
    },
    "propertyquarry_research_tasks": {
        "principal_id",
        "run_id",
        "task_id",
        "status",
        "property_ref",
        "task_json",
    },
    "propertyquarry_decision_ledger": {
        "principal_id",
        "decision_id",
        "property_ref",
        "decision_state",
        "reason_keys_json",
    },
    "propertyquarry_evidence_claims": {
        "principal_id",
        "claim_id",
        "property_ref",
        "claim_type",
        "claim_text",
        "verification_state",
    },
    "propertyquarry_agent_questions": {
        "principal_id",
        "task_id",
        "property_ref",
        "question_text",
        "status",
    },
    "propertyquarry_documents": {
        "principal_id",
        "document_id",
        "property_ref",
        "document_type",
        "verification_state",
        "extracted_claims_json",
    },
}


def _field_names(table_name: str) -> set[str]:
    return {
        str(field.get("name") or "").strip()
        for field in PROPERTYQUARRY_TEABLE_TABLE_FIELDS.get(table_name, [])
        if isinstance(field, dict) and str(field.get("name") or "").strip()
    }


def main() -> int:
    declared_tables = set(PROPERTYQUARRY_TEABLE_TABLE_NAMES)
    failures: list[str] = []
    for table_name, required_fields in sorted(REQUIRED_TABLE_FIELDS.items()):
        if table_name not in declared_tables:
            failures.append(f"missing_table:{table_name}")
            continue
        missing_fields = sorted(required_fields - _field_names(table_name))
        if missing_fields:
            failures.append(f"missing_fields:{table_name}:{','.join(missing_fields)}")
    extra_missing_config = sorted(declared_tables - set(PROPERTYQUARRY_TEABLE_TABLE_FIELDS))
    for table_name in extra_missing_config:
        failures.append(f"missing_field_config:{table_name}")
    payload = {
        "contract_name": "propertyquarry.teable_portability.v1",
        "status": "pass" if not failures else "fail",
        "required_table_count": len(REQUIRED_TABLE_FIELDS),
        "declared_table_count": len(declared_tables),
        "failures": failures,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
