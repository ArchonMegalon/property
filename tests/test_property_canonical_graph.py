from __future__ import annotations

from app.product.property_canonical_graph import build_property_passport_snapshot


def test_property_passport_links_relisted_property_and_records_price_change() -> None:
    runs = [
        {
            "run_id": "run-1",
            "updated_at": "2026-06-01T10:00:00+00:00",
            "sources": [
                {
                    "source_label": "Willhaben",
                    "top_candidates": [
                        {
                            "title": "Bright 3-room apartment",
                            "property_url": "https://www.willhaben.at/iad/object?adId=old-token",
                            "listing_id": "old-token",
                            "property_facts": {
                                "country_code": "AT",
                                "postal_name": "1190 Wien",
                                "street_address": "Hameaustrasse 34",
                                "area_sqm": 70,
                                "rooms": 3,
                                "total_rent_eur": 1500,
                                "has_floorplan": False,
                            },
                        }
                    ],
                }
            ],
        },
        {
            "run_id": "run-2",
            "updated_at": "2026-06-10T10:00:00+00:00",
            "sources": [
                {
                    "source_label": "Broker",
                    "top_candidates": [
                        {
                            "title": "Bright 3-room apartment relisted",
                            "property_url": "https://broker.example/listings/relisted?utm=secret",
                            "listing_id": "relisted",
                            "property_facts": {
                                "country_code": "AT",
                                "postal_name": "1190 Wien",
                                "street_address": "Hameaustrasse 34",
                                "area_sqm": 70,
                                "rooms": 3,
                                "total_rent_eur": 1450,
                                "has_floorplan": True,
                            },
                        }
                    ],
                }
            ],
        },
    ]

    snapshot = build_property_passport_snapshot(principal_id="pq-passport", runs=runs)
    payload = snapshot.as_public_dict()

    assert payload["property_count"] == 1
    assert payload["listing_instance_count"] == 2
    assert payload["change_event_count"] >= 2
    assert payload["properties"][0]["listing_count"] == 2
    assert "utm=secret" not in str(payload)
    assert any(row["field"] == "total_rent_eur" and row["current_value"] == 1450 for row in payload["recent_changes"])
    assert any(row["field"] == "has_floorplan" and row["current_value"] is True for row in payload["recent_changes"])
    assert {row["provider"] for row in payload["listing_instances"]} == {"Willhaben", "Broker"}


def test_property_passport_falls_back_to_listing_identity_without_location_facts() -> None:
    snapshot = build_property_passport_snapshot(
        principal_id="pq-passport",
        runs=[
            {
                "run_id": "run-1",
                "sources": [
                    {
                        "source_label": "Provider",
                        "top_candidates": [
                            {
                                "title": "Sparse listing",
                                "property_url": "https://provider.example/property/1?session=abc",
                                "property_facts": {"rooms": 2},
                            }
                        ],
                    }
                ],
            }
        ],
    )

    payload = snapshot.as_public_dict()

    assert payload["property_count"] == 1
    assert payload["listing_instance_count"] == 1
    assert payload["properties"][0]["identity_key"] == "listing:https://provider.example/property/1"
    assert payload["listing_instances"][0]["listing_url"] == "https://provider.example/property/1"
