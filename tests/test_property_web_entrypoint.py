from __future__ import annotations

import io
import os
from collections.abc import Callable

import pytest

from ea import property_web_entrypoint as entrypoint


class _ExecCalled(Exception):
    pass


@pytest.fixture(autouse=True)
def _restore_entrypoint_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "EA_RUN_AS_UID",
        "EA_RUN_AS_GID",
    ):
        monkeypatch.setenv(variable, os.environ.get(variable, ""))
    monkeypatch.delenv("EA_RUN_AS_UID")
    monkeypatch.delenv("EA_RUN_AS_GID")


def _patch_valid_nonroot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    uid: int = entrypoint.EXPECTED_UID,
    gid: int = entrypoint.EXPECTED_GID,
    groups: list[int] | None = None,
    capability: Callable[[str], int] | None = None,
) -> None:
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: uid)
    monkeypatch.setattr(entrypoint.os, "getresuid", lambda: (uid, uid, uid))
    monkeypatch.setattr(entrypoint.os, "getresgid", lambda: (gid, gid, gid))
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: list(groups or []))
    monkeypatch.setattr(entrypoint, "_capability_value", capability or (lambda _name: 0))
    monkeypatch.setattr(entrypoint.os, "umask", lambda _mask: 0)


def _reject_exec(_executable: str, _argv: list[str]) -> None:
    raise AssertionError("entrypoint must fail before exec")


def test_property_web_entrypoint_preserves_nonroot_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_nonroot(monkeypatch)
    observed: list[object] = []

    def fake_execvp(executable: str, argv: list[str]) -> None:
        observed.extend((executable, argv.copy()))
        raise _ExecCalled

    monkeypatch.setattr(entrypoint.os, "execvp", fake_execvp)
    monkeypatch.setenv("HOME", "/tmp/untrusted-home")
    monkeypatch.setenv("USER", "untrusted-user")
    monkeypatch.setenv("LOGNAME", "untrusted-logname")

    with pytest.raises(_ExecCalled):
        entrypoint.main(["python", "-m", "app.runner", "--once"])

    assert observed == ["python", ["python", "-m", "app.runner", "--once"]]
    assert entrypoint.os.environ["HOME"] == "/home/ea"
    assert entrypoint.os.environ["USER"] == "ea"
    assert entrypoint.os.environ["LOGNAME"] == "ea"
    assert entrypoint.os.environ["PATH"] == entrypoint.SAFE_PATH
    for variable in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
    ):
        assert variable not in entrypoint.os.environ


def test_property_web_entrypoint_drops_forced_root_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {
        "uids": (0, 0, 0),
        "gids": (0, 0, 0),
        "groups": [0],
    }
    events: list[object] = []

    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: state["uids"][1])
    monkeypatch.setattr(entrypoint.os, "getresuid", lambda: state["uids"])
    monkeypatch.setattr(entrypoint.os, "getresgid", lambda: state["gids"])
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: list(state["groups"]))

    def setgroups(groups: list[int]) -> None:
        events.append(("setgroups", groups.copy()))
        state["groups"] = groups.copy()

    def setresgid(real: int, effective: int, saved: int) -> None:
        events.append(("setresgid", real, effective, saved))
        state["gids"] = (real, effective, saved)

    def setresuid(real: int, effective: int, saved: int) -> None:
        events.append(("setresuid", real, effective, saved))
        state["uids"] = (real, effective, saved)

    def capability(name: str) -> int:
        events.append(("capability", name))
        return 0

    def fake_execvp(executable: str, argv: list[str]) -> None:
        events.append(("execvp", executable, argv.copy()))
        raise _ExecCalled

    monkeypatch.setattr(entrypoint.os, "setgroups", setgroups)
    monkeypatch.setattr(entrypoint.os, "setresgid", setresgid)
    monkeypatch.setattr(entrypoint.os, "setresuid", setresuid)
    monkeypatch.setattr(entrypoint, "_capability_value", capability)
    monkeypatch.setattr(
        entrypoint.os,
        "umask",
        lambda mask: events.append(("umask", mask)) or 0,
    )
    monkeypatch.setattr(entrypoint.os, "execvp", fake_execvp)

    with pytest.raises(_ExecCalled):
        entrypoint.main(["python", "-m", "app.runner"])

    assert events[:3] == [
        ("setgroups", []),
        ("setresgid", 10001, 10001, 10001),
        ("setresuid", 10001, 10001, 10001),
    ]
    assert events[3:] == [
        ("capability", "CapPrm"),
        ("capability", "CapEff"),
        ("capability", "CapInh"),
        ("capability", "CapAmb"),
        ("umask", 0o027),
        ("execvp", "python", ["python", "-m", "app.runner"]),
    ]


@pytest.mark.parametrize("failing_call", ["setgroups", "setresgid", "setresuid"])
def test_property_web_entrypoint_aborts_when_a_drop_syscall_fails(
    monkeypatch: pytest.MonkeyPatch,
    failing_call: str,
) -> None:
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)

    def drop_call(*_args: object) -> None:
        if failing_call == "setgroups":
            raise OSError("setgroups denied")

    def gid_call(*_args: object) -> None:
        if failing_call == "setresgid":
            raise OSError("setresgid denied")

    def uid_call(*_args: object) -> None:
        if failing_call == "setresuid":
            raise OSError("setresuid denied")

    monkeypatch.setattr(entrypoint.os, "setgroups", drop_call)
    monkeypatch.setattr(entrypoint.os, "setresgid", gid_call)
    monkeypatch.setattr(entrypoint.os, "setresuid", uid_call)
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


@pytest.mark.parametrize(
    ("variable", "value"),
    [("EA_RUN_AS_UID", "10002"), ("EA_RUN_AS_GID", "10002")],
)
def test_property_web_entrypoint_rejects_dynamic_identity(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    monkeypatch.delenv("EA_RUN_AS_UID", raising=False)
    monkeypatch.delenv("EA_RUN_AS_GID", raising=False)
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


@pytest.mark.parametrize(
    ("uid", "gid"),
    [(10002, entrypoint.EXPECTED_GID), (entrypoint.EXPECTED_UID, 10002)],
)
def test_property_web_entrypoint_rejects_wrong_nonroot_identity(
    monkeypatch: pytest.MonkeyPatch,
    uid: int,
    gid: int,
) -> None:
    _patch_valid_nonroot(monkeypatch, uid=uid, gid=gid)
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


def test_property_web_entrypoint_rejects_root_supplementary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_nonroot(monkeypatch, groups=[0, entrypoint.EXPECTED_GID])
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


def test_property_web_entrypoint_rejects_unexpected_nonroot_supplementary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_nonroot(monkeypatch, groups=[entrypoint.EXPECTED_GID, 999])
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


@pytest.mark.parametrize(
    "remaining_capability",
    ["CapPrm", "CapEff", "CapInh", "CapAmb"],
)
def test_property_web_entrypoint_rejects_remaining_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    remaining_capability: str,
) -> None:
    _patch_valid_nonroot(
        monkeypatch,
        capability=lambda name: int(name == remaining_capability),
    )
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


def test_property_web_entrypoint_rejects_successful_noop_root_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint.os, "setgroups", lambda _groups: None)
    monkeypatch.setattr(entrypoint.os, "setresgid", lambda *_ids: None)
    monkeypatch.setattr(entrypoint.os, "setresuid", lambda *_ids: None)
    monkeypatch.setattr(entrypoint.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(entrypoint.os, "getresgid", lambda: (0, 0, 0))
    monkeypatch.setattr(entrypoint.os, "getgroups", lambda: [])
    monkeypatch.setattr(entrypoint.os, "execvp", _reject_exec)

    with pytest.raises(SystemExit, match="126"):
        entrypoint.main(["python", "-m", "app.runner"])


def test_property_web_entrypoint_allows_exact_fixed_identity_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_valid_nonroot(monkeypatch)
    monkeypatch.setenv("EA_RUN_AS_UID", str(entrypoint.EXPECTED_UID))
    monkeypatch.setenv("EA_RUN_AS_GID", str(entrypoint.EXPECTED_GID))
    monkeypatch.setattr(
        entrypoint.os,
        "execvp",
        lambda _executable, _argv: (_ for _ in ()).throw(_ExecCalled),
    )

    with pytest.raises(_ExecCalled):
        entrypoint.main(["python", "-m", "app.runner"])


@pytest.mark.parametrize("status", ["Name:\tpython\n", "CapEff:\tnot-hex\n"])
def test_property_web_entrypoint_rejects_missing_or_malformed_capability_status(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: io.StringIO(status))

    with pytest.raises(SystemExit, match="126"):
        entrypoint._capability_value("CapEff")


def test_property_web_entrypoint_rejects_empty_command() -> None:
    with pytest.raises(SystemExit, match="64"):
        entrypoint.main([])
