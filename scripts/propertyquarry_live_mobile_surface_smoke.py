#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROUTES = (
    "/app/search",
    "/app/shortlist",
    "/app/agents",
    "/app/alerts",
    "/app/account",
    "/app/billing",
    "/app/settings/google",
    "/app/research",
    "/app/properties/packets",
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _route_expectations(route: str) -> dict[str, Any]:
    if route == "/app/search":
        return {"needs_mobile_dock": True, "needs_district_picker": True}
    if route == "/app/account":
        return {"needs_single_logout": True}
    return {}


def evaluate_mobile_metrics(route: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    expectations = _route_expectations(route)
    viewport_width = int(metrics.get("viewport_width") or 0)
    body_width = int(metrics.get("body_width") or 0)
    topbar_height = int(metrics.get("topbar_height") or 0)
    min_action_height = float(metrics.get("min_action_height") or 0)
    checks = [
        {"name": "status_200", "ok": int(metrics.get("status_code") or 0) == 200},
        {"name": "no_horizontal_overflow", "ok": bool(viewport_width) and body_width <= viewport_width + 1},
        {"name": "compact_topbar", "ok": 0 < topbar_height <= 112},
        {"name": "shared_top_navigation", "ok": bool(metrics.get("topnav_visible"))},
        {"name": "primary_touch_targets", "ok": min_action_height >= 44},
        {"name": "card_density", "ok": int(metrics.get("visible_card_count") or 0) <= 26},
        {"name": "low_shadow_noise", "ok": int(metrics.get("heavy_shadow_count") or 0) <= 2},
    ]
    if expectations.get("needs_mobile_dock"):
        checks.append({"name": "mobile_dock_visible", "ok": bool(metrics.get("mobile_dock_visible"))})
    if expectations.get("needs_district_picker"):
        checks.extend(
            (
                {"name": "district_picker_available", "ok": bool(metrics.get("district_picker_available"))},
                {"name": "district_map_popup_available", "ok": bool(metrics.get("district_map_popup_available"))},
                {"name": "district_list_not_visible_in_map_mode", "ok": bool(metrics.get("district_list_hidden_in_map_mode"))},
            )
        )
    if expectations.get("needs_single_logout"):
        checks.extend(
            (
                {"name": "account_logout_strip_visible", "ok": bool(metrics.get("account_logout_strip_visible"))},
                {"name": "single_logout_action", "ok": int(metrics.get("logout_button_count") or 0) == 1},
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
      const mobileDock = document.querySelector('[data-property-mobile-dock]');
      const actionNodes = visibleNodes('main button, main a.pqx-button, main a.pqx-link-button, main a.pq-pack-button, main .console-action, .pqx-account-logout-strip button, .pqx-account-logout-strip a');
      const actionHeights = actionNodes.map((node) => node.getBoundingClientRect().height).filter((height) => height > 0);
      const cardNodes = visibleNodes('.pqx-card, .pqx-panel, .pqx-result, .pqx-account-action-card, .pqx-billing-card, .pqx-billing-summary-card, .pqx-automation-card, .prd-panel, .prd-band');
      const heavyShadowNodes = cardNodes.filter((node) => window.getComputedStyle(node).boxShadow !== 'none');
      const locationField = document.querySelector('[data-property-field-name="location_query"]');
      const mapButton = locationField?.querySelector('[data-location-mode-button="map"]') || null;
      if (mapButton) mapButton.click();
      const locationGrid = locationField?.querySelector('[data-pqx-check-grid="location_query"]') || null;
      const mapOpen = locationField?.querySelector('[data-location-map-open]') || null;
      const logoutButtons = visibleNodes('button, a').filter((node) => String(node.textContent || '').trim() === 'Log out');
      return {
        body_width: document.documentElement.scrollWidth,
        viewport_width: window.innerWidth,
        topbar_height: topbar ? Math.round(topbar.getBoundingClientRect().height) : 0,
        topnav_visible: visible(topnav),
        mobile_dock_visible: visible(mobileDock),
        min_action_height: actionHeights.length ? Math.min(...actionHeights) : 44,
        visible_card_count: cardNodes.length,
        heavy_shadow_count: heavyShadowNodes.length,
        district_picker_available: Boolean(locationField),
        district_map_popup_available: visible(mapOpen),
        district_list_hidden_in_map_mode: locationGrid ? window.getComputedStyle(locationGrid).display === 'none' : false,
        account_logout_strip_visible: visible(document.querySelector('.pqx-account-logout-strip')),
        logout_button_count: logoutButtons.length,
      };
    }
    """


def build_live_mobile_surface_receipt(
    *,
    base_url: str,
    api_token: str,
    principal_id: str,
    routes: tuple[str, ...] = DEFAULT_ROUTES,
    viewport_width: int = 390,
    viewport_height: int = 844,
    timeout_ms: int = 20_000,
) -> dict[str, Any]:
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
    rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                is_mobile=True,
                has_touch=True,
                extra_http_headers=headers,
            )
            page = context.new_page()
            for route in routes:
                url = base_url.rstrip("/") + "/" + route.lstrip("/")
                response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
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
            context.close()
        finally:
            browser.close()
    failed = [row for row in rows if not row.get("ok")]
    return {
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "principal_id": principal_id,
        "viewport": {"width": viewport_width, "height": viewport_height},
        "route_count": len(rows),
        "failed_count": len(failed),
        "routes": rows,
        "notes": [
            "Live mobile smoke checks deployed HTML geometry only; it does not call listing providers.",
            "API token values are never written to this receipt.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live mobile UI smoke against PropertyQuarry app surfaces.")
    parser.add_argument("--base-url", default=_env("PROPERTYQUARRY_LIVE_BASE_URL", "http://localhost:8097"))
    parser.add_argument("--api-token", default=_env("PROPERTYQUARRY_LIVE_API_TOKEN") or _env("EA_API_TOKEN"))
    parser.add_argument("--principal-id", default=_env("PROPERTYQUARRY_LIVE_PRINCIPAL_ID", "pq-live-mobile-smoke"))
    parser.add_argument("--routes", default=",".join(DEFAULT_ROUTES))
    parser.add_argument("--viewport", default="390x844")
    parser.add_argument("--write", default="_completion/smoke/property-live-mobile-surface-latest.json")
    args = parser.parse_args()

    width_text, _, height_text = str(args.viewport).lower().partition("x")
    width = int(width_text or 390)
    height = int(height_text or 844)
    routes = tuple(route.strip() for route in str(args.routes or "").split(",") if route.strip())
    receipt = build_live_mobile_surface_receipt(
        base_url=str(args.base_url).strip(),
        api_token=str(args.api_token or "").strip(),
        principal_id=str(args.principal_id or "").strip() or "pq-live-mobile-smoke",
        routes=routes or DEFAULT_ROUTES,
        viewport_width=width,
        viewport_height=height,
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
