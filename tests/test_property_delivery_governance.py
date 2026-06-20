from __future__ import annotations

from app.product.property_delivery_governance import (
    PROPERTY_DELIVERY_CHANNEL_POLICIES,
    property_delivery_channel_policy,
    property_delivery_governance_rows,
)


def test_property_delivery_channel_policies_cover_email_telegram_whatsapp() -> None:
    policies = {policy.channel_key: policy for policy in PROPERTY_DELIVERY_CHANNEL_POLICIES}

    assert set(policies) == {"email", "telegram", "whatsapp"}
    assert all(policy.verified_destination_required for policy in policies.values())
    assert all(policy.opt_in_required for policy in policies.values())
    assert all(policy.quiet_hours_supported for policy in policies.values())
    assert all(policy.receipt_required for policy in policies.values())
    assert policies["whatsapp"].stop_start_supported is True
    assert policies["email"].suppression_required is True


def test_property_delivery_governance_rows_mark_enabled_channels() -> None:
    rows = property_delivery_governance_rows(["telegram", "whatsapp"])
    by_key = {str(row["channel_key"]): row for row in rows}

    assert by_key["email"]["tag"] == "Off"
    assert by_key["telegram"]["tag"] == "Enabled"
    assert by_key["whatsapp"]["tag"] == "Enabled"
    assert "STOP/START" in str(by_key["whatsapp"]["detail"])
    assert property_delivery_channel_policy("unknown") is None
