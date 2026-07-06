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


REQUIRED_TOUR_PROVIDER_MODES = ("matterport", "3dvista", "magicfit")
OPTIONAL_TOUR_PROVIDER_MODES = ("pano2vr", "krpano")
ACTIVE_PROVIDER_MATRIX_COUNTRY_CODES = ("AT", "DE", "CR")
REQUIRED_RESEARCH_PERFORMANCE_CHECKS = (
    "research_candidate",
    "research_visual_cards_present",
    "research_visual_requests_honest",
    "research_no_fake_visual_ready",
    "research_listing_facts",
    "research_listed_price_signal",
    "research_ranking_only_no_compare_cards",
    "research_mobile_open_property_compact_layout",
    "research_mobile_visual_frame_compact",
)
REQUIRED_SEARCH_PERFORMANCE_CHECKS = (
    "search_gzip_delivery",
    "search_gzip_vary_accept_encoding",
    "search_compressed_payload_under_budget",
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
    "/app/properties",
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
REQUIRED_LIVE_MOBILE_COVERAGE_CHECKS = (
    "research_detail_route_configured",
    "registry_mobile_customer_surfaces_covered",
)
REQUIRED_PUBLIC_AUTH_CHECKS = (
    "sign_in_minimal_copy",
    "sign_in_connected_identity_creates_account",
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
BILLING_MEMBER_TOKEN_REQUIRED_ENV = (
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY",
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER",
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_ENABLED",
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET",
)
BILLING_MEMBER_TOKEN_ADMIN_ACTION = (
    "generate a Brilliant Directories API key in the admin backend, confirm the member-login token account lane, "
    "then set PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY, PROPERTYQUARRY_BRILLIANT_DIRECTORIES_API_KEY_HEADER, "
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_ENABLED=1, and "
    "PROPERTYQUARRY_BRILLIANT_DIRECTORIES_MEMBER_LOGIN_TOKEN_SECRET so /app/billing opens without a second login"
)
COMMON_OPERATOR_DROP_README_TOKENS = (
    ("title", "PropertyQuarry provider export drop folder"),
    ("no_placeholders", "Do not copy placeholder HTML"),
    ("dry_import", "Single-provider dry import example:"),
    ("gold_gate", "Public gold only passes when verify_property_tour_controls reports ready provider modes"),
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
    "live_mobile": (
        "state/receipts/propertyquarry_live_mobile*.json",
        "state/receipts/property_live_mobile*.json",
        "_completion/smoke/property-live-mobile*.json",
    ),
    "public_smoke": (
        "state/receipts/propertyquarry_live_public*.json",
        "state/receipts/property_live_public*.json",
        "_completion/smoke/property-live-public*.json",
    ),
    "authenticated_smoke": (
        "state/receipts/propertyquarry_live_authenticated*.json",
        "state/receipts/property_live_authenticated*.json",
        "_completion/smoke/property-live-authenticated*.json",
    ),
    "tour_control": (
        "_completion/property_tour_controls/*.json",
        "_completion/tours/property-tour-controls*.json",
    ),
    "export_discovery": ("_completion/tours/property-tour-export-discovery*.json",),
    "import_manifest": ("_completion/property_tour_exports/import-manifest*.json",),
    "billing": ("_completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION*.json",),
    "tour_provider_ownership": ("_completion/property_tour_ownership/*.json",),
    "vendor_tooling": ("_completion/tours/property-tour-vendor-tooling*.json",),
    "repair_canary": ("_completion/repair/propertyquarry-repair-canary*.json",),
    "provider_catalog": ("_completion/smoke/property-live-provider-catalog*.json",),
    "provider_matrix": (
        "state/receipts/property_provider_stage*.json",
        "state/receipts/property_live_provider_smoke*.json",
        "state/receipts/property-provider-e2e*.json",
        "_completion/smoke/property-live-provider*.json",
        "_completion/provider_smoke/*provider-matrix*.json",
        "_completion/provider_smoke/all-search-ready*.json",
        "_completion/smoke/property-provider-e2e*.json",
    ),
    "whole_project_scope": ("_completion/whole_project_scope/property-whole-project-scope*.json",),
    "security_posture": ("_completion/security/property-security-posture*.json",),
    "release_hygiene": ("_completion/release_hygiene/property-release-hygiene*.json",),
    "furniture_style_contract": ("_completion/furniture_styles/property-furniture-style-contract*.json",),
    "bts_methodology_contract": ("_completion/bts_methodology/property-bts-methodology-contract*.json",),
    "tour_delivery_contract": ("_completion/tour_delivery/property-tour-delivery-contract*.json",),
    "map_preview_flagship": ("_completion/smoke/property-live-map-preview-flagship*.json",),
    "browser_3d_gate": ("_completion/smoke/property-live-3d-browser-gate*.json",),
    "runtime_reconstruction": ("_completion/tours/property-runtime-reconstruction*.json",),
    "walkthrough_quality": ("_completion/smoke/property-live-walkthrough-quality*.json",),
    "scene_video_readiness": (
        "_completion/scene_video_readiness/release-gate.json",
        "_completion/scene_video_readiness/PROPERTY_SCENE_VIDEO_READINESS.generated.json",
        "_completion/scene_video_readiness/property-scene-video-readiness*.json",
    ),
    "scene_video_readiness_verifier": (
        "_completion/scene_video_readiness/release-gate-verifier.json",
        "_completion/scene_video_readiness/*readiness-verifier*.json",
    ),
    "scene_video_provider_refresh_packet": (
        "_completion/scene_video_readiness/provider-refresh-packet.json",
        "_completion/scene_video_readiness/property-scene-video-provider-refresh-packet*.json",
    ),
    "scene_video_provider_refresh_packet_verifier": (
        "_completion/scene_video_readiness/provider-refresh-packet-verifier.json",
        "_completion/scene_video_readiness/*provider-refresh-packet-verifier*.json",
    ),
    "id_austria": ("_completion/id_austria/ID_AUSTRIA_PROVIDER_VERIFICATION*.json",),
}
DEFAULT_RECEIPT_FALLBACKS = {
    "performance": "_completion/smoke/property-auth-performance-latest.json",
    "live_mobile": "_completion/smoke/property-live-mobile-surface-latest.json",
    "public_smoke": "_completion/smoke/property-live-public-latest.json",
    "authenticated_smoke": "_completion/smoke/property-live-authenticated-latest.json",
    "tour_control": "_completion/tours/property-tour-controls-live-container-current.json",
    "export_discovery": "_completion/tours/property-tour-export-discovery-full-current.json",
    "import_manifest": "_completion/property_tour_exports/import-manifest-current.json",
    "billing": "_completion/brilliant_directories/BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json",
    "tour_provider_ownership": "_completion/property_tour_ownership/release-gate.json",
    "vendor_tooling": "_completion/tours/property-tour-vendor-tooling-current.json",
    "repair_canary": "_completion/repair/propertyquarry-repair-canary-latest.json",
    "provider_catalog": "_completion/smoke/property-live-provider-catalog-latest.json",
    "provider_matrix": "_completion/smoke/property-live-provider-latest.json",
    "whole_project_scope": "_completion/whole_project_scope/property-whole-project-scope-latest.json",
    "security_posture": "_completion/security/property-security-posture-latest.json",
    "release_hygiene": "_completion/release_hygiene/property-release-hygiene-latest.json",
    "furniture_style_contract": "_completion/furniture_styles/property-furniture-style-contract-latest.json",
    "bts_methodology_contract": "_completion/bts_methodology/property-bts-methodology-contract-latest.json",
    "tour_delivery_contract": "_completion/tour_delivery/property-tour-delivery-contract-latest.json",
    "map_preview_flagship": "_completion/smoke/property-live-map-preview-flagship-latest.json",
    "browser_3d_gate": "_completion/smoke/property-live-3d-browser-gate-latest.json",
    "runtime_reconstruction": "_completion/tours/property-runtime-reconstruction-release-gate.json",
    "walkthrough_quality": "_completion/smoke/property-live-walkthrough-quality-latest.json",
    "scene_video_readiness": "_completion/scene_video_readiness/release-gate.json",
    "scene_video_readiness_verifier": "_completion/scene_video_readiness/release-gate-verifier.json",
    "scene_video_provider_refresh_packet": "_completion/scene_video_readiness/provider-refresh-packet.json",
    "scene_video_provider_refresh_packet_verifier": "_completion/scene_video_readiness/provider-refresh-packet-verifier.json",
    "id_austria": "_completion/id_austria/ID_AUSTRIA_PROVIDER_VERIFICATION.generated.json",
}

_CANONICAL_GOLD_STATUS_LATEST_PATHS = (
    "_completion/property_gold_status/latest.json",
    "_completion/propertyquarry-gold-status-latest.json",
)
_CANONICAL_GOLD_STATUS_RELEASE_GATE_PATH = "_completion/property_gold_status/release-gate.json"


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


def _receipt_is_complete_enough(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status in {"running", "in_progress", "verifying"}:
        return False
    if payload.get("checkpoint") is True:
        return False
    if payload.get("complete") is False:
        return False
    return True


def _provider_matrix_proof_rank(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    if "targeted_search_matrix_status" not in payload and "targeted_search_matrix_summary" not in payload:
        return 0

    summary = dict(payload.get("targeted_search_matrix_summary") or {})
    status = str(payload.get("status") or "").strip().lower()
    targeted_status = str(payload.get("targeted_search_matrix_status") or "").strip().lower()
    executed = payload.get("targeted_search_matrix_executed") is True
    summary_executed = summary.get("executed") is True
    providers_covered = summary.get("all_search_ready_providers_covered") is True

    if status == "pass" and targeted_status == "pass" and executed and summary_executed and providers_covered:
        return 3
    if executed and summary_executed:
        return 2
    if executed or status == "pass":
        return 1
    return 0


def _provider_matrix_proof_coverage(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    summary = dict(payload.get("targeted_search_matrix_summary") or {})
    counts: list[int] = []
    for raw_value in (
        payload.get("targeted_search_matrix_count"),
        summary.get("case_count"),
        summary.get("executed_case_count"),
        summary.get("passed_case_count"),
    ):
        try:
            parsed = int(raw_value or 0)
        except Exception:
            parsed = 0
        if parsed > 0:
            counts.append(parsed)
    try:
        strict_case_count = int(summary.get("strict_case_count") or 0)
    except Exception:
        strict_case_count = 0
    try:
        soft_case_count = int(summary.get("soft_filter_case_count") or 0)
    except Exception:
        soft_case_count = 0
    if strict_case_count > 0 or soft_case_count > 0:
        counts.append(strict_case_count + soft_case_count)
    targeted_rows = [
        row for row in list(payload.get("targeted_search_matrix") or [])
        if isinstance(row, dict)
    ]
    if targeted_rows:
        counts.append(len(targeted_rows))
    return max(counts, default=0)


def _provider_matrix_scope_rank(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    summary = dict(payload.get("targeted_search_matrix_summary") or {})
    raw_country_codes = summary.get("country_codes")
    if not isinstance(raw_country_codes, list):
        raw_country_codes = payload.get("country_codes")
    country_codes = tuple(
        dict.fromkeys(
            str(country or "").strip().upper()
            for country in list(raw_country_codes or [])
            if str(country or "").strip()
        )
    )
    if not country_codes:
        return 0
    if tuple(sorted(country_codes)) != tuple(sorted(ACTIVE_PROVIDER_MATRIX_COUNTRY_CODES)):
        return 0
    country_scope = str(payload.get("country_scope") or "").strip().lower()
    if country_scope in {"explicit", "all_search_ready"}:
        return 2
    return 1


def _provider_catalog_smoke_summary(payload: dict[str, Any], receipt_path: Path | None) -> dict[str, Any]:
    if receipt_path is None:
        return {
            "status": "not_configured",
            "raw_status": "",
            "check_count": 0,
            "failed_checks": [],
            "targeted_search_matrix_executed": None,
            "targeted_search_matrix_status": "",
            "receipt_path": "",
            "note": "No separate provider-catalog smoke receipt was supplied.",
        }

    checks = [row for row in list(payload.get("checks") or []) if isinstance(row, dict)]
    failed_checks = [
        {
            "country_code": row.get("country_code"),
            "status": row.get("status") or "unknown",
            "runtime_provider_count_ok": row.get("runtime_provider_count_ok"),
            "runtime_defaults_present_ok": row.get("runtime_defaults_present_ok"),
            "runtime_provider_country_scope_ok": row.get("runtime_provider_country_scope_ok"),
        }
        for row in checks
        if row.get("status") != "pass"
        or row.get("runtime_provider_count_ok") is False
        or row.get("runtime_defaults_present_ok") is False
        or row.get("runtime_provider_country_scope_ok") is False
    ]
    cross_country_summary = dict(payload.get("cross_country_sanitization_summary") or {})
    cross_country_failed = (
        bool(cross_country_summary)
        and (
            cross_country_summary.get("sanitization_ok") is False
            or int(dict(cross_country_summary.get("status_counts") or {}).get("fail") or 0) > 0
        )
    )
    if cross_country_failed:
        failed_checks.append(
            {
                "country_code": "cross_country_sanitization",
                "status": "fail",
                "runtime_provider_count_ok": None,
                "runtime_defaults_present_ok": None,
                "runtime_provider_country_scope_ok": cross_country_summary.get("sanitization_ok"),
            }
        )

    raw_status = str(payload.get("status") or "unknown")
    missing_or_invalid = raw_status in {"missing", "invalid", "unknown"}
    checks_ok = bool(checks) and not failed_checks and not missing_or_invalid
    return {
        "status": "pass" if checks_ok else "blocked",
        "raw_status": raw_status,
        "check_count": len(checks),
        "failed_checks": failed_checks[:12],
        "targeted_search_matrix_executed": payload.get("targeted_search_matrix_executed"),
        "targeted_search_matrix_status": payload.get("targeted_search_matrix_status"),
        "receipt_path": str(receipt_path),
        "note": "Catalog smoke checks provider/default-provider runtime parity. The strict/soft targeted search matrix is reported under provider_matrix.",
    }


def _latest_receipt_path(patterns: tuple[str, ...], *, fallback: str) -> Path:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in Path().glob(pattern) if path.is_file())
    if not candidates:
        return Path(fallback).expanduser().resolve()

    def sort_key(path: Path) -> tuple[int, int, float, float, str]:
        payload = _load_json(path)
        completeness_rank = 1 if _receipt_is_complete_enough(payload) else 0
        provider_matrix_rank = _provider_matrix_proof_rank(payload)
        provider_matrix_scope_rank = _provider_matrix_scope_rank(payload)
        provider_matrix_coverage = _provider_matrix_proof_coverage(payload)
        generated_at, _timestamp_source, _raw_generated_at = _receipt_generated_at(payload)
        generated_timestamp = generated_at.timestamp() if generated_at is not None else 0.0
        try:
            modified_timestamp = path.stat().st_mtime
        except OSError:
            modified_timestamp = 0.0
        return (
            completeness_rank,
            provider_matrix_rank,
            provider_matrix_scope_rank,
            provider_matrix_coverage,
            generated_timestamp,
            modified_timestamp,
            path.as_posix(),
        )

    return max(candidates, key=sort_key).resolve()


def _default_receipt_path(name: str) -> Path:
    if name == "tour_control":
        canonical_path = Path(DEFAULT_RECEIPT_FALLBACKS[name]).expanduser().resolve()
        if canonical_path.is_file() and _receipt_is_complete_enough(_load_json(canonical_path)):
            return canonical_path
    return _latest_receipt_path(
        DEFAULT_RECEIPT_PATTERNS[name],
        fallback=DEFAULT_RECEIPT_FALLBACKS[name],
    )


def _default_receipt_path_if_exists(name: str) -> Path | None:
    path = _default_receipt_path(name)
    return path if path.is_file() else None


def _canonical_gold_status_alias_targets(output_path: Path) -> list[Path]:
    resolved_output = output_path.expanduser().resolve()
    latest_targets = [Path(path).expanduser().resolve() for path in _CANONICAL_GOLD_STATUS_LATEST_PATHS]
    release_gate_target = Path(_CANONICAL_GOLD_STATUS_RELEASE_GATE_PATH).expanduser().resolve()

    if resolved_output == release_gate_target:
        return [path for path in latest_targets if path != resolved_output]
    if resolved_output in latest_targets:
        return [path for path in latest_targets if path != resolved_output]
    return []


def _write_gold_status_output(output_path: Path, output: str) -> list[str]:
    resolved_output = output_path.expanduser().resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    rendered = output if output.endswith("\n") else f"{output}\n"
    resolved_output.write_text(rendered, encoding="utf-8")

    synced: list[str] = []
    for alias_path in _canonical_gold_status_alias_targets(resolved_output):
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        alias_path.write_text(rendered, encoding="utf-8")
        synced.append(str(alias_path))
    return synced


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
    required_modes = {
        str(provider or "").strip().lower()
        for provider in list(tour_receipt.get("required_provider_modes") or [])
        if str(provider or "").strip()
    } or set(REQUIRED_TOUR_PROVIDER_MODES)
    required_modes.intersection_update(REQUIRED_TOUR_PROVIDER_MODES)
    if not required_modes:
        required_modes = set(REQUIRED_TOUR_PROVIDER_MODES)
    ready = {
        str(provider or "").strip().lower()
        for provider in list(tour_receipt.get("ready_provider_modes") or [])
        if str(provider or "").strip()
    }
    missing = [
        provider
        for provider in REQUIRED_TOUR_PROVIDER_MODES
        if provider in required_modes and provider not in ready
    ]
    explicit_missing = [
        str(provider or "").strip().lower()
        for provider in list(tour_receipt.get("missing_provider_modes") or [])
        if str(provider or "").strip().lower() in required_modes
    ]
    for provider in explicit_missing:
        if provider not in missing:
            missing.append(provider)
    return missing


def _tour_provider_evidence_action(missing_provider_modes: list[str]) -> str:
    actions = {
        "matterport": "verified hosted 3D model URL/control receipt",
        "3dvista": "verified branded 3D tour export or allowlisted hosted tour URL",
        "pano2vr": "verified panorama tour export",
        "krpano": "optional operator-only panorama scene evidence",
        "magicfit": "receipt-backed playable walkthrough",
    }
    provider_labels = {
        "matterport": "Matterport",
        "3dvista": "3DVista",
        "pano2vr": "Pano2VR",
        "krpano": "krpano",
        "magicfit": "walkthrough",
    }
    parts = [
        f"{provider_labels.get(provider, provider)}: {actions[provider]}"
        for provider in missing_provider_modes
        if provider in actions
    ]
    if not parts:
        return "rerun verify_property_tour_controls.py and attach any provider evidence it still reports missing"
    return f"attach real provider evidence for missing modes only: {', '.join(parts)}"


def _tour_provider_missing_note(missing_provider_modes: list[str]) -> str:
    provider_labels = {
        "matterport": "Matterport",
        "3dvista": "3DVista",
        "pano2vr": "Pano2VR",
        "krpano": "krpano",
        "magicfit": "MagicFit",
    }
    labels = {
        "matterport": "Matterport hosted 3D model",
        "3dvista": "3DVista branded 3D tour export",
        "pano2vr": "Pano2VR panorama tour export",
        "krpano": "optional krpano panorama/cube viewer",
        "magicfit": "MagicFit playable walkthrough",
    }
    providers = [provider_labels[provider] for provider in missing_provider_modes if provider in provider_labels]
    names = [labels[provider] for provider in missing_provider_modes if provider in labels]
    if not names:
        return "This receipt has no missing tour provider modes in the active verifier output."
    provider_joined = ", ".join(providers)
    joined = ", ".join(names)
    return f"This receipt intentionally treats missing {provider_joined} evidence ({joined}) as blocked rather than pass."


def _magicfit_renderer_summary(vendor_tooling: dict[str, Any], *, receipt_present: bool) -> dict[str, Any]:
    renderer = dict(vendor_tooling.get("magicfit_renderer") or {}) if receipt_present else {}
    python_modules = renderer.get("python_modules") if isinstance(renderer.get("python_modules"), dict) else {}
    missing_python_modules = [
        module
        for module, status in python_modules.items()
        if not isinstance(status, dict) or not bool(status.get("available"))
    ]
    return {
        "status": str(renderer.get("status") or ("not_configured" if not receipt_present else "missing")),
        "script_path": str(renderer.get("script_path") or "") if receipt_present else "",
        "script_ready": (
            bool(renderer.get("script_ready"))
            if receipt_present and "script_ready" in renderer
            else None
        ),
        "credentials_configured": (
            bool(renderer.get("credentials_configured"))
            if receipt_present and "credentials_configured" in renderer
            else None
        ),
        "credential_sources": list(renderer.get("credential_sources") or []) if receipt_present else [],
        "env_files_checked": list(renderer.get("env_files_checked") or []) if receipt_present else [],
        "python_modules_ready": (
            bool(renderer.get("python_modules_ready"))
            if receipt_present and "python_modules_ready" in renderer
            else None
        ),
        "python_modules": python_modules,
        "missing_python_modules": missing_python_modules,
        "ready": bool(renderer.get("ready")) if receipt_present and "ready" in renderer else None,
        "next_action": str(renderer.get("next_action") or "") if receipt_present else "",
        "note": str(renderer.get("note") or "") if receipt_present else "",
    }


def _omagic_adapter_summary(vendor_tooling: dict[str, Any], *, receipt_present: bool) -> dict[str, Any]:
    adapter = dict(vendor_tooling.get("omagic_adapter") or {}) if receipt_present else {}
    runtime_script = dict(adapter.get("runtime_script") or {})
    return {
        "status": str(adapter.get("status") or ("not_configured" if not receipt_present else "missing")),
        "ready": bool(adapter.get("ready")) if receipt_present and "ready" in adapter else None,
        "script_path": str(adapter.get("script_path") or "") if receipt_present else "",
        "script_ready": bool(adapter.get("script_ready")) if receipt_present and "script_ready" in adapter else None,
        "runtime_checked": bool(adapter.get("runtime_checked")) if receipt_present and "runtime_checked" in adapter else False,
        "runtime_script_ready": adapter.get("runtime_script_ready") if receipt_present else None,
        "runtime_script": runtime_script,
        "model_upload_enable_env": str(adapter.get("model_upload_enable_env") or "") if receipt_present else "",
        "model_upload_adapter_enabled": bool(adapter.get("model_upload_adapter_enabled")) if receipt_present and "model_upload_adapter_enabled" in adapter else None,
        "render_endpoint_env_names": list(adapter.get("render_endpoint_env_names") or []) if receipt_present else [],
        "render_command_env_names": list(adapter.get("render_command_env_names") or []) if receipt_present else [],
        "render_target_configured": bool(adapter.get("render_target_configured")) if receipt_present and "render_target_configured" in adapter else None,
        "credential_env_names": list(adapter.get("credential_env_names") or []) if receipt_present else [],
        "next_action": str(adapter.get("next_action") or "") if receipt_present else "",
        "note": str(adapter.get("note") or "") if receipt_present else "",
    }


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
    observed_names: set[str] = set()
    for row in list(live_mobile.get("coverage_checks") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "unnamed_coverage_check")
        observed_names.add(name)
        if row.get("ok") is True:
            continue
        failed.append(
            {
                "name": name,
                "required_route_prefix": str(row.get("required_route_prefix") or ""),
                "reason": str(row.get("reason") or ""),
            }
        )
    for required_name in REQUIRED_LIVE_MOBILE_COVERAGE_CHECKS:
        if required_name not in observed_names:
            failed.append(
                {
                    "name": required_name,
                    "required_route_prefix": "/app/research/" if required_name == "research_detail_route_configured" else "",
                    "reason": "Live mobile receipt predates the required all-surface coverage contract.",
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
        ("billing_external_handoff" in passed_checks and "billing_no_second_login" in passed_checks)
        or "billing_fail_closed_recovery" in passed_checks
        or ("billing_bridge_launch" in passed_checks and "billing_internal_account_fallback" in passed_checks)
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


def _failed_receipt_checks(receipt: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for row in list(receipt.get("checks") or []):
        if not isinstance(row, dict) or row.get("ok") is True:
            continue
        failed.append(
            {
                "name": str(row.get("name") or "unnamed_check"),
                "detail": str(row.get("detail") or row.get("reason") or row.get("error") or ""),
                **({"state": row.get("state")} if isinstance(row.get("state"), dict) else {}),
                **({"coverage": row.get("coverage")} if isinstance(row.get("coverage"), dict) else {}),
                **({"frame_delta_stats": row.get("frame_delta_stats")} if isinstance(row.get("frame_delta_stats"), dict) else {}),
            }
        )
    return failed[:limit]


def _hard_gate_receipt_ok(receipt: dict[str, Any]) -> bool:
    return (
        receipt.get("status") == "pass"
        and int(receipt.get("failed_count") or 0) == 0
        and all(isinstance(row, dict) and row.get("ok") is True for row in list(receipt.get("checks") or []))
    )


def _route_covers_required_detail(route: str, required_prefix: str) -> bool:
    normalized_route = str(route or "").split("?", 1)[0].strip().rstrip("/")
    normalized_prefix = str(required_prefix or "").strip().rstrip("/")
    if not normalized_route or not normalized_prefix:
        return False
    return normalized_route.startswith(f"{normalized_prefix}/")


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


def _repo_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "docker-compose.property.yml").is_file():
        return cwd.resolve()
    return Path(__file__).resolve().parents[1]


def _fallback_artifact_readme_path(*, slug: str, provider: str) -> Path:
    configured_artifact_dir = str(os.getenv("EA_ARTIFACT_DIR") or os.getenv("EA_ARTIFACTS_DIR") or "").strip()
    if configured_artifact_dir:
        return (
            Path(configured_artifact_dir).expanduser().resolve()
            / "property-tour-export-drop-readmes"
            / slug
            / provider
            / "README.propertyquarry-export.txt"
        )
    return (
        _repo_root()
        / "_completion"
        / "property_tour_exports"
        / "drop-readmes"
        / slug
        / provider
        / "README.propertyquarry-export.txt"
    ).resolve()


def _operator_drop_provider_rows(import_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    provider_rows: dict[str, dict[str, Any]] = {}
    for raw_row in list(import_manifest.get("prepared_drop_dirs") or []):
        if not isinstance(raw_row, dict):
            continue
        provider = str(raw_row.get("provider") or "").strip().lower()
        if not provider:
            continue
        provider_rows[provider] = dict(raw_row)
    for raw_row in list(import_manifest.get("imports") or []):
        if not isinstance(raw_row, dict):
            continue
        provider = str(raw_row.get("provider") or "").strip().lower()
        slug = str(raw_row.get("slug") or "").strip()
        export_dir_text = str(raw_row.get("export_dir") or raw_row.get("asset_dir") or "").strip()
        if not provider:
            continue
        export_dir = Path(export_dir_text).expanduser().resolve() if export_dir_text else None
        export_readme_path = export_dir / "README.propertyquarry-export.txt" if export_dir is not None else None
        synthesized_row: dict[str, Any] = {
            "provider": provider,
            "slug": slug,
            "export_dir": str(export_dir) if export_dir is not None else export_dir_text,
            "readme": str(export_readme_path) if export_readme_path is not None else "",
            "drop_readme": str(export_readme_path) if export_readme_path is not None else "",
            "artifact_readme": str(_fallback_artifact_readme_path(slug=slug, provider=provider)) if slug else "",
        }
        merged_row = dict(provider_rows.get(provider) or {})
        for key, value in synthesized_row.items():
            if merged_row.get(key):
                continue
            merged_row[key] = value
        provider_rows[provider] = merged_row
    return provider_rows


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


def _billing_handoff_ready(
    billing_receipt: dict[str, Any],
    *,
    authenticated_smoke: dict[str, Any] | None = None,
) -> bool:
    return bool(_billing_handoff_readiness_details(billing_receipt, authenticated_smoke=authenticated_smoke).get("ready"))


def _billing_handoff_readiness_details(
    billing_receipt: dict[str, Any],
    *,
    authenticated_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    handoff = billing_receipt.get("billing_handoff")
    if not isinstance(handoff, dict):
        return {
            "ready": False,
            "ready_via": "",
            "direct_account_handoff_usable": None,
            "signed_handoff_usable": False,
            "live_smoke_external_handoff_usable": False,
            "live_smoke_no_second_login": False,
            "pricing_placeholder": False,
        }
    pricing_probe = handoff.get("pricing_surface_probe")
    pricing_placeholder = isinstance(pricing_probe, dict) and pricing_probe.get("placeholder") is True
    direct_ready = (
        bool(handoff.get("configured"))
        and bool(handoff.get("host_resolves"))
        and handoff.get("account_handoff_usable") is True
        and str(handoff.get("url") or "").strip().startswith("https://")
        and str(billing_receipt.get("status") or "").strip() != "blocked"
        and not pricing_placeholder
    )
    bridge = billing_receipt.get("billing_sso_bridge")
    member_token_handoff = billing_receipt.get("member_login_token_handoff")
    authenticated_route_row, authenticated_passed_checks, _ = _route_named_checks(
        authenticated_smoke or {},
        "/app/billing",
    )
    live_external_usable = "billing_external_handoff_usable" in authenticated_passed_checks
    live_no_second_login = "billing_no_second_login" in authenticated_passed_checks
    authenticated_external_handoff_usable = bool(authenticated_route_row) and live_external_usable and live_no_second_login
    member_token_ready = (
        isinstance(member_token_handoff, dict)
        and member_token_handoff.get("ready") is True
        and bool(handoff.get("configured"))
        and bool(handoff.get("host_resolves"))
        and str(handoff.get("url") or "").strip().startswith("https://")
        and str(billing_receipt.get("status") or "").strip() != "blocked"
        and (authenticated_external_handoff_usable or not authenticated_route_row)
        and not pricing_placeholder
    )
    bridge_session_ready = (
        isinstance(bridge, dict)
        and bridge.get("ready") is True
        and bridge.get("exchange_checked") is True
        and bridge.get("exchange_usable") is True
    )
    bridge_guided_login_assist = "billing_bridge_guided_login_assist" in authenticated_passed_checks
    authenticated_bridge_launch = bool(authenticated_route_row) and (
        "billing_bridge_launch" in authenticated_passed_checks
        and live_no_second_login
    )
    sso_bridge_ready = (
        bridge_session_ready
        and not bridge_guided_login_assist
        and (authenticated_bridge_launch or authenticated_external_handoff_usable)
    )
    ready_via = ""
    if direct_ready:
        ready_via = "direct_account"
    elif member_token_ready:
        ready_via = "member_login_token"
    elif sso_bridge_ready:
        ready_via = "sso_bridge"
    return {
        "ready": bool(ready_via),
        "ready_via": ready_via,
        "direct_account_handoff_usable": handoff.get("account_handoff_usable"),
        "signed_handoff_usable": bool(member_token_ready or sso_bridge_ready),
        "member_login_token_usable": bool(member_token_ready),
        "sso_bridge_usable": bool(sso_bridge_ready),
        "live_smoke_external_handoff_usable": bool(authenticated_external_handoff_usable),
        "live_smoke_no_second_login": bool(authenticated_route_row) and live_no_second_login,
        "live_smoke_bridge_launch": bool(authenticated_bridge_launch),
        "bridge_guided_login_assist": bool(bridge_guided_login_assist),
        "pricing_placeholder": bool(pricing_placeholder),
    }


def _id_austria_gate_details(id_austria_receipt: dict[str, Any]) -> dict[str, Any]:
    status = str(id_austria_receipt.get("status") or "").strip().lower()
    required = bool(id_austria_receipt.get("required"))
    configured = bool(id_austria_receipt.get("configured"))
    ready = (
        status in {"dry_verified_configured", "live_verified_configured", "production_verified_configured"}
        or (status == "disabled" and not required and not configured)
    )
    return {
        "ready": ready,
        "status": status or "missing",
        "required": required,
        "configured": configured,
        "error": str(id_austria_receipt.get("error") or "").strip(),
        "missing_env": list(id_austria_receipt.get("missing_env") or []),
        "redirect_uri": str(id_austria_receipt.get("redirect_uri") or "").strip(),
        "issuer": str(id_austria_receipt.get("issuer") or "").strip(),
    }


def _operator_drop_readme_status(
    import_manifest: dict[str, Any],
    *,
    expected_providers: set[str] | None = None,
) -> tuple[bool, int, list[str], list[dict[str, Any]]]:
    if expected_providers is None:
        expected_providers = set(PROVIDER_OPERATOR_DROP_README_TOKENS)
    else:
        expected_providers = set(expected_providers)
    if not expected_providers:
        return True, 0, [], []
    provider_rows = _operator_drop_provider_rows(import_manifest)
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
    whole_project_scope_receipt_path: Path | None = None,
    security_posture_receipt_path: Path | None = None,
    release_hygiene_receipt_path: Path | None = None,
    furniture_style_contract_receipt_path: Path | None = None,
    bts_methodology_contract_receipt_path: Path | None = None,
    tour_delivery_contract_receipt_path: Path | None = None,
    map_preview_flagship_receipt_path: Path | None = None,
    browser_3d_gate_receipt_path: Path | None = None,
    runtime_reconstruction_receipt_path: Path | None = None,
    walkthrough_quality_receipt_path: Path | None = None,
    scene_video_readiness_receipt_path: Path | None = None,
    scene_video_readiness_verifier_receipt_path: Path | None = None,
    scene_video_provider_refresh_packet_path: Path | None = None,
    scene_video_provider_refresh_packet_verifier_receipt_path: Path | None = None,
    id_austria_receipt_path: Path | None = None,
    max_receipt_age_hours: float | None = None,
    provider_catalog_receipt_path: Path | None = None,
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
    magicfit_renderer = _magicfit_renderer_summary(
        vendor_tooling,
        receipt_present=vendor_tooling_receipt_path is not None,
    )
    omagic_adapter = _omagic_adapter_summary(
        vendor_tooling,
        receipt_present=vendor_tooling_receipt_path is not None,
    )
    whole_project_scope = _load_json(whole_project_scope_receipt_path) if whole_project_scope_receipt_path is not None else {}
    security_posture = _load_json(security_posture_receipt_path) if security_posture_receipt_path is not None else {}
    release_hygiene = _load_json(release_hygiene_receipt_path) if release_hygiene_receipt_path is not None else {}
    furniture_style_contract = _load_json(furniture_style_contract_receipt_path) if furniture_style_contract_receipt_path is not None else {}
    bts_methodology_contract = _load_json(bts_methodology_contract_receipt_path) if bts_methodology_contract_receipt_path is not None else {}
    tour_delivery_contract = _load_json(tour_delivery_contract_receipt_path) if tour_delivery_contract_receipt_path is not None else {}
    map_preview_flagship = _load_json(map_preview_flagship_receipt_path) if map_preview_flagship_receipt_path is not None else {}
    browser_3d_gate = _load_json(browser_3d_gate_receipt_path) if browser_3d_gate_receipt_path is not None else {}
    runtime_reconstruction = _load_json(runtime_reconstruction_receipt_path) if runtime_reconstruction_receipt_path is not None else {}
    walkthrough_quality = _load_json(walkthrough_quality_receipt_path) if walkthrough_quality_receipt_path is not None else {}
    scene_video_readiness = _load_json(scene_video_readiness_receipt_path) if scene_video_readiness_receipt_path is not None else {}
    scene_video_readiness_verifier = _load_json(scene_video_readiness_verifier_receipt_path) if scene_video_readiness_verifier_receipt_path is not None else {}
    scene_video_provider_refresh_packet = _load_json(scene_video_provider_refresh_packet_path) if scene_video_provider_refresh_packet_path is not None else {}
    scene_video_provider_refresh_packet_verifier = (
        _load_json(scene_video_provider_refresh_packet_verifier_receipt_path)
        if scene_video_provider_refresh_packet_verifier_receipt_path is not None
        else {}
    )
    id_austria_receipt = _load_json(id_austria_receipt_path) if id_austria_receipt_path is not None else {}
    repair_canary = _load_json(repair_canary_receipt_path)
    provider_catalog = _load_json(provider_catalog_receipt_path) if provider_catalog_receipt_path is not None else {}
    provider_matrix = _load_json(provider_matrix_receipt_path)
    receipt_freshness_ok, stale_receipts = _receipt_freshness_status(
        {
            "performance": performance,
            "tour_controls": tour_controls,
            "export_discovery": export_discovery,
            **({"billing_handoff": billing_receipt} if billing_receipt_path is not None else {}),
            **({"id_austria": id_austria_receipt} if id_austria_receipt_path is not None else {}),
            "repair_canary": repair_canary,
            **({"provider_catalog_smoke": provider_catalog} if provider_catalog_receipt_path is not None else {}),
            "provider_matrix": provider_matrix,
            **({"live_mobile_surfaces": live_mobile} if live_mobile_receipt_path is not None else {}),
            **({"public_auth_surfaces": public_smoke} if public_smoke_receipt_path is not None else {}),
            **({"authenticated_customer_surfaces": authenticated_smoke} if authenticated_smoke_receipt_path is not None else {}),
            **({"tour_provider_ownership": tour_provider_ownership} if tour_provider_ownership_receipt_path is not None else {}),
            **({"vendor_tooling": vendor_tooling} if vendor_tooling_receipt_path is not None else {}),
            **({"whole_project_scope": whole_project_scope} if whole_project_scope_receipt_path is not None else {}),
            **({"security_posture": security_posture} if security_posture_receipt_path is not None else {}),
            **({"release_hygiene": release_hygiene} if release_hygiene_receipt_path is not None else {}),
            **({"furniture_style_contract": furniture_style_contract} if furniture_style_contract_receipt_path is not None else {}),
            **({"bts_methodology_contract": bts_methodology_contract} if bts_methodology_contract_receipt_path is not None else {}),
            **({"tour_delivery_contract": tour_delivery_contract} if tour_delivery_contract_receipt_path is not None else {}),
            **({"map_preview_flagship": map_preview_flagship} if map_preview_flagship_receipt_path is not None else {}),
            **({"browser_rendered_3d": browser_3d_gate} if browser_3d_gate_receipt_path is not None else {}),
            **({"generated_reconstruction_glb": runtime_reconstruction} if runtime_reconstruction_receipt_path is not None else {}),
            **({"walkthrough_quality": walkthrough_quality} if walkthrough_quality_receipt_path is not None else {}),
            **({"scene_video_readiness": scene_video_readiness} if scene_video_readiness_receipt_path is not None else {}),
            **({"scene_video_readiness_verifier": scene_video_readiness_verifier} if scene_video_readiness_verifier_receipt_path is not None else {}),
            **({"scene_video_provider_refresh_packet": scene_video_provider_refresh_packet} if scene_video_provider_refresh_packet_path is not None else {}),
            **({"scene_video_provider_refresh_packet_verifier": scene_video_provider_refresh_packet_verifier} if scene_video_provider_refresh_packet_verifier_receipt_path is not None else {}),
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
    provider_catalog_smoke = _provider_catalog_smoke_summary(provider_catalog, provider_catalog_receipt_path)
    provider_catalog_smoke_ok = provider_catalog_receipt_path is None or provider_catalog_smoke.get("status") == "pass"
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
    browser_3d_gate_ok = browser_3d_gate_receipt_path is None or _hard_gate_receipt_ok(browser_3d_gate)
    runtime_reconstruction_details = dict(runtime_reconstruction.get("details") or {})
    runtime_reconstruction_paths = dict(runtime_reconstruction_details.get("paths") or {})
    runtime_reconstruction_glb = dict(runtime_reconstruction_paths.get("glb") or {})
    runtime_reconstruction_ok = (
        runtime_reconstruction_receipt_path is None
        or (
            runtime_reconstruction.get("status") == "pass"
            and runtime_reconstruction.get("public_route_contract_ok") is True
            and runtime_reconstruction.get("glb_capability_ok") is True
            and runtime_reconstruction.get("glb_manifest_ok") is True
            and runtime_reconstruction.get("glb_non_empty") is True
            and runtime_reconstruction.get("glb_required") is True
            and runtime_reconstruction.get("required_paths_ok") is True
        )
    )
    walkthrough_quality_ok = walkthrough_quality_receipt_path is None or _hard_gate_receipt_ok(walkthrough_quality)
    scene_video_readiness_verifier_ok = (
        scene_video_readiness_verifier_receipt_path is None
        or (
            scene_video_readiness_verifier.get("status") == "pass"
            and not list(scene_video_readiness_verifier.get("blockers") or [])
        )
    )
    scene_video_provider_refresh_packet_verifier_ok = (
        scene_video_provider_refresh_packet_verifier_receipt_path is None
        or (
            scene_video_provider_refresh_packet_verifier.get("status") == "pass"
            and not list(scene_video_provider_refresh_packet_verifier.get("blockers") or [])
        )
    )
    scene_video_provider_summary = (
        dict(scene_video_readiness.get("summary") or {})
        if isinstance(scene_video_readiness.get("summary"), dict)
        else {}
    )
    scene_video_blocked_provider_count = int(scene_video_provider_summary.get("blocked_count") or 0)
    scene_video_blocked_providers = [
        str(provider or "").strip()
        for provider in list(scene_video_provider_summary.get("blocked_providers") or [])
        if str(provider or "").strip()
    ]
    scene_video_next_actions = [
        dict(action)
        for action in list(scene_video_readiness.get("next_actions") or [])
        if isinstance(action, dict)
    ]
    scene_video_action_providers = [
        str(action.get("provider") or "").strip()
        for action in scene_video_next_actions
        if str(action.get("provider") or "").strip()
    ]
    if not scene_video_blocked_providers:
        scene_video_blocked_providers = sorted(set(scene_video_action_providers))
    scene_video_provider_runtime_ready = (
        scene_video_readiness_receipt_path is not None
        and scene_video_blocked_provider_count == 0
        and not scene_video_next_actions
    )
    scene_video_provider_action_required = (
        scene_video_readiness_receipt_path is not None
        and (scene_video_blocked_provider_count > 0 or bool(scene_video_next_actions))
    )
    billing_readiness = _billing_handoff_readiness_details(
        billing_receipt,
        authenticated_smoke=authenticated_smoke if authenticated_smoke_receipt_path is not None else None,
    )
    billing_ok = billing_receipt_path is None or bool(billing_readiness.get("ready"))
    id_austria_details = _id_austria_gate_details(id_austria_receipt)
    id_austria_ok = id_austria_receipt_path is None or bool(id_austria_details.get("ready"))
    manifest_providers = {
        str(provider or "").strip().lower()
        for provider in list(import_manifest.get("providers") or [])
        if str(provider or "").strip()
    }
    import_manifest_status = str(import_manifest.get("status") or "").strip()
    import_manifest_not_needed = (
        import_manifest_receipt_path is not None
        and import_manifest_status not in {"missing", "invalid"}
        and not missing_provider_modes
        and int(import_manifest.get("import_count") or 0) == 0
    )
    export_discovery_ok = (
        export_discovery.get("status") in {"ready", "pass"}
        or import_manifest_not_needed
    )
    expected_import_providers = (
        set()
        if import_manifest_not_needed
        else (manifest_providers or {"3dvista", "magicfit"})
    )
    prepared_drop_providers = set(_operator_drop_provider_rows(import_manifest))
    hardened_readmes_ok, hardened_readme_provider_count, missing_hardened_readme_providers, hardened_readme_failures = _operator_drop_readme_status(
        import_manifest,
        expected_providers=expected_import_providers,
    )
    operator_import_manifest_ready = (
        import_manifest_not_needed
        or (
            import_manifest_status in {"ready_for_exports", "waiting_for_verified_assets", "partial_ready_for_import", "ready_for_import"}
            and int(import_manifest.get("import_count") or 0) >= len(expected_import_providers)
            and expected_import_providers.issubset(manifest_providers)
            and expected_import_providers.issubset(prepared_drop_providers)
            and hardened_readmes_ok
        )
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
    whole_project_scope_ok = (
        whole_project_scope_receipt_path is None
        or (
            whole_project_scope.get("status") == "pass"
            and not list(whole_project_scope.get("failures") or [])
        )
    )
    security_posture_ok = (
        security_posture_receipt_path is None
        or (
            security_posture.get("status") == "pass"
            and not list(security_posture.get("failures") or [])
        )
    )
    release_hygiene_ok = (
        release_hygiene_receipt_path is None
        or (
            release_hygiene.get("status") == "pass"
            and not list(release_hygiene.get("failures") or [])
        )
    )
    furniture_style_contract_ok = (
        furniture_style_contract_receipt_path is None
        or (
            furniture_style_contract.get("status") == "pass"
            and not list(furniture_style_contract.get("failures") or [])
            and int(furniture_style_contract.get("style_count") or 0) >= 5
            and dict(furniture_style_contract.get("plan_caps") or {}) == {"free": 5, "plus": 5, "agent": 5}
        )
    )
    bts_methodology_contract_ok = (
        bts_methodology_contract_receipt_path is None
        or (
            bts_methodology_contract.get("status") == "pass"
            and not list(bts_methodology_contract.get("failures") or [])
            and int(bts_methodology_contract.get("source_section_count") or 0) >= 5
            and {"en", "de"}.issubset(set(bts_methodology_contract.get("languages") or []))
        )
    )
    tour_delivery_contract_ok = (
        tour_delivery_contract_receipt_path is None
        or (
            tour_delivery_contract.get("status") == "pass"
            and not list(tour_delivery_contract.get("failures") or [])
            and "matterport" in set(tour_delivery_contract.get("ready_provider_modes") or [])
            and int(tour_delivery_contract.get("matterport_ready_count") or 0) > 0
            and (
                set(tour_delivery_contract.get("required_provider_modes") or tour_delivery_contract.get("required_providers") or [])
                == set(REQUIRED_TOUR_PROVIDER_MODES)
            )
        )
    )
    map_preview_flagship_ok = map_preview_flagship_receipt_path is None or _hard_gate_receipt_ok(map_preview_flagship)

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
    if not id_austria_ok:
        blockers.append(
            {
                "area": "id_austria_sign_in",
                "status": id_austria_details.get("status") or "missing",
                "required": bool(id_austria_details.get("required")),
                "configured": bool(id_austria_details.get("configured")),
                "error": str(id_austria_details.get("error") or ""),
                "missing_env": list(id_austria_details.get("missing_env") or []),
                "redirect_uri": str(id_austria_details.get("redirect_uri") or ""),
                "action": "either configure the production ID Austria OIDC contract or keep PROPERTYQUARRY_ID_AUSTRIA_REQUIRED unset so the sign-in lane stays explicitly fail-closed",
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
                "action": "run propertyquarry_live_authenticated_smoke.py against the deployed stack and keep /app/billing either redirected to a resolving billing portal or fail-closed without local billing-board copy, while /app/account keeps the notification routing form usable",
            }
        )
    if missing_provider_modes:
        provider_details: dict[str, dict[str, Any]] = {}
        if "magicfit" in missing_provider_modes:
            provider_details["magicfit"] = {
                "renderer_ready": magicfit_renderer.get("ready"),
                "renderer_status": magicfit_renderer.get("status"),
                "script_ready": magicfit_renderer.get("script_ready"),
                "credentials_configured": magicfit_renderer.get("credentials_configured"),
                "missing_python_modules": magicfit_renderer.get("missing_python_modules"),
                "next_action": magicfit_renderer.get("next_action"),
            }
        blockers.append(
            {
                "area": "verified_tour_provider_modes",
                "missing_provider_modes": missing_provider_modes,
                "action": _tour_provider_evidence_action(missing_provider_modes),
                **({"provider_details": provider_details} if provider_details else {}),
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
    if not browser_3d_gate_ok:
        blockers.append(
            {
                "area": "browser_rendered_3d",
                "status": browser_3d_gate.get("status") or ("not_configured" if browser_3d_gate_receipt_path is None else "missing"),
                "failed_count": browser_3d_gate.get("failed_count"),
                "providers": browser_3d_gate.get("providers") or [],
                "provider_results": browser_3d_gate.get("provider_results") or [],
                "failed_checks": _failed_receipt_checks(browser_3d_gate),
                "action": "rerun propertyquarry_3d_browser_gate.py and only claim 3D readiness when every visible 3D tour renders in a real browser without CSP, frame, network, loading, or blank-viewer failures",
            }
        )
    if not runtime_reconstruction_ok:
        blockers.append(
            {
                "area": "generated_reconstruction_glb",
                "status": runtime_reconstruction.get("status") or ("not_configured" if runtime_reconstruction_receipt_path is None else "missing"),
                "glb_export_status": runtime_reconstruction_details.get("glb_export_status"),
                "glb_non_empty": runtime_reconstruction.get("glb_non_empty"),
                "glb_manifest_ok": runtime_reconstruction.get("glb_manifest_ok"),
                "glb_capability_ok": runtime_reconstruction.get("glb_capability_ok"),
                "required_paths_ok": runtime_reconstruction.get("required_paths_ok"),
                "public_route_contract_ok": runtime_reconstruction.get("public_route_contract_ok"),
                "viewer_url": str(runtime_reconstruction.get("viewer_url") or ""),
                "action": "rerun property_runtime_reconstruction_smoke.py with --require-glb and --require-public-contract; fix Blender/NumPy/runtime export or generated-preview route leakage before claiming generated reconstruction readiness",
            }
        )
    if not map_preview_flagship_ok:
        blockers.append(
            {
                "area": "map_preview_flagship",
                "status": map_preview_flagship.get("status") or ("not_configured" if map_preview_flagship_receipt_path is None else "missing"),
                "failed_count": map_preview_flagship.get("failed_count"),
                "preview_count": map_preview_flagship.get("preview_count"),
                "failed_checks": _failed_receipt_checks(map_preview_flagship),
                "preview_results": list(map_preview_flagship.get("preview_results") or [])[:6],
                "action": "rerun propertyquarry_map_preview_flagship_gate.py and keep generated map thumbnails ready, non-placeholder, calm, readable, and free of excessive red overlays or artifact text",
            }
        )
    if not walkthrough_quality_ok:
        blockers.append(
            {
                "area": "walkthrough_quality",
                "status": walkthrough_quality.get("status") or ("not_configured" if walkthrough_quality_receipt_path is None else "missing"),
                "failed_count": walkthrough_quality.get("failed_count"),
                "video_relpath": str(walkthrough_quality.get("video_relpath") or ""),
                "failed_checks": _failed_receipt_checks(walkthrough_quality),
                "action": "rerun propertyquarry_walkthrough_quality_gate.py after generating a walkthrough with explicit room coverage, sufficient duration, and frame-continuity proof",
            }
        )
    if not scene_video_readiness_verifier_ok:
        blockers.append(
            {
                "area": "scene_video_readiness",
                "status": scene_video_readiness_verifier.get("status") or ("not_configured" if scene_video_readiness_verifier_receipt_path is None else "missing"),
                "verifier_blockers": list(scene_video_readiness_verifier.get("blockers") or [])[:12],
                "provider_summary": scene_video_readiness.get("summary") or {},
                "action": "rerun property_scene_video_readiness_report.py and verify_property_scene_video_readiness.py, then repair any Mootion BrowserAct, Telegram, 1min isolation, MagicFit, or OMagic/Magic routing regressions",
            }
        )
    if not scene_video_provider_refresh_packet_verifier_ok:
        blockers.append(
            {
                "area": "scene_video_provider_refresh_packet",
                "status": scene_video_provider_refresh_packet_verifier.get("status") or ("not_configured" if scene_video_provider_refresh_packet_verifier_receipt_path is None else "missing"),
                "verifier_blockers": list(scene_video_provider_refresh_packet_verifier.get("blockers") or [])[:12],
                "checked_providers": scene_video_provider_refresh_packet_verifier.get("checked_providers") or [],
                "packet_path": str(scene_video_provider_refresh_packet_path) if scene_video_provider_refresh_packet_path is not None else "",
                "action": "rerun materialize_scene_video_provider_refresh_packet.py and verify_scene_video_provider_refresh_packet.py; do not modify ONEMIN_* credentials while refreshing MagicFit or OMagic/Magic accounts",
            }
        )
    if bool(omagic_adapter.get("runtime_checked")) and not bool(omagic_adapter.get("ready")):
        blockers.append(
            {
                "area": "omagic_model_upload_adapter_deploy",
                "status": omagic_adapter.get("status") or "missing",
                "script_ready": omagic_adapter.get("script_ready"),
                "runtime_script_ready": omagic_adapter.get("runtime_script_ready"),
                "runtime_script": omagic_adapter.get("runtime_script") or {},
                "action": str(omagic_adapter.get("next_action") or "")
                or "rebuild/redeploy the PropertyQuarry runtime so the OMagic model-upload adapter exists before claiming provider parity",
            }
        )
    if scene_video_provider_action_required:
        blockers.append(
            {
                "area": "scene_video_provider_runtime",
                "status": "action_required",
                "provider_runtime_ready": False,
                "provider_blocked_count": scene_video_blocked_provider_count,
                "blocked_providers": scene_video_blocked_providers,
                "provider_summary": scene_video_provider_summary,
                "next_actions": scene_video_next_actions[:12],
                "action": "clear MagicFit credit/account visibility plus Magic/OMagic credential and upload-adapter gaps, rerun property_scene_video_readiness_report.py, then refresh the gold receipt before claiming Crezlo-level video/provider parity",
            }
        )
    if not export_discovery_ok:
        blockers.append(
            {
                "area": "tour_export_drop",
                "status": export_discovery.get("status") or "unknown",
                "action": "place verified 3D-tour exports in the configured drop directory and rerun discovery/import",
            }
        )
    if not billing_ok:
        billing_handoff = billing_receipt.get("billing_handoff") if isinstance(billing_receipt.get("billing_handoff"), dict) else {}
        billing_sso_bridge = billing_receipt.get("billing_sso_bridge") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else {}
        member_token_handoff = billing_receipt.get("member_login_token_handoff") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else {}
        blockers.append(
            {
                "area": "billing_handoff",
                "status": billing_receipt.get("status") or "missing",
                "error": billing_receipt.get("error") or "",
                "host": str(billing_handoff.get("host") or ""),
                "host_resolves": bool(billing_handoff.get("host_resolves")),
                "required_dns_record": billing_handoff.get("required_dns_record") if isinstance(billing_handoff.get("required_dns_record"), dict) else {},
                "next_action": str(billing_handoff.get("next_action") or ""),
                "sso_bridge_ready": billing_sso_bridge.get("ready"),
                "sso_bridge_config_ready": billing_sso_bridge.get("config_ready"),
                "sso_bridge_exchange_checked": billing_sso_bridge.get("exchange_checked"),
                "sso_bridge_exchange_usable": billing_sso_bridge.get("exchange_usable"),
                "sso_bridge_error": str(billing_sso_bridge.get("error") or ""),
                "sso_bridge_next_action": str(billing_sso_bridge.get("next_action") or ""),
                "member_login_token_enabled": member_token_handoff.get("enabled"),
                "member_login_token_configured": member_token_handoff.get("configured"),
                "member_login_token_ready": member_token_handoff.get("ready"),
                "member_login_token_error": str(member_token_handoff.get("error") or ""),
                "member_login_token_next_action": str(member_token_handoff.get("next_action") or ""),
                "member_login_token_required_env": list(BILLING_MEMBER_TOKEN_REQUIRED_ENV),
                "ready_via": str(billing_readiness.get("ready_via") or ""),
                "signed_handoff_usable": bool(billing_readiness.get("signed_handoff_usable")),
                "live_smoke_external_handoff_usable": bool(billing_readiness.get("live_smoke_external_handoff_usable")),
                "live_smoke_no_second_login": bool(billing_readiness.get("live_smoke_no_second_login")),
                "admin_action": BILLING_MEMBER_TOKEN_ADMIN_ACTION,
                "action": "configure the Brilliant Directories white-label billing host or signed member-login handoff so /app/billing opens a usable external account lane without a second login",
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
                "action": "prepare the 3D tour, panorama, and walkthrough operator import lanes before claiming gold",
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
    if not provider_catalog_smoke_ok:
        blockers.append(
            {
                "area": "provider_catalog_smoke",
                "status": provider_catalog_smoke.get("raw_status") or provider_catalog_smoke.get("status") or "unknown",
                "failed_checks": provider_catalog_smoke.get("failed_checks") or [],
                "action": "rerun the post-deploy provider catalog smoke and fix provider/default-provider parity or country-scope failures before using the latest runtime catalog",
            }
        )
    if not whole_project_scope_ok:
        blockers.append(
            {
                "area": "whole_project_scope",
                "status": whole_project_scope.get("status") or "missing",
                "failures": list(whole_project_scope.get("failures") or [])[:12],
                "action": "rerun check_property_whole_project_scope.py --write and keep the evidence-overlay registry, Teable/cached-read-model policy, and whole-product scope contracts passing",
            }
        )
    if not security_posture_ok:
        blockers.append(
            {
                "area": "production_security_posture",
                "status": security_posture.get("status") or "missing",
                "failures": list(security_posture.get("failures") or [])[:12],
                "action": "rerun check_property_security_posture.py --write and keep the isolated runtime, pinned supply chain, public-tour privacy, and locked-dependency posture passing",
            }
        )
    if not release_hygiene_ok:
        blockers.append(
            {
                "area": "release_hygiene",
                "status": release_hygiene.get("status") or "missing",
                "manifest_runtime_commit": str(release_hygiene.get("manifest_runtime_commit") or ""),
                "head_commit": str(release_hygiene.get("head_commit") or ""),
                "failures": list(release_hygiene.get("failures") or [])[:12],
                "action": "rerun check_property_release_hygiene.py --write after reconciling the release manifest runtime commit with current HEAD or the deployed parent",
            }
        )
    if not furniture_style_contract_ok:
        blockers.append(
            {
                "area": "furniture_style_variants",
                "status": furniture_style_contract.get("status") or "missing",
                "style_count": furniture_style_contract.get("style_count"),
                "plan_caps": furniture_style_contract.get("plan_caps") or {},
                "failures": list(furniture_style_contract.get("failures") or [])[:12],
                "action": "rerun check_property_furniture_style_contract.py --write and keep the five visible style choices, all-tier request-time choice, examples, UI handoff, and style-aware cached rendering contract passing",
            }
        )
    if not bts_methodology_contract_ok:
        blockers.append(
            {
                "area": "bts_methodology",
                "status": bts_methodology_contract.get("status") or "missing",
                "source_section_count": bts_methodology_contract.get("source_section_count"),
                "languages": bts_methodology_contract.get("languages") or [],
                "failures": list(bts_methodology_contract.get("failures") or [])[:12],
                "action": "rerun check_property_bts_methodology_contract.py --write and keep score-PDF provenance, official data-source copy, and selected-district no-reward policy passing",
            }
        )
    if not tour_delivery_contract_ok:
        blockers.append(
            {
                "area": "tour_delivery_contract_shape",
                "status": tour_delivery_contract.get("status") or "missing",
                "matterport_ready_count": tour_delivery_contract.get("matterport_ready_count"),
                "ready_provider_modes": tour_delivery_contract.get("ready_provider_modes") or [],
                "missing_provider_modes": tour_delivery_contract.get("missing_provider_modes") or [],
                "failures": list(tour_delivery_contract.get("failures") or [])[:12],
                "action": "rerun check_property_tour_delivery_contract.py --write and keep public-safe ready_payload, blocked_reason, required_to_send, white-label separation, and first-class Matterport readiness passing",
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
    if export_discovery.get("status") == "blocked_no_verified_exports" and not import_manifest_not_needed:
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
    if scene_video_provider_action_required:
        if scene_video_next_actions:
            next_required_actions.extend(
                {
                    "area": "scene_video_provider_runtime",
                    **action,
                    "action": str(action.get("action") or "").strip()
                    or "clear the scene-video provider runtime gap and rerun the scene-video readiness report",
                }
                for action in scene_video_next_actions
            )
        else:
            next_required_actions.append(
                {
                    "area": "scene_video_provider_runtime",
                    "provider": "_".join(scene_video_blocked_providers) if scene_video_blocked_providers else "scene_video",
                    "reason": "provider_runtime_not_ready",
                    "action": "clear the blocked scene-video providers and rerun property_scene_video_readiness_report.py",
                }
            )
    if "magicfit" in missing_provider_modes and vendor_tooling_receipt_path is not None and not bool(magicfit_renderer.get("ready")):
        next_required_actions.append(
            {
                "provider": "magicfit",
                "area": "magicfit_renderer",
                "renderer_status": magicfit_renderer.get("status"),
                "script_ready": magicfit_renderer.get("script_ready"),
                "credentials_configured": magicfit_renderer.get("credentials_configured"),
                "missing_python_modules": magicfit_renderer.get("missing_python_modules"),
                "action": (
                    str(magicfit_renderer.get("next_action") or "")
                    or "configure the MagicFit render lane before expecting a receipt-backed walkthrough"
                ),
            }
        )
    if bool(omagic_adapter.get("runtime_checked")) and not bool(omagic_adapter.get("ready")):
        next_required_actions.append(
            {
                "provider": "omagic",
                "area": "omagic_model_upload_adapter_deploy",
                "adapter_status": omagic_adapter.get("status"),
                "script_ready": omagic_adapter.get("script_ready"),
                "runtime_script_ready": omagic_adapter.get("runtime_script_ready"),
                "action": (
                    str(omagic_adapter.get("next_action") or "")
                    or "deploy the OMagic model-upload adapter before expecting model-backed walkthrough renders"
                ),
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
        {
            "area": "provider_catalog_smoke",
            "status": "pass",
            "raw_status": provider_catalog_smoke.get("raw_status"),
            "check_count": provider_catalog_smoke.get("check_count"),
            "receipt_path": provider_catalog_smoke.get("receipt_path"),
        }
        if provider_catalog_smoke_ok and provider_catalog_receipt_path is not None
        else None,
        {"area": "self_healing", "status": "pass", "receipt_path": str(repair_canary_receipt_path)}
        if repair_canary_ok
        else None,
        {"area": "whole_project_scope", "status": "pass", "receipt_path": str(whole_project_scope_receipt_path)}
        if whole_project_scope_receipt_path is not None and whole_project_scope_ok
        else None,
        {"area": "production_security_posture", "status": "pass", "receipt_path": str(security_posture_receipt_path)}
        if security_posture_receipt_path is not None and security_posture_ok
        else None,
        {
            "area": "release_hygiene",
            "status": "pass",
            "manifest_runtime_commit": str(release_hygiene.get("manifest_runtime_commit") or ""),
            "head_commit": str(release_hygiene.get("head_commit") or ""),
            "receipt_path": str(release_hygiene_receipt_path),
        }
        if release_hygiene_receipt_path is not None and release_hygiene_ok
        else None,
        {
            "area": "furniture_style_variants",
            "status": "pass",
            "style_count": furniture_style_contract.get("style_count"),
            "plan_caps": furniture_style_contract.get("plan_caps") or {},
            "receipt_path": str(furniture_style_contract_receipt_path),
        }
        if furniture_style_contract_receipt_path is not None and furniture_style_contract_ok
        else None,
        {
            "area": "bts_methodology",
            "status": "pass",
            "language_count": bts_methodology_contract.get("language_count"),
            "source_section_count": bts_methodology_contract.get("source_section_count"),
            "receipt_path": str(bts_methodology_contract_receipt_path),
        }
        if bts_methodology_contract_receipt_path is not None and bts_methodology_contract_ok
        else None,
        {
            "area": "tour_delivery_contract_shape",
            "status": "pass",
            "matterport_ready_count": tour_delivery_contract.get("matterport_ready_count"),
            "ready_provider_modes": tour_delivery_contract.get("ready_provider_modes") or [],
            "receipt_path": str(tour_delivery_contract_receipt_path),
        }
        if tour_delivery_contract_receipt_path is not None and tour_delivery_contract_ok
        else None,
        {
            "area": "map_preview_flagship",
            "status": "pass",
            "preview_count": map_preview_flagship.get("preview_count"),
            "receipt_path": str(map_preview_flagship_receipt_path),
        }
        if map_preview_flagship_receipt_path is not None and map_preview_flagship_ok
        else None,
        {
            "area": "browser_rendered_3d",
            "status": "pass",
            "providers": browser_3d_gate.get("providers") or [],
            "receipt_path": str(browser_3d_gate_receipt_path),
        }
        if browser_3d_gate_receipt_path is not None and browser_3d_gate_ok
        else None,
        {
            "area": "generated_reconstruction_glb",
            "status": "pass",
            "viewer_url": str(runtime_reconstruction.get("viewer_url") or ""),
            "public_route_contract_ok": runtime_reconstruction.get("public_route_contract_ok"),
            "glb_size_bytes": runtime_reconstruction_glb.get("size_bytes"),
            "receipt_path": str(runtime_reconstruction_receipt_path),
        }
        if runtime_reconstruction_receipt_path is not None and runtime_reconstruction_ok
        else None,
        {
            "area": "walkthrough_quality",
            "status": "pass",
            "video_relpath": str(walkthrough_quality.get("video_relpath") or ""),
            "receipt_path": str(walkthrough_quality_receipt_path),
        }
        if walkthrough_quality_receipt_path is not None and walkthrough_quality_ok
        else None,
        {
            "area": "scene_video_readiness",
            "status": "pass",
            "checked_providers": scene_video_readiness_verifier.get("checked_providers") or [],
            "provider_count": scene_video_readiness_verifier.get("provider_count"),
            "provider_runtime_ready": scene_video_provider_runtime_ready,
            "provider_blocked_count": scene_video_blocked_provider_count,
            "provider_action_required": bool(scene_video_blocked_provider_count or scene_video_next_actions),
            "receipt_path": str(scene_video_readiness_receipt_path) if scene_video_readiness_receipt_path is not None else "",
            "verifier_receipt_path": str(scene_video_readiness_verifier_receipt_path),
            "note": "Verifier pass means scene-video routing and actionability invariants hold; provider_runtime_ready shows whether MagicFit/OMagic provider capacity is actually clear.",
        }
        if scene_video_readiness_verifier_receipt_path is not None and scene_video_readiness_verifier_ok
        else None,
        {
            "area": "scene_video_provider_refresh_packet",
            "status": "pass",
            "checked_providers": scene_video_provider_refresh_packet_verifier.get("checked_providers") or [],
            "provider_count": scene_video_provider_refresh_packet_verifier.get("provider_count"),
            "packet_path": str(scene_video_provider_refresh_packet_path) if scene_video_provider_refresh_packet_path is not None else "",
            "verifier_receipt_path": str(scene_video_provider_refresh_packet_verifier_receipt_path),
            "note": "Provider-refresh packet verifier pass means MagicFit and OMagic/Magic account refresh instructions are secret-safe and preserve the 1min no-touch boundary.",
        }
        if scene_video_provider_refresh_packet_verifier_receipt_path is not None and scene_video_provider_refresh_packet_verifier_ok
        else None,
        {"area": "receipt_freshness", "status": "pass"}
        if receipt_freshness_ok
        else None,
    ]
    status = (
        "pass"
        if (
            not blockers
            and performance_ok
            and analytics_ok
            and live_mobile_ok
            and public_auth_ok
            and id_austria_ok
            and authenticated_customer_ok
            and tour_controls_ok
            and export_discovery_ok
            and operator_import_manifest_ok
            and billing_ok
            and repair_canary_ok
            and provider_catalog_smoke_ok
            and provider_matrix_ok
            and whole_project_scope_ok
            and security_posture_ok
            and release_hygiene_ok
            and furniture_style_contract_ok
            and bts_methodology_contract_ok
            and tour_delivery_contract_ok
            and map_preview_flagship_ok
            and browser_3d_gate_ok
            and runtime_reconstruction_ok
            and walkthrough_quality_ok
            and scene_video_readiness_verifier_ok
            and scene_video_provider_refresh_packet_verifier_ok
            and receipt_freshness_ok
        )
        else "blocked"
    )
    billing_provider_status = str(
        billing_receipt.get("status") or ("not_configured" if billing_receipt_path is None else "missing")
    )
    billing_handoff_status = "ready" if billing_ok else billing_provider_status
    notes: list[str] = []
    if status == "pass":
        notes.extend(
            [
                "Current gold gate is green on the active proof set.",
                (
                    f"Provider E2E is current: {provider_matrix_case_count} targeted strict/soft cases passed across every "
                    "search-ready provider mode with wrong-country selections sanitized before dispatch."
                ),
                "Self-healing canary is current and proves repair-or-quarantine behavior for failed provider sources.",
                (
                    "Prepared operator import folders can still wait for future verified asset drops without blocking the "
                    "current release."
                    if operator_import_manifest_ready and export_repair_sample
                    else "Prepared operator import folders are aligned with the active verified release."
                ),
            ]
        )
    else:
        notes.append("Gold remains blocked until every failing gate below is repaired.")
        if not missing_provider_modes:
            notes.append("Tour provider coverage is complete in the active verifier output.")
        if not repair_canary_ok:
            notes.append("Self-healing is proven only when the repair canary repairs or safely quarantines a failed provider source.")
        if not provider_matrix_ok:
            notes.append(
                "Provider E2E is proven only when every search-ready provider has executed strict and soft-filter targeted search cases."
            )
        if missing_provider_modes:
            notes.append("Every required tour provider mode must stay backed by verified evidence.")
        if "magicfit" in missing_provider_modes and vendor_tooling_receipt_path is not None and not bool(magicfit_renderer.get("ready")):
            notes.append("MagicFit is still blocked on renderer configuration, not just a missing imported walkthrough asset.")
        if not browser_3d_gate_ok:
            notes.append("3D browser readiness is blocked until the viewer renders in Chromium, not merely until a tour route exists.")
        if not runtime_reconstruction_ok:
            notes.append("Generated reconstruction readiness is blocked until the live runtime exports a non-empty GLB and public routes reject generated previews as 3D tours.")
        if not map_preview_flagship_ok:
            notes.append("Map preview readiness is blocked until generated thumbnails pass the visual-asset gate, not merely until the PNG route exists.")
        if not walkthrough_quality_ok:
            notes.append("Walkthrough readiness is blocked until room coverage and frame-continuity proof pass.")
        if not scene_video_readiness_verifier_ok:
            notes.append("Scene-video readiness is blocked until the verifier proves Mootion BrowserAct, Telegram, 1min isolation, and MagicFit/OMagic actionability invariants.")
        if scene_video_provider_action_required:
            notes.append("Scene-video provider runtime is blocked until MagicFit/Magic/OMagic account, credit, credential, and adapter gaps are cleared in the readiness receipt.")
        if bool(omagic_adapter.get("runtime_checked")) and not bool(omagic_adapter.get("ready")):
            notes.append("OMagic model-upload adapter deployment is blocked until the checked runtime contains the packaged adapter script.")
    notes.append(_tour_provider_missing_note(missing_provider_modes))
    ready_for_notification = status == "pass" and not blockers and not next_required_actions

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "ready_for_notification": ready_for_notification,
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
            "delivery_contracts": tour_controls.get("delivery_contracts") or {},
            "magicfit_playback": magicfit_playback,
            "magicfit_playback_ok": magicfit_playback_ok,
            "ready_provider_modes": tour_controls.get("ready_provider_modes"),
            "required_provider_modes": list(REQUIRED_TOUR_PROVIDER_MODES),
            "optional_provider_modes": list(OPTIONAL_TOUR_PROVIDER_MODES),
            "receipt_required_provider_modes": tour_controls.get("required_provider_modes") or [],
            "receipt_optional_provider_modes": tour_controls.get("optional_provider_modes") or [],
            "missing_provider_modes": missing_provider_modes,
            "receipt_path": str(tour_control_receipt_path),
        },
        "browser_rendered_3d": {
            "status": browser_3d_gate.get("status") or ("not_configured" if browser_3d_gate_receipt_path is None else "missing"),
            "failed_count": browser_3d_gate.get("failed_count") if browser_3d_gate_receipt_path is not None else None,
            "providers": browser_3d_gate.get("providers") or [],
            "provider_results": browser_3d_gate.get("provider_results") or [],
            "failed_checks": _failed_receipt_checks(browser_3d_gate) if browser_3d_gate_receipt_path is not None else [],
            "ready": browser_3d_gate_ok if browser_3d_gate_receipt_path is not None else None,
            "receipt_path": str(browser_3d_gate_receipt_path) if browser_3d_gate_receipt_path is not None else "",
            "note": "Hard browser gate: route existence or static labels do not prove 3D readiness.",
        },
        "generated_reconstruction_glb": {
            "status": runtime_reconstruction.get("status") or ("not_configured" if runtime_reconstruction_receipt_path is None else "missing"),
            "ready": runtime_reconstruction_ok if runtime_reconstruction_receipt_path is not None else None,
            "glb_required": runtime_reconstruction.get("glb_required") if runtime_reconstruction_receipt_path is not None else None,
            "glb_non_empty": runtime_reconstruction.get("glb_non_empty") if runtime_reconstruction_receipt_path is not None else None,
            "glb_manifest_ok": runtime_reconstruction.get("glb_manifest_ok") if runtime_reconstruction_receipt_path is not None else None,
            "glb_capability_ok": runtime_reconstruction.get("glb_capability_ok") if runtime_reconstruction_receipt_path is not None else None,
            "required_paths_ok": runtime_reconstruction.get("required_paths_ok") if runtime_reconstruction_receipt_path is not None else None,
            "public_route_contract_ok": runtime_reconstruction.get("public_route_contract_ok") if runtime_reconstruction_receipt_path is not None else None,
            "viewer_url": str(runtime_reconstruction.get("viewer_url") or ""),
            "glb_size_bytes": runtime_reconstruction_glb.get("size_bytes"),
            "receipt_path": str(runtime_reconstruction_receipt_path) if runtime_reconstruction_receipt_path is not None else "",
            "note": "Hard generated-reconstruction gate: OBJ/viewer existence does not prove GLB export, and generated previews must not leak as public 3D tours.",
        },
        "map_preview_flagship": {
            "status": map_preview_flagship.get("status") or ("not_configured" if map_preview_flagship_receipt_path is None else "missing"),
            "failed_count": map_preview_flagship.get("failed_count") if map_preview_flagship_receipt_path is not None else None,
            "preview_count": map_preview_flagship.get("preview_count") if map_preview_flagship_receipt_path is not None else None,
            "failed_checks": _failed_receipt_checks(map_preview_flagship) if map_preview_flagship_receipt_path is not None else [],
            "preview_results": list(map_preview_flagship.get("preview_results") or [])[:6] if map_preview_flagship_receipt_path is not None else [],
            "ready": map_preview_flagship_ok if map_preview_flagship_receipt_path is not None else None,
            "receipt_path": str(map_preview_flagship_receipt_path) if map_preview_flagship_receipt_path is not None else "",
            "note": "Hard visual-asset gate: image availability does not prove a flagship map thumbnail.",
        },
        "walkthrough_quality": {
            "status": walkthrough_quality.get("status") or ("not_configured" if walkthrough_quality_receipt_path is None else "missing"),
            "failed_count": walkthrough_quality.get("failed_count") if walkthrough_quality_receipt_path is not None else None,
            "video_relpath": str(walkthrough_quality.get("video_relpath") or ""),
            "failed_checks": _failed_receipt_checks(walkthrough_quality) if walkthrough_quality_receipt_path is not None else [],
            "ready": walkthrough_quality_ok if walkthrough_quality_receipt_path is not None else None,
            "receipt_path": str(walkthrough_quality_receipt_path) if walkthrough_quality_receipt_path is not None else "",
            "note": "Hard walkthrough gate: video existence does not prove room coverage or continuity.",
        },
        "scene_video_readiness": {
            "status": scene_video_readiness_verifier.get("status") or ("not_configured" if scene_video_readiness_verifier_receipt_path is None else "missing"),
            "ready": (
                scene_video_readiness_verifier_ok and scene_video_provider_refresh_packet_verifier_ok
                if scene_video_readiness_verifier_receipt_path is not None
                else None
            ),
            "actionability_ready": (
                scene_video_readiness_verifier_ok and scene_video_provider_refresh_packet_verifier_ok
                if scene_video_readiness_verifier_receipt_path is not None
                else None
            ),
            "provider_runtime_ready": scene_video_provider_runtime_ready if scene_video_readiness_receipt_path is not None else None,
            "provider_action_required": bool(scene_video_blocked_provider_count or scene_video_next_actions)
            if scene_video_readiness_receipt_path is not None
            else None,
            "provider_blocked_count": scene_video_blocked_provider_count if scene_video_readiness_receipt_path is not None else None,
            "blocked_providers": scene_video_blocked_providers,
            "provider_summary": scene_video_provider_summary,
            "telegram_delivery_readiness": scene_video_readiness.get("telegram_delivery_readiness") or {},
            "next_actions": scene_video_next_actions,
            "verifier_blockers": list(scene_video_readiness_verifier.get("blockers") or []) if scene_video_readiness_verifier_receipt_path is not None else [],
            "checked_providers": scene_video_readiness_verifier.get("checked_providers") or [],
            "receipt_path": str(scene_video_readiness_receipt_path) if scene_video_readiness_receipt_path is not None else "",
            "verifier_receipt_path": str(scene_video_readiness_verifier_receipt_path) if scene_video_readiness_verifier_receipt_path is not None else "",
            "provider_refresh_packet": {
                "status": (
                    scene_video_provider_refresh_packet_verifier.get("status")
                    or ("not_configured" if scene_video_provider_refresh_packet_verifier_receipt_path is None else "missing")
                ),
                "ready": (
                    scene_video_provider_refresh_packet_verifier_ok
                    if scene_video_provider_refresh_packet_verifier_receipt_path is not None
                    else None
                ),
                "checked_providers": scene_video_provider_refresh_packet_verifier.get("checked_providers") or [],
                "verifier_blockers": list(scene_video_provider_refresh_packet_verifier.get("blockers") or [])
                if scene_video_provider_refresh_packet_verifier_receipt_path is not None
                else [],
                "packet_provider_count": len(list(scene_video_provider_refresh_packet.get("providers") or []))
                if scene_video_provider_refresh_packet_path is not None
                else None,
                "packet_path": str(scene_video_provider_refresh_packet_path) if scene_video_provider_refresh_packet_path is not None else "",
                "verifier_receipt_path": str(scene_video_provider_refresh_packet_verifier_receipt_path)
                if scene_video_provider_refresh_packet_verifier_receipt_path is not None
                else "",
            },
            "note": "Scene-video verifier guards Mootion BrowserAct, Telegram delivery readiness, 1min isolation, and MagicFit/OMagic actionability without embedding secrets.",
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
            "account_handoff_usable": (billing_receipt.get("billing_handoff") or {}).get("account_handoff_usable") if isinstance(billing_receipt.get("billing_handoff"), dict) else None,
            "direct_account_handoff_usable": billing_readiness.get("direct_account_handoff_usable"),
            "signed_handoff_usable": bool(billing_readiness.get("signed_handoff_usable")),
            "ready_via": str(billing_readiness.get("ready_via") or ""),
            "live_smoke_external_handoff_usable": bool(billing_readiness.get("live_smoke_external_handoff_usable")),
            "live_smoke_no_second_login": bool(billing_readiness.get("live_smoke_no_second_login")),
            "live_smoke_bridge_launch": bool(billing_readiness.get("live_smoke_bridge_launch")),
            "bridge_guided_login_assist": bool(billing_readiness.get("bridge_guided_login_assist")),
            "pricing_placeholder": bool(billing_readiness.get("pricing_placeholder")),
            "account_handoff_error": str((billing_receipt.get("billing_handoff") or {}).get("account_handoff_error") or "") if isinstance(billing_receipt.get("billing_handoff"), dict) else "",
            "required_dns_record": (billing_receipt.get("billing_handoff") or {}).get("required_dns_record") if isinstance(billing_receipt.get("billing_handoff"), dict) and isinstance((billing_receipt.get("billing_handoff") or {}).get("required_dns_record"), dict) else {},
            "next_action": str((billing_receipt.get("billing_handoff") or {}).get("next_action") or "") if isinstance(billing_receipt.get("billing_handoff"), dict) else "",
            "sso_bridge": {
                "ready": (billing_receipt.get("billing_sso_bridge") or {}).get("ready") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else None,
                "config_ready": (billing_receipt.get("billing_sso_bridge") or {}).get("config_ready") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else None,
                "exchange_checked": (billing_receipt.get("billing_sso_bridge") or {}).get("exchange_checked") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else None,
                "exchange_usable": (billing_receipt.get("billing_sso_bridge") or {}).get("exchange_usable") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else None,
                "error": str((billing_receipt.get("billing_sso_bridge") or {}).get("error") or "") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else "",
                "next_action": str((billing_receipt.get("billing_sso_bridge") or {}).get("next_action") or "") if isinstance(billing_receipt.get("billing_sso_bridge"), dict) else "",
            },
            "member_login_token": {
                "enabled": (billing_receipt.get("member_login_token_handoff") or {}).get("enabled") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else None,
                "configured": (billing_receipt.get("member_login_token_handoff") or {}).get("configured") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else None,
                "ready": (billing_receipt.get("member_login_token_handoff") or {}).get("ready") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else None,
                "error": str((billing_receipt.get("member_login_token_handoff") or {}).get("error") or "") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else "",
                "next_action": str((billing_receipt.get("member_login_token_handoff") or {}).get("next_action") or "") if isinstance(billing_receipt.get("member_login_token_handoff"), dict) else "",
                "required_env": list(BILLING_MEMBER_TOKEN_REQUIRED_ENV),
            },
            "ready": billing_ok,
            "receipt_path": str(billing_receipt_path) if billing_receipt_path is not None else "",
        },
        "id_austria": {
            "status": id_austria_details.get("status") if id_austria_receipt_path is not None else "not_checked",
            "required": bool(id_austria_details.get("required")) if id_austria_receipt_path is not None else False,
            "configured": bool(id_austria_details.get("configured")) if id_austria_receipt_path is not None else False,
            "error": str(id_austria_details.get("error") or "") if id_austria_receipt_path is not None else "",
            "missing_env": list(id_austria_details.get("missing_env") or []) if id_austria_receipt_path is not None else [],
            "redirect_uri": str(id_austria_details.get("redirect_uri") or "") if id_austria_receipt_path is not None else "",
            "issuer": str(id_austria_details.get("issuer") or "") if id_austria_receipt_path is not None else "",
            "ready": bool(id_austria_details.get("ready")) if id_austria_receipt_path is not None else True,
            "receipt_path": str(id_austria_receipt_path) if id_austria_receipt_path is not None else "",
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
            "magicfit_renderer": magicfit_renderer,
            "omagic_adapter": omagic_adapter,
            "next_actions": vendor_tooling.get("next_actions") or [],
            "receipt_path": str(vendor_tooling_receipt_path) if vendor_tooling_receipt_path is not None else "",
            "note": "Host tooling readiness is tracked separately from verified 3D-tour export evidence and walkthrough render-lane configuration.",
        },
        "tour_provider_ownership": {
            "status": tour_provider_ownership.get("status") or ("not_configured" if tour_provider_ownership_receipt_path is None else "missing"),
            "missing_providers": tour_provider_ownership.get("missing_providers") or [],
            "providers": sorted((tour_provider_ownership.get("providers") or {}).keys()) if isinstance(tour_provider_ownership.get("providers"), dict) else [],
            "ready": tour_provider_ownership_ok,
            "receipt_path": str(tour_provider_ownership_receipt_path) if tour_provider_ownership_receipt_path is not None else "",
            "note": "This does not satisfy 3D-tour gold without verified polished 3D-tour exports or allowlisted hosted controls.",
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
        "provider_catalog_smoke": provider_catalog_smoke,
        "whole_project_scope": {
            "status": whole_project_scope.get("status") or ("not_configured" if whole_project_scope_receipt_path is None else "missing"),
            "schema": str(whole_project_scope.get("schema") or "") if whole_project_scope_receipt_path is not None else "",
            "required_overlay_layers": whole_project_scope.get("required_overlay_layers") or [],
            "failure_count": len(list(whole_project_scope.get("failures") or [])) if whole_project_scope_receipt_path is not None else None,
            "failures": list(whole_project_scope.get("failures") or [])[:12] if whole_project_scope_receipt_path is not None else [],
            "receipt_path": str(whole_project_scope_receipt_path) if whole_project_scope_receipt_path is not None else "",
            "note": "Whole-project scope covers evidence-overlay registry shape, async Teable-first ingestion policy, cached-read-model search policy, and whole-product boundary language.",
        },
        "production_security_posture": {
            "status": security_posture.get("status") or ("not_configured" if security_posture_receipt_path is None else "missing"),
            "schema": str(security_posture.get("schema") or "") if security_posture_receipt_path is not None else "",
            "required_checks": security_posture.get("required_checks") or [],
            "failure_count": len(list(security_posture.get("failures") or [])) if security_posture_receipt_path is not None else None,
            "failures": list(security_posture.get("failures") or [])[:12] if security_posture_receipt_path is not None else [],
            "receipt_path": str(security_posture_receipt_path) if security_posture_receipt_path is not None else "",
            "note": "Static security gate for isolated runtime/container posture, public-tour privacy, and locked Python dependency posture.",
        },
        "release_hygiene": {
            "status": release_hygiene.get("status") or ("not_configured" if release_hygiene_receipt_path is None else "missing"),
            "schema": str(release_hygiene.get("schema") or "") if release_hygiene_receipt_path is not None else "",
            "required_checks": release_hygiene.get("required_checks") or [],
            "failure_count": len(list(release_hygiene.get("failures") or [])) if release_hygiene_receipt_path is not None else None,
            "failures": list(release_hygiene.get("failures") or [])[:12] if release_hygiene_receipt_path is not None else [],
            "manifest_runtime_commit": str(release_hygiene.get("manifest_runtime_commit") or "") if release_hygiene_receipt_path is not None else "",
            "head_commit": str(release_hygiene.get("head_commit") or "") if release_hygiene_receipt_path is not None else "",
            "parent_commit": str(release_hygiene.get("parent_commit") or "") if release_hygiene_receipt_path is not None else "",
            "receipt_path": str(release_hygiene_receipt_path) if release_hygiene_receipt_path is not None else "",
            "note": "Repository hygiene and release-manifest authority gate.",
        },
        "furniture_style_variants": {
            "status": furniture_style_contract.get("status") or ("not_configured" if furniture_style_contract_receipt_path is None else "missing"),
            "schema": str(furniture_style_contract.get("schema") or "") if furniture_style_contract_receipt_path is not None else "",
            "style_count": furniture_style_contract.get("style_count") if furniture_style_contract_receipt_path is not None else None,
            "style_values": furniture_style_contract.get("style_values") or [],
            "plan_caps": furniture_style_contract.get("plan_caps") or {},
            "failure_count": len(list(furniture_style_contract.get("failures") or [])) if furniture_style_contract_receipt_path is not None else None,
            "failures": list(furniture_style_contract.get("failures") or [])[:12] if furniture_style_contract_receipt_path is not None else [],
            "receipt_path": str(furniture_style_contract_receipt_path) if furniture_style_contract_receipt_path is not None else "",
            "note": "Furniture-style variants are entitlement-gated and style-aware; this does not replace verified 3D-tour provider evidence.",
        },
        "bts_methodology": {
            "status": bts_methodology_contract.get("status") or ("not_configured" if bts_methodology_contract_receipt_path is None else "missing"),
            "schema": str(bts_methodology_contract.get("schema") or "") if bts_methodology_contract_receipt_path is not None else "",
            "language_count": bts_methodology_contract.get("language_count") if bts_methodology_contract_receipt_path is not None else None,
            "languages": bts_methodology_contract.get("languages") or [],
            "source_section_count": bts_methodology_contract.get("source_section_count") if bts_methodology_contract_receipt_path is not None else None,
            "failure_count": len(list(bts_methodology_contract.get("failures") or [])) if bts_methodology_contract_receipt_path is not None else None,
            "failures": list(bts_methodology_contract.get("failures") or [])[:12] if bts_methodology_contract_receipt_path is not None else [],
            "receipt_path": str(bts_methodology_contract_receipt_path) if bts_methodology_contract_receipt_path is not None else "",
            "note": "BTS score-PDF methodology gate for data-source provenance and selected-district no-reward scoring policy.",
        },
        "tour_delivery_contract_shape": {
            "status": tour_delivery_contract.get("status") or ("not_configured" if tour_delivery_contract_receipt_path is None else "missing"),
            "schema": str(tour_delivery_contract.get("schema") or "") if tour_delivery_contract_receipt_path is not None else "",
            "required_provider_modes": tour_delivery_contract.get("required_provider_modes") or tour_delivery_contract.get("required_providers") or [],
            "optional_provider_modes": tour_delivery_contract.get("optional_provider_modes") or [],
            "ready_provider_modes": tour_delivery_contract.get("ready_provider_modes") or [],
            "missing_provider_modes": tour_delivery_contract.get("missing_provider_modes") or [],
            "matterport_ready_count": tour_delivery_contract.get("matterport_ready_count") if tour_delivery_contract_receipt_path is not None else None,
            "failure_count": len(list(tour_delivery_contract.get("failures") or [])) if tour_delivery_contract_receipt_path is not None else None,
            "failures": list(tour_delivery_contract.get("failures") or [])[:12] if tour_delivery_contract_receipt_path is not None else [],
            "receipt_path": str(tour_delivery_contract_receipt_path) if tour_delivery_contract_receipt_path is not None else "",
            "note": "Public-safe tour delivery contract shape gate with Chummer-derived ready/blocker vocabulary and first-class Matterport readiness.",
        },
        "receipt_freshness": {
            "status": "pass" if receipt_freshness_ok else "fail",
            "max_age_hours": max_receipt_age_hours,
            "stale_receipts": stale_receipts,
        },
        "blockers": blockers,
        "pass_areas": [row for row in pass_areas if row is not None],
        "next_required_actions": next_required_actions,
        "notes": notes,
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
    parser.add_argument("--whole-project-scope-receipt", default="")
    parser.add_argument("--security-posture-receipt", default="")
    parser.add_argument("--release-hygiene-receipt", default="")
    parser.add_argument("--furniture-style-contract-receipt", default="")
    parser.add_argument("--bts-methodology-contract-receipt", default="")
    parser.add_argument("--tour-delivery-contract-receipt", default="")
    parser.add_argument("--map-preview-flagship-receipt", default="")
    parser.add_argument("--browser-3d-gate-receipt", default="")
    parser.add_argument("--runtime-reconstruction-receipt", default="")
    parser.add_argument("--walkthrough-quality-receipt", default="")
    parser.add_argument("--scene-video-readiness-receipt", default="")
    parser.add_argument("--scene-video-readiness-verifier-receipt", default="")
    parser.add_argument("--scene-video-provider-refresh-packet", default="")
    parser.add_argument("--scene-video-provider-refresh-packet-verifier-receipt", default="")
    parser.add_argument("--id-austria-receipt", default="")
    parser.add_argument("--repair-canary-receipt", default="")
    parser.add_argument("--provider-catalog-receipt", default="")
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
        tour_provider_ownership_receipt_path=Path(args.tour_provider_ownership_receipt) if args.tour_provider_ownership_receipt else _default_receipt_path("tour_provider_ownership"),
        vendor_tooling_receipt_path=Path(args.vendor_tooling_receipt) if args.vendor_tooling_receipt else _default_receipt_path("vendor_tooling"),
        whole_project_scope_receipt_path=Path(args.whole_project_scope_receipt) if args.whole_project_scope_receipt else _default_receipt_path("whole_project_scope"),
        security_posture_receipt_path=Path(args.security_posture_receipt) if args.security_posture_receipt else _default_receipt_path("security_posture"),
        release_hygiene_receipt_path=Path(args.release_hygiene_receipt) if args.release_hygiene_receipt else _default_receipt_path("release_hygiene"),
        furniture_style_contract_receipt_path=Path(args.furniture_style_contract_receipt) if args.furniture_style_contract_receipt else _default_receipt_path("furniture_style_contract"),
        bts_methodology_contract_receipt_path=Path(args.bts_methodology_contract_receipt) if args.bts_methodology_contract_receipt else _default_receipt_path("bts_methodology_contract"),
        tour_delivery_contract_receipt_path=Path(args.tour_delivery_contract_receipt) if args.tour_delivery_contract_receipt else _default_receipt_path("tour_delivery_contract"),
        map_preview_flagship_receipt_path=Path(args.map_preview_flagship_receipt) if args.map_preview_flagship_receipt else _default_receipt_path("map_preview_flagship"),
        browser_3d_gate_receipt_path=Path(args.browser_3d_gate_receipt) if args.browser_3d_gate_receipt else _default_receipt_path("browser_3d_gate"),
        runtime_reconstruction_receipt_path=(
            Path(args.runtime_reconstruction_receipt)
            if args.runtime_reconstruction_receipt
            else _default_receipt_path("runtime_reconstruction")
        ),
        walkthrough_quality_receipt_path=Path(args.walkthrough_quality_receipt) if args.walkthrough_quality_receipt else _default_receipt_path("walkthrough_quality"),
        scene_video_readiness_receipt_path=(
            Path(args.scene_video_readiness_receipt)
            if args.scene_video_readiness_receipt
            else _default_receipt_path("scene_video_readiness")
        ),
        scene_video_readiness_verifier_receipt_path=(
            Path(args.scene_video_readiness_verifier_receipt)
            if args.scene_video_readiness_verifier_receipt
            else _default_receipt_path("scene_video_readiness_verifier")
        ),
        scene_video_provider_refresh_packet_path=(
            Path(args.scene_video_provider_refresh_packet)
            if args.scene_video_provider_refresh_packet
            else _default_receipt_path("scene_video_provider_refresh_packet")
        ),
        scene_video_provider_refresh_packet_verifier_receipt_path=(
            Path(args.scene_video_provider_refresh_packet_verifier_receipt)
            if args.scene_video_provider_refresh_packet_verifier_receipt
            else _default_receipt_path("scene_video_provider_refresh_packet_verifier")
        ),
        id_austria_receipt_path=Path(args.id_austria_receipt) if args.id_austria_receipt else _default_receipt_path("id_austria"),
        repair_canary_receipt_path=Path(args.repair_canary_receipt) if args.repair_canary_receipt else _default_receipt_path("repair_canary"),
        provider_catalog_receipt_path=(
            Path(args.provider_catalog_receipt)
            if args.provider_catalog_receipt
            else _default_receipt_path_if_exists("provider_catalog")
        ),
        provider_matrix_receipt_path=Path(args.provider_matrix_receipt) if args.provider_matrix_receipt else _default_receipt_path("provider_matrix"),
        max_receipt_age_hours=args.max_receipt_age_hours,
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        _write_gold_status_output(out_path, output)
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
