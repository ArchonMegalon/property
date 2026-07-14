#!/usr/bin/env python3
"""Reference cache format for the externally sealed deploy journal.

Production CLI operations are delegated to the independently installed
controller, which holds the fixed controller lock and performs monotonic CAS.
The local JSON helpers remain for deterministic cache-contract tests only and
are never a production source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__:
    from scripts import propertyquarry_deploy_controller_guard as controller_guard
else:
    import propertyquarry_deploy_controller_guard as controller_guard


SCHEMA = "propertyquarry.deploy-containment-journal.v1"
PRODUCER = "propertyquarry-deploy-controller"
JOURNAL_PATH = Path("/var/lib/propertyquarry/release-control/deploy-containment-journal.v1.json")
PHASE_ORDER = {
    "armed": 10,
    "writers_quiesced": 20,
    "migration_committed": 30,
    "proofs_running": 40,
    "receipt_consumed": 50,
    "ingress_starting": 60,
    "public_verified": 70,
    "promotion_complete": 80,
    "contained": 90,
}
TERMINAL_PHASES = {"promotion_complete", "contained"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")


class DeployJournalError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _exact_keys(value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise DeployJournalError("deploy journal fields do not match the canonical schema")


def _validate(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeployJournalError("deploy journal must be a JSON object")
    _exact_keys(
        payload,
        {
            "schema",
            "producer",
            "deployment_id",
            "release_commit_sha",
            "release_image_digest",
            "writer_topology_sha256",
            "phase",
            "updated_at",
        },
    )
    if payload["schema"] != SCHEMA or payload["producer"] != PRODUCER:
        raise DeployJournalError("deploy journal identity is invalid")
    if not IDENTIFIER_RE.fullmatch(str(payload["deployment_id"] or "")):
        raise DeployJournalError("deploy journal deployment id is invalid")
    if not SHA_RE.fullmatch(str(payload["release_commit_sha"] or "")):
        raise DeployJournalError("deploy journal release SHA is invalid")
    if not DIGEST_RE.fullmatch(str(payload["release_image_digest"] or "")):
        raise DeployJournalError("deploy journal image digest is invalid")
    if not SHA256_RE.fullmatch(str(payload["writer_topology_sha256"] or "")):
        raise DeployJournalError("deploy journal topology digest is invalid")
    if payload["phase"] not in PHASE_ORDER:
        raise DeployJournalError("deploy journal phase is invalid")
    if not isinstance(payload["updated_at"], str) or not payload["updated_at"].endswith("Z"):
        raise DeployJournalError("deploy journal update time is invalid")
    return payload


def load_journal() -> dict[str, Any] | None:
    if not JOURNAL_PATH.exists():
        return None
    try:
        payload = json.loads(JOURNAL_PATH.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeployJournalError(f"deploy journal is unreadable or corrupt: {exc}") from exc
    return _validate(payload)


def _atomic_write(payload: Mapping[str, Any]) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{JOURNAL_PATH.name}.", dir=str(JOURNAL_PATH.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, JOURNAL_PATH)
        os.chmod(JOURNAL_PATH, 0o600)
        directory_fd = os.open(JOURNAL_PATH.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def record_phase(
    *,
    deployment_id: str,
    release_commit_sha: str,
    release_image_digest: str,
    writer_topology_sha256: str,
    phase: str,
) -> dict[str, Any]:
    candidate = _validate(
        {
            "schema": SCHEMA,
            "producer": PRODUCER,
            "deployment_id": deployment_id,
            "release_commit_sha": release_commit_sha,
            "release_image_digest": release_image_digest,
            "writer_topology_sha256": writer_topology_sha256,
            "phase": phase,
            "updated_at": _utc_now(),
        }
    )
    current = load_journal()
    if current is not None:
        same_deployment = current["deployment_id"] == deployment_id
        if not same_deployment and (
            current["phase"] not in TERMINAL_PHASES or phase != "armed"
        ):
            raise DeployJournalError(
                "an incomplete prior deployment must be reconciled before a new deployment"
            )
        if same_deployment:
            for key in ("release_commit_sha", "release_image_digest", "writer_topology_sha256"):
                if current[key] != candidate[key]:
                    raise DeployJournalError("deploy journal candidate binding changed mid-deployment")
            if current["phase"] in TERMINAL_PHASES:
                raise DeployJournalError("terminal deploy journal state cannot be reopened")
            if PHASE_ORDER[phase] <= PHASE_ORDER[str(current["phase"])]:
                raise DeployJournalError("deploy journal phase must advance monotonically")
    _atomic_write(candidate)
    return candidate


def mark_contained() -> dict[str, Any]:
    current = load_journal()
    if current is None:
        raise DeployJournalError("cannot mark containment without an active deploy journal")
    if current["phase"] == "contained":
        return current
    current = dict(current)
    current["phase"] = "contained"
    current["updated_at"] = _utc_now()
    _atomic_write(current)
    return current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    record = subparsers.add_parser("record")
    record.add_argument("--deployment-id", required=True)
    record.add_argument("--release-sha", required=True)
    record.add_argument("--image-digest", required=True)
    record.add_argument("--writer-topology-sha256", required=True)
    record.add_argument("--phase", choices=tuple(PHASE_ORDER), required=True)
    subparsers.add_parser("mark-contained")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return controller_guard.invoke_controller("journal-status", [])
        elif args.command == "mark-contained":
            return controller_guard.invoke_controller("journal-mark-contained", [])
        else:
            return controller_guard.invoke_controller(
                "journal-record",
                [
                    "--deployment-id",
                    args.deployment_id,
                    "--release-sha",
                    args.release_sha,
                    "--image-digest",
                    args.image_digest,
                    "--writer-topology-sha256",
                    args.writer_topology_sha256,
                    "--phase",
                    args.phase,
                ],
            )
    except (DeployJournalError, controller_guard.ControllerGuardError) as exc:
        print(f"deploy journal rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
