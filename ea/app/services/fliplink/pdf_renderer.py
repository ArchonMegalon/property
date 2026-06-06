from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from textwrap import wrap

from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.privacy import REDACTION_POLICY_VERSION, redact_property_packet


PDF_RENDERER_VERSION = "v4_visual_packet_pdf"
PDF_RENDERER_FALLBACK_VERSION = "v3_visual_packet_pdf"
PAGE_WIDTH = 612
PAGE_HEIGHT = 842
MARGIN_X = 44
CARD_WIDTH = PAGE_WIDTH - (MARGIN_X * 2)
Color = tuple[float, float, float]


def _safe_token(value: object, fallback: str = "packet") -> str:
    raw = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return token[:80] or fallback


def _pdf_escape(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_line(value: object, width: int = 92) -> list[str]:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return []
    return wrap(text, width=width, break_long_words=False) or [text]


def _text_items(value: object, *, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value[:limit] if str(item or "").strip()]


def _joined(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item or "").strip() for item in value if str(item or "").strip())
    return str(value or "").strip()


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _rgb(color: Color) -> str:
    return " ".join(_num(max(0.0, min(1.0, value))) for value in color)


def _draw_rect(ops: list[str], x: float, y: float, width: float, height: float, *, fill: Color) -> None:
    ops.append(f"{_rgb(fill)} rg")
    ops.append(f"{_num(x)} {_num(y)} {_num(width)} {_num(height)} re f")


def _draw_text(
    ops: list[str],
    text: object,
    *,
    x: float,
    y: float,
    size: float = 10,
    font: str = "F1",
    fill: Color = (0.12, 0.13, 0.13),
) -> None:
    value = str(text or "").strip()
    if not value:
        return
    ops.append(
        "BT "
        f"/{font} {_num(size)} Tf "
        f"{_rgb(fill)} rg "
        f"1 0 0 1 {_num(x)} {_num(y)} Tm "
        f"({_pdf_escape(value)}) Tj "
        "ET"
    )


def _draw_wrapped(
    ops: list[str],
    text: object,
    *,
    x: float,
    y: float,
    width_chars: int,
    size: float = 10,
    leading: float = 13,
    font: str = "F1",
    fill: Color = (0.17, 0.18, 0.18),
) -> float:
    for line in _wrap_line(text, width_chars):
        _draw_text(ops, line, x=x, y=y, size=size, font=font, fill=fill)
        y -= leading
    return y


def _build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    bold_font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_ids: list[int] = []
    for page_ops in pages or [[]]:
        content = "\n".join(page_ops).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
        page_id = add(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 {font_id} 0 R /F2 {bold_font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>"
    ).encode("ascii")
    assert catalog_id == 1

    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_at = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(body)


def _draw_footer(ops: list[str], *, page_number: int, privacy_mode: PacketPrivacyMode) -> None:
    _draw_rect(ops, MARGIN_X, 34, CARD_WIDTH, 1.2, fill=(0.82, 0.80, 0.75))
    _draw_text(
        ops,
        f"PropertyQuarry packet - {privacy_mode.value.replace('_', ' ')} - page {page_number}",
        x=MARGIN_X,
        y=20,
        size=8,
        fill=(0.36, 0.37, 0.36),
    )


def _new_page(*, page_number: int, privacy_mode: PacketPrivacyMode) -> list[str]:
    ops: list[str] = []
    _draw_rect(ops, 0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=(0.965, 0.95, 0.91))
    _draw_footer(ops, page_number=page_number, privacy_mode=privacy_mode)
    return ops


def _section(title: str, items: list[str], *, accent: Color = (0.15, 0.38, 0.30)) -> dict[str, object]:
    return {"title": title, "items": items, "accent": accent}


def _media_counts(payload: dict[str, object]) -> dict[str, int]:
    floorplans = payload.get("floorplan_refs") if isinstance(payload.get("floorplan_refs"), list) else []
    photos = payload.get("photo_refs") if isinstance(payload.get("photo_refs"), list) else []
    return {"floorplans": len(floorplans), "photos": len(photos)}


def _packet_sections(
    *,
    payload: dict[str, object],
    packet_kind: PropertyPacketKind,
) -> list[dict[str, object]]:
    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}

    def row(label: str, value: object) -> str:
        text = _joined(value)
        return f"{label}: {text}" if text else ""

    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        market_scope = payload.get("market_scope") or facts.get("market_scope") or facts.get("market_scope_label")
        coverage = [
            row("Market scope", market_scope),
            row("Freshness date", facts.get("freshness_date")),
            row("Coverage window", facts.get("coverage_window")),
            row("Listing count", facts.get("listing_count") or facts.get("sample_size")),
        ]
        pricing = [
            row("Median buy per sqm", facts.get("median_price_per_sqm_eur") or facts.get("market_buy_per_sqm_eur")),
            row("Median rent per sqm", facts.get("median_rent_per_sqm_eur") or facts.get("market_rent_per_sqm_eur")),
            row("Median price", facts.get("median_price_eur")),
            row("Median rent", facts.get("median_rent_eur")),
            row("Gross yield", facts.get("gross_yield_pct")),
            row("Payback years", facts.get("payback_years")),
        ]
        methodology = [
            row("Data sources", facts.get("data_sources")),
            row("Data coverage", facts.get("data_coverage") or facts.get("source_coverage")),
            row("Methodology", facts.get("methodology") or "provider scan, market aggregation, and owner-safe redaction"),
        ]
        market_observations = _text_items(payload.get("market_observations"), limit=8)
        examples = _text_items(payload.get("market_examples"), limit=8) or _text_items(facts.get("market_examples"), limit=8)
        exclusions = [
            *_text_items(payload.get("unknowns"), limit=6),
            row("Exclusions", facts.get("exclusions")),
            row("Accuracy notes", facts.get("accuracy_notes")),
            row("Disclaimer", facts.get("legal_disclaimer")),
        ]
        return [
            _section("Market scope", [item for item in coverage if item] or ["Market scope was not supplied."], accent=(0.15, 0.38, 0.30)),
            _section("Pricing signals", [item for item in pricing if item] or ["No pricing signal was supplied."], accent=(0.74, 0.55, 0.18)),
            _section(
                "Source coverage",
                [item for item in methodology if item] or ["Only redacted market-level source coverage is included."],
                accent=(0.19, 0.36, 0.53),
            ),
            _section(
                "Market observations",
                market_observations or examples or ["No comparable example summary was included."],
                accent=(0.17, 0.45, 0.37),
            ),
            _section(
                "Exclusions and accuracy",
                [item for item in exclusions if item] or ["This is not a valuation, legal opinion, or offer recommendation."],
                accent=(0.62, 0.29, 0.26),
            ),
            _section(
                "Source, provenance, and privacy",
                [
                    "Source: redacted market evidence only.",
                    "No owner preference snapshot, exact address, property URL, floorplan, or photo reference is included.",
                    "PropertyQuarry remains the source of truth for ranking, methodology, and audit state.",
                    f"Renderer fallback available: {PDF_RENDERER_FALLBACK_VERSION}",
                ],
                accent=(0.30, 0.31, 0.30),
            ),
        ]

    core_facts = [
        row("Purchase price", facts.get("purchase_price_eur") or facts.get("price_eur") or facts.get("price_display")),
        row("Monthly rent", facts.get("total_rent_eur") or facts.get("rent_eur") or facts.get("rent_display")),
        row("Area", facts.get("area_m2") or facts.get("area_sqm") or facts.get("living_area_m2")),
        row("Rooms", facts.get("rooms") or facts.get("room_count")),
        row("District", facts.get("district") or facts.get("postal_name") or facts.get("city")),
    ]
    evidence = [
        row("Floorplan", facts.get("has_floorplan")),
        row("Lift", facts.get("lift") or facts.get("has_lift")),
        row("Outdoor space", facts.get("balcony") or facts.get("terrace") or facts.get("garden") or facts.get("outdoor_space")),
        row("Heating", facts.get("heating_type")),
        row("Availability", facts.get("availability")),
    ]
    radius = [
        row("Supermarket", facts.get("nearest_supermarket_m") or facts.get("nearest_supermarket_name")),
        row("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("nearest_pharmacy_name")),
        row("Subway", facts.get("nearest_subway_m") or facts.get("nearest_subway_name")),
        row("Playground", facts.get("nearest_playground_m") or facts.get("nearest_playground_name")),
    ]
    match_reasons = _text_items(payload.get("match_reasons"), limit=8)
    risks = [*_text_items(payload.get("mismatch_reasons"), limit=6), *_text_items(payload.get("unknowns"), limit=6)]
    viewing_questions = _text_items(payload.get("viewing_questions"), limit=10)

    sections = [
        _section("Core facts", [item for item in core_facts if item] or ["No core facts were supplied."], accent=(0.15, 0.38, 0.30)),
        _section("Evidence readiness", [item for item in evidence if item] or ["Evidence readiness is not yet available."], accent=(0.74, 0.55, 0.18)),
    ]
    if any(item for item in radius):
        sections.append(_section("Daily-life radius", [item for item in radius if item], accent=(0.19, 0.36, 0.53)))
    sections.extend(
        [
            _section("Why it matched", match_reasons or ["No explicit match reason was included in the source packet."], accent=(0.17, 0.45, 0.37)),
            _section(
                "Risks and unknowns",
                risks or ["No explicit risk was included. Ask the agent for source documents and current operating costs."],
                accent=(0.62, 0.29, 0.26),
            ),
            _section(
                "Viewing checklist",
                viewing_questions
                or [
                    "Confirm usable floorplan and room dimensions.",
                    "Ask for operating cost history and renovation notes.",
                    "Check noise, light, storage, and daily route fit.",
                ],
                accent=(0.20, 0.37, 0.52),
            ),
        ]
    )
    if packet_kind == PropertyPacketKind.PAID_MARKET_REPORT:
        sections.append(
            _section(
                "Methodology and freshness",
                [
                    "This report is generated from redacted PropertyQuarry research and market-level evidence only.",
                    row("Freshness date", facts.get("freshness_date") or "generated packet timestamp"),
                    row("Methodology", facts.get("methodology") or "provider scan, ranking assessment, and owner-safe redaction"),
                ],
                accent=(0.42, 0.25, 0.48),
            )
        )
    sections.append(
        _section(
            "Source, provenance, and privacy",
            [
                f"Source: {payload.get('property_url') or 'internal PropertyQuarry packet'}",
                "This packet was redacted before publication.",
                "PropertyQuarry remains the source of truth for ranking, preference learning, and audit state.",
                f"Renderer fallback available: {PDF_RENDERER_FALLBACK_VERSION}",
            ],
            accent=(0.30, 0.31, 0.30),
        )
    )
    return sections


def _visual_pdf(
    *,
    title: str,
    recommended_title: str,
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    summary: str,
    media_counts: dict[str, int],
    sections: list[dict[str, object]],
) -> bytes:
    pages: list[list[str]] = []
    ops = _new_page(page_number=1, privacy_mode=privacy_mode)
    _draw_rect(ops, 0, 0, 15, PAGE_HEIGHT, fill=(0.15, 0.38, 0.30))
    _draw_rect(ops, 15, 0, 5, PAGE_HEIGHT, fill=(0.74, 0.55, 0.18))
    _draw_text(ops, "PropertyQuarry", x=MARGIN_X, y=774, size=20, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_text(ops, "Decision packet", x=MARGIN_X, y=752, size=11, fill=(0.43, 0.38, 0.29))
    y = _draw_wrapped(
        ops,
        recommended_title,
        x=MARGIN_X,
        y=705,
        width_chars=42,
        size=24,
        leading=28,
        font="F2",
        fill=(0.13, 0.14, 0.13),
    )
    y -= 18
    chips = [
        packet_kind.value.replace("_", " "),
        privacy_mode.value.replace("_", " "),
        fliplink_format.value.replace("_", " "),
        PDF_RENDERER_VERSION,
    ]
    chip_x = MARGIN_X
    for chip in chips:
        chip_width = min(156, max(72, 7.0 * len(chip) + 20))
        _draw_rect(ops, chip_x, y - 5, chip_width, 24, fill=(0.99, 0.98, 0.94))
        _draw_text(ops, chip, x=chip_x + 9, y=y + 2, size=8.5, font="F2", fill=(0.25, 0.28, 0.26))
        chip_x += chip_width + 8
        if chip_x > PAGE_WIDTH - MARGIN_X - 90:
            chip_x = MARGIN_X
            y -= 31
    y -= 72
    _draw_rect(ops, MARGIN_X, y - 104, CARD_WIDTH, 126, fill=(1.0, 0.995, 0.97))
    _draw_rect(ops, MARGIN_X, y + 13, CARD_WIDTH, 9, fill=(0.74, 0.55, 0.18))
    _draw_text(ops, "Decision snapshot", x=MARGIN_X + 18, y=y - 8, size=14, font="F2", fill=(0.15, 0.38, 0.30))
    _draw_wrapped(
        ops,
        summary or "Review this property against the current PropertyQuarry brief.",
        x=MARGIN_X + 18,
        y=y - 32,
        width_chars=78,
        size=10.5,
        leading=14,
    )
    y -= 160
    metric_width = (CARD_WIDTH - 24) / 3
    metrics = [
        ("Floorplans", str(media_counts.get("floorplans") or 0)),
        ("Photos", str(media_counts.get("photos") or 0)),
        ("Sections", str(len(sections))),
    ]
    for index, (label, value) in enumerate(metrics):
        x = MARGIN_X + (metric_width + 12) * index
        _draw_rect(ops, x, y - 72, metric_width, 82, fill=(0.93, 0.96, 0.94))
        _draw_text(ops, value, x=x + 14, y=y - 24, size=26, font="F2", fill=(0.15, 0.38, 0.30))
        _draw_text(ops, label, x=x + 14, y=y - 48, size=9.5, font="F2", fill=(0.30, 0.36, 0.32))
    _draw_text(ops, "Title", x=MARGIN_X, y=128, size=9, font="F2", fill=(0.43, 0.38, 0.29))
    _draw_wrapped(ops, title, x=MARGIN_X, y=112, width_chars=84, size=10, leading=12)
    pages.append(ops)

    page_number = 2
    ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
    y = 786
    _draw_text(ops, "Packet sections", x=MARGIN_X, y=y, size=17, font="F2", fill=(0.15, 0.38, 0.30))
    y -= 34
    for section in sections:
        title_text = str(section.get("title") or "").strip()
        raw_items = section.get("items")
        items = [str(item or "").strip() for item in raw_items if str(item or "").strip()] if isinstance(raw_items, list) else []
        raw_accent = section.get("accent")
        accent: Color = raw_accent if isinstance(raw_accent, tuple) and len(raw_accent) == 3 else (0.15, 0.38, 0.30)  # type: ignore[assignment]
        wrapped_count = sum(max(1, len(_wrap_line(item, 76))) for item in items[:8])
        card_height = max(74, 38 + wrapped_count * 12)
        if y - card_height < 64:
            pages.append(ops)
            page_number += 1
            ops = _new_page(page_number=page_number, privacy_mode=privacy_mode)
            y = 786
        _draw_rect(ops, MARGIN_X, y - card_height, CARD_WIDTH, card_height, fill=(1.0, 0.995, 0.97))
        _draw_rect(ops, MARGIN_X, y - card_height, 6, card_height, fill=accent)
        _draw_text(ops, title_text, x=MARGIN_X + 18, y=y - 21, size=12.5, font="F2", fill=(0.12, 0.14, 0.13))
        item_y = y - 42
        for item in items[:8] or ["No source item supplied."]:
            item_y = _draw_wrapped(ops, item, x=MARGIN_X + 20, y=item_y, width_chars=76, size=9.5, leading=12)
        y -= card_height + 16
    pages.append(ops)
    return _build_pdf(pages)


def render_property_packet_pdf(
    *,
    artifact_root: Path,
    publication_id: str,
    principal_id: str,
    source: dict[str, object],
    packet_kind: PropertyPacketKind,
    privacy_mode: PacketPrivacyMode,
    fliplink_format: FlipLinkFormat,
    include_exact_address: bool = False,
    include_floorplan: bool = True,
    include_photos: bool = True,
) -> dict[str, object]:
    redaction = redact_property_packet(
        source=source,
        privacy_mode=privacy_mode,
        packet_kind=packet_kind,
        include_exact_address=include_exact_address,
        include_floorplan=include_floorplan,
        include_photos=include_photos,
    )
    title = str(redaction.payload.get("title") or source.get("title") or "PropertyQuarry packet").strip() or "PropertyQuarry packet"
    recommended_title = f"{title} - {packet_kind.value.replace('_', ' ').title()}"
    sections = _packet_sections(payload=redaction.payload, packet_kind=packet_kind)
    pdf_bytes = _visual_pdf(
        title=title,
        recommended_title=recommended_title,
        packet_kind=packet_kind,
        privacy_mode=privacy_mode,
        fliplink_format=fliplink_format,
        summary=str(redaction.payload.get("fit_summary") or redaction.payload.get("recommendation") or ""),
        media_counts=_media_counts(redaction.payload),
        sections=sections,
    )
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    principal_token = _safe_token(principal_id, "principal")
    target_dir = artifact_root / "property_packets" / principal_token
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{_safe_token(publication_id)}.pdf"
    receipt_path = target_dir / f"{_safe_token(publication_id)}.receipt.json"
    pdf_path.write_bytes(pdf_bytes)
    receipt = {
        **redaction.receipt,
        "renderer_version": PDF_RENDERER_VERSION,
        "renderer_kind": "branded_visual_pdf",
        "visual_elements": ["cover", "metric_cards", "section_cards", "privacy_footer"],
        "pdf_sha256": pdf_sha256,
        "source_pdf_size_bytes": len(pdf_bytes),
        "source_pdf_artifact_ref": str(pdf_path),
        "redaction_policy_version": REDACTION_POLICY_VERSION,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "pdf_path": str(pdf_path),
        "receipt_path": str(receipt_path),
        "pdf_sha256": pdf_sha256,
        "pdf_size_bytes": len(pdf_bytes),
        "receipt": receipt,
        "redacted_payload": redaction.payload,
        "recommended_title": recommended_title,
    }
