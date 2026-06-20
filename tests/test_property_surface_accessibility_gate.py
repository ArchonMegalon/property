from __future__ import annotations

import subprocess
import sys


def test_property_surface_accessibility_gate_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_surface_accessibility.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ok: property surface accessibility" in result.stdout
