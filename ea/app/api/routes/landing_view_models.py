from __future__ import annotations

import base64
import html
import hashlib
import io
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from app.product.property_location_research import (
    _property_research_boundary_record,
    _property_research_geojson_outer_rings,
)
from app.api.routes.landing_property_saved_searches import (
    build_agent_management_rows,
    build_property_search_agents,
    select_property_search_agent,
)
from app.api.routes.landing_property_search_posture import (
    build_property_market_summary_items,
)
from app.api.routes.landing_property_shortlist_panel import (
    build_property_source_rows,
    build_property_shortlist_panel,
)
from app.product.property_surface_state import (
    build_property_empty_outcome_summary,
    build_property_previous_run_summary,
    build_property_search_form_state_snapshot,
    build_property_shortlist_snapshot,
    build_property_workbench_candidate_snapshot,
    effective_property_listing_mode,
    normalized_property_search_goal,
    property_mode_visibility_label,
)
from app.api.routes.landing_property_surface_contracts import (
    PropertyDecisionWorkbenchBriefContract,
    PropertyDecisionWorkbenchContract,
    PropertyDecisionWorkbenchRunContract,
    PropertySurfacePayloadContract,
    PropertySurfaceScope,
)
from app.api.routes.landing_property_workspace_payload import (
    property_workspace_payload as build_property_workspace_payload,
)
from app.api.routes.landing_property_workspace_helpers import (
    _artifact_receipt_rows,
    _candidate_detail_sections,
    _compact_provider_label,
    _delivery_proof_rows,
    _group_property_provider_options,
    _official_risk_posture_rows,
    _property_candidate_directions_url,
    _property_candidate_maps_url,
    _property_candidate_orientation_preview,
    _property_candidate_preview_image,
    _property_candidate_route_evidence,
    _property_counterfactual_rows,
    _property_family_filters_active,
    _property_market_filter_capabilities,
    _property_progress_route_preview_rows,
    _property_run_reliability_summary,
    _property_route_preview_path,
    _property_search_guard_rows,
    _property_search_worker_slots,
    _property_suppression_rows,
)


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


def _property_customer_source_summary(source: dict[str, object]) -> dict[str, object]:
    source_row = dict(source or {})
    def _to_int(value: object) -> int:
        try:
            return max(0, int(float(str(value or "").strip())))
        except Exception:
            return 0
    return {
        "source_label": str(source_row.get("source_label") or source_row.get("platform") or "Provider").strip() or "Provider",
        "platform": str(source_row.get("platform") or "").strip(),
        "provider_family": str(source_row.get("provider_family") or "").strip(),
        "source_status": str(source_row.get("source_status") or source_row.get("status") or "Scanned").strip(),
        "status": str(source_row.get("status") or source_row.get("source_status") or "").strip(),
        "message": str(source_row.get("message") or "").strip(),
        "error": str(source_row.get("error") or "").strip(),
        "listing_total": _to_int(source_row.get("listing_total") or source_row.get("scanned_listing_total") or 0),
        "scanned_listing_total": _to_int(source_row.get("scanned_listing_total") or source_row.get("listing_total") or 0),
        "high_fit_total": _to_int(source_row.get("high_fit_total") or 0),
        "filtered_low_fit_total": _to_int(source_row.get("filtered_low_fit_total") or 0),
        "filtered_floorplan_total": _to_int(source_row.get("filtered_floorplan_total") or 0),
        "location_mismatch_reason": str(source_row.get("location_mismatch_reason") or "").strip(),
        "location_mismatch_candidate_total": _to_int(source_row.get("location_mismatch_candidate_total") or 0),
        "provider_filter_pushdown": dict(source_row.get("provider_filter_pushdown") or {})
        if isinstance(source_row.get("provider_filter_pushdown"), dict)
        else {},
        "timing_ms": dict(source_row.get("timing_ms") or {})
        if isinstance(source_row.get("timing_ms"), dict)
        else {},
    }


def _property_customer_run_summary(summary: dict[str, object]) -> dict[str, object]:
    source_rows = [
        _property_customer_source_summary(row)
        for row in list(dict(summary or {}).get("sources") or [])
        if isinstance(row, dict)
    ]
    clean = {
        key: value
        for key, value in dict(summary or {}).items()
        if key
        not in {
            "sources",
            "research_tasks",
            "provider_quality",
        }
    }
    clean["sources"] = source_rows
    return clean


def _sanitize_platform_catalog_for_client(platform_catalog: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    sanitized: dict[str, list[dict[str, object]]] = {}
    for country_code, options in dict(platform_catalog or {}).items():
        country_key = str(country_code or "").strip()
        if not country_key:
            continue
        rows: list[dict[str, object]] = []
        for option in list(options or []):
            if not isinstance(option, dict):
                continue
            row: dict[str, object] = {
                "value": str(option.get("value") or "").strip(),
                "label": str(option.get("label") or option.get("value") or "").strip(),
                "family": str(option.get("family") or "").strip(),
            }
            detail = str(option.get("detail") or option.get("description") or "").strip()
            normalized_detail = detail.lower()
            if detail and "floorplans " not in normalized_detail and "filters " not in normalized_detail:
                row["detail"] = detail
            rows.append(row)
        sanitized[country_key] = rows
    return sanitized


def _property_result_title_display(title: object) -> str:
    text = " ".join(str(title or "").split()).strip()
    if not text:
        return "Property"
    text = re.sub(r"\s+-\s+(willhaben|immobilienscout24|immoscout|immowelt|idealista|kleinanzeigen)\b.*$", "", text, flags=re.IGNORECASE).strip()
    trailing_patterns = (
        r",\s*\d+(?:[.,]\d+)?\s*m².*$",
        r",\s*(?:€|eur|usd|chf)\s*[0-9][0-9\.\,\s-]*(?:\([^)]*\))?.*$",
        r",\s*\([^)]*\)\s*$",
    )
    changed = True
    while changed and text:
        changed = False
        for pattern in trailing_patterns:
            updated = re.sub(pattern, "", text, flags=re.IGNORECASE).strip(" ,-")
            if updated != text:
                text = updated
                changed = True
    return text or "Property"


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


def _svg_to_data_url(svg: str) -> str:
    encoded = urllib.parse.quote(svg, safe=":/?&=,+-_.!~*'()#")
    return f"data:image/svg+xml;charset=utf-8,{encoded}"


def _scope_layout_preview_data_url(
    *,
    country_code: str,
    region_code: str,
    normalized_query: str,
    market_label: str,
    layout_rows: list[dict[str, object]],
    selected_lookup: set[str],
) -> str:
    width = 640
    height = 368
    chips: list[str] = []
    for row in layout_rows[:18]:
        value = str(row.get("value") or "").strip().lower()
        label = html.escape(str(row.get("label") or row.get("value") or "").strip())
        if not value or not label:
            continue
        x = float(row.get("x") or 0.0) / 100.0 * width
        y = float(row.get("y") or 0.0) / 100.0 * height
        chip_width = max(92.0, min((float(row.get("width") or 24.0) / 100.0 * width), 188.0))
        chip_height = max(34.0, min((float(row.get("height") or 20.0) / 100.0 * height), 54.0))
        selected = value in selected_lookup
        fill = "#c73a43" if selected else "#f4ede4"
        stroke = "#8f1f29" if selected else "#d9ccbd"
        text_fill = "#fffaf6" if selected else "#3f3630"
        chips.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{chip_width:.1f}" height="{chip_height:.1f}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        chips.append(
            f'<text x="{x + 12:.1f}" y="{y + (chip_height / 2) + 5:.1f}" fill="{text_fill}" '
            f'font-family="Inter, Arial, sans-serif" font-size="15" font-weight="600">{label}</text>'
        )
    title = html.escape(normalized_query or market_label or "Search area")
    subtitle = html.escape(market_label or f"{region_code} · {country_code}")
    badge = html.escape(country_code or "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#f6f0e8"/>'
        '<stop offset="100%" stop-color="#efe5d8"/>'
        '</linearGradient>'
        '</defs>'
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>'
        '<rect x="18" y="18" width="604" height="332" rx="18" fill="rgba(255,255,255,0.48)" stroke="#ddd0c1" stroke-width="2"/>'
        f'<text x="34" y="52" fill="#2f2a25" font-family="Inter, Arial, sans-serif" font-size="25" font-weight="700">{title}</text>'
        f'<text x="34" y="78" fill="#72665b" font-family="Inter, Arial, sans-serif" font-size="15">{subtitle}</text>'
        f'<rect x="544" y="28" width="62" height="28" rx="14" fill="#ffffff" stroke="#d9ccbd" stroke-width="1.5"/>'
        f'<text x="575" y="47" text-anchor="middle" fill="#61554b" font-family="Inter, Arial, sans-serif" font-size="13" font-weight="700">{badge}</text>'
        + "".join(chips) +
        '</svg>'
    )
    return _svg_to_data_url(svg)


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    scale = 2.0 ** zoom
    tile_x = (lon + 180.0) / 360.0 * scale
    tile_y = (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * scale
    return tile_x, tile_y


def _tile_to_lonlat(tile_x: float, tile_y: float, zoom: int) -> tuple[float, float]:
    scale = 2.0 ** zoom
    lon = (tile_x / scale) * 360.0 - 180.0
    n = math.pi - (2.0 * math.pi * tile_y / scale)
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, lat


def _tile_crop_geo_bounds(
    *,
    center_lat: float,
    center_lon: float,
    zoom: int,
    width: int = 640,
    height: int = 368,
    tile_size: int = 256,
    tile_span: int = 4,
) -> tuple[float, float, float, float]:
    tile_x, tile_y = _latlon_to_tile(center_lat, center_lon, zoom)
    tile_origin_x = int(math.floor(tile_x)) - (tile_span // 2)
    tile_origin_y = int(math.floor(tile_y)) - (tile_span // 2)
    center_x = int(round((tile_x - tile_origin_x) * tile_size))
    center_y = int(round((tile_y - tile_origin_y) * tile_size))
    canvas_size = tile_size * tile_span
    left = max(0, min(canvas_size - width, center_x - (width // 2)))
    top = max(0, min(canvas_size - height, center_y - (height // 2)))
    west, north = _tile_to_lonlat(tile_origin_x + (left / tile_size), tile_origin_y + (top / tile_size), zoom)
    east, south = _tile_to_lonlat(
        tile_origin_x + ((left + width) / tile_size),
        tile_origin_y + ((top + height) / tile_size),
        zoom,
    )
    return west, south, east, north


def _mercator_fraction_y(lat: float) -> float:
    lat_rad = math.radians(max(min(lat, 85.05112878), -85.05112878))
    return (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0


def _map_preview_cache_root() -> Path:
    root = Path(str(os.environ.get("EA_ARTIFACTS_DIR") or "/tmp/ea_artifacts")).resolve() / "map_previews"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _png_file_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _preview_zoom_for_bounds(
    bounds: tuple[float, float, float, float],
    *,
    width: int = 640,
    height: int = 368,
    min_zoom: int = 3,
    max_zoom: int = 16,
) -> int:
    west, south, east, north = bounds
    lon_span = max(abs(east - west), 0.0005)
    world_width = 256.0
    zoom_x = math.log2((360.0 * width) / (lon_span * world_width))
    mercator_north = _mercator_fraction_y(north)
    mercator_south = _mercator_fraction_y(south)
    y_span = max(abs(mercator_south - mercator_north), 0.000001)
    zoom_y = math.log2(height / (y_span * world_width))
    zoom = int(max(min_zoom, min(max_zoom, math.floor(min(zoom_x, zoom_y) - 0.25))))
    return zoom


def _cached_preview_data_url(
    *,
    cache_key: dict[str, object],
    center_lat: float,
    center_lon: float,
    zoom: int,
    overlay_rows: list[dict[str, object]] | None = None,
    boundary_paths: list[str] | None = None,
    pin: tuple[float, float] | None = None,
    draw_overlay: bool = True,
    width: int = 640,
    height: int = 368,
) -> str:
    normalized_key = json.dumps(cache_key, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha1(normalized_key.encode("utf-8")).hexdigest()
    cache_path = _map_preview_cache_root() / f"{digest}.png"
    if cache_path.exists():
        return _png_file_to_data_url(cache_path)

    tile_x, tile_y = _latlon_to_tile(center_lat, center_lon, zoom)
    tile_size = 256
    tile_span = 4
    tile_origin_x = int(math.floor(tile_x)) - (tile_span // 2)
    tile_origin_y = int(math.floor(tile_y)) - (tile_span // 2)
    canvas = Image.new("RGB", (tile_size * tile_span, tile_size * tile_span), color=(242, 236, 225))
    for dx in range(tile_span):
        for dy in range(tile_span):
            x_index = tile_origin_x + dx
            y_index = tile_origin_y + dy
            url = f"https://tile.openstreetmap.org/{zoom}/{x_index}/{y_index}.png"
            request = urllib.request.Request(url, headers={"User-Agent": "PropertyQuarry/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=6.0) as response:
                    tile_bytes = response.read()
                tile_image = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                tile_image = Image.new("RGB", (tile_size, tile_size), color=(242, 236, 225))
            canvas.paste(tile_image, (dx * tile_size, dy * tile_size))
    center_x = int(round((tile_x - tile_origin_x) * tile_size))
    center_y = int(round((tile_y - tile_origin_y) * tile_size))
    left = max(0, min(canvas.width - width, center_x - (width // 2)))
    top = max(0, min(canvas.height - height, center_y - (height // 2)))
    cropped = canvas.crop((left, top, left + width, top + height))
    draw = ImageDraw.Draw(cropped, "RGBA")

    for path in boundary_paths or []:
        numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)]
        points = list(zip(numbers[0::2], numbers[1::2]))
        if len(points) < 3:
            continue
        draw.line(points + [points[0]], fill=(70, 68, 65, 210), width=4, joint="curve")
    if draw_overlay:
        for index, row in enumerate(overlay_rows or []):
            path = str(row.get("path") or "").strip()
            if not path:
                continue
            numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)]
            points = list(zip(numbers[0::2], numbers[1::2]))
            if len(points) < 3:
                continue
            selected = bool(row.get("selected"))
            shade = 94 + (index % 5) * 22
            fill = (182 + min(shade, 40), 36 + (index % 3) * 10, 42 + (index % 4) * 8, 130 if selected else 72)
            stroke = (132, 23, 29, 245 if selected else 190)
            draw.polygon(points, fill=fill, outline=stroke)
    if pin:
        marker_x, marker_y = pin
        draw.ellipse((marker_x - 18, marker_y - 18, marker_x + 18, marker_y + 18), fill=(207, 53, 53, 58))
        draw.polygon(
            [
                (marker_x, marker_y - 18),
                (marker_x - 12, marker_y - 1),
                (marker_x, marker_y + 19),
                (marker_x + 12, marker_y - 1),
            ],
            fill=(197, 40, 40, 255),
        )
        draw.ellipse((marker_x - 5, marker_y - 10, marker_x + 5, marker_y), fill=(255, 248, 241, 255))

    cropped.save(cache_path, format="PNG", optimize=True)
    return _png_file_to_data_url(cache_path)


@lru_cache(maxsize=96)
def _openstreetmap_static_preview_data_url(lat_key: int, lon_key: int, zoom: int = 13) -> str:
    lat = lat_key / 10000.0
    lon = lon_key / 10000.0
    return _cached_preview_data_url(
        cache_key={"kind": "point", "lat_key": lat_key, "lon_key": lon_key, "zoom": zoom},
        center_lat=lat,
        center_lon=lon,
        zoom=zoom,
        pin=(320.0, 184.0),
    )


@lru_cache(maxsize=96)
def _forward_geocode_preview_point(query: str) -> tuple[float, float] | None:
    normalized = str(query or "").strip()
    if not normalized:
        return None
    request = urllib.request.Request(
        "https://nominatim.openstreetmap.org/search?"
        f"format=jsonv2&limit=1&q={urllib.parse.quote(normalized)}",
        headers={"User-Agent": "PropertyQuarry/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    if not isinstance(row, dict):
        return None
    try:
        return float(row.get("lat") or 0.0), float(row.get("lon") or 0.0)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=128)
def _nominatim_boundary_record(query: str) -> dict[str, object]:
    return dict(_property_research_boundary_record(query) or {})


def _geojson_outer_rings(geojson: dict[str, object]) -> list[list[tuple[float, float]]]:
    return list(_property_research_geojson_outer_rings(geojson))


def _union_geo_bounds(bounds_rows: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not bounds_rows:
        return None
    west = min(row[0] for row in bounds_rows)
    south = min(row[1] for row in bounds_rows)
    east = max(row[2] for row in bounds_rows)
    north = max(row[3] for row in bounds_rows)
    if west == east:
        east += 0.01
        west -= 0.01
    if south == north:
        north += 0.01
        south -= 0.01
    return west, south, east, north


def _project_lonlat_to_preview_path(
    points: list[tuple[float, float]],
    bounds: tuple[float, float, float, float],
    *,
    width: float = 296.0,
    height: float = 160.0,
) -> tuple[str, tuple[float, float]]:
    west, south, east, north = bounds
    lon_span = max(east - west, 0.000001)
    lat_span = max(north - south, 0.000001)
    projected: list[tuple[float, float]] = []
    for lon, lat in points:
        x = ((lon - west) / lon_span) * width
        y = height - (((lat - south) / lat_span) * height)
        projected.append((x, y))
    if not projected:
        return "", (0.0, 0.0)
    commands = [f"M{projected[0][0]:.1f} {projected[0][1]:.1f}"]
    commands.extend(f"L{x:.1f} {y:.1f}" for x, y in projected[1:])
    commands.append("Z")
    centroid_x = sum(point[0] for point in projected) / len(projected)
    centroid_y = sum(point[1] for point in projected) / len(projected)
    return " ".join(commands), (centroid_x, centroid_y)


def _expand_geo_bounds(
    bounds: tuple[float, float, float, float],
    *,
    padding_ratio: float = 0.2,
) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    lon_pad = max((east - west) * padding_ratio, 0.01)
    lat_pad = max((north - south) * padding_ratio, 0.01)
    return west - lon_pad, south - lat_pad, east + lon_pad, north + lat_pad


def _preview_query_with_context(value: str, country_code: str, region_code: str) -> str:
    label = str(value or "").strip()
    region = str(region_code or "").strip().replace("_", " ")
    country = str(country_code or "").strip().upper()
    if not label:
        return ""
    parts = [label]
    lowered = label.lower()
    if region and region.lower() not in lowered:
        parts.append(region.title())
    if country and country.lower() not in lowered:
        parts.append(country)
    return ", ".join(part for part in parts if part)


def _context_preview_query(country_code: str, region_code: str, location_query: str, selected_labels: list[str]) -> str:
    if location_query and len(_csv_values(location_query)) <= 1:
        return _preview_query_with_context(location_query, country_code, region_code)
    region = str(region_code or "").strip().replace("_", " ")
    if region:
        return _preview_query_with_context(region, country_code, "")
    if selected_labels:
        return _preview_query_with_context(selected_labels[0], country_code, "")
    return _preview_query_with_context(location_query, country_code, region_code)


def _build_scope_boundary_preview(
    *,
    country_code: str,
    region_code: str,
    normalized_query: str,
    selected_labels: list[str],
    selected_values: list[str],
    option_lookup: dict[str, str],
    market_label: str,
) -> dict[str, object]:
    queries = [
        _preview_query_with_context(option_lookup.get(value.lower(), value), country_code, region_code)
        for value in selected_values
        if str(value or "").strip()
    ]
    if not queries and normalized_query:
        queries = [_preview_query_with_context(normalized_query, country_code, region_code)]
    rows: list[dict[str, object]] = []
    bounds_rows: list[tuple[float, float, float, float]] = []
    for query in queries[:12]:
        record = _nominatim_boundary_record(query)
        if not record:
            continue
        bounds = record.get("bounds")
        if isinstance(bounds, tuple) and len(bounds) == 4:
            bounds_rows.append(bounds)
        rings = _geojson_outer_rings(dict(record.get("geojson") or {}))
        label = str(record.get("display_name") or query).split(",")[0].strip() or query
        rows.append({"label": label, "bounds": bounds, "rings": rings, "selected": True})
    if not rows:
        return {}

    context_record = _nominatim_boundary_record(_context_preview_query(country_code, region_code, normalized_query, selected_labels))
    boundary_paths: list[str] = []
    context_bounds = context_record.get("bounds") if isinstance(context_record.get("bounds"), tuple) else None
    union_bounds = _union_geo_bounds(bounds_rows)
    if not union_bounds:
        return {}
    render_bounds = _expand_geo_bounds(context_bounds or union_bounds)

    center_lon = (render_bounds[0] + render_bounds[2]) / 2.0
    center_lat = (render_bounds[1] + render_bounds[3]) / 2.0
    zoom = _preview_zoom_for_bounds(render_bounds)
    preview_bounds = _tile_crop_geo_bounds(center_lat=center_lat, center_lon=center_lon, zoom=zoom, width=640, height=368)

    district_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        rings = row.get("rings") if isinstance(row.get("rings"), list) else []
        if rings:
            path, _ = _project_lonlat_to_preview_path(rings[0], preview_bounds, width=640.0, height=368.0)
        else:
            bounds = row.get("bounds") if isinstance(row.get("bounds"), tuple) else None
            if not bounds:
                continue
            west, south, east, north = bounds
            rect_points = [(west, south), (east, south), (east, north), (west, north)]
            path, _ = _project_lonlat_to_preview_path(rect_points, preview_bounds, width=640.0, height=368.0)
        if not path:
            continue
        overlay_row = {"label": str(row.get("label") or f"Area {index + 1}").strip(), "selected": True, "path": path}
        district_rows.append(overlay_row)

    if not district_rows:
        return {}

    if context_bounds:
        for ring in _geojson_outer_rings(dict(context_record.get("geojson") or {}))[:1]:
            boundary_path, _ = _project_lonlat_to_preview_path(ring, preview_bounds, width=640.0, height=368.0)
            if boundary_path:
                boundary_paths.append(boundary_path)

    image_url = _cached_preview_data_url(
        cache_key={
            "kind": "scope",
            "country": country_code,
            "region": region_code,
            "query": normalized_query,
            "areas": [row["label"] for row in district_rows],
            "zoom": zoom,
            "overlay_mode": "svg_tile_crop_v2",
        },
        center_lat=center_lat,
        center_lon=center_lon,
        zoom=zoom,
        boundary_paths=boundary_paths,
        draw_overlay=True,
    )
    return {
        "image_url": image_url,
        "alt": f"Search area preview for {normalized_query or market_label}",
        "summary": ", ".join(selected_labels[:2]) if selected_labels else (normalized_query or market_label),
        "count_label": "",
        "market_label": market_label,
        "district_rows": district_rows,
        "district_overlay_svg": "",
    }


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
    market_label_parts = [part for part in (normalized_region.replace("_", " ").title(), normalized_country) if part]
    market_label = " · ".join(market_label_parts) or "Search area"
    preview = _build_scope_boundary_preview(
        country_code=normalized_country,
        region_code=normalized_region,
        normalized_query=normalized_query,
        selected_labels=selected_labels,
        selected_values=selected_values,
        option_lookup=option_lookup,
        market_label=market_label,
    )
    if preview:
        return preview

    fallback_rows = _merge_option_catalog(option_rows, selected_values)
    fallback_layout = _scope_preview_layout(normalized_country, normalized_region, fallback_rows)
    if fallback_layout:
        if not selected_lookup and selected_values:
            selected_lookup = {str(value or "").strip().lower() for value in selected_values if str(value or "").strip()}
        return {
            "image_url": _scope_layout_preview_data_url(
                country_code=normalized_country,
                region_code=normalized_region,
                normalized_query=normalized_query,
                market_label=market_label,
                layout_rows=fallback_layout,
                selected_lookup=selected_lookup,
            ),
            "alt": f"Search area preview for {normalized_query or market_label}",
            "summary": ", ".join(selected_labels[:2]) if selected_labels else (normalized_query or market_label),
            "count_label": "",
            "market_label": market_label,
            "district_rows": [],
            "district_overlay_svg": "",
        }

    return {
        "image_url": "",
        "alt": f"Search area preview for {normalized_query or market_label}",
        "summary": ", ".join(selected_labels[:2]) if selected_labels else (normalized_query or market_label),
        "count_label": "",
        "market_label": market_label,
        "district_rows": [],
        "district_overlay_svg": "",
    }


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


@lru_cache(maxsize=32)
def _property_region_options_cached(country_code: str) -> tuple[tuple[str, str, str], ...]:
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
        rows = catalogs[normalized_country]
    else:
        rows = region_options_for_country(normalized_country)
    return tuple(
        (
            str(row.get("value") or ""),
            str(row.get("label") or ""),
            str(row.get("detail") or ""),
        )
        for row in rows
    )


def _property_region_options(country_code: str) -> list[dict[str, str]]:
    return [
        {"value": value, "label": label, "detail": detail}
        for value, label, detail in _property_region_options_cached(country_code)
    ]


@lru_cache(maxsize=128)
def _property_location_options_cached(country_code: str, region_code: str = "") -> tuple[tuple[str, str, str], ...]:
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
        rows = catalogs[normalized_country]
    else:
        rows = location_options_for_country_region(normalized_country, region_code)
    return tuple(
        (
            str(row.get("value") or ""),
            str(row.get("label") or ""),
            str(row.get("detail") or ""),
        )
        for row in rows
    )


def _property_location_options(country_code: str, region_code: str = "") -> list[dict[str, str]]:
    return [
        {"value": value, "label": label, "detail": detail}
        for value, label, detail in _property_location_options_cached(country_code, region_code)
    ]


@lru_cache(maxsize=1)
def _property_keyword_options_cached() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            str(row["value"]),
            str(row["label"]),
            str(row["detail"]),
        )
        for row in [
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
    )


def _property_keyword_options() -> list[dict[str, str]]:
    return [
        {"value": value, "label": label, "detail": detail}
        for value, label, detail in _property_keyword_options_cached()
    ]


@lru_cache(maxsize=8)
def _property_region_catalog_by_country_cached(country_values: tuple[str, ...]) -> tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]:
    return tuple(
        (
            country_code,
            tuple(
                (row["value"], row["label"], row["detail"])
                for row in _property_region_options(country_code)
            ),
        )
        for country_code in country_values
        if country_code
    )


def _property_region_catalog_by_country(country_values: tuple[str, ...]) -> dict[str, list[dict[str, str]]]:
    return {
        country_code: [
            {"value": value, "label": label, "detail": detail}
            for value, label, detail in rows
        ]
        for country_code, rows in _property_region_catalog_by_country_cached(country_values)
    }


@lru_cache(maxsize=8)
def _property_market_filter_capabilities_catalog_cached(
    country_values: tuple[str, ...],
) -> tuple[tuple[str, tuple[tuple[str, tuple[tuple[str, bool], ...]], ...]], ...]:
    return tuple(
        (
            country_code,
            tuple(
                (
                    str(region.get("value") or ""),
                    tuple(sorted(_property_market_filter_capabilities(country_code, str(region.get("value") or "")).items())),
                )
                for region in _property_region_options(country_code)
            ),
        )
        for country_code in country_values
        if country_code
    )


def _property_market_filter_capabilities_catalog(country_values: tuple[str, ...]) -> dict[str, dict[str, dict[str, bool]]]:
    return {
        country_code: {
            region_code: {key: bool(value) for key, value in capability_rows}
            for region_code, capability_rows in region_rows
        }
        for country_code, region_rows in _property_market_filter_capabilities_catalog_cached(country_values)
    }


@lru_cache(maxsize=8)
def _property_location_catalog_by_country_region_cached(
    country_values: tuple[str, ...],
) -> tuple[tuple[str, tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]], ...]:
    return tuple(
        (
            country_code,
            tuple(
                (
                    str(region.get("value") or ""),
                    tuple(
                        (row["value"], row["label"], row["detail"])
                        for row in _property_location_options(country_code, str(region.get("value") or ""))
                    ),
                )
                for region in _property_region_options(country_code)
            ),
        )
        for country_code in country_values
        if country_code
    )


def _property_location_catalog_by_country_region(country_values: tuple[str, ...]) -> dict[str, dict[str, list[dict[str, str]]]]:
    return {
        country_code: {
            region_code: [
                {"value": value, "label": label, "detail": detail}
                for value, label, detail in location_rows
            ]
            for region_code, location_rows in region_rows
        }
        for country_code, region_rows in _property_location_catalog_by_country_region_cached(country_values)
    }


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
        for key in ("title", "property_url", "review_url", "source_ref", "source_label")
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
    surface_scope = PropertySurfaceScope.for_section(str(property_state.get("surface_mode") or "properties"))
    property_run = dict(property_state.get("run") or {})
    property_run_preferences = (
        dict(property_run.get("property_search_preferences") or property_run.get("preferences") or {})
        if isinstance(property_run.get("property_search_preferences") or property_run.get("preferences"), dict)
        else {}
    )
    property_preferences = {
        **dict(property_state.get("preferences") or {}),
        **property_run_preferences,
    }
    property_summary = dict(property_run.get("summary") or {})
    property_country_label = str(property_state.get("country_label") or "Market")
    property_language_label = str(property_state.get("language_label") or "Deutsch")
    property_listing_mode_label = str(property_state.get("listing_mode_label") or "Rent")
    property_search_goal_label = str(property_state.get("search_goal_label") or "Find a home")
    property_investment_strategy_label = str(property_state.get("investment_strategy_label") or "Best overall opportunity")
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
    selected_full_region_scope = bool(property_preferences.get("full_region_scope"))
    country_options = [dict(option) for option in list(property_state.get("country_options") or []) if isinstance(option, dict)]
    language_options = [dict(option) for option in list(property_state.get("language_options") or []) if isinstance(option, dict)]
    listing_mode_options = [dict(option) for option in list(property_state.get("listing_mode_options") or []) if isinstance(option, dict)]
    search_goal_options = [dict(option) for option in list(property_state.get("search_goal_options") or []) if isinstance(option, dict)]
    investment_strategy_options = [dict(option) for option in list(property_state.get("investment_strategy_options") or []) if isinstance(option, dict)]
    investment_research_mode_options = [dict(option) for option in list(property_state.get("investment_research_mode_options") or []) if isinstance(option, dict)]
    property_type_options = [dict(option) for option in list(property_state.get("property_type_options") or []) if isinstance(option, dict)]
    selected_platforms = {
        str(value or "").strip()
        for value in (property_state.get("selected_platforms") or [])
        if str(value or "").strip()
    }
    search_form_state = build_property_search_form_state_snapshot(
        property_preferences,
        selected_listing_mode=selected_listing_mode,
    )
    selected_country_code = str(search_form_state.get("selected_country_code") or "AT").strip().upper() or "AT"
    selected_search_goal = str(search_form_state.get("selected_search_goal") or "home").strip().lower() or "home"
    selected_investment_strategy = str(search_form_state.get("selected_investment_strategy") or "best_overall").strip().lower() or "best_overall"
    selected_investment_research_mode = str(search_form_state.get("selected_investment_research_mode") or "off").strip().lower() or "off"
    property_is_investment_search = bool(search_form_state.get("property_is_investment_search"))
    selected_school_stage_preferences = [
        str(item or "").strip()
        for item in list(search_form_state.get("selected_school_stage_preferences") or [])
        if str(item or "").strip()
    ]
    school_evidence_controls_enabled = bool(search_form_state.get("school_evidence_controls_enabled"))
    selected_listing_mode = str(search_form_state.get("selected_listing_mode") or selected_listing_mode or "rent").strip().lower() or "rent"
    property_listing_mode_label = property_mode_visibility_label(
        {
            **property_preferences,
            "search_goal": selected_search_goal,
            "listing_mode": selected_listing_mode,
        },
        fallback=selected_listing_mode,
    )
    show_investment_underwriting_controls = bool(search_form_state.get("show_investment_underwriting_controls"))
    show_lifestyle_research_controls = bool(search_form_state.get("show_lifestyle_research_controls"))
    show_community_validation_controls = bool(search_form_state.get("show_community_validation_controls"))
    show_developer_project_stage_controls = bool(search_form_state.get("show_developer_project_stage_controls"))
    show_public_housing_policy_controls = bool(search_form_state.get("show_public_housing_policy_controls"))
    show_distressed_review_controls = bool(search_form_state.get("show_distressed_review_controls"))
    show_search_agent_detail_controls = bool(search_form_state.get("show_search_agent_detail_controls"))
    show_preference_profile_controls = bool(search_form_state.get("show_preference_profile_controls"))
    show_school_quality_priority_controls = bool(search_form_state.get("show_school_quality_priority_controls"))
    show_playground_importance_controls = bool(search_form_state.get("show_playground_importance_controls"))
    show_library_importance_controls = bool(search_form_state.get("show_library_importance_controls"))
    show_supermarket_importance_controls = bool(search_form_state.get("show_supermarket_importance_controls"))
    min_gross_yield_pct = int(search_form_state.get("min_gross_yield_pct") or 0)
    equity_available_eur = int(search_form_state.get("equity_available_eur") or 0)
    loan_term_years = int(search_form_state.get("loan_term_years") or 25)
    max_interest_rate_pct = int(search_form_state.get("max_interest_rate_pct") or 0)
    min_dscr = float(search_form_state.get("min_dscr") or 0.0)
    vacancy_reserve_pct = int(search_form_state.get("vacancy_reserve_pct") or 4)
    capex_reserve_pct = int(search_form_state.get("capex_reserve_pct") or 6)
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
    selected_region_label = selected_region_code.replace("_", " ").title() if selected_region_code else "area"
    if selected_region_code and not selected_location_values:
        try:
            from app.services.property_market_catalog import region_label_for_country_region
            selected_region_label = region_label_for_country_region(
                str(property_preferences.get("country_code") or "AT"),
                selected_region_code,
            )
        except Exception:
            selected_region_label = selected_region_code.replace("_", " ").title()
        if str(property_preferences.get("location_query") or "").strip().lower() == selected_region_label.strip().lower():
            selected_full_region_scope = True
    location_options = _property_location_options(
        str(property_preferences.get("country_code") or "AT"),
        selected_region_code,
    )
    keyword_options = _property_keyword_options()
    selected_location_values, custom_location_values = _split_known_and_custom_values(location_options, selected_location_values)
    selected_keyword_values, custom_keyword_values = _split_known_and_custom_values(keyword_options, selected_keyword_values)
    custom_location_query = str(property_preferences.get("custom_location_query") or ", ".join(custom_location_values)).strip()
    custom_keywords = str(property_preferences.get("custom_keywords") or ", ".join(custom_keyword_values)).strip()
    adjacent_area_radius_unit = str(property_preferences.get("adjacent_area_radius_unit") or "m").strip().lower()
    if adjacent_area_radius_unit not in {"m", "km"}:
        adjacent_area_radius_unit = "m"
    try:
        adjacent_area_radius_value = float(property_preferences.get("adjacent_area_radius_value"))
    except Exception:
        try:
            stored_adjacent_area_radius_m = float(property_preferences.get("adjacent_area_radius_m") or 0.0)
        except Exception:
            stored_adjacent_area_radius_m = 0.0
        adjacent_area_radius_value = stored_adjacent_area_radius_m / 1000.0 if adjacent_area_radius_unit == "km" else stored_adjacent_area_radius_m
    if adjacent_area_radius_unit == "km":
        adjacent_area_radius_value = max(0.0, min(adjacent_area_radius_value, 1000.0))
        adjacent_area_radius_step = 1
    else:
        adjacent_area_radius_value = max(0.0, min(adjacent_area_radius_value, 1000.0))
        adjacent_area_radius_step = 25
    property_selected_platform_labels = [
        str(option.get("label") or option.get("value") or "").strip()
        for option in platform_options
        if str(option.get("value") or "").strip() in selected_platforms
    ]
    property_market_summary_items = build_property_market_summary_items(
        row_item=row_item,
        property_country_label=property_country_label,
        property_language_label=property_language_label,
        property_search_goal_label=property_search_goal_label,
        property_type_label=property_type_label,
        property_listing_mode_label=property_listing_mode_label,
        property_is_investment_search=property_is_investment_search,
        show_investment_underwriting_controls=show_investment_underwriting_controls,
        property_investment_strategy_label=property_investment_strategy_label,
        min_gross_yield_pct=min_gross_yield_pct,
        equity_available_eur=equity_available_eur,
        min_dscr=min_dscr,
        property_investment_research_mode_label=property_investment_research_mode_label,
        property_available_within_years_value=property_available_within_years_value,
        property_preferences=property_preferences,
        custom_keywords=custom_keywords,
        show_lifestyle_research_controls=show_lifestyle_research_controls,
        show_developer_project_stage_controls=show_developer_project_stage_controls,
        show_public_housing_policy_controls=show_public_housing_policy_controls,
        show_distressed_review_controls=show_distressed_review_controls,
    )
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
    ] if surface_scope.wants_recent_matches else []
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

    if surface_scope.wants_run_views:
        for source in list(property_summary.get("sources") or []):
            if not isinstance(source, dict):
                continue
            source_row = dict(source)
            source_label = str(source_row.get("source_label") or source_row.get("source_url") or "Source").strip()
            source_row["display_source_label"] = _compact_provider_label(source_label)
            enriched_candidates: list[dict[str, object]] = []
            for candidate in list(source_row.get("top_candidates") or []):
                if not isinstance(candidate, dict):
                    continue
                candidate_row = dict(candidate)
                candidate_row.setdefault("source_label", source_label)
                candidate_row.setdefault("source_short_label", _compact_provider_label(source_label))
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
                        candidate_row.setdefault("source_short_label", _compact_provider_label(source_label))
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

    property_source_rows = build_property_source_rows(property_summary=property_summary)
    property_shortlist_rows, property_shortlist_cards = build_property_shortlist_panel(
        property_summary=property_summary,
        property_preferences=property_preferences,
        active_run_id=active_run_id,
        wants_run_views=surface_scope.wants_run_views,
        clean_candidate_copy=_clean_property_candidate_copy,
        candidate_priority_reason=_candidate_priority_reason,
        property_candidate_ref=_property_candidate_ref,
    )
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
    selected_property_type_values = _normalize_property_type_values(property_preferences.get("property_type"))
    if surface_scope.wants_search_runs or surface_scope.wants_agent_views:
        property_search_agents, property_search_agent = build_property_search_agents(
            property_preferences,
            selected_platforms=selected_platforms,
            selected_listing_mode=selected_listing_mode,
            search_mode_requested=property_search_mode_requested,
            default_duration_days=property_search_agent_duration_days,
            default_notification_limit=property_search_agent_notification_limit,
            default_notification_period=property_search_agent_notification_period,
            normalize_property_type_values=_normalize_property_type_values,
            scope_preview_builder=_property_scope_preview,
        )
    else:
        property_search_agents, property_search_agent = [], {}
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
    country_codes = tuple(
        str(option.get("value") or "").strip()
        for option in country_options
        if str(option.get("value") or "").strip()
    )
    region_catalog_by_country = _property_region_catalog_by_country(country_codes)
    market_filter_capabilities_by_country_region = _property_market_filter_capabilities_catalog(country_codes)
    location_catalog_by_country_region = _property_location_catalog_by_country_region(country_codes)
    property_form = {
        "variant": "property_search",
        "title": "Run a premium market sweep",
        "eyebrow": "Flagship property desk",
        "copy": "Set the market, shape the shortlist, choose the sources, then launch one visible research run with ranking, review pages, and client-ready alerts.",
        "submit_label": "Launch search",
        "fields": [
            {
                "type": "select",
                "name": "search_goal",
                "label": "What are you looking for?",
                "value": selected_search_goal,
                "options": search_goal_options,
                "tooltip": "Choose Find a home for lifestyle fit, or Find an investment for yield, value, risk, and execution ranking.",
                "step": "search",
            },
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
                "tooltip": "Home searches can look at rent or buy. Investment searches use buy mode automatically.",
                "step": "search",
                "hidden": property_is_investment_search,
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
                "hidden": not property_is_investment_search,
                "tooltip": "Choose whether the investment sweep should stay ranking-only or add yield, pricing, and risk context before the full property page.",
                "step": "search",
            },
            {
                "type": "select",
                "name": "investment_strategy",
                "label": "Investment strategy",
                "value": selected_investment_strategy,
                "options": investment_strategy_options,
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "Choose the thesis first. Cash flow weights yield highest. Appreciation weights area pricing and upside. Low risk penalizes unclear or messy deals.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_gross_yield_pct",
                "label": "Minimum gross yield",
                "value": str(min_gross_yield_pct),
                "min": "0",
                "max": "15",
                "visual_max": "15",
                "range_step": "1",
                "format": "percent_cap",
                "empty_label": "Any yield",
                "scale_min_label": "Any",
                "scale_max_label": "15%",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "Use this as a hard floor for expected gross yield when enough rent evidence exists. Unknown yields stay visible but rank lower.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "equity_available_eur",
                "label": "Equity available",
                "value": str(equity_available_eur),
                "min": "0",
                "max": "1000000",
                "visual_max": "1000000",
                "range_step": "25000",
                "format": "currency_eur",
                "empty_label": "Model leverage automatically",
                "scale_min_label": "Auto",
                "scale_max_label": "EUR 1.0m",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "Use this when you want debt coverage and cash-on-cash yield to reflect your real equity instead of the default leverage assumption.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "loan_term_years",
                "label": "Loan term",
                "value": str(loan_term_years),
                "min": "5",
                "max": "40",
                "visual_max": "40",
                "range_step": "1",
                "format": "loan_term_years",
                "scale_min_label": "5y",
                "scale_max_label": "40y",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "This drives the modeled annual debt service behind DSCR and cash-on-cash yield.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "max_interest_rate_pct",
                "label": "Rate assumption ceiling",
                "value": str(max_interest_rate_pct),
                "min": "0",
                "max": "12",
                "visual_max": "12",
                "range_step": "1",
                "format": "percent_cap",
                "empty_label": "Live or fallback rate",
                "scale_min_label": "Auto",
                "scale_max_label": "12%",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "Use this when you want the financing model to stay conservative even if a live feed returns a softer rate.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "min_dscr",
                "label": "Minimum debt coverage",
                "value": str(int(round(min_dscr * 100)) if min_dscr > 0 else 0),
                "min": "0",
                "max": "250",
                "visual_max": "250",
                "range_step": "5",
                "format": "dscr_hundredths",
                "empty_label": "Any DSCR",
                "scale_min_label": "Any",
                "scale_max_label": "2.50x",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "A DSCR floor lets you exclude deals that do not cover their modeled annual debt service cleanly enough.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "vacancy_reserve_pct",
                "label": "Vacancy reserve",
                "value": str(vacancy_reserve_pct),
                "min": "0",
                "max": "25",
                "visual_max": "25",
                "range_step": "1",
                "format": "percent_cap",
                "empty_label": "Feed or market default",
                "scale_min_label": "Auto",
                "scale_max_label": "25%",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "This reserve reduces the rent roll before NOI and DSCR are calculated.",
                "step": "search",
            },
            {
                "type": "range",
                "name": "capex_reserve_pct",
                "label": "Capex reserve",
                "value": str(capex_reserve_pct),
                "min": "0",
                "max": "25",
                "visual_max": "25",
                "range_step": "1",
                "format": "percent_cap",
                "empty_label": "Feed or market default",
                "scale_min_label": "Auto",
                "scale_max_label": "25%",
                "hidden": not show_investment_underwriting_controls,
                "tooltip": "This reserve keeps the underwriting honest when the listing looks cheap but long-run upkeep is still unresolved.",
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
                "name": "full_region_scope",
                "label": f"Use all {selected_region_label}" if selected_region_label else "Use full area",
                "value": "true",
                "checked": selected_full_region_scope,
                "step": "areas",
            },
            {
                "type": "checkbox_group",
                "name": "location_query",
                "label": "Target areas",
                "options": location_options,
                "values": selected_location_values,
                "hidden": selected_full_region_scope,
                "step": "areas",
            },
            {
                "type": "range",
                "name": "adjacent_area_radius_value",
                "label": "How far outside the selected areas",
                "value": int(adjacent_area_radius_value) if float(adjacent_area_radius_value).is_integer() else round(adjacent_area_radius_value, 1),
                "min": 0,
                "max": 1000,
                "range_step": adjacent_area_radius_step,
                "format": "distance_outside_area",
                "empty_label": "District only",
                "scale_min_label": "0",
                "scale_max_label": f"1000 {adjacent_area_radius_unit}",
                "step": "areas",
                "tooltip": "Allow homes just outside the selected districts or areas when they are still nearby.",
                "unit_field": "adjacent_area_radius_unit",
                "meter_step": 25,
                "km_step": 1,
            },
            {
                "type": "select",
                "name": "adjacent_area_radius_unit",
                "label": "Unit",
                "value": adjacent_area_radius_unit,
                "options": [
                    {"value": "m", "label": "Meters"},
                    {"value": "km", "label": "Kilometers"},
                ],
                "step": "areas",
            },
            {
                "type": "text",
                "name": "custom_location_query",
                "label": "Add areas manually",
                "value": custom_location_query,
                "placeholder": "Free text for areas not covered by the checklist",
                "tooltip": "Use this only when the district or area is not already available as a visible checkbox.",
                "step": "areas",
            },
            {
                "type": "checkbox",
                "name": "investment_require_floorplan",
                "label": "Only keep deals with a floorplan",
                "value": "true",
                "checked": bool(property_preferences.get("investment_require_floorplan") or property_preferences.get("require_floorplan")),
                "tooltip": "Use this for cleaner underwriting. Listings without a layout stay out of the final investment shortlist.",
                "step": "areas",
                "hidden": not show_investment_underwriting_controls,
            },
            {
                "type": "checkbox",
                "name": "investment_require_legal_clarity",
                "label": "Exclude legal complexity",
                "value": "true",
                "checked": bool(property_preferences.get("investment_require_legal_clarity")),
                "tooltip": "Exclude auctions, leasehold-style structures, and other legally messy deals when you want a cleaner shortlist first.",
                "step": "areas",
                "hidden": not show_investment_underwriting_controls,
            },
            {
                "type": "checkbox",
                "name": "investment_require_tenant_clarity",
                "label": "Exclude unclear tenant status",
                "value": "true",
                "checked": bool(property_preferences.get("investment_require_tenant_clarity")),
                "tooltip": "Penalize or exclude listings that do not make occupancy or rentability clear enough for a fast investment read.",
                "step": "areas",
                "hidden": not show_investment_underwriting_controls,
            },
            {
                "type": "checkbox",
                "name": "investment_avoid_major_renovation",
                "label": "Exclude heavy renovation candidates",
                "value": "true",
                "checked": bool(property_preferences.get("investment_avoid_major_renovation")),
                "tooltip": "Exclude listings whose own text suggests major renovation, core refurbishment, or a fixer-upper posture.",
                "step": "areas",
                "hidden": not show_investment_underwriting_controls,
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
                "hidden": not show_community_validation_controls,
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
                "hidden": selected_listing_mode != "rent",
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
                "hidden": not show_public_housing_policy_controls,
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
                "hidden": not show_public_housing_policy_controls,
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
                "hidden": not show_public_housing_policy_controls,
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
                "hidden": not show_public_housing_policy_controls,
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
                "hidden": not show_public_housing_policy_controls,
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
                "hidden": selected_listing_mode != "buy",
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
                "hidden": not show_preference_profile_controls,
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
                "hidden": not show_school_quality_priority_controls,
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
                "hidden": not show_playground_importance_controls,
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
                "hidden": not show_library_importance_controls,
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
                "hidden": not show_developer_project_stage_controls,
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
                "hidden": not show_distressed_review_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_lifestyle_research_controls,
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
                "hidden": not show_supermarket_importance_controls,
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
                "advanced_panel": "children_wellbeing",
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
                "advanced_panel": "children_wellbeing",
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
                "label": "Save as recurring search",
                "value": "true",
                "checked": property_search_agent_enabled,
                "tooltip": "Save these settings as a recurring search that keeps watching the market. Disable this checkbox to keep the settings as a one-off brief only.",
                "step": "providers",
            },
            {
                "type": "range",
                "name": "search_agent_duration_days",
                "label": "Recurring search duration",
                "value": str(property_search_agent_duration_days),
                "min": "7",
                "max": "365",
                "visual_max": "365",
                "range_step": "7",
                "format": "agent_duration_days",
                "scale_min_label": "1 week",
                "scale_mid_label": "6 months",
                "scale_max_label": "1 year",
                "tooltip": "How long this recurring search should stay active before it expires or needs review.",
                "step": "providers",
                "hidden": not show_search_agent_detail_controls,
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
                "hidden": not show_search_agent_detail_controls,
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
                "hidden": not show_search_agent_detail_controls,
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
            "platform_catalog_by_country": _sanitize_platform_catalog_for_client(
                dict(property_state.get("platform_catalog_by_country") or {})
            ),
            "default_language_by_country": dict(property_state.get("default_language_by_country") or {}),
            "region_catalog_by_country": region_catalog_by_country,
            "market_filter_capabilities_by_country_region": market_filter_capabilities_by_country_region,
            "market_filter_capabilities": market_filter_capabilities,
            "location_catalog_by_country_region": location_catalog_by_country_region,
            "supports_full_region_scope": True,
            "commercial": dict(property_state.get("commercial") or {}),
            "billing_checkout_enabled": bool(property_state.get("billing_checkout_enabled")),
            "billing_checkout_enabled_plans": list(property_state.get("billing_checkout_enabled_plans") or []),
            "billing_checkout_provider": str(property_state.get("billing_checkout_provider") or ""),
            "billing_checkout_provider_label": str(property_state.get("billing_checkout_provider_label") or ""),
            "billing_order_endpoint": str(property_state.get("billing_order_endpoint") or ""),
            "billing_order_endpoints_by_plan": dict(property_state.get("billing_order_endpoints_by_plan") or {}),
            "billing_provider_labels_by_plan": dict(property_state.get("billing_provider_labels_by_plan") or {}),
            "feedback_person_id": str(property_preferences.get("preference_person_id") or "self"),
            "search_agent": property_search_agent,
            "search_agents": property_search_agents,
            "search_agent_update_endpoint_template": "/v1/onboarding/property-search/agents/__AGENT_ID__",
            "shortlist_candidates": property_shortlist_cards,
            "wizard_steps": [
                {
                    "key": "search",
                    "label": "Market" if property_is_investment_search else "Where",
                    "detail": "Market, listing mode, and budget."
                    if property_is_investment_search
                    else "Country, city, and the first budget line.",
                },
                {
                    "key": "areas",
                    "label": "Strategy" if property_is_investment_search else "Home shape",
                    "detail": "Target areas, spillover distance, and investment guardrails."
                    if property_is_investment_search
                    else "Areas, spillover distance, and the home shape that should survive the cut.",
                },
                {
                    "key": "children",
                    "label": "Guardrails" if property_is_investment_search else "Daily life",
                    "detail": "Execution risk, legal posture, and which weak listings should be excluded."
                    if property_is_investment_search
                    else "Schools, childcare, and the everyday context that should stay explicit.",
                },
                {
                    "key": "reachability",
                    "label": "Evidence" if property_is_investment_search else "Reachability",
                    "detail": "How much underwriting and supporting evidence the shortlist needs."
                    if property_is_investment_search
                    else "Destinations, travel modes, and time limits that change the ranking.",
                },
                {
                    "key": "research",
                    "label": "Underwriting" if property_is_investment_search else "Research depth",
                    "detail": "Return, risk, and external evidence depth."
                    if property_is_investment_search
                    else "Risk, supply, and how much evidence each strong match should carry.",
                },
                {
                    "key": "providers",
                    "label": "Sources",
                    "detail": "Choose trusted sources, then save or launch.",
                },
            ],
        },
    }
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
                {"eyebrow": "Account", "title": "Current state", "items": string_rows([f"Status: {status_label}", f"Setup state: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"], ("No account state yet.",), tag="State", detail="This is the current account status.")},
                {"eyebrow": "Channels", "title": "Recent changes", "items": channel_items},
                {"eyebrow": "Trust", "title": "Why this feed matters", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Context", detail="This keeps the activity feed understandable.")},
            ],
        },
        "settings": {
            "title": "Rules",
            "summary": "Rules stay boring and explicit once the first working loop already exists.",
            "cards": [
                {"eyebrow": "Account", "title": "Current account posture", "items": string_rows([f"Name: {workspace.get('name') or 'PropertyQuarry'}", f"Mode: {humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"], ("No account posture yet.",), tag="Account", detail="These are the current PropertyQuarry defaults.")},
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
                    "body": "The strongest matches stay review-ready: fit, risk, 360 status, property page, and the next useful action are visible before operational crawl details.",
                    "items": property_shortlist_rows
                    or property_recent_matches
                    or [
                        row_item(
                            "First shortlist still pending",
                            "Launch the first sweep to generate a ranked candidate lane with property pages, hosted tours, and visible fit reasons.",
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
                    "body": "Strong matches should resolve to branded hosted property pages, not raw portal links.",
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
    return build_property_workspace_payload(
        section,
        status=status,
        property_state=property_state,
    )


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
