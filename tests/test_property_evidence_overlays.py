from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.api.routes.landing_property_research import _property_packet_evidence_overlay_rows
from app.product import property_evidence_overlays as overlays
from app.product.property_evidence_overlays import build_property_evidence_overlay_rows
from scripts.property_evidence_overlay_read_model import (
    RECEIPT_SCHEMA,
    build_ingestion_plan,
    execute_ingestion,
    verify_receipt,
)

FROZEN_EVIDENCE_NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


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
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)
    rollup_path = tmp_path / "rollups.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "media_attention",
                        "match": {"postal_code": "1020"},
                        "ui_state": "verified",
                        "summary": "12 local articles in the last 90 days, mostly transport and development.",
                        "source_name": "Terms-safe media index",
                        "source_url": "https://news.example.test/search?q=1020",
                        "article_url": "https://news.example.test/article/1",
                        "cache_updated_at": "2026-07-17T08:00:00+00:00",
                        "source_updated_at": "2026-06-24T08:00:00+00:00",
                        "source_checked_at": "2026-07-17T07:00:00+00:00",
                        "source_temporality": "current_feed",
                        "media_source_class": "independent_press",
                        "independent_press": True,
                        "uncertainty_label": "topic aggregate",
                    },
                    {
                        "layer_key": "fiber_broadband",
                        "match": {"street": "praterstrasse"},
                        "ui_state": "stale",
                        "summary": "Official fixed-line coverage says gigabit-class service may be available.",
                        "source_name": "Official broadband grid",
                        "source_url": "https://data.example.test/broadband",
                        "cache_updated_at": "2025-01-01T08:00:00+00:00",
                        "source_updated_at": "2024-12-01T08:00:00+00:00",
                        "source_temporality": "reference",
                        "reference_period": "2024",
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
    assert "does not establish source freshness or staleness" in str(
        by_key["fiber_broadband"]["detail"]
    )
    assert by_key["environmental_quality"]["ui_state"] == "unavailable"


def test_property_research_rows_preserve_evidence_states_and_original_article_link(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)
    property_url = "https://www.immobilienscout24.de/expose/altbau-u6"
    rollup_path = tmp_path / "evidence-rollups.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "media_attention",
                        "match": {"property_url": property_url},
                        "ui_state": "verified",
                        "summary": "12 local articles in the last 90 days, mostly transport and development.",
                        "source_name": "Public media index",
                        "source_url": "https://news.example.test/search/altbau-u6",
                        "article_url": "https://news.example.test/article/altbau-u6",
                        "cache_updated_at": "2026-07-17T00:00:00+00:00",
                        "source_updated_at": "2026-07-16T00:00:00+00:00",
                        "source_checked_at": "2026-07-17T00:00:00+00:00",
                        "source_temporality": "current_feed",
                        "media_source_class": "independent_press",
                        "independent_press": True,
                        "uncertainty_label": "topic aggregate",
                    },
                    {
                        "layer_key": "fiber_broadband",
                        "match": {"property_url": property_url},
                        "ui_state": "stale",
                        "summary": "The official broadband grid snapshot is waiting for an update.",
                        "source_name": "Official broadband grid",
                        "source_url": "https://broadband.example.test/altbau-u6",
                        "cache_updated_at": "2025-01-01T00:00:00+00:00",
                        "source_updated_at": "2024-12-31T00:00:00+00:00",
                        "source_temporality": "reference",
                        "reference_period": "2024",
                        "uncertainty_label": "area grid",
                    },
                    {
                        "layer_key": "environmental_quality",
                        "match": {"property_url": property_url},
                        "ui_state": "unavailable",
                        "summary": "This area layer is available for the address.",
                        "source_name": "Untrusted source",
                        "source_url": "javascript:alert(document.domain)",
                        "article_url": "data:text/html,unsafe",
                        "cache_updated_at": "2026-07-17T00:00:00+00:00",
                    },
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_READ_MODEL", "file")
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(rollup_path))

    rows = _property_packet_evidence_overlay_rows(
        facts={"property_url": property_url},
        candidate={"property_url": property_url},
    )
    by_title = {str(row["title"]): row for row in rows}

    assert len(rows) == 8
    assert by_title["Media attention"]["tag"] == "Ready"
    assert by_title["Media attention"]["href"] == "https://news.example.test/article/altbau-u6"
    assert "12 local articles" in by_title["Media attention"]["detail"]
    assert by_title["Fiber and broadband"]["tag"] == "Stale"
    assert by_title["Fiber and broadband"]["href"] == "https://broadband.example.test/altbau-u6"
    assert by_title["Environmental quality"]["tag"] == "Unavailable"
    assert "not available for this address yet" in by_title["Environmental quality"]["detail"]
    assert "is available for the address" not in by_title["Environmental quality"]["detail"]
    assert by_title["Environmental quality"].get("href", "") == ""


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://2130706433/private",
        "http://[::1]/private",
        "http://metadata.internal/private",
        "https://operator@example.com/private",
        "https://169.254.169.254\\foo",
        "http://ⓛocalhost/x",
        "http://１２７.０.０.１/x",
        "http://%6cocalhost/x",
        "http://%31%32%37.0.0.1/x",
        "http://127%2e0%2e0%2e1/x",
        "http://%256cocalhost/x",
        "http://localhost%5c.example.com/x",
    ],
)
def test_property_evidence_overlay_rejects_private_or_credentialed_links(
    unsafe_url: str,
) -> None:
    assert overlays._safe_public_http_url(unsafe_url) == ""


@pytest.mark.parametrize(
    "safe_url",
    [
        "https://news.example.test/article/1",
        "https://example.com/public",
        "https://[2606:4700:4700::1111]/public",
    ],
)
def test_property_evidence_overlay_accepts_public_links(safe_url: str) -> None:
    assert overlays._safe_public_http_url(safe_url) == safe_url


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({}, "unavailable"),
        ({"ui_state": "unknown", "cache_updated_at": "2026-07-17T00:00:00+00:00"}, "unavailable"),
        ({"ui_state": "verified"}, "unavailable"),
        ({"ui_state": "verified", "cache_updated_at": "2020-01-01T00:00:00+00:00"}, "stale"),
        ({"ui_state": "verified", "cache_updated_at": "2026-07-17T00:00:00+00:00"}, "verified"),
        ({"ui_state": "verified", "cache_updated_at": "2099-01-01T00:00:00+00:00"}, "unavailable"),
        ({"ui_state": "stale", "cache_updated_at": "2026-07-17T00:00:00+00:00"}, "stale"),
    ],
)
def test_property_evidence_overlay_state_requires_explicit_fresh_truth(
    monkeypatch,
    row: dict[str, object],
    expected: str,
) -> None:
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)

    assert overlays._state_for_rollup(row, stale_after_days=45) == expected


def test_overlay_ui_fails_unavailable_on_timezone_naive_source_provenance(
    monkeypatch,
) -> None:
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)
    layer = next(
        dict(row)
        for row in overlays.evidence_overlay_registry()["layers"]
        if row["layer_key"] == "environmental_quality"
    )

    state = overlays._state_for_rollup(
        {
            "ui_state": "verified",
            "source_temporality": "live",
            "source_updated_at": "2026-07-17T10:00:00",
            "cache_updated_at": "2026-07-17T11:00:00+00:00",
        },
        stale_after_days=45,
        layer=layer,
    )

    assert state == "unavailable"


def test_property_evidence_overlay_cache_contract_cannot_be_weakened_beyond_48_hours(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        overlays,
        "_now",
        lambda: datetime(2026, 7, 19, 12, 0, 1, tzinfo=timezone.utc),
    )

    assert overlays._state_for_rollup(
        {
            "ui_state": "verified",
            "cache_updated_at": "2026-07-17T12:00:00+00:00",
        },
        stale_after_days=45,
    ) == "stale"


def test_overlay_ui_separates_reference_period_feed_check_and_cache_expiry(
    monkeypatch,
) -> None:
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)
    registry = overlays.evidence_overlay_registry()
    layers = {
        str(layer["layer_key"]): dict(layer)
        for layer in registry["layers"]
        if isinstance(layer, dict)
    }

    reference = overlays._overlay_from_rollup(
        layers["summer_heat"],
        {
            "ui_state": "verified",
            "summary": "Published heat-atlas context.",
            "source_name": "Official heat atlas",
            "source_url": "https://data.example.test/heat",
            "source_temporality": "reference",
            "source_updated_at": "2022-06-01T00:00:00+00:00",
            "reference_period": "2021-06/2022-08",
            "cache_updated_at": "2026-07-17T10:00:00+00:00",
            "uncertainty_label": "district model",
        },
        stale_after_days=45,
    )
    assert reference["ui_state"] == "verified"
    assert reference["reference_period"] == "2021-06/2022-08"
    assert "Reference period: 2021-06/2022-08" in str(reference["detail"])
    assert "current area layer" not in str(reference["detail"])

    municipal_feed = overlays._overlay_from_rollup(
        layers["media_attention"],
        {
            "ui_state": "verified",
            "summary": "Municipal notices mentioning the district.",
            "source_name": "City notice feed",
            "source_url": "https://city.example.test/rss",
            "article_url": "https://city.example.test/notices/1",
            "source_temporality": "current_feed",
            "source_updated_at": "2026-04-17T12:00:00+00:00",
            "source_checked_at": "2026-07-17T10:00:00+00:00",
            "cache_updated_at": "2026-07-17T11:00:00+00:00",
            "media_source_class": "municipal_rss",
            "independent_press": False,
            "uncertainty_label": "municipal topic feed",
        },
        stale_after_days=45,
    )
    assert municipal_feed["ui_state"] == "verified"
    assert municipal_feed["source_updated_at"] == "2026-04-17T12:00:00+00:00"
    assert municipal_feed["source_checked_at"] == "2026-07-17T10:00:00+00:00"
    assert "Feed checked: 2026-07-17T10:00:00+00:00" in str(
        municipal_feed["detail"]
    )
    assert "not independent press" in str(municipal_feed["detail"])

    mislabeled_press = overlays._state_and_temporal_reason_for_rollup(
        {
            "ui_state": "verified",
            "source_name": "Independent publisher",
            "source_url": "https://publisher.example.test/feed",
            "article_url": "https://publisher.example.test/article/1",
            "source_temporality": "current_feed",
            "source_updated_at": "2026-07-17T09:00:00+00:00",
            "source_checked_at": "2026-07-17T10:00:00+00:00",
            "cache_updated_at": "2026-07-17T11:00:00+00:00",
            "media_source_class": "independent_press",
            "independent_press": False,
            "uncertainty_label": "publisher topic feed",
        },
        stale_after_days=45,
        layer=layers["media_attention"],
    )
    assert mislabeled_press == ("unavailable", "media_classification_invalid")

    expired_cache = overlays._overlay_from_rollup(
        layers["summer_heat"],
        {
            "ui_state": "verified",
            "summary": "Published heat-atlas context.",
            "source_name": "Official heat atlas",
            "source_url": "https://data.example.test/heat",
            "source_temporality": "reference",
            "source_updated_at": "2022-06-01T00:00:00+00:00",
            "reference_period": "2021-06/2022-08",
            "cache_updated_at": "2026-05-01T00:00:00+00:00",
            "uncertainty_label": "district model",
        },
        stale_after_days=45,
    )
    assert expired_cache["ui_state"] == "stale"
    assert expired_cache["temporal_status"] == "cache_copy_expired"
    assert "does not establish source freshness or staleness" in str(
        expired_cache["detail"]
    )


def test_property_evidence_overlays_use_listing_research_snapshot_coordinates_for_rollup_match(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(overlays, "_now", lambda: FROZEN_EVIDENCE_NOW)
    rollup_path = tmp_path / "rollups.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "summer_heat",
                        "match": {"property_coordinate": "48.2082,16.3738"},
                        "ui_state": "verified",
                        "summary": "Official heat layer marks this block as cooler than nearby dense corridors.",
                        "source_name": "Vienna climate analysis",
                        "source_url": "https://data.example.test/heat",
                        "cache_updated_at": "2026-07-16T08:00:00+00:00",
                        "source_updated_at": "2026-06-24T08:00:00+00:00",
                        "source_temporality": "reference",
                        "reference_period": "2025",
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
                        "verification_state": "verified",
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


@pytest.mark.parametrize(
    "verification_state",
    ["", "unknown", "needs_review", "stale", "flagged", "source_gap"],
)
def test_property_evidence_overlays_do_not_verify_heat_from_unverified_catalog_rows(
    tmp_path: Path,
    monkeypatch,
    verification_state: str,
) -> None:
    missing_rollup = tmp_path / "missing-rollups.json"
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(missing_rollup))

    rows = build_property_evidence_overlay_rows(
        facts={
            "official_risk_evidence": {
                "sources": [
                    {
                        "risk_key": "heat_resilience",
                        "verification_state": verification_state,
                        "summary": "The public climate dataset still needs an address-level check.",
                        "source_label": "Climate source registry",
                    }
                ]
            }
        },
        candidate={"candidate_ref": "candidate-1"},
    )
    by_key = {str(row["layer_key"]): row for row in rows}

    assert by_key["summer_heat"]["ui_state"] == "unavailable"
    assert by_key["summer_heat"]["tag"] == "Unavailable"


def test_property_evidence_overlays_accept_explicitly_verified_heat_source() -> None:
    layer = {
        "layer_key": "summer_heat",
        "title": "Summer heat",
        "teable_table": "pq_geo_summer_heat",
        "read_model": "cached_postgres_geo_rollup",
        "search_policy": "read_cached_rollup_only_no_inline_fetch",
    }

    row = overlays._derived_summer_heat_overlay(
        layer,
        {
            "official_risk_evidence": {
                "sources": [
                    {
                        "risk_key": "heat_resilience",
                        "verification_state": "needs_review",
                        "summary": "This unverified row must not shadow verified evidence.",
                        "source_label": "Unverified climate registry",
                        "source_url": "javascript:alert(document.domain)",
                    },
                    {
                        "risk_key": "heat_resilience",
                        "verification_state": "verified",
                        "summary": "The verified block-level climate layer shows moderate exposure.",
                        "source_label": "Vienna climate analysis",
                        "source_url": "https://data.gv.at/example",
                    }
                ]
            }
        },
    )

    assert row is not None
    assert row["ui_state"] == "verified"
    assert "verified block-level climate layer" in str(row["detail"])
    assert row["source_name"] == "Vienna climate analysis"
    assert row["source_url"] == "https://data.gv.at/example"
    assert "Unverified climate registry" not in str(row["detail"])


def test_property_evidence_overlays_do_not_attribute_derived_shade_to_unverified_source() -> None:
    layer = {
        "layer_key": "summer_heat",
        "title": "Summer heat",
        "teable_table": "pq_geo_summer_heat",
        "read_model": "cached_postgres_geo_rollup",
        "search_policy": "read_cached_rollup_only_no_inline_fetch",
    }

    row = overlays._derived_summer_heat_overlay(
        layer,
        {
            "tree_shade_signal": True,
            "official_risk_evidence": {
                "sources": [
                    {
                        "risk_key": "heat_resilience",
                        "verification_state": "needs_review",
                        "summary": "The registry still needs an address-level check.",
                        "source_label": "Unverified climate registry",
                        "source_url": "https://unverified.example.test/climate",
                    }
                ]
            },
        },
    )

    assert row is not None
    assert row["source_name"] == "Property facts"
    assert row["source_url"] == ""
    assert "Unverified climate registry" not in str(row["detail"])


@pytest.mark.parametrize(
    "facts",
    [
        {"tree_shade_signal": "false"},
        {"green_shade_signal": "0"},
        {"cooling_corridor_signal": "unknown"},
        {"heat_resilience_risk": "unknown"},
        {"heat_resilience_risk": "nan"},
        {"heat_resilience_risk": float("nan")},
    ],
)
def test_property_evidence_overlays_do_not_verify_unknown_or_negative_heat_signals(
    facts: dict[str, object],
) -> None:
    layer = {
        "layer_key": "summer_heat",
        "title": "Summer heat",
    }

    assert overlays._derived_summer_heat_overlay(layer, facts) is None


def test_property_evidence_rollup_exact_listing_match_cannot_be_bypassed_by_shared_area() -> None:
    lookup_values = {
        "candidate_ref": "candidate-right",
        "property_url": "https://listings.example.test/right",
        "postal_code": "1010",
    }

    assert not overlays._row_matches_candidate(
        {
            "match": {
                "property_url": "https://listings.example.test/wrong",
                "postal_code": "1010",
            }
        },
        lookup_values,
    )
    assert overlays._row_matches_candidate(
        {"match": {"postal_code": "1010"}},
        lookup_values,
    )


def test_property_evidence_overlays_prod_reads_postgres_only_and_never_derives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rollup_path = tmp_path / "legacy.json"
    rollup_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "layer_key": "summer_heat",
                        "match": {"postal_code": "1020"},
                        "summary": "Legacy file row must not be used in production.",
                        "cache_updated_at": "2026-07-15T08:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/property")
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_READ_MODEL", "file")
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH", str(rollup_path))
    monkeypatch.setattr(overlays, "_postgres_rollup_rows", lambda lookup: [])

    rows = build_property_evidence_overlay_rows(
        facts={
            "postal_code": "1020",
            "cooling_corridor_signal": "strong",
            "cooling_corridor_summary": "Inline derived evidence must not bypass the production read model.",
        },
        candidate={"candidate_ref": "candidate-prod"},
    )

    assert len(rows) == 8
    assert {row["ui_state"] for row in rows} == {"unavailable"}
    assert {row["read_model_source"] for row in rows} == {"postgres_cached_rollup_unavailable"}
    assert all("Legacy file" not in str(row["detail"]) for row in rows)
    assert all("Inline derived" not in str(row["detail"]) for row in rows)


def _complete_teable_export() -> tuple[dict[str, object], dict[str, object]]:
    registry = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json").read_text(
            encoding="utf-8"
        )
    )
    tables: dict[str, list[dict[str, object]]] = {}
    for index, layer in enumerate(registry["layers"]):
        layer_key = str(layer["layer_key"])
        table_name = str(layer["teable_table"])
        fields: dict[str, object] = {
            "match": {"street": f"launch street {index}"},
            "summary": f"Verified {layer_key} context.",
            "source_name": f"Official {layer_key} source",
            "source_url": f"https://data.example.test/{layer_key}",
            "source_updated_at": "2026-07-16T10:00:00+00:00",
            "cache_updated_at": "2026-07-16T11:00:00+00:00",
            "uncertainty_label": "area aggregate",
            "ui_state": "verified",
        }
        temporalities = set(layer["allowed_source_temporalities"])
        if "current_feed" in temporalities:
            fields["source_temporality"] = "current_feed"
            fields["source_checked_at"] = "2026-07-16T10:30:00+00:00"
        elif "live" in temporalities:
            fields["source_temporality"] = "live"
        else:
            fields["source_temporality"] = "reference"
            fields["reference_period"] = "2025"
        if layer_key == "media_attention":
            fields["article_url"] = "https://news.example.test/article/launch-proof"
            fields["media_source_class"] = "independent_press"
            fields["independent_press"] = True
        if layer_key == "official_safety_context":
            fields["geographic_scope"] = "district_aggregate"
            fields["rights_caveat"] = "Reuse subject to official source terms."
            fields["property_scoring"] = False
            fields["person_scoring"] = False
        tables[table_name] = [{"id": f"rec-{index}", "fields": fields}]
    source_tables = {
        table_name: {
            "table_id_sha256": f"{index + 1:064x}",
            "record_count": len(rows),
            "page_count": 1,
            "pages": [
                {
                    "status_code": 200,
                    "response_sha256": f"{index + 101:064x}",
                    "size_bytes": 128,
                }
            ],
        }
        for index, (table_name, rows) in enumerate(sorted(tables.items()))
    }
    return (
        {
            "schema": "propertyquarry.evidence_overlay_teable_export.v1",
            "generated_at": "2026-07-16T11:05:00+00:00",
            "tables": tables,
            "source_evidence": {
                "mode": "authenticated_teable_api",
                "auth_kind": "bearer_api_key",
                "secret_in_export": False,
                "base_origin": "https://app.teable.io",
                "base_id_sha256": "a" * 64,
                "redirects_followed": False,
                "table_discovery": {
                    "status_code": 200,
                    "response_sha256": "b" * 64,
                    "size_bytes": 256,
                },
                "tables": source_tables,
            },
        },
        registry,
    )


class _FakeOverlayRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.active_id = "f" * 64
        self.staged_id = ""

    def ensure_schema(self) -> None:
        return None

    def active_snapshot_id(self) -> str:
        return self.active_id

    def stage_snapshot(self, **kwargs: object) -> None:
        self.records = [dict(row) for row in list(kwargs.get("records") or []) if isinstance(row, dict)]
        self.staged_id = str(kwargs["snapshot_id"])

    def coverage(self, *, snapshot_id: str = "") -> list[dict[str, object]]:
        del snapshot_id
        return [
            {
                "layer_key": str(row["layer_key"]),
                "teable_table": str(row["teable_table"]),
                "record_count": 1,
                "latest_cache_updated_at": str(row["cache_updated_at"]),
                "latest_ingested_at": "2026-07-16T12:00:00+00:00",
            }
            for row in self.records
        ]

    def lookup(
        self,
        lookup: dict[str, str],
        *,
        snapshot_id: str = "",
    ) -> list[dict[str, object]]:
        del snapshot_id
        return [
            dict(row.get("payload") or {})
            for row in self.records
            if any(str(dict(row.get("match") or {}).get(key) or "") == value for key, value in lookup.items())
        ]

    def benchmark_samples(self, *, snapshot_id: str) -> list[tuple[str, dict[str, str]]]:
        assert snapshot_id == self.staged_id
        return [
            (str(row["layer_key"]), dict(row["match"]))
            for row in self.records
        ]

    def discard_staged_snapshot(self, snapshot_id: str) -> None:
        assert snapshot_id == self.staged_id
        self.staged_id = ""


def test_evidence_overlay_ingestion_proves_all_eight_teable_postgres_layers() -> None:
    export, registry = _complete_teable_export()
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    candidate_sha = "a" * 40
    plan = build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=candidate_sha,
        max_age_hours=48,
        expected_teable_origin="https://app.teable.io",
        expected_teable_base_id_sha256="a" * 64,
        now=now,
    )
    assert plan["status"] == "pass", plan["failures"]
    assert plan["layer_count"] == 8
    assert len(plan["records"]) == 8

    receipt = execute_ingestion(
        plan=plan,
        repository=_FakeOverlayRepository(),  # type: ignore[arg-type]
        candidate_sha=candidate_sha,
        max_query_ms=100,
        stage_only=True,
        observed_at=now,
    )

    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["status"] == "pass", receipt["failures"]
    assert receipt["ingestion"]["source"] == "authenticated_teable_api_export"
    assert receipt["ingestion"]["target"] == "postgres_cached_geo_rollup"
    assert receipt["read_model"]["sample_layer_count"] == 8
    assert receipt["read_model"]["source_fetch_during_search"] is False
    assert (
        verify_receipt(
            receipt,
            expected_candidate_sha=candidate_sha,
            max_age_hours=48,
            expected_teable_origin="https://app.teable.io",
            expected_teable_base_id_sha256="a" * 64,
            expected_phase="staged",
            now=now,
        )
        == []
    )

    tampered = json.loads(json.dumps(receipt))
    tampered["source_evidence"]["secret_in_export"] = True
    assert "Teable export authentication evidence is invalid" in verify_receipt(
        tampered,
        expected_candidate_sha=candidate_sha,
        max_age_hours=48,
        expected_teable_origin="https://app.teable.io",
        expected_teable_base_id_sha256="a" * 64,
        expected_phase="staged",
        now=now,
    )


def test_evidence_overlay_ingestion_fails_closed_on_missing_layer_and_stale_rows() -> None:
    export, registry = _complete_teable_export()
    tables = dict(export["tables"])
    tables.pop("pq_geo_traffic_noise")
    first_table = sorted(tables)[0]
    tables[first_table][0]["fields"]["cache_updated_at"] = "2025-01-01T00:00:00+00:00"
    export["tables"] = tables

    plan = build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha="b" * 40,
        max_age_hours=48,
        expected_teable_origin="https://app.teable.io",
        expected_teable_base_id_sha256="a" * 64,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert plan["status"] == "fail"
    failures = "\n".join(plan["failures"])
    assert "missing required tables" in failures
    assert "older than 48 hours" in failures
