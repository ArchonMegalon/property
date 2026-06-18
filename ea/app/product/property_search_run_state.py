from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable


def property_search_run_expired(
    at_iso: str,
    *,
    ttl_seconds: int,
    parse_utcish: Callable[[str], datetime | None],
) -> bool:
    parsed = parse_utcish(at_iso)
    if parsed is None:
        return True
    return (datetime.now(timezone.utc) - parsed).total_seconds() > float(ttl_seconds)


def property_search_run_stale_seconds(*, default_seconds: int) -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS") or "").strip()
    if not raw_value:
        return default_seconds
    try:
        parsed = int(raw_value)
    except Exception:
        return default_seconds
    return max(60, min(parsed, 24 * 60 * 60))


def property_search_review_open_timeout_seconds(*, default_seconds: float = 20.0) -> float:
    raw_value = str(os.getenv("EA_PROPERTY_SEARCH_REVIEW_OPEN_TIMEOUT_SECONDS") or "").strip()
    if not raw_value:
        return default_seconds
    try:
        parsed = float(raw_value)
    except Exception:
        return default_seconds
    return max(1.0, min(parsed, 300.0))


def property_search_run_is_stale(
    state: dict[str, object],
    *,
    terminal_statuses: set[str] | frozenset[str],
    parse_utcish: Callable[[str], datetime | None],
    stale_seconds: int,
) -> bool:
    status = str(state.get("status") or "").strip().lower()
    if not status or status in terminal_statuses or status == "initialization_required":
        return False
    parsed = parse_utcish(str(state.get("updated_at") or state.get("created_at") or ""))
    if parsed is None:
        return True
    return (datetime.now(timezone.utc) - parsed).total_seconds() > float(stale_seconds)


def property_search_run_default_summary(
    property_preferences: dict[str, object] | None,
    *,
    now_iso: Callable[[], str],
    effective_min_match_score: Callable[[dict[str, object] | None], float],
    match_score_cap: Callable[[dict[str, object] | None], float],
) -> dict[str, object]:
    min_match_score = effective_min_match_score(property_preferences)
    return {
        "generated_at": now_iso(),
        "status": "queued",
        "sources_total": 0,
        "listing_total": 0,
        "duplicate_listing_total": 0,
        "review_created_total": 0,
        "review_existing_total": 0,
        "notified_total": 0,
        "email_notified_total": 0,
        "tour_created_total": 0,
        "tour_existing_total": 0,
        "high_fit_total": 0,
        "filtered_area_total": 0,
        "filtered_property_type_total": 0,
        "filtered_availability_total": 0,
        "filtered_floorplan_total": 0,
        "filtered_low_fit_total": 0,
        "provider_cache_hit_total": 0,
        "provider_cache_refresh_total": 0,
        "public_property_cache_hit_total": 0,
        "public_property_cache_refresh_total": 0,
        "high_match_min_score": min_match_score,
        "max_match_score": match_score_cap(property_preferences),
        "min_area_m2": dict(property_preferences or {}).get("min_area_m2") or 0,
        "watch_notified_total": 0,
        "top_fit_score": 0.0,
        "sources_completed": 0,
        "eta_seconds": 0,
        "eta_label": "",
        "sources": [],
    }


def property_search_run_step_source_fraction(step: str) -> float:
    normalized = str(step or "").strip().lower()
    fractions = {
        "queued": 0.0,
        "starting": 0.01,
        "sources_resolved": 0.03,
        "source_started": 0.06,
        "source_fetching": 0.04,
        "source_extracting": 0.18,
        "source_rank_prep": 0.24,
        "source_previewing": 0.38,
        "source_assessing": 0.58,
        "source_ranking": 0.72,
        "source_shortlist": 0.84,
        "source_review_packet": 0.92,
        "source_completed": 1.0,
        "completed": 1.0,
    }
    return max(0.0, min(float(fractions.get(normalized, 0.0)), 1.0))


def property_search_eta_label(seconds: float) -> str:
    bounded = max(0.0, float(seconds or 0.0))
    if bounded < 45.0:
        return "under 1 min"
    minutes = int(round(bounded / 60.0))
    if minutes < 60:
        return f"about {minutes} min"
    hours = minutes // 60
    remainder = minutes % 60
    if remainder == 0:
        return f"about {hours} hr"
    return f"about {hours} hr {remainder} min"


def property_search_run_stale_failure_event(
    state: dict[str, object],
    *,
    stale_seconds: int,
) -> dict[str, object]:
    minutes = max(1, int(float(stale_seconds) / 60.0))
    summary = dict(state.get("summary") or {})
    source_rows = [dict(item) for item in list(summary.get("sources") or []) if isinstance(item, dict)]
    successful_source_total = len([row for row in source_rows if not str(row.get("error") or "").strip()])
    failed_source_total = len([row for row in source_rows if str(row.get("error") or "").strip()])
    ranked_candidate_total = len(list(summary.get("ranked_candidates") or []))
    listing_total = max(0, int(summary.get("listing_total") or 0))
    review_total = max(0, int(summary.get("review_created_total") or 0) + int(summary.get("review_existing_total") or 0))
    recovered_partial = (
        ranked_candidate_total > 0
        or listing_total > 0
        or review_total > 0
        or successful_source_total > 0
    )
    outcome = (
        property_search_run_terminal_outcome(
            sources_total=max(0, int(summary.get("sources_total") or len(source_rows))),
            failed_total=max(0, int(summary.get("failed_total") or failed_source_total)),
            successful_source_total=successful_source_total,
        )
        if source_rows
        else ("completed_partial" if recovered_partial else "failed")
    )
    if outcome == "processed" and recovered_partial:
        outcome = "completed_partial"
    if recovered_partial:
        message = (
            f"Search interrupted after more than {minutes} minutes without updates. "
            "The current shortlist is still available, but full market coverage did not finish."
        )
    else:
        message = (
            f"Search interrupted. This run stopped updating for more than {minutes} minutes and is now marked failed. "
            "Start a new search to retry the same brief."
        )
    summary_updates = {
        "interrupted": True,
        "stale_after_seconds": stale_seconds,
        "last_known_status": str(state.get("status") or "").strip().lower(),
    }
    if recovered_partial:
        summary_updates.update(
            {
                "repair_status": "degraded",
                "repair_status_label": "Partial coverage",
                "can_auto_repair": True,
                "customer_status_message": (
                    "The shortlist is ready, but one or more sources stopped before the full market scan finished."
                ),
            }
        )
    return {
        "step": "run_interrupted",
        "message": message,
        "status": outcome,
        "summary_updates": summary_updates,
        "force_status": outcome,
    }


def property_search_run_terminal_outcome(
    *,
    sources_total: int,
    failed_total: int,
    successful_source_total: int,
) -> str:
    total_sources = max(0, int(sources_total or 0))
    failed_sources = max(0, int(failed_total or 0))
    successful_sources = max(0, int(successful_source_total or 0))
    if failed_sources <= 0:
        return "processed"
    if successful_sources > 0:
        return "completed_partial"
    if total_sources > 0 and failed_sources >= total_sources:
        return "failed"
    return "completed_partial"


def property_search_run_sync_summary(
    *,
    state: dict[str, object],
    summary: dict[str, object] | None,
    terminal_statuses: set[str] | frozenset[str],
    eta_seconds: int | None = None,
    eta_label: str | None = None,
) -> dict[str, object]:
    normalized_summary = dict(summary or {})
    normalized_status = str(state.get("status") or normalized_summary.get("status") or "").strip().lower()
    if normalized_status:
        normalized_summary["status"] = normalized_status
    if normalized_status in terminal_statuses:
        progress_value = int(state.get("progress") or 100)
        normalized_summary["progress"] = progress_value
        normalized_summary["progress_percent"] = progress_value
        return normalized_summary
    progress_value = int(state.get("progress") or 0)
    normalized_summary["progress"] = progress_value
    normalized_summary["progress_percent"] = progress_value
    if eta_seconds is not None:
        normalized_summary["eta_seconds"] = int(eta_seconds)
    if eta_label is not None:
        normalized_summary["eta_label"] = str(eta_label or "").strip()
    return normalized_summary


def property_search_run_apply_event(
    *,
    state: dict[str, object],
    step: str,
    message: str,
    status: str,
    steps_delta: int,
    summary_updates: dict[str, object] | None,
    force_status: str,
    stages_total_override: int | None,
    terminal_statuses: set[str] | frozenset[str],
    default_stages_total: int,
    now_iso: Callable[[], str],
    compact_text: Callable[..., str],
    progress_projection: Callable[..., tuple[int, int, str]],
    sync_summary: Callable[..., dict[str, object]],
) -> dict[str, object]:
    mutated_state = dict(state)
    normalized_status = str(force_status or status or "in_progress").strip().lower() or "in_progress"
    normalized_step = compact_text(str(step), fallback="run_step")
    normalized_message = compact_text(str(message), fallback="", limit=280)
    mutated_state["status"] = normalized_status
    mutated_state["current_step"] = normalized_step
    mutated_state["message"] = normalized_message
    if stages_total_override is not None:
        mutated_state["stages_total"] = max(
            int(mutated_state.get("steps_completed") or 0) + 1,
            int(stages_total_override),
        )
    stages_total = max(1, int(mutated_state.get("stages_total") or default_stages_total))
    if normalized_status in terminal_statuses:
        mutated_state["steps_completed"] = stages_total
        mutated_state["progress"] = 100
        mutated_state["eta_seconds"] = 0
        mutated_state["eta_label"] = ""
        mutated_state["eta_seconds_smoothed"] = 0
    else:
        mutated_state["steps_completed"] = min(
            stages_total,
            max(0, int(mutated_state.get("steps_completed") or 0) + int(steps_delta)),
        )
    if summary_updates:
        summary = dict(mutated_state.get("summary") or {})
        summary.update(dict(summary_updates))
        mutated_state["summary"] = summary
    summary = dict(mutated_state.get("summary") or {})
    if normalized_status not in terminal_statuses:
        normalized_progress, eta_seconds, eta_label = progress_projection(
            state=mutated_state,
            step=step,
            status=normalized_status,
            summary=summary,
            stages_total=stages_total,
            steps_completed=int(mutated_state.get("steps_completed") or 0),
        )
        mutated_state["progress"] = normalized_progress
        mutated_state["eta_seconds"] = eta_seconds
        mutated_state["eta_label"] = eta_label
        mutated_state["eta_seconds_smoothed"] = eta_seconds
        summary = sync_summary(
            state=dict(mutated_state),
            summary=summary,
            terminal_statuses=terminal_statuses,
            eta_seconds=eta_seconds,
            eta_label=eta_label,
        )
    else:
        summary = sync_summary(
            state=dict(mutated_state),
            summary=summary,
            terminal_statuses=terminal_statuses,
        )
    mutated_state["summary"] = summary
    events = list(mutated_state.get("events") or [])
    events.append(
        {
            "at": now_iso(),
            "step": normalized_step,
            "message": compact_text(str(message), fallback="", limit=320),
            "status": normalized_status,
        }
    )
    if len(events) > 240:
        events = events[-240:]
    mutated_state["events"] = events
    mutated_state["updated_at"] = now_iso()
    return mutated_state


def property_search_run_progress_projection(
    *,
    state: dict[str, object],
    step: str,
    status: str,
    summary: dict[str, object],
    stages_total: int,
    steps_completed: int,
    terminal_statuses: set[str] | frozenset[str],
    parse_utcish: Callable[[str], datetime | None],
) -> tuple[int, int, str]:
    normalized_status = str(status or "").strip().lower()
    if normalized_status in terminal_statuses:
        return 100, 0, ""

    previous_progress = max(0, min(99, int(state.get("progress") or 0)))
    raw_progress = int((max(0, steps_completed) * 100) / max(1, stages_total))
    sources_total = max(0, int(summary.get("sources_total") or 0))
    source_rows = list(summary.get("sources") or [])
    source_completed = len([row for row in source_rows if isinstance(row, dict)])
    summary["sources_completed"] = source_completed
    normalized_step = str(step or "").strip().lower()

    bootstrap_without_output = (
        max(0, int(summary.get("listing_total") or 0)) <= 0
        and max(0, int(summary.get("review_created_total") or 0)) <= 0
        and max(0, int(summary.get("review_existing_total") or 0)) <= 0
    )
    if bootstrap_without_output and normalized_step in {"queued", "starting", "sources_resolved", "source_started", "source_fetching"}:
        if sources_total <= 0 or source_completed <= 0:
            return 0, 0, ""

    progress_candidate = raw_progress
    eta_seconds = 0
    eta_label = ""
    if sources_total > 0:
        # Do not show fabricated early progress before the run has produced any
        # concrete source summary row or listing/review work.
        if (
            source_completed <= 0
            and bootstrap_without_output
            and normalized_step in {"queued", "starting", "sources_resolved", "source_started", "source_fetching"}
        ):
            return 0, 0, ""
        phase_fraction = property_search_run_step_source_fraction(step)
        if phase_fraction >= 1.0:
            effective_completed_sources = float(min(sources_total, source_completed))
        else:
            effective_completed_sources = min(float(sources_total), float(source_completed) + phase_fraction)
        progress_candidate = int(round(3.0 + (effective_completed_sources / float(sources_total)) * 93.0))

        created_at = parse_utcish(str(state.get("created_at") or ""))
        if created_at is not None and effective_completed_sources > 0.0:
            elapsed_seconds = max(1.0, (datetime.now(timezone.utc) - created_at).total_seconds())
            remaining_sources = max(0.0, float(sources_total) - effective_completed_sources)
            observed_eta_seconds = min(8 * 60 * 60, max(0.0, (elapsed_seconds / effective_completed_sources) * remaining_sources))
            previous_eta_seconds = float(state.get("eta_seconds_smoothed") or 0.0)
            eta_seconds = int(
                round(
                    observed_eta_seconds
                    if previous_eta_seconds <= 0.0
                    else min(8 * 60 * 60, (previous_eta_seconds * 0.55) + (observed_eta_seconds * 0.45))
                )
            )
            eta_label = property_search_eta_label(float(eta_seconds))

    normalized_progress = max(previous_progress, min(99, progress_candidate))
    return normalized_progress, eta_seconds, eta_label


def new_property_search_run_record(
    *,
    run_id: str,
    principal_id: str,
    selected_platforms: tuple[str, ...],
    property_search_preferences: dict[str, object] | None,
    force_refresh: bool,
    now_iso: Callable[[], str],
    default_summary: Callable[[dict[str, object] | None], dict[str, object]],
    stages_total: int,
) -> dict[str, object]:
    requested_preferences = dict(property_search_preferences or {})
    if selected_platforms:
        requested_preferences["selected_platforms"] = list(selected_platforms)
    requested_preferences["force_refresh"] = bool(force_refresh)
    now_value = now_iso()
    return {
        "run_id": str(run_id or "").strip(),
        "principal_id": str(principal_id or "").strip(),
        "created_at": now_value,
        "updated_at": now_value,
        "status": "queued",
        "status_url": f"/app/api/signals/property/search/run/{str(run_id or '').strip()}",
        "selected_platforms": list(selected_platforms),
        "progress": 0,
        "current_step": "queued",
        "message": "Queued for execution.",
        "stages_total": stages_total,
        "steps_completed": 0,
        "summary": default_summary(requested_preferences),
        "events": [
            {
                "at": now_value,
                "step": "queued",
                "message": "Search run queued",
                "status": "queued",
            }
        ],
        "property_search_preferences": requested_preferences,
        "force_refresh": bool(force_refresh),
        "generated_at": now_value,
        "eta_seconds": 0,
        "eta_label": "",
        "eta_seconds_smoothed": 0,
        "control_state": "active",
        "pause_capable": True,
        "pause_reason": "",
    }
