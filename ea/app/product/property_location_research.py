from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import requests
from datetime import datetime, timezone
from functools import lru_cache

from app.product.projections import compact_text
from app.observability import outbound_observability_headers

_PROPERTY_LOCATION_RESEARCH_USER_AGENT = (
    "PropertyQuarry/2026-07 location-research (+https://propertyquarry.com; contact property@propertyquarry.com)"
)
_PROPERTY_LOCATION_RESEARCH_REFERER = "https://propertyquarry.com/"
_PROPERTY_SCHOOLATLAS_SOURCE_URL = "https://www.statistik.at/atlas/schulen/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_or_none(value: object) -> float | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return float(text.replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _property_location_research_headers() -> dict[str, str]:
    return {
        "User-Agent": _PROPERTY_LOCATION_RESEARCH_USER_AGENT,
        "Referer": _PROPERTY_LOCATION_RESEARCH_REFERER,
        "Accept": "*/*",
        **outbound_observability_headers(),
    }

def _property_research_distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> int:
    from math import atan2, cos, radians, sin, sqrt

    earth_radius_m = 6_371_000.0
    phi_a = radians(lat_a)
    phi_b = radians(lat_b)
    delta_phi = radians(lat_b - lat_a)
    delta_lambda = radians(lon_b - lon_a)
    arc = sin(delta_phi / 2.0) ** 2 + cos(phi_a) * cos(phi_b) * sin(delta_lambda / 2.0) ** 2
    return int(round(2.0 * earth_radius_m * atan2(sqrt(arc), sqrt(max(1.0 - arc, 0.0)))))

@lru_cache(maxsize=128)
def _property_research_reverse_geocode(lat: float, lon: float) -> dict[str, object]:
    request = urllib.request.Request(
        (
            "https://nominatim.openstreetmap.org/reverse?"
            f"format=jsonv2&lat={lat:.8f}&lon={lon:.8f}&zoom=18&addressdetails=1"
        ),
        headers=_property_location_research_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

@lru_cache(maxsize=128)
def _property_research_forward_geocode(query: str) -> dict[str, object]:
    normalized = str(query or "").strip()
    if not normalized:
        return {}
    request = urllib.request.Request(
        (
            "https://nominatim.openstreetmap.org/search?"
            f"format=jsonv2&limit=1&q={urllib.parse.quote(normalized)}"
        ),
        headers=_property_location_research_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, list) or not payload:
        return {}
    row = payload[0]
    return row if isinstance(row, dict) else {}


@lru_cache(maxsize=128)
def _property_research_boundary_record(query: str) -> dict[str, object]:
    normalized = str(query or "").strip()
    if not normalized:
        return {}
    request = urllib.request.Request(
        (
            "https://nominatim.openstreetmap.org/search?"
            f"format=jsonv2&limit=1&polygon_geojson=1&q={urllib.parse.quote(normalized)}"
        ),
        headers=_property_location_research_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, list) or not payload:
        return {}
    row = payload[0]
    if not isinstance(row, dict):
        return {}
    boundingbox = row.get("boundingbox") if isinstance(row.get("boundingbox"), list) else []
    try:
        south = float(boundingbox[0])
        north = float(boundingbox[1])
        west = float(boundingbox[2])
        east = float(boundingbox[3])
    except (IndexError, TypeError, ValueError):
        south = north = west = east = 0.0
    return {
        "display_name": str(row.get("display_name") or normalized).strip(),
        "geojson": row.get("geojson") if isinstance(row.get("geojson"), dict) else {},
        "bounds": (west, south, east, north),
        "lat": float(row.get("lat") or 0.0) if str(row.get("lat") or "").strip() else 0.0,
        "lon": float(row.get("lon") or 0.0) if str(row.get("lon") or "").strip() else 0.0,
    }


def _property_research_geojson_outer_rings(geojson: dict[str, object]) -> list[list[tuple[float, float]]]:
    geometry_type = str(geojson.get("type") or "").strip()
    coordinates = geojson.get("coordinates")
    rings: list[list[tuple[float, float]]] = []
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        polygons = coordinates
    else:
        polygons = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            continue
        outer = polygon[0]
        if not isinstance(outer, list):
            continue
        points: list[tuple[float, float]] = []
        for pair in outer:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                lon = float(pair[0])
                lat = float(pair[1])
            except (TypeError, ValueError):
                continue
            points.append((lon, lat))
        if points:
            rings.append(points)
    return rings


def _property_research_point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    test_x = float(lon)
    test_y = float(lat)
    prev_x, prev_y = ring[-1]
    for curr_x, curr_y in ring:
        intersects = ((curr_y > test_y) != (prev_y > test_y)) and (
            test_x < (prev_x - curr_x) * (test_y - curr_y) / max(prev_y - curr_y, 1e-12) + curr_x
        )
        if intersects:
            inside = not inside
        prev_x, prev_y = curr_x, curr_y
    return inside


def _property_research_point_to_ring_distance_m(lat: float, lon: float, ring: list[tuple[float, float]]) -> float | None:
    if len(ring) < 2:
        return None
    if _property_research_point_in_ring(lat, lon, ring):
        return 0.0

    return _property_research_point_to_ring_boundary_distance_m(lat, lon, ring)


def _property_research_point_to_ring_boundary_distance_m(lat: float, lon: float, ring: list[tuple[float, float]]) -> float | None:
    if len(ring) < 2:
        return None
    lat0_rad = math.radians(float(lat))
    meters_per_lon = 111_320.0 * max(math.cos(lat0_rad), 0.000001)
    meters_per_lat = 111_320.0
    point_x = float(lon) * meters_per_lon
    point_y = float(lat) * meters_per_lat

    min_distance: float | None = None
    points = list(ring)
    if points[0] != points[-1]:
        points.append(points[0])
    for (lon_a, lat_a), (lon_b, lat_b) in zip(points, points[1:]):
        ax = lon_a * meters_per_lon
        ay = lat_a * meters_per_lat
        bx = lon_b * meters_per_lon
        by = lat_b * meters_per_lat
        dx = bx - ax
        dy = by - ay
        segment_len_sq = dx * dx + dy * dy
        if segment_len_sq <= 0.0:
            distance = math.hypot(point_x - ax, point_y - ay)
        else:
            t = ((point_x - ax) * dx + (point_y - ay) * dy) / segment_len_sq
            t = max(0.0, min(1.0, t))
            nearest_x = ax + t * dx
            nearest_y = ay + t * dy
            distance = math.hypot(point_x - nearest_x, point_y - nearest_y)
        if min_distance is None or distance < min_distance:
            min_distance = distance
    return min_distance


def _property_research_point_to_geojson_distance_m(lat: float, lon: float, geojson: dict[str, object]) -> float | None:
    distances = [
        _property_research_point_to_ring_distance_m(lat, lon, ring)
        for ring in _property_research_geojson_outer_rings(dict(geojson or {}))
    ]
    known = [float(distance) for distance in distances if distance is not None]
    if not known:
        return None
    return min(known)


def _property_research_geojson_characteristic_span_m(geojson: dict[str, object]) -> float | None:
    rings = _property_research_geojson_outer_rings(dict(geojson or {}))
    points = [(lon, lat) for ring in rings for lon, lat in ring]
    if not points:
        return None
    min_lon = min(lon for lon, _lat in points)
    max_lon = max(lon for lon, _lat in points)
    min_lat = min(lat for _lon, lat in points)
    max_lat = max(lat for _lon, lat in points)
    mid_lat = (min_lat + max_lat) / 2.0
    width_m = _property_research_distance_m(mid_lat, min_lon, mid_lat, max_lon)
    height_m = _property_research_distance_m(min_lat, min_lon, max_lat, min_lon)
    span_m = min(width_m, height_m)
    return float(span_m) if span_m > 0 else None


def _property_research_point_to_geojson_boundary_distance_m(
    lat: float,
    lon: float,
    geojson: dict[str, object],
) -> float | None:
    distances = [
        _property_research_point_to_ring_boundary_distance_m(lat, lon, ring)
        for ring in _property_research_geojson_outer_rings(dict(geojson or {}))
        if _property_research_point_in_ring(lat, lon, ring)
    ]
    known = [float(distance) for distance in distances if distance is not None]
    if not known:
        return None
    return min(known)


def _property_research_point_to_geojson_interior_ratio(
    lat: float,
    lon: float,
    geojson: dict[str, object],
) -> float | None:
    boundary_distance_m = _property_research_point_to_geojson_boundary_distance_m(lat, lon, geojson)
    characteristic_span_m = _property_research_geojson_characteristic_span_m(geojson)
    if boundary_distance_m is None or not characteristic_span_m:
        return None
    # Normalize by half of the smaller district span: 150m is interior for a
    # compact district much sooner than for a very large one.
    return max(0.0, min(float(boundary_distance_m) / max(float(characteristic_span_m) / 2.0, 1.0), 1.0))

def _property_schoolatlas_wfs_base_url() -> str:
    raw = str(
        os.getenv("EA_PROPERTY_SCHOOLATLAS_WFS_BASE_URL")
        or os.getenv("EA_PROPERTY_STATISTIK_AT_SCHOOLATLAS_WFS_BASE_URL")
        or "https://www.statistik.at/gs-open"
    ).strip()
    return raw.rstrip("/")

@lru_cache(maxsize=64)
def _property_schoolatlas_wfs_json(
    layer_name: str,
    *,
    viewparams: str = "",
    max_features: int = 25000,
    srsname: str = "EPSG:4326",
) -> dict[str, object]:
    base_url = _property_schoolatlas_wfs_base_url()
    if not base_url:
        return {}
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": f"ATLAS_SCHULE_WFS:{str(layer_name or '').strip()}",
        "maxFeatures": str(max(1, int(max_features or 1))),
        "outputFormat": "application/json",
        "srsname": srsname,
    }
    if str(viewparams or "").strip():
        params["viewparams"] = str(viewparams).strip()
    try:
        response = requests.get(
            f"{base_url}/ATLAS_SCHULE_WFS/ows",
            params=params,
            headers={
                **_property_location_research_headers(),
                "User-Agent": _PROPERTY_SCOUT_USER_AGENT,
            },
            timeout=12.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

def _property_schoolatlas_coords_from_facts(facts: dict[str, object] | None) -> tuple[float | None, float | None]:
    payload = dict(facts or {})
    snapshot = (
        dict(payload.get("listing_research_snapshot") or {})
        if isinstance(payload.get("listing_research_snapshot"), dict)
        else {}
    )

    def _pair(source: dict[str, object], lat_key: str, lon_key: str) -> tuple[float | None, float | None]:
        lat_value = _float_or_none(source.get(lat_key))
        lon_value = _float_or_none(source.get(lon_key))
        if lat_value is None or lon_value is None:
            return None, None
        return lat_value, lon_value

    for source, lat_key, lon_key in (
        (payload, "map_lat", "map_lng"),
        (payload, "latitude", "longitude"),
        (payload, "location_latitude", "location_longitude"),
        (snapshot, "map_lat", "map_lng"),
        (snapshot, "latitude", "longitude"),
        (snapshot, "location_latitude", "location_longitude"),
    ):
        lat_value, lon_value = _pair(source, lat_key, lon_key)
        if lat_value is not None and lon_value is not None:
            return lat_value, lon_value
    return None, None

def _property_schoolatlas_transition_capable_school_type(value: object) -> bool:
    normalized = str(value or "").strip().upper()
    return normalized in {"VS", "NMSH", "HS", "AHS", "SS", "ASTAT", "NMSA"}

def _property_schoolatlas_is_gymnasium_destination(properties: dict[str, object]) -> bool:
    haystack = " ".join(
        str(properties.get(key) or "").strip().lower()
        for key in ("KARTO_TYP", "TYP_LAUFEND", "IPUB2_TYP_LAUFEND", "BEZEICHNUNG", "IPUB2_BEZEICHNUNG")
    )
    return any(marker in haystack for marker in ("ahs", "gymnasium", "allgemein bildende höhere", "allgemeinbildende höhere"))

def _property_schoolatlas_distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_m = 6371000.0
    lat1 = math.radians(lat_a)
    lat2 = math.radians(lat_b)
    dlat = math.radians(lat_b - lat_a)
    dlon = math.radians(lon_b - lon_a)
    a = (math.sin(dlat / 2.0) ** 2) + math.cos(lat1) * math.cos(lat2) * (math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius_m * c


def property_school_context_summary(facts: dict[str, object] | None) -> str:
    payload = dict(facts or {})
    return str(
        payload.get("school_atlas_context_summary")
        or payload.get("school_atlas_quality_summary")
        or ""
    ).strip()

def _property_schoolatlas_snapshot(lat: float, lon: float) -> dict[str, object]:
    schools_payload = _property_schoolatlas_wfs_json("ATLAS_SCHULE")
    features = list(schools_payload.get("features") or []) if isinstance(schools_payload, dict) else []
    if not features:
        return {}

    ranked_schools: list[dict[str, object]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = dict(feature.get("geometry") or {}) if isinstance(feature.get("geometry"), dict) else {}
        coordinates = list(geometry.get("coordinates") or []) if isinstance(geometry.get("coordinates"), (list, tuple)) else []
        if len(coordinates) < 2:
            continue
        lon_value = _float_or_none(coordinates[0])
        lat_value = _float_or_none(coordinates[1])
        if lat_value is None or lon_value is None:
            continue
        properties = dict(feature.get("properties") or {}) if isinstance(feature.get("properties"), dict) else {}
        distance_m = _property_schoolatlas_distance_m(lat, lon, lat_value, lon_value)
        ranked_schools.append(
            {
                "distance_m": round(distance_m, 1),
                "lat": lat_value,
                "lon": lon_value,
                "properties": properties,
            }
        )
    if not ranked_schools:
        return {}
    ranked_schools.sort(key=lambda item: float(item.get("distance_m") or 0.0))
    nearby_schools = []
    for item in ranked_schools[:3]:
        properties = dict(item.get("properties") or {})
        nearby_schools.append(
            {
                "name": compact_text(str(properties.get("BEZEICHNUNG") or "").strip(), fallback="School", limit=140),
                "type": str(properties.get("KARTO_TYP") or "").strip(),
                "distance_m": round(float(item.get("distance_m") or 0.0), 1),
                "student_total": int(properties.get("SCHUELER_INSG") or 0),
                "class_total": int(properties.get("KLASSEN") or 0),
                "postcode": str(properties.get("PLZ") or "").strip(),
                "city": str(properties.get("ORT") or "").strip(),
                "street": str(properties.get("STR") or "").strip(),
                "skz": str(properties.get("SKZ") or properties.get("SKZ_LAUFEND") or "").strip(),
            }
        )
    selected = next(
        (
            item
            for item in ranked_schools
            if _property_schoolatlas_transition_capable_school_type(dict(item.get("properties") or {}).get("KARTO_TYP"))
        ),
        ranked_schools[0],
    )
    selected_properties = dict(selected.get("properties") or {})
    selected_skz = str(selected_properties.get("SKZ") or selected_properties.get("SKZ_LAUFEND") or "").strip()
    transition_features: list[dict[str, object]] = []
    if selected_skz:
        transition_payload = _property_schoolatlas_wfs_json(
            "ATLAS_SCHULE_UEBERTRITT_OUT_WFS",
            viewparams=f"SKZ:{selected_skz}",
            max_features=500,
        )
        transition_features = (
            list(transition_payload.get("features") or [])
            if isinstance(transition_payload, dict)
            else []
        )
    known_total = 0
    gym_total = 0
    top_destinations: list[dict[str, object]] = []
    suppressed_destinations = 0
    for feature in transition_features:
        if not isinstance(feature, dict):
            continue
        properties = dict(feature.get("properties") or {}) if isinstance(feature.get("properties"), dict) else {}
        count = int(properties.get("ANZAHL") or 0)
        if count <= 0:
            suppressed_destinations += 1
        else:
            known_total += count
            if _property_schoolatlas_is_gymnasium_destination(properties):
                gym_total += count
        top_destinations.append(
            {
                "name": compact_text(str(properties.get("BEZEICHNUNG") or "").strip(), fallback="School", limit=140),
                "type": str(properties.get("IPUB2_BEZEICHNUNG") or properties.get("TYP_LAUFEND") or properties.get("KARTO_TYP") or "").strip(),
                "count": count,
                "count_label": "≤6" if count <= 0 else str(count),
                "postcode": str(properties.get("PLZ") or "").strip(),
                "city": str(properties.get("ORT") or "").strip(),
                "street": str(properties.get("STR") or "").strip(),
            }
        )
    top_destinations.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    gymnasium_progression_pct = round((gym_total * 100.0) / known_total, 1) if known_total > 0 else ""
    selected_name = compact_text(str(selected_properties.get("BEZEICHNUNG") or "").strip(), fallback="School", limit=140)
    selected_type = str(selected_properties.get("KARTO_TYP") or "").strip()
    selected_distance_m = round(float(selected.get("distance_m") or 0.0), 1)
    quality_summary = (
        f"Nearby SchoolAtlas schools: "
        + "; ".join(
            f"{row['name']} ({row['type'] or 'school'}, {int(float(row['distance_m']))} m, {int(row['student_total'] or 0)} students)"
            for row in nearby_schools
        )
    )
    if known_total > 0:
        progression_summary = (
            f"Nearest transition-capable school {selected_name} ({selected_type or 'school'}, {int(selected_distance_m)} m) "
            f"shows {known_total} disclosed outgoing transitions; about {gymnasium_progression_pct}% lead to Gymnasium/AHS."
        )
    elif transition_features:
        progression_summary = (
            f"Nearest transition-capable school {selected_name} ({selected_type or 'school'}, {int(selected_distance_m)} m) "
            f"has SchoolAtlas transition rows, but counts are suppressed or undisclosed."
        )
    else:
        progression_summary = (
            f"No outgoing SchoolAtlas transition table was available for the nearest transition-capable school "
            f"{selected_name} ({selected_type or 'school'}, {int(selected_distance_m)} m)."
        )
    if suppressed_destinations > 0:
        progression_summary += f" {suppressed_destinations} destination row(s) were only disclosed as ≤6."
    return {
        "school_atlas_context_summary": quality_summary,
        "school_atlas_quality_summary": quality_summary,
        "school_atlas_progression_summary": progression_summary,
        "school_atlas_gymnasium_progression_pct": gymnasium_progression_pct,
        "school_atlas_top_secondary_destinations": top_destinations[:5],
        "school_atlas_nearby_schools": nearby_schools,
        "school_atlas_selected_school": {
            "name": selected_name,
            "type": selected_type,
            "distance_m": selected_distance_m,
            "skz": selected_skz,
        },
        "school_atlas_evidence_type": "hard_public_data",
        "school_atlas_source_url": _PROPERTY_SCHOOLATLAS_SOURCE_URL,
    }


def _property_flowing_water_kind(tags: dict[str, object]) -> str:
    waterway = str(tags.get("waterway") or "").strip().lower()
    natural = str(tags.get("natural") or "").strip().lower()
    water = str(tags.get("water") or "").strip().lower()
    if waterway in {"river", "riverbank"}:
        return "river"
    if waterway == "canal":
        return "canal"
    if waterway in {"stream", "brook"}:
        return "stream"
    if natural == "water" and water in {"river", "riverbank"}:
        return "river"
    if natural == "water" and water == "canal":
        return "canal"
    if natural == "water" and water in {"stream", "brook"}:
        return "stream"
    return ""


def _property_flowing_water_label(kind: object) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized == "river":
        return "river"
    if normalized == "canal":
        return "canal"
    if normalized == "stream":
        return "stream"
    return "flowing water"


def _property_cooling_corridor_signal_for_distance(distance_m: object) -> str:
    distance = _float_or_none(distance_m)
    if not isinstance(distance, float) or distance <= 0.0:
        return ""
    if distance <= 350.0:
        return "strong"
    if distance <= 900.0:
        return "moderate"
    if distance <= 1800.0:
        return "weak"
    return ""


def _property_cooling_corridor_summary(*, name: str, kind: str, distance_m: int) -> str:
    label = compact_text(str(name or "").strip(), fallback=_property_flowing_water_label(kind), limit=80)
    if distance_m <= 350:
        return f"Nearby flowing water ({label}, about {distance_m} m) can soften summer heat and supports the local cooling-corridor read."
    if distance_m <= 900:
        return f"Flowing water ({label}, about {distance_m} m) is close enough to support the local summer cooling read."
    return f"A broader cooling-corridor hint is present because {label} is about {distance_m} m away."


@lru_cache(maxsize=128)
def _property_research_nearby_pois(lat: float, lon: float) -> dict[str, object]:
    query = f"""
[out:json][timeout:20];
(
  node["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="supermarket"](around:5000,{lat:.8f},{lon:.8f});
  node["shop"="convenience"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="convenience"](around:5000,{lat:.8f},{lon:.8f});
  node["shop"="greengrocer"](around:5000,{lat:.8f},{lon:.8f});
  way["shop"="greengrocer"](around:5000,{lat:.8f},{lon:.8f});
  node["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  way["amenity"="pharmacy"](around:5000,{lat:.8f},{lon:.8f});
  node["amenity"="library"](around:5000,{lat:.8f},{lon:.8f});
  way["amenity"="library"](around:5000,{lat:.8f},{lon:.8f});
  node["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  way["leisure"="playground"](around:5000,{lat:.8f},{lon:.8f});
  node["tourism"="zoo"](around:7000,{lat:.8f},{lon:.8f});
  way["tourism"="zoo"](around:7000,{lat:.8f},{lon:.8f});
  node["shop"="doityourself"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="doityourself"](around:7000,{lat:.8f},{lon:.8f});
  node["shop"="hardware"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="hardware"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="marketplace"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="marketplace"](around:7000,{lat:.8f},{lon:.8f});
  node["shop"="mall"](around:7000,{lat:.8f},{lon:.8f});
  way["shop"="mall"](around:7000,{lat:.8f},{lon:.8f});
  node["highway"="pedestrian"](around:7000,{lat:.8f},{lon:.8f});
  way["highway"="pedestrian"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="theatre"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="theatre"](around:7000,{lat:.8f},{lon:.8f});
  node["leisure"="swimming_pool"](around:7000,{lat:.8f},{lon:.8f});
  way["leisure"="swimming_pool"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="doctors"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="doctors"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="clinic"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="clinic"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="hospital"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="hospital"](around:7000,{lat:.8f},{lon:.8f});
  node["brand"~"^starbucks$",i](around:7000,{lat:.8f},{lon:.8f});
  way["brand"~"^starbucks$",i](around:7000,{lat:.8f},{lon:.8f});
  node["name"~"starbucks",i](around:7000,{lat:.8f},{lon:.8f});
  way["name"~"starbucks",i](around:7000,{lat:.8f},{lon:.8f});
  node["leisure"="fitness_centre"](around:7000,{lat:.8f},{lon:.8f});
  way["leisure"="fitness_centre"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="gym"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="gym"](around:7000,{lat:.8f},{lon:.8f});
  node["sport"="fitness"](around:7000,{lat:.8f},{lon:.8f});
  way["sport"="fitness"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="cinema"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="cinema"](around:7000,{lat:.8f},{lon:.8f});
  node["sport"~"^(climbing|bouldering)$"](around:7000,{lat:.8f},{lon:.8f});
  way["sport"~"^(climbing|bouldering)$"](around:7000,{lat:.8f},{lon:.8f});
  node["name"~"boulder",i](around:7000,{lat:.8f},{lon:.8f});
  way["name"~"boulder",i](around:7000,{lat:.8f},{lon:.8f});
  node["leisure"="dog_park"](around:7000,{lat:.8f},{lon:.8f});
  way["leisure"="dog_park"](around:7000,{lat:.8f},{lon:.8f});
  node["amenity"="dog_park"](around:7000,{lat:.8f},{lon:.8f});
  way["amenity"="dog_park"](around:7000,{lat:.8f},{lon:.8f});
  node["railway"="tram_stop"](around:7000,{lat:.8f},{lon:.8f});
  way["railway"="tram_stop"](around:7000,{lat:.8f},{lon:.8f});
  node["highway"="bus_stop"](around:7000,{lat:.8f},{lon:.8f});
  way["highway"="bus_stop"](around:7000,{lat:.8f},{lon:.8f});
  node["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
  way["railway"="subway_entrance"](around:7000,{lat:.8f},{lon:.8f});
  node["waterway"~"^(river|riverbank|canal|stream|brook)$"](around:3500,{lat:.8f},{lon:.8f});
  way["waterway"~"^(river|riverbank|canal|stream|brook)$"](around:3500,{lat:.8f},{lon:.8f});
  relation["waterway"~"^(river|riverbank|canal|stream|brook)$"](around:3500,{lat:.8f},{lon:.8f});
  way["natural"="water"]["water"~"^(river|canal|stream|brook)$"](around:3500,{lat:.8f},{lon:.8f});
  relation["natural"="water"]["water"~"^(river|canal|stream|brook)$"](around:3500,{lat:.8f},{lon:.8f});
);
out center tags;
"""
    try:
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data="data=" + urllib.parse.quote(query, safe=""),
            headers={
                **_property_location_research_headers(),
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return {}
    elements = list(payload.get("elements") or []) if isinstance(payload, dict) else []
    closest: dict[str, dict[str, object]] = {}
    for row in elements:
        if not isinstance(row, dict):
            continue
        tags = dict(row.get("tags") or {})
        point_lat = row.get("lat")
        point_lon = row.get("lon")
        if point_lat is None or point_lon is None:
            center = dict(row.get("center") or {})
            point_lat = center.get("lat")
            point_lon = center.get("lon")
        if not isinstance(point_lat, (int, float)) or not isinstance(point_lon, (int, float)):
            continue
        distance_m = _property_research_distance_m(lat, lon, float(point_lat), float(point_lon))
        if tags.get("shop") in {"supermarket", "convenience", "greengrocer"}:
            metric_key, name_key = "nearest_supermarket_m", "nearest_supermarket_name"
        elif tags.get("amenity") == "pharmacy":
            metric_key, name_key = "nearest_pharmacy_m", "nearest_pharmacy_name"
        elif tags.get("amenity") == "library":
            metric_key, name_key = "nearest_library_m", "nearest_library_name"
        elif tags.get("leisure") == "playground":
            metric_key, name_key = "nearest_playground_m", "nearest_playground_name"
        elif tags.get("tourism") == "zoo":
            metric_key, name_key = "nearest_zoo_m", "nearest_zoo_name"
        elif tags.get("shop") in {"doityourself", "hardware"}:
            metric_key, name_key = "nearest_hardware_store_m", "nearest_hardware_store_name"
        elif tags.get("amenity") == "marketplace":
            metric_key, name_key = "nearest_market_m", "nearest_market_name"
        elif tags.get("shop") == "mall":
            metric_key, name_key = "nearest_shopping_center_m", "nearest_shopping_center_name"
        elif tags.get("highway") == "pedestrian":
            metric_key, name_key = "nearest_shopping_street_m", "nearest_shopping_street_name"
        elif tags.get("amenity") == "theatre":
            metric_key, name_key = "nearest_theatre_m", "nearest_theatre_name"
        elif tags.get("leisure") == "swimming_pool":
            metric_key, name_key = "nearest_public_pool_m", "nearest_public_pool_name"
        elif tags.get("amenity") in {"doctors", "clinic", "hospital"}:
            metric_key, name_key = "nearest_medical_care_m", "nearest_medical_care_name"
        elif str(tags.get("brand") or "").strip().lower() == "starbucks" or "starbucks" in str(tags.get("name") or "").strip().lower():
            metric_key, name_key = "nearest_starbucks_m", "nearest_starbucks_name"
        elif tags.get("leisure") == "fitness_centre" or tags.get("amenity") == "gym" or tags.get("sport") == "fitness":
            metric_key, name_key = "nearest_fitness_center_m", "nearest_fitness_center_name"
        elif tags.get("amenity") == "cinema":
            metric_key, name_key = "nearest_cinema_m", "nearest_cinema_name"
        elif tags.get("sport") in {"climbing", "bouldering"} or "boulder" in str(tags.get("name") or "").strip().lower():
            metric_key, name_key = "nearest_bouldering_m", "nearest_bouldering_name"
        elif tags.get("leisure") == "dog_park" or tags.get("amenity") == "dog_park":
            metric_key, name_key = "nearest_dog_park_m", "nearest_dog_park_name"
        elif tags.get("amenity") == "cafe":
            metric_key, name_key = "nearest_good_cafe_m", "nearest_good_cafe_name"
        elif tags.get("railway") == "tram_stop" or tags.get("highway") == "bus_stop":
            metric_key, name_key = "nearest_tram_bus_m", "nearest_tram_bus_name"
        elif tags.get("railway") == "subway_entrance":
            metric_key, name_key = "nearest_subway_m", "nearest_subway_name"
        elif _property_flowing_water_kind(tags):
            metric_key, name_key = "nearest_flowing_water_m", "nearest_flowing_water_name"
        else:
            continue
        current = closest.get(metric_key)
        if current is None or distance_m < int(current.get("distance_m") or 0):
            closest[metric_key] = {
                "distance_m": distance_m,
                "name": str(tags.get("name") or "").strip(),
                "lat": float(point_lat),
                "lng": float(point_lon),
                "kind": _property_flowing_water_kind(tags),
            }
    result: dict[str, object] = {}
    for key, value in closest.items():
        result[key] = int(value.get("distance_m") or 0)
        prefix = key[:-2] if key.endswith("_m") else key
        result[f"{prefix}_name"] = str(value.get("name") or "").strip()
        result[f"{prefix}_lat"] = float(value.get("lat") or 0.0)
        result[f"{prefix}_lng"] = float(value.get("lng") or 0.0)
        if str(value.get("kind") or "").strip():
            result[f"{prefix}_kind"] = str(value.get("kind") or "").strip()
    flowing_water_distance_m = _float_or_none(result.get("nearest_flowing_water_m"))
    if isinstance(flowing_water_distance_m, float) and flowing_water_distance_m > 0.0:
        signal = _property_cooling_corridor_signal_for_distance(flowing_water_distance_m)
        if signal:
            result["cooling_corridor_signal"] = signal
            result["cooling_corridor_summary"] = _property_cooling_corridor_summary(
                name=str(result.get("nearest_flowing_water_name") or "").strip(),
                kind=str(result.get("nearest_flowing_water_kind") or "").strip(),
                distance_m=int(round(flowing_water_distance_m)),
            )
    return result

def _property_point_looks_like_austria(lat: float, lon: float) -> bool:
    return 46.0 <= float(lat) <= 49.5 and 9.0 <= float(lon) <= 17.5

def _property_official_risk_evidence(
    *,
    lat: float,
    lon: float,
    facts: dict[str, object] | None = None,
) -> dict[str, object]:
    if not _property_point_looks_like_austria(lat, lon):
        return {}
    payload = dict(facts or {})
    postal_name = str(payload.get("postal_name") or "").strip().lower()
    is_vienna = "wien" in postal_name or "vienna" in postal_name
    cooling_corridor_signal = str(payload.get("cooling_corridor_signal") or "").strip().lower()
    cooling_corridor_summary = str(payload.get("cooling_corridor_summary") or "").strip()
    flowing_water_name = compact_text(
        str(payload.get("nearest_flowing_water_name") or "").strip(),
        fallback=_property_flowing_water_label(payload.get("nearest_flowing_water_kind")),
        limit=80,
    )
    flowing_water_distance_m = _float_or_none(payload.get("nearest_flowing_water_m"))
    sources = [
        {
            "risk_key": "heat_resilience",
            "label": "Summer heat",
            "authority_label": "Stadt Wien / data.gv.at",
            "provider": "data.gv.at / Stadt Wien",
            "source_label": "Klimaanalysekarte Wien",
            "source_url": "https://www.data.gv.at/katalog/dataset/stadt-wien_klimaanalysekartewien",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "urban_climate_and_heat_load",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "medium",
            "verification_state": "flagged" if bool(payload.get("heat_resilience_risk")) else "needs_review",
            "summary": "Heat-period comfort should be checked against official urban-climate evidence, not only listing claims.",
            "required_next_step": "Sample the address against the Vienna climate-analysis layer and combine it with floor, orientation, cooling, shading, trees, and facade-shading evidence.",
        },
        {
            "risk_key": "cooling_corridor",
            "label": "Cooling corridor",
            "authority_label": "OpenStreetMap / cached microclimate proxy",
            "provider": "OpenStreetMap / derived proximity evidence",
            "source_label": "Flowing-water proximity",
            "source_url": "https://www.openstreetmap.org/copyright",
            "availability": "derived_proximity_evidence",
            "source_type": "osm_derived",
            "coverage_scope": "microclimate_proxy_flowing_water",
            "refresh_cadence": "osm_public_updates",
            "confidence": "medium" if cooling_corridor_signal in {"strong", "moderate"} else "low",
            "verification_state": "verified" if cooling_corridor_signal in {"strong", "moderate", "weak"} else "needs_review",
            "summary": cooling_corridor_summary
            or (
                f"Nearby flowing water ({flowing_water_name}, about {int(round(flowing_water_distance_m))} m) can support local summer cooling."
                if flowing_water_distance_m
                else "Nearby flowing water can support local summer cooling, but it is a microclimate hint rather than an indoor-comfort guarantee."
            ),
            "required_next_step": "Treat flowing-water proximity as a microclimate hint and combine it with floor, orientation, shade, trees, and building-cooling evidence.",
        },
        {
            "risk_key": "air_quality_risk",
            "label": "Air quality",
            "authority_label": "Umweltbundesamt / Stadt Wien",
            "provider": "data.gv.at / Umweltbundesamt" if not is_vienna else "data.gv.at / Stadt Wien",
            "source_label": "Luftgütemessungen u. meteorologische Messungen" if not is_vienna else "Luftmessnetz: aktuelle Messdaten Wien",
            "source_url": "https://www.data.gv.at/datasets/f2be2752-14cb-47c6-913e-d6fdf26771e0?locale=de" if not is_vienna else "https://www.data.gv.at/datasets/d9ae1245-158e-4d79-86a4-2d9b3defbedc?locale=de",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "station_and_municipal_measurements",
            "refresh_cadence": "recurring_public_updates",
            "confidence": "medium",
            "verification_state": "flagged" if bool(payload.get("air_quality_risk")) else "needs_review",
            "summary": "Official Austrian air-quality measurements should anchor the pollution read for this micro-location.",
            "required_next_step": "Cross-check the nearest station or city network before treating air burden as resolved.",
        },
        {
            "risk_key": "crime_risk",
            "label": "Crime burden",
            "authority_label": "Amtliche Statistik",
            "provider": "data.gv.at / amtliche Statistik",
            "source_label": "Amtliche Statistiken - Kriminalität",
            "source_url": "https://www.data.gv.at/datasets/76d09d69-4258-49e3-88ea-d87668fc30d2?locale=de",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "quarter_or_municipal_statistics",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "medium",
            "verification_state": "flagged" if bool(payload.get("crime_risk")) else "needs_review",
            "summary": "Official crime statistics should be checked before treating quarter-level safety as solved.",
            "required_next_step": "Verify the latest district-level or municipal read before using safety as a final pass/fail reason.",
        },
        {
            "risk_key": "school_evidence",
            "label": "School data",
            "authority_label": "Statistik Austria / municipal school datasets",
            "provider": "STATatlas / data.gv.at",
            "source_label": "SchoolAtlas and municipal school-location data",
            "source_url": "https://www.statistik.at/atlas/",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "school_types_and_locations",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "medium",
            "verification_state": "verified" if bool(property_school_context_summary(payload)) else "needs_review",
            "summary": "Austrian school-fit checks should be anchored in official school-location and school-type evidence, not generic portal claims.",
            "required_next_step": "Attach the nearest school-type evidence and catchment context before clearing family fit.",
        },
        {
            "risk_key": "drinking_water_risk",
            "label": "Water source and groundwater burden",
            "authority_label": "BMLUK",
            "provider": "data.gv.at / BMLUK",
            "source_label": "Grundwasser Aktuell Österreich",
            "source_url": "https://www.data.gv.at/datasets/36b90f02-0f6b-4e94-8d22-d5ba9ac8530b?locale=de",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "national_groundwater_monitoring",
            "refresh_cadence": "recurring_public_updates",
            "confidence": "medium",
            "verification_state": "flagged" if bool(payload.get("drinking_water_risk")) else "needs_review",
            "summary": "Groundwater and water-source evidence should come from the federal monitoring datasets, not only listing copy.",
            "required_next_step": "Check the local water-source and groundwater-monitoring record before assuming the water posture is safe.",
        },
        {
            "risk_key": "flood_risk",
            "label": "Flood exposure",
            "authority_label": "Hochwasserrichtlinie",
            "provider": "data.gv.at / Hochwasserrichtlinie",
            "source_label": "Überflutungsflächen HQ30, HWRL",
            "source_url": "https://www.data.gv.at/datasets/84372374-996a-4d7c-a7ee-9b063d9a7282?locale=de",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "national_flood_zone_mapping",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "high",
            "verification_state": "flagged" if bool(payload.get("flood_risk")) else "needs_review",
            "summary": "Historic flood and runoff checks should use the official HQ30/HWRL flood-zone datasets.",
            "required_next_step": "Overlay the parcel or street block with the official flood-zone evidence before clearing this risk.",
        },
        {
            "risk_key": "noise_risk",
            "label": "Noise exposure",
            "authority_label": "Lärminfo / Umweltbundesamt",
            "provider": "laerminfo.at / Umweltbundesamt",
            "source_label": "Strategic noise mapping",
            "source_url": "https://www.umweltbundesamt.at/mobilitaet/laerm/dashboard",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "road_rail_airport_noise",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "high",
            "verification_state": "flagged" if bool(payload.get("noise_risk")) else "needs_review",
            "summary": "Noise posture should come from Austrian strategic noise maps and corridor exposure checks before it becomes a hard rejection reason.",
            "required_next_step": "Cross-check the street block against the official noise map before clearing this risk.",
        },
        {
            "risk_key": "traffic_density",
            "label": "Traffic burden",
            "authority_label": "Stadt Wien / data.gv.at",
            "provider": "data.gv.at / Stadt Wien",
            "source_label": "Traffic and street exposure evidence",
            "source_url": "https://www.data.gv.at/",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "street_and_corridor_specific",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "medium",
            "verification_state": "flagged" if bool(payload.get("traffic_density_risk")) else "needs_review",
            "summary": "Traffic burden should be checked with official traffic or street-exposure data before it becomes a final ranking penalty.",
            "required_next_step": "Overlay the street block with traffic counts, road class, and noise exposure.",
        },
        {
            "risk_key": "green_shade",
            "label": "Green shade",
            "authority_label": "Stadt Wien / data.gv.at",
            "provider": "data.gv.at / Stadt Wien",
            "source_label": "Urban trees and green-space evidence",
            "source_url": "https://www.data.gv.at/",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "street_trees_and_green_space",
            "refresh_cadence": "periodic_public_updates",
            "confidence": "medium",
            "verification_state": "verified" if bool(payload.get("tree_shade_signal") or payload.get("green_shade_signal")) else "needs_review",
            "summary": "Summer comfort should include real shade and green-space context, especially trees before windows.",
            "required_next_step": "Attach street-tree, park, courtyard, and facade-shade evidence near the windows.",
        },
        {
            "risk_key": "broadband_availability",
            "label": "Broadband availability",
            "authority_label": "Breitbandatlas / RTR",
            "provider": "data.gv.at / RTR",
            "source_label": "Breitbandatlas",
            "source_url": "https://www.data.gv.at/datasets/588b9fdc-d2dd-4628-b186-f7b974065d40?locale=de",
            "availability": "official_dataset",
            "source_type": "official_dataset",
            "coverage_scope": "100m_grid_availability",
            "refresh_cadence": "quarterly_public_updates",
            "confidence": "medium",
            "verification_state": "needs_review",
            "summary": "Home-office viability should be backed by the Austrian broadband and mobile-coverage datasets, not listing adjectives alone.",
            "required_next_step": "Check fixed and mobile availability at the parcel block before clearing internet readiness.",
        },
        {
            "risk_key": "parking_pressure_risk",
            "label": "Parking pressure",
            "authority_label": "Municipal street-parking authority",
            "provider": "municipal parking data",
            "source_label": "Municipal parking-regulation evidence required",
            "source_url": "",
            "availability": "municipal_gap",
            "source_type": "municipal_gap",
            "coverage_scope": "street_and_district_specific",
            "refresh_cadence": "city_specific",
            "confidence": "low",
            "verification_state": "flagged" if bool(payload.get("parking_pressure_risk")) else "source_gap",
            "summary": "There is no shared national parking-pressure dataset here yet; this still needs a municipality-specific street-parking source.",
            "required_next_step": "Attach a municipality-specific parking-zone or resident-parking source before clearing this risk.",
        },
        {
            "risk_key": "winter_access_risk",
            "label": "Winter access",
            "authority_label": "Geosphere / municipal winter service",
            "provider": "official weather / municipal winter-service",
            "source_label": "Geosphere or municipal winter-service evidence required",
            "source_url": "https://www.geosphere.at/",
            "availability": "partial_official",
            "source_type": "partial_official",
            "coverage_scope": "weather_and_local_access_policy",
            "refresh_cadence": "seasonal_and_municipal",
            "confidence": "low",
            "verification_state": "flagged" if bool(payload.get("winter_access_risk")) else "source_gap",
            "summary": "Winter driveability still needs an official weather and municipality-specific access source, not only terrain heuristics.",
            "required_next_step": "Combine Geosphere weather exposure with the municipality winter-service regime before clearing this access risk.",
        },
    ]
    return {
        "country_code": "AT",
        "source_count": len(sources),
        "updated_at": _now_iso(),
        "sources": sources,
    }
