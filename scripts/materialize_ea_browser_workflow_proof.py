#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if __package__:
    from .propertyquarry_release_receipt_binding import ReleaseBindingError, build_source_binding
    from . import propertyquarry_release_proof_baseline as release_proof_baseline
else:
    from propertyquarry_release_receipt_binding import ReleaseBindingError, build_source_binding
    import propertyquarry_release_proof_baseline as release_proof_baseline


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_OUTPUT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
SOURCE_BACKED_TEST_FILE = release_proof_baseline.PRIMARY_SOURCE_TEST_FILE
SOURCE_BACKED_CASES = list(release_proof_baseline.PRIMARY_SOURCE_CASES)
EVIDENCE_OVERLAY_TEST_FILE = release_proof_baseline.EVIDENCE_OVERLAY_TEST_FILE
EVIDENCE_OVERLAY_CASES = list(release_proof_baseline.EVIDENCE_OVERLAY_CASES)
REAL_BROWSER_TEST_FILE = release_proof_baseline.REAL_BROWSER_TEST_FILE
REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES = release_proof_baseline.PACKETS_TOURS_REAL_BROWSER_CASES
REAL_BROWSER_CASES = list(release_proof_baseline.REAL_BROWSER_CASES)
REQUIRED_JOURNEY_IDS = release_proof_baseline.APPROVED_REQUIRED_JOURNEY_IDS
PYTEST_OUTCOME_KEYS = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
VOLATILE_EXECUTION_KEYS = frozenset(
    {
        "as_of",
        "command",
        "created_at",
        "cwd",
        "duration_seconds",
        "generated_at",
        "git_branch",
        "git_head",
        "git_repo_root",
        "mtime_utc",
        "python_bin",
        "resolved_path",
        "review_due",
        "size_bytes",
        "source_path",
    }
)
PYTEST_OUTCOME_RE = re.compile(
    r"\b(?P<count>\d+)\s+(?P<outcome>passed|failed|skipped|errors?|xfailed|xpassed)\b",
    re.IGNORECASE,
)
PYTEST_ISOLATED_ENV_KEYS = (
    "DATABASE_URL",
    "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER",
    "EA_ALLOW_LOOPBACK_NO_AUTH",
    "EA_API_TOKEN",
    "EA_ARTIFACTS_DIR",
    "EA_CF_ACCESS_AUD",
    "EA_CF_ACCESS_TEAM_DOMAIN",
    "EA_DATABASE_URL",
    "EA_DEFAULT_PRINCIPAL_ID",
    "EA_HOST_PORT",
    "EA_LEDGER_BACKEND",
    "EA_MISMATCH_PRINCIPAL_ID",
    "EA_OPERATOR_PRINCIPAL_ID",
    "EA_OPERATOR_PRINCIPAL_IDS",
    "EA_OPERATOR_PRINCIPALS",
    "EA_PRINCIPAL_ID",
    "EA_RUNTIME_MODE",
    "EA_SIGNING_SECRET",
    "EA_STORAGE_BACKEND",
    "EA_STORAGE_FALLBACK_ALLOWED",
    "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER",
    "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
)


def _governed_evidence_sources(seed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    return (
        release_proof_baseline.approved_evidence_sources(),
        release_proof_baseline.approved_seed_baseline_blockers(seed),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_release_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in VOLATILE_EXECUTION_KEYS:
                continue
            if key.endswith("_git_head"):
                continue
            if key == "output_excerpt":
                normalized[key] = []
                continue
            normalized[key] = _normalize_release_value(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_release_value(item) for item in value]
    return value


def _write_json_stable(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if isinstance(existing, dict) and _normalize_release_value(existing) == _normalize_release_value(payload):
            return
    path.write_text(serialized, encoding="utf-8")


def _resolve_python_bin(root: Path) -> str:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python.as_posix()
    return sys.executable


def _with_pythonpath(existing: str, root: Path) -> str:
    entries = [item for item in existing.split(os.pathsep) if item]
    for candidate in ("ea", (root / "ea").as_posix()):
        if candidate not in entries:
            entries.insert(0, candidate)
    return os.pathsep.join(entries)


def _truncate_output(text: str, *, limit: int = 40) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[:limit]


def _pytest_outcome_counts(text: str) -> dict[str, int]:
    counts = {key: 0 for key in PYTEST_OUTCOME_KEYS}
    for line in reversed(text.splitlines()):
        matches = list(PYTEST_OUTCOME_RE.finditer(line))
        if not matches:
            continue
        for match in matches:
            outcome = match.group("outcome").lower()
            if outcome == "error":
                outcome = "errors"
            counts[outcome] = int(match.group("count"))
        break
    return counts


def _extract_limitations(text: str, *, real_browser: bool) -> list[str]:
    lowered = text.lower()
    limitations: list[str] = []
    if "no module named 'uvicorn'" in lowered or 'no module named "uvicorn"' in lowered:
        limitations.append("uvicorn is not installed in the selected Python environment")
    if "no module named 'playwright'" in lowered or 'no module named "playwright"' in lowered:
        limitations.append("playwright is not installed in the selected Python environment")
    if "executable doesn't exist" in lowered or "browser_type.launch" in lowered:
        limitations.append("playwright browser binaries are not installed")
    if "skipped" in lowered and not limitations:
        limitations.append(
            "real browser E2E did not run to completion"
            if real_browser
            else "source-backed browser journey proof did not run to completion"
        )
    return limitations


def _lane_completion(
    result: dict[str, Any],
    *,
    required_cases: list[str],
    real_browser: bool,
) -> dict[str, Any]:
    normalized = dict(result)
    raw_counts = normalized.get("outcome_counts")
    if isinstance(raw_counts, dict):
        counts = {key: int(raw_counts.get(key) or 0) for key in PYTEST_OUTCOME_KEYS}
    else:
        counts = _pytest_outcome_counts("\n".join(str(line) for line in normalized.get("output_excerpt") or []))

    required_case_count = len(required_cases)
    executed_count = sum(counts[key] for key in ("passed", "failed", "errors", "xfailed", "xpassed"))
    selected_count = executed_count + counts["skipped"]
    all_required_cases_passed = (
        int(normalized.get("exit_code") or 0) == 0
        and required_case_count > 0
        and counts["passed"] >= required_case_count
        and counts["failed"] == 0
        and counts["skipped"] == 0
        and counts["errors"] == 0
        and counts["xfailed"] == 0
        and counts["xpassed"] == 0
    )

    reported_status = str(normalized.get("status") or "blocked").strip().lower()
    if reported_status == "pass" and not all_required_cases_passed:
        has_hard_failure = any(counts[key] for key in ("failed", "errors", "xfailed", "xpassed"))
        normalized["status"] = "preview_only" if real_browser and counts["skipped"] and not has_hard_failure else "blocked"
        limitations = [str(item) for item in normalized.get("limitations") or [] if str(item).strip()]
        if counts["skipped"]:
            limitations.append(
                "real browser E2E did not run to completion"
                if real_browser
                else "source-backed browser journey proof did not run to completion"
            )
        elif executed_count == 0:
            limitations.append(
                "required real browser E2E lane reported zero executed cases"
                if real_browser
                else "required source-backed browser journey lane reported zero executed cases"
            )
        else:
            limitations.append(
                "required real browser E2E cases did not all pass"
                if real_browser
                else "required source-backed browser journey cases did not all pass"
            )
        normalized["limitations"] = list(dict.fromkeys(limitations))

    normalized["required_case_count"] = required_case_count
    normalized["selected_count"] = selected_count
    normalized["executed_count"] = executed_count
    normalized["outcome_counts"] = counts
    return normalized


def _unavailable_lane(*, test_file: str, cases: list[str], real_browser: bool, limitation: str) -> dict[str, Any]:
    return _lane_completion(
        {
            "status": "blocked",
            "test_file": test_file,
            "cases": cases,
            "exit_code": 1,
            "output_excerpt": [],
            "limitations": [limitation],
            "outcome_counts": {key: 0 for key in PYTEST_OUTCOME_KEYS},
        },
        required_cases=cases,
        real_browser=real_browser,
    )


def _build_journey_evidence_matrix(
    seed: dict[str, Any],
    *,
    source_backed: list[dict[str, Any]],
    real_browser: dict[str, Any],
    source_binding: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    raw_matrix = seed.get("journey_evidence_matrix")
    approved_matrix_blockers = release_proof_baseline.approved_journey_matrix_blockers(raw_matrix)
    blockers: list[str] = list(approved_matrix_blockers)
    if not isinstance(raw_matrix, dict):
        return {
            "version": 1,
            "status": "blocked",
            "runtime_commit_sha": str((source_binding or {}).get("code_commit") or ""),
            "required_journey_ids": list(REQUIRED_JOURNEY_IDS),
            "rows": [],
        }, list(dict.fromkeys(["journey evidence matrix is missing", *approved_matrix_blockers]))

    try:
        version = int(raw_matrix.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != 1:
        blockers.append("journey evidence matrix version must be 1")
    readiness_scope = str(raw_matrix.get("readiness_scope") or "").strip()
    if readiness_scope != "candidate_source_and_browser_proof":
        blockers.append("journey evidence matrix has the wrong readiness scope")
    raw_required_ids = raw_matrix.get("required_journey_ids")
    if not isinstance(raw_required_ids, list):
        raw_required_ids = []
        blockers.append("journey evidence matrix required IDs must be a list")
    required_ids = [str(item).strip() for item in raw_required_ids if str(item).strip()]
    if required_ids != list(REQUIRED_JOURNEY_IDS):
        blockers.append("journey evidence matrix required IDs are missing, reordered, or unexpected")

    raw_row_items = raw_matrix.get("rows")
    if not isinstance(raw_row_items, list):
        raw_row_items = []
        blockers.append("journey evidence matrix rows must be a list")
    raw_rows = [row for row in raw_row_items if isinstance(row, dict)]
    if len(raw_rows) != len(raw_row_items):
        blockers.append("journey evidence matrix rows must contain only objects")
    rows_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for row in raw_rows:
        journey_id = str(row.get("journey_id") or "").strip()
        if journey_id in rows_by_id:
            duplicate_ids.add(journey_id)
        elif journey_id:
            rows_by_id[journey_id] = row
    if duplicate_ids:
        blockers.append("journey evidence matrix has duplicate IDs: " + ", ".join(sorted(duplicate_ids)))
    if set(rows_by_id) != set(REQUIRED_JOURNEY_IDS):
        blockers.append("journey evidence matrix rows do not exactly cover the required journeys")

    governed_sources, evidence_source_blockers = _governed_evidence_sources(seed)
    blockers.extend(evidence_source_blockers)
    lanes: dict[str, dict[str, Any]] = {}
    for lane in [*source_backed, real_browser]:
        test_file = str(lane.get("test_file") or "").strip()
        if not test_file:
            continue
        if test_file in lanes:
            blockers.append(f"browser workflow proof produced duplicate evidence lane: {test_file}")
            continue
        lanes[test_file] = lane
    allowed_cases = {
        str(entry["file"]): set(str(case) for case in entry["cases"])
        for entry in governed_sources
    }
    mapped_cases = {path: set() for path in allowed_cases}
    rendered_rows: list[dict[str, Any]] = []
    for journey_id in REQUIRED_JOURNEY_IDS:
        row = rows_by_id.get(journey_id, {})
        row_blockers: list[str] = []
        label = str(row.get("label") or "").strip()
        if not label:
            row_blockers.append("label is missing")
        raw_evidence_sources = row.get("evidence_sources")
        if not isinstance(raw_evidence_sources, list):
            raw_evidence_sources = []
            row_blockers.append("evidence sources must be a list")
        evidence_sources = [entry for entry in raw_evidence_sources if isinstance(entry, dict)]
        if len(evidence_sources) != len(raw_evidence_sources):
            row_blockers.append("evidence sources must contain only objects")
        if not evidence_sources:
            row_blockers.append("evidence sources are missing")
        lane_statuses: list[str] = []
        rendered_sources: list[dict[str, Any]] = []
        for entry in evidence_sources:
            test_file = str(entry.get("file") or "").strip()
            raw_cases = entry.get("cases")
            if not isinstance(raw_cases, list):
                row_blockers.append(f"evidence source cases must be a list: {test_file or 'missing'}")
                continue
            cases = [case.strip() for case in raw_cases if isinstance(case, str) and case.strip()]
            if len(cases) != len(raw_cases):
                row_blockers.append(f"evidence source has invalid cases: {test_file or 'missing'}")
                continue
            if len(cases) != len(set(cases)):
                row_blockers.append(f"evidence source has duplicate cases: {test_file or 'missing'}")
            lane = lanes.get(test_file)
            if lane is None:
                row_blockers.append(f"unsupported evidence source: {test_file or 'missing'}")
                continue
            if not cases:
                row_blockers.append(f"evidence source lacks cases: {test_file}")
                continue
            unexpected_cases = sorted(set(cases) - allowed_cases[test_file])
            if unexpected_cases:
                row_blockers.append(f"evidence source has ungoverned cases: {', '.join(unexpected_cases)}")
            mapped_cases[test_file].update(cases)
            lane_status = str(lane.get("status") or "blocked").strip().lower()
            lane_statuses.append(lane_status)
            rendered_sources.append(
                {
                    "file": test_file,
                    "cases": cases,
                    "lane_status": lane_status,
                }
            )

        if journey_id == "packets_tours":
            expected_tour_sources = [
                {
                    "file": REAL_BROWSER_TEST_FILE,
                    "cases": list(REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES),
                }
            ]
            actual_tour_sources = [
                {
                    "file": str(entry.get("file") or "").strip(),
                    "cases": [str(case).strip() for case in entry.get("cases") or [] if str(case).strip()],
                }
                for entry in rendered_sources
            ]
            if actual_tour_sources != expected_tour_sources:
                row_blockers.append(
                    "must map the exact ordered hosted, recovery, generated, mobile, and unavailable-tour cases"
                )

        live_requirement = row.get("live_requirement")
        if not isinstance(live_requirement, dict):
            live_requirement = {}
            row_blockers.append("live requirement is missing")
        live_status = str(live_requirement.get("status") or "").strip().lower()
        live_authority = str(live_requirement.get("authority") or "").strip()
        live_profile = str(live_requirement.get("required_profile") or "").strip()
        if live_status != "not_evaluated" or not live_authority or live_profile != "launch":
            row_blockers.append("live requirement must remain not_evaluated with a named launch authority")

        if row_blockers or any(status not in {"pass", "preview_only"} for status in lane_statuses):
            proof_status = "blocked"
        elif any(status == "preview_only" for status in lane_statuses):
            proof_status = "preview_only"
        else:
            proof_status = "pass"
        if row_blockers:
            blockers.extend(f"journey {journey_id}: {reason}" for reason in row_blockers)
        rendered_rows.append(
            {
                "journey_id": journey_id,
                "label": label,
                "proof_status": proof_status,
                "evidence_sources": rendered_sources,
                "live_requirement": {
                    "status": live_status,
                    "authority": live_authority,
                    "required_profile": live_profile,
                },
                "blocking_reasons": row_blockers,
            }
        )

    for test_file, expected_cases in allowed_cases.items():
        missing_cases = sorted(expected_cases - mapped_cases[test_file])
        extra_cases = sorted(mapped_cases[test_file] - expected_cases)
        if missing_cases or extra_cases:
            blockers.append(
                f"journey evidence matrix does not exactly map {test_file}: "
                f"missing={','.join(missing_cases) or 'none'}; extra={','.join(extra_cases) or 'none'}"
            )

    blockers = list(dict.fromkeys(blockers))
    if blockers or any(row["proof_status"] == "blocked" for row in rendered_rows):
        status = "blocked"
    elif any(row["proof_status"] == "preview_only" for row in rendered_rows):
        status = "preview_only"
    else:
        status = "pass"
    return {
        "version": version,
        "status": status,
        "readiness_scope": readiness_scope,
        "runtime_commit_sha": str((source_binding or {}).get("code_commit") or ""),
        "required_journey_ids": list(REQUIRED_JOURNEY_IDS),
        "rows": rendered_rows,
    }, blockers


def _run_pytest_cases(
    root: Path,
    *,
    python_bin: str,
    test_file: str,
    cases: list[str],
    real_browser: bool,
) -> dict[str, Any]:
    cmd = [
        python_bin,
        "-m",
        "pytest",
        "-q",
        *(f"{test_file}::{case}" for case in cases),
    ]
    if real_browser:
        cmd.append("-rs")
    env = os.environ.copy()
    for key in PYTEST_ISOLATED_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONPATH"] = _with_pythonpath(str(env.get("PYTHONPATH") or ""), root)
    started = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    combined_output = "\n".join(
        part for part in (str(result.stdout or "").strip(), str(result.stderr or "").strip()) if part
    )
    limitations = _extract_limitations(combined_output, real_browser=real_browser)
    outcome_counts = _pytest_outcome_counts(combined_output)
    required_case_count = len(cases)
    all_required_cases_passed = (
        result.returncode == 0
        and outcome_counts["passed"] >= required_case_count
        and outcome_counts["failed"] == 0
        and outcome_counts["skipped"] == 0
        and outcome_counts["errors"] == 0
        and outcome_counts["xfailed"] == 0
        and outcome_counts["xpassed"] == 0
    )
    if all_required_cases_passed:
        status = "pass"
    elif real_browser and outcome_counts["skipped"] and not any(
        outcome_counts[key] for key in ("failed", "errors", "xfailed", "xpassed")
    ):
        status = "preview_only"
    else:
        status = "blocked"
    return _lane_completion({
        "status": status,
        "command": shlex.join(cmd),
        "cwd": root.as_posix(),
        "python_bin": python_bin,
        "test_file": test_file,
        "cases": cases,
        "exit_code": result.returncode,
        "duration_seconds": duration_seconds,
        "output_excerpt": _truncate_output(combined_output),
        "limitations": limitations,
        "outcome_counts": outcome_counts,
    }, required_cases=cases, real_browser=real_browser)


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    runner: Callable[..., dict[str, Any]] = _run_pytest_cases,
    require_source_binding: bool = False,
) -> dict[str, Any]:
    seed = _load_json(root / seed_path)
    proof_target = str((seed.get("browser_workflow_proof") or {}).get("proof_target") or "executive-assistant").strip()
    proof_label = "PropertyQuarry" if proof_target == "propertyquarry" else "EA"
    python_bin = _resolve_python_bin(root)
    governed_sources, evidence_source_blockers = _governed_evidence_sources(seed)
    source_specs = [entry for entry in governed_sources if "/e2e/" not in entry["file"]]
    real_browser_specs = [entry for entry in governed_sources if "/e2e/" in entry["file"]]
    source_backed = [
        _lane_completion(
            runner(
                root,
                python_bin=python_bin,
                test_file=str(spec["file"]),
                cases=list(spec["cases"]),
                real_browser=False,
            ),
            required_cases=list(spec["cases"]),
            real_browser=False,
        )
        for spec in source_specs
    ]
    if len(real_browser_specs) == 1:
        real_browser_spec = real_browser_specs[0]
        real_browser = _lane_completion(
            runner(
                root,
                python_bin=python_bin,
                test_file=str(real_browser_spec["file"]),
                cases=list(real_browser_spec["cases"]),
                real_browser=True,
            ),
            required_cases=list(real_browser_spec["cases"]),
            real_browser=True,
        )
    else:
        real_browser = _unavailable_lane(
            test_file="",
            cases=[],
            real_browser=True,
            limitation="the current gate does not define one unambiguous real-browser evidence lane",
        )

    blocking_reasons: list[str] = list(evidence_source_blockers)
    current_limitations: list[str] = []
    source_binding: dict[str, Any] | None = None
    if require_source_binding:
        try:
            source_binding = build_source_binding(
                root,
                seed_path=seed_path,
                evidence_sources=(seed.get("browser_workflow_proof") or {}).get("evidence_sources"),
            )
        except (OSError, ReleaseBindingError) as exc:
            blocking_reasons.append(f"immutable source binding failed: {exc}")
    journey_evidence_matrix, journey_matrix_blockers = _build_journey_evidence_matrix(
        seed,
        source_backed=source_backed,
        real_browser=real_browser,
        source_binding=source_binding,
    )
    blocking_reasons.extend(journey_matrix_blockers)
    for source_lane in source_backed:
        if source_lane["status"] != "pass":
            blocking_reasons.append(
                "source-backed browser journey proof is not passing: "
                + str(source_lane.get("test_file") or "missing")
            )
            current_limitations.extend(source_lane.get("limitations") or [])
    if real_browser["status"] == "blocked":
        blocking_reasons.append("real browser E2E proof is not passing")
        current_limitations.extend(real_browser.get("limitations") or [])
    elif real_browser["status"] == "preview_only":
        current_limitations.extend(real_browser.get("limitations") or [])

    blocking_reasons = list(dict.fromkeys(blocking_reasons))

    if not blocking_reasons and real_browser["status"] == "pass":
        status = "pass"
        operator_summary = (
            f"{proof_label} browser workflow proof is published and green across the required journey matrix, "
            "source-backed contracts, and real-browser E2E."
        )
    elif not blocking_reasons:
        status = "preview_only"
        operator_summary = f"{proof_label} browser workflow proof is published, but it remains preview_only until the real-browser E2E slice runs cleanly."
    else:
        status = "blocked"
        operator_summary = f"{proof_label} browser workflow proof is published, but it is blocked by failing or unavailable proof lanes."

    receipt = {
        "contract_name": "ea.browser_workflow_proof",
        "product": str(seed.get("product") or "propertyquarry"),
        "surface": "browser_workflow_proof",
        "proof_target": proof_target,
        "version": 1,
        "kind": "proof_receipt",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_ea_browser_workflow_proof.py",
        "status": status,
        "operator_summary": operator_summary,
        "seed_source": seed_path.as_posix(),
        "release_claim_summary": str((seed.get("release_claim") or {}).get("summary") or "").strip(),
        "expected_browser_signals": list((seed.get("browser_workflow_proof") or {}).get("expected_browser_signals") or []),
        "approved_baseline": release_proof_baseline.approved_baseline_binding(),
        "source_binding": source_binding,
        "source_backed_journey_proof": source_backed[0] if source_backed else {},
        "source_backed_journey_proofs": source_backed,
        "real_browser_e2e_proof": real_browser,
        "journey_evidence_matrix": journey_evidence_matrix,
        "blocking_reasons": blocking_reasons,
        "current_limitations": sorted(set(current_limitations)),
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA browser workflow proof receipt.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="EA repository root.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="EA flagship release seed.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the generated receipt.")
    parser.add_argument("--stdout", action="store_true", help="Print the receipt JSON to stdout.")
    args = parser.parse_args()

    root = args.root.resolve()
    receipt = build_receipt(root, seed_path=args.seed, require_source_binding=True)
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_stable(output_path, receipt)
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "receipt_status": receipt["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
