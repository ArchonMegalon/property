from __future__ import annotations

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

