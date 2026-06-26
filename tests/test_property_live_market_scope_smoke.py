from __future__ import annotations

import json

from scripts.propertyquarry_live_market_scope_smoke import build_live_market_scope_receipt


def _response(payload: dict[str, object], *, status_code: int) -> dict[str, object]:
    return {
        "status_code": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload).encode("utf-8"),
        "error": "",
    }


def test_live_market_scope_smoke_accepts_only_presentation_markets_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        country = url.rsplit("country=", 1)[-1]
        if country in {"AT", "DE", "CR"}:
            return _response({"country_code": country, "providers": [{"value": f"provider_{country.lower()}"}]}, status_code=200)
        return _response({"error": {"code": "unsupported_property_market"}}, status_code=400)

    receipt = build_live_market_scope_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        fetcher=fetcher,
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    assert receipt["allowed_countries"] == ["AT", "DE", "CR"]
    assert receipt["blocked_countries"] == ["UK", "AU", "PL"]


def test_live_market_scope_smoke_rejects_australian_catalog_leak_without_network() -> None:
    def fetcher(url: str, _timeout: float) -> dict[str, object]:
        country = url.rsplit("country=", 1)[-1]
        if country in {"AT", "DE", "CR"}:
            return _response({"country_code": country, "providers": [{"value": f"provider_{country.lower()}"}]}, status_code=200)
        if country == "AU":
            return _response({"country_code": "AU", "providers": [{"value": "realestate_au"}]}, status_code=200)
        return _response({"error": {"code": "unsupported_property_market"}}, status_code=400)

    receipt = build_live_market_scope_receipt(
        base_url="https://propertyquarry.com",
        api_token="token",
        principal_id="cf-email:tibor.girschele@gmail.com",
        fetcher=fetcher,
    )

    assert receipt["status"] == "fail"
    australia = next(row for row in receipt["checks"] if row["country"] == "AU")
    assert australia["status_code"] == 200
    assert australia["provider_count"] == 1
    assert any(check["name"] == "blocked_error_code" and check["ok"] is False for check in australia["checks"])
