from __future__ import annotations

from collections.abc import Mapping

from app.services.dossier_writer.models import DossierEvidenceClaim


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _claim(
    claim_id: str,
    section_key: str,
    claim_text: str,
    claim_type: str,
    *,
    confidence: str = "medium",
    source_ref: str = "propertyquarry_deep_research",
    next_action: str = "",
    public: bool = False,
) -> DossierEvidenceClaim:
    allowed = ["owner_private", "family_review", "agent_share"]
    if public:
        allowed.extend(["paid_customer", "anonymous_public"])
    return DossierEvidenceClaim(
        claim_id=claim_id,
        section_key=section_key,
        claim_text=claim_text,
        claim_type=claim_type,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        source_refs=[source_ref],
        source_labels=[source_ref.replace("_", " ").title()],
        allowed_privacy_modes=allowed,  # type: ignore[arg-type]
        forbidden_privacy_modes=[] if public else ["anonymous_public"],
        next_action=next_action,
    )


def claims_from_deep_research(result: Mapping[str, object]) -> list[DossierEvidenceClaim]:
    facts = result.get("facts") if isinstance(result.get("facts"), Mapping) else {}
    facts = dict(facts or {})
    claims: list[DossierEvidenceClaim] = []
    title = _text(result.get("title") or facts.get("title") or facts.get("listing_title"))
    if title:
        claims.append(_claim("fact.title", "evidence_summary", f"Listing title: {title}.", "fact", confidence="high", public=True))
    for key, label in (
        ("price", "Asking price"),
        ("area_sqm", "Living area"),
        ("rooms", "Room count"),
        ("heating_type", "Heating type"),
        ("energy_certificate", "Energy certificate"),
        ("operating_costs_monthly", "Monthly operating costs"),
    ):
        value = _text(facts.get(key))
        if value:
            claims.append(_claim(f"fact.{key}", "evidence_summary", f"{label}: {value}.", "fact", confidence="high", public=key in {"area_sqm", "rooms"}))
    if not _text(facts.get("operating_costs_monthly") or facts.get("operating_costs")):
        claims.append(
            _claim(
                "risk.operating_cost_history_missing",
                "risk_register",
                "Operating-cost history is not yet available.",
                "missing_fact",
                confidence="high",
                next_action="Ask the agent for the last 24 months of operating-cost statements.",
                public=True,
            )
        )
    if not _text(facts.get("heating_type") or facts.get("heating")):
        claims.append(
            _claim(
                "risk.heating_source_unclear",
                "risk_register",
                "Heating source is still missing.",
                "missing_fact",
                confidence="medium",
                next_action="Ask the agent to confirm heating source and billing treatment.",
                public=True,
            )
        )
    for index, value in enumerate(list(result.get("risk_lines") or []), start=1):
        text = _text(value)
        if text:
            claims.append(_claim(f"risk.deep_research.{index}", "risk_register", text, "risk", confidence="medium"))
    for index, value in enumerate(list(result.get("agent_questions") or []), start=1):
        text = _text(value)
        if text:
            claims.append(_claim(f"question.agent.{index}", "agent_questions", text, "agent_question", confidence="high", next_action=text))
    for index, value in enumerate(list(result.get("daily_life_lines") or []), start=1):
        text = _text(value)
        if text:
            claims.append(_claim(f"location.daily_life.{index}", "daily_life_radius", text, "location_signal", confidence="medium", public=True))
    for index, value in enumerate(list(result.get("investment_lines") or []), start=1):
        text = _text(value)
        if text:
            claims.append(_claim(f"investment.assumption.{index}", "investment_read", text, "investment_assumption", confidence="low"))
    return claims
