#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .propertyquarry_release_receipt_binding import (
        ReleaseBindingError,
        build_source_binding,
        file_digest_binding,
    )
else:
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
)
PYTEST_OUTCOME_KEYS = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed")
PYTEST_OUTCOME_RE = re.compile(
    r"\b(?P<count>\d+)\s+(?P<outcome>passed|failed|skipped|errors?|xfailed|xpassed)\b",
    re.IGNORECASE,
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


def browser_receipt_pass_blockers(receipt: dict[str, Any], seed: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    proof_contract = seed.get("browser_workflow_proof")
    if not isinstance(proof_contract, dict):
        proof_contract = {}
    expected_target = str(proof_contract.get("proof_target") or "").strip()
    expected_product = str(seed.get("product") or "").strip()
    if not expected_target or not expected_product:
        return ["current gate seed lacks a product or browser proof target"]
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

    sources = [entry for entry in proof_contract.get("evidence_sources") or [] if isinstance(entry, dict)]
    source_backed = [entry for entry in sources if "/e2e/" not in str(entry.get("file") or "")]
    real_browser = [entry for entry in sources if "/e2e/" in str(entry.get("file") or "")]
    if len(source_backed) != 1 or len(real_browser) != 1 or len(sources) != 2:
        blockers.append("current gate seed must define exactly one source-backed and one real-browser proof source")
        return blockers

    for key, label, expected in (
        ("source_backed_journey_proof", "source-backed browser journey", source_backed[0]),
        ("real_browser_e2e_proof", "real browser E2E", real_browser[0]),
    ):
        expected_file = str(expected.get("file") or "").strip()
        expected_cases = [str(item) for item in expected.get("cases") or [] if str(item).strip()]
        if not _browser_lane_pass_is_supported(
            receipt.get(key),
            expected_test_file=expected_file,
            expected_cases=expected_cases,
        ):
            blockers.append(f"published pass lacks completed {label} proof")
    return blockers


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


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    truth_plane_path: Path = DEFAULT_TRUTH_PLANE,
    browser_proof_receipt_path: Path | None = DEFAULT_BROWSER_PROOF_RECEIPT,
    require_source_binding: bool = False,
) -> dict[str, Any]:
    seed = _load_json(root / seed_path)
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

    blockers: list[str] = []
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

    if status == "pass":
        operator_summary = (
            f"{proof_label} source/browser flagship proof is published and green; "
            "final live readiness is not evaluated by this receipt."
        )
    elif status == "preview_only":
        operator_summary = (
            f"{proof_label} source/browser flagship proof is materialized, but the current claim is preview_only "
            "until browser execution proof is published; final live readiness is not evaluated by this receipt."
        )
    else:
        operator_summary = (
            f"{proof_label} source/browser flagship proof is materialized, but the current browser-proof or "
            "release-doc state still blocks the claim; final live readiness is not evaluated by this receipt."
        )

    receipt: dict[str, Any] = {
        "product": str(seed.get("product") or "propertyquarry"),
        "surface": str(seed.get("surface") or "flagship_release_control"),
        "version": int(seed.get("version") or 1),
        "kind": "release_receipt",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_ea_flagship_release_gate.py",
        "status": status,
        "readiness_scope": "source_and_browser_proof",
        "live_readiness": {
            "status": "not_evaluated",
            "authority": "_completion/property_gold_status/release-gate.json",
            "required_profile": "launch",
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
        "ea_product_canon": product_canon,
        "browser_workflow_proof": {
            "proof_target": proof_target,
            "evidence_sources": seed.get("browser_workflow_proof", {}).get("evidence_sources", []),
            "source_files_present": browser_sources,
            "published_receipt": browser_receipt_path_value,
            "published_receipt_present": published_browser_receipt is not None,
        },
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
