from __future__ import annotations

import json

from scripts.verify_property_sent_links_manifest import verify_sent_links_manifest


def test_sent_links_manifest_gate_accepts_matterport_and_3dvista_links(tmp_path) -> None:
    manifest = tmp_path / "sent-links.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "title": "Matterport property",
                    "tour_url": "https://propertyquarry.com/tours/property-1/matterport",
                    "direct_tour_url": "https://my.matterport.com/show/?m=abc",
                    "flythrough_url": "https://propertyquarry.com/tours/property-1/flythrough",
                },
                {
                    "title": "3DVista property",
                    "tour_url": "https://propertyquarry.com/tours/property-2/3dvista",
                    "direct_tour_url": "https://propertyquarry.com/tours/property-2/3dvista/index.html",
                    "direct_flythrough_url": "https://propertyquarry.com/tours/property-2/flythrough.mp4",
                },
            ]
        ),
        encoding="utf-8",
    )

    receipt = verify_sent_links_manifest(manifest)

    assert receipt["status"] == "passed"
    assert receipt["failures"] == []


def test_sent_links_manifest_gate_rejects_cube_marzipano_and_dummy_fallbacks(tmp_path) -> None:
    manifest = tmp_path / "sent-links.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "title": "Bad cube property",
                    "tour_url": "https://propertyquarry.com/tours/property-1/cubeviewer",
                    "direct_tour_url": "https://propertyquarry.com/tours/property-1/marzipano",
                    "flythrough_url": "https://propertyquarry.com/tours/property-1/fallback.mp4",
                }
            ]
        ),
        encoding="utf-8",
    )

    receipt = verify_sent_links_manifest(manifest)

    assert receipt["status"] == "failed"
    assert any("forbidden_fallback_marker" in failure for failure in receipt["failures"])
