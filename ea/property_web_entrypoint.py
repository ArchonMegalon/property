from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import NoReturn


EXPECTED_UID = 10001
EXPECTED_GID = 10001
SAFE_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
_ALLOWED_IDENTITY_ENV = {
    "EA_RUN_AS_UID": EXPECTED_UID,
    "EA_RUN_AS_GID": EXPECTED_GID,
}


def _fail(message: str, code: int = 126) -> NoReturn:
    print(f"property-web-entrypoint: {message}", file=sys.stderr)
    raise SystemExit(code)


def _capability_value(name: str) -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                key, separator, value = line.partition(":")
                if separator and key == name:
                    return int(value.strip(), 16)
    except (OSError, ValueError) as error:
        _fail(f"cannot verify {name}: {error}")
    _fail(f"{name} missing from /proc/self/status")


def _validate_requested_identity() -> None:
    for variable, expected in _ALLOWED_IDENTITY_ENV.items():
        supplied = os.environ.get(variable, "")
        if supplied not in ("", str(expected)):
            _fail(f"{variable} must be unset or {expected}")


def _drop_forced_root() -> None:
    if os.geteuid() != 0:
        return
    try:
        os.setgroups([])
        os.setresgid(EXPECTED_GID, EXPECTED_GID, EXPECTED_GID)
        os.setresuid(EXPECTED_UID, EXPECTED_UID, EXPECTED_UID)
    except OSError as error:
        _fail(f"fixed-identity privilege drop failed: {error}")


def _verify_final_identity() -> None:
    uid_tuple = os.getresuid()
    gid_tuple = os.getresgid()
    if uid_tuple != (EXPECTED_UID,) * 3:
        _fail(f"unexpected uid tuple {uid_tuple!r}")
    if gid_tuple != (EXPECTED_GID,) * 3:
        _fail(f"unexpected gid tuple {gid_tuple!r}")
    unexpected_groups = sorted(set(os.getgroups()) - {EXPECTED_GID})
    if unexpected_groups:
        _fail(f"unexpected supplementary groups {unexpected_groups!r}")
    for field in ("CapPrm", "CapEff", "CapInh", "CapAmb"):
        if _capability_value(field) != 0:
            _fail(f"{field} remains after identity validation")


def main(argv: Sequence[str] | None = None) -> NoReturn:
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        _fail("no command supplied", 64)

    _validate_requested_identity()
    _drop_forced_root()
    _verify_final_identity()

    os.environ["HOME"] = "/home/ea"
    os.environ["USER"] = "ea"
    os.environ["LOGNAME"] = "ea"
    os.environ["PATH"] = SAFE_PATH
    for variable in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
    ):
        os.environ.pop(variable, None)
    os.umask(0o027)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
