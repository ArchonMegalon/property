from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ea"))

from app.repositories.onboarding_state_postgres import PostgresOnboardingStateRepository  # noqa: E402
from app.services.propertyquarry_teable_projection import (  # noqa: E402
    PROPERTYQUARRY_TEABLE_TABLE_NAMES,
    discover_propertyquarry_teable_table_config,
)


def _jsonable(value: object) -> object:
    if isinstance(value, str):
        text = value.strip()
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                return json.loads(text)
            except Exception:
                return value
    return value


def _table_config_from_env(*, base_url: str, api_key: str, base_id: str, base_name: str) -> dict[str, dict[str, object]]:
    raw = str(os.environ.get("PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON") or "").strip()
    if not raw:
        raw = str(os.environ.get("TEABLE_TABLE_SYNC_CONFIG_JSON") or "").strip()
    if not raw:
        discovered = discover_propertyquarry_teable_table_config(
            base_url=base_url,
            api_key=api_key,
            base_id=base_id,
            base_name=base_name,
        )
        if discovered:
            return discovered
        raise SystemExit("missing PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON or PROPERTYQUARRY_TEABLE_BASE_ID")
    try:
        loaded = json.loads(raw)
    except Exception as exc:
        raise SystemExit("invalid PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON") from exc
    if not isinstance(loaded, dict):
        raise SystemExit("invalid PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON")
    return {
        str(table_name or "").strip(): dict(config or {})
        for table_name, config in loaded.items()
        if str(table_name or "").strip() and isinstance(config, dict)
    }


def _request_json(*, method: str, url: str, api_key: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "PropertyQuarryTeableRestore/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = str(exc)[:500]
        raise SystemExit(f"Teable HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise SystemExit(f"Teable request failed: {str(exc)[:500]}") from exc
    if not payload.strip():
        return {}
    try:
        loaded = json.loads(payload)
    except Exception as exc:
        raise SystemExit("Teable returned invalid JSON") from exc
    return dict(loaded or {})


def fetch_teable_projection_records(
    *,
    base_url: str,
    api_key: str,
    table_config: dict[str, dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    records_by_table: dict[str, list[dict[str, object]]] = {}
    normalized_base = str(base_url or "https://app.teable.ai").strip().rstrip("/")
    for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES:
        config = dict(table_config.get(table_name) or {})
        table_id = str(config.get("table_id") or "").strip()
        field_key_type = str(config.get("field_key_type") or "name").strip() or "name"
        if not table_id:
            records_by_table[table_name] = []
            continue
        rows: list[dict[str, object]] = []
        skip = 0
        take = 1000
        while True:
            query = urllib.parse.urlencode(
                {
                    "fieldKeyType": field_key_type,
                    "cellFormat": "json",
                    "take": take,
                    "skip": skip,
                }
            )
            payload = _request_json(
                method="GET",
                url=f"{normalized_base}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
                api_key=api_key,
            )
            records = [dict(item) for item in payload.get("records") or [] if isinstance(item, dict)]
            for record in records:
                fields = {
                    str(key or "").strip(): _jsonable(value)
                    for key, value in dict(record.get("fields") or {}).items()
                    if str(key or "").strip()
                }
                if fields:
                    rows.append(fields)
            if len(records) < take:
                break
            skip += take
        records_by_table[table_name] = rows
    return records_by_table


def _first_row(rows: list[dict[str, object]], *, principal_id: str = "") -> dict[str, object]:
    for row in rows:
        if principal_id and str(row.get("principal_id") or "").strip() != principal_id:
            continue
        return dict(row)
    return {}


def _coerce_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        parsed = _jsonable(value)
        if isinstance(parsed, list):
            return parsed
        if value.strip():
            return [value.strip()]
    return []


def _coerce_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    parsed = _jsonable(value)
    if isinstance(parsed, dict):
        return dict(parsed)
    return {}


def _saved_candidates_from_evaluations(
    *,
    principal_id: str,
    records_by_table: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    properties = {
        str(row.get("property_ref") or "").strip(): dict(row)
        for row in records_by_table.get("propertyquarry_properties", [])
        if str(row.get("property_ref") or "").strip()
    }
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in records_by_table.get("propertyquarry_property_evaluations", []):
        if str(row.get("principal_id") or "").strip() != principal_id:
            continue
        property_ref = str(row.get("property_ref") or "").strip()
        if not property_ref or property_ref in seen:
            continue
        seen.add(property_ref)
        property_row = properties.get(property_ref, {})
        facts = _coerce_dict(row.get("facts_json") or property_row.get("facts_json"))
        candidate = {
            "property_ref": property_ref,
            "candidate_ref": property_ref,
            "property_url": str(row.get("property_url") or property_row.get("property_url") or "").strip(),
            "listing_id": str(property_row.get("listing_id") or "").strip(),
            "title": str(property_row.get("title") or "").strip(),
            "source_label": str(row.get("source_label") or property_row.get("source_label") or "").strip(),
            "fit_score": row.get("fit_score"),
            "recommendation": str(row.get("recommendation") or "").strip(),
            "fit_summary": str(row.get("fit_summary") or "").strip(),
            "review_url": str(row.get("review_url") or "").strip(),
            "tour_url": str(row.get("tour_url") or "").strip(),
            "tour_status": str(row.get("tour_status") or "").strip(),
            "saved_from_run_id": str(row.get("run_id") or "").strip(),
            "property_facts": facts,
        }
        candidates.append(candidate)
    candidates.sort(key=lambda item: float(item.get("fit_score") or 0), reverse=True)
    return candidates[:200]


def build_restore_bundle(
    *,
    principal_id: str,
    records_by_table: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        raise ValueError("principal_id_required")
    user = _first_row(records_by_table.get("propertyquarry_users", []), principal_id=normalized_principal)
    delivery = _first_row(records_by_table.get("propertyquarry_delivery_settings", []), principal_id=normalized_principal)
    preferences_row = _first_row(records_by_table.get("propertyquarry_preferences", []), principal_id=normalized_principal)
    preferences = _coerce_dict(preferences_row.get("preferences_json"))
    preferences.setdefault("country_code", str(preferences_row.get("country_code") or "").strip())
    preferences.setdefault("listing_mode", str(preferences_row.get("listing_mode") or "").strip())
    preferences.setdefault("property_type", str(preferences_row.get("property_type") or "").strip())
    preferences.setdefault("location_query", str(preferences_row.get("location_query") or "").strip())
    if not preferences.get("selected_platforms"):
        preferences["selected_platforms"] = _coerce_list(preferences_row.get("selected_platforms_json"))
    saved_candidates = list(preferences.get("saved_shortlist_candidates") or [])
    if not saved_candidates:
        saved_candidates = _saved_candidates_from_evaluations(
            principal_id=normalized_principal,
            records_by_table=records_by_table,
        )
        if saved_candidates:
            preferences["saved_shortlist_candidates"] = saved_candidates
    selected_channels = [
        str(value or "").strip().lower()
        for value in _coerce_list(delivery.get("selected_channels_json") or user.get("selected_channels_json"))
        if str(value or "").strip()
    ]
    preferred_channel = str(delivery.get("preferred_channel") or "email").strip().lower() or "email"
    if preferred_channel and preferred_channel not in selected_channels:
        selected_channels.append(preferred_channel)
    whatsapp_phone = str(delivery.get("whatsapp_ai_support_phone") or "").strip()
    if whatsapp_phone and "whatsapp" not in selected_channels:
        selected_channels.append("whatsapp")
    property_notifications = {
        "preferred_channel": preferred_channel,
        "preferred_label": str(delivery.get("preferred_label") or preferred_channel.title()).strip(),
        "notification_scope": str(delivery.get("notification_scope") or "scout_updates").strip(),
        "whatsapp_notification_opt_in": bool(delivery.get("whatsapp_notification_opt_in")),
        "whatsapp_ai_support_phone": whatsapp_phone,
        "whatsapp_ai_support_status": "ready" if whatsapp_phone else "missing",
        "whatsapp_ai_support_purpose": str(delivery.get("whatsapp_ai_support_purpose") or "").strip(),
        "signal_status": str(delivery.get("signal_status") or "coming_soon").strip(),
    }
    return {
        "contract_name": "propertyquarry.teable_restore_bundle.v1",
        "principal_id": normalized_principal,
        "status": "ready",
        "onboarding_state": {
            "workspace_name": str(user.get("workspace_name") or "PropertyQuarry").strip() or "PropertyQuarry",
            "workspace_mode": str(user.get("workspace_mode") or "personal").strip() or "personal",
            "region": str(user.get("region") or "").strip(),
            "language": str(user.get("language") or "").strip(),
            "timezone": str(user.get("timezone") or "").strip(),
            "selected_channels": sorted(set(selected_channels)),
            "property_search_preferences_json": preferences,
            "channel_preferences_json": {"property_notifications": property_notifications},
            "status": "completed",
        },
        "saved_result_count": len(saved_candidates),
        "source_tables": {
            table_name: len(records_by_table.get(table_name) or [])
            for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
        },
    }


def apply_restore_bundle(*, bundle: dict[str, object], database_url: str) -> dict[str, object]:
    state = _coerce_dict(bundle.get("onboarding_state"))
    principal_id = str(bundle.get("principal_id") or "").strip()
    if not principal_id:
        raise ValueError("principal_id_required")
    repo = PostgresOnboardingStateRepository(database_url)
    saved = repo.upsert_state(
        principal_id=principal_id,
        workspace_name=str(state.get("workspace_name") or "PropertyQuarry"),
        workspace_mode=str(state.get("workspace_mode") or "personal"),
        region=str(state.get("region") or ""),
        language=str(state.get("language") or ""),
        timezone=str(state.get("timezone") or ""),
        selected_channels=tuple(str(value or "").strip().lower() for value in _coerce_list(state.get("selected_channels"))),
        property_search_preferences_json=_coerce_dict(state.get("property_search_preferences_json")),
        channel_preferences_json=_coerce_dict(state.get("channel_preferences_json")),
        status=str(state.get("status") or "completed"),
    )
    return {
        "status": "applied",
        "principal_id": saved.principal_id,
        "selected_channels": list(saved.selected_channels),
        "saved_result_count": bundle.get("saved_result_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore PropertyQuarry account/results state from Teable projections.")
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--base-url", default=os.environ.get("TEABLE_BASE_URL") or "https://app.teable.ai")
    parser.add_argument("--base-id", default=os.environ.get("PROPERTYQUARRY_TEABLE_BASE_ID") or os.environ.get("TEABLE_BASE_ID") or "")
    parser.add_argument("--base-name", default=os.environ.get("PROPERTYQUARRY_TEABLE_TENANT_NAME") or "PropertyQuarry")
    parser.add_argument("--api-key", default=os.environ.get("TEABLE_API_KEY") or "")
    parser.add_argument("--output", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL") or "")
    args = parser.parse_args()
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("missing TEABLE_API_KEY")
    records = fetch_teable_projection_records(
        base_url=str(args.base_url or "https://app.teable.ai"),
        api_key=api_key,
        table_config=_table_config_from_env(
            base_url=str(args.base_url or "https://app.teable.ai"),
            api_key=api_key,
            base_id=str(args.base_id or ""),
            base_name=str(args.base_name or "PropertyQuarry"),
        ),
    )
    bundle = build_restore_bundle(principal_id=str(args.principal_id), records_by_table=records)
    if args.output:
        Path(args.output).write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.apply:
        database_url = str(args.database_url or "").strip()
        if not database_url:
            raise SystemExit("missing DATABASE_URL for --apply")
        result = apply_restore_bundle(bundle=bundle, database_url=database_url)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
