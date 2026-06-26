#!/usr/bin/env python3
from __future__ import annotations

import re
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
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


def build_release_hygiene_receipt() -> dict[str, object]:
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
    required_checks = [
        "release_manifest_runtime_commit_matches_head_or_parent",
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
