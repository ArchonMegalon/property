from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "docs/PROPERTYQUARRY_PREMIUM_UI_EXIT_GATE.md"
DESIGN_SYSTEM_GATE_PATH = ROOT / "docs/PROPERTYQUARRY_DESIGN_SYSTEM_GATE.md"
RELEASE_GATE_PATH = ROOT / "scripts/property_release_gates.sh"


def test_propertyquarry_premium_ui_exit_gate_is_linked_from_design_gate() -> None:
    design_gate = DESIGN_SYSTEM_GATE_PATH.read_text(encoding="utf-8")

    assert "docs/PROPERTYQUARRY_PREMIUM_UI_EXIT_GATE.md" in design_gate
    assert "premium UI exit gate wins" in design_gate


def test_propertyquarry_premium_ui_exit_gate_uses_recognized_design_references() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")

    for reference in (
        "Apple Human Interface Guidelines",
        "Material Design",
        "Nielsen's usability heuristics",
        "WCAG 2.2 AA",
        "Baymard",
        "GOV.UK",
    ):
        assert reference in gate

    for principle in (
        "clarity, direct manipulation, consistent navigation, forgiving touch targets",
        "visible hierarchy, meaningful motion, accessible states, predictable components",
        "system status, match with the real world, user control, recognition over recall",
        "contrast, keyboard access, focus visibility, target sizing, reduced motion support",
        "low-friction forms, clear product information, transparent checkout/account handoff",
        "one primary thing per page, plain language, explicit errors, no clever labels",
    ):
        assert principle in gate

    for brand_trait in (
        "calm expert",
        "premium but not flashy",
        "minimal but not empty",
        "specific local evidence",
        "one next step at a time",
        "no internal machinery exposed to customers",
    ):
        assert brand_trait in gate


def test_propertyquarry_premium_ui_exit_gate_blocks_known_live_failures() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")

    blockers = (
        "clipped controls",
        "tap targets below 44px",
        "bottom mobile menu bars",
        "raw provider URLs used as titles",
        "internal terms such as OODA",
        "fake progress bars",
        "stale ETA",
        "clickable-looking UI that does nothing",
        "unnecessary intermediate pages",
        "blank loading longer than 1s",
        "impossible combinations",
        "dark mode text below WCAG AA contrast",
        "keyboard traps, scroll traps, map gesture traps",
    )
    for blocker in blockers:
        assert blocker in gate


def test_propertyquarry_premium_ui_exit_gate_requires_full_customer_loop_receipts() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")

    required_receipts = (
        "mobile screenshots: search, district selection, results, research detail, account, billing, tour",
        "browser interaction audit: every visible clickable control on primary surfaces",
        "axe/WCAG scan for primary surfaces",
        "performance receipt for first paint, heavy-route lazy loading, and no 30s blank states",
        "tour receipt proving direct Matterport/3DVista load where available",
        "walkthrough receipt proving room coverage and no frame-jump artifact",
        "search receipt proving no hard score filtering when the user selected no hard filters",
        "copy audit proving no internal/operator language on customer surfaces",
        "recorded mobile browser run: sign in -> search -> district selection -> results -> research -> map -> tour/walkthrough request",
        "click audit: every visible button/link/image/menu either works, opens a real destination, or is disabled with a reason",
        "media audit: real Matterport or 3DVista tour opens directly when available; no 360-cube fallback is visible",
        "pricing/account audit: signed-in user never sees a create-account loop and plan status matches billing source of truth",
    )
    for receipt in required_receipts:
        assert receipt in gate

    assert "sign in -> search -> choose districts -> understand progress -> open ranked results" in gate
    assert "If any step feels noisy, fragile, fake, cramped, or confusing, the release is not gold." in gate


def test_propertyquarry_premium_ui_exit_gate_sets_measurable_mobile_and_performance_thresholds() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")

    thresholds = (
        "320px width must remain usable.",
        "390px width must look intentional, not squeezed.",
        "Touch targets for primary actions are at least 44px high",
        "first visible skeleton or useful status: <= 1s",
        "primary route usable shell: <= 2s on a normal mobile profile",
        "interaction feedback after tap/click: <= 100ms",
        "active search view shows the latest 10 meaningful updates",
    )
    for threshold in thresholds:
        assert threshold in gate


def test_propertyquarry_premium_ui_exit_gate_declares_automated_commands_and_triage_order() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")

    for command in (
        "python3 -m pytest tests/test_propertyquarry_premium_ui_exit_gate.py -q",
        "python3 -m pytest tests/test_propertyquarry_design_system_gate.py -q",
        "PYTHONPATH=ea python3 scripts/propertyquarry_authenticated_performance_smoke.py",
        "PYTHONPATH=ea python3 scripts/verify_property_tour_controls.py",
    ):
        assert command in gate

    for triage_rule in (
        "Remove broken or unnecessary controls before styling them.",
        "Collapse competing paths into one expected next action.",
        "Replace internal language with concrete customer value.",
        "Fix mobile ergonomics before desktop polish.",
        "Only then tune typography, spacing, color, and motion.",
    ):
        assert triage_rule in gate


def test_propertyquarry_premium_ui_exit_gate_mobile_flagship_proof_is_in_release_bundle() -> None:
    gate = GATE_PATH.read_text(encoding="utf-8")
    release_gate = RELEASE_GATE_PATH.read_text(encoding="utf-8")

    assert "recorded mobile browser run: sign in -> search -> district selection -> results -> research -> map -> tour/walkthrough request" in gate
    assert "tests/e2e/test_propertyquarry_flagship_flow.py" in release_gate
