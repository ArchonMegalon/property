from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app
from app.product.models import HandoffNote
from app.product.service import ProductService


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/sign-in", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


@pytest.fixture()
def propertyquarry_browser_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    from tests.product_test_helpers import build_product_client, start_workspace

    client = build_product_client(principal_id="pq-greenfield-browser")
    start_workspace(client, mode="personal", workspace_name="Property Office")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret")
    monkeypatch.setenv("FLIPLINK_WEBHOOK_SECRET", "webhook-secret")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "apartment",
            "location_query": "Berlin",
            "keywords": "lift family balcony",
            "selected_platforms": ["immoscout_de", "immowelt"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 4,
        },
    )
    assert stored.status_code == 200, stored.text

    run_status_calls: dict[str, int] = {}

    def _fake_empty_run_status(*, run_id: str, principal_id: str, processed: bool) -> dict[str, object]:
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed" if processed else "in_progress",
            "generated_at": "2026-06-05T07:00:00+00:00",
            "updated_at": "2026-06-05T07:01:00+00:00" if processed else "2026-06-05T07:00:15+00:00",
            "progress": 100 if processed else 12,
            "message": "No strong matches met the selected threshold." if processed else "Scanning cooperative providers.",
            "summary": {
                "sources_total": 2,
                "listing_total": 14 if processed else 3,
                "filtered_low_fit_total": 14 if processed else 0,
                "high_fit_total": 0,
                "high_match_min_score": 80,
                "tour_created_total": 0,
                "tour_existing_total": 0,
                "sources": [
                    {
                        "source_label": "Genossenschaften Austria",
                        "status": "scanned",
                        "listing_total": 8 if processed else 2,
                        "high_fit_total": 0,
                        "filtered_low_fit_total": 8 if processed else 0,
                    },
                    {
                        "source_label": "Justiz Edikte Austria",
                        "status": "scanned",
                        "listing_total": 6 if processed else 1,
                        "high_fit_total": 0,
                        "filtered_low_fit_total": 6 if processed else 0,
                    },
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 source(s) for scanning.", "status": "in_progress"},
                {
                    "step": "completed" if processed else "provider_scan",
                    "message": "No strong matches met the selected threshold." if processed else "Scanning cooperative providers.",
                    "status": "processed" if processed else "in_progress",
                },
            ],
        }

    def _fake_run_status(self, *, principal_id: str, run_id: str):
        assert principal_id == "pq-greenfield-browser"
        if run_id == "run-active-empty":
            calls = run_status_calls.get(run_id, 0)
            run_status_calls[run_id] = calls + 1
            return _fake_empty_run_status(run_id=run_id, principal_id=principal_id, processed=calls > 0)
        return {
            "run_id": run_id,
            "principal_id": principal_id,
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "status": "processed",
            "progress": 100,
            "message": "Property scouting run completed.",
            "summary": {
                "sources_total": 2,
                "listing_total": 7,
                "tour_created_total": 1,
                "tour_existing_total": 1,
                "sources": [
                    {
                        "source_label": "ImmoScout24 Germany",
                        "listing_total": 4,
                        "high_fit_total": 2,
                        "tour_created_total": 1,
                        "notified_total": 1,
                        "top_candidates": [
                            {
                                "title": "Altbau near U6",
                                "property_url": "https://www.immobilienscout24.de/expose/altbau-u6",
                                "fit_summary": "Personal fit 92/100 · shortlist · Lift and transit fit.",
                                "recommendation": "shortlist",
                                "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-1",
                                "tour_url": "https://propertyquarry.com/tours/altbau-u6",
                                "match_reasons": ["Lift and transit fit."],
                                "mismatch_reasons": [],
                                "property_facts": {
                                    "price_display": "EUR 420,000",
                                    "price_eur": 420000.0,
                                    "rooms": 3,
                                    "area_m2": 78,
                                    "postal_name": "Berlin Mitte",
                                    "nearest_supermarket_m": 280,
                                    "nearest_pharmacy_m": 410,
                                    "nearest_playground_m": 520,
                                    "nearest_subway_m": 1200,
                                },
                            },
                            {
                                "title": "Family flat near Tiergarten",
                                "property_url": "https://www.immobilienscout24.de/expose/family-tiergarten",
                                "fit_summary": "Personal fit 87/100 · shortlist · Larger layout and quieter block.",
                                "recommendation": "shortlist",
                                "review_url": "https://propertyquarry.com/app/handoffs/human_task:review-2",
                                "tour_url": "",
                                "match_reasons": ["Larger layout and quieter block."],
                                "mismatch_reasons": ["No 360 tour yet."],
                                "property_facts": {
                                    "price_display": "EUR 465,000",
                                    "price_eur": 465000.0,
                                    "rooms": 4,
                                    "area_m2": 92,
                                    "postal_name": "Berlin Tiergarten",
                                },
                            },
                        ],
                    }
                ],
            },
            "events": [
                {"step": "sources_resolved", "message": "Resolved 2 source(s) for scanning.", "status": "in_progress"},
                {"step": "completed", "message": "Property scouting run completed.", "status": "processed"},
            ],
        }

    def _fake_handoffs(self, *, principal_id: str, limit: int = 20, operator_id: str = "", status: str | None = "pending"):
        assert principal_id == "pq-greenfield-browser"
        return (
            HandoffNote(
                id="human_task:tour-1",
                queue_item_ref="queue:tour-1",
                summary="Hosted 3D page for Auhofstrasse shortlist",
                owner="office",
                due_time=None,
                escalation_status="high",
                task_type="property_tour_followup",
                delivery_reason="Lift, playground and subway fit the profile.",
                property_url="https://www.kalandra.at/objekt/14997053",
                tour_url="https://propertyquarry.com/tours/auhofstrasse-14997053",
            ),
        )

    monkeypatch.setattr(ProductService, "get_property_search_run_status", _fake_run_status)
    monkeypatch.setattr(ProductService, "list_handoffs", _fake_handoffs)

    app = create_app()
    test_client = TestClient(app, base_url="https://propertyquarry.com")
    test_client.headers.update({"X-EA-Principal-ID": "pq-greenfield-browser", "host": "propertyquarry.com"})

    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    local_base_url = f"http://127.0.0.1:{port}"
    browser_base_url = f"http://propertyquarry.com:{port}"
    _wait_for_http(local_base_url)
    try:
        yield {"base_url": browser_base_url, "client": test_client}
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--host-resolver-rules=MAP propertyquarry.com 127.0.0.1",
                "--no-proxy-server",
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def _new_context(browser: Browser, *, mobile: bool = False) -> BrowserContext:
    return browser.new_context(
        viewport={"width": 430 if mobile else 1440, "height": 932 if mobile else 1100},
        extra_http_headers={"X-EA-Principal-ID": "pq-greenfield-browser"},
    )


def _assert_property_shell_visual_gates(page: Page, *, max_appbar_height: int) -> None:
    appbar = page.locator(".pq-appbar, .pqx-topbar").first
    appbar_box = appbar.bounding_box()
    assert appbar_box is not None
    assert appbar_box["height"] <= max_appbar_height
    offenders = page.evaluate(
        """
        () => {
          const boxSelectors = ['.pq-appbar', '.pqx-topbar', '.pq-hero', '.pq-card', '.pq-shortlist-card', '.object-panel', '.pqx-panel', '.pqx-card', '.pqx-table-card'];
          const textSelectors = ['h1', 'h2', 'h3', 'p', 'small', '.pq-copy', '.pq-shortlist-meta', '.pq-shortlist-copy', '.object-copy', '.pqx-note', '.pqx-small'];
          const rows = [];
          for (const box of document.querySelectorAll(boxSelectors.join(','))) {
            const boxRect = box.getBoundingClientRect();
            if (boxRect.width <= 0 || boxRect.height <= 0) continue;
            for (const child of box.querySelectorAll(textSelectors.join(','))) {
              const childRect = child.getBoundingClientRect();
              if (childRect.width <= 0 || childRect.height <= 0) continue;
              if (
                childRect.left < boxRect.left - 1 ||
                childRect.right > boxRect.right + 1 ||
                childRect.top < boxRect.top - 1 ||
                childRect.bottom > boxRect.bottom + 1
              ) {
                rows.push({
                  box: box.className,
                  text: (child.textContent || '').trim().slice(0, 100),
                  deltaRight: Math.round(childRect.right - boxRect.right),
                  deltaBottom: Math.round(childRect.bottom - boxRect.bottom),
                });
              }
            }
          }
          return rows;
        }
        """
    )
    assert offenders == []


def _assert_research_packet_360_first(page: Page, *, min_stage_height: int) -> None:
    media = page.locator("[data-object-media-stage]").first
    ooda = page.get_by_text("OODA summary").first
    assert media.is_visible()
    assert ooda.is_visible()
    media_box = media.bounding_box()
    ooda_box = ooda.bounding_box()
    assert media_box is not None
    assert ooda_box is not None
    assert media_box["y"] < ooda_box["y"]
    assert media_box["height"] >= min_stage_height


def test_propertyquarry_greenfield_workspace_in_real_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-spa-shell' in content
        assert 'data-property-mobile-dock' in content
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-pq-theater' in content
        assert 'data-workbench-results-table' in content
        assert 'data-workbench-dossier' in content
        assert "Ranked shortlist" in content
        assert "Altbau near U6" in content
        assert "Family flat near Tiergarten" in content
        assert "360 ready" in content
        assert "Review packet" in content
        assert "Open 360" in content
        assert "OODA" in content
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        page.locator("[data-workbench-row]", has_text="Altbau near U6").click()
        page.wait_for_url(lambda url: "/app/research/" in str(url) and "run_id=run-42" in str(url), wait_until="domcontentloaded", timeout=5000)
        packet_content = page.content()
        assert "Open the space before you read the rest" not in packet_content
        assert "360 review first" not in packet_content
        _assert_research_packet_360_first(page, min_stage_height=420)
        assert page.locator("body", has_text="OODA summary").is_visible()
        assert page.locator("body", has_text="Decision pipeline").is_visible()
        assert page.locator("body", has_text="Decision feedback").is_visible()
        assert page.get_by_role("button", name="Save decision").is_visible()
        assert page.get_by_role("button", name="Open Clippy").is_visible()
    finally:
        context.close()


def test_propertyquarry_greenfield_workspace_is_mobile_usable(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        content = page.content()
        assert 'data-property-decision-workbench' in content
        assert 'data-pq-greenfield-shell' in content
        assert 'data-property-mobile-dock' in content
        assert page.locator('[data-workbench-mobile-mode="results"]').is_visible()
        assert page.locator('[data-workbench-mobile-mode="property"]').is_visible()
        mode_box = page.locator('[data-workbench-mobile-mode="results"]').bounding_box()
        assert mode_box is not None and mode_box["width"] <= 430
        mobile_dock = page.locator("[data-property-mobile-dock]")
        assert mobile_dock.is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
        page.locator("[data-workbench-row]", has_text="Family flat near Tiergarten").click()
        page.wait_for_url(lambda url: "/app/research/" in str(url) and "run_id=run-42" in str(url), wait_until="domcontentloaded", timeout=5000)
        assert page.locator("body", has_text="OODA summary").is_visible()
        assert page.locator("body", has_text="Decision pipeline").is_visible()
        assert page.locator("body", has_text="Decision feedback").is_visible()
        assert page.get_by_role("button", name="Open Clippy").is_visible()
        review_action = page.get_by_role("button", name="Save decision").bounding_box()
        assert review_action is not None and review_action["width"] <= 430
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
    finally:
        context.close()


def test_propertyquarry_workbench_tracks_household_and_followup_state_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    first = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": property_ref,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "source": "clippy_agent_brief",
            "followup_status": "asked",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-jonas",
            "stakeholder_label": "Jonas",
            "property_ref": property_ref,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Street noise still feels risky.",
            "source": "packet",
            "decision_state": "rejected",
        },
    )
    assert second.status_code == 200, second.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Household review").is_visible()
        assert page.locator("body", has_text="Agent follow-up").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        candidate_ref = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-ref")
        assert candidate_ref
        response = page.goto(f"{base_url}/app/properties?run_id=run-42&candidate={candidate_ref}", wait_until="networkidle")
        assert response is not None and response.ok
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            page.get_by_role("button", name="Answered").first.click()
        update_response = update_response_info.value
        assert update_response.ok, update_response.text()
        assert page.locator("[data-pw-followup-status]", has_text="Follow-up marked answered").is_visible()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Answered").is_visible()
        assert page.locator("body", has_text="Risk signals").is_visible()
    finally:
        context.close()


def test_propertyquarry_packet_tracks_followup_state_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    seeded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": property_ref,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "source": "clippy_agent_brief",
            "followup_status": "asked",
        },
    )
    assert seeded.status_code == 200, seeded.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert packet_path
        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as update_response_info:
            page.get_by_role("button", name="Answered").first.click()
        update_response = update_response_info.value
        assert update_response.ok, update_response.text()
        assert page.locator("body", has_text="Follow-up marked answered").is_visible()
        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Answered").is_visible()
    finally:
        context.close()


def test_propertyquarry_decision_to_clippy_to_packet_followup_flow_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        candidate_ref = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-ref")
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert candidate_ref
        assert packet_path

        response = page.goto(f"{base_url}/app/properties?run_id=run-42&candidate={candidate_ref}", wait_until="networkidle")
        assert response is not None and response.ok
        with page.expect_response("**/app/api/people/*/preference-profile/property-feedback") as save_response_info:
            page.get_by_role("button", name="No", exact=True).click()
            page.get_by_role("button", name="Save decision").click()
        save_response = save_response_info.value
        assert save_response.ok, save_response.text()
        assert page.locator("[data-pw-feedback-status]", has_text="Saved.").is_visible()

        page.get_by_role("button", name="Open Clippy").click()
        page.get_by_role("button", name="Ask agent next").click()
        with page.expect_response("**/app/api/property/decision-copilot") as clippy_response_info:
            page.get_by_role("button", name="Ask Clippy").click()
        clippy_response = clippy_response_info.value
        assert clippy_response.ok, clippy_response.text()
        with page.expect_response("**/app/api/property-feedback") as ask_agent_response_info:
            page.get_by_role("button", name=re.compile(r"Ask agent:")).first.click()
        ask_agent_response = ask_agent_response_info.value
        assert ask_agent_response.ok, ask_agent_response.text()
        assert page.locator("[data-pw-clippy-status]", has_text="Agent follow-up recorded").is_visible()

        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Can you").is_visible()
        assert page.locator("body", has_text="Asked").is_visible()

        response = page.goto(f"{base_url}{packet_path}?run_id=run-42" if "?" not in packet_path else f"{base_url}{packet_path}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
        with page.expect_response("**/app/api/property-feedback/*/followup-status") as packet_update_info:
            page.get_by_role("button", name="Answered").first.click()
        packet_update = packet_update_info.value
        assert packet_update.ok, packet_update.text()
        assert page.locator("body", has_text="Follow-up marked answered").is_visible()

        response = page.goto(f"{base_url}/app/properties?run_id=run-42&candidate={candidate_ref}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Answered").is_visible()
        assert page.locator("body", has_text="Household review").is_visible()
        assert page.locator("body", has_text="Risk signals").is_visible()
    finally:
        context.close()


def test_propertyquarry_active_run_auto_polls_notifies_and_renders_empty_result_desk(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    page.add_init_script(
        """
        (() => {
          try { Object.defineProperty(window, 'isSecureContext', { get: () => true, configurable: true }); } catch (_err) {}
          window.localStorage.setItem('propertyquarry.browserNotifications.enabled', '1');
          class FakeNotification {
            static permission = 'granted';
            static requestPermission = async () => 'granted';
            constructor(title, options) {
              window.localStorage.setItem('pq-test-notification-title', String(title || ''));
              window.localStorage.setItem('pq-test-notification-body', String((options && options.body) || ''));
              this.close = () => {};
            }
          }
          try { Object.defineProperty(window, 'Notification', { value: FakeNotification, configurable: true }); }
          catch (_err) { window.Notification = FakeNotification; }
        })();
        """
    )
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-active-empty", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.wait_for_function(
            "window.localStorage.getItem('propertyquarry.browserNotifications.run.run-active-empty.processed') === '1'",
            timeout=7000,
        )
        page.wait_for_selector("[data-pqx-empty-results]", timeout=7000)
        assert page.locator("[data-pqx-empty-results]", has_text="No strong matches met this brief").is_visible()
        assert page.locator("body", has_text="What would unlock more matches?").is_visible()
        assert page.locator("[data-pqx-counterfactuals]").is_visible()
        assert page.get_by_role("button", name=re.compile("Apply|Allow|Use|Raise|Relax|Reopen")).first.is_visible()
        assert page.locator("[data-pqx-source-breakdown]", has_text="Genossenschaften Austria").is_visible()
        assert page.evaluate("window.localStorage.getItem('pq-test-notification-title')") == "PropertyQuarry results are ready"
        assert "0 high-fit matches" in str(page.evaluate("window.localStorage.getItem('pq-test-notification-body')"))
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_shortlist_and_research_surfaces_do_not_bleed_text(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/shortlist?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.get_by_role("heading", name="Ranked review desk").first.is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)

        packet_href = page.locator('a[href*="/app/research/"]').first.get_attribute("href")
        assert packet_href
        packet_url = packet_href if packet_href.startswith("http") else f"{base_url}{packet_href}"
        response = page.goto(packet_url, wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator(".object-media-frame").is_visible()
        assert "Open the space before you read the rest" not in page.content()
        _assert_research_packet_360_first(page, min_stage_height=420)
        assert page.get_by_text("OODA summary").first.is_visible()
        _assert_property_shell_visual_gates(page, max_appbar_height=92)
    finally:
        context.close()


def test_propertyquarry_setup_wizard_changes_visible_controls_and_collapses_all_vienna(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        page.set_default_timeout(10000)
        response = page.goto(f"{base_url}/app/properties", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator('[data-console-form-variant="property_search"]').wait_for(state="visible")
        page.locator('[data-property-field-name="country_code"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="country_code"]').is_visible()
        assert page.locator('[data-property-field-name="location_query"]').is_hidden()

        page.select_option('select[name="country_code"]', "AT")
        page.locator("[data-property-step-next]").click()
        page.locator('[data-property-field-name="region_code"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="region_code"]').is_visible()
        assert page.locator('[data-property-field-name="country_code"]').is_hidden()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()

        page.locator('input[name="all_of_vienna"]').check()
        assert page.locator('[data-property-field-name="location_query"]').is_hidden()
        assert page.locator('[data-property-field-name="location_query"]').get_attribute("data-property-collapsed-by") == "all_of_vienna"

        page.locator('input[name="all_of_vienna"]').uncheck()
        assert page.locator('[data-property-field-name="location_query"]').is_visible()

        page.locator('[data-property-step-trigger="children"]').click()
        page.locator('[data-property-field-name="enable_family_mode"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="enable_family_mode"]').is_visible()
        assert page.locator('details[data-property-advanced-panel="children"]').is_hidden()
        assert page.locator('[data-property-field-name="school_stage_preferences"]').is_hidden()
        assert page.locator('[data-property-field-name="school_stage_preferences"]').get_attribute("data-property-collapsed-by") == "enable_family_mode"
        assert page.locator('[data-property-field-name="school_quality_priority"]').is_hidden()
        assert page.locator('[data-property-field-name="max_distance_to_playground_m"]').is_hidden()
        assert page.locator('[data-property-field-name="max_distance_to_library_m"]').is_hidden()

        page.locator('input[name="enable_family_mode"]').check()
        assert page.locator('details[data-property-advanced-panel="children"]').is_visible()
        assert page.locator('details[data-property-advanced-panel="children"]').evaluate("(node) => node.hasAttribute('open')") is False
        assert page.locator('[data-property-field-name="school_stage_preferences"]').is_hidden()
        assert page.locator('[data-property-field-name="school_quality_priority"]').is_hidden()
        assert page.locator('[data-property-field-name="school_quality_priority"]').get_attribute("data-property-collapsed-by") == "school_stage_preferences"
        page.locator('details[data-property-advanced-panel="children"] summary').click()
        assert page.locator('details[data-property-advanced-panel="children"]').evaluate("(node) => node.hasAttribute('open')") is True
        page.locator('[data-property-field-name="school_stage_preferences"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="school_stage_preferences"]').is_visible()
        assert page.locator('[data-property-field-name="max_distance_to_playground_m"]').is_visible()
        assert page.locator('[data-property-field-name="max_distance_to_library_m"]').is_visible()
        assert page.locator('[data-school-stage-note]').is_visible()
        assert "OR matches" in (page.locator('[data-school-stage-note]').text_content() or "")
        assert page.locator('[data-school-stage-variant]').first.is_hidden()

        page.locator('input[name="school_stage_preferences"][value="volksschule"]').check()
        assert page.locator('[data-school-stage-variant]').first.is_visible()
        assert "matching either variant stay in" in (page.locator('[data-school-stage-note]').text_content() or "")
        assert page.locator('[data-property-field-name="school_quality_priority"]').is_visible()

        page.locator('input[name="enable_family_mode"]').uncheck()
        assert page.locator('details[data-property-advanced-panel="children"]').is_hidden()
        assert page.locator('[data-property-field-name="school_stage_preferences"]').is_hidden()
        assert page.locator('[data-property-field-name="school_quality_priority"]').is_hidden()
        assert page.locator('[data-property-field-name="max_distance_to_playground_m"]').is_hidden()
        assert page.locator('[data-property-field-name="max_distance_to_library_m"]').is_hidden()

        page.locator('[data-property-step-trigger="reachability"]').click()
        page.locator('input[name="enable_commute_research"]').wait_for(state="visible")
        assert page.locator('input[name="enable_commute_research"]').is_visible()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_hidden()
        page.locator('input[name="enable_commute_research"]').check()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_visible()
        page.locator('details[data-property-advanced-panel="commute"] summary').click()
        assert page.locator('[data-property-field-name="commute_destination"]').is_visible()
        assert page.locator('[data-property-field-name="preferred_reachability_modes"]').is_visible()
        page.locator('input[name="enable_commute_research"]').uncheck()
        assert page.locator('details[data-property-advanced-panel="commute"]').is_hidden()

        page.locator('[data-property-step-trigger="areas"]').click()
        assert page.locator('details[data-property-advanced-panel="location_research"]').is_visible()
        assert page.locator('[data-property-field-name="max_distance_to_market_m"]').is_hidden()
        assert page.locator('details[data-property-advanced-panel="location_research"]').evaluate("(node) => node.hasAttribute('open')") is False
        page.locator('details[data-property-advanced-panel="location_research"] summary').click()
        assert page.locator('details[data-property-advanced-panel="location_research"]').evaluate("(node) => node.hasAttribute('open')") is True
        page.locator('[data-property-field-name="max_distance_to_market_m"]').wait_for(state="visible")
        assert page.locator('[data-property-field-name="max_distance_to_market_m"]').is_visible()
        assert page.locator('[data-property-field-name="max_distance_to_hardware_store_m"]').is_visible()
        assert page.locator('[data-property-field-name="prefer_good_air_quality"]').is_visible()
        assert page.locator('[data-property-field-name="avoid_flood_risk_area"]').is_visible()

        page.locator('[data-property-step-trigger="providers"]').click()
        page.locator('input[name="min_match_score"]').wait_for(state="visible")
        assert page.locator('label', has_text="Willhaben").count() >= 1
        assert page.locator('label', has_text="ImmoScout24 Austria").count() >= 1
        assert page.locator('label', has_text="Zillow").count() == 0
        match_slider = page.locator('input[name="min_match_score"]')
        assert match_slider.is_visible()
        assert match_slider.get_attribute("max") == "80"
        assert match_slider.get_attribute("data-range-selectable-max") == "45"
        assert match_slider.get_attribute("data-range-visual-max") == "80"
        tooltip = match_slider.get_attribute("title") or ""
        assert "backend" in tooltip.lower()
        assert "slower" in tooltip.lower()
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "45/80"
        assert page.locator('[data-current-plan-cap]').filter(has_text="Plan cap 45").count() >= 1
        floorplan_filter = page.locator('input[name="require_floorplan"]')
        assert floorplan_filter.is_visible()
        assert page.locator('label', has_text="Serious listings only").count() >= 1
        match_slider.evaluate("(node) => { node.value = '80'; node.dispatchEvent(new Event('input', { bubbles: true })); }")
        assert match_slider.input_value() == "45"
        assert page.locator('[data-range-value-for="min_match_score"]').inner_text().strip() == "45/80"
    finally:
        context.close()


def test_propertyquarry_setup_wizard_numeric_sliders_are_mobile_friendly(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=True)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'search'")

        expected_search_sliders = {
            "max_price_eur": "Any budget",
            "min_rooms": "Any rooms",
            "min_area_m2": "Any size",
        }
        for name, empty_label in expected_search_sliders.items():
            shell = page.locator(f'[data-range-control="{name}"]')
            slider = shell.locator('input[type="range"]')
            assert shell.is_visible()
            assert slider.is_visible()
            assert slider.get_attribute("data-range-empty-label") == empty_label
            shell_box = shell.bounding_box()
            slider_box = slider.bounding_box()
            assert shell_box is not None and shell_box["width"] <= 430
            assert slider_box is not None and slider_box["height"] >= 42

        price_slider = page.locator('input[name="max_price_eur"]')
        assert price_slider.get_attribute("max") == "6000"
        assert page.locator('[data-range-value-for="max_price_eur"]').inner_text().strip() == "Any budget"
        page.select_option('select[name="listing_mode"]', "buy")
        assert price_slider.get_attribute("max") == "2000000"
        assert page.locator('[data-range-control="max_price_eur"] [data-range-scale-max]').inner_text().strip() == "EUR 2M"

        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        for name in ("max_results_per_source", "min_match_score"):
            slider = page.locator(f'input[name="{name}"]')
            assert slider.is_visible()
            slider_box = slider.bounding_box()
            assert slider_box is not None and slider_box["height"] >= 42
            assert slider.get_attribute("max") in {"10", "80"}
        assert page.locator('input[name="max_results_per_source"]').get_attribute("data-range-selectable-max") == "2"
        assert page.locator('input[name="min_match_score"]').get_attribute("data-range-selectable-max") == "45"
        _assert_property_shell_visual_gates(page, max_appbar_height=130)
    finally:
        context.close()


def test_propertyquarry_start_failure_explains_backend_reason(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        page.route(
            "**/app/api/property/search-runs",
            lambda route: route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "property_plan_upgrade_required:plus"}),
            ),
        )
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        page.locator("[data-property-start]").click()
        page.wait_for_function("document.querySelector('[data-property-inline-error]')?.textContent.includes('Upgrade required for this run')")
        assert page.locator("[data-property-inline-error]", has_text="Upgrade required for this run").is_visible()
        assert page.locator("[data-property-inline-error]", has_text="plus plan").is_visible()
    finally:
        context.close()


def test_propertyquarry_launch_posts_real_start_payload_and_shows_run_status(
    monkeypatch: pytest.MonkeyPatch,
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
        self,
        *,
        principal_id: str,
        actor: str,
        selected_platforms: tuple[str, ...] = (),
        property_search_preferences: dict[str, object] | None = None,
        force_refresh: bool = False,
        max_results_per_source: int | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        observed["principal_id"] = principal_id
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        observed["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="sources_resolved",
                message="Resolved 1 source for launch smoke.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": "2026-06-05T00:00:00+00:00",
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "email_notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties", wait_until="networkidle")
        assert response is not None and response.ok
        page.select_option('select[name="country_code"]', "AT")
        page.locator('[data-property-step-trigger="areas"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'areas'")
        page.locator('input[name="all_of_vienna"]').check()
        page.locator('details[data-property-advanced-panel="location_research"] summary').click()
        page.locator('input[name="prefer_good_air_quality"]').check()
        page.locator('input[name="prefer_low_crime_area"]').check()
        page.locator('input[name="require_parking_pressure_check"]').check()
        page.locator('input[name="require_drinking_water_quality_research"]').check()
        page.locator('input[name="avoid_cesspit_or_septic_risk"]').check()
        page.locator('input[name="require_winter_access_research"]').check()
        page.locator('input[name="avoid_flood_risk_area"]').check()
        page.locator('input[name="max_distance_to_market_m"]').evaluate(
            "(node) => { node.value = '900'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('input[name="max_distance_to_hardware_store_m"]').evaluate(
            "(node) => { node.value = '1800'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('input[name="max_distance_to_medical_care_m"]').evaluate(
            "(node) => { node.value = '1200'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('[data-property-step-trigger="children"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'children'")
        page.locator('input[name="enable_family_mode"]').check()
        page.locator('details[data-property-advanced-panel="children"] summary').click()
        page.locator('input[name="max_distance_to_library_m"]').evaluate(
            "(node) => { node.value = '700'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('[data-property-step-trigger="providers"]').click()
        page.wait_for_function("document.querySelector('[data-console-form-variant=\"property_search\"]')?.dataset.propertyActiveStep === 'providers'")
        providerCount = page.locator('input[name="selected_platforms"]').count()
        expectedProviderCap = page.locator('[data-console-form-variant="property_search"]').evaluate(
            """(form) => {
              const raw = String(form.getAttribute('data-console-form-meta') || '').trim();
              const meta = raw ? JSON.parse(raw) : {};
              return Number(meta?.commercial?.max_platforms || 0);
            }"""
        )
        assert isinstance(expectedProviderCap, int)
        assert expectedProviderCap > 0
        page.locator('[data-checkbox-group-select-all="selected_platforms"]').click()
        checkedProviderCount = page.locator('input[name="selected_platforms"]:checked').count()
        assert providerCount > checkedProviderCount
        assert checkedProviderCount == expectedProviderCap
        assert page.locator('[data-property-inline-status]', has_text="allows up to 3 at once").is_visible()
        page.locator('input[name="min_match_score"]').evaluate(
            "(node) => { node.value = '45'; node.dispatchEvent(new Event('input', { bubbles: true })); }"
        )
        page.locator('input[name="require_floorplan"]').check()

        with page.expect_response("**/app/api/property/search-runs") as start_response:
            page.locator("[data-property-start]").click()
        response = start_response.value
        assert response.ok
        page.wait_for_url("**/app/properties?run_id=*", timeout=5000)
        run_id = page.evaluate("new URL(window.location.href).searchParams.get('run_id')")
        assert run_id
        page.wait_for_function("document.querySelector('[data-pqx-run-status]')?.textContent.trim().length > 0")
        assert "Could not start property search" not in page.locator("body").inner_text()
        deadline = time.time() + 5.0
        while "property_search_preferences" not in observed and time.time() < deadline:
            time.sleep(0.05)
        assert observed["principal_id"] == "pq-greenfield-browser"
        preferences = dict(observed["property_search_preferences"])
        assert preferences["country_code"] == "AT"
        assert preferences["region_code"] == "vienna"
        assert preferences["all_of_vienna"] is True
        assert preferences["location_query"] == "Vienna"
        assert preferences["prefer_good_air_quality"] is True
        assert preferences["prefer_low_crime_area"] is True
        assert preferences["require_parking_pressure_check"] is True
        assert preferences["require_drinking_water_quality_research"] is True
        assert preferences["avoid_cesspit_or_septic_risk"] is True
        assert preferences["require_winter_access_research"] is True
        assert preferences["avoid_flood_risk_area"] is True
        assert preferences["max_distance_to_market_m"] == 900
        assert preferences["max_distance_to_hardware_store_m"] == 1800
        assert preferences["max_distance_to_medical_care_m"] == 1200
        assert preferences["max_distance_to_library_m"] == 700
        assert preferences["min_match_score"] == 45
        assert preferences["require_floorplan"] is True
        assert len(observed["selected_platforms"]) == 3
        page.wait_for_function("document.querySelector('[data-pqx-run-status]')?.textContent.toLowerCase().includes('processed')")
        assert page.locator("body", has_text="Altbau near U6").is_visible()
        assert page.locator("body", has_text="Review packet").is_visible()
        assert page.locator("body", has_text="Open 360").is_visible()
        assert page.locator("body", has_text="Risk and investment").is_visible()
        page.locator("[data-workbench-row]", has_text="Altbau near U6").click()
        page.wait_for_url(lambda url: "/app/research/" in str(url) and f"run_id={run_id}" in str(url), wait_until="domcontentloaded", timeout=5000)
        assert page.locator("body", has_text="OODA summary").is_visible()
        assert page.locator("body", has_text="Alltagsfit").is_visible()
        assert page.locator("body", has_text="Risikofit").is_visible()
        assert page.locator("body", has_text="Decision feedback").is_visible()
    finally:
        context.close()


def test_propertyquarry_packet_dashboard_supports_real_browser_share_and_replication_actions(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    publication = client.post(
        "/app/api/properties/listing-browser-packet/packets/render",
        json={
            "packet_kind": "family_review",
            "privacy_mode": "family_review",
            "fliplink_format": "flipbook_3d",
            "property_payload": {
                "title": "Family flat near Augarten",
                "property_url": "https://www.willhaben.at/iad/immobilien/d/demo",
                "match_reasons": ["Floorplan and family fit."],
                "floorplan_refs": ["https://packets.propertyquarry.com/assets/floorplan.pdf"],
                "photo_refs": ["https://packets.propertyquarry.com/assets/photo.jpg"],
                "property_facts": {
                    "rooms": 3,
                    "area_m2": 84,
                    "street_address": "Private Street 4",
                    "map_lat": 48.2,
                    "map_lng": 16.3,
                    "has_floorplan": True,
                    "postal_name": "1020 Wien",
                },
                "public_preference_snapshot": {"prefer_balcony": True},
            },
        },
    )
    assert publication.status_code == 200, publication.text
    publication_id = publication.json()["publication"]["publication_id"]
    feedback_one = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-mara",
            "stakeholder_label": "Mara",
            "property_ref": "listing-browser-packet",
            "publication_id": publication_id,
            "category": "question",
            "sentiment": "neutral",
            "importance": 4,
            "text": "Can the agent confirm the operating costs?",
            "followup_status": "asked",
        },
    )
    assert feedback_one.status_code == 200, feedback_one.text
    feedback_two = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "family-jonas",
            "stakeholder_label": "Jonas",
            "property_ref": "listing-browser-packet",
            "publication_id": publication_id,
            "category": "dealbreaker",
            "sentiment": "negative",
            "importance": 5,
            "text": "Street noise is a blocker.",
            "decision_state": "rejected",
        },
    )
    assert feedback_two.status_code == 200, feedback_two.text
    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties/packets", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("[data-property-packets-dashboard]").is_visible()
        assert page.locator("body", has_text="Review packets ready for branded sharing.").is_visible()
        assert page.locator("body", has_text="Household review").is_visible()
        assert page.locator("body", has_text="Risk signals").is_visible()
        assert page.locator("body", has_text="Can the agent confirm the operating costs?").is_visible()
        page.locator('[data-packet-share-form] input[name="recipient_name"]').fill("Anna")
        page.locator('[data-packet-share-form] input[name="recipient_email"]').fill("anna@example.com")
        page.locator('[data-packet-share-form] input[name="relationship"]').fill("Sister")
        with page.expect_response("**/app/api/properties/packets/*/shares") as share_response_info:
            page.locator('[data-packet-share-form] button[type="submit"]').click()
        share_response = share_response_info.value
        assert share_response.ok, share_response.text()

        page.locator('[data-fliplink-analytics-form] input[name="views"]').fill("8")
        page.locator('[data-fliplink-analytics-form] input[name="unique_visitors"]').fill("2")
        page.locator('[data-fliplink-analytics-form] input[name="average_time_seconds"]').fill("55")
        with page.expect_response("**/app/api/properties/packets/*/fliplink/analytics-snapshot") as analytics_response_info:
            page.locator('[data-fliplink-analytics-form] button[type="submit"]').click()
        analytics_response = analytics_response_info.value
        assert analytics_response.ok, analytics_response.text()

        with page.expect_response("**/app/api/properties/packets/*/republish") as republish_response_info:
            page.locator(f'[data-republish-publication][data-publication-id="{publication_id}"]').click()
        republish_response = republish_response_info.value
        assert republish_response.ok, republish_response.text()

        page.reload(wait_until="networkidle")
        assert page.locator("body", has_text="Anna · family · link").is_visible()
        assert page.locator("[data-analytics-summary]", has_text="8 views").is_visible()
        assert page.locator("[data-analytics-summary]", has_text="2 visitors").is_visible()
        assert page.locator("body", has_text="Optimization recommendations").is_visible()
        assert page.locator("body", has_text="What changed").is_visible()
        assert page.locator("body", has_text="Street noise is a blocker.").is_visible()

        preview_expectations = {
            "search_results_ready": ("PropertyQuarry found 2 strong matches", "Open 360"),
            "property_match": ("Property match: Altbau near U6", "No — tell us why"),
            "tour_ready": ("Apartment tour ready: Family flat near Augarten", "No — tell us why"),
            "investment_research_ready": ("Investment research ready", "Pass — too risky"),
            "workspace_invitation": ("Mara invited you to PropertyQuarry", "Review workspace invite"),
            "workspace_access": ("Your access link for PropertyQuarry Workspace", "Open access link"),
            "google_connect": ("Connect Google to PropertyQuarry Workspace", "Connect Google"),
            "market_ready": ("PropertyQuarry market ready: Vienna", "Open PropertyQuarry"),
        }
        for template_key, (subject_text, cta_text) in preview_expectations.items():
            response = page.goto(f"{base_url}/app/properties/notifications/preview?template={template_key}", wait_until="networkidle")
            assert response is not None and response.ok
            assert page.locator("body", has_text="Email preview").is_visible()
            assert page.locator("body", has_text=subject_text).is_visible()
            assert page.frame_locator("iframe").locator("body", has_text=cta_text).is_visible()
    finally:
        context.close()


def test_propertyquarry_flagship_operating_loop_in_browser(
    browser: Browser,
    propertyquarry_browser_server: dict[str, object],
) -> None:
    client = propertyquarry_browser_server["client"]
    assert isinstance(client, TestClient)
    property_ref = "https://www.immobilienscout24.de/expose/altbau-u6"
    seeded = client.post(
        "/app/api/property-feedback",
        json={
            "stakeholder_id": "advisor-anna",
            "stakeholder_label": "Anna",
            "property_ref": property_ref,
            "category": "concern",
            "sentiment": "negative",
            "importance": 4,
            "text": "Operating costs still need proof before a viewing.",
            "source": "advisor_packet_review",
            "decision_state": "documents_requested",
        },
    )
    assert seeded.status_code == 200, seeded.text

    base_url = str(propertyquarry_browser_server["base_url"])
    context = _new_context(browser, mobile=False)
    page: Page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/properties?run_id=run-42", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Provider quality").is_visible()
        candidate_ref = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-ref")
        packet_path = page.locator("[data-workbench-row]", has_text="Altbau near U6").first.get_attribute("data-candidate-packet-url")
        assert candidate_ref
        assert packet_path
        response = page.goto(f"{base_url}/app/properties?run_id=run-42&candidate={candidate_ref}", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Authority posture").is_visible()
        assert page.locator("body", has_text="Official risk evidence").is_visible()
        with page.expect_response("**/app/api/people/*/preference-profile/property-feedback") as save_response_info:
            page.get_by_role("button", name="No", exact=True).click()
            page.get_by_role("button", name="Save decision").click()
        assert save_response_info.value.ok
        page.get_by_role("button", name="Open Clippy").click()
        page.get_by_role("button", name="Ask agent next").click()
        with page.expect_response("**/app/api/property/decision-copilot") as clippy_response_info:
            page.get_by_role("button", name="Ask Clippy").click()
        assert clippy_response_info.value.ok
        with page.expect_response("**/app/api/property-feedback") as followup_response_info:
            page.get_by_role("button", name=re.compile(r"Ask agent:")).first.click()
        assert followup_response_info.value.ok
        with page.expect_response("**/app/api/properties/*/packets/render") as packet_response_info:
            page.get_by_role("button", name="Create share packet").first.click()
        assert packet_response_info.value.ok
        page.wait_for_url(lambda url: "/app/properties/packets" in str(url), wait_until="networkidle", timeout=5000)
        assert page.locator("body", has_text="Household review").is_visible()
        assert page.locator("body", has_text="What changed").is_visible()
        share_form = page.locator('[data-packet-share-form]').first
        share_form.locator('input[name="recipient_name"]').fill("Anna")
        share_form.locator('input[name="recipient_email"]').fill("anna@example.com")
        share_form.locator('input[name="relationship"]').fill("Advisor")
        share_form.locator('select[name="audience_type"]').select_option("advisor")
        with page.expect_response("**/app/api/properties/packets/*/shares") as share_response_info:
            share_form.locator('button[type="submit"]').click()
        assert share_response_info.value.ok
        response = page.goto(f"{base_url}/app/properties/notifications/preview?template=property_match", wait_until="networkidle")
        assert response is not None and response.ok
        no_link = page.frame_locator("iframe").get_by_role("link", name="No — tell us why")
        href = no_link.get_attribute("href")
        assert href and "decision=no" in href and "clippy=1" in href
        packet_url = f"{base_url}{packet_path}"
        separator = "&" if "?" in packet_url else "?"
        response = page.goto(f"{packet_url}{separator}run_id=run-42&decision=no&clippy=1&prompt=What%20is%20the%20strongest%20blocker%20here%3F", wait_until="networkidle")
        assert response is not None and response.ok
        assert page.locator("body", has_text="Authority posture").is_visible()
        assert page.locator("body", has_text="Decision shortcut loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Clippy prompt loaded from the email or shared link.").is_visible()
        assert page.locator("body", has_text="Tracked follow-up").is_visible()
    finally:
        context.close()
