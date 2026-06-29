from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


_PROPERTY_SEARCH_RUN_TTL_SECONDS = 90 * 24 * 60 * 60
_PROPERTY_SEARCH_RUN_SCHEMA_LOCK = threading.Lock()
_PROPERTY_SEARCH_RUN_SCHEMA_READY = False

_PROPERTY_SOURCE_LISTING_CACHE_LOCK = threading.Lock()
_PROPERTY_SOURCE_LISTING_CACHE: dict[str, dict[str, object]] = {}
_PROPERTY_SOURCE_LISTING_CACHE_VERSION = "property_source_listing_cache_v1"
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_VERSION = 1
_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES = 256
_PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
_PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_LOCK = threading.Lock()
_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY = False

_PROPERTY_SEARCH_RUN_COMPACT_TOP_LEVEL_KEYS = (
    "run_id",
    "principal_id",
    "status",
    "progress",
    "stage",
    "stage_label",
    "current_step",
    "message",
    "created_at",
    "updated_at",
    "generated_at",
    "repair_parent_run_id",
    "repair_parent_run_ids",
    "active_search_agent_id",
    "selected_platforms",
    "property_search_preferences",
    "preferences",
)

_PROPERTY_SEARCH_RUN_COMPACT_PREFERENCE_DROP_KEYS = (
    "raw_preferences",
    "saved_shortlist_candidates",
    "search_agents",
    "preference_bundle",
)

_PROPERTY_SEARCH_RUN_COMPACT_SUMMARY_KEYS = (
    "status",
    "message",
    "progress",
    "stage",
    "stage_label",
    "current_plan_key",
    "current_plan_label",
    "research_depth",
    "max_results_per_source",
    "provider_total",
    "provider_group_total",
    "provider_workers",
    "sources_total",
    "source_total",
    "source_variant_total",
    "sources_completed",
    "sources_failed",
    "source_variant_completed_total",
    "source_variant_failed_total",
    "listing_total",
    "raw_listing_total",
    "scanned_listing_total",
    "reviewed_listing_total",
    "ranked_total",
    "ranked_candidate_total",
    "results_total",
    "survivor_total",
    "filtered_total",
    "held_back_total",
    "filtered_out_total",
    "filtered_area_total",
    "filtered_location_total",
    "filtered_floorplan_total",
    "filtered_property_type_total",
    "filtered_availability_total",
    "filtered_generic_page_total",
    "filtered_listing_mode_total",
    "location_mismatch_total",
    "min_score",
    "score_demoted_total",
    "eta_label",
    "eta_confidence_label",
    "started_at",
    "completed_at",
    "updated_at",
    "ranked_candidates",
    "results",
    "top_candidates",
    "filtered_breakdown",
    "relaxation_suggestions",
    "repair_status",
    "repair_status_label",
    "repair_step_label",
    "repair_outcome_summary",
    "repair_attempt_count",
    "repair_replacement_run_id",
    "repair_replacement_status_url",
    "repair_resolved_total",
    "repair_receipts",
    "provider_repair_task_opened_total",
    "provider_repair_task_existing_total",
    "provider_repair_tasks",
    "can_auto_repair",
    "repair_parent_run_id",
    "repair_parent_run_ids",
)

_PROPERTY_SEARCH_RUN_COMPACT_SOURCE_KEYS = (
    "source_url",
    "source_label",
    "source_scope_label",
    "platform",
    "provider_family",
    "provider_trust_tier",
    "source_access_level",
    "verification_required",
    "provider_filter_pushdown",
    "provider_cache",
    "listing_total",
    "reviewed_listing_total",
    "raw_listing_total",
    "scanned_listing_total",
    "review_created_total",
    "review_existing_total",
    "high_fit_total",
    "filtered_property_type_total",
    "filtered_area_total",
    "filtered_availability_total",
    "filtered_floorplan_total",
    "filtered_generic_page_total",
    "filtered_listing_mode_total",
    "filtered_low_fit_total",
    "score_demoted_total",
    "floorplan_recovered_total",
    "provider_repair_task_opened_total",
    "provider_repair_task_existing_total",
    "provider_repair_tasks",
    "top_fit_score",
    "status",
    "state",
    "progress",
    "error",
    "timing_ms",
    "filter_near_miss_total",
    "filter_near_miss_notified_total",
    "filter_near_misses",
    "location_mismatch_candidate_total",
    "preview_prepared_total",
)

_PROPERTY_SEARCH_RUN_COMPACT_PROVIDER_CACHE_KEYS = (
    "status",
    "cache_key",
)

_PROPERTY_SEARCH_RUN_COMPACT_PROVIDER_REPAIR_TASK_KEYS = (
    "status",
    "filter_key",
    "human_task_id",
    "queue_item_ref",
    "resolution",
    "reason",
    "repair_owner",
    "repair_workflow",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _property_search_run_database_url() -> str:
    return str(os.environ.get("DATABASE_URL") or "").strip()


def _property_search_run_connect():  # type: ignore[no-untyped-def]
    database_url = _property_search_run_database_url()
    if not database_url:
        raise RuntimeError("database_url_missing")
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _quote_pg_identifier(value: str) -> str:
    return '"' + str(value or "").replace('"', '""') + '"'


def _property_search_run_canonicalize_record(record: dict[str, object]) -> dict[str, object]:
    payload = dict(record or {})
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    if not summary:
        return payload

    def _coerce_non_negative_int(value: object, *, default: int = 0) -> int:
        try:
            return max(0, int(float(str(value or "").strip())))
        except Exception:
            return default

    blocked_statuses = {
        "dismissed",
        "filtered",
        "filtered_out",
        "hard_filtered",
        "maybe_false",
        "maybe_false_positive",
        "false_positive",
        "not_a_listing",
        "repair_only",
        "queued_for_repair",
    }
    hard_filter_reasons = {
        "area_mismatch",
        "availability_mismatch",
        "generic_listing_page",
        "listing_mode_mismatch",
        "location_mismatch",
        "location_scope",
        "outside_selected_area",
        "property_location_conflicts_with_active_search",
        "property_missing_concrete_location",
        "property_type_mismatch",
        "transaction_mismatch",
        "wrong_listing_mode",
        "wrong_property_type",
    }

    def _candidate_is_rankable(candidate: dict[str, object]) -> bool:
        for field in ("status", "review_status", "candidate_status", "filter_status", "repair_status"):
            if str(candidate.get(field) or "").strip().lower() in blocked_statuses:
                return False
        for flag in (
            "maybe_false",
            "maybe_false_positive",
            "false_positive",
            "flagged_for_repair",
            "repair_only",
            "filtered_out",
            "hard_filtered",
            "not_a_listing",
        ):
            value = candidate.get(flag)
            if isinstance(value, bool) and value:
                return False
            if str(value or "").strip().lower() in {"1", "true", "yes", "on"}:
                return False
        if str(candidate.get("hard_filter_reason") or "").strip():
            return False
        filter_reason = str(candidate.get("filter_reason") or "").strip().lower()
        if filter_reason in hard_filter_reasons:
            return False
        return True

    def _candidate_identity(candidate: dict[str, object], source_label: str) -> str:
        explicit_ref = str(candidate.get("candidate_ref") or candidate.get("research_candidate_ref") or "").strip()
        if explicit_ref:
            return explicit_ref
        property_url = urllib.parse.urldefrag(str(candidate.get("property_url") or "").strip())[0]
        if property_url:
            return property_url
        review_url = str(candidate.get("review_url") or "").strip()
        if review_url:
            return review_url
        title = str(candidate.get("title") or "").strip()
        return "|".join(part for part in (source_label, title) if part).strip()

    def _merge_candidate_rows(current: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
        merged = dict(current)
        for key, value in incoming.items():
            if key == "property_facts":
                current_facts = dict(merged.get("property_facts") or {}) if isinstance(merged.get("property_facts"), dict) else {}
                incoming_facts = dict(value or {}) if isinstance(value, dict) else {}
                if incoming_facts:
                    current_facts.update(incoming_facts)
                    merged["property_facts"] = current_facts
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    sources = [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]
    ranked_candidates = [
        dict(row)
        for row in list(summary.get("ranked_candidates") or [])
        if isinstance(row, dict) and _candidate_is_rankable(row)
    ]

    source_ranked_candidates: list[dict[str, object]] = []
    if sources:
        deduped_source_candidates: dict[str, dict[str, object]] = {}
        source_candidate_order: list[str] = []
        for source in sources:
            source_label = str(source.get("source_label") or source.get("label") or "").strip()
            candidate_rows = [
                dict(row)
                for row in list(source.get("research_candidates") or source.get("top_candidates") or [])
                if isinstance(row, dict)
            ]
            candidate_total = 0
            for candidate in candidate_rows:
                if not _candidate_is_rankable(candidate):
                    continue
                candidate.setdefault("source_label", source_label)
                identity = _candidate_identity(candidate, source_label)
                if not identity:
                    continue
                if identity in deduped_source_candidates:
                    deduped_source_candidates[identity] = _merge_candidate_rows(deduped_source_candidates[identity], candidate)
                else:
                    deduped_source_candidates[identity] = dict(candidate)
                    source_candidate_order.append(identity)
                candidate_total += 1
            if candidate_total > 0:
                source["ranked_total"] = max(
                    _coerce_non_negative_int(source.get("ranked_total")),
                    _coerce_non_negative_int(source.get("listing_total")),
                    candidate_total,
                )
                source["listing_total"] = max(
                    _coerce_non_negative_int(source.get("listing_total")),
                    _coerce_non_negative_int(source.get("ranked_total")),
                    candidate_total,
                )
                source["scanned_listing_total"] = max(
                    _coerce_non_negative_int(source.get("scanned_listing_total")),
                    _coerce_non_negative_int(source.get("reviewed_listing_total")),
                    _coerce_non_negative_int(source.get("listing_total")),
                    candidate_total,
                )
                source["reviewed_listing_total"] = max(
                    _coerce_non_negative_int(source.get("reviewed_listing_total")),
                    _coerce_non_negative_int(source.get("scanned_listing_total")),
                    _coerce_non_negative_int(source.get("listing_total")),
                    candidate_total,
                )
        source_ranked_candidates = [deduped_source_candidates[key] for key in source_candidate_order if key in deduped_source_candidates]

    if not ranked_candidates and source_ranked_candidates:
        ranked_candidates = [dict(row) for row in source_ranked_candidates]
        summary["ranked_candidates"] = ranked_candidates
    elif not ranked_candidates and not source_ranked_candidates and sources:
        visible_review_total = 0
        for source in sources:
            review_visible_total = (
                _coerce_non_negative_int(source.get("review_created_total"))
                + _coerce_non_negative_int(source.get("review_existing_total"))
            )
            visible_review_total += review_visible_total
            source["listing_total"] = review_visible_total
            source["ranked_total"] = review_visible_total
            if review_visible_total <= 0 and "top_fit_score" in source:
                source["top_fit_score"] = 0.0
        for key in (
            "listing_total",
            "ranked_total",
            "ranked_candidate_total",
            "results_total",
            "survivor_total",
        ):
            summary[key] = visible_review_total

    raw_listing_total = sum(_coerce_non_negative_int(source.get("raw_listing_total")) for source in sources)
    scanned_listing_total = sum(
        max(
            _coerce_non_negative_int(source.get("scanned_listing_total")),
            _coerce_non_negative_int(source.get("reviewed_listing_total")),
            _coerce_non_negative_int(source.get("listing_total")),
        )
        for source in sources
    )
    score_demoted_total = sum(_coerce_non_negative_int(source.get("score_demoted_total")) for source in sources)
    if raw_listing_total > 0:
        summary["raw_listing_total"] = max(_coerce_non_negative_int(summary.get("raw_listing_total")), raw_listing_total)
    if scanned_listing_total > 0:
        summary["scanned_listing_total"] = max(
            _coerce_non_negative_int(summary.get("scanned_listing_total")),
            _coerce_non_negative_int(summary.get("reviewed_listing_total")),
            scanned_listing_total,
        )
        summary["reviewed_listing_total"] = max(
            _coerce_non_negative_int(summary.get("reviewed_listing_total")),
            _coerce_non_negative_int(summary.get("scanned_listing_total")),
            scanned_listing_total,
        )
    if score_demoted_total > 0:
        summary["score_demoted_total"] = max(_coerce_non_negative_int(summary.get("score_demoted_total")), score_demoted_total)
    elif _coerce_non_negative_int(summary.get("filtered_low_fit_total")) > 0:
        summary["score_demoted_total"] = max(
            _coerce_non_negative_int(summary.get("score_demoted_total")),
            _coerce_non_negative_int(summary.get("filtered_low_fit_total")),
        )

    ranked_candidate_total = len(ranked_candidates)
    if ranked_candidate_total > 0:
        for key in (
            "ranked_total",
            "ranked_candidate_total",
            "results_total",
            "survivor_total",
            "listing_total",
            "scanned_listing_total",
            "reviewed_listing_total",
        ):
            summary[key] = max(_coerce_non_negative_int(summary.get(key)), ranked_candidate_total)

    held_back_total = _coerce_non_negative_int(summary.get("held_back_total"))
    filtered_total = _coerce_non_negative_int(summary.get("filtered_total"))
    if held_back_total > 0 and filtered_total <= 0:
        summary["filtered_total"] = held_back_total
    elif filtered_total > 0 and held_back_total <= 0:
        summary["held_back_total"] = filtered_total

    if sources:
        summary["sources"] = sources
    payload["summary"] = summary
    if not str(payload.get("status") or "").strip() and str(summary.get("status") or "").strip():
        payload["status"] = str(summary.get("status") or "").strip()
    return payload


def _compact_property_search_run_record(record: dict[str, object]) -> dict[str, object]:
    def _compact_provider_cache_row(value: object) -> dict[str, object]:
        payload = dict(value or {}) if isinstance(value, dict) else {}
        return {
            key: payload[key]
            for key in _PROPERTY_SEARCH_RUN_COMPACT_PROVIDER_CACHE_KEYS
            if key in payload
        }

    def _compact_provider_repair_task_row(value: object) -> dict[str, object]:
        payload = dict(value or {}) if isinstance(value, dict) else {}
        return {
            key: payload[key]
            for key in _PROPERTY_SEARCH_RUN_COMPACT_PROVIDER_REPAIR_TASK_KEYS
            if key in payload
        }

    def _compact_source_row(value: object) -> dict[str, object]:
        payload = dict(value or {}) if isinstance(value, dict) else {}
        compact_row = {
            key: payload[key]
            for key in _PROPERTY_SEARCH_RUN_COMPACT_SOURCE_KEYS
            if key in payload
        }
        if isinstance(compact_row.get("provider_cache"), dict):
            compact_row["provider_cache"] = _compact_provider_cache_row(compact_row.get("provider_cache"))
        if isinstance(compact_row.get("provider_repair_tasks"), list):
            compact_row["provider_repair_tasks"] = [
                _compact_provider_repair_task_row(task)
                for task in compact_row.get("provider_repair_tasks") or []
                if isinstance(task, dict)
            ]
        if isinstance(compact_row.get("filter_near_misses"), list):
            compact_row["filter_near_misses"] = [
                {
                    key: item[key]
                    for key in (
                        "property_url",
                        "title",
                        "failed_filter_key",
                        "failed_filter_label",
                        "requested_distance_m",
                        "observed_distance_m",
                        "observed_place_name",
                        "prefilter_score",
                    )
                    if isinstance(item, dict) and key in item
                }
                for item in compact_row.get("filter_near_misses") or []
                if isinstance(item, dict)
            ]
        return compact_row

    payload = _property_search_run_canonicalize_record(dict(record or {}))
    compact = {
        key: payload[key]
        for key in _PROPERTY_SEARCH_RUN_COMPACT_TOP_LEVEL_KEYS
        if key in payload
    }
    for preference_key in ("property_search_preferences", "preferences"):
        if isinstance(compact.get(preference_key), dict):
            preferences = dict(compact[preference_key])
            for drop_key in _PROPERTY_SEARCH_RUN_COMPACT_PREFERENCE_DROP_KEYS:
                preferences.pop(drop_key, None)
            compact[preference_key] = preferences
    summary = dict(payload.get("summary") or {}) if isinstance(payload.get("summary"), dict) else {}
    if summary:
        compact_summary = {
            key: summary[key]
            for key in _PROPERTY_SEARCH_RUN_COMPACT_SUMMARY_KEYS
            if key in summary
        }
        if isinstance(summary.get("sources"), list):
            compact_summary["sources"] = [
                _compact_source_row(row)
                for row in summary.get("sources") or []
                if isinstance(row, dict)
            ]
        if compact_summary:
            compact["summary"] = compact_summary
    if "run_id" not in compact and payload.get("run_id"):
        compact["run_id"] = payload.get("run_id")
    if "principal_id" not in compact and payload.get("principal_id"):
        compact["principal_id"] = payload.get("principal_id")
    if "status" not in compact and summary.get("status"):
        compact["status"] = summary.get("status")
    return compact


def _compact_property_search_run_record_with_row_timestamps(
    payload: object,
    *,
    created_at: object = "",
    updated_at: object = "",
) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    compact = _property_search_run_canonicalize_record(dict(payload or {}))

    def _timestamp_text(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "").strip()

    row_created_at = _timestamp_text(created_at)
    row_updated_at = _timestamp_text(updated_at)
    if not str(compact.get("created_at") or "").strip() and row_created_at:
        compact["created_at"] = row_created_at
    if not str(compact.get("updated_at") or "").strip() and row_updated_at:
        compact["updated_at"] = row_updated_at
    summary = compact.get("summary")
    if isinstance(summary, dict):
        compact_summary = dict(summary)
        if not str(compact_summary.get("updated_at") or "").strip() and row_updated_at:
            compact_summary["updated_at"] = row_updated_at
        compact["summary"] = compact_summary
    return compact


def _compact_pruned_property_search_run_record(
    record: dict[str, object],
    *,
    pruned_at: str | None = None,
) -> dict[str, object]:
    compact = _compact_property_search_run_record(record)
    compact["payload_retention_status"] = "compact_only"
    compact["payload_pruned_at"] = str(pruned_at or _now_iso()).strip() or _now_iso()
    return compact


def _compact_property_search_run_json_sql() -> str:
    preference_drop_sql = " ".join(
        f"- '{key}'"
        for key in _PROPERTY_SEARCH_RUN_COMPACT_PREFERENCE_DROP_KEYS
    )
    top_objects = " ||\n                            ".join(
        (
            f"jsonb_build_object('{key}', (payload_json -> '{key}') {preference_drop_sql})"
            if key in {"property_search_preferences", "preferences"}
            else f"jsonb_build_object('{key}', payload_json -> '{key}')"
        )
        for key in _PROPERTY_SEARCH_RUN_COMPACT_TOP_LEVEL_KEYS
    )
    summary_objects = " ||\n                                    ".join(
        f"jsonb_build_object('{key}', payload_json #> '{{summary,{key}}}')"
        for key in _PROPERTY_SEARCH_RUN_COMPACT_SUMMARY_KEYS
    )
    return f"""
                    jsonb_strip_nulls(
                        (
                            {top_objects}
                        )
                        ||
                        jsonb_build_object(
                            'summary',
                            jsonb_strip_nulls(
                                {summary_objects}
                            )
                        )
                    )
                """


def _property_search_run_primary_key_columns(cur) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS key_columns(attnum, ordinal) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_columns.attnum
        WHERE n.nspname = current_schema()
          AND t.relname = 'property_search_runs'
          AND i.indisprimary
        ORDER BY key_columns.ordinal
        """
    )
    return tuple(str(row[0]) for row in cur.fetchall())


def _property_search_run_table_exists(cur) -> bool:  # type: ignore[no-untyped-def]
    cur.execute("SELECT to_regclass('property_search_runs')")
    row = cur.fetchone()
    return bool(row and row[0])


def _property_search_run_column_names(cur) -> set[str]:  # type: ignore[no-untyped-def]
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'property_search_runs'
        """
    )
    return {str(row[0]) for row in cur.fetchall() if row and row[0]}


def _property_search_run_index_exists(cur, index_name: str) -> bool:  # type: ignore[no-untyped-def]
    cur.execute(
        """
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relkind = 'i'
          AND c.relname = %s
        LIMIT 1
        """,
        (str(index_name or "").strip(),),
    )
    return bool(cur.fetchone())


def _ensure_property_search_run_primary_key(cur) -> None:  # type: ignore[no-untyped-def]
    desired_columns = ("principal_id", "run_id")
    if _property_search_run_primary_key_columns(cur) == desired_columns:
        return
    cur.execute(
        """
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'property_search_runs'::regclass
          AND contype = 'p'
        """
    )
    row = cur.fetchone()
    if row and row[0]:
        cur.execute(f"ALTER TABLE property_search_runs DROP CONSTRAINT {_quote_pg_identifier(str(row[0]))}")
    cur.execute(
        """
        DELETE FROM property_search_runs a
        USING property_search_runs b
        WHERE a.ctid < b.ctid
          AND a.principal_id = b.principal_id
          AND a.run_id = b.run_id
        """
    )
    cur.execute("ALTER TABLE property_search_runs ALTER COLUMN principal_id SET NOT NULL")
    cur.execute("ALTER TABLE property_search_runs ALTER COLUMN run_id SET NOT NULL")
    cur.execute("ALTER TABLE property_search_runs ADD PRIMARY KEY (principal_id, run_id)")


def _ensure_property_search_run_schema() -> None:
    global _PROPERTY_SEARCH_RUN_SCHEMA_READY
    if _PROPERTY_SEARCH_RUN_SCHEMA_READY or not _property_search_run_database_url():
        return
    with _PROPERTY_SEARCH_RUN_SCHEMA_LOCK:
        if _PROPERTY_SEARCH_RUN_SCHEMA_READY:
            return
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                table_existed = _property_search_run_table_exists(cur)
                existing_columns = _property_search_run_column_names(cur) if table_existed else set()
                needs_compact_backfill = (
                    table_existed
                    and (
                        "status" not in existing_columns
                        or "compact_json" not in existing_columns
                    )
                )
                if not table_existed:
                    cur.execute(
                        """
                        CREATE TABLE property_search_runs (
                            principal_id TEXT NOT NULL,
                            run_id TEXT NOT NULL,
                            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            status TEXT,
                            compact_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL,
                            PRIMARY KEY (principal_id, run_id)
                        )
                        """
                    )
                    existing_columns = {
                        "principal_id",
                        "run_id",
                        "payload_json",
                        "status",
                        "compact_json",
                        "created_at",
                        "updated_at",
                    }
                if "status" not in existing_columns:
                    cur.execute("ALTER TABLE property_search_runs ADD COLUMN status TEXT")
                    existing_columns.add("status")
                if "compact_json" not in existing_columns:
                    cur.execute("ALTER TABLE property_search_runs ADD COLUMN compact_json JSONB NOT NULL DEFAULT '{}'::jsonb")
                    existing_columns.add("compact_json")
                _ensure_property_search_run_primary_key(cur)
                if not _property_search_run_index_exists(cur, "idx_property_search_runs_updated"):
                    cur.execute(
                        """
                        CREATE INDEX idx_property_search_runs_updated
                        ON property_search_runs(updated_at DESC)
                        """
                    )
                if not _property_search_run_index_exists(cur, "idx_property_search_runs_principal_updated"):
                    cur.execute(
                        """
                        CREATE INDEX idx_property_search_runs_principal_updated
                        ON property_search_runs(principal_id, updated_at DESC)
                        """
                    )
                if needs_compact_backfill:
                    cur.execute(
                        f"""
                        UPDATE property_search_runs
                        SET status = COALESCE(status, payload_json->>'status', payload_json#>>'{{summary,status}}'),
                            compact_json = {_compact_property_search_run_json_sql()}
                        WHERE compact_json = '{{}}'::jsonb
                           OR compact_json IS NULL
                           OR status IS NULL
                        """
                    )
        _PROPERTY_SEARCH_RUN_SCHEMA_READY = True


def _store_property_search_run_record(record: dict[str, object]) -> None:
    if not _property_search_run_database_url():
        return
    _ensure_property_search_run_schema()
    normalized_record = _property_search_run_canonicalize_record(dict(record or {}))
    run_id = str(normalized_record.get("run_id") or "").strip()
    principal_id = str(normalized_record.get("principal_id") or "").strip()
    if not run_id or not principal_id:
        return
    from psycopg.types.json import Json

    compact_record = _compact_property_search_run_record(normalized_record)
    status_value = str(compact_record.get("status") or "").strip() or None
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO property_search_runs (run_id, principal_id, payload_json, status, compact_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (principal_id, run_id) DO UPDATE
                SET payload_json = EXCLUDED.payload_json,
                    status = EXCLUDED.status,
                    compact_json = EXCLUDED.compact_json,
                    updated_at = EXCLUDED.updated_at
                WHERE property_search_runs.payload_json IS DISTINCT FROM EXCLUDED.payload_json
                   OR property_search_runs.status IS DISTINCT FROM EXCLUDED.status
                   OR property_search_runs.compact_json IS DISTINCT FROM EXCLUDED.compact_json
                """,
                (
                    run_id,
                    principal_id,
                    Json(normalized_record),
                    status_value,
                    Json(compact_record),
                    str(normalized_record.get("created_at") or _now_iso()).strip() or _now_iso(),
                    str(normalized_record.get("updated_at") or _now_iso()).strip() or _now_iso(),
                ),
            )


def _load_property_search_run_record(*, run_id: str, principal_id: str) -> dict[str, object] | None:
    if not _property_search_run_database_url():
        return None
    _ensure_property_search_run_schema()
    normalized_run_id = str(run_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_run_id or not normalized_principal_id:
        return None
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
                (normalized_run_id, normalized_principal_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return (
        _property_search_run_canonicalize_record(dict(row[0] or {}))
        if isinstance(row[0], dict)
        else None
    )


def _load_property_search_run_compact_record(*, run_id: str, principal_id: str) -> dict[str, object] | None:
    if not _property_search_run_database_url():
        return None
    _ensure_property_search_run_schema()
    normalized_run_id = str(run_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_run_id or not normalized_principal_id:
        return None
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(
                    NULLIF(compact_json, '{}'::jsonb),
                    jsonb_build_object(
                        'run_id', to_jsonb(run_id),
                        'principal_id', to_jsonb(principal_id),
                        'status', to_jsonb(status),
                        'created_at', to_jsonb(created_at),
                        'updated_at', to_jsonb(updated_at)
                    )
                ),
                created_at,
                updated_at
                FROM property_search_runs
                WHERE run_id = %s AND principal_id = %s
                """,
                (normalized_run_id, normalized_principal_id),
            )
            row = cur.fetchone()
    if not row:
        return None
    return _compact_property_search_run_record_with_row_timestamps(
        row[0],
        created_at=row[1] if len(row) > 1 else "",
        updated_at=row[2] if len(row) > 2 else "",
    )


def _list_property_search_run_records(
    *,
    limit: int = 20,
    statuses: tuple[str, ...] = (),
    principal_id: str = "",
    admin: bool = False,
    lightweight: bool = False,
    registry: dict[str, dict[str, object]] | None = None,
) -> tuple[dict[str, object], ...]:
    normalized_limit = max(int(limit or 0), 1)
    normalized_statuses = tuple(
        sorted({str(value or "").strip().lower() for value in statuses if str(value or "").strip()})
    )
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id and not admin:
        return ()
    if not _property_search_run_database_url():
        rows = [dict(value) for value in (registry or {}).values() if isinstance(value, dict)]
        if normalized_principal_id:
            rows = [row for row in rows if str(row.get("principal_id") or "").strip() == normalized_principal_id]
        if normalized_statuses:
            rows = [row for row in rows if str(row.get("status") or "").strip().lower() in normalized_statuses]
        rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        if lightweight:
            rows = [_compact_property_search_run_record(row) for row in rows]
        return tuple(rows[:normalized_limit])
    _ensure_property_search_run_schema()
    query = (
        """
        SELECT COALESCE(
            NULLIF(compact_json, '{}'::jsonb),
            jsonb_build_object(
                'run_id', to_jsonb(run_id),
                'principal_id', to_jsonb(principal_id),
                'status', to_jsonb(status),
                'created_at', to_jsonb(created_at),
                'updated_at', to_jsonb(updated_at)
            )
        ),
        created_at,
        updated_at
        FROM property_search_runs
        """
        if lightweight
        else "SELECT payload_json FROM property_search_runs"
    )
    params: list[object] = []
    where_clauses: list[str] = []
    if normalized_principal_id:
        where_clauses.append("principal_id = %s")
        params.append(normalized_principal_id)
    if normalized_statuses:
        where_clauses.append("status = ANY(%s)" if lightweight else "(payload_json->>'status') = ANY(%s)")
        params.append(list(normalized_statuses))
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY updated_at DESC LIMIT %s"
    params.append(normalized_limit)
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    results: list[dict[str, object]] = []
    for row in rows:
        payload = row[0] if row else None
        compact = _compact_property_search_run_record_with_row_timestamps(
            payload,
            created_at=row[1] if len(row) > 1 else "",
            updated_at=row[2] if len(row) > 2 else "",
        )
        if compact is not None:
            results.append(compact)
    return tuple(results)


def _prune_property_search_run_records() -> None:
    if not _property_search_run_database_url():
        return
    retention_seconds = _property_search_run_retention_seconds()
    if retention_seconds <= 0:
        return
    _ensure_property_search_run_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)).isoformat()
    pruned_at = _now_iso()
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH stale_runs AS (
                    SELECT
                        principal_id,
                        run_id,
                        COALESCE(NULLIF(compact_json, '{{}}'::jsonb), {_compact_property_search_run_json_sql()}) AS compacted
                    FROM property_search_runs
                    WHERE updated_at < %s
                      AND COALESCE(payload_json->>'payload_retention_status', '') <> 'compact_only'
                )
                UPDATE property_search_runs AS runs
                SET compact_json = stale_runs.compacted,
                    payload_json = stale_runs.compacted || jsonb_build_object(
                        'payload_retention_status', 'compact_only',
                        'payload_pruned_at', %s::text
                    ),
                    status = COALESCE(runs.status, stale_runs.compacted->>'status')
                FROM stale_runs
                WHERE runs.principal_id = stale_runs.principal_id
                  AND runs.run_id = stale_runs.run_id
                """,
                (cutoff, pruned_at),
            )


def _delete_property_search_run_record(
    *,
    run_id: str,
    principal_id: str,
    registry: dict[str, dict[str, object]] | None = None,
) -> bool:
    normalized_run_id = str(run_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_run_id or not normalized_principal_id:
        return False
    if not _property_search_run_database_url():
        if registry is None:
            return False
        record = registry.get(normalized_run_id)
        if str(dict(record or {}).get("principal_id") or "").strip() != normalized_principal_id:
            return False
        return registry.pop(normalized_run_id, None) is not None
    _ensure_property_search_run_schema()
    with _property_search_run_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
                (normalized_run_id, normalized_principal_id),
            )
            return bool(cur.rowcount)


def _property_search_run_retention_seconds() -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS") or "").strip()
    if not raw_value:
        return _PROPERTY_SEARCH_RUN_TTL_SECONDS
    try:
        parsed = int(raw_value)
    except Exception:
        return _PROPERTY_SEARCH_RUN_TTL_SECONDS
    return max(0, min(parsed, 10 * 365 * 24 * 60 * 60))


def property_search_run_retention_policy() -> dict[str, str]:
    retention_seconds = _property_search_run_retention_seconds()
    return {
        "property_search_run_retention_status": "enabled" if retention_seconds > 0 else "disabled",
        "property_search_run_retention_seconds": str(retention_seconds),
        "property_search_run_retention_days": str(round(retention_seconds / 86400, 2)),
        "property_search_run_retention_env": "EA_PROPERTY_SEARCH_RUN_RETENTION_SECONDS",
        "property_search_run_retention_default_seconds": str(_PROPERTY_SEARCH_RUN_TTL_SECONDS),
    }


def _property_source_listing_cache_ttl_seconds() -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS") or "").strip()
    if not raw_value:
        return 15 * 60
    try:
        parsed = int(raw_value)
    except Exception:
        return 15 * 60
    return max(0, min(parsed, 24 * 60 * 60))


def _property_source_listing_cache_stale_max_seconds() -> int:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS") or "").strip()
    if not raw_value:
        return 6 * 60 * 60
    try:
        parsed = int(raw_value)
    except Exception:
        return 6 * 60 * 60
    return max(0, min(parsed, 7 * 24 * 60 * 60))


def _property_source_listing_cache_path() -> Path | None:
    raw_value = str(os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH") or "").strip()
    if not raw_value or raw_value.lower() in {"0", "false", "no", "off", "disabled"}:
        return None
    return Path(raw_value).expanduser()


def _property_source_listing_cache_backend() -> str:
    raw_value = os.getenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND")
    storage_backend = str(os.getenv("EA_STORAGE_BACKEND") or "").strip().lower()
    configured = str(raw_value or "").strip().lower()
    if configured not in {"", "auto", "memory", "file", "postgres"}:
        configured = "auto"
    if configured in {"memory", "file", "postgres"}:
        return configured
    if raw_value is None and storage_backend == "postgres" and _property_search_run_database_url():
        return "postgres"
    if configured == "auto" and _property_search_run_database_url():
        return "postgres"
    if raw_value is None and _property_source_listing_cache_path() is not None:
        return "file"
    if _property_source_listing_cache_path() is not None:
        return "file"
    return "memory"


def _property_source_listing_cache_key(*, source_url: str, source_spec: dict[str, object] | None = None) -> str:
    spec = dict(source_spec or {})
    configured = str(spec.get("provider_cache_key") or "").strip()
    if configured:
        return configured[:240]
    pushdown = dict(spec.get("provider_filter_pushdown") or {}) if isinstance(spec.get("provider_filter_pushdown"), dict) else {}
    pushdown_key = str(pushdown.get("cache_key") or "").strip()
    if pushdown_key:
        return pushdown_key[:240]
    return ""


def _property_source_listing_cache_normalize_row(raw_key: object, raw_row: object, *, now: float | None = None) -> dict[str, object]:
    cache_key = str(raw_key or "").strip()[:240]
    if not cache_key or not isinstance(raw_row, dict):
        return {}
    try:
        stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
    except Exception:
        stored_at = 0.0
    effective_now = float(now or time.time())
    urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
    if not urls:
        return {}
    return {
        "cache_key": cache_key,
        "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
        "listing_urls": urls[:250],
        "stored_at_epoch": stored_at or effective_now,
        "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
        if isinstance(raw_row.get("provider_filter_pushdown"), dict)
        else {},
    }


def _property_source_listing_cache_row_state(
    *,
    cache_key: str,
    row: dict[str, object],
    allow_stale: bool,
    persistence: str,
) -> tuple[tuple[str, ...], dict[str, object]]:
    now = time.time()
    ttl = _property_source_listing_cache_ttl_seconds()
    stale_max = _property_source_listing_cache_stale_max_seconds()
    try:
        stored_at = float(row.get("stored_at_epoch") or 0.0)
    except Exception:
        stored_at = 0.0
    age_seconds = max(0.0, now - stored_at)
    if not allow_stale and (ttl <= 0 or age_seconds > float(ttl)):
        return (), {}
    if allow_stale and (
        ttl <= 0
        or (age_seconds > float(ttl) and stale_max <= 0)
        or (stale_max > 0 and age_seconds > float(stale_max))
    ):
        return (), {}
    urls = tuple(str(value or "").strip() for value in list(row.get("listing_urls") or []) if str(value or "").strip())
    if not urls:
        return (), {}
    state = {
        "status": "stale_fallback" if ttl > 0 and age_seconds > float(ttl) else "hit",
        "cache_key": cache_key,
        "age_seconds": round(age_seconds, 2),
        "listing_total": len(urls),
        "persistence": persistence,
        "revalidation": "candidate_preview",
    }
    return urls, state


def _property_source_listing_cache_prune_locked() -> None:
    while len(_PROPERTY_SOURCE_LISTING_CACHE) > _PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES:
        oldest_key = min(
            _PROPERTY_SOURCE_LISTING_CACHE,
            key=lambda key: float(_PROPERTY_SOURCE_LISTING_CACHE.get(key, {}).get("stored_at_epoch") or 0.0),
        )
        _PROPERTY_SOURCE_LISTING_CACHE.pop(oldest_key, None)


def _property_source_listing_cache_snapshot_locked() -> dict[str, dict[str, object]]:
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    snapshot: dict[str, dict[str, object]] = {}
    for key, row in _PROPERTY_SOURCE_LISTING_CACHE.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        try:
            stored_at = float(row.get("stored_at_epoch") or 0.0)
        except Exception:
            stored_at = 0.0
        if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
            continue
        urls = [str(value or "").strip() for value in list(row.get("listing_urls") or []) if str(value or "").strip()]
        if not urls:
            continue
        snapshot[normalized_key] = {
            "cache_key": normalized_key,
            "source_url": urllib.parse.urldefrag(str(row.get("source_url") or "").strip())[0],
            "listing_urls": urls[:250],
            "stored_at_epoch": stored_at or now,
            "provider_filter_pushdown": dict(row.get("provider_filter_pushdown") or {})
            if isinstance(row.get("provider_filter_pushdown"), dict)
            else {},
        }
    return dict(
        sorted(
            snapshot.items(),
            key=lambda item: float(item[1].get("stored_at_epoch") or 0.0),
            reverse=True,
        )[:_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES]
    )


@contextlib.contextmanager
def _property_source_listing_cache_file_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass


def _property_source_listing_cache_quarantine_corrupt_file(path: Path, *, reason: str) -> str:
    if not path.exists():
        return ""
    suffix = f"corrupt-{int(time.time())}-{uuid4().hex[:12]}"
    quarantine_path = path.with_name(f"{path.name}.{suffix}.json")
    try:
        path.replace(quarantine_path)
    except Exception:
        return ""
    return f"{quarantine_path}:{reason}"


def _ensure_property_source_listing_cache_schema() -> bool:
    global _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY
    if _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY:
        return True
    if not _property_search_run_database_url():
        return False
    with _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_LOCK:
        if _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY:
            return True
        try:
            with _property_search_run_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS property_source_listing_cache (
                            cache_key TEXT PRIMARY KEY,
                            source_url TEXT NOT NULL DEFAULT '',
                            listing_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
                            provider_filter_pushdown JSONB NOT NULL DEFAULT '{}'::jsonb,
                            stored_at_epoch DOUBLE PRECISION NOT NULL,
                            stored_at TIMESTAMPTZ NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_property_source_listing_cache_stored_at
                        ON property_source_listing_cache(stored_at_epoch DESC)
                        """
                    )
        except Exception:
            return False
        _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY = True
        return True


def _property_source_listing_cache_prune_postgres() -> None:
    if not _ensure_property_source_listing_cache_schema():
        return
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                if retention_seconds > 0:
                    cur.execute(
                        "DELETE FROM property_source_listing_cache WHERE stored_at_epoch < %s",
                        (time.time() - float(retention_seconds),),
                    )
                cur.execute(
                    """
                    DELETE FROM property_source_listing_cache
                    WHERE cache_key IN (
                        SELECT cache_key
                        FROM property_source_listing_cache
                        ORDER BY stored_at_epoch DESC
                        OFFSET %s
                    )
                    """,
                    (_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES,),
                )
    except Exception:
        return


def _property_source_listing_cache_get_postgres(cache_key: str) -> dict[str, object]:
    normalized_key = str(cache_key or "").strip()[:240]
    if not normalized_key or not _ensure_property_source_listing_cache_schema():
        return {}
    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cache_key, source_url, listing_urls, provider_filter_pushdown, stored_at_epoch
                    FROM property_source_listing_cache
                    WHERE cache_key = %s
                    """,
                    (normalized_key,),
                )
                row = cur.fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    return _property_source_listing_cache_normalize_row(
        row[0],
        {
            "source_url": row[1],
            "listing_urls": row[2],
            "provider_filter_pushdown": row[3],
            "stored_at_epoch": row[4],
        },
    )


def _property_source_listing_cache_put_postgres(row: dict[str, object]) -> bool:
    normalized = _property_source_listing_cache_normalize_row(row.get("cache_key"), row)
    if not normalized or not _ensure_property_source_listing_cache_schema():
        return False
    from psycopg.types.json import Json

    try:
        with _property_search_run_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_source_listing_cache (
                        cache_key,
                        source_url,
                        listing_urls,
                        provider_filter_pushdown,
                        stored_at_epoch,
                        stored_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (cache_key) DO UPDATE
                    SET source_url = EXCLUDED.source_url,
                        listing_urls = EXCLUDED.listing_urls,
                        provider_filter_pushdown = EXCLUDED.provider_filter_pushdown,
                        stored_at_epoch = EXCLUDED.stored_at_epoch,
                        stored_at = EXCLUDED.stored_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        normalized["cache_key"],
                        normalized["source_url"],
                        Json(list(normalized.get("listing_urls") or [])),
                        Json(dict(normalized.get("provider_filter_pushdown") or {})),
                        float(normalized.get("stored_at_epoch") or time.time()),
                    ),
                )
        _property_source_listing_cache_prune_postgres()
        return True
    except Exception:
        return False


def _property_source_listing_cache_persist_snapshot(snapshot: dict[str, dict[str, object]]) -> None:
    global _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME, _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH
    path = _property_source_listing_cache_path()
    if path is None:
        return
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    try:
        with _property_source_listing_cache_file_lock(path):
            merged_snapshot = dict(snapshot)
            try:
                existing_payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except Exception:
                _property_source_listing_cache_quarantine_corrupt_file(path, reason="persist_existing_json_invalid")
                existing_payload = {}
            existing_entries = existing_payload.get("entries") if isinstance(existing_payload, dict) else {}
            if isinstance(existing_entries, dict):
                for raw_key, raw_row in existing_entries.items():
                    cache_key = str(raw_key or "").strip()[:240]
                    if not cache_key or not isinstance(raw_row, dict):
                        continue
                    try:
                        stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
                    except Exception:
                        stored_at = 0.0
                    if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
                        continue
                    urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
                    if not urls:
                        continue
                    existing_row = dict(merged_snapshot.get(cache_key) or {})
                    try:
                        existing_stored_at = float(existing_row.get("stored_at_epoch") or 0.0)
                    except Exception:
                        existing_stored_at = 0.0
                    if existing_row and existing_stored_at >= stored_at:
                        continue
                    merged_snapshot[cache_key] = {
                        "cache_key": cache_key,
                        "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
                        "listing_urls": urls[:250],
                        "stored_at_epoch": stored_at or now,
                        "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
                        if isinstance(raw_row.get("provider_filter_pushdown"), dict)
                        else {},
                    }
            merged_snapshot = dict(
                sorted(
                    merged_snapshot.items(),
                    key=lambda item: float(item[1].get("stored_at_epoch") or 0.0),
                    reverse=True,
                )[:_PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES]
            )
            payload = {
                "version": _PROPERTY_SOURCE_LISTING_CACHE_VERSION,
                "schema_version": _PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_VERSION,
                "stored_at": _now_iso(),
                "stored_at_epoch": now,
                "entry_count": len(merged_snapshot),
                "max_entries": _PROPERTY_SOURCE_LISTING_CACHE_MAX_ENTRIES,
                "lock_strategy": "fcntl",
                "entries": merged_snapshot,
            }
            temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temp_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
                temp_path.replace(path)
                with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
                    _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = str(path)
                    try:
                        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = float(path.stat().st_mtime)
                    except Exception:
                        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        return


def _property_source_listing_cache_load() -> None:
    global _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME, _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH
    path = _property_source_listing_cache_path()
    path_text = str(path) if path is not None else ""
    try:
        path_mtime = float(path.stat().st_mtime) if path is not None and path.exists() else 0.0
    except Exception:
        path_mtime = 0.0
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        if (
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH == path_text
            and _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME == path_mtime
        ):
            return
    if path is None or path_mtime <= 0.0:
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = path_mtime
        return
    try:
        with _property_source_listing_cache_file_lock(path):
            parsed = json.loads(path.read_text(encoding="utf-8"))
            try:
                loaded_mtime = float(path.stat().st_mtime)
            except Exception:
                loaded_mtime = path_mtime
    except Exception:
        try:
            with _property_source_listing_cache_file_lock(path):
                _property_source_listing_cache_quarantine_corrupt_file(path, reason="load_json_invalid")
        except Exception:
            pass
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
        return
    entries = parsed.get("entries") if isinstance(parsed, dict) else {}
    if not isinstance(entries, dict):
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime
        return
    loaded_rows: dict[str, dict[str, object]] = {}
    now = time.time()
    retention_seconds = max(
        _property_source_listing_cache_ttl_seconds(),
        _property_source_listing_cache_stale_max_seconds(),
    )
    for raw_key, raw_row in entries.items():
        cache_key = str(raw_key or "").strip()[:240]
        if not cache_key or not isinstance(raw_row, dict):
            continue
        try:
            stored_at = float(raw_row.get("stored_at_epoch") or 0.0)
        except Exception:
            stored_at = 0.0
        if retention_seconds > 0 and stored_at > 0.0 and now - stored_at > float(retention_seconds):
            continue
        urls = [str(value or "").strip() for value in list(raw_row.get("listing_urls") or []) if str(value or "").strip()]
        if not urls:
            continue
        loaded_rows[cache_key] = {
            "cache_key": cache_key,
            "source_url": urllib.parse.urldefrag(str(raw_row.get("source_url") or "").strip())[0],
            "listing_urls": urls[:250],
            "stored_at_epoch": stored_at or now,
            "provider_filter_pushdown": dict(raw_row.get("provider_filter_pushdown") or {})
            if isinstance(raw_row.get("provider_filter_pushdown"), dict)
            else {},
        }
    if not loaded_rows:
        with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
            _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime
        return
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        for key, row in loaded_rows.items():
            existing = dict(_PROPERTY_SOURCE_LISTING_CACHE.get(key) or {})
            try:
                existing_stored_at = float(existing.get("stored_at_epoch") or 0.0)
            except Exception:
                existing_stored_at = 0.0
            if existing and existing_stored_at >= float(row.get("stored_at_epoch") or 0.0):
                continue
            _PROPERTY_SOURCE_LISTING_CACHE[key] = row
        _property_source_listing_cache_prune_locked()
        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = path_text
        _PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = loaded_mtime


def _property_source_listing_cache_get(cache_key: str, *, allow_stale: bool = False) -> tuple[tuple[str, ...], dict[str, object]]:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return (), {}
    backend = _property_source_listing_cache_backend()
    if backend == "postgres":
        postgres_row = _property_source_listing_cache_get_postgres(normalized_key)
        if postgres_row:
            with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
                _PROPERTY_SOURCE_LISTING_CACHE[normalized_key] = postgres_row
            return _property_source_listing_cache_row_state(
                cache_key=normalized_key,
                row=postgres_row,
                allow_stale=allow_stale,
                persistence="postgres",
            )
    if backend == "file":
        _property_source_listing_cache_load()
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        row = dict(_PROPERTY_SOURCE_LISTING_CACHE.get(normalized_key) or {})
    if not row:
        return (), {}
    return _property_source_listing_cache_row_state(
        cache_key=normalized_key,
        row=row,
        allow_stale=allow_stale,
        persistence=backend if backend in {"file", "memory"} else "memory",
    )


def _property_source_listing_cache_put(
    cache_key: str,
    *,
    source_url: str,
    listing_urls: tuple[str, ...],
    source_spec: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized_key = str(cache_key or "").strip()
    if not normalized_key:
        return {"status": "disabled", "cache_key": "", "listing_total": len(listing_urls)}
    urls = tuple(str(value or "").strip() for value in listing_urls if str(value or "").strip())
    spec = dict(source_spec or {})
    row = {
        "cache_key": normalized_key,
        "source_url": urllib.parse.urldefrag(str(source_url or "").strip())[0],
        "listing_urls": list(urls[:250]),
        "stored_at_epoch": time.time(),
        "provider_filter_pushdown": dict(spec.get("provider_filter_pushdown") or {})
        if isinstance(spec.get("provider_filter_pushdown"), dict)
        else {},
    }
    with _PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        _PROPERTY_SOURCE_LISTING_CACHE[normalized_key] = row
        _property_source_listing_cache_prune_locked()
        snapshot = _property_source_listing_cache_snapshot_locked()
    backend = _property_source_listing_cache_backend()
    persisted_backend = backend
    if backend == "file":
        _property_source_listing_cache_persist_snapshot(snapshot)
    elif backend == "postgres":
        persisted_backend = "postgres" if _property_source_listing_cache_put_postgres(row) else "memory"
    return {
        "status": "stored",
        "cache_key": normalized_key,
        "listing_total": len(urls),
        "persistence": persisted_backend,
        "ttl_seconds": _property_source_listing_cache_ttl_seconds(),
    }
