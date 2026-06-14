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

    assert "docs/PROPERTYQUARRY_APP_LAYOUT_GUIDE.md" in gate
    assert "No decision wizard inside result cards." in guide
    assert "Progress card dimensions" in guide
    assert "panel width desktop: 360-420px" in guide
    assert "Table columns" in guide


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
    assert "Best homes first" in body


def test_propertyquarry_brand_marks_route_to_public_or_dashboard_home() -> None:
    public_shell = (ROOT / "ea/app/templates/base_public.html").read_text(encoding="utf-8")
    console_shell = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "{% set brand_home_href = (brand.app_home or '/app/properties') if access_identity else (brand.public_base_url or '/') %}" in public_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} home">' in public_shell
    assert "{% set brand_home_href = brand.app_home or '/app/properties' %}" in console_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} home">' in console_shell
    assert "run.get('run_id')" not in workbench.split('<a class="pqx-brand"', 1)[1].split(">", 1)[0]
    assert '<a class="pqx-brand" href="/app/properties" aria-label="PropertyQuarry home">' in workbench


def test_propertyquarry_app_surfaces_expose_account_navigation() -> None:
    console_shell = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    for body in (console_shell, workbench):
        assert "Account navigation" in body
        assert ">Upgrade<" in body
        assert ">Log out<" in body


def test_propertyquarry_console_shell_uses_new_property_surface_links() -> None:
    body = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")

    assert 'href="/app/account{{ query_suffix }}"' in body
    assert 'href="/app/agents{{ query_suffix }}"' in body
    assert "Search, market watch, decision packets, and review in one persistent shell." in body
    assert 'href="/app/settings{{ query_suffix }}"' not in body
    assert 'href="/app/research{{ query_suffix }}"' not in body
