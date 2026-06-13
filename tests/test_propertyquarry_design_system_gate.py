from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_TEMPLATES = (
    ROOT / "ea/app/templates/app/property_decision_workbench.html",
    ROOT / "ea/app/templates/app/property_workspace.html",
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


def test_propertyquarry_clickable_looking_recent_reviews_are_real_links_or_plain_rows() -> None:
    body = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "href=\"{{ packet.get('url') or '#' }}\"" not in body
    assert "pqx-recent-review-static" in body
    assert "<span class=\"pqx-pill\">{{ packet.get('title') }}</span>" not in body
    assert ".pqx-recent-review" in body
    assert "white-space: normal;" in body
    assert "overflow-wrap: anywhere;" in body


def test_propertyquarry_search_results_explain_suppression_and_provider_quality() -> None:
    body = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "Search guard" in body
    assert "Held back by rules" in body
    assert "What did not reach the shortlist" in body
    assert "Source quality" in body
    assert "Floorplans {{ provider_quality.get('floorplan_reliability')" in body
    assert "PropertyQuarry ranks the candidates" in body


def test_propertyquarry_brand_marks_route_to_public_or_dashboard_home() -> None:
    public_shell = (ROOT / "ea/app/templates/base_public.html").read_text(encoding="utf-8")
    console_shell = (ROOT / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (ROOT / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "{% set brand_home_href = (brand.app_home or '/app/properties') if access_identity else (brand.public_base_url or '/') %}" in public_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} home">' in public_shell
    assert "{% set brand_home_href = brand.app_home or '/app/properties' %}" in console_shell
    assert '<a class="brand" href="{{ brand_home_href }}" aria-label="{{ brand.name }} dashboard">' in console_shell
    assert "run.get('run_id')" not in workbench.split('<a class="pqx-brand"', 1)[1].split(">", 1)[0]
    assert '<a class="pqx-brand" href="/app/properties" aria-label="PropertyQuarry dashboard">' in workbench
