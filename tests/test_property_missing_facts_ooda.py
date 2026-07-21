from app.api.routes.landing import (
    _property_distance_ooda_rows_for_preferences,
    _property_packet_everyday_fit_rows,
    _property_packet_missing_rows,
    _property_rooms_display,
)
from app.product.service import _property_enrich_missing_fact_research, _property_justiz_edikte_facts


def test_missing_rooms_with_floorplan_creates_ooda_research_item() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True, "floorplan_count": 1, "sale_channel": "judicial_auction"},
        property_url="https://edikte2.justiz.gv.at/example",
        title="Auction apartment",
        summary="Good floorplan evidence but no structured room count.",
    )

    assert facts["rooms_label"] == "Rooms under research"
    assert facts["rooms_research_status"] == "queued_missing_fact_ooda"
    assert facts["missing_facts_json"] == ["rooms"]
    research = facts["missing_fact_research"]
    assert research["status"] == "queued"
    assert research["items"][0]["field"] == "rooms"
    assert research["items"][0]["ooda"]["act"].startswith("Queue missing-fact research")
    assert _property_rooms_display(facts) == ""


def test_missing_rooms_ooda_fills_medium_confidence_room_count_from_text() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True, "floorplan_count": 1},
        property_url="https://example.test/listing",
        title="3 Zimmer Wohnung mit Grundriss",
        summary="Wohnung mit Balkon.",
    )

    assert facts["rooms"] == 3
    assert facts["rooms_label"] == "3 rooms"
    assert facts["rooms_research_status"] == "filled_by_missing_fact_ooda"
    assert facts["missing_fact_research"]["status"] == "completed"
    assert facts["missing_fact_research"]["items"][0]["status"] == "filled"
    assert "missing_facts_json" not in facts


def test_justiz_edikte_parser_extracts_rooms_when_text_contains_room_fact() -> None:
    facts = _property_justiz_edikte_facts(
        "https://edikte2.justiz.gv.at/edikte/ex/example",
        "<html><title>Edikt</title></html>",
        "Schätzwert EUR 300.000. Die Wohnung hat 4 Zimmer und 91 m² Wohnfläche.",
    )

    assert facts["provider_channel"] == "justiz_edikte_at"
    assert facts["rooms"] == 4
    assert facts["rooms_label"] == "4 rooms"


def test_packet_missing_rows_surface_missing_fact_ooda() -> None:
    facts = _property_enrich_missing_fact_research(
        facts={"has_floorplan": True},
        property_url="https://example.test/floorplan.zip",
        title="Floorplan bundle",
        summary="No structured room count.",
    )

    rows = _property_packet_missing_rows(facts=facts, preferences={"min_rooms": 3})

    assert any(row["title"] == "Rooms" and row["tag"] == "To check" for row in rows)


def test_packet_missing_rows_treats_nearest_supermarket_alias_as_known() -> None:
    rows = _property_packet_missing_rows(
        facts={"nearest_supermarket_m": 340},
        preferences={"max_distance_to_supermarket_m": 700},
    )

    assert not any(row["title"] == "Supermarket distance" for row in rows)


def test_family_only_distance_rows_stay_hidden_without_family_context() -> None:
    facts = {
        "nearest_playground_m": 250,
        "nearest_library_m": 500,
        "nearest_medical_care_m": 800,
        "nearest_supermarket_m": 300,
    }

    ooda_rows = _property_distance_ooda_rows_for_preferences(facts, {})
    titles = {row["title"] for row in ooda_rows}

    assert "Nearest playground" not in titles
    assert "Nearest library" not in titles
    assert "Nearest medical care" not in titles
    assert "Nearest supermarket" in titles

    everyday_rows = _property_packet_everyday_fit_rows(facts=facts, preferences={})
    everyday_titles = {row["title"] for row in everyday_rows}

    assert "Playground" not in everyday_titles
    assert "Library" not in everyday_titles
    assert "Medical care" not in everyday_titles
    assert "Supermarket" in everyday_titles


def test_family_only_distance_rows_return_with_family_mode() -> None:
    facts = {
        "nearest_playground_m": 250,
        "nearest_library_m": 500,
        "nearest_medical_care_m": 800,
    }
    preferences = {"enable_family_mode": True}

    ooda_rows = _property_distance_ooda_rows_for_preferences(facts, preferences)
    titles = {row["title"] for row in ooda_rows}
    assert "Nearest playground" in titles
    assert "Nearest library" in titles
    assert "Nearest medical care" in titles

    everyday_rows = _property_packet_everyday_fit_rows(facts=facts, preferences=preferences)
    everyday_titles = {row["title"] for row in everyday_rows}
    assert "Playground" in everyday_titles
    assert "Library" in everyday_titles
    assert "Medical care" in everyday_titles
