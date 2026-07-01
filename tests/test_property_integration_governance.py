from __future__ import annotations

from app.services.property_integration_governance import (
    property_integration_governance_lanes,
    property_integration_governance_rows,
    required_property_integration_receipts,
)


def test_property_integration_governance_covers_recommended_ltd_lanes(monkeypatch) -> None:
    for lane in property_integration_governance_lanes():
        for env_name in (*lane.enabled_env, *lane.kill_switch_env):
            monkeypatch.delenv(env_name, raising=False)

    lanes = {lane.provider_key: lane for lane in property_integration_governance_lanes()}

    assert {
        "metasurvey",
        "lunacal",
        "apixdrive",
        "invoiless",
        "documentation_ai",
        "paperguide",
        "internxt",
        "approvethis",
        "unmixr",
        "brilliant_directories",
        "sendr",
        "deftform",
    } <= set(lanes)
    assert lanes["metasurvey"].priority == 1
    assert lanes["lunacal"].priority == 1
    assert lanes["apixdrive"].priority == 2
    assert lanes["invoiless"].priority == 2
    assert lanes["documentation_ai"].priority == 3
    assert all(not lane.enabled for lane in lanes.values())


def test_property_integration_governance_keeps_propertyquarry_canonical() -> None:
    lanes = property_integration_governance_lanes()
    forbidden_text = "\n".join(lane.forbidden_use for lane in lanes).lower()

    assert all("PropertyQuarry owns" in lane.source_of_truth for lane in lanes)
    assert "cannot own yes/maybe/no decisions" in forbidden_text
    assert "no inbound automation may mutate property truth" in forbidden_text
    assert "cannot own payment verification" in forbidden_text
    assert "cannot ingest the whole repository" in forbidden_text
    assert "not live storage" in forbidden_text
    assert "cannot replace propertyquarry policy" in forbidden_text
    assert "cannot own property facts" in forbidden_text
    assert "cannot own listing truth" in forbidden_text
    assert "direct send" in forbidden_text


def test_property_integration_governance_privacy_defaults_fail_closed() -> None:
    lanes = property_integration_governance_lanes()

    assert all(not lane.exact_address_allowed for lane in lanes)
    assert all(not lane.private_documents_allowed for lane in lanes)
    assert all(lane.kill_switch_env for lane in lanes)
    assert all(lane.verification_required for lane in lanes)
    assert all("raw_provider_payload" in lane.forbidden_inputs for lane in lanes)
    assert "unredacted_private_document" in set(next(lane for lane in lanes if lane.provider_key == "paperguide").forbidden_inputs)
    assert "unencrypted_database_dump" in set(next(lane for lane in lanes if lane.provider_key == "internxt").forbidden_inputs)
    sendr = next(lane for lane in lanes if lane.provider_key == "sendr")
    assert "private_user_profile" in set(sendr.forbidden_inputs)
    assert "human_review" in set(sendr.verification_required)


def test_property_integration_governance_rows_are_sorted_by_priority(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_METASURVEY_ENABLED", "1")
    rows = property_integration_governance_rows()

    priorities = [int(row["priority"]) for row in rows]
    assert priorities == sorted(priorities)
    metasurvey = next(row for row in rows if row["provider_key"] == "metasurvey")
    assert metasurvey["enabled"] is True
    assert metasurvey["exact_address_allowed"] is False
    assert "feedback_observation" in metasurvey["allowed_data_classes"]


def test_property_integration_required_receipts_cover_verification_privacy_truth_and_kill_switch() -> None:
    receipt_text = "\n".join(row["title"] + " " + row["detail"] for row in required_property_integration_receipts()).lower()

    assert "provider verification" in receipt_text
    assert "privacy projection" in receipt_text
    assert "propertyquarry source of truth" in receipt_text
    assert "kill switch" in receipt_text
    assert "fail-closed" in receipt_text
