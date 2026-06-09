from __future__ import annotations

from typing import Any

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import (
    _comparison_rows,
    _confidence_label,
    _display_number,
    _display_price,
    _fallback_match_reasons,
    _fallback_questions,
    _fallback_risks,
    _joined,
    _money_phrase,
    _property_narrative,
    _recommendation_label,
    _resolve_pdf_flythrough_url,
    _resolve_pdf_primary_tour_url,
    _resolve_pdf_review_url,
    _text_items,
)
from app.services.premium_dossier.models import PremiumDossierCompileResult, PremiumFactCard


def _safe_lines(value: object, *, limit: int = 8) -> list[str]:
    return [str(item or "").strip() for item in list(value or [])[:limit] if str(item or "").strip()]


def _fact_cards(payload: dict[str, object]) -> list[PremiumFactCard]:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    rows = [
        PremiumFactCard("Preis", _display_price(facts.get("price") or payload.get("price")) or "Auf Anfrage"),
        PremiumFactCard("Fläche", _display_number(facts.get("area_sqm") or facts.get("living_area_sqm"), suffix=" m²") or "Unklar"),
        PremiumFactCard("Zimmer", str(facts.get("rooms") or payload.get("rooms") or "").strip() or "Unklar"),
        PremiumFactCard("Heizung", str(facts.get("heating") or facts.get("heating_type") or "").strip() or "Unklar"),
        PremiumFactCard("Lift", "Ja" if facts.get("lift") or facts.get("has_lift") else "Nicht bestätigt"),
        PremiumFactCard("Energie", str(facts.get("epc") or facts.get("energy_certificate") or "").strip() or "Offen"),
        PremiumFactCard("Betriebskosten", _money_phrase(facts.get("operating_costs_monthly") or facts.get("operating_costs")) or "Offen"),
        PremiumFactCard("ÖV", str(facts.get("nearest_tram_bus_label") or facts.get("nearest_transit_label") or "").strip() or "Siehe Lageprofil"),
    ]
    return [row for row in rows if row.value]


def compile_premium_dossier(
    *,
    source: dict[str, object],
    redacted_payload: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    renderer_version: str,
) -> PremiumDossierCompileResult:
    facts = dict(redacted_payload.get("facts") or {}) if isinstance(redacted_payload.get("facts"), dict) else {}
    title = str(redacted_payload.get("title") or source.get("title") or "PropertyQuarry dossier").strip() or "PropertyQuarry dossier"
    recommended_title = f"{title} - {packet_kind.value.replace('_', ' ').title()}"
    why_match = _safe_lines(redacted_payload.get("match_reasons")) or _fallback_match_reasons(facts)
    why_fail = _safe_lines(redacted_payload.get("mismatch_reasons"))
    risk_register = _safe_lines(redacted_payload.get("risk_lines"), limit=10) or _fallback_risks(facts)
    daily_life = _safe_lines(redacted_payload.get("daily_life_lines"), limit=10)
    family_route = _safe_lines(redacted_payload.get("family_route_lines"), limit=8)
    investment_lines = _safe_lines(redacted_payload.get("investment_lines"), limit=8)
    agent_questions = _safe_lines(redacted_payload.get("agent_questions"), limit=8) or _fallback_questions(facts)
    provenance_lines = _safe_lines(redacted_payload.get("provenance_lines"), limit=10)
    photo_refs = _text_items(redacted_payload.get("photo_refs"), limit=12)
    floorplan_refs = _text_items(redacted_payload.get("floorplan_refs"), limit=4)
    magic_fit_scene = dict(redacted_payload.get("magic_fit_scene") or {}) if isinstance(redacted_payload.get("magic_fit_scene"), dict) else {}
    magic_fit_image_url = str(magic_fit_scene.get("image_url") or "").strip()
    hero_image_url = magic_fit_image_url or (photo_refs[0] if photo_refs else (floorplan_refs[0] if floorplan_refs else ""))
    recommendation = _recommendation_label(redacted_payload.get("recommendation"))
    compare_rows = _comparison_rows(redacted_payload.get("comparison_rows"))
    compare_reason = str(redacted_payload.get("compare_reason") or (compare_rows[0].get("compare_reason") if compare_rows else "") or "").strip()
    property_narrative = _property_narrative(redacted_payload)
    return PremiumDossierCompileResult(
        title=title,
        recommended_title=recommended_title,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        redacted_payload=redacted_payload,
        fact_cards=_fact_cards(redacted_payload),
        why_match=why_match,
        why_fail=why_fail,
        property_narrative=property_narrative,
        risk_register=risk_register,
        daily_life=daily_life,
        family_route=family_route,
        investment_lines=investment_lines,
        agent_questions=agent_questions,
        provenance_lines=provenance_lines,
        comparison_rows=compare_rows,
        gallery_urls=photo_refs,
        floorplan_urls=floorplan_refs,
        hero_image_url=hero_image_url,
        tour_url=_resolve_pdf_primary_tour_url(source=source, payload=redacted_payload),
        flythrough_url=_resolve_pdf_flythrough_url(source=source, payload=redacted_payload),
        review_url=_resolve_pdf_review_url(source=source, payload=redacted_payload),
        fit_summary=str(redacted_payload.get("fit_summary") or redacted_payload.get("recommendation") or "").strip(),
        recommendation=recommendation,
        confidence_label=_confidence_label(risk_lines=risk_register, match_reasons=why_match, mismatch_reasons=why_fail),
        next_action=str(redacted_payload.get("next_action") or "").strip(),
        compare_reason=compare_reason,
        renderer_version=renderer_version,
    )
