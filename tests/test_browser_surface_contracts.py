from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


PUBLIC_ROUTES = (
    "/",
    "/product",
    "/security",
    "/data-deletion",
    "/pricing",
    "/docs",
    "/integrations",
    "/guides/wohnung-kaufen-wien-checkliste",
    "/markets/vienna",
    "/register",
    "/sign-in",
)

APP_ROUTES = (
    "/app/properties",
    "/app/settings",
)

LEGACY_APP_ROUTE_REDIRECTS = {
    "/app/briefing": "/app/queue",
    "/app/inbox": "/app/queue",
    "/app/follow-ups": "/app/commitments",
    "/app/memory": "/app/people",
    "/app/contacts": "/app/evidence",
    "/app/channels": "/app/account#delivery",
    "/app/automation": "/app/agents",
    "/app/automations": "/app/agents",
}

PROPERTY_SETTINGS_ALIAS_REDIRECTS = {
    "/app/usage": "/app/settings/usage",
    "/app/support": "/app/settings/support",
    "/app/trust": "/app/settings/trust",
    "/app/google": "/app/settings/google",
    "/app/access": "/app/settings/access",
    "/app/invitations": "/app/settings/invitations",
    "/app/outcomes": "/app/settings/outcomes",
    "/app/plan": "/app/settings/plan",
}

PROPERTY_LEGACY_APP_SURFACE_REDIRECTS = {
    "/app/today": "/app/properties",
    "/app/queue": "/app/shortlist",
    "/app/commitments": "/app/account",
    "/app/people": "/app/account",
    "/app/evidence": "/app/account",
    "/app/activity": "/app/account",
    "/app/channel-loop": "/app/account",
}


def _client(*, principal_id: str = "exec-browser-contract") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _assert_no_drift(text: str) -> None:
    lower = text.lower()
    assert "chummer" not in lower
    assert "gm_creator_ops" not in lower
    assert "principal id" not in lower
    assert "operator access ·" not in lower


def _internal_links(html: str) -> list[str]:
    refs = sorted(set(re.findall(r'href="([^"]+)"', html)))
    return [ref for ref in refs if ref.startswith("/") and not ref.startswith("//")]


def _visible_text(html: str) -> str:
    without_script = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", without_script)).strip().lower()


def _assert_internal_links_resolve(client: TestClient, *, source_path: str, html: str) -> None:
    for href in _internal_links(html):
        if href.startswith("/app/actions/") or href.startswith("/sign-out"):
            continue
        request_href = href.split("#", 1)[0] or "/"
        linked = client.get(request_href, headers={"host": "propertyquarry.com", "accept": "text/html"}, follow_redirects=False)
        assert linked.status_code in {200, 303, 307}, f"{source_path} links to {href} -> {linked.status_code}"


def test_public_surface_routes_render_and_keep_product_language() -> None:
    client = _client()
    for path in PUBLIC_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_no_drift(response.text)

    landing = client.get("/")
    assert "Search once. Rank the right homes. Decide with evidence." in landing.text
    assert "research the shortlist" in landing.text
    assert "Open search" in landing.text
    assert "Built for focused private search first" in landing.text
    assert "Upgrade only when it helps" in landing.text

    pricing = client.get("/pricing")
    assert "Pick the search lane you need." in pricing.text
    assert "Upgrade when the current lane is the bottleneck." in pricing.text
    assert "Typical office path" not in pricing.text

    security = client.get("/security")
    assert "Automatic digests" in security.text
    assert "Morning memo schedule" not in security.text

    deletion = client.get("/data-deletion")
    assert "Request deletion of your PropertyQuarry data." in deletion.text
    assert "property@propertyquarry.com" in deletion.text
    assert "Data deletion request" in deletion.text

    sign_in = client.get("/sign-in")
    assert "Return with the same browser, a secure email link, or your connected identity." in sign_in.text
    assert "Choose the narrowest sign-in path" not in sign_in.text

    for href in _internal_links(landing.text):
        assert not href.startswith("/tours")
        assert not href.startswith("/results")
        resolved = client.get(href, follow_redirects=False)
        assert resolved.status_code in {200, 303, 307}, href


def test_pricing_surfaces_payfunnels_checkout_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYFUNNELS_WEBHOOK_SECRET", "pf-secret")
    monkeypatch.setenv("PAYFUNNELS_PLUS_CHECKOUT_URL", "https://checkout.payfunnels.example/plus")
    monkeypatch.setenv("PAYFUNNELS_AGENT_CHECKOUT_URL", "https://checkout.payfunnels.example/agent")
    client = _client()

    pricing = client.get("/pricing")

    assert pricing.status_code == 200
    assert "Secure checkout." in pricing.text
    assert "Checkout uses PayFunnels" not in pricing.text
    assert "Sign in to upgrade" in pricing.text
    assert 'data-rybbit-event="pricing_sign_in_to_upgrade"' in pricing.text


def test_propertyquarry_exposes_privacy_safe_pwa_shell() -> None:
    client = _client()

    public_page = client.get("/")
    app_page = client.get("/app/search")
    manifest = client.get("/manifest.webmanifest")
    service_worker = client.get("/service-worker.js")

    assert public_page.status_code == 200
    assert app_page.status_code == 200
    assert '<link rel="manifest" href="/manifest.webmanifest">' in public_page.text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in app_page.text
    assert "navigator.serviceWorker.register('/service-worker.js', { scope: '/app/' })" in public_page.text
    assert "navigator.serviceWorker.register('/service-worker.js', { scope: '/app/' })" in app_page.text

    assert manifest.status_code == 200
    payload = manifest.json()
    assert payload["name"] == "PropertyQuarry"
    assert payload["start_url"] == "/app/search"
    assert payload["display"] == "standalone"
    assert payload["scope"] == "/"
    assert payload["icons"][0]["src"] == "/pwa-icon.svg"

    assert service_worker.status_code == 200
    assert service_worker.headers["cache-control"] == "no-store"
    assert service_worker.headers["x-content-type-options"] == "nosniff"
    assert service_worker.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "caches.open" not in service_worker.text
    assert "cache.put" not in service_worker.text
    assert "fetch(event.request)" not in service_worker.text


def test_propertyquarry_public_host_blocks_raw_runtime_api_docs() -> None:
    client = _client(principal_id="exec-property-openapi-public")
    for path in ("/openapi.json", "/api/docs", "/api/redoc"):
        response = client.get(path, headers={"host": "propertyquarry.com"}, follow_redirects=False)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "propertyquarry_api_schema_not_public"
        assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive, nosnippet"

    internal_schema = client.get("/openapi.json", follow_redirects=False)
    assert internal_schema.status_code == 200
    assert internal_schema.headers["content-type"].startswith("application/json")


def test_propertyquarry_public_docs_do_not_link_raw_openapi_schema() -> None:
    client = _client(principal_id="exec-property-docs-no-openapi")
    for path in ("/", "/product", "/docs"):
        response = client.get(path, headers={"host": "propertyquarry.com"})
        assert response.status_code == 200, path
        assert "/openapi.json" not in response.text
        assert "API schema" not in response.text


def test_experimental_routes_are_unavailable_in_product_mode_by_default() -> None:
    client = _client()
    for path in ("/tours/example-tour", "/results/example-result"):
        response = client.get(path)
        assert response.status_code == 404, path


def test_app_surface_routes_render_without_product_drift() -> None:
    principal_id = "exec-app-contract"
    client = _client(principal_id=principal_id)
    for path in APP_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_no_drift(response.text)
        assert principal_id not in response.text

    properties = client.get("/app/properties")
    assert str(properties.url).endswith("/app/search")
    assert "Launch search" in properties.text
    assert "Search flow" in properties.text

    settings = client.get("/app/settings")
    assert str(settings.url).endswith("/app/account")
    assert "Useful account controls" in settings.text
    assert "Identity, plan, delivery, and editable defaults." in settings.text


def test_propertyquarry_management_settings_use_property_language() -> None:
    client = _client(principal_id="exec-property-settings-language")
    banned_terms = (
        "office loop",
        "memo",
        "commitment",
        "handoff",
        "draft",
        "operator load",
        "queue items",
        "operator seats",
        "principal seats",
    )
    paths = (
        "/app/settings/plan",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/invitations",
        "/app/settings/outcomes",
    )
    for path in paths:
        response = client.get(path, headers={"host": "propertyquarry.com", "accept": "text/html"})
        assert response.status_code == 200, path
        text = _visible_text(response.text)
        for term in banned_terms:
            assert term not in text, f"{path} leaked {term!r}"
        _assert_internal_links_resolve(client, source_path=path, html=response.text)

    usage = client.get("/app/settings/usage", headers={"host": "propertyquarry.com", "accept": "text/html"})
    assert "Ranked homes" in usage.text
    assert "Sources used" in usage.text
    assert "Source checks" not in usage.text
    assert "Repair status" in usage.text

    trust = client.get("/app/settings/trust", headers={"host": "propertyquarry.com", "accept": "text/html"})
    assert 'href="/downloads"' not in trust.text
    assert 'href="/app/api/property/account/export?download=1"' in trust.text


def test_propertyquarry_settings_detail_aliases_redirect_to_property_pages() -> None:
    client = _client(principal_id="exec-property-settings-aliases")
    for source, target in PROPERTY_SETTINGS_ALIAS_REDIRECTS.items():
        response = client.get(source, headers={"host": "propertyquarry.com", "accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307, source
        assert response.headers["location"] == target
        page = client.get(target, headers={"host": "propertyquarry.com", "accept": "text/html"})
        assert page.status_code == 200, target
        text = _visible_text(page.text)
        assert "memo items" not in text
        assert "commitments" not in text
        assert "handoffs" not in text


def test_propertyquarry_legacy_app_surfaces_redirect_to_property_surfaces() -> None:
    client = _client(principal_id="exec-property-legacy-surfaces")
    for source, target in PROPERTY_LEGACY_APP_SURFACE_REDIRECTS.items():
        response = client.get(source, headers={"host": "propertyquarry.com", "accept": "text/html"}, follow_redirects=False)
        assert response.status_code == 307, source
        assert response.headers["location"] == target
        page = client.get(target, headers={"host": "propertyquarry.com", "accept": "text/html"}, follow_redirects=True)
        assert page.status_code == 200, target
        text = _visible_text(page.text)
        assert "current office loop" not in text
        assert "memo items" not in text
        assert "commitment ledger" not in text
        assert "handoffs" not in text


def test_propertyquarry_core_surface_internal_links_resolve() -> None:
    client = _client(principal_id="exec-property-core-link-contract")
    paths = (
        "/",
        "/product",
        "/pricing",
        "/security",
        "/support",
        "/privacy",
        "/terms",
        "/imprint",
        "/cookies",
        "/docs",
        "/integrations",
        "/guides/wohnung-kaufen-wien-checkliste",
        "/markets/vienna",
        "/register",
        "/sign-in",
        "/app/search",
        "/app/properties",
        "/app/shortlist",
        "/app/agents",
        "/app/account",
        "/app/billing",
    )
    for path in paths:
        response = client.get(path, headers={"host": "propertyquarry.com", "accept": "text/html"}, follow_redirects=True)
        assert response.status_code == 200, path
        _assert_internal_links_resolve(client, source_path=path, html=response.text)


def test_legacy_app_aliases_redirect_to_canonical_routes() -> None:
    client = _client()
    for path, target in LEGACY_APP_ROUTE_REDIRECTS.items():
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307, path
        assert response.headers["location"] == target

    redirected = client.get("/app/inbox?focus=board", follow_redirects=False)
    assert redirected.status_code == 307
    assert redirected.headers["location"] == "/app/queue?focus=board"


def test_unauthenticated_browser_app_navigation_redirects_to_sign_in() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    response = client.get("/app/properties", headers={"accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in?return_to=%2Fapp%2Fproperties"

    deep_link = client.get(
        "/app/properties?run_id=5139bf4532e64edb95534684bf8b620a",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert deep_link.status_code == 303
    assert deep_link.headers["location"] == (
        "/sign-in?return_to=%2Fapp%2Fproperties%3Frun_id%3D5139bf4532e64edb95534684bf8b620a"
    )


def test_unauthenticated_api_calls_still_return_json_auth_error() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ.pop("EA_ENABLE_PUBLIC_SIDE_SURFACES", None)
    os.environ.pop("EA_ENABLE_PUBLIC_RESULTS", None)
    os.environ.pop("EA_ENABLE_PUBLIC_TOURS", None)
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    response = client.get("/app/api/brief", headers={"accept": "application/json"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"
