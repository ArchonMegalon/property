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
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "search-runner/provider-adapters",
        "current_state": (
            "Title, summary and URL postal conflicts are filtered before ranking/notification. Source-scope extraction "
            "now normalizes all postal URL/label scopes, not only Vienna, and strips URL path tails like `/augasse`."
        ),
        "next_action": (
            "Keep broad live-provider canaries for Austrian postal-code and province slug cases, and expand fixtures as "
            "new provider-specific location encodings appear."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-soft-filters-score-only",
        "priority": "P0",
        "area": "Ranking",
        "title": "Soft filters affect score, not eligibility",
        "status": "verified",
        "user_visible": True,
        "owner_lane": "ranking/e2e",
        "current_state": (
            "Verified in unit and e2e coverage: non-hard daily-life preferences preserve the discovered hit set, while "
            "soft mismatches only score-demote, annotate distance preference notes and affect ordering/explanation."
        ),
        "next_action": (
            "Keep the soft-filter equivalence E2E in the release gate and extend it with every new What matters category."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-repair-fleet-durable",
        "priority": "P0",
        "area": "Reliability",
        "title": "Repair workflow must be executable and durable",
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "fleet/job-system",
        "current_state": (
            "Provider repair tasks, stale-run replacement, worker-exception repair and repair receipts are executable. "
            "Compact run snapshots now preserve replacement run links, repair receipts, task counts and can-auto-repair state."
        ),
        "next_action": (
            "Add provider quarantine/retry-budget receipts and a live canary proving fetch-failed provider lanes advance to "
            "replacement or completed_partial without stale queued copy."
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
        "projection_id": "pq-priority-search-wizard-feedback",
        "priority": "P0",
        "area": "Search workflow",
        "title": "Search wizard navigation and launch feedback must be immediate",
        "status": "verified",
        "user_visible": True,
        "owner_lane": "frontend/search",
        "current_state": (
            "Browser tests verify step clicks replace visible controls without accumulation, step changes scroll back to "
            "the wizard nav, the top launch button remains visible, and launch shows a busy/disabled state immediately."
        ),
        "next_action": (
            "Keep these browser tests in the release gate whenever the search setup layout is rearranged."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-dark-light-design-tokens",
        "priority": "P0",
        "area": "Design system",
        "title": "Light and dark mode must share readable component tokens",
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "frontend/design-system",
        "current_state": (
            "Sign-in provider rows now use compact shared surface/icon/button tokens and no longer show noisy Google?/Facebook? "
            "help buttons. Broader app-surface light/dark screenshot coverage is still required."
        ),
        "next_action": (
            "Replace one-off white panels/buttons with shared surface, border, icon and text tokens; screenshot-test "
            "landing, sign-in, account, search, results, research, agents, automation and pricing in both themes."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-automation-map-thumbnails",
        "priority": "P1",
        "area": "Automation",
        "title": "Automation cards use OSM district-overlay thumbnails only",
        "status": "verified",
        "user_visible": True,
        "owner_lane": "frontend/maps",
        "current_state": (
            "Verified: automation cards use the map-only preview builder, reject generic local thumbnail/point-preview "
            "fallbacks, materialize async OSM district overlays, and keep a small framing margin around selected shapes."
        ),
        "next_action": (
            "Keep map-only preview tests in the release gate and extend fixtures when new countries add district boundary data."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-tour-walkthrough-explicit-request",
        "priority": "P1",
        "area": "Tours and media",
        "title": "360 tours and walkthrough renders must be request-driven",
        "status": "verified",
        "user_visible": True,
        "owner_lane": "media-factory",
        "current_state": (
            "Verified: generated visual requests send auto_deliver=false, keep buttons disabled while queued, expose "
            "ready walkthrough links only after completion, reject Willhaben tracking endpoints as provider 360 URLs, "
            "and preserve Matterport live embeds without leaking private source URLs in public manifests."
        ),
        "next_action": (
            "Keep the manifest-backed sent-link browser test for live Matterport/3DVista and flythrough URLs; it skips "
            "locally unless PROPERTYQUARRY_SENT_LINKS_MANIFEST points at real sent links."
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
        "status": "in_progress",
        "user_visible": False,
        "owner_lane": "public-tours/security",
        "current_state": (
            "Raw tour.json is built from a narrow top-level allowlist, listing/property/source URLs and brief are "
            "excluded, served assets are manifest-bound, and the release gate now enforces those invariants."
        ),
        "next_action": (
            "Replace compatibility wrappers with dedicated PublicTourManifest/PrivateTourReceipt dataclasses and keep "
            "public action routes auth-gated."
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
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "billing/payments",
        "current_state": (
            "Pricing has been simplified; PayFunnels completion webhooks are idempotent; failed, cancelled and refunded "
            "callbacks now clear stale pending checkouts and record bounded billing event receipts; the billing surface "
            "shows a compact latest-payment row only when useful."
        ),
        "next_action": (
            "Finish downgrade/cancel policy, billing history UI, invoice handoff, failed-payment recovery copy and "
            "production PayFunnels smoke receipts."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-signin-logout-account-minimal",
        "priority": "P1",
        "area": "Account and auth",
        "title": "Sign-in, logout and account surfaces must be fast and minimal",
        "status": "open",
        "user_visible": True,
        "owner_lane": "auth/account-ux",
        "current_state": (
            "Root, sign-in, logout and account/profile flows have repeatedly exposed wasted space, unavailable provider "
            "buttons, redirect edge cases and settings that look editable when they are not."
        ),
        "next_action": (
            "Keep authenticated root fast, preserve /?home=1 as the deliberate public-home escape, hide disabled social "
            "providers, prove logout, and remove account/profile rows that cannot be acted on."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-results-recovery-controls",
        "priority": "P1",
        "area": "Results recovery",
        "title": "Filtered counts must open useful relaxation controls",
        "status": "open",
        "user_visible": True,
        "owner_lane": "results/rerun-ux",
        "current_state": (
            "Filtered-count affordances have regressed into dead clicks or scroll-only anchors. Users need immediate, "
            "low-noise ways to relax filters and see expected recovered-match counts."
        ),
        "next_action": (
            "Make every filtered-count click open a compact recovery panel with budget/radius sliders, hard-rule warnings, "
            "live newly-ranked count estimates and a smart rerun action."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-run-progress-eta-minimal",
        "priority": "P1",
        "area": "Run progress",
        "title": "Run progress and ETA must feel alive without noise",
        "status": "open",
        "user_visible": True,
        "owner_lane": "run-state/frontend",
        "current_state": (
            "Live result pages can show failed/partial states, duplicated repair text, stale queued wording, dead refresh "
            "buttons, empty detail grids and no useful ETA."
        ),
        "next_action": (
            "Auto-refresh run state without flicker, remove manual refresh buttons, show compact ETA and current useful "
            "work, deduplicate repair copy and fill minimal failure/partial summaries with actionable content."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-provider-source-labels",
        "priority": "P1",
        "area": "Run state",
        "title": "Provider and source-variant counts must be accurate",
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "run-state/provider-catalog",
        "current_state": (
            "Customer UI now derives provider display totals from real provider brands and uses source-check wording for "
            "parallel adapter/search variants, avoiding the old 156-providers trust break."
        ),
        "next_action": (
            "Keep snapshot tests on run-health labels, live progress, failed repair states and no-result summaries; extend "
            "the same provider/source distinction to any new management surfaces."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-scout-notification-quality",
        "priority": "P1",
        "area": "Notifications",
        "title": "Scout updates only send strong, valid matches",
        "status": "in_progress",
        "user_visible": True,
        "owner_lane": "notifications/scout",
        "current_state": (
            "Scout notifications now strip search-scope labels and enforce a hard 60/100 outbound floor even if the env "
            "override is misconfigured lower. Wrong-area and generic-page suppression has focused regression coverage."
        ),
        "next_action": (
            "Keep broad live-provider canaries for wrong-area candidates, suppress maybe-false rows from ranking, and "
            "include concise source/listing links only when the candidate is eligible."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-performance-first-load",
        "priority": "P1",
        "area": "Performance",
        "title": "First-load performance for app, agents and research pages",
        "status": "open",
        "user_visible": True,
        "owner_lane": "frontend/performance",
        "current_state": (
            "Root and app landing were improved, but agents and some research detail pages can still feel slow when "
            "thumbnails, maps, media state or large run payloads are initialized synchronously."
        ),
        "next_action": (
            "Precompute agent map thumbnails, lazy-load heavy media/research sections, keep authenticated navigation "
            "under the route budget, and add authenticated smoke/performance probes."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-research-page-premium-performance",
        "priority": "P1",
        "area": "Research detail",
        "title": "Research pages must load fast and fit the decision workflow",
        "status": "open",
        "user_visible": True,
        "owner_lane": "research/frontend",
        "current_state": (
            "Some research pages take too long to load, waste vertical space, look visually uneven and block tour/"
            "walkthrough actions instead of showing a clear requested-media state."
        ),
        "next_action": (
            "Slim the research layout to one-screen decision density, lazy-load expensive media/state, keep 360 first, "
            "make request-tour/request-walkthrough buttons explicit and add screenshot tests."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-mobile-pwa",
        "priority": "P1",
        "area": "Mobile",
        "title": "Mobile and PWA posture",
        "status": "open",
        "user_visible": True,
        "owner_lane": "frontend/mobile",
        "current_state": (
            "The product needs an explicit mobile/PWA answer for search review, shortlist, viewing companion, account and "
            "share flows, not only responsive desktop pages."
        ),
        "next_action": (
            "Audit mobile breakpoints, add installable PWA metadata if appropriate, validate offline-safe viewing notes "
            "scope, and add mobile screenshot smoke tests for core surfaces."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-prompt-injection-boundary",
        "priority": "P1",
        "area": "Security",
        "title": "Untrusted listing and document content is data, never instruction",
        "status": "in_progress",
        "user_visible": False,
        "owner_lane": "security/research-pipeline",
        "current_state": (
            "Listing-text extraction strips scripted/hidden content and flags instruction-like text. Content-studio source "
            "packets and generated drafts now fail validation on prompt-injection language and hidden/scripted markup."
        ),
        "next_action": (
            "Extend the same boundary to uploaded PDF metadata/OCR, external feeds and every LLM research prompt; keep "
            "malicious fixtures in release gates and record prompt/schema versions."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-legal-trust-pages",
        "priority": "P1",
        "area": "Trust and legal",
        "title": "Public trust, legal, attribution and disclaimer pages",
        "status": "open",
        "user_visible": True,
        "owner_lane": "public/trust",
        "current_state": (
            "The paid public product needs reviewed privacy, terms, imprint, cookie, subprocessors, refund, support, "
            "property-data attribution, generated-tour and investment-education disclaimers."
        ),
        "next_action": (
            "Ship the public legal/trust route set, link it from footer/account where relevant, and keep legal copy separate "
            "from marketing or AI-generated content optimization."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-accessibility-release-gate",
        "priority": "P1",
        "area": "Accessibility",
        "title": "Accessibility must become a release gate",
        "status": "open",
        "user_visible": True,
        "owner_lane": "frontend/accessibility",
        "current_state": (
            "Polish passes cover visual layout, but accessibility is not yet a first-class exit gate across public, app, "
            "results, research, account, pricing and generated artifact surfaces."
        ),
        "next_action": (
            "Add axe, keyboard, focus, contrast, reduced-motion, touch-target and dialog checks; include PDF language, "
            "heading order, bookmarks and accessible link labels for generated dossiers."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-external-investment-feed-hardening",
        "priority": "P1",
        "area": "Investment data",
        "title": "External investment feeds need host allowlist and protected cache",
        "status": "done",
        "user_visible": False,
        "owner_lane": "investment/security",
        "current_state": (
            "External investment feeds now require an allowed-host configuration for HTTPS, only allow local insecure "
            "HTTP by explicit env, default to /docker/property/state, cap response size and chmod cache files to 0600."
        ),
        "next_action": (
            "Keep the focused feed-hardening tests in the release gate and add production source freshness/attribution "
            "receipts before surfacing investment outputs broadly."
        ),
        "source": "whole-product audit",
    },
    {
        "projection_id": "pq-priority-content-studio-subscribr",
        "priority": "P2",
        "area": "Content studio",
        "title": "Subscribr content studio with source-bound script packets",
        "status": "open",
        "user_visible": False,
        "owner_lane": "content-studio/integrations",
        "current_state": (
            "Subscribr should be an operator-governed video-script and content pre-production lane, not a property truth, "
            "ranking, billing or publication authority."
        ),
        "next_action": (
            "Implement source-packet contracts, privacy/fair-housing/freshness validation, Subscribr receipts, human review "
            "and direct-publish disabled gates before any live listing content is used."
        ),
        "source": "Subscribr integration guide",
    },
    {
        "projection_id": "pq-priority-ltd-integration-roadmap",
        "priority": "P2",
        "area": "Integration roadmap",
        "title": "Governed LTD integrations that fill missing product systems",
        "status": "open",
        "user_visible": False,
        "owner_lane": "integration-governance",
        "current_state": (
            "The next LTD work should add product systems rather than more generators: MetaSurvey, Lunacal, ApiX-Drive, "
            "Invoiless, Documentation.AI, Paperguide, Internxt, ApproveThis and Unmixr only under boundaries."
        ),
        "next_action": (
            "Implement one shared adapter contract with allowed data classes, kill switches, receipts and delete behavior; "
            "start with MetaSurvey/Lunacal and ApiX-Drive/Invoiless."
        ),
        "source": "LTD integration audit",
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
