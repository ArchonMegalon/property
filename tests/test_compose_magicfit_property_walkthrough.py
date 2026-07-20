import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import compose_magicfit_property_walkthrough as composer
from scripts.compose_magicfit_property_walkthrough import (
    _normalized_rmse,
    _strict_source_receipt_identity,
    _validate_segment_receipt,
    build_xfade_filter,
    route_coverage_from_receipt,
)
from scripts.property_magicfit_delivery_contract import (
    validate_magicfit_source_receipt,
)


def test_composer_requires_exact_slug_bound_approved_source_receipt_handoff() -> None:
    identity = _strict_source_receipt_identity(
        property_slug="danube-core-home",
        hosted_walkthrough_video_url=(
            "https://media.powlcdn.com/magicfit/danube-core-home.mp4"
        ),
    )

    assert identity == {
        "provider": "magicfit",
        "provider_key": "magicfit",
        "provider_backend_key": "magicfit",
        "render_status": "completed",
        "target_slug": "danube-core-home",
        "hosted_walkthrough_video_url": (
            "https://media.powlcdn.com/magicfit/danube-core-home.mp4"
        ),
    }


@pytest.mark.parametrize(
    ("slug", "hosted_url"),
    (
        ("", "https://media.powlcdn.com/magicfit/home.mp4"),
        ("wrong/slug", "https://media.powlcdn.com/magicfit/home.mp4"),
        ("danube-home", "https://example.test/magicfit/home.mp4"),
        ("danube-home", ""),
    ),
)
def test_composer_fails_closed_without_strict_operator_handoff(
    slug: str,
    hosted_url: str,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="magicfit_strict_source_receipt_handoff_required",
    ):
        _strict_source_receipt_identity(
            property_slug=slug,
            hosted_walkthrough_video_url=hosted_url,
        )


def test_composer_emits_importable_pending_handoff_not_public_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    segments = [tmp_path / "segment-1.mp4", tmp_path / "segment-2.mp4"]
    receipt_paths = [tmp_path / "segment-1.json", tmp_path / "segment-2.json"]
    for index, (segment, receipt_path) in enumerate(
        zip(segments, receipt_paths, strict=True),
        start=1,
    ):
        segment.write_bytes(f"segment-{index}".encode())
        receipt_path.write_text(
            json.dumps(
                {
                    "provider_key": "magicfit",
                    "provider_backend_key": "magicfit",
                    "render_status": "completed",
                    "output_contract_ok": True,
                    "output_file": str(segment),
                    "page_url": f"https://magicfit.example/session/{index}",
                }
            ),
            encoding="utf-8",
        )
    output_path = tmp_path / "composed.mp4"
    state_path = tmp_path / "source-receipt.json"

    def _probe(path: Path) -> dict[str, object]:
        return {
            "duration_seconds": 71.0 if path == output_path else 36.0,
            "width": 1920,
            "height": 1080,
            "size_bytes": max(1, path.stat().st_size if path.exists() else 10),
            "r_frame_rate": "60/1",
            "avg_frame_rate": "60/1",
            "nb_frames": 2160,
        }

    monkeypatch.setattr(composer, "_probe_video", _probe)
    monkeypatch.setattr(composer, "_decode_video", lambda _path: None)
    monkeypatch.setattr(
        composer,
        "_extract_frame",
        lambda _path, _output_path, *, seconds: None,
    )
    monkeypatch.setattr(composer, "_normalized_rmse", lambda _left, _right: 0.0)

    def _run(_command: list[str], **_kwargs: object) -> object:
        output_path.write_bytes(b"verified-composed-video")
        return object()

    monkeypatch.setattr(composer.subprocess, "run", _run)

    payload = composer.compose(
        segments=segments,
        segment_receipts=receipt_paths,
        coverage_receipt_path=None,
        route_labels_override=["living", "kitchen"],
        output_path=output_path,
        state_path=state_path,
        required_duration_seconds=65.0,
        transition_seconds=1.0,
        boundary_rmse_limit=0.2,
        encoder_preset="fast",
        ffmpeg_timeout_seconds=120.0,
        output_fps=60.0,
        property_slug="danube-core-home",
        property_title="Danube Core Home",
        hosted_walkthrough_video_url=(
            "https://media.powlcdn.com/magicfit/danube-core-home.mp4"
        ),
    )

    assert payload["status"] == "source_receipt_ready_for_pending_import"
    assert payload["acceptance_status"] == "pending"
    assert payload["launch_eligible"] is False
    assert payload["operator_handoff_required"] is True
    assert payload["operator_handoff"]["command_argv"] == [
        "python",
        "scripts/import_magicfit_walkthrough.py",
        "--slug",
        "danube-core-home",
        "--video-path",
        str(output_path),
        "--source-receipt",
        str(state_path),
    ]
    assert payload["output_file"] == str(output_path)
    assert "provider_session_url" not in state_path.read_text(encoding="utf-8")
    validate_magicfit_source_receipt(payload, slug="danube-core-home")


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
