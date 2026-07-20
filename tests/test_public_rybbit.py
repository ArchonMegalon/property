from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.services.public_analytics_consent import (
    ANALYTICS_CONSENT_COOKIE,
    ANALYTICS_CONSENT_CSRF_COOKIE,
    ANALYTICS_CONSENT_GRANTED,
)
from app.services.public_rybbit import rybbit_head_snippet


class _FakeUrl:
    def __init__(self, path: str) -> None:
        self.path = path
        self.hostname = "propertyquarry.com"


class _FakeRequest:
    def __init__(self, path: str, host: str = "propertyquarry.com", *, consent: bool = True) -> None:
        self.headers = {"host": host}
        self.cookies = {ANALYTICS_CONSENT_COOKIE: ANALYTICS_CONSENT_GRANTED} if consent else {}
        self.scope = {"path": path}
        self.url = _FakeUrl(path)


def test_propertyquarry_rybbit_snippet_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("EA_ENABLE_RYBBIT", raising=False)
    monkeypatch.delenv("EA_PUBLIC_RYBBIT_ENABLED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_SITE_ID", raising=False)
    monkeypatch.delenv("RYBBIT_SITE_ID", raising=False)

    assert rybbit_head_snippet(_FakeRequest("/")) == ""


def test_propertyquarry_rybbit_snippet_masks_private_property_paths(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_BASE_URL", "https://analytics.propertyquarry.com")

    snippet = rybbit_head_snippet(_FakeRequest("/"))

    assert 'src="https://analytics.propertyquarry.com/api/script.js"' in snippet
    assert 'data-site-id="propertyquarry-site"' in snippet
    assert "/workspace-access/**" in snippet
    assert "/app/api/**" in snippet
    assert "/tours/**" in snippet
    assert "/app/properties/**" in snippet


def test_propertyquarry_rybbit_skips_authenticated_routes_by_default(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_AUTHENTICATED_ENABLED", raising=False)

    assert rybbit_head_snippet(_FakeRequest("/app/properties")) == ""
    assert rybbit_head_snippet(_FakeRequest("/app/research/private-result")) == ""
    assert rybbit_head_snippet(_FakeRequest("/tours/private-tour/control")) == ""


def test_propertyquarry_rybbit_requires_explicit_analytics_consent(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")

    assert rybbit_head_snippet(_FakeRequest("/", consent=False)) == ""


def test_propertyquarry_rybbit_authenticated_scope_is_explicit_and_anonymous(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_AUTHENTICATED_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")

    snippet = rybbit_head_snippet(_FakeRequest("/app/properties"))

    assert 'data-site-id="propertyquarry-site"' in snippet
    assert "identify" not in snippet
    assert "principal" not in snippet
    assert "email" not in snippet


def test_propertyquarry_rybbit_uses_live_dashboard_id_without_private_app_identifiers(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_AUTHENTICATED_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "10315")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_TAG", "propertyquarry")
    monkeypatch.setenv(
        "PROPERTYQUARRY_RYBBIT_SKIP_PATTERNS",
        "/workspace-access/**,/app/api/**,/v1/**,/api/**,/auth/**,/admin/**,/tours/files/**",
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_RYBBIT_MASK_PATTERNS",
        "/app/**,/workspace-access/**,/app/handoffs/**,/tours/**,/app/properties/**,/app/research/**",
    )

    public_snippet = rybbit_head_snippet(_FakeRequest("/"))
    app_snippet = rybbit_head_snippet(_FakeRequest("/app/search"))

    for snippet in (public_snippet, app_snippet):
        assert 'src="https://app.rybbit.io/api/script.js"' in snippet
        assert 'data-site-id="10315"' in snippet
        assert 'data-tag="propertyquarry"' in snippet
        assert "/app/**" in snippet
        assert "/app/research/**" in snippet
        assert "/tours/files/**" in snippet
        assert "identify" not in snippet
        assert "principal" not in snippet
        assert "email" not in snippet
        assert "run_id" not in snippet
        assert "listing" not in snippet


def test_propertyquarry_rybbit_snippet_rejects_invalid_base_url(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "propertyquarry-site")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_BASE_URL", "javascript:alert(1)")

    assert rybbit_head_snippet(_FakeRequest("/")) == ""


def test_propertyquarry_rybbit_snippet_accepts_legacy_host_site_id(monkeypatch) -> None:
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_IO_PROPERTYQUARRY_SITE_ID", "legacy-property-site")
    monkeypatch.delenv("PROPERTYQUARRY_RYBBIT_SITE_ID", raising=False)
    monkeypatch.delenv("RYBBIT_SITE_ID", raising=False)
    request = type(
        "Request",
        (),
        {
            "headers": {"host": "propertyquarry.com"},
            "cookies": {ANALYTICS_CONSENT_COOKIE: ANALYTICS_CONSENT_GRANTED},
        },
    )()

    snippet = rybbit_head_snippet(request)

    assert 'src="https://app.rybbit.io/api/script.js"' in snippet
    assert 'data-site-id="legacy-property-site"' in snippet


def test_propertyquarry_page_renders_one_rybbit_script_with_legacy_and_canonical_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_IO_PROPERTYQUARRY_SITE_ID", "legacy-property-site")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_RYBBIT_SITE_ID", "canonical-property-site")
    monkeypatch.delenv("EA_PUBLIC_RYBBIT_RENDER_IN_CLICKRANK", raising=False)
    from app.api.app import create_app

    client = TestClient(create_app())
    initial = client.get("/", headers={"host": "propertyquarry.com"})
    csrf_token = str(client.cookies.get(ANALYTICS_CONSENT_CSRF_COOKIE) or "")
    assert initial.status_code == 200
    assert csrf_token
    consent_response = client.post(
        "/privacy/analytics-consent",
        data={"csrf_token": csrf_token, "decision": "granted", "return_to": "/"},
        headers={"host": "propertyquarry.com", "origin": "http://propertyquarry.com"},
        follow_redirects=False,
    )
    assert consent_response.status_code == 303

    response = client.get("/", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert response.text.count("https://app.rybbit.io/api/script.js") == 1
    assert 'data-site-id="canonical-property-site"' in response.text
    assert 'data-site-id="legacy-property-site"' not in response.text

    app_response = client.get(
        "/app/properties",
        headers={"host": "propertyquarry.com", "X-EA-Principal-ID": "rybbit-browser-test"},
    )
    assert app_response.status_code == 200
    assert "https://app.rybbit.io/api/script.js" not in app_response.text
