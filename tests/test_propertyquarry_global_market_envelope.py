from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from propertyquarry_global_governance_test_support import (
    install_test_authority,
    signed_attestation,
)
from scripts import propertyquarry_global_market_envelope as envelope
from scripts import propertyquarry_gold_status as gold
from scripts.propertyquarry_global_governance_attestation import (
    GLOBAL_MARKET_GATE_ID,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE = "sha256:89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def _global_governance_authority(tmp_path, monkeypatch) -> None:
    install_test_authority(tmp_path, monkeypatch)


def _source() -> dict[str, object]:
    return envelope.load_envelope()


def _market(receipt: dict[str, object], country_code: str) -> dict[str, object]:
    return next(
        row
        for row in receipt["markets"]
        if isinstance(row, dict) and row.get("country_code") == country_code
    )


def test_checked_in_envelope_is_honestly_blocked_and_classified() -> None:
    source = _source()
    receipt = envelope.materialize_envelope(source)

    assert receipt["status"] == "BLOCKED"
    assert receipt["summary"]["launch_supported_markets"] == []
    assert receipt["summary"]["classifications"] == {
        "launch_supported": [],
        "private_beta": ["AT", "DE"],
        "preview": [],
        "catalog": [],
        "browser_state_only": ["CR"],
    }
    assert receipt["blockers"][0]["code"] == "global:no_launch_supported_market"

    for country_code in ("AT", "DE", "CR"):
        market = _market(receipt, country_code)
        source_market = next(
            row
            for row in source["markets"]
            if row["country_code"] == country_code
        )
        missing_by_name = {
            row["dimension"]: row
            for row in market["missing_dimensions"]
        }
        assert market["status"] == "BLOCKED"
        assert market["classification_match"] is True
        assert "provider_rights" in missing_by_name
        assert "live_provider_e2e" in missing_by_name
        assert missing_by_name["live_provider_e2e"]["missing_evidence"]
        assert market["workflow_claims"] == {
            "buyer_decision_support": True,
            "renter_discovery": True,
            "seller_supply": False,
        }
        assert market["market_contract"] == source_market["market_contract"]
        assert market["market_contract"]["listing_modes"] == ["rent", "buy"]
        assert market["market_contract"]["privacy_region"]["verification_status"] == (
            "external_unverified"
        )
        assert market["market_contract"]["support_window"] == {
            "coverage_status": "not_committed",
            "timezone": source_market["default_timezone"],
            "weekly_windows": [],
            "channels": [],
        }
        if country_code in {"AT", "DE"}:
            assert "renter_journey" not in missing_by_name
            assert source_market["dimensions"]["renter_journey"] == {
                "status": "proven",
                "evidence": [
                    "renter_discovery_contract",
                    "renter_value_loop_chromium",
                ],
                "missing_evidence": [],
            }
        else:
            assert "renter_journey" in missing_by_name
            assert missing_by_name["renter_journey"]["missing_evidence"]

    renter_receipt = source["evidence_catalog"]["renter_value_loop_chromium"]
    assert renter_receipt["sha256"] == (
        "e407552133e1182e7fb23f0d1f8b2e9de0d82bff8673b3a01e719a5385b143ab"
    )
    assert "no live provider" in renter_receipt["scope"]

    assert _market(receipt, "AT")["computed_classification"] == "private_beta"
    assert _market(receipt, "DE")["computed_classification"] == "private_beta"
    assert _market(receipt, "CR")["computed_classification"] == "browser_state_only"
    assert {
        row["country_code"]: (
            row["market_language"],
            row["currency_code"],
            row["default_timezone"],
        )
        for row in receipt["markets"]
    } == {
        "AT": ("de-AT", "EUR", "Europe/Vienna"),
        "DE": ("de-DE", "EUR", "Europe/Berlin"),
        "CR": ("es-CR", "CRC", "America/Costa_Rica"),
    }


def test_source_digest_is_canonical_and_repeatable() -> None:
    source = _source()
    expected = hashlib.sha256(envelope.canonical_json_bytes(source)).hexdigest()

    first = envelope.materialize_envelope(
        source,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=NOW,
    )
    second = envelope.materialize_envelope(
        copy.deepcopy(source),
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=NOW,
    )

    assert first["source_sha256"] == expected
    assert second == first


def _fully_evidenced_launch_source() -> dict[str, object]:
    source = _source()
    source["phase_one"]["operating_mode"] = "launch"
    source["phase_one"]["excluded_claims"] = [
        claim
        for claim in source["phase_one"]["excluded_claims"]
        if claim != "fully_localized_global_product"
    ]
    for market in source["markets"]:
        market["declared_classification"] = "launch_supported"
        market["market_contract"]["privacy_region"]["verification_status"] = "verified"
        market["market_contract"]["support_window"] = {
            "coverage_status": "committed_business_hours",
            "timezone": market["default_timezone"],
            "weekly_windows": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                    "start_local": "09:00",
                    "end_local": "17:00",
                }
            ],
            "channels": ["email"],
        }
        for dimension_name in envelope._market_required_dimensions(market):
            dimension = market["dimensions"][dimension_name]
            dimension["status"] = "proven"
            dimension["missing_evidence"] = []
            if not dimension["evidence"]:
                dimension["evidence"] = ["market_catalog_75"]
    return source


def _live_launch_evidence(source: dict[str, object]) -> dict[str, object]:
    source_sha = hashlib.sha256(envelope.canonical_json_bytes(source)).hexdigest()
    evidence = {
        "status": "pass",
        "observed_at": NOW.isoformat(),
        "evidence_digest": "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
        "workflow_ref": "workflow:global-market:launch:8f27c4",
    }
    receipt = {
        "schema": envelope.LIVE_RECEIPT_SCHEMA,
        "profile": "launch",
        "claim_scope": "core",
        "generated_at": NOW.isoformat(),
        "source_envelope_id": source["envelope_id"],
        "source_sha256": source_sha,
        "release_identity": {"commit_sha": COMMIT, "image_digest": IMAGE},
        "markets": [
            {
                "country_code": market["country_code"],
                "dimensions": [
                    {"dimension": dimension, **evidence}
                    for dimension in envelope._market_required_dimensions(market)
                ],
            }
            for market in source["markets"]
        ],
    }
    receipt["independent_attestation"] = signed_attestation(
        gate_id=GLOBAL_MARKET_GATE_ID,
        receipt_contract=envelope.LIVE_RECEIPT_SCHEMA,
        release_commit_sha=COMMIT,
        release_image_digest=IMAGE,
        source_digests={"market_envelope_sha256": f"sha256:{source_sha}"},
        payload_sha256=envelope._attested_payload_digest(receipt),
        issued_at=NOW - timedelta(minutes=2),
    )
    return receipt


def test_canonical_launch_producer_receipt_is_directly_accepted_by_gold() -> None:
    source = _fully_evidenced_launch_source()
    receipt = envelope.materialize_envelope(
        source,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        live_launch_evidence=_live_launch_evidence(source),
        live_receipt_ref="governed:global-market:launch:8f27c4",
        now=NOW,
    )
    assert receipt["status"] == "READY"
    assert receipt["blockers"] == []
    assert receipt["independently_attested"] is True

    accepted, details = gold._global_market_envelope_launch_status(
        receipt,
        receipt_present=True,
        required=True,
        expected_release_commit_sha=COMMIT,
        expected_release_image_digest=IMAGE,
        now=NOW,
        max_age_hours=24,
    )
    assert accepted is True
    assert details["status"] == "pass"
    assert details["errors"] == []


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        (
            "independently_attested",
            False,
            "global market envelope receipt is not independently attested",
        ),
        (
            "live_receipt_ref",
            "",
            "global market envelope receipt has no governed live evidence reference",
        ),
        (
            "live_receipt_age_seconds",
            24 * 3600 + 1,
            "global market envelope live evidence is stale, future-dated, or missing",
        ),
    ],
)
def test_gold_rejects_missing_or_stale_live_market_attestation(
    field: str,
    value: object,
    expected_error: str,
) -> None:
    source = _fully_evidenced_launch_source()
    receipt = envelope.materialize_envelope(
        source,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        live_launch_evidence=_live_launch_evidence(source),
        live_receipt_ref="governed:global-market:launch:8f27c4",
        now=NOW,
    )
    receipt[field] = value

    accepted, details = gold._global_market_envelope_launch_status(
        receipt,
        receipt_present=True,
        required=True,
        expected_release_commit_sha=COMMIT,
        expected_release_image_digest=IMAGE,
        now=NOW,
        max_age_hours=24,
    )

    assert accepted is False
    assert expected_error in details["errors"]


def test_launch_ready_dimensions_cannot_bypass_exact_release_binding() -> None:
    source = _fully_evidenced_launch_source()
    receipt = envelope.materialize_envelope(
        source,
        expected_release_sha="a" * 40,
        expected_image_digest="sha256:" + "b" * 64,
        live_launch_evidence=_live_launch_evidence(source),
        now=NOW,
    )
    assert receipt["status"] == "BLOCKED"
    assert any("placeholder" in row["code"] for row in receipt["blockers"])


def test_authored_proven_statuses_cannot_substitute_for_live_attested_market_evidence() -> None:
    receipt = envelope.materialize_envelope(
        _fully_evidenced_launch_source(),
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=NOW,
    )
    assert receipt["status"] == "BLOCKED"
    assert receipt["independently_attested"] is False
    assert any(
        row["reason"] == "fresh independently attested live market evidence is required"
        for row in receipt["blockers"]
    )


def test_declared_launch_supported_cannot_override_missing_live_evidence() -> None:
    source = _source()
    source["markets"][0]["declared_classification"] = "launch_supported"

    receipt = envelope.materialize_envelope(source)
    austria = _market(receipt, "AT")

    assert receipt["status"] == "BLOCKED"
    assert austria["computed_classification"] == "private_beta"
    assert austria["classification_match"] is False
    assert austria["launch_supported"] is False
    assert any(
        row["code"] == "AT:classification_mismatch"
        for row in receipt["blockers"]
    )


def test_taxonomy_distinguishes_preview_catalog_and_browser_state() -> None:
    source = _source()
    costa_rica = source["markets"][2]
    assert envelope.compute_market_classification(costa_rica) == "browser_state_only"

    preview = copy.deepcopy(costa_rica)
    preview["dimensions"]["market_browser_journey"]["status"] = "missing"
    preview["dimensions"]["market_browser_journey"]["evidence"] = []
    assert envelope.compute_market_classification(preview) == "preview"

    catalog = copy.deepcopy(preview)
    catalog["dimensions"]["responsive_devices"]["evidence"] = []
    assert envelope.compute_market_classification(catalog) == "catalog"


def test_validator_rejects_an_incomplete_dimension_set() -> None:
    source = _source()
    del source["markets"][0]["dimensions"]["performance"]

    with pytest.raises(
        envelope.EnvelopeError,
        match="dimensions_must_be_exact_ordered_set:AT",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_proven_status_without_receipt_evidence() -> None:
    source = _source()
    dimension = source["markets"][0]["dimensions"]["content_locale"]
    dimension["status"] = "proven"
    dimension["evidence"] = []
    dimension["missing_evidence"] = []

    with pytest.raises(
        envelope.EnvelopeError,
        match="proven_dimension_requires_evidence_only:AT:content_locale",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_market_semantics_drift() -> None:
    source = _source()
    source["markets"][2]["currency_code"] = "EUR"

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_semantics_mismatch:CR:currency_code:expected=CRC:observed=EUR",
    ):
        envelope.materialize_envelope(source)


@pytest.mark.parametrize("field", envelope.MARKET_CONTRACT_FIELDS)
def test_validator_rejects_every_omitted_market_contract_field(field: str) -> None:
    source = _source()
    del source["markets"][0]["market_contract"][field]

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_contract:AT_fields_must_be_exact_ordered_set",
    ):
        envelope.materialize_envelope(source)


@pytest.mark.parametrize(
    ("field", "wrong_type"),
    [
        ("accepted_content_languages", []),
        ("measurement_system", []),
        ("timezone_policy", []),
        ("address_model", []),
        ("provider_set", []),
        ("listing_modes", {}),
        ("privacy_region", []),
        ("support_window", []),
    ],
)
def test_validator_rejects_wrong_market_contract_field_types(
    field: str,
    wrong_type: object,
) -> None:
    source = _source()
    source["markets"][0]["market_contract"][field] = wrong_type

    with pytest.raises(envelope.EnvelopeError):
        envelope.materialize_envelope(source)


def test_validator_rejects_open_ended_market_contract_objects() -> None:
    source = _source()
    source["markets"][0]["market_contract"]["undeclared_extension"] = True

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_contract:AT_fields_must_be_exact_ordered_set",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_unknown_market_provider() -> None:
    source = _source()
    provider = source["markets"][0]["market_contract"]["provider_set"]["providers"][0]
    provider["provider_id"] = "unknown_at_provider"

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_provider_unknown:AT:unknown_at_provider",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_cross_market_provider() -> None:
    source = _source()
    provider = source["markets"][0]["market_contract"]["provider_set"]["providers"][0]
    provider["provider_id"] = "immoscout_de"

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_provider_country_mismatch:AT:immoscout_de",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_provider_modes_that_drift_from_governed_catalog() -> None:
    source = _source()
    provider = source["markets"][0]["market_contract"]["provider_set"]["providers"][0]
    provider["listing_modes"] = ["rent"]

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_provider_listing_modes_mismatch:AT:willhaben",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_provider_that_catalog_does_not_mark_search_ready() -> None:
    source = _source()
    provider = source["markets"][0]["market_contract"]["provider_set"]["providers"][0]
    provider["provider_id"] = "arwag_at"

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_provider_not_search_ready:AT:arwag_at",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_provider_set_without_every_offered_listing_mode() -> None:
    source = _source()
    source["markets"][0]["market_contract"]["provider_set"]["providers"] = [
        {"provider_id": "wiener_wohnen", "listing_modes": ["rent"]}
    ]

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_provider_mode_coverage_incomplete:AT",
    ):
        envelope.materialize_envelope(source)


def test_validator_rejects_listing_modes_that_conflict_with_workflow_claims() -> None:
    source = _source()
    source["markets"][0]["market_contract"]["listing_modes"] = ["rent"]

    with pytest.raises(
        envelope.EnvelopeError,
        match="market_listing_modes_workflow_mismatch:AT",
    ):
        envelope.materialize_envelope(source)


@pytest.mark.parametrize(
    ("privacy_status", "expected_error"),
    [
        ("external_unverified", "launch_requires_verified_privacy_region:AT"),
        ("verified", "launch_requires_committed_support_window:AT"),
    ],
)
def test_launch_contract_cannot_use_unverified_privacy_or_uncommitted_support(
    privacy_status: str,
    expected_error: str,
) -> None:
    source = _source()
    source["phase_one"]["operating_mode"] = "launch"
    source["phase_one"]["excluded_claims"] = [
        claim
        for claim in source["phase_one"]["excluded_claims"]
        if claim != "fully_localized_global_product"
    ]
    source["markets"][0]["market_contract"]["privacy_region"][
        "verification_status"
    ] = privacy_status

    with pytest.raises(
        envelope.EnvelopeError,
        match=expected_error,
    ):
        envelope.materialize_envelope(source)


def test_cli_writes_blocked_receipt_and_returns_nonzero(tmp_path) -> None:
    output_path = tmp_path / "market-envelope-receipt.json"

    result = envelope.main(
        [
            "--input",
            str(envelope.DEFAULT_ENVELOPE_PATH),
            "--output",
            str(output_path),
        ]
    )
    receipt = json.loads(output_path.read_text(encoding="utf-8"))

    assert result == 1
    assert receipt["schema"] == envelope.RECEIPT_SCHEMA
    assert receipt["status"] == "BLOCKED"
    assert receipt["summary"]["launch_supported_markets"] == []


def test_cli_writes_invalid_receipt_and_returns_two(tmp_path) -> None:
    input_path = tmp_path / "invalid-envelope.json"
    output_path = tmp_path / "invalid-envelope-receipt.json"
    source = _source()
    source["markets"][2]["default_timezone"] = "UTC"
    input_path.write_text(json.dumps(source), encoding="utf-8")

    result = envelope.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )
    receipt = json.loads(output_path.read_text(encoding="utf-8"))

    assert result == 2
    assert receipt["status"] == "INVALID"
    assert receipt["error"].startswith(
        "market_semantics_mismatch:CR:default_timezone"
    )
