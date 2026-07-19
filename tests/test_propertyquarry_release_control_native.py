from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import socket
import stat
import subprocess

import pytest

from scripts import propertyquarry_release_local_container_gate as container_gate


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "propertyquarry-release-control-v2"
PACKAGE = ROOT / "packaging" / "propertyquarry-release-control-v2"
EXPECTED_TOOLCHAIN_SHA256 = (
    "5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053"
)
COMPONENTS = (
    "propertyquarry-release-controller-v2",
    "propertyquarry-release-supervisor-v2",
    "propertyquarry-release-watchdog-v2",
)
SCRATCH_EXECUTION = {
    "contract": "linux-amd64-static-et-exec-v1",
    "elf_class": "ELF64",
    "elf_data": "little-endian",
    "elf_machine": "Advanced Micro Devices X86-64",
    "elf_type": "ET_EXEC",
    "statically_linked": True,
    "pt_interp_absent": True,
    "dynamic_section_absent": True,
    "dt_needed_absent": True,
    "non_executable_stack": True,
    "writable_executable_load_segments_absent": True,
    "file_gate_passed": True,
    "readelf_gate_passed": True,
}
NATIVE_SOURCE_FILES = (
    "go.mod",
    "toolchain.lock.json",
    "Makefile",
    "tools/build.sh",
    "tools/repro-build.sh",
    "tools/source-files.txt",
    "tools/stage-verify.sh",
    "tools/verify-static-elf.sh",
    "internal/releasecontrol/releasecontrol.go",
    "internal/releasecontrol/releasecontrol_test.go",
    "internal/releasecontrol/installed_authority_linux.go",
    "internal/releasecontrol/installed_authority_linux_test.go",
    "internal/releasecontrol/installed_runtime_linux.go",
    "internal/releasecontrol/installed_tree_linux.go",
    "internal/releasecontrol/quarantine_request.go",
    "internal/releasecontrol/quarantine_request_test.go",
    "internal/releasecontrol/quarantine_transport_linux.go",
    "internal/releasecontrol/quarantine_transport_linux_test.go",
    "cmd/propertyquarry-release-controller-v2/main.go",
    "cmd/propertyquarry-release-supervisor-v2/main.go",
    "cmd/propertyquarry-release-watchdog-v2/main.go",
)
PACKAGE_TEMPLATE_FILES = (
    "schema/controller-v2.schema.json",
    "schema/watchdog-v2.schema.json",
    "systemd/propertyquarry-release-control-v2.socket",
    "systemd/propertyquarry-release-control-v2@.service",
    "systemd/propertyquarry-release-watchdog-v2.service",
    "sysusers.d/propertyquarry-release-control-v2.conf",
    "tmpfiles.d/propertyquarry-release-control-v2.conf",
)


def _go_binary() -> str:
    value = os.environ.get("PROPERTYQUARRY_NATIVE_GO")
    if not value:
        pytest.skip(
            "set PROPERTYQUARRY_NATIVE_GO to the checksum-verified Go 1.26.5 binary"
        )
    return value


def _go_archive() -> str:
    value = os.environ.get("PROPERTYQUARRY_GO_ARCHIVE")
    if not value:
        pytest.skip(
            "set PROPERTYQUARRY_GO_ARCHIVE to the checksum-verified Go 1.26.5 archive"
        )
    return value


def _build_environment() -> dict[str, str]:
    return {
        **os.environ,
        "PROPERTYQUARRY_NATIVE_GO": _go_binary(),
        "PROPERTYQUARRY_GO_ARCHIVE": _go_archive(),
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOWORK": "off",
        "CGO_ENABLED": "0",
    }


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_manifest_digest() -> str:
    framed = bytearray()
    for relative in (NATIVE / "tools" / "source-files.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        framed.extend(_sha256(NATIVE / relative).removeprefix("sha256:").encode())
        framed.extend(b"  ")
        framed.extend(relative.encode())
        framed.extend(b"\n")
    return "sha256:" + hashlib.sha256(framed).hexdigest()


@pytest.fixture(scope="session")
def native_binaries(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("propertyquarry-native-binaries")
    subprocess.run(
        [str(NATIVE / "tools" / "build.sh"), str(output)],
        cwd=ROOT,
        env=_build_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert {path.name for path in output.iterdir()} == set(COMPONENTS)
    assert all(stat.S_IMODE((output / name).stat().st_mode) == 0o755 for name in COMPONENTS)
    return output


@pytest.fixture(scope="session")
def reproducible_native_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("propertyquarry-native-repro")
    hostile_environment = {
        **_build_environment(),
        "GOCACHEPROG": "/definitely/not/a/cache-helper",
        "GOEXPERIMENT": "this_must_not_leak",
        "GO_EXTLINK_ENABLED": "1",
        "GOFIPS140": "latest",
        "GOFLAGS": "-race",
        "GO_LDSO": "/definitely/not/a/loader",
        "PYTHONHOME": "/definitely/not/a/python-home",
        "PYTHONPATH": "/definitely/not/a/python-path",
        "TAR_OPTIONS": "--help",
    }
    result = subprocess.run(
        [str(NATIVE / "tools" / "repro-build.sh"), str(output)],
        cwd=ROOT,
        env=hostile_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(output / "build-receipt.json")
    return output


def test_native_toolchain_and_module_are_closed_and_pinned() -> None:
    lock = json.loads((NATIVE / "toolchain.lock.json").read_text(encoding="utf-8"))
    assert lock == {
        "arch": "amd64",
        "archive_bytes": 66879095,
        "archive_sha256": EXPECTED_TOOLCHAIN_SHA256,
        "archive_url": "https://go.dev/dl/go1.26.5.linux-amd64.tar.gz",
        "distribution": "go.dev official binary archive",
        "go_binary_sha256": (
            "8da5fd321795754b994c64e3eb8a5a14ff47bd285559a7e876f3c79abafc67f9"
        ),
        "os": "linux",
        "schema": "propertyquarry.release-control.toolchain-lock.v2",
        "version": "go1.26.5",
    }
    assert (NATIVE / "go.mod").read_text(encoding="utf-8") == (
        "module propertyquarry.local/release-control-v2\n\ngo 1.26.0\n"
    )
    assert not (NATIVE / "go.sum").exists()
    assert not (NATIVE / "vendor").exists()


def test_native_source_stays_outside_exact_seven_file_package_template() -> None:
    expected = set(PACKAGE_TEMPLATE_FILES)
    actual = {
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    for relative in expected:
        path = PACKAGE / relative
        assert not path.is_symlink()
        assert stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
    assert NATIVE.is_dir()
    for relative in NATIVE_SOURCE_FILES:
        path = NATIVE / relative
        assert path.is_file()
        assert not path.is_symlink()
        expected_mode = 0o755 if relative.startswith("tools/") and relative.endswith(".sh") else 0o644
        assert stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) == expected_mode


def test_build_contract_is_offline_reproducible_and_has_no_candidate_path() -> None:
    build = (NATIVE / "tools" / "build.sh").read_text(encoding="utf-8")
    stage_verify = (NATIVE / "tools" / "stage-verify.sh").read_text(
        encoding="utf-8"
    )
    makefile = (NATIVE / "Makefile").read_text(encoding="utf-8")
    for exact in (
        "CGO_ENABLED=0",
        "GOARCH=amd64",
        "GOAMD64=v1",
        "GOFIPS140=off",
        "GOOS=linux",
        "GOPROXY=off",
        "GOSUMDB=off",
        "GOTOOLCHAIN=local",
        "GOWORK=off",
        "-mod=readonly",
        "-trimpath",
        "-buildvcs=false",
        "-buildmode=exe",
        "-buildid=",
        "-linkmode=internal",
        "SCRATCH_EXECUTION_CONTRACT=linux-amd64-static-et-exec-v1",
        "ScratchExecutionContract=$SCRATCH_EXECUTION_CONTRACT",
        "verify-static-elf.sh",
    ):
        assert exact in build
    assert "../../build/propertyquarry-release-control-v2/linux-amd64" in makefile
    assert "stage-verify: repro" in makefile
    assert "env -i" in build
    assert "tar --extract" in build
    assert "PROPERTYQUARRY_NATIVE_GO" not in build
    assert "--build-info-json" not in stage_verify
    assert "import subprocess" not in stage_verify
    assert "subprocess.run" not in stage_verify
    all_source = "\n".join(
        (NATIVE / relative).read_text(encoding="utf-8")
        for relative in NATIVE_SOURCE_FILES
    )
    for forbidden in ("/docker/property", "GITHUB_WORKSPACE", "net/http"):
        assert forbidden not in all_source


def test_native_effect_claim_is_release_scoped_and_local_lifecycle_is_explicit() -> None:
    metadata_contracts = (
        NATIVE / "internal" / "releasecontrol" / "releasecontrol.go",
        NATIVE / "tools" / "repro-build.sh",
        ROOT / "scripts" / "propertyquarry_release_local_container_gate.py",
    )
    for path in metadata_contracts:
        contract = path.read_text(encoding="utf-8")
        assert '"performs_effects"' not in contract
        assert "performs_release_effects" in contract

    documentation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "docs" / "PROPERTYQUARRY_RELEASE_NATIVE_BUILD_V2.md",
            ROOT / "docs" / "PROPERTYQUARRY_RELEASE_LOCAL_OCI_V2.md",
        )
    )
    assert "performs no effects" not in documentation
    for required in (
        "performs_release_effects",
        "local Unix socket",
        "pinned inert controller",
        "SIGUSR2",
        "not a release effect",
    ):
        assert required in documentation


def test_go_unit_suite_passes_offline() -> None:
    subprocess.run(
        [_go_binary(), "test", "-mod=readonly", "./..."],
        cwd=NATIVE,
        env=_build_environment(),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("component", COMPONENTS)
def test_build_info_and_self_test_are_explicitly_non_authoritative(
    native_binaries: Path, component: str
) -> None:
    binary = native_binaries / component
    for mode, self_test in (("--build-info-json", False), ("--self-test", True)):
        result = subprocess.run(
            [str(binary), mode],
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0
        assert result.stderr == b""
        assert result.stdout.isascii()
        assert result.stdout.endswith(b"\n")
        assert result.stdout.count(b"\n") == 1
        expected_payload = {
            "schema": "propertyquarry.release-control.native-build-info.v2",
            "version": 2,
            "component": component,
            "toolchain": "go1.26.5",
            "source_manifest_digest": _source_manifest_digest(),
            "scratch_execution_contract": SCRATCH_EXECUTION["contract"],
            "authoritative": False,
            "production_ready": False,
            "performs_release_effects": False,
            "self_test": self_test,
        }
        expected = (
            json.dumps(
                expected_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
        assert result.stdout == expected
        assert json.loads(result.stdout.decode("ascii")) == expected_payload


@pytest.mark.parametrize("component", COMPONENTS)
def test_actual_go_self_test_bytes_pass_strict_python_container_gate(
    native_binaries: Path, component: str
) -> None:
    result = subprocess.run(
        [str(native_binaries / component), "--self-test"],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.isascii()
    assert result.stdout.endswith(b"\n")
    assert result.stdout.count(b"\n") == 1
    parsed = container_gate._parse_build_info(
        result.stdout,
        component=component,
        toolchain="go1.26.5",
        source_manifest_digest=_source_manifest_digest(),
    )
    assert result.stdout == (
        json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


@pytest.mark.parametrize("component", COMPONENTS)
def test_native_binary_is_loaderless_scratch_elf(
    native_binaries: Path, component: str
) -> None:
    binary = native_binaries / component
    gate = subprocess.run(
        [str(NATIVE / "tools" / "verify-static-elf.sh"), str(binary)],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
    )
    assert gate.stdout == "static-elf-ok\n"
    assert gate.stderr == ""

    file_output = subprocess.run(
        ["/usr/bin/file", "-b", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        env={"LANG": "C", "LC_ALL": "C"},
    ).stdout
    assert "ELF 64-bit LSB executable, x86-64" in file_output
    assert "statically linked" in file_output
    assert "dynamically linked" not in file_output
    assert "interpreter " not in file_output
    assert "pie executable" not in file_output

    header = subprocess.run(
        ["/usr/bin/readelf", "--wide", "--file-header", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        env={"LANG": "C", "LC_ALL": "C"},
    ).stdout
    program_headers = subprocess.run(
        ["/usr/bin/readelf", "--wide", "--program-headers", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        env={"LANG": "C", "LC_ALL": "C"},
    ).stdout
    dynamic = subprocess.run(
        ["/usr/bin/readelf", "--wide", "--dynamic", str(binary)],
        check=True,
        capture_output=True,
        text=True,
        env={"LANG": "C", "LC_ALL": "C"},
    ).stdout
    assert re.search(r"Type:\s+EXEC \(Executable file\)", header)
    assert "Advanced Micro Devices X86-64" in header
    assert "INTERP" not in program_headers
    assert "There is no dynamic section in this file." in dynamic
    assert "NEEDED" not in dynamic


def test_watchdog_operational_mode_never_claims_ready(
    native_binaries: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "notify.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(str(marker))
    listener.settimeout(0.1)
    try:
        result = subprocess.run(
            [
                str(native_binaries / "propertyquarry-release-watchdog-v2"),
                "--config",
                "/etc/propertyquarry-release-control/watchdog-v2.json",
            ],
            cwd=tmp_path,
            env={
                "HOME": str(tmp_path / "home"),
                "TMPDIR": str(tmp_path / "tmp"),
                "NOTIFY_SOCKET": str(marker),
            },
            check=False,
            capture_output=True,
            text=True,
        )
        with pytest.raises(socket.timeout):
            listener.recv(4096)
    finally:
        listener.close()
    assert result.returncode == 50
    assert result.stdout == ""
    assert result.stderr == ""
    assert {path.name for path in tmp_path.iterdir()} == {"notify.sock"}


@pytest.mark.parametrize(
    ("component", "mode"),
    (
        ("propertyquarry-release-supervisor-v2", "--docker-broker"),
        ("propertyquarry-release-supervisor-v2", "--request-smoke"),
        ("propertyquarry-release-supervisor-v2", "--docker-restart-stimulus"),
        ("propertyquarry-release-watchdog-v2", "--health-json"),
        ("propertyquarry-release-watchdog-v2", "--docker-watchdog"),
    ),
)
def test_installed_local_authority_modes_fail_silent_without_installed_inputs(
    native_binaries: Path,
    tmp_path: Path,
    component: str,
    mode: str,
) -> None:
    result = subprocess.run(
        [
            str(native_binaries / component),
            "--installed-local-authority",
            mode,
        ],
        cwd=tmp_path,
        env={},
        check=False,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""
    assert list(tmp_path.iterdir()) == []


def _run_supervisor_with_bearer(binary: Path, bearer: bytes) -> subprocess.CompletedProcess[bytes]:
    read_fd, write_fd = os.pipe()
    def install_fd9() -> None:
        os.dup2(read_fd, 9)

    try:
        process = subprocess.Popen(
            [str(binary), "release-preflight"],
            env={**os.environ, "PROPERTYQUARRY_OIDC_TOKEN_FD": "9"},
            pass_fds=(read_fd,),
            preexec_fn=install_fd9,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.close(read_fd)
        read_fd = -1
        view = memoryview(bearer)
        while view:
            try:
                written = os.write(write_fd, view)
            except BrokenPipeError:
                break
            view = view[written:]
        os.close(write_fd)
        write_fd = -1
        stdout, stderr = process.communicate(timeout=10)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.parametrize(
    "bearer",
    (
        b"valid-token\n",
        b"valid-token\n\n",
        b"valid-token\r\n",
        b"x" * 16_385 + b"\n",
    ),
)
def test_supervisor_client_consumes_fd9_and_always_fails_closed(
    native_binaries: Path, bearer: bytes
) -> None:
    result = _run_supervisor_with_bearer(
        native_binaries / "propertyquarry-release-supervisor-v2", bearer
    )
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize("token_fd", (None, "8"))
def test_supervisor_rejects_missing_fd9_without_state_mutation(
    native_binaries: Path, tmp_path: Path, token_fd: str | None
) -> None:
    environment = {
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
    }
    if token_fd is not None:
        environment["PROPERTYQUARRY_OIDC_TOKEN_FD"] = token_fd
    result = subprocess.run(
        [
            str(native_binaries / "propertyquarry-release-supervisor-v2"),
            "release-preflight",
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
    )
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""
    assert list(tmp_path.iterdir()) == []


def test_broker_rejects_non_unix_fd0(native_binaries: Path) -> None:
    result = subprocess.run(
        [
            str(native_binaries / "propertyquarry-release-supervisor-v2"),
            "--server-broker",
            "--config",
            "/etc/propertyquarry-release-control/controller-v2.json",
            "--socket-activation",
        ],
        input=b"",
        check=False,
        capture_output=True,
    )
    assert result.returncode == 50
    assert result.stdout == b""


def test_broker_accepts_only_connected_unix_stream_then_refuses(
    native_binaries: Path, tmp_path: Path
) -> None:
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        result = subprocess.run(
            [
                str(native_binaries / "propertyquarry-release-supervisor-v2"),
                "--server-broker",
                "--config",
                "/etc/propertyquarry-release-control/controller-v2.json",
                "--socket-activation",
            ],
            stdin=child,
            cwd=tmp_path,
            env={
                "HOME": str(tmp_path / "home"),
                "TMPDIR": str(tmp_path / "tmp"),
            },
            check=False,
            capture_output=True,
        )
    finally:
        parent.close()
        child.close()
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""
    assert list(tmp_path.iterdir()) == []


def test_broker_rejects_connected_tcp_fd0(native_binaries: Path) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname(), timeout=2)
    server, _ = listener.accept()
    try:
        result = subprocess.run(
            [
                str(native_binaries / "propertyquarry-release-supervisor-v2"),
                "--server-broker",
                "--config",
                "/etc/propertyquarry-release-control/controller-v2.json",
                "--socket-activation",
            ],
            stdin=server,
            check=False,
            capture_output=True,
        )
    finally:
        server.close()
        client.close()
        listener.close()
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize(
    "operation", ("release-preflight", "release-run", "reconcile-run")
)
def test_controller_closes_response_pipe_without_a_frame(
    native_binaries: Path, tmp_path: Path, operation: str
) -> None:
    read_fd, write_fd = os.pipe()
    try:
        result = subprocess.run(
            [
                str(native_binaries / "propertyquarry-release-controller-v2"),
                "--config",
                "/etc/propertyquarry-release-control/controller-v2.json",
                "--operation",
                operation,
                "--response-fd",
                str(write_fd),
                "--event-id",
                "event-1",
                "--request-transport-digest",
                "sha256:" + "a" * 64,
            ],
            pass_fds=(write_fd,),
            cwd=tmp_path,
            env={
                "HOME": str(tmp_path / "home"),
                "TMPDIR": str(tmp_path / "tmp"),
            },
            check=False,
            capture_output=True,
        )
    finally:
        os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 1)
        assert ready == [read_fd]
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)
    assert result.returncode == 50
    assert result.stdout == b""
    assert result.stderr == b""
    assert list(tmp_path.iterdir()) == []


def test_controller_response_pipe_cannot_be_contaminated_by_stderr_alias(
    native_binaries: Path,
) -> None:
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(
            [
                str(native_binaries / "propertyquarry-release-controller-v2"),
                "--config",
                "/etc/propertyquarry-release-control/controller-v2.json",
                "--operation",
                "release-run",
                "--response-fd",
                str(write_fd),
                "--event-id",
                "event-1",
                "--request-transport-digest",
                "sha256:" + "a" * 64,
            ],
            pass_fds=(write_fd,),
            stdout=subprocess.PIPE,
            stderr=write_fd,
        )
        assert process.wait(timeout=5) == 50
    finally:
        os.close(write_fd)
    try:
        assert os.read(read_fd, 4096) == b""
    finally:
        os.close(read_fd)


def test_broker_socket_cannot_be_contaminated_by_stderr_alias(
    native_binaries: Path,
) -> None:
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    parent.settimeout(1)
    try:
        process = subprocess.Popen(
            [
                str(native_binaries / "propertyquarry-release-supervisor-v2"),
                "--server-broker",
                "--config",
                "/etc/propertyquarry-release-control/controller-v2.json",
                "--socket-activation",
            ],
            stdin=child,
            stdout=subprocess.PIPE,
            stderr=child,
        )
        child.close()
        assert process.wait(timeout=5) == 50
        assert parent.recv(4096) == b""
    finally:
        parent.close()
        child.close()


def test_double_build_is_byte_identical_and_receipt_is_non_authoritative(
    reproducible_native_bundle: Path,
) -> None:
    output = reproducible_native_bundle
    receipt = json.loads((output / "build-receipt.json").read_text(encoding="utf-8"))
    assert set(receipt) == {
        "schema",
        "authoritative",
        "production_ready",
        "reproducible_double_build",
        "distinct_absolute_source_roots",
        "isolated_build_caches",
        "independent_toolchain_extractions",
        "go_subprocess_environment_allowlisted",
        "go_subprocess_inherited_environment_cleared",
        "module_network_resolution_disabled",
        "host_network_namespace_isolated",
        "go_tests_passed_in_both_builds",
        "scratch_execution",
        "source_manifest_reverified_after_build",
        "receipt_published_last",
        "root_install_performed",
        "package_signature_verified",
        "builder_identity_authenticated",
        "toolchain",
        "toolchain_archive_bytes",
        "toolchain_archive_sha256",
        "go_binary_sha256",
        "source_manifest_sha256",
        "build_flags",
        "ldflags",
        "build_environment",
        "binary_mode",
        "binary_sizes",
        "binaries",
    }
    assert receipt["schema"] == "propertyquarry.release-control.native-build-receipt.v2"
    assert receipt["authoritative"] is False
    assert receipt["production_ready"] is False
    assert receipt["reproducible_double_build"] is True
    assert receipt["distinct_absolute_source_roots"] is True
    assert receipt["isolated_build_caches"] is True
    assert receipt["independent_toolchain_extractions"] is True
    assert receipt["go_subprocess_environment_allowlisted"] is True
    assert receipt["go_subprocess_inherited_environment_cleared"] is True
    assert receipt["module_network_resolution_disabled"] is True
    assert receipt["host_network_namespace_isolated"] is False
    assert receipt["go_tests_passed_in_both_builds"] is True
    assert receipt["scratch_execution"] == SCRATCH_EXECUTION
    assert receipt["source_manifest_reverified_after_build"] is True
    assert receipt["receipt_published_last"] is True
    assert receipt["root_install_performed"] is False
    assert receipt["package_signature_verified"] is False
    assert receipt["builder_identity_authenticated"] is False
    assert receipt["toolchain"] == "go1.26.5 linux/amd64"
    assert receipt["toolchain_archive_bytes"] == 66_879_095
    assert receipt["toolchain_archive_sha256"] == EXPECTED_TOOLCHAIN_SHA256
    assert receipt["go_binary_sha256"] == (
        "sha256:8da5fd321795754b994c64e3eb8a5a14ff47bd285559a7e876f3c79abafc67f9"
    )
    assert receipt["source_manifest_sha256"] == _source_manifest_digest()
    assert receipt["build_flags"] == [
        "-mod=readonly",
        "-trimpath",
        "-buildvcs=false",
        "-buildmode=exe",
    ]
    assert receipt["ldflags"] == (
        "-buildid= -linkmode=internal -X propertyquarry.local/"
        "release-control-v2/internal/"
        "releasecontrol.SourceManifestDigest="
        + _source_manifest_digest()
        + " -X propertyquarry.local/release-control-v2/internal/"
        "releasecontrol.ScratchExecutionContract="
        + SCRATCH_EXECUTION["contract"]
    )
    assert receipt["build_environment"] == {
        "CGO_ENABLED": "0",
        "GO111MODULE": "on",
        "GOARCH": "amd64",
        "GOAMD64": "v1",
        "GOENV": "off",
        "GOEXPERIMENT": "",
        "GOFIPS140": "off",
        "GOFLAGS": "",
        "GOOS": "linux",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOTELEMETRY": "off",
        "GOTOOLCHAIN": "local",
        "GOWORK": "off",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    assert receipt["binary_mode"] == "0755"
    assert receipt["binary_sizes"] == {
        name: (output / name).stat().st_size for name in COMPONENTS
    }
    assert receipt["binaries"] == {name: _sha256(output / name) for name in COMPONENTS}
    assert stat.S_IMODE((output / "build-receipt.json").stat().st_mode) == 0o644
    assert all(stat.S_IMODE((output / name).stat().st_mode) == 0o755 for name in COMPONENTS)

    for name in COMPONENTS:
        result = subprocess.run(
            [str(output / name), "--build-info-json"],
            check=True,
            capture_output=True,
            text=True,
            env={},
        )
        assert result.stderr == ""
        assert json.loads(result.stdout)["source_manifest_digest"] == receipt[
            "source_manifest_sha256"
        ]


def test_staged_systemd_units_resolve_all_three_native_binaries(
    reproducible_native_bundle: Path, tmp_path: Path
) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is required for staged unit verification")
    stage = tmp_path / "root"
    result = subprocess.run(
        [
            str(NATIVE / "tools" / "stage-verify.sh"),
            str(reproducible_native_bundle),
            str(stage),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(stage / "staged-unit-receipt.json")
    receipt = json.loads(
        (stage / "staged-unit-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["schema"] == (
        "propertyquarry.release-control.staged-unit-verification.v2"
    )
    for key in (
        "authoritative",
        "production_ready",
        "root_install_performed",
        "package_signature_verified",
    ):
        assert receipt[key] is False
    for key in (
        "static_unit_compatibility",
        "package_template_exact_seven",
        "placeholder_targets_used",
    ):
        assert receipt[key] is True
    assert re.fullmatch(r"systemd [0-9]+", receipt["systemd_analyze_version"])
    assert receipt["build_receipt_sha256"] == _sha256(
        reproducible_native_bundle / "build-receipt.json"
    )
    assert receipt["binaries"] == {
        name: _sha256(reproducible_native_bundle / name) for name in COMPONENTS
    }
    assert receipt["package_templates"] == {
        relative: _sha256(PACKAGE / relative) for relative in PACKAGE_TEMPLATE_FILES
    }


def test_stage_rejects_malformed_or_symlinked_build_receipt_before_writing(
    reproducible_native_bundle: Path, tmp_path: Path
) -> None:
    for variant in ("malformed", "unbound", "symlink"):
        bundle = tmp_path / f"bundle-{variant}"
        shutil.copytree(reproducible_native_bundle, bundle)
        receipt = bundle / "build-receipt.json"
        if variant == "malformed":
            receipt.write_text("not-json\n", encoding="utf-8")
        elif variant == "unbound":
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["binaries"][COMPONENTS[0]] = "sha256:" + "0" * 64
            receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        else:
            receipt.unlink()
            receipt.symlink_to(reproducible_native_bundle / "build-receipt.json")
        stage = tmp_path / f"stage-{variant}"
        result = subprocess.run(
            [str(NATIVE / "tools" / "stage-verify.sh"), str(bundle), str(stage)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert result.stdout == ""
        assert not stage.exists()


def test_stage_never_executes_forgeable_input_bundle_binaries(
    reproducible_native_bundle: Path, tmp_path: Path
) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is required for staged unit verification")
    bundle = tmp_path / "hostile-bundle"
    shutil.copytree(reproducible_native_bundle, bundle)
    marker = tmp_path / "input-binary-was-executed"
    hostile = (
        "#!/bin/sh\n"
        f": > {shlex.quote(str(marker))}\n"
        "exit 91\n"
    )
    for name in COMPONENTS:
        binary = bundle / name
        binary.write_text(hostile, encoding="utf-8")
        binary.chmod(0o755)

    receipt_path = bundle / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["binary_sizes"] = {
        name: (bundle / name).stat().st_size for name in COMPONENTS
    }
    receipt["binaries"] = {name: _sha256(bundle / name) for name in COMPONENTS}
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    stage = tmp_path / "hostile-stage"
    result = subprocess.run(
        [str(NATIVE / "tools" / "stage-verify.sh"), str(bundle), str(stage)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert not marker.exists()
    assert not stage.exists()
