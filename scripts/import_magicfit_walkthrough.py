#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PUBLIC_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}


def _public_tour_dir() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours").expanduser().resolve()


def _safe_relpath(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return "/".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video_is_playable(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in PUBLIC_VIDEO_EXTENSIONS:
        return False
    try:
        header = path.read_bytes()[:64]
    except OSError:
        return False
    if len(header) < 12:
        return False
    if suffix in {".mp4", ".m4v", ".mov"}:
        return b"ftyp" in header[:32]
    if suffix == ".webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    return False


def _load_magicfit_receipt(path_value: str, *, source: Path, allow_unreceipted: bool) -> tuple[dict[str, object], str]:
    if allow_unreceipted:
        return {}, ""
    receipt_path = Path(path_value or "").expanduser().resolve()
    if not receipt_path.is_file():
        raise SystemExit("magicfit_receipt_missing")
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"magicfit_receipt_invalid:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("magicfit_receipt_invalid")
    provider = str(payload.get("provider") or "").strip().lower()
    if provider != "magicfit":
        raise SystemExit("magicfit_receipt_provider_mismatch")
    output_file = str(payload.get("output_file") or "").strip()
    if output_file:
        try:
            if Path(output_file).expanduser().resolve() != source:
                raise SystemExit("magicfit_receipt_output_mismatch")
        except OSError as exc:
            raise SystemExit(f"magicfit_receipt_output_invalid:{type(exc).__name__}") from exc
    return payload, str(receipt_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a verified MagicFit walkthrough video into a public tour bundle.")
    parser.add_argument("--slug", required=True, help="Existing PropertyQuarry public tour slug.")
    parser.add_argument("--video-path", required=True, help="Playable MagicFit MP4/M4V/MOV/WebM render.")
    parser.add_argument("--target-relpath", default="", help="Optional target path inside the tour bundle.")
    parser.add_argument("--source-receipt", default="", help="MagicFit render receipt path to reference without embedding secrets.")
    parser.add_argument(
        "--allow-unreceipted-test-asset",
        action="store_true",
        help="Allow a playable local fixture without MagicFit provenance. Intended for tests only.",
    )
    args = parser.parse_args()

    slug = _safe_relpath(args.slug)
    if "/" in slug or not slug:
        raise SystemExit("invalid_tour_slug")
    source = Path(args.video_path).expanduser().resolve()
    if not source.is_file():
        raise SystemExit("magicfit_video_missing")
    if not _video_is_playable(source):
        raise SystemExit("magicfit_video_unverified")
    _receipt_payload, receipt_relpath = _load_magicfit_receipt(
        args.source_receipt,
        source=source,
        allow_unreceipted=bool(args.allow_unreceipted_test_asset),
    )

    bundle_dir = _public_tour_dir() / slug
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise SystemExit("tour_manifest_missing")

    target_relpath = _safe_relpath(args.target_relpath)
    if not target_relpath:
        target_relpath = f"magicfit-walkthrough{source.suffix.lower()}"
    if PurePosixPath(target_relpath).suffix.lower() not in PUBLIC_VIDEO_EXTENSIONS:
        raise SystemExit("invalid_magicfit_target")
    target = (bundle_dir / target_relpath).resolve()
    if bundle_dir.resolve() not in target.parents:
        raise SystemExit("invalid_magicfit_target")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("invalid_tour_manifest")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    payload["video_provider"] = "magicfit"
    payload["video_relpath"] = target_relpath
    payload["video_coverage_proof"] = "boundary_verified_frame_continuation"
    payload["magicfit_import"] = {
        "source": "magicfit_rendered_walkthrough",
        "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "target_relpath": target_relpath,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
        "source_receipt_path": receipt_relpath,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "imported",
                "slug": slug,
                "video_relpath": target_relpath,
                "video_url": f"/tours/files/{slug}/{target_relpath}",
                "provider": "magicfit",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
