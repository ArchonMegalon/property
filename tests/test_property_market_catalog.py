from __future__ import annotations

import urllib.parse

from app.services.property_market_catalog import (
    default_language_for_country,
    default_platforms_for_country,
    generated_source_specs,
    is_supported_country_code,
    language_label,
    listing_mode_label,
    normalize_property_search_preferences,
    normalize_country_code,
    property_type_label,
    provider_options,
    provider_listing_markers_for_host,
    normalize_listing_mode,
)


def test_provider_options_are_filtered_by_country() -> None:
    germany = provider_options(country_code="DE")
    austria = provider_options(country_code="AT")
    sweden = provider_options(country_code="SE")
    costa_rica = provider_options(country_code="CR")

    assert any(row["value"] == "immoscout_de" for row in germany)
    assert any(row["value"] == "immowelt" for row in germany)
    assert any(row["value"] == "zvg_de" for row in germany)
    assert any(row["value"] == "genossenschaften_at" for row in austria)
    assert any(row["value"] == "justiz_edikte_at" for row in austria)
    assert any(row["value"] == "kronofogden_auktionstorget_se" for row in sweden)
    assert any(row["value"] == "encuentra24_cr" for row in costa_rica)
    assert any(row["value"] == "re_cr_mls" and "MLS" in row["label"] for row in costa_rica)
    assert all("Germany" in str(row.get("description") or "") for row in germany)


def test_normalize_property_search_preferences_defaults_country_and_language() -> None:
    payload = normalize_property_search_preferences({"location_query": "Berlin"})

    assert payload["country_code"] == "AT"
    assert payload["region_code"] == ""
    assert payload["language_code"] == "de"
    assert payload["listing_mode"] == "rent"
    assert payload["property_type"] == "any"
    assert payload["alert_frequency"] == "daily"
    assert payload["alert_channels"] == ["telegram"]
    assert payload["search_agent_enabled"] is False
    assert payload["search_agent_duration_days"] == 30
    assert payload["search_agent_notification_limit"] == 5
    assert payload["search_agent_notification_period"] == "day"


def test_normalize_property_search_preferences_clamps_search_agent_controls() -> None:
    payload = normalize_property_search_preferences(
        {
            "search_agent_enabled": "on",
            "search_agent_duration_days": 999,
            "search_agent_notification_limit": 999,
            "search_agent_notification_period": "week",
        }
    )

    assert payload["search_agent_enabled"] is True
    assert payload["search_agent_duration_days"] == 365
    assert payload["search_agent_notification_limit"] == 50
    assert payload["search_agent_notification_period"] == "week"


def test_normalize_property_search_preferences_scopes_all_of_vienna_backend_runs() -> None:
    payload = normalize_property_search_preferences(
        {
            "country_code": "AT",
            "region_code": "vienna",
            "all_of_vienna": "true",
            "location_query": "",
        }
    )

    assert payload["all_of_vienna"] is True
    assert payload["location_query"] == "Vienna"


def test_normalize_property_search_preferences_drops_stale_austrian_postal_codes_for_foreign_searches() -> None:
    payload = normalize_property_search_preferences(
        {
            "country_code": "CR",
            "region_code": "puntarenas",
            "location_query": "Monteverde, 1116",
            "custom_location_query": "1116",
        }
    )

    assert payload["country_code"] == "CR"
    assert payload["location_query"] == "Monteverde"
    assert payload["custom_location_query"] == ""


def test_normalize_listing_mode_accepts_sale_aliases() -> None:
    assert normalize_listing_mode("sale") == "buy"
    assert normalize_listing_mode("for-sale") == "buy"


def test_country_normalization_understands_common_country_names() -> None:
    assert normalize_country_code("Germany") == "DE"
    assert normalize_country_code("GB") == "UK"
    assert normalize_country_code("Great Britain") == "UK"
    assert normalize_country_code("United States") == "US"
    assert normalize_country_code("Costa Rica") == "CR"
    assert is_supported_country_code("Spain") is True
    assert is_supported_country_code("NO") is False


def test_generated_source_specs_use_country_platform_defaults() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "DE",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Berlin",
            "keywords": "lift balcony",
        },
        selected_platforms=(),
        principal_id="exec-property-de",
        default_person_id="self",
        max_results=4,
    )

    assert tuple(row["platform"] for row in specs[:2])[:1]
    assert specs[0]["country_code"] == "DE"
    assert specs[0]["listing_mode"] == "buy"
    assert "Berlin" in str(specs[0]["label"])
    assert "berlin" in str(specs[0]["url"]).lower()


def test_generated_source_specs_support_distressed_sale_platforms() -> None:
    sweden_specs = generated_source_specs(
        preferences={
            "country_code": "SE",
            "language_code": "sv",
            "listing_mode": "buy",
            "location_query": "Stockholm",
            "keywords": "auction repossessed",
        },
        selected_platforms=("kronofogden_auktionstorget_se", "treasury_real_property_us"),
        principal_id="exec-property-auctions",
        default_person_id="self",
        max_results=3,
    )
    us_specs = generated_source_specs(
        preferences={
            "country_code": "US",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "Florida",
        },
        selected_platforms=("treasury_real_property_us",),
        principal_id="exec-property-auctions-us",
        default_person_id="self",
        max_results=3,
    )

    assert any(str(row["platform"]) == "kronofogden_auktionstorget_se" for row in sweden_specs)
    assert any("kronofogden" in str(row["url"]).lower() for row in sweden_specs)
    assert any(str(row["platform"]) == "treasury_real_property_us" for row in us_specs)
    assert any("treasury.gov" in str(row["url"]).lower() for row in us_specs)


def test_market_labels_are_human_readable() -> None:
    assert language_label("fr", country_code="FR") == "Français"
    assert listing_mode_label("buy") == "Buy"
    assert property_type_label("house") == "House"
    assert property_type_label("land") == "Building land"


def test_generated_source_specs_support_austrian_land_searches() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "property_type": "land",
            "location_query": "Niederösterreich",
            "keywords": "baugrund seezugang",
        },
        selected_platforms=("willhaben",),
        principal_id="exec-property-land-at",
        default_person_id="self",
        max_results=4,
    )

    assert specs
    assert specs[0]["provider_filter_pushdown"]["requested"]["property_type"] == "land"
    assert "grundstuecke" in str(specs[0]["url"])
    assert "Nieder" in urllib.parse.unquote(str(specs[0]["url"]))
    assert "seezugang" in urllib.parse.unquote(str(specs[0]["url"])).lower()


def test_generated_source_specs_skip_buy_only_sources_for_rent_without_distress_signal() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
        },
        selected_platforms=("justiz_edikte_at",),
        principal_id="exec-property-rent-no-justiz",
        default_person_id="self",
        max_results=4,
    )
    distress_specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Wien",
            "include_distressed_sale_signals": True,
        },
        selected_platforms=("justiz_edikte_at",),
        principal_id="exec-property-rent-with-justiz",
        default_person_id="self",
        max_results=4,
    )

    assert specs == ()
    assert distress_specs
    assert distress_specs[0]["listing_mode"] == "buy"


def test_generated_source_specs_build_provider_specific_market_urls() -> None:
    uk_specs = generated_source_specs(
        preferences={
            "country_code": "UK",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "London",
            "min_rooms": 3,
            "max_price_eur": 950000,
        },
        selected_platforms=("rightmove", "zoopla"),
        principal_id="exec-property-uk",
        default_person_id="self",
        max_results=3,
    )
    france_specs = generated_source_specs(
        preferences={
            "country_code": "FR",
            "language_code": "fr",
            "listing_mode": "rent",
            "location_query": "Paris",
            "min_rooms": 2,
        },
        selected_platforms=("bienici",),
        principal_id="exec-property-fr",
        default_person_id="self",
        max_results=3,
    )
    netherlands_specs = generated_source_specs(
        preferences={
            "country_code": "NL",
            "language_code": "nl",
            "listing_mode": "buy",
            "location_query": "Amsterdam",
            "property_type": "house",
        },
        selected_platforms=("funda",),
        principal_id="exec-property-nl",
        default_person_id="self",
        max_results=3,
    )

    assert "searchLocation=London" in str(uk_specs[0]["url"])
    assert "q=London" in str(uk_specs[1]["url"])
    assert "price_max=950000" in str(uk_specs[1]["url"])
    assert "bienici.com/recherche/location/paris" in str(france_specs[0]["url"]).lower()
    assert "minRooms=2" in str(france_specs[0]["url"])
    assert "funda.nl/zoeken/koop/amsterdam/" in str(netherlands_specs[0]["url"]).lower()
    assert "object_type=house" in str(netherlands_specs[0]["url"])


def test_default_platforms_for_country_are_stable() -> None:
    assert default_platforms_for_country("UK") == ("rightmove", "zoopla", "onthemarket")
    assert default_platforms_for_country("PT") == ("idealista_pt", "imovirtual", "casa_sapo")
    assert default_platforms_for_country("CR") == ("encuentra24_cr", "re_cr_mls", "realtor_cr", "coldwellbanker_cr")
    assert default_platforms_for_country("AT") == ("willhaben", "immmo", "immoscout_at", "remax_at", "kalandra", "broker_direct_at", "community_signals_at", "genossenschaften_at")
    assert default_language_for_country("SE") == "sv"
    assert default_language_for_country("CR") == "es"


def test_workspace_location_options_follow_supported_country_codes() -> None:
    from app.api.routes.landing_view_models import _property_location_options, _property_region_options

    assert any(row["value"] == "London" for row in _property_location_options("UK"))
    assert any(row["value"] == "London" for row in _property_location_options("GB"))
    assert any(row["value"] == "costa_rica" for row in _property_region_options("CR"))
    assert any(row["value"] == "Costa Rica" for row in _property_location_options("CR", "costa_rica"))
    assert any(row["value"] == "Tamarindo" for row in _property_location_options("CR", "guanacaste"))
    assert any(row["value"] == "Monteverde" for row in _property_location_options("CR", "costa_rica"))
    assert any(row["value"] == "Monteverde" for row in _property_location_options("CR", "puntarenas"))
    assert any(row["value"] == "Santa Elena" for row in _property_location_options("CR", "puntarenas"))
    assert any(row["value"] == "Puerto Viejo" for row in _property_location_options("CR", "caribbean"))
    assert any(row["value"] == "canada" for row in _property_region_options("CA"))
    assert any(row["value"] == "Toronto" for row in _property_location_options("CA", "canada"))
    assert any(row["value"] == "Switzerland" for row in _property_location_options("CH", "switzerland"))


def test_workspace_preference_schema_matches_backend_categories() -> None:
    from app.api.routes.landing_view_models import _property_preference_schema

    schema = _property_preference_schema()
    categories = schema["categories"]
    constraint_keys = {row["key"] for row in categories["constraint"]["keys"]}
    soft_keys = {row["key"] for row in categories["soft_preference"]["keys"]}
    aversion_keys = {row["key"] for row in categories["aversion"]["keys"]}

    assert "require_lift" in constraint_keys
    assert "require_lift" not in soft_keys
    assert "prefer_lift" in soft_keys
    assert "avoided_districts" in aversion_keys


def test_provider_listing_markers_follow_provider_host() -> None:
    markers = provider_listing_markers_for_host("www.realtor.com")

    assert "/realestateandhomes-detail/" in markers


def test_generated_source_specs_cover_new_country_bundles() -> None:
    portugal_specs = generated_source_specs(
        preferences={
            "country_code": "PT",
            "language_code": "pt",
            "listing_mode": "buy",
            "location_query": "Lisbon",
        },
        selected_platforms=("idealista_pt", "imovirtual"),
        principal_id="exec-property-pt",
        default_person_id="self",
        max_results=3,
    )
    ireland_specs = generated_source_specs(
        preferences={
            "country_code": "IE",
            "language_code": "en",
            "listing_mode": "rent",
            "location_query": "Dublin",
        },
        selected_platforms=("daft_ie",),
        principal_id="exec-property-ie",
        default_person_id="self",
        max_results=3,
    )
    australia_specs = generated_source_specs(
        preferences={
            "country_code": "AU",
            "language_code": "en",
            "listing_mode": "buy",
            "location_query": "Sydney",
            "min_rooms": 2,
        },
        selected_platforms=("domain_au",),
        principal_id="exec-property-au",
        default_person_id="self",
        max_results=3,
    )

    assert "idealista.pt/en/comprar-casas/lisbon/" in str(portugal_specs[0]["url"]).lower()
    assert "imovirtual.com" in str(portugal_specs[1]["url"]).lower()
    assert "daft.ie/property-for-rent/dublin" in str(ireland_specs[0]["url"]).lower()
    assert "domain.com.au" in str(australia_specs[0]["url"]).lower()
    assert "suburb=Sydney" in str(australia_specs[0]["url"])


def test_generated_source_specs_cover_costa_rica_providers() -> None:
    rent_specs = generated_source_specs(
        preferences={
            "country_code": "CR",
            "language_code": "es",
            "listing_mode": "rent",
            "location_query": "Escazú",
            "keywords": "condo seguridad",
            "min_area_m2": 80,
        },
        selected_platforms=(),
        principal_id="exec-property-cr",
        default_person_id="self",
        max_results=4,
    )
    buy_specs = generated_source_specs(
        preferences={
            "country_code": "CR",
            "language_code": "es",
            "listing_mode": "buy",
            "location_query": "Tamarindo",
            "keywords": "beach house",
        },
        selected_platforms=("encuentra24", "recr", "realtorcr", "coldwellbankercr"),
        principal_id="exec-property-cr-buy",
        default_person_id="self",
        max_results=4,
    )

    assert {row["platform"] for row in rent_specs} == {"encuentra24_cr", "re_cr_mls"}
    assert any("encuentra24.com/costa-rica-en/real-estate-for-rent" in str(row["url"]) for row in rent_specs)
    assert any("Escaz" in str(row["label"]) for row in rent_specs)
    assert {row["platform"] for row in buy_specs} == {"encuentra24_cr", "re_cr_mls", "realtor_cr", "coldwellbanker_cr"}
    assert any("realtor.com/international/cr" in str(row["url"]) for row in buy_specs)
    assert all(row["country_code"] == "CR" for row in [*rent_specs, *buy_specs])


def test_generated_source_specs_allow_countrywide_costa_rica_without_target_area() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "CR",
            "language_code": "es",
            "listing_mode": "buy",
            "property_type": "land",
            "location_query": "",
            "keywords": "beach access",
        },
        selected_platforms=(),
        principal_id="exec-property-cr-countrywide",
        default_person_id="self",
        max_results=4,
    )

    assert {row["platform"] for row in specs} == {"encuentra24_cr", "re_cr_mls", "realtor_cr", "coldwellbanker_cr"}
    assert all(row["location_query"] == "" for row in specs)
    assert all(row["country_code"] == "CR" for row in specs)
    assert any("beach+access" in str(row["url"]) or "q=beach" in str(row["url"]) for row in specs)


def test_generated_source_specs_drop_stale_austrian_postal_code_from_costa_rica_urls() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "CR",
            "region_code": "puntarenas",
            "language_code": "es",
            "listing_mode": "buy",
            "location_query": "Monteverde, 1116",
            "custom_location_query": "1116",
        },
        selected_platforms=("encuentra24_cr",),
        principal_id="exec-property-cr-clean-location",
        default_person_id="self",
        max_results=3,
    )

    assert len(specs) == 1
    assert specs[0]["location_query"] == "Monteverde"
    assert "q=Monteverde" in str(specs[0]["url"])
    assert "1116" not in str(specs[0]["url"])


def test_generated_source_specs_split_multi_area_queries_into_dedicated_sources() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "1200 Vienna, 1020 Vienna, 1090",
            "keywords": "lift family",
        },
        selected_platforms=("willhaben",),
        principal_id="exec-property-at",
        default_person_id="self",
        max_results=2,
    )

    assert len(specs) == 3
    assert all(row["platform"] == "willhaben" for row in specs)
    assert [row["location_query"] for row in specs] == ["1200 Vienna", "1020 Vienna", "1090"]
    assert "q=1200+Vienna+lift+family" in str(specs[0]["url"])
    assert "q=1020+Vienna+lift+family" in str(specs[1]["url"])


def test_generated_source_specs_pushes_coarse_filters_to_willhaben() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "property_type": "apartment",
            "location_query": "1200 Vienna",
            "keywords": "lift family",
            "min_area_m2": 80,
            "min_rooms": 3,
            "max_price_eur": 2200,
            "require_floorplan": True,
        },
        selected_platforms=("willhaben",),
        principal_id="exec-property-at-pushdown",
        default_person_id="self",
        max_results=2,
    )

    assert len(specs) == 1
    url = str(specs[0]["url"])
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["q"] == ["1200 Vienna lift family"]
    assert params["ESTATE_SIZE/LIVING_AREA_FROM"] == ["80"]
    assert params["PRICE_TO"] == ["2200"]
    assert params["NO_OF_ROOMS_BUCKET"] == ["3X3"]
    pushdown = dict(specs[0]["provider_filter_pushdown"])
    assert pushdown["applied"]["min_area_m2"] == 80
    assert pushdown["applied"]["max_price_eur"] == 2200
    assert pushdown["applied"]["min_rooms"] == 3
    assert "require_floorplan" in pushdown["post_filter_only"]
    assert str(pushdown["cache_key"]).startswith("willhaben:")
    assert specs[0]["provider_cache_key"] == pushdown["cache_key"]


def test_generated_source_specs_expand_austria_cooperative_provider_group() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "rent",
            "location_query": "Vienna",
        },
        selected_platforms=("genossenschaften_at",),
        principal_id="exec-property-coops-at",
        default_person_id="self",
        max_results=3,
    )

    assert len(specs) == 6
    assert all(row["platform"] == "genossenschaften_at" for row in specs)
    assert any("gesiba.at" in str(row["url"]).lower() for row in specs)
    assert any("siedlungsunion.at" in str(row["url"]).lower() for row in specs)
    assert any("angebote.sozialbau.at" in str(row["url"]).lower() for row in specs)
    assert any("wbv-gpa.at" in str(row["url"]).lower() for row in specs)
    assert any("frieden.at" in str(row["url"]).lower() for row in specs)
    assert all("Vienna" in str(row["label"]) for row in specs)


def test_generated_source_specs_build_justiz_edikte_result_search_url() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "1090",
            "keywords": "lift family",
            "property_type": "apartment",
        },
        selected_platforms=("justiz_edikte_at",),
        principal_id="exec-property-justiz-at",
        default_person_id="self",
        max_results=3,
    )

    assert len(specs) == 1
    assert specs[0]["platform"] == "justiz_edikte_at"
    assert "suchedi?SearchView&subf=eex" in str(specs[0]["url"])
    assert "%5BVPLZ%5D=1090" in str(specs[0]["url"])
    assert "%5BBL%5D=0" in str(specs[0]["url"])


def test_generated_source_specs_use_public_fallback_for_immoscout_at_and_kalandra() -> None:
    specs = generated_source_specs(
        preferences={
            "country_code": "AT",
            "language_code": "de",
            "listing_mode": "buy",
            "location_query": "Wien",
        },
        selected_platforms=("immoscout_at", "kalandra"),
        principal_id="exec-property-at-upstreams",
        default_person_id="self",
        max_results=3,
    )

    assert len(specs) == 2
    immoscout_spec = next(row for row in specs if row["platform"] == "immoscout_at")
    kalandra_spec = next(row for row in specs if row["platform"] == "kalandra")
    assert str(immoscout_spec["url"]).startswith("https://www.immmo.at/suche/kauf")
    assert "pq_upstream=immoscout_at" in str(immoscout_spec["url"])
    assert kalandra_spec["url"] == "https://www.kalandra.at/immobiliensuche"
