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
    "ea/app/templates/base_public.html",
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

ACCESSIBILITY_PRIMITIVE_TEMPLATES = (
    "ea/app/templates/base_public.html",
    "ea/app/templates/base_console.html",
    "ea/app/templates/app/property_decision_workbench.html",
    "ea/app/templates/app/property_research_detail.html",
)


def _hex_to_rgb(value: str) -> tuple[float, float, float] | None:
    text = value.strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return None
    return tuple(int(text[index : index + 2], 16) / 255.0 for index in (1, 3, 5))  # type: ignore[return-value]


def _relative_luminance(value: str) -> float | None:
    rgb = _hex_to_rgb(value)
    if rgb is None:
        return None

    def _channel(component: float) -> float:
        if component <= 0.03928:
            return component / 12.92
        return ((component + 0.055) / 1.055) ** 2.4

    red, green, blue = (_channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float | None:
    foreground_luminance = _relative_luminance(foreground)
    background_luminance = _relative_luminance(background)
    if foreground_luminance is None or background_luminance is None:
        return None
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _css_vars(text: str, selector: str) -> dict[str, str]:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", text, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return {}
    return {
        str(var_match.group("name")): str(var_match.group("value")).strip()
        for var_match in re.finditer(r"--(?P<name>[a-zA-Z0-9_-]+)\s*:\s*(?P<value>[^;]+);", match.group("body"))
    }


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


def _check_dialogs(path: Path, text: str, failures: list[str]) -> None:
    for match in re.finditer(r"<dialog\b(?P<attrs>[^>]*)>", text, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group(0)
        line = _line_number(text, match.start())
        if not ((_attr(tag, "aria-label") or "").strip() or (_attr(tag, "aria-labelledby") or "").strip()):
            failures.append(f"{path}:{line} dialog needs aria-label or aria-labelledby")


def _check_accessibility_primitives(path: Path, text: str, failures: list[str]) -> None:
    relative = str(path.relative_to(ROOT))
    if relative not in ACCESSIBILITY_PRIMITIVE_TEMPLATES:
        return
    if "prefers-reduced-motion: reduce" not in text:
        failures.append(f"{path} must define a prefers-reduced-motion: reduce block")
    if ":focus-visible" not in text:
        failures.append(f"{path} must define visible focus styles")
    if relative in {"ea/app/templates/base_public.html", "ea/app/templates/base_console.html"}:
        for token in ("--touch-target:", "--touch-target-coarse:", "--focus-ring:"):
            if token not in text:
                failures.append(f"{path} must define {token.rstrip(':')}")
        if "@media (pointer: coarse)" not in text or "var(--touch-target-coarse)" not in text:
            failures.append(f"{path} must increase interactive targets for coarse pointers")
        if "min-height: var(--touch-target)" not in text:
            failures.append(f"{path} must use --touch-target for primary buttons")
    if relative == "ea/app/templates/app/property_decision_workbench.html":
        for token in ("--pq-touch-target:", "--pq-touch-target-coarse:", "--pq-focus-ring:"):
            if token not in text:
                failures.append(f"{path} must define {token.rstrip(':')}")
        if "@media (pointer: coarse)" not in text or "var(--pq-touch-target-coarse)" not in text:
            failures.append(f"{path} must increase workbench controls for coarse pointers")
    if relative == "ea/app/templates/app/property_research_detail.html":
        if "@media (pointer: coarse)" not in text or "var(--touch-target-coarse)" not in text:
            failures.append(f"{path} must increase research-detail controls for coarse pointers")


def _check_contrast_tokens(path: Path, text: str, failures: list[str]) -> None:
    relative = str(path.relative_to(ROOT))
    if relative in {"ea/app/templates/base_public.html", "ea/app/templates/base_console.html"}:
        tokens = _css_vars(text, ":root")
        pairs = (
            ("text", "panel", 4.5),
            ("text-soft", "panel", 4.5),
            ("text-dim", "panel", 3.0),
            ("text", "bg", 4.5),
            ("text-soft", "bg", 4.5),
        )
    elif relative == "ea/app/templates/app/property_decision_workbench.html":
        light_tokens = _css_vars(text, ":root")
        dark_tokens = _css_vars(text, 'html[data-pq-theme="dark"]')
        pairs = (
            ("pq-ink", "pq-paper", 4.5),
            ("pq-muted", "pq-paper", 4.5),
            ("pq-faint", "pq-paper", 3.0),
            ("pq-ink", "pq-panel", 4.5),
            ("pq-muted", "pq-panel", 4.5),
        )
        for label, tokens in (("light", light_tokens), ("dark", dark_tokens)):
            for foreground, background, minimum in pairs:
                ratio = _contrast_ratio(tokens.get(foreground, ""), tokens.get(background, ""))
                if ratio is None or ratio < minimum:
                    failures.append(
                        f"{path} {label} contrast {foreground} on {background} must be >= {minimum:g}:1"
                    )
        return
    else:
        return

    for foreground, background, minimum in pairs:
        ratio = _contrast_ratio(tokens.get(foreground, ""), tokens.get(background, ""))
        if ratio is None or ratio < minimum:
            failures.append(f"{path} contrast {foreground} on {background} must be >= {minimum:g}:1")


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
        _check_dialogs(path, text, failures)
        _check_accessibility_primitives(path, text, failures)
        _check_contrast_tokens(path, text, failures)

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
