#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


DESKTOP_RELPATH = "walkthrough-desktop-1080p60.mp4"
MOBILE_RELPATH = "walkthrough-mobile-720p60.mp4"
SIDECAR_RELPATH = "tour.walkthrough.json"
CORE_GOLD_PROVIDER_KEY = "propertyquarry_core_gold"
LEGACY_WALKTHROUGH_RELPATH = "magicfit-walkthrough.mp4"
LEGACY_DESKTOP_RELPATH = "magicfit-walkthrough-desktop-1080p60.mp4"
LEGACY_MOBILE_RELPATH = "magicfit-walkthrough-mobile-720p60.mp4"
LEGACY_SIDECAR_RELPATH = "tour.magicfit.json"
LEGACY_MAGICFIT_ARTIFACT_NAMES = frozenset(
    {
        LEGACY_WALKTHROUGH_RELPATH,
        LEGACY_DESKTOP_RELPATH,
        LEGACY_MOBILE_RELPATH,
        LEGACY_SIDECAR_RELPATH,
    }
)
PROVIDER_CLAIM_FIELDS = frozenset(
    {
        "provider",
        "provider_key",
        "provider_backend_key",
        "video_provider",
        "video_provider_key",
        "video_provider_backend_key",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"json_object_required:{path}")
    return dict(payload)


def _manifest_walkthrough_path(bundle_dir: Path, manifest: dict[str, Any]) -> Path:
    raw_relpath = manifest.get("video_relpath")
    if (
        not isinstance(raw_relpath, str)
        or not raw_relpath
        or raw_relpath != raw_relpath.strip()
        or "\\" in raw_relpath
    ):
        raise RuntimeError("gold_walkthrough_rollback_video_relpath_invalid")
    relpath = PurePosixPath(raw_relpath)
    if (
        relpath.is_absolute()
        or relpath.as_posix() != raw_relpath
        or any(part in {"", ".", ".."} for part in relpath.parts)
    ):
        raise RuntimeError("gold_walkthrough_rollback_video_relpath_invalid")
    resolved_bundle = bundle_dir.resolve()
    resolved_video = (bundle_dir / Path(*relpath.parts)).resolve()
    try:
        resolved_video.relative_to(resolved_bundle)
    except ValueError as exc:
        raise RuntimeError(
            "gold_walkthrough_rollback_video_relpath_invalid"
        ) from exc
    return resolved_video


def _contains_legacy_magicfit_claim(
    value: object,
    *,
    field_name: str = "",
) -> bool:
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower()
            if key == "magicfit_import" or key.startswith("magicfit_"):
                return True
            if _contains_legacy_magicfit_claim(nested, field_name=key):
                return True
        return False
    if isinstance(value, list):
        return any(
            _contains_legacy_magicfit_claim(item, field_name=field_name)
            for item in value
        )
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if field_name in PROVIDER_CLAIM_FIELDS and normalized == "magicfit":
        return True
    return any(name in normalized for name in LEGACY_MAGICFIT_ARTIFACT_NAMES)


def _delivery_variant(receipt_path: Path, *, expected_key: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    receipt = _load_json(receipt_path)
    if str(receipt.get("contract_name") or "") != "propertyquarry.walkthrough_delivery_variants.v1":
        raise RuntimeError(f"delivery_receipt_contract_invalid:{expected_key}")
    if str(receipt.get("status") or "").lower() != "pass":
        raise RuntimeError(f"delivery_receipt_failed:{expected_key}")
    rows = [dict(row) for row in list(receipt.get("variants") or []) if isinstance(row, dict)]
    matches = [row for row in rows if str(row.get("key") or "").strip().lower() == expected_key]
    if len(matches) != 1:
        raise RuntimeError(f"delivery_variant_missing:{expected_key}")
    variant = matches[0]
    video_path = Path(str(variant.get("path") or "")).expanduser().resolve()
    if not video_path.is_file() or _sha256(video_path) != str(variant.get("sha256") or ""):
        raise RuntimeError(f"delivery_variant_hash_mismatch:{expected_key}")
    metadata = dict(variant.get("metadata") or {})
    expected_dimensions = (1920, 1080) if expected_key == "desktop" else (1280, 720)
    if (int(metadata.get("width") or 0), int(metadata.get("height") or 0)) != expected_dimensions:
        raise RuntimeError(f"delivery_variant_dimensions_invalid:{expected_key}")
    if str(metadata.get("avg_frame_rate") or "") != "60/1":
        raise RuntimeError(f"delivery_variant_fps_invalid:{expected_key}")
    if variant.get("full_decode_verified") is not True or variant.get("motion_interpolation_verified") is not True:
        raise RuntimeError(f"delivery_variant_unverified:{expected_key}")
    if dict(receipt.get("motion_interpolation") or {}).get("frame_duplication_only") is not False:
        raise RuntimeError(f"delivery_variant_interpolation_invalid:{expected_key}")
    return receipt, variant, video_path


def updated_public_assets(payload: dict[str, Any]) -> list[dict[str, object]]:
    replaced = {
        DESKTOP_RELPATH,
        MOBILE_RELPATH,
        LEGACY_WALKTHROUGH_RELPATH,
        LEGACY_DESKTOP_RELPATH,
        LEGACY_MOBILE_RELPATH,
        LEGACY_SIDECAR_RELPATH,
    }
    rows = [
        dict(row)
        for row in list(payload.get("public_assets") or [])
        if isinstance(row, dict)
        and str(row.get("path") or row.get("relpath") or row.get("asset_relpath") or "") not in replaced
    ]
    rows.extend(
        [
            {
                "path": DESKTOP_RELPATH,
                "privacy_class": "public",
                "role": "video",
                "mime_type": "video/mp4",
            },
            {
                "path": MOBILE_RELPATH,
                "privacy_class": "public",
                "role": "video_mobile",
                "mime_type": "video/mp4",
            },
        ]
    )
    return rows


def build_sidecar(
    *,
    source_receipt: dict[str, Any],
    source_receipt_path: Path,
    desktop_receipt_path: Path,
    desktop_variant: dict[str, Any],
    mobile_receipt_path: Path,
    mobile_variant: dict[str, Any],
    generated_at: str,
) -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.core_gold_walkthrough.v1",
        "provider": "PropertyQuarry Core Gold",
        "provider_key": CORE_GOLD_PROVIDER_KEY,
        "provider_backend_key": CORE_GOLD_PROVIDER_KEY,
        "status": "installed",
        "delivery_status": "installed",
        "launch_eligible": True,
        "composition": str(source_receipt.get("composition") or ""),
        "continuity_repair_status": str(source_receipt.get("continuity_repair_status") or ""),
        "continuity_repair_method": str(source_receipt.get("continuity_repair_method") or ""),
        "continuity_repair_cut_seconds": list(source_receipt.get("continuity_repair_cut_seconds") or []),
        "segment_count": int(source_receipt.get("segment_count") or 0),
        "route_labels": list(source_receipt.get("route_labels") or []),
        "covered_route_labels": list(source_receipt.get("covered_route_labels") or []),
        "boundary_checks": list(source_receipt.get("boundary_checks") or []),
        "transition_offsets_seconds": list(source_receipt.get("transition_offsets_seconds") or []),
        "transition_seconds": float(source_receipt.get("transition_seconds") or 0.0),
        "required_duration_seconds": float(source_receipt.get("required_duration_seconds") or 0.0),
        "duration_seconds": float(dict(desktop_variant.get("metadata") or {}).get("duration_seconds") or 0.0),
        "video_relpath": DESKTOP_RELPATH,
        "video_sha256": str(desktop_variant.get("sha256") or ""),
        "video_metadata": dict(desktop_variant.get("metadata") or {}),
        "video_mobile_relpath": MOBILE_RELPATH,
        "video_mobile_sha256": str(mobile_variant.get("sha256") or ""),
        "video_mobile_metadata": dict(mobile_variant.get("metadata") or {}),
        "motion_interpolation_verified": True,
        "frame_duplication_only": False,
        "full_decode_verified": True,
        "source_receipt_path": str(source_receipt_path),
        "source_receipt_sha256": _sha256(source_receipt_path),
        "desktop_delivery_receipt_path": str(desktop_receipt_path),
        "desktop_delivery_receipt_sha256": _sha256(desktop_receipt_path),
        "mobile_delivery_receipt_path": str(mobile_receipt_path),
        "mobile_delivery_receipt_sha256": _sha256(mobile_receipt_path),
        "generated_at": generated_at,
    }


def updated_manifest(
    payload: dict[str, Any],
    *,
    desktop_variant: dict[str, Any],
    mobile_variant: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    desktop_metadata = dict(desktop_variant.get("metadata") or {})
    mobile_metadata = dict(mobile_variant.get("metadata") or {})
    provider_neutral_payload = {
        key: value
        for key, value in payload.items()
        if key != "magicfit_import" and not str(key).startswith("magicfit_")
    }
    updated = {
        **provider_neutral_payload,
        "video_relpath": DESKTOP_RELPATH,
        "video_mobile_relpath": MOBILE_RELPATH,
        "flythrough_video_relpath": DESKTOP_RELPATH,
        "video_sidecar_relpath": SIDECAR_RELPATH,
        "video_provider": CORE_GOLD_PROVIDER_KEY,
        "video_provider_key": CORE_GOLD_PROVIDER_KEY,
        "video_coverage_proof": "boundary_verified_frame_continuation",
        "public_assets": updated_public_assets(payload),
        "core_gold_walkthrough": {
            "source": "continuity_repaired_motion_interpolated_walkthrough",
            "installed_at": generated_at,
            "desktop_target_relpath": DESKTOP_RELPATH,
            "desktop_sha256": str(desktop_variant.get("sha256") or ""),
            "desktop_size_bytes": int(desktop_metadata.get("size_bytes") or 0),
            "desktop_frame_rate": str(desktop_metadata.get("avg_frame_rate") or ""),
            "mobile_target_relpath": MOBILE_RELPATH,
            "mobile_sha256": str(mobile_variant.get("sha256") or ""),
            "mobile_size_bytes": int(mobile_metadata.get("size_bytes") or 0),
            "mobile_frame_rate": str(mobile_metadata.get("avg_frame_rate") or ""),
            "continuity_repair_verified": True,
            "motion_interpolation_verified": True,
            "frame_duplication_only": False,
        },
    }
    if _contains_legacy_magicfit_claim(updated):
        raise RuntimeError("core_gold_manifest_provider_claims_remain")
    return updated


def _atomic_copy(source: Path, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", dir=destination.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        dir=path.parent,
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def install(
    *,
    bundle_dir: Path,
    source_receipt_path: Path,
    desktop_receipt_path: Path,
    mobile_receipt_path: Path,
    rollback_receipt_path: Path,
    install_receipt_path: Path,
) -> dict[str, object]:
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise RuntimeError("gold_walkthrough_manifest_missing")
    manifest = _load_json(manifest_path)
    rollback = _load_json(rollback_receipt_path)
    if str(rollback.get("status") or "").lower() != "pass":
        raise RuntimeError("gold_walkthrough_rollback_unverified")
    expected_manifest_sha = str(dict(rollback.get("manifest") or {}).get("sha256") or "")
    if _sha256(manifest_path) != expected_manifest_sha:
        raise RuntimeError("gold_walkthrough_manifest_changed_since_rollback_snapshot")
    old_video_path = _manifest_walkthrough_path(bundle_dir, manifest)
    expected_old_video_sha = str(dict(rollback.get("walkthrough") or {}).get("sha256") or "")
    if not old_video_path.is_file() or _sha256(old_video_path) != expected_old_video_sha:
        raise RuntimeError("gold_walkthrough_rollback_video_mismatch")

    source_receipt = _load_json(source_receipt_path)
    if str(source_receipt.get("continuity_repair_status") or "").lower() != "pass":
        raise RuntimeError("gold_walkthrough_source_continuity_unverified")
    desktop_receipt, desktop_variant, desktop_path = _delivery_variant(
        desktop_receipt_path,
        expected_key="desktop",
    )
    mobile_receipt, mobile_variant, mobile_path = _delivery_variant(
        mobile_receipt_path,
        expected_key="mobile",
    )
    source_sha = str(source_receipt.get("video_sha256") or "")
    if str(desktop_receipt.get("source_video_sha256") or "") != source_sha:
        raise RuntimeError("gold_walkthrough_desktop_source_mismatch")
    if str(mobile_receipt.get("source_video_sha256") or "") != source_sha:
        raise RuntimeError("gold_walkthrough_mobile_source_mismatch")

    generated_at = _utc_now()
    sidecar = build_sidecar(
        source_receipt=source_receipt,
        source_receipt_path=source_receipt_path,
        desktop_receipt_path=desktop_receipt_path,
        desktop_variant=desktop_variant,
        mobile_receipt_path=mobile_receipt_path,
        mobile_variant=mobile_variant,
        generated_at=generated_at,
    )
    updated = updated_manifest(
        manifest,
        desktop_variant=desktop_variant,
        mobile_variant=mobile_variant,
        generated_at=generated_at,
    )

    _atomic_copy(desktop_path, bundle_dir / DESKTOP_RELPATH)
    _atomic_copy(mobile_path, bundle_dir / MOBILE_RELPATH)
    _atomic_write_json(bundle_dir / SIDECAR_RELPATH, sidecar)
    _atomic_write_json(manifest_path, updated)
    receipt: dict[str, object] = {
        "contract_name": "propertyquarry.core_gold_walkthrough_install.v1",
        "status": "pass",
        "generated_at": generated_at,
        "bundle_dir": str(bundle_dir),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "sidecar_path": str(bundle_dir / SIDECAR_RELPATH),
        "sidecar_sha256": _sha256(bundle_dir / SIDECAR_RELPATH),
        "desktop_path": str(bundle_dir / DESKTOP_RELPATH),
        "desktop_sha256": _sha256(bundle_dir / DESKTOP_RELPATH),
        "mobile_path": str(bundle_dir / MOBILE_RELPATH),
        "mobile_sha256": _sha256(bundle_dir / MOBILE_RELPATH),
        "rollback_receipt_path": str(rollback_receipt_path),
        "rollback_receipt_sha256": _sha256(rollback_receipt_path),
    }
    _atomic_write_json(install_receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically install the provider-independent PropertyQuarry Core "
            "Gold walkthrough."
        )
    )
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--source-receipt", required=True)
    parser.add_argument("--desktop-receipt", required=True)
    parser.add_argument("--mobile-receipt", required=True)
    parser.add_argument("--rollback-receipt", required=True)
    parser.add_argument("--write", required=True)
    args = parser.parse_args()
    receipt = install(
        bundle_dir=Path(args.bundle_dir).expanduser().resolve(),
        source_receipt_path=Path(args.source_receipt).expanduser().resolve(),
        desktop_receipt_path=Path(args.desktop_receipt).expanduser().resolve(),
        mobile_receipt_path=Path(args.mobile_receipt).expanduser().resolve(),
        rollback_receipt_path=Path(args.rollback_receipt).expanduser().resolve(),
        install_receipt_path=Path(args.write).expanduser().resolve(),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
