from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import scripts.materialize_ea_browser_workflow_proof as browser_proof_materializer
from scripts import propertyquarry_release_proof_baseline as release_proof_baseline
from scripts.materialize_ea_browser_workflow_proof import build_receipt


SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")


def _evidence_sources() -> list[dict[str, object]]:
    return [
        {
            "file": browser_proof_materializer.SOURCE_BACKED_TEST_FILE,
            "cases": list(browser_proof_materializer.SOURCE_BACKED_CASES),
        },
        {
            "file": browser_proof_materializer.REAL_BROWSER_TEST_FILE,
            "cases": list(browser_proof_materializer.REAL_BROWSER_CASES),
        },
        {
            "file": browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE,
            "cases": list(browser_proof_materializer.EVIDENCE_OVERLAY_CASES),
        },
    ]


def _journey_evidence_matrix() -> dict[str, object]:
    source_file = browser_proof_materializer.SOURCE_BACKED_TEST_FILE
    browser_file = browser_proof_materializer.REAL_BROWSER_TEST_FILE
    evidence_file = browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE
    return {
        "version": 1,
        "readiness_scope": "candidate_source_and_browser_proof",
        "required_journey_ids": list(browser_proof_materializer.REQUIRED_JOURNEY_IDS),
        "rows": [
            {
                "journey_id": "public_entry",
                "label": "Public entry and optional media recovery",
                "evidence_sources": [
                    {
                        "file": source_file,
                        "cases": ["test_propertyquarry_public_home_survives_unreadable_optional_tour_media"],
                    }
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-public-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "onboarding_auth",
                "label": "Onboarding, authentication, session return, and sign-out",
                "evidence_sources": [
                    {
                        "file": source_file,
                        "cases": ["test_property_workspace_sign_out_clears_workspace_session_cookie"],
                    },
                    {
                        "file": browser_file,
                        "cases": [
                            "test_propertyquarry_expired_session_next_action_moves_keyboard_focus_to_sign_in_options"
                        ],
                    },
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-activation-to-value-*.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "search_ranking",
                "label": "Search setup, ranked results, and failed-run recovery",
                "evidence_sources": [
                    {
                        "file": source_file,
                        "cases": [
                            "test_propertyquarry_workspace_routes_render_greenfield_surfaces",
                            "test_propertyquarry_failed_run_stays_on_activity_surface",
                        ],
                    },
                    {
                        "file": browser_file,
                        "cases": ["test_propertyquarry_greenfield_workspace_in_real_browser"],
                    },
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-authenticated-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "shortlist_research_revisit",
                "label": "Shortlist, research detail, persistence, and revisit",
                "evidence_sources": [
                    {
                        "file": source_file,
                        "cases": ["test_property_saved_shortlist_candidates_persist_across_runs"],
                    },
                    {
                        "file": browser_file,
                        "cases": [
                            "test_propertyquarry_greenfield_workspace_is_mobile_usable",
                            "test_propertyquarry_workbench_candidate_history_stays_in_place",
                            "test_propertyquarry_research_evidence_states_and_links_render_in_real_browser",
                        ],
                    },
                    {
                        "file": evidence_file,
                        "cases": list(browser_proof_materializer.EVIDENCE_OVERLAY_CASES),
                    },
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-mobile-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "account_pricing_privacy_recovery",
                "label": "Account, pricing, privacy lifecycle, and recovery",
                "evidence_sources": [
                    {
                        "file": source_file,
                        "cases": [
                            "test_propertyquarry_account_exposes_working_lifecycle_controls",
                            "test_propertyquarry_pricing_checkout_failure_copy_is_safe_and_accessible",
                        ],
                    }
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-authenticated-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "packets_tours",
                "label": "Decision packets, sharing, tours, and recovery",
                "evidence_sources": [
                    {
                        "file": browser_file,
                        "cases": list(
                            browser_proof_materializer.REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES
                        ),
                    }
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-public-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "feedback",
                "label": "Decision feedback and packet follow-up",
                "evidence_sources": [
                    {
                        "file": browser_file,
                        "cases": [
                            "test_propertyquarry_decision_to_clippy_to_packet_followup_flow_in_browser",
                            "test_propertyquarry_packet_tracks_followup_state_in_browser",
                        ],
                    }
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-authenticated-release-gate.json",
                    "required_profile": "launch",
                },
            },
            {
                "journey_id": "notifications",
                "label": "Alert controls, channel preferences, and external Telegram delivery",
                "evidence_sources": [
                    {
                        "file": browser_file,
                        "cases": [
                            "test_propertyquarry_account_notifications_save_multi_channel_preferences_in_real_browser",
                            "test_propertyquarry_browser_alert_button_toggles_enabled_state",
                        ],
                    }
                ],
                "live_requirement": {
                    "status": "not_evaluated",
                    "authority": "_completion/smoke/property-live-notification-delivery.json",
                    "required_profile": "launch",
                },
            },
        ],
    }


def _write_seed(root: Path) -> None:
    (root / SEED).parent.mkdir(parents=True, exist_ok=True)
    (root / SEED).write_text(
        json.dumps(
            {
                "product": "propertyquarry",
                "surface": "propertyquarry_flagship_release_control",
                "release_claim": {"summary": "browser proof must match the flagship claim"},
                "browser_workflow_proof": {
                    "proof_target": "propertyquarry",
                    "expected_browser_signals": ["/app/properties", "/app/research"],
                    "evidence_sources": _evidence_sources(),
                },
                "journey_evidence_matrix": _journey_evidence_matrix(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_browser_workflow_proof_passes_when_both_lanes_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_seed(tmp_path)
    runtime_commit_sha = "a" * 40
    monkeypatch.setattr(
        browser_proof_materializer,
        "build_source_binding",
        lambda *_args, **_kwargs: {"code_commit": runtime_commit_sha},
    )

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

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner, require_source_binding=True)

    assert receipt["status"] == "pass"
    assert release_proof_baseline.approved_baseline_integrity_blockers() == []
    assert receipt["contract_name"] == "ea.browser_workflow_proof"
    assert receipt["proof_target"] == "propertyquarry"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == []
    assert receipt["approved_baseline"] == release_proof_baseline.approved_baseline_binding()
    assert receipt["expected_browser_signals"] == ["/app/properties", "/app/research"]
    assert receipt["source_backed_journey_proof"]["test_file"] == "tests/test_propertyquarry_workspace_redesign.py"
    assert receipt["source_backed_journey_proof"]["cases"] == browser_proof_materializer.SOURCE_BACKED_CASES
    assert receipt["source_backed_journey_proof"] == receipt["source_backed_journey_proofs"][0]
    assert [lane["test_file"] for lane in receipt["source_backed_journey_proofs"]] == [
        browser_proof_materializer.SOURCE_BACKED_TEST_FILE,
        browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE,
    ]
    assert [lane["required_case_count"] for lane in receipt["source_backed_journey_proofs"]] == [7, 1]
    assert receipt["source_backed_journey_proofs"][1]["cases"] == browser_proof_materializer.EVIDENCE_OVERLAY_CASES
    assert receipt["real_browser_e2e_proof"]["test_file"] == "tests/e2e/test_propertyquarry_greenfield_browser.py"
    assert receipt["real_browser_e2e_proof"]["cases"] == browser_proof_materializer.REAL_BROWSER_CASES
    assert len(browser_proof_materializer.REAL_BROWSER_CASES) == 16
    assert receipt["real_browser_e2e_proof"]["required_case_count"] == 16
    assert receipt["real_browser_e2e_proof"]["selected_count"] == 16
    assert receipt["real_browser_e2e_proof"]["executed_count"] == 16
    assert receipt["real_browser_e2e_proof"]["outcome_counts"]["passed"] == 16
    matrix = receipt["journey_evidence_matrix"]
    assert matrix["status"] == "pass"
    assert matrix["runtime_commit_sha"] == runtime_commit_sha
    assert matrix["required_journey_ids"] == list(browser_proof_materializer.REQUIRED_JOURNEY_IDS)
    assert [row["journey_id"] for row in matrix["rows"]] == list(browser_proof_materializer.REQUIRED_JOURNEY_IDS)
    assert all(row["proof_status"] == "pass" for row in matrix["rows"])
    assert all(row["live_requirement"]["status"] == "not_evaluated" for row in matrix["rows"])
    packets_tours = next(row for row in matrix["rows"] if row["journey_id"] == "packets_tours")
    assert packets_tours["evidence_sources"] == [
        {
            "file": browser_proof_materializer.REAL_BROWSER_TEST_FILE,
            "cases": list(browser_proof_materializer.REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES),
            "lane_status": "pass",
        }
    ]

    mapped_cases = {
        browser_proof_materializer.SOURCE_BACKED_TEST_FILE: set(),
        browser_proof_materializer.REAL_BROWSER_TEST_FILE: set(),
        browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE: set(),
    }
    for row in matrix["rows"]:
        for evidence_source in row["evidence_sources"]:
            mapped_cases[evidence_source["file"]].update(evidence_source["cases"])
    assert mapped_cases[browser_proof_materializer.SOURCE_BACKED_TEST_FILE] == set(
        browser_proof_materializer.SOURCE_BACKED_CASES
    )
    assert mapped_cases[browser_proof_materializer.REAL_BROWSER_TEST_FILE] == set(
        browser_proof_materializer.REAL_BROWSER_CASES
    )
    assert mapped_cases[browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE] == set(
        browser_proof_materializer.EVIDENCE_OVERLAY_CASES
    )


def test_release_proof_baseline_fingerprint_is_literal_and_detects_payload_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert release_proof_baseline.APPROVED_BASELINE_SHA256 == (
        "c9403bfba909e95ef8e0ded9c2c915c586e448db55f0e98f466d3ba3a166dcc9"
    )
    weakened_payload = json.loads(
        json.dumps(release_proof_baseline._baseline_payload())
    )
    weakened_payload["evidence_sources"][0]["cases"][0] = "test_unapproved_weakened_entry"
    weakened_payload["journeys"][2]["evidence_sources"][0]["cases"][0] = (
        "test_unapproved_weakened_entry"
    )
    monkeypatch.setattr(
        release_proof_baseline,
        "_baseline_payload",
        lambda: weakened_payload,
    )

    blockers = release_proof_baseline.approved_baseline_integrity_blockers()

    assert any("payload fingerprint does not match the pinned baseline" in reason for reason in blockers)
    assert release_proof_baseline.approved_baseline_binding()["sha256"] == (
        "c9403bfba909e95ef8e0ded9c2c915c586e448db55f0e98f466d3ba3a166dcc9"
    )


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_blocker"),
    (
        ("product", "executive-assistant", "product must be the exact standalone target propertyquarry"),
        (
            "surface",
            "ea_flagship_release_control",
            "surface must be the exact standalone surface propertyquarry_flagship_release_control",
        ),
        (
            "proof_target",
            "executive-assistant",
            "proof target must be the exact standalone target propertyquarry",
        ),
    ),
)
def test_browser_workflow_proof_blocks_wrong_standalone_target_even_when_all_lanes_pass(
    tmp_path: Path,
    field: str,
    bad_value: str,
    expected_blocker: str,
) -> None:
    _write_seed(tmp_path)
    seed_path = tmp_path / SEED
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    if field == "proof_target":
        seed["browser_workflow_proof"][field] = bad_value
    else:
        seed[field] = bad_value
    seed_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    def passing_runner(
        root: Path,
        *,
        python_bin: str,
        test_file: str,
        cases: list[str],
        real_browser: bool,
    ) -> dict[str, object]:
        del real_browser
        return {
            "status": "pass",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 0,
            "limitations": [],
            "outcome_counts": {
                "passed": len(cases),
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "xfailed": 0,
                "xpassed": 0,
            },
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=passing_runner)

    assert receipt["status"] == "blocked"
    assert any(expected_blocker in reason for reason in receipt["blocking_reasons"])


def test_browser_receipt_stable_write_heals_sha256_but_ignores_generated_at_only_change(
    tmp_path: Path,
) -> None:
    output = tmp_path / "browser-receipt.json"
    expected = {
        "generated_at": "2026-07-17T03:00:00Z",
        "status": "pass",
        "source_binding": {"seed": {"sha256": "a" * 64, "git_blob_oid": "1" * 40}},
    }
    stale = json.loads(json.dumps(expected))
    stale["generated_at"] = "2026-07-17T02:00:00Z"
    stale["source_binding"]["seed"]["sha256"] = "b" * 64
    output.write_text(json.dumps(stale), encoding="utf-8")

    browser_proof_materializer._write_json_stable(output, expected)

    assert json.loads(output.read_text(encoding="utf-8")) == expected
    generated_at_only = json.loads(json.dumps(expected))
    generated_at_only["generated_at"] = "2026-07-17T04:00:00Z"
    browser_proof_materializer._write_json_stable(output, generated_at_only)
    assert json.loads(output.read_text(encoding="utf-8")) == expected


@pytest.mark.parametrize("journey_id", list(browser_proof_materializer.REQUIRED_JOURNEY_IDS))
def test_browser_workflow_proof_blocks_self_consistent_weakened_seed_for_every_journey(
    tmp_path: Path,
    journey_id: str,
) -> None:
    _write_seed(tmp_path)
    seed_file = tmp_path / SEED
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    row = next(
        item
        for item in seed["journey_evidence_matrix"]["rows"]
        if item["journey_id"] == journey_id
    )
    row_source = row["evidence_sources"][0]
    approved_case = row_source["cases"][0]
    weakened_case = f"test_unapproved_weakened_{journey_id}"
    row_source["cases"][0] = weakened_case
    top_level_source = next(
        item
        for item in seed["browser_workflow_proof"]["evidence_sources"]
        if item["file"] == row_source["file"]
    )
    top_level_source["cases"][top_level_source["cases"].index(approved_case)] = weakened_case
    seed_file.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    executed_cases: list[str] = []

    def fake_runner(
        root: Path,
        *,
        python_bin: str,
        test_file: str,
        cases: list[str],
        real_browser: bool,
    ) -> dict[str, object]:
        del real_browser
        executed_cases.extend(cases)
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

    assert receipt["status"] == "blocked"
    assert "browser evidence sources do not match the immutable approved baseline" in receipt["blocking_reasons"]
    assert (
        f"journey {journey_id} evidence sources do not match the immutable approved baseline"
        in receipt["blocking_reasons"]
    )
    assert weakened_case not in executed_cases
    approved_sources = release_proof_baseline.approved_evidence_sources()
    expected_execution_order = [
        case
        for source in approved_sources
        if "/e2e/" not in source["file"]
        for case in source["cases"]
    ] + [
        case
        for source in approved_sources
        if "/e2e/" in source["file"]
        for case in source["cases"]
    ]
    assert executed_cases == expected_execution_order


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
            "output_excerpt": (
                [f"{len(cases)} skipped, 20 deselected in 0.79s"]
                if real_browser
                else [f"{len(cases)} passed"]
            ),
            "limitations": ["real browser E2E did not run to completion"] if real_browser else [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "preview_only"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == ["real browser E2E did not run to completion"]
    assert receipt["real_browser_e2e_proof"]["status"] == "preview_only"
    assert receipt["real_browser_e2e_proof"]["required_case_count"] == len(
        browser_proof_materializer.REAL_BROWSER_CASES
    )
    assert receipt["real_browser_e2e_proof"]["selected_count"] == len(
        browser_proof_materializer.REAL_BROWSER_CASES
    )
    assert receipt["real_browser_e2e_proof"]["executed_count"] == 0
    assert receipt["real_browser_e2e_proof"]["outcome_counts"]["skipped"] == len(
        browser_proof_materializer.REAL_BROWSER_CASES
    )


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


def test_pytest_lane_runner_isolates_release_runtime_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}
    for key in browser_proof_materializer.PYTEST_ISOLATED_ENV_KEYS:
        monkeypatch.setenv(key, f"release-value-for-{key.lower()}")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/tmp/playwright-browsers")

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        captured_env.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="2 passed in 0.01s\n", stderr="")

    monkeypatch.setattr(browser_proof_materializer.subprocess, "run", fake_run)

    lane = browser_proof_materializer._run_pytest_cases(
        tmp_path,
        python_bin="python3",
        test_file="tests/test_propertyquarry_workspace_redesign.py",
        cases=["first_source_case", "second_source_case"],
        real_browser=False,
    )

    assert lane["status"] == "pass"
    assert all(key not in captured_env for key in browser_proof_materializer.PYTEST_ISOLATED_ENV_KEYS)
    assert captured_env["PLAYWRIGHT_BROWSERS_PATH"] == "/tmp/playwright-browsers"
    assert "ea" in captured_env["PYTHONPATH"].split(":")


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
            "output_excerpt": [] if real_browser else [f"{len(cases)} passed"],
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
            "output_excerpt": [f"{len(cases)} skipped"] if real_browser else [f"{len(cases)} passed"],
            "limitations": limitations,
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "preview_only"
    assert receipt["blocking_reasons"] == []
    assert receipt["current_limitations"] == ["uvicorn is not installed in the selected Python environment"]


def test_browser_workflow_proof_blocks_when_source_backed_lane_fails(tmp_path: Path) -> None:
    _write_seed(tmp_path)

    def fake_runner(root: Path, *, python_bin: str, test_file: str, cases: list[str], real_browser: bool) -> dict[str, object]:
        if real_browser or test_file == browser_proof_materializer.SOURCE_BACKED_TEST_FILE:
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
        return {
            "status": "blocked",
            "command": "pytest",
            "cwd": root.as_posix(),
            "python_bin": python_bin,
            "test_file": test_file,
            "cases": cases,
            "exit_code": 1,
            "duration_seconds": 1.0,
            "output_excerpt": [f"{len(cases)} failed"],
            "limitations": ["application import path is broken"],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "blocked"
    assert (
        "source-backed browser journey proof is not passing: "
        + browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE
        in receipt["blocking_reasons"]
    )
    assert receipt["source_backed_journey_proofs"][0]["status"] == "pass"
    assert receipt["source_backed_journey_proofs"][1]["status"] == "blocked"
    assert receipt["current_limitations"] == ["application import path is broken"]


def test_browser_workflow_proof_blocks_when_journey_matrix_row_is_missing(tmp_path: Path) -> None:
    _write_seed(tmp_path)
    seed_file = tmp_path / SEED
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    seed["journey_evidence_matrix"]["rows"] = seed["journey_evidence_matrix"]["rows"][:-1]
    seed_file.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

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
            "output_excerpt": [f"{len(cases)} passed"],
            "limitations": [],
        }

    receipt = build_receipt(tmp_path, seed_path=SEED, runner=fake_runner)

    assert receipt["status"] == "blocked"
    assert receipt["journey_evidence_matrix"]["status"] == "blocked"
    assert receipt["journey_evidence_matrix"]["rows"][-1]["journey_id"] == "notifications"
    assert receipt["journey_evidence_matrix"]["rows"][-1]["proof_status"] == "blocked"
    assert "journey evidence matrix rows do not exactly cover the required journeys" in receipt["blocking_reasons"]
    assert any(reason.startswith("journey notifications:") for reason in receipt["blocking_reasons"])


def test_browser_workflow_proof_blocks_a_self_consistent_weakened_packets_tours_seed(
    tmp_path: Path,
) -> None:
    _write_seed(tmp_path)
    seed_file = tmp_path / SEED
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    packets_tours = next(
        row for row in seed["journey_evidence_matrix"]["rows"] if row["journey_id"] == "packets_tours"
    )
    packets_tours["evidence_sources"][0]["cases"] = [
        browser_proof_materializer.REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES[0]
    ]
    seed_file.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    def fake_runner(
        root: Path,
        *,
        python_bin: str,
        test_file: str,
        cases: list[str],
        real_browser: bool,
    ) -> dict[str, object]:
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

    assert receipt["status"] == "blocked"
    assert receipt["journey_evidence_matrix"]["status"] == "blocked"
    assert (
        "journey packets_tours: must map the exact ordered hosted, recovery, generated, mobile, "
        "and unavailable-tour cases"
        in receipt["blocking_reasons"]
    )


def test_browser_workflow_proof_rejects_non_object_journey_rows() -> None:
    seed = {
        "browser_workflow_proof": {"evidence_sources": _evidence_sources()},
        "journey_evidence_matrix": _journey_evidence_matrix(),
    }
    seed["journey_evidence_matrix"]["rows"].append("unexpected")
    source_lanes = [
        {"status": "pass", "test_file": browser_proof_materializer.SOURCE_BACKED_TEST_FILE},
        {"status": "pass", "test_file": browser_proof_materializer.EVIDENCE_OVERLAY_TEST_FILE},
    ]
    browser_lane = {"status": "pass", "test_file": browser_proof_materializer.REAL_BROWSER_TEST_FILE}

    matrix, blockers = browser_proof_materializer._build_journey_evidence_matrix(
        seed,
        source_backed=source_lanes,
        real_browser=browser_lane,
        source_binding={"code_commit": "a" * 40},
    )

    assert matrix["status"] == "blocked"
    assert "journey evidence matrix rows must contain only objects" in blockers


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


def test_browser_workflow_proof_stable_write_ignores_runner_local_metadata_but_keeps_source_identity(
    tmp_path: Path,
) -> None:
    output = tmp_path / "browser-proof.json"
    source_binding = {
        "version": 1,
        "code_commit": "a" * 40,
        "seed": {
            "path": ".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json",
            "git_blob_oid": "b" * 40,
        },
        "required_test_sources": [
            {
                "path": "tests/test_propertyquarry_workspace_redesign.py",
                "git_blob_oid": "c" * 40,
            }
        ],
    }
    local = {
        "contract_name": "ea.browser_workflow_proof",
        "generated_at": "2026-07-16T10:00:00Z",
        "status": "pass",
        "source_binding": source_binding,
        "source_backed_journey_proof": {
            "status": "pass",
            "command": "/usr/bin/python3 -m pytest -q tests/example.py::test_example",
            "cwd": "/tmp/propertyquarry-local",
            "python_bin": "/usr/bin/python3",
            "duration_seconds": 10.25,
            "output_excerpt": ["1 passed in 10.00s"],
            "exit_code": 0,
        },
    }
    output.write_text(json.dumps(local, indent=2) + "\n", encoding="utf-8")
    original_bytes = output.read_bytes()

    hosted = json.loads(json.dumps(local))
    hosted["generated_at"] = "2026-07-16T11:00:00Z"
    hosted_lane = hosted["source_backed_journey_proof"]
    hosted_lane["command"] = "/opt/hostedtoolcache/Python/3.12/bin/python -m pytest -q tests/example.py::test_example"
    hosted_lane["cwd"] = "/home/runner/work/property/property"
    hosted_lane["python_bin"] = "/opt/hostedtoolcache/Python/3.12/bin/python"
    hosted_lane["duration_seconds"] = 1.5
    hosted_lane["output_excerpt"] = ["1 passed in 1.00s"]

    browser_proof_materializer._write_json_stable(output, hosted)

    assert output.read_bytes() == original_bytes

    hosted["source_binding"]["required_test_sources"][0]["git_blob_oid"] = "d" * 40
    browser_proof_materializer._write_json_stable(output, hosted)

    assert output.read_bytes() != original_bytes
    assert (
        json.loads(output.read_text(encoding="utf-8"))["source_binding"]["required_test_sources"][0]["git_blob_oid"]
        == "d" * 40
    )
