from __future__ import annotations

from pathlib import Path

from scripts.propertyquarry_magicfit_native_continuity_gate import (
    build_native_continuity_receipt,
)


def _render_receipt() -> dict[str, object]:
    return {
        "provider_key": "magicfit",
        "provider_backend_key": "magicfit",
        "render_status": "completed",
        "provider_operation": "native_video_extend",
        "composition": "provider_native_cumulative_extension",
        "postproduction_edit_count": 0,
        "output_contract_ok": True,
        "duration_seconds_magicfit": 10,
        "native_extend_source_proof": {
            "status": "pass",
            "source_metadata": {"duration_seconds": 10.0},
        },
        "native_extend_prefix_proof": {
            "status": "pass",
            "maximum_perceptual_normalized_rmse": 0.02,
            "perceptual_rmse_limit": 0.08,
        },
    }


def test_native_continuity_gate_passes_complete_smooth_provider_evidence(tmp_path: Path) -> None:
    render_path = tmp_path / "render.json"
    output_path = tmp_path / "output.mp4"
    render_path.write_text("{}", encoding="utf-8")
    output_path.write_bytes(b"video")

    receipt = build_native_continuity_receipt(
        render_receipt=_render_receipt(),
        render_receipt_path=render_path,
        output_path=output_path,
        output_metadata={"duration_seconds": 20.05},
        delta_stats={
            "ok": True,
            "max_delta": 7.9,
            "transition_boundary_samples": [{"delta": 4.2}],
        },
        max_jump_delta=18.0,
        full_decode_verified=True,
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0


def test_native_continuity_gate_rejects_edits_and_visible_jump(tmp_path: Path) -> None:
    render_path = tmp_path / "render.json"
    output_path = tmp_path / "output.mp4"
    render_path.write_text("{}", encoding="utf-8")
    output_path.write_bytes(b"video")
    render = _render_receipt()
    render["postproduction_edit_count"] = 1

    receipt = build_native_continuity_receipt(
        render_receipt=render,
        render_receipt_path=render_path,
        output_path=output_path,
        output_metadata={"duration_seconds": 20.05},
        delta_stats={
            "ok": True,
            "max_delta": 68.6,
            "transition_boundary_samples": [{"delta": 41.0}],
        },
        max_jump_delta=18.0,
        full_decode_verified=True,
    )

    assert receipt["status"] == "fail"
    assert "postproduction_edits_absent" in receipt["failures"]
    assert "global_frame_jump_limit" in receipt["failures"]
    assert "native_join_frame_jump_limit" in receipt["failures"]
