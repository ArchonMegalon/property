#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENV_FILES = (
    Path("/docker/property/.env"),
    Path("/docker/EA/.env"),
)

TABLE_NAME = "propertyquarry_product_priorities"

FIELDS = [
    {"name": "projection_id", "type": "singleLineText", "unique": True},
    {"name": "priority", "type": "singleLineText"},
    {"name": "area", "type": "singleLineText"},
    {"name": "title", "type": "singleLineText"},
    {"name": "status", "type": "singleLineText"},
    {"name": "user_visible", "type": "checkbox"},
    {"name": "owner_lane", "type": "singleLineText"},
    {"name": "current_state", "type": "longText"},
    {"name": "next_action", "type": "longText"},
    {"name": "source", "type": "singleLineText"},
    {"name": "updated_at", "type": "singleLineText"},
]

PRIORITIES = [
    {
        "projection_id": "pq-priority-search-location-hard-filters",
        "priority": "P0",
        "area": "Search correctness",
        "title": "Postal-code and district hard filters must never leak wrong areas",
        "status": "open",
        "user_visible": True,
        "owner_lane": "search-runner/provider-adapters",
        "current_state": (
            "Live scouting repeatedly surfaced Salzburg, Schaerding, 1200, 1220 and other non-selected "
            "areas under a 1010 Vienna search label. Area selection is a hard rule, unlike soft lifestyle preferences."
        ),
        "next_action": (
            "Normalize postal codes from title, description, URL, provider metadata and address fields; reject hard-area "
            "violations before ranking or notifications; add provider-check fixtures for all Austrian postal-code cases."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-soft-filters-score-only",
        "priority": "P0",
        "area": "Ranking",
        "title": "Soft filters affect score, not eligibility",
        "status": "open",
        "user_visible": True,
        "owner_lane": "ranking/e2e",
        "current_state": (
            "Runs with many optional preferences can leave hundreds of candidates outside the shortlist. Must-have and "
            "hard rules may filter; neutral/nice/strong preferences should score and explain."
        ),
        "next_action": (
            "Keep the soft-filter equivalence E2E: same hard criteria with and without soft filters must inspect the same "
            "candidate set; only ordering, score and explanation may change."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-repair-fleet-durable",
        "priority": "P0",
        "area": "Reliability",
        "title": "Repair workflow must be executable and durable",
        "status": "open",
        "user_visible": True,
        "owner_lane": "fleet/job-system",
        "current_state": (
            "Interrupted and fetch-failed runs show repair copy, but the customer can still see stale queued states and "
            "partial coverage without a clear completed retry."
        ),
        "next_action": (
            "Persist repair attempts, checkpoints, provider quarantine, retry budget and terminal completed_partial states; "
            "make failed runs trigger repair jobs automatically with idempotent receipts."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-ui-minimal-polish",
        "priority": "P0",
        "area": "UX polish",
        "title": "Every surface must be minimal, readable and purposeful",
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "frontend/design-system",
        "current_state": (
            "The product still has copy that feels internal, repeated status rows, oversized panels, dark-mode contrast "
            "edge cases and controls that sometimes lack immediate feedback."
        ),
        "next_action": (
            "Audit landing, search, results, research, agents, automation, account, sign-in, pricing and legal pages in "
            "light/dark/mobile; remove non-actionable proof/check wording and verify clickable affordances."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-automation-map-thumbnails",
        "priority": "P1",
        "area": "Automation",
        "title": "Automation cards use OSM district-overlay thumbnails only",
        "status": "open",
        "user_visible": True,
        "owner_lane": "frontend/maps",
        "current_state": (
            "Automation thumbnails should show selected district shapes with a small margin. Generic thumbnail pipelines "
            "should not replace the map-based previews."
        ),
        "next_action": (
            "Pre-render/cached district-overlay thumbnails for agents; fit all selected shapes without cutting them off; "
            "delete the unrelated thumbnail fallback path."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-tour-walkthrough-explicit-request",
        "priority": "P1",
        "area": "Tours and media",
        "title": "360 tours and walkthrough renders must be request-driven",
        "status": "open",
        "user_visible": True,
        "owner_lane": "media-factory",
        "current_state": (
            "Provider 360/Matterport/3DVista links should be enabled when present. Generated walkthrough/video work must "
            "not start by default or burn credits without a user action."
        ),
        "next_action": (
            "E2E test provider live-360 detection, Matterport/3DVista routing, blocked synthetic fallback, and explicit "
            "request buttons for generated media."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-account-lifecycle",
        "priority": "P1",
        "area": "Account lifecycle",
        "title": "Account data controls need export, deletion, sessions and shared-link revocation",
        "status": "open",
        "user_visible": True,
        "owner_lane": "account/privacy",
        "current_state": (
            "Account surfaces still focus on profile and delivery. Paid users need durable lifecycle controls for their "
            "searches, documents, public packets, sessions and preferences."
        ),
        "next_action": (
            "Add export/delete/search-history controls, active sessions, revoke shared links, consent history, learning "
            "opt-out and property-specific retention."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-public-tour-manifest",
        "priority": "P1",
        "area": "Privacy/security",
        "title": "Public tour manifests must be positive-schema safe at rest",
        "status": "open",
        "user_visible": False,
        "owner_lane": "public-tours/security",
        "current_state": (
            "Redaction is improved, but public artifacts should be constructed from a narrow manifest schema rather than "
            "broad payload copying plus redaction."
        ),
        "next_action": (
            "Separate PublicTourManifest from private receipts; require every served asset to be in the public manifest; "
            "directly inspect raw tour.json in tests."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-provider-rights-readiness",
        "priority": "P1",
        "area": "Provider governance",
        "title": "Provider rights and market-readiness registry",
        "status": "open",
        "user_visible": False,
        "owner_lane": "provider-governance",
        "current_state": (
            "Providers have operational quality metadata but not enough explicit rights, cache, publication, attribution "
            "and market-readiness controls."
        ),
        "next_action": (
            "Track access mode, terms review, caching rights, media republication, max request rate, attribution and "
            "market readiness before exposing providers/countries as public-ready."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-payfunnels-commercial-lifecycle",
        "priority": "P1",
        "area": "Billing",
        "title": "Finish PayFunnels commercial lifecycle",
        "status": "open",
        "user_visible": True,
        "owner_lane": "billing/payments",
        "current_state": (
            "Pricing has been simplified, but the paid lifecycle still needs complete PayFunnels verification, entitlement "
            "activation, invoice handoff and failure handling."
        ),
        "next_action": (
            "Implement PayFunnels webhook/payment verification, plan entitlement transitions, billing history, downgrade/"
            "cancel behavior and invoice handoff."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-property-passport",
        "priority": "P2",
        "area": "Product moat",
        "title": "Canonical property passport and change intelligence",
        "status": "open",
        "user_visible": True,
        "owner_lane": "property-memory",
        "current_state": (
            "The product is still run/candidate-centric. Durable value comes from one property identity that accumulates "
            "listings, claims, documents, media, decisions, viewings and outcomes."
        ),
        "next_action": (
            "Introduce property_entities, listing_instances, property_claims, property_events, property_documents, "
            "property_decisions and viewing/outcome states; build 'what changed since last review'."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-observability-dr",
        "priority": "P2",
        "area": "Operations",
        "title": "Observability, SLOs and restore drills",
        "status": "open",
        "user_visible": False,
        "owner_lane": "ops",
        "current_state": (
            "Logs and container health are not enough for a paid product. Search duration, provider coverage, queue age, "
            "render success, notification success and restore ability need measurable proof."
        ),
        "next_action": (
            "Add SLO dashboards, provider canaries, queue-depth alerts, encrypted backups, artifact backup and regular "
            "restore drills with RPO/RTO."
        ),
        "source": "whole-product audit",
    },
]


def _load_env_files(*paths: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in loaded:
                loaded[key] = value.strip().strip("'").strip('"')
    return loaded


def _env_value(name: str, defaults: dict[str, str], fallback: str = "") -> str:
    return str(os.environ.get(name) or defaults.get(name) or fallback).strip()


def _request_json(
    *,
    method: str,
    url: str,
    api_key: str,
    body: dict[str, object] | None = None,
) -> object:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://app.teable.ai",
            "Referer": "https://app.teable.ai/",
            "User-Agent": "PropertyQuarryTeablePriorityMaterializer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:1000]
        raise SystemExit(f"HTTP {exc.code} from Teable: {detail}") from exc
    except Exception as exc:
        raise SystemExit(f"Teable request failed: {exc}") from exc
    if not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except Exception as exc:
        raise SystemExit(f"Teable returned invalid JSON: {exc}") from exc


def _items(payload: object, key_names: tuple[str, ...]) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in key_names:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _extract_id(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("id", "tableId"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        for key in ("table", "data"):
            value = _extract_id(payload.get(key))
            if value:
                return value
    return ""


def _list_tables(*, base_url: str, api_key: str, base_id: str) -> dict[str, str]:
    payload = _request_json(
        method="GET",
        url=f"{base_url}/api/base/{urllib.parse.quote(base_id)}/table",
        api_key=api_key,
    )
    tables: dict[str, str] = {}
    for item in _items(payload, ("tables", "data", "items")):
        name = str(item.get("name") or item.get("tableName") or "").strip()
        table_id = str(item.get("id") or item.get("tableId") or "").strip()
        if name and table_id:
            tables[name] = table_id
    return tables


def _ensure_table(*, base_url: str, api_key: str, base_id: str) -> tuple[str, bool]:
    tables = _list_tables(base_url=base_url, api_key=api_key, base_id=base_id)
    existing = str(tables.get(TABLE_NAME) or "").strip()
    if existing:
        return existing, False
    payload = _request_json(
        method="POST",
        url=f"{base_url}/api/base/{urllib.parse.quote(base_id)}/table/",
        api_key=api_key,
        body={"name": TABLE_NAME, "fields": FIELDS, "fieldKeyType": "name"},
    )
    table_id = _extract_id(payload)
    if not table_id:
        raise SystemExit(f"Teable create-table response did not include a table id for {TABLE_NAME}")
    return table_id, True


def _existing_records(*, base_url: str, api_key: str, table_id: str) -> dict[str, str]:
    found: dict[str, str] = {}
    skip = 0
    take = 1000
    while True:
        query = urllib.parse.urlencode(
            {
                "fieldKeyType": "name",
                "cellFormat": "json",
                "take": take,
                "skip": skip,
                "projection": "projection_id",
            }
        )
        payload = _request_json(
            method="GET",
            url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
            api_key=api_key,
        )
        records = _items(payload, ("records", "data", "items"))
        for record in records:
            fields = dict(record.get("fields") or {})
            projection_id = str(fields.get("projection_id") or "").strip()
            record_id = str(record.get("id") or "").strip()
            if projection_id and record_id:
                found[projection_id] = record_id
        if len(records) < take:
            break
        skip += take
    return found


def _upsert_rows(*, base_url: str, api_key: str, table_id: str, rows: list[dict[str, object]]) -> tuple[int, int]:
    existing = _existing_records(base_url=base_url, api_key=api_key, table_id=table_id)
    created = 0
    updated = 0
    pending_creates: list[dict[str, object]] = []
    for row in rows:
        projection_id = str(row.get("projection_id") or "").strip()
        if not projection_id:
            raise SystemExit("priority row missing projection_id")
        record_id = str(existing.get(projection_id) or "").strip()
        if record_id:
            _request_json(
                method="PATCH",
                url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
                api_key=api_key,
                body={
                    "fieldKeyType": "name",
                    "typecast": True,
                    "record": {"fields": row},
                },
            )
            updated += 1
        else:
            pending_creates.append({"fields": row})
    for start in range(0, len(pending_creates), 50):
        chunk = pending_creates[start : start + 50]
        payload = _request_json(
            method="POST",
            url=f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record",
            api_key=api_key,
            body={"fieldKeyType": "name", "typecast": True, "records": chunk},
        )
        records = _items(payload, ("records", "data", "items"))
        created += len(records) or len(chunk)
    return created, updated


def parse_args() -> argparse.Namespace:
    defaults = _load_env_files(*DEFAULT_ENV_FILES)
    parser = argparse.ArgumentParser(description="Materialize key PropertyQuarry product priorities into Teable.")
    parser.add_argument("--base-url", default=_env_value("TEABLE_BASE_URL", defaults, "https://app.teable.ai"))
    parser.add_argument("--api-key", default=_env_value("TEABLE_API_KEY", defaults))
    parser.add_argument("--base-id", default=_env_value("PROPERTYQUARRY_TEABLE_BASE_ID", defaults))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = str(args.base_url or "https://app.teable.ai").strip().rstrip("/")
    api_key = str(args.api_key or "").strip()
    base_id = str(args.base_id or "").strip()
    if not api_key:
        raise SystemExit("missing TEABLE_API_KEY")
    if not base_id:
        raise SystemExit("missing PROPERTYQUARRY_TEABLE_BASE_ID")
    table_id, created_table = _ensure_table(base_url=base_url, api_key=api_key, base_id=base_id)
    updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [{**row, "updated_at": updated_at} for row in PRIORITIES]
    created, updated = _upsert_rows(base_url=base_url, api_key=api_key, table_id=table_id, rows=rows)
    print(
        json.dumps(
            {
                "status": "ready",
                "table_name": TABLE_NAME,
                "table_id": table_id,
                "created_table": created_table,
                "created_count": created,
                "updated_count": updated,
                "row_count": len(rows),
                "priority_counts": {
                    priority: sum(1 for row in rows if row.get("priority") == priority)
                    for priority in sorted({str(row.get("priority") or "") for row in rows})
                },
                "updated_at": updated_at,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
