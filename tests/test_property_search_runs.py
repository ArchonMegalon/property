from __future__ import annotations

import json
import os
import time
import urllib.parse
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

import app.product.service as product_service
from app.product.service import ProductService
from app.product.service import _property_alert_personal_fit_snapshot, _property_candidate_matches_requested_location, _property_search_location_hints
from app.services.property_billing import property_commercial_snapshot
from app.services import property_market_catalog
from tests.product_test_helpers import build_product_client, build_property_client, seed_product_state, start_workspace


def _poll_property_search_run_status(client, run_id: str) -> dict[str, object]:
    latest_status: dict[str, object] = {}
    for _ in range(120):
        response = client.get(f"/app/api/signals/property/search/run/{run_id}")
        assert response.status_code == 200, response.text
        latest_status = response.json()
        if str(latest_status.get("status") or "").strip() in {"processed", "failed", "noop", "cancelled"}:
            return latest_status
        time.sleep(0.02)
    return latest_status


def test_free_property_plan_stays_narrower_than_paid_lanes() -> None:
    snapshot = property_commercial_snapshot({})

    assert snapshot["current_plan_key"] == "free"
    assert snapshot["research_depth"] == "standard"
    assert snapshot["investment_research_level"] == "none"
    assert snapshot["max_platforms"] == 3
    assert snapshot["max_results_per_source"] == 2
    assert snapshot["max_match_score"] == 45


def test_property_plan_investment_research_levels_follow_tier() -> None:
    plus = property_commercial_snapshot(
        {"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}}
    )
    agent = property_commercial_snapshot(
        {"property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}}
    )

    assert plus["investment_research_level"] == "preview"
    assert plus["research_depth"] == "deep"
    assert plus["max_platforms"] == 8
    assert plus["max_match_score"] == 65
    assert plus["magic_fit_scene_period"] == "day"
    assert plus["magic_fit_video_period"] == "day"
    assert agent["investment_research_level"] == "full"
    assert agent["research_depth"] == "deep"
    assert agent["max_platforms"] == 0
    assert agent["max_match_score"] == 80
    assert agent["magic_fit_scene_period"] == "none"
    assert agent["magic_fit_video_period"] == "none"


def test_findmyhome_entry_links_are_not_treated_as_supported_property_listings() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/immo/wohnung-kaufen/wien?id=13&entry=20&sort=&dir=ASC&pp=20&vars=id%3A13%3Bw_e%3A1%3Bland%3AAT%3Bbl%3A9%3B&lang=de&module=select&list="
    )


def test_findmyhome_search_page_is_not_treated_as_property_listing() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/immo/wohnung-kaufen/wien"
    )


def test_findmyhome_search_state_urls_stay_unsupported_after_sanitization() -> None:
    assert not product_service._property_scout_is_supported_listing_url(
        "https://findmyhome.at/immo/wohnung-kaufen/wien?id=14&entry=10&sort=sort_fl&dir=ASC&pp=10&vars=&lang=&module=&list='/'"
    )


def test_findmyhome_short_detail_url_is_treated_as_supported_listing() -> None:
    assert product_service._property_scout_is_supported_listing_url(
        "https://www.findmyhome.at/5620769?tl=1"
    )


def test_findmyhome_result_cards_extract_short_detail_urls() -> None:
    html = '''
    <div class="row margin-top-20">
      <div class="col-xs-12 col-sm-9 col-md-9 col-lg-9">
        <h3 class="obj_list">
          <strong><span style="color:#c30a32">TOP: </span></strong>
          <a href='/5620769?tl=1' class='btnHeadlineErgebnisliste'>Helle 2-Zimmer Wohnung, Nähe Meiselmarkt</a>
        </h3>
      </div>
    </div>
    '''

    urls = product_service._property_scout_extract_listing_urls(
        source_url="https://www.findmyhome.at/immo/wohnung-kaufen/wien",
        html=html,
        source_spec={"provider_filter_pushdown": {"requested": {}, "applied": {}}},
    )

    assert urls == ("https://www.findmyhome.at/5620769?tl=1",)


def test_free_property_plan_uses_daily_visual_generation_caps() -> None:
    snapshot = property_commercial_snapshot({})

    assert snapshot["magic_fit_scene_limit"] == 1
    assert snapshot["magic_fit_video_limit"] == 1
    assert snapshot["magic_fit_scene_period"] == "week"
    assert snapshot["magic_fit_video_period"] == "day"


class _QuotaRow:
    def __init__(self, *, event_type: str, created_at: str, channel: str = "product") -> None:
        self.channel = channel
        self.event_type = event_type
        self.created_at = created_at


class _QuotaRuntime:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def list_recent_observations(self, limit: int = 4000, principal_id: str = "") -> list[object]:
        return list(self._rows)[:limit]


class _QuotaOnboarding:
    def __init__(self, preferences: dict[str, object]) -> None:
        self._preferences = preferences

    def status(self, principal_id: str = "") -> dict[str, object]:
        return {"property_search_preferences": dict(self._preferences)}


class _QuotaContainer:
    def __init__(self, preferences: dict[str, object], rows: list[object]) -> None:
        self.onboarding = _QuotaOnboarding(preferences)
        self.channel_runtime = _QuotaRuntime(rows)


class _PreviewCacheRuntime:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def ingest_observation(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        dedupe_key: str = "",
        **_kwargs,
    ) -> object:
        row = SimpleNamespace(
            principal_id=principal_id,
            channel=channel,
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            dedupe_key=dedupe_key,
            created_at=datetime.now(timezone.utc).isoformat(),
            observation_id=str(uuid.uuid4()),
        )
        self.rows.insert(0, row)
        return row

    def list_recent_observations(self, limit: int = 4000, principal_id: str = "") -> list[object]:
        rows = [
            row
            for row in self.rows
            if not principal_id or str(getattr(row, "principal_id", "") or "").strip() == str(principal_id or "").strip()
        ]
        return rows[:limit]


class _PreviewCacheContainer:
    def __init__(self) -> None:
        self.channel_runtime = _PreviewCacheRuntime()


def test_property_visual_quota_enforces_free_daily_magic_fit_limit() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _QuotaContainer(
        {},
        [
            _QuotaRow(
                event_type="property_magic_fit_scene_created",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
    )

    with pytest.raises(ValueError, match="property_magic_fit_upgrade_required:plus"):
        service._enforce_property_visual_quota(
            principal_id="cf-email:quota-free@example.test",
            property_preferences={},
            quota_kind="scene",
        )


def test_property_visual_quota_enforces_plus_daily_video_limit() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _QuotaContainer(
        {"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}},
        [
            _QuotaRow(event_type="generic_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
            _QuotaRow(event_type="willhaben_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
            _QuotaRow(event_type="generic_property_tour_created", created_at=datetime.now(timezone.utc).isoformat()),
        ],
    )

    with pytest.raises(ValueError, match="property_tour_upgrade_required:agent"):
        service._enforce_property_visual_quota(
            principal_id="cf-email:quota-plus@example.test",
            property_preferences={"property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"}},
            quota_kind="video",
        )


def test_propertyquarry_public_urls_do_not_inherit_external_brain_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL", raising=False)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://myexternalbrain.com/tours")

    assert product_service._property_public_app_base_url() == "https://propertyquarry.com"
    assert product_service._property_public_tour_base_url() == "https://propertyquarry.com/tours"


def test_property_public_preview_cache_reuses_sanitized_public_facts() -> None:
    service = ProductService.__new__(ProductService)
    service._container = _PreviewCacheContainer()
    cache_index: dict[str, dict[str, object]] = {}
    stored = service._property_public_preview_cache_store(
        cache_index=cache_index,
        property_url="https://example.test/listing/1",
        preview={
            "property_url": "https://example.test/listing/1",
            "listing_id": "listing-1",
            "title": "Quiet courtyard flat",
            "summary": "Useful public preview facts.",
            "property_facts_json": {
                "provider_channel": "findmyhome_at",
                "postal_name": "1200 Wien",
                "rooms": 3,
                "has_floorplan": True,
                "exact_address": "Hidden 1",
                "lat": 48.2,
                "cookie_debug": "nope",
            },
            "floorplan_urls_json": ["https://cdn.example.test/floorplan.png"],
        },
    )

    assert stored["property_facts_json"]["provider_channel"] == "findmyhome_at"
    assert "exact_address" not in stored["property_facts_json"]
    assert "lat" not in stored["property_facts_json"]
    assert "cookie_debug" not in stored["property_facts_json"]

    indexed = service._property_public_preview_cache_index()
    loaded = service._property_public_preview_cache_lookup(
        cache_index=indexed,
        property_url="https://example.test/listing/1",
    )

    assert loaded is not None
    assert loaded["title"] == "Quiet courtyard flat"
    assert loaded["property_facts_json"]["has_floorplan"] is True


def test_austria_noise_preference_uses_layout_quiet_signal_only_as_weak_hint() -> None:
    adjustment, notes = product_service._property_austria_preference_score_adjustment(
        preferences={"country_code": "AT", "avoid_noise_risk_area": True},
        property_facts={"quiet_layout_signal": "weak_positive"},
        title="Wohnung",
        summary="Ruhige Lage",
    )

    assert adjustment == -2.0
    assert "noise evidence missing" in notes
    assert "layout-derived quiet signal" in notes


def test_property_public_preview_workers_warm_multiple_provider_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProductService.__new__(ProductService)
    service._container = _PreviewCacheContainer()
    cache_index: dict[str, dict[str, object]] = {}
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_WARM_LIMIT", "2")

    preview_calls: list[str] = []

    def _fake_preview(property_url: str, prefer_fast: bool = False) -> dict[str, object]:
        preview_calls.append(property_url)
        return {
            "property_url": property_url,
            "listing_id": property_url.rsplit("/", 1)[-1],
            "title": f"Preview for {property_url.rsplit('/', 1)[-1]}",
            "summary": "Reusable public facts.",
            "property_facts_json": {
                "provider_channel": "provider",
                "has_floorplan": property_url.endswith("1"),
            },
        }

    monkeypatch.setattr(product_service, "_property_scout_page_preview_compat", _fake_preview)

    result = service._warm_property_public_preview_cache_for_sources(
        specs=[
            {"platform": "derstandard_at", "label": "DER STANDARD", "url": "https://example.test/derstandard", "source_access_level": "browser"},
            {"platform": "immmo_at", "label": "immmo", "url": "https://example.test/immmo", "source_access_level": "public"},
        ],
        prefetched_source_results={
            ("derstandard_at", "https://example.test/derstandard"): {
                "listing_urls": [
                    "https://example.test/listing/1",
                    "https://example.test/listing/2",
                ]
            },
            ("immmo_at", "https://example.test/immmo"): {
                "listing_urls": [
                    "https://example.test/listing/3",
                    "https://example.test/listing/4",
                ]
            },
        },
        cache_index=cache_index,
    )

    assert result["enabled"] is True
    assert result["worker_concurrency"] == 2
    assert result["warm_limit"] == 2
    assert result["warmed_total"] == 4
    assert result["sources_touched"] == 2
    assert set(preview_calls) == {
        "https://example.test/listing/1",
        "https://example.test/listing/2",
        "https://example.test/listing/3",
        "https://example.test/listing/4",
    }
    assert service._property_public_preview_cache_lookup(
        cache_index=cache_index,
        property_url="https://example.test/listing/3",
    ) is not None


def test_property_search_location_matching_prefers_requested_districts() -> None:
    hints = _property_search_location_hints({"location_query": "1200 Vienna, 1020 Vienna, 1090"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=1",
        title="Wohnung in 1200 Wien mit Lift",
        summary="Nahe U6 und familienfreundlich.",
        property_facts={"postal_name": "1200 Wien"},
    ) is True
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=2",
        title="Wohnung in 1130 Wien",
        summary="Altbau",
        property_facts={"postal_name": "1130 Wien"},
    ) is False


def test_property_search_location_matching_rejects_unselected_vienna_districts() -> None:
    hints = _property_search_location_hints(
        {
            "location_query": (
                "1020 Vienna, 1070 Vienna, 1090 Vienna, 1100 Vienna, 1110 Vienna, "
                "1180 Vienna, 1200 Vienna, 1220 Vienna, Aspern"
            )
        }
    )

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1150-rudolfsheim-fuenfhaus/top-lage-naehe-westbahnhof",
        title="Top Lage Nähe Westbahnhof, 69 m², € 838,13, (1150 Wien) - willhaben",
        summary="Provider result page was queried from a selected Vienna source scope.",
        property_facts={"source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/wien/wien-1020-leopoldstadt/familienwohnung",
        title="Helle Familienwohnung, 69 m², € 938,13, (1020 Wien) - willhaben",
        summary="Provider result page was queried from a selected Vienna source scope.",
        property_facts={"source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is True


def test_property_search_location_matching_accepts_source_scope_location() -> None:
    hints = _property_search_location_hints({"location_query": "1200 Vienna, 1020 Vienna, 1090"})
    facts = product_service._property_facts_with_source_scope(
        facts={"street_address": "Rotensterngasse 21", "provider_channel": "justiz_edikte_at"},
        source_url=(
            "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/suchedi?"
            "retfields=%5BVPLZ%5D=1020;%5BVOrt%5D=Wien"
        ),
        source_label="Justiz Edikte Auctions | Austria | Buy | 1020 Vienna",
    )

    assert facts["source_scope_location"] == "1020 Vienna"
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        title="BG Leopoldstadt, 082 25 E 89/25g",
        summary="Sparse judicial auction detail page.",
        property_facts=facts,
    ) is True


def test_property_provider_greenfield_api_returns_country_scoped_catalog_with_austria_and_cr_regression_coverage() -> None:
    client = build_property_client(principal_id="exec-provider-catalog-germany")
    de_body = client.get("/app/api/property/providers?country=DE").json()

    assert any(row["value"] == "core_portals_de" and row["family"] == "core_portal" for row in de_body["providers"])
    assert any(row["value"] == "shared_housing_de" and row["family"] == "shared_housing" for row in de_body["providers"])
    assert any(row["value"] == "corporate_landlords_de" and row["family"] == "corporate_landlord" for row in de_body["providers"])
    assert any(row["value"] == "municipal_housing_de" and row["family"] == "municipal_housing" for row in de_body["providers"])
    assert any(row["value"] == "immoscout_de" for row in de_body["providers"])
    assert any(row["value"] == "wg_gesucht_de" and row["family"] == "shared_housing" for row in de_body["providers"])
    assert any(row["value"] == "vonovia_de" and row["family"] == "corporate_landlord" for row in de_body["providers"])
    assert any(row["value"] == "neubaukompass_de" and row["family"] == "developer_projects" for row in de_body["providers"])
    assert any(row["value"] == "auctions_de" and row["family"] == "distressed_sales" for row in de_body["providers"])
    assert any(row["value"] == "broker_direct_de" and row["family"] == "broker_direct" for row in de_body["providers"])
    assert any(row["value"] == "furnished_relocation_de" and row["family"] == "furnished_relocation" for row in de_body["providers"])
    assert any(row["value"] == "ohne_makler_de" and row["family"] == "broker_direct" for row in de_body["providers"])
    assert any(row["value"] == "von_poll_de" and row["family"] == "broker_direct" for row in de_body["providers"])

    at_body = client.get("/app/api/property/providers?country=AT").json()

    assert any(row["value"] == "public_housing_at" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "genossenschaften_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "wohnberatung_wien" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "wiener_wohnen" and row["family"] == "public_housing" for row in at_body["providers"])
    assert any(row["value"] == "gesiba_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "oesw_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "egw_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "zvginfo_at" and row["family"] == "distressed_sales" for row in at_body["providers"])
    assert any(row["value"] == "school_directories_de" for row in de_body["evidence_sources"])
    assert any(row["value"] == "statatlas_schulen_at" for row in at_body["evidence_sources"])


def test_property_provider_greenfield_api_returns_mode_aware_default_platforms() -> None:
    client = build_property_client(principal_id="exec-provider-catalog-mode-aware")

    at_buy_body = client.get(
        "/app/api/property/providers",
        params={"country": "AT", "listing_mode": "buy", "property_type": "apartment"},
    ).json()
    at_land_body = client.get(
        "/app/api/property/providers",
        params={"country": "AT", "listing_mode": "buy", "property_type": "land"},
    ).json()
    de_buy_body = client.get(
        "/app/api/property/providers",
        params={"country": "DE", "listing_mode": "buy", "property_type": "apartment"},
    ).json()

    assert at_buy_body["listing_mode"] == "buy"
    assert at_buy_body["property_type"] == "apartment"
    assert at_buy_body["default_platforms"] == [
        "willhaben",
        "immmo",
        "immoscout_at",
        "derstandard_at",
        "broker_direct_at",
        "developer_projects_at",
    ]
    assert at_land_body["default_platforms"] == [
        "willhaben",
        "immmo",
        "immoscout_at",
        "broker_direct_at",
    ]
    assert de_buy_body["default_platforms"] == [
        "core_portals_de",
        "new_build_de",
        "broker_direct_de",
        "corporate_landlords_de",
    ]


def test_austria_generated_source_defaults_use_public_and_cooperative_lanes_for_rent() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Vienna",
        },
        selected_platforms=(),
        principal_id="exec-property-at-rent-defaults",
        default_person_id="self",
        max_results=4,
    )

    platforms = {str(row["platform"]) for row in specs}

    assert "public_housing_at" in platforms
    assert "genossenschaften_at" in platforms


def test_austria_generated_source_defaults_use_broker_and_project_lanes_for_buy() -> None:
    specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Vienna",
        },
        selected_platforms=(),
        principal_id="exec-property-at-buy-defaults",
        default_person_id="self",
        max_results=4,
    )

    platforms = {str(row["platform"]) for row in specs}

    assert "broker_direct_at" in platforms
    assert "developer_projects_at" in platforms


def test_germany_auction_sources_require_buy_or_explicit_distressed_signal_mode() -> None:
    rent_specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Berlin",
        },
        selected_platforms=("auctions_de", "zvg_de"),
        principal_id="exec-property-de-auctions-rent",
        default_person_id="self",
        max_results=3,
    )
    distressed_specs = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Berlin",
            "include_distressed_sale_signals": True,
        },
        selected_platforms=("auctions_de",),
        principal_id="exec-property-de-auctions-distressed",
        default_person_id="self",
        max_results=3,
    )

    assert rent_specs == ()
    assert distressed_specs
    assert all(str(row["listing_mode"]) == "buy" for row in distressed_specs)


def test_property_search_location_matching_accepts_generic_provider_scope_location() -> None:
    hints = _property_search_location_hints({"country_code": "CR", "region_code": "puntarenas", "location_query": "Monteverde"})
    facts = product_service._property_facts_with_source_scope(
        facts={"provider_channel": "re_cr_mls"},
        source_url="https://re.cr/en/search?country=CR&q=Monteverde",
        source_label="RE.cr Costa Rica MLS | Costa Rica | Buy | Monteverde",
    )

    assert facts["source_scope_location"] == "Monteverde"
    assert facts["source_city"] == "Monteverde"
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://re.cr/en/listing/sparse-card",
        title="Mountain view home",
        summary="Sparse provider card.",
        property_facts=facts,
        country_code="CR",
        region_code="puntarenas",
    ) is True


def test_property_search_location_matching_rejects_concrete_cr_location_conflict() -> None:
    hints = _property_search_location_hints({"country_code": "CR", "region_code": "puntarenas", "location_query": "Monteverde"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.re.cr/en/real-estate/heredia-costa-rica",
        title="Properties for sale and for rent in Heredia, Costa Rica",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.realtor.com/international/cr/limon-talamanca-puerto-viejo-limon-310108049873/",
        title="Limón Talamanca Puerto Viejo, Limon 70403 Apartment for Sale",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.re.cr/en/real-estate/lake-arenal",
        title="Lake Arenal Real Estate",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.realtor.com/international/cr/bella-vista-nuevo-arenal-lake-arenal-guanacaste-310101836907/",
        title="Bella Vista Nuevo Arenal Lake Arenal Guanacaste House for Sale",
        summary="Provider result page was queried from a Monteverde source scope.",
        property_facts={"source_scope_location": "Monteverde", "source_city": "Monteverde", "country_code": "CR", "region_code": "puntarenas"},
        country_code="CR",
        region_code="puntarenas",
    ) is False


def test_property_search_location_matching_rejects_source_scope_postal_conflict() -> None:
    hints = _property_search_location_hints({"location_query": "1020 Vienna, 1030 Vienna, Wien"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/object?adId=2098041582",
        title="Neubau 2 Zimmer Traum mit Balkon, 51,81 m², € 1.099,-, (3400 Klosterneuburg)",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://propertyquarry.com/tours/gefrderte-2-zimmer-mietwohnung-mit-balkon-und-carport-in-jagerberg-layout-first-828b943ae4",
        title="Geförderte 2 Zimmer Mietwohnung mit Balkon und Carport in Jagerberg",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "8091 Jagerberg", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/eigentumswohnung/oberoesterreich/gmunden/wohnung-mit-seeblick",
        title="Wohnung mit Seeblick in Gmunden",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "4810 Gmunden", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/einfamilienhaus/niederoesterreich/hollabrunn/familienhaus",
        title="Familienhaus in Hollabrunn",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "2020 Hollabrunn", "source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-4020-linz",
        title="Wohnung mieten in 4020 Linz | 48.38 m² | 2 Zimmer",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "4020 Linz", "source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.immobilienscout24.at/expose/natters-top-05",
        title="Wohnhausanlage Osteräcker 01 - Natters | TOP 05",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"postal_name": "6161 Natters", "source_scope_location": "1020 Vienna", "source_city": "Vienna"},
    ) is False


def test_property_search_location_matching_rejects_non_vienna_title_even_with_vienna_source_scope() -> None:
    hints = _property_search_location_hints({"location_query": "Wien"})

    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/mietwohnungen/oberoesterreich/gmunden/seeblick",
        title="Moderne Wohnung mit Seeblick in Gmunden",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False
    assert _property_candidate_matches_requested_location(
        location_hints=hints,
        property_url="https://www.willhaben.at/iad/immobilien/d/haus/niederoesterreich/hollabrunn/familienhaus",
        title="Familienhaus in Hollabrunn mit Garten",
        summary="Provider result page was queried from a Vienna source scope.",
        property_facts={"source_scope_location": "Wien", "source_city": "Wien"},
    ) is False


def test_property_search_location_hints_ignore_broad_austria_scope() -> None:
    assert _property_search_location_hints({"location_query": "Österreich"}) == ()
    assert _property_search_location_hints({"location_query": "All Austria"}) == ()
    assert _property_search_location_hints({"location_query": "Niederösterreich"}) == ("Niederösterreich",)


def test_property_distance_gate_records_relaxed_and_unknown_distances() -> None:
    relaxed_facts = {"nearest_supermarket_m": 420}

    assert product_service._property_apply_distance_gate(
        relaxed_facts,
        request_preferences={
            "max_distance_to_supermarket_m": 200,
            "max_distance_to_supermarket_importance": "important",
        },
        preference_key="max_distance_to_supermarket_m",
        fact_key="nearest_supermarket_m",
        label="supermarket",
    ) is True
    assert relaxed_facts["distance_relaxations_json"] == [
        {"label": "supermarket", "requested_m": 200, "actual_m": 420}
    ]

    unknown_facts: dict[str, object] = {}
    assert product_service._property_apply_distance_gate(
        unknown_facts,
        request_preferences={
            "max_distance_to_playground_m": 300,
            "max_distance_to_playground_importance": "must_have",
        },
        preference_key="max_distance_to_playground_m",
        fact_key="nearest_playground_m",
        label="playground",
    ) is True
    assert unknown_facts["distance_unknowns_json"] == [
        {"label": "playground", "requested_m": 300}
    ]

    outside_facts = {"nearest_library_m": 1200}
    assert product_service._property_apply_distance_gate(
        outside_facts,
        request_preferences={
            "max_distance_to_library_m": 300,
            "max_distance_to_library_importance": "must_have",
        },
        preference_key="max_distance_to_library_m",
        fact_key="nearest_library_m",
        label="Library",
    ) is False
    assert "distance_relaxations_json" not in outside_facts


def test_property_distance_gate_can_avoid_nearby_locations() -> None:
    too_close_facts = {"nearest_shopping_center_m": 220}
    assert product_service._property_apply_distance_gate(
        too_close_facts,
        request_preferences={
            "max_distance_to_shopping_center_m": 500,
            "max_distance_to_shopping_center_importance": "avoid_nearby",
        },
        preference_key="max_distance_to_shopping_center_m",
        fact_key="nearest_shopping_center_m",
        label="shopping center",
    ) is False
    assert too_close_facts["distance_avoidances_json"] == [
        {"label": "shopping center", "requested_m": 500, "actual_m": 220}
    ]

    far_enough_facts = {"nearest_shopping_center_m": 1400}
    assert product_service._property_apply_distance_gate(
        far_enough_facts,
        request_preferences={
            "max_distance_to_shopping_center_m": 500,
            "max_distance_to_shopping_center_importance": "avoid_nearby",
        },
        preference_key="max_distance_to_shopping_center_m",
        fact_key="nearest_shopping_center_m",
        label="shopping center",
    ) is True


def test_property_search_prefetch_listing_urls_records_timings_and_errors(monkeypatch) -> None:
    def _fake_listing_urls_for_source(*, source_url: str, source_spec: dict[str, object], force_refresh: bool):
        if source_spec.get("platform") == "bad":
            raise RuntimeError("fetch_failed")
        return (("https://example.com/listing-1",), {"status": "miss"})

    monkeypatch.setattr(product_service, "_property_scout_listing_urls_for_source", _fake_listing_urls_for_source)

    prefetched = product_service._property_search_prefetch_listing_urls(
        specs=[
            {"url": "https://example.com/good", "platform": "good", "provider_family": "core_portal"},
            {"url": "https://example.com/bad", "platform": "bad", "provider_family": "core_portal"},
        ],
        force_refresh=False,
    )

    good = prefetched[("good", "https://example.com/good")]
    bad = prefetched[("bad", "https://example.com/bad")]
    assert good["listing_urls"] == ("https://example.com/listing-1",)
    assert good["provider_cache_state"]["status"] == "miss"
    assert float(good["timing_ms"]["provider_fetch"]) >= 0.0
    assert bad["error"] == "fetch_failed"
    assert float(bad["timing_ms"]["provider_fetch"]) >= 0.0


def test_property_filter_feedback_patch_disables_filter_and_reruns_search(monkeypatch) -> None:
    principal_id = "exec-property-filter-feedback-patch"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Feedback Office")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "max_distance_to_supermarket_m": 200,
            "max_distance_to_supermarket_importance": "important",
            "property_search_enabled": True,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    service = ProductService(client.app.state.container)
    prompt = service._prepare_notification_feedback_prompt(
        principal_id=principal_id,
        notification_kind="property_scout_filter_near_miss",
        person_id="self",
        domain="property_search",
        object_type="property_listing",
        object_id="https://www.willhaben.at/iad/object?adId=near-miss",
        source_ref="property-scout:near-miss",
        raw_signal_json={"failed_filter_key": "max_distance_to_supermarket_m"},
        interpreted_signal_json={},
        suggestion_options=[
            {
                "key": "disable_max_distance_to_supermarket_m",
                "label": "Disable supermarket radius",
                "event_type": "property_filter_disable_requested",
                "reply_text": "Noted. I disabled that one search filter and started a fresh search.",
                "property_search_preference_patch": {"max_distance_to_supermarket_m": None},
                "property_search_rerun": True,
            }
        ],
    )
    service._record_notification_feedback_prompt(
        principal_id=principal_id,
        prompt=prompt,
        delivery_channel="telegram",
        telegram_chat_ref="42",
        telegram_message_ids=["77"],
    )
    observed: dict[str, object] = {}

    def _fake_sync_direct_property_scout(
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
        observed["actor"] = actor
        observed["force_refresh"] = force_refresh
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {"status": "processed", "listing_total": 2}

    monkeypatch.setattr(service, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    result = service.record_notification_feedback(
        principal_id=principal_id,
        notification_key=str(prompt["notification_key"]),
        feedback_key="disable_max_distance_to_supermarket_m",
        actor="telegram_test",
        chat_id="42",
    )

    assert result["status"] == "recorded"
    assert result["property_search_preference_patch_status"] == "patched"
    assert result["property_search_rerun_status"] == "processed"
    assert observed["principal_id"] == principal_id
    assert observed["actor"] == "telegram_filter_feedback"
    assert observed["force_refresh"] is True
    updated = client.app.state.container.onboarding.status(principal_id=principal_id)["property_search_preferences"]
    raw = updated["raw_preferences"]
    assert raw["max_distance_to_supermarket_m"] is None
    assert raw["max_distance_to_supermarket_importance"] == "nice_to_have"


def test_property_filter_feedback_patch_ignores_unsupported_keys() -> None:
    principal_id = "exec-property-filter-feedback-unsupported"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Unsupported Office")
    service = ProductService(client.app.state.container)

    result = service._apply_property_search_feedback_patch(
        principal_id=principal_id,
        patch={"selected_platforms": [], "max_distance_to_playground_m": None},
    )

    assert result["status"] == "patched"
    assert result["patched_keys"] == ["max_distance_to_playground_m"]
    updated = client.app.state.container.onboarding.status(principal_id=principal_id)["property_search_preferences"]
    assert updated["raw_preferences"]["max_distance_to_playground_m"] is None
    assert "selected_platforms" not in updated["raw_preferences"]


def test_property_filter_near_miss_feedback_buttons_fit_telegram_callback_limit(monkeypatch) -> None:
    principal_id = "exec-property-filter-near-miss-buttons"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Button Office")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    service = ProductService(client.app.state.container)
    sent: dict[str, object] = {}

    def _fake_send_telegram_message_for_principal(*args, **kwargs):
        sent.update(kwargs)
        return SimpleNamespace(chat_id="1354554303", message_ids=("7",))

    monkeypatch.setattr(product_service, "send_telegram_message_for_principal", _fake_send_telegram_message_for_principal)

    result = service._send_property_scout_filter_near_miss_telegram(
        principal_id=principal_id,
        actor="test",
        title="Near miss apartment",
        summary="Strong candidate",
        counterparty="Willhaben",
        property_url="https://www.willhaben.at/iad/object?adId=near-miss",
        source_ref="property-scout:near-miss",
        preference_person_id="self",
        failed_filter_key="max_distance_to_supermarket_m",
        failed_filter_label="supermarket radius",
        prefilter_score=86.0,
    )

    assert result["status"] == "sent"
    inline_buttons = list(sent["inline_buttons"])
    callback_values = [
        str(callback_data)
        for row in inline_buttons
        for _label, callback_data in row
    ]
    assert callback_values
    assert all(len(value.encode("utf-8")) <= 64 for value in callback_values)
    assert any("|df_super|" in value for value in callback_values)
    assert any("|kf_super|" in value for value in callback_values)


def test_property_filter_near_miss_sender_suppresses_location_conflicts(monkeypatch) -> None:
    principal_id = "exec-property-filter-near-miss-location-sender"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Filter Location Gate Office")
    monkeypatch.setenv(
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        json.dumps({"default": {"token": "telegram-token", "handle": "tibor_concierge_bot"}}),
    )
    client.app.state.container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name="telegram_identity",
        external_account_ref="1354554303",
        auth_metadata_json={"default_chat_ref": "1354554303", "bot_key": "default", "bot_handle": "tibor_concierge_bot"},
        scope_json={"assistant_surfaces": ["dm"]},
        status="enabled",
    )
    service = ProductService(client.app.state.container)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        product_service,
        "send_telegram_message_for_principal",
        lambda *args, **kwargs: sent.append(dict(kwargs)) or SimpleNamespace(chat_id="1354554303", message_ids=("7",)),
    )

    result = service._send_property_scout_filter_near_miss_telegram(
        principal_id=principal_id,
        actor="test",
        title="Wohnung mieten in 4020 Linz | 48.38 m2 | 2 Zimmer",
        summary="Outside Vienna.",
        counterparty="DER STANDARD Immobilien | Austria | Buy | 1020 Vienna",
        property_url="https://immobilien.derstandard.at/detail/wohnung-mieten-in-4020-linz",
        source_ref="property-scout:linz-near-miss",
        preference_person_id="self",
        failed_filter_key="min_area_m2",
        failed_filter_label="minimum area",
        prefilter_score=86.0,
        requested_location_hints=("1020 Vienna",),
        requested_country_code="AT",
        requested_region_code="vienna",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert sent == []


def test_property_search_sparse_auction_floorplan_area_scores_above_review_threshold() -> None:
    preview = {
        "title": "BG Leopoldstadt, 082 25 E 89/25g",
        "summary": "Sparse judicial auction detail page.",
        "property_facts_json": {
            "area_sqm": 126.59,
            "floorplan_count": 1,
            "floorplan_urls_json": ["https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/0/example/$file/Gutachten.pdf"],
            "provider_channel": "justiz_edikte_at",
            "sale_channel": "judicial_auction",
            "source_scope_location": "1020 Vienna",
        },
    }
    assessment = {
        "fit_score": 47.96,
        "upstream_personalization": {"adjusted_fit_score": 45.46},
    }

    score = product_service._property_scout_rank_score(
        property_url="https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/alldoc/example!OpenDocument",
        assessment=assessment,
        preview=preview,
        ordinal=6,
    )

    assert score >= 54.0


def test_property_search_type_filter_blocks_garage_for_residential_searches() -> None:
    garage_title = "Garagenplatz zu vermieten, 10 m2, EUR 190,-, (1030 Wien) - willhaben"

    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/object?adId=1835567057",
            title=garage_title,
            summary="Garagenplatz zu vermieten.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="house",
            property_url="https://www.willhaben.at/iad/object?adId=1835567057",
            title=garage_title,
            summary="Garagenplatz zu vermieten.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/object?adId=1",
            title="Wohnung mit Balkon und optionalem Garagenplatz",
            summary="Helle Wohnung, Lift, Terrasse, Garagenplatz optional anmietbar.",
            property_facts={"property_type": "apartment"},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="office",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="apartment",
            property_url="https://www.willhaben.at/iad/immobilien/d/gewerbeimmobilien/buero",
            title="Bürofläche mit Balkon nahe U-Bahn",
            summary="Gewerbefläche mit Teeküche, Besprechungszimmern und Lift.",
            property_facts={"property_type": "office"},
        )
        is False
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="any",
            property_url="https://www.immmo.at/expose/praxis",
            title="Großzügige Praxisfläche in gepflegtem Zustand",
            summary="Ideal für medizinische Nutzung.",
            property_facts={},
        )
        is False
    )


def test_property_search_type_filter_supports_building_land() -> None:
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="land",
            property_url="https://www.willhaben.at/iad/object?adId=land-one",
            title="Baugrundstück mit Seezugang in Niederösterreich",
            summary="Bauland, aufgeschlossen, ruhige Lage.",
            property_facts={},
        )
        is True
    )
    assert (
        product_service._property_candidate_matches_requested_property_type(
            property_type="land",
            property_url="https://www.willhaben.at/iad/object?adId=flat-one",
            title="Wohnung mit Garten und Balkon",
            summary="Helle Wohnung, kein Baugrund.",
            property_facts={"property_type": "apartment"},
        )
        is False
    )


def test_property_scout_listing_url_cache_reuses_provider_result_lists(monkeypatch) -> None:
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "memory")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", "")
    fetch_calls: list[str] = []

    def _fake_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        fetch_calls.append(url)
        return "<html>provider source</html>"

    def _fake_extract_listing_urls(
        *,
        source_url: str,
        html: str,
        source_spec: dict[str, object] | None = None,
    ) -> tuple[str, ...]:
        return (
            "https://www.willhaben.at/iad/object?adId=cache-1",
            "https://www.willhaben.at/iad/object?adId=cache-2",
        )

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(product_service, "_property_scout_extract_listing_urls", _fake_extract_listing_urls)
    source_spec = {
        "platform": "willhaben",
        "provider_cache_key": "willhaben:test-cache-key",
        "provider_filter_pushdown": {"cache_key": "willhaben:test-cache-key"},
    }

    first_urls, first_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
    )
    second_urls, second_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
    )
    refreshed_urls, refreshed_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=80",
        source_spec=source_spec,
        force_refresh=True,
    )

    assert first_cache["status"] == "miss"
    assert second_cache["status"] == "hit"
    assert refreshed_cache["status"] == "refresh"
    assert first_urls == second_urls == refreshed_urls
    assert len(fetch_calls) == 2


def test_property_scout_listing_url_cache_persists_provider_result_lists(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")
    fetch_calls: list[str] = []

    def _fake_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        fetch_calls.append(url)
        return "<html>provider source</html>"

    def _fake_extract_listing_urls(
        *,
        source_url: str,
        html: str,
        source_spec: dict[str, object] | None = None,
    ) -> tuple[str, ...]:
        return (
            "https://www.willhaben.at/iad/object?adId=persist-1",
            "https://www.willhaben.at/iad/object?adId=persist-2",
        )

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _fake_fetch_html)
    monkeypatch.setattr(product_service, "_property_scout_extract_listing_urls", _fake_extract_listing_urls)
    source_spec = {
        "platform": "willhaben",
        "provider_cache_key": "willhaben:persistent-cache-key",
        "provider_filter_pushdown": {"cache_key": "willhaben:persistent-cache-key"},
    }

    first_urls, first_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=90",
        source_spec=source_spec,
    )
    assert first_cache["status"] == "miss"
    assert first_cache["persistence"] == "file"
    assert cache_path.exists()

    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0

    def _blocked_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        raise AssertionError("persistent provider-list cache should satisfy this request")

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _blocked_fetch_html)
    second_urls, second_cache = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=90",
        source_spec=source_spec,
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert persisted["version"] == "property_source_listing_cache_v1"
    assert persisted["schema_version"] == 1
    assert persisted["entry_count"] == 1
    assert persisted["lock_strategy"] == "fcntl"
    assert "willhaben:persistent-cache-key" in persisted["entries"]
    assert cache_path.with_name(f"{cache_path.name}.lock").exists()
    assert second_cache["status"] == "hit"
    assert second_cache["persistence"] == "file"
    assert second_urls == first_urls
    assert len(fetch_calls) == 1


def test_property_scout_listing_url_cache_uses_source_fallback_when_provider_fetch_fails(monkeypatch) -> None:
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "memory")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", "")
    observed: dict[str, object] = {}

    def _blocked_fetch_html(url: str, *, timeout_seconds: float = 60.0) -> str:
        observed["timeout_seconds"] = timeout_seconds
        raise TimeoutError("remax upstream timeout")

    monkeypatch.setattr(product_service, "_property_scout_fetch_html", _blocked_fetch_html)
    source_spec = {
        "platform": "remax_at",
        "provider_cache_key": "remax_at:fallback-cache-key",
        "provider_filter_pushdown": {"cache_key": "remax_at:fallback-cache-key"},
        "fetch_timeout_seconds": 8,
        "fallback_listing_urls": ["https://www.remax.at/de/ib/remax-first-wien/immobilien"],
    }

    urls, cache_state = product_service._property_scout_listing_urls_for_source(
        source_url="https://www.remax.at/en/properties/propertysearch?q=Wien&minArea=35",
        source_spec=source_spec,
        force_refresh=True,
    )

    assert observed["timeout_seconds"] == 8
    assert urls == ("https://www.remax.at/de/ib/remax-first-wien/immobilien",)
    assert cache_state["status"] == "fallback"
    assert cache_state["fallback_reason"] == "source_fetch_failed"


def test_property_scout_listing_url_cache_merges_existing_persistent_entries(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": "property_source_listing_cache_v1",
                "entries": {
                    "willhaben:other-worker-key": {
                        "cache_key": "willhaben:other-worker-key",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen?q=other",
                        "listing_urls": ["https://www.willhaben.at/iad/object?adId=other-1"],
                        "stored_at_epoch": time.time(),
                        "provider_filter_pushdown": {"cache_key": "willhaben:other-worker-key"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")

    product_service._property_source_listing_cache_put(
        "willhaben:this-worker-key",
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?q=this",
        listing_urls=("https://www.willhaben.at/iad/object?adId=this-1",),
        source_spec={"provider_filter_pushdown": {"cache_key": "willhaben:this-worker-key"}},
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "willhaben:other-worker-key" in persisted["entries"]
    assert "willhaben:this-worker-key" in persisted["entries"]
    assert persisted["entry_count"] == 2


def test_property_scout_listing_url_cache_quarantines_corrupt_persistent_snapshot(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text("{not valid json", encoding="utf-8")
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")

    product_service._property_source_listing_cache_put(
        "willhaben:recovered-cache-key",
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?q=recovered",
        listing_urls=("https://www.willhaben.at/iad/object?adId=recovered-1",),
        source_spec={"provider_filter_pushdown": {"cache_key": "willhaben:recovered-cache-key"}},
    )

    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    corrupt_files = sorted(tmp_path.glob("provider-listings.json.corrupt-*.json"))
    assert corrupt_files
    assert persisted["version"] == "property_source_listing_cache_v1"
    assert persisted["schema_version"] == 1
    assert persisted["lock_strategy"] == "fcntl"
    assert "willhaben:recovered-cache-key" in persisted["entries"]


def test_property_scout_listing_url_cache_rejects_overstale_persistent_fallback(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "provider-listings.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": "property_source_listing_cache_v1",
                "entries": {
                    "willhaben:old-cache-key": {
                        "cache_key": "willhaben:old-cache-key",
                        "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
                        "listing_urls": ["https://www.willhaben.at/iad/object?adId=old-1"],
                        "stored_at_epoch": time.time() - 3600,
                        "provider_filter_pushdown": {"cache_key": "willhaben:old-cache-key"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "file")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_PATH", str(cache_path))
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "1")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "60")

    cached_urls, cached_state = product_service._property_source_listing_cache_get(
        "willhaben:old-cache-key",
        allow_stale=True,
    )

    assert cached_urls == ()
    assert cached_state == {}


def test_hosted_property_tour_bundle_reuses_existing_manifest(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    title = "Reusable listing"
    listing_id = "reuse-1"
    property_url = "https://www.willhaben.at/iad/object?adId=reuse-1"
    variant_key = "layout_first"
    slug = product_service._hosted_property_tour_slug(
        title=title,
        listing_id=listing_id,
        property_url=property_url,
        variant_key=variant_key,
    )
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "floorplan-01.pdf").write_bytes(b"%PDF-1.4\n")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "creation_mode": "hosted_floorplan_tour",
                "scenes": [{"asset_relpath": "floorplan-01.pdf", "role": "floorplan"}],
            }
        ),
        encoding="utf-8",
    )

    def _blocked_download(*args, **kwargs) -> str:
        raise AssertionError("existing hosted tour should not download assets again")

    monkeypatch.setattr(product_service, "_download_public_tour_asset_with_type", _blocked_download)

    payload = product_service._write_hosted_floorplan_property_tour_bundle(
        principal_id="exec-reuse",
        title=title,
        listing_id=listing_id,
        property_url=property_url,
        variant_key=variant_key,
        floorplan_urls=("https://cdn.example.com/floorplan.pdf",),
        property_facts_json={},
        source_host="willhaben.at",
    )

    assert payload["tour_cache_status"] == "existing"
    assert str(payload["hosted_url"]).endswith(f"/{slug}")


def test_property_alert_review_reuses_returned_review_packet() -> None:
    principal_id = "exec-property-review-packet-reuse"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Reuse Office")
    seed_product_state(client, principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    property_url = "https://www.willhaben.at/iad/object?adId=reuse-returned-1"

    first = service._open_property_alert_review(
        principal_id=principal_id,
        title="Reusable returned review flat",
        summary="A completed review packet should remain reusable.",
        source_ref="property-scout:reuse-returned-1",
        external_id=property_url,
        counterparty="Willhaben",
        account_email="",
        property_url=property_url,
        actor="test",
        notify_telegram=False,
        personal_fit_assessment={"fit_score": 76.0, "recommendation": "shortlist"},
        preference_person_id="self",
        tour_url="https://propertyquarry.com/tours/reuse-returned-1",
    )
    task_id = str(first["human_task_id"]).split(":", 1)[1]
    returned = client.app.state.container.orchestrator.return_human_task(
        task_id,
        principal_id=principal_id,
        operator_id="operator-office",
        resolution="reviewed",
        returned_payload_json={"resolution": "reviewed"},
        provenance_json={"source": "test"},
    )
    assert returned is not None
    assert returned.status == "returned"

    second = service._open_property_alert_review(
        principal_id=principal_id,
        title="Reusable returned review flat",
        summary="Same listing in a later search.",
        source_ref="property-scout:reuse-returned-1",
        external_id=property_url,
        counterparty="Willhaben",
        account_email="",
        property_url=property_url,
        actor="test",
        notify_telegram=False,
        personal_fit_assessment={"fit_score": 78.0, "recommendation": "shortlist"},
        preference_person_id="self",
        tour_url="https://propertyquarry.com/tours/reuse-returned-1-refresh",
    )

    all_reviews = [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]
    assert second["status"] == "existing"
    assert second["human_task_id"] == first["human_task_id"]
    assert second["review_task_status"] == "returned"
    assert second["review_reused"] is True
    assert second["tour_url"] == "https://propertyquarry.com/tours/reuse-returned-1-refresh"
    assert len(all_reviews) == 1
    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_reused"})
    assert events.status_code == 200
    reused_events = [
        item
        for item in events.json()["items"]
        if item["payload"]["human_task_id"] == first["human_task_id"]
    ]
    assert reused_events
    assert reused_events[0]["payload"]["review_task_status"] == "returned"


def test_property_alert_review_suppresses_candidate_outside_active_location() -> None:
    principal_id = "exec-property-alert-location-gate"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Review Location Gate Office")
    seed_product_state(client, principal_id=principal_id)
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "flatbee"],
            "property_search_enabled": True,
        },
    )
    assert stored.status_code == 200, stored.text
    service = product_service.build_product_service(client.app.state.container)

    result = service._open_property_alert_review(
        principal_id=principal_id,
        title="Familienfreundliche 3-Zimmer-Wohnung im Zentrum von Gmunden",
        summary="Provider result was queried from a Vienna source scope.",
        source_ref="property-scout:https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
        external_id="flatbee-gmunden",
        counterparty="Flatbee",
        account_email="",
        property_url="https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
        actor="test",
        notify_telegram=True,
        candidate_properties=(
            {
                "property_url": "https://www.flatbee.at/properties/searchengine_property_detail/d05ee215-Gmunden",
                "listing_title": "Familienfreundliche 3-Zimmer-Wohnung im Zentrum von Gmunden - Oberösterreich - 4810",
                "property_facts_json": {"postal_name": "4810 Gmunden", "source_scope_location": "Wien", "source_city": "Wien"},
            },
        ),
        personal_fit_assessment={"fit_score": 92.0, "recommendation": "shortlist"},
        preference_person_id="self",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "property_location_conflicts_with_active_search"
    assert not [
        task
        for task in client.app.state.container.orchestrator.list_human_tasks(
            principal_id=principal_id,
            status=None,
            limit=20,
        )
        if task.task_type == "property_alert_review"
    ]
    events = client.get("/app/api/events", params={"channel": "product", "event_type": "property_alert_review_suppressed_location_mismatch"})
    assert events.status_code == 200
    assert any("Gmunden" in str(item["payload"]) for item in events.json()["items"])


def test_property_search_run_status_reconstructs_missing_status_url() -> None:
    principal_id = "exec-property-search-missing-status-url"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"legacy-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "in_progress",
            "status_url": "",
            "selected_platforms": ["willhaben"],
            "progress": 25,
            "current_step": "source_started",
            "message": "Scanning source.",
            "stages_total": 4,
            "steps_completed": 1,
            "summary": {"sources_total": 1},
            "events": [],
            "property_search_preferences": {},
        }

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status_url"] == f"/app/api/signals/property/search/run/{run_id}"


def test_property_search_run_progress_stays_monotonic_when_stage_totals_expand() -> None:
    principal_id = "exec-property-search-progress-monotonic"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"progress-{uuid.uuid4().hex}"
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["willhaben"],
            "progress": 41,
            "current_step": "source_previewing",
            "message": "Reviewing candidate 4 of 31.",
            "stages_total": 120,
            "steps_completed": 49,
            "summary": {
                "sources_total": 10,
                "sources": [{"source_label": f"Source {index}"} for index in range(4)],
            },
            "events": [],
            "property_search_preferences": {},
            "eta_seconds": 0,
            "eta_label": "",
            "eta_seconds_smoothed": 0,
        }

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="source_extracting",
        message="Extracting listing candidates from the next source.",
        status="in_progress",
        steps_delta=1,
        summary_updates={"sources_total": 10},
        stages_total_override=220,
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status is not None
    assert int(status["progress"]) >= 41
    assert str(status.get("eta_label") or "").startswith("about") or str(status.get("eta_label") or "").startswith("under")


def test_property_search_run_progress_records_sources_completed_and_eta_summary() -> None:
    principal_id = "exec-property-search-progress-eta"
    client = build_property_client(principal_id=principal_id)
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"progress-{uuid.uuid4().hex}"
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=18)).isoformat()
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": "in_progress",
            "status_url": f"/app/api/signals/property/search/run/{run_id}",
            "selected_platforms": ["immowelt_at"],
            "progress": 0,
            "current_step": "sources_resolved",
            "message": "Resolved 6 source(s) for scanning.",
            "stages_total": 120,
            "steps_completed": 2,
            "summary": {
                "sources_total": 6,
                "sources": [{"source_label": "Source A"}, {"source_label": "Source B"}],
            },
            "events": [],
            "property_search_preferences": {},
            "eta_seconds": 0,
            "eta_label": "",
            "eta_seconds_smoothed": 0,
        }

    service._record_property_search_run_event(
        run_id=run_id,
        principal_id=principal_id,
        step="source_assessing",
        message="Enriching top 6 candidate(s) out of 31 for immowelt Austria.",
        status="in_progress",
        steps_delta=1,
        summary_updates={"sources_total": 6},
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)
    assert status is not None
    assert int(status["summary"]["sources_completed"]) == 2
    assert int(status["summary"]["eta_seconds"]) > 0
    assert str(status["summary"]["eta_label"])


def test_property_search_run_surfaces_and_updates_missing_fact_research_tasks() -> None:
    principal_id = "exec-property-search-research-queue"
    client = build_property_client(principal_id=principal_id)
    run_id = f"research-{uuid.uuid4().hex}"
    with product_service._PROPERTY_SEARCH_RUN_LOCK:
        product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = {
            "run_id": run_id,
            "principal_id": principal_id,
            "created_at": product_service._now_iso(),
            "updated_at": product_service._now_iso(),
            "status": "in_progress",
            "status_url": "",
            "selected_platforms": ["justiz_edikte_at"],
            "progress": 65,
            "current_step": "source_review_packet",
            "message": "Preparing review packets.",
            "stages_total": 8,
            "steps_completed": 5,
            "summary": {
                "sources_total": 1,
                "sources": [
                    {
                        "source_label": "Justiz Edikte Auctions",
                        "top_candidates": [
                            {
                                "source_ref": "property-scout:auction-1",
                                "property_url": "https://edikte2.justiz.gv.at/example",
                                "title": "Auction apartment with floorplan",
                                "fit_score": 72.0,
                                "review_url": "/app/handoffs/human_task:auction-review",
                                "property_facts": {
                                    "has_floorplan": True,
                                    "missing_fact_research": {
                                        "status": "queued",
                                        "updated_at": "2026-06-06T01:00:00+00:00",
                                        "items": [
                                            {
                                                "field": "rooms",
                                                "label": "Rooms",
                                                "status": "research_needed",
                                                "display_value": "Rooms under research",
                                                "evidence": "Floorplan exists but no structured room count.",
                                                "ooda": {
                                                    "observe": "Room count is missing.",
                                                    "act": "Parse the downloadable floorplan bundle.",
                                                },
                                                "next_actions": ["Parse ZIP/PDF bundle.", "Run floorplan OCR."],
                                            }
                                        ],
                                    },
                                },
                            }
                        ],
                    }
                ],
            },
            "events": [],
            "property_search_preferences": {},
        }

    status = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["research_task_total"] == 1
    assert body["open_research_task_total"] == 1
    task = body["research_tasks"][0]
    assert task["field"] == "rooms"
    assert task["priority"] == "high"
    assert task["status"] == "queued"
    assert task["review_url"] == "/app/handoffs/human_task:auction-review"

    filled = client.post(
        f"/app/api/signals/property/search/run/{run_id}/research-tasks/{task['task_id']}",
        json={"action": "fill", "value": "4 rooms", "note": "Read from the valuation PDF."},
    )
    assert filled.status_code == 200, filled.text
    updated = filled.json()
    assert updated["filled_research_task_total"] == 1
    assert updated["open_research_task_total"] == 0
    updated_task = updated["research_tasks"][0]
    assert updated_task["status"] == "filled"
    assert updated_task["display_value"] == "4 rooms"
    assert updated_task["owner_note"] == "Read from the valuation PDF."
    assert any(event["step"] == "research_task_updated" for event in updated["events"])


def test_property_alert_personal_fit_snapshot_times_out_fast(monkeypatch) -> None:
    class _Profiles:
        def assess_candidate(self, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.2)
            return {"fit_score": 50}

    monkeypatch.setenv("EA_PROPERTY_ALERT_ASSESSMENT_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(
        product_service,
        "_property_alert_facts_for_url",
        lambda url: ({"postal_name": "1200 Wien"}, "listing-1"),
    )

    assessment, facts, listing_id = _property_alert_personal_fit_snapshot(
        preference_profiles=_Profiles(),
        principal_id="exec-timeout",
        person_id="self",
        property_url="https://www.willhaben.at/iad/object?adId=1",
    )

    assert assessment is None
    assert facts == {}
    assert listing_id == ""


def test_property_candidate_supports_live_tour_detects_360() -> None:
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"has_360": True}}
    ) is True
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"source_virtual_tour_url": "https://example.com/tour"}}
    ) is True
    assert product_service._property_candidate_supports_live_tour(
        {"property_facts": {"has_360": False}}
    ) is False


def test_willhaben_packet_source_virtual_tour_url_falls_back_to_attribute_map_links() -> None:
    packet = {
        "property_facts_json": {
            "attribute_map": {
                "INFOLINK/NAME": ["3D Rundgang"],
                "INFOLINK/URL": ["https://my.matterport.com/show/?m=BmVWxvZQZLq"],
                "VIRTUAL_VIEW_LINK/URL": ["https://my.matterport.com/show/?m=BmVWxvZQZLq"],
            }
        }
    }

    assert (
        product_service._willhaben_packet_source_virtual_tour_url(packet)
        == "https://my.matterport.com/show/?m=BmVWxvZQZLq"
    )


def test_property_search_run_starts_with_explicit_platform_and_tracks_progress(monkeypatch) -> None:
    principal_id = "exec-property-search-run-explicit"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Office")
    seed_product_state(client, principal_id=principal_id)

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
        observed["actor"] = actor
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        observed["force_refresh"] = bool(force_refresh)
        observed["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mock scout step",
                status="in_progress",
                steps_delta=2,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
                    "source_label": "Willhaben Rentals",
                    "preference_person_id": "self",
                    "listing_total": 1,
                    "review_created_total": 1,
                    "review_existing_total": 0,
                    "notified_total": 0,
                    "tour_created_total": 0,
                    "tour_existing_total": 0,
                    "high_fit_total": 0,
                    "watch_notified_total": 0,
                    "top_fit_score": 0.0,
                }
            ],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"preference_person_id": "elisabeth", "min_match_score": 80, "require_floorplan": True},
            "force_refresh": True,
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text

    started_body = started.json()
    run_id = started_body["run_id"]
    assert run_id
    assert started_body["selected_platforms"] == ["willhaben"]
    assert started_body["status_url"] == f"/app/api/signals/property/search/run/{run_id}"

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1
    assert status["steps_completed"] > 0
    assert status["progress"] >= 0
    assert status["principal_id"] == principal_id
    assert observed["selected_platforms"] == ("willhaben",)
    assert observed["force_refresh"] is True
    assert observed["max_results_per_source"] == 2
    assert observed["property_search_preferences"]["preference_person_id"] == "elisabeth"
    assert observed["property_search_preferences"]["min_match_score"] == 45.0
    assert observed["property_search_preferences"]["require_floorplan"] is True


def test_property_search_run_greenfield_api_wraps_legacy_signal_contract(monkeypatch) -> None:
    principal_id = "exec-property-search-run-greenfield-api"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Greenfield API")

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
        if callable(progress_callback):
            progress_callback(
                step="sources_resolved",
                message="Resolved sources for greenfield API.",
                status="in_progress",
                steps_delta=1,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
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

    started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"country_code": "AT", "min_area_m2": 80},
            "max_results_per_source": 2,
        },
    )
    assert started.status_code == 200, started.text
    body = started.json()
    run_id = body["run_id"]
    assert body["status_url"] == f"/app/api/property/search-runs/{run_id}"

    latest: dict[str, object] = {}
    for _ in range(120):
        status = client.get(f"/app/api/property/search-runs/{run_id}")
        assert status.status_code == 200, status.text
        latest = status.json()
        if latest["status"] == "processed":
            break
        time.sleep(0.02)
    assert latest["status"] == "processed"
    assert latest["status_url"] == f"/app/api/property/search-runs/{run_id}"

    events = client.get(f"/app/api/property/search-runs/{run_id}/events")
    assert events.status_code == 200, events.text
    events_body = events.json()
    assert events_body["run_id"] == run_id
    assert events_body["status_url"] == f"/app/api/property/search-runs/{run_id}"
    assert any(item["step"] == "sources_resolved" for item in events_body["events"])

    legacy_status = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert legacy_status.status_code == 200, legacy_status.text
    assert legacy_status.json()["status_url"] == f"/app/api/signals/property/search/run/{run_id}"


def test_property_provider_greenfield_api_returns_country_scoped_catalog() -> None:
    client = build_property_client(principal_id="exec-property-provider-greenfield-api")

    at_response = client.get("/app/api/property/providers", params={"country": "AT"})
    uk_response = client.get("/app/api/property/providers", params={"country": "UK"})
    cr_response = client.get("/app/api/property/providers", params={"country": "CR"})

    assert at_response.status_code == 200, at_response.text
    assert uk_response.status_code == 200, uk_response.text
    assert cr_response.status_code == 200, cr_response.text
    at_body = at_response.json()
    uk_body = uk_response.json()
    cr_body = cr_response.json()
    assert at_body["country_code"] == "AT"
    assert cr_body["country_code"] == "CR"
    assert any(row["value"] == "willhaben" for row in at_body["providers"])
    assert any(row["value"] == "immowelt_at" and "immowelt" in row["label"].lower() for row in at_body["providers"])
    assert any(row["value"] == "findmyhome_at" and "FindMyHome" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "derstandard_at" and "STANDARD" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "remax_at" and "RE/MAX Austria" in row["label"] for row in at_body["providers"])
    assert any(row["value"] == "wag_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "heimat_oesterreich_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "bwsg_at" and row["family"] == "cooperative" for row in at_body["providers"])
    assert any(row["value"] == "arwag_at" and row["family"] == "developer_projects" for row in at_body["providers"])
    assert any(row["value"] == "raiffeisen_wohnbau_at" and row["family"] == "developer_projects" for row in at_body["providers"])
    assert all("Willhaben" not in row["label"] for row in uk_body["providers"])
    assert any(row["value"] == "rightmove" for row in uk_body["providers"])
    assert any(row["value"] == "encuentra24_cr" for row in cr_body["providers"])
    assert any(row["value"] == "re_cr_mls" for row in cr_body["providers"])
    assert any(row["value"] == "theagency_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "krain_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "desarrollos_cr" and row["family"] == "developer_projects" for row in cr_body["providers"])
    assert any(row["value"] == "tierraverde_cr" and row["family"] == "developer_projects" for row in cr_body["providers"])
    assert any(row["value"] == "propertiesincostarica_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "costaricarealestateservice_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])
    assert any(row["value"] == "twocostaricarealestate_cr" and row["family"] == "broker_direct" for row in cr_body["providers"])


def test_property_search_run_can_be_deleted_from_api(monkeypatch) -> None:
    principal_id = "exec-property-search-run-delete"
    client = build_property_client(principal_id=principal_id)

    def _fake_sync_direct_property_scout(self, *, principal_id: str, selected_platforms, property_search_preferences, force_refresh: bool = False):
        return {
            "summary": {
                "ranked_candidates": [],
                "sources": [],
                "sources_total": 0,
                "listing_total": 0,
            }
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/property/search-runs",
        json={
            "selected_platforms": ["willhaben"],
            "property_preferences": {"country_code": "AT"},
            "max_results_per_source": 1,
        },
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]

    deleted = client.delete(f"/app/api/property/search-runs/{run_id}")
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["run_id"] == run_id
    assert body["deleted"] is True

    missing = client.get(f"/app/api/property/search-runs/{run_id}")
    assert missing.status_code == 404, missing.text


def test_property_provider_catalog_generates_remax_austria_sources() -> None:
    rows = property_market_catalog.generated_source_specs(
        preferences={
            "country_code": "AT",
            "listing_mode": "buy",
            "location_query": "Wien",
            "min_area_m2": 70,
        },
        selected_platforms=("remax",),
        principal_id="exec-property-remax-source",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "remax_at"
    assert row["provider_family"] == "broker_direct"
    assert row["url"].startswith("https://www.remax.at/en/properties/propertysearch")
    assert "q=Wien" in row["url"]
    assert row["fetch_timeout_seconds"] == 8
    assert "https://www.remax.at/de/ib/remax-first-wien/immobilien" in row["fallback_listing_urls"]
    assert row["provider_filter_pushdown"]["applied"]["min_area_m2"] == 70


def test_property_search_run_rejects_invalid_platform_and_enforces_run_principal_scope(monkeypatch) -> None:
    principal_id = "exec-property-search-run-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Run Scope Office")

    response = client.post(
        "/app/api/signals/property/search/run",
        json={"selected_platforms": ["not-a-real-platform"]},
    )
    assert response.status_code == 400

    observed_sync: dict[str, object] = {}

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
        observed_sync["called"] = True
        observed_sync["selected_platforms"] = tuple(selected_platforms)
        observed_sync["force_refresh"] = bool(force_refresh)
        observed_sync["max_results_per_source"] = max_results_per_source
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="mocked from onboarding prefs",
                status="in_progress",
                steps_delta=3,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 1,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 1,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    owner = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 2,
            "property_commercial": {"active_plan_key": "plus", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert owner.status_code == 200, owner.text

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert observed_sync.get("called") is True
    assert set(observed_sync.get("selected_platforms") or ()) == {"willhaben", "kalandra"}

    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert status["summary"]["sources_total"] == 1

    intruder = build_property_client(principal_id="intruder-property-search-run-scope")
    intruder_status = intruder.get(f"/app/api/signals/property/search/run/{run_id}")
    assert intruder_status.status_code == 404


def test_property_search_run_requests_market_initialization_for_unsupported_country() -> None:
    principal_id = "cf-email:bootstrap.market@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Bootstrap Request Office")

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "property_preferences": {
                "country_code": "NO",
                "language_code": "en",
                "listing_mode": "buy",
                "location_query": "Oslo",
            }
        },
    )
    assert started.status_code == 200, started.text

    body = started.json()
    assert body["status"] == "initialization_required"
    assert body["run_id"] == ""
    assert body["bootstrap_required"] is True
    assert body["bootstrap_country_code"] == "NO"
    assert body["bootstrap_country_label"] == "NO"
    assert body["bootstrap_eta_hours"] == 3
    assert body["bootstrap_handoff_ref"].startswith("human_task:")
    assert body["status_url"] == ""

    handoffs = client.get("/app/api/handoffs")
    assert handoffs.status_code == 200
    bootstrap = next(item for item in handoffs.json() if item["task_type"] == "property_market_bootstrap")
    assert bootstrap["id"] == body["bootstrap_handoff_ref"]
    assert "Initialize PropertyQuarry market" in bootstrap["summary"]


def test_property_search_run_sends_results_ready_email_when_processed(monkeypatch) -> None:
    principal_id = "cf-email:results.ready@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Ready Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-1"
        accepted_at = "2026-06-04T12:00:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )
    monkeypatch.setattr(product_service.time, "sleep", lambda _seconds: None)

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
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 3,
            "review_created_total": 2,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 1,
            "tour_existing_total": 1,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [
                {
                    "source_label": "Willhaben",
                    "top_candidates": [
                        {
                            "title": "Best floorplan flat",
                            "fit_score": 88.0,
                            "fit_summary": "Personal fit 88/100",
                            "review_url": "https://propertyquarry.com/workspace-access/review-token?return_to=%2Fapp%2Fhandoffs%2Fhuman_task%3Areview-1",
                            "tour_url": "https://propertyquarry.com/tours/best-floorplan-flat",
                            "tour_status": "created",
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"selected_platforms": ["willhaben"], "property_preferences": {"country_code": "AT", "location_query": "Wien"}},
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"
    assert sent
    assert sent[0]["recipient_email"] == "results.ready@example.com"
    assert sent[0]["result_total"] == 3
    assert sent[0]["hosted_tour_total"] == 2
    assert urllib.parse.quote(f"/app/properties?run_id={run_id}", safe="/") in str(sent[0]["results_url"])
    assert sent[0]["top_properties"][0]["title"] == "Best floorplan flat"
    assert sent[0]["top_properties"][0]["review_url"].startswith("https://propertyquarry.com/workspace-access/")
    assert str(sent[0]["top_properties"][0]["review_url"]).endswith("return_to=%2Fapp%2Fhandoffs%2Fhuman_task%3Areview-1")
    assert "return_to=%2Ftours%2Fbest-floorplan-flat" in str(sent[0]["top_properties"][0]["tour_url"])


def test_property_search_results_ready_email_waits_for_tour_completion(monkeypatch) -> None:
    principal_id = "cf-email:tour.wait@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Finalization Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-2"
        accepted_at = "2026-06-04T12:05:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )
    monkeypatch.setattr(product_service.time, "sleep", lambda _seconds: None)

    poll_state = {"calls": 0}

    def _fake_latest_property_tour_event(self, *, principal_id: str, source_ref: str):  # type: ignore[no-untyped-def]
        poll_state["calls"] += 1
        if poll_state["calls"] < 2:
            return None
        return {
            "event_type": "generic_property_tour_created",
            "payload": {
                "tour_url": "https://propertyquarry.com/tours/final-tour",
                "vendor_tour_url": "https://vendor.example/tour",
            },
            "created_at": product_service._now_iso(),
        }

    monkeypatch.setattr(ProductService, "_latest_property_tour_event", _fake_latest_property_tour_event)

    service = product_service.build_product_service(client.app.state.container)
    result = {
        "status": "processed",
        "listing_total": 1,
        "sources": [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "source_ref": "property-scout:test-1",
                        "tour_status": "queued",
                        "tour_url": "",
                        "blocked_reason": "",
                        "property_facts": {"has_360": True},
                    }
                ],
            }
        ],
    }

    service._await_property_search_results_delivery_ready(
        principal_id=principal_id,
        run_id="run-final-1",
        result=result,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert sent
    assert sent[0]["hosted_tour_total"] == 1


def test_property_search_run_status_snapshot_finishes_results_email_after_restart(monkeypatch) -> None:
    principal_id = "cf-email:tour.restart@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Results Restart Office")

    sent: list[dict[str, object]] = []

    class _Receipt:
        provider = "emailit"
        message_id = "results-ready-3"
        accepted_at = "2026-06-04T12:10:00+00:00"

    monkeypatch.setattr(
        product_service,
        "send_property_search_results_ready_email",
        lambda **kwargs: sent.append(dict(kwargs)) or _Receipt(),
    )

    container = client.app.state.container
    service = product_service.build_product_service(container)
    run_id = "run-final-2"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "processed"
    state["summary"] = {
        "status": "processed",
        "listing_total": 1,
        "sources": [
            {
                "source_label": "Willhaben",
                "top_candidates": [
                    {
                        "source_ref": "property-scout:test-2",
                        "tour_status": "queued",
                        "tour_url": "",
                        "blocked_reason": "",
                        "property_facts": {"has_360": True},
                    }
                ],
            }
        ],
    }
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    monkeypatch.setattr(
        ProductService,
        "_latest_property_tour_event",
        lambda self, *, principal_id, source_ref: {
            "event_type": "generic_property_tour_created",
            "payload": {"tour_url": "https://propertyquarry.com/tours/recovered-tour"},
            "created_at": product_service._now_iso(),
        },
    )

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert sent
    assert sent[0]["hosted_tour_total"] == 1
    assert status["summary"]["ready_tour_total"] == 1


def test_property_search_run_status_marks_stale_active_run_failed(monkeypatch) -> None:
    principal_id = "cf-email:stale.run@example.com"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Stale Run Office")
    monkeypatch.setenv("EA_PROPERTY_SEARCH_RUN_STALE_SECONDS", "60")

    container = client.app.state.container
    service = product_service.build_product_service(container)
    run_id = "run-stale-1"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id=principal_id,
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "in_progress"
    state["progress"] = 1
    state["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)

    status = service.get_property_search_run_status(principal_id=principal_id, run_id=run_id)

    assert status is not None
    assert status["status"] == "failed"
    assert status["progress"] == 100
    assert status["summary"]["interrupted"] is True
    assert any(event["step"] == "run_interrupted" for event in status["events"])


def test_property_search_run_status_survives_registry_loss_via_persisted_record(monkeypatch) -> None:
    principal_id = "exec-property-search-run-persisted"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Persisted Office")

    persisted: dict[str, dict[str, object]] = {}

    def _fake_store(record: dict[str, object]) -> None:
        persisted[str(record.get("run_id") or "")] = dict(record)

    def _fake_load(*, run_id: str) -> dict[str, object] | None:
        row = persisted.get(run_id)
        return dict(row) if isinstance(row, dict) else None

    monkeypatch.setattr(product_service, "_store_property_search_run_record", _fake_store)
    monkeypatch.setattr(product_service, "_load_property_search_run_record", _fake_load)

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
        if callable(progress_callback):
            progress_callback(
                step="mock-progress",
                message="persisted status event",
                status="in_progress",
                steps_delta=2,
                summary_updates={"sources_total": 1},
            )
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"selected_platforms": ["willhaben"]})
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    status = _poll_property_search_run_status(client, run_id)
    assert status["status"] == "processed"

    product_service._PROPERTY_SEARCH_RUN_REGISTRY.pop(run_id, None)

    reloaded = client.get(f"/app/api/signals/property/search/run/{run_id}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["status"] == "processed"


def test_property_search_preferences_persist_and_merge_into_run(monkeypatch) -> None:
    principal_id = "exec-property-search-run-merge"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Merge Office")
    seed_product_state(client, principal_id=principal_id)

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "selected_platforms": ["willhaben", "kalandra"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 50,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["property_search_preferences"]["max_results_per_source"] == 50

    status_snapshot = client.get("/v1/onboarding/property-search/preferences")
    assert status_snapshot.status_code == 200
    assert set(status_snapshot.json()["property_search_preferences"]["selected_platforms"]) == {"willhaben", "kalandra"}


def test_property_search_preferences_persist_all_of_vienna_as_hard_location_scope() -> None:
    principal_id = "exec-property-search-all-vienna-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Vienna Scope")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "all_of_vienna": True,
            "location_query": "",
            "selected_platforms": ["willhaben"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )

    assert stored.status_code == 200, stored.text
    preferences = stored.json()["property_search_preferences"]
    assert preferences["country_code"] == "AT"
    assert preferences["region_code"] == "vienna"
    assert preferences["all_of_vienna"] is True
    assert preferences["location_query"] == "Vienna"


def test_property_search_preferences_normalize_country_names_before_saving() -> None:
    principal_id = "exec-property-search-country-name-scope"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Name Scope")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "Costa Rica",
            "listing_mode": "sale",
            "property_type": "land",
            "location_query": "Tamarindo",
            "selected_platforms": ["encuentra24_cr"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )

    assert stored.status_code == 200, stored.text
    preferences = stored.json()["property_search_preferences"]
    assert preferences["country_code"] == "CR"
    assert preferences["language_code"] == "es"
    assert preferences["listing_mode"] == "buy"
    assert preferences["property_type"] == "land"
    assert preferences["location_query"] == "Tamarindo"


def test_direct_property_scout_uses_saved_preferences_and_respects_disabled_flag(monkeypatch) -> None:
    principal_id = "exec-property-direct-saved-preferences"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Direct Saved Preferences")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": False,
            "alert_frequency": "disabled",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

    service = product_service.build_product_service(client.app.state.container)
    disabled = service.sync_direct_property_scout(principal_id=principal_id, actor="scheduler")

    assert disabled["status"] == "noop"
    assert disabled["noop_reason"] == "property_search_disabled"

    enabled = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert enabled.status_code == 200, enabled.text
    observed: dict[str, object] = {}

    def _fake_generated_specs(**kwargs):
        observed["preferences"] = dict(kwargs.get("preferences") or {})
        observed["selected_platforms"] = tuple(kwargs.get("selected_platforms") or ())
        return ()

    monkeypatch.setattr(product_service, "generated_property_source_specs", _fake_generated_specs)

    result = service.sync_direct_property_scout(principal_id=principal_id, actor="scheduler")

    assert result["status"] == "noop"
    assert observed["preferences"]["location_query"] == "Wien"
    assert observed["preferences"]["listing_mode"] == "rent"
    assert observed["selected_platforms"] == ()


def test_property_search_run_uses_saved_platforms_before_family_toggles(monkeypatch) -> None:
    principal_id = "exec-property-search-saved-platforms"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Saved Platforms")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "immmo", "immoscout_at", "remax_at", "kalandra", "broker_direct_at"],
            "include_broker_direct_sources": True,
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

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
        observed["selected_platforms"] = tuple(selected_platforms)
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"selected_platforms": []})
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    assert set(observed.get("selected_platforms") or ()) >= {
        "willhaben",
        "immmo",
        "immoscout_at",
        "derstandard_at",
        "remax_at",
        "kalandra",
        "broker_direct_at",
    }


def test_property_search_run_updates_active_search_agent_lifecycle(monkeypatch) -> None:
    principal_id = "exec-property-search-agent-lifecycle"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Agent Lifecycle")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "search_agent_enabled": True,
            "search_agent_notification_limit": 3,
            "search_agent_notification_period": "day",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service,
        "generated_property_source_specs",
        lambda *, preferences, selected_platforms, principal_id, default_person_id, max_results: (
            {
                "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien",
                "label": "Willhaben Vienna",
                "platform": "willhaben",
                "principal_id": principal_id,
                "preference_person_id": default_person_id,
                "notify_telegram": False,
                "max_results": 1,
            },
        ),
    )
    monkeypatch.setattr(product_service, "_property_scout_listing_urls_for_source", lambda **kwargs: ((), {"status": "miss"}))
    service = product_service.build_product_service(client.app.state.container)

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="scheduler",
        selected_platforms=("willhaben",),
        max_results_per_source=1,
        force_refresh=True,
    )

    lifecycle = dict(result.get("search_agent_lifecycle") or {})
    assert lifecycle["notification_period"] == "day"
    assert lifecycle["notification_limit"] == 3
    assert lifecycle["last_run_at"]
    assert lifecycle["next_run_at"]
    state = client.app.state.container.onboarding.status(principal_id=principal_id)
    agents = list(dict(state.get("property_search_preferences") or {}).get("search_agents") or [])
    assert agents[0]["last_run_at"] == lifecycle["last_run_at"]
    assert agents[0]["next_run_at"] == lifecycle["next_run_at"]
    assert agents[0]["sent_in_current_window"] == 0


def test_direct_property_scout_emits_timing_receipts_even_when_sources_are_empty(monkeypatch) -> None:
    principal_id = "exec-property-scout-timing"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Scout Timing")
    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_search_enabled": True,
            "alert_frequency": "daily",
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text
    monkeypatch.setattr(
        product_service,
        "_merged_property_scout_source_specs",
        lambda **kwargs: [
            {
                "url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien",
                "label": "Willhaben Vienna",
                "platform": "willhaben",
                "provider_family": "core_portal",
                "principal_id": principal_id,
                "preference_person_id": "self",
                "notify_telegram": False,
                "max_results": 1,
            }
        ],
    )
    monkeypatch.setattr(
        product_service,
        "_property_scout_listing_urls_for_source",
        lambda **kwargs: ((), {"status": "miss"}),
    )
    service = product_service.build_product_service(client.app.state.container)

    result = service.sync_direct_property_scout(
        principal_id=principal_id,
        actor="scheduler",
        selected_platforms=("willhaben",),
        max_results_per_source=1,
        force_refresh=True,
    )

    assert result["status"] == "processed"
    assert float(dict(result.get("timing_ms") or {}).get("run_total") or 0.0) >= 0.0
    assert float(dict(result.get("timing_ms") or {}).get("provider_fetch_total") or 0.0) >= 0.0
    assert len(result["sources"]) == 1
    assert float(dict(result["sources"][0].get("timing_ms") or {}).get("provider_fetch") or 0.0) >= 0.0


def test_property_search_run_explicit_empty_keywords_clear_saved_keywords(monkeypatch) -> None:
    principal_id = "exec-property-search-clear-keywords"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Clear Keywords")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "keywords": "supermarket nearby, underground nearby, no gas",
            "custom_keywords": "quiet, bright",
            "selected_platforms": ["willhaben"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

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
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"property_preferences": {"keywords": "", "custom_keywords": ""}},
    )
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    assert observed["property_search_preferences"]["keywords"] == ""
    assert observed["property_search_preferences"]["custom_keywords"] == ""


def test_property_search_preferences_update_preserves_existing_commercial_state(monkeypatch) -> None:
    principal_id = "pq-commercial-preserve"
    client = build_property_client(principal_id=principal_id)
    started = client.post("/v1/onboarding/start", json={"workspace_name": "Commercial Preserve", "workspace_mode": "personal"})
    assert started.status_code == 200

    seeded = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Wien",
            "selected_platforms": ["willhaben"],
            "property_commercial": {
                "status": "active",
                "active_plan_key": "agent",
                "active_until": "2099-12-31T23:59:59+00:00",
            },
        },
    )
    assert seeded.status_code == 200

    updated = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Wien",
            "selected_platforms": ["willhaben", "genossenschaften_at"],
            "investment_research_mode": "auto",
            "use_stored_feedback_preferences": False,
        },
    )
    assert updated.status_code == 200
    commercial = updated.json()["property_search_preferences"]["property_commercial"]
    assert commercial["active_plan_key"] == "agent"
    assert commercial["status"] == "active"

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
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["preference_person_id"] = str((property_search_preferences or {}).get("preference_person_id") or "").strip()
        observed["use_stored_feedback_preferences"] = bool((property_search_preferences or {}).get("use_stored_feedback_preferences"))
        observed["max_results_per_source"] = max_results_per_source
        observed["force_refresh"] = bool(force_refresh)
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={"property_preferences": {"preference_person_id": "override"}},
    )
    assert started.status_code == 200
    assert set(observed.get("selected_platforms") or ()) == {"willhaben", "genossenschaften_at"}
    assert observed.get("preference_person_id") == "override"
    assert observed.get("use_stored_feedback_preferences") is False
    assert observed.get("max_results_per_source") is None


def test_property_search_run_does_not_reapply_stale_saved_agent_area_filter(monkeypatch) -> None:
    principal_id = "exec-property-search-stale-agent-merge"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Stale Agent Merge")
    seed_product_state(client, principal_id=principal_id)

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "CR",
            "listing_mode": "buy",
            "property_type": "house",
            "location_query": "Monteverde",
            "min_area_m2": 80,
            "require_floorplan": True,
            "min_match_score": 40,
            "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
            "search_agents": [
                {
                    "agent_id": "agent-monteverde-buy",
                    "name": "Monteverde buy",
                    "country_code": "CR",
                    "listing_mode": "buy",
                    "property_type": "house",
                    "location_query": "Monteverde",
                    "min_area_m2": 80,
                    "require_floorplan": True,
                    "min_match_score": 40,
                    "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
                }
            ],
            "active_search_agent_id": "agent-monteverde-buy",
            "property_commercial": {
                "active_plan_key": "agent",
                "status": "active",
                "active_until": "2999-01-01T00:00:00+00:00",
            },
        },
    )
    assert stored.status_code == 200, stored.text

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
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post(
        "/app/api/signals/property/search/run",
        json={
            "selected_platforms": ["re_cr_mls", "realtor_com_cr"],
            "property_preferences": {
                "country_code": "CR",
                "listing_mode": "buy",
                "property_type": "house",
                "location_query": "Monteverde",
                "min_area_m2": 0,
                "require_floorplan": False,
                "min_match_score": 25,
                "search_agents": stored.json()["property_search_preferences"]["search_agents"],
                "active_search_agent_id": "agent-monteverde-buy",
                "raw_preferences": {"min_area_m2": 80},
            },
        },
    )
    assert started.status_code == 200, started.text
    _poll_property_search_run_status(client, started.json()["run_id"])

    preferences = dict(observed["property_search_preferences"])
    assert "re_cr_mls" in tuple(observed["selected_platforms"] or ())
    assert preferences.get("min_area_m2") not in {80, "80"}
    assert preferences["require_floorplan"] is False
    assert preferences["min_match_score"] == 25


def test_property_search_execution_preferences_relax_only_floorplan_for_discovery_mode() -> None:
    request_preferences, execution_policy = product_service._property_search_execution_preferences(
        {
            "search_mode": "discovery",
            "max_price_eur": 500000,
            "min_area_m2": 80,
            "require_floorplan": True,
            "floorplan_requirement_mode": "hard",
        }
    )

    assert request_preferences["search_mode"] == "discovery"
    assert request_preferences["require_floorplan"] is True
    assert request_preferences["floorplan_requirement_mode"] == "soft"
    assert request_preferences["max_price_eur"] == 500000
    assert request_preferences["min_area_m2"] == 80
    assert execution_policy["search_mode"] == "discovery"
    assert execution_policy["require_floorplan"] is True
    assert execution_policy["enforce_floorplan_filter"] is False
    assert execution_policy["discovery_relaxed_filters"] == ["require_floorplan"]


def test_property_search_effective_min_match_score_uses_discovery_floor() -> None:
    assert product_service._property_search_effective_min_match_score({"search_mode": "discovery", "min_match_score": 60}) == 1.0


def test_property_search_run_defaults_platforms_from_country_preferences(monkeypatch) -> None:
    principal_id = "exec-property-search-country-defaults"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Defaults")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "rent",
            "location_query": "London",
            "selected_platforms": [],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

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
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 1,
            "review_created_total": 1,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert set(observed.get("selected_platforms") or ()) == {"rightmove", "zoopla", "onthemarket"}
    assert observed["property_search_preferences"]["country_code"] == "UK"
    assert observed["property_search_preferences"]["location_query"] == "London"


def test_property_search_run_drops_saved_providers_from_wrong_country(monkeypatch) -> None:
    principal_id = "exec-property-search-country-provider-guard"
    client = build_property_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Country Provider Guard")

    stored = client.post(
        "/v1/onboarding/property-search/preferences",
        json={
            "country_code": "AT",
            "region_code": "vienna",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "1020 Vienna",
            "selected_platforms": ["re_cr_mls", "encuentra24_cr"],
            "property_commercial": {"active_plan_key": "agent", "status": "active", "active_until": "2999-01-01T00:00:00+00:00"},
        },
    )
    assert stored.status_code == 200, stored.text

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
        observed["selected_platforms"] = tuple(selected_platforms)
        observed["property_search_preferences"] = dict(property_search_preferences or {})
        return {
            "generated_at": product_service._now_iso(),
            "status": "processed",
            "sources_total": 1,
            "listing_total": 0,
            "review_created_total": 0,
            "review_existing_total": 0,
            "notified_total": 0,
            "tour_created_total": 0,
            "tour_existing_total": 0,
            "high_fit_total": 0,
            "watch_notified_total": 0,
            "sources": [],
        }

    monkeypatch.setattr(ProductService, "sync_direct_property_scout", _fake_sync_direct_property_scout)

    started = client.post("/app/api/signals/property/search/run", json={"property_preferences": {}})
    assert started.status_code == 200, started.text
    assert "re_cr_mls" not in observed["selected_platforms"]
    assert "encuentra24_cr" not in observed["selected_platforms"]
    assert set(observed["selected_platforms"]) >= {"willhaben", "immmo", "immoscout_at"}
    preferences = observed["property_search_preferences"]
    assert preferences["provider_country_filter_applied"] is True
    assert set(preferences["provider_country_filter_removed"]) == {"re_cr_mls", "encuentra24_cr"}


def test_reconcile_property_search_results_delivery_completes_unsent_ready_run(monkeypatch) -> None:
    client = build_property_client(principal_id="exec-property-search-reconcile")
    service = product_service.build_product_service(client.app.state.container)
    run_id = f"run-reconcile-ready-{uuid.uuid4().hex}"
    state = {
        "run_id": run_id,
        "principal_id": "exec-property-search-reconcile",
        "created_at": product_service._now_iso(),
        "updated_at": product_service._now_iso(),
        "status": "processed",
        "summary": {
            "sources_total": 1,
            "listing_total": 1,
            "eligible_tour_total": 1,
            "pending_tour_total": 0,
            "ready_tour_total": 1,
            "blocked_tour_total": 0,
            "top_candidates": [
                {
                    "title": "Ready candidate",
                    "source_ref": "source-1",
                    "listing_id": "listing-1",
                    "tour_status": "ready",
                    "tour_url": "https://propertyquarry.com/tours/ready-candidate",
                }
            ],
        },
        "events": [],
        "selected_platforms": ["willhaben"],
    }
    product_service._PROPERTY_SEARCH_RUN_REGISTRY[run_id] = dict(state)
    product_service._store_property_search_run_record(state)
    observed: dict[str, object] = {}

    def _fake_notify(self, *, principal_id: str, run_id: str, result: dict[str, object]) -> None:
        observed["principal_id"] = principal_id
        observed["run_id"] = run_id
        observed["result"] = dict(result)
        self._record_product_event(
            principal_id=principal_id,
            event_type="property_search_results_ready_email_sent",
            payload={"run_id": run_id},
            source_id=run_id,
            dedupe_key=f"{principal_id}|{run_id}|property-search-results-ready-email",
        )

    monkeypatch.setattr(ProductService, "_notify_property_search_results_ready", _fake_notify)

    summary = service.reconcile_property_search_results_delivery(
        principal_id="exec-property-search-reconcile",
        limit=10,
    )

    assert summary["attempted"] >= 1
    assert summary["finalized"] >= 1
    assert summary["emailed"] >= 1
    assert observed["principal_id"] == "exec-property-search-reconcile"
    assert observed["run_id"] == run_id


def test_property_search_results_ready_can_send_heyy_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    principal_id = "exec-property-search-heyy"
    client = build_product_client(principal_id=principal_id)
    start_workspace(client, mode="personal", workspace_name="Property Search Heyy Office", selected_channels=["whatsapp"])
    onboarding = client.app.state.container.onboarding
    state = onboarding._ensure_state(principal_id)  # noqa: SLF001
    onboarding._replace_channel_pref(  # noqa: SLF001
        state,
        "whatsapp",
        {"mode": "business", "phone_number": "+436647916419"},
        status="in_progress",
    )
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_HEYY_TEMPLATE_SEARCH_AGENT_DIGEST", "tmpl-search-digest")
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        "app.product.service.HeyyWhatsAppBridgeService.send_template",
        lambda self, **kwargs: observed.update(kwargs) or {
            "status": "sent",
            "provider": "heyy",
            "channel_id": kwargs.get("channel_id") or "",
            "message_id": "msg-search-digest-1",
            "delivery_status": "queued",
        },
    )

    service = product_service.build_product_service(client.app.state.container)
    result = service._notify_property_search_results_ready_heyy(
        principal_id=principal_id,
        run_id="run-heyy-1",
        result={
            "listing_total": 12,
            "high_fit_total": 4,
            "notification_budget_suppressed_total": 8,
            "ranked_candidates": [{"fit_score": 91.0}],
            "search_agent_lifecycle": {"agent_name": "Vienna rent watch"},
        },
    )
    assert result["status"] == "sent"
    assert observed["phone_number"] == "+436647916419"
    assert observed["template_id"] == "tmpl-search-digest"
    assert any(item.get("name") == "agent_name" and item.get("value") == "Vienna rent watch" for item in list(observed.get("variables") or []))
    assert any(item.get("name") == "top_fit_score" and item.get("value") == "91" for item in list(observed.get("variables") or []))


def test_property_search_run_postgres_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(product_service, "_PROPERTY_SEARCH_RUN_SCHEMA_READY", False)
    run_id = f"run-postgres-round-trip-{uuid.uuid4().hex}"
    state = product_service._new_property_search_run_record(
        run_id=run_id,
        principal_id="exec-property-postgres-round-trip",
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT", "location_query": "Vienna"},
        force_refresh=False,
    )
    state["status"] = "processed"
    state["progress"] = 100

    product_service._store_property_search_run_record(state)
    loaded = product_service._load_property_search_run_record(run_id=run_id)
    listed = product_service._list_property_search_run_records(limit=5, statuses=("processed",))

    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert loaded["principal_id"] == "exec-property-postgres-round-trip"
    assert loaded["property_search_preferences"]["country_code"] == "AT"
    assert any(row.get("run_id") == run_id for row in listed)


def test_property_source_listing_cache_postgres_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    db_url = str(os.environ.get("EA_TEST_PROPERTY_DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("EA_TEST_PROPERTY_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_BACKEND", "postgres")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("EA_PROPERTY_SOURCE_LISTING_CACHE_STALE_MAX_SECONDS", "3600")
    monkeypatch.setattr(product_service, "_PROPERTY_SOURCE_LISTING_CACHE_SCHEMA_READY", False)
    cache_key = f"willhaben:postgres-round-trip:{uuid.uuid4().hex}"
    listing_urls = (
        "https://www.willhaben.at/iad/object?adId=postgres-cache-1",
        "https://www.willhaben.at/iad/object?adId=postgres-cache-2",
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_PATH = ""
        product_service._PROPERTY_SOURCE_LISTING_CACHE_LOADED_MTIME = 0.0

    stored = product_service._property_source_listing_cache_put(
        cache_key,
        source_url="https://www.willhaben.at/iad/immobilien/mietwohnungen?ESTATE_SIZE%2FLIVING_AREA_FROM=85",
        listing_urls=listing_urls,
        source_spec={"provider_filter_pushdown": {"cache_key": cache_key, "min_area_m2": 85}},
    )
    with product_service._PROPERTY_SOURCE_LISTING_CACHE_LOCK:
        product_service._PROPERTY_SOURCE_LISTING_CACHE.clear()

    cached_urls, cached_state = product_service._property_source_listing_cache_get(cache_key)

    assert stored["persistence"] == "postgres"
    assert cached_urls == listing_urls
    assert cached_state["status"] == "hit"
    assert cached_state["persistence"] == "postgres"
    assert cached_state["listing_total"] == 2
