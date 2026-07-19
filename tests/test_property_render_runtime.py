from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path

import pytest

from ea import property_render_elf_validator as elf_audit
from ea import property_render_entrypoint as entrypoint
from ea import property_render_ffmpeg_validator as ffmpeg_audit


def test_render_ffmpeg_audit_is_pure_stdlib_with_stable_public_api() -> None:
    source = Path(ffmpeg_audit.__file__).read_text(encoding="utf-8")
    signature = inspect.signature(ffmpeg_audit.audit_ffmpeg_encoder)

    assert "from scripts" not in source
    assert "from ea" not in source
    assert list(signature.parameters) == ["runner", "require_bounded_surface"]
    assert (
        signature.parameters["require_bounded_surface"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )
    assert callable(ffmpeg_audit.capture_local_tool)
    assert callable(ffmpeg_audit.capture_container_tool)


def test_render_ffmpeg_registry_parsers_ignore_legends_and_parse_ffmpeg_8() -> None:
    codecs = """Decoders:\n V..... = Video\n V....D rawvideo raw video\n"""
    filters = """Filters:\n T.. = Timeline support\n .. format V->V (null)\n TS hflip V->V (null)\n"""

    assert ffmpeg_audit._ffmpeg_codec_registry_names(codecs) == {"rawvideo"}
    assert ffmpeg_audit._ffmpeg_filter_registry_names(filters) == {
        "format",
        "hflip",
    }


def test_render_ffmpeg_buildconf_parser_ignores_exit_diagnostic() -> None:
    output = """configuration:\n --prefix=/opt/ffmpeg --enable-static\nExiting with exit code 0\n"""

    assert ffmpeg_audit._ffmpeg_configure_tokens(output) == frozenset(
        {"--prefix=/opt/ffmpeg", "--enable-static"}
    )


def test_render_ffmpeg_audit_accepts_shipped_no_reproducibility_claim() -> None:
    provenance_path = Path(ffmpeg_audit.__file__).with_name(
        "property_render_media_provenance.json"
    )
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    ffmpeg = payload["ffmpeg"]
    build_receipts = payload["build_receipts"]
    checks = ffmpeg_audit._provenance_checks(
        {
            "available": True,
            "payload": payload,
            "observed": {
                "ffmpeg_path": "/usr/local/bin/ffmpeg",
                "ffmpeg_binary_sha256": ffmpeg["binary_sha256"],
                "ffmpeg_binary_size": ffmpeg["binary_size"],
                "build_receipts": {
                    name: {
                        "path": binding["path"],
                        "sha256": binding["sha256"],
                    }
                    for name, binding in build_receipts.items()
                },
            },
        },
        configure_tokens=ffmpeg_audit.FFMPEG_REQUIRED_CONFIGURE_FLAGS,
        registries={
            name: set(values)
            for name, values in ffmpeg["registries"].items()
        },
    )

    assert "reproducible_builds_observed" not in payload["glib"]
    assert checks["glib_build_contract_exact"] is True
    assert all(checks.values())

    payload["glib"]["reproducible_builds_observed"] = 3
    unsupported_checks = ffmpeg_audit._provenance_checks(
        {
            "available": True,
            "payload": payload,
            "observed": {
                "ffmpeg_path": "/usr/local/bin/ffmpeg",
                "ffmpeg_binary_sha256": ffmpeg["binary_sha256"],
                "ffmpeg_binary_size": ffmpeg["binary_size"],
                "build_receipts": {
                    name: {
                        "path": binding["path"],
                        "sha256": binding["sha256"],
                    }
                    for name, binding in build_receipts.items()
                },
            },
        },
        configure_tokens=ffmpeg_audit.FFMPEG_REQUIRED_CONFIGURE_FLAGS,
        registries={
            name: set(values)
            for name, values in ffmpeg["registries"].items()
        },
    )

    assert unsupported_checks["glib_build_contract_exact"] is False


def test_render_entrypoint_rejects_requested_identity_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RUN_AS_UID", "10002")

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["true"])


def test_render_entrypoint_drops_forced_root_to_fixed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint.os, "setgroups", lambda groups: calls.append(("groups", groups)))
    monkeypatch.setattr(
        entrypoint.os,
        "setresgid",
        lambda real, effective, saved: calls.append(("gid", real, effective, saved)),
    )
    monkeypatch.setattr(
        entrypoint.os,
        "setresuid",
        lambda real, effective, saved: calls.append(("uid", real, effective, saved)),
    )

    entrypoint._drop_forced_root()

    assert calls == [
        ("groups", []),
        ("gid", 10001, 10001, 10001),
        ("uid", 10001, 10001, 10001),
    ]


def test_render_entrypoint_sanitizes_environment_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExecObserved(RuntimeError):
        pass

    observed: dict[str, object] = {}
    monkeypatch.delenv("EA_RUN_AS_UID", raising=False)
    monkeypatch.delenv("EA_RUN_AS_GID", raising=False)
    monkeypatch.delenv("EA_ROLE", raising=False)
    monkeypatch.setenv("PYTHONPATH", "/attacker")
    monkeypatch.setenv("LD_PRELOAD", "/attacker/preload.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/attacker/libraries")
    monkeypatch.setenv("LD_ARBITRARY_FUTURE_CONTROL", "enabled")
    monkeypatch.setenv("GLIBC_TUNABLES", "glibc.rtld.nns=99")
    monkeypatch.setenv("GCONV_PATH", "/attacker/gconv")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/attacker/preload.js")
    monkeypatch.setenv("NODE_PATH", "/attacker/node-modules")
    monkeypatch.setenv("NODE_ARBITRARY_FUTURE_CONTROL", "enabled")
    monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", "/attacker/node")
    monkeypatch.setenv("_PLAYWRIGHT_DRIVER_CLI_PATH", "/attacker/cli.js")
    monkeypatch.setenv(
        "_PLAYWRIGHT_DRIVER_EXECUTABLE_PATH", "/attacker/driver"
    )
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/attacker/browsers")
    monkeypatch.setattr(entrypoint, "_drop_forced_root", lambda: None)
    monkeypatch.setattr(entrypoint, "_verify_final_identity", lambda: None)

    def fake_preflight() -> None:
        observed["preflight"] = True
        observed["preflight_environment"] = dict(os.environ)

    monkeypatch.setattr(entrypoint, "_run_runtime_preflight", fake_preflight)
    monkeypatch.setattr(entrypoint.os, "umask", lambda mask: observed.setdefault("umask", mask))

    def fake_execvp(command: str, argv: list[str]) -> None:
        observed["command"] = command
        observed["argv"] = argv
        observed["environment"] = dict(os.environ)
        raise ExecObserved

    monkeypatch.setattr(entrypoint.os, "execvp", fake_execvp)

    with pytest.raises(ExecObserved):
        entrypoint.main(["/usr/local/bin/python", "-m", "app.runner"])

    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert observed["command"] == "/usr/local/bin/python"
    assert observed["argv"] == ["/usr/local/bin/python", "-m", "app.runner"]
    assert observed["umask"] == 0o027
    assert observed["preflight"] is True
    assert environment["HOME"] == "/home/ea"
    assert environment["PATH"] == entrypoint.SAFE_PATH
    assert "PYTHONPATH" not in environment
    preflight_environment = observed["preflight_environment"]
    assert isinstance(preflight_environment, dict)
    for sanitized_environment in (preflight_environment, environment):
        assert "GLIBC_TUNABLES" not in sanitized_environment
        assert "GCONV_PATH" not in sanitized_environment
        assert not any(name.startswith("LD_") for name in sanitized_environment)
        assert not any(name.startswith("NODE_") for name in sanitized_environment)
        assert "PLAYWRIGHT_NODEJS_PATH" not in sanitized_environment
        assert "_PLAYWRIGHT_DRIVER_CLI_PATH" not in sanitized_environment
        assert "_PLAYWRIGHT_DRIVER_EXECUTABLE_PATH" not in sanitized_environment
        assert (
            sanitized_environment["PLAYWRIGHT_BROWSERS_PATH"]
            == entrypoint.PLAYWRIGHT_BROWSERS_PATH
        )


@pytest.mark.parametrize(
    ("status_values", "expected_message"),
    (
        (
            {
                "CapBnd": 1,
                "CapPrm": 0,
                "CapEff": 0,
                "CapInh": 0,
                "CapAmb": 0,
                "NoNewPrivs": 1,
            },
            "CapBnd remains",
        ),
        (
            {
                "CapBnd": 0,
                "CapPrm": 0,
                "CapEff": 0,
                "CapInh": 0,
                "CapAmb": 0,
                "NoNewPrivs": 0,
            },
            "NoNewPrivs is not enforced",
        ),
    ),
)
def test_render_entrypoint_rejects_incomplete_kernel_confinement(
    monkeypatch: pytest.MonkeyPatch,
    status_values: dict[str, int],
    expected_message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(entrypoint.os, "getresuid", lambda: (10001, 10001, 10001))
    monkeypatch.setattr(entrypoint.os, "getresgid", lambda: (10001, 10001, 10001))
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: [])
    monkeypatch.setattr(
        entrypoint,
        "_capability_value",
        lambda name: status_values[name],
    )

    with pytest.raises(SystemExit, match="126"):
        entrypoint._verify_final_identity()

    assert expected_message in capsys.readouterr().err


def test_render_entrypoint_runs_render_preflight_with_isolated_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setenv("EA_ROLE", "render-tools")
    monkeypatch.setenv(
        "PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN", "operator-secret"
    )
    monkeypatch.setenv("NODE_OPTIONS", "--require=/attacker/preload.js")
    monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", "/attacker/node")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/attacker/browsers")

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[object]:
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, returncode=0)

    entrypoint._run_runtime_preflight(run=run)

    assert observed["argv"] == list(entrypoint.RUNTIME_PREFLIGHT_COMMAND)
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["check"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["timeout"] == entrypoint.RUNTIME_PREFLIGHT_TIMEOUT_SECONDS
    assert kwargs["env"] == entrypoint._runtime_preflight_environment()
    preflight_environment = kwargs["env"]
    assert isinstance(preflight_environment, dict)
    assert "PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN" not in preflight_environment
    assert "NODE_OPTIONS" not in preflight_environment
    assert "PLAYWRIGHT_NODEJS_PATH" not in preflight_environment
    assert (
        preflight_environment["PLAYWRIGHT_BROWSERS_PATH"]
        == entrypoint.PLAYWRIGHT_BROWSERS_PATH
    )


def test_render_entrypoint_preflight_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EA_ROLE", "render-tools")

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[object]:
        return subprocess.CompletedProcess(argv, returncode=23)

    with pytest.raises(SystemExit, match="126"):
        entrypoint._run_runtime_preflight(run=run)

    assert "runtime preflight failed with exit 23" in capsys.readouterr().err


@pytest.mark.parametrize("role", (None, "api", "render-tools"))
def test_render_entrypoint_runs_preflight_for_every_role(
    monkeypatch: pytest.MonkeyPatch,
    role: str | None,
) -> None:
    calls: list[list[str]] = []
    if role is None:
        monkeypatch.delenv("EA_ROLE", raising=False)
    else:
        monkeypatch.setenv("EA_ROLE", role)

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[object]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode=0)

    entrypoint._run_runtime_preflight(run=run)

    assert calls == [list(entrypoint.RUNTIME_PREFLIGHT_COMMAND)]


def test_render_elf_audit_skips_symlinks_but_includes_wheel_private_libraries(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "tool"
    executable.parent.mkdir()
    executable.write_bytes(b"\x7fELFpayload")
    (tmp_path / "bin" / "tool-link").symlink_to(executable)
    private_library = tmp_path / "wheel.libs" / "libprivate.so"
    private_library.parent.mkdir()
    private_library.write_bytes(b"\x7fELFpayload")

    assert list(elf_audit.iter_elf_paths((tmp_path,))) == [
        executable,
        private_library,
    ]


def test_render_elf_audit_checks_wheel_private_library_with_its_own_rpath_context(
    tmp_path: Path,
) -> None:
    extension = tmp_path / "package" / "extension.so"
    extension.parent.mkdir()
    extension.write_bytes(b"\x7fELFpayload")
    private_library = tmp_path / "package.libs" / "libprivate.so"
    private_library.parent.mkdir()
    private_library.write_bytes(b"\x7fELFpayload")
    audited: list[tuple[Path, dict[str, str]]] = []

    def resolved(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        audited.append((Path(argv[-1]), environment))
        return subprocess.CompletedProcess(
            argv,
            returncode=0,
            stdout="libc.so.6 => /usr/lib/libc.so.6",
            stderr="",
        )

    checked, failures = elf_audit.audit_elf_closure((tmp_path,), run=resolved)

    assert checked == 2
    assert failures == []
    assert audited[0] == (extension, elf_audit._SAFE_ENV)
    assert audited[1][0] == private_library
    assert audited[1][1] == {
        **elf_audit._SAFE_ENV,
        "LD_LIBRARY_PATH": str(private_library.parent.resolve()),
    }


def test_render_elf_audit_fails_when_required_root_is_missing(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(RuntimeError, match="required ELF audit root is unavailable"):
        list(elf_audit.iter_elf_paths((missing,)))


def test_render_elf_audit_propagates_walk_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = PermissionError("walk denied")

    def failed_walk(
        _root: Path,
        *,
        followlinks: bool,
        onerror: object,
    ) -> list[object]:
        assert followlinks is False
        assert callable(onerror)
        onerror(denied)
        return []

    monkeypatch.setattr(elf_audit.os, "walk", failed_walk)

    with pytest.raises(RuntimeError, match="cannot traverse retained root"):
        list(elf_audit.iter_elf_paths((tmp_path,)))


def test_render_elf_audit_reports_unresolved_dependency(tmp_path: Path) -> None:
    executable = tmp_path / "tool"
    executable.write_bytes(b"\x7fELFpayload")

    def unresolved(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            returncode=0,
            stdout="libmissing.so => not found\n",
            stderr="",
        )

    checked, failures = elf_audit.audit_elf_closure((tmp_path,), run=unresolved)

    assert checked == 1
    assert failures == [
        {
            "path": str(executable),
            "returncode": 0,
            "output": "libmissing.so => not found",
        }
    ]
