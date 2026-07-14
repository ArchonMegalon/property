#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any


CANONICAL_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
CANONICAL_BROWSER_RECEIPT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
CANONICAL_FLAGSHIP_RECEIPT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
CANONICAL_RELEASE_MANIFEST = Path("docs/PROPERTYQUARRY_RELEASE_MANIFEST.md")
CANONICAL_WEEKLY_PULSE = Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json")
SOURCE_BINDING_VERSION = 1


class ReleaseBindingError(ValueError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: Path | str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseBindingError(f"release evidence path is not a safe repository-relative path: {path}")
    return path


def canonical_regular_file(root: Path, relative_path: Path | str) -> Path:
    root = root.resolve(strict=True)
    relative_path = _safe_relative_path(relative_path)
    candidate = root
    for index, part in enumerate(relative_path.parts):
        candidate = candidate / part
        try:
            mode = os.lstat(candidate).st_mode
        except OSError as exc:
            raise ReleaseBindingError(f"release evidence file is missing or unreadable: {relative_path}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise ReleaseBindingError(f"release evidence path contains a symlink: {relative_path}")
        if index < len(relative_path.parts) - 1 and not stat.S_ISDIR(mode):
            raise ReleaseBindingError(f"release evidence parent is not a directory: {relative_path}")
    if not stat.S_ISREG(mode):
        raise ReleaseBindingError(f"release evidence path is not a regular file: {relative_path}")
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReleaseBindingError(f"release evidence path escapes the repository: {relative_path}") from exc
    return candidate


def git_bytes(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseBindingError(f"git {' '.join(args)} failed: {detail or 'unknown git error'}")
    return bytes(completed.stdout)


def git_text(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8", errors="strict").strip()


def resolve_commit(root: Path, revision: str = "HEAD") -> str:
    commit = git_text(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not commit:
        raise ReleaseBindingError(f"Git revision did not resolve to a commit: {revision}")
    return commit.lower()


def commit_parents(root: Path, commit: str) -> list[str]:
    fields = git_text(root, "rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0].lower() != commit.lower():
        raise ReleaseBindingError(f"could not resolve commit parents for {commit}")
    return [item.lower() for item in fields[1:]]


def changed_paths(root: Path, parent: str, commit: str) -> list[str]:
    output = git_text(root, "diff-tree", "--no-commit-id", "--name-only", "-r", parent, commit)
    return [line.strip() for line in output.splitlines() if line.strip()]


def commit_timestamp(root: Path, commit: str) -> int:
    raw = git_text(root, "show", "-s", "--format=%ct", commit)
    try:
        return int(raw)
    except ValueError as exc:
        raise ReleaseBindingError(f"commit has an invalid timestamp: {commit}") from exc


def commit_file_bytes(root: Path, commit: str, relative_path: Path | str) -> bytes:
    relative_path = _safe_relative_path(relative_path)
    return git_bytes(root, "show", f"{commit}:{relative_path.as_posix()}")


def commit_file_oid(root: Path, commit: str, relative_path: Path | str) -> str:
    relative_path = _safe_relative_path(relative_path)
    return git_text(root, "rev-parse", f"{commit}:{relative_path.as_posix()}").lower()


def working_file_oid(root: Path, relative_path: Path | str) -> str:
    path = canonical_regular_file(root, relative_path)
    return git_text(root, "hash-object", "--no-filters", path.as_posix()).lower()


def file_digest_binding(root: Path, relative_path: Path | str) -> dict[str, str]:
    relative_path = _safe_relative_path(relative_path)
    path = canonical_regular_file(root, relative_path)
    return {
        "path": relative_path.as_posix(),
        "sha256": sha256_bytes(path.read_bytes()),
        "git_blob_oid": working_file_oid(root, relative_path),
    }


def _commit_bound_file(root: Path, relative_path: Path, code_commit: str) -> dict[str, str]:
    path = canonical_regular_file(root, relative_path)
    working_bytes = path.read_bytes()
    committed_bytes = commit_file_bytes(root, code_commit, relative_path)
    if working_bytes != committed_bytes:
        raise ReleaseBindingError(
            f"release source differs from immutable code commit {code_commit}: {relative_path.as_posix()}"
        )
    return {
        "path": relative_path.as_posix(),
        "sha256": sha256_bytes(working_bytes),
        "git_blob_oid": commit_file_oid(root, code_commit, relative_path),
    }


def build_source_binding(
    root: Path,
    *,
    seed_path: Path | str,
    evidence_sources: object,
    code_commit: str | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    seed_path = _safe_relative_path(seed_path)
    code_commit = resolve_commit(root, code_commit or "HEAD")
    if not isinstance(evidence_sources, list):
        raise ReleaseBindingError("flagship seed lacks browser evidence source nodes")
    source_paths: list[Path] = []
    for entry in evidence_sources:
        if not isinstance(entry, dict):
            raise ReleaseBindingError("flagship seed contains an invalid browser evidence source node")
        source_path = _safe_relative_path(str(entry.get("file") or ""))
        cases = [str(item).strip() for item in entry.get("cases") or [] if str(item).strip()]
        if not cases:
            raise ReleaseBindingError(f"browser evidence source lacks required cases: {source_path.as_posix()}")
        source_paths.append(source_path)
    if len(source_paths) != 2 or len({path.as_posix() for path in source_paths}) != 2:
        raise ReleaseBindingError("flagship seed must define exactly two distinct browser evidence sources")
    return {
        "version": SOURCE_BINDING_VERSION,
        "code_commit": code_commit,
        "seed": _commit_bound_file(root, seed_path, code_commit),
        "required_test_sources": [
            _commit_bound_file(root, source_path, code_commit) for source_path in source_paths
        ],
    }
