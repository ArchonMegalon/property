#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


DEFAULT_ROUTES = (
    "/app/properties",
    "/app/search",
    "/app/shortlist",
    "/app/agents",
    "/app/alerts",
    "/app/account",
    "/app/billing",
    "/app/settings/google",
    "/app/settings/access",
    "/app/settings/usage",
    "/app/settings/support",
    "/app/settings/trust",
    "/app/settings/invitations",
    "/app/research",
    "/app/properties/packets",
)
SEEDED_RESEARCH_DETAIL_ROUTE = "/app/research/perf-candidate-1020?run_id=run-gold-mobile"
SEED_FIXTURE_USER_AGENT = "PropertyQuarry-live-mobile-surface-smoke/1.0"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def route_is_research_detail(route: str) -> bool:
    route_path = str(route or "").split("?", 1)[0].strip().rstrip("/")
    return route_path.startswith("/app/research/") and route_path != "/app/research"


def routes_require_api_auth(routes: tuple[str, ...]) -> bool:
    return any(str(route or "").split("?", 1)[0].strip().startswith("/app/") for route in routes)


def seeded_research_detail_payload() -> dict[str, Any]:
    candidate = {
        "candidate_ref": "perf-candidate-1020",
        "rank": 1,
        "title": "Performance smoke apartment in 1020 Vienna",
        "source_label": "Willhaben | Austria | Rent | 1020 Vienna",
        "source_platform": "willhaben",
        "property_url": "https://example.invalid/propertyquarry/performance-smoke",
        "packet_url": "/app/research/perf-candidate-1020",
        "review_url": "/app/research/perf-candidate-1020",
        "fit_score": 91,
        "score": 91,
        "fit_summary": "Transit, area, layout and budget fit the seeded brief.",
        "match_reasons": ["1020 Vienna matches the seeded search area.", "The synthetic listing keeps route and layout data compact."],
        "mismatch_reasons": ["Operating-cost evidence still needs a provider document."],
        "saved_from_run_id": "run-gold-mobile",
        "property_facts": {
            "postal_code": "1020",
            "postal_name": "1020 Vienna",
            "district": "1020 Vienna",
            "price_display": "EUR 1,290",
            "price_eur": 1290,
            "area_m2": 72,
            "area_sqm": 72,
            "rooms": 3,
            "has_floorplan": True,
            "has_balcony": True,
            "operating_costs_status": "missing",
            "listing_fact_confirmation": {
                "status": "confirmed",
                "label": "Facts confirmed",
                "summary": "4 listing facts confirmed automatically from provider evidence.",
                "fields": ["area", "location", "price", "rooms"],
                "requires_manual_confirmation": False,
            },
        },
        "route_evidence": [
            {"label": "Transit", "distance": "350 m", "icon": "U"},
            {"label": "School", "distance": "650 m", "icon": "S"},
        ],
    }
    return {
        "country_code": "AT",
        "language_code": "en",
        "listing_mode": "rent",
        "property_type": "apartment",
        "location_query": "1020 Vienna",
        "selected_platforms": ["willhaben"],
        "saved_shortlist_candidates": [candidate],
    }


def _seed_research_detail_headers(*, base_url: str, api_token: str, principal_id: str, host_header: str = "") -> dict[str, str]:
    parsed_base = urllib.parse.urlparse(str(base_url or "").strip())
    origin = urllib.parse.urlunparse((parsed_base.scheme or "https", parsed_base.netloc, "", "", "", "")).rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": SEED_FIXTURE_USER_AGENT,
        "X-EA-Principal-ID": principal_id,
    }
    if origin:
        headers["Origin"] = origin
        headers["Referer"] = f"{origin}/app/search"
    if host_header:
        headers["Host"] = host_header
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
    return headers


def seed_research_detail_fixture(*, base_url: str, api_token: str, principal_id: str, host_header: str = "") -> str:
    headers = _seed_research_detail_headers(
        base_url=base_url,
        api_token=api_token,
        principal_id=principal_id,
        host_header=host_header,
    )
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/onboarding/property-search/preferences",
        data=json.dumps(seeded_research_detail_payload()).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        status_code = int(getattr(response, "status", 0) or 0)
        if status_code != 200:
            raise RuntimeError(f"seed_research_detail_fixture_failed:{status_code}")
        response.read(4096)
    return SEEDED_RESEARCH_DETAIL_ROUTE


def build_mobile_coverage_checks(
    routes: tuple[str, ...],
    *,
    require_research_detail: bool = False,
) -> list[dict[str, Any]]:
    normalized_routes = {_normalize_route_for_coverage(route) for route in routes}
    checks: list[dict[str, Any]] = []
    if require_research_detail:
        checks.append(
            {
                "name": "research_detail_route_configured",
                "ok": any(route_is_research_detail(route) for route in routes),
                "required_route_prefix": "/app/research/",
                "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
            }
        )
    checks.extend(_registry_mobile_surface_coverage_checks(routes=routes, normalized_routes=normalized_routes, require_research_detail=require_research_detail))
    return checks


def _normalize_route_for_coverage(route: str) -> str:
    normalized = str(route or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return normalized or "/"


def _route_pattern_is_mobile_app_surface(route_pattern: str) -> bool:
    normalized = str(route_pattern or "").strip()
    if normalized.startswith("/app/api/"):
        return False
    return normalized.startswith("/app/") or normalized == "/app"


def _route_pattern_is_covered(route_pattern: str, routes: tuple[str, ...], normalized_routes: set[str]) -> bool:
    normalized_pattern = _normalize_route_for_coverage(route_pattern)
    if not _route_pattern_is_mobile_app_surface(normalized_pattern):
        return False
    if ":" not in normalized_pattern:
        return normalized_pattern in normalized_routes
    if normalized_pattern.startswith("/app/research/:candidate_ref"):
        return any(route_is_research_detail(route) for route in routes)
    return False


def _registry_mobile_surface_coverage_checks(
    *,
    routes: tuple[str, ...],
    normalized_routes: set[str],
    require_research_detail: bool,
) -> list[dict[str, Any]]:
    try:
        from app.product.property_surface_registry import all_property_surfaces
    except Exception as exc:  # pragma: no cover - protects standalone use without PYTHONPATH.
        return [
            {
                "name": "registry_mobile_surface_coverage",
                "ok": False,
                "reason": f"Could not import PropertyQuarry surface registry: {type(exc).__name__}",
            }
        ]
    missing: list[str] = []
    covered: list[str] = []
    for surface in all_property_surfaces():
        if not bool(getattr(surface, "customer_visible", True)):
            continue
        route_patterns = tuple(str(route or "") for route in getattr(surface, "routes", ()) if _route_pattern_is_mobile_app_surface(str(route or "")))
        if not route_patterns:
            continue
        has_dynamic_research_route = any(_normalize_route_for_coverage(pattern).startswith("/app/research/:candidate_ref") for pattern in route_patterns)
        if has_dynamic_research_route and not require_research_detail:
            continue
        if any(_route_pattern_is_covered(pattern, routes, normalized_routes) for pattern in route_patterns):
            covered.append(str(getattr(surface, "key", "")))
        else:
            missing.append(str(getattr(surface, "key", "")))
    return [
        {
            "name": "registry_mobile_customer_surfaces_covered",
            "ok": not missing,
            "covered_surface_count": len([key for key in covered if key]),
            "missing_surface_keys": [key for key in missing if key],
            "reason": "Live mobile smoke routes must cover every customer-visible /app surface declared in the PropertyQuarry surface registry.",
        }
    ]


def _route_expectations(route: str) -> dict[str, Any]:
    route_path = str(route or "").split("?", 1)[0].strip()
    if route == "/app/search":
        return {"needs_district_picker": True}
    if route_path == "/app/account":
        return {"needs_single_logout": True}
    if route_path.startswith("/app/research/"):
        return {"needs_research_detail": True}
    return {}


def evaluate_mobile_metrics(route: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    if str(route or "").split("?", 1)[0].strip() == "/app/billing" and int(metrics.get("status_code") or 0) in {303, 307}:
        redirect_location = str(metrics.get("redirect_location") or "").strip()
        return [
            {"name": "billing_external_handoff", "ok": redirect_location.startswith("https://") and "/app/billing" not in redirect_location},
            {"name": "billing_local_page_deleted", "ok": True},
        ]
    if str(route or "").split("?", 1)[0].strip() == "/app/billing" and int(metrics.get("status_code") or 0) == 503:
        billing_text = str(metrics.get("billing_visible_text") or "").strip().lower()
        return [
            {"name": "billing_fail_closed_recovery", "ok": all(marker in billing_text for marker in ("billing handoff unavailable", "external account lane", "propertyquarry access remains active"))},
            {"name": "billing_local_page_deleted", "ok": not any(marker in billing_text for marker in ("open pricing", "compare plans", "plus checkout", "billing history"))},
        ]
    expectations = _route_expectations(route)
    viewport_width = int(metrics.get("viewport_width") or 0)
    body_width = int(metrics.get("body_width") or 0)
    topbar_height = int(metrics.get("topbar_height") or 0)
    min_action_height = float(metrics.get("min_action_height") or 0)
    checks = [
        {"name": "status_200", "ok": int(metrics.get("status_code") or 0) == 200},
        {"name": "no_horizontal_overflow", "ok": bool(viewport_width) and body_width <= viewport_width + 1},
        {"name": "compact_topbar", "ok": 0 < topbar_height <= 76},
        {"name": "shared_top_navigation", "ok": bool(metrics.get("topnav_visible"))},
        {"name": "primary_touch_targets", "ok": min_action_height >= 44},
        {"name": "card_density", "ok": int(metrics.get("visible_card_count") or 0) <= 26},
        {"name": "low_shadow_noise", "ok": int(metrics.get("heavy_shadow_count") or 0) <= 2},
    ]
    if expectations.get("needs_district_picker"):
        checks.extend(
            (
                {"name": "district_picker_available", "ok": bool(metrics.get("district_picker_available"))},
                {"name": "district_map_popup_available", "ok": bool(metrics.get("district_map_popup_available"))},
                {"name": "district_list_not_visible_in_map_mode", "ok": bool(metrics.get("district_list_hidden_in_map_mode"))},
                {"name": "district_map_modal_opens", "ok": bool(metrics.get("district_map_modal_opened"))},
                {"name": "district_map_click_selects_shape", "ok": bool(metrics.get("district_map_click_selected"))},
                {"name": "district_map_zoom_toggle_changes_scale", "ok": bool(metrics.get("district_map_zoom_changed"))},
                {"name": "district_map_pinch_zoom_changes_scale", "ok": bool(metrics.get("district_map_pinch_zoom_changed"))},
                {"name": "district_map_close_restores_scroll", "ok": bool(metrics.get("district_map_close_restored_scroll"))},
                {"name": "mobile_what_matters_single_open_section", "ok": bool(metrics.get("mobile_what_matters_single_open"))},
            )
        )
    if expectations.get("needs_single_logout"):
        account_menu_present = bool(metrics.get("account_menu_present"))
        account_logout_strip_visible = bool(metrics.get("account_logout_strip_visible"))
        checks.extend(
            (
                {"name": "account_logout_strip_visible", "ok": account_logout_strip_visible},
                {"name": "single_logout_action", "ok": int(metrics.get("logout_button_count") or 0) == 1},
                {"name": "account_menu_mobile_sheet", "ok": bool(metrics.get("account_menu_mobile_sheet")) or (account_logout_strip_visible and not account_menu_present)},
                {"name": "account_menu_trigger_compact", "ok": bool(metrics.get("account_menu_trigger_compact")) or (account_logout_strip_visible and not account_menu_present)},
            )
        )
    if expectations.get("needs_research_detail"):
        checks.extend(
            (
                {"name": "research_detail_workspace", "ok": bool(metrics.get("research_detail_workspace"))},
                {"name": "research_detail_decision_after_aside", "ok": bool(metrics.get("research_detail_decision_after_aside"))},
                {"name": "research_detail_media_stage", "ok": bool(metrics.get("research_detail_media_stage"))},
                {"name": "research_detail_visual_controls", "ok": bool(metrics.get("research_detail_visual_controls"))},
                {"name": "research_detail_no_fake_visual_ready", "ok": not bool(metrics.get("research_detail_fake_visual_ready"))},
                {"name": "research_detail_generated_reconstruction_honest", "ok": bool(metrics.get("research_detail_generated_reconstruction_honest"))},
                {"name": "research_detail_verified_tour_evidence_copy", "ok": bool(metrics.get("research_detail_verified_tour_evidence_copy"))},
                {"name": "research_detail_walkthrough_evidence_copy", "ok": bool(metrics.get("research_detail_walkthrough_evidence_copy"))},
                {"name": "research_detail_no_vague_visual_copy", "ok": bool(metrics.get("research_detail_no_vague_visual_copy"))},
                {"name": "research_detail_walkthrough_magicfit_only", "ok": bool(metrics.get("research_detail_walkthrough_magicfit_only"))},
                {"name": "research_detail_no_walkthrough_provider_chooser", "ok": bool(metrics.get("research_detail_no_walkthrough_provider_chooser"))},
                {"name": "research_detail_no_legacy_walkthrough_providers", "ok": bool(metrics.get("research_detail_no_legacy_walkthrough_providers"))},
            )
        )
    return checks


def _collect_metrics_script() -> str:
    return """
    () => {
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const visibleNodes = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
      const topbar = document.querySelector('[data-property-research-topnav], .pqx-topbar, .prd-topbar');
      const topnav = document.querySelector('nav[aria-label="PropertyQuarry sections"]');
      const mobileNavMenu = document.querySelector('[data-pqx-mobile-nav-menu] > summary, .pq-appbar-mobile-nav');
      const actionNodes = visibleNodes('main button, main a.pqx-button, main a.pqx-link-button, main a.pq-pack-button, main .console-action, .pqx-account-logout-strip button, .pqx-account-logout-strip a');
      const actionHeights = actionNodes.map((node) => node.getBoundingClientRect().height).filter((height) => height > 0);
      const cardNodes = visibleNodes('.pqx-card, .pqx-panel, .pqx-result, .pqx-account-action-card, .pqx-billing-card, .pqx-billing-summary-card, .pqx-automation-card, .prd-panel, .prd-band');
      const heavyShadowNodes = cardNodes.filter((node) => window.getComputedStyle(node).boxShadow !== 'none');
      const locationField = document.querySelector('[data-property-field-name="location_query"]');
      const availableScrollY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const requestedScrollY = Math.min(220, availableScrollY);
      window.scrollTo(0, requestedScrollY);
      const pageScrollBeforeMap = Math.round(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0);
      const mapButton = locationField?.querySelector('[data-location-mode-button="map"]') || null;
      if (mapButton) mapButton.click();
      const locationGrid = locationField?.querySelector('[data-pqx-check-grid="location_query"]') || null;
      const mapOpen = locationField?.querySelector('[data-location-map-open]') || null;
      const dialog = locationField?.querySelector('[data-location-map-dialog]') || null;
      if (mapOpen) mapOpen.click();
      const firstDistrict = dialog?.querySelector('[data-location-map-district]') || null;
      const firstValue = String(firstDistrict?.getAttribute('data-location-value') || '').trim();
      const firstInput = firstValue ? locationField?.querySelector(`input[name="location_query"][value="${CSS.escape(firstValue)}"]`) : null;
      const districtWasChecked = Boolean(firstInput?.checked);
      if (firstDistrict) {
        const rect = firstDistrict.getBoundingClientRect();
        firstDistrict.dispatchEvent(new MouseEvent('click', {
          bubbles: true,
          cancelable: true,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2
        }));
      }
      const districtIsChecked = Boolean(firstInput?.checked);
      const mapLayer = dialog?.querySelector('[data-location-map-layer]') || null;
      const initialTransform = String(mapLayer?.getAttribute('transform') || '');
      const zoomToggle = dialog?.querySelector('[data-location-map-zoom="reset"]') || null;
      if (zoomToggle) zoomToggle.click();
      const zoomedTransform = String(mapLayer?.getAttribute('transform') || '');
      if (zoomToggle) zoomToggle.click();
      const parseScale = (transform) => {
        const match = String(transform || '').match(/scale\\(([^)]+)\\)/i);
        const value = match ? Number(match[1]) : 0;
        return Number.isFinite(value) ? value : 0;
      };
      let pinchZoomChanged = false;
      const mapViewport = dialog?.querySelector('[data-location-map-viewport]') || null;
      if (mapViewport && mapLayer && typeof PointerEvent === 'function') {
        const viewportRect = mapViewport.getBoundingClientRect();
        const centerX = viewportRect.left + (viewportRect.width / 2);
        const centerY = viewportRect.top + (viewportRect.height / 2);
        const beforePinch = String(mapLayer.getAttribute('transform') || '');
        const dispatchPinchPointer = (type, pointerId, clientX, clientY, isPrimary) => {
          mapViewport.dispatchEvent(new PointerEvent(type, {
            bubbles: true,
            cancelable: true,
            composed: true,
            pointerId,
            pointerType: 'touch',
            isPrimary,
            clientX,
            clientY,
          }));
        };
        dispatchPinchPointer('pointerdown', 1, centerX - 26, centerY, true);
        dispatchPinchPointer('pointerdown', 2, centerX + 26, centerY, false);
        dispatchPinchPointer('pointermove', 1, centerX - 58, centerY, true);
        dispatchPinchPointer('pointermove', 2, centerX + 58, centerY, false);
        dispatchPinchPointer('pointerup', 1, centerX - 58, centerY, true);
        dispatchPinchPointer('pointerup', 2, centerX + 58, centerY, false);
        const afterPinch = String(mapLayer.getAttribute('transform') || '');
        pinchZoomChanged = parseScale(afterPinch) > parseScale(beforePinch) + 0.08;
      }
      const closeButton = dialog?.querySelector('[data-location-map-close]') || null;
      const modalOpened = Boolean(dialog?.open) || document.documentElement.dataset.pqxLocationMapOpen === 'true';
      const htmlOverflowOpen = document.documentElement.style.overflow || '';
      const bodyOverflowOpen = document.body.style.overflow || '';
      const bodyPositionOpen = document.body.style.position || '';
      const bodyTopOpen = document.body.style.top || '';
      if (closeButton) closeButton.click();
      const pageScrollAfterClose = Math.round(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0);
      const modalClosed = !(dialog?.open)
        && document.documentElement.dataset.pqxLocationMapOpen !== 'true'
        && document.documentElement.style.overflow !== 'hidden'
        && document.body.style.overflow !== 'hidden'
        && Math.abs(pageScrollAfterClose - pageScrollBeforeMap) <= 2;
      const whatMatters = document.querySelector('[data-property-what-matters-panel]');
      const whatMatterGroups = Array.from(whatMatters?.querySelectorAll('details[data-what-matters-group]') || []);
      let singleOpen = true;
      if (whatMatterGroups.length >= 2) {
        whatMatterGroups[0].open = true;
        whatMatterGroups[0].dispatchEvent(new Event('toggle'));
        whatMatterGroups[1].open = true;
        whatMatterGroups[1].dispatchEvent(new Event('toggle'));
        singleOpen = whatMatterGroups.filter((node) => node.open).length === 1 && whatMatterGroups[1].open;
      }
      const logoutButtons = visibleNodes('button, a').filter((node) => String(node.textContent || '').trim() === 'Log out');
      const accountMenu = document.querySelector('.account-menu, .pqx-account-menu');
      const accountSummary = accountMenu?.querySelector('summary') || null;
      if (accountSummary && !accountMenu.open) accountSummary.click();
      const accountPanel = accountMenu?.querySelector('.account-menu-panel') || null;
      const accountSummaryRect = accountSummary?.getBoundingClientRect();
      const accountPanelStyle = accountPanel ? window.getComputedStyle(accountPanel) : null;
      const accountPanelRect = accountPanel?.getBoundingClientRect();
      const decisionWorkspace = document.querySelector('.prd-decision-workspace');
      const firstAside = document.querySelector('aside');
      const mediaStage = document.querySelector('[data-object-media-stage]');
      const visualControls = visibleNodes('[data-pw-visual-request], [data-object-magicfit-generate], [data-object-magicfit-toggle]');
      const bodyText = String(document.body?.textContent || '').toLowerCase();
      const pageHtml = String(document.documentElement?.innerHTML || '').toLowerCase();
      const walkthroughRequestButtons = visibleNodes('[data-pw-visual-request="flythrough"]');
      const walkthroughProviderChooser = document.querySelector('[data-pw-walkthrough-provider-select]');
      const walkthroughMagicfitOnly = walkthroughRequestButtons.length > 0 && walkthroughRequestButtons.every((node) => (
        String(node.getAttribute('data-pw-walkthrough-provider') || '').trim().toLowerCase() === 'magicfit'
      ));
      const generatedReconstructionCard = document.querySelector('[data-prd-visual-card="generated_reconstruction"]');
      const generatedReconstructionHonest = !generatedReconstructionCard || (
        bodyText.includes('not a verified provider capture')
        && bodyText.includes('build verified 3d tour')
        && Boolean(document.querySelector('[data-pw-visual-request="tour"]'))
      );
      const verifiedTourEvidenceCopy = (
        bodyText.includes('evidence: verified matterport control')
        || bodyText.includes('evidence: verified 3dvista control')
        || bodyText.includes('evidence: verified pano2vr control')
        || bodyText.includes('evidence: verified krpano control')
        || bodyText.includes('no verified 3d tour is published yet')
        || bodyText.includes('a matterport, 3dvista, pano2vr, or licensed krpano capture is still needed')
      );
      const walkthroughEvidenceCopy = (
        bodyText.includes('open walkthrough')
        || bodyText.includes('walkthrough is ready')
        || bodyText.includes('rendered walkthrough is ready')
        || bodyText.includes('no playable walkthrough is published yet')
        || bodyText.includes('a verified rendered video is still needed')
      );
      const vagueVisualCopy = (
        bodyText.includes('more source material is still needed before this 3d tour can be built')
        || bodyText.includes('more source material is still needed before this walkthrough can be built')
        || bodyText.includes('more source material is still needed before this visual can be built')
        || bodyText.includes('more source material is needed first')
      );
      return {
        body_width: document.documentElement.scrollWidth,
        viewport_width: window.innerWidth,
        topbar_height: topbar ? Math.round(topbar.getBoundingClientRect().height) : 0,
        topnav_visible: visible(topnav) || visible(mobileNavMenu),
        min_action_height: actionHeights.length ? Math.min(...actionHeights) : 44,
        visible_card_count: cardNodes.length,
        heavy_shadow_count: heavyShadowNodes.length,
        district_picker_available: Boolean(locationField),
        district_map_popup_available: visible(mapOpen),
        district_list_hidden_in_map_mode: locationGrid ? window.getComputedStyle(locationGrid).display === 'none' : false,
        district_map_modal_opened: modalOpened,
        district_map_click_selected: Boolean(firstDistrict && firstInput && districtIsChecked !== districtWasChecked),
        district_map_zoom_changed: Boolean(zoomToggle && mapLayer && zoomedTransform !== initialTransform && zoomedTransform.includes('scale(')),
        district_map_pinch_zoom_changed: pinchZoomChanged,
        district_map_close_restored_scroll: Boolean(!dialog || modalClosed),
        district_map_lock_open: htmlOverflowOpen === 'hidden' && bodyOverflowOpen === 'hidden' && bodyPositionOpen === 'fixed' && bodyTopOpen.startsWith('-'),
        mobile_what_matters_single_open: singleOpen,
        account_logout_strip_visible: visible(document.querySelector('.pqx-account-logout-strip')),
        logout_button_count: logoutButtons.length,
        account_menu_present: Boolean(accountMenu),
        account_menu_mobile_sheet: Boolean(accountPanel && accountPanelStyle?.position === 'fixed' && accountPanelRect && accountPanelRect.width >= window.innerWidth - 24),
        account_menu_trigger_compact: Boolean(accountSummaryRect && accountSummaryRect.width <= 58),
        research_detail_workspace: visible(decisionWorkspace),
        research_detail_decision_after_aside: Boolean(decisionWorkspace && firstAside && (firstAside.compareDocumentPosition(decisionWorkspace) & Node.DOCUMENT_POSITION_FOLLOWING)),
        research_detail_media_stage: visible(mediaStage),
        research_detail_visual_controls: visualControls.length > 0,
        research_detail_fake_visual_ready: bodyText.includes('fake 3d') || bodyText.includes('fake tour') || bodyText.includes('placeholder 3d') || bodyText.includes('placeholder tour'),
        research_detail_generated_reconstruction_honest: generatedReconstructionHonest,
        research_detail_verified_tour_evidence_copy: verifiedTourEvidenceCopy,
        research_detail_walkthrough_evidence_copy: walkthroughEvidenceCopy,
        research_detail_no_vague_visual_copy: !vagueVisualCopy,
        research_detail_walkthrough_magicfit_only: walkthroughMagicfitOnly,
        research_detail_no_walkthrough_provider_chooser: !walkthroughProviderChooser && !pageHtml.includes('data-pw-walkthrough-provider-select'),
        research_detail_no_legacy_walkthrough_providers: !pageHtml.includes('mootion') && !pageHtml.includes('omagic'),
      };
    }
    """


def build_live_mobile_surface_receipt(
    *,
    base_url: str,
    api_token: str,
    principal_id: str,
    host_header: str = "",
    routes: tuple[str, ...] = DEFAULT_ROUTES,
    require_research_detail: bool = False,
    viewport_width: int = 390,
    viewport_height: int = 844,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    if routes_require_api_auth(routes) and not str(api_token or "").strip():
        return {
            "status": "blocked",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": base_url,
            "host_header": host_header,
            "navigation_base_url": base_url,
            "principal_id": principal_id,
            "viewport": {"width": viewport_width, "height": viewport_height},
            "route_count": 0,
            "failed_count": 1,
            "coverage_checks": [
                {
                    "name": "api_token_present_for_app_routes",
                    "ok": False,
                    "reason": "Live mobile app-surface smoke requires EA_API_TOKEN or --api-token; otherwise protected pages render sign-in redirects instead of the app UI.",
                }
            ],
            "routes": [],
            "notes": [
                "Live mobile smoke checks deployed HTML geometry only; it does not call listing providers.",
                "API token values are never written to this receipt.",
            ],
        }
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - exercised when optional dependency is absent.
        return {
            "status": "blocked",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": f"playwright_unavailable:{type(exc).__name__}: {exc}",
            "routes": [],
            "failed_count": 1,
        }

    headers = {
        "X-EA-Principal-ID": principal_id,
        "Accept": "text/html,application/xhtml+xml",
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
    browser_args: list[str] = []
    navigation_base_url = base_url
    normalized_host_header = str(host_header or "").strip()
    if normalized_host_header:
        parsed_base = urllib.parse.urlparse(base_url)
        original_host = str(parsed_base.hostname or "").strip()
        branded_host = normalized_host_header.split(":", 1)[0].strip()
        if branded_host:
            branded_netloc = normalized_host_header
            if ":" not in branded_netloc and parsed_base.port:
                branded_netloc = f"{branded_host}:{parsed_base.port}"
            navigation_base_url = urllib.parse.urlunparse(parsed_base._replace(netloc=branded_netloc))
            if original_host and original_host != branded_host:
                browser_args.append(f"--host-resolver-rules=MAP {branded_host} {original_host}")
    rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=browser_args)
        try:
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                is_mobile=True,
                has_touch=True,
                extra_http_headers=headers,
            )
            for route in routes:
                url = navigation_base_url.rstrip("/") + "/" + route.lstrip("/")
                if str(route or "").split("?", 1)[0].strip() == "/app/billing":
                    request_url = base_url.rstrip("/") + "/" + route.lstrip("/")
                    request_headers = {"Host": normalized_host_header} if normalized_host_header else {}
                    try:
                        response = context.request.get(request_url, headers=request_headers, max_redirects=0, timeout=timeout_ms)
                        status_code = int(response.status)
                        billing_text = ""
                        if status_code == 503:
                            try:
                                billing_text = str(response.text() or "")
                            except Exception:
                                billing_text = ""
                        metrics = {
                            "status_code": status_code,
                            "viewport_width": viewport_width,
                            "body_width": viewport_width,
                            "topbar_height": 0,
                            "min_action_height": 44,
                            "redirect_location": str(response.headers.get("location") or ""),
                            "billing_visible_text": billing_text,
                        }
                        checks = evaluate_mobile_metrics(route, metrics)
                        rows.append(
                            {
                                "route": route,
                                "url": url,
                                "status_code": status_code,
                                "ok": all(bool(check.get("ok")) for check in checks),
                                "checks": checks,
                                "metrics": metrics,
                            }
                        )
                    except Exception as exc:
                        metrics = {
                            "status_code": 0,
                            "viewport_width": viewport_width,
                            "body_width": 0,
                            "topbar_height": 0,
                            "min_action_height": 0,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        checks = evaluate_mobile_metrics(route, metrics)
                        rows.append(
                            {
                                "route": route,
                                "url": url,
                                "status_code": 0,
                                "ok": False,
                                "checks": checks,
                                "metrics": metrics,
                            }
                        )
                    continue
                page = context.new_page()
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(350)
                    status_code = int(response.status) if response is not None else 0
                    metrics = dict(page.evaluate(_collect_metrics_script()) or {})
                    metrics["status_code"] = status_code
                    checks = evaluate_mobile_metrics(route, metrics)
                    rows.append(
                        {
                            "route": route,
                            "url": url,
                            "status_code": status_code,
                            "ok": all(bool(check.get("ok")) for check in checks),
                            "checks": checks,
                            "metrics": metrics,
                        }
                    )
                except Exception as exc:
                    metrics = {
                        "status_code": 0,
                        "viewport_width": viewport_width,
                        "body_width": 0,
                        "topbar_height": 0,
                        "min_action_height": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    checks = evaluate_mobile_metrics(route, metrics)
                    rows.append(
                        {
                            "route": route,
                            "url": url,
                            "status_code": 0,
                            "ok": False,
                            "checks": checks,
                            "metrics": metrics,
                        }
                    )
                finally:
                    page.close()
            context.close()
        finally:
            browser.close()
    failed = [row for row in rows if not row.get("ok")]
    coverage_checks = build_mobile_coverage_checks(routes, require_research_detail=require_research_detail)
    failed_coverage = [row for row in coverage_checks if not row.get("ok")]
    return {
        "status": "pass" if not failed and not failed_coverage else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "host_header": host_header,
        "navigation_base_url": navigation_base_url,
        "principal_id": principal_id,
        "viewport": {"width": viewport_width, "height": viewport_height},
        "route_count": len(rows),
        "failed_count": len(failed) + len(failed_coverage),
        "coverage_checks": coverage_checks,
        "routes": rows,
        "notes": [
            "Live mobile smoke checks deployed HTML geometry only; it does not call listing providers.",
            "API token values are never written to this receipt.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live mobile UI smoke against PropertyQuarry app surfaces.")
    parser.add_argument("--base-url", default=_env("PROPERTYQUARRY_LIVE_BASE_URL", "http://localhost:8097"))
    parser.add_argument("--host-header", default=_env("PROPERTYQUARRY_LIVE_HOST_HEADER"))
    parser.add_argument("--api-token", default=_env("PROPERTYQUARRY_LIVE_API_TOKEN") or _env("EA_API_TOKEN"))
    parser.add_argument("--principal-id", default=_env("PROPERTYQUARRY_LIVE_PRINCIPAL_ID", "pq-live-mobile-smoke"))
    configured_research_detail = _env("PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE")
    default_routes = (*DEFAULT_ROUTES, configured_research_detail) if configured_research_detail else DEFAULT_ROUTES
    parser.add_argument("--routes", default=",".join(default_routes))
    parser.add_argument(
        "--require-research-detail",
        action="store_true",
        default=_env_flag("PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_REQUIRED"),
        help="Fail unless routes include a current /app/research/{id} detail URL.",
    )
    parser.add_argument(
        "--seed-research-detail-fixture",
        action="store_true",
        default=_env_flag("PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_SEED_FIXTURE"),
        help="Seed a deterministic saved research-detail candidate for the smoke principal and include it in the route set.",
    )
    parser.add_argument("--viewport", default="390x844")
    parser.add_argument("--timeout-ms", type=int, default=int(_env("PROPERTYQUARRY_LIVE_MOBILE_TIMEOUT_MS", "30000") or 30000))
    parser.add_argument("--write", default="_completion/smoke/property-live-mobile-surface-latest.json")
    args = parser.parse_args()

    width_text, _, height_text = str(args.viewport).lower().partition("x")
    width = int(width_text or 390)
    height = int(height_text or 844)
    routes_list = [route.strip() for route in str(args.routes or "").split(",") if route.strip()]
    seeded_route = ""
    if args.seed_research_detail_fixture:
        seeded_route = seed_research_detail_fixture(
            base_url=str(args.base_url).strip(),
            api_token=str(args.api_token or "").strip(),
            principal_id=str(args.principal_id or "").strip() or "pq-live-mobile-smoke",
            host_header=str(args.host_header or "").strip(),
        )
        if seeded_route not in routes_list:
            routes_list.append(seeded_route)
        args.require_research_detail = True
    routes = tuple(routes_list)
    receipt = build_live_mobile_surface_receipt(
        base_url=str(args.base_url).strip(),
        api_token=str(args.api_token or "").strip(),
        principal_id=str(args.principal_id or "").strip() or "pq-live-mobile-smoke",
        host_header=str(args.host_header or "").strip(),
        routes=routes or DEFAULT_ROUTES,
        require_research_detail=bool(args.require_research_detail),
        viewport_width=width,
        viewport_height=height,
        timeout_ms=max(1, int(args.timeout_ms or 30000)),
    )
    if seeded_route:
        receipt["seeded_research_detail_route"] = seeded_route
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
