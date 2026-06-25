#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_BY_PROVIDER = {
    "3dvista": "import_3dvista_export.py",
    "pano2vr": "import_pano2vr_export.py",
}


def _safe_provider(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "").replace("-", "")
    if normalized in {"3dvista", "threevista", "threedvista", "3d-vista".replace("-", "")}:
        return "3dvista"
    if normalized in {"pano2vr", "pano2v"}:
        return "pano2vr"
    return ""


def _safe_slug(value: object) -> str:
    slug = str(value or "").strip()
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return ""
    return slug


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"import_manifest_invalid:{type(exc).__name__}") from exc
    rows = payload.get("imports") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("import_manifest_missing_imports")
    return [dict(row) for row in rows if isinstance(row, dict)]


def _artifact_dir() -> Path:
    return Path(os.getenv("EA_ARTIFACT_DIR") or "/data/artifacts").expanduser().resolve()


def _run_import(row: dict[str, Any], *, env: dict[str, str]) -> dict[str, Any]:
    provider = _safe_provider(row.get("provider"))
    slug = _safe_slug(row.get("slug"))
    export_dir = Path(str(row.get("export_dir") or "")).expanduser()
    result: dict[str, Any] = {
        "provider": provider or str(row.get("provider") or "").strip(),
        "slug": slug or str(row.get("slug") or "").strip(),
        "status": "failed",
    }
    if not provider:
        result["error"] = "unsupported_provider"
        return result
    if not slug:
        result["error"] = "invalid_tour_slug"
        return result
    if not export_dir.is_dir():
        result["error"] = "export_dir_missing"
        return result
    script = ROOT / "scripts" / SCRIPT_BY_PROVIDER[provider]
    cmd = [
        sys.executable,
        str(script),
        "--slug",
        slug,
        "--export-dir",
        str(export_dir.resolve()),
    ]
    entry = str(row.get("entry") or "").strip()
    if entry:
        cmd.extend(["--entry", entry])
    target_subdir = str(row.get("target_subdir") or "").strip()
    if target_subdir:
        cmd.extend(["--target-subdir", target_subdir])
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=int(os.getenv("PROPERTYQUARRY_TOUR_IMPORT_TIMEOUT_SECONDS") or "120"),
        check=False,
    )
    result["returncode"] = completed.returncode
    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout or "import_failed").strip().splitlines()[-1][:240]
        return result
    try:
        imported = json.loads(completed.stdout or "{}")
    except Exception:
        imported = {}
    result["status"] = "imported"
    result["control_url"] = str(imported.get("control_url") or f"/tours/{slug}/control/{provider}")
    result["entry_relpath"] = str(imported.get("entry_relpath") or "")
    return result


def build_import_receipt(manifest_path: Path, *, public_tour_dir: Path | None = None) -> dict[str, Any]:
    imports = _load_manifest(manifest_path)
    env = dict(os.environ)
    if public_tour_dir is not None:
        env["EA_PUBLIC_TOUR_DIR"] = str(public_tour_dir.expanduser().resolve())
    rows = [_run_import(row, env=env) for row in imports]
    failed = [row for row in rows if row.get("status") != "imported"]
    return {
        "status": "pass" if not failed else "fail",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "public_tour_dir": env.get("EA_PUBLIC_TOUR_DIR") or "",
        "import_count": len(rows),
        "imported_count": len(rows) - len(failed),
        "failed_count": len(failed),
        "imports": rows,
        "notes": [
            "Each row delegates to the hardened single-export importer for its provider.",
            "Receipts include slugs, provider keys, control URLs, and relative entry paths only; raw provider credentials and private listing data are not required.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-import verified 3DVista and Pano2VR exports into PropertyQuarry public tour bundles.")
    parser.add_argument("--manifest", required=True, help="JSON file: {'imports': [{'slug','provider','export_dir', optional 'entry','target_subdir'}]}.")
    parser.add_argument("--public-tour-dir", default="", help="Override EA_PUBLIC_TOUR_DIR for this run.")
    parser.add_argument("--write", default="", help="Receipt path. Defaults to EA_ARTIFACT_DIR/property-tour-export-imports.json.")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.is_file():
        raise SystemExit("import_manifest_missing")
    receipt = build_import_receipt(
        manifest_path,
        public_tour_dir=Path(args.public_tour_dir) if str(args.public_tour_dir or "").strip() else None,
    )
    write_path = Path(args.write).expanduser().resolve() if str(args.write or "").strip() else _artifact_dir() / "property-tour-export-imports.json"
    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "import_count", "imported_count", "failed_count", "imports")}, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
