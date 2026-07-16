from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest


_POSTGRES_BROWSER_E2E = os.environ.get("PROPERTYQUARRY_POSTGRES_BROWSER_E2E") == "1"

try:
    from playwright.sync_api import Page, expect, sync_playwright
except ImportError:
    if _POSTGRES_BROWSER_E2E:
        raise
    pytest.skip("PostgreSQL browser lane requires Playwright", allow_module_level=True)


pytestmark = pytest.mark.skipif(
    not _POSTGRES_BROWSER_E2E,
    reason="run through scripts/smoke_property_postgres.sh --browser-e2e",
)


def _required_environment(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    assert value, f"{name} is required for the PostgreSQL browser lane"
    return value


def _assert_ok(response: httpx.Response, *, operation: str) -> dict[str, object]:
    assert response.status_code == 200, f"{operation} failed: HTTP {response.status_code}: {response.text}"
    payload = response.json()
    assert isinstance(payload, dict), f"{operation} returned a non-object response"
    return payload


def test_propertyquarry_postgres_storage_public_boundary_and_internally_provisioned_workbench() -> None:
    base_url = _required_environment("PROPERTYQUARRY_POSTGRES_BROWSER_BASE_URL").rstrip("/")
    api_token = _required_environment("EA_API_TOKEN")
    expected_ready_reason = _required_environment("PROPERTYQUARRY_POSTGRES_BROWSER_EXPECTED_READY_REASON")
    session_path = Path(_required_environment("PROPERTYQUARRY_POSTGRES_BROWSER_SESSION_FILE"))
    assert stat.S_IMODE(session_path.stat().st_mode) == 0o600
    session_receipt = json.loads(session_path.read_text(encoding="utf-8"))
    assert session_receipt.get("contract_name") == "propertyquarry.postgres_browser_internal_session"
    assert session_receipt.get("status") == "pass"
    assert session_receipt.get("provisioning_scope") == "internal_ci_only"
    assert session_receipt.get("runtime_mode") == "prod"
    assert session_receipt.get("storage_backend") == "postgres"
    access_token = str(session_receipt.get("access_token") or "").strip()
    principal_id = str(session_receipt.get("principal_id") or "").strip()
    assert access_token and principal_id

    with httpx.Client(base_url=base_url, timeout=20.0, follow_redirects=False) as client:
        ready = _assert_ok(client.get("/health/ready"), operation="readiness probe")
        assert ready.get("reason") == expected_ready_reason, ready
        version = _assert_ok(client.get("/version"), operation="version probe")
        assert version.get("storage_backend") == "postgres", version

        registration = client.post(
            "/v1/register/start",
            json={"email": "postgres-public-registration@example.com", "return_to": "/app/search"},
        )
        assert registration.status_code == 503, registration.text
        assert registration.json()["error"]["code"] == "registration_email_delivery_unavailable"
        assert "verification_token" not in registration.text
        assert "verification_code" not in registration.text
        assert "magic_link_url" not in registration.text

        unauthenticated = client.get("/app/properties")
        assert unauthenticated.status_code in {303, 401}, unauthenticated.text

        token_impersonation = client.get(
            "/v1/onboarding/status",
            headers={
                "X-EA-API-Token": api_token,
                "X-EA-Principal-ID": "postgres-browser-lane",
            },
        )
        assert token_impersonation.status_code == 401, token_impersonation.text
        token_error = dict(token_impersonation.json().get("error") or {})
        assert token_error.get("code") == "principal_required", token_impersonation.text

        with httpx.Client(
            base_url=base_url,
            timeout=20.0,
            cookies={"ea_workspace_session": access_token},
        ) as session_client:
            stored = _assert_ok(
                session_client.post(
                    "/v1/onboarding/property-search/preferences",
                    json={
                        "country_code": "AT",
                        "language_code": "en",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "location_query": "Vienna",
                        "selected_platforms": ["willhaben"],
                        "max_results_per_source": 4,
                    },
                ),
                operation="store PostgreSQL-backed search preferences",
            )
            assert stored.get("principal_id") == principal_id, stored
            refreshed = _assert_ok(
                session_client.get("/v1/onboarding/property-search/preferences"),
                operation="read PostgreSQL-backed search preferences",
            )
            preferences = dict(refreshed.get("property_search_preferences") or {})
            assert preferences.get("country_code") == "AT", refreshed
            assert preferences.get("location_query") == "Vienna", refreshed

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-proxy-server",
            ],
        )
        try:
            public_context = browser.new_context(viewport={"width": 1440, "height": 900})
            public_page: Page = public_context.new_page()
            try:
                response = public_page.goto(f"{base_url}/", wait_until="domcontentloaded")
                assert response is not None and response.ok
                expect(public_page.locator("body")).to_contain_text("PropertyQuarry")
                response = public_page.goto(f"{base_url}/sign-in", wait_until="domcontentloaded")
                assert response is not None and response.ok
                expect(public_page.get_by_role("heading", name="Continue your property search.")).to_be_visible()
            finally:
                public_context.close()

            authenticated_context = browser.new_context(viewport={"width": 1440, "height": 900})
            authenticated_context.add_cookies(
                [{"name": "ea_workspace_session", "value": access_token, "url": base_url}]
            )
            authenticated_page: Page = authenticated_context.new_page()
            page_errors: list[str] = []
            authenticated_page.on("pageerror", lambda error: page_errors.append(str(error)))
            try:
                response = authenticated_page.goto(f"{base_url}/app/search", wait_until="domcontentloaded")
                assert response is not None and response.ok
                search_form = authenticated_page.locator('[data-console-form-variant="property_search"]')
                expect(search_form).to_be_visible()
                expect(search_form.locator('select[name="country_code"]').first).to_have_value("AT")
                expect(authenticated_page.locator("body")).to_contain_text("Vienna")
                search_form.locator('[data-property-step-trigger="providers"]').click()
                expect(search_form).to_have_attribute("data-property-active-step", "providers")

                response = authenticated_page.goto(f"{base_url}/app/properties", wait_until="domcontentloaded")
                assert response is not None and response.ok
                expect(authenticated_page.locator("[data-property-decision-workbench]")).to_be_visible()
                expect(
                    authenticated_page.get_by_role("navigation", name="PropertyQuarry sections")
                ).to_be_visible()
                assert page_errors == []
            finally:
                authenticated_context.close()
        finally:
            browser.close()
