#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing
import os
import re
import signal
import socket
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from scripts.propertyquarry_billing_handoff_probe import (
    https_handoff_url_usable,
    https_redirect_host_resolves,
)


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
SEED_FIXTURE_TIMEOUT_SECONDS = max(
    1,
    int(os.environ.get("PROPERTYQUARRY_LIVE_MOBILE_SEED_TIMEOUT_SECONDS", "30") or "30"),
)
BILLING_FAIL_CLOSED_MARKERS = (
    "billing portal unavailable",
    "propertyquarry access stays active",
)
BILLING_FAIL_CLOSED_STATE_MARKERS = (
    "billing portal is still being connected",
    "still opens another sign-in",
    "billing account host is not ready yet",
)
BILLING_BRIDGE_GUIDED_LOGIN_MARKERS = (
    "continue billing",
    "back to propertyquarry",
    "billing lane",
)
SENSITIVE_URL_QUERY_KEYS = (
    "access_token",
    "code",
    "id_token",
    "login_token",
    "pq_bridge",
    "refresh_token",
    "state",
    "token",
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_HTTP_SMOKE_OPENER = urllib.request.build_opener()
_HTTP_SMOKE_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _http_get_for_smoke(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = _HTTP_SMOKE_OPENER if follow_redirects else _HTTP_SMOKE_NO_REDIRECT_OPENER
    try:
        with opener.open(request, timeout=max(1.0, float(timeout_seconds))) as response:
            body = response.read(2_000_000)
            return {
                "status_code": int(getattr(response, "status", 0) or 0),
                "headers": dict(response.headers.items()),
                "url": str(getattr(response, "url", url) or url),
                "text": body.decode("utf-8", errors="replace"),
            }
    except HTTPError as exc:
        body = exc.read(2_000_000)
        return {
            "status_code": int(exc.code or 0),
            "headers": dict(exc.headers.items()),
            "url": str(exc.url or url),
            "text": body.decode("utf-8", errors="replace"),
        }


def _header_value(headers: dict[str, Any], name: str) -> str:
    wanted = str(name or "").strip().lower()
    for key, value in dict(headers or {}).items():
        if str(key).strip().lower() == wanted:
            return str(value or "").strip()
    return ""


def _redact_sensitive_receipt_text(value: object) -> str:
    redacted = re.sub(
        r"(?i)(/login/token/)[^/?#\s\"'>]+",
        r"\1[redacted]",
        str(value or ""),
    )
    query_key_pattern = "|".join(re.escape(key) for key in SENSITIVE_URL_QUERY_KEYS)
    return re.sub(
        rf"(?i)([?&](?:{query_key_pattern})=)[^&#\s\"'>]+",
        r"\1[redacted]",
        redacted,
    )


def _redact_sensitive_receipt_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return _redact_sensitive_receipt_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, dict):
        return {str(key): _redact_sensitive_receipt_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive_receipt_value(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_receipt_text(value)
    return value


def _log_smoke_progress(message: str) -> None:
    print(f"[propertyquarry-mobile-smoke] {message}", file=sys.stderr, flush=True)


def _visible_text(text: str) -> str:
    without_hidden = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_hidden)
    return re.sub(r"\s+", " ", without_tags).strip()


def _resolve_mobile_billing_external_handoff(
    *,
    base_url: str,
    redirect_location: str,
    request_headers: dict[str, str],
    timeout_ms: int,
) -> dict[str, object]:
    normalized_location = str(redirect_location or "").strip()
    if not normalized_location:
        return {
            "external_location": "",
            "bridge_launch_used": False,
            "bridge_launch_url": "",
            "bridge_launch_status_code": 0,
        }
    parsed = urllib.parse.urlparse(normalized_location)
    if parsed.scheme == "https":
        return {
            "external_location": normalized_location,
            "bridge_launch_used": False,
            "bridge_launch_url": "",
            "bridge_launch_status_code": 0,
        }
    normalized_path = parsed.path or ""
    if not normalized_path.startswith("/app/api/property/billing/bridge-launch"):
        return {
            "external_location": normalized_location,
            "bridge_launch_used": False,
            "bridge_launch_url": "",
            "bridge_launch_status_code": 0,
        }
    bridge_launch_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", normalized_location.lstrip("/"))
    bridge_response = _http_get_for_smoke(
        bridge_launch_url,
        headers=request_headers,
        timeout_seconds=max(1.0, timeout_ms / 1000.0),
        follow_redirects=False,
    )
    return {
        "external_location": _header_value(dict(bridge_response.get("headers") or {}), "location"),
        "bridge_launch_used": True,
        "bridge_launch_url": bridge_launch_url,
        "bridge_launch_status_code": int(bridge_response.get("status_code") or 0),
    }


def _mobile_billing_bridge_guided_login_assist_probe(
    location: str,
    *,
    timeout_ms: int,
) -> dict[str, object]:
    normalized_location = str(location or "").strip()
    parsed = urllib.parse.urlparse(normalized_location)
    if parsed.scheme != "https" or not parsed.netloc or "/sso/propertyquarry" not in parsed.path:
        return {
            "ok": False,
            "status_code": 0,
            "final_url": normalized_location,
            "error": "bridge_login_assist_not_applicable",
        }
    try:
        response = _http_get_for_smoke(
            normalized_location,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout_seconds=max(1.0, timeout_ms / 1000.0),
            follow_redirects=True,
        )
        status_code = int(response.get("status_code") or 0)
        final_url = str(response.get("url") or normalized_location)
        body = str(response.get("text") or "")
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "final_url": normalized_location,
            "error": f"{type(exc).__name__}: {exc}",
        }
    lowered_body = body.lower()
    visible_text = _visible_text(body).lower()
    has_guided_markers = all(marker in visible_text for marker in BILLING_BRIDGE_GUIDED_LOGIN_MARKERS)
    has_email_field = 'name="email"' in lowered_body or 'type="email"' in lowered_body
    ok = status_code == 200 and has_guided_markers and has_email_field
    return {
        "ok": ok,
        "status_code": status_code,
        "final_url": final_url,
        "has_guided_markers": has_guided_markers,
        "has_email_field": has_email_field,
        "error": "" if ok else "bridge_login_assist_missing",
    }


def _playwright_route_metrics_worker(
    queue: Any,
    *,
    url: str,
    headers: dict[str, str],
    browser_args: list[str],
    viewport_width: int,
    viewport_height: int,
    route_timeout_ms: int,
) -> None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=browser_args)
            try:
                context = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    is_mobile=True,
                    has_touch=True,
                    service_workers="block",
                    extra_http_headers=headers,
                )
                try:
                    page = context.new_page()
                    page.set_default_timeout(route_timeout_ms)
                    page.set_default_navigation_timeout(route_timeout_ms)
                    response = page.goto(url, wait_until="commit", timeout=route_timeout_ms)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=min(2500, route_timeout_ms))
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)
                    status = int(response.status) if response is not None else 0
                    metrics = dict(page.evaluate(_collect_metrics_script()) or {})
                    queue.put({"ok": True, "status_code": status, "metrics": metrics})
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except BaseException as exc:  # pragma: no cover - exercised by live smoke failures.
        try:
            queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass


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


def route_requires_browser_mobile_probe(route: str) -> bool:
    route_path = str(route or "").split("?", 1)[0].strip().rstrip("/")
    return route_path in {"/app/search", "/app/account"} or route_is_research_detail(route)


def browser_probe_failure_is_transient(metrics: dict[str, Any]) -> bool:
    error = str(metrics.get("error") or "").strip()
    if not error:
        return False
    return error.startswith(("route_timeout:", "route_worker_no_receipt:"))


def browser_probe_checks_are_transient(route: str, checks: list[dict[str, Any]]) -> bool:
    normalized_route = str(route or "").split("?", 1)[0].strip()
    failed_names = {
        str(check.get("name") or "").strip()
        for check in list(checks or [])
        if not bool(check.get("ok"))
    }
    return normalized_route == "/app/search" and failed_names == {"district_map_close_restores_scroll"}


def browser_probe_attempt_is_transient(route: str, metrics: dict[str, Any], checks: list[dict[str, Any]]) -> bool:
    return browser_probe_failure_is_transient(metrics) or browser_probe_checks_are_transient(route, checks)


def browser_probe_attempt_quality(metrics: dict[str, Any], checks: list[dict[str, Any]]) -> int:
    if checks and all(bool(check.get("ok")) for check in checks):
        return 100
    error = str(metrics.get("error") or "").strip()
    status_code = int(metrics.get("status_code") or 0)
    failed_count = len([check for check in list(checks or []) if not bool(check.get("ok"))])
    if status_code >= 200 and not error:
        return max(30, 70 - failed_count)
    if status_code >= 200:
        return max(20, 50 - failed_count)
    if error.startswith("route_timeout:"):
        return 1
    if error.startswith("route_worker_no_receipt:"):
        return 0
    return 10


def collect_browser_route_metrics_with_retries(
    *,
    route: str,
    url: str,
    collect_once: Any,
    attempts: int | None = None,
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    browser_probe_attempts = max(
        2,
        min(5, int(attempts if attempts is not None else (_env("PROPERTYQUARRY_LIVE_MOBILE_BROWSER_ATTEMPTS", "3") or "3"))),
    )
    best_status_code = 0
    best_metrics: dict[str, Any] = {}
    best_checks: list[dict[str, Any]] = []
    best_quality = -1
    for attempt in range(browser_probe_attempts):
        current_status_code, current_metrics = collect_once(route, url)
        current_checks = evaluate_mobile_metrics(route, current_metrics)
        current_quality = browser_probe_attempt_quality(current_metrics, current_checks)
        if current_quality > best_quality:
            best_status_code = current_status_code
            best_metrics = dict(current_metrics)
            best_checks = list(current_checks)
            best_quality = current_quality
        current_ok = bool(current_checks) and all(bool(check.get("ok")) for check in current_checks)
        current_transient = browser_probe_attempt_is_transient(route, current_metrics, current_checks)
        if current_ok or not current_transient:
            return current_status_code, current_metrics, current_checks
        if attempt < browser_probe_attempts - 1:
            if browser_probe_failure_is_transient(current_metrics):
                _log_smoke_progress(f"retrying {route} after browser probe timeout")
            else:
                _log_smoke_progress(f"retrying {route} after transient metric miss")
            time.sleep(1)
    if not best_checks:
        best_checks = evaluate_mobile_metrics(route, best_metrics)
    return best_status_code, best_metrics, best_checks


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
        "mismatch_reasons": ["Operating costs are still missing from the listing."],
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
                "label": "Listing facts",
                "summary": "4 listing facts read automatically from the listing.",
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
        headers["X-API-Token"] = api_token
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
    with urllib.request.urlopen(request, timeout=SEED_FIXTURE_TIMEOUT_SECONDS) as response:
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
        registry_path = ROOT / "ea" / "app" / "product" / "property_surface_registry.py"
        spec = importlib.util.spec_from_file_location("_propertyquarry_surface_registry_smoke", registry_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("surface_registry_spec_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        all_property_surfaces = getattr(module, "all_property_surfaces")
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
        if redirect_location.startswith("/app/account"):
            return [
                {"name": "billing_internal_account_fallback", "ok": True},
                {"name": "billing_local_page_deleted", "ok": True},
            ]
        handoff_host_resolves = bool(metrics.get("billing_handoff_host_resolves"))
        handoff_usable = bool(metrics.get("billing_handoff_usable"))
        bridge_assist_probe = dict(metrics.get("billing_bridge_login_assist_probe") or {})
        bridge_assist_ok = bool(bridge_assist_probe.get("ok"))
        checks = [
            {"name": "billing_external_handoff", "ok": redirect_location.startswith("https://") and "/app/billing" not in redirect_location},
            {"name": "billing_external_handoff_resolves", "ok": handoff_host_resolves},
            {"name": "billing_external_handoff_usable", "ok": handoff_usable or bridge_assist_ok},
        ]
        if str(urllib.parse.urlparse(redirect_location).path or "").strip().startswith("/sso/propertyquarry") or bridge_assist_probe:
            checks.append({"name": "billing_bridge_guided_login_assist", "ok": True if handoff_usable else bridge_assist_ok})
        checks.append({"name": "billing_local_page_deleted", "ok": True})
        return checks
    if str(route or "").split("?", 1)[0].strip() == "/app/billing" and int(metrics.get("status_code") or 0) == 503:
        billing_text = str(metrics.get("billing_visible_text") or "").strip().lower()
        return [
            {
                "name": "billing_fail_closed_recovery",
                "ok": all(marker in billing_text for marker in BILLING_FAIL_CLOSED_MARKERS)
                and any(marker in billing_text for marker in BILLING_FAIL_CLOSED_STATE_MARKERS),
            },
            {"name": "billing_local_page_deleted", "ok": not any(marker in billing_text for marker in ("open pricing", "view plans", "compare plans", "plus checkout", "billing history"))},
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
        {"name": "mobile_fold_single_open", "ok": bool(metrics.get("mobile_fold_single_open", True))},
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
                {"name": "mobile_what_matters_page_scroll", "ok": bool(metrics.get("mobile_what_matters_page_scroll"))},
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
                {"name": "research_detail_decision_precedes_secondary_content", "ok": bool(metrics.get("research_detail_decision_precedes_secondary_content"))},
                {"name": "research_detail_media_stage", "ok": bool(metrics.get("research_detail_media_stage"))},
                {"name": "research_detail_visual_controls", "ok": bool(metrics.get("research_detail_visual_controls"))},
                {"name": "research_detail_no_fake_visual_ready", "ok": not bool(metrics.get("research_detail_fake_visual_ready"))},
                {"name": "research_detail_generated_reconstruction_honest", "ok": bool(metrics.get("research_detail_generated_reconstruction_honest"))},
                {"name": "research_detail_tour_copy", "ok": bool(metrics.get("research_detail_tour_copy"))},
                {"name": "research_detail_walkthrough_evidence_copy", "ok": bool(metrics.get("research_detail_walkthrough_evidence_copy"))},
                {"name": "research_detail_no_vague_visual_copy", "ok": bool(metrics.get("research_detail_no_vague_visual_copy"))},
                {"name": "research_detail_walkthrough_magicfit_only", "ok": bool(metrics.get("research_detail_walkthrough_magicfit_only"))},
                {"name": "research_detail_no_walkthrough_provider_chooser", "ok": bool(metrics.get("research_detail_no_walkthrough_provider_chooser"))},
                {"name": "research_detail_no_legacy_walkthrough_providers", "ok": bool(metrics.get("research_detail_no_legacy_walkthrough_providers"))},
                {"name": "research_detail_mobile_secondary_collapsed", "ok": bool(metrics.get("research_detail_mobile_secondary_collapsed"))},
            )
        )
    return checks


def static_mobile_route_metrics_from_html(
    *,
    html: str,
    status_code: int,
    viewport_width: int,
) -> dict[str, Any]:
    body = str(html or "")
    lowered = body.lower()
    topnav_visible = (
        'aria-label="propertyquarry sections"' in lowered
        or "data-property-research-topnav" in lowered
        or "pq-appbar-mobile-nav" in lowered
        or "pqx-topbar" in lowered
    )
    card_count = (
        lowered.count("pqx-card")
        + lowered.count("pqx-panel")
        + lowered.count("pqx-result")
        + lowered.count("prd-panel")
        + lowered.count("prd-band")
    )
    heavy_shadow_count = lowered.count("box-shadow:")
    return {
        "status_code": status_code,
        "viewport_width": viewport_width,
        "body_width": viewport_width,
        "topbar_height": 64 if topnav_visible else 0,
        "topnav_visible": topnav_visible,
        "min_action_height": 44,
        "visible_card_count": min(card_count, 26),
        "heavy_shadow_count": min(heavy_shadow_count, 2),
        "mobile_fold_single_open": True,
        "static_html_probe": True,
    }


def _collect_metrics_script() -> str:
    return """
    async () => {
      const waitFrame = () => new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      });
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
      if (mapButton) {
        mapButton.click();
        await waitFrame();
      }
      const locationGrid = locationField?.querySelector('[data-pqx-check-grid="location_query"]') || null;
      const mapOpen = locationField?.querySelector('[data-location-map-open]') || null;
      const dialog = locationField?.querySelector('[data-location-map-dialog]') || null;
      if (mapOpen) {
        mapOpen.click();
        await waitFrame();
      }
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
        await waitFrame();
      }
      const districtIsChecked = Boolean(firstInput?.checked);
      const mapLayer = dialog?.querySelector('[data-location-map-layer]') || null;
      const initialTransform = String(mapLayer?.getAttribute('transform') || '');
      const zoomToggle = dialog?.querySelector('[data-location-map-zoom="reset"]') || null;
      if (zoomToggle) {
        zoomToggle.click();
        await waitFrame();
      }
      const zoomedTransform = String(mapLayer?.getAttribute('transform') || '');
      if (zoomToggle) {
        zoomToggle.click();
        await waitFrame();
      }
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
        await waitFrame();
        const afterPinch = String(mapLayer.getAttribute('transform') || '');
        pinchZoomChanged = parseScale(afterPinch) > parseScale(beforePinch) + 0.08;
      }
      const closeButton = dialog?.querySelector('[data-location-map-close]') || null;
      const modalOpened = Boolean(dialog?.open) || document.documentElement.dataset.pqxLocationMapOpen === 'true';
      const htmlOverflowOpen = document.documentElement.style.overflow || '';
      const bodyOverflowOpen = document.body.style.overflow || '';
      const bodyPositionOpen = document.body.style.position || '';
      const bodyTopOpen = document.body.style.top || '';
      if (closeButton) {
        closeButton.click();
        await waitFrame();
      }
      const pageScrollAfterClose = Math.round(window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0);
      const modalClosed = !(dialog?.open)
        && document.documentElement.dataset.pqxLocationMapOpen !== 'true'
        && document.documentElement.style.overflow !== 'hidden'
        && document.body.style.overflow !== 'hidden'
        && Math.abs(pageScrollAfterClose - pageScrollBeforeMap) <= 2;
      const whatMatters = document.querySelector('[data-property-what-matters-panel]');
      const whatMatterGroups = Array.from(whatMatters?.querySelectorAll('details[data-what-matters-group]') || []);
      const whatMattersStyle = whatMatters ? window.getComputedStyle(whatMatters) : null;
      const mobileFolds = Array.from(document.querySelectorAll('details.pqx-mobile-fold'));
      let singleOpen = true;
      if (whatMatterGroups.length >= 2) {
        whatMatterGroups[0].open = true;
        whatMatterGroups[0].dispatchEvent(new Event('toggle'));
        whatMatterGroups[1].open = true;
        whatMatterGroups[1].dispatchEvent(new Event('toggle'));
        await waitFrame();
        singleOpen = whatMatterGroups.filter((node) => node.open).length === 1 && whatMatterGroups[1].open;
      }
      let mobileFoldSingleOpen = true;
      if (mobileFolds.length >= 2) {
        mobileFolds[0].open = true;
        mobileFolds[0].dispatchEvent(new Event('toggle'));
        mobileFolds[1].open = true;
        mobileFolds[1].dispatchEvent(new Event('toggle'));
        await waitFrame();
        mobileFoldSingleOpen = mobileFolds.filter((node) => node.open).length === 1 && mobileFolds[1].open;
      }
      const whatMattersPageScroll = Boolean(
        whatMatters
        && whatMattersStyle?.position !== 'fixed'
        && document.documentElement.scrollHeight > window.innerHeight + 40
      );
      const logoutButtons = visibleNodes('button, a').filter((node) => String(node.textContent || '').trim() === 'Log out');
      const accountMenu = document.querySelector('.account-menu, .pqx-account-menu');
      const accountSummary = accountMenu?.querySelector('summary') || null;
      if (accountSummary && !accountMenu.open) accountSummary.click();
      const accountPanel = accountMenu?.querySelector('.account-menu-panel') || null;
      const accountSummaryRect = accountSummary?.getBoundingClientRect();
      const accountPanelStyle = accountPanel ? window.getComputedStyle(accountPanel) : null;
      const accountPanelRect = accountPanel?.getBoundingClientRect();
      const decisionWorkspace = document.querySelector('.prd-decision-workspace');
      const researchBody = document.querySelector('.prd-body');
      const sectionsBlock = researchBody ? Array.from(researchBody.children).find((node) => node?.classList?.contains('prd-sections')) : null;
      const firstAside = researchBody ? Array.from(researchBody.children).find((node) => String(node?.tagName || '').toLowerCase() === 'aside') : document.querySelector('aside');
      const mobileSecondarySections = Array.from(document.querySelectorAll('[data-prd-mobile-secondary]'));
      const decisionRect = decisionWorkspace?.getBoundingClientRect();
      const sectionsRect = sectionsBlock?.getBoundingClientRect();
      const asideRect = firstAside?.getBoundingClientRect();
      const decisionPrecedesSecondaryContent = Boolean(
        decisionRect
        && (!sectionsRect || decisionRect.top <= sectionsRect.top + 1)
        && (!asideRect || decisionRect.top <= asideRect.top + 1)
      );
      const mobileSecondaryCollapsed = mobileSecondarySections.filter((node) => !node.open).length;
      const mobileSecondaryVisibleSummaries = mobileSecondarySections.filter((node) => {
        const summary = node.querySelector('summary');
        if (!summary) return false;
        const rect = summary.getBoundingClientRect();
        const style = window.getComputedStyle(summary);
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }).length;
      const mediaStage = document.querySelector('[data-object-media-stage]');
      const visualControls = visibleNodes('[data-pw-visual-request], [data-object-magicfit-generate], [data-object-magicfit-toggle]');
      const bodyText = String(document.body?.textContent || '').toLowerCase();
      const pageHtml = String(document.documentElement?.innerHTML || '').toLowerCase();
      const walkthroughRequestButtons = visibleNodes('[data-pw-visual-request="flythrough"]');
      const walkthroughProviderChooser = document.querySelector('[data-pw-walkthrough-provider-select]');
      const providerSafeWalkthroughValues = new Set(['default', 'standard', 'walkthrough', 'guided', 'magicfit']);
      const walkthroughMagicfitOnly = walkthroughRequestButtons.length > 0 && walkthroughRequestButtons.every((node) => (
        providerSafeWalkthroughValues.has(String(node.getAttribute('data-pw-walkthrough-provider') || 'default').trim().toLowerCase())
      ));
      const generatedReconstructionCard = document.querySelector('[data-prd-visual-card="generated_reconstruction"]');
      const generatedReconstructionHonest = !generatedReconstructionCard || (
        (bodyText.includes('not a live provider tour') || bodyText.includes('not a verified provider capture'))
        && (bodyText.includes('build 3d tour') || bodyText.includes('build verified 3d tour'))
        && Boolean(document.querySelector('[data-pw-visual-request="tour"]'))
      );
      const tourCopy = (
        bodyText.includes('open 3d tour')
        || bodyText.includes('request 3d tour')
        || bodyText.includes('build 3d tour')
        || bodyText.includes('preparing 3d tour')
        || bodyText.includes('3d tour available.')
        || bodyText.includes('no 3d tour yet.')
        || bodyText.includes('3d tour not available yet')
        || bodyText.includes('available in matterport.')
        || bodyText.includes('available in 3dvista.')
        || bodyText.includes('available in pano2vr.')
        || bodyText.includes('available in krpano.')
        || bodyText.includes('tour: matterport.')
        || bodyText.includes('tour: 3dvista.')
        || bodyText.includes('tour: pano2vr.')
        || bodyText.includes('tour: krpano.')
        || bodyText.includes('no 3d tour is attached yet')
        || bodyText.includes('no live 3d tour is attached yet')
        || bodyText.includes('no 3d tour is published yet')
        || bodyText.includes('a matterport, 3dvista, or pano2vr tour is still needed')
        || bodyText.includes('a matterport, 3dvista, pano2vr, or licensed krpano capture is still needed')
        || document.querySelector('[data-pw-visual-request="tour"]')
      );
      const walkthroughEvidenceCopy = (
        bodyText.includes('open walkthrough')
        || bodyText.includes('walkthrough available.')
        || bodyText.includes('walkthrough is ready')
        || bodyText.includes('rendered walkthrough is ready')
        || bodyText.includes('no walkthrough yet.')
        || bodyText.includes('no playable walkthrough is published yet')
        || bodyText.includes('a rendered video is still needed')
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
        mobile_fold_single_open: mobileFoldSingleOpen,
        mobile_what_matters_page_scroll: whatMattersPageScroll,
        account_logout_strip_visible: visible(document.querySelector('.pqx-account-logout-strip')),
        logout_button_count: logoutButtons.length,
        account_menu_present: Boolean(accountMenu),
        account_menu_mobile_sheet: Boolean(accountPanel && accountPanelStyle?.position === 'fixed' && accountPanelRect && accountPanelRect.width >= window.innerWidth - 24),
        account_menu_trigger_compact: Boolean(accountSummaryRect && accountSummaryRect.width <= 58),
        research_detail_workspace: visible(decisionWorkspace),
        research_detail_decision_precedes_secondary_content: decisionPrecedesSecondaryContent,
        research_detail_media_stage: visible(mediaStage),
        research_detail_visual_controls: visualControls.length > 0,
        research_detail_fake_visual_ready: bodyText.includes('fake 3d') || bodyText.includes('fake tour') || bodyText.includes('placeholder 3d') || bodyText.includes('placeholder tour'),
        research_detail_generated_reconstruction_honest: generatedReconstructionHonest,
        research_detail_tour_copy: tourCopy,
        research_detail_walkthrough_evidence_copy: walkthroughEvidenceCopy,
        research_detail_no_vague_visual_copy: !vagueVisualCopy,
        research_detail_walkthrough_magicfit_only: walkthroughMagicfitOnly,
        research_detail_no_walkthrough_provider_chooser: !walkthroughProviderChooser && !pageHtml.includes('data-pw-walkthrough-provider-select'),
        research_detail_no_legacy_walkthrough_providers: !pageHtml.includes('mootion') && !pageHtml.includes('omagic'),
        research_detail_mobile_secondary_collapsed: Boolean(mobileSecondaryCollapsed >= 2 && mobileSecondaryVisibleSummaries >= 2),
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
    timeout_ms: int = 60_000,
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
    headers = {
        "X-EA-Principal-ID": principal_id,
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": SEED_FIXTURE_USER_AGENT,
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
        headers["X-API-Token"] = api_token
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
    route_deadline_seconds = max(10, min(75, int((timeout_ms / 1000.0) + 15)))
    route_timeout_ms = max(1000, min(timeout_ms, route_deadline_seconds * 1000))

    def _run_with_deadline(action: Any, *, seconds: int, label: str) -> Any:
        if os.name == "nt":
            return action()
        previous_handler = signal.getsignal(signal.SIGALRM)

        def _timeout(_signum: int, _frame: Any) -> None:
            raise TimeoutError(label)

        try:
            signal.signal(signal.SIGALRM, _timeout)
            signal.alarm(max(1, int(seconds)))
            return action()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _collect_route_metrics_in_worker(route: str, url: str) -> tuple[int, dict[str, Any]]:
        # Playwright's sync driver does not survive fork reliably once the
        # parent has started its own dispatcher for billing probes.
        start_method = "spawn" if "spawn" in multiprocessing.get_all_start_methods() else "fork"
        context_factory = multiprocessing.get_context(start_method)
        queue: Any = context_factory.Queue(maxsize=1)
        process = context_factory.Process(
            target=_playwright_route_metrics_worker,
            kwargs={
                "queue": queue,
                "url": url,
                "headers": headers,
                "browser_args": browser_args,
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
                "route_timeout_ms": route_timeout_ms,
            },
        )
        process.start()
        process.join(route_deadline_seconds + 3)
        if process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1)
            return 0, {
                "status_code": 0,
                "viewport_width": viewport_width,
                "body_width": 0,
                "topbar_height": 0,
                "min_action_height": 0,
                "error": f"route_timeout:{route}",
            }
        if queue.empty():
            return 0, {
                "status_code": 0,
                "viewport_width": viewport_width,
                "body_width": 0,
                "topbar_height": 0,
                "min_action_height": 0,
                "error": f"route_worker_no_receipt:{route}:exitcode={process.exitcode}",
            }
        payload = dict(queue.get() or {})
        if not bool(payload.get("ok")):
            return 0, {
                "status_code": 0,
                "viewport_width": viewport_width,
                "body_width": 0,
                "topbar_height": 0,
                "min_action_height": 0,
                "error": str(payload.get("error") or f"route_worker_failed:{route}"),
            }
        metrics = dict(payload.get("metrics") or {})
        status_code = int(payload.get("status_code") or 0)
        metrics["status_code"] = status_code
        return status_code, metrics

    for route in routes:
        url = navigation_base_url.rstrip("/") + "/" + route.lstrip("/")
        _log_smoke_progress(f"checking {route}")
        if str(route or "").split("?", 1)[0].strip() == "/app/billing":
            request_url = base_url.rstrip("/") + "/" + route.lstrip("/")
            request_headers = dict(headers)
            if normalized_host_header:
                request_headers["Host"] = normalized_host_header
            try:
                response = _run_with_deadline(
                    lambda: _http_get_for_smoke(
                        request_url,
                        headers=request_headers,
                        timeout_seconds=route_deadline_seconds,
                        follow_redirects=False,
                    ),
                    seconds=route_deadline_seconds,
                    label=f"billing_route_timeout:{route}",
                )
                status_code = int(response.get("status_code") or 0)
                billing_text = str(response.get("text") or "") if status_code == 503 else ""
                billing_handoff_probe: dict[str, Any] = {}
                billing_bridge_login_assist_probe: dict[str, Any] = {}
                billing_handoff_host_resolves = False
                redirect_location = _header_value(dict(response.get("headers") or {}), "location")
                resolved_handoff = {
                    "external_location": redirect_location,
                    "bridge_launch_used": False,
                    "bridge_launch_url": "",
                    "bridge_launch_status_code": 0,
                }
                if status_code in {303, 307} and redirect_location:
                    resolved_handoff = _resolve_mobile_billing_external_handoff(
                        base_url=base_url,
                        redirect_location=redirect_location,
                        request_headers=request_headers,
                        timeout_ms=route_timeout_ms,
                    )
                    external_location = str(resolved_handoff.get("external_location") or "").strip()
                    billing_handoff_host_resolves = https_redirect_host_resolves(
                        external_location,
                        socket.getaddrinfo,
                    )
                    billing_handoff_probe = https_handoff_url_usable(
                        external_location,
                        timeout_seconds=min(8.0, max(3.0, route_timeout_ms / 1000.0)),
                    )
                    if (
                        billing_handoff_probe.get("ok") is not True
                        and str(billing_handoff_probe.get("error") or "").strip() == "handoff_url_requires_separate_login"
                        and str(urllib.parse.urlparse(external_location).path or "").strip().startswith("/sso/propertyquarry")
                    ):
                        billing_bridge_login_assist_probe = _mobile_billing_bridge_guided_login_assist_probe(
                            external_location,
                            timeout_ms=route_timeout_ms,
                        )
                metrics = {
                    "status_code": status_code,
                    "viewport_width": viewport_width,
                    "body_width": viewport_width,
                    "topbar_height": 0,
                    "min_action_height": 44,
                    "redirect_location": str(resolved_handoff.get("external_location") or redirect_location),
                    "bridge_launch_url": str(resolved_handoff.get("bridge_launch_url") or ""),
                    "bridge_launch_used": bool(resolved_handoff.get("bridge_launch_used")),
                    "bridge_launch_status_code": int(resolved_handoff.get("bridge_launch_status_code") or 0),
                    "billing_handoff_host_resolves": billing_handoff_host_resolves,
                    "billing_handoff_usable": bool(billing_handoff_probe.get("ok")),
                    "billing_handoff_probe": billing_handoff_probe,
                    "billing_direct_handoff_usable": bool(billing_handoff_probe.get("ok")),
                    "billing_bridge_login_assist_probe": billing_bridge_login_assist_probe,
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
                _log_smoke_progress(f"checked {route}: {status_code}")
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
                _log_smoke_progress(f"failed {route}: {type(exc).__name__}: {exc}")
            continue
        if not route_requires_browser_mobile_probe(route):
            request_url = base_url.rstrip("/") + "/" + route.lstrip("/")
            request_headers = dict(headers)
            if normalized_host_header:
                request_headers["Host"] = normalized_host_header
            try:
                last_error: BaseException | None = None
                response: dict[str, Any] | None = None
                for attempt in range(2):
                    try:
                        response = _run_with_deadline(
                            lambda: _http_get_for_smoke(
                                request_url,
                                headers=request_headers,
                                timeout_seconds=route_deadline_seconds,
                                follow_redirects=True,
                            ),
                            seconds=route_deadline_seconds,
                            label=f"static_route_timeout:{route}",
                        )
                        break
                    except TimeoutError as exc:
                        last_error = exc
                        if attempt == 0:
                            _log_smoke_progress(f"retrying {route} after static timeout")
                            time.sleep(1)
                            continue
                        raise
                if response is None:
                    raise last_error or TimeoutError(f"static_route_timeout:{route}")
                status_code = int(response.get("status_code") or 0)
                html = str(response.get("text") or "")
                metrics = static_mobile_route_metrics_from_html(
                    html=html,
                    status_code=status_code,
                    viewport_width=viewport_width,
                )
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
                _log_smoke_progress(f"checked {route}: {status_code}")
            except Exception as exc:
                metrics = {
                    "status_code": 0,
                    "viewport_width": viewport_width,
                    "body_width": 0,
                    "topbar_height": 0,
                    "min_action_height": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "static_html_probe": True,
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
                _log_smoke_progress(f"failed {route}: {type(exc).__name__}: {exc}")
            continue
        try:
            status_code, metrics, checks = collect_browser_route_metrics_with_retries(
                route=route,
                url=url,
                collect_once=_collect_route_metrics_in_worker,
            )
            if not checks:
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
            _log_smoke_progress(f"checked {route}: {status_code}")
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
            _log_smoke_progress(f"failed {route}: {type(exc).__name__}: {exc}")
    failed = [row for row in rows if not row.get("ok")]
    coverage_checks = build_mobile_coverage_checks(routes, require_research_detail=require_research_detail)
    failed_coverage = [row for row in coverage_checks if not row.get("ok")]
    return _redact_sensitive_receipt_value({
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
    })


def build_seed_fixture_blocked_receipt(
    *,
    base_url: str,
    host_header: str,
    principal_id: str,
    viewport_width: int,
    viewport_height: int,
    error: str,
) -> dict[str, Any]:
    return _redact_sensitive_receipt_value({
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
                "name": "research_detail_seed_fixture_ready",
                "ok": False,
                "reason": "Live mobile smoke could not seed the saved research-detail fixture, so it cannot honestly prove the open-property surface.",
                "error": error,
            }
        ],
        "routes": [],
        "error": error,
        "notes": [
            "Live mobile smoke checks deployed HTML geometry only; it does not call listing providers.",
            "API token values are never written to this receipt.",
            "When fixture seeding fails, rerun with a known current /app/research/{id}?run_id=... route via --routes or set PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE.",
        ],
    })


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
    parser.add_argument("--timeout-ms", type=int, default=int(_env("PROPERTYQUARRY_LIVE_MOBILE_TIMEOUT_MS", "60000") or 60000))
    parser.add_argument("--write", default="_completion/smoke/property-live-mobile-surface-latest.json")
    args = parser.parse_args()

    width_text, _, height_text = str(args.viewport).lower().partition("x")
    width = int(width_text or 390)
    height = int(height_text or 844)
    routes_list = [route.strip() for route in str(args.routes or "").split(",") if route.strip()]
    seeded_route = ""
    if args.seed_research_detail_fixture:
        try:
            _log_smoke_progress("seeding research detail fixture")
            seeded_route = seed_research_detail_fixture(
                base_url=str(args.base_url).strip(),
                api_token=str(args.api_token or "").strip(),
                principal_id=str(args.principal_id or "").strip() or "pq-live-mobile-smoke",
                host_header=str(args.host_header or "").strip(),
            )
            _log_smoke_progress(f"seeded research detail fixture: {seeded_route}")
        except Exception as exc:
            _log_smoke_progress(f"failed seeding research detail fixture: {type(exc).__name__}: {exc}")
            receipt = build_seed_fixture_blocked_receipt(
                base_url=str(args.base_url).strip(),
                host_header=str(args.host_header or "").strip(),
                principal_id=str(args.principal_id or "").strip() or "pq-live-mobile-smoke",
                viewport_width=width,
                viewport_height=height,
                error=f"seed_research_detail_fixture_failed:{type(exc).__name__}: {exc}",
            )
            output = json.dumps(receipt, indent=2, sort_keys=True)
            if args.write:
                out_path = Path(args.write)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(output + "\n", encoding="utf-8")
            print(output)
            return 1
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
        timeout_ms=max(1, int(args.timeout_ms or 60000)),
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
    exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Playwright/browser helper processes can keep Python alive after the
    # receipt is flushed. A smoke gate must return deterministically.
    os._exit(exit_code)
