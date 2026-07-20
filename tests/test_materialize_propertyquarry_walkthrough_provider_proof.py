import json
from pathlib import Path

import pytest

from scripts.materialize_propertyquarry_walkthrough_provider_proof import (
    _source_sidecar,
    _validate_source,
    materialize,
)


def test_validate_source_accepts_completed_magicfit_composite() -> None:
    _validate_source(
        "magicfit",
        {
            "provider": "magicfit",
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "render_status": "completed",
            "target_slug": "strict-source-home",
            "hosted_walkthrough_video_url": (
                "https://media.powlcdn.com/magicfit/strict-source-home.mp4"
            ),
        },
        slug="strict-source-home",
    )


def test_validate_source_rejects_retired_shallow_magicfit_receipt() -> None:
    with pytest.raises(
        RuntimeError,
        match="magicfit_strict_source_receipt_required",
    ):
        _validate_source(
            "magicfit",
            {
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "render_status": "completed",
                "status": "rendered",
                "composition": "boundary_verified_frame_continuation",
                "segment_count": 2,
                "route_labels": ["living", "kitchen"],
                "covered_route_labels": ["living", "kitchen"],
            },
            slug="strict-source-home",
        )


def test_validate_source_rejects_omagic_without_model_consumption() -> None:
    with pytest.raises(RuntimeError, match="omagic_source_model_not_consumed"):
        _validate_source(
            "omagic",
            {
                "provider_key": "omagic",
                "provider_backend_key": "omagic",
                "render_status": "completed",
                "model_input_consumed": False,
                "model_input_consumption_proof": "",
            },
        )


def test_magicfit_shallow_public_sidecar_is_forbidden(tmp_path: Path) -> None:
    source_receipt = tmp_path / "source.json"
    source_receipt.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="magicfit_shallow_public_sidecar_forbidden",
    ):
        _source_sidecar(
            provider="magicfit",
            source={},
            video_relpath="walkthrough.mp4",
            source_receipt_path=source_receipt,
            metadata={
                "duration_seconds": 29.186,
                "width": 1920,
                "height": 1080,
                "size_bytes": 123,
            },
        )


def test_magicfit_materializer_fails_closed_with_exact_import_handoff(
    tmp_path: Path,
) -> None:
    video = tmp_path / "composed.mp4"
    video.write_bytes(b"composed-video")
    slug = "strict-source-home"
    receipt = tmp_path / "source-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "render_status": "completed",
                "target_slug": slug,
                "hosted_walkthrough_video_url": (
                    "https://media.powlcdn.com/magicfit/strict-source-home.mp4"
                ),
            }
        ),
        encoding="utf-8",
    )
    public_root = tmp_path / "public"

    with pytest.raises(RuntimeError) as raised:
        materialize(
            provider="magicfit",
            tour_root=public_root,
            slug=slug,
            title="Strict source home",
            video_path=video,
            source_receipt_path=receipt,
        )

    message = str(raised.value)
    assert "magicfit_public_materialization_forbidden" in message
    assert "import_magicfit_walkthrough.py" in message
    assert f"--slug {slug}" in message
    assert f"--video-path {video}" in message
    assert f"--source-receipt {receipt}" in message
    assert not public_root.exists()


def test_magicfit_materializer_rejects_json_the_importer_cannot_load(
    tmp_path: Path,
) -> None:
    video = tmp_path / "composed.mp4"
    video.write_bytes(b"composed-video")
    receipt = tmp_path / "duplicate-key-source-receipt.json"
    receipt.write_text(
        """{
          "render_status": "completed",
          "render_status": "completed",
          "target_slug": "strict-source-home",
          "hosted_walkthrough_video_url": "https://media.powlcdn.com/magicfit/strict-source-home.mp4"
        }\n""",
        encoding="utf-8",
    )
    public_root = tmp_path / "public"

    with pytest.raises(
        RuntimeError,
        match="magicfit_strict_source_receipt_required",
    ):
        materialize(
            provider="magicfit",
            tour_root=public_root,
            slug="strict-source-home",
            title="Strict source home",
            video_path=video,
            source_receipt_path=receipt,
        )

    assert not public_root.exists()
