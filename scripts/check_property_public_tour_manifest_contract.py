#!/usr/bin/env python3
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.api.routes import public_tour_payloads, public_tours
from app.product import property_tour_hosting


FORBIDDEN_PUBLIC_TOP_LEVEL_KEYS = {
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

LEGACY_PREVIEW_BYPASS_PREFIXES = (
    "telegram-preview",
    "diorama-preview",
    "magicfit-still",
)


def main() -> int:
    failures: list[str] = []

    public_keys = set(public_tour_payloads._PUBLIC_TOUR_TOP_LEVEL_KEYS)
    leaked = sorted(public_keys & FORBIDDEN_PUBLIC_TOP_LEVEL_KEYS)
    if leaked:
        failures.append(f"public tour top-level allowlist exposes private keys: {', '.join(leaked)}")
    if not hasattr(public_tour_payloads, "PublicTourManifest"):
        failures.append("public tour payloads must expose an explicit PublicTourManifest contract")
    if not hasattr(public_tour_payloads, "PrivateTourReceipt"):
        failures.append("public tour payloads must expose an explicit PrivateTourReceipt contract")
    if not hasattr(public_tour_payloads, "build_public_tour_manifest"):
        failures.append("public tour payloads must expose a public manifest builder")

    redactor_source = inspect.getsource(public_tour_payloads.redacted_public_tour_payload)
    if "_PUBLIC_TOUR_TOP_LEVEL_KEYS" not in redactor_source:
        failures.append("public tour payload redactor must be driven by the positive top-level allowlist")
    if "public_tour_allowed_asset_paths(payload)" not in redactor_source:
        failures.append("public tour video relpaths must be checked against the public asset manifest")

    asset_source = inspect.getsource(public_tours._asset_file)
    if "_public_tour_manifest(payload)" not in asset_source or "safe_relpath not in manifest" not in asset_source:
        failures.append("public tour file serving must be anchored to the public asset manifest")
    for prefix in LEGACY_PREVIEW_BYPASS_PREFIXES:
        if prefix in asset_source:
            failures.append(f"public tour file serving must not allow filename-prefix bypass {prefix!r}")

    payload_route_source = inspect.getsource(public_tours.public_tour_payload)
    if "include_external_tour_urls=False" not in payload_route_source:
        failures.append("raw public tour JSON route must not include external provider/source URLs")
    if "expose_asset_relpaths=False" not in payload_route_source:
        failures.append("raw public tour JSON route must expose manifest assets, not raw relpaths")

    writer_source = inspect.getsource(property_tour_hosting._write_hosted_property_tour_payload)
    public_builder_source = inspect.getsource(property_tour_hosting._public_tour_public_payload)
    private_receipt_source = inspect.getsource(property_tour_hosting._public_tour_private_receipt)
    if "_public_tour_public_payload(payload)" not in writer_source:
        failures.append("hosted public tour writer must construct tour.json through the public manifest builder")
    if "build_public_tour_manifest" not in public_builder_source:
        failures.append("hosted public tour writer must use the explicit PublicTourManifest builder")
    if "PrivateTourReceipt" not in private_receipt_source:
        failures.append("hosted public tour writer must use the explicit PrivateTourReceipt contract")
    if "tour.private.json" not in writer_source and "_public_tour_private_manifest_path" not in writer_source:
        failures.append("hosted public tour writer must keep private receipt data outside raw tour.json")

    if failures:
        print("property public tour manifest contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property public tour manifest contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
