from __future__ import annotations

from app.services.property_content_packet_builder import build_product_tutorial_source_packet
from app.services.property_content_privacy import validate_property_content_privacy


def test_property_content_privacy_blocks_user_email_payment_and_private_profile() -> None:
    packet = build_product_tutorial_source_packet(title="Privacy test")
    packet["user_email"] = "buyer@example.com"
    packet["payment_card"] = "4242 4242 4242 4242"
    packet["privacy"] = {"user_identity_included": True, "private_profile_included": True}

    report = validate_property_content_privacy(packet)

    assert report["status"] == "fail"
    codes = {item["code"] for item in report["findings"]}
    assert "private_key_blocked" in codes
    assert "email_value_blocked" in codes
    assert "payment_value_blocked" in codes
    assert "user_identity_included" in codes
    assert "private_profile_included" in codes


def test_property_content_privacy_accepts_approved_preference_projection() -> None:
    packet = build_product_tutorial_source_packet(title="Projection test")
    packet["fit"] = {"approved_preferences": ["lift required", "public transit important"]}

    report = validate_property_content_privacy(packet)

    assert report["status"] == "pass"

