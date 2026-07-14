from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import check_property_surface_accessibility as gate


def test_property_surface_accessibility_gate_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_surface_accessibility.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ok: property surface accessibility" in result.stdout


def test_property_surface_accessibility_gate_scans_console_base() -> None:
    relative_path = "ea/app/templates/base_console.html"

    assert relative_path in gate.SURFACE_TEMPLATES
    path = gate.ROOT / relative_path
    failures: list[str] = []
    gate._check_accessibility_primitives(path, path.read_text(encoding="utf-8"), failures)

    assert failures == []


def test_property_surface_accessibility_gate_rejects_unnamed_dialog() -> None:
    failures: list[str] = []

    gate._check_dialogs(Path("sample.html"), "<dialog><button type=\"button\">Close</button></dialog>", failures)

    assert any("dialog needs aria-label or aria-labelledby" in failure for failure in failures)


def test_property_surface_accessibility_gate_requires_focusable_sign_in_hash_target() -> None:
    failures: list[str] = []

    gate._check_links(
        Path("sample.html"),
        '<div id="sign-in-options"></div><a href="#sign-in-options">Sign in again</a>',
        failures,
    )

    assert any("hash link target must accept keyboard focus" in failure for failure in failures)


def test_property_surface_accessibility_gate_accepts_focusable_sign_in_hash_target() -> None:
    failures: list[str] = []

    gate._check_links(
        Path("sample.html"),
        '<div id="sign-in-options" tabindex="-1"></div><a href="#sign-in-options">Sign in again</a>',
        failures,
    )

    assert failures == []


def test_property_surface_accessibility_gate_requires_motion_and_focus_primitives() -> None:
    failures: list[str] = []

    gate._check_accessibility_primitives(
        gate.ROOT / "ea/app/templates/base_public.html",
        "a { color: inherit; }",
        failures,
    )

    assert any("prefers-reduced-motion: reduce" in failure for failure in failures)
    assert any("visible focus styles" in failure for failure in failures)


def test_property_surface_accessibility_gate_requires_touch_target_primitives() -> None:
    failures: list[str] = []

    gate._check_accessibility_primitives(
        gate.ROOT / "ea/app/templates/base_public.html",
        """
        :root { --touch-target: 40px; }
        .btn { min-height: var(--touch-target); }
        a:focus-visible { outline: 2px solid red; }
        @media (prefers-reduced-motion: reduce) { * { transition: none; } }
        """,
        failures,
    )

    assert any("--touch-target-coarse" in failure for failure in failures)
    assert any("--focus-ring" in failure for failure in failures)
    assert any("coarse pointers" in failure for failure in failures)


def test_property_surface_accessibility_gate_rejects_legacy_mobile_dock() -> None:
    failures: list[str] = []

    gate._check_accessibility_primitives(
        gate.ROOT / "ea/app/templates/base_console.html",
        """
        :root { --touch-target: 40px; --touch-target-coarse: 44px; --focus-ring: 3px solid red; }
        a:focus-visible { outline: 2px solid red; }
        .btn { min-height: var(--touch-target); }
        .pq-appbar-mobile-nav a,
        .pq-appbar-mobile-nav span { min-height: var(--touch-target); }
        @media (prefers-reduced-motion: reduce) { * { transition: none; } }
        @media (pointer: coarse) {
          .pq-appbar-mobile-nav a,
          .pq-appbar-mobile-nav span { min-height: var(--touch-target-coarse); }
        }
        .pq-mobile-nav a { min-height: 48px; }
        """,
        failures,
    )

    assert any("legacy mobile bottom dock" in failure for failure in failures)


def test_property_surface_accessibility_gate_checks_contrast_tokens() -> None:
    failures: list[str] = []

    gate._check_contrast_tokens(
        gate.ROOT / "ea/app/templates/base_public.html",
        """
        :root {
          --bg: #ffffff;
          --panel: #ffffff;
          --text: #ffffff;
          --text-soft: #fefefe;
          --text-dim: #fdfdfd;
        }
        """,
        failures,
    )

    assert any("contrast text on panel" in failure for failure in failures)
    assert any("contrast text-soft on panel" in failure for failure in failures)


def test_property_surface_accessibility_gate_checks_workbench_dark_contrast() -> None:
    failures: list[str] = []

    gate._check_contrast_tokens(
        gate.ROOT / "ea/app/templates/app/property_decision_workbench.html",
        """
        :root {
          --pq-ink: #171513;
          --pq-muted: #696358;
          --pq-faint: #90877a;
          --pq-paper: #fffdf9;
          --pq-panel: #fbf7ef;
        }
        html[data-pq-theme="dark"] {
          --pq-ink: #ffffff;
          --pq-muted: #ffffff;
          --pq-faint: #ffffff;
          --pq-paper: #ffffff;
          --pq-panel: #ffffff;
        }
        """,
        failures,
    )

    assert any("dark contrast pq-ink on pq-paper" in failure for failure in failures)
