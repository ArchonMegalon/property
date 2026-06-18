from __future__ import annotations

from app.domain.property.content_source_packet import (
    CONTENT_MODE_PRODUCT_TUTORIAL,
    build_property_content_source_packet,
    sha256_json,
)


def build_product_tutorial_source_packet(*, title: str, language: str = "en", jurisdiction: str = "GLOBAL") -> dict[str, object]:
    sources = [
        {
            "source_type": "product_documentation",
            "title": "PropertyQuarry product surface",
            "observed_at": "",
            "sha256": sha256_json({"fixture": "propertyquarry_product_docs", "title": title}),
        }
    ]
    return build_property_content_source_packet(
        packet_id=f"pq-product-tutorial-{sha256_json({'title': title})[:12]}",
        content_mode=CONTENT_MODE_PRODUCT_TUTORIAL,
        title=title,
        language=language,
        jurisdiction=jurisdiction,
        audience="PropertyQuarry user",
        target_words=650,
        facts={"product": "PropertyQuarry", "disclosure": "educational product tutorial"},
        allowed_claims=[
            "This script explains how to use PropertyQuarry.",
            "Examples must use synthetic or public-safe fixtures.",
        ],
        unknowns=["Current UI screenshots must be rechecked before recording."],
        sources=sources,
        research_policy="approved_sources_only",
    )


def build_synthetic_dossier_source_packet() -> dict[str, object]:
    snapshot = {
        "run_id": "synthetic-run",
        "candidate_ref": "synthetic-candidate",
        "snapshot_sha256": sha256_json({"synthetic": "property-dossier"}),
        "observed_at": "2026-06-18T10:00:00Z",
        "source_label": "Synthetic fixture",
        "source_url": "",
        "listing_status": "active",
    }
    return build_property_content_source_packet(
        packet_id="pq-synthetic-dossier-demo",
        content_mode="PROPERTY_DOSSIER",
        title="Why this listing matched and what is still missing",
        language="en",
        jurisdiction="AT",
        audience="prospective renter",
        property_snapshot=snapshot,
        facts={
            "location_label": "Vienna fixture district",
            "price_display": "EUR 1,450",
            "area_display": "82 m2",
            "rooms_display": "3",
            "tour_status": "ready",
            "lift": "reported",
        },
        fit={
            "fit_score": 92,
            "summary": "Lift, transit and room count fit the approved brief.",
            "approved_preferences": ["lift required", "public transit important", "three bedrooms preferred"],
        },
        ooda={
            "observe": ["Lift reported", "Transit access researched"],
            "orient": "Strong fit against approved priorities.",
            "decide": "Keep for viewing review.",
            "act": "Verify heating and building reserves.",
        },
        risks=[{"severity": "medium", "finding": "Heating details are missing."}],
        unknowns=["Heating system", "Current reserve fund", "Noise exposure at peak hours"],
        sources=[
            {
                "source_type": "synthetic_listing",
                "url": "",
                "observed_at": "2026-06-18T10:00:00Z",
                "sha256": snapshot["snapshot_sha256"],
            }
        ],
        allowed_claims=[
            "This listing received a fit score of 92 in this search run.",
            "Heating details were not available in the reviewed source.",
        ],
        research_policy="provided_sources_only",
    )

