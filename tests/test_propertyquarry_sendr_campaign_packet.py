from __future__ import annotations

from app.domain.property.sendr_campaign import (
    SENDR_CAMPAIGN_PACKET_CONTRACT,
    SENDR_CAMPAIGN_RECEIPT_CONTRACT,
    SENDR_ENGAGEMENT_BATCH_CONTRACT,
)
from app.services.property_outreach_policy import (
    materialize_propertyquarry_sendr_campaign_receipt,
    materialize_propertyquarry_sendr_engagement_receipt,
    validate_propertyquarry_sendr_campaign_packet,
)


def _valid_sendr_packet() -> dict[str, object]:
    return {
        "contract_name": SENDR_CAMPAIGN_PACKET_CONTRACT,
        "packet_id": "pq-relocation-vienna-pilot-001",
        "campaign_type": "RELOCATION_PARTNER_OUTREACH",
        "project": "propertyquarry",
        "owner": "propertyquarry_growth",
        "target_audience": "Vienna relocation consultants",
        "source_material": [
            {
                "path": "docs/PRODUCT_BRIEF.md",
                "sha256": "a" * 64,
                "classification": "approved_public",
            },
            {
                "path": "_completion/propertyquarry/sample_dossier.generated.json",
                "sha256": "b" * 64,
                "classification": "public_demo_synthetic",
            },
        ],
        "allowed_claims": [
            "PropertyQuarry aggregates listings and ranks them against a stated brief.",
            "The product helps decide which listings deserve attention.",
        ],
        "forbidden_claims": [
            "PropertyQuarry guarantees the best property.",
            "PropertyQuarry provides legal advice.",
            "PropertyQuarry provides individualized financial advice.",
        ],
        "recipient_policy": {
            "allowed_recipient_basis": [
                "public_business_contact",
                "prior_conversation",
                "inbound_lead",
                "event_context",
                "manual_partner_shortlist",
            ],
            "forbidden_recipient_basis": [
                "scraped_private_profile",
                "private_whatsapp_export",
                "raw_ea_inbox",
                "purchased_personal_list_without_lawful_basis",
            ],
        },
        "recipients": [
            {
                "recipient_basis": "public_business_contact",
                "source_url_or_note": "Public business website imprint.",
                "jurisdiction": "AT",
                "allowed_channel": "email",
                "suppression_status": "clear",
            }
        ],
        "channels": {"email": True, "linkedin": True, "whatsapp": False},
        "sendr_features_allowed": {
            "lead_finder": True,
            "data_enrichment": True,
            "personalized_pages": True,
            "dynamic_video": True,
            "sequencer": True,
            "whatsapp": False,
        },
        "message_copy": [
            "PropertyQuarry helps screen noisy property markets.",
            "Would it be worth a short call?",
        ],
        "personalized_page_template": "Public demo page with synthetic Vienna sample.",
        "video_script": "Thirty second product demo using public or synthetic examples.",
        "human_review_required": True,
        "direct_send_allowed": False,
        "auto_reply_allowed": False,
    }


def test_sendr_campaign_packet_passes_with_documented_forbidden_examples() -> None:
    validation = validate_propertyquarry_sendr_campaign_packet(_valid_sendr_packet())

    assert validation["status"] == "pass"
    assert validation["checks"]["claim_validation"] == "pass"
    assert validation["checks"]["recipient_basis_policy"] == "pass"
    assert validation["checks"]["no_direct_send"] == "pass"
    assert validation["checks"]["no_auto_reply"] == "pass"


def test_sendr_campaign_receipt_is_limited_and_human_reviewed() -> None:
    receipt = materialize_propertyquarry_sendr_campaign_receipt(
        _valid_sendr_packet(),
        reviewer="operator",
        reviewed_at="2026-07-01T00:00:00Z",
        max_contacts=50,
    )

    assert receipt["contract_name"] == SENDR_CAMPAIGN_RECEIPT_CONTRACT
    assert receipt["status"] == "pilot_approved"
    assert receipt["license_tier"] == "AppSumo Tier 4"
    assert receipt["direct_send_allowed"] is False
    assert receipt["auto_reply_allowed"] is False
    assert receipt["limited_send_allowed"] is True
    assert receipt["recipient_policy"]["recipient_count"] == 1
    assert receipt["recipient_policy"]["suppression_checked"] is True
    assert len(str(receipt["source_packet_sha256"])) == 64
    assert len(str(receipt["message_copy_sha256"])) == 64


def test_sendr_campaign_packet_blocks_direct_send_whatsapp_private_data_and_bad_claims() -> None:
    packet = _valid_sendr_packet()
    packet["allowed_claims"] = ["PropertyQuarry guarantees the best property and a risk-free investment."]
    packet["private_user_profile"] = {"exact_private_commute_destination": "Private school address"}
    packet["channels"] = {"email": True, "linkedin": False, "whatsapp": True}
    packet["sendr_features_allowed"] = {"whatsapp": True}
    packet["direct_send_allowed"] = True
    packet["auto_reply_allowed"] = True
    packet["recipients"] = [
        {
            "recipient_basis": "raw_ea_inbox",
            "source_url_or_note": "",
            "jurisdiction": "",
            "allowed_channel": "whatsapp",
            "suppression_status": "suppressed",
        }
    ]

    validation = validate_propertyquarry_sendr_campaign_packet(packet)

    assert validation["status"] == "fail"
    assert validation["checks"]["claim_validation"] == "fail"
    assert validation["checks"]["privacy"] == "fail"
    assert validation["checks"]["email_or_linkedin_only"] == "fail"
    assert validation["checks"]["no_direct_send"] == "fail"
    assert validation["checks"]["no_auto_reply"] == "fail"
    assert validation["checks"]["recipients"] == "fail"
    finding_text = " ".join(str(item) for item in validation["findings"])
    assert "recipient_0_basis" in finding_text
    assert "private_user_profile" in finding_text


def test_sendr_campaign_packet_fails_closed_when_runtime_send_switches_are_enabled() -> None:
    env = {
        "PROPERTYQUARRY_SENDR_DIRECT_SEND_ENABLED": "1",
        "PROPERTYQUARRY_SENDR_AUTO_REPLY_ENABLED": "1",
    }

    validation = validate_propertyquarry_sendr_campaign_packet(_valid_sendr_packet(), env=env)

    assert validation["status"] == "fail"
    assert validation["checks"]["no_direct_send"] == "fail"
    assert validation["checks"]["no_auto_reply"] == "fail"


def test_sendr_engagement_receipt_redacts_raw_body_and_routes_reply_to_review() -> None:
    receipt = materialize_propertyquarry_sendr_engagement_receipt(
        campaign_id="sendr-campaign-001",
        event_batch_id="batch-001",
        events=[
            {
                "event_type": "reply_received",
                "recipient_hash": "recipient-a",
                "preview": "Interested. Can you show me a Vienna example?",
                "raw_body": "Full reply must not be stored here.",
            },
            {
                "event_type": "unsubscribe",
                "recipient_hash": "recipient-b",
                "raw_body": "Remove me.",
            },
        ],
    )

    assert receipt["contract_name"] == SENDR_ENGAGEMENT_BATCH_CONTRACT
    assert receipt["status"] == "review_required"
    assert receipt["events"][0]["raw_body_stored"] is False
    assert receipt["events"][0]["human_review_required"] is True
    assert "raw_body" not in receipt["events"][0]
    assert receipt["propertyquarry_actions"]["partner_lead_candidates"] == 1
    assert receipt["propertyquarry_actions"]["draft_reply_candidates"] == 1
    assert receipt["propertyquarry_actions"]["suppression_updates"] == 1
