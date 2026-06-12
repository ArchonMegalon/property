from __future__ import annotations

from scripts.property_live_provider_smoke import build_live_provider_smoke_receipt


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
