from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_TEMPLATES = (
    ROOT / "ea/app/templates/app/property_decision_workbench.html",
    ROOT / "ea/app/templates/app/property_packets.html",
    ROOT / "ea/app/templates/propertyquarry_home.html",
)


def _template_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CUSTOMER_TEMPLATES)


def test_propertyquarry_customer_templates_avoid_internal_operator_language() -> None:
    body = _template_text()

    forbidden = (
        ">EA<",
        " EA ranks",
        "EA post-filtered",
        "OODA",
        "Artifact receipts",
        "Generated asset receipts",
        "Telegram links",
        "premium_dossier_render_failed",
        "tour_control_3dvista_export_missing",
        "tour_control_matterport_export_missing",
    )
    for marker in forbidden:
        assert marker not in body


def test_propertyquarry_layout_guide_is_the_design_contract() -> None:
    gate = (ROOT / "docs/PROPERTYQUARRY_DESIGN_SYSTEM_GATE.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/PROPERTYQUARRY_APP_LAYOUT_GUIDE.md").read_text(encoding="utf-8")
    registry = (ROOT / "docs/PROPERTYQUARRY_SURFACE_REGISTRY.md").read_text(encoding="utf-8")

    assert "docs/PROPERTYQUARRY_APP_LAYOUT_GUIDE.md" in gate
    assert "No decision wizard inside result cards." in guide
    assert "Progress card dimensions" in guide
    assert "panel width desktop: 360-420px" in guide
    assert "Table columns" in guide
    assert "This file defines \"all surfaces\"" in registry
    assert "Public Acquisition" in registry
    assert "Authenticated App" in registry
    assert "Generated Artifacts" in registry


def test_propertyquarry_surface_registry_defines_all_product_surfaces() -> None:
    from app.product.property_surface_registry import (
        ACCEPTANCE_GATES,
        AUDIT_AXES,
        PROOF_TYPES,
        clickrank_property_surface_keys,
        neuronwriter_property_surface_keys,
        property_surface_acceptance_matrix,
        property_surface_keys,
        property_surfaces_by_group,
    )

    keys = set(property_surface_keys())
    grouped = property_surfaces_by_group()

    assert len(keys) >= 25
    assert len(keys) == len(property_surface_keys())
    assert set(grouped) == {
        "public_acquisition",
        "auth_handoff",
        "authenticated_app",
        "results_research",
        "shared_public_artifacts",
        "generated_artifacts",
        "delivery",
        "management",
        "system_states",
    }
    for group, rows in grouped.items():
        assert rows, group

    required_keys = {
        "public_home",
        "public_pricing",
        "public_docs_guides",
        "registration",
        "sign_in",
        "app_shell",
        "search_wizard",
        "what_matters",
        "run_home",
        "shortlist",
        "property_research_detail",
        "agents",
        "account",
        "billing",
        "public_packet",
        "public_tour",
        "premium_dossier",
        "video_walkthrough",
        "email_delivery",
        "telegram_delivery",
        "whatsapp_delivery",
        "provider_management",
        "fleet_repair",
        "ltd_runtime",
        "loading_empty_error_states",
    }
    assert required_keys.issubset(keys)
    assert "legacy_object_detail" not in keys

    assert {"navigation", "clickability", "accessibility", "performance", "privacy"}.issubset(set(AUDIT_AXES))
    assert set(clickrank_property_surface_keys()) == {
        "public_home",
        "public_pricing",
        "public_trust",
        "public_docs_guides",
    }
    assert "app_shell" not in clickrank_property_surface_keys()
    assert "public_tour" not in clickrank_property_surface_keys()
    assert "property_research_detail" in neuronwriter_property_surface_keys()
    assert "app_shell" not in neuronwriter_property_surface_keys()

    expected_gates = {
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
    }
    assert expected_gates == set(ACCEPTANCE_GATES)
    assert {"unit_contract", "screenshot", "privacy_fixture", "performance_probe"}.issubset(set(PROOF_TYPES))

    matrix = property_surface_acceptance_matrix()
    assert set(matrix) == keys
    for key, row in matrix.items():
        assert expected_gates.issubset(set(row["required_gates"])), key
        assert row["proof_types"], key
    assert matrix["public_home"]["clickrank_allowed"] is True
    assert matrix["public_home"]["neuronwriter_allowed"] is True
    assert "/guides/wohnung-kaufen-wien-checkliste" in matrix["public_docs_guides"]["routes"]
    assert "/markets/vienna" in matrix["public_docs_guides"]["routes"]
    assert "/blog" not in matrix["public_docs_guides"]["routes"]
    assert "/compare" not in matrix["public_docs_guides"]["routes"]
    assert matrix["app_shell"]["clickrank_allowed"] is False
    assert matrix["app_shell"]["neuronwriter_allowed"] is False
    assert matrix["public_results"]["routes"] == (
        "/results/:slug",
        "/results/:slug.json",
        "/results/files/:slug/:asset",
    )
    assert matrix["public_packet"]["routes"] == (
        "/v1/integrations/fliplink/documents/property-packets/:token",
        "/app/properties/packets",
    )
    assert matrix["public_tour"]["clickrank_allowed"] is False
    assert matrix["public_tour"]["routes"] == ("/tours/:slug", "/tours/:slug.json", "/tours/files/:slug/:asset")
    assert matrix["agents"]["routes"] == ("/app/agents", "/app/automation", "/app/automations")
    assert matrix["premium_dossier"]["routes"] == ("/app/api/properties/packets/:publication_id/pdf",)
    assert "/app/api/signals/willhaben/property-tour" in matrix["floorplan_and_tour_control"]["routes"]
    assert "/app/api/property-video/requests/dadan" in matrix["video_walkthrough"]["routes"]
    assert "/v1/integrations/dadan/webhooks/recording-submitted" in matrix["video_walkthrough"]["routes"]
    assert "/v1/channels/telegram/ingest" in matrix["telegram_delivery"]["routes"]
    assert "/v1/integrations/heyy/whatsapp/webhook" in matrix["whatsapp_delivery"]["routes"]


def test_propertyquarry_clickable_looking_recent_reviews_are_real_links_or_plain_rows() -> None:
    body = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "href=\"{{ packet.get('url') or '#' }}\"" not in body
    assert "pqx-recent-review-static" in body
    assert "<span class=\"pqx-pill\">{{ packet.get('title') }}</span>" not in body
    assert ".pqx-recent-review" in body
    assert "white-space: normal;" in body
    assert "overflow-wrap: normal;" in body


def test_propertyquarry_search_results_explain_suppression_and_provider_quality() -> None:
    body = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "Search guard" not in body
    assert "Filtered by rules" in body
    assert "Open to relax one rule and rerun the search." in body
    assert "data-pqx-counterfactual" in body
    assert "How this search was filtered" in body
    assert "Floorplans {{ provider_quality.get('floorplan_reliability')" in body
    assert "Best matches" in body


def test_propertyquarry_brand_marks_route_to_public_or_dashboard_home() -> None:
    public_shell = (ROOT / "ea/app/templates/base_public.html").read_text(encoding="utf-8")
    console_shell = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "{% set brand_home_href = '/?home=1' if (brand.key == 'propertyquarry' and public_signed_in) else ((brand.app_home or '/app/properties') if public_signed_in else (brand.public_base_url or '/')) %}" in public_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} home">' in public_shell
    assert "{% set brand_home_href = '/?home=1' if brand.key == 'propertyquarry' else (brand.app_home or '/app/properties') %}" in console_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} home">' in console_shell
    assert "run.get('run_id')" not in workbench.split('<a class="pqx-brand"', 1)[1].split(">", 1)[0]
    assert '<a class="pqx-brand" href="/?home=1" aria-label="PropertyQuarry public home">' in workbench


def test_propertyquarry_app_surfaces_expose_account_navigation() -> None:
    console_shell = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    for body in (console_shell, workbench):
        assert "Account navigation" in body
        assert ">Upgrade<" in body
        assert ">Log out<" in body


def test_propertyquarry_customer_surfaces_keep_accessibility_exit_gates() -> None:
    public_shell = (ROOT / "ea/app/templates/base_public.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "a:focus-visible" in public_shell
    assert "button:focus-visible" in public_shell
    assert "@media (prefers-reduced-motion: reduce)" in public_shell
    assert "@media (prefers-reduced-motion: reduce)" in workbench
    assert 'aria-label="PropertyQuarry sections"' in workbench
    assert 'aria-label="PropertyQuarry view mode"' in workbench
    assert 'aria-label="Search setup"' in workbench
    assert 'aria-label="Account navigation"' in workbench
    assert 'aria-label="Close filtered rules"' in workbench


def test_propertyquarry_console_shell_uses_new_property_surface_links() -> None:
    body = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")

    assert 'href="/app/account{{ query_suffix }}"' in body
    assert 'href="/app/agents{{ query_suffix }}"' in body
    assert "Search, market watch, decision packets, and review in one persistent shell." in body
    assert 'href="/app/settings{{ query_suffix }}"' not in body
    assert 'href="/app/research{{ query_suffix }}"' not in body
