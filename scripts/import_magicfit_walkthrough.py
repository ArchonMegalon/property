#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from property_tour_host_safety import (
        TourHostSafetyError,
        bounded_env_int,
        bounded_lane_lock,
        require_bounded_file,
        require_free_disk,
        tour_asset_max_bytes,
        tour_manifest_max_bytes,
    )
except ModuleNotFoundError:
    from scripts.property_tour_host_safety import (
        TourHostSafetyError,
        bounded_env_int,
        bounded_lane_lock,
        require_bounded_file,
        require_free_disk,
        tour_asset_max_bytes,
        tour_manifest_max_bytes,
    )


PUBLIC_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}
MAGICFIT_HOSTED_VIDEO_RE = re.compile(
    r"^https://(?:cdn\.pushowl\.com|media\.powlcdn\.com)/magicfit/[^\"'\s<>]+?\.(?:mp4|webm)(?:[?#][^\"'\s<>]*)?$",
    re.IGNORECASE,
)
PENDING_POINTER_RELPATH = "tour.magicfit.pending.json"
STAGING_ROOT_RELPATH = ".magicfit-staging"
DELIVERIES_ROOT_RELPATH = ".magicfit-deliveries"
ACTIVATION_LOCK_RELPATH = ".magicfit-activation.lock"


class _DuplicateJsonKey(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"nonfinite:{value}")


def _public_tour_dir() -> Path:
    return Path(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours").expanduser().resolve()


def _safe_relpath(value: object) -> str:
    """Return only an already-canonical, filesystem-safe relative path."""

    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    if "\\" in value or value.startswith("/"):
        return ""
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return ""
    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        return ""
    if PurePosixPath(value).as_posix() != value:
        return ""
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_bytes(path: Path, body: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
        path.chmod(mode)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


@contextlib.contextmanager
def _activation_lock(bundle_dir: Path):
    lock_path = bundle_dir / ACTIVATION_LOCK_RELPATH
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SystemExit("magicfit_activation_lock_invalid")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _private_stage_directory(bundle_dir: Path, relpath: str) -> Path:
    bundle_root = bundle_dir.resolve()
    target = bundle_dir / relpath
    target.mkdir(parents=True, exist_ok=True)
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"magicfit_staging_path_invalid:{type(exc).__name__}") from exc
    if bundle_root not in resolved.parents or target.is_symlink() or not target.is_dir():
        raise SystemExit("magicfit_staging_path_invalid")
    current = target
    while current != bundle_dir:
        if current.is_symlink() or not current.is_dir():
            raise SystemExit("magicfit_staging_path_invalid")
        current.chmod(0o700)
        current = current.parent
    return resolved


def _stage_video(source: Path, target: Path, *, expected_sha256: str) -> None:
    if target.is_file():
        if target.is_symlink() or _sha256(target) != expected_sha256:
            raise SystemExit("magicfit_staged_video_conflict")
        target.chmod(0o600)
        return
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected_sha256:
            raise SystemExit("magicfit_staged_video_digest_mismatch")
        temporary.chmod(0o600)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(target)
        target.chmod(0o600)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _digest_bound_video_relpath(requested_relpath: str, video_sha256: str) -> str:
    requested = PurePosixPath(requested_relpath)
    suffix = requested.suffix.lower()
    filename = f"{requested.stem}.{video_sha256}{suffix}"
    # Accepted media lives in a dedicated public subtree.  This avoids chmod or
    # replacement of an operator-selected directory containing unrelated tour
    # assets while retaining the requested basename for diagnostics.
    final_path = (PurePosixPath("magicfit-media") / filename).as_posix()
    if len(final_path) > 768 or any(len(part) > 255 for part in final_path.split("/")):
        raise SystemExit("invalid_magicfit_target")
    return final_path


def _video_is_playable(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in PUBLIC_VIDEO_EXTENSIONS:
        return False
    try:
        with path.open("rb") as handle:
            header = handle.read(64)
    except OSError:
        return False
    if len(header) < 12:
        return False
    signature_ok = False
    if suffix in {".mp4", ".m4v", ".mov"}:
        signature_ok = b"ftyp" in header[:32]
    elif suffix == ".webm":
        signature_ok = header.startswith(b"\x1aE\xdf\xa3")
    if not signature_ok:
        return False
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        result = subprocess.run(
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
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except Exception:
        return False
    streams = [row for row in list(payload.get("streams") or []) if isinstance(row, dict)]
    if not any(str(row.get("codec_type") or "").strip().lower() == "video" for row in streams):
        return False
    durations: list[float] = []
    if isinstance(payload.get("format"), dict):
        try:
            durations.append(float(payload["format"].get("duration")))
        except Exception:
            pass
    for row in streams:
        try:
            durations.append(float(row.get("duration")))
        except Exception:
            pass
    return bool(durations and max(durations) > 0.0)


def _receipt_target_matches_slug(payload: dict[str, object], *, slug: str) -> bool:
    expected = slug if isinstance(slug, str) and slug == slug.strip() else ""
    if not expected:
        return False
    for key in ("target_slug", "tour_slug", "property_slug", "slug"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() == expected:
            return True
    for key in ("property_url", "tour_url", "hosted_url", "public_url"):
        raw_value = payload.get(key)
        value = raw_value.strip().rstrip("/") if isinstance(raw_value, str) else ""
        if value and value.rsplit("/", 1)[-1] == expected:
            return True
    return False


def _load_magicfit_receipt(
    path_value: str,
    *,
    source: Path,
    slug: str,
    allow_unreceipted: bool,
) -> tuple[dict[str, object], str, str]:
    if allow_unreceipted:
        return {}, "", ""
    receipt_path = Path(path_value or "").expanduser().resolve()
    if not receipt_path.is_file():
        raise SystemExit("magicfit_receipt_missing")
    try:
        require_bounded_file(
            receipt_path,
            reason_prefix="magicfit_receipt",
            maximum_bytes=bounded_env_int(
                "PROPERTYQUARRY_MAGICFIT_RECEIPT_MAX_BYTES",
                default=1024 * 1024,
                minimum=1_024,
                maximum=8 * 1024 * 1024,
            ),
        )
        receipt_bytes = receipt_path.read_bytes()
        payload = json.loads(
            receipt_bytes.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_nonfinite_json,
        )
    except TourHostSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    except Exception as exc:
        raise SystemExit(f"magicfit_receipt_invalid:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("magicfit_receipt_invalid")
    provider_value = payload.get("provider")
    provider = provider_value.strip().lower() if isinstance(provider_value, str) else ""
    if provider != "magicfit":
        raise SystemExit("magicfit_receipt_provider_mismatch")
    output_file_value = payload.get("output_file")
    if "output_file" in payload and not isinstance(output_file_value, str):
        raise SystemExit("magicfit_receipt_output_invalid:type")
    output_file = output_file_value.strip() if isinstance(output_file_value, str) else ""
    if output_file:
        try:
            if Path(output_file).expanduser().resolve() != source:
                raise SystemExit("magicfit_receipt_output_mismatch")
        except OSError as exc:
            raise SystemExit(f"magicfit_receipt_output_invalid:{type(exc).__name__}") from exc
    if not _receipt_target_matches_slug(payload, slug=slug):
        raise SystemExit("magicfit_receipt_target_mismatch")
    backend_value = payload.get("provider_backend_key")
    backend = backend_value.strip().lower() if isinstance(backend_value, str) else ""
    if backend != "magicfit":
        raise SystemExit("magicfit_receipt_backend_mismatch")
    render_value = payload.get("render_status")
    render_status = render_value.strip().lower() if isinstance(render_value, str) else ""
    if render_status not in {"completed", "rendered", "success", "succeeded"}:
        raise SystemExit("magicfit_receipt_render_incomplete")
    hosted_value = payload.get("hosted_walkthrough_video_url")
    output_url_value = payload.get("video_output_url")
    if (
        "hosted_walkthrough_video_url" in payload
        and not isinstance(hosted_value, str)
    ) or ("video_output_url" in payload and not isinstance(output_url_value, str)):
        raise SystemExit("magicfit_receipt_hosted_video_unverified")
    hosted_video_url = (
        hosted_value.strip()
        if isinstance(hosted_value, str) and hosted_value.strip()
        else output_url_value.strip()
        if isinstance(output_url_value, str)
        else ""
    )
    if not MAGICFIT_HOSTED_VIDEO_RE.match(hosted_video_url):
        raise SystemExit("magicfit_receipt_hosted_video_unverified")
    return payload, str(receipt_path), hashlib.sha256(receipt_bytes).hexdigest()


def _coverage_proof_from_receipt(payload: dict[str, object]) -> dict[str, object]:
    for key in (
        "walkthrough_coverage_proof",
        "magicfit_walkthrough_coverage",
        "walkthrough_quality_receipt",
        "coverage_proof",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _main_unlocked() -> int:
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
    try:
        require_bounded_file(
            source,
            reason_prefix="magicfit_video",
            maximum_bytes=tour_asset_max_bytes(),
        )
    except TourHostSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    if not _video_is_playable(source):
        raise SystemExit("magicfit_video_unverified")
    receipt_payload, _receipt_path, source_receipt_sha256 = _load_magicfit_receipt(
        args.source_receipt,
        source=source,
        slug=slug,
        allow_unreceipted=bool(args.allow_unreceipted_test_asset),
    )

    public_root = _public_tour_dir()
    bundle_dir = public_root / slug
    try:
        bundle_root = bundle_dir.resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"tour_bundle_invalid:{type(exc).__name__}") from exc
    if (
        public_root not in bundle_root.parents
        or bundle_dir.is_symlink()
        or not bundle_dir.is_dir()
    ):
        raise SystemExit("tour_bundle_invalid")
    manifest_path = bundle_dir / "tour.json"
    if not manifest_path.is_file():
        raise SystemExit("tour_manifest_missing")
    try:
        require_bounded_file(
            manifest_path,
            reason_prefix="tour_manifest",
            maximum_bytes=tour_manifest_max_bytes(),
        )
    except TourHostSafetyError as exc:
        raise SystemExit(str(exc)) from exc

    if args.target_relpath:
        target_relpath = _safe_relpath(args.target_relpath)
        if not target_relpath:
            raise SystemExit("invalid_magicfit_target")
    else:
        target_relpath = f"magicfit-walkthrough{source.suffix.lower()}"
    if PurePosixPath(target_relpath).suffix.lower() not in PUBLIC_VIDEO_EXTENSIONS:
        raise SystemExit("invalid_magicfit_target")
    requested_target = (bundle_dir / target_relpath).resolve()
    if bundle_dir.resolve() not in requested_target.parents:
        raise SystemExit("invalid_magicfit_target")
    video_sha256 = _sha256(source)
    final_video_relpath = _digest_bound_video_relpath(target_relpath, video_sha256)
    imported_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    with _activation_lock(bundle_dir):
        try:
            manifest_bytes = manifest_path.read_bytes()
            payload = json.loads(
                manifest_bytes.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_nonfinite_json,
            )
        except Exception as exc:
            raise SystemExit(f"invalid_tour_manifest:{type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise SystemExit("invalid_tour_manifest")
        if payload.get("slug") not in {None, slug}:
            raise SystemExit("invalid_tour_manifest_slug")

        base_manifest_sha256 = _sha256_bytes(manifest_bytes)
        delivery_digest = _sha256_bytes(
            (
                f"{video_sha256}\n{source_receipt_sha256}\n"
                f"{final_video_relpath}\n{base_manifest_sha256}\n"
            ).encode("utf-8")
        )
        stage_dir_relpath = f"{STAGING_ROOT_RELPATH}/{delivery_digest}"
        stage_dir = _private_stage_directory(bundle_dir, stage_dir_relpath)
        staged_video_relpath = f"{stage_dir_relpath}/video{source.suffix.lower()}"
        staged_video_path = bundle_dir / staged_video_relpath
        try:
            require_free_disk(
                stage_dir,
                reason_prefix="magicfit_import",
                expected_write_bytes=int(source.stat(follow_symlinks=False).st_size),
            )
        except TourHostSafetyError as exc:
            raise SystemExit(str(exc)) from exc
        _stage_video(source, staged_video_path, expected_sha256=video_sha256)

        accepted_sidecar_relpath = (
            f"{DELIVERIES_ROOT_RELPATH}/{delivery_digest}.json"
        )
        staged_manifest_relpath = f"{stage_dir_relpath}/tour.json"
        staged_manifest_path = bundle_dir / staged_manifest_relpath

        # Build the exact future public manifest in private staging.  It is not
        # reachable through the public asset allowlist, and tour.json remains
        # byte-for-byte unchanged until acceptance commits this file last.
        activated_payload = dict(payload)
        activated_payload["video_provider"] = "magicfit"
        activated_payload["video_provider_backend_key"] = "magicfit"
        activated_payload["video_relpath"] = final_video_relpath
        activated_payload["video_sidecar_relpath"] = accepted_sidecar_relpath
        magicfit_import: dict[str, object] = {
            "source": "magicfit_rendered_walkthrough",
            "provider_backend_key": "magicfit",
            "proof_status": "delivery_accepted",
            "imported_at": imported_at,
            "requested_target_relpath": target_relpath,
            "target_relpath": final_video_relpath,
            "sha256": video_sha256,
            "size_bytes": source.stat().st_size,
            "source_receipt_sha256": source_receipt_sha256,
            "delivery_sidecar_relpath": accepted_sidecar_relpath,
        }
        coverage_proof = _coverage_proof_from_receipt(receipt_payload)
        if coverage_proof:
            activated_payload["video_coverage_proof"] = "route_coverage_verified"
            activated_payload["walkthrough_coverage_proof"] = coverage_proof
            magicfit_import["coverage_proof"] = coverage_proof
        else:
            activated_payload["video_coverage_proof"] = "provider_render_verified"
            activated_payload.pop("walkthrough_coverage_proof", None)
        activated_payload["magicfit_import"] = magicfit_import
        staged_manifest_bytes = _json_bytes(activated_payload)
        _atomic_write_bytes(staged_manifest_path, staged_manifest_bytes, mode=0o600)

        pending_delivery = {
            "contract_name": "propertyquarry.magicfit_delivery_acceptance.v1",
            "provider": "magicfit",
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "render_status": "completed",
            "status": "rendered_pending_delivery_acceptance",
            "acceptance_status": "pending",
            "launch_eligible": False,
            "video_relpath": final_video_relpath,
            "video_sha256": video_sha256,
            "source_receipt_sha256": source_receipt_sha256,
            "generated_at": imported_at,
            "base_manifest_sha256": base_manifest_sha256,
            "staged_video_relpath": staged_video_relpath,
            "staged_manifest_relpath": staged_manifest_relpath,
            "staged_manifest_sha256": _sha256_bytes(staged_manifest_bytes),
            "accepted_sidecar_relpath": accepted_sidecar_relpath,
        }
        # The pointer is the import commit point.  A crash before this replace
        # leaves any previous pending delivery selected; a crash afterwards
        # selects only a completely written, digest-bound staging directory.
        _atomic_write_bytes(
            bundle_dir / PENDING_POINTER_RELPATH,
            _json_bytes(pending_delivery),
            mode=0o600,
        )
    print(
        json.dumps(
            {
                "status": "staged_pending_delivery_acceptance",
                "slug": slug,
                "video_relpath_after_acceptance": final_video_relpath,
                "public_video_url_after_acceptance": (
                    f"/tours/files/{slug}/{final_video_relpath}"
                ),
                "provider": "magicfit",
                "provider_backend_key": "magicfit",
                "acceptance_status": "pending",
                "launch_eligible": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    try:
        with bounded_lane_lock("magicfit-import"):
            return _main_unlocked()
    except TourHostSafetyError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
