from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PropertyLocaleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PropertyMarketLocale:
    country_code: str
    locale: str
    currency_code: str
    timezone: str
    decimal_separator: str
    group_separator: str
    currency_group_separator: str
    currency_pattern: str
    currency_code_pattern: str
    date_pattern: str
    postal_pattern: str


# These patterns are pinned to Unicode CLDR 48.2. In particular, Austrian
# decimal grouping differs from Austrian currency grouping; collapsing them
# into one separator silently produces a German, rather than de-AT, display.
MARKET_LOCALES: dict[str, PropertyMarketLocale] = {
    "AT": PropertyMarketLocale(
        country_code="AT",
        locale="de-AT",
        currency_code="EUR",
        timezone="Europe/Vienna",
        decimal_separator=",",
        group_separator="\u00a0",
        currency_group_separator=".",
        currency_pattern="{symbol}\u00a0{amount}",
        currency_code_pattern="{symbol}\u00a0{amount}",
        date_pattern="%d.%m.%Y, %H:%M",
        postal_pattern=r"[1-9][0-9]{3}",
    ),
    "DE": PropertyMarketLocale(
        country_code="DE",
        locale="de-DE",
        currency_code="EUR",
        timezone="Europe/Berlin",
        decimal_separator=",",
        group_separator=".",
        currency_group_separator=".",
        currency_pattern="{amount}\u00a0{symbol}",
        currency_code_pattern="{amount}\u00a0{symbol}",
        date_pattern="%d.%m.%Y, %H:%M",
        postal_pattern=r"[0-9]{5}",
    ),
    "CR": PropertyMarketLocale(
        country_code="CR",
        locale="es-CR",
        currency_code="CRC",
        timezone="America/Costa_Rica",
        decimal_separator=",",
        group_separator="\u00a0",
        currency_group_separator="\u00a0",
        currency_pattern="{symbol}{amount}",
        currency_code_pattern="{symbol}\u00a0{amount}",
        date_pattern="%d/%m/%Y, %I:%M",
        postal_pattern=r"[0-9]{5}",
    ),
}

_CURRENCY_SYMBOLS_BY_LOCALE: dict[str, dict[str, str]] = {
    "de-AT": {"EUR": "€", "GBP": "£", "USD": "$"},
    "de-DE": {"EUR": "€", "GBP": "£", "USD": "$"},
    "es-CR": {"CRC": "₡"},
}


def resolve_market_locale(country_code: object, requested_locale: object = "") -> PropertyMarketLocale:
    country = str(country_code or "").strip().upper()
    spec = MARKET_LOCALES.get(country)
    if spec is None:
        raise PropertyLocaleError(f"unsupported_property_market:{country or 'missing'}")
    requested = str(requested_locale or "").strip().replace("_", "-").lower()
    if requested and requested not in {spec.locale.lower(), spec.locale.split("-", 1)[0].lower()}:
        raise PropertyLocaleError(f"unsupported_property_market_locale:{country}:{requested}")
    return spec


def _decimal_value(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PropertyLocaleError("property_number_required")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PropertyLocaleError("property_number_invalid") from exc
    if not parsed.is_finite():
        raise PropertyLocaleError("property_number_must_be_finite")
    return parsed


def parse_market_decimal(value: object, *, country_code: object, requested_locale: object = "") -> Decimal:
    spec = resolve_market_locale(country_code, requested_locale)
    raw = unicodedata.normalize("NFC", str(value or "")).strip()
    if not raw or len(raw) > 80:
        raise PropertyLocaleError("property_localized_number_invalid")
    if spec.group_separator == "\u00a0":
        # Treat keyboard space and narrow no-break space as input aliases for
        # CLDR's no-break-space grouping, while retaining the grouping shape
        # for validation instead of deleting arbitrary whitespace.
        raw = raw.replace("\u202f", "\u00a0").replace(" ", "\u00a0")
    group = re.escape(spec.group_separator)
    decimal = re.escape(spec.decimal_separator)
    pattern = rf"[+-]?(?:[0-9]+|[0-9]{{1,3}}(?:{group}[0-9]{{3}})+)(?:{decimal}[0-9]+)?"
    if not re.fullmatch(pattern, raw):
        raise PropertyLocaleError("property_localized_number_invalid")
    normalized = raw.replace(spec.group_separator, "").replace(spec.decimal_separator, ".")
    return _decimal_value(normalized)


def _format_market_decimal_with_group(
    value: object,
    *,
    spec: PropertyMarketLocale,
    group_separator: str,
    fraction_digits: int = 0,
) -> str:
    if isinstance(fraction_digits, bool) or not 0 <= int(fraction_digits) <= 6:
        raise PropertyLocaleError("property_fraction_digits_out_of_range")
    digits = int(fraction_digits)
    quantum = Decimal(1).scaleb(-digits)
    amount = _decimal_value(value).quantize(quantum, rounding=ROUND_HALF_UP)
    negative = amount < 0
    rendered = f"{abs(amount):.{digits}f}"
    integer, _, fraction = rendered.partition(".")
    groups: list[str] = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    grouped = group_separator.join(reversed(groups))
    if digits:
        grouped = f"{grouped}{spec.decimal_separator}{fraction}"
    return f"-{grouped}" if negative else grouped


def format_market_decimal(
    value: object,
    *,
    country_code: object,
    requested_locale: object = "",
    fraction_digits: int = 0,
) -> str:
    spec = resolve_market_locale(country_code, requested_locale)
    return _format_market_decimal_with_group(
        value,
        spec=spec,
        group_separator=spec.group_separator,
        fraction_digits=fraction_digits,
    )


def format_market_currency(
    value: object,
    *,
    country_code: object,
    requested_locale: object = "",
    currency_code: object = "",
    fraction_digits: int = 0,
) -> str:
    spec = resolve_market_locale(country_code, requested_locale)
    currency = str(currency_code or spec.currency_code).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise PropertyLocaleError("property_currency_code_invalid")
    amount = _format_market_decimal_with_group(
        value,
        spec=spec,
        group_separator=spec.currency_group_separator,
        fraction_digits=fraction_digits,
    )
    sign = "-" if amount.startswith("-") else ""
    unsigned_amount = amount.removeprefix("-")
    symbol = _CURRENCY_SYMBOLS_BY_LOCALE.get(spec.locale, {}).get(currency)
    pattern = spec.currency_pattern if symbol else spec.currency_code_pattern
    return f"{sign}{pattern.format(symbol=symbol or currency, amount=unsigned_amount)}"


def format_market_datetime(
    value: datetime,
    *,
    country_code: object,
    requested_locale: object = "",
    timezone_name: object = "",
) -> str:
    spec = resolve_market_locale(country_code, requested_locale)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PropertyLocaleError("property_datetime_must_be_timezone_aware")
    zone_name = str(timezone_name or spec.timezone).strip()
    if zone_name != spec.timezone:
        raise PropertyLocaleError(f"unsupported_property_market_timezone:{spec.country_code}:{zone_name}")
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise PropertyLocaleError(f"property_market_timezone_unavailable:{zone_name}") from exc
    localized = value.astimezone(zone)
    rendered = localized.strftime(spec.date_pattern)
    if spec.locale == "es-CR":
        day_period = "a. m." if localized.hour < 12 else "p. m."
        return f"{rendered} {day_period}"
    return rendered


def normalize_market_address_component(value: object) -> str:
    normalized = unicodedata.normalize("NFC", " ".join(str(value or "").split())).strip()
    if not normalized or len(normalized) > 200 or any(unicodedata.category(char) == "Cc" for char in normalized):
        raise PropertyLocaleError("property_address_component_invalid")
    return normalized


def validate_market_postal_code(value: object, *, country_code: object) -> str:
    spec = resolve_market_locale(country_code)
    postal_code = normalize_market_address_component(value)
    if not re.fullmatch(spec.postal_pattern, postal_code):
        raise PropertyLocaleError(f"property_postal_code_invalid:{spec.country_code}")
    return postal_code
