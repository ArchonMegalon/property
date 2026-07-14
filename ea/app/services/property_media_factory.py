from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class MediaRequirement:
    task: str
    first_frame_continuity: bool = False
    constant_speed: bool = False
    provider_verified: bool = True
    preferred_provider_key: str = ""
    require_final_publisher: bool = True


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


def _normalize_provider_preference(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    normalized = normalized.replace(" ", "_")
    if not normalized:
        return ""
    alias_map = {
        "magic": "omagic",
        "omagic": "omagic",
        "mootion": "mootion",
        "magicfit": "magicfit",
        "onemin": "onemin_i2v",
        "onemin_i2v": "onemin_i2v",
    }
    return alias_map.get(normalized, normalized)


DEFAULT_PROPERTY_MEDIA_PROVIDERS: tuple[ProviderCapability, ...] = (
    ProviderCapability(
        provider_key="omagic",
        role="model_upload_walkthrough",
        verified=True,
        tasks=("walkthrough_video", "video_segment", "model_walkthrough_video"),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=True,
        reason="OMagic is the preferred model-backed walkthrough lane; publication requires a model upload receipt and continuity gates.",
    ),
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
        reason="MagicFit is the photoreal segment-chain fallback; publication is allowed only after first-frame chaining, duration, and continuity gates pass.",
    ),
    ProviderCapability(
        provider_key="mootion",
        role="image_to_video_walkthrough",
        verified=True,
        tasks=("walkthrough_video", "video_segment"),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=False,
        reason="Legacy image-to-video lane exposed through the mootion alias; publication remains off.",
    ),
    ProviderCapability(
        provider_key="onemin_i2v",
        role="image_to_video_walkthrough",
        verified=True,
        tasks=("walkthrough_video", "video_segment"),
        supports_first_frame=True,
        supports_constant_speed_publication=True,
        final_publisher=True,
        reason="1min.AI is the governed final-publication fallback when OMagic and MagicFit are unavailable; publication still requires duration, continuity, and room-coverage gates.",
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
    ordered_keys = tuple(provider.provider_key for provider in candidates)
    preferred_provider_key = _normalize_provider_preference(requirement.preferred_provider_key)
    if preferred_provider_key:
        candidates = [provider for provider in candidates if provider.provider_key == preferred_provider_key]
        if not candidates:
            return MediaRoute(
                status="blocked",
                reason="no_candidate_matches_preferred_provider",
                candidates=ordered_keys,
            )
    if requirement.first_frame_continuity:
        candidates = [provider for provider in candidates if provider.supports_first_frame]
    if requirement.constant_speed:
        candidates = [provider for provider in candidates if provider.supports_constant_speed_publication]

    if not candidates:
        return MediaRoute(
            status="blocked",
            reason="no_verified_provider_matches_requirements",
            candidates=ordered_keys,
        )

    final_candidates = [provider for provider in candidates if provider.final_publisher]
    if task == "walkthrough_video" and not preferred_provider_key:
        final_provider_order = {
            "magicfit": 0,
            "omagic": 1,
            "onemin_i2v": 2,
        }
        final_candidates.sort(key=lambda provider: final_provider_order.get(provider.provider_key, 99))
    selected = final_candidates[0] if final_candidates else candidates[0]
    if (
        requirement.require_final_publisher
        and (requirement.first_frame_continuity or requirement.constant_speed)
        and not selected.final_publisher
    ):
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
