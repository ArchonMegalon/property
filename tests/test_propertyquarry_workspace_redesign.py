from __future__ import annotations

import json
import re
import html
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from app.api.dependencies import RequestContext, get_request_context
from app.api.routes import landing as landing_routes
from app.api.routes.landing_property_surface_contracts import PropertySurfaceScope
from app.api.routes import landing_property_workspace_helpers
from app.api.routes import landing_property_research
from app.api.routes import landing_property_saved_searches
from app.api.routes import landing_property_shortlist_panel
from app.api.routes import landing_property_workspace_payload
from app.api.routes import public_tours
from app.api.routes import landing_view_models
from app.api.routes import public_results
from app.services import public_branding
from app.services import property_market_catalog
from app.product import property_surface_state
from app.product.models import HandoffNote
from app.product.service import (
    ProductService,
    _property_candidate_notification_location_evidence_kind,
    _property_candidate_matches_requested_location,
    _property_enrich_facts_from_listing_text,
    _property_facts_with_source_scope,
    _property_search_analysis_cap_per_source,
    _property_source_display_label,
    _property_scout_brief_text,
    build_product_service,
)
from tests.product_test_helpers import build_property_client, seed_product_state, start_workspace


def _read_workbench_bundle() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/app/_property_results_list.html",
        repo_root / "ea/app/templates/app/_property_running_panel.html",
        repo_root / "ea/app/templates/app/_property_search_agents_panel.html",
        repo_root / "ea/app/templates/app/_property_selected_review_panel.html",
        repo_root / "ea/app/templates/app/_property_workbench_script.html",
        repo_root / "ea/app/templates/app/_property_workbench_brief_script.html",
        repo_root / "ea/app/templates/app/_property_workbench_feedback_script.html",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths if path.exists())


class _RenderedInteractiveElementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "button", "form"}:
            return
        self.elements.append((tag, {key: value or "" for key, value in attrs}, ""))

    def handle_data(self, data: str) -> None:
        if not self.elements:
            return
        text = str(data or "").strip()
        if not text:
            return
        tag, attrs, current = self.elements[-1]
        self.elements[-1] = (tag, attrs, f"{current} {text}".strip())


def test_propertyquarry_app_templates_do_not_reintroduce_legacy_dark_theme_tokens() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_paths = [
        repo_root / "ea/app/templates/base_console.html",
        repo_root / "ea/app/templates/console_shell.html",
        repo_root / "ea/app/templates/app/object_detail.html",
        repo_root / "ea/app/templates/app/people_detail.html",
        repo_root / "ea/app/templates/app/commitment_candidate_review.html",
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
    ]
    forbidden_tokens = (
        "rgba(18, 23, 34",
        "rgba(15, 19, 26",
        "rgba(49, 60, 77",
        "#070a10",
        "#0a0d14",
        "#0b1017",
        "360 not ready",
        "not scheduled yet",
    )
    for template_path in template_paths:
        body = template_path.read_text(encoding="utf-8")
        assert "background: var(--panel);" in body or "background: var(--pq-paper);" in body
        for token in forbidden_tokens:
            assert token not in body, f"{token!r} leaked into {template_path.relative_to(repo_root)}"


def test_property_results_empty_state_uses_saved_search_language() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")

    assert "Open saved searches" in body
    assert "Open automation" not in body


def test_propertyquarry_primary_surfaces_have_no_dead_click_targets_or_generic_noise() -> None:
    client = build_property_client(principal_id="pq-rendered-surface-click-audit")
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")
    public_client = build_property_client(principal_id="pq-rendered-public-click-audit")
    public_client.headers.pop("X-EA-Principal-ID", None)
    audited_paths = (
        (client, "/app/search"),
        (client, "/app/properties"),
        (client, "/app/shortlist"),
        (client, "/app/agents"),
        (client, "/app/account"),
        (client, "/app/billing"),
        (client, "/data-deletion"),
        (public_client, "/"),
        (public_client, "/?home=1"),
        (public_client, "/sign-in"),
        (public_client, "/pricing"),
        (public_client, "/data-deletion"),
    )
    protected_paths = (
        "/app/search",
        "/app/shortlist",
    )
    noisy_phrases = (
        "Use stored feedback preferences",
        "Manage feedback preferences",
        "Preference profile",
        "Billing truth",
        "Plan and limits",
        "Plan unit",
        "entitlement truth",
        "Make plan, limits",
        "worker capacity",
        "provider breadth",
        "What this plan can actually run",
        "How this plan affects real runs",
        "live search workers",
        "Fleet digest",
        "Executive Assistant",
        "memo items",
        "queue items",
        "operator load",
        "EA queued",
        "Open automation",
        "office loop",
        "Refresh delivery",
        "support tooling",
        "workspace access links",
        "workspace access method",
        "workspace records",
        "Office-loop proof",
        "release proof",
        "Journey proof",
        "No proof summary",
        "Gate state",
        "Passed checks",
        "source check",
        "Run health and coverage",
        "Everyday preferences, schools, childcare, and local fit that should stay explicit.",
        "workspace preferences",
        "generated workflow data",
        "generated workflow records",
        "generated drafts",
        "operational artifacts tied to your workspace",
        "operational artifacts tied to your account",
    )
    for audit_client, path in audited_paths:
        response = audit_client.get(path, headers={"host": "propertyquarry.com"})
        assert response.status_code == 200, path
        rendered_text = re.sub(
            r"<script.*?</script>|<style.*?</style>",
            " ",
            response.text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        rendered_text = re.sub(r"<[^>]+>", " ", rendered_text)
        rendered_text = re.sub(r"\s+", " ", rendered_text)
        for phrase in noisy_phrases:
            assert phrase.lower() not in rendered_text.lower(), f"{phrase!r} leaked into {path}"

        parser = _RenderedInteractiveElementParser()
        parser.feed(response.text)
        for tag, attrs, text in parser.elements:
            if tag == "a":
                href = str(attrs.get("href") or "").strip()
                assert href and href != "#", f"dead link on {path}: {text!r}"
                assert not href.lower().startswith("javascript:"), f"javascript link on {path}: {text!r}"
                if audit_client is public_client and href.split("#", 1)[0] in protected_paths:
                    assert "current session" not in text.lower(), f"anonymous page links current-session action to protected route on {path}"
            if tag == "button" and "disabled" not in attrs:
                button_type = str(attrs.get("type") or "submit").strip().lower() or "submit"
                has_data_handler = any(key.startswith("data-") for key in attrs)
                has_form_action = bool(str(attrs.get("formaction") or "").strip())
                assert (
                    button_type in {"submit", "reset"}
                    or has_data_handler
                    or has_form_action
                ), f"enabled button without action wiring on {path}: {text!r}"
            if tag == "form":
                action = str(attrs.get("action") or "").strip()
                method = str(attrs.get("method") or "get").strip().lower() or "get"
                has_data_handler = any(key.startswith("data-") for key in attrs)
                assert action or has_data_handler, f"form without action or client handler on {path}"
                assert not action.lower().startswith("javascript:"), f"javascript form action on {path}: {action!r}"
                assert method in {"get", "post", "dialog"}, f"unexpected form method on {path}: {method!r}"


def test_propertyquarry_invitations_surface_uses_collaborator_language() -> None:
    client = build_property_client(principal_id="pq-rendered-invitation-language")
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    response = client.get("/app/settings/invitations", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200

    rendered_text = re.sub(
        r"<script.*?</script>|<style.*?</style>",
        " ",
        response.text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    rendered_text = re.sub(r"<[^>]+>", " ", rendered_text)
    rendered_text = re.sub(r"\s+", " ", rendered_text)

    assert "Collaborator" in rendered_text
    assert "Account owner" in rendered_text
    assert "operator invitation" not in rendered_text.lower()
    assert "operator one" not in rendered_text.lower()
    assert "another reviewer or operator" not in rendered_text.lower()


def test_property_result_title_display_cleans_provider_url_garbage() -> None:
    raw_title = 'https://www.raiffeisen-wohnbau.at/projects/id/1090-vienna/augasse-17/70/\\&quot;\\n'

    display = landing_view_models._property_result_title_display(raw_title)

    assert display == "Augasse 17 70"
    assert "https://" not in display
    assert "&quot;" not in display
    assert "\\n" not in display


def test_propertyquarry_object_detail_template_exposes_user_facing_optional_tools() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "Open question helper" in body
    assert "Visualize furnished living" in body
    assert "Upload reference photos" in body
    assert "Use Google Photos Picker" in body
    assert "Attach the generated still to the packet PDF dossier" in body


def test_propertyquarry_blocks_legacy_object_detail_routes_for_generic_office_objects() -> None:
    principal_id = "pq-legacy-object-detail-guard"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    seeded = seed_product_state(client, principal_id=principal_id)

    legacy_paths = [
        f"/app/people/{seeded['stakeholder_id']}",
        f"/app/commitment-items/commitment:{seeded['commitment_id']}",
        f"/app/decisions/{seeded['decision_window_id']}",
        f"/app/deadlines/{seeded['deadline_window_id']}",
        f"/app/handoffs/human_task:{seeded['human_task_id']}",
    ]
    for path in legacy_paths:
        response = client.get(path, headers={"host": "propertyquarry.com"})
        assert response.status_code == 404, path
        assert "propertyquarry_object_detail_not_available" in response.text


def test_propertyquarry_results_prefer_real_media_over_generated_diorama_previews() -> None:
    candidate = {
        "preview_image_url": "https://propertyquarry.com/tours/files/demo-tour/diorama-preview.png",
        "property_facts": {
            "media_urls_json": [
                "https://cdn.example.com/provider/photo-1.jpg",
                "https://cdn.example.com/provider/photo-2.jpg",
            ]
        },
    }
    assert landing_view_models._property_candidate_preview_image(candidate) == "https://cdn.example.com/provider/photo-1.jpg"


def test_propertyquarry_candidate_display_facts_prefer_listing_locality_over_source_scope_placeholder() -> None:
    candidate = {
        "title": "expat flat: möblierte 2-Zimmer-Wohnung I beim Prater/ Praterstraße, 77 m², € 1.598,-, (1020 Wien) - willhaben",
        "property_facts": {
            "postal_name": "1010 Vienna",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "address": "1020 Wien",
            "listing_research_snapshot": {
                "postal_name": "1020 Wien",
                "address": "1020 Wien",
            },
        },
    }

    facts = landing_property_workspace_helpers._property_candidate_display_facts(candidate)

    assert facts["postal_name"] == "1020 Wien"
    assert facts["address"] == "1020 Wien"


def test_propertyquarry_candidate_display_facts_use_listing_postal_over_dirty_source_scope_without_snapshot() -> None:
    candidate = {
        "title": "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD",
        "summary": "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
        "property_facts": {
            "postal_name": "1010 Vienna",
            "district": "1010 Vienna",
            "address": "1010 Vienna",
            "source_scope_location": "1010 Vienna",
            "source_postal_code": "1010",
            "source_city": "Vienna",
        },
    }

    facts = landing_property_workspace_helpers._property_candidate_display_facts(candidate)

    assert facts["postal_name"] == "1220 Wien"
    assert facts["district"] == "1220 Wien"
    assert facts["address"] == "1220 Wien"


def test_propertyquarry_scout_source_labels_strip_search_scope_for_any_postal_code() -> None:
    assert _property_source_display_label("DER STANDARD Immobilien | Austria | Rent | 1010 Vienna") == "DER STANDARD Immobilien"
    assert _property_source_display_label("Willhaben | Austria | Rent | Salzburg") == "Willhaben"
    assert _property_source_display_label("Willhaben | Austria | Rent | 4784 Schärding") == "Willhaben"
    assert _property_source_display_label("Genossenschaften | Austria | Rent | 1220 Wien | GESIBA Wohnungen") == "Genossenschaften · GESIBA Wohnungen"

    message = _property_scout_brief_text(
        title="Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | EUR 1.090",
        property_url="https://example.test/listing",
        source_text=_property_source_display_label("DER STANDARD Immobilien | Austria | Rent | 1010 Vienna"),
        fit_summary="Personal fit 50/100",
    )

    assert "Source: DER STANDARD Immobilien" in message
    assert "Source: DER STANDARD Immobilien | Austria | Rent | 1010 Vienna" not in message

    raw_message = _property_scout_brief_text(
        title="#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse in Salzburg",
        property_url="https://example.test/listing",
        source_text="Willhaben | Austria | Rent | 1010 Vienna",
        fit_summary="Personal fit 54/100",
    )
    assert "Source: Willhaben" in raw_message
    assert "Source: Willhaben | Austria | Rent | 1010 Vienna" not in raw_message


def test_propertyquarry_requested_postal_scope_rejects_listing_url_postal_leaks() -> None:
    examples = [
        (
            "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | EUR 1.090",
            "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
            "https://www.derstandard.at/immobilien/wohnung-mieten-in-1220-wien",
        ),
        (
            "Wohnung mieten in 1200 Wien,Brigittenau | 81.98 m² | 3 Zimmer",
            "Stilvolle 3-Zimmer-Wohnung mit Garten & Terrasse im 20. Bezirk.",
            "https://www.derstandard.at/immobilien/wohnung-mieten-in-1200-wien-brigittenau",
        ),
        (
            "Prepared property page",
            "Gallitzinstrasse",
            "https://www.raiffeisen-wohnbau.at/projects/id/1160-vienna/gallitzinstras",
        ),
        (
            "Augasse 17",
            "Projektadresse Augasse 17 in 1090 Wien.",
            "https://www.raiffeisen-wohnbau.at/de/projects/id/1090-vienna/augasse-17/70",
        ),
        (
            "#W2 Moderne Schöne Zwei-Zimmer Wohnung mit Terrasse",
            "Moderne Wohnung mit Penthouse-Charakter in Salzburg.",
            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/salzburg/salzburg-stadt/moderne-wohnung",
        ),
        (
            "Einziehen sorgenfrei starten",
            "Ihre Traumwohnung mit Balkon in Schärding.",
            "https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/schaerding/einziehen-sorgenfrei-starten",
        ),
    ]

    for title, summary, property_url in examples:
        facts = _property_facts_with_source_scope(
            facts={"postal_name": "1010 Vienna"},
            source_url=property_url,
            source_label="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        )
        facts = _property_enrich_facts_from_listing_text(
            facts=facts,
            title=title,
            summary=summary,
            listing_mode="rent",
        )

        assert not _property_candidate_matches_requested_location(
            location_hints=("1010 Vienna",),
            property_url=property_url,
            title=title,
            summary=summary,
            property_facts=facts,
            country_code="AT",
            region_code="vienna",
        ), property_url


def test_propertyquarry_requested_postal_scope_ignores_source_scope_placeholders_in_fact_fields() -> None:
    facts = _property_facts_with_source_scope(
        facts={
            "district": "1010 Vienna",
            "postal_name": "1010 Vienna",
            "location": "1010 Vienna",
            "address": "1010 Vienna",
            "address_lines": ["1010 Vienna"],
        },
        source_url="",
        source_label="DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
    )

    assert (
        _property_candidate_notification_location_evidence_kind(
            property_url="https://immobilien.derstandard.at/detail/source-scope-only",
            title="Wohnung mieten | 60 m2 | 2 Zimmer",
            summary="Schöne Wohnung mit Balkon.",
            property_facts=facts,
        )
        == "source_scope_only"
    )
    assert not _property_candidate_matches_requested_location(
        location_hints=("1010 Vienna",),
        property_url="https://immobilien.derstandard.at/detail/source-scope-only",
        title="Wohnung mieten | 60 m2 | 2 Zimmer",
        summary="Schöne Wohnung mit Balkon.",
        property_facts=facts,
        country_code="AT",
        region_code="vienna",
    )


def test_property_postal_parser_is_generic_but_not_price_hungry() -> None:
    names = landing_property_workspace_helpers._property_postal_names_from_text(
        "Wohnung mieten in 5020 Salzburg | 60 m2 | EUR 1.090"
    )
    assert names == ("5020 Salzburg",)
    assert landing_property_workspace_helpers._property_postal_names_from_text(
        "Expat flat beim Prater EUR 1.598 77 m2 2 rooms"
    ) == ()
    assert landing_property_workspace_helpers._property_postal_codes_from_text(
        "Expat flat beim Prater EUR 1.598 77 m2 2 rooms",
        require_locality=True,
    ) == ()
    assert landing_property_workspace_helpers._property_postal_codes_from_text(
        "4784 Schärding",
        require_locality=True,
    ) == ("4784",)


def test_property_orientation_preview_derives_non_vienna_postal_location_from_listing_copy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_boundary_preview(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "image_url": "/app/api/property/map-previews/" + ("c" * 40) + ".png",
            "preview_kind": "osm_point_fallback",
            "summary": str(kwargs.get("normalized_query") or ""),
        }

    monkeypatch.setattr(landing_view_models, "_build_scope_boundary_preview", _fake_boundary_preview)
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda label: None)

    preview = landing_property_workspace_helpers._property_candidate_orientation_preview(
        {
            "title": "Moderne Wohnung in 5020 Salzburg | 60 m2 | EUR 1.090",
            "summary": "Balkon und Lift.",
            "property_facts_json": {},
        }
    )

    assert captured["normalized_query"] == "5020 Salzburg"
    assert preview["title"] == "5020 Salzburg"
    assert preview["caption"] == "5020 Salzburg"


def test_propertyquarry_shortlist_does_not_surface_willhaben_tracking_endpoint_as_provider_360() -> None:
    body = _read_workbench_bundle()
    assert "api.willhaben.at/restapi/v2/logevent" not in body


def test_propertyquarry_visual_requests_stay_user_initiated_and_idempotent() -> None:
    body = _read_workbench_bundle()
    research_detail = (
        Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_research_detail.html"
    ).read_text(encoding="utf-8")

    assert "auto_deliver: false" in body
    assert "allow_floorplan_only: true" in body
    assert "keepButtonDisabled = true" in body
    assert "button.disabled = keepButtonDisabled" in body
    assert "data-pw-visual-ready-url" in body
    assert "const requestedReadyUrl = requestKind === 'flythrough' ? nextFlythroughUrl : nextTourUrl" in body
    assert "window.location.href = readyUrl" in body
    assert "button.setAttribute('data-pw-visual-state', requestedReadyUrl ? 'ready' : requestedStatus)" in body
    assert "Open walkthrough" in research_detail
    assert "Open flythrough" not in research_detail
    assert "['pending', 'queued', 'processing', 'running', 'in_progress', 'started', 'rendering'].includes(nextState)" in research_detail
    assert "button.disabled = ['pending', 'queued', 'processing', 'running', 'in_progress', 'started', 'rendering'].includes(currentState)" in research_detail


def test_propertyquarry_register_surface_uses_property_search_language() -> None:
    client = build_property_client(principal_id="pq-register-copy")
    public_client = build_property_client(principal_id="pq-register-copy-public")
    public_client.headers.pop("X-EA-Principal-ID", None)

    page = client.get("/register", headers={"host": "propertyquarry.com"})
    sign_in = public_client.get("/sign-in", headers={"host": "propertyquarry.com"})
    signed_in_sign_in = client.get("/sign-in", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert sign_in.status_code == 200
    assert signed_in_sign_in.status_code == 200
    assert "Start an account that finds and ranks the right properties" in page.text
    assert "Create the account and start the first search" in page.text
    assert 'href="/app/search"' in page.text
    assert 'href="/app/search"' not in sign_in.text
    assert 'href="/sign-in/current-session"' in sign_in.text
    assert "Open current session" in sign_in.text
    assert 'href="/app/search"' in signed_in_sign_in.text
    assert "Open current session" in signed_in_sign_in.text
    assert 'href="/app/properties">Open current session</a>' not in sign_in.text
    assert "Google?" not in sign_in.text
    assert "Facebook?" not in sign_in.text
    assert "Use the path that matches how you joined" not in sign_in.text
    assert "Identity-only." in sign_in.text
    assert "auth-provider-icon" in sign_in.text
    assert "first useful memo" not in page.text
    assert 'data-milestone="commitments"' not in page.text
    assert "Executive Assistant" not in page.text
    assert "Executive Assistant" not in sign_in.text

    get_started_template = (
        Path(__file__).resolve().parents[1] / "ea/app/templates/get_started.html"
    )
    get_started_body = get_started_template.read_text(encoding="utf-8")
    assert "first useful property search" in get_started_body
    assert "first useful memo" not in get_started_body
    assert "workspace narrow" not in get_started_body
    onboarding_rules = (
        Path(__file__).resolve().parents[1] / "ea/app/templates/onboarding/_step_rules.html"
    ).read_text(encoding="utf-8")
    assert 'href="/app/search">Open PropertyQuarry</a>' in onboarding_rules
    assert 'href="/app/properties">Open PropertyQuarry</a>' not in onboarding_rules


def test_propertyquarry_sign_in_offers_id_austria_only_for_austrian_requests(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET", "id-austria-secret")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI", "https://propertyquarry.com/id-austria/callback")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET", "id-austria-state-secret")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_ENVIRONMENT", "production")

    client = build_property_client(principal_id="pq-id-austria-gate")
    client.headers.pop("X-EA-Principal-ID", None)

    outside_austria = client.get("/sign-in", headers={"host": "propertyquarry.com", "cf-ipcountry": "DE"})
    inside_austria = client.get("/sign-in", headers={"host": "propertyquarry.com", "cf-ipcountry": "AT"})

    assert outside_austria.status_code == 200, outside_austria.text
    assert inside_austria.status_code == 200, inside_austria.text
    assert "Continue with ID Austria" not in outside_austria.text
    assert "Continue with ID Austria" in inside_austria.text

    blocked = client.get(
        "/sign-in/id-austria",
        headers={"host": "propertyquarry.com", "cf-ipcountry": "DE"},
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "id_austria_austria_ip_required" in str(blocked.headers.get("location") or "")

    started = client.get(
        "/sign-in/id-austria",
        headers={"host": "propertyquarry.com", "cf-ipcountry": "AT"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    started_location = str(started.headers.get("location") or "")
    parsed = urllib.parse.urlparse(started_location)
    query = urllib.parse.parse_qs(parsed.query)
    assert parsed.netloc == "idp.id-austria.gv.at"
    assert query["redirect_uri"][0] == "https://propertyquarry.com/id-austria/callback"
    assert query["scope"][0] == "openid profile"


def test_public_branding_repo_urls_stay_in_property_repository(monkeypatch) -> None:
    brand = public_branding.brand_from_hostname("propertyquarry.com")
    assert brand["key"] == "propertyquarry"
    assert brand["name"] == "PropertyQuarry"
    assert brand["app_home"] == "/app/search"
    assert brand["repo_url"] == "https://github.com/ArchonMegalon/property"

    monkeypatch.setenv("PROPERTYQUARRY_DEFAULT_BRAND", "0")
    fallback_brand = public_branding.brand_from_hostname("legacy.invalid")
    assert fallback_brand["key"] == "propertyquarry"
    assert fallback_brand["name"] == "PropertyQuarry"
    assert fallback_brand["app_home"] == "/app/search"
    assert fallback_brand["repo_url"] == "https://github.com/ArchonMegalon/property"

    source = (Path(__file__).resolve().parents[1] / "ea/app/services/public_branding.py").read_text(encoding="utf-8")
    assert "Executive Assistant" not in source
    assert "/app/today" not in source
    assert "PROPERTYQUARRY_DEFAULT_BRAND" not in source


def test_propertyquarry_account_surfaces_do_not_use_ea_channel_copy() -> None:
    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "ea/app/api/routes/landing.py",
        root / "ea/app/api/routes/landing_channel.py",
        root / "ea/app/api/routes/landing_setup.py",
        root / "ea/app/api/routes/admin_view_models.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)

    assert "Record where EA will operate" not in combined
    assert "After confirmation, EA will return" not in combined
    assert "EA will continue using this lane" not in combined
    assert "Executive Workspace" not in combined
    assert "PropertyQuarry will return" in combined


def test_propertyquarry_public_and_progress_surfaces_do_not_use_generic_ea_copy() -> None:
    root = Path(__file__).resolve().parents[1]
    console_shell = (root / "ea/app/templates/console_shell.html").read_text(encoding="utf-8")
    pdf_renderer = (root / "ea/app/services/fliplink/pdf_renderer.py").read_text(encoding="utf-8")
    rendered_result = public_results._result_html({})

    assert "EA post-filtered" not in console_shell
    assert "PropertyQuarry applied" in console_shell
    assert "Recurring checkout is not live" not in console_shell
    assert "Request access from pricing." in console_shell
    assert "Vienna property page" not in pdf_renderer
    assert "PropertyQuarry Result" in rendered_result
    assert "PropertyQuarry public result viewer" in rendered_result
    assert "EA Result" not in rendered_result
    assert "EA public result viewer" not in rendered_result


def test_propertyquarry_research_investment_rows_use_listing_currency(monkeypatch) -> None:
    monkeypatch.setattr(landing_property_research, "_property_investment_research_access_level", lambda *args, **kwargs: "full")
    monkeypatch.setattr(
        landing_property_research,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 420000.0,
            "current_area_sqm": 80.0,
            "current_price_per_sqm_eur": 5250.0,
            "market_buy_per_sqm_eur": 5400.0,
            "market_buy_delta_pct": -2.8,
            "market_rent_per_sqm_eur": 22.25,
            "expected_monthly_rent_eur": 1650.0,
            "gross_yield_pct": 4.7,
            "payback_years": 21.2,
            "buy_sample_count": 2,
            "rent_sample_count": 2,
            "buy_samples": [{"title": "London comp", "per_sqm_eur": 5400.0, "source_label": "Rightmove"}],
            "rent_samples": [{"title": "London rent comp", "per_sqm_eur": 22.25, "source_label": "Rightmove"}],
        },
    )

    rows, _risk_rows = landing_property_research._property_investment_research_rows(
        property_url="https://example.test/london-flat",
        facts={
            "country_code": "GB",
            "currency_code": "GBP",
            "price_display": "GBP 420000",
            "area_sqm": 80,
            "postal_name": "London SW1",
        },
        preferences={"country_code": "GB"},
        commercial={},
        requested=True,
    )
    detail_text = "\n".join(f"{row.get('title')} {row.get('detail')}" for row in rows)

    assert "GBP 420 000 over 80.0 m2" in detail_text
    assert "Market buy benchmark is about GBP 5 400/m2." in detail_text
    assert "About GBP 1 650 (GBP 22.25/m2)" in detail_text
    assert "London comp | 5400.0 GBP/m2" in detail_text
    assert " EUR" not in detail_text


def test_property_research_investment_auto_mode_requires_explicit_request() -> None:
    preferences = {
        "listing_mode": "buy",
        "investment_research_mode": "auto",
    }
    commercial = {"investment_research_level": "full"}

    assert (
        landing_property_research._property_investment_research_access_level(
            preferences,
            commercial,
            requested=False,
        )
        == "off"
    )
    assert (
        landing_property_research._property_investment_research_access_level(
            preferences,
            commercial,
            requested=True,
        )
        == "full"
    )


def test_propertyquarry_research_packet_extracts_non_eur_price_display() -> None:
    facts = landing_property_research._property_enriched_candidate_facts(
        candidate={
            "title": "Two bedroom flat | GBP 420000 | 80 m2",
            "summary": "London SW1.",
            "property_facts": {"country_code": "GB", "postal_name": "London SW1"},
        }
    )
    rows = landing_property_research._property_fact_rows(facts)
    row_text = "\n".join(f"{row.get('title')} {row.get('detail')}" for row in rows)

    assert facts["currency_code"] == "GBP"
    assert facts["price_display"] == "GBP 420000"
    assert "Price GBP 420 000" in row_text
    assert "Price 420000.0 EUR" not in row_text


def test_propertyquarry_research_money_display_accepts_market_currency() -> None:
    assert landing_property_research._property_research_money_display(420000, currency_code="GBP") == "GBP 420,000"
    assert landing_property_research._property_research_money_display("£420,000", currency_code="GBP") == "GBP 420,000"


def test_propertyquarry_search_surface_prewarm_touches_templates_and_catalogs(monkeypatch) -> None:
    landing_routes.prewarm_property_search_surface_cache.cache_clear()
    landing_routes._property_country_catalog_snapshot_json.cache_clear()
    loaded_templates: list[str] = []
    catalog_calls: list[tuple[str, tuple[str, ...]]] = []
    provider_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        landing_routes.templates.env,
        "get_template",
        lambda name: loaded_templates.append(str(name)) or object(),
    )
    monkeypatch.setattr(landing_routes, "property_country_options", lambda: [{"value": "AT", "label": "Austria"}])
    monkeypatch.setattr(landing_routes, "property_provider_options", lambda *, country_code: provider_calls.append(("providers", country_code)) or [])
    monkeypatch.setattr(landing_routes, "property_evidence_source_options", lambda *, country_code: provider_calls.append(("evidence", country_code)) or [])
    monkeypatch.setattr(landing_routes, "default_language_for_country", lambda country_code: provider_calls.append(("language", country_code)) or "de")
    monkeypatch.setattr(
        landing_routes,
        "default_platforms_for_country_listing_mode",
        lambda country_code, mode: provider_calls.append((f"default:{mode}", country_code)) or [],
    )
    monkeypatch.setattr(
        landing_view_models,
        "_property_region_catalog_by_country",
        lambda country_codes: catalog_calls.append(("regions", tuple(country_codes))) or {},
    )
    monkeypatch.setattr(
        landing_view_models,
        "_property_market_filter_capabilities_catalog",
        lambda country_codes: catalog_calls.append(("capabilities", tuple(country_codes))) or {},
    )
    monkeypatch.setattr(
        landing_view_models,
        "_property_location_catalog_by_country_region",
        lambda country_codes: catalog_calls.append(("locations", tuple(country_codes))) or {},
    )

    assert landing_routes.prewarm_property_search_surface_cache() is True

    assert "propertyquarry_home.html" in loaded_templates
    assert "app/property_decision_workbench.html" in loaded_templates
    assert ("regions", ("AT",)) in catalog_calls
    assert ("locations", ("AT",)) in catalog_calls
    assert ("providers", "AT") in provider_calls
    assert ("default:rent", "AT") in provider_calls
    assert ("default:buy", "AT") in provider_calls
    landing_routes.prewarm_property_search_surface_cache.cache_clear()
    landing_routes._property_country_catalog_snapshot_json.cache_clear()


def test_propertyquarry_usage_page_uses_property_usage_language() -> None:
    client = build_property_client(principal_id="exec-property-usage-copy")
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    page = client.get("/app/settings/usage")

    assert page.status_code == 200
    assert "Usage and activation" in page.text
    assert "Search runs, ranked homes, filtered homes" in page.text
    assert "Property usage" in page.text
    assert "Ranked homes" in page.text
    assert "Sources used" in page.text
    assert "Source checks" not in page.text
    forbidden_copy = (
        "Current office loop",
        "Queue pressure, memo activity",
        "operator load",
        "Memo items",
        "Commitments",
        "Handoffs",
        "Draft approvals granted",
        "Commitment closed",
        "Memo open rate",
    )
    for marker in forbidden_copy:
        assert marker not in page.text


def test_propertyquarry_plan_page_uses_property_plan_language() -> None:
    client = build_property_client(principal_id="exec-property-plan-copy")
    start_workspace(client, mode="personal", workspace_name="PropertyQuarry")

    page = client.get("/app/settings/plan", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "PropertyQuarry plan" in page.text
    assert "Collaborator seats" in page.text
    assert "market update, review queue, follow-up ledger, review workflow" in page.text
    assert "draft review" not in page.text
    assert "PropertyQuarry pilot with one account owner and one collaborator." in page.text
    forbidden_copy = (
        "morning memo",
        "commitment ledger",
        "Google-first pilot with one executive and one operator.",
        "Operator seats",
    )
    for marker in forbidden_copy:
        assert marker not in page.text


def test_propertyquarry_search_shell_prewarm_builds_search_payload(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class _Auth:
        default_principal_id = "principal-default"

    class _Settings:
        auth = _Auth()

    class _Onboarding:
        def status(self, *, principal_id: str):
            calls.append(("status", principal_id))
            return {"workspace": {"name": "Prewarm"}, "channels": {}, "property_search_preferences": {}}

    class _Container:
        settings = _Settings()
        onboarding = _Onboarding()

    def fake_console_context(**kwargs):
        calls.append(("context", kwargs["surface_mode"]))
        return {"preferences": {}, "commercial": {}}

    def fake_workspace_payload(section: str, *, status: dict[str, object], property_state: dict[str, object]):
        calls.append(("payload", section))
        return {"title": "Search", "stats": [], "console_form": {}}

    monkeypatch.setattr(landing_routes, "_property_console_context", fake_console_context)
    monkeypatch.setattr(landing_routes, "_property_workspace_payload", fake_workspace_payload)
    monkeypatch.setattr(landing_routes.templates.env, "get_template", lambda name: calls.append(("template", name)) or object())

    assert landing_routes.prewarm_property_search_shell_cache(container=_Container()) is True

    assert ("status", "principal-default") in calls
    assert ("context", "search") in calls
    assert ("payload", "search") in calls
    assert ("template", "app/property_decision_workbench.html") in calls


def test_propertyquarry_properties_surface_returns_404_for_missing_explicit_run(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-missing-properties-run")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    monkeypatch.setattr(ProductService, "get_property_search_run_status", lambda self, *, principal_id, run_id: None)

    response = client.get(
        "/app/properties",
        params={"run_id": "run-missing"},
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "property_search_run_not_found"


def test_propertyquarry_shortlist_surface_returns_404_for_missing_explicit_run(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-missing-shortlist-run")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    monkeypatch.setattr(ProductService, "get_property_search_run_status", lambda self, *, principal_id, run_id: None)

    response = client.get(
        "/app/shortlist",
        params={"run_id": "run-missing"},
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "property_search_run_not_found"


def test_propertyquarry_search_form_does_not_scan_active_runs_without_explicit_run(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-no-active-run-scan")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    calls: list[str] = []

    def _fake_find_active(self, *, principal_id: str, limit: int = 8):
        calls.append(principal_id)
        return {}

    monkeypatch.setattr(ProductService, "find_active_property_search_run", _fake_find_active)

    response = client.get(
        "/app/search",
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert calls == []


def test_propertyquarry_results_fallback_preview_prefers_candidate_pin_map_over_boundary_overlay(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda label: (48.183, 16.337))
    monkeypatch.setattr(
        landing_view_models,
        "_build_scope_boundary_preview",
        lambda **kwargs: {"image_url": "data:image/svg+xml;utf8,boundary", "summary": "Boundary preview"},
    )
    preview = landing_property_workspace_helpers._property_candidate_orientation_preview(
        {
            "title": "Unbefristete 2-Zimmer Wohnung",
            "summary": "(1100 Wien)",
            "property_facts": {},
        }
    )
    assert str(preview["image_url"]).startswith("data:image/")
    assert "boundary" not in str(preview["image_url"])
    assert preview["image_url"] == preview["thumb_image_url"]


def test_propertyquarry_search_route_does_not_use_generic_workspace_search(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-route")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _explode(*args, **kwargs):
        raise AssertionError("generic workspace search should not run for PropertyQuarry /app/search")

    monkeypatch.setattr(ProductService, "search_workspace", _explode)

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert 'data-property-decision-workbench' in response.text
    assert "Search people, threads, commitments, decisions, deadlines, evidence, rules, and handoffs." not in response.text


def test_propertyquarry_shortlist_without_run_id_prefers_latest_terminal_run_with_results(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-shortlist-latest-results")
    start_workspace(client, mode="personal", workspace_name="Shortlist Latest Results Office")

    def _fake_runs(self, *, principal_id: str, limit: int = 8, hydrate: bool = True):
        assert hydrate is False
        return [
            {
                "run_id": "run-empty-terminal",
                "principal_id": principal_id,
                "status": "completed_partial",
                "updated_at": "2026-06-17T15:10:00+00:00",
                "summary": {"status": "completed_partial", "ranked_candidates": []},
            },
            {
                "run_id": "run-ranked-terminal",
                "principal_id": principal_id,
                "status": "completed_partial",
                "updated_at": "2026-06-17T15:00:00+00:00",
                "summary": {
                    "status": "completed_partial",
                    "ranked_candidates": [
                        {
                            "title": "Praterstrasse flat",
                            "fit_score": 54.0,
                            "packet_url": "/app/research/prater-flat?run_id=run-ranked-terminal",
                            "property_url": "https://www.willhaben.at/iad/object?adId=1134225012",
                            "property_facts": {"postal_name": "1020 Wien", "price_display": "€ 1.598"},
                        }
                    ],
                },
            },
        ]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        raise AssertionError("shortlist should use the lightweight run-list snapshot when it already contains ranked candidates")

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/shortlist", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Praterstrasse flat" in response.text


def test_propertyquarry_shortlist_without_runs_renders_actionable_empty_state() -> None:
    client = build_property_client(principal_id="pq-shortlist-empty-state")
    start_workspace(client, mode="personal", workspace_name="Shortlist Empty State Office")

    response = client.get("/app/shortlist", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "No saved shortlist yet." in response.text
    assert "Shortlisted homes stay here across searches until you remove them." in response.text
    assert 'href="/app/search"' in response.text
    assert 'href="/app/agents"' in response.text
    assert 'data-pqx-results-empty-state' in response.text


def test_property_suppression_rows_synthesizes_generic_breakdown_from_aggregate_filtered_total() -> None:
    rows = landing_property_workspace_helpers._property_suppression_rows(
        run_summary={"filtered_total": 58, "held_back_total": 58},
        source_rows=[],
        preferences={"location_query": "1010 Vienna"},
    )

    assert rows
    assert rows[0]["affected_total"] == 58
    assert rows[0]["action_label"] == "Adjust filters"


def test_propertyquarry_running_panel_prefers_listing_snapshot_location_over_source_scope_placeholder(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-running-location-truth")
    start_workspace(client, mode="personal", workspace_name="Running Location Truth Office")

    def _fake_active_run(self, *, principal_id: str):
        return {"run_id": "run-live-1020", "status": "in_progress"}

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "status_label": "Search in progress",
            "progress": 47,
            "message": "Prepared property page for expat flat.",
            "summary": {
                "status": "in_progress",
                "reviewed_listing_total": 12,
                "ranked_candidates": [
                    {
                        "title": "expat flat",
                        "fit_score": 61.0,
                        "price_display": "EUR 1,598",
                        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                        "source_url": "https://www.willhaben.at/iad/object?adId=1134225012",
                        "preview_image_url": "https://img.example.com/demo-1020.jpg",
                        "property_facts": {
                            "postal_name": "1010 Vienna",
                            "listing_research_snapshot": {
                                "postal_name": "1020 Wien",
                                "address": "1020 Wien",
                            },
                        },
                    }
                ],
                "sources": [],
            },
        }

    monkeypatch.setattr(ProductService, "find_active_property_search_run", _fake_active_run)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", params={"run_id": "run-live-1020"}, headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "1020 Wien" in response.text


def test_propertyquarry_search_route_renders_what_matters_as_comboboxes() -> None:
    client = build_property_client(principal_id="pq-what-matters-comboboxes")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    html = response.text

    section_match = re.search(
        r'<section[^>]*data-property-what-matters-panel[^>]*>(?P<section>.*?)</section>',
        html,
        re.DOTALL,
    )
    assert section_match, "What matters panel should render"
    section_html = section_match.group("section")
    assert "What matters" in section_html
    assert "Neutral by default" in section_html
    assert "Home basics" in section_html
    assert "Daily life" in section_html
    assert "Risk and evidence" in section_html
    assert "Schools and childcare" in section_html
    assert 'data-what-matters-group="home_basics"' in section_html
    assert 'data-what-matters-group="daily_life"' in section_html
    assert 'data-what-matters-group="risk_evidence"' in section_html
    assert 'data-what-matters-group="schools"' in section_html
    assert '<select name="keyword_preference__lift"' in section_html
    assert '<select name="keyword_preference__barrier-free"' in section_html
    assert '<select name="keyword_distance__playground nearby"' in section_html
    assert '<select name="keyword_preference__library nearby"' in section_html
    assert '<select name="keyword_preference__public pool nearby"' in section_html
    assert '<select name="keyword_preference__medical care nearby"' in section_html
    assert 'data-keyword-display-key="hardware-store"' in section_html
    assert 'data-keyword-display-key="shopping-center"' in section_html
    assert 'data-keyword-display-key="promenade"' in section_html
    assert '<select name="school_preference__kindergarten"' in section_html
    assert '<select name="school_preference__volksschule"' in section_html
    assert '<select name="school_preference__gymnasium"' in section_html
    assert 'data-school-parent-value="kindergarten"' in section_html
    assert 'data-school-parent-value="volksschule"' in section_html
    assert 'data-school-dependent-row' in section_html
    assert 'data-preference-state="any"' in section_html
    assert 'name="school_preference__public_kindergarten"' in section_html
    assert 'name="school_preference__private_kindergarten"' in section_html
    assert 'name="school_preference__ganztags_volksschule"' in section_html
    assert 'name="school_preference__halbtags_volksschule"' in section_html
    assert "General kindergarten coverage nearby" not in section_html
    assert "Primary school nearby" not in section_html
    assert "Full-day primary school nearby" not in section_html
    assert "General kindergarten coverage" in section_html
    assert "Primary school coverage" in section_html
    assert "Full-day primary school coverage" in section_html
    assert 'data-keyword-distance-select' in section_html
    assert 'data-keyword-distance-enabled="false"' in section_html
    assert 'name="keyword_distance__playground nearby" data-keyword-distance-select data-keyword-value="playground nearby" disabled' in section_html
    assert ">Neutral</option>" in section_html
    assert '.pqx-what-matters-panel .pqx-choice-groupbox {\n      grid-column: 1 / -1;' in html
    assert 'grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));' in html
    assert 'grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));' in html
    assert '.pqx-what-matters-panel .pqx-keyword-priority-row[data-keyword-distance-enabled="true"] > div' in html
    assert "overflow-wrap: break-word;" in html
    assert ".pqx-what-matters-panel .pqx-school-priority-row {" in html
    template_source = (
        Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    ).read_text(encoding="utf-8")
    assert "field.get('school_preference_options')" in template_source
    assert 'type="checkbox"' not in section_html
    assert 'data-property-advanced-panel="children"' not in html
    assert 'data-property-advanced-panel="location_research"' not in html
    assert 'data-property-field-step="children" data-property-field-name="keywords"' in html
    assert 'data-property-field-name="enable_lifestyle_research" hidden' in html
    assert re.search(
        r'data-property-field-name="max_distance_to_supermarket_m"[^>]*data-property-semantic-hidden="true"[^>]*hidden',
        html,
    )
    assert re.search(
        r'data-property-field-name="require_school_evidence"[^>]*data-property-semantic-hidden="true"[^>]*hidden',
        html,
    )
    assert re.search(
        r'data-property-field-name="school_stage_preferences"[^>]*data-property-semantic-hidden="true"[^>]*hidden',
        html,
    )
    assert re.search(
        r'data-property-field-name="max_distance_to_library_m"[^>]*data-property-semantic-hidden="true"[^>]*hidden',
        html,
    )
    assert 'data-property-field-name="use_stored_feedback_preferences"' not in html
    assert 'data-property-field-name="preference_person_id"' not in html
    assert "Use stored feedback preferences" not in html
    assert "Manage feedback preferences" not in html
    assert 'Load my what matters' in section_html
    assert 'Save my what matters' in section_html
    assert '>What<' in html
    assert '>What matters<' in html
    assert '>Home shape<' not in html


def test_propertyquarry_search_route_disables_unimplemented_providers() -> None:
    client = build_property_client(principal_id="pq-provider-coming-soon")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    html = response.text

    assert 'value="community_signals_at"' in html
    assert re.search(r'value="community_signals_at"\s+disabled', html)
    assert 'Coming soon' in html


def test_propertyquarry_localhost_brand_uses_request_origin_for_public_base() -> None:
    client = build_property_client(principal_id="pq-localhost-brand")
    response = client.get("/sitemap.xml", headers={"host": "localhost:8097"})
    assert response.status_code == 200
    assert "localhost:8097/" in response.text


def test_propertyquarry_search_route_skips_heavy_run_status_hydration() -> None:
    from app.product.service import ProductService

    client = build_property_client(principal_id="pq-search-lightweight")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
        },
    )

    original_find_active = ProductService.find_active_property_search_run
    original_get_status = ProductService.get_property_search_run_status
    find_active_calls: list[str] = []

    def fake_find_active(self, *, principal_id: str, limit: int = 8):
        find_active_calls.append(principal_id)
        return {
            "run_id": "run-active-lightweight",
            "status": "in_progress",
            "message": "Scanning providers.",
            "progress": 18,
            "status_url": "/app/api/signals/property/search/run/run-active-lightweight",
            "summary": {"sources_total": 2},
        }

    def fail_get_status(self, *, principal_id: str, run_id: str):
        raise AssertionError("search route should not hydrate full run status without explicit run_id")

    ProductService.find_active_property_search_run = fake_find_active
    ProductService.get_property_search_run_status = fail_get_status
    try:
        response = client.get("/app/search")
    finally:
        ProductService.find_active_property_search_run = original_find_active
        ProductService.get_property_search_run_status = original_get_status

    assert response.status_code == 200
    assert find_active_calls == []
    assert "run-active-lightweight" not in response.text


def test_propertyquarry_search_route_skips_first_paint_side_effects(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-first-paint")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def fail_search_first_paint(*args, **kwargs):
        raise AssertionError("search first paint should not hydrate profile, saved shortlist, or write events")

    monkeypatch.setattr(ProductService, "get_preference_profile", fail_search_first_paint)
    monkeypatch.setattr(ProductService, "property_feedback_learning_summary", fail_search_first_paint)
    monkeypatch.setattr(ProductService, "list_property_saved_shortlist_candidates", fail_search_first_paint)
    monkeypatch.setattr(ProductService, "record_surface_event", fail_search_first_paint)

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert 'data-property-decision-workbench' in response.text


def test_propertyquarry_search_route_trims_heavy_workbench_state() -> None:
    client = build_property_client(principal_id="pq-search-trimmed")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "1010 Vienna",
            "saved_shortlist_candidates": [
                {"candidate_ref": "candidate-1", "title": "Huge saved candidate", "detail": "x" * 5000}
            ],
        },
    )
    assert stored.status_code == 200

    response = client.get("/app/search")
    assert response.status_code == 200
    match = re.search(r'<script type="application/json" data-property-workbench-json>(.*?)</script>', response.text, re.S)
    assert match, "workbench JSON should render"
    payload = json.loads(match.group(1))
    assert payload["brief_preferences"].get("saved_shortlist_candidates") in (None, [])
    assert "raw_preferences" not in payload["brief_preferences"]
    assert "search_agents" not in payload["brief_preferences"]
    assert payload.get("search_agents") == []
    assert payload.get("search_agent") == {}
    assert payload.get("previous_search_runs") == []
    assert "https://propertyquarry.com/" not in response.text


def test_propertyquarry_properties_route_does_not_duplicate_heavy_run_payload(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-properties-heavy-run")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    heavy_blob = "x" * 5000

    def _fake_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "progress": 34,
            "property_search_preferences": {
                "country_code": "AT",
                "location_query": "1010 Vienna",
                "raw_preferences": {"huge": heavy_blob},
                "saved_shortlist_candidates": [{"candidate_ref": "saved", "detail": heavy_blob}],
                "search_agents": [{"id": "agent", "detail": heavy_blob}],
            },
            "summary": {
                "status": "in_progress",
                "sources_total": 1,
                "listing_total": 4,
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                        "status": "in_progress",
                        "listing_total": 4,
                        "source_html": heavy_blob,
                        "raw_payload": {"html": heavy_blob},
                    }
                ],
            },
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_status)

    response = client.get("/app/properties?run_id=run-heavy", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert "source_html" not in response.text
    assert heavy_blob not in response.text
    workbench_match = re.search(
        r'<script type="application/json" data-property-workbench-json>(.*?)</script>',
        response.text,
        re.S,
    )
    assert workbench_match
    workbench_payload = json.loads(html.unescape(workbench_match.group(1)))
    assert "source_html" not in json.dumps(workbench_payload)
    assert "raw_preferences" not in workbench_payload["brief_preferences"]
    assert "saved_shortlist_candidates" not in workbench_payload["brief_preferences"]
    assert "search_agents" not in workbench_payload["brief_preferences"]
    meta_match = re.search(r"<div hidden data-property-workspace-meta='(.*?)'></div>", response.text, re.S)
    assert meta_match
    property_meta = json.loads(html.unescape(meta_match.group(1)))
    assert "initial_run" not in property_meta


def test_propertyquarry_search_route_exposes_theme_toggle() -> None:
    client = build_property_client(principal_id="pq-theme-toggle")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    html = response.text

    assert 'data-pqx-theme-toggle' in html
    assert 'propertyquarry.theme' in html
    assert 'data-pq-theme' in html
    assert 'Light mode' in html or 'Dark mode' in html


def test_propertyquarry_dark_mode_overrides_light_card_backgrounds() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workbench = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    sign_in = (repo_root / "ea/app/templates/sign_in.html").read_text(encoding="utf-8")
    packets = (repo_root / "ea/app/templates/app/property_packets.html").read_text(encoding="utf-8")

    required_dark_selectors = (
        'html[data-pq-theme="dark"] .pqx-field input:not([type="checkbox"])',
        'html[data-pq-theme="dark"] .pqx-range-label',
        'html[data-pq-theme="dark"] .pqx-range-value',
        'html[data-pq-theme="dark"] .pqx-tooltip[data-tooltip-open="true"]::after',
        'html[data-pq-theme="dark"] .pqx-choice-groupbox',
        'html[data-pq-theme="dark"] .pqx-what-matters-panel',
        'html[data-pq-theme="dark"] .pqx-automation-thumbnail',
        'html[data-pq-theme="dark"] .pqx-automation-delete',
        'html[data-pq-theme="dark"] .pqx-automation-history-table th',
        'html[data-pq-theme="dark"] .pqx-automation-card',
        'html[data-pq-theme="dark"] .pqx-account-action-card',
        'html[data-pq-theme="dark"] .pqx-account-channel-option',
        'html[data-pq-theme="dark"] .pqx-account-channel-detail',
        'html[data-pq-theme="dark"] .pqx-account-channel-detail input',
        'html[data-pq-theme="dark"] .pqx-account-card',
        'html[data-pq-theme="dark"] .pqx-billing-metric',
        'html[data-pq-theme="dark"] .pqx-billing-note-rail',
        'html[data-pq-theme="dark"] .pqx-billing-card',
        'html[data-pq-theme="dark"] .pqx-card',
        'html[data-pq-theme="dark"] .pqx-ooda-item',
        'html[data-pq-theme="dark"] .pqx-reading-card',
        'html[data-pq-theme="dark"] .pqx-event-card',
        'html[data-pq-theme="dark"] .pqx-source-card',
        'html[data-pq-theme="dark"] .pqx-filtered-dialog-card',
        'html[data-pq-theme="dark"] .pqx-filtered-dialog-rule',
        'html[data-pq-theme="dark"] .pqx-filtered-dialog-close',
        'html[data-pq-theme="dark"] .pqx-filter-radius-control',
        'html[data-pq-theme="dark"] .pqx-route-preview-card',
        'html[data-pq-theme="dark"] .pqx-result',
        'html[data-pq-theme="dark"] .pqx-result.is-top-ranked',
        'html[data-pq-theme="dark"] .pqx-result-panel',
        'html[data-pq-theme="dark"] .pqx-result-fact',
        'html[data-pq-theme="dark"] .pqx-result-fit-score',
        'html[data-pq-theme="dark"] .pqx-result-open',
        'html[data-pq-theme="dark"] .pqx-progress-button',
        'html[data-pq-theme="dark"] .pqx-progress-board',
        'html[data-pq-theme="dark"] .pqx-progress-meter',
        'html[data-pq-theme="dark"] .pqx-pulse-line',
        'html[data-pq-theme="dark"] .pqx-results-summary-link',
        'html[data-pq-theme="dark"] .pqx-run-chip',
        'html[data-pq-theme="dark"] .pqx-account-menu summary',
        'html[data-pq-theme="dark"] .pqx-source-progress',
        'html[data-pq-theme="dark"] .pqx-reliability-strip',
        'html[data-pq-theme="dark"] .pqx-worker-strip',
        'html[data-pq-theme="dark"] .pqx-worker-lane',
        'html[data-pq-theme="dark"] .pqx-worker-popover',
        'html[data-pq-theme="dark"] .pqx-source-chip',
        'html[data-pq-theme="dark"] textarea',
        'html[data-pq-theme="dark"] .pqx-research-value',
        'html[data-pq-theme="dark"] .pqx-empty',
        'html[data-pq-theme="dark"] .pqx-results-empty-state',
        'html[data-pq-theme="dark"] .pqx-bottom-nav',
        'html[data-pq-theme="dark"] .pqx-button.primary',
        'html[data-pq-theme="dark"] .pqx-link-button.primary',
        'html[data-pq-theme="dark"] .pqx-context-actions .pqx-link-button.primary',
        'html[data-pq-theme="dark"] .pqx-result[aria-selected="true"]',
        'html[data-pq-theme="dark"] .pqx-result-fact.recovered',
        'html[data-pq-theme="dark"] .pqx-progress-button.is-ready',
        'html[data-pq-theme="dark"] .pqx-progress-button.is-blocked',
        'html[data-pq-theme="dark"] .pqx-source-chip.good',
        'html[data-pq-theme="dark"] .pqx-source-chip.warn',
        'html[data-pq-theme="dark"] .pqx-worker-progress',
    )
    for selector in required_dark_selectors:
        assert selector in workbench
    assert "background: var(--pq-paper);" in workbench
    assert "color: var(--pq-ink);" in workbench
    assert "color: #171411;" in workbench
    assert "background: color-mix(in srgb, var(--panel) 88%, transparent);" in sign_in
    assert "auth-provider-card" in sign_in
    assert "--pq-card: #fffdf8;" in packets


def test_propertyquarry_shared_shells_apply_saved_dark_theme_tokens() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for relative in ("ea/app/templates/base_public.html", "ea/app/templates/base_console.html"):
        body = (repo_root / relative).read_text(encoding="utf-8")
        assert "propertyquarry.theme" in body
        assert 'html[data-pq-theme="dark"]' in body
        assert "--panel: #171c18;" in body
        assert "--text: #f2eee6;" in body
        assert "color-scheme: dark;" in body

    console_shell = (repo_root / "ea/app/templates/console_shell.html").read_text(encoding="utf-8")
    assert "background: var(--panel);" in console_shell
    assert "color: var(--text);" in console_shell
    assert "background: #ffffff;" not in console_shell
    assert 'html[data-pq-theme="dark"] .console-form[data-console-form-variant="property_search"] .console-advanced-panel' in console_shell
    assert 'html[data-pq-theme="dark"] .console-form[data-console-form-variant="property_search"] .console-range-help[data-tooltip-open="true"]::after' in console_shell
    assert 'html[data-pq-theme="dark"] .console-choice[data-school-stage-parent]' in console_shell
    assert 'html[data-pq-theme="dark"] .console-choice[data-school-stage-variant]' in console_shell

    base_console = (repo_root / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    assert 'html[data-pq-theme="dark"] .pq-rail' in base_console
    assert 'html[data-pq-theme="dark"] .pq-appbar' in base_console
    assert 'html[data-pq-theme="dark"] .pq-mobile-nav' in base_console

    base_public = (repo_root / "ea/app/templates/base_public.html").read_text(encoding="utf-8")
    assert 'html[data-pq-theme="dark"] .mobile-nav a' in base_public

    research_detail = (repo_root / "ea/app/templates/app/property_research_detail.html").read_text(encoding="utf-8")
    assert 'html[data-pq-theme="dark"] .prd-media-badge' in research_detail
    assert 'html[data-pq-theme="dark"] .prd-media-frame.prd-media-image-failed::before' in research_detail


def test_propertyquarry_search_route_does_not_scan_active_run_for_initial_form(monkeypatch) -> None:
    principal_id = "pq-search-live-run-banner"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    find_active_calls: list[str] = []

    def _explode(self, *, principal_id: str, limit: int = 8):
        assert principal_id == "pq-search-live-run-banner"
        raise AssertionError("search route should not hydrate the recent run list")

    def _fake_active_run(self, *, principal_id: str, limit: int = 8):
        assert principal_id == "pq-search-live-run-banner"
        find_active_calls.append(principal_id)
        return {"run_id": "run-live-42", "status": "in_progress", "summary": {"status": "in_progress"}}

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        raise AssertionError("search route should not hydrate full run status without explicit run_id")

    monkeypatch.setattr(ProductService, "list_property_search_runs", _explode)
    monkeypatch.setattr(ProductService, "find_active_property_search_run", _fake_active_run)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert find_active_calls == []
    assert "Live run" not in response.text
    assert "/app/properties?run_id=run-live-42" not in response.text


def test_propertyquarry_properties_route_redirects_to_search_without_a_run() -> None:
    client = build_property_client(principal_id="pq-properties-redirects-to-search")
    start_workspace(client, mode="personal", workspace_name="Search First Office")

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"


def test_propertyquarry_root_redirects_signed_in_users_to_search(monkeypatch) -> None:
    principal_id = "pq-root-search-redirect"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Root Search Redirect Office")

    monkeypatch.setattr(
        landing_routes,
        "build_product_service",
        lambda container: (_ for _ in ()).throw(AssertionError("propertyquarry root should not build the product service before redirecting")),
    )
    monkeypatch.setattr(landing_routes, "_workspace_session_payload", lambda request, container: {"principal_id": principal_id})
    monkeypatch.setattr(landing_routes, "_load_status", lambda container, access_identity, request=None: (principal_id, {}))

    response = client.get("/", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"


def test_propertyquarry_root_redirects_token_authenticated_users_but_keeps_home_escape(monkeypatch) -> None:
    principal_id = "pq-root-token-search-redirect"
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "test-token")
    monkeypatch.setenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", "1")

    from fastapi.testclient import TestClient
    from app.api.app import create_app

    client = TestClient(create_app(), base_url="https://propertyquarry.com")
    headers = {
        "host": "propertyquarry.com",
        "Authorization": "Bearer test-token",
        "X-EA-Principal-ID": principal_id,
    }
    monkeypatch.setattr(
        landing_routes,
        "build_product_service",
        lambda container: (_ for _ in ()).throw(AssertionError("root redirect should not build the product service")),
    )

    response = client.get("/", headers=headers, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"

    public_home = client.get("/?home=1", headers=headers, follow_redirects=False)
    assert public_home.status_code == 200
    assert "Search once. Rank the right homes. Decide with evidence." in public_home.text
    assert 'href="/?home=1" aria-label="PropertyQuarry home"' in public_home.text
    assert 'href="/app/search"' in public_home.text
    assert 'href="/app/properties"' in public_home.text
    assert 'href="/sign-in?signing_in=1"' not in public_home.text
    assert ">Sign in<" not in public_home.text
    assert "home_create_account" not in public_home.text
    assert "home_sign_in" not in public_home.text
    assert "Signing you in" not in public_home.text
    assert 'data-target-endpoint="/app/api/property/landing-handoff"' not in public_home.text


def test_propertyquarry_root_home_query_renders_public_home_when_signed_in(monkeypatch) -> None:
    principal_id = "pq-root-public-home"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Root Public Home Office")

    monkeypatch.setattr(
        landing_routes,
        "build_product_service",
        lambda container: (_ for _ in ()).throw(AssertionError("propertyquarry public home should not build the product service")),
    )
    monkeypatch.setattr(landing_routes, "_workspace_session_payload", lambda request, container: {"principal_id": principal_id})
    monkeypatch.setattr(landing_routes, "_load_status", lambda container, access_identity, request=None: (principal_id, {}))

    response = client.get("/?home=1", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert response.status_code == 200
    assert "Search once. Rank the right homes. Decide with evidence." in response.text
    assert 'href="/app/search"' in response.text
    assert 'href="/app/properties"' in response.text
    assert 'href="/sign-in?signing_in=1"' not in response.text
    assert ">Sign in<" not in response.text
    assert "home_create_account" not in response.text
    assert "home_sign_in" not in response.text
    assert "Signing you in" not in response.text
    assert 'data-target-endpoint="/app/api/property/landing-handoff"' not in response.text


def test_propertyquarry_root_hints_signing_in_from_query_flags() -> None:
    client = build_property_client()
    response = client.get("/?signing_in=1&signing=yes", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Signing you in" in response.text
    assert 'data-target-endpoint="/app/api/property/landing-handoff"' in response.text
    assert "home_create_account" not in response.text
    assert "href=\"/app/search\"" in response.text


def test_propertyquarry_root_hints_signing_in_from_oauth_callback_params() -> None:
    client = build_property_client()
    response = client.get("/?code=oauth-code&state=oauth-state", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Signing you in" in response.text
    assert 'data-target-endpoint="/app/api/property/landing-handoff"' in response.text


def test_propertyquarry_root_localhost_signed_in_does_not_redirect_to_public_host(monkeypatch) -> None:
    principal_id = "pq-root-localhost-fast-landing"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Root Localhost Landing Office")

    monkeypatch.setattr(landing_routes, "_workspace_session_payload", lambda request, container: {"principal_id": principal_id})
    monkeypatch.setattr(landing_routes, "_load_status", lambda container, access_identity, request=None: (principal_id, {}))

    response = client.get("/", headers={"host": "localhost:8097"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"
    assert "https://propertyquarry.com/app/search" not in response.headers["location"]


def test_propertyquarry_landing_handoff_prefers_active_run(monkeypatch) -> None:
    principal_id = "pq-landing-handoff-run"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Landing Handoff Run Office")

    def _fake_active_run(self, *, principal_id: str, limit: int = 8):
        assert principal_id == "pq-landing-handoff-run"
        return {"run_id": "run-live-42", "status": "in_progress"}

    monkeypatch.setattr(ProductService, "find_active_property_search_run", _fake_active_run)
    monkeypatch.setattr(landing_routes, "_workspace_session_payload", lambda request, container: {"principal_id": principal_id})
    monkeypatch.setattr(landing_routes, "_load_status", lambda container, access_identity, request=None: (principal_id, {}))

    response = client.get("/app/api/property/landing-handoff", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert response.json()["target"] == "/app/properties?run_id=run-live-42"


def test_propertyquarry_landing_handoff_falls_back_to_search(monkeypatch) -> None:
    principal_id = "pq-landing-handoff-search"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Landing Handoff Search Office")

    monkeypatch.setattr(ProductService, "find_active_property_search_run", lambda self, *, principal_id, limit=8: {})
    monkeypatch.setattr(landing_routes, "_workspace_session_payload", lambda request, container: {"principal_id": principal_id})
    monkeypatch.setattr(landing_routes, "_load_status", lambda container, access_identity, request=None: (principal_id, {}))

    response = client.get("/app/api/property/landing-handoff", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert response.json()["target"] == "/app/search"


def test_property_provider_options_expose_homepage_links() -> None:
    options = property_market_catalog.provider_options(country_code="AT")
    willhaben = next(option for option in options if option["value"] == "willhaben")
    assert willhaben["homepage_url"] == "https://www.willhaben.at"
    community_signals = next(option for option in options if option["value"] == "community_signals_at")
    assert community_signals["search_ready"] is False
    assert community_signals["coming_soon"] is True
    assert community_signals["availability_note"] == "Coming soon"


def test_property_surface_state_normalizes_search_run_snapshot() -> None:
    snapshot = property_surface_state.normalize_property_search_run_snapshot(
        {
            "run_id": "run-123",
            "summary": {"status": "completed", "listing_total": 12},
            "preferences": {"country_code": "AT"},
            "active_search_agent_id": "agent-1",
        }
    )
    assert snapshot["run_id"] == "run-123"
    assert snapshot["status"] == "completed"
    assert snapshot["property_search_preferences"] == {"country_code": "AT"}
    assert snapshot["active_search_agent_id"] == "agent-1"


def test_property_surface_state_builds_billing_truth_snapshot() -> None:
    snapshot = property_surface_state.build_property_billing_truth_snapshot(
        commercial={
            "current_plan_label": "Agent",
            "current_plan_key": "agent",
            "research_depth": "deep",
            "max_platforms": 12,
            "max_results_per_source": 5,
        },
        default_billing_plan="agent",
        billing_enabled_plans=["plus", "agent"],
        billing_order_endpoints_by_plan={"agent": "/billing/order"},
        billing_provider_labels_by_plan={"agent": "PayFunnels"},
        fleet_digest={"summary": "Visible"},
    )
    assert snapshot["current_plan_label"] == "Agent"
    assert snapshot["checkout_provider"] == "payfunnels"
    assert snapshot["order_endpoint"] == "/billing/order"
    assert snapshot["fleet_digest"] == {"summary": "Visible"}


def test_property_surface_state_builds_preference_manager_snapshot() -> None:
    snapshot = property_surface_state.build_property_preference_manager_snapshot(
        person_id="self",
        raw_preference_nodes=[
            {
                "node_id": "node-1",
                "domain": "willhaben",
                "category": "constraint",
                "key": "budget_max",
                "value_json": 900000,
                "strength": "high",
                "status": "active",
            }
        ],
        include_full_manager=True,
        schema={"keys": ["budget_max"]},
    )
    assert snapshot["person_id"] == "self"
    assert snapshot["schema"] == {"keys": ["budget_max"]}
    assert snapshot["nodes"][0]["label"] == "Budget Max (Constraint)"
    assert snapshot["active_nodes"][0]["node_id"] == "node-1"


def test_property_surface_state_builds_run_health_snapshot() -> None:
    snapshot = property_surface_state.build_property_run_health_snapshot(
        {
            "run_id": "run-123",
            "status": "in_progress",
            "progress": 42,
            "eta_label": "about 3 min",
            "summary": {
                "sources_total": 4,
                "listing_total": 18,
                "filtered_low_fit_total": 6,
            },
            "open_research_task_total": 2,
            "research_task_total": 5,
        }
    )
    assert snapshot["run_id"] == "run-123"
    assert snapshot["status"] == "in_progress"
    assert snapshot["status_label"] == "Running"
    assert snapshot["progress"] == 42
    assert snapshot["in_progress"] is True
    assert snapshot["source_total"] == 4
    assert snapshot["listing_total"] == 18
    assert snapshot["filtered_total"] == 0
    assert snapshot["research_task_total"] == 5
    assert snapshot["open_research_task_total"] == 2


def test_property_surface_state_builds_filtered_total_from_summary_components() -> None:
    snapshot = property_surface_state.build_property_run_health_snapshot(
        {
            "run_id": "run-123",
            "status": "processed",
            "summary": {
                "filtered_area_total": 18,
                "filtered_floorplan_total": 4,
                "filtered_listing_mode_total": 2,
                "filtered_generic_page_total": 1,
                "filtered_low_fit_total": 7,
                "notification_budget_suppressed_total": 3,
            },
        }
    )
    assert snapshot["held_back_total"] == 25
    assert snapshot["filtered_total"] == 25


def test_property_saved_shortlist_candidates_persist_across_runs() -> None:
    client = build_property_client(principal_id="pq-saved-shortlist")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    product = build_product_service(client.app.state.container)

    saved = product.persist_property_saved_shortlist_candidates(
        principal_id="pq-saved-shortlist",
        run_id="run-1",
        candidates=[
            {
                "candidate_ref": "cand-1",
                "property_url": "https://example.test/property-1",
                "title": "Property One",
                "rank": 1,
            }
        ],
    )
    assert len(saved) == 1

    saved = product.persist_property_saved_shortlist_candidates(
        principal_id="pq-saved-shortlist",
        run_id="run-2",
        candidates=[
            {
                "candidate_ref": "cand-2",
                "property_url": "https://example.test/property-2",
                "title": "Property Two",
                "rank": 1,
            }
        ],
    )
    assert len(saved) == 2

    visible = product.list_property_saved_shortlist_candidates(principal_id="pq-saved-shortlist")
    assert [row["property_ref"] for row in visible] == [
        "https://example.test/property-2",
        "https://example.test/property-1",
    ]


def test_property_lookup_candidate_falls_back_to_ranked_candidates() -> None:
    candidate = {
        "title": "Ranked-only home",
        "property_url": "https://example.test/listing/1",
        "source_ref": "property-scout:ranked-only",
        "source_label": "Provider | Austria | Rent | Vienna",
    }
    candidate_ref = landing_property_research._property_candidate_ref(candidate)
    property_context = {
        "run": {
            "run_id": "run-ranked-only",
            "summary": {
                "ranked_candidates": [candidate],
                "sources": [],
            },
        }
    }

    resolved = landing_property_research._property_lookup_candidate(
        property_context=property_context,
        candidate_ref=candidate_ref,
    )

    assert resolved is not None
    assert resolved["title"] == "Ranked-only home"


def test_property_surface_state_previous_run_summary_uses_status_copy() -> None:
    summary = property_surface_state.build_property_previous_run_summary(
        {
            "run_id": "run-9",
            "status": "failed",
            "message": "stalled",
            "summary": {"status": "failed"},
            "preferences": {"country_code": "AT", "location_query": "Vienna", "listing_mode": "buy"},
        },
        include_scope_preview=False,
        scope_preview_builder=lambda country, region, location: {"summary": f"{country}:{region}:{location}"},
        compact_provider_label=lambda label: label,
        candidate_maps_url_builder=lambda candidate: "",
    )
    assert summary["status_label"] == "Search failed"
    assert summary["status_note"] == "stalled"
    assert summary["is_finished"] is True


def test_property_surface_state_previous_run_price_fallback_uses_catalog_currencies() -> None:
    summary = property_surface_state.build_property_previous_run_summary(
        {
            "run_id": "run-cad",
            "status": "processed",
            "summary": {
                "ranked_candidates": [
                    {
                        "title": "Detached home in Toronto | CAD 825,000 | 140 m2",
                        "property_facts": {"postal_name": "Toronto", "area_sqm": 140},
                    }
                ]
            },
            "preferences": {"country_code": "CA", "location_query": "Toronto", "listing_mode": "buy"},
        },
        include_scope_preview=False,
        scope_preview_builder=lambda country, region, location: {"summary": f"{country}:{region}:{location}"},
        compact_provider_label=lambda label: label,
        candidate_maps_url_builder=lambda candidate: "",
    )

    assert summary["top_price_display"] == "CAD 825,000"
    assert summary["top_candidates"][0]["price_display"] == "CAD 825,000"


def test_property_surface_state_builds_shortlist_snapshot_and_preserves_rank_order() -> None:
    snapshot = property_surface_state.build_property_shortlist_snapshot(
        [
            {"candidate_ref": "a", "title": "A"},
            {"candidate_ref": "b", "title": "B"},
            {"candidate_ref": "c", "title": "C"},
        ],
        selected_candidate_ref="b",
    )
    assert snapshot["selected_candidate_ref"] == "b"
    assert snapshot["selected"]["title"] == "B"
    assert [row["candidate_ref"] for row in snapshot["results"]] == ["a", "b", "c"]
    assert snapshot["results_total"] == 3
    assert snapshot["has_results"] is True


def test_property_search_agent_selection_snapshot_is_typed_and_linked() -> None:
    snapshot = landing_property_saved_searches.select_property_search_agent(
        [
            {"agent_id": "agent-a", "location_query": "Vienna", "is_active": False},
            {"agent_id": "agent-b", "location_query": "Graz", "is_active": True},
        ],
        requested_agent_id="agent-b",
        previous_runs=[
            {"agent_id": "agent-b", "title": "Graz", "run_id": "run-1"},
            {"agent_id": "agent-a", "title": "Vienna", "run_id": "run-2"},
        ],
        run_id="run-live",
    )
    assert snapshot["selected_agent_id"] == "agent-b"
    assert snapshot["selected_agent"]["location_query"] == "Graz"
    assert snapshot["selected_agent_latest_run"]["run_id"] == "run-1"
    assert "agent_id=agent-b" in snapshot["selected_agent_open_href"]
    assert "run_id=run-live" in snapshot["selected_agent_edit_href"]


def test_property_workbench_candidate_snapshot_carries_detail_state() -> None:
    snapshot = property_surface_state.build_property_workbench_candidate_snapshot(
        candidate_ref="cand-1",
        rank=1,
        title="Lead candidate",
        source_label="Willhaben",
        location_label="Vienna",
        price_display="EUR 650,000",
        costs_display="Costs EUR 320/mo",
        price_per_sqm_display="EUR 8,200/m2",
        layout_display="3 rooms | 79 m2",
        layout_verification_label="verified",
        fit_score=86,
        fit_label="Strong fit",
        fit_summary="Good light and transit.",
        tour={"status": "ready"},
        orientation_preview={"caption": "Leopoldstadt"},
        ooda={"summary": "Walkable"},
        risk={"level": "low", "summary": "No major blocker"},
        investment={"enabled": True},
        match_reasons=["Transit"],
        mismatch_reasons=["Needs kitchen refresh"],
        review_page_neuronwriter={"status": "ready"},
        packet_url="/app/research/cand-1",
        review_url="",
        property_url="https://example.com/listing",
        map_url="https://maps.example.com",
        source_url="https://example.com/listing",
        property_facts={"postal_name": "Vienna"},
        assessment={"fit_score": 86},
        objection_rows=[{"title": "Risk", "detail": "Minor"}],
        timeline_rows=[{"title": "Ranked", "detail": "Now"}],
        household_rows=[{"title": "Parent", "detail": "Yes"}],
        risk_signal_rows=[{"title": "Signal", "detail": "Low"}],
        followup_rows=[{"title": "Ask", "detail": "Broker"}],
        recent_change_rows=[{"title": "Update", "detail": "Fresh"}],
        official_evidence_rows=[{"title": "Cadastre", "detail": "Linked"}],
        official_posture_rows=[{"title": "Risk", "detail": "Clear"}],
        object_rows=[{"title": "Rooms", "detail": "3"}],
        cost_rows=[{"title": "Costs", "detail": "320"}],
        feature_values=[{"title": "Balcony", "detail": "Yes"}],
        description_text="Clean description",
        location_text="Near Prater",
        energy_rows=[{"title": "EPC", "detail": "B"}],
        household_alignment_score=72,
        household_alignment_label="aligned",
        recovered_by_filter=True,
        relaxed_filter_label="Match bar",
        preview_image_url="https://img.example.com/1.jpg",
    )
    assert snapshot["candidate_ref"] == "cand-1"
    assert snapshot["rank"] == 1
    assert snapshot["tour"]["status"] == "ready"
    assert snapshot["official_evidence_rows"][0]["title"] == "Cadastre"
    assert snapshot["household_alignment_label"] == "aligned"


def test_property_console_context_skips_feedback_and_profile_hydration_on_properties(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-fast-properties")

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            return []

        def get_property_search_run_status(self, *, principal_id: str, run_id: str):
            return {
                "run_id": run_id,
                "status": "in_progress",
                "summary": {
                    "status": "in_progress",
                    "sources": [
                        {
                            "source_label": "Willhaben",
                            "top_candidates": [{"candidate_ref": "cand-1", "title": "Lead"}],
                        }
                    ],
                },
            }

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            raise AssertionError("properties surface should not hydrate preference profiles")

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            raise AssertionError("properties surface should not hydrate learning summaries")

        def list_handoffs(self, *, principal_id: str, limit: int = 12, status=None):
            raise AssertionError("properties surface should not hydrate recent match handoffs")

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())
    monkeypatch.setattr(
        landing_routes,
        "build_fliplink_packet_service",
        lambda container: (_ for _ in ()).throw(AssertionError("properties surface should not build packet feedback")),
    )

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-fast-properties",
        status={"property_search_preferences": {"country_code": "AT"}},
        run_id="run-1",
        surface_mode="properties",
    )

    candidate = context["run"]["summary"]["sources"][0]["top_candidates"][0]
    assert context["preference_bundle"] == {}
    assert "feedback_summary" not in candidate
    assert "feedback_rows" not in candidate


def test_property_console_context_skips_preference_profile_hydration_on_search(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-search-learning")
    seen = {"profile": 0}

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            return []

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            seen["profile"] += 1
            return {"preference_nodes": [{"node_id": "node-1", "key": "budget_max", "value_json": 900000}]}

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            return {"summary": "Learning ready"}

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-search-learning",
        status={"property_search_preferences": {"country_code": "AT"}},
        surface_mode="search",
    )

    assert seen["profile"] == 0
    assert context["preference_bundle"] == {}
    assert context["learning_summary"] == {}


def test_property_console_context_shortlist_skips_feedback_hydration_for_terminal_runs(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-shortlist-feedback-cap")
    seen: list[str] = []

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            return []

        def get_property_search_run_status(self, *, principal_id: str, run_id: str):
            return {
                "run_id": run_id,
                "status": "completed_partial",
                "summary": {
                    "status": "completed_partial",
                    "ranked_candidates": [
                        {"candidate_ref": "ranked-1", "title": "Ranked One"},
                        {"candidate_ref": "ranked-2", "title": "Ranked Two"},
                    ],
                    "sources": [
                        {
                            "source_label": f"Source {index}",
                            "top_candidates": [
                                {"candidate_ref": f"source-{index}-cand-{candidate_index}", "title": "Source Lead"}
                                for candidate_index in range(4)
                            ],
                        }
                        for index in range(12)
                    ],
                },
            }

        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            return {}

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            return {}

    class _PacketService:
        def feedback_summary(self, *, principal_id: str, property_ref: str):
            seen.append(property_ref)
            return {"clusters": []}

        def list_structured_feedback(self, *, principal_id: str, property_ref: str):
            return []

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())
    monkeypatch.setattr(landing_routes, "build_fliplink_packet_service", lambda container: _PacketService())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-shortlist-feedback-cap",
        status={"property_search_preferences": {"country_code": "AT"}},
        run_id="run-1",
        surface_mode="shortlist",
    )

    ranked = context["run"]["summary"]["ranked_candidates"]
    assert len(ranked) == 2
    assert all("feedback_summary" not in candidate for candidate in ranked)
    assert seen == []


def test_property_console_context_skips_recent_run_hydration_for_explicit_shortlist_run(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-shortlist-no-recent-runs")

    class _Product:
        def list_property_search_runs(self, *, principal_id: str, limit: int = 8):
            raise AssertionError("explicit shortlist run should not hydrate recent runs")

        def get_property_search_run_status(self, *, principal_id: str, run_id: str):
            return {
                "run_id": run_id,
                "status": "completed_partial",
                "summary": {
                    "status": "completed_partial",
                    "ranked_candidates": [{"candidate_ref": "cand-1", "title": "Ranked One"}],
                    "sources": [],
                },
            }

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-shortlist-no-recent-runs",
        status={"property_search_preferences": {"country_code": "AT"}},
        run_id="run-1",
        surface_mode="shortlist",
    )

    assert context["recent_search_runs"] == []
    assert context["run"]["run_id"] == "run-1"


def test_property_console_context_keeps_preference_profile_hydration_on_account(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-account-profile")
    seen = {"profile": 0, "learning": 0}

    class _Product:
        def get_preference_profile(self, *, principal_id: str, person_id: str = "self"):
            seen["profile"] += 1
            return {"preference_nodes": [{"node_id": "node-1", "key": "budget_max", "value_json": 900000}]}

        def property_feedback_learning_summary(self, *, principal_id: str, person_id: str = "self", domain: str = "willhaben"):
            seen["learning"] += 1
            return {"summary": "Learning ready"}

    monkeypatch.setattr(landing_routes, "build_product_service", lambda container: _Product())

    context = landing_routes._property_console_context(
        container=client.app.state.container,
        principal_id="pq-account-profile",
        status={"property_search_preferences": {"country_code": "AT"}},
        surface_mode="account",
    )

    assert seen["profile"] == 1
    assert seen["learning"] == 0
    assert context["preference_bundle"]["preference_nodes"][0]["node_id"] == "node-1"
    assert context["learning_summary"] == {}


def test_property_properties_surface_skips_search_agent_snapshot_build(monkeypatch) -> None:
    principal_id = "pq-properties-skip-search-agents"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    monkeypatch.setattr(
        landing_view_models,
        "build_property_search_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("properties surface should not build search agent snapshots")),
    )

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/search"


def test_property_research_packet_snapshot_normalizes_route_payload() -> None:
    snapshot = property_surface_state.build_property_research_packet_snapshot(
        title="Lead home",
        summary="EUR 650,000 · 79 m² · Vienna",
        source_label="Willhaben",
        price="EUR 650,000",
        area="79 m²",
        rooms="3 rooms",
        location="Vienna",
        media={"tour_url": "https://example.com/tour"},
        preview_image={"image_url": "https://img.example.com/1.jpg"},
        gallery_items=[{"kind": "image", "url": "https://img.example.com/1.jpg"}],
        location_preview={"title": "Leopoldstadt"},
        actions=[{"label": "Open listing", "href": "https://example.com/listing"}],
        visual_status_line="3D tour is ready.",
        source_ref="src-1",
        run_id="run-1",
        candidate_ref="cand-1",
        overview_rows=[{"label": "Price", "value": "EUR 650,000"}],
        sections=[{"eyebrow": "At a glance", "title": "Why this stayed"}],
        match_reasons=["Transit"],
        mismatch_reasons=["Kitchen refresh"],
        listing_rows=[{"label": "Rooms", "value": "3"}],
        cost_rows=[{"label": "Costs", "value": "320"}],
        feature_values=[{"label": "Balcony", "value": "Yes"}],
        description_text="Bright flat",
        location_text="Near Prater",
        energy_rows=[{"label": "EPC", "value": "B"}],
        missing_rows=[{"title": "Land register", "detail": "Still missing"}],
        decision_rows=[{"title": "Next step", "detail": "Call broker"}],
        compare_rows=[{"title": "Comp A", "detail": "Open next"}],
        compare_table_rows=[{"candidate": {"title": "Comp A"}}],
        compare_headers=["Candidate", "Fit"],
        official_evidence_rows=[{"title": "Cadastre", "detail": "Linked"}],
        official_posture_rows=[{"title": "Risk", "detail": "Clear"}],
        future_research_rows=[{"title": "School", "detail": "Atlas linked"}],
        provenance_rows=[{"title": "Source", "detail": "Listing"}],
        timeline_rows=[{"title": "Ranked", "detail": "Now"}],
        everyday_fit_rows=[{"title": "Transit", "detail": "Strong"}],
        risk_fit_rows=[{"title": "Flood", "detail": "Low"}],
        investment_rows=[{"title": "Yield", "detail": "4.1%"}],
        investment_risk_rows=[{"title": "Tax", "detail": "Verify"}],
        next_best_question="Ask about reserves",
        feedback={"save_endpoint": "/app/api/property-feedback"},
        neuronwriter={"status": "ready"},
        objection_rows=[{"title": "Risk", "detail": "Minor"}],
        household_rows=[{"title": "Parent", "detail": "Yes"}],
        risk_signal_rows=[{"title": "Signal", "detail": "Low"}],
    )
    assert snapshot["research_title"] == "Lead home"
    assert snapshot["research_candidate_ref"] == "cand-1"
    assert snapshot["research_gallery_items"][0]["kind"] == "image"
    assert snapshot["research_feedback"]["save_endpoint"] == "/app/api/property-feedback"
    assert snapshot["research_official_evidence_rows"][0]["title"] == "Cadastre"


def test_property_workbench_templates_render_provider_homepage_links_in_new_tabs() -> None:
    bundle = _read_workbench_bundle()
    assert 'data-provider-homepage-link' in bundle
    assert 'target="_blank"' in bundle
    assert 'rel="noopener noreferrer"' in bundle


def test_property_surface_scope_owns_loading_rules() -> None:
    properties_scope = PropertySurfaceScope.for_section("properties")
    search_scope = PropertySurfaceScope.for_section("search")
    agents_scope = PropertySurfaceScope.for_section("agents")
    billing_scope = PropertySurfaceScope.for_section("billing")
    shortlist_scope = PropertySurfaceScope.for_section("shortlist")

    assert properties_scope.wants_recent_runs is True
    assert properties_scope.wants_run_state is True
    assert properties_scope.wants_recent_matches is False
    assert properties_scope.wants_search_runs is False

    assert search_scope.wants_recent_runs is True
    assert search_scope.wants_run_state is True
    assert search_scope.wants_run_views is True
    assert search_scope.wants_credit_digest is False

    assert agents_scope.wants_agent_views is True
    assert agents_scope.wants_recent_runs is False
    assert agents_scope.wants_search_runs is False

    assert billing_scope.wants_credit_digest is True
    assert billing_scope.wants_recent_runs is False
    assert billing_scope.wants_run_views is False

    assert shortlist_scope.wants_run_state is True
    assert shortlist_scope.wants_run_views is True


def test_property_candidate_orientation_preview_uses_openstreetmap_backdrop_for_generic_locations(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_build_scope_boundary_preview", lambda **kwargs: {})
    monkeypatch.setattr(
        landing_view_models,
        "_openstreetmap_static_preview_data_url",
        lambda lat_key, lon_key, zoom=13: "data:image/png;base64,preview",
    )
    preview = landing_view_models._property_candidate_orientation_preview(
        {
            "property_facts": {
                "postal_name": "Graz",
                "map_lat": 47.0707,
                "map_lng": 15.4395,
            }
        }
    )
    assert preview["image_url"] == "data:image/png;base64,preview"
    assert preview["alt"] == "Wider area around Graz"


def test_property_candidate_orientation_preview_reuses_boundary_projection_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_build_scope_boundary_preview",
        lambda **kwargs: {
            "image_url": "data:image/png;base64,boundarypreview",
            "summary": "Leopoldstadt",
            "district_rows": [{"label": "Leopoldstadt", "selected": True, "path": "M1 1 L2 1 L2 2 Z"}],
        },
    )
    preview = landing_view_models._property_candidate_orientation_preview(
        {
            "property_facts": {
                "district": "Leopoldstadt",
                "postal_name": "Vienna",
                "country_code": "AT",
            }
        }
    )
    assert str(preview["image_url"]).startswith("data:image/")
    assert preview["caption"] == "Leopoldstadt"
    assert preview["district_rows"][0]["label"] == "Leopoldstadt"


def test_property_research_title_display_strips_provider_price_and_fact_noise() -> None:
    raw = "Super nette 2 Zimmer Wohnung (ideal für WG) in bester Lage für Unis, 60 m², € 1.150,-, (1090 Wien) - willhaben"
    assert landing_routes._property_research_title_display(raw) == "Super nette 2 Zimmer Wohnung (ideal für WG) in bester Lage für Unis"


def test_property_scope_preview_uses_generic_boundary_projection(monkeypatch) -> None:
    def fake_record(query: str) -> dict[str, object]:
        lowered = query.lower()
        if "vienna" in lowered:
            return {
                "display_name": "Vienna, Austria",
                "bounds": (16.18, 48.12, 16.55, 48.32),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.18, 48.12], [16.55, 48.12], [16.55, 48.32], [16.18, 48.32], [16.18, 48.12]]],
                },
            }
        if "1020" in lowered:
            return {
                "display_name": "Leopoldstadt, Vienna, Austria",
                "bounds": (16.39, 48.20, 16.46, 48.24),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.39, 48.20], [16.46, 48.20], [16.46, 48.24], [16.39, 48.24], [16.39, 48.20]]],
                },
            }
        if "1200" in lowered:
            return {
                "display_name": "Brigittenau, Vienna, Austria",
                "bounds": (16.35, 48.22, 16.41, 48.27),
                "geojson": {
                    "type": "Polygon",
                    "coordinates": [[[16.35, 48.22], [16.41, 48.22], [16.41, 48.27], [16.35, 48.27], [16.35, 48.22]]],
                },
            }
        return {}

    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", fake_record)
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/scopepreview.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)
    preview = landing_view_models._property_scope_preview("AT", "vienna", "1020 Vienna, 1200 Vienna")
    assert preview["image_url"] == "/app/api/property/map-previews/scopepreview.png"
    assert len(preview["district_rows"]) == 2
    assert all(str(row.get("path") or "").startswith("M") for row in preview["district_rows"])
    assert preview["preview_kind"] == "osm_district_overlay"
    assert preview["has_district_overlay"] is True
    assert len(preview_render_calls) == 1
    assert len(preview_render_calls[0]["overlay_rows"]) == 2
    assert preview_render_calls[0]["cache_key"]["overlay_mode"] == "svg_tile_crop_v5"
    assert preview_render_calls[0]["cache_key"]["render_bounds_source"] == "selected_areas"
    assert preview_render_calls[0]["zoom"] >= 10


def test_property_scope_preview_without_boundary_data_uses_local_vienna_overlay_fallback(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/localdistrict.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview("AT", "vienna", "1020 Vienna")

    assert preview["image_url"] == "/app/api/property/map-previews/localdistrict.png"
    assert preview["preview_kind"] == "osm_district_overlay"
    assert preview["has_district_overlay"] is True
    assert preview["district_rows"][0]["label"] == "Leopoldstadt"
    assert preview_render_calls[0]["cache_key"]["overlay_mode"] == "svg_tile_crop_v5"


def test_property_scope_preview_without_boundary_or_local_overlay_uses_local_layout_fallback(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    preview = landing_view_models._property_scope_preview("AT", "vienna", "Mödling")
    image_url = str(preview["image_url"])
    assert image_url.startswith("data:image/svg+xml")
    assert "#" not in image_url
    assert "%23" in image_url
    assert preview["district_rows"] == []


def test_property_scope_preview_without_known_layout_uses_osm_point_fallback(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    monkeypatch.setattr(landing_view_models, "_property_location_options", lambda country_code, region_code: [])
    monkeypatch.setattr(landing_view_models, "_scope_preview_layout", lambda country_code, region_code, options: [])
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: (47.8095, 13.0550))
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/salzburgpoint.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview("AT", "salzburg", "Non-catalog hillside")

    assert preview["image_url"] == "/app/api/property/map-previews/salzburgpoint.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview["has_district_overlay"] is False
    assert preview_render_calls[0]["pin"] == (320.0, 184.0)
    assert preview_render_calls[0]["zoom"] == 16


def test_property_scope_preview_fast_without_known_layout_uses_osm_point_fallback(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_property_location_options", lambda country_code, region_code: [])
    monkeypatch.setattr(landing_view_models, "_scope_preview_layout", lambda country_code, region_code, options: [])
    monkeypatch.setattr(landing_view_models, "_merge_option_catalog", lambda option_rows, selected_values: [])
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: (47.8095, 13.0550))
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/salzburgpoint-fast.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview_fast("AT", "salzburg", "Non-catalog hillside")

    assert preview["image_url"] == "/app/api/property/map-previews/salzburgpoint-fast.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview["has_district_overlay"] is False
    assert preview_render_calls[0]["pin"] == (320.0, 184.0)
    assert preview_render_calls[0]["zoom"] == 16


def test_property_scope_preview_empty_scope_uses_neutral_map_not_all_districts(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    monkeypatch.setattr(
        landing_view_models,
        "_property_location_options",
        lambda country_code, region_code: [
            {"value": "1010 Vienna", "label": "1010 Vienna"},
            {"value": "1020 Vienna", "label": "1020 Vienna"},
        ],
    )
    monkeypatch.setattr(
        landing_view_models,
        "_scope_preview_layout",
        lambda country_code, region_code, options: [
            {"value": str(row.get("value") or ""), "label": str(row.get("label") or "")}
            for row in options
        ],
    )
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: (47.5162, 14.5501))
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/austria-neutral.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview("AT", "", "")

    assert preview["image_url"] == "/app/api/property/map-previews/austria-neutral.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview["district_rows"] == []
    assert preview_render_calls[0]["pin"] == (320.0, 184.0)


def test_property_scope_preview_fast_empty_scope_uses_neutral_map_not_all_districts(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_property_location_options",
        lambda country_code, region_code: [
            {"value": "1010 Vienna", "label": "1010 Vienna"},
            {"value": "1020 Vienna", "label": "1020 Vienna"},
        ],
    )
    monkeypatch.setattr(
        landing_view_models,
        "_scope_preview_layout",
        lambda country_code, region_code, options: [
            {"value": str(row.get("value") or ""), "label": str(row.get("label") or "")}
            for row in options
        ],
    )
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: (47.5162, 14.5501))
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/austria-neutral-fast.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview_fast("AT", "", "")

    assert preview["image_url"] == "/app/api/property/map-previews/austria-neutral-fast.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview["district_rows"] == []
    assert preview_render_calls[0]["pin"] == (320.0, 184.0)


def test_property_scope_preview_fast_falls_back_to_layout_when_point_preview_fails(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_property_location_options", lambda country_code, region_code: [])
    def fake_scope_preview_layout(country_code: str, region_code: str, options: list[dict[str, str]]) -> list[dict[str, object]]:
        if any(str(row.get("value") == "scope") for row in options):
            return [
                {"value": "scope", "label": "Vienna", "detail": ""},
            ]
        return []
    monkeypatch.setattr(landing_view_models, "_scope_preview_layout", fake_scope_preview_layout)
    monkeypatch.setattr(landing_view_models, "_merge_option_catalog", lambda option_rows, selected_values: [])
    monkeypatch.setattr(landing_view_models, "_property_scope_point_preview", lambda **kwargs: {})
    preview_render_calls: list[dict[str, object]] = []

    def fake_scope_layout_preview_data_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/layout-fallback.png"

    monkeypatch.setattr(landing_view_models, "_scope_layout_preview_data_url", fake_scope_layout_preview_data_url)

    preview = landing_view_models._property_scope_preview_fast("AT", "vienna", "Non-catalog hillside")

    assert preview["image_url"] == "/app/api/property/map-previews/layout-fallback.png"
    assert preview["preview_kind"] == "fallback_layout"
    assert preview["has_district_overlay"] is False
    assert preview_render_calls[0]["normalized_query"] == "Non-catalog hillside"
    assert preview_render_calls[0]["layout_rows"][0]["value"] == "scope"


def test_property_scope_preview_map_only_rejects_local_layout_thumbnail_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_property_scope_preview",
        lambda country_code, region_code, location_query: (_ for _ in ()).throw(
            AssertionError("automation thumbnails must not call the generic local thumbnail pipeline")
        ),
    )
    monkeypatch.setattr(
        landing_view_models,
        "_build_scope_boundary_preview",
        lambda **kwargs: {
            "image_url": "data:image/svg+xml;charset=utf-8,local-layout",
            "summary": kwargs.get("normalized_query"),
            "preview_kind": "local_district_layout",
            "has_district_overlay": False,
        },
    )
    monkeypatch.setattr(landing_view_models, "_property_scope_point_preview", lambda **kwargs: {})

    preview = landing_view_models._property_scope_preview_map_only("AT", "vienna", "1020 Vienna")

    assert preview["preview_kind"] == "osm_map_pending"
    assert str(preview["image_url"]).startswith("/app/api/property/map-previews/")
    assert "data:image/svg+xml" not in str(preview["image_url"])
    assert preview["has_district_overlay"] is False


def test_property_scope_preview_map_only_rejects_point_thumbnail_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_build_scope_boundary_preview",
        lambda **kwargs: {
            "image_url": "/app/api/property/map-previews/point.png",
            "preview_kind": "osm_point_fallback",
            "has_district_overlay": False,
        },
    )

    preview = landing_view_models._property_scope_preview_map_only("AT", "vienna", "1020 Vienna")

    assert preview["preview_kind"] == "osm_map_pending"
    assert preview["image_url"] == "/app/api/property/map-previews/0000000000000000000000000000000000000000.png"
    assert preview["has_district_overlay"] is False


def test_property_scope_preview_map_only_uses_local_boundary_and_async_render(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_nominatim_boundary_record",
        lambda query: (_ for _ in ()).throw(AssertionError("agents first paint must not call Nominatim")),
    )
    scheduled: list[dict[str, object]] = []

    def fake_schedule_cached_preview_render(**kwargs) -> Path:
        scheduled.append(dict(kwargs))
        return tmp_path / "1234567890abcdef1234567890abcdef12345678.png"

    monkeypatch.setattr(landing_view_models, "_schedule_cached_preview_render", fake_schedule_cached_preview_render)

    preview = landing_view_models._property_scope_preview_map_only("AT", "vienna", "1020 Vienna, 1200 Vienna")

    assert preview["preview_kind"] == "osm_district_overlay"
    assert preview["has_district_overlay"] is True
    assert len(preview["district_rows"]) == 2
    assert preview["image_url"] == "/app/api/property/map-previews/1234567890abcdef1234567890abcdef12345678.png"
    assert scheduled
    assert scheduled[0]["draw_overlay"] is True
    assert len(scheduled[0]["overlay_rows"]) == 2


def test_property_scope_preview_map_only_materializes_first_paint_png_without_remote_tiles(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        landing_view_models.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("agents thumbnails must not wait for remote map tiles")),
    )
    monkeypatch.setattr(
        landing_view_models,
        "_nominatim_boundary_record",
        lambda query: (_ for _ in ()).throw(AssertionError("agents first paint must not call Nominatim")),
    )

    preview = landing_view_models._property_scope_preview_map_only("AT", "vienna", "1020 Vienna, 1200 Vienna")

    assert preview["preview_kind"] == "osm_district_overlay"
    assert preview["has_district_overlay"] is True
    image_url = str(preview["image_url"])
    assert image_url.startswith("/app/api/property/map-previews/")
    assert "0000000000000000000000000000000000000000" not in image_url
    preview_id = re.search(r"/([0-9a-f]{40})\.png$", image_url)
    assert preview_id
    preview_file = tmp_path / "map_previews" / f"{preview_id.group(1)}.png"
    assert preview_file.is_file()
    assert preview_file.stat().st_size > 1000


def test_property_scope_preview_boundary_framing_adds_small_map_breathing_room() -> None:
    bounds = (16.356, 48.202, 16.379, 48.216)

    west, south, east, north = landing_view_models._expand_geo_bounds(bounds)
    lon_span = bounds[2] - bounds[0]
    lat_span = bounds[3] - bounds[1]
    lon_pad = bounds[0] - west
    lat_pad = bounds[1] - south

    assert west < bounds[0]
    assert south < bounds[1]
    assert east > bounds[2]
    assert north > bounds[3]
    assert lon_pad >= lon_span * 0.10
    assert lat_pad >= lat_span * 0.10
    assert lon_pad <= lon_span * 0.23
    assert lat_pad <= lat_span * 0.23


def test_property_scope_preview_zoom_uses_tightest_unclipped_tile_crop() -> None:
    single_district_raw_bounds = (16.365, 48.197, 16.456, 48.235)
    single_district_bounds = landing_view_models._expand_geo_bounds(single_district_raw_bounds)
    assert landing_view_models._preview_zoom_for_bounds(
        single_district_bounds,
        fit_bounds=single_district_raw_bounds,
    ) == 13

    adjacent_district_raw_bounds = (16.35, 48.197, 16.456, 48.26)
    adjacent_district_bounds = landing_view_models._expand_geo_bounds(adjacent_district_raw_bounds)
    assert landing_view_models._preview_zoom_for_bounds(
        adjacent_district_bounds,
        fit_bounds=adjacent_district_raw_bounds,
    ) == 12


def test_property_scope_preview_map_only_never_uses_point_thumbnail(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_build_scope_boundary_preview", lambda **kwargs: {})
    monkeypatch.setattr(
        landing_view_models,
        "_property_scope_point_preview",
        lambda **kwargs: {
            "image_url": "/app/api/property/map-previews/point.png",
            "preview_kind": "osm_point_fallback",
            "has_district_overlay": False,
        },
    )

    preview = landing_view_models._property_scope_preview_map_only("AT", "vienna", "1020 Vienna")

    assert preview["preview_kind"] == "osm_map_pending"
    assert preview["image_url"] == "/app/api/property/map-previews/0000000000000000000000000000000000000000.png"
    assert preview["has_district_overlay"] is False


def test_property_scope_preview_uses_region_fallback_when_geocode_fails(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    monkeypatch.setattr(landing_view_models, "_property_location_options", lambda country_code, region_code: [])
    monkeypatch.setattr(landing_view_models, "_scope_preview_layout", lambda country_code, region_code, options: [])
    monkeypatch.setattr(landing_view_models, "_merge_option_catalog", lambda option_rows, selected_values: [])
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: None)
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/fallback.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview_fast("AT", "austria", "Nonspecific query outside catalog")

    assert preview["image_url"] == "/app/api/property/map-previews/fallback.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview_render_calls[0]["pin"] == (320.0, 184.0)
    assert preview_render_calls[0]["zoom"] == 16
    assert preview_render_calls[0]["cache_key"]["lat_key"] == int(47.5162 * 10000)
    assert preview_render_calls[0]["cache_key"]["lon_key"] == int(14.5501 * 10000)


def test_property_scope_preview_falls_back_to_country_center_with_unknown_region(monkeypatch) -> None:
    monkeypatch.setattr(landing_view_models, "_nominatim_boundary_record", lambda query: {})
    monkeypatch.setattr(landing_view_models, "_property_location_options", lambda country_code, region_code: [])
    monkeypatch.setattr(landing_view_models, "_scope_preview_layout", lambda country_code, region_code, options: [])
    monkeypatch.setattr(landing_view_models, "_merge_option_catalog", lambda option_rows, selected_values: [])
    monkeypatch.setattr(landing_view_models, "_forward_geocode_preview_point", lambda query: None)
    preview_render_calls: list[dict[str, object]] = []

    def fake_cached_preview_image_url(**kwargs) -> str:
        preview_render_calls.append(dict(kwargs))
        return "/app/api/property/map-previews/fallback-country.png"

    monkeypatch.setattr(landing_view_models, "_cached_preview_image_url", fake_cached_preview_image_url)

    preview = landing_view_models._property_scope_preview("DE", "nonnorm", "random unknown")

    assert preview["image_url"] == "/app/api/property/map-previews/fallback-country.png"
    assert preview["preview_kind"] == "osm_point_fallback"
    assert preview_render_calls[0]["cache_key"]["lat_key"] == int(51.1657 * 10000)
    assert preview_render_calls[0]["cache_key"]["lon_key"] == int(10.4515 * 10000)


def test_property_map_preview_route_serves_private_cached_png(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path))
    preview_id = "a" * 40
    preview_root = tmp_path / "map_previews"
    preview_root.mkdir(parents=True)
    preview_root.joinpath(f"{preview_id}.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    client = build_property_client(principal_id="pq-map-preview-route")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    response = client.get(f"/app/api/property/map-previews/{preview_id}.png", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert response.headers["x-property-map-preview-state"] == "ready"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"

    missing = client.get("/app/api/property/map-previews/not-a-preview.png", headers={"host": "propertyquarry.com"})
    assert missing.status_code == 404


def test_property_map_preview_route_fallback_to_placeholder_for_missing_cached_png(monkeypatch) -> None:
    preview_id = "b" * 40
    client = build_property_client(principal_id="pq-map-preview-route-placeholder")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    response = client.get(f"/app/api/property/map-previews/{preview_id}.png", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["x-property-map-preview-state"] == "pending"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.content.startswith(b"\x89PNG")


def test_property_lookup_candidate_falls_back_to_shortlist_candidates_from_context() -> None:
    property_context = {
        "run": {
            "run_id": "run-1",
            "summary": {
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Buy | Vienna",
                        "top_candidates": [
                            {
                                "title": "Vienna apartment",
                                "property_url": "https://example.com/listing/1",
                                "source_ref": "property-scout:1",
                                "review_url": "",
                                "property_facts": {},
                            }
                        ],
                    }
                ],
            },
        }
    }
    candidate = dict(property_context["run"]["summary"]["sources"][0]["top_candidates"][0])
    candidate["source_label"] = "Willhaben | Austria | Buy | Vienna"
    candidate_ref = landing_property_research._property_candidate_ref(candidate)
    found = landing_property_research._property_lookup_candidate(property_context=property_context, candidate_ref=candidate_ref)
    assert found is not None
    assert found["property_url"] == "https://example.com/listing/1"


def test_property_lookup_candidate_prefers_stable_candidate_ref_over_recomputed_hash() -> None:
    property_context = {
        "run": {
            "run_id": "run-stable-ref",
            "summary": {
                "ranked_candidates": [
                    {
                        "candidate_ref": "cand-stable-1",
                        "title": "Stable candidate",
                        "property_url": "https://example.com/listing/stable",
                        "source_label": "Old label",
                    }
                ],
            },
        }
    }

    found = landing_property_research._property_lookup_candidate(
        property_context=property_context,
        candidate_ref="cand-stable-1",
    )
    assert found is not None
    assert found["property_url"] == "https://example.com/listing/stable"


def test_property_shortlist_candidates_preserve_stable_candidate_ref_in_packet_url() -> None:
    property_context = {
        "run": {
            "run_id": "run-stable-packet",
            "summary": {
                "ranked_candidates": [
                    {
                        "candidate_ref": "cand-stable-22",
                        "title": "Stable packet candidate",
                        "property_url": "https://example.com/listing/stable-22",
                        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                    }
                ],
                "sources": [],
            },
        }
    }

    candidates = landing_property_research._property_shortlist_candidates_from_context(property_context)

    assert candidates[0]["packet_url"].endswith("/app/research/cand-stable-22?run_id=run-stable-packet")


def test_property_workspace_payload_excludes_ranked_candidates_without_concrete_location_or_price() -> None:
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "listing_mode": "buy",
                "search_goal": "home",
                "location_query": "1010 Vienna",
            },
            "run": {
                "run_id": "run-weak-candidate",
                "property_search_preferences": {
                    "listing_mode": "buy",
                    "search_goal": "home",
                    "location_query": "1010 Vienna",
                },
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "candidate-weak",
                            "title": "Project launch with no concrete facts",
                            "property_url": "https://example.com/project-launch",
                            "source_label": "Provider | Austria | Buy | 1010 Vienna",
                            "property_facts": {},
                        }
                    ],
                    "sources": [],
                },
            },
        },
    )

    assert payload["decision_workbench"]["results"] == []


def test_property_workspace_payload_drops_oversized_inline_candidate_previews() -> None:
    oversized_preview = "data:image/png;base64," + ("a" * 10000)
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "listing_mode": "rent",
                "search_goal": "home",
                "location_query": "1020 Vienna",
            },
            "run": {
                "run_id": "run-inline-preview",
                "property_search_preferences": {
                    "listing_mode": "rent",
                    "search_goal": "home",
                    "location_query": "1020 Vienna",
                },
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "cand-inline-preview",
                            "title": "Real 1020 apartment",
                            "property_url": "https://example.test/good",
                            "preview_image_url": oversized_preview,
                            "fit_score": 72,
                            "property_facts": {
                                "postal_name": "1020 Wien",
                                "rent_display": "EUR 1,200",
                                "total_rent_eur": 1200,
                                "area_sqm": 72,
                                "rooms": 3,
                            },
                        }
                    ],
                    "sources": [],
                },
            },
        },
    )

    result = payload["decision_workbench"]["results"][0]
    assert result["preview_image_url"] == ""
    assert json.dumps(payload).find(oversized_preview) == -1


def test_property_workspace_payload_source_fallback_excludes_false_positive_and_repair_rows() -> None:
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "listing_mode": "rent",
                "search_goal": "home",
                "location_query": "1020 Vienna",
            },
            "run": {
                "run_id": "run-source-only-fallback",
                "property_search_preferences": {
                    "listing_mode": "rent",
                    "search_goal": "home",
                    "location_query": "1020 Vienna",
                },
                "summary": {
                    "ranked_candidates": [],
                    "sources": [
                        {
                            "source_label": "Willhaben | Austria | Rent | 1020 Vienna",
                            "top_candidates": [
                                {
                                    "candidate_ref": "good",
                                    "title": "Real 1020 apartment",
                                    "property_url": "https://example.test/good",
                                    "fit_score": 72,
                                    "property_facts": {
                                        "postal_name": "1020 Wien",
                                        "rent_display": "EUR 1,200",
                                        "total_rent_eur": 1200,
                                        "area_sqm": 72,
                                        "rooms": 3,
                                    },
                                },
                                {
                                    "candidate_ref": "maybe-false",
                                    "title": "Maybe false",
                                    "property_url": "https://example.test/maybe",
                                    "fit_score": 99,
                                    "maybe_false": True,
                                    "property_facts": {"postal_name": "1020 Wien", "price_display": "EUR 1,100", "area_sqm": 70},
                                },
                                {
                                    "candidate_ref": "repair-only",
                                    "title": "Repair only",
                                    "property_url": "https://example.test/repair",
                                    "fit_score": 98,
                                    "flagged_for_repair": True,
                                    "property_facts": {"postal_name": "1020 Wien", "price_display": "EUR 1,100", "area_sqm": 70},
                                },
                                {
                                    "candidate_ref": "hard-filtered",
                                    "title": "Wrong area",
                                    "property_url": "https://example.test/filter",
                                    "fit_score": 97,
                                    "hard_filter_reason": "area_mismatch",
                                    "property_facts": {"postal_name": "1200 Wien", "price_display": "EUR 1,100", "area_sqm": 70},
                                },
                            ],
                        }
                    ],
                },
            },
        },
    )

    titles = [str(row.get("title") or "") for row in payload["decision_workbench"]["results"]]
    assert titles == ["Real 1020 apartment"]


def test_property_workspace_payload_excludes_dirty_source_scope_when_listing_text_has_other_postal() -> None:
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "listing_mode": "rent",
                "search_goal": "home",
                "location_query": "1010 Vienna",
            },
            "run": {
                "run_id": "run-dirty-source-scope",
                "property_search_preferences": {
                    "listing_mode": "rent",
                    "search_goal": "home",
                    "location_query": "1010 Vienna",
                },
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "candidate-1220",
                            "title": "Wohnung mieten in 1220 Wien | 60 m² | 2 Zimmer | € 1.090 | DER STANDARD",
                            "summary": "2-Zimmer Wohnung mit Traumblick / UNO und U-Bahn ums Eck in 1220 Wien.",
                            "property_url": "https://immobilien.derstandard.at/detail/wohnung-mieten-in-1220-wien",
                            "source_label": "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
                            "fit_score": 82,
                            "property_facts": {
                                "postal_name": "1010 Vienna",
                                "district": "1010 Vienna",
                                "source_scope_location": "1010 Vienna",
                                "source_postal_code": "1010",
                                "source_city": "Vienna",
                                "rent_display": "€ 1.090",
                                "area_m2": 60,
                                "rooms": 2,
                            },
                        }
                    ],
                    "sources": [],
                },
            },
        },
    )

    assert payload["decision_workbench"]["results"] == []


def test_property_workspace_payload_uses_market_timezone_when_account_has_no_timezone() -> None:
    payload = landing_property_workspace_payload.property_workspace_payload(
        "account",
        status={"workspace": {"name": "London buyer"}, "channels": {}},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {"country_code": "UK", "location_query": "London", "listing_mode": "buy"},
        },
    )

    account_rows = [
        item
        for card in payload["primary_cards"]
        for item in list(card.get("items") or [])
        if isinstance(item, dict)
    ]
    assert any(row.get("title") == "Timezone" and row.get("detail") == "Europe/London" for row in account_rows)


def test_property_workspace_payload_parses_non_eur_market_price_from_title() -> None:
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "country_code": "UK",
                "listing_mode": "buy",
                "search_goal": "home",
                "location_query": "London",
            },
            "run": {
                "run_id": "run-gbp-title-price",
                "property_search_preferences": {
                    "country_code": "UK",
                    "listing_mode": "buy",
                    "search_goal": "home",
                    "location_query": "London",
                },
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "candidate-gbp",
                            "title": "Two-bedroom flat in London | GBP 725,000 | 70 m2",
                            "property_url": "https://example.test/london-flat",
                            "fit_score": 80,
                            "property_facts": {"postal_name": "London", "area_sqm": 70, "rooms": 2},
                        }
                    ],
                    "sources": [],
                },
            },
        },
    )

    assert payload["decision_workbench"]["results"][0]["price_display"] == "GBP 725,000"


def test_property_workspace_payload_does_not_embed_external_branded_tour_host(monkeypatch) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")
    payload = landing_property_workspace_payload.property_workspace_payload(
        "shortlist",
        status={},
        property_state={
            "commercial": {},
            "billing_truth": {},
            "preferences": {
                "country_code": "AT",
                "listing_mode": "rent",
                "search_goal": "home",
                "location_query": "1020 Vienna",
            },
            "run": {
                "run_id": "run-legacy-tour-host",
                "property_search_preferences": {
                    "country_code": "AT",
                    "listing_mode": "rent",
                    "search_goal": "home",
                    "location_query": "1020 Vienna",
                },
                "summary": {
                    "ranked_candidates": [
                        {
                            "candidate_ref": "candidate-tour",
                            "title": "Apartment with live tour",
                            "property_url": "https://example.test/tour-flat",
                            "fit_score": 80,
                            "tour_url": "https://myexternalbrain.com/tours/live-flat",
                            "property_facts": {
                                "postal_name": "1020 Wien",
                                "rent_display": "EUR 1,200",
                                "area_sqm": 70,
                                "rooms": 2,
                            },
                        }
                    ],
                    "sources": [],
                },
            },
        },
    )

    tour = payload["decision_workbench"]["results"][0]["tour"]
    assert tour["url"] == "https://myexternalbrain.com/tours/live-flat"
    assert tour["embed_url"] == ""


def test_property_workbench_no_longer_embeds_vienna_district_mapping_js() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")
    assert "const districtMap = {" not in body
    assert "syncViennaScopeControls" not in body


def test_property_workbench_step_triggers_prevent_default_and_use_semantic_hidden_state() -> None:
    body = _read_workbench_bundle()
    assert "node.hidden = false;" in body
    assert "const collapsedBy = String(node.dataset.propertyCollapsedBy || '').trim();" in body
    assert "node.hidden = !stepVisible || semanticallyHidden || Boolean(collapsedBy);" in body
    assert "event.preventDefault();" in body
    assert "event.stopPropagation();" in body
    assert "let targetIndex = visibleSteps.findIndex" in body
    assert "targetIndex = steps.findIndex" not in body


def test_property_research_detail_uses_user_facing_visual_and_decision_copy() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_research_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "Current recommendation" not in body
    assert "Decision call" not in body
    assert "Open Magic Fit" not in body
    assert "Request missing documents" in body
    assert "Open question helper" in body
    assert "data-prd-map-overlay" in body
    assert "Questions worth asking next" in body
    assert "Requesting a 3D tour from the available source material" in body
    assert ".prd-actions .console-action.is-processing::before" in body
    assert "prd-media-image-failed" in body
    assert "img[data-prd-hero-image]" in body
    assert "data-prd-hero-fallback-src" in body


def test_property_research_detail_keeps_desktop_first_view_compact() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_research_detail.html"
    body = template_path.read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(0, 0.98fr) minmax(340px, 0.92fr);" in body
    assert "grid-template-columns: 1fr;" in body
    assert "min-height: clamp(210px, 30vh, 300px);" in body
    assert "max-height: min(calc(100vh - 370px), 320px);" in body
    assert "min-height: clamp(230px, 32vh, 320px);" in body
    assert "grid-template-columns: 76px minmax(0, 1fr);" in body
    assert 'data-pqx-screenfit-target="research-detail-hero"' in body
    assert "prd-hero-gallery" in body
    assert "-webkit-line-clamp: 2;" in body
    assert "min-height: min(56vh, 520px);" not in body
    assert body.index("data-object-media-stage") < body.index("At a glance")


def test_property_research_media_does_not_embed_stale_hosted_tour_record(monkeypatch) -> None:
    monkeypatch.setattr(landing_property_research, "_hosted_property_tour_manifest", lambda _url: {})
    monkeypatch.setattr(landing_property_research, "_hosted_property_tour_provider_export_keys", lambda _url: ())

    payload = landing_property_research._property_tour_media_payload(
        {
            "tour_url": "https://propertyquarry.com/tours/stale-tour",
            "property_url": "https://example.test/listing",
        }
    )

    assert payload["has_live_viewer"] is False
    assert payload["embed_href"] == ""
    assert payload["hosted_ready"] is False
    assert payload["status_label"] == "360 needs rebuild"
    assert payload["primary_href"] == ""

    monkeypatch.setattr(landing_property_research, "_hosted_property_tour_manifest", lambda _url: {"matterport_url": "https://my.matterport.com/show/?m=TEST123"})
    monkeypatch.setattr(landing_property_research, "_hosted_property_tour_provider_export_keys", lambda _url: ("matterport",))
    ready_payload = landing_property_research._property_tour_media_payload(
        {"tour_url": "https://propertyquarry.com/tours/ready-tour"}
    )
    assert ready_payload["has_live_viewer"] is True
    assert ready_payload["hosted_ready"] is True
    assert ready_payload["embed_href"] == "https://propertyquarry.com/tours/ready-tour/control"


def test_base_public_template_exposes_public_seo_contract() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/base_public.html"
    body = template_path.read_text(encoding="utf-8")
    assert '<meta name="description"' in body
    assert '<link rel="canonical"' in body
    assert '<meta property="og:title"' in body
    assert 'application/ld+json' in body


def test_public_pages_are_indexable_but_sign_in_is_not(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-public-seo")
    home = client.get("/")
    assert home.status_code == 200, home.text
    assert home.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"

    pricing = client.get("/pricing")
    assert pricing.status_code == 200, pricing.text
    assert pricing.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"

    sign_in = client.get("/sign-in")
    assert sign_in.status_code == 200, sign_in.text
    assert sign_in.headers.get("X-Robots-Tag") == "noindex, nofollow, noarchive, nosnippet"

    robots = client.get("/robots.txt")
    assert robots.status_code == 200, robots.text
    assert "Allow: /" in robots.text
    assert "Disallow: /app/" in robots.text
    assert "Sitemap: https://propertyquarry.com/sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200, sitemap.text
    assert "<loc>https://propertyquarry.com/</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/pricing</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/privacy</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/terms</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/support</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/imprint</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/guides/wohnung-kaufen-wien-checkliste</loc>" in sitemap.text
    assert "<loc>https://propertyquarry.com/markets/vienna</loc>" in sitemap.text


def test_public_channel_pages_use_propertyquarry_workflow_language() -> None:
    client = build_property_client(principal_id="pq-public-channel-copy")

    page = client.get("/channels/google")

    assert page.status_code == 200, page.text
    assert "Connect this when it improves search updates, shortlist decisions, or property follow-up." in page.text
    assert "Save the connection only if it makes the property workflow easier to act on." in page.text
    assert "channel-guidance-grid" in page.text
    forbidden = (
        "morning memo",
        "draft queue",
        "commitment lane",
        "channel-proof",
    )
    for phrase in forbidden:
        assert phrase not in page.text


def test_public_trust_pages_render_and_footer_links_are_customer_facing() -> None:
    client = build_property_client(principal_id="pq-public-trust")
    home = client.get("/")
    assert home.status_code == 200, home.text

    for href in ("/privacy", "/terms", "/support", "/imprint", "/cookies", "/subprocessors", "/refunds", "/disclaimers"):
        assert f'href="{href}"' in home.text
    assert 'href="/openapi.json">API</a>' not in home.text
    assert "Repository</a>" not in home.text

    expected = {
        "/privacy": ("Privacy", "Public tours should use a narrow public manifest"),
        "/terms": ("Terms", "Generated or embedded tours help screening"),
        "/support": ("Support", "wrong-area matches"),
        "/imprint": ("Imprint", "How to reach PropertyQuarry"),
        "/cookies": ("Cookies and Analytics", "essential cookies"),
        "/subprocessors": ("Subprocessors", "Vendor control plane"),
        "/refunds": ("Refunds and Cancellation", "failed payment recovery"),
        "/disclaimers": ("Disclaimers", "Generated visualization"),
    }
    for path, snippets in expected.items():
        page = client.get(path)
        assert page.status_code == 200, page.text
        assert page.headers.get("X-Robots-Tag") == "index, follow, max-image-preview:large"
        for snippet in snippets:
            assert snippet in page.text
        assert "receipts" not in page.text.lower()
        assert "Replace placeholder" not in page.text
        assert "Before public paid launch" not in page.text


def test_public_guide_and_market_pages_render_editorial_seo_surface() -> None:
    client = build_property_client(principal_id="pq-public-editorial")

    guide = client.get("/guides/wohnung-kaufen-wien-checkliste")
    assert guide.status_code == 200, guide.text
    assert "Wohnung kaufen in Wien" in guide.text
    assert 'data-rybbit-event="guide_open_propertyquarry"' in guide.text
    assert "FAQPage" in guide.text

    market = client.get("/markets/vienna")
    assert market.status_code == 200, market.text
    assert "Vienna apartment search" in market.text
    assert 'data-rybbit-event="market_start_search"' in market.text
    assert "FAQPage" in market.text


def test_public_ctas_and_selected_review_panel_expose_rybbit_events() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    home = (repo_root / "ea/app/templates/propertyquarry_home.html").read_text(encoding="utf-8")
    pricing = (repo_root / "ea/app/templates/pricing_page.html").read_text(encoding="utf-8")
    selected_review = (repo_root / "ea/app/templates/app/_property_selected_review_panel.html").read_text(encoding="utf-8")
    workbench_script = (repo_root / "ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")
    assert 'data-rybbit-event="home_create_account"' in home
    assert 'data-rybbit-event="pricing_checkout_start"' in pricing
    assert 'data-rybbit-event="property_open_page"' in selected_review
    assert 'data-rybbit-event="property_open_page"' in workbench_script
    assert 'data-rybbit-event="property_request_tour"' in workbench_script


def test_base_console_identifies_rybbit_with_opaque_principal_id() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/base_console.html"
    body = template_path.read_text(encoding="utf-8")
    assert "analytics_principal_id" in body
    assert "rybbit.identify({{ analytics_principal_id|tojson }}" in body
    assert "rybbit.identify({{ principal_id|tojson }}" not in body


def test_property_customer_run_summary_strips_operator_only_fields() -> None:
    summary = landing_view_models._property_customer_run_summary(
        {
            "sources_total": 2,
            "timing_receipts": {"first_shortlist_ready_at": "2026-06-15T10:00:00+00:00"},
            "research_tasks": [{"task_id": "t-1"}],
            "sources": [
                {
                    "source_label": "Provider A",
                    "provider_quality": {"floorplan_reliability": "high"},
                    "listing_total": 12,
                    "high_fit_total": 3,
                    "timing_ms": {"provider_preview": 10.5},
                }
            ],
        }
    )
    assert "research_tasks" not in summary
    assert summary["timing_receipts"]["first_shortlist_ready_at"] == "2026-06-15T10:00:00+00:00"
    assert "provider_quality" not in summary["sources"][0]
    assert summary["sources"][0]["listing_total"] == 12


def test_property_search_worker_slots_prioritize_distinct_providers() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 2},
            "sources": [
                {"source_label": "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna", "platform": "derstandard_at", "status": "in_progress"},
                {"source_label": "DER STANDARD Immobilien | Austria | Rent | 1020 Vienna", "platform": "derstandard_at", "status": "in_progress"},
                {"source_label": "immmo | Austria | Rent | 1010 Vienna", "platform": "immmo_at", "status": "in_progress"},
                {"source_label": "FindMyHome.at | Austria | Rent | 1010 Vienna", "platform": "findmyhome_at", "status": "queued"},
            ],
        },
        plan_key="plus",
    )

    providers = [row.get("provider") for row in worker_state.get("workers") or []]
    assert providers[:2] == [
        "DER STANDARD Immobilien | Austria | Rent | 1010 Vienna",
        "immmo | Austria | Rent | 1010 Vienna",
    ]
    labels = [row.get("label") for row in worker_state.get("workers") or []]
    assert labels[:2] == ["DER STANDARD", "immmo"]
    assert worker_state["workers"][0]["shard_count"] == 1
    assert worker_state["upgrade_copy"] == ""
    assert worker_state["tooltip"] == "Parallel search keeps selected portals moving at once. Saved searches are separate."


def test_property_search_worker_slots_only_show_real_lanes_instead_of_plan_fillers() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 4},
            "progress": 12,
            "status": "running",
            "sources": [
                {"source_label": "Willhaben | Austria | Buy | Vienna", "platform": "willhaben_at", "status": "in_progress"},
                {"source_label": "immmo | Austria | Buy | Vienna", "platform": "immmo_at", "status": "failed", "error": "HTTP 410"},
            ],
        },
        plan_key="agent",
    )

    assert worker_state["visible_workers"] == 2
    assert len(worker_state["workers"]) == 2
    assert [row.get("status_label") for row in worker_state["workers"]] == ["Running", "Fetch failed"]
    assert all(row.get("label") != "Preparing sources" for row in worker_state["workers"])


def test_property_search_worker_slots_hide_internal_check_wording() -> None:
    worker_state = landing_view_models._property_search_worker_slots(
        {
            "provider_workers": {"worker_concurrency": 1},
            "progress": 8,
            "status": "running",
            "sources": [],
        },
        plan_key="free",
    )

    combined = " ".join(
        [
            str(worker_state.get("upgrade_copy") or ""),
            str(worker_state.get("tooltip") or ""),
            " ".join(str(row.get("label") or "") for row in list(worker_state.get("workers") or [])),
            " ".join(str(row.get("provider") or "") for row in list(worker_state.get("workers") or [])),
        ]
    )
    assert "parallel checks" not in combined
    assert "source check" not in combined.lower()
    assert "worker" not in combined.lower()
    assert "provider scan" not in combined.lower()
    assert "Preparing search" in combined


def test_property_run_live_board_replaces_duplicate_review_message_with_latest_filter_reason() -> None:
    snapshot = property_surface_state.build_property_run_live_board_snapshot(
        {
            "status": "running",
            "progress": 45,
            "message": "Reviewing candidate 25 of 60 for Willhaben | Austria | Rent | 1010 Vienna.",
            "events": [
                {
                    "step": "source_family_filter",
                    "message": "Skipped shortlist candidate 23 of 60 outside the relaxed playground radius for Willhaben | Austria | Rent | 1010 Vienna.",
                    "status": "in_progress",
                }
            ],
            "summary": {
                "sources_total": 156,
                "source_variant_total": 156,
                "provider_total": 28,
                "reviewed_listing_total": 25,
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Rent | 1010 Vienna",
                        "platform": "willhaben",
                        "status": "running",
                    }
                ],
            },
        },
        plan_key="agent",
    )

    assert snapshot["fraction_label"] == "25 / 60"
    assert snapshot["summary_label"] == "28 providers · Willhaben · 25 / 60"
    assert "156 scans" not in snapshot["summary_label"]
    assert snapshot["phase_label"] == "Playground was too far away for candidate 23/60 (score impact only)"
    assert snapshot["source_count_label"] == "25 / 60"


def test_property_run_live_board_sanitizes_stale_source_counts_without_source_rows() -> None:
    snapshot = property_surface_state.build_property_run_live_board_snapshot(
        {
            "status": "failed",
            "progress": 40,
            "summary": {
                "provider_total": 3,
                "source_variant_total": 156,
                "sources_total": 156,
                "listing_total": 0,
                "sources": [],
            },
            "events": [{"step": "source_fetching", "message": "Fetching source page for Willhaben."}],
        },
        plan_key="plus",
    )

    assert "156" not in snapshot["source_count_label"]
    assert snapshot["source_count_label"] in {"0/3 sources", "waiting for selected sources"}


def test_property_run_live_board_marks_school_route_risk_as_score_only() -> None:
    snapshot = property_surface_state.build_property_run_live_board_snapshot(
        {
            "status": "running",
            "progress": 38,
            "message": "Reviewing candidate 18 of 60 for Willhaben | Austria | Rent | 1010 Vienna.",
            "events": [
                {
                    "step": "source_family_score",
                    "message": "School route looked dangerous for candidate 17 of 60 because traffic exposure is high.",
                    "status": "in_progress",
                }
            ],
            "summary": {"sources_total": 12, "reviewed_listing_total": 18, "sources": []},
        },
        plan_key="plus",
    )

    assert snapshot["phase_label"] == "Way to school looked risky for candidate 17/60 (score impact only)"


def test_property_run_live_board_marks_safe_kindergarten_route_as_score_upgrade() -> None:
    snapshot = property_surface_state.build_property_run_live_board_snapshot(
        {
            "status": "running",
            "progress": 38,
            "message": "Reviewing candidate 19 of 60 for Willhaben | Austria | Rent | 1010 Vienna.",
            "events": [
                {
                    "step": "source_family_score",
                    "message": "Kindergarten route looked safe for candidate 18 of 60 because the walk uses calm streets.",
                    "status": "in_progress",
                }
            ],
            "summary": {"sources_total": 12, "reviewed_listing_total": 19, "sources": []},
        },
        plan_key="plus",
    )

    assert snapshot["phase_label"] == "Way to kindergarten looked safe for candidate 18/60 (score upgraded)"


def test_property_run_live_board_surfaces_engine_insight_categories() -> None:
    cases = [
        (
            "Balcony evidence confirmed for candidate 11 of 60.",
            "Outdoor space evidence found for candidate 11/60 (score upgraded)",
        ),
        (
            "Operating costs are missing for candidate 12 of 60 and need verification.",
            "Cost evidence still needs verification for candidate 12/60 (score impact only)",
        ),
        (
            "Postal code mismatch outside selected scope for candidate 13 of 60.",
            "Location evidence conflicted for candidate 13/60 (hard area rule)",
        ),
        (
            "Kept shortlist candidate 14 of 60 in discovery despite a Noise miss for Willhaben. Noise is higher than preferred.",
            "Noise missed the preference for candidate 14/60 (score impact only)",
        ),
        (
            "Matterport tour available for candidate 15 of 60.",
            "Remote-view evidence improved the score for candidate 15/60 (score upgraded)",
        ),
        (
            "High-speed internet evidence confirmed for candidate 16 of 60.",
            "Internet evidence improved the score for candidate 16/60 (score upgraded)",
        ),
        (
            "Energy certificate is missing for candidate 17 of 60.",
            "Energy evidence still needs verification for candidate 17/60 (score impact only)",
        ),
        (
            "School distance is within the selected preference for candidate 18 of 60.",
            "School distance fit the preference for candidate 18/60 (score upgraded)",
        ),
        (
            "Kindergarten is too far beyond the preference for candidate 19 of 60.",
            "Kindergarten distance was wider than preferred for candidate 19/60 (score impact only)",
        ),
        (
            "Commute is longer than preferred for candidate 20 of 60.",
            "Commute was longer than preferred for candidate 20/60 (score impact only)",
        ),
        (
            "Supermarket and pharmacy are farther than preferred for candidate 21 of 60.",
            "Daily errands were farther than preferred for candidate 21/60 (score impact only)",
        ),
        (
            "No balcony or terrace found for candidate 22 of 60.",
            "Outdoor space was missing for candidate 22/60 (score impact only)",
        ),
        (
            "South-facing orientation evidence confirmed for candidate 23 of 60.",
            "Light and orientation evidence improved the score for candidate 23/60 (score upgraded)",
        ),
        (
            "Duplicate candidate 24 of 60 already seen on another provider.",
            "Candidate 24/60 matched existing property memory",
        ),
        (
            "Listing freshness check found candidate 25 of 60 is stale and no longer available.",
            "Listing freshness changed for candidate 25/60; repair opened",
        ),
        (
            "Provider repair opened for candidate 26 of 60 after fetch failed in extractor.",
            "Repair picked up candidate 26/60",
        ),
        (
            "Price per sqm is below benchmark for candidate 27 of 60.",
            "Price-per-m2 benchmark improved the score for candidate 27/60",
        ),
        (
            "Price per sqm is above benchmark for candidate 28 of 60.",
            "Price-per-m2 benchmark reduced the score for candidate 28/60 (score impact only)",
        ),
        (
            "Total monthly cost fits inside budget for candidate 29 of 60.",
            "Total monthly cost fit the budget for candidate 29/60 (score upgraded)",
        ),
        (
            "Total monthly cost exceeds budget for candidate 30 of 60.",
            "Total monthly cost exceeded the budget for candidate 30/60 (hard budget rule)",
        ),
        (
            "Room count and layout shape matched for candidate 31 of 60.",
            "Room layout matched the home shape for candidate 31/60 (score upgraded)",
        ),
        (
            "Bike route looked protected and direct for candidate 32 of 60.",
            "Bike route looked practical for candidate 32/60 (score upgraded)",
        ),
        (
            "Noise context is low and quiet for candidate 33 of 60.",
            "Noise context improved the score for candidate 33/60",
        ),
        (
            "Flood and groundwater evidence is clear for candidate 34 of 60.",
            "Water-risk evidence looked clear for candidate 34/60 (score upgraded)",
        ),
        (
            "Operating-cost statement is missing for candidate 35 of 60.",
            "Document evidence is still missing for candidate 35/60 (score impact only)",
        ),
    ]
    for message, expected in cases:
        snapshot = property_surface_state.build_property_run_live_board_snapshot(
            {
                "status": "running",
                "progress": 50,
                "message": "Reviewing candidate 20 of 60 for Willhaben | Austria | Rent | 1010 Vienna.",
                "events": [{"step": "source_candidate_signal", "message": message, "status": "in_progress"}],
                "summary": {"sources_total": 12, "reviewed_listing_total": 20, "sources": []},
            },
            plan_key="plus",
        )
        assert snapshot["phase_label"] == expected


def test_property_run_reliability_summary_surfaces_repair_and_eta_state() -> None:
    reliability = landing_property_workspace_helpers._property_run_reliability_summary(
        {
            "status": "running",
            "progress": 42,
            "message": "Retrying one provider while the shortlist stays visible.",
            "eta_label": "about 6m",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                ],
                "held_back_total": 7,
            },
        },
        results_total=3,
    )
    assert reliability["health_label"] == "Repairing"
    assert reliability["repair_step_label"] == "Retrying 1 selected source"
    assert reliability["coverage_label"] == "2/4 sources checked · 2 still running"
    assert reliability["result_label"] == "3 ranked results ready"
    assert reliability["filtered_label"] == "7 filtered by active rules"
    assert reliability["repair"]["repair_status"] == "repairing"
    assert reliability["repair"]["can_auto_repair"] is True


def test_property_run_reliability_summary_surfaces_completed_partial_state() -> None:
    reliability = landing_property_workspace_helpers._property_run_reliability_summary(
        {
            "status": "completed_partial",
            "message": "One provider stayed degraded.",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                    {"source_label": "C", "status": "completed"},
                    {"source_label": "D", "status": "completed"},
                ],
            },
        },
        results_total=4,
    )

    assert reliability["health_label"] == "Partial coverage"
    assert reliability["health_tone"] == "warn"
    assert reliability["customer_status_message"] == "One provider stayed degraded."
    assert reliability["repair"]["repair_status"] == "degraded"
    assert reliability["repair"]["repair_status_label"] == "Partial coverage"


def test_property_surface_state_builds_run_repair_snapshot() -> None:
    repair = property_surface_state.build_property_run_repair_snapshot(
        {
            "status": "running",
            "progress": 44,
            "eta_label": "about 6m",
            "summary": {
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                ],
            },
        },
        results_total=2,
    )

    assert repair["repair_status"] == "repairing"
    assert repair["repair_status_label"] == "Repairing"
    assert repair["repair_step_label"] == "Retrying 1 selected source"
    assert repair["repair_outcome_summary"] == "Some selected sources are retrying, but the current shortlist is already usable."
    assert repair["eta_confidence_label"] == "Medium"
    assert repair["can_auto_repair"] is True


def test_property_surface_state_builds_run_reliability_snapshot() -> None:
    reliability = property_surface_state.build_property_run_reliability_snapshot(
        {
            "status": "completed_partial",
            "message": "One provider stayed degraded.",
            "summary": {
                "sources_total": 4,
                "sources": [
                    {"source_label": "A", "status": "completed"},
                    {"source_label": "B", "status": "failed", "error": "HTTP 410"},
                    {"source_label": "C", "status": "completed"},
                    {"source_label": "D", "status": "completed"},
                ],
            },
        },
        results_total=4,
    )

    assert reliability["health_label"] == "Partial coverage"
    assert reliability["repair_step_label"] == "Retrying 1 selected source"
    assert reliability["repair"]["repair_status"] == "degraded"
    assert reliability["customer_status_message"] == "One provider stayed degraded."


def test_property_surface_state_builds_search_form_state_snapshot() -> None:
    snapshot = property_surface_state.build_property_search_form_state_snapshot(
        {
            "country_code": "at",
            "search_goal": "investment",
            "listing_mode": "rent",
            "investment_research_mode": "off",
            "investment_strategy": "cash_flow",
            "include_public_housing_signals": True,
            "include_distressed_sale_signals": True,
            "max_distance_to_playground_m": 500,
            "use_stored_feedback_preferences": False,
            "loan_term_years": "41",
            "min_dscr": "4.0",
            "vacancy_reserve_pct": "-3",
        },
        selected_listing_mode="rent",
    )

    assert snapshot["selected_country_code"] == "AT"
    assert snapshot["selected_search_goal"] == "investment"
    assert snapshot["selected_listing_mode"] == "buy"
    assert snapshot["property_is_investment_search"] is True
    assert snapshot["show_investment_underwriting_controls"] is False
    assert snapshot["show_public_housing_policy_controls"] is False
    assert snapshot["show_distressed_review_controls"] is True
    assert snapshot["show_playground_importance_controls"] is False
    assert snapshot["show_preference_profile_controls"] is False
    assert snapshot["loan_term_years"] == 40
    assert snapshot["min_dscr"] == 3.0
    assert snapshot["vacancy_reserve_pct"] == 0


def test_propertyquarry_results_template_marks_top_rank_and_watch_out_copy() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/_property_results_list.html").read_text(encoding="utf-8")
    assert "is-top-ranked" in body
    assert "mismatch_reasons" in body
    assert "pqx-progress-button" in body
    assert "walkthrough_tooltip" in body
    assert "Score:" in body
    assert "pqx-thumb-link" in body
    assert "pqx-results-filter-link" in body


def test_propertyquarry_workspace_routes_render_greenfield_surfaces(monkeypatch) -> None:
    principal_id = "pq-redesign-browser"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PAYPAL_CHECKOUT", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
            "enable_commute_research": True,
            "commute_destination": "Berlin Hauptbahnhof",
            "max_commute_minutes_transit": 25,
        },
    )
    assert stored.status_code == 200, stored.text
    profile_node = client.post(
        "/app/api/people/elisabeth/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "prefer_balcony",
            "value_json": True,
            "strength": "medium",
            "confidence": 0.9,
        },
    )
    assert profile_node.status_code == 200, profile_node.text

    top_candidate = {
        "title": "Altbau near U6",
        "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
        "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
        "compare_reason": "Chosen ahead of the next option because it scored 5 points higher on the current brief; it includes a floorplan while the next option does not.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-1",
        "tour_url": "https://propertyquarry.com/tours/altbau-u6",
        "match_reasons": [
            "Includes a live 360 source, which supports remote review after the core fit is already acceptable.",
            "Lift and transit fit.",
        ],
        "mismatch_reasons": [],
        "property_facts": {
            "price_display": "EUR 420,000",
            "price_eur": 420000.0,
            "rooms": 3,
            "area_m2": 78,
            "postal_name": "Berlin Mitte",
            "street_address": "Invalidenstrasse 14",
            "map_lat": 52.531,
            "map_lng": 13.384,
            "nearest_supermarket_m": 280,
            "nearest_supermarket_name": "Demo Supermarket",
            "nearest_supermarket_lat": 52.532,
            "nearest_supermarket_lng": 13.385,
            "nearest_pharmacy_m": 410,
            "nearest_library_m": 360,
            "nearest_running_m": 640,
            "nearest_tram_bus_m": 190,
            "nearest_playground_m": 520,
            "nearest_starbucks_m": 340,
            "nearest_fitness_center_m": 460,
            "nearest_cinema_m": 690,
            "nearest_bouldering_m": 880,
            "nearest_subway_m": 1200,
            "listing_research_snapshot": {
                "street_address": "Invalidenstrasse 14",
                "nearest_supermarket_m": 280,
                "map_lat": 52.531,
            },
            "listing_research_meta": {
                "strategy": "provider_html_plus_geo",
            },
            "official_risk_evidence": {
                "country_code": "AT",
                "updated_at": "2026-06-08T18:30:00+00:00",
                "sources": [
                    {
                        "label": "Air quality",
                        "authority_label": "Stadt Wien",
                        "provider": "data.gv.at / Stadt Wien",
                        "source_label": "Luftmessnetz: aktuelle Messdaten Wien",
                        "source_url": "https://www.data.gv.at/datasets/d9ae1245-158e-4d79-86a4-2d9b3defbedc?locale=de",
                        "availability": "official_dataset",
                        "verification_state": "flagged",
                        "confidence": "medium",
                        "summary": "Official city air-quality measurements should anchor the pollution read for this micro-location.",
                        "required_next_step": "Cross-check the nearest station before treating air burden as resolved.",
                    },
                    {
                        "label": "Flood exposure",
                        "authority_label": "Hochwasserrichtlinie",
                        "provider": "data.gv.at / Hochwasserrichtlinie",
                        "source_label": "Überflutungsflächen HQ30, HWRL",
                        "source_url": "https://www.data.gv.at/datasets/84372374-996a-4d7c-a7ee-9b063d9a7282?locale=de",
                        "availability": "official_dataset",
                        "verification_state": "needs_review",
                        "confidence": "high",
                        "summary": "Official HQ30 and flood-zone evidence should anchor the flood-risk read.",
                    },
                    {
                        "label": "Parking pressure",
                        "authority_label": "Municipal parking authority",
                        "provider": "municipal parking data",
                        "source_label": "Municipal parking-regulation evidence required",
                        "availability": "municipal_gap",
                        "verification_state": "source_gap",
                        "confidence": "low",
                        "summary": "A municipality-specific parking source is still missing for this micro-location.",
                        "required_next_step": "Attach a municipality-specific parking-zone source before clearing parking pressure.",
                    },
                ],
            },
            "future_change_research": {
                "school_atlas_quality_summary": "Nearby SchoolAtlas schools: Volksschule Beispiel (VS, 280 m, 240 students)",
                "school_atlas_progression_summary": "Nearest transition-capable school Volksschule Beispiel shows 64 disclosed outgoing transitions; about 62.5% lead to Gymnasium/AHS.",
                "school_atlas_evidence_type": "hard_public_data",
                "school_atlas_source_url": "https://www.statistik.at/atlas/schulen/",
            },
        },
    }
    second_candidate = {
        "title": "Family flat near Tiergarten",
        "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
        "fit_summary": "Personal fit 87/100 · shortlist · Larger layout and quieter block.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-2",
        "tour_url": "",
        "tour_status": "skipped",
        "match_reasons": ["Larger layout and quieter block."],
        "mismatch_reasons": ["No 360 tour yet."],
        "property_facts": {
            "price_display": "EUR 465,000",
            "price_eur": 465000.0,
            "rooms": 4,
            "area_m2": 92,
            "postal_name": "Berlin Tiergarten",
            "has_floorplan": False,
            "floorplan_count": 0,
        },
    }
    queued_candidate = {
        "title": "Courtyard loft with pending tour",
        "property_url": "https://www.immobilienscout24.de/expose/courtyard-loft",
        "fit_summary": "Personal fit 83/100 · shortlist · Quiet courtyard and strong transit.",
        "recommendation": "shortlist",
        "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-3",
        "tour_url": "",
        "tour_status": "queued",
        "tour_eta_minutes": 12,
        "match_reasons": ["Quiet courtyard and strong transit."],
        "mismatch_reasons": ["Hosted 360 is not ready yet."],
        "property_facts": {
            "price_display": "EUR 438,000",
            "price_eur": 438000.0,
            "rooms": 3,
            "area_m2": 81,
            "postal_name": "Berlin Moabit",
            "has_floorplan": True,
            "has_360": True,
        },
    }
    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-redesign-browser"
        assert run_id == "run-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "research_task_total": 1,
            "open_research_task_total": 1,
            "filled_research_task_total": 0,
            "dismissed_research_task_total": 0,
            "research_tasks": [
                {
                    "task_id": "mf_rooms_run_42",
                    "field": "rooms",
                    "label": "Rooms",
                    "status": "queued",
                    "priority": "high",
                    "title": "Family flat near Tiergarten",
                    "source_label": "ImmoScout24 Germany",
                    "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-2",
                    "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
                    "fit_score": 87,
                    "display_value": "Room count not verified yet",
                    "evidence": "Floorplan exists, but no structured room count was extracted yet.",
                    "next_actions": ["Parse the floorplan and source PDF bundle."],
                }
            ],
            "summary": {
                "sources_total": 2,
                "listing_total": 7,
                "tour_created_total": 1,
                "tour_existing_total": 1,
                "review_created_total": 1,
                "packet_created_total": 1,
                "telegram_sent_total": 1,
                "research_task_total": 1,
                "open_research_task_total": 1,
                "dossier_writer_neuronwriter_status": "pending",
                "notification_budget": {
                    "limit": 1,
                    "period": "day",
                    "sent_in_window": 0,
                    "remaining_after_run": 0,
                },
                "notification_budget_suppressed_total": 2,
                "sources": [
                        {
                            "source_label": "ImmoScout24 Germany",
                            "listing_total": 4,
                            "high_fit_total": 2,
                            "tour_created_total": 1,
                            "notified_total": 1,
                            "filtered_low_fit_total": 3,
                            "filtered_floorplan_total": 1,
                            "location_mismatch_candidate_total": 2,
                            "location_mismatch_reason": "provider_returned_candidates_outside_selected_location",
                            "review_created_total": 1,
                            "provider_repair_task_opened_total": 1,
                            "provider_repair_task_existing_total": 0,
                            "provider_repair_tasks": [{"repair_owner": "ea_one_manager"}],
                            "provider_filter_pushdown": {
                                "filter_strength": "weak_search_then_post_filter",
                                "post_filter_only": ["min_area_m2"],
                            },
                            "provider_quality": {
                                "floorplan_reliability": "medium",
                                "filter_pushdown_strength": "partial",
                                "last_verified": "2026-06-13",
                            },
                            "dossier_writer_neuronwriter_status": "pending",
                            "notification_budget_suppressed_total": 2,
                            "top_candidates": [top_candidate, second_candidate, queued_candidate],
                        }
                    ],
                },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 provider(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-browser"
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for Auhofstrasse shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="https://propertyquarry.com/tours/auhofstrasse-14997053",
            ),
        )

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)
    monkeypatch.setattr(landing_property_research, "_property_investment_research_access_level", lambda *args, **kwargs: "full")
    monkeypatch.setattr(
        landing_property_research,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 420000.0,
            "current_area_sqm": 78.0,
            "current_price_per_sqm_eur": 5384.62,
            "market_buy_per_sqm_eur": 5600.0,
            "market_buy_delta_pct": -3.8,
            "market_rent_per_sqm_eur": 19.5,
            "expected_monthly_rent_eur": 1521.0,
            "gross_yield_pct": 4.35,
            "payback_years": 23.0,
            "buy_sample_count": 3,
            "rent_sample_count": 2,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 5600.0, "source_label": "ImmoScout24 Germany"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 19.5, "source_label": "ImmoScout24 Germany"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    setup = client.get("/app/properties", headers=headers)
    assert setup.status_code == 200
    assert 'data-range-control="max_price_eur"' in setup.text
    assert 'data-range-control="min_rooms"' in setup.text
    assert 'data-range-control="min_area_m2"' in setup.text
    assert 'data-range-control="available_within_years"' in setup.text
    assert 'data-range-control="max_results_per_source"' in setup.text
    assert 'data-range-control="min_match_score"' in setup.text
    assert 'data-range-format="currency_eur"' in setup.text
    assert 'data-range-currency-code="EUR"' in setup.text
    assert 'data-range-format="area_m2"' in setup.text
    assert 'data-range-empty-label="Any budget"' in setup.text
    assert 'data-range-preset="listing_mode_price"' in setup.text
    assert "Max budget" in setup.text
    assert 'value="office"' in setup.text
    assert "Office" in setup.text
    assert 'data-tooltip-trigger' in setup.text
    assert 'aria-expanded="false"' in setup.text
    assert "Set a hard budget ceiling. Leave it at Any budget when you want PropertyQuarry to rank first and filter price later." in setup.text
    assert 'data-school-stage-variant' in setup.text
    assert 'data-school-stage-parent' in setup.text
    assert 'data-kindergarten-parent' in setup.text
    assert 'data-kindergarten-variant' in setup.text
    assert "Checked school types are treated as OR matches." in setup.text
    assert "Select Volksschule to reveal Ganztags- and Halbtagsvolksschule variants." in setup.text
    assert "Select Kindergarten to reveal public and private kindergarten options." in setup.text
    assert 'data-checkbox-group-select-all="selected_platforms"' in setup.text
    assert 'class="pqx-step-head-actions"' in setup.text
    assert 'data-property-start-top' in setup.text
    assert 'data-property-launch-status' in setup.text
    assert 'aria-live="polite"' in setup.text
    assert setup.text.index('data-property-start-top') < setup.text.index('data-property-step-nav')
    assert 'data-property-step-nav' in setup.text
    template = _read_workbench_bundle()
    assert "padding: 4px 4px 10px;" in template
    assert "padding: 3px 3px 9px;" in template
    assert "padding: 2px 2px 10px;" in template
    assert "scroll-snap-type: x proximity;" in template
    assert "Add family" in setup.text
    assert "Clear family" in setup.text
    assert "Select providers" in setup.text
    assert "Court and auction listings" in setup.text
    assert "Justiz Edikte" in setup.text
    assert 'data-property-advanced-panel="commute"' in setup.text
    assert 'class="pqx-disclosure-summary"' in setup.text
    assert 'class="pqx-disclosure-icon" aria-hidden="true">+</span>' in setup.text
    assert ">What matters<" in setup.text
    assert ">Sources<" in setup.text
    assert 'data-pqx-save-what-matters' in setup.text
    assert 'data-pqx-load-what-matters' in setup.text
    assert ">Strategy<" not in setup.text
    assert 'data-property-field-step="areas"' not in setup.text
    assert 'data-property-field-step="what" data-property-field-name="investment_require_floorplan"' in setup.text
    assert 'name="max_distance_to_library_m"' in setup.text
    assert 'name="max_distance_to_library_importance"' in setup.text

    assert 'name="max_distance_to_playground_importance"' in setup.text
    assert 'name="max_distance_to_supermarket_m"' in setup.text
    assert 'name="max_distance_to_supermarket_importance"' in setup.text
    assert "Supermarket nearby means" not in setup.text
    assert "Playground nearby means" not in setup.text
    assert "Library nearby means" not in setup.text
    assert "Supermarket radius" in setup.text
    assert "providers: { label: 'Providers'" not in template
    assert "providers: { label: 'Sources', detail: 'Choose trusted sources, then save or launch.' }" in template
    assert "If good matches are scarce" in setup.text
    assert 'name="max_distance_to_zoo_m"' in setup.text
    assert 'name="max_distance_to_market_m"' in setup.text
    assert 'name="max_distance_to_hardware_store_m"' in setup.text
    assert 'name="max_distance_to_shopping_center_m"' in setup.text
    assert 'name="max_distance_to_shopping_street_m"' in setup.text
    assert 'name="max_distance_to_theatre_m"' in setup.text
    assert 'name="max_distance_to_public_pool_m"' in setup.text
    assert 'name="max_distance_to_medical_care_m"' in setup.text
    assert 'name="prefer_good_air_quality"' in setup.text
    assert 'name="prefer_low_crime_area"' in setup.text
    assert 'name="require_drinking_water_quality_research"' in setup.text
    assert 'name="require_parking_pressure_check"' in setup.text
    assert 'name="avoid_cesspit_or_septic_risk"' in setup.text
    assert 'name="require_winter_access_research"' in setup.text
    assert 'name="avoid_flood_risk_area"' in setup.text
    assert 'name="school_stage_preferences"' in setup.text
    assert 'value="volksschule"' in setup.text
    assert 'value="kindergarten"' in setup.text
    assert 'value="public_kindergarten"' in setup.text
    assert 'value="private_kindergarten"' in setup.text
    assert 'value="ganztags_volksschule"' in setup.text
    assert 'value="halbtags_volksschule"' in setup.text
    assert 'data-property-show-unavailable' in setup.text
    assert 'No practical zoo or Tiergarten signal is configured for this market yet.' in setup.text
    assert 'data-property-pulse-strip' not in setup.text
    assert "Min area" in setup.text
    assert 'data-property-search-utility-strip' not in setup.text
    assert 'data-property-search-utility="automation"' not in setup.text
    assert 'data-property-search-utility="preferences"' not in setup.text
    assert "Saved preferences" not in setup.text
    assert "Recurring searches, delivery, reports, and repair policy live in the dedicated automation view." not in setup.text
    assert "Manage durable rules in Account." not in setup.text
    assert "Open automation" not in setup.text
    assert 'data-keyword-preference-select' in setup.text
    assert "Neutral" in setup.text
    assert "Avoid" in setup.text
    assert "Strong wish" in setup.text
    assert "Barrier-free" in setup.text
    assert "Playground importance" not in setup.text
    assert "Save limits" not in setup.text
    assert 'data-search-agent-action="resume"' not in setup.text
    assert 'data-search-agent-action="duplicate"' not in setup.text
    assert 'data-search-agent-action="delete"' not in setup.text
    assert 'data-search-agent-action="run"' not in setup.text

    search_surface = client.get("/app/search", headers=headers)
    assert search_surface.status_code == 200
    assert 'data-property-decision-workbench' in search_surface.text
    assert 'data-property-search-utility-strip' not in search_surface.text
    assert 'data-property-search-utility="automation"' not in search_surface.text
    assert 'data-property-search-utility="preferences"' not in search_surface.text
    assert "Saved preferences" not in search_surface.text
    assert "Recurring searches, delivery, reports, and repair policy live in the dedicated automation view." not in search_surface.text
    assert "Manage durable rules in Account." not in search_surface.text
    assert "Open automation" not in search_surface.text
    assert "Search people, threads, commitments, decisions, deadlines, evidence, rules, and handoffs." not in search_surface.text

    search = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert search.status_code == 200
    assert 'data-property-app-shell' in search.text
    assert 'data-property-spa-shell' in search.text
    assert 'data-property-pulse-strip' in search.text
    assert 'data-property-mobile-dock' in search.text
    assert 'data-property-decision-workbench' in search.text
    assert 'data-pq-greenfield-shell' in search.text
    assert 'data-pq-theater' in search.text
    assert 'data-workbench-results-table' in search.text
    assert 'data-workbench-row' in search.text
    assert '<a class="pqx-result"' not in search.text
    assert '<article class="pqx-result pqx-card"' in search.text
    assert "ranked homes" in search.text
    assert "Match" in search.text
    assert "Source" in search.text
    assert "Map" in search.text
    assert 'data-pqx-route-preview-strip' in search.text
    assert "Your route" in search.text
    assert "Berlin Hauptbahnhof" in search.text
    assert "https://www.google.com/maps/search/?api=1" in search.text
    assert 'target="_blank" rel="noreferrer">Map</a>' in search.text
    assert "https://www.google.com/maps/dir/?api=1" in search.text
    assert "Evidence" in search.text
    assert "Supermarket" in search.text
    assert "280 m" in search.text
    assert 'class="pqx-route-evidence"' in search.text
    assert 'class="pqx-thumb"' in search.text
    assert "ranked homes" in search.text
    assert "Altbau near U6" in search.text
    assert "Family flat near Tiergarten" in search.text
    assert "360 ready" in search.text
    assert "360 queued" in search.text
    assert "about 12 min" in search.text
    assert 'data-tour-status="queued"' in search.text
    assert 'data-tour-eta="about 12 min"' in search.text
    assert "still waiting on floorplans" in search.text
    assert "not scheduled yet" not in search.text
    assert "360 not ready" not in search.text
    assert "360" in search.text
    assert "Match" in search.text
    assert "EUR 420,000" in search.text
    assert "still waiting on floorplans" in search.text
    assert "Pending layout proof" not in search.text
    assert "These homes are still being checked for a floorplan" in search.text
    assert 'data-pqx-progress-board' in search.text
    assert "Search in progress" in search.text or "Results are ready" in search.text
    assert 'data-pqx-progress-eta' in search.text
    assert 'class="pqx-source-progress"' in search.text
    assert 'class="pqx-source-list"' in search.text
    assert 'class="pqx-route-preview-strip"' in search.text
    assert 'data-research-task-id="mf_rooms_run_42"' not in search.text
    assert 'data-research-task-action="fill"' not in search.text
    assert 'data-research-task-action="dismiss"' not in search.text
    assert "EUR 5,385/m2" in search.text
    assert "Lift and transit fit" in search.text
    assert "Lift and transit fit." in search.text
    assert "Preferred because: Includes a live 360 source" not in search.text
    assert "Open property page" in search.text
    assert 'data-candidate-packet-url="/app/research/' in search.text
    assert 'data-candidate-listing-url="https://www.immobilienscout24.de/expose/altbau-u6"' in search.text
    assert "Filtered" in search.text
    assert "Missing floorplan evidence" in search.text
    assert "Floorplan gate" not in search.text
    assert "still waiting on floorplans" in search.text
    assert "These homes are still being checked for a floorplan" in search.text
    assert "Layout not verified" not in search.text
    assert "Missing floorplan evidence" in search.text
    assert 'data-pqx-filtered-dialog' in search.text
    assert re.search(r"<button[^>]+data-property-start-top[^>]*>\\s*Launch search\\s*</button>", search.text) is None
    assert "Morning Memo" not in search.text
    assert "Office signals ingested" not in search.text
    family_candidate_ref = landing_routes._property_candidate_ref(
        {
            "title": str(second_candidate.get("title") or "").strip(),
            "property_url": str(second_candidate.get("property_url") or "").strip(),
            "review_url": str(second_candidate.get("review_url") or "").strip(),
            "tour_url": str(second_candidate.get("tour_url") or "").strip(),
            "source_label": "ImmoScout24 Germany",
        }
    )
    selected_candidate = client.get(
        "/app/properties",
        params={"run_id": "run-42", "candidate": family_candidate_ref},
        headers=headers,
    )
    assert selected_candidate.status_code == 200
    assert "Family flat near Tiergarten" in selected_candidate.text

    shortlist = client.get("/app/shortlist", params={"run_id": "run-42"}, headers=headers)
    assert shortlist.status_code == 200
    assert "ranked homes" in shortlist.text
    assert "Altbau near U6" in shortlist.text
    assert "Open property" in shortlist.text
    assert "Hosted review" not in shortlist.text
    assert "Open feedback" not in shortlist.text
    shortlist_payload_match = re.search(
        r'<script type="application/json" data-property-workbench-json>(.*?)</script>',
        shortlist.text,
        re.S,
    )
    assert shortlist_payload_match is not None
    shortlist_payload = json.loads(shortlist_payload_match.group(1))
    assert len(shortlist_payload.get("results") or []) >= 2
    assert str(((shortlist_payload.get("results") or [{}])[0]).get("title") or "").strip() == "Altbau near U6"

    research = client.get("/app/research", params={"run_id": "run-42"}, headers=headers)
    assert research.status_code == 200
    assert "ranked homes" in research.text
    assert "/app/research/" in research.text
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-42"', research.text)
    assert packet_match is not None

    packet = client.get(packet_match.group(1), params={"run_id": "run-42", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Internal property dossier with fit reasoning" not in packet.text
    assert "Open the space before you read the rest" not in packet.text
    assert "360 review first" not in packet.text
    assert 'data-object-media-stage' in packet.text
    assert 'title="Property 360 review"' not in packet.text
    assert packet.text.index("data-object-media-stage") < packet.text.index("At a glance")
    assert "360 needs rebuild" in packet.text
    assert "Rebuild 3D tour" in packet.text
    assert 'data-property-research-detail' in packet.text
    assert "At a glance" in packet.text
    assert "Current recommendation" not in packet.text
    assert "Why this was selected" not in packet.text
    assert "Supermarket" in packet.text
    assert "https://www.google.com/maps/dir/" not in packet.text
    assert "Open navigation" not in packet.text
    assert "Library" in packet.text
    assert "Underground" in packet.text
    assert "Current read" in packet.text
    assert "What to do next" in packet.text
    assert "Evidence added" in packet.text
    assert "Manual clearance required" in packet.text
    assert "Luftmessnetz: aktuelle Messdaten Wien" in packet.text
    assert "What the wider evidence says" in packet.text
    assert "Energy posture and heating" in packet.text
    assert "School context" in packet.text
    assert "Gymnasium progression" in packet.text
    assert "Return and costs" in packet.text
    assert "Gross yield" in packet.text
    assert "Expected monthly rent" in packet.text
    assert "Decision support" in packet.text
    assert "Candidate" in packet.text
    assert "Layout" in packet.text
    assert "Family flat near Tiergarten" in packet.text
    assert "Listing" in packet.text
    assert "Review page" not in packet.text
    assert "Useful links" not in packet.text
    assert "Open listing" in packet.text
    assert "Would you pursue this home?" not in packet.text
    assert "Save your decision" in packet.text
    assert "Viewing requested" in packet.text
    assert "Request missing documents" in packet.text
    assert "Offer candidate" in packet.text
    assert "Extra tools" in packet.text
    assert "Open question helper" in packet.text
    assert "Ask agent next" not in packet.text
    assert "Tracked follow-up" in packet.text
    assert "What changed" in packet.text
    assert "What others flagged" in packet.text
    assert "Household alignment" in packet.text
    assert "Risk signals" in packet.text
    assert "Contradicted" in packet.text
    assert "Resolved" in packet.text
    assert 'data-object-feedback-reaction="like"' in packet.text
    assert 'data-object-feedback-save' in packet.text
    assert "Save answer" in packet.text
    assert "Manage preferences" in packet.text
    assert "rgba(18, 23, 34" not in packet.text
    assert "rgba(15, 19, 26" not in packet.text
    assert "background: var(--panel);" in packet.text

    profile = client.get("/app/profile", params={"run_id": "run-42"}, headers=headers)
    assert profile.status_code == 200
    assert "Account" in profile.text
    assert "Identity, plan, delivery, and editable defaults." in profile.text

    alerts = client.get("/app/alerts", params={"run_id": "run-42"}, headers=headers)
    assert alerts.status_code == 200
    assert "Alerts" in alerts.text
    assert "Delivery rules" in alerts.text
    assert "Email" in alerts.text
    assert "Telegram" in alerts.text
    assert "WhatsApp" in alerts.text
    assert "STOP/START" in alerts.text
    assert "Outbound channels must stay opt-in" in alerts.text

    notifications_preview = client.get("/app/properties/notifications/preview", params={"template": "property_match"}, headers=headers)
    assert notifications_preview.status_code == 200
    assert "Email preview" in notifications_preview.text
    assert "Property match: Altbau near U6" in notifications_preview.text
    assert "PropertyQuarry shortlisted a property match" in notifications_preview.text
    assert "No — tell us why" in notifications_preview.text

    workspace_preview = client.get("/app/properties/notifications/preview", params={"template": "workspace_invitation"}, headers=headers)
    assert workspace_preview.status_code == 200
    assert "Mara invited you to PropertyQuarry" in workspace_preview.text
    assert "Open invite" in workspace_preview.text

    billing = client.get("/app/billing", params={"run_id": "run-42"}, headers=headers)
    assert billing.status_code == 200
    assert "Billing" in billing.text
    assert "Your plan" in billing.text
    assert "Billing history" in billing.text
    assert "Cancellation and refunds" in billing.text
    assert "Invoice handoff" in billing.text
    assert "Billing truth" not in billing.text
    assert "Commercial truth" not in billing.text
    assert "Plan and limits" not in billing.text
    assert "Plan unit" not in billing.text
    assert "PayFunnels" not in billing.text
    assert "What is available now" not in billing.text
    assert "Current search access" not in billing.text
    assert billing.text.count("Plan") >= 1
    assert billing.text.count("Checkout") <= 2
    billing_payload_source = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_property_workspace_payload.py").read_text(encoding="utf-8")
    assert 'row_item("Provider", str(property_state.get("billing_checkout_provider_label")' not in billing_payload_source


def test_property_billing_surface_shows_compact_payment_history() -> None:
    client = build_property_client(principal_id="exec-property-billing-history")
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Billing History Office")
    response = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "property_search_enabled": True,
            "property_commercial": {
                "active_plan_key": "plus",
                "status": "active",
                "billing_events_json": [
                    {
                        "event_id": "evt_pay_1",
                        "event_type": "payment.completed",
                        "provider": "payfunnels",
                        "plan_key": "plus",
                        "order_id": "pf_123",
                        "invoice_id": "inv_123",
                        "invoice_status": "issued",
                        "accounting_status": "invoice_pending",
                        "payment_status": "paid",
                        "amount_eur": "3.00",
                        "net_amount_eur": "2.52",
                        "vat_amount_eur": "0.48",
                        "vat_rate": "20%",
                        "recorded_at": "2026-06-20T12:00:00+00:00",
                    }
                ],
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    billing = client.get("/app/billing", headers=headers)

    assert billing.status_code == 200
    assert "Billing history" in billing.text
    assert "Payment Completed" in billing.text
    assert "Paid | EUR 3.00 | 2026-06-20 12:00 | Invoice inv_123 | VAT EUR 0.48" in billing.text
    assert "Plus" in billing.text
    assert "PayFunnels" not in billing.text


def test_property_search_progress_copy_names_providers_not_generic_sources() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    service_source = (repo_root / "ea/app/product/service.py").read_text(encoding="utf-8")
    view_model_source = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "Resolved {source_variant_total} source(s) for scanning." not in service_source
    assert "Resolved {provider_total or source_variant_total} provider(s) for scanning." not in service_source
    assert "Resolved {source_variant_total} source check(s)." not in service_source
    assert "source variant(s)" not in service_source
    assert "Selected {provider_total} provider(s) with expanded coverage." in service_source
    assert "provider_total = _property_search_provider_total(specs)" in service_source
    assert "provider_group_total = _property_search_provider_group_total(specs)" in service_source
    assert 'else "Sources"' not in view_model_source
    assert '"label": "Source checks"' not in view_model_source


def test_propertyquarry_search_range_controls_use_selected_country_currency() -> None:
    client = build_property_client(principal_id="pq-search-currency-uk")
    start_workspace(client, mode="personal", workspace_name="Property Search Currency UK")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "London",
            "selected_platforms": ["rightmove"],
        },
    )
    assert stored.status_code == 200, stored.text

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})

    assert response.status_code == 200
    assert 'data-range-control="max_price_eur"' in response.text
    assert 'data-range-format="currency_eur"' in response.text
    assert 'data-range-currency-code="GBP"' in response.text
    assert "GBP 2M" in response.text


def test_property_research_decision_rows_remove_clarification_noise() -> None:
    rows = landing_property_research._property_packet_decision_rows(
        candidate={"recommendation": "ask for clarification"},
        match_reasons=["Layout fits."],
        mismatch_reasons=["Operating costs missing."],
        missing_rows=[{"tag": "important"}],
    )

    text = " ".join(str(row.get("detail") or row.get("title") or row.get("tag") or "") for row in rows)
    assert "ask for clarification" not in text.lower()
    assert "request clarification" not in text.lower()
    assert "Best next move" not in text
    assert any(row.get("title") == "Next" for row in rows)
    assert "Verify the missing evidence before spending more time on it" in text


def test_property_counterfactual_budget_action_uses_market_currency() -> None:
    rows = landing_property_workspace_helpers._property_counterfactual_rows(
        preferences={"max_price_eur": 500000},
        raw_preferences={"max_price_eur": 500000},
        run_summary={"sources": [{"filtered_area_total": 4}]},
        provider_options=[],
        current_platform_cap=0,
        currency_code="GBP",
    )

    budget_row = next(row for row in rows if row.get("tag") == "Budget")
    assert budget_row["action_label"] == "Raise to GBP 550,000"
    assert budget_row["slider"] == {
        "kind": "budget",
        "field": "max_price_eur",
        "label": "Budget ceiling",
        "min": 500000,
        "max": 675000,
        "step": 5000,
        "value": 550000,
        "unit": "GBP",
    }
    assert "EUR" not in str(budget_row["action_label"])


def test_property_packets_dashboard_uses_customer_facing_language() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_packets.html"
    body = template_path.read_text(encoding="utf-8")

    assert "Share polished property pages and track the replies." in body
    assert "Packet sharing" not in body
    assert "Sharing" in body
    assert "Ready to send" in body
    assert "Privacy checked · PDF ready · Sharing controls active" in body
    assert "Paste shared page link" in body
    assert "Copy response endpoint" in body
    assert "Which property pages can safely leave your account" in body
    assert "https://packets.propertyquarry.com/p/..." not in body
    assert "Copy response URL" not in body
    assert "Sharing cockpit" not in body
    assert "Publication queue" not in body
    assert "source_pdf_sha256" not in body
    assert "renderer_version" not in body
    assert "Share page" in body
    assert "Share packet" not in body
    assert "Household reactions" in body
    assert "Packet posture" not in body


def test_property_object_detail_feedback_script_avoids_magicfit_preview_innerhtml() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail_feedback_script.html"
    body = template_path.read_text(encoding="utf-8")

    render_magicfit_block = body.split("const renderMagicFitPreview = (scene) => {", 1)[1].split("const renderMagicFitReferenceList = () => {", 1)[0]
    assert "innerHTML" not in render_magicfit_block
    assert "document.createElement('img')" in render_magicfit_block
    assert "appendTextNode(" in render_magicfit_block

    legacy_template = Path(__file__).resolve().parents[1] / "ea/app/templates/app/object_detail.html"
    legacy_body = legacy_template.read_text(encoding="utf-8")
    legacy_block = legacy_body.split("const renderMagicFitPreview = (scene) => {", 1)[1].split("const renderMagicFitReferenceList = () => {", 1)[0]
    assert "innerHTML" not in legacy_block
    assert "document.createElement('img')" in legacy_block
    reference_block = legacy_body.split("const renderMagicFitReferenceList = () => {", 1)[1].split("renderMagicFitPreview(payload.magic_fit_scene || {});", 1)[0]
    assert "innerHTML" not in reference_block
    followup_block = legacy_body.split("const renderFollowups = (rows) => {", 1)[1].split("renderFollowups(payload.followup_rows || []);", 1)[0]
    assert "innerHTML" not in followup_block
    clippy_block = legacy_body.split("const renderClippy = (body) => {", 1)[1].split("clippyAskButton?.addEventListener", 1)[0]
    assert "innerHTML" not in clippy_block


def test_public_tour_allow_and_deny_extension_sets_do_not_overlap() -> None:
    overlap = public_tours._PUBLIC_TOUR_ALLOWED_ASSET_EXTENSIONS & public_tours._PUBLIC_TOUR_DENIED_ASSET_EXTENSIONS
    assert overlap == frozenset()


def test_propertyquarry_public_product_copy_uses_property_page_language() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    product_page = (repo_root / "ea/app/templates/product_page.html").read_text(encoding="utf-8")
    pricing_page = (repo_root / "ea/app/templates/pricing_page.html").read_text(encoding="utf-8")

    assert "research packets" not in product_page
    assert "research packet" not in pricing_page
    assert "hosted packet" not in pricing_page
    assert "property page" in product_page
    assert "property page" in pricing_page


def test_propertyquarry_settings_and_onboarding_avoid_workspace_customer_copy() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    onboarding = (repo_root / "ea/app/services/onboarding.py").read_text(encoding="utf-8")
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "Finalize your workspace preferences" not in onboarding
    assert "Current workspace posture" not in view_models
    assert '"label": "Workspace"' not in view_models


def test_property_workbench_recent_reviews_do_not_render_fake_links() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert "href=\"{{ packet.get('url') or '#' }}\"" not in body
    assert "packet.get('url')" in body
    assert "pqx-recent-review" in body
    assert "pqx-recent-review-static" in body
    assert "<span class=\"pqx-pill\">{{ packet.get('title') }}</span>" not in body
    assert ".pqx-recent-review" in body
    assert "overflow-wrap: anywhere;" not in body


def test_property_workbench_previous_search_cards_have_explicit_overflow_gate() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")

    assert 'data-pqx-previous-search-card' in body
    assert 'data-pqx-scope-preview' in body
    assert 'class="pqx-previous-scope-image"' in body
    assert 'class="pqx-previous-scope-trigger"' in body
    assert 'class="pqx-previous-title"' in body
    assert 'class="pqx-previous-delete"' in body
    assert 'class="pqx-previous-open-link"' in body
    assert 'data-pqx-scope-lightbox' in body
    assert ".pqx-previous-title" in body
    assert "-webkit-line-clamp: 1;" in body
    assert ".pqx-previous-scope-preview" in body
    assert "aspect-ratio: 16 / 8;" in body
    assert ".pqx-previous-search {" in body
    assert "grid-template-columns: minmax(0, 1fr);" in body
    assert "border-bottom: 1px solid var(--pq-line);" in body


def test_property_workspace_search_agents_have_explicit_overflow_gate() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_workspace.html"
    assert not template_path.exists()


def test_propertyquarry_pixefy_visual_watch_audits_periodic_screenshots() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts/propertyquarry_visual_watch.py"
    body = script.read_text(encoding="utf-8")

    assert "PROPERTYQUARRY_PIXEFY_INTERVAL_SECONDS" in body
    assert "page.screenshot" in body
    assert "escaped" in body
    assert "offscreenMedia" in body
    assert "screenFitTargets" in body
    assert "fitsViewport" in body
    assert "duplicateGraphics" in body
    assert "visual-watch-report.json" in body


def test_property_workbench_sparse_candidates_do_not_display_raw_urls() -> None:
    body = _read_workbench_bundle()

    assert "candidate.get('title') or candidate.get('property_url')" not in body
    assert "candidate?.title || candidate?.property_url" not in body
    assert "source?.source_label || source?.platform || source?.source_url" not in body
    assert "candidate.get('title') or 'Property candidate'" in body
    assert "candidate?.title || 'Property candidate'" in body


def test_property_workspace_source_cards_do_not_display_raw_source_urls() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_workspace.html"
    assert not template_path.exists()


def test_property_search_property_type_uses_checkbox_multi_select() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    templates = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/console_shell.html",
    ]

    for template_path in templates:
        body = template_path.read_text(encoding="utf-8")
        assert "field.name == 'property_type'" in body, f"{template_path.name} does not include property_type control branch"
        assert re.search(r'type="checkbox"\s*name="{{\s*field\.name\s*}}"', body), (
            f"{template_path.name} does not render property_type as checkbox"
        )
        assert '<select name="property_type"' not in body, f"{template_path.name} still renders property_type as select"


def test_property_search_agents_can_load_saved_filters_into_form() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "ea/app/templates/app/property_decision_workbench.html"
    agents_partial = repo_root / "ea/app/templates/app/_property_search_agents_panel.html"
    script_partial = repo_root / "ea/app/templates/app/_property_workbench_script.html"
    brief_script_partial = repo_root / "ea/app/templates/app/_property_workbench_brief_script.html"
    feedback_script_partial = repo_root / "ea/app/templates/app/_property_workbench_feedback_script.html"
    body = template_path.read_text(encoding="utf-8")
    agents_body = agents_partial.read_text(encoding="utf-8")
    script_body = script_partial.read_text(encoding="utf-8")
    brief_script_body = brief_script_partial.read_text(encoding="utf-8")
    feedback_script_body = feedback_script_partial.read_text(encoding="utf-8")

    assert '{% include "app/_property_search_agents_panel.html" %}' in body
    assert "data-search-agent-payload" in agents_body
    assert 'class="pqx-automation-thumbnail"' in agents_body
    assert "agent_load_href = '/app/search?load_agent='" in agents_body
    assert '<a class="pqx-automation-thumbnail" href="{{ agent_load_href }}"' in agents_body
    assert 'class="pqx-automation-thumbnail-action">Edit</span>' in agents_body
    assert 'data-search-agent-action="delete"' in agents_body
    assert ">Edit</button>" not in agents_body
    assert "Load filters" not in body
    assert "applySearchAgentPayloadToForm" in script_body
    assert "resetSearchBriefForm" in script_body
    assert "resetSearchBriefForm();" in script_body
    assert "Saved search ready to edit. Tweak the filters or run it again." in script_body
    assert "Delete ${label}?" in script_body
    assert "data-search-agent-loaded-state" in body
    assert "Loaded: ${label}" in script_body
    assert "data-search-agent-dirty-label" in body
    assert "Unsaved changes in ${dirtyFields} field" in script_body
    assert "data-search-agent-save-current" in body
    assert "data-search-agent-save-new" in body
    assert "data-search-agent-reset" in body
    assert '{% include "app/_property_workbench_brief_script.html" %}' in script_body
    assert "'search_mode'" in brief_script_body
    assert "search_mode: fieldValue(form, 'search_mode') || 'strict'" in brief_script_body
    assert "Object.entries(source).forEach" in script_body or "Object.entries(source).forEach" in brief_script_body
    assert "Save as new" in body
    assert "credentials: 'same-origin'" in script_body
    assert "authHeaders()" not in script_body
    assert "load_agent" in script_body
    assert "propertyDecisionStateEndpoint" in script_body
    assert '{% include "app/_property_workbench_feedback_script.html" %}' in script_body
    assert "No saved decision yet. Choose Yes, Maybe, No, or Hide to start the decision trail." in feedback_script_body
    assert "Current state" in feedback_script_body
    assert "data-pw-agent-question-id" in feedback_script_body
    assert "data-pw-document-id" in feedback_script_body


def test_property_workspace_search_form_exposes_austria_evidence_and_eligibility_controls() -> None:
    template_body = _read_workbench_bundle()
    view_model_body = (
        Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py"
    ).read_text(encoding="utf-8")

    assert "School evidence priority" in view_model_body
    assert "Wiener Wohn-Ticket available" in view_model_body
    assert "Subsidized or cooperative supply only" in view_model_body
    assert "Require school evidence" in view_model_body
    assert "Require energy certificate evidence" in view_model_body
    assert "Require operating-cost evidence" in view_model_body
    assert "Court and auction review" in view_model_body
    assert "Require high-speed internet evidence" in view_model_body
    assert "Avoid noise-risk area" in view_model_body
    assert "keyword_priority_group" in view_model_body
    assert "Ganztag matters" not in view_model_body
    assert "require_school_evidence" in template_body
    assert "wiener_wohnticket_available" in template_body
    assert "subsidized_required" in template_body
    assert "miete_mit_kaufoption" in template_body
    assert "eigenmittel_max_eur" in template_body
    assert "application_window_days" in template_body
    assert "require_energy_certificate" in template_body
    assert "require_operating_cost_statement" in template_body
    assert "enable_auction_legal_review" in template_body
    assert "platform_defaults_by_country_mode" in template_body
    assert "defaultPlatformsForCountryMode" in template_body
    assert "Public records" in template_body
    assert "Official checks" not in template_body
    assert "evidence_source_catalog_by_country" in template_body


def test_property_workspace_templates_expose_account_navigation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    console_shell = (repo_root / "ea/app/templates/base_console.html").read_text(encoding="utf-8")
    workbench = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    for body in (console_shell, workbench):
        assert "Account navigation" in body
        assert ">Upgrade<" in body
        assert ">Profile<" in body
        assert ">Settings<" in body
        assert ">Log out<" in body
        assert "account_nav.sign_out_action" in body


def test_property_workspace_hero_actions_use_visible_propertyquarry_surfaces() -> None:
    body = _read_workbench_bundle()
    assert "Search" in body
    assert "Shortlist" in body
    assert "Automation" in body


def test_property_workspace_sign_out_clears_workspace_session_cookie() -> None:
    principal_id = "pq-account-sign-out"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text
    access_body = access_session.json()

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")

    workspace = client.get("/app/properties")
    assert workspace.status_code == 200
    assert "Account navigation" in workspace.text
    assert "Upgrade" in workspace.text
    assert "Log out" in workspace.text

    hostile_sign_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert hostile_sign_out.status_code == 403
    assert hostile_sign_out.json()["error"]["code"] == "cross_site_browser_mutation"
    assert client.cookies.get("ea_workspace_session")

    signed_out = client.post("/app/actions/sign-out", data={"return_to": "/"}, follow_redirects=False)
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/"
    sign_out_cookie = str(signed_out.headers.get("set-cookie") or "")
    assert "ea_workspace_session=" in sign_out_cookie
    assert "Max-Age=0" in sign_out_cookie or "expires=" in sign_out_cookie.lower()
    assert not client.cookies.get("ea_workspace_session")

    signed_out_workspace = client.get("/app/properties")
    assert signed_out_workspace.status_code == 200
    assert "Signed in" not in signed_out_workspace.text


def test_property_workspace_sign_out_clears_cookie_variants() -> None:
    principal_id = "pq-account-sign-out-variants"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Outlet")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text
    access_body = access_session.json()

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    open_cookie_headers = opened_access.headers.get_list("set-cookie")
    assert any("ea_workspace_session=" in item and "Domain=.propertyquarry.com" in item for item in open_cookie_headers)

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={
            "Host": "www.propertyquarry.com",
            "Origin": "https://www.propertyquarry.com",
        },
        follow_redirects=False,
    )
    assert signed_out.status_code == 303
    clear_cookie_headers = signed_out.headers.get_list("set-cookie")
    assert len(clear_cookie_headers) >= 4
    assert any("ea_workspace_session=" in item and "Domain=.propertyquarry.com" in item and "Secure" in item for item in clear_cookie_headers)
    assert any("ea_workspace_session=" in item and "Domain=.propertyquarry.com" in item and "Secure" not in item for item in clear_cookie_headers)
    assert any("ea_workspace_session=" in item and "Domain" not in item and "Secure" in item for item in clear_cookie_headers)
    assert any("ea_workspace_session=" in item and "Domain" not in item and "Secure" not in item for item in clear_cookie_headers)
    assert any("ea_workspace_session=" in item and "Path=/app" in item and "Secure" not in item for item in clear_cookie_headers)
    assert not client.cookies.get("ea_workspace_session")


def test_property_workspace_sign_out_clears_cookie_on_local_host_without_domain_scope() -> None:
    principal_id = "pq-account-sign-out-localhost-no-domain"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Outlet Local")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
        headers={"Host": "localhost:8097"},
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], headers={"Host": "localhost:8097"}, follow_redirects=False)
    assert opened_access.status_code == 303

    open_cookie_headers = opened_access.headers.get_list("set-cookie")
    assert any("ea_workspace_session=" in item for item in open_cookie_headers)
    assert all("Domain=" not in item for item in open_cookie_headers)

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={
            "Host": "localhost:8097",
            "Origin": "https://localhost:8097",
        },
        follow_redirects=False,
    )
    assert signed_out.status_code == 303
    clear_cookie_headers = signed_out.headers.get_list("set-cookie")
    assert len(clear_cookie_headers) >= 2
    assert all("Domain=" not in item for item in clear_cookie_headers)
    assert any("Secure" in item for item in clear_cookie_headers)
    assert any("Secure" not in item for item in clear_cookie_headers)
    assert not client.cookies.get("ea_workspace_session")


def test_property_workspace_sign_out_removes_signed_in_ui_globally() -> None:
    principal_id = "pq-account-sign-out-surface-globals"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Global Signed-Out Check")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text
    access_body = access_session.json()

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert "ea_workspace_session=" in str(opened_access.headers.get("set-cookie") or "")

    signed_in_properties = client.get("/app/properties")
    assert signed_in_properties.status_code == 200
    assert "aria-label=\"Account navigation\"" in signed_in_properties.text

    signed_out = client.post("/app/actions/sign-out", data={"return_to": "/"}, follow_redirects=False)
    assert signed_out.status_code == 303
    assert not client.cookies.get("ea_workspace_session")

    anonymous_properties = client.get("/app/properties")
    assert anonymous_properties.status_code == 200
    assert "aria-label=\"Account navigation\"" not in anonymous_properties.text

    anonymous_account = client.get("/app/account")
    assert anonymous_account.status_code == 200
    assert "aria-label=\"Account navigation\"".lower() not in anonymous_account.text.lower()


def test_property_workspace_sign_out_accepts_default_https_port_variants() -> None:
    principal_id = "pq-account-sign-out-port-normalization"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Port Normalization Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert client.cookies.get("ea_workspace_session")

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={
            "Host": "propertyquarry.com:443",
            "Origin": "https://propertyquarry.com",
        },
        follow_redirects=False,
    )
    assert signed_out.status_code == 303, signed_out.text
    assert signed_out.headers["location"] == "/"
    assert "ea_workspace_session=" in str(signed_out.headers.get("set-cookie") or "")
    assert not client.cookies.get("ea_workspace_session")


def test_property_workspace_sign_out_accepts_www_host_variants() -> None:
    principal_id = "pq-account-sign-out-www-normalization"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="WWW Host Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert client.cookies.get("ea_workspace_session")

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={
            "Host": "www.propertyquarry.com",
            "Origin": "https://www.propertyquarry.com",
        },
        follow_redirects=False,
    )
    assert signed_out.status_code == 303, signed_out.text
    assert signed_out.headers["location"] == "/"
    assert "ea_workspace_session=" in str(signed_out.headers.get("set-cookie") or "")
    assert not client.cookies.get("ea_workspace_session")


def test_property_workspace_sign_out_clears_secure_cookie_attributes() -> None:
    principal_id = "pq-account-sign-out-secure"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Secure Cookie Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={
            "Host": "propertyquarry.com",
            "Origin": "https://propertyquarry.com",
            "x-forwarded-proto": "https",
        },
        follow_redirects=False,
    )
    set_cookie = str(signed_out.headers.get("set-cookie") or "")
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/"
    assert "ea_workspace_session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()
    assert "Secure" in set_cookie


def test_property_workspace_sign_out_redirects_cloudflare_access_to_access_logout(monkeypatch) -> None:
    principal_id = "pq-account-sign-out-cf"
    monkeypatch.setenv("EA_CF_ACCESS_TEAM_DOMAIN", "demo.cloudflareaccess.com")

    client = build_property_client(principal_id=principal_id)
    app = client.app
    app.dependency_overrides[get_request_context] = lambda: RequestContext(
        principal_id="cf-email:user@example.com",
        authenticated=True,
        auth_source="cloudflare_access",
        access_email="user@example.com",
        operator_id="",
    )
    client.headers.pop("X-EA-Principal-ID", None)
    try:
        signed_out = client.post(
            "/app/actions/sign-out",
            data={"return_to": "/app/account"},
            headers={
                "Host": "propertyquarry.com",
                "Origin": "https://propertyquarry.com",
                "x-forwarded-proto": "https",
            },
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_request_context, None)

    assert signed_out.status_code == 303
    location = str(signed_out.headers.get("location") or "")
    parsed = urllib.parse.urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "demo.cloudflareaccess.com"
    assert parsed.path == "/cdn-cgi/access/logout"
    query = urllib.parse.parse_qs(parsed.query or "")
    assert "return_to" in query
    assert query["return_to"][0].endswith("/app/account")
    assert "ea_workspace_session=" in str(signed_out.headers.get("set-cookie") or "")


def test_property_workspace_sign_out_works_via_get() -> None:
    principal_id = "pq-account-sign-out-get"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Get Logout")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Personal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert client.cookies.get("ea_workspace_session")

    signed_out = client.get(
        "/app/actions/sign-out?return_to=/",
        follow_redirects=False,
        headers={"Host": "propertyquarry.com"},
    )
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/"
    assert "ea_workspace_session=" in str(signed_out.headers.get("set-cookie") or "")
    assert not client.cookies.get("ea_workspace_session")


def test_propertyquarry_workspace_session_root_home_override_stays_public() -> None:
    principal_id = "pq-root-cookie-home"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Root Cookie Home Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_session.json()["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert client.cookies.get("ea_workspace_session")

    root = client.get("/", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/app/search"

    public_home = client.get("/?home=1", headers={"host": "propertyquarry.com"}, follow_redirects=False)
    assert public_home.status_code == 200
    assert "Search once. Rank the right homes. Decide with evidence." in public_home.text
    assert 'href="/?home=1" aria-label="PropertyQuarry home"' in public_home.text
    assert 'href="/app/search"' in public_home.text
    assert ">Sign in<" not in public_home.text
    assert "Signing you in" not in public_home.text
    assert 'data-target-endpoint="/app/api/property/landing-handoff"' not in public_home.text


def test_property_workspace_browser_forms_accept_same_origin_mutations() -> None:
    principal_id = "pq-account-same-origin-post"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    access_session = client.post(
        "/app/api/access-sessions",
        json={
            "email": "principal@example.com",
            "role": "principal",
            "display_name": "Principal Access",
            "expires_in_hours": 24,
        },
    )
    assert access_session.status_code == 200, access_session.text
    access_body = access_session.json()

    client.headers.pop("X-EA-Principal-ID", None)
    opened_access = client.get(access_body["access_url"], follow_redirects=False)
    assert opened_access.status_code == 303
    assert client.cookies.get("ea_workspace_session")

    signed_out = client.post(
        "/app/actions/sign-out",
        data={"return_to": "/"},
        headers={"Origin": "https://propertyquarry.com"},
        follow_redirects=False,
    )
    assert signed_out.status_code == 303
    assert signed_out.headers["location"] == "/"
    assert not client.cookies.get("ea_workspace_session")


def test_property_properties_surface_skips_recent_runs_load_without_explicit_run(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-fast-properties")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _explode(*args, **kwargs):
        raise AssertionError("properties surface should not load recent runs on first visit")

    monkeypatch.setattr(ProductService, "list_property_search_runs", _explode)

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert 'data-property-decision-workbench' in response.text


def test_property_properties_surface_uses_active_run_lookup_without_recent_run_list(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-properties-active-run-lookup")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _explode(self, *, principal_id: str, limit: int = 8):
        raise AssertionError("properties surface should not hydrate the recent run list")

    def _fake_active_run(self, *, principal_id: str, limit: int = 8):
        assert principal_id == "pq-properties-active-run-lookup"
        return {"run_id": "run-live-lookup", "status": "in_progress", "summary": {"status": "in_progress"}}

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-properties-active-run-lookup"
        assert run_id == "run-live-lookup"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "status_label": "Search in progress",
            "progress": 17,
            "message": "Reviewing candidate 3 of 12.",
            "summary": {"status": "in_progress", "sources": [], "ranked_candidates": []},
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _explode)
    monkeypatch.setattr(ProductService, "find_active_property_search_run", _fake_active_run)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "run-live-lookup" in response.text


def test_property_search_form_defaults_to_discovery_after_thin_strict_run(monkeypatch) -> None:
    payload = landing_routes._property_workspace_payload(
        "properties",
        status={"workspace": {"name": "Discovery Default"}, "channels": {}},
        property_state={
            "preferences": {
                "country_code": "AT",
                "listing_mode": "rent",
                "region_code": "vienna",
                "location_query": "1020 Vienna",
                "search_mode": "strict",
            },
            "run": {
                "status": "completed",
                "summary": {
                    "ranked_total": 2,
                    "sources_total": 8,
                    "listing_total": 31,
                    "ranked_candidates": [
                        {"candidate_ref": "candidate-1", "title": "Candidate 1"},
                        {"candidate_ref": "candidate-2", "title": "Candidate 2"},
                    ],
                },
            },
            "commercial": {},
            "preference_bundle": {},
        },
    )

    search_mode_field = next(
        field
        for field in list((payload.get("console_form") or {}).get("fields") or [])
        if str(field.get("name") or "").strip() == "search_mode"
    )
    assert search_mode_field["value"] == "discovery"
    assert search_mode_field["options"] == [
        {"value": "strict", "label": "Strict shortlist"},
        {"value": "discovery", "label": "Discovery pass"},
    ]
    assert "turns school, family, and entertainment distance misses into ranking penalties" in str(search_mode_field.get("tooltip") or "")


def test_property_workspace_payload_returns_decision_workbench_contract_shape() -> None:
    payload = landing_routes._property_workspace_payload(
        "billing",
        status={"workspace": {"name": "Contract Shape"}, "channels": {}},
        property_state={
            "preferences": {"country_code": "AT", "listing_mode": "buy"},
            "commercial": {"current_plan_label": "Agent", "current_plan_key": "agent"},
            "preference_bundle": {},
        },
    )

    assert payload["title"] == "Billing"
    assert isinstance(payload["decision_workbench"], dict)
    assert isinstance(payload["decision_workbench"]["run"], dict)
    assert isinstance(payload["decision_workbench"]["brief"], dict)
    assert payload["current_plan_label"] == "Agent"


def test_property_billing_payload_skips_full_preference_manager_build(monkeypatch) -> None:
    monkeypatch.setattr(
        landing_view_models,
        "_property_preference_schema",
        lambda: (_ for _ in ()).throw(AssertionError("billing surface should not build the full preference manager schema")),
    )

    payload = landing_routes._property_workspace_payload(
        "billing",
        status={"workspace": {"name": "Billing Scope"}, "channels": {}},
        property_state={
            "preferences": {"country_code": "AT", "listing_mode": "buy"},
            "commercial": {"current_plan_label": "Agent", "current_plan_key": "agent"},
            "preference_bundle": {
                "preference_nodes": [
                    {"node_id": "node-1", "status": "active", "key": "budget_max", "value_json": 900000}
                ]
            },
        },
    )

    preference_manager = dict(payload.get("preference_manager") or {})
    assert preference_manager.get("schema") == {}
    assert preference_manager.get("nodes") == []
    assert len(list(preference_manager.get("active_nodes") or [])) == 1


def test_property_search_posture_summary_hides_child_rows_when_parent_toggles_are_off() -> None:
    payload = landing_routes._property_workspace_payload(
        "properties",
        status={"workspace": {"name": "Summary Hygiene"}, "channels": {}},
        property_state={
            "preferences": {
                "country_code": "AT",
                "search_goal": "investment",
                "listing_mode": "buy",
                "investment_research_mode": "off",
                "investment_strategy": "cash_flow",
                "min_gross_yield_pct": 6,
                "equity_available_eur": 250000,
                "min_dscr": 1.35,
                "enable_commute_research": False,
                "commute_destination": "Stephansplatz",
                "additional_reachability_targets": "Praterstern",
                "enable_lifestyle_research": False,
                "university_name": "WU Wien",
                "school_stage_preferences": ["volksschule"],
                "require_school_evidence": True,
                "school_evidence_priority": "very_important",
                "include_developer_project_signals": False,
                "desired_project_stages": ["planned", "waitlist"],
                "include_public_housing_signals": False,
                "wiener_wohnticket_available": True,
                "subsidized_required": True,
                "miete_mit_kaufoption": True,
                "eigenmittel_max_eur": 25000,
                "application_window_days": 14,
                "include_distressed_sale_signals": False,
                "enable_auction_legal_review": True,
            },
            "commercial": {},
            "preference_bundle": {},
        },
    )

    search_posture_card = next(
        card
        for card in list(payload.get("primary_cards") or [])
        if str(card.get("eyebrow") or "").strip() == "Search posture"
    )
    labels = {
        str(item.get("title") or "").strip()
        for item in list(search_posture_card.get("items") or [])
        if isinstance(item, dict)
    }
    assert "Investment strategy" not in labels
    assert "Minimum gross yield" not in labels
    assert "Equity available" not in labels
    assert "Minimum DSCR" not in labels
    assert "Commute destination" not in labels
    assert "Additional destinations" not in labels
    assert "University focus" not in labels
    assert "Children" not in labels
    assert "School evidence" not in labels
    assert "School evidence priority" not in labels
    assert "Accepted project stages" not in labels
    assert "Wiener Wohn-Ticket" not in labels
    assert "Subsidized supply" not in labels
    assert "Miete mit Kaufoption" not in labels
    assert "Eigenmittel ceiling" not in labels
    assert "Application window" not in labels
    assert "Auction legal review" not in labels


def test_property_search_posture_summary_uses_selected_market_currency() -> None:
    payload = landing_routes._property_workspace_payload(
        "properties",
        status={"workspace": {"name": "Currency Posture"}, "channels": {}},
        property_state={
            "preferences": {
                "country_code": "GB",
                "search_goal": "investment",
                "listing_mode": "buy",
                "investment_research_mode": "auto",
                "equity_available_eur": 250000,
            },
            "commercial": {"current_plan_key": "agent"},
            "preference_bundle": {},
        },
    )

    search_posture_card = next(
        card
        for card in list(payload.get("primary_cards") or [])
        if str(card.get("eyebrow") or "").strip() == "Search posture"
    )
    equity_row = next(
        item
        for item in list(search_posture_card.get("items") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip() == "Equity available"
    )

    assert equity_row["detail"] == "GBP 250 000"


def test_property_dashboard_renders_previous_searches_with_compact_finished_results(monkeypatch) -> None:
    principal_id = "pq-previous-searches"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Previous Search Office")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-finished",
                "principal_id": principal_id,
                "status": "completed",
                "updated_at": "2026-06-13T08:00:00+00:00",
                "property_search_preferences": {
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 12,
                    "listing_total": 21,
                    "notified_total": 2,
                    "top_fit_score": 68,
                    "filtered_floorplan_total": 4,
                    "ranked_candidates": [
                        {
                            "title": "Ruhige 2-Zimmer Wohnung mit Balkon",
                            "source_label": "Willhaben",
                            "fit_score": 68,
                            "price_display": "EUR 1,150",
                            "compare_reason": "Strong district and layout fit.",
                            "packet_url": "/app/research/candidate-1?run_id=run-finished",
                        }
                    ],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/properties", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "1020 Vienna" in page.text
    assert "ranked" in page.text
    assert "pqx-previous-open-link" in page.text
    assert "filtered" in page.text


def test_property_dashboard_failed_previous_search_uses_customer_facing_copy(monkeypatch) -> None:
    principal_id = "pq-previous-search-failed-copy"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Failed Search Copy")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-failed-copy",
                "principal_id": principal_id,
                "status": "failed",
                "message": "Provider returned 403 while fetching Willhaben.",
                "updated_at": "2026-06-13T08:00:00+00:00",
                "property_search_preferences": {
                    "country_code": "AT",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 1,
                    "listing_total": 0,
                    "ranked_candidates": [],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/properties", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Search failed" in page.text
    assert ">Failed<" not in page.text


def test_property_search_agents_have_dedicated_management_page() -> None:
    principal_id = "pq-agent-management"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna apartments",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "buy",
                    "property_type": "apartment",
                    "notification_limit": 3,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "buy",
                        "property_type": "apartment",
                    },
                },
                {
                    "agent_id": "agent-monteverde",
                    "name": "Monteverde land",
                    "enabled": True,
                    "country_code": "CR",
                    "region_code": "puntarenas",
                    "location_query": "Monteverde",
                    "listing_mode": "buy",
                    "property_type": "land",
                    "notification_limit": 5,
                    "notification_period": "week",
                    "preferences_json": {
                        "country_code": "CR",
                        "region_code": "puntarenas",
                        "location_query": "Monteverde",
                        "listing_mode": "buy",
                        "property_type": "land",
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    page = client.get("/app/agents", headers={"host": "propertyquarry.com"})
    assert page.status_code == 200
    assert "Automation" in page.text
    assert "Vienna apartments" in page.text
    assert "Monteverde land" in page.text
    assert "Saved searches" in page.text
    assert 'data-property-search-agent-grid' in page.text
    assert "pqx-automation-table" not in page.text
    assert 'class="pqx-automation-card' in page.text
    assert 'class="pqx-automation-thumbnail"' in page.text
    assert 'href="/app/search?load_agent=agent-vienna"' in page.text
    assert 'href="/app/search?load_agent=agent-monteverde"' in page.text
    assert 'data-search-agent-action="delete"' in page.text
    assert 'title="Delete saved search"' in page.text
    assert "Selected watch, delivery, repair" not in page.text
    assert "Limits" not in page.text
    assert 'href="/app/agents"' in page.text
    assert 'href="/app/search' in page.text
    assert "Run</button>" in page.text
    assert "Refresh" not in page.text
    assert 'class="pqx-automation-thumbnail-action">Edit</span>' in page.text
    assert "Pause</button>" in page.text
    assert "/app/search?load_agent=" in page.text
    assert "/app/search?run_agent=" in page.text
    template = _read_workbench_bundle()
    product_api = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/product_api.py").read_text(encoding="utf-8")
    assert ".pqx-automation-grid" in template
    assert ".pqx-automation-thumbnail" in template
    assert ".pqx-automation-delete" in template
    assert ".pqx-automation-card" in template
    assert 'pqx-automation-scope-empty--fallback' not in template
    assert "Map preview unavailable" not in template
    assert "Map preview unavailable" not in product_api
    assert "Preparing map" in product_api
    assert "object-position: center 44%;" not in template
    assert 'transform: scale(2.18);' not in template
    assert 'transform: scale(3.05);' not in template
    assert '.pqx-automation-thumbnail[data-scope-preview-kind="osm_district_overlay"] img' in template
    assert 'pqx-automation-thumbnail[data-scope-preview-kind="osm_point_fallback"]' not in template
    assert "object-fit: contain;" in template
    assert "transform: none;" in template
    assert "pqx-automation-scope-empty" not in template
    assert "pqx-automation-scope-empty" not in page.text
    assert "osm_map_pending" in template
    assert "/app/api/property/map-previews/0000000000000000000000000000000000000000.png" in template
    assert '.pqx-button[data-pqx-loading="true"]::before' in template
    assert "@keyframes pqxSpin" in template
    script = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")
    assert "root.querySelectorAll('[data-property-start], [data-property-start-top], [data-pqx-launch-top]')" in script
    assert "event.preventDefault();" in script
    assert "setSearchLaunchBusy(true);" in script
    assert "searchLaunchInFlight" in script
    assert "root.querySelector('[data-pqx-launch-top]')?.addEventListener('click'" not in script
    assert "const setPropertyInlineStatus = (message) => {" in script
    assert "data-property-launch-status" in script
    assert "const refreshPendingMapPreviews = () => {" in script
    assert "data-map-preview-refresh-bound" in script
    assert "x-property-map-preview-state" in script
    assert "URL.createObjectURL(blob)" in script
    assert "data-map-preview-ready" in script
    assert "?preview=" not in script
    assert "const stepNav = form.querySelector('[data-property-step-nav]');" in script
    assert "stepNav.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });" in script
    assert "const showPreviewFallback = () => {" not in script
    assert "img.complete && img.naturalWidth === 0" not in script
    assert "thumb.classList.add('is-preview-error')" not in script
    assert "fallback.hidden = false" not in script
    assert "fallback.style.display = 'grid'" not in script
    assert "grid-template-columns: minmax(150px, 0.38fr) minmax(0, 1fr);" in template
    assert ".pqx-automation-table" not in template
    assert '.pqx-shell[data-pqx-surface="agents"] .pqx-mobile-switch' in template
    assert '.pqx-shell[data-pqx-surface="account"] .pqx-mobile-switch' in template
    assert "position: static;" in template
    assert '.pqx-shell[data-pqx-surface="account"] .pqx-brief-drawer-panel > .pqx-section-head' in template
    assert 'data-property-mobile-step-rail' in template
    assert 'data-property-mobile-action-dock' in template
    assert '.pqx-shell[data-pqx-surface="search"] [data-property-mobile-step-rail]' in template
    assert '.pqx-shell[data-pqx-surface="search"] [data-property-mobile-action-dock]' in template
    assert 'scroll-snap-type: x proximity;' in template
    assert '-webkit-overflow-scrolling: touch;' in template
    assert 'env(safe-area-inset-bottom, 0px)' in template
    assert 'contain-intrinsic-size: 142px;' in template


def test_property_agents_surface_uses_map_only_scope_preview_for_cards_and_history(monkeypatch) -> None:
    principal_id = "pq-agent-map-thumbnail"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Fast")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                    },
                }
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    preview_calls: list[tuple[str, str, str]] = []
    map_preview_calls: list[tuple[str, str, str]] = []

    def _rich_scope_preview(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
        preview_calls.append((country_code, region_code, location_query))
        return {
            "image_url": "data:image/png;base64,richscope",
            "summary": location_query,
            "preview_kind": "osm_district_overlay",
            "has_district_overlay": True,
        }

    def _map_scope_preview(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
        map_preview_calls.append((country_code, region_code, location_query))
        return {
            "image_url": "/app/api/property/map-previews/1111111111111111111111111111111111111111.png",
            "summary": location_query,
            "preview_kind": "osm_district_overlay",
            "has_district_overlay": True,
        }

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": f"agent-run-fast-{index}",
                "principal_id": principal_id,
                "active_search_agent_id": "agent-vienna",
                "status": "completed",
                "updated_at": "2026-06-13T09:10:00+00:00",
                "property_search_preferences": {
                    "active_search_agent_id": "agent-vienna",
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {"sources_total": 1, "listing_total": 1, "ranked_candidates": []},
            }
            for index in range(8)
        ]

    monkeypatch.setattr(landing_view_models, "_property_scope_preview", _rich_scope_preview)
    monkeypatch.setattr(landing_view_models, "_property_scope_preview_map_only", _map_scope_preview)
    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)

    page = client.get("/app/agents", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna rent watch" in page.text
    assert "agent-run-fast-0" not in page.text
    assert 'data-scope-preview-kind="osm_district_overlay"' in page.text
    assert 'data-scope-overlay="true"' in page.text
    assert "data:image/svg+xml" not in page.text
    assert preview_calls == []
    assert map_preview_calls == [("AT", "vienna", "1020 Vienna")]


def test_property_agents_surface_uses_map_only_preview_for_saved_search_cards(monkeypatch) -> None:
    principal_id = "pq-agent-fast-card-preview"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Fast Cards")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                    },
                }
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    map_preview_calls: list[tuple[str, str, str]] = []

    def _map_scope_preview(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
        map_preview_calls.append((country_code, region_code, location_query))
        return {
            "image_url": "/app/api/property/map-previews/2222222222222222222222222222222222222222.png",
            "summary": location_query,
            "preview_kind": "osm_district_overlay",
            "has_district_overlay": True,
        }

    monkeypatch.setattr(landing_view_models, "_property_scope_preview_map_only", _map_scope_preview)

    page = client.get("/app/agents", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna rent watch" in page.text
    assert 'data-scope-preview-kind="osm_district_overlay"' in page.text
    assert "data:image/svg+xml" not in page.text
    assert map_preview_calls == [("AT", "vienna", "1020 Vienna")]


def test_property_agents_surface_renders_map_preview_for_every_saved_search(monkeypatch) -> None:
    principal_id = "pq-agent-preview-all"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Preview Cap")

    agents = [
        {
            "agent_id": f"agent-{index}",
            "name": f"Vienna watch {index}",
            "enabled": True,
            "country_code": "AT",
            "region_code": "vienna",
            "location_query": f"10{index + 10} Vienna",
            "listing_mode": "rent",
            "property_type": "apartment",
            "preferences_json": {
                "country_code": "AT",
                "region_code": "vienna",
                "location_query": f"10{index + 10} Vienna",
                "listing_mode": "rent",
            },
        }
        for index in range(7)
    ]
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1010 Vienna",
            "search_agents": agents,
        },
    )
    assert stored.status_code == 200, stored.text

    map_preview_calls: list[tuple[str, str, str]] = []

    def _map_scope_preview(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
        map_preview_calls.append((country_code, region_code, location_query))
        return {
            "image_url": f"/app/api/property/map-previews/{len(map_preview_calls):040d}.png",
            "summary": location_query,
            "preview_kind": "osm_district_overlay",
            "has_district_overlay": True,
        }

    monkeypatch.setattr(landing_view_models, "_property_scope_preview_map_only", _map_scope_preview)

    page = client.get("/app/agents", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna watch 6" in page.text
    assert len(map_preview_calls) == 7
    assert 'data-scope-preview-kind="deferred_map"' not in page.text
    assert "/app/api/property/map-previews/0000000000000000000000000000000000000000.png" not in page.text
    assert page.text.count('class="pqx-automation-thumbnail"') >= 7


def test_property_search_agent_builder_renders_all_scope_previews() -> None:
    calls: list[str] = []

    def _preview_builder(country_code: str, region_code: str, location_query: str) -> dict[str, object]:
        calls.append(location_query)
        return {
            "image_url": f"/app/api/property/map-previews/{len(calls):040d}.png",
            "preview_kind": "osm_district_overlay",
            "summary": location_query,
        }

    agents, _selected = landing_property_saved_searches.build_property_search_agents(
        {
            "search_agents": [
                {
                    "agent_id": f"agent-{index}",
                    "name": f"Watch {index}",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": f"10{index + 10} Vienna",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": f"10{index + 10} Vienna",
                    },
                }
                for index in range(3)
            ]
        },
        selected_platforms=["willhaben"],
        selected_listing_mode="rent",
        search_mode_requested="strict",
        default_duration_days=30,
        default_notification_limit=3,
        default_notification_period="week",
        normalize_property_type_values=lambda value: [str(value or "apartment")],
        scope_preview_builder=_preview_builder,
    )

    assert calls == ["1010 Vienna", "1011 Vienna", "1012 Vienna"]
    assert agents[0]["scope_preview"]["preview_kind"] == "osm_district_overlay"
    assert agents[1]["scope_preview"]["preview_kind"] == "osm_district_overlay"
    assert agents[2]["scope_preview"]["image_url"] == "/app/api/property/map-previews/0000000000000000000000000000000000000003.png"


def test_property_agents_surface_strips_candidate_media_from_management_payload(monkeypatch) -> None:
    principal_id = "pq-agent-strip-result-media"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Media Boundary")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                    },
                }
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "completed",
            "summary": {
                "status": "completed",
                "sources_total": 1,
                "listing_total": 1,
                "ranked_candidates": [
                    {
                        "candidate_ref": "media-heavy",
                        "title": "Media heavy result",
                        "fit_score": 91,
                        "preview_image_url": "data:image/png;base64,very-heavy-preview",
                        "orientation_preview": {
                            "image_url": "data:image/png;base64,very-heavy-orientation",
                            "thumb_image_url": "data:image/png;base64,very-heavy-thumb",
                        },
                        "property_facts": {"postal_name": "1020 Wien"},
                    }
                ],
                "sources": [
                    {
                        "source_label": "Willhaben",
                        "top_candidates": [
                            {
                                "candidate_ref": "source-media-heavy",
                                "preview_image_url": "data:image/png;base64,source-preview",
                            }
                        ],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    page = client.get("/app/agents", params={"run_id": "run-media-heavy"}, headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna rent watch" in page.text
    assert "data:image/png;base64,very-heavy" not in page.text
    assert "data:image/png;base64,source-preview" not in page.text
    assert "Media heavy result" not in page.text


def test_static_property_surfaces_skip_full_fleet_digest_on_first_paint(monkeypatch) -> None:
    principal_id = "pq-agent-account-fast-first-paint"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Static Surface Fast")

    def _fail_channel_loop_pack(self, *args, **kwargs):
        raise AssertionError("static surface first paint must not block on full fleet digest generation")

    monkeypatch.setattr(ProductService, "channel_loop_pack", _fail_channel_loop_pack)

    agents = client.get("/app/agents", headers={"host": "propertyquarry.com"})
    account = client.get("/app/account#profile", headers={"host": "propertyquarry.com"})
    billing = client.get("/app/billing", headers={"host": "propertyquarry.com"})

    assert agents.status_code == 200
    assert account.status_code == 200
    assert billing.status_code == 200
    assert "Billing" in billing.text


def test_property_fleet_digest_uses_short_cache_for_repeated_surface_loads(monkeypatch) -> None:
    from app.product import service as product_service_module

    principal_id = "pq-fleet-digest-cache"
    client = build_property_client(principal_id=principal_id)
    product = build_product_service(client.app.state.container)
    calls = {"count": 0}
    product_service_module._PROPERTY_FLEET_DIGEST_CACHE.clear()

    def fake_status_report(**kwargs):
        calls["count"] += 1
        return {
            "onemin_billing_aggregate": {"actual_remaining_credits_total": 250_000_000},
            "lane_telemetry": {"active_lanes": 2},
        }

    monkeypatch.setattr(product_service_module.responses_upstream, "codex_status_report", fake_status_report)

    first = product._fleet_digest_payload(principal_id=principal_id)
    second = product._fleet_digest_payload(principal_id=principal_id)
    first["stats"]["visible_credits"] = 1

    assert calls["count"] == 1
    assert second["stats"]["visible_credits"] == 250_000_000


def test_property_search_agents_can_open_focused_cockpit_view(monkeypatch) -> None:
    principal_id = "pq-agent-focus"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Search Agent Focus")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1020 Vienna",
            "active_search_agent_id": "agent-vienna",
            "search_agents": [
                {
                    "agent_id": "agent-vienna",
                    "name": "Vienna rent watch",
                    "enabled": True,
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                    "property_type": "apartment",
                    "notification_limit": 5,
                    "notification_period": "day",
                    "sent_in_current_window": 2,
                    "last_run_at": "2026-06-13T09:00:00+00:00",
                    "next_run_at": "2026-06-14T09:00:00+00:00",
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                    },
                },
            ],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-agent-1",
                "principal_id": principal_id,
                "active_search_agent_id": "agent-vienna",
                "status": "completed",
                "updated_at": "2026-06-13T09:10:00+00:00",
                "property_search_preferences": {
                    "active_search_agent_id": "agent-vienna",
                    "country_code": "AT",
                    "region_code": "vienna",
                    "location_query": "1020 Vienna",
                    "listing_mode": "rent",
                },
                "summary": {
                    "sources_total": 7,
                    "listing_total": 24,
                    "notified_total": 2,
                    "top_fit_score": 71,
                    "filtered_floorplan_total": 5,
                    "filtered_area_total": 3,
                    "ranked_candidates": [
                        {
                            "title": "Courtyard flat",
                            "source_label": "Willhaben",
                            "fit_score": 71,
                            "packet_url": "/app/research/agent-candidate?run_id=run-agent-1",
                        }
                    ],
                },
            }
        ]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    page = client.get("/app/agents?agent_id=agent-vienna", headers={"host": "propertyquarry.com"})

    assert page.status_code == 200
    assert "Vienna rent watch" in page.text
    assert "Ranked 1 | Sent 2 | Filtered 8" not in page.text
    assert "run-agent-1" not in page.text
    assert "No finished run yet" in page.text
    assert "/app/search?load_agent=" in page.text


def test_property_workspace_setup_is_dashboard_first_and_compact() -> None:
    template_path = Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html"
    body = template_path.read_text(encoding="utf-8")
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "Open the right surface for the next decision." in body
    assert "data-pqx-previous-searches" in body
    assert 'class="pqx-previous-open-link"' in body
    assert 'data-pqx-delete-run="' in body
    assert "data-pqx-dashboard-summary" in body
    assert "Automation" in body
    assert "Start" in body
    assert "Recent decisions and reviews" in body
    assert "pqx-previous-scope-caption" in body
    assert "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);" in body
    assert "display: flex;" in body
    assert "<legend>Search flow</legend>" in body
    assert ".pqx-disclosure-summary {" in body
    assert ".pqx-disclosure-icon {" in body
    assert ".pqx-workflow-step:hover," in body


def test_property_shortlist_surface_is_single_column_and_results_first() -> None:
    body = _read_workbench_bundle()

    assert "pqx-result-panel active" in body
    assert "pqx-results-filter-link" in body
    assert "Open property" in body
    assert "Open listing" in body
    assert "Request walkthrough" in body
    assert "Video processing" not in body
    assert 'data-pw-decision-state="archived"' in body
    assert "data-pw-remove-row" in body
    assert "No price published" in body
    assert 'data-candidate-listing-url="${escapeHtml(propertyUrl)}"' in body
    assert "const openRowTarget = () => {" in body
    assert "window.location.href = packetUrl;" in body
    assert "window.open(listingUrl, '_blank', 'noopener,noreferrer');" in body
    assert "event.key !== 'Enter' && event.key !== ' '" in body
    assert 'aria-label="Account navigation"' in body
    assert ">Me<" not in body
    assert "Tell us what to find." not in body


def test_property_workspace_previous_search_delete_uses_real_api_endpoint() -> None:
    body = _read_workbench_bundle()
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "data-pqx-delete-run" in body
    assert "Delete this previous search from the dashboard?" in body
    assert "method: 'DELETE'" in body
    assert "/app/api/property/search-runs/" in body
    assert "_property_scope_preview" in view_model
    assert "scope_preview" in view_model


def test_property_finished_search_results_prioritize_main_list_and_filtered_disclosure() -> None:
    body = _read_workbench_bundle()

    assert "data-pqx-filtered-open" in body
    assert 'href="#pqx-filtered-breakdown"' in body
    assert '<a class="pqx-results-summary-link pqx-results-filter-link" href="#pqx-filtered-breakdown" data-pqx-filtered-open' in body
    assert '<button class="pqx-results-summary-link pqx-results-filter-link" type="button" data-pqx-filtered-open' not in body
    assert "pqx-results-filter-link" in body
    assert "filtered" in body
    assert "Relax one hard rule" in body
    assert "Adjust filters" not in body.split("data-pqx-filtered-open", 1)[1].split("</section>", 1)[0]
    assert "const filteredDialogHasActions = () => Boolean(filteredDialog?.querySelector('.pqx-filtered-dialog-rule'));" in body
    assert "const openFilteredDialog = () => {" in body
    assert "Relax one rule" in body
    assert "estimated newly ranked homes after rerun" in body
    assert "data-pqx-filter-slider" in body
    assert "data-pqx-filter-field" in body
    assert "adjustments[fieldName]" in body
    assert "document.addEventListener('click', handleFilteredOpenClick);" in body
    assert "No ranked homes are ready yet. Relax one hard rule and rerun." in body
    assert "Best homes first" not in body


def test_property_live_run_has_no_manual_refresh_controls() -> None:
    body = _read_workbench_bundle()
    running_panel = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/_property_running_panel.html").read_text(encoding="utf-8")

    assert "data-pqx-refresh-status" not in body
    assert "data-pqx-refresh-status" not in running_panel
    assert "Refresh status" not in body
    assert ">Refresh<" not in running_panel
    assert "Refresh the provider step" not in body
    assert "Stop this live search?" in running_panel
    assert "Stop and remove" not in running_panel
    assert "Refreshing this page will continue to show the completed result desk" not in body
    assert "Refreshing this page will continue to show the completed result desk" not in running_panel


def test_property_live_ranked_candidates_filter_repair_and_false_positive_rows() -> None:
    body = _read_workbench_bundle()
    view_model = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    payload_builder = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_property_workspace_payload.py").read_text(encoding="utf-8")
    helper = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_property_workspace_helpers.py").read_text(encoding="utf-8")

    assert "const isRankableCandidate = (candidate) => {" in body
    assert "candidate.maybe_false || candidate.maybe_false_positive || candidate.false_positive || candidate.flagged_for_repair" in body
    assert "String(candidate.hard_filter_reason || '').trim()" in body
    assert "hardFilterReasons.has(filterReason)" in body
    assert "String(candidate.hard_filter_reason || candidate.filter_reason || '').trim()" not in body
    assert "topCandidates.forEach((candidate) => {" in body
    assert "if (!isRankableCandidate(candidate)) return;" in body
    assert "Number(right?.ranking_score || right?.investment_score || right?.fit_score || 0)" in body
    assert "filter_reason in hard_filter_reasons" in helper
    assert 'candidate.get("hard_filter_reason") or candidate.get("filter_reason")' not in helper
    assert "filter_reason in hard_filter_reasons" in view_model
    assert 'candidate.get("hard_filter_reason") or candidate.get("filter_reason")' not in view_model
    assert "_property_candidate_is_rankable(candidate_row)" in view_model
    assert "_property_candidate_is_rankable(candidate)" in payload_builder


def test_property_decision_save_uses_canonical_endpoint_and_renders_consequences() -> None:
    body = _read_workbench_bundle()

    assert "propertyDecisionSaveEndpoint = () => '/app/api/property/decisions'" in body
    assert "renderSavedDecisionConsequences(body)" in body
    assert "agent_question_tasks" in body
    assert "document_intake" in body
    assert "suppression_explanation" in body
    assert "Saved durably" in body
    assert "propertyFeedbackSaveEndpoint" not in body


def test_property_workspace_running_state_explains_slow_provider_checks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "ea/app/templates/app/property_decision_workbench.html"
    running_partial = repo_root / "ea/app/templates/app/_property_running_panel.html"
    script_partial = repo_root / "ea/app/templates/app/_property_workbench_script.html"
    body = template_path.read_text(encoding="utf-8")
    running_body = running_partial.read_text(encoding="utf-8")
    script_body = script_partial.read_text(encoding="utf-8")

    assert "estimateRunEtaLabel" in script_body
    assert "formatEta" in script_body
    assert "data-pqx-progress-eta" in body
    assert "data-pqx-running-provider-state" not in body
    run_visible_branch = body.split("{% elif run_visible %}", 1)[1].split("{% elif run_terminal_no_results %}", 1)[0]
    assert '{% include "app/_property_running_panel.html" %}' in run_visible_branch
    assert '{% include "app/_property_workbench_script.html" %}' in body
    assert running_body.count("{{ progress_board(run, run_sources, research_task_counts) }}") == 1
    assert 'data-pqx-running-details' in running_body
    assert "source lanes" not in body
    assert "0 lanes in progress" not in body
    assert "lanes in progress" not in body


def test_propertyquarry_user_facing_copy_avoids_hosted_review_jargon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    checked_paths = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/propertyquarry_home.html",
        repo_root / "ea/app/templates/pricing_page.html",
        repo_root / "ea/app/api/routes/landing.py",
        repo_root / "ea/app/api/routes/landing_view_models.py",
        repo_root / "ea/app/services/registration_email.py",
    ]

    for path in checked_paths:
        body = path.read_text(encoding="utf-8")
        assert "Hosted review" not in body, str(path)
        assert "hosted-review" not in body, str(path)


def test_propertyquarry_customer_surfaces_avoid_operator_jargon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    checked_paths = [
        repo_root / "ea/app/templates/app/property_decision_workbench.html",
        repo_root / "ea/app/templates/app/_property_account_panel.html",
        repo_root / "ea/app/templates/app/_property_selected_review_panel.html",
        repo_root / "ea/app/templates/app/object_detail.html",
        repo_root / "ea/app/api/routes/landing.py",
        repo_root / "ea/app/api/routes/landing_view_models.py",
        repo_root / "ea/app/api/routes/landing_objects.py",
        repo_root / "ea/app/api/routes/landing_property_workspace_helpers.py",
        repo_root / "ea/app/product/service.py",
    ]
    forbidden = (
        "Artifact receipts",
        "Delivery proof",
        "NeuronWriter editorial pass",
        "Telegram links",
        "Generated asset receipts",
        "access-session receipts",
        "repair receipts will appear",
        "Missing-fact OODA queued.",
        "Open the packet to inspect OODA.",
        "account truth",
        "checkout truth",
        "settings noise",
        "Layout proof rule",
        "Run one discovery pass without layout proof",
        "Recover layout proof for held-back homes",
        "Workers checking",
        "This property needs more proof before it can move from maybe to pursue.",
        "reconnect the tour worker",
        "recurring-cost proof visible",
        "Writing quality check",
        "Visible proof",
        "Run proof",
        "Repair proof",
        "Manual proof",
        "Next proof",
        "workers active",
        "active worker",
        "provider scan",
        "more scans",
        "Search progress details",
        '"OODA"',
        ">OODA<",
    )

    for path in checked_paths:
        body = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in body, f"{phrase!r} leaked in {path}"


def test_propertyquarry_dark_mode_covers_nested_search_controls() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    body = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    dark_block = body.split('html[data-pq-theme="dark"] .pqx-loaded-agent', 1)[1].split(
        "html[data-pq-theme=\"dark\"] .pqx-workflow-step:hover", 1
    )[0]

    required_selectors = (
        ".pqx-what-matters-head",
        ".pqx-what-matters-chip",
        ".pqx-what-matters-panel .pqx-choice-groupbox",
        ".pqx-what-matters-panel .pqx-pref-row",
        ".pqx-what-matters-panel .pqx-pref-row[data-preference-state]",
        ".pqx-what-matters-panel .pqx-school-priority-row[data-school-family-active=\"true\"]",
        ".pqx-what-matters-panel .pqx-school-priority-row[data-school-parent-active=\"true\"]",
        ".pqx-what-matters-panel .pqx-choice-groupbox[data-active-distance-rows=\"true\"]",
        ".pqx-choice-groupbox",
        ".pqx-automation-kpis span",
        ".pqx-automation-history-link",
        ".pqx-workflow-step",
        ".pqx-billing-metric",
        ".pqx-billing-note-rail",
        ".pqx-ooda-item",
        ".pqx-event-card",
        ".pqx-card",
        ".pqx-reading-card",
        ".pqx-source-card",
        ".pqx-route-preview-card",
        ".pqx-result",
        ".pqx-result.is-top-ranked",
        ".pqx-result-panel",
        ".pqx-result-fact",
        ".pqx-result-fit-score",
        ".pqx-result-open",
        ".pqx-progress-button",
        ".pqx-progress-board",
        ".pqx-progress-meter",
        ".pqx-pulse-line",
        ".pqx-results-summary-link",
        ".pqx-empty",
        ".pqx-results-empty-state",
        ".pqx-bottom-nav",
    )

    for selector in required_selectors:
        assert selector in dark_block


def test_property_delivery_rows_are_customer_outcomes_not_provider_receipts() -> None:
    rows = landing_property_workspace_helpers._delivery_proof_rows(
        {
            "dossier_writer_neuronwriter_status": "ready",
            "packet_created_total": 2,
            "tour_created_total": 1,
            "telegram_sent_total": 3,
        }
    )
    text = " ".join(
        " ".join(str(row.get(key) or "") for key in ("title", "detail", "tag"))
        for row in rows
    )

    assert "Writing status: ready" in text
    assert "Messages use titled links instead of long raw URLs." in text
    assert "2 review pages, 1 tour, 3 sent updates." in text
    assert "NeuronWriter" not in text
    assert "Telegram notification receipts" not in text
    assert "packet receipts" not in text
    assert "tour receipts" not in text


def test_property_artifact_rows_are_readiness_copy_not_receipt_jargon() -> None:
    rows = landing_property_workspace_helpers._artifact_receipt_rows(
        {
            "tour_created_total": 1,
            "flythrough_rendered_total": 2,
            "telegram_sent_total": 3,
            "repair_receipts": [{"resolution": "completed_partial"}],
        }
    )
    text = " ".join(
        " ".join(str(row.get(key) or "") for key in ("title", "detail", "tag"))
        for row in rows
    )

    assert "Dossier PDF" in text
    assert "PDF output must be readable, clean, and free of internal status text." in text
    assert "Real tour links can be shown when available; fake cube viewers stay hidden." in text
    assert "Walkthrough videos stay request-only and must pass visual quality checks before delivery." in text
    assert "1 3D tour, 2 walkthrough videos, 3 sent updates." in text
    assert "Repair outcome" in text
    assert "1 repair attempt recorded." in text
    assert "MarkupGo" not in text
    assert "Playwright render receipt" not in text
    assert "export receipts" not in text
    assert "Telegram delivery" not in text
    assert "Telegram sends" not in text
    assert "receipts" not in text.lower()


def test_propertyquarry_project_shape_docs_define_flagship_loop_and_design_gate() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_map = repo_root / "docs/PROPERTYQUARRY_SOURCE_OF_TRUTH_MAP.md"
    tone_guide = repo_root / "docs/PROPERTYQUARRY_TONE_GUIDE.md"
    dossier_art = repo_root / "docs/PREMIUM_DOSSIER_ART_DIRECTION.md"
    design_gate = repo_root / "docs/PROPERTYQUARRY_DESIGN_SYSTEM_GATE.md"
    retention = repo_root / "docs/PROPERTYQUARRY_DATA_RETENTION.md"
    analytics = repo_root / "docs/PROPERTYQUARRY_ANALYTICS_TAXONOMY.md"
    provider_quality = repo_root / "docs/PROPERTYQUARRY_PROVIDER_QUALITY.md"
    failure_ux = repo_root / "docs/PROPERTYQUARRY_FAILURE_UX.md"
    for path in (source_map, tone_guide, dossier_art, design_gate, retention, analytics, provider_quality, failure_ux):
        assert path.exists(), str(path)
        assert path.read_text(encoding="utf-8").strip(), str(path)

    source_body = source_map.read_text(encoding="utf-8")
    assert "Brief -> Search -> Compare -> Dossier -> Tour -> Decide -> Explain why -> Learn" in source_body
    assert "property_decision_ledger" in source_body
    assert "property_evidence_graph" in source_body
    assert "NeuronWriter" in source_body
    assert "private owner/family/agent packets by default" in source_body

    tone_body = tone_guide.read_text(encoding="utf-8")
    assert "raw URLs in message text" in tone_body
    assert "OODA summary" in tone_body
    assert "Decision summary" in tone_body

    dossier_body = dossier_art.read_text(encoding="utf-8")
    assert "cover image or poster visible on page one" in dossier_body
    assert "no artifact status tables" in dossier_body

    design_body = design_gate.read_text(encoding="utf-8")
    assert "no plaintext URLs in Telegram or email body text" in design_body
    assert "show suppressed-candidate summaries" in design_body

    registry_body = (repo_root / "docs/PROPERTYQUARRY_SURFACE_REGISTRY.md").read_text(encoding="utf-8")
    registry_source = (repo_root / "ea/app/product/property_surface_registry.py").read_text(encoding="utf-8")
    assert "/workspace-access/:token" in registry_body
    assert "/workspace-invites/:token" in registry_body
    assert "/workspace-access/:token" in registry_source
    assert "/workspace-invites/:token" in registry_source
    assert "/workspace-link" not in registry_body
    assert '"/workspace-link"' not in registry_source

    retention_body = retention.read_text(encoding="utf-8")
    assert "private PDFs and signed packet links must be revocable" in retention_body
    assert "raw household feedback is owner-private by default" in retention_body
    assert "Data-Class Matrix" in retention_body
    assert "Search runs" in retention_body
    assert "Source listing cache" in retention_body
    assert "Canonical property passport" in retention_body
    assert "Public packets and tours" in retention_body
    assert "External investment data" in retention_body
    assert "Revocation must remove customer access and make stale artifacts undiscoverable" in retention_body
    assert "workspace defaults" not in retention_body
    assert "workspace links" not in retention_body

    analytics_body = analytics.read_text(encoding="utf-8")
    assert "pq.search.started" in analytics_body
    assert "pq.decision.saved" in analytics_body
    assert "signed link token" in analytics_body

    provider_quality_body = provider_quality.read_text(encoding="utf-8")
    assert "floorplan_reliability" in provider_quality_body
    assert "filter_pushdown_strength" in provider_quality_body
    assert "last_verified" in provider_quality_body

    failure_body = failure_ux.read_text(encoding="utf-8")
    assert "human message" in failure_body
    assert "operator detail" in failure_body
    assert "fallback action" in failure_body


def test_propertyquarry_in_progress_run_hides_search_form_and_shows_live_run(monkeypatch) -> None:
    principal_id = "pq-live-run-focus"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Run Focus")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "full_region_scope": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben", "genossenschaften_at"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "progress": 42,
            "message": "Scoring enriched candidate 2 of 4 for Willhaben | Austria | Buy | Wien.",
            "summary": {
                "sources_total": 4,
                "listing_total": 6,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "eta_label": "about 6 min",
                "sources": [],
            },
            "events": [
                {"step": "source_assessing", "message": "Scoring enriched candidate 2 of 4 for Willhaben | Austria | Buy | Wien.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    live = client.get("/app/properties", params={"run_id": "run-live"}, headers=headers)
    assert live.status_code == 200
    assert 'data-property-spa-shell' in live.text
    assert 'data-property-decision-workbench' in live.text
    assert 'data-pq-greenfield-shell' in live.text
    assert 'data-pqx-state="running"' in live.text
    assert 'class="pqx-run-head"' not in live.text
    assert live.text.count('class="pqx-progress-board"') == 1
    assert 'data-pqx-run-summary' in live.text
    assert "Search in progress" in live.text
    assert 'data-pqx-progress-board' in live.text
    assert 'data-pqx-progress-eta' in live.text
    assert "42% · about 6 min" in live.text
    assert 'class="pqx-source-progress"' in live.text
    assert 'class="pqx-source-list"' in live.text
    assert 'class="pqx-route-preview-strip"' in live.text
    assert "Scoring enriched candidate 2 of 4" in live.text
    assert re.search(r"<button[^>]+data-property-start-top[^>]*>\\s*Launch search\\s*</button>", live.text) is None
    assert ">Save defaults</button>" not in live.text
    assert "Test a wider budget ceiling" not in live.text


def test_propertyquarry_properties_auto_opens_latest_active_run_when_run_id_missing(monkeypatch) -> None:
    principal_id = "pq-live-run-auto-open"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Auto Open")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_list_runs(self, *, principal_id: str, limit: int = 8, hydrate: bool = True):
        assert principal_id == "pq-live-run-auto-open"
        assert hydrate is False
        return [
            {"run_id": "run-active-42", "status": "in_progress", "summary": {"status": "in_progress"}},
            {"run_id": "run-finished-1", "status": "processed", "summary": {"status": "processed"}},
        ]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-live-run-auto-open"
        assert run_id == "run-active-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "in_progress",
            "progress": 18,
            "message": "Checking fresh rental listings for Vienna.",
            "summary": {
                "status": "in_progress",
                "sources_total": 3,
                "listing_total": 7,
                "eta_label": "about 4 min",
                "sources": [],
            },
            "events": [
                {"step": "source_fetch", "message": "Checking fresh rental listings for Vienna.", "status": "in_progress"},
            ],
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_list_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    live = client.get("/app/properties", headers=headers)
    assert live.status_code == 200
    assert "Search in progress" in live.text
    assert "Checking fresh rental listings for Vienna." in live.text
    assert "Open a saved search or launch a new brief" not in live.text
    assert "run-active-42" in live.text


def test_propertyquarry_empty_outcome_rows_fallback_when_values_are_blank(monkeypatch) -> None:
    principal_id = "pq-empty-outcome-fallback"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Empty Outcome Fallback")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-empty-outcome-fallback"
        assert run_id == "run-empty-outcome"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "",
            "summary": {
                "status": "failed",
                "sources_total": 0,
                "listing_total": 0,
                "ranked_candidates": [],
                "sources": [],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(
        landing_property_workspace_payload,
        "build_property_empty_outcome_summary",
        lambda **kwargs: {
            "happened": "   ",
            "still_worked": " ",
            "active_rule": "\n",
            "next_move": "\t",
        },
    )

    response = client.get("/app/properties", params={"run_id": "run-empty-outcome"}, headers=headers)

    assert response.status_code == 200
    assert "Status" in response.text
    assert "<strong>Update</strong>" in response.text
    assert "The search stopped before a stable shortlist was ready." in response.text
    assert "Next" in response.text
    assert "Restart the same brief and let repair retry the interrupted search." in response.text
    assert "What happened" not in response.text
    assert "What still worked" not in response.text
    assert "Main blocker" not in response.text
    assert "Best next move" not in response.text


def test_propertyquarry_empty_completed_run_uses_premium_no_match_copy() -> None:
    body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html").read_text(
        encoding="utf-8"
    )

    assert "No strong matches found yet." in body
    assert "No shortlist yet." not in body


def test_propertyquarry_provider_fact_never_uses_source_variant_count(monkeypatch) -> None:
    principal_id = "pq-provider-count-regression"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Provider Count Regression")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben", "derstandard_at", "kalandra"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-provider-count-regression"
        assert run_id == "run-variant-heavy"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "The search stopped before a stable shortlist was ready.",
            "summary": {
                "status": "failed",
                "sources_total": 156,
                "source_variant_total": 156,
                "provider_total": 1,
                "sources_completed": 153,
                "listing_total": 2160,
                "filtered_total": 24,
                "ranked_candidates": [],
                "eta_label": "about 8 hr",
                "repair_status_label": "Repairing",
                "repair_step_label": "Repairing interrupted run.",
                "sources": [],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", params={"run_id": "run-variant-heavy"}, headers=headers)

    assert response.status_code == 200
    assert re.search(r"<span>Providers</span><strong>\s*3\s*</strong>", response.text)
    assert re.search(r"<span>Listings</span><strong>\s*2160\s*</strong>", response.text)
    assert "<span>Providers</span><strong>156</strong>" not in response.text
    assert "<span>Source checks</span>" not in response.text
    assert "The selected sources covered 2160 listings." in response.text
    assert "Source variants" not in response.text
    assert "Status" in response.text
    assert "Timing" not in response.text
    assert "Repairing interrupted run." in response.text
    assert response.text.count("Why homes stayed out") == 1
    assert "Provider-level details" not in response.text
    assert "Filtering diagnostics" not in response.text
    assert "Filtered by rules: Filtering diagnostics" not in response.text


def test_propertyquarry_live_progress_derives_provider_count_before_source_variants() -> None:
    script = _read_workbench_bundle()

    assert "const providerDisplayTotalForRun = (runPayload, summary = null) =>" in script
    assert "Array.isArray(runPayload?.brief?.providers)" in script
    assert "Array.isArray(data?.brief?.providers)" in script
    assert "const rawProviderSourceKey" in script
    assert "sourceProviders.add(identity);" in script
    assert "const providerDisplayTotal = providerDisplayTotalForRun(runPayload, summary);" in script
    assert "const providerTotal = Number(summary.provider_total || 0);" not in script
    assert "const selectedProviderTotal = Array.isArray(runPayload?.selected_platforms) ? runPayload.selected_platforms.length : 0;" not in script
    assert "progress || 12" not in script
    assert "statusLabel === 'Starting' ? Math.max(3, Math.min(progress || 3, 6))" in script


def test_propertyquarry_console_shell_render_run_uses_provider_display_total() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    console_shell = (repo_root / "ea/app/templates/console_shell.html").read_text(encoding="utf-8")

    assert "const providerDisplayTotalForRun = (payload, summary = null) =>" in console_shell
    assert "const providers = providerDisplayTotalForRun(payload, summary);" in console_shell
    assert "const providerTotal = Number(summary.provider_total || 0);" not in console_shell
    assert "const sourceVariantTotal = Math.max(0, Number(runSummary.source_variant_total || runSummary.sources_total || 0));" in console_shell


def test_propertyquarry_run_hero_never_exposes_source_variant_count_as_search_scope() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    payload_builder = (repo_root / "ea/app/api/routes/landing_property_workspace_payload.py").read_text(encoding="utf-8")

    assert '"label": "Search scope"' in payload_builder
    assert '"value": "Selected"' in payload_builder
    assert '"detail": "Checking the saved brief."' in payload_builder
    assert '"value": str(run_source_variant_total)' not in payload_builder
    assert '"Selected sources are checking the saved brief."' not in payload_builder


def test_propertyquarry_raw_ranked_fallback_excludes_maybe_false_candidates(monkeypatch) -> None:
    principal_id = "pq-raw-ranked-rankable"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Raw Ranked Rankable")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-raw-ranked-rankable"
        assert run_id == "run-raw-ranked"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "Search interrupted after repair queued a partial shortlist.",
            "summary": {
                "status": "failed",
                "sources_total": 2,
                "listing_total": 2,
                "ranked_candidates": [
                    {
                        "candidate_ref": "good-1",
                        "title": "Real shortlist survivor",
                        "fit_score": 72,
                        "property_url": "https://example.test/good",
                        "property_facts": {"postal_name": "1010 Wien", "price_display": "EUR 1,200"},
                    },
                    {
                        "candidate_ref": "bad-1",
                        "title": "Maybe false candidate",
                        "fit_score": 95,
                        "maybe_false": True,
                        "status": "maybe_false",
                        "property_url": "https://example.test/bad",
                        "property_facts": {"postal_name": "Salzburg", "price_display": "EUR 1,000"},
                    },
                ],
                "sources": [],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", params={"run_id": "run-raw-ranked"}, headers=headers)

    assert response.status_code == 200
    assert "Real shortlist survivor" in response.text
    assert "Maybe false candidate" not in response.text


def test_propertyquarry_properties_route_redirects_terminal_partial_run_to_shortlist(monkeypatch) -> None:
    principal_id = "pq-terminal-partial-shortlist"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Terminal Partial Redirect")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-terminal-partial-shortlist"
        assert run_id == "run-partial-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "completed_partial",
            "progress": 100,
            "message": "Search interrupted after more than 20 minutes without updates. The current shortlist is still available.",
            "summary": {
                "status": "completed_partial",
                "sources_total": 4,
                "listing_total": 18,
                "filtered_total": 2,
                "held_back_total": 2,
                "ranked_candidates": [
                    {"candidate_ref": "cand-1", "title": "Candidate One"},
                ],
                "sources": [],
            },
            "events": [
                {"step": "run_interrupted", "message": "Search interrupted after more than 20 minutes without updates.", "status": "completed_partial"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get(
        "/app/properties",
        params={"run_id": "run-partial-42"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/app/shortlist?run_id=run-partial-42"


def test_propertyquarry_suppression_rows_use_summary_fallback_and_show_active_rule() -> None:
    rows = landing_property_workspace_helpers._property_suppression_rows(
        run_summary={
            "filtered_low_fit_total": 9,
            "filtered_area_total": 4,
            "filtered_location_total": 3,
        },
        source_rows=[],
        preferences={
            "min_match_score": 82,
            "min_area_m2": 70,
            "adjacent_area_radius_m": 500,
            "location_query": "Vienna",
        },
        include_soft=True,
    )
    low_fit_row = next(row for row in rows if row.get("rule_key") == "Below fit threshold")
    assert "Current match bar: 82." in str(low_fit_row.get("detail") or "")
    location_row = next(row for row in rows if row.get("rule_key") == "Outside selected area")
    assert "Vienna" in str(location_row.get("detail") or "")
    assert "500 m spillover" in str(location_row.get("detail") or "")


def test_propertyquarry_suppression_rows_treats_low_fit_as_soft_by_default() -> None:
    rows = landing_property_workspace_helpers._property_suppression_rows(
        run_summary={
            "filtered_low_fit_total": 9,
            "filtered_area_total": 4,
            "filtered_location_total": 3,
        },
        source_rows=[],
        preferences={
            "min_match_score": 82,
            "min_area_m2": 70,
            "adjacent_area_radius_m": 500,
            "location_query": "Vienna",
        },
    )
    assert not any((row.get("rule_key") or "") == "Below fit threshold" for row in rows)


def test_propertyquarry_suppression_rows_includes_property_type_and_availability_rules() -> None:
    rows = landing_property_workspace_helpers._property_suppression_rows(
        run_summary={
            "filtered_property_type_total": 3,
            "filtered_availability_total": 1,
            "filtered_listing_mode_total": 2,
            "filtered_generic_page_total": 1,
            "filtered_area_total": 0,
            "filtered_floorplan_total": 0,
            "filtered_low_fit_total": 0,
            "notification_budget_suppressed_total": 0,
        },
        source_rows=[
            {"source_label": "Willhaben Vienna", "filtered_property_type_total": 3},
            {"source_label": "Willhaben Vienna", "filtered_availability_total": 1},
            {"source_label": "DER STANDARD Vienna", "filtered_listing_mode_total": 2},
            {"source_label": "Genossenschaften Austria", "filtered_generic_page_total": 1},
        ],
        preferences={
            "available_within_years": 1,
            "location_query": "1010 Vienna",
        },
    )

    property_type_row = next(row for row in rows if row.get("rule_key") == "Property type mismatch")
    availability_row = next(row for row in rows if row.get("rule_key") == "Availability mismatch")
    listing_mode_row = next(row for row in rows if row.get("rule_key") == "Wrong transaction type")
    overview_row = next(row for row in rows if row.get("rule_key") == "Provider overview page")

    assert property_type_row["affected_total"] == 3
    assert availability_row["affected_total"] == 1
    assert listing_mode_row["affected_total"] == 2
    assert overview_row["affected_total"] == 1
    assert property_type_row["action_label"] == "Relax property type"
    assert availability_row["action_label"] == "Edit move-in timing"


def test_propertyquarry_shortlist_uses_run_search_goal_over_saved_defaults(monkeypatch) -> None:
    principal_id = "pq-run-goal-overrides-saved-defaults"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "investment",
            "investment_research_mode": "auto",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-run-goal-overrides-saved-defaults"
        assert run_id == "run-home-42"
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "property_search_preferences": {
                "country_code": "AT",
                "language_code": "de",
                "listing_mode": "buy",
                "search_goal": "home",
                "investment_research_mode": "off",
                "location_query": "Vienna",
                "selected_platforms": ["willhaben"],
            },
            "summary": {
                "status": "processed",
                "ranked_candidates": [
                    {
                        "title": "Vienna family flat",
                        "property_url": "https://example.test/vienna-family-flat",
                        "fit_summary": "Strong home fit near parks and daily errands.",
                        "match_reasons": ["Parks and daily errands stay close."],
                        "property_facts": {
                            "price_display": "EUR 520,000",
                            "rooms": 3,
                            "area_m2": 82,
                            "postal_name": "1020 Wien",
                        },
                    }
                ],
                "sources": [],
            },
            "events": [{"step": "completed", "message": "Property scouting run completed.", "status": "processed"}],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    shortlist = client.get("/app/shortlist", params={"run_id": "run-home-42"}, headers={"host": "propertyquarry.com"})
    assert shortlist.status_code == 200
    assert '"search_goal": "home"' in shortlist.text
    assert "Find a home" in shortlist.text
    assert "Why this ranks" not in shortlist.text
    assert "Open the investment read." not in shortlist.text


def test_propertyquarry_shortlist_excludes_saved_candidates_outside_active_run_area(monkeypatch) -> None:
    client = build_property_client(principal_id="pq-shortlist-hard-area")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "property_search_preferences": {
                "country_code": "AT",
                "listing_mode": "rent",
                "search_goal": "home",
                "location_query": "1010 Vienna",
                "selected_districts": ["1010 Vienna"],
            },
            "summary": {
                "status": "processed",
                "ranked_candidates": [
                    {
                        "title": "Vienna inner-district flat",
                        "property_url": "https://example.test/vienna-1010-flat",
                        "fit_summary": "Inside the selected district.",
                        "match_reasons": ["1010 Vienna"],
                        "property_facts": {
                            "rent_display": "EUR 1,250",
                            "postal_name": "1010 Wien",
                        },
                    }
                ],
                "sources": [],
            },
            "events": [{"step": "completed", "message": "Property scouting run completed.", "status": "processed"}],
        }

    def _fake_saved_shortlist_candidates(self, *, principal_id: str):
        return [
            {
                "title": "Schardenberg rental",
                "property_url": "https://example.test/schardenberg-rental",
                "fit_summary": "Saved from an older run.",
                "match_reasons": ["Older shortlist survivor"],
                "location_label": "4784 Schardenberg",
                "property_facts": {
                    "postal_name": "4784 Schardenberg",
                    "rent_display": "€ 524,60",
                },
            }
        ]

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_property_saved_shortlist_candidates", _fake_saved_shortlist_candidates)

    shortlist = client.get("/app/shortlist", params={"run_id": "run-area-42"}, headers={"host": "propertyquarry.com"})
    assert shortlist.status_code == 200
    assert "Vienna inner-district flat" in shortlist.text
    assert "Schardenberg rental" not in shortlist.text


def test_propertyquarry_shortlist_panel_builds_cards_and_actions() -> None:
    def _priority_reason(match_reasons: list[str], mismatch_reasons: list[str], fit_summary: str) -> str:
        if match_reasons:
            return match_reasons[0]
        if mismatch_reasons:
            return mismatch_reasons[0]
        return fit_summary

    rows, cards = landing_property_shortlist_panel.build_property_shortlist_panel(
        property_summary={
            "sources": [
                {
                    "source_label": "Willhaben",
                    "top_candidates": [
                        {
                            "title": "Vienna family flat",
                            "fit_summary": "Strong home fit near parks and daily errands.",
                            "match_reasons": ["Near parks"],
                            "mismatch_reasons": ["Needs a second bathroom"],
                            "recommendation": "shortlist",
                            "review_url": "https://example.test/review",
                            "tour_url": "https://example.test/360",
                            "property_url": "https://example.test/source",
                            "property_facts": {
                                "nearest_starbucks_m": 240,
                                "future_change_research": {
                                    "school_atlas_progression_summary": "Strong local AHS transition.",
                                    "school_atlas_evidence_type": "verified",
                                },
                            },
                            "feedback_rows": [{"label": "Daily life works"}],
                        }
                    ],
                }
            ]
        },
        property_preferences={},
        active_run_id="run-42",
        wants_run_views=True,
        clean_candidate_copy=landing_view_models._clean_property_candidate_copy,
        candidate_priority_reason=_priority_reason,
        property_candidate_ref=landing_view_models._property_candidate_ref,
    )

    assert len(rows) == 1
    assert len(cards) == 1
    assert rows[0]["action_label"] == "Open property page"
    assert rows[0]["secondary_action_label"] == "Open listing"
    assert rows[0]["tertiary_action_label"] == "Open 360"
    assert rows[0]["quaternary_action_label"] == "Source"
    assert cards[0]["packet_url"].endswith("?run_id=run-42")
    assert cards[0]["lifestyle_highlights"][0]["label"] == "Starbucks"
    assert cards[0]["research_highlights"][0]["label"] == "School transition"
    source_rows = landing_property_shortlist_panel.build_property_source_rows(
        property_summary={
            "sources": [
                {
                    "source_label": "Willhaben",
                    "listing_total": 12,
                    "high_fit_total": 3,
                    "filtered_floorplan_total": 2,
                    "tour_created_total": 1,
                    "notified_total": 1,
                    "email_notified_total": 1,
                    "top_fit_score": 87.5,
                }
            ]
        }
    )
    assert source_rows == [
        {
            "title": "Willhaben",
            "detail": "12 listings | 3 high-fit | 2 still waiting on floorplans | 1 hosted tours | 1 client alerts | 1 email | top score 87.50",
            "tag": "Scanned",
        }
    ]


def test_property_search_analysis_cap_defaults_to_top_k_slice(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_SEARCH_ANALYSIS_CAP_PER_SOURCE", raising=False)
    assert _property_search_analysis_cap_per_source(max_results=2, candidate_total=31) == 6
    assert _property_search_analysis_cap_per_source(max_results=5, candidate_total=31) == 12
    assert _property_search_analysis_cap_per_source(max_results=5, candidate_total=4) == 4


def test_property_search_analysis_cap_allows_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_ANALYSIS_CAP_PER_SOURCE", "9")
    assert _property_search_analysis_cap_per_source(max_results=2, candidate_total=31) == 9


def test_propertyquarry_running_progress_ring_stays_compact_and_top_aligned() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    run_hero = re.search(r"\.pqx-run-hero \{(?P<body>.*?)\n    \}", template, re.S)
    assert run_hero is not None
    assert ".pqx-run-head" in template
    assert "grid-template-columns: auto minmax(0, 1fr);" in template
    assert "width: clamp(86px, 10vw, 118px);" in template
    assert "width: 78px;" in template
    assert ".pqx-progress-board" in template
    assert "@keyframes pqxPulseSlide" in template
    assert "@keyframes pqxRouteTrace" in template
    assert "@keyframes pqxScanSweep" in template
    assert "@media (prefers-reduced-motion: reduce)" in template
    assert "align-content: space-between;" not in run_hero.group("body")
    assert 'data-pqx-screenfit-target="run-progress"' in template
    assert "width: min(260px, 58vw);" not in template


def test_propertyquarry_setup_intro_is_compact_and_allows_fact_text_to_wrap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    setup = re.search(r"\.pqx-setup \{(?P<body>.*?)\n    \}", template, re.S)
    setup_intro = re.search(r"\.pqx-setup-intro \{(?P<body>.*?)\n    \}", template, re.S)
    fact = re.search(r"\.pqx-fact \{(?P<body>.*?)\n    \}", template, re.S)
    fact_strong = re.search(r"\.pqx-fact strong \{(?P<body>.*?)\n    \}", template, re.S)

    assert setup is not None
    assert setup_intro is not None
    assert fact is not None
    assert fact_strong is not None
    assert "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);" in setup.group("body")
    assert "align-items: start;" in setup.group("body")
    assert "align-content: start;" in setup_intro.group("body")
    assert "padding: 18px 18px 14px;" in setup_intro.group("body")
    assert ".pqx-setup.pqx-surface-search" in template
    assert "min-height: 0;" in fact.group("body")
    assert "overflow-wrap: normal;" in fact_strong.group("body")
    assert "white-space: normal;" in fact_strong.group("body")
    assert "white-space: nowrap;" not in fact_strong.group("body")


def test_propertyquarry_workspace_supports_area_select_all_actions() -> None:
    principal_id = "pq-vienna-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Vienna Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "region_code": "vienna",
            "full_region_scope": True,
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text
    profile_node = client.post(
        "/app/api/people/self/preference-profile/nodes",
        json={
            "domain": "willhaben",
            "category": "soft_preference",
            "key": "prefer_outdoor_space",
            "value_json": True,
            "strength": "high",
            "confidence": 1.0,
        },
    )
    assert profile_node.status_code == 200, profile_node.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-workbench-brief-drawer' in search.text
    assert "<h2>Search profile</h2>" not in search.text
    assert 'data-property-search-utility="preferences"' not in search.text
    assert 'data-property-search-utility-strip' not in search.text
    assert "Saved preferences" not in search.text
    assert "Prefer Outdoor Space (Soft Preference)" not in search.text
    assert 'data-checkbox-group-select-all="location_query"' in search.text
    assert 'data-checkbox-group-clear-all="location_query"' in search.text
    assert 'name="full_region_scope" value="true" checked' in search.text


def test_propertyquarry_workspace_exposes_adjacent_area_radius_control() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    brief_script = (repo_root / "ea/app/templates/app/_property_workbench_brief_script.html").read_text(encoding="utf-8")
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert '"name": "adjacent_area_radius_value"' in view_models
    assert '"name": "adjacent_area_radius_unit"' in view_models
    assert 'data-range-unit-field="{{ field.get(\'unit_field\') or \'\' }}"' in template
    assert "adjacent_area_radius_m: adjacentAreaRadiusMeters" in brief_script


def test_propertyquarry_workspace_exposes_investment_goal_and_guardrails() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    view_models = (repo_root / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")
    brief_script = (repo_root / "ea/app/templates/app/_property_workbench_brief_script.html").read_text(encoding="utf-8")
    workbench_script = (repo_root / "ea/app/templates/app/_property_workbench_script.html").read_text(encoding="utf-8")

    assert '"name": "search_goal"' in view_models
    assert '"label": "What are you looking for?"' in view_models
    assert '"name": "investment_strategy"' in view_models
    assert '"name": "min_gross_yield_pct"' in view_models
    assert '"name": "equity_available_eur"' in view_models
    assert '"name": "loan_term_years"' in view_models
    assert '"name": "max_interest_rate_pct"' in view_models
    assert '"name": "min_dscr"' in view_models
    assert '"name": "vacancy_reserve_pct"' in view_models
    assert '"name": "capex_reserve_pct"' in view_models
    assert '"name": "investment_require_legal_clarity"' in view_models
    assert '"name": "investment_require_tenant_clarity"' in view_models
    assert '"name": "investment_avoid_major_renovation"' in view_models
    assert "Choose the thesis first." in view_models
    assert "Use this as a hard floor for expected gross yield" in view_models
    assert "debt coverage and cash-on-cash yield" in view_models
    assert "A DSCR floor lets you exclude deals" in view_models
    assert "search_goal: searchGoal" in brief_script
    assert "const investmentResearchEnabled = searchGoal === 'investment' && investmentResearchMode !== 'off';" in brief_script
    assert "investment_strategy: investmentResearchEnabled" in brief_script
    assert "min_dscr: investmentResearchEnabled" in brief_script
    assert "const searchGoalField = form.querySelector('select[name=\"search_goal\"]');" in workbench_script
    assert "{ label: 'What', detail: 'Property type, budget, size, and move-in guardrails.' }" in workbench_script
    assert "form.dataset.propertyExcludedSteps = 'children,reachability';" in workbench_script
    assert "form.dataset.propertyExcludedSteps = 'areas';" in workbench_script
    assert "const isSearchStep = !activeStep || activeStep === 'search' || activeStep === 'areas';" in workbench_script
    assert "const setConditionalWrapVisibility = (wrap, visible, reason" in workbench_script
    assert "setConditionalWrapVisibility(locationFieldWrap, isSearchStep && hasAreaOptions, 'area_scope');" in workbench_script
    assert "const resyncSearchFormState = () => {" in workbench_script
    assert "}).finally(resyncSearchFormState);" in workbench_script
    assert "const lifestyleDetailWraps = [" in workbench_script
    assert "input[name=\"enable_lifestyle_research\"]')?.addEventListener('change', syncSearchGoalControls);" in workbench_script
    assert "university_name: Boolean(form.querySelector('input[name=\"enable_lifestyle_research\"]')?.checked)" in brief_script
    assert "Home shape" not in workbench_script


def test_propertyquarry_workspace_surfaces_institutional_underwriting_language() -> None:
    bundle = _read_workbench_bundle()
    lowered = bundle.lower()
    assert "Institutional read" in bundle
    assert "institutional score" in lowered
    assert "return, value, demand, liquidity, risk control, execution effort, and evidence confidence" in lowered
    assert "External model" in bundle


def test_propertyquarry_saved_brief_reload_does_not_backfill_custom_location_from_checkbox_scope() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template = (repo_root / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")

    assert "setFieldValue('custom_location_query', payload.location_query)" not in template


def test_propertyquarry_workspace_hides_investment_research_for_rent() -> None:
    principal_id = "pq-rent-no-investment-filter"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Rent Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "investment_research_mode": "auto",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="investment_research_mode" hidden' in search.text


def test_propertyquarry_workspace_hides_investment_research_for_home_buy() -> None:
    principal_id = "pq-home-buy-no-investment-filter"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Buy Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "investment_research_mode": "auto",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="investment_research_mode" hidden' in search.text
    assert 'data-property-field-name="investment_strategy" hidden' in search.text


def test_propertyquarry_workspace_hides_underwriting_controls_when_investment_depth_is_off() -> None:
    principal_id = "pq-investment-depth-off"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Investment Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "investment",
            "investment_research_mode": "off",
            "investment_strategy": "cash_flow",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="investment_research_mode"' in search.text
    assert 'data-property-field-name="investment_strategy" hidden' in search.text
    assert 'data-property-field-name="min_gross_yield_pct" hidden' in search.text
    assert 'data-property-field-name="equity_available_eur" hidden' in search.text
    assert 'data-property-field-name="loan_term_years" hidden' in search.text
    assert 'data-property-field-name="max_interest_rate_pct" hidden' in search.text
    assert 'data-property-field-name="min_dscr" hidden' in search.text
    assert 'data-property-field-name="vacancy_reserve_pct" hidden' in search.text
    assert 'data-property-field-name="capex_reserve_pct" hidden' in search.text
    assert 'data-property-field-name="investment_require_floorplan" hidden' in search.text
    assert 'data-property-field-name="investment_require_legal_clarity" hidden' in search.text


def test_propertyquarry_workspace_hides_rent_only_controls_for_investment_search() -> None:
    principal_id = "pq-investment-no-rent-lapse"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Investment Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "investment",
            "investment_research_mode": "off",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_public_housing_signals": True,
            "wiener_wohnticket_available": True,
            "subsidized_required": True,
            "miete_mit_kaufoption": True,
            "eigenmittel_max_eur": 50000,
            "application_window_days": 14,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="listing_mode" hidden' in search.text
    assert 'data-property-field-name="include_public_housing_signals" hidden' in search.text
    assert 'data-property-field-name="wiener_wohnticket_available" hidden' in search.text


def test_propertyquarry_workspace_hides_dwelling_only_hard_gates_for_land_only_search() -> None:
    principal_id = "pq-land-only-hides-dwelling-gates"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Land Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "property_type": ["land"],
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "require_floorplan": True,
            "require_energy_certificate": True,
            "require_operating_cost_statement": True,
            "investment_require_floorplan": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="min_rooms" hidden' in search.text
    assert 'data-property-field-name="require_floorplan" hidden' in search.text
    assert 'data-property-field-name="require_energy_certificate" hidden' in search.text
    assert 'data-property-field-name="require_operating_cost_statement" hidden' in search.text
    assert 'data-property-field-name="subsidized_required" hidden' in search.text
    assert 'data-property-field-name="miete_mit_kaufoption" hidden' in search.text
    assert 'data-property-field-name="eigenmittel_max_eur" hidden' in search.text
    assert 'data-property-field-name="application_window_days" hidden' in search.text


def test_propertyquarry_workspace_hides_buy_only_provider_controls_for_rent_search() -> None:
    principal_id = "pq-rent-no-buy-controls"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Rent Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_distressed_sale_signals": True,
            "enable_auction_legal_review": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_distressed_sale_signals" hidden' in search.text
    assert 'data-property-field-name="enable_auction_legal_review" hidden' in search.text


def test_propertyquarry_workspace_hides_community_validation_when_community_signals_are_off() -> None:
    principal_id = "pq-home-no-community-validation"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Community Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_community_signals": False,
            "require_manual_validation_for_community": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_community_signals"' in search.text
    assert 'data-property-field-name="require_manual_validation_for_community" hidden' in search.text


def test_propertyquarry_workspace_hides_public_housing_child_controls_when_public_housing_signals_are_off() -> None:
    principal_id = "pq-rent-no-public-housing-children"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Public Housing Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_public_housing_signals": False,
            "wiener_wohnticket_available": True,
            "subsidized_required": True,
            "miete_mit_kaufoption": True,
            "eigenmittel_max_eur": 50000,
            "application_window_days": 14,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_public_housing_signals"' in search.text
    assert 'data-property-field-name="wiener_wohnticket_available" hidden' in search.text
    assert 'data-property-field-name="subsidized_required" hidden' in search.text
    assert 'data-property-field-name="miete_mit_kaufoption" hidden' in search.text
    assert 'data-property-field-name="eigenmittel_max_eur" hidden' in search.text
    assert 'data-property-field-name="application_window_days" hidden' in search.text


def test_propertyquarry_workspace_hides_project_stage_controls_when_developer_signals_are_off() -> None:
    principal_id = "pq-no-developer-project-stage-children"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Developer Pipeline Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_developer_project_signals": False,
            "desired_project_stages": ["planned", "waitlist"],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_developer_project_signals"' in search.text
    assert 'data-property-field-name="desired_project_stages" hidden' in search.text


def test_propertyquarry_workspace_hides_recurring_search_details_when_recurring_search_is_off() -> None:
    principal_id = "pq-no-recurring-search-details"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Recurring Search Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "search_agent_enabled": False,
            "search_agent_duration_days": 90,
            "search_agent_notification_limit": 9,
            "search_agent_notification_period": "week",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="search_agent_enabled"' in search.text
    assert 'data-property-field-name="search_agent_duration_days" hidden' in search.text
    assert 'data-property-field-name="search_agent_notification_limit" hidden' in search.text
    assert 'data-property-field-name="search_agent_notification_period" hidden' in search.text


def test_propertyquarry_workspace_hides_preference_profile_when_stored_feedback_is_off() -> None:
    principal_id = "pq-no-stored-feedback-profile"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Feedback Profile Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "use_stored_feedback_preferences": False,
            "preference_person_id": "partner-profile",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="use_stored_feedback_preferences"' not in search.text
    assert 'data-property-field-name="preference_person_id"' not in search.text
    assert "Use stored feedback preferences" not in search.text
    assert "Manage feedback preferences" not in search.text


def test_propertyquarry_brief_script_declares_preference_person_before_payload_use() -> None:
    bundle = _read_workbench_bundle()
    person_decl = bundle.index("const personId = 'self';")
    payload_use = bundle.index("preference_person_id: personId,")
    assert person_decl < payload_use


def test_propertyquarry_brief_script_only_keeps_full_region_scope_when_all_areas_remain_selected() -> None:
    bundle = _read_workbench_bundle()
    assert "const availableLocationTotal = form.querySelectorAll('input[name=\"location_query\"]').length;" in bundle
    assert "const fullRegionScope = allLocationsSelected" in bundle
    assert "selectedLocations.length === availableLocationTotal" in bundle


def test_propertyquarry_run_script_clears_full_region_scope_when_a_district_is_deselected() -> None:
    bundle = _read_workbench_bundle()
    assert "if (target instanceof HTMLInputElement && !target.checked && fullRegionScopeField) {" in bundle
    assert "fullRegionScopeField.checked = false;" in bundle


def test_propertyquarry_run_script_treats_completed_partial_as_terminal() -> None:
    bundle = _read_workbench_bundle()
    assert "const terminalStates = new Set(['processed', 'completed_partial', 'failed', 'noop', 'cancelled', 'completed']);" in bundle


def test_propertyquarry_run_script_compacts_candidate_progress_to_fraction() -> None:
    bundle = _read_workbench_bundle()
    assert "const compactRunMessage = (value) => {" in bundle
    assert "return `${candidateMatch[1]} / ${candidateMatch[2]}`;" in bundle


def test_propertyquarry_run_script_prefers_concrete_provider_labels_for_grouped_sources() -> None:
    bundle = _read_workbench_bundle()
    assert "const genericSourceFamilies = new Set([" in bundle
    assert "if (segments.length > 1 && genericSourceFamilies.has(String(segments[0] || '').trim().toLowerCase())) {" in bundle
    assert "text = segments[segments.length - 1];" in bundle


def test_propertyquarry_results_header_uses_held_back_total_for_filtered_count() -> None:
    bundle = _read_workbench_bundle()
    assert "runPayload?.filtered_total" in bundle
    assert "runPayload?.held_back_total" in bundle
    assert "runPayload?.score_demoted_total" in bundle
    assert "run.get('held_back_total')" in bundle
    assert "run_summary.get('held_back_total')" in bundle
    assert 'id="pqx-filtered-breakdown"' in bundle


def test_property_surface_run_contract_exposes_filtered_totals() -> None:
    contract_path = Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_property_surface_contracts.py"
    body = contract_path.read_text(encoding="utf-8")
    assert "filtered_total: int = 0" in body
    assert "score_demoted_total: int = 0" in body
    assert "held_back_total: int = 0" in body


def test_propertyquarry_run_script_turns_shortlist_build_events_into_phase_copy() -> None:
    bundle = _read_workbench_bundle()
    assert "return 'Shortlist ready';" in bundle
    assert "phaseLabel: `Shortlist ready · ${shortlistMatch[1]} home${String(shortlistMatch[1]) === '1' ? '' : 's'}`," in bundle


def test_propertyquarry_workspace_hides_auction_review_when_distressed_signals_are_off() -> None:
    principal_id = "pq-buy-no-distressed-review"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Auction Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "include_distressed_sale_signals": False,
            "enable_auction_legal_review": True,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="include_distressed_sale_signals"' in search.text
    assert 'data-property-field-name="enable_auction_legal_review" hidden' in search.text


def test_propertyquarry_workspace_hides_lifestyle_detail_controls_when_lifestyle_research_is_off() -> None:
    principal_id = "pq-home-no-lifestyle-detail"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Lifestyle Scope Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "search_goal": "home",
            "enable_lifestyle_research": False,
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "university_name": "WU",
            "max_distance_to_university_m": 500,
            "max_distance_to_starbucks_m": 300,
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert 'data-property-field-name="enable_lifestyle_research"' in search.text
    assert 'data-property-field-name="university_name" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_university_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_starbucks_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_fitness_center_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_cinema_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_bouldering_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_dog_park_m" hidden' in search.text
    assert 'data-property-field-name="max_distance_to_good_cafe_m" hidden' in search.text


def test_propertyquarry_workspace_hides_school_evidence_priority_when_school_evidence_is_inactive() -> None:
    principal_id = "pq-home-no-school-evidence-priority"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="School Evidence Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "school_evidence_priority": "very_important",
            "require_school_evidence": False,
            "school_stage_preferences": [],
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert re.search(
        r'data-property-field-name="school_evidence_priority"[^>]*data-property-semantic-hidden="true"[^>]*hidden',
        search.text,
    )
    assert 'data-property-field-name="school_quality_priority"' not in search.text


def test_propertyquarry_workspace_hides_distance_importance_controls_without_distance_caps() -> None:
    principal_id = "pq-home-no-distance-importance"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Distance Importance Office")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "search_goal": "home",
            "region_code": "vienna",
            "location_query": "Vienna",
            "selected_platforms": ["willhaben"],
            "max_distance_to_playground_m": 0,
            "max_distance_to_playground_importance": "must_have",
            "max_distance_to_library_m": 0,
            "max_distance_to_library_importance": "must_have",
            "max_distance_to_supermarket_m": 0,
            "max_distance_to_supermarket_importance": "must_have",
        },
    )
    assert stored.status_code == 200, stored.text

    search = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert search.status_code == 200
    assert re.search(r'data-property-field-name="max_distance_to_library_importance"[^>]*hidden', search.text)
    assert re.search(r'data-property-field-name="max_distance_to_supermarket_importance"[^>]*hidden', search.text)


def test_propertyquarry_workspace_setup_stays_user_facing(monkeypatch) -> None:
    principal_id = "pq-provider-quality"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "in_progress",
            "progress": 12,
            "message": "Scanning providers.",
            "summary": {"status": "in_progress", "sources": []},
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)

    response = client.get("/app/properties", params={"run_id": "run-42"}, headers=headers)
    assert response.status_code == 200
    assert "Run" in response.text
    assert "Search" in response.text
    assert "Shortlist" in response.text
    assert "Automation" in response.text
    assert "Build the brief. Then let the agents work." not in response.text


def test_property_workspace_search_controls_have_explicit_click_handlers() -> None:
    body = _read_workbench_bundle()

    assert 'data-checkbox-group-select-all="{{ field.name }}"' in body
    assert "field.name == 'selected_platforms'" in body
    assert "form.querySelectorAll('[data-checkbox-group-select-all]').forEach((button) => {" in body
    assert "const groupSelect = event.target?.closest?.('[data-checkbox-group-select-scope]');" in body
    assert "const groupClear = event.target?.closest?.('[data-checkbox-group-clear-scope]');" in body
    assert "root.querySelectorAll('[data-pqx-delete-run]').forEach((button) => {" in body
    assert "loadSearchAgentRow(row, false)" in body
    assert "loadSearchAgentRow(row, true)" in body


def test_property_workspace_search_uses_groupboxes_without_feedback_profile_noise() -> None:
    template_body = (Path(__file__).resolve().parents[1] / "ea/app/templates/app/property_decision_workbench.html").read_text(encoding="utf-8")
    view_model_body = (Path(__file__).resolve().parents[1] / "ea/app/api/routes/landing_view_models.py").read_text(encoding="utf-8")

    assert "pqx-choice-groupbox" in template_body
    assert "Neutral by default" in template_body
    assert ">Neutral</option>" in template_body
    assert '"label": "What matters"' in view_model_body
    assert '"name": "preference_person_id"' not in view_model_body
    assert '"name": "use_stored_feedback_preferences"' not in view_model_body


def test_propertyquarry_failed_run_stays_on_activity_surface(monkeypatch) -> None:
    principal_id = "pq-failed-run-visible"
    client = build_property_client(principal_id=principal_id)
    headers = {"host": "propertyquarry.com"}
    start_workspace(client, mode="personal", workspace_name="Failed Run Office")

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "failed",
            "progress": 100,
            "message": "Provider returned 403 while fetching Willhaben.",
            "summary": {
                "sources_total": 1,
                "listing_total": 0,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "repair_status": "repairing",
                "repair_status_label": "Repairing",
                "repair_step_label": "Retrying Willhaben provider check",
                "sources": [],
            },
            "events": [
                {"step": "source_fetching", "message": "Fetching source page for Willhaben.", "status": "in_progress"},
                {"step": "failed", "message": "Provider returned 403 while fetching Willhaben.", "status": "failed"},
            ],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    page = client.get("/app/properties", params={"run_id": "run-failed"}, headers=headers)
    assert page.status_code == 200
    assert 'data-pqx-state="empty_results"' in page.text
    assert "The search could not finish." not in page.text
    assert "Repairing search." in page.text
    assert "Retrying Willhaben provider check" in page.text
    empty_section = re.search(r'<section class="pqx-stage pqx-empty-results.*?</section>', page.text, re.S)
    assert empty_section is not None
    assert empty_section.group(0).count("Retrying Willhaben provider check") == 1
    hero_note = re.search(r'<div class="pqx-note">\s*(.*?)\s*</div>', page.text, re.S)
    assert hero_note is not None
    assert "<strong>" not in hero_note.group(1)
    assert "Repair is queued for the interrupted provider checks." not in page.text
    assert "Auto-repair is queued and will retry" not in page.text
    assert "Best matches" not in page.text
    assert "Provider returned 403 while fetching Willhaben." in page.text
    assert "Open to relax one rule and rerun the search." not in page.text
    assert "New search" in page.text
    assert "updates quietly every 10s" in page.text
    assert "checks quietly every 10s" not in page.text
    assert "refresh this page" not in page.text
    assert "Checking repair status automatically every 10s." not in page.text
    assert "Repair status checked at" not in page.text
    assert "Check repair status" not in page.text
    assert "Refresh delivery" not in page.text
    assert "Search progress" not in page.text
    assert 'data-workbench-brief-drawer' not in page.text
    assert "Tell us what to find." not in page.text


def test_propertyquarry_failed_parent_run_with_replacement_hides_stale_source_count() -> None:
    summary = property_surface_state.build_property_empty_outcome_summary(
        run_summary={
            "sources_total": 156,
            "sources_completed": 0,
            "listing_total": 0,
            "repair_status": "repairing",
            "repair_status_label": "Repairing",
            "repair_step_label": "Started a replacement search run from the saved brief.",
            "repair_replacement_run_id": "replacement-run",
        },
        run_sources=[],
        run_status_value="failed",
        run_message="Repairing interrupted run while the worker restarts.",
        counterfactual_rows=[],
        suppression_rows=[],
    )

    combined = " ".join(str(value) for value in summary.values())
    assert "A replacement search is checking the saved brief." in combined
    assert "The brief was saved; the replacement run is now active." in combined
    assert "repair receipt" not in combined.lower()
    assert "run receipts" not in combined.lower()
    assert "0/156 source variants" not in combined
    assert "0/156 provider checks" not in combined
    assert "interrupted pass stopped" not in combined


def test_propertyquarry_failed_repair_without_progress_hides_stale_zero_source_count() -> None:
    summary = property_surface_state.build_property_empty_outcome_summary(
        run_summary={
            "sources_total": 156,
            "sources_completed": 0,
            "listing_total": 0,
            "repair_status": "repairing",
            "repair_status_label": "Repairing",
            "repair_step_label": "Repairing interrupted run.",
            "provider_repair_tasks": [{"status": "opened"}],
        },
        run_sources=[],
        run_status_value="failed",
        run_message="Repairing interrupted run while the worker restarts.",
        counterfactual_rows=[],
        suppression_rows=[],
    )

    combined = " ".join(str(value) for value in summary.values())
    assert summary["happened"] == "Repair is retrying the interrupted search."
    assert "The brief and selected sources were still saved." in combined
    assert "Repair took over before any listing inspection completed." in combined
    assert "repair receipt" not in combined.lower()
    assert "run receipts" not in combined.lower()
    assert "0/156" not in combined
    assert "source variants" not in combined
    assert "source checks" not in combined.lower()


def test_propertyquarry_empty_outcome_explains_selected_area_dead_end() -> None:
    summary = property_surface_state.build_property_empty_outcome_summary(
        run_summary={
            "status": "processed",
            "sources_total": 31,
            "sources_completed": 31,
            "raw_listing_total": 361,
            "listing_total": 0,
            "filtered_total": 236,
            "held_back_total": 236,
            "filtered_area_total": 153,
            "filtered_generic_page_total": 83,
        },
        run_sources=[
            {
                "source_scope_label": "Willhaben | Austria | Rent | 1010 Vienna",
                "location_mismatch_candidate_total": 30,
                "filtered_area_total": 30,
            }
        ],
        run_status_value="processed",
        run_message="Property scouting run completed.",
        counterfactual_rows=[],
        suppression_rows=[],
    )

    assert summary["happened"] == "No valid homes survived inside the selected area."
    assert "361 candidates returned by the selected sources" in summary["still_worked"]
    assert "Widen the selected districts" in summary["next_move"]
    assert "provider overview pages" in summary["eta_feedback"]
    assert "receipts" not in " ".join(summary.values()).lower()
    assert "0/31 source variants" not in " ".join(summary.values())


def test_propertyquarry_packet_enriches_sparse_candidate_facts_for_investment(monkeypatch) -> None:
    principal_id = "pq-packet-fact-enrichment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Packet Enrichment")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    sparse_candidate = {
        "title": "Familien-Maisonette mit weitläufiger Terrasse und drei Zimmern, 88,48 m², € 659.000,-, (1160 Wien) - willhaben",
        "property_url": "https://www.willhaben.at/iad/object?adId=2113641102",
        "fit_summary": "Sparse candidate facts should still allow underwriting.",
        "recommendation": "shortlist",
        "review_url": "",
        "tour_url": "",
        "match_reasons": ["Location and layout fit."],
        "mismatch_reasons": [],
        "property_facts": {"has_360": False},
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Willhaben | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [sparse_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(
        landing_property_research,
        "_property_investment_research_snapshot",
        lambda **kwargs: {
            "current_price_eur": 659000.0,
            "current_area_sqm": 88.48,
            "current_price_per_sqm_eur": 7448.01,
            "market_buy_per_sqm_eur": 7000.0,
            "market_buy_delta_pct": 6.4,
            "market_rent_per_sqm_eur": 18.5,
            "expected_monthly_rent_eur": 1636.88,
            "gross_yield_pct": 2.98,
            "payback_years": 33.5,
            "buy_sample_count": 4,
            "rent_sample_count": 3,
            "buy_samples": [{"title": "Comp A", "per_sqm_eur": 7000.0, "source_label": "Willhaben"}],
            "rent_samples": [{"title": "Rent Comp A", "per_sqm_eur": 18.5, "source_label": "Willhaben"}],
        },
    )

    headers = {"host": "propertyquarry.com"}
    research = client.get("/app/research", params={"run_id": "run-88"}, headers=headers)
    packet_match = re.search(r'href="(/app/research/[^"?]+)\?run_id=run-88"', research.text)
    assert packet_match is not None
    packet = client.get(packet_match.group(1), params={"run_id": "run-88", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Investment research is waiting on core facts" not in packet.text
    assert "Current underwriting base" in packet.text
    assert "Buy-side benchmark" in packet.text
    assert "Gross yield" in packet.text
    assert "Institutional underwriting score" in packet.text


def test_propertyquarry_workspace_search_surface_keeps_internal_review_link(monkeypatch) -> None:
    principal_id = "pq-redesign-no-fallback"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-redesign-no-fallback"
        return (
            HandoffNote(
                id="human_task:tour-2",
                queue_item_ref="queue:tour-2",
                summary="Review shortlisted property packet",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_alert_review",
                delivery_reason="Research page is still pending.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="",
            ),
        )

    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

    response = client.get("/app/properties", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert "Search" in response.text


def test_propertyquarry_research_packet_shows_auction_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-auction-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["justiz_edikte_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    auction_candidate = {
        "title": "BG Innere Stadt Wien, 001 50 E 30/25a",
        "summary": "",
        "property_url": "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        "fit_score": 37.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "court": "BG Innere Stadt Wien",
            "court_file_reference": "001 50 E 30/25a",
            "valuation_display": "EUR 310,000",
            "reserve_price_display": "EUR 155,000",
            "occupancy_status": "occupied",
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Justiz Edikte Auctions | Austria | Buy | Wien",
                        "listing_total": 1,
                        "top_candidates": [auction_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_property_research, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    packet_ref = landing_property_research._property_candidate_ref(
        {
            **auction_candidate,
            "source_label": "Justiz Edikte Auctions | Austria | Buy | Wien",
        }
    )
    packet = client.get(f"/app/research/{packet_ref}", params={"run_id": "run-auction", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Court process" in packet.text
    assert "Case reference" in packet.text
    assert "Judicial valuation" in packet.text
    assert "Reserve or deposit" in packet.text
    assert "Judicial sale diligence" in packet.text


def test_propertyquarry_research_packet_shows_cooperative_investment_context_when_benchmark_is_pending(monkeypatch) -> None:
    principal_id = "pq-redesign-coop-investment"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "investment_research_mode": "auto",
            "location_query": "Wien",
            "selected_platforms": ["genossenschaften_at"],
            "preference_person_id": "self",
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    coop_candidate = {
        "title": "1210 Wien | Antonie-Lehr-Straße 18 / Leopoldauer Haide Gasse 12",
        "summary": "Miete | 144 units | August 2026 | 37486 registrations",
        "property_url": "https://angebote.sozialbau.at/sobitvX/htmlprospect/home.xhtml?pq_listing=1",
        "fit_score": 52.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "tour_status": "skipped",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "provider_group": "genossenschaften_at",
            "provider_channel": "sozialbau",
            "marketing_type": "Miete",
            "availability_label": "August 2026",
            "registration_count": 37486,
            "postal_name": "1210 Wien",
            "has_floorplan": False,
            "floorplan_count": 0,
        },
    }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "done",
            "summary": {
                "sources_total": 1,
                "listing_total": 1,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Genossenschaften | Austria | Buy | Wien | Sozialbau Projekte in Bau",
                        "listing_total": 1,
                        "top_candidates": [coop_candidate],
                    }
                ],
            },
            "events": [],
        }

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(landing_property_research, "_property_investment_research_snapshot", lambda **kwargs: {})

    headers = {"host": "propertyquarry.com"}
    packet_ref = landing_property_research._property_candidate_ref(
        {
            **coop_candidate,
            "source_label": "Genossenschaften | Austria | Buy | Wien | Sozialbau Projekte in Bau",
        }
    )
    packet = client.get(f"/app/research/{packet_ref}", params={"run_id": "run-coop", "investment": 1}, headers=headers)
    assert packet.status_code == 200
    assert "Provider lane" in packet.text
    assert "Offer posture" in packet.text
    assert "Applicant pressure" in packet.text
    assert "Rental-led cooperative lane" in packet.text
    assert "Extremely high applicant pressure" in packet.text
    assert "No hosted 3D tour yet" in packet.text
    assert "Floorplan missing" in packet.text
    assert "not scheduled yet" not in packet.text
    assert "1210 Wien" in packet.text


def test_property_research_packet_uses_cross_run_lookup_for_missing_candidate(monkeypatch) -> None:
    principal_id = "pq-research-packet-cross-run"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    candidate = {
        "title": "Praterstrasse 77 · 2 Zimmer · 77 m² · 1.198",
        "summary": "",
        "property_url": "https://www.willhaben.at/iad/object?adId=1134225012",
        "fit_score": 67.0,
        "fit_summary": "Strong transit and kitchen.",
        "recommendation": "Consider",
        "review_url": "",
        "tour_url": "",
        "match_reasons": ["Transit fit", "Price fit"],
        "mismatch_reasons": ["Small parking"],
        "property_facts": {
            "price_eur": 1198.0,
            "area_m2": 77.0,
            "rooms": 2.0,
            "source_scope_location": "1010 Vienna",
        },
    }

    fallback_candidate = dict(candidate)
    fallback_candidate["source_label"] = "Willhaben|AT|Rent|Wien"

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-stale",
                "principal_id": principal_id,
                "status": "completed",
                "summary": {
                    "ranked_candidates": [],
                    "filtered_total": 0,
                    "sources": [],
                },
            },
            {
                "run_id": "run-current",
                "principal_id": principal_id,
                "status": "completed",
                "summary": {
                    "ranked_candidates": [fallback_candidate],
                },
            },
        ]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        if str(run_id) == "run-current":
            return {
                "run_id": run_id,
                "principal_id": principal_id,
                "status": "completed",
                "progress": 100,
                "message": "done",
                "summary": {"sources": [{"source_label": "Willhaben|AT|Rent|Wien", "top_candidates": [fallback_candidate]}]},
            }
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "completed",
            "progress": 100,
            "message": "done",
            "summary": {"ranked_candidates": []},
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    packet_ref = landing_property_research._property_candidate_ref(
        {
            **fallback_candidate,
            "source_label": "Willhaben|AT|Rent|Wien",
        }
    )

    packet = client.get(f"/app/research/{packet_ref}", params={"run_id": "run-stale"}, headers={"host": "propertyquarry.com"})
    assert packet.status_code == 200
    assert "Praterstrasse 77 · 2 Zimmer · 77 m² · 1.198" in packet.text
    assert "Transit fit" in packet.text


def test_property_research_packet_uses_saved_shortlist_fallback(monkeypatch) -> None:
    principal_id = "pq-research-packet-saved-shortlist"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    saved_candidate = {
        "title": "Saved shortlist flat",
        "property_url": "https://example.com/homes/shortlist-home",
        "summary": "",
        "fit_score": 72.0,
        "fit_summary": "",
        "recommendation": "",
        "review_url": "",
        "tour_url": "",
        "match_reasons": [],
        "mismatch_reasons": [],
        "property_facts": {
            "price_eur": 900.0,
            "area_m2": 65.0,
        },
        "source_label": "Willhaben|AT|Rent|Wien",
        "saved_from_run_id": "run-shortlist",
    }

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [
            {
                "run_id": "run-empty",
                "status": "completed",
                "principal_id": principal_id,
                "summary": {"ranked_candidates": []},
            }
        ]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "completed",
            "progress": 100,
            "message": "done",
            "summary": {"ranked_candidates": []},
        }

    def _fake_saved_shortlist(self, *, principal_id: str):
        return [dict(saved_candidate)]

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_property_saved_shortlist_candidates", _fake_saved_shortlist)

    packet_ref = landing_property_research._property_candidate_ref(saved_candidate)
    packet = client.get(f"/app/research/{packet_ref}", params={"run_id": "run-missing"}, headers={"host": "propertyquarry.com"})
    assert packet.status_code == 200
    assert "Saved shortlist flat" in packet.text


def test_property_research_packet_missing_candidate_redirects_to_shortlist(monkeypatch) -> None:
    principal_id = "pq-research-packet-missing-redirect"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [{"run_id": "run-missing", "status": "completed", "principal_id": principal_id, "summary": {"ranked_candidates": []}}]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "completed",
            "progress": 100,
            "message": "done",
            "summary": {"ranked_candidates": []},
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_property_saved_shortlist_candidates", lambda self, *, principal_id: [])

    packet = client.get(
        "/app/research/missing-packet-ref",
        params={"run_id": "run-missing"},
        headers={"host": "propertyquarry.com"},
        follow_redirects=False,
    )

    assert packet.status_code == 307
    assert packet.headers["location"] == (
        "/app/shortlist?packet_missing=1&run_id=run-missing&missing_candidate_ref=missing-packet-ref#results-list"
    )

    shortlist = client.get(packet.headers["location"], headers={"host": "propertyquarry.com"})
    assert shortlist.status_code == 200
    assert "Property page is being rebuilt" in shortlist.text
    assert "Repair queued for the missing property page" in shortlist.text
    assert "Repair queued" in shortlist.text
    assert "missing-packet-ref" in shortlist.text
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(repair_tasks) == 1
    assert repair_tasks[0].priority == "urgent"
    assert repair_tasks[0].assigned_operator_id == "ea_one_manager"
    repair_payload = dict(repair_tasks[0].input_json or {})
    assert repair_payload["repair_workflow"] == "ea_provider_ooda"
    assert repair_payload["filter_key"] == "research_packet_missing"
    assert repair_payload["run_id"] == "run-missing"
    assert dict(repair_payload["diagnostics"])["candidate_ref"] == "missing-packet-ref"


def test_property_research_packet_missing_candidate_returns_recovery_json(monkeypatch) -> None:
    principal_id = "pq-research-packet-missing-json"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Office")

    def _fake_runs(self, *, principal_id: str, limit: int = 8):
        return [{"run_id": "run-json", "status": "completed", "principal_id": principal_id, "summary": {"ranked_candidates": []}}]

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status": "completed",
            "progress": 100,
            "message": "done",
            "summary": {"ranked_candidates": []},
        }

    monkeypatch.setattr(ProductService, "list_property_search_runs", _fake_runs)
    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_property_saved_shortlist_candidates", lambda self, *, principal_id: [])

    packet = client.get(
        "/app/research/missing-json-ref",
        params={"run_id": "run-json"},
        headers={"host": "propertyquarry.com", "accept": "application/json"},
        follow_redirects=False,
    )

    assert packet.status_code == 202
    payload = packet.json()
    assert payload["code"] == "property_research_packet_recovery"
    assert payload["status"] == "recovery_available"
    assert payload["repair_status"] == "needs_rebuild"
    assert payload["candidate_ref"] == "missing-json-ref"
    assert payload["queue_item_ref"].startswith("human_task:")
    assert payload["redirect_url"] == (
        "/app/shortlist?packet_missing=1&run_id=run-json&missing_candidate_ref=missing-json-ref#results-list"
    )
    assert "property_research_packet_not_found" not in packet.text
    repeated = client.get(
        "/app/research/missing-json-ref",
        params={"run_id": "run-json"},
        headers={"host": "propertyquarry.com", "accept": "application/json"},
        follow_redirects=False,
    )
    assert repeated.status_code == 202
    assert repeated.json()["queue_item_ref"] == payload["queue_item_ref"]
    repair_tasks = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_provider_repair_ooda"
    ]
    assert len(repair_tasks) == 1
    assert dict(repair_tasks[0].input_json or {}).get("filter_key") == "research_packet_missing"
    repair_summary = ProductService(client.app.state.container).process_property_provider_repair_tasks(
        principal_id=principal_id,
        actor="test",
        limit=5,
    )
    assert repair_summary["deferred_total"] == 1


def test_propertyquarry_settings_hide_generic_google_sync_metrics() -> None:
    client = build_property_client(principal_id="pq-redesign-settings")
    start_workspace(client, mode="personal", workspace_name="Property Office")

    account = client.get("/app/account", headers={"host": "propertyquarry.com"})
    assert account.status_code == 200
    assert "Identity, plan, delivery, and editable defaults." in account.text
    assert "Search defaults" in account.text
    assert "Edit search" in account.text
    assert account.text.count("Edit search") == 1
    assert "Open automation" not in account.text
    assert account.text.count("Open pricing") == 1
    assert "Useful account controls" in account.text
    assert "Automation and reports" not in account.text
    assert "Recurring intelligence leaving this account" not in account.text
    assert "Delivery lane" not in account.text
    assert 'href="/app/search' in account.text
    assert "Operating posture" not in account.text
    assert 'id="settings"' in account.text
    assert 'id="plans"' in account.text
    assert 'id="profile"' in account.text
    assert "Open pricing" in account.text
    assert "Open security" in account.text
    assert "Sync runs" not in account.text
    assert "Last Google sync" not in account.text
    assert "Office signals ingested" not in account.text


def test_propertyquarry_account_exposes_working_lifecycle_controls(monkeypatch) -> None:
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps(
            {
                "propertyquarry": {
                    "token": "telegram-secret-token",
                    "handle": "propertyquarry_bot",
                }
            }
        ),
    )
    principal_id = "pq-account-lifecycle-controls"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Lifecycle Controls")
    headers = {"host": "propertyquarry.com"}

    account = client.get("/app/account", headers=headers)
    assert account.status_code == 200
    assert "Export account data" in account.text
    assert 'href="/app/api/property/account/export?download=1"' in account.text
    assert "Clear search history" in account.text
    assert 'action="/app/api/property/search-runs/clear"' in account.text
    assert "Manage access links" in account.text
    assert 'href="/app/settings/access"' in account.text
    assert "Public packets and tours" in account.text
    assert 'href="/app/properties/packets"' in account.text
    assert "Connected services" in account.text
    assert 'href="/app/settings/google"' in account.text
    assert "Analytics and learning" in account.text
    assert 'href="/cookies"' in account.text
    assert "Delete account data" in account.text
    assert 'href="/data-deletion"' in account.text
    assert "Notification type" in account.text
    assert "Choose where strong-match notifications arrive." in account.text
    assert 'action="/app/api/property/account/notifications"' in account.text
    assert 'value="email"' in account.text
    assert 'value="telegram"' in account.text
    assert 'data-channel-detail="email"' in account.text
    assert 'data-channel-detail="telegram"' in account.text
    assert 'data-channel-detail="whatsapp"' in account.text
    assert '.pqx-account-channel-form:has(input[name="preferred_channel"][value="whatsapp"]:checked)' in account.text
    assert "WhatsApp number" in account.text
    assert "Used for WhatsApp scout updates when WhatsApp is selected" in account.text
    assert "Support starts by asking what you need before giving property guidance" in account.text
    assert "Used only for PropertyQuarry AI support." not in account.text
    assert "Save alerts and AI support number" not in account.text
    assert 'name="whatsapp_ai_support_phone"' in account.text
    assert "PropertyQuarry bot" in account.text
    assert "@propertyquarry_bot" in account.text
    assert 'href="https://t.me/propertyquarry_bot"' in account.text
    assert "telegram-secret-token" not in account.text
    assert "Official assistant bot" not in account.text
    assert "generic history" not in account.text
    assert "EA host" not in account.text
    assert 'value="whatsapp"' in account.text
    assert 'value="signal" disabled' in account.text
    access_links = client.get("/app/settings/access", headers=headers)
    assert access_links.status_code == 200
    assert "Create an access link" in access_links.text
    assert "Live access links" in access_links.text
    assert "workspace access links" not in access_links.text

    export = client.get("/app/api/property/account/export", headers=headers)
    assert export.status_code == 200
    payload = export.json()
    assert payload["export_type"] == "propertyquarry_account_data"
    assert payload["principal_id"] == principal_id
    assert isinstance(payload["property_search_preferences"], dict)
    assert isinstance(payload["recent_property_search_runs"], list)
    assert payload["property_passport_summary"]["property_count"] == 0
    assert isinstance(payload["property_passport_summary"]["properties"], list)
    assert "access_token" not in json.dumps(payload)

    notification_update = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "telegram", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers=headers,
        follow_redirects=False,
    )
    assert notification_update.status_code == 303
    assert notification_update.headers["location"] == "/app/account?notifications_saved=1#delivery"
    export_after_update = client.get("/app/api/property/account/export", headers=headers)
    assert export_after_update.status_code == 200
    assert (
        export_after_update.json()["delivery_preferences"]["property_notifications"]["preferred_channel"]
        == "telegram"
    )
    assert (
        export_after_update.json()["delivery_preferences"]["property_notifications"]["notification_scope"]
        == "scout_updates"
    )
    assert (
        export_after_update.json()["delivery_preferences"]["property_notifications"]["whatsapp_notification_opt_in"]
        is False
    )
    assert (
        export_after_update.json()["delivery_preferences"]["property_notifications"]["whatsapp_ai_support_phone"]
        == "+436647916419"
    )
    assert (
        export_after_update.json()["delivery_preferences"]["property_notifications"]["whatsapp_ai_support_purpose"]
        == "ai_support_only"
    )
    assert "whatsapp" in client.app.state.container.onboarding._ensure_state(principal_id).selected_channels  # noqa: SLF001
    contact_hint = build_product_service(client.app.state.container)._heyy_whatsapp_contact_hint(  # noqa: SLF001
        principal_id=principal_id
    )
    assert contact_hint["phone_number"] == "+436647916419"

    whatsapp_update = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "whatsapp", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers=headers,
        follow_redirects=False,
    )
    assert whatsapp_update.status_code == 303
    export_after_whatsapp = client.get("/app/api/property/account/export", headers=headers)
    assert export_after_whatsapp.status_code == 200
    whatsapp_preferences = export_after_whatsapp.json()["delivery_preferences"]["property_notifications"]
    assert whatsapp_preferences["preferred_channel"] == "whatsapp"
    assert whatsapp_preferences["whatsapp_notification_opt_in"] is True

    signal_update = client.post(
        "/app/api/property/account/notifications",
        data={"preferred_channel": "signal", "whatsapp_ai_support_phone": "+43 664 791 6419"},
        headers=headers,
        follow_redirects=False,
    )
    assert signal_update.status_code == 400
    assert "property_notification_channel_invalid" in signal_update.text

    download = client.get("/app/api/property/account/export?download=1", headers=headers)
    assert download.status_code == 200
    assert download.headers["cache-control"] == "no-store"
    assert "propertyquarry-account-export" in download.headers["content-disposition"]

    access = client.get("/app/settings/access", headers=headers)
    assert access.status_code == 200
    assert "Access" in access.text


def test_propertyquarry_account_does_not_embed_full_raw_preference_payload() -> None:
    large_note = "oversized-preference-payload-" + ("x" * 250_000)
    payload = landing_property_workspace_payload.property_workspace_payload(
        "account",
        status={
            "workspace": {"name": "Property Office", "timezone": "Europe/Vienna"},
            "channels": {},
        },
        property_state={
            "country_label": "Austria",
            "region_label": "Vienna",
            "preferences": {
                "country_code": "AT",
                "region_code": "vienna",
                "location_query": "1020 Vienna",
                "listing_mode": "rent",
                "property_type": "apartment",
                "raw_preferences": {"notes": large_note},
                "search_agents": [
                    {
                        "agent_id": "agent-large",
                        "name": "Large saved search",
                        "preferences_json": {"notes": large_note},
                    }
                ],
                "property_commercial": {"debug": large_note},
            },
            "preference_bundle": {},
            "commercial": {},
            "billing_truth": {},
            "selected_platforms": ["willhaben"],
            "run": {},
            "run_health": {},
        },
    )

    workbench = dict(payload.get("decision_workbench") or {})
    brief_preferences = dict(workbench.get("brief_preferences") or {})
    encoded = json.dumps(brief_preferences, sort_keys=True)
    assert "oversized-preference-payload" not in encoded
    assert set(brief_preferences) <= {
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


def test_propertyquarry_agents_page_trims_saved_search_edit_payloads() -> None:
    large_note = "oversized-agent-payload-" + ("x" * 250_000)
    client = build_property_client(principal_id="pq-agent-payload-trim")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    response = client.post(
        "/v1/onboarding/property-search/preferences",
        headers={"host": "propertyquarry.com"},
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "location_query": "1020 Vienna",
            "listing_mode": "rent",
            "property_type": "apartment",
            "search_agents": [
                {
                    "agent_id": "agent-large",
                    "name": "Large saved search",
                    "enabled": True,
                    "preferences_json": {
                        "country_code": "AT",
                        "region_code": "vienna",
                        "location_query": "1020 Vienna",
                        "listing_mode": "rent",
                        "property_type": "apartment",
                        "notes": large_note,
                        "raw_preferences": {"notes": large_note},
                    },
                }
            ],
        },
    )
    assert response.status_code == 200

    agents = client.get("/app/agents", headers={"host": "propertyquarry.com"})
    assert agents.status_code == 200
    assert "Large saved search" in agents.text
    assert "oversized-agent-payload" not in agents.text
    assert "preferenceProfileEndpoint" not in agents.text
    assert "Saved durably. Profile now has" not in agents.text
    assert len(agents.text) < 380_000


def test_propertyquarry_static_surfaces_do_not_inline_search_only_scripts() -> None:
    client = build_property_client(principal_id="pq-static-surface-payload")
    start_workspace(client, mode="personal", workspace_name="Property Static Payload")
    headers = {"host": "propertyquarry.com"}

    for route in ("/app/agents", "/app/account", "/app/billing"):
        response = client.get(route, headers=headers)
        assert response.status_code == 200
        assert "preferenceProfileEndpoint" not in response.text
        assert "Saved durably. Profile now has" not in response.text
        assert len(response.text) < 420_000, route


def test_propertyquarry_account_payload_avoids_internal_posture_labels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    payload_source = (repo_root / "ea/app/api/routes/landing_property_workspace_payload.py").read_text(encoding="utf-8")

    assert '"eyebrow": "Operating posture"' not in payload_source
    assert '"title": "Commercial posture"' not in payload_source
    assert '"title": "Edit"' in payload_source
    assert '"title": "Plan access"' in payload_source


def test_property_workspace_primary_internal_links_resolve() -> None:
    principal_id = "pq-primary-link-audit"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Link Audit")
    public_client = build_property_client(principal_id="pq-primary-public-link-audit")
    public_client.headers.pop("X-EA-Principal-ID", None)
    headers = {"host": "propertyquarry.com"}
    channel_redirect = client.get("/app/channels", headers=headers, follow_redirects=False)
    assert channel_redirect.status_code == 307
    assert channel_redirect.headers["location"] == "/app/account#delivery"
    automation_redirect = client.get("/app/automations", headers=headers, follow_redirects=False)
    assert automation_redirect.status_code == 307
    assert automation_redirect.headers["location"] == "/app/agents"
    automation_singular_redirect = client.get("/app/automation", headers=headers, follow_redirects=False)
    assert automation_singular_redirect.status_code == 307
    assert automation_singular_redirect.headers["location"] == "/app/agents"
    pages = [
        (client, "/app/search"),
        (client, "/app/properties"),
        (client, "/app/shortlist"),
        (client, "/app/agents"),
        (client, "/app/account"),
        (client, "/app/account#profile"),
        (client, "/app/profile"),
        (client, "/app/alerts"),
        (client, "/app/settings/access"),
        (public_client, "/"),
        (public_client, "/?home=1"),
        (public_client, "/sign-in"),
        (public_client, "/pricing"),
        (public_client, "/data-deletion"),
    ]
    protected_current_session_targets = {"/app/search", "/app/properties", "/app/shortlist"}
    checked: set[str] = set()
    failures: list[str] = []
    fragment_failures: list[str] = []
    button_failures: list[str] = []
    form_failures: list[str] = []
    audited_page_paths: set[str] = set()
    for page_client, page_path in pages:
        audited_page_paths.add(page_path.split("#", 1)[0])
        page = page_client.get(page_path, headers=headers, follow_redirects=True)
        assert page.status_code == 200, page.text[:500]
        assert not re.search(r'href="/app/settings(?=[?#"])', page.text), page_path
        for href in re.findall(r'href="([^"]+)"', page.text):
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            if href.startswith("#"):
                fragment = href[1:].strip()
                if fragment and f'id="{fragment}"' not in page.text and f"id='{fragment}'" not in page.text:
                    fragment_failures.append(f"{page_path} offers {href} but no matching id is rendered")
                continue
            if href.startswith(("http://", "https://", "//")):
                continue
            target, _, fragment = href.partition("#")
            if page_client is public_client and target in protected_current_session_targets:
                failures.append(f"{page_path} offers protected current-session target {href} to an anonymous visitor")
                continue
            if "__" in href or href.startswith("/app/api/"):
                continue
            target = target or page_path.split("#", 1)[0]
            if not target.startswith("/"):
                continue
            if target in checked:
                continue
            checked.add(target)
            response = page_client.get(target, headers=headers, follow_redirects=True)
            if page_client is public_client and target.startswith("/app/") and response.status_code in {401, 403}:
                failures.append(f"{page_path} offers protected link {href} to an anonymous visitor")
                continue
            if response.status_code >= 400:
                failures.append(f"{page_path} offers {href} -> {response.status_code}")
            elif fragment and f'id="{fragment}"' not in response.text and f"id='{fragment}'" not in response.text:
                fragment_failures.append(f"{page_path} offers {href} but {target} has no matching id")
        for form_attrs in re.findall(r"<form([^>]*)>", page.text, flags=re.DOTALL):
            attrs = dict(re.findall(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)="([^"]*)"', form_attrs))
            action = str(attrs.get("action") or "").strip()
            method = str(attrs.get("method") or "get").strip().lower() or "get"
            has_data_handler = any(key.startswith("data-") for key in attrs)
            if not action and not has_data_handler:
                form_failures.append(f"{page_path} renders form without action or client handler")
            if action.lower().startswith("javascript:"):
                form_failures.append(f"{page_path} renders javascript form action {action!r}")
            if method not in {"get", "post", "dialog"}:
                form_failures.append(f"{page_path} renders unsupported form method {method!r}")
            if page_client is public_client and action in protected_current_session_targets:
                form_failures.append(f"{page_path} renders anonymous form to protected target {action!r}")
        for button_attrs, button_label in re.findall(r"<button([^>]*)>(.*?)</button>", page.text, flags=re.DOTALL):
            attrs = button_attrs.strip()
            if "disabled" in attrs:
                continue
            if 'type="submit"' in attrs or "type='submit'" in attrs:
                continue
            if "data-" in attrs or "popovertarget=" in attrs or "aria-controls=" in attrs:
                continue
            label = re.sub(r"<[^>]+>", " ", button_label)
            label = re.sub(r"\s+", " ", label).strip()
            button_failures.append(f"{page_path} renders inert button {label!r} attrs={attrs!r}")
    assert not failures
    assert not fragment_failures
    assert not button_failures
    assert not form_failures
    assert "/app/account" in checked
    assert "/app/search" in checked
    assert "/sign-in" in audited_page_paths


def test_propertyquarry_shell_uses_the_new_surface_navigation() -> None:
    client = build_property_client(principal_id="pq-surface-nav")
    start_workspace(client, mode="personal", workspace_name="Surface Nav")

    response = client.get("/app/search", headers={"host": "propertyquarry.com"})
    assert response.status_code == 200
    assert ">Search<" in response.text
    assert ">Run<" not in response.text
    assert ">Shortlist<" in response.text
    assert ">Automation<" in response.text
    assert ">Account<" in response.text
    assert 'href="/app/research"' not in response.text
    assert ">Alerts<" not in response.text
    assert ">Billing<" in response.text
