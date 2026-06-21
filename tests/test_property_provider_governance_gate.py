from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_property_provider_governance_checker_passes_current_catalog() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "scripts/check_property_provider_governance.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "ok"
    assert payload["provider_count"] > 0
    assert payload["failure_count"] == 0
    assert payload["failures"] == []


def test_property_release_gate_runs_provider_governance_checker() -> None:
    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")

    assert "scripts/check_property_provider_governance.py" in release_gate
