from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PropertySurfaceName = Literal[
    "properties",
    "search",
    "shortlist",
    "agents",
    "billing",
    "account",
    "settings",
]


@dataclass(frozen=True)
class PropertySurfaceScope:
    section: PropertySurfaceName
    wants_run_state: bool
    wants_recent_runs: bool
    wants_recent_matches: bool
    wants_preference_profile: bool
    wants_learning_summary: bool
    wants_search_runs: bool
    wants_agent_views: bool
    wants_credit_digest: bool
    wants_run_views: bool

    @classmethod
    def for_section(cls, section: str) -> "PropertySurfaceScope":
        normalized = str(section or "properties").strip().lower() or "properties"
        if normalized not in {"properties", "search", "shortlist", "agents", "billing", "account", "settings"}:
            normalized = "properties"
        return cls(
            section=normalized,  # type: ignore[arg-type]
            wants_run_state=normalized in {"properties", "search", "shortlist", "agents"},
            wants_recent_runs=normalized in {"properties", "search", "shortlist", "agents"},
            wants_recent_matches=normalized in {"shortlist"},
            wants_preference_profile=normalized in {"account"},
            wants_learning_summary=False,
            wants_search_runs=normalized in {"search", "shortlist", "agents"},
            wants_agent_views=normalized == "agents",
            wants_credit_digest=normalized in {"billing"},
            wants_run_views=normalized in {"properties", "search", "shortlist", "agents"},
        )


@dataclass(frozen=True)
class PropertyDecisionWorkbenchRunContract:
    run_id: str
    status: str
    status_label: str
    progress: int
    message: str
    status_url: str
    summary: dict[str, object]
    filtered_total: int = 0
    held_back_total: int = 0
    events: list[object] = field(default_factory=list)
    worker_state: list[object] = field(default_factory=list)
    reliability: dict[str, object] = field(default_factory=dict)
    research_task_total: int = 0
    open_research_task_total: int = 0
    filled_research_task_total: int = 0
    dismissed_research_task_total: int = 0
    route_previews: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class PropertyDecisionWorkbenchBriefContract:
    country: str
    search_goal: str
    search_goal_label: str
    mode: str
    investment_strategy_label: str
    region: str
    areas: list[str] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    plan: str = ""
    plan_key: str = "free"
    research_depth: str = "deep"


@dataclass(frozen=True)
class PropertyDecisionWorkbenchContract:
    run: PropertyDecisionWorkbenchRunContract
    brief: PropertyDecisionWorkbenchBriefContract
    brief_preferences: dict[str, object] = field(default_factory=dict)
    endpoints: dict[str, object] = field(default_factory=dict)
    counterfactual_rows: list[object] = field(default_factory=list)
    recent_packets: list[object] = field(default_factory=list)
    previous_search_runs: list[object] = field(default_factory=list)
    search_agents: list[object] = field(default_factory=list)
    search_agent: dict[str, object] = field(default_factory=dict)
    results: list[object] = field(default_factory=list)
    search_guard_rows: list[object] = field(default_factory=list)
    suppression_rows: list[object] = field(default_factory=list)
    delivery_proof_rows: list[object] = field(default_factory=list)
    artifact_receipt_rows: list[object] = field(default_factory=list)
    research_tasks: list[object] = field(default_factory=list)
    research_task_counts: dict[str, object] = field(default_factory=dict)
    selected_candidate_ref: str = ""
    selected: dict[str, object] = field(default_factory=dict)
    empty_outcome: dict[str, str] = field(default_factory=dict)
    show_brief_default: bool = True


@dataclass(frozen=True)
class PropertySurfacePayloadContract:
    title: str
    summary: str
    stats: list[object] = field(default_factory=list)
    current_plan_label: str = ""
    run_payload: dict[str, object] = field(default_factory=dict)
    run_summary: dict[str, object] = field(default_factory=dict)
    preference_manager: dict[str, object] = field(default_factory=dict)
    decision_workbench: PropertyDecisionWorkbenchContract | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        extras = dict(payload.pop("extras", {}) or {})
        if payload.get("decision_workbench") is None:
            payload.pop("decision_workbench", None)
        payload.update(extras)
        return payload
