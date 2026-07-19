from __future__ import annotations

import re

from starlette.requests import Request

from app.api.routes import landing as landing_routes
from tests.product_test_helpers import build_property_client, start_workspace


def test_propertyquarry_locale_contract_does_not_mislabel_untranslated_copy() -> None:
    client = build_property_client(principal_id="pq-ui-locale-contract")
    client.headers.pop("X-EA-Principal-ID", None)

    response = client.get(
        "/?ui_locale=de",
        headers={
            "host": "propertyquarry.com",
            "accept-language": "de-AT,de;q=0.9,en;q=0.8",
        },
    )

    assert response.status_code == 200
    assert '<html lang="en" dir="ltr">' in response.text
    assert response.headers["content-language"] == "en"


def test_propertyquarry_partial_locale_contract_applies_only_to_governed_app_shell() -> None:
    client = build_property_client(principal_id="pq-ui-locale-console")
    start_workspace(client, mode="personal", workspace_name="Locale contract")

    response = client.get(
        "/app/search?ui_locale=es",
        headers={"host": "propertyquarry.com", "accept-language": "es-CR,es;q=0.9"},
    )

    assert response.status_code == 200
    html_tag = re.search(r"<html\b[^>]*>", response.text, re.IGNORECASE)
    assert html_tag is not None
    assert re.search(r'\blang="es-CR"', html_tag.group(0))
    assert re.search(r'\bdir="ltr"', html_tag.group(0))
    assert response.headers["content-language"] == "es-CR"
    assert response.headers["x-propertyquarry-translation-status"] == (
        "critical-ui-shell; english-fallback-legal-provider-incomplete; "
        "not-professionally-reviewed"
    )
    assert 'data-pq-english-fallback="legal provider-specific incomplete"' in response.text
    assert 'data-pq-professional-review="false"' in response.text
    assert "Los textos legales, de proveedores y aún no traducidos permanecen en inglés." in response.text


def test_propertyquarry_locale_resolver_uses_only_governed_complete_ui_locales() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"ui_locale=de",
            "headers": [
                (b"host", b"propertyquarry.com"),
                (b"accept-language", b"de,en;q=0.8"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("propertyquarry.com", 443),
        }
    )

    context = landing_routes._propertyquarry_ui_locale_context(request)

    assert context == {
        "ui_locale": "en",
        "ui_locale_requested": "de",
        "ui_locale_fallback": True,
        "supported_ui_locales": ["en"],
        "document_language": "en",
        "document_direction": "ltr",
    }
