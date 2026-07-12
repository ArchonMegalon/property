import json
from pathlib import Path

from PIL import Image

from scripts.compose_magicfit_property_walkthrough import (
    _normalized_rmse,
    _validate_segment_receipt,
    build_xfade_filter,
    route_coverage_from_receipt,
)


def test_build_xfade_filter_calculates_offsets_and_duration() -> None:
    graph, final_label, duration, offsets = build_xfade_filter(
        [15.0, 15.0, 15.0],
        1.0,
        output_fps=24.0,
    )

    assert final_label == "x2"
    assert duration == 43.0
    assert offsets == [14.0, 28.0]
    assert "fps=24" in graph
    assert "offset=14.000[x1]" in graph
    assert "offset=28.000[x2]" in graph


def test_route_coverage_requires_matching_passed_room_lists() -> None:
    receipt = {
        "checks": [
            {
                "name": "walkthrough_room_coverage_complete",
                "ok": True,
                "coverage": {
                    "status": "pass",
                    "rooms_expected": ["living", "kitchen"],
                    "rooms_visited": ["living", "kitchen"],
                },
            }
        ]
    }

    assert route_coverage_from_receipt(receipt) == (["living", "kitchen"], ["living", "kitchen"])


def test_normalized_rmse_has_no_imagemagick_runtime_dependency(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(left)
    Image.new("RGB", (4, 4), (255, 255, 255)).save(right)

    assert _normalized_rmse(left, left) == 0.0
    assert _normalized_rmse(left, right) == 1.0


def test_composer_accepts_hash_bound_motion_interpolated_segment_receipt(tmp_path: Path) -> None:
    segment = tmp_path / "segment-60fps.mp4"
    segment.write_bytes(b"video")
    source_receipt = tmp_path / "source.json"
    source_receipt.write_text(
        json.dumps(
            {
                "page_url": "https://magicfit.example/session/1",
                "continuity_repair_status": "pass",
                "continuity_repair_method": "verified_internal_hard_cut_crossfade",
                "continuity_repair_cut_seconds": [11.7],
                "continuity_repair_transition_offsets_seconds": [10.7],
            }
        ),
        encoding="utf-8",
    )
    delivery_receipt = tmp_path / "delivery.json"
    delivery_receipt.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.walkthrough_delivery_variants.v1",
                "status": "pass",
                "source_receipt_path": str(source_receipt),
                "source_provider_session_url": "https://magicfit.example/session/1",
                "source_metadata": {"avg_frame_rate": "24/1"},
                "continuity_repair_status": "pass",
                "continuity_repair_method": "verified_internal_hard_cut_crossfade",
                "continuity_repair_cut_seconds": [11.7],
                "continuity_repair_transition_offsets_seconds": [10.7],
                "variants": [
                    {
                        "path": str(segment),
                        "full_decode_verified": True,
                        "motion_interpolation_verified": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    receipt = _validate_segment_receipt(delivery_receipt, segment)

    assert receipt["provider_key"] == "magicfit"
    assert receipt["motion_interpolation_verified"] is True
    assert receipt["source_native_frame_rate"] == "24/1"
    assert receipt["continuity_repair_transition_offsets_seconds"] == [10.7]
