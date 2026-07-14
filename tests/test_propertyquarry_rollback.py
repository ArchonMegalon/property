from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from scripts import propertyquarry_rollback as rollback


CURRENT_SHA = "1" * 40
PREVIOUS_SHA = "2" * 40


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "PROPERTYQUARRY_ROLLBACK_CURRENT_RELEASE": CURRENT_SHA,
        "PROPERTYQUARRY_ROLLBACK_PREVIOUS_RELEASE": PREVIOUS_SHA,
        "PROPERTYQUARRY_ROLLBACK_SIGNED_AUTHORIZATION": "/run/propertyquarry/rollback-authority.json",
        "PROPERTYQUARRY_ROLLBACK_SCHEMA_COMPATIBILITY_COMMAND": "candidate-schema-check",
        "PROPERTYQUARRY_ROLLBACK_TRAFFIC_SWITCH_COMMAND": "candidate-traffic-switch",
        "PROPERTYQUARRY_ROLLBACK_HEALTH_VERIFY_COMMAND": "candidate-health",
        "PROPERTYQUARRY_ROLLBACK_VERSION_VERIFY_COMMAND": "candidate-version",
        "PROPERTYQUARRY_ROLLBACK_PUBLIC_VERIFY_COMMAND": "candidate-public",
        "PROPERTYQUARRY_ROLLBACK_AUTH_VERIFY_COMMAND": "candidate-auth",
        "PROPERTYQUARRY_ROLLBACK_SCHEDULER_VERIFY_COMMAND": "candidate-scheduler",
    }
    values.update(overrides)
    return values


class NoMutationRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> rollback.CommandResult:
        self.calls.append(tuple(argv))
        raise AssertionError("candidate rollback commands must never execute")


def test_release_identifiers_must_be_immutable_and_distinct(tmp_path: Path) -> None:
    invalid = _environment(PROPERTYQUARRY_ROLLBACK_PREVIOUS_RELEASE="propertyquarry:latest")
    receipt, exit_code = rollback.run_rollback(
        environ=invalid,
        receipt_path=tmp_path / "invalid.json",
        execute=False,
    )
    assert exit_code == 2
    assert "full 40-character Git SHA" in receipt["error"]["message"]

    same = _environment(PROPERTYQUARRY_ROLLBACK_PREVIOUS_RELEASE=CURRENT_SHA.upper())
    receipt, exit_code = rollback.run_rollback(
        environ=same,
        receipt_path=tmp_path / "same.json",
        execute=False,
    )
    assert exit_code == 2
    assert "same immutable identifier" in receipt["error"]["message"]


def test_default_dry_run_is_command_free_non_authoritative_and_private(
    tmp_path: Path,
) -> None:
    runner = NoMutationRunner()
    receipt_path = tmp_path / "dry-run.json"
    receipt, exit_code = rollback.run_rollback(
        environ=_environment(),
        receipt_path=receipt_path,
        execute=False,
        runner=runner,
    )

    assert exit_code == 0
    assert receipt["status"] == "dry_run"
    assert receipt["execution_ready"] is False
    assert runner.calls == []
    assert "external_controller.rollback-run" in json.dumps(receipt)
    assert "external_controller" not in receipt
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600


def test_source_execute_fails_before_identity_commands_or_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = NoMutationRunner()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("candidate identity or command was inspected before containment")

    monkeypatch.setattr(rollback, "parse_release_identity", forbidden)
    receipt, exit_code = rollback.run_rollback(
        environ={
            "PROPERTYQUARRY_ROLLBACK_TRAFFIC_SWITCH_COMMAND": "attacker-switch --approve",
            "PROPERTYQUARRY_ROLLBACK_SIGNED_AUTHORIZATION": "/candidate/fake.json",
        },
        receipt_path=tmp_path / "execute-disabled.json",
        execute=True,
        runner=runner,
    )

    assert exit_code == 2
    assert receipt["error"]["type"] == "SourceExecutionDisabled"
    assert "installed native controller" in receipt["error"]["message"]
    assert receipt["command_boundary"]["traffic_switch_attempted"] is False
    assert runner.calls == []
    with pytest.raises(rollback.RollbackValidationError, match="source --execute is disabled"):
        rollback.SubprocessCommandRunner().run(
            ("candidate-traffic-switch",), env={}, timeout_seconds=1
        )


def test_real_source_execute_ignores_hostile_guard_and_controller_swap(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    scripts = candidate / "scripts"
    scripts.mkdir(parents=True)
    source = Path(rollback.__file__).resolve()
    entrypoint = scripts / source.name
    shutil.copyfile(source, entrypoint)
    entrypoint.chmod(0o755)
    marker = tmp_path / "candidate-authority-executed"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    fake_python = hostile_bin / "python3"
    fake_python.write_text(
        f"#!/bin/sh\nprintf '%s\\n' hostile-python >> '{marker}'\nexit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    swapped_controller = tmp_path / "controller"
    swapped_controller.write_text("original", encoding="utf-8")
    (scripts / "propertyquarry_deploy_controller_guard.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['HOSTILE_MARKER']).write_text('imported')\n"
        "Path(os.environ['HOSTILE_CONTROLLER']).write_text('swapped')\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "real-execute-disabled.json"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(scripts),
            "PATH": str(hostile_bin),
            "HOSTILE_MARKER": str(marker),
            "HOSTILE_CONTROLLER": str(swapped_controller),
            "PROPERTYQUARRY_ROLLBACK_TRAFFIC_SWITCH_COMMAND": "attacker-switch --approve",
        }
    )

    completed = subprocess.run(
        [
            str(entrypoint),
            "--execute",
            "--receipt",
            str(receipt_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["error"]["type"] == "SourceExecutionDisabled"
    assert payload["command_boundary"]["traffic_switch_attempted"] is False
    assert not marker.exists()
    assert swapped_controller.read_text(encoding="utf-8") == "original"


def test_rollback_source_has_no_candidate_controller_authority() -> None:
    source = Path(rollback.__file__).read_text(encoding="utf-8")

    assert "propertyquarry_deploy_controller_guard" not in source
    assert "invoke_controller" not in source
    assert "controller_invoker" not in source
    assert source.startswith("#!/usr/bin/python3 -I\n")
