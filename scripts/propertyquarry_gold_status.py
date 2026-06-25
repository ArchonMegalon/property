#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_TOUR_PROVIDER_MODES = ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "missing", "path": str(path)}
    except Exception as exc:
        return {"status": "invalid", "path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, dict):
        return {"status": "invalid", "path": str(path), "error": "json_root_not_object"}
    return payload


def _missing_provider_modes(tour_receipt: dict[str, Any]) -> list[str]:
    ready = {
        str(provider or "").strip().lower()
        for provider in list(tour_receipt.get("ready_provider_modes") or [])
        if str(provider or "").strip()
    }
    missing = [
        provider
        for provider in REQUIRED_TOUR_PROVIDER_MODES
        if provider not in ready
    ]
    explicit_missing = [
        str(provider or "").strip().lower()
        for provider in list(tour_receipt.get("missing_provider_modes") or [])
        if str(provider or "").strip().lower() in REQUIRED_TOUR_PROVIDER_MODES
    ]
    for provider in explicit_missing:
        if provider not in missing:
            missing.append(provider)
    return missing


def build_gold_status_receipt(
    *,
    performance_receipt_path: Path,
    tour_control_receipt_path: Path,
    export_discovery_receipt_path: Path,
    import_manifest_receipt_path: Path | None = None,
    repair_canary_receipt_path: Path,
    provider_matrix_receipt_path: Path,
    live_mobile_receipt_path: Path | None = None,
) -> dict[str, Any]:
    performance = _load_json(performance_receipt_path)
    live_mobile = _load_json(live_mobile_receipt_path) if live_mobile_receipt_path is not None else {}
    tour_controls = _load_json(tour_control_receipt_path)
    export_discovery = _load_json(export_discovery_receipt_path)
    import_manifest = _load_json(import_manifest_receipt_path) if import_manifest_receipt_path is not None else {}
    repair_canary = _load_json(repair_canary_receipt_path)
    provider_matrix = _load_json(provider_matrix_receipt_path)

    missing_provider_modes = _missing_provider_modes(tour_controls)
    provider_matrix_summary = dict(provider_matrix.get("targeted_search_matrix_summary") or {})
    provider_matrix_case_count = int(provider_matrix_summary.get("case_count") or provider_matrix_summary.get("executed_case_count") or 0)
    provider_matrix_passed_case_count = int(provider_matrix_summary.get("passed_case_count") or 0)
    provider_matrix_modes_ok = (
        provider_matrix_summary.get("all_search_ready_provider_modes_passed") is True
        or (
            provider_matrix_summary.get("missing_mode_pairs") == []
            and provider_matrix_case_count > 0
            and provider_matrix_passed_case_count == provider_matrix_case_count
        )
    )
    provider_matrix_country_scope_ok = (
        provider_matrix_summary.get("provider_country_scope_ok") is True
        or (
            provider_matrix.get("country_scope") == "all_search_ready"
            and bool(provider_matrix_summary.get("country_codes"))
        )
    )
    provider_matrix_target_context_ok = (
        provider_matrix_summary.get("target_context_country_scope_ok") is True
        or provider_matrix.get("country_scope") == "all_search_ready"
    )
    performance_ok = performance.get("status") == "pass" and int(performance.get("failed_count") or 0) == 0
    live_mobile_ok = (
        live_mobile_receipt_path is None
        or (
            live_mobile.get("status") == "pass"
            and int(live_mobile.get("failed_count") or 0) == 0
            and int(live_mobile.get("route_count") or 0) >= 9
        )
    )
    tour_controls_ok = tour_controls.get("status") == "pass" and not missing_provider_modes
    export_discovery_ok = export_discovery.get("status") in {"ready", "pass"}
    expected_import_providers = {"3dvista", "pano2vr", "krpano", "magicfit"}
    manifest_providers = {
        str(provider or "").strip().lower()
        for provider in list(import_manifest.get("providers") or [])
        if str(provider or "").strip()
    }
    prepared_drop_providers = {
        str(row.get("provider") or "").strip().lower()
        for row in list(import_manifest.get("prepared_drop_dirs") or [])
        if isinstance(row, dict)
    }
    operator_import_manifest_ready = (
        import_manifest.get("status") == "ready_for_exports"
        and int(import_manifest.get("import_count") or 0) >= len(expected_import_providers)
        and expected_import_providers.issubset(manifest_providers)
        and expected_import_providers.issubset(prepared_drop_providers)
    )
    repair_canary_ok = (
        repair_canary.get("status") == "pass"
        and repair_canary.get("run_status") == "completed_partial"
        and repair_canary.get("source_repair_status") == "returned"
        and repair_canary.get("receipt_resolution") == "provider_quarantined_retry_budget_exhausted"
    )
    provider_matrix_ok = (
        provider_matrix.get("status") == "pass"
        and provider_matrix.get("targeted_search_matrix_status") == "pass"
        and provider_matrix.get("targeted_search_matrix_executed") is True
        and provider_matrix_summary.get("executed") is True
        and provider_matrix_summary.get("all_search_ready_providers_covered") is True
        and provider_matrix_modes_ok
        and provider_matrix_summary.get("dispatch_acceptance_complete") is True
        and provider_matrix_summary.get("status_readback_complete") is True
        and provider_matrix_summary.get("payload_contracts_ok") is True
        and provider_matrix_country_scope_ok
        and provider_matrix_target_context_ok
        and provider_matrix_summary.get("agent_unlimited_results_ok") is True
        and provider_matrix_summary.get("strict_without_soft_filters_ok") is True
        and provider_matrix_summary.get("soft_filters_present_ok") is True
        and int(provider_matrix_summary.get("failed_case_count") or 0) == 0
    )

    blockers: list[dict[str, Any]] = []
    if not performance_ok:
        blockers.append(
            {
                "area": "mobile_and_authenticated_surfaces",
                "status": performance.get("status") or "unknown",
                "action": "rerun and fix propertyquarry_authenticated_performance_smoke until every measured route passes",
            }
        )
    if not live_mobile_ok:
        blockers.append(
            {
                "area": "live_mobile_surfaces",
                "status": live_mobile.get("status") or "unknown",
                "action": "run propertyquarry_live_mobile_surface_smoke.py against the deployed stack and fix any overflow, chrome, touch-target, or logout regressions",
            }
        )
    if missing_provider_modes:
        blockers.append(
            {
                "area": "verified_tour_provider_modes",
                "missing_provider_modes": missing_provider_modes,
                "action": "attach real provider evidence: verified 3DVista/Pano2VR exports, a walkable_scene for licensed krpano, and a receipt-backed playable MagicFit walkthrough",
            }
        )
    if not export_discovery_ok:
        blockers.append(
            {
                "area": "tour_export_drop",
                "status": export_discovery.get("status") or "unknown",
                "action": "place verified 3DVista/Pano2VR exports in the configured drop directory and rerun discovery/import",
            }
        )
    if not repair_canary_ok:
        blockers.append(
            {
                "area": "self_healing_repair",
                "status": repair_canary.get("status") or "unknown",
                "action": "rerun and fix propertyquarry_repair_fleet_canary until failed provider sources are repaired or safely quarantined",
            }
        )
    if not provider_matrix_ok:
        blockers.append(
            {
                "area": "provider_targeted_search_matrix",
                "status": provider_matrix.get("status") or "unknown",
                "targeted_search_matrix_status": provider_matrix.get("targeted_search_matrix_status") or "unknown",
                "executed": bool(provider_matrix.get("targeted_search_matrix_executed")),
                "action": "run property_live_provider_smoke.py for all search-ready countries with --execute-search-matrix so every provider has strict and soft-filter targeted search evidence",
            }
        )

    next_required_actions = list(tour_controls.get("next_required_actions") or [])
    if export_discovery.get("status") == "blocked_no_verified_exports":
        next_required_actions.append(
            {
                "provider": "3dvista_pano2vr_krpano_magicfit",
                "action": "drop real 3DVista/Pano2VR export folders, krpano panorama/cube assets, and receipt-backed MagicFit video assets into the prepared import directories",
            }
        )

    status = "pass" if performance_ok and live_mobile_ok and tour_controls_ok and export_discovery_ok and repair_canary_ok and provider_matrix_ok else "blocked"
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "performance": {
            "status": performance.get("status"),
            "failed_count": performance.get("failed_count"),
            "route_count": performance.get("route_count"),
            "receipt_path": str(performance_receipt_path),
        },
        "live_mobile_surfaces": {
            "status": live_mobile.get("status") or ("not_configured" if live_mobile_receipt_path is None else "missing"),
            "failed_count": live_mobile.get("failed_count"),
            "route_count": live_mobile.get("route_count"),
            "viewport": live_mobile.get("viewport"),
            "receipt_path": str(live_mobile_receipt_path) if live_mobile_receipt_path is not None else "",
        },
        "tour_controls": {
            "status": tour_controls.get("status"),
            "provider_counts": tour_controls.get("provider_counts"),
            "ready_provider_modes": tour_controls.get("ready_provider_modes"),
            "missing_provider_modes": missing_provider_modes,
            "receipt_path": str(tour_control_receipt_path),
        },
        "export_discovery": {
            "status": export_discovery.get("status"),
            "import_count": export_discovery.get("import_count"),
            "rejected_count": export_discovery.get("rejected_count"),
            "receipt_path": str(export_discovery_receipt_path),
        },
        "operator_import_manifest": {
            "status": import_manifest.get("status") or ("not_configured" if import_manifest_receipt_path is None else "missing"),
            "ready_for_exports": operator_import_manifest_ready,
            "import_count": import_manifest.get("import_count"),
            "providers": sorted(manifest_providers),
            "prepared_drop_provider_count": len(prepared_drop_providers),
            "missing_prepared_providers": sorted(expected_import_providers - prepared_drop_providers),
            "next_command": import_manifest.get("next_command"),
            "receipt_path": str(import_manifest_receipt_path) if import_manifest_receipt_path is not None else "",
            "note": "Prepared operator drop lanes are progress only; gold still requires real imported assets and verified playable controls.",
        },
        "self_healing": {
            "status": repair_canary.get("status"),
            "run_status": repair_canary.get("run_status"),
            "source_repair_status": repair_canary.get("source_repair_status"),
            "receipt_resolution": repair_canary.get("receipt_resolution"),
            "receipt_path": str(repair_canary_receipt_path),
        },
        "provider_matrix": {
            "status": provider_matrix.get("status"),
            "country_scope": provider_matrix.get("country_scope"),
            "targeted_search_matrix_status": provider_matrix.get("targeted_search_matrix_status"),
            "targeted_search_matrix_executed": provider_matrix.get("targeted_search_matrix_executed"),
            "targeted_search_matrix_count": provider_matrix.get("targeted_search_matrix_count"),
            "strict_case_count": provider_matrix_summary.get("strict_case_count"),
            "soft_filter_case_count": provider_matrix_summary.get("soft_filter_case_count"),
            "failed_case_count": provider_matrix_summary.get("failed_case_count"),
            "agent_unlimited_results_ok": provider_matrix_summary.get("agent_unlimited_results_ok"),
            "all_search_ready_provider_modes_passed": provider_matrix_modes_ok,
            "provider_country_scope_ok": provider_matrix_country_scope_ok,
            "target_context_country_scope_ok": provider_matrix_target_context_ok,
            "receipt_path": str(provider_matrix_receipt_path),
        },
        "blockers": blockers,
        "next_required_actions": next_required_actions,
        "notes": [
            "Gold is not claimable until every required provider mode is backed by verified evidence.",
            "Self-healing is proven only when the repair canary repairs or safely quarantines a failed provider source.",
            "Provider E2E is proven only when every search-ready provider has executed strict and soft-filter targeted search cases.",
            "This receipt intentionally treats missing 3DVista, Pano2VR, krpano, or MagicFit evidence as blocked rather than pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize current PropertyQuarry gold-readiness receipts.")
    parser.add_argument("--performance-receipt", default="_completion/smoke/property-auth-performance-latest.json")
    parser.add_argument("--live-mobile-receipt", default="_completion/smoke/property-live-mobile-surface-latest.json")
    parser.add_argument("--tour-control-receipt", default="_completion/property_tour_controls/latest-current.json")
    parser.add_argument("--export-discovery-receipt", default="_completion/property_tour_exports/discovery-current.json")
    parser.add_argument("--import-manifest-receipt", default="_completion/property_tour_exports/import-manifest-current.json")
    parser.add_argument("--repair-canary-receipt", default="_completion/repair/propertyquarry-repair-canary-latest.json")
    parser.add_argument("--provider-matrix-receipt", default="_completion/provider_smoke/all-search-ready-live.json")
    parser.add_argument("--write", default="_completion/property_gold_status/latest.json")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    receipt = build_gold_status_receipt(
        performance_receipt_path=Path(args.performance_receipt),
        live_mobile_receipt_path=Path(args.live_mobile_receipt),
        tour_control_receipt_path=Path(args.tour_control_receipt),
        export_discovery_receipt_path=Path(args.export_discovery_receipt),
        import_manifest_receipt_path=Path(args.import_manifest_receipt),
        repair_canary_receipt_path=Path(args.repair_canary_receipt),
        provider_matrix_receipt_path=Path(args.provider_matrix_receipt),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if receipt.get("status") == "pass":
        return 0
    return 2 if args.fail_on_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
