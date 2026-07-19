from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.routes.public_tours import (
    _pano2vr_control_url,
    _pano2vr_export_file,
    _pano2vr_spatial_provenance_errors_cached,
    _tour_html,
)
from app.product.property_tour_hosting import _write_hosted_property_tour_payload
from scripts.property_tour_panorama_provenance import (
    KRPANO_SPATIAL_PROVENANCE_KEY,
    PANORAMA_SPATIAL_PROVENANCE_SCHEMA,
    PANO2VR_SPATIAL_PROVENANCE_KEY,
    asset_set_sha256,
    export_tree_sha256,
    panorama_asset_relpaths,
    pano2vr_export_topology,
    walkable_scene_topology,
)
from scripts.verify_property_tour_controls import build_property_tour_control_receipt


def _spatial_receipt(
    *,
    slug: str,
    provider: str,
    artifact: dict[str, object],
    topology: dict[str, object],
    projection: str = "equirectangular",
) -> dict[str, object]:
    return {
        "schema": PANORAMA_SPATIAL_PROVENANCE_SCHEMA,
        "status": "pass",
        "provider": provider,
        "target_slug": slug,
        "artifact": artifact,
        "capture": {
            "source_kind": "camera_equirectangular",
            "projection": projection,
            **topology,
        },
        "authorization": {
            "status": "approved",
            "reference": f"camera-release:{slug}",
        },
        "review": {
            "property_match": "pass",
            "visual_match": "pass",
            "spatial_capture_match": "pass",
            "flat_composite_absent": True,
            "reviewed_by": "property-tour-reviewer",
            "reviewed_at": "2026-07-18T12:00:00+00:00",
        },
    }


def _write_pano2vr_bundle(
    root: Path,
    slug: str,
    *,
    walkable: bool = False,
    connected_scenes: bool = False,
    include_receipt: bool = True,
) -> Path:
    bundle = root / slug
    export_dir = bundle / "pano"
    export_dir.mkdir(parents=True)
    payload: dict[str, object] = {
        "slug": slug,
        "title": slug,
        "pano2vr_entry_relpath": "pano/index.html",
    }
    if walkable:
        payload.update(
            {
                "scene_strategy": "walkable_panorama",
                "creation_mode": "hosted_walkable_360",
            }
        )
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    (export_dir / "index.html").write_text(
        "<!doctype html><script src='tour.js'></script><span>pano.xml</span>",
        encoding="utf-8",
    )
    (export_dir / "tour.js").write_text("window.ggskin = true;", encoding="utf-8")
    xml = (
        "<tour>"
        "<panorama id='node1'><hotspots><hotspot url='{node2}' /></hotspots></panorama>"
        "<panorama id='node2'><hotspots><hotspot url='{node1}' /></hotspots></panorama>"
        "</tour>"
        if connected_scenes
        else "<panorama id='node1'><hotspots /></panorama>"
    )
    (export_dir / "pano.xml").write_text(xml, encoding="utf-8")
    if include_receipt:
        topology = pano2vr_export_topology(export_dir)
        private_payload = {
            PANO2VR_SPATIAL_PROVENANCE_KEY: _spatial_receipt(
                slug=slug,
                provider="pano2vr",
                artifact={
                    "kind": "local_export",
                    "sha256": export_tree_sha256(export_dir),
                    "entry_relpath": "index.html",
                },
                topology=topology,
            )
        }
        (bundle / "tour.private.json").write_text(
            json.dumps(private_payload),
            encoding="utf-8",
        )
    return bundle


def _write_krpano_bundle(
    root: Path,
    slug: str,
    *,
    walkable: bool = False,
    connected_scenes: bool = False,
    include_receipt: bool = True,
) -> Path:
    bundle = root / slug
    panorama_path = bundle / "krpano" / "panorama.jpg"
    panorama_path.parent.mkdir(parents=True)
    Image.new("RGB", (2048, 1024), color=(12, 31, 45)).save(
        panorama_path,
        format="JPEG",
    )
    second_panorama_path = bundle / "krpano" / "living.jpg"
    if connected_scenes:
        Image.new("RGB", (2048, 1024), color=(22, 41, 55)).save(
            second_panorama_path,
            format="JPEG",
        )
    walkable_scene: dict[str, object] = {
        "projection": "equirectangular",
        "panorama_relpath": "krpano/panorama.jpg",
    }
    if connected_scenes:
        walkable_scene = {
            "projection": "equirectangular",
            "scenes": [
                {
                    "id": "entry",
                    "panorama_relpath": "krpano/panorama.jpg",
                    "hotspots": [{"target_scene": "living"}],
                },
                {
                    "id": "living",
                    "panorama_relpath": "krpano/living.jpg",
                    "hotspots": [{"target_scene": "entry"}],
                },
            ],
        }
    payload: dict[str, object] = {
        "slug": slug,
        "title": slug,
        "scene_strategy": "walkable_panorama" if walkable else "single_panorama",
        "creation_mode": "hosted_walkable_360" if walkable else "hosted_panorama_360",
        "walkable_scene": walkable_scene,
    }
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    if include_receipt:
        private_payload = {
            KRPANO_SPATIAL_PROVENANCE_KEY: _spatial_receipt(
                slug=slug,
                provider="krpano",
                artifact={
                    "kind": "panorama_assets",
                    "sha256": asset_set_sha256(
                        bundle,
                        panorama_asset_relpaths(payload),
                    ),
                    "entry_relpath": "",
                },
                topology=walkable_scene_topology(payload),
            )
        }
        (bundle / "tour.private.json").write_text(
            json.dumps(private_payload),
            encoding="utf-8",
        )
    return bundle


def _tour_row(receipt: dict[str, object]) -> dict[str, object]:
    rows = receipt.get("tours")
    assert isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
    return rows[0]


def test_marker_only_pano2vr_export_fails_closed(tmp_path: Path) -> None:
    _write_pano2vr_bundle(tmp_path, "marker-only", include_receipt=False)

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["pano2vr"] == 0
    blocker = receipt["provider_blockers"]["pano2vr"]["reasons"][0]
    assert blocker["reason"] == "pano2vr_spatial_provenance_missing_or_invalid"


def test_one_node_pano2vr_receipt_cannot_satisfy_walkable_claim(tmp_path: Path) -> None:
    _write_pano2vr_bundle(tmp_path, "one-node-walkable", walkable=True)

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["pano2vr"] == 0
    blocker = receipt["provider_blockers"]["pano2vr"]["reasons"][0]
    assert blocker["reason"] == "pano2vr_spatial_provenance_missing_or_invalid"


def test_connected_pano2vr_receipt_satisfies_walkable_claim(tmp_path: Path) -> None:
    _write_pano2vr_bundle(
        tmp_path,
        "connected-walkable",
        walkable=True,
        connected_scenes=True,
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["pano2vr"] == 1
    control = _tour_row(receipt)["controls"][0]
    assert control["evidence"] == "provenance_bound_pano2vr_spatial_export"


def test_ratio_only_krpano_asset_without_receipt_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_krpano_bundle(tmp_path, "ratio-only", include_receipt=False)

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["krpano"] == 0
    blocker = receipt["provider_blockers"]["krpano"]["reasons"][0]
    assert blocker["reason"] == "krpano_spatial_provenance_missing_or_invalid"


def test_one_scene_krpano_receipt_cannot_satisfy_walkable_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_krpano_bundle(tmp_path, "one-scene-walkable", walkable=True)

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["krpano"] == 0


def test_reviewed_single_krpano_panorama_remains_honestly_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_krpano_bundle(tmp_path, "single-panorama")

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["krpano"] == 1
    control = _tour_row(receipt)["controls"][0]
    assert control["evidence"] == "provenance_bound_licensed_krpano_spatial_scene"


def test_connected_reviewed_krpano_scenes_satisfy_walkable_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_krpano_bundle(
        tmp_path,
        "connected-krpano",
        walkable=True,
        connected_scenes=True,
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["krpano"] == 1
    control = _tour_row(receipt)["controls"][0]
    assert control["evidence"] == "provenance_bound_licensed_krpano_spatial_scene"


def test_panorama_byte_tamper_invalidates_receipt(tmp_path: Path) -> None:
    bundle = _write_pano2vr_bundle(tmp_path, "tampered-pano")
    (bundle / "pano" / "tour.js").write_text(
        "window.ggskin = false; // changed after review",
        encoding="utf-8",
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["pano2vr"] == 0


def test_panorama_asset_hash_rejects_internal_symlink(tmp_path: Path) -> None:
    asset_dir = tmp_path / "krpano"
    asset_dir.mkdir()
    real_asset = asset_dir / "real-panorama.jpg"
    real_asset.write_bytes(b"real panorama bytes")
    (asset_dir / "panorama.jpg").symlink_to(real_asset.name)

    with pytest.raises(ValueError, match="asset_symlink_forbidden"):
        asset_set_sha256(tmp_path, ("krpano/panorama.jpg",))


def test_offline_verifier_fails_closed_above_panorama_hash_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pano2vr_bundle(tmp_path, "offline-budget")
    monkeypatch.setenv("PROPERTYQUARRY_PANORAMA_MAX_HASH_FILES", "1")

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["provider_counts"]["pano2vr"] == 0


def test_raw_pano2vr_files_require_private_byte_bound_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pano2vr_bundle(tmp_path, "raw-marker-only", include_receipt=False)
    _write_pano2vr_bundle(tmp_path, "raw-reviewed")
    tampered_bundle = _write_pano2vr_bundle(tmp_path, "raw-tampered")
    tampered_receipt_path = tampered_bundle / "tour.private.json"
    tampered_receipt = json.loads(tampered_receipt_path.read_text(encoding="utf-8"))
    tampered_receipt[PANO2VR_SPATIAL_PROVENANCE_KEY]["artifact"]["sha256"] = "0" * 64
    tampered_receipt_path.write_text(json.dumps(tampered_receipt), encoding="utf-8")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    _pano2vr_spatial_provenance_errors_cached.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        _pano2vr_export_file("raw-marker-only", "pano/index.html")

    assert exc_info.value.status_code == 404
    assert _pano2vr_export_file("raw-reviewed", "pano/index.html").is_file()
    with pytest.raises(HTTPException) as tampered_exc_info:
        _pano2vr_export_file("raw-tampered", "pano/index.html")
    assert tampered_exc_info.value.status_code == 404

    monkeypatch.setenv("PROPERTYQUARRY_PUBLIC_PANO2VR_MAX_HASH_FILES", "1")
    _pano2vr_spatial_provenance_errors_cached.cache_clear()
    with pytest.raises(HTTPException) as budget_exc_info:
        _pano2vr_export_file("raw-reviewed", "pano/index.html")
    assert budget_exc_info.value.status_code == 404


def test_public_pano2vr_shell_uses_safe_same_origin_route_without_private_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "public-shell-pano2vr"
    bundle = _write_pano2vr_bundle(
        tmp_path,
        slug,
        walkable=True,
        connected_scenes=True,
        include_receipt=True,
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    payload["control_mode"] = "pano2vr"
    payload["scenes"] = [
        {
            "scene_id": "node1",
            "name": "Entry hall",
            "role": "photo",
        }
    ]

    expected_url = f"/tours/pano2vr/{slug}/pano/index.html"

    assert "source_virtual_tour_url" not in payload
    assert PANO2VR_SPATIAL_PROVENANCE_KEY not in payload
    assert _pano2vr_control_url(slug, payload) == expected_url

    rendered = _tour_html(payload, hostname="propertyquarry.com")

    assert 'href="#live-360"' in rendered
    assert 'id="live-360"' in rendered
    assert f'src="{expected_url}"' in rendered
    assert "source_virtual_tour_url" not in rendered
    assert PANO2VR_SPATIAL_PROVENANCE_KEY not in rendered


@pytest.mark.parametrize("receipt_state", ["missing", "tampered"])
def test_public_pano2vr_shell_hides_control_when_private_provenance_is_unavailable(
    receipt_state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = f"public-shell-pano2vr-{receipt_state}"
    bundle = _write_pano2vr_bundle(
        tmp_path,
        slug,
        walkable=True,
        connected_scenes=True,
        include_receipt=receipt_state == "tampered",
    )
    if receipt_state == "tampered":
        receipt_path = bundle / "tour.private.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt[PANO2VR_SPATIAL_PROVENANCE_KEY]["artifact"]["sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    _pano2vr_spatial_provenance_errors_cached.cache_clear()
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    payload["control_mode"] = "pano2vr"
    payload["scenes"] = [
        {
            "scene_id": "node1",
            "name": "Entry hall",
            "role": "photo",
        }
    ]
    unavailable_url = f"/tours/pano2vr/{slug}/pano/index.html"

    assert _pano2vr_control_url(slug, payload) == ""

    rendered = _tour_html(payload, hostname="propertyquarry.com")

    assert 'href="#live-360"' not in rendered
    assert 'id="live-360"' not in rendered
    assert unavailable_url not in rendered
    assert "source_virtual_tour_url" not in rendered
    assert PANO2VR_SPATIAL_PROVENANCE_KEY not in rendered


def test_hosted_pano2vr_bundle_separates_raw_public_manifest_from_private_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "raw-hosted-pano2vr-privacy"
    bundle = _write_pano2vr_bundle(
        tmp_path,
        slug,
        walkable=True,
        connected_scenes=True,
        include_receipt=False,
    )
    export_dir = bundle / "pano"
    (bundle / "tour.json").unlink()
    (bundle / "scene-01.jpg").write_bytes(b"public-scene")
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    provenance = _spatial_receipt(
        slug=slug,
        provider="pano2vr",
        artifact={
            "kind": "local_export",
            "sha256": export_tree_sha256(export_dir),
            "entry_relpath": "index.html",
        },
        topology=pano2vr_export_topology(export_dir),
    )
    private_values = {
        "principal_id": "cf-email:owner@example.com",
        "search_run_id": "search-private-123",
        "listing_url": "https://listings.example.test/private-listing",
        "property_url": "https://broker.example.test/private-property",
        "source_ref": "property-scout:private-source",
        "external_id": "external-private-id",
        "recipient_email": "viewer@example.com",
        "source_virtual_tour_url": "https://provider.example.test/private-tour",
    }
    exact_address = "Private Street 7, 1020 Wien"
    source_image_url = "https://provider.example.test/private-scene.jpg"

    _write_hosted_property_tour_payload(
        bundle,
        {
            "slug": slug,
            "title": "Raw hosted Pano2VR privacy",
            "display_title": "Raw hosted Pano2VR privacy",
            "control_mode": "pano2vr",
            "scene_strategy": "walkable_panorama",
            "creation_mode": "hosted_walkable_360",
            "pano2vr_entry_relpath": "pano/index.html",
            PANO2VR_SPATIAL_PROVENANCE_KEY: provenance,
            **private_values,
            "facts": {
                "rooms": 3,
                "area_sqm": 84,
                "postal_name": "1020 Wien",
                "exact_address": exact_address,
                "street_address": "Private Street 7",
                "map_lat": 48.22,
                "map_lng": 16.39,
            },
            "scenes": [
                {
                    "name": "Living room",
                    "role": "photo",
                    "asset_relpath": "scene-01.jpg",
                    "source_url": source_image_url,
                    "privacy_class": "public",
                    "mime_type": "image/jpeg",
                }
            ],
        },
    )

    public_path = bundle / "tour.json"
    private_path = bundle / "tour.private.json"
    public_manifest = json.loads(public_path.read_text(encoding="utf-8"))
    private_manifest = json.loads(private_path.read_text(encoding="utf-8"))
    serialized_public = json.dumps(public_manifest, ensure_ascii=False, sort_keys=True)

    assert public_manifest["pano2vr_entry_relpath"] == "pano/index.html"
    for private_marker in (
        *private_values.keys(),
        *private_values.values(),
        "source_url",
        source_image_url,
        "exact_address",
        "street_address",
        exact_address,
        "Private Street 7",
        "map_lat",
        "map_lng",
        PANO2VR_SPATIAL_PROVENANCE_KEY,
        "camera-release:",
        "property-tour-reviewer",
    ):
        assert private_marker not in serialized_public

    for key, value in private_values.items():
        assert private_manifest[key] == value
    assert private_manifest["private_exact_location"]["facts"] == {
        "exact_address": exact_address,
        "street_address": "Private Street 7",
        "map_lat": 48.22,
        "map_lng": 16.39,
    }
    assert private_manifest[PANO2VR_SPATIAL_PROVENANCE_KEY]["authorization"] == {
        "status": "approved",
        "reference": f"camera-release:{slug}",
    }
    assert private_manifest[PANO2VR_SPATIAL_PROVENANCE_KEY]["review"]["reviewed_by"] == (
        "property-tour-reviewer"
    )
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
