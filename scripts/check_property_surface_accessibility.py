#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SURFACE_TEMPLATES = (
    "ea/app/templates/propertyquarry_home.html",
    "ea/app/templates/pricing_page.html",
    "ea/app/templates/sign_in.html",
    "ea/app/templates/register.html",
    "ea/app/templates/security_page.html",
    "ea/app/templates/docs_page.html",
    "ea/app/templates/integrations_page.html",
    "ea/app/templates/data_deletion.html",
    "ea/app/templates/app/property_decision_workbench.html",
    "ea/app/templates/app/property_research_detail.html",
    "ea/app/templates/app/property_packets.html",
    "ea/app/templates/app/_property_results_list.html",
    "ea/app/templates/app/_property_running_panel.html",
    "ea/app/templates/app/_property_search_agents_panel.html",
    "ea/app/templates/app/_property_account_panel.html",
    "ea/app/templates/app/_property_billing_panel.html",
    "ea/app/templates/app/_property_selected_review_panel.html",
)

FORBIDDEN_CUSTOMER_NOISE = (
    "billing truth",
    "plan and limits",
    "refresh delivery",
    "repair status checked",
    "what happened",
    "what still worked",
    "main blocker",
    "best next move",
    "release gate",
    "review gates",
    "visual checks",
    "proof",
)

ALLOWED_HASH_TARGETS = {"#results-list", "#pqx-filtered-breakdown"}


def _line_number(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf"""\b{name}\s*=\s*(['"])(.*?)\1""", tag, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    return match.group(2)


def _visible_text(html_fragment: str) -> str:
    no_template = re.sub(r"{[#%{].*?[#}%]}", " ", html_fragment, flags=re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_template)
    return re.sub(r"\s+", " ", no_tags).strip()


def _check_customer_noise(path: Path, text: str, failures: list[str]) -> None:
    lowered = text.lower()
    for phrase in FORBIDDEN_CUSTOMER_NOISE:
        offset = lowered.find(phrase)
        if offset >= 0:
            failures.append(f"{path}:{_line_number(text, offset)} contains customer-facing noise phrase: {phrase}")


def _check_buttons(path: Path, text: str, failures: list[str]) -> None:
    for match in re.finditer(r"<button\b(?P<attrs>[^>]*)>(?P<body>.*?)</button>", text, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        attrs = match.group("attrs")
        body = match.group("body")
        line = _line_number(text, match.start())
        if re.search(r"\btype\s*=", attrs, flags=re.IGNORECASE) is None:
            failures.append(f"{path}:{line} button must declare type")
        label = _visible_text(body) or _attr(tag, "aria-label") or _attr(tag, "title")
        if not str(label or "").strip():
            failures.append(f"{path}:{line} button needs visible text, aria-label or title")


def _check_links(path: Path, text: str, failures: list[str]) -> None:
    for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>", text, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        href = _attr(tag, "href")
        line = _line_number(text, match.start())
        if href is None:
            failures.append(f"{path}:{line} anchor must declare href")
            continue
        normalized = href.strip()
        if normalized in {"", "#"}:
            failures.append(f"{path}:{line} anchor href must not be empty or #")
        if normalized.lower().startswith("javascript:"):
            failures.append(f"{path}:{line} anchor must not use javascript: href")
        if normalized.startswith("#") and normalized not in ALLOWED_HASH_TARGETS:
            failures.append(f"{path}:{line} hash link must target an approved in-page action")


def _check_images(path: Path, text: str, failures: list[str]) -> None:
    for match in re.finditer(r"<img\b(?P<attrs>[^>]*)>", text, flags=re.IGNORECASE | re.DOTALL):
        attrs = match.group("attrs")
        if re.search(r"\balt\s*=", attrs, flags=re.IGNORECASE) is None:
            failures.append(f"{path}:{_line_number(text, match.start())} image must declare alt text")


def main() -> int:
    failures: list[str] = []
    for relative_path in SURFACE_TEMPLATES:
        path = ROOT / relative_path
        if not path.exists():
            failures.append(f"{relative_path} is missing")
            continue
        text = path.read_text(encoding="utf-8")
        _check_customer_noise(path, text, failures)
        _check_buttons(path, text, failures)
        _check_links(path, text, failures)
        _check_images(path, text, failures)

    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")
    if "scripts/check_property_surface_accessibility.py" not in release_gate:
        failures.append("property_release_gates.sh must run check_property_surface_accessibility.py")

    if failures:
        print("property surface accessibility check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("ok: property surface accessibility")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
