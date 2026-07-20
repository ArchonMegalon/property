from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.public_analytics_consent import (
    ANALYTICS_CONSENT_COOKIE,
    ANALYTICS_CONSENT_CSRF_COOKIE,
    ANALYTICS_CONSENT_DENIED,
    ANALYTICS_CONSENT_GRANTED,
    analytics_consent_state,
    browser_privacy_signal_enabled,
    consent_request_is_same_origin,
)


_HOST = "propertyquarry.com"
_ORIGIN = f"http://{_HOST}"
_CLICKRANK_SITE_ID = "propertyquarry-public-site"


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.setenv("EA_ENABLE_CLICKRANK", "1")
    monkeypatch.setenv("CLICKRANK_AI_PROPERTYQUARRY_SITE_ID", _CLICKRANK_SITE_ID)
    monkeypatch.delenv("EA_ENABLE_RYBBIT", raising=False)
    monkeypatch.delenv("EA_PUBLIC_RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("RYBBIT_ENABLED", raising=False)
    from app.api.app import create_app

    return TestClient(create_app())


def _csrf_token(client: TestClient) -> str:
    return str(client.cookies.get(ANALYTICS_CONSENT_CSRF_COOKIE) or "")


def _submit_consent(
    client: TestClient,
    *,
    decision: str,
    return_to: str = "/",
    extra_headers: dict[str, str] | None = None,
):
    headers = {"host": _HOST, "origin": _ORIGIN}
    headers.update(extra_headers or {})
    return client.post(
        "/privacy/analytics-consent",
        data={
            "csrf_token": _csrf_token(client),
            "decision": decision,
            "return_to": return_to,
        },
        headers=headers,
        follow_redirects=False,
    )


def test_public_analytics_is_off_before_consent_and_choice_is_accessible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.get("/", headers={"host": _HOST})

    assert response.status_code == 200
    assert "Your privacy choice" in response.text
    assert "Reject optional analytics" in response.text
    assert "Allow analytics" in response.text
    assert "aria-labelledby=\"analytics-consent-title\"" in response.text
    assert "clickrank.ai" not in response.text
    assert _csrf_token(client)
    csrf_set_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{ANALYTICS_CONSENT_CSRF_COOKIE}=")
    )
    assert "HttpOnly" in csrf_set_cookie
    assert "SameSite=strict" in csrf_set_cookie
    assert response.headers["cache-control"] == "private, no-store"
    assert {token.strip() for token in response.headers["vary"].split(",")} >= {
        "Cookie",
        "DNT",
        "Sec-GPC",
    }


def test_grant_enables_configured_analytics_and_denial_withdraws_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    client.get("/", headers={"host": _HOST})

    granted = _submit_consent(client, decision="granted")

    assert granted.status_code == 303
    assert granted.headers["location"] == "/"
    assert client.cookies.get(ANALYTICS_CONSENT_COOKIE) == ANALYTICS_CONSENT_GRANTED
    enabled_page = client.get("/", headers={"host": _HOST})
    assert f"https://js.clickrank.ai/seo/{_CLICKRANK_SITE_ID}/script?" in enabled_page.text
    assert "Your privacy choice" not in enabled_page.text

    settings_page = client.get("/cookies", headers={"host": _HOST})
    assert settings_page.status_code == 200
    assert "Optional analytics are currently allowed" in settings_page.text
    denied = _submit_consent(
        client,
        decision="denied",
        return_to="/cookies#analytics-preferences",
    )

    assert denied.status_code == 303
    assert denied.headers["location"] == "/cookies#analytics-preferences"
    assert client.cookies.get(ANALYTICS_CONSENT_COOKIE) == ANALYTICS_CONSENT_DENIED
    disabled_page = client.get("/", headers={"host": _HOST})
    assert "clickrank.ai" not in disabled_page.text


@pytest.mark.parametrize("privacy_header", [{"sec-gpc": "1"}, {"dnt": "1"}])
def test_browser_privacy_signals_override_a_stored_grant(
    monkeypatch: pytest.MonkeyPatch,
    privacy_header: dict[str, str],
) -> None:
    client = _client(monkeypatch)
    client.get("/", headers={"host": _HOST})
    assert _submit_consent(client, decision="granted").status_code == 303

    response = client.get("/", headers={"host": _HOST, **privacy_header})

    assert response.status_code == 200
    assert "clickrank.ai" not in response.text
    assert "Your privacy choice" not in response.text


def test_gpc_prevents_a_crafted_grant_from_becoming_active_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    settings = client.get("/cookies", headers={"host": _HOST, "sec-gpc": "1"})

    assert settings.status_code == 200
    assert "Global Privacy Control or Do Not Track signal is on" in settings.text
    assert 'name="decision" value="granted"' not in settings.text
    response = _submit_consent(
        client,
        decision="granted",
        return_to="/cookies#analytics-preferences",
        extra_headers={"sec-gpc": "1"},
    )

    assert response.status_code == 303
    assert client.cookies.get(ANALYTICS_CONSENT_COOKIE) == ANALYTICS_CONSENT_DENIED
    after_signal_is_removed = client.get("/", headers={"host": _HOST})
    assert "clickrank.ai" not in after_signal_is_removed.text


def test_consent_post_rejects_cross_origin_and_open_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    client.get("/", headers={"host": _HOST})

    cross_origin = client.post(
        "/privacy/analytics-consent",
        data={
            "csrf_token": _csrf_token(client),
            "decision": "granted",
            "return_to": "/",
        },
        headers={"host": _HOST, "origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert cross_origin.status_code == 403

    sanitized = _submit_consent(client, decision="denied", return_to="//attacker.example/path")
    assert sanitized.status_code == 303
    assert sanitized.headers["location"] == "/cookies"


def test_consent_service_recognizes_gpc_dnt_and_malformed_origins() -> None:
    granted_cookie = {ANALYTICS_CONSENT_COOKIE: ANALYTICS_CONSENT_GRANTED}
    gpc_request = SimpleNamespace(headers={"sec-gpc": "1"}, cookies=granted_cookie)
    dnt_request = SimpleNamespace(headers={"dnt": "yes"}, cookies=granted_cookie)

    assert browser_privacy_signal_enabled(gpc_request) is True
    assert browser_privacy_signal_enabled(dnt_request) is True
    assert analytics_consent_state(gpc_request) == "denied_by_browser_signal"
    malformed_origin_request = SimpleNamespace(
        headers={"host": "propertyquarry.com", "origin": "https://propertyquarry.com:bad"},
        url=SimpleNamespace(scheme="https"),
    )
    assert consent_request_is_same_origin(malformed_origin_request) is False
