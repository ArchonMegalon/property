from __future__ import annotations

from scripts.propertyquarry_live_authenticated_smoke import build_live_authenticated_smoke_receipt


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=()",
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
        "final_url": final_url or "https://propertyquarry.com/app/account",
        "headers": {"Content-Type": "text/html; charset=utf-8", **(headers or SECURITY_HEADERS)},
        "body": body.encode("utf-8"),
        "duration_ms": 14,
    }


def test_live_authenticated_smoke_passes_paid_customer_surfaces_without_network() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": "PropertyQuarry <h2>Account</h2> <h2>Notifications</h2> <h2>Agent</h2>",
        "https://propertyquarry.com/app/billing": "PropertyQuarry Open pricing",
        "https://propertyquarry.com/sign-in": "PropertyQuarry Open search Continue with Google <button>Log out</button> Open current session",
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
        "https://propertyquarry.com/app/account": "PropertyQuarry <h2>Account</h2> <h2>Notifications</h2> <h2>Agent</h2>",
        "https://propertyquarry.com/app/billing": "PropertyQuarry Compare plans",
        "https://propertyquarry.com/sign-in": "PropertyQuarry Open search Continue with Google <button>Log out</button>",
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


def test_live_authenticated_smoke_fails_when_account_loses_paid_plan_projection() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": "PropertyQuarry <h2>Account</h2> <h2>Notifications</h2> <h2>Free</h2>",
        "https://propertyquarry.com/app/billing": "PropertyQuarry Open pricing",
        "https://propertyquarry.com/sign-in": "PropertyQuarry Open search Continue with Google <button>Log out</button> Open current session",
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


def test_live_authenticated_smoke_fails_when_sign_in_surface_duplicates_logout() -> None:
    bodies = {
        "https://propertyquarry.com/app/account": "PropertyQuarry <h2>Account</h2> <h2>Notifications</h2> <h2>Agent</h2>",
        "https://propertyquarry.com/app/billing": "PropertyQuarry Open pricing",
        "https://propertyquarry.com/sign-in": "PropertyQuarry Open search Continue with Google <button>Log out</button><button>Log out</button> Open current session",
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
