from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.domain.property.sendr_campaign import (
    ALLOWED_SENDR_RECIPIENT_BASIS,
    ALLOWED_SENDR_SOURCE_CLASSIFICATIONS,
    FORBIDDEN_SENDR_RECIPIENT_BASIS,
    SENDR_CAMPAIGN_PACKET_CONTRACT,
    SENDR_CAMPAIGN_RECEIPT_CONTRACT,
    SENDR_ENGAGEMENT_BATCH_CONTRACT,
    SUPPORTED_SENDR_CAMPAIGN_TYPES,
    canonical_json,
    sendr_campaign_packet_sha256,
    sendr_campaign_text_index,
    sha256_json,
    sha256_text,
    utc_now_iso,
)


BLOCKED_CLAIM_PHRASES = (
    "best property",
    "guaranteed fit",
    "guaranteed viewing success",
    "safe neighbourhood",
    "safe neighborhood",
    "risk-free investment",
    "we know the correct price",
    "verify every fact",
    "exclusive inventory",
    "legal advice",
    "individualized financial advice",
    "guaranteed return",
    "undervalued investment",
)

BLOCKED_PRIVACY_KEYS = (
    "raw_provider_payload",
    "portal_credentials",
    "private_user_profile",
    "private_preference_profile",
    "private_feedback_history",
    "exact_private_commute_destination",
    "private_saved_search_name",
    "payment_data",
    "billing_entitlement",
    "seller_private_contact",
    "agent_private_contact",
    "medical_notes",
    "family_details",
    "children_details",
)

BLOCKED_FAIR_HOUSING_PHRASES = (
    "protected-class targeting",
    "safe for families like you",
    "avoid this type of people",
    "christian neighbourhood",
    "muslim neighbourhood",
    "white neighbourhood",
    "not suitable for foreigners",
    "religion-coded",
    "race-coded",
)


def _env_enabled(env: dict[str, str] | None, name: str) -> bool:
    source = os.environ if env is None else env
    return str(source.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _pass_fail(condition: bool) -> str:
    return "pass" if condition else "fail"


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _contains_any(text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = str(text or "").lower()
    return [phrase for phrase in phrases if phrase in lowered]


def _collect_private_key_findings(value: object, *, path: str = "$") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip()
            lowered = key_text.lower()
            if any(token in lowered for token in BLOCKED_PRIVACY_KEYS):
                findings.append({"code": "private_data_blocked", "path": f"{path}.{key_text}", "detail": key_text})
            findings.extend(_collect_private_key_findings(item, path=f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_collect_private_key_findings(item, path=f"{path}[{index}]"))
    return findings


def validate_propertyquarry_sendr_campaign_packet(
    packet: dict[str, object],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    checks: dict[str, str] = {}
    findings: list[dict[str, str]] = []
    packet = dict(packet or {})
    campaign_type = str(packet.get("campaign_type") or "").strip().upper()
    source_material = [_as_dict(row) for row in _as_list(packet.get("source_material"))]
    recipient_policy = _as_dict(packet.get("recipient_policy"))
    channels = _as_dict(packet.get("channels"))
    features = _as_dict(packet.get("sendr_features_allowed"))
    allowed_bases = {str(item or "").strip() for item in _as_list(recipient_policy.get("allowed_recipient_basis")) if str(item or "").strip()}
    forbidden_bases = {str(item or "").strip() for item in _as_list(recipient_policy.get("forbidden_recipient_basis")) if str(item or "").strip()}

    checks["contract"] = _pass_fail(packet.get("contract_name") == SENDR_CAMPAIGN_PACKET_CONTRACT)
    checks["campaign_type"] = _pass_fail(campaign_type in SUPPORTED_SENDR_CAMPAIGN_TYPES)
    checks["source_packet_hash"] = _pass_fail(
        str(packet.get("source_packet_sha256") or "") in {"", sendr_campaign_packet_sha256(packet)}
    )
    checks["source_material"] = _pass_fail(
        bool(source_material)
        and all(str(row.get("classification") or "").strip() in ALLOWED_SENDR_SOURCE_CLASSIFICATIONS for row in source_material)
    )
    checks["recipient_basis_policy"] = _pass_fail(
        bool(allowed_bases)
        and allowed_bases <= set(ALLOWED_SENDR_RECIPIENT_BASIS)
        and forbidden_bases >= set(FORBIDDEN_SENDR_RECIPIENT_BASIS)
        and not (allowed_bases & set(FORBIDDEN_SENDR_RECIPIENT_BASIS))
    )
    checks["email_or_linkedin_only"] = _pass_fail(
        bool(channels.get("email") or channels.get("linkedin"))
        and not bool(channels.get("whatsapp"))
        and not bool(features.get("whatsapp"))
    )
    checks["no_direct_send"] = _pass_fail(
        not bool(packet.get("direct_send_allowed"))
        and not _env_enabled(env, "PROPERTYQUARRY_SENDR_DIRECT_SEND_ENABLED")
    )
    checks["no_auto_reply"] = _pass_fail(
        not bool(packet.get("auto_reply_allowed"))
        and not _env_enabled(env, "PROPERTYQUARRY_SENDR_AUTO_REPLY_ENABLED")
    )
    checks["human_review"] = _pass_fail(bool(packet.get("human_review_required")) is True)

    recipients = [_as_dict(row) for row in _as_list(packet.get("recipients"))]
    recipient_failures = []
    for index, recipient in enumerate(recipients):
        basis = str(recipient.get("recipient_basis") or "").strip()
        channel = str(recipient.get("allowed_channel") or "").strip().lower()
        if basis not in ALLOWED_SENDR_RECIPIENT_BASIS or basis in FORBIDDEN_SENDR_RECIPIENT_BASIS:
            recipient_failures.append(f"recipient_{index}_basis")
        if not str(recipient.get("source_url_or_note") or "").strip():
            recipient_failures.append(f"recipient_{index}_source")
        if not str(recipient.get("jurisdiction") or "").strip():
            recipient_failures.append(f"recipient_{index}_jurisdiction")
        if channel not in {"email", "linkedin"}:
            recipient_failures.append(f"recipient_{index}_channel")
        if str(recipient.get("suppression_status") or "").strip().lower() in {"suppressed", "unsubscribe", "complaint"}:
            recipient_failures.append(f"recipient_{index}_suppressed")
    checks["recipients"] = _pass_fail(not recipient_failures)
    findings.extend({"code": code, "path": "$.recipients", "detail": code} for code in recipient_failures)

    scan_packet = dict(packet)
    scan_packet.pop("forbidden_claims", None)
    scan_recipient_policy = _as_dict(scan_packet.get("recipient_policy"))
    scan_recipient_policy.pop("forbidden_recipient_basis", None)
    if scan_recipient_policy:
        scan_packet["recipient_policy"] = scan_recipient_policy
    text_index = sendr_campaign_text_index(scan_packet)
    for code, phrases in (
        ("claim_validation", BLOCKED_CLAIM_PHRASES),
        ("privacy", ()),
        ("fair_housing", BLOCKED_FAIR_HOUSING_PHRASES),
    ):
        matches = _contains_any(text_index, phrases)
        if code == "privacy":
            privacy_findings = _collect_private_key_findings(packet)
            checks[code] = _pass_fail(not privacy_findings)
            findings.extend(privacy_findings)
            continue
        checks[code] = _pass_fail(not matches)
        findings.extend({"code": f"{code}_blocked", "path": "$", "detail": match} for match in matches)

    checks["financial_legal_language"] = checks["claim_validation"]
    checks["suppression"] = _pass_fail("suppression_status" in canonical_json(packet) or not recipients)
    status = "pass" if all(value == "pass" for value in checks.values()) else "fail"
    return {"status": status, "checks": checks, "findings": findings}


def materialize_propertyquarry_sendr_campaign_receipt(
    packet: dict[str, object],
    *,
    reviewer: str = "operator",
    reviewed_at: str = "",
    max_contacts: int = 50,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    validation = validate_propertyquarry_sendr_campaign_packet(packet, env=env)
    passed = validation["status"] == "pass"
    allowed_claims = [str(item or "").strip() for item in _as_list(packet.get("allowed_claims")) if str(item or "").strip()]
    message_copy = "\n".join(str(item or "").strip() for item in _as_list(packet.get("message_copy")) if str(item or "").strip())
    page_template = str(packet.get("personalized_page_template") or "").strip()
    video_script = str(packet.get("video_script") or "").strip()
    recipient_bases = sorted(
        {
            str(row.get("recipient_basis") or "").strip()
            for row in [_as_dict(item) for item in _as_list(packet.get("recipients"))]
            if str(row.get("recipient_basis") or "").strip()
        }
        or {
            str(item or "").strip()
            for item in _as_list(_as_dict(packet.get("recipient_policy")).get("allowed_recipient_basis"))
            if str(item or "").strip()
        }
    )
    return {
        "contract_name": SENDR_CAMPAIGN_RECEIPT_CONTRACT,
        "status": "pilot_approved" if passed else "blocked",
        "provider": "sendr",
        "license_tier": "AppSumo Tier 4",
        "packet_id": str(packet.get("packet_id") or ""),
        "campaign_type": str(packet.get("campaign_type") or ""),
        "source_packet_sha256": sendr_campaign_packet_sha256(packet),
        "approved_claims_sha256": sha256_json(allowed_claims),
        "message_copy_sha256": sha256_text(message_copy),
        "personalized_page_template_sha256": sha256_text(page_template),
        "video_script_sha256": sha256_text(video_script),
        "recipient_policy": {
            "recipient_count": len(_as_list(packet.get("recipients"))),
            "recipient_basis": recipient_bases,
            "blocked_recipient_count": len([item for item in validation["findings"] if str(item.get("code") or "").startswith("recipient_")]),
            "suppression_checked": validation["checks"].get("suppression") == "pass",
        },
        "channels": {
            "email": bool(_as_dict(packet.get("channels")).get("email")),
            "linkedin": bool(_as_dict(packet.get("channels")).get("linkedin")),
            "whatsapp": False,
        },
        "validation": validation["checks"],
        "findings": validation["findings"],
        "human_review": {
            "reviewer": str(reviewer or "operator"),
            "reviewed_at": str(reviewed_at or utc_now_iso()),
            "approval_scope": f"pilot_{int(max_contacts)}_contacts" if passed else "blocked",
        },
        "direct_send_allowed": False,
        "limited_send_allowed": bool(passed),
        "max_contacts": int(max_contacts),
        "auto_reply_allowed": False,
    }


def materialize_propertyquarry_sendr_engagement_receipt(
    *,
    campaign_id: str,
    events: list[dict[str, object]],
    event_batch_id: str = "",
) -> dict[str, object]:
    safe_events: list[dict[str, object]] = []
    suppression_updates = 0
    partner_leads = 0
    demo_requests = 0
    draft_replies = 0
    for index, event in enumerate(events or []):
        row = _as_dict(event)
        event_type = str(row.get("event_type") or "").strip().lower()
        if event_type in {"unsubscribe", "complaint", "bounce"}:
            suppression_updates += 1
        if event_type in {"reply_received", "meeting_booked"}:
            partner_leads += 1
        if event_type == "meeting_booked":
            demo_requests += 1
        if event_type == "reply_received":
            draft_replies += 1
        safe_events.append(
            {
                "event_type": event_type,
                "recipient_hash": str(row.get("recipient_hash") or sha256_text(str(index))).strip(),
                "occurred_at": str(row.get("occurred_at") or utc_now_iso()).strip(),
                "preview": str(row.get("preview") or "")[:240],
                "raw_body_stored": False,
                "human_review_required": event_type in {"reply_received", "meeting_booked", "complaint"},
            }
        )
    return {
        "contract_name": SENDR_ENGAGEMENT_BATCH_CONTRACT,
        "status": "review_required" if safe_events else "empty",
        "campaign_id": str(campaign_id or ""),
        "event_batch_id": str(event_batch_id or sha256_text(canonical_json(safe_events))),
        "events": safe_events,
        "propertyquarry_actions": {
            "partner_lead_candidates": partner_leads,
            "demo_request_candidates": demo_requests,
            "draft_reply_candidates": draft_replies,
            "suppression_updates": suppression_updates,
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
