from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_CACHE_VERSION = 1
_CACHE_TTL_SECONDS = 12 * 60 * 60


def _float_or_none(value: object) -> float | None:
    if value in (None, "", False):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


def _int_or_none(value: object) -> int | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    try:
        return int(round(parsed))
    except Exception:
        return None


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cache_path() -> Path:
    explicit = str(os.getenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path("/docker/property/state/property_investment_external_cache.json")


def _cache_ttl_seconds() -> int:
    raw = str(os.getenv("EA_PROPERTY_INVESTMENT_EXTERNAL_CACHE_TTL_SECONDS") or "").strip()
    if not raw:
        return _CACHE_TTL_SECONDS
    try:
        return max(60, min(int(raw), 7 * 24 * 60 * 60))
    except Exception:
        return _CACHE_TTL_SECONDS


@contextlib.contextmanager
def _cache_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass


def _load_cache() -> dict[str, object]:
    path = _cache_path()
    if not path.exists():
        return {"version": _CACHE_VERSION, "rows": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": _CACHE_VERSION, "rows": {}}
    if not isinstance(payload, dict):
        return {"version": _CACHE_VERSION, "rows": {}}
    rows = dict(payload.get("rows") or {}) if isinstance(payload.get("rows"), dict) else {}
    return {"version": _CACHE_VERSION, "rows": rows}


def _store_cache(payload: dict[str, object]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def _cache_key(*, lane: str, request_payload: dict[str, object]) -> str:
    material = json.dumps({"lane": lane, "payload": request_payload}, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cached_feed_payload(*, lane: str, request_payload: dict[str, object]) -> dict[str, object] | None:
    key = _cache_key(lane=lane, request_payload=request_payload)
    path = _cache_path()
    with _cache_lock(path):
        payload = _load_cache()
        rows = dict(payload.get("rows") or {})
        row = dict(rows.get(key) or {}) if isinstance(rows.get(key), dict) else {}
        if not row:
            return None
        try:
            stored_at = float(row.get("stored_at_epoch") or 0.0)
        except Exception:
            stored_at = 0.0
        if stored_at <= 0.0 or (time.time() - stored_at) > float(_cache_ttl_seconds()):
            return None
        data = dict(row.get("data") or {}) if isinstance(row.get("data"), dict) else {}
        return data or None


def _put_cached_feed_payload(*, lane: str, request_payload: dict[str, object], data: dict[str, object]) -> None:
    key = _cache_key(lane=lane, request_payload=request_payload)
    path = _cache_path()
    with _cache_lock(path):
        payload = _load_cache()
        rows = dict(payload.get("rows") or {})
        rows[key] = {
            "stored_at_epoch": time.time(),
            "lane": lane,
            "data": dict(data or {}),
        }
        payload["rows"] = rows
        _store_cache(payload)


def _feed_env(prefix: str, name: str) -> str:
    return str(os.getenv(f"{prefix}_{name}") or "").strip()


def _feed_url(prefix: str) -> str:
    return _feed_env(prefix, "URL")


def _feed_method(prefix: str) -> str:
    method = _feed_env(prefix, "METHOD").upper() or "GET"
    return method if method in {"GET", "POST"} else "GET"


def _feed_timeout(prefix: str) -> int:
    raw = _feed_env(prefix, "TIMEOUT_SECONDS")
    if not raw:
        return 8
    try:
        return max(2, min(int(raw), 30))
    except Exception:
        return 8


def _feed_headers(prefix: str) -> dict[str, str]:
    headers = {"User-Agent": "PropertyQuarry/1.0"}
    api_key = _feed_env(prefix, "API_KEY")
    auth_token = _feed_env(prefix, "AUTH_TOKEN")
    auth_header = _feed_env(prefix, "AUTH_HEADER") or "Authorization"
    if api_key:
        key_header = _feed_env(prefix, "API_KEY_HEADER") or "X-API-Key"
        headers[key_header] = api_key
    if auth_token:
        if auth_header.lower() == "authorization" and not auth_token.lower().startswith("bearer "):
            headers[auth_header] = f"Bearer {auth_token}"
        else:
            headers[auth_header] = auth_token
    extra_headers = _feed_env(prefix, "HEADERS_JSON")
    if extra_headers:
        try:
            parsed = json.loads(extra_headers)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if str(key).strip() and str(value).strip():
                        headers[str(key).strip()] = str(value).strip()
        except Exception:
            pass
    return headers


def _fetch_external_feed(prefix: str, request_payload: dict[str, object]) -> dict[str, object]:
    cached = _cached_feed_payload(lane=prefix, request_payload=request_payload)
    if cached:
        result = dict(cached)
        result.setdefault("source_mode", "cached_live_feed")
        return result
    url = _feed_url(prefix)
    if not url:
        return {}
    method = _feed_method(prefix)
    headers = _feed_headers(prefix)
    body = json.dumps(request_payload, ensure_ascii=True).encode("utf-8")
    request_url = url
    data: bytes | None = None
    if method == "GET":
        query = urllib.parse.urlencode(
            {
                key: value
                for key, value in request_payload.items()
                if value not in (None, "", [], {})
            },
            doseq=True,
        )
        if query:
            request_url = f"{url}{'&' if '?' in url else '?'}{query}"
    else:
        headers.setdefault("Content-Type", "application/json")
        data = body
    request = urllib.request.Request(request_url, headers=headers, data=data, method=method)
    with urllib.request.urlopen(request, timeout=_feed_timeout(prefix)) as response:
        raw = response.read().decode("utf-8", "ignore")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return {}
    result = dict(payload)
    result.setdefault("source_mode", "live_feed")
    _put_cached_feed_payload(lane=prefix, request_payload=request_payload, data=result)
    return result


def _country_tax_defaults(country_code: str) -> dict[str, object]:
    normalized = str(country_code or "").strip().upper()
    if normalized == "AT":
        return {
            "property_transfer_tax_pct": 3.5,
            "land_registry_fee_pct": 1.1,
            "annual_property_tax_pct": 0.12,
            "source_mode": "country_default",
            "source_label": "Austria fallback tax model",
        }
    if normalized == "DE":
        return {
            "property_transfer_tax_pct": 6.0,
            "land_registry_fee_pct": 0.7,
            "annual_property_tax_pct": 0.20,
            "source_mode": "country_default",
            "source_label": "Germany fallback tax model",
        }
    if normalized == "PT":
        return {
            "property_transfer_tax_pct": 6.5,
            "land_registry_fee_pct": 0.8,
            "annual_property_tax_pct": 0.35,
            "source_mode": "country_default",
            "source_label": "Portugal fallback tax model",
        }
    if normalized == "ES":
        return {
            "property_transfer_tax_pct": 8.0,
            "land_registry_fee_pct": 1.0,
            "annual_property_tax_pct": 0.45,
            "source_mode": "country_default",
            "source_label": "Spain fallback tax model",
        }
    return {
        "property_transfer_tax_pct": 5.0,
        "land_registry_fee_pct": 0.8,
        "annual_property_tax_pct": 0.25,
        "source_mode": "country_default",
        "source_label": "Generic fallback tax model",
    }


def _rent_roll_snapshot(*, snapshot: dict[str, object], feed: dict[str, object]) -> dict[str, object]:
    if feed:
        annual_rent = _float_or_none(feed.get("annual_rent_eur") or feed.get("annual_rent"))
        monthly_rent = _float_or_none(feed.get("monthly_rent_eur") or feed.get("monthly_rent"))
        if annual_rent is None and isinstance(monthly_rent, float):
            annual_rent = round(monthly_rent * 12.0, 2)
        if monthly_rent is None and isinstance(annual_rent, float):
            monthly_rent = round(annual_rent / 12.0, 2)
        return {
            "estimated_monthly_rent_eur": monthly_rent,
            "estimated_annual_rent_eur": annual_rent,
            "lease_count": _int_or_none(feed.get("lease_count") or feed.get("unit_count")),
            "vacancy_rate_pct": _float_or_none(feed.get("vacancy_rate_pct") or feed.get("vacancy_pct")),
            "rent_growth_pct": _float_or_none(feed.get("rent_growth_pct")),
            "source_mode": str(feed.get("source_mode") or "live_feed").strip() or "live_feed",
            "source_label": str(feed.get("source_label") or "Rent roll feed").strip() or "Rent roll feed",
        }
    annual_rent = _float_or_none(snapshot.get("expected_annual_rent_eur"))
    monthly_rent = _float_or_none(snapshot.get("expected_monthly_rent_eur"))
    if annual_rent is None and isinstance(monthly_rent, float):
        annual_rent = round(monthly_rent * 12.0, 2)
    if monthly_rent is None and isinstance(annual_rent, float):
        monthly_rent = round(annual_rent / 12.0, 2)
    return {
        "estimated_monthly_rent_eur": monthly_rent,
        "estimated_annual_rent_eur": annual_rent,
        "lease_count": None,
        "vacancy_rate_pct": None,
        "rent_growth_pct": None,
        "source_mode": "comp_fallback",
        "source_label": "Local rent comparable model",
    }


def _operating_cost_snapshot(*, feed: dict[str, object], facts: dict[str, object], area_sqm: float, annual_rent_eur: float | None) -> dict[str, object]:
    if feed:
        monthly = _float_or_none(feed.get("monthly_operating_costs_eur") or feed.get("monthly_costs_eur"))
        annual = _float_or_none(feed.get("annual_operating_costs_eur") or feed.get("annual_costs_eur"))
        if annual is None and isinstance(monthly, float):
            annual = round(monthly * 12.0, 2)
        if monthly is None and isinstance(annual, float):
            monthly = round(annual / 12.0, 2)
        return {
            "monthly_operating_costs_eur": monthly,
            "annual_operating_costs_eur": annual,
            "operating_cost_ratio_pct": _float_or_none(feed.get("operating_cost_ratio_pct")),
            "source_mode": str(feed.get("source_mode") or "live_feed").strip() or "live_feed",
            "source_label": str(feed.get("source_label") or "Operating cost feed").strip() or "Operating cost feed",
        }
    listed_monthly = _float_or_none(
        facts.get("operating_costs_monthly")
        or facts.get("operating_costs_monthly_eur")
        or facts.get("betriebskosten_monatlich_eur")
    )
    if isinstance(listed_monthly, float) and listed_monthly > 0.0:
        annual = round(listed_monthly * 12.0, 2)
        ratio = round((annual / annual_rent_eur) * 100.0, 1) if isinstance(annual_rent_eur, float) and annual_rent_eur > 0.0 else None
        return {
            "monthly_operating_costs_eur": listed_monthly,
            "annual_operating_costs_eur": annual,
            "operating_cost_ratio_pct": ratio,
            "source_mode": "listing_fact",
            "source_label": "Listing operating costs",
        }
    fallback_per_sqm = _float_or_none(os.getenv("EA_PROPERTY_OPERATING_COST_FALLBACK_EUR_PER_SQM_MONTH")) or 2.7
    monthly = round(max(area_sqm, 0.0) * fallback_per_sqm, 2) if area_sqm > 0.0 else None
    annual = round(monthly * 12.0, 2) if isinstance(monthly, float) else None
    ratio = round((annual / annual_rent_eur) * 100.0, 1) if isinstance(annual, float) and isinstance(annual_rent_eur, float) and annual_rent_eur > 0.0 else None
    return {
        "monthly_operating_costs_eur": monthly,
        "annual_operating_costs_eur": annual,
        "operating_cost_ratio_pct": ratio,
        "source_mode": "assumption",
        "source_label": "Fallback operating cost model",
    }


def _tax_snapshot(*, feed: dict[str, object], country_code: str, purchase_price_eur: float) -> dict[str, object]:
    base = dict(feed or {}) if feed else _country_tax_defaults(country_code)
    transfer_pct = _float_or_none(base.get("property_transfer_tax_pct")) or 0.0
    registry_pct = _float_or_none(base.get("land_registry_fee_pct")) or 0.0
    annual_pct = _float_or_none(base.get("annual_property_tax_pct")) or 0.0
    transfer_eur = round(purchase_price_eur * (transfer_pct / 100.0), 2) if purchase_price_eur > 0 else 0.0
    registry_eur = round(purchase_price_eur * (registry_pct / 100.0), 2) if purchase_price_eur > 0 else 0.0
    annual_tax_eur = round(purchase_price_eur * (annual_pct / 100.0), 2) if purchase_price_eur > 0 else 0.0
    return {
        "property_transfer_tax_pct": transfer_pct,
        "land_registry_fee_pct": registry_pct,
        "annual_property_tax_pct": annual_pct,
        "property_transfer_tax_eur": transfer_eur,
        "land_registry_fee_eur": registry_eur,
        "annual_property_tax_eur": annual_tax_eur,
        "source_mode": str(base.get("source_mode") or ("live_feed" if feed else "country_default")).strip() or "country_default",
        "source_label": str(base.get("source_label") or ("Tax feed" if feed else "Country fallback tax model")).strip() or "Country fallback tax model",
    }


def _financing_snapshot(
    *,
    feed: dict[str, object],
    purchase_price_eur: float,
    acquisition_costs_eur: float,
    annual_noi_eur: float | None,
    preferences: dict[str, object],
) -> dict[str, object]:
    feed_rate = _float_or_none(feed.get("interest_rate_pct"))
    preference_rate = _float_or_none(preferences.get("max_interest_rate_pct"))
    fallback_rate = _float_or_none(os.getenv("EA_PROPERTY_FINANCING_FALLBACK_INTEREST_RATE_PCT")) or 4.25
    interest_rate_pct = feed_rate if isinstance(feed_rate, float) and feed_rate > 0.0 else (preference_rate if isinstance(preference_rate, float) and preference_rate > 0.0 else fallback_rate)
    equity_available_eur = _float_or_none(preferences.get("equity_available_eur"))
    down_payment_pct = _float_or_none(preferences.get("down_payment_pct"))
    if not isinstance(equity_available_eur, float) or equity_available_eur <= 0.0:
        if isinstance(down_payment_pct, float) and down_payment_pct > 0.0:
            equity_available_eur = round(purchase_price_eur * (down_payment_pct / 100.0), 2)
        else:
            equity_available_eur = round(purchase_price_eur * 0.25, 2) if purchase_price_eur > 0.0 else 0.0
    loan_amount_eur = max(0.0, round(purchase_price_eur - equity_available_eur, 2))
    loan_term_years = _int_or_none(feed.get("loan_term_years") or preferences.get("loan_term_years")) or 25
    annual_rate = max(interest_rate_pct, 0.0) / 100.0
    periods = max(int(loan_term_years), 1) * 12
    monthly_rate = annual_rate / 12.0
    if loan_amount_eur <= 0.0:
        monthly_payment = 0.0
    elif monthly_rate <= 0.0:
        monthly_payment = loan_amount_eur / periods
    else:
        monthly_payment = loan_amount_eur * (monthly_rate * math.pow(1.0 + monthly_rate, periods)) / (math.pow(1.0 + monthly_rate, periods) - 1.0)
    annual_debt_service_eur = round(monthly_payment * 12.0, 2)
    dscr = round(annual_noi_eur / annual_debt_service_eur, 2) if isinstance(annual_noi_eur, float) and annual_noi_eur > 0.0 and annual_debt_service_eur > 0.0 else None
    cash_invested_eur = round(equity_available_eur + max(acquisition_costs_eur - purchase_price_eur, 0.0), 2)
    return {
        "interest_rate_pct": round(interest_rate_pct, 2),
        "loan_term_years": loan_term_years,
        "equity_available_eur": round(equity_available_eur, 2),
        "loan_amount_eur": round(loan_amount_eur, 2),
        "ltv_pct": round((loan_amount_eur / purchase_price_eur) * 100.0, 1) if purchase_price_eur > 0.0 else None,
        "annual_debt_service_eur": annual_debt_service_eur,
        "cash_invested_eur": cash_invested_eur,
        "dscr": dscr,
        "source_mode": str(feed.get("source_mode") or ("live_feed" if feed else "assumption")).strip() or "assumption",
        "source_label": str(feed.get("source_label") or ("Financing feed" if feed else "Fallback financing model")).strip() or "Fallback financing model",
    }


def property_investment_external_snapshot(
    *,
    country_code: str,
    property_url: str,
    title: str,
    facts: dict[str, object],
    preferences: dict[str, object],
    snapshot: dict[str, object] | None,
) -> dict[str, object]:
    purchase_price_eur = _float_or_none((snapshot or {}).get("current_price_eur") or facts.get("price_eur")) or 0.0
    area_sqm = _float_or_none((snapshot or {}).get("current_area_sqm") or facts.get("area_m2") or facts.get("living_area_m2")) or 0.0
    rooms = _float_or_none(facts.get("rooms") or facts.get("room_count"))
    request_payload = {
        "country_code": str(country_code or "").strip().upper() or "AT",
        "property_url": str(property_url or "").strip(),
        "title": str(title or "").strip(),
        "property_type": list(preferences.get("property_type") or []),
        "region_code": str(preferences.get("region_code") or "").strip(),
        "location_query": str(preferences.get("location_query") or "").strip(),
        "map_lat": _float_or_none(facts.get("map_lat")),
        "map_lng": _float_or_none(facts.get("map_lng")),
        "postal_name": str(facts.get("postal_name") or "").strip(),
        "district": str(facts.get("district") or "").strip(),
        "purchase_price_eur": purchase_price_eur,
        "area_sqm": area_sqm,
        "rooms": rooms,
    }
    rent_feed = _fetch_external_feed("EA_PROPERTY_RENT_ROLL_FEED", request_payload)
    rent_roll = _rent_roll_snapshot(snapshot=dict(snapshot or {}), feed=rent_feed)
    annual_rent_eur = _float_or_none(rent_roll.get("estimated_annual_rent_eur"))

    operating_feed = _fetch_external_feed("EA_PROPERTY_OPERATING_COST_FEED", request_payload)
    operating_costs = _operating_cost_snapshot(
        feed=operating_feed,
        facts=facts,
        area_sqm=area_sqm,
        annual_rent_eur=annual_rent_eur,
    )

    tax_feed = _fetch_external_feed("EA_PROPERTY_TAX_FEED", request_payload)
    taxes = _tax_snapshot(
        feed=tax_feed,
        country_code=str(country_code or "").strip().upper(),
        purchase_price_eur=purchase_price_eur,
    )

    vacancy_reserve_pct = _float_or_none(preferences.get("vacancy_reserve_pct"))
    if vacancy_reserve_pct is None:
        vacancy_reserve_pct = _float_or_none(rent_roll.get("vacancy_rate_pct"))
    if vacancy_reserve_pct is None:
        vacancy_reserve_pct = 4.0
    capex_reserve_pct = _float_or_none(preferences.get("capex_reserve_pct"))
    if capex_reserve_pct is None:
        capex_reserve_pct = 6.0
    vacancy_loss_eur = round((annual_rent_eur or 0.0) * (vacancy_reserve_pct / 100.0), 2) if annual_rent_eur else 0.0
    capex_reserve_eur = round((annual_rent_eur or 0.0) * (capex_reserve_pct / 100.0), 2) if annual_rent_eur else 0.0
    annual_operating_costs_eur = _float_or_none(operating_costs.get("annual_operating_costs_eur")) or 0.0
    annual_property_tax_eur = _float_or_none(taxes.get("annual_property_tax_eur")) or 0.0
    acquisition_costs_eur = round(
        purchase_price_eur
        + (_float_or_none(taxes.get("property_transfer_tax_eur")) or 0.0)
        + (_float_or_none(taxes.get("land_registry_fee_eur")) or 0.0),
        2,
    )
    annual_noi_eur = round(
        max((annual_rent_eur or 0.0) - vacancy_loss_eur - annual_operating_costs_eur - annual_property_tax_eur - capex_reserve_eur, 0.0),
        2,
    ) if annual_rent_eur else None

    financing_feed = _fetch_external_feed("EA_PROPERTY_FINANCING_FEED", request_payload)
    financing = _financing_snapshot(
        feed=financing_feed,
        purchase_price_eur=purchase_price_eur,
        acquisition_costs_eur=acquisition_costs_eur,
        annual_noi_eur=annual_noi_eur,
        preferences=preferences,
    )
    annual_debt_service_eur = _float_or_none(financing.get("annual_debt_service_eur")) or 0.0
    dscr = _float_or_none(financing.get("dscr"))
    cap_rate_pct = round((annual_noi_eur / acquisition_costs_eur) * 100.0, 2) if annual_noi_eur and acquisition_costs_eur > 0.0 else None
    net_yield_pct = round((annual_noi_eur / purchase_price_eur) * 100.0, 2) if annual_noi_eur and purchase_price_eur > 0.0 else None
    cash_flow_after_debt_eur = round((annual_noi_eur or 0.0) - annual_debt_service_eur, 2) if annual_noi_eur is not None else None
    cash_invested_eur = _float_or_none(financing.get("cash_invested_eur"))
    cash_on_cash_yield_pct = round((cash_flow_after_debt_eur / cash_invested_eur) * 100.0, 2) if cash_flow_after_debt_eur is not None and isinstance(cash_invested_eur, float) and cash_invested_eur > 0.0 else None
    break_even_occupancy_pct = (
        round(((annual_operating_costs_eur + annual_property_tax_eur + capex_reserve_eur + annual_debt_service_eur) / annual_rent_eur) * 100.0, 1)
        if annual_rent_eur and annual_rent_eur > 0.0
        else None
    )

    live_lane_count = sum(
        1
        for row in (rent_roll, operating_costs, taxes, financing)
        if str(row.get("source_mode") or "").strip().lower() in {"live_feed", "cached_live_feed"}
    )
    fallback_lane_count = 4 - live_lane_count
    if live_lane_count >= 3:
        confidence_label = "High confidence"
    elif live_lane_count >= 1:
        confidence_label = "Partial evidence"
    else:
        confidence_label = "Fallback assumptions"

    source_rows = [
        {
            "label": "Rent roll",
            "mode": str(rent_roll.get("source_mode") or "").strip(),
            "detail": str(rent_roll.get("source_label") or "").strip(),
        },
        {
            "label": "Taxes",
            "mode": str(taxes.get("source_mode") or "").strip(),
            "detail": str(taxes.get("source_label") or "").strip(),
        },
        {
            "label": "Financing",
            "mode": str(financing.get("source_mode") or "").strip(),
            "detail": str(financing.get("source_label") or "").strip(),
        },
        {
            "label": "Operating costs",
            "mode": str(operating_costs.get("source_mode") or "").strip(),
            "detail": str(operating_costs.get("source_label") or "").strip(),
        },
    ]
    summary_bits = [
        f"{live_lane_count}/4 live feeds" if live_lane_count > 0 else "0/4 live feeds",
        f"{fallback_lane_count}/4 fallback lanes" if fallback_lane_count > 0 else "",
    ]
    return {
        "rent_roll": rent_roll,
        "taxes": taxes,
        "financing": financing,
        "operating_costs": operating_costs,
        "vacancy_reserve_pct": vacancy_reserve_pct,
        "capex_reserve_pct": capex_reserve_pct,
        "vacancy_loss_eur": vacancy_loss_eur,
        "capex_reserve_eur": capex_reserve_eur,
        "acquisition_costs_eur": acquisition_costs_eur,
        "annual_noi_eur": annual_noi_eur,
        "cap_rate_pct": cap_rate_pct,
        "net_yield_pct": net_yield_pct,
        "cash_flow_after_debt_eur": cash_flow_after_debt_eur,
        "cash_on_cash_yield_pct": cash_on_cash_yield_pct,
        "break_even_occupancy_pct": break_even_occupancy_pct,
        "confidence_label": confidence_label,
        "feed_status_label": "Live external model" if live_lane_count > 0 else "Fallback underwriting model",
        "feed_status_detail": " · ".join(bit for bit in summary_bits if bit),
        "source_rows": source_rows,
    }
