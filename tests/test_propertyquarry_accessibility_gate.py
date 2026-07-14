from __future__ import annotations

from pathlib import Path

from scripts import propertyquarry_accessibility_gate as gate


ROOT = Path(__file__).resolve().parents[1]


def _axe_input(tmp_path: Path) -> Path:
    path = tmp_path / "axe.min.js"
    path.write_text("/* pinned axe input */\n" + "window.axe = {};\n" * 20, encoding="utf-8")
    return path


def _passing_metrics(*, engine: str, dialog_applicable: bool) -> dict[str, object]:
    return {
        "browser_engine": engine,
        "route_document_loaded": True,
        "axe_core_version": gate.AXE_CORE_VERSION,
        "axe_serious_critical_count": 0,
        "focused": True,
        "visible_focus": True,
        "dialog_applicable": dialog_applicable,
        "dialog_focus_contained": True,
        "dialog_escape_closes": True,
        "dialog_focus_restored": True,
        "error_semantics_valid": True,
        "live_progress_semantics_valid": True,
        "zoom_percent": 200,
        "reflow_without_horizontal_scroll": True,
        "contrast_violation_count": 0,
        "contrast_incomplete_count": 0,
        "reduced_motion_media_matches": True,
        "active_motion_count": 0,
    }


def test_accessibility_gate_builds_engine_route_receipt_from_pinned_local_axe(tmp_path: Path) -> None:
    routes = (
        *gate.PUBLIC_INFORMATION_ROUTES,
        "/app/search",
        "/app/research/candidate?run_id=run-a11y",
    )

    def fake_collect(**kwargs):
        engine = kwargs["browser_engine"]
        return [
            {
                "route": route,
                "browser_engine": engine,
                "ok": True,
                "checks": gate.evaluate_accessibility_metrics(
                    _passing_metrics(engine=engine, dialog_applicable=route == "/app/search")
                ),
                "metrics": _passing_metrics(engine=engine, dialog_applicable=route == "/app/search"),
            }
            for route in kwargs["routes"]
        ]

    receipt = gate.build_accessibility_receipt(
        base_url="http://127.0.0.1:8097",
        routes=routes,
        browser_engines=("chromium", "firefox", "webkit"),
        axe_core_path=_axe_input(tmp_path),
        collect_engine_rows=fake_collect,
    )

    assert receipt["status"] == "pass"
    assert receipt["required_browser_engines"] == ["chromium", "firefox", "webkit"]
    assert receipt["expected_sample_count"] == len(routes) * 3
    assert receipt["observed_sample_count"] == len(routes) * 3
    assert receipt["dialog_interaction_sample_count"] == 3
    assert all(row["ok"] is True for row in receipt["routes"])


def test_accessibility_gate_blocks_clearly_when_pinned_axe_is_unavailable(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-axe.min.js"
    receipt = gate.build_accessibility_receipt(
        base_url="http://127.0.0.1:8097",
        routes=("/sign-in",),
        axe_core_path=missing_path,
    )

    assert receipt["status"] == "blocked"
    assert receipt["routes"] == []
    assert receipt["checks"][0]["name"] == "axe_core_pinned_input"
    assert f"axe-core {gate.AXE_CORE_VERSION}" in receipt["checks"][0]["reason"]
    assert str(missing_path.resolve()) in receipt["checks"][0]["reason"]


def test_accessibility_gate_fails_named_engine_without_fallback(tmp_path: Path) -> None:
    def fake_collect(**kwargs):
        if kwargs["browser_engine"] == "webkit":
            raise RuntimeError("playwright_browser_engine_unavailable:webkit")
        return []

    receipt = gate.build_accessibility_receipt(
        base_url="http://127.0.0.1:8097",
        routes=("/app/research/candidate",),
        browser_engines=("webkit",),
        axe_core_path=_axe_input(tmp_path),
        collect_engine_rows=fake_collect,
    )

    assert receipt["status"] == "fail"
    assert receipt["engine_failures"] == [
        {
            "browser_engine": "webkit",
            "error": "RuntimeError: playwright_browser_engine_unavailable:webkit",
        }
    ]
    assert receipt["checks"][1]["ok"] is False


def test_accessibility_gate_fails_when_public_information_matrix_is_narrowed(tmp_path: Path) -> None:
    routes = ("/sign-in", "/app/search", "/app/research/candidate")

    def fake_collect(**kwargs):
        engine = kwargs["browser_engine"]
        return [
            {
                "route": route,
                "browser_engine": engine,
                "ok": True,
                "checks": gate.evaluate_accessibility_metrics(
                    _passing_metrics(engine=engine, dialog_applicable=route == "/app/search")
                ),
                "metrics": _passing_metrics(engine=engine, dialog_applicable=route == "/app/search"),
            }
            for route in routes
        ]

    receipt = gate.build_accessibility_receipt(
        base_url="http://127.0.0.1:8097",
        routes=routes,
        browser_engines=("chromium",),
        axe_core_path=_axe_input(tmp_path),
        collect_engine_rows=fake_collect,
    )

    coverage = next(check for check in receipt["checks"] if check["name"] == "public_information_route_matrix_configured")
    assert receipt["status"] == "fail"
    assert coverage["ok"] is False
    assert "/support" in coverage["missing_routes"]


def test_accessibility_metrics_fail_serious_axe_contrast_reflow_and_motion() -> None:
    metrics = _passing_metrics(engine="chromium", dialog_applicable=True)
    metrics.update(
        {
            "axe_serious_critical_count": 2,
            "contrast_violation_count": 1,
            "reflow_without_horizontal_scroll": False,
            "active_motion_count": 1,
        }
    )
    failed = {
        check["name"]
        for check in gate.evaluate_accessibility_metrics(metrics)
        if check["ok"] is not True
    }

    assert failed == {
        "axe_no_serious_or_critical_violations",
        "zoom_200_reflow",
        "contrast_signals_clear",
        "reduced_motion_honored",
    }


def test_accessibility_gate_is_wired_to_narrow_ci_and_protected_release() -> None:
    workflow = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(encoding="utf-8")
    release_gate = (ROOT / "scripts/propertyquarry_live_release_gates.sh").read_text(encoding="utf-8")

    assert "propertyquarry-accessibility-contracts:" in workflow
    assert "tests/test_propertyquarry_accessibility_gate.py" in workflow
    assert f"axe-core@{gate.AXE_CORE_VERSION}" in workflow
    assert "scripts/propertyquarry_accessibility_gate.py" in release_gate
    assert "PROPERTYQUARRY_ACCESSIBILITY_RESEARCH_DETAIL_ROUTE" in release_gate
