"""Validate the ELF dependency closure shipped in the render runtime."""

from __future__ import annotations

import json
import os
import stat
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
    Path("/ms-playwright"),
    Path("/app"),
)
_SAFE_ENV = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
}
_NON_DYNAMIC_MARKERS = ("not a dynamic executable", "statically linked")


def _audit_environment(path: Path) -> dict[str, str]:
    environment = dict(_SAFE_ENV)
    if any(part.endswith(".libs") for part in path.parts):
        # Audit every wheel-private object, including libraries that are only
        # normally loaded through an extension module whose RPATH names this
        # sibling directory.  An explicit, single-directory loader scope gives
        # standalone ldd the same closed dependency set without inheriting any
        # host-controlled LD_* values.
        environment["LD_LIBRARY_PATH"] = str(path.parent.resolve(strict=True))
    return environment


def iter_elf_paths(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[tuple[int, int]] = set()
    for root in roots:
        try:
            root_metadata = root.stat()
        except OSError as error:
            raise RuntimeError(
                f"required ELF audit root is unavailable {root}: {error}"
            ) from error
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise RuntimeError(f"required ELF audit root is not a directory: {root}")

        def raise_walk_error(error: OSError) -> None:
            raise RuntimeError(f"cannot traverse retained root {root}: {error}") from error

        for directory, child_directories, filenames in os.walk(
            root,
            followlinks=False,
            onerror=raise_walk_error,
        ):
            child_directories.sort()
            for filename in sorted(filenames):
                path = Path(directory, filename)
                try:
                    metadata = path.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(path, flags)
                    try:
                        opened_metadata = os.fstat(descriptor)
                        if not stat.S_ISREG(opened_metadata.st_mode):
                            raise RuntimeError(
                                f"retained path changed type while inspecting {path}"
                            )
                        identity = (opened_metadata.st_dev, opened_metadata.st_ino)
                        if identity != (metadata.st_dev, metadata.st_ino):
                            raise RuntimeError(
                                f"retained path changed identity while inspecting {path}"
                            )
                        if identity in seen:
                            continue
                        seen.add(identity)
                        magic = os.read(descriptor, len(_ELF_MAGIC))
                    finally:
                        os.close(descriptor)
                    if magic == _ELF_MAGIC:
                        # Wheel-private .libs objects are deliberately included.  The
                        # audit supplies their closed sibling directory as the loader
                        # scope so standalone ldd can validate transitive wheel members.
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
            env=_audit_environment(path),
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
        print("property-render ELF audit accepts no arguments", file=sys.stderr)
        return 64
    if not Path("/usr/bin/ldd").is_file():
        print("property-render ELF audit requires /usr/bin/ldd", file=sys.stderr)
        return 1
    try:
        checked, failures = audit_elf_closure(_DEFAULT_ROOTS)
    except Exception as error:
        print(f"property-render ELF audit failed: {error}", file=sys.stderr)
        return 1
    empty_audit = checked == 0
    print(
        json.dumps(
            {
                "schema": "propertyquarry.render_elf_audit.v1",
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
