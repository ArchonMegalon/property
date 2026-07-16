from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.propertyquarry_release_receipt_binding import build_source_binding


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_ea_flagship_release_gate.py"
OUTPUT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
TRUTH_PLANE = Path(".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md")
BROWSER_PROOF = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
PRODUCT_CANON_DOCS = [
    Path(".codex-design/ea/README.md"),
    Path(".codex-design/ea/START_HERE.md"),
    Path(".codex-design/ea/VISION.md"),
    Path(".codex-design/ea/PUBLIC_NAVIGATION.yaml"),
    Path(".codex-design/ea/APP_NAVIGATION.yaml"),
    Path(".codex-design/ea/SURFACE_DESIGN_SYSTEM.md"),
    Path(".codex-design/ea/FIRST_VALUE_JOURNEY.md"),
    Path(".codex-design/ea/COPY_PRINCIPLES.md"),
    Path(".codex-design/ea/METRICS_AND_SLOS.yaml"),
    Path(".codex-design/ea/LTD_INTEGRATION_MAP.md"),
]
JOURNEY_IDS = [
    "public_entry",
    "onboarding_auth",
    "search_ranking",
    "shortlist_research_revisit",
    "account_pricing_privacy_recovery",
    "packets_tours",
    "feedback",
    "notifications",
]


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_flagship_sources(root: Path) -> dict[str, object]:
    tracked = sorted(
        {
            SEED.as_posix(),
            TRUTH_PLANE.as_posix(),
            *(path.as_posix() for path in PRODUCT_CANON_DOCS),
            "README.md",
            "RUNBOOK.md",
            "RELEASE_CHECKLIST.md",
            "PRODUCT_RELEASE_CHECKLIST.md",
            "tests/test_propertyquarry_workspace_redesign.py",
            "tests/e2e/test_propertyquarry_greenfield_browser.py",
        }
    )
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "PropertyQuarry Fixture")
    _git(root, "config", "user.email", "propertyquarry-fixture@example.invalid")
    _git(root, "add", "--", *tracked)
    _git(root, "commit", "--quiet", "-m", "fixture: immutable flagship sources")
    seed = json.loads((root / SEED).read_text(encoding="utf-8"))
    return build_source_binding(
        root,
        seed_path=SEED,
        evidence_sources=seed["browser_workflow_proof"]["evidence_sources"],
    )


def _passing_browser_lane(root: Path, *, test_file: str, cases: list[str]) -> dict[str, object]:
    return {
        "status": "pass",
        "command": "python3 -m pytest -q "
        + " ".join(f"{test_file}::{case}" for case in cases),
        "cwd": root.as_posix(),
        "python_bin": "python3",
        "test_file": test_file,
        "cases": cases,
        "required_case_count": len(cases),
        "selected_count": len(cases),
        "executed_count": len(cases),
        "outcome_counts": {
            "passed": len(cases),
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "xfailed": 0,
            "xpassed": 0,
        },
        "exit_code": 0,
        "duration_seconds": 0.01,
        "output_excerpt": [f"{len(cases)} passed"],
        "limitations": [],
    }


def _journey_matrix(
    *,
    source_file: str,
    source_case: str,
    browser_file: str,
    browser_case: str,
    receipt: bool = False,
    runtime_commit_sha: str = "",
) -> dict[str, object]:
    row_sources = {
        "public_entry": [(source_file, [source_case])],
        "onboarding_auth": [(source_file, [source_case])],
        "search_ranking": [(source_file, [source_case]), (browser_file, [browser_case])],
        "shortlist_research_revisit": [(browser_file, [browser_case])],
        "account_pricing_privacy_recovery": [(source_file, [source_case])],
        "packets_tours": [(browser_file, [browser_case])],
        "feedback": [(browser_file, [browser_case])],
        "notifications": [(browser_file, [browser_case])],
    }
    rows: list[dict[str, object]] = []
    for journey_id in JOURNEY_IDS:
        sources = [
            {
                "file": test_file,
                "cases": cases,
                **({"lane_status": "pass"} if receipt else {}),
            }
            for test_file, cases in row_sources[journey_id]
        ]
        row: dict[str, object] = {
            "journey_id": journey_id,
            "label": journey_id.replace("_", " ").title(),
            "evidence_sources": sources,
            "live_requirement": {
                "status": "not_evaluated",
                "authority": f"_completion/smoke/property-live-{journey_id}.json",
                "required_profile": "launch",
            },
        }
        if receipt:
            row["proof_status"] = "pass"
            row["blocking_reasons"] = []
        rows.append(row)
    matrix: dict[str, object] = {
        "version": 1,
        "readiness_scope": "candidate_source_and_browser_proof",
        "required_journey_ids": JOURNEY_IDS,
        "rows": rows,
    }
    if receipt:
        matrix["status"] = "pass"
        matrix["runtime_commit_sha"] = runtime_commit_sha
    return matrix


def _write_minimal_flagship_tree(
    root: Path,
    *,
    browser_proof_status: str | None = None,
) -> None:
    (root / SEED).parent.mkdir(parents=True, exist_ok=True)
    (root / TRUTH_PLANE).parent.mkdir(parents=True, exist_ok=True)
    (root / OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    (root / BROWSER_PROOF).parent.mkdir(parents=True, exist_ok=True)
    for rel in PRODUCT_CANON_DOCS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# canon\n", encoding="utf-8")

    seed = {
        "product": "propertyquarry",
        "surface": "propertyquarry_flagship_release_control",
        "version": 1,
        "truth_plane": {
            "source": ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md",
            "legacy_history": "MILESTONE.json",
        },
        "release_claim": {
            "summary": "The standalone PropertyQuarry surface can only claim flagship-grade release truth when browser proof and release verification agree.",
            "required_conditions": [
                "EA product surface canon exists and names the public navigation, app navigation, first-value journey, surface system, copy rules, and LTD delivery map",
                "source-backed browser proof renders the standalone PropertyQuarry workspace",
                "real browser E2E opens ranked PropertyQuarry results on desktop",
                "real browser E2E proves the PropertyQuarry workbench remains usable on mobile",
                "release asset verification knows the EA flagship truth plane, the EA product surface canon, and the gate seed",
                "release checklists cite the EA truth plane and the EA product surface canon instead of using MILESTONE green as the oracle",
            ],
        },
        "ea_product_canon": {
            "source_root": ".codex-design/ea",
            "scope_label": "EA product surface canon",
            "required_docs": [path.as_posix() for path in PRODUCT_CANON_DOCS],
        },
        "browser_workflow_proof": {
            "proof_target": "propertyquarry",
            "expected_browser_signals": ["/app/properties", "/app/research"],
            "evidence_sources": [
                {
                    "file": "tests/test_propertyquarry_workspace_redesign.py",
                    "cases": ["test_propertyquarry_workspace_routes_render_greenfield_surfaces"],
                },
                {
                    "file": "tests/e2e/test_propertyquarry_greenfield_browser.py",
                    "cases": ["test_propertyquarry_greenfield_workspace_in_real_browser"],
                },
            ]
        },
        "verification_binding": {
            "primary_verifier": "scripts/verify_release_assets.sh",
            "supporting_test": "tests/test_flagship_truth_plane.py",
        },
    }
    sources = seed["browser_workflow_proof"]["evidence_sources"]
    seed["journey_evidence_matrix"] = _journey_matrix(
        source_file=sources[0]["file"],
        source_case=sources[0]["cases"][0],
        browser_file=sources[1]["file"],
        browser_case=sources[1]["cases"][0],
    )
    (root / SEED).write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    (root / TRUTH_PLANE).write_text("# EA flagship truth plane\n", encoding="utf-8")
    for rel in ("README.md", "RUNBOOK.md", "RELEASE_CHECKLIST.md", "PRODUCT_RELEASE_CHECKLIST.md"):
        (root / rel).write_text(
            "\n".join(
                [
                    "EA_FLAGSHIP_TRUTH_PLANE.md",
                    "EA_FLAGSHIP_RELEASE_GATE.json",
                    "EA_FLAGSHIP_RELEASE_GATE.generated.json",
                    "scripts/materialize_ea_flagship_release_gate.py",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    for rel in ("tests/test_propertyquarry_workspace_redesign.py", "tests/e2e/test_propertyquarry_greenfield_browser.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# browser proof source\n", encoding="utf-8")
    source_binding = _commit_flagship_sources(root)
    if browser_proof_status is not None:
        browser_proof: dict[str, object] = {
            "contract_name": "ea.browser_workflow_proof",
            "kind": "proof_receipt",
            "surface": "browser_workflow_proof",
            "version": 1,
            "generated_at": "2026-07-13T12:00:00Z",
            "generated_by": "scripts/materialize_ea_browser_workflow_proof.py",
            "product": "propertyquarry",
            "status": browser_proof_status,
            "proof_target": "propertyquarry",
            "release_claim_summary": seed["release_claim"]["summary"],
            "expected_browser_signals": seed["browser_workflow_proof"][
                "expected_browser_signals"
            ],
            "source_binding": source_binding,
            "journey_evidence_matrix": _journey_matrix(
                source_file=sources[0]["file"],
                source_case=sources[0]["cases"][0],
                browser_file=sources[1]["file"],
                browser_case=sources[1]["cases"][0],
                receipt=True,
                runtime_commit_sha=str(source_binding["code_commit"]),
            ),
            "blocking_reasons": [],
            "current_limitations": [],
        }
        if browser_proof_status == "pass":
            browser_proof.update(
                {
                    "source_backed_journey_proof": _passing_browser_lane(
                        root,
                        test_file=sources[0]["file"],
                        cases=sources[0]["cases"],
                    ),
                    "real_browser_e2e_proof": _passing_browser_lane(
                        root,
                        test_file=sources[1]["file"],
                        cases=sources[1]["cases"],
                    ),
                }
            )
        (root / BROWSER_PROOF).write_text(
            json.dumps(browser_proof, indent=2) + "\n",
            encoding="utf-8",
        )


def test_materializer_writes_preview_only_receipt_without_browser_execution_receipt(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path)

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["product"] == "propertyquarry"
    assert receipt["surface"] == "propertyquarry_flagship_release_control"
    assert receipt["version"] == 1
    assert receipt["status"] == "preview_only"
    assert len(receipt["source_binding"]["code_commit"]) == 40
    assert receipt["truth_plane"]["source"] == ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md"
    assert receipt["ea_product_canon"]["source_root"] == ".codex-design/ea"
    assert receipt["ea_product_canon"]["scope_label"] == "EA product surface canon"
    assert receipt["ea_product_canon"]["all_required_docs_present"] is True
    assert receipt["browser_workflow_proof"]["proof_target"] == "propertyquarry"
    assert receipt["browser_workflow_proof"]["published_receipt_present"] is False
    assert receipt["browser_workflow_proof"]["source_files_present"][0]["present"] is True
    assert receipt["browser_workflow_proof"]["source_files_present"][1]["present"] is True
    assert receipt["journey_evidence_matrix"]["status"] == "not_evaluated"
    assert receipt["journey_evidence_matrix"]["runtime_commit_sha"] == receipt["source_binding"]["code_commit"]
    assert receipt["journey_evidence_matrix"]["required_journey_ids"] == JOURNEY_IDS
    assert all(row["proof_status"] == "not_evaluated" for row in receipt["journey_evidence_matrix"]["rows"])
    assert "no published browser execution receipt is attached yet" in receipt["current_limitations"]
    assert receipt["blocking_reasons"] == []
    assert "preview_only" in receipt["operator_summary"]


def test_materializer_can_publish_pass_when_browser_execution_receipt_exists(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path, browser_proof_status="pass")

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["status"] == "pass"
    browser_proof = json.loads((tmp_path / BROWSER_PROOF).read_text(encoding="utf-8"))
    assert receipt["source_binding"] == browser_proof["source_binding"]
    assert receipt["browser_receipt_binding"]["path"] == BROWSER_PROOF.as_posix()
    assert receipt["browser_workflow_proof"]["published_receipt_present"] is True
    assert receipt["browser_workflow_proof"]["published_receipt"] == BROWSER_PROOF.as_posix()
    assert receipt["current_limitations"] == []
    assert receipt["blocking_reasons"] == []
    assert receipt["ea_product_canon"]["all_required_docs_present"] is True
    assert receipt["journey_evidence_matrix"]["status"] == "pass"
    assert receipt["journey_evidence_matrix"]["runtime_commit_sha"] == receipt["source_binding"]["code_commit"]
    assert all(row["proof_status"] == "pass" for row in receipt["journey_evidence_matrix"]["rows"])
    assert "green" in receipt["operator_summary"]


def test_materializer_surfaces_browser_proof_blockers_when_published_receipt_is_blocked(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path)
    (tmp_path / BROWSER_PROOF).write_text(
        json.dumps(
            {
                "status": "blocked",
                "blocking_reasons": [
                    "source-backed browser journey proof is not passing",
                    "real browser E2E proof is not passing",
                ],
                "current_limitations": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["status"] == "blocked"
    assert "browser workflow proof: source-backed browser journey proof is not passing" in receipt["blocking_reasons"]
    assert "browser workflow proof: real browser E2E proof is not passing" in receipt["blocking_reasons"]


def test_materializer_blocks_internally_inconsistent_browser_pass_with_all_real_browser_cases_skipped(
    tmp_path: Path,
) -> None:
    _write_minimal_flagship_tree(tmp_path)
    (tmp_path / BROWSER_PROOF).write_text(
        json.dumps(
            {
                "contract_name": "ea.browser_workflow_proof",
                "product": "propertyquarry",
                "status": "pass",
                "proof_target": "propertyquarry",
                "blocking_reasons": [],
                "current_limitations": [],
                "source_backed_journey_proof": {
                    "status": "pass",
                    "test_file": "tests/test_propertyquarry_workspace_redesign.py",
                    "cases": ["test_propertyquarry_workspace_routes_render_greenfield_surfaces"],
                    "exit_code": 0,
                    "output_excerpt": ["1 passed"],
                    "limitations": [],
                },
                "real_browser_e2e_proof": {
                    "status": "pass",
                    "test_file": "tests/e2e/test_propertyquarry_greenfield_browser.py",
                    "cases": ["test_propertyquarry_greenfield_workspace_in_real_browser"],
                    "exit_code": 0,
                    "output_excerpt": ["1 skipped, 20 deselected in 0.79s"],
                    "limitations": ["real browser E2E did not run to completion"],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["status"] == "blocked"
    assert (
        "browser workflow proof: published pass lacks completed real browser E2E proof"
        in receipt["blocking_reasons"]
    )
    assert "green" not in receipt["operator_summary"]


def test_materializer_blocks_stale_pass_that_does_not_match_current_seed_nodes(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path, browser_proof_status="pass")
    stale = json.loads((tmp_path / BROWSER_PROOF).read_text(encoding="utf-8"))
    stale["real_browser_e2e_proof"]["cases"] = ["test_previous_release_browser_case"]
    stale["real_browser_e2e_proof"]["required_case_count"] = 1
    stale["real_browser_e2e_proof"]["executed_count"] = 1
    stale["real_browser_e2e_proof"]["outcome_counts"] = {"passed": 1}
    (tmp_path / BROWSER_PROOF).write_text(json.dumps(stale), encoding="utf-8")

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked"
    assert (
        "browser workflow proof: published pass lacks completed real browser E2E proof"
        in receipt["blocking_reasons"]
    )


def test_materializer_blocks_pass_with_a_tampered_journey_runtime_binding(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path, browser_proof_status="pass")
    tampered = json.loads((tmp_path / BROWSER_PROOF).read_text(encoding="utf-8"))
    tampered["journey_evidence_matrix"]["runtime_commit_sha"] = "0" * 40
    (tmp_path / BROWSER_PROOF).write_text(json.dumps(tampered), encoding="utf-8")

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked"
    assert (
        "browser workflow proof: published pass journey matrix is not bound to the browser receipt runtime commit"
        in receipt["blocking_reasons"]
    )
