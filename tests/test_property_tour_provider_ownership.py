from __future__ import annotations

import json

from scripts.verify_property_tour_provider_ownership import build_property_tour_provider_ownership_receipt


def test_tour_provider_ownership_receipt_passes_without_leaking_secrets(monkeypatch) -> None:
    monkeypatch.setenv("THREEDVISTA_LOGIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("THREEDVISTA_LOGIN_PASSWORD", "secretpass")
    monkeypatch.setenv("PANO2VR_EMAIL", "owner@example.com")
    monkeypatch.setenv("PANO2VR_LICENSE_KEY", "super-secret-license")

    receipt = build_property_tour_provider_ownership_receipt()
    serialized = json.dumps(receipt)

    assert receipt["status"] == "pass"
    assert receipt["providers"]["3dvista"]["status"] == "owned_configured"
    assert receipt["providers"]["pano2vr"]["status"] == "owned_configured"
    assert receipt["providers"]["3dvista"]["export_verified"] is False
    assert receipt["providers"]["pano2vr"]["export_verified"] is False
    assert receipt["privacy"]["secrets_in_receipt"] is False
    assert "secretpass" not in serialized
    assert "super-secret-license" not in serialized
    assert receipt["providers"]["pano2vr"]["license_key"]["present"] is True
    assert receipt["providers"]["pano2vr"]["license_key"]["length"] == len("super-secret-license")


def test_tour_provider_ownership_receipt_blocks_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("THREEDVISTA_LOGIN_EMAIL", raising=False)
    monkeypatch.delenv("THREEDVISTA_LICENSE_EMAIL", raising=False)
    monkeypatch.delenv("THREEDVISTA_LOGIN_PASSWORD", raising=False)
    monkeypatch.setenv("PANO2VR_EMAIL", "owner@example.com")
    monkeypatch.setenv("PANO2VR_LICENSE_KEY", "super-secret-license")

    receipt = build_property_tour_provider_ownership_receipt()

    assert receipt["status"] == "blocked_missing_config"
    assert receipt["missing_providers"] == ["3dvista"]
