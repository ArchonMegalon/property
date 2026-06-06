from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
GATES_DIR = ROOT / "docs" / "exit_gates"

COMMON_STATUSES = ["pass", "fail", "watch", "blocked"]
PHASE_KEYS = [
    "phase",
    "name",
    "objective",
    "status_values",
    "required_test_modules",
    "required_contract_coverage",
    "required_browser_workflows",
    "required_persistence_assertions",
    "required_ui_affordances",
    "fail_closed_conditions",
    "exit_criteria",
    "evidence_artifacts",
]


def load_gate(filename: str) -> dict[str, object]:
    path = GATES_DIR / filename
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(payload, dict), f"{path} must parse to a mapping"
    return payload


def assert_phase_gate_shape(payload: dict[str, object], *, phase: int) -> None:
    assert sorted(PHASE_KEYS) == sorted(payload.keys())
    assert payload["phase"] == phase
    assert payload["status_values"] == COMMON_STATUSES
    required_test_modules = payload["required_test_modules"]
    assert isinstance(required_test_modules, dict)
    assert sorted(required_test_modules.keys()) == ["browser", "contract", "gate"]
    for key, value in required_test_modules.items():
        assert isinstance(value, list) and value, f"{key} test modules must be a non-empty list"
        assert all(isinstance(item, str) and item.startswith("tests/") for item in value)
    for list_key in (
        "required_contract_coverage",
        "required_persistence_assertions",
        "required_ui_affordances",
        "fail_closed_conditions",
        "exit_criteria",
        "evidence_artifacts",
    ):
        value = payload[list_key]
        assert isinstance(value, list) and value, f"{list_key} must be a non-empty list"
        assert all(isinstance(item, str) and item.strip() for item in value)
    workflows = payload["required_browser_workflows"]
    assert isinstance(workflows, list) and workflows
    for row in workflows:
        assert isinstance(row, dict)
        assert isinstance(row.get("name"), str) and str(row["name"]).strip()
        checks = row.get("checks")
        assert isinstance(checks, list) and checks
        assert all(isinstance(item, str) and item.strip() for item in checks)


def assert_master_gate_shape(payload: dict[str, object]) -> None:
    assert sorted(payload.keys()) == sorted(
        ["name", "objective", "required_test_modules", "required_browser_workflows", "fail_closed_conditions", "exit_criteria"]
    )
    assert isinstance(payload["name"], str) and str(payload["name"]).strip()
    assert isinstance(payload["objective"], str) and str(payload["objective"]).strip()
    test_modules = payload["required_test_modules"]
    assert isinstance(test_modules, list) and test_modules
    assert all(isinstance(item, str) and item.startswith("tests/") for item in test_modules)
    for list_key in ("required_browser_workflows", "fail_closed_conditions", "exit_criteria"):
        value = payload[list_key]
        assert isinstance(value, list) and value
        assert all(isinstance(item, str) and item.strip() for item in value)
