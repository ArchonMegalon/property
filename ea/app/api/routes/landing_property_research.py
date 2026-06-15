from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any

from app.api.routes.landing_property_workspace_helpers import (
    _candidate_detail_sections,
    _official_risk_posture_rows,
    _property_candidate_orientation_preview,
    _property_candidate_preview_image,
)
from app.product.property_location_research import property_school_context_summary
from app.product.projections.common import compact_text
from app.product.service import (
    _property_enrich_missing_fact_research,
    _property_investment_area_sqm,
    _property_investment_underwriting_payload,
    _property_investment_location_seed,
    _property_investment_price_eur,
    _property_investment_research_snapshot,
    _property_tour_control_link,
)


def _object_detail_row(
    title: str,
    detail: str,
    tag: str,
    href: str = "",
    action_href: str = "",
    action_label: str = "",
    action_value: str = "",
    action_method: str = "",
    return_to: str = "",
    secondary_action_href: str = "",
    secondary_action_label: str = "",
    secondary_action_value: str = "",
    secondary_action_method: str = "",
    secondary_return_to: str = "",
    tertiary_action_href: str = "",
    tertiary_action_label: str = "",
    tertiary_action_value: str = "",
    tertiary_action_method: str = "",
    tertiary_return_to: str = "",
    quaternary_action_href: str = "",
    quaternary_action_label: str = "",
    quaternary_action_value: str = "",
    quaternary_action_method: str = "",
    quaternary_return_to: str = "",
) -> dict[str, str]:
    row = {
        "title": str(title or "").strip(),
        "detail": str(detail or "").strip(),
        "tag": str(tag or "").strip(),
    }
    if href:
        row["href"] = href
    if action_href:
        row["action_href"] = action_href
    if action_label:
        row["action_label"] = action_label
    if action_value:
        row["action_value"] = action_value
    if action_method:
        row["action_method"] = action_method
    if return_to:
        row["return_to"] = return_to
    if secondary_action_href:
        row["secondary_action_href"] = secondary_action_href
    if secondary_action_label:
        row["secondary_action_label"] = secondary_action_label
    if secondary_action_value:
        row["secondary_action_value"] = secondary_action_value
    if secondary_action_method:
        row["secondary_action_method"] = secondary_action_method
    if secondary_return_to:
        row["secondary_return_to"] = secondary_return_to
    if tertiary_action_href:
        row["tertiary_action_href"] = tertiary_action_href
    if tertiary_action_label:
        row["tertiary_action_label"] = tertiary_action_label
    if tertiary_action_value:
        row["tertiary_action_value"] = tertiary_action_value
    if tertiary_action_method:
        row["tertiary_action_method"] = tertiary_action_method
    if tertiary_return_to:
        row["tertiary_return_to"] = tertiary_return_to
    if quaternary_action_href:
        row["quaternary_action_href"] = quaternary_action_href
    if quaternary_action_label:
        row["quaternary_action_label"] = quaternary_action_label
    if quaternary_action_value:
        row["quaternary_action_value"] = quaternary_action_value
    if quaternary_action_method:
        row["quaternary_action_method"] = quaternary_action_method
    if quaternary_return_to:
        row["quaternary_return_to"] = quaternary_return_to
    return row


def _evidence_detail_rows(items) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    rows: list[dict[str, str]] = []
    for item in items or ():
        rows.append(
            _object_detail_row(
                str(getattr(item, "note", "") or getattr(item, "ref", "") or "Supporting evidence"),
                str(getattr(item, "ref", "") or "No external reference attached."),
                str(getattr(item, "source_type", "") or "Evidence"),
            )
        )
    if rows:
        return rows
    return [_object_detail_row("No supporting evidence yet", "This object has no attached evidence refs yet.", "Pending")]


def _render_console_object_detail(
    *,
    request: Request,
    context: RequestContext,
    workspace_label: str,
    page_title: str,
    current_nav: str,
    console_title: str,
    console_summary: str,
    object_kind: str,
    object_title: str,
    object_summary: str,
    object_meta: list[dict[str, str]],
    object_media: dict[str, object] | None = None,
    object_ooda_title: str = "",
    object_ooda_copy: str = "",
    object_ooda_rows: list[dict[str, str]] | None = None,
    object_sidebar_kicker: str = "",
    object_sidebar_title: str,
    object_sidebar_copy: str,
    object_sidebar_rows: list[dict[str, str]],
    object_sections: list[dict[str, object]],
    object_sidebar_form: dict[str, object] | None = None,
    object_feedback: dict[str, object] | None = None,
) -> HTMLResponse:
    return _render_public_template(
        request,
        "app/object_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=page_title,
                current_nav=current_nav,
                context=context,
                console_title=console_title,
                console_summary=console_summary,
                nav_groups=app_nav_groups_for_brand(request_brand(request)["key"]),
                workspace_label=workspace_label,
                cards=[],
                stats=[{"label": item["label"], "value": item["value"]} for item in object_meta],
            ),
            "object_kind": object_kind,
            "object_title": object_title,
            "object_summary": object_summary,
            "object_meta": object_meta,
            "object_media": object_media or {},
            "object_ooda_title": object_ooda_title,
            "object_ooda_copy": object_ooda_copy,
            "object_ooda_rows": object_ooda_rows or [],
            "object_sidebar_kicker": object_sidebar_kicker,
            "object_sidebar_title": object_sidebar_title,
            "object_sidebar_copy": object_sidebar_copy,
            "object_sidebar_rows": object_sidebar_rows,
            "object_sections": object_sections,
            "object_sidebar_form": object_sidebar_form or {},
            "object_feedback": object_feedback or {},
        },
    )


def _property_candidate_ref(candidate: dict[str, object]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "source_ref", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _property_shortlist_candidates_from_context(property_context: dict[str, object]) -> list[dict[str, object]]:
    run_payload = dict(property_context.get("run") or {})
    run_summary = dict(run_payload.get("summary") or {})
    run_id = str(run_payload.get("run_id") or "").strip()
    packet_candidates: list[dict[str, object]] = []
    for source in list(run_summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for candidate in list(source.get("top_candidates") or [])[:5]:
            if not isinstance(candidate, dict):
                continue
            candidate_row = dict(candidate)
            candidate_row.setdefault("source_label", source_label)
            candidate_row.setdefault("property_facts", dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {})
            packet_ref = _property_candidate_ref(
                {
                    "title": str(candidate_row.get("title") or "").strip(),
                    "property_url": str(candidate_row.get("property_url") or "").strip(),
                    "review_url": str(candidate_row.get("review_url") or "").strip(),
                    "source_ref": str(candidate_row.get("source_ref") or "").strip(),
                    "source_label": source_label,
                }
            )
            packet_url = f"/app/research/{packet_ref}"
            if run_id:
                packet_url = f"{packet_url}?run_id={urllib.parse.quote(run_id, safe='')}"
            candidate_row.setdefault("packet_url", packet_url)
            packet_candidates.append(candidate_row)
    return packet_candidates


def _property_lookup_candidate(
    *,
    property_context: dict[str, object],
    candidate_ref: str,
) -> dict[str, object] | None:
    summary = dict(dict(property_context.get("run") or {}).get("summary") or {})
    for source in list(summary.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
        for raw_candidate in list(source.get("top_candidates") or []):
            if not isinstance(raw_candidate, dict):
                continue
            candidate = dict(raw_candidate)
            candidate.setdefault("source_label", source_label)
            if _property_candidate_ref(candidate) == candidate_ref:
                return candidate
    return None


def _property_enriched_candidate_facts(*, candidate: dict[str, object]) -> dict[str, object]:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    text = " | ".join(part for part in (title, summary) if part)
    if text:
        if "price_eur" not in facts:
            price_match = re.search(r"(?:€|EUR)\s*([\d\.\s]+(?:,\d+)?)", text, flags=re.IGNORECASE)
            if price_match:
                raw_amount = str(price_match.group(1) or "").strip().replace(" ", "")
                normalized_amount = raw_amount.replace(".", "").replace(",", ".")
                try:
                    facts["price_eur"] = float(normalized_amount)
                    facts.setdefault("price_display", compact_text(price_match.group(0), fallback=f"EUR {facts['price_eur']:.0f}", limit=120))
                except Exception:
                    pass
        if "area_m2" not in facts and "living_area_m2" not in facts:
            area_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2]", text, flags=re.IGNORECASE)
            if area_match:
                try:
                    facts["area_m2"] = float(str(area_match.group(1) or "").replace(",", "."))
                except Exception:
                    pass
        if "rooms" not in facts and "room_count" not in facts:
            rooms_match = re.search(r"(\d+(?:[.,]\d+)?)\s*[- ]?Zimmer", text, flags=re.IGNORECASE)
            if rooms_match:
                try:
                    facts["rooms"] = float(str(rooms_match.group(1) or "").replace(",", "."))
                except Exception:
                    pass
        if "postal_name" not in facts and "address" not in facts and "district" not in facts:
            postal_match = re.search(r"\((\d{4}\s+[A-Za-zÄÖÜäöüß][^)]*)\)", text)
            if postal_match:
                postal_name = str(postal_match.group(1) or "").strip()[:160]
                if postal_name:
                    facts["postal_name"] = postal_name
                    facts.setdefault("address", postal_name)
    return _property_enrich_missing_fact_research(
        facts=facts,
        property_url=str(candidate.get("property_url") or "").strip(),
        title=title,
        summary=summary,
        source_label=str(candidate.get("source_label") or "").strip(),
    )


def _property_missing_fact_items(facts: dict[str, object]) -> list[dict[str, object]]:
    research = facts.get("missing_fact_research")
    if not isinstance(research, dict):
        return []
    items = research.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _property_missing_fact_item(facts: dict[str, object], field: str) -> dict[str, object]:
    normalized = str(field or "").strip()
    for item in _property_missing_fact_items(facts):
        if str(item.get("field") or "").strip() == normalized:
            return item
    return {}


def _property_rooms_display(facts: dict[str, object]) -> str:
    label = str(facts.get("rooms_label") or "").strip()
    if label:
        return label
    raw_value = facts.get("rooms") or facts.get("room_count")
    if raw_value not in (None, "", []):
        return f"{raw_value} rooms"
    item = _property_missing_fact_item(facts, "rooms")
    if item:
        return str(item.get("display_value") or "Rooms under research").strip() or "Rooms under research"
    return ""


def _property_fact_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    labels = {
        "price_eur": "Price",
        "warm_rent_eur": "Warm rent",
        "cold_rent_eur": "Cold rent",
        "area_m2": "Area",
        "rooms": "Rooms",
        "bedrooms": "Bedrooms",
        "bathrooms": "Bathrooms",
        "floor": "Floor",
        "has_lift": "Lift",
        "heating_type": "Heating",
        "energy_class": "Energy class",
        "distance_supermarket_m": "Supermarket",
        "distance_playground_m": "Playground",
        "nearest_playground_m": "Playground",
        "nearest_library_m": "Library",
        "nearest_zoo_m": "Zoo",
        "distance_pharmacy_m": "Pharmacy",
        "nearest_pharmacy_m": "Pharmacy",
        "nearest_market_m": "Market",
        "nearest_hardware_store_m": "Baumarkt",
        "nearest_shopping_center_m": "Shopping center",
        "nearest_shopping_street_m": "Flaniermeile",
        "nearest_theatre_m": "Theatre",
        "nearest_public_pool_m": "Public pool",
        "nearest_medical_care_m": "Medical care",
        "distance_underground_m": "Underground",
        "nearest_subway_m": "Underground",
        "nearest_supermarket_m": "Supermarket",
        "nearest_tram_bus_m": "Straßenbahn / Bus",
        "address": "Address",
    }
    rows: list[dict[str, str]] = []
    for key, label in labels.items():
        value = facts.get(key)
        if value in (None, "", []):
            continue
        text = str(value).strip()
        if key.endswith("_eur"):
            text = f"{text} EUR"
        elif key.endswith("_m"):
            text = f"{text} m"
        elif key == "area_m2":
            text = f"{text} m2"
        elif isinstance(value, bool):
            text = "Yes" if value else "No"
        rows.append(_object_detail_row(label, text, "Fact"))
    return rows


def _property_distance_metric(facts: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        raw_value = facts.get(key)
        if raw_value in (None, "", []):
            continue
        try:
            meters = int(float(raw_value))
        except Exception:
            continue
        if meters > 0:
            return meters
    return None


def _property_bike_minutes_label(meters: int) -> str:
    minutes = max(1, int(round(float(meters) / 330.0)))
    return f"about {minutes} min by bike"


def _property_family_context_active(preferences: dict[str, object]) -> bool:
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


def _property_distance_ooda_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    return _property_distance_ooda_rows_for_preferences(facts, {})


def _property_distance_ooda_rows_for_preferences(
    facts: dict[str, object],
    preferences: dict[str, object],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    family_context = _property_family_context_active(preferences)
    distance_specs = (
        ("Playground", ("distance_playground_m", "nearest_playground_m"), "Family", "walking", True),
        ("Library", ("nearest_library_m",), "Family", "walking", True),
        ("Zoo", ("nearest_zoo_m",), "Family", "bicycling", True),
        ("Pharmacy", ("distance_pharmacy_m", "nearest_pharmacy_m"), "Errands", "walking"),
        ("Medical care", ("nearest_medical_care_m",), "Family", "walking", True),
        ("Market", ("nearest_market_m",), "District life", "walking"),
        ("Baumarkt", ("nearest_hardware_store_m",), "Practical", "bicycling"),
        ("Shopping center", ("nearest_shopping_center_m",), "Errands", "bicycling"),
        ("Flaniermeile", ("nearest_shopping_street_m",), "City life", "walking"),
        ("Theatre", ("nearest_theatre_m",), "Culture", "walking"),
        ("Public pool", ("nearest_public_pool_m",), "Family", "bicycling", True),
        ("Run or green space", ("nearest_running_m",), "Daily life", "walking"),
        ("Supermarket", ("distance_supermarket_m", "nearest_supermarket_m"), "Errands", "walking"),
        ("Straßenbahn / Bus", ("nearest_tram_bus_m", "nearest_transit_m"), "Transit", "walking"),
        ("Underground", ("distance_underground_m", "nearest_subway_m"), "Transit", "walking"),
    )
    normalized_distance_specs: tuple[tuple[str, tuple[str, ...], str, str, bool], ...] = tuple(
        item if len(item) == 5 else (item[0], item[1], item[2], item[3], False)
        for item in distance_specs
    )
    for label, keys, tag, travelmode, family_only in normalized_distance_specs:
        if family_only and not family_context:
            continue
        meters = _property_distance_metric(facts, *keys)
        if meters is None:
            continue
        rows.append(
            _object_detail_row(
                f"Nearest {label.lower()}",
                f"{meters:,} m away | {_property_bike_minutes_label(meters)}".replace(",", " "),
                tag,
            )
        )
    return rows


def _property_tour_source_gap_detail(candidate: dict[str, object]) -> str:
    blocked_reason = str(candidate.get("blocked_reason") or "").strip()
    if blocked_reason:
        reason_map = {
            "listing_360_media_missing": "Floorplan or source 360 media missing: the listing does not expose usable tour material yet.",
            "pure_360_assets_unavailable": "Source 360 assets are not accessible enough to rebuild a hosted PropertyQuarry tour.",
            "property_tour_fallback_disabled": "Generated fallback tours are disabled until source floorplan or 360 material is available.",
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
        return "No hosted 3D tour yet. Floorplan missing or usable source 360 media still needs to be found before a hosted tour can be built."
    if _false_flag(facts.get("has_360")) or _zero_count("media_count", "image_count"):
        return "No hosted 3D tour yet. The source did not expose enough room media, a floorplan, or a usable 360."
    return "No hosted 3D tour yet. More source media is needed before PropertyQuarry can build it."


def _property_tour_media_payload(candidate: dict[str, object]) -> dict[str, object]:
    tour_url = str(candidate.get("tour_url") or "").strip()
    vendor_tour_url = str(candidate.get("vendor_tour_url") or "").strip()
    review_url = str(candidate.get("review_url") or "").strip()
    status = str(candidate.get("tour_status") or "").strip().lower()
    eta_raw = str(candidate.get("tour_eta_minutes") or "").strip()
    eta_minutes = 0
    if eta_raw:
        try:
            eta_minutes = int(float(eta_raw))
        except Exception:
            eta_minutes = 0
    embed_href = _property_tour_control_link(tour_url) if tour_url else ""
    if tour_url:
        status_label = "Live 360 ready"
        status_detail = "Hosted 360 is ready on PropertyQuarry and should be reviewed before the raw listing."
    elif vendor_tour_url:
        status_label = "Source 360 available"
        status_detail = "The source 360 is available, but this page keeps it as an external action instead of embedding a brittle vendor viewer."
    elif status in {"queued", "pending"}:
        status_label = "360 queued"
        status_detail = f"Tour generation is queued. ETA about {eta_minutes or 10} min."
    elif status in {"processing", "running", "in_progress", "started"}:
        status_label = "360 rendering"
        status_detail = f"Tour generation is running. ETA about {eta_minutes or 5} min."
    elif status in {"blocked", "failed", "skipped", "not_applicable"}:
        status_label = "360 unavailable"
        status_detail = _property_tour_source_gap_detail(candidate)
    else:
        status_label = "360 unavailable"
        status_detail = _property_tour_source_gap_detail(candidate)
    return {
        "status_label": status_label,
        "status_detail": status_detail,
        "embed_href": embed_href,
        "has_live_viewer": bool(embed_href),
        "show_status_line": bool(tour_url or vendor_tour_url or status in {"queued", "pending", "processing", "running", "in_progress", "started"}),
        "primary_href": tour_url or vendor_tour_url or review_url,
        "primary_label": (
            "Open 3D reconstruction floor plan"
            if tour_url
            else ("Open source 360" if vendor_tour_url else ("Open property page" if review_url else ""))
        ),
        "secondary_href": review_url,
        "secondary_label": "Open property page" if review_url else "",
        "tertiary_href": vendor_tour_url if tour_url and vendor_tour_url and vendor_tour_url != tour_url else "",
        "tertiary_label": "Vendor 360" if tour_url and vendor_tour_url and vendor_tour_url != tour_url else "",
    }


def _property_tour_detail_line(candidate: dict[str, object]) -> str:
    tour_url = str(candidate.get("tour_url") or "").strip()
    vendor_tour_url = str(candidate.get("vendor_tour_url") or "").strip()
    if tour_url:
        return "Open the white-label 3D reconstruction floor plan on PropertyQuarry."
    if vendor_tour_url:
        return "A source 360 exists, but the preferred PropertyQuarry-hosted tour is not ready yet."
    return _property_tour_source_gap_detail(candidate)


def _property_research_money_display(value: object) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if not text:
            return ""
        currency = "EUR" if ("eur" in text.lower() or "€" in text) else ""
        money_match = re.search(r"[0-9][0-9\.\,\s]*(?:[,.][0-9]{1,2})?", text)
        if currency and money_match:
            number_text = money_match.group(0).replace(" ", "").strip(".,")
            if "." in number_text and "," in number_text:
                number_text = number_text.replace(".", "").replace(",", ".")
            elif "," in number_text:
                integer_part, decimal_part = number_text.rsplit(",", 1)
                number_text = integer_part + decimal_part if len(decimal_part) == 3 else integer_part + "." + decimal_part
            elif number_text.count(".") > 1:
                number_text = number_text.replace(".", "")
            try:
                amount = float(number_text)
                if amount > 0:
                    return f"{currency} {amount:,.0f}".replace(",", ",")
            except Exception:
                return text
        if currency:
            return text
        try:
            value = float(text.replace(",", "."))
        except Exception:
            return text
    if isinstance(value, (int, float)):
        amount = float(value)
        if amount <= 0:
            return ""
        return f"EUR {amount:,.0f}".replace(",", ",")
    return ""


def _google_maps_embed_url(map_url: object) -> str:
    normalized = str(map_url or "").strip()
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    query = urllib.parse.parse_qs(parsed.query or "")
    if parsed.netloc.endswith("google.com") and parsed.path.startswith("/maps/search"):
        raw_query = next(iter(query.get("query") or []), "").strip()
        if raw_query:
            return f"https://www.google.com/maps?q={urllib.parse.quote(raw_query, safe=',')}&output=embed"
    return ""


def _property_research_gallery_items(
    *,
    candidate: dict[str, object],
    facts: dict[str, object],
    preview_image: str,
    latest_magic_fit_scene: dict[str, object] | None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append(url: object, *, label: str, kind: str) -> None:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            return
        if not normalized.startswith(("https://", "http://", "/")):
            return
        seen.add(normalized)
        rows.append({"url": normalized, "label": label, "kind": kind})

    _append(preview_image, label="Lead photo", kind="photo")
    for key in ("media_urls_json", "photo_urls_json", "image_urls_json"):
        values = facts.get(key) or candidate.get(key)
        if not isinstance(values, (list, tuple)):
            continue
        for index, value in enumerate(values[:8], start=1):
            _append(value, label=f"Photo {index}", kind="photo")

    if isinstance(latest_magic_fit_scene, dict):
        _append(
            latest_magic_fit_scene.get("image_url"),
            label=str(latest_magic_fit_scene.get("scene_type") or "Lifestyle still").replace("_", " ").title(),
            kind="diorama",
        )
    return rows[:8]


def _property_review_detail_line(candidate: dict[str, object]) -> str:
    review_url = str(candidate.get("review_url") or "").strip()
    if review_url:
        return "Open the property page on PropertyQuarry."
    return "No review page exists for this candidate yet."


def _property_packet_provenance_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    labels = {
        "street_address": "Address",
        "exact_address": "Exact address",
        "address": "Address",
        "has_lift": "Lift",
        "heating_type": "Heating",
        "energy_class": "Energy class",
        "distance_supermarket_m": "Supermarket",
        "nearest_supermarket_m": "Supermarket",
        "distance_playground_m": "Playground",
        "nearest_playground_m": "Playground",
        "distance_pharmacy_m": "Pharmacy",
        "nearest_pharmacy_m": "Pharmacy",
        "distance_underground_m": "Underground",
        "nearest_subway_m": "Underground",
    }
    research_snapshot = dict(facts.get("listing_research_snapshot") or {}) if isinstance(facts.get("listing_research_snapshot"), dict) else {}
    research_meta = dict(facts.get("listing_research_meta") or {}) if isinstance(facts.get("listing_research_meta"), dict) else {}
    rows: list[dict[str, str]] = []
    for key, label in labels.items():
        raw_value = facts.get(key)
        if raw_value in (None, "", []):
            continue
        if isinstance(raw_value, bool):
            value = "Confirmed" if raw_value else "Not confirmed"
        elif isinstance(raw_value, (int, float)) and key.endswith("_m"):
            value = f"{int(raw_value)} m"
        else:
            value = str(raw_value).strip()
        if not value:
            continue
        provenance = "Researched" if key in research_snapshot else "Listing"
        if key in {"street_address", "exact_address", "address"} and ("map_lat" in research_snapshot or "map_lng" in research_snapshot):
            provenance = "Inferred"
        detail = value
        strategy = str(research_meta.get("strategy") or "").strip()
        if provenance == "Researched" and strategy:
            detail = f"{detail} | via {strategy.replace('_', ' ')}"
        rows.append(_object_detail_row(label, detail, provenance))
    return rows


def _property_packet_official_evidence_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    official = dict(facts.get("official_risk_evidence") or {}) if isinstance(facts.get("official_risk_evidence"), dict) else {}
    rows: list[dict[str, str]] = []
    for row in list(official.get("sources") or [])[:6]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("label") or row.get("risk_key") or "Official evidence").strip()
        source_label = str(row.get("source_label") or row.get("provider") or "Official dataset").strip()
        authority = str(row.get("authority_label") or row.get("provider") or "").strip()
        summary = str(row.get("summary") or "").strip()
        availability = str(row.get("availability") or "official_dataset").replace("_", " ").title()
        verification = str(row.get("verification_state") or "needs_review").replace("_", " ").title()
        confidence = str(row.get("confidence") or "").replace("_", " ").title()
        next_step = str(row.get("required_next_step") or "").strip()
        scope = str(row.get("coverage_scope") or "").replace("_", " ").strip()
        detail = " | ".join(part for part in (authority, source_label, summary, f"Scope: {scope}" if scope else "") if part)
        if next_step:
            detail = f"{detail} | Next: {next_step}" if detail else next_step
        rows.append(
            _object_detail_row(
                title,
                detail or "Official source attached for this risk lane.",
                " · ".join(part for part in (availability, verification, confidence) if part),
                href=str(row.get("source_url") or "").strip(),
            )
        )
    return rows


def _property_packet_official_posture_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    official = dict(facts.get("official_risk_evidence") or {}) if isinstance(facts.get("official_risk_evidence"), dict) else {}
    rows: list[dict[str, str]] = []
    for row in _official_risk_posture_rows(official):
        rows.append(
            _object_detail_row(
                str(row.get("title") or "Authority posture").strip(),
                str(row.get("detail") or "").strip() or "Official-source authority posture is not attached yet.",
                str(row.get("tag") or "Pending").strip() or "Pending",
            )
        )
    return rows


def _property_packet_future_research_rows(facts: dict[str, object]) -> list[dict[str, str]]:
    future = dict(facts.get("future_change_research") or {}) if isinstance(facts.get("future_change_research"), dict) else {}
    rows: list[dict[str, str]] = []
    school_quality = property_school_context_summary(future)
    school_progression = str(future.get("school_atlas_progression_summary") or "").strip()
    school_evidence_type = str(future.get("school_atlas_evidence_type") or "").strip().replace("_", " ")
    school_source_url = str(future.get("school_atlas_source_url") or "").strip()
    if school_quality:
        rows.append(_object_detail_row("School context", school_quality, school_evidence_type.title() or "Research", href=school_source_url))
    if school_progression:
        rows.append(_object_detail_row("Gymnasium progression", school_progression, school_evidence_type.title() or "Research", href=school_source_url))
    selected_school = dict(future.get("school_atlas_selected_school") or {}) if isinstance(future.get("school_atlas_selected_school"), dict) else {}
    if selected_school:
        selected_label = " | ".join(
            part for part in (
                str(selected_school.get("name") or "").strip(),
                str(selected_school.get("type") or "").strip(),
                f"{int(float(selected_school.get('distance_m') or 0))} m" if selected_school.get("distance_m") not in (None, "", []) else "",
            ) if part
        )
        if selected_label:
            rows.append(_object_detail_row("Nearest selected school", selected_label, "School"))
    top_destinations = [
        str(item.get("name") or "").strip()
        for item in list(future.get("school_atlas_top_secondary_destinations") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if top_destinations:
        rows.append(_object_detail_row("Top next schools", ", ".join(top_destinations[:3]), "Path"))
    planning_confidence = str(future.get("planning_confidence") or "").strip()
    if planning_confidence:
        rows.append(_object_detail_row("Planning confidence", planning_confidence, "Confidence"))
    investment_impact = str(future.get("investment_impact") or "").strip()
    if investment_impact:
        rows.append(_object_detail_row("Long-term impact", investment_impact.replace("_", " ").title(), "Impact"))
    return rows


def _property_packet_score_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
    match_reasons: list[str],
    mismatch_reasons: list[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    selected_locations = {str(value).strip().lower() for value in str(preferences.get("location_query") or "").split(",") if str(value).strip()}
    fact_address = str(facts.get("address") or facts.get("postal_name") or "").strip()
    if fact_address:
        fits_location = any(token in fact_address.lower() for token in selected_locations) if selected_locations else True
        rows.append(
            _object_detail_row(
                "Location fit",
                fact_address,
                "Strong" if fits_location else "Check",
            )
        )
    price_value = str(
        facts.get("price_display")
        or facts.get("rent_display")
        or facts.get("price")
        or facts.get("price_eur")
        or ""
    ).strip()
    if price_value:
        rows.append(_object_detail_row("Budget signal", price_value, "Budget"))
    area_value = str(facts.get("area_m2") or facts.get("living_area_m2") or "").strip()
    rooms_value = _property_rooms_display(facts)
    if area_value or rooms_value:
        detail = " | ".join(
            part for part in (
                rooms_value,
                f"{area_value} m2" if area_value else "",
            ) if part
        )
        rows.append(_object_detail_row("Layout signal", detail, "Layout"))
    if match_reasons:
        rows.append(_object_detail_row("Best fit signal", match_reasons[0], "Positive"))
    if mismatch_reasons:
        rows.append(_object_detail_row("Main caution", mismatch_reasons[0], "Risk"))
    return rows


def _property_packet_missing_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    missing_fact_specs = [
        ("address", "Exact address", "Needed for precise neighbourhood checks and revisit logistics."),
        ("heating_type", "Heating type", "Needed to confirm if the building avoids the wrong heating setup."),
        ("has_lift", "Lift status", "Needed because access and daily usability often decide the shortlist."),
        ("distance_supermarket_m", "Supermarket distance", "Needed to validate daily-errand convenience."),
        ("distance_playground_m", "Playground distance", "Needed if the search is family-oriented."),
        ("nearest_library_m", "Library distance", "Needed for family, study, and child logistics when that criterion matters."),
        ("nearest_zoo_m", "Zoo distance", "Needed when zoo or Tiergarten access matters for family routines."),
        ("distance_pharmacy_m", "Pharmacy distance", "Needed to confirm basic services nearby."),
        ("nearest_medical_care_m", "Doctors and hospitals", "Needed when family, elder-care, or health resilience matter."),
        ("nearest_market_m", "Market distance", "Needed if district-life quality or produce-market access matters."),
        ("nearest_hardware_store_m", "Baumarkt distance", "Needed when renovation or practical errand access matters."),
        ("nearest_shopping_center_m", "Shopping-center distance", "Needed when broad bad-weather errand access matters."),
        ("nearest_shopping_street_m", "Flaniermeile distance", "Needed when promenade and walkable city life matter."),
        ("nearest_theatre_m", "Theatre distance", "Needed when cultural access matters."),
        ("nearest_public_pool_m", "Public-pool distance", "Needed when family or swimming access matters."),
        ("distance_underground_m", "Underground distance", "Needed to validate fast transit access."),
        ("air_quality_risk", "Air-quality risk", "Needed to understand pollution burden and respiratory comfort."),
        ("crime_risk", "Crime pattern", "Needed to understand practical safety burden in the quarter."),
        ("parking_pressure_risk", "Parking pressure", "Needed when there is no garage and street parking might be difficult."),
        ("drinking_water_risk", "Water source and groundwater burden", "Needed to understand whether water quality or source dependence is a real concern."),
        ("cesspit_risk", "Senkgrube or septic burden", "Needed to understand recurring costs, maintenance, and smell risk."),
        ("winter_access_risk", "Winter driving access", "Needed to understand snow, slope, and seasonal access constraints."),
        ("flood_risk", "Flood exposure", "Needed to understand historic flooding, runoff, and zone risk."),
    ]
    wanted_keywords = {str(value).strip().lower() for value in str(preferences.get("keywords") or "").split(",") if str(value).strip()}
    for key, title, detail in missing_fact_specs:
        if facts.get(key) not in (None, "", []):
            continue
        if key == "distance_playground_m" and "playground nearby" not in wanted_keywords and "family" not in wanted_keywords:
            continue
        if key == "nearest_library_m" and "library nearby" not in wanted_keywords and "family" not in wanted_keywords:
            continue
        if key == "distance_underground_m" and "underground nearby" not in wanted_keywords:
            continue
        if key == "heating_type" and not ({"no gas", "district heating"} & wanted_keywords):
            continue
        if key == "air_quality_risk" and not bool(preferences.get("prefer_good_air_quality")):
            continue
        if key == "crime_risk" and not bool(preferences.get("prefer_low_crime_area")):
            continue
        if key == "parking_pressure_risk" and not bool(preferences.get("require_parking_pressure_check")):
            continue
        if key == "drinking_water_risk" and not bool(preferences.get("require_drinking_water_quality_research")):
            continue
        if key == "cesspit_risk" and not bool(preferences.get("avoid_cesspit_or_septic_risk")):
            continue
        if key == "winter_access_risk" and not bool(preferences.get("require_winter_access_research")):
            continue
        if key == "flood_risk" and not bool(preferences.get("avoid_flood_risk_area")):
            continue
        severity = "Critical" if key in {"address", "heating_type", "has_lift"} else "Important"
        rows.append(_object_detail_row(title, detail, severity))
    for item in _property_missing_fact_items(facts):
        if str(item.get("status") or "").strip().lower() == "filled":
            continue
        label = str(item.get("label") or item.get("field") or "Missing fact").strip()
        ooda = dict(item.get("ooda") or {}) if isinstance(item.get("ooda"), dict) else {}
        detail = str(ooda.get("act") or item.get("evidence") or "Missing-fact research queued.").strip()
        rows.append(_object_detail_row(label, detail, "Research"))
    return rows


def _property_packet_everyday_fit_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    family_context = _property_family_context_active(preferences)
    for key, title, tag, family_only in (
        ("nearest_supermarket_m", "Supermarket", "Errands", False),
        ("nearest_playground_m", "Playground", "Family", True),
        ("nearest_library_m", "Library", "Family", True),
        ("nearest_zoo_m", "Zoo", "Family", True),
        ("nearest_medical_care_m", "Medical care", "Family", True),
        ("nearest_market_m", "Market", "District life", False),
        ("nearest_hardware_store_m", "Baumarkt", "Practical", False),
        ("nearest_shopping_center_m", "Shopping center", "Errands", False),
        ("nearest_shopping_street_m", "Flaniermeile", "City life", False),
        ("nearest_theatre_m", "Theatre", "Culture", False),
        ("nearest_public_pool_m", "Public pool", "Family", True),
        ("nearest_subway_m", "Underground", "Transit", False),
    ):
        if family_only and not family_context:
            continue
        raw_value = facts.get(key)
        if raw_value in (None, "", []):
            continue
        try:
            meters = int(float(raw_value))
        except Exception:
            continue
        rows.append(_object_detail_row(title, f"About {meters} m away.", tag))
    if bool(preferences.get("enable_commute_research")):
        commute_rows: list[str] = []
        for key, label in (
            ("max_commute_minutes_transit", "Transit"),
            ("max_commute_minutes_bike", "Bike"),
            ("max_commute_minutes_drive", "Car"),
            ("max_commute_minutes_walk", "Walk"),
        ):
            try:
                minutes = int(float(preferences.get(key) or 0))
            except Exception:
                minutes = 0
            if minutes > 0:
                commute_rows.append(f"{label} <= {minutes} min")
        if commute_rows:
            rows.append(_object_detail_row("Commute posture", " | ".join(commute_rows), "Reachability"))
    return rows


def _property_packet_risk_fit_rows(
    *,
    facts: dict[str, object],
    preferences: dict[str, object],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for flag, title, detail in (
        ("air_quality_risk", "Air quality", "Pollution burden or respiratory comfort still need explicit validation."),
        ("crime_risk", "Crime burden", "Quarter-level safety pattern still needs explicit validation."),
        ("parking_pressure_risk", "Parking pressure", "Street-parking burden still needs explicit validation when no garage is included."),
        ("drinking_water_risk", "Water quality", "Water source and groundwater burden still need explicit validation."),
        ("cesspit_risk", "Senkgrube or septic", "Recurring cost, maintenance, and smell burden still need explicit validation."),
        ("winter_access_risk", "Winter access", "Snow, slope, and seasonal driveability still need explicit validation."),
        ("flood_risk", "Flood exposure", "Historic flooding, runoff, or zone risk still need explicit validation."),
    ):
        if bool(facts.get(flag)):
            rows.append(_object_detail_row(title, detail, "Risk"))
    if bool(preferences.get("prefer_good_air_quality")) and not bool(facts.get("air_quality_risk")):
        rows.append(_object_detail_row("Air-quality check", "The brief explicitly asks for good air quality, so deep research should still verify the local burden.", "Research"))
    if bool(preferences.get("prefer_low_crime_area")) and not bool(facts.get("crime_risk")):
        rows.append(_object_detail_row("Safety check", "The brief explicitly asks for a lower-crime area, so deep research should still verify the quarter pattern.", "Research"))
    if bool(preferences.get("require_parking_pressure_check")) and not bool(facts.get("garage")) and not bool(facts.get("parking_pressure_risk")):
        rows.append(_object_detail_row("Parking check", "No garage is confirmed, so deep research should still verify evening street-parking reality.", "Research"))
    if bool(preferences.get("require_drinking_water_quality_research")) and not bool(facts.get("drinking_water_risk")):
        rows.append(_object_detail_row("Water-source check", "The brief explicitly asks for water-source and groundwater validation.", "Research"))
    if bool(preferences.get("avoid_cesspit_or_septic_risk")) and not bool(facts.get("cesspit_risk")):
        rows.append(_object_detail_row("Senkgrube check", "The brief explicitly asks to avoid Senkgrube or septic burden, so the infrastructure should be verified.", "Research"))
    if bool(preferences.get("require_winter_access_research")) and not bool(facts.get("winter_access_risk")):
        rows.append(_object_detail_row("Winter-access check", "The brief explicitly asks for snow and slope driveability validation.", "Research"))
    if bool(preferences.get("avoid_flood_risk_area")) and not bool(facts.get("flood_risk")):
        rows.append(_object_detail_row("Flood check", "The brief explicitly asks to avoid flood exposure, so runoff and flood-zone history should be verified.", "Research"))
    return rows


def _property_packet_decision_rows(
    *,
    candidate: dict[str, object],
    match_reasons: list[str],
    mismatch_reasons: list[str],
    missing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    why_now = "; ".join(match_reasons[:2]) if match_reasons else "Enough positive fit signals are present to justify review now."
    why_not_now = "; ".join(mismatch_reasons[:2]) if mismatch_reasons else "No major blocking caution has been captured yet."
    critical_missing = sum(1 for row in missing_rows if str(row.get("tag") or "").strip().lower() == "critical")
    important_missing = sum(1 for row in missing_rows if str(row.get("tag") or "").strip().lower() == "important")
    if critical_missing:
        severity = "High"
        severity_detail = f"{critical_missing} critical fact(s) still missing before this should be trusted fully."
    elif important_missing >= 2:
        severity = "Medium"
        severity_detail = f"{important_missing} important fact(s) still missing. Keep this on the shortlist, but do not treat it as settled."
    elif important_missing == 1:
        severity = "Low"
        severity_detail = "One important fact is still missing. The packet is usable, but not fully closed."
    else:
        severity = "Low"
        severity_detail = "No major missing-data pressure remains in the current packet."
    recommendation_key = str(candidate.get("recommendation") or candidate.get("tag") or "candidate").replace("_", " ").strip().lower()
    recommendation = {
        "shortlist": "Keep it high on the shortlist",
        "review": "Keep it in review",
        "candidate": "Keep it under review",
        "mention": "Check it after the top homes",
        "view if compelling": "Only pursue if the missing facts clear up well",
        "ask for clarification": "Request clarification before spending more time on it",
        "reject": "Drop it unless new evidence changes the file",
        "drop": "Drop it unless new evidence changes the file",
    }.get(recommendation_key, recommendation_key.title() or "Keep it under review")
    return [
        _object_detail_row("Why now", why_now, "Now"),
        _object_detail_row("Why not now", why_not_now, "Risk"),
        _object_detail_row("Missing-data severity", severity_detail, severity),
        _object_detail_row("Best next move", recommendation, "Action"),
    ]


def _property_packet_compare_rows(
    *,
    property_context: dict[str, object],
    current_candidate_ref: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    shortlist_candidates = _property_shortlist_candidates_from_context(property_context)
    for candidate in shortlist_candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        candidate_ref = _property_candidate_ref(candidate)
        if candidate_ref == current_candidate_ref:
            continue
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        fact_line = " | ".join(
            part for part in (
                str(facts.get("price_display") or facts.get("rent_display") or facts.get("price") or "").strip(),
                _property_rooms_display(facts),
                f"{facts.get('area_m2')} m2" if facts.get("area_m2") else "",
            ) if part
        )
        rows.append(
            _object_detail_row(
                str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate",
                " | ".join(
                    part for part in (
                        str(candidate.get("fit_summary") or candidate.get("detail") or "").strip(),
                        fact_line,
                    ) if part
                ) or "Open the property page to compare this home.",
                str(candidate.get("tag") or candidate.get("recommendation") or "Compare").strip() or "Compare",
                href=str(candidate.get("packet_url") or "").strip(),
                secondary_action_href=str(candidate.get("packet_url") or "").strip(),
                secondary_action_label="Open property page" if str(candidate.get("packet_url") or "").strip() else "",
                secondary_action_method="get" if str(candidate.get("packet_url") or "").strip() else "",
            )
        )
        if len(rows) >= 3:
            break
    return rows


def _property_investment_research_access_level(preferences: dict[str, object], commercial: dict[str, object], *, requested: bool) -> str:
    if str(preferences.get("listing_mode") or "").strip().lower() != "buy":
        return "off"
    if not requested and str(preferences.get("investment_research_mode") or "").strip().lower() != "auto":
        return "off"
    level = str(commercial.get("investment_research_level") or "none").strip().lower() or "none"
    return level


def _property_investment_risk_rows(facts: dict[str, object], snapshot: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not str(facts.get("street_address") or "").strip():
        rows.append(_object_detail_row("Address confidence is low", "Exact address is still missing, so neighbourhood and comp confidence are reduced.", "High"))
    if not str(facts.get("heating_type") or "").strip():
        rows.append(_object_detail_row("Heating type still unknown", "Yield assumptions can be wrong if the heating setup drives renovation or tenant demand risk.", "Medium"))
    occupancy = str(facts.get("occupancy_status") or "").strip().lower()
    if occupancy:
        rows.append(_object_detail_row("Occupancy posture", str(facts.get("occupancy_status") or "").strip(), "Risk" if any(token in occupancy for token in ("occup", "vermiet", "bewohn", "uthyrd", "zamieszk")) else "Watch"))
    payback_years = snapshot.get("payback_years")
    if isinstance(payback_years, (int, float)) and float(payback_years) > 35.0:
        rows.append(_object_detail_row("Long payback horizon", f"Estimated payback is about {float(payback_years):.1f} years at current rent assumptions.", "Medium"))
    return rows


def _property_investment_context_rows(
    facts: dict[str, object],
    preferences: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    risk_rows: list[dict[str, str]] = []
    listing_mode = str(preferences.get("listing_mode") or "").strip().lower()
    provider_group = str(facts.get("provider_group") or "").strip().lower()
    provider_channel = str(facts.get("provider_channel") or "").strip()
    marketing_type = str(facts.get("marketing_type") or "").strip()
    availability_label = str(facts.get("availability_label") or facts.get("move_in") or "").strip()
    court = str(facts.get("court") or "").strip()
    court_file_reference = str(facts.get("court_file_reference") or "").strip()
    valuation_display = str(facts.get("valuation_display") or "").strip()
    reserve_display = str(facts.get("reserve_price_display") or "").strip()
    occupancy = str(facts.get("occupancy_status") or "").strip()
    registration_count = 0
    try:
        registration_count = int(float(facts.get("registration_count") or 0))
    except Exception:
        registration_count = 0

    if provider_group == "genossenschaften_at":
        provider_label = provider_channel.replace("_", " ").strip().title() if provider_channel else "Genossenschaften"
        rows.append(_object_detail_row("Provider lane", f"{provider_label} cooperative supply lane.", "Source"))
        if marketing_type:
            rows.append(_object_detail_row("Offer posture", marketing_type, "Source"))
            if listing_mode == "buy" and marketing_type.lower().startswith("miet"):
                risk_rows.append(
                    _object_detail_row(
                        "Rental-led cooperative lane",
                        "This candidate is coming through a rental/cooperative supply lane while the brief is in buy mode. Treat the underwriting output as weak until the acquisition path is confirmed.",
                        "High",
                    )
                )
        if availability_label:
            rows.append(_object_detail_row("Delivery timing", availability_label, "Timing"))
        if registration_count > 0:
            rows.append(_object_detail_row("Applicant pressure", f"{registration_count:,} registrations or applicants were visible on the source lane.", "Demand"))
            if registration_count >= 10000:
                risk_rows.append(_object_detail_row("Extremely high applicant pressure", "Competition on this cooperative lane is already very high, so practical conversion odds may be weak even if the fit looks decent.", "High"))
            elif registration_count >= 1000:
                risk_rows.append(_object_detail_row("High applicant pressure", "Competition on this cooperative lane is already meaningful. Keep conversion risk in mind before overvaluing the headline fit.", "Medium"))

    if court or court_file_reference or valuation_display or reserve_display:
        if court:
            rows.append(_object_detail_row("Court process", court, "Auction"))
        if court_file_reference:
            rows.append(_object_detail_row("Case reference", court_file_reference, "Auction"))
        if valuation_display:
            rows.append(_object_detail_row("Judicial valuation", valuation_display, "Auction"))
        if reserve_display:
            rows.append(_object_detail_row("Reserve or deposit", reserve_display, "Auction"))
        risk_rows.append(
            _object_detail_row(
                "Judicial sale diligence",
                "This candidate is coming from a judicial or foreclosure lane. Underwriting should explicitly verify occupancy, legal encumbrances, and auction terms before treating the apparent discount as real.",
                "High",
            )
        )
        if occupancy:
            rows.append(_object_detail_row("Recorded occupancy", occupancy, "Auction"))

    return rows, risk_rows


def _property_investment_research_rows(
    *,
    property_url: str,
    facts: dict[str, object],
    preferences: dict[str, object],
    commercial: dict[str, object],
    requested: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    access_level = _property_investment_research_access_level(preferences, commercial, requested=requested)
    if access_level == "off":
        return [], []
    if access_level == "none":
        return [
            _object_detail_row(
                "Upgrade required",
                "Investment research is reserved for paid investment tiers. The current free tier does not run buy-side underwriting research.",
                "Locked",
            )
        ], []
    context_rows, context_risk_rows = _property_investment_context_rows(facts, preferences)
    current_price_eur = _property_investment_price_eur(facts)
    current_area_sqm = _property_investment_area_sqm(facts)
    location_seed = _property_investment_location_seed(facts, preferences)
    if not isinstance(current_price_eur, float) or not isinstance(current_area_sqm, float) or not location_seed:
        return context_rows + [
            _object_detail_row(
                "Investment research is waiting on core facts",
                "The packet still needs a credible buy price, area, and location before comp and yield work can run.",
                "Pending",
            )
        ], context_risk_rows
    selected_platforms = ",".join(str(value or "").strip() for value in (preferences.get("selected_platforms") or []) if str(value or "").strip())
    snapshot = _property_investment_research_snapshot(
        property_url=property_url,
        country_code=str(preferences.get("country_code") or "").strip() or "AT",
        location_query=location_seed,
        selected_platforms_csv=selected_platforms,
        current_price_eur=current_price_eur,
        current_area_sqm=current_area_sqm,
        research_level=access_level,
    )
    if not snapshot:
        return context_rows + [
            _object_detail_row(
                "Investment research could not build a benchmark yet",
                "No usable market samples were recovered from the current provider set for this location.",
                "Pending",
            )
        ], context_risk_rows
    rows: list[dict[str, str]] = context_rows + [
        _object_detail_row("Current underwriting base", f"EUR {current_price_eur:,.0f} over {current_area_sqm:.1f} m2 ({float(snapshot.get('current_price_per_sqm_eur') or 0.0):.2f} EUR/m2)", "Base"),
        _object_detail_row("Comparable buy samples", f"{int(snapshot.get('buy_sample_count') or 0)} listings", "Comps"),
        _object_detail_row("Comparable rent samples", f"{int(snapshot.get('rent_sample_count') or 0)} listings", "Comps"),
    ]
    underwriting = _property_investment_underwriting_payload(
        title=str(facts.get("listing_title") or facts.get("title") or property_url).strip() or property_url,
        summary=str(facts.get("summary") or facts.get("description_text") or "").strip(),
        facts=facts,
        preferences=preferences,
        snapshot=snapshot,
    )
    if underwriting:
        rows.append(
            _object_detail_row(
                "Institutional underwriting score",
                f"{underwriting.get('score_display') or ''} | {underwriting.get('confidence_label') or 'Partial evidence'}",
                str(underwriting.get("score_bucket_label") or "Mixed"),
            )
        )
        external_model = dict(underwriting.get("external_model") or {}) if isinstance(underwriting.get("external_model"), dict) else {}
        if external_model:
            rows.append(
                _object_detail_row(
                    "External model status",
                    " | ".join(
                        part
                        for part in (
                            str(underwriting.get("feed_status_label") or "").strip(),
                            str(underwriting.get("feed_status_detail") or "").strip(),
                        )
                        if part
                    ) or "External model status pending.",
                    str(external_model.get("confidence_label") or "Mixed"),
                )
            )
    market_buy = snapshot.get("market_buy_per_sqm_eur")
    delta_pct = snapshot.get("market_buy_delta_pct")
    if isinstance(market_buy, (int, float)):
        detail = f"Market buy benchmark is about {float(market_buy):.2f} EUR/m2."
        if isinstance(delta_pct, (int, float)):
            direction = "below" if float(delta_pct) < 0 else "above"
            detail = f"{detail} This listing sits {abs(float(delta_pct)):.1f}% {direction} that benchmark."
        rows.append(_object_detail_row("Buy-side benchmark", detail, "Value"))
    expected_rent = snapshot.get("expected_monthly_rent_eur")
    gross_yield = snapshot.get("gross_yield_pct")
    payback_years = snapshot.get("payback_years")
    if isinstance(expected_rent, (int, float)):
        rows.append(_object_detail_row("Expected monthly rent", f"About EUR {float(expected_rent):,.0f} ({float(snapshot.get('market_rent_per_sqm_eur') or 0.0):.2f} EUR/m2)", "Yield"))
    if isinstance(gross_yield, (int, float)):
        rows.append(_object_detail_row("Gross yield", f"About {float(gross_yield):.2f}% before vacancy, tax, and capex.", "Yield"))
    net_yield = underwriting.get("net_yield_pct")
    if isinstance(net_yield, (int, float)):
        rows.append(_object_detail_row("Net yield", f"About {float(net_yield):.2f}% after tax, opex, vacancy, and capex reserves.", "Yield"))
    cap_rate = underwriting.get("cap_rate_pct")
    if isinstance(cap_rate, (int, float)):
        rows.append(_object_detail_row("Cap rate", f"About {float(cap_rate):.2f}% on current acquisition cost assumptions.", "Yield"))
    dscr = underwriting.get("dscr")
    if isinstance(dscr, (int, float)):
        rows.append(_object_detail_row("Debt coverage", f"About {float(dscr):.2f}x on the current financing model.", "Financing"))
    if isinstance(payback_years, (int, float)):
        rows.append(_object_detail_row("Payback horizon", f"About {float(payback_years):.1f} years on gross rent assumptions.", "Yield"))
    for dimension in list(underwriting.get("dimensions") or [])[:7]:
        if not isinstance(dimension, dict):
            continue
        rows.append(
            _object_detail_row(
                str(dimension.get("label") or "Underwriting dimension").strip(),
                f"{int(float(dimension.get('score') or 0))}/100 | {str(dimension.get('tooltip') or '').strip()}",
                str(dimension.get("bucket_label") or "Mixed").strip(),
            )
        )
    if access_level == "preview":
        rows.append(_object_detail_row("Preview tier limit", "Plus only returns the benchmark headline. Agent unlocks the fuller risk and diligence pass.", "Upgrade"))
        return rows, context_risk_rows
    external_model = dict(underwriting.get("external_model") or {}) if isinstance(underwriting.get("external_model"), dict) else {}
    if external_model:
        financing = dict(external_model.get("financing") or {}) if isinstance(external_model.get("financing"), dict) else {}
        taxes = dict(external_model.get("taxes") or {}) if isinstance(external_model.get("taxes"), dict) else {}
        operating = dict(external_model.get("operating_costs") or {}) if isinstance(external_model.get("operating_costs"), dict) else {}
        if isinstance(external_model.get("acquisition_costs_eur"), (int, float)):
            rows.append(_object_detail_row("Acquisition cost base", f"About EUR {float(external_model.get('acquisition_costs_eur')):,.0f} including transfer tax and registry fees.", "Base"))
        if isinstance(taxes.get("property_transfer_tax_pct"), (int, float)):
            rows.append(_object_detail_row("Transfer tax model", f"{float(taxes.get('property_transfer_tax_pct')):.2f}% transfer tax and {float(taxes.get('land_registry_fee_pct') or 0.0):.2f}% registry fee.", str(taxes.get("source_label") or "Tax model")))
        if isinstance(operating.get("annual_operating_costs_eur"), (int, float)):
            rows.append(_object_detail_row("Operating cost model", f"About EUR {float(operating.get('annual_operating_costs_eur')):,.0f} per year ({float(operating.get('operating_cost_ratio_pct') or 0.0):.1f}% of rent when rent is known).", str(operating.get("source_label") or "Operating cost model")))
        if isinstance(financing.get("interest_rate_pct"), (int, float)):
            rows.append(_object_detail_row("Financing model", f"{float(financing.get('interest_rate_pct')):.2f}% over {int(float(financing.get('loan_term_years') or 0))} years with about EUR {float(financing.get('annual_debt_service_eur') or 0.0):,.0f} annual debt service.", str(financing.get("source_label") or "Financing model")))
    risk_rows = context_risk_rows + _property_investment_risk_rows(facts, snapshot)
    if isinstance(snapshot.get("buy_samples"), list) and snapshot["buy_samples"]:
        top_buy = snapshot["buy_samples"][0]
        rows.append(_object_detail_row("Closest buy comp", f"{top_buy.get('title')} | {top_buy.get('per_sqm_eur')} EUR/m2 via {top_buy.get('source_label')}", "Comp"))
    if isinstance(snapshot.get("rent_samples"), list) and snapshot["rent_samples"]:
        top_rent = snapshot["rent_samples"][0]
        rows.append(_object_detail_row("Closest rent comp", f"{top_rent.get('title')} | {top_rent.get('per_sqm_eur')} EUR/m2 via {top_rent.get('source_label')}", "Comp"))
    return rows, risk_rows


def _property_packet_compare_table(
    *,
    property_context: dict[str, object],
    current_candidate: dict[str, object],
    current_candidate_ref: str,
) -> list[list[object]]:
    def _tour_state_for(candidate: dict[str, object]) -> str:
        if str(candidate.get("tour_url") or "").strip():
            return "Ready"
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_raw = str(candidate.get("tour_eta_minutes") or "").strip()
        if status in {"queued", "pending"}:
            return f"Queued | ETA about {eta_raw or '10'} min"
        if status in {"processing", "running", "in_progress", "started"}:
            return f"Rendering | ETA about {eta_raw or '5'} min"
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return "Unavailable | " + _property_tour_source_gap_detail(candidate)
        return "Unavailable | " + _property_tour_source_gap_detail(candidate)

    def _row_for(candidate: dict[str, object], *, candidate_ref: str, current: bool) -> list[object]:
        facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "").strip() or "No fit summary"
        price_value = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price")
            or facts.get("price_eur")
            or "Unknown"
        ).strip()
        layout_value = " | ".join(
            part for part in (
                _property_rooms_display(facts),
                f"{facts.get('area_m2')} m2" if facts.get("area_m2") else "",
            ) if part
        ) or "Layout under research"
        tour_state = _tour_state_for(candidate)
        return [
            {
                "title": (str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate") + (" (Current)" if current else ""),
                "detail": str(candidate.get("source_label") or "").strip(),
                "href": str(candidate.get("packet_url") or "").strip(),
            },
            fit_summary,
            price_value,
            layout_value,
            tour_state,
            {
                "title": "Open property page",
                "detail": "Inspect this home in detail",
                "href": str(candidate.get("packet_url") or "").strip(),
            },
        ]

    table_rows: list[list[object]] = [_row_for(current_candidate, candidate_ref=current_candidate_ref, current=True)]
    shortlist_candidates = _property_shortlist_candidates_from_context(property_context)
    for candidate in shortlist_candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        candidate_ref = _property_candidate_ref(candidate)
        if candidate_ref == current_candidate_ref:
            continue
        table_rows.append(_row_for(candidate, candidate_ref=candidate_ref, current=False))
        if len(table_rows) >= 4:
            break
    return table_rows
