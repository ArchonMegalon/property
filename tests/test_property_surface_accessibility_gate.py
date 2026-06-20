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


def test_property_surface_accessibility_gate_rejects_unnamed_dialog() -> None:
    failures: list[str] = []

    gate._check_dialogs(Path("sample.html"), "<dialog><button type=\"button\">Close</button></dialog>", failures)

    assert any("dialog needs aria-label or aria-labelledby" in failure for failure in failures)


def test_property_surface_accessibility_gate_requires_motion_and_focus_primitives() -> None:
    failures: list[str] = []

    gate._check_accessibility_primitives(
        gate.ROOT / "ea/app/templates/base_public.html",
        "a { color: inherit; }",
        failures,
    )

    assert any("prefers-reduced-motion: reduce" in failure for failure in failures)
    assert any("visible focus styles" in failure for failure in failures)
