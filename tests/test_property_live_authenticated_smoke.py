from __future__ import annotations

import urllib.request

from scripts.propertyquarry_live_authenticated_smoke import build_live_authenticated_smoke_receipt


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=()",
}

SIGN_IN_BODY = (
    "PropertyQuarry Open search Continue with Google "
    "First-time provider sign-in still creates the account automatically. "
    "<button>Log out</button> Open current session"
)

SIGN_IN_ACTIVE_BODY = (
    "PropertyQuarry Open search Continue with Google "
    "First-time provider sign-in still creates the account automatically. "
    "<button>Log out</button>"
)

ACCOUNT_AGENT_BODY = (
    'PropertyQuarry <section class="pqx-account-logout-strip" aria-label="Current session">'
    "<button>Log out</button></section> <h2>Account</h2> <h2>Notifications</h2> <h2>Agent</h2>"
    '<form action="/app/api/property/account/notifications">'
    '<input type="checkbox" name="notification_channels" value="email">'
    '<input type="checkbox" name="notification_channels" value="telegram">'
    '<input type="checkbox" name="notification_channels" value="whatsapp">'
    '<input type="radio" name="preferred_channel" value="email">'
    '<input type="tel" name="whatsapp_ai_support_phone">'
    "<button>Save notification routing</button></form>"
)

ACCOUNT_FREE_BODY = ACCOUNT_AGENT_BODY.replace("<h2>Agent</h2>", "<h2>Free</h2>")


def _fake_response(
    body: str,
    *,
    status_code: int = 200,
    final_url: str = "",
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "status_code": status_code,
        "final_url": final_url or "https://propertyquarry.com/app/account",
        "headers": {"Content-Type": "text/html; charset=utf-8", **(headers or SECURITY_HEADERS)},
        "body": body.encode("utf-8"),
        "duration_ms": 14,
    }


def test_live_authenticated_smoke_passes_paid_customer_surfaces_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_authenticated_smoke_accepts_active_signed_in_copy_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_ACTIVE_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_authenticated_smoke_accepts_external_billing_redirect_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=lambda _host, _port: [(object(),)],
    )

    assert receipt["status"] == "pass"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff" and check["ok"] is True for check in billing_row["checks"])
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is True for check in billing_row["checks"])


def test_live_authenticated_smoke_rejects_unresolved_external_billing_redirect_without_network(monkeypatch) -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("missing dns")

    def public_dns_unavailable(_request, timeout=0):
        raise OSError("public dns unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", public_dns_unavailable)

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=unresolved,
    )

    assert receipt["status"] == "fail"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff" and check["ok"] is True for check in billing_row["checks"])
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is False for check in billing_row["checks"])


def test_live_authenticated_smoke_accepts_public_dns_for_stale_local_billing_resolver(monkeypatch) -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return (
                b'{"Status":0,"Answer":[{"name":"billing.propertyquarry.com.",'
                b'"type":5,"data":"members.brilliantdirectories.com."}]}'
            )

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: _DnsResponse())

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=unresolved,
        billing_handoff_dns_target="members.brilliantdirectories.com",
    )

    assert receipt["status"] == "pass"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is True for check in billing_row["checks"])


def test_live_authenticated_smoke_accepts_public_dns_without_expected_target(monkeypatch) -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return (
                b'{"Status":0,"Answer":[{"name":"billing.propertyquarry.com.",'
                b'"type":5,"data":"members.brilliantdirectories.com."}]}'
            )

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: _DnsResponse())

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=unresolved,
    )

    assert receipt["status"] == "pass"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is True for check in billing_row["checks"])


def test_live_authenticated_smoke_accepts_cloudflare_proxied_billing_host(monkeypatch) -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        url = str(getattr(request, "full_url", request))
        if "type=CNAME" in url:
            return _DnsResponse(
                b'{"Status":0,"Answer":[{"name":"billing.propertyquarry.com.",'
                b'"type":5,"data":"members.brilliantdirectories.com."}]}'
            )
        if "type=A" in url:
            return _DnsResponse(
                b'{"Status":0,"Answer":[{"name":"billing.propertyquarry.com.",'
                b'"type":1,"data":"188.114.96.3"}]}'
            )
        return _DnsResponse(b'{"Status":0,"Answer":[]}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=unresolved,
        billing_handoff_dns_target="propertyquarry.directoryup.com",
    )

    assert receipt["status"] == "pass"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is True for check in billing_row["checks"])


def test_live_authenticated_smoke_rejects_public_dns_target_mismatch(monkeypatch) -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(
                "",
                status_code=303,
                final_url=url,
                headers={**SECURITY_HEADERS, "Location": "https://billing.propertyquarry.com/account"},
            )
        return _fake_response(bodies[url], final_url=url)

    def unresolved(_host: str, _port: int) -> None:
        raise OSError("stale local dns")

    class _DnsResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"Status":0,"Answer":[{"name":"billing.propertyquarry.com.","type":5,"data":"wrong.example.com."}]}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: _DnsResponse())

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
        billing_handoff_resolver=unresolved,
        billing_handoff_dns_target="members.brilliantdirectories.com",
    )

    assert receipt["status"] == "fail"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_external_handoff_resolves" and check["ok"] is False for check in billing_row["checks"])


def test_live_authenticated_smoke_accepts_fail_closed_billing_recovery_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        if url.endswith("/app/billing"):
            return _fake_response(bodies[url], status_code=503, final_url=url)
        return _fake_response(bodies[url], final_url=url)

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=fetcher,
    )

    assert receipt["status"] == "pass"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_fail_closed_recovery" and check["ok"] is True for check in billing_row["checks"])


def test_live_authenticated_smoke_passes_free_customer_surfaces_when_free_is_expected() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_FREE_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="user-free@example.test",
        expected_plan_label="Free",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_live_authenticated_smoke_fails_when_account_loses_paid_plan_projection() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_FREE_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "fail"
    account_row = next(row for row in receipt["checks"] if row["path"] == "/app/account")
    assert any(check["name"] == "account_paid_plan" and check["ok"] is False for check in account_row["checks"])


def test_live_authenticated_smoke_fails_when_account_loses_logout_strip() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY.replace("pqx-account-logout-strip", "pqx-account-session"),
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "fail"
    account_row = next(row for row in receipt["checks"] if row["path"] == "/app/account")
    assert any(check["name"] == "account_logout_strip" and check["ok"] is False for check in account_row["checks"])


def test_live_authenticated_smoke_fails_when_account_duplicates_logout_actions() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY.replace("</section>", "</section><button>Log out</button>", 1),
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "fail"
    account_row = next(row for row in receipt["checks"] if row["path"] == "/app/account")
    assert any(check["name"] == "account_single_logout" and check["ok"] is False for check in account_row["checks"])


def test_live_authenticated_smoke_fails_when_sign_in_surface_duplicates_logout() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY.replace("<button>Log out</button>", "<button>Log out</button><button>Log out</button>"),
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "fail"
    sign_in_row = next(row for row in receipt["checks"] if row["path"] == "/sign-in")
    assert any(check["name"] == "sign_in_single_logout" and check["ok"] is False for check in sign_in_row["checks"])


def test_live_authenticated_smoke_fails_when_sign_in_loses_account_creation_copy() -> None:
    bodies = {
        "https://propertyquarry.com/sign-in": "PropertyQuarry Open search Continue with Google <button>Log out</button> Open current session Email sign-in links are temporarily unavailable.",
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        routes=("/sign-in",),
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    sign_in_row = next(row for row in receipt["checks"] if row["path"] == "/sign-in")
    assert receipt["status"] == "fail"
    assert any(check["name"] == "sign_in_provider_creates_account" and check["ok"] is False for check in sign_in_row["checks"])
    assert any(check["name"] == "sign_in_no_unavailable_auth_copy" and check["ok"] is False for check in sign_in_row["checks"])


def test_live_authenticated_smoke_retries_transient_transport_failures_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Billing handoff unavailable. Billing opens in the external account lane once the account handoff is connected. Your PropertyQuarry access remains active from the account page.",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }
    attempts: dict[str, int] = {}

    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        attempts[url] = attempts.get(url, 0) + 1
        if url.endswith("/app/account") and attempts[url] == 1:
            return {
                "status_code": 0,
                "final_url": url,
                "headers": {},
                "body": b"",
                "duration_ms": 8000,
                "error": "TimeoutError: timed out",
            }
        return _fake_response(bodies[url], final_url=url)

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        retry_count=2,
        retry_backoff_seconds=0,
        fetcher=fetcher,
    )

    assert receipt["status"] == "pass"
    account_row = next(row for row in receipt["checks"] if row["path"] == "/app/account")
    assert account_row["attempt_count"] == 2


def test_live_authenticated_smoke_rejects_local_billing_board_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": ACCOUNT_AGENT_BODY,
        "https://propertyquarry.com/app/billing": "PropertyQuarry Plan Agent Deep Multi All ranked Billing history Compare plans Open pricing",
        "https://propertyquarry.com/sign-in": SIGN_IN_BODY,
    }

    receipt = build_live_authenticated_smoke_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        expected_plan_label="Agent",
        fetcher=lambda url, _timeout: _fake_response(bodies[url], final_url=url),
    )

    assert receipt["status"] == "fail"
    billing_row = next(row for row in receipt["checks"] if row["path"] == "/app/billing")
    assert any(check["name"] == "billing_local_board_deleted" and check["ok"] is False for check in billing_row["checks"])
