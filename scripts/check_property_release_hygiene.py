#!/usr/bin/env python3
from __future__ import annotations

import re
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from scripts.verify_generated_release_artifacts_clean import load_release_manifest
else:
    from verify_generated_release_artifacts_clean import load_release_manifest


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TRACKED_PREFIXES = (
    "tmp_audit/",
)

FORBIDDEN_TRACKED_EXACT_PATHS = {
    ".env",
    ".env.local",
}

FORBIDDEN_AUDIT_SUFFIXES = (
    "_audit.py",
    "_desktop.png",
    "_mobile.png",
)

IGNORED_UNTRACKED_PREFIXES = (
    "_completion/",
    "_tmp_live_shots/",
    ".pytest_cache/",
    "state/",
    "tmp_audit/",
)

RELEASE_SOURCE_PREFIXES = (
    ".github/workflows/",
    "docs/",
    "ea/",
    "scripts/",
    "tests/",
)

RELEASE_SOURCE_EXACT_PATHS = {
    ".env.example",
    ".env.local.example",
    "LTDs.md",
    "docker-compose.property.yml",
    "ea/Dockerfile.property",
    "ea/Dockerfile.property-web",
}

RELEASE_SOURCE_SUFFIXES = {
    ".html",
    ".j2",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}

ALLOWED_17217_HOST_PATHS = {
    "docker-compose.yml",
}

LOCAL_API_TOKEN_MARKER = "propertyquarry-" + "local-api-token"
LOCAL_BRIDGE_HOST = ".".join(("172", "17", "0", "1"))

TEXT_SUFFIXES = {
    ".py",
    ".sh",
    ".http",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".env",
}

BEARER_LITERAL_RE = re.compile(
    r"Authorization:\s*Bearer\s+(?!\$\{?[A-Z_][A-Z0-9_]*\}?|\{\{[^}]+\}\}|<token>|REDACTED\b)([A-Za-z0-9._-]+)",
    flags=re.IGNORECASE,
)
MANIFEST_RUNTIME_COMMIT_RE = re.compile(r"^\|\s*Runtime commit SHA\s*\|\s*`?([0-9a-f]{7,40})`?\s*\|", flags=re.MULTILINE)

RELEASE_METADATA_DESCENDANT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
}


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def git_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_commit_parent_shas(commit_sha: str) -> list[str]:
    if not commit_sha:
        return []
    result = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", commit_sha],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    revisions = result.stdout.strip().split()
    return revisions[1:] if len(revisions) > 1 else []


def git_head_parent_sha() -> str:
    parent_shas = git_commit_parent_shas(git_head_sha())
    return parent_shas[0] if parent_shas else ""


def git_commit_is_ancestor(commit_sha: str, head_sha: str) -> bool:
    if not commit_sha or not head_sha:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit_sha, head_sha],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def committed_paths_since(commit_sha: str, head_sha: str) -> list[str] | None:
    if not commit_sha or not head_sha:
        return None
    result = subprocess.run(
        [
            "git",
            "log",
            "-m",
            "--format=",
            "--name-only",
            "--no-renames",
            "-z",
            f"{commit_sha}..{head_sha}",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    if result.returncode != 0:
        return None
    return sorted(
        {
            raw_path.decode("utf-8", errors="surrogateescape")
            for raw_path in result.stdout.split(b"\0")
            if raw_path
        }
    )


def tree_paths_between(commit_sha: str, head_sha: str) -> list[str] | None:
    if not commit_sha or not head_sha:
        return None
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            commit_sha,
            head_sha,
            "--",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=False,
    )
    if result.returncode != 0:
        return None
    return sorted(
        {
            raw_path.decode("utf-8", errors="surrogateescape")
            for raw_path in result.stdout.split(b"\0")
            if raw_path
        }
    )


def _revisions_match(left_sha: str, right_sha: str) -> bool:
    return bool(left_sha and right_sha) and (
        left_sha.startswith(right_sha) or right_sha.startswith(left_sha)
    )


def _metadata_only(paths: list[str]) -> bool:
    return all(path in RELEASE_METADATA_DESCENDANT_PATHS for path in paths)


def manifest_release_binding(
    manifest_sha: str,
    head_sha: str,
    parent_shas: str | list[str],
) -> tuple[bool, list[str]]:
    if _revisions_match(manifest_sha, head_sha):
        return True, []
    if not git_commit_is_ancestor(manifest_sha, head_sha):
        return False, []

    normalized_parent_shas = (
        [parent_shas] if isinstance(parent_shas, str) else list(parent_shas)
    )
    if len(normalized_parent_shas) > 1:
        observed_paths: set[str] = set()
        for parent_sha in normalized_parent_shas:
            if _revisions_match(manifest_sha, parent_sha):
                parent_descendant_paths: list[str] = []
            elif git_commit_is_ancestor(manifest_sha, parent_sha):
                parent_descendant_paths = committed_paths_since(manifest_sha, parent_sha)
                if parent_descendant_paths is None:
                    continue
            else:
                continue
            observed_paths.update(parent_descendant_paths)
            if not _metadata_only(parent_descendant_paths):
                continue

            merge_tree_paths = tree_paths_between(parent_sha, head_sha)
            if merge_tree_paths is None:
                continue
            observed_paths.update(merge_tree_paths)
            if _metadata_only(merge_tree_paths):
                return True, sorted(set(parent_descendant_paths) | set(merge_tree_paths))
        return False, sorted(observed_paths)

    descendant_paths = committed_paths_since(manifest_sha, head_sha)
    if descendant_paths is None:
        return False, []
    return _metadata_only(descendant_paths), descendant_paths


def _git_status_rows() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def release_manifest_runtime_sha() -> str:
    manifest = ROOT / "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"
    try:
        values = load_release_manifest(manifest)
    except (OSError, ValueError):
        return ""
    return str(values.get("release_commit_sha") or "").strip()


def looks_like_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name.startswith(".env")


def _normalize_status_path(raw_path: str) -> str:
    normalized = str(raw_path or "").strip().replace("\\", "/")
    if " -> " in normalized:
        normalized = normalized.split(" -> ", 1)[1].strip()
    return normalized


def _is_release_source_path(rel_path: str) -> bool:
    normalized = str(rel_path or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in IGNORED_UNTRACKED_PREFIXES):
        return False
    if normalized in RELEASE_SOURCE_EXACT_PATHS:
        return True
    if any(normalized.startswith(prefix) for prefix in RELEASE_SOURCE_PREFIXES):
        return True
    return "/" not in normalized and Path(normalized).suffix.lower() in RELEASE_SOURCE_SUFFIXES


def build_release_hygiene_receipt() -> dict[str, object]:
    failures: list[str] = []
    manifest_sha = release_manifest_runtime_sha()
    head_sha = git_head_sha()
    parent_shas = git_commit_parent_shas(head_sha)
    parent_sha = parent_shas[0] if parent_shas else ""
    manifest_binding_ok = False
    manifest_descendant_paths: list[str] = []
    if not manifest_sha:
        failures.append("release manifest runtime commit missing: docs/PROPERTYQUARRY_RELEASE_MANIFEST.md")
    else:
        manifest_binding_ok, manifest_descendant_paths = manifest_release_binding(
            manifest_sha,
            head_sha,
            parent_shas,
        )
    if manifest_sha and not manifest_binding_ok:
        disallowed_descendants = [
            path for path in manifest_descendant_paths if path not in RELEASE_METADATA_DESCENDANT_PATHS
        ]
        failures.append(
            "release manifest runtime commit is not HEAD, its parent, or a metadata-only ancestor: "
            f"manifest={manifest_sha} head={head_sha} parents={parent_shas} "
            f"disallowed_descendants={disallowed_descendants}"
        )
    tracked_dirty_paths: list[str] = []
    untracked_release_source_paths: list[str] = []
    for row in _git_status_rows():
        if len(row) < 4:
            continue
        status_code = row[:2]
        path = _normalize_status_path(row[3:])
        if not path:
            continue
        if status_code == "??":
            if _is_release_source_path(path):
                untracked_release_source_paths.append(path)
            continue
        tracked_dirty_paths.append(path)
    if tracked_dirty_paths:
        preview = ", ".join(tracked_dirty_paths[:12])
        if len(tracked_dirty_paths) > 12:
            preview += f", +{len(tracked_dirty_paths) - 12} more"
        failures.append(f"tracked worktree must be clean before release: {preview}")
    if untracked_release_source_paths:
        preview = ", ".join(untracked_release_source_paths[:12])
        if len(untracked_release_source_paths) > 12:
            preview += f", +{len(untracked_release_source_paths) - 12} more"
        failures.append(f"untracked release source files forbidden before release: {preview}")
    for rel_path in tracked_paths():
        normalized = rel_path.replace("\\", "/")
        path = ROOT / normalized
        if not path.exists():
            continue
        if normalized in FORBIDDEN_TRACKED_EXACT_PATHS:
            failures.append(f"tracked live env file forbidden: {normalized}")
            continue
        if any(normalized.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES):
            failures.append(f"tracked audit scratch path forbidden: {normalized}")
            continue
        if any(normalized.endswith(suffix) for suffix in FORBIDDEN_AUDIT_SUFFIXES):
            failures.append(f"tracked audit artifact forbidden: {normalized}")
        if not path.is_file() or not looks_like_text(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if LOCAL_API_TOKEN_MARKER in text:
            failures.append(f"hardcoded local API token marker forbidden in tracked file: {normalized}")
        if LOCAL_BRIDGE_HOST in text and normalized not in ALLOWED_17217_HOST_PATHS:
            failures.append(f"raw {LOCAL_BRIDGE_HOST} host reference forbidden in tracked file: {normalized}")
        if BEARER_LITERAL_RE.search(text):
            failures.append(f"hardcoded bearer authorization forbidden in tracked file: {normalized}")
    required_checks = [
        "release_manifest_runtime_commit_matches_head_parent_or_metadata_only_ancestor",
        "tracked_worktree_clean",
        "no_untracked_release_source_files",
        "no_tracked_live_env_files",
        "no_tracked_audit_scratch_paths",
        "no_tracked_audit_artifacts",
        "no_hardcoded_local_api_token_marker",
        "no_raw_local_bridge_host_refs",
        "no_hardcoded_bearer_authorization",
    ]
    return {
        "schema": "propertyquarry.release_hygiene_receipt.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "pass" if not failures else "fail",
        "required_checks": required_checks,
        "failure_count": len(failures),
        "failures": failures,
        "manifest_runtime_commit": manifest_sha,
        "head_commit": head_sha,
        "parent_commit": parent_sha,
        "parent_commits": parent_shas,
        "manifest_descendant_paths": manifest_descendant_paths,
        "manifest_metadata_only_ancestor": bool(manifest_descendant_paths) and manifest_binding_ok,
        "tracked_dirty_path_count": len(tracked_dirty_paths),
        "untracked_release_source_count": len(untracked_release_source_paths),
        "note": "Repository hygiene and release-manifest authority gate for the tracked PropertyQuarry release plane.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check PropertyQuarry release hygiene.")
    parser.add_argument("--write", default="", help="Optional path for a JSON receipt.")
    args = parser.parse_args()

    receipt = build_release_hygiene_receipt()
    failures = list(receipt.get("failures") or [])
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failures:
        print("property release hygiene check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property release hygiene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
