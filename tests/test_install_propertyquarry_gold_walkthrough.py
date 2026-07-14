from scripts.install_propertyquarry_gold_walkthrough import (
    DESKTOP_RELPATH,
    MOBILE_RELPATH,
    updated_manifest,
    updated_public_assets,
)


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


def test_updated_manifest_selects_60fps_desktop_and_mobile_variants() -> None:
    manifest = updated_manifest(
        {"slug": "danube-flats", "public_assets": [{"path": "preview.png"}]},
        desktop_variant=_variant(key="desktop", width=1920, height=1080, size_bytes=50_000_000),
        mobile_variant=_variant(key="mobile", width=1280, height=720, size_bytes=30_000_000),
        generated_at="2026-07-10T15:00:00Z",
    )

    assert manifest["video_relpath"] == DESKTOP_RELPATH
    assert manifest["video_mobile_relpath"] == MOBILE_RELPATH
    assert manifest["video_provider"] == "magicfit"
    assert manifest["video_coverage_proof"] == "boundary_verified_frame_continuation"
    assert manifest["magicfit_import"]["desktop_frame_rate"] == "60/1"
    assert manifest["magicfit_import"]["mobile_frame_rate"] == "60/1"
    assert manifest["magicfit_import"]["frame_duplication_only"] is False
