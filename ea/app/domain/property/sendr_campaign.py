from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


SENDR_CAMPAIGN_PACKET_CONTRACT = "propertyquarry.sendr_campaign_packet.v1"
SENDR_CAMPAIGN_RECEIPT_CONTRACT = "propertyquarry.sendr_campaign_receipt.v1"
SENDR_ENGAGEMENT_BATCH_CONTRACT = "propertyquarry.sendr_engagement_batch.v1"

SUPPORTED_SENDR_CAMPAIGN_TYPES = (
    "RELOCATION_PARTNER_OUTREACH",
    "BUYER_SCOUT_OUTREACH",
    "AGENT_TIER_PILOT",
    "CITY_GUIDE_PROMOTION",
    "PROPERTYQUARRY_DEMO_BOOKING",
    "PARTNER_AFFILIATE_OUTREACH",
)

ALLOWED_SENDR_RECIPIENT_BASIS = (
    "public_business_contact",
    "prior_conversation",
    "inbound_lead",
    "opt_in_waitlist",
    "event_context",
    "manual_partner_shortlist",
    "referral",
    "existing_business_relationship",
)

FORBIDDEN_SENDR_RECIPIENT_BASIS = (
    "scraped_private_profile",
    "private_whatsapp_export",
    "raw_ea_inbox",
    "purchased_personal_list_without_lawful_basis",
)

ALLOWED_SENDR_SOURCE_CLASSIFICATIONS = (
    "approved_public",
    "public_demo_synthetic",
    "reviewed_public",
    "approved_demo_packet",
    "approved_product_brief",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sendr_campaign_packet_sha256(packet: dict[str, object]) -> str:
    clean = dict(packet or {})
    clean.pop("source_packet_sha256", None)
    return sha256_json(clean)


def sendr_campaign_text_index(packet: dict[str, object]) -> str:
    fragments: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            fragments.append(value)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(packet)
    return "\n".join(fragment.strip() for fragment in fragments if fragment and fragment.strip())
