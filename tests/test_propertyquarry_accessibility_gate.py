from __future__ import annotations

from pathlib import Path

import pytest

from scripts import propertyquarry_accessibility_gate as gate
from scripts import propertyquarry_gold_status as gold_status


ROOT = Path(__file__).resolve().parents[1]
_MISSING = object()


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
        "axe_moderate_or_higher_wcag_count": 0,
        "focused": True,
        "visible_focus": True,
        "focus_unobscured": True,
        "target_size_minimum_css_px": 24,
        "target_count": 8,
        "undersized_target_count": 0,
        "dialog_applicable": dialog_applicable,
        "dialog_focus_contained": True,
        "dialog_escape_closes": True,
        "dialog_focus_restored": True,
        "error_semantics_valid": True,
        "live_progress_semantics_valid": True,
        "zoom_percent": 200,
        "reflow_without_horizontal_scroll": True,
        "zoom_400_percent": 400,
        "zoom_400_viewport_width": 320,
        "zoom_400_scroll_width": 320,
        "zoom_400_reflow_without_horizontal_scroll": True,
        "zoom_400_clipped_interactive_count": 0,
        "contrast_violation_count": 0,
        "contrast_incomplete_count": 0,
        "reduced_motion_media_matches": True,
        "active_motion_count": 0,
    }


def _flagship_routes() -> tuple[str, ...]:
    return (
        *gate.DEFAULT_ACCESSIBILITY_ROUTES,
        "/app/research/current-result?run_id=run-a11y",
        "/app/shortlist/run/run-a11y",
        "/tours/tour-a11y",
    )


def test_accessibility_gate_builds_engine_route_receipt_from_pinned_local_axe(tmp_path: Path) -> None:
    routes = _flagship_routes()

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
    assert receipt["observed_browser_engines"] == ["chromium", "firefox", "webkit"]
    checks = {row["name"]: row for row in receipt["checks"]}
    assert checks["flagship_static_route_matrix_configured"]["ok"] is True
    assert checks["literal_route_placeholders_absent"]["ok"] is True
    assert checks["research_detail_route_configured"]["matched_routes"] == [
        "/app/research/current-result?run_id=run-a11y"
    ]
    assert checks["shortlist_run_route_configured"]["matched_routes"] == [
        "/app/shortlist/run/run-a11y"
    ]
    assert checks["public_tour_route_configured"]["matched_routes"] == [
        "/tours/tour-a11y"
    ]
    assert receipt["manual_assistive_technology_evidence"] == {
        "status": "external_evidence_required",
        "required_for_launch": True,
        "satisfied_by_this_receipt": False,
    }


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


def test_accessibility_defaults_exactly_match_gold_static_route_inventory() -> None:
    assert gate.DEFAULT_ACCESSIBILITY_ROUTES == gold_status.REQUIRED_FLAGSHIP_ACCESSIBILITY_ROUTES
    assert {
        "/app/billing",
        "/app/properties/notifications/preview",
        "/app/settings/outcomes",
        "/app/settings/plan",
        "/app/support",
    }.issubset(gate.DEFAULT_ACCESSIBILITY_ROUTES)


def test_accessibility_gate_rejects_empty_browser_engine_configuration() -> None:
    with pytest.raises(ValueError, match="accessibility_browser_engines_required"):
        gate.normalize_browser_engines(())


@pytest.mark.parametrize(
    ("requested_path", "final_path", "expected_contract"),
    (
        ("/app/search", "/app/search", "exact_path"),
        (
            "/app/support",
            "/app/settings/support",
            "canonical_app_support_redirect",
        ),
        (
            "/app/billing",
            "/app/account?billing=1#delivery",
            "canonical_billing_handoff_redirect",
        ),
        (
            "/tours/tour-a11y",
            "/tours/tour-a11y/control/3dvista",
            "canonical_public_tour_control_redirect",
        ),
    ),
)
def test_accessibility_navigation_contract_allows_only_named_canonical_redirects(
    requested_path: str,
    final_path: str,
    expected_contract: str,
) -> None:
    ok, contract = gate._navigation_contract(
        requested_url=f"https://propertyquarry.com{requested_path}",
        final_url=f"https://propertyquarry.com{final_path}",
        status_code=200,
    )

    assert ok is True
    assert contract == expected_contract


@pytest.mark.parametrize(
    ("final_url", "status_code", "expected_contract"),
    (
        ("https://billing.example.test/account", 200, "cross_origin_redirect"),
        ("https://propertyquarry.com/app/account?billing=1", 200, "unexpected_final_path"),
        ("https://propertyquarry.com/app/settings/support", 500, "non_success_status"),
        ("https://propertyquarry.com/tours/another/control/3dvista", 200, "unexpected_final_path"),
    ),
)
def test_accessibility_navigation_contract_rejects_unnamed_redirects(
    final_url: str,
    status_code: int,
    expected_contract: str,
) -> None:
    ok, contract = gate._navigation_contract(
        requested_url="https://propertyquarry.com/app/billing",
        final_url=final_url,
        status_code=status_code,
    )

    assert ok is False
    assert contract == expected_contract


def test_accessibility_gate_rejects_literal_dynamic_route_placeholders(tmp_path: Path) -> None:
    routes = (
        *gate.DEFAULT_ACCESSIBILITY_ROUTES,
        "/app/research/{candidate_id}?run_id={run_id}",
        "/app/shortlist/run/{run_id}",
        "/tours/{slug}",
    )

    def fake_collect(**kwargs):
        engine = kwargs["browser_engine"]
        return [
            {
                "route": route,
                "browser_engine": engine,
                "ok": True,
                "checks": gate.evaluate_accessibility_metrics(
                    _passing_metrics(
                        engine=engine,
                        dialog_applicable=route == "/app/search",
                    )
                ),
                "metrics": _passing_metrics(
                    engine=engine,
                    dialog_applicable=route == "/app/search",
                ),
            }
            for route in kwargs["routes"]
        ]

    receipt = gate.build_accessibility_receipt(
        base_url="http://127.0.0.1:8097",
        routes=routes,
        browser_engines=("chromium",),
        axe_core_path=_axe_input(tmp_path),
        collect_engine_rows=fake_collect,
    )

    checks = {row["name"]: row for row in receipt["checks"]}
    assert receipt["status"] == "fail"
    assert checks["literal_route_placeholders_absent"] == {
        "name": "literal_route_placeholders_absent",
        "ok": False,
        "placeholder_routes": [
            "/app/research/{candidate_id}?run_id={run_id}",
            "/app/shortlist/run/{run_id}",
            "/tours/{slug}",
        ],
    }
    for name in (
        "research_detail_route_configured",
        "shortlist_run_route_configured",
        "public_tour_route_configured",
    ):
        assert checks[name]["ok"] is False
        assert checks[name]["matched_routes"] == []


@pytest.mark.parametrize(
    ("missing_prefix", "check_name"),
    (
        ("/app/research/", "research_detail_route_configured"),
        ("/app/shortlist/run/", "shortlist_run_route_configured"),
        ("/tours/", "public_tour_route_configured"),
    ),
)
def test_accessibility_gate_requires_each_concrete_dynamic_route_family(
    tmp_path: Path,
    missing_prefix: str,
    check_name: str,
) -> None:
    routes = tuple(
        route
        for route in _flagship_routes()
        if not str(route).split("?", 1)[0].startswith(missing_prefix)
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
        browser_engines=("chromium",),
        axe_core_path=_axe_input(tmp_path),
        collect_engine_rows=fake_collect,
    )

    check = next(row for row in receipt["checks"] if row["name"] == check_name)
    assert receipt["status"] == "fail"
    assert check["ok"] is False
    assert check["matched_routes"] == []


@pytest.mark.parametrize(
    "field",
    (
        "axe_moderate_or_higher_wcag_count",
        "focus_unobscured",
        "target_size_minimum_css_px",
        "undersized_target_count",
    ),
)
def test_accessibility_metrics_fail_closed_when_new_wcag_metrics_are_missing(field: str) -> None:
    metrics = _passing_metrics(engine="chromium", dialog_applicable=True)
    metrics.pop(field)

    failed = {
        check["name"]
        for check in gate.evaluate_accessibility_metrics(metrics)
        if check["ok"] is not True
    }

    expected = {
        "axe_moderate_or_higher_wcag_count": "axe_no_moderate_or_higher_wcag_violations",
        "focus_unobscured": "focus_not_obscured",
        "target_size_minimum_css_px": "target_size_24_css_px_or_spacing",
        "undersized_target_count": "target_size_24_css_px_or_spacing",
    }
    assert expected[field] in failed


def test_axe_threshold_includes_only_wcag_tagged_moderate_or_higher_rows() -> None:
    rows = [
        {"id": "minor-wcag", "impact": "minor", "tags": ["wcag2aa"]},
        {"id": "moderate-best-practice", "impact": "moderate", "tags": ["best-practice"]},
        {"id": "moderate-wcag", "impact": "moderate", "tags": ["wcag22aa"]},
        {"id": "serious-wcag", "impact": "serious", "tags": ["wcag2a"]},
        {"id": "critical-wcag", "impact": "critical", "tags": ["wcag21aa"]},
    ]

    assert [
        row["id"]
        for row in gate._axe_moderate_or_higher_wcag_violations(rows)
    ] == ["moderate-wcag", "serious-wcag", "critical-wcag"]


def test_accessibility_metrics_fail_moderate_axe_target_focus_contrast_reflow_and_motion() -> None:
    metrics = _passing_metrics(engine="chromium", dialog_applicable=True)
    metrics.update(
        {
            "axe_serious_critical_count": 2,
            "axe_moderate_or_higher_wcag_count": 2,
            "focus_unobscured": False,
            "undersized_target_count": 1,
            "contrast_violation_count": 1,
            "reflow_without_horizontal_scroll": False,
            "zoom_400_reflow_without_horizontal_scroll": False,
            "zoom_400_clipped_interactive_count": 1,
            "active_motion_count": 1,
        }
    )
    failed = {
        check["name"]
        for check in gate.evaluate_accessibility_metrics(metrics)
        if check["ok"] is not True
    }

    assert failed == {
        "axe_no_moderate_or_higher_wcag_violations",
        "focus_not_obscured",
        "target_size_24_css_px_or_spacing",
        "zoom_200_reflow",
        "zoom_400_reflow",
        "contrast_signals_clear",
        "reduced_motion_honored",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("zoom_400_viewport_width", _MISSING),
        ("zoom_400_viewport_width", 319),
        ("zoom_400_scroll_width", _MISSING),
        ("zoom_400_scroll_width", 0),
        ("zoom_400_scroll_width", 323),
    ),
)
def test_accessibility_400_percent_reflow_requires_observed_320px_geometry(
    field: str,
    value: object,
) -> None:
    metrics = _passing_metrics(engine="chromium", dialog_applicable=True)
    if value is _MISSING:
        metrics.pop(field)
    else:
        metrics[field] = value

    failed = {
        check["name"]
        for check in gate.evaluate_accessibility_metrics(metrics)
        if check["ok"] is not True
    }

    assert "zoom_400_reflow" in failed


def test_accessibility_gate_is_wired_to_narrow_ci_and_protected_release() -> None:
    workflow = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(encoding="utf-8")
    release_gate = (ROOT / "scripts/propertyquarry_live_release_gates.sh").read_text(encoding="utf-8")

    assert "propertyquarry-accessibility-contracts:" in workflow
    assert "tests/test_propertyquarry_accessibility_gate.py" in workflow
    assert f"axe-core@{gate.AXE_CORE_VERSION}" in workflow
    accessibility_job = workflow.split(
        "  propertyquarry-accessibility-contracts:\n", 1
    )[1].split("\n  propertyquarry-failure-state-contracts:\n", 1)[0]
    assert "python -m playwright install --with-deps chromium firefox webkit" in accessibility_job
    assert "scripts/propertyquarry_accessibility_gate.py" in accessibility_job
    assert '--browser-engines "${PROPERTYQUARRY_ACCESSIBILITY_BROWSER_ENGINES}"' in accessibility_job
    assert "PROPERTYQUARRY_ACCESSIBILITY_BROWSER_ENGINES: chromium,firefox,webkit" in accessibility_job
    assert "Preserve governed accessibility evidence" in accessibility_job
    assert "scripts/propertyquarry_accessibility_gate.py" in release_gate
    assert "PROPERTYQUARRY_ACCESSIBILITY_RESEARCH_DETAIL_ROUTE" in release_gate
    assert "PROPERTYQUARRY_ACCESSIBILITY_SHORTLIST_RUN_ROUTE" in release_gate
    assert "PROPERTYQUARRY_ACCESSIBILITY_PUBLIC_TOUR_ROUTE" in release_gate
    assert 'expected_probe_shortlist_run_route="/app/shortlist/run/run-gold-mobile"' in release_gate
