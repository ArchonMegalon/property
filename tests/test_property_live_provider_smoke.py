from __future__ import annotations

from scripts.property_live_provider_smoke import build_live_provider_smoke_receipt
from app.services.property_market_catalog import provider_options


def test_live_provider_smoke_is_skipped_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", raising=False)

    receipt = build_live_provider_smoke_receipt(countries=("AT", "CR"))

    assert receipt["status"] == "skipped"
    assert receipt["enabled"] is False
    assert len(receipt["checks"]) == 2
    assert all(row["provider_count"] > 0 for row in receipt["checks"])
    assert all(row["requires_floorplan_receipt"] is True for row in receipt["checks"])


def test_live_provider_smoke_dry_run_proves_at_and_cr_catalogs(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "1")

    receipt = build_live_provider_smoke_receipt(countries=("AT", "CR"))

    assert receipt["status"] == "dry_run"
    rows = {row["country_code"]: row for row in receipt["checks"]}
    assert rows["AT"]["default_provider_count"] > 0
    assert rows["CR"]["default_provider_count"] > 0
    assert rows["AT"]["requires_filter_pushdown_receipt"] is True
    assert rows["CR"]["requires_location_boundary_receipt"] is True


def test_live_provider_smoke_live_mode_probes_runtime_catalog(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")

    payloads = {
        "AT": {
            "country_code": "AT",
            "listing_mode": "rent",
            "property_type": "any",
            "default_platforms": [
                "willhaben",
                "derstandard_at",
                "immoscout_at",
                "public_housing_at",
                "genossenschaften_at",
                "immmo",
            ],
            "providers": [{"value": row.get("value")} for row in provider_options(country_code="AT")],
        },
        "CR": {
            "country_code": "CR",
            "listing_mode": "rent",
            "property_type": "any",
            "default_platforms": [
                "encuentra24_cr",
                "re_cr_mls",
                "realtor_cr",
                "propertiesincostarica_cr",
                "coldwellbanker_cr",
                "krain_cr",
                "theagency_cr",
                "desarrollos_cr",
                "tierraverde_cr",
                "twocostaricarealestate_cr",
            ],
            "providers": [{"value": value} for value in [
                "encuentra24_cr",
                "re_cr_mls",
                "realtor_cr",
                "propertiesincostarica_cr",
                "coldwellbanker_cr",
                "krain_cr",
                "theagency_cr",
                "desarrollos_cr",
                "tierraverde_cr",
                "twocostaricarealestate_cr",
                "century21_cr",
            ]],
        },
    }

    def _fetcher(country: str, _timeout: float) -> dict[str, object]:
        return payloads[country]

    receipt = build_live_provider_smoke_receipt(countries=("AT", "CR"), fetcher=_fetcher)

    assert receipt["status"] == "pass"
    rows = {row["country_code"]: row for row in receipt["checks"]}
    assert rows["AT"]["status"] == "pass"
    assert rows["AT"]["runtime_provider_count_ok"] is True
    assert rows["AT"]["runtime_defaults_present_ok"] is True
    assert rows["AT"]["runtime_country_code"] == "AT"
    assert rows["CR"]["status"] == "pass"
    assert rows["CR"]["runtime_provider_count_ok"] is True
    assert rows["CR"]["runtime_defaults_present_ok"] is True


def test_live_provider_smoke_live_mode_reports_runtime_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")

    receipt = build_live_provider_smoke_receipt(
        countries=("AT",),
        fetcher=lambda _country, _timeout: {
            "country_code": "AT",
            "default_platforms": ["willhaben"],
            "providers": [{"value": "willhaben"}],
        },
    )

    assert receipt["status"] == "fail"
    row = receipt["checks"][0]
    assert row["status"] == "fail"
    assert row["runtime_provider_count_ok"] is False
    assert row["runtime_defaults_present_ok"] is False
