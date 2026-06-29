from __future__ import annotations

import io
import urllib.error

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
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    {
                        "Location": login_url,
                        "Set-Cookie": "bd_member_session=ready; Path=/; Secure; HttpOnly",
                    },
                    io.BytesIO(b""),
                )
            if request.full_url == login_url:
                assert request.get_header("Cookie") == "bd_member_session=ready"
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
