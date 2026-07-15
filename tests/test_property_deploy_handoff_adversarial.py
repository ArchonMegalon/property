"""Executable fail-closed tests for the unprivileged release handoff.

The real host's Docker authority correctly prevents a full invocation.  The
deeper cases therefore execute a copied handoff whose only substitutions are
drift-checked temporary authority paths, test UID/GID, Docker-socket probe, and
temporary parent-chain boundary.  Nothing writes to /etc, /usr, or Docker.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "scripts" / "deploy_propertyquarry.sh"


def _replace_once(source: str, old: str, new: str) -> str:
    """Keep every test-only handoff substitution explicit and drift-sensitive."""
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class HandoffSandbox:
    root: Path
    candidate_root: Path
    authority_root: Path
    script: Path
    controller: Path
    manifest: Path
    pin: Path
    request: Path
    docker_socket_probe: Path
    compose_plan: Path
    database_policy: Path
    drain_keyring: Path
    gateway_trust: Path
    monitoring_topology: Path
    monitoring_tools: Path

    def environment(self, **overrides: str | None) -> dict[str, str]:
        env = {
            "HOME": str(self.root / "home"),
            "PATH": "/usr/bin:/bin",
            "EA_RUNTIME_MODE": "prod",
            "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST": str(self.request),
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.script), *arguments],
            cwd=cwd or self.candidate_root,
            env=env or self.environment(),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def set_controller(self, source: Path, *, append_bytes: int = 0) -> None:
        self.controller.chmod(0o700)
        shutil.copyfile(source, self.controller)
        if append_bytes:
            with self.controller.open("ab") as handle:
                handle.truncate(self.controller.stat().st_size + append_bytes)
        self.controller.chmod(0o555)
        self.refresh_pin()

    def set_controller_bytes(self, payload: bytes, *, refresh_pin: bool = True) -> None:
        self.controller.chmod(0o700)
        self.controller.write_bytes(payload)
        self.controller.chmod(0o555)
        if refresh_pin:
            self.refresh_pin()

    def refresh_pin(self) -> None:
        self.pin.chmod(0o600)
        self.pin.write_text(f"{_sha256(self.controller)}\n", encoding="ascii")
        self.pin.chmod(0o444)

    def set_pin(self, payload: bytes) -> None:
        self.pin.chmod(0o600)
        self.pin.write_bytes(payload)
        self.pin.chmod(0o444)

    def set_request(self, payload: bytes, *, mode: int = 0o400) -> None:
        self.request.chmod(0o600)
        self.request.write_bytes(payload)
        self.request.chmod(mode)


def _build_sandbox(tmp_path: Path) -> HandoffSandbox:
    candidate_root = tmp_path / "candidate"
    authority_root = tmp_path / "authority"
    script = candidate_root / "scripts" / HANDOFF.name
    controller = authority_root / "usr/libexec/propertyquarry-release-control/controller"
    manifest = authority_root / "etc/propertyquarry/release-control/controller.json"
    pin = authority_root / "etc/propertyquarry/release-control/controller.sha256"
    request = tmp_path / "request.json"
    docker_socket_probe = authority_root / "absent-docker.sock"
    compose_plan = authority_root / "etc/propertyquarry/release-control/compose.json"
    database_policy = authority_root / "etc/propertyquarry/release-control/database.json"
    drain_keyring = authority_root / "etc/propertyquarry/release-control/drain.json"
    gateway_trust = authority_root / "etc/propertyquarry/gateway.json"
    monitoring_topology = authority_root / "etc/propertyquarry/monitoring-topology.json"
    monitoring_tools = authority_root / "etc/propertyquarry/monitoring-tools.json"

    script.parent.mkdir(parents=True)
    controller.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    for directory in (
        authority_root,
        authority_root / "usr",
        authority_root / "usr/libexec",
        controller.parent,
        authority_root / "etc",
        authority_root / "etc/propertyquarry",
        manifest.parent,
    ):
        directory.chmod(0o700)

    shutil.copyfile("/usr/bin/echo", controller)
    controller.chmod(0o555)
    manifest.write_text("{}\n", encoding="utf-8")
    manifest.chmod(0o444)
    request.write_text("{}\n", encoding="utf-8")
    request.chmod(0o400)
    pin.write_text(f"{_sha256(controller)}\n", encoding="ascii")
    pin.chmod(0o444)

    source = HANDOFF.read_text(encoding="utf-8")
    path_substitutions = {
        "/usr/libexec/propertyquarry-release-control/propertyquarry-deploy-controller": controller,
        "/etc/propertyquarry/release-control/external-deploy-controller.v1.json": manifest,
        "/etc/propertyquarry/release-control/external-deploy-controller.sha256": pin,
        "/etc/propertyquarry/release-control/deploy-compose-plan.v1.json": compose_plan,
        "/etc/propertyquarry/release-control/database-fence-policy.v1.json": database_policy,
        "/etc/propertyquarry/release-control/deploy-drain-keyring.v2.json": drain_keyring,
        "/etc/propertyquarry/operator-gateway-trust.v1.json": gateway_trust,
        "/etc/propertyquarry/monitoring-topology.v1.json": monitoring_topology,
        "/etc/propertyquarry/monitoring-tools.v1.json": monitoring_tools,
    }
    for production_path, test_path in path_substitutions.items():
        assert '"' not in str(test_path)
        source = _replace_once(source, production_path, str(test_path))
    assert source.count("/var/run/docker.sock") == 2
    source = source.replace("/var/run/docker.sock", str(docker_socket_probe))
    source = _replace_once(
        source,
        "PROPERTYQUARRY_RELEASE_CONTROL_UID=0",
        f"PROPERTYQUARRY_RELEASE_CONTROL_UID={os.geteuid()}",
    )
    source = _replace_once(
        source,
        "PROPERTYQUARRY_RELEASE_CONTROL_GID=0",
        "\n".join(
            (
                f"PROPERTYQUARRY_RELEASE_CONTROL_GID={os.getegid()}",
                f'PROPERTYQUARRY_TEST_AUTHORITY_ROOT="{authority_root}"',
            )
        ),
    )
    source = _replace_once(
        source,
        '[[ "${current}" == "/" ]] && return 0',
        "[[ \"${current}\" == \"${PROPERTYQUARRY_TEST_AUTHORITY_ROOT}\" || "
        '"${current}" == "/" ]] && return 0',
    )
    script.write_text(source, encoding="utf-8")
    script.chmod(0o700)

    return HandoffSandbox(
        root=tmp_path,
        candidate_root=candidate_root,
        authority_root=authority_root,
        script=script,
        controller=controller,
        manifest=manifest,
        pin=pin,
        request=request,
        docker_socket_probe=docker_socket_probe,
        compose_plan=compose_plan,
        database_policy=database_policy,
        drain_keyring=drain_keyring,
        gateway_trust=gateway_trust,
        monitoring_topology=monitoring_topology,
        monitoring_tools=monitoring_tools,
    )


@pytest.fixture
def handoff(tmp_path: Path) -> HandoffSandbox:
    return _build_sandbox(tmp_path)


def _run_real_handoff(
    *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HANDOFF), *arguments],
        cwd=ROOT,
        env=env
        or {
            "HOME": "/nonexistent",
            "PATH": "/usr/bin:/bin",
            "EA_RUNTIME_MODE": "prod",
            "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST": "/tmp/nonexistent-propertyquarry-request",
        },
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def _argument_value(arguments: list[str], name: str) -> str:
    position = arguments.index(name)
    return arguments[position + 1]


def test_real_handoff_refuses_sourced_execution_before_any_authority_probe(
    tmp_path: Path,
) -> None:
    poison_marker = tmp_path / "bash-env-executed"
    poison = tmp_path / "bash-env"
    poison.write_text(f"/usr/bin/touch {poison_marker}\n", encoding="utf-8")
    completed = subprocess.run(
        ["/bin/bash", "-p", "-c", 'source "$1"', "handoff-source", str(HANDOFF)],
        cwd=ROOT,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "BASH_ENV": str(poison)},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 2
    assert "Refusing sourced execution of the release handoff." in completed.stderr
    assert not poison_marker.exists()


def test_real_handoff_rejects_unknown_arguments_before_any_authority_probe() -> None:
    completed = _run_real_handoff("--candidate-compose", "attacker.yml")

    assert completed.returncode == 2
    assert "Unknown argument: --candidate-compose" in completed.stderr


@pytest.mark.parametrize("runtime_mode", ["local", "production-and-test"])
def test_real_handoff_rejects_ambiguous_runtime_modes_before_privileged_checks(
    runtime_mode: str,
) -> None:
    completed = _run_real_handoff(
        env={
            "HOME": "/nonexistent",
            "PATH": "/usr/bin:/bin",
            "EA_RUNTIME_MODE": runtime_mode,
            "PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST": "/tmp/nonexistent-request",
        }
    )

    assert completed.returncode == 2
    assert "EA_RUNTIME_MODE must select production" in completed.stderr


def test_real_handoff_rejects_this_hosts_docker_capable_caller_without_using_docker() -> None:
    socket_path = Path("/var/run/docker.sock")
    if not socket_path.exists() or not stat.S_ISSOCK(socket_path.stat().st_mode):
        pytest.skip("host has no Docker socket")
    if not os.access(socket_path, os.W_OK):
        pytest.skip("test caller has no writable Docker socket")

    completed = _run_real_handoff()

    assert completed.returncode == 2
    assert "Candidate handoff must not have Docker daemon authority." in completed.stderr


def test_root_guard_branch_fails_closed_without_elevating_the_test(
    handoff: HandoffSandbox,
) -> None:
    source = handoff.script.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "if (( EUID == 0 )); then",
        f"if (( EUID == {os.geteuid()} )); then",
    )
    handoff.script.write_text(source, encoding="utf-8")
    handoff.script.chmod(0o700)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "Refusing to run candidate checkout code with release privilege." in completed.stderr


@pytest.mark.parametrize(
    ("runtime_mode", "expected_operation"),
    [("PrOdUcTiOn", "deploy-preflight"), ("test", "candidate-preflight")],
)
def test_preflight_executes_with_only_read_only_non_mutating_disposition_flags(
    handoff: HandoffSandbox,
    runtime_mode: str,
    expected_operation: str,
) -> None:
    completed = handoff.run(
        "--preflight-only",
        env=handoff.environment(EA_RUNTIME_MODE=runtime_mode),
    )

    assert completed.returncode == 0, completed.stderr
    arguments = completed.stdout.split()
    assert arguments[0] == expected_operation
    for required in (
        "--read-only",
        "--forbid-containment",
        "--forbid-state-mutation",
        "--require-explicit-preflight-disposition",
        "--require-signed-request-fd-stable-read-and-signature",
        "--forbid-caller-compose",
        "--forbid-candidate-output-authority",
    ):
        assert required in arguments
    assert "--controller-owns-all-privileged-actions" not in arguments
    assert "--contain-before-candidate-validation" not in arguments
    assert _argument_value(arguments, "--requested-runtime-mode") == runtime_mode.lower()
    assert _argument_value(arguments, "--signed-request-sha256") == _sha256(handoff.request)
    assert _argument_value(arguments, "--canonical-compose-plan") == str(handoff.compose_plan)
    assert _argument_value(arguments, "--database-fence-policy") == str(handoff.database_policy)


def test_deploy_executes_with_controller_ownership_and_containment_before_validation(
    handoff: HandoffSandbox,
) -> None:
    completed = handoff.run()

    assert completed.returncode == 0, completed.stderr
    arguments = completed.stdout.split()
    assert arguments[0] == "deploy-run"
    assert "--controller-owns-all-privileged-actions" in arguments
    assert "--contain-before-candidate-validation" in arguments
    assert "--read-only" not in arguments
    assert "--forbid-state-mutation" not in arguments


@pytest.mark.parametrize("variable", ["DOCKER_HOST", "DOCKER_CONTEXT"])
def test_rejects_caller_selected_docker_authority(
    handoff: HandoffSandbox,
    variable: str,
) -> None:
    completed = handoff.run(env=handoff.environment(**{variable: "attacker-controlled"}))

    assert completed.returncode == 2
    assert "Candidate handoff must not have Docker daemon authority." in completed.stderr


@pytest.mark.parametrize(
    "variable",
    ["DATABASE_URL", "POSTGRES_PASSWORD", "PGHOST", "PGSERVICE", "PROPERTYQUARRY_CF_TUNNEL_TOKEN"],
)
def test_rejects_database_and_traffic_credentials(
    handoff: HandoffSandbox,
    variable: str,
) -> None:
    completed = handoff.run(env=handoff.environment(**{variable: "must-not-cross"}))

    assert completed.returncode == 2
    assert "Database and traffic credentials belong only to the installed controller." in completed.stderr


@pytest.mark.parametrize("request_value", [None, "relative-request.json"])
def test_rejects_missing_or_relative_request_transport(
    handoff: HandoffSandbox,
    request_value: str | None,
) -> None:
    completed = handoff.run(
        env=handoff.environment(PROPERTYQUARRY_DEPLOY_SIGNED_REQUEST=request_value)
    )

    assert completed.returncode == 2
    assert "must be an absolute external signed-request path" in completed.stderr


def test_rejects_symlink_request_transport(handoff: HandoffSandbox) -> None:
    target = handoff.root / "request-target.json"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o400)
    handoff.request.unlink()
    handoff.request.symlink_to(target)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "Signed request transport is missing, not a regular file, or a symlink." in completed.stderr


def test_rejects_request_transport_with_wrong_mode(handoff: HandoffSandbox) -> None:
    handoff.request.chmod(0o600)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "invoking-user-owned, single-link, mode 0400" in completed.stderr


def test_rejects_multiply_linked_request_transport(handoff: HandoffSandbox) -> None:
    os.link(handoff.request, handoff.root / "request-second-link.json")

    completed = handoff.run()

    assert completed.returncode == 2
    assert "invoking-user-owned, single-link, mode 0400" in completed.stderr


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "invoking-user-owned, single-link, mode 0400"), (1048577, "must contain between 1 byte and 1 MiB")],
)
def test_rejects_empty_or_oversized_request_transport(
    handoff: HandoffSandbox,
    size: int,
    expected: str,
) -> None:
    handoff.set_request(b"x" * size)

    completed = handoff.run()

    assert completed.returncode == 2
    assert expected in completed.stderr


def test_rejects_world_writable_authority_parent(handoff: HandoffSandbox) -> None:
    handoff.controller.parent.chmod(0o777)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "Release-control parent is not authority-owned and non-writable" in completed.stderr


def test_rejects_symlink_authority_parent(handoff: HandoffSandbox) -> None:
    parent = handoff.controller.parent
    real_parent = parent.with_name("real-release-control")
    parent.rename(real_parent)
    parent.symlink_to(real_parent, target_is_directory=True)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "Release-control parent is missing, not a directory, or a symlink" in completed.stderr


def test_rejects_authority_parent_owned_by_unexpected_uid(handoff: HandoffSandbox) -> None:
    source = handoff.script.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        f"PROPERTYQUARRY_RELEASE_CONTROL_UID={os.geteuid()}",
        f"PROPERTYQUARRY_RELEASE_CONTROL_UID={os.geteuid() + 10000}",
    )
    handoff.script.write_text(source, encoding="utf-8")
    handoff.script.chmod(0o700)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "Release-control parent is not authority-owned and non-writable" in completed.stderr


@pytest.mark.parametrize(
    ("attribute", "required_mode", "label"),
    [
        ("controller", 0o755, "External deploy controller"),
        ("manifest", 0o644, "External controller manifest"),
        ("pin", 0o644, "External controller digest pin"),
    ],
)
def test_rejects_external_authority_files_with_wrong_mode(
    handoff: HandoffSandbox,
    attribute: str,
    required_mode: int,
    label: str,
) -> None:
    getattr(handoff, attribute).chmod(required_mode)

    completed = handoff.run()

    assert completed.returncode == 2
    assert f"{label} must be authority-owned, single-link" in completed.stderr


@pytest.mark.parametrize(
    ("attribute", "label"),
    [
        ("controller", "External deploy controller"),
        ("manifest", "External controller manifest"),
        ("pin", "External controller digest pin"),
    ],
)
def test_rejects_multiply_linked_external_authority_files(
    handoff: HandoffSandbox,
    attribute: str,
    label: str,
) -> None:
    os.link(getattr(handoff, attribute), handoff.root / f"{attribute}-second-link")

    completed = handoff.run()

    assert completed.returncode == 2
    assert f"{label} must be authority-owned, single-link" in completed.stderr


def test_rejects_external_file_owned_by_unexpected_authority_group(
    handoff: HandoffSandbox,
) -> None:
    other_groups = [group for group in os.getgroups() if group != os.getegid()]
    if not other_groups:
        pytest.skip("caller has no alternate supplementary group")
    os.chown(handoff.controller, -1, other_groups[0])

    completed = handoff.run()

    assert completed.returncode == 2
    assert "External deploy controller must be authority-owned, single-link" in completed.stderr


@pytest.mark.parametrize("attribute", ["controller", "manifest", "pin"])
def test_rejects_symlink_external_authority_files(
    handoff: HandoffSandbox,
    attribute: str,
) -> None:
    path = getattr(handoff, attribute)
    target = handoff.root / f"{attribute}-target"
    shutil.copyfile(path, target)
    target.chmod(path.stat().st_mode & 0o777)
    path.unlink()
    path.symlink_to(target)

    completed = handoff.run()

    assert completed.returncode == 2
    assert "missing, not a regular file, or a symlink" in completed.stderr


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"0" * 64, "must contain exactly one SHA-256 line"),
        (b"G" * 64 + b"\n", "digest pin is invalid"),
        (b"0" * 64 + b"\n1\n", "must contain exactly one SHA-256 line"),
    ],
)
def test_rejects_malformed_controller_digest_pin(
    handoff: HandoffSandbox,
    payload: bytes,
    expected: str,
) -> None:
    handoff.set_pin(payload)

    completed = handoff.run()

    assert completed.returncode == 2
    assert expected in completed.stderr
    assert "External controller digest-pin validation failed." in completed.stderr


def test_rejects_non_elf_controller_even_when_digest_pin_matches(
    handoff: HandoffSandbox,
) -> None:
    handoff.set_controller_bytes(b"#!/bin/sh\nexit 0\n")

    completed = handoff.run()

    assert completed.returncode == 2
    assert "must be a pinned native ELF entrypoint" in completed.stderr


def test_rejects_controller_that_does_not_match_digest_pin(
    handoff: HandoffSandbox,
) -> None:
    handoff.set_pin(b"0" * 64 + b"\n")

    completed = handoff.run()

    assert completed.returncode == 2
    assert "does not match its root-owned digest pin" in completed.stderr


def test_controller_receives_clean_environment_not_caller_tooling_or_secrets(
    handoff: HandoffSandbox,
) -> None:
    poison_marker = handoff.root / "bash-env-executed"
    poison = handoff.root / "poison-bash-env"
    poison.write_text(f"/usr/bin/touch {poison_marker}\n", encoding="utf-8")
    capture = handoff.candidate_root / "deploy-run"
    capture.write_text("#!/bin/bash\n/usr/bin/env\n", encoding="utf-8")
    handoff.set_controller(Path("/usr/bin/bash"))
    poisoned_values = {
        "BASH_ENV": str(poison),
        "ENV": "MUST_NOT_REACH_CONTROLLER_ENV",
        "PYTHONPATH": "MUST_NOT_REACH_CONTROLLER_PYTHONPATH",
        "PYTHONHOME": "MUST_NOT_REACH_CONTROLLER_PYTHONHOME",
        "PERL5LIB": "MUST_NOT_REACH_CONTROLLER_PERL5LIB",
        "RUBYLIB": "MUST_NOT_REACH_CONTROLLER_RUBYLIB",
        "COMPOSE_FILE": "MUST_NOT_REACH_CONTROLLER_COMPOSE",
        "EA_API_TOKEN": "MUST_NOT_REACH_CONTROLLER_TOKEN",
        "PROPERTYQUARRY_DEPLOY_PYTHON_BIN": "MUST_NOT_REACH_CONTROLLER_PYTHON_BIN",
    }

    completed = handoff.run(env=handoff.environment(**poisoned_values))

    assert completed.returncode == 0, completed.stderr
    assert "PATH=/usr/sbin:/usr/bin:/sbin:/bin" in completed.stdout
    assert "HOME=/nonexistent" in completed.stdout
    assert "LANG=C" in completed.stdout
    for value in poisoned_values.values():
        assert value not in completed.stdout
    assert not poison_marker.exists()


def test_rejects_controller_identity_swap_after_open(
    handoff: HandoffSandbox,
) -> None:
    handoff.set_controller(Path("/usr/bin/echo"), append_bytes=64 * 1024 * 1024)
    original_identity = (handoff.controller.stat().st_dev, handoff.controller.stat().st_ino)
    process = subprocess.Popen(
        [str(handoff.script)],
        cwd=handoff.candidate_root,
        env=handoff.environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    opened = False
    process_fd_root = Path(f"/proc/{process.pid}/fd")
    while process.poll() is None and time.monotonic() < deadline:
        try:
            descriptors = list(process_fd_root.iterdir())
        except FileNotFoundError:
            break
        for descriptor in descriptors:
            try:
                identity = (descriptor.stat().st_dev, descriptor.stat().st_ino)
            except FileNotFoundError:
                continue
            if identity == original_identity:
                opened = True
                break
        if opened:
            break
        time.sleep(0.001)

    if not opened:
        process.kill()
        process.communicate(timeout=5)
        pytest.fail("did not observe the controller's stable open file descriptor")

    replacement = handoff.root / "replacement-controller"
    shutil.copyfile("/usr/bin/echo", replacement)
    replacement.chmod(0o555)
    os.replace(replacement, handoff.controller)
    stdout, stderr = process.communicate(timeout=15)

    assert process.returncode == 2, stdout
    assert (
        "External handoff file changed while it was opened" in stderr
        or "External handoff identity changed after hashing" in stderr
    )
