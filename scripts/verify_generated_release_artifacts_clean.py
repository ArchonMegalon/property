#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ARTIFACTS = (
    Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"),
    Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"),
    Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"),
)
RELEASE_MANIFEST_PATH = Path("docs/PROPERTYQUARRY_RELEASE_MANIFEST.md")
RELEASE_ARTIFACT_SET_PREFIX = "propertyquarry-generated-release-artifacts-v1@sha256:"
RELEASE_MANIFEST_SCHEMA = "propertyquarry.release_manifest.v1"
RELEASE_MANIFEST_JSON_START = "<!-- propertyquarry-release-manifest-json:start -->"
RELEASE_MANIFEST_JSON_END = "<!-- propertyquarry-release-manifest-json:end -->"
RELEASE_MANIFEST_VERIFICATION_COMMANDS = (
    "bash scripts/verify_release_assets.sh && "
    "python3 scripts/verify_flagship_release_readiness.py && "
    "python3 scripts/verify_generated_release_artifacts_clean.py"
)
RELEASE_MANIFEST_FIELDS = (
    "release_manifest_schema",
    "release_product",
    "release_candidate_status",
    "release_repository",
    "release_repository_origin",
    "release_mirror_repository",
    "release_mirror_origin",
    "release_branch",
    "release_commit_sha",
    "release_public_origin",
    "release_artifact_set",
    "release_label",
    "release_generated_at",
    "release_verification_commands",
    "release_deployment_id",
)
RELEASE_MANIFEST_STATIC_VALUES = {
    "release_manifest_schema": RELEASE_MANIFEST_SCHEMA,
    "release_product": "PropertyQuarry",
    "release_candidate_status": "source-browser-candidate-pending-protected-live-evidence",
    "release_repository": "ArchonMegalon/property",
    "release_repository_origin": "https://github.com/ArchonMegalon/property.git",
    "release_mirror_repository": "ArchonMegalon/propertyquarry",
    "release_mirror_origin": "https://github.com/ArchonMegalon/propertyquarry.git",
    "release_branch": "main",
    "release_public_origin": "https://propertyquarry.com",
    "release_verification_commands": RELEASE_MANIFEST_VERIFICATION_COMMANDS,
}
_RFC3339_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_SET = re.compile(
    rf"^{re.escape(RELEASE_ARTIFACT_SET_PREFIX)}[0-9a-f]{{64}}$"
)
VOLATILE_KEYS = {
    "generated_at",
    "as_of",
    "created_at",
    "mtime_utc",
    "size_bytes",
    "sha256",
    "duration_seconds",
    "git_branch",
    "git_head",
    "source_path",
    "resolved_path",
    "git_repo_root",
    "command",
    "cwd",
    "output_excerpt",
    "python_bin",
    "review_due",
    "code_commit",
}


def _normalize(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in VOLATILE_KEYS or str(key).endswith("_git_head"):
                continue
            if key == "git_blob_oid" and path[-1:] == ("browser_receipt_binding",):
                continue
            normalized[key] = _normalize(item, (*path, str(key)))
        return normalized
    if isinstance(value, list):
        return [_normalize(item, path) for item in value]
    return value


def _load_worktree(path: Path) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_head(path: Path) -> Any:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path.as_posix()}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _release_artifact_set_identity(root: Path = ROOT) -> str:
    entries: list[dict[str, object]] = []
    for path in GENERATED_ARTIFACTS:
        payload = (root / path).read_bytes()
        entries.append(
            {
                "path": path.as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    canonical = json.dumps(
        entries,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{RELEASE_ARTIFACT_SET_PREFIX}{hashlib.sha256(canonical).hexdigest()}"


def _release_manifest_expected_values(
    root: Path = ROOT,
) -> tuple[dict[str, str], list[str]]:
    issues: list[str] = []
    receipt_path = root / GENERATED_ARTIFACTS[0]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"release authority receipt is missing or invalid: {exc}"]
    if not isinstance(receipt, dict):
        return {}, ["release authority receipt must be a JSON object"]

    source_binding = receipt.get("source_binding")
    if not isinstance(source_binding, dict):
        source_binding = {}
    runtime_commit_sha = str(source_binding.get("code_commit") or "").strip()
    generated_at = str(receipt.get("generated_at") or "").strip()
    if not _FULL_GIT_SHA.fullmatch(runtime_commit_sha):
        issues.append("release authority receipt runtime commit SHA is missing or invalid")
    if not _RFC3339_UTC_SECONDS.fullmatch(generated_at):
        issues.append("release authority receipt generated_at is missing or not UTC RFC3339 seconds")

    try:
        artifact_set = _release_artifact_set_identity(root)
    except Exception as exc:
        issues.append(f"release artifact set is missing or unreadable: {exc}")
        artifact_set = ""

    expected = dict(RELEASE_MANIFEST_STATIC_VALUES)
    expected.update(
        {
            "release_commit_sha": runtime_commit_sha,
            "release_artifact_set": artifact_set,
            "release_label": (
                f"propertyquarry-source-browser-candidate-{runtime_commit_sha[:12]}"
                if runtime_commit_sha
                else ""
            ),
            "release_deployment_id": (
                f"propertyquarry-governed-deploy-{runtime_commit_sha[:12]}"
                if runtime_commit_sha
                else ""
            ),
            "release_generated_at": generated_at,
        }
    )
    return expected, issues


def _parse_release_manifest(text: str) -> tuple[dict[str, str], list[str]]:
    if (
        text.count(RELEASE_MANIFEST_JSON_START) != 1
        or text.count(RELEASE_MANIFEST_JSON_END) != 1
    ):
        return {}, ["release manifest must contain exactly one marked canonical JSON authority"]
    if text.index(RELEASE_MANIFEST_JSON_START) > text.index(RELEASE_MANIFEST_JSON_END):
        return {}, ["release manifest canonical JSON markers are out of order"]
    before_end, after_end = text.split(RELEASE_MANIFEST_JSON_END, 1)
    before_start, marked = before_end.split(RELEASE_MANIFEST_JSON_START, 1)
    if RELEASE_MANIFEST_JSON_END in before_start or RELEASE_MANIFEST_JSON_START in after_end:
        return {}, ["release manifest canonical JSON markers are out of order"]
    fenced = re.fullmatch(r"\s*```json\s*\n(?P<body>.*)\n```\s*", marked, flags=re.DOTALL)
    if fenced is None:
        return {}, ["release manifest canonical authority must be one exact JSON code fence"]

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"release manifest authority field is duplicated: {key}")
            payload[key] = value
        return payload

    try:
        raw = json.loads(fenced.group("body"), object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        return {}, [f"release manifest canonical JSON is invalid: {exc.msg}"]
    except ValueError as exc:
        return {}, [str(exc)]
    if not isinstance(raw, dict):
        return {}, ["release manifest canonical JSON root must be an object"]
    values: dict[str, str] = {}
    issues: list[str] = []
    for key, value in raw.items():
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        values[key] = normalized
        if normalized != value:
            issues.append(
                f"release manifest authority field contains surrounding whitespace: {key}"
            )
    non_string = sorted(str(key) for key, value in raw.items() if not isinstance(value, str))
    issues.extend(
        f"release manifest authority field must be a string: {key}"
        for key in non_string
    )
    return values, issues


def _release_manifest_shape_issues(values: dict[str, str]) -> list[str]:
    issues: list[str] = []
    expected_fields = set(RELEASE_MANIFEST_FIELDS)
    for field in RELEASE_MANIFEST_FIELDS:
        if field not in values:
            issues.append(f"release manifest authority field is missing: {field}")
        elif not values[field]:
            issues.append(f"release manifest authority field is empty: {field}")
        elif values[field] != values[field].strip():
            issues.append(
                f"release manifest authority field contains surrounding whitespace: {field}"
            )
        elif any(ord(char) < 32 for char in values[field]):
            issues.append(f"release manifest authority field contains control text: {field}")
    for field in sorted(set(values) - expected_fields):
        issues.append(f"release manifest authority field is unexpected: {field}")
    if values.get("release_manifest_schema") not in {None, "", RELEASE_MANIFEST_SCHEMA}:
        issues.append("release manifest schema is invalid")
    commit_sha = values.get("release_commit_sha", "")
    if commit_sha and _FULL_GIT_SHA.fullmatch(commit_sha) is None:
        issues.append("release manifest runtime commit SHA is invalid")
    generated_at = values.get("release_generated_at", "")
    if generated_at and _RFC3339_UTC_SECONDS.fullmatch(generated_at) is None:
        issues.append("release manifest generated_at is not UTC RFC3339 seconds")
    artifact_set = values.get("release_artifact_set", "")
    if artifact_set and _ARTIFACT_SET.fullmatch(artifact_set) is None:
        issues.append("release manifest artifact set identity is invalid")
    return issues


def release_manifest_sha256(values: dict[str, str]) -> str:
    issues = _release_manifest_shape_issues(values)
    if issues:
        raise ValueError("; ".join(issues))
    canonical = json.dumps(
        values,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_release_manifest(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"release manifest is missing or unreadable: {type(exc).__name__}") from exc
    values, issues = _parse_release_manifest(text)
    issues.extend(_release_manifest_shape_issues(values))
    if issues:
        raise ValueError("; ".join(dict.fromkeys(issues)))
    return values


def _validate_release_manifest_values(
    observed: dict[str, str],
    expected: dict[str, str],
) -> list[str]:
    issues: list[str] = []
    for label, expected_value in expected.items():
        observed_value = observed.get(label)
        if observed_value is None:
            issues.append(f"release manifest authority field is missing: {label}")
        elif not observed_value:
            issues.append(f"release manifest authority field is empty: {label}")
        elif observed_value != expected_value:
            issues.append(f"release manifest authority field mismatches current evidence: {label}")
    for label in sorted(set(observed) - set(expected)):
        issues.append(f"release manifest authority field is unexpected: {label}")
    return issues


def verify_release_manifest(root: Path = ROOT) -> list[str]:
    expected, issues = _release_manifest_expected_values(root)
    manifest_path = root / RELEASE_MANIFEST_PATH
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except Exception as exc:
        return [*issues, f"release manifest is missing or unreadable: {exc}"]
    observed, parse_issues = _parse_release_manifest(text)
    issues.extend(parse_issues)
    issues.extend(_release_manifest_shape_issues(observed))
    issues.extend(_validate_release_manifest_values(observed, expected))
    return list(dict.fromkeys(issues))


def main() -> int:
    failures: list[str] = []
    semantically_clean: list[Path] = []
    for path in GENERATED_ARTIFACTS:
        try:
            head_payload = _load_head(path)
            worktree_payload = _load_worktree(path)
        except Exception as exc:
            failures.append(f"{path}: unable to load generated artifact: {exc}")
            continue
        if _normalize(head_payload) != _normalize(worktree_payload):
            failures.append(f"{path}: semantic drift after materialization")
        else:
            semantically_clean.append(path)

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    subprocess.run(
        ["git", "-C", str(ROOT), "restore", "--", *(path.as_posix() for path in semantically_clean)],
        check=True,
    )
    manifest_failures = verify_release_manifest(ROOT)
    if manifest_failures:
        for failure in manifest_failures:
            print(failure, file=sys.stderr)
        return 1
    print("generated release artifacts are semantically clean")
    print("immutable release manifest authority is exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
