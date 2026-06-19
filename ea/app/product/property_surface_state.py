from __future__ import annotations

import re
import urllib.parse
from typing import Callable

from app.services.property_market_catalog import supported_currency_codes

from app.product.models import (
    PropertyBillingTruthSnapshot,
    PropertyPreferenceManagerSnapshot,
    PropertyResearchPacketSnapshot,
    PropertyRecurringWatchSnapshot,
    PropertySearchFormStateSnapshot,
    PropertyRunHealthSnapshot,
    PropertyRunLiveBoardSnapshot,
    PropertyRunReliabilitySnapshot,
    PropertyRunRepairSnapshot,
    PropertySearchAgentSelectionSnapshot,
    PropertySearchRunSnapshot,
    PropertyShortlistSnapshot,
    PropertyWorkbenchCandidateSnapshot,
)


_GENERIC_SOURCE_FAMILIES = {
    "genossenschaften",
    "genossenschaften at",
    "community housing",
    "community providers",
    "developer projects",
}


def _positive_int(value: object, *, default: int = 0) -> int:
    try:
        parsed = int(float(value or 0))
    except Exception:
        parsed = 0
    return parsed if parsed > 0 else default


def normalized_property_search_goal(value: object) -> str:
    goal = str(value or "home").strip().lower() or "home"
    return goal if goal in {"home", "investment"} else "home"


def effective_property_listing_mode(
    preferences: dict[str, object] | None,
    *,
    fallback: str = "rent",
) -> str:
    payload = dict(preferences or {})
    if normalized_property_search_goal(payload.get("search_goal")) == "investment":
        return "buy"
    mode = str(payload.get("listing_mode") or fallback or "rent").strip().lower()
    return "buy" if mode == "buy" else "rent"


def property_mode_visibility_label(
    preferences: dict[str, object] | None,
    *,
    fallback: str = "rent",
) -> str:
    payload = dict(preferences or {})
    if normalized_property_search_goal(payload.get("search_goal")) == "investment":
        return "Investment"
    return "Buy" if effective_property_listing_mode(payload, fallback=fallback) == "buy" else "Rent"


def _property_search_ranked_candidates_from_sources(
    sources: list[dict[str, object]],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    ranked_candidates: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_label = str(source.get("source_label") or source.get("label") or "").strip()
        for candidate in list(source.get("research_candidates") or source.get("top_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            candidate_row = dict(candidate)
            candidate_row.setdefault("source_label", source_label)
            candidate_key = str(
                candidate_row.get("candidate_ref")
                or candidate_row.get("source_ref")
                or candidate_row.get("property_url")
                or candidate_row.get("listing_id")
                or candidate_row.get("title")
                or ""
            ).strip()
            if candidate_key and candidate_key in seen_keys:
                continue
            if candidate_key:
                seen_keys.add(candidate_key)
            ranked_candidates.append(candidate_row)
    ranked_candidates.sort(key=lambda item: float(item.get("fit_score") or 0.0), reverse=True)
    for index, candidate_row in enumerate(ranked_candidates, start=1):
        candidate_row.setdefault("rank", index)
    return ranked_candidates[:limit]


def _property_summary_held_back_total(summary: dict[str, object]) -> int:
    return max(
        0,
        _positive_int(summary.get("held_back_total"))
        or _positive_int(summary.get("filtered_total"))
        or _positive_int(summary.get("filtered_out_total"))
        or (
            _positive_int(summary.get("filtered_floorplan_total"))
            + _positive_int(summary.get("filtered_area_total"))
            + _positive_int(summary.get("filtered_property_type_total"))
            + _positive_int(summary.get("filtered_availability_total"))
            + _positive_int(summary.get("filtered_generic_page_total"))
            + _positive_int(summary.get("filtered_listing_mode_total"))
        ),
    )


def normalize_property_search_run_snapshot(raw_run: dict[str, object]) -> dict[str, object]:
    payload = PropertySearchRunSnapshot.from_dict(dict(raw_run or {})).to_dict()
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    sources = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    if sources:
        ranked_candidates = [
            dict(row)
            for row in list(summary.get("ranked_candidates") or [])
            if isinstance(row, dict)
        ]
        if not ranked_candidates:
            ranked_candidates = _property_search_ranked_candidates_from_sources(sources)
            if ranked_candidates:
                summary["ranked_candidates"] = ranked_candidates
        held_back_total = _property_summary_held_back_total(summary)
        if held_back_total > 0:
            summary.setdefault("held_back_total", held_back_total)
            summary.setdefault("filtered_total", held_back_total)
        payload["summary"] = summary
    return payload


def property_run_status_copy(status_value: object, message_value: object = "") -> tuple[str, str]:
    status = str(status_value or "").strip().lower()
    message = str(message_value or "").strip()
    if status in {"processed", "completed"}:
        return ("Finished", "")
    if status == "completed_partial":
        return ("Finished with partial coverage", message or "The shortlist is ready, but one or more sources finished degraded.")
    if status == "failed":
        return ("Search failed", message or "The search failed before ranking finished.")
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


def build_property_run_health_snapshot(
    run_payload: dict[str, object],
    *,
    run_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = dict(run_payload or {})
    summary = (
        dict(run_summary or {})
        if isinstance(run_summary, dict)
        else (dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {})
    )
    status = str(payload.get("status") or summary.get("status") or "not_started").strip().lower() or "not_started"
    raw_message = str(payload.get("message") or summary.get("message") or "").strip()
    status_label, status_note = property_run_status_copy(status, raw_message)
    held_back_total = _positive_int(summary.get("held_back_total"))
    if not held_back_total:
        held_back_total = (
            _positive_int(summary.get("filtered_floorplan_total"))
            + _positive_int(summary.get("filtered_area_total"))
            + _positive_int(summary.get("filtered_property_type_total"))
            + _positive_int(summary.get("filtered_availability_total"))
            + _positive_int(summary.get("filtered_generic_page_total"))
            + _positive_int(summary.get("filtered_listing_mode_total"))
        )
    filtered_total = _positive_int(summary.get("filtered_total"), default=held_back_total or 0)
    return PropertyRunHealthSnapshot(
        run_id=str(payload.get("run_id") or "").strip(),
        status=status,
        status_label=status_label,
        status_note=status_note,
        message=status_note or raw_message,
        progress=_positive_int(payload.get("progress")),
        status_url=str(payload.get("status_url") or "").strip(),
        eta_label=str(payload.get("eta_label") or "").strip(),
        in_progress=status not in {"processed", "completed", "completed_partial", "failed", "noop", "cancelled", "not_started", "not started"},
        source_total=_positive_int(summary.get("sources_total")),
        listing_total=_positive_int(summary.get("listing_total") or summary.get("raw_listing_total")),
        filtered_total=filtered_total,
        held_back_total=held_back_total,
        research_task_total=_positive_int(payload.get("research_task_total") or summary.get("research_task_total")),
        open_research_task_total=_positive_int(payload.get("open_research_task_total") or summary.get("open_research_task_total")),
        filled_research_task_total=_positive_int(payload.get("filled_research_task_total") or summary.get("filled_research_task_total")),
        dismissed_research_task_total=_positive_int(payload.get("dismissed_research_task_total") or summary.get("dismissed_research_task_total")),
    ).to_dict()


def build_property_run_repair_snapshot(
    run_payload: dict[str, object],
    *,
    results_total: int = 0,
) -> dict[str, object]:
    payload = dict(run_payload or {})
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    timing = dict(summary.get("timing_receipts") or {}) if isinstance(summary.get("timing_receipts"), dict) else {}
    status = str(payload.get("status") or summary.get("status") or "queued").strip().lower() or "queued"
    progress = max(0, min(100, _positive_int(payload.get("progress") or summary.get("progress"))))
    source_rows = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    failed_total = 0
    for row in source_rows:
        row_status = str(row.get("status") or row.get("state") or "").strip().lower()
        if row_status in {"failed", "error", "skipped"} or row.get("error"):
            failed_total += 1
    repair_step = str(summary.get("repair_step_label") or "").strip()
    if not repair_step and failed_total:
        repair_step = f"Retrying {failed_total} provider check{'s' if failed_total != 1 else ''}"
    next_useful_eta = str(summary.get("next_useful_update_eta_label") or "").strip()
    if not next_useful_eta and timing.get("first_shortlist_ready_at") and results_total > 0:
        next_useful_eta = "new shortlist already ready"
    final_eta = str(payload.get("eta_label") or summary.get("eta_label") or "").strip()
    eta_confidence = str(summary.get("eta_confidence") or "").strip().lower()
    if not eta_confidence:
        if final_eta and progress >= 20:
            eta_confidence = "medium"
        elif final_eta:
            eta_confidence = "low"
        else:
            eta_confidence = "unknown"
    repair_status = str(summary.get("repair_status") or "").strip().lower()
    if not repair_status:
        if status == "completed_partial":
            repair_status = "degraded"
        elif failed_total:
            repair_status = "repairing"
        else:
            repair_status = "stable"
    repair_status_label = str(summary.get("repair_status_label") or "").strip()
    if not repair_status_label:
        if repair_status == "repairing":
            repair_status_label = "Repairing"
        elif repair_status == "degraded":
            repair_status_label = "Partial coverage"
        elif repair_status == "failed":
            repair_status_label = "Repair failed"
        else:
            repair_status_label = "Stable"
    repair_outcome_summary = str(summary.get("repair_outcome_summary") or "").strip()
    if not repair_outcome_summary:
        if status == "completed_partial":
            repair_outcome_summary = "The shortlist is ready, but one or more sources finished degraded."
        elif failed_total and results_total > 0:
            repair_outcome_summary = "Some provider checks are retrying, but the current shortlist is already usable."
        elif failed_total:
            repair_outcome_summary = "Some provider checks are retrying before the shortlist can settle."
    return PropertyRunRepairSnapshot(
        repair_status=repair_status,
        repair_status_label=repair_status_label,
        repair_step_label=repair_step,
        repair_outcome_summary=repair_outcome_summary,
        repair_class=str(summary.get("repair_class") or "").strip(),
        repair_attempt_count=_positive_int(summary.get("repair_attempt_count")),
        eta_confidence_label=eta_confidence.title() if eta_confidence else "Unknown",
        next_useful_update_eta_label=next_useful_eta,
        can_auto_repair=bool(summary.get("can_auto_repair") or failed_total or repair_status in {"repairing", "degraded"}),
    ).to_dict()


def build_property_run_reliability_snapshot(
    run_payload: dict[str, object],
    *,
    results_total: int = 0,
) -> dict[str, object]:
    payload = dict(run_payload or {})
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    status = str(payload.get("status") or summary.get("status") or "queued").strip().lower() or "queued"
    progress = max(0, min(100, _positive_int(payload.get("progress") or summary.get("progress"))))
    message = str(payload.get("message") or "").strip()
    source_rows = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    source_total = max(0, _positive_int(summary.get("sources_total"), default=len(source_rows)))
    source_checked = len(source_rows)
    listing_total = max(0, _positive_int(summary.get("listing_total") or summary.get("reviewed_listing_total")))
    filtered_total = max(0, _property_summary_held_back_total(summary))
    failed_total = 0
    for row in source_rows:
        row_status = str(row.get("status") or row.get("state") or "").strip().lower()
        if row_status in {"failed", "error", "skipped"} or row.get("error"):
            failed_total += 1
    pending_total = max(0, source_total - source_checked)
    repair = build_property_run_repair_snapshot(payload, results_total=results_total)
    customer_status = str(summary.get("customer_status_message") or "").strip()
    if not customer_status:
        if status in {"processed", "completed"}:
            customer_status = "Search finished cleanly."
        elif status == "completed_partial":
            customer_status = message or "Search finished with partial coverage after one or more provider checks degraded."
        elif status == "failed":
            customer_status = message or "Search interrupted before the final pass completed."
        elif failed_total and results_total > 0:
            customer_status = "Some provider checks are retrying, but the current shortlist is already usable."
        elif failed_total:
            customer_status = "Some provider checks are retrying before the shortlist can settle."
        elif results_total > 0:
            customer_status = "Strongest verified matches are already ready while the rest of the search finishes."
        elif source_checked > 0:
            customer_status = "Providers are being checked and the first shortlist is still building."
        else:
            customer_status = message or "Preparing the first provider lanes."
    if status in {"processed", "completed"}:
        health_tone = "good"
        health_label = "Healthy"
    elif status == "completed_partial":
        health_tone = "warn"
        health_label = "Partial coverage"
    elif status == "failed":
        health_tone = "bad"
        health_label = "Interrupted"
    elif failed_total:
        health_tone = "warn"
        health_label = "Repairing"
    elif source_checked > 0 or progress > 0:
        health_tone = "good"
        health_label = "Working"
    else:
        health_tone = "idle"
        health_label = "Starting"
    coverage_label = ""
    if source_total:
        coverage_label = f"{source_checked}/{source_total} provider checks"
        if pending_total:
            coverage_label += f" · {pending_total} still running"
    result_label = ""
    if results_total > 0:
        result_label = f"{results_total} ranked result{'s' if results_total != 1 else ''} ready"
    elif listing_total > 0:
        result_label = f"{listing_total} homes reviewed"
    filtered_label = ""
    if filtered_total > 0:
        filtered_label = f"{filtered_total} filtered by active rules"
    return PropertyRunReliabilitySnapshot(
        health_label=health_label,
        health_tone=health_tone,
        coverage_label=coverage_label,
        result_label=result_label,
        filtered_label=filtered_label,
        repair_step_label=str(repair.get("repair_step_label") or "").strip(),
        next_useful_update_eta_label=str(repair.get("next_useful_update_eta_label") or "").strip(),
        final_eta_label=str(payload.get("eta_label") or summary.get("eta_label") or "").strip(),
        eta_confidence_label=str(repair.get("eta_confidence_label") or "Unknown").strip() or "Unknown",
        customer_status_message=customer_status,
        repair=repair,
    ).to_dict()


def _compact_run_message(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "Waiting for the first source update."
    candidate_match = re.search(r"(?:Reviewing(?: candidate)?|Scoring enriched candidate|Ranked|Scored)\s+(\d+)\s+(?:of)\s+(\d+)", text, flags=re.IGNORECASE)
    if candidate_match:
        return f"{candidate_match.group(1)} / {candidate_match.group(2)}"
    shortlist_match = re.search(r"^Built shortlist of\s+\d+\s+listing\(s\)\s+for\s+(.+)\.$", text, flags=re.IGNORECASE)
    if shortlist_match:
        return "Shortlist ready"
    return text


def _parse_property_run_message_info(value: object) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {
            "raw": "",
            "fraction_label": "",
            "source_label": "",
            "phase_label": "Waiting for the first source update.",
        }
    source_match = re.search(r"\sfor\s+(.+?)\.?$", text, flags=re.IGNORECASE)
    candidate_match = re.search(r"^(Reviewing(?: candidate)?|Scoring enriched candidate|Ranked|Scored)\s+(\d+)\s+(?:of)\s+(\d+)", text, flags=re.IGNORECASE)
    if candidate_match:
        verb = str(candidate_match.group(1) or "").strip().lower()
        phase_label = (
            "Reviewing homes"
            if verb.startswith("review")
            else ("Scoring homes" if verb.startswith("scor") else "Updating shortlist")
        )
        return {
            "raw": text,
            "fraction_label": f"{candidate_match.group(2)} / {candidate_match.group(3)}",
            "source_label": str(source_match.group(1) or "").strip() if source_match else "",
            "phase_label": phase_label,
        }
    enrich_match = re.search(r"^Enriching top\s+(\d+)\s+candidate\(s\)\s+out of\s+(\d+)\s+for\s+(.+?)\s+before final shortlist scoring\.?$", text, flags=re.IGNORECASE)
    if enrich_match:
        return {
            "raw": text,
            "fraction_label": f"{enrich_match.group(1)} / {enrich_match.group(2)}",
            "source_label": str(enrich_match.group(3) or "").strip(),
            "phase_label": "Preparing shortlist",
        }
    shortlist_match = re.search(r"^Built shortlist of\s+(\d+)\s+listing\(s\)\s+for\s+(.+)\.$", text, flags=re.IGNORECASE)
    if shortlist_match:
        total = str(shortlist_match.group(1) or "0")
        return {
            "raw": text,
            "fraction_label": "",
            "source_label": str(shortlist_match.group(2) or "").strip(),
            "phase_label": f"Shortlist ready · {total} home{'' if total == '1' else 's'}",
        }
    prepared_match = re.search(r"^Prepared property page for\s+.+\.$", text, flags=re.IGNORECASE)
    if prepared_match:
        return {
            "raw": text,
            "fraction_label": "",
            "source_label": "",
            "phase_label": "Preparing property pages",
        }
    completed_match = re.search(r"^Completed scanning\s+(.+?)\.?$", text, flags=re.IGNORECASE)
    if completed_match:
        return {
            "raw": text,
            "fraction_label": "",
            "source_label": str(completed_match.group(1) or "").strip(),
            "phase_label": "Source finished",
        }
    return {
        "raw": text,
        "fraction_label": "",
        "source_label": str(source_match.group(1) or "").strip() if source_match else "",
        "phase_label": _compact_run_message(text),
    }


def _latest_property_run_fraction_info(run_payload: dict[str, object]) -> dict[str, str]:
    current = _parse_property_run_message_info(run_payload.get("message"))
    if current.get("fraction_label"):
        return current
    events = list(run_payload.get("events") or [])
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        parsed = _parse_property_run_message_info(event.get("message"))
        if parsed.get("fraction_label"):
            return parsed
    return current


def _property_run_candidate_reason_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = re.search(r"candidate\s+(\d+)\s+of\s+(\d+)", text, flags=re.IGNORECASE)
    if not candidate:
        return ""
    ordinal = f"{candidate.group(1)}/{candidate.group(2)}"
    normalized = text.lower()
    if any(token in normalized for token in ("balcony", "terrace", "outdoor")) and any(
        token in normalized for token in ("missing", "none", "without", "absent", "no ")
    ):
        return f"Outdoor space was missing for candidate {ordinal} (score impact only)"
    positive_signals = (
        (("balcony", "terrace", "outdoor"), "Outdoor space evidence found"),
        (("lift", "elevator", "barrier-free", "barrier free", "accessible"), "Access evidence improved the score"),
        (("operating cost", "monthly cost", "total cost", "betriebskosten"), "Cost evidence improved the score"),
        (("heating", "heizung"), "Heating evidence improved the score"),
        (("energy", "energy certificate", "energieausweis"), "Energy evidence improved the score"),
        (("internet", "broadband", "fiber", "fibre", "high-speed"), "Internet evidence improved the score"),
        (("floorplan", "layout"), "Layout evidence improved the score"),
        (("360", "matterport", "3dvista", "virtual tour", "live tour"), "Remote-view evidence improved the score"),
        (("garage", "parking"), "Parking evidence improved the score"),
        (("commute", "transit", "subway", "u-bahn", "underground", "train"), "Transit evidence improved the score"),
        (("school", "volksschule"), "School fit improved the score"),
        (("kindergarten", "childcare"), "Childcare fit improved the score"),
        (("supermarket", "pharmacy", "bakery", "market", "errand"), "Daily errands improved the score"),
        (("sunlight", "bright", "orientation", "south-facing"), "Light and orientation evidence improved the score"),
    )
    for tokens, label in positive_signals:
        if any(token in normalized for token in tokens) and any(token in normalized for token in ("found", "confirmed", "available", "evidence", "clear", "ready")):
            return f"{label} for candidate {ordinal} (score upgraded)"
    soft_concerns = (
        (("operating cost", "monthly cost", "total cost", "betriebskosten", "price"), "Cost evidence still needs verification"),
        (("heating", "heizung"), "Heating evidence still needs verification"),
        (("energy", "energy certificate", "energieausweis"), "Energy evidence still needs verification"),
        (("internet", "broadband", "fiber", "fibre", "high-speed"), "Internet evidence still needs verification"),
        (("noise", "traffic noise", "nuisance"), "Noise risk needs verification"),
        (("flood", "water", "groundwater"), "Water-risk evidence needs verification"),
        (("air quality", "pollution", "emissions"), "Air-quality risk needs verification"),
        (("crime", "safety"), "Local safety evidence needs verification"),
        (("parking", "garage"), "Parking situation needs verification"),
        (("winter", "driving"), "Winter access needs verification"),
        (("septic", "senkgrube"), "Wastewater risk needs verification"),
        (("sunlight", "orientation", "light"), "Light and orientation need verification"),
    )
    for tokens, label in soft_concerns:
        if any(token in normalized for token in tokens) and any(token in normalized for token in ("missing", "unknown", "unclear", "risk", "burden", "verify", "verification")):
            return f"{label} for candidate {ordinal} (score impact only)"
    if "district" in normalized or "postal" in normalized or "postcode" in normalized:
        if any(token in normalized for token in ("conflict", "mismatch", "outside", "wrong")):
            return f"Location evidence conflicted for candidate {ordinal} (hard area rule)"
    if (
        ("school" in normalized or "kindergarten" in normalized)
        and any(token in normalized for token in ("safe", "safer", "good", "calm", "low traffic", "low-traffic"))
        and any(token in normalized for token in ("route", "way", "walk"))
    ):
        route_label = "Way to kindergarten" if "kindergarten" in normalized else "Way to school"
        return f"{route_label} looked safe for candidate {ordinal} (score upgraded)"
    if (
        ("school" in normalized or "kindergarten" in normalized)
        and any(token in normalized for token in ("danger", "dangerous", "unsafe", "risk", "risky", "traffic"))
        and any(token in normalized for token in ("route", "way", "walk"))
    ):
        route_label = "Way to kindergarten" if "kindergarten" in normalized else "Way to school"
        return f"{route_label} looked risky for candidate {ordinal} (score impact only)"
    discovery_match = re.search(r"despite\s+a\s+(.+?)\s+miss", text, flags=re.IGNORECASE)
    if discovery_match:
        label = str(discovery_match.group(1) or "").strip()
        label = label[:1].upper() + label[1:] if label else "Preference"
        return f"{label} missed the preference for candidate {ordinal} (score impact only)"
    if "duplicate" in normalized or "already seen" in normalized or "same listing" in normalized:
        return f"Duplicate check linked candidate {ordinal} to existing property memory"
    if any(token in normalized for token in ("stale", "removed", "expired", "no longer available")):
        return f"Listing freshness check flagged candidate {ordinal} for repair"
    if any(token in normalized for token in ("repair", "extractor", "fetch failed", "provider patch")):
        return f"Provider repair lane picked up candidate {ordinal}"
    if any(token in normalized for token in ("price per sqm", "price per square", "€/m2", "eur/m2", "eur per m2")):
        if any(token in normalized for token in ("below", "under", "cheaper", "discount", "stronger than benchmark")):
            return f"Price-per-m2 benchmark improved the score for candidate {ordinal}"
        if any(token in normalized for token in ("above", "over", "expensive", "premium", "higher than benchmark")):
            return f"Price-per-m2 benchmark reduced the score for candidate {ordinal} (score impact only)"
        return f"Price-per-m2 benchmark was checked for candidate {ordinal}"
    if any(token in normalized for token in ("total monthly", "all-in cost", "warm rent", "monthly total")):
        if any(token in normalized for token in ("within", "fits", "fit", "under budget", "inside budget")):
            return f"Total monthly cost fit the budget for candidate {ordinal} (score upgraded)"
        if any(token in normalized for token in ("above", "over", "exceeds", "outside budget")):
            return f"Total monthly cost exceeded the budget for candidate {ordinal} (hard budget rule)"
    if any(token in normalized for token in ("rooms", "room count", "layout shape", "floor plan shape", "floorplan shape")):
        if any(token in normalized for token in ("fits", "fit", "matches", "matched", "usable")):
            return f"Room layout matched the home shape for candidate {ordinal} (score upgraded)"
        if any(token in normalized for token in ("awkward", "unclear", "inefficient", "needs verification")):
            return f"Room layout needs a closer check for candidate {ordinal} (score impact only)"
    if any(token in normalized for token in ("bike route", "cycling", "bicycle")):
        if any(token in normalized for token in ("safe", "protected", "direct", "calm")):
            return f"Bike route looked practical for candidate {ordinal} (score upgraded)"
        if any(token in normalized for token in ("unsafe", "traffic", "risky", "indirect")):
            return f"Bike route looked weak for candidate {ordinal} (score impact only)"
    if any(token in normalized for token in ("noise", "quiet", "street exposure")):
        if any(token in normalized for token in ("low", "quiet", "calm", "shielded")):
            return f"Noise context improved the score for candidate {ordinal}"
        if any(token in normalized for token in ("high", "loud", "exposed", "risk")):
            return f"Noise context reduced the score for candidate {ordinal} (score impact only)"
    if any(token in normalized for token in ("flood", "water", "groundwater")):
        if any(token in normalized for token in ("clear", "low", "outside", "not in")):
            return f"Water-risk evidence looked clear for candidate {ordinal} (score upgraded)"
        if any(token in normalized for token in ("risk", "burden", "inside", "unclear")):
            return f"Water-risk evidence needs review for candidate {ordinal} (score impact only)"
    if any(token in normalized for token in ("document", "energy certificate", "operating-cost statement", "betriebskosten statement")):
        if any(token in normalized for token in ("found", "available", "attached", "confirmed")):
            return f"Document evidence improved confidence for candidate {ordinal}"
        if any(token in normalized for token in ("missing", "not attached", "unavailable")):
            return f"Document evidence is still missing for candidate {ordinal} (score impact only)"
    if ("school" in normalized or "kindergarten" in normalized) and any(
        token in normalized for token in ("close enough", "within", "near", "nearby", "fit", "matches", "matched")
    ):
        fit_label = "Kindergarten distance" if "kindergarten" in normalized else "School distance"
        return f"{fit_label} fit the preference for candidate {ordinal} (score upgraded)"
    if ("school" in normalized or "kindergarten" in normalized) and any(
        token in normalized for token in ("too far", "farther", "further", "beyond", "outside")
    ):
        fit_label = "Kindergarten distance" if "kindergarten" in normalized else "School distance"
        return f"{fit_label} was wider than preferred for candidate {ordinal} (score impact only)"
    if "commute" in normalized and any(token in normalized for token in ("within", "fast", "short", "fits", "fit", "matched")):
        return f"Commute fit improved the score for candidate {ordinal}"
    if "commute" in normalized and any(token in normalized for token in ("long", "slow", "longer", "beyond", "outside")):
        return f"Commute was longer than preferred for candidate {ordinal} (score impact only)"
    if any(token in normalized for token in ("supermarket", "pharmacy", "bakery", "market", "errand")) and any(
        token in normalized for token in ("far", "farther", "beyond", "outside")
    ):
        return f"Daily errands were farther than preferred for candidate {ordinal} (score impact only)"
    distance_match = re.search(
        r"(?:outside the relaxed|beyond the preferred)\s+(.+?)\s+radius",
        text,
        flags=re.IGNORECASE,
    )
    if distance_match:
        label = str(distance_match.group(1) or "").strip().replace("-", " ")
        label = label[:1].upper() + label[1:] if label else "Distance"
        return f"{label} was too far away for candidate {ordinal} (score impact only)"
    if "below" in normalized and ("/m2" in normalized or "area" in normalized):
        return f"Area was below the minimum for candidate {ordinal}"
    if "outside the move-in horizon" in normalized:
        return f"Move-in was outside the horizon for candidate {ordinal}"
    if "outside the selected target area" in normalized:
        return f"Location was outside the selected area for candidate {ordinal} (hard area rule)"
    if "without enough barrier-free evidence" in normalized:
        return f"Barrier-free evidence was missing for candidate {ordinal}"
    if "non-residential" in normalized:
        return f"Property type did not match for candidate {ordinal}"
    if "non-listing candidate" in normalized:
        return f"Candidate {ordinal} was a generic listing page"
    if "layout verification" in normalized or "floorplan" in normalized:
        return f"Layout still needs verification for candidate {ordinal}"
    return ""


def _latest_property_run_candidate_reason_label(run_payload: dict[str, object]) -> str:
    events = list(run_payload.get("events") or [])
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        label = _property_run_candidate_reason_label(event.get("message"))
        if label:
            return label
    return _property_run_candidate_reason_label(run_payload.get("message"))


def _compact_property_provider_label(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "Provider"
    segments = [part.strip() for part in text.split("|") if str(part).strip()]
    if len(segments) > 1 and str(segments[0]).strip().lower() in _GENERIC_SOURCE_FAMILIES:
        text = segments[-1]
    else:
        for marker in ("|", "·", " — ", " – ", ":", "("):
            if marker in text:
                text = text.split(marker)[0].strip()
    words = [item for item in text.split(" ") if item]
    if len(words) > 3:
        text = " ".join(words[:3]).strip()
    if len(text) > 20 and len(words) >= 2:
        text = " ".join(words[:2]).strip()
    if len(text) > 20:
        text = f"{text[:17].rstrip()}..."
    return text or "Provider"


def _source_provider_group(source: dict[str, object]) -> str:
    family = str(source.get("provider_family") or "").strip().lower()
    if family:
        return family
    platform = str(source.get("platform") or "").strip().lower()
    if platform:
        return platform
    label = str(source.get("source_label") or source.get("label") or "").strip()
    return (label.split("|")[0] or label).strip().lower() or "provider"


def build_property_run_live_board_snapshot(
    run_payload: dict[str, object],
    *,
    plan_key: str = "free",
) -> dict[str, object]:
    payload = dict(run_payload or {})
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    status = str(payload.get("status") or summary.get("status") or "queued").strip().lower() or "queued"
    progress = max(0, min(100, _positive_int(payload.get("progress") or summary.get("progress"))))
    source_total = max(0, _positive_int(summary.get("sources_total")))
    source_rows = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    reviewed_total = max(0, _positive_int(summary.get("reviewed_listing_total") or summary.get("listing_total") or summary.get("raw_listing_total")))
    waiting_on_floorplans = max(0, _positive_int(summary.get("filtered_floorplan_total")))
    packet_prepared = max(0, _positive_int(summary.get("review_created_total")) + _positive_int(summary.get("review_existing_total")))
    shortlist_ready = max(0, _positive_int(summary.get("high_fit_total")))

    live_info = _latest_property_run_fraction_info(payload)
    current_info = _parse_property_run_message_info(payload.get("message"))
    active_source_label = str(current_info.get("source_label") or live_info.get("source_label") or "").strip()
    message_text = str(payload.get("message") or "").strip().lower()

    aggregate_label = f"{reviewed_total} homes reviewed"
    if waiting_on_floorplans > 0:
        aggregate_label += f" · {waiting_on_floorplans} still waiting on floorplans"
    phase_label = str(current_info.get("phase_label") or "").strip() or "Waiting for the first source update."
    candidate_reason_label = _latest_property_run_candidate_reason_label(payload)
    if current_info.get("fraction_label") and candidate_reason_label:
        phase_label = candidate_reason_label
    if phase_label == "Waiting for the first source update." and packet_prepared > 0 and str(payload.get("current_step") or "").strip().lower() == "source_review_packet":
        phase_label = f"{packet_prepared} property pages prepared"
    elif phase_label == "Waiting for the first source update." and shortlist_ready > 0 and str(payload.get("current_step") or "").strip().lower() == "source_shortlist":
        phase_label = f"{shortlist_ready} shortlist homes ready"

    normalized_rows: list[dict[str, object]] = []
    for source in source_rows:
        row = dict(source)
        raw_status = str(row.get("status") or row.get("state") or "").strip().lower()
        row_label = str(row.get("source_label") or row.get("label") or "").strip()
        if not raw_status:
            row["status"] = "failed" if row.get("error") else "completed"
        if active_source_label and row_label == active_source_label and not message_text.startswith("completed scanning "):
            row["status"] = "failed" if row.get("error") else "running"
        normalized_rows.append(row)
    synthetic_active = []
    if active_source_label and not any(str(row.get("source_label") or row.get("label") or "").strip() == active_source_label for row in normalized_rows) and not message_text.startswith("completed scanning "):
        synthetic_active.append({"source_label": active_source_label, "label": active_source_label, "status": "running"})
    lane_rows = [*synthetic_active, *normalized_rows]
    active_rows = [
        row for row in lane_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() in {"running", "processing", "in_progress", "working", "warming", "queued", "pending", "starting"}
    ]
    failed_rows = [
        row for row in lane_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() in {"failed", "error", "skipped"} or row.get("error")
    ]
    completed_rows = [
        row for row in lane_rows
        if str(row.get("status") or row.get("state") or "").strip().lower() in {"completed", "processed", "done", "success"}
    ]
    raw_worker_queue = [*active_rows, *failed_rows, *completed_rows]
    seen_groups: set[str] = set()
    worker_queue: list[dict[str, object]] = []
    for row in raw_worker_queue:
        key = _source_provider_group(row)
        if key in seen_groups:
            continue
        seen_groups.add(key)
        worker_queue.append(row)
    plan_cap = 4 if plan_key == "agent" else (2 if plan_key == "plus" else 1)
    run_active = progress > 0 or status in {"queued", "in_progress", "running", "processing", "starting"}
    actual_worker_count = min(plan_cap, len(worker_queue))
    worker_count = actual_worker_count if actual_worker_count > 0 else (1 if run_active else 0)
    worker_lanes: list[dict[str, object]] = []
    for index in range(worker_count):
        source = worker_queue[index] if index < len(worker_queue) else None
        raw_status = str((source or {}).get("status") or (source or {}).get("state") or "").strip().lower()
        progress_pct = _positive_int((source or {}).get("progress"))
        if progress_pct <= 0:
            if raw_status in {"completed", "processed", "done", "success", "failed", "error", "skipped"}:
                progress_pct = 100
            elif raw_status in {"running", "processing", "in_progress", "working", "warming"}:
                progress_pct = 58
            elif raw_status in {"queued", "pending", "starting"}:
                progress_pct = 18
            else:
                progress_pct = 0
        if source is None:
            status_label = "Starting" if run_active else "Idle"
        elif raw_status in {"completed", "processed", "done", "success"}:
            status_label = "Done"
        elif raw_status in {"failed", "error"} or source.get("error"):
            status_label = "Fetch failed"
        elif raw_status in {"running", "processing", "in_progress", "working", "warming"}:
            status_label = "Running"
        else:
            status_label = "Up next"
        if source is None:
            tone = "active" if status_label == "Starting" else "idle"
        elif progress_pct >= 100 and status_label == "Done":
            tone = "done"
        elif status_label in {"Running", "Starting"}:
            tone = "active"
        elif status_label == "Fetch failed":
            tone = "warn"
        else:
            tone = "queued"
        provider = str((source or {}).get("source_label") or (source or {}).get("label") or ("Preparing provider checks" if status_label == "Starting" else ("Waiting for a provider check" if source_rows else "Ready when you start")))
        group_key = _source_provider_group(source or {})
        shard_count = max(0, len([row for row in raw_worker_queue if _source_provider_group(row) == group_key]) - 1) if source else 0
        worker_lanes.append(
            {
                "label": _compact_property_provider_label(provider) if source else ("Preparing provider checks" if status_label == "Starting" else ("Waiting" if source_rows else "Ready")),
                "provider": provider,
                "shard_count": shard_count,
                "status_label": status_label,
                "progress_pct": progress_pct if source else (max(4, min(progress or 4, 12)) if status_label == "Starting" else progress_pct),
                "tone": tone,
            }
        )
    source_chips = [
        {
            "label": str(source.get("source_label") or source.get("label") or "Source"),
            "tone": "warn" if source.get("error") else "good",
        }
        for source in source_rows[:8]
    ]
    provider_full_label = str(live_info.get("source_label") or (worker_queue[0].get("source_label") if worker_queue else "") or "").strip()
    provider_total = _positive_int(summary.get("provider_total"))
    source_variant_total = _positive_int(summary.get("source_variant_total"), default=source_total)
    scan_total_label = (
        f"{provider_total} providers · {source_variant_total} variants"
        if provider_total and source_variant_total > provider_total
        else f"{source_total} provider checks"
    )
    provider_label = _compact_property_provider_label(provider_full_label or scan_total_label)
    source_count_label = live_info.get("fraction_label") or f"{len(source_rows)}/{source_total} checks"
    summary_label = (
        f"{scan_total_label} · {provider_label} · {live_info.get('fraction_label')}"
        if provider_full_label and live_info.get("fraction_label")
        else f"{scan_total_label} · {aggregate_label}"
    )
    return PropertyRunLiveBoardSnapshot(
        provider_label=provider_label,
        provider_full_label=provider_full_label,
        fraction_label=str(live_info.get("fraction_label") or "").strip(),
        phase_label=phase_label,
        aggregate_label=aggregate_label,
        summary_label=summary_label,
        source_count_label=source_count_label,
        source_chips=source_chips,
        worker_lanes=worker_lanes,
    ).to_dict()


def build_property_billing_truth_snapshot(
    *,
    commercial: dict[str, object],
    default_billing_plan: str,
    billing_enabled_plans: list[str],
    billing_order_endpoints_by_plan: dict[str, str],
    billing_provider_labels_by_plan: dict[str, str],
    fleet_digest: dict[str, object] | None = None,
) -> dict[str, object]:
    return PropertyBillingTruthSnapshot(
        current_plan_label=str(commercial.get("current_plan_label") or "Free").strip() or "Free",
        current_plan_key=str(commercial.get("current_plan_key") or "free").strip().lower() or "free",
        research_depth=str(commercial.get("research_depth") or "deep").strip() or "deep",
        max_platforms=int(commercial.get("max_platforms") or 0),
        max_results_per_source=int(commercial.get("max_results_per_source") or 0),
        checkout_provider=(
            "payfunnels"
            if default_billing_plan and billing_provider_labels_by_plan.get(default_billing_plan) == "PayFunnels"
            else ("paypal" if default_billing_plan and billing_provider_labels_by_plan.get(default_billing_plan) == "PayPal" else "")
        ),
        checkout_provider_label=str(billing_provider_labels_by_plan.get(default_billing_plan) or ""),
        checkout_enabled=bool(billing_enabled_plans),
        checkout_enabled_plans=tuple(billing_enabled_plans),
        order_endpoint=str(billing_order_endpoints_by_plan.get(default_billing_plan) or ""),
        order_endpoints_by_plan=dict(billing_order_endpoints_by_plan),
        provider_labels_by_plan=dict(billing_provider_labels_by_plan),
        fleet_digest=dict(fleet_digest or {}),
    ).to_dict()


def build_property_preference_manager_snapshot(
    *,
    person_id: str,
    raw_preference_nodes: list[dict[str, object]],
    include_full_manager: bool,
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
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

    active_preference_total = sum(
        1
        for row in raw_preference_nodes
        if str(row.get("node_id") or "").strip()
        and str(row.get("status") or "").strip().lower() in {"", "active"}
    )
    nodes = (
        [
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
        if include_full_manager
        else []
    )
    if nodes:
        nodes.sort(key=lambda row: (str(row.get("status") or "") != "active", str(row.get("label") or "").lower()))
    active_nodes = (
        [row for row in nodes if str(row.get("status") or "") == "active"]
        if include_full_manager
        else [{"status": "active"} for _ in range(active_preference_total)]
    )
    return PropertyPreferenceManagerSnapshot(
        person_id=str(person_id or "self").strip() or "self",
        nodes=nodes,
        active_nodes=active_nodes,
        schema=dict(schema or {}) if include_full_manager else {},
        bundle_endpoint=f"/app/api/people/{urllib.parse.quote(str(person_id or 'self').strip() or 'self', safe='')}/preference-profile",
        node_endpoint=f"/app/api/people/{urllib.parse.quote(str(person_id or 'self').strip() or 'self', safe='')}/preference-profile/nodes",
        archive_endpoint_template=f"/app/api/people/{urllib.parse.quote(str(person_id or 'self').strip() or 'self', safe='')}/preference-profile/nodes/__NODE_ID__/archive",
    ).to_dict()


def build_property_search_form_state_snapshot(
    property_preferences: dict[str, object] | None,
    *,
    selected_listing_mode: str,
) -> dict[str, object]:
    preferences = dict(property_preferences or {})
    selected_country_code = str(preferences.get("country_code") or "AT").strip().upper() or "AT"
    selected_search_goal = normalized_property_search_goal(preferences.get("search_goal"))
    selected_investment_strategy = str(preferences.get("investment_strategy") or "best_overall").strip().lower() or "best_overall"
    if selected_investment_strategy not in {"best_overall", "cash_flow", "appreciation", "undervalued", "low_risk"}:
        selected_investment_strategy = "best_overall"
    selected_investment_research_mode = str(preferences.get("investment_research_mode") or "off").strip().lower() or "off"
    if selected_investment_research_mode not in {"off", "auto"}:
        selected_investment_research_mode = "off"
    property_is_investment_search = selected_search_goal == "investment"
    selected_school_stage_preferences = [
        str(item or "").strip()
        for item in list(preferences.get("school_stage_preferences") or [])
        if str(item or "").strip()
    ]
    school_evidence_controls_enabled = (
        not property_is_investment_search
        and (
            bool(selected_school_stage_preferences)
            or bool(preferences.get("require_school_evidence"))
        )
    )
    effective_listing_mode_value = effective_property_listing_mode(
        {
            **preferences,
            "search_goal": selected_search_goal,
            "listing_mode": selected_listing_mode,
        },
        fallback=selected_listing_mode,
    )
    show_investment_underwriting_controls = property_is_investment_search and selected_investment_research_mode != "off"
    show_lifestyle_research_controls = not property_is_investment_search and bool(preferences.get("enable_lifestyle_research"))
    show_community_validation_controls = bool(preferences.get("include_community_signals"))
    show_developer_project_stage_controls = bool(preferences.get("include_developer_project_signals"))
    show_public_housing_policy_controls = effective_listing_mode_value == "rent" and bool(preferences.get("include_public_housing_signals"))
    show_distressed_review_controls = effective_listing_mode_value == "buy" and bool(preferences.get("include_distressed_sale_signals"))
    show_search_agent_detail_controls = bool(preferences.get("search_agent_enabled"))
    show_preference_profile_controls = bool(preferences.get("use_stored_feedback_preferences", True))
    show_playground_importance_controls = not property_is_investment_search and bool(preferences.get("max_distance_to_playground_m"))
    show_library_importance_controls = not property_is_investment_search and bool(preferences.get("max_distance_to_library_m"))
    show_supermarket_importance_controls = bool(preferences.get("max_distance_to_supermarket_m"))

    def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(float(str(preferences.get(name) or "").strip()))))
        except Exception:
            return default

    def _bounded_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
        try:
            return max(minimum, min(maximum, float(str(preferences.get(name) or "").strip())))
        except Exception:
            return default

    return PropertySearchFormStateSnapshot(
        selected_country_code=selected_country_code,
        selected_search_goal=selected_search_goal,
        selected_listing_mode=effective_listing_mode_value,
        selected_investment_strategy=selected_investment_strategy,
        selected_investment_research_mode=selected_investment_research_mode,
        property_is_investment_search=property_is_investment_search,
        selected_school_stage_preferences=selected_school_stage_preferences,
        school_evidence_controls_enabled=school_evidence_controls_enabled,
        show_investment_underwriting_controls=show_investment_underwriting_controls,
        show_lifestyle_research_controls=show_lifestyle_research_controls,
        show_community_validation_controls=show_community_validation_controls,
        show_developer_project_stage_controls=show_developer_project_stage_controls,
        show_public_housing_policy_controls=show_public_housing_policy_controls,
        show_distressed_review_controls=show_distressed_review_controls,
        show_search_agent_detail_controls=show_search_agent_detail_controls,
        show_preference_profile_controls=show_preference_profile_controls,
        show_school_evidence_priority_controls=school_evidence_controls_enabled,
        show_playground_importance_controls=show_playground_importance_controls,
        show_library_importance_controls=show_library_importance_controls,
        show_supermarket_importance_controls=show_supermarket_importance_controls,
        min_gross_yield_pct=_bounded_int("min_gross_yield_pct", default=0, minimum=0, maximum=15),
        equity_available_eur=_bounded_int("equity_available_eur", default=0, minimum=0, maximum=5_000_000),
        loan_term_years=_bounded_int("loan_term_years", default=25, minimum=5, maximum=40),
        max_interest_rate_pct=_bounded_int("max_interest_rate_pct", default=0, minimum=0, maximum=12),
        min_dscr=_bounded_float("min_dscr", default=0.0, minimum=0.0, maximum=3.0),
        vacancy_reserve_pct=_bounded_int("vacancy_reserve_pct", default=4, minimum=0, maximum=25),
        capex_reserve_pct=_bounded_int("capex_reserve_pct", default=6, minimum=0, maximum=25),
    ).to_dict()


def _previous_run_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(float(str(value or "").strip())))
    except Exception:
        return default


def _previous_run_price_text(candidate: dict[str, object]) -> str:
    facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
    for raw_value in (
        candidate.get("price_display"),
        candidate.get("costs_display"),
        facts.get("price_display"),
        facts.get("rent_display"),
        facts.get("price"),
        facts.get("rent"),
    ):
        text = str(raw_value or "").strip()
        if text:
            return text
    title_text = " ".join(str(candidate.get("title") or "").split()).strip()
    if not title_text:
        return ""
    currency_pattern = "|".join(re.escape(code) for code in supported_currency_codes())
    for pattern in (
        r"(€\s?[0-9][0-9\.\s]*(?:,\d{1,2})?\s*,-?)",
        rf"((?:{currency_pattern})\s?[0-9][0-9\.,\s]*)",
    ):
        match = re.search(pattern, title_text, flags=re.IGNORECASE)
        if match:
            return " ".join(str(match.group(1) or "").split()).strip(" ,")
    return ""


def build_property_previous_run_summary(
    raw_run: dict[str, object],
    *,
    include_scope_preview: bool,
    scope_preview_builder: Callable[[str, str, str], dict[str, object]],
    compact_provider_label: Callable[[str], str],
    candidate_maps_url_builder: Callable[[dict[str, object]], str],
) -> dict[str, object]:
    summary = dict(raw_run.get("summary") or {}) if isinstance(raw_run.get("summary"), dict) else {}
    preferences_json = dict(raw_run.get("property_search_preferences") or raw_run.get("preferences") or {}) if isinstance(raw_run.get("property_search_preferences") or raw_run.get("preferences"), dict) else {}
    run_status = str(raw_run.get("status") or summary.get("status") or "queued").strip().lower()
    run_id_value = str(raw_run.get("run_id") or "").strip()
    country = str(preferences_json.get("country_code") or summary.get("country_code") or "").strip().upper()
    region = str(preferences_json.get("region_code") or summary.get("region_code") or "").strip()
    location = str(preferences_json.get("location_query") or summary.get("location_query") or "").strip()
    mode = property_mode_visibility_label(
        {
            **summary,
            **preferences_json,
        },
        fallback=str(summary.get("listing_mode") or "rent"),
    )
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
        source_short_label = compact_provider_label(source_label)
        top_candidates.append(
            {
                "title": title,
                "source_label": source_label,
                "source_short_label": source_short_label,
                "fit_score": _previous_run_int(candidate.get("fit_score")),
                "detail": str(
                    candidate.get("compare_reason")
                    or candidate.get("fit_summary")
                    or (list(candidate.get("match_reasons") or [""])[0] if isinstance(candidate.get("match_reasons"), list) else "")
                    or "Open the finished search to review this candidate."
                ).strip(),
                "review_url": str(candidate.get("packet_url") or candidate.get("review_url") or "").strip(),
                "map_url": str(candidate.get("map_url") or candidate_maps_url_builder(candidate)).strip(),
                "price_display": _previous_run_price_text(candidate),
            }
        )
    held_back_total = max(
        0,
        _previous_run_int(summary.get("filtered_floorplan_total"))
        + _previous_run_int(summary.get("filtered_area_total"))
        + _previous_run_int(summary.get("filtered_property_type_total"))
        + _previous_run_int(summary.get("filtered_availability_total"))
        + _previous_run_int(summary.get("filtered_generic_page_total"))
        + _previous_run_int(summary.get("filtered_listing_mode_total"))
    )
    status_label, status_note = property_run_status_copy(
        raw_run.get("status") or summary.get("status"),
        raw_run.get("message") or summary.get("message"),
    )
    scope_preview = scope_preview_builder(country, region, location) if include_scope_preview else {}
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
        "href": f"/app/shortlist?run_id={urllib.parse.quote(run_id_value, safe='')}" if run_id_value else "/app/shortlist",
        "updated_at": str(raw_run.get("updated_at") or raw_run.get("generated_at") or "").strip(),
        "source_total": _previous_run_int(summary.get("sources_total")),
        "listing_total": _previous_run_int(summary.get("listing_total") or summary.get("raw_listing_total")),
        "ranked_total": len(ranked_candidates),
        "sent_total": _previous_run_int(summary.get("notified_total") or summary.get("watch_notified_total")),
        "held_back_total": held_back_total,
        "top_fit_score": _previous_run_int(summary.get("top_fit_score") or (top_candidates[0].get("fit_score") if top_candidates else 0)),
        "top_price_display": str((top_candidates[0].get("price_display") if top_candidates else "") or "").strip(),
        "top_candidates": top_candidates,
        "is_finished": run_status in {"processed", "completed", "failed", "noop", "cancelled"},
    }


def build_property_empty_outcome_summary(
    *,
    run_summary: dict[str, object],
    run_sources: list[dict[str, object]],
    run_status_value: str,
    run_message: str,
    counterfactual_rows: list[dict[str, object]],
    suppression_rows: list[dict[str, object]],
) -> dict[str, str]:
    filtered_total = int(run_summary.get("filtered_total") or run_summary.get("held_back_total") or 0)
    source_total = int(run_summary.get("sources_total") or len(run_sources) or 0)
    source_completed = int(
        run_summary.get("sources_completed")
        or len(
            [
                row
                for row in (run_sources or [])
                if str(row.get("status") or "").strip().lower() in {"completed", "processed", "ok"}
            ]
        )
        or 0
    )
    listing_total = int(run_summary.get("listing_total") or 0)
    status_value = str(run_status_value or "").strip().lower()
    eta_label = str(run_summary.get("eta_label") or "").strip()
    repair_step_label = str(run_summary.get("repair_step_label") or "").strip()
    repair_status_label = str(run_summary.get("repair_status_label") or run_summary.get("repair_status") or "").strip()
    repair_tasks = [row for row in list(run_summary.get("provider_repair_tasks") or []) if isinstance(row, dict)]
    repair_task_open = any(str(row.get("status") or "").strip().lower() in {"opened", "assigned", "running", "repairing"} for row in repair_tasks)
    strongest_relax = next((row for row in (counterfactual_rows or []) if row.get("adjustments")), {})
    active_rule = ""
    if strongest_relax:
        active_rule = str(strongest_relax.get("title") or strongest_relax.get("rule_label") or "").strip()
    elif suppression_rows:
        active_rule = str((suppression_rows[0] or {}).get("title") or "").strip()
    if status_value == "failed":
        if source_total or listing_total:
            completed_label = f"{source_completed}/{source_total} source variants" if source_total else "Source variants"
            listing_label = f"{listing_total} listing{'s' if listing_total != 1 else ''}"
            if repair_task_open:
                happened = "A repair task is open in the fleet and will retry the interrupted source variants."
            elif repair_step_label or repair_status_label:
                happened = "Auto-repair is queued and will retry the interrupted source variants."
            else:
                happened = "The search stopped before a stable shortlist was ready."
            stopped_context = f"The interrupted pass stopped after {completed_label.lower()} and {listing_label} inspected."
        else:
            happened = str(run_message or "The search stopped before a stable shortlist was ready.").strip()
            stopped_context = ""
    elif filtered_total > 0:
        happened = f"The search finished, but {filtered_total} candidate{'s' if filtered_total != 1 else ''} stayed outside the shortlist."
    else:
        happened = "The search finished without a candidate clearing the current shortlist."
    still_worked = (
        f"{source_total} provider check{'s' if source_total != 1 else ''} covered {listing_total} listing{'s' if listing_total != 1 else ''}."
        if source_total or listing_total
        else "The brief, providers, and run receipts were still recorded."
    )
    if status_value == "failed":
        next_move = "Wait for repair; this page checks quietly every 10s and will move to the usable run when one is ready."
    else:
        next_move = (
            str(strongest_relax.get("detail") or "").strip()
            or (f"Relax {active_rule} first so the next run changes one rule at a time." if active_rule else "")
            or "Widen one rule first, then rerun."
        )
    if status_value == "failed" and repair_step_label:
        eta_feedback = stopped_context
    elif status_value == "failed" and repair_status_label:
        eta_feedback = f"Repair status: {repair_status_label}. {stopped_context}".strip()
    elif status_value not in {"processed", "completed", "completed_partial", "noop", "cancelled"} and eta_label:
        eta_feedback = f"Estimated remaining time: {eta_label}."
    elif source_total:
        eta_feedback = f"{source_completed}/{source_total} provider checks completed."
    elif status_value == "failed":
        eta_feedback = "Repair has the run queued; refresh this page or open the rerun when it appears."
    else:
        eta_feedback = "The run is complete; rerun after changing one rule to get a fresh ETA."
    return {
        "happened": happened,
        "still_worked": still_worked,
        "next_move": next_move,
        "active_rule": active_rule,
        "eta_feedback": eta_feedback,
    }


def build_property_shortlist_snapshot(
    results: list[dict[str, object]],
    *,
    selected_candidate_ref: str = "",
) -> dict[str, object]:
    ordered_results = [dict(row) for row in list(results or []) if isinstance(row, dict)]
    selected = ordered_results[0] if ordered_results else {}
    normalized_selected_ref = str(selected_candidate_ref or "").strip()
    if normalized_selected_ref:
        for row in ordered_results:
            if str(row.get("candidate_ref") or "").strip() != normalized_selected_ref:
                continue
            selected = row
            break
    return PropertyShortlistSnapshot(
        results=ordered_results,
        selected=selected,
        selected_candidate_ref=str(selected.get("candidate_ref") or "").strip(),
        results_total=len(ordered_results),
        has_results=bool(ordered_results),
    ).to_dict()


def build_property_search_agent_selection_snapshot(
    property_search_agents: list[dict[str, object]],
    *,
    requested_agent_id: str,
    previous_runs: list[dict[str, object]],
    run_id: str,
) -> dict[str, object]:
    selected_agent = next(
        (
            agent
            for agent in property_search_agents
            if str(agent.get("agent_id") or "").strip() == str(requested_agent_id or "").strip()
        ),
        None,
    )
    if selected_agent is None:
        selected_agent = next(
            (agent for agent in property_search_agents if agent.get("is_active")),
            property_search_agents[0] if property_search_agents else None,
        )
    selected_agent_id = str((selected_agent or {}).get("agent_id") or "").strip()
    selected_agent_runs = [
        dict(row)
        for row in previous_runs
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
    latest_run = selected_agent_runs[0] if selected_agent_runs else {}
    open_href = ""
    edit_href = ""
    if selected_agent_id:
        open_href = f"/app/agents?agent_id={urllib.parse.quote(selected_agent_id, safe='')}"
        edit_href = f"/app/properties?load_agent={urllib.parse.quote(selected_agent_id, safe='')}"
        if run_id:
            suffix = urllib.parse.quote(run_id, safe="")
            open_href = f"{open_href}&run_id={suffix}"
            edit_href = f"{edit_href}&run_id={suffix}"
    return PropertySearchAgentSelectionSnapshot(
        selected_agent=dict(selected_agent or {}),
        selected_agent_id=selected_agent_id,
        selected_agent_runs=selected_agent_runs,
        selected_agent_latest_run=dict(latest_run or {}),
        selected_agent_open_href=open_href,
        selected_agent_edit_href=edit_href,
    ).to_dict()


def build_property_workbench_candidate_snapshot(
    *,
    candidate_ref: str,
    rank: int,
    title: str,
    source_label: str,
    location_label: str,
    price_display: str,
    costs_display: str,
    price_per_sqm_display: str,
    layout_display: str,
    layout_verification_label: str,
    fit_score: int,
    fit_label: str,
    fit_summary: str,
    tour: dict[str, object],
    flythrough: dict[str, object] | None = None,
    orientation_preview: dict[str, object],
    ooda: dict[str, object],
    risk: dict[str, object],
    investment: dict[str, object],
    match_reasons: list[str],
    mismatch_reasons: list[str],
    review_page_neuronwriter: dict[str, object],
    packet_url: str,
    review_url: str,
    property_url: str,
    map_url: str,
    source_url: str,
    floorplan_url: str = "",
    property_facts: dict[str, object],
    assessment: dict[str, object],
    objection_rows: list[dict[str, str]],
    timeline_rows: list[dict[str, str]],
    household_rows: list[dict[str, str]],
    risk_signal_rows: list[dict[str, str]],
    followup_rows: list[dict[str, str]],
    recent_change_rows: list[dict[str, str]],
    official_evidence_rows: list[dict[str, str]],
    official_posture_rows: list[dict[str, str]],
    object_rows: list[dict[str, str]],
    cost_rows: list[dict[str, str]],
    feature_values: list[dict[str, str]],
    description_text: str,
    location_text: str,
    energy_rows: list[dict[str, str]],
    household_alignment_score: int,
    household_alignment_label: str,
    recovered_by_filter: bool = False,
    relaxed_filter_label: str = "",
    preview_image_url: str = "",
    repair_flag_label: str = "",
    repair_flag_detail: str = "",
) -> dict[str, object]:
    return PropertyWorkbenchCandidateSnapshot(
        candidate_ref=str(candidate_ref or "").strip(),
        rank=max(1, int(rank or 1)),
        title=str(title or "Candidate").strip() or "Candidate",
        source_label=str(source_label or "").strip(),
        location_label=str(location_label or "").strip(),
        price_display=str(price_display or "").strip() or "n/a",
        costs_display=str(costs_display or "").strip(),
        price_per_sqm_display=str(price_per_sqm_display or "").strip(),
        layout_display=str(layout_display or "").strip() or "n/a",
        layout_verification_label=str(layout_verification_label or "").strip() or "needs check",
        fit_score=max(0, min(100, int(fit_score or 0))),
        fit_label=str(fit_label or "Candidate").strip() or "Candidate",
        fit_summary=str(fit_summary or "").strip(),
        tour=dict(tour or {}),
        flythrough=dict(flythrough or {}),
        orientation_preview=dict(orientation_preview or {}),
        ooda=dict(ooda or {}),
        risk=dict(risk or {}),
        investment=dict(investment or {}),
        match_reasons=[str(item).strip() for item in list(match_reasons or []) if str(item).strip()],
        mismatch_reasons=[str(item).strip() for item in list(mismatch_reasons or []) if str(item).strip()],
        review_page_neuronwriter=dict(review_page_neuronwriter or {}),
        packet_url=str(packet_url or "").strip(),
        review_url=str(review_url or "").strip(),
        property_url=str(property_url or "").strip(),
        map_url=str(map_url or "").strip(),
        source_url=str(source_url or "").strip(),
        floorplan_url=str(floorplan_url or "").strip(),
        property_facts=dict(property_facts or {}),
        assessment=dict(assessment or {}),
        objection_rows=[dict(row) for row in list(objection_rows or []) if isinstance(row, dict)],
        timeline_rows=[dict(row) for row in list(timeline_rows or []) if isinstance(row, dict)],
        household_rows=[dict(row) for row in list(household_rows or []) if isinstance(row, dict)],
        risk_signal_rows=[dict(row) for row in list(risk_signal_rows or []) if isinstance(row, dict)],
        followup_rows=[dict(row) for row in list(followup_rows or []) if isinstance(row, dict)],
        recent_change_rows=[dict(row) for row in list(recent_change_rows or []) if isinstance(row, dict)],
        official_evidence_rows=[dict(row) for row in list(official_evidence_rows or []) if isinstance(row, dict)],
        official_posture_rows=[dict(row) for row in list(official_posture_rows or []) if isinstance(row, dict)],
        object_rows=[dict(row) for row in list(object_rows or []) if isinstance(row, dict)],
        cost_rows=[dict(row) for row in list(cost_rows or []) if isinstance(row, dict)],
        feature_values=[dict(row) for row in list(feature_values or []) if isinstance(row, dict)],
        description_text=str(description_text or "").strip(),
        location_text=str(location_text or "").strip(),
        energy_rows=[dict(row) for row in list(energy_rows or []) if isinstance(row, dict)],
        household_alignment_score=max(0, int(household_alignment_score or 0)),
        household_alignment_label=str(household_alignment_label or "waiting").strip() or "waiting",
        recovered_by_filter=bool(recovered_by_filter),
        relaxed_filter_label=str(relaxed_filter_label or "").strip(),
        preview_image_url=str(preview_image_url or "").strip(),
        repair_flag_label=str(repair_flag_label or "").strip(),
        repair_flag_detail=str(repair_flag_detail or "").strip(),
    ).to_dict()


def build_property_research_packet_snapshot(
    *,
    title: str,
    summary: str,
    source_label: str,
    price: str,
    area: str,
    rooms: str,
    location: str,
    media: dict[str, object],
    preview_image: dict[str, object],
    gallery_items: list[dict[str, object]],
    location_preview: dict[str, object],
    actions: list[dict[str, object]],
    visual_status_line: str,
    source_ref: str,
    run_id: str,
    candidate_ref: str,
    overview_rows: list[dict[str, object]],
    sections: list[dict[str, object]],
    match_reasons: list[str],
    mismatch_reasons: list[str],
    listing_rows: list[dict[str, object]],
    cost_rows: list[dict[str, object]],
    feature_values: list[dict[str, object]],
    description_text: str,
    location_text: str,
    energy_rows: list[dict[str, object]],
    missing_rows: list[dict[str, object]],
    decision_rows: list[dict[str, object]],
    compare_rows: list[dict[str, object]],
    compare_table_rows: list[object],
    compare_headers: list[str],
    official_evidence_rows: list[dict[str, object]],
    official_posture_rows: list[dict[str, object]],
    future_research_rows: list[dict[str, object]],
    provenance_rows: list[dict[str, object]],
    timeline_rows: list[dict[str, object]],
    everyday_fit_rows: list[dict[str, object]],
    risk_fit_rows: list[dict[str, object]],
    investment_rows: list[dict[str, object]],
    investment_risk_rows: list[dict[str, object]],
    next_best_question: str,
    feedback: dict[str, object],
    neuronwriter: dict[str, object],
    objection_rows: list[dict[str, object]],
    household_rows: list[dict[str, object]],
    risk_signal_rows: list[dict[str, object]],
) -> dict[str, object]:
    if isinstance(preview_image, dict):
        preview_image_payload = dict(preview_image)
    else:
        preview_image_url = str(preview_image or "").strip()
        preview_image_payload = {"image_url": preview_image_url} if preview_image_url else {}
    return PropertyResearchPacketSnapshot(
        research_title=str(title or "").strip() or "Research packet",
        research_summary=str(summary or "").strip(),
        research_source_label=str(source_label or "").strip(),
        research_price=str(price or "").strip(),
        research_area=str(area or "").strip(),
        research_rooms=str(rooms or "").strip(),
        research_location=str(location or "").strip(),
        research_media=dict(media or {}),
        research_preview_image=preview_image_payload,
        research_gallery_items=[dict(row) for row in list(gallery_items or []) if isinstance(row, dict)],
        research_location_preview=dict(location_preview or {}),
        research_actions=[dict(row) for row in list(actions or []) if isinstance(row, dict)],
        research_visual_status_line=str(visual_status_line or "").strip(),
        research_source_ref=str(source_ref or "").strip(),
        research_run_id=str(run_id or "").strip(),
        research_candidate_ref=str(candidate_ref or "").strip(),
        research_overview_rows=[dict(row) for row in list(overview_rows or []) if isinstance(row, dict)],
        research_sections=[dict(row) for row in list(sections or []) if isinstance(row, dict)],
        research_match_reasons=[str(row).strip() for row in list(match_reasons or []) if str(row).strip()],
        research_mismatch_reasons=[str(row).strip() for row in list(mismatch_reasons or []) if str(row).strip()],
        research_listing_rows=[dict(row) for row in list(listing_rows or []) if isinstance(row, dict)],
        research_cost_rows=[dict(row) for row in list(cost_rows or []) if isinstance(row, dict)],
        research_feature_values=[dict(row) for row in list(feature_values or []) if isinstance(row, dict)],
        research_description_text=str(description_text or "").strip(),
        research_location_text=str(location_text or "").strip(),
        research_energy_rows=[dict(row) for row in list(energy_rows or []) if isinstance(row, dict)],
        research_missing_rows=[dict(row) for row in list(missing_rows or []) if isinstance(row, dict)],
        research_decision_rows=[dict(row) for row in list(decision_rows or []) if isinstance(row, dict)],
        research_compare_rows=[dict(row) for row in list(compare_rows or []) if isinstance(row, dict)],
        research_compare_table_rows=[
            [dict(cell) if isinstance(cell, dict) else cell for cell in row]
            if isinstance(row, (list, tuple))
            else (dict(row) if isinstance(row, dict) else row)
            for row in list(compare_table_rows or [])
        ],
        research_compare_headers=[str(row).strip() for row in list(compare_headers or []) if str(row).strip()],
        research_official_evidence_rows=[dict(row) for row in list(official_evidence_rows or []) if isinstance(row, dict)],
        research_official_posture_rows=[dict(row) for row in list(official_posture_rows or []) if isinstance(row, dict)],
        research_future_research_rows=[dict(row) for row in list(future_research_rows or []) if isinstance(row, dict)],
        research_provenance_rows=[dict(row) for row in list(provenance_rows or []) if isinstance(row, dict)],
        research_timeline_rows=[dict(row) for row in list(timeline_rows or []) if isinstance(row, dict)],
        research_everyday_fit_rows=[dict(row) for row in list(everyday_fit_rows or []) if isinstance(row, dict)],
        research_risk_fit_rows=[dict(row) for row in list(risk_fit_rows or []) if isinstance(row, dict)],
        research_investment_rows=[dict(row) for row in list(investment_rows or []) if isinstance(row, dict)],
        research_investment_risk_rows=[dict(row) for row in list(investment_risk_rows or []) if isinstance(row, dict)],
        research_next_best_question=str(next_best_question or "").strip(),
        research_feedback=dict(feedback or {}),
        research_neuronwriter=dict(neuronwriter or {}),
        research_objection_rows=[dict(row) for row in list(objection_rows or []) if isinstance(row, dict)],
        research_household_rows=[dict(row) for row in list(household_rows or []) if isinstance(row, dict)],
        research_risk_signal_rows=[dict(row) for row in list(risk_signal_rows or []) if isinstance(row, dict)],
    ).to_dict()


def build_property_recurring_watch_snapshot(
    raw_agent: dict[str, object],
    *,
    property_preferences: dict[str, object],
    selected_platforms: list[str],
    selected_listing_mode: str,
    search_mode_requested: str,
    default_duration_days: int,
    default_notification_limit: int,
    default_notification_period: str,
    normalize_property_type_values: Callable[[object], list[str]],
    scope_preview_builder: Callable[[str, str, str], dict[str, object]],
    safe_agent_load_payload: Callable[[dict[str, object]], dict[str, object]],
) -> dict[str, object]:
    saved_preferences = (
        dict(raw_agent.get("preferences_json") or {})
        if isinstance(raw_agent.get("preferences_json"), dict)
        else {}
    )
    agent_duration_days = _positive_int(raw_agent.get("duration_days"), default=default_duration_days)
    agent_duration_days = max(7, min(365, agent_duration_days or default_duration_days))
    agent_notification_limit = _positive_int(raw_agent.get("notification_limit"), default=default_notification_limit)
    agent_notification_limit = max(1, min(50, agent_notification_limit or default_notification_limit))
    agent_notification_period = str(raw_agent.get("notification_period") or default_notification_period).strip().lower()
    if agent_notification_period not in {"day", "week"}:
        agent_notification_period = default_notification_period
    agent_selected_platforms = (
        saved_preferences.get("selected_platforms")
        if isinstance(saved_preferences.get("selected_platforms"), list)
        else (raw_agent.get("selected_platforms") if isinstance(raw_agent.get("selected_platforms"), list) else selected_platforms)
    )
    agent_enabled = bool(raw_agent.get("enabled"))
    agent_search_goal = normalized_property_search_goal(
        saved_preferences.get("search_goal") or raw_agent.get("search_goal") or property_preferences.get("search_goal")
    )
    agent_listing_mode = effective_property_listing_mode(
        {
            **property_preferences,
            **saved_preferences,
            "search_goal": agent_search_goal,
            "listing_mode": saved_preferences.get("listing_mode") or raw_agent.get("listing_mode") or selected_listing_mode,
        },
        fallback=selected_listing_mode,
    )
    agent_country_code = str(saved_preferences.get("country_code") or raw_agent.get("country_code") or property_preferences.get("country_code") or "AT").strip().upper()
    agent_location_query = str(saved_preferences.get("location_query") or raw_agent.get("location_query") or property_preferences.get("location_query") or "").strip()
    agent_property_types = normalize_property_type_values(saved_preferences.get("property_type") or raw_agent.get("property_type") or property_preferences.get("property_type"))
    agent_region_code = str(saved_preferences.get("region_code") or raw_agent.get("region_code") or property_preferences.get("region_code") or "").strip().lower()
    agent_name = str(raw_agent.get("name") or "").strip()
    goal_mode_label = "Investment" if agent_search_goal == "investment" else ("Buy" if agent_listing_mode == "buy" else "Rent")
    if not agent_name:
        agent_name = f"{goal_mode_label} search · {agent_location_query or agent_country_code}"
    last_run_at = str(raw_agent.get("last_run_at") or "").strip()
    next_run_at = str(raw_agent.get("next_run_at") or "").strip()
    sent_in_current_window = _positive_int(raw_agent.get("sent_in_current_window"), default=0)
    remaining_notifications = max(agent_notification_limit - sent_in_current_window, 0)
    area_label = agent_location_query or agent_country_code or "No area saved"
    notification_label = f"{agent_notification_limit} per {('week' if agent_notification_period == 'week' else 'day')}"
    scope_preview = scope_preview_builder(
        agent_country_code,
        agent_region_code,
        agent_location_query,
    )
    return PropertyRecurringWatchSnapshot(
        agent_id=str(raw_agent.get("agent_id") or "current").strip() or "current",
        name=agent_name,
        enabled=agent_enabled,
        is_active=bool(raw_agent.get("is_active")),
        status_label="Active" if agent_enabled else "Paused",
        duration_days=agent_duration_days,
        duration_label=(
            "1 week"
            if agent_duration_days == 7
            else "1 year"
            if agent_duration_days == 365
            else f"{agent_duration_days} days"
        ),
        notification_limit=agent_notification_limit,
        notification_period=agent_notification_period,
        notification_period_label="week" if agent_notification_period == "week" else "day",
        location_query=agent_location_query,
        listing_mode=agent_listing_mode,
        country_code=agent_country_code,
        region_code=agent_region_code,
        property_type=", ".join(agent_property_types),
        provider_count=len(agent_selected_platforms),
        last_run_label=last_run_at or "not run yet",
        next_run_label=next_run_at or ("waiting for scheduler" if agent_enabled else "paused"),
        sent_in_current_window=sent_in_current_window,
        remaining_notifications=remaining_notifications,
        area_label=area_label,
        scope_label=f"{goal_mode_label} · {area_label} · {agent_country_code}",
        scope_preview=scope_preview,
        notification_label=notification_label,
        run_label=f"Last: {last_run_at or 'not run yet'} · Next: {next_run_at or ('waiting for scheduler' if agent_enabled else 'paused')}",
        delivery_label=f"Sent {sent_in_current_window}/{agent_notification_limit} this {('week' if agent_notification_period == 'week' else 'day')}",
        load_payload={
            **(
                safe_agent_load_payload(saved_preferences)
                if saved_preferences
                else {
                    "country_code": agent_country_code,
                    "region_code": agent_region_code,
                    "location_query": agent_location_query,
                    "property_type": agent_property_types,
                    "search_mode": str(raw_agent.get("search_mode") or search_mode_requested or "strict").strip().lower() or "strict",
                    "selected_platforms": list(agent_selected_platforms or []),
                    "search_agent_enabled": agent_enabled,
                    "search_agent_duration_days": agent_duration_days,
                    "search_agent_notification_limit": agent_notification_limit,
                    "search_agent_notification_period": agent_notification_period,
                }
            ),
            "search_goal": agent_search_goal,
            "listing_mode": agent_listing_mode,
        },
    ).to_dict()
