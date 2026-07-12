#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.propertyquarry_live_http_security import validated_live_base_origin


_FULL_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def build_live_release_provenance_receipt(
    *,
    base_url: str,
    expected_commit_sha: str,
    expected_branch: str = "main",
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    expected_sha = str(expected_commit_sha or "").strip().lower()
    expected_branch_name = str(expected_branch or "main").strip() or "main"
    checks: list[dict[str, object]] = []
    try:
        origin = validated_live_base_origin(base_url)
    except ValueError as exc:
        checks.append({"name": "live_base_origin_safe", "ok": False, "reason": str(exc)})
        return {
            "contract_name": "propertyquarry.live_release_provenance.v1",
            "generated_at": generated_at,
            "status": "blocked",
            "base_url": str(base_url or ""),
            "expected_commit_sha": expected_sha,
            "expected_branch": expected_branch_name,
            "checks": checks,
        }
    if _FULL_GIT_SHA_PATTERN.fullmatch(expected_sha) is None:
        checks.append({"name": "expected_commit_sha_full", "ok": False})
        return {
            "contract_name": "propertyquarry.live_release_provenance.v1",
            "generated_at": generated_at,
            "status": "blocked",
            "base_url": origin,
            "expected_commit_sha": expected_sha,
            "expected_branch": expected_branch_name,
            "checks": checks,
        }

    request = urllib.request.Request(
        f"{origin}/version",
        headers={
            "Accept": "application/json",
            "User-Agent": "PropertyQuarry-live-release-provenance/1.0",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=max(1.0, float(timeout_seconds))) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            body = response.read(200_000)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code or 0)
        body = exc.read(200_000)
    except Exception as exc:
        checks.append({"name": "version_reachable", "ok": False, "reason": type(exc).__name__})
        return {
            "contract_name": "propertyquarry.live_release_provenance.v1",
            "generated_at": generated_at,
            "status": "fail",
            "base_url": origin,
            "expected_commit_sha": expected_sha,
            "expected_branch": expected_branch_name,
            "checks": checks,
        }

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    actual_sha = str(payload.get("release_commit_sha") or "").strip().lower()
    actual_branch = str(payload.get("release_branch") or "").strip()
    deployment_id = str(payload.get("release_deployment_id") or "").strip()
    checks.extend(
        [
            {"name": "version_status_ok", "ok": status_code == 200, "status_code": status_code},
            {"name": "release_commit_sha_full", "ok": _FULL_GIT_SHA_PATTERN.fullmatch(actual_sha) is not None},
            {"name": "release_commit_matches", "ok": actual_sha == expected_sha},
            {"name": "release_branch_matches", "ok": actual_branch == expected_branch_name},
            {"name": "release_deployment_id_present", "ok": bool(deployment_id)},
        ]
    )
    failed = [check for check in checks if not bool(check.get("ok"))]
    return {
        "contract_name": "propertyquarry.live_release_provenance.v1",
        "generated_at": generated_at,
        "status": "pass" if not failed else "fail",
        "base_url": origin,
        "expected_commit_sha": expected_sha,
        "expected_branch": expected_branch_name,
        "actual_commit_sha": actual_sha,
        "actual_branch": actual_branch,
        "deployment_id_present": bool(deployment_id),
        "failed_count": len(failed),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify that live PropertyQuarry provenance matches the dispatched commit.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("PROPERTYQUARRY_LIVE_MOBILE_BASE_URL")
        or os.getenv("PROPERTYQUARRY_LIVE_SMOKE_BASE_URL")
        or "",
    )
    parser.add_argument(
        "--expected-commit-sha",
        default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA") or "",
    )
    parser.add_argument("--expected-branch", default=os.getenv("PROPERTYQUARRY_EXPECTED_RELEASE_BRANCH") or "main")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--write", default="_completion/smoke/property-live-release-provenance.json")
    args = parser.parse_args()
    receipt = build_live_release_provenance_receipt(
        base_url=str(args.base_url or ""),
        expected_commit_sha=str(args.expected_commit_sha or ""),
        expected_branch=str(args.expected_branch or "main"),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        output_path = Path(args.write)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
