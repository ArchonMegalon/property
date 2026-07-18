from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ea import property_web_elf_validator as audit


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["/usr/bin/ldd", "/fixture"],
        returncode,
        stdout,
        stderr,
    )


def test_property_web_elf_audit_ignores_non_elf_and_deduplicates_hardlinks(
    tmp_path: Path,
) -> None:
    elf = tmp_path / "runtime.so"
    alias = tmp_path / "runtime-hardlink.so"
    text = tmp_path / "notes.txt"
    elf.write_bytes(b"\x7fELFfixture")
    alias.hardlink_to(elf)
    text.write_text("not an executable", encoding="utf-8")

    assert list(audit.iter_elf_paths([tmp_path])) == [alias]


def test_property_web_elf_audit_checks_extension_roots_not_private_wheel_members(
    tmp_path: Path,
) -> None:
    extension = tmp_path / "package" / "extension.so"
    private = tmp_path / "package.libs" / "private.so"
    extension.parent.mkdir()
    private.parent.mkdir()
    extension.write_bytes(b"\x7fELFextension")
    private.write_bytes(b"\x7fELFprivate")

    assert list(audit.iter_elf_paths([tmp_path])) == [extension]


def test_property_web_elf_audit_accepts_resolved_and_static_objects(
    tmp_path: Path,
) -> None:
    dynamic = tmp_path / "dynamic.so"
    static = tmp_path / "static"
    dynamic.write_bytes(b"\x7fELFdynamic")
    static.write_bytes(b"\x7fELFstatic")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1].endswith("dynamic.so"):
            return _completed(0, "libc.so.6 => /usr/lib/libc.so.6")
        return _completed(1, stderr="not a dynamic executable")

    checked, failures = audit.audit_elf_closure([tmp_path], run=run)

    assert checked == 2
    assert failures == []


def test_property_web_elf_audit_rejects_missing_library(
    tmp_path: Path,
) -> None:
    elf = tmp_path / "broken.so"
    elf.write_bytes(b"\x7fELFbroken")

    checked, failures = audit.audit_elf_closure(
        [tmp_path],
        run=lambda *_args, **_kwargs: _completed(
            0,
            "libuuid.so.1 => not found",
        ),
    )

    assert checked == 1
    assert failures == [
        {
            "path": str(elf),
            "returncode": 0,
            "output": "libuuid.so.1 => not found",
        }
    ]


def test_property_web_elf_audit_rejects_unexpected_ldd_failure(
    tmp_path: Path,
) -> None:
    elf = tmp_path / "invalid.so"
    elf.write_bytes(b"\x7fELFinvalid")

    checked, failures = audit.audit_elf_closure(
        [tmp_path],
        run=lambda *_args, **_kwargs: _completed(126, stderr="loader refused"),
    )

    assert checked == 1
    assert failures[0]["returncode"] == 126
    assert failures[0]["output"] == "loader refused"


def test_property_web_elf_audit_main_rejects_an_empty_audit(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(audit, "audit_elf_closure", lambda _roots: (0, []))

    assert audit.main([]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checked"] == 0
    assert report["failures"] == []
    assert report["status"] == "fail"
