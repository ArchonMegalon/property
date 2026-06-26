#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
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
    "research_ranking_only_no_compare_cards",
    "research_mobile_open_property_compact_layout",
    "research_mobile_visual_frame_compact",
)
REQUIRED_SEARCH_PERFORMANCE_CHECKS = (
    "what_matters_distance_controls_compact",
    "what_matters_school_distance_controls",
)
REQUIRED_RYBBIT_PERFORMANCE_CHECKS = (
    "rybbit_no_identify",
    "rybbit_taxonomy_events_only",
    "rybbit_allowed_attributes_only",
    "rybbit_no_private_payload",
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
REQUIRED_PUBLIC_AUTH_CHECKS = (
    "sign_in_minimal_copy",
    "sign_in_provider_creates_account",
    "sign_in_no_unavailable_auth_copy",
    "sign_in_google_state",
    "sign_in_google_feedback",
)
REQUIRED_BILLING_SURFACE_CHECKS = (
    "billing_local_board_deleted",
)
REQUIRED_ACCOUNT_NOTIFICATION_CHECKS = (
    "account_notifications",
    "account_notification_form",
    "account_notification_email_channel",
    "account_notification_telegram_channel",
    "account_notification_whatsapp_channel",
    "account_notification_primary_route",
    "account_notification_whatsapp_phone",
    "account_notification_save_action",
)
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


DEFAULT_RECEIPT_PATTERNS = {
    "performance": ("_completion/smoke/property-auth-performance-*.json",),
    "live_mobile": ("_completion/smoke/property-live-mobile-surface*.json",),
    "public_smoke": ("_completion/smoke/property-live-public*.json",),
    "authenticated_smoke": ("_completion/smoke/property-live-authenticated*.json",),
    "tour_control": ("_completion/tours/property-tour-controls*.json",),
    "export_discovery": ("_completion/tours/property-tour-export-discovery*.json",),
    "import_manifest": ("_completion/property_tour_exports/import-manifest*.json",),
    "billing": ("_completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION*.json",),
    "vendor_tooling": ("_completion/tours/property-tour-vendor-tooling*.json",),
    "repair_canary": ("_completion/repair/propertyquarry-repair-canary*.json",),
    "provider_matrix": ("_completion/provider_smoke/all-search-ready*.json",),
}
DEFAULT_RECEIPT_FALLBACKS = {
    "performance": "_completion/smoke/property-auth-performance-latest.json",
    "live_mobile": "_completion/smoke/property-live-mobile-surface-with-research-detail-pass.json",
    "public_smoke": "_completion/smoke/property-live-public-latest.json",
    "authenticated_smoke": "_completion/smoke/property-live-authenticated-latest.json",
    "tour_control": "_completion/tours/property-tour-controls-live-container-current.json",
    "export_discovery": "_completion/tours/property-tour-export-discovery-full-current.json",
    "import_manifest": "_completion/property_tour_exports/import-manifest-current.json",
    "billing": "_completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json",
    "vendor_tooling": "_completion/tours/property-tour-vendor-tooling-current.json",
    "repair_canary": "_completion/repair/propertyquarry-repair-canary-latest.json",
    "provider_matrix": "_completion/provider_smoke/all-search-ready-current-resumed.json",
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


def _latest_receipt_path(patterns: tuple[str, ...], *, fallback: str) -> Path:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in Path().glob(pattern) if path.is_file())
    if not candidates:
        return Path(fallback).expanduser().resolve()

    def sort_key(path: Path) -> tuple[float, float, str]:
        payload = _load_json(path)
        generated_at, _timestamp_source, _raw_generated_at = _receipt_generated_at(payload)
        generated_timestamp = generated_at.timestamp() if generated_at is not None else 0.0
        try:
            modified_timestamp = path.stat().st_mtime
        except OSError:
            modified_timestamp = 0.0
        return (generated_timestamp, modified_timestamp, path.as_posix())

    return max(candidates, key=sort_key).resolve()


def _default_receipt_path(name: str) -> Path:
    return _latest_receipt_path(
        DEFAULT_RECEIPT_PATTERNS[name],
        fallback=DEFAULT_RECEIPT_FALLBACKS[name],
    )


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


def _tour_provider_evidence_action(missing_provider_modes: list[str]) -> str:
    actions = {
        "matterport": "verified Matterport model URL/control receipt",
        "3dvista": "verified 3DVista export or allowlisted 3DVista tour URL",
        "pano2vr": "verified Pano2VR export",
        "krpano": "real krpano walkable_scene from panorama/cube assets plus the licensed environment",
        "magicfit": "receipt-backed playable MagicFit walkthrough",
    }
    parts = [actions[provider] for provider in missing_provider_modes if provider in actions]
    if not parts:
        return "rerun verify_property_tour_controls.py and attach any provider evidence it still reports missing"
    return f"attach real provider evidence for missing modes only: {', '.join(parts)}"


def _tour_provider_missing_note(missing_provider_modes: list[str]) -> str:
    labels = {
        "matterport": "Matterport",
        "3dvista": "3DVista",
        "pano2vr": "Pano2VR",
        "krpano": "krpano",
        "magicfit": "MagicFit",
    }
    names = [labels[provider] for provider in missing_provider_modes if provider in labels]
    if not names:
        return "This receipt has no missing tour provider modes in the active verifier output."
    joined = ", ".join(names)
    return f"This receipt intentionally treats missing {joined} evidence as blocked rather than pass."


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


def _performance_search_checks(performance: dict[str, Any]) -> tuple[bool, list[str], str]:
    for row in list(performance.get("routes") or []):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").split("?", 1)[0]
        if path != "/app/search":
            continue
        passed_checks = {
            str(check.get("name") or "")
            for check in list(row.get("checks") or [])
            if isinstance(check, dict) and check.get("ok") is True
        }
        missing = [name for name in REQUIRED_SEARCH_PERFORMANCE_CHECKS if name not in passed_checks]
        return (not missing, missing, path)
    return (False, list(REQUIRED_SEARCH_PERFORMANCE_CHECKS), "")


def _performance_analytics_checks(performance: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], list[dict[str, Any]], int]:
    missing_by_route: list[dict[str, Any]] = []
    failed_checks: list[dict[str, Any]] = []
    routes_with_analytics_checks = 0

    for row in list(performance.get("routes") or []):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").split("?", 1)[0].strip()
        checks = [check for check in list(row.get("checks") or []) if isinstance(check, dict)]
        rybbit_checks = [
            check
            for check in checks
            if str(check.get("name") or "").startswith("rybbit_")
        ]
        if not rybbit_checks:
            continue

        routes_with_analytics_checks += 1
        passed = {
            str(check.get("name") or "")
            for check in rybbit_checks
            if check.get("ok") is True
        }
        missing = [name for name in REQUIRED_RYBBIT_PERFORMANCE_CHECKS if name not in passed]
        if missing:
            missing_by_route.append({"path": path, "missing_checks": missing})
        failed_checks.extend(
            {
                "path": path,
                "name": str(check.get("name") or "unnamed_check"),
                "detail": str(check.get("detail") or ""),
            }
            for check in rybbit_checks
            if check.get("ok") is not True
        )

    if routes_with_analytics_checks == 0:
        missing_by_route.append(
            {
                "path": "*",
                "missing_checks": list(REQUIRED_RYBBIT_PERFORMANCE_CHECKS),
            }
        )
    return not missing_by_route and not failed_checks, missing_by_route, failed_checks, routes_with_analytics_checks


def _covered_live_mobile_routes(live_mobile: dict[str, Any]) -> set[str]:
    covered: set[str] = set()
    for row in list(live_mobile.get("routes") or []):
        if not isinstance(row, dict) or row.get("ok") is not True:
            continue
        route = str(row.get("route") or "").split("?", 1)[0].strip()
        if route:
            covered.add(route)
    return covered


def _failed_live_mobile_coverage_checks(live_mobile: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for row in list(live_mobile.get("coverage_checks") or []):
        if not isinstance(row, dict) or row.get("ok") is True:
            continue
        failed.append(
            {
                "name": str(row.get("name") or "unnamed_coverage_check"),
                "required_route_prefix": str(row.get("required_route_prefix") or ""),
                "reason": str(row.get("reason") or ""),
            }
        )
    return failed


def _public_sign_in_checks(public_smoke: dict[str, Any]) -> tuple[bool, list[str], list[dict[str, Any]]]:
    sign_in_row: dict[str, Any] = {}
    for row in list(public_smoke.get("checks") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("path") or "").split("?", 1)[0].strip() == "/sign-in":
            sign_in_row = row
            break
    if not sign_in_row:
        return False, list(REQUIRED_PUBLIC_AUTH_CHECKS), []
    passed_checks = {
        str(check.get("name") or "")
        for check in list(sign_in_row.get("checks") or [])
        if isinstance(check, dict) and check.get("ok") is True
    }
    missing = [name for name in REQUIRED_PUBLIC_AUTH_CHECKS if name not in passed_checks]
    failed = [
        {
            "name": str(check.get("name") or "unnamed_check"),
            "ok": bool(check.get("ok")),
        }
        for check in list(sign_in_row.get("checks") or [])
        if isinstance(check, dict) and check.get("ok") is not True and str(check.get("name") or "").startswith("sign_in_")
    ]
    return not missing and not failed, missing, failed


def _route_named_checks(receipt: dict[str, Any], route_path: str) -> tuple[dict[str, Any], set[str], list[dict[str, Any]]]:
    route_row: dict[str, Any] = {}
    for row in list(receipt.get("checks") or receipt.get("routes") or []):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or row.get("route") or "").split("?", 1)[0].strip()
        if path == route_path:
            route_row = row
            break
    if not route_row:
        return {}, set(), []
    passed = {
        str(check.get("name") or "")
        for check in list(route_row.get("checks") or [])
        if isinstance(check, dict) and check.get("ok") is True
    }
    failed = [
        {
            "name": str(check.get("name") or "unnamed_check"),
            "ok": bool(check.get("ok")),
            "detail": str(check.get("detail") or ""),
        }
        for check in list(route_row.get("checks") or [])
        if isinstance(check, dict) and check.get("ok") is not True
    ]
    return route_row, passed, failed


def _authenticated_billing_surface_checks(authenticated_smoke: dict[str, Any]) -> tuple[bool, list[str], list[dict[str, Any]], str]:
    route_row, passed_checks, failed_checks = _route_named_checks(authenticated_smoke, "/app/billing")
    if not route_row:
        return False, ["billing_route_missing"], [], ""
    missing = [name for name in REQUIRED_BILLING_SURFACE_CHECKS if name not in passed_checks]
    handoff_or_recovery_ok = (
        "billing_external_handoff" in passed_checks
        or "billing_fail_closed_recovery" in passed_checks
    )
    if not handoff_or_recovery_ok:
        missing.append("billing_external_handoff_or_fail_closed_recovery")
    return not missing and not failed_checks, missing, failed_checks, str(route_row.get("status_code") or "")


def _authenticated_account_notification_checks(authenticated_smoke: dict[str, Any]) -> tuple[bool, list[str], list[dict[str, Any]]]:
    route_row, passed_checks, failed_checks = _route_named_checks(authenticated_smoke, "/app/account")
    if not route_row:
        return False, ["account_route_missing"], []
    missing = [name for name in REQUIRED_ACCOUNT_NOTIFICATION_CHECKS if name not in passed_checks]
    notification_failed = [
        check
        for check in failed_checks
        if str(check.get("name") or "").startswith("account_notification") or str(check.get("name") or "") == "account_notifications"
    ]
    return not missing and not notification_failed, missing, notification_failed


def _route_covers_required_detail(route: str, required_prefix: str) -> bool:
    normalized_route = str(route or "").strip().rstrip("/")
    normalized_prefix = str(required_prefix or "").strip().rstrip("/")
    if not normalized_route or not normalized_prefix:
        return False
    return normalized_route == normalized_prefix or normalized_route.startswith(f"{normalized_prefix}/")


def _host_readme_path(readme_path_text: str) -> Path:
    path = Path(readme_path_text)
    if path.is_file() or not str(path).startswith("/data/incoming_property_tours/"):
        return path
    host_incoming_root = Path(
        os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR")
        or os.getenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR")
        or "/docker/property/state/incoming_property_tours"
    ).expanduser()
    try:
        relative = path.relative_to("/data/incoming_property_tours")
    except ValueError:
        return path
    return host_incoming_root / relative


def _read_first_available_readme(row: dict[str, Any]) -> tuple[str, str, str]:
    attempted: list[str] = []
    for key in ("readme", "artifact_readme", "drop_readme"):
        readme_path_text = str(row.get(key) or "").strip()
        if not readme_path_text or readme_path_text in attempted:
            continue
        attempted.append(readme_path_text)
        readme_path = _host_readme_path(readme_path_text)
        try:
            return readme_path.read_text(encoding="utf-8"), str(readme_path), key
        except FileNotFoundError:
            continue
        except Exception as exc:
            return "", str(readme_path), f"{key}:{type(exc).__name__}: {exc}"
    return "", ", ".join(attempted), ""


def _billing_handoff_ready(billing_receipt: dict[str, Any]) -> bool:
    handoff = billing_receipt.get("billing_handoff")
    if not isinstance(handoff, dict):
        return False
    return (
        bool(handoff.get("configured"))
        and bool(handoff.get("host_resolves"))
        and str(handoff.get("url") or "").strip().startswith("https://")
        and str(billing_receipt.get("status") or "").strip() != "blocked"
    )


def _operator_drop_readme_status(
    import_manifest: dict[str, Any],
    *,
    expected_providers: set[str] | None = None,
) -> tuple[bool, int, list[str], list[dict[str, Any]]]:
    expected_providers = expected_providers or set(PROVIDER_OPERATOR_DROP_README_TOKENS)
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
        artifact_readme_path_text = str(row.get("artifact_readme") or "").strip()
        if not readme_path_text and not artifact_readme_path_text:
            failures.append({"provider": provider, "status": "missing_readme_path", "missing_tokens": ["readme_path"]})
            continue
        body, resolved_readme_path, readme_source = _read_first_available_readme(row)
        if not body:
            failures.append(
                {
                    "provider": provider,
                    "status": "missing_readme_file",
                    "readme": resolved_readme_path,
                    "readme_source": readme_source,
                    "readme_write_error": str(row.get("readme_write_error") or ""),
                    "artifact_readme_write_error": str(row.get("artifact_readme_write_error") or ""),
                    "missing_tokens": ["readme_file"],
                }
            )
            continue
        required_tokens = (*COMMON_OPERATOR_DROP_README_TOKENS, *PROVIDER_OPERATOR_DROP_README_TOKENS[provider])
        missing_labels = [label for label, token in required_tokens if token not in body]
        if missing_labels:
            failures.append(
                {
                    "provider": provider,
                    "status": "stale_readme",
                    "readme": resolved_readme_path,
                    "readme_source": readme_source,
                    "missing_tokens": missing_labels,
                }
            )
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
    billing_receipt_path: Path | None = None,
    live_mobile_receipt_path: Path | None = None,
    public_smoke_receipt_path: Path | None = None,
    authenticated_smoke_receipt_path: Path | None = None,
    tour_provider_ownership_receipt_path: Path | None = None,
    vendor_tooling_receipt_path: Path | None = None,
    max_receipt_age_hours: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    performance = _load_json(performance_receipt_path)
    live_mobile = _load_json(live_mobile_receipt_path) if live_mobile_receipt_path is not None else {}
    public_smoke = _load_json(public_smoke_receipt_path) if public_smoke_receipt_path is not None else {}
    authenticated_smoke = _load_json(authenticated_smoke_receipt_path) if authenticated_smoke_receipt_path is not None else {}
    tour_controls = _load_json(tour_control_receipt_path)
    export_discovery = _load_json(export_discovery_receipt_path)
    import_manifest = _load_json(import_manifest_receipt_path) if import_manifest_receipt_path is not None else {}
    billing_receipt = _load_json(billing_receipt_path) if billing_receipt_path is not None else {}
    tour_provider_ownership = _load_json(tour_provider_ownership_receipt_path) if tour_provider_ownership_receipt_path is not None else {}
    vendor_tooling = _load_json(vendor_tooling_receipt_path) if vendor_tooling_receipt_path is not None else {}
    repair_canary = _load_json(repair_canary_receipt_path)
    provider_matrix = _load_json(provider_matrix_receipt_path)
    receipt_freshness_ok, stale_receipts = _receipt_freshness_status(
        {
            "performance": performance,
            "tour_controls": tour_controls,
            "export_discovery": export_discovery,
            **({"billing_handoff": billing_receipt} if billing_receipt_path is not None else {}),
            "repair_canary": repair_canary,
            "provider_matrix": provider_matrix,
            **({"live_mobile_surfaces": live_mobile} if live_mobile_receipt_path is not None else {}),
            **({"public_auth_surfaces": public_smoke} if public_smoke_receipt_path is not None else {}),
            **({"authenticated_customer_surfaces": authenticated_smoke} if authenticated_smoke_receipt_path is not None else {}),
            **({"tour_provider_ownership": tour_provider_ownership} if tour_provider_ownership_receipt_path is not None else {}),
            **({"vendor_tooling": vendor_tooling} if vendor_tooling_receipt_path is not None else {}),
        },
        now=now,
        max_age_hours=max_receipt_age_hours,
    )

    missing_provider_modes = _missing_provider_modes(tour_controls)
    magicfit_playback = dict(tour_controls.get("magicfit_playback") or {})
    magicfit_ready = "magicfit" in {
        str(provider or "").strip().lower()
        for provider in list(tour_controls.get("ready_provider_modes") or [])
        if str(provider or "").strip()
    }
    magicfit_playback_ok = (
        not magicfit_ready
        or not magicfit_playback
        or magicfit_playback.get("playback_ok") is True
    )
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
    cross_country_sanitization_summary = dict(provider_matrix.get("cross_country_sanitization_summary") or {})
    cross_country_sanitization_ok = (
        cross_country_sanitization_summary.get("sanitization_ok") is True
        and int(cross_country_sanitization_summary.get("case_count") or 0) > 0
        and int(dict(cross_country_sanitization_summary.get("status_counts") or {}).get("fail") or 0) == 0
    )
    research_performance_ok, missing_research_performance_checks, research_performance_path = _performance_research_detail_checks(performance)
    search_performance_ok, missing_search_performance_checks, search_performance_path = _performance_search_checks(performance)
    analytics_ok, missing_analytics_checks, failed_analytics_checks, analytics_route_count = _performance_analytics_checks(performance)
    performance_ok = (
        performance.get("status") == "pass"
        and int(performance.get("failed_count") or 0) == 0
        and research_performance_ok
        and search_performance_ok
    )
    live_mobile_covered_routes = _covered_live_mobile_routes(live_mobile)
    missing_live_mobile_routes = [
        route for route in REQUIRED_LIVE_MOBILE_ROUTES if route not in live_mobile_covered_routes
    ]
    missing_live_mobile_detail_routes = [
        prefix
        for prefix in REQUIRED_LIVE_MOBILE_DETAIL_PREFIXES
        if not any(_route_covers_required_detail(route, prefix) for route in live_mobile_covered_routes)
    ]
    failed_live_mobile_coverage_checks = _failed_live_mobile_coverage_checks(live_mobile)
    live_mobile_ok = (
        live_mobile_receipt_path is None
        or (
            live_mobile.get("status") == "pass"
            and int(live_mobile.get("failed_count") or 0) == 0
            and int(live_mobile.get("route_count") or 0) >= len(REQUIRED_LIVE_MOBILE_ROUTES)
            and not missing_live_mobile_routes
            and not missing_live_mobile_detail_routes
            and not failed_live_mobile_coverage_checks
        )
    )
    public_sign_in_ok, missing_public_sign_in_checks, failed_public_sign_in_checks = _public_sign_in_checks(public_smoke)
    public_auth_ok = (
        public_smoke_receipt_path is None
        or (
            public_smoke.get("status") == "pass"
            and int(public_smoke.get("failed_count") or 0) == 0
            and public_sign_in_ok
        )
    )
    authenticated_billing_ok, missing_authenticated_billing_checks, failed_authenticated_billing_checks, authenticated_billing_status_code = _authenticated_billing_surface_checks(authenticated_smoke)
    authenticated_notifications_ok, missing_authenticated_notification_checks, failed_authenticated_notification_checks = _authenticated_account_notification_checks(authenticated_smoke)
    authenticated_customer_ok = (
        authenticated_smoke_receipt_path is None
        or (
            authenticated_smoke.get("status") == "pass"
            and int(authenticated_smoke.get("failed_count") or 0) == 0
            and authenticated_billing_ok
            and authenticated_notifications_ok
        )
    )
    tour_controls_ok = tour_controls.get("status") == "pass" and not missing_provider_modes and magicfit_playback_ok
    export_discovery_ok = export_discovery.get("status") in {"ready", "pass"}
    billing_ok = billing_receipt_path is None or _billing_handoff_ready(billing_receipt)
    manifest_providers = {
        str(provider or "").strip().lower()
        for provider in list(import_manifest.get("providers") or [])
        if str(provider or "").strip()
    }
    expected_import_providers = manifest_providers or {"3dvista", "pano2vr", "krpano", "magicfit"}
    prepared_drop_providers = {
        str(row.get("provider") or "").strip().lower()
        for row in list(import_manifest.get("prepared_drop_dirs") or [])
        if isinstance(row, dict)
    }
    hardened_readmes_ok, hardened_readme_provider_count, missing_hardened_readme_providers, hardened_readme_failures = _operator_drop_readme_status(
        import_manifest,
        expected_providers=expected_import_providers,
    )
    import_manifest_status = str(import_manifest.get("status") or "").strip()
    operator_import_manifest_ready = (
        import_manifest_status in {"ready_for_exports", "waiting_for_verified_assets", "partial_ready_for_import", "ready_for_import"}
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
        and cross_country_sanitization_ok
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
                "missing_search_checks": missing_search_performance_checks,
                "action": "rerun and fix propertyquarry_authenticated_performance_smoke until every measured route passes",
            }
        )
    if not analytics_ok:
        blockers.append(
            {
                "area": "analytics_privacy",
                "status": performance.get("status") or "unknown",
                "missing_checks": missing_analytics_checks,
                "failed_checks": failed_analytics_checks,
                "action": "rerun propertyquarry_authenticated_performance_smoke.py and keep Rybbit taxonomy, no-identify, allowed-attribute, and private-payload checks passing on measured app routes",
            }
        )
    if not live_mobile_ok:
        blockers.append(
            {
                "area": "live_mobile_surfaces",
                "status": live_mobile.get("status") or "unknown",
                "missing_routes": missing_live_mobile_routes,
                "missing_detail_routes": missing_live_mobile_detail_routes,
                "failed_coverage_checks": failed_live_mobile_coverage_checks,
                "action": "run propertyquarry_live_mobile_surface_smoke.py against the deployed stack with PROPERTYQUARRY_LIVE_RESEARCH_DETAIL_ROUTE and fix any overflow, chrome, touch-target, detail, or logout regressions",
            }
        )
    if not public_auth_ok:
        blockers.append(
            {
                "area": "public_auth_surfaces",
                "status": public_smoke.get("status") or "unknown",
                "missing_sign_in_checks": missing_public_sign_in_checks,
                "failed_sign_in_checks": failed_public_sign_in_checks,
                "action": "run propertyquarry_live_public_smoke.py against the deployed stack and fix provider sign-in account-creation copy, unavailable-copy, or provider-opening regressions",
            }
        )
    if not authenticated_customer_ok:
        blockers.append(
            {
                "area": "authenticated_customer_surfaces",
                "status": authenticated_smoke.get("status") or "unknown",
                "billing_status_code": authenticated_billing_status_code,
                "missing_billing_checks": missing_authenticated_billing_checks,
                "failed_billing_checks": failed_authenticated_billing_checks,
                "missing_notification_checks": missing_authenticated_notification_checks,
                "failed_notification_checks": failed_authenticated_notification_checks,
                "action": "run propertyquarry_live_authenticated_smoke.py against the deployed stack and keep /app/billing either redirected to a resolving external account lane or fail-closed without local billing-board copy, while /app/account keeps the notification routing form usable",
            }
        )
    if missing_provider_modes:
        blockers.append(
            {
                "area": "verified_tour_provider_modes",
                "missing_provider_modes": missing_provider_modes,
                "action": _tour_provider_evidence_action(missing_provider_modes),
            }
        )
    if not magicfit_playback_ok:
        blockers.append(
            {
                "area": "magicfit_walkthrough_playback",
                "status": "failed",
                "playable_count": magicfit_playback.get("playable_count"),
                "ready_count": magicfit_playback.get("ready_count"),
                "action": "rerun verify_property_tour_controls.py and keep MagicFit ready only when every ready MagicFit control has local playable or live-probed video evidence",
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
    if not billing_ok:
        billing_handoff = billing_receipt.get("billing_handoff") if isinstance(billing_receipt.get("billing_handoff"), dict) else {}
        blockers.append(
            {
                "area": "billing_handoff",
                "status": billing_receipt.get("status") or "missing",
                "error": billing_receipt.get("error") or "",
                "host": str(billing_handoff.get("host") or ""),
                "host_resolves": bool(billing_handoff.get("host_resolves")),
                "required_dns_record": billing_handoff.get("required_dns_record") if isinstance(billing_handoff.get("required_dns_record"), dict) else {},
                "next_action": str(billing_handoff.get("next_action") or ""),
                "action": "configure the white-label Brilliant Directories billing host so /app/billing redirects to a resolving external account lane",
            }
        )
    if import_manifest_receipt_path is not None and import_manifest_status in {"ready_for_exports", "waiting_for_verified_assets", "partial_ready_for_import", "ready_for_import"} and not hardened_readmes_ok:
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
                "cross_country_sanitization_ok": cross_country_sanitization_ok,
                "action": "run property_live_provider_smoke.py for all search-ready countries with --execute-search-matrix so every provider has strict/soft-filter evidence and wrong-country provider selections are sanitized before dispatch",
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
            **({"file_count": row.get("file_count")} if "file_count" in row else {}),
            **({"present_sample": row.get("present_sample")} if "present_sample" in row else {}),
            **({"entry_candidates": row.get("entry_candidates")} if "entry_candidates" in row else {}),
            **({"missing": row.get("missing")} if "missing" in row else {}),
            **({"missing_markers": row.get("missing_markers")} if "missing_markers" in row else {}),
        }
        for row in list(export_discovery.get("rejected") or [])[:6]
        if isinstance(row, dict)
    ]
    export_repair_sample = [
        {
            "slug": str(row.get("slug") or ""),
            "provider": str(row.get("provider") or ""),
            "status": str(row.get("status") or ""),
            "reason": str(row.get("reason") or ""),
            "required_action": str(row.get("required_action") or ""),
            "drop_path": str(row.get("drop_path") or ""),
            "import_command_after_assets_arrive": str(row.get("import_command_after_assets_arrive") or ""),
            **({"file_count": row.get("file_count")} if "file_count" in row else {}),
            **({"present_sample": row.get("present_sample")} if "present_sample" in row else {}),
            **({"entry_candidates": row.get("entry_candidates")} if "entry_candidates" in row else {}),
            **({"missing": row.get("missing")} if "missing" in row else {}),
            **({"missing_markers": row.get("missing_markers")} if "missing_markers" in row else {}),
        }
        for row in list(export_discovery.get("repair_manifest") or [])[:6]
        if isinstance(row, dict)
    ]
    missing_export_rejection_sample = [
        row
        for row in export_rejection_sample
        if str(row.get("provider") or "").strip().lower() in set(missing_provider_modes)
    ]
    if export_discovery.get("status") == "blocked_no_verified_exports":
        next_required_actions.append(
            {
                "provider": "_".join(missing_provider_modes) if missing_provider_modes else "verified_tour_exports",
                "action": (
                    missing_export_rejection_sample[0]["action"]
                    if missing_export_rejection_sample and missing_export_rejection_sample[0].get("action")
                    else _tour_provider_evidence_action(missing_provider_modes)
                ),
                "rejected_sample": missing_export_rejection_sample,
            }
        )

    operator_import_manifest_ok = import_manifest_receipt_path is None or operator_import_manifest_ready
    tour_provider_ownership_ok = (
        tour_provider_ownership_receipt_path is not None
        and tour_provider_ownership.get("status") == "pass"
        and not list(tour_provider_ownership.get("missing_providers") or [])
    )
    pass_areas = [
        {"area": "performance", "status": "pass", "receipt_path": str(performance_receipt_path)}
        if performance_ok
        else None,
        {"area": "analytics_privacy", "status": "pass", "receipt_path": str(performance_receipt_path)}
        if analytics_ok
        else None,
        {"area": "live_mobile_surfaces", "status": "pass", "receipt_path": str(live_mobile_receipt_path)}
        if live_mobile_receipt_path is not None and live_mobile_ok
        else None,
        {"area": "public_auth_surfaces", "status": "pass", "receipt_path": str(public_smoke_receipt_path)}
        if public_smoke_receipt_path is not None and public_auth_ok
        else None,
        {"area": "authenticated_customer_surfaces", "status": "pass", "receipt_path": str(authenticated_smoke_receipt_path)}
        if authenticated_smoke_receipt_path is not None and authenticated_customer_ok
        else None,
        {
            "area": "tour_provider_ownership",
            "status": "pass",
            "providers": sorted((tour_provider_ownership.get("providers") or {}).keys()),
            "receipt_path": str(tour_provider_ownership_receipt_path),
            "note": "Ownership/config proof only; verified exports are still required for gold tour readiness.",
        }
        if tour_provider_ownership_ok
        else None,
        {
            "area": "provider_targeted_search_matrix",
            "status": "pass",
            "targeted_search_matrix_count": provider_matrix.get("targeted_search_matrix_count"),
            "cross_country_sanitization_case_count": cross_country_sanitization_summary.get("case_count"),
            "receipt_path": str(provider_matrix_receipt_path),
        }
        if provider_matrix_ok
        else None,
        {"area": "self_healing", "status": "pass", "receipt_path": str(repair_canary_receipt_path)}
        if repair_canary_ok
        else None,
        {"area": "receipt_freshness", "status": "pass"}
        if receipt_freshness_ok
        else None,
    ]
    status = (
        "pass"
        if (
            performance_ok
            and analytics_ok
            and live_mobile_ok
            and public_auth_ok
            and authenticated_customer_ok
            and tour_controls_ok
            and export_discovery_ok
            and operator_import_manifest_ok
            and billing_ok
            and repair_canary_ok
            and provider_matrix_ok
            and receipt_freshness_ok
        )
        else "blocked"
    )
    billing_provider_status = str(
        billing_receipt.get("status") or ("not_configured" if billing_receipt_path is None else "missing")
    )
    billing_handoff_status = "ready" if billing_ok else billing_provider_status
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
            "search_path": search_performance_path,
            "search_checks_ok": search_performance_ok,
            "missing_search_checks": missing_search_performance_checks,
            "receipt_path": str(performance_receipt_path),
        },
        "analytics": {
            "status": "pass" if analytics_ok else "fail",
            "route_count": analytics_route_count,
            "required_checks": list(REQUIRED_RYBBIT_PERFORMANCE_CHECKS),
            "missing_checks": missing_analytics_checks,
            "failed_checks": failed_analytics_checks,
            "receipt_path": str(performance_receipt_path),
            "note": "This proves app-side Rybbit privacy and taxonomy hygiene, not external dashboard delivery.",
        },
        "live_mobile_surfaces": {
            "status": live_mobile.get("status") or ("not_configured" if live_mobile_receipt_path is None else "missing"),
            "failed_count": live_mobile.get("failed_count"),
            "route_count": live_mobile.get("route_count"),
            "required_route_count": len(REQUIRED_LIVE_MOBILE_ROUTES),
            "missing_routes": missing_live_mobile_routes,
            "required_detail_prefixes": list(REQUIRED_LIVE_MOBILE_DETAIL_PREFIXES),
            "missing_detail_routes": missing_live_mobile_detail_routes,
            "failed_coverage_checks": failed_live_mobile_coverage_checks,
            "viewport": live_mobile.get("viewport"),
            "receipt_path": str(live_mobile_receipt_path) if live_mobile_receipt_path is not None else "",
        },
        "public_auth_surfaces": {
            "status": public_smoke.get("status") or ("not_configured" if public_smoke_receipt_path is None else "missing"),
            "failed_count": public_smoke.get("failed_count"),
            "route_count": public_smoke.get("route_count"),
            "sign_in_checks_ok": public_sign_in_ok if public_smoke_receipt_path is not None else None,
            "missing_sign_in_checks": missing_public_sign_in_checks if public_smoke_receipt_path is not None else [],
            "failed_sign_in_checks": failed_public_sign_in_checks if public_smoke_receipt_path is not None else [],
            "receipt_path": str(public_smoke_receipt_path) if public_smoke_receipt_path is not None else "",
        },
        "authenticated_customer_surfaces": {
            "status": authenticated_smoke.get("status") or ("not_configured" if authenticated_smoke_receipt_path is None else "missing"),
            "failed_count": authenticated_smoke.get("failed_count"),
            "route_count": authenticated_smoke.get("route_count"),
            "billing_checks_ok": authenticated_billing_ok if authenticated_smoke_receipt_path is not None else None,
            "billing_status_code": authenticated_billing_status_code,
            "missing_billing_checks": missing_authenticated_billing_checks if authenticated_smoke_receipt_path is not None else [],
            "failed_billing_checks": failed_authenticated_billing_checks if authenticated_smoke_receipt_path is not None else [],
            "notification_checks_ok": authenticated_notifications_ok if authenticated_smoke_receipt_path is not None else None,
            "missing_notification_checks": missing_authenticated_notification_checks if authenticated_smoke_receipt_path is not None else [],
            "failed_notification_checks": failed_authenticated_notification_checks if authenticated_smoke_receipt_path is not None else [],
            "receipt_path": str(authenticated_smoke_receipt_path) if authenticated_smoke_receipt_path is not None else "",
        },
        "tour_controls": {
            "status": tour_controls.get("status"),
            "provider_counts": tour_controls.get("provider_counts"),
            "provider_blockers": tour_controls.get("provider_blockers"),
            "magicfit_playback": magicfit_playback,
            "magicfit_playback_ok": magicfit_playback_ok,
            "ready_provider_modes": tour_controls.get("ready_provider_modes"),
            "missing_provider_modes": missing_provider_modes,
            "receipt_path": str(tour_control_receipt_path),
        },
        "export_discovery": {
            "status": export_discovery.get("status"),
            "import_count": export_discovery.get("import_count"),
            "rejected_count": export_discovery.get("rejected_count"),
            "repair_count": export_discovery.get("repair_count"),
            "rejected_sample": export_rejection_sample,
            "repair_sample": export_repair_sample,
            "receipt_path": str(export_discovery_receipt_path),
        },
        "operator_import_manifest": {
            "status": import_manifest.get("status") or ("not_configured" if import_manifest_receipt_path is None else "missing"),
            "ready_for_exports": operator_import_manifest_ready,
            "import_count": import_manifest.get("import_count"),
            "drop_status_summary": import_manifest.get("drop_status_summary") or {},
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
        "billing_handoff": {
            "status": billing_handoff_status,
            "provider_status": billing_provider_status,
            "error": billing_receipt.get("error") or "",
            "configured": bool((billing_receipt.get("billing_handoff") or {}).get("configured")) if isinstance(billing_receipt.get("billing_handoff"), dict) else False,
            "host": str((billing_receipt.get("billing_handoff") or {}).get("host") or "") if isinstance(billing_receipt.get("billing_handoff"), dict) else "",
            "host_resolves": bool((billing_receipt.get("billing_handoff") or {}).get("host_resolves")) if isinstance(billing_receipt.get("billing_handoff"), dict) else False,
            "required_dns_record": (billing_receipt.get("billing_handoff") or {}).get("required_dns_record") if isinstance(billing_receipt.get("billing_handoff"), dict) and isinstance((billing_receipt.get("billing_handoff") or {}).get("required_dns_record"), dict) else {},
            "next_action": str((billing_receipt.get("billing_handoff") or {}).get("next_action") or "") if isinstance(billing_receipt.get("billing_handoff"), dict) else "",
            "ready": billing_ok,
            "receipt_path": str(billing_receipt_path) if billing_receipt_path is not None else "",
        },
        "vendor_tooling": {
            "status": vendor_tooling.get("status") or ("not_configured" if vendor_tooling_receipt_path is None else "missing"),
            "mode": str(vendor_tooling.get("mode") or "") if vendor_tooling_receipt_path is not None else "",
            "host_ready": vendor_tooling.get("host_ready") if vendor_tooling_receipt_path is not None else None,
            "generated_tour_ready": bool(vendor_tooling.get("generated_tour_ready")) if vendor_tooling_receipt_path is not None else None,
            "generated_tour_tools": vendor_tooling.get("generated_tour_tools") or {},
            "runtime_generated_tour_ready": vendor_tooling.get("runtime_generated_tour_ready") if vendor_tooling_receipt_path is not None else None,
            "runtime_generated_tour_tools": vendor_tooling.get("runtime_generated_tour_tools") or {},
            "wine_runtime_ready": bool(vendor_tooling.get("wine_runtime_ready")) if vendor_tooling_receipt_path is not None else None,
            "installer_count": vendor_tooling.get("installer_count") if vendor_tooling_receipt_path is not None else None,
            "installer_counts": vendor_tooling.get("installer_counts") or {},
            "installed_app_count": vendor_tooling.get("installed_app_count") if vendor_tooling_receipt_path is not None else None,
            "installed_app_counts": vendor_tooling.get("installed_app_counts") or {},
            "installed_apps": vendor_tooling.get("installed_apps") or [],
            "verified_export_ready_counts": vendor_tooling.get("verified_export_ready_counts") or {},
            "missing_verified_exports": vendor_tooling.get("missing_verified_exports") or [],
            "next_actions": vendor_tooling.get("next_actions") or [],
            "receipt_path": str(vendor_tooling_receipt_path) if vendor_tooling_receipt_path is not None else "",
            "note": "Host tooling readiness is tracked separately from verified 3DVista/Pano2VR export evidence.",
        },
        "tour_provider_ownership": {
            "status": tour_provider_ownership.get("status") or ("not_configured" if tour_provider_ownership_receipt_path is None else "missing"),
            "missing_providers": tour_provider_ownership.get("missing_providers") or [],
            "providers": sorted((tour_provider_ownership.get("providers") or {}).keys()) if isinstance(tour_provider_ownership.get("providers"), dict) else [],
            "ready": tour_provider_ownership_ok,
            "receipt_path": str(tour_provider_ownership_receipt_path) if tour_provider_ownership_receipt_path is not None else "",
            "note": "This does not satisfy 3D-tour gold without verified 3DVista/Pano2VR exports or allowlisted hosted controls.",
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
            "passed_case_count": provider_matrix_summary.get("passed_case_count"),
            "failed_case_count": provider_matrix_summary.get("failed_case_count"),
            "agent_unlimited_results_ok": provider_matrix_summary.get("agent_unlimited_results_ok"),
            "strict_without_soft_filters_ok": provider_matrix_summary.get("strict_without_soft_filters_ok"),
            "soft_filters_present_ok": provider_matrix_summary.get("soft_filters_present_ok"),
            "dispatch_acceptance_complete": provider_matrix_summary.get("dispatch_acceptance_complete"),
            "status_readback_complete": provider_matrix_summary.get("status_readback_complete"),
            "payload_contracts_ok": provider_matrix_summary.get("payload_contracts_ok"),
            "all_search_ready_provider_modes_passed": provider_matrix_modes_ok,
            "provider_country_scope_ok": provider_matrix_country_scope_ok,
            "target_context_country_scope_ok": provider_matrix_target_context_ok,
            "cross_country_sanitization_ok": cross_country_sanitization_ok,
            "cross_country_sanitization_case_count": cross_country_sanitization_summary.get("case_count"),
            "receipt_path": str(provider_matrix_receipt_path),
        },
        "receipt_freshness": {
            "status": "pass" if receipt_freshness_ok else "fail",
            "max_age_hours": max_receipt_age_hours,
            "stale_receipts": stale_receipts,
        },
        "blockers": blockers,
        "pass_areas": [row for row in pass_areas if row is not None],
        "next_required_actions": next_required_actions,
        "notes": [
            "Gold is not claimable until every required provider mode is backed by verified evidence.",
            "Self-healing is proven only when the repair canary repairs or safely quarantines a failed provider source.",
            "Provider E2E is proven only when every search-ready provider has executed strict and soft-filter targeted search cases.",
            _tour_provider_missing_note(missing_provider_modes),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize current PropertyQuarry gold-readiness receipts.")
    parser.add_argument("--performance-receipt", default="")
    parser.add_argument("--live-mobile-receipt", default="")
    parser.add_argument("--public-smoke-receipt", default="")
    parser.add_argument("--authenticated-smoke-receipt", default="")
    parser.add_argument("--tour-control-receipt", default="")
    parser.add_argument("--export-discovery-receipt", default="")
    parser.add_argument("--import-manifest-receipt", default="")
    parser.add_argument("--billing-receipt", default="")
    parser.add_argument("--tour-provider-ownership-receipt", default="")
    parser.add_argument("--vendor-tooling-receipt", default="")
    parser.add_argument("--repair-canary-receipt", default="")
    parser.add_argument("--provider-matrix-receipt", default="")
    parser.add_argument("--write", default="_completion/property_gold_status/latest.json")
    parser.add_argument("--max-receipt-age-hours", type=float, default=24.0)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    receipt = build_gold_status_receipt(
        performance_receipt_path=Path(args.performance_receipt) if args.performance_receipt else _default_receipt_path("performance"),
        live_mobile_receipt_path=Path(args.live_mobile_receipt) if args.live_mobile_receipt else _default_receipt_path("live_mobile"),
        public_smoke_receipt_path=Path(args.public_smoke_receipt) if args.public_smoke_receipt else _default_receipt_path("public_smoke"),
        authenticated_smoke_receipt_path=Path(args.authenticated_smoke_receipt) if args.authenticated_smoke_receipt else _default_receipt_path("authenticated_smoke"),
        tour_control_receipt_path=Path(args.tour_control_receipt) if args.tour_control_receipt else _default_receipt_path("tour_control"),
        export_discovery_receipt_path=Path(args.export_discovery_receipt) if args.export_discovery_receipt else _default_receipt_path("export_discovery"),
        import_manifest_receipt_path=Path(args.import_manifest_receipt) if args.import_manifest_receipt else _default_receipt_path("import_manifest"),
        billing_receipt_path=Path(args.billing_receipt) if args.billing_receipt else _default_receipt_path("billing"),
        tour_provider_ownership_receipt_path=Path(args.tour_provider_ownership_receipt) if args.tour_provider_ownership_receipt else None,
        vendor_tooling_receipt_path=Path(args.vendor_tooling_receipt) if args.vendor_tooling_receipt else _default_receipt_path("vendor_tooling"),
        repair_canary_receipt_path=Path(args.repair_canary_receipt) if args.repair_canary_receipt else _default_receipt_path("repair_canary"),
        provider_matrix_receipt_path=Path(args.provider_matrix_receipt) if args.provider_matrix_receipt else _default_receipt_path("provider_matrix"),
        max_receipt_age_hours=args.max_receipt_age_hours,
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    try:
        print(output)
    except BrokenPipeError:
        with contextlib.suppress(Exception):
            sys.stdout.close()
    if receipt.get("status") == "pass":
        return 0
    return 2 if args.fail_on_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
