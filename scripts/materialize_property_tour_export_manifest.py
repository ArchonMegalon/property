#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_property_tour_controls import build_property_tour_control_receipt


IMPORTABLE_PROVIDERS = ("3dvista", "pano2vr", "krpano", "magicfit")
PROVIDER_ENTRY_MARKERS = {
    "3dvista": "index.html/index.htm containing tdvplayer, tdvplayerapi, or tourviewer runtime markers",
    "pano2vr": "index.html/index.htm containing ggpkg, ggskin, pano.xml, or tour.js runtime markers",
    "krpano": "one real 2:1 equirectangular panorama named panorama.jpg/png/webp, or six square cube-face images named cube-face-1..6",
    "magicfit": "a playable MagicFit MP4/MOV/WebM plus the matching MagicFit render receipt JSON",
}


def _tour_root() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/property/state/public_property_tours").expanduser().resolve()


def _artifact_dir() -> Path:
    return Path(os.getenv("EA_ARTIFACT_DIR") or "/data/artifacts").expanduser().resolve()


def _incoming_root() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR") or "/data/incoming_property_tours").expanduser().resolve()


def _provider_target_subdir(provider: str) -> str:
    if provider == "3dvista":
        return "3dvista"
    if provider == "pano2vr":
        return "pano2vr"
    if provider == "krpano":
        return "krpano"
    if provider == "magicfit":
        return "magicfit"
    return provider


def _default_missing_action(provider: str) -> str:
    if provider == "3dvista":
        return "run import_3dvista_export.py with a verified 3DVista export or add an allowlisted 3dvista.com URL"
    if provider == "pano2vr":
        return "run import_pano2vr_export.py with a verified Pano2VR export"
    if provider == "krpano":
        return "run import_krpano_walkable_scene.py with a real 2:1 panorama or six cube faces and krpano license env"
    if provider == "magicfit":
        return "run import_magicfit_walkthrough.py with a playable MagicFit video and matching render receipt"
    return ""


def _default_missing_reason(provider: str) -> str:
    if provider == "3dvista":
        return "missing_3dvista_export"
    if provider == "pano2vr":
        return "missing_pano2vr_export"
    if provider == "krpano":
        return "missing_krpano_walkable_scene"
    if provider == "magicfit":
        return "missing_magicfit_walkthrough"
    return ""


def _tour_sort_key(tour: dict[str, Any]) -> tuple[int, int, str]:
    controls = [row for row in list(tour.get("controls") or []) if isinstance(row, dict)]
    is_ready = str(tour.get("status") or "").strip().lower() == "ready"
    return (0 if is_ready else 1, -len(controls), str(tour.get("slug") or ""))


def _missing_import_targets(receipt: dict[str, Any], *, providers: set[str], incoming_root: Path, limit_per_provider: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    counts = {provider: 0 for provider in providers}
    tours = [tour for tour in list(receipt.get("tours") or []) if isinstance(tour, dict)]
    for tour in sorted(tours, key=_tour_sort_key):
        if not isinstance(tour, dict):
            continue
        slug = str(tour.get("slug") or "").strip()
        if not slug:
            continue
        missing_rows = [row for row in list(tour.get("missing_evidence") or []) if isinstance(row, dict)]
        if not missing_rows:
            missing_rows = [
                {
                    "provider": provider,
                    "reason": _default_missing_reason(provider),
                    "action": _default_missing_action(provider),
                }
                for provider in list(tour.get("missing_provider_modes") or [])
            ]
        current_control_providers = sorted(
            {
                str(control.get("provider") or "").strip().lower()
                for control in list(tour.get("controls") or [])
                if isinstance(control, dict) and str(control.get("provider") or "").strip()
            }
        )
        for missing in missing_rows:
            provider = str(missing.get("provider") or "").strip().lower()
            if provider not in providers or provider not in IMPORTABLE_PROVIDERS:
                continue
            if counts.get(provider, 0) >= limit_per_provider:
                continue
            export_dir = incoming_root / slug / _provider_target_subdir(provider)
            rows.append(
                {
                    "slug": slug,
                    "title": str(tour.get("title") or slug).strip(),
                    "provider": provider,
                    "export_dir": str(export_dir),
                    "asset_dir": str(export_dir),
                    "entry": "",
                    "target_subdir": _provider_target_subdir(provider),
                    "reason": str(missing.get("reason") or ""),
                    "action": str(missing.get("action") or ""),
                    "current_control_providers": ",".join(current_control_providers),
                }
            )
            counts[provider] = counts.get(provider, 0) + 1
    return rows


def build_export_manifest(
    *,
    tour_root: Path | None = None,
    incoming_root: Path | None = None,
    providers: set[str] | None = None,
    limit_per_provider: int = 1,
) -> dict[str, Any]:
    resolved_tour_root = (tour_root or _tour_root()).expanduser().resolve()
    resolved_incoming_root = (incoming_root or _incoming_root()).expanduser().resolve()
    receipt = build_property_tour_control_receipt(
        tour_root=resolved_tour_root,
        require_all_provider_modes=True,
    )
    requested_providers = providers or set(IMPORTABLE_PROVIDERS)
    missing_modes = set(str(provider) for provider in list(receipt.get("missing_provider_modes") or []))
    selected_providers = {provider for provider in requested_providers if provider in missing_modes and provider in IMPORTABLE_PROVIDERS}
    imports = _missing_import_targets(
        receipt,
        providers=selected_providers,
        incoming_root=resolved_incoming_root,
        limit_per_provider=max(1, int(limit_per_provider or 1)),
    )
    status = "ready_for_exports" if imports else ("pass" if not selected_providers else "blocked_no_import_targets")
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tour_root": str(resolved_tour_root),
        "incoming_root": str(resolved_incoming_root),
        "missing_provider_modes": sorted(missing_modes),
        "providers": sorted(selected_providers),
        "import_count": len(imports),
        "imports": imports,
        "next_command": "python /app/scripts/import_property_tour_exports.py --manifest /data/artifacts/property-tour-export-import-manifest.json --write /data/artifacts/property-tour-export-import-receipt.json",
        "notes": [
            "Copy each real provider export or asset into its export_dir before running the import command.",
            "Do not place placeholder HTML, flat photos, or fake videos in these directories; the hardened importers reject unverified entries.",
            "After import, run verify_property_tour_controls.py with --require-all-provider-modes.",
        ],
    }


def prepare_export_drop_dirs(manifest: dict[str, Any]) -> list[dict[str, str]]:
    prepared: list[dict[str, str]] = []
    for row in list(manifest.get("imports") or []):
        if not isinstance(row, dict):
            continue
        export_dir = Path(str(row.get("export_dir") or "")).expanduser().resolve()
        provider = str(row.get("provider") or "").strip().lower()
        slug = str(row.get("slug") or "").strip()
        if provider not in IMPORTABLE_PROVIDERS or not slug:
            continue
        export_dir.mkdir(parents=True, exist_ok=True)
        readme_path = export_dir / "README.propertyquarry-export.txt"
        readme_path.write_text(
            "\n".join(
                [
                    "PropertyQuarry provider export drop folder",
                    "",
                    f"Slug: {slug}",
                    f"Title: {str(row.get('title') or slug).strip()}",
                    f"Provider: {provider}",
                    f"Current verified controls: {str(row.get('current_control_providers') or 'none').strip()}",
                    f"Expected entry: {PROVIDER_ENTRY_MARKERS[provider]}",
                    "",
                    "Copy the real provider export or asset contents into this directory.",
                    "Do not copy placeholder HTML, flat listing photos, or fake videos; the importers reject unverified entries.",
                    "",
                    f"After exports are copied, run: {manifest.get('next_command')}",
                    "Then rerun: python /app/scripts/verify_property_tour_controls.py --tour-root /data/public_property_tours --require-all-provider-modes --summary-only",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        prepared.append(
            {
                "slug": slug,
                "provider": provider,
                "export_dir": str(export_dir),
                "readme": str(readme_path),
            }
        )
    return prepared


def _parse_provider_filter(raw: str) -> set[str]:
    values = {part.strip().lower() for part in str(raw or "").split(",") if part.strip()}
    return {value for value in values if value in IMPORTABLE_PROVIDERS} or set(IMPORTABLE_PROVIDERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a PropertyQuarry tour/walkthrough import manifest from current missing evidence.")
    parser.add_argument("--tour-root", default="", help="Tour root. Defaults to EA_PUBLIC_TOUR_DIR.")
    parser.add_argument("--incoming-root", default="", help="Where operators should drop exports. Defaults to PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR or /data/incoming_property_tours.")
    parser.add_argument("--providers", default="3dvista,pano2vr,krpano,magicfit", help="Comma-separated provider filter.")
    parser.add_argument("--limit-per-provider", type=int, default=1)
    parser.add_argument("--prepare-dirs", action="store_true", help="Create incoming export directories with per-provider README instructions.")
    parser.add_argument("--write", default="", help="Output manifest path. Defaults to EA_ARTIFACT_DIR/property-tour-export-import-manifest.json.")
    args = parser.parse_args()
    manifest = build_export_manifest(
        tour_root=Path(args.tour_root) if str(args.tour_root or "").strip() else None,
        incoming_root=Path(args.incoming_root) if str(args.incoming_root or "").strip() else None,
        providers=_parse_provider_filter(args.providers),
        limit_per_provider=max(1, int(args.limit_per_provider or 1)),
    )
    if args.prepare_dirs:
        manifest["prepared_drop_dirs"] = prepare_export_drop_dirs(manifest)
    write_path = Path(args.write).expanduser().resolve() if str(args.write or "").strip() else _artifact_dir() / "property-tour-export-import-manifest.json"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("status", "tour_root", "incoming_root", "missing_provider_modes", "import_count", "imports", "next_command")}, indent=2, sort_keys=True))
    return 0 if manifest["status"] in {"pass", "ready_for_exports"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
