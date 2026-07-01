from __future__ import annotations

from scripts.propertyquarry_live_public_smoke import build_live_public_smoke_receipt


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
}

SIGN_IN_COPY = (
    "PropertyQuarry Use a saved session, email link, or connected identity. "
    "First-time provider sign-in also creates the account automatically. "
)


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
        "https://propertyquarry.com/": "PropertyQuarry Search once. Rank the right homes. Decide faster.",
        "https://propertyquarry.com/security": (
            'PropertyQuarry Strict rules. Smart ranking. Score guide '
            'href="/how-it-works/score" Hard filters decide eligibility. '
            "You choose what is shared Account data stays editable"
        ),
        "https://propertyquarry.com/pricing": "PropertyQuarry Pricing Start free First sign-in creates the account automatically. Open account, then activate from billing.",
        "https://propertyquarry.com/privacy": "PropertyQuarry Privacy Public tours should use a narrow public manifest",
        "https://propertyquarry.com/terms": "PropertyQuarry Terms Generated or embedded tours help screening",
        "https://propertyquarry.com/support": "PropertyQuarry Support wrong-area matches",
        "https://propertyquarry.com/imprint": "PropertyQuarry Imprint How to reach PropertyQuarry",
        "https://propertyquarry.com/cookies": "PropertyQuarry Cookies and Analytics essential cookies",
        "https://propertyquarry.com/subprocessors": "PropertyQuarry Subprocessors Service partner registry",
        "https://propertyquarry.com/refunds": "PropertyQuarry Refunds and Cancellation failed payment recovery",
        "https://propertyquarry.com/disclaimers": "PropertyQuarry Disclaimers Generated visualization",
        "https://propertyquarry.com/register": "PropertyQuarry Set up your PropertyQuarry account Finish setup",
        "https://propertyquarry.com/sign-in": (
            'PropertyQuarry Use a saved session, email link, or connected identity. '
            "First-time provider sign-in also creates the account automatically. "
            "Any provider below reopens the same account or creates it automatically on first use. "
            '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>'
        ),
        "https://propertyquarry.com/manifest.webmanifest": (
            '{"name":"PropertyQuarry","lang":"en","dir":"ltr","id":"/app/search","start_url":"/app/search",'
            '"display":"standalone","display_override":["standalone","minimal-ui","browser"],"scope":"/",'
            '"launch_handler":{"client_mode":"navigate-existing"},"prefer_related_applications":false,'
            '"icons":[{"src":"/pwa-icon.svg","purpose":"any maskable"},'
            '{"src":"/pwa-icon-192.png","sizes":"192x192","type":"image/png","purpose":"any maskable"},'
            '{"src":"/pwa-icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}],'
            '"shortcuts":[{"url":"/app/search"},{"url":"/app/properties"},{"url":"/app/shortlist"},{"url":"/app/agents"}]}'
        ),
        "https://propertyquarry.com/service-worker.js": "self.skipWaiting(); self.clients.claim();",
        "https://propertyquarry.com/robots.txt": "Sitemap: https://propertyquarry.com/sitemap.xml",
        "https://propertyquarry.com/sitemap.xml": "<loc>https://propertyquarry.com/</loc><loc>https://propertyquarry.com/pricing</loc>",
        "https://propertyquarry.com/app/properties": "PropertyQuarry Use a saved session, email link, or connected identity.",
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://accounts.google.com/o/oauth2/v2/auth?"
                        "scope=openid+email+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fgoogle%2Fcallback&state=s"
                    )
                },
            )
        return _fake_response(
            bodies[url],
            final_url="https://propertyquarry.com/sign-in?return_to=%2Fapp%2Fproperties"
            if url.endswith("/app/properties")
            else url,
        )

    receipt = build_live_public_smoke_receipt(fetcher=fetcher)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_public_smoke_checks_billing_worker_redirects_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url == "https://billing.propertyquarry.com/":
            return _fake_response(
                "",
                status_code=302,
                final_url=url,
                headers={
                    "Location": "https://propertyquarry.com/",
                    "X-PQ-Billing-Worker": "propertyquarry-billing-handoff",
                    "X-PQ-Billing-Worker-Branch": "hero-redirect",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
        if url == "https://billing.propertyquarry.com/account/upgrade":
            return _fake_response(
                "",
                status_code=302,
                final_url=url,
                headers={
                    "Location": "https://propertyquarry.com/pricing",
                    "X-PQ-Billing-Worker": "propertyquarry-billing-handoff",
                    "X-PQ-Billing-Worker-Branch": "pricing-redirect",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
        return _fake_response(
            "PropertyQuarry Search once. Rank the right homes. Decide faster.",
            final_url=url,
        )

    receipt = build_live_public_smoke_receipt(
        routes=(),
        billing_base_url="https://billing.propertyquarry.com",
        fetcher=fetcher,
    )

    assert receipt["status"] == "pass"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert rows["billing:/"]["ok"] is True
    assert rows["billing:/account/upgrade"]["ok"] is True
    assert any(check["name"] == "billing_worker_branch" and check["ok"] is True for check in rows["billing:/"]["checks"])


def test_live_public_smoke_rejects_billing_worker_fake_landing_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.startswith("https://billing.propertyquarry.com"):
            return _fake_response("Open houses Find an agent", status_code=200, final_url=url)
        return _fake_response(
            "PropertyQuarry Search once. Rank the right homes. Decide faster.",
            final_url=url,
        )

    receipt = build_live_public_smoke_receipt(
        routes=(),
        billing_base_url="https://billing.propertyquarry.com",
        fetcher=fetcher,
    )

    assert receipt["status"] == "fail"
    row = next(row for row in receipt["checks"] if row["path"] == "billing:/")
    assert any(check["name"] == "billing_worker_redirect_status" and check["ok"] is False for check in row["checks"])


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
            "PropertyQuarry Search once. Rank the right homes. Decide faster.",
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
            '<html><body><main>PropertyQuarry Search once. Rank the right homes. Decide faster.</main><div class="pq-proof"></div></body></html>',
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
    assert any(check["name"] == "manifest_png_install_icons" and check["ok"] is False for check in row["checks"])
    assert any(check["name"] == "manifest_core_shortcuts" and check["ok"] is False for check in row["checks"])


def test_live_public_smoke_fails_broken_google_sign_in_redirect_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in"):
            return _fake_response(
                SIGN_IN_COPY
                + '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>',
                final_url=url,
            )
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={"Location": "https://evil.example.test/oauth?scope=openid+email+profile&state=s"},
            )
        return _fake_response("PropertyQuarry", final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)

    assert receipt["status"] == "fail"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert any(check["name"] == "google_redirect_host" and check["ok"] is False for check in rows["/sign-in/google"]["checks"])


def test_live_public_smoke_fails_sign_in_without_account_creation_copy() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        return _fake_response(
            'PropertyQuarry Use a saved session, email link, or connected identity. '
            'Email sign-in links are temporarily unavailable. '
            '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>',
            final_url=url,
        )

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)
    row = next(row for row in receipt["checks"] if row["path"] == "/sign-in")

    assert receipt["status"] == "fail"
    assert any(check["name"] == "sign_in_provider_creates_account" and check["ok"] is False for check in row["checks"])
    assert any(check["name"] == "sign_in_no_unavailable_auth_copy" and check["ok"] is False for check in row["checks"])


def test_live_public_smoke_accepts_when_facebook_lane_is_hidden_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in"):
            return _fake_response(
                SIGN_IN_COPY
                + '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>',
                final_url=url,
            )
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://accounts.google.com/o/oauth2/v2/auth?"
                        "scope=openid+email+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fgoogle%2Fcallback&state=s"
                    )
                },
            )
        return _fake_response("PropertyQuarry", final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)

    assert receipt["status"] == "pass"


def test_live_public_smoke_fails_facebook_email_scope_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in"):
            return _fake_response(
                SIGN_IN_COPY
                + '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>'
                '<a href="/sign-in/facebook" data-submitting-label="Opening Facebook...">Continue with Facebook</a>',
                final_url=url,
            )
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://accounts.google.com/o/oauth2/v2/auth?"
                        "scope=openid+email+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fgoogle%2Fcallback&state=s"
                    )
                },
            )
        if url.endswith("/sign-in/facebook"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://www.facebook.com/v21.0/dialog/oauth?"
                        "scope=public_profile,email&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Ffacebook%2Fcallback&state=s"
                    )
                },
            )
        return _fake_response("PropertyQuarry", final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)

    assert receipt["status"] == "fail"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert any(check["name"] == "facebook_no_email_scope" and check["ok"] is False for check in rows["/sign-in/facebook"]["checks"])


def test_live_public_smoke_accepts_id_austria_identity_redirect_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in"):
            return _fake_response(
                SIGN_IN_COPY
                + '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>'
                '<button disabled>Facebook unavailable</button>'
                '<a href="/sign-in/id-austria" data-submitting-label="Opening ID Austria...">Continue with ID Austria</a>',
                final_url=url,
            )
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://accounts.google.com/o/oauth2/v2/auth?"
                        "scope=openid+email+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fgoogle%2Fcallback&state=s"
                    )
                },
            )
        if url.endswith("/sign-in/id-austria"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://idp.id-austria.gv.at/auth/idp/profile/oidc/authorize?"
                        "scope=openid+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fid-austria%2Fcallback&state=s"
                    )
                },
            )
        return _fake_response("PropertyQuarry", final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)

    assert receipt["status"] == "pass"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert any(check["name"] == "id_austria_redirect_host" and check["ok"] is True for check in rows["/sign-in/id-austria"]["checks"])
    assert any(check["name"] == "id_austria_identity_scope" and check["ok"] is True for check in rows["/sign-in/id-austria"]["checks"])


def test_live_public_smoke_fails_broken_id_austria_redirect_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/sign-in"):
            return _fake_response(
                SIGN_IN_COPY
                + '<a href="/sign-in/google" data-submitting-label="Opening Google...">Continue with Google</a>'
                '<a href="/sign-in/id-austria" data-submitting-label="Opening ID Austria...">Continue with ID Austria</a>',
                final_url=url,
            )
        if url.endswith("/sign-in/google"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://accounts.google.com/o/oauth2/v2/auth?"
                        "scope=openid+email+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fgoogle%2Fcallback&state=s"
                    )
                },
            )
        if url.endswith("/sign-in/id-austria"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={
                    "Location": (
                        "https://evil.example.test/auth?"
                        "scope=openid+profile&redirect_uri=https%3A%2F%2Fpropertyquarry.com%2Fid-austria%2Fcallback&state=s"
                    )
                },
            )
        return _fake_response("PropertyQuarry", final_url=url)

    receipt = build_live_public_smoke_receipt(routes=("/sign-in",), fetcher=fetcher)

    assert receipt["status"] == "fail"
    rows = {row["path"]: row for row in receipt["checks"]}
    assert any(check["name"] == "id_austria_redirect_host" and check["ok"] is False for check in rows["/sign-in/id-austria"]["checks"])


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
