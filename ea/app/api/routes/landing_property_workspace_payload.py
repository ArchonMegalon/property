from __future__ import annotations

import re
import urllib.parse
import json

from app.api.routes.landing_property_saved_searches import (
    build_agent_management_rows,
    select_property_search_agent,
)
from app.api.routes.landing_property_surface_contracts import (
    PropertyDecisionWorkbenchBriefContract,
    PropertyDecisionWorkbenchContract,
    PropertyDecisionWorkbenchRunContract,
    PropertySurfacePayloadContract,
    PropertySurfaceScope,
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
    _property_candidate_is_rankable,
    _property_candidate_preview_image,
    _property_candidate_route_evidence,
    _property_candidate_display_facts,
    _property_postal_codes_from_text,
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
from app.product.property_surface_state import (
    build_property_empty_outcome_summary,
    build_property_preference_manager_snapshot,
    build_property_previous_run_summary,
    build_property_shortlist_snapshot,
    build_property_workbench_candidate_snapshot,
    effective_property_listing_mode,
    normalized_property_search_goal,
    property_mode_visibility_label,
)
from app.product.property_delivery_governance import property_delivery_governance_rows


def _property_workbench_lightweight_image_url(value: object, *, max_data_url_chars: int = 4096) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if url.lower().startswith("data:") and len(url) > max_data_url_chars:
        return ""
    return url


def _property_workbench_lightweight_orientation_preview(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    preview = dict(value)
    for key in ("image_url", "thumb_image_url", "preview_image_url"):
        cleaned = _property_workbench_lightweight_image_url(preview.get(key))
        if cleaned:
            preview[key] = cleaned
        else:
            preview.pop(key, None)
    return preview


def _property_provider_identity_key(source_spec: dict[str, object]) -> str:
    provider_source_key = str(source_spec.get("provider_source_key") or source_spec.get("source_provider_key") or "").strip()
    if provider_source_key:
        candidate = provider_source_key.split(":", 1)[0].strip().casefold()
        if candidate:
            return candidate
    for key in ("provider_key", "platform", "provider_family", "label", "source_label"):
        raw_value = str(source_spec.get(key) or "").strip()
        if key in {"label", "source_label"} and "|" in raw_value:
            raw_value = raw_value.split("|", 1)[0].strip()
        normalized = raw_value.lower()
        if normalized:
            return normalized
    return ""


def _property_provider_total(source_rows: list[dict[str, object]]) -> int:
    provider_keys: set[str] = set()
    for row in source_rows:
        key = _property_provider_identity_key(row)
        if key:
            provider_keys.add(key)
    return len(provider_keys)


def property_workspace_payload(
    section: str,
    *,
    status: dict[str, object],
    property_state: dict[str, object],
) -> dict[str, object]:
    from app.api.routes.landing_view_models import (
        _clean_property_candidate_copy,
        _csv_values,
        _normalize_property_type_values,
        _property_customer_run_summary,
        _property_candidate_ref,
        _property_preference_schema,
        _property_result_title_display,
        _property_scope_preview,
        _property_scope_preview_map_only,
        _sanitize_platform_catalog_for_client,
        app_section_payload,
        humanize,
        row_item,
        string_rows,
    )
    from app.services.property_market_catalog import (
        currency_code_for_country,
        default_timezone_for_country,
        supported_currency_codes,
    )

    surface_scope = PropertySurfaceScope.for_section(section)
    normalized_section = surface_scope.section
    wants_search_runs = surface_scope.wants_search_runs
    wants_agent_views = surface_scope.wants_agent_views
    wants_credit_digest = surface_scope.wants_credit_digest
    wants_run_views = surface_scope.wants_run_views
    wants_full_preference_manager = normalized_section == "account"
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
    billing_truth = dict(property_state.get("billing_truth") or {})
    saved_property_preferences = dict(property_state.get("preferences") or {})
    preference_bundle = dict(property_state.get("preference_bundle") or {})
    raw_preference_nodes = (
        [
            dict(row)
            for row in list(preference_bundle.get("preference_nodes") or [])
            if isinstance(row, dict)
        ]
        if preference_bundle
        else []
    )
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    google = dict(channels.get("google") or {})
    current_plan_label = str(billing_truth.get("current_plan_label") or commercial.get("current_plan_label") or "Free").strip() or "Free"
    try:
        current_platform_cap = int(
            billing_truth.get("max_platforms")
            if billing_truth.get("max_platforms") is not None
            else (commercial.get("max_platforms") if commercial.get("max_platforms") is not None else 3)
        )
    except Exception:
        current_platform_cap = 3
    search_posture_card = cards_by_eyebrow.get("search posture", {})
    market_coverage_card = cards_by_eyebrow.get("market coverage", {})
    shortlist_card = cards_by_eyebrow.get("shortlist", {})
    run_card = cards_by_eyebrow.get("run status", {})
    learning_card = cards_by_eyebrow.get("learning loop", {})
    recent_matches_card = cards_by_eyebrow.get("recent matches", {})
    shortlist_candidates = [
        dict(candidate)
        for candidate in list(property_meta.get("shortlist_candidates") or [])
        if isinstance(candidate, dict)
    ]
    if normalized_section in {"properties", "search", "shortlist", "agents", "account", "settings", "billing"}:
        trimmed_meta = dict(property_meta)
        if normalized_section in {"properties", "search", "shortlist", "account", "settings", "billing"}:
            trimmed_meta.pop("search_agent", None)
            trimmed_meta.pop("search_agents", None)
        trimmed_meta.pop("initial_run", None)
        trimmed_meta.pop("shortlist_candidates", None)
        property_form["meta"] = trimmed_meta
        property_meta = trimmed_meta
    run_payload = dict(property_state.get("run") or {})
    run_property_preferences = dict(run_payload.get("property_search_preferences") or {}) if isinstance(run_payload.get("property_search_preferences"), dict) else {}
    property_preferences = {**saved_property_preferences, **run_property_preferences}
    preference_person_id = str(property_state.get("preference_person_id") or property_preferences.get("preference_person_id") or "self").strip() or "self"
    brief_preferences_payload = dict(property_preferences)
    for heavy_key in (
        "raw_preferences",
        "saved_shortlist_candidates",
        "search_agents",
        "property_commercial",
        "preference_bundle",
    ):
        brief_preferences_payload.pop(heavy_key, None)
    if normalized_section in {"agents", "account", "settings", "billing"}:
        static_brief_keys = {
            "country_code",
            "region_code",
            "location_query",
            "listing_mode",
            "property_type",
            "property_types",
            "search_goal",
            "investment_strategy",
            "keywords",
            "selected_platforms",
        }
        brief_preferences_payload = {
            key: value
            for key, value in brief_preferences_payload.items()
            if key in static_brief_keys
        }
    run_health = dict(property_state.get("run_health") or {})
    packet_recovery = dict(property_state.get("packet_recovery") or {})
    run_events = list(run_payload.get("events") or [])
    raw_run_summary = dict(run_payload.get("summary") or {})
    run_summary = _property_customer_run_summary(raw_run_summary)
    run_payload = {**run_payload, "summary": run_summary}

    def _management_safe_run_summary(summary: dict[str, object]) -> dict[str, object]:
        safe_summary = dict(summary)
        safe_summary.pop("ranked_candidates", None)
        safe_summary.pop("candidates", None)
        safe_summary.pop("shortlist_candidates", None)
        safe_sources: list[dict[str, object]] = []
        for source in list(safe_summary.get("sources") or []):
            if not isinstance(source, dict):
                continue
            safe_source = dict(source)
            safe_source.pop("top_candidates", None)
            safe_source.pop("ranked_candidates", None)
            safe_sources.append(safe_source)
        safe_summary["sources"] = safe_sources
        return safe_summary

    management_surface = normalized_section in {"agents", "account", "settings", "billing"}
    run_summary_for_surface = _management_safe_run_summary(run_summary) if management_surface else run_summary
    run_payload_for_surface = {**run_payload, "summary": run_summary_for_surface} if management_surface else run_payload
    run_sources = [dict(row) for row in list(run_summary.get("sources") or []) if isinstance(row, dict)]
    raw_run_sources = [dict(row) for row in list(raw_run_summary.get("sources") or []) if isinstance(row, dict)]
    if not shortlist_candidates:
        ranked_candidates = [
            dict(candidate)
            for candidate in list(raw_run_summary.get("ranked_candidates") or [])
            if isinstance(candidate, dict)
            and _property_candidate_is_rankable(candidate)
        ]
        if ranked_candidates:
            shortlist_candidates = ranked_candidates
        else:
            synthesized_candidates: list[dict[str, object]] = []
            for source in raw_run_sources:
                source_label = str(source.get("source_label") or source.get("label") or "").strip()
                for candidate in [dict(row) for row in list(source.get("top_candidates") or []) if isinstance(row, dict)]:
                    if not _property_candidate_is_rankable(candidate):
                        continue
                    candidate.setdefault("source_label", source_label)
                    synthesized_candidates.append(candidate)
            synthesized_candidates.sort(key=lambda item: float(item.get("fit_score") or 0.0), reverse=True)
            shortlist_candidates = synthesized_candidates
    selected_locations = _csv_values(property_preferences.get("location_query"))
    selected_keywords = _csv_values(property_preferences.get("keywords"))
    selected_search_goal = normalized_property_search_goal(property_preferences.get("search_goal"))
    property_is_investment_search = selected_search_goal == "investment"
    effective_listing_mode = effective_property_listing_mode(
        {
            **property_preferences,
            "search_goal": selected_search_goal,
        },
        fallback=str(property_preferences.get("listing_mode") or "rent"),
    )
    mode_visibility_label = property_mode_visibility_label(
        {
            **property_preferences,
            "search_goal": selected_search_goal,
            "listing_mode": effective_listing_mode,
        },
        fallback=effective_listing_mode,
    )
    property_search_goal_label = "Find an investment" if property_is_investment_search else "Find a home"
    property_investment_strategy_label = (
        {
            "cash_flow": "Cash flow",
            "appreciation": "Appreciation",
            "undervalued": "Undervalued",
            "low_risk": "Low risk",
        }.get(str(property_preferences.get("investment_strategy") or "").strip().lower(), "Best overall opportunity")
        if property_is_investment_search
        else ""
    )
    available_platform_values = {
        str(option.get("value") or "").strip().lower()
        for option in provider_options
        if str(option.get("value") or "").strip()
    }
    has_platform_catalog = len(available_platform_values) > 0
    normalized_platforms: list[str] = []
    for value in list(property_preferences.get("selected_platforms") or property_state.get("selected_platforms") or []):
        normalized = str(value or "").strip()
        normalized_lower = normalized.lower()
        if not normalized:
            continue
        if has_platform_catalog and normalized_lower not in available_platform_values:
            continue
        if normalized_lower in normalized_platforms:
            continue
        normalized_platforms.append(normalized_lower)
    selected_platforms = normalized_platforms
    sources_total_rows = [dict(row) for row in list(run_summary.get("sources") or []) if isinstance(row, dict)]
    run_source_variant_total = max(
        int(run_summary.get("source_variant_total") or run_summary.get("sources_total") or 0),
        len(sources_total_rows),
    )
    run_provider_total = int(run_summary.get("provider_total") or 0)
    run_provider_display_total = run_provider_total
    if sources_total_rows:
        inferred_run_provider_total = _property_provider_total(sources_total_rows)
        source_total_hint = max(len(sources_total_rows), run_source_variant_total)
        if inferred_run_provider_total:
            if (
                run_provider_total <= 0
                or run_provider_total > source_total_hint
                or (run_provider_total == source_total_hint and inferred_run_provider_total < run_provider_total)
            ):
                run_provider_display_total = inferred_run_provider_total
    if run_provider_display_total <= 0 and selected_platforms:
        run_provider_display_total = len(selected_platforms)
    if selected_platforms:
        run_provider_display_total = max(run_provider_display_total, len(selected_platforms))
    run_provider_display_total = max(run_provider_display_total, 0)
    run_payload_for_surface = {
        **run_payload_for_surface,
        "provider_display_total": run_provider_display_total,
        "source_variant_display_total": run_source_variant_total,
        "selected_platform_count": len(selected_platforms),
    }
    selected_country_code = str(property_preferences.get("country_code") or property_state.get("country_code") or "AT").strip().upper() or "AT"
    workspace_currency_code = currency_code_for_country(selected_country_code) or "EUR"
    workspace_timezone = str(workspace.get("timezone") or default_timezone_for_country(selected_country_code) or "UTC").strip() or "UTC"
    supported_currency_pattern = "|".join(re.escape(code) for code in supported_currency_codes())
    supported_currency_strip_pattern = re.compile(rf"\b(?:{supported_currency_pattern})\b", flags=re.IGNORECASE)
    run_has_explicit_listing_context = bool(
        run_property_preferences
        or str(raw_run_summary.get("listing_mode") or "").strip()
        or str(raw_run_summary.get("search_goal") or "").strip()
    )
    run_has_explicit_scope_context = bool(
        run_property_preferences
        or str(raw_run_summary.get("country_code") or "").strip()
        or str(raw_run_summary.get("region_code") or "").strip()
        or str(raw_run_summary.get("location_query") or "").strip()
    )
    review_scope_locations = selected_locations if run_has_explicit_scope_context else []
    suppression_rows = _property_suppression_rows(
        run_summary=run_summary,
        source_rows=run_sources,
        preferences=property_preferences,
        include_soft=False,
    )
    counterfactual_rows = _property_counterfactual_rows(
        preferences=property_preferences,
        raw_preferences=dict(property_state.get("raw_preferences") or {}),
        run_summary=run_summary,
        provider_options=provider_options,
        current_platform_cap=current_platform_cap,
        currency_code=workspace_currency_code,
    )
    delivery_proof_rows = _delivery_proof_rows(run_summary)
    artifact_receipt_rows = _artifact_receipt_rows(run_summary)
    selected_candidate_ref = str(property_state.get("selected_candidate_ref") or "").strip()
    run_id = str(run_payload.get("run_id") or "").strip()
    run_suffix = f"?run_id={run_id}" if run_id else ""
    search_posture_items = list(search_posture_card.get("items") or [])
    fleet_digest = dict(billing_truth.get("fleet_digest") or property_state.get("fleet_digest") or {}) if wants_credit_digest else {}
    fleet_digest_items = [
        row_item(
            str(item.get("title") or "Repair notes"),
            str(item.get("detail") or item.get("value") or "").strip() or str(fleet_digest.get("preview_text") or "Repair notes pending"),
            str(item.get("tag") or "Repair"),
        )
        for item in list(fleet_digest.get("items") or [])[:4]
        if isinstance(item, dict)
    ] if wants_credit_digest else []
    fleet_digest_summary = str(fleet_digest.get("summary") or fleet_digest.get("preview_text") or "").strip() if wants_credit_digest else ""
    def _local_int(value: object) -> int:
        try:
            if value not in (None, ""):
                return int(float(value))
        except Exception:
            pass
        return 0
    fleet_digest_stats = dict(fleet_digest.get("stats") or {}) if isinstance(fleet_digest.get("stats"), dict) else {}
    active_fleet_lanes = _local_int(fleet_digest_stats.get("active_lanes"))
    queued_fleet_lanes = _local_int(fleet_digest_stats.get("queued_lanes"))
    failed_fleet_lanes = _local_int(fleet_digest_stats.get("failed_lanes"))
    stalled_fleet_lanes = _local_int(fleet_digest_stats.get("stalled_lanes"))
    repair_truth_rows = [
        row_item(
            "Repair lanes",
            " · ".join(
                part
                for part in (
                    f"{active_fleet_lanes} active" if active_fleet_lanes else "",
                    f"{queued_fleet_lanes} queued" if queued_fleet_lanes else "",
                    f"{failed_fleet_lanes} failed" if failed_fleet_lanes else "",
                    f"{stalled_fleet_lanes} stalled" if stalled_fleet_lanes else "",
                )
                if part
            )
            or "No live repair telemetry is visible yet.",
            "Repair",
        ),
        row_item(
            "Digest",
            fleet_digest_summary or "Repair and credit digests will appear here once the next refresh completes.",
            "Digest",
        ),
    ]
    packet_ready_total = sum(
        1
        for candidate in shortlist_candidates
        if str(candidate.get("packet_url") or candidate.get("review_url") or "").strip()
    )
    tour_ready_total = sum(1 for candidate in shortlist_candidates if str(candidate.get("tour_url") or "").strip())

    run_message = str(run_health.get("message") or run_payload.get("message") or "").strip()
    run_status_value = str(run_health.get("status") or run_payload.get("status") or "").strip().lower()
    run_status_label = str(run_health.get("status_label") or "").strip() or "Queued"
    run_status_note = str(run_health.get("status_note") or "").strip()
    run_in_progress = bool(run_id and bool(run_health.get("in_progress")))
    progress_route_previews = _property_progress_route_preview_rows(
        run_summary=run_summary,
        property_preferences=property_preferences,
    ) if wants_run_views else []
    search_worker_state = _property_search_worker_slots(run_summary, plan_key=str(commercial.get("current_plan_key") or "free")) if wants_run_views else []

    def _run_count(value: object, default: int = 0) -> int:
        try:
            return max(0, int(float(str(value or "").strip())))
        except Exception:
            return default

    open_research_task_total = _run_count(run_health.get("open_research_task_total") or run_payload.get("open_research_task_total") or raw_run_summary.get("open_research_task_total"))
    filled_research_task_total = _run_count(run_health.get("filled_research_task_total") or run_payload.get("filled_research_task_total") or raw_run_summary.get("filled_research_task_total"))
    dismissed_research_task_total = _run_count(run_health.get("dismissed_research_task_total") or run_payload.get("dismissed_research_task_total") or raw_run_summary.get("dismissed_research_task_total"))
    research_task_total = _run_count(run_health.get("research_task_total") or run_payload.get("research_task_total") or raw_run_summary.get("research_task_total"))

    scope_preview_builder = _property_scope_preview_map_only if normalized_section == "agents" else _property_scope_preview
    previous_search_runs = [
        build_property_previous_run_summary(
            dict(row),
            include_scope_preview=normalized_section != "agents" and index < 6,
            scope_preview_builder=scope_preview_builder,
            compact_provider_label=_compact_provider_label,
            candidate_maps_url_builder=_property_candidate_maps_url,
        )
        for index, row in enumerate(list(property_state.get("recent_search_runs") or []))
        if isinstance(row, dict) and str(row.get("run_id") or "").strip()
    ] if wants_search_runs else []
    if wants_search_runs or wants_agent_views:
        selected_agent_context = select_property_search_agent(
            property_search_agents,
            requested_agent_id=str(property_state.get("selected_agent_id") or "").strip(),
            previous_runs=previous_search_runs,
            run_id=run_id,
        )
    else:
        selected_agent_context = {
            "selected_agent": {},
            "selected_agent_id": "",
            "selected_agent_runs": [],
            "selected_agent_latest_run": {},
            "selected_agent_open_href": "",
            "selected_agent_edit_href": "",
        }
    selected_agent = selected_agent_context["selected_agent"]
    selected_agent_id = selected_agent_context["selected_agent_id"]
    selected_agent_runs = selected_agent_context["selected_agent_runs"]
    selected_agent_latest_run = selected_agent_context["selected_agent_latest_run"]
    selected_agent_open_href = selected_agent_context["selected_agent_open_href"]
    selected_agent_edit_href = selected_agent_context["selected_agent_edit_href"]

    preference_manager = build_property_preference_manager_snapshot(
        person_id=preference_person_id,
        raw_preference_nodes=raw_preference_nodes,
        include_full_manager=wants_full_preference_manager,
        schema=_property_preference_schema() if wants_full_preference_manager else {},
    )
    if normalized_section == "search":
        decision_workbench = PropertyDecisionWorkbenchContract(
            run=PropertyDecisionWorkbenchRunContract(
                run_id="",
                status="not_started",
                status_label="Ready",
                progress=0,
                message="",
                status_url="",
                summary={},
                filtered_total=0,
                held_back_total=0,
                events=[],
                worker_state=[],
                reliability={},
                research_task_total=0,
                open_research_task_total=0,
                filled_research_task_total=0,
                dismissed_research_task_total=0,
                provider_display_total=run_provider_display_total,
                source_variant_display_total=run_source_variant_total,
                selected_platform_count=len(selected_platforms),
                route_previews=[],
            ),
            brief=PropertyDecisionWorkbenchBriefContract(
                country=str(property_state.get("country_label") or "Market"),
                search_goal=selected_search_goal,
                search_goal_label=property_search_goal_label,
                mode=mode_visibility_label,
                investment_strategy_label=property_investment_strategy_label if property_is_investment_search else "",
                region=str(property_state.get("region_label") or property_preferences.get("region_code") or "").strip(),
                areas=selected_locations,
                priorities=selected_keywords,
                providers=selected_platforms,
                plan=current_plan_label,
                plan_key=str(commercial.get("current_plan_key") or "free").strip().lower() or "free",
                research_depth=str(commercial.get("research_depth") or "deep").strip(),
            ),
            brief_preferences=brief_preferences_payload,
            endpoints={
                "preferences": str(property_meta.get("preferences_endpoint") or "").strip(),
                "start": str(property_meta.get("start_endpoint") or "").strip(),
                "billing_order": str(property_meta.get("billing_order_endpoint") or "").strip(),
                "delete_run_template": "/app/api/property/search-runs/__RUN_ID__",
            },
            counterfactual_rows=counterfactual_rows,
            recent_packets=[],
            previous_search_runs=[],
            search_agents=[],
            search_agent={},
            results=[],
            search_guard_rows=[],
            suppression_rows=[],
            delivery_proof_rows=[],
            artifact_receipt_rows=[],
            research_tasks=[],
            research_task_counts={"total": 0, "open": 0, "filled": 0, "dismissed": 0},
            selected_candidate_ref="",
            selected={},
            empty_outcome={},
            packet_recovery=packet_recovery,
            show_brief_default=True,
        )
        return PropertySurfacePayloadContract(
            title="Search",
            summary="Set the market, filters, source mix, and what matters before launching the next run.",
            stats=list(base.get("stats") or []),
            current_plan_label=current_plan_label,
            run_payload={},
            run_summary={},
            preference_manager=preference_manager,
            decision_workbench=decision_workbench,
            extras={
                "hero_kicker": "Search",
                "hero_title": "Shape the next property run.",
                "hero_summary": "Brief, sources, priorities.",
                "hero_actions": [],
                "hero_highlights": [
                    {
                        "label": "Areas",
                        "value": str(len(selected_locations) or 0),
                        "detail": ", ".join(selected_locations[:3]) or "Choose the target areas.",
                        "href": f"/app/search{run_suffix}",
                    },
                    {
                        "label": "Priorities",
                        "value": str(len(selected_keywords) or 0),
                        "detail": ", ".join(selected_keywords[:3]) or "Record what should drive the ranking.",
                        "href": f"/app/search{run_suffix}",
                    },
                    {
                        "label": "Providers",
                        "value": str(len(selected_platforms) or 0),
                        "detail": "The selected portals for the next sweep.",
                        "href": f"/app/search{run_suffix}",
                    },
                ],
                "primary_cards": [card for card in (search_posture_card, market_coverage_card) if card],
                "secondary_cards": [],
                "console_form": property_form,
                "show_brief_form": True,
                "show_run_panel": False,
                "show_shortlist_cards": False,
                "show_results_table": False,
                "results_table_headers": [],
                "results_table_rows": [],
            },
        ).to_dict()

    def _tour_source_gap_detail(candidate: dict[str, object]) -> str:
        blocked_reason = str(candidate.get("blocked_reason") or "").strip()
        if blocked_reason:
            reason_map = {
                "listing_360_media_missing": "3D tour not ready yet. This listing still needs a floorplan or usable 360 source.",
                "pure_360_assets_unavailable": "3D tour not ready yet. The source media could not be opened reliably enough to rebuild it.",
                "property_tour_fallback_disabled": "3D tour not ready yet. A floorplan or usable 360 source is still missing.",
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
            return "3D tour not ready yet. This listing still needs a floorplan or usable 360 source."
        if _false_flag(facts.get("has_360")) or _zero_count("media_count", "image_count"):
            return "3D tour not ready yet. More usable room media is still needed."
        return "3D tour not ready yet. More source material is still needed before it can be built."

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
        area_value = str(
            facts.get("area_display")
            or facts.get("living_area_display")
            or facts.get("usable_area_display")
            or facts.get("area_m2")
            or facts.get("living_area_m2")
            or facts.get("area_sqm")
            or ""
        ).strip()
        if price_value:
            parts.append(price_value)
        if rooms_value:
            parts.append(f"{rooms_value} rooms")
        if area_value:
            parts.append(area_value if "m2" in area_value.lower() or "m²" in area_value.lower() else f"{area_value} m2")
        return " | ".join(parts)

    def _area_display(facts: dict[str, object]) -> str:
        for key in (
            "area_display",
            "living_area_display",
            "usable_area_display",
            "wohnflaeche_display",
            "wohnfläche_display",
        ):
            value = str(facts.get(key) or "").strip()
            if value:
                return value
        for key in (
            "area_m2",
            "area_sqm",
            "living_area_m2",
            "living_area_sqm",
            "usable_area_m2",
            "wohnflaeche_m2",
            "wohnfläche_m2",
        ):
            value = str(facts.get(key) or "").strip()
            if value:
                return f"{value} m2"
        return ""

    def _floorplan_url(facts: dict[str, object]) -> str:
        for key in ("floorplan_preview_url", "floorplan_url", "floorplan_image_url"):
            value = str(facts.get(key) or "").strip()
            if value:
                return value
        for key in ("floorplan_urls_json", "floorplan_urls"):
            raw = facts.get(key)
            rows = raw if isinstance(raw, list) else []
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        rows = parsed
                except Exception:
                    rows = [raw]
            for item in rows:
                if isinstance(item, dict):
                    for item_key in ("image_url", "url", "src", "href"):
                        value = str(item.get(item_key) or "").strip()
                        if value:
                            return value
                else:
                    value = str(item or "").strip()
                    if value:
                        return value
        return ""

    def _obvious_listing_mode_mismatch(facts: dict[str, object], *, listing_mode: str) -> bool:
        normalized_mode = str(listing_mode or "").strip().lower()
        if normalized_mode == "buy":
            has_buy_price = isinstance(_property_investment_price_eur(facts), float)
            has_rent_signal = any(
                facts.get(key)
                for key in (
                    "rent_display",
                    "warm_rent_display",
                    "cold_rent_display",
                    "total_rent_display",
                    "warm_rent_eur",
                    "cold_rent_eur",
                    "total_rent_eur",
                    "rent_eur",
                    "gesamtmiete_display",
                )
            )
            return bool(has_rent_signal and not has_buy_price)
        if normalized_mode == "rent":
            has_buy_signal = isinstance(_property_investment_price_eur(facts), float)
            has_rent_price = any(
                facts.get(key)
                for key in ("rent_display", "warm_rent_display", "cold_rent_display", "total_rent_display", "rent_eur", "total_rent_eur")
            )
            return bool(has_buy_signal and not has_rent_price)
        return False

    compare_rows = []
    for candidate in shortlist_candidates[:3]:
        fit_summary = str(candidate.get("fit_summary") or candidate.get("detail") or "").strip()
        fact_line = _candidate_fact_line(candidate)
        detail = " | ".join(part for part in (fit_summary, fact_line) if part) or "Open the property page to inspect the ranking and evidence."
        compare_rows.append(
            {
                "title": str(candidate.get("title") or "Shortlist candidate").strip() or "Shortlist candidate",
                "detail": detail,
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Candidate").strip() or "Candidate",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open property page",
                "secondary_action_href": str(candidate.get("tour_url") or candidate.get("review_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("tour_url") or candidate.get("review_url")) else "",
                "secondary_action_label": "Open 360" if candidate.get("tour_url") else ("Open listing" if candidate.get("review_url") else ""),
            }
        )

    def _tour_status_line(candidate: dict[str, object]) -> str:
        provider_tour_url = str(
            candidate.get("source_virtual_tour_url")
            or (
                dict(candidate.get("property_facts") or {}).get("source_virtual_tour_url")
                if isinstance(candidate.get("property_facts"), dict)
                else ""
            )
            or ""
        ).strip()
        if "api.willhaben.at/restapi/v2/logevent/" in provider_tour_url.lower():
            provider_tour_url = ""
        if str(candidate.get("tour_url") or "").strip():
            return "Ready | Live now"
        if provider_tour_url:
            return "Ready | Provider 360"
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
        return f"{workspace_currency_code} {price / area:,.0f}/m2"

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
                "detail": match_reasons[0] if match_reasons else (mismatch_reasons[0] if mismatch_reasons else "Open the property page for the full decision read."),
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
                    "detail": "The property page is ready for household or advisor follow-up.",
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
            rows.append({"title": "No household votes yet", "detail": "Shared reactions will appear here after a property page decision is recorded.", "tag": "Waiting"})
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
        provider_tour_url = str(
            candidate.get("source_virtual_tour_url")
            or (
                dict(candidate.get("property_facts") or {}).get("source_virtual_tour_url")
                if isinstance(candidate.get("property_facts"), dict)
                else ""
            )
            or ""
        ).strip()
        if "api.willhaben.at/restapi/v2/logevent/" in provider_tour_url.lower():
            provider_tour_url = ""
        status = str(candidate.get("tour_status") or "").strip().lower()
        eta_minutes = str(candidate.get("tour_eta_minutes") or "").strip()
        if tour_url:
            blocked_fallback = False
            try:
                from app.product import property_tour_hosting

                parsed_tour = urllib.parse.urlparse(tour_url)
                path_parts = [part for part in str(parsed_tour.path or "").split("/") if part]
                slug = path_parts[-1] if len(path_parts) >= 2 and path_parts[-2] == "tours" else ""
                if slug:
                    hosted_payload = property_tour_hosting._existing_hosted_property_tour_payload(slug)  # type: ignore[attr-defined]
                    blocked_fallback = bool(
                        hosted_payload and property_tour_hosting._property_tour_payload_is_disabled_fallback(hosted_payload)  # type: ignore[attr-defined]
                    )
            except Exception:
                blocked_fallback = False
            if blocked_fallback:
                return {
                    "status": "blocked",
                    "label": "360 unavailable",
                    "url": "",
                    "embed_url": "",
                    "eta_label": "A real hosted 3D tour is not available for this listing yet.",
                }
            embed_url = tour_url
            try:
                from app.product import property_tour_hosting

                parsed_tour = urllib.parse.urlparse(tour_url)
                tour_host = str(parsed_tour.netloc or "").strip().lower()
                property_host = urllib.parse.urlparse(property_tour_hosting._property_public_app_base_url()).netloc.strip().lower()  # type: ignore[attr-defined]
                if property_tour_hosting._is_branded_public_tour_url(tour_url) and tour_host and property_host and tour_host != property_host:  # type: ignore[attr-defined]
                    embed_url = ""
            except Exception:
                embed_url = tour_url
            return {"status": "ready", "label": "360 ready", "url": tour_url, "embed_url": embed_url, "eta_label": ""}
        if provider_tour_url:
            return {
                "status": "ready",
                "label": "360 ready",
                "url": provider_tour_url,
                "embed_url": provider_tour_url,
                "eta_label": "Provider 360",
            }
        if status in {"queued", "pending"}:
            return {"status": "queued", "label": "360 queued", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '10'} min"}
        if status in {"processing", "running", "in_progress", "started"}:
            return {"status": "processing", "label": "360 rendering", "url": "", "embed_url": "", "eta_label": f"about {eta_minutes or '5'} min"}
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return {"status": "blocked", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}
        return {"status": "missing", "label": "360 unavailable", "url": "", "embed_url": "", "eta_label": _tour_source_gap_detail(candidate)}

    def _flythrough_payload(candidate: dict[str, object]) -> dict[str, object]:
        flythrough_url = str(candidate.get("flythrough_url") or "").strip()
        status = str(candidate.get("flythrough_status") or "").strip().lower()
        reason = str(candidate.get("flythrough_reason") or "").strip()
        provider = str(candidate.get("flythrough_provider") or "").strip()
        if flythrough_url:
            return {
                "status": "ready",
                "label": "Open walkthrough",
                "url": flythrough_url,
                "detail": provider.replace("_", " ").title() if provider else "Walkthrough ready",
                "progress_pct": 100,
                "eta_label": "",
            }
        if status in {"queued", "pending"}:
            return {
                "status": "queued",
                "label": "Walkthrough queued",
                "url": "",
                "detail": "Queued after your request.",
                "progress_pct": 18,
                "eta_label": "about 10 min",
            }
        if status in {"processing", "running", "in_progress", "started", "rendering"}:
            return {
                "status": "processing",
                "label": "Walkthrough processing",
                "url": "",
                "detail": "Rendering after your request.",
                "progress_pct": 64,
                "eta_label": "about 5 min",
            }
        if status in {"blocked", "failed", "skipped", "not_applicable"}:
            return {
                "status": "blocked",
                "label": "Walkthrough unavailable",
                "url": "",
                "detail": reason or "Source material was not strong enough to render a walkthrough.",
                "progress_pct": 0,
                "eta_label": "",
            }
        return {"status": "missing", "label": "", "url": "", "detail": "", "progress_pct": 0, "eta_label": ""}

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

    def _normalized_money_text(text: str) -> str:
        upper_text = text.upper()
        currency = next((code for code in supported_currency_codes() if code in upper_text), "")
        if not currency and "€" in text:
            currency = "EUR"
        money_match = re.search(r"[0-9][0-9\.\,\s]*(?:[,.][0-9]{1,2})?", text)
        if not money_match:
            return text if currency else ""
        number_text = money_match.group(0).replace(" ", "").strip(".,")
        if "." in number_text and "," in number_text:
            number_text = number_text.replace(".", "").replace(",", ".")
        elif "," in number_text:
            integer_part, decimal_part = number_text.rsplit(",", 1)
            number_text = integer_part + decimal_part if len(decimal_part) == 3 else integer_part + "." + decimal_part
        elif number_text.count(".") > 1:
            number_text = number_text.replace(".", "")
        elif "." in number_text:
            integer_part, decimal_part = number_text.rsplit(".", 1)
            if len(decimal_part) == 3 and integer_part.isdigit():
                number_text = integer_part + decimal_part
        try:
            amount = float(number_text)
        except Exception:
            return text if currency else ""
        if amount <= 0:
            return ""
        return f"{currency or workspace_currency_code} {amount:,.0f}".replace(",", ",")

    def _money_display(value: object) -> str:
        if value in (None, "", []):
            return ""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            if supported_currency_strip_pattern.search(text) or "€" in text:
                return _normalized_money_text(text)
            try:
                value = float(text.replace(",", "."))
            except Exception:
                return text
        if isinstance(value, (int, float)):
            amount = float(value)
            if abs(amount) >= 1000:
                formatted = f"{amount:,.0f}".replace(",", ",")
                return f"{workspace_currency_code} {formatted}"
            if amount:
                return f"{workspace_currency_code} {amount:.0f}"
        return ""

    def _money_numeric_value(value: object) -> float | None:
        if value in (None, "", []):
            return None
        if isinstance(value, (int, float)):
            amount = float(value)
            return amount if amount > 0.0 else None
        text = str(value or "").strip()
        if not text:
            return None
        normalized = _normalized_money_text(text) if (supported_currency_strip_pattern.search(text) or "€" in text) else text
        cleaned = supported_currency_strip_pattern.sub("", normalized).replace("€", "").replace(",", "").strip()
        try:
            amount = float(cleaned)
        except Exception:
            return None
        return amount if amount > 0.0 else None

    def _property_investment_price_eur(facts: dict[str, object]) -> float | None:
        for key in ("purchase_price_eur", "buy_price_eur", "price_eur", "price_numeric", "kaufpreis_eur"):
            value = _money_numeric_value(facts.get(key))
            if isinstance(value, float) and value > 0.0:
                return value
        return None

    def _candidate_costs_line(facts: dict[str, object], *, listing_mode: str, price_line: str) -> str:
        normalized_mode = str(listing_mode or "").strip().lower()
        for key in (
            "operating_costs_display",
            "operating_costs_monthly_display",
            "betriebskosten_display",
            "betriebskosten_monatlich_display",
            "service_charges_display",
            "additional_costs_display",
            "side_costs_display",
            "monthly_costs_display",
            "warm_rent_display",
            "cold_rent_display",
            "total_rent_display",
            "gesamtmiete_display",
        ):
            value = str(facts.get(key) or "").strip()
            if value:
                return value
        for key in (
            "operating_costs_monthly",
            "operating_costs_monthly_eur",
            "operating_costs",
            "service_charges_eur",
            "additional_costs_eur",
            "side_costs_eur",
            "betriebskosten_eur",
            "betriebskosten_monatlich_eur",
            "monthly_operating_costs_eur",
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
            return "Operating costs not listed"
        price_per_sqm = _money_per_sqm_line(facts)
        if price_per_sqm:
            return price_per_sqm
        return "Running costs not listed"

    def _title_price_fallback(title: object) -> str:
        text = " ".join(str(title or "").split()).strip()
        if not text:
            return ""
        patterns = [
            r"(€\s?[0-9][0-9\.\s]*(?:,[0-9]{1,2})?\s*,-?)",
            rf"((?:{supported_currency_pattern})\s?[0-9][0-9\.,\s]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw = " ".join(str(match.group(1) or "").split()).strip(" ,")
                return _normalized_money_text(raw) or raw
        return ""

    def _candidate_price_signal(
        facts: dict[str, object],
        *,
        listing_mode: str,
        title: object,
    ) -> str:
        normalized_mode = str(listing_mode or "").strip().lower()
        if normalized_mode == "buy":
            for key in (
                "price_display",
                "purchase_price_display",
                "buy_price_display",
                "price_eur",
                "purchase_price_eur",
                "buy_price_eur",
            ):
                value = _money_display(facts.get(key)) if key.endswith("_eur") else str(facts.get(key) or "").strip()
                if value:
                    return value
        else:
            for key in (
                "rent_display",
                "monthly_rent_display",
                "warm_rent_display",
                "cold_rent_display",
                "total_rent_display",
                "rent_eur",
                "monthly_rent_eur",
                "warm_rent_eur",
                "cold_rent_eur",
                "total_rent_eur",
            ):
                value = _money_display(facts.get(key)) if key.endswith("_eur") else str(facts.get(key) or "").strip()
                if value:
                    return value
        return _title_price_fallback(title)

    def _candidate_is_generic_listing_page(
        candidate: dict[str, object],
        facts: dict[str, object],
    ) -> bool:
        title = " ".join(str(candidate.get("title") or "").split()).strip().lower()
        url = str(candidate.get("property_url") or "").strip().lower()
        concrete_signals = any(
            (
                facts.get("rooms"),
                facts.get("living_area_sqm"),
                facts.get("area_sqm"),
                facts.get("usable_area_sqm"),
                facts.get("price_eur"),
                facts.get("purchase_price_eur"),
                facts.get("buy_price_eur"),
                facts.get("rent_eur"),
                facts.get("monthly_rent_eur"),
                facts.get("warm_rent_eur"),
                facts.get("cold_rent_eur"),
                facts.get("exact_address"),
                facts.get("street_address"),
            )
        )
        if concrete_signals:
            return False
        generic_title_markers = (
            "immobiliensuche",
            "bestandsobjekte",
            "projekte",
            "projekte in bau",
            "projekte in planung",
            "gemeindewohnungen",
            "angebote",
            "overview",
            "suche",
            "wohnungen",
            "projektdetail",
            "immobilien",
            "projektentwickler",
            "architekturwettbewerbe",
        )
        generic_url_markers = (
            "/suche",
            "/projekte",
            "/projekt/",
            "/angebote",
            "/immobilien/",
            "/immobilien",
            "/overview",
            "/bestandsobjekte",
            "/gemeindewohnungen",
        )
        return any(marker in title for marker in generic_title_markers) or any(marker in url for marker in generic_url_markers)

    def _candidate_is_non_residential(
        candidate: dict[str, object],
        facts: dict[str, object],
    ) -> bool:
        text = " ".join(
            part for part in (
                str(candidate.get("title") or "").strip(),
                str(candidate.get("summary") or "").strip(),
                str(candidate.get("property_url") or "").strip(),
                str(facts.get("property_type") or "").strip(),
            ) if part
        ).lower()
        non_res_markers = (
            "lager",
            "storage",
            "garage",
            "stellplatz",
            "parkplatz",
            "büro",
            "buero",
            "office",
            "gewerbe",
            "geschäftslokal",
            "geschaeftslokal",
            "retail",
            "shop",
            "local",
        )
        residential_markers = ("wohnung", "apartment", "flat", "haus", "house", "penthouse", "garden apartment")
        return any(marker in text for marker in non_res_markers) and not any(marker in text for marker in residential_markers)

    def _candidate_matches_selected_postal_scope(
        candidate: dict[str, object],
        facts: dict[str, object],
        *,
        selected_locations: list[str],
    ) -> bool:
        requested_postal_codes = {
            code
            for value in selected_locations
            for code in _property_postal_codes_from_text(value, require_locality=False)
        }
        if not requested_postal_codes:
            return True
        listing_text = " ".join(
            part for part in (
                str(candidate.get("title") or "").strip(),
                str(candidate.get("summary") or "").strip(),
            ) if part
        )
        listing_postal_codes = set(_property_postal_codes_from_text(listing_text, require_locality=True))
        if listing_postal_codes:
            return bool(listing_postal_codes & requested_postal_codes)
        concrete_text = " ".join(
            part for part in (
                str(candidate.get("title") or "").strip(),
                str(candidate.get("summary") or "").strip(),
                str(candidate.get("property_url") or "").strip(),
                str(facts.get("district") or "").strip(),
                str(facts.get("postal_name") or "").strip(),
                str(facts.get("street_address") or "").strip(),
                str(facts.get("exact_address") or "").strip(),
            ) if part
        )
        found_postal_codes = set(_property_postal_codes_from_text(concrete_text, require_locality=False))
        if not found_postal_codes:
            return True
        return bool(found_postal_codes & requested_postal_codes)

    def _candidate_has_concrete_location_signal(
        candidate: dict[str, object],
        facts: dict[str, object],
    ) -> bool:
        if any(
            str(facts.get(key) or "").strip()
            for key in ("district", "postal_name", "street_address", "exact_address", "address")
        ):
            return True
        text = " ".join(
            part
            for part in (
                str(candidate.get("title") or "").strip(),
                str(candidate.get("summary") or "").strip(),
            )
            if part
        )
        return bool(_property_postal_codes_from_text(text, require_locality=True))

    def _candidate_is_shortlist_admissible(
        candidate: dict[str, object],
        facts: dict[str, object],
        *,
        listing_mode: str,
        selected_locations: list[str],
    ) -> bool:
        source_family = str(candidate.get("source_family") or facts.get("source_family") or "").strip().lower()
        has_price_signal = bool(_candidate_price_signal(facts, listing_mode=listing_mode, title=candidate.get("title")))
        has_area_signal = bool(
            str(facts.get("living_area_sqm") or "").strip()
            or str(facts.get("area_sqm") or "").strip()
            or str(facts.get("usable_area_sqm") or "").strip()
        )
        if _candidate_is_non_residential(candidate, facts):
            return False
        if _candidate_is_generic_listing_page(candidate, facts):
            return False
        if not _candidate_has_concrete_location_signal(candidate, facts):
            return False
        if not _candidate_matches_selected_postal_scope(candidate, facts, selected_locations=selected_locations):
            return False
        if not has_price_signal:
            return False
        if source_family == "developer_projects" and not has_price_signal and not has_area_signal:
            return False
        has_core_signal = bool(
            has_price_signal
            or str(facts.get("rooms") or "").strip()
            or has_area_signal
            or str(candidate.get("tour_url") or "").strip()
            or str(_floorplan_url(facts) or "").strip()
        )
        if not has_core_signal:
            return False
        return True

    def _candidate_repair_flag(
        candidate: dict[str, object],
        facts: dict[str, object],
        *,
        listing_mode: str,
        selected_locations: list[str],
    ) -> tuple[str, str]:
        if str(candidate.get("flythrough_raw_status") or "").strip().lower() == "failed" and str(candidate.get("flythrough_url") or "").strip():
            return ("Repair flagged", "Renderer reported failed even though a hosted walkthrough exists.")
        return ("", "")

    for candidate in ([] if management_surface else shortlist_candidates):
        facts = _property_candidate_display_facts(candidate)
        if run_has_explicit_listing_context and _obvious_listing_mode_mismatch(facts, listing_mode=effective_listing_mode):
            continue
        if not _candidate_is_shortlist_admissible(
            candidate,
            facts,
            listing_mode=effective_listing_mode,
            selected_locations=review_scope_locations,
        ):
            continue
        price_line = str(
            facts.get("price_display")
            or facts.get("rent_display")
            or facts.get("price_eur")
            or ""
        ).strip()
        parsed_buy_price = _money_numeric_value(facts.get("price_eur"))
        if effective_listing_mode == "buy":
            suspicious_display = _money_numeric_value(price_line) if price_line else None
            if isinstance(parsed_buy_price, float) and parsed_buy_price >= 1000.0 and (
                not price_line
                or not isinstance(suspicious_display, float)
                or suspicious_display < 1000.0
            ):
                price_line = _money_display(parsed_buy_price)
        if not price_line or price_line.lower() == "n/a":
            price_line = _title_price_fallback(candidate.get("title") or "")
        if not price_line:
            price_line = "n/a"
        fit_score = _fit_score_value(candidate, facts)
        layout_parts = [_rooms_layout_part(facts), _area_display(facts)]
        layout_verified = bool(
            facts.get("has_floorplan")
            or facts.get("floorplan_count")
            or facts.get("floorplans_count")
            or facts.get("floorplan_urls_json")
            or facts.get("floorplan_urls")
        )
        packet_url = str(candidate.get("packet_url") or "").strip()
        review_url = str(candidate.get("review_url") or "").strip()
        if not packet_url and "/app/research/" in review_url:
            packet_url = review_url
        map_url = str(candidate.get("map_url") or "").strip() or _property_candidate_maps_url(candidate)
        tour_status_line = _tour_status_line(candidate)
        ooda_detail = _distance_line(candidate)
        candidate_ref = str(packet_url or "").split("/app/research/", 1)[-1].split("?", 1)[0] if "/app/research/" in packet_url else _property_candidate_ref(candidate)
        if not packet_url and candidate_ref:
            packet_url = f"/app/research/{candidate_ref}"
            if run_id:
                packet_url = f"{packet_url}?run_id={urllib.parse.quote(run_id, safe='')}"
        packet_label = "Property page" if packet_url else "Pending"
        tour_payload = _tour_payload(candidate)
        ooda_rows = _candidate_ooda_rows(candidate, facts)
        risk_payload = _risk_summary(candidate, facts)
        match_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("match_reasons") or []) if _clean_property_candidate_copy(item)]
        mismatch_reasons = [_clean_property_candidate_copy(item) for item in list(candidate.get("mismatch_reasons") or []) if _clean_property_candidate_copy(item)]
        detail_sections = _candidate_detail_sections(facts)
        candidate_investment = dict(candidate.get("investment") or {}) if isinstance(candidate.get("investment"), dict) else {}
        investment_headline_fallback = (
            "Underwriting is still building from the current listing evidence."
            if effective_listing_mode == "buy"
            else ""
        )
        investment_payload = {
            "enabled": effective_listing_mode == "buy",
            "price_per_sqm": _money_per_sqm_line(facts),
            "headline": str(candidate_investment.get("headline") or investment_headline_fallback).strip(),
            "gross_yield_display": str(candidate_investment.get("gross_yield_display") or "").strip(),
            "net_yield_display": str(candidate_investment.get("net_yield_display") or "").strip(),
            "cap_rate_display": str(candidate_investment.get("cap_rate_display") or "").strip(),
            "cash_on_cash_display": str(candidate_investment.get("cash_on_cash_display") or "").strip(),
            "dscr_display": str(candidate_investment.get("dscr_display") or "").strip(),
            "market_delta_display": str(candidate_investment.get("market_delta_display") or "").strip(),
            "expected_rent_display": str(candidate_investment.get("expected_rent_display") or "").strip(),
            "confidence_label": str(candidate_investment.get("confidence_label") or "").strip(),
            "feed_status_label": str(candidate_investment.get("feed_status_label") or "").strip(),
            "feed_status_detail": str(candidate_investment.get("feed_status_detail") or "").strip(),
            "score": candidate_investment.get("score"),
            "score_display": str(candidate_investment.get("score_display") or "").strip(),
            "underwriting_summary": str(candidate_investment.get("underwriting_summary") or "").strip(),
            "strategy": str(candidate_investment.get("strategy") or "").strip(),
            "dimensions": [dict(item) for item in list(candidate_investment.get("dimensions") or []) if isinstance(item, dict)][:7],
            "reasons": [str(item).strip() for item in list(candidate_investment.get("reasons") or []) if str(item).strip()][:3],
            "blockers": [str(item).strip() for item in list(candidate_investment.get("blockers") or []) if str(item).strip()][:3],
        }
        orientation_preview = _property_workbench_lightweight_orientation_preview(
            _property_candidate_orientation_preview(candidate)
        )
        repair_flag_label, repair_flag_detail = _candidate_repair_flag(
            candidate,
            facts,
            listing_mode=effective_listing_mode,
            selected_locations=review_scope_locations,
        )
        workbench_results.append(
            build_property_workbench_candidate_snapshot(
                candidate_ref=candidate_ref,
                rank=len(workbench_results) + 1,
                title=_property_result_title_display(candidate.get("title") or "Candidate"),
                recovered_by_filter=bool(candidate.get("recovered_by_filter") or candidate.get("counterfactual_recovered")),
                relaxed_filter_label=str(candidate.get("relaxed_filter_label") or candidate.get("counterfactual_label") or "").strip(),
                preview_image_url=_property_workbench_lightweight_image_url(
                    candidate.get("preview_image_url") or _property_candidate_preview_image(candidate)
                ),
                source_label=_compact_provider_label(candidate.get("source_label") or ""),
                location_label=str(facts.get("district") or facts.get("postal_name") or facts.get("city") or facts.get("address") or "").strip(),
                price_display=price_line,
                costs_display=_candidate_costs_line(
                    facts,
                    listing_mode=effective_listing_mode,
                    price_line=price_line,
                ),
                price_per_sqm_display=investment_payload["price_per_sqm"],
                layout_display=" | ".join(part for part in layout_parts if part) or "n/a",
                layout_verification_label="verified" if layout_verified else "needs check",
                fit_score=fit_score,
                fit_label=str(candidate.get("recommendation") or candidate.get("tag") or "Candidate").strip().replace("_", " ").title(),
                fit_summary=_clean_property_candidate_copy(candidate.get("fit_summary") or ""),
                tour=tour_payload,
                flythrough=_flythrough_payload(candidate),
                orientation_preview=orientation_preview,
                ooda={
                    "summary": ooda_detail or (match_reasons[0] if match_reasons else "Open the property page to inspect the decision read."),
                    "rows": ooda_rows,
                },
                risk=risk_payload,
                investment=investment_payload,
                match_reasons=match_reasons,
                mismatch_reasons=mismatch_reasons,
                review_page_neuronwriter=dict(candidate.get("review_page_neuronwriter") or {}) if isinstance(candidate.get("review_page_neuronwriter"), dict) else {},
                packet_url=packet_url,
                review_url=str(candidate.get("review_url") or "").strip(),
                property_url=str(candidate.get("property_url") or "").strip(),
                map_url=map_url,
                source_url=str(candidate.get("property_url") or "").strip(),
                floorplan_url=_floorplan_url(facts),
                property_facts=facts,
                assessment=dict(candidate.get("assessment") or {}) if isinstance(candidate.get("assessment"), dict) else {},
                objection_rows=_candidate_objection_rows(candidate, facts),
                timeline_rows=_candidate_timeline_rows(candidate, facts),
                household_rows=_candidate_household_rows(candidate),
                risk_signal_rows=_candidate_risk_signal_rows(candidate),
                followup_rows=_candidate_followup_rows(candidate),
                recent_change_rows=_candidate_recent_change_rows(candidate),
                official_evidence_rows=[
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
                official_posture_rows=_official_risk_posture_rows(
                    dict(facts.get("official_risk_evidence") or {})
                    if isinstance(facts.get("official_risk_evidence"), dict)
                    else {}
                ),
                object_rows=detail_sections["object_rows"],
                cost_rows=detail_sections["cost_rows"],
                feature_values=detail_sections["feature_values"],
                description_text=detail_sections["description_text"],
                location_text=detail_sections["location_text"],
                energy_rows=detail_sections["energy_rows"],
                household_alignment_score=int(dict(candidate.get("feedback_summary") or {}).get("household_alignment_score") or 0) if isinstance(candidate.get("feedback_summary"), dict) else 0,
                household_alignment_label=str(dict(candidate.get("feedback_summary") or {}).get("family_alignment") or "waiting") if isinstance(candidate.get("feedback_summary"), dict) else "waiting",
                repair_flag_label=repair_flag_label,
                repair_flag_detail=repair_flag_detail,
            )
        )
        results_table_rows.append(
            {
                "cells": [
                    {"title": "Open 360" if str(candidate.get("tour_url") or "").strip() else tour_status_line, "detail": "Hosted 360 tour" if str(candidate.get("tour_url") or "").strip() else "", "href": str(candidate.get("tour_url") or "").strip()},
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
            {"href": f"/app/search{run_suffix}", "label": "Edit brief"},
            {"href": f"/app/agents{run_suffix}", "label": "Automation"},
        ],
        "shortlist": [
            {"href": f"/app/properties{run_suffix}", "label": "Open run", "tone": "primary"},
            {"href": f"/app/search{run_suffix}", "label": "Refine search"},
            {"href": f"/app/agents{run_suffix}", "label": "Automation"},
        ],
        "research": [
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist", "tone": "primary"},
            {"href": f"/app/properties{run_suffix}", "label": "Refine search"},
            {"href": f"/app/alerts{run_suffix}", "label": "Alerts"},
        ],
        "profile": [
            {"href": f"/app/properties{run_suffix}", "label": "Refine search", "tone": "primary"},
            {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
            {"href": "/app/account#settings", "label": "Account"},
        ],
        "alerts": [
            {"href": f"/app/properties{run_suffix}", "label": "Open search desk", "tone": "primary"},
            {"href": f"/app/agents{run_suffix}", "label": "Saved searches"},
            {"href": "/app/account#delivery", "label": "Delivery"},
        ],
        "agents": [
            {"href": f"/app/search{run_suffix}", "label": "New watch", "tone": "primary"},
            {"href": f"/app/search{run_suffix}", "label": "Edit brief"},
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
                "value": str(property_state.get("country_label") or "Market"),
                "detail": str(search_posture_items[0].get("detail") or "").strip() if search_posture_items else "",
                "href": f"/app/search{run_suffix}",
            },
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:3]) or "Choose the target areas.", "href": f"/app/search{run_suffix}"},
            {"label": "Priorities", "value": str(len(selected_keywords) or 0), "detail": ", ".join(selected_keywords[:3]) or "Record what should drive the ranking.", "href": f"/app/search{run_suffix}"},
            {"label": "Providers", "value": str(len(selected_platforms) or 0), "detail": "The selected portals for the next sweep.", "href": f"/app/search{run_suffix}"},
        ],
        "shortlist": [
            {"label": "Candidates", "value": str(len(shortlist_candidates)), "detail": "Ranked properties worth direct review now.", "href": f"/app/shortlist{run_suffix}"},
            {"label": "Pages", "value": str(packet_ready_total), "detail": "Hosted property pages ready before the raw portal listing.", "href": f"/app/research{run_suffix}"},
            {"label": "360 ready", "value": str(tour_ready_total), "detail": "Hosted or embedded tours already available.", "href": f"/app/research{run_suffix}"},
            {"label": "Run state", "value": run_status_label, "detail": run_message or "The latest run status.", "href": f"/app/properties{run_suffix}"},
        ],
        "research": [
            {"label": "Pages", "value": str(packet_ready_total), "detail": "Hosted property pages ready for inspection.", "href": f"/app/research{run_suffix}"},
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
            {"label": "Saved searches", "value": str(len(property_search_agents)), "detail": "Recurring briefs available for editing and rerunning.", "href": f"/app/agents{run_suffix}"},
            {"label": "Active", "value": str(sum(1 for agent in property_search_agents if agent.get("enabled"))), "detail": "Agents allowed to send matching updates.", "href": f"/app/agents{run_suffix}"},
            {"label": "Delivery", "value": str(property_search_agent.get("notification_label") or "Set per agent"), "detail": "Each recurring search ranks down to the allowed message budget.", "href": f"/app/agents{run_suffix}"},
            {"label": "Reports", "value": "Email", "detail": "Digests, repair notes, and market watches leave from this lane.", "href": f"/app/agents{run_suffix}"},
        ],
        "billing": [
            {"label": "Plan", "value": current_plan_label, "detail": "Active plan.", "href": f"/app/billing{run_suffix}"},
            {"label": "Depth", "value": str(commercial.get("research_depth") or "deep").title(), "detail": "How deep the research lane runs.", "href": f"/app/billing{run_suffix}"},
            {"label": "Providers", "value": str(commercial.get("max_platforms") or "Multi"), "detail": "Portal allowance for the active plan.", "href": f"/app/billing{run_suffix}"},
            {"label": "Per source", "value": str(commercial.get("max_results_per_source") or 2), "detail": "Maximum ranked results per provider.", "href": f"/app/billing{run_suffix}"},
        ],
        "settings": [
            {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": "/app/account#settings"},
            {"label": "Account", "value": str(workspace.get("name") or "PropertyQuarry"), "detail": workspace_timezone, "href": "/app/account#profile"},
            {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": f"/app/billing{run_suffix}"},
            {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": f"/app/profile{run_suffix}"},
        ],
    }
    preference_rows = [
        row_item(
            "Account",
            str(workspace.get("name") or "PropertyQuarry"),
            "Account",
        ),
        row_item(
            "Google sign-in",
            str(google.get("connected_account_email") or google.get("status") or "Not connected"),
            "Connection",
        ),
        row_item(
            "Timezone",
            workspace_timezone,
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
            "Account posture",
            "Billing, saved defaults, and security should stay explicit and product-specific.",
            "Control",
        ),
    ]
    delivery_channel_keys = set(
        str(channel or "").strip().lower()
        for channel in list(property_preferences.get("alert_channels") or [])
        if str(channel or "").strip()
    )
    delivery_channel_keys.update(
        key
        for key, value in channels.items()
        if key in {"email", "telegram", "whatsapp"} and isinstance(value, dict) and str(value.get("status") or "").strip().lower() in {"enabled", "active", "guided_manual", "export_planned"}
    )
    delivery_governance_rows = [
        row_item(
            str(row.get("title") or "Delivery"),
            str(row.get("detail") or "").strip(),
            str(row.get("tag") or "").strip(),
        )
        for row in property_delivery_governance_rows(sorted(delivery_channel_keys))
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
                "This lane will show the first hosted page or run update once the shortlist is strong enough to notify.",
                "Quiet",
            )
        ]
    plan_catalog = [dict(plan) for plan in list(commercial.get("plan_catalog") or []) if isinstance(plan, dict)]
    current_plan_key = str(commercial.get("current_plan_key") or "free").strip().lower() or "free"
    current_plan_spec = next((plan for plan in plan_catalog if str(plan.get("plan_key") or "").strip().lower() == current_plan_key), {})
    current_platform_cap = int(current_plan_spec.get("max_platforms") or commercial.get("max_platforms") or 0)
    current_result_cap = int(current_plan_spec.get("max_results_per_source") or commercial.get("max_results_per_source") or 0)
    current_match_cap = int(current_plan_spec.get("max_match_score") or commercial.get("max_match_score") or 0)
    commercial_state = dict(commercial.get("property_commercial") or {})
    billing_rows = [
        row_item(
            "Current plan",
            f"{current_plan_label} | {str(commercial.get('research_depth') or 'deep')} research",
            "Plan",
        ),
        row_item(
            "Coverage",
            f"{commercial.get('max_platforms') or 'Multi'} providers | up to {commercial.get('max_results_per_source') or 2} results per provider",
            "Limits",
        ),
        row_item(
            "Checkout",
            str(property_state.get("billing_checkout_provider_label") or "Unavailable"),
            "Provider",
        ),
    ]
    pending_plan_key = str(commercial_state.get("pending_plan_key") or "").strip()
    pending_order_id = str(commercial_state.get("pending_order_id") or "").strip()
    last_payment_status = str(commercial_state.get("last_payment_status") or "").strip().replace("_", " ")
    last_billing_event_type = str(commercial_state.get("last_billing_event_type") or "").strip().replace("_", " ")
    last_payment_amount = str(commercial_state.get("last_payment_amount_eur") or "").strip()
    if pending_plan_key and pending_order_id:
        billing_rows.append(
            row_item(
                "Checkout pending",
                f"{pending_plan_key.title()} checkout is waiting for provider confirmation.",
                "Pending",
            )
        )
    elif last_payment_status:
        payment_detail = last_payment_status.title()
        if last_payment_amount:
            payment_detail = f"{payment_detail} | EUR {last_payment_amount}"
        if last_billing_event_type:
            payment_detail = f"{payment_detail} | {last_billing_event_type}"
        billing_rows.append(
            row_item(
                "Latest payment",
                payment_detail,
                "Recorded",
            )
        )
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
            f"{result_cap} results per provider" if result_cap else "",
            f"{match_cap}/100 match ceiling" if match_cap else "",
            f"{str(plan.get('research_depth') or '').strip()} research".strip() if str(plan.get("research_depth") or "").strip() else "",
        ]
        improvement_parts = []
        if platform_cap > current_platform_cap:
            improvement_parts.append(f"+{platform_cap - current_platform_cap} more portals")
        elif platform_cap < current_platform_cap:
            improvement_parts.append(f"{current_platform_cap - platform_cap} fewer platforms, but a tighter working lane")
        if result_cap > current_result_cap:
            improvement_parts.append(f"+{result_cap - current_result_cap} more results per provider")
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
                "Checkout metadata is not loaded yet. The current plan still governs portals, shortlist density, and research depth.",
                "Catalog",
            )
        ]
    billing_decision_rows = [
        row_item(
            "Stay on the current tier",
            "Use the current plan until a real run needs more portals, more ranked homes, or deeper research.",
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
                "Plus buys a denser working shortlist; Agent is the full-depth lane.",
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
    billing_history_rows = []
    billing_events = [
        dict(event)
        for event in list(commercial_state.get("billing_events_json") or [])
        if isinstance(event, dict)
    ]
    invoice_handoffs_by_event = {
        str(row.get("event_id") or "").strip(): dict(row)
        for row in list(commercial.get("invoice_handoffs") or [])
        if isinstance(row, dict) and str(row.get("event_id") or "").strip()
    }
    for event in list(reversed(billing_events))[:5]:
        event_type = str(event.get("event_type") or "billing event").strip().replace("_", " ").replace(".", " ")
        event_status = str(event.get("payment_status") or "").strip().replace("_", " ")
        event_plan = str(event.get("plan_key") or "").strip().title()
        event_amount = str(event.get("amount_eur") or "").strip()
        event_handoff = invoice_handoffs_by_event.get(str(event.get("event_id") or "").strip(), {})
        event_invoice_id = str(event_handoff.get("invoice_id") or event.get("invoice_id") or "").strip()
        event_accounting_status = str(event_handoff.get("state") or event.get("accounting_status") or "").strip().replace("_", " ")
        event_vat = str(event_handoff.get("vat_amount_eur") or event.get("vat_amount_eur") or "").strip()
        event_vat_rate = str(event_handoff.get("vat_rate") or event.get("vat_rate") or "").strip()
        event_when = str(event.get("recorded_at") or "").strip()[:16].replace("T", " ")
        detail_parts = [part for part in (event_status.title(), f"EUR {event_amount}" if event_amount else "", event_when) if part]
        if event_invoice_id:
            detail_parts.append(f"Invoice {event_invoice_id}")
        elif event_accounting_status:
            detail_parts.append(event_accounting_status.title())
        if event_vat:
            detail_parts.append(f"VAT EUR {event_vat}")
        elif event_vat_rate:
            detail_parts.append(f"VAT {event_vat_rate}")
        billing_history_rows.append(
            row_item(
                event_type.title(),
                " | ".join(detail_parts) or "Recorded by the billing webhook.",
                event_plan or "Payment",
            )
        )
    if not billing_history_rows:
        billing_history_rows.append(
            row_item(
                "No payment history yet",
                "Checkout events will appear here after a payment, cancellation, refund, or failed attempt.",
                "History",
            )
        )
    billing_history_rows.extend(
        [
            {
                **row_item(
                    "Cancellation and refunds",
                    "Policy, refund handling, and failed-payment recovery live on the public refund page.",
                    "Policy",
                ),
                "action_href": "/refunds",
                "action_label": "Open policy",
            },
            row_item(
                "Invoice handoff",
                "Payment verification stays in PropertyQuarry; invoice/VAT documents are handled by the accounting lane after receipt.",
                "Invoice",
            ),
        ]
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
                "detail": " | ".join(part for part in detail_parts if part) or "Open the property page to inspect the fit and missing evidence.",
                "tag": str(candidate.get("tag") or candidate.get("recommendation") or "Packet").strip() or "Packet",
                "action_href": str(candidate.get("packet_url") or candidate.get("review_url") or candidate.get("tour_url") or candidate.get("property_url") or "").strip(),
                "action_method": "get",
                "action_label": "Open property page",
                "secondary_action_href": str(candidate.get("review_url") or candidate.get("tour_url") or "").strip(),
                "secondary_action_method": "get" if (candidate.get("review_url") or candidate.get("tour_url")) else "",
                "secondary_action_label": "Open listing" if candidate.get("review_url") else ("Open 360" if candidate.get("tour_url") else ""),
            }
        )
    if not research_rows:
        research_rows = list(recent_matches_card.get("items") or []) or [
            row_item(
                "Research pages have not been opened yet",
                "As soon as a run finishes with credible matches, the strongest candidates will be promoted into hosted property pages from this desk.",
                "First page",
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
            "action_href": "/app/account#delivery",
            "action_method": "get",
            "action_label": "Review delivery",
        },
    ]
    agent_management_rows = build_agent_management_rows(property_search_agents, run_id=run_id)
    if not agent_management_rows:
        agent_management_rows = [
            row_item(
                "No saved search yet",
                "Create one from the search desk, then return here to edit, pause, or review its notification budget.",
                "First search",
            )
        ]
    editable_search_defaults_items = [
        {
            "title": "Search defaults",
            "detail": "Market, areas, providers, budget, and what matters are edited in the Search workflow.",
            "tag": "Editable",
            "action_href": f"/app/search{run_suffix}",
            "action_method": "get",
            "action_label": "Edit search",
        }
    ]

    sections: dict[str, dict[str, object]] = {
        "properties": {
            "title": "Run",
            "summary": (
                "Review the final ranked result table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "Keep health, coverage, repair state, and the next useful update visible while the run is active."
                    if run_in_progress
                    else "This surface is for run health, partial coverage, and the last completed sweep."
                )
            ),
            "hero_kicker": "Run",
            "hero_title": (
                "Review the finished run in one table."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else ("Keep the run visible until the shortlist is ready." if run_in_progress else "No run is active right now.")
            ),
            "hero_summary": (
                "Coverage, pages, repair."
                if run_status_value in {"processed", "completed"} and results_table_rows
                else (
                    "Health, coverage, repair."
                    if run_in_progress
                    else "No active run."
                )
            ),
            "hero_actions": [{"href": f"/app/search{run_suffix}", "label": "Open search"}, {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"}] if run_in_progress else (hero_actions["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"href": f"/app/search{run_suffix}", "label": "Refine search", "tone": "primary"},
                {"href": f"/app/shortlist{run_suffix}", "label": "Open shortlist"},
                {"href": f"/app/agents{run_suffix}", "label": "Automation"},
            ]),
            "hero_highlights": [
                {"label": "Run state", "value": run_status_label, "detail": run_message or "The current live run status."},
                (
                    {
                        "label": "Providers",
                        "value": str(run_provider_display_total),
                        "detail": "Selected providers are checking the chosen areas.",
                    }
                    if run_provider_display_total > 0
                    and run_source_variant_total > run_provider_display_total
                    else {
                        "label": "Search scope",
                        "value": str(run_source_variant_total),
                        "detail": "Selected sources are checking the saved brief.",
                    }
                ),
                {"label": "Listings", "value": str(int(run_summary.get("listing_total") or 0)), "detail": "Listings recovered so far."},
            ] if run_in_progress else (hero_highlights["properties"] if not (run_status_value in {"processed", "completed"} and results_table_rows) else [
                {"label": "Results", "value": str(len(results_table_rows)), "detail": "Final ranked candidates in this run."},
                {"label": "Pages", "value": str(packet_ready_total), "detail": "Hosted property pages ready now."},
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
            "summary": "Use one ranked decision table for the strongest candidates and open the full property page only when a card deserves it.",
            "hero_kicker": "Shortlist",
            "hero_title": "Review the best candidates before you open deeper property pages.",
            "hero_summary": "Ranked candidates first.",
            "hero_actions": hero_actions["shortlist"],
            "hero_highlights": hero_highlights["shortlist"],
            "primary_cards": [
                {
                    "eyebrow": "Decision table",
                    "title": "Compare the top shortlist before you open a single full property page",
                    "body": "",
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
            "summary": "Turn high-fit candidates into property dossiers with evidence, property pages, and hosted follow-ups.",
            "hero_kicker": "Research pages",
            "hero_title": "Inspect the evidence before you open the raw listing.",
            "hero_summary": "This lane should feel like a property dossier desk: fit reasons, decision checks, property pages, and hosted tours where they exist.",
            "hero_actions": hero_actions["research"],
            "hero_highlights": hero_highlights["research"],
            "primary_cards": [
                {
                    "eyebrow": "Research pages",
                    "title": "Open the strongest property pages first",
                    "body": "Hosted property pages and 360 tours stay primary. Raw portal links remain secondary.",
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
            "summary": "Track what has already been delivered and which run events are preparing the next outbound property page.",
            "hero_kicker": "Alerts",
            "hero_title": "See what has been sent and what is about to leave.",
            "hero_summary": "Alerts are product output, not hidden queue state. Keep hosted matches, property pages, and run updates visible in one lane.",
            "hero_actions": hero_actions["alerts"],
            "hero_highlights": hero_highlights["alerts"],
            "primary_cards": [
                {
                    "eyebrow": "Client alerts",
                    "title": "Recent outbound property follow-ups",
                    "body": "Hosted pages, property briefs, and run updates that mattered enough to notify the client.",
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
                {
                    "eyebrow": "Delivery",
                    "title": "Delivery rules",
                    "body": "Outbound channels must stay opt-in, receipted, and quiet-hour aware.",
                    "items": delivery_governance_rows,
                },
                run_card,
            ],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "agents": {
            "title": "Automation",
            "summary": "Edit saved searches, start a fresh sweep, and open recent outcomes.",
            "hero_kicker": "Automation",
            "hero_title": "Saved searches.",
            "hero_summary": f"{sum(1 for agent in property_search_agents if agent.get('enabled'))} active | {len(property_search_agents)} saved.",
            "hero_actions": hero_actions["agents"],
            "hero_highlights": hero_highlights["agents"],
            "primary_cards": [
                {
                    "eyebrow": "Selected watch",
                    "title": str((selected_agent or {}).get("name") or "Open one market watch"),
                    "body": (
                        ""
                        if selected_agent
                        else ""
                    ),
                    "items": (
                        [
                            {
                                "title": "Watching",
                                "detail": str((selected_agent or {}).get("scope_label") or "No scope saved"),
                                "tag": str((selected_agent or {}).get("status_label") or "Idle"),
                                "action_href": selected_agent_open_href or f"/app/agents{run_suffix}",
                                "action_method": "get",
                                "action_label": "Open watch",
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
                    "eyebrow": "Watchlist",
                    "title": "Watchlist",
                    "body": "",
                    "items": agent_management_rows,
                }
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Delivery",
                    "title": "Delivery",
                    "body": "",
                    "items": [
                        row_item("Delivery", str((selected_agent or {}).get("delivery_label") or "Set a daily or weekly delivery cap."), str((selected_agent or {}).get("notification_label") or "Budget")),
                        row_item("Reports", "Daily, weekly, and repair digests can leave through email.", "Email"),
                        row_item(
                            "Latest outcome",
                            (
                                f"Ranked {str((selected_agent_latest_run or {}).get('ranked_total') or 0)} | Sent {str((selected_agent_latest_run or {}).get('sent_total') or 0)} | Filtered {str((selected_agent_latest_run or {}).get('held_back_total') or 0)}"
                                if selected_agent_latest_run
                                else "No finished recurring run has produced a delivery summary yet."
                            ),
                            str((selected_agent_latest_run or {}).get("status_label") or "Waiting"),
                        ),
                    ],
                },
                {
                    "eyebrow": "Repair",
                    "title": "Repair",
                    "body": "",
                    "items": repair_truth_rows + (
                        fleet_digest_items[:2]
                        if fleet_digest_items
                        else [row_item("Repair notes", "Provider retries and repair outcomes will appear here after the next saved-search run.", "Repair")]
                    ),
                },
                {
                    "eyebrow": "Limits",
                    "title": "Limits",
                    "body": "",
                    "items": [
                        row_item("Free", "1 active saved search.", "Plan"),
                        row_item("Plus", "3 active saved searches.", "Plan"),
                        row_item("Agent", "Unlimited saved searches.", "Plan"),
                    ],
                },
                {
                    "eyebrow": "Latest outcomes",
                    "title": "Recent runs",
                    "body": "",
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
            "summary": "Plan, checkout, and the current search allowance.",
            "hero_kicker": "Billing",
            "hero_title": "Your plan.",
            "hero_summary": "Current access, checkout status, and search capacity.",
            "hero_actions": hero_actions["billing"],
            "hero_highlights": hero_highlights["billing"],
            "primary_cards": [
                {
                    "eyebrow": "Plan",
                    "title": "Current search access",
                    "body": "",
                    "items": billing_rows,
                },
                {
                    "eyebrow": "Payment",
                    "title": "Payment",
                    "body": "",
                    "items": [
                        row_item(
                            "Status",
                            "Available" if bool(property_state.get("billing_checkout_enabled")) else "Not active yet",
                            "Status",
                        ),
                        row_item("Change plan", "Upgrade only when a real search hits the current allowance.", "Decision"),
                    ],
                },
            ],
            "secondary_cards": [
                {
                    "eyebrow": "Upgrade",
                    "title": "Tier changes",
                    "body": "",
                    "items": billing_upgrade_rows,
                },
                {
                    "eyebrow": "Decision",
                    "title": "When to upgrade",
                    "body": "",
                    "items": billing_decision_rows,
                },
                {
                    "eyebrow": "History",
                    "title": "Billing history",
                    "body": "",
                    "items": billing_history_rows,
                },
            ],
            "console_form": property_form,
            "show_brief_form": False,
            "show_shortlist_cards": False,
            "show_billing_cards": True,
        },
        "account": {
            "title": "Account",
            "summary": "Identity, plan, delivery, and editable defaults.",
            "hero_kicker": "Account",
            "hero_title": "Account.",
            "hero_summary": "Identity, plan, delivery, and editable defaults.",
            "hero_actions": [],
            "hero_highlights": [
                {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": "/app/account#settings"},
                {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": "/app/account#plans"},
                {"label": "Saved searches", "value": str(len(property_search_agents)), "detail": "Recurring searches ready to rerun or edit.", "href": f"/app/agents{run_suffix}"},
                {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": f"/app/search{run_suffix}"},
            ],
            "primary_cards": [
                {
                    "id": "settings",
                    "eyebrow": "Connections",
                    "title": "Identity and return access",
                    "body": "",
                    "items": preference_rows + settings_connection_rows,
                },
                {
                    "id": "plans",
                    "eyebrow": "Plan",
                    "title": "Current access",
                    "body": "",
                    "items": billing_rows,
                },
                {
                    "id": "profile",
                    "eyebrow": "Saved defaults",
                    "title": "Search defaults",
                    "body": "",
                    "items": editable_search_defaults_items,
                },
                {
                    "id": "delivery",
                    "eyebrow": "Delivery",
                    "title": "Reports and alerts",
                    "body": "",
                    "items": [
                        row_item("Recurring searches", f"{len(property_search_agents)} saved searches ready to rerun or edit.", "Automation"),
                        row_item("Delivery", "Email digests and recurring market watches use your saved-search settings.", "Reports"),
                        row_item("Return access", str(google.get("connected_account_email") or "Sign-in without widening scope."), "Identity"),
                    ],
                },
                {
                    "eyebrow": "Next change",
                    "title": "Edit",
                    "body": "",
                    "items": [
                        row_item("Search", "Change areas, filters, providers, or shortlist depth.", "Search"),
                        row_item("Plan", "Open pricing when the current allowance blocks a real run.", "Plan"),
                        row_item("Security", "Review retention and identity posture.", "Trust"),
                    ],
                },
            ],
            "secondary_cards": [{
                "eyebrow": "Links",
                "title": "Public pages",
                "body": "",
                "items": [
                    {
                        "title": "Security",
                        "detail": "Review trust and data posture.",
                        "tag": "Public",
                        "action_href": "/security",
                        "action_method": "get",
                        "action_label": "Open security",
                    },
                ],
            }],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
        "settings": {
            "title": "Account",
            "summary": "Identity, plan, delivery, and editable defaults.",
            "hero_kicker": "Account",
            "hero_title": "Account.",
            "hero_summary": "Identity, plan, delivery, and editable defaults.",
            "hero_actions": [
                {"href": f"/app/search{run_suffix}", "label": "Edit search", "tone": "primary"},
                {"href": f"/app/agents{run_suffix}", "label": "Saved searches"},
                {"href": "/pricing", "label": "Open pricing"},
            ],
            "hero_highlights": [
                {"label": "Identity", "value": "Google" if str(google.get("connected_account_email") or "").strip() else "Local", "detail": str(google.get("connected_account_email") or "Sign-in without widening scope."), "href": "/app/account#settings"},
                {"label": "Plan", "value": current_plan_label, "detail": str(commercial.get("research_depth") or "deep") + " research", "href": "/app/account#plans"},
                {"label": "Saved searches", "value": str(len(property_search_agents)), "detail": "Recurring searches ready to rerun or edit.", "href": f"/app/agents{run_suffix}"},
                {"label": "Areas", "value": str(len(selected_locations) or 0), "detail": ", ".join(selected_locations[:2]) or "Saved search areas.", "href": f"/app/search{run_suffix}"},
            ],
            "primary_cards": [
                {
                    "id": "settings",
                    "eyebrow": "Connections",
                    "title": "Identity and return access",
                    "body": "",
                    "items": preference_rows + settings_connection_rows,
                },
                {
                    "id": "profile",
                    "eyebrow": "Saved defaults",
                    "title": "Search defaults",
                    "body": "",
                    "items": editable_search_defaults_items,
                },
                {
                    "eyebrow": "Next change",
                    "title": "Edit",
                    "body": "",
                    "items": [
                        row_item("Search brief", "Go back to Search when the market, provider mix, or shortlist depth needs adjustment.", "Search"),
                        row_item("Plan", "Open pricing when the current allowance blocks a real run.", "Plan"),
                        row_item("Security", "Review retention and identity posture.", "Trust"),
                    ],
                },
            ],
            "secondary_cards": [billing_rows and {
                "id": "plans",
                "eyebrow": "Plan",
                "title": "Plan access",
                "body": "",
                "items": billing_rows,
            } or {}, {
                "eyebrow": "Links",
                "title": "Public pages",
                "body": "",
                "items": [
                    {
                        "title": "Pricing",
                        "detail": "Compare tiers.",
                        "tag": "Public",
                        "action_href": "/pricing",
                        "action_method": "get",
                        "action_label": "Open pricing",
                    },
                    {
                        "title": "Security",
                        "detail": "Review trust and data posture.",
                        "tag": "Public",
                        "action_href": "/security",
                        "action_method": "get",
                        "action_label": "Open security",
                    },
                ],
            }],
            "console_form": {},
            "show_brief_form": False,
            "show_shortlist_cards": False,
        },
    }

    payload = dict(sections.get(section, sections["properties"]))
    payload["account_status"] = dict(status or {})
    shortlist_snapshot = build_property_shortlist_snapshot(
        workbench_results,
        selected_candidate_ref=selected_candidate_ref,
    )
    workbench_results = [dict(row) for row in list(shortlist_snapshot.get("results") or []) if isinstance(row, dict)]
    selected_result = dict(shortlist_snapshot.get("selected") or {})
    run_health_summary = dict(run_health or {})
    workbench_filtered_total = int(
        run_health_summary.get("filtered_total")
        or run_health_summary.get("held_back_total")
        or run_summary.get("filtered_total")
        or run_summary.get("held_back_total")
        or 0
    )
    if workbench_filtered_total <= 0 and suppression_rows:
        workbench_filtered_total = sum(
            max(int(float((row or {}).get("affected_total") or 0)), 0)
            for row in suppression_rows
            if isinstance(row, dict) and (row.get("rule_key") or "").strip() != "Below fit threshold"
        )
    workbench_score_demoted_total = int(
        run_health_summary.get("score_demoted_total")
        or run_health_summary.get("filtered_low_fit_total")
        or run_summary.get("score_demoted_total")
        or run_summary.get("filtered_low_fit_total")
        or 0
    )
    workbench_held_back_total = int(
        run_health_summary.get("held_back_total")
        or run_summary.get("held_back_total")
        or workbench_filtered_total
        or 0
    )
    decision_workbench = PropertyDecisionWorkbenchContract(
        run=PropertyDecisionWorkbenchRunContract(
            run_id=run_id,
            status=run_status_value or "not_started",
            status_label=run_status_label,
            progress=int(run_health.get("progress") or run_payload.get("progress") or 0),
            message=run_status_note or run_message,
            status_url=str(run_health.get("status_url") or run_payload.get("status_url") or "").strip(),
            filtered_total=workbench_filtered_total,
            score_demoted_total=workbench_score_demoted_total,
            held_back_total=workbench_held_back_total,
            summary=run_summary_for_surface,
            events=run_events[-8:],
            worker_state=search_worker_state,
            reliability=_property_run_reliability_summary(
                {
                    "status": run_status_value or "not_started",
                    "progress": int(run_health.get("progress") or run_payload.get("progress") or 0),
                    "message": run_status_note or run_message,
                    "eta_label": str(run_health.get("eta_label") or run_payload.get("eta_label") or "").strip(),
                    "summary": run_summary_for_surface,
                },
                results_total=int(shortlist_snapshot.get("results_total") or len(workbench_results)),
            ),
            research_task_total=research_task_total,
            open_research_task_total=open_research_task_total,
            filled_research_task_total=filled_research_task_total,
            dismissed_research_task_total=dismissed_research_task_total,
            provider_display_total=run_provider_display_total,
            source_variant_display_total=run_source_variant_total,
            selected_platform_count=len(selected_platforms),
            route_previews=progress_route_previews,
        ),
        brief=PropertyDecisionWorkbenchBriefContract(
            country=str(property_state.get("country_label") or "Market"),
            search_goal=selected_search_goal,
            search_goal_label=property_search_goal_label,
            mode=mode_visibility_label,
            investment_strategy_label=property_investment_strategy_label if property_is_investment_search else "",
            region=str(property_state.get("region_label") or property_preferences.get("region_code") or "").strip(),
            areas=selected_locations,
            priorities=selected_keywords,
            providers=selected_platforms,
            plan=current_plan_label,
            plan_key=str(commercial.get("current_plan_key") or "free").strip().lower() or "free",
            research_depth=str(commercial.get("research_depth") or "deep").strip(),
        ),
        brief_preferences=brief_preferences_payload,
        endpoints={
            "preferences": str(property_meta.get("preferences_endpoint") or "").strip(),
            "start": str(property_meta.get("start_endpoint") or "").strip(),
            "billing_order": str(property_meta.get("billing_order_endpoint") or "").strip(),
            "delete_run_template": "/app/api/property/search-runs/__RUN_ID__",
        },
        counterfactual_rows=counterfactual_rows,
        recent_packets=[
            {
                "title": str(item.get("title") or item.get("label") or "Property page").strip(),
                "detail": str(item.get("detail") or "").strip(),
                "tag": str(item.get("tag") or "Packet").strip(),
                "url": str(item.get("action_href") or "").strip(),
            }
            for item in list(recent_matches_card.get("items") or [])[:5]
            if isinstance(item, dict)
        ],
        previous_search_runs=[] if normalized_section == "search" else previous_search_runs,
        search_agents=[] if normalized_section == "search" else property_search_agents,
        search_agent={} if normalized_section == "search" else property_search_agent,
        results=workbench_results,
        search_guard_rows=[],
        suppression_rows=suppression_rows,
        delivery_proof_rows=delivery_proof_rows,
        artifact_receipt_rows=artifact_receipt_rows,
        research_tasks=[],
        research_task_counts={
            "total": research_task_total,
            "open": open_research_task_total,
            "filled": filled_research_task_total,
            "dismissed": dismissed_research_task_total,
        },
        selected_candidate_ref=str(shortlist_snapshot.get("selected_candidate_ref") or selected_result.get("candidate_ref") or "").strip(),
        selected=selected_result,
        empty_outcome=build_property_empty_outcome_summary(
            run_summary=run_summary,
            run_sources=run_sources,
            run_status_value=run_status_value,
            run_message=run_message,
            counterfactual_rows=counterfactual_rows,
            suppression_rows=suppression_rows,
        ),
        packet_recovery=packet_recovery,
        show_brief_default=not (run_in_progress or (run_status_value in {"processed", "completed"} and bool(shortlist_snapshot.get("has_results")))),
    )
    contract = PropertySurfacePayloadContract(
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        stats=list(base.get("stats") or []),
        current_plan_label=current_plan_label,
        run_payload=run_payload_for_surface,
        run_summary=run_summary_for_surface,
        preference_manager=preference_manager,
        decision_workbench=decision_workbench,
        extras={
            key: value
            for key, value in payload.items()
            if key not in {"title", "summary"}
        },
    )
    return contract.to_dict()
