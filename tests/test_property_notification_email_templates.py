from __future__ import annotations

from app.services.registration_email import property_notification_preview


def test_property_notification_previews_cover_all_gold_templates() -> None:
    templates = {
        "search_results_ready": "PropertyQuarry found 2 strong matches",
        "property_match": "Property match: Altbau near U6",
        "tour_ready": "Apartment tour ready: Family flat near Augarten",
        "investment_research_ready": "Investment research ready",
        "workspace_invitation": "Mara invited you to PropertyQuarry",
        "workspace_access": "Your access link for PropertyQuarry account",
        "google_connect": "Connect Google to PropertyQuarry account",
        "market_ready": "PropertyQuarry market ready: Vienna",
    }
    for key, subject_prefix in templates.items():
        preview = property_notification_preview(key)
        assert preview["template_key"] == key
        assert str(preview.get("subject") or "").startswith(subject_prefix)
        assert str(preview.get("preheader") or "").strip()
        assert str(preview.get("text") or "").strip()
        html = str(preview.get("html") or "")
        assert html
        assert "PropertyQuarry" in html
        assert "PropertyQuarry" in str(preview.get("text") or "")
        assert "EA prepared" not in html
        assert "EA shortlisted" not in html
        assert "EA prepared" not in str(preview.get("text") or "")
        assert "EA shortlisted" not in str(preview.get("text") or "")
        assert "<html" in html.lower()
        assert "propertyquarry.com" in html


def test_property_notification_preview_html_contains_action_surface_links() -> None:
    actionable = {
        "search_results_ready": ("Open 360",),
        "property_match": ("Yes, shortlist", "No — tell us why", "Ask agent"),
        "tour_ready": ("Open 360 review", "No — tell us why", "Ask agent about blockers or missing facts"),
        "investment_research_ready": ("Open investment packet", "Ask for documents", "Pass — too risky"),
        "workspace_invitation": ("Open invite",),
        "workspace_access": ("Open access link",),
        "google_connect": ("Connect Google",),
        "market_ready": ("Open PropertyQuarry",),
    }
    for key, expected_actions in actionable.items():
        html = str(property_notification_preview(key).get("html") or "")
        for action in expected_actions:
            assert action in html, f"{action!r} missing from {key}"


def test_search_results_ready_preview_includes_compare_reason() -> None:
    preview = property_notification_preview("search_results_ready")
    text = str(preview.get("text") or "")
    html = str(preview.get("html") or "")

    assert "Why it won:" in text
    assert "Why it won" in html
    assert "scored 5 points higher" in text or "includes a floorplan" in text


def test_property_notification_preview_plaintext_never_exposes_raw_urls() -> None:
    for key in (
        "search_results_ready",
        "property_match",
        "tour_ready",
        "investment_research_ready",
        "workspace_invitation",
        "workspace_access",
        "google_connect",
        "market_ready",
    ):
        text = str(property_notification_preview(key).get("text") or "")
        assert "http://" not in text
        assert "https://" not in text
        assert "titled" in text or key == "market_ready"
