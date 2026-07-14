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


def test_magicfit_is_default_final_continuity_publisher() -> None:
    still_route = route_property_media_task(MediaRequirement(task="interior_still"))
    final_route = route_property_media_task(
        MediaRequirement(task="walkthrough_video", first_frame_continuity=True, constant_speed=True)
    )

    assert still_route.provider_key == "magicfit"
    assert final_route.ok
    assert final_route.provider_key == "magicfit"


def test_omagic_aliases_select_omagic_lane() -> None:
    for provider_key in ("magic", "omagic"):
        route = route_property_media_task(MediaRequirement(task="walkthrough_video", preferred_provider_key=provider_key))

        assert route.ok
        assert route.provider_key == "omagic"


def test_walkthrough_provider_mootion_preference_stays_mootion() -> None:
    route = route_property_media_task(MediaRequirement(task="walkthrough_video", preferred_provider_key="mootion"))

    assert route.ok
    assert route.provider_key == "mootion"


def test_legacy_onemin_aliases_select_internal_i2v_lane() -> None:
    for provider_key in ("onemin", "onemin_i2v"):
        route = route_property_media_task(MediaRequirement(task="walkthrough_video", preferred_provider_key=provider_key))

        assert route.ok
        assert route.provider_key == "onemin_i2v"


def test_onemin_can_publish_final_walkthrough_when_selected() -> None:
    route = route_property_media_task(
        MediaRequirement(
            task="walkthrough_video",
            preferred_provider_key="onemin_i2v",
            first_frame_continuity=True,
            constant_speed=True,
        )
    )

    assert route.ok
    assert route.provider_key == "onemin_i2v"


def test_magicfit_preference_stays_magicfit() -> None:
    route = route_property_media_task(MediaRequirement(task="walkthrough_video", preferred_provider_key="magicfit"))

    assert route.ok
    assert route.provider_key == "magicfit"


def test_unknown_walkthrough_provider_is_rejected() -> None:
    route = route_property_media_task(MediaRequirement(task="walkthrough_video", preferred_provider_key="does_not_exist"))

    assert not route.ok
    assert route.reason == "no_candidate_matches_preferred_provider"


def test_lived_in_staging_routes_to_photoreal_magicfit_not_local_geometry() -> None:
    staged_route = route_property_media_task(
        MediaRequirement(
            task="staged_lived_in_tour",
            first_frame_continuity=True,
            constant_speed=True,
        )
    )
    geometry_route = route_property_media_task(MediaRequirement(task="geometry_reference"))

    assert staged_route.ok
    assert staged_route.provider_key == "magicfit"
    assert staged_route.role == "photoreal_walkthrough_segment_chain"
    assert geometry_route.provider_key == "local_true_one_take"
    assert geometry_route.role == "technical_fallback_renderer"


def test_lived_in_staging_prompt_rejects_cgi_showroom_language() -> None:
    from app.product import service as product_service

    prompt = product_service._default_magicfit_property_flythrough_prompt(
        title="Family flat with balcony",
        property_facts={"room_count": 3, "city": "Vienna", "area_sqm": 72},
        room_count=3,
        room_visit_plan=["entry", "living room", "kitchen", "bedroom", "bathroom", "balcony"],
    )

    assert "photoreal staging render" in prompt
    assert "not a Blender preview" in prompt
    assert "not a game engine" in prompt
    assert "not an empty showroom" in prompt


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
