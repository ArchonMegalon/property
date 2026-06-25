from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.propertyquarry_gold_status import build_gold_status_receipt


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gold_status_cli_defaults_to_live_container_tour_receipt() -> None:
    source = (ROOT / "scripts/propertyquarry_gold_status.py").read_text(encoding="utf-8")

    assert "_completion/tours/property-tour-controls-live-container-current.json" in source
    assert "_completion/smoke/property-live-public-latest.json" in source
    assert "_completion/smoke/property-live-authenticated-latest.json" in source
    assert "_completion/tours/property-tour-controls-after-monotonic-counters.json" not in source


def _provider_matrix_payload(*, status: str = "pass", executed: bool = True) -> dict[str, object]:
    return {
        "status": status,
        "country_scope": "all_search_ready",
        "targeted_search_matrix_status": "pass" if status == "pass" else "planned",
        "targeted_search_matrix_executed": executed,
        "targeted_search_matrix_count": 242,
        "targeted_search_matrix_summary": {
            "executed": executed,
            "strict_case_count": 121,
            "soft_filter_case_count": 121,
            "failed_case_count": 0,
            "all_search_ready_providers_covered": True,
            "all_search_ready_provider_modes_passed": True,
            "dispatch_acceptance_complete": True,
            "status_readback_complete": True,
            "payload_contracts_ok": True,
            "provider_country_scope_ok": True,
            "target_context_country_scope_ok": True,
            "agent_unlimited_results_ok": True,
            "strict_without_soft_filters_ok": True,
            "soft_filters_present_ok": True,
        },
        "cross_country_sanitization_summary": {
            "case_count": 18,
            "status_counts": {"pass": 18},
            "sanitization_ok": True,
        },
    }


def _performance_payload(*, include_research_checks: bool = True, include_analytics_checks: bool = True) -> dict[str, object]:
    checks = [
        {"name": "research_candidate", "ok": True},
        {"name": "research_visual_cards_present", "ok": True},
        {"name": "research_visual_requests_honest", "ok": True},
        {"name": "research_no_fake_visual_ready", "ok": True},
        {"name": "research_confirmed_listing_facts", "ok": True},
        {"name": "research_confirmed_price_signal", "ok": True},
        {"name": "research_mobile_open_property_compact_layout", "ok": True},
        {"name": "research_mobile_visual_frame_compact", "ok": True},
    ]
    analytics_checks = [
        {"name": "rybbit_no_identify", "ok": True},
        {"name": "rybbit_taxonomy_events_only", "ok": True},
        {"name": "rybbit_allowed_attributes_only", "ok": True},
        {"name": "rybbit_no_private_payload", "ok": True},
    ]
    if include_analytics_checks:
        checks.extend(analytics_checks)
    return {
        "status": "pass",
        "failed_count": 0,
        "route_count": 15,
        "routes": [
            {
                "path": "/app/research/perf-candidate-1020?run_id=run-gold",
                "ok": True,
                "checks": checks if include_research_checks else checks[:4],
            }
        ],
    }


def _billing_payload(*, host_resolves: bool = True, status: str = "disabled") -> dict[str, object]:
    return {
        "status": status,
        "error": "" if host_resolves and status != "blocked" else "billing_handoff_host_unresolved:gaierror",
        "billing_handoff": {
            "configured": True,
            "url": "https://billing.propertyquarry.com/account",
            "host": "billing.propertyquarry.com",
            "host_resolves": host_resolves,
            "error": "" if host_resolves else "billing_handoff_host_unresolved:gaierror",
        },
    }


def _live_mobile_payload(*, routes: list[str] | None = None, status: str = "pass", failed_count: int = 0) -> dict[str, object]:
    route_list = routes or [
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
        "/app/research/perf-candidate-1020?run_id=run-gold",
        "/app/properties/packets",
    ]
    return {
        "status": status,
        "failed_count": failed_count,
        "route_count": len(route_list),
        "viewport": {"width": 390, "height": 844},
        "routes": [{"route": route, "ok": True, "checks": []} for route in route_list],
    }


def _public_smoke_payload(*, status: str = "pass", failed_count: int = 0, include_account_creation: bool = True) -> dict[str, object]:
    sign_in_checks = [
        {"name": "sign_in_minimal_copy", "ok": True},
        {"name": "sign_in_provider_creates_account", "ok": include_account_creation},
        {"name": "sign_in_no_unavailable_auth_copy", "ok": True},
        {"name": "sign_in_google_state", "ok": True},
        {"name": "sign_in_google_feedback", "ok": True},
    ]
    return {
        "status": status,
        "failed_count": failed_count,
        "route_count": 22,
        "checks": [
            {
                "path": "/sign-in",
                "ok": status == "pass" and failed_count == 0 and include_account_creation,
                "checks": sign_in_checks,
            }
        ],
    }


def _authenticated_smoke_payload(
    *,
    status: str = "pass",
    failed_count: int = 0,
    billing_external: bool = False,
    billing_fail_closed: bool = True,
    local_board_deleted: bool = True,
    include_notification_checks: bool = True,
) -> dict[str, object]:
    billing_checks = [
        {"name": "billing_local_board_deleted", "ok": local_board_deleted, "detail": "" if local_board_deleted else "billing history, compare plans"},
    ]
    if billing_external:
        billing_checks.append({"name": "billing_external_handoff", "ok": True})
    if billing_fail_closed:
        billing_checks.append({"name": "billing_fail_closed_recovery", "ok": True})
    notification_checks = [
        {"name": "account_notifications", "ok": True},
        {"name": "account_notification_form", "ok": True},
        {"name": "account_notification_email_channel", "ok": True},
        {"name": "account_notification_telegram_channel", "ok": True},
        {"name": "account_notification_whatsapp_channel", "ok": True},
        {"name": "account_notification_primary_route", "ok": True},
        {"name": "account_notification_whatsapp_phone", "ok": True},
        {"name": "account_notification_save_action", "ok": True},
    ]
    return {
        "status": status,
        "failed_count": failed_count,
        "route_count": 3,
        "checks": [
            {
                "path": "/app/account",
                "status_code": 200,
                "ok": status == "pass" and failed_count == 0 and include_notification_checks,
                "checks": notification_checks if include_notification_checks else notification_checks[:2],
            },
            {
                "path": "/app/billing",
                "status_code": 303 if billing_external else 503,
                "ok": status == "pass" and failed_count == 0 and local_board_deleted and (billing_external or billing_fail_closed),
                "checks": billing_checks,
            }
        ],
    }


def _write_hardened_drop_readmes(tmp_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    provider_bodies = {
        "3dvista": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example: python /app/scripts/import_3dvista_export.py --slug demo --export-dir drop/3dvista
Gold only passes when verify_property_tour_controls reports ready provider modes.
Copy the complete 3DVista export folder into this directory.
The entry must contain tdvplayer.
""",
        "pano2vr": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example: python /app/scripts/import_pano2vr_export.py --slug demo --export-dir drop/pano2vr
Gold only passes when verify_property_tour_controls reports ready provider modes.
Copy the complete Pano2VR output folder into this directory.
The entry must contain tour.js.
""",
        "krpano": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example: python /app/scripts/import_krpano_walkable_scene.py --slug demo --panorama drop/krpano/panorama.jpg
Gold only passes when verify_property_tour_controls reports ready provider modes.
Copy cube-face-1 through cube-face-6 or a real panorama.
Set KRPANO_LICENSE_DOMAIN=propertyquarry.com before importing.
""",
        "magicfit": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example: python /app/scripts/import_magicfit_walkthrough.py --slug demo --video-path drop/magicfit/magicfit-walkthrough.mp4 --source-receipt drop/magicfit/magicfit-receipt.json
Gold only passes when verify_property_tour_controls reports ready provider modes.
Copy magicfit-walkthrough.mp4 and magicfit-receipt.json into this directory.
""",
    }
    for provider, body in provider_bodies.items():
        export_dir = tmp_path / "drop" / provider
        export_dir.mkdir(parents=True, exist_ok=True)
        readme = export_dir / "README.propertyquarry-export.txt"
        readme.write_text(body, encoding="utf-8")
        rows.append({"provider": provider, "export_dir": str(export_dir), "readme": str(readme)})
    return rows


def _import_manifest_payload(tmp_path: Path, *, hardened_readmes: bool = True) -> dict[str, object]:
    providers = ["3dvista", "pano2vr", "krpano", "magicfit"]
    prepared_drop_dirs: list[dict[str, str]]
    if hardened_readmes:
        prepared_drop_dirs = _write_hardened_drop_readmes(tmp_path)
    else:
        prepared_drop_dirs = []
        for provider in providers:
            export_dir = tmp_path / "drop" / provider
            export_dir.mkdir(parents=True, exist_ok=True)
            readme = export_dir / "README.propertyquarry-export.txt"
            readme.write_text("Old placeholder instructions", encoding="utf-8")
            prepared_drop_dirs.append({"provider": provider, "export_dir": str(export_dir), "readme": str(readme)})
    return {
        "status": "waiting_for_verified_assets",
        "import_count": len(providers),
        "providers": providers,
        "drop_status_summary": {"ready_for_import": 0, "waiting_for_assets": len(providers), "other": 0},
        "prepared_drop_dirs": prepared_drop_dirs,
        "next_command": "python /app/scripts/import_property_tour_exports.py --manifest manifest.json",
    }


def test_gold_status_blocks_when_required_tour_provider_modes_are_missing(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 0, "pano2vr": 0, "krpano": 0, "magicfit": 0},
            "ready_provider_modes": ["matterport"],
            "missing_provider_modes": ["3dvista", "pano2vr", "krpano", "magicfit"],
            "next_required_actions": [{"provider": "magicfit", "action": "import a walkthrough"}],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {
            "status": "blocked_no_verified_exports",
            "import_count": 0,
            "rejected_count": 1,
            "rejected": [
                {
                    "slug": "family-flat",
                    "provider": "magicfit",
                    "reason": "magicfit_receipt_missing",
                    "action": "copy the matching MagicFit render receipt as magicfit-receipt.json or receipt.json",
                    "drop_layout": "<drop>/<slug>/magicfit/",
                }
            ],
            "repair_count": 1,
            "repair_manifest": [
                {
                    "slug": "family-flat",
                    "provider": "magicfit",
                    "status": "waiting_for_verified_assets",
                    "reason": "magicfit_receipt_missing",
                    "drop_path": "/drop/family-flat/magicfit",
                    "required_action": "copy the matching MagicFit render receipt as magicfit-receipt.json or receipt.json",
                    "import_command_after_assets_arrive": "python /app/scripts/import_magicfit_walkthrough.py --slug family-flat --video-path /drop/family-flat/magicfit/magicfit-walkthrough.mp4 --source-receipt /drop/family-flat/magicfit/magicfit-receipt.json",
                }
            ],
        },
    )
    import_manifest = _write_json(tmp_path / "import-manifest.json", _import_manifest_payload(tmp_path))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        import_manifest_receipt_path=import_manifest,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["performance"]["status"] == "pass"
    assert receipt["self_healing"]["status"] == "pass"
    assert receipt["provider_matrix"]["targeted_search_matrix_executed"] is True
    assert receipt["tour_controls"]["missing_provider_modes"] == ["3dvista", "pano2vr", "krpano", "magicfit"]
    assert receipt["operator_import_manifest"]["ready_for_exports"] is True
    assert receipt["operator_import_manifest"]["status"] == "waiting_for_verified_assets"
    assert receipt["operator_import_manifest"]["drop_status_summary"]["waiting_for_assets"] == 4
    assert receipt["operator_import_manifest"]["missing_prepared_providers"] == []
    assert receipt["operator_import_manifest"]["hardened_readmes_ok"] is True
    assert receipt["operator_import_manifest"]["hardened_readme_provider_count"] == 4
    assert "gold still requires real imported assets" in receipt["operator_import_manifest"]["note"]
    assert receipt["export_discovery"]["rejected_sample"][0]["reason"] == "magicfit_receipt_missing"
    assert receipt["export_discovery"]["repair_count"] == 1
    assert receipt["export_discovery"]["repair_sample"][0]["status"] == "waiting_for_verified_assets"
    assert "import_magicfit_walkthrough.py" in receipt["export_discovery"]["repair_sample"][0]["import_command_after_assets_arrive"]
    assert "magicfit-receipt.json" in receipt["next_required_actions"][-1]["action"]
    assert receipt["next_required_actions"][-1]["rejected_sample"][0]["provider"] == "magicfit"
    assert any(row["area"] == "verified_tour_provider_modes" for row in receipt["blockers"])
    assert any(row["area"] == "tour_export_drop" for row in receipt["blockers"])


def test_gold_status_missing_tour_action_excludes_already_verified_modes(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "blocked_missing_provider_modes",
            "provider_counts": {"matterport": 29, "magicfit": 8, "3dvista": 0, "pano2vr": 0, "krpano": 0},
            "provider_blockers": {
                "3dvista": {"blocked_count": 12, "reasons": [{"reason": "missing_3dvista_export", "count": 12, "action": "import a verified 3DVista export"}]},
                "pano2vr": {"blocked_count": 12, "reasons": [{"reason": "missing_pano2vr_export", "count": 12, "action": "import a verified Pano2VR export"}]},
                "krpano": {"blocked_count": 9, "reasons": [{"reason": "missing_walkable_scene", "count": 9, "action": "provide a real walkable_scene"}]},
            },
            "ready_provider_modes": ["matterport", "magicfit"],
            "missing_provider_modes": ["3dvista", "pano2vr", "krpano"],
            "next_required_actions": [
                {"provider": "3dvista", "action": "import a verified 3DVista export"},
                {"provider": "pano2vr", "action": "import a verified Pano2VR export"},
                {"provider": "krpano", "action": "provide a real walkable_scene"},
            ],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {
            "status": "blocked_no_verified_exports",
            "import_count": 0,
            "rejected_count": 4,
            "rejected": [
                {"slug": "flat", "provider": "3dvista", "reason": "3dvista_export_entry_unverified", "action": "copy the complete 3DVista export", "drop_layout": "<drop>/<slug>/3dvista/"},
                {"slug": "flat", "provider": "pano2vr", "reason": "pano2vr_export_entry_unverified", "action": "copy the complete Pano2VR export", "drop_layout": "<drop>/<slug>/pano2vr/"},
                {"slug": "flat", "provider": "krpano", "reason": "krpano_assets_missing", "action": "copy a real panorama", "drop_layout": "<drop>/<slug>/krpano/"},
                {"slug": "flat", "provider": "magicfit", "reason": "magicfit_video_missing", "action": "copy the MagicFit walkthrough", "drop_layout": "<drop>/<slug>/magicfit/"},
            ],
        },
    )
    import_manifest = _write_json(tmp_path / "import-manifest.json", _import_manifest_payload(tmp_path))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        import_manifest_receipt_path=import_manifest,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "verified_tour_provider_modes")
    assert blocker["missing_provider_modes"] == ["3dvista", "pano2vr", "krpano"]
    assert receipt["tour_controls"]["provider_blockers"]["krpano"]["reasons"][0]["reason"] == "missing_walkable_scene"
    assert "MagicFit" not in blocker["action"]
    assert "Matterport" not in blocker["action"]
    assert "3DVista" in blocker["action"]
    assert "Pano2VR" in blocker["action"]
    assert "krpano" in blocker["action"]
    aggregate_action = receipt["next_required_actions"][-1]
    assert aggregate_action["provider"] == "3dvista_pano2vr_krpano"
    assert {row["provider"] for row in aggregate_action["rejected_sample"]} == {"3dvista", "pano2vr", "krpano"}
    missing_note = receipt["notes"][-1]
    assert "MagicFit" not in missing_note
    assert "Matterport" not in missing_note
    assert "3DVista, Pano2VR, krpano" in missing_note


def test_gold_status_blocks_when_magicfit_ready_lacks_playback_proof(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "magicfit_playback": {"playback_ok": False, "playable_count": 0, "ready_count": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "magicfit_walkthrough_playback")
    assert receipt["status"] == "blocked"
    assert receipt["tour_controls"]["magicfit_playback_ok"] is False
    assert blocker["playable_count"] == 0
    assert blocker["ready_count"] == 1


def test_gold_status_passes_only_when_all_required_evidence_is_present(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "pass"
    assert receipt["performance"]["research_detail_checks_ok"] is True
    assert receipt["performance"]["missing_research_detail_checks"] == []
    assert receipt["analytics"]["status"] == "pass"
    assert receipt["analytics"]["route_count"] == 1
    assert receipt["blockers"] == []


def test_gold_status_blocks_when_public_sign_in_account_creation_smoke_is_missing(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    public_smoke = _write_json(tmp_path / "public-smoke.json", _public_smoke_payload(include_account_creation=False))
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        public_smoke_receipt_path=public_smoke,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "public_auth_surfaces")
    assert receipt["status"] == "blocked"
    assert receipt["public_auth_surfaces"]["sign_in_checks_ok"] is False
    assert "sign_in_provider_creates_account" in blocker["missing_sign_in_checks"]


def test_gold_status_blocks_when_brilliant_directories_billing_handoff_does_not_resolve(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    live_mobile = _write_json(tmp_path / "live-mobile.json", _live_mobile_payload())
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    billing = _write_json(tmp_path / "billing.json", _billing_payload(host_resolves=False, status="blocked"))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        billing_receipt_path=billing,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["billing_handoff"]["ready"] is False
    assert receipt["billing_handoff"]["host"] == "billing.propertyquarry.com"
    blocker = next(row for row in receipt["blockers"] if row["area"] == "billing_handoff")
    assert blocker["host_resolves"] is False
    assert "Brilliant Directories" in blocker["action"]


def test_gold_status_accepts_resolving_url_only_brilliant_directories_billing_handoff(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    live_mobile = _write_json(tmp_path / "live-mobile.json", _live_mobile_payload())
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    billing = _write_json(tmp_path / "billing.json", _billing_payload(host_resolves=True, status="disabled"))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        billing_receipt_path=billing,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "pass"
    assert receipt["billing_handoff"]["ready"] is True
    assert receipt["billing_handoff"]["host_resolves"] is True
    assert not any(row["area"] == "billing_handoff" for row in receipt["blockers"])


def test_gold_status_blocks_when_authenticated_billing_surface_exposes_local_board(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    authenticated_smoke = _write_json(
        tmp_path / "authenticated-smoke.json",
        _authenticated_smoke_payload(billing_external=False, billing_fail_closed=False, local_board_deleted=False),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    billing = _write_json(tmp_path / "billing.json", _billing_payload(host_resolves=True, status="disabled"))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        authenticated_smoke_receipt_path=authenticated_smoke,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        billing_receipt_path=billing,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "authenticated_customer_surfaces")
    assert receipt["status"] == "blocked"
    assert receipt["authenticated_customer_surfaces"]["billing_checks_ok"] is False
    assert "billing_external_handoff_or_fail_closed_recovery" in blocker["missing_billing_checks"]
    assert any(row["name"] == "billing_local_board_deleted" for row in blocker["failed_billing_checks"])


def test_gold_status_blocks_when_authenticated_notification_surface_loses_routing_form(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    authenticated_smoke = _write_json(
        tmp_path / "authenticated-smoke.json",
        _authenticated_smoke_payload(include_notification_checks=False),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    billing = _write_json(tmp_path / "billing.json", _billing_payload(host_resolves=True, status="disabled"))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        authenticated_smoke_receipt_path=authenticated_smoke,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        billing_receipt_path=billing,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "authenticated_customer_surfaces")
    assert receipt["status"] == "blocked"
    assert receipt["authenticated_customer_surfaces"]["notification_checks_ok"] is False
    assert "account_notification_telegram_channel" in blocker["missing_notification_checks"]
    assert "notification routing form" in blocker["action"]


def test_gold_status_blocks_when_receipts_are_stale_even_if_checks_pass(tmp_path: Path) -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    fresh_generated_at = (now - timedelta(minutes=10)).isoformat()
    stale_generated_at = (now - timedelta(hours=3)).isoformat()
    performance_payload = _performance_payload()
    performance_payload["generated_at"] = fresh_generated_at
    provider_matrix_payload = _provider_matrix_payload()
    provider_matrix_payload["generated_at"] = fresh_generated_at
    performance = _write_json(tmp_path / "performance.json", performance_payload)
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "generated_at": stale_generated_at,
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"generated_at": fresh_generated_at, "status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "generated_at": fresh_generated_at,
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", provider_matrix_payload)

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
        max_receipt_age_hours=1,
        now=now,
    )

    assert receipt["status"] == "blocked"
    assert receipt["receipt_freshness"]["status"] == "fail"
    blocker = next(row for row in receipt["blockers"] if row["area"] == "receipt_freshness")
    assert blocker["stale_receipts"] == [
        {
            "area": "tour_controls",
            "status": "stale",
            "generated_at": stale_generated_at,
            "timestamp_source": "generated_at",
            "raw_generated_at": stale_generated_at,
            "age_hours": 3.0,
            "max_age_hours": 1,
        }
    ]


def test_gold_status_accepts_repair_summary_timestamp_for_freshness(tmp_path: Path) -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    fresh_generated_at = (now - timedelta(minutes=10)).isoformat()
    performance_payload = _performance_payload()
    performance_payload["generated_at"] = fresh_generated_at
    provider_matrix_payload = _provider_matrix_payload()
    provider_matrix_payload["generated_at"] = fresh_generated_at
    performance = _write_json(tmp_path / "performance.json", performance_payload)
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "generated_at": fresh_generated_at,
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"generated_at": fresh_generated_at, "status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
            "repair_summary": {"generated_at": fresh_generated_at},
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", provider_matrix_payload)

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
        max_receipt_age_hours=1,
        now=now,
    )

    assert receipt["status"] == "pass"
    assert receipt["receipt_freshness"]["status"] == "pass"
    assert receipt["receipt_freshness"]["stale_receipts"] == []


def test_gold_status_blocks_when_repair_canary_is_missing_or_failed(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "failed",
            "run_status": "failed",
            "source_repair_status": "",
            "receipt_resolution": "",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert any(row["area"] == "self_healing_repair" for row in receipt["blockers"])


def test_gold_status_blocks_when_provider_matrix_is_not_executed(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(
        tmp_path / "provider-matrix.json",
        _provider_matrix_payload(status="blocked_targeted_search_matrix_not_executed", executed=False),
    )

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert any(row["area"] == "provider_targeted_search_matrix" for row in receipt["blockers"])


def test_gold_status_blocks_when_cross_country_provider_sanitization_is_missing(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_payload = _provider_matrix_payload()
    provider_payload["cross_country_sanitization_summary"] = {
        "case_count": 1,
        "status_counts": {"fail": 1},
        "sanitization_ok": False,
    }
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", provider_payload)

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    blocker = next(row for row in receipt["blockers"] if row["area"] == "provider_targeted_search_matrix")
    assert receipt["status"] == "blocked"
    assert receipt["provider_matrix"]["cross_country_sanitization_ok"] is False
    assert blocker["cross_country_sanitization_ok"] is False
    assert "wrong-country provider selections are sanitized" in blocker["action"]


def test_gold_status_blocks_when_live_mobile_surface_smoke_fails(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    live_mobile = _write_json(
        tmp_path / "live-mobile.json",
        {"status": "fail", "failed_count": 1, "route_count": 7, "viewport": {"width": 390, "height": 844}},
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_mobile_surfaces"]["status"] == "fail"
    assert any(row["area"] == "live_mobile_surfaces" for row in receipt["blockers"])


def test_gold_status_blocks_when_live_mobile_surface_coverage_is_old_or_narrow(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    live_mobile = _write_json(
        tmp_path / "live-mobile.json",
        _live_mobile_payload(
            routes=[
                "/app/search",
                "/app/shortlist",
                "/app/agents",
                "/app/alerts",
                "/app/account",
                "/app/billing",
                "/app/settings/google",
                "/app/research",
                "/app/properties/packets",
            ]
        ),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_mobile_surfaces"]["required_route_count"] == 14
    assert "/app/settings/access" in receipt["live_mobile_surfaces"]["missing_routes"]
    assert receipt["live_mobile_surfaces"]["missing_detail_routes"] == []
    blocker = next(row for row in receipt["blockers"] if row["area"] == "live_mobile_surfaces")
    assert "/app/settings/invitations" in blocker["missing_routes"]
    assert blocker["missing_detail_routes"] == []


def test_gold_status_blocks_when_live_mobile_research_surface_is_missing(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    routes_without_research = [
        route
        for route in _live_mobile_payload()["routes"]
        if not str(route["route"]).startswith("/app/research")
    ]
    live_mobile = _write_json(
        tmp_path / "live-mobile.json",
        {
            "status": "pass",
            "failed_count": 0,
            "route_count": 14,
            "viewport": {"width": 390, "height": 844},
            "routes": routes_without_research,
        },
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert "/app/research" in receipt["live_mobile_surfaces"]["missing_routes"]
    assert receipt["live_mobile_surfaces"]["missing_detail_routes"] == ["/app/research/"]


def test_gold_status_blocks_when_live_mobile_coverage_check_fails(tmp_path: Path) -> None:
    performance = _write_json(tmp_path / "performance.json", _performance_payload())
    live_mobile_payload = _live_mobile_payload()
    live_mobile_payload["status"] = "fail"
    live_mobile_payload["failed_count"] = 1
    live_mobile_payload["coverage_checks"] = [
        {
            "name": "research_detail_route_configured",
            "ok": False,
            "required_route_prefix": "/app/research/",
            "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
        }
    ]
    live_mobile = _write_json(tmp_path / "live-mobile.json", live_mobile_payload)
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        live_mobile_receipt_path=live_mobile,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["live_mobile_surfaces"]["failed_coverage_checks"] == [
        {
            "name": "research_detail_route_configured",
            "required_route_prefix": "/app/research/",
            "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
        }
    ]
    blocker = next(row for row in receipt["blockers"] if row["area"] == "live_mobile_surfaces")
    assert blocker["failed_coverage_checks"] == receipt["live_mobile_surfaces"]["failed_coverage_checks"]


def test_gold_status_resolves_container_incoming_readme_paths(monkeypatch, tmp_path: Path) -> None:
    incoming_root = tmp_path / "incoming"
    readme = incoming_root / "slug-a" / "3dvista" / "README.propertyquarry-export.txt"
    readme.parent.mkdir(parents=True)
    readme.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR", str(incoming_root))

    from scripts.propertyquarry_gold_status import _host_readme_path

    assert _host_readme_path("/data/incoming_property_tours/slug-a/3dvista/README.propertyquarry-export.txt") == readme


def test_gold_status_requires_operator_readmes_only_for_manifest_providers(tmp_path: Path) -> None:
    from scripts.propertyquarry_gold_status import _operator_drop_readme_status

    prepared: list[dict[str, str]] = []
    bodies = {
        "3dvista": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example:
Gold only passes when verify_property_tour_controls reports ready provider modes
Copy the complete 3DVista export folder
tdvplayer
import_3dvista_export.py
""",
        "pano2vr": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example:
Gold only passes when verify_property_tour_controls reports ready provider modes
Copy the complete Pano2VR output folder
tour.js
import_pano2vr_export.py
""",
        "krpano": """
PropertyQuarry provider export drop folder
Do not copy placeholder HTML.
Single-provider dry import example:
Gold only passes when verify_property_tour_controls reports ready provider modes
cube-face-1
KRPANO_LICENSE_DOMAIN=propertyquarry.com
import_krpano_walkable_scene.py
""",
    }
    for provider, body in bodies.items():
        readme = tmp_path / "incoming" / "slug" / provider / "README.propertyquarry-export.txt"
        readme.parent.mkdir(parents=True)
        readme.write_text(body, encoding="utf-8")
        prepared.append({"provider": provider, "readme": str(readme)})

    ok, count, missing, failures = _operator_drop_readme_status(
        {"providers": ["3dvista", "pano2vr", "krpano"], "prepared_drop_dirs": prepared},
        expected_providers={"3dvista", "pano2vr", "krpano"},
    )

    assert ok is True
    assert count == 3
    assert missing == []
    assert failures == []


def test_gold_status_blocks_when_performance_receipt_lacks_research_detail_checks(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(include_research_checks=False),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 2, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["performance"]["research_detail_checks_ok"] is False
    assert "research_confirmed_listing_facts" in receipt["performance"]["missing_research_detail_checks"]
    blocker = next(row for row in receipt["blockers"] if row["area"] == "mobile_and_authenticated_surfaces")
    assert "research_mobile_open_property_compact_layout" in blocker["missing_research_detail_checks"]


def test_gold_status_blocks_when_performance_receipt_lacks_analytics_privacy_checks(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(include_analytics_checks=False),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(tmp_path / "discovery.json", {"status": "ready", "import_count": 2, "rejected_count": 0})
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["analytics"]["status"] == "fail"
    assert receipt["analytics"]["route_count"] == 0
    blocker = next(row for row in receipt["blockers"] if row["area"] == "analytics_privacy")
    assert blocker["missing_checks"][0]["missing_checks"] == [
        "rybbit_no_identify",
        "rybbit_taxonomy_events_only",
        "rybbit_allowed_attributes_only",
        "rybbit_no_private_payload",
    ]


def test_gold_status_blocks_when_operator_drop_readmes_are_stale(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 0, "pano2vr": 0, "krpano": 0, "magicfit": 0},
            "ready_provider_modes": ["matterport"],
            "missing_provider_modes": ["3dvista", "pano2vr", "krpano", "magicfit"],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "blocked_no_verified_exports", "import_count": 0, "rejected_count": 0},
    )
    import_manifest = _write_json(tmp_path / "import-manifest.json", _import_manifest_payload(tmp_path, hardened_readmes=False))
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        import_manifest_receipt_path=import_manifest,
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["operator_import_manifest"]["ready_for_exports"] is False
    assert receipt["operator_import_manifest"]["hardened_readmes_ok"] is False
    assert sorted(receipt["operator_import_manifest"]["missing_hardened_readme_providers"]) == ["3dvista", "krpano", "magicfit", "pano2vr"]
    blocker = next(row for row in receipt["blockers"] if row["area"] == "tour_operator_drop_readmes")
    assert blocker["status"] == "stale_or_missing"
    assert blocker["failures"][0]["status"] == "stale_readme"


def test_gold_status_blocks_when_operator_import_manifest_is_missing(tmp_path: Path) -> None:
    performance = _write_json(
        tmp_path / "performance.json",
        _performance_payload(),
    )
    tour_controls = _write_json(
        tmp_path / "tour-controls.json",
        {
            "status": "pass",
            "provider_counts": {"matterport": 1, "3dvista": 1, "pano2vr": 1, "krpano": 1, "magicfit": 1},
            "ready_provider_modes": ["matterport", "3dvista", "pano2vr", "krpano", "magicfit"],
            "missing_provider_modes": [],
        },
    )
    discovery = _write_json(
        tmp_path / "discovery.json",
        {"status": "ready", "import_count": 4, "rejected_count": 0},
    )
    repair_canary = _write_json(
        tmp_path / "repair.json",
        {
            "status": "pass",
            "run_status": "completed_partial",
            "source_repair_status": "returned",
            "receipt_resolution": "provider_quarantined_retry_budget_exhausted",
        },
    )
    provider_matrix = _write_json(tmp_path / "provider-matrix.json", _provider_matrix_payload())

    receipt = build_gold_status_receipt(
        performance_receipt_path=performance,
        tour_control_receipt_path=tour_controls,
        export_discovery_receipt_path=discovery,
        import_manifest_receipt_path=tmp_path / "missing-import-manifest.json",
        repair_canary_receipt_path=repair_canary,
        provider_matrix_receipt_path=provider_matrix,
    )

    assert receipt["status"] == "blocked"
    assert receipt["operator_import_manifest"]["ready_for_exports"] is False
    blocker = next(row for row in receipt["blockers"] if row["area"] == "tour_operator_import_manifest")
    assert blocker["status"] == "missing"
