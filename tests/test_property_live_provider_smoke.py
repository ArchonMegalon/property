from __future__ import annotations

import json

from scripts.property_live_provider_smoke import build_live_provider_smoke_receipt
from app.services.property_market_catalog import COUNTRIES, provider_options


def _search_ready_provider_count(country_code: str) -> int:
    return sum(
        1
        for row in provider_options(country_code=country_code)
        if bool(row.get("search_ready")) and not bool(row.get("coming_soon"))
    )


def _all_search_ready_countries() -> tuple[str, ...]:
    return tuple(
        country.code
        for country in COUNTRIES
        if _search_ready_provider_count(country.code) > 0
    )


def test_live_provider_smoke_is_skipped_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", raising=False)

    receipt = build_live_provider_smoke_receipt(countries=("AT", "CR"))

    assert receipt["status"] == "skipped"
    assert receipt["enabled"] is False
    assert len(receipt["checks"]) == 2
    assert all(row["provider_count"] > 0 for row in receipt["checks"])
    assert all(row["requires_floorplan_receipt"] is True for row in receipt["checks"])
    assert receipt["targeted_search_matrix_status"] == "skipped"
    assert receipt["targeted_search_matrix_count"] == 2 * (
        _search_ready_provider_count("AT") + _search_ready_provider_count("CR")
    )
    summary = receipt["targeted_search_matrix_summary"]
    assert summary["executed"] is False
    assert summary["skipped_case_count"] == receipt["targeted_search_matrix_count"]
    assert summary["all_search_ready_providers_covered"] is True
    assert summary["agent_unlimited_results_ok"] is True
    assert receipt["country_scope"] == "explicit"


def test_live_provider_smoke_can_expand_to_all_search_ready_countries(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_LIVE_PROVIDER_ALL_SEARCH_READY_COUNTRIES", raising=False)

    receipt = build_live_provider_smoke_receipt(countries=(), all_search_ready_countries=True)

    countries = _all_search_ready_countries()
    provider_total = sum(_search_ready_provider_count(country) for country in countries)
    assert receipt["status"] == "skipped"
    assert receipt["country_scope"] == "all_search_ready"
    assert receipt["targeted_search_matrix_count"] == 2 * provider_total
    assert receipt["targeted_search_matrix_summary"]["country_codes"] == list(countries)
    assert receipt["targeted_search_matrix_summary"]["all_search_ready_providers_covered"] is True
    assert receipt["targeted_search_matrix_summary"]["strict_case_count"] == provider_total
    assert receipt["targeted_search_matrix_summary"]["soft_filter_case_count"] == provider_total


def test_live_provider_smoke_explicit_countries_can_override_all_country_env(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_ALL_SEARCH_READY_COUNTRIES", "1")

    receipt = build_live_provider_smoke_receipt(countries=("AT",), all_search_ready_countries=False)

    assert receipt["country_scope"] == "explicit"
    assert receipt["targeted_search_matrix_summary"]["country_codes"] == ["AT"]
    assert receipt["targeted_search_matrix_count"] == 2 * _search_ready_provider_count("AT")


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
    assert receipt["targeted_search_matrix_status"] == "dry_run"
    matrix = receipt["targeted_search_matrix"]
    assert len(matrix) == 2 * (_search_ready_provider_count("AT") + _search_ready_provider_count("CR"))
    assert {row["mode"] for row in matrix} == {"targeted_no_soft_filters", "targeted_soft_filters"}
    assert all(row["payload_contract_ok"] is True for row in matrix)
    assert all(row["provider_country_code"] == row["country_code"] for row in matrix)
    assert all(row["agent_unlimited_results"] is True for row in matrix)
    assert all(row["status"] == "dry_run" for row in matrix)
    assert all(row["soft_filters_present"] is (row["mode"] == "targeted_soft_filters") for row in matrix)
    summary = receipt["targeted_search_matrix_summary"]
    assert summary["case_count"] == len(matrix)
    assert summary["strict_case_count"] == _search_ready_provider_count("AT") + _search_ready_provider_count("CR")
    assert summary["soft_filter_case_count"] == _search_ready_provider_count("AT") + _search_ready_provider_count("CR")
    assert summary["dry_run_case_count"] == len(matrix)
    assert summary["payload_contracts_ok"] is True
    assert summary["provider_country_scope_ok"] is True
    assert summary["strict_without_soft_filters_ok"] is True
    assert summary["soft_filters_present_ok"] is True


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
            "providers": [{"value": row.get("value"), "country_code": row.get("country_code")} for row in provider_options(country_code="AT")],
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
            "providers": [{"value": value, "country_code": "CR"} for value in [
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
    assert rows["AT"]["runtime_provider_country_scope_ok"] is True
    assert rows["AT"]["runtime_country_code"] == "AT"
    assert rows["CR"]["status"] == "pass"
    assert rows["CR"]["runtime_provider_count_ok"] is True
    assert rows["CR"]["runtime_defaults_present_ok"] is True
    assert rows["CR"]["runtime_provider_country_scope_ok"] is True
    assert receipt["targeted_search_matrix_status"] == "planned"
    assert receipt["targeted_search_matrix_executed"] is False
    summary = receipt["targeted_search_matrix_summary"]
    assert summary["execution_requested"] is False
    assert summary["executed"] is False
    assert summary["planned_case_count"] == receipt["targeted_search_matrix_count"]
    assert summary["all_search_ready_providers_covered"] is True


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


def test_live_provider_smoke_live_mode_rejects_cross_country_runtime_provider(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")

    at_options = [dict(row) for row in provider_options(country_code="AT")]
    payload = {
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
        "providers": [
            *[
                {"value": row.get("value"), "country_code": row.get("country_code")}
                for row in at_options
                if row.get("value") != "willhaben"
            ],
            {"value": "willhaben", "country_code": "PL"},
        ],
    }

    receipt = build_live_provider_smoke_receipt(countries=("AT",), fetcher=lambda _country, _timeout: payload)

    assert receipt["status"] == "fail"
    row = receipt["checks"][0]
    assert row["runtime_provider_count_ok"] is True
    assert row["runtime_defaults_present_ok"] is True
    assert row["runtime_provider_country_scope_ok"] is False
    assert row["runtime_provider_country_mismatches"] == ["willhaben"]


def test_live_provider_smoke_can_execute_targeted_search_matrix(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E", "1")

    catalog_payload = {
        "country_code": "AT",
        "listing_mode": "rent",
        "property_type": "apartment",
        "default_platforms": [
            "willhaben",
            "derstandard_at",
            "immoscout_at",
            "public_housing_at",
            "genossenschaften_at",
            "immmo",
        ],
        "providers": [{"value": row.get("value")} for row in provider_options(country_code="AT")],
    }
    observed_payloads: list[dict[str, object]] = []
    observed_status_reads: list[tuple[str, str]] = []
    checkpoint_path = tmp_path / "provider-matrix-checkpoint.json"

    def _search_executor(payload: dict[str, object], _timeout: float) -> dict[str, object]:
        observed_payloads.append(dict(payload))
        provider = str((payload.get("selected_platforms") or ["provider"])[0])
        preferences = dict(payload.get("property_preferences") or {})
        mode = str(preferences.get("search_mode") or "strict")
        return {
            "run_id": f"run-{provider}-{mode}",
            "status_url": f"/app/api/property/search-runs/run-{provider}-{mode}",
            "status": "queued",
        }

    def _status_fetcher(run_id: str, status_url: str, _timeout: float) -> dict[str, object]:
        observed_status_reads.append((run_id, status_url))
        return {
            "run_id": run_id,
            "status_url": status_url,
            "status": "queued",
            "candidate_count": 0,
        }

    receipt = build_live_provider_smoke_receipt(
        countries=("AT",),
        fetcher=lambda _country, _timeout: catalog_payload,
        search_executor=_search_executor,
        status_fetcher=_status_fetcher,
        checkpoint_path=checkpoint_path,
    )

    assert receipt["status"] == "pass"
    assert receipt["targeted_search_matrix_status"] == "pass"
    assert receipt["targeted_search_matrix_executed"] is True
    summary = receipt["targeted_search_matrix_summary"]
    assert summary["execution_requested"] is True
    assert summary["executed"] is True
    assert summary["executed_case_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["passed_case_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["failed_case_count"] == 0
    assert summary["failed_cases"] == []
    assert summary["dispatch_accepted_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["dispatch_acceptance_complete"] is True
    assert summary["status_readback_required"] is True
    assert summary["status_readback_case_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["status_readback_ok_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["status_readback_complete"] is True
    assert summary["all_search_ready_providers_covered"] is True
    assert summary["agent_unlimited_results_ok"] is True
    assert summary["provider_country_scope_ok"] is True
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["checkpoint"] is True
    assert checkpoint["complete"] is False
    assert checkpoint["targeted_search_matrix_status"] == "running"
    assert checkpoint["targeted_search_matrix_count"] == 2 * _search_ready_provider_count("AT")
    assert len(observed_payloads) == 2 * _search_ready_provider_count("AT")
    assert len(observed_status_reads) == len(observed_payloads)
    assert all(row["status_probe_ok"] is True for row in receipt["targeted_search_matrix"])
    assert all(row["status_probe_status"] == "queued" for row in receipt["targeted_search_matrix"])
    assert all(payload.get("dispatch_only") is True for payload in observed_payloads)
    assert all("max_results_per_source" not in payload for payload in observed_payloads)
    assert {
        dict(payload.get("property_preferences") or {}).get("search_mode")
        for payload in observed_payloads
    } == {"strict", "discovery"}
    assert all(
        dict(payload.get("property_preferences") or {}).get("property_commercial", {}).get("active_plan_key") == "agent"
        for payload in observed_payloads
    )


def test_live_provider_smoke_can_resume_passed_targeted_search_cases(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E", "1")

    first_provider = str(provider_options(country_code="AT")[0]["value"])
    resume_path = tmp_path / "provider-matrix-resume.json"
    resume_path.write_text(
        json.dumps(
            {
                "targeted_search_matrix": [
                    {
                        "country_code": "AT",
                        "provider": first_provider,
                        "mode": "targeted_no_soft_filters",
                        "status": "pass",
                        "run_id": "resumed-run",
                        "status_url": "/app/api/property/search-runs/resumed-run",
                        "runtime_status": "queued",
                        "status_probe_ok": True,
                        "status_probe_status": "queued",
                        "status_probe_candidate_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog_payload = {
        "country_code": "AT",
        "listing_mode": "rent",
        "property_type": "apartment",
        "default_platforms": [
            "willhaben",
            "derstandard_at",
            "immoscout_at",
            "public_housing_at",
            "genossenschaften_at",
            "immmo",
        ],
        "providers": [{"value": row.get("value")} for row in provider_options(country_code="AT")],
    }
    observed_payloads: list[dict[str, object]] = []

    def _search_executor(payload: dict[str, object], _timeout: float) -> dict[str, object]:
        observed_payloads.append(dict(payload))
        provider = str((payload.get("selected_platforms") or ["provider"])[0])
        preferences = dict(payload.get("property_preferences") or {})
        mode = str(preferences.get("search_mode") or "strict")
        return {
            "run_id": f"run-{provider}-{mode}",
            "status_url": f"/app/api/property/search-runs/run-{provider}-{mode}",
            "status": "queued",
        }

    receipt = build_live_provider_smoke_receipt(
        countries=("AT",),
        fetcher=lambda _country, _timeout: catalog_payload,
        search_executor=_search_executor,
        status_fetcher=lambda run_id, status_url, _timeout: {"run_id": run_id, "status_url": status_url, "status": "queued"},
        resume_checkpoint_path=resume_path,
    )

    expected_case_count = 2 * _search_ready_provider_count("AT")
    summary = receipt["targeted_search_matrix_summary"]
    assert receipt["status"] == "pass"
    assert receipt["resume_source"] == str(resume_path)
    assert summary["executed_case_count"] == expected_case_count
    assert summary["resumed_case_count"] == 1
    assert summary["passed_case_count"] == expected_case_count
    assert len(observed_payloads) == expected_case_count - 1
    resumed_rows = [row for row in receipt["targeted_search_matrix"] if row.get("resumed_from_checkpoint")]
    assert len(resumed_rows) == 1
    assert resumed_rows[0]["run_id"] == "resumed-run"


def test_live_provider_smoke_execution_fails_when_status_probe_is_unreadable(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE", "1")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN", "0")
    monkeypatch.setenv("PROPERTYQUARRY_LIVE_PROVIDER_SEARCH_E2E", "1")

    catalog_payload = {
        "country_code": "AT",
        "listing_mode": "rent",
        "property_type": "apartment",
        "default_platforms": [
            "willhaben",
            "derstandard_at",
            "immoscout_at",
            "public_housing_at",
            "genossenschaften_at",
            "immmo",
        ],
        "providers": [{"value": row.get("value")} for row in provider_options(country_code="AT")],
    }

    def _search_executor(payload: dict[str, object], _timeout: float) -> dict[str, object]:
        provider = str((payload.get("selected_platforms") or ["provider"])[0])
        return {
            "run_id": f"run-{provider}",
            "status_url": f"/app/api/property/search-runs/run-{provider}",
            "status": "queued",
        }

    receipt = build_live_provider_smoke_receipt(
        countries=("AT",),
        fetcher=lambda _country, _timeout: catalog_payload,
        search_executor=_search_executor,
        status_fetcher=lambda _run_id, _status_url, _timeout: {"run_id": "wrong-run", "status": "missing"},
    )

    assert receipt["status"] == "fail"
    assert receipt["targeted_search_matrix_status"] == "fail"
    summary = receipt["targeted_search_matrix_summary"]
    assert summary["execution_requested"] is True
    assert summary["failed_case_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["dispatch_accepted_count"] == 2 * _search_ready_provider_count("AT")
    assert summary["dispatch_acceptance_complete"] is True
    assert summary["status_readback_required"] is True
    assert summary["status_readback_ok_count"] == 0
    assert summary["status_readback_complete"] is False
    assert len(summary["failed_cases"]) == 25
    assert summary["failed_case_sample_count"] == 25
    assert summary["failed_case_sample_limit"] == 25
    assert {
        row["mode"]
        for row in summary["failed_cases"]
    } == {"targeted_no_soft_filters", "targeted_soft_filters"}
    assert all(row["status_probe_ok"] is False for row in receipt["targeted_search_matrix"])
