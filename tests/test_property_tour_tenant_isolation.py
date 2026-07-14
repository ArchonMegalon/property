from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.product import property_tour_hosting
from product_test_helpers import build_product_client


def _fake_gallery_download(url: str, target: Path) -> str:
    del url
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"property-tour-image")
    return "image/jpeg"


def _write_gallery(
    *,
    principal_id: str,
    recipient_email: str,
    property_url: str,
) -> dict[str, object]:
    return property_tour_hosting._write_hosted_photo_gallery_property_tour_bundle(
        principal_id=principal_id,
        title="Same listing",
        listing_id="same-listing-42",
        property_url=property_url,
        variant_key="layout_first",
        media_urls=["https://93.184.216.34/photo.jpg"],
        property_facts_json={},
        source_host="example.test",
        source_ref="listing:same-listing-42",
        external_id="same-listing-42",
        recipient_email=recipient_email,
    )


def test_branded_public_tour_url_rejects_lookalike_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PROPERTYQUARRY_PUBLIC_TOUR_BASE_URL",
        "PROPERTYQUARRY_PUBLIC_BASE_URL",
        "EA_PUBLIC_TOUR_BASE_URL",
        "EA_PUBLIC_APP_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert property_tour_hosting._is_branded_public_tour_url("https://propertyquarry.com/tours/demo") is True
    assert property_tour_hosting._is_branded_public_tour_url("https://propertyquarry.com:443/tours/demo") is True
    assert property_tour_hosting._is_branded_public_tour_url("https://www.propertyquarry.com/tours/demo") is True
    assert property_tour_hosting._is_branded_public_tour_url("https://evilpropertyquarry.com/tours/demo") is False
    assert property_tour_hosting._is_branded_public_tour_url("https://propertyquarry.com.evil.example/tours/demo") is False


def test_same_listing_bundles_are_private_to_each_principal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.example/tours")
    monkeypatch.setattr(property_tour_hosting, "_hosted_property_tour_identity_secret", lambda: b"tenant-test-secret")
    monkeypatch.setattr(property_tour_hosting, "_download_public_tour_asset_with_type", _fake_gallery_download)
    property_url = "https://listings.example.test/same-listing-42"
    owner_one = "cf-email:owner-one@example.test"
    owner_two = "cf-email:owner-two@example.test"

    first = _write_gallery(
        principal_id=owner_one,
        recipient_email="owner-one@example.test",
        property_url=property_url,
    )
    second = _write_gallery(
        principal_id=owner_two,
        recipient_email="owner-two@example.test",
        property_url=property_url,
    )

    first_slug = str(first["slug"])
    second_slug = str(second["slug"])
    assert first_slug != second_slug
    assert first_slug != property_tour_hosting._hosted_property_tour_slug(
        title="Same listing",
        listing_id="same-listing-42",
        property_url=property_url,
        variant_key="layout_first",
    )

    public_payload = property_tour_hosting._load_hosted_property_tour_payload(tmp_path / first_slug)
    assert "principal_id" not in public_payload
    assert "recipient_email" not in public_payload
    assert "property_url" not in public_payload
    assert "source_ref" not in public_payload

    first_owner_payload = property_tour_hosting._load_hosted_property_tour_payload(
        tmp_path / first_slug,
        principal_id=owner_one,
    )
    wrong_owner_payload = property_tour_hosting._load_hosted_property_tour_payload(
        tmp_path / first_slug,
        principal_id=owner_two,
    )
    assert first_owner_payload["principal_id"] == owner_one
    assert first_owner_payload["recipient_email"] == "owner-one@example.test"
    assert "principal_id" not in wrong_owner_payload
    assert "recipient_email" not in wrong_owner_payload
    assert property_tour_hosting._existing_hosted_property_tour_payload(
        first_slug,
        principal_id=owner_two,
    ) == {}

    reused = _write_gallery(
        principal_id=owner_one,
        recipient_email="changed-by-owner@example.test",
        property_url=property_url,
    )
    assert reused["slug"] == first_slug
    assert reused["tour_cache_status"] == "existing"
    assert reused["recipient_email"] == "owner-one@example.test"

    first_private_path = tmp_path / first_slug / "tour.private.json"
    first_private_before = json.loads(first_private_path.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="hosted_property_tour_owner_mismatch"):
        property_tour_hosting._write_hosted_property_tour_payload(
            tmp_path / first_slug,
            {**first_owner_payload, "principal_id": owner_two, "recipient_email": "owner-two@example.test"},
        )
    assert json.loads(first_private_path.read_text(encoding="utf-8")) == first_private_before

    denied_revoke = property_tour_hosting.revoke_hosted_property_tour_bundle(
        slug=first_slug,
        principal_id=owner_two,
        actor="cross-tenant-test",
    )
    assert denied_revoke["status"] == "not_found"
    assert (tmp_path / first_slug).is_dir()
    assert (tmp_path / second_slug).is_dir()

    revoked = property_tour_hosting.revoke_hosted_property_tour_bundle(
        slug=first_slug,
        principal_id=owner_one,
        actor="owner-test",
    )
    assert revoked["status"] == "revoked"
    assert not (tmp_path / first_slug).exists()
    assert (tmp_path / second_slug).is_dir()


def test_legacy_bundle_is_reused_only_by_its_recorded_owner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.example/tours")
    monkeypatch.setattr(property_tour_hosting, "_hosted_property_tour_identity_secret", lambda: b"tenant-test-secret")
    monkeypatch.setattr(property_tour_hosting, "_download_public_tour_asset_with_type", _fake_gallery_download)
    property_url = "https://listings.example.test/legacy-listing-7"
    owner_one = "cf-email:legacy-owner@example.test"
    owner_two = "cf-email:new-owner@example.test"
    legacy_slug = property_tour_hosting._hosted_property_tour_slug(
        title="Same listing",
        listing_id="same-listing-42",
        property_url=property_url,
        variant_key="layout_first",
    )
    legacy_dir = tmp_path / legacy_slug
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "photo-01.jpg").write_bytes(b"legacy-photo")
    property_tour_hosting._write_hosted_property_tour_payload(
        legacy_dir,
        {
            "slug": legacy_slug,
            "principal_id": owner_one,
            "property_url": property_url,
            "listing_url": property_url,
            "source_ref": "listing:same-listing-42",
            "external_id": "same-listing-42",
            "recipient_email": "legacy-owner@example.test",
            "title": "Legacy listing tour",
            "display_title": "Legacy listing tour",
            "variant_key": "layout_first",
            "scene_strategy": "photo_gallery_hosted",
            "scenes": [{"ordinal": 1, "name": "Photo 1", "role": "photo", "asset_relpath": "photo-01.jpg"}],
            "creation_mode": "hosted_photo_gallery_tour",
        },
    )

    owner_reuse = _write_gallery(
        principal_id=owner_one,
        recipient_email="legacy-owner@example.test",
        property_url=property_url,
    )
    other_owner = _write_gallery(
        principal_id=owner_two,
        recipient_email="new-owner@example.test",
        property_url=property_url,
    )

    assert owner_reuse["slug"] == legacy_slug
    assert owner_reuse["tour_cache_status"] == "existing"
    assert other_owner["slug"] != legacy_slug
    legacy_receipt = json.loads((legacy_dir / "tour.private.json").read_text(encoding="utf-8"))
    assert legacy_receipt["principal_id"] == owner_one
    assert legacy_receipt["recipient_email"] == "legacy-owner@example.test"


def test_legacy_bundle_without_owner_is_not_claimed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.example/tours")
    monkeypatch.setattr(property_tour_hosting, "_hosted_property_tour_identity_secret", lambda: b"tenant-test-secret")
    monkeypatch.setattr(property_tour_hosting, "_download_public_tour_asset_with_type", _fake_gallery_download)
    property_url = "https://listings.example.test/unowned-legacy-listing"
    legacy_slug = property_tour_hosting._hosted_property_tour_slug(
        title="Same listing",
        listing_id="same-listing-42",
        property_url=property_url,
        variant_key="layout_first",
    )
    legacy_dir = tmp_path / legacy_slug
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "photo-01.jpg").write_bytes(b"unowned-legacy-photo")
    original_manifest = {
        "slug": legacy_slug,
        "display_title": "Unowned legacy share",
        "scenes": [{"ordinal": 1, "role": "photo", "asset_relpath": "photo-01.jpg"}],
    }
    (legacy_dir / "tour.json").write_text(json.dumps(original_manifest), encoding="utf-8")

    created = _write_gallery(
        principal_id="cf-email:new-owner@example.test",
        recipient_email="new-owner@example.test",
        property_url=property_url,
    )

    assert created["slug"] != legacy_slug
    assert json.loads((legacy_dir / "tour.json").read_text(encoding="utf-8")) == original_manifest
    assert not (legacy_dir / "tour.private.json").exists()


def test_revoke_api_returns_not_found_to_another_principal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))
    monkeypatch.setenv("EA_PUBLIC_TOUR_BASE_URL", "https://propertyquarry.example/tours")
    monkeypatch.setattr(property_tour_hosting, "_hosted_property_tour_identity_secret", lambda: b"tenant-test-secret")
    monkeypatch.setattr(property_tour_hosting, "_download_public_tour_asset_with_type", _fake_gallery_download)
    owner_one = "cf-email:api-owner@example.test"
    owner_two = "cf-email:api-attacker@example.test"
    payload = _write_gallery(
        principal_id=owner_one,
        recipient_email="api-owner@example.test",
        property_url="https://listings.example.test/api-revoke-listing",
    )
    slug = str(payload["slug"])

    attacker_client = build_product_client(principal_id=owner_two)
    owner_client = build_product_client(principal_id=owner_one)
    denied = attacker_client.post(f"/app/api/property/public-tours/{slug}/revoke")

    assert denied.status_code == 404
    assert (tmp_path / slug).is_dir()

    revoked = owner_client.post(f"/app/api/property/public-tours/{slug}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert not (tmp_path / slug).exists()
