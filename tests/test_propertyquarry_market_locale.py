from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.routes.landing_property_research import (
    _property_enriched_candidate_facts,
    _property_fact_rows,
    _property_market_display_context,
    _property_rooms_display,
)
from app.services.property_locale import (
    PropertyLocaleError,
    format_market_currency,
    format_market_datetime,
    format_market_decimal,
    normalize_market_address_component,
    parse_market_decimal,
    resolve_market_locale,
    validate_market_postal_code,
)


def test_property_market_locale_is_explicit_and_does_not_cross_fallback() -> None:
    assert resolve_market_locale("AT", "de").locale == "de-AT"
    assert resolve_market_locale("DE", "de-DE").timezone == "Europe/Berlin"
    assert resolve_market_locale("CR", "es").currency_code == "CRC"

    with pytest.raises(PropertyLocaleError, match="unsupported_property_market_locale"):
        resolve_market_locale("CR", "de-DE")
    with pytest.raises(PropertyLocaleError, match="unsupported_property_market"):
        resolve_market_locale("US", "en-US")


def test_property_market_currency_and_parsing_are_locale_deterministic() -> None:
    assert parse_market_decimal("1\u00a0234,56", country_code="AT") == Decimal("1234.56")
    assert parse_market_decimal("1 234,56", country_code="CR") == Decimal("1234.56")
    assert format_market_currency("1234.5", country_code="AT", fraction_digits=2) == "€\u00a01.234,50"
    assert format_market_currency("1234.5", country_code="DE", fraction_digits=2) == "1.234,50\u00a0€"
    assert format_market_currency("1234.5", country_code="CR", fraction_digits=2) == "₡1\u00a0234,50"
    assert format_market_currency("1234.5", country_code="CR", currency_code="USD", fraction_digits=2) == "USD\u00a01\u00a0234,50"
    assert format_market_currency("-1234.5", country_code="AT", fraction_digits=2) == "-€\u00a01.234,50"
    assert format_market_currency("-1234.5", country_code="CR", fraction_digits=2) == "-₡1\u00a0234,50"

    assert format_market_decimal("1234.5", country_code="AT", fraction_digits=1) == "1\u00a0234,5"
    assert format_market_decimal("1234.5", country_code="DE", fraction_digits=1) == "1.234,5"
    assert format_market_decimal("1234.5", country_code="CR", fraction_digits=1) == "1\u00a0234,5"

    with pytest.raises(PropertyLocaleError, match="property_localized_number_invalid"):
        parse_market_decimal("1,234.56", country_code="DE")
    with pytest.raises(PropertyLocaleError, match="property_localized_number_invalid"):
        parse_market_decimal("12 34,56", country_code="CR")


def test_property_market_datetime_respects_dst_and_rejects_cross_market_timezones() -> None:
    winter = datetime(2026, 1, 19, 12, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    vienna_before_dst = datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc)
    vienna_after_dst = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)

    assert format_market_datetime(winter, country_code="AT") == "19.01.2026, 13:00"
    assert format_market_datetime(summer, country_code="AT") == "19.07.2026, 14:00"
    assert format_market_datetime(summer, country_code="DE") == "19.07.2026, 14:00"
    assert format_market_datetime(summer, country_code="CR") == "19/07/2026, 06:00 a. m."
    assert format_market_datetime(vienna_before_dst, country_code="AT") == "29.03.2026, 01:59"
    assert format_market_datetime(vienna_after_dst, country_code="AT") == "29.03.2026, 03:00"

    with pytest.raises(PropertyLocaleError, match="unsupported_property_market_timezone"):
        format_market_datetime(summer, country_code="AT", timezone_name="Europe/Berlin")
    with pytest.raises(PropertyLocaleError, match="timezone_aware"):
        format_market_datetime(datetime(2026, 7, 19, 12, 0), country_code="AT")


@pytest.mark.parametrize(
    ("country_code", "currency_code", "locale", "timezone_name", "display"),
    [
        ("AT", "EUR", "de-AT", "Europe/Vienna", "19.07.2026, 14:00"),
        ("DE", "EUR", "de-DE", "Europe/Berlin", "19.07.2026, 14:00"),
        ("CR", "CRC", "es-CR", "America/Costa_Rica", "19/07/2026, 06:00 a. m."),
    ],
)
def test_property_market_display_context_binds_visible_locale_currency_and_time(
    country_code: str,
    currency_code: str,
    locale: str,
    timezone_name: str,
    display: str,
) -> None:
    context = _property_market_display_context(
        facts={"market_country_code": country_code, "currency_code": currency_code},
        observed_at="2026-07-19T12:00:00Z",
    )

    assert context["country_code"] == country_code
    assert context["currency_code"] == currency_code
    assert context["locale"] == locale
    assert context["timezone"] == timezone_name
    assert context["updated_at_iso"] == "2026-07-19T12:00:00+00:00"
    assert context["updated_at_display"] == display


def test_property_market_display_context_never_labels_naive_or_invalid_timestamp() -> None:
    naive = _property_market_display_context(
        facts={"market_country_code": "AT"},
        observed_at="2026-07-19T12:00:00",
    )
    invalid = _property_market_display_context(
        facts={"market_country_code": "AT"},
        observed_at="not-a-timestamp",
    )

    assert naive["updated_at_display"] == ""
    assert naive["updated_at_iso"] == ""
    assert invalid["updated_at_display"] == ""
    assert invalid["updated_at_iso"] == ""


def test_property_market_display_context_uses_declared_units_before_market_default() -> None:
    market_default = _property_market_display_context(
        facts={"market_country_code": "CR"},
    )
    explicit_eur_amount = _property_market_display_context(
        facts={"market_country_code": "CR", "price_eur": 123456},
    )
    explicit_currency = _property_market_display_context(
        facts={"market_country_code": "CR", "price_eur": 123456, "currency_code": "CRC"},
    )

    assert market_default["currency_code"] == "CRC"
    assert explicit_eur_amount["currency_code"] == "EUR"
    assert explicit_currency["currency_code"] == "CRC"


def test_property_market_addresses_preserve_unicode_and_validate_postal_shapes() -> None:
    decomposed = "  Scho\u0308nbrunner   Straße  "
    assert normalize_market_address_component(decomposed) == "Schönbrunner Straße"
    assert validate_market_postal_code("1020", country_code="AT") == "1020"
    assert validate_market_postal_code("10115", country_code="DE") == "10115"
    assert validate_market_postal_code("10101", country_code="CR") == "10101"

    with pytest.raises(PropertyLocaleError, match="property_postal_code_invalid:AT"):
        validate_market_postal_code("10115", country_code="AT")


def test_property_research_fact_rows_use_explicit_market_formatting() -> None:
    facts = {
        "market_country_code": "AT",
        "currency_code": "EUR",
        "price_eur": 420000,
        "area_m2": 78.5,
        "rooms": 3.5,
        "nearest_subway_m": 1200,
    }

    rows = {row["title"]: row["detail"] for row in _property_fact_rows(facts)}

    assert rows["Price"] == "€\u00a0420.000"
    assert rows["Area"] == "78,5 m²"
    assert rows["Rooms"] == "3,5"
    assert rows["Underground"] == "1\u00a0200 m"
    assert _property_rooms_display(facts) == "3,5 rooms"


def test_property_research_facts_inherit_only_governed_explicit_market() -> None:
    localized = _property_enriched_candidate_facts(
        candidate={"title": "Apartment", "property_facts": {"price_eur": 123456}},
        preferences={"country_code": "CR"},
    )
    unsupported = _property_enriched_candidate_facts(
        candidate={"title": "Apartment", "property_facts": {"price_eur": 123456}},
        preferences={"country_code": "US"},
    )
    exact_run_market = _property_enriched_candidate_facts(
        candidate={"title": "Apartment", "property_facts": {"price_eur": 123456}},
        preferences={"country_code": "CR"},
        market_preferences={"country_code": "AT"},
    )
    missing_run_market = _property_enriched_candidate_facts(
        candidate={"title": "Apartment", "property_facts": {"price_eur": 123456}},
        preferences={"country_code": "CR"},
        market_preferences={},
    )

    assert localized["market_country_code"] == "CR"
    assert "market_country_code" not in unsupported
    assert exact_run_market["market_country_code"] == "AT"
    assert "market_country_code" not in missing_run_market
    localized_rows = {row["title"]: row["detail"] for row in _property_fact_rows(localized)}
    assert localized_rows["Price"] == "EUR\u00a0123\u00a0456"
