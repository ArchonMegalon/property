from __future__ import annotations

import re
import urllib.parse
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


def _dedupe_urls(*collections: object) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for collection in collections:
        for item in list(collection or []):
            url = str(item or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append(url)
    return rows


def _writer_payload(payload: dict[str, object]) -> dict[str, object]:
    return dict(payload.get("dossier_writer") or {}) if isinstance(payload.get("dossier_writer"), dict) else {}


def _editorial_sections(payload: dict[str, object]) -> list[dict[str, object]]:
    writer = _writer_payload(payload)
    rows = list(writer.get("sections") or []) if isinstance(writer.get("sections"), list) else []
    sections: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("section_key") or "").strip()
        body = str(row.get("body_markdown") or "").strip()
        bullets = _safe_lines(row.get("bullets"), limit=5)
        cta = str(row.get("cta") or "").strip()
        if not title or not (body or bullets or cta):
            continue
        sections.append(
            {
                "title": title,
                "body": body,
                "bullets": bullets,
                "cta": cta,
                "section_key": str(row.get("section_key") or "").strip(),
            }
        )
    return sections


def _writer_neuronwriter(payload: dict[str, object]) -> dict[str, object]:
    writer = _writer_payload(payload)
    return dict(writer.get("neuronwriter") or {}) if isinstance(writer.get("neuronwriter"), dict) else {}


def _appendix_research_lines(
    *,
    source: dict[str, object],
    redacted_payload: dict[str, object],
    facts: dict[str, object],
    editorial_sections: list[dict[str, object]],
    risk_register: list[str],
) -> list[str]:
    rows: list[str] = []
    for section in editorial_sections[:4]:
        body = str(section.get("body") or "").strip()
        if body:
            rows.append(body)
        for bullet in _safe_lines(section.get("bullets"), limit=2):
            rows.append(bullet)
        if len(rows) >= 8:
            break

    fact_sources: list[dict[str, object]] = [facts]
    for payload in (redacted_payload, source):
        if isinstance(payload.get("property_facts_json"), dict):
            fact_sources.append(dict(payload.get("property_facts_json") or {}))
        if isinstance(payload.get("facts"), dict):
            fact_sources.append(dict(payload.get("facts") or {}))
    for fact_source in fact_sources:
        missing_research = dict(fact_source.get("missing_fact_research") or {}) if isinstance(fact_source.get("missing_fact_research"), dict) else {}
        for item in list(missing_research.get("items") or [])[:3]:
            if not isinstance(item, dict):
                continue
            row = " - ".join(
                part
                for part in (
                    str(item.get("label") or item.get("field") or "Research item").strip(),
                    str(item.get("status") or "").strip().replace("_", " "),
                    str(item.get("evidence") or item.get("display_value") or "").strip(),
                )
                if part
            )
            if row:
                rows.append(row)
        if len(rows) >= 8:
            break

    if not rows:
        rows.extend(risk_register[:4])
    deduped = list(dict.fromkeys([row for row in rows if str(row or "").strip()]))
    return deduped[:8] or [
        "Deep research did not expose a decisive additional fact yet; verify operating costs, floorplan logic, and legal or energy documents manually."
    ]


def _visual_story(payload: dict[str, object], *, photo_refs: list[str], floorplan_refs: list[str]) -> dict[str, object]:
    magic_fit_scene = dict(payload.get("magic_fit_scene") or {}) if isinstance(payload.get("magic_fit_scene"), dict) else {}
    diorama_scene = dict(payload.get("diorama_scene") or {}) if isinstance(payload.get("diorama_scene"), dict) else {}
    scene_image_url = str(magic_fit_scene.get("image_url") or "").strip()
    diorama_image_url = str(diorama_scene.get("image_url") or "").strip()
    scene_summary = str(magic_fit_scene.get("summary") or diorama_scene.get("summary") or "").strip()
    visual_story_urls = _dedupe_urls(
        [scene_image_url],
        [diorama_image_url],
        photo_refs,
        floorplan_refs,
    )
    hero_image_url = next(iter(visual_story_urls), "")
    portrait_image_url = next(iter(visual_story_urls), "")
    property_image_url = next(
        (
            url
            for url in [*photo_refs, *floorplan_refs]
            if url and url != portrait_image_url
        ),
        "",
    )
    detail_gallery_urls = [
        url
        for url in visual_story_urls
        if url and url not in {portrait_image_url, property_image_url}
    ]
    return {
        "scene_image_url": scene_image_url,
        "diorama_image_url": diorama_image_url,
        "scene_summary": scene_summary,
        "visual_story_urls": visual_story_urls,
        "hero_image_url": hero_image_url,
        "portrait_image_url": portrait_image_url,
        "property_image_url": property_image_url or portrait_image_url,
        "detail_gallery_urls": detail_gallery_urls,
    }


def _google_maps_url(payload: dict[str, object]) -> str:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    if isinstance(payload.get("property_facts"), dict):
        facts = {**facts, **dict(payload.get("property_facts") or {})}
    snapshot = dict(facts.get("listing_research_snapshot") or {}) if isinstance(facts.get("listing_research_snapshot"), dict) else {}
    if snapshot:
        merged = {**snapshot, **facts}

        def _normalized(value: object) -> str:
            return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

        source_scope_location = str(facts.get("source_scope_location") or merged.get("source_scope_location") or "").strip()
        source_city = str(facts.get("source_city") or merged.get("source_city") or "").strip()
        source_postal_code = str(facts.get("source_postal_code") or merged.get("source_postal_code") or "").strip()
        source_scope_candidates = {
            _normalized(source_scope_location),
            _normalized(source_city),
        }
        if source_postal_code and source_city:
            source_scope_candidates.add(_normalized(f"{source_postal_code} {source_city}"))
        source_scope_candidates.discard("")

        for key in ("district", "location", "postal_name", "address", "street_address", "exact_address", "city"):
            snapshot_value = str(snapshot.get(key) or "").strip()
            top_value = str(facts.get(key) or "").strip()
            if snapshot_value and (
                not top_value
                or _normalized(top_value) in source_scope_candidates
            ):
                merged[key] = snapshot_value
        facts = merged

    def _text(*values: object) -> str:
        return next((str(value or "").strip() for value in values if str(value or "").strip()), "")

    lat = _text(facts.get("map_lat"), facts.get("lat"), facts.get("latitude"))
    lng = _text(facts.get("map_lng"), facts.get("lng"), facts.get("lon"), facts.get("longitude"))
    if lat and lng:
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(f'{lat},{lng}', safe=',')}"
    address_lines = " ".join(str(item or "").strip() for item in list(facts.get("address_lines") or []) if str(item or "").strip())
    query = _text(
        facts.get("exact_address"),
        facts.get("street_address"),
        facts.get("address"),
        address_lines,
        facts.get("postal_name"),
        facts.get("location"),
        payload.get("title"),
    )
    if not query:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


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
    editorial_sections = _editorial_sections(redacted_payload)
    neuronwriter = _writer_neuronwriter(redacted_payload)
    visual_story = _visual_story(redacted_payload, photo_refs=photo_refs, floorplan_refs=floorplan_refs)
    if editorial_sections:
        editorial_match = next((row for row in editorial_sections if str(row.get("section_key") or "").strip() == "evidence_summary"), None)
        editorial_risk = next((row for row in editorial_sections if str(row.get("section_key") or "").strip() == "risk_register"), None)
        editorial_daily_life = next((row for row in editorial_sections if str(row.get("section_key") or "").strip() == "daily_life_radius"), None)
        editorial_questions = next((row for row in editorial_sections if str(row.get("section_key") or "").strip() == "agent_questions"), None)
        why_match = _safe_lines((editorial_match or {}).get("bullets"), limit=6) or why_match
        risk_register = _safe_lines((editorial_risk or {}).get("bullets"), limit=8) or risk_register
        daily_life = _safe_lines((editorial_daily_life or {}).get("bullets"), limit=8) or daily_life
        agent_questions = _safe_lines((editorial_questions or {}).get("bullets"), limit=8) or agent_questions
    recommendation = _recommendation_label(redacted_payload.get("recommendation"))
    compare_rows = _comparison_rows(redacted_payload.get("comparison_rows"))
    compare_reason = str(redacted_payload.get("compare_reason") or (compare_rows[0].get("compare_reason") if compare_rows else "") or "").strip()
    property_narrative = [
        *[
            str(row.get("body") or "").strip()
            for row in editorial_sections[:3]
            if str(row.get("body") or "").strip()
        ],
        *_property_narrative(redacted_payload),
    ]
    property_narrative = list(dict.fromkeys([line for line in property_narrative if line]))[:5]
    appendix_mode = str(redacted_payload.get("appendix_mode") or source.get("appendix_mode") or "").strip().lower()
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
        visual_story_urls=list(visual_story["visual_story_urls"]),
        detail_gallery_urls=list(visual_story["detail_gallery_urls"]),
        hero_image_url=str(visual_story["hero_image_url"]),
        portrait_image_url=str(visual_story["portrait_image_url"]),
        property_image_url=str(visual_story["property_image_url"]),
        scene_image_url=str(visual_story["scene_image_url"]),
        diorama_image_url=str(visual_story["diorama_image_url"]),
        scene_summary=str(visual_story["scene_summary"]),
        tour_url=_resolve_pdf_primary_tour_url(source=source, payload=redacted_payload),
        flythrough_url=_resolve_pdf_flythrough_url(source=source, payload=redacted_payload),
        review_url=_resolve_pdf_review_url(source=source, payload=redacted_payload),
        map_url=str(redacted_payload.get("map_url") or source.get("map_url") or _google_maps_url(redacted_payload) or _google_maps_url(source)).strip(),
        fit_summary=str(redacted_payload.get("fit_summary") or redacted_payload.get("recommendation") or "").strip(),
        recommendation=recommendation,
        confidence_label=_confidence_label(risk_lines=risk_register, match_reasons=why_match, mismatch_reasons=why_fail),
        next_action=str(redacted_payload.get("next_action") or "").strip(),
        compare_reason=compare_reason,
        editorial_sections=editorial_sections,
        neuronwriter_status=str(neuronwriter.get("status") or "").strip(),
        neuronwriter_reason=str(neuronwriter.get("reason") or "").strip(),
        neuronwriter_share_url=str(neuronwriter.get("share_url") or neuronwriter.get("readonly_url") or "").strip(),
        neuronwriter_questions=_safe_lines(neuronwriter.get("questions"), limit=5),
        appendix_mode=appendix_mode,
        source_pdf_filename=str(redacted_payload.get("source_pdf_filename") or source.get("source_pdf_filename") or "").strip(),
        appendix_research_lines=_appendix_research_lines(
            source=source,
            redacted_payload=redacted_payload,
            facts=facts,
            editorial_sections=editorial_sections,
            risk_register=risk_register,
        )
        if appendix_mode.endswith("appendix")
        else [],
        renderer_version=renderer_version,
    )
