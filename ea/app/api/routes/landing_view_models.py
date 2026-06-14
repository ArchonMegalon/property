from __future__ import annotations

import html
import hashlib
import re
import urllib.parse
from typing import Any

from app.services.property_artifact_contracts import required_artifact_receipt_rows


def _csv_values(value: object) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for raw in str(value or "").split(","):
        normalized = str(raw or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(normalized)
    return values


def _normalize_property_type_values(value: object) -> list[str]:
    """Normalize property_type payloads from single, list, or comma-separated forms."""
    values: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    elif isinstance(value, str) and "," in value:
        raw_values = [item.strip() for item in value.split(",")]
    else:
        raw_values = [str(value or "")]

    for item in raw_values:
        normalized = item.strip().lower()
        if not normalized:
            continue
        if normalized == "any" and len(raw_values) > 1:
            values = [value for value in values if value != "any"]
            continue
        if normalized not in values:
            values.append(normalized)

    if not values:
        values = ["any"]
    return values


def _clean_property_candidate_copy(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    noisy_exact = {
        "Provider-ranked fallback candidate kept because strict personal-fit scoring produced no shortlist.",
    }
    if text in noisy_exact:
        return ""
    replacements = {
        "Provider-ranked fallback candidate kept because strict personal-fit scoring produced no shortlist.": "Fallback candidate because no stronger fit cleared the shortlist.",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()


def _merge_option_catalog(
    base: list[dict[str, str]],
    selected_values: list[str],
) -> list[dict[str, str]]:
    values = {str(item.get("value") or "").strip().lower() for item in base if str(item.get("value") or "").strip()}
    merged = list(base)
    for value in selected_values:
        normalized = str(value or "").strip()
        if not normalized or normalized.lower() in values:
            continue
        merged.append({"value": normalized, "label": normalized})
        values.add(normalized.lower())
    return merged


def _split_known_and_custom_values(
    base: list[dict[str, str]],
    selected_values: list[str],
) -> tuple[list[str], list[str]]:
    known_values = {
        str(item.get("value") or "").strip().lower()
        for item in base
        if str(item.get("value") or "").strip()
    }
    known: list[str] = []
    custom: list[str] = []
    for value in selected_values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        if normalized.lower() in known_values:
            known.append(normalized)
        else:
            custom.append(normalized)
    return known, custom


def _scope_preview_layout(country_code: str, region_code: str, options: list[dict[str, str]]) -> list[dict[str, object]]:
    normalized_country = str(country_code or "").strip().upper()
    normalized_region = str(region_code or "").strip().lower()
    explicit_layouts: dict[tuple[str, str], dict[str, tuple[float, float, float, float]]] = {
        (
            "AT",
            "vienna",
        ): {
            "1010 vienna": (45, 67, 10, 10),
            "1020 vienna": (57, 58, 18, 22),
            "1030 vienna": (52, 82, 17, 18),
            "1040 vienna": (41, 80, 10, 12),
            "1050 vienna": (34, 82, 11, 11),
            "1060 vienna": (27, 75, 11, 12),
            "1070 vienna": (24, 66, 11, 10),
            "1080 vienna": (30, 60, 9, 9),
            "1090 vienna": (38, 54, 12, 12),
            "1100 vienna": (41, 96, 19, 20),
            "1110 vienna": (61, 100, 16, 19),
            "1120 vienna": (24, 92, 16, 15),
            "1130 vienna": (8, 81, 19, 16),
            "1140 vienna": (2, 63, 24, 18),
            "1150 vienna": (19, 80, 8, 11),
            "1160 vienna": (12, 57, 16, 18),
            "1170 vienna": (18, 46, 15, 14),
            "1180 vienna": (31, 40, 18, 15),
            "1190 vienna": (41, 25, 24, 24),
            "1200 vienna": (51, 47, 14, 12),
            "1210 vienna": (60, 26, 28, 24),
            "1220 vienna": (76, 48, 24, 34),
            "1230 vienna": (5, 98, 31, 18),
            "klosterneuburg": (58, 8, 18, 12),
            "mödling": (31, 112, 18, 12),
            "purkersdorf": (-4, 75, 18, 12),
        },
    }
    explicit = explicit_layouts.get((normalized_country, normalized_region), {})
    if explicit:
        layout_rows: list[dict[str, object]] = []
        for option in options:
            value = str(option.get("value") or "").strip()
            rect = explicit.get(value.lower())
            if not rect:
                continue
            x, y, width, height = rect
            layout_rows.append(
                {
                    "value": value,
                    "label": str(option.get("label") or value).strip() or value,
                    "detail": str(option.get("detail") or "").strip(),
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
        if layout_rows:
            return layout_rows

    total = max(1, len(options))
    columns = 3 if total > 6 else 2
    rows = max(1, (total + columns - 1) // columns)
    cell_width = 100 / columns
    cell_height = 100 / rows
    grid_rows: list[dict[str, object]] = []
    for index, option in enumerate(options):
        column = index % columns
        row = index // columns
        grid_rows.append(
            {
                "value": str(option.get("value") or "").strip(),
                "label": str(option.get("label") or option.get("value") or "").strip(),
                "detail": str(option.get("detail") or "").strip(),
                "x": (column * cell_width) + 4,
                "y": (row * cell_height) + 8,
                "width": max(18.0, cell_width - 8),
                "height": max(16.0, cell_height - 12),
            }
        )
    return grid_rows


def _property_scope_preview(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
    normalized_country = str(country_code or "").strip().upper()
    normalized_region = str(region_code or "").strip().lower()
    normalized_query = str(location_query or "").strip()
    option_rows = _property_location_options(normalized_country, normalized_region)
    layout_rows = _scope_preview_layout(normalized_country, normalized_region, option_rows)
    option_lookup = {
        str(option.get("value") or "").strip().lower(): str(option.get("label") or option.get("value") or "").strip()
        for option in option_rows
        if str(option.get("value") or "").strip()
    }
    selected_values = _csv_values(normalized_query)
    selected_lookup = {value.lower() for value in selected_values}
    if normalized_country == "AT" and normalized_region == "vienna" and normalized_query.lower() in {"vienna", "wien"}:
        selected_lookup = {
            str(row.get("value") or "").strip().lower()
            for row in layout_rows
            if str(row.get("value") or "").strip()
        }
    elif not selected_lookup and normalized_query:
        if normalized_query.lower() in option_lookup:
            selected_lookup = {normalized_query.lower()}
        elif normalized_region and normalized_query.lower() == normalized_region:
            selected_lookup = {
                str(row.get("value") or "").strip().lower()
                for row in layout_rows
                if str(row.get("value") or "").strip()
            }
    selected_labels = [
        option_lookup.get(value.lower(), value)
        for value in selected_values
        if str(value or "").strip()
    ]
    if not selected_labels and selected_lookup:
        selected_labels = [
            str(row.get("label") or row.get("value") or "").strip()
            for row in layout_rows
            if str(row.get("value") or "").strip().lower() in selected_lookup
        ]
    market_label_parts = [part for part in (normalized_region.replace("_", " ").title(), normalized_country) if part]
    market_label = " · ".join(market_label_parts) or "Search area"

    vienna_district_map: dict[str, dict[str, object]] = {
        "1010 vienna": {"path": "M140 70 L151 64 L163 67 L165 80 L154 89 L141 85 Z", "label": "1010 Vienna"},
        "1020 vienna": {"path": "M166 62 L186 54 L205 58 L208 76 L199 91 L178 92 L165 81 Z", "label": "1020 Vienna"},
        "1030 vienna": {"path": "M164 84 L178 92 L200 92 L210 109 L198 123 L176 124 L160 110 Z", "label": "1030 Vienna"},
        "1040 vienna": {"path": "M139 88 L155 87 L161 109 L154 121 L138 119 L130 103 Z", "label": "1040 Vienna"},
        "1050 vienna": {"path": "M120 92 L130 101 L138 119 L126 126 L111 119 L109 103 Z", "label": "1050 Vienna"},
        "1060 vienna": {"path": "M101 84 L118 82 L120 94 L109 104 L95 100 L94 88 Z", "label": "1060 Vienna"},
        "1070 vienna": {"path": "M101 68 L119 64 L120 82 L101 84 L93 75 Z", "label": "1070 Vienna"},
        "1080 vienna": {"path": "M118 54 L136 52 L136 67 L120 74 L110 66 Z", "label": "1080 Vienna"},
        "1090 vienna": {"path": "M136 45 L160 42 L170 56 L165 70 L152 72 L136 67 Z", "label": "1090 Vienna"},
        "1100 vienna": {"path": "M137 120 L155 123 L177 124 L198 123 L219 129 L218 145 L143 146 L131 133 Z", "label": "1100 Vienna"},
        "1110 vienna": {"path": "M219 127 L241 127 L265 135 L276 149 L233 152 L219 145 Z", "label": "1110 Vienna"},
        "1120 vienna": {"path": "M90 111 L110 106 L126 126 L131 133 L123 146 L88 146 L76 134 Z", "label": "1120 Vienna"},
        "1130 vienna": {"path": "M54 95 L75 90 L91 111 L76 134 L52 132 L41 111 Z", "label": "1130 Vienna"},
        "1140 vienna": {"path": "M27 83 L53 76 L74 89 L54 95 L41 111 L26 110 L18 95 Z", "label": "1140 Vienna"},
        "1150 vienna": {"path": "M73 88 L90 86 L95 100 L90 111 L75 90 Z", "label": "1150 Vienna"},
        "1160 vienna": {"path": "M67 70 L89 66 L101 68 L94 88 L73 88 L63 80 Z", "label": "1160 Vienna"},
        "1170 vienna": {"path": "M73 45 L96 38 L111 48 L102 68 L89 66 L67 70 L58 56 Z", "label": "1170 Vienna"},
        "1180 vienna": {"path": "M101 36 L125 30 L139 35 L136 52 L118 54 L110 66 L101 49 Z", "label": "1180 Vienna"},
        "1190 vienna": {"path": "M126 19 L158 16 L191 18 L205 32 L196 49 L170 56 L160 42 L136 45 L125 30 Z", "label": "1190 Vienna"},
        "1200 vienna": {"path": "M170 57 L195 48 L211 52 L214 69 L208 76 L186 54 Z", "label": "1200 Vienna"},
        "1210 vienna": {"path": "M206 31 L228 27 L253 34 L269 52 L266 75 L242 87 L214 69 L211 52 L196 49 Z", "label": "1210 Vienna"},
        "1220 vienna": {"path": "M214 69 L242 87 L266 75 L282 95 L280 122 L266 136 L241 127 L219 127 L210 109 L200 92 L208 76 Z", "label": "1220 Vienna"},
        "1230 vienna": {"path": "M18 110 L26 110 L41 111 L52 132 L88 146 L26 146 L18 128 Z", "label": "1230 Vienna"},
    }

    def _district_centroid_from_path(path: str) -> tuple[float, float]:
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)]
        points = list(zip(numbers[0::2], numbers[1::2]))
        if not points:
            return 0.0, 0.0
        x_total = sum(point[0] for point in points)
        y_total = sum(point[1] for point in points)
        return x_total / len(points), y_total / len(points)

    shapes: list[str] = []
    interactive_shapes: list[str] = []
    selected_count = 0
    district_rows: list[dict[str, object]] = []
    if normalized_country == "AT" and normalized_region == "vienna":
        for row in layout_rows:
            label = str(row.get("label") or row.get("value") or "").strip()
            value = str(row.get("value") or label).strip().lower()
            selected = bool(value and value in selected_lookup)
            if selected:
                selected_count += 1
            district_spec = vienna_district_map.get(value)
            if not district_spec:
                continue
            digest = hashlib.sha1(label.lower().encode("utf-8")).digest()
            red_tint = 108 + (digest[0] % 42)
            green_tint = 30 + (digest[1] % 28)
            blue_tint = 34 + (digest[2] % 24)
            fill = f"#{red_tint:02x}{green_tint:02x}{blue_tint:02x}" if selected else "#efe8da"
            fill_opacity = "0.78" if selected else "0.38"
            stroke = "#7b6a5a" if not selected else "#8a1e1e"
            stroke_width = "1.45" if selected else "1.05"
            path = str(district_spec.get("path") or "")
            centroid_x, centroid_y = _district_centroid_from_path(path)
            shapes.append(
                f'<path d="{path}" fill="{fill}" fill-opacity="{fill_opacity}" stroke="{stroke}" stroke-width="{stroke_width}" '
                'stroke-linejoin="round" stroke-linecap="round" />'
            )
            interactive_shapes.append(
                f'<path class="pqx-previous-district-hotspot{" is-selected" if selected else ""}" d="{path}" '
                f'data-label="{html.escape(label)}" data-pqx-scope-open data-pqx-scope-title="{html.escape(label)}" '
                f'cx="{centroid_x:.2f}" cy="{centroid_y:.2f}"><title>{html.escape(label)}</title></path>'
            )
            district_rows.append(
                {
                    "label": label,
                    "selected": selected,
                    "path": path,
                    "center_x_pct": round((centroid_x / 296.0) * 100.0, 3),
                    "center_y_pct": round((centroid_y / 160.0) * 100.0, 3),
                }
            )
    else:
        for row in layout_rows:
            value = str(row.get("value") or "").strip().lower()
            selected = bool(value and value in selected_lookup)
            if selected:
                selected_count += 1
            x = float(row.get("x") or 0.0)
            y = float(row.get("y") or 0.0)
            width = float(row.get("width") or 16.0)
            height = float(row.get("height") or 12.0)
            radius = min(7.0, max(3.0, min(width, height) * 0.22))
            digest = hashlib.sha1(str(row.get("label") or row.get("value") or "").strip().lower().encode("utf-8")).digest()
            fill = f"#{170 + (digest[0] % 48):02x}{52 + (digest[1] % 40):02x}{58 + (digest[2] % 34):02x}" if selected else "#d8d3c8"
            fill_opacity = "0.44" if selected else "0.62"
            stroke = "#f2a3a3" if selected else "#b9b1a1"
            stroke_width = "1.8" if selected else "1.1"
            shapes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="{radius:.1f}" fill="{fill}" fill-opacity="{fill_opacity}" stroke="{stroke}" stroke-width="{stroke_width}" />'
            )
            district_rows.append(
                {
                    "label": str(row.get("label") or row.get("value") or "").strip(),
                    "selected": selected,
                    "left_pct": round((x / 296.0) * 100.0, 3),
                    "top_pct": round((y / 160.0) * 100.0, 3),
                    "width_pct": round((width / 296.0) * 100.0, 3),
                    "height_pct": round((height / 160.0) * 100.0, 3),
                }
            )

    custom_marker = ""
    if normalized_query and not selected_count:
        custom_marker = (
            '<g transform="translate(94 24)">'
            '<circle cx="0" cy="0" r="9" fill="#d44f4f" fill-opacity="0.24" stroke="#f2a3a3" stroke-width="1.6" />'
            '<circle cx="0" cy="0" r="3.5" fill="#d44f4f" />'
            "</g>"
        )
    city_boundary = '<path d="M20 20 L276 20 L276 140 L20 140 Z" stroke="#9E9689" stroke-width="2.1" stroke-linejoin="round" fill="none" opacity="0.72"/>'
    if normalized_country == "AT" and normalized_region == "vienna":
        city_boundary = (
            '<path d="M18 44 L28 28 L44 22 L74 18 L108 22 L138 18 L176 16 L208 18 L242 24 L266 34 '
            'L280 52 L276 72 L282 95 L279 119 L266 136 L236 146 L200 143 L173 148 L138 146 L104 150 '
            'L70 146 L43 138 L24 124 L16 102 L16 74 L14 56 Z" '
            'stroke="#5f5648" stroke-width="2.2" stroke-linejoin="round" fill="none" opacity="0.92"/>'
        )
    road_lines = [
        '<path d="M24 44 C54 46, 84 42, 116 54 C146 66, 178 66, 214 58 C242 50, 258 50, 278 46" stroke="#c9c0b2" stroke-width="6" stroke-linecap="round" opacity="0.92"/>',
        '<path d="M20 104 C48 94, 72 92, 101 84 C136 74, 166 84, 196 96 C224 106, 248 106, 278 96" stroke="#cdc5b7" stroke-width="4.8" stroke-linecap="round" opacity="0.88"/>',
        '<path d="M58 18 C62 36, 62 62, 60 142" stroke="#d7cfbf" stroke-width="2.4" stroke-linecap="round" opacity="0.84"/>',
        '<path d="M110 18 C114 38, 118 64, 116 146" stroke="#d2c9bb" stroke-width="2.1" stroke-linecap="round" opacity="0.8"/>',
        '<path d="M176 18 C174 42, 178 72, 184 146" stroke="#d2c9bb" stroke-width="2.2" stroke-linecap="round" opacity="0.82"/>',
        '<path d="M234 22 C228 50, 232 82, 246 142" stroke="#d7cfbf" stroke-width="2.0" stroke-linecap="round" opacity="0.78"/>',
        '<path d="M34 64 C72 56, 94 62, 126 76 C156 88, 182 92, 210 86 C238 80, 258 78, 274 82" stroke="#bcae9f" stroke-width="1.4" stroke-linecap="round" opacity="0.72"/>',
        '<path d="M34 122 C64 112, 92 116, 122 124 C152 132, 184 134, 220 128 C246 124, 262 122, 274 124" stroke="#bcae9f" stroke-width="1.2" stroke-linecap="round" opacity="0.65"/>',
    ]
    park_patches = [
        '<path d="M24 58 C36 44, 58 42, 68 56 C76 68, 62 84, 42 84 C26 82, 18 68, 24 58 Z" fill="#dfe2d2" opacity="0.74"/>',
        '<path d="M203 104 C218 92, 246 94, 254 110 C260 124, 246 138, 224 136 C206 132, 196 118, 203 104 Z" fill="#d7dcc9" opacity="0.7"/>',
        '<path d="M108 26 C118 18, 132 20, 136 31 C138 40, 130 48, 118 48 C108 46, 102 36, 108 26 Z" fill="#dde0cf" opacity="0.64"/>',
    ]
    water_layer = ''
    if normalized_country == "AT" and normalized_region == "vienna":
        water_layer = (
            '<path d="M204 14 C214 28, 219 42, 220 60 C221 80, 214 96, 217 116 C220 132, 229 144, 236 154" '
            'stroke="#9db5c3" stroke-width="16" stroke-linecap="round" opacity="0.58"/>'
            '<path d="M200 18 C209 33, 212 48, 212 64 C212 83, 206 100, 208 120 C210 133, 216 145, 222 154" '
            'stroke="#d8e4ea" stroke-width="7" stroke-linecap="round" opacity="0.9"/>'
            '<path d="M218 54 C228 62, 234 72, 236 84 C238 95, 236 108, 240 121" stroke="#d8e4ea" stroke-width="3" stroke-linecap="round" opacity="0.82"/>'
        )
    district_overlay_svg = ""
    if interactive_shapes:
        district_overlay_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 296 160" class="pqx-previous-district-hotspots" '
            'preserveAspectRatio="none" aria-hidden="true">'
            f'{"".join(interactive_shapes)}'
            "</svg>"
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="184" viewBox="0 0 320 184" fill="none">'
        '<defs>'
        '<linearGradient id="bg" x1="18" y1="16" x2="280" y2="168" gradientUnits="userSpaceOnUse">'
        '<stop stop-color="#f5f0e5"/>'
        '<stop offset="1" stop-color="#e8decc"/>'
        '</linearGradient>'
        '<pattern id="paper" width="12" height="12" patternUnits="userSpaceOnUse">'
        '<path d="M0 12 L12 0 M-3 3 L3 -3 M9 15 L15 9" stroke="#c8bea9" stroke-opacity="0.18" stroke-width="0.8"/>'
        '</pattern>'
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#2D2418" flood-opacity="0.16"/>'
        '</filter>'
        '</defs>'
        '<rect width="320" height="184" rx="18" fill="#d9cdb8"/>'
        '<g transform="translate(12 12)" filter="url(#shadow)">'
        '<rect width="296" height="160" rx="14" fill="url(#bg)"/>'
        '<rect x="0.5" y="0.5" width="295" height="159" rx="14" fill="url(#paper)" opacity="0.42"/>'
        '<rect x="0.5" y="0.5" width="295" height="159" rx="14" fill="none" stroke="#c7baa1" stroke-width="1"/>'
        f'{"".join(park_patches)}'
        f'{water_layer}'
        f'{"".join(road_lines)}'
        f'{city_boundary}'
        f'{"".join(shapes)}'
        f"{custom_marker}"
        "</g>"
        "</svg>"
    )
    return {
        "image_url": f"data:image/svg+xml;utf8,{urllib.parse.quote(svg, safe='/:;,+-=()%')}",
        "alt": f"Search area preview for {normalized_query or market_label}",
        "summary": ", ".join(selected_labels[:2]) if selected_labels else (normalized_query or market_label),
        "count_label": "",
        "market_label": market_label,
        "district_rows": district_rows,
        "district_overlay_svg": district_overlay_svg,
    }


def _property_candidate_maps_url(candidate: dict[str, object]) -> str:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    if isinstance(candidate.get("property_facts_json"), dict):
        facts = {**facts, **dict(candidate.get("property_facts_json") or {})}
    if isinstance(facts.get("listing_research_snapshot"), dict):
        facts = {**dict(facts.get("listing_research_snapshot") or {}), **facts}

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
        candidate.get("title"),
    )
    if not query:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


def _property_search_worker_slots(run_summary: dict[str, object], *, plan_key: str) -> dict[str, object]:
    normalized_plan = str(plan_key or "free").strip().lower() or "free"
    slot_cap = {"free": 1, "plus": 3, "agent": 6}.get(normalized_plan, 1)
    provider_workers = dict(run_summary.get("provider_workers") or {}) if isinstance(run_summary.get("provider_workers"), dict) else {}
    configured_workers = max(1, int(provider_workers.get("worker_concurrency") or slot_cap or 1))
    visible_workers = max(1, min(slot_cap, configured_workers))
    source_rows = [dict(row) for row in list(run_summary.get("sources") or []) if isinstance(row, dict)]

    def _source_progress(source_row: dict[str, object]) -> int:
        raw_status = str(source_row.get("status") or source_row.get("state") or "").strip().lower()
        if raw_status in {"completed", "processed", "done", "success"}:
            return 100
        if raw_status in {"failed", "error", "skipped"} or source_row.get("error"):
            return 100
        try:
            explicit = int(float(str(source_row.get("progress") or "").strip()))
        except Exception:
            explicit = 0
        if explicit > 0:
            return max(0, min(explicit, 100))
        if raw_status in {"running", "processing", "in_progress", "working", "warming"}:
            return 58
        if raw_status in {"queued", "pending", "starting"}:
            return 18
        return 10

    def _source_status_label(source_row: dict[str, object]) -> str:
        raw_status = str(source_row.get("status") or source_row.get("state") or "").strip().lower()
        if raw_status in {"completed", "processed", "done", "success"}:
            return "Done"
        if raw_status in {"failed", "error"} or source_row.get("error"):
            return "Needs retry"
        if raw_status in {"running", "processing", "in_progress", "working", "warming"}:
            return "Running"
        if raw_status in {"queued", "pending", "starting"}:
            return "Queued"
        return "Queued"

    active_sources = [
        row for row in source_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() not in {"completed", "processed", "done", "success", "failed", "error", "skipped"}
    ]
    completed_sources = [
        row for row in source_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() in {"completed", "processed", "done", "success"}
    ]
    queue = active_sources + completed_sources

    worker_rows: list[dict[str, object]] = []
    for index in range(visible_workers):
        source_row = queue[index] if index < len(queue) else {}
        source_label = str(source_row.get("source_label") or source_row.get("label") or "").strip()
        status_label = _source_status_label(source_row) if source_row else "Idle"
        progress = _source_progress(source_row) if source_row else 0
        worker_rows.append(
            {
                "label": f"W{index + 1}",
                "provider": source_label or ("Waiting for a source" if active_sources or source_rows else "Stand by"),
                "status_label": status_label,
                "progress_pct": progress,
                "tone": "done" if progress >= 100 and source_row else ("active" if status_label == "Running" else ("queued" if status_label == "Queued" else "idle")),
            }
        )

    upgrade_copy = ""
    if normalized_plan == "free":
        upgrade_copy = "Upgrade to Plus for 3 search workers or Agent for 6."
    elif normalized_plan == "plus":
        upgrade_copy = "Upgrade to Agent for 6 search workers."

    return {
        "plan_key": normalized_plan,
        "visible_workers": visible_workers,
        "slot_cap": slot_cap,
        "workers": worker_rows,
        "upgrade_copy": upgrade_copy,
        "tooltip": "Search workers handle source lanes in parallel. Faster tiers unlock more concurrent workers.",
    }


def _property_candidate_directions_url(
    candidate: dict[str, object],
    *,
    target_lat: object = "",
    target_lng: object = "",
    target_query: object = "",
    mode: str = "walking",
) -> str:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    if isinstance(candidate.get("property_facts_json"), dict):
        facts = {**facts, **dict(candidate.get("property_facts_json") or {})}
    if isinstance(facts.get("listing_research_snapshot"), dict):
        facts = {**dict(facts.get("listing_research_snapshot") or {}), **facts}

    def _text(*values: object) -> str:
        return next((str(value or "").strip() for value in values if str(value or "").strip()), "")

    origin_lat = _text(facts.get("map_lat"), facts.get("lat"), facts.get("latitude"))
    origin_lng = _text(facts.get("map_lng"), facts.get("lng"), facts.get("lon"), facts.get("longitude"))
    address_lines = " ".join(str(item or "").strip() for item in list(facts.get("address_lines") or []) if str(item or "").strip())
    origin = (
        f"{origin_lat},{origin_lng}"
        if origin_lat and origin_lng
        else _text(facts.get("exact_address"), facts.get("street_address"), address_lines, facts.get("postal_name"), candidate.get("title"))
    )
    destination = f"{target_lat},{target_lng}" if _text(target_lat) and _text(target_lng) else _text(target_query)
    if not origin or not destination:
        return ""
    travel_mode = mode if mode in {"walking", "transit", "driving", "bicycling"} else "walking"
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={urllib.parse.quote(origin, safe=',')}"
        f"&destination={urllib.parse.quote(destination, safe=',')}"
        f"&travelmode={urllib.parse.quote(travel_mode)}"
    )


def _property_family_filters_active(preferences: dict[str, object]) -> bool:
    if bool(preferences.get("enable_family_mode")):
        return True
    school_stage_preferences = preferences.get("school_stage_preferences")
    if isinstance(school_stage_preferences, (list, tuple, set)) and any(str(item).strip() for item in school_stage_preferences):
        return True
    keywords = {
        str(value).strip().lower()
        for value in str(preferences.get("keywords") or "").split(",")
        if str(value).strip()
    }
    return bool(
        {"family", "playground nearby", "library nearby", "public pool nearby", "medical care nearby"} & keywords
    )


def _property_candidate_route_evidence(
    candidate: dict[str, object],
    property_preferences: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    if isinstance(candidate.get("property_facts_json"), dict):
        facts = {**facts, **dict(candidate.get("property_facts_json") or {})}
    if isinstance(facts.get("listing_research_snapshot"), dict):
        facts = {**dict(facts.get("listing_research_snapshot") or {}), **facts}

    family_filters_active = _property_family_filters_active(property_preferences or {})
    specs = (
        ("BOOK", "School", "nearest_school_m", "nearest_school_name", "nearest_school_lat", "nearest_school_lng", "transit", True),
        ("CART", "Supermarket", "nearest_supermarket_m", "nearest_supermarket_name", "nearest_supermarket_lat", "nearest_supermarket_lng", "walking", False),
        ("PLAY", "Playground", "nearest_playground_m", "nearest_playground_name", "nearest_playground_lat", "nearest_playground_lng", "walking", True),
        ("RX", "Pharmacy", "nearest_pharmacy_m", "nearest_pharmacy_name", "nearest_pharmacy_lat", "nearest_pharmacy_lng", "walking", False),
        ("U", "Transit", "nearest_subway_m", "nearest_subway_name", "nearest_subway_lat", "nearest_subway_lng", "transit", False),
    )
    rows: list[dict[str, str]] = []
    for icon, label, distance_key, name_key, lat_key, lng_key, mode, family_only in specs:
        if family_only and not family_filters_active:
            continue
        raw_distance = facts.get(distance_key)
        if raw_distance in (None, "", []):
            continue
        try:
            meters = int(float(raw_distance))
        except Exception:
            continue
        place_name = str(facts.get(name_key) or label).strip() or label
        row = {
            "icon": icon,
            "label": label,
            "distance": f"{meters} m",
            "detail": place_name,
            "mode": mode,
            "map_url": _property_candidate_directions_url(
                candidate,
                target_lat=facts.get(lat_key),
                target_lng=facts.get(lng_key),
                target_query=place_name,
                mode=mode,
            ),
        }
        rows.append(row)
    return rows[:4]


def _property_route_preview_path(
    *,
    origin_lat: object = "",
    origin_lng: object = "",
    target_lat: object = "",
    target_lng: object = "",
) -> str:
    def _float(value: object) -> float | None:
        try:
            return float(str(value or "").strip())
        except Exception:
            return None

    start_x = 12.0
    start_y = 56.0
    end_x = 132.0
    end_y = 18.0
    o_lat = _float(origin_lat)
    o_lng = _float(origin_lng)
    t_lat = _float(target_lat)
    t_lng = _float(target_lng)
    if all(value is not None for value in (o_lat, o_lng, t_lat, t_lng)):
        lat_delta = max(-1.0, min(1.0, (t_lat or 0.0) - (o_lat or 0.0)))
        lng_delta = max(-1.0, min(1.0, (t_lng or 0.0) - (o_lng or 0.0)))
        end_y = max(12.0, min(60.0, 38.0 - lat_delta * 18.0))
        control_1_y = max(10.0, min(60.0, 52.0 - lat_delta * 10.0))
        control_2_y = max(10.0, min(60.0, 24.0 - lat_delta * 8.0))
        control_1_x = max(30.0, min(58.0, 42.0 + lng_delta * 12.0))
        control_2_x = max(82.0, min(110.0, 96.0 + lng_delta * 12.0))
    else:
        control_1_x = 42.0
        control_1_y = 48.0
        control_2_x = 96.0
        control_2_y = 24.0
    return (
        f"M {start_x:.1f} {start_y:.1f} "
        f"C {control_1_x:.1f} {control_1_y:.1f}, {control_2_x:.1f} {control_2_y:.1f}, {end_x:.1f} {end_y:.1f}"
    )


def _property_progress_route_preview_rows(
    *,
    run_summary: dict[str, object],
    property_preferences: dict[str, object],
) -> list[dict[str, str]]:
    ranked_candidates = [
        dict(row)
        for row in list(run_summary.get("ranked_candidates") or [])
        if isinstance(row, dict)
    ]
    if not ranked_candidates:
        return []
    candidate = ranked_candidates[0]
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    if isinstance(candidate.get("property_facts_json"), dict):
        facts = {**facts, **dict(candidate.get("property_facts_json") or {})}
    if isinstance(facts.get("listing_research_snapshot"), dict):
        facts = {**dict(facts.get("listing_research_snapshot") or {}), **facts}

    origin_lat = facts.get("map_lat") or facts.get("lat") or facts.get("latitude")
    origin_lng = facts.get("map_lng") or facts.get("lng") or facts.get("lon") or facts.get("longitude")
    rows: list[dict[str, str]] = []
    family_filters_active = _property_family_filters_active(property_preferences)

    commute_destination = str(property_preferences.get("commute_destination") or "").strip()
    if bool(property_preferences.get("enable_commute_research")) and commute_destination:
        commute_specs = (
            ("transit", "Transit", int(property_preferences.get("max_commute_minutes_transit") or 0)),
            ("driving", "Car", int(property_preferences.get("max_commute_minutes_drive") or 0)),
            ("bicycling", "Bike", int(property_preferences.get("max_commute_minutes_bike") or 0)),
            ("walking", "Foot", int(property_preferences.get("max_commute_minutes_walk") or 0)),
        )
        selected_mode, mode_label, mode_minutes = next(
            ((mode, label, minutes) for mode, label, minutes in commute_specs if minutes > 0),
            ("transit", "Transit", 0),
        )
        detail = (
            f"{mode_label} <= {mode_minutes} min"
            if mode_minutes > 0
            else f"{mode_label} route from the property"
        )
        rows.append(
            {
                "title": commute_destination,
                "label": "Your route",
                "detail": detail,
                "mode_label": mode_label,
                "map_url": _property_candidate_directions_url(
                    candidate,
                    target_query=commute_destination,
                    mode=selected_mode,
                ),
                "preview_path": _property_route_preview_path(
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                ),
            }
        )

    route_specs = (
        ("School", "nearest_school_m", "nearest_school_name", "nearest_school_lat", "nearest_school_lng", "transit", True),
        ("Supermarket", "nearest_supermarket_m", "nearest_supermarket_name", "nearest_supermarket_lat", "nearest_supermarket_lng", "walking", False),
        ("Playground", "nearest_playground_m", "nearest_playground_name", "nearest_playground_lat", "nearest_playground_lng", "walking", True),
        ("Pharmacy", "nearest_pharmacy_m", "nearest_pharmacy_name", "nearest_pharmacy_lat", "nearest_pharmacy_lng", "walking", False),
        ("Underground", "nearest_subway_m", "nearest_subway_name", "nearest_subway_lat", "nearest_subway_lng", "transit", False),
    )
    for label, distance_key, name_key, lat_key, lng_key, mode, family_only in route_specs:
        if family_only and not family_filters_active:
            continue
        raw_distance = facts.get(distance_key)
        if raw_distance in (None, "", []):
            continue
        try:
            meters = int(float(raw_distance))
        except Exception:
            continue
        place_name = str(facts.get(name_key) or label).strip() or label
        rows.append(
            {
                "title": place_name,
                "label": label,
                "detail": f"{meters} m from the property",
                "mode_label": "Transit" if mode == "transit" else "Walk",
                "map_url": _property_candidate_directions_url(
                    candidate,
                    target_lat=facts.get(lat_key),
                    target_lng=facts.get(lng_key),
                    target_query=place_name,
                    mode=mode,
                ),
                "preview_path": _property_route_preview_path(
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                    target_lat=facts.get(lat_key),
                    target_lng=facts.get(lng_key),
                ),
            }
        )
        if len(rows) >= 3:
            break
    return rows[:3]


def _property_candidate_preview_image(candidate: dict[str, object]) -> str:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    for key in (
        "preview_image_url",
        "thumbnail_url",
        "image_url",
        "hero_image_url",
    ):
        value = str(candidate.get(key) or facts.get(key) or "").strip()
        if value.startswith(("https://", "/")) and "diorama-preview" not in value and "telegram-preview" not in value:
            return value
    for key in ("media_urls_json", "photo_urls_json", "image_urls_json"):
        values = facts.get(key) or candidate.get(key)
        if isinstance(values, (list, tuple)):
            for value in values:
                normalized = str(value or "").strip()
                if normalized.startswith(("https://", "/")):
                    return normalized
    return ""


def _property_candidate_orientation_preview(candidate: dict[str, object]) -> dict[str, str]:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    label = str(facts.get("postal_name") or facts.get("city") or facts.get("address") or "Wider area").strip() or "Wider area"
    try:
        lat = float(facts.get("map_lat") or facts.get("lat") or 0.0)
    except Exception:
        lat = 0.0
    try:
        lng = float(facts.get("map_lng") or facts.get("lng") or 0.0)
    except Exception:
        lng = 0.0
    if lat or lng:
        pin_x = 24.0 + abs(lng % 1.0) * 72.0
        pin_y = 24.0 + (1.0 - abs(lat % 1.0)) * 48.0
    else:
        digest = hashlib.sha1(label.lower().encode("utf-8")).digest()
        pin_x = 28.0 + (digest[0] / 255.0) * 64.0
        pin_y = 24.0 + (digest[1] / 255.0) * 48.0
    pin_x = max(18.0, min(102.0, pin_x))
    pin_y = max(16.0, min(76.0, pin_y))
    map_url = str(candidate.get("map_url") or "").strip() or _property_candidate_maps_url(candidate)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 92" role="img" aria-label="Wider area map preview">'
        '<rect width="120" height="92" rx="12" fill="#f6f1e6"/>'
        '<path d="M8 68 C28 54, 43 56, 59 48 S90 34, 112 18" fill="none" stroke="#d7cfbf" stroke-width="8" stroke-linecap="round"/>'
        '<path d="M14 24 C36 30, 58 20, 78 28 S102 38, 112 30" fill="none" stroke="#e4ddcf" stroke-width="5" stroke-linecap="round"/>'
        '<path d="M18 82 C38 76, 52 78, 68 68 S95 60, 108 66" fill="none" stroke="#ddd4c5" stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="{pin_x:.1f}" cy="{pin_y:.1f}" r="13" fill="#d34b4b" fill-opacity="0.18" />'
        f'<path d="M{pin_x:.1f} {pin_y - 12:.1f}c-5.8 0-10.5 4.7-10.5 10.5 0 7.8 10.5 19.1 10.5 19.1s10.5-11.3 10.5-19.1c0-5.8-4.7-10.5-10.5-10.5z" fill="#d34b4b"/>'
        f'<circle cx="{pin_x:.1f}" cy="{pin_y - 1.8:.1f}" r="4.2" fill="#fff7ee"/>'
        "</svg>"
    )
    return {
        "image_url": f"data:image/svg+xml;utf8,{urllib.parse.quote(svg, safe='/:;,+-=()%')}",
        "alt": f"Wider area around {label}",
        "title": label,
        "caption": "Open a larger map preview",
        "map_url": map_url,
    }


def _first_fact_text(facts: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = facts.get(key)
        if value in (None, "", []):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _bool_fact_text(facts: dict[str, object], *keys: str, label: str) -> str:
    for key in keys:
        value = facts.get(key)
        if isinstance(value, bool):
            return label if value else ""
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "ja", "available", "present"}:
            return label
    return ""


def _candidate_detail_sections(facts: dict[str, object]) -> dict[str, object]:
    object_rows = [
        ("Type", _first_fact_text(facts, "object_type", "property_type", "asset_type")),
        ("Building", _first_fact_text(facts, "building_type", "bautyp")),
        ("Condition", _first_fact_text(facts, "condition", "zustand")),
        ("Living area", _first_fact_text(facts, "area_display", "area_label") or (f"{facts.get('area_m2') or facts.get('area_sqm')} m2" if (facts.get("area_m2") or facts.get("area_sqm")) else "")),
        ("Rooms", _first_fact_text(facts, "rooms_display") or str(facts.get("rooms") or "").strip()),
        ("Floor", _first_fact_text(facts, "floor", "floor_label", "stockwerk")),
        ("Available", _first_fact_text(facts, "available_from", "available", "verfuegbar", "verfügbar")),
        ("Term", _first_fact_text(facts, "lease_term", "befristung")),
        ("Heating", _first_fact_text(facts, "heating", "heating_type")),
    ]
    cost_rows = [
        ("Rent / price", _first_fact_text(facts, "price_display", "rent_display")),
        ("Operating costs", _first_fact_text(facts, "operating_costs_display", "operating_costs_monthly_display")),
        ("Additional costs", _first_fact_text(facts, "additional_costs_display", "side_costs_display", "service_charges_display")),
        ("Deposit", _first_fact_text(facts, "deposit_display", "kaution_display")),
        ("Commission", _first_fact_text(facts, "commission_display", "maklerprovision_display")),
    ]
    feature_values = [
        _bool_fact_text(facts, "has_fitted_kitchen", "kitchen", label="Kitchen"),
        _bool_fact_text(facts, "has_cellar", "cellar", "keller", label="Cellar"),
        _bool_fact_text(facts, "has_garage", "garage", label="Garage"),
        _bool_fact_text(facts, "barrier_free", "accessible", label="Barrier-free"),
        _bool_fact_text(facts, "furnished", "has_furniture", label="Furnished"),
        _bool_fact_text(facts, "has_lift", "lift", "elevator", label="Lift"),
        _bool_fact_text(facts, "has_parking", "parking", label="Parking"),
        _bool_fact_text(facts, "has_storage_room", "storage_room", "abstellraum", label="Storage room"),
        _bool_fact_text(facts, "has_balcony", "balcony", label="Balcony"),
        _bool_fact_text(facts, "has_terrace", "terrace", label="Terrace"),
        _bool_fact_text(facts, "has_garden", "garden", label="Garden"),
        _bool_fact_text(facts, "has_loggia", "loggia", label="Loggia"),
    ]
    description_text = _first_fact_text(facts, "description", "object_description", "listing_description", "summary")
    location_text = _first_fact_text(facts, "location_description", "lage", "neighborhood_description", "micro_location_summary")
    energy_rows = [
        ("HWB", _first_fact_text(facts, "hwb", "hwb_kwh_m2_year")),
        ("HWB class", _first_fact_text(facts, "hwb_class", "hwb_energieklasse")),
        ("fGEE", _first_fact_text(facts, "f_gee", "fgee")),
        ("fGEE class", _first_fact_text(facts, "f_gee_class", "fgee_energieklasse")),
        ("Heating", _first_fact_text(facts, "heating", "heating_type")),
    ]
    return {
        "object_rows": [{"label": label, "value": value} for label, value in object_rows if str(value or "").strip()],
        "cost_rows": [{"label": label, "value": value} for label, value in cost_rows if str(value or "").strip()],
        "feature_values": [value for value in feature_values if value],
        "description_text": description_text,
        "location_text": location_text,
        "energy_rows": [{"label": label, "value": value} for label, value in energy_rows if str(value or "").strip()],
    }


def _group_property_provider_options(options: list[dict[str, object]]) -> list[dict[str, object]]:
    family_order = {
        "marketplace": 0,
        "core_portal": 0,
        "classified": 0,
        "shared_housing": 1,
        "corporate_landlord": 2,
        "municipal_housing": 3,
        "broker_direct": 1,
        "cooperative": 2,
        "public_housing": 3,
        "developer_projects": 4,
        "distressed_sales": 5,
        "community_signals": 6,
        "community_meta": 7,
    }
    family_headings = {
        "marketplace": ("Core marketplaces", "Primary broad-market search lanes for this country."),
        "core_portal": ("Core portals", "Primary broad-market search lanes for this country."),
        "classified": ("Classifieds", "Private and long-tail inventory with weaker structure and more duplicate risk."),
        "shared_housing": ("Shared housing", "Rooms, WG, sublet, and student-friendly sources that should not pollute standard family-home search."),
        "corporate_landlord": ("Direct landlords", "Large landlord-direct inventory that often carries better availability and operating details."),
        "municipal_housing": ("Municipal housing", "City-owned or public-sector housing supply with eligibility and application rules."),
        "broker_direct": ("Broker direct", "Broker-owned inventory and direct source lanes."),
        "cooperative": ("Cooperatives", "Genossenschaften and cooperative housing sources."),
        "public_housing": ("Public housing", "Municipal and public-housing-adjacent sources."),
        "developer_projects": ("Developer projects", "New-build and launch pipeline sources."),
        "distressed_sales": ("Court and auction", "Court-published and auction-style listings that need extra legal review."),
        "community_signals": ("Community signals", "Facebook, Telegram, and other weakly verified off-market hints."),
        "community_meta": ("Watch-tier meta", "Long-tail meta or watch-tier sources with lower trust."),
    }
    grouped: dict[str, list[dict[str, object]]] = {}
    for option in options:
        family = str(option.get("family") or "marketplace").strip() or "marketplace"
        grouped.setdefault(family, []).append(option)
    rows: list[dict[str, object]] = []
    for family, items in sorted(grouped.items(), key=lambda pair: (family_order.get(pair[0], 99), pair[0])):
        title, detail = family_headings.get(
            family,
            (str(family).replace("_", " ").title(), "Grouped by source family for a cleaner market setup."),
        )
        rows.append(
            {
                "key": family,
                "title": title,
                "detail": detail,
                "options": sorted(
                    items,
                    key=lambda item: (
                        str(item.get("trust_tier") or "").strip() != "trusted",
                        str(item.get("trust_tier") or "").strip() == "watch",
                        str(item.get("label") or "").strip().lower(),
                    ),
                ),
            }
        )
    return rows


def _property_market_filter_capabilities(country_code: str, region_code: str) -> dict[str, bool]:
    country = str(country_code or "").strip().upper() or "AT"
    region = str(region_code or "").strip().lower()
    defaults: dict[str, bool] = {"family_zoo": True}
    if country == "AT":
        regional = {
            "vienna": {"family_zoo": True},
            "salzburg": {"family_zoo": True},
            "styria": {"family_zoo": True},
            "upper_austria": {"family_zoo": False},
            "lower_austria": {"family_zoo": False},
            "burgenland": {"family_zoo": False},
            "carinthia": {"family_zoo": False},
            "tyrol": {"family_zoo": False},
            "vorarlberg": {"family_zoo": False},
        }
        return {**defaults, **regional.get(region, {"family_zoo": False})}
    if country == "DE":
        regional = {
            "berlin": {"family_zoo": True},
            "hamburg": {"family_zoo": True},
            "munich": {"family_zoo": True},
            "cologne": {"family_zoo": True},
            "frankfurt": {"family_zoo": True},
        }
        return {**defaults, **regional.get(region, defaults)}
    if country in {"UK", "FR", "ES", "IT", "NL", "BE", "CH"}:
        return defaults
    return defaults


def _provider_quality_rows(
    source_rows: list[dict[str, object]],
    provider_options: list[dict[str, object]],
) -> list[dict[str, str]]:
    option_map = {
        str(option.get("value") or "").strip().lower(): dict(option)
        for option in provider_options
        if str(option.get("value") or "").strip()
    }
    best_use_labels = {
        "marketplace": "broad market coverage",
        "core_portal": "broad market coverage",
        "classified": "private and weak-signal discovery",
        "shared_housing": "rooms, student, and sublet search",
        "corporate_landlord": "structured landlord-direct inventory",
        "municipal_housing": "public and eligibility-gated housing",
        "broker_direct": "high-signal direct inventory",
        "cooperative": "cooperative and family housing",
        "public_housing": "municipal and public lanes",
        "developer_projects": "new-build pipeline",
        "distressed_sales": "court and auction scans",
        "community_signals": "weak-signal off-market leads",
        "community_meta": "watch-tier long tail",
    }
    rows: list[dict[str, str]] = []
    for raw in source_rows[:8]:
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").strip().lower()
        option = option_map.get(platform, {})
        label = str(option.get("label") or raw.get("source_label") or platform or "Provider").strip() or "Provider"
        family = str(raw.get("provider_family") or option.get("family") or "marketplace").strip().lower() or "marketplace"
        trust = str(raw.get("provider_trust_tier") or option.get("trust_tier") or "standard").strip().lower() or "standard"
        scanned_total = 0
        shortlist_total = 0
        floorplan_filtered_total = 0
        review_total = 0
        tour_total = 0
        repair_opened_total = 0
        repair_existing_total = 0
        repair_task_total = 0
        try:
            scanned_total = max(int(float(raw.get("scanned_listing_total") or raw.get("listing_total") or 0)), 0)
            shortlist_total = max(int(float(raw.get("high_fit_total") or 0)), 0)
            floorplan_filtered_total = max(int(float(raw.get("filtered_floorplan_total") or 0)), 0)
            review_total = max(int(float(raw.get("review_created_total") or 0)) + int(float(raw.get("review_existing_total") or 0)), 0)
            tour_total = max(int(float(raw.get("tour_created_total") or 0)) + int(float(raw.get("tour_existing_total") or 0)), 0)
            repair_opened_total = max(int(float(raw.get("provider_repair_task_opened_total") or 0)), 0)
            repair_existing_total = max(int(float(raw.get("provider_repair_task_existing_total") or 0)), 0)
            repair_task_total = repair_opened_total + repair_existing_total
        except Exception:
            pass
        high_fit_rate = f"{round((shortlist_total / scanned_total) * 100)}%" if scanned_total else "n/a"
        floorplan_completeness = f"{round(max(0.0, 1.0 - (floorplan_filtered_total / scanned_total)) * 100)}%" if scanned_total else "n/a"
        tour_success = f"{round((tour_total / review_total) * 100)}%" if review_total else ("0%" if shortlist_total else "n/a")
        detail_parts = [
            f"{shortlist_total} shortlisted",
            f"{high_fit_rate} high-fit rate",
            f"{floorplan_completeness} floorplan completeness",
            f"{tour_success} tour readiness",
            f"best for {best_use_labels.get(family, family.replace('_', ' '))}",
        ]
        if floorplan_filtered_total:
            detail_parts.append(f"{floorplan_filtered_total} layout check{'s' if floorplan_filtered_total != 1 else ''} still unverified")
        rows.append(
            {
                "title": label,
                "detail": " | ".join(detail_parts),
                "tag": f"{trust.title()} · {family.replace('_', ' ').title()}",
            }
        )
    if not rows:
        rows.append(
            {
                "title": "Provider quality will appear after the first run",
                "detail": "Search at least one source before PropertyQuarry can compare shortlist yield, layout proof, and tour readiness.",
                "tag": "Waiting",
            }
        )
    return rows


def _property_search_guard_rows(
    *,
    preferences: dict[str, object],
    run_summary: dict[str, object],
    source_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    target_parts = [
        str(preferences.get("location_query") or "").strip(),
        str(preferences.get("region_code") or "").strip().replace("_", " ").title(),
        str(preferences.get("country_code") or "").strip().upper(),
    ]
    target_label = " · ".join(dict.fromkeys(part for part in target_parts if part))
    rows: list[dict[str, str]] = [
        {
            "title": "Target area guard",
            "detail": (
                f"Target: {target_label}. Outside-area candidates are suppressed before any filter-relaxation prompt."
                if target_label
                else "No narrow target area is set. Country-wide or broad-region results may appear."
            ),
            "tag": "Location",
        }
    ]
    outside_total = 0
    weak_filter_sources: list[str] = []
    no_plan_total = 0
    for source in source_rows:
        try:
            outside_total += max(int(float(source.get("location_mismatch_candidate_total") or 0)), 0)
        except Exception:
            pass
        try:
            no_plan_total += max(int(float(source.get("filtered_floorplan_total") or 0)), 0)
        except Exception:
            pass
        pushdown = dict(source.get("provider_filter_pushdown") or {}) if isinstance(source.get("provider_filter_pushdown"), dict) else {}
        if str(pushdown.get("filter_strength") or "").strip() == "weak_search_then_post_filter":
            weak_filter_sources.append(str(source.get("source_label") or source.get("platform") or "Provider").strip())
    if outside_total:
        rows.append(
            {
                "title": "Outside-area results suppressed",
                "detail": f"{outside_total} candidate{' was' if outside_total == 1 else 's were'} rejected before ranking because the provider returned locations outside the selected area.",
                "tag": "Suppressed",
            }
        )
    held_back = 0
    try:
        held_back = max(int(float(run_summary.get("notification_budget_suppressed_total") or 0)), 0)
    except Exception:
        held_back = 0
    if held_back:
        rows.append(
            {
                "title": "Alert budget applied",
                "detail": f"{held_back} lower-ranked candidate{' was' if held_back == 1 else 's were'} kept in the table instead of sent as messages.",
                "tag": "Messages",
            }
        )
    if weak_filter_sources:
        rows.append(
            {
                "title": "Source filters are limited",
                "detail": f"{', '.join(weak_filter_sources[:3])} could not apply every filter directly, so PropertyQuarry checked the listings after reading them.",
                "tag": "Source",
            }
        )
    if no_plan_total:
        rows.append(
            {
                "title": "Layout proof rule",
                "detail": f"{no_plan_total} candidate{' still needs' if no_plan_total == 1 else 's still need'} verified layout evidence.",
                "tag": "Evidence",
            }
        )
    return rows[:5]


def _property_suppression_rows(
    *,
    run_summary: dict[str, object],
    source_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    counters = {
        "Outside selected area": 0,
        "Missing floorplan evidence": 0,
        "Below fit threshold": 0,
        "Wrong property type": 0,
        "Outside area/size rule": 0,
        "Availability mismatch": 0,
        "Duplicate listing": 0,
        "Alert budget": 0,
    }
    source_labels: dict[str, set[str]] = {key: set() for key in counters}
    field_map = (
        ("Outside selected area", "location_mismatch_candidate_total"),
        ("Missing floorplan evidence", "filtered_floorplan_total"),
        ("Below fit threshold", "filtered_low_fit_total"),
        ("Wrong property type", "filtered_property_type_total"),
        ("Outside area/size rule", "filtered_area_total"),
        ("Availability mismatch", "filtered_availability_total"),
        ("Duplicate listing", "duplicate_listing_total"),
        ("Alert budget", "notification_budget_suppressed_total"),
    )
    for source in source_rows:
        source_label = str(source.get("source_label") or source.get("platform") or "Provider").strip() or "Provider"
        for label, field_name in field_map:
            try:
                value = max(int(float(source.get(field_name) or 0)), 0)
            except Exception:
                value = 0
            if value:
                counters[label] += value
                source_labels[label].add(source_label)
    try:
        summary_budget = max(int(float(run_summary.get("notification_budget_suppressed_total") or 0)), 0)
    except Exception:
        summary_budget = 0
    if summary_budget > counters["Alert budget"]:
        counters["Alert budget"] = summary_budget
    action_map = {
        "Outside selected area": "Keep suppressed unless you widen the target area.",
        "Missing floorplan evidence": "These are not invalid. PropertyQuarry is still looking for floorplans in photos, PDFs, downloads, and 360 media.",
        "Below fit threshold": "Lower the fit threshold only for a broader discovery run.",
        "Wrong property type": "Change property category if these should be included.",
        "Outside area/size rule": "Relax area limits only after reviewing the near-miss table.",
        "Availability mismatch": "Adjust timing if move-in date is flexible.",
        "Duplicate listing": "No action needed; duplicates stay collapsed.",
        "Alert budget": "Increase daily/weekly message limits or review the held-back table.",
    }
    rows: list[dict[str, str]] = []
    for label, total in counters.items():
        if total <= 0:
            continue
        providers = ", ".join(sorted(source_labels[label])[:3])
        rows.append(
            {
                "title": label,
                "detail": f"{total} candidate{' was' if total == 1 else 's were'} filtered out. {action_map[label]}",
                "tag": providers or "Search rule",
                "action_label": {
                    "Outside selected area": "Review area",
                    "Missing floorplan evidence": "Recover floorplans",
                    "Below fit threshold": "Show near misses",
                    "Wrong property type": "Edit category",
                    "Outside area/size rule": "Relax size",
                    "Availability mismatch": "Edit timing",
                    "Duplicate listing": "Keep collapsed",
                    "Alert budget": "Edit alert budget",
                }.get(label, "Review rule"),
            }
        )
    return rows[:8]


def _delivery_proof_rows(run_summary: dict[str, object]) -> list[dict[str, str]]:
    neuronwriter_statuses: list[str] = []
    for key in (
        "dossier_writer_neuronwriter_status",
        "notification_neuronwriter_status",
        "review_page_neuronwriter_status",
    ):
        value = str(run_summary.get(key) or "").strip()
        if value:
            neuronwriter_statuses.append(value)
    for source in list(run_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        for key in (
            "dossier_writer_neuronwriter_status",
            "notification_neuronwriter_status",
            "review_page_neuronwriter_status",
        ):
            value = str(source.get(key) or "").strip()
            if value:
                neuronwriter_statuses.append(value)
    normalized_neuronwriter_statuses = sorted(set(neuronwriter_statuses))
    if normalized_neuronwriter_statuses:
        neuronwriter_detail = "Editorial pass status: " + ", ".join(normalized_neuronwriter_statuses)
        neuronwriter_tag = "Checked"
    else:
        neuronwriter_detail = "Dossiers, review pages, email, and Telegram notifications use the redacted NeuronWriter editorial lane when the integration is configured; private facts remain claim-bound."
        neuronwriter_tag = "Required"
    try:
        telegram_sent = max(int(float(run_summary.get("telegram_sent_total") or run_summary.get("notified_total") or 0)), 0)
    except Exception:
        telegram_sent = 0
    try:
        tour_total = max(int(float(run_summary.get("tour_created_total") or 0)) + int(float(run_summary.get("tour_existing_total") or 0)), 0)
    except Exception:
        tour_total = 0
    try:
        packet_total = max(int(float(run_summary.get("packet_created_total") or run_summary.get("review_created_total") or 0)), 0)
    except Exception:
        packet_total = 0
    return [
        {
            "title": "Writing quality check",
            "detail": neuronwriter_detail,
            "tag": neuronwriter_tag,
        },
        {
            "title": "Message links",
            "detail": "Messages render links as titled buttons or titled HTML links, so raw full URLs are not visible in chat copy.",
            "tag": "Hard gate",
        },
        {
            "title": "Generated files",
            "detail": f"{packet_total} packet receipts, {tour_total} tour receipts, {telegram_sent} Telegram notification receipts summarized for this run.",
            "tag": "Visible proof",
        },
    ]


def _artifact_receipt_rows(run_summary: dict[str, object]) -> list[dict[str, str]]:
    rows = [dict(row) for row in required_artifact_receipt_rows()]
    try:
        telegram_sent = max(int(float(run_summary.get("telegram_sent_total") or run_summary.get("notified_total") or 0)), 0)
    except Exception:
        telegram_sent = 0
    try:
        tour_total = max(int(float(run_summary.get("tour_created_total") or 0)) + int(float(run_summary.get("tour_existing_total") or 0)), 0)
    except Exception:
        tour_total = 0
    try:
        flythrough_total = max(int(float(run_summary.get("flythrough_rendered_total") or 0)) + int(float(run_summary.get("flythrough_existing_total") or 0)), 0)
    except Exception:
        flythrough_total = 0
    rows.append(
        {
            "title": "Current run receipts",
            "detail": f"{tour_total} 3D tour receipts, {flythrough_total} fly-through receipts, {telegram_sent} Telegram sends recorded in this run summary.",
            "tag": "Run proof",
        }
    )
    return rows


def _official_risk_posture_rows(official: dict[str, object]) -> list[dict[str, str]]:
    rows = [dict(row) for row in list(official.get("sources") or []) if isinstance(row, dict)]
    if not rows:
        return []
    total = len(rows)
    official_total = 0
    partial_total = 0
    gap_total = 0
    flagged_total = 0
    review_total = 0
    verified_total = 0
    low_conf_total = 0
    for row in rows:
        availability = str(row.get("availability") or "").strip().lower()
        verification_state = str(row.get("verification_state") or "").strip().lower()
        confidence = str(row.get("confidence") or "").strip().lower()
        if availability == "official_dataset":
            official_total += 1
        elif availability == "partial_official":
            partial_total += 1
        if availability in {"municipal_gap", "source_gap"} or verification_state == "source_gap":
            gap_total += 1
        if verification_state == "flagged":
            flagged_total += 1
        if verification_state in {"flagged", "needs_review", "source_gap", "stale"}:
            review_total += 1
        if verification_state in {"verified", "confirmed", "cleared"}:
            verified_total += 1
        if confidence == "low":
            low_conf_total += 1
    if gap_total:
        headline = "Manual clearance required"
        headline_detail = f"{gap_total} risk lane(s) still depend on municipality-specific or missing official evidence."
        headline_tag = "Source gap"
    elif flagged_total:
        headline = "Official sources attached, risks still flagged"
        headline_detail = f"{flagged_total} lane(s) remain flagged and still need manual clearance before this read is trustworthy."
        headline_tag = "Flagged"
    elif review_total:
        headline = "Authority coverage attached, review still open"
        headline_detail = f"{review_total} lane(s) still need a manual confirmation pass even though official sources are already attached."
        headline_tag = "Review"
    else:
        headline = "Authority coverage in place"
        headline_detail = "All active risk lanes already have attached authority coverage and no unresolved source-gap blockers."
        headline_tag = "Ready"
    next_steps: list[str] = []
    for row in rows:
        verification_state = str(row.get("verification_state") or "").strip().lower()
        availability = str(row.get("availability") or "").strip().lower()
        required_next_step = str(row.get("required_next_step") or "").strip()
        if verification_state not in {"flagged", "needs_review", "source_gap", "stale"} and availability not in {"municipal_gap", "source_gap"}:
            continue
        if required_next_step and required_next_step not in next_steps:
            next_steps.append(required_next_step)
    coverage_parts = [f"{total} lanes attached", f"{official_total} official", f"{partial_total} partial", f"{gap_total} gaps"]
    verification_parts = [f"{verified_total} verified", f"{flagged_total} flagged", f"{review_total} still open"]
    response = [
        {"title": headline, "detail": headline_detail, "tag": headline_tag},
        {"title": "Coverage", "detail": " | ".join(coverage_parts), "tag": str(official.get("country_code") or "").strip() or "Market"},
        {"title": "Verification", "detail": " | ".join(verification_parts), "tag": f"{low_conf_total} low confidence" if low_conf_total else "Confidence ok"},
    ]
    if next_steps:
        response.append(
            {
                "title": "Next authority step",
                "detail": " | ".join(next_steps[:2]),
                "tag": "Manual proof",
            }
        )
    updated_at = str(official.get("updated_at") or "").strip()
    if updated_at:
        response.append(
            {
                "title": "Evidence snapshot",
                "detail": updated_at.replace("T", " ").replace("+00:00", " UTC"),
                "tag": "Attached",
            }
        )
    return response


def _property_counterfactual_rows(
    *,
    preferences: dict[str, object],
    raw_preferences: dict[str, object] | None,
    run_summary: dict[str, object],
    provider_options: list[dict[str, object]],
    current_platform_cap: int,
) -> list[dict[str, object]]:
    def _sanitize_counterfactual_row(row: dict[str, object]) -> dict[str, object]:
        item = dict(row)
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        action_label = str(item.get("action_label") or "").strip()
        if title.lower() == "pending layout proof":
            item["title"] = "Missing floorplan evidence"
            if detail:
                item["detail"] = detail.replace("layout proof", "floorplan evidence")
            if action_label.lower() == "run layout recovery":
                item["action_label"] = "Recover floorplans"
        return item

    rows: list[dict[str, object]] = [
        _sanitize_counterfactual_row(dict(row))
        for row in list(run_summary.get("search_broaden_suggestions") or [])
        if isinstance(row, dict) and str(row.get("title") or "").strip()
    ]

    def _positive_int(value: object, default: int = 0) -> int:
        try:
            return max(0, int(float(str(value or "").strip())))
        except Exception:
            return default

    def _has_explicit_numeric_filter(source: dict[str, object] | None, key: str) -> bool:
        raw_source = dict(source or {})
        nested = raw_source.get("raw_preferences")
        if isinstance(nested, dict):
            raw_source = dict(nested)
        if key not in raw_source:
            return False
        value = raw_source.get(key)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        try:
            return int(float(str(value).strip())) > 0
        except Exception:
            return False

    def _sum_source_total(field_name: str) -> int:
        total = 0
        for source in list(run_summary.get("sources") or []):
            if not isinstance(source, dict):
                continue
            try:
                total += max(0, int(float(source.get(field_name) or 0)))
            except Exception:
                continue
        return total

    current_score = _positive_int(preferences.get("min_match_score"), 0)
    low_fit_total = _sum_source_total("filtered_low_fit_total")
    outside_area_or_size_total = _sum_source_total("filtered_area_total")
    outside_selected_area_total = _sum_source_total("location_mismatch_candidate_total")
    if current_score > 35:
        next_score = 35 if current_score <= 45 else max(35, current_score - 10)
        rows.append(
            {
                "title": f"Lower the match threshold to {next_score}",
                "detail": "Keep more watch-tier candidates in the next sweep instead of filtering them out at the current score gate.",
                "tag": "Threshold",
                "action_label": f"Apply {next_score}/80",
                "adjustments": {"min_match_score": next_score},
                "affected_total": low_fit_total,
            }
        )

    filtered_floorplan_total = _positive_int(run_summary.get("filtered_floorplan_total"), 0)
    if bool(preferences.get("require_floorplan")) and filtered_floorplan_total > 0:
        rows.append(
            {
                "title": "Try a discovery run without requiring layout proof",
                "detail": f"{filtered_floorplan_total} listing(s) were filtered out because layout proof was not verified yet. Use this only to inspect the wider market, then restore the requirement.",
                "tag": "Research",
                "action_label": "Run discovery pass",
                "adjustments": {"require_floorplan": False},
                "affected_total": filtered_floorplan_total,
            }
        )

    country_code = str(preferences.get("country_code") or "").strip().upper()
    region_code = str(preferences.get("region_code") or "").strip().lower()
    if country_code == "AT" and region_code == "vienna" and not bool(preferences.get("all_of_vienna")):
        rows.append(
            {
                "title": "Expand from district picks to all Vienna",
                "detail": "Keep Vienna selected but stop suppressing the rest of the city in the next pass.",
                "tag": "Area",
                "action_label": "Use all Vienna",
                "adjustments": {"all_of_vienna": True, "location_query": "Vienna", "custom_location_query": ""},
                "affected_total": outside_selected_area_total,
            }
        )

    selected_platforms = [
        str(value).strip()
        for value in list(preferences.get("selected_platforms") or [])
        if str(value).strip()
    ]
    cap = max(0, int(current_platform_cap or 0))
    available_platforms = [
        str(option.get("value") or "").strip()
        for option in provider_options
        if str(option.get("value") or "").strip()
    ]
    widened_platforms = list(dict.fromkeys([*selected_platforms, *available_platforms]))
    if cap > 0:
        widened_platforms = widened_platforms[:cap]
    if len(widened_platforms) > len(selected_platforms):
        rows.append(
            {
                "title": f"Widen the provider batch to {len(widened_platforms)} sources",
                "detail": "Use the full provider allowance on the current plan before changing the rest of the brief.",
                "tag": "Providers",
                "action_label": "Use full provider cap",
                "adjustments": {"selected_platforms": widened_platforms},
                "affected_total": 0,
            }
        )

    current_budget = _positive_int(preferences.get("max_price_eur"), 0)
    explicit_budget = _has_explicit_numeric_filter(raw_preferences, "max_price_eur")
    if current_budget > 0 and explicit_budget:
        next_budget = current_budget + max(25000, int(round(current_budget * 0.1)))
        rows.append(
            {
                "title": "Test a wider budget ceiling",
                "detail": "Run one broader sweep before discarding the market entirely if price pressure may be the real bottleneck.",
                "tag": "Budget",
                "action_label": f"Raise to EUR {next_budget:,}".replace(",", ","),
                "adjustments": {"max_price_eur": next_budget},
                "affected_total": outside_area_or_size_total,
            }
        )

    strict_distance_keys = [
        "max_distance_to_market_m",
        "max_distance_to_hardware_store_m",
        "max_distance_to_medical_care_m",
        "max_distance_to_library_m",
        "max_distance_to_public_pool_m",
        "max_distance_to_theatre_m",
    ]
    strict_distance_count = sum(1 for key in strict_distance_keys if _positive_int(preferences.get(key), 0) > 0)
    if strict_distance_count >= 2:
        relaxed_adjustments: dict[str, object] = {}
        for key in strict_distance_keys:
            current_value = _positive_int(preferences.get(key), 0)
            if current_value > 0:
                relaxed_adjustments[key] = int(round(current_value * 1.35))
        rows.append(
            {
                "title": "Relax the stricter everyday-distance caps",
                "detail": "Keep the same lifestyle intent but widen the walk radius enough to recover borderline candidates.",
                "tag": "Alltag",
                "action_label": "Relax distance caps",
                "adjustments": relaxed_adjustments,
                "affected_total": outside_area_or_size_total,
            }
        )

    deduped: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    for row in rows:
        title = str(row.get("title") or "").strip().lower()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        deduped.append(row)
    if not deduped:
        deduped.append(
            {
                "title": "Reopen the brief with broader constraints",
                "detail": "Keep the same market, but reopen the brief so you can lower the score gate, widen providers, or relax one hard filter before the next sweep.",
                "tag": "Reset",
                "action_label": "Reopen brief",
                "adjustments": {},
            }
        )
    return deduped[:5]


def _property_preference_schema() -> dict[str, object]:
    from app.api.routes.product_api_contracts import _PROPERTY_PREFERENCE_VALUE_SPECS

    category_labels = {
        "constraint": "Hard rule",
        "soft_preference": "Preference",
        "aversion": "Avoid",
    }
    value_hints = {
        "bool": "Leave empty for yes, or enter true/false.",
        "positive_number": "Enter a number.",
        "text_list": "Enter comma-separated values.",
    }
    categories: dict[str, dict[str, object]] = {}
    for category, key in sorted(_PROPERTY_PREFERENCE_VALUE_SPECS):
        value_kind = str(_PROPERTY_PREFERENCE_VALUE_SPECS[(category, key)])
        bucket = categories.setdefault(
            category,
            {
                "label": category_labels.get(category, category.replace("_", " ").title()),
                "keys": [],
            },
        )
        bucket["keys"].append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "value_kind": value_kind,
                "hint": value_hints.get(value_kind, "Enter a value."),
            }
        )
    return {"categories": categories}


def _property_region_options(country_code: str) -> list[dict[str, str]]:
    from app.services.property_market_catalog import normalize_country_code, region_options_for_country

    catalogs: dict[str, list[dict[str, str]]] = {
        "AT": [
            {"value": "vienna", "label": "Vienna", "detail": "Wien and the close commuter ring"},
            {"value": "austria", "label": "All Austria", "detail": "Nationwide Austrian search"},
            {"value": "lower_austria", "label": "Lower Austria", "detail": "St. Poelten, Baden, Krems, Wiener Neustadt"},
            {"value": "upper_austria", "label": "Upper Austria", "detail": "Linz, Wels, Steyr"},
            {"value": "styria", "label": "Styria", "detail": "Graz and the southern corridor"},
            {"value": "salzburg", "label": "Salzburg", "detail": "City and surroundings"},
            {"value": "tyrol", "label": "Tyrol", "detail": "Innsbruck and Tyrolean centres"},
            {"value": "vorarlberg", "label": "Vorarlberg", "detail": "Bregenz, Dornbirn, Feldkirch"},
            {"value": "carinthia", "label": "Carinthia", "detail": "Klagenfurt and Villach"},
            {"value": "burgenland", "label": "Burgenland", "detail": "Eisenstadt and the eastern commuter belt"},
        ],
    }
    normalized_country = normalize_country_code(country_code)
    if normalized_country in catalogs:
        return list(catalogs[normalized_country])
    return region_options_for_country(normalized_country)


def _property_location_options(country_code: str, region_code: str = "") -> list[dict[str, str]]:
    from app.services.property_market_catalog import location_options_for_country_region, normalize_country_code

    austria_catalogs: dict[str, list[dict[str, str]]] = {
        "austria": [
            {"value": "Österreich", "label": "All Austria", "detail": "Nationwide"},
            {"value": "Niederösterreich", "label": "Lower Austria", "detail": "State-wide"},
            {"value": "Oberösterreich", "label": "Upper Austria", "detail": "State-wide"},
            {"value": "Steiermark", "label": "Styria", "detail": "State-wide"},
            {"value": "Salzburg", "label": "Salzburg", "detail": "State-wide"},
            {"value": "Kärnten", "label": "Carinthia", "detail": "State-wide"},
            {"value": "Burgenland", "label": "Burgenland", "detail": "State-wide"},
            {"value": "Tirol", "label": "Tyrol", "detail": "State-wide"},
            {"value": "Vorarlberg", "label": "Vorarlberg", "detail": "State-wide"},
        ],
        "vienna": [
            {"value": "1010 Vienna", "label": "1010 Vienna", "detail": "Innere Stadt"},
            {"value": "1020 Vienna", "label": "1020 Vienna", "detail": "Leopoldstadt"},
            {"value": "1030 Vienna", "label": "1030 Vienna", "detail": "Landstrasse"},
            {"value": "1040 Vienna", "label": "1040 Vienna", "detail": "Wieden"},
            {"value": "1050 Vienna", "label": "1050 Vienna", "detail": "Margareten"},
            {"value": "1060 Vienna", "label": "1060 Vienna", "detail": "Mariahilf"},
            {"value": "1070 Vienna", "label": "1070 Vienna", "detail": "Neubau"},
            {"value": "1080 Vienna", "label": "1080 Vienna", "detail": "Josefstadt"},
            {"value": "1090 Vienna", "label": "1090 Vienna", "detail": "Alsergrund"},
            {"value": "1100 Vienna", "label": "1100 Vienna", "detail": "Favoriten"},
            {"value": "1110 Vienna", "label": "1110 Vienna", "detail": "Simmering"},
            {"value": "1120 Vienna", "label": "1120 Vienna", "detail": "Meidling"},
            {"value": "1130 Vienna", "label": "1130 Vienna", "detail": "Hietzing"},
            {"value": "1140 Vienna", "label": "1140 Vienna", "detail": "Penzing"},
            {"value": "1150 Vienna", "label": "1150 Vienna", "detail": "Rudolfsheim-Fuenfhaus"},
            {"value": "1160 Vienna", "label": "1160 Vienna", "detail": "Ottakring"},
            {"value": "1170 Vienna", "label": "1170 Vienna", "detail": "Hernals"},
            {"value": "1180 Vienna", "label": "1180 Vienna", "detail": "Waehring"},
            {"value": "1190 Vienna", "label": "1190 Vienna", "detail": "Doebling"},
            {"value": "1200 Vienna", "label": "1200 Vienna", "detail": "Brigittenau"},
            {"value": "1210 Vienna", "label": "1210 Vienna", "detail": "Floridsdorf"},
            {"value": "1220 Vienna", "label": "1220 Vienna", "detail": "Donaustadt"},
            {"value": "1230 Vienna", "label": "1230 Vienna", "detail": "Liesing"},
            {"value": "Klosterneuburg", "label": "Klosterneuburg", "detail": "Vienna outskirts"},
            {"value": "Mödling", "label": "Mödling", "detail": "South of Vienna"},
            {"value": "Purkersdorf", "label": "Purkersdorf", "detail": "West of Vienna"},
        ],
        "lower_austria": [
            {"value": "Niederösterreich", "label": "All Lower Austria", "detail": "State-wide"},
            {"value": "St. Poelten", "label": "St. Poelten", "detail": "Capital of Lower Austria"},
            {"value": "Krems", "label": "Krems", "detail": "Wachau corridor"},
            {"value": "Baden", "label": "Baden", "detail": "South of Vienna"},
            {"value": "Wiener Neustadt", "label": "Wiener Neustadt", "detail": "Southern rail corridor"},
            {"value": "Tulln", "label": "Tulln", "detail": "North-west of Vienna"},
        ],
        "upper_austria": [
            {"value": "Linz", "label": "Linz", "detail": "Capital of Upper Austria"},
            {"value": "Wels", "label": "Wels", "detail": "Central Upper Austria"},
            {"value": "Steyr", "label": "Steyr", "detail": "Industrial corridor"},
        ],
        "styria": [
            {"value": "Graz", "label": "Graz", "detail": "Capital of Styria"},
            {"value": "Leoben", "label": "Leoben", "detail": "Upper Styrian centre"},
            {"value": "Kapfenberg", "label": "Kapfenberg", "detail": "North of Graz corridor"},
        ],
        "salzburg": [
            {"value": "Salzburg", "label": "Salzburg", "detail": "City-wide"},
            {"value": "Hallein", "label": "Hallein", "detail": "South of Salzburg"},
        ],
        "tyrol": [
            {"value": "Innsbruck", "label": "Innsbruck", "detail": "City-wide"},
            {"value": "Hall in Tirol", "label": "Hall in Tirol", "detail": "East of Innsbruck"},
        ],
        "vorarlberg": [
            {"value": "Dornbirn", "label": "Dornbirn", "detail": "Rheintal centre"},
            {"value": "Bregenz", "label": "Bregenz", "detail": "Lake Constance"},
            {"value": "Feldkirch", "label": "Feldkirch", "detail": "Southern Vorarlberg"},
        ],
        "carinthia": [
            {"value": "Klagenfurt", "label": "Klagenfurt", "detail": "Capital of Carinthia"},
            {"value": "Villach", "label": "Villach", "detail": "West Carinthia"},
        ],
        "burgenland": [
            {"value": "Eisenstadt", "label": "Eisenstadt", "detail": "Capital of Burgenland"},
            {"value": "Neusiedl am See", "label": "Neusiedl am See", "detail": "North Burgenland"},
        ],
    }
    catalogs: dict[str, list[dict[str, str]]] = {
        "AT": list(austria_catalogs.get(str(region_code or "").strip().lower() or "vienna", austria_catalogs["vienna"])),
        "DE": [
            {"value": "Berlin Mitte", "label": "Berlin Mitte", "detail": "Central Berlin"},
            {"value": "Berlin Prenzlauer Berg", "label": "Berlin Prenzlauer Berg", "detail": "Family-friendly"},
            {"value": "Berlin Charlottenburg", "label": "Berlin Charlottenburg", "detail": "West Berlin"},
            {"value": "Munich", "label": "Munich", "detail": "City-wide"},
            {"value": "Hamburg", "label": "Hamburg", "detail": "City-wide"},
        ],
        "ES": [
            {"value": "Barcelona", "label": "Barcelona", "detail": "City-wide"},
            {"value": "Eixample", "label": "Eixample", "detail": "Central Barcelona"},
            {"value": "Madrid", "label": "Madrid", "detail": "City-wide"},
            {"value": "Valencia", "label": "Valencia", "detail": "City-wide"},
        ],
        "IT": [
            {"value": "Milan", "label": "Milan", "detail": "City-wide"},
            {"value": "Rome", "label": "Rome", "detail": "City-wide"},
            {"value": "Bologna", "label": "Bologna", "detail": "City-wide"},
        ],
        "FR": [
            {"value": "Paris", "label": "Paris", "detail": "City-wide"},
            {"value": "Lyon", "label": "Lyon", "detail": "City-wide"},
            {"value": "Marseille", "label": "Marseille", "detail": "City-wide"},
        ],
        "NL": [
            {"value": "Amsterdam", "label": "Amsterdam", "detail": "City-wide"},
            {"value": "Rotterdam", "label": "Rotterdam", "detail": "City-wide"},
            {"value": "Utrecht", "label": "Utrecht", "detail": "City-wide"},
        ],
        "UK": [
            {"value": "London", "label": "London", "detail": "City-wide"},
            {"value": "Manchester", "label": "Manchester", "detail": "City-wide"},
            {"value": "Bristol", "label": "Bristol", "detail": "City-wide"},
        ],
        "US": [
            {"value": "Brooklyn", "label": "Brooklyn", "detail": "New York City"},
            {"value": "Queens", "label": "Queens", "detail": "New York City"},
            {"value": "Jersey City", "label": "Jersey City", "detail": "New Jersey"},
            {"value": "San Francisco", "label": "San Francisco", "detail": "Bay Area"},
            {"value": "Boston", "label": "Boston", "detail": "City-wide"},
        ],
    }
    normalized_country = normalize_country_code(country_code)
    if normalized_country in catalogs:
        return list(catalogs[normalized_country])
    return location_options_for_country_region(normalized_country, region_code)


def _property_keyword_options() -> list[dict[str, str]]:
    return [
        {"value": "lift", "label": "Lift", "detail": "Elevator in the building"},
        {"value": "balcony", "label": "Balcony", "detail": "Outdoor private space"},
        {"value": "terrace", "label": "Terrace", "detail": "Large outdoor space"},
        {"value": "baugrund", "label": "Baugrund", "detail": "Building plot / land"},
        {"value": "seezugang", "label": "Seezugang", "detail": "Lake access or lakeside potential"},
        {"value": "wasserzugang", "label": "Wasserzugang", "detail": "Access to water"},
        {"value": "family", "label": "Family-friendly", "detail": "Good fit for children"},
        {"value": "playground nearby", "label": "Playground nearby", "detail": "Walkable play options"},
        {"value": "supermarket nearby", "label": "Supermarket nearby", "detail": "Daily errands close by"},
        {"value": "pharmacy nearby", "label": "Pharmacy nearby", "detail": "Healthcare basics nearby"},
        {"value": "underground nearby", "label": "Underground nearby", "detail": "Fast transit access"},
        {"value": "no gas", "label": "No gas heating", "detail": "Avoid gas-based systems"},
        {"value": "district heating", "label": "District heating", "detail": "Prefer Fernwärme"},
        {"value": "parking", "label": "Parking", "detail": "Car-friendly"},
        {"value": "pets allowed", "label": "Pets allowed", "detail": "Pet-friendly rules"},
        {"value": "quiet", "label": "Quiet", "detail": "Lower street noise"},
        {"value": "bright", "label": "Bright", "detail": "Good natural light"},
    ]


def humanize(value: str) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"


def status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "ready_to_connect", "ready_for_brief", "completed", "started", "available"}:
        return "good"
    if normalized in {"planned_business", "export_planned", "guided_manual", "bot_link_requested", "export_intake_complete", "import_acknowledged", "in_progress"}:
        return "warn"
    if normalized in {"credentials_missing", "planned_not_available", "not_selected", "anonymous"}:
        return "muted"
    return "muted"


def list_rows(values: object, fallback: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    if isinstance(values, (list, tuple, set)):
        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                rows.append(normalized)
    elif values:
        normalized = str(values).strip()
        if normalized:
            rows.append(normalized)
    return rows or [str(row) for row in fallback]


def row_item(title: str, detail: str, tag: str) -> dict[str, str]:
    return {"title": title, "detail": detail, "tag": tag}


def string_rows(values: object, fallback: tuple[str, ...], *, tag: str, detail: str) -> list[dict[str, str]]:
    return [row_item(value, detail, tag) for value in list_rows(values, fallback)]


def _compact_when(value: str | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback
    if "T" in normalized:
        return normalized.split("T", 1)[0]
    return normalized


def _property_candidate_ref(candidate: dict[str, object]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "tour_url", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def approval_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        reason = str(getattr(value, "reason", "") or "").strip()
        action_json = dict(getattr(value, "requested_action_json", {}) or {})
        action_name = humanize(str(action_json.get("action") or action_json.get("event_type") or "review"))
        title = reason or f"{action_name.capitalize()} needs approval"
        detail = " · ".join(
            part
            for part in (
                "Pending approval",
                action_name if action_name and action_name != "review" else "",
                f"Expires {_compact_when(getattr(value, 'expires_at', None), 'soon')}"
                if getattr(value, "expires_at", None)
                else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Pending approval", "Approval"))
    return rows


def human_task_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        raw_title = str(getattr(value, "brief", "") or "").strip()
        task_type = str(getattr(value, "task_type", "") or "follow_up")
        fallback_title = "Commitment" if task_type == "follow_up" else humanize(task_type).capitalize()
        title = raw_title or fallback_title
        priority = humanize(str(getattr(value, "priority", "") or "open"))
        role_required = humanize(str(getattr(value, "role_required", "") or "review"))
        why_human = str(getattr(value, "why_human", "") or "").strip()
        due_label = _compact_when(getattr(value, "sla_due_at", None), "")
        detail = " · ".join(
            part
            for part in (
                f"{priority.capitalize()} priority" if priority else "",
                role_required if role_required and role_required != "review" else "",
                f"Due {due_label}" if due_label else "",
                why_human if why_human else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Waiting on human review", "Task"))
    return rows


def delivery_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        recipient = str(getattr(value, "recipient", "") or "").strip()
        channel = humanize(str(getattr(value, "channel", "") or "delivery")).capitalize()
        title = recipient or f"{channel} delivery"
        attempt_count = int(getattr(value, "attempt_count", 0) or 0)
        next_attempt_at = _compact_when(getattr(value, "next_attempt_at", None), "")
        last_error = str(getattr(value, "last_error", "") or "").strip()
        detail = " · ".join(
            part
            for part in (
                channel,
                f"Attempt {attempt_count + 1}",
                f"Retry {next_attempt_at}" if next_attempt_at else "",
                last_error[:80] if last_error else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Queued for delivery", "Queued"))
    return rows


def channel_cards(channels: dict[str, Any]) -> list[dict[str, str]]:
    ordered = (
        ("google", "Google sign-in", "/integrations/google"),
        ("telegram", "Telegram", "/integrations/telegram"),
        ("whatsapp", "WhatsApp", "/integrations/whatsapp"),
    )
    cards: list[dict[str, str]] = []
    for key, label, href in ordered:
        channel = dict(channels.get(key) or {})
        cards.append(
            {
                "label": label,
                "href": href,
                "status": humanize(str(channel.get("status") or "not_selected")),
                "tone": status_tone(str(channel.get("status") or "not_selected")),
                "detail": str(channel.get("detail") or "Not configured yet."),
                "summary": str(channel.get("bundle_summary") or channel.get("history_import_posture") or ""),
            }
        )
    return cards


def app_section_payload(
    section: str,
    status: dict[str, object],
    *,
    live_feed: dict[str, object] | None = None,
    property_context: dict[str, object] | None = None,
) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    delivery_preferences = dict(status.get("delivery_preferences") or {})
    morning_memo = dict(delivery_preferences.get("morning_memo") or {})
    preview = dict(status.get("brief_preview") or {})
    channels = dict(status.get("channels") or {})
    cards = channel_cards(channels)
    selected = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    live = dict(live_feed or {})
    approvals = list(live.get("approvals") or [])
    human_tasks = list(live.get("human_tasks") or [])
    pending_delivery = list(live.get("pending_delivery") or [])
    status_label = humanize(str(status.get("status") or "draft"))
    ready_channels = sum(1 for card in cards if card["tone"] == "good")
    selected_count = len(selected) or len([card for card in cards if card["status"] != "not selected"]) or 0
    stats = [
        {"label": "Approvals", "value": str(len(approvals))},
        {"label": "Human tasks", "value": str(len(human_tasks))},
        {"label": "Queued delivery", "value": str(len(pending_delivery))},
        {
            "label": "Channels ready",
            "value": f"{ready_channels}/{selected_count}" if selected_count else str(ready_channels),
        },
    ]
    first_brief = list_rows(
        preview.get("first_brief_preview") or preview.get("first_brief"),
        ("Connect Google sign-in if you want a faster return path and verified account access.",),
    )
    suggested = list_rows(preview.get("suggested_actions"), ("Finish onboarding and request the first memo.",))
    trust_notes = list_rows(preview.get("trust_notes"), ("Keep approvals and retention rules explicit.",))
    people = list_rows(preview.get("top_contacts"), ("No people surfaced yet.",))
    themes = list_rows(preview.get("top_themes"), ("No themes surfaced yet.",))
    approvals_items = approval_rows(approvals)
    human_task_items = human_task_rows(human_tasks)
    pending_delivery_items = delivery_rows(pending_delivery)
    live_queue = (approvals_items + human_task_items)[:6]
    privacy_lines = [
        f"Retention: {humanize(str(privacy.get('retention_mode') or 'not set'))}",
        f"Drafts: {'allowed' if privacy.get('allow_drafts') else 'manual only'}",
        f"Action suggestions: {'allowed' if privacy.get('allow_action_suggestions') else 'off'}",
        f"Automatic briefs: {'allowed' if privacy.get('allow_auto_briefs') else 'off'}",
    ]
    if privacy.get("allow_auto_briefs"):
        privacy_lines.append(
            "Memo schedule: "
            + " · ".join(
                part
                for part in (
                    humanize(str(morning_memo.get("cadence") or "daily_morning")),
                    f"{morning_memo.get('delivery_time_local') or '08:00'} {morning_memo.get('timezone') or workspace.get('timezone') or 'UTC'}",
                    str(morning_memo.get("resolved_recipient_email") or "waiting for recipient"),
                )
                if str(part or "").strip()
            )
        )
    channel_lines = [f"{card['label']}: {card['status']} — {card['detail']}" for card in cards]
    channel_items = [row_item(card["label"], card["detail"], card["status"]) for card in cards]
    identity_posture_items = [
        row_item(
            "Keep identity boring",
            "Return through a secure email link, invite, or SSO before widening channel setup.",
            "Recommended",
        ),
        row_item(
            "Connect Google for workspace context",
            "Treat Google as optional account access first; only widen scopes later if the product truly needs them.",
            "Linked",
        ),
        row_item(
            "Link messaging channels later",
            "Treat Telegram and WhatsApp as optional linked channels, not the workspace core.",
            "Linked",
        ),
        row_item(
            "Keep work bounded",
            "Approvals, human tasks, and queued delivery stay explicit instead of hiding behind automation copy.",
            "Guardrail",
        ),
    ]
    follow_up_context_items = [
        row_item(title, "Keep the underlying promise, thread, or deadline attached to the work item.", "Context")
        for title in trust_notes
    ]
    property_state = dict(property_context or {})
    property_preferences = dict(property_state.get("preferences") or {})
    property_run = dict(property_state.get("run") or {})
    property_summary = dict(property_run.get("summary") or {})
    property_country_label = str(property_state.get("country_label") or "Austria")
    property_language_label = str(property_state.get("language_label") or "Deutsch")
    property_listing_mode_label = str(property_state.get("listing_mode_label") or "Rent")
    property_investment_research_mode_label = str(property_state.get("investment_research_mode_label") or "Off")
    property_type_label = str(property_state.get("property_type_label") or "Any type")
    property_provider_total_for_country = int(property_state.get("provider_total_for_country") or 0)
    selected_listing_mode = str(property_preferences.get("listing_mode") or "rent").strip().lower() or "rent"
    try:
        property_available_within_years_value = max(
            0,
            min(10, int(float(str(property_preferences.get("available_within_years") or "").strip()))),
        )
    except Exception:
        property_available_within_years_value = 0
    selected_region_code = str(property_preferences.get("region_code") or "").strip().lower()
    selected_all_of_vienna = bool(property_preferences.get("all_of_vienna"))
    country_options = [dict(option) for option in list(property_state.get("country_options") or []) if isinstance(option, dict)]
    language_options = [dict(option) for option in list(property_state.get("language_options") or []) if isinstance(option, dict)]
    listing_mode_options = [dict(option) for option in list(property_state.get("listing_mode_options") or []) if isinstance(option, dict)]
    investment_research_mode_options = [dict(option) for option in list(property_state.get("investment_research_mode_options") or []) if isinstance(option, dict)]
    property_type_options = [dict(option) for option in list(property_state.get("property_type_options") or []) if isinstance(option, dict)]
    selected_platforms = {
        str(value or "").strip()
        for value in (property_state.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    selected_country_code = str(property_preferences.get("country_code") or "AT").strip().upper() or "AT"
    platform_options = [
        dict(option)
        for option in list(property_state.get("platform_options") or [])
        if isinstance(option, dict)
    ]
    evidence_source_rows = [
        dict(option)
        for option in list(property_state.get("evidence_source_rows") or [])
        if isinstance(option, dict)
    ]
    try:
        from app.services.property_market_catalog import provider_options as property_provider_options

        known_values = {
            str(option.get("value") or "").strip().lower()
            for option in platform_options
            if str(option.get("value") or "").strip()
        }
        for option in property_provider_options(country_code=selected_country_code):
            value = str(option.get("value") or "").strip()
            if not value or value.lower() in known_values:
                continue
            platform_options.append(dict(option))
            known_values.add(value.lower())
    except Exception:
        pass
    if not evidence_source_rows:
        try:
            from app.services.property_market_catalog import evidence_source_options as property_evidence_source_options

            evidence_source_rows = [
                dict(option)
                for option in property_evidence_source_options(country_code=selected_country_code)
                if isinstance(option, dict)
            ]
        except Exception:
            evidence_source_rows = []
    selected_location_values = _csv_values(property_preferences.get("location_query"))
    selected_keyword_values = _csv_values(property_preferences.get("keywords"))
    region_options = _property_region_options(str(property_preferences.get("country_code") or "AT"))
    if not selected_region_code and region_options:
        selected_region_code = str(region_options[0].get("value") or "").strip().lower()
    if (
        str(property_preferences.get("country_code") or "AT").strip().upper() == "AT"
        and selected_region_code == "vienna"
        and not selected_location_values
        and str(property_preferences.get("location_query") or "").strip().lower() in {"vienna", "wien"}
    ):
        selected_all_of_vienna = True
    location_options = _property_location_options(
        str(property_preferences.get("country_code") or "AT"),
        selected_region_code,
    )
    keyword_options = _property_keyword_options()
    selected_location_values, custom_location_values = _split_known_and_custom_values(location_options, selected_location_values)
    selected_keyword_values, custom_keyword_values = _split_known_and_custom_values(keyword_options, selected_keyword_values)
    custom_location_query = str(property_preferences.get("custom_location_query") or ", ".join(custom_location_values)).strip()
    custom_keywords = str(property_preferences.get("custom_keywords") or ", ".join(custom_keyword_values)).strip()
    property_selected_platform_labels = [
        str(option.get("label") or option.get("value") or "").strip()
        for option in platform_options
        if str(option.get("value") or "").strip() in selected_platforms
    ]
    property_market_summary_items = [
        row_item("Country", property_country_label, "Market"),
        row_item("Browser language", property_language_label, "Research"),
        row_item("Search mode", property_listing_mode_label, "Mode"),
        row_item("Property type", property_type_label, "Type"),
    ]
    if selected_listing_mode == "buy":
        property_market_summary_items.append(row_item("Investment research", property_investment_research_mode_label, "Underwriting"))
    if property_available_within_years_value > 0:
        property_market_summary_items.append(
            row_item(
                "Move-in deadline",
                "Within 1 year" if property_available_within_years_value == 1 else f"Within {property_available_within_years_value} years",
                "Timing",
            )
        )
    if str(property_preferences.get("location_query") or "").strip():
        property_market_summary_items.append(
            row_item("Location query", str(property_preferences.get("location_query") or "").strip(), "Target")
        )
    if str(property_preferences.get("keywords") or "").strip():
        property_market_summary_items.append(
            row_item("Research focus", str(property_preferences.get("keywords") or "").strip(), "Focus")
        )
    if custom_keywords:
        property_market_summary_items.append(row_item("Custom priorities", custom_keywords, "Custom"))
    if bool(property_preferences.get("enable_family_mode")):
        property_market_summary_items.append(row_item("Family mode", "Enabled", "Mode"))
    if str(property_preferences.get("commute_destination") or "").strip():
        property_market_summary_items.append(
            row_item("Commute destination", str(property_preferences.get("commute_destination") or "").strip(), "Route")
        )
    if str(property_preferences.get("additional_reachability_targets") or "").strip():
        property_market_summary_items.append(
            row_item("Additional destinations", str(property_preferences.get("additional_reachability_targets") or "").strip(), "Route")
        )
    if str(property_preferences.get("university_name") or "").strip():
        property_market_summary_items.append(
            row_item("University focus", str(property_preferences.get("university_name") or "").strip(), "Research")
        )
    school_stage_preferences = [
        str(item or "").strip().replace("_", " ")
        for item in list(property_preferences.get("school_stage_preferences") or [])
        if str(item or "").strip()
    ]
    if school_stage_preferences:
        property_market_summary_items.append(
            row_item("Children", ", ".join(school_stage_preferences), "Family")
        )
    if bool(property_preferences.get("ganztag_required")):
        property_market_summary_items.append(row_item("All-day school", "Required", "Family"))
    if bool(property_preferences.get("require_school_evidence")):
        property_market_summary_items.append(row_item("School evidence", "Required", "Evidence"))
    if str(property_preferences.get("school_quality_priority") or "any") not in {"", "any"}:
        property_market_summary_items.append(
            row_item("School evidence priority", str(property_preferences.get("school_quality_priority") or "any").replace("_", " ").title(), "Evidence")
        )
    desired_project_stages = [
        str(item or "").strip().replace("_", " ")
        for item in list(property_preferences.get("desired_project_stages") or [])
        if str(item or "").strip()
    ]
    if desired_project_stages:
        property_market_summary_items.append(row_item("Accepted project stages", ", ".join(desired_project_stages), "Pipeline"))
    if bool(property_preferences.get("prefer_good_air_quality")):
        property_market_summary_items.append(row_item("Air quality", "Prefer stronger station-backed air quality", "Risk"))
    if bool(property_preferences.get("avoid_noise_risk_area")):
        property_market_summary_items.append(row_item("Noise posture", "Avoid noise-risk areas", "Risk"))
    if bool(property_preferences.get("require_high_speed_internet")):
        property_market_summary_items.append(row_item("Home office", "High-speed internet required", "Infrastructure"))
    if bool(property_preferences.get("require_energy_certificate")):
        property_market_summary_items.append(row_item("Energy certificate", "Required", "Documents"))
    if bool(property_preferences.get("require_operating_cost_statement")):
        property_market_summary_items.append(row_item("Operating costs", "Statement required", "Documents"))
    if bool(property_preferences.get("wiener_wohnticket_available")):
        property_market_summary_items.append(row_item("Wiener Wohn-Ticket", "Available", "Eligibility"))
    if bool(property_preferences.get("subsidized_required")):
        property_market_summary_items.append(row_item("Subsidized supply", "Required", "Eligibility"))
    if bool(property_preferences.get("miete_mit_kaufoption")):
        property_market_summary_items.append(row_item("Miete mit Kaufoption", "Accepted", "Eligibility"))
    if int(property_preferences.get("eigenmittel_max_eur") or 0) > 0:
        property_market_summary_items.append(
            row_item("Eigenmittel ceiling", f"EUR {int(property_preferences.get('eigenmittel_max_eur') or 0):,}".replace(",", ","), "Eligibility")
        )
    if int(property_preferences.get("application_window_days") or 0) > 0:
        property_market_summary_items.append(
            row_item("Application window", f"Within {int(property_preferences.get('application_window_days') or 0)} days", "Eligibility")
        )
    if bool(property_preferences.get("enable_auction_legal_review")):
        property_market_summary_items.append(row_item("Auction legal review", "Required when auction evidence appears", "Legal"))
    property_platform_rows = [
        row_item(
            str(option.get("label") or option.get("value") or "Provider"),
            "Included in the dedicated crawl lane." if str(option.get("value") or "").strip() in selected_platforms else "Available to add to the crawl lane.",
            "Selected" if str(option.get("value") or "").strip() in selected_platforms else "Available",
        )
        for option in platform_options
    ]
    property_recent_matches = [
        dict(item)
        for item in list(property_state.get("recent_matches") or [])
        if isinstance(item, dict)
    ]
    property_event_rows = [
        row_item(
            str(event.get("step") or "Update").replace("_", " ").capitalize(),
            str(event.get("message") or "No message").strip(),
            str(event.get("status") or "queued").replace("_", " "),
        )
        for event in list(property_run.get("events") or [])[-6:]
        if isinstance(event, dict)
    ]
    active_run_id = str(property_run.get("run_id") or "").strip()

    def _packet_url_for_candidate(candidate: dict[str, object], *, source_label: str) -> str:
        candidate_for_ref = dict(candidate)
        candidate_for_ref.setdefault("source_label", source_label)
        packet_ref = _property_candidate_ref(candidate_for_ref)
        packet_url = f"/app/research/{packet_ref}"
        if active_run_id:
            packet_url = f"{packet_url}?run_id={active_run_id}"
        return packet_url

    enriched_sources: list[dict[str, object]] = []
    def _candidate_priority_reason(match_reasons: list[str], mismatch_reasons: list[str], fit_summary: str) -> str:
        def _is_tour_only(text: str) -> bool:
            lowered = str(text or "").strip().lower()
            return bool(lowered) and any(marker in lowered for marker in ("360", "panorama", "virtual tour", "remote review"))

        preferred_match = next((item for item in match_reasons if item and not _is_tour_only(item)), "")
        if preferred_match:
            return f"Preferred because: {preferred_match}"
        preferred_risk = next((item for item in mismatch_reasons if item and not _is_tour_only(item)), "")
        if preferred_risk:
            return f"Watch-out first: {preferred_risk}"
        if fit_summary and not _is_tour_only(fit_summary):
            return fit_summary
        if match_reasons:
            return "Preferred because it stayed closest to the current brief on the available facts; 3D evidence helps verification but was not decisive on its own."
        return ""

    for source in list(property_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_row = dict(source)
        source_label = str(source_row.get("source_label") or source_row.get("source_url") or "Source").strip()
        enriched_candidates: list[dict[str, object]] = []
        for candidate in list(source_row.get("top_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            candidate_row = dict(candidate)
            candidate_row.setdefault("source_label", source_label)
            if isinstance(source_row.get("provider_quality"), dict):
                candidate_row.setdefault("provider_quality", dict(source_row.get("provider_quality") or {}))
            else:
                candidate_row.setdefault(
                    "provider_quality",
                    {
                        "floorplan_reliability": str(source_row.get("floorplan_reliability") or "").strip(),
                        "filter_pushdown_strength": str(source_row.get("filter_pushdown_strength") or "").strip(),
                        "last_verified": str(source_row.get("last_verified") or "").strip(),
                    },
                )
            if not str(candidate_row.get("packet_url") or "").strip():
                candidate_row["packet_url"] = _packet_url_for_candidate(candidate_row, source_label=source_label)
            enriched_candidates.append(candidate_row)
        source_row["top_candidates"] = enriched_candidates
        enriched_sources.append(source_row)
    if enriched_sources:
        property_summary["sources"] = enriched_sources
        ranked_candidates = [
            dict(row)
            for row in list(property_summary.get("ranked_candidates") or [])
            if isinstance(row, dict)
        ]
        if not ranked_candidates:
            seen_candidates: set[str] = set()
            for source_row in enriched_sources:
                source_label = str(source_row.get("source_label") or source_row.get("source_url") or "Source").strip()
                for candidate in list(source_row.get("top_candidates") or []):
                    if not isinstance(candidate, dict):
                        continue
                    candidate_row = dict(candidate)
                    candidate_key = str(candidate_row.get("source_ref") or candidate_row.get("property_url") or candidate_row.get("listing_id") or "").strip()
                    if candidate_key and candidate_key in seen_candidates:
                        continue
                    if candidate_key:
                        seen_candidates.add(candidate_key)
                    candidate_row.setdefault("source_label", source_label)
                    if isinstance(source_row.get("provider_quality"), dict):
                        candidate_row.setdefault("provider_quality", dict(source_row.get("provider_quality") or {}))
                    ranked_candidates.append(candidate_row)
        ranked_candidates.sort(key=lambda item: float(item.get("fit_score") or 0.0), reverse=True)
        for index, candidate_row in enumerate(ranked_candidates, start=1):
            candidate_row["rank"] = index
            candidate_row.setdefault("map_url", _property_candidate_maps_url(candidate_row))
            candidate_row.setdefault("preview_image_url", _property_candidate_preview_image(candidate_row))
            candidate_row.setdefault("route_evidence", _property_candidate_route_evidence(candidate_row, property_preferences))
            if not str(candidate_row.get("packet_url") or "").strip():
                candidate_row["packet_url"] = _packet_url_for_candidate(
                    candidate_row,
                    source_label=str(candidate_row.get("source_label") or "Source"),
                )
        property_summary["ranked_candidates"] = ranked_candidates[:50]
        property_run["summary"] = property_summary

    property_source_rows = [
        row_item(
            str(source.get("source_label") or source.get("source_url") or "Source").strip(),
            " | ".join(
                part
                for part in (
                    f"{int(source.get('listing_total') or 0)} listings",
                    f"{int(source.get('high_fit_total') or 0)} high-fit",
                    f"{int(source.get('filtered_floorplan_total') or 0)} pending layout proof"
                    if int(source.get('filtered_floorplan_total') or 0)
                    else "",
                    f"{int(source.get('tour_created_total') or 0)} hosted tours",
                    f"{int(source.get('notified_total') or 0)} client alerts",
                    f"{int(source.get('email_notified_total') or 0)} email" if int(source.get('email_notified_total') or 0) else "",
                    f"top score {float(source.get('top_fit_score') or 0.0):.2f}" if source.get("top_fit_score") is not None else "",
                )
                if part
            ),
            "Scanned",
        )
        for source in list(property_summary.get("sources") or [])
        if isinstance(source, dict)
    ]
    property_shortlist_rows: list[dict[str, str]] = []
    property_shortlist_cards: list[dict[str, object]] = []

    def _candidate_lifestyle_highlights(candidate: dict[str, object]) -> list[dict[str, str]]:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        specs = (
            ("SB", "Starbucks", facts.get("nearest_starbucks_m")),
            ("GYM", "Fitness", facts.get("nearest_fitness_center_m")),
            ("FILM", "Cinema", facts.get("nearest_cinema_m")),
            ("BLD", "Bouldering", facts.get("nearest_bouldering_m")),
            ("DOG", "Dog park", facts.get("nearest_dog_park_m")),
            ("CAFE", "Cafe", facts.get("nearest_good_cafe_m")),
        )
        rows: list[dict[str, str]] = []
        for icon, label, raw_value in specs:
            if raw_value in (None, "", []):
                continue
            try:
                meters = int(float(raw_value))
            except Exception:
                continue
            rows.append({"icon": icon, "label": label, "distance": f"{meters} m"})
        return rows[:4]

    def _candidate_research_highlights(candidate: dict[str, object]) -> list[dict[str, str]]:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        future = dict(facts.get("future_change_research") or {}) if isinstance(facts.get("future_change_research"), dict) else {}
        rows: list[dict[str, str]] = []
        school_quality = str(future.get("school_atlas_quality_summary") or "").strip()
        school_progression = str(future.get("school_atlas_progression_summary") or "").strip()
        school_evidence = str(future.get("school_atlas_evidence_type") or "").strip().replace("_", " ")
        if school_quality:
            rows.append(
                {
                    "icon": "SCH",
                    "label": "SchoolAtlas",
                    "detail": school_quality,
                    "tag": school_evidence.title() if school_evidence else "Research",
                }
            )
        if school_progression:
            rows.append(
                {
                    "icon": "AHS",
                    "label": "Gymnasium path",
                    "detail": school_progression,
                    "tag": school_evidence.title() if school_evidence else "Research",
                }
            )
        return rows[:3]

    for source in list(property_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for candidate in list(source.get("top_candidates") or [])[:5]:
            if not isinstance(candidate, dict):
                continue
            title = str(candidate.get("title") or candidate.get("property_url") or "Property candidate").strip() or "Property candidate"
            detail_parts = [
                _clean_property_candidate_copy(candidate.get("fit_summary") or ""),
                source_label,
            ]
            match_reasons = [
                _clean_property_candidate_copy(item)
                for item in list(candidate.get("match_reasons") or [])
                if _clean_property_candidate_copy(item)
            ]
            mismatch_reasons = [
                _clean_property_candidate_copy(item)
                for item in list(candidate.get("mismatch_reasons") or [])
                if _clean_property_candidate_copy(item)
            ]
            priority_reason = _candidate_priority_reason(match_reasons, mismatch_reasons, _clean_property_candidate_copy(candidate.get("fit_summary") or ""))
            compare_reason = str(candidate.get("compare_reason") or "").strip()
            if compare_reason:
                detail_parts.append(compare_reason)
            if priority_reason:
                detail_parts.append(priority_reason)
            row: dict[str, str] = {
                "title": title,
                "detail": " | ".join(part for part in detail_parts if part) or source_label,
                "tag": str(candidate.get("recommendation") or "candidate").replace("_", " ").title(),
            }
            provider_quality = dict(candidate.get("provider_quality") or {}) if isinstance(candidate.get("provider_quality"), dict) else {}
            review_url = str(candidate.get("review_url") or "").strip()
            tour_url = str(candidate.get("tour_url") or "").strip()
            property_url = str(candidate.get("property_url") or "").strip()
            packet_ref = _property_candidate_ref(
                {
                    "title": title,
                    "property_url": property_url,
                    "review_url": review_url,
                    "tour_url": tour_url,
                    "source_label": source_label,
                }
            )
            packet_url = f"/app/research/{packet_ref}"
            if active_run_id:
                packet_url = f"{packet_url}?run_id={active_run_id}"
            if review_url:
                row["action_href"] = packet_url
                row["action_method"] = "get"
                row["action_label"] = "Review packet"
                row["secondary_action_href"] = review_url
                row["secondary_action_method"] = "get"
                row["secondary_action_label"] = "Review details"
            else:
                row["action_href"] = packet_url
                row["action_method"] = "get"
                row["action_label"] = "Review packet"
            if tour_url:
                if row.get("secondary_action_href"):
                    row["tertiary_action_href"] = tour_url
                    row["tertiary_action_method"] = "get"
                    row["tertiary_action_label"] = "Open 360"
                elif row.get("action_href"):
                    row["secondary_action_href"] = tour_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Open 360"
                else:
                    row["action_href"] = tour_url
                    row["action_method"] = "get"
                    row["action_label"] = "Open 360"
            if property_url:
                if row.get("tertiary_action_href"):
                    row["quaternary_action_href"] = property_url
                    row["quaternary_action_method"] = "get"
                    row["quaternary_action_label"] = "Source"
                elif row.get("secondary_action_href"):
                    row["tertiary_action_href"] = property_url
                    row["tertiary_action_method"] = "get"
                    row["tertiary_action_label"] = "Source"
                elif row.get("action_href"):
                    row["secondary_action_href"] = property_url
                    row["secondary_action_method"] = "get"
                    row["secondary_action_label"] = "Source"
                else:
                    row["action_href"] = property_url
                    row["action_method"] = "get"
                    row["action_label"] = "Source"
            property_shortlist_rows.append(row)
            property_shortlist_cards.append(
                {
                    "title": title,
                    "source_label": source_label,
                    "detail": row["detail"],
                    "tag": row["tag"],
                    "fit_summary": str(candidate.get("fit_summary") or "").strip(),
                    "recommendation": str(candidate.get("recommendation") or "").strip(),
                    "property_url": property_url,
                    "packet_url": packet_url,
                    "review_url": review_url,
                    "tour_url": tour_url,
                    "tour_status": str(candidate.get("tour_status") or "").strip(),
                    "tour_eta_minutes": candidate.get("tour_eta_minutes") or "",
                    "blocked_reason": str(candidate.get("blocked_reason") or "").strip(),
                    "match_reasons": match_reasons,
                    "mismatch_reasons": mismatch_reasons,
                    "lifestyle_highlights": _candidate_lifestyle_highlights(candidate),
                    "research_highlights": _candidate_research_highlights(candidate),
                    "provider_quality": provider_quality,
                    "property_facts": dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {},
                    "assessment": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                    "feedback_summary": dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {},
                    "feedback_rows": [
                        dict(row)
                        for row in list(candidate.get("feedback_rows") or [])
                        if isinstance(row, dict)
                    ],
                }
            )
    property_shortlist_rows.sort(
        key=lambda item: (
            "shortlist" not in str(item.get("tag") or "").lower(),
            "view if compelling" not in str(item.get("tag") or "").lower(),
            str(item.get("title") or ""),
        )
    )
    property_shortlist_rows = property_shortlist_rows[:8]
    property_shortlist_cards = property_shortlist_cards[:6]
    property_learning_summary = dict(property_state.get("learning_summary") or {})
    property_learning_rows = [
        row_item(entry, "Learned positive preference from explicit filters or listing feedback.", "Learnt")
        for entry in list(property_learning_summary.get("likes") or [])[:4]
        if str(entry or "").strip()
    ]
    property_learning_rows.extend(
        row_item(entry, "Negative preference that should suppress future shortlist candidates.", "Avoid")
        for entry in list(property_learning_summary.get("dislikes") or [])[:4]
        if str(entry or "").strip()
    )
    property_learning_rows.extend(
        row_item(entry, "Hard rule that should fail or demote mismatching listings.", "Rule")
        for entry in list(property_learning_summary.get("hard_rules") or [])[:3]
        if str(entry or "").strip()
    )
    property_recent_feedback_rows = [
        row_item(
            str(entry.get("reaction") or "feedback").strip().title(),
            " | ".join(
                part
                for part in (
                    ", ".join(str(item or "").strip() for item in list(entry.get("reasons") or [])[:3] if str(item or "").strip()),
                    str(entry.get("note") or "").strip(),
                    str(entry.get("recorded_at") or "").strip()[:10],
                )
                if part
            )
            or "Structured feedback recorded.",
            "Feedback",
        )
        for entry in list(property_learning_summary.get("recent_feedback") or [])[:4]
        if isinstance(entry, dict)
    ]
    try:
        property_plan_max_results = max(1, int(property_state.get("commercial", {}).get("max_results_per_source") or 2))
    except Exception:
        property_plan_max_results = 2
    try:
        property_plan_max_match_score = max(1, min(100, int(property_state.get("commercial", {}).get("max_match_score") or 45)))
    except Exception:
        property_plan_max_match_score = 45
    property_visible_max_match_score = 80
    property_visible_max_results_per_source = 10
    property_plan_catalog = [
        dict(plan)
        for plan in list(property_state.get("commercial", {}).get("plan_catalog") or [])
        if isinstance(plan, dict)
    ]
    property_current_plan_key = str(property_state.get("commercial", {}).get("current_plan_key") or "free").strip().lower() or "free"

    def _property_upgrade_hint(metric_key: str, current_cap: int, visible_cap: int) -> str:
        if current_cap >= visible_cap:
            return ""
        upgrade_parts: list[str] = []
        for plan in property_plan_catalog:
            plan_key = str(plan.get("plan_key") or "").strip().lower()
            if not plan_key or plan_key == property_current_plan_key:
                continue
            try:
                plan_cap = int(plan.get(metric_key) or 0)
            except Exception:
                continue
            if plan_cap <= current_cap:
                continue
            upgrade_parts.append(f"{str(plan.get('display_name') or plan_key.title())} unlocks {plan_cap}")
        if upgrade_parts:
            return f"Current plan cap {current_cap}; " + ". ".join(upgrade_parts) + "."
        return f"Current plan cap {current_cap}; visible ceiling {visible_cap}."

    def _positive_int(value: object, *, default: int = 0) -> int:
        try:
            parsed = int(float(str(value or "").strip()))
        except Exception:
            return default
        return max(0, parsed)

    def _eur_short(value: int) -> str:
        if value >= 1_000_000:
            return f"EUR {value // 1_000_000}M"
        if value >= 1_000:
            return f"EUR {value // 1_000}k"
        return f"EUR {value}"

    property_price_value = _positive_int(property_preferences.get("max_price_eur"))
    property_price_range_presets = {
        "rent": {"max": 6000, "step": 100, "scaleMaxLabel": "EUR 6k"},
        "buy": {"max": 2_000_000, "step": 25_000, "scaleMaxLabel": "EUR 2M"},
        "any": {"max": 2_000_000, "step": 25_000, "scaleMaxLabel": "EUR 2M"},
    }
    property_price_preset = property_price_range_presets.get(selected_listing_mode) or property_price_range_presets["rent"]
    property_price_slider_max = max(int(property_price_preset["max"]), property_price_value)
    property_price_slider_step = int(property_price_preset["step"])
    property_min_rooms_value = min(8, _positive_int(property_preferences.get("min_rooms")))
    property_min_area_value = min(250, _positive_int(property_preferences.get("min_area_m2")))
    property_available_within_years_value = min(10, _positive_int(property_preferences.get("available_within_years")))
    market_filter_capabilities = _property_market_filter_capabilities(
        str(property_preferences.get("country_code") or "AT"),
        selected_region_code,
    )
    try:
        property_results_value = int(property_preferences.get("max_results_per_source") or property_plan_max_results)
    except Exception:
        property_results_value = property_plan_max_results
    property_results_value = max(1, min(property_results_value, property_plan_max_results))
    property_search_agent_enabled = bool(property_preferences.get("search_agent_enabled"))
    property_search_agent_duration_days = _positive_int(property_preferences.get("search_agent_duration_days"), default=30)
    property_search_agent_duration_days = max(7, min(365, property_search_agent_duration_days or 30))
    property_search_agent_notification_limit = _positive_int(property_preferences.get("search_agent_notification_limit"), default=5)
    property_search_agent_notification_limit = max(1, min(50, property_search_agent_notification_limit or 5))
    property_search_agent_notification_period = str(property_preferences.get("search_agent_notification_period") or "day").strip().lower()
    if property_search_agent_notification_period not in {"day", "week"}:
        property_search_agent_notification_period = "day"
    property_search_mode_requested = str(property_preferences.get("search_mode") or "strict").strip().lower()
    if property_search_mode_requested not in {"strict", "discovery"}:
        property_search_mode_requested = "strict"
    def _format_property_search_agent(raw_agent: dict[str, object]) -> dict[str, object]:
        def _safe_agent_load_payload(value: dict[str, object]) -> dict[str, object]:
            return {
                key: item
                for key, item in dict(value or {}).items()
                if key not in {"search_agents", "active_search_agent_id", "raw_preferences", "property_commercial"}
            }

        agent_duration_days = _positive_int(raw_agent.get("duration_days"), default=property_search_agent_duration_days)
        agent_duration_days = max(7, min(365, agent_duration_days or property_search_agent_duration_days))
        agent_notification_limit = _positive_int(raw_agent.get("notification_limit"), default=property_search_agent_notification_limit)
        agent_notification_limit = max(1, min(50, agent_notification_limit or property_search_agent_notification_limit))
        agent_notification_period = str(raw_agent.get("notification_period") or property_search_agent_notification_period).strip().lower()
        if agent_notification_period not in {"day", "week"}:
            agent_notification_period = property_search_agent_notification_period
        agent_selected_platforms = raw_agent.get("selected_platforms") if isinstance(raw_agent.get("selected_platforms"), list) else selected_platforms
        agent_enabled = bool(raw_agent.get("enabled"))
        agent_listing_mode = str(raw_agent.get("listing_mode") or selected_listing_mode).strip().lower() or selected_listing_mode
        agent_country_code = str(raw_agent.get("country_code") or property_preferences.get("country_code") or "AT").strip().upper()
        agent_location_query = str(raw_agent.get("location_query") or property_preferences.get("location_query") or "").strip()
        agent_property_types = _normalize_property_type_values(raw_agent.get("property_type") or property_preferences.get("property_type"))
        agent_name = str(raw_agent.get("name") or "").strip()
        if not agent_name:
            agent_name = f"{agent_listing_mode.title()} search · {agent_location_query or agent_country_code}"
        last_run_at = str(raw_agent.get("last_run_at") or "").strip()
        next_run_at = str(raw_agent.get("next_run_at") or "").strip()
        try:
            sent_in_current_window = max(int(float(raw_agent.get("sent_in_current_window") or 0)), 0)
        except Exception:
            sent_in_current_window = 0
        remaining_notifications = max(agent_notification_limit - sent_in_current_window, 0)
        area_label = agent_location_query or agent_country_code or "No area saved"
        notification_label = f"{agent_notification_limit} per {('week' if agent_notification_period == 'week' else 'day')}"
        return {
            "agent_id": str(raw_agent.get("agent_id") or "current").strip() or "current",
            "name": agent_name,
            "enabled": agent_enabled,
            "is_active": bool(raw_agent.get("is_active")),
            "status_label": "Active" if agent_enabled else "Paused",
            "duration_days": agent_duration_days,
            "duration_label": (
                "1 week"
                if agent_duration_days == 7
                else "1 year"
                if agent_duration_days == 365
                else f"{agent_duration_days} days"
            ),
            "notification_limit": agent_notification_limit,
            "notification_period": agent_notification_period,
            "notification_period_label": "week" if agent_notification_period == "week" else "day",
            "location_query": agent_location_query,
            "listing_mode": agent_listing_mode,
            "country_code": agent_country_code,
            "region_code": str(raw_agent.get("region_code") or property_preferences.get("region_code") or "").strip().lower(),
            "property_type": ", ".join(agent_property_types),
            "provider_count": len(agent_selected_platforms),
            "last_run_label": last_run_at or "not run yet",
            "next_run_label": next_run_at or ("waiting for scheduler" if agent_enabled else "paused"),
            "sent_in_current_window": sent_in_current_window,
            "remaining_notifications": remaining_notifications,
            "area_label": area_label,
            "scope_label": f"{agent_listing_mode.title()} · {area_label} · {agent_country_code}",
            "notification_label": notification_label,
            "run_label": f"Last: {last_run_at or 'not run yet'} · Next: {next_run_at or ('waiting for scheduler' if agent_enabled else 'paused')}",
            "delivery_label": f"Sent {sent_in_current_window}/{agent_notification_limit} this {('week' if agent_notification_period == 'week' else 'day')}",
            "load_payload": (
                _safe_agent_load_payload(dict(raw_agent.get("preferences_json") or {}))
                if isinstance(raw_agent.get("preferences_json"), dict)
                else {
                    "country_code": agent_country_code,
                    "region_code": str(raw_agent.get("region_code") or property_preferences.get("region_code") or "").strip().lower(),
                    "location_query": agent_location_query,
                    "listing_mode": agent_listing_mode,
                    "property_type": agent_property_types,
                    "search_mode": str(raw_agent.get("search_mode") or property_search_mode_requested or "strict").strip().lower() or "strict",
                    "selected_platforms": list(agent_selected_platforms or []),
                    "search_agent_enabled": agent_enabled,
                    "search_agent_duration_days": agent_duration_days,
                    "search_agent_notification_limit": agent_notification_limit,
                    "search_agent_notification_period": agent_notification_period,
                }
            ),
        }

    raw_property_search_agents = property_preferences.get("search_agents") if isinstance(property_preferences.get("search_agents"), list) else []
    selected_property_type_values = _normalize_property_type_values(property_preferences.get("property_type"))
    property_search_agents = [
        _format_property_search_agent(agent)
        for agent in raw_property_search_agents
        if isinstance(agent, dict)
    ]
    if not property_search_agents:
        property_search_agents = [
            _format_property_search_agent(
                {
                    "agent_id": str(property_preferences.get("active_search_agent_id") or "current").strip() or "current",
                    "enabled": property_search_agent_enabled,
                    "duration_days": property_search_agent_duration_days,
                    "notification_limit": property_search_agent_notification_limit,
                    "notification_period": property_search_agent_notification_period,
                    "location_query": str(property_preferences.get("location_query") or "").strip(),
                    "listing_mode": selected_listing_mode,
                    "country_code": str(property_preferences.get("country_code") or "AT").strip().upper(),
                    "selected_platforms": selected_platforms,
                    "is_active": True,
                }
            )
        ]
    property_search_agent = next((agent for agent in property_search_agents if agent.get("is_active")), property_search_agents[0])
    property_search_mode = property_search_mode_requested
    property_run_for_defaults = dict(property_state.get("run") or {})
    property_run_summary_for_defaults = dict(property_run_for_defaults.get("summary") or {})
    property_run_status_for_defaults = str(property_run_for_defaults.get("status") or "").strip().lower()
    property_ranked_total_for_defaults = _positive_int(
        property_run_summary_for_defaults.get("ranked_total"),
        default=len(
            [
                row
                for row in list(property_run_summary_for_defaults.get("ranked_candidates") or [])
                if isinstance(row, dict)
            ]
        ),
    )
    if property_search_mode == "strict" and property_run_status_for_defaults in {"processed", "completed"} and property_ranked_total_for_defaults < 6:
        property_search_mode = "discovery"
    try:
        property_min_match_score_value = int(property_preferences.get("min_match_score") or min(65, property_plan_max_match_score))
    except Exception:
        property_min_match_score_value = min(65, property_plan_max_match_score)
    property_min_match_score_value = max(1, min(property_min_match_score_value, property_plan_max_match_score))
    property_min_match_tooltip = (
        "Minimum personal fit score a listing must beat before it can enter the shortlist. "
        "Raising it usually improves precision, but can make searches much slower and increases backend crawl and scoring load."
    )
    property_min_match_upgrade_hint = _property_upgrade_hint(
        "max_match_score",
        property_plan_max_match_score,
        property_visible_max_match_score,
    )
    profile_manage_href = f"/app/profile?run_id={active_run_id}" if active_run_id else "/app/profile"
    selected_preference_person_id = str(property_preferences.get("preference_person_id") or "self").strip() or "self"
    preference_profile_options = [{"value": "self", "label": "Default"}]
    if selected_preference_person_id != "self":
        preference_profile_options.append(
            {
                "value": selected_preference_person_id,
                "label": selected_preference_person_id,
            }
        )
    property_form = {
        "variant": "property_search",
        "title": "Run a premium market sweep",
        "eyebrow": "Flagship property desk",
        "copy": "Set the market, shape the shortlist, choose the sources, then launch one visible research run with ranking, review pages, and client-ready alerts.",
        "submit_label": "Launch search",
        "fields": [
            {
                "type": "select",
                "name": "country_code",
                "label": "Country",
                "value": str(property_preferences.get("country_code") or "AT"),
                "options": country_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "listing_mode",
                "label": "Search mode",
                "value": selected_listing_mode,
                "options": listing_mode_options,
                "step": "search",
            },
            {
                "type": "checkbox_group",
                "name": "property_type",
                "label": "Property type",
                "values": selected_property_type_values,
                "options": property_type_options,
                "step": "search",
            },
            {
                "type": "select",
                "name": "investment_research_mode",
                "label": "Investment research",
                "value": str(property_preferences.get("investment_research_mode") or "off"),
                "options": investment_research_mode_options,
                "hidden": selected_listing_mode != "buy",
                "step": "search",
            },
            {
                "type": "select",
                "name": "region_code",
                "label": "State or metro area",
                "value": selected_region_code,
                "options": region_options,
                "step": "search",
            },
            {
                "type": "checkbox",
                "name": "all_of_vienna",
                "label": "All of Vienna",
                "value": "true",
                "checked": selected_all_of_vienna,
                "step": "areas",
            },
            {
                "type": "checkbox_group",
                "name": "location_query",
                "label": "Target areas",
                "options": location_options,
                "values": selected_location_values,
                "hidden": selected_all_of_vienna
                and str(property_preferences.get("country_code") or "AT").strip().upper() == "AT"
                and selected_region_code == "vienna",
                "step": "areas",
            },
            {
                "type": "text",
                "name": "custom_location_query",
                "label": "Custom areas",
                "value": custom_location_query,
                "placeholder": "Free text for areas not covered by the checklist",
                "tooltip": "Use this only when the district or area is not already available as a visible checkbox.",
                "step": "areas",
            },
            {
                "type": "checkbox_group",
                "name": "selected_platforms",
                "label": "Search sources",
                "options": platform_options,
                "option_groups": _group_property_provider_options(platform_options),
                "values": list(selected_platforms),
                "step": "providers",
            },
            {
                "type": "select",
                "name": "search_mode",
                "label": "Result mode",
                "value": property_search_mode,
                "options": [
                    {"value": "strict", "label": "Strict shortlist"},
                    {"value": "discovery", "label": "Discovery pass"},
                ],
                "tooltip": (
                    "Strict shortlist keeps your hard preference gates. Discovery pass keeps the same area and provider scope, "
                    "but turns school, family, and entertainment distance misses into ranking penalties instead of filtering them out."
                ),
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "use_flatbee_reputation_penalty",
                "label": "Apply Flatbee reputation penalty",
                "value": "true",
                "checked": bool(property_preferences.get("use_flatbee_reputation_penalty", True)),
                "tooltip": "Flatbee stays available in all-provider sweeps, but this modifier heavily discounts its results because the source has a weak trust reputation and frequent duplicate-quality issues.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "include_broker_direct_sources",
                "label": "Makler-direkt Quellen",
                "value": "true",
                "checked": bool(property_preferences.get("include_broker_direct_sources")),
                "tooltip": "Track Makler-direkt lanes such as Kalandra and other broker-owned pages as a distinct source family, separate from marketplaces and cooperatives.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "include_community_signals",
                "label": "Facebook / Telegram Hinweise",
                "value": "true",
                "checked": bool(property_preferences.get("include_community_signals")),
                "tooltip": "Include Facebook groups, Telegram hints, Flatbee-style community leads, and other off-market signals, but keep them separately verifiable.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "require_manual_validation_for_community",
                "label": "Manual validation for Facebook / Telegram leads",
                "value": "true",
                "checked": bool(property_preferences.get("require_manual_validation_for_community")),
                "tooltip": "Community-sourced hits should be treated as unverified until a human confirms identity, freshness, and legitimacy.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "include_developer_project_signals",
                "label": "Developer project signals",
                "value": "true",
                "checked": bool(property_preferences.get("include_developer_project_signals")),
                "tooltip": "Track early-stage project and launch signals from Bauträger and premarket project sites.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "include_public_housing_signals",
                "label": "Public housing signals",
                "value": "true",
                "checked": bool(property_preferences.get("include_public_housing_signals")),
                "tooltip": "Track municipal, public housing, and Wohnservice-like lanes separately from commercial marketplaces.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "wiener_wohnticket_available",
                "label": "Wiener Wohn-Ticket available",
                "value": "true",
                "checked": bool(property_preferences.get("wiener_wohnticket_available")),
                "tooltip": "Only treat Vienna municipal and subsidized opportunities as fully usable when a Wiener Wohn-Ticket is already available.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "subsidized_required",
                "label": "Subsidized or cooperative supply only",
                "value": "true",
                "checked": bool(property_preferences.get("subsidized_required")),
                "tooltip": "Bias the search toward geforderte, cooperative, and municipal supply instead of private-market inventory.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "miete_mit_kaufoption",
                "label": "Prefer Miete mit Kaufoption",
                "value": "true",
                "checked": bool(property_preferences.get("miete_mit_kaufoption")),
                "tooltip": "Keep lease-to-own style cooperative offers visible as their own eligibility-sensitive lane.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "range",
                "name": "eigenmittel_max_eur",
                "label": "Max Eigenmittel",
                "value": str(property_preferences.get("eigenmittel_max_eur") or 0),
                "min": "0",
                "max": "150000",
                "visual_max": "150000",
                "range_step": "1000",
                "format": "currency_eur",
                "empty_label": "Any Eigenmittel",
                "scale_min_label": "Any",
                "scale_max_label": "EUR 150k",
                "tooltip": "Treat cooperative or subsidized offers above this financing contribution as a weaker fit instead of hiding them completely.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "range",
                "name": "application_window_days",
                "label": "Application window",
                "value": str(property_preferences.get("application_window_days") or 0),
                "min": "0",
                "max": "90",
                "visual_max": "90",
                "range_step": "1",
                "format": "days",
                "empty_label": "Any application window",
                "scale_min_label": "Any",
                "scale_max_label": "90 days",
                "tooltip": "Keep short registration windows visible as an urgency signal when cooperative or subsidized stock is scarce.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox",
                "name": "include_distressed_sale_signals",
                "label": "Court and auction listings",
                "value": "true",
                "checked": bool(property_preferences.get("include_distressed_sale_signals")),
                "tooltip": "Keep court-published, auction, and forced-sale listings visible as a separate source family.",
                "step": "providers",
                "advanced_panel": "provider_policies",
            },
            {
                "type": "checkbox_group",
                "name": "keywords",
                "label": "What matters",
                "options": keyword_options,
                "values": selected_keyword_values,
                "step": "areas",
            },
            {
                "type": "text",
                "name": "custom_keywords",
                "label": "Custom priorities",
                "value": custom_keywords,
                "placeholder": "Free text for priorities not listed above",
                "tooltip": "If the same custom preference is requested three times, it should be promoted into this user's default catalog. If many users request the same thing, it should become available for everyone.",
                "step": "areas",
            },
            {
                "type": "select",
                "name": "preference_person_id",
                "label": "Preference profile",
                "value": selected_preference_person_id,
                "options": preference_profile_options,
                "manage_href": profile_manage_href,
                "manage_label": "Manage feedback preferences",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "use_stored_feedback_preferences",
                "label": "Use stored feedback preferences",
                "value": "true",
                "checked": bool(property_preferences.get("use_stored_feedback_preferences", True)),
                "manage_href": profile_manage_href,
                "manage_label": "Manage",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "enable_building_risk_research",
                "label": "Building and operating-cost research",
                "value": "true",
                "checked": bool(property_preferences.get("enable_building_risk_research")),
                "tooltip": "Investigate reserve fund, renovation pressure, energy risk, special levies, and operating-cost exposure.",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "enable_market_supply_research",
                "label": "Market supply and exit research",
                "value": "true",
                "checked": bool(property_preferences.get("enable_market_supply_research")),
                "tooltip": "Investigate developer pipeline, competing supply, target-demand depth, and exit liquidity.",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "enable_location_risk_research",
                "label": "Micro-location risk research",
                "value": "true",
                "checked": bool(property_preferences.get("enable_location_risk_research")),
                "tooltip": "Investigate safety, schools, clinics, daily-life access, pollution, flood, heat, and nuisance burden.",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "enable_family_mode",
                "label": "Family mode",
                "value": "true",
                "checked": bool(property_preferences.get("enable_family_mode")),
                "tooltip": "Prioritize school evidence, childcare, playgrounds, pediatrician access, and daily family logistics as a coherent mode.",
                "step": "children",
            },
            {
                "type": "checkbox",
                "name": "ganztag_required",
                "label": "Ganztag matters",
                "value": "true",
                "checked": bool(property_preferences.get("ganztag_required")),
                "tooltip": "Treat all-day school or childcare availability as a first-class family signal instead of a nice-to-have note.",
                "step": "children",
                "advanced_panel": "children",
                "hidden": True,
            },
            {
                "type": "checkbox_group",
                "name": "school_stage_preferences",
                "label": "Children and school needs",
                "options": [
                    {"value": "kindergarten", "label": "Kindergarten"},
                    {"value": "public_kindergarten", "label": "Öffentlicher Kindergarten"},
                    {"value": "private_kindergarten", "label": "Privater Kindergarten"},
                    {"value": "volksschule", "label": "Volksschule"},
                    {"value": "ganztags_volksschule", "label": "Ganztagsvolksschule"},
                    {"value": "halbtags_volksschule", "label": "Halbtagsvolksschule"},
                    {"value": "gymnasium", "label": "Gymnasium"},
                ],
                "values": list(property_preferences.get("school_stage_preferences") or []),
                "step": "children",
                "advanced_panel": "children",
            },
            {
                "type": "select",
                "name": "school_quality_priority",
                "label": "School evidence priority",
                "value": str(property_preferences.get("school_quality_priority") or "any"),
                "options": [
                    {"value": "any", "label": "Any"},
                    {"value": "important", "label": "Important"},
                    {"value": "very_important", "label": "Very important"},
                ],
                "step": "children",
                "advanced_panel": "children",
            },
            {
                "type": "checkbox",
                "name": "require_school_evidence",
                "label": "Require school evidence",
                "value": "true",
                "checked": bool(property_preferences.get("require_school_evidence")),
                "tooltip": "Keep school fit tied to official school-evidence rows instead of inferring too much from generic map proximity.",
                "step": "children",
                "advanced_panel": "children",
            },
            {
                "type": "range",
                "name": "max_distance_to_playground_m",
                "label": "Playground nearby means",
                "value": str(property_preferences.get("max_distance_to_playground_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any playground distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Defines what nearby means for playground access. If good matches are scarce, PropertyQuarry relaxes this radius and marks the gap instead of returning nothing.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "select",
                "name": "max_distance_to_playground_importance",
                "label": "Playground importance",
                "value": str(property_preferences.get("max_distance_to_playground_importance") or "important"),
                "options": [
                    {"value": "must_have", "label": "Must have"},
                    {"value": "important", "label": "Important"},
                    {"value": "nice_to_have", "label": "Nice to have"},
                ],
                "tooltip": "Controls how strongly playground distance affects ranking and how far the adaptive fallback may relax the radius.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_library_m",
                "label": "Library nearby means",
                "value": str(property_preferences.get("max_distance_to_library_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any library distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Defines what nearby means for a public library or comparable Bücherei. Sparse searches relax this radius before returning an empty shortlist.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "select",
                "name": "max_distance_to_library_importance",
                "label": "Library importance",
                "value": str(property_preferences.get("max_distance_to_library_importance") or "nice_to_have"),
                "options": [
                    {"value": "must_have", "label": "Must have"},
                    {"value": "important", "label": "Important"},
                    {"value": "nice_to_have", "label": "Nice to have"},
                ],
                "tooltip": "Controls how strongly library distance affects ranking and adaptive radius relaxation.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_zoo_m",
                "label": "Max distance to zoo",
                "value": str(property_preferences.get("max_distance_to_zoo_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any zoo distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Optional family and weekend-life signal. Only keep listings within this distance of a zoo or Tiergarten.",
                "step": "children",
                "advanced_panel": "children_distances",
                "availability_key": "family_zoo",
                "disabled_reason": "No practical zoo or Tiergarten signal is configured for this market yet.",
            },
            {
                "type": "checkbox",
                "name": "enable_commute_research",
                "label": "Commute reality research",
                "value": "true",
                "checked": bool(property_preferences.get("enable_commute_research")),
                "tooltip": "Check actual travel times at realistic times of day instead of relying only on straight-line distance.",
                "step": "reachability",
            },
            {
                "type": "text",
                "name": "commute_destination",
                "label": "Primary destination",
                "value": str(property_preferences.get("commute_destination") or ""),
                "placeholder": "Workplace, university, Oma, or another key address",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "text",
                "name": "additional_reachability_targets",
                "label": "Additional destinations",
                "value": str(property_preferences.get("additional_reachability_targets") or ""),
                "placeholder": "Comma-separated: office, grandma, club, doctor",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "checkbox_group",
                "name": "preferred_reachability_modes",
                "label": "Reachability modes",
                "options": [
                    {"value": "public_transit", "label": "Public transit"},
                    {"value": "bike", "label": "Bike"},
                    {"value": "car", "label": "Car"},
                    {"value": "walk", "label": "Walk"},
                ],
                "values": list(property_preferences.get("preferred_reachability_modes") or []),
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "range",
                "name": "max_commute_minutes_transit",
                "label": "Max commute by transit",
                "value": str(property_preferences.get("max_commute_minutes_transit") or 0),
                "min": "0",
                "max": "180",
                "visual_max": "180",
                "range_step": "5",
                "format": "minutes",
                "empty_label": "Any transit commute",
                "scale_min_label": "Any",
                "scale_max_label": "180 min",
                "tooltip": "Maximum acceptable public-transit commute time.",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "range",
                "name": "max_commute_minutes_drive",
                "label": "Max commute by car",
                "value": str(property_preferences.get("max_commute_minutes_drive") or 0),
                "min": "0",
                "max": "180",
                "visual_max": "180",
                "range_step": "5",
                "format": "minutes",
                "empty_label": "Any driving commute",
                "scale_min_label": "Any",
                "scale_max_label": "180 min",
                "tooltip": "Maximum acceptable driving commute time.",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "range",
                "name": "max_commute_minutes_bike",
                "label": "Max commute by bike",
                "value": str(property_preferences.get("max_commute_minutes_bike") or 0),
                "min": "0",
                "max": "180",
                "visual_max": "180",
                "range_step": "5",
                "format": "minutes",
                "empty_label": "Any cycling commute",
                "scale_min_label": "Any",
                "scale_max_label": "180 min",
                "tooltip": "Maximum acceptable cycling commute time.",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "range",
                "name": "max_commute_minutes_walk",
                "label": "Max commute by foot",
                "value": str(property_preferences.get("max_commute_minutes_walk") or 0),
                "min": "0",
                "max": "180",
                "visual_max": "180",
                "range_step": "5",
                "format": "minutes",
                "empty_label": "Any walking commute",
                "scale_min_label": "Any",
                "scale_max_label": "180 min",
                "tooltip": "Maximum acceptable walking time for adult destinations.",
                "step": "reachability",
                "advanced_panel": "commute",
            },
            {
                "type": "checkbox_group",
                "name": "desired_project_stages",
                "label": "Accepted project stages",
                "options": [
                    {"value": "existing", "label": "Existing"},
                    {"value": "under_construction", "label": "Under construction"},
                    {"value": "planned", "label": "Planned"},
                    {"value": "waitlist", "label": "Waitlist"},
                    {"value": "pre_registration", "label": "Pre-registration"},
                ],
                "values": list(property_preferences.get("desired_project_stages") or []),
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "apply_unknowns_penalty",
                "label": "Penalize unknowns in ranking",
                "value": "true",
                "checked": bool(property_preferences.get("apply_unknowns_penalty")),
                "tooltip": "Keep strong unknown-heavy listings visible if they fit, but rank better-known candidates above them.",
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "enable_action_readiness_research",
                "label": "Next steps",
                "value": "true",
                "checked": bool(property_preferences.get("enable_action_readiness_research")),
                "tooltip": "Show the next questions, documents, and follow-ups for serious matches.",
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "require_energy_certificate",
                "label": "Require energy certificate evidence",
                "value": "true",
                "checked": bool(property_preferences.get("require_energy_certificate")),
                "tooltip": "Treat missing Energieausweis evidence as a material gap, especially in Austrian buy and cooperative due diligence.",
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "require_operating_cost_statement",
                "label": "Require operating-cost evidence",
                "value": "true",
                "checked": bool(property_preferences.get("require_operating_cost_statement")),
                "tooltip": "Keep Betriebskosten and recurring-cost proof visible before a property is treated as ready for pursuit.",
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "enable_auction_legal_review",
                "label": "Court and auction review",
                "value": "true",
                "checked": bool(property_preferences.get("enable_auction_legal_review")),
                "tooltip": "Keep court-sale and auction listings separate from normal homes and flag them for extra legal review.",
                "step": "research",
            },
            {
                "type": "checkbox",
                "name": "enable_lifestyle_research",
                "label": "Freizeit und Alltag",
                "value": "true",
                "checked": bool(property_preferences.get("enable_lifestyle_research")),
                "tooltip": "Track lifestyle distance signals like Starbucks and fitness centers separately from hard investment or family-risk criteria.",
                "step": "areas",
            },
            {
                "type": "text",
                "name": "university_name",
                "label": "University focus",
                "value": str(property_preferences.get("university_name") or ""),
                "placeholder": "University of Vienna, WU, TU Wien",
                "step": "areas",
            },
            {
                "type": "range",
                "name": "max_distance_to_university_m",
                "label": "Max distance to university",
                "value": str(property_preferences.get("max_distance_to_university_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any university distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Keep university proximity visible as a livability and investment signal. Use the university name above for a target campus or institution.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_starbucks_m",
                "label": "Max distance to Starbucks",
                "value": str(property_preferences.get("max_distance_to_starbucks_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any Starbucks distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest Starbucks.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_fitness_center_m",
                "label": "Max distance to fitness center",
                "value": str(property_preferences.get("max_distance_to_fitness_center_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any fitness distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest fitness center or gym.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_cinema_m",
                "label": "Max distance to cinema",
                "value": str(property_preferences.get("max_distance_to_cinema_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any cinema distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest cinema.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_bouldering_m",
                "label": "Max distance to bouldering gym",
                "value": str(property_preferences.get("max_distance_to_bouldering_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any bouldering distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest bouldering or climbing gym.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_dog_park_m",
                "label": "Max distance to dog park",
                "value": str(property_preferences.get("max_distance_to_dog_park_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any dog park distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest dog park or dog exercise area.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_good_cafe_m",
                "label": "Max distance to good cafe",
                "value": str(property_preferences.get("max_distance_to_good_cafe_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any cafe distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional fun filter. Only keep listings within this distance of the nearest cafe-quality proxy.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_supermarket_m",
                "label": "Supermarket nearby means",
                "value": str(property_preferences.get("max_distance_to_supermarket_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any supermarket distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Defines what nearby means for everyday groceries. If good matches are scarce, this radius is relaxed and reported instead of hiding every result.",
                "step": "areas",
                "advanced_panel": "shopping_distances",
            },
            {
                "type": "select",
                "name": "max_distance_to_supermarket_importance",
                "label": "Supermarket importance",
                "value": str(property_preferences.get("max_distance_to_supermarket_importance") or "important"),
                "options": [
                    {"value": "must_have", "label": "Must have"},
                    {"value": "important", "label": "Important"},
                    {"value": "nice_to_have", "label": "Nice to have"},
                ],
                "tooltip": "Controls how strongly supermarket distance affects ranking and adaptive radius relaxation.",
                "step": "areas",
                "advanced_panel": "shopping_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_market_m",
                "label": "Max distance to market",
                "value": str(property_preferences.get("max_distance_to_market_m") or 0),
                "min": "0",
                "max": "5000",
                "visual_max": "5000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any market distance",
                "scale_min_label": "Any",
                "scale_max_label": "5 km",
                "tooltip": "Optional district-life filter. Covers produce markets and flanier markets like Naschmarkt.",
                "step": "areas",
                "advanced_panel": "shopping_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_hardware_store_m",
                "label": "Max distance to Baumarkt",
                "value": str(property_preferences.get("max_distance_to_hardware_store_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any Baumarkt distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Useful for renovation and everyday practical access. Tracks DIY and hardware-store distance.",
                "step": "areas",
                "advanced_panel": "shopping_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_shopping_center_m",
                "label": "Max distance to shopping center",
                "value": str(property_preferences.get("max_distance_to_shopping_center_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any shopping-center distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Tracks larger shopping centers for errands and bad-weather convenience.",
                "step": "areas",
                "advanced_panel": "shopping_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_shopping_street_m",
                "label": "Max distance to flaniermeile",
                "value": str(property_preferences.get("max_distance_to_shopping_street_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any promenade distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Tracks pedestrian-heavy shopping streets and promenade zones for strolling and city-life fit.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_theatre_m",
                "label": "Max distance to theatre",
                "value": str(property_preferences.get("max_distance_to_theatre_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any theatre distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Optional culture filter. Only keep listings within this distance of a theatre.",
                "step": "areas",
                "advanced_panel": "lifestyle_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_public_pool_m",
                "label": "Max distance to public pool",
                "value": str(property_preferences.get("max_distance_to_public_pool_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any pool distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Useful for family leisure and everyday sport access. Tracks public swimming pools.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "range",
                "name": "max_distance_to_medical_care_m",
                "label": "Max distance to doctors and hospitals",
                "value": str(property_preferences.get("max_distance_to_medical_care_m") or 0),
                "min": "0",
                "max": "7000",
                "visual_max": "7000",
                "range_step": "50",
                "format": "meters_cap",
                "empty_label": "Any medical-care distance",
                "scale_min_label": "Any",
                "scale_max_label": "7 km",
                "tooltip": "Tracks proximity to doctors, health centers, clinics, and hospitals. Stronger signal when children or elder-care logistics matter.",
                "step": "children",
                "advanced_panel": "children_distances",
            },
            {
                "type": "checkbox",
                "name": "prefer_good_air_quality",
                "label": "Good air quality matters",
                "value": "true",
                "checked": bool(property_preferences.get("prefer_good_air_quality")),
                "tooltip": "Treat poor air quality as a risk signal in deep research and ranking.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "avoid_noise_risk_area",
                "label": "Avoid noise-risk area",
                "value": "true",
                "checked": bool(property_preferences.get("avoid_noise_risk_area")),
                "tooltip": "Use official Austrian noise maps and route exposure signals as ranking penalties or suppression reasons.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "require_high_speed_internet",
                "label": "Require high-speed internet evidence",
                "value": "true",
                "checked": bool(property_preferences.get("require_high_speed_internet")),
                "tooltip": "Promote listings backed by Austrian broadband coverage evidence when home-office viability matters.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "prefer_low_crime_area",
                "label": "Low crime area matters",
                "value": "true",
                "checked": bool(property_preferences.get("prefer_low_crime_area")),
                "tooltip": "Treat crime burden and safety pattern as a genuine risk factor in deep research.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "require_drinking_water_quality_research",
                "label": "Research water source and groundwater burden",
                "value": "true",
                "checked": bool(property_preferences.get("require_drinking_water_quality_research")),
                "tooltip": "Ask deep research to investigate Hochquellwasser versus groundwater dependency and any public burden signals.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "require_parking_pressure_check",
                "label": "Check parking situation if no garage",
                "value": "true",
                "checked": bool(property_preferences.get("require_parking_pressure_check")),
                "tooltip": "If the listing has no garage, deep research should investigate general street-parking pressure and paid-parking burden.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "avoid_cesspit_or_septic_risk",
                "label": "Avoid Senkgrube or septic risk",
                "value": "true",
                "checked": bool(property_preferences.get("avoid_cesspit_or_septic_risk")),
                "tooltip": "Treat cesspit or septic dependence, costs, and smell burden as a risk that must be clarified.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "require_winter_access_research",
                "label": "Check winter driving conditions",
                "value": "true",
                "checked": bool(property_preferences.get("require_winter_access_research")),
                "tooltip": "For more remote properties, deep research should investigate winter snow access, slope, and seasonal driving constraints.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "avoid_flood_risk_area",
                "label": "Avoid flood-risk area",
                "value": "true",
                "checked": bool(property_preferences.get("avoid_flood_risk_area")),
                "tooltip": "Treat historic flooding, runoff, and river or drainage exposure as a serious location risk in deep research.",
                "step": "areas",
                "advanced_panel": "location_research",
            },
            {
                "type": "checkbox",
                "name": "enable_trust_risk_scoring",
                "label": "Duplicate, scam, and stale scoring",
                "value": "true",
                "checked": bool(property_preferences.get("enable_trust_risk_scoring")),
                "tooltip": "Generate trust-verification work for duplicate, stale, and scam risk rather than treating all sources equally.",
                "step": "areas",
            },
            {
                "type": "range",
                "name": "max_price_eur",
                "label": "Max budget",
                "value": str(property_price_value),
                "min": "0",
                "max": str(property_price_slider_max),
                "visual_max": str(property_price_slider_max),
                "range_step": str(property_price_slider_step),
                "format": "currency_eur",
                "empty_label": "Any budget",
                "scale_min_label": "No max",
                "scale_max_label": _eur_short(property_price_slider_max),
                "tooltip": "Set a hard budget ceiling. Leave it at Any budget when you want PropertyQuarry to rank first and filter price later.",
                "range_preset": "listing_mode_price",
                "range_presets": property_price_range_presets,
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_rooms",
                "label": "Min rooms",
                "value": str(property_min_rooms_value),
                "min": "0",
                "max": "8",
                "visual_max": "8",
                "range_step": "1",
                "format": "rooms",
                "empty_label": "Any rooms",
                "scale_min_label": "Any",
                "scale_max_label": "8+ rooms",
                "tooltip": "Minimum room count. Keep this open when layout quality matters more than the advertised room number.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_area_m2",
                "label": "Min area",
                "value": str(property_min_area_value),
                "min": "0",
                "max": "250",
                "visual_max": "250",
                "range_step": "5",
                "format": "area_m2",
                "empty_label": "Any size",
                "scale_min_label": "Any",
                "scale_max_label": "250+ m2",
                "tooltip": "Minimum usable area. Larger minimums reduce weak matches but can make the crawl skip sparse auction or cooperative listings.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "available_within_years",
                "label": "Move-in deadline",
                "value": str(property_available_within_years_value),
                "min": "0",
                "max": "10",
                "visual_max": "10",
                "range_step": "1",
                "format": "availability_years",
                "empty_label": "Any delivery date",
                "scale_min_label": "Any",
                "scale_max_label": "10 years",
                "tooltip": "Filter for listings or projects that should be ready within the selected number of years. Useful for cooperative and planned development sign-ups.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "max_results_per_source",
                "label": "Max results per source",
                "value": str(property_results_value),
                "min": "1",
                "max": str(property_visible_max_results_per_source),
                "selectable_max": str(property_plan_max_results),
                "visual_max": str(property_visible_max_results_per_source),
                "range_step": "1",
                "format": "count",
                "suffix": "",
                "upgrade_hint": _property_upgrade_hint(
                    "max_results_per_source",
                    property_plan_max_results,
                    property_visible_max_results_per_source,
                ),
                "tooltip": "How many strong matches each provider may return. Higher values increase review depth and processing work.",
                "step": "providers",
            },
            {
                "type": "range",
                "name": "min_match_score",
                "label": "Match score",
                "value": str(property_min_match_score_value),
                "min": "1",
                "max": str(property_visible_max_match_score),
                "selectable_max": str(property_plan_max_match_score),
                "visual_max": str(property_visible_max_match_score),
                "range_step": "1",
                "suffix": f"/{property_visible_max_match_score}",
                "upgrade_hint": property_min_match_upgrade_hint,
                "tooltip": property_min_match_tooltip,
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "search_agent_enabled",
                "label": "Create permanent search agent",
                "value": "true",
                "checked": property_search_agent_enabled,
                "tooltip": "Save these settings as an ongoing search agent. Disable this checkbox to keep the settings as a one-off search brief only.",
                "step": "providers",
            },
            {
                "type": "range",
                "name": "search_agent_duration_days",
                "label": "Search agent duration",
                "value": str(property_search_agent_duration_days),
                "min": "7",
                "max": "365",
                "visual_max": "365",
                "range_step": "7",
                "format": "agent_duration_days",
                "scale_min_label": "1 week",
                "scale_mid_label": "6 months",
                "scale_max_label": "1 year",
                "tooltip": "How long this saved search agent should stay active before it expires or needs review.",
                "step": "providers",
            },
            {
                "type": "range",
                "name": "search_agent_notification_limit",
                "label": "Notification budget",
                "value": str(property_search_agent_notification_limit),
                "min": "1",
                "max": "50",
                "visual_max": "50",
                "range_step": "1",
                "format": "notification_count",
                "scale_min_label": "1",
                "scale_mid_label": "25",
                "scale_max_label": "50",
                "tooltip": "Maximum Telegram property alerts to send in the selected period. If more matches exist, PropertyQuarry ranks them and sends only the best ones.",
                "step": "providers",
            },
            {
                "type": "select",
                "name": "search_agent_notification_period",
                "label": "Notification period",
                "value": property_search_agent_notification_period,
                "options": [
                    {"value": "day", "label": "Per day"},
                    {"value": "week", "label": "Per week"},
                ],
                "tooltip": "Choose whether the notification budget resets daily or weekly.",
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "require_floorplan",
                "label": "Serious listings only - floor plan required",
                "value": "true",
                "checked": bool(property_preferences.get("require_floorplan")),
                "step": "providers",
            },
            {
                "type": "checkbox",
                "name": "force_refresh",
                "label": "Force fresh crawl",
                "value": "true",
                "checked": bool(property_preferences.get("force_refresh")),
                "step": "providers",
            },
        ],
        "meta": {
            "preferences_endpoint": str(property_state.get("preferences_endpoint") or ""),
            "start_endpoint": str(property_state.get("start_endpoint") or ""),
            "run_id": str(property_run.get("run_id") or ""),
            "initial_run": property_run,
            "platform_catalog_by_country": dict(property_state.get("platform_catalog_by_country") or {}),
            "default_language_by_country": dict(property_state.get("default_language_by_country") or {}),
            "region_catalog_by_country": {
                option.get("value"): _property_region_options(str(option.get("value") or ""))
                for option in country_options
                if str(option.get("value") or "").strip()
            },
            "market_filter_capabilities_by_country_region": {
                str(option.get("value") or ""): {
                    str(region.get("value") or ""): _property_market_filter_capabilities(
                        str(option.get("value") or ""),
                        str(region.get("value") or ""),
                    )
                    for region in _property_region_options(str(option.get("value") or ""))
                }
                for option in country_options
                if str(option.get("value") or "").strip()
            },
            "market_filter_capabilities": market_filter_capabilities,
            "location_catalog_by_country_region": {
                str(option.get("value") or ""): {
                    str(region.get("value") or ""): _property_location_options(str(option.get("value") or ""), str(region.get("value") or ""))
                    for region in _property_region_options(str(option.get("value") or ""))
                }
                for option in country_options
                if str(option.get("value") or "").strip()
            },
            "supports_all_of_vienna": True,
            "commercial": dict(property_state.get("commercial") or {}),
            "billing_checkout_enabled": bool(property_state.get("billing_checkout_enabled")),
            "billing_checkout_enabled_plans": list(property_state.get("billing_checkout_enabled_plans") or []),
            "billing_checkout_provider": str(property_state.get("billing_checkout_provider") or ""),
            "billing_checkout_provider_label": str(property_state.get("billing_checkout_provider_label") or ""),
            "billing_order_endpoint": str(property_state.get("billing_order_endpoint") or ""),
            "feedback_person_id": str(property_preferences.get("preference_person_id") or "self"),
            "search_agent": property_search_agent,
            "search_agents": property_search_agents,
            "search_agent_update_endpoint_template": "/v1/onboarding/property-search/agents/__AGENT_ID__",
            "shortlist_candidates": property_shortlist_cards,
            "wizard_steps": [
                {
                    "key": "search",
                    "label": "Market",
                    "detail": "Market, mode, and budget.",
                },
                {
                    "key": "areas",
                    "label": "Areas",
                    "detail": "Areas, fit signals, and lifestyle priorities.",
                },
                {
                    "key": "children",
                    "label": "Family",
                    "detail": "Playgrounds, schools, and childcare.",
                },
                {
                    "key": "reachability",
                    "label": "Commute",
                    "detail": "Destinations, travel modes, and time limits.",
                },
                {
                    "key": "research",
                    "label": "Research",
                    "detail": "Risk, supply, investment, and evidence depth.",
                },
                {
                    "key": "providers",
                    "label": "Sources",
                    "detail": "Choose sources, then save or launch.",
                },
            ],
        },
    }
    if selected_listing_mode != "buy":
        property_form["fields"] = [
            field
            for field in list(property_form.get("fields") or [])
            if str(field.get("name") or "").strip() != "investment_research_mode"
        ]

    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": str(
                preview.get("headline")
                or status.get("next_step")
                or "Start with the operating memo, clear the decision queue, and keep commitments from drifting."
            ),
            "cards": [
                {
                    "eyebrow": "Live queue",
                    "title": "What needs action now",
                    "body": "The day opens on real approvals and human tasks instead of a motivational dashboard.",
                    "items": live_queue
                    or string_rows(
                        first_brief,
                        ("Connect Google sign-in if you want easier return access from the same account.",),
                        tag="Next",
                        detail="This is the shortest path to a real working day.",
                    ),
                },
                {
                    "eyebrow": "Outbound work",
                    "title": "What is queued to leave the office loop",
                    "body": "Pending delivery stays visible so drafts, approvals, and sends never blur together.",
                    "items": pending_delivery_items
                    or string_rows(
                        suggested,
                        ("No queued delivery yet.",),
                        tag="Review",
                        detail="Once a draft or action is ready, it will show up here.",
                    ),
                },
                {
                    "eyebrow": "Brief signal",
                    "title": "What is shaping the day",
                    "body": "The memo stays narrative, but it still points at work that exists.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="Use the memo to set the order of operations."),
                },
                {
                    "eyebrow": "Identity and channels",
                    "title": "Keep setup boring and useful",
                    "body": "Identity stays simple. Channels widen coverage only after the first loop works.",
                    "items": identity_posture_items,
                },
            ],
        },
        "queue": {
            "title": "Decision Queue",
            "summary": str(preview.get("headline") or "Turn the day into decisions: approve, assign, defer, or close."),
            "cards": [
                {
                    "eyebrow": "Decision pressure",
                    "title": "What changed",
                    "body": "The queue explains what changed, why it matters, and what decision belongs next.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="This is the current ranked memo item."),
                },
                {
                    "eyebrow": "Themes",
                    "title": "Recurring topics",
                    "body": "Themes help the user understand the day without reopening every thread.",
                    "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="This theme is active in the current workspace."),
                },
                {
                    "eyebrow": "Live queue",
                    "title": "What the queue clears",
                    "body": "A useful queue terminates in real approvals, assignments, or outbound actions.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live review items yet.",),
                        tag="Queue",
                        detail="Once the office loop starts moving, the memo points here.",
                    ),
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "People affected by the queue",
                    "body": "Stakeholders only matter if they stay attached to the decisions and commitments in front of the team.",
                    "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="This person is active in the current memo."),
                },
            ],
        },
        "commitments": {
            "title": "Commitments",
            "summary": "Messages, meetings, and notes only matter when they update a commitment, create a decision, or close a loop.",
            "cards": [
                {
                    "eyebrow": "Commitment pressure",
                    "title": "What is in motion",
                    "body": "This surface shows which commitments are active, which decisions are waiting, and which drafts are holding things up.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live commitment queue yet.",),
                        tag="Draft",
                        detail="Once drafts or approvals exist, they will appear here.",
                    ),
                },
                {
                    "eyebrow": "Queued delivery",
                    "title": "What is waiting to leave",
                    "body": "Outbound work is part of the commitment loop, not hidden afterthought state.",
                    "items": pending_delivery_items
                    or string_rows(
                        channel_lines,
                        ("No delivery queue yet.",),
                        tag="Ready",
                        detail="Connected channels determine what the queue can actually move.",
                    ),
                },
                {
                    "eyebrow": "Decision pressure",
                    "title": "What will bubble up next",
                    "body": "The commitment ledger gets its order from pressure and deadlines, not from unread-count theater.",
                    "items": string_rows(first_brief, ("No priorities surfaced yet.",), tag="Memo", detail="This is the current upstream signal for the commitment queue."),
                },
            ],
        },
        "people": {
            "title": "People Graph",
            "summary": "The product moat lives in the relationship system: people, recurring themes, open loops, and office pressure that survive beyond one session.",
            "cards": [
                {"eyebrow": "Stakeholders", "title": "Who matters right now", "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="These people are shaping the current office loop.")},
                {"eyebrow": "Relationship themes", "title": "What keeps recurring", "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="Recurring pressure and themes stay durable in the workspace.")},
                {"eyebrow": "Rules", "title": "What the office memory may keep", "items": string_rows(privacy_lines, ("No retention policy set yet.",), tag="Policy", detail="These rules bound what the workspace retains.")},
            ],
        },
        "evidence": {
            "title": "Evidence",
            "summary": "Evidence explains why something surfaced: which signal, which channel, which context, and which rule put it in front of the team.",
            "cards": [
                {"eyebrow": "Memo evidence", "title": "Why items surfaced", "items": string_rows(first_brief, ("No evidence rows surfaced yet.",), tag="Evidence", detail="This is one of the signals behind the current operating view.")},
                {"eyebrow": "Trust notes", "title": "What keeps the surface explainable", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Rule", detail="These constraints explain why the assistant behaved this way.")},
                {"eyebrow": "Channel sources", "title": "Where the evidence came from", "items": channel_items},
            ],
        },
        "channels": {
            "title": "Channels",
            "summary": "Channels widen coverage. They never redefine the product core or become the main story of the workspace.",
            "cards": [
                {"eyebrow": "Google", "title": cards[0]["label"], "items": [cards[0]["detail"], cards[0]["summary"] or "Google sign-in is the recommended first connection."]},
                {"eyebrow": "Telegram", "title": cards[1]["label"], "items": [cards[1]["detail"], cards[1]["summary"] or "Personal identity and bot install stay distinct."]},
                {"eyebrow": "WhatsApp", "title": cards[2]["label"], "items": [cards[2]["detail"], cards[2]["summary"] or "Business onboarding and export intake stay separate."]},
            ],
        },
        "automations": {
            "title": "Policies",
            "summary": "Policies stay understandable: what the assistant may read, draft, send, remember, and escalate.",
            "cards": [
                {"eyebrow": "Assistant posture", "title": "Current rules", "items": privacy_lines},
                {"eyebrow": "Suggested changes", "title": "What to unlock next", "items": suggested},
                {"eyebrow": "Guardrails", "title": "Why these rules exist", "items": trust_notes},
            ],
        },
        "activity": {
            "title": "Audit",
            "summary": "Audit explains what changed, what left the system, and which rule or review point allowed it.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current state", "items": string_rows([f"Status: {status_label}", f"Setup state: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"], ("No workspace state yet.",), tag="State", detail="This is the current workspace status.")},
                {"eyebrow": "Channels", "title": "Recent changes", "items": channel_items},
                {"eyebrow": "Trust", "title": "Why this feed matters", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Context", detail="This keeps the activity feed understandable.")},
            ],
        },
        "settings": {
            "title": "Rules",
            "summary": "Rules stay boring and explicit once the first working loop already exists.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current workspace posture", "items": string_rows([f"Name: {workspace.get('name') or 'PropertyQuarry'}", f"Mode: {humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"], ("No workspace posture yet.",), tag="Workspace", detail="These are the current office defaults.")},
                {"eyebrow": "Policy", "title": "Assistant behavior", "items": string_rows(privacy_lines, ("No privacy posture set yet.",), tag="Rule", detail="These controls shape what the assistant may do.")},
                {"eyebrow": "Channels", "title": "Selected linked channels", "items": channel_items},
            ],
        },
        "properties": {
            "title": "Properties",
            "summary": (
                str(property_run.get("message") or "").strip()
                or "Run a dedicated cross-platform property crawl, keep the progress visible, and surface hosted 3D-tour matches instead of raw listing noise."
            ),
            "cards": [
                {
                    "eyebrow": "Search posture",
                    "title": "What this search is optimizing for",
                    "body": "The crawl posture stays explicit: market, research language, target location, property shape, and who the ranking is trying to satisfy.",
                    "items": property_market_summary_items
                    + [
                        row_item(
                            "Preference profile",
                            str(property_preferences.get("preference_person_id") or "self"),
                            "Profile",
                        ),
                        row_item(
                            "Active providers",
                            ", ".join(property_selected_platform_labels) if property_selected_platform_labels else "No providers saved yet.",
                            "Profile",
                        ),
                        row_item(
                            "Result cap per source",
                            str(property_preferences.get("max_results_per_source") or "3"),
                            "Guardrail",
                        ),
                    ],
                },
                {
                    "eyebrow": "Market coverage",
                    "title": "Which providers this country unlocks",
                    "body": "Each market switches the provider catalog. The saved selection should be a deliberate subset, not a hard-coded Austria-only list.",
                    "items": [
                        row_item(
                            "Country bundle",
                            f"{property_country_label} | {property_provider_total_for_country or len(platform_options)} supported providers",
                            "Coverage",
                        ),
                        row_item(
                            "Selected now",
                            str(len(property_selected_platform_labels) or 0),
                            "Selection",
                        ),
                    ] + (property_platform_rows[:4] if property_platform_rows else []),
                },
                {
                    "eyebrow": "Shortlist",
                    "title": "Ranked review desk",
                    "body": "The strongest matches stay review-ready: fit, risk, 360 status, packet link, and the next useful action are visible before operational crawl details.",
                    "items": property_shortlist_rows
                    or property_recent_matches
                    or [
                        row_item(
                            "First shortlist still pending",
                            "Launch the first sweep to generate a ranked candidate lane with review packets, hosted tours, and visible fit reasons.",
                            "First run",
                        )
                    ],
                },
                {
                    "eyebrow": "Run status",
                    "title": "Current crawl",
                    "body": str(property_run.get("message") or "Start a crawl to see source-by-source progress, shortlisted hosted tours, and what actually got sent."),
                    "items": property_source_rows
                    or property_event_rows
                    or [
                        row_item(
                            "No live search in flight",
                            "Save the brief, then launch the first dedicated run to expose source-by-source progress and shortlist formation here.",
                            "Ready",
                        )
                    ],
                },
                {
                    "eyebrow": "Learning loop",
                    "title": "What the product has learned from feedback",
                    "body": "Paid research only gets stronger if the system remembers what helped, what failed, and which hard rules should suppress future noise.",
                    "items": property_learning_rows
                    or property_recent_feedback_rows
                    or [
                        row_item(
                            "Preference memory is still clean",
                            "Record feedback on packets and shortlists to teach the ranking what to favor, what to suppress, and which rules should stay hard.",
                            "Learning",
                        )
                    ],
                },
                {
                    "eyebrow": "Recent matches",
                    "title": "Hosted pages already delivered",
                    "body": "Strong matches should resolve to branded hosted property pages or review packets, not raw portal links.",
                    "items": property_recent_matches
                    or property_event_rows
                    or [
                        row_item(
                            "No hosted follow-up has left the desk yet",
                            "The first credible packet, hosted page, or review follow-up will appear here once a candidate is strong enough to share.",
                            "Outbound",
                        )
                    ],
                },
            ],
            "stats": [
                {"label": "Country", "value": property_country_label},
                {"label": "Providers", "value": str(len(property_selected_platform_labels) or 0)},
                {"label": "Sources", "value": str(int(property_summary.get("sources_total") or 0))},
                {"label": "Listings", "value": str(int(property_summary.get("listing_total") or 0))},
                {"label": "Hosted tours", "value": str(int(property_summary.get("tour_created_total") or 0) + int(property_summary.get("tour_existing_total") or 0))},
            ],
            "console_form": property_form,
        },
    }
    payload = dict(mapping[section])
    payload.setdefault("stats", stats)
    return payload


def property_workspace_payload(
    section: str,
    *,
    status: dict[str, object],
    property_state: dict[str, object],
) -> dict[str, object]:
    base = app_section_payload("properties", status, live_feed=(), property_context=property_state)
    cards = list(base.get("cards") or [])
    cards_by_eyebrow = {
        str(card.get("eyebrow") or "").strip().lower(): dict(card)
        for card in cards
        if isinstance(card, dict)
    }
    cards_by_title = {
        str(card.get("title") or "").strip().lower(): dict(card)
        for card in cards
        if isinstance(card, dict)
    }
    property_form = dict(base.get("console_form") or {})
    property_meta = dict(property_form.get("meta") or {})
    property_search_agents = [
        dict(agent)
        for agent in list(property_meta.get("search_agents") or [])
        if isinstance(agent, dict)
    ]
    property_search_agent = next((agent for agent in property_search_agents if agent.get("is_active")), property_search_agents[0] if property_search_agents else {})
    provider_options = []
    for field in list(property_form.get("schema") or []):
        if not isinstance(field, dict):
            continue
        if str(field.get("name") or "").strip() != "selected_platforms":
            continue
        provider_options = [dict(option) for option in list(field.get("options") or []) if isinstance(option, dict)]
        break
    commercial = dict(property_state.get("commercial") or {})
    property_preferences = dict(property_state.get("preferences") or {})
    preference_person_id = str(property_state.get("preference_person_id") or property_preferences.get("preference_person_id") or "self").strip() or "self"
    preference_bundle = dict(property_state.get("preference_bundle") or {})
    raw_preference_nodes = [
        dict(row)
        for row in list(preference_bundle.get("preference_nodes") or [])
        if isinstance(row, dict)
    ]
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    google = dict(channels.get("google") or {})
    current_plan_label = str(commercial.get("current_plan_label") or "Free").strip() or "Free"
    try:
        current_platform_cap = int(commercial.get("max_platforms") if commercial.get("max_platforms") is not None else 3)
    except Exception:
        current_platform_cap = 3
    search_posture_card = cards_by_eyebrow.get("search posture", {})
    market_coverage_card = cards_by_eyebrow.get("market coverage", {})
    shortlist_card = cards_by_eyebrow.get("shortlist", {})
    run_card = cards_by_eyebrow.get("run status", {})
    learning_card = cards_by_eyebrow.get("learning loop", {})
    recent_matches_card = cards_by_eyebrow.get("recent matches", {})
    shortlist_candidates = list(property_meta.get("shortlist_candidates") or [])
    run_payload = dict(property_state.get("run") or {})
    run_events = list(run_payload.get("events") or [])
    run_summary = dict(run_payload.get("summary") or {})
    run_sources = [dict(row) for row in list(run_summary.get("sources") or []) if isinstance(row, dict)]
    provider_quality_by_key: dict[str, dict[str, object]] = {}
    for candidate_row in list(run_summary.get("ranked_candidates") or []):
        if not isinstance(candidate_row, dict):
            continue
        candidate_quality = candidate_row.get("provider_quality")
        if not isinstance(candidate_quality, dict) or not candidate_quality:
            continue
        for key_value in (
            candidate_row.get("source_ref"),
            candidate_row.get("property_url"),
            candidate_row.get("listing_id"),
            candidate_row.get("title"),
        ):
            key = str(key_value or "").strip().lower()
            if key:
                provider_quality_by_key.setdefault(key, dict(candidate_quality))
    if provider_quality_by_key:
        for candidate_row in shortlist_candidates:
            if not isinstance(candidate_row, dict) or isinstance(candidate_row.get("provider_quality"), dict):
                continue
            for key_value in (
                candidate_row.get("source_ref"),
                candidate_row.get("property_url"),
                candidate_row.get("listing_id"),
                candidate_row.get("title"),
            ):
                key = str(key_value or "").strip().lower()
                if key and key in provider_quality_by_key:
                    candidate_row["provider_quality"] = dict(provider_quality_by_key[key])
                    break
    raw_research_tasks = list(run_payload.get("research_tasks") or run_summary.get("research_tasks") or [])
    selected_locations = _csv_values(property_preferences.get("location_query"))
    selected_keywords = _csv_values(property_preferences.get("keywords"))
    selected_platforms = [str(value).strip() for value in list(property_state.get("selected_platforms") or []) if str(value).strip()]
    provider_quality_rows = _provider_quality_rows(run_sources, provider_options)
    suppression_rows = _property_suppression_rows(
        run_summary=run_summary,
        source_rows=run_sources,
    )
    delivery_proof_rows = _delivery_proof_rows(run_summary)
    artifact_receipt_rows = _artifact_receipt_rows(run_summary)
    selected_candidate_ref = str(property_state.get("selected_candidate_ref") or "").strip()
    run_id = str(run_payload.get("run_id") or "").strip()
    run_suffix = f"?run_id={run_id}" if run_id else ""
    search_posture_items = list(search_posture_card.get("items") or [])
    packet_ready_total = sum(
        1
        for candidate in shortlist_candidates
        if str(candidate.get("packet_url") or candidate.get("review_url") or "").strip()
    )
    tour_ready_total = sum(1 for candidate in shortlist_candidates if str(candidate.get("tour_url") or "").strip())

    def _property_run_status_copy(status_value: object, message_value: object = "") -> tuple[str, str]:
        status = str(status_value or "").strip().lower()
        message = str(message_value or "").strip()
        if status in {"processed", "completed"}:
            return ("Finished", "")
        if status == "failed":
            return ("Needs attention", message or "The search stopped before ranking finished.")
        if status == "cancelled":
            return ("Stopped", message or "This search was stopped before it finished.")
        if status == "noop":
            return ("No changes", message or "The search finished without anything new to rank.")
        if status in {"queued", "starting"}:
            return ("Queued", message)
        if status in {"running", "in_progress", "processing", "scanning"}:
            return ("Running", message)
        label = status.replace("_", " ").title() if status else "Queued"
        return (label, message)

    run_message = str(run_payload.get("message") or "").strip()
    run_status_value = str(run_payload.get("status") or "").strip().lower()
    run_status_label, run_status_note = _property_run_status_copy(run_status_value or "not started", run_message)
    run_in_progress = bool(run_id and run_status_value and run_status_value not in {"processed", "completed", "failed", "noop", "cancelled", "not started"})
    progress_route_previews = _property_progress_route_preview_rows(
        run_summary=run_summary,
        property_preferences=property_preferences,
    )
    search_worker_state = _property_search_worker_slots(run_summary, plan_key=str(commercial.get("current_plan_key") or "free"))

    research_tasks: list[dict[str, object]] = []
    for task in raw_research_tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            continue
        status = str(task.get("status") or "queued").strip().lower().replace("_", " ") or "queued"
        next_actions = [str(item).strip() for item in list(task.get("next_actions") or []) if str(item).strip()]
        ooda = dict(task.get("ooda") or {}) if isinstance(task.get("ooda"), dict) else {}
        detail = (
            str(task.get("evidence") or "").strip()
            or str(ooda.get("act") or ooda.get("orient") or "").strip()
            or (next_actions[0] if next_actions else "")
            or "PropertyQuarry is trying to complete this fact from the available source material."
        )
        research_tasks.append(
            {
                "task_id": task_id,
                "field": str(task.get("field") or "").strip(),
                "label": str(task.get("label") or task.get("field") or "Missing fact").strip(),
                "status": status,
                "status_label": status.title(),
                "priority": str(task.get("priority") or "normal").strip().lower(),
                "title": str(task.get("title") or "Property").strip(),
                "source_label": str(task.get("source_label") or "").strip(),
                "property_url": str(task.get("property_url") or "").strip(),
                "review_url": str(task.get("review_url") or "").strip(),
                "fit_score": task.get("fit_score") or 0,
                "display_value": str(task.get("display_value") or task.get("owner_value") or "").strip(),
                "detail": detail,
                "next_action": next_actions[0] if next_actions else str(ooda.get("act") or "").strip(),
                "updated_at": str(task.get("updated_at") or "").strip(),
                "owner_note": str(task.get("owner_note") or "").strip(),
            }
        )
    research_tasks.sort(
        key=lambda row: (
            1 if str(row.get("status") or "") == "filled" else 0,
            1 if str(row.get("status") or "") == "dismissed" else 0,
            0 if str(row.get("priority") or "") == "high" else 1,
            -float(row.get("fit_score") or 0),
            str(row.get("title") or "").lower(),
        )
    )
    open_research_task_total = int(run_payload.get("open_research_task_total") or run_summary.get("open_research_task_total") or sum(1 for task in research_tasks if str(task.get("status") or "") in {"queued", "in progress", "blocked"}))
    filled_research_task_total = int(run_payload.get("filled_research_task_total") or run_summary.get("filled_research_task_total") or sum(1 for task in research_tasks if str(task.get("status") or "") == "filled"))
    dismissed_research_task_total = int(run_payload.get("dismissed_research_task_total") or run_summary.get("dismissed_research_task_total") or sum(1 for task in research_tasks if str(task.get("status") or "") == "dismissed"))
    research_task_total = int(run_payload.get("research_task_total") or run_summary.get("research_task_total") or len(research_tasks))

    def _previous_run_int(value: object, default: int = 0) -> int:
        try:
            return max(0, int(float(str(value or "").strip())))
        except Exception:
            return default

    def _format_previous_search_run(raw_run: dict[str, object]) -> dict[str, object]:
        summary = dict(raw_run.get("summary") or {}) if isinstance(raw_run.get("summary"), dict) else {}
        preferences_json = dict(raw_run.get("property_search_preferences") or raw_run.get("preferences") or {}) if isinstance(raw_run.get("property_search_preferences") or raw_run.get("preferences"), dict) else {}
        run_status = str(raw_run.get("status") or summary.get("status") or "queued").strip().lower()
        run_id_value = str(raw_run.get("run_id") or "").strip()
        country = str(preferences_json.get("country_code") or summary.get("country_code") or "").strip().upper()
        region = str(preferences_json.get("region_code") or summary.get("region_code") or "").strip()
        location = str(preferences_json.get("location_query") or summary.get("location_query") or "").strip()
        mode = str(preferences_json.get("listing_mode") or summary.get("listing_mode") or "").strip().title()
        scope_parts = [part for part in (country, region, location) if part]
        ranked_candidates = [
            dict(row)
            for row in list(summary.get("ranked_candidates") or [])
            if isinstance(row, dict)
        ]
        top_candidates: list[dict[str, object]] = []
        for candidate in ranked_candidates[:3]:
            title = str(candidate.get("title") or "Property").strip() or "Property"
            source_label = str(candidate.get("source_label") or candidate.get("source_platform") or "Source").strip() or "Source"
            top_candidates.append(
                {
                    "title": title,
                    "source_label": source_label,
                    "fit_score": _previous_run_int(candidate.get("fit_score")),
                    "detail": str(
                        candidate.get("compare_reason")
                        or candidate.get("fit_summary")
                        or (list(candidate.get("match_reasons") or [""])[0] if isinstance(candidate.get("match_reasons"), list) else "")
                        or "Open the finished search to review this candidate."
                    ).strip(),
                    "review_url": str(candidate.get("packet_url") or candidate.get("review_url") or "").strip(),
                    "map_url": str(candidate.get("map_url") or _property_candidate_maps_url(candidate)).strip(),
                }
            )
        held_back_total = max(
            0,
            _previous_run_int(summary.get("filtered_floorplan_total"))
            + _previous_run_int(summary.get("filtered_area_total"))
            + _previous_run_int(summary.get("filtered_low_fit_total"))
            + _previous_run_int(summary.get("notification_budget_suppressed_total")),
        )
        status_label, status_note = _property_run_status_copy(
            raw_run.get("status") or summary.get("status"),
            raw_run.get("message") or summary.get("message"),
        )
        scope_preview = _property_scope_preview(country, region, location)
        return {
            "run_id": run_id_value,
            "agent_id": str(raw_run.get("active_search_agent_id") or preferences_json.get("active_search_agent_id") or "").strip(),
            "status": run_status,
            "status_label": status_label,
            "status_note": status_note,
            "title": location or region or country or "Saved search",
            "scope_label": " · ".join(scope_parts) or "No scope saved",
            "scope_preview": scope_preview,
            "scope_summary": str(scope_preview.get("summary") or location or region or country or "Search area").strip(),
            "mode_label": mode or "Search",
            "href": f"/app/properties?run_id={urllib.parse.quote(run_id_value, safe='')}" if run_id_value else "/app/properties",
            "updated_at": str(raw_run.get("updated_at") or raw_run.get("generated_at") or "").strip(),
            "source_total": _previous_run_int(summary.get("sources_total")),
            "listing_total": _previous_run_int(summary.get("listing_total") or summary.get("raw_listing_total")),
            "ranked_total": len(ranked_candidates),
            "sent_total": _previous_run_int(summary.get("notified_total") or summary.get("watch_notified_total")),
            "held_back_total": held_back_total,
            "top_fit_score": _previous_run_int(summary.get("top_fit_score") or (top_candidates[0].get("fit_score") if top_candidates else 0)),
            "top_candidates": top_candidates,
            "is_finished": run_status in {"processed", "completed", "failed", "noop", "cancelled"},
        }

    previous_search_runs = [
        _format_previous_search_run(dict(row))
        for row in list(property_state.get("recent_search_runs") or [])
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    ]
    requested_agent_id = str(property_state.get("selected_agent_id") or "").strip()
    selected_agent = next((agent for agent in property_search_agents if str(agent.get("agent_id") or "").strip() == requested_agent_id), None)
    if selected_agent is None:
        selected_agent = next((agent for agent in property_search_agents if agent.get("is_active")), property_search_agents[0] if property_search_agents else None)
    selected_agent_id = str((selected_agent or {}).get("agent_id") or "").strip()
    selected_agent_runs = [
        dict(row)
        for row in previous_search_runs
        if isinstance(row, dict)
        and (
            (selected_agent_id and str(row.get("agent_id") or "").strip() == selected_agent_id)
            or (
                selected_agent
                and not str(row.get("agent_id") or "").strip()
                and str(row.get("title") or "").strip() == str(selected_agent.get("location_query") or "").strip()
            )
        )
    ]
    selected_agent_latest_run = selected_agent_runs[0] if selected_agent_runs else {}
    selected_agent_open_href = ""
    selected_agent_edit_href = ""
    if selected_agent_id:
        selected_agent_open_href = f"/app/agents?agent_id={urllib.parse.quote(selected_agent_id, safe='')}"
        selected_agent_edit_href = f"/app/properties?load_agent={urllib.parse.quote(selected_agent_id, safe='')}"
        if run_id:
            selected_agent_open_href = f"{selected_agent_open_href}&run_id={urllib.parse.quote(run_id, safe='')}"
            selected_agent_edit_href = f"{selected_agent_edit_href}&run_id={urllib.parse.quote(run_id, safe='')}"

    def _preference_value_label(value: object) -> str:
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip()) or "empty list"
        if isinstance(value, dict):
            return ", ".join(f"{key}: {item}" for key, item in value.items() if str(key).strip()) or "empty object"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value if value is not None else "").strip() or "empty"

    def _preference_key_label(row: dict[str, object]) -> str:
        key = str(row.get("key") or "").strip().replace("_", " ")
        category = str(row.get("category") or "").strip().replace("_", " ")
        return (key or "Preference").title() + (f" ({category.title()})" if category else "")

    preference_manager_nodes = [
        {
            "node_id": str(row.get("node_id") or "").strip(),
            "domain": str(row.get("domain") or "").strip() or "willhaben",
            "category": str(row.get("category") or "").strip() or "soft_preference",
            "key": str(row.get("key") or "").strip(),
            "label": _preference_key_label(row),
            "value_label": _preference_value_label(row.get("value_json")),
            "value_json": row.get("value_json"),
            "strength": str(row.get("strength") or "medium").strip() or "medium",
            "confidence": row.get("confidence") or 0,
            "source_mode": str(row.get("source_mode") or "").strip(),
            "status": str(row.get("status") or "").strip().lower() or "active",
            "updated_at": str(row.get("updated_at") or "").strip(),
        }
        for row in raw_preference_nodes
        if str(row.get("node_id") or "").strip()
    ]
    preference_manager_nodes.sort(key=lambda row: (str(row.get("status") or "") != "active", str(row.get("label") or "").lower()))
    preference_manager = {
        "person_id": preference_person_id,
        "nodes": preference_manager_nodes,
        "active_nodes": [row for row in preference_manager_nodes if str(row.get("status") or "") == "active"],
        "schema": _property_preference_schema(),
        "bundle_endpoint": f"/app/api/people/{preference_person_id}/preference-profile",
        "node_endpoint": f"/app/api/people/{preference_person_id}/preference-profile/nodes",
        "archive_endpoint_template": f"/app/api/people/{preference_person_id}/preference-profile/nodes/__NODE_ID__/archive",
    }

    def _tour_source_gap_detail(candidate: dict[str, object]) -> str:
        blocked_reason = str(candidate.get("blocked_reason") or "").strip()
        if blocked_reason:
            reason_map = {
                "listing_360_media_missing": "Tour not ready yet: the listing does not expose usable layout or 360 material.",
                "pure_360_assets_unavailable": "Tour not ready yet: the source media cannot be opened reliably.",
                "property_tour_fallback_disabled": "Tour not ready yet: PropertyQuarry needs source layout or 360 material first.",
            }
            return reason_map.get(blocked_reason, blocked_reason.replace("_", " "))
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}

        def _false_flag(value: object) -> bool:
            return str(value or "").strip().lower() in {"0", "false", "no", "none", "null"}

        def _zero_count(*keys: str) -> bool:
            for key in keys:
                raw_value = facts.get(key)
                if raw_value in (None, ""):
                    continue
                try:
                    return float(str(raw_value).strip()) <= 0.0
                except Exception:
                    continue
            return False

        if _false_flag(facts.get("has_floorplan")) or _zero_count("floorplan_count", "floorplans_count"):
            return "Tour not ready yet: layout proof or source 360 media is not verified."
        if _false_flag(facts.get("has_360")) or _zero_count("media_count", "image_count"):
            return "Tour not ready yet: source room media is not verified."
        return "Tour not ready yet: source layout or 360 media is not verified."

    def _candidate_fact_line(candidate: dict[str, object]) -> str:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        parts: list[str] = []
        price_value = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price")
            or facts.get("price_eur")
            or ""
        ).strip()
        rooms_value = str(facts.get("rooms") or facts.get("room_count") or "").strip()
        area_value = str(facts.get("area_m2") or facts.get("living_area_m2") or "").strip()
        if price_value:
            parts.append(price_value)
        if rooms_value:
            parts.append(f"{rooms_value} rooms")
        if area_value:
            parts.append(f"{area_value} m2")
        return " | ".join(parts)

    compare_rows = []
    for candidate in shortlist_candidates[:3]:
        fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "").strip()
        fact_line = _candidate_fact_line(candidate)
        detail = " | ".join(part for part in (fit_summary, fact_line) if part) or "Open the packet to inspect the ranking and the evidence."
        compare_rows.append(
            {
                "title": str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate",
                "detail": detail,
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open packet",
                "secondary_action_href": str(candidate.get("tour_url") or candidate.get("review_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("tour_url") or candidate.get("review_url")) else "",
                "secondary_action_label": "Open 360" if candidate.get("tour_url") else ("Review details" if candidate.get("review_url") else ""),
            }
        )

    def _tour_status_line(candidate: dict[str, object]) -> str:
        if str(candidate.get("tour_url") or "").strip():
            return "Ready | Live now"
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_minutes = int(candidate.get("tour_eta_minutes") or 0) if str(candidate.get("tour_eta_minutes") or "").strip() else 0
        if status in {"queued", "pending"}:
            return f"Queued | ETA about {eta_minutes or 10} min"
        if status in {"processing", "running", "in_progress", "started"}:
            return f"Rendering | ETA about {eta_minutes or 5} min"
        if status in {"created", "existing"}:
            return "Ready"
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return f"Blocked | {_tour_source_gap_detail(candidate)}"
        blocked_reason = str(candidate.get("blocked_reason") or "").strip()
        if blocked_reason:
            return f"Blocked | {blocked_reason.replace('_', ' ')}"
        return f"Unavailable | {_tour_source_gap_detail(candidate)}"

    def _distance_line(candidate: dict[str, object]) -> str:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        family_filters_active = _property_family_filters_active(property_preferences)
        specs = (
            ("Playground", facts.get("nearest_playground_m") or facts.get("distance_playground_m"), True),
            ("Library", facts.get("nearest_library_m"), True),
            ("Zoo", facts.get("nearest_zoo_m"), True),
            ("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("distance_pharmacy_m"), False),
            ("Medical", facts.get("nearest_medical_care_m"), True),
            ("Supermarket", facts.get("nearest_supermarket_m") or facts.get("distance_supermarket_m"), False),
            ("Market", facts.get("nearest_market_m"), False),
            ("Baumarkt", facts.get("nearest_hardware_store_m"), False),
            ("Starbucks", facts.get("nearest_starbucks_m"), False),
            ("Fitness", facts.get("nearest_fitness_center_m"), False),
            ("Run", facts.get("nearest_running_m"), False),
            ("Straßenbahn / Bus", facts.get("nearest_tram_bus_m") or facts.get("nearest_transit_m"), False),
            ("Underground", facts.get("nearest_subway_m") or facts.get("distance_underground_m"), False),
        )
        parts: list[str] = []
        for label, raw_value, family_only in specs:
            if family_only and not family_filters_active:
                continue
            if raw_value in (None, "", []):
                continue
            try:
                meters = int(float(raw_value))
            except Exception:
                continue
            bike_minutes = max(1, int(round(float(meters) / 330.0)))
            parts.append(f"{label} {meters} m | {bike_minutes} min bike")
        return " · ".join(parts[:3])

    results_table_rows = []
    workbench_results: list[dict[str, object]] = []

    def _money_per_sqm_line(facts: dict[str, object]) -> str:
        raw_price = facts.get("price_eur") or facts.get("purchase_price_eur")
        raw_area = facts.get("area_m2") or facts.get("living_area_m2")
        try:
            price = float(raw_price)
            area = float(raw_area)
        except Exception:
            return ""
        if price <= 0 or area <= 0:
            return ""
        return f"EUR {price / area:,.0f}/m2"

    def _missing_fact_items(facts: dict[str, object]) -> list[dict[str, object]]:
        research = facts.get("missing_fact_research")
        if not isinstance(research, dict):
            return []
        items = research.get("items")
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _missing_fact_item(facts: dict[str, object], field: str) -> dict[str, object]:
        normalized = str(field or "").strip()
        for item in _missing_fact_items(facts):
            if str(item.get("field") or "").strip() == normalized:
                return item
        return {}

    def _rooms_layout_part(facts: dict[str, object]) -> str:
        label = str(facts.get("rooms_label") or "").strip()
        if label:
            return label
        raw_value = facts.get("rooms") or facts.get("room_count")
        if raw_value:
            return f"{raw_value} rooms"
        item = _missing_fact_item(facts, "rooms")
        if item:
            return str(item.get("display_value") or "Rooms under research").strip() or "Rooms under research"
        return ""

    def _risk_summary(candidate: dict[str, object], facts: dict[str, object]) -> dict[str, str]:
        mismatch = [str(item).strip() for item in list(candidate.get("mismatch_reasons") or []) if str(item).strip()]
        missing: list[str] = []
        if not str(candidate.get("tour_url") or "").strip():
            tour_status = str(candidate.get("tour_status") or "").strip().lower()
            if tour_status in {"blocked", "failed", "skipped", "not_applicable"}:
                missing.append("floorplan/360 source media")
            else:
                missing.append("360 pending")
        if not (facts.get("street_address") or facts.get("address")):
            missing.append("address")
        if not (facts.get("heating") or facts.get("heating_type")):
            missing.append("heating")
        if bool(facts.get("air_quality_risk")):
            missing.append("air quality")
        if bool(facts.get("crime_risk")):
            missing.append("crime risk")
        if bool(facts.get("parking_pressure_risk")):
            missing.append("parking pressure")
        if bool(facts.get("drinking_water_risk")):
            missing.append("water quality")
        if bool(facts.get("cesspit_risk")):
            missing.append("Senkgrube or septic burden")
        if bool(facts.get("winter_access_risk")):
            missing.append("winter access")
        if bool(facts.get("flood_risk")):
            missing.append("flood exposure")
        for item in _missing_fact_items(facts):
            if str(item.get("status") or "").strip().lower() != "filled":
                missing.append(str(item.get("label") or item.get("field") or "research fact").strip())
        if mismatch:
            return {"level": "medium", "summary": mismatch[0]}
        if len(missing) >= 2:
            return {"level": "medium", "summary": "Missing " + ", ".join(missing[:3])}
        if missing:
            return {"level": "low", "summary": "Missing " + missing[0]}
        return {"level": "low", "summary": "No major packet risk flagged yet."}

    def _candidate_ooda_rows(candidate: dict[str, object], facts: dict[str, object]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        family_filters_active = _property_family_filters_active(property_preferences)
        for label, raw_value, family_only in (
            ("Playground", facts.get("nearest_playground_m") or facts.get("distance_playground_m"), True),
            ("Library", facts.get("nearest_library_m"), True),
            ("Zoo", facts.get("nearest_zoo_m"), True),
            ("Pharmacy", facts.get("nearest_pharmacy_m") or facts.get("distance_pharmacy_m"), False),
            ("Medical care", facts.get("nearest_medical_care_m"), True),
            ("Supermarket", facts.get("nearest_supermarket_m") or facts.get("distance_supermarket_m"), False),
            ("Market", facts.get("nearest_market_m"), False),
            ("Baumarkt", facts.get("nearest_hardware_store_m"), False),
            ("Starbucks", facts.get("nearest_starbucks_m"), False),
            ("Fitness", facts.get("nearest_fitness_center_m"), False),
            ("Run or green space", facts.get("nearest_running_m"), False),
            ("Straßenbahn / Bus", facts.get("nearest_tram_bus_m") or facts.get("nearest_transit_m"), False),
            ("Underground", facts.get("nearest_subway_m") or facts.get("distance_underground_m"), False),
        ):
            if family_only and not family_filters_active:
                continue
            if raw_value in (None, "", []):
                continue
            try:
                meters = int(float(raw_value))
            except Exception:
                continue
            rows.append(
                {
                    "label": label,
                    "value": f"{meters} m",
                    "detail": f"about {max(1, int(round(float(meters) / 330.0)))} min by bike",
                }
            )
        match_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("match_reasons") or []) if _clean_property_candidate_copy(item)]
        mismatch_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("mismatch_reasons") or []) if _clean_property_candidate_copy(item)]
        rows.insert(
            0,
            {
                "label": "Decide",
                "value": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(),
                "detail": match_reasons[0] if match_reasons else (mismatch_reasons[0] if mismatch_reasons else "Open the packet for the full decision read."),
            },
        )
        for item in _missing_fact_items(facts):
            if str(item.get("status") or "").strip().lower() == "filled":
                continue
            ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
            label = str(item.get("label") or item.get("field") or "Missing fact").strip()
            rows.append(
                {
                    "label": "Research",
                    "value": str(item.get("display_value") or label).strip(),
                    "detail": str(ooda.get("act") or item.get("evidence") or "Missing-fact research queued.").strip(),
                }
            )
        for risk_key, label, detail in (
            ("air_quality_risk", "Risk", "Air quality needs explicit verification for this micro-location."),
            ("crime_risk", "Risk", "Crime and safety burden need explicit verification for this quarter."),
            ("parking_pressure_risk", "Risk", "Parking pressure still needs clarification if no garage is included."),
            ("drinking_water_risk", "Risk", "Water source and groundwater burden still need verification."),
            ("cesspit_risk", "Risk", "Senkgrube or septic burden still needs verification."),
            ("winter_access_risk", "Risk", "Winter driving access still needs verification."),
            ("flood_risk", "Risk", "Flood and runoff exposure still need verification."),
        ):
            if bool(facts.get(risk_key)):
                rows.append({"label": label, "value": risk_key.replace("_", " ").title(), "detail": detail})
        return rows[:6]

    def _candidate_objection_rows(candidate: dict[str, object], facts: dict[str, object]) -> list[dict[str, str]]:
        mismatch_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("mismatch_reasons") or []) if _clean_property_candidate_copy(item)]
        rows: list[dict[str, str]] = []
        feedback_summary = dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {}
        for reason in mismatch_reasons[:3]:
            rows.append({"title": "Mismatch", "detail": reason, "tag": "Risk"})
        for cluster in list(feedback_summary.get("clusters") or [])[:2]:
            if not isinstance(cluster, dict):
                continue
            rows.append(
                {
                    "title": str(cluster.get("theme") or "feedback").replace("_", " ").title(),
                    "detail": str(cluster.get("summary") or "No detail yet.").strip(),
                    "tag": str(cluster.get("severity") or "Risk").replace("_", " ").title(),
                }
            )
        if not str(candidate.get("tour_url") or "").strip():
            rows.append({"title": "360 gap", "detail": _tour_source_gap_detail(candidate), "tag": "Review"})
        for item in _missing_fact_items(facts)[:2]:
            if str(item.get("status") or "").strip().lower() == "filled":
                continue
            rows.append(
                {
                    "title": str(item.get("label") or item.get("field") or "Missing fact").strip(),
                    "detail": str(item.get("evidence") or item.get("display_value") or "Still under research.").strip(),
                    "tag": "Research",
                }
            )
        for risk_key, title, detail in (
            ("air_quality_risk", "Air quality", "Location-risk research should verify pollution burden and recurring exposure."),
            ("crime_risk", "Crime burden", "Quarter-level safety pattern still needs verification."),
            ("parking_pressure_risk", "Parking pressure", "Street-parking burden still needs verification where no garage is included."),
            ("drinking_water_risk", "Water quality", "Drinking-water source and groundwater burden still need verification."),
            ("cesspit_risk", "Senkgrube or septic", "Recurring cost, smell, or maintenance burden still need verification."),
            ("winter_access_risk", "Winter access", "Snow, slope, and seasonal driveability still need verification."),
            ("flood_risk", "Flood exposure", "Historic flooding and runoff exposure still need verification."),
        ):
            if bool(facts.get(risk_key)):
                rows.append({"title": title, "detail": detail, "tag": "Risk"})
        for note in list(facts.get("austria_preference_notes") or [])[:2]:
            detail = str(note or "").strip()
            if detail:
                rows.append({"title": "Austria fit rule", "detail": detail.capitalize(), "tag": "Eligibility"})
        if not rows:
            rows.append({"title": "No recorded objection yet", "detail": "This candidate has no explicit blocker captured yet.", "tag": "Clear"})
        return rows[:4]

    def _candidate_timeline_rows(candidate: dict[str, object], facts: dict[str, object]) -> list[dict[str, str]]:
        rows = [
            {
                "title": "Found by provider",
                "detail": str(candidate.get("source_label") or "Property provider").strip() or "Property provider",
                "tag": "Found",
            },
            {
                "title": "Ranked",
                "detail": _clean_property_candidate_copy(candidate.get("fit_summary") or candidate.get("recommendation") or "Candidate ranked for review."),
                "tag": "Ranked",
            },
            {
                "title": "360 state",
                "detail": str(candidate.get("tour_url") or _tour_status_line(candidate)).strip(),
                "tag": "360",
            },
        ]
        pending_missing = [
            str(item.get("label") or item.get("field") or "Missing fact").strip()
            for item in _missing_fact_items(facts)
            if str(item.get("status") or "").strip().lower() != "filled"
        ]
        if pending_missing:
            rows.append(
                {
                    "title": "Decision checks queued",
                    "detail": ", ".join(pending_missing[:3]),
                    "tag": "Research",
                }
            )
        if str(candidate.get("packet_url") or "").strip():
            rows.append(
                {
                    "title": "Packet ready",
                    "detail": "Review packet is ready for household or advisor follow-up.",
                    "tag": "Packet",
                }
            )
        feedback_summary = dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {}
        household = dict(feedback_summary.get("household_review") or {}) if isinstance(feedback_summary.get("household_review"), dict) else {}
        if int(feedback_summary.get("household_alignment_score") or 0) > 0:
            rows.append(
                {
                    "title": "Household alignment",
                    "detail": f"{int(feedback_summary.get('household_alignment_score') or 0)}/100 · {str(household.get('alignment_label') or feedback_summary.get('family_alignment') or 'waiting').replace('_', ' ')}",
                    "tag": "Household",
                }
            )
        return rows[:5]

    def _candidate_household_rows(candidate: dict[str, object]) -> list[dict[str, str]]:
        feedback_summary = dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {}
        household = dict(feedback_summary.get("household_review") or {}) if isinstance(feedback_summary.get("household_review"), dict) else {}
        rows = [
            {
                "title": str(row.get("stakeholder_label") or "Stakeholder").strip(),
                "detail": str(row.get("reason") or "No detail yet.").strip(),
                "tag": str(row.get("decision") or "maybe").replace("_", " ").title(),
            }
            for row in list(household.get("stakeholders") or [])[:4]
            if isinstance(row, dict)
        ]
        if not rows:
            rows.append({"title": "No household votes yet", "detail": "Shared reactions will appear here after packet or workspace decisions are recorded.", "tag": "Waiting"})
        return rows

    def _candidate_risk_signal_rows(candidate: dict[str, object]) -> list[dict[str, str]]:
        feedback_summary = dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {}
        rows = [
            {
                "title": str(row.get("theme") or "risk").replace("_", " ").title(),
                "detail": f"{str(row.get('summary') or 'No summary yet.').strip()} | privacy {str(row.get('privacy_state') or 'suppressed')} | confidence {str(row.get('confidence') or 'low')}",
                "tag": str(row.get("reason_key") or "signal").replace("_", " ").title(),
            }
            for row in list(feedback_summary.get("risk_signal_candidates") or [])[:3]
            if isinstance(row, dict)
        ]
        if not rows:
            rows.append({"title": "No published risk signal yet", "detail": "Signals stay suppressed until the privacy threshold is met.", "tag": "Suppressed"})
        return rows

    def _candidate_followup_rows(candidate: dict[str, object]) -> list[dict[str, str]]:
        feedback_rows = [dict(row) for row in list(candidate.get("feedback_rows") or []) if isinstance(row, dict)]
        rows = [
            {
                "feedback_id": str(row.get("feedback_id") or "").strip(),
                "title": str(row.get("text") or row.get("category") or "Follow-up").strip(),
                "detail": str(row.get("followup_note") or row.get("stakeholder_label") or row.get("stakeholder_id") or "").strip(),
                "tag": str(row.get("followup_status") or "suggested").replace("_", " ").title(),
            }
            for row in feedback_rows
            if str(row.get("category") or "").strip() == "question"
        ]
        if not rows:
            rows.append({"feedback_id": "", "title": "No tracked question yet", "detail": "Use Clippy or Ask agent next to start a tracked follow-up.", "tag": "Waiting"})
        return rows[:4]

    def _candidate_recent_change_rows(candidate: dict[str, object]) -> list[dict[str, str]]:
        timeline_rows = [dict(row) for row in list(candidate.get("timeline_rows") or []) if isinstance(row, dict)]
        rows = [
            {
                "title": str(row.get("title") or "Update").strip(),
                "detail": str(row.get("detail") or "Property state updated.").strip(),
                "tag": str(row.get("tag") or "Changed").strip(),
            }
            for row in timeline_rows[:3]
            if str(row.get("detail") or row.get("title") or "").strip()
        ]
        if not rows:
            rows.append({"title": "No new deltas yet", "detail": "The visible timeline will summarize what changed after the first decision, packet event, or follow-up update.", "tag": "Waiting"})
        return rows

    def _tour_payload(candidate: dict[str, object]) -> dict[str, str]:
        tour_url = str(candidate.get("tour_url") or "").strip()
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_minutes = str(candidate.get("tour_eta_minutes") or "").strip()
        if tour_url:
            embed_url = "" if "myexternalbrain.com" in tour_url.lower() else tour_url
            return {"status": "ready", "label": "360 ready", "url": tour_url, "embed_url": embed_url, "eta_label": ""}
        if status in {"queued", "pending"}:
            return {"status": "queued", "label": "360 queued", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '10'} min"}
        if status in {"processing", "running", "in_progress", "started"}:
            return {"status": "processing", "label": "360 rendering", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '5'} min"}
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return {"status": "blocked", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}
        return {"status": "missing", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}

    def _fit_score_value(candidate: dict[str, object], facts: dict[str, object]) -> int:
        assessment = dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {}
        assessment = assessment or (dict(facts.get("personal_fit_assessment") or {}) if isinstance(facts.get("personal_fit_assessment"), dict) else {})
        for raw_value in (
            candidate.get("fit_score"),
            candidate.get("assessment_fit_score"),
            assessment.get("adjusted_fit_score"),
            assessment.get("fit_score"),
        ):
            if raw_value in (None, ""):
                continue
            try:
                return max(0, min(100, int(round(float(raw_value)))))
            except Exception:
                continue
        return 0

    def _money_display(value: object) -> str:
        if value in (None, "", []):
            return ""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            lowered = text.lower()
            if "eur" in lowered or "€" in text:
                return text
            try:
                value = float(text.replace(",", "."))
            except Exception:
                return text
        if isinstance(value, (int, float)):
            amount = float(value)
            if abs(amount) >= 1000:
                formatted = f"{amount:,.0f}".replace(",", ",")
                return f"EUR {formatted}"
            if amount:
                return f"EUR {amount:.0f}"
        return ""

    def _candidate_costs_line(facts: dict[str, object], *, listing_mode: str, price_line: str) -> str:
        normalized_mode = str(listing_mode or "").strip().lower()
        for key in (
            "operating_costs_display",
            "operating_costs_monthly_display",
            "service_charges_display",
            "additional_costs_display",
            "side_costs_display",
            "monthly_costs_display",
        ):
            value = str(facts.get(key) or "").strip()
            if value:
                return value
        for key in (
            "operating_costs_monthly",
            "operating_costs",
            "service_charges_eur",
            "additional_costs_eur",
            "side_costs_eur",
            "betriebskosten_eur",
        ):
            value = _money_display(facts.get(key))
            if value:
                return f"Costs {value}/mo" if normalized_mode == "buy" else f"Costs {value}"
        if normalized_mode == "rent":
            warm_rent = _money_display(facts.get("warm_rent_eur") or facts.get("warm_rent"))
            cold_rent = _money_display(facts.get("cold_rent_eur") or facts.get("cold_rent"))
            total_rent = _money_display(facts.get("total_rent_eur") or facts.get("rent_eur"))
            if warm_rent and cold_rent and warm_rent != cold_rent:
                return f"Cold {cold_rent} · Warm {warm_rent}"
            if total_rent and total_rent != price_line:
                return f"Monthly total {total_rent}"
            if warm_rent and warm_rent != price_line:
                return f"Warm rent {warm_rent}"
            if cold_rent and cold_rent != price_line:
                return f"Cold rent {cold_rent}"
            return "Costs open"
        price_per_sqm = _money_per_sqm_line(facts)
        if price_per_sqm:
            return price_per_sqm
        return "Costs open"

    for candidate in shortlist_candidates:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        price_line = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price_eur")
            or ""
        ).strip() or "n/a"
        fit_score = _fit_score_value(candidate, facts)
        layout_parts = [
            _rooms_layout_part(facts),
            f"{facts.get('area_m2') or facts.get('area_sqm')} m2" if (facts.get("area_m2") or facts.get("area_sqm")) else "",
        ]
        layout_verified = bool(
            facts.get("has_floorplan")
            or facts.get("floorplan_count")
            or facts.get("floorplans_count")
            or facts.get("floorplan_urls_json")
            or facts.get("floorplan_urls")
        )
        packet_url = str(candidate.get("packet_url") or candidate.get("review_url") or "").strip()
        packet_label = "Review packet" if packet_url else "Pending"
        map_url = str(candidate.get("map_url") or "").strip() or _property_candidate_maps_url(candidate)
        tour_status_line = _tour_status_line(candidate)
        ooda_detail = _distance_line(candidate)
        candidate_ref = str(packet_url or "").split("/app/research/", 1)[-1].split("?", 1)[0] if "/app/research/" in packet_url else _property_candidate_ref(candidate)
        tour_payload = _tour_payload(candidate)
        ooda_rows = _candidate_ooda_rows(candidate, facts)
        risk_payload = _risk_summary(candidate, facts)
        match_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("match_reasons") or []) if _clean_property_candidate_copy(item)]
        mismatch_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("mismatch_reasons") or []) if _clean_property_candidate_copy(item)]
        provider_quality = dict(candidate.get("provider_quality") or {}) if isinstance(candidate.get("provider_quality"), dict) else {}
        detail_sections = _candidate_detail_sections(facts)
        provider_quality_line = " · ".join(
            part
            for part in (
                f"Floorplans {provider_quality.get('floorplan_reliability')}" if str(provider_quality.get("floorplan_reliability") or "").strip() else "",
                f"Filters {provider_quality.get('filter_pushdown_strength')}" if str(provider_quality.get("filter_pushdown_strength") or "").strip() else "",
                f"Verified {provider_quality.get('last_verified')}" if str(provider_quality.get("last_verified") or "").strip() else "",
            )
            if str(part or "").strip()
        )
        investment_payload = {
            "enabled": str(property_preferences.get("listing_mode") or "").strip().lower() == "buy",
            "price_per_sqm": _money_per_sqm_line(facts),
            "headline": "Open packet for full underwriting" if str(property_preferences.get("listing_mode") or "").strip().lower() == "buy" else "",
        }
        orientation_preview = _property_candidate_orientation_preview(candidate)
        workbench_results.append(
            {
                "candidate_ref": candidate_ref,
                "rank": len(workbench_results) + 1,
                "title": str(candidate.get("title") or "Candidate").strip() or "Candidate",
                "preview_image_url": str(candidate.get("preview_image_url") or _property_candidate_preview_image(candidate) or "").strip(),
                "source_label": str(candidate.get("source_label") or "").strip(),
                "location_label": str(facts.get("postal_name") or facts.get("city") or facts.get("address") or "").strip(),
                "price_display": price_line,
                "costs_display": _candidate_costs_line(
                    facts,
                    listing_mode=str(property_preferences.get("listing_mode") or ""),
                    price_line=price_line,
                ),
                "price_per_sqm_display": investment_payload["price_per_sqm"],
                "layout_display": " | ".join(part for part in layout_parts if part) or "n/a",
                "layout_verification_label": "verified" if layout_verified else "needs check",
                "fit_score": fit_score,
                "fit_label": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(),
                "fit_summary": _clean_property_candidate_copy(candidate.get("fit_summary") or ""),
                "provider_quality": provider_quality,
                "provider_quality_line": provider_quality_line,
                "tour": tour_payload,
                "orientation_preview": orientation_preview,
                "ooda": {
                    "summary": ooda_detail or (match_reasons[0] if match_reasons else "Open the packet to inspect the decision read."),
                    "rows": ooda_rows,
                },
                "risk": risk_payload,
                "investment": investment_payload,
                "match_reasons": match_reasons,
                "mismatch_reasons": mismatch_reasons,
                "packet_url": packet_url,
                "review_url": str(candidate.get("review_url") or "").strip(),
                "property_url": str(candidate.get("property_url") or "").strip(),
                "map_url": map_url,
                "source_url": str(candidate.get("property_url") or "").strip(),
                "property_facts": facts,
                "assessment": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                "objection_rows": _candidate_objection_rows(candidate, facts),
                "timeline_rows": _candidate_timeline_rows(candidate, facts),
                "household_rows": _candidate_household_rows(candidate),
                "risk_signal_rows": _candidate_risk_signal_rows(candidate),
                "followup_rows": _candidate_followup_rows(candidate),
                "recent_change_rows": _candidate_recent_change_rows(candidate),
                "official_evidence_rows": [
                    {
                        "title": str(row.get("label") or row.get("risk_key") or "Official evidence").strip(),
                        "detail": " | ".join(
                            part
                            for part in (
                                str(row.get("source_label") or row.get("provider") or "").strip(),
                                str(row.get("summary") or "").strip(),
                                f"Next: {str(row.get('required_next_step') or '').strip()}" if str(row.get("required_next_step") or "").strip() else "",
                            )
                            if part
                        ) or "Official source linked for this risk lane.",
                        "tag": " · ".join(
                            part
                            for part in (
                                str(row.get("availability") or "").replace("_", " ").title(),
                                str(row.get("verification_state") or "").replace("_", " ").title(),
                                str(row.get("confidence") or "").replace("_", " ").title(),
                            )
                            if part
                        ),
                    }
                    for row in list(dict(facts.get("official_risk_evidence") or {}).get("sources") or [])[:4]
                    if isinstance(row, dict)
                ],
                "official_posture_rows": _official_risk_posture_rows(
                    dict(facts.get("official_risk_evidence") or {})
                    if isinstance(facts.get("official_risk_evidence"), dict)
                    else {}
                ),
                "object_rows": detail_sections["object_rows"],
                "cost_rows": detail_sections["cost_rows"],
                "feature_values": detail_sections["feature_values"],
                "description_text": detail_sections["description_text"],
                "location_text": detail_sections["location_text"],
                "energy_rows": detail_sections["energy_rows"],
                "household_alignment_score": int(dict(candidate.get("feedback_summary") or {}).get("household_alignment_score") or 0) if isinstance(candidate.get("feedback_summary"), dict) else 0,
                "household_alignment_label": str(dict(candidate.get("feedback_summary") or {}).get("family_alignment") or "waiting") if isinstance(candidate.get("feedback_summary"), dict) else "waiting",
            }
        )
        results_table_rows.append(
            {
                "cells": [
                    {"title": "Open 360" if str(candidate.get("tour_url") or "").strip() else tour_status_line, "detail": tour_status_line if str(candidate.get("tour_url") or "").strip() else "", "href": str(candidate.get("tour_url") or "").strip()},
                    {"title": f"#{len(results_table_rows) + 1} {str(candidate.get('title') or 'Candidate').strip() or 'Candidate'}", "detail": str(candidate.get("source_label") or "").strip()},
                    {"title": str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(), "detail": str(candidate.get("fit_summary") or "").strip()},
                    {"title": "Open Map" if map_url else "Map pending", "detail": "", "href": map_url},
                    {"title": price_line, "detail": ""},
                    {"title": " | ".join(part for part in layout_parts if part) or "n/a", "detail": ""},
                    {"title": ooda_detail or "Packet explains the neighbourhood fit.", "detail": "", "href": packet_url},
                    {"title": packet_label, "detail": packet_url or str(candidate.get("property_url") or "").strip(), "href": packet_url},
                ],
                "packet_url": packet_url,
                "tour_url": str(candidate.get("tour_url") or "").strip(),
                "map_url": map_url,
                "source_url": str(candidate.get("property_url") or "").strip(),
            }
        )

    hero_actions = {
        "properties": [
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist", "tone": "primary"},
            {"href": f"/app/research{run_suffix}", "label": "Open research"},
            {"href": f"/app/billing{run_suffix}", "label": "Plans"},
        ],
        "shortlist": [
            {"href": f"/app/research{run_suffix}", "label": "Open research", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            {"href": f"/app/alerts{run_suffix}", "label": "Alerts"},
        ],
        "research": [
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            {"href": f"/app/alerts{run_suffix}", "label": "Alerts"},
        ],
        "profile": [
            {"href": f"/app/properties{run_suffix}", "label": "Refine search", "tone": "primary"},
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
            {"href": f"/app/settings{run_suffix}", "label": "Settings"},
        ],
        "alerts": [
            {"href": f"/app/properties{run_suffix}", "label": "Open search desk", "tone": "primary"},
            {"href": f"/app/agents{run_suffix}", "label": "Search agents"},
            {"href": f"/app/settings{run_suffix}", "label": "Notifications"},
        ],
        "agents": [
            {"href": f"/app/properties{run_suffix}", "label": "Create or edit", "tone": "primary"},
            {"href": f"/app/alerts{run_suffix}", "label": "Recent alerts"},
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
        ],
        "billing": [
            {"href": "/pricing", "label": "Open pricing", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Back to search"},
            {"href": "/security", "label": "Security"},
        ],
        "settings": [
            {"href": f"/app/properties{run_suffix}", "label": "Back to search", "tone": "primary"},
            {"href": "/security", "label": "Open security"},
            {"href": "/pricing", "label": "Open pricing"},
        ],
    }
    hero_highlights = {
        "properties": [
            {
                "label": "Market",
                "value": str(property_state.get("country_label") or "Austria"),
                "detail": str(search_posture_items[0].get("detail") or "").strip() if search_posture_items else "",
                "href": f"/app/properties{run_suffix}",
            },
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "Choose the target districts.", "href": "/app/account#profile"},
            {"label": "Priorities", "value": str(len(selected_keywords) or 0), "detail": ", ".join(selected_keywords[:3]) or "Record what should drive the ranking.", "href": "/app/account#profile"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "The selected portals for the next sweep.", "href": f"/app/search{run_suffix}"},
        ],
        "shortlist": [
            {"label": "Candidates", "value": str(len(shortlist_candidates)), "detail": "Ranked properties worth direct review now.", "href": f"/app/shortlist{run_suffix}"},
            {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal packets ready before the raw portal listing.", "href": f"/app/research{run_suffix}"},
            {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted or embedded tours already available.", "href": f"/app/research{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest run status.", "href": f"/app/properties{run_suffix}"},
        ],
        "research": [
            {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal dossiers ready for inspection.", "href": f"/app/research{run_suffix}"},
            {"label": "Tours", "value": str(tour_ready_total), "detail": "Candidates already backed by a 360 or hosted tour.", "href": f"/app/research{run_suffix}"},
            {"label": "Signals", "value": str(int(run_summary.get("listing_total") or 0)), "detail": "Raw listings considered in the latest run.", "href": f"/app/properties{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest research pass.", "href": f"/app/properties{run_suffix}"},
        ],
        "profile": [
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "No areas saved yet.", "href": f"/app/profile{run_suffix}"},
            {"label": "Priorities", "value": str(len(selected_keywords) or 0), "detail": ", ".join(selected_keywords[:3]) or "No ranking preferences saved yet.", "href": f"/app/profile{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "Current active provider set.", "href": f"/app/properties{run_suffix}"},
            {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": f"/app/billing{run_suffix}"},
        ],
        "alerts": [
            {"label": "Delivered", "value": str(len(recent_matches_card.get("items") or [])), "detail": "Hosted pages or packets already sent.", "href": f"/app/alerts{run_suffix}"},
            {"label": "Run events", "value": str(len(run_events[-4:])), "detail": "Recent run updates visible to the user.", "href": f"/app/alerts{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "Portals currently feeding the alert lane.", "href": f"/app/properties{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest saved-search sweep.", "href": f"/app/properties{run_suffix}"},
        ],
        "agents": [
            {"label": "Saved agents", "value": str(len(property_search_agents)), "detail": "Reusable searches available for editing and rerunning.", "href": f"/app/agents{run_suffix}"},
            {"label": "Active", "value": str(sum(1 for agent in property_search_agents if agent.get("enabled"))), "detail": "Agents allowed to send matching updates.", "href": f"/app/agents{run_suffix}"},
            {"label": "Notification window", "value": str(property_search_agent.get("notification_label") or "Set per agent"), "detail": "Each agent ranks down to the allowed message budget.", "href": f"/app/agents{run_suffix}"},
            {"label": "Next run", "value": str(property_search_agent.get("next_run_label") or "waiting"), "detail": str(property_search_agent.get("area_label") or "Saved search area"), "href": f"/app/agents{run_suffix}"},
        ],
        "billing": [
            {"label": "Plan", "value": current_plan_label, "detail": "Current commercial posture.", "href": f"/app/billing{run_suffix}"},
            {"label": "Depth", "value": str(commercial.get("research_depth") or "deep").title(), "detail": "How deep the research lane runs.", "href": f"/app/billing{run_suffix}"},
            {"label": "Providers", "value": str(commercial.get("max_platforms") or "Multi"), "detail": "Maximum provider breadth for this plan.", "href": f"/app/billing{run_suffix}"},
            {"label": "Per source", "value": str(commercial.get("max_results_per_source") or 2), "detail": "Maximum ranked results per provider.", "href": f"/app/billing{run_suffix}"},
        ],
        "settings": [
            {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": f"/app/settings{run_suffix}"},
            {"label": "Workspace", "value": str(workspace.get("name") or "PropertyQuarry"), "detail": str(workspace.get("timezone") or "Europe/Vienna"), "href": f"/app/settings{run_suffix}"},
            {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": f"/app/billing{run_suffix}"},
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": f"/app/profile{run_suffix}"},
        ],
    }
    preference_rows = [
        row_item(
            "Workspace",
            str(workspace.get("name") or "PropertyQuarry"),
            "Workspace",
        ),
        row_item(
            "Google sign-in",
            str(google.get("connected_account_email") or google.get("status") or "Not connected"),
            "Connection",
        ),
        row_item(
            "Timezone",
            str(workspace.get("timezone") or "Europe/Vienna"),
            "Preference",
        ),
        row_item(
            "Active plan",
            current_plan_label,
            "Plan",
        ),
    ]
    settings_connection_rows = [
        row_item(
            "Google sign-in",
            "Identity-only return access. PropertyQuarry should not widen this into office sync on the settings surface.",
            "Connection",
        ),
        row_item(
            "Notification delivery",
            "Good matches can leave through Telegram or email once the shortlist is credible enough to notify.",
            "Alerts",
        ),
        row_item(
            "Workspace posture",
            "Billing, saved defaults, and security should stay explicit and product-specific.",
            "Control",
        ),
    ]
    alerts_rows = list(recent_matches_card.get("items") or []) + [
        row_item(
            str(event.get("step") or "Run update").replace("_", " ").strip().title(),
            str(event.get("message") or "No further detail.").strip() or "No further detail.",
            str(event.get("status") or "Update").replace("_", " ").strip().title(),
        )
        for event in run_events[-4:]
        if isinstance(event, dict)
    ]
    if not alerts_rows:
        alerts_rows = [
            row_item(
                "No client-facing alert has been sent yet",
                "This lane will show the first hosted page, review packet, or run update once the shortlist is strong enough to notify.",
                "Quiet",
            )
        ]
    plan_catalog = [dict(plan) for plan in list(commercial.get("plan_catalog") or []) if isinstance(plan, dict)]
    current_plan_key = str(commercial.get("current_plan_key") or "free").strip().lower() or "free"
    current_plan_spec = next((plan for plan in plan_catalog if str(plan.get("plan_key") or "").strip().lower() == current_plan_key), {})
    current_platform_cap = int(current_plan_spec.get("max_platforms") or commercial.get("max_platforms") or 0)
    current_result_cap = int(current_plan_spec.get("max_results_per_source") or commercial.get("max_results_per_source") or 0)
    current_match_cap = int(current_plan_spec.get("max_match_score") or commercial.get("max_match_score") or 0)
    billing_rows = [
        row_item(
            "Current plan",
            f"{current_plan_label} | {str(commercial.get('research_depth') or 'deep')} research",
            "Plan",
        ),
        row_item(
            "Coverage",
            f"{commercial.get('max_platforms') or 'Multi'} sources | up to {commercial.get('max_results_per_source') or 2} results per source",
            "Limits",
        ),
        row_item(
            "Checkout",
            str(property_state.get("billing_checkout_provider_label") or "Unavailable"),
            "Provider",
        ),
    ]
    if commercial.get("active_until"):
        billing_rows.append(
            row_item(
                "Access window",
                str(commercial.get("active_until") or "").strip(),
                "Status",
            )
        )
    billing_upgrade_rows = []
    for plan in plan_catalog:
        plan_key = str(plan.get("plan_key") or "").strip().lower()
        if not plan_key or plan_key == current_plan_key:
            continue
        platform_cap = int(plan.get("max_platforms") or 0)
        result_cap = int(plan.get("max_results_per_source") or 0)
        match_cap = int(plan.get("max_match_score") or 0)
        delta_parts = [
            f"{platform_cap} platforms" if platform_cap else "",
            f"{result_cap} results per source" if result_cap else "",
            f"{match_cap}/100 match ceiling" if match_cap else "",
            f"{str(plan.get('research_depth') or '').strip()} research".strip() if str(plan.get("research_depth") or "").strip() else "",
        ]
        improvement_parts = []
        if platform_cap > current_platform_cap:
            improvement_parts.append(f"+{platform_cap - current_platform_cap} platform breadth")
        elif platform_cap < current_platform_cap:
            improvement_parts.append(f"{current_platform_cap - platform_cap} fewer platforms, but a tighter working lane")
        if result_cap > current_result_cap:
            improvement_parts.append(f"+{result_cap - current_result_cap} more results per source")
        if match_cap > current_match_cap:
            improvement_parts.append(f"+{match_cap - current_match_cap} points of shortlist ceiling")
        billing_upgrade_rows.append(
            row_item(
                str(plan.get("display_name") or "Plan"),
                " | ".join(part for part in delta_parts if part) + (
                    f" | {'; '.join(improvement_parts)}" if improvement_parts else ""
                ),
                str(plan.get("checkout_label") or "Plan"),
            )
        )
    if not billing_upgrade_rows:
        billing_upgrade_rows = [
            row_item(
                "No live upgrade catalog available",
                "Checkout metadata is not loaded yet. The current plan still governs search breadth, shortlist density, and research depth.",
                "Catalog",
            )
        ]
    billing_decision_rows = [
        row_item(
            "Stay on the current tier",
            "Use the current plan until the real bottleneck is clear: source breadth, shortlist density, or deeper research.",
            "Decision",
        ),
        row_item(
            "Move tiers for a concrete reason",
            "Upgrade when the current caps block a real search run, not because the feature grid sounds bigger.",
            "Decision",
        ),
    ]
    if current_plan_key == "free":
        billing_decision_rows.append(
            row_item(
                "First paid move",
                "Plus buys a denser working shortlist; Agent is the lane for full-breadth, full-depth search.",
                "Next tier",
            )
        )
    elif current_plan_key == "plus":
        billing_decision_rows.append(
            row_item(
                "When to jump to Agent",
                "Move when the search needs both full provider coverage and the heaviest research posture at the same time.",
                "Next tier",
            )
        )
    else:
        billing_decision_rows.append(
            row_item(
                "Agent posture",
                "The focus here is not another upgrade. It is making sure the heavier research lane is actually being used productively.",
                "Current tier",
            )
        )
    research_rows = []
    for candidate in shortlist_candidates[:6]:
        title = str(candidate.get("title") or "Research packet").strip() or "Research packet"
        reasons = list(candidate.get("match_reasons") or [])[:2]
        mismatches = list(candidate.get("mismatch_reasons") or [])[:2]
        detail_parts = []
        if candidate.get("fit_summary"):
            detail_parts.append(str(candidate.get("fit_summary") or "").strip())
        if reasons:
            detail_parts.append("; ".join(str(reason).strip() for reason in reasons if str(reason).strip()))
        if mismatches:
            detail_parts.append("Risks: " + "; ".join(str(reason).strip() for reason in mismatches if str(reason).strip()))
        research_rows.append(
            {
                "title": title,
                "detail": " | ".join(part for part in detail_parts if part) or "Open the packet to inspect the fit and missing evidence.",
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Packet").strip() or "Packet",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open packet",
                "secondary_action_href": str(candidate.get("review_url") or candidate.get("tour_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("review_url") or candidate.get("tour_url")) else "",
                "secondary_action_label": "Review details" if candidate.get("review_url") else ("Open 360" if candidate.get("tour_url") else ""),
            }
        )
    if not research_rows:
        research_rows = list(recent_matches_card.get("items") or []) or [
            row_item(
                "Research packets have not been opened yet",
                "As soon as a run finishes with credible matches, the strongest candidates will be promoted into packets from this desk.",
                "First packet",
            )
        ]
    saved_search_rows = [
        {
            "title": "Current saved search",
            "detail": " | ".join(
                part for part in (
                    str(property_state.get("country_label") or "").strip(),
                    f"{len(selected_locations)} target area(s)" if selected_locations else "",
                    f"{len(selected_platforms)} provider(s)" if selected_platforms else "",
                ) if part
            ) or "No saved search brief yet.",
            "tag": "Saved",
            "action_href": f"/app/properties{run_suffix}",
            "action_method": "get",
            "action_label": "Refine brief",
        },
        {
            "title": "Latest run posture",
            "detail": run_message or "Open the search desk to launch or monitor the next sweep.",
            "tag": run_status_label,
            "action_href": f"/app/properties{run_suffix}",
            "action_method": "get",
            "action_label": "Open search desk",
        },
        {
            "title": "Delivery path",
            "detail": "Telegram and email stay secondary until the shortlist is credible enough to notify.",
            "tag": "Alerts",
            "action_href": f"/app/settings{run_suffix}",
            "action_method": "get",
            "action_label": "Review settings",
        },
    ]
    agent_management_rows = []
    for agent in property_search_agents:
        if not isinstance(agent, dict):
            continue
        agent_id = urllib.parse.quote(str(agent.get("agent_id") or "current").strip() or "current", safe="")
        edit_href = f"/app/properties?load_agent={agent_id}"
        open_href = f"/app/agents?agent_id={agent_id}"
        if run_id:
            edit_href = f"{edit_href}&run_id={urllib.parse.quote(run_id, safe='')}"
            open_href = f"{open_href}&run_id={urllib.parse.quote(run_id, safe='')}"
        label = str(agent.get("name") or agent.get("area_label") or "Saved search").strip() or "Saved search"
        status_label = "Active" if bool(agent.get("enabled")) else "Paused"
        detail_parts = [
            str(agent.get("scope_label") or "").strip(),
            str(agent.get("notification_label") or "").strip(),
            str(agent.get("run_label") or "").strip(),
        ]
        agent_management_rows.append(
            {
                "title": label,
                "detail": " | ".join(part for part in detail_parts if part) or "Saved search settings can be edited from the search desk.",
                "tag": status_label,
                "action_href": open_href,
                "action_method": "get",
                "action_label": "Open",
                "secondary_action_href": edit_href,
                "secondary_action_method": "get",
                "secondary_action_label": "Edit",
            }
        )
    if not agent_management_rows:
        agent_management_rows = [
            row_item(
                "No saved search agent yet",
                "Create one from the search desk, then return here to edit, pause, or review its notification budget.",
                "First agent",
            )
        ]

    sections: dict[str, dict[str, object]] = {
        "properties": {
            "title": "Results" if run_status_value in {"processed", "completed"} and results_table_rows else ("Live search" if run_in_progress else "Search Brief"),
            "summary": (
                "Review the final ranked result table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "The search brief is locked while the run is active. Keep the visible progress and source-by-source status in front of the user."
                    if run_in_progress
                    else str(base.get("summary") or "Define the search brief, launch the run, and keep the crawl visible.")
                )
            ),
            "hero_kicker": "Results" if run_status_value in {"processed", "completed"} and results_table_rows else ("Live search" if run_in_progress else "Search brief"),
            "hero_title": (
                "Review the finished shortlist in one table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else ("Keep the run visible until the shortlist is ready." if run_in_progress else "Shape the next market sweep before the crawlers fan out.")
            ),
            "hero_summary": (
                "Once the run is done, keep the result surface simple: one ranked table, packet links, and clear 360 status."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "Hide the search form while the run is active. Show only progress, source events, and the first usable signals until the final ranked table is ready."
                    if run_in_progress
                    else "Pick the market, region, buying posture, shortlist priorities, and provider set once so the run starts from an explicit brief instead of a stack of browser tabs."
                )
            ),
            "hero_actions": [{"href": f"/app/search{run_suffix}", "label": "Open search"}, {"href": f"/app/properties{run_suffix}", "label": "Back to Home"}] if run_in_progress else (hero_actions["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"href": f"/app/search{run_suffix}", "label": "Refine search", "tone": "primary"},
                {"href": f"/app/properties{run_suffix}", "label": "Back to Home"},
                {"href": f"/app/agents{run_suffix}", "label": "Search agents"},
            ]),
            "hero_highlights": [
                {"label": "Run state", "value": run_status_label, "detail": run_message or "The current live run status."},
                {"label": "Sources", "value": str(int(run_summary.get("sources_total") or 0)), "detail": "Places being checked for this search."},
                {"label": "Listings", "value": str(int(run_summary.get("listing_total") or 0)), "detail": "Listings recovered so far."},
            ] if run_in_progress else (hero_highlights["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"label": "Results", "value": str(len(results_table_rows)), "detail": "Final ranked candidates in this run."},
                {"label": "Packets", "value": str(packet_ready_total), "detail": "Internal review packets ready now."},
                {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted tours available right now."},
            ]),
            "primary_cards": [] if (run_status_value in {"processed", "completed"} and results_table_rows) or run_in_progress else [search_posture_card, market_coverage_card],
            "secondary_cards": [] if run_status_value in {"processed", "completed"} and results_table_rows else ([run_card] if run_in_progress else [run_card, recent_matches_card]),
            "console_form": property_form,
            "show_brief_form": not ((run_status_value in {"processed", "completed"} and results_table_rows) or run_in_progress),
            "show_run_panel": run_in_progress,
            "show_shortlist_cards": False,
            "show_results_table": run_status_value in {"processed", "completed"} and bool(results_table_rows),
            "results_table_headers": ["360", "Candidate", "Fit", "Map", "Price", "Layout", "Quick read", "Review"],
            "results_table_rows": results_table_rows,
        },
        "shortlist": {
            "title": "Shortlist",
            "summary": "Keep the strongest candidates in one ranked lane and record preference feedback directly on the cards.",
            "hero_kicker": "Shortlist",
            "hero_title": "Review the properties that deserve attention now.",
            "hero_summary": "Start with fit, risks, packet link, 360 link, and one-step feedback. Crawl counters stay secondary.",
            "hero_actions": hero_actions["shortlist"],
            "hero_highlights": hero_highlights["shortlist"],
            "primary_cards": [
                {
                    "eyebrow": "At a glance",
                    "title": "Compare the top shortlist before opening deeper packets",
                    "body": "The first scan should show which candidate looks strongest right now without forcing the user to open five pages.",
                    "items": compare_rows or [row_item("No ranked shortlist yet", "Complete the next run and this panel becomes the first comparison desk for the leading candidates.", "First run")],
                },
                shortlist_card,
            ],
            "secondary_cards": [run_card, market_coverage_card],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": True,
        },
        "research": {
            "title": "Research",
            "summary": "Turn high-fit candidates into property dossiers with evidence, packets, and hosted follow-ups.",
            "hero_kicker": "Research packets",
            "hero_title": "Inspect the evidence before you open the raw listing.",
            "hero_summary": "This lane should feel like a property dossier desk: fit reasons, decision checks, packet links, and hosted tours where they exist.",
            "hero_actions": hero_actions["research"],
            "hero_highlights": hero_highlights["research"],
            "primary_cards": [
                {
                    "eyebrow": "Research packets",
                    "title": "Open the strongest packets first",
                    "body": "Hosted packet links and 360 tours stay primary. Raw portal links remain secondary.",
                    "items": research_rows,
                }
            ],
            "secondary_cards": [recent_matches_card, run_card],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "profile": {
            "title": "Profile Learning",
            "summary": "Show what the ranking learned, what should be suppressed next time, and which rules remain explicit.",
            "hero_kicker": "Profile learning",
            "hero_title": "Make the learning loop visible and editable.",
            "hero_summary": "Likes, dislikes, and hard rules must survive beyond one run. This lane is where the ranking becomes personal instead of repeating the same weak matches.",
            "hero_actions": hero_actions["profile"],
            "hero_highlights": hero_highlights["profile"],
            "primary_cards": [learning_card],
            "secondary_cards": [
                {
                    "eyebrow": "Saved posture",
                    "title": "Current profile state",
                    "body": "The saved search posture should be easy to inspect without reopening the full brief.",
                    "items": list(search_posture_card.get("items") or []),
                },
                {
                    "eyebrow": "Account",
                    "title": "Who this profile belongs to",
                    "body": "Identity and connection state stay narrow and explicit on PropertyQuarry.",
                    "items": preference_rows,
                },
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "alerts": {
            "title": "Alerts",
            "summary": "Track what has already been delivered and which run events are preparing the next outbound packet.",
            "hero_kicker": "Alerts",
            "hero_title": "See what has been sent and what is about to leave.",
            "hero_summary": "Alerts are product output, not hidden queue state. Keep hosted matches, review packets, and run updates visible in one lane.",
            "hero_actions": hero_actions["alerts"],
            "hero_highlights": hero_highlights["alerts"],
            "primary_cards": [
                {
                    "eyebrow": "Client alerts",
                    "title": "Recent outbound property follow-ups",
                    "body": "Hosted pages, review briefs, and run updates that mattered enough to notify the client.",
                    "items": alerts_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Saved search",
                    "title": "The alert lane should still expose the search brief driving it",
                    "body": "Recurring alerts are only useful when the user can still see and revise the search posture behind them.",
                    "items": saved_search_rows,
                },
                run_card,
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "agents": {
            "title": "Search agents",
            "summary": "Manage reusable searches, notification budgets, and the saved filters behind each recurring run.",
            "hero_kicker": "Search agents",
            "hero_title": str((selected_agent or {}).get("name") or "Edit the searches that keep watching the market."),
            "hero_summary": (
                f"{str((selected_agent or {}).get('scope_label') or '').strip()} | {str((selected_agent or {}).get('delivery_label') or '').strip()} | {str((selected_agent_latest_run or {}).get('held_back_total') or 0)} filtered on the latest finished run."
                if selected_agent
                else "Each agent owns one saved brief, its allowed message volume, and whether it is active. When more listings fit than the budget allows, PropertyQuarry ranks them and sends only the strongest matches."
            ),
            "hero_actions": hero_actions["agents"],
            "hero_highlights": hero_highlights["agents"],
            "primary_cards": [
                {
                    "eyebrow": "Selected agent",
                    "title": str((selected_agent or {}).get("name") or "Open a saved agent"),
                    "body": (
                        "This market watch owns one saved brief, a notification budget, and the shortlist that leaves first."
                        if selected_agent
                        else "Choose a saved agent to inspect its watch, recent runs, and edit path."
                    ),
                    "items": (
                        [
                            {
                                "title": "Watching",
                                "detail": str((selected_agent or {}).get("scope_label") or "No scope saved"),
                                "tag": str((selected_agent or {}).get("status_label") or "Idle"),
                                "action_href": selected_agent_open_href or f"/app/agents{run_suffix}",
                                "action_method": "get",
                                "action_label": "Refresh",
                                "secondary_action_href": selected_agent_edit_href or f"/app/properties{run_suffix}",
                                "secondary_action_method": "get",
                                "secondary_action_label": "Edit",
                            },
                            row_item("Notification budget", str((selected_agent or {}).get("delivery_label") or "Set a daily or weekly cap."), str((selected_agent or {}).get("notification_label") or "Budget")),
                            row_item("Run cadence", str((selected_agent or {}).get("run_label") or "Waiting for the first scheduler run."), "Timing"),
                            row_item(
                                "Latest finished run",
                                (
                                    f"Ranked {str((selected_agent_latest_run or {}).get('ranked_total') or 0)} | Sent {str((selected_agent_latest_run or {}).get('sent_total') or 0)} | Filtered {str((selected_agent_latest_run or {}).get('held_back_total') or 0)}"
                                    if selected_agent_latest_run
                                    else "No finished run for this saved search yet."
                                ),
                                str((selected_agent_latest_run or {}).get("status_label") or "Waiting"),
                            ),
                        ]
                    ),
                },
                {
                    "eyebrow": "Saved agents",
                    "title": "Reusable searches",
                    "body": "Use Edit to load an agent back into the search desk, adjust the filters, and run or save it again.",
                    "items": agent_management_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Notification budget",
                    "title": "Strongest matches leave first",
                    "body": "If an agent finds more candidates than its daily or weekly limit, the shortlist is ranked and only the best-fit matches are sent.",
                    "items": [
                        row_item("Free", "1 active search agent.", "Plan"),
                        row_item("Plus", "3 active search agents.", "Plan"),
                        row_item("Agent", "Unlimited active search agents.", "Plan"),
                    ],
                },
                {
                    "eyebrow": "Recent runs",
                    "title": "What changed on the latest sweeps",
                    "body": "Use finished runs to inspect what was ranked, what left the budget, and what stayed filtered behind the active rules.",
                    "items": (
                        [
                            {
                                "title": str(run.get("title") or "Saved search"),
                                "detail": f"{str(run.get('status_label') or 'Run').strip()} | Ranked {str(run.get('ranked_total') or 0)} | Sent {str(run.get('sent_total') or 0)} | Filtered {str(run.get('held_back_total') or 0)}",
                                "tag": str(run.get("top_fit_score") or 0),
                                "action_href": str(run.get("href") or ""),
                                "action_method": "get",
                                "action_label": "Open results",
                            }
                            for run in (selected_agent_runs[:3] if selected_agent_runs else previous_search_runs[:3])
                        ]
                        or [row_item("No finished run yet", "The first completed sweep will show ranked, sent, and held-back counts here.", "Waiting")]
                    ),
                },
                run_card,
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "billing": {
            "title": "Billing",
            "summary": "Keep plan state, checkout path, and usage posture visible without mixing them into the shortlist surface.",
            "hero_kicker": "Billing",
            "hero_title": "Control the research tier without losing the search context.",
            "hero_summary": "The billing lane should explain what the current plan unlocks, what is capped, and how the next upgrade changes the search depth.",
            "hero_actions": hero_actions["billing"],
            "hero_highlights": hero_highlights["billing"],
            "primary_cards": [
                {
                    "eyebrow": "Plan posture",
                    "title": "Current commercial state",
                    "body": "Free should prove the product. Paid should expand research, provider breadth, and automation cleanly.",
                    "items": billing_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Upgrade impact",
                    "title": "What actually changes with each tier",
                    "body": "Show the numerical delta before the user opens checkout: provider breadth, shortlist density, threshold ceiling, and research depth.",
                    "items": billing_upgrade_rows,
                },
                {
                    "eyebrow": "Commercial decision",
                    "title": "Upgrade only when the current lane is the bottleneck",
                    "body": "The billing surface should help a serious buyer decide whether the next tier is justified by workload, not by generic SaaS pressure.",
                    "items": billing_decision_rows,
                },
            ],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
            "show_billing_cards": True,
        },
        "account": {
            "title": "Account",
            "summary": "Keep plan, profile, settings, and sign-out narrow and product-specific.",
            "hero_kicker": "Account",
            "hero_title": "Manage account, plan, and saved defaults.",
            "hero_summary": "Account keeps identity, plan limits, saved defaults, and sign-out in one place. It should feel like product control, not inherited office tooling.",
            "hero_actions": [
                {"href": f"/app/properties{run_suffix}", "label": "Back to Home", "tone": "primary"},
                {"href": f"/app/agents{run_suffix}", "label": "Search agents"},
                {"href": "/pricing", "label": "Open pricing"},
            ],
            "hero_highlights": [
                {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": "/app/account#settings"},
                {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": "/app/account#plans"},
                {"label": "Saved agents", "value": str(len(property_search_agents)), "detail": "Recurring searches ready to rerun or edit.", "href": f"/app/agents{run_suffix}"},
                {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": "/app/account#profile"},
            ],
            "primary_cards": [
                {
                    "eyebrow": "Connections",
                    "title": "Identity and return access",
                    "body": "Google is optional identity and easier return access. It is not an office sync contract here.",
                    "items": preference_rows + settings_connection_rows,
                },
                {
                    "eyebrow": "Saved defaults",
                    "title": "Current search brief state",
                    "body": "The saved brief stays visible so you can change the product posture before the next run.",
                    "items": list(search_posture_card.get("items") or []),
                },
                {
                    "eyebrow": "Operating posture",
                    "title": "Where the next change belongs",
                    "body": "Settings should tell the user what to change next instead of leaking inherited assistant concepts.",
                    "items": [
                        row_item("Search brief", "Go back to Search when the market, provider mix, or shortlist depth needs adjustment.", "Search"),
                        row_item("Plan", "Open the plan ladder when you need more providers, deeper research, or more sustained automation.", "Plan"),
                        row_item("Security", "Use the public security page to inspect retention and identity posture on this product.", "Trust"),
                    ],
                },
            ],
            "secondary_cards": [billing_rows and {
                "eyebrow": "Plan",
                "title": "Commercial posture",
                "body": "Plan limits and research depth stay visible here too.",
                "items": billing_rows,
            } or {}, {
                "eyebrow": "Public surfaces",
                "title": "Product-facing controls",
                "body": "The user should understand where the public contract lives too.",
                "items": [
                    {
                        "title": "Pricing",
                        "detail": "Inspect the current plan ladder and commercial delta on the public product page.",
                        "tag": "Public",
                        "action_href": "/pricing",
                        "action_method": "get",
                        "action_label": "Open pricing",
                    },
                    {
                        "title": "Security",
                        "detail": "Review trust, identity, and data-posture language on the public product page.",
                        "tag": "Public",
                        "action_href": "/security",
                        "action_method": "get",
                        "action_label": "Open security",
                    },
                ],
            }],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "settings": {
            "title": "Account",
            "summary": "Keep plan, profile, settings, and sign-out narrow and product-specific.",
            "hero_kicker": "Account",
            "hero_title": "Manage account, plan, and saved defaults.",
            "hero_summary": "Account keeps identity, plan limits, saved defaults, and sign-out in one place. It should feel like product control, not inherited office tooling.",
            "hero_actions": [
                {"href": f"/app/properties{run_suffix}", "label": "Back to Home", "tone": "primary"},
                {"href": f"/app/agents{run_suffix}", "label": "Search agents"},
                {"href": "/pricing", "label": "Open pricing"},
            ],
            "hero_highlights": [
                {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": "/app/account#settings"},
                {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": "/app/account#plans"},
                {"label": "Saved agents", "value": str(len(property_search_agents)), "detail": "Recurring searches ready to rerun or edit.", "href": f"/app/agents{run_suffix}"},
                {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": "/app/account#profile"},
            ],
            "primary_cards": [
                {
                    "eyebrow": "Connections",
                    "title": "Identity and return access",
                    "body": "Google is optional identity and easier return access. It is not an office sync contract here.",
                    "items": preference_rows + settings_connection_rows,
                },
                {
                    "eyebrow": "Saved defaults",
                    "title": "Current search brief state",
                    "body": "The saved brief stays visible so you can change the product posture before the next run.",
                    "items": list(search_posture_card.get("items") or []),
                },
                {
                    "eyebrow": "Operating posture",
                    "title": "Where the next change belongs",
                    "body": "Settings should tell the user what to change next instead of leaking inherited assistant concepts.",
                    "items": [
                        row_item("Search brief", "Go back to Search when the market, provider mix, or shortlist depth needs adjustment.", "Search"),
                        row_item("Plan", "Open the plan ladder when you need more providers, deeper research, or more sustained automation.", "Plan"),
                        row_item("Security", "Use the public security page to inspect retention and identity posture on this product.", "Trust"),
                    ],
                },
            ],
            "secondary_cards": [billing_rows and {
                "eyebrow": "Plan",
                "title": "Commercial posture",
                "body": "Plan limits and research depth stay visible here too.",
                "items": billing_rows,
            } or {}, {
                "eyebrow": "Public surfaces",
                "title": "Product-facing controls",
                "body": "The user should understand where the public contract lives too.",
                "items": [
                    {
                        "title": "Pricing",
                        "detail": "Inspect the current plan ladder and commercial delta on the public product page.",
                        "tag": "Public",
                        "action_href": "/pricing",
                        "action_method": "get",
                        "action_label": "Open pricing",
                    },
                    {
                        "title": "Security",
                        "detail": "Review trust, identity, and data-posture language on the public product page.",
                        "tag": "Public",
                        "action_href": "/security",
                        "action_method": "get",
                        "action_label": "Open security",
                    },
                ],
            }],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
    }

    payload = dict(sections.get(section, sections["properties"]))
    payload["stats"] = list(base.get("stats") or [])
    payload["current_plan_label"] = current_plan_label
    payload["run_payload"] = run_payload
    payload["run_summary"] = run_summary
    payload["preference_manager"] = preference_manager
    selected_result = workbench_results[0] if workbench_results else {}
    if selected_candidate_ref:
        for index, row in enumerate(workbench_results):
            if str(row.get("candidate_ref") or "").strip() != selected_candidate_ref:
                continue
            selected_result = row
            if index != 0:
                workbench_results = [row, *workbench_results[:index], *workbench_results[index + 1 :]]
            break
    payload["decision_workbench"] = {
        "run": {
            "run_id": run_id,
            "status": run_status_value or "not_started",
            "status_label": run_status_label,
            "progress": int(run_payload.get("progress") or 0),
            "message": run_status_note or run_message,
            "status_url": str(run_payload.get("status_url") or "").strip(),
            "summary": run_summary,
            "events": run_events[-8:],
            "worker_state": search_worker_state,
            "research_task_total": research_task_total,
            "open_research_task_total": open_research_task_total,
            "filled_research_task_total": filled_research_task_total,
            "dismissed_research_task_total": dismissed_research_task_total,
            "route_previews": progress_route_previews,
        },
        "brief": {
            "country": str(property_state.get("country_label") or "Austria"),
            "mode": str(property_preferences.get("listing_mode") or "rent").strip().title(),
            "region": str(property_state.get("region_label") or property_preferences.get("region_code") or "").strip(),
            "areas": selected_locations,
            "priorities": selected_keywords,
            "providers": selected_platforms,
            "plan": current_plan_label,
            "plan_key": str(commercial.get("current_plan_key") or "free").strip().lower() or "free",
            "research_depth": str(commercial.get("research_depth") or "deep").strip(),
        },
        "brief_preferences": dict(property_preferences),
        "endpoints": {
            "preferences": str(property_meta.get("preferences_endpoint") or "").strip(),
            "start": str(property_meta.get("start_endpoint") or "").strip(),
            "billing_order": str(property_meta.get("billing_order_endpoint") or "").strip(),
            "delete_run_template": "/app/api/property/search-runs/__RUN_ID__",
        },
        "counterfactual_rows": _property_counterfactual_rows(
            preferences=property_preferences,
            raw_preferences=dict(property_state.get("raw_preferences") or {}),
            run_summary=run_summary,
            provider_options=provider_options,
            current_platform_cap=current_platform_cap,
        ),
        "recent_packets": [
            {
                "title": str(item.get("title") or item.get("label") or "Review packet").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "tag": str(item.get("tag") or "Packet").strip(),
                "url": str(item.get("action_href") or "").strip(),
            }
            for item in list(recent_matches_card.get("items") or [])[:5]
            if isinstance(item, dict)
        ],
        "previous_search_runs": previous_search_runs,
        "results": workbench_results,
        "search_guard_rows": [],
        "suppression_rows": suppression_rows,
        "provider_quality_rows": provider_quality_rows,
        "delivery_proof_rows": delivery_proof_rows,
        "artifact_receipt_rows": artifact_receipt_rows,
        "research_tasks": research_tasks[:50],
        "research_task_counts": {
            "total": research_task_total,
            "open": open_research_task_total,
            "filled": filled_research_task_total,
            "dismissed": dismissed_research_task_total,
        },
        "selected_candidate_ref": str(selected_result.get("candidate_ref") or "").strip(),
        "selected": selected_result,
        "show_brief_default": not (run_in_progress or (run_status_value in {"processed", "completed"} and bool(workbench_results))),
    }
    return payload


def admin_section_payload(section: str) -> dict[str, object]:
    mapping: dict[str, dict[str, object]] = {
        "policies": {
            "title": "Policies",
            "summary": "Operator-only controls for approval rules, task contracts, and promoted skills.",
            "cards": [
                {"eyebrow": "Policy", "title": "Runtime policy endpoints", "items": ["/v1/policy", "/v1/tasks/contracts", "/v1/skills"]},
                {"eyebrow": "Why it matters", "title": "Keep the product shell separate", "items": ["Buyers see the assistant workflow.", "Admins see the policy plane."]},
            ],
        },
        "providers": {
            "title": "Providers",
            "summary": "Bindings, 1min state, and control-plane views belong here, not in the main buyer navigation.",
            "cards": [
                {"eyebrow": "Provider APIs", "title": "Registry and health", "items": ["/v1/providers/registry", "/v1/providers/states", "/v1/providers/onemin/aggregate"]},
                {"eyebrow": "Operational focus", "title": "What this surface is for", "items": ["Capacity admission", "Binding state", "Runway and burn"]},
            ],
        },
        "audit-trail": {
            "title": "Audit Trail",
            "summary": "Evidence, telemetry, and delivery state stay visible to admins without leaking into the public product story.",
            "cards": [
                {"eyebrow": "Audit", "title": "Trace surfaces", "items": ["/v1/runtime/lanes/telemetry", "/v1/evidence", "/v1/delivery/pending"]},
                {"eyebrow": "Goal", "title": "What this surface needs", "items": ["Receipts", "Execution state", "Delivery confirmations"]},
            ],
        },
        "operators": {
            "title": "Operators",
            "summary": "Admin identity, backlog, and approval work stay in the admin surface.",
            "cards": [
                {"eyebrow": "Human runtime", "title": "Admin endpoints", "items": ["/v1/human/operators", "/v1/human/tasks"]},
                {"eyebrow": "Trust boundary", "title": "Why this is separate", "items": ["Admin identity is separate from the customer workspace surface.", "Audit trails depend on trusted admin records."]},
            ],
        },
        "api": {
            "title": "Runtime",
            "summary": "The operator-center contract belongs in the admin surface, not on the public product pages.",
            "cards": [
                {"eyebrow": "OpenAPI", "title": "Schemas and runtime entrypoints", "items": ["/openapi.json", "/v1/plans/compile", "/v1/rewrite", "/v1/responses"]},
                {"eyebrow": "Docs", "title": "Reference material", "items": ["README", "ARCHITECTURE_MAP", "CI smoke suite"]},
            ],
        },
    }
    payload = mapping[section]
    return {
        "stats": [
            {"label": "Surface", "value": "admin"},
            {"label": "Access", "value": "admin-only"},
            {"label": "Audience", "value": "admins"},
            {"label": "Goal", "value": "operator center"},
        ],
        **payload,
    }
