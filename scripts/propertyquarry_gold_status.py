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
    repair_canary_receipt_path: Path,
) -> dict[str, Any]:
    performance = _load_json(performance_receipt_path)
    tour_controls = _load_json(tour_control_receipt_path)
    export_discovery = _load_json(export_discovery_receipt_path)
    repair_canary = _load_json(repair_canary_receipt_path)

    missing_provider_modes = _missing_provider_modes(tour_controls)
    performance_ok = performance.get("status") == "pass" and int(performance.get("failed_count") or 0) == 0
    tour_controls_ok = tour_controls.get("status") == "pass" and not missing_provider_modes
    export_discovery_ok = export_discovery.get("status") in {"ready", "pass"}
    repair_canary_ok = (
        repair_canary.get("status") == "pass"
        and repair_canary.get("run_status") == "completed_partial"
        and repair_canary.get("source_repair_status") == "returned"
        and repair_canary.get("receipt_resolution") == "provider_quarantined_retry_budget_exhausted"
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

    next_required_actions = list(tour_controls.get("next_required_actions") or [])
    if export_discovery.get("status") == "blocked_no_verified_exports":
        next_required_actions.append(
            {
                "provider": "3dvista_pano2vr",
                "action": "drop real 3DVista/Pano2VR export folders containing provider runtime markers into the tour export drop directory",
            }
        )

    status = "pass" if performance_ok and tour_controls_ok and export_discovery_ok and repair_canary_ok else "blocked"
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "performance": {
            "status": performance.get("status"),
            "failed_count": performance.get("failed_count"),
            "route_count": performance.get("route_count"),
            "receipt_path": str(performance_receipt_path),
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
        "self_healing": {
            "status": repair_canary.get("status"),
            "run_status": repair_canary.get("run_status"),
            "source_repair_status": repair_canary.get("source_repair_status"),
            "receipt_resolution": repair_canary.get("receipt_resolution"),
            "receipt_path": str(repair_canary_receipt_path),
        },
        "blockers": blockers,
        "next_required_actions": next_required_actions,
        "notes": [
            "Gold is not claimable until every required provider mode is backed by verified evidence.",
            "Self-healing is proven only when the repair canary repairs or safely quarantines a failed provider source.",
            "This receipt intentionally treats missing 3DVista, Pano2VR, krpano, or MagicFit evidence as blocked rather than pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize current PropertyQuarry gold-readiness receipts.")
    parser.add_argument("--performance-receipt", default="_completion/smoke/property-auth-performance-latest.json")
    parser.add_argument("--tour-control-receipt", default="_completion/property_tour_controls/latest-current.json")
    parser.add_argument("--export-discovery-receipt", default="_completion/property_tour_exports/discovery-current.json")
    parser.add_argument("--repair-canary-receipt", default="_completion/repair/propertyquarry-repair-canary-latest.json")
    parser.add_argument("--write", default="_completion/property_gold_status/latest.json")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    receipt = build_gold_status_receipt(
        performance_receipt_path=Path(args.performance_receipt),
        tour_control_receipt_path=Path(args.tour_control_receipt),
        export_discovery_receipt_path=Path(args.export_discovery_receipt),
        repair_canary_receipt_path=Path(args.repair_canary_receipt),
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
