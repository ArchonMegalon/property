from __future__ import annotations

import urllib.parse

from app.api.routes.landing_property_research import _property_normalized_mismatch_reasons
from app.product.property_location_research import property_school_context_summary


def _candidate_external_listing_url(candidate: dict[str, object]) -> str:
    for key in ("property_url", "source_url"):
        url = str(candidate.get(key) or "").strip()
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.strip().lower()
        path = parsed.path.strip()
        if path.startswith("/app/"):
            continue
        if host.endswith("propertyquarry.com") and path.startswith("/app/"):
            continue
        return url
    return ""


def _source_count(source: dict[str, object], key: str) -> int:
    try:
        return max(0, int(float(source.get(key) or 0)))
    except Exception:
        return 0


def _source_ranked_total(source: dict[str, object]) -> int:
    top_candidates = [
        dict(candidate)
        for candidate in list(source.get("top_candidates") or [])
        if isinstance(candidate, dict)
    ]
    explicit_total = max(
        _source_count(source, "ranked_total"),
        _source_count(source, "ranked_candidate_total"),
        _source_count(source, "results_total"),
        _source_count(source, "survivor_total"),
        _source_count(source, "high_fit_total"),
    )
    if top_candidates:
        return max(len(top_candidates), explicit_total)
    return explicit_total


def build_property_source_rows(*, property_summary: dict[str, object]) -> list[dict[str, str]]:
    return [
        {
            "title": str(source.get("source_label") or source.get("source_url") or "Source").strip(),
            "detail": " | ".join(
                part
                for part in (
                    f"{int(source.get('listing_total') or 0)} listings",
                    f"{_source_ranked_total(source)} ranked",
                    f"{int(source.get('filtered_floorplan_total') or 0)} still waiting on floorplans"
                    if int(source.get('filtered_floorplan_total') or 0)
                    else "",
                    f"{int(source.get('tour_created_total') or 0)} 3D tours",
                    f"{int(source.get('notified_total') or 0)} client alerts",
                    f"{int(source.get('email_notified_total') or 0)} email" if int(source.get('email_notified_total') or 0) else "",
                    f"top score {float(source.get('top_fit_score') or 0.0):.2f}" if source.get("top_fit_score") is not None else "",
                )
                if part
            ),
            "tag": "Scanned",
        }
        for source in list(property_summary.get("sources") or [])
        if isinstance(source, dict)
    ]


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
    school_quality = property_school_context_summary(future)
    school_progression = str(future.get("school_atlas_progression_summary") or "").strip()
    school_evidence = str(future.get("school_atlas_evidence_type") or "").strip().replace("_", " ")
    if school_quality:
        rows.append(
            {
                "icon": "SCH",
                "label": "School context",
                "detail": school_quality,
                "tag": school_evidence.title() if school_evidence else "Research",
            }
        )
    if school_progression:
        rows.append(
            {
                "icon": "AHS",
                "label": "School transition",
                "detail": school_progression,
                "tag": school_evidence.title() if school_evidence else "Research",
            }
        )
    return rows[:3]


def build_property_shortlist_panel(
    *,
    property_summary: dict[str, object],
    property_preferences: dict[str, object],
    active_run_id: str,
    wants_run_views: bool,
    clean_candidate_copy,
    candidate_priority_reason,
    property_candidate_ref,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    property_shortlist_rows: list[dict[str, str]] = []
    property_shortlist_cards: list[dict[str, object]] = []
    if not wants_run_views:
        return property_shortlist_rows, property_shortlist_cards

    ranked_candidates = [
        dict(candidate)
        for candidate in list(property_summary.get("ranked_candidates") or [])
        if isinstance(candidate, dict)
    ]
    if not ranked_candidates:
        for source in list(property_summary.get("sources") or []):
            if not isinstance(source, dict):
                continue
            source_label = str(source.get("source_label") or source.get("source_url") or "Source").strip()
            for candidate in list(source.get("top_candidates") or []):
                if not isinstance(candidate, dict):
                    continue
                candidate_row = dict(candidate)
                candidate_row.setdefault("source_label", source_label)
                ranked_candidates.append(candidate_row)

    ranked_candidates.sort(
        key=lambda candidate: (
            int(candidate.get("rank") or 9999),
            -float(candidate.get("ranking_score") or candidate.get("fit_score") or 0.0),
        )
    )

    for candidate in ranked_candidates:
        candidate_facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        source_label = str(candidate.get("source_label") or candidate.get("source_url") or "Source").strip()
        title = str(candidate.get("title") or candidate.get("property_url") or "Property candidate").strip() or "Property candidate"
        detail_parts = [clean_candidate_copy(candidate.get("fit_summary") or "")]
        match_reasons = [
            clean_candidate_copy(item)
            for item in list(candidate.get("match_reasons") or [])
            if clean_candidate_copy(item)
        ]
        mismatch_reasons = _property_normalized_mismatch_reasons(
            [clean_candidate_copy(item) for item in list(candidate.get("mismatch_reasons") or []) if clean_candidate_copy(item)],
            facts=candidate_facts,
            preferences=property_preferences,
        )
        priority_reason = candidate_priority_reason(match_reasons, mismatch_reasons, clean_candidate_copy(candidate.get("fit_summary") or ""))
        if priority_reason:
            detail_parts.append(priority_reason)
        row: dict[str, str] = {
            "title": title,
            "detail": " | ".join(part for part in detail_parts if part) or source_label,
            "tag": str(candidate.get("recommendation") or "candidate").replace("_", " ").title(),
        }
        review_url = str(candidate.get("review_url") or "").strip()
        tour_url = str(candidate.get("tour_url") or "").strip()
        property_url = str(candidate.get("property_url") or "").strip()
        external_listing_url = _candidate_external_listing_url(candidate)
        packet_ref = property_candidate_ref(
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
            row["action_label"] = "Open property page"
            if external_listing_url:
                row["secondary_action_href"] = external_listing_url
                row["secondary_action_method"] = "get"
                row["secondary_action_label"] = "Open listing"
        else:
            row["action_href"] = packet_url
            row["action_method"] = "get"
            row["action_label"] = "Open property page"
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
                "property_facts": candidate_facts,
                "assessment": dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                "feedback_summary": dict(candidate.get("feedback_summary") or {}) if isinstance(candidate.get("feedback_summary"), dict) else {},
                "feedback_rows": [
                    dict(row)
                    for row in list(candidate.get("feedback_rows") or [])
                    if isinstance(row, dict)
                ],
            }
        )
    return property_shortlist_rows[:8], property_shortlist_cards
