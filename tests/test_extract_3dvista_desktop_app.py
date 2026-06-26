from __future__ import annotations

from pathlib import Path

from scripts.extract_3dvista_desktop_app import build_3dvista_app_receipt


def _write_fake_3dvista_app(root: Path) -> None:
    (root / "META-INF" / "AIR").mkdir(parents=True)
    (root / "bin" / "win64").mkdir(parents=True)
    (root / "3DVista Virtual Tour.exe").write_bytes(b"MZ")
    (root / "bin" / "win64" / "tdvtools_v2.exe").write_bytes(b"MZtdv")
    (root / "bin" / "win64" / "three-d-tools.exe").write_bytes(b"MZ3d")
    (root / "bin" / "win64" / "TDVServer.exe").write_bytes(b"MZsrv")
    (root / "META-INF" / "AIR" / "application.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<application xmlns="http://ns.adobe.com/air/application/50.2">
  <id>tdv.show</id>
  <name>3DVista Virtual Tour</name>
  <versionNumber>26.0.3</versionNumber>
  <versionLabel>2026.0.3</versionLabel>
</application>
""",
        encoding="utf-8",
    )


def test_3dvista_desktop_app_receipt_tracks_app_and_helper_readiness(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    installer = tmp_path / "3DVVirtualTour_x64.exe"
    installer.write_bytes(b"MZinstaller")
    _write_fake_3dvista_app(app_dir)

    receipt = build_3dvista_app_receipt(
        installer_path=installer,
        app_dir=app_dir,
        extract_dir=tmp_path / "extract",
    )

    assert receipt["status"] == "ready"
    assert receipt["installer"]["exists"] is True
    assert receipt["app"]["exists"] is True
    assert receipt["air_metadata"]["version_label"] == "2026.0.3"
    assert receipt["air_metadata"]["app_id"] == "tdv.show"
    assert receipt["panorama_processing_cli_ready"] is True
    assert receipt["three_d_asset_cli_ready"] is True
    assert receipt["local_tour_server_cli_ready"] is True


def test_3dvista_desktop_app_receipt_does_not_claim_verified_export(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    _write_fake_3dvista_app(app_dir)

    receipt = build_3dvista_app_receipt(
        installer_path=tmp_path / "missing-installer.exe",
        app_dir=app_dir,
        extract_dir=tmp_path / "extract",
    )

    assert receipt["status"] == "ready"
    assert receipt["headless_publish_cli_ready"] is False
    assert receipt["verified_export_required"] is True
    assert receipt["next_actions"][0]["area"] == "verified_3dvista_export"


def test_3dvista_desktop_app_receipt_reports_missing_app(tmp_path: Path) -> None:
    receipt = build_3dvista_app_receipt(
        installer_path=tmp_path / "missing-installer.exe",
        app_dir=tmp_path / "missing-app",
        extract_dir=tmp_path / "extract",
    )

    assert receipt["status"] == "missing_app"
    assert receipt["app"]["exists"] is False
    assert receipt["panorama_processing_cli_ready"] is False
