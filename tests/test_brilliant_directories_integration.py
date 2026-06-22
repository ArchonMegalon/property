from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.brilliant_directories import (
    BrilliantDirectoriesApiError,
    build_brilliant_directories_api_request,
    build_brilliant_directories_member_profile_request,
    build_brilliant_directories_member_search_request,
    build_brilliant_directories_projection_packet_from_profile_response,
    build_brilliant_directories_projection_packet_from_search_response,
    build_brilliant_directories_projection_packet,
    build_brilliant_directories_verification_receipt,
    build_directory_profile_projection,
    execute_brilliant_directories_api_request,
    fetch_brilliant_directories_member_profile_projection_packet,
    fetch_brilliant_directories_member_projection_packet,
    load_brilliant_directories_config,
)
from app.services import brilliant_directories as brilliant_directories_service
from tests.product_test_helpers import build_property_client, start_workspace


ROOT = Path(__file__).resolve().parents[1]


class _FakeBrilliantDirectoriesResponse:
    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        self._body = body
        self._content_type = content_type

    def getheader(self, name: str, default: str = "") -> str:
        if name.lower() == "content-type":
            return self._content_type
        return default

    def read(self, size: int = -1) -> bytes:
        if size is not None and size >= 0:
            return self._body[:size]
        return self._body


class _FakeBrilliantDirectoriesOpener:
    def __init__(self, response: _FakeBrilliantDirectoriesResponse) -> None:
        self.response = response
        self.requests: list[object] = []

    def open(self, request, timeout: float = 0):  # noqa: ANN001
        self.requests.append(request)
        return self.response


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_PUBLIC_SITE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_PRICING_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER",
        "BRILLIANT_DIRECTORIES_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_brilliant_directories_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)

    config = load_brilliant_directories_config()
    receipt = build_brilliant_directories_verification_receipt()

    assert config.enabled is False
    assert config.configured is False
    assert receipt["status"] == "disabled"
    assert receipt["live_network_called"] is False


def test_brilliant_directories_enabled_config_requires_https_allowed_host_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")

    with pytest.raises(BrilliantDirectoriesApiError) as missing_base:
        load_brilliant_directories_config()
    assert str(missing_base.value) == "brilliant_directories_base_url_missing"

    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "http://directory.example/api")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "secret")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    with pytest.raises(BrilliantDirectoriesApiError) as non_https:
        load_brilliant_directories_config()
    assert str(non_https.value) == "brilliant_directories_https_required"

    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://evil.example/api")
    with pytest.raises(BrilliantDirectoriesApiError) as bad_host:
        load_brilliant_directories_config()
    assert str(bad_host.value) == "brilliant_directories_host_not_allowed"


def test_brilliant_directories_request_builder_keeps_api_key_out_of_url_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    config = load_brilliant_directories_config()
    request = build_brilliant_directories_api_request(
        config,
        "POST",
        "/members/search",
        payload={"category": "relocation advisor"},
        query={"limit": 10},
    )

    assert request.url == "https://directory.example/api/v2/members/search?limit=10"
    assert request.headers["X-Api-Key"] == "bd-secret-token"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"bd-secret-token" not in (request.body or b"")
    assert request.body == b"category=relocation+advisor"
    assert "bd-secret-token" not in request.url
    assert request.redacted_receipt()["headers"]["X-Api-Key"] == "[redacted]"


def test_brilliant_directories_request_builder_supports_explicit_json_without_making_it_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_api_request(
        load_brilliant_directories_config(),
        "POST",
        "/widgets/render",
        payload={"widget": "public_directory"},
        body_format="json",
    )

    assert request.headers["Content-Type"] == "application/json"
    assert request.body == b'{"widget": "public_directory"}'


def test_brilliant_directories_member_search_request_uses_official_form_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_search_request(
        load_brilliant_directories_config(),
        keyword="relocation",
        category="advisor",
        city="Vienna",
        country_code="at",
        limit=250,
    )

    assert request.method == "POST"
    assert request.url == "https://directory.example/api/v2/user/search"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert request.body is not None
    body = request.body.decode("utf-8")
    assert "q=relocation" in body
    assert "category=advisor" in body
    assert "city=Vienna" in body
    assert "country_code=AT" in body
    assert "limit=100" in body


def test_brilliant_directories_member_search_request_does_not_duplicate_api_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_search_request(
        load_brilliant_directories_config(),
        keyword="relocation",
    )

    assert request.url == "https://directory.example/api/v2/user/search"
    assert "/api/v2/api/v2/" not in request.url


def test_brilliant_directories_member_profile_request_uses_official_get_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    request = build_brilliant_directories_member_profile_request(
        load_brilliant_directories_config(),
        profile_id="24",
    )

    assert request.method == "GET"
    assert request.url == "https://directory.example/api/v2/user/get/24"
    assert request.body is None

    with pytest.raises(BrilliantDirectoriesApiError) as invalid_profile:
        build_brilliant_directories_member_profile_request(load_brilliant_directories_config(), profile_id="../24")
    assert str(invalid_profile.value) == "brilliant_directories_profile_id_invalid"


def test_brilliant_directories_member_profile_fetch_projects_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(
            b'{"message":{"user_id":"24","company":"Vienna Relocation Advisors","profession":"Relocation"}}'
        )
    )

    packet = fetch_brilliant_directories_member_profile_projection_packet(
        load_brilliant_directories_config(),
        profile_id="24",
        purpose="Public profile detail",
        opener=opener,
    )

    assert opener.requests[0].get_full_url() == "https://directory.example/api/v2/user/get/24"
    assert packet.as_dict()["profiles"][0]["display_name"] == "Vienna Relocation Advisors"


def test_brilliant_directories_executor_reads_json_without_leaking_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    config = load_brilliant_directories_config()
    request = build_brilliant_directories_member_search_request(config, keyword="relocation")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(b'{"message":[{"user_id":"7","company":"Public Advisor"}]}')
    )

    payload = execute_brilliant_directories_api_request(request, opener=opener)

    assert payload["message"][0]["company"] == "Public Advisor"  # type: ignore[index]
    assert opener.requests
    sent = opener.requests[0]
    assert sent.get_full_url() == "https://directory.example/api/v2/user/search"
    assert sent.get_header("X-api-key") == "bd-secret-token" or sent.get_header("X-Api-Key") == "bd-secret-token"
    assert request.redacted_receipt()["headers"]["X-Api-Key"] == "[redacted]"
    assert "bd-secret-token" not in json.dumps(request.redacted_receipt())


def test_brilliant_directories_executor_rejects_non_json_and_oversized_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    request = build_brilliant_directories_member_search_request(load_brilliant_directories_config())

    with pytest.raises(BrilliantDirectoriesApiError) as content_type_error:
        execute_brilliant_directories_api_request(
            request,
            opener=_FakeBrilliantDirectoriesOpener(
                _FakeBrilliantDirectoriesResponse(b"<html></html>", content_type="text/html")
            ),
        )
    assert str(content_type_error.value) == "brilliant_directories_unexpected_content_type"

    monkeypatch.setattr(brilliant_directories_service, "BRILLIANT_DIRECTORIES_MAX_RESPONSE_BYTES", 8)
    with pytest.raises(BrilliantDirectoriesApiError) as oversized_error:
        execute_brilliant_directories_api_request(
            request,
            opener=_FakeBrilliantDirectoriesOpener(
                _FakeBrilliantDirectoriesResponse(b'{"message":[1,2,3]}')
            ),
        )
    assert str(oversized_error.value) == "brilliant_directories_response_too_large"


def test_brilliant_directories_executor_blocks_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    request = build_brilliant_directories_member_search_request(load_brilliant_directories_config())

    class _RedirectingOpener:
        def open(self, request, timeout: float = 0):  # noqa: ANN001
            import urllib.error

            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "brilliant_directories_redirect_blocked",
                {},
                None,
            )

    with pytest.raises(BrilliantDirectoriesApiError) as redirect_error:
        execute_brilliant_directories_api_request(request, opener=_RedirectingOpener())
    assert str(redirect_error.value) == "brilliant_directories_redirect_blocked"


def test_brilliant_directories_projection_allows_public_directory_fields() -> None:
    profile = build_directory_profile_projection(
        {
            "member_id": 42,
            "name": "Vienna Relocation Advisors",
            "category": "Relocation",
            "profile_url": "https://directory.example/vienna-relocation",
            "city": "Vienna",
            "region": "Vienna",
            "country_code": "AT",
            "description": "English and German relocation guidance.",
            "tags": ["relocation", "renters"],
        }
    )
    packet = build_brilliant_directories_projection_packet([profile], purpose="Public relocation directory")
    payload = packet.as_dict()

    assert payload["contract_name"] == "propertyquarry.brilliant_directories_projection.v1"
    assert payload["profile_count"] == 1
    assert payload["publication_allowed"] is False
    assert payload["direct_property_truth_mutation_allowed"] is False
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"


def test_brilliant_directories_projection_rejects_private_property_and_contact_fields() -> None:
    with pytest.raises(BrilliantDirectoriesApiError) as contact_error:
        build_directory_profile_projection({"id": "1", "name": "Agent", "email": "agent@example.test"})
    assert "private_field_blocked" in str(contact_error.value)

    with pytest.raises(BrilliantDirectoriesApiError) as ranking_error:
        build_directory_profile_projection({"id": "1", "name": "Agent", "property_facts": {"price": 1000}})
    assert "private_field_blocked" in str(ranking_error.value)


def test_brilliant_directories_search_response_strips_private_member_fields() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {
                    "user_id": "17",
                    "company": "Vienna Relocation Advisors",
                    "email": "agent@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "lat": "48.2",
                    "lon": "16.3",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                    "search_description": "Public profile text with no contact detail.",
                }
            ],
        },
        purpose="Public relocation directory",
    )

    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert payload["profiles"][0]["public_url"] == "austria/vienna/vienna-relocation-advisors"
    assert "agent@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized
    assert "16.3" not in serialized
    assert "Public profile text" not in serialized


def test_brilliant_directories_search_response_strips_unapproved_external_profile_urls() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {
                    "user_id": "91",
                    "company": "Approved Directory Advisor",
                    "profile_url": "https://directory.example/austria/vienna/approved-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
                {
                    "user_id": "92",
                    "company": "External Directory Advisor",
                    "profile_url": "https://tracking.example/profile/external-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
                {
                    "user_id": "93",
                    "company": "Relative Directory Advisor",
                    "filename": "austria/vienna/relative-advisor",
                    "city": "Vienna",
                    "country_code": "AT",
                },
            ],
        },
        purpose="Public relocation directory",
        allowed_url_hosts=("directory.example",),
    )

    profiles = packet.as_dict()["profiles"]
    assert profiles[0]["public_url"] == "https://directory.example/austria/vienna/approved-advisor"
    assert "public_url" not in profiles[1]
    assert profiles[2]["public_url"] == "austria/vienna/relative-advisor"


def test_brilliant_directories_search_response_strips_unsafe_relative_profile_urls() -> None:
    packet = build_brilliant_directories_projection_packet_from_search_response(
        {
            "status": "success",
            "message": [
                {"user_id": "81", "company": "Traversal Advisor", "filename": "../private/profile"},
                {"user_id": "82", "company": "Protocol Relative Advisor", "filename": "//evil.example/profile"},
            ],
        },
        purpose="Public relocation directory",
    )

    profiles = packet.as_dict()["profiles"]
    assert "public_url" not in profiles[0]
    assert "public_url" not in profiles[1]


def test_brilliant_directories_profile_response_projects_public_detail_only() -> None:
    packet = build_brilliant_directories_projection_packet_from_profile_response(
        {
            "status": "success",
            "message": {
                "user_id": "24",
                "company": "Vienna Relocation Advisors",
                "profession": "Relocation",
                "description": "Helps international renters prepare a Vienna search.",
                "specialties": "relocation,renters",
                "email": "private@example.test",
                "phone_number": "+43 1 555",
                "address1": "Secret Street 1",
                "lat": "48.2",
                "lon": "16.3",
                "filename": "austria/vienna/vienna-relocation-advisors",
                "city": "Vienna",
                "state_ln": "Vienna",
                "country_code": "AT",
            },
        },
        purpose="Public profile detail",
        allowed_url_hosts=("directory.example",),
    )

    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)
    profile = payload["profiles"][0]
    assert payload["projection_mode"] == "public_directory_profile_detail"
    assert profile["profile_id"] == "24"
    assert profile["display_name"] == "Vienna Relocation Advisors"
    assert profile["summary"] == "Helps international renters prepare a Vienna search."
    assert "relocation" in profile["tags"]
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized


def test_brilliant_directories_live_style_search_projection_uses_public_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example/api/v2")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    opener = _FakeBrilliantDirectoriesOpener(
        _FakeBrilliantDirectoriesResponse(
            json.dumps(
                {
                    "message": [
                        {
                            "user_id": "24",
                            "company": "Vienna Relocation Advisors",
                            "email": "private@example.test",
                            "phone_number": "+43 1 555",
                            "filename": "austria/vienna/vienna-relocation-advisors",
                            "city": "Vienna",
                            "state_ln": "Vienna",
                            "country_code": "AT",
                        }
                    ]
                }
            ).encode("utf-8")
        )
    )

    packet = fetch_brilliant_directories_member_projection_packet(
        load_brilliant_directories_config(),
        purpose="Public relocation directory",
        keyword="relocation",
        city="Vienna",
        country_code="AT",
        opener=opener,
    )
    payload = packet.as_dict()
    serialized = json.dumps(payload, sort_keys=True)

    assert opener.requests[0].get_full_url() == "https://directory.example/api/v2/user/search"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized


def test_brilliant_directories_runtime_route_reports_disabled_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-disabled")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/brilliant-directories/members?city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "brilliant_directories"
    assert payload["status"] == "disabled"
    assert payload["profile_count"] == 0
    assert payload["profiles"] == []
    assert payload["publication_allowed"] is False
    assert payload["direct_property_truth_mutation_allowed"] is False


def test_property_directory_members_route_is_white_label_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-directory-disabled")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/members?city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert payload["status"] == "disabled"
    assert payload["profile_count"] == 0
    assert payload["profiles"] == []
    assert "brilliant_directories" not in serialized
    assert "brilliant directories" not in serialized.lower()
    assert "brilliantdirectories" not in serialized.lower()


def test_brilliant_directories_runtime_route_fetches_public_member_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    captured_requests: list[object] = []

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        captured_requests.append(request)
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "lat": "48.2",
                    "lon": "16.3",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-runtime")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/brilliant-directories/members"
        "?keyword=relocation&category=advisor&city=Vienna&country_code=AT&limit=8",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "ready"
    assert payload["contract_name"] == "propertyquarry.brilliant_directories_projection.v1"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert payload["profiles"][0]["public_url"] == "austria/vienna/vienna-relocation-advisors"
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized
    assert "48.2" not in serialized
    assert "16.3" not in serialized
    assert captured_requests
    sent = captured_requests[0]
    assert sent.url == "https://directory.example/api/v2/user/search"
    assert b"q=relocation" in (sent.body or b"")
    assert b"category=advisor" in (sent.body or b"")
    assert b"city=Vienna" in (sent.body or b"")
    assert b"country_code=AT" in (sent.body or b"")
    assert b"limit=8" in (sent.body or b"")
    assert b"bd-secret-token" not in (sent.body or b"")


def test_property_directory_members_route_returns_white_label_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        assert getattr(request, "url", "") == "https://directory.example/api/v2/user/search"
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "profession": "Relocation",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-directory-white-label")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(
        "/app/api/property/directories/members?keyword=relocation&city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["contract_name"] == "propertyquarry.directory_projection.v1"
    assert payload["status"] == "ready"
    assert payload["profile_count"] == 1
    assert payload["profiles"][0]["display_name"] == "Vienna Relocation Advisors"
    assert "brilliant_directories" not in serialized
    assert "brilliant directories" not in serialized.lower()
    assert "brilliantdirectories" not in serialized.lower()
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized


def test_brilliant_directories_public_directory_page_is_white_label_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-public-disabled")

    response = client.get("/directory", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in response.text
    assert response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"
    assert "PropertyQuarry Directory" in response.text
    assert "Find the people around a property decision." in response.text
    assert "Profiles are being prepared" in response.text
    assert "governed directory lane" not in response.text
    assert "another branded site" not in response.text
    assert "</style>\n</style>" not in response.text
    assert "Search directory" in response.text
    assert "Brilliant Directories" not in response.text
    assert "brilliantdirectories.com" not in response.text.lower()
    assert "credentials" not in response.text
    assert "not active on this host" not in response.text
    assert "provider returned" not in response.text.lower()
    assert "provider stores" not in response.text.lower()

    profile_response = client.get("/directory/profile/sample", headers={"host": "propertyquarry.com"})
    assert profile_response.status_code == 200
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in profile_response.text
    assert profile_response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"
    assert "another branded site" not in profile_response.text


def test_brilliant_directories_sitemap_hides_unconfigured_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-sitemap-disabled")

    response = client.get("/sitemap.xml", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "<loc>https://propertyquarry.com/</loc>" in response.text
    assert "<loc>https://propertyquarry.com/pricing</loc>" in response.text
    assert "<loc>https://propertyquarry.com/directory</loc>" not in response.text
    assert "directory.example" not in response.text


def test_brilliant_directories_sitemap_includes_configured_white_label_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")
    client = build_property_client(principal_id="pq-brilliant-directories-sitemap-ready")

    response = client.get("/sitemap.xml", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "<loc>https://propertyquarry.com/directory</loc>" in response.text
    assert "directory.example" not in response.text
    assert "bd-secret-token" not in response.text


def test_brilliant_directories_public_directory_page_renders_sanitized_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del timeout_seconds, opener
        request_url = str(getattr(request, "url", "") or "")
        if request_url == "https://directory.example/api/v2/user/get/24":
            return {
                "message": {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "profession": "Relocation",
                    "description": "Helps international renters prepare a Vienna search.",
                    "specialties": "relocation,renters",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            }
        assert request_url == "https://directory.example/api/v2/user/search"
        return {
            "message": [
                {
                    "user_id": "24",
                    "company": "Vienna Relocation Advisors",
                    "email": "private@example.test",
                    "phone_number": "+43 1 555",
                    "address1": "Secret Street 1",
                    "filename": "austria/vienna/vienna-relocation-advisors",
                    "city": "Vienna",
                    "state_ln": "Vienna",
                    "country_code": "AT",
                }
            ]
        }

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-public-ready")

    response = client.get(
        "/directory?keyword=relocation&city=Vienna&country_code=AT",
        headers={"host": "propertyquarry.com"},
    )

    assert response.status_code == 200
    serialized = response.text
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in serialized
    assert response.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"
    assert "Vienna Relocation Advisors" in serialized
    assert "/directory/profile/24" in serialized
    assert "https://directory.example/austria/vienna/vienna-relocation-advisors" not in serialized
    assert "target=\"_blank\"" not in serialized
    assert "1 public profile shown" in serialized
    assert "private@example.test" not in serialized
    assert "+43 1 555" not in serialized
    assert "Secret Street" not in serialized

    profile_response = client.get("/directory/profile/24", headers={"host": "propertyquarry.com"})
    assert profile_response.status_code == 200
    assert "<title>Vienna Relocation Advisors | PropertyQuarry Directory</title>" in profile_response.text
    assert (
        '<meta name="description" content="Helps international renters prepare a Vienna search.">'
        in profile_response.text
    )
    assert '<meta name="robots" content="index, follow, max-image-preview:large">' in profile_response.text
    assert profile_response.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"
    assert "Vienna Relocation Advisors" in profile_response.text
    assert "Helps international renters prepare a Vienna search." in profile_response.text
    assert "Relocation" in profile_response.text
    assert "private@example.test" not in profile_response.text
    assert "+43 1 555" not in profile_response.text
    assert "Secret Street" not in profile_response.text
    assert "directory.example" not in profile_response.text
    assert "Brilliant Directories" not in profile_response.text


def test_brilliant_directories_public_directory_page_noindexes_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL", "https://directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS", "directory.example")
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY", "bd-secret-token")

    def fake_execute(request: object, *, timeout_seconds: float = 30.0, opener: object | None = None) -> dict[str, object]:
        del request, timeout_seconds, opener
        return {"message": []}

    monkeypatch.setattr(brilliant_directories_service, "execute_brilliant_directories_api_request", fake_execute)
    client = build_property_client(principal_id="pq-brilliant-directories-public-empty")

    response = client.get("/directory?keyword=missing", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "No public profiles matched" in response.text
    assert '<meta name="robots" content="noindex, follow, noarchive, nosnippet">' in response.text
    assert response.headers.get("X-Robots-Tag") == "noindex, follow, noarchive, nosnippet"


def test_brilliant_directories_pricing_stays_propertyquarry_white_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    client = build_property_client(principal_id="pq-brilliant-directories-pricing")

    response = client.get("/pricing", headers={"host": "propertyquarry.com"}, follow_redirects=False)

    assert response.status_code == 200
    assert "<h1>Pricing</h1>" in response.text
    assert "directory.example" not in response.text


def test_brilliant_directories_script_writes_disabled_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR", str(tmp_path))

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_brilliant_directories_provider.py")],
        cwd=ROOT,
        env={**dict(os.environ), "PYTHONPATH": str(ROOT / "ea")},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    out_path = Path(completed.stdout.strip())
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload["provider"] == "brilliant_directories"
    assert payload["status"] == "disabled"
    assert payload["live_network_called"] is False
    assert payload["verified_capabilities"]["form_encoded_request_contract"] is True
    assert payload["verified_capabilities"]["private_provider_contact_fields_stripped"] is True
