#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROVIDERS = ("3dvista", "pano2vr")
MARKERS_BY_PROVIDER = {
    "3dvista": ("tdvplayer", "tdvplayerapi", "tourviewer"),
    "pano2vr": ("ggpkg", "ggskin", "pano.xml", "tour.js"),
}
ENTRY_NAMES = ("index.html", "index.htm", "tour.html", "virtualtour.html", "output/index.html")
TEXT_RUNTIME_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".json", ".xml"}
MAX_MARKER_SCAN_BYTES = 1_000_000
MAX_MARKER_SCAN_FILES = 240


def _default_drop_dir() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR") or "/data/property_tour_export_drop").expanduser()


def _artifact_dir() -> Path:
    return Path(os.getenv("EA_ARTIFACT_DIR") or "/data/artifacts").expanduser()


def _safe_slug(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw or "/" in raw or raw in {".", ".."} or ".." in raw:
        return ""
    return raw


def _provider_from_text(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "").replace("-", "")
    if normalized in {"3dvista", "threedvista", "threevista"}:
        return "3dvista"
    if normalized in {"pano2vr", "pano2v"}:
        return "pano2vr"
    return ""


def _entry_candidates(export_dir: Path) -> Iterable[Path]:
    for name in ENTRY_NAMES:
        candidate = export_dir / name
        if candidate.is_file():
            yield candidate
    yield from sorted(export_dir.rglob("*.html"))
    yield from sorted(export_dir.rglob("*.htm"))


def _text_asset_has_markers(path: Path, markers: tuple[str, ...]) -> bool:
    if path.suffix.lower() not in TEXT_RUNTIME_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_MARKER_SCAN_BYTES:
            return False
        body = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in body for marker in markers)


def _export_has_provider_markers(export_dir: Path, entry: Path, markers: tuple[str, ...]) -> bool:
    export_root = export_dir.resolve()
    candidates = [entry.resolve()]
    for candidate in sorted(export_root.rglob("*")):
        if len(candidates) >= MAX_MARKER_SCAN_FILES:
            break
        resolved = candidate.resolve()
        if candidate.is_file() and candidate.suffix.lower() in TEXT_RUNTIME_SUFFIXES and resolved not in candidates:
            candidates.append(resolved)
    for candidate in candidates:
        if export_root not in candidate.parents and candidate != export_root:
            continue
        if _text_asset_has_markers(candidate, markers):
            return True
    return False


def _verified_entry(export_dir: Path, provider: str) -> tuple[Path | None, str]:
    markers = MARKERS_BY_PROVIDER[provider]
    seen: set[Path] = set()
    for entry in _entry_candidates(export_dir):
        resolved = entry.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if export_dir.resolve() not in resolved.parents:
            continue
        if _export_has_provider_markers(export_dir, resolved, markers):
            return resolved, resolved.relative_to(export_dir.resolve()).as_posix()
    return None, ""


def _candidate_layouts(drop_dir: Path) -> list[tuple[str, str, Path]]:
    rows: list[tuple[str, str, Path]] = []
    if not drop_dir.is_dir():
        return rows
    for slug_dir in sorted(path for path in drop_dir.iterdir() if path.is_dir()):
        slug = _safe_slug(slug_dir.name)
        if not slug:
            continue
        for provider in PROVIDERS:
            provider_dir = slug_dir / provider
            if provider_dir.is_dir():
                rows.append((slug, provider, provider_dir.resolve()))
    for provider_dir in sorted(path for path in drop_dir.iterdir() if path.is_dir()):
        provider = _provider_from_text(provider_dir.name)
        if not provider:
            continue
        for slug_dir in sorted(path for path in provider_dir.iterdir() if path.is_dir()):
            slug = _safe_slug(slug_dir.name)
            if slug:
                rows.append((slug, provider, slug_dir.resolve()))
    deduped: dict[tuple[str, str, str], tuple[str, str, Path]] = {}
    for slug, provider, export_dir in rows:
        deduped[(slug, provider, str(export_dir))] = (slug, provider, export_dir)
    return list(deduped.values())


def build_discovery_receipt(*, drop_dir: Path, public_tour_dir: Path | None = None) -> dict[str, Any]:
    public_root = (public_tour_dir or Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours")).expanduser()
    imports: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for slug, provider, export_dir in _candidate_layouts(drop_dir.expanduser()):
        manifest_path = public_root / slug / "tour.json"
        if not manifest_path.is_file():
            rejected.append({"slug": slug, "provider": provider, "reason": "tour_manifest_missing"})
            continue
        entry, entry_relpath = _verified_entry(export_dir, provider)
        if entry is None:
            rejected.append({"slug": slug, "provider": provider, "reason": f"{provider}_export_entry_unverified"})
            continue
        imports.append(
            {
                "slug": slug,
                "provider": provider,
                "export_dir": str(export_dir),
                "entry": entry_relpath,
            }
        )
    status = "ready" if imports else "blocked_no_verified_exports"
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "drop_dir": str(drop_dir.expanduser()),
        "public_tour_dir": str(public_root),
        "import_count": len(imports),
        "rejected_count": len(rejected),
        "imports": imports,
        "rejected": rejected,
        "import_manifest": {"imports": imports},
        "notes": [
            "This discovery step does not publish tours. It only emits rows accepted by the hardened import_property_tour_exports.py importer.",
            "3DVista and Pano2VR placeholders are rejected unless the entry or bundled local runtime files contain provider markers.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover verified 3DVista/Pano2VR export folders and emit an import manifest.")
    parser.add_argument("--drop-dir", default=str(_default_drop_dir()))
    parser.add_argument("--public-tour-dir", default="")
    parser.add_argument("--write", default="")
    parser.add_argument("--manifest-write", default="")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()
    receipt = build_discovery_receipt(
        drop_dir=Path(args.drop_dir),
        public_tour_dir=Path(args.public_tour_dir) if str(args.public_tour_dir or "").strip() else None,
    )
    write_path = Path(args.write).expanduser() if str(args.write or "").strip() else _artifact_dir() / "property-tour-export-discovery.json"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if str(args.manifest_write or "").strip():
        manifest_path = Path(args.manifest_write).expanduser()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(receipt["import_manifest"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "import_count", "rejected_count", "imports", "rejected")}, indent=2, sort_keys=True))
    if receipt["status"] == "ready":
        return 0
    return 2 if args.fail_on_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
