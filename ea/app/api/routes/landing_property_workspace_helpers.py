from __future__ import annotations

import urllib.parse
from typing import Any

from app.services.property_artifact_contracts import required_artifact_receipt_rows


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

    def _source_provider_group(source_row: dict[str, object]) -> str:
        provider_family = str(source_row.get("provider_family") or "").strip().lower()
        if provider_family:
            return provider_family
        platform = str(source_row.get("platform") or "").strip().lower()
        if platform:
            return platform
        label = str(source_row.get("source_label") or source_row.get("label") or "").strip()
        if "|" in label:
            label = label.split("|", 1)[0].strip()
        return label.casefold() or "provider"

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
            return "Retrying"
        if raw_status in {"running", "processing", "in_progress", "working", "warming"}:
            return "Running"
        if raw_status in {"queued", "pending", "starting"}:
            return "Up next"
        return "Waiting"

    active_sources = [
        row for row in source_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() not in {"completed", "processed", "done", "success", "failed", "error", "skipped"}
    ]
    completed_sources = [
        row for row in source_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() in {"completed", "processed", "done", "success"}
    ]
    queue = active_sources + completed_sources

    diversified_queue: list[dict[str, object]] = []
    seen_groups: set[str] = set()
    duplicate_counts: dict[str, int] = {}
    for source_row in queue:
        group_key = _source_provider_group(source_row)
        duplicate_counts[group_key] = duplicate_counts.get(group_key, 0) + 1
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        diversified_queue.append(source_row)
    for source_row in queue:
        group_key = _source_provider_group(source_row)
        if any(_source_provider_group(existing) == group_key for existing in diversified_queue):
            if source_row in diversified_queue:
                continue
        diversified_queue.append(source_row)
    queue = diversified_queue

    worker_rows: list[dict[str, object]] = []
    for index in range(visible_workers):
        source_row = queue[index] if index < len(queue) else {}
        source_label = str(source_row.get("source_label") or source_row.get("label") or "").strip()
        compact_label = _compact_provider_label(source_label)
        provider_group = _source_provider_group(source_row) if source_row else ""
        shard_count = max(0, int(duplicate_counts.get(provider_group, 0)) - 1) if provider_group else 0
        status_label = _source_status_label(source_row) if source_row else "Idle"
        progress = _source_progress(source_row) if source_row else 0
        worker_rows.append(
            {
                "label": compact_label if source_row else ("Waiting" if active_sources or source_rows else "Stand by"),
                "provider": source_label or ("Waiting for a source" if active_sources or source_rows else "Stand by"),
                "shard_count": shard_count,
                "status_label": status_label,
                "progress_pct": progress,
                "tone": "done" if progress >= 100 and source_row and status_label == "Done" else ("active" if status_label == "Running" else ("queued" if status_label in {"Up next", "Retrying"} else "idle")),
            }
        )

    upgrade_copy = ""
    if normalized_plan == "free":
        upgrade_copy = "Upgrade to Plus for 3 search workers or Agent for 6. Saved searches are a separate limit."
    elif normalized_plan == "plus":
        upgrade_copy = "Upgrade to Agent for 6 search workers. Saved searches are a separate limit."

    return {
        "plan_key": normalized_plan,
        "visible_workers": visible_workers,
        "slot_cap": slot_cap,
        "workers": worker_rows,
        "upgrade_copy": upgrade_copy,
        "tooltip": "Search workers are the parallel source lanes running this search right now. They are not the same thing as recurring saved searches.",
    }


def _compact_provider_label(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "Provider"
    for marker in ("|", "·", " — ", " – ", ":", "("):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    words = [part for part in text.split() if part]
    if len(words) > 3:
        text = " ".join(words[:3]).strip()
    if len(text) > 20 and len(words) >= 2:
        text = " ".join(words[:2]).strip()
    if len(text) > 20:
        text = f"{text[:17].rstrip()}..."
    return text or "Provider"


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


def _property_candidate_orientation_preview(candidate: dict[str, object]) -> dict[str, object]:
    from app.api.routes import landing_view_models

    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    label = str(
        facts.get("district")
        or facts.get("postal_name")
        or facts.get("city")
        or facts.get("address")
        or "Wider area"
    ).strip() or "Wider area"
    context_label = str(
        facts.get("postal_name")
        or facts.get("city")
        or facts.get("state")
        or facts.get("region")
        or label
    ).strip() or label
    country_code = str(
        facts.get("country_code")
        or facts.get("country")
        or candidate.get("country_code")
        or candidate.get("country")
        or ""
    ).strip()
    region_code = str(
        facts.get("city")
        or facts.get("postal_name")
        or facts.get("state")
        or facts.get("region")
        or ""
    ).strip().lower().replace(" ", "_")
    try:
        lat = float(facts.get("map_lat") or facts.get("lat") or 0.0)
    except Exception:
        lat = 0.0
    try:
        lng = float(facts.get("map_lng") or facts.get("lng") or 0.0)
    except Exception:
        lng = 0.0
    map_url = str(candidate.get("map_url") or "").strip() or _property_candidate_maps_url(candidate)
    if not (lat or lng):
        geocoded = landing_view_models._forward_geocode_preview_point(label)
        if geocoded:
            lat, lng = geocoded
    selected_labels: list[str] = []
    for raw_value in (facts.get("district"), facts.get("postal_name"), facts.get("city"), facts.get("address")):
        value = str(raw_value or "").strip()
        if value and value.casefold() not in {item.casefold() for item in selected_labels}:
            selected_labels.append(value)
    option_lookup = {item.casefold(): item for item in selected_labels}
    boundary_preview = landing_view_models._build_scope_boundary_preview(
        country_code=country_code.upper(),
        region_code=region_code,
        normalized_query=context_label,
        selected_labels=selected_labels[:1] or [label],
        selected_values=selected_labels[:1] or [label],
        option_lookup=option_lookup,
        market_label=context_label or label,
    )
    if boundary_preview:
        image_url = str(boundary_preview.get("image_url") or "").strip()
    elif lat or lng:
        image_url = landing_view_models._openstreetmap_static_preview_data_url(
            int(round(lat * 10000.0)),
            int(round(lng * 10000.0)),
        )
    else:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="368" viewBox="0 0 320 184" role="img" aria-label="Area map preview">'
            '<rect width="320" height="184" rx="18" fill="#ddd3c1"/>'
            '<rect x="12" y="12" width="296" height="160" rx="14" fill="#f4efe5" stroke="#c6baa7"/>'
            '<path d="M16 128 C54 104, 86 110, 120 96 S188 70, 236 58 S276 34, 304 22" fill="none" stroke="#cfc4b3" stroke-width="10" stroke-linecap="round"/>'
            '<path d="M26 42 C64 52, 98 42, 134 50 S210 66, 300 48" fill="none" stroke="#ddd5c6" stroke-width="6" stroke-linecap="round"/>'
            '<path d="M32 156 C68 144, 98 148, 134 136 S210 114, 292 126" fill="none" stroke="#d6cbbb" stroke-width="7" stroke-linecap="round"/>'
            '</svg>'
        )
        image_url = f"data:image/svg+xml;utf8,{urllib.parse.quote(svg, safe='/:;,+-=()%')}"
    alt = f"Wider area around {label}"
    caption = str(boundary_preview.get("summary") or "Open a larger area map").strip() if boundary_preview else "Open a larger area map"
    return {
        "image_url": image_url,
        "alt": alt,
        "title": label,
        "caption": caption,
        "map_url": map_url,
        "district_rows": list(boundary_preview.get("district_rows") or []) if boundary_preview else [],
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
) -> list[dict[str, object]]:
    counters = {
        "Outside selected area": 0,
        "Missing floorplan evidence": 0,
        "Below fit threshold": 0,
        "Outside area/size rule": 0,
        "Availability mismatch": 0,
        "Alert budget": 0,
    }
    source_labels: dict[str, set[str]] = {key: set() for key in counters}
    field_map = (
        ("Outside selected area", "location_mismatch_candidate_total"),
        ("Missing floorplan evidence", "filtered_floorplan_total"),
        ("Below fit threshold", "filtered_low_fit_total"),
        ("Outside area/size rule", "filtered_area_total"),
        ("Availability mismatch", "filtered_availability_total"),
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
        "Outside selected area": "Add nearby districts first instead of opening the full market.",
        "Missing floorplan evidence": "These homes are still being checked for a floorplan in photos, PDFs, downloads, and 360 media.",
        "Below fit threshold": "Lower the match bar a little if you want to see more borderline homes.",
        "Outside area/size rule": "Stretch the size or area rule only if the shortlist feels too thin.",
        "Availability mismatch": "Loosen the move-in timing if the date is flexible.",
        "Alert budget": "Raise the daily alert limit if you want more saved-search notifications.",
    }
    title_map = {
        "Outside selected area": "Include nearby districts",
        "Missing floorplan evidence": "Include homes while floorplans are still being checked",
        "Below fit threshold": "Lower the match bar",
        "Outside area/size rule": "Stretch the size rule",
        "Availability mismatch": "Loosen move-in timing",
        "Alert budget": "Raise the alert limit",
    }
    action_label_map = {
        "Outside selected area": "Set nearby radius",
        "Missing floorplan evidence": "Show held-back homes",
        "Below fit threshold": "See lower-fit homes",
        "Outside area/size rule": "Relax size",
        "Availability mismatch": "Edit move-in timing",
        "Alert budget": "Raise alerts",
    }
    rows: list[dict[str, str]] = []
    for label, total in counters.items():
        if total <= 0:
            continue
        providers = ", ".join(sorted(source_labels[label])[:3])
        rows.append(
            {
                "title": title_map.get(label, label),
                "rule_key": label,
                "detail": f"{total} candidate{' was' if total == 1 else 's were'} filtered out. {action_map[label]}",
                "tag": providers or "Search rule",
                "affected_total": total,
                "action_label": action_label_map.get(label, "Review rule"),
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
        lowered_title = title.lower()
        if "duplicate listing" in lowered_title or "wrong property type" in lowered_title:
            return {}
        if title.lower() in {"pending layout proof", "missing floorplan evidence"}:
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
                "title": "Include homes while floorplans are still being checked",
                "detail": f"{filtered_floorplan_total} listing(s) are being held back until a floorplan is verified. Use this only for a wider look, then turn the rule back on.",
                "tag": "Research",
                "action_label": "Show held-back homes",
                "adjustments": {"require_floorplan": False},
                "affected_total": filtered_floorplan_total,
            }
        )

    country_code = str(preferences.get("country_code") or "").strip().upper()
    region_code = str(preferences.get("region_code") or "").strip().lower()
    full_region_scope = bool(preferences.get("full_region_scope"))
    if country_code and region_code and not full_region_scope:
        try:
            from app.services.property_market_catalog import region_label_for_country_region
            region_label = region_label_for_country_region(country_code, region_code)
        except Exception:
            region_label = region_code.replace("_", " ").title()
        rows.append(
            {
                "title": "Add homes near the selected districts",
                "detail": f"Include homes within a small radius of the selected districts when they sit in adjacent parts of {region_label}.",
                "tag": "Area",
                "action_label": "Set nearby radius",
                "adjustments": {"full_region_scope": True, "location_query": region_label, "custom_location_query": "", "adjacent_area_radius_m": 750},
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
                "title": f"Check {len(widened_platforms)} sources instead of {len(selected_platforms)}",
                "detail": "Use the rest of the provider allowance on the current plan before widening the brief itself.",
                "tag": "Providers",
                "action_label": "Use all sources",
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
                "title": "Raise the budget once",
                "detail": "Use one wider price pass to see whether budget pressure is the real blocker.",
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
                "title": "Stretch the everyday distance limits",
                "detail": "Keep the same lifestyle intent but widen the walking distance enough to recover borderline homes.",
                "tag": "Alltag",
                "action_label": "Stretch distance",
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
