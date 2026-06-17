from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceRef:
    ref_id: str
    label: str
    href: str = ""
    source_type: str = ""
    note: str = ""


@dataclass(frozen=True)
class PolicyGate:
    gate_id: str
    label: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class HistoryEntry:
    event_type: str
    created_at: str | None = None
    source_id: str = ""
    actor: str = ""
    detail: str = ""


@dataclass(frozen=True)
class BriefItem:
    id: str
    workspace_id: str
    kind: str
    title: str
    summary: str
    score: float
    why_now: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    related_people: tuple[str, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    recommended_action: str = ""
    status: str = "open"
    confidence: float = 0.0
    object_ref: str = ""
    profile_followup_refs: tuple[str, ...] = ()
    evidence_count: int = 0


@dataclass(frozen=True)
class DecisionQueueItem:
    id: str
    queue_kind: str
    title: str
    summary: str
    priority: str
    rank_score: float = 0.0
    deadline: str | None = None
    owner_role: str = ""
    requires_principal: bool = False
    evidence_refs: tuple[EvidenceRef, ...] = ()
    profile_followup_refs: tuple[str, ...] = ()
    resolution_state: str = "open"


@dataclass(frozen=True)
class CommitmentItem:
    id: str
    source_type: str
    source_ref: str
    statement: str
    owner: str
    counterparty: str
    due_at: str | None
    status: str
    last_activity_at: str | None
    risk_level: str
    proof_refs: tuple[EvidenceRef, ...] = ()
    confidence: float = 0.5
    channel_hint: str = ""
    resolution_code: str = ""
    resolution_reason: str = ""
    duplicate_of_ref: str = ""
    merged_into_ref: str = ""
    merged_from_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftCandidate:
    id: str
    thread_ref: str
    recipient_summary: str
    intent: str
    draft_text: str
    tone: str
    requires_approval: bool
    approval_status: str
    provenance_refs: tuple[EvidenceRef, ...] = ()
    send_channel: str = ""


@dataclass(frozen=True)
class DecisionItem:
    id: str
    title: str
    summary: str
    priority: str
    owner_role: str
    due_at: str | None
    status: str
    decision_type: str = ""
    recommendation: str = ""
    next_action: str = ""
    rationale: str = ""
    options: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    linked_thread_ids: tuple[str, ...] = ()
    related_people: tuple[str, ...] = ()
    impact_summary: str = ""
    sla_status: str = ""
    resolution_reason: str = ""


@dataclass(frozen=True)
class DeadlineItem:
    id: str
    title: str
    summary: str
    priority: str
    start_at: str | None
    end_at: str | None
    status: str


@dataclass(frozen=True)
class ThreadItem:
    id: str
    title: str
    channel: str
    status: str
    last_activity_at: str | None
    summary: str
    counterparties: tuple[str, ...] = ()
    draft_ids: tuple[str, ...] = ()
    related_commitment_ids: tuple[str, ...] = ()
    related_decision_ids: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class CommitmentCandidate:
    title: str
    details: str
    source_text: str
    confidence: float
    suggested_due_at: str | None = None
    counterparty: str = ""
    channel_hint: str = ""
    source_ref: str = ""
    signal_type: str = ""
    status: str = "pending"
    candidate_id: str = ""
    kind: str = "commitment"
    stakeholder_id: str = ""
    duplicate_of_ref: str = ""
    merge_strategy: str = "create"


@dataclass(frozen=True)
class PersonProfile:
    id: str
    display_name: str
    role_or_company: str
    importance_score: int
    relationship_temperature: str
    open_loops_count: int
    latest_touchpoint_at: str | None
    preferred_tone: str
    themes: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonDetail:
    profile: PersonProfile
    commitments: tuple[CommitmentItem, ...] = ()
    drafts: tuple[DraftCandidate, ...] = ()
    threads: tuple[ThreadItem, ...] = ()
    queue_items: tuple[DecisionQueueItem, ...] = ()
    handoffs: tuple[HandoffNote, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    history: tuple[HistoryEntry, ...] = ()


@dataclass(frozen=True)
class HandoffNote:
    id: str
    queue_item_ref: str
    summary: str
    owner: str
    due_time: str | None
    escalation_status: str
    status: str = "open"
    task_type: str = ""
    resolution: str = ""
    draft_ref: str = ""
    recipient_email: str = ""
    subject: str = ""
    delivery_reason: str = ""
    evidence_refs: tuple[EvidenceRef, ...] = ()
    property_url: str = ""
    listing_id: str = ""
    variant_key: str = ""
    blocked_reason: str = ""
    tour_url: str = ""
    connector_binding_id: str = ""
    vendor_tour_url: str = ""
    editor_url: str = ""
    source_ref: str = ""
    external_id: str = ""


@dataclass(frozen=True)
class PropertySearchRunSnapshot:
    run_id: str
    status: str
    summary: dict[str, object] = field(default_factory=dict)
    property_search_preferences: dict[str, object] = field(default_factory=dict)
    active_search_agent_id: str = ""
    updated_at: str = ""
    generated_at: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PropertySearchRunSnapshot":
        payload = dict(value or {})
        preferences = payload.get("property_search_preferences") or payload.get("preferences") or {}
        summary = payload.get("summary") or {}
        return cls(
            run_id=str(payload.get("run_id") or "").strip(),
            status=str(payload.get("status") or dict(summary).get("status") or "").strip(),
            summary=dict(summary) if isinstance(summary, dict) else {},
            property_search_preferences=dict(preferences) if isinstance(preferences, dict) else {},
            active_search_agent_id=str(
                payload.get("active_search_agent_id")
                or (preferences.get("active_search_agent_id") if isinstance(preferences, dict) else "")
                or ""
            ).strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
            generated_at=str(payload.get("generated_at") or "").strip(),
            message=str(payload.get("message") or (summary.get("message") if isinstance(summary, dict) else "") or "").strip(),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyRunHealthSnapshot:
    run_id: str
    status: str
    status_label: str
    status_note: str
    message: str
    progress: int
    status_url: str
    eta_label: str
    in_progress: bool
    source_total: int
    listing_total: int
    filtered_total: int
    held_back_total: int
    research_task_total: int = 0
    open_research_task_total: int = 0
    filled_research_task_total: int = 0
    dismissed_research_task_total: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyRunRepairSnapshot:
    repair_status: str
    repair_status_label: str
    repair_step_label: str
    repair_outcome_summary: str
    repair_class: str = ""
    repair_attempt_count: int = 0
    eta_confidence_label: str = "Unknown"
    next_useful_update_eta_label: str = ""
    can_auto_repair: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyRunReliabilitySnapshot:
    health_label: str
    health_tone: str
    coverage_label: str
    result_label: str
    filtered_label: str
    repair_step_label: str
    next_useful_update_eta_label: str
    final_eta_label: str
    eta_confidence_label: str
    customer_status_message: str
    repair: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyShortlistSnapshot:
    results: list[dict[str, object]] = field(default_factory=list)
    selected: dict[str, object] = field(default_factory=dict)
    selected_candidate_ref: str = ""
    results_total: int = 0
    has_results: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertySearchAgentSelectionSnapshot:
    selected_agent: dict[str, object] = field(default_factory=dict)
    selected_agent_id: str = ""
    selected_agent_runs: list[dict[str, object]] = field(default_factory=list)
    selected_agent_latest_run: dict[str, object] = field(default_factory=dict)
    selected_agent_open_href: str = ""
    selected_agent_edit_href: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyPreferenceManagerSnapshot:
    person_id: str
    nodes: list[dict[str, object]] = field(default_factory=list)
    active_nodes: list[dict[str, object]] = field(default_factory=list)
    schema: dict[str, object] = field(default_factory=dict)
    bundle_endpoint: str = ""
    node_endpoint: str = ""
    archive_endpoint_template: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertySearchFormStateSnapshot:
    selected_country_code: str
    selected_search_goal: str
    selected_listing_mode: str
    selected_investment_strategy: str
    selected_investment_research_mode: str
    property_is_investment_search: bool
    selected_school_stage_preferences: list[str] = field(default_factory=list)
    school_evidence_controls_enabled: bool = False
    show_investment_underwriting_controls: bool = False
    show_lifestyle_research_controls: bool = False
    show_community_validation_controls: bool = False
    show_developer_project_stage_controls: bool = False
    show_public_housing_policy_controls: bool = False
    show_distressed_review_controls: bool = False
    show_search_agent_detail_controls: bool = False
    show_preference_profile_controls: bool = True
    show_school_quality_priority_controls: bool = False
    show_playground_importance_controls: bool = False
    show_library_importance_controls: bool = False
    show_supermarket_importance_controls: bool = False
    min_gross_yield_pct: int = 0
    equity_available_eur: int = 0
    loan_term_years: int = 25
    max_interest_rate_pct: int = 0
    min_dscr: float = 0.0
    vacancy_reserve_pct: int = 4
    capex_reserve_pct: int = 6

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyWorkbenchCandidateSnapshot:
    candidate_ref: str
    rank: int
    title: str
    source_label: str
    location_label: str
    price_display: str
    costs_display: str
    price_per_sqm_display: str
    layout_display: str
    layout_verification_label: str
    fit_score: int
    fit_label: str
    fit_summary: str
    tour: dict[str, object] = field(default_factory=dict)
    flythrough: dict[str, object] = field(default_factory=dict)
    orientation_preview: dict[str, object] = field(default_factory=dict)
    ooda: dict[str, object] = field(default_factory=dict)
    risk: dict[str, object] = field(default_factory=dict)
    investment: dict[str, object] = field(default_factory=dict)
    match_reasons: list[str] = field(default_factory=list)
    mismatch_reasons: list[str] = field(default_factory=list)
    review_page_neuronwriter: dict[str, object] = field(default_factory=dict)
    packet_url: str = ""
    review_url: str = ""
    property_url: str = ""
    map_url: str = ""
    source_url: str = ""
    floorplan_url: str = ""
    property_facts: dict[str, object] = field(default_factory=dict)
    assessment: dict[str, object] = field(default_factory=dict)
    objection_rows: list[dict[str, str]] = field(default_factory=list)
    timeline_rows: list[dict[str, str]] = field(default_factory=list)
    household_rows: list[dict[str, str]] = field(default_factory=list)
    risk_signal_rows: list[dict[str, str]] = field(default_factory=list)
    followup_rows: list[dict[str, str]] = field(default_factory=list)
    recent_change_rows: list[dict[str, str]] = field(default_factory=list)
    official_evidence_rows: list[dict[str, str]] = field(default_factory=list)
    official_posture_rows: list[dict[str, str]] = field(default_factory=list)
    object_rows: list[dict[str, str]] = field(default_factory=list)
    cost_rows: list[dict[str, str]] = field(default_factory=list)
    feature_values: list[dict[str, str]] = field(default_factory=list)
    description_text: str = ""
    location_text: str = ""
    energy_rows: list[dict[str, str]] = field(default_factory=list)
    household_alignment_score: int = 0
    household_alignment_label: str = "waiting"
    recovered_by_filter: bool = False
    relaxed_filter_label: str = ""
    preview_image_url: str = ""
    repair_flag_label: str = ""
    repair_flag_detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyRecurringWatchSnapshot:
    agent_id: str
    name: str
    enabled: bool
    is_active: bool
    status_label: str
    duration_days: int
    duration_label: str
    notification_limit: int
    notification_period: str
    notification_period_label: str
    location_query: str
    listing_mode: str
    country_code: str
    region_code: str
    property_type: str
    provider_count: int
    last_run_label: str
    next_run_label: str
    sent_in_current_window: int
    remaining_notifications: int
    area_label: str
    scope_label: str
    scope_preview: dict[str, object] = field(default_factory=dict)
    notification_label: str = ""
    run_label: str = ""
    delivery_label: str = ""
    load_payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyRunLiveBoardSnapshot:
    provider_label: str
    provider_full_label: str
    fraction_label: str
    phase_label: str
    aggregate_label: str
    summary_label: str
    source_count_label: str
    source_chips: list[dict[str, object]] = field(default_factory=list)
    worker_lanes: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyBillingTruthSnapshot:
    current_plan_label: str
    current_plan_key: str
    research_depth: str
    max_platforms: int
    max_results_per_source: int
    checkout_provider: str = ""
    checkout_provider_label: str = ""
    checkout_enabled: bool = False
    checkout_enabled_plans: tuple[str, ...] = ()
    order_endpoint: str = ""
    order_endpoints_by_plan: dict[str, str] = field(default_factory=dict)
    provider_labels_by_plan: dict[str, str] = field(default_factory=dict)
    fleet_digest: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PropertyResearchPacketSnapshot:
    research_title: str
    research_summary: str
    research_source_label: str
    research_price: str
    research_area: str
    research_rooms: str
    research_location: str
    research_media: dict[str, object] = field(default_factory=dict)
    research_preview_image: dict[str, object] = field(default_factory=dict)
    research_gallery_items: list[dict[str, object]] = field(default_factory=list)
    research_location_preview: dict[str, object] = field(default_factory=dict)
    research_actions: list[dict[str, object]] = field(default_factory=list)
    research_visual_status_line: str = ""
    research_source_ref: str = ""
    research_run_id: str = ""
    research_candidate_ref: str = ""
    research_overview_rows: list[dict[str, object]] = field(default_factory=list)
    research_sections: list[dict[str, object]] = field(default_factory=list)
    research_match_reasons: list[str] = field(default_factory=list)
    research_mismatch_reasons: list[str] = field(default_factory=list)
    research_listing_rows: list[dict[str, object]] = field(default_factory=list)
    research_cost_rows: list[dict[str, object]] = field(default_factory=list)
    research_feature_values: list[dict[str, object]] = field(default_factory=list)
    research_description_text: str = ""
    research_location_text: str = ""
    research_energy_rows: list[dict[str, object]] = field(default_factory=list)
    research_missing_rows: list[dict[str, object]] = field(default_factory=list)
    research_decision_rows: list[dict[str, object]] = field(default_factory=list)
    research_compare_rows: list[dict[str, object]] = field(default_factory=list)
    research_compare_table_rows: list[object] = field(default_factory=list)
    research_compare_headers: list[str] = field(default_factory=list)
    research_official_evidence_rows: list[dict[str, object]] = field(default_factory=list)
    research_official_posture_rows: list[dict[str, object]] = field(default_factory=list)
    research_future_research_rows: list[dict[str, object]] = field(default_factory=list)
    research_provenance_rows: list[dict[str, object]] = field(default_factory=list)
    research_timeline_rows: list[dict[str, object]] = field(default_factory=list)
    research_everyday_fit_rows: list[dict[str, object]] = field(default_factory=list)
    research_risk_fit_rows: list[dict[str, object]] = field(default_factory=list)
    research_investment_rows: list[dict[str, object]] = field(default_factory=list)
    research_investment_risk_rows: list[dict[str, object]] = field(default_factory=list)
    research_next_best_question: str = ""
    research_feedback: dict[str, object] = field(default_factory=dict)
    research_neuronwriter: dict[str, object] = field(default_factory=dict)
    research_objection_rows: list[dict[str, object]] = field(default_factory=list)
    research_household_rows: list[dict[str, object]] = field(default_factory=list)
    research_risk_signal_rows: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    label: str
    source_type: str
    summary: str
    href: str = ""
    related_object_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleItem:
    id: str
    label: str
    scope: str
    status: str
    summary: str
    current_value: str
    impact: str
    requires_approval: bool = False
    simulated_effect: str = ""


@dataclass(frozen=True)
class ProductSnapshot:
    brief_items: tuple[BriefItem, ...] = field(default_factory=tuple)
    queue_items: tuple[DecisionQueueItem, ...] = field(default_factory=tuple)
    commitments: tuple[CommitmentItem, ...] = field(default_factory=tuple)
    recently_closed_commitments: tuple[CommitmentItem, ...] = field(default_factory=tuple)
    commitment_candidates: tuple[CommitmentCandidate, ...] = field(default_factory=tuple)
    drafts: tuple[DraftCandidate, ...] = field(default_factory=tuple)
    decisions: tuple[DecisionItem, ...] = field(default_factory=tuple)
    threads: tuple[ThreadItem, ...] = field(default_factory=tuple)
    people: tuple[PersonProfile, ...] = field(default_factory=tuple)
    handoffs: tuple[HandoffNote, ...] = field(default_factory=tuple)
    completed_handoffs: tuple[HandoffNote, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    rules: tuple[RuleItem, ...] = field(default_factory=tuple)
    stats_json: dict[str, int] = field(default_factory=dict)
