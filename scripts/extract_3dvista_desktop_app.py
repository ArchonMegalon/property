#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_APP_RELATIVE_PATH = Path("3DVista Virtual Tour.exe")
APPLICATION_XML_RELATIVE_PATH = Path("META-INF") / "AIR" / "application.xml"
HELPER_COMMANDS = {
    "tdvtools_v2": Path("bin") / "win64" / "tdvtools_v2.exe",
    "three_d_tools": Path("bin") / "win64" / "three-d-tools.exe",
    "tdv_server": Path("bin") / "win64" / "TDVServer.exe",
    "zip_sign": Path("bin") / "win64" / "zip-sign.exe",
    "file_picker_cli": Path("bin") / "win64" / "file-picker-cli.exe",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_installer_path() -> Path:
    return Path(
        os.getenv("PROPERTYQUARRY_3DVISTA_INSTALLER")
        or _repo_root() / "state" / "vendor_installers" / "3DVVirtualTour_x64.exe"
    ).expanduser()


def _default_app_dir() -> Path:
    return Path(
        os.getenv("PROPERTYQUARRY_3DVISTA_APP_DIR")
        or _repo_root() / "state" / "vendor_apps" / "3dvista"
    ).expanduser()


def _default_extract_dir() -> Path:
    return Path(
        os.getenv("PROPERTYQUARRY_3DVISTA_EXTRACT_DIR")
        or _repo_root() / "state" / "vendor_extracts" / "3dvista-current"
    ).expanduser()


def _file_row(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": 0}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": path.stat().st_size,
    }


def _read_air_metadata(app_dir: Path) -> dict[str, str]:
    application_xml = app_dir / APPLICATION_XML_RELATIVE_PATH
    if not application_xml.is_file():
        return {"version_number": "", "version_label": "", "app_id": "", "name": ""}
    try:
        root = ET.fromstring(application_xml.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError:
        return {"version_number": "", "version_label": "", "app_id": "", "name": ""}
    namespace = ""
    if root.tag.startswith("{") and "}" in root.tag:
        namespace = root.tag.split("}", 1)[0].strip("{")

    def find_text(name: str) -> str:
        path = f"{{{namespace}}}{name}" if namespace else name
        node = root.find(path)
        return str(node.text or "").strip() if node is not None else ""

    return {
        "version_number": find_text("versionNumber"),
        "version_label": find_text("versionLabel"),
        "app_id": find_text("id"),
        "name": find_text("name"),
    }


def _helper_rows(app_dir: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for name, relative_path in HELPER_COMMANDS.items():
        path = app_dir / relative_path
        rows[name] = {
            "path": str(path.resolve()) if path.exists() else str(path),
            "available": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else 0,
        }
    return rows


def _run_7z_extract(installer_path: Path, extract_dir: Path) -> dict[str, Any]:
    seven_zip = shutil.which("7z") or shutil.which("7zz")
    if not seven_zip:
        return {"status": "skipped", "reason": "7z_missing", "command": []}
    if not installer_path.is_file():
        return {"status": "skipped", "reason": "installer_missing", "command": []}
    extract_dir.mkdir(parents=True, exist_ok=True)
    command = [seven_zip, "x", "-y", f"-o{extract_dir}", str(installer_path)]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=900)
    return {
        "status": "pass" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "command": command,
        "stdout_tail": (completed.stdout or "").strip().splitlines()[-20:],
        "stderr_tail": (completed.stderr or "").strip().splitlines()[-20:],
    }


def _sync_app_dir(extract_dir: Path, app_dir: Path) -> dict[str, Any]:
    source_app = extract_dir / REQUIRED_APP_RELATIVE_PATH
    if not source_app.is_file():
        return {"status": "skipped", "reason": "extracted_app_missing", "source": str(source_app)}
    if app_dir.exists():
        shutil.rmtree(app_dir)
    shutil.copytree(extract_dir, app_dir)
    return {"status": "pass", "source": str(extract_dir.resolve()), "target": str(app_dir.resolve())}


def build_3dvista_app_receipt(
    *,
    installer_path: Path,
    app_dir: Path,
    extract_dir: Path,
    extract: bool = False,
    sync_app: bool = False,
) -> dict[str, Any]:
    extraction: dict[str, Any] = {"status": "not_requested"}
    sync: dict[str, Any] = {"status": "not_requested"}
    if extract:
        extraction = _run_7z_extract(installer_path, extract_dir)
    if sync_app:
        sync = _sync_app_dir(extract_dir, app_dir)

    app_exe = app_dir / REQUIRED_APP_RELATIVE_PATH
    helper_rows = _helper_rows(app_dir)
    helper_names_available = sorted(name for name, row in helper_rows.items() if row["available"])
    app_ready = app_exe.is_file()
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "ready" if app_ready else "missing_app",
        "installer": _file_row(installer_path),
        "extract_dir": str(extract_dir.resolve()),
        "app_dir": str(app_dir.resolve()),
        "extraction": extraction,
        "sync": sync,
        "app": _file_row(app_exe),
        "air_metadata": _read_air_metadata(app_dir),
        "helper_commands": helper_rows,
        "helper_commands_available": helper_names_available,
        "panorama_processing_cli_ready": "tdvtools_v2" in helper_names_available,
        "three_d_asset_cli_ready": "three_d_tools" in helper_names_available,
        "local_tour_server_cli_ready": "tdv_server" in helper_names_available,
        "headless_publish_cli_ready": False,
        "verified_export_required": True,
        "next_actions": [
            {
                "area": "verified_3dvista_export",
                "action": "Create or import a complete 3DVista export whose entry/runtime contains tdvplayer, tdvplayerapi, or tourviewer markers; the desktop app extraction alone is not tour-control evidence.",
            }
        ],
        "note": "This receipt proves official 3DVista desktop app extraction/readiness only. It intentionally does not claim a verified hosted tour export.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and verify the official 3DVista desktop app for PropertyQuarry operator use.")
    parser.add_argument("--installer", default=str(_default_installer_path()))
    parser.add_argument("--app-dir", default=str(_default_app_dir()))
    parser.add_argument("--extract-dir", default=str(_default_extract_dir()))
    parser.add_argument("--extract", action="store_true", help="Run 7z extraction from the installer into --extract-dir.")
    parser.add_argument("--sync-app", action="store_true", help="Copy the extracted app payload into --app-dir after extraction.")
    parser.add_argument("--write", default="_completion/tours/3dvista-desktop-app-current.json")
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args()

    receipt = build_3dvista_app_receipt(
        installer_path=Path(args.installer).expanduser(),
        app_dir=Path(args.app_dir).expanduser(),
        extract_dir=Path(args.extract_dir).expanduser(),
        extract=bool(args.extract),
        sync_app=bool(args.sync_app),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        output_path = Path(args.write)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if args.fail_on_missing and receipt.get("status") != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
