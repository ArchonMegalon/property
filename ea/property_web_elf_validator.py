"""Validate the ELF dependency closure shipped in the web runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path


_ELF_MAGIC = b"\x7fELF"
_DEFAULT_ROOTS = (
    Path("/bin"),
    Path("/sbin"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/usr/lib"),
    Path("/usr/local/bin"),
    Path("/usr/local/lib"),
    Path("/app"),
)
_SAFE_ENV = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
}
_NON_DYNAMIC_MARKERS = ("not a dynamic executable", "statically linked")


def iter_elf_paths(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[tuple[int, int]] = set()
    for root in roots:
        if not root.exists():
            continue
        for directory, child_directories, filenames in os.walk(root, followlinks=False):
            child_directories.sort()
            for filename in sorted(filenames):
                path = Path(directory, filename)
                try:
                    metadata = path.stat(follow_symlinks=False)
                    identity = (metadata.st_dev, metadata.st_ino)
                    # Audit wheel-private libraries through their extension load root;
                    # standalone ldd loses the extension's $ORIGIN/RPATH context.
                    private_wheel_dependency = any(
                        part.endswith(".libs") for part in path.parts
                    )
                    if (
                        not path.is_file()
                        or path.is_symlink()
                        or identity in seen
                        or private_wheel_dependency
                    ):
                        continue
                    seen.add(identity)
                    with path.open("rb") as handle:
                        if handle.read(len(_ELF_MAGIC)) == _ELF_MAGIC:
                            yield path
                except OSError as error:
                    raise RuntimeError(f"cannot inspect retained path {path}: {error}") from error


def audit_elf_closure(
    roots: Iterable[Path],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, list[dict[str, object]]]:
    checked = 0
    failures: list[dict[str, object]] = []
    for path in iter_elf_paths(roots):
        checked += 1
        completed = run(
            ["/usr/bin/ldd", str(path)],
            check=False,
            capture_output=True,
            env=_SAFE_ENV,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        normalized = output.lower()
        missing = "not found" in normalized
        unexpected_failure = completed.returncode != 0 and not any(
            marker in normalized for marker in _NON_DYNAMIC_MARKERS
        )
        if missing or unexpected_failure:
            failures.append(
                {
                    "path": str(path),
                    "returncode": completed.returncode,
                    "output": output,
                }
            )
    return checked, failures


def main(argv: Sequence[str] | None = None) -> int:
    if list(sys.argv[1:] if argv is None else argv):
        print("property-web ELF audit accepts no arguments", file=sys.stderr)
        return 64
    if not Path("/usr/bin/ldd").is_file():
        print("property-web ELF audit requires /usr/bin/ldd", file=sys.stderr)
        return 1
    try:
        checked, failures = audit_elf_closure(_DEFAULT_ROOTS)
    except Exception as error:
        print(f"property-web ELF audit failed: {error}", file=sys.stderr)
        return 1
    empty_audit = checked == 0
    print(
        json.dumps(
            {
                "schema": "propertyquarry.web_elf_audit.v1",
                "status": "fail" if empty_audit or failures else "pass",
                "checked": checked,
                "failures": failures,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return int(empty_audit or bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
