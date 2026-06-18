from __future__ import annotations

import pytest

from app.domain.property.content_source_packet import (
    CONTENT_MODE_PRIVATE_SHORTLIST_VIDEO_BETA,
    PropertyContentPacketError,
    build_property_content_source_packet,
    source_packet_sha256,
)
from app.services.property_content_packet_builder import (
    build_product_tutorial_source_packet,
    build_synthetic_dossier_source_packet,
)
from app.services.property_content_validation import validate_property_content_source_packet


def test_product_tutorial_packet_is_public_safe_and_hash_bound() -> None:
    packet = build_product_tutorial_source_packet(title="How to Read a PropertyQuarry Dossier")

    assert packet["contract_name"] == "propertyquarry.video_source_packet.v1"
    assert packet["content_mode"] == "PRODUCT_TUTORIAL"
    assert packet["subscribr_channel_key"] == "propertyquarry-academy"
    assert packet["publication_allowed"] is False
    assert packet["production_allowed"] is False
    assert packet["source_packet_sha256"] == source_packet_sha256(packet)
    assert validate_property_content_source_packet(packet)["status"] == "pass"


def test_property_dossier_packet_requires_snapshot_source_binding_and_unknowns() -> None:
    packet = build_synthetic_dossier_source_packet()
    report = validate_property_content_source_packet(packet)

    assert report["status"] == "pass"
    assert packet["research_policy"] == "provided_sources_only"
    assert packet["property_snapshot"]["run_id"] == "synthetic-run"
    assert packet["unknowns"]
    assert packet["human_review_required"] is True


def test_property_dossier_packet_without_snapshot_fails() -> None:
    packet = build_property_content_source_packet(
        packet_id="bad-dossier",
        content_mode="PROPERTY_DOSSIER",
        title="Bad dossier",
        sources=[],
        unknowns=[],
    )

    report = validate_property_content_source_packet(packet)

    assert report["status"] == "fail"
    assert report["checks"]["property_snapshot"] == "fail"
    assert report["checks"]["source_binding"] == "fail"


def test_private_shortlist_video_beta_is_not_enabled() -> None:
    with pytest.raises(PropertyContentPacketError):
        build_property_content_source_packet(
            packet_id="private-beta",
            content_mode=CONTENT_MODE_PRIVATE_SHORTLIST_VIDEO_BETA,
            title="Private shortlist",
        )

