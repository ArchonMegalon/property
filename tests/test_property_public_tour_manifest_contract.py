from __future__ import annotations

import subprocess
import sys

from app.api.routes import public_tour_payloads


def test_public_tour_manifest_allowlist_excludes_private_source_fields() -> None:
    forbidden = {
        "brief",
        "listing_url",
        "property_url",
        "source_url",
        "source_ref",
        "external_id",
        "principal_id",
        "recipient_email",
        "source_virtual_tour_url",
        "source_virtual_tour_origin",
        "panorama_source",
        "three_d_vista_url",
        "matterport_url",
        "exact_address",
        "map_lat",
        "map_lng",
        "video_provider",
        "video_provider_key",
        "video_render_provider",
        "video_coverage_proof",
    }

    assert forbidden.isdisjoint(public_tour_payloads._PUBLIC_TOUR_TOP_LEVEL_KEYS)


def test_governed_public_projection_drops_external_media_and_embedded_authority_marker() -> None:
    payload = {
        "slug": "governed-tour",
        "title": "Governed tour",
        "governed_spatial": {
            "artifact_verified": True,
            "private_url": "https://private.invalid/task",
        },
        "scenes": [
            {
                "scene_id": "scene-1",
                "role": "live_360",
                "image_url": "https://provider.invalid/private-asset.jpg",
            }
        ],
    }

    projection = public_tour_payloads.build_public_tour_manifest(
        payload,
        url_allowed=lambda _value: True,
        bundle_dir_resolver=lambda _slug: None,
    ).as_dict()

    assert projection["scenes"] == []
    assert "governed_spatial" not in projection
    assert "private.invalid" not in str(projection)
    assert "provider.invalid" not in str(projection)


def test_public_tour_manifest_contract_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_public_tour_manifest_contract.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ok: property public tour manifest contract" in result.stdout
