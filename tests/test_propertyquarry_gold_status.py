from __future__ import annotations

import json
from pathlib import Path

from scripts.propertyquarry_gold_status import build_gold_status_receipt


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
    }


def _performance_payload(*, include_research_checks: bool = True) -> dict[str, object]:
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
        "/app/properties/packets",
    ]
    return {
        "status": status,
        "failed_count": failed_count,
        "route_count": len(route_list),
        "viewport": {"width": 390, "height": 844},
        "routes": [{"route": route, "ok": True, "checks": []} for route in route_list],
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
        "status": "ready_for_exports",
        "import_count": len(providers),
        "providers": providers,
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
        {"status": "blocked_no_verified_exports", "import_count": 0, "rejected_count": 0},
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
    assert receipt["operator_import_manifest"]["missing_prepared_providers"] == []
    assert receipt["operator_import_manifest"]["hardened_readmes_ok"] is True
    assert receipt["operator_import_manifest"]["hardened_readme_provider_count"] == 4
    assert "gold still requires real imported assets" in receipt["operator_import_manifest"]["note"]
    assert any(row["area"] == "verified_tour_provider_modes" for row in receipt["blockers"])
    assert any(row["area"] == "tour_export_drop" for row in receipt["blockers"])


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
    assert receipt["blockers"] == []


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
    blocker = next(row for row in receipt["blockers"] if row["area"] == "live_mobile_surfaces")
    assert "/app/settings/invitations" in blocker["missing_routes"]


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
