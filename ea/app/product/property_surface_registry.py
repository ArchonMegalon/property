from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SurfaceGroup = Literal[
    "public_acquisition",
    "auth_handoff",
    "authenticated_app",
    "results_research",
    "shared_public_artifacts",
    "generated_artifacts",
    "delivery",
    "management",
    "system_states",
]


AUDIT_AXES: tuple[str, ...] = (
    "navigation",
    "copy",
    "layout_density",
    "responsive_layout",
    "loading_state",
    "empty_state",
    "error_state",
    "clickability",
    "accessibility",
    "performance",
    "privacy",
    "analytics",
)


ACCEPTANCE_GATES: tuple[str, ...] = (
    "route_ownership",
    "clickable_controls_do_real_work",
    "premium_visual_density_and_responsive_layout",
    "loading_empty_degraded_failed_and_repairing_states",
    "privacy_and_tenancy_boundary",
    "performance_budget",
    "seo_and_optimizer_boundary",
    "analytics_without_private_payloads",
    "accessibility_and_keyboard_flow",
    "regression_proof",
)


PROOF_TYPES: tuple[str, ...] = (
    "unit_contract",
    "browser_smoke",
    "screenshot",
    "link_crawl",
    "privacy_fixture",
    "performance_probe",
    "live_smoke_when_route_is_public",
)


@dataclass(frozen=True)
class PropertySurface:
    key: str
    group: SurfaceGroup
    label: str
    routes: tuple[str, ...]
    templates: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    clickrank_allowed: bool = False
    neuronwriter_allowed: bool = False
    customer_visible: bool = True
    required_gates: tuple[str, ...] = ACCEPTANCE_GATES
    proof_types: tuple[str, ...] = ("unit_contract",)


PROPERTY_SURFACES: tuple[PropertySurface, ...] = (
    PropertySurface(
        key="public_home",
        group="public_acquisition",
        label="Public home",
        routes=("/", "/?home=1"),
        templates=("propertyquarry_home.html", "base_public.html"),
        clickrank_allowed=True,
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="public_pricing",
        group="public_acquisition",
        label="Pricing",
        routes=("/pricing",),
        templates=("pricing_page.html", "base_public.html"),
        clickrank_allowed=True,
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="public_trust",
        group="public_acquisition",
        label="Trust, security, and legal pages",
        routes=("/security", "/privacy", "/terms", "/imprint", "/cookies", "/subprocessors", "/support"),
        templates=("security_page.html", "docs_page.html", "base_public.html"),
        clickrank_allowed=True,
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="public_docs_guides",
        group="public_acquisition",
        label="Docs, integrations, guides, and market pages",
        routes=(
            "/docs",
            "/integrations",
            "/integrations/:channel_name",
            "/guides/wohnung-kaufen-wien-checkliste",
            "/markets/vienna",
        ),
        templates=("docs_page.html", "integrations_page.html", "public_editorial_page.html", "base_public.html"),
        clickrank_allowed=True,
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="registration",
        group="auth_handoff",
        label="Registration",
        routes=("/register", "/get-started"),
        templates=("register.html", "base_public.html"),
    ),
    PropertySurface(
        key="sign_in",
        group="auth_handoff",
        label="Sign in and active sign-in handoff",
        routes=("/sign-in", "/workspace-link", "/google/connected", "/app/api/property/landing-handoff"),
        templates=("sign_in.html", "workspace_link.html", "google_connected.html", "propertyquarry_home.html"),
    ),
    PropertySurface(
        key="app_shell",
        group="authenticated_app",
        label="Authenticated shell and navigation",
        routes=("/app", "/app/properties", "/app/search", "/app/shortlist", "/app/agents", "/app/account"),
        templates=("base_console.html", "app/property_decision_workbench.html"),
    ),
    PropertySurface(
        key="search_wizard",
        group="authenticated_app",
        label="Search wizard",
        routes=("/app/search",),
        templates=("app/property_decision_workbench.html", "app/_property_workbench_script.html"),
    ),
    PropertySurface(
        key="what_matters",
        group="authenticated_app",
        label="What matters controls",
        routes=("/app/search#what-matters",),
        templates=("app/property_decision_workbench.html", "app/_property_workbench_script.html"),
    ),
    PropertySurface(
        key="run_home",
        group="authenticated_app",
        label="Run home and progress",
        routes=("/app/properties", "/app/properties?run_id=:run_id"),
        templates=("app/property_decision_workbench.html", "app/_property_running_panel.html"),
    ),
    PropertySurface(
        key="shortlist",
        group="results_research",
        label="Ranked shortlist and filtered breakdown",
        routes=("/app/shortlist", "/app/shortlist?run_id=:run_id"),
        templates=("app/property_decision_workbench.html", "app/_property_results_list.html"),
    ),
    PropertySurface(
        key="property_research_detail",
        group="results_research",
        label="Property research detail",
        routes=("/app/research/:candidate_ref",),
        templates=("app/property_research_detail.html", "app/_property_selected_review_panel.html"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="agents",
        group="authenticated_app",
        label="Saved searches and automation",
        routes=("/app/agents", "/app/automations"),
        templates=("app/property_decision_workbench.html", "app/_property_search_agents_panel.html"),
    ),
    PropertySurface(
        key="account",
        group="authenticated_app",
        label="Account, profile, data, and delivery settings",
        routes=("/app/account", "/app/account#profile", "/app/account#delivery", "/app/profile", "/app/alerts"),
        templates=("app/property_decision_workbench.html", "app/_property_account_panel.html"),
    ),
    PropertySurface(
        key="billing",
        group="authenticated_app",
        label="Billing and plan controls",
        routes=("/app/account#plans", "/app/billing"),
        templates=("app/property_decision_workbench.html", "app/_property_billing_panel.html"),
    ),
    PropertySurface(
        key="public_results",
        group="shared_public_artifacts",
        label="Public redacted result pages",
        routes=("/results/:slug", "/results/:slug.json", "/results/files/:slug/:asset"),
        clickrank_allowed=False,
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="public_packet",
        group="shared_public_artifacts",
        label="Public packet share",
        routes=("/v1/integrations/fliplink/documents/property-packets/:token", "/app/properties/packets"),
        templates=("app/property_packets.html",),
        artifacts=("redacted packet manifest", "packet PDF"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="public_tour",
        group="shared_public_artifacts",
        label="Public 3D tour share",
        routes=("/tours/:slug", "/tours/:slug.json", "/tours/files/:slug/:asset"),
        artifacts=("public tour manifest", "tour assets"),
    ),
    PropertySurface(
        key="premium_dossier",
        group="generated_artifacts",
        label="Premium dossier PDF",
        routes=("/app/api/properties/packets/:publication_id/pdf",),
        artifacts=("premium dossier HTML", "premium dossier PDF", "appendix PDF"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="floorplan_and_tour_control",
        group="generated_artifacts",
        label="Floorplan, Matterport, 3DVista, and local tour controls",
        routes=(
            "/app/research/:candidate_ref#tour",
            "/app/api/signals/willhaben/property-tour",
            "/tours/:slug/control",
            "/tours/:slug/control/:viewer_mode",
        ),
        artifacts=("floorplan asset", "tour receipt", "walkthrough receipt"),
    ),
    PropertySurface(
        key="video_walkthrough",
        group="generated_artifacts",
        label="Video walkthrough request and status",
        routes=(
            "/app/research/:candidate_ref#walkthrough",
            "/app/api/property-video/requests/dadan",
            "/v1/integrations/dadan/webhooks/recording-submitted",
        ),
        artifacts=("Dadan request", "video receipt"),
    ),
    PropertySurface(
        key="email_delivery",
        group="delivery",
        label="Email alerts and digests",
        routes=("/app/account#delivery", "/app/api/channel-loop"),
        artifacts=("email digest", "delivery receipt"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="telegram_delivery",
        group="delivery",
        label="Telegram review messages",
        routes=("/app/account#delivery", "/v1/channels/telegram/ingest", "/v1/channels/telegram/ingest/:bot_key"),
        artifacts=("Telegram alert", "appendix link"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="whatsapp_delivery",
        group="delivery",
        label="WhatsApp alerts and template messages",
        routes=(
            "/app/account#delivery",
            "/v1/integrations/heyy/whatsapp/webhook",
            "/app/api/integrations/heyy/notifications/property-match",
            "/app/api/integrations/heyy/notifications/search-agent-digest",
        ),
        artifacts=("WhatsApp template", "delivery receipt"),
        neuronwriter_allowed=True,
    ),
    PropertySurface(
        key="provider_management",
        group="management",
        label="Provider catalog and runtime configuration",
        routes=("/admin/providers", "/v1/providers", "/app/search#sources"),
        customer_visible=False,
    ),
    PropertySurface(
        key="fleet_repair",
        group="management",
        label="Fleet repair, fetch-fail recovery, and run reliability",
        routes=("/app/properties?run_id=:run_id", "/admin/audit-trail", "/v1/property/repair"),
        templates=("app/property_decision_workbench.html", "app/_property_running_panel.html"),
    ),
    PropertySurface(
        key="ltd_runtime",
        group="management",
        label="LTD runtime catalog and operator actions",
        routes=("/v1/ltds/runtime-catalog",),
        customer_visible=False,
    ),
    PropertySurface(
        key="loading_empty_error_states",
        group="system_states",
        label="Loading, empty, failed, degraded, repairing, and completed-partial states",
        routes=("/app/search", "/app/properties", "/app/shortlist", "/app/research/:candidate_ref"),
        templates=("app/property_decision_workbench.html", "app/_property_results_list.html", "app/_property_running_panel.html"),
    ),
    PropertySurface(
        key="browser_notifications",
        group="system_states",
        label="Browser notification permission and status states",
        routes=("/app/search", "/app/shortlist", "/app/agents"),
        templates=("app/property_decision_workbench.html", "app/_property_workbench_script.html"),
    ),
)


def all_property_surfaces() -> tuple[PropertySurface, ...]:
    return PROPERTY_SURFACES


def property_surface_keys() -> tuple[str, ...]:
    return tuple(surface.key for surface in PROPERTY_SURFACES)


def property_surfaces_by_group() -> dict[str, tuple[PropertySurface, ...]]:
    grouped: dict[str, list[PropertySurface]] = {}
    for surface in PROPERTY_SURFACES:
        grouped.setdefault(surface.group, []).append(surface)
    return {group: tuple(rows) for group, rows in grouped.items()}


def clickrank_property_surface_keys() -> tuple[str, ...]:
    return tuple(surface.key for surface in PROPERTY_SURFACES if surface.clickrank_allowed)


def neuronwriter_property_surface_keys() -> tuple[str, ...]:
    return tuple(surface.key for surface in PROPERTY_SURFACES if surface.neuronwriter_allowed)


def property_surface_acceptance_matrix() -> dict[str, dict[str, object]]:
    return {
        surface.key: {
            "group": surface.group,
            "label": surface.label,
            "routes": surface.routes,
            "templates": surface.templates,
            "artifacts": surface.artifacts,
            "customer_visible": surface.customer_visible,
            "clickrank_allowed": surface.clickrank_allowed,
            "neuronwriter_allowed": surface.neuronwriter_allowed,
            "required_gates": surface.required_gates,
            "proof_types": surface.proof_types,
        }
        for surface in PROPERTY_SURFACES
    }
