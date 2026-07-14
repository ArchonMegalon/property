#!/usr/bin/python3 -I
"""Command-free PropertyQuarry rollback planner with private receipts.

Source ``--execute`` is deliberately disabled before identity or command
inspection. Privileged rollback belongs only to the independently installed
native release controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence


RECEIPT_SCHEMA = "propertyquarry.rollback_receipt.v1"
INSTALLED_CONTROLLER_PATH = Path(
    "/usr/libexec/propertyquarry-release-control/propertyquarry-deploy-controller"
)
SOURCE_EXECUTION_DISABLED = (
    "source --execute is disabled; invoke the installed native controller "
    f"directly as the privileged operator: {INSTALLED_CONTROLLER_PATH} rollback-run"
)
DEFAULT_COMMAND_TIMEOUT_SECONDS = 300
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
IMAGE_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-fA-F]{64}$")
URI_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@")
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)^(?P<key>[^=]*(?:token|password|passwd|secret|authorization|api[_-]?key)[^=]*)=(?P<value>.*)$"
)
SENSITIVE_FLAG_RE = re.compile(
    r"(?i)^--?(?:token|password|passwd|secret|authorization|api[_-]?key|access[_-]?token)$"
)

COMMAND_ENV_BY_STEP = {
    "current_version": "PROPERTYQUARRY_ROLLBACK_VERSION_VERIFY_COMMAND",
    "schema_compatibility": "PROPERTYQUARRY_ROLLBACK_SCHEMA_COMPATIBILITY_COMMAND",
    "traffic_switch": "PROPERTYQUARRY_ROLLBACK_TRAFFIC_SWITCH_COMMAND",
    "health": "PROPERTYQUARRY_ROLLBACK_HEALTH_VERIFY_COMMAND",
    "version": "PROPERTYQUARRY_ROLLBACK_VERSION_VERIFY_COMMAND",
    "public": "PROPERTYQUARRY_ROLLBACK_PUBLIC_VERIFY_COMMAND",
    "auth": "PROPERTYQUARRY_ROLLBACK_AUTH_VERIFY_COMMAND",
    "scheduler": "PROPERTYQUARRY_ROLLBACK_SCHEDULER_VERIFY_COMMAND",
}

STEP_PHASE = {
    "current_version": "pre_switch",
    "schema_compatibility": "pre_switch",
    "traffic_switch": "traffic_switch",
    "health": "post_rollback",
    "version": "post_rollback",
    "public": "post_rollback",
    "auth": "post_rollback",
    "scheduler": "post_rollback",
}


class RollbackError(RuntimeError):
    """Base rollback error."""


class RollbackValidationError(RollbackError):
    """Invalid operator input or environment."""


class RollbackCommandError(RollbackError):
    """A guarded command failed."""


@dataclass(frozen=True)
class ReleaseIdentity:
    kind: str
    value: str
    immutable_key: str

    def receipt_value(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> CommandResult:
        del argv, env, timeout_seconds
        raise RollbackValidationError(SOURCE_EXECUTION_DISABLED)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_release_identity(raw: str, *, field_name: str) -> ReleaseIdentity:
    value = str(raw or "").strip()
    if GIT_SHA_RE.fullmatch(value):
        normalized = value.lower()
        return ReleaseIdentity("git_commit", normalized, f"git:{normalized}")
    if DIGEST_RE.fullmatch(value):
        normalized = value.lower()
        return ReleaseIdentity("image_digest", normalized, f"image:{normalized}")
    if IMAGE_DIGEST_RE.fullmatch(value):
        prefix, digest = value.rsplit("@", 1)
        normalized_digest = digest.lower()
        return ReleaseIdentity(
            "image_digest",
            f"{prefix}@{normalized_digest}",
            f"image:{normalized_digest}",
        )
    raise RollbackValidationError(
        f"{field_name} must be a full 40-character Git SHA, sha256 digest, "
        "or immutable image reference ending in @sha256:<64 hex>"
    )


def expected_confirmation(current: ReleaseIdentity, target: ReleaseIdentity) -> str:
    return f"ROLLBACK PROPERTYQUARRY FROM {current.value} TO {target.value}"


def positive_int(raw: str, *, field_name: str, default: int) -> int:
    value = str(raw or "").strip()
    if not value:
        return default
    if not value.isdigit() or int(value) <= 0:
        raise RollbackValidationError(f"{field_name} must be a positive integer")
    return int(value)


def parse_command(raw: str, *, field_name: str) -> tuple[str, ...]:
    value = str(raw or "").strip()
    if not value:
        raise RollbackValidationError(f"{field_name} is required")
    try:
        argv = tuple(shlex.split(value))
    except ValueError as exc:
        raise RollbackValidationError(f"{field_name} is not valid shell-style argv: {exc}") from exc
    if not argv:
        raise RollbackValidationError(f"{field_name} must contain an executable")
    return argv


def redact_text(value: str) -> str:
    return URI_CREDENTIAL_RE.sub(r"\g<scheme>***@", str(value or ""))


def redact_argv(argv: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for item in argv:
        value = str(item)
        if redact_next:
            redacted.append("***")
            redact_next = False
            continue
        assignment = SENSITIVE_ASSIGNMENT_RE.match(value)
        if assignment:
            redacted.append(f"{assignment.group('key')}=***")
            continue
        redacted.append(redact_text(value))
        if SENSITIVE_FLAG_RE.fullmatch(value):
            redact_next = True
    return redacted


def output_evidence(value: str) -> dict[str, object]:
    encoded = str(value or "").encode("utf-8", errors="replace")
    return {
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def version_identity_from_output(output: str, expected: ReleaseIdentity) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RollbackCommandError("version verification must emit one JSON object") from exc
    if not isinstance(payload, dict):
        raise RollbackCommandError("version verification must emit one JSON object")

    if expected.kind == "git_commit":
        observed = str(payload.get("release_commit_sha") or "").strip().lower()
        if not GIT_SHA_RE.fullmatch(observed):
            raise RollbackCommandError(
                "version verification did not emit a full release_commit_sha"
            )
        return observed

    observed = str(
        payload.get("release_image_digest")
        or payload.get("image_digest")
        or payload.get("web_image_digest")
        or ""
    ).strip()
    if IMAGE_DIGEST_RE.fullmatch(observed):
        observed = observed.rsplit("@", 1)[1]
    observed = observed.lower()
    if not DIGEST_RE.fullmatch(observed):
        raise RollbackCommandError(
            "version verification did not emit release_image_digest, image_digest, "
            "or web_image_digest as sha256:<64 hex>"
        )
    return observed


def version_matches(expected: ReleaseIdentity, observed: str) -> bool:
    if expected.kind == "git_commit":
        return observed == expected.value
    expected_digest = expected.value.rsplit("@", 1)[-1]
    return observed == expected_digest


def atomic_write_receipt(path: Path, payload: Mapping[str, object], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise RollbackValidationError(
            f"receipt already exists: {path}; use a unique path or --overwrite"
        )
    if path.exists() and path.is_dir():
        raise RollbackValidationError(f"receipt path is a directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        temporary_path.unlink(missing_ok=True)


def _step_plan(commands: Mapping[str, Sequence[str]]) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "phase": STEP_PHASE[name],
            "command": redact_argv(commands[name]),
            "status": "planned",
        }
        for name in COMMAND_ENV_BY_STEP
    ]


def _run_step(
    *,
    name: str,
    argv: Sequence[str],
    runner: CommandRunner,
    command_env: Mapping[str, str],
    timeout_seconds: int,
    monotonic: Callable[[], float],
    now: Callable[[], datetime],
) -> tuple[dict[str, object], CommandResult]:
    del name, argv, runner, command_env, timeout_seconds, monotonic, now
    raise RollbackValidationError(SOURCE_EXECUTION_DISABLED)


def run_rollback(
    *,
    environ: Mapping[str, str],
    receipt_path: Path,
    execute: bool,
    confirmation: str = "",
    overwrite: bool = False,
    runner: CommandRunner | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = utc_now,
) -> tuple[dict[str, object], int]:
    if receipt_path.exists() and not overwrite:
        raise RollbackValidationError(
            f"receipt already exists: {receipt_path}; use a unique path or --overwrite"
        )
    if receipt_path.exists() and receipt_path.is_dir():
        raise RollbackValidationError(f"receipt path is a directory: {receipt_path}")

    started_monotonic = monotonic()
    started_at = now()
    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "operation": "rollback",
        "mode": "execute" if execute else "dry_run",
        "status": "failed",
        "started_at": isoformat(started_at),
        "completed_at": None,
        "elapsed_seconds": None,
        "release": {},
        "confirmation": {
            "required_for_execution": True,
            "matched": False,
        },
        "command_boundary": {
            "traffic_switch_attempted": False,
            "traffic_switch_completed": False,
        },
        "steps": [],
        "verification": {
            "current_version": {"passed": False, "observed_release": None},
            "health": False,
            "version": {"passed": False, "observed_release": None},
            "public": False,
            "auth": False,
            "scheduler": False,
        },
        "error": None,
    }
    if execute:
        receipt["error"] = {
            "type": "SourceExecutionDisabled",
            "message": SOURCE_EXECUTION_DISABLED,
        }
        receipt["completed_at"] = isoformat(now())
        receipt["elapsed_seconds"] = round(
            max(0.0, monotonic() - started_monotonic), 6
        )
        atomic_write_receipt(receipt_path, receipt, overwrite=overwrite)
        return receipt, 2

    exit_code = 0
    active_step: dict[str, object] | None = None

    try:
        current = parse_release_identity(
            environ.get("PROPERTYQUARRY_ROLLBACK_CURRENT_RELEASE", ""),
            field_name="PROPERTYQUARRY_ROLLBACK_CURRENT_RELEASE",
        )
        target = parse_release_identity(
            environ.get("PROPERTYQUARRY_ROLLBACK_PREVIOUS_RELEASE", ""),
            field_name="PROPERTYQUARRY_ROLLBACK_PREVIOUS_RELEASE",
        )
        if current.immutable_key == target.immutable_key:
            raise RollbackValidationError(
                "current and previous releases resolve to the same immutable identifier"
            )
        receipt["release"] = {
            "current": current.receipt_value(),
            "target_previous": target.receipt_value(),
        }

        required_confirmation = expected_confirmation(current, target)
        supplied_confirmation = str(
            confirmation
            or environ.get("PROPERTYQUARRY_ROLLBACK_CONFIRMATION", "")
            or ""
        )
        confirmation_matched = supplied_confirmation == required_confirmation
        receipt["confirmation"] = {
            "required_for_execution": True,
            "matched": confirmation_matched,
            "expected_sha256": hashlib.sha256(required_confirmation.encode("utf-8")).hexdigest(),
        }

        receipt["steps"] = [
            {
                "name": "external_controller.rollback-run",
                "status": "planned",
                "owns": [
                    "fixed_lock",
                    "external_monotonic_state",
                    "journal_containment",
                    "database_fence",
                    "forward_schema_compatibility",
                    "traffic_and_verification",
                ],
            }
        ]
        receipt["status"] = "dry_run"
        receipt["execution_ready"] = False
    except RollbackValidationError as exc:
        exit_code = 2
        receipt["error"] = {
            "type": type(exc).__name__,
            "message": redact_text(str(exc)),
        }
    except RollbackError as exc:
        exit_code = 1
        receipt["error"] = {
            "type": type(exc).__name__,
            "message": redact_text(str(exc)),
        }
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
        exit_code = 1
        receipt["error"] = {
            "type": type(exc).__name__,
            "message": redact_text(str(exc)),
        }

    completed_at = now()
    receipt["completed_at"] = isoformat(completed_at)
    receipt["elapsed_seconds"] = round(max(0.0, monotonic() - started_monotonic), 6)
    atomic_write_receipt(receipt_path, receipt, overwrite=overwrite)
    return receipt, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan an isolated PropertyQuarry rollback. Source execution is "
            "disabled; use the installed native controller."
        )
    )
    parser.add_argument("--receipt", required=True, type=Path, help="JSON receipt destination")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="fail closed; source execution is disabled and the installed controller is required",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="exact release-bound confirmation; PROPERTYQUARRY_ROLLBACK_CONFIRMATION is also accepted",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing receipt path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt, exit_code = run_rollback(
            environ=os.environ,
            receipt_path=args.receipt,
            execute=bool(args.execute),
            confirmation=str(args.confirm or ""),
            overwrite=bool(args.overwrite),
        )
    except RollbackValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if exit_code:
        error = receipt.get("error")
        message = error.get("message") if isinstance(error, dict) else "rollback failed"
        print(f"error: {message}", file=sys.stderr)
    else:
        print(json.dumps(receipt, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
