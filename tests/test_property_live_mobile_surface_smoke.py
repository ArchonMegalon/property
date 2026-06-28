from __future__ import annotations

import io
import json
from urllib.error import HTTPError

from scripts.propertyquarry_live_mobile_surface_smoke import (
    DEFAULT_ROUTES,
    SEEDED_RESEARCH_DETAIL_ROUTE,
    SEED_FIXTURE_USER_AGENT,
    _resolve_mobile_billing_external_handoff,
    _seed_research_detail_headers,
    build_seed_fixture_blocked_receipt,
    build_live_mobile_surface_receipt,
    build_mobile_coverage_checks,
    evaluate_mobile_metrics,
    main,
    route_is_research_detail,
    seed_research_detail_fixture,
    routes_require_api_auth,
    seeded_research_detail_payload,
)


BILLING_PORTAL_UNAVAILABLE_BODY = (
    "PropertyQuarry Billing portal unavailable. "
    "The billing portal is still being connected. "
    "Your PropertyQuarry access stays active from the account page."
)

BILLING_PORTAL_LOGIN_REQUIRED_BODY = (
    "PropertyQuarry Billing portal unavailable. "
    "This billing account still opens another sign-in, so PropertyQuarry is keeping it closed for now. "
    "Your PropertyQuarry access stays active from the account page."
)


def _base_metrics() -> dict[str, object]:
    return {
        "status_code": 200,
        "body_width": 390,
        "viewport_width": 390,
        "topbar_height": 72,
        "topnav_visible": True,
        "min_action_height": 46,
        "visible_card_count": 12,
        "heavy_shadow_count": 0,
        "district_picker_available": True,
        "district_map_popup_available": True,
        "district_list_hidden_in_map_mode": True,
        "district_map_modal_opened": True,
        "district_map_click_selected": True,
        "district_map_zoom_changed": True,
        "district_map_pinch_zoom_changed": True,
        "district_map_close_restored_scroll": True,
        "mobile_what_matters_single_open": True,
        "mobile_fold_single_open": True,
        "mobile_what_matters_page_scroll": True,
        "account_logout_strip_visible": True,
        "logout_button_count": 1,
        "account_menu_present": True,
        "account_menu_mobile_sheet": True,
        "account_menu_trigger_compact": True,
        "research_detail_workspace": True,
        "research_detail_decision_precedes_secondary_content": True,
        "research_detail_media_stage": True,
        "research_detail_visual_controls": True,
        "research_detail_fake_visual_ready": False,
        "research_detail_generated_reconstruction_honest": True,
        "research_detail_verified_tour_evidence_copy": True,
        "research_detail_walkthrough_evidence_copy": True,
        "research_detail_no_vague_visual_copy": True,
        "research_detail_walkthrough_magicfit_only": True,
        "research_detail_no_walkthrough_provider_chooser": True,
        "research_detail_no_legacy_walkthrough_providers": True,
        "research_detail_mobile_secondary_collapsed": True,
    }


def _failed_names(route: str, metrics: dict[str, object]) -> set[str]:
    return {str(row["name"]) for row in evaluate_mobile_metrics(route, metrics) if not row["ok"]}


def test_live_mobile_smoke_accepts_compact_search_surface_metrics() -> None:
    assert _failed_names("/app/search", _base_metrics()) == set()


def test_live_mobile_smoke_accepts_empty_shortlist_with_top_navigation_only() -> None:
    metrics = _base_metrics()

    assert _failed_names("/app/shortlist", metrics) == set()


def test_live_mobile_smoke_accepts_external_billing_handoff() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 303,
            "redirect_location": "https://billing.propertyquarry.com/account",
            "billing_handoff_host_resolves": True,
            "billing_handoff_usable": True,
        }
    )

    assert _failed_names("/app/billing", metrics) == set()


def test_live_mobile_smoke_accepts_fail_closed_billing_recovery() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 503,
            "billing_visible_text": BILLING_PORTAL_UNAVAILABLE_BODY,
        }
    )

    assert _failed_names("/app/billing", metrics) == set()


def test_live_mobile_smoke_accepts_login_required_fail_closed_billing_recovery() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 503,
            "billing_visible_text": BILLING_PORTAL_LOGIN_REQUIRED_BODY,
        }
    )

    assert _failed_names("/app/billing", metrics) == set()


def test_live_mobile_smoke_rejects_local_billing_page() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 503,
            "billing_visible_text": "PropertyQuarry Plan Agent Billing history Compare plans Open pricing",
        }
    )

    assert _failed_names("/app/billing", metrics) == {
        "billing_fail_closed_recovery",
        "billing_local_page_deleted",
    }


def test_live_mobile_smoke_rejects_local_billing_redirect_loop() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 303,
            "redirect_location": "/app/billing",
            "billing_handoff_host_resolves": False,
            "billing_handoff_usable": False,
        }
    )

    assert _failed_names("/app/billing", metrics) == {
        "billing_external_handoff",
        "billing_external_handoff_resolves",
        "billing_external_handoff_usable",
    }


def test_live_mobile_smoke_rejects_billing_handoff_that_requires_second_login() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "status_code": 303,
            "redirect_location": "https://billing.propertyquarry.com/account",
            "billing_handoff_host_resolves": True,
            "billing_handoff_usable": False,
        }
    )

    assert _failed_names("/app/billing", metrics) == {"billing_external_handoff_usable"}


def test_live_mobile_smoke_resolves_signed_bridge_launch_to_external_billing_host() -> None:
    class _Response:
        def __init__(self, location: str) -> None:
            self.status = 303
            self.headers = {"location": location}

    class _RequestContext:
        def get(self, url: str, *, headers=None, max_redirects=0, timeout=0):  # noqa: ANN001
            assert url == "http://localhost:8097/app/api/property/billing/bridge-launch"
            assert headers == {"Host": "propertyquarry.com"}
            assert max_redirects == 0
            assert timeout == 5000
            return _Response("https://billing.propertyquarry.com/sso/propertyquarry?pq_bridge=token")

    resolved = _resolve_mobile_billing_external_handoff(
        base_url="http://localhost:8097",
        redirect_location="/app/api/property/billing/bridge-launch",
        request_context=_RequestContext(),
        request_headers={"Host": "propertyquarry.com"},
        timeout_ms=5000,
    )

    assert resolved == {
        "external_location": "https://billing.propertyquarry.com/sso/propertyquarry?pq_bridge=token",
        "bridge_launch_used": True,
        "bridge_launch_url": "http://localhost:8097/app/api/property/billing/bridge-launch",
        "bridge_launch_status_code": 303,
    }


def test_live_mobile_smoke_accepts_research_and_packets_surfaces_without_search_controls() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "district_picker_available": False,
            "district_map_popup_available": False,
            "district_list_hidden_in_map_mode": False,
        }
    )

    assert _failed_names("/app/research", metrics) == set()
    assert _failed_names("/app/properties/packets", metrics) == set()


def test_live_mobile_smoke_requires_real_research_detail_layout() -> None:
    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", _base_metrics()) == set()
    metrics = _base_metrics()
    metrics.update(
        {
            "research_detail_workspace": False,
            "research_detail_decision_precedes_secondary_content": False,
            "research_detail_media_stage": False,
            "research_detail_visual_controls": False,
            "research_detail_fake_visual_ready": True,
            "research_detail_generated_reconstruction_honest": False,
            "research_detail_verified_tour_evidence_copy": False,
            "research_detail_walkthrough_evidence_copy": False,
            "research_detail_no_vague_visual_copy": False,
            "research_detail_walkthrough_magicfit_only": False,
            "research_detail_no_walkthrough_provider_chooser": False,
            "research_detail_no_legacy_walkthrough_providers": False,
            "research_detail_mobile_secondary_collapsed": False,
        }
    )

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_workspace",
        "research_detail_decision_precedes_secondary_content",
        "research_detail_media_stage",
        "research_detail_visual_controls",
        "research_detail_no_fake_visual_ready",
        "research_detail_generated_reconstruction_honest",
        "research_detail_verified_tour_evidence_copy",
        "research_detail_walkthrough_evidence_copy",
        "research_detail_no_vague_visual_copy",
        "research_detail_walkthrough_magicfit_only",
        "research_detail_no_walkthrough_provider_chooser",
        "research_detail_no_legacy_walkthrough_providers",
        "research_detail_mobile_secondary_collapsed",
    }


def test_live_mobile_smoke_rejects_generated_reconstruction_without_verified_tour_path() -> None:
    metrics = _base_metrics()
    metrics["research_detail_generated_reconstruction_honest"] = False

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_generated_reconstruction_honest",
    }


def test_live_mobile_smoke_rejects_vague_research_detail_visual_copy() -> None:
    metrics = _base_metrics()
    metrics["research_detail_no_vague_visual_copy"] = False

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_no_vague_visual_copy",
    }


def test_live_mobile_smoke_requires_compact_mobile_research_detail_secondary_sections() -> None:
    metrics = _base_metrics()
    metrics["research_detail_mobile_secondary_collapsed"] = False

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_mobile_secondary_collapsed",
    }


def test_live_mobile_smoke_requires_magicfit_only_walkthrough_controls() -> None:
    metrics = _base_metrics()
    metrics["research_detail_walkthrough_magicfit_only"] = False

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_walkthrough_magicfit_only",
    }


def test_live_mobile_smoke_rejects_walkthrough_provider_chooser_and_legacy_provider_noise() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "research_detail_no_walkthrough_provider_chooser": False,
            "research_detail_no_legacy_walkthrough_providers": False,
        }
    )

    assert _failed_names("/app/research/perf-candidate-1020?run_id=run-gold", metrics) == {
        "research_detail_no_walkthrough_provider_chooser",
        "research_detail_no_legacy_walkthrough_providers",
    }


def test_live_mobile_smoke_default_routes_cover_settings_surfaces() -> None:
    assert {
        "/app/properties",
        "/app/settings/google",
        "/app/settings/access",
        "/app/settings/usage",
        "/app/settings/support",
        "/app/settings/trust",
        "/app/settings/invitations",
    }.issubset(set(DEFAULT_ROUTES))


def test_live_mobile_smoke_blocks_app_routes_without_api_token_before_playwright() -> None:
    assert routes_require_api_auth(("/app/search",)) is True
    assert routes_require_api_auth(("/pricing",)) is False

    receipt = build_live_mobile_surface_receipt(
        base_url="http://localhost:8097",
        api_token="",
        principal_id="pq-live-mobile-smoke",
        routes=("/app/search",),
    )

    assert receipt["status"] == "blocked"
    assert receipt["routes"] == []
    assert receipt["coverage_checks"] == [
        {
            "name": "api_token_present_for_app_routes",
            "ok": False,
            "reason": "Live mobile app-surface smoke requires EA_API_TOKEN or --api-token; otherwise protected pages render sign-in redirects instead of the app UI.",
        }
    ]


def test_live_mobile_smoke_can_require_current_research_detail_route() -> None:
    assert route_is_research_detail("/app/research") is False
    assert route_is_research_detail("/app/research/current-result?run_id=run-gold") is True

    missing = build_mobile_coverage_checks(DEFAULT_ROUTES, require_research_detail=True)
    assert missing[0] == {
        "name": "research_detail_route_configured",
        "ok": False,
        "required_route_prefix": "/app/research/",
        "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
    }
    registry_check = missing[1]
    assert registry_check["name"] == "registry_mobile_customer_surfaces_covered"
    assert registry_check["ok"] is False
    assert set(registry_check["missing_surface_keys"]) == {
        "property_research_detail",
        "floorplan_and_tour_control",
        "video_walkthrough",
    }

    covered = build_mobile_coverage_checks(
        (*DEFAULT_ROUTES, "/app/research/current-result?run_id=run-gold"),
        require_research_detail=True,
    )
    assert covered == [
        {
            "name": "research_detail_route_configured",
            "ok": True,
            "required_route_prefix": "/app/research/",
            "reason": "Gold mobile smoke must exercise a current live research detail page, not only /app/research.",
        },
        {
            "name": "registry_mobile_customer_surfaces_covered",
            "ok": True,
            "covered_surface_count": 18,
            "missing_surface_keys": [],
            "reason": "Live mobile smoke routes must cover every customer-visible /app surface declared in the PropertyQuarry surface registry.",
        },
    ]

def test_live_mobile_smoke_rejects_missing_registry_mobile_surface() -> None:
    routes_without_run_home = tuple(route for route in DEFAULT_ROUTES if route != "/app/properties")

    checks = build_mobile_coverage_checks(routes_without_run_home, require_research_detail=False)
    registry_check = next(check for check in checks if check["name"] == "registry_mobile_customer_surfaces_covered")

    assert registry_check["ok"] is False
    assert registry_check["missing_surface_keys"] == ["run_home", "fleet_repair"]


def test_live_mobile_smoke_seeded_research_detail_payload_is_valid_detail_fixture() -> None:
    payload = seeded_research_detail_payload()
    candidates = list(payload["saved_shortlist_candidates"])
    candidate = dict(candidates[0])

    assert route_is_research_detail(SEEDED_RESEARCH_DETAIL_ROUTE) is True
    assert payload["location_query"] == "1020 Vienna"
    assert candidate["candidate_ref"] == "perf-candidate-1020"
    assert candidate["saved_from_run_id"] == "run-gold-mobile"
    assert candidate["packet_url"] == "/app/research/perf-candidate-1020"
    assert dict(candidate["property_facts"])["listing_fact_confirmation"]["status"] == "confirmed"


def test_live_mobile_smoke_seed_headers_include_public_edge_safe_metadata() -> None:
    headers = _seed_research_detail_headers(
        base_url="https://propertyquarry.com",
        api_token="secret-token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        host_header="propertyquarry.com",
    )

    assert headers == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": SEED_FIXTURE_USER_AGENT,
        "X-EA-Principal-ID": "cf-email:tibor.girschele@gmail.com",
        "Origin": "https://propertyquarry.com",
        "Referer": "https://propertyquarry.com/app/search",
        "Host": "propertyquarry.com",
        "Authorization": "Bearer secret-token",
        "X-EA-API-Token": "secret-token",
    }


def test_live_mobile_smoke_seed_fixture_posts_with_browser_like_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status = 200

        def read(self, _size: int = -1) -> bytes:
            return b'{"ok":true}'

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_urlopen(request, timeout: int = 0):
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = {key.title(): value for key, value in request.header_items()}
        captured["body"] = json.loads((request.data or b"{}").decode("utf-8"))
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    route = seed_research_detail_fixture(
        base_url="https://propertyquarry.com",
        api_token="secret-token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        host_header="propertyquarry.com",
    )

    assert route == SEEDED_RESEARCH_DETAIL_ROUTE
    assert captured["timeout"] == 20
    assert captured["url"] == "https://propertyquarry.com/v1/onboarding/property-search/preferences"
    assert captured["method"] == "POST"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": SEED_FIXTURE_USER_AGENT,
        "X-Ea-Principal-Id": "cf-email:tibor.girschele@gmail.com",
        "Origin": "https://propertyquarry.com",
        "Referer": "https://propertyquarry.com/app/search",
        "Host": "propertyquarry.com",
        "Authorization": "Bearer secret-token",
        "X-Ea-Api-Token": "secret-token",
    }
    candidate = dict(captured["body"]["saved_shortlist_candidates"][0])
    assert candidate["candidate_ref"] == "perf-candidate-1020"


def test_live_mobile_smoke_seed_fixture_raises_for_http_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int = 0):
        raise HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b"forbidden"),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    try:
        seed_research_detail_fixture(
            base_url="https://propertyquarry.com",
            api_token="secret-token",
            principal_id="cf-email:tibor.girschele@gmail.com",
            host_header="propertyquarry.com",
        )
    except HTTPError as exc:
        assert exc.code == 403
    else:  # pragma: no cover - guard against silently swallowing live seeding failures.
        raise AssertionError("expected HTTPError")


def test_live_mobile_smoke_builds_blocked_receipt_when_seed_fixture_cannot_be_created() -> None:
    receipt = build_seed_fixture_blocked_receipt(
        base_url="https://propertyquarry.com",
        host_header="propertyquarry.com",
        principal_id="pq-live-mobile-smoke",
        viewport_width=390,
        viewport_height=844,
        error="seed_research_detail_fixture_failed:TimeoutError: timed out",
    )

    assert receipt["status"] == "blocked"
    assert receipt["route_count"] == 0
    assert receipt["failed_count"] == 1
    assert receipt["error"] == "seed_research_detail_fixture_failed:TimeoutError: timed out"
    assert receipt["coverage_checks"] == [
        {
            "name": "research_detail_seed_fixture_ready",
            "ok": False,
            "reason": "Live mobile smoke could not seed the saved research-detail fixture, so it cannot honestly prove the open-property surface.",
            "error": "seed_research_detail_fixture_failed:TimeoutError: timed out",
        }
    ]


def test_live_mobile_smoke_main_writes_blocked_receipt_when_seed_fixture_times_out(monkeypatch, tmp_path) -> None:
    out_path = tmp_path / "live-mobile-timeout.json"

    monkeypatch.setattr(
        "scripts.propertyquarry_live_mobile_surface_smoke.seed_research_detail_fixture",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(
        "scripts.propertyquarry_live_mobile_surface_smoke.build_live_mobile_surface_receipt",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("receipt builder should not run when seeding fails")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "propertyquarry_live_mobile_surface_smoke.py",
            "--base-url",
            "https://propertyquarry.com",
            "--api-token",
            "secret-token",
            "--seed-research-detail-fixture",
            "--write",
            str(out_path),
        ],
    )

    exit_code = main()

    assert exit_code == 1
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["error"] == "seed_research_detail_fixture_failed:TimeoutError: timed out"


def test_live_mobile_smoke_rejects_horizontal_overflow_and_noisy_chrome() -> None:
    metrics = _base_metrics()
    metrics.update({"body_width": 420, "topbar_height": 140, "heavy_shadow_count": 5})

    assert _failed_names("/app/search", metrics) == {
        "no_horizontal_overflow",
        "compact_topbar",
        "low_shadow_noise",
    }


def test_live_mobile_smoke_requires_search_district_picker_popup() -> None:
    metrics = _base_metrics()
    metrics.update({"district_map_popup_available": False, "district_list_hidden_in_map_mode": False})

    assert _failed_names("/app/search", metrics) == {
        "district_map_popup_available",
        "district_list_not_visible_in_map_mode",
    }


def test_live_mobile_smoke_requires_interactive_search_district_map() -> None:
    metrics = _base_metrics()
    metrics.update(
        {
            "district_map_modal_opened": False,
            "district_map_click_selected": False,
            "district_map_zoom_changed": False,
            "district_map_pinch_zoom_changed": False,
            "district_map_close_restored_scroll": False,
        }
    )

    assert _failed_names("/app/search", metrics) == {
        "district_map_modal_opens",
        "district_map_click_selects_shape",
        "district_map_zoom_toggle_changes_scale",
        "district_map_pinch_zoom_changes_scale",
        "district_map_close_restores_scroll",
    }


def test_live_mobile_smoke_requires_single_open_what_matters_group() -> None:
    metrics = _base_metrics()
    metrics.update({"mobile_what_matters_single_open": False})

    assert _failed_names("/app/search", metrics) == {"mobile_what_matters_single_open_section"}


def test_live_mobile_smoke_requires_single_open_generic_mobile_fold() -> None:
    metrics = _base_metrics()
    metrics.update({"mobile_fold_single_open": False})

    assert _failed_names("/app/alerts", metrics) == {"mobile_fold_single_open"}


def test_live_mobile_smoke_requires_page_scrolling_what_matters_surface() -> None:
    metrics = _base_metrics()
    metrics.update({"mobile_what_matters_page_scroll": False})

    assert _failed_names("/app/search", metrics) == {"mobile_what_matters_page_scroll"}


def test_live_mobile_smoke_requires_single_account_logout() -> None:
    metrics = _base_metrics()
    metrics.update({"logout_button_count": 2})

    assert _failed_names("/app/account", metrics) == {"single_logout_action"}


def test_live_mobile_smoke_requires_compact_account_menu_sheet() -> None:
    metrics = _base_metrics()
    metrics.update({"account_menu_mobile_sheet": False, "account_menu_trigger_compact": False})

    assert _failed_names("/app/account", metrics) == {
        "account_menu_mobile_sheet",
        "account_menu_trigger_compact",
    }


def test_live_mobile_smoke_accepts_dedicated_account_logout_without_dropdown() -> None:
    metrics = _base_metrics()
    metrics.update({"account_menu_present": False, "account_menu_mobile_sheet": False, "account_menu_trigger_compact": False})

    assert _failed_names("/app/account", metrics) == set()


def test_live_mobile_smoke_rejects_small_packet_touch_targets() -> None:
    metrics = _base_metrics()
    metrics.update({"min_action_height": 40})

    assert _failed_names("/app/properties/packets", metrics) == {"primary_touch_targets"}
