from __future__ import annotations

from scripts import property_provider_matrix_stage_runner as stage_runner


def test_next_provider_batch_skips_fully_passed_provider() -> None:
    receipt = {
        "targeted_search_matrix": [
            {
                "country_code": "AT",
                "provider": "willhaben",
                "mode": "targeted_no_soft_filters",
                "status": "pass",
            },
            {
                "country_code": "AT",
                "provider": "willhaben",
                "mode": "targeted_soft_filters",
                "status": "pass",
            },
        ]
    }

    batch = stage_runner.next_provider_batch(
        receipt=receipt,
        countries=("AT",),
        batch_size=2,
    )

    assert len(batch) == 2
    assert "willhaben" not in batch


def test_next_provider_batch_balances_country_rotation(monkeypatch) -> None:
    monkeypatch.setattr(
        stage_runner,
        "_search_ready_provider_keys_by_country",
        lambda countries: {
            "AT": ["willhaben", "immmo"],
            "DE": ["immowelt_de", "immoscout24_de"],
            "CR": ["encuentra24_cr", "re_cr_mls"],
        },
    )

    batch = stage_runner.next_provider_batch(
        receipt={},
        countries=("AT", "DE", "CR"),
        batch_size=4,
    )

    assert batch == ["willhaben", "immowelt_de", "encuentra24_cr", "immmo"]


def test_merge_provider_matrix_receipts_marks_partial_coverage_until_full_scope_is_done() -> None:
    previous = {
        "base_url": "https://propertyquarry.com",
        "search_run_timeout_seconds": 25.0,
        "provider_catalog_timeout_seconds": 8.0,
        "checks": [
            {"country_code": "AT", "status": "pass"},
        ],
        "cross_country_sanitization_checks": [
            {"country_code": "AT", "status": "pass", "sanitization_ok": True},
        ],
        "targeted_search_matrix": [
            {
                "country_code": "AT",
                "provider": "willhaben",
                "provider_country_code": "AT",
                "mode": "targeted_no_soft_filters",
                "status": "pass",
                "runtime_status": "queued",
                "status_probe_ok": True,
            },
            {
                "country_code": "AT",
                "provider": "willhaben",
                "provider_country_code": "AT",
                "mode": "targeted_soft_filters",
                "status": "pass",
                "runtime_status": "queued",
                "status_probe_ok": True,
            },
        ],
    }
    current = {
        "base_url": "https://propertyquarry.com",
        "search_run_timeout_seconds": 25.0,
        "provider_catalog_timeout_seconds": 8.0,
        "checks": [
            {"country_code": "AT", "status": "pass"},
        ],
        "cross_country_sanitization_checks": [
            {"country_code": "AT", "status": "pass", "sanitization_ok": True},
        ],
        "targeted_search_matrix": [
            {
                "country_code": "AT",
                "provider": "immmo",
                "provider_country_code": "AT",
                "mode": "targeted_no_soft_filters",
                "status": "pass",
                "runtime_status": "queued",
                "status_probe_ok": True,
            },
            {
                "country_code": "AT",
                "provider": "immmo",
                "provider_country_code": "AT",
                "mode": "targeted_soft_filters",
                "status": "pass",
                "runtime_status": "queued",
                "status_probe_ok": True,
            },
        ],
    }

    merged = stage_runner.merge_provider_matrix_receipts(
        previous_receipt=previous,
        current_receipt=current,
        countries=("AT",),
    )

    assert merged["status"] == "staged_provider_coverage_incomplete"
    assert merged["targeted_search_matrix_status"] == "partial"
    assert merged["targeted_search_matrix_count"] == 4
    summary = dict(merged["targeted_search_matrix_summary"])
    assert summary["executed"] is True
    assert summary["provider_scope_filtered"] is False
    assert summary["selected_provider_scope_covered"] is False
    assert summary["all_search_ready_providers_covered"] is False
    assert merged["remaining_search_ready_provider_count_by_country"]["AT"] > 0
    assert "willhaben" not in list(merged.get("next_provider_batch_suggestion") or [])


def test_build_staged_provider_matrix_receipt_executes_only_next_uncovered_batch(monkeypatch) -> None:
    previous = {
        "targeted_search_matrix": [
            {"country_code": "AT", "provider": "willhaben", "mode": "targeted_no_soft_filters", "status": "pass"},
            {"country_code": "AT", "provider": "willhaben", "mode": "targeted_soft_filters", "status": "pass"},
        ]
    }
    observed: dict[str, object] = {}

    monkeypatch.setattr(stage_runner, "_load_receipt", lambda path="": previous)

    def _fake_build_live_provider_smoke_receipt(**kwargs):
        observed["provider_keys"] = kwargs.get("provider_keys")
        observed["resume_checkpoint_path"] = kwargs.get("resume_checkpoint_path")
        return {
            "base_url": kwargs.get("base_url"),
            "search_run_timeout_seconds": 25.0,
            "provider_catalog_timeout_seconds": 8.0,
            "checks": [{"country_code": "AT", "status": "pass"}],
            "cross_country_sanitization_checks": [{"country_code": "AT", "status": "pass", "sanitization_ok": True}],
            "targeted_search_matrix": [
                {
                    "country_code": "AT",
                    "provider": "immmo",
                    "provider_country_code": "AT",
                    "mode": "targeted_no_soft_filters",
                    "status": "pass",
                    "runtime_status": "queued",
                    "status_probe_ok": True,
                },
                {
                    "country_code": "AT",
                    "provider": "immmo",
                    "provider_country_code": "AT",
                    "mode": "targeted_soft_filters",
                    "status": "pass",
                    "runtime_status": "queued",
                    "status_probe_ok": True,
                },
            ],
        }

    monkeypatch.setattr(stage_runner, "build_live_provider_smoke_receipt", _fake_build_live_provider_smoke_receipt)

    receipt = stage_runner.build_staged_provider_matrix_receipt(
        countries=("AT",),
        base_url="https://propertyquarry.com",
        batch_size=1,
        resume_receipt_path="state/receipts/provider-stage.json",
        allowed_provider_keys=(),
        timeout_seconds=8.0,
    )

    assert observed["provider_keys"] == ("immmo",)
    assert observed["resume_checkpoint_path"] == "state/receipts/provider-stage.json"
    assert receipt["targeted_search_matrix_count"] == 4
