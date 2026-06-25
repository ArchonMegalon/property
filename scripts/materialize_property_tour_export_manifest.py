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


IMPORTABLE_PROVIDERS = ("3dvista", "pano2vr")


def _tour_root() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/docker/property/state/public_property_tours").expanduser().resolve()


def _artifact_dir() -> Path:
    return Path(os.getenv("EA_ARTIFACT_DIR") or "/data/artifacts").expanduser().resolve()


def _incoming_root() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR") or "/data/incoming_property_tours").expanduser().resolve()


def _provider_target_subdir(provider: str) -> str:
    return "3dvista" if provider == "3dvista" else "pano2vr"


def _missing_import_targets(receipt: dict[str, Any], *, providers: set[str], incoming_root: Path, limit_per_provider: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    counts = {provider: 0 for provider in providers}
    for tour in list(receipt.get("tours") or []):
        if not isinstance(tour, dict):
            continue
        slug = str(tour.get("slug") or "").strip()
        if not slug:
            continue
        for missing in list(tour.get("missing_evidence") or []):
            if not isinstance(missing, dict):
                continue
            provider = str(missing.get("provider") or "").strip().lower()
            if provider not in providers or provider not in IMPORTABLE_PROVIDERS:
                continue
            if counts.get(provider, 0) >= limit_per_provider:
                continue
            export_dir = incoming_root / slug / _provider_target_subdir(provider)
            rows.append(
                {
                    "slug": slug,
                    "provider": provider,
                    "export_dir": str(export_dir),
                    "entry": "",
                    "target_subdir": _provider_target_subdir(provider),
                    "reason": str(missing.get("reason") or ""),
                    "action": str(missing.get("action") or ""),
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
            "Copy each real provider export into its export_dir before running the import command.",
            "Do not place placeholder HTML in these directories; the hardened importers reject unverified entries.",
            "After import, run verify_property_tour_controls.py with --require-all-provider-modes.",
        ],
    }


def _parse_provider_filter(raw: str) -> set[str]:
    values = {part.strip().lower() for part in str(raw or "").split(",") if part.strip()}
    return {value for value in values if value in IMPORTABLE_PROVIDERS} or set(IMPORTABLE_PROVIDERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a PropertyQuarry 3DVista/Pano2VR export import manifest from current missing tour evidence.")
    parser.add_argument("--tour-root", default="", help="Tour root. Defaults to EA_PUBLIC_TOUR_DIR.")
    parser.add_argument("--incoming-root", default="", help="Where operators should drop exports. Defaults to PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR or /data/incoming_property_tours.")
    parser.add_argument("--providers", default="3dvista,pano2vr", help="Comma-separated provider filter.")
    parser.add_argument("--limit-per-provider", type=int, default=1)
    parser.add_argument("--write", default="", help="Output manifest path. Defaults to EA_ARTIFACT_DIR/property-tour-export-import-manifest.json.")
    args = parser.parse_args()
    manifest = build_export_manifest(
        tour_root=Path(args.tour_root) if str(args.tour_root or "").strip() else None,
        incoming_root=Path(args.incoming_root) if str(args.incoming_root or "").strip() else None,
        providers=_parse_provider_filter(args.providers),
        limit_per_provider=max(1, int(args.limit_per_provider or 1)),
    )
    write_path = Path(args.write).expanduser().resolve() if str(args.write or "").strip() else _artifact_dir() / "property-tour-export-import-manifest.json"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("status", "tour_root", "incoming_root", "missing_provider_modes", "import_count", "imports", "next_command")}, indent=2, sort_keys=True))
    return 0 if manifest["status"] in {"pass", "ready_for_exports"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
