from __future__ import annotations

import json
from pathlib import Path

from app.product.property_evidence_overlays import build_property_evidence_overlay_rows


def test_property_evidence_overlays_fail_closed_when_no_cached_rollup(tmp_path: Path, monkeypatch) -> None:
    missing_rollup = tmp_path / "missing-rollups.json"
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(missing_rollup))

    rows = build_property_evidence_overlay_rows(
        facts={"postal_code": "1020", "street": "Praterstrasse"},
        candidate={"candidate_ref": "candidate-1"},
    )

    assert len(rows) == 8
    assert {row["ui_state"] for row in rows} == {"unavailable"}
    assert all(row["search_policy"] == "read_cached_rollup_only_no_inline_fetch" for row in rows)
    assert all("not available for this address yet" in str(row["detail"]) for row in rows)
    assert all("crawl" not in str(row["detail"]).lower() for row in rows)
    assert all("index" not in str(row["detail"]).lower() for row in rows)


def test_property_evidence_overlays_read_verified_and_stale_cached_rollups(tmp_path: Path, monkeypatch) -> None:
    rollup_path = tmp_path / "rollups.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "media_attention",
                        "match": {"postal_code": "1020"},
                        "summary": "12 local articles in the last 90 days, mostly transport and development.",
                        "source_name": "Terms-safe media index",
                        "source_url": "https://news.example.test/search?q=1020",
                        "article_url": "https://news.example.test/article/1",
                        "cache_updated_at": "2026-06-25T08:00:00+00:00",
                        "source_updated_at": "2026-06-24T08:00:00+00:00",
                        "uncertainty_label": "topic aggregate",
                    },
                    {
                        "layer_key": "fiber_broadband",
                        "match": {"street": "praterstrasse"},
                        "summary": "Official fixed-line coverage says gigabit-class service may be available.",
                        "source_name": "Official broadband grid",
                        "cache_updated_at": "2025-01-01T08:00:00+00:00",
                        "uncertainty_label": "area grid",
                    },
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(rollup_path))

    rows = build_property_evidence_overlay_rows(
        facts={"postal_code": "1020", "street": "Praterstrasse"},
        candidate={"candidate_ref": "candidate-1"},
    )
    by_key = {str(row["layer_key"]): row for row in rows}

    assert by_key["media_attention"]["ui_state"] == "verified"
    assert by_key["media_attention"]["tag"] == "Ready"
    assert by_key["media_attention"]["article_url"] == "https://news.example.test/article/1"
    assert "12 local articles" in str(by_key["media_attention"]["detail"])
    assert by_key["media_attention"]["source_name"] == "Media index"
    assert "Terms-safe" not in str(by_key["media_attention"]["detail"])
    assert "uncertainty:" not in str(by_key["media_attention"]["detail"]).lower()
    assert by_key["fiber_broadband"]["ui_state"] == "stale"
    assert by_key["fiber_broadband"]["tag"] == "Stale"
    assert "Update pending" in str(by_key["fiber_broadband"]["detail"])
    assert by_key["environmental_quality"]["ui_state"] == "unavailable"


def test_property_evidence_overlays_use_listing_research_snapshot_coordinates_for_rollup_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rollup_path = tmp_path / "rollups.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "summer_heat",
                        "match": {"property_coordinate": "48.2082,16.3738"},
                        "summary": "Official heat layer marks this block as cooler than nearby dense corridors.",
                        "source_name": "Vienna climate analysis",
                        "cache_updated_at": "2026-06-25T08:00:00+00:00",
                        "uncertainty_label": "block-level climate layer",
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(rollup_path))

    rows = build_property_evidence_overlay_rows(
        facts={
            "listing_research_snapshot": {
                "map_lat": 48.2082,
                "map_lng": 16.3738,
            }
        },
        candidate={"candidate_ref": "candidate-1"},
    )
    by_key = {str(row["layer_key"]): row for row in rows}

    assert by_key["summer_heat"]["ui_state"] == "verified"
    assert "cooler than nearby dense corridors" in str(by_key["summer_heat"]["detail"])


def test_property_evidence_overlays_derive_summer_heat_row_from_attached_climate_facts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    missing_rollup = tmp_path / "missing-rollups.json"
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(missing_rollup))

    rows = build_property_evidence_overlay_rows(
        facts={
            "cooling_corridor_signal": "strong",
            "cooling_corridor_summary": "Nearby flowing water (Donaukanal, about 260 m) can soften summer heat and supports the local cooling-corridor read.",
            "official_risk_evidence": {
                "sources": [
                    {
                        "risk_key": "cooling_corridor",
                        "source_label": "Flowing-water proximity",
                        "source_url": "https://www.openstreetmap.org/copyright",
                    }
                ]
            },
        },
        candidate={"candidate_ref": "candidate-1"},
    )
    by_key = {str(row["layer_key"]): row for row in rows}

    assert by_key["summer_heat"]["ui_state"] == "verified"
    assert "Donaukanal" in str(by_key["summer_heat"]["detail"])
    assert "microclimate hint (strong)" in str(by_key["summer_heat"]["detail"])
    assert by_key["summer_heat"]["source_url"] == "https://www.openstreetmap.org/copyright"
