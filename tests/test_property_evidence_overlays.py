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
    assert all("did not crawl or index this source inline" in str(row["detail"]) for row in rows)


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
    assert by_key["media_attention"]["tag"] == "Verified"
    assert by_key["media_attention"]["article_url"] == "https://news.example.test/article/1"
    assert "12 local articles" in str(by_key["media_attention"]["detail"])
    assert by_key["fiber_broadband"]["ui_state"] == "stale"
    assert by_key["fiber_broadband"]["tag"] == "Stale"
    assert by_key["environmental_quality"]["ui_state"] == "unavailable"
