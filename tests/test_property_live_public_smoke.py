from __future__ import annotations

from scripts.propertyquarry_live_public_smoke import build_live_public_smoke_receipt


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
}


def _fake_response(
    body: str,
    *,
    status_code: int = 200,
    final_url: str = "",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "status_code": status_code,
        "final_url": final_url or "https://propertyquarry.com/",
        "headers": {"Content-Type": "text/html; charset=utf-8", **(headers or SECURITY_HEADERS)},
        "body": body.encode("utf-8"),
        "duration_ms": 12,
    }


def test_live_public_smoke_passes_core_public_routes_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/": "PropertyQuarry Search once. Rank the right homes. Decide with evidence.",
        "https://propertyquarry.com/security": "PropertyQuarry Security, privacy, and visual quality are reviewed before public changes go live.",
        "https://propertyquarry.com/pricing": "PropertyQuarry Pricing Start free Request access.",
        "https://propertyquarry.com/privacy": "PropertyQuarry Privacy Public tours should use a narrow public manifest",
        "https://propertyquarry.com/terms": "PropertyQuarry Terms Generated or embedded tours help screening",
        "https://propertyquarry.com/support": "PropertyQuarry Support wrong-area matches",
        "https://propertyquarry.com/imprint": "PropertyQuarry Imprint How to reach PropertyQuarry",
        "https://propertyquarry.com/cookies": "PropertyQuarry Cookies and Analytics essential cookies",
        "https://propertyquarry.com/subprocessors": "PropertyQuarry Subprocessors Vendor control plane",
        "https://propertyquarry.com/refunds": "PropertyQuarry Refunds and Cancellation failed payment recovery",
        "https://propertyquarry.com/disclaimers": "PropertyQuarry Disclaimers Generated visualization",
        "https://propertyquarry.com/register": "PropertyQuarry Create account",
        "https://propertyquarry.com/sign-in": "PropertyQuarry Use your current session, secure email link, or connected identity. Identity-only.",
        "https://propertyquarry.com/manifest.webmanifest": (
            '{"name":"PropertyQuarry","start_url":"/app/search","display":"standalone","scope":"/",'
            '"icons":[{"src":"/pwa-icon.svg","purpose":"any maskable"}]}'
        ),
        "https://propertyquarry.com/service-worker.js": "self.skipWaiting(); self.clients.claim();",
        "https://propertyquarry.com/robots.txt": "Sitemap: https://propertyquarry.com/sitemap.xml",
        "https://propertyquarry.com/sitemap.xml": "<loc>https://propertyquarry.com/</loc><loc>https://propertyquarry.com/pricing</loc>",
        "https://propertyquarry.com/app/properties": "PropertyQuarry Use your current session, secure email link, or connected identity. Identity-only.",
    }

    receipt = build_live_public_smoke_receipt(
        fetcher=lambda url, _timeout: _fake_response(
            bodies[url],
            final_url="https://propertyquarry.com/sign-in?return_to=%2Fapp%2Fproperties"
            if url.endswith("/app/properties")
            else url,
        )
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_public_smoke_fails_cloudflare_502_and_legacy_origin_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/pricing"):
            return _fake_response("Executive Assistant Morning Memo", status_code=200, final_url=url)
        return _fake_response("<html>Cloudflare 502</html>", status_code=502, final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/", "/pricing"), fetcher=fetcher)

    assert receipt["status"] == "fail"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert rows["/"]["status_code"] == 502
    assert rows["/"]["ok"] is False
    assert rows["/pricing"]["ok"] is False
    assert any(check["name"] == "no_generic_ea_copy" and check["ok"] is False for check in rows["/pricing"]["checks"])


def test_live_public_smoke_fails_missing_browser_security_headers_without_network() -> None:
    receipt = build_live_public_smoke_receipt(
        routes=("/",),
        fetcher=lambda url, _timeout: _fake_response(
            "PropertyQuarry Search once. Rank the right homes. Decide with evidence.",
            final_url=url,
            headers={"Content-Type": "text/html; charset=utf-8"},
        ),
    )

    assert receipt["status"] == "fail"
    row = receipt["checks"][0]
    assert any(check["name"] == "security_csp" and check["ok"] is False for check in row["checks"])
    assert any(check["name"] == "security_nosniff" and check["ok"] is False for check in row["checks"])


def test_live_public_smoke_fails_legacy_home_proof_component_without_network() -> None:
    receipt = build_live_public_smoke_receipt(
        routes=("/",),
        fetcher=lambda url, _timeout: _fake_response(
            '<html><body><main>PropertyQuarry Search once. Rank the right homes. Decide with evidence.</main><div class="pq-proof"></div></body></html>',
            final_url=url,
        ),
    )

    assert receipt["status"] == "fail"
    row = receipt["checks"][0]
    assert row["path"] == "/"
    assert any(check["name"] == "home_no_legacy_proof_component" and check["ok"] is False for check in row["checks"])


def test_live_public_smoke_fails_weak_pwa_manifest_without_network() -> None:
    receipt = build_live_public_smoke_receipt(
        routes=("/manifest.webmanifest",),
        fetcher=lambda url, _timeout: _fake_response(
            '{"name":"PropertyQuarry","start_url":"/app/search"}',
            final_url=url,
        ),
    )

    assert receipt["status"] == "fail"
    row = receipt["checks"][0]
    assert any(check["name"] == "manifest_display_scope" and check["ok"] is False for check in row["checks"])
    assert any(check["name"] == "manifest_maskable_icon" and check["ok"] is False for check in row["checks"])


def test_live_public_smoke_accepts_localhost_sitemap_origin_without_network() -> None:
    receipt = build_live_public_smoke_receipt(
        base_url="http://localhost:18101",
        routes=("/sitemap.xml",),
        fetcher=lambda url, _timeout: _fake_response(
            "<loc>http://localhost:18101/</loc><loc>http://localhost:18101/pricing</loc>",
            final_url=url,
        ),
    )

    assert receipt["status"] == "pass"
    assert receipt["checks"][0]["path"] == "/sitemap.xml"
