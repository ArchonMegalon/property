#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DEFAULT_ROUTES = (
    "/",
    "/security",
    "/pricing",
    "/directory",
    "/directory/profile/sample",
    "/privacy",
    "/terms",
    "/support",
    "/imprint",
    "/cookies",
    "/subprocessors",
    "/refunds",
    "/disclaimers",
    "/register",
    "/sign-in",
    "/manifest.webmanifest",
    "/service-worker.js",
    "/robots.txt",
    "/sitemap.xml",
    "/app/properties",
)


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


def _security_header_checks(*, path: str, final_url: str, headers: dict[str, object]) -> list[tuple[str, bool]]:
    html_like_paths = {
        "/",
        "/security",
        "/pricing",
        "/directory",
        "/directory/profile/sample",
        "/privacy",
        "/terms",
        "/support",
        "/imprint",
        "/cookies",
        "/subprocessors",
        "/refunds",
        "/disclaimers",
        "/register",
        "/sign-in",
        "/app/properties",
    }
    if path not in html_like_paths:
        return []
    csp = _header_value(headers, "Content-Security-Policy")
    permissions = _header_value(headers, "Permissions-Policy")
    parsed_final = urllib.parse.urlparse(str(final_url or ""))
    checks = [
        ("security_csp", "default-src 'self'" in csp and "frame-ancestors 'self'" in csp),
        ("security_nosniff", _header_value(headers, "X-Content-Type-Options").lower() == "nosniff"),
        ("security_referrer_policy", _header_value(headers, "Referrer-Policy") == "strict-origin-when-cross-origin"),
        ("security_permissions_policy", "camera=()" in permissions and "microphone=()" in permissions),
    ]
    if parsed_final.scheme == "https":
        checks.append(
            (
                "security_hsts",
                _header_value(headers, "Strict-Transport-Security").lower().startswith("max-age=31536000"),
            )
        )
    return checks


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def fetch_url(url: str, *, timeout_seconds: float, follow_redirects: bool = True) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PropertyQuarry-live-smoke/1.0",
            "Accept": "text/html,application/json,*/*",
        },
    )
    started = time.perf_counter()
    try:
        opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=timeout_seconds) as response:
            return {
                "status_code": int(response.status),
                "final_url": str(response.geturl()),
                "headers": dict(response.headers.items()),
                "body": response.read(220_000),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status_code": int(exc.code),
            "final_url": str(exc.geturl()),
            "headers": dict(exc.headers.items()),
            "body": exc.read(220_000),
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "final_url": url,
            "headers": {},
            "body": b"",
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _route_checks(*, path: str, status_code: int, final_url: str, text: str) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    visible_text = _visible_text(text)
    if path in {
        "/",
        "/security",
        "/pricing",
        "/directory",
        "/directory/profile/sample",
        "/privacy",
        "/terms",
        "/support",
        "/imprint",
        "/cookies",
        "/subprocessors",
        "/refunds",
        "/disclaimers",
        "/register",
        "/sign-in",
    }:
        checks.extend(
            (
                ("contains_propertyquarry", "PropertyQuarry" in text),
                ("no_chummer_copy", "chummer" not in text.lower()),
                ("no_generic_ea_copy", "Executive Assistant" not in text and "Morning Memo" not in text),
            )
        )
    if path == "/":
        checks.append(("home_has_main_copy", "Search once. Rank the right homes. Decide with evidence." in text))
        checks.append(("home_no_visible_proof_noise", "proof" not in visible_text.lower()))
        checks.append(("home_no_legacy_proof_component", "pq-proof" not in text.lower()))
    elif path == "/security":
        checks.extend(
            (
                (
                    "security_route_copy",
                    "Strict rules. Smart ranking." in text
                    and "Score guide" in text
                    and "Hard filters decide eligibility" in text
                    and "/how-it-works/score" in text
                    and "You choose what is shared" in text,
                ),
                ("security_old_proof_copy_removed", "release-side proof" not in text.lower()),
                ("security_no_internal_release_copy", "Release checks and security review" not in text),
            )
        )
    elif path == "/pricing":
        checks.extend(
            (
                ("pricing_minimal_copy", "Pricing" in text and "Start free" in text),
                ("pricing_old_noise_removed", "Choose the lane that matches the real search workload" not in text),
                ("pricing_subtitle_removed", "Choose by sources, shortlist size, and research depth." not in text),
            )
        )
    elif path == "/directory":
        lowered_visible = visible_text.lower()
        checks.extend(
            (
                (
                    "directory_white_label",
                    "PropertyQuarry directory" in text
                    and "brilliant directories" not in lowered_visible
                    and "brilliantdirectories" not in lowered_visible
                    and "credentials" not in lowered_visible
                    and "not active on this host" not in lowered_visible
                    and "provider returned" not in lowered_visible
                    and "provider stores" not in lowered_visible,
                ),
                (
                    "directory_action_state",
                    (
                        "Search directory" in text
                        and "Directory coming soon" not in text
                    )
                    or (
                        "Directory coming soon" in text
                        and "Search directory" not in text
                        and ">Reset<" not in text
                        and ">Clear<" not in text
                    ),
                ),
                (
                    "directory_empty_noindex",
                    "Directory opening soon" not in text
                    and "governed directory lane" not in text
                    and 'name="robots" content="noindex, follow, noarchive, nosnippet"' in text,
                ),
            )
        )
    elif path.startswith("/directory/profile/"):
        lowered_visible = visible_text.lower()
        checks.extend(
            (
                ("directory_profile_white_label", "Profile details stay on PropertyQuarry" in text and "brilliant directories" not in lowered_visible and "brilliantdirectories" not in lowered_visible),
                ("directory_profile_local_navigation", "Back to directory" in text and "Contact support" in text),
                (
                    "directory_profile_placeholder_noindex",
                    "Profile details stay on PropertyQuarry" not in text
                    or (
                        'name="robots" content="noindex, follow, noarchive, nosnippet"' in text
                        and "another branded site" not in text
                    ),
                ),
            )
        )
    elif path in {"/privacy", "/terms", "/support", "/imprint", "/cookies", "/subprocessors", "/refunds", "/disclaimers"}:
        expected_by_path = {
            "/privacy": ("Privacy", "Public tours should use a narrow public manifest"),
            "/terms": ("Terms", "Generated or embedded tours help screening"),
            "/support": ("Support", "wrong-area matches"),
            "/imprint": ("Imprint", "How to reach PropertyQuarry"),
            "/cookies": ("Cookies and Analytics", "essential cookies"),
            "/subprocessors": ("Subprocessors", "Service partner registry"),
            "/refunds": ("Refunds and Cancellation", "failed payment recovery"),
            "/disclaimers": ("Disclaimers", "Generated visualization"),
        }
        expected = expected_by_path[path]
        checks.extend(
            (
                ("trust_page_title", expected[0] in text),
                ("trust_page_substance", expected[1] in text),
                ("trust_page_no_placeholder", "Before public paid launch" not in text and "Replace placeholder" not in text),
                (
                    "trust_page_no_operator_secret_copy",
                    "credentials" not in visible_text.lower()
                    and "provider login" not in visible_text.lower()
                    and "api key" not in visible_text.lower(),
                ),
            )
        )
    elif path == "/sign-in":
        google_active = 'href="/sign-in/google"' in text and "Continue with Google" in text
        google_unavailable = 'href="/sign-in/google"' not in text and "Google unavailable" in text
        facebook_active = 'href="/sign-in/facebook"' in text and "Continue with Facebook" in text
        facebook_unavailable = 'href="/sign-in/facebook"' not in text and "Facebook unavailable" in text
        google_hidden = 'href="/sign-in/google"' not in text and "Google unavailable" not in text
        facebook_hidden = 'href="/sign-in/facebook"' not in text and "Facebook unavailable" not in text
        checks.extend(
            (
                (
                    "sign_in_minimal_copy",
                    "Use a saved session, email link, or connected identity." in text
                    and "Identity only" not in text
                    and "Identity-only." not in text
                    and "Google?" not in text
                    and "Facebook?" not in text,
                ),
                ("sign_in_google_state", google_active or google_unavailable or google_hidden),
                ("sign_in_facebook_state", facebook_active or facebook_unavailable or facebook_hidden),
                (
                    "sign_in_google_feedback",
                    (not google_active) or 'data-submitting-label="Opening Google..."' in text,
                ),
            )
        )
        if "Continue with Facebook" in text or 'href="/sign-in/facebook"' in text:
            checks.extend(
                (
                    ("sign_in_facebook_control", 'href="/sign-in/facebook"' in text),
                    ("sign_in_facebook_feedback", 'data-submitting-label="Opening Facebook..."' in text),
                )
            )
    elif path == "/manifest.webmanifest":
        try:
            manifest_payload = json.loads(text)
        except Exception:
            manifest_payload = {}
        icons = manifest_payload.get("icons") if isinstance(manifest_payload, dict) else []
        icon_rows = [dict(row) for row in icons if isinstance(row, dict)] if isinstance(icons, list) else []
        shortcuts = manifest_payload.get("shortcuts") if isinstance(manifest_payload, dict) else []
        shortcut_urls = {
            str(row.get("url") or "").strip()
            for row in shortcuts
            if isinstance(row, dict)
        } if isinstance(shortcuts, list) else set()
        checks.extend(
            (
                ("manifest_name", isinstance(manifest_payload, dict) and manifest_payload.get("name") == "PropertyQuarry"),
                (
                    "manifest_language_direction",
                    isinstance(manifest_payload, dict)
                    and manifest_payload.get("lang") == "en"
                    and manifest_payload.get("dir") == "ltr",
                ),
                ("manifest_id", isinstance(manifest_payload, dict) and manifest_payload.get("id") == "/app/search"),
                ("manifest_start_url", isinstance(manifest_payload, dict) and manifest_payload.get("start_url") == "/app/search"),
                ("manifest_display_scope", isinstance(manifest_payload, dict) and manifest_payload.get("display") == "standalone" and manifest_payload.get("scope") == "/"),
                (
                    "manifest_display_override",
                    isinstance(manifest_payload, dict)
                    and "standalone" in list(manifest_payload.get("display_override") or []),
                ),
                (
                    "manifest_launch_handler",
                    isinstance(manifest_payload, dict)
                    and dict(manifest_payload.get("launch_handler") or {}).get("client_mode") == "navigate-existing",
                ),
                (
                    "manifest_related_apps_disabled",
                    isinstance(manifest_payload, dict)
                    and manifest_payload.get("prefer_related_applications") is False,
                ),
                (
                    "manifest_maskable_icon",
                    any(str(row.get("src") or "") == "/pwa-icon.svg" and "maskable" in str(row.get("purpose") or "") for row in icon_rows),
                ),
                (
                    "manifest_png_install_icons",
                    {
                        (str(row.get("src") or ""), str(row.get("sizes") or ""), str(row.get("type") or ""))
                        for row in icon_rows
                    }
                    >= {
                        ("/pwa-icon-192.png", "192x192", "image/png"),
                        ("/pwa-icon-512.png", "512x512", "image/png"),
                    },
                ),
                (
                    "manifest_core_shortcuts",
                    {"/app/search", "/app/properties", "/app/shortlist", "/app/agents"}.issubset(shortcut_urls),
                ),
            )
        )
    elif path == "/service-worker.js":
        checks.append(("service_worker_no_cache_api", "caches." not in text and "skipWaiting" in text))
    elif path == "/robots.txt":
        checks.append(("robots_sitemap", "Sitemap: https://propertyquarry.com/sitemap.xml" in text))
    elif path == "/sitemap.xml":
        parsed_final = urllib.parse.urlparse(str(final_url or ""))
        sitemap_origin = f"{parsed_final.scheme}://{parsed_final.netloc}" if parsed_final.scheme and parsed_final.netloc else "https://propertyquarry.com"
        checks.append(
            (
                "sitemap_core",
                (f"<loc>{sitemap_origin}/</loc>" in text and f"<loc>{sitemap_origin}/pricing</loc>" in text)
                or (
                    "<loc>https://propertyquarry.com/</loc>" in text
                    and "<loc>https://propertyquarry.com/pricing</loc>" in text
                ),
            )
        )
    elif path == "/app/properties":
        checks.extend(
            (
                (
                    "app_boundary",
                    status_code in {200, 401, 403}
                    or "/sign-in" in final_url
                    or "/app/search" in final_url
                    or "/app/properties" in final_url,
                ),
                ("not_public_home_leak", "Search once. Rank the right homes. Decide with evidence." not in text),
            )
        )
    return checks


def _redirect_location(result: dict[str, object]) -> str:
    headers = dict(result.get("headers") or {})
    return _header_value(headers, "Location")


def _oauth_redirect_row(
    *,
    path: str,
    result: dict[str, object],
    checks: list[tuple[str, bool]],
) -> dict[str, object]:
    status_code = int(result.get("status_code") or 0)
    final_url = str(result.get("final_url") or "")
    headers = dict(result.get("headers") or {})
    location = _redirect_location(result)
    ok = status_code in {302, 303, 307, 308} and bool(location) and all(value for _, value in checks)
    return {
        "path": path,
        "status_code": status_code,
        "final_url": final_url,
        "duration_ms": int(result.get("duration_ms") or 0),
        "content_type": str(headers.get("Content-Type") or ""),
        "x_robots_tag": str(headers.get("X-Robots-Tag") or ""),
        "ok": ok,
        "checks": [{"name": name, "ok": value} for name, value in checks],
        "error": str(result.get("error") or ""),
        "snippet": _compact_snippet(location),
    }


def _sign_in_provider_redirect_checks(
    *,
    normalized_base: str,
    sign_in_text: str,
    timeout_seconds: float,
    redirect_fetcher: Callable[[str, float], dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if 'href="/sign-in/google"' in sign_in_text:
        path = "/sign-in/google"
        result = redirect_fetcher(f"{normalized_base}{path}", timeout_seconds)
        location = _redirect_location(result)
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)
        scopes = set(str(query.get("scope", [""])[0]).replace(",", " ").split())
        rows.append(
            _oauth_redirect_row(
                path=path,
                result=result,
                checks=[
                    ("google_redirect_host", parsed.scheme == "https" and parsed.netloc == "accounts.google.com"),
                    ("google_identity_scope", {"openid", "email", "profile"}.issubset(scopes)),
                    ("google_callback_uri", str(query.get("redirect_uri", [""])[0]).endswith("/google/callback")),
                    ("google_state_present", bool(query.get("state", [""])[0])),
                ],
            )
        )
    if 'href="/sign-in/facebook"' in sign_in_text:
        path = "/sign-in/facebook"
        result = redirect_fetcher(f"{normalized_base}{path}", timeout_seconds)
        location = _redirect_location(result)
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)
        scope_text = str(query.get("scope", [""])[0])
        scopes = set(scope_text.replace(",", " ").split())
        rows.append(
            _oauth_redirect_row(
                path=path,
                result=result,
                checks=[
                    ("facebook_redirect_host", parsed.scheme == "https" and parsed.netloc == "www.facebook.com"),
                    ("facebook_public_profile_scope", scopes == {"public_profile"}),
                    ("facebook_no_email_scope", "email" not in scopes and "email" not in scope_text),
                    ("facebook_callback_uri", str(query.get("redirect_uri", [""])[0]).endswith("/facebook/callback")),
                    ("facebook_state_present", bool(query.get("state", [""])[0])),
                ],
            )
        )
    if 'href="/sign-in/id-austria"' in sign_in_text:
        path = "/sign-in/id-austria"
        result = redirect_fetcher(f"{normalized_base}{path}", timeout_seconds)
        location = _redirect_location(result)
        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)
        scopes = set(str(query.get("scope", [""])[0]).replace(",", " ").split())
        rows.append(
            _oauth_redirect_row(
                path=path,
                result=result,
                checks=[
                    ("id_austria_redirect_host", parsed.scheme == "https" and parsed.netloc.endswith("id-austria.gv.at")),
                    ("id_austria_authorize_path", parsed.path.endswith("/authorize")),
                    ("id_austria_identity_scope", {"openid", "profile"}.issubset(scopes)),
                    ("id_austria_callback_uri", str(query.get("redirect_uri", [""])[0]).endswith("/id-austria/callback")),
                    ("id_austria_state_present", bool(query.get("state", [""])[0])),
                ],
            )
        )
    return rows


def build_live_public_smoke_receipt(
    *,
    base_url: str = "https://propertyquarry.com",
    routes: tuple[str, ...] = DEFAULT_ROUTES,
    timeout_seconds: float = 12.0,
    fetcher: Callable[[str, float], dict[str, object]] | None = None,
) -> dict[str, object]:
    normalized_base = str(base_url or "").strip().rstrip("/") or "https://propertyquarry.com"
    fetch = fetcher or (lambda url, timeout: fetch_url(url, timeout_seconds=timeout))
    redirect_fetch = fetcher or (lambda url, timeout: fetch_url(url, timeout_seconds=timeout, follow_redirects=False))
    checks: list[dict[str, object]] = []
    sign_in_text = ""
    for raw_path in routes:
        path = "/" + str(raw_path or "").strip().lstrip("/")
        url = f"{normalized_base}{path}"
        result = fetch(url, timeout_seconds)
        body = result.get("body")
        body_bytes = body if isinstance(body, bytes) else str(body or "").encode("utf-8")
        text = _decode_body(body_bytes)
        status_code = int(result.get("status_code") or 0)
        final_url = str(result.get("final_url") or url)
        headers = dict(result.get("headers") or {})
        if path == "/sign-in":
            sign_in_text = text
        route_checks = _route_checks(path=path, status_code=status_code, final_url=final_url, text=text)
        route_checks.extend(_security_header_checks(path=path, final_url=final_url, headers=headers))
        ok = status_code < 500 and status_code > 0 and all(value for _, value in route_checks)
        checks.append(
            {
                "path": path,
                "status_code": status_code,
                "final_url": final_url,
                "duration_ms": int(result.get("duration_ms") or 0),
                "content_type": str(headers.get("Content-Type") or ""),
                "x_robots_tag": str(headers.get("X-Robots-Tag") or ""),
                "ok": ok,
                "checks": [{"name": name, "ok": value} for name, value in route_checks],
                "error": str(result.get("error") or ""),
                "snippet": _compact_snippet(text),
            }
        )
    if sign_in_text:
        checks.extend(
            _sign_in_provider_redirect_checks(
                normalized_base=normalized_base,
                sign_in_text=sign_in_text,
                timeout_seconds=timeout_seconds,
                redirect_fetcher=redirect_fetch,
            )
        )
    failed = [row for row in checks if not bool(row.get("ok"))]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": normalized_base,
        "status": "pass" if not failed else "fail",
        "route_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
        "notes": [
            "This smoke is public and non-mutating.",
            "It verifies Cloudflare/origin availability, PropertyQuarry public copy, PWA assets, SEO files, and the app auth boundary.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the public PropertyQuarry deployment without mutating data.")
    parser.add_argument("--base-url", default="https://propertyquarry.com")
    parser.add_argument("--route", action="append", default=[], help="Route to smoke. Defaults to core public routes.")
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--write", default="", help="Optional JSON receipt output path.")
    args = parser.parse_args()
    receipt = build_live_public_smoke_receipt(
        base_url=args.base_url,
        routes=tuple(args.route or DEFAULT_ROUTES),
        timeout_seconds=args.timeout_seconds,
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        Path(args.write).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
