from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import scripts.materialize_ea_browser_workflow_proof as browser_proof_materializer
from scripts.materialize_ea_browser_workflow_proof import build_receipt


SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")


def _write_seed(root: Path) -> None:
    (root / SEED).parent.mkdir(parents=True, exist_ok=True)
    (root / SEED).write_text(
        json.dumps(
            {
                "product": "propertyquarry",
                "release_claim": {"summary": "browser proof must match the flagship claim"},
                "browser_workflow_proof": {
                    "proof_target": "propertyquarry",
                    "expected_browser_signals": ["/app/properties", "/app/research"],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_browser_workflow_proof_passes_when_both_lanes_pass(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        assert root == tmp_path
        return {
            "status": "pass",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 0,
            "duration_seconds": 1.0,
            "output_excerpt": [f"{len(cases)} passed"],
            "limitations": [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "pass"
    assert receipt["contract_name"] == "ea.browser_workflow_proof"
    assert receipt["proof_target"] == "propertyquarry"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == []
    assert receipt["expected_browser_signals"] == ["/app/properties", "/app/research"]
    assert receipt["source_backed_journey_proof"]["test_file"] == "tests/test_propertyquarry_workspace_redesign.py"
    assert receipt["source_backed_journey_proof"]["cases"] == [
        "test_propertyquarry_workspace_routes_render_greenfield_surfaces",
        "test_propertyquarry_failed_run_stays_on_activity_surface",
    ]
    assert receipt["real_browser_e2e_proof"]["test_file"] == "tests/e2e/test_propertyquarry_greenfield_browser.py"
    assert receipt["real_browser_e2e_proof"]["cases"] == [
        "test_propertyquarry_greenfield_workspace_in_real_browser",
        "test_propertyquarry_greenfield_workspace_is_mobile_usable",
    ]


def test_browser_workflow_proof_downgrades_false_green_all_skipped_real_browser_lane(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        return {
            "status": "pass",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 0,
            "duration_seconds": 1.0,
            "output_excerpt": ["2 skipped, 20 deselected in 0.79s"] if real_browser else ["4 passed"],
            "limitations": ["real browser E2E did not run to completion"] if real_browser else [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "preview_only"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == ["real browser E2E did not run to completion"]
    assert receipt["real_browser_e2e_proof"]["status"] == "preview_only"
    assert receipt["real_browser_e2e_proof"]["required_case_count"] == 2
    assert receipt["real_browser_e2e_proof"]["selected_count"] == 2
    assert receipt["real_browser_e2e_proof"]["executed_count"] == 0
    assert receipt["real_browser_e2e_proof"]["outcome_counts"]["skipped"] == 2


def test_pytest_lane_runner_does_not_treat_exit_zero_with_all_skips_as_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_proof_materializer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="ss [100%]\n2 skipped, 20 deselected in 0.79s\n",
            stderr="",
        ),
    )

    lane = browser_proof_materializer._run_pytest_cases(
        tmp_path,
        python_bin="python3",
        test_file="tests/e2e/test_propertyquarry_greenfield_browser.py",
        cases=["first_real_browser_case", "second_real_browser_case"],
        real_browser=True,
    )

    assert lane["status"] == "preview_only"
    assert lane["executed_count"] == 0
    assert lane["selected_count"] == 2
    assert lane["outcome_counts"]["skipped"] == 2
    assert lane["limitations"] == ["real browser E2E did not run to completion"]
    assert " -k " not in f" {lane['command']} "
    assert "tests/e2e/test_propertyquarry_greenfield_browser.py::first_real_browser_case" in lane["command"]
    assert "tests/e2e/test_propertyquarry_greenfield_browser.py::second_real_browser_case" in lane["command"]


def test_browser_workflow_proof_blocks_false_green_zero_outcome_real_browser_lane(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        return {
            "status": "pass",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 0,
            "duration_seconds": 1.0,
            "output_excerpt": [] if real_browser else ["4 passed"],
            "limitations": [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "blocked"
    assert receipt["real_browser_e2e_proof"]["status"] == "blocked"
    assert receipt["real_browser_e2e_proof"]["executed_count"] == 0
    assert "real browser E2E proof is not passing" in receipt["blocking_reasons"]
    assert "required real browser E2E lane reported zero executed cases" in receipt["current_limitations"]


def test_browser_workflow_proof_stays_preview_only_when_real_browser_lane_is_skipped(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        status = "preview_only" if real_browser else "pass"
        limitations = ["uvicorn is not installed in the selected Python environment"] if real_browser else []
        return {
            "status": status,
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 5 if real_browser else 0,
            "duration_seconds": 1.0,
            "output_excerpt": ["skipped"] if real_browser else ["4 passed"],
            "limitations": limitations,
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "preview_only"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == ["uvicorn is not installed in the selected Python environment"]


def test_browser_workflow_proof_blocks_when_source_backed_lane_fails(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        if real_browser:
            return {
                "status": "pass",
                "command": "pytest",
                "cwd": root.as_posix(),
                "python_bin": python_bin,
                "test_file": test_file,
                "cases": cases,
                "exit_code": 0,
                "duration_seconds": 1.0,
                "output_excerpt": ["2 passed"],
                "limitations": [],
            }
        return {
            "status": "blocked",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 1,
            "duration_seconds": 1.0,
            "output_excerpt": ["4 failed"],
            "limitations": ["application import path is broken"],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "blocked"
    assert "source-backed browser journey proof is not passing" in receipt["blocking_reasons"]
    assert receipt["current_limitations"] == ["application import path is broken"]


def test_browser_workflow_proof_current_blocked_receipt_replaces_published_pass_in_ci(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_seed(tmp_path)
    output = tmp_path / browser_proof_materializer.DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"contract_name": "ea.browser_workflow_proof", "status": "pass"}),
        encoding="utf-8",
    )
    blocked = {
        "contract_name": "ea.browser_workflow_proof",
        "product": "propertyquarry",
        "status": "blocked",
        "blocking_reasons": ["source-backed browser journey proof is not passing"],
    }
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(browser_proof_materializer, "build_receipt", lambda *_args, **_kwargs: blocked)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_ea_browser_workflow_proof.py",
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--output",
            browser_proof_materializer.DEFAULT_OUTPUT.as_posix(),
        ],
    )

    assert browser_proof_materializer.main() == 0
    assert json.loads(output.read_text(encoding="utf-8")) == blocked
