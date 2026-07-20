import json
from pathlib import Path

import pytest

from scripts.install_propertyquarry_gold_walkthrough import (
    CORE_GOLD_PROVIDER_KEY,
    DESKTOP_RELPATH,
    MOBILE_RELPATH,
    SIDECAR_RELPATH,
    _manifest_walkthrough_path,
    build_sidecar,
    updated_manifest,
    updated_public_assets,
)


def test_rollback_verification_uses_current_manifest_video_not_a_provider_name(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "generic-bundle"
    bundle_dir.mkdir()
    video = bundle_dir / "current-provider-neutral-video.mp4"
    video.write_bytes(b"existing-video")

    assert _manifest_walkthrough_path(
        bundle_dir,
        {"video_relpath": "current-provider-neutral-video.mp4"},
    ) == video.resolve()


def _variant(*, key: str, width: int, height: int, size_bytes: int) -> dict[str, object]:
    return {
        "key": key,
        "sha256": f"{key}-sha",
        "metadata": {
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "avg_frame_rate": "60/1",
        },
    }


def test_updated_public_assets_preserves_existing_assets_and_replaces_video_rows() -> None:
    assets = updated_public_assets(
        {
            "public_assets": [
                {"path": "preview.png", "role": "preview", "privacy_class": "public"},
                {"path": DESKTOP_RELPATH, "role": "stale"},
                {"path": MOBILE_RELPATH, "role": "stale"},
            ]
        }
    )

    assert assets[0]["path"] == "preview.png"
    assert assets[1] == {
        "path": DESKTOP_RELPATH,
        "privacy_class": "public",
        "role": "video",
        "mime_type": "video/mp4",
    }
    assert assets[2] == {
        "path": MOBILE_RELPATH,
        "privacy_class": "public",
        "role": "video_mobile",
        "mime_type": "video/mp4",
    }


def test_core_gold_sidecar_is_provider_independent(
    tmp_path: Path,
) -> None:
    source_receipt = tmp_path / "source.json"
    desktop_receipt = tmp_path / "desktop.json"
    mobile_receipt = tmp_path / "mobile.json"
    for path in (source_receipt, desktop_receipt, mobile_receipt):
        path.write_text("{}\n", encoding="utf-8")

    sidecar = build_sidecar(
        source_receipt={
            "composition": "boundary_verified_frame_continuation",
            "continuity_repair_status": "pass",
        },
        source_receipt_path=source_receipt,
        desktop_receipt_path=desktop_receipt,
        desktop_variant=_variant(
            key="desktop", width=1920, height=1080, size_bytes=50_000_000
        ),
        mobile_receipt_path=mobile_receipt,
        mobile_variant=_variant(
            key="mobile", width=1280, height=720, size_bytes=30_000_000
        ),
        generated_at="2026-07-10T15:00:00Z",
    )

    assert SIDECAR_RELPATH == "tour.walkthrough.json"
    assert sidecar["contract_name"] == "propertyquarry.core_gold_walkthrough.v1"
    assert sidecar["provider_key"] == CORE_GOLD_PROVIDER_KEY
    assert sidecar["provider_backend_key"] == CORE_GOLD_PROVIDER_KEY
    assert "magicfit_import" not in sidecar
    assert not any("magicfit" in key.lower() for key in sidecar)


def test_updated_manifest_selects_60fps_desktop_and_mobile_variants() -> None:
    manifest = updated_manifest(
        {"slug": "danube-flats", "public_assets": [{"path": "preview.png"}]},
        desktop_variant=_variant(key="desktop", width=1920, height=1080, size_bytes=50_000_000),
        mobile_variant=_variant(key="mobile", width=1280, height=720, size_bytes=30_000_000),
        generated_at="2026-07-10T15:00:00Z",
    )

    assert manifest["video_relpath"] == DESKTOP_RELPATH
    assert manifest["video_mobile_relpath"] == MOBILE_RELPATH
    assert manifest["video_provider"] == CORE_GOLD_PROVIDER_KEY
    assert manifest["video_provider_key"] == CORE_GOLD_PROVIDER_KEY
    assert manifest["video_sidecar_relpath"] == "tour.walkthrough.json"
    assert manifest["video_coverage_proof"] == "boundary_verified_frame_continuation"
    assert manifest["core_gold_walkthrough"]["desktop_frame_rate"] == "60/1"
    assert manifest["core_gold_walkthrough"]["mobile_frame_rate"] == "60/1"
    assert manifest["core_gold_walkthrough"]["frame_duplication_only"] is False
    assert "magicfit_import" not in manifest
    assert "magicfit" not in json.dumps(manifest, sort_keys=True).lower()


def test_updated_manifest_removes_legacy_magicfit_claims_and_asset_rows() -> None:
    manifest = updated_manifest(
        {
            "slug": "danube-flats",
            "video_provider": "magicfit",
            "video_sidecar_relpath": "tour.magicfit.json",
            "magicfit_import": {"launch_eligible": True},
            "magicfit_stale_claim": "remove-me",
            "public_assets": [
                {"path": "preview.png"},
                {"path": "magicfit-walkthrough.mp4"},
                {"path": "magicfit-walkthrough-desktop-1080p60.mp4"},
                {"path": "magicfit-walkthrough-mobile-720p60.mp4"},
                {"path": "tour.magicfit.json"},
            ],
        },
        desktop_variant=_variant(
            key="desktop", width=1920, height=1080, size_bytes=50_000_000
        ),
        mobile_variant=_variant(
            key="mobile", width=1280, height=720, size_bytes=30_000_000
        ),
        generated_at="2026-07-10T15:00:00Z",
    )

    serialized = json.dumps(manifest, sort_keys=True).lower()
    assert "magicfit" not in serialized
    assert [row["path"] for row in manifest["public_assets"]] == [
        "preview.png",
        DESKTOP_RELPATH,
        MOBILE_RELPATH,
    ]


def test_updated_manifest_fails_closed_on_unknown_nested_provider_claim() -> None:
    with pytest.raises(
        RuntimeError,
        match="core_gold_manifest_provider_claims_remain",
    ):
        updated_manifest(
            {
                "slug": "danube-flats",
                "historical_delivery": {"provider": "magicfit"},
            },
            desktop_variant=_variant(
                key="desktop",
                width=1920,
                height=1080,
                size_bytes=50_000_000,
            ),
            mobile_variant=_variant(
                key="mobile",
                width=1280,
                height=720,
                size_bytes=30_000_000,
            ),
            generated_at="2026-07-10T15:00:00Z",
        )
