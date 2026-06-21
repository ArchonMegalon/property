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
    build_brilliant_directories_projection_packet,
    build_brilliant_directories_verification_receipt,
    build_directory_profile_projection,
    load_brilliant_directories_config,
)


ROOT = Path(__file__).resolve().parents[1]


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_ENABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_DISABLED",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BASE_URL",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_ALLOWED_HOSTS",
        "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY",
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
    assert b"bd-secret-token" not in (request.body or b"")
    assert "bd-secret-token" not in request.url
    assert request.redacted_receipt()["headers"]["X-Api-Key"] == "[redacted]"


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
