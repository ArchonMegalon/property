from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.product import property_evidence_overlays as overlays
from app.product.property_evidence_overlays import build_property_evidence_overlay_rows
from scripts.property_evidence_overlay_read_model import (
    RECEIPT_SCHEMA,
    build_ingestion_plan,
    execute_ingestion,
    verify_receipt,
)


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
            "source_updated_at": "2026-07-15T10:00:00+00:00",
            "cache_updated_at": "2026-07-15T11:00:00+00:00",
            "uncertainty_label": "area aggregate",
            "ui_state": "verified",
        }
        if layer_key == "media_attention":
            fields["article_url"] = "https://news.example.test/article/launch-proof"
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
            "generated_at": "2026-07-15T11:05:00+00:00",
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
