#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


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


def git_head_parent_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD^"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def release_manifest_runtime_sha() -> str:
    manifest = ROOT / "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"
    try:
        body = manifest.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    match = MANIFEST_RUNTIME_COMMIT_RE.search(body)
    return match.group(1).strip() if match else ""


def looks_like_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name.startswith(".env")


def main() -> int:
    failures: list[str] = []
    manifest_sha = release_manifest_runtime_sha()
    head_sha = git_head_sha()
    parent_sha = git_head_parent_sha()
    if not manifest_sha:
        failures.append("release manifest runtime commit missing: docs/PROPERTYQUARRY_RELEASE_MANIFEST.md")
    elif not (
        head_sha.startswith(manifest_sha)
        or manifest_sha.startswith(head_sha)
        or (parent_sha and parent_sha.startswith(manifest_sha))
        or (parent_sha and manifest_sha.startswith(parent_sha))
    ):
        failures.append(
            "release manifest runtime commit does not match current HEAD or deployed parent: "
            f"manifest={manifest_sha} head={head_sha} parent={parent_sha}"
        )
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
    if failures:
        print("property release hygiene check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property release hygiene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
