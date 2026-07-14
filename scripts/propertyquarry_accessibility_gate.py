#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from scripts.propertyquarry_live_mobile_surface_smoke import DEFAULT_ROUTES, route_is_research_detail
from scripts.propertyquarry_live_public_smoke import PUBLIC_INFORMATION_ROUTES
from scripts.propertyquarry_playwright_runtime import (
    SUPPORTED_PLAYWRIGHT_ENGINES,
    normalize_playwright_engine,
    playwright_browser_type,
    playwright_engine_launch_kwargs,
)


AXE_CORE_VERSION = "4.10.2"
DEFAULT_AXE_CORE_PATH = Path("node_modules/axe-core/axe.min.js")
DEFAULT_BROWSER_ENGINE = "chromium"
DEFAULT_ACCESSIBILITY_ROUTES = (
    *PUBLIC_INFORMATION_ROUTES,
    *(route for route in DEFAULT_ROUTES if route != "/app/billing"),
)
REQUIRED_ACCESSIBILITY_CHECKS = (
    "route_document_loaded",
    "axe_core_version_pinned",
    "axe_no_serious_or_critical_violations",
    "keyboard_only_navigation",
    "visible_keyboard_focus",
    "dialog_focus_contract",
    "semantic_error_states",
    "semantic_live_progress_states",
    "zoom_200_reflow",
    "contrast_signals_clear",
    "reduced_motion_honored",
)


def normalize_browser_engines(engines: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_engine in engines or (DEFAULT_BROWSER_ENGINE,):
        engine = normalize_playwright_engine(raw_engine)
        if engine not in normalized:
            normalized.append(engine)
    return tuple(normalized)


def resolve_axe_core_source(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            "axe_core_unavailable:"
            f"expected pinned axe-core {AXE_CORE_VERSION} input at {resolved}; "
            f"install axe-core@{AXE_CORE_VERSION} locally and pass --axe-core-path"
        )
    source = resolved.read_text(encoding="utf-8")
    if "axe" not in source or len(source) < 100:
        raise ValueError(f"axe_core_invalid_input:{resolved}")
    return source


def _origin(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def _continue_with_origin_scoped_headers(
    route: Any,
    *,
    authorized_origin: str,
    headers: dict[str, str],
) -> None:
    request_origin = _origin(str(route.request.url or ""))
    if request_origin != authorized_origin:
        route.continue_()
        return
    merged = dict(route.request.headers)
    merged.update(headers)
    route.continue_(headers=merged)


def _focus_metrics(page: Any) -> dict[str, Any]:
    focused = False
    for _ in range(16):
        page.keyboard.press("Tab")
        metrics = dict(
            page.evaluate(
                """
                () => {
                  const node = document.activeElement;
                  if (!node || node === document.body || node === document.documentElement) {
                    return { focused: false, visible_focus: false, tag: '' };
                  }
                  const style = getComputedStyle(node);
                  const rect = node.getBoundingClientRect();
                  const outlineWidth = Number.parseFloat(style.outlineWidth || '0') || 0;
                  const focusVisible = (style.outlineStyle !== 'none' && outlineWidth > 0)
                    || (style.boxShadow && style.boxShadow !== 'none');
                  return {
                    focused: rect.width > 0 && rect.height > 0,
                    visible_focus: Boolean(focusVisible),
                    tag: String(node.tagName || '').toLowerCase(),
                    role: String(node.getAttribute('role') || ''),
                  };
                }
                """
            )
            or {}
        )
        if metrics.get("focused"):
            focused = True
            return metrics
    return {"focused": focused, "visible_focus": False, "tag": "", "role": ""}


def _dialog_focus_metrics(page: Any) -> dict[str, Any]:
    opener_found = bool(
        page.evaluate(
            """
            () => {
              const visible = (node) => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 0 && rect.height > 0 && !node.disabled;
              };
              const candidates = Array.from(document.querySelectorAll(
                '[data-location-map-open], [aria-haspopup="dialog"], button[aria-controls], [data-dialog-trigger]'
              )).filter(visible);
              const opener = candidates.find((node) => {
                if (node.matches('[data-location-map-open], [aria-haspopup="dialog"], [data-dialog-trigger]')) return true;
                const controlled = document.getElementById(node.getAttribute('aria-controls') || '');
                return Boolean(controlled && controlled.matches('dialog, [role="dialog"], [aria-modal="true"]'));
              });
              if (!opener) return false;
              opener.setAttribute('data-pq-a11y-dialog-opener', '1');
              return true;
            }
            """
        )
    )
    if not opener_found:
        return {
            "dialog_applicable": False,
            "dialog_focus_contained": True,
            "dialog_escape_closes": True,
            "dialog_focus_restored": True,
        }
    opener = page.locator('[data-pq-a11y-dialog-opener="1"]').first
    opener.focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(150)
    dialog = page.locator('[role="dialog"]:visible, dialog[open], [aria-modal="true"]:visible').first
    if dialog.count() == 0:
        return {
            "dialog_applicable": True,
            "dialog_focus_contained": False,
            "dialog_escape_closes": False,
            "dialog_focus_restored": False,
        }
    initial_focus_inside = bool(
        dialog.evaluate("node => node === document.activeElement || node.contains(document.activeElement)")
    )
    focus_contained = initial_focus_inside
    for _ in range(8):
        page.keyboard.press("Tab")
        if not bool(dialog.evaluate("node => node === document.activeElement || node.contains(document.activeElement)")):
            focus_contained = False
            break
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    dialog_closed = dialog.count() == 0 or not dialog.is_visible()
    focus_restored = bool(
        page.evaluate(
            """
            () => {
              const opener = document.querySelector('[data-pq-a11y-dialog-opener="1"]');
              return Boolean(opener && (opener === document.activeElement || opener.contains(document.activeElement)));
            }
            """
        )
    )
    return {
        "dialog_applicable": True,
        "dialog_focus_contained": focus_contained,
        "dialog_escape_closes": dialog_closed,
        "dialog_focus_restored": focus_restored,
    }


def _page_semantic_metrics(page: Any) -> dict[str, Any]:
    return dict(
        page.evaluate(
            """
            () => {
              const visible = (node) => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const errors = Array.from(document.querySelectorAll(
                '[role="alert"], [aria-invalid="true"], [aria-errormessage], .error, .field-error, [data-error]'
              )).filter(visible);
              const errorSemantics = errors.every((node) => {
                if (node.getAttribute('role') === 'alert') return true;
                if (node.getAttribute('aria-invalid') === 'true') {
                  return Boolean(node.getAttribute('aria-describedby') || node.getAttribute('aria-errormessage'));
                }
                return Boolean(node.closest('[role="alert"]') || node.getAttribute('aria-live'));
              });
              const progress = Array.from(document.querySelectorAll(
                '[role="status"], [role="progressbar"], [aria-live], [aria-busy="true"], progress'
              )).filter(visible);
              const progressSemantics = progress.every((node) => Boolean(
                node.matches('progress, [role="status"], [role="progressbar"]')
                || node.getAttribute('aria-live')
                || node.getAttribute('aria-busy') === 'true'
              ));
              const animations = document.getAnimations ? document.getAnimations() : [];
              const activeMotion = animations.filter((animation) => {
                if (animation.playState !== 'running') return false;
                const timing = animation.effect && animation.effect.getComputedTiming
                  ? animation.effect.getComputedTiming()
                  : {};
                return Number(timing.duration || 0) > 100;
              });
              return {
                error_state_count: errors.length,
                error_semantics_valid: errorSemantics,
                live_progress_count: progress.length,
                live_progress_semantics_valid: progressSemantics,
                reduced_motion_media_matches: matchMedia('(prefers-reduced-motion: reduce)').matches,
                active_motion_count: activeMotion.length,
              };
            }
            """
        )
        or {}
    )


def _axe_metrics(page: Any, *, axe_source: str) -> dict[str, Any]:
    page.add_script_tag(content=axe_source)
    axe_version = str(page.evaluate("() => window.axe && window.axe.version || ''") or "")
    if axe_version != AXE_CORE_VERSION:
        raise RuntimeError(f"axe_core_version_mismatch:expected={AXE_CORE_VERSION}:observed={axe_version or 'missing'}")
    result = dict(
        page.evaluate(
            """
            async () => await window.axe.run(document, {
              runOnly: {
                type: 'tag',
                values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
              },
              resultTypes: ['violations', 'incomplete']
            })
            """
        )
        or {}
    )
    violations = [dict(row) for row in list(result.get("violations") or []) if isinstance(row, dict)]
    serious = [row for row in violations if str(row.get("impact") or "") in {"serious", "critical"}]
    contrast_violations = [row for row in violations if str(row.get("id") or "") == "color-contrast"]
    contrast_incomplete = [
        dict(row)
        for row in list(result.get("incomplete") or [])
        if isinstance(row, dict) and str(row.get("id") or "") == "color-contrast"
    ]
    return {
        "axe_core_version": axe_version,
        "axe_violation_count": len(violations),
        "axe_serious_critical_count": len(serious),
        "axe_serious_critical_violations": [
            {
                "id": str(row.get("id") or ""),
                "impact": str(row.get("impact") or ""),
                "help": str(row.get("help") or ""),
                "node_count": len(list(row.get("nodes") or [])),
            }
            for row in serious
        ],
        "contrast_violation_count": len(contrast_violations),
        "contrast_incomplete_count": len(contrast_incomplete),
    }


def collect_accessibility_engine_rows(
    *,
    base_url: str,
    routes: tuple[str, ...],
    browser_engine: str,
    headers: dict[str, str],
    axe_source: str,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    engine = normalize_playwright_engine(browser_engine)
    authorized_origin = _origin(base_url)
    rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser_type = playwright_browser_type(playwright, engine=engine)
        try:
            browser = browser_type.launch(
                **playwright_engine_launch_kwargs(
                    playwright,
                    engine=engine,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
            )
        except Exception as exc:
            raise RuntimeError(f"playwright_browser_engine_unavailable:{engine}:{type(exc).__name__}: {exc}") from exc
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                reduced_motion="reduce",
                service_workers="block",
            )
            context.route(
                "**/*",
                lambda route: _continue_with_origin_scoped_headers(
                    route,
                    authorized_origin=authorized_origin,
                    headers=headers,
                ),
            )
            try:
                for route in routes:
                    url = base_url.rstrip("/") + "/" + route.lstrip("/")
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.set_default_navigation_timeout(timeout_ms)
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        page.wait_for_timeout(250)
                        final_url = str(page.url or "")
                        status_code = int(response.status) if response is not None else 0
                        expected_path = urllib.parse.urlparse(url).path.rstrip("/") or "/"
                        final_path = urllib.parse.urlparse(final_url).path.rstrip("/") or "/"
                        metrics: dict[str, Any] = {
                            "browser_engine": engine,
                            "status_code": status_code,
                            "navigation_committed": response is not None,
                            "requested_url": url,
                            "final_url": final_url,
                            "route_document_loaded": expected_path == final_path and 200 <= status_code < 300,
                        }
                        metrics.update(_axe_metrics(page, axe_source=axe_source))
                        metrics.update(_focus_metrics(page))
                        metrics.update(_dialog_focus_metrics(page))
                        metrics.update(_page_semantic_metrics(page))
                        page.set_viewport_size({"width": 640, "height": 900})
                        page.wait_for_timeout(100)
                        metrics.update(
                            dict(
                                page.evaluate(
                                    """
                                    () => ({
                                      zoom_percent: 200,
                                      reflow_viewport_width: document.documentElement.clientWidth,
                                      reflow_scroll_width: document.documentElement.scrollWidth,
                                      reflow_without_horizontal_scroll:
                                        document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2,
                                    })
                                    """
                                )
                                or {}
                            )
                        )
                    except Exception as exc:
                        metrics = {
                            "browser_engine": engine,
                            "status_code": 0,
                            "route_document_loaded": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    checks = evaluate_accessibility_metrics(metrics)
                    rows.append(
                        {
                            "route": route,
                            "url": url,
                            "browser_engine": engine,
                            "ok": all(check.get("ok") is True for check in checks),
                            "checks": checks,
                            "metrics": metrics,
                        }
                    )
                    page.close()
            finally:
                context.close()
        finally:
            browser.close()
    return rows


def evaluate_accessibility_metrics(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    dialog_ok = (
        metrics.get("dialog_focus_contained") is True
        and metrics.get("dialog_escape_closes") is True
        and metrics.get("dialog_focus_restored") is True
    )
    return [
        {"name": "route_document_loaded", "ok": metrics.get("route_document_loaded") is True},
        {"name": "axe_core_version_pinned", "ok": metrics.get("axe_core_version") == AXE_CORE_VERSION},
        {
            "name": "axe_no_serious_or_critical_violations",
            "ok": int(metrics.get("axe_serious_critical_count") or 0) == 0
            and metrics.get("axe_core_version") == AXE_CORE_VERSION,
        },
        {"name": "keyboard_only_navigation", "ok": metrics.get("focused") is True},
        {"name": "visible_keyboard_focus", "ok": metrics.get("visible_focus") is True},
        {"name": "dialog_focus_contract", "ok": dialog_ok, "applicable": bool(metrics.get("dialog_applicable"))},
        {"name": "semantic_error_states", "ok": metrics.get("error_semantics_valid") is True},
        {"name": "semantic_live_progress_states", "ok": metrics.get("live_progress_semantics_valid") is True},
        {
            "name": "zoom_200_reflow",
            "ok": int(metrics.get("zoom_percent") or 0) == 200
            and metrics.get("reflow_without_horizontal_scroll") is True,
        },
        {
            "name": "contrast_signals_clear",
            "ok": int(metrics.get("contrast_violation_count") or 0) == 0
            and int(metrics.get("contrast_incomplete_count") or 0) == 0
            and metrics.get("axe_core_version") == AXE_CORE_VERSION,
        },
        {
            "name": "reduced_motion_honored",
            "ok": metrics.get("reduced_motion_media_matches") is True
            and int(metrics.get("active_motion_count") or 0) == 0,
        },
    ]


def build_accessibility_receipt(
    *,
    base_url: str,
    routes: tuple[str, ...] = DEFAULT_ACCESSIBILITY_ROUTES,
    browser_engines: tuple[str, ...] = SUPPORTED_PLAYWRIGHT_ENGINES,
    api_token: str = "",
    principal_id: str = "pq-accessibility-gate",
    axe_core_path: Path = DEFAULT_AXE_CORE_PATH,
    timeout_ms: int = 30_000,
    collect_engine_rows: Callable[..., list[dict[str, Any]]] = collect_accessibility_engine_rows,
) -> dict[str, Any]:
    engines = normalize_browser_engines(browser_engines)
    try:
        axe_source = resolve_axe_core_source(axe_core_path)
    except Exception as exc:
        return {
            "status": "blocked",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": base_url,
            "axe_core_version": AXE_CORE_VERSION,
            "axe_core_path": str(axe_core_path.expanduser().resolve()),
            "required_browser_engines": list(engines),
            "configured_routes": list(routes),
            "route_count": 0,
            "failed_count": 1,
            "checks": [{"name": "axe_core_pinned_input", "ok": False, "reason": str(exc)}],
            "routes": [],
        }
    headers = {"X-EA-Principal-ID": principal_id, "Accept": "text/html,application/xhtml+xml"}
    if api_token:
        headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "X-EA-API-Token": api_token,
                "X-API-Token": api_token,
            }
        )
    rows: list[dict[str, Any]] = []
    engine_failures: list[dict[str, Any]] = []
    for engine in engines:
        try:
            rows.extend(
                collect_engine_rows(
                    base_url=base_url,
                    routes=routes,
                    browser_engine=engine,
                    headers=headers,
                    axe_source=axe_source,
                    timeout_ms=timeout_ms,
                )
            )
        except Exception as exc:
            engine_failures.append(
                {"browser_engine": engine, "error": f"{type(exc).__name__}: {exc}"}
            )
    expected_samples = {(engine, route) for engine in engines for route in routes}
    observed_samples = {
        (str(row.get("browser_engine") or ""), str(row.get("route") or ""))
        for row in rows
    }
    missing_samples = sorted(expected_samples - observed_samples)
    dialog_sample_count = sum(
        1
        for row in rows
        if isinstance(row.get("metrics"), dict) and row["metrics"].get("dialog_applicable") is True
    )
    detail_configured = any(route_is_research_detail(route) for route in routes)
    configured_route_paths = {
        str(route or "").split("?", 1)[0].rstrip("/") or "/"
        for route in routes
    }
    missing_public_information_routes = [
        route for route in PUBLIC_INFORMATION_ROUTES if route not in configured_route_paths
    ]
    checks = [
        {"name": "axe_core_pinned_input", "ok": True, "version": AXE_CORE_VERSION},
        {
            "name": "accessibility_route_engine_matrix_complete",
            "ok": not missing_samples and not engine_failures,
            "missing_samples": [
                {"browser_engine": engine, "route": route}
                for engine, route in missing_samples
            ],
            "engine_failures": engine_failures,
        },
        {
            "name": "public_information_route_matrix_configured",
            "ok": not missing_public_information_routes,
            "required_routes": list(PUBLIC_INFORMATION_ROUTES),
            "missing_routes": missing_public_information_routes,
        },
        {
            "name": "research_detail_route_configured",
            "ok": detail_configured,
            "required_route_prefix": "/app/research/",
        },
        {
            "name": "dialog_focus_interaction_sampled",
            "ok": dialog_sample_count > 0,
            "sample_count": dialog_sample_count,
        },
    ]
    failed_rows = [row for row in rows if row.get("ok") is not True]
    failed_checks = [check for check in checks if check.get("ok") is not True]
    receipt = {
        "status": "pass" if not failed_rows and not failed_checks else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "axe_core_version": AXE_CORE_VERSION,
        "axe_core_path": str(axe_core_path.expanduser().resolve()),
        "required_browser_engines": list(engines),
        "configured_routes": list(routes),
        "expected_sample_count": len(expected_samples),
        "observed_sample_count": len(observed_samples),
        "route_count": len(rows),
        "failed_count": len(failed_rows) + len(failed_checks),
        "dialog_interaction_sample_count": dialog_sample_count,
        "checks": checks,
        "routes": rows,
        "engine_failures": engine_failures,
        "notes": [
            "Axe is injected only from the pinned local input; this gate never downloads scripts or uses a CDN.",
            "The 200% reflow check uses a 640 CSS-pixel viewport as the cross-engine equivalent of zooming a 1280-pixel layout to 200%.",
            "The route matrix preserves every authenticated app route while also requiring every public sitemap, legal, support, docs, integrations, guide, market, registration, and sign-in page.",
        ],
    }
    serialized = json.dumps(receipt, sort_keys=True)
    if api_token and api_token in serialized:
        raise RuntimeError("accessibility_receipt_secret_leak")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the strict PropertyQuarry accessibility route/engine gate.")
    parser.add_argument("--base-url", default=os.environ.get("PROPERTYQUARRY_ACCESSIBILITY_BASE_URL", "http://127.0.0.1:8097"))
    configured_detail = str(os.environ.get("PROPERTYQUARRY_ACCESSIBILITY_RESEARCH_DETAIL_ROUTE") or "").strip()
    default_routes = (*DEFAULT_ACCESSIBILITY_ROUTES, configured_detail) if configured_detail else DEFAULT_ACCESSIBILITY_ROUTES
    parser.add_argument("--routes", default=",".join(default_routes))
    parser.add_argument(
        "--browser-engines",
        default=os.environ.get("PROPERTYQUARRY_ACCESSIBILITY_BROWSER_ENGINES", ",".join(SUPPORTED_PLAYWRIGHT_ENGINES)),
    )
    parser.add_argument("--axe-core-path", default=os.environ.get("PROPERTYQUARRY_AXE_CORE_PATH", str(DEFAULT_AXE_CORE_PATH)))
    parser.add_argument("--api-token", default=os.environ.get("PROPERTYQUARRY_ACCESSIBILITY_API_TOKEN") or os.environ.get("EA_API_TOKEN", ""))
    parser.add_argument("--principal-id", default=os.environ.get("PROPERTYQUARRY_ACCESSIBILITY_PRINCIPAL_ID", "pq-accessibility-gate"))
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--write", default="_completion/smoke/property-live-accessibility-latest.json")
    args = parser.parse_args()
    try:
        engines = normalize_browser_engines(
            tuple(engine.strip() for engine in str(args.browser_engines or "").split(",") if engine.strip())
        )
    except ValueError as exc:
        parser.error(str(exc))
    routes = tuple(route.strip() for route in str(args.routes or "").split(",") if route.strip())
    receipt = build_accessibility_receipt(
        base_url=str(args.base_url).strip(),
        routes=routes or DEFAULT_ACCESSIBILITY_ROUTES,
        browser_engines=engines,
        api_token=str(args.api_token or "").strip(),
        principal_id=str(args.principal_id or "").strip() or "pq-accessibility-gate",
        axe_core_path=Path(args.axe_core_path),
        timeout_ms=max(1_000, int(args.timeout_ms)),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        output_path = Path(args.write)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
