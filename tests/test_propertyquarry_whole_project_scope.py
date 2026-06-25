from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_whole_project_scope_tracks_gold_blocker_extensions() -> None:
    scope = (ROOT / "docs/PROPERTYQUARRY_WHOLE_PROJECT_SCOPE.md").read_text(encoding="utf-8")
    manifest = (ROOT / "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md").read_text(encoding="utf-8")

    required_scope_tokens = (
        "Whole-project gold must include implemented, customer-visible evidence overlays",
        "Teable ingestion table",
        "media-attention statistics with article links",
        "fiber/broadband coverage",
        "Rybbit dashboard receipts",
        "visual quality and accessibility",
        "runtime security, supply chain, and authorization",
    )
    required_manifest_tokens = (
        "Evidence-map overlays remain a whole-project gold blocker",
        "Rybbit remains a whole-project gold blocker",
        "Release hardening remains a whole-project gold blocker",
        "Production security remains a whole-project gold blocker",
        "SBOM",
        "durable RBAC/session revocation",
    )

    for token in required_scope_tokens:
        assert token in scope
    for token in required_manifest_tokens:
        assert token in manifest


def test_evidence_overlay_registry_tracks_required_gold_layers() -> None:
    registry = json.loads((ROOT / "docs/PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json").read_text(encoding="utf-8"))
    layers = {row["layer_key"]: row for row in registry["layers"]}

    assert set(layers) == {
        "environmental_quality",
        "summer_heat",
        "traffic_noise",
        "public_mobility",
        "school_context",
        "official_safety_context",
        "media_attention",
        "fiber_broadband",
    }
    for layer in layers.values():
        assert layer["ingestion_mode"] == "async_teable_job"
        assert layer["read_model"] == "cached_postgres_geo_rollup"
        assert layer["search_policy"] == "read_cached_rollup_only_no_inline_fetch"
        assert {"unavailable", "stale", "verified"}.issubset(set(layer["ui_states"]))
        assert str(layer["teable_table"]).startswith("pq_geo_")
    assert layers["media_attention"]["article_links_required"] is True
    assert "article_url" in layers["media_attention"]["provenance_fields"]
    assert "never property or person scoring" in layers["official_safety_context"]["customer_framing"]
    assert "provider address checks only as secondary verified jobs" in layers["fiber_broadband"]["customer_framing"]


def test_whole_project_scope_checker_enforces_overlay_registry() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_whole_project_scope.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ok: property whole-project scope" in result.stdout
