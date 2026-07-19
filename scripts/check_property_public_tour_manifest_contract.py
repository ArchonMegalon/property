#!/usr/bin/env python3
from __future__ import annotations

import ast
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


def _named_calls(source: str, function_name: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == function_name
    ]


def _is_name(node: ast.expr | None, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _control_render_call_threads_request_context(call: ast.Call) -> bool:
    if not call.args or not _is_name(call.args[0], "rendered_payload"):
        return False
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
    return all(
        _is_name(keywords.get(keyword), expected)
        for keyword, expected in (
            ("viewer_mode", "viewer_mode"),
            ("fullscreen", "fullscreen"),
            ("nonce", "nonce"),
        )
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
    delegated_writer_source = inspect.getsource(
        property_tour_hosting._write_hosted_property_tour_payload_with_slug_lock_held
    )
    atomic_writer_source = inspect.getsource(
        property_tour_hosting._write_hosted_property_tour_manifests_atomic
    )
    public_builder_source = inspect.getsource(property_tour_hosting._public_tour_public_payload)
    private_receipt_source = inspect.getsource(property_tour_hosting._public_tour_private_receipt)
    if "_write_hosted_property_tour_payload_with_slug_lock_held" not in writer_source:
        failures.append("hosted public tour writer must delegate while holding the slug publication lock")
    if "_public_tour_public_payload(payload)" not in delegated_writer_source:
        failures.append("hosted public tour writer must construct tour.json through the public manifest builder")
    if "build_public_tour_manifest" not in public_builder_source:
        failures.append("hosted public tour writer must use the explicit PublicTourManifest builder")
    if "PrivateTourReceipt" not in private_receipt_source:
        failures.append("hosted public tour writer must use the explicit PrivateTourReceipt contract")
    if "_public_tour_private_receipt(payload)" not in delegated_writer_source:
        failures.append("hosted public tour writer must construct the private receipt separately")
    if (
        "_write_hosted_property_tour_manifests_atomic" not in delegated_writer_source
        or "_PROPERTY_PUBLIC_TOUR_PRIVATE_MANIFEST" not in atomic_writer_source
    ):
        failures.append("hosted public tour writer must keep private receipt data outside raw tour.json")

    landing_source = inspect.getsource(__import__("app.api.routes.landing", fromlist=["_propertyquarry_example_media_targets"])._propertyquarry_example_media_targets)
    if "_hosted_property_tour_verified_open_url" not in landing_source:
        failures.append("PropertyQuarry example media targets must only expose verified hosted tour controls")
    if "/control/{control_provider}" in landing_source or "_manifest_control_provider" in landing_source:
        failures.append("PropertyQuarry example media targets must not infer ready controls directly from public manifest keys")

    control_viewer_source = inspect.getsource(public_tours.public_tour_control_viewer)
    control_render_calls = _named_calls(control_viewer_source, "_tour_control_html")
    if not control_render_calls or not all(
        _control_render_call_threads_request_context(call) for call in control_render_calls
    ):
        failures.append(
            "forced public tour provider routes must render the requested provider control "
            "with viewer mode, fullscreen state, and CSP nonce or fail closed"
        )
    if _named_calls(control_viewer_source, "_tour_html"):
        failures.append("forced public tour provider routes must not fall back to the generic tour shell")

    if failures:
        print("property public tour manifest contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property public tour manifest contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
