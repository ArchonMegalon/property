from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.product import property_tour_ai_panorama_intake as intake
from app.product.property_search_tour_binding import property_search_source_url_sha256


LISTING_URL = "https://www.willhaben.at/iad/immobilien/d/1807240910/"
SLUG = "prater-ai-360-candidate-1"
PRINCIPAL = "principal-secret@example.invalid"
RUN_ID = "run-123"
CANDIDATE_REF = "candidate-private-9"
SOURCE_REF = "property-scout:1807240910"
EXTERNAL_ID = "1807240910"


@pytest.fixture(autouse=True)
def _strict_contract_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_PUBLIC_TOUR_DIR", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR", raising=False)

    def _contract(*, bundle_dir: Path, payload: dict[str, object], mode: str = "full") -> dict[str, object]:
        return {
            "ready": True,
            "reason": "",
            "representation_kind": "ai_panorama_360",
            "property_url_sha256": str(payload.get("property_url_sha256") or ""),
            "core_manifest_sha256": intake._semantic_manifest_sha256(payload),
        }

    monkeypatch.setattr(intake, "_hosted_property_tour_ai_panorama_contract", _contract)


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    path.chmod(0o644)


def _make_bundle(root: Path, *, slug: str = SLUG) -> Path:
    bundle = root / "sealed-bundle"
    bundle.mkdir(parents=True, mode=0o755)
    property_url_sha256 = property_search_source_url_sha256(LISTING_URL)
    browser_receipt = {
        "desktop": {"screenshot_relpath": "proof/browser-desktop.png"},
        "mobile": {"screenshot_relpath": "proof/browser-mobile.png"},
        "dollhouse": {"screenshot_relpath": "proof/browser-dollhouse.png"},
    }
    provenance = {
        "contract_name": "propertyquarry.ai_panorama_provenance.v1",
        "property_binding_kind": "willhaben_source_listing_url_sha256",
        "property_url_sha256": property_url_sha256,
    }
    payload = {
        "slug": slug,
        "publication_status": "ready",
        "property_url_sha256": property_url_sha256,
        "walkable_scene": {
            "representation_kind": "ai_reconstruction",
            "floorplan_relpath": "floorplan.webp",
            "scenes": [
                {
                    "id": "living-room",
                    "asset_relpath": "panoramas/living-room.jpg",
                }
            ],
            "acceptance": {
                "provenance_relpath": "proof/provenance.json",
                "browser_receipt_relpath": "proof/browser-proof.json",
            },
        },
    }
    _write(bundle / "tour.json", json.dumps(payload, sort_keys=True).encode("utf-8"))
    _write(bundle / "floorplan.webp", b"floorplan")
    _write(bundle / "panoramas/living-room.jpg", b"panorama")
    _write(bundle / "proof/provenance.json", json.dumps(provenance).encode("utf-8"))
    _write(bundle / "proof/browser-proof.json", json.dumps(browser_receipt).encode("utf-8"))
    _write(bundle / "proof/browser-desktop.png", b"desktop")
    _write(bundle / "proof/browser-mobile.png", b"mobile")
    _write(bundle / "proof/browser-dollhouse.png", b"dollhouse")
    return bundle


def _request(bundle: Path, public_dir: Path, **overrides: object) -> dict[str, object]:
    os.environ["EA_PUBLIC_TOUR_DIR"] = str(public_dir)
    os.environ["PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR"] = str(bundle.parent)
    request: dict[str, object] = {
        "contract": intake.AI_PANORAMA_INSTALL_REQUEST_CONTRACT,
        "source_bundle": str(bundle),
        "public_tour_dir": str(public_dir),
        "expected_slug": SLUG,
        "principal_id": PRINCIPAL,
        "search_run_id": RUN_ID,
        "candidate_ref": CANDIDATE_REF,
        "listing_url": LISTING_URL,
        "provider_key": "willhaben",
        "source_ref": SOURCE_REF,
        "external_id": EXTERNAL_ID,
    }
    request.update(overrides)
    return request


def _hash_bound_request(bundle: Path, public_dir: Path, **overrides: object) -> dict[str, object]:
    request = _request(bundle, public_dir, **overrides)
    plan = intake.install_sealed_ai_panorama_bundle(request)
    request.update(
        {
            "expected_source_tree_sha256": plan["source_tree_sha256"],
            "expected_tour_sha256": plan["source_tour_sha256"],
        }
    )
    return request


def test_private_request_loader_requires_owner_only_regular_file(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"contract": intake.AI_PANORAMA_INSTALL_REQUEST_CONTRACT}),
        encoding="utf-8",
    )
    request_path.chmod(0o644)
    with pytest.raises(intake.AiPanoramaIntakeError, match="request_permissions_invalid"):
        intake.load_private_ai_panorama_install_request(request_path)

    request_path.chmod(0o600)
    loaded = intake.load_private_ai_panorama_install_request(request_path)
    assert loaded["contract"] == intake.AI_PANORAMA_INSTALL_REQUEST_CONTRACT

    link_path = tmp_path / "request-link.json"
    link_path.symlink_to(request_path)
    with pytest.raises(intake.AiPanoramaIntakeError, match="request_permissions_invalid"):
        intake.load_private_ai_panorama_install_request(link_path)


def test_private_request_revalidates_the_opened_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "request.json"
    replacement_path = tmp_path / "replacement.json"
    payload = json.dumps(
        {"contract": intake.AI_PANORAMA_INSTALL_REQUEST_CONTRACT}
    )
    request_path.write_text(payload, encoding="utf-8")
    request_path.chmod(0o600)
    replacement_path.write_text(payload, encoding="utf-8")
    replacement_path.chmod(0o644)
    original_open = os.open

    def _swapped_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        target = replacement_path if Path(path) == request_path else path
        return original_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(intake.os, "open", _swapped_open)
    with pytest.raises(intake.AiPanoramaIntakeError, match="request_permissions_invalid"):
        intake.load_private_ai_panorama_install_request(request_path)


def test_dry_run_is_default_hash_discovery_and_redacts_private_values(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "source")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    receipt = intake.install_sealed_ai_panorama_bundle(_request(bundle, public_dir))

    assert receipt["status"] == "validated"
    assert receipt["mode"] == "dry_run"
    assert receipt["applied"] is False
    assert receipt["source_file_count"] == 8
    assert len(str(receipt["source_tree_sha256"])) == 64
    rendered = json.dumps(receipt, sort_keys=True)
    for private_value in (PRINCIPAL, RUN_ID, CANDIDATE_REF, LISTING_URL, SOURCE_REF, EXTERNAL_ID):
        assert private_value not in rendered
    assert not (public_dir / SLUG).exists()


def test_apply_requires_both_exact_source_hashes(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "source")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    request = _request(bundle, public_dir)
    with pytest.raises(intake.AiPanoramaIntakeError, match="expected_source_tree_sha256_invalid"):
        intake.install_sealed_ai_panorama_bundle(request, apply=True)

    plan = intake.install_sealed_ai_panorama_bundle(request)
    request["expected_source_tree_sha256"] = plan["source_tree_sha256"]
    request["expected_tour_sha256"] = "0" * 64
    with pytest.raises(intake.AiPanoramaIntakeError, match="source_tour_sha256_mismatch"):
        intake.install_sealed_ai_panorama_bundle(request, apply=True)
    assert not (public_dir / SLUG).exists()


def test_apply_writes_owned_pair_atomically_and_is_idempotent(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "source")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    request = _hash_bound_request(bundle, public_dir)

    first = intake.install_sealed_ai_panorama_bundle(request, apply=True)
    second = intake.install_sealed_ai_panorama_bundle(request, apply=True)

    target = public_dir / SLUG
    private_path = target / "tour.private.json"
    private = json.loads(private_path.read_text(encoding="utf-8"))
    assert first["status"] == "installed"
    assert first["applied"] is True
    assert second["status"] == "already_installed"
    assert second["applied"] is False
    assert stat_mode(private_path) == 0o600
    assert {
        key: private[key]
        for key in (
            "principal_id",
            "search_run_id",
            "candidate_ref",
            "listing_url",
            "property_url",
            "source_ref",
            "external_id",
        )
    } == {
        "principal_id": PRINCIPAL,
        "search_run_id": RUN_ID,
        "candidate_ref": CANDIDATE_REF,
        "listing_url": LISTING_URL,
        "property_url": LISTING_URL,
        "source_ref": SOURCE_REF,
        "external_id": EXTERNAL_ID,
    }
    public = json.loads((target / "tour.json").read_text(encoding="utf-8"))
    assert public["property_url_sha256"] == property_search_source_url_sha256(LISTING_URL)
    assert not intake._PRIVATE_MANIFEST_KEYS.intersection(public)


def stat_mode(path: Path) -> int:
    return path.stat(follow_symlinks=False).st_mode & 0o777


def test_existing_target_rejects_wrong_owner_and_replacement(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "source")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    request = _hash_bound_request(bundle, public_dir)
    intake.install_sealed_ai_panorama_bundle(request, apply=True)

    wrong_owner = dict(request, principal_id="other-principal")
    with pytest.raises(intake.AiPanoramaIntakeError, match="target_owner_mismatch"):
        intake.install_sealed_ai_panorama_bundle(wrong_owner, apply=True)

    replacement_bundle = _make_bundle(tmp_path / "replacement")
    (replacement_bundle / "panoramas/living-room.jpg").write_bytes(b"different-panorama")
    replacement_request = _request(replacement_bundle, public_dir)
    snapshot = intake._scan_source_bundle(replacement_bundle)
    replacement_request.update(
        {
            "expected_source_tree_sha256": snapshot.tree_sha256,
            "expected_tour_sha256": snapshot.tour_sha256,
        }
    )
    with pytest.raises(intake.AiPanoramaIntakeError, match="target_replace_forbidden"):
        intake.install_sealed_ai_panorama_bundle(replacement_request, apply=True)


def test_rejects_symlinks_extra_files_and_provider_mislabel(tmp_path: Path) -> None:
    public_dir = tmp_path / "public"
    public_dir.mkdir()

    symlink_bundle = _make_bundle(tmp_path / "symlink-source")
    (symlink_bundle / "proof/browser-mobile.png").unlink()
    (symlink_bundle / "proof/browser-mobile.png").symlink_to(
        symlink_bundle / "proof/browser-desktop.png"
    )
    with pytest.raises(intake.AiPanoramaIntakeError, match="source_symlink_forbidden"):
        intake.install_sealed_ai_panorama_bundle(_request(symlink_bundle, public_dir))

    extra_bundle = _make_bundle(tmp_path / "extra-source")
    _write(extra_bundle / "proof/unbound.json", b"{}")
    with pytest.raises(intake.AiPanoramaIntakeError, match="source_file_set_mismatch"):
        intake.install_sealed_ai_panorama_bundle(_request(extra_bundle, public_dir))

    mislabelled_bundle = _make_bundle(tmp_path / "mislabelled-source")
    provenance_path = mislabelled_bundle / "proof/provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["property_binding_kind"] = "propertyquarry_research_url_sha256"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(
        intake.AiPanoramaIntakeError,
        match="provider_qualified_provenance_mismatch",
    ):
        intake.install_sealed_ai_panorama_bundle(_request(mislabelled_bundle, public_dir))


def test_rejects_source_and_destination_outside_configured_roots(
    tmp_path: Path,
) -> None:
    bundle = _make_bundle(tmp_path / "source")
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    request = _request(bundle, public_dir)

    other_public_dir = tmp_path / "other-public"
    other_public_dir.mkdir()
    os.environ["EA_PUBLIC_TOUR_DIR"] = str(other_public_dir)
    with pytest.raises(intake.AiPanoramaIntakeError, match="public_dir_not_configured"):
        intake.install_sealed_ai_panorama_bundle(request)

    os.environ["EA_PUBLIC_TOUR_DIR"] = str(public_dir)
    other_incoming_dir = tmp_path / "other-incoming"
    other_incoming_dir.mkdir()
    os.environ["PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR"] = str(other_incoming_dir)
    with pytest.raises(intake.AiPanoramaIntakeError, match="source_outside_incoming_root"):
        intake.install_sealed_ai_panorama_bundle(request)


def test_web_image_copies_binder_and_installer_operator_clis() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1] / "ea" / "Dockerfile.property-web"
    ).read_text(encoding="utf-8")
    assert (
        "COPY --chmod=0555 scripts/install_ai_panorama_tour_bundle.py "
        "/app/scripts/install_ai_panorama_tour_bundle.py"
    ) in dockerfile
    assert (
        "COPY --chmod=0555 scripts/bind_property_search_candidate_tour.py "
        "/app/scripts/bind_property_search_candidate_tour.py"
    ) in dockerfile
