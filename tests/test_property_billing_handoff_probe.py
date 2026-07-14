from __future__ import annotations

import io
import urllib.error
from email.message import Message

import pytest

from scripts import propertyquarry_billing_handoff_probe as probe


class _BodyResponse:
    def __init__(self, body: bytes, *, status: int = 200, url: str = "", headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.status = status
        self._url = url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size is not None and size >= 0:
            return self._body[:size]
        return self._body

    def geturl(self) -> str:
        return self._url


def test_billing_admin_login_surface_probe_detects_backend_form_without_recaptcha(monkeypatch) -> None:
    login_url = "https://propertyquarry.directoryup.com/admin/login"
    html = b"""
    <html><head><title>propertyquarry.com Admin Login</title></head>
    <body>
      <form action=\"//ww2.managemydirectory.com/admin/login.php\" method=\"post\">
        <input type=hidden NAME=website VALUE=\"62716\">
        <input type=hidden name=rftoken value=\"token\">
        <input type=text name=username>
        <input type=password name=password>
      </form>
      <a href=\"https://www.managemydirectory.com/admin/login.php?action=retrieve\">Forgot Password? Click to Reset</a>
    </body></html>
    """

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == login_url
            return _BodyResponse(html, status=200, url=login_url)

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.billing_admin_login_surface_probe(login_url)

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["form_action"] == "https://ww2.managemydirectory.com/admin/login.php"
    assert result["website_id"] == "62716"
    assert result["has_username_field"] is True
    assert result["has_password_field"] is True
    assert result["recaptcha_required"] is False
    assert result["recovery_href"] == "https://www.managemydirectory.com/admin/login.php?action=retrieve"


def test_billing_handoff_accepts_member_token_redirect_into_account_page(monkeypatch) -> None:
    token_url = "https://billing.propertyquarry.com/login/token/abc123/account"
    login_url = "https://billing.propertyquarry.com/login?login_direct_url=account%2Faccount"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            if request.full_url == token_url:
                headers = Message()
                headers.add_header("Location", login_url)
                headers.add_header("Set-Cookie", "token=ready; Path=/; Secure; HttpOnly")
                headers.add_header("Set-Cookie", "loggedin=1; Path=/; Secure; HttpOnly")
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    headers,
                    io.BytesIO(b""),
                )
            if request.full_url == login_url:
                cookie_header = request.get_header("Cookie")
                assert "token=ready" in cookie_header
                assert "loggedin=1" in cookie_header
                return _BodyResponse(
                    b"<html><body><a href=\"/account/home\">My Account</a><a href=\"/account/logout\">Log out</a></body></html>",
                    status=200,
                    url=login_url,
                )
            raise AssertionError(request.full_url)

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(token_url)

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["redirect_chain"] == [login_url]


def test_billing_handoff_rejects_cross_host_redirect_even_when_redirect_status_is_usable(monkeypatch) -> None:
    handoff_url = "https://billing.propertyquarry.com/account"
    rejected_url = "https://evil.example/account"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == handoff_url
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                {"Location": rejected_url},
                io.BytesIO(b""),
            )

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(handoff_url)

    assert result["ok"] is False
    assert result["error"] == "handoff_url_redirect_not_allowed"
    assert result["redirect_chain"] == [rejected_url]


def test_billing_handoff_rejects_redirect_status_without_location(monkeypatch) -> None:
    handoff_url = "https://billing.propertyquarry.com/account"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == handoff_url
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                {},
                io.BytesIO(b""),
            )

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(handoff_url)

    assert result["ok"] is False
    assert result["error"] == "handoff_url_http_302"


def test_billing_handoff_allows_explicit_cross_host_member_redirect_without_leaking_host_cookie(monkeypatch) -> None:
    handoff_url = "https://billing.propertyquarry.com/start"
    account_url = "https://accounts.propertyquarry.com/login?login_direct_url=account%2Faccount"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            if request.full_url == handoff_url:
                assert "caller_secret=initial-only" in str(request.get_header("Cookie") or "")
                headers = Message()
                headers.add_header("Location", account_url)
                headers.add_header("Set-Cookie", "origin_secret=do-not-leak; Path=/; Secure; HttpOnly")
                headers.add_header("Set-Cookie", "token=ready; Domain=propertyquarry.com; Path=/; Secure; HttpOnly")
                headers.add_header("Set-Cookie", "loggedin=1; Domain=propertyquarry.com; Path=/; Secure; HttpOnly")
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    headers,
                    io.BytesIO(b""),
                )
            if request.full_url == account_url:
                cookie_header = str(request.get_header("Cookie") or "")
                assert "token=ready" in cookie_header
                assert "loggedin=1" in cookie_header
                assert "origin_secret" not in cookie_header
                assert "caller_secret" not in cookie_header
                return _BodyResponse(
                    b'<html><body><a href="/account/home">My Account</a><a href="/account/logout">Log out</a></body></html>',
                    status=200,
                    url=account_url,
                )
            raise AssertionError(request.full_url)

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(
        handoff_url,
        allowed_hosts=("https://accounts.propertyquarry.com:443",),
        cookie_header="caller_secret=initial-only",
    )

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["redirect_chain"] == [account_url]


@pytest.mark.parametrize(
    "cookie_attributes",
    (
        "Domain=evil.example; Path=/; Secure",
        "Path=/never; Secure",
        "Path=/; Max-Age=0; Secure",
        "Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure",
    ),
)
def test_billing_handoff_does_not_accept_member_cookies_a_browser_would_not_send(
    monkeypatch,
    cookie_attributes: str,
) -> None:
    handoff_url = "https://billing.propertyquarry.com/start"
    login_url = "https://billing.propertyquarry.com/login?login_direct_url=account%2Faccount"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == handoff_url
            headers = Message()
            headers.add_header("Location", login_url)
            headers.add_header("Set-Cookie", f"token=ready; {cookie_attributes}")
            headers.add_header("Set-Cookie", f"loggedin=1; {cookie_attributes}")
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                headers,
                io.BytesIO(b""),
            )

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(handoff_url)

    assert result["ok"] is False
    assert result["error"] == "handoff_url_requires_separate_login"
    assert result["redirect_chain"] == [login_url]


def test_billing_handoff_ignores_malformed_set_cookie_without_crashing(monkeypatch) -> None:
    handoff_url = "https://billing.propertyquarry.com/start"
    login_url = "https://billing.propertyquarry.com/login?login_direct_url=account%2Faccount"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == handoff_url
            headers = Message()
            headers.add_header("Location", login_url)
            headers.add_header("Set-Cookie", 'token="unterminated; Path=/; Secure')
            headers.add_header("Set-Cookie", "loggedin=1; Path=/; Secure")
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                headers,
                io.BytesIO(b""),
            )

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.https_handoff_url_usable(handoff_url)

    assert result["ok"] is False
    assert result["error"] == "handoff_url_requires_separate_login"
    assert result["redirect_chain"] == [login_url]


def test_billing_admin_login_surface_probe_falls_back_to_backend_recovery_url(monkeypatch) -> None:
    login_url = "https://propertyquarry.directoryup.com/admin/login"
    html = b"""
    <html><head><title>propertyquarry.com Admin Login</title></head>
    <body>
      <form action=\"//ww2.managemydirectory.com/admin/login.php\" method=\"post\">
        <input type=hidden NAME=website VALUE=\"62716\">
        <input type=text name=username>
        <input type=password name=password>
      </form>
    </body></html>
    """

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            assert request.full_url == login_url
            return _BodyResponse(html, status=200, url=login_url)

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.billing_admin_login_surface_probe(login_url)

    assert result["ok"] is True
    assert result["recovery_href"] == "https://www.managemydirectory.com/admin/login.php?action=retrieve"


def test_billing_admin_login_attempt_reports_invalid_credentials_and_recovery_link(monkeypatch) -> None:
    login_url = "https://propertyquarry.directoryup.com/admin/login"
    form_action = "https://ww2.managemydirectory.com/admin/login.php"
    login_html = b"""
    <html><body>
      <form action=\"//ww2.managemydirectory.com/admin/login.php\" method=\"post\">
        <input type=hidden NAME=action VALUE=login>
        <input type=hidden NAME=website VALUE=\"62716\">
        <input type=hidden name=rftoken value=\"token\">
        <input type=text name=username>
        <input type=password name=password>
      </form>
      <a href=\"https://www.managemydirectory.com/admin/login.php?action=retrieve\">Forgot Password? Click to Reset</a>
    </body></html>
    """
    invalid_html = b"<html><head><title>Administration Login</title></head><body>Invalid</body></html>"

    class _Opener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            if request.full_url == login_url and request.get_method() == "GET":
                return _BodyResponse(login_html, status=200, url=login_url)
            if request.full_url == form_action and request.get_method() == "POST":
                return _BodyResponse(invalid_html, status=200, url=form_action + "?message=Invalid")
            raise AssertionError((request.full_url, request.get_method()))

    monkeypatch.setattr(probe, "no_proxy_opener", lambda *handlers: _Opener())

    result = probe.billing_admin_login_attempt(
        username="shared@example.com",
        password="wrong-pass",
        login_url=login_url,
    )

    assert result["attempted"] is True
    assert result["authenticated"] is False
    assert result["status_code"] == 200
    assert result["error"] == "billing_admin_invalid_credentials"
    assert result["final_url"] == form_action + "?message=Invalid"
    assert result["recovery_href"] == "https://www.managemydirectory.com/admin/login.php?action=retrieve"
