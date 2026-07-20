#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from . import propertyquarry_release_proof_baseline as release_proof_baseline
    from .propertyquarry_release_receipt_binding import (
        ReleaseBindingError,
        build_source_binding,
        file_digest_binding,
    )
else:
    import propertyquarry_release_proof_baseline as release_proof_baseline
    from propertyquarry_release_receipt_binding import (
        ReleaseBindingError,
        build_source_binding,
        file_digest_binding,
    )


DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_TRUTH_PLANE = Path(".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md")
DEFAULT_OUTPUT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
DEFAULT_BROWSER_PROOF_RECEIPT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
REQUIRED_DOCS = (
    Path("README.md"),
    Path("RUNBOOK.md"),
    Path("RELEASE_CHECKLIST.md"),
    Path("PRODUCT_RELEASE_CHECKLIST.md"),
    Path("docs/PROPERTYQUARRY_GLOBAL_FLAGSHIP_GOAL.md"),
)
PYTEST_OUTCOME_KEYS = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
PYTEST_OUTCOME_RE = re.compile(
    r"\b(?P<count>\d+)\s+(?P<outcome>passed|failed|skipped|errors?|xfailed|xpassed)\b",
    re.IGNORECASE,
)
REQUIRED_JOURNEY_IDS = release_proof_baseline.APPROVED_REQUIRED_JOURNEY_IDS
REAL_BROWSER_TEST_FILE = release_proof_baseline.REAL_BROWSER_TEST_FILE
REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES = release_proof_baseline.PACKETS_TOURS_REAL_BROWSER_CASES


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_release_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"generated_at", "created_at", "mtime_utc", "duration_seconds", "git_head"}:
                continue
            if key.endswith("_git_head"):
                continue
            if key == "review_due":
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


def _present(root: Path, rel: Path) -> bool:
    return (root / rel).exists()


def _stringify_path(path: Path) -> str:
    return path.as_posix()


def _pytest_outcome_counts(output_excerpt: object) -> dict[str, int]:
    counts = {key: 0 for key in PYTEST_OUTCOME_KEYS}
    text = "\n".join(str(line) for line in output_excerpt or []) if isinstance(output_excerpt, list) else ""
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


def _browser_lane_pass_is_supported(
    lane: object,
    *,
    expected_test_file: str,
    expected_cases: list[str],
) -> bool:
    if not isinstance(lane, dict) or str(lane.get("status") or "").strip().lower() != "pass":
        return False
    cases = [str(item) for item in lane.get("cases") or [] if str(item).strip()]
    try:
        required_case_count = int(lane.get("required_case_count") or len(cases))
        raw_counts = lane.get("outcome_counts")
        if isinstance(raw_counts, dict):
            counts = {key: int(raw_counts.get(key) or 0) for key in PYTEST_OUTCOME_KEYS}
        else:
            counts = _pytest_outcome_counts(lane.get("output_excerpt"))
        executed_count = int(lane.get("executed_count") or 0)
        exit_code = int(lane.get("exit_code") if lane.get("exit_code") is not None else 1)
    except (TypeError, ValueError):
        return False
    if executed_count == 0:
        executed_count = sum(counts[key] for key in ("passed", "failed", "errors", "xfailed", "xpassed"))
    return (
        bool(expected_cases)
        and str(lane.get("test_file") or "").strip() == expected_test_file
        and cases == expected_cases
        and required_case_count == len(expected_cases)
        and exit_code == 0
        and counts["passed"] >= required_case_count
        and executed_count >= required_case_count
        and counts["failed"] == 0
        and counts["skipped"] == 0
        and counts["errors"] == 0
        and counts["xfailed"] == 0
        and counts["xpassed"] == 0
        and not list(lane.get("limitations") or [])
    )


def _journey_matrix_pass_blockers(receipt: dict[str, Any], seed: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    expected = seed.get("journey_evidence_matrix")
    actual = receipt.get("journey_evidence_matrix")
    if not isinstance(expected, dict):
        return ["current gate seed lacks the journey evidence matrix"]
    if not isinstance(actual, dict):
        return ["published pass lacks the journey evidence matrix"]
    expected_id_items = expected.get("required_journey_ids")
    actual_id_items = actual.get("required_journey_ids")
    if not isinstance(expected_id_items, list) or not isinstance(actual_id_items, list):
        blockers.append("published pass journey IDs must be governed lists")
        expected_id_items = expected_id_items if isinstance(expected_id_items, list) else []
        actual_id_items = actual_id_items if isinstance(actual_id_items, list) else []
    expected_ids = [str(item).strip() for item in expected_id_items if str(item).strip()]
    actual_ids = [str(item).strip() for item in actual_id_items if str(item).strip()]
    if expected_ids != list(REQUIRED_JOURNEY_IDS) or actual_ids != expected_ids:
        blockers.append("published pass journey IDs do not match the complete current matrix")
    if str(actual.get("status") or "").strip().lower() != "pass":
        blockers.append("published pass journey matrix is not passing")
    if str(actual.get("readiness_scope") or "").strip() != str(expected.get("readiness_scope") or "").strip():
        blockers.append("published pass journey matrix has the wrong readiness scope")
    source_binding = receipt.get("source_binding") if isinstance(receipt.get("source_binding"), dict) else {}
    if str(actual.get("runtime_commit_sha") or "").strip().lower() != str(source_binding.get("code_commit") or "").strip().lower():
        blockers.append("published pass journey matrix is not bound to the browser receipt runtime commit")

    expected_row_items = expected.get("rows")
    actual_row_items = actual.get("rows")
    if not isinstance(expected_row_items, list) or not isinstance(actual_row_items, list):
        blockers.append("published pass journey rows must be governed lists")
        expected_row_items = expected_row_items if isinstance(expected_row_items, list) else []
        actual_row_items = actual_row_items if isinstance(actual_row_items, list) else []
    expected_row_list = [row for row in expected_row_items if isinstance(row, dict)]
    actual_row_list = [row for row in actual_row_items if isinstance(row, dict)]
    expected_rows = {
        str(row.get("journey_id") or "").strip(): row
        for row in expected_row_list
        if str(row.get("journey_id") or "").strip()
    }
    actual_rows = {
        str(row.get("journey_id") or "").strip(): row
        for row in actual_row_list
        if str(row.get("journey_id") or "").strip()
    }
    if (
        len(expected_row_list) != len(REQUIRED_JOURNEY_IDS)
        or len(expected_row_list) != len(expected_row_items)
        or len(expected_rows) != len(expected_row_list)
        or len(actual_row_list) != len(actual_row_items)
        or len(actual_row_list) != len(expected_row_list)
        or len(actual_rows) != len(actual_row_list)
        or set(expected_rows) != set(REQUIRED_JOURNEY_IDS)
        or set(actual_rows) != set(expected_rows)
    ):
        blockers.append("published pass journey rows do not exactly cover the current matrix")
        return blockers
    for journey_id in REQUIRED_JOURNEY_IDS:
        expected_row = expected_rows[journey_id]
        actual_row = actual_rows[journey_id]
        if str(actual_row.get("label") or "").strip() != str(expected_row.get("label") or "").strip():
            blockers.append(f"published pass journey {journey_id} has stale label metadata")
        expected_source_items = expected_row.get("evidence_sources")
        actual_source_items = actual_row.get("evidence_sources")
        if not isinstance(expected_source_items, list) or not isinstance(actual_source_items, list):
            blockers.append(f"published pass journey {journey_id} evidence nodes must be governed lists")
            expected_source_items = expected_source_items if isinstance(expected_source_items, list) else []
            actual_source_items = actual_source_items if isinstance(actual_source_items, list) else []
        expected_sources = [
            {
                "file": str(entry.get("file") or "").strip(),
                "cases": [str(case).strip() for case in entry.get("cases") or [] if str(case).strip()],
            }
            for entry in expected_source_items
            if isinstance(entry, dict)
        ]
        actual_sources = [
            {
                "file": str(entry.get("file") or "").strip(),
                "cases": [str(case).strip() for case in entry.get("cases") or [] if str(case).strip()],
            }
            for entry in actual_source_items
            if isinstance(entry, dict)
        ]
        if journey_id == "packets_tours":
            required_tour_sources = [
                {
                    "file": REAL_BROWSER_TEST_FILE,
                    "cases": list(REQUIRED_PACKETS_TOURS_REAL_BROWSER_CASES),
                }
            ]
            if expected_sources != required_tour_sources:
                blockers.append(
                    "current packets_tours journey does not map the exact ordered required tour cases"
                )
            if actual_sources != required_tour_sources:
                blockers.append(
                    "published pass packets_tours journey does not prove the exact ordered required tour cases"
                )
        if (
            len(expected_sources) != len(expected_source_items)
            or len(actual_sources) != len(actual_source_items)
            or actual_sources != expected_sources
        ):
            blockers.append(f"published pass journey {journey_id} has stale evidence nodes")
        if any(
            str(entry.get("lane_status") or "").strip().lower() != "pass"
            for entry in actual_row.get("evidence_sources") or []
            if isinstance(entry, dict)
        ):
            blockers.append(f"published pass journey {journey_id} has an incomplete evidence lane")
        if str(actual_row.get("proof_status") or "").strip().lower() != "pass":
            blockers.append(f"published pass journey {journey_id} did not complete")
        if list(actual_row.get("blocking_reasons") or []):
            blockers.append(f"published pass journey {journey_id} still reports blockers")
        expected_live = expected_row.get("live_requirement")
        if not isinstance(expected_live, dict):
            expected_live = {}
        if (
            str(expected_live.get("status") or "").strip().lower() != "not_evaluated"
            or not str(expected_live.get("authority") or "").strip()
            or str(expected_live.get("required_profile") or "").strip() != "launch"
        ):
            blockers.append(f"current journey {journey_id} lacks a fail-closed live authority")
        if actual_row.get("live_requirement") != expected_live:
            blockers.append(f"published pass journey {journey_id} has stale live requirements")
    return blockers


def browser_receipt_pass_blockers(receipt: dict[str, Any], seed: dict[str, Any]) -> list[str]:
    blockers: list[str] = list(release_proof_baseline.approved_seed_baseline_blockers(seed))
    proof_contract = seed.get("browser_workflow_proof")
    if not isinstance(proof_contract, dict):
        proof_contract = {}
    expected_target = str(proof_contract.get("proof_target") or "").strip()
    expected_product = str(seed.get("product") or "").strip()
    if not expected_target or not expected_product:
        return list(dict.fromkeys([*blockers, "current gate seed lacks a product or browser proof target"]))
    if str(receipt.get("contract_name") or "").strip() != "ea.browser_workflow_proof":
        blockers.append("published pass has the wrong browser proof contract")
    if str(receipt.get("kind") or "").strip() != "proof_receipt":
        blockers.append("published pass has the wrong browser proof receipt kind")
    if str(receipt.get("surface") or "").strip() != "browser_workflow_proof":
        blockers.append("published pass has the wrong browser proof surface")
    try:
        receipt_version = int(receipt.get("version") or 0)
    except (TypeError, ValueError):
        receipt_version = 0
    if receipt_version != 1:
        blockers.append("published pass has the wrong browser proof version")
    if str(receipt.get("generated_by") or "").strip() != "scripts/materialize_ea_browser_workflow_proof.py":
        blockers.append("published pass was not produced by the governed browser proof materializer")
    if receipt.get("approved_baseline") != release_proof_baseline.approved_baseline_binding():
        blockers.append("published pass is not bound to the immutable approved release-proof baseline")
    if str(receipt.get("product") or "").strip() != expected_product:
        blockers.append(f"published pass targets product {receipt.get('product') or 'missing'}, expected {expected_product}")
    if str(receipt.get("proof_target") or "").strip() != expected_target:
        blockers.append(
            f"published pass targets {receipt.get('proof_target') or 'missing'}, expected {expected_target}"
        )
    release_claim = seed.get("release_claim")
    if not isinstance(release_claim, dict):
        release_claim = {}
    expected_claim = str(release_claim.get("summary") or "").strip()
    if str(receipt.get("release_claim_summary") or "").strip() != expected_claim:
        blockers.append("published pass release claim does not match the current gate seed")
    expected_signals = [str(item) for item in proof_contract.get("expected_browser_signals") or [] if str(item).strip()]
    raw_actual_signals = receipt.get("expected_browser_signals")
    actual_signals = [
        str(item) for item in raw_actual_signals if str(item).strip()
    ] if isinstance(raw_actual_signals, list) else []
    if not isinstance(raw_actual_signals, list):
        blockers.append("published pass lacks a governed browser signals list")
    if actual_signals != expected_signals:
        blockers.append("published pass browser signals do not match the current gate seed")
    raw_receipt_blockers = receipt.get("blocking_reasons")
    receipt_blockers = [
        str(item) for item in raw_receipt_blockers if str(item).strip()
    ] if isinstance(raw_receipt_blockers, list) else []
    if not isinstance(raw_receipt_blockers, list):
        blockers.append("published pass lacks a governed blocking_reasons list")
    if receipt_blockers:
        blockers.append("published pass still reports browser blockers: " + "; ".join(receipt_blockers))
    raw_receipt_limitations = receipt.get("current_limitations")
    receipt_limitations = [
        str(item) for item in raw_receipt_limitations if str(item).strip()
    ] if isinstance(raw_receipt_limitations, list) else []
    if not isinstance(raw_receipt_limitations, list):
        blockers.append("published pass lacks a governed current_limitations list")
    if receipt_limitations:
        blockers.append("published pass still reports browser limitations: " + "; ".join(receipt_limitations))
    blockers.extend(_journey_matrix_pass_blockers(receipt, seed))

    raw_sources = proof_contract.get("evidence_sources")
    if not isinstance(raw_sources, list) or any(not isinstance(entry, dict) for entry in raw_sources):
        blockers.append("current gate seed browser evidence sources must be a complete governed list")
        return blockers
    sources: list[dict[str, Any]] = []
    for entry in raw_sources:
        test_file = str(entry.get("file") or "").strip()
        raw_cases = entry.get("cases")
        cases = (
            [case.strip() for case in raw_cases if isinstance(case, str) and case.strip()]
            if isinstance(raw_cases, list)
            else []
        )
        if (
            not test_file
            or not isinstance(raw_cases, list)
            or len(cases) != len(raw_cases)
            or not cases
            or len(cases) != len(set(cases))
        ):
            blockers.append("current gate seed contains an incomplete or duplicate browser evidence node")
            return blockers
        sources.append({"file": test_file, "cases": cases})
    source_files = [str(entry["file"]) for entry in sources]
    if len(source_files) != len(set(source_files)):
        blockers.append("current gate seed contains duplicate browser evidence sources")
        return blockers
    source_backed = [entry for entry in sources if "/e2e/" not in str(entry.get("file") or "")]
    real_browser = [entry for entry in sources if "/e2e/" in str(entry.get("file") or "")]
    if not source_backed or len(real_browser) != 1:
        blockers.append("current gate seed must define at least one source-backed and exactly one real-browser proof source")
        return blockers

    raw_source_lanes = receipt.get("source_backed_journey_proofs")
    if not isinstance(raw_source_lanes, list):
        blockers.append("published pass lacks the complete source-backed browser journey proof list")
        source_lanes: list[object] = []
    else:
        source_lanes = list(raw_source_lanes)
    if len(source_lanes) != len(source_backed):
        blockers.append("published pass source-backed proof lanes do not exactly match the current gate seed")
    for index, expected in enumerate(source_backed):
        lane = source_lanes[index] if index < len(source_lanes) else None
        expected_file = str(expected.get("file") or "").strip()
        expected_cases = [str(item) for item in expected.get("cases") or [] if str(item).strip()]
        if not _browser_lane_pass_is_supported(
            lane,
            expected_test_file=expected_file,
            expected_cases=expected_cases,
        ):
            blockers.append(f"published pass lacks completed source-backed browser journey proof: {expected_file}")
    if source_lanes and receipt.get("source_backed_journey_proof") != source_lanes[0]:
        blockers.append("published pass legacy source-backed proof does not match the primary governed lane")

    expected_browser = real_browser[0]
    expected_browser_file = str(expected_browser.get("file") or "").strip()
    expected_browser_cases = [
        str(item) for item in expected_browser.get("cases") or [] if str(item).strip()
    ]
    if not _browser_lane_pass_is_supported(
        receipt.get("real_browser_e2e_proof"),
        expected_test_file=expected_browser_file,
        expected_cases=expected_browser_cases,
    ):
        blockers.append("published pass lacks completed real browser E2E proof")
    return list(dict.fromkeys(blockers))


def _build_browser_sources(root: Path, seed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    evidence_sources = list((seed.get("browser_workflow_proof") or {}).get("evidence_sources") or [])
    rendered: list[dict[str, Any]] = []
    missing: list[str] = []
    for entry in evidence_sources:
        rel = Path(str(entry.get("file") or "").strip())
        cases = [str(case) for case in list(entry.get("cases") or []) if str(case).strip()]
        present = _present(root, rel)
        rendered.append(
            {
                "file": rel.as_posix(),
                "present": present,
                "cases": cases,
            }
        )
        if not present:
            missing.append(rel.as_posix())
    return rendered, missing


def _build_doc_checks(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rendered: list[dict[str, Any]] = []
    missing: list[str] = []
    for rel in REQUIRED_DOCS:
        present = _present(root, rel)
        rendered.append({"path": rel.as_posix(), "present": present})
        if not present:
            missing.append(rel.as_posix())
    return rendered, missing


def _build_product_canon(root: Path, seed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    canon = dict(seed.get("ea_product_canon") or {})
    source_root = str(canon.get("source_root") or "").strip()
    scope_label = str(canon.get("scope_label") or "EA product canon").strip() or "EA product canon"
    required_docs = [str(item) for item in list(canon.get("required_docs") or []) if str(item).strip()]
    docs_present: list[dict[str, Any]] = []
    missing_docs: list[str] = []
    for doc in required_docs:
        rel = Path(doc)
        present = _present(root, rel)
        docs_present.append({"path": rel.as_posix(), "present": present})
        if not present:
            missing_docs.append(rel.as_posix())
    return {
        "source_root": source_root,
        "scope_label": scope_label,
        "required_docs": required_docs,
        "docs_present": docs_present,
        "all_required_docs_present": not missing_docs,
    }, missing_docs


def _project_journey_evidence_matrix(
    seed: dict[str, Any],
    *,
    published_browser_receipt: dict[str, Any] | None,
    published_browser_receipt_status: str | None,
    source_binding: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(published_browser_receipt, dict) and published_browser_receipt_status == "pass":
        published_matrix = published_browser_receipt.get("journey_evidence_matrix")
        if isinstance(published_matrix, dict):
            return published_matrix

    raw_matrix = seed.get("journey_evidence_matrix")
    if not isinstance(raw_matrix, dict):
        raw_matrix = {}
    rendered_rows: list[dict[str, Any]] = []
    for row in raw_matrix.get("rows") or []:
        if not isinstance(row, dict):
            continue
        rendered_sources: list[dict[str, Any]] = []
        for entry in row.get("evidence_sources") or []:
            if not isinstance(entry, dict):
                continue
            rendered_sources.append(
                {
                    "file": str(entry.get("file") or "").strip(),
                    "cases": [str(case).strip() for case in entry.get("cases") or [] if str(case).strip()],
                    "lane_status": "not_evaluated",
                }
            )
        rendered_rows.append(
            {
                "journey_id": str(row.get("journey_id") or "").strip(),
                "label": str(row.get("label") or "").strip(),
                "proof_status": "not_evaluated",
                "evidence_sources": rendered_sources,
                "live_requirement": row.get("live_requirement") if isinstance(row.get("live_requirement"), dict) else {},
                "blocking_reasons": [],
            }
        )
    return {
        "version": int(raw_matrix.get("version") or 0),
        "status": "not_evaluated",
        "readiness_scope": str(raw_matrix.get("readiness_scope") or "").strip(),
        "runtime_commit_sha": str((source_binding or {}).get("code_commit") or ""),
        "required_journey_ids": [
            str(item).strip() for item in raw_matrix.get("required_journey_ids") or [] if str(item).strip()
        ],
        "rows": rendered_rows,
    }


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    truth_plane_path: Path = DEFAULT_TRUTH_PLANE,
    browser_proof_receipt_path: Path | None = DEFAULT_BROWSER_PROOF_RECEIPT,
    require_source_binding: bool = False,
) -> dict[str, Any]:
    seed = _load_json(root / seed_path)
    approved_baseline_blockers = release_proof_baseline.approved_seed_baseline_blockers(seed)
    proof_target = str((seed.get("browser_workflow_proof") or {}).get("proof_target") or "executive-assistant").strip()
    proof_label = "PropertyQuarry" if proof_target == "propertyquarry" else "EA"
    truth_plane_present = _present(root, truth_plane_path)
    docs, missing_docs = _build_doc_checks(root)
    browser_sources, missing_browser_sources = _build_browser_sources(root, seed)
    product_canon, missing_canon_docs = _build_product_canon(root, seed)

    published_browser_receipt = None
    browser_receipt_status = None
    browser_receipt_path_value = None
    browser_receipt_blockers: list[str] = []
    browser_receipt_limitations: list[str] = []
    source_binding: dict[str, Any] | None = None
    source_binding_blocker = ""
    if require_source_binding:
        try:
            source_binding = build_source_binding(
                root,
                seed_path=seed_path,
                evidence_sources=(seed.get("browser_workflow_proof") or {}).get("evidence_sources"),
            )
        except (OSError, ReleaseBindingError) as exc:
            source_binding_blocker = f"immutable source binding failed: {exc}"
    browser_receipt_binding: dict[str, str] | None = None
    if browser_proof_receipt_path is not None:
        candidate = root / browser_proof_receipt_path
        browser_receipt_path_value = browser_proof_receipt_path.as_posix()
        if candidate.exists():
            published_browser_receipt = _load_json(candidate)
            if require_source_binding:
                try:
                    browser_receipt_binding = file_digest_binding(root, browser_proof_receipt_path)
                except (OSError, ReleaseBindingError) as exc:
                    source_binding_blocker = source_binding_blocker or f"browser receipt binding failed: {exc}"
            browser_receipt_status = str(
                published_browser_receipt.get("status")
                or published_browser_receipt.get("state")
                or published_browser_receipt.get("release_truth")
                or ""
            ).strip()
            browser_receipt_blockers = [
                str(item) for item in list(published_browser_receipt.get("blocking_reasons") or []) if str(item).strip()
            ]
            browser_receipt_limitations = [
                str(item) for item in list(published_browser_receipt.get("current_limitations") or []) if str(item).strip()
            ]
            inconsistent_pass_blockers = browser_receipt_pass_blockers(published_browser_receipt, seed)
            if require_source_binding and published_browser_receipt.get("source_binding") != source_binding:
                inconsistent_pass_blockers.append(
                    "published pass immutable source binding does not match the current code commit"
                )
            if inconsistent_pass_blockers:
                browser_receipt_status = "blocked"
                browser_receipt_blockers.extend(inconsistent_pass_blockers)
        elif truth_plane_present:
            browser_receipt_status = None

    blockers: list[str] = [
        f"immutable approved release-proof baseline: {reason}"
        for reason in approved_baseline_blockers
    ]
    current_limitations: list[str] = []
    if not truth_plane_present:
        blockers.append(f"missing truth plane: {truth_plane_path.as_posix()}")
    if source_binding_blocker:
        blockers.append(source_binding_blocker)
    if missing_canon_docs:
        blockers.append("missing EA product canon docs: " + ", ".join(missing_canon_docs))
    if missing_docs:
        blockers.append("missing release docs: " + ", ".join(missing_docs))
    if missing_browser_sources:
        blockers.append("missing browser proof sources: " + ", ".join(missing_browser_sources))
    if published_browser_receipt is None:
        current_limitations.append("no published browser execution receipt is attached yet")
    else:
        current_limitations.extend(browser_receipt_limitations)
        if browser_receipt_status in {"blocked", "fail"}:
            if browser_receipt_blockers:
                blockers.extend("browser workflow proof: " + reason for reason in browser_receipt_blockers)
            else:
                blockers.append("browser workflow proof reported blocked status")
        elif browser_receipt_status == "preview_only" and not browser_receipt_limitations:
            current_limitations.append("browser workflow proof remains preview_only")

    status = "blocked" if blockers else "preview_only"
    if published_browser_receipt is not None and not blockers:
        if browser_receipt_status == "pass":
            status = "pass"
        elif browser_receipt_status in {"blocked", "fail"}:
            status = "blocked"

    release_summary = str((seed.get("release_claim") or {}).get("summary") or "").strip()
    blockers = list(dict.fromkeys(blockers))
    current_limitations = list(dict.fromkeys(current_limitations))
    journey_evidence_matrix = _project_journey_evidence_matrix(
        seed,
        published_browser_receipt=published_browser_receipt,
        published_browser_receipt_status=browser_receipt_status,
        source_binding=source_binding,
    )

    if status == "pass":
        operator_summary = (
            f"{proof_label} source/browser checkpoint is published and green; this does not establish global "
            "launch authority, and final live readiness is not evaluated by this receipt."
        )
    elif status == "preview_only":
        operator_summary = (
            f"{proof_label} source/browser flagship proof is materialized, but the current claim is preview_only "
            "until browser execution proof is published; this does not establish global launch authority, and "
            "final live readiness is not evaluated by this receipt."
        )
    else:
        operator_summary = (
            f"{proof_label} source/browser flagship proof is materialized, but the current browser-proof or "
            "release-doc state still blocks the claim; this does not establish global launch authority, and "
            "final live readiness is not evaluated by this receipt."
        )

    receipt: dict[str, Any] = {
        "product": str(seed.get("product") or "propertyquarry"),
        "surface": str(seed.get("surface") or "flagship_release_control"),
        "version": int(seed.get("version") or 1),
        "kind": "release_receipt",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_ea_flagship_release_gate.py",
        "approved_baseline": release_proof_baseline.approved_baseline_binding(),
        "status": status,
        "readiness_scope": "source_and_browser_proof",
        "live_readiness": {
            "status": "not_evaluated",
            "authority": "_completion/property_gold_status/release-gate.json",
            "required_profile": "launch",
        },
        "global_launch_readiness": {
            "status": "not_evaluated",
            "market_envelope_authority": release_proof_baseline.GLOBAL_LAUNCH_MARKET_ENVELOPE_AUTHORITY,
            "terminal_command": release_proof_baseline.GLOBAL_LAUNCH_TERMINAL_COMMAND,
            "source_browser_checkpoint_is_sufficient": False,
        },
        "source_binding": source_binding,
        "browser_receipt_binding": browser_receipt_binding,
        "operator_summary": operator_summary,
        "truth_plane": {
            "source": truth_plane_path.as_posix(),
            "present": truth_plane_present,
            "legacy_history": (seed.get("truth_plane") or {}).get("legacy_history"),
        },
        "release_claim": seed.get("release_claim") or {},
        "global_launch_contract": seed.get("global_launch_contract") or {},
        "ea_product_canon": product_canon,
        "browser_workflow_proof": {
            "proof_target": proof_target,
            "evidence_sources": seed.get("browser_workflow_proof", {}).get("evidence_sources", []),
            "source_files_present": browser_sources,
            "published_receipt": browser_receipt_path_value,
            "published_receipt_present": published_browser_receipt is not None,
        },
        "journey_evidence_matrix": journey_evidence_matrix,
        "verification_binding": {
            "primary_verifier": (seed.get("verification_binding") or {}).get("primary_verifier", "scripts/verify_release_assets.sh"),
            "supporting_test": (seed.get("verification_binding") or {}).get("supporting_test", "tests/test_flagship_truth_plane.py"),
            "materializer": "scripts/materialize_ea_flagship_release_gate.py",
        },
        "documentation_refs": [
            {"path": rel.as_posix(), "present": present}
            for rel, present in (
                (Path("README.md"), _present(root, Path("README.md"))),
                (Path("RUNBOOK.md"), _present(root, Path("RUNBOOK.md"))),
                (Path("RELEASE_CHECKLIST.md"), _present(root, Path("RELEASE_CHECKLIST.md"))),
                (Path("PRODUCT_RELEASE_CHECKLIST.md"), _present(root, Path("PRODUCT_RELEASE_CHECKLIST.md"))),
            )
        ],
        "release_docs": docs,
        "blocking_reasons": blockers,
        "current_limitations": current_limitations,
        "release_truth": {
            "oracle": truth_plane_path.as_posix(),
            "seed": seed_path.as_posix(),
            "summary": release_summary,
        },
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA flagship release receipt.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="EA repository root.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="Path to the EA flagship release seed.")
    parser.add_argument("--truth-plane", type=Path, default=DEFAULT_TRUTH_PLANE, help="Path to the EA flagship truth plane.")
    parser.add_argument(
        "--browser-proof-receipt",
        type=Path,
        default=DEFAULT_BROWSER_PROOF_RECEIPT,
        help="Optional browser execution receipt to fold into the current status.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the generated receipt.")
    parser.add_argument("--stdout", action="store_true", help="Print the receipt to stdout instead of writing only to disk.")
    args = parser.parse_args()

    receipt = build_receipt(
        args.root.resolve(),
        seed_path=args.seed,
        truth_plane_path=args.truth_plane,
        browser_proof_receipt_path=args.browser_proof_receipt,
        require_source_binding=True,
    )

    output_path = args.root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_stable(output_path, receipt)
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "receipt_status": receipt["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
