from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


SCHEMA = "propertyquarry.playwright_browser_inventory.v1"
PLAYWRIGHT_PACKAGE_VERSION = "1.60.0"
CHROMIUM_REVISION = "1223"
CHROMIUM_VERSION = "148.0.7778.96"
EXPECTED_ROOTS = ("chromium-1223", "chromium_headless_shell-1223")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raise_walk_error(error: OSError) -> None:
    raise error


def build_inventory(root: Path) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    entries: list[dict[str, object]] = []
    for name in EXPECTED_ROOTS:
        browser_root = resolved_root / name
        metadata = browser_root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or browser_root.is_symlink():
            raise RuntimeError(f"browser root is not a directory: {name}")
        initial_entry_count = len(entries)
        for directory, child_directories, filenames in os.walk(
            browser_root,
            followlinks=False,
            onerror=_raise_walk_error,
        ):
            child_directories.sort()
            filenames.sort()
            directory_path = Path(directory)
            retained_directories: list[str] = []
            for child_name in child_directories:
                child = directory_path / child_name
                child_metadata = child.lstat()
                relative = child.relative_to(resolved_root).as_posix()
                if stat.S_ISLNK(child_metadata.st_mode):
                    entries.append(
                        {
                            "kind": "symlink",
                            "path": relative,
                            "target": os.readlink(child),
                        }
                    )
                elif stat.S_ISDIR(child_metadata.st_mode):
                    retained_directories.append(child_name)
                else:
                    raise RuntimeError(f"unsupported browser entry: {relative}")
            child_directories[:] = retained_directories
            for filename in filenames:
                path = directory_path / filename
                metadata = path.lstat()
                relative = path.relative_to(resolved_root).as_posix()
                if stat.S_ISLNK(metadata.st_mode):
                    entries.append(
                        {
                            "kind": "symlink",
                            "path": relative,
                            "target": os.readlink(path),
                        }
                    )
                elif stat.S_ISREG(metadata.st_mode):
                    entries.append(
                        {
                            "kind": "file",
                            "path": relative,
                            "sha256": _sha256(path),
                            "size": metadata.st_size,
                        }
                    )
                else:
                    raise RuntimeError(f"unsupported browser entry: {relative}")
        if len(entries) == initial_entry_count:
            raise RuntimeError(f"browser root is empty: {name}")
    return {
        "schema": SCHEMA,
        "version": 1,
        "playwright_package_version": PLAYWRIGHT_PACKAGE_VERSION,
        "chromium_revision": CHROMIUM_REVISION,
        "chromium_version": CHROMIUM_VERSION,
        "roots": list(EXPECTED_ROOTS),
        "entries": sorted(entries, key=lambda item: str(item["path"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_inventory(args.root)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o444)
    os.replace(temporary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
