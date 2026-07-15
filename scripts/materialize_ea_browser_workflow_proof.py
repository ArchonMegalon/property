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
else:
    from propertyquarry_release_receipt_binding import ReleaseBindingError, build_source_binding


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_OUTPUT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
SOURCE_BACKED_TEST_FILE = "tests/test_propertyquarry_workspace_redesign.py"
SOURCE_BACKED_CASES = [
    "test_propertyquarry_workspace_routes_render_greenfield_surfaces",
    "test_propertyquarry_failed_run_stays_on_activity_surface",
]
REAL_BROWSER_TEST_FILE = "tests/e2e/test_propertyquarry_greenfield_browser.py"
REAL_BROWSER_CASES = [
    "test_propertyquarry_greenfield_workspace_in_real_browser",
    "test_propertyquarry_greenfield_workspace_is_mobile_usable",
]
PYTEST_OUTCOME_KEYS = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_release_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"generated_at", "created_at", "mtime_utc", "size_bytes", "sha256", "duration_seconds", "git_head"}:
                continue
            if key.endswith("_git_head"):
                continue
            if key == "review_due":
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
    source_backed = _lane_completion(runner(
        root,
        python_bin=python_bin,
        test_file=SOURCE_BACKED_TEST_FILE,
        cases=SOURCE_BACKED_CASES,
        real_browser=False,
    ), required_cases=SOURCE_BACKED_CASES, real_browser=False)
    real_browser = _lane_completion(runner(
        root,
        python_bin=python_bin,
        test_file=REAL_BROWSER_TEST_FILE,
        cases=REAL_BROWSER_CASES,
        real_browser=True,
    ), required_cases=REAL_BROWSER_CASES, real_browser=True)

    blocking_reasons: list[str] = []
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
    if source_backed["status"] != "pass":
        blocking_reasons.append("source-backed browser journey proof is not passing")
        current_limitations.extend(source_backed.get("limitations") or [])
    if real_browser["status"] == "blocked":
        blocking_reasons.append("real browser E2E proof is not passing")
        current_limitations.extend(real_browser.get("limitations") or [])
    elif real_browser["status"] == "preview_only":
        current_limitations.extend(real_browser.get("limitations") or [])

    if not blocking_reasons and real_browser["status"] == "pass":
        status = "pass"
        operator_summary = f"{proof_label} browser workflow proof is published and green across both source-backed journeys and real-browser E2E."
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
        "source_binding": source_binding,
        "source_backed_journey_proof": source_backed,
        "real_browser_e2e_proof": real_browser,
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
