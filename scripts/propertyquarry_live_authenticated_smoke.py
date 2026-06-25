#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable


DEFAULT_ROUTES = (
    "/app/account",
    "/app/billing",
    "/sign-in",
)
MAX_RESPONSE_BODY_BYTES = 900_000

FORBIDDEN_CUSTOMER_NOISE = (
    "billing truth",
    "plan and limits",
    "refresh delivery",
    "repair status checked",
    "what happened",
    "what still worked",
    "main blocker",
    "best next move",
)
BILLING_FAIL_CLOSED_MARKERS = (
    "billing handoff unavailable",
    "external account lane",
    "white-label billing url",
)
BILLING_LOCAL_BOARD_MARKERS = (
    "open pricing",
    "compare plans",
    "plus checkout",
    "billing history",
    "current commercial state",
    "plan posture",
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _compact_snippet(text: str, *, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", str(text or "")[:limit]).strip()


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _visible_text(text: str) -> str:
    without_hidden = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_hidden)
    return re.sub(r"\s+", " ", without_tags).strip()


def _header_value(headers: dict[str, object], name: str) -> str:
    normalized_name = str(name or "").strip().lower()
    for key, value in headers.items():
        if str(key or "").strip().lower() == normalized_name:
            return str(value or "").strip()
    return ""


def _security_header_checks(*, headers: dict[str, object]) -> list[tuple[str, bool]]:
    csp = _header_value(headers, "Content-Security-Policy")
    permissions = _header_value(headers, "Permissions-Policy")
    return [
        ("security_csp", "default-src 'self'" in csp and "frame-ancestors 'self'" in csp),
        ("security_nosniff", _header_value(headers, "X-Content-Type-Options").lower() == "nosniff"),
        ("security_referrer_policy", _header_value(headers, "Referrer-Policy") == "strict-origin-when-cross-origin"),
        ("security_permissions_policy", "camera=()" in permissions and "microphone=()" in permissions),
    ]


def fetch_url(
    url: str,
    *,
    timeout_seconds: float,
    api_token: str,
    principal_id: str,
    country_code: str,
) -> dict[str, object]:
    headers = {
        "User-Agent": "PropertyQuarry-live-authenticated-smoke/1.0",
        "Accept": "text/html,application/json,*/*",
        "Host": "propertyquarry.com",
        "X-EA-Principal-ID": principal_id,
        "cf-ipcountry": country_code,
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_NoRedirectHandler)
    started = datetime.now(timezone.utc)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            ended = datetime.now(timezone.utc)
            return {
                "status_code": int(response.status),
                "final_url": str(response.geturl()),
                "headers": dict(response.headers.items()),
                "body": response.read(MAX_RESPONSE_BODY_BYTES),
                "duration_ms": int((ended - started).total_seconds() * 1000),
            }
    except urllib.error.HTTPError as exc:
        ended = datetime.now(timezone.utc)
        return {
            "status_code": int(exc.code),
            "final_url": str(exc.geturl()),
            "headers": dict(exc.headers.items()),
            "body": exc.read(MAX_RESPONSE_BODY_BYTES),
            "duration_ms": int((ended - started).total_seconds() * 1000),
        }
    except Exception as exc:
        ended = datetime.now(timezone.utc)
        return {
            "status_code": 0,
            "final_url": url,
            "headers": {},
            "body": b"",
            "duration_ms": int((ended - started).total_seconds() * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _route_checks(*, path: str, text: str, expected_plan_label: str) -> list[tuple[str, bool]]:
    visible_text = _visible_text(text)
    lowered_visible = visible_text.lower()
    checks: list[tuple[str, bool]] = []
    if path == "/app/account":
        account_logout_count = len(re.findall(r">Log out<", text))
        checks.extend(
            (
                ("account_heading", "<h2>Account</h2>" in text or ">Account<" in text),
                ("account_notifications", "<h2>Notifications</h2>" in text),
                ("account_paid_plan", f"<h2>{expected_plan_label}</h2>" in text if expected_plan_label else True),
                ("account_logout_strip", "pqx-account-logout-strip" in text and "Current session" in text),
                ("account_single_logout", account_logout_count == 1),
                ("account_no_customer_noise", not any(noise in lowered_visible for noise in FORBIDDEN_CUSTOMER_NOISE)),
            )
        )
    elif path == "/app/billing":
        checks.extend(
            (
                (
                    "billing_fail_closed_recovery",
                    all(marker in lowered_visible for marker in BILLING_FAIL_CLOSED_MARKERS),
                ),
                ("billing_no_self_link", 'href="/app/billing"' not in text),
                (
                    "billing_local_board_deleted",
                    not any(marker in lowered_visible for marker in BILLING_LOCAL_BOARD_MARKERS),
                ),
                ("billing_no_customer_noise", not any(noise in lowered_visible for noise in FORBIDDEN_CUSTOMER_NOISE)),
            )
        )
    elif path == "/sign-in":
        logout_count = len(re.findall(r">Log out<", text))
        checks.extend(
            (
                ("sign_in_current_session", "Open current session" in visible_text or "Open search" in visible_text),
                ("sign_in_single_logout", logout_count == 1),
                ("sign_in_google_state", "Continue with Google" in visible_text),
                (
                    "sign_in_provider_creates_account",
                    "First-time provider sign-in" in visible_text
                    and "creates the account automatically" in visible_text,
                ),
                (
                    "sign_in_no_unavailable_auth_copy",
                    "temporarily unavailable" not in lowered_visible
                    and "email delivery is unavailable" not in lowered_visible
                    and "config_missing" not in lowered_visible,
                ),
                ("sign_in_no_double_logout", logout_count <= 1),
            )
        )
    return checks


def build_live_authenticated_smoke_receipt(
    *,
    base_url: str,
    api_token: str,
    principal_id: str,
    expected_plan_label: str = "",
    country_code: str = "AT",
    timeout_seconds: float = 8.0,
    retry_count: int = 2,
    retry_backoff_seconds: float = 0.75,
    routes: tuple[str, ...] = DEFAULT_ROUTES,
    fetcher: Callable[[str, float], dict[str, object]] | None = None,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    failures = 0

    def _default_fetcher(url: str, timeout: float) -> dict[str, object]:
        return fetch_url(
            url,
            timeout_seconds=timeout,
            api_token=api_token,
            principal_id=principal_id,
            country_code=country_code,
        )

    effective_fetcher = fetcher or _default_fetcher
    for path in routes:
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        attempts: list[dict[str, object]] = []
        max_attempts = max(1, int(retry_count) + 1)
        for attempt_index in range(max_attempts):
            result = effective_fetcher(url, timeout_seconds)
            attempts.append(result)
            status_code = int(result.get("status_code") or 0)
            transient_failure = bool(result.get("error")) or status_code == 0 or status_code >= 500
            if not transient_failure or attempt_index >= max_attempts - 1:
                break
            sleep(max(0.0, float(retry_backoff_seconds)) * float(attempt_index + 1))
        result = attempts[-1]
        status_code = int(result.get("status_code") or 0)
        headers = dict(result.get("headers") or {})
        body = bytes(result.get("body") or b"")
        text = _decode_body(body)
        if path == "/app/billing" and status_code in {303, 307}:
            location = _header_value(headers, "Location")
            route_checks = [
                ("status_ok", True),
                *_security_header_checks(headers=headers),
                ("billing_external_handoff", location.startswith("https://") and "/app/billing" not in location),
                ("billing_local_board_deleted", True),
                ("billing_no_customer_noise", True),
            ]
        elif path == "/app/billing" and status_code == 503:
            route_checks = [
                ("status_ok", True),
                *_security_header_checks(headers=headers),
                *_route_checks(path=path, text=text, expected_plan_label=expected_plan_label),
            ]
        else:
            route_checks = [
                *(
                    [("status_ok", status_code == 200)]
                    if path in {"/app/account", "/app/billing", "/sign-in"}
                    else []
                ),
                *_security_header_checks(headers=headers),
                *_route_checks(path=path, text=text, expected_plan_label=expected_plan_label),
            ]
        ok = all(passed for _, passed in route_checks) and not result.get("error")
        if not ok:
            failures += 1
        checks.append(
            {
                "path": path,
                "status_code": status_code,
                "ok": ok,
                "final_url": str(result.get("final_url") or url),
                "duration_ms": int(result.get("duration_ms") or 0),
                "attempt_count": len(attempts),
                "content_type": _header_value(headers, "Content-Type"),
                "checks": [{"name": name, "ok": passed} for name, passed in route_checks],
                "snippet": _compact_snippet(text),
                "error": str(result.get("error") or ""),
            }
        )
    return {
        "base_url": base_url,
        "principal_id": principal_id,
        "expected_plan_label": expected_plan_label,
        "country_code": country_code,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route_count": len(routes),
        "failed_count": failures,
        "status": "pass" if failures == 0 else "fail",
        "checks": checks,
        "notes": [
            "This smoke is authenticated and read-only.",
            "It verifies paid customer surfaces: account, billing, and sign-in state.",
        ],
    }


def main() -> int:
    if len(os.sys.argv) > 1 and os.sys.argv[1] in {"--help", "-h"}:
        print(
            "Usage:\n"
            "  python3 scripts/propertyquarry_live_authenticated_smoke.py [--base-url <url>] [--principal-id <id>]\n\n"
            "Smokes the authenticated PropertyQuarry runtime surfaces using EA_API_TOKEN."
        )
        return 0
    parser = argparse.ArgumentParser(description="PropertyQuarry authenticated live runtime smoke.")
    parser.add_argument("--base-url", default=_env_value("PROPERTYQUARRY_LIVE_SMOKE_BASE_URL") or "http://localhost:8097")
    parser.add_argument("--principal-id", default=_env_value("PROPERTYQUARRY_LIVE_SMOKE_PRINCIPAL_ID") or _env_value("EA_PRINCIPAL_ID") or "cf-email:tibor.girschele@gmail.com")
    parser.add_argument("--expected-plan-label", default=_env_value("PROPERTYQUARRY_LIVE_SMOKE_PLAN_LABEL") or "Agent")
    parser.add_argument("--country-code", default=_env_value("PROPERTYQUARRY_LIVE_SMOKE_COUNTRY_CODE") or "AT")
    parser.add_argument("--api-token", default=_env_value("EA_API_TOKEN"))
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.75)
    args = parser.parse_args()

    if not str(args.api_token or "").strip():
        raise SystemExit("EA_API_TOKEN is required for authenticated live smoke.")

    receipt = build_live_authenticated_smoke_receipt(
        base_url=str(args.base_url),
        api_token=str(args.api_token),
        principal_id=str(args.principal_id),
        expected_plan_label=str(args.expected_plan_label),
        country_code=str(args.country_code),
        timeout_seconds=float(args.timeout_seconds),
        retry_count=int(args.retry_count),
        retry_backoff_seconds=float(args.retry_backoff_seconds),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
