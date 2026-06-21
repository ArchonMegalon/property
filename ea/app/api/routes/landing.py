from __future__ import annotations

import contextlib
import html
import hmac
import hashlib
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.api.dependencies import (
    RequestContext,
    _extract_token,
    _resolved_principal_id,
    _workspace_session_payload,
    browser_principal_override_allowed,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    require_operator_context,
)
from app.api.routes.landing_content import (
    ADMIN_NAV_GROUPS,
    APP_NAV_GROUPS,
    app_nav_groups_for_brand,
    DOC_LINKS,
    FEATURE_CARDS,
    HOW_STEPS,
    LANDING_FAQS,
    PERSONAS,
    PRICING_TIERS,
    PRODUCT_MODULES,
    PUBLIC_NAV,
    PUBLIC_TRUST_PAGES,
    SIGN_IN_NOTES,
    TRUST_CARDS,
)
from app.api.routes.landing_property_surface_contracts import PropertySurfaceScope
from app.api.routes.landing_property_workspace_helpers import _compact_provider_label
from app.api.routes.landing_view_models import (
    app_section_payload as _app_section_payload,
    channel_cards as _channel_cards,
    humanize as _humanize,
    list_rows as _list_rows,
    property_workspace_payload as _property_workspace_payload,
)
from app.api.routes.landing_property_research import (
    _candidate_detail_sections,
    _evidence_detail_rows,
    _google_maps_embed_url,
    _object_detail_row,
    _official_risk_posture_rows,
    _property_distance_ooda_rows,
    _property_distance_ooda_rows_for_preferences,
    _property_candidate_orientation_preview,
    _property_candidate_preview_image,
    _property_candidate_ref,
    _property_enriched_candidate_facts,
    _property_fact_rows,
    _property_investment_research_rows,
    _property_lookup_candidate,
    _property_missing_fact_items,
    _property_packet_compare_rows,
    _property_packet_compare_table,
    _property_packet_decision_rows,
    _property_packet_everyday_fit_rows,
    _property_packet_future_research_rows,
    _property_packet_missing_rows,
    _property_packet_official_evidence_rows,
    _property_packet_official_posture_rows,
    _property_packet_provenance_rows,
    _property_packet_risk_fit_rows,
    _property_packet_score_rows,
    _property_research_gallery_items,
    _property_research_money_display,
    _property_review_detail_line,
    _property_rooms_display,
    _property_shortlist_candidates_from_context,
    _property_tour_media_payload,
    _property_tour_detail_line,
)
from app.api.routes.admin_view_models import build_admin_section_payload as _build_admin_section_payload
from app.api.routes.workspace_view_models import workspace_section_payload as _workspace_section_payload
from app.container import AppContainer
from app.product.commercial import workspace_plan_for_mode
from app.product.property_surface_state import (
    build_property_billing_truth_snapshot,
    build_property_research_packet_snapshot,
    build_property_run_health_snapshot,
    normalize_property_search_run_snapshot,
)
from app.product.projections.common import compact_text
from app.product.service import build_product_service
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import complete_google_oauth_callback
from app.services.property_billing import payfunnels_configured, property_commercial_snapshot
from app.services.property_market_catalog import (
    country_label as property_country_label,
    country_options as property_country_options,
    default_language_for_country,
    default_platforms_for_country_listing_mode,
    default_platforms_for_country,
    evidence_source_options as property_evidence_source_options,
    investment_strategy_label as property_investment_strategy_label,
    investment_strategy_options as property_investment_strategy_options,
    language_label as property_language_label,
    language_options as property_language_options,
    listing_mode_label as property_listing_mode_label,
    listing_mode_options as property_listing_mode_options,
    investment_research_mode_label as property_investment_research_mode_label,
    investment_research_mode_options as property_investment_research_mode_options,
    normalize_country_code,
    normalize_property_search_preferences,
    property_type_label as property_type_label_for_value,
    property_type_options as property_type_options_catalog,
    provider_options as property_provider_options,
    search_goal_label as property_search_goal_label,
    search_goal_options as property_search_goal_options,
    supported_currency_codes,
)
from app.services.public_branding import request_brand
from app.services.public_clickrank import (
    clickrank_head_snippet as _clickrank_head_snippet,
    request_hostname as _request_hostname,
    request_path as _request_path,
)
from app.services.public_heyy_live_chat import heyy_live_chat_head_snippet as _heyy_live_chat_head_snippet
from app.services.public_rybbit import rybbit_head_snippet as _rybbit_head_snippet
from app.services.registration_email import email_delivery_enabled, property_notification_preview
from app.services.fliplink import build_fliplink_packet_service

router = APIRouter(tags=["landing"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


def _facebook_sign_in_enabled() -> bool:
    enabled_flag = str(os.environ.get("PROPERTYQUARRY_ENABLE_FACEBOOK_SIGN_IN") or "").strip().lower()
    if enabled_flag in {"0", "false", "no", "off", "disabled"}:
        return False
    configured = all(
        str(os.environ.get(key) or "").strip()
        for key in (
            "EA_FACEBOOK_OAUTH_APP_ID",
            "EA_FACEBOOK_OAUTH_APP_SECRET",
            "EA_FACEBOOK_OAUTH_REDIRECT_URI",
        )
    ) and bool(
        str(
            os.environ.get("EA_FACEBOOK_OAUTH_STATE_SECRET")
            or os.environ.get("EA_GOOGLE_OAUTH_STATE_SECRET")
            or os.environ.get("EA_PROVIDER_SECRET_KEY")
            or os.environ.get("EA_SIGNING_SECRET")
            or ""
        ).strip()
    )
    if enabled_flag:
        return enabled_flag in {"1", "true", "yes", "on", "enabled"} and configured
    return configured


@router.get("/manifest.webmanifest", response_class=JSONResponse, include_in_schema=False)
def propertyquarry_web_manifest() -> JSONResponse:
    return JSONResponse(
        {
            "name": "PropertyQuarry",
            "short_name": "PropertyQuarry",
            "description": "A focused property search and decision workspace.",
            "id": "/app/search",
            "start_url": "/app/search",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f0e8",
            "theme_color": "#17211c",
            "orientation": "portrait-primary",
            "categories": ["productivity", "lifestyle"],
            "launch_handler": {"client_mode": "navigate-existing"},
            "icons": [
                {
                    "src": "/pwa-icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
            "shortcuts": [
                {
                    "name": "Search",
                    "short_name": "Search",
                    "description": "Open the property search brief.",
                    "url": "/app/search",
                    "icons": [{"src": "/pwa-icon.svg", "sizes": "any", "type": "image/svg+xml"}],
                },
                {
                    "name": "Results",
                    "short_name": "Results",
                    "description": "Open current ranked homes.",
                    "url": "/app/properties",
                    "icons": [{"src": "/pwa-icon.svg", "sizes": "any", "type": "image/svg+xml"}],
                },
                {
                    "name": "Saved Searches",
                    "short_name": "Saved",
                    "description": "Open saved search automation.",
                    "url": "/app/agents",
                    "icons": [{"src": "/pwa-icon.svg", "sizes": "any", "type": "image/svg+xml"}],
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/pwa-icon.svg", response_class=Response, include_in_schema=False)
def propertyquarry_pwa_icon() -> Response:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="PropertyQuarry"><rect width="512" height="512" rx="96" fill="#17211c"/><path d="M144 336V188l112-64 112 64v148h-74v-92h-76v92z" fill="#f8faf7"/><path d="M171 354h170" stroke="#bd8b2f" stroke-width="24" stroke-linecap="round"/></svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/service-worker.js", response_class=PlainTextResponse, include_in_schema=False)
def propertyquarry_service_worker() -> PlainTextResponse:
    return PlainTextResponse(
        """self.addEventListener('install', () => {
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', () => {
  return;
});
""",
        media_type="text/javascript",
        headers={"Cache-Control": "no-store"},
    )


@lru_cache(maxsize=1)
def _property_country_catalog_snapshot_json() -> str:
    country_rows = [dict(row) for row in property_country_options()]
    country_codes = [
        str(row.get("value") or "").strip()
        for row in country_rows
        if str(row.get("value") or "").strip()
    ]
    payload = {
        "platform_catalog_by_country": {
            country_code: property_provider_options(country_code=country_code)
            for country_code in country_codes
        },
        "platform_defaults_by_country_mode": {
            country_code: {
                mode: list(default_platforms_for_country_listing_mode(country_code, mode))
                for mode in ("rent", "buy")
            }
            for country_code in country_codes
        },
        "evidence_source_catalog_by_country": {
            country_code: property_evidence_source_options(country_code=country_code)
            for country_code in country_codes
        },
        "default_language_by_country": {
            country_code: default_language_for_country(country_code)
            for country_code in country_codes
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _property_country_catalog_snapshot() -> dict[str, object]:
    return dict(json.loads(_property_country_catalog_snapshot_json()))


@lru_cache(maxsize=1)
def prewarm_property_search_surface_cache() -> bool:
    template_names = (
        "propertyquarry_home.html",
        "app/property_decision_workbench.html",
        "app/_property_results_list.html",
        "app/_property_running_panel.html",
        "app/_property_search_agents_panel.html",
        "app/_property_selected_review_panel.html",
    )
    for template_name in template_names:
        with contextlib.suppress(Exception):
            templates.env.get_template(template_name)

    _property_country_catalog_snapshot_json()
    country_rows = [dict(row) for row in property_country_options()]
    country_codes = tuple(
        str(row.get("value") or "").strip()
        for row in country_rows
        if str(row.get("value") or "").strip()
    )
    with contextlib.suppress(Exception):
        from app.api.routes import landing_view_models

        landing_view_models._property_region_catalog_by_country(country_codes)
        landing_view_models._property_market_filter_capabilities_catalog(country_codes)
        landing_view_models._property_location_catalog_by_country_region(country_codes)
    return True


def prewarm_property_search_shell_cache(*, container: AppContainer, principal_id: str = "") -> bool:
    auth_settings = getattr(getattr(container, "settings", None), "auth", None)
    normalized_principal = (
        str(principal_id or "").strip()
        or str(getattr(auth_settings, "default_principal_id", "") or "").strip()
        or "local-user"
    )
    status = container.onboarding.status(principal_id=normalized_principal)
    property_context = _property_console_context(
        container=container,
        principal_id=normalized_principal,
        status=status,
        surface_mode="search",
    )
    property_context["surface_mode"] = "search"
    payload = _property_workspace_payload(
        "search",
        status=status,
        property_state=property_context,
    )
    templates.env.get_template("app/property_decision_workbench.html")
    return bool(payload)


def _faq_structured_data(rows: tuple[dict[str, str], ...]) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": str(row.get("question") or "").strip(),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": str(row.get("answer") or "").strip(),
                },
            }
            for row in rows
            if str(row.get("question") or "").strip() and str(row.get("answer") or "").strip()
        ],
    }


PUBLIC_GUIDE_WIEN = {
    "kicker": "Guide",
    "title": "Wohnung kaufen in Wien: Checkliste fuer Besichtigung, Kosten und Risiken",
    "summary": "A calm PropertyQuarry guide to the checks that matter before you book a viewing, request documents, or move a flat into the real shortlist.",
    "band": (
        {"title": "What to clarify first", "body": "Price, Betriebskosten, floorplan, heating, and the everyday location read should be visible before emotional momentum takes over."},
        {"title": "What usually blocks good decisions", "body": "Missing floorplans, unclear reserve or operating costs, weak light, hidden noise, and no clear next question for the broker."},
    ),
    "sections": (
        {
            "eyebrow": "Before the viewing",
            "title": "The shortest useful checklist",
            "items": (
                "Request the floorplan and check whether the room layout actually fits the household.",
                "Separate cold rent or purchase price from operating costs and reserve exposure.",
                "Look for heating type, energy certificate posture, and anything that could change monthly cost.",
                "Check the wider area for daily needs, transit, schools, and obvious noise sources.",
            ),
        },
        {
            "eyebrow": "Ask next",
            "title": "Questions worth sending before you spend more time",
            "items": (
                "Can you send the current floorplan and the latest Betriebskosten breakdown?",
                "What has changed in the building or reserve posture in the last 12 months?",
                "Which rooms face the street and which face the courtyard?",
                "Are there any missing documents that would normally be shared before a viewing?",
            ),
        },
    ),
    "faqs": (
        {"question": "Why start with floorplan and costs?", "answer": "Because these two checks eliminate many false positives before the viewing consumes time."},
        {"question": "Should I trust the listing description alone?", "answer": "No. Listing copy is useful, but the next step should come from visible facts, not just tone."},
    ),
}

PUBLIC_MARKET_VIENNA = {
    "kicker": "Market",
    "title": "Vienna apartment search: what makes a shortlist usable",
    "summary": "A practical overview of how a Vienna search should move from portal clutter to a ranked list that is actually worth reviewing.",
    "band": (
        {"title": "Too many portals is not the real problem", "body": "The main problem is that good and weak homes are mixed together without a clear reason to open one first."},
        {"title": "The right shortlist is smaller than the crawl", "body": "A useful Vienna shortlist should carry fit reasons, missing facts, and the next question, not just tiles and filters."},
    ),
    "sections": (
        {
            "eyebrow": "How to read the market",
            "title": "What separates signal from noise",
            "items": (
                "Treat district fit, daily reachability, and household needs as first-class inputs, not afterthought filters.",
                "Keep missing floorplans visible instead of letting them silently distort the shortlist.",
                "Rank the strongest homes first and keep weaker near-misses available only as deliberate tradeoffs.",
            ),
        },
        {
            "eyebrow": "What to expect",
            "title": "What a premium search surface should show",
            "items": (
                "The strongest homes first.",
                "The one reason each home survived the cut.",
                "The main blocker that still needs an answer.",
                "The next-best fallback if this one fails.",
            ),
        },
    ),
    "faqs": (
        {"question": "Why does district scope matter so much in Vienna?", "answer": "Because small district differences can change commute, noise, school fit, and price faster than listing text suggests."},
        {"question": "Why not just widen every search?", "answer": "Because a good shortlist should get sharper first. Broader reach only helps when the tradeoff is explicit."},
    ),
}


def _clean_property_candidate_copy(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text == "Provider-ranked fallback candidate kept because strict personal-fit scoring produced no shortlist.":
        return ""
    return text.replace(
        "Provider-ranked fallback candidate kept because strict personal-fit scoring produced no shortlist.",
        "Fallback candidate because no stronger fit cleared the shortlist.",
    ).strip()


def _property_title_price_fallback(title: object) -> str:
    text = " ".join(str(title or "").split()).strip()
    if not text:
        return ""
    currency_pattern = "|".join(re.escape(code) for code in supported_currency_codes())
    for pattern in (
        r"(€\s?[0-9][0-9\.\s]*(?:,[0-9]{1,2})?\s*,-?)",
        rf"((?:{currency_pattern})\s?[0-9][0-9\.,\s]*)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            raw = " ".join(str(match.group(1) or "").split()).strip(" ,")
            return _property_research_money_display(raw) or raw
    return ""


def _property_research_title_display(title: object) -> str:
    text = " ".join(str(title or "").split()).strip()
    if not text:
        return "Research packet"
    text = re.sub(r"\s+-\s+[^\-\|,]+$", "", text).strip()
    trailing_patterns = (
        r",\s*\d+(?:[.,]\d+)?\s*m².*$",
        r",\s*[€$£]\s*[0-9][0-9\.\,\s-]*(?:\([^)]*\))?.*$",
        r",\s*\([^)]*\)\s*$",
    )
    changed = True
    while changed and text:
        changed = False
        for pattern in trailing_patterns:
            updated = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" ,-")
            if updated != text:
                text = updated
                changed = True
    return text or "Research packet"

templates.env.globals["clickrank_head_snippet"] = lambda request=None: Markup(
    _clickrank_head_snippet(_request_hostname(request), _request_path(request))
)
templates.env.globals["rybbit_head_snippet"] = lambda request=None: Markup(_rybbit_head_snippet(request))
templates.env.globals["heyy_live_chat_head_snippet"] = lambda request=None: Markup(_heyy_live_chat_head_snippet(request))


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt() -> PlainTextResponse:
    response = PlainTextResponse(
        "\n".join(
            (
                "User-agent: *",
                "Allow: /",
                "Disallow: /app/",
                "Disallow: /api/",
                "Disallow: /v1/",
                "Disallow: /auth/",
                "Disallow: /admin/",
                "Disallow: /workspace-access/",
                "Sitemap: https://propertyquarry.com/sitemap.xml",
                "",
            )
        )
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.get("/sitemap.xml", include_in_schema=False, response_class=Response)
def sitemap_xml(request: Request) -> Response:
    brand = request_brand(request)
    base_url = str(brand.get("public_base_url") or "https://propertyquarry.com").strip().rstrip("/")
    urls = (
        "/",
        "/pricing",
        "/security",
        "/privacy",
        "/terms",
        "/support",
        "/imprint",
        "/cookies",
        "/subprocessors",
        "/refunds",
        "/disclaimers",
        "/integrations",
        "/docs",
        "/guides/wohnung-kaufen-wien-checkliste",
        "/markets/vienna",
        "/sign-in",
    )
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path in urls:
        if path == "/sign-in":
            continue
        body.append(f"  <url><loc>{html.escape(base_url + path)}</loc></url>")
    body.append("</urlset>")
    response = Response("\n".join(body), media_type="application/xml")
    response.headers["X-Robots-Tag"] = "index, follow, max-image-preview:large"
    return response



def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()



def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"



def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))



def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()



def _form_values(form_data: dict[str, list[str]], key: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in (form_data.get(key) or []) if str(value).strip())


def _property_feedback_reference_candidates(candidate_ref: str, candidate: dict[str, object]) -> tuple[str, ...]:
    refs: list[str] = []
    for value in (
        candidate_ref,
        candidate.get("property_ref"),
        candidate.get("listing_id"),
        candidate.get("property_url"),
        candidate.get("review_url"),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in refs:
            refs.append(normalized)
    return tuple(refs)



def _property_lookup_candidate_across_runs(
    product: Any,
    *,
    principal_id: str,
    candidate_ref: str,
    run_id: str = "",
    max_runs: int = 12,
) -> tuple[dict[str, object] | None, str]:
    normalized_run_id = str(run_id or "").strip()
    normalized_candidate_ref = str(candidate_ref or "").strip()
    if not normalized_candidate_ref:
        return None, ""
    run_ids: list[str] = []
    if normalized_run_id:
        run_ids.append(normalized_run_id)
    try:
        for row in list(product.list_property_search_runs(principal_id=principal_id, limit=max_runs) or []):
            if not isinstance(row, dict):
                continue
            recent_run_id = str(row.get("run_id") or "").strip()
            if recent_run_id and recent_run_id not in run_ids:
                run_ids.append(recent_run_id)
    except Exception:
        pass
    for row_run_id in run_ids[: max(int(max_runs or 0), 1)]:
        try:
            run_payload = dict(
                product.get_property_search_run_status(
                    principal_id=principal_id,
                    run_id=row_run_id,
                )
                or {}
            )
        except Exception:
            continue
        if not isinstance(run_payload, dict):
            continue
        candidate = _property_lookup_candidate(
            property_context={"run": run_payload},
            candidate_ref=normalized_candidate_ref,
        )
        if candidate:
            return candidate, row_run_id
    return None, ""


def _property_compact_preference_overlay(payload: dict[str, object]) -> dict[str, object]:
    preferences = dict(payload or {})
    for heavy_key in (
        "raw_preferences",
        "saved_shortlist_candidates",
        "search_agents",
        "property_commercial",
        "preference_bundle",
    ):
        preferences.pop(heavy_key, None)
    return preferences


def _property_lookup_candidate_in_saved_shortlist(
    product: Any,
    *,
    principal_id: str,
    candidate_ref: str,
) -> dict[str, object] | None:
    normalized_candidate_ref = str(candidate_ref or "").strip()
    if not normalized_candidate_ref:
        return None
    try:
        candidates = list(product.list_property_saved_shortlist_candidates(principal_id=principal_id) or [])
    except Exception:
        candidates = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        candidate = dict(row)
        if _property_candidate_ref(candidate) == normalized_candidate_ref:
            return candidate
    return None


def _property_missing_packet_target(*, run_id: str = "", candidate_ref: str = "") -> str:
    normalized_run_id = str(run_id or "").strip()
    normalized_candidate_ref = str(candidate_ref or "").strip()
    query: dict[str, str] = {"packet_missing": "1"}
    if normalized_run_id:
        query["run_id"] = normalized_run_id
    if normalized_candidate_ref:
        query["missing_candidate_ref"] = normalized_candidate_ref
    return f"/app/shortlist?{urllib.parse.urlencode(query)}#results-list"


def _property_missing_packet_response(
    request: Request,
    *,
    container: AppContainer | None = None,
    principal_id: str = "",
    run_id: str = "",
    candidate_ref: str = "",
) -> JSONResponse | RedirectResponse:
    normalized_run_id = str(run_id or "").strip()
    normalized_candidate_ref = str(candidate_ref or "").strip()
    target = _property_missing_packet_target(
        run_id=normalized_run_id,
        candidate_ref=normalized_candidate_ref,
    )
    repair_task_ref = _property_queue_missing_research_packet_repair(
        container=container,
        principal_id=principal_id,
        run_id=normalized_run_id,
        candidate_ref=normalized_candidate_ref,
        recovery_url=target,
    )
    accept_header = str(request.headers.get("accept") or "").lower()
    requested_with = str(request.headers.get("x-requested-with") or "").lower()
    if "application/json" in accept_header or requested_with == "xmlhttprequest":
        return JSONResponse(
            {
                "status": "recovery_available",
                "code": "property_research_packet_recovery",
                "message": "That property page is not available in this packet. The shortlist is still available.",
                "run_id": normalized_run_id,
                "candidate_ref": normalized_candidate_ref,
                "redirect_url": target,
                "repair_status": "needs_rebuild",
                "queue_item_ref": repair_task_ref,
                "action_label": "Open shortlist",
            },
            status_code=202,
        )
    return RedirectResponse(url=target, status_code=307)


def _property_queue_missing_research_packet_repair(
    *,
    container: AppContainer | None,
    principal_id: str,
    run_id: str,
    candidate_ref: str,
    recovery_url: str,
) -> str:
    normalized_principal = str(principal_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    normalized_candidate_ref = str(candidate_ref or "").strip()
    if container is None or not normalized_principal or not normalized_candidate_ref:
        return ""
    try:
        repair = build_product_service(container)._open_property_provider_repair_task(
            principal_id=normalized_principal,
            property_url=(
                "propertyquarry://research-packet/"
                f"{urllib.parse.quote(normalized_run_id or 'unknown', safe='')}/"
                f"{urllib.parse.quote(normalized_candidate_ref, safe='')}"
            ),
            title=f"Missing property research packet {normalized_candidate_ref}",
            source_url=str(recovery_url or "").strip(),
            source_label="Property research packet",
            source_platform="propertyquarry",
            source_family="research_packet",
            filter_key="research_packet_missing",
            diagnostics={
                "failure_class": "research_packet_missing",
                "run_id": normalized_run_id,
                "candidate_ref": normalized_candidate_ref,
                "recovery_url": str(recovery_url or "").strip(),
                "reason": "candidate page was requested but could not be reconstructed from active run, cross-run lookup, or saved shortlist",
            },
            source_ref=f"property-research-packet:{normalized_run_id}:{normalized_candidate_ref}",
            run_id=normalized_run_id,
        )
        return str(repair.get("queue_item_ref") or repair.get("human_task_id") or "").strip()
    except Exception:
        return ""


def _principal_for_page(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
    request: Request | None = None,
) -> str:
    if access_identity is not None:
        return access_identity.principal_id
    if request is not None:
        workspace_session = _workspace_session_payload(request, container)
        if workspace_session is not None:
            return str(workspace_session.get("principal_id") or "").strip()
        expected = _expected_api_token(container)
        if expected and hmac.compare_digest(_extract_token(request), expected):
            return _resolved_principal_id(
                request,
                container=container,
                authenticated=True,
                access_identity=None,
            )
        if str(request.headers.get("x-ea-principal-id") or "").strip():
            return _resolved_principal_id(
                request,
                container=container,
                authenticated=False,
                access_identity=None,
            )
    return ""



def _anonymous_onboarding_status() -> dict[str, object]:
    return {
        "principal_id": "",
        "status": "anonymous",
        "workspace": {"name": "PropertyQuarry"},
        "selected_channels": [],
        "privacy": {},
        "assistant_modes": [],
        "featured_domains": [],
        "storage_posture": {},
        "channels": {},
        "brief_preview": {},
        "next_step": "Sign in to start a workspace or view the current one.",
        "onboarding_id": "",
    }



def _load_status(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
    request: Request | None = None,
) -> tuple[str, dict[str, object]]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity, request=request)
    if not principal_id:
        return "", _anonymous_onboarding_status()
    return principal_id, container.onboarding.status(principal_id=principal_id)


def _landing_public_home_requested(request: Request) -> bool:
    for key in ("home", "show_home", "public_home"):
        value = str(request.query_params.get(key) or "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
    return False


def _landing_authenticated_principal(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
    request: Request,
) -> str:
    if access_identity is not None:
        return str(access_identity.principal_id or "").strip()
    workspace_session = _workspace_session_payload(request, container)
    if workspace_session is not None:
        return str(workspace_session.get("principal_id") or "").strip()
    expected = _expected_api_token(container)
    if expected and hmac.compare_digest(_extract_token(request), expected):
        return _resolved_principal_id(
            request,
            container=container,
            authenticated=True,
            access_identity=None,
        )
    return ""


def _public_app_base_url(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-host") or "").strip().lower().rstrip(".")
    request_host = str(request.url.hostname or "").strip().lower().rstrip(".")
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip() or request.url.scheme
    effective_host = forwarded or request_host
    if effective_host in {"propertyquarry.com", "www.propertyquarry.com"}:
        host = forwarded or request_host
        return f"https://{host}"
    explicit = str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if forwarded:
        forwarded_proto = _first_forwarded_https_or_first_token(forwarded_proto)
    if forwarded:
        return f"{forwarded_proto}://{forwarded}"
    return str(request.base_url).rstrip("/")



def _normalize_return_to_for_logout(*, return_to: str, request: Request) -> str:
    parsed_return_to = urllib.parse.urlparse(return_to)
    if parsed_return_to.scheme and parsed_return_to.netloc:
        return return_to
    if not return_to.startswith("/"):
        return _public_app_base_url(request)
    return f"{_public_app_base_url(request).rstrip('/')}{return_to}"


def _cloudflare_access_logout_url(
    request: Request,
    *,
    team_domain: str,
    return_to: str,
) -> str:
    normalized_team_domain = str(team_domain or "").strip().rstrip("/").lower()
    if "://" in normalized_team_domain:
        parsed_domain = urllib.parse.urlparse(normalized_team_domain)
        normalized_team_domain = str(parsed_domain.netloc or "").strip().lower().rstrip("/")
    if not normalized_team_domain:
        return return_to
    public_return_to = _normalize_return_to_for_logout(return_to=return_to, request=request)
    params = urllib.parse.urlencode({"return_to": public_return_to})
    return f"https://{normalized_team_domain}/cdn-cgi/access/logout?{params}"


def _normalize_browser_return_to(raw: str | None, *, default: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return default
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//") or not value.startswith("/"):
        return default
    return value


def _first_forwarded_https_or_first_token(raw: str) -> str:
    tokens = [token.strip().lower() for token in str(raw or "").split(",") if token.strip()]
    if "https" in tokens:
        return "https"
    if "wss" in tokens:
        return "wss"
    return tokens[0] if tokens else ""


def _browser_request_uses_secure_scheme(request: Request) -> bool:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    normalized = _first_forwarded_https_or_first_token(forwarded_proto)
    if normalized:
        return normalized in {"https", "wss"}
    return str(request.url.scheme or "").strip().lower() == "https"


def _workspace_session_cookie_kwargs(request: Request, *, expires_at: str = "") -> dict[str, object]:
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or str(request.url.hostname or "") or "").strip()
    host = host.split(",", 1)[0].split(":", 1)[0].strip().lower().rstrip(".")
    domain = None
    if host.endswith(".propertyquarry.com") or host == "propertyquarry.com" or host == "www.propertyquarry.com":
        domain = ".propertyquarry.com"

    kwargs: dict[str, object] = {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": _browser_request_uses_secure_scheme(request),
    }
    if domain is not None:
        kwargs["domain"] = domain
    normalized_expires_at = str(expires_at or "").strip()
    if not normalized_expires_at:
        return kwargs
    try:
        expires_dt = datetime.fromisoformat(normalized_expires_at)
    except ValueError:
        return kwargs
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    max_age = max(int((expires_dt - datetime.now(timezone.utc)).total_seconds()), 0)
    kwargs["expires"] = expires_dt
    kwargs["max_age"] = max_age
    return kwargs


def _clear_workspace_session_cookie(response: RedirectResponse, request: Request) -> None:
    base_kwargs = {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
    }
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or str(request.url.hostname or "") or "").strip()
    host = host.split(",", 1)[0].split(":", 1)[0].strip().lower().rstrip(".")
    clear_domains = [None]
    if host.endswith(".propertyquarry.com") or host == "propertyquarry.com" or host == "www.propertyquarry.com":
        clear_domains.append(".propertyquarry.com")

    for secure in (True, False):
        for clear_domain in clear_domains:
            for path in ("/", "/app"):
                response.delete_cookie(
                    "ea_workspace_session",
                    secure=secure,
                    domain=clear_domain,
                    path=path,
                    httponly=base_kwargs["httponly"],
                    samesite=base_kwargs["samesite"],
                )


def _signed_out_marker_cookie_kwargs(request: Request) -> dict[str, object]:
    kwargs = _workspace_session_cookie_kwargs(request)
    kwargs["httponly"] = True
    kwargs["max_age"] = 60 * 60 * 24 * 7
    return kwargs


def _clear_signed_out_marker_cookie(response: RedirectResponse, request: Request) -> None:
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or str(request.url.hostname or "") or "").strip()
    host = host.split(",", 1)[0].split(":", 1)[0].strip().lower().rstrip(".")
    clear_domains = [None]
    if host.endswith(".propertyquarry.com") or host == "propertyquarry.com" or host == "www.propertyquarry.com":
        clear_domains.append(".propertyquarry.com")
    for secure in (True, False):
        for clear_domain in clear_domains:
            for path in ("/", "/app"):
                response.delete_cookie(
                    "ea_workspace_signed_out",
                    secure=secure,
                    domain=clear_domain,
                    path=path,
                    httponly=True,
                    samesite="lax",
                )


def _shared_browser_fields(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    container: AppContainer,
) -> str:
    token_field = ""
    if access_identity is None and _token_required(container):
        token_field = """
        <label for=\"api_token\">API token</label>
        <input id=\"api_token\" name=\"api_token\" type=\"password\" placeholder=\"required for browser setup on this host\">
        """
    if access_identity is not None:
        return f"""
        <input type=\"hidden\" name=\"principal_id\" value=\"{html.escape(principal_id)}\">
        {token_field}
        """
    if not browser_principal_override_allowed():
        return f"""
        {token_field}
        <p class=\"helper-note\">This browser can only finish setup for the default workspace on this deployment. Switching workspaces from the browser is disabled here.</p>
        """
    return f"""
    <label for=\"principal_id\">Workspace ID (advanced)</label>
    <input id=\"principal_id\" name=\"principal_id\" value=\"{html.escape(principal_id)}\" required>
    {token_field}
    """



def _browser_form_context(
    *,
    form_data: dict[str, list[str]],
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        api_token = _form_value(form_data, "api_token", "")
        if not expected or not hmac.compare_digest(api_token, expected):
            raise HTTPException(status_code=401, detail="auth_required")
    if access_identity is not None:
        requested = _form_value(form_data, "principal_id", access_identity.principal_id)
        if requested and requested != access_identity.principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return access_identity.principal_id
    default_principal = _default_principal_id(container)
    requested = _form_value(form_data, "principal_id", "")
    if browser_principal_override_allowed():
        return requested or default_principal
    if requested and requested != default_principal:
        raise HTTPException(status_code=403, detail="principal_override_not_allowed")
    return default_principal



def _public_context(
    *,
    request: Request,
    current_nav: str,
    page_title: str,
    principal_id: str,
    status: dict[str, object],
    access_identity: CloudflareAccessIdentity | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    query = request.query_params
    explicit_public_home = (
        str(brand.get("key") or "").strip() == "propertyquarry"
        and _landing_public_home_requested(request)
    )
    signing_in_progress = False
    if explicit_public_home:
        signing_in_progress = False
    elif access_identity is not None or principal_id:
        signing_in_progress = True
    elif str(query.get("signing_in") or query.get("signing") or "").strip().lower() in {"1", "true", "yes"}:
        signing_in_progress = True
    elif str(query.get("code") or "").strip() and str(query.get("state") or "").strip():
        signing_in_progress = True
    public_base_url = str(brand.get("public_base_url") or "").strip().rstrip("/")
    request_path = str(getattr(request.url, "path", "") or "").strip() or "/"
    canonical_path = str((extra or {}).get("canonical_path") or request_path).strip() or "/"
    if not canonical_path.startswith("/"):
        canonical_path = f"/{canonical_path.lstrip('/')}"
    canonical_url = str((extra or {}).get("canonical_url") or "").strip() or f"{public_base_url}{canonical_path}"
    meta_description = str((extra or {}).get("meta_description") or "").strip()
    if not meta_description:
        meta_description = (
            "PropertyQuarry helps renters, buyers, and investors define a brief, compare the strongest homes, "
            "open the dossier, and decide with evidence."
        )
    og_title = str((extra or {}).get("og_title") or "").strip() or page_title
    og_description = str((extra or {}).get("og_description") or "").strip() or meta_description
    og_type = str((extra or {}).get("og_type") or "").strip() or "website"
    robots_directive = str((extra or {}).get("robots_directive") or "").strip() or "index, follow, max-image-preview:large"
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    preview = dict(status.get("brief_preview") or {})
    selected_channels = [str(row) for row in (status.get("selected_channels") or []) if str(row).strip()]
    context: dict[str, object] = {
        "page_title": page_title,
        "meta_description": meta_description,
        "canonical_url": canonical_url,
        "og_title": og_title,
        "og_description": og_description,
        "og_type": og_type,
        "robots_directive": robots_directive,
        "structured_data_json": (extra or {}).get("structured_data_json"),
        "brand": brand,
        "public_nav": PUBLIC_NAV,
        "current_nav": current_nav,
        "access_identity": access_identity,
        "principal_id": principal_id,
        "public_signed_in": bool(access_identity is not None or principal_id),
        "status": status,
        "workspace": workspace,
        "privacy": dict(status.get("privacy") or {}),
        "channels": channels,
        "channel_cards": _channel_cards(channels),
        "selected_channels_label": ", ".join(selected_channels) if selected_channels else "Google sign-in recommended",
        "signing_in_progress": signing_in_progress,
        "workspace_mode_label": _humanize(str(workspace.get("mode") or "personal")),
        "brief_headline": str(preview.get("headline") or "Turn your channels into a prioritized day."),
        "first_brief_items": _list_rows(
            preview.get("first_brief_preview") or preview.get("first_brief"),
            (
                "Connect Google sign-in if you want easier return access from the same account.",
                "Keep one reviewable property workflow before widening the channel footprint.",
                "Make approvals and memory rules explicit before automating actions.",
            ),
        ),
        "suggested_actions": _list_rows(
            preview.get("suggested_actions"),
            (
                "Turn the workspace posture into a useful shortlist and research loop.",
                "Add more channels only after the first loop already feels useful.",
            ),
        ),
        "trust_notes": _list_rows(
            preview.get("trust_notes"),
            (
                "Each channel says clearly what the assistant can actually do today.",
                "Approvals and workspace memory stay visible product features, not hidden implementation details.",
            ),
        ),
        "top_contacts": _list_rows(preview.get("top_contacts"), ("No contact memory yet.",)),
        "top_themes": _list_rows(preview.get("top_themes"), ("No themes yet.",)),
    }
    if extra:
        context.update(extra)
    return context


def _workspace_plan(container: AppContainer, *, principal_id: str):
    status = container.onboarding.status(principal_id=principal_id)
    workspace = dict(status.get("workspace") or {})
    return workspace_plan_for_mode(str(workspace.get("mode") or "personal"))


def _account_nav_context(*, request: Request, context: RequestContext) -> dict[str, object]:
    if not context.principal_id:
        return {}
    if (
        str(request.cookies.get("ea_workspace_signed_out") or "").strip() == "1"
        and context.auth_source not in {"workspace_access_session", "cloudflare_access", "api_token"}
    ):
        return {}

    brand = request_brand(request)
    account_label = str(context.access_email or "").strip().lower()
    if not account_label:
        account_label = str(context.operator_id or "").strip() or "Account"
    menu_label = str(context.access_email or "").strip()
    if not menu_label:
        menu_label = str(context.operator_id or "").strip() or "Account"
    raw_sign_out_return_to = str(brand.get("public_base_url") or "/").strip()
    parsed_sign_out_return_to = urllib.parse.urlparse(raw_sign_out_return_to)
    sign_out_return_to = "/"
    if parsed_sign_out_return_to.path:
        sign_out_return_to = parsed_sign_out_return_to.path.strip() or "/"
    elif raw_sign_out_return_to.startswith("/"):
        sign_out_return_to = raw_sign_out_return_to
    elif not raw_sign_out_return_to:
        sign_out_return_to = "/"
    elif raw_sign_out_return_to != "/":
        sign_out_return_to = "/"
    return {
        "label": account_label,
        "menu_label": menu_label,
        "profile_href": "/app/account#profile",
        "billing_href": "/app/billing",
        "settings_href": "/app/account#settings",
        "sign_out_action": "/app/actions/sign-out",
        "sign_out_return_to": sign_out_return_to,
    }



def _console_shell_context(
    *,
    request: Request,
    page_title: str,
    current_nav: str,
    context: RequestContext,
    console_title: str,
    console_summary: str,
    nav_groups: tuple[dict[str, object], ...],
    workspace_label: str,
    cards: list[dict[str, object]],
    stats: list[dict[str, str]],
    console_form: dict[str, object] | None = None,
) -> dict[str, object]:
    brand = request_brand(request)
    analytics_principal_id = ""
    if str(context.principal_id or "").strip():
        analytics_principal_id = "principal_" + hashlib.sha256(
            str(context.principal_id or "").strip().encode("utf-8")
        ).hexdigest()[:24]
    return {
        "page_title": page_title,
        "brand": brand,
        "current_nav": current_nav,
        "nav_groups": nav_groups,
        "console_title": console_title,
        "console_summary": console_summary,
        "workspace_label": workspace_label,
        "cards": cards,
        "stats": stats,
        "console_form": console_form or {},
        "principal_id": context.principal_id,
        "analytics_principal_id": analytics_principal_id,
        "access_email": context.access_email,
        "operator_id": context.operator_id,
        "account_nav": _account_nav_context(request=request, context=context),
    }



def _render_public_template(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    context.setdefault("request", request)
    context.setdefault("brand", request_brand(request))
    response = templates.TemplateResponse(request, template_name, context)
    response.headers["X-Robots-Tag"] = str(context.get("robots_directive") or "index, follow, max-image-preview:large")
    return response


def _render_secure_link_page(
    request: Request,
    *,
    page_title: str,
    current_nav: str,
    link_kicker: str,
    link_title: str,
    link_summary: str,
    link_detail_title: str,
    link_status_label: str,
    link_rows: list[dict[str, str]],
    primary_action_href: str,
    primary_action_label: str,
    primary_action_method: str = "get",
    primary_action_fields: dict[str, str] | None = None,
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    response = _render_public_template(
        request,
        "workspace_link.html",
        **_public_context(
            request=request,
            current_nav=current_nav,
            page_title=page_title,
            principal_id="",
            status=_anonymous_onboarding_status(),
            access_identity=None,
            extra={
                "link_kicker": link_kicker,
                "link_title": link_title,
                "link_summary": link_summary,
                "link_detail_title": link_detail_title,
                "link_status_label": link_status_label,
                "link_rows": link_rows,
                "primary_action_href": primary_action_href,
                "primary_action_label": primary_action_label,
                "primary_action_method": str(primary_action_method or "get").strip().lower() or "get",
                "primary_action_fields": dict(primary_action_fields or {}),
                "secondary_action_href": secondary_action_href,
                "secondary_action_label": secondary_action_label,
                "robots_directive": "noindex, nofollow, noarchive, nosnippet",
            },
        ),
    )
    response.status_code = status_code
    return response


def _default_operator_id_for_browser(container: AppContainer, *, principal_id: str) -> str:
    operators = container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=1)
    if not operators:
        return ""
    return str(operators[0].operator_id or "").strip()


def _app_live_feed(container: AppContainer, *, principal_id: str) -> dict[str, object]:
    approvals = container.orchestrator.list_pending_approvals_for_principal(
        principal_id=principal_id,
        limit=6,
    )
    human_tasks = container.orchestrator.list_human_tasks(
        principal_id=principal_id,
        status="pending",
        limit=6,
    )
    pending_delivery = container.channel_runtime.list_pending_delivery(
        limit=6,
        principal_id=principal_id,
    )
    return {
        "approvals": approvals,
        "human_tasks": human_tasks,
        "pending_delivery": pending_delivery,
    }


def _property_search_platform_catalog() -> tuple[dict[str, str], ...]:
    return tuple(property_provider_options(country_code="AT"))


def _property_console_context(
    *,
    container: AppContainer,
    principal_id: str,
    status: dict[str, object],
    run_id: str = "",
    selected_agent_id: str = "",
    surface_mode: str = "properties",
) -> dict[str, object]:
    product = build_product_service(container)
    surface_scope = PropertySurfaceScope.for_section(surface_mode)
    wants_run_state = surface_scope.wants_run_state
    wants_recent_runs = surface_scope.wants_recent_runs
    wants_recent_matches = surface_scope.wants_recent_matches
    wants_preference_profile = surface_scope.wants_preference_profile
    wants_learning_summary = surface_scope.wants_learning_summary
    raw_property_preferences = dict(status.get("property_search_preferences") or {})
    preferences = normalize_property_search_preferences(dict(raw_property_preferences.get("raw_preferences") or raw_property_preferences))
    selected_country = normalize_country_code(preferences.get("country_code"))
    commercial = property_commercial_snapshot(preferences)
    billing_order_endpoints_by_plan: dict[str, str] = {}
    billing_provider_labels_by_plan: dict[str, str] = {}
    billing_enabled_plans: list[str] = []
    for paid_plan in ("plus", "agent"):
        if payfunnels_configured(plan_key=paid_plan):
            billing_enabled_plans.append(paid_plan)
            billing_order_endpoints_by_plan[paid_plan] = "/app/api/signals/property/billing/payfunnels/order"
            billing_provider_labels_by_plan[paid_plan] = "PayFunnels"
    default_billing_plan = billing_enabled_plans[0] if billing_enabled_plans else ""
    selected_platforms = {
        str(value or "").strip().lower()
        for value in (preferences.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    if not selected_platforms:
        selected_platforms = set(
            default_platforms_for_country_listing_mode(
                selected_country,
                preferences.get("listing_mode"),
                property_type=preferences.get("property_type"),
            )
        )
    country_provider_options = [dict(option) for option in property_provider_options(country_code=selected_country)]
    run_payload: dict[str, object] = {}
    normalized_run_id = str(run_id or "").strip()
    has_persisted_brief = bool(
        str(preferences.get("country_code") or raw_property_preferences.get("country_code") or "").strip()
        or str(preferences.get("region_code") or raw_property_preferences.get("region_code") or "").strip()
        or str(preferences.get("location_query") or raw_property_preferences.get("location_query") or "").strip()
        or str(preferences.get("search_goal") or raw_property_preferences.get("search_goal") or "").strip()
    )
    recent_search_runs: list[dict[str, object]] = []
    lightweight_active_run: dict[str, object] = {}
    active_run: dict[str, object] | None = None
    should_load_recent_runs = (
        wants_recent_runs
        and not (normalized_run_id and surface_scope.section in {"properties", "shortlist"})
        and surface_scope.section != "search"
        and (
            surface_scope.section != "properties"
            or has_persisted_brief
        )
    )
    if should_load_recent_runs:
        try:
            recent_search_runs = [
                normalize_property_search_run_snapshot(dict(row))
                for row in product.list_property_search_runs(
                    principal_id=principal_id,
                    limit=8,
                    hydrate=surface_scope.section not in {"properties", "shortlist"},
                )
                if isinstance(row, dict)
            ]
        except Exception:
            recent_search_runs = []
    if wants_run_state and not normalized_run_id:
        terminal_statuses = {"processed", "completed", "completed_partial", "failed", "noop", "cancelled", "not started"}
        active_run = next(
            (
                row
                for row in recent_search_runs
                if isinstance(row, dict)
                and str(row.get("run_id") or "").strip()
                and str(
                    row.get("status")
                    or (dict(row.get("summary") or {}) if isinstance(row.get("summary"), dict) else {}).get("status")
                    or ""
                ).strip().lower()
                not in terminal_statuses
            ),
            None,
        )
        if active_run is None and surface_scope.section == "shortlist":
            active_run = next(
                (
                    row
                    for row in recent_search_runs
                    if isinstance(row, dict)
                    and str(row.get("run_id") or "").strip()
                    and _property_run_payload_has_shortlist_results(row)
                ),
                None,
            )
        if active_run is None and surface_scope.section == "properties":
            with contextlib.suppress(Exception):
                active_run = dict(product.find_active_property_search_run(principal_id=principal_id, limit=8) or {})
        if isinstance(active_run, dict):
            normalized_run_id = str(active_run.get("run_id") or "").strip()
    if wants_run_state and normalized_run_id:
        active_summary_source = run_payload if run_payload else (active_run if isinstance(active_run, dict) else {})
        active_summary = dict(active_summary_source.get("summary") or {}) if isinstance(active_summary_source.get("summary"), dict) else {}
        should_hydrate_run_status = True
        if surface_scope.section == "search" and not active_summary.get("ranked_candidates"):
            should_hydrate_run_status = (
                not active_summary.get("sources")
                and not active_summary.get("sources_total")
                and not active_summary.get("reviewed_listing_total")
                and not active_summary.get("listing_total")
            )
        if surface_scope.section == "shortlist" and active_summary.get("ranked_candidates"):
            should_hydrate_run_status = False
        if should_hydrate_run_status:
            try:
                lightweight_run_status = surface_scope.section == "properties"
                run_payload = dict(
                    product.get_property_search_run_status(
                        principal_id=principal_id,
                        run_id=normalized_run_id,
                        lightweight=lightweight_run_status,
                    )
                    or {}
                )
            except TypeError:
                try:
                    run_payload = dict(
                        product.get_property_search_run_status(
                            principal_id=principal_id,
                            run_id=normalized_run_id,
                        )
                        or {}
                    )
                except Exception:
                    run_payload = active_run if isinstance(active_run, dict) else {}
            except Exception:
                run_payload = active_run if isinstance(active_run, dict) else {}
        else:
            run_payload = dict(active_run or run_payload or {})
    if run_payload:
        run_preferences_payload = (
            dict(run_payload.get("property_search_preferences") or run_payload.get("preferences") or {})
            if isinstance(run_payload.get("property_search_preferences") or run_payload.get("preferences"), dict)
            else {}
        )
        if run_preferences_payload:
            preferences = normalize_property_search_preferences(
                {**preferences, **_property_compact_preference_overlay(run_preferences_payload)}
            )
            selected_country = normalize_country_code(preferences.get("country_code"))
            commercial = property_commercial_snapshot(preferences)
            selected_platforms = {
                str(value or "").strip().lower()
                for value in (preferences.get("selected_platforms") or [])
                if str(value or "").strip()
            }
            if not selected_platforms:
                selected_platforms = set(
                    default_platforms_for_country_listing_mode(
                        selected_country,
                        preferences.get("listing_mode"),
                        property_type=preferences.get("property_type"),
                    )
                )
            country_provider_options = [dict(option) for option in property_provider_options(country_code=selected_country)]
    run_status_value = str(run_payload.get("status") or "").strip().lower()
    enrich_run_candidates_with_feedback = (
        wants_run_state
        and surface_scope.section == "shortlist"
        and run_status_value not in {"processed", "completed", "completed_partial"}
    )
    if run_payload and enrich_run_candidates_with_feedback:
        packet_service = build_fliplink_packet_service(container)
        summary = dict(run_payload.get("summary") or {}) if isinstance(run_payload.get("summary"), dict) else {}
        ranked_candidates = [
            dict(row)
            for row in list(summary.get("ranked_candidates") or [])
            if isinstance(row, dict)
        ]
        if ranked_candidates:
            summary["ranked_candidates"] = [
                _property_enrich_candidate_feedback(
                    packet_service=packet_service,
                    principal_id=principal_id,
                    candidate=candidate,
                )
                for candidate in ranked_candidates[:20]
            ] + ranked_candidates[20:]
        else:
            sources = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
            for source in sources[:8]:
                source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
                candidates = [dict(row) for row in list(source.get("top_candidates") or []) if isinstance(row, dict)]
                enriched_candidates: list[dict[str, object]] = []
                for candidate in candidates[:3]:
                    candidate.setdefault("source_label", source_label)
                    enriched_candidates.append(
                        _property_enrich_candidate_feedback(
                            packet_service=packet_service,
                            principal_id=principal_id,
                            candidate=candidate,
                        )
                    )
                source["top_candidates"] = enriched_candidates
            summary["sources"] = sources
        run_payload["summary"] = summary
    run_health = build_property_run_health_snapshot(
        run_payload,
        run_summary=dict(run_payload.get("summary") or {}) if isinstance(run_payload.get("summary"), dict) else {},
    ) if wants_run_state else {}

    recent_matches: list[dict[str, object]] = []
    learning_summary: dict[str, object] = {}
    preference_bundle: dict[str, object] = {}
    preference_person_id = str(preferences.get("preference_person_id") or "self").strip() or "self"
    if wants_recent_matches:
        try:
            for handoff in product.list_handoffs(principal_id=principal_id, limit=12, status=None):
                task_type = str(getattr(handoff, "task_type", "") or "").strip()
                if task_type not in {"property_tour_followup", "property_alert_review"}:
                    continue
                hosted_url = str(getattr(handoff, "tour_url", "") or "").strip()
                review_url = str(getattr(handoff, "editor_url", "") or "").strip()
                title = str(getattr(handoff, "summary", "") or "").strip() or str(getattr(handoff, "id", "") or "").strip() or "Property match"
                detail_parts = [
                    str(getattr(handoff, "delivery_reason", "") or "").strip(),
                    str(getattr(handoff, "counterparty", "") or "").strip(),
                    str(getattr(handoff, "blocked_reason", "") or "").strip(),
                ]
                detail = " | ".join(part for part in detail_parts if part) or "Recent property follow-up."
                row: dict[str, object] = {
                    "title": title,
                    "detail": detail,
                    "tag": "Hosted tour" if hosted_url else "Review",
                }
                if hosted_url:
                    row["action_href"] = hosted_url
                    row["action_method"] = "get"
                    row["action_label"] = "Open 360"
                if review_url:
                    if hosted_url:
                        row["secondary_action_href"] = review_url
                        row["secondary_action_method"] = "get"
                        row["secondary_action_label"] = "Review brief"
                    else:
                        row["action_href"] = review_url
                        row["action_method"] = "get"
                        row["action_label"] = "Review brief"
                recent_matches.append(row)
                if len(recent_matches) >= 6:
                    break
        except Exception:
            recent_matches = []
    if wants_preference_profile:
        try:
            preference_bundle = dict(
                product.get_preference_profile(
                    principal_id=principal_id,
                    person_id=preference_person_id,
                )
                or {}
            )
        except Exception:
            preference_bundle = {}
    if wants_learning_summary:
        try:
            learning_summary = dict(
                product.property_feedback_learning_summary(
                    principal_id=principal_id,
                    person_id=preference_person_id,
                    domain="willhaben",
                )
                or {}
            )
        except Exception:
            learning_summary = {}

    billing_truth = build_property_billing_truth_snapshot(
        commercial=commercial,
        default_billing_plan=default_billing_plan,
        billing_enabled_plans=billing_enabled_plans,
        billing_order_endpoints_by_plan=billing_order_endpoints_by_plan,
        billing_provider_labels_by_plan=billing_provider_labels_by_plan,
    )
    country_catalog_snapshot = _property_country_catalog_snapshot()

    return {
        "platform_options": country_provider_options,
        "platform_catalog_by_country": dict(country_catalog_snapshot.get("platform_catalog_by_country") or {}),
        "platform_defaults_by_country_mode": dict(country_catalog_snapshot.get("platform_defaults_by_country_mode") or {}),
        "evidence_source_catalog_by_country": dict(country_catalog_snapshot.get("evidence_source_catalog_by_country") or {}),
        "default_language_by_country": dict(country_catalog_snapshot.get("default_language_by_country") or {}),
        "country_options": property_country_options(),
        "language_options": property_language_options(),
        "listing_mode_options": property_listing_mode_options(),
        "search_goal_options": property_search_goal_options(),
        "investment_strategy_options": property_investment_strategy_options(),
        "investment_research_mode_options": property_investment_research_mode_options(),
        "property_type_options": property_type_options_catalog(),
        "country_label": property_country_label(selected_country),
        "language_label": property_language_label(preferences.get("language_code"), country_code=selected_country),
        "listing_mode_label": property_listing_mode_label(preferences.get("listing_mode")),
        "search_goal_label": property_search_goal_label(preferences.get("search_goal")),
        "investment_strategy_label": property_investment_strategy_label(preferences.get("investment_strategy")),
        "investment_research_mode_label": property_investment_research_mode_label(preferences.get("investment_research_mode")),
        "property_type_label": property_type_label_for_value(preferences.get("property_type")),
        "provider_total_for_country": len(country_provider_options),
        "preferences": preferences,
        "raw_preferences": raw_property_preferences,
        "selected_platforms": list(selected_platforms),
        "run": run_payload if wants_run_state else lightweight_active_run,
        "run_health": run_health,
        "recent_search_runs": recent_search_runs,
        "selected_agent_id": str(selected_agent_id or "").strip(),
        "recent_matches": recent_matches,
        "learning_summary": learning_summary,
        "preference_bundle": preference_bundle,
        "preference_person_id": preference_person_id,
        "start_endpoint": "/app/api/property/search-runs",
        "preferences_endpoint": "/v1/onboarding/property-search/preferences",
        "commercial": commercial,
        "billing_checkout_provider": str(billing_truth.get("checkout_provider") or ""),
        "billing_checkout_provider_label": str(billing_truth.get("checkout_provider_label") or ""),
        "billing_checkout_enabled": bool(billing_truth.get("checkout_enabled")),
        "billing_checkout_enabled_plans": list(billing_truth.get("checkout_enabled_plans") or []),
        "billing_order_endpoint": str(billing_truth.get("order_endpoint") or ""),
        "billing_order_endpoints_by_plan": dict(billing_truth.get("order_endpoints_by_plan") or {}),
        "billing_provider_labels_by_plan": dict(billing_truth.get("provider_labels_by_plan") or {}),
        "billing_truth": billing_truth,
    }


def _property_run_payload_has_shortlist_results(run_payload: dict[str, object]) -> bool:
    if not isinstance(run_payload, dict) or not run_payload:
        return False
    summary = dict(run_payload.get("summary") or {}) if isinstance(run_payload.get("summary"), dict) else {}
    for key in ("ranked_candidates", "results", "top_candidates"):
        candidates = run_payload.get(key)
        if isinstance(candidates, list) and candidates:
            return True
        summary_candidates = summary.get(key)
        if isinstance(summary_candidates, list) and summary_candidates:
            return True
    sources = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    if any(list(source.get("top_candidates") or []) for source in sources):
        return True
    for key in ("ranked_total", "ranked_candidate_total", "results_total", "survivor_total"):
        raw_value = run_payload.get(key, summary.get(key))
        try:
            if int(raw_value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _property_enrich_candidate_feedback(
    *,
    packet_service: Any,
    principal_id: str,
    candidate: dict[str, object],
) -> dict[str, object]:
    candidate_row = dict(candidate)
    feedback_summary: dict[str, object] = {}
    feedback_rows: list[dict[str, object]] = []
    for feedback_ref in _property_feedback_reference_candidates(
        _property_candidate_ref(candidate_row),
        candidate_row,
    ):
        try:
            summary_candidate = dict(packet_service.feedback_summary(principal_id=principal_id, property_ref=feedback_ref))
        except Exception:
            summary_candidate = {}
        try:
            rows_candidate = list(packet_service.list_structured_feedback(principal_id=principal_id, property_ref=feedback_ref))
        except Exception:
            rows_candidate = []
        if summary_candidate and not feedback_summary:
            feedback_summary = summary_candidate
        if rows_candidate and not feedback_rows:
            feedback_rows = rows_candidate
        if feedback_summary and feedback_rows:
            break
    candidate_row["feedback_summary"] = feedback_summary
    candidate_row["feedback_rows"] = feedback_rows[:12]
    return candidate_row


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> Response:
    brand = request_brand(request)
    authenticated_principal = _landing_authenticated_principal(
        container=container,
        access_identity=access_identity,
        request=request,
    )
    if (
        str(brand.get("key") or "").strip() == "propertyquarry"
        and authenticated_principal
        and not _landing_public_home_requested(request)
    ):
        return RedirectResponse("/app/search", status_code=307)
    principal_id = _principal_for_page(container=container, access_identity=access_identity, request=request)
    status = _anonymous_onboarding_status()
    if principal_id:
        status["workspace"] = {
            "name": (
                str(getattr(access_identity, "display_name", "") or "").strip()
                or "PropertyQuarry"
            ),
        }
    else:
        principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    commercial = property_commercial_snapshot(None)
    return _render_public_template(
        request,
        "propertyquarry_home.html" if brand["key"] == "propertyquarry" else "marketing_home.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title=brand["name"],
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "feature_cards": FEATURE_CARDS,
                "how_steps": HOW_STEPS,
                "personas": PERSONAS,
                "product_modules": PRODUCT_MODULES,
                "trust_cards": TRUST_CARDS,
                "landing_faqs": LANDING_FAQS,
                "doc_links": DOC_LINKS,
                "plan_catalog": tuple(commercial.get("plan_catalog") or ()),
                "meta_description": "PropertyQuarry helps renters, buyers, and investors define a brief, rank the strongest homes, open the dossier, and decide with evidence.",
                "structured_data_json": [
                    {
                        "@context": "https://schema.org",
                        "@type": "SoftwareApplication",
                        "name": "PropertyQuarry",
                        "applicationCategory": "BusinessApplication",
                        "description": "A focused property desk for serious apartment and home decisions.",
                        "offers": {
                            "@type": "AggregateOffer",
                            "lowPrice": "0",
                            "priceCurrency": "EUR",
                        },
                    },
                    _faq_structured_data(LANDING_FAQS),
                ],
            },
        ),
    )


@router.get("/product", response_class=HTMLResponse)
def product_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=307)


@router.get("/app/api/property/landing-handoff", include_in_schema=False)
def propertyquarry_landing_handoff(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> dict[str, object]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity, request=request)
    if not principal_id:
        return {"target": "/app/search", "signed_in": False}
    product = build_product_service(container)
    active_run = dict(product.find_active_property_search_run(principal_id=principal_id, limit=8) or {})
    candidate_run_id = str(active_run.get("run_id") or "").strip()
    if candidate_run_id:
        return {
            "target": f"/app/properties?run_id={urllib.parse.quote(candidate_run_id, safe='')}",
            "signed_in": True,
            "run_id": candidate_run_id,
            "status": str(active_run.get("status") or "").strip(),
        }
    return {"target": "/app/search", "signed_in": True}


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    return _render_public_template(
        request,
        "integrations_page.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title="PropertyQuarry Integrations",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "meta_description": "See which PropertyQuarry integrations are live, which stay guided, and where manual review remains explicit.",
            },
        ),
    )


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    channels = dict(status.get("channels") or {})
    mapping = {
        "google": {
            "title": "Google sign-in",
            "eyebrow": "Google",
            "detail_points": (
                "Start with Google sign-in unless you already know you need broader workspace actions.",
                "PropertyQuarry only needs Google identity by default so the same account can return cleanly.",
                "Broader Gmail or Drive context stays an explicit upgrade path instead of the default.",
            ),
            "body_points": (
                "Explain permissions in plain language first and raw scopes second.",
                "Show a real connected account and a real first success instead of treating consent as the finish line.",
                "Keep Google as optional account access, not as the center of the product story.",
            ),
        },
        "telegram": {
            "title": "Telegram",
            "eyebrow": "Telegram",
            "detail_points": (
                "Personal identity linking and official bot installation are separate decisions.",
                "Login alone does not imply generic history import.",
                "Future-only, import-later, and manual-forward are distinct promises and stay distinct in the UI.",
            ),
            "body_points": (
                "Ask first whether this is a personal Telegram setup or a bot rollout.",
                "Record where PropertyQuarry should operate: DM, groups, or channels.",
                "Treat the bot as the durable operating surface once installed and verified.",
            ),
        },
        "whatsapp": {
            "title": "WhatsApp",
            "eyebrow": "WhatsApp",
            "detail_points": (
                "Business onboarding and export intake are separate supported paths.",
                "The assistant does not promise generic automated history download outside those paths.",
                "Live messaging and manual history intake stay visibly distinct in the product contract.",
            ),
            "body_points": (
                "Use Business onboarding for the long-term live assistant path.",
                "Use export intake for personal or unsupported cases without pretending it is live sync.",
                "Keep media inclusion, history source, and future live sync as separate explicit choices.",
            ),
        },
    }
    current = mapping.get(channel_name)
    if current is None:
        raise HTTPException(status_code=404, detail="integration_not_found")
    channel = dict(channels.get(channel_name) or {})
    return _render_public_template(
        request,
        "channel_detail.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title=f"PropertyQuarry {current['title']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "channel": channel,
                "channel_title": current["title"],
                "channel_eyebrow": current["eyebrow"],
                "detail_points": current["detail_points"],
                "body_points": current["body_points"],
                "meta_description": f"Understand how PropertyQuarry handles {current['title']} access, review, and supported actions.",
            },
        ),
    )


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    return _render_public_template(
        request,
        "security_page.html",
        **_public_context(
            request=request,
            current_nav="security",
            page_title="PropertyQuarry Security",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "trust_cards": TRUST_CARDS,
                "meta_description": "Review how PropertyQuarry keeps research visible, actions explicit, and product trust grounded in reviewable evidence.",
            },
        ),
    )


@router.get("/data-deletion", response_class=HTMLResponse)
def data_deletion_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    return _render_public_template(
        request,
        "data_deletion.html",
        **_public_context(
            request=request,
            current_nav="security",
            page_title="PropertyQuarry Data Deletion",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "contact_email": "property@propertyquarry.com",
                "meta_description": "How to request deletion of account, search, connected-channel, and generated property data held by PropertyQuarry.",
            },
        ),
    )


@router.get("/user-data-deletion", response_class=HTMLResponse)
def user_data_deletion_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return data_deletion_page(request=request, container=container, access_identity=access_identity)


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    commercial = property_commercial_snapshot(None)
    checkout_enabled_plans: list[str] = []
    checkout_provider_labels_by_plan: dict[str, str] = {}
    checkout_order_endpoints_by_plan: dict[str, str] = {}
    for paid_plan in ("plus", "agent"):
        if payfunnels_configured(plan_key=paid_plan):
            checkout_enabled_plans.append(paid_plan)
            checkout_provider_labels_by_plan[paid_plan] = "PayFunnels"
            checkout_order_endpoints_by_plan[paid_plan] = "/app/api/signals/property/billing/payfunnels/order"
    checkout_session_ready = access_identity is not None or _workspace_session_payload(request, container) is not None
    return _render_public_template(
        request,
        "pricing_page.html",
        **_public_context(
            request=request,
            current_nav="pricing",
            page_title="PropertyQuarry Pricing",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "pricing_tiers": PRICING_TIERS,
                "plan_catalog": tuple(commercial.get("plan_catalog") or ()),
                "pricing_checkout_enabled_plans": checkout_enabled_plans,
                "pricing_checkout_provider_labels_by_plan": checkout_provider_labels_by_plan,
                "pricing_order_endpoints_by_plan": checkout_order_endpoints_by_plan,
                "pricing_checkout_session_ready": checkout_session_ready,
                "meta_description": "Compare PropertyQuarry plans by search breadth, shortlist density, research depth, and the quality of the property review page.",
                "structured_data_json": [
                    {
                        "@context": "https://schema.org",
                        "@type": "Product",
                        "name": "PropertyQuarry",
                        "description": "Property research and shortlist ranking for renters, buyers, and investors.",
                        "offers": [
                            {
                                "@type": "Offer",
                                "name": str(plan.get("display_name") or ""),
                                "price": str(plan.get("monthly_price_eur") or 0),
                                "priceCurrency": "EUR",
                            }
                            for plan in tuple(commercial.get("plan_catalog") or ())
                        ],
                    },
                    _faq_structured_data(
                        (
                            {
                                "question": "When should I stay on Free?",
                                "answer": "Stay on Free when the main question is whether the ranking and property page are useful at all.",
                            },
                            {
                                "question": "What does Plus change?",
                                "answer": "Plus gives a denser shortlist and richer property pages on a tighter set of sources.",
                            },
                            {
                                "question": "When does Agent make sense?",
                                "answer": "Agent is for ongoing property-desk work that needs full source breadth, denser shortlists, and deeper research at the same time.",
                            },
                        )
                    ),
                ],
            },
        ),
    )


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    return _render_public_template(
        request,
        "docs_page.html",
        **_public_context(
            request=request,
            current_nav="docs",
            page_title="PropertyQuarry Docs",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "doc_links": DOC_LINKS,
                "meta_description": "Read the public documentation for PropertyQuarry features, workflows, and product boundaries.",
            },
        ),
    )


def _render_public_trust_page(
    *,
    page_key: str,
    request: Request,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> HTMLResponse:
    page = PUBLIC_TRUST_PAGES.get(page_key)
    if page is None:
        raise HTTPException(status_code=404, detail="public_trust_page_not_found")
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    return _render_public_template(
        request,
        "public_editorial_page.html",
        **_public_context(
            request=request,
            current_nav=str(page.get("nav") or page_key),
            page_title=f"PropertyQuarry {page['title']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "canonical_path": str(page["path"]),
                "meta_description": str(page["summary"]),
                "editorial_kicker": page["kicker"],
                "editorial_title": page["title"],
                "editorial_summary": page["summary"],
                "editorial_cta_href": "",
                "editorial_cta_label": "",
                "editorial_cta_event": "",
                "editorial_band": page["band"],
                "editorial_sections": page["sections"],
                "editorial_faqs": page["faqs"],
                "structured_data_json": [
                    {
                        "@context": "https://schema.org",
                        "@type": "WebPage",
                        "name": f"PropertyQuarry {page['title']}",
                        "description": str(page["summary"]),
                        "publisher": {"@type": "Organization", "name": "PropertyQuarry"},
                    },
                ],
            },
        ),
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="privacy",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/terms", response_class=HTMLResponse)
def terms_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="terms",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/imprint", response_class=HTMLResponse)
def imprint_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="imprint",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/support", response_class=HTMLResponse)
def support_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="support",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/cookies", response_class=HTMLResponse)
def cookies_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="cookies",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/subprocessors", response_class=HTMLResponse)
def subprocessors_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="subprocessors",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/refunds", response_class=HTMLResponse)
def refunds_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="refunds",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/disclaimers", response_class=HTMLResponse)
def disclaimers_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    return _render_public_trust_page(
        page_key="disclaimers",
        request=request,
        container=container,
        access_identity=access_identity,
    )


@router.get("/guides/wohnung-kaufen-wien-checkliste", response_class=HTMLResponse)
def guide_wien_checklist_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    page = PUBLIC_GUIDE_WIEN
    return _render_public_template(
        request,
        "public_editorial_page.html",
        **_public_context(
            request=request,
            current_nav="docs",
            page_title=str(page["title"]),
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "canonical_path": "/guides/wohnung-kaufen-wien-checkliste",
                "meta_description": str(page["summary"]),
                "editorial_kicker": page["kicker"],
                "editorial_title": page["title"],
                "editorial_summary": page["summary"],
                "editorial_cta_href": "/register",
                "editorial_cta_label": "Open PropertyQuarry",
                "editorial_cta_event": "guide_open_propertyquarry",
                "editorial_band": page["band"],
                "editorial_sections": page["sections"],
                "editorial_faqs": page["faqs"],
                "structured_data_json": [
                    {
                        "@context": "https://schema.org",
                        "@type": "Article",
                        "headline": str(page["title"]),
                        "description": str(page["summary"]),
                        "author": {"@type": "Organization", "name": "PropertyQuarry"},
                        "publisher": {"@type": "Organization", "name": "PropertyQuarry"},
                    },
                    _faq_structured_data(page["faqs"]),
                ],
            },
        ),
    )


@router.get("/markets/vienna", response_class=HTMLResponse)
def market_vienna_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    page = PUBLIC_MARKET_VIENNA
    return _render_public_template(
        request,
        "public_editorial_page.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title=str(page["title"]),
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "canonical_path": "/markets/vienna",
                "meta_description": str(page["summary"]),
                "editorial_kicker": page["kicker"],
                "editorial_title": page["title"],
                "editorial_summary": page["summary"],
                "editorial_cta_href": "/register",
                "editorial_cta_label": "Start a Vienna search",
                "editorial_cta_event": "market_start_search",
                "editorial_band": page["band"],
                "editorial_sections": page["sections"],
                "editorial_faqs": page["faqs"],
                "structured_data_json": [
                    {
                        "@context": "https://schema.org",
                        "@type": "Article",
                        "headline": str(page["title"]),
                        "description": str(page["summary"]),
                        "author": {"@type": "Organization", "name": "PropertyQuarry"},
                        "publisher": {"@type": "Organization", "name": "PropertyQuarry"},
                    },
                    _faq_structured_data(page["faqs"]),
                ],
            },
        ),
    )


@router.api_route("/sign-in", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def sign_in_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    link_status = str(request.query_params.get("link_status") or "").strip()
    link_email = str(request.query_params.get("link_email") or "").strip()
    link_error = str(request.query_params.get("link_error") or "").strip()
    google_error = str(request.query_params.get("google_error") or "").strip()
    google_prefill_email = str(request.query_params.get("google_prefill_email") or "").strip()
    facebook_error = str(request.query_params.get("facebook_error") or "").strip()
    return _render_public_template(
        request,
        "sign_in.html",
        **_public_context(
            request=request,
            current_nav="sign-in",
            page_title=f"Sign in to {request_brand(request)['name']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "sign_in_notes": SIGN_IN_NOTES,
                "sign_in_link_enabled": email_delivery_enabled(),
                "sign_in_link_status": link_status,
                "sign_in_link_email": link_email,
                "sign_in_google_prefill_email": google_prefill_email,
                "sign_in_link_error": link_error,
                "sign_in_google_error": google_error,
                "sign_in_facebook_error": facebook_error,
                "sign_in_facebook_enabled": _facebook_sign_in_enabled(),
                "robots_directive": "noindex, nofollow, noarchive, nosnippet",
            },
        ),
    )


@router.api_route("/sign-in/current-session", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def sign_in_current_session(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    principal_id = _landing_authenticated_principal(
        container=container,
        access_identity=access_identity,
        request=request,
    )
    if principal_id:
        return RedirectResponse(str(request_brand(request).get("app_home") or "/app/search"), status_code=303)
    return RedirectResponse("/sign-in?current_session=missing", status_code=303)


@router.post("/sign-in/email-link")
async def sign_in_email_link(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    email = _form_value(form_data, "email", "").lower()
    product = build_product_service(container)
    try:
        result = product.request_workspace_sign_in_email_links(
            email=email,
            base_url=_public_app_base_url(request),
        )
    except ValueError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "link_status": "invalid",
                    "link_email": email,
                    "link_error": str(exc or "workspace_sign_in_email_invalid"),
                }
            ),
            status_code=303,
        )
    except RuntimeError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "link_status": "failed",
                    "link_email": email,
                    "link_error": str(exc or "workspace_sign_in_email_delivery_not_configured"),
                }
            ),
            status_code=303,
        )
    query = {
        "link_status": "submitted",
        "link_email": str(result.get("email") or email).strip().lower(),
    }
    return RedirectResponse("/sign-in?" + urllib.parse.urlencode(query), status_code=303)


@router.api_route("/sign-in/google", methods=["GET", "POST"], response_model=None, include_in_schema=False)
async def sign_in_google(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    from app.services.google_oauth import build_google_oauth_start

    try:
        packet = build_google_oauth_start(
            principal_id="",
            scope_bundle="identity",
            redirect_uri_override=f"{_public_app_base_url(request)}/google/callback",
            return_to="/sign-in?google_connected=1",
            browser_source="sign_in",
        )
    except RuntimeError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "google_error": str(exc or "google_oauth_not_ready"),
                }
            ),
            status_code=303,
        )
    return RedirectResponse(str(packet.auth_url), status_code=303)


@router.api_route("/sign-in/facebook", methods=["GET", "POST"], response_model=None, include_in_schema=False)
async def sign_in_facebook(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> RedirectResponse:
    from app.services.facebook_oauth import build_facebook_oauth_start

    if not _facebook_sign_in_enabled():
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "facebook_error": "facebook_sign_in_disabled",
                }
            ),
            status_code=303,
        )
    try:
        packet = build_facebook_oauth_start(
            principal_id="",
            redirect_uri_override=f"{_public_app_base_url(request)}/facebook/callback",
            return_to="/sign-in?facebook_connected=1",
            browser_source="sign_in",
        )
    except RuntimeError as exc:
        return RedirectResponse(
            "/sign-in?"
            + urllib.parse.urlencode(
                {
                    "facebook_error": str(exc or "facebook_oauth_not_ready"),
                }
            ),
            status_code=303,
        )
    return RedirectResponse(str(packet.auth_url), status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity, request=request)
    if principal_id:
        build_product_service(container).record_surface_event(
            principal_id=principal_id,
            event_type="activation_opened",
            surface="register",
        )
    return _render_public_template(
        request,
        "register.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Create your PropertyQuarry account" if request_brand(request)["key"] == "propertyquarry" else "Start your workspace",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


@router.api_route("/workspace-invites/{token}", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_preview(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    product = build_product_service(container)
    invite = product.preview_workspace_invitation(token=token)
    if invite is None:
        return _render_secure_link_page(
            request,
            page_title="Workspace invite unavailable",
            current_nav="sign-in",
            link_kicker="Invite unavailable",
            link_title="This workspace invite is no longer valid.",
            link_summary="Ask the workspace owner to send a fresh invitation or use a current sign-in link if you already have access.",
            link_detail_title="What happened",
            link_status_label="Invite unavailable",
            link_rows=[
                {"label": "Invite status", "value": "Unavailable", "detail": "The invite may be expired, revoked, or already replaced."},
                {"label": "Next step", "value": "Request a fresh invite", "detail": "Use sign in if you already have another secure link."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    return _render_secure_link_page(
        request,
        page_title="Review workspace invite",
        current_nav="sign-in",
        link_kicker="Workspace invitation",
        link_title="Review this workspace invite before you join.",
        link_summary="This secure invite opens one executive office. Accept it when you are ready to enter with the role below.",
        link_detail_title="Invite details",
        link_status_label=str(invite.get("status") or "pending").replace("_", " ").title(),
        link_rows=[
            {"label": "Email", "value": str(invite.get("email") or "Unknown"), "detail": ""},
            {"label": "Role", "value": str(invite.get("role") or "operator").replace("_", " ").title(), "detail": ""},
            {
                "label": "Expires",
                "value": str(invite.get("expires_at") or "Not recorded")[:19] or "Not recorded",
                "detail": "Accept before the invite expires so the workspace can issue access cleanly.",
            },
        ],
        primary_action_href=f"/workspace-invites/{urllib.parse.quote(token, safe='')}/accept",
        primary_action_label="Accept invitation",
        secondary_action_href="/sign-in",
        secondary_action_label="Return through existing access",
    )


@router.api_route("/workspace-access/{token}", methods=["GET", "HEAD"], response_model=None, include_in_schema=False)
def workspace_access_session(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
):
    product = build_product_service(container)
    brand = request_brand(request)
    actor = str(request.headers.get("X-EA-Operator-ID") or request.headers.get("X-EA-Principal-ID") or "").strip()
    session = product.open_workspace_access_session(token=token, actor=actor)
    if session is None:
        return _render_secure_link_page(
            request,
            page_title="Sign-in link unavailable",
            current_nav="sign-in",
            link_kicker="Secure link expired",
            link_title="This sign-in link is no longer valid.",
            link_summary="Request a fresh sign-in link or use another secure workspace path such as an invite, current session, or SSO.",
            link_detail_title="What to do next",
            link_status_label="Link expired",
            link_rows=[
                {"label": "Link state", "value": "Expired or revoked", "detail": "Secure workspace links rotate and eventually expire."},
                {"label": "Recovery", "value": "Request a new link", "detail": "Use the same inbox that already has account access."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    target = _normalize_browser_return_to(
        request.query_params.get("return_to") or str(session.get("default_target") or "").strip(),
        default=str(session.get("default_target") or brand.get("app_home") or "/app/properties"),
    )
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        "ea_workspace_session",
        str(session.get("access_token") or "").strip(),
        **_workspace_session_cookie_kwargs(request, expires_at=str(session.get("expires_at") or "").strip()),
    )
    _clear_signed_out_marker_cookie(response, request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.api_route("/app/actions/sign-out", methods=["GET", "POST"], response_model=None, include_in_schema=False)
async def app_sign_out(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body: dict[str, list[str]] = {}
    if request.method == "POST":
        body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    public_base = str(request_brand(request).get("public_base_url") or "/").strip() or "/"
    query_params = request.query_params
    return_to = _normalize_browser_return_to(query_params.get("return_to", "") or _form_value(body, "return_to", public_base), default=public_base)
    if not return_to:
        return_to = public_base
    workspace_session = _workspace_session_payload(request, container)
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    if isinstance(workspace_session, dict):
        session_id = str(workspace_session.get("session_id") or "").strip()
        principal_id = str(workspace_session.get("principal_id") or context.principal_id or "").strip()
        if session_id and principal_id:
            try:
                product.revoke_workspace_access_session(
                    principal_id=principal_id,
                    session_id=session_id,
                    actor=actor,
                )
            except Exception:
                pass
    if (
        context.auth_source == "cloudflare_access"
        and str(container.settings.auth.cf_access_team_domain or "").strip()
    ):
        return_to = _cloudflare_access_logout_url(
            request,
            team_domain=str(container.settings.auth.cf_access_team_domain or "").strip(),
            return_to=return_to,
        )

    response = RedirectResponse(return_to, status_code=303)
    _clear_workspace_session_cookie(response, request)
    response.set_cookie("ea_workspace_signed_out", "1", **_signed_out_marker_cookie_kwargs(request))
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    return response


@router.api_route("/workspace-invites/{token}/accept", methods=["GET", "HEAD"], response_class=HTMLResponse, include_in_schema=False)
def workspace_invite_accept(
    token: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    product = build_product_service(container)
    actor = str(
        getattr(access_identity, "email", "")
        or request.headers.get("X-EA-Operator-ID")
        or request.headers.get("X-EA-Principal-ID")
        or "workspace_invite"
    ).strip() or "workspace_invite"
    try:
        invite = product.accept_workspace_invitation(token=token, accepted_by=actor)
    except ValueError as exc:
        if str(exc or "").strip() == "operator_seat_limit_reached":
            return _render_secure_link_page(
                request,
                page_title="Invite cannot be accepted",
                current_nav="sign-in",
                link_kicker="Workspace full",
                link_title="This workspace cannot add another operator right now.",
                link_summary="The office is at its current operator seat limit. Ask the workspace owner to free a seat or upgrade the plan before retrying.",
                link_detail_title="Why acceptance stopped",
                link_status_label="Seat limit reached",
                link_rows=[
                    {"label": "Invite status", "value": "Pending", "detail": "The invite is still valid, but the workspace needs room before it can be accepted."},
                    {"label": "Next step", "value": "Contact the workspace owner", "detail": "They can revoke an unused seat or expand the plan and resend access."},
                ],
                primary_action_href="/sign-in",
                primary_action_label="Return to sign in",
                secondary_action_href="/register",
                secondary_action_label="Create account",
                status_code=409,
            )
        raise
    if invite is None:
        return _render_secure_link_page(
            request,
            page_title="Workspace invite unavailable",
            current_nav="sign-in",
            link_kicker="Invite unavailable",
            link_title="This workspace invite is no longer valid.",
            link_summary="Ask the workspace owner to send a fresh invitation or use another secure workspace link if you already have access.",
            link_detail_title="What happened",
            link_status_label="Invite unavailable",
            link_rows=[
                {"label": "Invite state", "value": "Unavailable", "detail": "The invite may be expired, revoked, or already used."},
                {"label": "Next step", "value": "Request a fresh invite", "detail": "A new secure link will reopen the correct workspace."},
            ],
            primary_action_href="/sign-in",
            primary_action_label="Request new sign-in link",
            secondary_action_href="/register",
            secondary_action_label="Create account",
            status_code=404,
        )
    access_url = str(invite.get("access_url") or "").strip()
    if access_url:
        response = RedirectResponse(access_url, status_code=303)
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    return _render_secure_link_page(
        request,
        page_title="Workspace invite accepted",
        current_nav="sign-in",
        link_kicker="Invitation accepted",
        link_title="Your workspace invite was accepted.",
        link_summary="Continue through sign in if you need another secure access link for this workspace.",
        link_detail_title="Accepted access",
        link_status_label=str(invite.get("status") or "accepted").replace("_", " ").title(),
        link_rows=[
            {"label": "Email", "value": str(invite.get("email") or "Workspace teammate"), "detail": ""},
            {"label": "Role", "value": str(invite.get("role") or "operator").replace("_", " ").title(), "detail": ""},
        ],
        primary_action_href="/sign-in",
        primary_action_label="Continue to sign in",
        secondary_action_href=str(request_brand(request).get("app_home") or "/app/today"),
        secondary_action_label="Open current session",
    )


@router.get("/get-started", response_class=HTMLResponse)
def get_started() -> RedirectResponse:
    return RedirectResponse("/register", status_code=307)


@router.get("/app", response_class=HTMLResponse)
def app_root(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request_brand(request).get("app_home") or "/app/today"), status_code=307)


@router.get("/app/research/{candidate_ref}", response_class=HTMLResponse)
def property_research_packet(
    candidate_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    run_id: str = Query(default=""),
    investment: int = Query(default=0),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    product = build_product_service(container)
    property_context = _property_console_context(
        container=container,
        principal_id=context.principal_id,
        status=status,
        run_id=run_id,
    )
    normalized_candidate_ref = str(candidate_ref or "").strip()
    resolved_run_id = str(run_id or "").strip()
    candidate = _property_lookup_candidate(
        property_context=property_context,
        candidate_ref=normalized_candidate_ref,
    )
    if candidate is None:
        candidate, matched_run_id = _property_lookup_candidate_across_runs(
            product,
            principal_id=context.principal_id,
            candidate_ref=normalized_candidate_ref,
            run_id=resolved_run_id,
        )
        if candidate is not None and matched_run_id and matched_run_id != resolved_run_id:
            resolved_run_id = matched_run_id
            with contextlib.suppress(Exception):
                property_context["run"] = dict(
                    product.get_property_search_run_status(
                        principal_id=context.principal_id,
                        run_id=resolved_run_id,
                    )
                    or {}
                )
    if candidate is None:
        candidate = _property_lookup_candidate_in_saved_shortlist(
            product,
            principal_id=context.principal_id,
            candidate_ref=normalized_candidate_ref,
        )
    if candidate is not None and not resolved_run_id:
        resolved_run_id = str(candidate.get("saved_from_run_id") or "").strip()
    if candidate is None:
        return _property_missing_packet_response(
            request,
            container=container,
            principal_id=context.principal_id,
            run_id=resolved_run_id,
            candidate_ref=normalized_candidate_ref,
        )
    workspace = dict(status.get("workspace") or {})
    assessment = dict(candidate.get("assessment") or {})
    facts = _property_enriched_candidate_facts(candidate=candidate)
    match_reasons = [str(item).strip() for item in list(candidate.get("match_reasons") or []) if str(item).strip()]
    mismatch_reasons = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
    preferences = dict(property_context.get("preferences") or {})
    commercial = dict(property_context.get("commercial") or {})
    fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "No fit summary captured.").strip()
    review_url = str(candidate.get("review_url") or "").strip()
    tour_url = str(candidate.get("tour_url") or "").strip()
    property_url = str(
        candidate.get("property_url")
        or candidate.get("listing_url")
        or candidate.get("source_url")
        or candidate.get("url")
        or ""
    ).strip()
    source_label = str(candidate.get("source_label") or "Property scout").strip() or "Property scout"
    display_source_label = _compact_provider_label(source_label) or source_label
    title = str(candidate.get("title") or property_url or "Research packet").strip() or "Research packet"
    display_title = _property_research_title_display(title)
    run_target = (
        f"/app/research/{candidate_ref}"
        + (f"?run_id={urllib.parse.quote(resolved_run_id, safe='')}" if str(resolved_run_id or "").strip() else "")
    )
    preference_person_id = str(preferences.get("preference_person_id") or "self").strip() or "self"
    packet_score_rows = _property_packet_score_rows(
        facts=facts,
        preferences=preferences,
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
    )
    everyday_fit_rows = _property_packet_everyday_fit_rows(
        facts=facts,
        preferences=preferences,
    )
    risk_fit_rows = _property_packet_risk_fit_rows(
        facts=facts,
        preferences=preferences,
    )
    missing_rows = _property_packet_missing_rows(
        facts=facts,
        preferences=preferences,
    )
    decision_rows = _property_packet_decision_rows(
        candidate=candidate,
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
        missing_rows=missing_rows,
    )
    provenance_rows = _property_packet_provenance_rows(facts)
    official_evidence_rows = _property_packet_official_evidence_rows(facts)
    official_posture_rows = _property_packet_official_posture_rows(facts)
    future_research_rows = _property_packet_future_research_rows(facts)
    compare_rows = _property_packet_compare_rows(
        property_context=property_context,
        current_candidate_ref=normalized_candidate_ref,
    )
    compare_table_rows = _property_packet_compare_table(
        property_context=property_context,
        current_candidate=candidate,
        current_candidate_ref=normalized_candidate_ref,
    )
    investment_rows, investment_risk_rows = _property_investment_research_rows(
        property_url=property_url,
        facts=facts,
        preferences=preferences,
        commercial=commercial,
        requested=bool(int(investment or 0)),
    )
    ooda_summary_rows = [
        _object_detail_row("Why this was selected", _clean_property_candidate_copy(match_reasons[0]), "Match")
        if match_reasons
        else _object_detail_row("Why this was selected", _clean_property_candidate_copy(fit_summary) or "This candidate survived the shortlist ranking.", "Match"),
        _object_detail_row(
            "Best reason to act",
            _clean_property_candidate_copy(str(decision_rows[0].get("detail") or fit_summary).strip())
            or "The current packet sees enough signal to keep this candidate open.",
            "Quick read",
        ),
        _object_detail_row("Main concern", _clean_property_candidate_copy(mismatch_reasons[0]), "Risk")
        if mismatch_reasons
        else _object_detail_row("Main concern", "Some evidence is still missing, so this packet should be treated as a research view, not final diligence.", "Risk"),
        _object_detail_row("Next step", str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate", "Decision"),
    ]
    for item in _property_missing_fact_items(facts):
        if str(item.get("status") or "").strip().lower() == "filled":
            continue
        ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
        ooda_summary_rows.append(
            _object_detail_row(
                str(item.get("label") or item.get("field") or "Missing fact").strip(),
                str(ooda.get("orient") or ooda.get("act") or item.get("evidence") or "Missing-fact research queued.").strip(),
                "Research",
            )
        )
    ooda_summary_rows.extend(_property_distance_ooda_rows_for_preferences(facts, preferences))
    investment_run_target = run_target + ("&investment=1" if "?" in run_target else "?investment=1")
    try:
        feedback_suggestions = dict(product.property_feedback_suggestions(property_facts=facts, assessment=assessment or candidate))
    except Exception:
        feedback_suggestions = {"negative": [], "positive": []}
    packet_service = build_fliplink_packet_service(container)
    feedback_summary: dict[str, object] = {}
    property_timeline_rows: list[dict[str, object]] = []
    structured_feedback_rows: list[dict[str, object]] = []
    for feedback_ref in _property_feedback_reference_candidates(str(candidate_ref or "").strip(), candidate):
        try:
            summary_candidate = dict(packet_service.feedback_summary(principal_id=context.principal_id, property_ref=feedback_ref))
        except Exception:
            summary_candidate = {}
        try:
            timeline_candidate = list(packet_service.property_timeline(principal_id=context.principal_id, property_ref=feedback_ref))
        except Exception:
            timeline_candidate = []
        try:
            feedback_rows_candidate = list(packet_service.list_structured_feedback(principal_id=context.principal_id, property_ref=feedback_ref))
        except Exception:
            feedback_rows_candidate = []
        if summary_candidate and not feedback_summary:
            feedback_summary = summary_candidate
        if timeline_candidate and not property_timeline_rows:
            property_timeline_rows = timeline_candidate
        if feedback_rows_candidate and not structured_feedback_rows:
            structured_feedback_rows = feedback_rows_candidate
        if feedback_summary and property_timeline_rows and structured_feedback_rows:
            break
    objection_clusters = [
        _object_detail_row(
            str(cluster.get("theme") or "feedback").replace("_", " ").title(),
            str(cluster.get("summary") or "No detail yet.").strip(),
            str(cluster.get("severity") or "medium").strip().title(),
        )
        for cluster in list(feedback_summary.get("clusters") or [])[:4]
        if isinstance(cluster, dict)
    ]
    if not objection_clusters:
        objection_clusters = [
            _object_detail_row(
                "No recorded objections yet",
                "Stakeholder objections and reviewer disagreements will surface here once packet or decision feedback is captured.",
                "Waiting",
            )
        ]
    household_review = dict(feedback_summary.get("household_review") or {}) if isinstance(feedback_summary.get("household_review"), dict) else {}
    household_rows = [
        _object_detail_row(
            str(row.get("stakeholder_label") or "Stakeholder").strip(),
            str(row.get("reason") or "No detail yet.").strip(),
            str(row.get("decision") or "maybe").replace("_", " ").title(),
        )
        for row in list(household_review.get("stakeholders") or [])[:4]
        if isinstance(row, dict)
    ]
    if not household_rows:
        household_rows = [
            _object_detail_row(
                "No household votes yet",
                "Shared household or advisor reactions will appear here once someone records a Yes, Maybe, or No.",
                "Waiting",
            )
        ]
    risk_signal_rows = [
        _object_detail_row(
            str(row.get("theme") or "risk").replace("_", " ").title(),
            f"{str(row.get('summary') or 'No summary yet.').strip()} | privacy {str(row.get('privacy_state') or 'suppressed')} | confidence {str(row.get('confidence') or 'low')}",
            str(row.get("reason_key") or "signal").replace("_", " ").title(),
        )
        for row in list(feedback_summary.get("risk_signal_candidates") or [])[:4]
        if isinstance(row, dict)
    ]
    if not risk_signal_rows:
        risk_signal_rows = [
            _object_detail_row(
                "No published risk signal yet",
                "PropertyQuarry is still below the anonymization threshold for this property, so market-risk candidates stay suppressed.",
                "Suppressed",
            )
        ]
    next_best_question = str(household_review.get("next_best_question") or "").strip()
    timeline_rows = [
        _object_detail_row(
            str(row.get("event_type") or "packet_update").replace("_", " ").title(),
            str(row.get("summary") or "Property state updated.").strip(),
            str(row.get("created_at") or "").replace("T", " ").replace("+00:00", " UTC")[:32] or "Timeline",
        )
        for row in property_timeline_rows[:6]
        if isinstance(row, dict)
    ]
    if not timeline_rows:
        timeline_rows = [
            _object_detail_row("Shortlist state", "This property page is ready for a decision and agent follow-up.", "Now"),
            _object_detail_row("Tour state", _property_tour_detail_line(candidate), "360"),
            _object_detail_row("Feedback state", "No timeline events are recorded yet. The first saved decision will start the visible timeline.", "Waiting"),
        ]
    changed_rows = timeline_rows[:3] or [
        _object_detail_row(
            "No new deltas yet",
            "The first saved decision, share event, or follow-up update will appear here.",
            "Waiting",
        )
    ]
    latest_magic_fit_scene = product.latest_property_magic_fit_scene(
        principal_id=context.principal_id,
        property_ref=str(candidate_ref or "").strip(),
    )
    magic_fit_rows = [
        _object_detail_row(
            str(latest_magic_fit_scene.get("scene_type") or "Lifestyle scene").replace("_", " ").title(),
            str(latest_magic_fit_scene.get("summary") or "A generated family-in-space still is ready for the packet and PDF.").strip(),
            "Visual simulation",
            href=str(latest_magic_fit_scene.get("image_url") or "").strip(),
            secondary_action_href=str(latest_magic_fit_scene.get("image_url") or "").strip(),
            secondary_action_label="Open still" if str(latest_magic_fit_scene.get("image_url") or "").strip() else "",
            secondary_action_method="get" if str(latest_magic_fit_scene.get("image_url") or "").strip() else "",
        )
    ] if latest_magic_fit_scene else [
        _object_detail_row(
            "No scene generated yet",
            "Opt in to create a furnished family-life still for the packet. It stays clearly marked as a visual simulation and can be attached to the PDF dossier.",
            "Opt-in",
        )
    ]
    agent_question_rows = [
        _object_detail_row(
            f"Question {index + 1}",
            str(row.get("question") or "").strip(),
            str(row.get("status") or "suggested").replace("_", " ").title(),
        )
        for index, row in enumerate(list(feedback_suggestions.get("agent_questions") or [])[:5])
        if isinstance(row, dict) and str(row.get("question") or "").strip()
    ]
    if not agent_question_rows:
        agent_question_rows = [
            _object_detail_row(
                "No generated question yet",
                "Save a decision or add missing-fact blockers to generate the next agent brief automatically.",
                "Waiting",
            )
        ]
    followup_rows = [
        {
            "feedback_id": str(row.get("feedback_id") or "").strip(),
            "title": str(row.get("text") or row.get("category") or "Follow-up").strip(),
            "detail": str(row.get("followup_note") or row.get("stakeholder_label") or row.get("stakeholder_id") or "").strip(),
            "tag": str(row.get("followup_status") or "suggested").replace("_", " ").title(),
        }
        for row in structured_feedback_rows
        if isinstance(row, dict) and str(row.get("category") or "").strip() == "question"
    ]
    if not followup_rows:
        followup_rows = [
            {
                "feedback_id": "",
                "title": "No tracked question yet",
                "detail": "Use the question helper or the suggested next question to start a tracked follow-up.",
                "tag": "Waiting",
            }
        ]
    detail_sections = _candidate_detail_sections(facts)
    price_summary = str(
        facts.get("price_display")
        or facts.get("rent_display")
        or facts.get("price")
        or _property_research_money_display(facts.get("price_eur"))
        or ""
    ).strip()
    if not price_summary or price_summary.lower() == "n/a":
        price_summary = _property_title_price_fallback(title)
    area_summary = str(facts.get("area_m2") or facts.get("living_area_m2") or "").strip()
    rooms_summary = str(facts.get("rooms_label") or facts.get("rooms") or facts.get("room_count") or "").strip()
    location_summary = str(
        candidate.get("location_label")
        or facts.get("district")
        or facts.get("postal_name")
        or facts.get("address")
        or facts.get("source_scope_location")
        or source_label
        or ""
    ).strip()
    headline_summary_parts = [
        part
        for part in (
            price_summary,
            f"{area_summary} m²" if area_summary else "",
            rooms_summary,
            location_summary,
        )
        if str(part or "").strip()
    ]
    object_summary = " · ".join(headline_summary_parts) or display_source_label
    if price_summary and not any(str(row.get("label") or "").strip().lower() == "rent / price" for row in list(detail_sections.get("cost_rows") or [])):
        detail_sections["cost_rows"] = [{"label": "Rent / price", "value": price_summary}] + list(detail_sections.get("cost_rows") or [])
    research_media = _property_tour_media_payload(candidate)
    orientation_preview = _property_candidate_orientation_preview(candidate)
    preview_image = _property_candidate_preview_image(candidate)
    gallery_items = _property_research_gallery_items(
        candidate=candidate,
        facts=facts,
        preview_image=preview_image,
        latest_magic_fit_scene=latest_magic_fit_scene if isinstance(latest_magic_fit_scene, dict) else None,
    )
    location_preview = {
        "image_url": str(orientation_preview.get("image_url") or "").strip(),
        "map_url": str(orientation_preview.get("map_url") or "").strip(),
        "embed_url": _google_maps_embed_url(orientation_preview.get("map_url")),
        "title": str(orientation_preview.get("title") or location_summary or "Wider area").strip(),
        "alt": str(orientation_preview.get("alt") or f"Map around {location_summary or display_source_label}").strip(),
        "caption": str(orientation_preview.get("caption") or "").strip(),
        "district_rows": list(orientation_preview.get("district_rows") or []),
    }
    flythrough_url = str(candidate.get("flythrough_url") or "").strip()
    tour_status = str(candidate.get("tour_status") or "").strip().lower()
    flythrough_status = str(candidate.get("flythrough_status") or "").strip().lower()
    hosted_tour_ready = bool(research_media.get("hosted_ready"))
    eta_raw = str(candidate.get("tour_eta_minutes") or "").strip()
    hero_actions: list[dict[str, object]] = []
    if property_url:
        hero_actions.append({"href": property_url, "label": "Open listing", "external": True})
    if hosted_tour_ready and tour_url:
        hero_actions.append({"href": tour_url, "label": "Open 3D tour", "external": False})
    elif tour_url and not hosted_tour_ready and property_url:
        hero_actions.append({"kind": "tour", "label": "Rebuild 3D tour", "property_url": property_url, "state": "idle"})
    elif tour_status in {"queued", "pending"} and property_url:
        hero_actions.append({"kind": "tour", "label": f"3D tour queued{f' · ETA {eta_raw} min' if eta_raw else ''}", "property_url": property_url, "state": "pending"})
    elif tour_status in {"processing", "running", "in_progress", "started"} and property_url:
        hero_actions.append({"kind": "tour", "label": f"3D tour rendering{f' · ETA {eta_raw} min' if eta_raw else ''}", "property_url": property_url, "state": "rendering"})
    elif property_url:
        hero_actions.append({"kind": "tour", "label": "Request 3D tour", "property_url": property_url, "state": "idle"})
    if flythrough_url:
        hero_actions.append({"href": flythrough_url, "label": "Open flythrough", "external": False})
    elif flythrough_status in {"queued", "pending"} and property_url:
        hero_actions.append({"kind": "flythrough", "label": "Flythrough queued", "property_url": property_url, "state": "pending"})
    elif flythrough_status in {"processing", "running", "in_progress", "started"} and property_url:
        hero_actions.append({"kind": "flythrough", "label": "Flythrough rendering", "property_url": property_url, "state": "rendering"})
    elif property_url:
        hero_actions.append({"kind": "flythrough", "label": "Request walkthrough", "property_url": property_url, "state": "idle"})
    if str(candidate.get("packet_url") or review_url or "").strip():
        hero_actions.append({"href": str(candidate.get("packet_url") or review_url or "").strip(), "label": "Copy page link", "copy": True})
    visual_status_line = ""
    if flythrough_url:
        visual_status_line = "Flythrough is ready on this page."
    elif flythrough_status in {"queued", "pending"}:
        visual_status_line = "Flythrough is queued and will appear here as soon as rendering starts."
    elif flythrough_status in {"processing", "running", "in_progress", "started"}:
        visual_status_line = "Flythrough is rendering now and will appear here when it is ready."
    elif hosted_tour_ready and tour_url:
        visual_status_line = "3D tour is ready. You can inspect it now or request a flythrough next."
    elif tour_url and not hosted_tour_ready:
        visual_status_line = "Hosted 3D assets are not ready yet. You can request a rebuild now."
    elif tour_status in {"queued", "pending"}:
        visual_status_line = f"3D tour is queued{f' with an ETA of about {eta_raw} minutes' if eta_raw else ''}."
    elif tour_status in {"processing", "running", "in_progress", "started"}:
        visual_status_line = f"3D tour is rendering{f' with an ETA of about {eta_raw} minutes' if eta_raw else ''}."
    overview_rows = [
        {"label": "Price", "value": price_summary or "Price on request"},
        {"label": "Area", "value": f"{area_summary} m²" if area_summary else "Not listed"},
        {"label": "Rooms", "value": rooms_summary or "Not listed"},
        {"label": "Location", "value": location_summary or display_source_label},
    ]
    if detail_sections.get("feature_values"):
        overview_rows.append({"label": "Highlights", "value": ", ".join(list(detail_sections.get("feature_values") or [])[:4])})
    research_sections: list[dict[str, object]] = [
        {
            "eyebrow": "At a glance",
            "title": "Why this home stayed on the list",
            "items": ooda_summary_rows[:6],
        },
        {
            "eyebrow": "Property details",
            "title": "What the listing says",
            "items": [_object_detail_row(str(row.get("label") or "").strip(), str(row.get("value") or "").strip(), "Listing") for row in list(detail_sections.get("object_rows") or [])],
        },
        {
            "eyebrow": "Costs",
            "title": "Price, running costs, and fees",
            "items": [_object_detail_row(str(row.get("label") or "").strip(), str(row.get("value") or "").strip(), "Listing") for row in list(detail_sections.get("cost_rows") or [])],
        },
        {
            "eyebrow": "Description",
            "title": "How the home is described",
            "copy": str(detail_sections.get("description_text") or "").strip(),
            "items": [],
        },
        {
            "eyebrow": "Location & area",
            "title": "How the wider area reads today",
            "copy": str(detail_sections.get("location_text") or "").strip(),
            "items": everyday_fit_rows[:6],
        },
        {
            "eyebrow": "Energy & heating",
            "title": "Energy posture and heating",
            "items": [_object_detail_row(str(row.get("label") or "").strip(), str(row.get("value") or "").strip(), "Listing") for row in list(detail_sections.get("energy_rows") or [])],
        },
        {
            "eyebrow": "Before you decide",
            "title": "What still needs an answer",
            "items": (missing_rows + investment_risk_rows)[:10] or [_object_detail_row("No blocker recorded", "The current file does not show a blocking gap beyond normal due diligence.", "Clear")],
        },
        {
            "eyebrow": "Next step",
            "title": "What to do with this home now",
            "items": decision_rows,
        },
        {
            "eyebrow": "Evidence added",
            "title": "What PropertyQuarry researched beyond the listing",
            "items": (official_evidence_rows[:4] + official_posture_rows[:3] + future_research_rows[:3] + provenance_rows[:3])
            or [_object_detail_row("No external evidence attached yet", "Broader research has not attached external datasets to this property yet.", "Pending")],
        },
        {
            "eyebrow": "Ask next",
            "title": "Questions worth sending now",
            "items": agent_question_rows + ([_object_detail_row("Next household question", next_best_question, "Next")] if next_best_question else []),
        },
        {
            "eyebrow": "What changed",
            "title": "Timeline and follow-up",
            "items": timeline_rows,
        },
        {
            "eyebrow": "Compare next",
            "title": "The next-best homes from this run",
            "table_headers": ["Candidate", "Fit", "Price", "Layout", "360", "Open"],
            "table_rows": compare_table_rows,
            "items": compare_rows or [_object_detail_row("No compare lane yet", "This run has no second-best candidate attached for side-by-side comparison yet.", "Waiting")],
        },
    ]
    if str(preferences.get("listing_mode") or "").strip().lower() == "buy":
        research_sections.insert(
            7,
            {
                "eyebrow": "Investment",
                "title": "Buy-side underwriting view",
                "items": investment_rows
                or [_object_detail_row("Investment research is off", "Run the buy-side research pass if you need yield, reserve, and document-risk context.", "Optional")],
            },
        )
    feedback_payload = {
        "person_id": preference_person_id,
        "profile_href": f"/app/profile" + (f"?run_id={urllib.parse.quote(run_id, safe='')}" if str(run_id or "").strip() else ""),
        "suggestions": feedback_suggestions,
        "property_url": property_url,
        "packet_href": f"/app/research/{urllib.parse.quote(candidate_ref, safe='')}" + (f"?run_id={urllib.parse.quote(run_id, safe='')}" if str(run_id or "").strip() else ""),
        "property_title": display_title,
        "property_facts": facts,
        "assessment": assessment or candidate,
        "investment_context": investment_rows + investment_risk_rows,
        "followup_rows": followup_rows,
        "magic_fit_scene": latest_magic_fit_scene,
        "property_slug": str(candidate_ref or "").strip(),
        "save_endpoint": f"/app/api/people/{urllib.parse.quote(preference_person_id, safe='')}/preference-profile/property-feedback",
        "clippy_endpoint": "/app/api/property/decision-copilot",
        "magic_fit_create_endpoint": "/app/api/property/magic-fit-scenes",
        "magic_fit_upload_endpoint": "/app/api/property/magic-fit-reference-files",
        "google_photos_session_endpoint": "/app/api/signals/google/photos/session",
        "google_photos_session_status_endpoint_template": "/app/api/signals/google/photos/session/__SESSION_ID__",
        "structured_feedback_endpoint": "/app/api/property-feedback",
        "followup_status_endpoint_template": "/app/api/property-feedback/__FEEDBACK_ID__/followup-status",
    }
    review_page_neuronwriter = dict(candidate.get("review_page_neuronwriter") or {})
    research_snapshot = build_property_research_packet_snapshot(
        title=display_title,
        summary=object_summary,
        source_label=display_source_label,
        price=price_summary or "Price on request",
        area=f"{area_summary} m²" if area_summary else "",
        rooms=rooms_summary,
        location=location_summary or display_source_label,
        media=research_media,
        preview_image=preview_image,
        gallery_items=gallery_items,
        location_preview=location_preview,
        actions=hero_actions,
        visual_status_line=visual_status_line,
        source_ref=str(candidate.get("source_ref") or "").strip(),
        run_id=str(run_id or "").strip(),
        candidate_ref=str(candidate_ref or "").strip(),
        overview_rows=overview_rows,
        sections=research_sections,
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
        listing_rows=list(detail_sections.get("object_rows") or []),
        cost_rows=list(detail_sections.get("cost_rows") or []),
        feature_values=list(detail_sections.get("feature_values") or []),
        description_text=str(detail_sections.get("description_text") or "").strip(),
        location_text=str(detail_sections.get("location_text") or "").strip(),
        energy_rows=list(detail_sections.get("energy_rows") or []),
        missing_rows=missing_rows,
        decision_rows=decision_rows,
        compare_rows=compare_rows,
        compare_table_rows=compare_table_rows,
        compare_headers=["Candidate", "Fit", "Price", "Layout", "360", "Open"],
        official_evidence_rows=official_evidence_rows,
        official_posture_rows=official_posture_rows,
        future_research_rows=future_research_rows,
        provenance_rows=provenance_rows,
        timeline_rows=timeline_rows,
        everyday_fit_rows=everyday_fit_rows,
        risk_fit_rows=risk_fit_rows,
        investment_rows=investment_rows,
        investment_risk_rows=investment_risk_rows,
        next_best_question=next_best_question,
        feedback=feedback_payload,
        neuronwriter=review_page_neuronwriter,
        objection_rows=objection_clusters,
        household_rows=household_rows,
        risk_signal_rows=risk_signal_rows,
    )
    return _render_public_template(
        request,
        "app/property_research_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"PropertyQuarry {display_title}",
                current_nav="research",
                context=context,
                console_title="Property",
                console_summary="",
                nav_groups=app_nav_groups_for_brand(request_brand(request)["key"]),
                workspace_label=str(workspace.get("name") or "PropertyQuarry"),
                cards=[],
                stats=[{"label": row["label"], "value": row["value"]} for row in overview_rows[:4]],
            ),
            **research_snapshot,
        },
    )


@router.get("/app/properties/notifications/preview", response_class=HTMLResponse)
def property_notification_preview_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    template: str = Query(default="search_results_ready"),
) -> HTMLResponse:
    del container, context
    templates_available = (
        "search_results_ready",
        "property_match",
        "tour_ready",
        "investment_research_ready",
        "workspace_invitation",
        "workspace_access",
        "google_connect",
        "market_ready",
    )
    selected = str(template or "search_results_ready").strip().lower() or "search_results_ready"
    if selected not in templates_available:
        selected = "search_results_ready"
    preview = property_notification_preview(selected)
    options = "".join(
        f'<option value="{html.escape(key)}" {"selected" if key == selected else ""}>{html.escape(key.replace("_", " "))}</option>'
        for key in templates_available
    )
    body = f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>PropertyQuarry notification preview</title>
      {_clickrank_head_snippet(_request_hostname(request), _request_path(request))}
      <style>
        body {{ margin:0; background:#f6f3ee; color:#242321; font:14px/1.6 Arial,Helvetica,sans-serif; }}
        .wrap {{ max-width:1280px; margin:0 auto; padding:24px; display:grid; gap:18px; }}
        .panel {{ background:#fffdf8; border:1px solid #ded6c8; border-radius:18px; padding:20px; }}
        .grid {{ display:grid; grid-template-columns:320px 1fr; gap:18px; }}
        .meta {{ color:#6c675f; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
        h1,h2 {{ margin:0 0 12px; }}
        select {{ width:100%; min-height:42px; border:1px solid #b9ad9a; border-radius:10px; padding:0 12px; background:#fffdf8; }}
        pre {{ white-space:pre-wrap; word-break:break-word; background:#fdf9f1; border:1px solid #ded6c8; border-radius:12px; padding:14px; }}
        iframe {{ width:100%; min-height:720px; border:1px solid #ded6c8; border-radius:12px; background:#fff; }}
        .actions a {{ color:#825818; text-decoration:underline; text-underline-offset:3px; font-weight:700; }}
        @media (max-width: 980px) {{ .grid {{ grid-template-columns:1fr; }} iframe {{ min-height:560px; }} }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="panel">
          <div class="meta">PropertyQuarry notification system</div>
          <h1>Email preview</h1>
          <div class="actions"><a href="/app/alerts">Back to alerts</a></div>
        </div>
        <div class="grid">
          <div class="panel">
            <form method="get" action="/app/properties/notifications/preview">
              <div class="meta">Template</div>
              <select name="template">{options}</select>
            </form>
            <script>document.querySelector('select[name="template"]')?.addEventListener('change', (event) => event.target.form.submit());</script>
            <div style="height:18px"></div>
            <div class="meta">Subject</div>
            <h2>{html.escape(str(preview.get("subject") or ""))}</h2>
            <div class="meta">Preheader</div>
            <p>{html.escape(str(preview.get("preheader") or ""))}</p>
            <div class="meta">Plain text</div>
            <pre>{html.escape(str(preview.get("text") or ""))}</pre>
          </div>
          <div class="panel">
            <div class="meta">HTML render</div>
            <iframe sandbox="" srcdoc="{html.escape(str(preview.get('html') or ''))}"></iframe>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(body)


@router.get("/app/{section}", response_class=HTMLResponse)
def app_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    run_id: str = Query(default=""),
    candidate: str = Query(default=""),
    agent_id: str = Query(default=""),
    packet_missing: str = Query(default=""),
    missing_candidate_ref: str = Query(default=""),
) -> HTMLResponse:
    brand = request_brand(request)
    property_brand = brand["key"] == "propertyquarry"
    nav_groups = app_nav_groups_for_brand(brand["key"])
    allowed = {item["href"].rstrip("/").rsplit("/", 1)[-1] for group in nav_groups for item in group["items"]}
    legacy_redirects = {
        "briefing": "/app/queue",
        "inbox": "/app/queue",
        "follow-ups": "/app/commitments",
        "memory": "/app/people",
        "contacts": "/app/evidence",
        "activity": "/admin/office",
        "channels": "/app/settings",
        "automation": "/app/settings",
        "automations": "/app/settings",
    }
    property_legacy_redirects = {
        "today": "/app/properties",
        "queue": "/app/shortlist",
        "commitments": "/app/account",
        "people": "/app/account",
        "evidence": "/app/account",
        "activity": "/app/account",
        "channel-loop": "/app/account",
        "automation": "/app/agents",
        "automations": "/app/agents",
        "channels": "/app/account#delivery",
        "research": "/app/properties",
        "profile": "/app/account",
        "settings": "/app/account",
        "usage": "/app/settings/usage",
        "support": "/app/settings/support",
        "trust": "/app/settings/trust",
        "google": "/app/settings/google",
        "access": "/app/settings/access",
        "invitations": "/app/settings/invitations",
        "outcomes": "/app/settings/outcomes",
        "plan": "/app/settings/plan",
    }
    allowed.update(legacy_redirects)
    allowed.update({"today", "queue", "commitments", "people", "evidence", "activity", "channel-loop"})
    if property_brand:
        allowed.update({"properties", "search", "shortlist", "agents", "alerts", "billing", "account"})
        legacy_redirects.update(property_legacy_redirects)
        allowed.update(property_legacy_redirects)
    else:
        allowed.update(
            {
                "today",
                "queue",
                "commitments",
                "people",
                "evidence",
                "properties",
                "settings",
                "search",
                "channel-loop",
            }
        )
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    if section in legacy_redirects:
        target = legacy_redirects[section]
        query = str(request.url.query or "").strip()
        if query:
            target = f"{target}?{query}"
        return RedirectResponse(target, status_code=307)
    resolved_section = section
    current_nav = section
    property_surface_aliases = {
        "properties": "properties",
        "search": "search",
        "shortlist": "shortlist",
        "agents": "agents",
        "alerts": "alerts",
        "account": "account",
        "billing": "billing",
    }
    status = container.onboarding.status(principal_id=context.principal_id)
    normalized_run_id = str(run_id or "").strip()
    if property_brand and resolved_section in {"properties", "shortlist"} and normalized_run_id:
        product = build_product_service(container)
        route_run = dict(
            product.get_property_search_run_status(
                principal_id=context.principal_id,
                run_id=normalized_run_id,
            )
            or {}
        )
        if not route_run:
            raise HTTPException(status_code=404, detail="property_search_run_not_found")
        if resolved_section == "properties":
            route_run_status = str(route_run.get("status") or "").strip().lower()
            if route_run_status in {"processed", "completed", "completed_partial"} and _property_run_payload_has_shortlist_results(route_run):
                target = "/app/shortlist"
                query = str(request.url.query or "").strip()
                if query:
                    target = f"{target}?{query}"
                else:
                    target = f"{target}?run_id={urllib.parse.quote(normalized_run_id, safe='')}"
                return RedirectResponse(target, status_code=307)
    if resolved_section == "channel-loop":
        workspace = dict(status.get("workspace") or {})
        product = build_product_service(container)
        pack = product.channel_loop_pack(
            principal_id=context.principal_id,
            operator_id=str(context.operator_id or "").strip(),
        )
        product.record_surface_event(
            principal_id=context.principal_id,
            event_type="channel_loop_opened",
            surface="channel_loop",
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        )
        stats = [
            {"label": "Memo items", "value": str(int(dict(pack.get("stats") or {}).get("memo_items") or 0))},
            {"label": "Pending drafts", "value": str(int(dict(pack.get("stats") or {}).get("pending_drafts") or 0))},
            {"label": "Commitments", "value": str(int(dict(pack.get("stats") or {}).get("open_commitments") or 0))},
            {"label": "Handoffs", "value": str(int(dict(pack.get("stats") or {}).get("open_handoffs") or 0))},
            {"label": "Decisions", "value": str(int(dict(pack.get("stats") or {}).get("open_decisions") or 0))},
        ]
        return _render_public_template(
            request,
            "console_shell.html",
            **_console_shell_context(
                request=request,
                page_title=f"{request_brand(request)['name']} Inline Loop",
                current_nav="today",
                context=context,
                console_title=str(pack.get("headline") or "Inline loop"),
                console_summary=str(pack.get("summary") or "Clear the compact office loop."),
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or "PropertyQuarry account"),
                cards=[
                    {
                        "eyebrow": "Inline loop",
                        "title": str(pack.get("headline") or "Inline loop"),
                        "body": str(pack.get("summary") or "Clear the compact office loop."),
                        "items": list(pack.get("items") or []),
                    },
                    *[
                        {
                            "eyebrow": "Channel digest",
                            "title": str(digest.get("headline") or "Channel digest"),
                            "body": " ".join(
                                part
                                for part in (
                                    str(digest.get("summary") or "").strip(),
                                    str(digest.get("preview_text") or "").strip(),
                                )
                                if part
                            ),
                            "items": list(digest.get("items") or []),
                        }
                        for digest in list(pack.get("digests") or [])
                    ],
                ],
                stats=stats,
            ),
        )
    property_sections = {"properties", "search", "shortlist", "agents", "alerts", "account", "billing"} if property_brand else set()
    core_sections = {"today", "queue", "commitments", "people", "evidence", "activity"}
    if not property_brand:
        core_sections.add("settings")
    if resolved_section in core_sections:
        product = build_product_service(container)
        surface_event = {
            "today": "memo_opened",
            "queue": "queue_opened",
            "commitments": "commitment_ledger_opened",
            "people": "people_graph_opened",
            "evidence": "evidence_opened",
            "activity": "operator_queue_opened",
            "settings": "rules_opened",
        }.get(resolved_section)
        if surface_event:
            product.record_surface_event(
                principal_id=context.principal_id,
                event_type=surface_event,
                surface=resolved_section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
        outcomes = product.workspace_outcomes(principal_id=context.principal_id) if resolved_section == "settings" else None
        payload = _workspace_section_payload(
            resolved_section,
            product.workspace_snapshot(
                principal_id=context.principal_id,
                operator_id=str(context.operator_id or "").strip(),
            ),
            diagnostics,
            outcomes,
            operator_id=str(context.operator_id or "").strip(),
            brand_key=request_brand(request)["key"],
        )
    else:
        property_payload_section = property_surface_aliases.get(resolved_section, resolved_section) if property_brand else resolved_section
        product = build_product_service(container)
        property_context = (
            _property_console_context(
                container=container,
                principal_id=context.principal_id,
                status=status,
                run_id=run_id,
                selected_agent_id=agent_id,
                surface_mode=resolved_section,
            )
            if resolved_section in property_sections or resolved_section == "properties"
            else None
        )
        if (
            property_brand
            and resolved_section == "properties"
            and not str(run_id or "").strip()
            and isinstance(property_context, dict)
        ):
            route_run = dict(property_context.get("run") or {}) if isinstance(property_context.get("run"), dict) else {}
            route_run_id = str(route_run.get("run_id") or "").strip()
            if not route_run_id:
                query = str(request.url.query or "").strip()
                target = "/app/search"
                if query:
                    target = f"{target}?{query}"
                return RedirectResponse(target, status_code=307)
        if property_context is not None and property_brand:
            property_context["surface_mode"] = current_nav
            if str(packet_missing or "").strip().lower() in {"1", "true", "yes"}:
                missing_ref = str(missing_candidate_ref or "").strip()
                recovery_query = {"packet_missing": "1"}
                if normalized_run_id:
                    recovery_query["run_id"] = normalized_run_id
                if missing_ref:
                    recovery_query["missing_candidate_ref"] = missing_ref
                recovery_href = f"/app/shortlist?{urllib.parse.urlencode(recovery_query)}#results-list"
                repair_task_ref = _property_queue_missing_research_packet_repair(
                    container=container,
                    principal_id=context.principal_id,
                    run_id=normalized_run_id,
                    candidate_ref=missing_ref,
                    recovery_url=recovery_href,
                )
                property_context["packet_recovery"] = {
                    "title": "Property page is being rebuilt",
                    "detail": (
                        "Repair queued for the missing property page. The shortlist below remains usable while "
                        "PropertyQuarry rebuilds or preserves a recovery receipt."
                        if repair_task_ref
                        else "That property page is not available from the current packet. The shortlist below remains usable while the run can be refreshed."
                    ),
                    "candidate_ref": missing_ref,
                    "run_id": normalized_run_id,
                    "queue_item_ref": repair_task_ref,
                    "action_href": recovery_href,
                    "action_label": "Stay on shortlist",
                    "tone": "warn",
                }
            if PropertySurfaceScope.for_section(resolved_section).section == "shortlist":
                with contextlib.suppress(Exception):
                    property_context["saved_shortlist_candidates"] = product.list_property_saved_shortlist_candidates(
                        principal_id=context.principal_id,
                    )
            if PropertySurfaceScope.for_section(resolved_section).wants_credit_digest:
                fleet_digest = product.cached_fleet_digest_payload(
                    principal_id=context.principal_id,
                    operator_key=str(context.operator_id or "").strip(),
                )
                digests = [dict(fleet_digest)] if fleet_digest else []
                property_context["channel_digests"] = digests
                property_context["fleet_digest"] = dict(fleet_digest or {})
                billing_truth = dict(property_context.get("billing_truth") or {})
                if billing_truth:
                    billing_truth["fleet_digest"] = dict(property_context.get("fleet_digest") or {})
                    property_context["billing_truth"] = billing_truth
        if (resolved_section in property_sections or resolved_section == "properties") and current_nav != "search":
            product.record_surface_event(
                principal_id=context.principal_id,
                event_type=f"{current_nav}_opened",
                surface=current_nav,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        if property_brand and resolved_section in property_sections:
            if property_context is not None and property_payload_section == "properties":
                property_context["selected_candidate_ref"] = str(candidate or "").strip()
            payload = _property_workspace_payload(
                property_payload_section,
                status=status,
                property_state=property_context or {},
            )
            if current_nav == "search":
                payload["title"] = "Search"
                payload["summary"] = "Build the brief, run the sweep, compare the results, and open the property that deserves a decision."
            elif current_nav == "account":
                payload["title"] = "Account"
                payload["summary"] = "Identity, plan, delivery, and editable defaults."
            elif current_nav == "billing":
                payload["title"] = "Billing"
                payload["summary"] = "Plan, checkout, and current allowance."
        else:
            payload = _app_section_payload(
                resolved_section,
                status,
                live_feed=_app_live_feed(container, principal_id=context.principal_id),
                property_context=property_context,
            )
    workspace = dict(status.get("workspace") or {})
    if property_brand and resolved_section in property_sections:
        property_template = "app/property_decision_workbench.html"
        return _render_public_template(
            request,
            property_template,
            **{
                **_console_shell_context(
                    request=request,
                    page_title=f"{request_brand(request)['name']} {payload['title']}",
                    current_nav=current_nav,
                    context=context,
                    console_title=str(payload["title"]),
                    console_summary=str(payload["summary"]),
                    nav_groups=nav_groups,
                    workspace_label=str(request_brand(request)["name"] or "PropertyQuarry"),
                    cards=list(payload.get("cards") or []),
                    stats=list(payload["stats"]),
                    console_form=dict(payload.get("console_form") or {}),
                ),
                **payload,
            },
        )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{request_brand(request)['name']} {payload['title']}",
            current_nav=current_nav,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=nav_groups,
            workspace_label=str(workspace.get("name") or "PropertyQuarry account"),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
            console_form=dict(payload.get("console_form") or {}),
        ),
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/policies", status_code=307)


@router.get("/admin/{section}", response_class=HTMLResponse)
def admin_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> HTMLResponse:
    allowed = {row["key"] for group in ADMIN_NAV_GROUPS for row in group["items"]}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="admin_section_not_found")
    operator_id = str(context.operator_id or "").strip()
    if not operator_id and context.auth_source == "loopback_no_auth":
        operator_id = _default_operator_id_for_browser(container, principal_id=context.principal_id)
    payload = _build_admin_section_payload(
        section,
        container=container,
        principal_id=context.principal_id,
        operator_id=operator_id,
    )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{request_brand(request)['name']} Admin {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=ADMIN_NAV_GROUPS,
            workspace_label="Operator Center",
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


@router.get("/setup")
def legacy_setup_redirect() -> RedirectResponse:
    return RedirectResponse("/register", status_code=307)


@router.get("/demo/brief")
def legacy_brief_redirect() -> RedirectResponse:
    return RedirectResponse("/app/queue", status_code=307)


@router.get("/channels/google")
def legacy_google_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/google", status_code=307)


@router.get("/channels/telegram")
def legacy_telegram_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/telegram", status_code=307)


@router.get("/channels/whatsapp")
def legacy_whatsapp_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/whatsapp", status_code=307)


@router.get("/app/commitments/candidates/{candidate_id}", response_class=HTMLResponse)
def commitment_candidate_review(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    brand = request_brand(request)
    nav_groups = app_nav_groups_for_brand(brand["key"])
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    candidate = product.get_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="commitment_candidate_opened",
        surface=f"candidate:{candidate_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_public_template(
        request,
        "app/commitment_candidate_review.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"{brand['name']} Review {candidate.title}",
                current_nav="queue",
                context=context,
                console_title="Review extracted commitment",
                console_summary="Edit the wording, due date, or ownership before this enters the commitment ledger.",
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or brand["workspace_label"]),
                cards=[],
                stats=[
                    {"label": "Confidence", "value": f"{int(candidate.confidence * 100)}%"},
                    {"label": "Counterparty", "value": candidate.counterparty or "None"},
                    {"label": "Suggested due", "value": candidate.suggested_due_at[:10] if candidate.suggested_due_at else "Open"},
                    {"label": "Status", "value": candidate.status.title()},
                ],
            ),
            "candidate": candidate,
        },
    )
