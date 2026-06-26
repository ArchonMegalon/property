from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class MediaRequirement:
    task: str
    first_frame_continuity: bool = False
    constant_speed: bool = False
    provider_verified: bool = True
    must_be_magicfit: bool = False


@dataclass(frozen=True)
class ProviderCapability:
    provider_key: str
    role: str
    verified: bool
    tasks: tuple[str, ...]
    supports_first_frame: bool = False
    supports_constant_speed_publication: bool = False
    final_publisher: bool = False
    reason: str = ""


@dataclass(frozen=True)
class MediaRoute:
    status: str
    provider_key: str = ""
    role: str = ""
    reason: str = ""
    candidates: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "selected" and bool(self.provider_key)


DEFAULT_PROPERTY_MEDIA_PROVIDERS: tuple[ProviderCapability, ...] = (
    ProviderCapability(
        provider_key="magicfit",
        role="photoreal_walkthrough_segment_chain",
        verified=True,
        tasks=(
            "walkthrough_video",
            "video_segment",
            "interior_still",
            "staged_lived_in_tour",
            "staged_lived_in_still",
            "style_reference",
            "short_video_segment",
        ),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=True,
        reason="MagicFit is the required photoreal fly-through lane; publication is allowed only after first-frame chaining, duration, and continuity gates pass.",
    ),
    ProviderCapability(
        provider_key="onemin_i2v",
        role="image_to_video_walkthrough",
        verified=True,
        tasks=("walkthrough_video", "video_segment"),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=False,
        reason="1min.AI remains an implementation fallback/probe lane, but it is not the final publisher when MagicFit is required.",
    ),
    ProviderCapability(
        provider_key="poppy_ai",
        role="research_board",
        verified=False,
        tasks=("research_board", "briefing", "prompt_board"),
        supports_first_frame=False,
        supports_constant_speed_publication=False,
        final_publisher=False,
        reason="Poppy AI is tracked as a board/research lane until API/chatbot/export proof exists.",
    ),
    ProviderCapability(
        provider_key="local_true_one_take",
        role="technical_fallback_renderer",
        verified=True,
        tasks=("walkthrough_video", "video_segment", "control_reference", "geometry_reference"),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=False,
        reason="Local renderer can prove continuity and constant camera speed, but it is not an LTD provider output.",
    ),
)


def route_property_media_task(
    requirement: MediaRequirement,
    providers: Iterable[ProviderCapability] = DEFAULT_PROPERTY_MEDIA_PROVIDERS,
) -> MediaRoute:
    task = str(requirement.task or "").strip()
    if not task:
        return MediaRoute(status="blocked", reason="media_task_missing")

    candidates = [provider for provider in providers if task in provider.tasks]
    if requirement.provider_verified:
        candidates = [provider for provider in candidates if provider.verified]
    if requirement.must_be_magicfit:
        candidates = [provider for provider in candidates if provider.provider_key == "magicfit"]
    if requirement.first_frame_continuity:
        candidates = [provider for provider in candidates if provider.supports_first_frame]
    if requirement.constant_speed:
        candidates = [provider for provider in candidates if provider.supports_constant_speed_publication]

    ordered_keys = tuple(provider.provider_key for provider in candidates)
    if not candidates:
        return MediaRoute(
            status="blocked",
            reason="no_verified_provider_matches_requirements",
            candidates=ordered_keys,
        )

    final_candidates = [provider for provider in candidates if provider.final_publisher]
    selected = final_candidates[0] if final_candidates else candidates[0]
    if (requirement.first_frame_continuity or requirement.constant_speed) and not selected.final_publisher:
        return MediaRoute(
            status="blocked",
            provider_key=selected.provider_key,
            role=selected.role,
            reason="selected_provider_cannot_publish_final_walkthrough",
            candidates=ordered_keys,
        )
    return MediaRoute(
        status="selected",
        provider_key=selected.provider_key,
        role=selected.role,
        reason=selected.reason,
        candidates=ordered_keys,
    )
