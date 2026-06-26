#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.discover_property_tour_exports import build_discovery_receipt


INSTALLER_PATTERNS = (
    "Pano2VR*.exe",
    "Pano2VR*.msi",
    "pano2vr*.exe",
    "pano2vr*.msi",
    "3DVista*.exe",
    "3DVista*.msi",
    "3DVista*.dmg",
    "3DVVirtualTour*.exe",
    "3DVVirtualTour*.msi",
    "VirtualTour*.exe",
    "VirtualTour*.msi",
)
OFFICIAL_INSTALLER_SOURCES = {
    "3dvista": {
        "product": "3DVista VT Pro",
        "download_page": "https://www.3dvista.com/en/download/",
        "account_page": "https://cloud.3dvista.com",
        "operator_note": "Use the owned 3DVista account to download/export; keep private credentials out of tracked receipts.",
    },
    "pano2vr": {
        "product": "Pano2VR 8 Pro",
        "download_page": "https://ggnome.com/pano2vr-download/",
        "account_page": "https://ggnome.com/account/",
        "operator_note": "The Garden Gnome download may be Cloudflare-challenged for headless curl; download with a browser if the host fetch returns 403.",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_drop_dir() -> Path:
    return Path(
        os.getenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR")
        or os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR")
        or _repo_root() / "state" / "incoming_property_tours"
    ).expanduser()


def _default_tour_root() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or _repo_root() / "state" / "public_property_tours").expanduser()


def _default_wine_prefix() -> Path:
    return Path(os.getenv("PROPERTYQUARRY_PANO2VR_WINEPREFIX") or _repo_root() / "state" / "wine-pano2vr").expanduser()


def _command_version(command: str, *args: str, env: dict[str, str] | None = None) -> dict[str, object]:
    executable = shutil.which(command)
    if not executable:
        return {"available": False, "path": "", "version": ""}
    version = ""
    try:
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            env=command_env,
        )
        version = (completed.stdout or completed.stderr or "").strip().splitlines()[0][:160]
    except Exception:
        version = ""
    return {"available": True, "path": executable, "version": version}


def _container_command_available(container: str, command: str) -> dict[str, object]:
    if not container:
        return {"available": False, "container": "", "path": ""}
    docker = shutil.which("docker")
    if not docker:
        return {"available": False, "container": container, "path": "", "reason": "docker_missing"}
    try:
        completed = subprocess.run(
            [docker, "exec", container, "sh", "-lc", f"command -v {command}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {"available": False, "container": container, "path": "", "reason": type(exc).__name__}
    path = (completed.stdout or "").strip().splitlines()[0] if completed.stdout.strip() else ""
    return {
        "available": completed.returncode == 0 and bool(path),
        "container": container,
        "path": path,
        "returncode": int(completed.returncode),
    }


def _container_python_import_available(container: str, module: str) -> dict[str, object]:
    if not container:
        return {"available": False, "container": "", "module": module}
    docker = shutil.which("docker")
    if not docker:
        return {"available": False, "container": container, "module": module, "reason": "docker_missing"}
    script = f"python3 - <<'PY'\nimport {module}\nprint({module}.__version__ if hasattr({module}, '__version__') else 'available')\nPY"
    try:
        completed = subprocess.run(
            [docker, "exec", container, "sh", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {"available": False, "container": container, "module": module, "reason": type(exc).__name__}
    return {
        "available": completed.returncode == 0,
        "container": container,
        "module": module,
        "version": (completed.stdout or completed.stderr or "").strip().splitlines()[0][:120] if (completed.stdout or completed.stderr or "").strip() else "",
        "returncode": int(completed.returncode),
    }


def _python_module_available(module: str) -> bool:
    try:
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _installer_search_roots(extra_roots: list[str]) -> list[Path]:
    roots = [
        _repo_root() / "state" / "vendor_installers",
        _repo_root() / "state" / "incoming_property_tours",
        Path.home() / "Downloads",
    ]
    roots.extend(Path(value).expanduser() for value in extra_roots if str(value or "").strip())
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _find_installers(roots: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in INSTALLER_PATTERNS:
            for path in sorted(root.rglob(pattern)):
                if not path.is_file():
                    continue
                lowered_name = path.name.lower()
                provider = "pano2vr" if "pano2vr" in lowered_name else "3dvista"
                rows.append(
                    {
                        "provider": provider,
                        "path": str(path.resolve()),
                        "size_bytes": path.stat().st_size,
                    }
                )
    return rows


def _installed_app_search_roots(wine_prefix: Path) -> list[Path]:
    roots = [
        _repo_root() / "state" / "vendor_apps" / "3dvista",
        _repo_root() / "state" / "vendor_apps" / "pano2vr",
        _repo_root() / "state" / "wine-3dvista",
        _repo_root() / "state" / "wine-pano2vr",
        wine_prefix,
    ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _find_installed_apps(roots: list[Path]) -> list[dict[str, object]]:
    provider_patterns = {
        "pano2vr": ("Pano2VR*.exe", "pano2vr*.exe"),
        "3dvista": ("3DVista*.exe", "VirtualTour*.exe", "3DVVirtualTour*.exe"),
    }
    rows: list[dict[str, object]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for provider, patterns in provider_patterns.items():
            for pattern in patterns:
                for path in sorted(root.glob(pattern)):
                    if not path.is_file():
                        continue
                    rows.append(
                        {
                            "provider": provider,
                            "path": str(path.resolve()),
                            "size_bytes": path.stat().st_size,
                            "layout": "portable_extract",
                        }
                    )
        for program_root_name in ("Program Files", "Program Files (x86)"):
            program_root = root / "drive_c" / program_root_name
            if not program_root.is_dir():
                continue
            for provider, patterns in provider_patterns.items():
                for pattern in patterns:
                    for path in sorted(program_root.rglob(pattern)):
                        if not path.is_file():
                            continue
                        rows.append(
                            {
                                "provider": provider,
                                "path": str(path.resolve()),
                                "size_bytes": path.stat().st_size,
                                "layout": "wine_program_files",
                            }
                        )
    return rows


def _provider_counts(rows: list[dict[str, object]], providers: tuple[str, ...]) -> dict[str, int]:
    counts = {provider: 0 for provider in providers}
    for row in rows:
        provider = str(row.get("provider") or "").strip().lower()
        if provider in counts:
            counts[provider] += 1
    return counts


def _installer_source_rows(providers: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for provider in providers:
        source = OFFICIAL_INSTALLER_SOURCES.get(provider)
        if not source:
            continue
        rows.append(
            {
                "provider": provider,
                "product": str(source["product"]),
                "download_page": str(source["download_page"]),
                "account_page": str(source["account_page"]),
                "operator_note": str(source["operator_note"]),
            }
        )
    return rows


def _provider_ready_counts(discovery: dict[str, Any]) -> dict[str, int]:
    counts = {"3dvista": 0, "pano2vr": 0}
    for row in list(discovery.get("imports") or []):
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip().lower()
        if provider in counts:
            counts[provider] += 1
    return counts


def build_vendor_tooling_receipt(
    *,
    drop_dir: Path,
    tour_root: Path,
    wine_prefix: Path,
    installer_roots: list[Path],
    installed_app_roots: list[Path] | None = None,
    runtime_container: str = "",
    runtime_only: bool = False,
) -> dict[str, Any]:
    discovery = build_discovery_receipt(drop_dir=drop_dir, public_tour_dir=tour_root)
    provider_ready_counts = _provider_ready_counts(discovery)
    installers = [] if runtime_only else _find_installers(installer_roots)
    installed_apps = [] if runtime_only else _find_installed_apps(installed_app_roots if installed_app_roots is not None else _installed_app_search_roots(wine_prefix))
    installer_counts = _provider_counts(installers, ("3dvista", "pano2vr"))
    installed_app_counts = _provider_counts(installed_apps, ("3dvista", "pano2vr"))
    wine = {"available": False, "path": "", "version": "", "skipped": "runtime_only"} if runtime_only else _command_version("wine", "--version")
    wine64 = {"available": False, "path": "", "version": "", "skipped": "runtime_only"} if runtime_only else _command_version("wine64", "--version")
    xvfb = {"available": False, "path": "", "version": "", "skipped": "runtime_only"} if runtime_only else _command_version("xvfb-run", "--help")
    winetricks = {"available": False, "path": "", "version": "", "skipped": "runtime_only"} if runtime_only else _command_version("winetricks", "--version")
    krpano = _command_version("krpanotools", "version")
    blender = _command_version("blender", "--version")
    colmap = _command_version("colmap", "-h")
    meshlabserver = _command_version("meshlabserver", "-h", env={"QT_QPA_PLATFORM": "offscreen"})
    ffmpeg = _command_version("ffmpeg", "-version")
    exiftool = _command_version("exiftool", "-ver")
    imagemagick = _command_version("magick", "-version")
    if not imagemagick.get("available"):
        imagemagick = _command_version("convert", "-version")
    wine_prefix_ready = False if runtime_only else wine_prefix.is_dir() and (wine_prefix / "system.reg").is_file()
    wine_runtime_ready = bool(wine.get("available")) or bool(wine64.get("available"))
    host_ready = None if runtime_only else wine_runtime_ready and bool(xvfb.get("available")) and wine_prefix_ready
    host_generated_tour_tools = {
        "krpanotools": krpano,
        "blender": blender,
        "colmap": colmap,
        "meshlabserver": meshlabserver,
        "ffmpeg": ffmpeg,
        "exiftool": exiftool,
        "imagemagick": imagemagick,
    }
    runtime_local_tools = {
        "ffmpeg": ffmpeg,
        "blender": blender,
        "colmap": colmap,
        "exiftool": exiftool,
        "convert": imagemagick,
        "python:numpy": {"available": _python_module_available("numpy"), "path": "python", "version": ""},
    }
    generated_tour_tools = runtime_local_tools if runtime_only else host_generated_tour_tools
    generated_tour_ready = all(bool(row.get("available")) for row in generated_tour_tools.values())
    runtime_required_tools = ("ffmpeg", "blender", "colmap", "exiftool", "convert")
    runtime_generated_tour_tools = {
        command: _container_command_available(runtime_container, command)
        for command in runtime_required_tools
    } if runtime_container and not runtime_only else {}
    if runtime_container:
        runtime_generated_tour_tools["python:numpy"] = _container_python_import_available(runtime_container, "numpy")
    if runtime_only:
        runtime_generated_tour_tools = runtime_local_tools
    runtime_generated_tour_ready = (
        all(bool(row.get("available")) for row in runtime_generated_tour_tools.values())
        if runtime_generated_tour_tools
        else None
    )
    missing_exports = [
        provider
        for provider in ("3dvista", "pano2vr")
        if provider_ready_counts.get(provider, 0) <= 0
    ]
    next_actions: list[dict[str, object]] = []
    if not runtime_only and not host_ready:
        next_actions.append(
            {
                "area": "host_tooling",
                "action": "install wine64, wine32, winetricks, xvfb-run and initialize PROPERTYQUARRY_PANO2VR_WINEPREFIX",
            }
        )
    if not generated_tour_ready:
        missing_tools = [name for name, row in generated_tour_tools.items() if not row.get("available")]
        next_actions.append(
            {
                "area": "runtime_generated_tour_tooling" if runtime_only else "generated_tour_tooling",
                "missing_tools": missing_tools,
                "action": "install the missing runtime generation tools before claiming floorplan/photos-to-tour readiness" if runtime_only else "install the missing local generation tools before claiming floorplan/photos-to-tour readiness",
            }
        )
    if runtime_generated_tour_ready is False and not runtime_only:
        missing_runtime_tools = [name for name, row in runtime_generated_tour_tools.items() if not row.get("available")]
        next_actions.append(
            {
                "area": "runtime_generated_tour_tooling",
                "container": runtime_container,
                "missing_tools": missing_runtime_tools,
                "action": "install missing runtime tools or route reconstruction generation to the prepared operator host lane",
            }
        )
    missing_installers = [
        provider
        for provider in ("3dvista", "pano2vr")
        if not runtime_only and installer_counts.get(provider, 0) <= 0 and provider_ready_counts.get(provider, 0) <= 0
    ]
    if missing_installers:
        next_actions.append(
            {
                "area": "vendor_installers",
                "missing_providers": missing_installers,
                "action": "download official desktop installers into state/vendor_installers or provide complete verified exports",
                "official_sources": _installer_source_rows(missing_installers),
            }
        )
    missing_installed_apps = [
        provider
        for provider in ("3dvista", "pano2vr")
        if not runtime_only
        and installer_counts.get(provider, 0) > 0
        and installed_app_counts.get(provider, 0) <= 0
        and provider_ready_counts.get(provider, 0) <= 0
    ]
    if missing_installed_apps:
        next_actions.append(
            {
                "area": "vendor_desktop_apps",
                "missing_providers": missing_installed_apps,
                "action": "install the cached official desktop app under Wine or provide a complete verified export",
            }
        )
    for provider in missing_exports:
        next_actions.append(
            {
                "area": "verified_export",
                "provider": provider,
                "action": f"place a complete verified {provider} export folder or zip into the prepared PropertyQuarry drop directory",
                "accepted_layouts": [
                    f"<drop>/<slug>/{provider}/",
                    f"<drop>/{provider}/<slug>/",
                    "or a zip file inside either folder",
                ],
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "runtime" if runtime_only else "operator_host",
        "status": "pass" if (runtime_only or host_ready) and generated_tour_ready and not missing_exports else "blocked_missing_verified_exports",
        "host_ready": host_ready,
        "generated_tour_ready": generated_tour_ready,
        "generated_tour_tools": generated_tour_tools,
        "runtime_generated_tour_ready": runtime_generated_tour_ready,
        "runtime_generated_tour_tools": runtime_generated_tour_tools,
        "wine_runtime_ready": wine_runtime_ready,
        "wine": wine,
        "wine64": wine64,
        "xvfb_run": xvfb,
        "winetricks": winetricks,
        "wine_prefix": {
            "path": str(wine_prefix.resolve()),
            "ready": wine_prefix_ready,
        },
        "installer_count": len(installers),
        "installers": installers[:20],
        "installer_counts": installer_counts,
        "official_installer_sources": _installer_source_rows(["3dvista", "pano2vr"]),
        "installed_app_count": len(installed_apps),
        "installed_apps": installed_apps[:20],
        "installed_app_counts": installed_app_counts,
        "drop_dir": str(drop_dir.resolve()),
        "tour_root": str(tour_root.resolve()),
        "verified_export_ready_counts": provider_ready_counts,
        "missing_verified_exports": missing_exports,
        "discovery_status": str(discovery.get("status") or ""),
        "discovery_import_count": int(discovery.get("import_count") or 0),
        "discovery_rejected_count": int(discovery.get("rejected_count") or 0),
        "next_actions": next_actions,
        "note": "This receipt records only local tooling, installer, and verified-export readiness; private credentials and invoice data are intentionally omitted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PropertyQuarry desktop vendor tooling readiness for 3DVista/Pano2VR.")
    parser.add_argument("--drop-dir", default=str(_default_drop_dir()))
    parser.add_argument("--tour-root", default=str(_default_tour_root()))
    parser.add_argument("--wine-prefix", default=str(_default_wine_prefix()))
    parser.add_argument("--installer-root", action="append", default=[])
    parser.add_argument("--runtime-container", default=os.getenv("PROPERTYQUARRY_API_CONTAINER_NAME") or "propertyquarry-api")
    parser.add_argument("--runtime-only", action="store_true", help="Validate the current runtime container/process lane; skip desktop Wine/installers/apps.")
    parser.add_argument("--write", default="_completion/tours/property-tour-vendor-tooling-current.json")
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    receipt = build_vendor_tooling_receipt(
        drop_dir=Path(args.drop_dir).expanduser(),
        tour_root=Path(args.tour_root).expanduser(),
        wine_prefix=Path(args.wine_prefix).expanduser(),
        installer_roots=_installer_search_roots(args.installer_root),
        runtime_container=str(args.runtime_container or "").strip(),
        runtime_only=bool(args.runtime_only),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if receipt.get("status") == "pass":
        return 0
    return 2 if args.fail_on_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
