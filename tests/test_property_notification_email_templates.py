from __future__ import annotations

from app.services.registration_email import property_notification_preview


def test_property_notification_previews_cover_all_gold_templates() -> None:
    templates = {
        "search_results_ready": "PropertyQuarry found 2 strong matches",
        "property_match": "Property match: Altbau near U6",
        "tour_ready": "Apartment tour ready: Family flat near Augarten",
        "investment_research_ready": "Investment research ready",
        "workspace_invitation": "Mara invited you to PropertyQuarry",
        "workspace_access": "Your access link for PropertyQuarry Workspace",
        "google_connect": "Connect Google to PropertyQuarry Workspace",
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
        "property_match": ("Open 360",),
        "tour_ready": ("Open hosted 360", "Open research packet"),
        "investment_research_ready": ("Open investment packet",),
        "workspace_invitation": ("Review workspace invite",),
        "workspace_access": ("Open access link",),
        "google_connect": ("Connect Google",),
        "market_ready": ("Open PropertyQuarry",),
    }
    for key, expected_actions in actionable.items():
        html = str(property_notification_preview(key).get("html") or "")
        for action in expected_actions:
            assert action in html, f"{action!r} missing from {key}"
