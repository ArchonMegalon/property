from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.property_media_factory import (
    MediaRequirement,
    ProviderCapability,
    route_property_media_task,
)


def test_walkthrough_with_start_frame_continuity_routes_to_magicfit() -> None:
    route = route_property_media_task(
        MediaRequirement(
            task="walkthrough_video",
            first_frame_continuity=True,
            constant_speed=True,
        )
    )

    assert route.ok
    assert route.provider_key == "magicfit"
    assert route.role == "photoreal_walkthrough_segment_chain"


def test_poppy_ai_is_only_a_research_board_lane_until_verified() -> None:
    unverified_route = route_property_media_task(MediaRequirement(task="research_board"))
    permissive_route = route_property_media_task(
        MediaRequirement(task="research_board", provider_verified=False)
    )

    assert not unverified_route.ok
    assert unverified_route.reason == "no_verified_provider_matches_requirements"
    assert permissive_route.provider_key == "poppy_ai"
    assert permissive_route.role == "research_board"


def test_magicfit_is_final_continuity_publisher() -> None:
    still_route = route_property_media_task(MediaRequirement(task="interior_still"))
    final_route = route_property_media_task(
        MediaRequirement(
            task="walkthrough_video",
            first_frame_continuity=True,
            constant_speed=True,
            must_be_magicfit=True,
        )
    )

    assert still_route.provider_key == "magicfit"
    assert final_route.ok
    assert final_route.provider_key == "magicfit"


def test_unverified_video_providers_fail_closed_for_final_walkthrough() -> None:
    providers = (
        ProviderCapability(
            provider_key="candidate_video",
            role="unverified_video",
            verified=False,
            tasks=("walkthrough_video",),
            supports_first_frame=True,
            supports_constant_speed_publication=True,
            final_publisher=True,
        ),
    )

    route = route_property_media_task(
        MediaRequirement(
            task="walkthrough_video",
            first_frame_continuity=True,
            constant_speed=True,
        ),
        providers=providers,
    )

    assert not route.ok
    assert route.reason == "no_verified_provider_matches_requirements"


def _load_onemin_segment_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "render_onemin_property_i2v_segment.py"
    spec = importlib.util.spec_from_file_location("render_onemin_property_i2v_segment", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_onemin_video_url_extraction_accepts_nested_relative_result_path() -> None:
    module = _load_onemin_segment_module()

    payload = {
        "aiRecord": {
            "aiRecordDetail": {
                "resultObject": ["development/videos/property_walkthrough.mp4"],
                "responseObject": {"status": "SUCCESS"},
            }
        }
    }

    assert module.choose_video_url(payload) == "https://api.1min.ai/development/videos/property_walkthrough.mp4"


def test_onemin_i2v_request_supports_fast_video_fallback_models(monkeypatch) -> None:
    module = _load_onemin_segment_module()
    observed: list[dict[str, object]] = []

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"aiRecord": {"aiRecordDetail": {"resultObject": ["https://cdn.example/out.mp4"]}}}

    def _fake_post(url, headers, json, timeout):  # noqa: ANN001
        observed.append(dict(json))
        return _Response()

    monkeypatch.setattr(module.requests, "post", _fake_post)

    module.request_i2v(
        api_key="test-key",
        image_url="images/test.jpg",
        prompt="continuous one-shot apartment walkthrough",
        duration=10,
        model="pika",
        timeout_seconds=15,
    )
    module.request_i2v(
        api_key="test-key",
        image_url="images/test.jpg",
        prompt="continuous one-shot apartment walkthrough",
        duration=10,
        model="skyreels",
        timeout_seconds=15,
    )

    assert observed[0]["model"] == "pika"
    assert observed[0]["promptObject"]["task_type"] == "pika-v2.2"
    assert observed[1]["model"] == "Qubico/skyreels"
    assert observed[1]["promptObject"]["aspect_ratio"] == "16:9"
