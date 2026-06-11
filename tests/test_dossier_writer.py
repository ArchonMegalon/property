from __future__ import annotations

from app.services.dossier_writer import claims_from_deep_research, verify_dossier_narrative, write_claim_bound_dossier, write_verified_dossier_from_research
from app.services.dossier_writer.models import DossierSectionDraft
from app.services.dossier_writer.neuronwriter_adapter import create_neuronwriter_query, get_neuronwriter_query, recommend_for_draft
from app.api.dependencies import RequestContext
from app.api.routes.product_api import (
    PropertyDossierWriteIn,
    PropertyNeuronWriterQueryIn,
    create_property_neuronwriter_query,
    write_property_dossier,
)


def _research() -> dict[str, object]:
    return {
        "title": "Neubauwohnung mit Balkon in Wien",
        "facts": {"rooms": "3", "area_sqm": "72", "heating_type": "Gasheizung"},
        "daily_life_lines": ["The tram stop and supermarket are within the daily-life radius."],
        "investment_lines": ["Yield confidence remains low until rent assumptions are sourced."],
        "agent_questions": ["Ask for the last 24 months of operating-cost statements."],
    }


def test_claim_extraction_marks_missing_operating_costs_with_next_action() -> None:
    claims = claims_from_deep_research(_research())
    claim = next(item for item in claims if item.claim_id == "risk.operating_cost_history_missing")

    assert claim.claim_type == "missing_fact"
    assert claim.confidence == "high"
    assert "anonymous_public" in claim.allowed_privacy_modes
    assert "24 months" in claim.next_action


def test_private_claim_bound_writer_uses_neuronwriter_gate_but_stays_disabled_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_PRIVATE_PACKET_ALLOWED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_ENABLED", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_DOSSIER_MODE", raising=False)
    claims = claims_from_deep_research(_research())
    draft = write_claim_bound_dossier(
        dossier_id="dossier-1",
        claims=claims,
        packet_kind="owner_review",
        privacy_mode="owner_private",
    )
    recommendation = recommend_for_draft(draft)

    assert draft.sections
    assert recommendation.status == "blocked"
    assert recommendation.reason == "neuronwriter_private_packet_blocked"


def test_public_market_report_can_use_neuronwriter_guard_but_stays_disabled_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_ENABLED", raising=False)
    claims = claims_from_deep_research(_research())
    draft = write_claim_bound_dossier(
        dossier_id="market-1",
        claims=claims,
        packet_kind="paid_market_report",
        privacy_mode="paid_customer",
    )
    recommendation = recommend_for_draft(draft)

    assert recommendation.status == "disabled"
    assert recommendation.reason == "neuronwriter_disabled"


def test_private_packet_neuronwriter_live_mode_uses_public_safe_topic(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_post(method: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        observed.update({"method": method, "payload": payload, "api_key": api_key})
        return {"query": "private-safe-query"}

    monkeypatch.setenv("PROPERTYQUARRY_NEURONWRITER_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_NEURONWRITER_DOSSIER_MODE", "private_public_safe")
    monkeypatch.setenv("NEURONWRITER_API_KEY", "test-key")
    monkeypatch.setattr("app.services.dossier_writer.neuronwriter_adapter._post", fake_post)
    claims = claims_from_deep_research(_research())
    draft = write_claim_bound_dossier(
        dossier_id="dossier-private",
        claims=claims,
        packet_kind="owner_review",
        privacy_mode="owner_private",
    )

    recommendation = recommend_for_draft(draft)

    assert recommendation.status == "pending"
    assert observed["method"] == "new-query"
    assert observed["api_key"] == "test-key"
    assert "Executive" in str(observed["payload"]["keyword"])
    assert "Neubauwohnung" not in str(observed["payload"]["keyword"])


def test_verifier_rejects_unsupported_salesy_claim() -> None:
    claims = claims_from_deep_research(_research())
    draft = write_claim_bound_dossier(
        dossier_id="dossier-2",
        claims=claims,
        packet_kind="owner_review",
        privacy_mode="owner_private",
    )
    draft.sections.append(
        DossierSectionDraft(
            section_key="bad_claim",
            title="Bad Claim",
            claims_used=[claims[0].claim_id],
            body_markdown="This property is guaranteed profitable and risk-free.",
        )
    )
    verified = verify_dossier_narrative(draft, claims=claims)

    assert verified.status == "rejected"
    assert verified.forbidden_hits


def test_write_verified_dossier_from_research_returns_claim_coverage() -> None:
    verified = write_verified_dossier_from_research(
        dossier_id="dossier-3",
        research=_research(),
        packet_kind="owner_review",
        privacy_mode="owner_private",
    )

    assert verified.status == "verified"
    assert verified.claim_coverage["claims_used"] > 0
    assert verified.neuronwriter is not None
    assert verified.neuronwriter.status == "blocked"
    assert verified.neuronwriter.reason == "neuronwriter_private_packet_blocked"


def test_neuronwriter_new_query_uses_official_header_and_payload(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_post(method: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        observed.update({"method": method, "payload": payload, "api_key": api_key})
        return {"query": "query-1", "query_url": "https://app.neuronwriter.com/analysis/view/query-1", "share_url": "https://share"}

    monkeypatch.setattr("app.services.dossier_writer.neuronwriter_adapter._post", fake_post)
    result = create_neuronwriter_query(
        keyword="Betriebskosten Wohnung Wien prüfen",
        project_id="propertyquarry-de",
        language="German",
        engine="google.at",
        api_key="test-key",
    )

    assert result.status == "pending"
    assert observed["method"] == "new-query"
    assert observed["api_key"] == "test-key"
    assert observed["payload"] == {
        "project": "propertyquarry-de",
        "keyword": "Betriebskosten Wohnung Wien prüfen",
        "language": "German",
        "engine": "google.at",
    }


def test_neuronwriter_get_query_normalizes_recommendations(monkeypatch) -> None:
    def fake_post(method: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        return {
            "status": "ready",
            "content_terms": [{"term": "Betriebskosten"}, {"term": "Rücklage"}],
            "h2_terms": ["Kosten prüfen"],
            "questions": ["Welche Unterlagen fehlen?"],
        }

    monkeypatch.setattr("app.services.dossier_writer.neuronwriter_adapter._post", fake_post)
    result = get_neuronwriter_query("query-1", api_key="test-key")

    assert result.status == "ready"
    assert result.terms == ["Betriebskosten", "Rücklage"]
    assert result.headings == ["Kosten prüfen"]
    assert result.questions == ["Welche Unterlagen fehlen?"]


def test_neuronwriter_query_api_blocks_private_content_without_override(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_PRIVATE_PACKET_ALLOWED", raising=False)
    context = RequestContext(principal_id="operator-local", authenticated=True, auth_source="loopback_no_auth")

    result = create_property_neuronwriter_query(
        "brief-1",
        PropertyNeuronWriterQueryIn(
            keyword="private apartment packet",
            project_id="propertyquarry-de",
            content_mode="private_packet",
        ),
        context=context,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "neuronwriter_private_or_non_public_content_blocked"


def test_dossier_write_api_returns_verified_claim_bound_payload(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_NEURONWRITER_ENABLED", raising=False)
    context = RequestContext(principal_id="operator-local", authenticated=True, auth_source="loopback_no_auth")

    result = write_property_dossier(
        "dossier-api-1",
        PropertyDossierWriteIn(
            packet_kind="owner_review",
            privacy_mode="owner_private",
            research=_research(),
        ),
        context=context,
    )

    assert result["status"] == "written"
    assert result["privacy_check"] == "passed"
    assert result["claim_coverage"]["unsupported_sentences"] == 0
    assert result["sections"]
