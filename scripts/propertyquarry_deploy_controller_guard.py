#!/usr/bin/python3 -I
"""Read-only legacy attestation for the installed release controller.

The candidate checkout is not a release authority and invocation is disabled.
This guard accepts no
path, digest, key, or state selector from the caller.  It validates one fixed
root-owned controller and external manifest, verifies that the fixed deploy
lock is held, and delegates the complete privileged operation to that
controller.  The tracked manifest is deliberately UNCONFIGURED until release
control provisions the external controller and advances the compiled pins.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


SCHEMA = "propertyquarry.external-deploy-controller.v1"
TRACKED_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "release"
    / "propertyquarry_external_deploy_controller.v1.json"
)
EXTERNAL_MANIFEST_PATH = Path(
    "/etc/propertyquarry/release-control/external-deploy-controller.v1.json"
)
CONTROLLER_PATH = Path(
    "/usr/libexec/propertyquarry-release-control/propertyquarry-deploy-controller"
)
CONTROLLER_LOCK_PATH = Path("/var/lock/propertyquarry/deploy-controller.lock")
MANIFEST_STATUS = "UNCONFIGURED"
MANIFEST_SHA256 = "617196bbb307759432e72f54581b1947d04083a2f1e619d8b718b88f2a95bb47"
CONTROLLER_SHA256 = "UNCONFIGURED"
MONOTONIC_AUTHORITY_ID = "UNCONFIGURED"
MINIMUM_MONOTONIC_GENERATION = 0
REQUIRED_UID = 0
SECURE_PATH_ROOT = Path("/")
EXTERNAL_MANIFEST_MODE = 0o444
CONTROLLER_MODE = 0o555

OPERATIONS = {
    "attest",
    "journal-status",
    "journal-reconcile-incomplete",
    "journal-record",
    "journal-mark-contained",
    "state-read",
    "state-compare-and-swap",
    "drain-verify",
    "promotion-consume",
    "database-observe",
    "database-contain-and-fence",
    "database-fence-status",
    "migration-run",
    "database-fence-release",
    "recovery-run",
    "rollback-run",
}
FORBIDDEN_SELECTOR_ENV = (
    "PROPERTYQUARRY_DEPLOY_CONTROLLER_PATH",
    "PROPERTYQUARRY_DEPLOY_CONTROLLER_SHA256",
    "PROPERTYQUARRY_DEPLOY_CONTROLLER_MANIFEST",
    "PROPERTYQUARRY_DEPLOY_MONOTONIC_AUTHORITY",
)


class ControllerGuardError(RuntimeError):
    """The external release controller could not be authenticated or invoked."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ControllerGuardError(f"controller manifest contains duplicate key {key}")
        result[key] = value
    return result


def _read_stable_regular_bytes(
    path: Path,
    *,
    label: str,
    maximum_size: int = 1024 * 1024,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ControllerGuardError(f"{label} is unavailable: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ControllerGuardError(f"{label} must be a regular non-symlink file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(raw) > maximum_size or (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ControllerGuardError(f"{label} changed while it was read")
    return raw


def _read_json_file(path: Path, *, label: str) -> dict[str, Any]:
    raw = _read_stable_regular_bytes(path, label=label)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ControllerGuardError(f"{label} contains non-finite constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerGuardError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ControllerGuardError(f"{label} must be a JSON object")
    return payload


def _validate_secure_path(
    path: Path,
    *,
    label: str,
    mode: int,
    executable: bool,
) -> os.stat_result:
    if not path.is_absolute():
        raise ControllerGuardError(f"{label} path must be absolute")
    try:
        relative = path.relative_to(SECURE_PATH_ROOT)
    except ValueError as exc:
        raise ControllerGuardError(f"{label} escapes the fixed secure root") from exc
    current = SECURE_PATH_ROOT
    root_metadata = current.lstat()
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != REQUIRED_UID
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        raise ControllerGuardError(f"{label} secure root ownership or mode is unsafe")
    for part in relative.parts[:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ControllerGuardError(f"{label} parent is unavailable: {exc}") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != REQUIRED_UID
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ControllerGuardError(f"{label} parent ownership or mode is unsafe")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ControllerGuardError(f"{label} is unavailable: {exc}") from exc
    expected_type = stat.S_ISREG(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not expected_type
        or metadata.st_uid != REQUIRED_UID
        or stat.S_IMODE(metadata.st_mode) != mode
        or metadata.st_nlink != 1
    ):
        kind = "executable" if executable else "manifest"
        raise ControllerGuardError(
            f"{label} must be a single-link, root-owned, non-symlink {kind} with mode {mode:04o}"
        )
    return metadata


def _validate_manifest(payload: Mapping[str, Any]) -> None:
    expected = {
        "schema",
        "status",
        "controller_path",
        "controller_sha256",
        "protocol_version",
        "monotonic_authority_id",
        "minimum_monotonic_generation",
    }
    if set(payload) != expected:
        raise ControllerGuardError("controller manifest fields do not match the v1 contract")
    if (
        payload["schema"] != SCHEMA
        or payload["status"] != "active"
        or payload["controller_path"] != str(CONTROLLER_PATH)
        or payload["controller_sha256"] != CONTROLLER_SHA256
        or payload["protocol_version"] != 1
        or payload["monotonic_authority_id"] != MONOTONIC_AUTHORITY_ID
        or payload["minimum_monotonic_generation"] != MINIMUM_MONOTONIC_GENERATION
    ):
        raise ControllerGuardError("controller manifest identity or monotonic pins are invalid")


def validate_external_controller() -> dict[str, Any]:
    selected = [name for name in FORBIDDEN_SELECTOR_ENV if os.environ.get(name)]
    if selected:
        raise ControllerGuardError(
            "caller-selected controller configuration is forbidden: " + ", ".join(selected)
        )
    tracked = _read_json_file(TRACKED_MANIFEST_PATH, label="tracked controller manifest")
    if hashlib.sha256(_canonical_bytes(tracked)).hexdigest() != MANIFEST_SHA256:
        raise ControllerGuardError("tracked controller manifest does not match its compiled pin")
    if MANIFEST_STATUS != "active" or tracked.get("status") != "active":
        raise ControllerGuardError(
            "external deploy controller is UNCONFIGURED; privileged release actions are blocked"
        )
    _validate_manifest(tracked)
    _validate_secure_path(
        EXTERNAL_MANIFEST_PATH,
        label="external controller manifest",
        mode=EXTERNAL_MANIFEST_MODE,
        executable=False,
    )
    external = _read_json_file(EXTERNAL_MANIFEST_PATH, label="external controller manifest")
    if _canonical_bytes(external) != _canonical_bytes(tracked):
        raise ControllerGuardError("external controller manifest does not match reviewed metadata")
    _validate_secure_path(
        CONTROLLER_PATH,
        label="external deploy controller",
        mode=CONTROLLER_MODE,
        executable=True,
    )
    controller_bytes = _read_stable_regular_bytes(
        CONTROLLER_PATH,
        label="external deploy controller",
        maximum_size=16 * 1024 * 1024,
    )
    actual_hash = hashlib.sha256(controller_bytes).hexdigest()
    if actual_hash != CONTROLLER_SHA256:
        raise ControllerGuardError("external deploy controller does not match its immutable hash pin")
    return dict(external)


def _validate_lock_descriptor(descriptor: int) -> None:
    try:
        supplied = os.fstat(descriptor)
        fixed = CONTROLLER_LOCK_PATH.stat()
    except OSError as exc:
        raise ControllerGuardError(f"fixed controller lock descriptor is invalid: {exc}") from exc
    if not stat.S_ISREG(supplied.st_mode) or (supplied.st_dev, supplied.st_ino) != (
        fixed.st_dev,
        fixed.st_ino,
    ):
        raise ControllerGuardError("controller lock descriptor does not reference the fixed lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise ControllerGuardError("controller lock descriptor is not held exclusively") from exc


@contextmanager
def controller_lock(inherited_fd: int | None = None) -> Iterator[int]:
    if inherited_fd is not None:
        _validate_lock_descriptor(inherited_fd)
        yield inherited_fd
        return
    CONTROLLER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor = os.open(CONTROLLER_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ControllerGuardError("another release operation holds the fixed controller lock") from exc
        yield descriptor
    finally:
        os.close(descriptor)


def invoke_controller(
    operation: str,
    arguments: Sequence[str],
    *,
    inherited_lock_fd: int | None = None,
) -> int:
    del arguments, inherited_lock_fd
    if operation not in OPERATIONS:
        raise ControllerGuardError(f"unsupported external controller operation: {operation}")
    raise ControllerGuardError(
        "candidate Python controller invocation is disabled; invoke the installed "
        f"native controller directly: {CONTROLLER_PATH} {operation}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    parser.add_argument("--controller-lock-fd", type=int)
    parser.add_argument("controller_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    controller_args = list(args.controller_args)
    if controller_args[:1] == ["--"]:
        controller_args = controller_args[1:]
    try:
        return invoke_controller(
            args.operation,
            controller_args,
            inherited_lock_fd=args.controller_lock_fd,
        )
    except ControllerGuardError as exc:
        print(f"external deploy controller rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
