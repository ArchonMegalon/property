from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path

import pytest

from scripts import propertyquarry_continuous_ux_gate as gate


ROOT = Path(__file__).resolve().parents[1]
_MISSING = object()


def _passing_row(*, engine: str, route: str) -> dict[str, object]:
    first_value_samples = (
        [210.0, 220.0, 230.0]
        if engine == gate.FIRST_VALUE_ENGINE
        else [220.0]
    )
    metrics: dict[str, object] = {
        "document_ready_state": "complete",
        "final_route": route,
        "main_visible": route != gate.ERROR_ROUTE,
        "navigation_visible": True,
        "body_text_length": 120,
        "visible_interactive_count": 4,
        "horizontal_overflow": False,
        "visible_image_count": 0,
        "terminal_visible_image_count": 0,
        "broken_visible_image_count": 0,
        "zoom_400_percent": 400,
        "zoom_400_viewport_width": 320,
        "zoom_400_scroll_width": 320,
        "zoom_400_reflow_without_horizontal_scroll": True,
        "zoom_400_clipped_interactive_count": 0,
        "first_value_ms": 220.0,
        "first_value_cold_ms": 260.0,
        "first_value_initial_samples_ms": first_value_samples,
        "first_value_samples_ms": first_value_samples,
        "first_value_sample_count": len(first_value_samples),
        "first_value_retry_used": False,
        "first_value_gated": engine == gate.FIRST_VALUE_ENGINE,
        "first_value_basis": gate.FIRST_VALUE_BASIS,
        "provider_response_mocked": False,
        "request_interception_mode": "origin_scoped_headers_continue_only",
        "route_fulfill_count": 0,
    }
    if route == gate.SEARCH_ROUTE:
        metrics.update(
            {
                "loading_action_available": True,
                "loading_state_visible": True,
                "loading_state_semantic": True,
            }
        )
    if route == gate.ERROR_ROUTE:
        metrics.update(
            {
                "error_state_visible": True,
                "error_state_semantic": True,
                "error_state_recovered_online": True,
            }
        )
    row: dict[str, object] = {
        "route": route,
        "browser_engine": engine,
        "status_code": gate.ERROR_EXPECTED_STATUS if route == gate.ERROR_ROUTE else 200,
        "metrics": metrics,
        "error": "",
    }
    checks = gate.evaluate_continuous_ux_row(row)
    row["checks"] = checks
    row["ok"] = all(check["ok"] is True for check in checks)
    return row


def test_continuous_ux_gate_rejects_non_loopback_or_non_memory_before_browser() -> None:
    called = False

    def fake_collect(**_kwargs):
        nonlocal called
        called = True
        return []

    receipt = gate.build_continuous_ux_receipt(
        base_url="https://propertyquarry.com",
        release_commit_sha="a" * 40,
        api_token="ephemeral-token",
        storage_backend="postgres",
        collect_engine_rows=fake_collect,
    )

    assert receipt["status"] == "blocked"
    assert called is False
    assert receipt["production_claim"] is False
    assert receipt["deployed_or_live_proof"] is False
    assert receipt["base_origin_kind"] == "invalid"
    assert receipt["proof_mode"] == gate.MOCK_PROOF_MODE
    assert "ephemeral-token" not in str(receipt)


def test_continuous_ux_gate_contract_collector_cannot_claim_real_browser_pass() -> None:
    def fake_collect(**kwargs):
        return [
            _passing_row(engine=kwargs["browser_engine"], route=route)
            for route in kwargs["routes"]
        ]

    receipt = gate.build_continuous_ux_receipt(
        base_url="http://127.0.0.1:8097",
        release_commit_sha="a" * 40,
        api_token="ephemeral-token",
        storage_backend="memory",
        browser_engines=("chromium", "firefox", "webkit"),
        collect_engine_rows=fake_collect,
    )

    assert receipt["status"] == "fail"
    assert receipt["proof_mode"] == gate.MOCK_PROOF_MODE
    real_check = next(
        check
        for check in receipt["checks"]
        if check["name"] == "real_playwright_browser_evidence"
    )
    assert real_check["ok"] is False
    assert receipt["expected_sample_count"] == len(gate.DEFAULT_ROUTES) * 3
    assert receipt["observed_sample_count"] == len(gate.DEFAULT_ROUTES) * 3
    assert receipt["provider_response_mocking"] is False
    assert receipt["screenshot_pixel_comparison"] is False


def test_continuous_ux_row_fails_closed_on_visual_zoom_state_or_budget_regression() -> None:
    search = _passing_row(engine="chromium", route=gate.SEARCH_ROUTE)
    metrics = dict(search["metrics"])
    metrics.update(
        {
            "broken_visible_image_count": 1,
            "zoom_400_clipped_interactive_count": 1,
            "first_value_ms": gate.FIRST_VALUE_BUDGET_MS + 1.0,
            "first_value_basis": "untrusted_stopwatch",
            "loading_state_semantic": False,
            "provider_response_mocked": True,
        }
    )
    search["metrics"] = metrics

    failed = {
        check["name"]
        for check in gate.evaluate_continuous_ux_row(search)
        if check["ok"] is not True
    }

    assert failed == {
        "structural_visual_contract",
        "zoom_400_reflow",
        "first_value_under_budget",
        "loading_state_semantic",
        "provider_response_not_mocked",
    }


def test_visible_image_wait_stabilizes_declared_sources_before_decode() -> None:
    class FakePage:
        script = ""
        argument: dict[str, int] = {}

        def evaluate(self, script: str, argument: dict[str, int]) -> None:
            self.script = script
            self.argument = argument

    page = FakePage()
    gate._wait_for_visible_image_terminal_state(page, timeout_ms=30_000)

    assert page.argument == {
        "timeoutMs": 10_000,
        "stabilityMs": gate.VISIBLE_IMAGE_STABILITY_MS,
    }
    assert "image.currentSrc" in page.script
    assert "image.getAttribute('src')" in page.script
    assert "image.getAttribute('srcset')" in page.script
    assert "requestAnimationFrame" in page.script
    assert "Promise.allSettled" in page.script
    assert "image.naturalWidth" not in page.script
    assert "visible_image_terminal_state_timeout" in page.script


def test_visible_image_wait_handles_hydration_breakage_and_frame_timeout() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 120, 80)).save(buffer, format="PNG")
    valid_source = "data:image/png;base64," + base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")
    with playwright_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        except Exception as exc:  # pragma: no cover - developer machines may omit browsers
            pytest.skip(f"chromium unavailable for continuous UX contract: {type(exc).__name__}")
        try:
            page = browser.new_page()
            page.set_content("<main>hydrating</main><nav aria-label='Primary'>nav</nav>")
            page.evaluate(
                """
                ([source]) => setTimeout(() => {
                  const image = document.createElement('img');
                  image.alt = 'delayed';
                  image.style.cssText = 'width:20px;height:20px';
                  image.src = source;
                  document.body.appendChild(image);
                }, 75)
                """,
                [valid_source],
            )
            gate._wait_for_visible_image_terminal_state(page, timeout_ms=2_000)
            delayed = gate._structural_visual_metrics(page)
            assert delayed["visible_image_count"] == 1
            assert delayed["terminal_visible_image_count"] == 1
            assert delayed["broken_visible_image_count"] == 0

            page.set_content(
                "<main>broken</main><nav aria-label='Primary'>nav</nav>"
                "<img alt='broken' style='width:20px;height:20px' "
                "src='data:image/png;base64,broken'>"
            )
            gate._wait_for_visible_image_terminal_state(page, timeout_ms=2_000)
            broken = gate._structural_visual_metrics(page)
            assert broken["visible_image_count"] == 1
            assert broken["terminal_visible_image_count"] == 1
            assert broken["broken_visible_image_count"] == 1

            page.set_content(
                "<main>missing</main><nav aria-label='Primary'>nav</nav>"
                "<img alt='missing' style='width:20px;height:20px' src=''>"
            )
            with pytest.raises(Exception, match="visible_image_terminal_state_timeout"):
                gate._wait_for_visible_image_terminal_state(page, timeout_ms=1_000)

            page.set_content("<main>no frames</main><nav aria-label='Primary'>nav</nav>")
            page.evaluate("window.requestAnimationFrame = () => 0")
            started = time.monotonic()
            with pytest.raises(Exception, match="visible_image_terminal_state_timeout"):
                gate._wait_for_visible_image_terminal_state(page, timeout_ms=1_000)
            assert time.monotonic() - started < 2.5
        finally:
            browser.close()


@pytest.mark.parametrize(
    ("route", "target", "field", "value"),
    (
        (gate.SEARCH_ROUTE, "metrics", "loading_action_available", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "loading_state_visible", False),
        (gate.SEARCH_ROUTE, "metrics", "loading_state_semantic", _MISSING),
        (gate.ERROR_ROUTE, "metrics", "error_state_visible", _MISSING),
        (gate.ERROR_ROUTE, "metrics", "error_state_semantic", False),
        (gate.ERROR_ROUTE, "metrics", "error_state_recovered_online", _MISSING),
        (gate.SEARCH_ROUTE, "row", "status_code", _MISSING),
        (gate.SEARCH_ROUTE, "row", "status_code", 503),
        (gate.SEARCH_ROUTE, "metrics", "document_ready_state", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "document_ready_state", "loading"),
        (gate.SEARCH_ROUTE, "row", "error", _MISSING),
        (gate.SEARCH_ROUTE, "row", "error", "playwright_timeout"),
        (gate.SEARCH_ROUTE, "metrics", "first_value_retry_used", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "first_value_retry_used", True),
        (gate.SEARCH_ROUTE, "metrics", "first_value_cold_ms", -1.0),
        (gate.SEARCH_ROUTE, "metrics", "first_value_cold_ms", float("inf")),
        (gate.SEARCH_ROUTE, "metrics", "first_value_initial_samples_ms", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "first_value_initial_samples_ms", [210.0, 220.0]),
        (gate.SEARCH_ROUTE, "metrics", "zoom_400_viewport_width", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "zoom_400_viewport_width", 321),
        (gate.SEARCH_ROUTE, "metrics", "zoom_400_scroll_width", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "horizontal_overflow", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "horizontal_overflow", True),
        (gate.SEARCH_ROUTE, "metrics", "provider_response_mocked", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "provider_response_mocked", True),
        (gate.SEARCH_ROUTE, "metrics", "request_interception_mode", _MISSING),
        (gate.SEARCH_ROUTE, "metrics", "route_fulfill_count", _MISSING),
    ),
)
def test_continuous_ux_row_rejects_missing_or_tampered_raw_evidence(
    route: str,
    target: str,
    field: str,
    value: object,
) -> None:
    row = _passing_row(engine=gate.FIRST_VALUE_ENGINE, route=route)
    evidence = row if target == "row" else row["metrics"]
    assert isinstance(evidence, dict)
    if value is _MISSING:
        evidence.pop(field)
    else:
        evidence[field] = value

    assert any(
        check["ok"] is not True
        for check in gate.evaluate_continuous_ux_row(row)
    )


def test_continuous_ux_gate_is_additive_push_pr_ci_without_production_environment() -> None:
    workflow = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(
        encoding="utf-8"
    )

    assert "propertyquarry-continuous-ux:" in workflow
    job = workflow.split("propertyquarry-continuous-ux:", 1)[1].split(
        "\n  propertyquarry-", 1
    )[0]
    assert "EA_STORAGE_BACKEND: memory" in job
    assert "python scripts/propertyquarry_continuous_ux_gate.py" in job
    assert "release_manifest_runtime_sha" in job
    assert "PROPERTYQUARRY_RELEASE_COMMIT_SHA=${runtime_sha}" in job
    assert "PROPERTYQUARRY_RELEASE_COMMIT_SHA: ${{ github.sha }}" not in job
    assert "propertyquarry-continuous-ux-${{ github.sha }}" in job
    assert "if-no-files-found: error" in job
    assert "environment:" not in job
    assert "secrets." not in job
    assert "propertyquarry-live-release-gates:" in workflow
    live_job = workflow.split("propertyquarry-live-release-gates:", 1)[1].split(
        "\n  propertyquarry-", 1
    )[0]
    live_needs = live_job.split("runs-on:", 1)[0]
    assert "propertyquarry-flagship-security" in live_needs
    assert "propertyquarry-continuous-ux" in live_needs
    assert "uses: actions/download-artifact@" in live_job
    assert "name: propertyquarry-continuous-ux-${{ github.sha }}" in live_job
    assert (
        "PROPERTYQUARRY_CONTINUOUS_UX_RECEIPT: "
        "_completion/smoke/propertyquarry-continuous-ux-${{ github.sha }}.json"
    ) in live_job
    assert "_flagship_continuous_ux_proof" in live_job
    assert (
        'echo "PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA=${runtime_sha}" '
        '>> "${GITHUB_ENV}"'
    ) in live_job
    assert "PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA: ${{ github.sha }}" not in live_job
