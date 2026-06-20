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
    }

    assert forbidden.isdisjoint(public_tour_payloads._PUBLIC_TOUR_TOP_LEVEL_KEYS)


def test_public_tour_manifest_contract_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_property_public_tour_manifest_contract.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ok: property public tour manifest contract" in result.stdout
