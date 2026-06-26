#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE_DOC = ROOT / "docs" / "PROPERTYQUARRY_WHOLE_PROJECT_SCOPE.md"
OVERLAY_REGISTRY = ROOT / "docs" / "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json"

REQUIRED_OVERLAY_LAYERS = {
    "environmental_quality",
    "summer_heat",
    "traffic_noise",
    "public_mobility",
    "school_context",
    "official_safety_context",
    "media_attention",
    "fiber_broadband",
}

REQUIRED_PHRASES = (
    "Public entry and SEO surfaces",
    "Authentication, logout, account, sessions, data export, deletion, and share-link revocation",
    "Search setup, district and postal-code filtering, hard versus soft filter behavior",
    "Search execution, source coverage, fleet repair, retry state, ETA state",
    "Results, filtered-breakdown actions, rank ordering",
    "Research detail, 360 tours, Matterport and 3DVista links",
    "Automation and saved searches, including map thumbnails",
    "Provider governance, market readiness, rights, rate limits",
    "Canonical property memory",
    "Ranking and learning",
    "Notifications, scout thresholds",
    "Billing, invoices, VAT, refunds",
    "Privacy, prompt-injection boundaries",
    "Accessibility, responsive layout",
    "Observability: SLOs",
    "Documentation, help center, legal pages",
    "Integration governance for LTD/provider lanes",
    "Audit prose alone is not done",
    "one canonical property identity",
)

FORBIDDEN_PHRASES = (
    "Executive Assistant",
    "Morning Memo",
    "office loop",
)


def _check_overlay_registry(failures: list[str]) -> None:
    if not OVERLAY_REGISTRY.exists():
        failures.append("docs/PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json must define evidence overlay gold contract")
        return
    try:
        registry = json.loads(OVERLAY_REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append(f"evidence overlay registry must be valid JSON: {exc}")
        return
    if registry.get("contract_name") != "propertyquarry.evidence_overlay_registry.v1":
        failures.append("evidence overlay registry must declare contract_name propertyquarry.evidence_overlay_registry.v1")
    policy = registry.get("gold_policy") if isinstance(registry.get("gold_policy"), dict) else {}
    if policy.get("search_execution_policy") != "cached_rollups_only_no_inline_source_indexing":
        failures.append("evidence overlay registry must forbid inline source indexing during search")
    if policy.get("ingestion_policy") != "async_teable_first_then_cached_read_model":
        failures.append("evidence overlay registry must require async Teable-first ingestion")
    layers = [row for row in list(registry.get("layers") or []) if isinstance(row, dict)]
    by_key = {str(row.get("layer_key") or "").strip(): row for row in layers}
    missing_layers = sorted(REQUIRED_OVERLAY_LAYERS - set(by_key))
    if missing_layers:
        failures.append(f"evidence overlay registry missing required layers: {', '.join(missing_layers)}")
    for layer_key in sorted(REQUIRED_OVERLAY_LAYERS & set(by_key)):
        row = by_key[layer_key]
        prefix = f"evidence overlay {layer_key}"
        if not str(row.get("source_registry") or "").strip():
            failures.append(f"{prefix} must declare source_registry")
        if not str(row.get("teable_table") or "").strip().startswith("pq_geo_"):
            failures.append(f"{prefix} must declare a pq_geo_* Teable table")
        if row.get("ingestion_mode") != "async_teable_job":
            failures.append(f"{prefix} must use async_teable_job ingestion")
        if row.get("read_model") != "cached_postgres_geo_rollup":
            failures.append(f"{prefix} must use cached_postgres_geo_rollup read model")
        if row.get("search_policy") != "read_cached_rollup_only_no_inline_fetch":
            failures.append(f"{prefix} must forbid inline fetches during search")
        ui_states = {str(value) for value in list(row.get("ui_states") or [])}
        if not {"unavailable", "stale", "verified"}.issubset(ui_states):
            failures.append(f"{prefix} must expose unavailable, stale, and verified UI states")
        provenance = {str(value) for value in list(row.get("provenance_fields") or [])}
        if not {"source_name", "source_url", "source_updated_at", "cache_updated_at", "uncertainty_label"}.issubset(provenance):
            failures.append(f"{prefix} must expose source, freshness, cache, and uncertainty provenance")
        if layer_key == "media_attention":
            if row.get("article_links_required") is not True or "article_url" not in provenance:
                failures.append("media_attention overlay must require original article links when available")
        if layer_key == "official_safety_context" and "never property or person scoring" not in str(row.get("customer_framing") or ""):
            failures.append("official_safety_context overlay must forbid property/person scoring")
        if layer_key == "fiber_broadband" and "provider address checks only as secondary verified jobs" not in str(row.get("customer_framing") or ""):
            failures.append("fiber_broadband overlay must keep provider checks secondary to official coverage")


def build_scope_receipt() -> dict[str, object]:
    failures: list[str] = []
    if not SCOPE_DOC.exists():
        failures.append("docs/PROPERTYQUARRY_WHOLE_PROJECT_SCOPE.md must define whole-product scope")
    else:
        body = SCOPE_DOC.read_text(encoding="utf-8")
        for phrase in REQUIRED_PHRASES:
            if phrase not in body:
                failures.append(f"whole-project scope is missing required phrase: {phrase}")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in body:
                failures.append(f"whole-project scope uses inherited generic copy: {phrase}")
        if "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json" not in body:
            failures.append("whole-project scope must reference PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json")

    _check_overlay_registry(failures)

    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")
    if "scripts/check_property_whole_project_scope.py" not in release_gate:
        failures.append("property_release_gates.sh must run check_property_whole_project_scope.py")

    return {
        "schema": "propertyquarry.whole_project_scope_receipt.v1",
        "status": "pass" if not failures else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope_doc": str(SCOPE_DOC.relative_to(ROOT)),
        "evidence_overlay_registry": str(OVERLAY_REGISTRY.relative_to(ROOT)),
        "required_overlay_layers": sorted(REQUIRED_OVERLAY_LAYERS),
        "required_phrase_count": len(REQUIRED_PHRASES),
        "forbidden_phrase_count": len(FORBIDDEN_PHRASES),
        "release_gate": "scripts/property_release_gates.sh",
        "failures": failures,
        "notes": [
            "This receipt proves the whole-project scope contract and evidence-overlay registry shape.",
            "It does not replace runtime/mobile/provider/tour receipts; gold status must combine all gates.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PropertyQuarry whole-project scope and evidence-overlay registry contracts.")
    parser.add_argument("--write", default="")
    args = parser.parse_args()

    receipt = build_scope_receipt()
    failures = list(receipt.get("failures") or [])
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        print("property whole-project scope check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("ok: property whole-project scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
