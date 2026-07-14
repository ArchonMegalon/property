from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from scripts import publish_property_tour_live as live_publish


SLUG = live_publish.AUTHORIZED_SLUG
ORIGIN = "https://propertyquarry.com"
LOGICAL_VOLUME = "property_public_tours"
USER_INSTRUCTION_SHA256 = "4" * 64
ROLLBACK_INSTRUCTION_SHA256 = "5" * 64


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def _chmod_directories(root: Path, mode: int) -> None:
    root.chmod(mode)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(mode)


def _build_package(tmp_path: Path) -> Path:
    package_root = tmp_path / "reviewed-package"
    bundle = package_root / "public_property_tours" / SLUG
    authority_dir = package_root / "publication-authority"
    asset_bytes = {
        "generated-reconstruction/viewer.html": b"<!doctype html><p>viewer</p>\n",
        "generated-reconstruction/reconstruction.json": b'{"synthetic":true}\n',
        "generated-reconstruction/source-floorplan.png": b"png-floorplan",
        "generated-reconstruction/vendor/three.module.js": b"export const T = 1;\n",
        (
            "generated-reconstruction/vendor/examples/jsm/controls/"
            "OrbitControls.js"
        ): b"export const O = 1;\n",
    }
    specs = {
        "generated-reconstruction/viewer.html": ("text/html", "viewer_document"),
        "generated-reconstruction/reconstruction.json": (
            "application/json",
            "reconstruction_manifest",
        ),
        "generated-reconstruction/source-floorplan.png": (
            "image/png",
            "floorplan_texture",
        ),
        "generated-reconstruction/vendor/three.module.js": (
            "text/javascript",
            "viewer_module",
        ),
        (
            "generated-reconstruction/vendor/examples/jsm/controls/"
            "OrbitControls.js"
        ): ("text/javascript", "viewer_module"),
    }
    bindings = [
        {
            "path": path,
            "sha256": _sha256(asset_bytes[path]),
            "size_bytes": len(asset_bytes[path]),
            "mime_type": specs[path][0],
            "role": specs[path][1],
        }
        for path in sorted(asset_bytes)
    ]
    authority = {
        "schema": live_publish.PUBLICATION_AUTHORITY_SCHEMA,
        "status": "authorized",
        "owner": "PropertyQuarry",
        "repository": live_publish.PROPERTY_REPOSITORY,
        "slug": SLUG,
        "public_activation_authority": True,
        "publication_authority_verified": True,
        "user_instruction_sha256": USER_INSTRUCTION_SHA256,
        "allowed_public_origins": [
            "https://myexternalbrain.com",
            ORIGIN,
        ],
        "package": {
            "public_bundle_relpath": f"public_property_tours/{SLUG}",
            "public_file_relpaths": sorted(live_publish._PUBLIC_FILE_RELPATHS),
            "public_file_count": 6,
            "asset_bindings": bindings,
        },
    }
    authority_bytes = _json_bytes(authority)
    tour = {
        "schema": live_publish.PUBLIC_TOUR_PACKAGE_SCHEMA,
        "slug": SLUG,
        "generated_viewer_release": {
            "status": "ready",
            "public_activation_authority": True,
            "publication_authority_verified": True,
            "publication_authority_receipt_sha256": _sha256(authority_bytes),
            "revoked": False,
            "disqualified": False,
            "asset_bindings": bindings,
        },
    }
    _write(bundle / "tour.json", _json_bytes(tour), 0o644)
    for relpath, content in asset_bytes.items():
        _write(bundle / relpath, content, 0o644)
    _write(authority_dir / f"{SLUG}.json", authority_bytes, 0o600)
    _chmod_directories(bundle, 0o755)
    package_root.chmod(0o755)
    (package_root / "public_property_tours").chmod(0o755)
    authority_dir.chmod(0o700)
    return package_root


def _build_live_volume(tmp_path: Path) -> Path:
    live_root = tmp_path / "live-volume"
    destination = live_root / SLUG
    destination.mkdir(parents=True)
    _write(destination / "legacy-listing.pdf", b"legacy-pdf", 0o644)
    _write(destination / "legacy-floorplan.pdf", b"legacy-floorplan", 0o644)
    live_root.chmod(0o755)
    destination.chmod(0o755)
    return live_root


def _common(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    package_root = _build_package(tmp_path)
    live_root = _build_live_volume(tmp_path)
    receipt_root = tmp_path / "control-receipts"
    receipt_root.mkdir(mode=0o700)
    kwargs: dict[str, object] = {
        "package_root": package_root,
        "live_volume_root": live_root,
        "receipt_root": receipt_root,
        "origin": ORIGIN,
        "logical_volume": LOGICAL_VOLUME,
        "slug": SLUG,
        "destination_relpath": SLUG,
        "user_instruction_sha256": USER_INSTRUCTION_SHA256,
    }
    return package_root, live_root, receipt_root, kwargs


def _precondition_and_grant(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, dict[str, object]]:
    package_root, live_root, receipt_root, kwargs = _common(tmp_path)
    precondition_path = receipt_root / "precondition.json"
    grant_path = receipt_root / "replace-grant.json"
    precondition = live_publish.inspect_live_precondition(**kwargs)
    live_publish.write_precondition_receipt(
        precondition,
        path=precondition_path,
        receipt_root=receipt_root,
    )
    live_publish.create_replacement_grant(
        **kwargs,
        precondition_receipt_path=precondition_path,
        grant_path=grant_path,
    )
    return (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    )


def _publish(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object]]:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    publication_path = receipt_root / "publication.json"
    publication = live_publish.publish_live_with_grant(
        **kwargs,
        precondition_receipt_path=precondition_path,
        grant_path=grant_path,
        publication_receipt_path=publication_path,
    )
    return (
        package_root,
        live_root,
        receipt_root,
        publication_path,
        kwargs,
        publication,
    )


def _receipt_finalization_case(
    tmp_path: Path, operation: str
) -> tuple[Path, Path, Path, Callable[[], dict[str, object]]]:
    if operation == "replace":
        (
            _package_root,
            live_root,
            receipt_root,
            precondition_path,
            grant_path,
            kwargs,
        ) = _precondition_and_grant(tmp_path)
        target = receipt_root / "publication.json"

        def invoke() -> dict[str, object]:
            return live_publish.publish_live_with_grant(
                **kwargs,
                precondition_receipt_path=precondition_path,
                grant_path=grant_path,
                publication_receipt_path=target,
            )

        return live_root, receipt_root, target, invoke

    (
        _package_root,
        live_root,
        receipt_root,
        publication_path,
        _kwargs,
        _publication,
    ) = _publish(tmp_path)
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    target = receipt_root / "rollback.json"

    def invoke() -> dict[str, object]:
        return live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=target,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    return live_root, receipt_root, target, invoke


def _prepared_transaction(path: Path, operation: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == live_publish.TRANSACTION_RECEIPT_SCHEMA
    assert payload["status"] == "prepared"
    assert payload["operation"] == operation
    assert payload["recovery_evidence_durable_before_exchange"] is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return payload


def test_read_only_precondition_binds_exact_live_and_property_package(
    tmp_path: Path,
) -> None:
    package_root, live_root, receipt_root, kwargs = _common(tmp_path)
    destination = live_root / SLUG
    before_identity = (destination.stat().st_dev, destination.stat().st_ino)
    before_names = sorted(path.name for path in destination.iterdir())

    receipt = live_publish.inspect_live_precondition(**kwargs)

    assert receipt["schema"] == live_publish.PRECONDITION_SCHEMA
    assert receipt["origin"] == ORIGIN
    assert receipt["logical_volume"] == LOGICAL_VOLUME
    assert receipt["destination_relpath"] == SLUG
    assert receipt["old_tree"]["file_count"] == 2
    assert receipt["old_tree"]["root_identity"] == {
        "device": before_identity[0],
        "inode": before_identity[1],
    }
    replacement = receipt["replacement_package"]
    assert replacement["file_count"] == 6
    assert replacement["user_instruction_sha256"] == USER_INSTRUCTION_SHA256
    assert receipt["property_authority_upstream"] is True
    assert receipt["ea_authority"] is False
    assert (destination.stat().st_dev, destination.stat().st_ino) == before_identity
    assert sorted(path.name for path in destination.iterdir()) == before_names
    assert sorted(path.name for path in live_root.iterdir()) == [SLUG]
    assert package_root.exists()
    assert receipt_root.is_dir()


def test_single_use_exchange_retains_old_tree_and_governed_rollback(
    tmp_path: Path,
) -> None:
    package_root, live_root, receipt_root, publication_path, kwargs, publication = (
        _publish(tmp_path)
    )
    bundle = package_root / "public_property_tours" / SLUG
    source_identity = (bundle.stat().st_dev, bundle.stat().st_ino)
    live_tree = live_publish._snapshot_tree(
        live_root / SLUG, code="test_live_tree"
    )
    source_tree = live_publish._snapshot_tree(bundle, code="test_source_tree")

    assert live_tree.tree_sha256 == source_tree.tree_sha256
    assert len(live_tree.files) == 6
    rollback_name = publication["retained_rollback_relpath"]
    retained = live_publish._snapshot_tree(
        live_root / str(rollback_name), code="test_retained_tree"
    )
    assert sorted(row.relpath for row in retained.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    assert publication["atomic_exchange"] is True
    assert publication["rollback_tree_retained"] is True
    assert Path(publication["consumed_grant_path"]).parent == (
        receipt_root / "used-grants"
    )
    assert stat.S_IMODE(publication_path.stat().st_mode) == 0o600
    assert not (receipt_root / "replace-grant.json").exists()
    consumed_grant = Path(str(publication["consumed_grant_path"]))
    replay_path = receipt_root / "copied-replay-grant.json"
    _write(replay_path, consumed_grant.read_bytes(), 0o600)
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    with pytest.raises(
        live_publish.LivePublicationError,
        match="single_use_grant_already_claimed",
    ):
        live_publish._claim_grant(
            grant_path=replay_path,
            receipt_root=receipt_root,
            grant=replay_payload,
            expected_sha256=_sha256(replay_path.read_bytes()),
        )
    assert replay_path.exists()

    rollback_grant_path = receipt_root / "rollback-grant.json"
    rollback_grant = live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=rollback_grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    assert rollback_grant["single_use"] is True
    assert stat.S_IMODE(rollback_grant_path.stat().st_mode) == 0o600
    rollback_receipt_path = receipt_root / "rollback.json"
    rollback_receipt = live_publish.rollback_live_with_grant(
        publication_receipt_path=publication_path,
        grant_path=rollback_grant_path,
        rollback_receipt_path=rollback_receipt_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )

    restored = live_publish._snapshot_tree(live_root / SLUG, code="test_restored")
    retained_published = live_publish._snapshot_tree(
        live_root / str(rollback_name), code="test_published_retained"
    )
    assert sorted(row.relpath for row in restored.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    assert retained_published.tree_sha256 == source_tree.tree_sha256
    assert rollback_receipt["published_tree_retained"] is True
    assert stat.S_IMODE(rollback_receipt_path.stat().st_mode) == 0o600
    assert (bundle.stat().st_dev, bundle.stat().st_ino) == source_identity
    assert bundle.exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink"])
def test_live_precondition_rejects_links_and_special_files(
    tmp_path: Path, kind: str
) -> None:
    _package_root, live_root, _receipt_root, kwargs = _common(tmp_path)
    destination = live_root / SLUG
    if kind == "symlink":
        (destination / "link.pdf").symlink_to(destination / "legacy-listing.pdf")
    elif kind == "fifo":
        os.mkfifo(destination / "pipe")
    else:
        os.link(
            destination / "legacy-listing.pdf",
            destination / "legacy-listing-copy.pdf",
        )

    with pytest.raises(
        live_publish.LivePublicationError,
        match=(
            "symlink_forbidden"
            if kind == "symlink"
            else "special_file_forbidden"
            if kind == "fifo"
            else "hardlink_forbidden"
        ),
    ):
        live_publish.inspect_live_precondition(**kwargs)


def test_package_hardlink_is_rejected_without_touching_live(
    tmp_path: Path,
) -> None:
    package_root, live_root, _receipt_root, kwargs = _common(tmp_path)
    viewer = (
        package_root
        / "public_property_tours"
        / SLUG
        / "generated-reconstruction/viewer.html"
    )
    outside_link = package_root / "viewer-retained-link"
    os.link(viewer, outside_link)
    live_identity = ((live_root / SLUG).stat().st_dev, (live_root / SLUG).stat().st_ino)

    with pytest.raises(live_publish.LivePublicationError, match="hardlink_forbidden"):
        live_publish.inspect_live_precondition(**kwargs)

    assert ((live_root / SLUG).stat().st_dev, (live_root / SLUG).stat().st_ino) == live_identity
    assert viewer.exists()
    assert outside_link.exists()


def test_destination_drift_blocks_before_grant_consumption(
    tmp_path: Path,
) -> None:
    (
        _package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    _write(live_root / SLUG / "legacy-listing.pdf", b"changed-after-grant", 0o644)

    with pytest.raises(
        live_publish.LivePublicationError, match="precondition_receipt_stale"
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=receipt_root / "publication.json",
        )

    assert grant_path.exists()
    assert not (receipt_root / "used-grants").exists()
    assert (live_root / SLUG / "legacy-listing.pdf").read_bytes() == b"changed-after-grant"


def test_occupied_publication_receipt_blocks_before_claim_or_exchange(
    tmp_path: Path,
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    publication_path = receipt_root / "publication.json"
    _write(publication_path, b"occupied-control-receipt", 0o600)
    before = live_publish._snapshot_tree(live_root / SLUG, code="before")

    with pytest.raises(
        live_publish.LivePublicationError,
        match="publication_receipt_reservation_failed",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=publication_path,
        )

    after = live_publish._snapshot_tree(live_root / SLUG, code="after")
    assert (after.root_device, after.root_inode, after.tree_sha256) == (
        before.root_device,
        before.root_inode,
        before.tree_sha256,
    )
    assert publication_path.read_bytes() == b"occupied-control-receipt"
    assert grant_path.exists()
    assert not (receipt_root / "used-grants").exists()
    assert package_root.exists()


def test_post_exchange_receipt_failure_leaves_durable_recovery_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    publication_path = receipt_root / "publication.json"

    def fail_finalization(**_kwargs: object) -> None:
        raise live_publish.LivePublicationError("simulated_receipt_finalization_failure")

    monkeypatch.setattr(
        live_publish, "_finalize_transaction_receipt", fail_finalization
    )
    with pytest.raises(
        live_publish.LivePublicationError,
        match="simulated_receipt_finalization_failure",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=publication_path,
        )

    prepared = _prepared_transaction(publication_path, "replace")
    live_tree = live_publish._snapshot_tree(live_root / SLUG, code="live")
    source_tree = live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    )
    retained = live_publish._snapshot_tree(
        live_root / str(prepared["peer_relpath"]), code="retained"
    )
    assert live_tree.tree_sha256 == source_tree.tree_sha256
    assert sorted(row.relpath for row in retained.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    assert Path(str(prepared["expected_consumed_grant_path"])).exists()
    assert not grant_path.exists()


@pytest.mark.parametrize("operation", ["replace", "rollback"])
@pytest.mark.parametrize("phase", ["before", "after"])
def test_receipt_exchange_fault_restores_prepared_requested_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    phase: str,
) -> None:
    live_root, _receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )

    def fail_receipt_transition(
        _root: Path, _target: str, _candidate: str, _code: str
    ) -> None:
        raise OSError(f"injected-{phase}-receipt-exchange-failure")

    hook = (
        "_before_receipt_exchange_hook"
        if phase == "before"
        else "_after_receipt_exchange_hook"
    )
    monkeypatch.setattr(live_publish, hook, fail_receipt_transition)
    expected_code = (
        "publication_receipt_write_failed"
        if operation == "replace"
        else "rollback_receipt_write_failed"
    )
    with pytest.raises(live_publish.LivePublicationError, match=expected_code):
        invoke()

    prepared = _prepared_transaction(target, operation)
    assert prepared["final_receipt_path"] == str(target)
    live_after = live_publish._snapshot_tree(live_root / SLUG, code="live_after")
    assert len(live_after.files) == (6 if operation == "replace" else 2)


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_post_receipt_exchange_fsync_failure_restores_prepared_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    live_root, _receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )

    def fail_transition_fsync(_root_fd: int) -> None:
        raise OSError("injected-final-receipt-directory-fsync-failure")

    monkeypatch.setattr(
        live_publish, "_fsync_final_receipt_transition", fail_transition_fsync
    )
    expected_code = (
        "publication_receipt_write_failed"
        if operation == "replace"
        else "rollback_receipt_write_failed"
    )
    with pytest.raises(live_publish.LivePublicationError, match=expected_code):
        invoke()

    _prepared_transaction(target, operation)
    live_after = live_publish._snapshot_tree(live_root / SLUG, code="live_after")
    assert len(live_after.files) == (6 if operation == "replace" else 2)
    final_status = json.loads(target.read_text(encoding="utf-8"))["status"]
    assert final_status == "prepared"


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_persistent_post_exchange_directory_fsync_failure_still_restores_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _live_root, _receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    real_fsync = os.fsync
    transition_started = False

    def mark_transition_started(
        _root: Path, _target: str, _candidate: str, _code: str
    ) -> None:
        nonlocal transition_started
        transition_started = True

    def fail_directory_fsync_after_transition(descriptor: int) -> None:
        if transition_started and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("persistent-receipt-directory-fsync-failure")
        real_fsync(descriptor)

    monkeypatch.setattr(
        live_publish, "_after_receipt_exchange_hook", mark_transition_started
    )
    monkeypatch.setattr(live_publish.os, "fsync", fail_directory_fsync_after_transition)
    expected_code = (
        "publication_receipt_write_failed"
        if operation == "replace"
        else "rollback_receipt_write_failed"
    )
    with pytest.raises(live_publish.LivePublicationError, match=expected_code):
        invoke()

    _prepared_transaction(target, operation)


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_final_receipt_name_cas_race_never_leaves_success_at_requested_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _live_root, receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    moved_prepared = receipt_root / f"operator-moved-{operation}-prepared.json"

    def substitute_target(
        root: Path, target_name: str, _candidate: str, _code: str
    ) -> None:
        assert root == receipt_root
        (root / target_name).rename(moved_prepared)
        _write(root / target_name, b'{"status":"substitute"}\n', 0o600)

    monkeypatch.setattr(
        live_publish, "_before_receipt_exchange_hook", substitute_target
    )
    with pytest.raises(
        live_publish.LivePublicationError,
        match="transaction_receipt_race_detected",
    ):
        invoke()

    _prepared_transaction(target, operation)
    assert moved_prepared.exists()
    assert json.loads(moved_prepared.read_text(encoding="utf-8"))["status"] == (
        "prepared"
    )


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_removed_requested_receipt_name_is_recreated_as_prepared_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    _live_root, receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    moved_prepared = receipt_root / f"operator-removed-{operation}-prepared.json"

    def remove_target_name(
        root: Path, target_name: str, _candidate: str, _code: str
    ) -> None:
        (root / target_name).rename(moved_prepared)

    monkeypatch.setattr(
        live_publish, "_before_receipt_exchange_hook", remove_target_name
    )
    expected_code = (
        "publication_receipt_write_failed"
        if operation == "replace"
        else "rollback_receipt_write_failed"
    )
    with pytest.raises(live_publish.LivePublicationError, match=expected_code):
        invoke()

    _prepared_transaction(target, operation)
    assert moved_prepared.exists()


@pytest.mark.parametrize("operation", ["replace", "rollback"])
@pytest.mark.parametrize("phase", ["before", "after"])
def test_receipt_root_replacement_blocks_final_success_and_restores_prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    phase: str,
) -> None:
    _live_root, receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    original_identity = (receipt_root.stat().st_dev, receipt_root.stat().st_ino)
    displaced_root = tmp_path / f"operator-moved-{operation}-receipt-root"

    def replace_receipt_root(
        root: Path, _target_name: str, _candidate: str, _code: str
    ) -> None:
        assert root == receipt_root
        root.rename(displaced_root)
        root.mkdir(mode=0o700)
        for entry in list(displaced_root.iterdir()):
            entry.rename(root / entry.name)

    monkeypatch.setattr(
        live_publish,
        (
            "_before_receipt_exchange_hook"
            if phase == "before"
            else "_after_receipt_exchange_hook"
        ),
        replace_receipt_root,
    )
    expected_code = (
        "publication_receipt_write_failed"
        if phase == "before" and operation == "replace"
        else "rollback_receipt_write_failed"
        if phase == "before"
        else "transaction_receipt_race_detected"
    )
    with pytest.raises(live_publish.LivePublicationError, match=expected_code):
        invoke()

    assert (receipt_root.stat().st_dev, receipt_root.stat().st_ino) != original_identity
    _prepared_transaction(target, operation)
    assert displaced_root.is_dir()


def test_replacement_grant_requires_mode_0600_and_exact_json_types(
    tmp_path: Path,
) -> None:
    (
        _package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    grant_path.chmod(0o640)
    with pytest.raises(live_publish.LivePublicationError, match="replacement_grant_invalid"):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=receipt_root / "publication.json",
        )
    grant = json.loads(grant_path.read_text(encoding="utf-8"))
    grant["required_mode"] = True
    grant_path.unlink()
    _write(grant_path, _json_bytes(grant), 0o600)
    with pytest.raises(live_publish.LivePublicationError, match="replacement_grant_invalid"):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=receipt_root / "publication.json",
        )
    assert sorted(path.name for path in live_root.iterdir()) == [SLUG]


def test_pre_exchange_destination_race_never_blindly_restores_raced_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    raced = live_root / "raced-object"
    raced.mkdir(mode=0o755)
    _write(raced / "raced.txt", b"raced-bytes", 0o644)
    displaced_original = live_root / "operator-moved-original"

    def race(
        operation: str,
        volume_root: Path,
        destination_name: str,
        _peer_name: str,
    ) -> None:
        assert operation == "replace"
        (volume_root / destination_name).rename(displaced_original)
        raced.rename(volume_root / destination_name)

    monkeypatch.setattr(live_publish, "_before_exchange_hook", race)
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=receipt_root / "publication.json",
        )

    live_package = live_publish._snapshot_tree(
        live_root / SLUG, code="test_live_package"
    )
    source_package = live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG,
        code="test_source_package",
    )
    assert live_package.tree_sha256 == source_package.tree_sha256
    assert (displaced_original / "legacy-listing.pdf").read_bytes() == b"legacy-pdf"
    used_grants = list((receipt_root / "used-grants").iterdir())
    assert len(used_grants) == 1
    grant_id = used_grants[0].stem.removeprefix("replace-")
    retained_raced = live_root / f".property-live-rollback-{grant_id}"
    assert (retained_raced / "raced.txt").read_bytes() == b"raced-bytes"
    prepared = json.loads(
        (receipt_root / "publication.json").read_text(encoding="utf-8")
    )
    assert prepared["schema"] == live_publish.TRANSACTION_RECEIPT_SCHEMA
    assert prepared["status"] == "prepared"
    assert package_root.exists()


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_exchange_hook_peer_substitution_is_blocked_before_name_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    live_root, _receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    public_before = live_publish._snapshot_tree(live_root / SLUG, code="before")
    alternate = live_root / f"hook-alternate-{operation}-peer"
    alternate.mkdir(mode=0o755)
    _write(alternate / "alternate.txt", b"hook-alternate", 0o644)
    displaced_peer = live_root / f"operator-moved-hook-{operation}-peer"
    observed_peer_name: str | None = None

    def substitute_peer(
        _operation: str,
        volume_root: Path,
        _destination_name: str,
        peer_name: str,
    ) -> None:
        nonlocal observed_peer_name
        observed_peer_name = peer_name
        (volume_root / peer_name).rename(displaced_peer)
        alternate.rename(volume_root / peer_name)

    monkeypatch.setattr(live_publish, "_before_exchange_hook", substitute_peer)
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_precondition_drift",
    ):
        invoke()

    prepared = _prepared_transaction(target, operation)
    public_after = live_publish._snapshot_tree(live_root / SLUG, code="after")
    assert (
        public_after.root_device,
        public_after.root_inode,
        public_after.tree_sha256,
    ) == (
        public_before.root_device,
        public_before.root_inode,
        public_before.tree_sha256,
    )
    assert observed_peer_name == prepared["peer_relpath"]
    assert (
        live_root / str(prepared["peer_relpath"]) / "alternate.txt"
    ).read_bytes() == b"hook-alternate"
    assert displaced_peer.is_dir()


@pytest.mark.parametrize("operation", ["replace", "rollback"])
def test_recovery_clone_substitution_retries_until_public_is_known_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    live_root, _receipt_root, target, invoke = _receipt_finalization_case(
        tmp_path, operation
    )
    public_before = live_publish._snapshot_tree(live_root / SLUG, code="before")
    alternate = live_root / f"first-{operation}-alternate"
    alternate.mkdir(mode=0o755)
    _write(alternate / "alternate.txt", b"first-alternate", 0o644)
    recovery_attacker = live_root / f"recovery-{operation}-alternate"
    recovery_attacker.mkdir(mode=0o755)
    _write(recovery_attacker / "recovery.txt", b"recovery-alternate", 0o644)
    displaced_peer = live_root / f"operator-moved-{operation}-expected-peer"
    original_exchange = live_publish._renameat2
    first_race = False
    recovery_race = False

    def race_both_exchange_seams(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal first_race, recovery_race
        if (
            flags == live_publish._RENAME_EXCHANGE
            and code == "exchange_failed"
            and not first_race
        ):
            first_race = True
            (live_root / destination_name).rename(displaced_peer)
            alternate.rename(live_root / destination_name)
        elif (
            flags == live_publish._RENAME_EXCHANGE
            and code == "exchange_repair_failed"
            and not recovery_race
        ):
            recovery_race = True
            os.rename(
                destination_name,
                "operator-moved-known-safe-tree",
                src_dir_fd=destination_parent_fd,
                dst_dir_fd=destination_parent_fd,
            )
            os.rename(
                recovery_attacker.name,
                destination_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=destination_parent_fd,
            )
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )

    monkeypatch.setattr(live_publish, "_renameat2", race_both_exchange_seams)
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        invoke()

    _prepared_transaction(target, operation)
    public_after = live_publish._snapshot_tree(live_root / SLUG, code="after")
    assert public_after.tree_sha256 == public_before.tree_sha256
    assert public_after.total_size_bytes == public_before.total_size_bytes
    assert len(public_after.files) == len(public_before.files)
    repair_parents = [
        path
        for path in live_root.iterdir()
        if path.name.startswith(f".property-live-repair-{operation}-")
    ]
    assert len(repair_parents) == 2
    retained_relpaths = {
        row.relpath
        for parent in repair_parents
        for row in live_publish._snapshot_tree(
            parent, code="retained_repair_evidence"
        ).files
    }
    assert "known-safe-tree/alternate.txt" in retained_relpaths
    assert "known-safe-tree/recovery.txt" in retained_relpaths
    assert first_race is True
    assert recovery_race is True


def test_pre_exchange_replacement_peer_substitution_restores_original_public_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    alternate = live_root / "alternate-replacement-peer"
    alternate.mkdir(mode=0o755)
    _write(alternate / "alternate.txt", b"alternate-replacement", 0o644)
    displaced_stage = live_root / "operator-moved-expected-replacement"
    original_exchange = live_publish._renameat2
    raced = False

    def substitute_peer_then_exchange(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        if (
            flags == live_publish._RENAME_EXCHANGE
            and code == "exchange_failed"
            and not raced
        ):
            raced = True
            (live_root / destination_name).rename(displaced_stage)
            alternate.rename(live_root / destination_name)
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )

    monkeypatch.setattr(live_publish, "_renameat2", substitute_peer_then_exchange)
    publication_path = receipt_root / "publication.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=publication_path,
        )

    prepared = _prepared_transaction(publication_path, "replace")
    public_tree = live_publish._snapshot_tree(live_root / SLUG, code="public")
    assert sorted(row.relpath for row in public_tree.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    repair_parents = [
        path
        for path in live_root.iterdir()
        if path.name.startswith(".property-live-repair-replace-")
    ]
    assert len(repair_parents) == 1
    assert (
        repair_parents[0] / "known-safe-tree" / "alternate.txt"
    ).read_bytes() == b"alternate-replacement"
    assert sorted(
        row.relpath
        for row in live_publish._snapshot_tree(
            live_root / str(prepared["peer_relpath"]), code="retained_original"
        ).files
    ) == ["legacy-floorplan.pdf", "legacy-listing.pdf"]
    assert live_publish._snapshot_tree(
        displaced_stage, code="displaced_stage"
    ).tree_sha256 == live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG,
        code="source",
    ).tree_sha256
    assert Path(str(prepared["expected_consumed_grant_path"])).exists()
    assert not grant_path.exists()


def test_post_exchange_peer_replacement_never_swaps_attacker_into_public_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    attacker = live_root / "attacker-peer"
    attacker.mkdir(mode=0o755)
    _write(attacker / "attacker.txt", b"attacker-bytes", 0o644)
    displaced_peer = live_root / "operator-moved-post-exchange-peer"
    original_exchange = live_publish._renameat2
    raced = False

    def exchange_then_replace_peer(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )
        if (
            flags == live_publish._RENAME_EXCHANGE
            and code == "exchange_failed"
            and not raced
        ):
            raced = True
            (live_root / destination_name).rename(displaced_peer)
            attacker.rename(live_root / destination_name)

    monkeypatch.setattr(live_publish, "_renameat2", exchange_then_replace_peer)
    publication_path = receipt_root / "publication.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=publication_path,
        )

    prepared = _prepared_transaction(publication_path, "replace")
    live_tree = live_publish._snapshot_tree(live_root / SLUG, code="live")
    source_tree = live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    )
    assert live_tree.tree_sha256 == source_tree.tree_sha256
    assert (displaced_peer / "legacy-listing.pdf").read_bytes() == b"legacy-pdf"
    assert (
        live_root / str(prepared["peer_relpath"]) / "attacker.txt"
    ).read_bytes() == b"attacker-bytes"


def test_post_exchange_volume_root_replacement_blocks_publication_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        package_root,
        live_root,
        receipt_root,
        precondition_path,
        grant_path,
        kwargs,
    ) = _precondition_and_grant(tmp_path)
    displaced_volume = tmp_path / "operator-moved-live-volume"
    original_exchange = live_publish._renameat2
    raced = False

    def exchange_then_replace_volume_root(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )
        if flags == live_publish._RENAME_EXCHANGE and code == "exchange_failed" and not raced:
            raced = True
            live_root.rename(displaced_volume)
            live_root.mkdir(mode=0o755)
            (displaced_volume / source_name).rename(live_root / source_name)
            (displaced_volume / destination_name).rename(
                live_root / destination_name
            )

    monkeypatch.setattr(
        live_publish, "_renameat2", exchange_then_replace_volume_root
    )
    publication_path = receipt_root / "publication.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_recovery_binding_drift",
    ):
        live_publish.publish_live_with_grant(
            **kwargs,
            precondition_receipt_path=precondition_path,
            grant_path=grant_path,
            publication_receipt_path=publication_path,
        )

    prepared = _prepared_transaction(publication_path, "replace")
    assert prepared["live_volume_root_identity"] != {
        "device": live_root.stat().st_dev,
        "inode": live_root.stat().st_ino,
    }
    assert live_publish._snapshot_tree(
        live_root / SLUG, code="new_live"
    ).tree_sha256 == live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    ).tree_sha256
    assert displaced_volume.exists()


def test_rollback_drift_fails_closed_without_consuming_rollback_grant(
    tmp_path: Path,
) -> None:
    _package, live_root, receipt_root, publication_path, _kwargs, publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    retained = live_root / str(publication["retained_rollback_relpath"])
    _write(retained / "legacy-listing.pdf", b"rollback-tree-drift", 0o644)

    with pytest.raises(live_publish.LivePublicationError, match="rollback_tree_drift"):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=receipt_root / "rollback.json",
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    assert grant_path.exists()
    assert len(live_publish._snapshot_tree(live_root / SLUG, code="live").files) == 6


def test_occupied_rollback_receipt_blocks_before_claim_or_exchange(
    tmp_path: Path,
) -> None:
    _package, live_root, receipt_root, publication_path, _kwargs, publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    rollback_path = receipt_root / "rollback.json"
    _write(rollback_path, b"occupied-rollback-receipt", 0o600)
    live_before = live_publish._snapshot_tree(live_root / SLUG, code="before")
    retained_path = live_root / str(publication["retained_rollback_relpath"])
    retained_before = live_publish._snapshot_tree(retained_path, code="retained")

    with pytest.raises(
        live_publish.LivePublicationError,
        match="rollback_receipt_reservation_failed",
    ):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=rollback_path,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    live_after = live_publish._snapshot_tree(live_root / SLUG, code="after")
    retained_after = live_publish._snapshot_tree(retained_path, code="retained")
    assert (live_after.root_inode, live_after.tree_sha256) == (
        live_before.root_inode,
        live_before.tree_sha256,
    )
    assert (retained_after.root_inode, retained_after.tree_sha256) == (
        retained_before.root_inode,
        retained_before.tree_sha256,
    )
    assert rollback_path.read_bytes() == b"occupied-rollback-receipt"
    assert grant_path.exists()


def test_rollback_receipt_failure_retains_prepared_recovery_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root, live_root, receipt_root, publication_path, _kwargs, publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )

    def fail_finalization(**_kwargs: object) -> None:
        raise live_publish.LivePublicationError("simulated_rollback_receipt_failure")

    monkeypatch.setattr(
        live_publish, "_finalize_transaction_receipt", fail_finalization
    )
    rollback_path = receipt_root / "rollback.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="simulated_rollback_receipt_failure",
    ):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=rollback_path,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    prepared = _prepared_transaction(rollback_path, "rollback")
    restored = live_publish._snapshot_tree(live_root / SLUG, code="restored")
    retained_published = live_publish._snapshot_tree(
        live_root / str(publication["retained_rollback_relpath"]),
        code="retained_published",
    )
    assert sorted(row.relpath for row in restored.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    assert retained_published.tree_sha256 == live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    ).tree_sha256
    assert Path(str(prepared["expected_consumed_grant_path"])).exists()
    assert not grant_path.exists()


def test_pre_exchange_rollback_peer_substitution_restores_published_public_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root, live_root, receipt_root, publication_path, _kwargs, publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    alternate = live_root / "alternate-rollback-peer"
    alternate.mkdir(mode=0o755)
    _write(alternate / "alternate.txt", b"alternate-rollback", 0o644)
    displaced_rollback = live_root / "operator-moved-expected-rollback"
    original_exchange = live_publish._renameat2
    raced = False

    def substitute_peer_then_exchange(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        if flags == live_publish._RENAME_EXCHANGE and code == "exchange_failed" and not raced:
            raced = True
            (live_root / destination_name).rename(displaced_rollback)
            alternate.rename(live_root / destination_name)
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )

    monkeypatch.setattr(live_publish, "_renameat2", substitute_peer_then_exchange)
    rollback_path = receipt_root / "rollback.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=rollback_path,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    prepared = _prepared_transaction(rollback_path, "rollback")
    public_tree = live_publish._snapshot_tree(live_root / SLUG, code="public")
    source_tree = live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    )
    assert public_tree.tree_sha256 == source_tree.tree_sha256
    repair_parents = [
        path
        for path in live_root.iterdir()
        if path.name.startswith(".property-live-repair-rollback-")
    ]
    assert len(repair_parents) == 1
    assert (
        repair_parents[0] / "known-safe-tree" / "alternate.txt"
    ).read_bytes() == b"alternate-rollback"
    assert live_publish._snapshot_tree(
        live_root / str(prepared["peer_relpath"]), code="retained_published"
    ).tree_sha256 == source_tree.tree_sha256
    assert sorted(
        row.relpath
        for row in live_publish._snapshot_tree(
            displaced_rollback, code="displaced_rollback"
        ).files
    ) == ["legacy-floorplan.pdf", "legacy-listing.pdf"]
    assert Path(str(prepared["expected_consumed_grant_path"])).exists()
    assert not grant_path.exists()
    assert publication["status"] == "published"


def test_rollback_post_exchange_peer_replacement_never_publishes_attacker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root, live_root, receipt_root, publication_path, _kwargs, publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    attacker = live_root / "rollback-attacker-peer"
    attacker.mkdir(mode=0o755)
    _write(attacker / "attacker.txt", b"rollback-attacker", 0o644)
    displaced_published = live_root / "operator-moved-published-tree"
    original_exchange = live_publish._renameat2
    raced = False

    def exchange_then_replace_peer(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )
        if flags == live_publish._RENAME_EXCHANGE and code == "exchange_failed" and not raced:
            raced = True
            (live_root / destination_name).rename(displaced_published)
            attacker.rename(live_root / destination_name)

    monkeypatch.setattr(live_publish, "_renameat2", exchange_then_replace_peer)
    rollback_path = receipt_root / "rollback.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_compare_and_swap_failed",
    ):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=rollback_path,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    prepared = _prepared_transaction(rollback_path, "rollback")
    restored = live_publish._snapshot_tree(live_root / SLUG, code="restored")
    assert sorted(row.relpath for row in restored.files) == [
        "legacy-floorplan.pdf",
        "legacy-listing.pdf",
    ]
    assert live_publish._snapshot_tree(
        displaced_published, code="published"
    ).tree_sha256 == live_publish._snapshot_tree(
        package_root / "public_property_tours" / SLUG, code="source"
    ).tree_sha256
    assert (
        live_root / str(prepared["peer_relpath"]) / "attacker.txt"
    ).read_bytes() == b"rollback-attacker"
    assert publication_path.exists()
    assert publication["status"] == "published"


def test_rollback_post_exchange_volume_root_replacement_blocks_final_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package, live_root, receipt_root, publication_path, _kwargs, _publication = (
        _publish(tmp_path)
    )
    grant_path = receipt_root / "rollback-grant.json"
    live_publish.create_rollback_grant(
        publication_receipt_path=publication_path,
        grant_path=grant_path,
        live_volume_root=live_root,
        receipt_root=receipt_root,
        origin=ORIGIN,
        logical_volume=LOGICAL_VOLUME,
        slug=SLUG,
        destination_relpath=SLUG,
        rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
    )
    displaced_volume = tmp_path / "operator-moved-rollback-volume"
    original_exchange = live_publish._renameat2
    raced = False

    def exchange_then_replace_volume_root(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
        flags: int,
        code: str,
    ) -> None:
        nonlocal raced
        original_exchange(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            flags,
            code,
        )
        if flags == live_publish._RENAME_EXCHANGE and code == "exchange_failed" and not raced:
            raced = True
            live_root.rename(displaced_volume)
            live_root.mkdir(mode=0o755)
            (displaced_volume / source_name).rename(live_root / source_name)
            (displaced_volume / destination_name).rename(
                live_root / destination_name
            )

    monkeypatch.setattr(
        live_publish, "_renameat2", exchange_then_replace_volume_root
    )
    rollback_path = receipt_root / "rollback.json"
    with pytest.raises(
        live_publish.LivePublicationError,
        match="exchange_recovery_binding_drift",
    ):
        live_publish.rollback_live_with_grant(
            publication_receipt_path=publication_path,
            grant_path=grant_path,
            rollback_receipt_path=rollback_path,
            live_volume_root=live_root,
            receipt_root=receipt_root,
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            rollback_user_instruction_sha256=ROLLBACK_INSTRUCTION_SHA256,
        )

    prepared = _prepared_transaction(rollback_path, "rollback")
    assert prepared["live_volume_root_identity"] != {
        "device": live_root.stat().st_dev,
        "inode": live_root.stat().st_ino,
    }
    assert sorted(
        row.relpath
        for row in live_publish._snapshot_tree(
            live_root / SLUG, code="new_live"
        ).files
    ) == ["legacy-floorplan.pdf", "legacy-listing.pdf"]
    assert displaced_volume.exists()


def test_receipts_must_be_outside_served_tree(tmp_path: Path) -> None:
    package_root = _build_package(tmp_path)
    live_root = _build_live_volume(tmp_path)
    with pytest.raises(
        live_publish.LivePublicationError, match="receipt_root_inside_served_tree"
    ):
        live_publish.inspect_live_precondition(
            package_root=package_root,
            live_volume_root=live_root,
            receipt_root=live_root / "receipts",
            origin=ORIGIN,
            logical_volume=LOGICAL_VOLUME,
            slug=SLUG,
            destination_relpath=SLUG,
            user_instruction_sha256=USER_INSTRUCTION_SHA256,
        )
    assert sorted(path.name for path in live_root.iterdir()) == [SLUG]


@pytest.mark.parametrize(
    "origin",
    [
        "https://propertyquarry.com.",
        "https://propertyquarry.com:443",
        "https://propertyquarry.com/path",
        "https://propertyquarry.com.evil.test",
        "HTTPS://propertyquarry.com",
    ],
)
def test_origin_binding_is_exact_and_canonical(tmp_path: Path, origin: str) -> None:
    _package_root, _live_root, _receipt_root, kwargs = _common(tmp_path)
    kwargs["origin"] = origin
    with pytest.raises(live_publish.LivePublicationError, match="origin_invalid|origin_unauthorized"):
        live_publish.inspect_live_precondition(**kwargs)
