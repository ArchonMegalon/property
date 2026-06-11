from __future__ import annotations

from app.services.dossier_writer.models import DossierOutline, DossierOutlineSection, DossierPacketKind


OWNER_REVIEW = (
    ("executive_decision", "Executive Decision", ["fact", "risk", "missing_fact"]),
    ("evidence_summary", "Evidence Summary", ["fact"]),
    ("media_3d_tour", "Media / 3D Tour", ["fact"]),
    ("daily_life_radius", "Daily-Life Radius", ["location_signal"]),
    ("risk_register", "Risk Register", ["risk", "missing_fact"]),
    ("investment_read", "Investment Read", ["investment_assumption"]),
    ("agent_questions", "Agent Questions", ["agent_question", "missing_fact"]),
)

PAID_MARKET_REPORT = (
    ("market_thesis", "Market Thesis", ["fact", "location_signal"]),
    ("pricing_signals", "Pricing Signals", ["fact", "investment_assumption"]),
    ("risk_categories", "Risk Categories", ["risk", "missing_fact"]),
    ("methodology", "Methodology", ["fact"]),
)


def plan_dossier_outline(packet_kind: DossierPacketKind) -> DossierOutline:
    rows = PAID_MARKET_REPORT if packet_kind in {"paid_market_report", "public_city_guide"} else OWNER_REVIEW
    return DossierOutline(
        packet_kind=packet_kind,
        sections=[
            DossierOutlineSection(section_key=key, title=title, claim_types=list(claim_types))  # type: ignore[arg-type]
            for key, title, claim_types in rows
        ],
    )
