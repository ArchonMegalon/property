from pathlib import Path

import pytest

from scripts.materialize_propertyquarry_walkthrough_provider_proof import _source_sidecar, _validate_source


def test_validate_source_accepts_completed_magicfit_composite() -> None:
    _validate_source(
        "magicfit",
        {
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "status": "rendered",
            "render_status": "completed",
            "composition": "boundary_verified_frame_continuation",
            "segment_count": 5,
            "route_labels": ["living", "kitchen"],
            "covered_route_labels": ["living", "kitchen"],
            "full_decode_verified": True,
        },
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


def test_magicfit_sidecar_preserves_declared_transition_timing(tmp_path: Path) -> None:
    source_receipt = tmp_path / "source.json"
    source_receipt.write_text("{}\n", encoding="utf-8")

    sidecar = _source_sidecar(
        provider="magicfit",
        source={
            "composition": "boundary_verified_frame_continuation",
            "segment_count": 2,
            "route_labels": ["living", "kitchen"],
            "covered_route_labels": ["living", "kitchen"],
            "required_duration_seconds": 25.0,
            "boundary_checks": [{"status": "pass"}],
            "transition_offsets_seconds": [14.093],
            "transition_seconds": 1.0,
            "continuity_repair_status": "pass",
            "output_frame_rate": "60",
            "source_frame_rates": ["60/1", "60/1"],
            "native_source_frame_rates": ["24/1", "24/1"],
            "motion_interpolation_status": "pass",
            "video_sha256": "abc",
        },
        video_relpath="walkthrough.mp4",
        source_receipt_path=source_receipt,
        metadata={"duration_seconds": 29.186, "width": 1920, "height": 1080, "size_bytes": 123},
    )

    assert sidecar["transition_offsets_seconds"] == [14.093]
    assert sidecar["transition_seconds"] == 1.0
    assert sidecar["continuity_repair_status"] == "pass"
    assert sidecar["output_frame_rate"] == "60"
    assert sidecar["native_source_frame_rates"] == ["24/1", "24/1"]
    assert sidecar["motion_interpolation_status"] == "pass"
