#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DEMO_SLUG = "luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557"
DEFAULT_PROVIDERS = ("matterport", "3dvista")
FAILURE_PATTERNS = (
    "violates the following content security policy",
    "refused to display",
    "err_blocked_by_response",
    "webassembly.instantiate",
    "failed to fetch",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check(name: str, ok: bool, **extra: object) -> dict[str, object]:
    return {"name": name, "ok": bool(ok), **extra}


def _browser_url_and_args(base_url: str, host_header: str) -> tuple[str, list[str]]:
    parsed = urllib.parse.urlparse(str(base_url or "http://localhost:8097").strip().rstrip("/"))
    host = str(parsed.hostname or "").lower()
    args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--autoplay-policy=no-user-gesture-required",
    ]
    if host_header and host in {"127.0.0.1", "localhost", "::1"}:
        target_host = str(host_header).strip().split(":", 1)[0]
        netloc = target_host
        if parsed.port:
            netloc = f"{target_host}:{parsed.port}"
        parsed = parsed._replace(netloc=netloc)
        args.extend(
            [
                f"--host-resolver-rules=MAP {target_host} 127.0.0.1",
                "--no-proxy-server",
            ]
        )
    return urllib.parse.urlunparse(parsed).rstrip("/"), args


def _bad_console_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    bad: list[dict[str, str]] = []
    for row in messages:
        text = str(row.get("text") or "").lower()
        if any(pattern in text for pattern in FAILURE_PATTERNS):
            bad.append(row)
    return bad


def _bad_responses(responses: list[dict[str, object]], *, browser_base_url: str) -> list[dict[str, object]]:
    parsed_base = urllib.parse.urlparse(browser_base_url)
    base_host = str(parsed_base.hostname or "").lower()
    bad: list[dict[str, object]] = []
    for row in responses:
        status = int(row.get("status") or 0)
        if status < 400:
            continue
        url = str(row.get("url") or "")
        parsed = urllib.parse.urlparse(url)
        host = str(parsed.hostname or "").lower()
        resource_type = str(row.get("resource_type") or "")
        if host == base_host or resource_type in {"document", "script", "fetch", "xhr"}:
            bad.append(row)
    return bad


def _bad_request_failures(request_failures: list[dict[str, str]], *, browser_base_url: str) -> list[dict[str, str]]:
    parsed_base = urllib.parse.urlparse(browser_base_url)
    base_host = str(parsed_base.hostname or "").lower()
    bad: list[dict[str, str]] = []
    for row in request_failures:
        url = str(row.get("url") or "")
        resource_type = str(row.get("resource_type") or "")
        failure = str(row.get("failure") or "")
        if "favicon" in url.lower():
            continue
        if resource_type == "media" and "net::ERR_ABORTED" in failure:
            continue
        parsed = urllib.parse.urlparse(url)
        host = str(parsed.hostname or "").lower()
        if host != base_host and resource_type in {"image", "media", "font"}:
            continue
        if host == base_host or resource_type in {"document", "script", "fetch", "xhr"}:
            bad.append(row)
    return bad


def _frame_render_state(page: Any, *, provider: str) -> dict[str, object]:
    frames = [frame.url for frame in page.frames]
    iframe_srcs = page.locator("iframe").evaluate_all("(els) => els.map((node) => node.getAttribute('src') || '')")
    provider_frame_url = ""
    for frame_url in frames:
        if "/control/" in frame_url:
            continue
        if frame_url and frame_url != "about:blank":
            provider_frame_url = frame_url
            break
    state: dict[str, object] = {
        "frames": frames,
        "iframe_srcs": iframe_srcs,
        "provider_frame_url": provider_frame_url,
        "canvas_count": 0,
        "visible_canvas_count": 0,
        "frame_text": "",
        "same_origin_frame_inspected": False,
    }
    for frame in page.frames:
        if frame.url != provider_frame_url or not provider_frame_url:
            continue
        if provider_frame_url.startswith("http") and urllib.parse.urlparse(provider_frame_url).hostname not in {"propertyquarry.com", "localhost", "127.0.0.1"}:
            continue
        try:
            state["same_origin_frame_inspected"] = True
            state["canvas_count"] = frame.locator("canvas").count()
            state["visible_canvas_count"] = frame.locator("canvas:visible").count()
            state["frame_text"] = frame.locator("body").inner_text(timeout=2_000)[:800]
        except Exception as exc:
            state["frame_inspection_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    if provider == "matterport" and "my.matterport.com/show/" in provider_frame_url:
        state["external_embedded_target_ok"] = True
    return state


def _provider_rendered_ok(provider: str, state: dict[str, object]) -> bool:
    provider_key = str(provider or "").strip().lower()
    frame_url = str(state.get("provider_frame_url") or "")
    if not frame_url or frame_url == "about:blank":
        return False
    text = str(state.get("frame_text") or "").lower()
    if provider_key in {"3dvista", "pano2vr"}:
        return int(state.get("visible_canvas_count") or 0) > 0 and "loading virtual tour" not in text
    if provider_key == "matterport":
        return "my.matterport.com/show/" in frame_url and bool(state.get("external_embedded_target_ok"))
    return True


def build_browser_gate_receipt(
    *,
    base_url: str,
    host_header: str,
    demo_slug: str,
    providers: list[str],
    timeout_ms: int,
    write_screenshots_dir: str = "",
) -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment guard
        return {
            "contract_name": "propertyquarry.3d_browser_gate.v1",
            "generated_at": _utc_now(),
            "status": "fail",
            "checks": [_check("playwright_available", False, error=f"{type(exc).__name__}: {exc}")],
            "failed_count": 1,
        }

    browser_base_url, browser_args = _browser_url_and_args(base_url, host_header)
    slug = str(demo_slug or DEFAULT_DEMO_SLUG).strip()
    screenshot_dir = Path(write_screenshots_dir) if write_screenshots_dir else None
    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, object]] = []
    provider_results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=browser_args)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            ignore_https_errors=True,
        )
        try:
            for provider in providers:
                provider_key = str(provider or "").strip().lower()
                if provider_key not in DEFAULT_PROVIDERS:
                    continue
                page = context.new_page()
                console_messages: list[dict[str, str]] = []
                request_failures: list[dict[str, str]] = []
                responses: list[dict[str, object]] = []
                page.on(
                    "console",
                    lambda msg: console_messages.append({"type": msg.type, "text": msg.text[:1_000]}),
                )
                page.on(
                    "pageerror",
                    lambda exc: console_messages.append({"type": "pageerror", "text": str(exc)[:1_000]}),
                )
                page.on(
                    "requestfailed",
                    lambda req: request_failures.append(
                        {
                            "url": req.url,
                            "resource_type": req.resource_type,
                            "failure": str(req.failure or "")[:400],
                        }
                    ),
                )
                page.on(
                    "response",
                    lambda resp: responses.append(
                        {
                            "url": resp.url,
                            "status": resp.status,
                            "resource_type": resp.request.resource_type,
                            "content_type": str(resp.headers.get("content-type") or "")[:120],
                        }
                    ),
                )
                route = f"/tours/{urllib.parse.quote(slug, safe='')}/control/{provider_key}"
                url = f"{browser_base_url}{route}"
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(800)
                load_button = page.locator("#load-provider")
                clicked = False
                if load_button.count():
                    clicked = True
                    load_button.click(timeout=timeout_ms)
                page.wait_for_timeout(8_000)
                state = _frame_render_state(page, provider=provider_key)
                if screenshot_dir:
                    page.screenshot(path=str(screenshot_dir / f"{provider_key}.png"), full_page=True)
                bad_console = _bad_console_messages(console_messages)
                bad_http = _bad_responses(responses, browser_base_url=browser_base_url)
                bad_request_failures = _bad_request_failures(request_failures, browser_base_url=browser_base_url)
                frame_url = str(state.get("provider_frame_url") or "")
                rendered_ok = _provider_rendered_ok(provider_key, state)
                load_button_required_ok = clicked or not load_button.count()
                provider_checks = [
                    _check(f"{provider_key}_control_page_ok", bool(response and response.ok), status=response.status if response else 0),
                    _check(
                        f"{provider_key}_direct_viewer_loaded",
                        load_button_required_ok,
                        clicked=clicked,
                        load_button_present=bool(load_button.count()),
                    ),
                    _check(f"{provider_key}_iframe_navigated", bool(frame_url and frame_url != "about:blank"), frame_url=frame_url),
                    _check(f"{provider_key}_no_browser_console_blockers", not bad_console, bad_console=bad_console[:8]),
                    _check(f"{provider_key}_no_request_failures", not bad_request_failures, request_failures=bad_request_failures[:8]),
                    _check(f"{provider_key}_no_bad_http_assets", not bad_http, bad_http=bad_http[:8]),
                    _check(f"{provider_key}_rendered_viewer", rendered_ok, state=state),
                ]
                checks.extend(provider_checks)
                provider_results.append(
                    {
                        "provider": provider_key,
                        "url": url,
                        "clicked": clicked,
                        "state": state,
                        "bad_console_count": len(bad_console),
                        "bad_request_failure_count": len(bad_request_failures),
                        "bad_http_count": len(bad_http),
                        "status": "pass" if all(row["ok"] for row in provider_checks) else "fail",
                    }
                )
                page.close()
        finally:
            context.close()
            browser.close()
    failed = [row for row in checks if not row.get("ok")]
    return {
        "contract_name": "propertyquarry.3d_browser_gate.v1",
        "generated_at": _utc_now(),
        "status": "pass" if not failed else "fail",
        "base_url": str(base_url).strip(),
        "browser_base_url": browser_base_url,
        "host_header": host_header,
        "demo_slug": slug,
        "providers": providers,
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
        "provider_results": provider_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard browser-render gate for PropertyQuarry 3D tour controls.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_LIVE_BASE_URL", "http://localhost:8097"))
    parser.add_argument("--host-header", default=os.getenv("PROPERTYQUARRY_LIVE_HOST_HEADER", "propertyquarry.com"))
    parser.add_argument("--demo-slug", default=DEFAULT_DEMO_SLUG)
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS))
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--screenshots-dir", default="")
    parser.add_argument("--write", default="_completion/smoke/property-live-3d-browser-gate-latest.json")
    args = parser.parse_args()
    providers = [item.strip().lower() for item in str(args.providers or "").split(",") if item.strip()]
    receipt = build_browser_gate_receipt(
        base_url=args.base_url,
        host_header=args.host_header,
        demo_slug=args.demo_slug,
        providers=providers or list(DEFAULT_PROVIDERS),
        timeout_ms=max(5_000, int(args.timeout_ms or 45_000)),
        write_screenshots_dir=args.screenshots_dir,
    )
    output = json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
