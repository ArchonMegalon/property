#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

_3DVISTA_EXPORT_MARKERS = ("tdvplayer", "tdvplayerapi", "tourviewer")
_TEXT_RUNTIME_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".json", ".xml"}
_MAX_MARKER_SCAN_BYTES = 1_000_000
_MAX_MARKER_SCAN_FILES = 240


def _public_tour_dir() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours").expanduser().resolve()


def _safe_relpath(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return "/".join(parts)


def _find_entry(export_dir: Path, explicit_entry: str = "") -> Path:
    if explicit_entry:
        candidate = (export_dir / _safe_relpath(explicit_entry)).resolve()
        if export_dir in candidate.parents and candidate.is_file():
            return candidate
        raise SystemExit(f"3dvista_entry_not_found:{explicit_entry}")
    preferred = (
        "index.html",
        "index.htm",
        "tour.html",
        "virtualtour.html",
    )
    for name in preferred:
        candidate = export_dir / name
        if candidate.is_file():
            return candidate.resolve()
    matches = sorted(export_dir.rglob("*.html")) + sorted(export_dir.rglob("*.htm"))
    if not matches:
        raise SystemExit("3dvista_export_entry_missing")
    return matches[0].resolve()


def _text_asset_has_markers(path: Path, markers: tuple[str, ...]) -> bool:
    if path.suffix.lower() not in _TEXT_RUNTIME_SUFFIXES:
        return False
    try:
        if path.stat().st_size > _MAX_MARKER_SCAN_BYTES:
            return False
        body = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in body for marker in markers)


def _entry_has_3dvista_markers(export_dir: Path, entry: Path) -> bool:
    export_root = export_dir.resolve()
    candidates = [entry.resolve()]
    for candidate in sorted(export_root.rglob("*")):
        if len(candidates) >= _MAX_MARKER_SCAN_FILES:
            break
        if candidate.is_file() and candidate.suffix.lower() in _TEXT_RUNTIME_SUFFIXES and candidate.resolve() not in candidates:
            candidates.append(candidate.resolve())
    for candidate in candidates:
        if export_root not in candidate.parents and candidate != export_root:
            continue
        if _text_asset_has_markers(candidate, _3DVISTA_EXPORT_MARKERS):
            return True
    return False


def _copy_export(export_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in export_dir.iterdir():
        target = target_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a 3DVista VT Pro export into a PropertyQuarry public tour bundle.")
    parser.add_argument("--slug", required=True, help="Existing PropertyQuarry public tour slug.")
    parser.add_argument("--export-dir", required=True, help="Directory exported by 3DVista VT Pro.")
    parser.add_argument("--entry", default="", help="Optional entry HTML path relative to export-dir.")
    parser.add_argument("--target-subdir", default="3dvista", help="Subdirectory inside the tour bundle.")
    args = parser.parse_args()

    slug = _safe_relpath(args.slug)
    if "/" in slug or not slug:
        raise SystemExit("invalid_tour_slug")
    export_dir = Path(args.export_dir).expanduser().resolve()
    if not export_dir.is_dir():
        raise SystemExit("3dvista_export_dir_missing")
    entry = _find_entry(export_dir, args.entry)
    if not _entry_has_3dvista_markers(export_dir, entry):
        raise SystemExit("3dvista_export_entry_unverified")

    bundle_dir = _public_tour_dir() / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise SystemExit("tour_manifest_missing")
    target_subdir = _safe_relpath(args.target_subdir or "3dvista") or "3dvista"
    target_dir = (bundle_dir / target_subdir).resolve()
    if bundle_dir.resolve() not in target_dir.parents:
        raise SystemExit("invalid_3dvista_target")

    _copy_export(export_dir, target_dir)
    entry_rel_to_export = entry.relative_to(export_dir).as_posix()
    entry_relpath = f"{target_subdir}/{entry_rel_to_export}"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["control_mode"] = "3dvista"
    payload["viewer_provider"] = "3dvista_vt_pro"
    payload["three_d_vista_entry_relpath"] = entry_relpath
    payload["three_d_vista_import"] = {
        "source": "3dvista_vt_pro_export",
        "entry_relpath": entry_relpath,
        "target_subdir": target_subdir,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "imported",
                "slug": slug,
                "entry_relpath": entry_relpath,
                "control_url": f"/tours/{slug}/control/3dvista",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
