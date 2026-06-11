#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


ENV_FILES = (
    Path("/docker/property/.env"),
    Path("/app/.env"),
    Path("/app/config/.env"),
    Path("/docker/chummercomplete/chummer.run-services/.env"),
)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def _load_env() -> None:
    for path in ENV_FILES:
        _load_env_file(path)


def _login_if_needed(page) -> None:
    page.goto("https://magicfit.pushowl.com/home", wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(4_000)
    body = page.locator("body").inner_text(timeout=10_000)
    if not re.search(r"login|sign in|email|password", body, re.I):
        return
    email = (os.environ.get("CHUMMER_EA_MAGICFIT_EMAIL") or os.environ.get("MAGICFIT_EMAIL") or "").strip()
    password = (os.environ.get("CHUMMER_EA_MAGICFIT_PASSWORD") or os.environ.get("MAGICFIT_PASSWORD") or "").strip()
    if not email or not password:
        raise RuntimeError("magicfit_credentials_missing")
    page.locator("input[type=email], input[name*=email i], input[placeholder*=email i]").first.fill(email)
    page.locator("input[type=password]").first.fill(password)
    page.get_by_role("button", name=re.compile(r"sign in|login|continue|submit", re.I)).first.click()
    page.wait_for_timeout(8_000)


def main() -> int:
    _load_env()
    out_json = Path(os.getenv("MAGICFIT_UI_DUMP_JSON") or "/tmp/magicfit-ui-dump.json")
    out_png = Path(os.getenv("MAGICFIT_UI_DUMP_PNG") or "/tmp/magicfit-ui-dump.png")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        _login_if_needed(page)
        page.goto("https://magicfit.pushowl.com/agents/generate?mode=video", wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(6_000)
        buttons = page.locator("button").evaluate_all(
            """nodes => nodes.map((b, i) => ({
                index: i,
                text: (b.innerText || b.textContent || "").trim(),
                aria: b.getAttribute("aria-label"),
                title: b.getAttribute("title"),
                disabled: b.disabled,
                className: String(b.className || "")
            })).filter(x => x.text || x.aria || x.title)"""
        )
        body = page.locator("body").inner_text(timeout=10_000)
        out_json.write_text(
            json.dumps(
                {
                    "url": page.url,
                    "duration_mentions": sorted(set(re.findall(r"\b(?:4|5|6|8|10|12|15)s\b", body))),
                    "button_count": len(buttons),
                    "buttons": buttons,
                    "body": body,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        page.screenshot(path=str(out_png), full_page=True)
        browser.close()
    print(json.dumps({"dump_json": str(out_json), "dump_png": str(out_png)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
