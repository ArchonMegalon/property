#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_TOUR_PROVIDER_MODES = ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
REQUIRED_RESEARCH_PERFORMANCE_CHECKS = (
    "research_candidate",
    "research_visual_cards_present",
    "research_visual_requests_honest",
    "research_no_fake_visual_ready",
    "research_confirmed_listing_facts",
    "research_confirmed_price_signal",
    "research_mobile_open_property_compact_layout",
    "research_mobile_visual_frame_compact",
)
REQUIRED_LIVE_MOBILE_ROUTES = (
    "/app/search",
    "/app/shortlist",
    "/app/agents",
    "/app/alerts",
    "/app/account",
    "/app/billing",
    "/app/settings/google",
    "/app/settings/access",
    "/app/settings/usage",
    "/app/settings/support",
    "/app/settings/trust",
    "/app/settings/invitations",
    "/app/research",
    "/app/properties/packets",
)
REQUIRED_LIVE_MOBILE_DETAIL_PREFIXES = ("/app/research/",)
COMMON_OPERATOR_DROP_README_TOKENS = (
    ("title", "PropertyQuarry provider export drop folder"),
    ("no_placeholders", "Do not copy placeholder HTML"),
    ("dry_import", "Single-provider dry import example:"),
    ("gold_gate", "Gold only passes when verify_property_tour_controls reports ready provider modes"),
)
PROVIDER_OPERATOR_DROP_README_TOKENS = {
    "3dvista": (
        ("complete_export", "Copy the complete 3DVista export folder"),
        ("runtime_marker", "tdvplayer"),
        ("importer", "import_3dvista_export.py"),
    ),
    "pano2vr": (
        ("complete_output", "Copy the complete Pano2VR output folder"),
        ("runtime_marker", "tour.js"),
        ("importer", "import_pano2vr_export.py"),
    ),
    "krpano": (
        ("cube_faces", "cube-face-1"),
        ("license_domain", "KRPANO_LICENSE_DOMAIN=propertyquarry.com"),
        ("importer", "import_krpano_walkable_scene.py"),
    ),
    "magicfit": (
        ("walkthrough_video", "magicfit-walkthrough.mp4"),
        ("render_receipt", "magicfit-receipt.json"),
        ("importer", "import_magicfit_walkthrough.py"),
    ),
}


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


def _parse_receipt_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _receipt_generated_at(payload: dict[str, Any]) -> tuple[datetime | None, str, str]:
    candidates: tuple[tuple[str, object], ...] = (
        ("generated_at", payload.get("generated_at")),
        ("updated_at", payload.get("updated_at")),
        ("completed_at", payload.get("completed_at")),
        ("repair_summary.generated_at", (payload.get("repair_summary") or {}).get("generated_at") if isinstance(payload.get("repair_summary"), dict) else ""),
        ("summary.generated_at", (payload.get("summary") or {}).get("generated_at") if isinstance(payload.get("summary"), dict) else ""),
    )
    for source, value in candidates:
        parsed = _parse_receipt_datetime(value)
        if parsed is not None:
            return parsed, source, str(value or "").strip()
    return None, "", ""


def _receipt_freshness_status(
    receipts: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_hours: float | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    if max_age_hours is None or max_age_hours <= 0:
        return True, []
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    for area, payload in receipts.items():
        generated_at, timestamp_source, raw_generated_at = _receipt_generated_at(payload)
        if generated_at is None:
            rows.append(
                {
                    "area": area,
                    "status": "missing_or_invalid_generated_at",
                    "generated_at": str(payload.get("generated_at") or ""),
                }
            )
            continue
        age_seconds = max(0.0, (current_time - generated_at).total_seconds())
        age_hours = age_seconds / 3600.0
        if age_hours > max_age_hours:
            rows.append(
                {
                    "area": area,
                    "status": "stale",
                    "generated_at": generated_at.isoformat(),
                    "timestamp_source": timestamp_source,
                    "raw_generated_at": raw_generated_at,
                    "age_hours": round(age_hours, 2),
                    "max_age_hours": max_age_hours,
                }
            )
    return not rows, rows


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


def _performance_research_detail_checks(performance: dict[str, Any]) -> tuple[bool, list[str], str]:
    for row in list(performance.get("routes") or []):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").split("?", 1)[0]
        if not path.startswith("/app/research/"):
            continue
        passed_checks = {
            str(check.get("name") or "")
            for check in list(row.get("checks") or [])
            if isinstance(check, dict) and check.get("ok") is True
        }
        missing = [name for name in REQUIRED_RESEARCH_PERFORMANCE_CHECKS if name not in passed_checks]
        return (not missing, missing, path)
    return (False, list(REQUIRED_RESEARCH_PERFORMANCE_CHECKS), "")


def _covered_live_mobile_routes(live_mobile: dict[str, Any]) -> set[str]:
    covered: set[str] = set()
    for row in list(live_mobile.get("routes") or []):
        if not isinstance(row, dict) or row.get("ok") is not True:
            continue
        route = str(row.get("route") or "").split("?", 1)[0].strip()
        if route:
            covered.add(route)
    return covered


def _operator_drop_readme_status(import_manifest: dict[str, Any]) -> tuple[bool, int, list[str], list[dict[str, Any]]]:
    expected_providers = set(PROVIDER_OPERATOR_DROP_README_TOKENS)
    provider_rows = {
        str(row.get("provider") or "").strip().lower(): row
        for row in list(import_manifest.get("prepared_drop_dirs") or [])
        if isinstance(row, dict) and str(row.get("provider") or "").strip().lower()
    }
    failures: list[dict[str, Any]] = []
    verified_providers: set[str] = set()
    for provider in sorted(expected_providers):
        row = provider_rows.get(provider)
        if not row:
            failures.append({"provider": provider, "status": "missing_manifest_row", "missing_tokens": ["readme_path"]})
            continue
        readme_path_text = str(row.get("readme") or "").strip()
        if not readme_path_text:
            failures.append({"provider": provider, "status": "missing_readme_path", "missing_tokens": ["readme_path"]})
            continue
        readme_path = Path(readme_path_text)
        try:
            body = readme_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            failures.append({"provider": provider, "status": "missing_readme_file", "missing_tokens": ["readme_file"]})
            continue
        except Exception as exc:
            failures.append({"provider": provider, "status": "invalid_readme_file", "error": f"{type(exc).__name__}: {exc}", "missing_tokens": ["readme_file"]})
            continue
        required_tokens = (*COMMON_OPERATOR_DROP_README_TOKENS, *PROVIDER_OPERATOR_DROP_README_TOKENS[provider])
        missing_labels = [label for label, token in required_tokens if token not in body]
        if missing_labels:
            failures.append({"provider": provider, "status": "stale_readme", "missing_tokens": missing_labels})
            continue
        verified_providers.add(provider)
    missing_providers = sorted(expected_providers - verified_providers)
    return (not failures and not missing_providers, len(verified_providers), missing_providers, failures[:8])


def build_gold_status_receipt(
    *,
    performance_receipt_path: Path,
    tour_control_receipt_path: Path,
    export_discovery_receipt_path: Path,
    import_manifest_receipt_path: Path | None = None,
    repair_canary_receipt_path: Path,
    provider_matrix_receipt_path: Path,
    live_mobile_receipt_path: Path | None = None,
    max_receipt_age_hours: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    performance = _load_json(performance_receipt_path)
    live_mobile = _load_json(live_mobile_receipt_path) if live_mobile_receipt_path is not None else {}
    tour_controls = _load_json(tour_control_receipt_path)
    export_discovery = _load_json(export_discovery_receipt_path)
    import_manifest = _load_json(import_manifest_receipt_path) if import_manifest_receipt_path is not None else {}
    repair_canary = _load_json(repair_canary_receipt_path)
    provider_matrix = _load_json(provider_matrix_receipt_path)
    receipt_freshness_ok, stale_receipts = _receipt_freshness_status(
        {
            "performance": performance,
            "tour_controls": tour_controls,
            "export_discovery": export_discovery,
            "repair_canary": repair_canary,
            "provider_matrix": provider_matrix,
            **({"live_mobile_surfaces": live_mobile} if live_mobile_receipt_path is not None else {}),
        },
        now=now,
        max_age_hours=max_receipt_age_hours,
    )

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
    research_performance_ok, missing_research_performance_checks, research_performance_path = _performance_research_detail_checks(performance)
    performance_ok = (
        performance.get("status") == "pass"
        and int(performance.get("failed_count") or 0) == 0
        and research_performance_ok
    )
    live_mobile_covered_routes = _covered_live_mobile_routes(live_mobile)
    missing_live_mobile_routes = [
        route for route in REQUIRED_LIVE_MOBILE_ROUTES if route not in live_mobile_covered_routes
    ]
    missing_live_mobile_detail_routes = [
        prefix
        for prefix in REQUIRED_LIVE_MOBILE_DETAIL_PREFIXES
        if not any(route.startswith(prefix) for route in live_mobile_covered_routes)
    ]
    live_mobile_ok = (
        live_mobile_receipt_path is None
        or (
            live_mobile.get("status") == "pass"
            and int(live_mobile.get("failed_count") or 0) == 0
            and int(live_mobile.get("route_count") or 0) >= len(REQUIRED_LIVE_MOBILE_ROUTES)
            and not missing_live_mobile_routes
            and not missing_live_mobile_detail_routes
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
    hardened_readmes_ok, hardened_readme_provider_count, missing_hardened_readme_providers, hardened_readme_failures = _operator_drop_readme_status(import_manifest)
    operator_import_manifest_ready = (
        import_manifest.get("status") == "ready_for_exports"
        and int(import_manifest.get("import_count") or 0) >= len(expected_import_providers)
        and expected_import_providers.issubset(manifest_providers)
        and expected_import_providers.issubset(prepared_drop_providers)
        and hardened_readmes_ok
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
                "missing_research_detail_checks": missing_research_performance_checks,
                "action": "rerun and fix propertyquarry_authenticated_performance_smoke until every measured route passes",
            }
        )
    if not live_mobile_ok:
        blockers.append(
            {
                "area": "live_mobile_surfaces",
                "status": live_mobile.get("status") or "unknown",
                "missing_routes": missing_live_mobile_routes,
                "missing_detail_routes": missing_live_mobile_detail_routes,
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
    if import_manifest_receipt_path is not None and import_manifest.get("status") == "ready_for_exports" and not hardened_readmes_ok:
        blockers.append(
            {
                "area": "tour_operator_drop_readmes",
                "status": "stale_or_missing",
                "missing_hardened_readme_providers": missing_hardened_readme_providers,
                "failures": hardened_readme_failures,
                "action": "rerun materialize_property_tour_export_manifest.py --prepare-dirs so each provider drop folder has current import and verification instructions",
            }
        )
    if import_manifest_receipt_path is not None and not operator_import_manifest_ready:
        blockers.append(
            {
                "area": "tour_operator_import_manifest",
                "status": import_manifest.get("status") or "missing",
                "missing_prepared_providers": sorted(expected_import_providers - prepared_drop_providers),
                "hardened_readmes_ok": hardened_readmes_ok,
                "action": "prepare the 3DVista, Pano2VR, krpano, and MagicFit operator import lanes before claiming gold",
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
    if not receipt_freshness_ok:
        blockers.append(
            {
                "area": "receipt_freshness",
                "status": "stale_or_missing",
                "max_age_hours": max_receipt_age_hours,
                "stale_receipts": stale_receipts,
                "action": "rerun the stale live smoke, tour, repair, provider, or discovery verifiers before claiming gold",
            }
        )

    next_required_actions = list(tour_controls.get("next_required_actions") or [])
    export_rejection_sample = [
        {
            "slug": str(row.get("slug") or ""),
            "provider": str(row.get("provider") or ""),
            "reason": str(row.get("reason") or ""),
            "action": str(row.get("action") or ""),
            "drop_layout": str(row.get("drop_layout") or ""),
        }
        for row in list(export_discovery.get("rejected") or [])[:6]
        if isinstance(row, dict)
    ]
    if export_discovery.get("status") == "blocked_no_verified_exports":
        next_required_actions.append(
            {
                "provider": "3dvista_pano2vr_krpano_magicfit",
                "action": (
                    export_rejection_sample[0]["action"]
                    if export_rejection_sample and export_rejection_sample[0].get("action")
                    else "drop real 3DVista/Pano2VR export folders, krpano panorama/cube assets, and receipt-backed MagicFit video assets into the prepared import directories"
                ),
                "rejected_sample": export_rejection_sample,
            }
        )

    operator_import_manifest_ok = import_manifest_receipt_path is None or operator_import_manifest_ready
    status = (
        "pass"
        if (
            performance_ok
            and live_mobile_ok
            and tour_controls_ok
            and export_discovery_ok
            and operator_import_manifest_ok
            and repair_canary_ok
            and provider_matrix_ok
            and receipt_freshness_ok
        )
        else "blocked"
    )
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "performance": {
            "status": performance.get("status"),
            "failed_count": performance.get("failed_count"),
            "route_count": performance.get("route_count"),
            "research_detail_path": research_performance_path,
            "research_detail_checks_ok": research_performance_ok,
            "missing_research_detail_checks": missing_research_performance_checks,
            "receipt_path": str(performance_receipt_path),
        },
        "live_mobile_surfaces": {
            "status": live_mobile.get("status") or ("not_configured" if live_mobile_receipt_path is None else "missing"),
            "failed_count": live_mobile.get("failed_count"),
            "route_count": live_mobile.get("route_count"),
            "required_route_count": len(REQUIRED_LIVE_MOBILE_ROUTES),
            "missing_routes": missing_live_mobile_routes,
            "required_detail_prefixes": list(REQUIRED_LIVE_MOBILE_DETAIL_PREFIXES),
            "missing_detail_routes": missing_live_mobile_detail_routes,
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
            "rejected_sample": export_rejection_sample,
            "receipt_path": str(export_discovery_receipt_path),
        },
        "operator_import_manifest": {
            "status": import_manifest.get("status") or ("not_configured" if import_manifest_receipt_path is None else "missing"),
            "ready_for_exports": operator_import_manifest_ready,
            "import_count": import_manifest.get("import_count"),
            "providers": sorted(manifest_providers),
            "prepared_drop_provider_count": len(prepared_drop_providers),
            "missing_prepared_providers": sorted(expected_import_providers - prepared_drop_providers),
            "hardened_readmes_ok": hardened_readmes_ok,
            "hardened_readme_provider_count": hardened_readme_provider_count,
            "missing_hardened_readme_providers": missing_hardened_readme_providers,
            "hardened_readme_failures": hardened_readme_failures,
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
        "receipt_freshness": {
            "status": "pass" if receipt_freshness_ok else "fail",
            "max_age_hours": max_receipt_age_hours,
            "stale_receipts": stale_receipts,
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
    parser.add_argument("--live-mobile-receipt", default="_completion/smoke/property-live-mobile-surface-with-research-detail-pass.json")
    parser.add_argument("--tour-control-receipt", default="_completion/tours/property-tour-controls-after-monotonic-counters.json")
    parser.add_argument("--export-discovery-receipt", default="_completion/tours/property-tour-export-discovery-full-current.json")
    parser.add_argument("--import-manifest-receipt", default="_completion/property_tour_exports/import-manifest-current.json")
    parser.add_argument("--repair-canary-receipt", default="_completion/repair/propertyquarry-repair-canary-latest.json")
    parser.add_argument("--provider-matrix-receipt", default="_completion/provider_smoke/all-search-ready-current-resumed.json")
    parser.add_argument("--write", default="_completion/property_gold_status/latest.json")
    parser.add_argument("--max-receipt-age-hours", type=float, default=24.0)
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
        max_receipt_age_hours=args.max_receipt_age_hours,
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
