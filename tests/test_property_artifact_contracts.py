from __future__ import annotations

from app.services.property_artifact_contracts import property_artifact_provider_lanes, required_artifact_receipt_rows
from app.services.property_media_factory import MediaRequirement, route_property_media_task


def test_property_artifact_provider_matrix_covers_owned_delivery_lanes() -> None:
    lanes = {lane.provider_key: lane for lane in property_artifact_provider_lanes()}

    for required in (
        "matterport",
        "3dvista",
        "magicfit",
        "onemin",
        "jogg",
        "poppy_ai",
        "dadan",
        "neuronwriter",
        "subscribr",
        "pixefy",
        "rafter",
    ):
        assert required in lanes
    assert "cube" not in " ".join(lane.allowed_use.lower() for lane in lanes.values())
    assert "cube fallback" in lanes["matterport"].forbidden_use.lower()
    assert "No name-only route" in lanes["3dvista"].forbidden_use
    assert lanes["magicfit"].role == "Video"
    assert "continuous-shot" in lanes["magicfit"].fail_closed_rule.lower()
    assert "public-safe" in lanes["neuronwriter"].privacy_posture
    assert lanes["subscribr"].role == "Content Studio"
    assert "direct publishing" in lanes["subscribr"].forbidden_use
    assert lanes["pixefy"].role == "Visual QA"
    assert "overflow gates" in lanes["pixefy"].forbidden_use


def test_required_artifact_receipts_forbid_cube_and_bare_links() -> None:
    text = "\n".join(row["detail"] for row in required_artifact_receipt_rows())

    assert "fake cube viewers stay hidden" in text
    assert "titled hyperlink" in text
    assert "must pass visual quality checks before delivery" in text
    assert "receipts" not in text.lower()


def test_property_walkthrough_video_still_routes_to_magicfit_for_final_publication() -> None:
    route = route_property_media_task(
        MediaRequirement(
            task="walkthrough_video",
            first_frame_continuity=True,
            constant_speed=True,
        )
    )

    assert route.ok
    assert route.provider_key == "magicfit"
