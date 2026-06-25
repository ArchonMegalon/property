#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROVIDERS = ("3dvista", "pano2vr", "krpano", "magicfit")
PROVIDER_DROP_LAYOUTS = {
    "3dvista": "<drop>/<slug>/3dvista/ or <drop>/3dvista/<slug>/ with a complete 3DVista export",
    "pano2vr": "<drop>/<slug>/pano2vr/ or <drop>/pano2vr/<slug>/ with a complete Pano2VR export",
    "krpano": "<drop>/<slug>/krpano/ or <drop>/krpano/<slug>/ with panorama.jpg/png/webp or cube-face-1..6",
    "magicfit": "<drop>/<slug>/magicfit/ or <drop>/magicfit/<slug>/ with magicfit-walkthrough.mp4 and magicfit-receipt.json",
}
REJECTION_ACTIONS = {
    "tour_manifest_missing": "create or import the base hosted tour bundle first so tour.json exists under the public tour directory",
    "3dvista_export_entry_unverified": "copy the complete 3DVista export; the entry or bundled runtime must contain tdvplayer, tdvplayerapi, or tourviewer markers",
    "pano2vr_export_entry_unverified": "copy the complete Pano2VR export; the entry or bundled runtime must contain ggpkg, ggskin, pano.xml, or tour.js markers",
    "krpano_assets_missing": "copy a real 2:1 panorama named panorama.jpg/png/webp or six cube faces named cube-face-1..6",
    "magicfit_video_missing": "copy the playable MagicFit walkthrough as magicfit-walkthrough.mp4/mov/webm or walkthrough.mp4/mov/webm",
    "magicfit_video_unverified": "replace the placeholder with a playable MagicFit video stream with positive duration",
    "magicfit_receipt_missing": "copy the matching MagicFit render receipt as magicfit-receipt.json or receipt.json",
    "magicfit_receipt_invalid": "replace the MagicFit receipt with valid JSON containing provider=magicfit and the target slug/output",
    "magicfit_receipt_provider_mismatch": "use the MagicFit receipt for this walkthrough; provider must be magicfit",
    "magicfit_receipt_output_mismatch": "use the MagicFit receipt that names the exact walkthrough video file in this drop folder",
    "magicfit_receipt_output_invalid": "fix the MagicFit receipt output_file path so it resolves to the copied video",
    "magicfit_receipt_target_mismatch": "use a MagicFit receipt whose target_slug, tour_slug, property_slug, slug, or hosted URL matches this tour slug",
    "unsupported_provider": "use one of the supported providers: 3dvista, pano2vr, krpano, or magicfit",
}
MARKERS_BY_PROVIDER = {
    "3dvista": ("tdvplayer", "tdvplayerapi", "tourviewer"),
    "pano2vr": ("ggpkg", "ggskin", "pano.xml", "tour.js"),
}
ENTRY_NAMES = ("index.html", "index.htm", "tour.html", "virtualtour.html", "output/index.html")
TEXT_RUNTIME_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".json", ".xml"}
EXPORT_ARCHIVE_SUFFIXES = {".zip"}
PANORAMA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}
MAX_MARKER_SCAN_BYTES = 1_000_000
MAX_MARKER_SCAN_FILES = 240
EQUIRECTANGULAR_MIN_RATIO = 1.9
EQUIRECTANGULAR_MAX_RATIO = 2.1


def _default_drop_dir() -> Path:
    return Path(
        os.getenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR")
        or os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR")
        or "/data/incoming_property_tours"
    ).expanduser()


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
    if normalized == "krpano":
        return "krpano"
    if normalized == "magicfit":
        return "magicfit"
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


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> Path:
    if not zip_path.is_file() or zip_path.suffix.lower() not in EXPORT_ARCHIVE_SUFFIXES:
        return target_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = str(member.filename or "").replace("\\", "/").lstrip("/")
            raw_parts = [part for part in name.split("/") if part]
            parts = [part for part in raw_parts if part not in {".", ".."}]
            if not parts or len(parts) != len(raw_parts):
                raise ValueError("unsafe_zip_path")
            destination = (target_dir / "/".join(parts)).resolve()
            if target_dir.resolve() not in destination.parents and destination != target_dir.resolve():
                raise ValueError("unsafe_zip_path")
        archive.extractall(target_dir)
    children = [path for path in target_dir.iterdir() if path.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0].resolve()
    return target_dir.resolve()


def _verified_zip_entry(zip_path: Path, provider: str) -> tuple[str, str]:
    try:
        with tempfile.TemporaryDirectory(prefix=f"propertyquarry-{provider}-zip-") as tmp:
            export_dir = _safe_extract_zip(zip_path, Path(tmp))
            entry, entry_relpath = _verified_entry(export_dir, provider)
            if entry is None:
                return "", ""
            return str(zip_path), entry_relpath
    except Exception:
        return "", ""


def _discover_export_zip(export_dir: Path, provider: str) -> tuple[Path | None, str]:
    preferred = [
        export_dir / f"{provider}.zip",
        export_dir / "export.zip",
        export_dir / "tour.zip",
    ]
    candidates = [path for path in preferred if path.is_file()] + [
        path for path in sorted(export_dir.glob("*.zip")) if path not in preferred
    ]
    for candidate in candidates:
        _, entry_relpath = _verified_zip_entry(candidate, provider)
        if entry_relpath:
            return candidate, entry_relpath
    return None, ""


def _discover_panorama(asset_dir: Path) -> Path | None:
    def is_real_equirectangular(candidate: Path) -> bool:
        if not candidate.is_file() or candidate.suffix.lower() not in PANORAMA_EXTENSIONS:
            return False
        try:
            from PIL import Image

            with Image.open(candidate) as image:
                width, height = int(image.width), int(image.height)
        except Exception:
            return False
        if width < 1024 or height < 512:
            return False
        ratio = width / height if height else 0
        return EQUIRECTANGULAR_MIN_RATIO <= ratio <= EQUIRECTANGULAR_MAX_RATIO

    for name in ("panorama.jpg", "panorama.jpeg", "panorama.png", "panorama.webp", "equirect.jpg", "equirect.jpeg", "equirect.png", "equirect.webp"):
        candidate = asset_dir / name
        if is_real_equirectangular(candidate):
            return candidate
    matches = [
        path
        for path in sorted(asset_dir.iterdir())
        if is_real_equirectangular(path) and "panorama" in path.stem.lower()
    ]
    return matches[0] if matches else None


def _discover_cube_faces(asset_dir: Path) -> list[Path]:
    faces: list[Path] = []
    for index in range(1, 7):
        face = next(
            (
                asset_dir / f"cube-face-{index}{suffix}"
                for suffix in sorted(PANORAMA_EXTENSIONS)
                if (asset_dir / f"cube-face-{index}{suffix}").is_file()
            ),
            None,
        )
        if face is None:
            return []
        faces.append(face)
    return faces


def _discover_video(asset_dir: Path) -> Path | None:
    preferred = [
        asset_dir / f"magicfit-walkthrough{suffix}"
        for suffix in sorted(VIDEO_EXTENSIONS)
    ] + [
        asset_dir / f"walkthrough{suffix}"
        for suffix in sorted(VIDEO_EXTENSIONS)
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate
    matches = [path for path in sorted(asset_dir.iterdir()) if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS]
    return matches[0] if matches else None


def _discover_receipt(asset_dir: Path) -> Path | None:
    for candidate in (asset_dir / "magicfit-receipt.json", asset_dir / "receipt.json"):
        if candidate.is_file():
            return candidate
    matches = sorted(asset_dir.glob("*.json"))
    return matches[0] if matches else None


def _receipt_target_matches_slug(payload: dict[str, object], *, slug: str) -> bool:
    expected = str(slug or "").strip()
    if not expected:
        return False
    for key in ("target_slug", "tour_slug", "property_slug", "slug"):
        if str(payload.get(key) or "").strip() == expected:
            return True
    for key in ("property_url", "tour_url", "hosted_url", "public_url"):
        value = str(payload.get(key) or "").strip().rstrip("/")
        if value and value.rsplit("/", 1)[-1] == expected:
            return True
    return False


def _magicfit_receipt_rejection_reason(receipt: Path, *, video: Path, slug: str) -> str:
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except Exception:
        return "magicfit_receipt_invalid"
    if not isinstance(payload, dict):
        return "magicfit_receipt_invalid"
    if str(payload.get("provider") or "").strip().lower() != "magicfit":
        return "magicfit_receipt_provider_mismatch"
    output_file = str(payload.get("output_file") or "").strip()
    if output_file:
        try:
            if Path(output_file).expanduser().resolve() != video.resolve():
                return "magicfit_receipt_output_mismatch"
        except OSError:
            return "magicfit_receipt_output_invalid"
    if not _receipt_target_matches_slug(payload, slug=slug):
        return "magicfit_receipt_target_mismatch"
    return ""


def _relative_file_sample(export_dir: Path, *, limit: int = 8) -> list[str]:
    if not export_dir.is_dir():
        return []
    rows: list[str] = []
    for path in sorted(export_dir.rglob("*")):
        if len(rows) >= limit:
            break
        if not path.is_file() or path.name == "README.propertyquarry-export.txt":
            continue
        try:
            rows.append(path.relative_to(export_dir).as_posix())
        except ValueError:
            rows.append(path.name)
    return rows


def _file_count(export_dir: Path) -> int:
    if not export_dir.is_dir():
        return 0
    return sum(
        1
        for path in export_dir.rglob("*")
        if path.is_file() and path.name != "README.propertyquarry-export.txt"
    )


def _entry_candidate_sample(export_dir: Path, *, limit: int = 6) -> list[str]:
    if not export_dir.is_dir():
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for entry in _entry_candidates(export_dir):
        if len(rows) >= limit:
            break
        try:
            relpath = entry.relative_to(export_dir).as_posix()
        except ValueError:
            relpath = entry.name
        if relpath not in seen:
            seen.add(relpath)
            rows.append(relpath)
    return rows


def _provider_drop_diagnostics(export_dir: Path, provider: str) -> dict[str, object]:
    if provider not in MARKERS_BY_PROVIDER:
        return {}
    marker_label = f"{provider}_runtime_marker"
    return {
        "file_count": _file_count(export_dir),
        "present_sample": _relative_file_sample(export_dir),
        "entry_candidates": _entry_candidate_sample(export_dir),
        "missing": [marker_label],
        "missing_markers": list(MARKERS_BY_PROVIDER[provider]),
    }


def _rejection_row(*, slug: str, provider: str, reason: str, export_dir: Path | None = None) -> dict[str, Any]:
    row = {
        "slug": slug,
        "provider": provider,
        "reason": reason,
        "action": REJECTION_ACTIONS.get(reason, "replace the dropped asset with a verified provider export and rerun discovery"),
        "drop_layout": PROVIDER_DROP_LAYOUTS.get(provider, "<drop>/<slug>/<provider>/"),
    }
    if export_dir is not None:
        row["drop_path"] = str(export_dir)
        row.update(_provider_drop_diagnostics(export_dir, provider))
    return row


def _repair_manifest_rows(rejected: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in rejected:
        provider = str(row.get("provider") or "").strip().lower()
        slug = str(row.get("slug") or "").strip()
        reason = str(row.get("reason") or "").strip()
        drop_path = str(row.get("drop_path") or "").strip()
        if not provider or not slug or not reason:
            continue
        command = ""
        if provider in {"3dvista", "pano2vr"} and drop_path:
            command = f"python /app/scripts/import_{provider}_export.py --slug {slug} --export-dir {drop_path}"
        elif provider == "krpano" and drop_path:
            command = f"python /app/scripts/import_krpano_walkable_scene.py --slug {slug} --panorama {drop_path}/panorama.jpg"
        elif provider == "magicfit" and drop_path:
            command = (
                "python /app/scripts/import_magicfit_walkthrough.py "
                f"--slug {slug} --video-path {drop_path}/magicfit-walkthrough.mp4 "
                f"--source-receipt {drop_path}/magicfit-receipt.json"
            )
        repair_row: dict[str, Any] = {
            "slug": slug,
            "provider": provider,
            "status": "waiting_for_verified_assets",
            "reason": reason,
            "drop_path": drop_path,
            "required_action": str(row.get("action") or "").strip(),
            "drop_layout": str(row.get("drop_layout") or "").strip(),
            "import_command_after_assets_arrive": command,
        }
        for key in ("file_count", "present_sample", "entry_candidates", "missing", "missing_markers"):
            if key in row:
                repair_row[key] = row[key]
        rows.append(repair_row)
    return rows


def _video_has_playable_stream(path: Path) -> bool:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False
    try:
        header = path.read_bytes()[:64]
    except OSError:
        return False
    if path.suffix.lower() in {".mp4", ".m4v", ".mov"} and b"ftyp" not in header[:32]:
        return False
    if path.suffix.lower() == ".webm" and not header.startswith(b"\x1aE\xdf\xa3"):
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        return False
    streams = [row for row in list(payload.get("streams") or []) if isinstance(row, dict)]
    if not any(str(row.get("codec_type") or "").strip().lower() == "video" for row in streams):
        return False
    durations: list[float] = []
    if isinstance(payload.get("format"), dict):
        with contextlib.suppress(Exception):
            durations.append(float(payload["format"].get("duration")))
    for row in streams:
        with contextlib.suppress(Exception):
            durations.append(float(row.get("duration")))
    return bool(durations and max(durations) > 0.0)


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
            rejected.append(_rejection_row(slug=slug, provider=provider, reason="tour_manifest_missing", export_dir=export_dir))
            continue
        if provider in {"3dvista", "pano2vr"}:
            entry, entry_relpath = _verified_entry(export_dir, provider)
            export_zip: Path | None = None
            if entry is None:
                export_zip, entry_relpath = _discover_export_zip(export_dir, provider)
            if entry is None and export_zip is None:
                rejected.append(_rejection_row(slug=slug, provider=provider, reason=f"{provider}_export_entry_unverified", export_dir=export_dir))
                continue
            row = {
                "slug": slug,
                "provider": provider,
                "export_dir": str(export_dir),
                "entry": entry_relpath,
            }
            if export_zip is not None:
                row["export_zip"] = str(export_zip)
            imports.append(row)
            continue
        if provider == "krpano":
            panorama = _discover_panorama(export_dir)
            cube_faces = _discover_cube_faces(export_dir)
            if panorama is None and len(cube_faces) != 6:
                rejected.append(_rejection_row(slug=slug, provider=provider, reason="krpano_assets_missing", export_dir=export_dir))
                continue
            row = {
                "slug": slug,
                "provider": provider,
                "asset_dir": str(export_dir),
            }
            if panorama is not None:
                row["panorama"] = str(panorama)
            elif len(cube_faces) == 6:
                for index, face in enumerate(cube_faces, start=1):
                    row[f"cube_face_{index}"] = str(face)
            imports.append(row)
            continue
        if provider == "magicfit":
            video = _discover_video(export_dir)
            receipt = _discover_receipt(export_dir)
            if video is None:
                rejected.append(_rejection_row(slug=slug, provider=provider, reason="magicfit_video_missing", export_dir=export_dir))
                continue
            if not _video_has_playable_stream(video):
                rejected.append(_rejection_row(slug=slug, provider=provider, reason="magicfit_video_unverified", export_dir=export_dir))
                continue
            if receipt is None:
                rejected.append(_rejection_row(slug=slug, provider=provider, reason="magicfit_receipt_missing", export_dir=export_dir))
                continue
            receipt_rejection_reason = _magicfit_receipt_rejection_reason(receipt, video=video, slug=slug)
            if receipt_rejection_reason:
                rejected.append(_rejection_row(slug=slug, provider=provider, reason=receipt_rejection_reason, export_dir=export_dir))
                continue
            imports.append(
                {
                    "slug": slug,
                    "provider": provider,
                    "asset_dir": str(export_dir),
                    "video": str(video),
                    "receipt": str(receipt),
                }
            )
            continue
        rejected.append(_rejection_row(slug=slug, provider=provider, reason="unsupported_provider", export_dir=export_dir))
    status = "ready" if imports else "blocked_no_verified_exports"
    repair_manifest = _repair_manifest_rows(rejected)
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "drop_dir": str(drop_dir.expanduser()),
        "public_tour_dir": str(public_root),
        "import_count": len(imports),
        "rejected_count": len(rejected),
        "imports": imports,
        "rejected": rejected,
        "repair_count": len(repair_manifest),
        "repair_manifest": repair_manifest,
        "import_manifest": {"imports": imports},
        "notes": [
            "This discovery step does not publish tours. It only emits rows accepted by the hardened import_property_tour_exports.py importer.",
            "3DVista and Pano2VR placeholders are rejected unless the entry or bundled local runtime files contain provider markers.",
            "krpano rows require a real panorama/cubemap candidate; MagicFit rows require a playable video stream and receipt candidate before import.",
            "Rejected rows are also emitted in repair_manifest so status/UI repair can show exact missing assets without treating placeholders as verified tours.",
        ],
    }


def _handoff_markdown_path(write_path: Path) -> Path:
    name = write_path.name
    if name.endswith(".json"):
        return write_path.with_name(f"{name[:-5]}.handoff.md")
    return write_path.with_suffix(f"{write_path.suffix}.handoff.md" if write_path.suffix else ".handoff.md")


def _tour_export_handoff_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# PropertyQuarry Tour Export Handoff",
        "",
        "Gold remains blocked until real provider assets are copied into the drop folders and pass the hardened importers.",
        "",
        f"- Discovery status: `{receipt.get('status')}`",
        f"- Drop root: `{receipt.get('drop_dir')}`",
        f"- Public tour root: `{receipt.get('public_tour_dir')}`",
        f"- Importable rows now: `{receipt.get('import_count')}`",
        f"- Rejected rows now: `{receipt.get('rejected_count')}`",
        "",
        "Do not copy placeholder HTML, flat photos, or fake videos. The importer must see real provider runtime markers or playable media.",
        "",
    ]
    rejected = [row for row in list(receipt.get("rejected") or []) if isinstance(row, dict)]
    if rejected:
        lines.extend(["## Rejected Drops", ""])
    for row in rejected:
        provider = str(row.get("provider") or "").strip()
        slug = str(row.get("slug") or "").strip()
        drop_path = str(row.get("drop_path") or "").strip()
        file_count = row.get("file_count")
        present_sample = ", ".join(str(item) for item in list(row.get("present_sample") or [])) or "none"
        entry_candidates = ", ".join(str(item) for item in list(row.get("entry_candidates") or [])) or "none"
        missing = ", ".join(str(item) for item in list(row.get("missing") or [])) or str(row.get("reason") or "")
        markers = ", ".join(str(item) for item in list(row.get("missing_markers") or [])) or "provider-specific runtime/media evidence"
        lines.extend(
            [
                f"### {provider} · {slug}",
                "",
                f"- Drop path: `{drop_path}`",
                f"- Reason: `{row.get('reason')}`",
                f"- Files found: `{file_count if file_count is not None else 'n/a'}`",
                f"- Present sample: `{present_sample}`",
                f"- Entry candidates: `{entry_candidates}`",
                f"- Missing: `{missing}`",
                f"- Required markers/evidence: `{markers}`",
                f"- Required action: {row.get('action')}",
                f"- Expected layout: `{row.get('drop_layout')}`",
                "",
            ]
        )
    repair_rows = [row for row in list(receipt.get("repair_manifest") or []) if isinstance(row, dict)]
    if repair_rows:
        lines.extend(["## Commands After Assets Arrive", ""])
        for row in repair_rows:
            command = str(row.get("import_command_after_assets_arrive") or "").strip()
            if command:
                lines.append(f"- `{command}`")
        lines.append("")
    lines.extend(
        [
            "After importing, rerun:",
            "",
            "`python /app/scripts/verify_property_tour_controls.py --tour-root /data/public_property_tours --require-all-provider-modes --summary-only`",
            "",
        ]
    )
    return "\n".join(lines)


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
    _handoff_markdown_path(write_path).write_text(_tour_export_handoff_markdown(receipt), encoding="utf-8")
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
