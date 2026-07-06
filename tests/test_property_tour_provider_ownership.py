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


def test_tour_provider_ownership_receipt_can_capture_current_import_and_private_viewer_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("THREEDVISTA_LOGIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("THREEDVISTA_LOGIN_PASSWORD", "secretpass")
    monkeypatch.setenv("PANO2VR_EMAIL", "owner@example.com")
    monkeypatch.setenv("PANO2VR_LICENSE_KEY", "super-secret-license")

    (tmp_path / "3dvista_private_viewer_refresh_live_current.json").write_text(
        json.dumps(
            {
                "status": "refreshed",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/3dvista",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "3dvista-import-current.json").write_text(
        json.dumps(
            {
                "status": "imported",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/3dvista",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "3dvista-web-account-probe-current.json").write_text(
        json.dumps({"status": "ok"}),
        encoding="utf-8",
    )
    (tmp_path / "pano2vr-import-current.json").write_text(
        json.dumps(
            {
                "status": "imported",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/pano2vr",
            }
        ),
        encoding="utf-8",
    )

    receipt = build_property_tour_provider_ownership_receipt(receipt_root=tmp_path)

    assert receipt["providers"]["3dvista"]["private_viewer_verified"] is True
    assert receipt["providers"]["3dvista"]["import_verified"] is True
    assert receipt["providers"]["3dvista"]["export_verified"] is True
    assert receipt["providers"]["3dvista"]["web_account_probe_ok"] is True
    assert receipt["providers"]["3dvista"]["control_url"] == "/tours/luxury-slug/control/3dvista"
    assert receipt["providers"]["pano2vr"]["import_verified"] is True
    assert receipt["providers"]["pano2vr"]["export_verified"] is True
    assert receipt["providers"]["pano2vr"]["control_url"] == "/tours/luxury-slug/control/pano2vr"


def test_tour_provider_ownership_receipt_passes_from_receipt_backed_delivery_evidence_without_secrets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("THREEDVISTA_LOGIN_EMAIL", raising=False)
    monkeypatch.delenv("THREEDVISTA_LICENSE_EMAIL", raising=False)
    monkeypatch.delenv("THREEDVISTA_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("PANO2VR_EMAIL", raising=False)
    monkeypatch.delenv("PANO2VR_LICENSE_KEY", raising=False)

    (tmp_path / "3dvista_private_viewer_refresh_live_current.json").write_text(
        json.dumps(
            {
                "status": "refreshed",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/3dvista",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "3dvista-import-current.json").write_text(
        json.dumps(
            {
                "status": "imported",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/3dvista",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pano2vr-import-current.json").write_text(
        json.dumps(
            {
                "status": "imported",
                "slug": "luxury-slug",
                "control_url": "/tours/luxury-slug/control/pano2vr",
            }
        ),
        encoding="utf-8",
    )

    receipt = build_property_tour_provider_ownership_receipt(receipt_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["missing_providers"] == []
    assert receipt["providers"]["3dvista"]["status"] == "owned_receipt_backed"
    assert receipt["providers"]["3dvista"]["ownership_metadata_present"] is True
    assert receipt["providers"]["3dvista"]["secret_config_present"] is False
    assert receipt["providers"]["3dvista"]["delivery_evidence_present"] is True
    assert receipt["providers"]["pano2vr"]["status"] == "owned_receipt_backed"
    assert receipt["providers"]["pano2vr"]["ownership_metadata_present"] is True
    assert receipt["providers"]["pano2vr"]["secret_config_present"] is False
    assert receipt["providers"]["pano2vr"]["delivery_evidence_present"] is True
