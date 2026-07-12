#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
except Exception:
    PlaywrightTimeoutError = RuntimeError  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.property_tour_runtime_paths import preferred_public_tour_root, running_container_public_tour_dir
except Exception:
    preferred_public_tour_root = None  # type: ignore[assignment]
    running_container_public_tour_dir = None  # type: ignore[assignment]

try:
    from scripts.propertyquarry_playwright_runtime import (
        playwright_chromium_capture_available as _playwright_chromium_capture_available,
        playwright_chromium_executable as _playwright_chromium_executable,
        playwright_chromium_launch_kwargs as _playwright_chromium_launch_kwargs,
    )
except ModuleNotFoundError:
    from propertyquarry_playwright_runtime import (  # type: ignore[no-redef]
        playwright_chromium_capture_available as _playwright_chromium_capture_available,
        playwright_chromium_executable as _playwright_chromium_executable,
        playwright_chromium_launch_kwargs as _playwright_chromium_launch_kwargs,
    )


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIEWER_VERSION = "propertyquarry_3d_tour_viewer_v3"
DISCLOSURE = "Planning preview built from the floor plan and listing photos. Use it as a layout aid, not as a captured tour."
WALKTHROUGH_VIEWPORT_SIZE = (1280, 720)
WALKTHROUGH_CARD_SIZE = (1440, 810)
WALKTHROUGH_MAP_BOX = (988, 222, 1332, 452)
THREE_VENDOR_VERSION = "0.167.1"
THREE_VENDOR_ROOT = ROOT / "vendor" / "three" / THREE_VENDOR_VERSION
THREE_MODULE_SOURCE = THREE_VENDOR_ROOT / "three.module.js"
ORBIT_CONTROLS_SOURCE = THREE_VENDOR_ROOT / "examples" / "jsm" / "controls" / "OrbitControls.js"
_PREVIEW_FONT_PATHS = {
    ("sans", False): Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("sans", True): Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("serif", False): Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    ("serif", True): Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
}
_PREVIEW_FONT_CACHE: dict[tuple[str, bool, int], ImageFont.ImageFont] = {}


def _compact_route_label(value: object, *, fallback: str = "", limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return fallback
    return text[:limit].strip() or fallback


def _route_detail_base_label(value: object) -> str:
    label = _compact_route_label(value)
    if not label:
        return ""
    return re.sub(r"\s+detail\s+\d+\s*$", "", label, flags=re.IGNORECASE).strip()


def _env_flag(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _numeric_room_count(value: object) -> int:
    try:
        if value in (None, "", False):
            return 0
        parsed = float(str(value).replace(",", ".").strip())
    except Exception:
        return 0
    if parsed <= 0:
        return 0
    return max(1, min(25, int(parsed) if float(parsed).is_integer() else int(math.ceil(parsed))))


def _positive_item_count(value: object) -> int:
    try:
        if value in (None, "", False):
            return 0
        parsed = int(float(str(value).strip()))
    except Exception:
        return 0
    return parsed if parsed > 0 else 0


def _extract_room_count_from_text(text: object) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    patterns = (
        r"\b(\d+(?:[.,]\d+)?)\s*[- ]?\s*(?:zimmer|room|rooms|bedroom|bedrooms)\b",
        r"\b(?:zimmer|rooms?|bedrooms?)\s*[:：]?\s*(\d+(?:[.,]\d+)?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        count = _numeric_room_count(match.group(1))
        if count > 0:
            return count
    return 0


def _append_unique_route_label(labels: list[str], value: object) -> None:
    label = _compact_route_label(value)
    if not label:
        return
    lowered = label.lower()
    if lowered in {item.lower() for item in labels}:
        return
    labels.append(label)


def _reconstruction_walkthrough_route_labels(
    payload: dict[str, object],
    *,
    explicit_labels: list[str] | tuple[str, ...] = (),
    explicit_room_count: int = 0,
) -> list[str]:
    labels: list[str] = []
    for raw_label in list(explicit_labels or []):
        _append_unique_route_label(labels, raw_label)
    if labels:
        return labels

    walkable_scene = dict(payload.get("walkable_scene") or {}) if isinstance(payload.get("walkable_scene"), dict) else {}
    for collection_key in ("route", "rooms"):
        for raw_item in list(walkable_scene.get(collection_key) or []):
            if not isinstance(raw_item, dict):
                continue
            _append_unique_route_label(labels, raw_item.get("label") or raw_item.get("room") or raw_item.get("name"))
    for collection_key in ("room_visit_plan", "covered_route_labels"):
        for raw_label in list(payload.get(collection_key) or []):
            _append_unique_route_label(labels, raw_label)
    if labels:
        return labels

    facts = dict(payload.get("facts") or {}) if isinstance(payload.get("facts"), dict) else {}
    teaser_attributes = [
        str(item).strip()
        for item in list(facts.get("teaser_attributes") or [])
        if str(item).strip()
    ]
    text_blob = " ".join(
        part
        for part in (
            payload.get("title"),
            payload.get("display_title"),
            payload.get("tour_title"),
            facts.get("title"),
            facts.get("listing_title"),
            facts.get("summary"),
            facts.get("description"),
            facts.get("rooms_label"),
            " ".join(teaser_attributes),
        )
        if str(part or "").strip()
    )
    lowered_text = text_blob.lower()
    media = dict(payload.get("media") or {}) if isinstance(payload.get("media"), dict) else {}
    source_photos = dict(media.get("source_photos") or {}) if isinstance(media.get("source_photos"), dict) else {}
    source_photo_count = max(
        _positive_item_count(source_photos.get("count")),
        _positive_item_count(payload.get("photo_count")),
    )
    scenes = list(payload.get("scenes") or [])
    if scenes:
        source_photo_count = max(
            source_photo_count,
            len(
                [
                    row
                    for row in scenes
                    if isinstance(row, dict) and str(row.get("role") or "").strip().lower() == "photo"
                ]
            ),
        )
    base_room_count = _numeric_room_count(facts.get("room_count") or facts.get("rooms")) or _extract_room_count_from_text(text_blob)
    if explicit_room_count > 0:
        base_room_count = max(base_room_count, _numeric_room_count(explicit_room_count))

    has_hall = bool(re.search(r"\b(hallway|hall|foyer|entry|entryway|eingang|vorraum|flur)\b", lowered_text))
    has_kitchen = bool(re.search(r"\b(wohnkueche|wohnküche|küche|kueche|kitchen)\b", lowered_text))
    has_bathroom = bool(re.search(r"\b(bathroom|badezimmer|bad)\b", lowered_text))
    has_toilet = bool(re.search(r"\b(separate[rsn]*\s+wc|separate[rsn]*\s+toilet|wc|w\.?c\.?|toilette|toilet)\b", lowered_text))
    has_storage = bool(re.search(r"\b(storage|storeroom|store room|utility room|abstellraum)\b", lowered_text))
    has_dining = bool(re.search(r"\b(dining room|dining|esszimmer)\b", lowered_text))
    has_outdoor = bool(re.search(r"\b(balcony|balkon|loggia|terrace|terrasse|dachterrasse)\b", lowered_text))
    has_outdoor = has_outdoor or any(
        bool(facts.get(key))
        for key in ("has_balcony", "has_terrace", "has_loggia", "balcony", "terrace", "loggia")
    )
    has_staircase = bool(
        re.search(
            r"\b(maisonette|duplex|split[- ]level|mezzanine|gallery|gallerie|stairs?|staircase|treppe|stiege|two floors?|two levels?|2 stockwerke|zwei stockwerke)\b",
            lowered_text,
        )
    )

    if has_hall or base_room_count > 0 or any((has_kitchen, has_bathroom, has_toilet, has_storage, has_outdoor, has_staircase)):
        _append_unique_route_label(labels, "entry/hall")
    if has_staircase:
        _append_unique_route_label(labels, "staircase")
    if has_storage:
        _append_unique_route_label(labels, "storage room")
    if has_bathroom:
        _append_unique_route_label(labels, "bath/WC")
    separate_toilet = has_toilet and ("separate" in lowered_text or "extra wc" in lowered_text or "gäste wc" in lowered_text or not has_bathroom)
    if separate_toilet:
        _append_unique_route_label(labels, "toilet")
    if has_kitchen:
        _append_unique_route_label(labels, "living kitchen")
    if base_room_count >= 1:
        _append_unique_route_label(labels, "living room")
    if base_room_count >= 2:
        _append_unique_route_label(labels, "bedroom")
    for bedroom_index in range(2, max(1, base_room_count - 1) + 1):
        _append_unique_route_label(labels, f"bedroom {bedroom_index}")
    if has_dining and not has_kitchen:
        _append_unique_route_label(labels, "dining room")
    if has_outdoor:
        _append_unique_route_label(labels, "balcony/terrace")
    if labels and source_photo_count > 0:
        route_kinds = {_route_label_kind(label) for label in labels}
        has_core_interior = bool(route_kinds & {"living", "kitchen", "dining", "bedroom", "generic"})
        if not has_core_interior:
            enriched_labels: list[str] = []
            if "entry" in route_kinds or source_photo_count >= 2 or bool(facts.get("has_floorplan")) or has_outdoor:
                _append_unique_route_label(enriched_labels, "entry/hall")
            if "stairs" in route_kinds:
                _append_unique_route_label(enriched_labels, "staircase")
            if "storage" in route_kinds:
                _append_unique_route_label(enriched_labels, "storage room")
            _append_unique_route_label(enriched_labels, "living area")
            if source_photo_count >= 4:
                _append_unique_route_label(enriched_labels, "sleeping area")
            if "bath" in route_kinds or source_photo_count >= 6:
                _append_unique_route_label(enriched_labels, "bath/WC")
            if "toilet" in route_kinds:
                _append_unique_route_label(enriched_labels, "toilet")
            if "outdoor" in route_kinds or has_outdoor:
                _append_unique_route_label(enriched_labels, "balcony/terrace")
            labels = enriched_labels
    if labels:
        return labels

    if source_photo_count > 0:
        if source_photo_count >= 2 or bool(facts.get("has_floorplan")) or has_outdoor:
            _append_unique_route_label(labels, "entry/hall")
        _append_unique_route_label(labels, "living area")
        if source_photo_count >= 4:
            _append_unique_route_label(labels, "sleeping area")
        if source_photo_count >= 6:
            _append_unique_route_label(labels, "bath/WC")
        if has_outdoor:
            _append_unique_route_label(labels, "balcony/terrace")
    if labels:
        return labels

    fallback_room_count = max(base_room_count, _numeric_room_count(explicit_room_count))
    if fallback_room_count <= 0:
        fallback_room_count = 1
    return [f"room stop {index}" for index in range(1, fallback_room_count + 1)]


def _route_label_kind(label: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(label or "").strip().lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return "generic"
    if any(token in normalized for token in ("entry", "hall", "foyer", "vorraum", "flur")):
        return "entry"
    if any(token in normalized for token in ("stair", "treppe", "stiege", "duplex", "maisonette", "mezzanine", "split level")):
        return "stairs"
    if any(token in normalized for token in ("bath", "bad", "badezimmer")):
        return "bath"
    if any(token in normalized for token in ("toilet", "wc")):
        return "toilet"
    if any(token in normalized for token in ("storage", "abstell")):
        return "storage"
    if any(token in normalized for token in ("balcony", "terrace", "balkon", "terrasse", "loggia")):
        return "outdoor"
    if any(token in normalized for token in ("kitchen", "kuche", "küche", "wohnkuche", "wohnküche")):
        return "kitchen"
    if any(token in normalized for token in ("dining", "esszimmer")):
        return "dining"
    if any(token in normalized for token in ("bedroom", "schlaf")):
        return "bedroom"
    if "living" in normalized or "wohn" in normalized:
        return "living"
    return "generic"


def _walkthrough_stop_labels(
    route_labels: list[str] | tuple[str, ...],
    *,
    target_stop_count: int = 0,
) -> list[str]:
    base_labels = [
        _compact_route_label(label)
        for label in list(route_labels or [])
        if _compact_route_label(label)
    ]
    if not base_labels:
        base_labels = ["room stop 1"]
    target_count = max(len(base_labels), max(0, int(target_stop_count or 0)))
    if target_count <= len(base_labels):
        return base_labels

    labels = list(base_labels)
    repeatable_kinds = {"living", "kitchen", "dining", "bedroom", "bath", "outdoor", "generic"}
    repeat_pool = [label for label in base_labels if _route_label_kind(label) in repeatable_kinds]
    if not repeat_pool:
        repeat_pool = [label for label in base_labels if _route_label_kind(label) not in {"entry", "stairs", "storage", "toilet"}]
    if not repeat_pool:
        repeat_pool = list(base_labels)
    label_counts = {label: 1 for label in base_labels}
    repeat_index = 0
    while len(labels) < target_count:
        base_label = repeat_pool[repeat_index % len(repeat_pool)]
        repeat_index += 1
        label_counts[base_label] = label_counts.get(base_label, 1) + 1
        labels.append(f"{base_label} detail {label_counts[base_label]}")
    return labels


def _viewer_storyboard_steps(
    expected_segments: list[str] | tuple[str, ...],
    *,
    route_stops: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized_segments = [
        _compact_route_label(label, fallback=f"Stop {index + 1}")
        for index, label in enumerate(list(expected_segments or []))
    ]
    if not normalized_segments or not route_stops:
        return []

    route_index_by_label: dict[str, int] = {}
    for index, stop in enumerate(route_stops):
        label = _compact_route_label(stop.get("label") or stop.get("room") or stop.get("name"))
        if not label:
            continue
        route_index_by_label.setdefault(label.lower(), index)
        base_label = _route_detail_base_label(label)
        if base_label:
            route_index_by_label.setdefault(base_label.lower(), index)

    steps: list[dict[str, object]] = []
    visit_counts: dict[int, int] = {}
    last_route_index = 0
    total = len(normalized_segments)
    for sequence, label in enumerate(normalized_segments, start=1):
        normalized_label = label.lower()
        route_index = route_index_by_label.get(normalized_label)
        if route_index is None:
            route_index = route_index_by_label.get(_route_detail_base_label(label).lower())
        if route_index is None:
            route_index = min(max(0, sequence - 1), len(route_stops) - 1)
        last_route_index = route_index if route_index >= 0 else last_route_index
        variant = visit_counts.get(last_route_index, 0)
        visit_counts[last_route_index] = variant + 1
        steps.append(
            {
                "label": label,
                "sequence": sequence,
                "total": total,
                "state": {
                    "viewMode": "room",
                    "routeIndex": last_route_index,
                    "variant": variant,
                },
            }
        )
    return steps


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _route_anchor_from_floorplan_mask(
    *,
    desired_x: float,
    desired_z: float,
    wall_mask: list[list[int]],
    used_cells: set[tuple[int, int]],
) -> tuple[float, float] | None:
    rows = len(wall_mask)
    cols = len(wall_mask[0]) if rows else 0
    if not rows or not cols:
        return None

    def _open_neighbor_count(row: int, col: int, radius: int = 2) -> int:
        open_neighbors = 0
        for near_row in range(max(0, row - radius), min(rows, row + radius + 1)):
            for near_col in range(max(0, col - radius), min(cols, col + radius + 1)):
                if near_row == row and near_col == col:
                    continue
                if not wall_mask[near_row][near_col]:
                    open_neighbors += 1
        return open_neighbors

    candidates: list[tuple[float, int, int]] = []
    for row in range(rows):
        for col in range(cols):
            if wall_mask[row][col]:
                continue
            if (row, col) in used_cells:
                continue
            candidate_x = ((col + 0.5) / cols) - 0.5
            candidate_z = ((row + 0.5) / rows) - 0.5
            distance = math.dist((candidate_x, candidate_z), (desired_x, desired_z))
            clearance_bonus = _open_neighbor_count(row, col) * 0.012
            edge_penalty = 0.0
            if row in {0, rows - 1} or col in {0, cols - 1}:
                edge_penalty = 0.16
            candidates.append((distance - clearance_bonus + edge_penalty, row, col))
    if not candidates:
        return None
    _, selected_row, selected_col = min(candidates, key=lambda item: item[0])
    used_cells.add((selected_row, selected_col))
    return (((selected_col + 0.5) / cols) - 0.5, ((selected_row + 0.5) / rows) - 0.5)


def _reconstruction_walkable_scene(
    *,
    route_labels: list[str] | tuple[str, ...],
    width_m: float,
    depth_m: float,
    height_m: float,
    geometry: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_labels = [
        _compact_route_label(label)
        for label in list(route_labels or [])
        if _compact_route_label(label)
    ]
    if not normalized_labels:
        normalized_labels = ["entry/hall"]
    inner_width = max(1.2, width_m * 0.34)
    inner_depth = max(1.2, depth_m * 0.34)
    semantic_anchors: dict[str, tuple[float, float]] = {
        "entry": (-0.28, 0.30),
        "stairs": (-0.08, 0.10),
        "bath": (-0.26, -0.26),
        "toilet": (-0.12, -0.28),
        "storage": (-0.30, -0.10),
        "kitchen": (0.10, 0.14),
        "living": (0.20, 0.00),
        "dining": (0.28, -0.04),
        "bedroom": (0.24, -0.24),
        "outdoor": (0.34, -0.34),
        "generic": (0.00, 0.00),
    }
    fallback_anchors: list[tuple[float, float]] = [
        (-0.28, 0.26),
        (-0.10, 0.18),
        (0.14, 0.12),
        (0.26, 0.00),
        (0.22, -0.18),
        (0.00, -0.26),
        (-0.22, -0.18),
    ]
    wall_mask = (
        [list(row) for row in list((geometry or {}).get("wall_mask") or []) if isinstance(row, list)]
        if isinstance(geometry, dict)
        else []
    )
    stop_positions: list[tuple[float, float]] = []
    used_positions: list[tuple[float, float]] = []
    used_floorplan_cells: set[tuple[int, int]] = set()
    for index, label in enumerate(normalized_labels):
        kind = _route_label_kind(label)
        base_x, base_z = semantic_anchors.get(kind, semantic_anchors["generic"])
        if kind == "bedroom":
            bedroom_offset = min(0.18, 0.12 * sum(1 for prior in normalized_labels[:index] if _route_label_kind(prior) == "bedroom"))
            base_x = max(-0.32, base_x - bedroom_offset)
        elif kind == "generic":
            base_x, base_z = fallback_anchors[index % len(fallback_anchors)]
        floorplan_anchor = _route_anchor_from_floorplan_mask(
            desired_x=base_x,
            desired_z=base_z,
            wall_mask=wall_mask,
            used_cells=used_floorplan_cells,
        )
        if floorplan_anchor is not None:
            base_x, base_z = floorplan_anchor
        candidate = (base_x, base_z)
        if any(abs(candidate[0] - used_x) < 0.06 and abs(candidate[1] - used_z) < 0.06 for used_x, used_z in used_positions):
            fallback_x, fallback_z = fallback_anchors[index % len(fallback_anchors)]
            candidate = (fallback_x, fallback_z)
        used_positions.append(candidate)
        stop_positions.append(candidate)

    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    route: list[dict[str, object]] = []
    rooms: list[dict[str, object]] = []
    eye_y = round(max(1.45, min(height_m * 0.58, height_m - 0.3)), 3)
    target_y = round(max(1.2, min(height_m * 0.5, eye_y - 0.18)), 3)
    for index, (label, (nx, nz)) in enumerate(zip(normalized_labels, stop_positions), start=1):
        kind = _route_label_kind(label)
        focus_x = round(nx * inner_width, 3)
        focus_z = round(nz * inner_depth, 3)
        offset_x = 0.72 if focus_x < 0 else -0.72
        offset_z = 0.92 if focus_z < 0.18 else 0.58
        camera_x = round(_clamp(focus_x + offset_x, -(width_m * 0.42), width_m * 0.42), 3)
        camera_z = round(_clamp(focus_z + offset_z, -(depth_m * 0.42), depth_m * 0.42), 3)
        stop = {
            "label": label,
            "room": label,
            "name": label,
            "kind": kind,
            "sequence": index,
            "focus": {"x": focus_x, "y": target_y, "z": focus_z},
            "camera": {"x": camera_x, "y": eye_y, "z": camera_z},
        }
        route.append(stop)
        rooms.append(
            {
                "label": label,
                "name": label,
                "kind": kind,
                "sequence": index,
                "position": {"x": focus_x, "y": 0.0, "z": focus_z},
                "focus": {"x": focus_x, "y": target_y, "z": focus_z},
            }
        )
    return {
        "kind": "generated_reconstruction_layout",
        "bounds": {"width_m": round(width_m, 3), "depth_m": round(depth_m, 3), "height_m": round(height_m, 3)},
        "rooms": rooms,
        "route": route,
    }


def _generated_reconstruction_photo_reference_panels(
    *,
    photos: list[dict[str, object]],
    walkable_scene: dict[str, object],
    width_m: float,
    depth_m: float,
    height_m: float,
) -> list[dict[str, object]]:
    if not photos:
        return []
    route_stops = [dict(stop) for stop in list(walkable_scene.get("route") or []) if isinstance(stop, dict)]
    panels: list[dict[str, object]] = []
    side_counts = {"north": 0, "south": 0, "east": 0, "west": 0}
    secondary_offsets = (0.0, -0.95, 0.95, -1.7, 1.7, -2.45, 2.45)
    mount_y = round(max(1.42, min(height_m * 0.58, height_m - 0.62)), 3)

    for index, row in enumerate(photos):
        if not isinstance(row, dict):
            continue
        relpath = str(row.get("relpath") or "").strip()
        if not relpath:
            continue
        if route_stops:
            stop_index = min(
                max(0, int((index * len(route_stops)) / max(1, len(photos)))),
                max(0, len(route_stops) - 1),
            )
        else:
            stop_index = -1
        stop = route_stops[stop_index] if stop_index >= 0 else {}
        focus = dict(stop.get("focus") or {}) if isinstance(stop.get("focus"), dict) else {}
        focus_x = _clamp_float(float(focus.get("x") or 0.0), -(width_m * 0.28), width_m * 0.28)
        focus_z = _clamp_float(float(focus.get("z") or 0.0), -(depth_m * 0.28), depth_m * 0.28)
        label = _compact_route_label(
            stop.get("label") or stop.get("room") or stop.get("name"),
            fallback=f"Room reference {len(panels) + 1}",
        )
        kind = _route_label_kind(label)
        photo_width_px = max(1, int(row.get("width") or 1))
        photo_height_px = max(1, int(row.get("height") or 1))
        aspect_ratio = _clamp_float(photo_width_px / photo_height_px, 0.75, 1.85)
        photo_height = round(_clamp_float(1.04, 0.92, 1.18), 3)
        photo_width = round(_clamp_float(photo_height * aspect_ratio, 1.0, 1.82), 3)
        frame_width = round(photo_width + 0.18, 3)
        frame_height = round(photo_height + 0.26, 3)

        if abs(focus_x / max(width_m, 1.0)) > abs(focus_z / max(depth_m, 1.0)):
            wall_side = "east" if focus_x >= 0 else "west"
        else:
            wall_side = "south" if focus_z >= 0 else "north"
        side_index = side_counts[wall_side]
        side_counts[wall_side] += 1
        offset = secondary_offsets[side_index % len(secondary_offsets)]

        if wall_side in {"east", "west"}:
            secondary_span = max(0.0, (depth_m * 0.34) - (photo_width * 0.42))
            panel_z = round(_clamp_float(focus_z + offset, -secondary_span, secondary_span), 3)
            panel_x = round((width_m * 0.5) - 0.08, 3) * (1 if wall_side == "east" else -1)
            rotation_y = round(-math.pi / 2 if wall_side == "east" else math.pi / 2, 6)
            panel_position = {"x": panel_x, "y": mount_y, "z": panel_z}
        else:
            secondary_span = max(0.0, (width_m * 0.34) - (photo_width * 0.42))
            panel_x = round(_clamp_float(focus_x + offset, -secondary_span, secondary_span), 3)
            panel_z = round((depth_m * 0.5) - 0.08, 3) * (1 if wall_side == "south" else -1)
            rotation_y = round(math.pi if wall_side == "south" else 0.0, 6)
            panel_position = {"x": panel_x, "y": mount_y, "z": panel_z}

        panels.append(
            {
                "index": len(panels) + 1,
                "label": label,
                "kind": kind,
                "route_index": stop_index,
                "photo_relpath": relpath,
                "photo_width": photo_width,
                "photo_height": photo_height,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "wall_side": wall_side,
                "position": panel_position,
                "rotation_y": rotation_y,
            }
        )
    return panels


def _generated_reconstruction_diorama_palette(style_label: str) -> dict[str, tuple[int, int, int]]:
    normalized = str(style_label or "").strip().lower()
    if normalized and any(
        marker in normalized
        for marker in ("moody", "dark", "night", "charcoal", "walnut", "cinematic", "industrial")
    ):
        return {
            "wash": (50, 45, 43),
            "floorplan_wash": (70, 66, 63),
            "matte": (247, 242, 234),
            "accent": (189, 145, 63),
            "accent_soft": (255, 248, 236),
        }
    if normalized and any(
        marker in normalized
        for marker in ("scandi", "minimal", "minimalist", "nordic", "airy", "cool", "blue", "modern")
    ):
        return {
            "wash": (226, 233, 240),
            "floorplan_wash": (238, 241, 244),
            "matte": (248, 249, 247),
            "accent": (111, 140, 172),
            "accent_soft": (242, 247, 252),
        }
    if normalized and any(
        marker in normalized
        for marker in ("vintage", "mid century", "mid-century", "earth", "terracotta", "retro")
    ):
        return {
            "wash": (232, 219, 202),
            "floorplan_wash": (241, 232, 221),
            "matte": (249, 242, 235),
            "accent": (170, 109, 72),
            "accent_soft": (255, 246, 238),
        }
    return {
        "wash": (245, 240, 232),
        "floorplan_wash": (242, 235, 226),
        "matte": (251, 247, 241),
        "accent": (186, 139, 51),
        "accent_soft": (255, 250, 240),
    }


def _preview_font(size: int, *, bold: bool = False, serif: bool = False) -> ImageFont.ImageFont:
    family = "serif" if serif else "sans"
    normalized_size = max(10, int(size))
    cache_key = (family, bool(bold), normalized_size)
    cached = _PREVIEW_FONT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    font_path = _PREVIEW_FONT_PATHS[(family, bool(bold))]
    try:
        if font_path.is_file():
            font = ImageFont.truetype(str(font_path), normalized_size)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _PREVIEW_FONT_CACHE[cache_key] = font
    return font


def _text_width(font: ImageFont.ImageFont, text: object) -> float:
    normalized = str(text or "")
    try:
        return float(font.getlength(normalized))  # type: ignore[attr-defined]
    except Exception:
        bbox = font.getbbox(normalized)
        return float(max(0, bbox[2] - bbox[0]))


def _line_height(font: ImageFont.ImageFont, *, leading: float = 1.18) -> int:
    try:
        bbox = font.getbbox("Ag")
        height = max(1, bbox[3] - bbox[1])
    except Exception:
        height = max(1, int(getattr(font, "size", 12) or 12))
    return max(1, int(round(height * leading)))


def _wrap_text(text: object, *, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = [segment for segment in re.split(r"\s+", str(text or "").strip()) if segment]
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(font, candidate) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    text: object,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
    max_width: int,
    line_gap: int = 4,
) -> int:
    lines = _wrap_text(text, font=font, max_width=max_width)
    x, y = origin
    step = _line_height(font)
    for index, line in enumerate(lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += step + (line_gap if index + 1 < len(lines) else 0)
    return y


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    text: object,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), str(text or ""), font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(
        (center[0] - (width / 2) - bbox[0], center[1] - (height / 2) - bbox[1]),
        str(text or ""),
        font=font,
        fill=fill,
    )


def _draw_text_chip(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    text: object,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
    outline: tuple[int, int, int] | tuple[int, int, int, int],
    text_fill: tuple[int, int, int] | tuple[int, int, int, int],
    radius: int = 18,
    pad_x: int = 14,
    pad_y: int = 8,
    outline_width: int = 2,
) -> tuple[int, int, int, int]:
    label = str(text or "").strip()
    bbox = draw.textbbox((0, 0), label, font=font)
    width = (bbox[2] - bbox[0]) + (pad_x * 2)
    height = (bbox[3] - bbox[1]) + (pad_y * 2)
    x, y = origin
    box = (x, y, x + width, y + height)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=outline_width)
    draw.text((x + pad_x, y + pad_y - bbox[1]), label, font=font, fill=text_fill)
    return box


@contextmanager
def _serve_directory(root: Path):
    class _QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for_playwright_condition(page, predicate: str, *, timeout_ms: int = 15_000) -> None:
    deadline = time.monotonic() + (max(int(timeout_ms), 1) / 1000)
    while time.monotonic() < deadline:
        try:
            if bool(page.evaluate(predicate)):
                return
        except Exception:
            pass
        page.wait_for_timeout(250)
    raise TimeoutError("playwright_condition_timeout")


def _decorate_viewer_walkthrough_frame(
    image: Image.Image,
    *,
    label: str,
    sequence: int,
    total: int,
    style_label: str = "",
    floorplan_thumb: Image.Image | None = None,
    route_markers: list[dict[str, object]] | None = None,
) -> Image.Image:
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    palette = _generated_reconstruction_diorama_palette(style_label)
    eyebrow_font = _preview_font(16, bold=True)
    label_font = _preview_font(30, serif=True, bold=True)
    meta_font = _preview_font(15)
    chip_font = _preview_font(14, bold=True)
    panel_heading_font = _preview_font(16, bold=True)
    progress_number_font = _preview_font(14, bold=True)

    top_box = (26, 24, 332, 116)
    draw.rounded_rectangle(top_box, radius=22, fill=(247, 241, 232, 216), outline=(216, 202, 176, 255), width=2)
    draw.text((46, 42), "Layout flythrough", font=eyebrow_font, fill=(66, 52, 31))
    draw.text((46, 66), "Planning preview", font=label_font, fill=(48, 38, 24))

    progress_box = (canvas.width - 388, canvas.height - 138, canvas.width - 28, canvas.height - 28)
    draw.rounded_rectangle(progress_box, radius=24, fill=(24, 19, 14, 196), outline=(255, 255, 255, 48), width=2)
    draw.text((progress_box[0] + 20, progress_box[1] + 18), "Room route", font=eyebrow_font, fill=(250, 244, 235, 212))
    _draw_wrapped_text(
        draw,
        (progress_box[0] + 20, progress_box[1] + 42),
        label,
        font=label_font,
        fill=(251, 246, 239),
        max_width=progress_box[2] - progress_box[0] - 40,
        line_gap=0,
    )
    draw.text(
        (progress_box[0] + 20, progress_box[3] - 34),
        f"Stop {max(1, sequence)} of {max(1, total)}",
        font=meta_font,
        fill=(250, 244, 235, 214),
    )
    if style_label:
        _draw_text_chip(
            draw,
            (progress_box[0] + 20, progress_box[1] - 28),
            style_label,
            font=chip_font,
            fill=(255, 252, 245, 228),
            outline=(216, 202, 176, 255),
            text_fill=(96, 72, 38),
            radius=16,
            pad_x=12,
            pad_y=6,
            outline_width=2,
        )

    normalized_markers = [dict(marker) for marker in list(route_markers or []) if isinstance(marker, dict)]
    if floorplan_thumb is not None and normalized_markers:
        route_panel_box = (canvas.width - 392, 24, canvas.width - 28, 350)
        draw.rounded_rectangle(
            route_panel_box,
            radius=28,
            fill=(251, 247, 241, 228),
            outline=(216, 202, 176, 255),
            width=2,
        )
        draw.text((route_panel_box[0] + 20, route_panel_box[1] + 18), "Route map", font=panel_heading_font, fill=(45, 38, 28))
        route_map = _walkthrough_route_map_inset(
            floorplan_thumb=floorplan_thumb,
            route_markers=normalized_markers,
            active_index=max(0, min(max(0, sequence) - 1, max(0, len(normalized_markers) - 1))),
            palette=palette,
        )
        route_map_anchor = (route_panel_box[0] + 18, route_panel_box[1] + 48)
        draw.rounded_rectangle(
            (
                route_map_anchor[0] - 6,
                route_map_anchor[1] - 6,
                route_map_anchor[0] + route_map.width + 6,
                route_map_anchor[1] + route_map.height + 6,
            ),
            radius=22,
            fill=(255, 252, 245, 234),
            outline=(216, 202, 176, 255),
            width=2,
        )
        canvas.alpha_composite(route_map.convert("RGBA"), route_map_anchor)
        draw.text((route_panel_box[0] + 20, route_panel_box[1] + 292), "Current stop", font=panel_heading_font, fill=(45, 38, 28))
        _draw_wrapped_text(
            draw,
            (route_panel_box[0] + 20, route_panel_box[1] + 314),
            label,
            font=meta_font,
            fill=(96, 72, 38),
            max_width=route_panel_box[2] - route_panel_box[0] - 40,
            line_gap=0,
        )
        progress_left = route_panel_box[0] + 20
        progress_right = route_panel_box[2] - 24
        progress_y = route_panel_box[3] - 30
        if total > 1:
            draw.line((progress_left, progress_y, progress_right, progress_y), fill=(214, 202, 180), width=4)
        for index in range(max(1, total)):
            if total <= 1:
                cx = (progress_left + progress_right) / 2
            else:
                cx = progress_left + ((progress_right - progress_left) * index / max(total - 1, 1))
            fill = palette["accent"] if index < max(1, sequence) else (255, 252, 245)
            outline = (138, 97, 23) if index + 1 == max(1, sequence) else (167, 124, 43)
            radius = 8 if index + 1 == max(1, sequence) else 6
            draw.ellipse((cx - radius, progress_y - radius, cx + radius, progress_y + radius), fill=fill, outline=outline, width=3)
            _draw_centered_text(
                draw,
                (cx, progress_y - 18),
                str(index + 1),
                font=progress_number_font,
                fill=(75, 57, 35),
            )
    return canvas.convert("RGB")


def _generated_reconstruction_fit_cover(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        return ImageOps.fit(normalized, size, Image.Resampling.LANCZOS)


def _generated_reconstruction_mount_card(
    image: Image.Image,
    *,
    max_size: tuple[int, int],
    frame_px: int,
    rotate_degrees: float = 0.0,
    matte_color: tuple[int, int, int] = (250, 247, 242),
    shadow_alpha: int = 84,
) -> Image.Image:
    rendered = image.convert("RGB")
    rendered.thumbnail(max_size, Image.Resampling.LANCZOS)
    framed = Image.new("RGBA", (rendered.width + (frame_px * 2), rendered.height + (frame_px * 2)), (0, 0, 0, 0))
    matte = Image.new("RGBA", framed.size, (*matte_color, 255))
    framed.alpha_composite(matte)
    framed.paste(rendered, (frame_px, frame_px))
    shadow = Image.new("RGBA", (framed.width + 64, framed.height + 64), (0, 0, 0, 0))
    shadow_block = Image.new("RGBA", framed.size, (24, 22, 20, shadow_alpha))
    shadow.alpha_composite(shadow_block, (26, 30))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    composite = Image.new(
        "RGBA",
        (max(shadow.width, framed.width), max(shadow.height, framed.height)),
        (0, 0, 0, 0),
    )
    composite.alpha_composite(shadow)
    composite.alpha_composite(framed)
    if rotate_degrees:
        composite = composite.rotate(rotate_degrees, resample=Image.Resampling.BICUBIC, expand=True)
    return composite


def _generated_reconstruction_floorplan_with_route(
    floorplan_path: Path,
    *,
    walkable_scene: dict[str, object],
    size: tuple[int, int],
    palette: dict[str, tuple[int, int, int]],
) -> Image.Image:
    floorplan = _generated_reconstruction_fit_cover(floorplan_path, size)
    floorplan = Image.blend(floorplan, Image.new("RGB", floorplan.size, palette["floorplan_wash"]), 0.12)
    draw = ImageDraw.Draw(floorplan)
    marker_font = _preview_font(max(16, int(round(min(size) * 0.026))), bold=True)
    route_stops = [dict(stop) for stop in list(walkable_scene.get("route") or []) if isinstance(stop, dict)]
    bounds = dict(walkable_scene.get("bounds") or {}) if isinstance(walkable_scene, dict) else {}
    width_m = max(0.001, float(bounds.get("width_m") or 0.0))
    depth_m = max(0.001, float(bounds.get("depth_m") or 0.0))
    if not route_stops:
        return floorplan
    margin_x = max(46, int(round(size[0] * 0.065)))
    margin_y = max(38, int(round(size[1] * 0.075)))
    radius = max(12, int(round(min(size) * 0.02)))
    previous_point: tuple[int, int] | None = None
    for index, stop in enumerate(route_stops[:8], start=1):
        focus = dict(stop.get("focus") or {}) if isinstance(stop.get("focus"), dict) else {}
        x_pct = _clamp_float((((float(focus.get("x") or 0.0) / width_m) + 0.5) * 100.0), 8.0, 92.0)
        y_pct = _clamp_float((((float(focus.get("z") or 0.0) / depth_m) + 0.5) * 100.0), 10.0, 90.0)
        marker_x = int(round(margin_x + ((size[0] - (margin_x * 2)) * x_pct / 100.0)))
        marker_y = int(round(margin_y + ((size[1] - (margin_y * 2)) * y_pct / 100.0)))
        point = (marker_x, marker_y)
        if previous_point is not None:
            draw.line((previous_point[0], previous_point[1], point[0], point[1]), fill=palette["accent"], width=6)
        draw.ellipse(
            (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
            fill=palette["accent_soft"],
            outline=palette["accent"],
            width=5,
        )
        _draw_centered_text(
            draw,
            (marker_x, marker_y),
            str(index),
            font=marker_font,
            fill=(96, 72, 38),
        )
        previous_point = point
    return floorplan


def _write_generated_reconstruction_diorama_preview(
    output_path: Path,
    *,
    floorplan_path: Path,
    photo_paths: list[Path],
    walkable_scene: dict[str, object],
    style_label: str = "",
) -> dict[str, object]:
    palette = _generated_reconstruction_diorama_palette(style_label)
    route_stops = [dict(stop) for stop in list(walkable_scene.get("route") or []) if isinstance(stop, dict)]
    route_labels = [
        _compact_route_label(stop.get("label") or stop.get("room") or stop.get("name"), fallback=f"Stop {index + 1}", limit=22)
        for index, stop in enumerate(route_stops[:4])
    ]
    route_copy = "  •  ".join(label for label in route_labels if label)
    route_stop_count = max(1, len(route_stops))
    photo_count = len(photo_paths)
    preview_sources = list(photo_paths[:3]) or [floorplan_path]
    try:
        eyebrow_font = _preview_font(22, bold=True)
        title_font = _preview_font(58, serif=True, bold=True)
        body_font = _preview_font(22)
        chip_font = _preview_font(20, bold=True)
        rail_heading_font = _preview_font(24, bold=True)
        rail_label_font = _preview_font(26, serif=True, bold=True)
        rail_copy_font = _preview_font(18)
        stat_value_font = _preview_font(28, serif=True, bold=True)
        stat_label_font = _preview_font(15, bold=True)
        footer_font = _preview_font(20)
        route_strip_font = _preview_font(20, bold=True)
        hero_background = _generated_reconstruction_fit_cover(preview_sources[0], (1600, 1100))
        floorplan_stage_image = _generated_reconstruction_floorplan_with_route(
            floorplan_path,
            walkable_scene=walkable_scene,
            size=(1160, 700),
            palette=palette,
        )
        canvas = Image.new("RGBA", (1600, 1100), (*palette["wash"], 255))
        background = hero_background.filter(ImageFilter.GaussianBlur(18))
        background = Image.blend(background, Image.new("RGB", canvas.size, palette["wash"]), 0.82)
        canvas.alpha_composite(background.convert("RGBA"))
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((62, 54, 612, 412), fill=(255, 255, 255, 42))
        draw.ellipse((980, 88, 1538, 468), fill=(255, 255, 255, 28))

        title_box = (74, 70, 620, 268)
        draw.rounded_rectangle(
            title_box,
            radius=34,
            fill=(255, 252, 245, 218),
            outline=(216, 202, 176, 255),
            width=2,
        )
        draw.text((102, 98), "Generated diorama", font=eyebrow_font, fill=(96, 72, 38))
        draw.text((102, 126), "Layout-first", font=title_font, fill=(42, 35, 26))
        draw.text((102, 184), "room route", font=title_font, fill=(42, 35, 26))
        body_bottom = _draw_wrapped_text(
            draw,
            (104, 246),
            "Perspective staging from the floor plan and listing photos.",
            font=body_font,
            fill=(84, 66, 40),
            max_width=468,
        )
        chip_y = max(220, body_bottom + 12)
        first_chip = _draw_text_chip(
            draw,
            (102, chip_y),
            f"{route_stop_count} route stops",
            font=chip_font,
            fill=(255, 248, 236, 228),
            outline=(216, 202, 176, 255),
            text_fill=(96, 72, 38),
        )
        second_chip = _draw_text_chip(
            draw,
            (first_chip[2] + 10, chip_y),
            f"{photo_count} source photos",
            font=chip_font,
            fill=(255, 252, 245, 222),
            outline=(216, 202, 176, 255),
            text_fill=(96, 72, 38),
        )
        if style_label:
            _draw_text_chip(
                draw,
                (second_chip[2] + 10, chip_y),
                style_label,
                font=chip_font,
                fill=(*palette["accent_soft"], 236),
                outline=palette["accent"],
                text_fill=(96, 72, 38),
            )

        stage_surface = Image.new(
            "RGBA",
            (floorplan_stage_image.width + 64, floorplan_stage_image.height + 112),
            (*palette["matte"], 255),
        )
        stage_surface.paste(floorplan_stage_image, (32, 32))
        stage_draw = ImageDraw.Draw(stage_surface)
        stage_draw.rounded_rectangle(
            (10, 10, stage_surface.width - 11, stage_surface.height - 11),
            radius=34,
            outline=(216, 202, 176, 255),
            width=3,
        )
        if route_copy:
            strip_top = stage_surface.height - 64
            stage_draw.rounded_rectangle(
                (34, strip_top - 14, stage_surface.width - 34, stage_surface.height - 28),
                radius=22,
                fill=(255, 252, 245, 230),
                outline=(216, 202, 176, 255),
                width=2,
            )
            stage_draw.text((56, strip_top), route_copy, font=route_strip_font, fill=(78, 61, 36))

        stage_depth_fill = Image.blend(
            stage_surface.convert("RGB"),
            Image.new("RGB", stage_surface.size, (126, 108, 82)),
            0.58,
        ).convert("RGBA")
        stage_depth_draw = ImageDraw.Draw(stage_depth_fill)
        stage_depth_draw.rectangle(
            (0, stage_surface.height - 18, stage_surface.width, stage_surface.height),
            fill=(*palette["accent"], 235),
        )
        stage_shadow = Image.new(
            "RGBA",
            (stage_surface.width + 160, stage_surface.height + 180),
            (0, 0, 0, 0),
        )
        stage_shadow.alpha_composite(
            Image.new("RGBA", stage_surface.size, (28, 24, 20, 72)),
            (58, 92),
        )
        stage_shadow = stage_shadow.filter(ImageFilter.GaussianBlur(28))
        stage_stack = Image.new("RGBA", stage_shadow.size, (0, 0, 0, 0))
        stage_stack.alpha_composite(stage_shadow)
        stage_stack.alpha_composite(stage_depth_fill, (34, 54))
        stage_stack.alpha_composite(stage_surface, (0, 0))
        rotated_stage = stage_stack.rotate(-6.5, resample=Image.Resampling.BICUBIC, expand=True)
        canvas.alpha_composite(rotated_stage, (92, 292))

        panel_specs = [
            {"size": (286, 198), "rotate": -7.0, "anchor": (148, 312)},
            {"size": (420, 292), "rotate": 1.6, "anchor": (590, 74)},
            {"size": (300, 210), "rotate": 6.4, "anchor": (1162, 176)},
        ]
        for index, source_path in enumerate(preview_sources[: len(panel_specs)]):
            spec = panel_specs[index]
            panel_card = _generated_reconstruction_mount_card(
                _generated_reconstruction_fit_cover(source_path, spec["size"]),
                max_size=spec["size"],
                frame_px=16 if index == 1 else 14,
                rotate_degrees=float(spec["rotate"]),
                matte_color=palette["matte"],
                shadow_alpha=92 if index == 1 else 78,
            )
            anchor_x, anchor_y = spec["anchor"]
            canvas.alpha_composite(panel_card, (anchor_x, anchor_y))

        route_rail_box = (1162, 556, 1494, 930)
        draw.rounded_rectangle(
            route_rail_box,
            radius=34,
            fill=(255, 252, 245, 224),
            outline=(216, 202, 176, 255),
            width=2,
        )
        draw.text((1188, 584), "Route sequence", font=rail_heading_font, fill=(45, 38, 28))
        draw.text((1188, 614), "The launch opens on a guided room route.", font=rail_copy_font, fill=(96, 72, 38))
        route_row_top = 658
        for index, label in enumerate(route_labels or ["Route overview"]):
            row_top = route_row_top + (index * 58)
            row_box = (1186, row_top, 1468, row_top + 48)
            draw.rounded_rectangle(
                row_box,
                radius=20,
                fill=(255, 252, 245, 238 if index == 0 else 214),
                outline=(216, 202, 176, 255),
                width=2,
            )
            badge_center = (1216, row_top + 24)
            draw.ellipse(
                (badge_center[0] - 16, badge_center[1] - 16, badge_center[0] + 16, badge_center[1] + 16),
                fill=(*palette["accent_soft"], 255),
                outline=palette["accent"],
                width=3,
            )
            _draw_centered_text(draw, badge_center, str(index + 1), font=chip_font, fill=(96, 72, 38))
            draw.text((1244, row_top + 11), label, font=rail_label_font, fill=(45, 38, 28))

        stats_top = 842
        stats = [
            (str(route_stop_count), "route stops"),
            (str(photo_count), "source photos"),
            ("1", "diorama hero"),
        ]
        for index, (value, label) in enumerate(stats):
            card_left = 1186 + (index * 94)
            card_right = min(route_rail_box[2] - 26, card_left + 86)
            stat_box = (card_left, stats_top, card_right, stats_top + 68)
            draw.rounded_rectangle(
                stat_box,
                radius=18,
                fill=(*palette["accent_soft"], 228 if index == 0 else 212),
                outline=(216, 202, 176, 255),
                width=2,
            )
            draw.text((card_left + 14, stats_top + 10), value, font=stat_value_font, fill=(45, 38, 28))
            _draw_wrapped_text(
                draw,
                (card_left + 14, stats_top + 38),
                label,
                font=stat_label_font,
                fill=(96, 72, 38),
                max_width=card_right - card_left - 24,
                line_gap=1,
            )

        footer_box = (148, 1004, 1452, 1062)
        draw.rounded_rectangle(
            footer_box,
            radius=24,
            fill=(255, 252, 245, 222),
            outline=(216, 202, 176, 255),
            width=2,
        )
        footer_copy = "Generated from the floor plan and listing photos. Use it as a layout-first briefing image, not as a captured tour."
        _draw_wrapped_text(
            draw,
            (footer_box[0] + 24, footer_box[1] + 16),
            footer_copy,
            font=footer_font,
            fill=(84, 66, 40),
            max_width=(footer_box[2] - footer_box[0]) - 48,
            line_gap=2,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, format="PNG", optimize=True)
        return {
            "status": "generated",
            "bundle_relpath": output_path.name,
            "sha256": _sha256(output_path),
            "size_bytes": output_path.stat().st_size,
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def _write_generated_reconstruction_telegram_preview(
    output_path: Path,
    *,
    source_path: Path,
    style_label: str = "",
) -> dict[str, object]:
    palette = _generated_reconstruction_diorama_palette(style_label)
    try:
        with Image.open(source_path) as image:
            base = ImageOps.exif_transpose(image).convert("RGB")
            width, height = base.size
            canvas_width = max(int(round(width * 1.62)), width + 220)
            canvas_height = max(int(round(height * 1.62)), height + 220)
            background = ImageOps.fit(base, (canvas_width, canvas_height), Image.Resampling.LANCZOS)
            background = background.filter(ImageFilter.GaussianBlur(18))
            background = Image.blend(background, Image.new("RGB", background.size, palette["wash"]), 0.78)
            scale = min((canvas_width * 0.52) / max(width, 1), (canvas_height * 0.52) / max(height, 1))
            scaled = base.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                Image.Resampling.LANCZOS,
            )
            canvas = background
            offset_x = (canvas_width - scaled.size[0]) // 2
            offset_y = (canvas_height - scaled.size[1]) // 2
            canvas.paste(scaled, (offset_x, offset_y))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(output_path, format="PNG", optimize=True)
        return {
            "status": "generated",
            "bundle_relpath": output_path.name,
            "sha256": _sha256(output_path),
            "size_bytes": output_path.stat().st_size,
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


def _walkthrough_route_map_inset(
    *,
    floorplan_thumb: Image.Image | None,
    route_markers: list[dict[str, object]],
    active_index: int,
    palette: dict[str, tuple[int, int, int]],
) -> Image.Image:
    map_width = max(1, WALKTHROUGH_MAP_BOX[2] - WALKTHROUGH_MAP_BOX[0])
    map_height = max(1, WALKTHROUGH_MAP_BOX[3] - WALKTHROUGH_MAP_BOX[1])
    if floorplan_thumb is not None:
        inset = ImageOps.fit(floorplan_thumb.copy(), (map_width, map_height), Image.Resampling.LANCZOS)
        inset = Image.blend(inset, Image.new("RGB", inset.size, palette["floorplan_wash"]), 0.12)
    else:
        inset = Image.new("RGB", (map_width, map_height), palette["floorplan_wash"])
    draw = ImageDraw.Draw(inset)
    previous_point: tuple[int, int] | None = None
    for index, marker in enumerate(route_markers):
        marker_x = int(round((_clamp_float(float(marker.get("x_pct") or 0.0), 0.0, 100.0) / 100.0) * (map_width - 1)))
        marker_y = int(round((_clamp_float(float(marker.get("y_pct") or 0.0), 0.0, 100.0) / 100.0) * (map_height - 1)))
        point = (marker_x, marker_y)
        if previous_point is not None:
            draw.line((previous_point[0], previous_point[1], point[0], point[1]), fill=palette["accent"], width=5)
        radius = 11 if index == active_index else 8
        fill = palette["accent_soft"] if index <= active_index else (255, 252, 245)
        outline = palette["accent"] if index == active_index else (167, 124, 43)
        draw.ellipse(
            (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
            fill=fill,
            outline=outline,
            width=4,
        )
        draw.text((marker_x - 5, marker_y - 7), str(index + 1), fill=palette["accent"])
        previous_point = point
    return inset


def _walkthrough_floorplan_thumb(floorplan_image: Path | None) -> Image.Image | None:
    if floorplan_image is None or not floorplan_image.exists():
        return None
    map_width = max(1, WALKTHROUGH_MAP_BOX[2] - WALKTHROUGH_MAP_BOX[0])
    map_height = max(1, WALKTHROUGH_MAP_BOX[3] - WALKTHROUGH_MAP_BOX[1])
    with Image.open(floorplan_image) as image:
        floorplan_thumb = ImageOps.exif_transpose(image).convert("RGB")
        return ImageOps.fit(floorplan_thumb, (map_width, map_height), Image.Resampling.LANCZOS)


def _walkthrough_route_markers(
    expected_segments: list[str] | tuple[str, ...],
    *,
    walkable_scene: dict[str, object] | None,
) -> list[dict[str, object]]:
    route_stops = (
        [dict(stop) for stop in list((walkable_scene or {}).get("route") or []) if isinstance(stop, dict)]
        if isinstance(walkable_scene, dict)
        else []
    )
    bounds = dict((walkable_scene or {}).get("bounds") or {}) if isinstance(walkable_scene, dict) else {}
    bound_width = max(0.001, float(bounds.get("width_m") or 0.0))
    bound_depth = max(0.001, float(bounds.get("depth_m") or 0.0))
    route_markers: list[dict[str, object]] = []
    for index, label in enumerate(list(expected_segments or [])):
        stop = route_stops[index] if index < len(route_stops) else {}
        focus = dict(stop.get("focus") or {}) if isinstance(stop.get("focus"), dict) else {}
        if focus:
            marker_x = _clamp_float((((float(focus.get("x") or 0.0) / bound_width) + 0.5) * 100.0), 10.0, 90.0)
            marker_y = _clamp_float((((float(focus.get("z") or 0.0) / bound_depth) + 0.5) * 100.0), 12.0, 88.0)
        else:
            denominator = max(1, len(expected_segments) - 1)
            marker_x = 16.0 + ((68.0 / denominator) * index if denominator else 34.0)
            marker_y = 52.0 + (8.0 if index % 2 else -8.0)
        route_markers.append({"label": label, "x_pct": marker_x, "y_pct": marker_y})
    return route_markers


def _render_walkthrough_stop_card(
    *,
    stop_index: int,
    label: str,
    expected_segments: list[str],
    source_path: Path,
    supporting_path: Path | None,
    floorplan_thumb: Image.Image | None,
    route_markers: list[dict[str, object]],
    style_label: str = "",
) -> Image.Image:
    card_w, card_h = WALKTHROUGH_CARD_SIZE
    palette = _generated_reconstruction_diorama_palette(style_label)
    eyebrow_font = _preview_font(22, bold=True)
    headline_font = _preview_font(52, serif=True, bold=True)
    meta_font = _preview_font(20, bold=True)
    body_font = _preview_font(20)
    panel_heading_font = _preview_font(23, bold=True)
    panel_label_font = _preview_font(26, serif=True, bold=True)
    footer_font = _preview_font(18)
    chip_font = _preview_font(18, bold=True)
    progress_number_font = _preview_font(16, bold=True)
    hero_source = _generated_reconstruction_fit_cover(source_path, (card_w, card_h))
    background = hero_source.filter(ImageFilter.GaussianBlur(24))
    background = Image.blend(background, Image.new("RGB", (card_w, card_h), palette["wash"]), 0.76)
    card = background.convert("RGBA")
    draw = ImageDraw.Draw(card)
    draw.rectangle((0, 0, card_w - 1, 128), fill=(251, 247, 241, 218))
    draw.rectangle((0, card_h - 104, card_w - 1, card_h - 1), fill=(247, 241, 232, 228))
    draw.rectangle((0, 0, card_w - 1, card_h - 1), outline=(216, 202, 176, 255), width=3)
    header_box = (52, 28, 720, 142)
    draw.rounded_rectangle(
        header_box,
        radius=30,
        fill=(251, 247, 241, 230),
        outline=(216, 202, 176, 255),
        width=2,
    )
    draw.text((76, 48), "Layout walkthrough", font=eyebrow_font, fill=(45, 38, 28))
    draw.text((76, 74), label, font=headline_font, fill=(45, 38, 28))
    stop_chip = _draw_text_chip(
        draw,
        (530, 46),
        f"Stop {stop_index + 1} of {len(expected_segments)}",
        font=chip_font,
        fill=(*palette["accent_soft"], 236),
        outline=palette["accent"],
        text_fill=(96, 72, 38),
    )
    if style_label:
        _draw_text_chip(
            draw,
            (stop_chip[0], stop_chip[3] + 10),
            style_label,
            font=chip_font,
            fill=(255, 252, 245, 224),
            outline=(216, 202, 176, 255),
            text_fill=(96, 72, 38),
        )

    hero_card = _generated_reconstruction_mount_card(
        _generated_reconstruction_fit_cover(source_path, (820, 500)),
        max_size=(820, 500),
        frame_px=18,
        rotate_degrees=-2.8 if stop_index % 2 == 0 else 2.8,
        matte_color=palette["matte"],
        shadow_alpha=92,
    )
    hero_anchor_x = 72
    hero_anchor_y = 170
    card.alpha_composite(hero_card, (hero_anchor_x, hero_anchor_y))

    if supporting_path is not None and supporting_path.exists():
        supporting_card = _generated_reconstruction_mount_card(
            _generated_reconstruction_fit_cover(supporting_path, (276, 188)),
            max_size=(276, 188),
            frame_px=12,
            rotate_degrees=7.5 if stop_index % 2 == 0 else -7.5,
            matte_color=palette["matte"],
            shadow_alpha=78,
        )
        support_x = 664
        support_y = 470
        card.alpha_composite(supporting_card, (support_x, support_y))

    panel_box = (952, 146, 1368, 638)
    draw.rounded_rectangle(panel_box, radius=30, fill=(255, 252, 245, 228), outline=(216, 202, 176, 255), width=3)
    draw.text((984, 176), "Route map", font=panel_heading_font, fill=(45, 38, 28))
    route_map = _walkthrough_route_map_inset(
        floorplan_thumb=floorplan_thumb,
        route_markers=route_markers,
        active_index=stop_index,
        palette=palette,
    )
    route_map_anchor = (WALKTHROUGH_MAP_BOX[0], WALKTHROUGH_MAP_BOX[1])
    draw.rounded_rectangle(
        (WALKTHROUGH_MAP_BOX[0] - 8, WALKTHROUGH_MAP_BOX[1] - 8, WALKTHROUGH_MAP_BOX[2] + 8, WALKTHROUGH_MAP_BOX[3] + 8),
        radius=24,
        fill=(251, 247, 241, 230),
        outline=(216, 202, 176, 255),
        width=2,
    )
    card.alpha_composite(route_map.convert("RGBA"), route_map_anchor)

    draw.text((984, 476), "Current stop", font=panel_heading_font, fill=(45, 38, 28))
    draw.text((984, 508), label, font=panel_label_font, fill=(96, 72, 38))

    progress_left = 984
    progress_right = 1334
    progress_y = 596
    if len(expected_segments) > 1:
        draw.line((progress_left, progress_y, progress_right, progress_y), fill=(214, 202, 180), width=4)
    for index, _segment in enumerate(expected_segments):
        if len(expected_segments) == 1:
            cx = (progress_left + progress_right) / 2
        else:
            cx = progress_left + ((progress_right - progress_left) * index / max(len(expected_segments) - 1, 1))
        fill = palette["accent"] if index <= stop_index else (255, 252, 245)
        outline = (138, 97, 23) if index == stop_index else (167, 124, 43)
        radius = 10 if index == stop_index else 7
        draw.ellipse((cx - radius, progress_y - radius, cx + radius, progress_y + radius), fill=fill, outline=outline, width=3)
        _draw_centered_text(draw, (cx, progress_y + 26), str(index + 1), font=progress_number_font, fill=(75, 57, 35))

    previous_label = expected_segments[stop_index - 1] if stop_index > 0 else "Arrival"
    next_label = expected_segments[stop_index + 1] if stop_index + 1 < len(expected_segments) else "Tour complete"
    info_box = (984, 648, 1340, 744)
    draw.rounded_rectangle(info_box, radius=20, fill=(255, 252, 245, 220), outline=(216, 202, 176, 255), width=2)
    draw.text((info_box[0] + 16, info_box[1] + 14), f"From: {previous_label}", font=meta_font, fill=(96, 72, 38))
    draw.text((info_box[0] + 16, info_box[1] + 42), f"Next: {next_label}", font=meta_font, fill=(96, 72, 38))
    _draw_wrapped_text(
        draw,
        (info_box[0] + 16, info_box[1] + 72),
        "Guided by the floor plan and listing photos.",
        font=body_font,
        fill=(96, 72, 38),
        max_width=info_box[2] - info_box[0] - 32,
        line_gap=2,
    )

    _draw_wrapped_text(
        draw,
        (76, card_h - 72),
        "Planning preview from source media. Confirm exact finishes, size, and sightlines at the viewing.",
        font=footer_font,
        fill=(96, 72, 38),
        max_width=1020,
        line_gap=2,
    )
    return card.convert("RGB")


def _upsert_public_asset(
    payload: dict[str, object],
    *,
    relpath: str,
    role: str,
    privacy_class: str = "public",
    mime_type: str = "",
) -> None:
    normalized_relpath = _safe_relpath(relpath)
    if not normalized_relpath:
        return
    public_assets = list(payload.get("public_assets") or []) if isinstance(payload.get("public_assets"), list) else []
    for row in public_assets:
        if isinstance(row, dict) and any(
            str(row.get(key) or "").strip() == normalized_relpath
            for key in ("path", "relpath", "asset_relpath")
        ):
            row["path"] = normalized_relpath
            row["privacy_class"] = privacy_class
            row["role"] = role
            if mime_type:
                row["mime_type"] = mime_type
            payload["public_assets"] = public_assets
            return
    public_assets.append(
        {
            "path": normalized_relpath,
            "privacy_class": privacy_class,
            "role": role,
            **({"mime_type": mime_type} if mime_type else {}),
        }
    )
    payload["public_assets"] = public_assets


def _upsert_diorama_scene(payload: dict[str, object], *, relpath: str) -> None:
    normalized_relpath = _safe_relpath(relpath)
    if not normalized_relpath:
        return
    scenes = [dict(scene) for scene in list(payload.get("scenes") or []) if isinstance(scene, dict)]
    inserted = False
    for scene in scenes:
        if str(scene.get("role") or "").strip().lower() != "diorama":
            continue
        scene["name"] = "Layout diorama"
        scene["role"] = "diorama"
        scene["ordinal"] = 0
        scene["mime_type"] = "image/png"
        scene["asset_relpath"] = normalized_relpath
        inserted = True
        break
    if not inserted:
        scenes.insert(
            0,
            {
                "name": "Layout diorama",
                "role": "diorama",
                "ordinal": 0,
                "mime_type": "image/png",
                "asset_relpath": normalized_relpath,
            },
        )
    payload["scenes"] = scenes


def _public_tour_dir() -> Path:
    configured = str(os.getenv("EA_PUBLIC_TOUR_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if running_container_public_tour_dir is not None:
        runtime_root = running_container_public_tour_dir(os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or "")
        if isinstance(runtime_root, Path):
            return runtime_root.expanduser().resolve()
    if preferred_public_tour_root is not None:
        return preferred_public_tour_root(
            configured_root="",
            repo_root=ROOT,
            fallback_root=ROOT / "state" / "public_property_tours",
            runtime_container=os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or "",
        )
    cwd = Path.cwd().resolve()
    if cwd.name == "property" and (cwd / "state" / "public_property_tours").exists():
        return (cwd / "state" / "public_property_tours").resolve()
    return Path("/data/public_property_tours").expanduser().resolve()


def _runtime_publish_required() -> bool:
    if _env_flag("PROPERTYQUARRY_RECONSTRUCTION_ALLOW_LOCAL_ONLY"):
        return False
    if _env_flag("PROPERTYQUARRY_RECONSTRUCTION_REQUIRE_RUNTIME_PUBLISH"):
        return True
    if str(os.getenv("EA_ROLE") or "").strip().lower() != "render-tools":
        return False
    try:
        configured_public_root = Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or "").strip() or "/data/public_property_tours").expanduser().resolve()
    except OSError:
        configured_public_root = Path("/data/public_property_tours")
    return configured_public_root != Path("/data/public_property_tours").resolve()


def _runtime_publish_succeeded(receipt: dict[str, object]) -> bool:
    return str(receipt.get("status") or "").strip() == "updated"


def _sync_bundle_to_runtime_container(bundle_dir: Path, *, slug: str) -> dict[str, object]:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {"status": "docker_unavailable", "slug": slug}
    container = str(os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or "propertyquarry-api").strip()
    if not container:
        return {"status": "runtime_container_missing", "slug": slug}
    normalized_bundle = bundle_dir.expanduser().resolve()
    if not normalized_bundle.is_dir():
        return {"status": "bundle_missing", "slug": slug, "bundle_dir": str(normalized_bundle)}
    remote_bundle = f"/data/public_property_tours/{slug}"
    try:
        mkdir_timeout_seconds = max(
            2.0,
            float(str(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_RUNTIME_MKDIR_TIMEOUT_SECONDS") or "8").strip() or "8"),
        )
    except Exception:
        mkdir_timeout_seconds = 8.0
    try:
        copy_timeout_seconds = max(
            5.0,
            float(str(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_RUNTIME_COPY_TIMEOUT_SECONDS") or "30").strip() or "30"),
        )
    except Exception:
        copy_timeout_seconds = 30.0
    try:
        mkdir_result = subprocess.run(
            [docker_bin, "exec", container, "mkdir", "-p", remote_bundle],
            check=False,
            capture_output=True,
            text=True,
            timeout=mkdir_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "runtime_mkdir_timeout",
            "slug": slug,
            "container": container,
            "timeout_seconds": exc.timeout,
        }
    if mkdir_result.returncode != 0:
        return {
            "status": "runtime_mkdir_failed",
            "slug": slug,
            "container": container,
            "stderr": (mkdir_result.stderr or "").strip()[-400:],
        }
    try:
        copy_result = subprocess.run(
            [docker_bin, "cp", f"{normalized_bundle}/.", f"{container}:{remote_bundle}/"],
            check=False,
            capture_output=True,
            text=True,
            timeout=copy_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "runtime_copy_timeout",
            "slug": slug,
            "container": container,
            "timeout_seconds": exc.timeout,
        }
    if copy_result.returncode != 0:
        return {
            "status": "runtime_copy_failed",
            "slug": slug,
            "container": container,
            "stderr": (copy_result.stderr or "").strip()[-400:],
        }
    return {"status": "updated", "slug": slug, "container": container}


def _safe_relpath(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return "/".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _web_safe_image_suffix(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix in {".tif", ".tiff"}:
        return ".jpg"
    return suffix or ".jpg"


def _image_metadata(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        return {
            "width": int(image.width),
            "height": int(image.height),
            "mode": str(image.mode),
        }


def _copy_normalized_image(source: Path, target: Path) -> dict[str, object]:
    if source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise SystemExit(f"unsupported_image_extension:{source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        normalized.save(target, format="JPEG" if target.suffix.lower() in {".jpg", ".jpeg"} else None, quality=90)
    metadata = _image_metadata(target)
    return {
        "source_path": str(source),
        "relpath": target.name,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
        **metadata,
    }


def _connected_components(mask: list[list[int]]) -> list[dict[str, object]]:
    rows = len(mask)
    cols = len(mask[0]) if rows else 0
    visited = [[False for _ in range(cols)] for _ in range(rows)]
    components: list[dict[str, object]] = []
    for row in range(rows):
        for col in range(cols):
            if not mask[row][col] or visited[row][col]:
                continue
            queue = [(col, row)]
            visited[row][col] = True
            area = 0
            min_col = max_col = col
            min_row = max_row = row
            touches_edge = col in {0, cols - 1} or row in {0, rows - 1}
            while queue:
                current_col, current_row = queue.pop()
                area += 1
                min_col = min(min_col, current_col)
                max_col = max(max_col, current_col)
                min_row = min(min_row, current_row)
                max_row = max(max_row, current_row)
                for next_col, next_row in (
                    (current_col + 1, current_row),
                    (current_col - 1, current_row),
                    (current_col, current_row + 1),
                    (current_col, current_row - 1),
                ):
                    if (
                        0 <= next_col < cols
                        and 0 <= next_row < rows
                        and mask[next_row][next_col]
                        and not visited[next_row][next_col]
                    ):
                        visited[next_row][next_col] = True
                        queue.append((next_col, next_row))
                        if next_col in {0, cols - 1} or next_row in {0, rows - 1}:
                            touches_edge = True
            components.append(
                {
                    "area": area,
                    "bbox": (min_col, min_row, max_col, max_row),
                    "touches_edge": touches_edge,
                }
            )
    return components


def _bbox_axis_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int]:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0, max(ax0 - bx1, bx0 - ax1) - 1)
    dy = max(0, max(ay0 - by1, by0 - ay1) - 1)
    return dx, dy


def _floorplan_content_bbox(path: Path) -> tuple[int, int, int, int]:
    with Image.open(path) as floorplan_image:
        normalized = ImageOps.exif_transpose(floorplan_image).convert("L")
        width, height = normalized.size
        preview_width = min(240, max(120, width // 4))
        preview_height = max(120, int(round(height * preview_width / max(width, 1))))
        preview = normalized.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
        preview_pixels = preview.load()
        binary = [
            [1 if preview_pixels[col, row] < 225 else 0 for col in range(preview_width)]
            for row in range(preview_height)
        ]
    components = [
        component
        for component in _connected_components(binary)
        if not bool(component.get("touches_edge")) and int(component.get("area") or 0) >= 20
    ]
    if not components:
        return (0, 0, width, height)
    components.sort(key=lambda component: int(component.get("area") or 0), reverse=True)
    main_bbox = tuple(components[0]["bbox"])
    kept = []
    for component in components:
        area = int(component.get("area") or 0)
        bbox = tuple(component.get("bbox") or main_bbox)
        gap_x, gap_y = _bbox_axis_gap(bbox, main_bbox)
        if area >= 120 or (max(gap_x, gap_y) <= 6 and (gap_x == 0 or gap_y == 0)):
            kept.append(bbox)
    min_col = min(bbox[0] for bbox in kept)
    min_row = min(bbox[1] for bbox in kept)
    max_col = max(bbox[2] for bbox in kept)
    max_row = max(bbox[3] for bbox in kept)
    scale_x = width / preview_width
    scale_y = height / preview_height
    padding = 16
    left = max(0, int(min_col * scale_x) - padding)
    top = max(0, int(min_row * scale_y) - padding)
    right = min(width, int(round((max_col + 1) * scale_x)) + padding)
    bottom = min(height, int(round((max_row + 1) * scale_y)) + padding)
    if right - left < 40 or bottom - top < 40:
        return (0, 0, width, height)
    return (left, top, right, bottom)


def _extract_floorplan_geometry(
    path: Path,
    *,
    max_grid_width: int = 120,
) -> dict[str, object]:
    with Image.open(path) as floorplan_image:
        normalized = ImageOps.exif_transpose(floorplan_image).convert("L")
        bbox = _floorplan_content_bbox(path)
        cropped = normalized.crop(bbox)
    crop_width, crop_height = cropped.size
    grid_width = max(96, min(max_grid_width, int(round(crop_width / 7.0))))
    grid_height = max(72, int(round(crop_height * grid_width / max(crop_width, 1))))
    reduced = cropped.resize((grid_width, grid_height), Image.Resampling.LANCZOS)
    reduced_pixels = reduced.load()
    initial_mask = [
        [1 if reduced_pixels[col, row] < 210 else 0 for col in range(grid_width)]
        for row in range(grid_height)
    ]
    filtered_mask = [[0 for _ in range(grid_width)] for _ in range(grid_height)]
    for row in range(grid_height):
        for col in range(grid_width):
            if not initial_mask[row][col]:
                continue
            neighbors = 0
            for near_row in range(max(0, row - 1), min(grid_height, row + 2)):
                for near_col in range(max(0, col - 1), min(grid_width, col + 2)):
                    neighbors += initial_mask[near_row][near_col]
            if neighbors >= 3:
                filtered_mask[row][col] = 1
    for component in _connected_components(filtered_mask):
        area = int(component.get("area") or 0)
        min_col, min_row, max_col, max_row = tuple(component.get("bbox") or (0, 0, 0, 0))
        width_cells = max_col - min_col + 1
        height_cells = max_row - min_row + 1
        if area < 6 or (width_cells <= 2 and height_cells <= 2):
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    if filtered_mask[row][col]:
                        filtered_mask[row][col] = 0
    return {
        "content_bbox_px": {
            "left": int(bbox[0]),
            "top": int(bbox[1]),
            "right": int(bbox[2]),
            "bottom": int(bbox[3]),
        },
        "content_size_px": {"width": int(crop_width), "height": int(crop_height)},
        "mask_size_cells": {"width": int(grid_width), "height": int(grid_height)},
        "wall_mask": filtered_mask,
    }


def _room_dimensions(width: int, height: int, *, max_width_m: float) -> tuple[float, float, float]:
    ratio = height / width if width else 0.7
    room_width = float(max_width_m)
    room_depth = max(3.0, min(18.0, room_width * ratio))
    room_height = 2.75
    return round(room_width, 3), round(room_depth, 3), room_height


def _write_inferred_floorplan(target: Path, *, photo_count: int) -> dict[str, object]:
    room_count = max(2, min(6, photo_count or 3))
    width, height = 1400, 940
    image = Image.new("RGB", (width, height), color=(248, 244, 235))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    ink = (45, 39, 30)
    muted = (184, 138, 50)
    draw.rectangle((90, 90, width - 90, height - 90), outline=ink, width=14)
    if room_count <= 3:
        splits = [0.52]
    else:
        splits = [0.42, 0.68]
    for split in splits:
        x = int(90 + (width - 180) * split)
        draw.line((x, 90, x, height - 90), fill=ink, width=8)
    if room_count >= 4:
        y = int(90 + (height - 180) * 0.55)
        draw.line((90, y, int(width * 0.68), y), fill=ink, width=8)
    draw.arc((width - 260, height - 250, width - 90, height - 80), 180, 270, fill=muted, width=6)
    draw.text((120, 120), "Inferred schematic from source photos", fill=muted)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="JPEG", quality=90)
    metadata = _image_metadata(target)
    return {
        "source_path": "generated_from_photo_set",
        "relpath": target.name,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
        "inferred": True,
        "inference_method": "room_count_heuristic_from_photo_count",
        **metadata,
    }


def _wall_rectangles_from_mask(
    wall_mask: list[list[int]],
    *,
    width_m: float,
    depth_m: float,
) -> list[dict[str, float]]:
    rows = len(wall_mask)
    cols = len(wall_mask[0]) if rows else 0
    if not rows or not cols:
        return []
    active: dict[tuple[int, int], dict[str, int]] = {}
    merged: list[dict[str, int]] = []
    for row_index, row in enumerate(wall_mask):
        next_active: dict[tuple[int, int], dict[str, int]] = {}
        run_start: int | None = None
        for col_index in range(cols + 1):
            filled = col_index < cols and bool(row[col_index])
            if filled and run_start is None:
                run_start = col_index
            elif not filled and run_start is not None:
                key = (run_start, col_index - 1)
                current = active.get(key)
                if current is None:
                    current = {
                        "x0": run_start,
                        "x1": col_index - 1,
                        "y0": row_index,
                        "y1": row_index,
                    }
                else:
                    current["y1"] = row_index
                next_active[key] = current
                run_start = None
        for key, rectangle in active.items():
            if key not in next_active:
                merged.append(rectangle)
        active = next_active
    merged.extend(active.values())
    cell_width = width_m / cols
    cell_depth = depth_m / rows
    half_width = width_m / 2
    half_depth = depth_m / 2
    rectangles: list[dict[str, float]] = []
    for rectangle in merged:
        span_cols = rectangle["x1"] - rectangle["x0"] + 1
        span_rows = rectangle["y1"] - rectangle["y0"] + 1
        if span_cols <= 1 and span_rows <= 1:
            continue
        rect_width = round(span_cols * cell_width, 4)
        rect_depth = round(span_rows * cell_depth, 4)
        center_x = round(-half_width + (rectangle["x0"] + span_cols / 2) * cell_width, 4)
        center_z = round(-half_depth + (rectangle["y0"] + span_rows / 2) * cell_depth, 4)
        rectangles.append(
            {
                "center_x": center_x,
                "center_z": center_z,
                "width": rect_width,
                "depth": rect_depth,
            }
        )
    return rectangles


def _write_obj(
    target_dir: Path,
    *,
    width_m: float,
    depth_m: float,
    height_m: float,
    wall_rectangles: list[dict[str, float]],
) -> None:
    obj_lines = ["mtllib model.mtl", "o propertyquarry_generated_layout"]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[str, str, tuple[int, int, int, int]]] = []

    def add_quad(material: str, group: str, points: tuple[tuple[float, float, float], ...]) -> None:
        start_index = len(vertices) + 1
        vertices.extend(points)
        faces.append((material, group, (start_index, start_index + 1, start_index + 2, start_index + 3)))

    def add_box(material: str, group: str, *, center_x: float, center_z: float, box_width: float, box_depth: float, box_height: float) -> None:
        half_box_width = box_width / 2
        half_box_depth = box_depth / 2
        min_x = center_x - half_box_width
        max_x = center_x + half_box_width
        min_z = center_z - half_box_depth
        max_z = center_z + half_box_depth
        min_y = 0.0
        max_y = box_height
        points = [
            (min_x, min_y, min_z),
            (max_x, min_y, min_z),
            (max_x, min_y, max_z),
            (min_x, min_y, max_z),
            (min_x, max_y, min_z),
            (max_x, max_y, min_z),
            (max_x, max_y, max_z),
            (min_x, max_y, max_z),
        ]
        start_index = len(vertices) + 1
        vertices.extend(points)
        faces.extend(
            [
                (material, f"{group}_floor", (start_index, start_index + 1, start_index + 2, start_index + 3)),
                (material, f"{group}_north", (start_index, start_index + 4, start_index + 5, start_index + 1)),
                (material, f"{group}_east", (start_index + 1, start_index + 5, start_index + 6, start_index + 2)),
                (material, f"{group}_south", (start_index + 2, start_index + 6, start_index + 7, start_index + 3)),
                (material, f"{group}_west", (start_index + 3, start_index + 7, start_index + 4, start_index)),
                (material, f"{group}_ceiling", (start_index + 4, start_index + 7, start_index + 6, start_index + 5)),
            ]
        )

    add_quad(
        "warm_floor",
        "floor_plate",
        (
            (-width_m / 2, 0.0, -depth_m / 2),
            (width_m / 2, 0.0, -depth_m / 2),
            (width_m / 2, 0.0, depth_m / 2),
            (-width_m / 2, 0.0, depth_m / 2),
        ),
    )
    for index, rectangle in enumerate(wall_rectangles, start=1):
        add_box(
            "warm_plaster",
            f"wall_{index:03d}",
            center_x=float(rectangle["center_x"]),
            center_z=float(rectangle["center_z"]),
            box_width=float(rectangle["width"]),
            box_depth=float(rectangle["depth"]),
            box_height=height_m,
        )
    for x, y, z in vertices:
        obj_lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    current_material = ""
    for material, group, indexes in faces:
        if material != current_material:
            obj_lines.append(f"usemtl {material}")
            current_material = material
        obj_lines.append(f"g {group}")
        obj_lines.append("f " + " ".join(str(index) for index in indexes))
    (target_dir / "model.obj").write_text("\n".join(obj_lines) + "\n", encoding="utf-8")
    (target_dir / "model.mtl").write_text(
        "\n".join(
            [
                "newmtl warm_floor",
                "Ka 0.94 0.90 0.84",
                "Kd 0.94 0.90 0.84",
                "Ks 0.01 0.01 0.01",
                "Ns 8",
                "newmtl warm_plaster",
                "Ka 0.78 0.74 0.69",
                "Kd 0.90 0.87 0.81",
                "Ks 0.04 0.04 0.04",
                "Ns 14",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _copy_viewer_vendor_assets(target_dir: Path) -> dict[str, str]:
    if not THREE_MODULE_SOURCE.is_file() or not ORBIT_CONTROLS_SOURCE.is_file():
        raise FileNotFoundError("viewer_vendor_assets_missing")
    vendor_dir = target_dir / "vendor"
    three_target = vendor_dir / "three.module.js"
    orbit_target = vendor_dir / "examples" / "jsm" / "controls" / "OrbitControls.js"
    orbit_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(THREE_MODULE_SOURCE, three_target)
    shutil.copy2(ORBIT_CONTROLS_SOURCE, orbit_target)
    return {
        "three_relpath": "vendor/three.module.js",
        "orbit_controls_relpath": "vendor/examples/jsm/controls/OrbitControls.js",
    }


def _write_glb_with_blender(target_dir: Path) -> dict[str, object]:
    blender = shutil.which("blender")
    if not blender:
        return {"status": "skipped", "reason": "blender_missing"}
    obj_path = target_dir / "model.obj"
    glb_path = target_dir / "model.glb"
    if not obj_path.is_file():
        return {"status": "skipped", "reason": "obj_missing"}
    with tempfile.TemporaryDirectory(prefix="propertyquarry-blender-export-") as tempdir:
        script_path = Path(tempdir) / "export_glb.py"
        script_path.write_text(
            "\n".join(
                [
                    "import bpy",
                    "import sys",
                    "from pathlib import Path",
                    f"obj_path = Path({str(obj_path)!r})",
                    f"glb_path = Path({str(glb_path)!r})",
                    "bpy.ops.object.select_all(action='SELECT')",
                    "bpy.ops.object.delete()",
                    "if hasattr(bpy.ops.wm, 'obj_import'):",
                    "    bpy.ops.wm.obj_import(filepath=str(obj_path))",
                    "else:",
                    "    bpy.ops.import_scene.obj(filepath=str(obj_path))",
                    "for obj in bpy.context.scene.objects:",
                    "    obj.select_set(True)",
                    "bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format='GLB', export_yup=True)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [blender, "--background", "--factory-startup", "--python", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    if result.returncode != 0 or not glb_path.is_file():
        return {
            "status": "failed",
            "reason": "blender_glb_export_failed",
            "stdout_tail": (result.stdout or "")[-500:],
            "stderr_tail": (result.stderr or "")[-500:],
        }
    return {
        "status": "generated",
        "glb_relpath": glb_path.name,
        "glb_sha256": _sha256(glb_path),
        "glb_size_bytes": glb_path.stat().st_size,
    }


def _video_duration_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return max(0.0, float(str(completed.stdout or "0").strip() or 0.0))
    except Exception:
        return 0.0


def _declutter_floorplan_stop_positions(
    positions: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Keep 44px route targets separate on the viewer's 4:3 floorplan map."""
    placed: list[tuple[float, float]] = []
    x_step = 16.0
    y_step = 21.0
    for raw_left, raw_top in positions:
        candidates: list[tuple[float, float, float]] = []
        seen: set[tuple[float, float]] = set()
        for grid_x in range(-6, 7):
            for grid_y in range(-5, 6):
                left = round(_clamp_float(raw_left + (grid_x * x_step), 8.0, 92.0), 2)
                top = round(_clamp_float(raw_top + (grid_y * y_step), 10.0, 90.0), 2)
                key = (left, top)
                if key in seen:
                    continue
                seen.add(key)
                distance = ((left - raw_left) ** 2) + ((top - raw_top) ** 2)
                candidates.append((distance, left, top))
        candidates.sort(key=lambda row: (row[0], abs(row[2] - raw_top), abs(row[1] - raw_left)))
        selected = (round(raw_left, 2), round(raw_top, 2))
        for _distance, left, top in candidates:
            if all(abs(left - other_left) >= 15.5 or abs(top - other_top) >= 20.0 for other_left, other_top in placed):
                selected = (left, top)
                break
        placed.append(selected)
    return placed


def _viewer_html(*, manifest: dict[str, object], three_relpath: str, orbit_controls_relpath: str) -> str:
    width_m = manifest["room_dimensions_m"]["width"]
    depth_m = manifest["room_dimensions_m"]["depth"]
    height_m = manifest["room_dimensions_m"]["height"]
    photos = manifest.get("photos") if isinstance(manifest.get("photos"), list) else []
    geometry = dict(manifest.get("geometry") or {}) if isinstance(manifest.get("geometry"), dict) else {}
    wall_rectangles = geometry.get("wall_rectangles") if isinstance(geometry.get("wall_rectangles"), list) else []
    walkable_scene = dict(manifest.get("walkable_scene") or {}) if isinstance(manifest.get("walkable_scene"), dict) else {}
    route_stops = list(walkable_scene.get("route") or []) if isinstance(walkable_scene.get("route"), list) else []
    photo_reference_panels = (
        list(manifest.get("photo_reference_panels") or [])
        if isinstance(manifest.get("photo_reference_panels"), list)
        else []
    )
    style_label = str(manifest.get("style_label") or "").strip()
    escaped_style = html.escape(style_label)
    style_copy = f'<span>{escaped_style}</span>' if escaped_style else ""
    floorplan_relpath = html.escape(str(dict(manifest.get("floorplan") or {}).get("relpath") or "source-floorplan.jpg"))
    floorplan_stop_rows: list[dict[str, object]] = []
    for index, stop in enumerate(route_stops):
        if not isinstance(stop, dict):
            continue
        focus = dict(stop.get("focus") or {}) if isinstance(stop.get("focus"), dict) else {}
        label = html.escape(str(stop.get("label") or stop.get("room") or stop.get("name") or f"Stop {index + 1}"))
        left_pct = round(
            _clamp_float((((float(focus.get("x") or 0.0) / max(float(width_m), 0.001)) + 0.5) * 100.0), 8.0, 92.0),
            2,
        )
        top_pct = round(
            _clamp_float((((float(focus.get("z") or 0.0) / max(float(depth_m), 0.001)) + 0.5) * 100.0), 10.0, 90.0),
            2,
        )
        floorplan_stop_rows.append(
            {
                "index": index,
                "label": label,
                "source_left_pct": left_pct,
                "source_top_pct": top_pct,
            }
        )
    display_positions = _declutter_floorplan_stop_positions(
        [
            (float(row["source_left_pct"]), float(row["source_top_pct"]))
            for row in floorplan_stop_rows
        ]
    )
    floorplan_stop_items: list[str] = []
    floorplan_leader_items: list[str] = []
    floorplan_anchor_items: list[str] = []
    for row, (display_left_pct, display_top_pct) in zip(floorplan_stop_rows, display_positions):
        index = int(row["index"])
        label = str(row["label"])
        source_left_pct = float(row["source_left_pct"])
        source_top_pct = float(row["source_top_pct"])
        if abs(display_left_pct - source_left_pct) > 0.5 or abs(display_top_pct - source_top_pct) > 0.5:
            floorplan_leader_items.append(
                f'<line x1="{source_left_pct}" y1="{source_top_pct}" x2="{display_left_pct}" y2="{display_top_pct}" />'
            )
        floorplan_anchor_items.append(
            f'<circle cx="{source_left_pct}" cy="{source_top_pct}" r="1.15" />'
        )
        floorplan_stop_items.append(
            f"""
        <button class="floorplan-stop" type="button" data-route-index="{index}" aria-label="Go to {label}" style="left:{display_left_pct}%;top:{display_top_pct}%;">
          <span class="floorplan-stop-index">{index + 1}</span>
          <span class="floorplan-stop-label">{label}</span>
        </button>"""
        )
    floorplan_stop_markup = "".join(floorplan_stop_items)
    floorplan_route_overlay = (
        f"""
        <svg class="floorplan-route-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polyline points="{' '.join(f'{row["source_left_pct"]},{row["source_top_pct"]}' for row in floorplan_stop_rows)}" />
          {''.join(floorplan_leader_items)}
          {''.join(floorplan_anchor_items)}
        </svg>"""
        if floorplan_stop_rows
        else ""
    )
    route_items = "\n".join(
        f'<button class="route-button" type="button" data-route-index="{index}">{html.escape(str(stop.get("label") or stop.get("room") or stop.get("name") or f"Stop {index + 1}"))}</button>'
        for index, stop in enumerate(route_stops)
        if isinstance(stop, dict)
    )
    route_section = (
        f"""
    <section class="panel" aria-label="Room route">
      <div class="panel-head">
        <p>Room route</p>
        <span>{len(route_stops)}</span>
      </div>
      <div class="route-buttons">{route_items}</div>
    </section>"""
        if route_items
        else ""
    )
    photo_items = "\n".join(
        f'<img src="{html.escape(str(row["relpath"]))}" alt="Room photo {index}" loading="lazy">'
        for index, row in enumerate(photos, start=1)
        if isinstance(row, dict) and row.get("relpath")
    )
    photo_section = (
        f"""
    <section class="panel" aria-label="Listing photos">
      <div class="panel-head">
        <p>Photos</p>
        <span>{len(photos)}</span>
      </div>
      <div class="photos">{photo_items}</div>
    </section>"""
        if photo_items
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Layout preview | PropertyQuarry</title>
  <style>
    :root {{
      color-scheme: light;
      --ink:#17201c;
      --muted:#5f6b65;
      --canvas:#e8eeeb;
      --surface:#ffffff;
      --panel:rgba(255,255,255,.94);
      --line:#d5ddd8;
      --accent:#146b5d;
      --accent-soft:#e4f1ed;
      --signal:#c85f43;
      --shadow:0 12px 32px rgba(23,32,28,.1);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin:0;
      min-height:100vh;
      font-family:Aptos, ui-sans-serif, system-ui, sans-serif;
      background:#f2f5f3;
      color:var(--ink);
    }}
    main {{ min-height:100vh; display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:0; padding:0; }}
    .stage {{ position:relative; min-height:100vh; }}
    .viewport {{
      width:100%;
      height:100vh;
      min-height:560px;
      border:0;
      border-radius:0;
      background:var(--canvas);
      box-shadow:none;
      overflow:hidden;
      touch-action:none;
    }}
    .viewport canvas {{
      display:block;
      width:100%;
      height:100%;
    }}
    .stage-hotspots {{
      position:absolute;
      inset:0;
      pointer-events:none;
      z-index:2;
      overflow:hidden;
    }}
    .route-hotspot {{
      position:absolute;
      transform:translate(-50%,-50%);
      width:44px;
      height:44px;
      border:0;
      border-radius:50%;
      padding:0;
      background:transparent;
      color:var(--accent);
      display:grid;
      place-items:center;
      font:inherit;
      font-size:12px;
      font-weight:700;
      cursor:pointer;
      pointer-events:auto;
    }}
    .route-hotspot::before {{
      content:"";
      position:absolute;
      inset:8px;
      z-index:-1;
      border:1px solid rgba(20,107,93,.38);
      border-radius:50%;
      background:rgba(255,255,255,.94);
      box-shadow:0 8px 20px rgba(23,32,28,.14);
    }}
    .route-hotspot::after {{
      content:attr(data-label);
      position:absolute;
      top:calc(50% + 20px);
      left:50%;
      transform:translateX(-50%);
      padding:5px 8px;
      border:1px solid var(--line);
      border-radius:4px;
      background:rgba(255,255,255,.96);
      color:var(--ink);
      box-shadow:0 8px 20px rgba(23,32,28,.12);
      white-space:nowrap;
      opacity:0;
      pointer-events:none;
    }}
    .route-hotspot:hover::after,
    .route-hotspot:focus-visible::after,
    .route-hotspot[data-active="true"]::after {{ opacity:1; }}
    .route-hotspot[data-active="true"]::before {{
      border-color:var(--signal);
      background:#fff3ef;
    }}
    .hud {{
      position:absolute;
      top:18px;
      left:18px;
      right:18px;
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
      pointer-events:none;
    }}
    .title-card, .hint-pill {{
      border:1px solid var(--line);
      border-radius:6px;
      background:rgba(255,255,255,.84);
      backdrop-filter:blur(14px);
      box-shadow:0 10px 28px rgba(23,32,28,.1);
    }}
    .title-card {{ padding:14px 16px; max-width:min(390px,70vw); }}
    h1 {{ margin:0; font-size:30px; line-height:1.05; letter-spacing:0; }}
    .title-card p {{ margin:8px 0 0; color:var(--muted); font-size:14px; line-height:1.35; }}
    .hint-pill {{ padding:10px 13px; color:var(--muted); font-size:13px; white-space:nowrap; }}
    .viewer-actions {{
      position:absolute;
      left:18px;
      bottom:18px;
      display:flex;
      gap:2px;
      padding:4px;
      max-width:calc(100% - 36px);
      border:1px solid var(--line);
      border-radius:6px;
      background:rgba(255,255,255,.88);
      box-shadow:0 10px 28px rgba(23,32,28,.12);
      backdrop-filter:blur(14px);
      z-index:2;
    }}
    .capture-route-card {{
      position:absolute;
      right:24px;
      bottom:24px;
      display:none;
      min-width:min(320px,56vw);
      padding:14px 16px;
      border:1px solid rgba(255,255,255,.2);
      border-radius:6px;
      background:rgba(23,32,28,.88);
      color:#fbf6ef;
      backdrop-filter:blur(18px);
      box-shadow:0 18px 48px rgba(23,32,28,.24);
      z-index:2;
    }}
    .capture-route-kicker {{
      display:block;
      font-size:12px;
      font-weight:700;
      letter-spacing:0;
      text-transform:uppercase;
      color:rgba(251,246,239,.72);
    }}
    .capture-route-label {{
      display:block;
      margin-top:8px;
      font-size:32px;
      line-height:1;
      letter-spacing:0;
    }}
    .capture-route-progress {{
      display:block;
      margin-top:8px;
      font-size:13px;
      color:rgba(251,246,239,.78);
    }}
    .viewer-chip {{
      border:0;
      border-radius:4px;
      background:transparent;
      color:var(--ink);
      min-height:44px;
      min-width:44px;
      padding:0 14px;
      font:inherit;
      font-size:13px;
      font-weight:600;
      box-shadow:none;
      cursor:pointer;
    }}
    .viewer-chip:hover {{
      background:#f0f4f2;
    }}
    .viewer-chip[data-active="true"] {{
      background:var(--accent-soft);
      color:var(--accent);
    }}
    .route-buttons {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
    }}
    .route-button {{
      border:1px solid var(--line);
      border-radius:4px;
      background:var(--surface);
      color:var(--ink);
      min-height:44px;
      min-width:44px;
      padding:0 12px;
      font:inherit;
      font-size:13px;
      font-weight:600;
      cursor:pointer;
    }}
    .route-button[data-active="true"] {{
      border-color:rgba(20,107,93,.45);
      background:var(--accent-soft);
      color:var(--accent);
    }}
    button:focus-visible {{ outline:3px solid rgba(20,107,93,.38); outline-offset:2px; }}
    aside {{
      display:flex;
      flex-direction:column;
      gap:10px;
      min-width:0;
      height:100vh;
      overflow-y:auto;
      padding:12px;
      border-left:1px solid var(--line);
      background:#f4f7f5;
    }}
    .panel {{ border:1px solid var(--line); border-radius:6px; background:var(--panel); padding:14px; box-shadow:0 6px 18px rgba(23,32,28,.05); }}
    .panel-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }}
    .panel-head p, .panel-head span {{ margin:0; color:var(--muted); font-size:13px; }}
    .panel-head p {{ color:var(--ink); font-weight:700; }}
    .facts {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
    .facts div {{ border:0; border-left:1px solid var(--line); border-radius:0; padding:8px 10px; background:transparent; }}
    .facts div:first-child {{ border-left:0; }}
    .facts b {{ display:block; font-size:20px; line-height:1; letter-spacing:0; }}
    .facts span {{ display:block; margin-top:5px; color:var(--muted); font-size:12px; }}
    .style-pill {{ display:inline-flex; margin-top:10px; padding:8px 10px; border-radius:4px; background:var(--accent-soft); color:var(--accent); font-size:13px; }}
    .floorplan, .photos img {{ width:100%; border:1px solid var(--line); border-radius:4px; object-fit:cover; background:white; }}
    .floorplan {{ aspect-ratio:4/3; }}
    .floorplan-map {{ position:relative; overflow:visible; }}
    .floorplan-route-overlay {{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      overflow:visible;
      pointer-events:none;
    }}
    .floorplan-route-overlay polyline,
    .floorplan-route-overlay line {{
      fill:none;
      stroke:rgba(20,107,93,.48);
      stroke-width:1.5;
      stroke-linecap:round;
      stroke-linejoin:round;
      vector-effect:non-scaling-stroke;
    }}
    .floorplan-route-overlay line {{ stroke:rgba(95,107,101,.44); stroke-dasharray:3 3; }}
    .floorplan-route-overlay circle {{ fill:var(--signal); vector-effect:non-scaling-stroke; }}
    .floorplan-stop {{
      position:absolute;
      transform:translate(-50%,-50%);
      width:44px;
      height:44px;
      border:0;
      border-radius:50%;
      background:transparent;
      color:var(--accent);
      display:grid;
      place-items:center;
      font:inherit;
      font-size:12px;
      font-weight:700;
      cursor:pointer;
      overflow:visible;
    }}
    .floorplan-stop::before {{
      content:"";
      position:absolute;
      inset:8px;
      border:1px solid rgba(20,107,93,.4);
      border-radius:50%;
      background:rgba(255,255,255,.96);
      box-shadow:0 7px 18px rgba(23,32,28,.13);
    }}
    .floorplan-stop:hover::before,
    .floorplan-stop[data-active="true"]::before {{
      border-color:var(--signal);
      background:#fff3ef;
    }}
    .floorplan-stop-index {{ position:relative; z-index:1; }}
    .floorplan-stop-label {{
      position:absolute;
      left:50%;
      top:calc(50% + 20px);
      transform:translateX(-50%);
      z-index:2;
      padding:5px 8px;
      border:1px solid var(--line);
      border-radius:4px;
      background:rgba(255,255,255,.97);
      color:var(--ink);
      font-size:11px;
      font-weight:600;
      line-height:1;
      white-space:nowrap;
      box-shadow:0 8px 20px rgba(23,32,28,.1);
      opacity:0;
      pointer-events:none;
    }}
    .floorplan-stop:hover .floorplan-stop-label,
    .floorplan-stop:focus-visible .floorplan-stop-label,
    .floorplan-stop[data-active="true"] .floorplan-stop-label {{
      opacity:1;
    }}
    .floorplan-stop[data-active="true"] .floorplan-stop-label {{
      border-color:rgba(200,95,67,.4);
      background:#fff3ef;
      color:#8f3f2b;
    }}
    .floorplan-note {{ margin-top:10px; }}
    .photos {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }}
    .photos img {{ aspect-ratio:1; }}
    .note {{ margin:0; color:var(--muted); font-size:13px; line-height:1.4; }}
    html[data-capture-mode="true"] body {{ background:#dfe7e3; }}
    html[data-capture-mode="true"] main {{
      display:block;
      min-height:100vh;
      padding:0;
    }}
    html[data-capture-mode="true"] aside {{
      display:none;
    }}
    html[data-capture-mode="true"] .stage {{
      min-height:100vh;
    }}
    html[data-capture-mode="true"] .viewport {{
      height:100vh;
      min-height:100vh;
      border:none;
      border-radius:0;
      box-shadow:none;
    }}
    html[data-capture-mode="true"] .stage-hotspots,
    html[data-capture-mode="true"] .viewer-actions,
    html[data-capture-mode="true"] .hint-pill {{
      display:none;
    }}
    html[data-capture-mode="true"] .capture-route-card {{
      display:block;
    }}
    @media (max-width: 880px) {{
      main {{ display:block; padding:0; }}
      .stage {{ min-height:0; }}
      .viewport {{ height:70svh; min-height:500px; border-radius:0; }}
      aside {{
        height:auto;
        overflow:visible;
        margin:0;
        padding:10px;
        border-top:1px solid var(--line);
        border-left:0;
      }}
      .hud {{ top:12px; left:12px; right:12px; }}
      .hint-pill {{ display:none; }}
      .viewer-actions {{
        left:12px;
        right:12px;
        bottom:12px;
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        max-width:none;
      }}
      .title-card {{ max-width:calc(100vw - 24px); padding:12px 13px; }}
      h1 {{ font-size:27px; }}
      .title-card p {{ font-size:13px; }}
      .floorplan-stop-label {{ font-size:10px; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="stage">
    <div class="viewport" id="viewport" aria-label="3D layout preview"></div>
    <div class="stage-hotspots" id="stage-hotspots" aria-label="Room hotspots"></div>
    <div class="hud">
      <div class="title-card">
        <h1>Layout preview</h1>
        <p>Use the real floorplan layout to understand the space before deciding whether to visit.</p>
      </div>
      <div class="hint-pill">Drag, zoom, then inspect the plan beside it.</div>
    </div>
    <div class="viewer-actions">
      <button class="viewer-chip" id="view-overview" type="button">Overview</button>
      <button class="viewer-chip" id="view-dollhouse" type="button">Dollhouse</button>
      <button class="viewer-chip" id="view-inside" type="button">Room view</button>
      <button class="viewer-chip" id="view-guided-route" type="button">Guide me</button>
    </div>
    <div class="capture-route-card" id="capture-route-card" hidden>
      <span class="capture-route-kicker" id="capture-route-kicker">Layout flythrough</span>
      <strong class="capture-route-label" id="capture-route-label">Layout overview</strong>
      <span class="capture-route-progress" id="capture-route-progress">Planning preview</span>
    </div>
  </section>
  <aside>
    <section class="panel">
      <div class="panel-head">
        <p>Layout preview</p>
        <span>approx.</span>
      </div>
      <p class="note">Built from the floorplan and listing photos. Use it for orientation; confirm dimensions at the viewing.</p>
      {f'<span class="style-pill">{style_copy}</span>' if style_copy else ''}
    </section>
    <section class="panel facts" aria-label="Approximate room dimensions">
      <div><b>{width_m}</b><span>m wide</span></div>
      <div><b>{depth_m}</b><span>m deep</span></div>
      <div><b>{height_m}</b><span>m high</span></div>
    </section>
    {route_section}
    <section class="panel">
      <div class="panel-head">
        <p>Floorplan</p>
        <span>{'route map' if floorplan_stop_markup else 'source'}</span>
      </div>
      <div class="floorplan-map">
        <img class="floorplan" src="{floorplan_relpath}" alt="Floorplan">
        {floorplan_route_overlay}
        {floorplan_stop_markup}
      </div>
      {'<p class="note floorplan-note">Tap a numbered stop on the plan to move through the route.</p>' if floorplan_stop_markup else ''}
    </section>
    {photo_section}
  </aside>
</main>
<script type="importmap">
{{
  "imports": {{
    "three": "./{three_relpath}"
  }}
}}
</script>
<script type="module">
import * as THREE from "three";
import {{ OrbitControls }} from "./{orbit_controls_relpath}";

const viewport = document.getElementById("viewport");
const hotspotLayer = document.getElementById("stage-hotspots");
const overviewButton = document.getElementById("view-overview");
const dollhouseButton = document.getElementById("view-dollhouse");
const insideButton = document.getElementById("view-inside");
const guideButton = document.getElementById("view-guided-route");
const wallRectangles = {json.dumps(wall_rectangles, ensure_ascii=False)};
const walkableScene = {json.dumps(walkable_scene, ensure_ascii=False)};
const routeStops = Array.isArray(walkableScene.route) ? walkableScene.route.filter((stop) => stop && typeof stop === "object") : [];
const photoPanelSpecs = {json.dumps(photo_reference_panels, ensure_ascii=False)};
const routeButtons = Array.from(document.querySelectorAll(".route-button"));
const floorplanStopButtons = Array.from(document.querySelectorAll(".floorplan-stop"));
const roomWidth = {json.dumps(width_m)};
const roomDepth = {json.dumps(depth_m)};
const roomHeight = {json.dumps(height_m)};
const routeQuery = new URLSearchParams(window.location.search);
const captureMode = routeQuery.get("capture") === "1";
const guidedQueryEnabled = routeQuery.get("guided") === "1";
const shellProbeMode = routeQuery.get("shell_probe") === "1";
if (captureMode) {{
  document.documentElement.dataset.captureMode = "true";
}}
const captureRouteCard = document.getElementById("capture-route-card");
const captureRouteKicker = document.getElementById("capture-route-kicker");
const captureRouteLabel = document.getElementById("capture-route-label");
const captureRouteProgress = document.getElementById("capture-route-progress");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xe8eeeb);
scene.fog = new THREE.Fog(0xe8eeeb, 13, 34);
let renderFrameCount = 0;

const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true, preserveDrawingBuffer: true }});
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
viewport.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = true;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minPolarAngle = Math.PI * 0.14;
controls.minDistance = Math.max(roomWidth, roomDepth) * 0.32;
controls.maxDistance = Math.max(roomWidth, roomDepth) * 2.4;

const hemisphereLight = new THREE.HemisphereLight(0xfffbf5, 0xd7c4aa, 1.35);
scene.add(hemisphereLight);
const keyLight = new THREE.DirectionalLight(0xffffff, 1.05);
keyLight.position.set(roomWidth * 0.7, roomHeight * 3.2, roomDepth * 0.9);
keyLight.castShadow = true;
keyLight.shadow.mapSize.width = 2048;
keyLight.shadow.mapSize.height = 2048;
keyLight.shadow.camera.near = 0.1;
keyLight.shadow.camera.far = 40;
scene.add(keyLight);

const textureLoader = new THREE.TextureLoader();
const floorTexture = textureLoader.load({json.dumps(str(dict(manifest.get("floorplan") or {}).get("relpath") or "source-floorplan.jpg"))});
floorTexture.colorSpace = THREE.SRGBColorSpace;
floorTexture.anisotropy = 8;
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(roomWidth, roomDepth),
  new THREE.MeshStandardMaterial({{
    color: 0xf8f4eb,
    map: floorTexture,
    roughness: 0.96,
    metalness: 0.0,
  }})
);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

const wallMaterial = new THREE.MeshStandardMaterial({{
  color: 0xf4efe4,
  roughness: 0.88,
  metalness: 0.02,
  side: THREE.DoubleSide,
  transparent: true,
  opacity: 1.0,
}});
const wallEdgeMaterial = new THREE.LineBasicMaterial({{
  color: 0xc2ab83,
  transparent: true,
  opacity: 0.62,
}});
const wallMeshes = [];
const wallEdgeMeshes = [];
const wallMeshPairs = [];
const overviewCutawayBoundaryX = Math.max(0.22, Math.min(roomWidth * 0.08, 0.48));
const overviewCutawayBoundaryZ = Math.max(0.22, Math.min(roomDepth * 0.08, 0.48));
for (const wall of wallRectangles) {{
  const wallWidth = Number(wall.width || 0);
  const wallDepth = Number(wall.depth || 0);
  const centerX = Number(wall.center_x || 0);
  const centerZ = Number(wall.center_z || 0);
  const touchesEastShell = centerX + (wallWidth * 0.5) >= (roomWidth * 0.5) - overviewCutawayBoundaryX;
  const touchesSouthShell = centerZ + (wallDepth * 0.5) >= (roomDepth * 0.5) - overviewCutawayBoundaryZ;
  const cutawayEligible = Boolean(touchesEastShell || touchesSouthShell);
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(wall.width, roomHeight, wall.depth),
    wallMaterial,
  );
  mesh.position.set(centerX, roomHeight / 2, centerZ);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData.baseCenterY = roomHeight / 2;
  mesh.userData.cutawayEligible = cutawayEligible;
  wallMeshes.push(mesh);
  scene.add(mesh);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), wallEdgeMaterial);
  edges.position.copy(mesh.position);
  edges.userData.baseCenterY = roomHeight / 2;
  edges.userData.cutawayEligible = cutawayEligible;
  wallEdgeMeshes.push(edges);
  scene.add(edges);
  wallMeshPairs.push({{ mesh, edges, cutawayEligible }});
}}

const routeMarkerGroup = new THREE.Group();
scene.add(routeMarkerGroup);
const routeMarkers = [];
const routeHotspots = [];
const routeMarkerMaterial = new THREE.MeshStandardMaterial({{
  color: 0xa77c2b,
  roughness: 0.36,
  metalness: 0.04,
}});
const routeLinePoints = [];
for (const stop of routeStops) {{
  const focus = stop.focus && typeof stop.focus === "object" ? stop.focus : null;
  if (!focus) continue;
  const marker = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.16, 0.028, 28),
    routeMarkerMaterial.clone(),
  );
  marker.position.set(Number(focus.x || 0), 0.016, Number(focus.z || 0));
  marker.receiveShadow = true;
  routeMarkerGroup.add(marker);
  routeMarkers.push(marker);
  routeLinePoints.push(new THREE.Vector3(Number(focus.x || 0), 0.018, Number(focus.z || 0)));
  if (hotspotLayer) {{
    const button = document.createElement("button");
    button.type = "button";
    button.className = "route-hotspot";
    button.dataset.routeIndex = String(routeHotspots.length);
    const hotspotLabel = String(stop.label || stop.room || stop.name || `Stop ${{routeHotspots.length + 1}}`);
    button.dataset.label = hotspotLabel;
    button.setAttribute("aria-label", `Go to ${{hotspotLabel}}`);
    button.textContent = String(routeHotspots.length + 1);
    button.addEventListener("click", () => setRouteView(Number(button.dataset.routeIndex || 0)));
    hotspotLayer.appendChild(button);
    routeHotspots.push({{
      button,
      focus: new THREE.Vector3(Number(focus.x || 0), Number(focus.y || roomHeight * 0.5), Number(focus.z || 0)),
    }});
  }}
}}
if (routeLinePoints.length >= 2) {{
  const routeLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(routeLinePoints),
    new THREE.LineBasicMaterial({{
      color: 0xc2ab83,
      transparent: true,
      opacity: 0.7,
    }})
  );
  routeMarkerGroup.add(routeLine);
}}

const stagingGroup = new THREE.Group();
scene.add(stagingGroup);
const stagingObjects = [];
const stagingMaterials = {{
  textile: new THREE.MeshStandardMaterial({{ color: 0xb58f73, roughness: 0.86, metalness: 0.0 }}),
  paleTextile: new THREE.MeshStandardMaterial({{ color: 0xe4dacd, roughness: 0.9, metalness: 0.0 }}),
  timber: new THREE.MeshStandardMaterial({{ color: 0x9b7650, roughness: 0.72, metalness: 0.02 }}),
  stone: new THREE.MeshStandardMaterial({{ color: 0xd7d0c3, roughness: 0.82, metalness: 0.01 }}),
  accent: new THREE.MeshStandardMaterial({{ color: 0xa77c2b, roughness: 0.58, metalness: 0.03 }}),
  foliage: new THREE.MeshStandardMaterial({{ color: 0x6f8561, roughness: 0.92, metalness: 0.0 }}),
}};

function stagingKind(stop) {{
  const raw = String(stop?.kind || stop?.label || stop?.room || stop?.name || "").toLowerCase();
  if (raw.includes("kitchen") || raw.includes("kuche") || raw.includes("kueche") || raw.includes("küche")) return "kitchen";
  if (raw.includes("bed") || raw.includes("schlaf")) return "bedroom";
  if (raw.includes("bath") || raw.includes("bad") || raw.includes("wc") || raw.includes("toilet")) return "bath";
  if (raw.includes("balcony") || raw.includes("terrace") || raw.includes("balkon") || raw.includes("terrasse") || raw.includes("loggia")) return "outdoor";
  if (raw.includes("entry") || raw.includes("hall") || raw.includes("foyer") || raw.includes("flur") || raw.includes("vorraum")) return "entry";
  if (raw.includes("dining") || raw.includes("esszimmer")) return "dining";
  if (raw.includes("living") || raw.includes("wohn")) return "living";
  return "generic";
}}

function addStagingBox(group, name, dimensions, position, material, rotationY = 0) {{
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(
      Math.max(0.04, Number(dimensions.x || 0.2)),
      Math.max(0.04, Number(dimensions.y || 0.2)),
      Math.max(0.04, Number(dimensions.z || 0.2)),
    ),
    material,
  );
  mesh.name = String(name || "generated-staging-object");
  mesh.position.set(Number(position.x || 0), Number(position.y || 0), Number(position.z || 0));
  mesh.rotation.y = Number(rotationY || 0);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  stagingObjects.push(mesh);
  return mesh;
}}

function addStagingRug(group, dimensions, position, material) {{
  const rug = new THREE.Mesh(
    new THREE.PlaneGeometry(Math.max(0.2, Number(dimensions.x || 1)), Math.max(0.2, Number(dimensions.z || 1))),
    material,
  );
  rug.name = "generated-staging-rug";
  rug.rotation.x = -Math.PI / 2;
  rug.position.set(Number(position.x || 0), 0.024, Number(position.z || 0));
  rug.receiveShadow = true;
  group.add(rug);
  stagingObjects.push(rug);
  return rug;
}}

function addGeneratedStagingForStop(stop, index) {{
  const focus = stop?.focus && typeof stop.focus === "object" ? stop.focus : null;
  if (!focus) return null;
  const group = new THREE.Group();
  const baseX = Math.max(-(roomWidth * 0.38), Math.min(roomWidth * 0.38, Number(focus.x || 0)));
  const baseZ = Math.max(-(roomDepth * 0.38), Math.min(roomDepth * 0.38, Number(focus.z || 0)));
  group.position.set(baseX, 0, baseZ);
  group.rotation.y = (Number(index || 0) % 2 === 0 ? -0.22 : 0.18);
  const kind = stagingKind(stop);
  if (kind === "living" || kind === "generic") {{
    addStagingRug(group, {{ x: 1.62, z: 1.1 }}, {{ x: 0.05, z: 0.02 }}, stagingMaterials.paleTextile);
    addStagingBox(group, "generated-sofa-seat", {{ x: 1.24, y: 0.28, z: 0.52 }}, {{ x: -0.22, y: 0.14, z: -0.22 }}, stagingMaterials.textile);
    addStagingBox(group, "generated-sofa-back", {{ x: 1.24, y: 0.48, z: 0.12 }}, {{ x: -0.22, y: 0.38, z: -0.53 }}, stagingMaterials.textile);
    addStagingBox(group, "generated-coffee-table", {{ x: 0.72, y: 0.2, z: 0.42 }}, {{ x: 0.26, y: 0.1, z: 0.34 }}, stagingMaterials.timber);
  }} else if (kind === "bedroom") {{
    addStagingRug(group, {{ x: 1.74, z: 1.22 }}, {{ x: 0.02, z: 0.02 }}, stagingMaterials.paleTextile);
    addStagingBox(group, "generated-bed-base", {{ x: 1.42, y: 0.34, z: 1.02 }}, {{ x: 0, y: 0.17, z: -0.02 }}, stagingMaterials.paleTextile);
    addStagingBox(group, "generated-bed-headboard", {{ x: 1.48, y: 0.72, z: 0.12 }}, {{ x: 0, y: 0.44, z: -0.62 }}, stagingMaterials.timber);
    addStagingBox(group, "generated-bed-pillow", {{ x: 0.64, y: 0.16, z: 0.22 }}, {{ x: -0.26, y: 0.44, z: -0.42 }}, stagingMaterials.stone);
  }} else if (kind === "kitchen" || kind === "dining") {{
    addStagingBox(group, "generated-kitchen-counter", {{ x: 1.48, y: 0.68, z: 0.42 }}, {{ x: -0.08, y: 0.34, z: -0.38 }}, stagingMaterials.stone);
    addStagingBox(group, "generated-kitchen-island", {{ x: 0.9, y: 0.42, z: 0.5 }}, {{ x: 0.28, y: 0.21, z: 0.28 }}, stagingMaterials.timber);
    addStagingBox(group, "generated-dining-surface", {{ x: 0.86, y: 0.18, z: 0.58 }}, {{ x: -0.48, y: 0.46, z: 0.36 }}, stagingMaterials.timber);
  }} else if (kind === "bath") {{
    addStagingBox(group, "generated-bath-vanity", {{ x: 0.72, y: 0.52, z: 0.36 }}, {{ x: -0.22, y: 0.26, z: -0.18 }}, stagingMaterials.stone);
    addStagingBox(group, "generated-bath-tub", {{ x: 1.08, y: 0.36, z: 0.54 }}, {{ x: 0.28, y: 0.18, z: 0.28 }}, stagingMaterials.paleTextile);
  }} else if (kind === "entry") {{
    addStagingBox(group, "generated-entry-bench", {{ x: 1.0, y: 0.28, z: 0.34 }}, {{ x: -0.1, y: 0.14, z: -0.18 }}, stagingMaterials.timber);
    addStagingBox(group, "generated-entry-console", {{ x: 0.78, y: 0.64, z: 0.22 }}, {{ x: 0.34, y: 0.32, z: 0.24 }}, stagingMaterials.stone);
  }} else if (kind === "outdoor") {{
    addStagingBox(group, "generated-outdoor-table", {{ x: 0.72, y: 0.26, z: 0.56 }}, {{ x: 0.0, y: 0.13, z: 0.08 }}, stagingMaterials.timber);
    addStagingBox(group, "generated-planter", {{ x: 0.34, y: 0.4, z: 0.34 }}, {{ x: -0.52, y: 0.2, z: -0.28 }}, stagingMaterials.accent);
    addStagingBox(group, "generated-foliage", {{ x: 0.42, y: 0.42, z: 0.42 }}, {{ x: -0.52, y: 0.56, z: -0.28 }}, stagingMaterials.foliage);
  }}
  stagingGroup.add(group);
  return group;
}}

routeStops.forEach((stop, index) => addGeneratedStagingForStop(stop, index));

function buildPanelLabelTexture(label) {{
  const canvas = document.createElement("canvas");
  canvas.width = 720;
  canvas.height = 140;
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "rgba(255,252,245,0.98)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "rgba(194,171,131,0.78)";
  context.lineWidth = 4;
  context.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
  context.fillStyle = "#4b3923";
  context.font = "600 40px Aptos, ui-sans-serif, system-ui, sans-serif";
  context.textBaseline = "middle";
  context.fillText(String(label || "Room reference"), 28, canvas.height / 2, canvas.width - 56);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}}

const photoPanelGroup = new THREE.Group();
scene.add(photoPanelGroup);
const photoPanelCards = [];
const photoPanelPlanes = [];
let loadedPhotoTextureCount = 0;
const liveViewerState = {{
  ready: false,
  routeStopCount: Number(routeStops.length || 0),
  activeRouteIndex: -1,
  viewMode: "overview",
  photoPanelCount: Number(photoPanelSpecs.length || 0),
  loadedPhotoTextureCount: 0,
  frameCount: 0,
  renderCalls: 0,
  renderTriangles: 0,
}};
for (const spec of photoPanelSpecs) {{
  if (!spec || typeof spec !== "object" || !spec.photo_relpath) continue;
  const panelGroup = new THREE.Group();
  panelGroup.position.set(
    Number(spec.position?.x || 0),
    Number(spec.position?.y || 1.5),
    Number(spec.position?.z || 0),
  );
  panelGroup.rotation.y = Number(spec.rotation_y || 0);

  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(Number(spec.frame_width || 1.3) + 0.08, Number(spec.frame_height || 1.2) + 0.1),
    new THREE.MeshBasicMaterial({{
      color: 0x000000,
      transparent: true,
      opacity: 0.12,
      side: THREE.DoubleSide,
    }})
  );
  shadow.position.set(0.03, -0.02, -0.035);
  panelGroup.add(shadow);

  const matte = new THREE.Mesh(
    new THREE.PlaneGeometry(Number(spec.frame_width || 1.3), Number(spec.frame_height || 1.2)),
    new THREE.MeshStandardMaterial({{
      color: 0xfffbf3,
      roughness: 0.72,
      metalness: 0.02,
      side: THREE.DoubleSide,
    }})
  );
  matte.position.z = -0.012;
  matte.castShadow = true;
  matte.receiveShadow = true;
  panelGroup.add(matte);

  const photoPanel = new THREE.Mesh(
    new THREE.PlaneGeometry(Number(spec.photo_width || 1.12), Number(spec.photo_height || 0.92)),
    new THREE.MeshStandardMaterial({{
      color: 0xf6efe5,
      roughness: 0.82,
      metalness: 0.01,
      side: THREE.DoubleSide,
    }})
  );
  photoPanel.position.set(0, 0.05, 0.006);
  photoPanel.castShadow = true;
  photoPanel.receiveShadow = true;
  panelGroup.add(photoPanel);
  photoPanelPlanes.push(photoPanel);

  const labelTexture = buildPanelLabelTexture(String(spec.label || "Room reference"));
  if (labelTexture) {{
    const labelWidth = Math.max(0.82, Math.min(Number(spec.frame_width || 1.3), 1.72));
    const labelPlaque = new THREE.Mesh(
      new THREE.PlaneGeometry(labelWidth, 0.24),
      new THREE.MeshBasicMaterial({{
        map: labelTexture,
        transparent: true,
        side: THREE.DoubleSide,
      }})
    );
    labelPlaque.position.set(0, -((Number(spec.frame_height || 1.2) * 0.5) - 0.15), 0.018);
    panelGroup.add(labelPlaque);
  }}

  textureLoader.load(
    String(spec.photo_relpath || ""),
    (texture) => {{
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = 8;
      photoPanel.material.map = texture;
      photoPanel.material.needsUpdate = true;
      loadedPhotoTextureCount += 1;
      liveViewerState.loadedPhotoTextureCount = loadedPhotoTextureCount;
    }},
    undefined,
    () => null,
  );

  photoPanelCards.push({{
    group: panelGroup,
    routeIndex: Number(spec.route_index ?? -1),
    matteMaterial: matte.material,
  }});
  photoPanelGroup.add(panelGroup);
}}

const outline = new THREE.Mesh(
  new THREE.PlaneGeometry(roomWidth * 1.01, roomDepth * 1.01),
  new THREE.MeshBasicMaterial({{
    color: 0xffffff,
    opacity: 0.08,
    transparent: true,
    side: THREE.DoubleSide,
  }})
);
outline.rotation.x = -Math.PI / 2;
outline.position.y = 0.002;
scene.add(outline);

function easeInOutCubic(value) {{
  const bounded = Math.max(0, Math.min(1, Number(value || 0)));
  if (bounded < 0.5) {{
    return 4 * bounded * bounded * bounded;
  }}
  return 1 - Math.pow(-2 * bounded + 2, 3) / 2;
}}

function overviewCameraState() {{
  return {{
    position: new THREE.Vector3(roomWidth * 0.74, roomHeight * 1.22, roomDepth * 0.76),
    target: new THREE.Vector3(0, roomHeight * 0.52, -roomDepth * 0.04),
    viewMode: "overview",
    routeIndex: activeRouteIndex >= 0 ? activeRouteIndex : (routeStops.length ? 0 : -1),
  }};
}}

function dollhouseCameraState() {{
  return {{
    position: new THREE.Vector3(
      roomWidth * 0.12,
      Math.max(roomHeight * 2.18, Math.max(roomWidth, roomDepth) * 1.08),
      roomDepth * 0.94,
    ),
    target: new THREE.Vector3(0, roomHeight * 0.24, -roomDepth * 0.03),
    viewMode: "dollhouse",
    routeIndex: activeRouteIndex >= 0 ? activeRouteIndex : (routeStops.length ? 0 : -1),
  }};
}}

function routeCameraState(index = 0, variant = 0) {{
  const boundedIndex = routeStops.length
    ? Math.max(0, Math.min(Number(index || 0), routeStops.length - 1))
    : -1;
  const stop = boundedIndex >= 0 ? (routeStops[boundedIndex] || routeStops[0]) : null;
  const focus = stop?.focus && typeof stop.focus === "object" ? stop.focus : {{}};
  const cameraStop = stop?.camera && typeof stop.camera === "object" ? stop.camera : {{}};
  const position = new THREE.Vector3(
    Number(cameraStop.x || 0),
    Number(cameraStop.y || roomHeight * 0.78),
    Number(cameraStop.z || 0),
  );
  const target = new THREE.Vector3(
    Number(focus.x || 0),
    Number(focus.y || roomHeight * 0.6),
    Number(focus.z || 0),
  );
  const visitVariant = Math.max(0, Number(variant || 0));
  if (visitVariant > 0) {{
    const lookVector = new THREE.Vector3(target.x - position.x, 0, target.z - position.z);
    if (lookVector.lengthSq() > 1e-6) {{
      lookVector.normalize();
      const lateral = new THREE.Vector3(-lookVector.z, 0, lookVector.x);
      const orbitDirection = visitVariant % 2 === 0 ? 1 : -1;
      const lateralOffset = Math.min(Math.max(roomWidth, roomDepth) * 0.06, 0.46) * Math.min(2.2, 0.92 + (visitVariant * 0.32)) * orbitDirection;
      const forwardOffset = Math.min(Math.max(roomWidth, roomDepth) * 0.04, 0.28) * Math.min(visitVariant, 2);
      position.addScaledVector(lateral, lateralOffset);
      position.addScaledVector(lookVector, forwardOffset);
      position.y += Math.min(0.22, 0.08 * visitVariant);
      target.addScaledVector(lateral, lateralOffset * 0.18);
      position.x = Math.max(-(roomWidth * 0.45), Math.min(roomWidth * 0.45, position.x));
      position.z = Math.max(-(roomDepth * 0.45), Math.min(roomDepth * 0.45, position.z));
    }}
  }}
  return {{
    position,
    target,
    viewMode: "room",
    routeIndex: boundedIndex,
  }};
}}

function insideCameraState() {{
  if (routeStops.length) {{
    return routeCameraState(activeRouteIndex >= 0 ? activeRouteIndex : 0, 0);
  }}
  return {{
    position: new THREE.Vector3(-roomWidth * 0.12, roomHeight * 0.78, roomDepth * 0.18),
    target: new THREE.Vector3(roomWidth * 0.2, roomHeight * 0.66, -roomDepth * 0.28),
    viewMode: "room",
    routeIndex: activeRouteIndex,
  }};
}}

function resolveViewState(request = {{}}) {{
  const viewMode = request && typeof request === "object" ? String(request.viewMode || "").trim().toLowerCase() : "";
  if (viewMode === "dollhouse") {{
    return dollhouseCameraState();
  }}
  if (viewMode === "room") {{
    return routeStops.length
      ? routeCameraState(Number(request.routeIndex || 0), Number(request.variant || 0))
      : insideCameraState();
  }}
  if (viewMode === "inside") {{
    return insideCameraState();
  }}
  return overviewCameraState();
}}

function captureRouteCopy(overlay = {{}}) {{
  const normalizedOverlay = overlay && typeof overlay === "object" ? overlay : {{}};
  const routeIndexValue = Number.isFinite(Number(normalizedOverlay.routeIndex))
    ? Number(normalizedOverlay.routeIndex)
    : activeRouteIndex;
  const activeStop = routeIndexValue >= 0 ? routeStops[routeIndexValue] : null;
  const activeLabel = activeStop
    ? String(activeStop.label || activeStop.room || activeStop.name || `Stop ${{routeIndexValue + 1}}`)
    : "";
  const sequence = Number.isFinite(Number(normalizedOverlay.sequence))
    ? Math.max(0, Number(normalizedOverlay.sequence))
    : (routeIndexValue >= 0 ? routeIndexValue + 1 : 0);
  const total = Number.isFinite(Number(normalizedOverlay.total))
    ? Math.max(1, Number(normalizedOverlay.total))
    : Math.max(1, Number(routeStops.length || 1));
  const label = String(
    normalizedOverlay.label
    || (activeViewMode === "dollhouse" ? "Dollhouse route view" : activeViewMode === "room" ? activeLabel || "Room view" : "Layout overview")
  ).trim();
  const kicker = String(normalizedOverlay.kicker || (activeViewMode === "room" ? "Room route" : "Layout flythrough")).trim();
  const progress = String(
    normalizedOverlay.progress
    || (sequence > 0 ? `Stop ${{sequence}} of ${{total}}` : `${{Math.max(1, routeStops.length || 1)}} route stops`)
  ).trim();
  return {{
    kicker: kicker || "Layout flythrough",
    label: label || "Layout overview",
    progress: progress || "Planning preview",
  }};
}}

function syncCaptureRouteCard(overlay = {{}}) {{
  if (!captureRouteCard || !captureRouteKicker || !captureRouteLabel || !captureRouteProgress) {{
    return null;
  }}
  const copy = captureRouteCopy(overlay);
  captureRouteCard.hidden = !captureMode;
  captureRouteKicker.textContent = copy.kicker;
  captureRouteLabel.textContent = copy.label;
  captureRouteProgress.textContent = copy.progress;
  return copy;
}}

function travelDistanceForTransition(nextPosition, nextTarget) {{
  const cameraDistance = camera.position.distanceTo(nextPosition);
  const targetDistance = controls.target.distanceTo(nextTarget);
  return Math.max(cameraDistance, targetDistance * 1.15);
}}

const routeCameraTransition = {{
  active: false,
  startedAt: 0,
  durationMs: 0,
  progress: 1,
  targetRouteIndex: routeStops.length ? 0 : -1,
  targetViewMode: "overview",
  fromPosition: new THREE.Vector3(),
  toPosition: new THREE.Vector3(),
  fromTarget: new THREE.Vector3(),
  toTarget: new THREE.Vector3(),
}};
const guidedRouteState = {{
  active: false,
  currentIndex: -1,
  dwellMs: 2200,
  timerId: 0,
}};

function clearGuidedRouteTimer() {{
  if (guidedRouteState.timerId) {{
    window.clearTimeout(guidedRouteState.timerId);
    guidedRouteState.timerId = 0;
  }}
}}

function setGuideChipState(active) {{
  if (!guideButton) {{
    return;
  }}
  guideButton.dataset.active = active ? "true" : "false";
  guideButton.textContent = active ? "Stop guide" : "Guide me";
}}

function stopGuidedRoute() {{
  clearGuidedRouteTimer();
  guidedRouteState.active = false;
  setGuideChipState(false);
}}

function queueGuidedRouteIndex(index, delayMs) {{
  clearGuidedRouteTimer();
  if (!guidedRouteState.active) {{
    return;
  }}
  guidedRouteState.timerId = window.setTimeout(() => {{
    runGuidedRouteIndex(index);
  }}, Math.max(240, Number(delayMs || guidedRouteState.dwellMs)));
}}

function runGuidedRouteIndex(index) {{
  if (!guidedRouteState.active || !routeStops.length) {{
    return;
  }}
  const boundedIndex = Math.max(0, Math.min(Number(index || 0), routeStops.length - 1));
  guidedRouteState.currentIndex = boundedIndex;
  setRouteView(boundedIndex, {{ guided: true, variant: boundedIndex > 0 ? 1 : 0 }});
  const transitionDelay = Math.max(guidedRouteState.dwellMs, Number(routeCameraTransition.durationMs || 0) + guidedRouteState.dwellMs);
  if (boundedIndex + 1 < routeStops.length) {{
    queueGuidedRouteIndex(boundedIndex + 1, transitionDelay);
    return;
  }}
  guidedRouteState.timerId = window.setTimeout(() => {{
    stopGuidedRoute();
  }}, transitionDelay);
}}

function startGuidedRoute(options = {{}}) {{
  if (!routeStops.length) {{
    return false;
  }}
  guidedRouteState.active = true;
  const requestedIndex = Number.isFinite(Number(options && options.startIndex))
    ? Number(options.startIndex)
    : (activeRouteIndex >= 0 ? activeRouteIndex : 0);
  guidedRouteState.currentIndex = Math.max(0, Math.min(requestedIndex, routeStops.length - 1));
  setGuideChipState(true);
  runGuidedRouteIndex(guidedRouteState.currentIndex);
  return true;
}}

function commitCameraView(position, target) {{
  camera.position.copy(position);
  controls.target.copy(target);
  controls.update();
}}

function completeCameraTransition() {{
  commitCameraView(routeCameraTransition.toPosition, routeCameraTransition.toTarget);
  routeCameraTransition.active = false;
  routeCameraTransition.startedAt = 0;
  routeCameraTransition.progress = 1;
}}

function startCameraTransition({{ position, target, viewMode, routeIndex = activeRouteIndex, immediate = false }}) {{
  const nextPosition = position.clone();
  const nextTarget = target.clone();
  const travelDistance = travelDistanceForTransition(nextPosition, nextTarget);
  applyViewMode(viewMode);
  const normalizedRouteIndex = routeStops.length
    ? Math.max(-1, Math.min(Number(routeIndex ?? activeRouteIndex ?? -1), routeStops.length - 1))
    : -1;
  if (normalizedRouteIndex >= 0) {{
    setActiveRouteButton(normalizedRouteIndex);
  }}
  routeCameraTransition.targetRouteIndex = normalizedRouteIndex;
  routeCameraTransition.targetViewMode = activeViewMode;
  routeCameraTransition.toPosition.copy(nextPosition);
  routeCameraTransition.toTarget.copy(nextTarget);
  if (immediate || travelDistance < 0.08) {{
    routeCameraTransition.durationMs = 0;
    completeCameraTransition();
    return;
  }}
  routeCameraTransition.fromPosition.copy(camera.position);
  routeCameraTransition.fromTarget.copy(controls.target);
  routeCameraTransition.durationMs = Math.round(Math.max(650, Math.min(1550, 560 + (travelDistance * 120))));
  routeCameraTransition.startedAt = performance.now();
  routeCameraTransition.progress = 0;
  routeCameraTransition.active = true;
}}

function stepCameraTransition(now) {{
  if (!routeCameraTransition.active) {{
    return false;
  }}
  const elapsed = Math.max(0, Number(now || performance.now()) - Number(routeCameraTransition.startedAt || 0));
  const durationMs = Math.max(1, Number(routeCameraTransition.durationMs || 1));
  const linearProgress = Math.max(0, Math.min(1, elapsed / durationMs));
  const easedProgress = easeInOutCubic(linearProgress);
  routeCameraTransition.progress = linearProgress;
  camera.position.lerpVectors(routeCameraTransition.fromPosition, routeCameraTransition.toPosition, easedProgress);
  controls.target.lerpVectors(routeCameraTransition.fromTarget, routeCameraTransition.toTarget, easedProgress);
  controls.update();
  if (linearProgress >= 1) {{
    completeCameraTransition();
  }}
  return true;
}}

function setOverviewView(options = {{}}) {{
  if (!Boolean(options && options.guided)) {{
    stopGuidedRoute();
  }}
  const state = overviewCameraState();
  startCameraTransition({{
    position: state.position,
    target: state.target,
    viewMode: state.viewMode,
    routeIndex: state.routeIndex,
    immediate: renderFrameCount < 1,
  }});
}}

function setDollhouseView(options = {{}}) {{
  if (!Boolean(options && options.guided)) {{
    stopGuidedRoute();
  }}
  const state = dollhouseCameraState();
  startCameraTransition({{
    position: state.position,
    target: state.target,
    viewMode: state.viewMode,
    routeIndex: state.routeIndex,
    immediate: renderFrameCount < 1,
  }});
}}

function setInsideView(options = {{}}) {{
  if (!Boolean(options && options.guided)) {{
    stopGuidedRoute();
  }}
  if (routeStops.length) {{
    setRouteView(0, {{ immediate: renderFrameCount < 1 && activeRouteIndex < 0, guided: Boolean(options && options.guided) }});
    return;
  }}
  const state = insideCameraState();
  startCameraTransition({{
    position: state.position,
    target: state.target,
    viewMode: state.viewMode,
    routeIndex: state.routeIndex,
    immediate: renderFrameCount < 1,
  }});
}}

let activeRouteIndex = -1;
let activeViewMode = "overview";
function setActiveViewChip(mode) {{
  overviewButton && (overviewButton.dataset.active = mode === "overview" ? "true" : "false");
  dollhouseButton && (dollhouseButton.dataset.active = mode === "dollhouse" ? "true" : "false");
  insideButton && (insideButton.dataset.active = mode === "room" ? "true" : "false");
  setGuideChipState(guidedRouteState.active);
}}

const cutawayWallCount = wallMeshPairs.filter((pair) => Boolean(pair.cutawayEligible)).length;
function applyCutawayWallVisibility(active) {{
  const hideCutawayWalls = Boolean(active);
  for (const pair of wallMeshPairs) {{
    const visible = !(hideCutawayWalls && Boolean(pair.cutawayEligible));
    pair.mesh.visible = visible;
    pair.edges.visible = visible;
  }}
}}

function setWallHeightScale(scale) {{
  const boundedScale = Math.max(0.42, Math.min(1.0, Number(scale || 1)));
  for (const mesh of wallMeshes) {{
    mesh.scale.y = boundedScale;
    mesh.position.y = roomHeight * boundedScale * 0.5;
  }}
  for (const edge of wallEdgeMeshes) {{
    edge.scale.y = boundedScale;
    edge.position.y = roomHeight * boundedScale * 0.5;
  }}
}}

function applyViewMode(mode) {{
  const normalizedMode = mode === "dollhouse" ? "dollhouse" : mode === "room" ? "room" : "overview";
  const isOverview = normalizedMode === "overview";
  const isDollhouse = normalizedMode === "dollhouse";
  const cutawayActive = isOverview || isDollhouse;
  activeViewMode = normalizedMode;
  liveViewerState.viewMode = normalizedMode;
  wallMaterial.opacity = isDollhouse ? 0.38 : isOverview ? 0.84 : 1.0;
  wallMaterial.depthWrite = !cutawayActive;
  wallMaterial.needsUpdate = true;
  wallEdgeMaterial.opacity = isDollhouse ? 0.88 : isOverview ? 0.54 : 0.62;
  floor.material.color.set(isDollhouse ? 0xfcf8ef : isOverview ? 0xfbf7ef : 0xf8f4eb);
  photoPanelGroup.visible = !isDollhouse;
  if (hotspotLayer) {{
    hotspotLayer.style.opacity = isDollhouse ? "0.78" : "1";
  }}
  controls.minPolarAngle = isDollhouse ? Math.PI * 0.02 : isOverview ? Math.PI * 0.1 : Math.PI * 0.14;
  controls.maxPolarAngle = isDollhouse ? Math.PI * 0.34 : isOverview ? Math.PI * 0.42 : Math.PI * 0.49;
  setWallHeightScale(isDollhouse ? 0.56 : isOverview ? 0.82 : 1.0);
  applyCutawayWallVisibility(cutawayActive);
  setActiveViewChip(normalizedMode);
  syncCaptureRouteCard();
}}

function setActiveRouteButton(index) {{
  routeButtons.forEach((button, buttonIndex) => {{
    button.dataset.active = buttonIndex === index ? "true" : "false";
  }});
  floorplanStopButtons.forEach((button) => {{
    button.dataset.active = Number(button.dataset.routeIndex || -1) === index ? "true" : "false";
  }});
  routeMarkers.forEach((marker, markerIndex) => {{
    marker.scale.setScalar(markerIndex === index ? 1.28 : 1.0);
    marker.material.color.set(markerIndex === index ? 0xb9892f : 0xa77c2b);
  }});
  routeHotspots.forEach((entry, entryIndex) => {{
    entry.button.dataset.active = entryIndex === index ? "true" : "false";
  }});
  photoPanelCards.forEach((card) => {{
    const active = Number(card.routeIndex) === index;
    card.group.scale.setScalar(active ? 1.035 : 1.0);
    card.matteMaterial.color.set(active ? 0xfff4df : 0xfffbf3);
  }});
  activeRouteIndex = index;
  liveViewerState.activeRouteIndex = index;
  syncCaptureRouteCard({{ routeIndex: index }});
}}

function setRouteView(index, options = {{}}) {{
  if (!routeStops.length) {{
    return;
  }}
  if (!Boolean(options && options.guided)) {{
    stopGuidedRoute();
  }}
  const state = routeCameraState(index, Number(options?.variant || 0));
  startCameraTransition({{
    position: state.position,
    target: state.target,
    viewMode: state.viewMode,
    routeIndex: state.routeIndex,
    immediate: Boolean(options && options.immediate),
  }});
}}

overviewButton?.addEventListener("click", setOverviewView);
dollhouseButton?.addEventListener("click", setDollhouseView);
insideButton?.addEventListener("click", setInsideView);
guideButton?.addEventListener("click", () => {{
  if (guidedRouteState.active) {{
    stopGuidedRoute();
    return;
  }}
  startGuidedRoute({{ startIndex: activeRouteIndex >= 0 ? activeRouteIndex : 0 }});
}});
routeButtons.forEach((button, index) => button.addEventListener("click", () => setRouteView(index)));
floorplanStopButtons.forEach((button) => button.addEventListener("click", () => setRouteView(Number(button.dataset.routeIndex || 0))));
renderer.domElement.addEventListener("pointerdown", () => {{
  if (guidedRouteState.active) {{
    stopGuidedRoute();
  }}
}});
renderer.domElement.addEventListener("wheel", () => {{
  if (guidedRouteState.active) {{
    stopGuidedRoute();
  }}
}}, {{ passive: true }});

function resize() {{
  const width = Math.max(320, viewport.clientWidth || 320);
  const height = Math.max(420, viewport.clientHeight || 420);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}}

function syncRouteHotspots() {{
  if (!hotspotLayer) {{
    return 0;
  }}
  const width = Math.max(1, viewport.clientWidth || renderer.domElement.clientWidth || 1);
  const height = Math.max(1, viewport.clientHeight || renderer.domElement.clientHeight || 1);
  let visibleCount = 0;
  for (const entry of routeHotspots) {{
    const projected = entry.focus.clone().project(camera);
    const visible =
      Number.isFinite(projected.x) &&
      Number.isFinite(projected.y) &&
      Number.isFinite(projected.z) &&
      projected.z > -1 &&
      projected.z < 1;
    if (!visible) {{
      entry.button.hidden = true;
      continue;
    }}
    const left = (projected.x * 0.5 + 0.5) * width;
    const top = (-projected.y * 0.5 + 0.5) * height;
    if (left < -24 || left > width + 24 || top < -24 || top > height + 24) {{
      entry.button.hidden = true;
      continue;
    }}
    entry.button.hidden = false;
    entry.button.style.left = `${{left.toFixed(1)}}px`;
    entry.button.style.top = `${{top.toFixed(1)}}px`;
    visibleCount += 1;
  }}
  return visibleCount;
}}

function renderCaptureFrame(payload = {{}}) {{
  const normalizedPayload = payload && typeof payload === "object" ? payload : {{}};
  const fromState = resolveViewState(normalizedPayload.from || {{}});
  const toState = resolveViewState(normalizedPayload.to || {{}});
  const progress = easeInOutCubic(Math.max(0, Math.min(1, Number(normalizedPayload.progress || 0))));
  const routeIndex = Number.isFinite(Number(normalizedPayload.routeIndex))
    ? Number(normalizedPayload.routeIndex)
    : Number(toState.routeIndex ?? -1);
  applyViewMode(String(toState.viewMode || "overview"));
  camera.position.lerpVectors(fromState.position, toState.position, progress);
  controls.target.lerpVectors(fromState.target, toState.target, progress);
  controls.update();
  setActiveRouteButton(routeIndex);
  syncCaptureRouteCard(
    normalizedPayload.overlay && typeof normalizedPayload.overlay === "object"
      ? {{ ...normalizedPayload.overlay, routeIndex }}
      : {{ routeIndex }}
  );
  renderer.render(scene, camera);
  renderFrameCount += 1;
  syncRouteHotspots();
  return getRenderMetrics();
}}

window.addEventListener("resize", resize);
resize();
setOverviewView();
if (routeStops.length) {{
  setActiveRouteButton(0);
}}
syncCaptureRouteCard();
setGuideChipState(false);
if (guidedQueryEnabled && routeStops.length && !captureMode) {{
  window.setTimeout(() => {{
    startGuidedRoute({{ startIndex: 0 }});
  }}, 820);
}}

function getRenderMetrics() {{
    const canvas = renderer.domElement;
    if (!canvas) {{
      return {{
        ready: false,
        reason: "canvas_unavailable",
        frameCount: Number(renderFrameCount || 0),
        wallRectCount: Number(wallRectangles.length || 0),
      }};
    }}
    scene.updateMatrixWorld(true);
    camera.updateMatrixWorld(true);
    const projectionMatrix = new THREE.Matrix4().multiplyMatrices(
      camera.projectionMatrix,
      camera.matrixWorldInverse,
    );
    const frustum = new THREE.Frustum().setFromProjectionMatrix(projectionMatrix);
    const corner = new THREE.Vector3();
    let visibleWallCount = 0;
    let hiddenCutawayWallCount = 0;
    let projectedCoverage = 0;
    let maxProjectedArea = 0;
    for (const mesh of wallMeshes) {{
      if (!mesh.visible) {{
        if (Boolean(mesh.userData?.cutawayEligible)) {{
          hiddenCutawayWallCount += 1;
        }}
        continue;
      }}
      const box = new THREE.Box3().setFromObject(mesh);
      if (!frustum.intersectsBox(box)) continue;
      visibleWallCount += 1;
      const corners = [
        [box.min.x, box.min.y, box.min.z],
        [box.min.x, box.min.y, box.max.z],
        [box.min.x, box.max.y, box.min.z],
        [box.min.x, box.max.y, box.max.z],
        [box.max.x, box.min.y, box.min.z],
        [box.max.x, box.min.y, box.max.z],
        [box.max.x, box.max.y, box.min.z],
        [box.max.x, box.max.y, box.max.z],
      ];
      let minX = 1;
      let maxX = -1;
      let minY = 1;
      let maxY = -1;
      let hasProjectedCorner = false;
      for (const [x, y, z] of corners) {{
        corner.set(x, y, z).project(camera);
        if (!Number.isFinite(corner.x) || !Number.isFinite(corner.y)) continue;
        minX = Math.min(minX, Math.max(-1, Math.min(1, corner.x)));
        maxX = Math.max(maxX, Math.max(-1, Math.min(1, corner.x)));
        minY = Math.min(minY, Math.max(-1, Math.min(1, corner.y)));
        maxY = Math.max(maxY, Math.max(-1, Math.min(1, corner.y)));
        hasProjectedCorner = true;
      }}
      if (!hasProjectedCorner) continue;
      const projectedWidth = Math.max(0, (maxX - minX) / 2);
      const projectedHeight = Math.max(0, (maxY - minY) / 2);
      const projectedArea = projectedWidth * projectedHeight;
      projectedCoverage += projectedArea;
      maxProjectedArea = Math.max(maxProjectedArea, projectedArea);
    }}
    let visiblePhotoPanelCount = 0;
    let projectedPhotoCoverage = 0;
    for (const panel of photoPanelPlanes) {{
      const box = new THREE.Box3().setFromObject(panel);
      if (!frustum.intersectsBox(box)) continue;
      visiblePhotoPanelCount += 1;
      const corners = [
        [box.min.x, box.min.y, box.min.z],
        [box.min.x, box.min.y, box.max.z],
        [box.min.x, box.max.y, box.min.z],
        [box.min.x, box.max.y, box.max.z],
        [box.max.x, box.min.y, box.min.z],
        [box.max.x, box.min.y, box.max.z],
        [box.max.x, box.max.y, box.min.z],
        [box.max.x, box.max.y, box.max.z],
      ];
      let minX = 1;
      let maxX = -1;
      let minY = 1;
      let maxY = -1;
      let hasProjectedCorner = false;
      for (const [x, y, z] of corners) {{
        corner.set(x, y, z).project(camera);
        if (!Number.isFinite(corner.x) || !Number.isFinite(corner.y)) continue;
        minX = Math.min(minX, Math.max(-1, Math.min(1, corner.x)));
        maxX = Math.max(maxX, Math.max(-1, Math.min(1, corner.x)));
        minY = Math.min(minY, Math.max(-1, Math.min(1, corner.y)));
        maxY = Math.max(maxY, Math.max(-1, Math.min(1, corner.y)));
        hasProjectedCorner = true;
      }}
      if (!hasProjectedCorner) continue;
      const projectedWidth = Math.max(0, (maxX - minX) / 2);
      const projectedHeight = Math.max(0, (maxY - minY) / 2);
      projectedPhotoCoverage += projectedWidth * projectedHeight;
    }}
    let visibleStagingObjectCount = 0;
    let projectedStagingCoverage = 0;
    for (const object of stagingObjects) {{
      if (!object.visible) continue;
      const box = new THREE.Box3().setFromObject(object);
      if (!frustum.intersectsBox(box)) continue;
      visibleStagingObjectCount += 1;
      const corners = [
        [box.min.x, box.min.y, box.min.z],
        [box.min.x, box.min.y, box.max.z],
        [box.min.x, box.max.y, box.min.z],
        [box.min.x, box.max.y, box.max.z],
        [box.max.x, box.min.y, box.min.z],
        [box.max.x, box.min.y, box.max.z],
        [box.max.x, box.max.y, box.min.z],
        [box.max.x, box.max.y, box.max.z],
      ];
      let minX = 1;
      let maxX = -1;
      let minY = 1;
      let maxY = -1;
      let hasProjectedCorner = false;
      for (const [x, y, z] of corners) {{
        corner.set(x, y, z).project(camera);
        if (!Number.isFinite(corner.x) || !Number.isFinite(corner.y)) continue;
        minX = Math.min(minX, Math.max(-1, Math.min(1, corner.x)));
        maxX = Math.max(maxX, Math.max(-1, Math.min(1, corner.x)));
        minY = Math.min(minY, Math.max(-1, Math.min(1, corner.y)));
        maxY = Math.max(maxY, Math.max(-1, Math.min(1, corner.y)));
        hasProjectedCorner = true;
      }}
      if (!hasProjectedCorner) continue;
      const projectedWidth = Math.max(0, (maxX - minX) / 2);
      const projectedHeight = Math.max(0, (maxY - minY) / 2);
      projectedStagingCoverage += projectedWidth * projectedHeight;
    }}
      return {{
        ready: true,
        frameCount: Number(renderFrameCount || 0),
        wallRectCount: Number(wallRectangles.length || 0),
        wallMeshCount: Number(wallMeshes.length || 0),
        cutawayWallCount: Number(cutawayWallCount || 0),
        hiddenCutawayWallCount: Number(hiddenCutawayWallCount || 0),
        visibleWallCount: Number(visibleWallCount || 0),
        routeStopCount: Number(routeStops.length || 0),
        activeRouteIndex: Number(activeRouteIndex ?? -1),
        viewMode: activeViewMode,
        captureMode: Boolean(captureMode),
        guidedQueryEnabled: Boolean(guidedQueryEnabled),
        guidedRouteActive: Boolean(guidedRouteState.active),
        guidedRouteCurrentIndex: Number(guidedRouteState.currentIndex ?? -1),
        guidedRouteDwellMs: Number(guidedRouteState.dwellMs || 0),
        isTransitioning: Boolean(routeCameraTransition.active),
        transitionProgressPct: Number((Math.max(0, Math.min(1, routeCameraTransition.progress || 0)) * 100).toFixed(1)),
        transitionTargetRouteIndex: Number(routeCameraTransition.targetRouteIndex ?? -1),
        transitionDurationMs: Number(routeCameraTransition.durationMs || 0),
        transitionTargetViewMode: String(routeCameraTransition.targetViewMode || activeViewMode),
        wallOpacity: Number(wallMaterial.opacity.toFixed(3)),
        wallHeightScale: Number((wallMeshes[0]?.scale.y || 0).toFixed(3)),
        photoPanelGroupVisible: Boolean(photoPanelGroup.visible),
        hotspotCount: Number(routeHotspots.length || 0),
      visibleHotspotCount: Number(syncRouteHotspots() || 0),
      captureOverlayVisible: Boolean(captureRouteCard && !captureRouteCard.hidden),
      captureRouteLabel: String(captureRouteLabel?.textContent || "").trim(),
      stagingObjectCount: Number(stagingObjects.length || 0),
      visibleStagingObjectCount: Number(visibleStagingObjectCount || 0),
      photoPanelCount: Number(photoPanelSpecs.length || 0),
      loadedPhotoTextureCount: Number(loadedPhotoTextureCount || 0),
      visiblePhotoPanelCount: Number(visiblePhotoPanelCount || 0),
      sceneChildCount: Number(scene.children.length || 0),
      sampleWidth: Number(canvas.width || 0),
      sampleHeight: Number(canvas.height || 0),
      projectedCoveragePct: Number((Math.min(1, projectedCoverage) * 100).toFixed(2)),
      projectedPhotoCoveragePct: Number((Math.min(1, projectedPhotoCoverage) * 100).toFixed(2)),
      projectedStagingCoveragePct: Number((Math.min(1, projectedStagingCoverage) * 100).toFixed(2)),
      maxProjectedWallPct: Number((Math.min(1, maxProjectedArea) * 100).toFixed(2)),
      renderCalls: Number(renderer.info.render.calls || 0),
      renderTriangles: Number(renderer.info.render.triangles || 0),
      cameraPosition: {{
        x: Number(camera.position.x.toFixed(3)),
        y: Number(camera.position.y.toFixed(3)),
        z: Number(camera.position.z.toFixed(3)),
      }},
    }};
}}

window.__pqReconstructionDebug = {{
  setOverviewView,
  setDollhouseView,
  setInsideView,
  setRouteView,
  startGuidedRoute,
  stopGuidedRoute,
  renderCaptureFrame,
  getLiveState: () => ({{ ...liveViewerState }}),
  getRenderMetrics,
}};

    function renderFrame(now = 0) {{
      const transitioned = stepCameraTransition(now);
      if (!transitioned) {{
        controls.update();
      }}
      renderer.render(scene, camera);
      syncRouteHotspots();
      renderFrameCount += 1;
      liveViewerState.ready = true;
      liveViewerState.frameCount = Number(renderFrameCount || 0);
      liveViewerState.routeStopCount = Number(routeStops.length || 0);
      liveViewerState.renderCalls = Number(renderer.info.render.calls || 0);
      liveViewerState.renderTriangles = Number(renderer.info.render.triangles || 0);
      if (shellProbeMode && !routeCameraTransition.active && renderFrameCount > 12) {{
        return;
      }}
      window.requestAnimationFrame(renderFrame);
    }}

    renderFrame(performance.now());
</script>
</body>
</html>
"""


def _write_viewer_walkthrough(
    target: Path,
    *,
    viewer_path: Path,
    expected_segments: list[str],
    route_stops: list[dict[str, object]],
    seconds_per_stop: float,
    style_label: str = "",
    floorplan_thumb: Image.Image | None = None,
    route_markers: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if sync_playwright is None:
        return {"status": "skipped", "reason": "playwright_missing"}
    if not viewer_path.is_file():
        return {"status": "skipped", "reason": "viewer_html_missing"}
    storyboard_steps = _viewer_storyboard_steps(expected_segments, route_stops=route_stops)
    if not storyboard_steps:
        return {"status": "skipped", "reason": "viewer_storyboard_unavailable"}

    fps = 12
    capture_frame_count = 6
    segment_frame_count = max(1, capture_frame_count)
    total_frame_count = max(1, segment_frame_count * len(storyboard_steps))
    duration_seconds = len(storyboard_steps) * seconds_per_stop
    input_fps = max(1.0, segment_frame_count / max(seconds_per_stop, 0.001))
    sidecar_path = target.with_suffix(".quality.json")
    last_metrics: dict[str, object] = {}
    move_phase_ratio = 0.42
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle_root = viewer_path.parent.parent

    with tempfile.TemporaryDirectory(prefix="propertyquarry-viewer-walkthrough-", dir=str(target.parent)) as tempdir:
        working_dir = Path(tempdir)
        frames_dir = working_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        try:
            with _serve_directory(bundle_root) as base_url:
                viewer_relpath = viewer_path.relative_to(bundle_root).as_posix()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**_playwright_chromium_launch_kwargs(playwright))
                    page = browser.new_page(
                        viewport={"width": WALKTHROUGH_VIEWPORT_SIZE[0], "height": WALKTHROUGH_VIEWPORT_SIZE[1]},
                        device_scale_factor=1,
                    )
                    try:
                        page.goto(f"{base_url}/{viewer_relpath}?capture=1", wait_until="domcontentloaded")
                        _wait_for_playwright_condition(
                            page,
                            """() => {
                              const debug = window.__pqReconstructionDebug;
                              if (!debug || typeof debug.getRenderMetrics !== 'function') {
                                return false;
                              }
                              const metrics = debug.getRenderMetrics();
                              const photoPanelCount = Number(metrics.photoPanelCount || 0);
                              const loadedPhotoTextureCount = Number(metrics.loadedPhotoTextureCount || 0);
                              return Boolean(metrics.ready)
                                && Number(metrics.frameCount || 0) >= 2
                                && Number(metrics.renderCalls || 0) > 0
                                && Number(metrics.renderTriangles || 0) > 0
                                && (photoPanelCount === 0 || loadedPhotoTextureCount >= Math.min(photoPanelCount, 2));
                            }""",
                            timeout_ms=45_000,
                        )
                        page.wait_for_timeout(180)
                        previous_state: dict[str, object] = {"viewMode": "overview"}
                        frame_index = 0
                        for step in storyboard_steps:
                            next_state = dict(step.get("state") or {})
                            for segment_index in range(segment_frame_count):
                                phase = segment_index / max(segment_frame_count - 1, 1)
                                progress = min(1.0, phase / move_phase_ratio) if move_phase_ratio > 0 else 1.0
                                frame_payload = page.evaluate(
                                    """(payload) => {
                                      const debug = window.__pqReconstructionDebug;
                                      if (!debug || typeof debug.renderCaptureFrame !== 'function') {
                                        return {
                                          metrics: { ready: false, reason: 'render_capture_frame_unavailable' },
                                          imageDataUrl: '',
                                        };
                                      }
                                      const metrics = debug.renderCaptureFrame(payload);
                                      const canvas = document.querySelector('#viewport canvas');
                                      return {
                                        metrics,
                                        imageDataUrl: canvas && typeof canvas.toDataURL === 'function'
                                          ? canvas.toDataURL('image/jpeg', 0.92)
                                          : '',
                                      };
                                    }""",
                                    {
                                        "from": previous_state,
                                        "to": next_state,
                                        "routeIndex": next_state.get("routeIndex"),
                                        "progress": progress,
                                        "overlay": {
                                            "kicker": "Room route",
                                            "label": str(step.get("label") or ""),
                                            "sequence": int(step.get("sequence") or 0),
                                            "total": int(step.get("total") or 0),
                                        },
                                    },
                                )
                                frame_row = dict(frame_payload or {}) if isinstance(frame_payload, dict) else {}
                                metrics = frame_row.get("metrics") if isinstance(frame_row.get("metrics"), dict) else {}
                                last_metrics = dict(metrics or {}) if isinstance(metrics, dict) else {}
                                if last_metrics.get("ready") is not True:
                                    raise RuntimeError(str(last_metrics.get("reason") or "viewer_render_not_ready"))
                                image_data_url = str(frame_row.get("imageDataUrl") or "").strip()
                                if not image_data_url.startswith("data:image/jpeg;base64,"):
                                    raise RuntimeError("viewer_frame_capture_unavailable")
                                frame_path = frames_dir / f"frame-{frame_index:05d}.jpg"
                                frame_bytes = base64.b64decode(image_data_url.split(",", 1)[1])
                                with Image.open(io.BytesIO(frame_bytes)) as rendered:
                                    decorated = _decorate_viewer_walkthrough_frame(
                                        rendered,
                                        label=str(step.get("label") or ""),
                                        sequence=int(step.get("sequence") or 0),
                                        total=int(step.get("total") or 0),
                                        style_label=style_label,
                                        floorplan_thumb=floorplan_thumb,
                                        route_markers=route_markers,
                                    )
                                    decorated.save(frame_path, format="JPEG", quality=92, optimize=True)
                                frame_index += 1
                            previous_state = next_state
                    finally:
                        browser.close()
        except PlaywrightTimeoutError:
            if target.exists():
                target.unlink()
            return {"status": "failed", "reason": "viewer_capture_timeout"}
        except Exception as exc:
            if target.exists():
                target.unlink()
            return {"status": "failed", "reason": f"viewer_capture_failed:{exc.__class__.__name__}"}

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {"status": "skipped", "reason": "ffmpeg_missing"}
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-framerate",
                    f"{input_fps:.3f}",
                    "-i",
                    str(frames_dir / "frame-%05d.jpg"),
                    "-vf",
                    f"fps={fps}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(target),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(120, int(duration_seconds * 2.5)),
            )
        except subprocess.TimeoutExpired:
            if target.exists():
                target.unlink()
            return {"status": "failed", "reason": "ffmpeg_timeout"}
    if result.returncode != 0:
        if target.exists():
            target.unlink()
        return {"status": "failed", "reason": (result.stderr or "ffmpeg_failed")[-500:]}

    duration = _video_duration_seconds(target)
    coverage = {
        "status": "pass",
        "source": "propertyquarry_generated_reconstruction_viewer_capture",
        "segments_expected": expected_segments,
        "segments_visited": expected_segments,
        "coverage_segments": [
            {
                "segment": label,
                "index": index + 1,
                "start": round(min(duration, index * seconds_per_stop), 3),
                "end": round(min(duration, (index + 1) * seconds_per_stop), 3),
            }
            for index, label in enumerate(expected_segments)
        ],
    }
    sidecar = {
        "provider": "PropertyQuarry generated reconstruction",
        "provider_key": "propertyquarry_generated_reconstruction",
        "composition": "viewer_route_storyboard",
        "motion_style": "threejs_layout_flythrough",
        "style_label": style_label,
        "duration_seconds": round(duration, 3),
        "seconds_per_stop": seconds_per_stop,
        "fps": fps,
        "transition_style": "dolly_then_hold",
        "transition_duration_seconds": round(seconds_per_stop * move_phase_ratio, 3),
        "room_stop_count": len(expected_segments),
        "walkthrough_card_count": len(expected_segments),
        "route_map_embedded": floorplan_thumb is not None and bool(route_markers),
        "route_context_mode": (
            "viewer_capture_floorplan_inset_active_stop"
            if floorplan_thumb is not None and bool(route_markers)
            else "capture_overlay_route_progress"
        ),
        "route_labels": expected_segments,
        "covered_route_labels": expected_segments,
        "viewer_capture_mode": True,
        "viewer_capture_metrics": {
            key: value
            for key, value in last_metrics.items()
            if key
            in {
                "wallMeshCount",
                "visibleWallCount",
                "photoPanelCount",
                "loadedPhotoTextureCount",
                "captureMode",
                "captureRouteLabel",
                "projectedCoveragePct",
                "projectedPhotoCoveragePct",
                "renderTriangles",
            }
        },
        "walkthrough_coverage_proof": coverage,
        "disclosure": DISCLOSURE,
    }
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "generated",
        "relpath": target.name,
        "sidecar_relpath": sidecar_path.name,
        "sha256": _sha256(target),
        "sidecar_sha256": _sha256(sidecar_path),
        "size_bytes": target.stat().st_size,
        "duration_seconds": round(duration, 3),
        "composition": str(sidecar.get("composition") or ""),
        "motion_style": str(sidecar.get("motion_style") or ""),
        "coverage_proof": coverage,
    }


def _stop_card_motion_window(
    *,
    stop_index: int,
    label: str,
    card_size: tuple[int, int],
    viewport_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    card_w, card_h = card_size
    viewport_w, viewport_h = viewport_size
    x_margin = max(0, card_w - viewport_w)
    y_margin = max(0, card_h - viewport_h)
    label_kind = _route_label_kind(label)
    x_span = min(float(x_margin), 36.0 if label_kind in {"living", "dining", "kitchen"} else 28.0)
    y_span = min(float(y_margin), 18.0 if label_kind in {"bath", "toilet", "storage"} else 12.0)
    if stop_index % 2 == 0:
        x_start = min(float(x_margin), 18.0)
        x_end = min(float(x_margin), x_start + x_span)
    else:
        x_end = max(0.0, float(x_margin) - 18.0)
        x_start = max(0.0, x_end - x_span)
    y_start = min(float(y_margin), 12.0 + ((stop_index % 3) * 4.0))
    y_end = min(float(y_margin), y_start + y_span)
    return x_start, x_end, y_start, y_end


def _render_stop_card_motion_frame(
    card_image: Image.Image,
    *,
    motion_window: tuple[float, float, float, float],
    progress: float,
    viewport_size: tuple[int, int],
) -> Image.Image:
    viewport_w, viewport_h = viewport_size
    x_start, x_end, y_start, y_end = motion_window
    x = x_start + ((x_end - x_start) * progress)
    y = y_start + ((y_end - y_start) * progress)
    max_x = max(0, card_image.width - viewport_w)
    max_y = max(0, card_image.height - viewport_h)
    left = int(round(_clamp_float(x, 0.0, float(max_x))))
    top = int(round(_clamp_float(y, 0.0, float(max_y))))
    return card_image.crop((left, top, left + viewport_w, top + viewport_h)).convert("RGB")


def _write_stop_card_walkthrough(
    target: Path,
    images: list[Path],
    *,
    style_label: str = "",
    route_labels: list[str] | tuple[str, ...] = (),
    room_count: int = 0,
    walkable_scene: dict[str, object] | None = None,
) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "skipped", "reason": "ffmpeg_missing"}
    if not images:
        return {"status": "skipped", "reason": "source_images_missing"}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="propertyquarry-reconstruction-", dir=str(target.parent)) as tempdir:
        working_dir = Path(tempdir)
        try:
            seconds_per_stop = float(
                os.getenv("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP")
                or os.getenv("PROPERTYQUARRY_FLYTHROUGH_SECONDS_PER_ROUTE_STOP")
                or "5"
            )
        except Exception:
            seconds_per_stop = 5.0
        seconds_per_stop = max(5.0, min(30.0, seconds_per_stop))
        normalized_route_labels = [
            _compact_route_label(label)
            for label in list(route_labels or [])
            if _compact_route_label(label)
        ]
        floorplan_image = images[0] if len(images) > 1 else None
        photo_images = list(images[1:]) if len(images) > 1 else list(images)
        expected_segments = list(normalized_route_labels)
        if not expected_segments:
            fallback_stop_count = max(_numeric_room_count(room_count), len(photo_images) or len(images))
            if fallback_stop_count <= 0:
                fallback_stop_count = 1
            expected_segments = [f"Room view {index:02d}" for index in range(1, fallback_stop_count + 1)]
        duration_seconds = min(240.0, max(seconds_per_stop, len(expected_segments) * seconds_per_stop))
        fps = 12
        segment_frame_count = max(1, int(round(seconds_per_stop * fps)))
        total_frame_count = max(1, segment_frame_count * max(1, len(expected_segments)))
        duration_seconds = total_frame_count / fps
        viewport_w, viewport_h = WALKTHROUGH_VIEWPORT_SIZE
        card_w, card_h = WALKTHROUGH_CARD_SIZE

        floorplan_thumb = _walkthrough_floorplan_thumb(floorplan_image)
        route_markers = _walkthrough_route_markers(expected_segments, walkable_scene=walkable_scene)

        stop_card_paths: list[Path] = []
        source_images = photo_images or list(images)
        for index, label in enumerate(expected_segments):
            image_path = source_images[index % max(len(source_images), 1)]
            supporting_path = None
            if len(photo_images) > 1:
                supporting_index = (index + 1) % len(photo_images)
                candidate = photo_images[supporting_index]
                if candidate != image_path:
                    supporting_path = candidate
            card_path = working_dir / f"walkthrough-stop-{index + 1:02d}.jpg"
            stop_card = _render_walkthrough_stop_card(
                stop_index=index,
                label=label,
                expected_segments=expected_segments,
                source_path=image_path,
                supporting_path=supporting_path,
                floorplan_thumb=floorplan_thumb,
                route_markers=route_markers,
                style_label=style_label,
            )
            stop_card.save(card_path, format="JPEG", quality=92)
            stop_card_paths.append(card_path)

        try:
            configured_timeout_seconds = int(
                float(str(os.getenv("PROPERTYQUARRY_RECONSTRUCTION_FFMPEG_TIMEOUT_SECONDS") or "0").strip() or "0")
            )
        except Exception:
            configured_timeout_seconds = 0
        timeout_seconds = max(300, int(duration_seconds * 8), configured_timeout_seconds)
        transition_duration = min(0.8, max(0.35, seconds_per_stop / 20.0)) if len(stop_card_paths) > 1 else 0.0
        transition_frame_count = int(round(transition_duration * fps)) if transition_duration > 0 else 0
        try:
            frames_dir = working_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            card_images = [Image.open(path).convert("RGB") for path in stop_card_paths]
            motion_windows = [
                _stop_card_motion_window(
                    stop_index=index,
                    label=expected_segments[index],
                    card_size=(card_w, card_h),
                    viewport_size=(viewport_w, viewport_h),
                )
                for index in range(len(stop_card_paths))
            ]
            frame_index = 0
            for index, card_image in enumerate(card_images):
                next_image = card_images[index + 1] if index + 1 < len(card_images) else None
                incoming_transition_frames = transition_frame_count if index > 0 else 0
                transition_frames_for_segment = transition_frame_count if next_image is not None else 0
                steady_frame_count = max(
                    1,
                    segment_frame_count - incoming_transition_frames - transition_frames_for_segment,
                )
                for steady_index in range(steady_frame_count):
                    progress = steady_index / max(steady_frame_count - 1, 1)
                    frame = _render_stop_card_motion_frame(
                        card_image,
                        motion_window=motion_windows[index],
                        progress=progress,
                        viewport_size=(viewport_w, viewport_h),
                    )
                    frame.save(frames_dir / f"frame-{frame_index:05d}.jpg", format="JPEG", quality=92, optimize=True)
                    frame_index += 1
                if next_image is None or transition_frames_for_segment <= 0:
                    continue
                current_frame = _render_stop_card_motion_frame(
                    card_image,
                    motion_window=motion_windows[index],
                    progress=1.0,
                    viewport_size=(viewport_w, viewport_h),
                )
                next_frame = _render_stop_card_motion_frame(
                    next_image,
                    motion_window=motion_windows[index + 1],
                    progress=0.0,
                    viewport_size=(viewport_w, viewport_h),
                )
                for transition_index in range(transition_frames_for_segment):
                    alpha = (transition_index + 1) / max(transition_frames_for_segment + 1, 1)
                    frame = Image.blend(current_frame, next_frame, alpha)
                    frame.save(frames_dir / f"frame-{frame_index:05d}.jpg", format="JPEG", quality=92, optimize=True)
                    frame_index += 1
            for card_image in card_images:
                card_image.close()

            command = [
                ffmpeg,
                "-y",
                "-framerate",
                str(fps),
                "-i",
                str(frames_dir / "frame-%05d.jpg"),
            ]
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(target),
                ]
            )
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            if target.exists():
                target.unlink()
            return {"status": "failed", "reason": "ffmpeg_timeout"}
    if result.returncode != 0:
        if target.exists():
            target.unlink()
        return {"status": "failed", "reason": (result.stderr or "ffmpeg_failed")[-500:]}
    duration = _video_duration_seconds(target)
    sidecar_path = target.with_suffix(".quality.json")
    coverage_step_seconds = max(0.0, seconds_per_stop - transition_duration)
    coverage = {
        "status": "pass",
        "source": "propertyquarry_generated_reconstruction_stop_cards",
        "segments_expected": expected_segments,
        "segments_visited": expected_segments,
        "coverage_segments": [
            {
                "segment": label,
                "index": index + 1,
                "start": round(min(duration, index * coverage_step_seconds), 3),
                "end": round(min(duration, (index * coverage_step_seconds) + seconds_per_stop), 3),
            }
            for index, label in enumerate(expected_segments)
        ],
    }
    sidecar = {
        "provider": "PropertyQuarry generated reconstruction",
        "provider_key": "propertyquarry_generated_reconstruction",
        "composition": "route_focused_stop_cards",
        "motion_style": "ken_burns_route_cards",
        "style_label": style_label,
        "duration_seconds": round(duration, 3),
        "seconds_per_stop": seconds_per_stop,
        "transition_style": "crossfade" if transition_duration > 0 else "hard_cut",
        "transition_duration_seconds": round(transition_duration, 3),
        "room_stop_count": len(expected_segments),
        "walkthrough_card_count": len(stop_card_paths),
        "route_map_embedded": floorplan_thumb is not None and bool(route_markers),
        "route_context_mode": "floorplan_inset_active_stop" if floorplan_thumb is not None and bool(route_markers) else "text_only_progress",
        "route_labels": expected_segments,
        "covered_route_labels": expected_segments,
        "walkthrough_coverage_proof": coverage,
        "disclosure": DISCLOSURE,
    }
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "generated",
        "relpath": target.name,
        "sidecar_relpath": sidecar_path.name,
        "sha256": _sha256(target),
        "sidecar_sha256": _sha256(sidecar_path),
        "size_bytes": target.stat().st_size,
        "duration_seconds": round(duration, 3),
        "composition": str(sidecar.get("composition") or ""),
        "motion_style": str(sidecar.get("motion_style") or ""),
        "coverage_proof": coverage,
    }


def _write_walkthrough(
    target: Path,
    images: list[Path],
    *,
    style_label: str = "",
    route_labels: list[str] | tuple[str, ...] = (),
    room_count: int = 0,
    walkable_scene: dict[str, object] | None = None,
    viewer_path: Path | None = None,
) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "skipped", "reason": "ffmpeg_missing"}
    if not images:
        return {"status": "skipped", "reason": "source_images_missing"}

    try:
        seconds_per_stop = float(
            os.getenv("PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP")
            or os.getenv("PROPERTYQUARRY_FLYTHROUGH_SECONDS_PER_ROUTE_STOP")
            or "5"
        )
    except Exception:
        seconds_per_stop = 5.0
    seconds_per_stop = max(5.0, min(30.0, seconds_per_stop))
    normalized_route_labels = [
        _compact_route_label(label)
        for label in list(route_labels or [])
        if _compact_route_label(label)
    ]
    expected_segments = list(normalized_route_labels)
    if not expected_segments:
        photo_images = list(images[1:]) if len(images) > 1 else list(images)
        fallback_stop_count = max(_numeric_room_count(room_count), len(photo_images) or len(images))
        if fallback_stop_count <= 0:
            fallback_stop_count = 1
        expected_segments = [f"Room view {index:02d}" for index in range(1, fallback_stop_count + 1)]

    route_stops = (
        [dict(stop) for stop in list((walkable_scene or {}).get("route") or []) if isinstance(stop, dict)]
        if isinstance(walkable_scene, dict)
        else []
    )
    floorplan_image = images[0] if len(images) > 1 else None
    floorplan_thumb = _walkthrough_floorplan_thumb(floorplan_image)
    route_markers = _walkthrough_route_markers(expected_segments, walkable_scene=walkable_scene)
    viewer_walkthrough_required = _env_flag("PROPERTYQUARRY_RECONSTRUCTION_VIEWER_WALKTHROUGH_REQUIRED")
    viewer_walkthrough_disabled = _env_flag("PROPERTYQUARRY_RECONSTRUCTION_DISABLE_VIEWER_WALKTHROUGH")
    viewer_walkthrough_runtime_default_disabled = (
        str(os.getenv("EA_ROLE") or "").strip().lower() == "render-tools"
        and not viewer_walkthrough_required
        and not _env_flag("PROPERTYQUARRY_RECONSTRUCTION_ENABLE_VIEWER_WALKTHROUGH")
    )
    viewer_walkthrough_enabled = (
        viewer_walkthrough_required
        or _env_flag("PROPERTYQUARRY_RECONSTRUCTION_ENABLE_VIEWER_WALKTHROUGH")
        or (
            viewer_path is not None
            and sync_playwright is not None
            and not viewer_walkthrough_disabled
            and not viewer_walkthrough_runtime_default_disabled
        )
    )
    if viewer_walkthrough_enabled and viewer_path is not None:
        viewer_receipt = _write_viewer_walkthrough(
            target,
            viewer_path=viewer_path,
            expected_segments=expected_segments,
            route_stops=route_stops,
            seconds_per_stop=seconds_per_stop,
            style_label=style_label,
            floorplan_thumb=floorplan_thumb,
            route_markers=route_markers,
        )
        if viewer_receipt.get("status") == "generated":
            return viewer_receipt
        if viewer_walkthrough_required:
            return viewer_receipt

    return _write_stop_card_walkthrough(
        target,
        images,
        style_label=style_label,
        route_labels=expected_segments,
        room_count=room_count,
        walkable_scene=walkable_scene,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PropertyQuarry reconstruction from a floorplan image and photos.")
    parser.add_argument("--slug", required=True, help="Existing PropertyQuarry public tour slug.")
    parser.add_argument("--floorplan", default="", help="Floorplan image. PDF support is intentionally not implied here.")
    parser.add_argument("--photo", action="append", default=[], help="Source property photo. Can be provided multiple times.")
    parser.add_argument("--target-subdir", default="generated-reconstruction")
    parser.add_argument("--max-width-m", type=float, default=10.0)
    parser.add_argument("--style-label", default="", help="Human-readable staging style label for receipts and walkthrough overlays.")
    parser.add_argument("--room-label", action="append", default=[], help="Optional explicit walkthrough stop label. Can be provided multiple times.")
    parser.add_argument("--room-count", type=int, default=0, help="Optional explicit walkthrough stop count when no labels are available.")
    parser.add_argument(
        "--infer-floorplan-from-photos",
        action="store_true",
        help="Generate a disclosed schematic floorplan when no real floorplan image is available.",
    )
    parser.add_argument("--skip-video", action="store_true")
    args = parser.parse_args()

    slug = _safe_relpath(args.slug)
    if "/" in slug or not slug:
        raise SystemExit("invalid_tour_slug")
    public_root = _public_tour_dir()
    bundle_dir = public_root / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise SystemExit("tour_manifest_missing")
    target_subdir = _safe_relpath(args.target_subdir) or "generated-reconstruction"
    output_dir = (bundle_dir / target_subdir).resolve()
    if bundle_dir.resolve() not in output_dir.parents:
        raise SystemExit("invalid_reconstruction_target")
    output_dir.mkdir(parents=True, exist_ok=True)

    photo_sources = [Path(value).expanduser().resolve() for value in args.photo or []]
    floorplan_arg = str(args.floorplan or "").strip()
    if floorplan_arg:
        floorplan_source = Path(floorplan_arg).expanduser().resolve()
        if not floorplan_source.is_file():
            raise SystemExit("floorplan_missing")
        floorplan_target = output_dir / f"source-floorplan{_web_safe_image_suffix(floorplan_source)}"
        floorplan_meta = _copy_normalized_image(floorplan_source, floorplan_target)
        floorplan_meta["relpath"] = floorplan_target.name
    elif args.infer_floorplan_from_photos:
        if not photo_sources:
            raise SystemExit("floorplan_or_photos_required")
        floorplan_target = output_dir / "source-floorplan-inferred.jpg"
        floorplan_meta = _write_inferred_floorplan(floorplan_target, photo_count=len(photo_sources))
    else:
        raise SystemExit("floorplan_missing")

    photo_rows: list[dict[str, object]] = []
    photo_paths: list[Path] = []
    for index, source in enumerate(photo_sources, start=1):
        if not source.is_file():
            raise SystemExit(f"photo_missing:{index}")
        target = output_dir / f"photo-{index:02d}{_web_safe_image_suffix(source)}"
        row = _copy_normalized_image(source, target)
        row["relpath"] = target.name
        row["index"] = index
        photo_rows.append(row)
        photo_paths.append(target)

    geometry = _extract_floorplan_geometry(floorplan_target)
    geometry_content_size = dict(geometry.get("content_size_px") or {})
    width_m, depth_m, height_m = _room_dimensions(
        int(geometry_content_size.get("width") or floorplan_meta["width"]),
        int(geometry_content_size.get("height") or floorplan_meta["height"]),
        max_width_m=max(3.0, float(args.max_width_m)),
    )
    wall_rectangles = _wall_rectangles_from_mask(
        list(geometry.get("wall_mask") or []),
        width_m=width_m,
        depth_m=depth_m,
    )

    _write_obj(
        output_dir,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
        wall_rectangles=wall_rectangles,
    )
    glb_export = _write_glb_with_blender(output_dir)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("invalid_tour_manifest")
    source_images = [floorplan_target, *photo_paths]
    route_labels = _reconstruction_walkthrough_route_labels(
        payload,
        explicit_labels=list(args.room_label or []),
        explicit_room_count=int(args.room_count or 0),
    )
    walkthrough_route_labels = _walkthrough_stop_labels(route_labels, target_stop_count=len(photo_rows))
    walkable_scene = _reconstruction_walkable_scene(
        route_labels=route_labels,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
        geometry=geometry,
    )
    photo_reference_panels = _generated_reconstruction_photo_reference_panels(
        photos=photo_rows,
        walkable_scene=walkable_scene,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
    )
    style_label = str(args.style_label or "").strip()
    diorama_preview = _write_generated_reconstruction_diorama_preview(
        bundle_dir / "diorama-preview.png",
        floorplan_path=floorplan_target,
        photo_paths=photo_paths,
        walkable_scene=walkable_scene,
        style_label=style_label,
    )
    telegram_preview = (
        _write_generated_reconstruction_telegram_preview(
            bundle_dir / "telegram-preview.png",
            source_path=bundle_dir / "diorama-preview.png",
            style_label=style_label,
        )
        if str(diorama_preview.get("status") or "").strip() == "generated"
        else {"status": "skipped", "reason": "diorama_preview_unavailable"}
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt: dict[str, object] = {
        "provider": "propertyquarry_generated_reconstruction",
        "generated_at": generated_at,
        "slug": slug,
        "disclosure": DISCLOSURE,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "style_label": style_label,
        "method": "floorplan_aspect_room_volume_with_source_photo_reference_panels",
        "room_dimensions_m": {"width": width_m, "depth": depth_m, "height": height_m},
        "geometry": {
            "content_bbox_px": dict(geometry.get("content_bbox_px") or {}),
            "content_size_px": dict(geometry.get("content_size_px") or {}),
            "mask_size_cells": dict(geometry.get("mask_size_cells") or {}),
            "wall_rectangles": wall_rectangles,
            "wall_rect_count": len(wall_rectangles),
        },
        "floorplan": floorplan_meta,
        "photos": photo_rows,
        "walkable_scene": walkable_scene,
        "photo_reference_panels": photo_reference_panels,
        "model": {
            "obj_relpath": "model.obj",
            "mtl_relpath": "model.mtl",
            "obj_sha256": _sha256(output_dir / "model.obj"),
            "mtl_sha256": _sha256(output_dir / "model.mtl"),
            "glb_export": glb_export,
        },
        "viewer": {
            "relpath": "viewer.html",
            "version": VIEWER_VERSION,
            "photo_reference_panel_count": len(photo_reference_panels),
        },
        "bundle_preview_assets": {
            "diorama": diorama_preview,
            "telegram": telegram_preview,
        },
        "walkthrough": {"status": "pending", "reason": "viewer_render_not_started"},
        "route_labels": route_labels,
        "walkthrough_route_labels": walkthrough_route_labels,
    }
    if glb_export.get("status") == "generated":
        receipt["model"]["glb_relpath"] = str(glb_export.get("glb_relpath") or "model.glb")
        receipt["model"]["glb_sha256"] = str(glb_export.get("glb_sha256") or "")
        receipt["model"]["glb_size_bytes"] = int(glb_export.get("glb_size_bytes") or 0)
    vendor_assets = _copy_viewer_vendor_assets(output_dir)
    viewer_path = output_dir / "viewer.html"
    viewer_path.write_text(
        _viewer_html(
            manifest=receipt,
            three_relpath=str(vendor_assets.get("three_relpath") or "vendor/three.module.js"),
            orbit_controls_relpath=str(vendor_assets.get("orbit_controls_relpath") or "vendor/examples/jsm/controls/OrbitControls.js"),
        ),
        encoding="utf-8",
    )
    walkthrough = (
        {"status": "skipped", "reason": "skip_video_requested"}
        if args.skip_video
        else _write_walkthrough(
            output_dir / "generated-walkthrough.mp4",
            source_images,
            style_label=style_label,
            route_labels=walkthrough_route_labels,
            room_count=int(args.room_count or 0),
            walkable_scene=walkable_scene,
            viewer_path=viewer_path,
        )
    )
    receipt["walkthrough"] = walkthrough
    (output_dir / "reconstruction.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt["viewer"]["sha256"] = _sha256(output_dir / "viewer.html")
    (output_dir / "reconstruction.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base_relpath = PurePosixPath(target_subdir).as_posix()
    generated_reconstruction = {
        "provider": "propertyquarry_generated_reconstruction",
        "generated_at": generated_at,
        "viewer_version": VIEWER_VERSION,
        "viewer_relpath": f"{base_relpath}/viewer.html",
        "model_relpath": f"{base_relpath}/model.obj",
        "material_relpath": f"{base_relpath}/model.mtl",
        "manifest_relpath": f"{base_relpath}/reconstruction.json",
        "glb_export_status": str(glb_export.get("status") or ""),
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "disclosure": DISCLOSURE,
        "route_labels": route_labels,
        "room_stop_count": len(route_labels),
        "walkthrough_route_labels": walkthrough_route_labels,
        "walkthrough_stop_count": len(walkthrough_route_labels),
        "photo_reference_panel_count": len(photo_reference_panels),
        "walkable_scene": walkable_scene,
        "walkable_scene_kind": str(walkable_scene.get("kind") or "").strip(),
    }
    floorplan_relpath = str(dict(receipt.get("floorplan") or {}).get("relpath") or "").strip()
    if floorplan_relpath:
        generated_reconstruction["floorplan_relpath"] = f"{base_relpath}/{floorplan_relpath}"
    photo_relpaths = [
        f"{base_relpath}/{str(row.get('relpath') or '').strip()}"
        for row in list(receipt.get("photos") or [])
        if isinstance(row, dict) and str(row.get("relpath") or "").strip()
    ]
    if photo_relpaths:
        generated_reconstruction["photo_relpaths"] = photo_relpaths
    if glb_export.get("status") == "generated":
        generated_reconstruction["glb_model_relpath"] = f"{base_relpath}/{glb_export.get('glb_relpath') or 'model.glb'}"
    if str(diorama_preview.get("status") or "").strip() == "generated":
        generated_reconstruction["diorama_preview_bundle_relpath"] = str(diorama_preview.get("bundle_relpath") or "diorama-preview.png")
    if str(telegram_preview.get("status") or "").strip() == "generated":
        generated_reconstruction["telegram_preview_bundle_relpath"] = str(telegram_preview.get("bundle_relpath") or "telegram-preview.png")
    if walkthrough.get("status") == "generated":
        generated_reconstruction["walkthrough_video_relpath"] = f"{base_relpath}/generated-walkthrough.mp4"
        if str(args.style_label or "").strip():
            generated_reconstruction["walkthrough_style_label"] = str(args.style_label or "").strip()
        if str(walkthrough.get("composition") or "").strip():
            generated_reconstruction["walkthrough_composition"] = str(walkthrough.get("composition") or "").strip()
        if str(walkthrough.get("motion_style") or "").strip():
            generated_reconstruction["walkthrough_motion_style"] = str(walkthrough.get("motion_style") or "").strip()
        if walkthrough.get("sidecar_relpath"):
            generated_reconstruction["walkthrough_sidecar_relpath"] = f"{base_relpath}/{walkthrough.get('sidecar_relpath')}"
        if isinstance(walkthrough.get("coverage_proof"), dict):
            generated_reconstruction["walkthrough_coverage_proof"] = walkthrough["coverage_proof"]
    if route_labels:
        payload["room_visit_plan"] = route_labels
        payload["covered_route_labels"] = route_labels
    for key in (
        "video_relpath",
        "video_provider",
        "video_provider_key",
        "video_render_provider",
        "video_source",
        "video_sidecar_relpath",
        "video_coverage_proof",
    ):
        payload.pop(key, None)
    payload["generated_reconstruction"] = generated_reconstruction
    for relpath in dict.fromkeys(
        (
            f"{base_relpath}/{str(vendor_assets.get('three_relpath') or 'vendor/three.module.js')}",
            f"{base_relpath}/{str(vendor_assets.get('orbit_controls_relpath') or 'vendor/examples/jsm/controls/OrbitControls.js')}",
        )
    ):
        _upsert_public_asset(
            payload,
            relpath=relpath,
            role="generated_reconstruction_viewer_asset",
            privacy_class="generated_reconstruction_public",
            mime_type="text/javascript",
        )
    if str(diorama_preview.get("status") or "").strip() == "generated":
        payload["diorama_preview_relpath"] = str(diorama_preview.get("bundle_relpath") or "diorama-preview.png")
        payload["preview_relpath"] = str(diorama_preview.get("bundle_relpath") or "diorama-preview.png")
        _upsert_diorama_scene(payload, relpath=payload["diorama_preview_relpath"])
        _upsert_public_asset(
            payload,
            relpath=payload["diorama_preview_relpath"],
            role="diorama",
            mime_type="image/png",
        )
    if str(telegram_preview.get("status") or "").strip() == "generated":
        payload["telegram_preview_relpath"] = str(telegram_preview.get("bundle_relpath") or "telegram-preview.png")
        _upsert_public_asset(
            payload,
            relpath=payload["telegram_preview_relpath"],
            role="preview",
            mime_type="image/png",
        )
    if walkthrough.get("status") == "generated":
        payload["video_relpath"] = f"{base_relpath}/generated-walkthrough.mp4"
        payload["video_provider"] = "propertyquarry_generated_reconstruction"
        payload["video_provider_key"] = "propertyquarry_generated_reconstruction"
        payload["video_render_provider"] = "propertyquarry_generated_reconstruction"
        payload["video_source"] = "propertyquarry_generated_reconstruction"
        payload["video_coverage_proof"] = "boundary_verified_frame_continuation"
        if walkthrough.get("sidecar_relpath"):
            payload["video_sidecar_relpath"] = f"{base_relpath}/{walkthrough.get('sidecar_relpath')}"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runtime_publish = _sync_bundle_to_runtime_container(bundle_dir, slug=slug)
    runtime_publish_required = _runtime_publish_required()
    runtime_publish_ok = _runtime_publish_succeeded(runtime_publish)
    receipt["runtime_publish"] = runtime_publish
    receipt["runtime_publish_required"] = runtime_publish_required
    receipt["runtime_publish_ok"] = runtime_publish_ok
    (output_dir / "reconstruction.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    response = {
        "slug": slug,
        "provider": "propertyquarry_generated_reconstruction",
        "viewer_relpath": f"{base_relpath}/viewer.html",
        "model_relpath": f"{base_relpath}/model.obj",
        "diorama_preview_relpath": str(payload.get("diorama_preview_relpath") or ""),
        "telegram_preview_relpath": str(payload.get("telegram_preview_relpath") or ""),
        "public_tour_url": "",
        "satisfies_verified_tour_gate": False,
        "walkthrough_status": walkthrough.get("status"),
        "verified_provider_capture": False,
        "runtime_publish": runtime_publish,
        "runtime_publish_required": runtime_publish_required,
    }

    if runtime_publish_required and not runtime_publish_ok:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "runtime_publish_failed",
                    "local_bundle_generated": True,
                    **response,
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "generated",
                **response,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
