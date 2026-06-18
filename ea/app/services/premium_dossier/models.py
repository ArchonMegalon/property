from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind


RendererName = Literal["markupgo", "playwright", "legacy"]


@dataclass(frozen=True)
class PremiumFactCard:
    label: str
    value: str
    confidence: str = ""
    source: str = ""


@dataclass(frozen=True)
class PremiumDossierCompileResult:
    title: str
    recommended_title: str
    packet_kind: PropertyPacketKind
    privacy_mode: PacketPrivacyMode
    fliplink_format: FlipLinkFormat
    redacted_payload: dict[str, object]
    fact_cards: list[PremiumFactCard] = field(default_factory=list)
    why_match: list[str] = field(default_factory=list)
    why_fail: list[str] = field(default_factory=list)
    property_narrative: list[str] = field(default_factory=list)
    risk_register: list[str] = field(default_factory=list)
    daily_life: list[str] = field(default_factory=list)
    family_route: list[str] = field(default_factory=list)
    investment_lines: list[str] = field(default_factory=list)
    agent_questions: list[str] = field(default_factory=list)
    provenance_lines: list[str] = field(default_factory=list)
    comparison_rows: list[dict[str, str]] = field(default_factory=list)
    gallery_urls: list[str] = field(default_factory=list)
    floorplan_urls: list[str] = field(default_factory=list)
    visual_story_urls: list[str] = field(default_factory=list)
    detail_gallery_urls: list[str] = field(default_factory=list)
    hero_image_url: str = ""
    portrait_image_url: str = ""
    property_image_url: str = ""
    scene_image_url: str = ""
    diorama_image_url: str = ""
    scene_summary: str = ""
    tour_url: str = ""
    flythrough_url: str = ""
    review_url: str = ""
    map_url: str = ""
    fit_summary: str = ""
    recommendation: str = ""
    confidence_label: str = ""
    next_action: str = ""
    compare_reason: str = ""
    editorial_sections: list[dict[str, object]] = field(default_factory=list)
    neuronwriter_status: str = ""
    neuronwriter_reason: str = ""
    neuronwriter_share_url: str = ""
    neuronwriter_questions: list[str] = field(default_factory=list)
    appendix_mode: str = ""
    source_pdf_filename: str = ""
    appendix_research_lines: list[str] = field(default_factory=list)
    renderer_version: str = ""


@dataclass(frozen=True)
class PremiumDossierRenderRequest:
    dossier_id: str
    renderer_version: str
    html: str
    title: str
    privacy_mode: str
    packet_kind: str
    metadata: dict[str, object] = field(default_factory=dict)
    expected_text: list[str] = field(default_factory=list)
    forbidden_text: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PremiumDossierRenderResult:
    status: Literal["rendered", "failed", "fallback_rendered"]
    renderer: RendererName
    pdf_bytes: bytes = b""
    pdf_sha256: str = ""
    render_seconds: float = 0.0
    provider_task_id: str = ""
    page_count: int | None = None
    error_code: str = ""
    error_detail: str = ""


@dataclass(frozen=True)
class PremiumDossierQualityReport:
    ok: bool
    required_text_check: str
    forbidden_text_check: str
    page_count: int = 0
    visual_preview_check: str = "not_run"
    cover_dominance_check: str = "not_run"
    footer_band_check: str = "not_run"
    raw_url_text_check: str = "not_run"
    visual_preview_artifact_ref: str = ""
    first_page_width_px: int = 0
    first_page_height_px: int = 0
    first_page_nonwhite_ratio: float = 0.0
    first_page_top_band_nonwhite_ratio: float = 0.0
    first_page_footer_band_nonwhite_ratio: float = 0.0
    required_text_hits: list[str] = field(default_factory=list)
    forbidden_text_hits: list[str] = field(default_factory=list)
    raw_url_text_hits: list[str] = field(default_factory=list)
