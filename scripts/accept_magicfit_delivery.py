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
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


DELIVERY_CONTRACT = "propertyquarry.magicfit_delivery_acceptance.v1"
REVIEW_CONTRACT = "propertyquarry.magicfit_delivery_review.v1"
EVIDENCE_CONTRACT = "propertyquarry.magicfit_e2e_evidence.v1"
BROWSER_RECEIPT_CONTRACT = "propertyquarry.magicfit_browser_playback.v1"
PUBLIC_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
UTC_TIMESTAMP_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|\+00:00)\Z"
)
MAX_FUTURE_SKEW = timedelta(minutes=5)
PENDING_POINTER_RELPATH = "tour.magicfit.pending.json"
ACTIVATION_LOCK_RELPATH = ".magicfit-activation.lock"
PENDING_SIDECAR_FIELDS = frozenset(
    {
        "contract_name",
        "provider",
        "provider_key",
        "provider_backend_key",
        "render_status",
        "status",
        "acceptance_status",
        "launch_eligible",
        "video_relpath",
        "video_sha256",
        "source_receipt_sha256",
        "generated_at",
        "base_manifest_sha256",
        "staged_video_relpath",
        "staged_manifest_relpath",
        "staged_manifest_sha256",
        "accepted_sidecar_relpath",
    }
)
EVIDENCE_FIELDS = frozenset(
    {
        "schema",
        "status",
        "provider",
        "target_slug",
        "observed_at",
        "source_receipt_sha256",
        "video",
        "checklist",
        "artifacts",
    }
)
EVIDENCE_VIDEO_FIELDS = frozenset({"sha256", "size_bytes", "duration_seconds"})
EVIDENCE_ARTIFACT_FIELDS = frozenset(
    {"contact_sheet_sha256", "browser_receipt_sha256"}
)
BROWSER_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "status",
        "provider",
        "target_slug",
        "observed_at",
        "route",
        "http_status",
        "video_sha256",
        "duration_seconds",
        "final_current_time",
        "playback_to_end",
        "video_error",
        "console_errors",
        "request_failures",
        "benign_request_aborts",
        "bad_responses",
    }
)
REVIEW_CHECKS = frozenset(
    {
        "playback_to_end",
        "continuous_walkthrough",
        "no_visible_rotation_jump",
        "intended_property_and_scope",
        "no_sensitive_or_trial_branding",
    }
)


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


def _load_json_bytes(path: Path, *, error: str) -> tuple[dict[str, Any], bytes]:
    try:
        body = path.read_bytes()
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_nonfinite_json,
        )
    except Exception as exc:
        raise SystemExit(f"{error}:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(error)
    return dict(payload), body


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


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


def _activation_failpoint(name: str) -> None:
    # Test-only denial injection proves each crash boundary.  The guard keeps
    # production operators from accidentally enabling a fault through ambient
    # configuration; it can only make tests fail closed.
    if not os.getenv("PYTEST_CURRENT_TEST"):
        return
    if os.getenv("PROPERTYQUARRY_MAGICFIT_ACTIVATION_FAILPOINT") == name:
        raise SystemExit(f"magicfit_activation_test_failpoint:{name}")


def _valid_sha256(value: object) -> str:
    return value if isinstance(value, str) and SHA256_RE.fullmatch(value) else ""


def _canonical_relpath(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    if value.startswith("/") or "\\" in value:
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
    return value if PurePosixPath(value).as_posix() == value else ""


def _strict_utc(value: object, *, require_z: bool) -> datetime | None:
    if not isinstance(value, str) or UTC_TIMESTAMP_RE.fullmatch(value) is None:
        return None
    if require_z and not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _local_file(bundle_dir: Path, relpath: str) -> Path | None:
    canonical = _canonical_relpath(relpath)
    if not canonical:
        return None
    try:
        bundle_root = bundle_dir.resolve()
        lexical = bundle_dir
        for part in PurePosixPath(canonical).parts:
            lexical = lexical / part
            if lexical.is_symlink():
                return None
        candidate = lexical.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if bundle_root not in candidate.parents or not candidate.is_file():
        return None
    return lexical


def _video_probe(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix not in PUBLIC_VIDEO_EXTENSIONS:
        raise SystemExit("magicfit_acceptance_video_extension_invalid")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("magicfit_acceptance_ffprobe_missing")
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,duration:format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        raise SystemExit(f"magicfit_acceptance_video_probe_failed:{type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise SystemExit("magicfit_acceptance_video_probe_failed")
    try:
        payload = json.loads(completed.stdout or "{}")
        streams = [row for row in list(payload.get("streams") or []) if isinstance(row, dict)]
        duration = float(dict(payload.get("format") or {}).get("duration") or 0.0)
        size_bytes = int(dict(payload.get("format") or {}).get("size") or 0)
    except Exception as exc:
        raise SystemExit(f"magicfit_acceptance_video_probe_invalid:{type(exc).__name__}") from exc
    if not any(str(row.get("codec_type") or "").lower() == "video" for row in streams):
        raise SystemExit("magicfit_acceptance_video_stream_missing")
    if duration <= 0.0 or size_bytes != path.stat().st_size:
        raise SystemExit("magicfit_acceptance_video_probe_invalid")
    return {"duration_seconds": duration, "size_bytes": size_bytes}


def _source_receipt_valid(payload: dict[str, Any], *, slug: str) -> bool:
    if str(payload.get("provider") or "").strip().lower() != "magicfit":
        return False
    if str(payload.get("provider_backend_key") or "").strip().lower() != "magicfit":
        return False
    if str(payload.get("render_status") or "").strip().lower() not in {
        "completed",
        "rendered",
        "success",
        "succeeded",
    }:
        return False
    return any(
        isinstance(payload.get(key), str) and payload[key].strip() == slug
        for key in ("target_slug", "tour_slug", "property_slug", "slug")
    )


def _validate_evidence(
    payload: dict[str, Any],
    *,
    slug: str,
    generated_at: datetime,
    video_sha256: str,
    video_probe: dict[str, object],
    source_receipt_sha256: str,
    contact_sheet_sha256: str,
    browser_receipt_sha256: str,
) -> dict[str, bool]:
    if set(payload) != EVIDENCE_FIELDS:
        raise SystemExit("magicfit_acceptance_evidence_contract_invalid")
    if (
        payload.get("schema") != EVIDENCE_CONTRACT
        or payload.get("status") != "pass"
        or payload.get("provider") != "magicfit"
        or payload.get("target_slug") != slug
        or payload.get("source_receipt_sha256") != source_receipt_sha256
    ):
        raise SystemExit("magicfit_acceptance_evidence_contract_invalid")
    observed_at = _strict_utc(payload.get("observed_at"), require_z=True)
    now = datetime.now(timezone.utc)
    if (
        observed_at is None
        or observed_at < generated_at
        or observed_at > now + MAX_FUTURE_SKEW
    ):
        raise SystemExit("magicfit_acceptance_evidence_timestamp_invalid")

    video = payload.get("video")
    if not isinstance(video, dict) or set(video) != EVIDENCE_VIDEO_FIELDS:
        raise SystemExit("magicfit_acceptance_evidence_video_invalid")
    try:
        evidence_size = int(video.get("size_bytes"))
        evidence_duration = float(video.get("duration_seconds"))
    except (TypeError, ValueError):
        raise SystemExit("magicfit_acceptance_evidence_video_invalid")
    if (
        video.get("sha256") != video_sha256
        or evidence_size != int(video_probe["size_bytes"])
        or evidence_duration <= 0.0
        or abs(evidence_duration - float(video_probe["duration_seconds"])) > 0.1
    ):
        raise SystemExit("magicfit_acceptance_evidence_video_mismatch")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != EVIDENCE_ARTIFACT_FIELDS:
        raise SystemExit("magicfit_acceptance_evidence_artifacts_invalid")
    if (
        artifacts.get("contact_sheet_sha256") != contact_sheet_sha256
        or artifacts.get("browser_receipt_sha256") != browser_receipt_sha256
    ):
        raise SystemExit("magicfit_acceptance_evidence_artifacts_mismatch")

    checklist = payload.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != REVIEW_CHECKS:
        raise SystemExit("magicfit_acceptance_evidence_checklist_invalid")
    if not all(checklist.get(key) is True for key in REVIEW_CHECKS):
        raise SystemExit("magicfit_acceptance_evidence_checklist_failed")
    return {key: True for key in sorted(REVIEW_CHECKS)}


def _validate_browser_receipt(
    payload: dict[str, Any],
    *,
    slug: str,
    generated_at: datetime,
    video_sha256: str,
    video_duration: float,
) -> None:
    if set(payload) != BROWSER_RECEIPT_FIELDS:
        raise SystemExit("magicfit_acceptance_browser_receipt_contract_invalid")
    observed_at = _strict_utc(payload.get("observed_at"), require_z=True)
    now = datetime.now(timezone.utc)
    try:
        duration = float(payload.get("duration_seconds"))
        final_current_time = float(payload.get("final_current_time"))
    except (TypeError, ValueError):
        raise SystemExit("magicfit_acceptance_browser_receipt_contract_invalid")
    benign_request_aborts = payload.get("benign_request_aborts")
    if not isinstance(benign_request_aborts, list) or len(benign_request_aborts) > 1:
        raise SystemExit("magicfit_acceptance_browser_receipt_contract_invalid")
    review_route = (
        f"operator-review://propertyquarry/magicfit/{slug}/{video_sha256}"
    )
    expected_benign_abort = {
        "failure": "net::ERR_ABORTED",
        "method": "GET",
        "resource_type": "media",
        "route": review_route,
    }
    if any(row != expected_benign_abort for row in benign_request_aborts):
        raise SystemExit("magicfit_acceptance_browser_receipt_contract_invalid")
    if (
        payload.get("schema") != BROWSER_RECEIPT_CONTRACT
        or payload.get("status") != "pass"
        or payload.get("provider") != "magicfit"
        or payload.get("target_slug") != slug
        or payload.get("route") != review_route
        or payload.get("http_status") != 200
        or payload.get("video_sha256") != video_sha256
        or payload.get("playback_to_end") is not True
        or payload.get("video_error") is not None
        or payload.get("console_errors") != []
        or payload.get("request_failures") != []
        or payload.get("bad_responses") != []
        or observed_at is None
        or observed_at < generated_at
        or observed_at > now + MAX_FUTURE_SKEW
        or duration <= 0.0
        or abs(duration - video_duration) > 0.1
        or final_current_time < duration - 0.25
    ):
        raise SystemExit("magicfit_acceptance_browser_receipt_contract_invalid")


def _write_bytes_atomic(path: Path, body: bytes, *, mode: int) -> None:
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


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    body = (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    _write_bytes_atomic(path, body, mode=0o600)


def _safe_delivery_destination(
    bundle_dir: Path,
    relpath: str,
    *,
    required_prefix: str,
    directory_mode: int,
) -> Path:
    canonical = _canonical_relpath(relpath)
    prefix = f"{required_prefix.rstrip('/')}/"
    if not canonical.startswith(prefix):
        raise SystemExit("magicfit_acceptance_delivery_path_invalid")
    bundle_root = bundle_dir.resolve()
    lexical = bundle_dir / canonical
    lexical.parent.mkdir(parents=True, exist_ok=True)
    try:
        parent = lexical.parent.resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(
            f"magicfit_acceptance_delivery_path_invalid:{type(exc).__name__}"
        ) from exc
    if bundle_root not in parent.parents or lexical.parent.is_symlink():
        raise SystemExit("magicfit_acceptance_delivery_path_invalid")
    current = lexical.parent
    while current != bundle_dir:
        if current.is_symlink() or not current.is_dir():
            raise SystemExit("magicfit_acceptance_delivery_path_invalid")
        current.chmod(directory_mode)
        current = current.parent
    return lexical


def _activate_video(
    *,
    bundle_dir: Path,
    staged_video_relpath: str,
    final_video_relpath: str,
    video_sha256: str,
) -> Path:
    staged = _local_file(bundle_dir, staged_video_relpath)
    final = _safe_delivery_destination(
        bundle_dir,
        final_video_relpath,
        required_prefix="magicfit-media",
        directory_mode=0o755,
    )
    if final.exists():
        if final.is_symlink() or not final.is_file() or _sha256_file(final) != video_sha256:
            raise SystemExit("magicfit_acceptance_active_video_conflict")
        final.chmod(0o644)
        return final
    if staged is None or _sha256_file(staged) != video_sha256:
        raise SystemExit("magicfit_acceptance_staged_video_missing")
    staged.replace(final)
    final.chmod(0o644)
    _fsync_directory(final.parent)
    return final


def _candidate_manifest_binding_valid(
    payload: dict[str, Any],
    *,
    slug: str,
    video_relpath: str,
    accepted_sidecar_relpath: str,
    video_sha256: str,
    source_receipt_sha256: str,
) -> bool:
    magicfit_import = payload.get("magicfit_import")
    return bool(
        payload.get("slug") == slug
        and payload.get("video_provider") == "magicfit"
        and payload.get("video_provider_backend_key") == "magicfit"
        and payload.get("video_relpath") == video_relpath
        and payload.get("video_sidecar_relpath") == accepted_sidecar_relpath
        and isinstance(magicfit_import, dict)
        and magicfit_import.get("proof_status") == "delivery_accepted"
        and magicfit_import.get("sha256") == video_sha256
        and magicfit_import.get("source_receipt_sha256")
        == source_receipt_sha256
        and magicfit_import.get("delivery_sidecar_relpath")
        == accepted_sidecar_relpath
    )


def _accept_locked(
    *,
    args: argparse.Namespace,
    slug: str,
    bundle_dir: Path,
) -> int:
    manifest_path = bundle_dir / "tour.json"
    pending_path = bundle_dir / PENDING_POINTER_RELPATH
    if not manifest_path.is_file() or not pending_path.is_file():
        raise SystemExit("magicfit_acceptance_pending_delivery_missing")

    manifest, manifest_bytes = _load_json_bytes(
        manifest_path, error="magicfit_acceptance_manifest_invalid"
    )
    pending, pending_bytes = _load_json_bytes(
        pending_path, error="magicfit_acceptance_pending_contract_invalid"
    )
    expected_pending = {
        "contract_name": DELIVERY_CONTRACT,
        "provider": "magicfit",
        "provider_key": "magicfit",
        "provider_backend_key": "magicfit",
        "render_status": "completed",
        "status": "rendered_pending_delivery_acceptance",
        "acceptance_status": "pending",
        "launch_eligible": False,
    }
    if set(pending) != PENDING_SIDECAR_FIELDS or any(
        pending.get(key) != value for key, value in expected_pending.items()
    ):
        raise SystemExit("magicfit_acceptance_pending_contract_invalid")

    video_relpath = _canonical_relpath(pending.get("video_relpath"))
    staged_video_relpath = _canonical_relpath(pending.get("staged_video_relpath"))
    staged_manifest_relpath = _canonical_relpath(
        pending.get("staged_manifest_relpath")
    )
    accepted_sidecar_relpath = _canonical_relpath(
        pending.get("accepted_sidecar_relpath")
    )
    generated_at = _strict_utc(pending.get("generated_at"), require_z=False)
    video_sha256 = _valid_sha256(pending.get("video_sha256"))
    source_receipt_sha256 = _valid_sha256(pending.get("source_receipt_sha256"))
    base_manifest_sha256 = _valid_sha256(pending.get("base_manifest_sha256"))
    staged_manifest_sha256 = _valid_sha256(
        pending.get("staged_manifest_sha256")
    )
    stage_parts = PurePosixPath(staged_video_relpath).parts
    stage_manifest_parts = PurePosixPath(staged_manifest_relpath).parts
    sidecar_parts = PurePosixPath(accepted_sidecar_relpath).parts
    delivery_digest = stage_parts[1] if len(stage_parts) >= 3 else ""
    if (
        generated_at is None
        or not video_sha256
        or not source_receipt_sha256
        or not base_manifest_sha256
        or not staged_manifest_sha256
        or not video_relpath.startswith("magicfit-media/")
        or f".{video_sha256}" not in PurePosixPath(video_relpath).stem
        or len(stage_parts) != 3
        or stage_parts[0] != ".magicfit-staging"
        or SHA256_RE.fullmatch(delivery_digest) is None
        or stage_manifest_parts
        != (".magicfit-staging", delivery_digest, "tour.json")
        or sidecar_parts
        != (".magicfit-deliveries", f"{delivery_digest}.json")
    ):
        raise SystemExit("magicfit_acceptance_pending_contract_invalid")
    if generated_at > datetime.now(timezone.utc) + MAX_FUTURE_SKEW:
        raise SystemExit("magicfit_acceptance_pending_timestamp_invalid")

    active_manifest_sha256 = _sha256_bytes(manifest_bytes)
    if active_manifest_sha256 not in {
        base_manifest_sha256,
        staged_manifest_sha256,
    }:
        raise SystemExit("magicfit_acceptance_manifest_changed")

    if active_manifest_sha256 == base_manifest_sha256:
        staged_manifest_path = _local_file(bundle_dir, staged_manifest_relpath)
        if (
            staged_manifest_path is None
            or _sha256_file(staged_manifest_path) != staged_manifest_sha256
        ):
            raise SystemExit("magicfit_acceptance_staged_manifest_missing")
        candidate_manifest, _candidate_bytes = _load_json_bytes(
            staged_manifest_path,
            error="magicfit_acceptance_staged_manifest_invalid",
        )
    else:
        candidate_manifest = manifest
    if not _candidate_manifest_binding_valid(
        candidate_manifest,
        slug=slug,
        video_relpath=video_relpath,
        accepted_sidecar_relpath=accepted_sidecar_relpath,
        video_sha256=video_sha256,
        source_receipt_sha256=source_receipt_sha256,
    ):
        raise SystemExit("magicfit_acceptance_manifest_binding_invalid")

    staged_video_path = _local_file(bundle_dir, staged_video_relpath)
    final_video_path = _local_file(bundle_dir, video_relpath)
    video_path = staged_video_path or final_video_path
    if video_path is None or _sha256_file(video_path) != video_sha256:
        raise SystemExit("magicfit_acceptance_pending_video_digest_mismatch")
    video_probe = _video_probe(video_path)

    source_path = Path(args.source_receipt).expanduser().resolve()
    source_receipt, source_bytes = _load_json_bytes(
        source_path, error="magicfit_acceptance_source_receipt_invalid"
    )
    if (
        _sha256_bytes(source_bytes) != source_receipt_sha256
        or not _source_receipt_valid(source_receipt, slug=slug)
    ):
        raise SystemExit("magicfit_acceptance_source_receipt_digest_mismatch")

    contact_sheet = Path(args.contact_sheet).expanduser().resolve()
    browser_receipt = Path(args.browser_receipt).expanduser().resolve()
    reviewer_authority = Path(args.reviewer_authority).expanduser().resolve()
    for path, error in (
        (contact_sheet, "magicfit_acceptance_contact_sheet_missing"),
        (browser_receipt, "magicfit_acceptance_browser_receipt_missing"),
        (reviewer_authority, "magicfit_acceptance_reviewer_authority_missing"),
    ):
        if not path.is_file() or path.stat().st_size <= 0:
            raise SystemExit(error)
    try:
        image_header = contact_sheet.read_bytes()[:12]
    except OSError as exc:
        raise SystemExit(
            f"magicfit_acceptance_contact_sheet_invalid:{type(exc).__name__}"
        ) from exc
    if not (
        image_header.startswith(b"\x89PNG\r\n\x1a\n")
        or image_header.startswith(b"\xff\xd8\xff")
    ):
        raise SystemExit("magicfit_acceptance_contact_sheet_invalid")
    contact_sheet_sha256 = _sha256_file(contact_sheet)
    browser_payload, browser_bytes = _load_json_bytes(
        browser_receipt, error="magicfit_acceptance_browser_receipt_invalid"
    )
    _validate_browser_receipt(
        browser_payload,
        slug=slug,
        generated_at=generated_at,
        video_sha256=video_sha256,
        video_duration=float(video_probe["duration_seconds"]),
    )
    browser_receipt_sha256 = _sha256_bytes(browser_bytes)
    authority_sha256 = _sha256_file(reviewer_authority)

    evidence_path = Path(args.evidence_receipt).expanduser().resolve()
    evidence, evidence_bytes = _load_json_bytes(
        evidence_path, error="magicfit_acceptance_evidence_invalid"
    )
    checklist = _validate_evidence(
        evidence,
        slug=slug,
        generated_at=generated_at,
        video_sha256=video_sha256,
        video_probe=video_probe,
        source_receipt_sha256=source_receipt_sha256,
        contact_sheet_sha256=contact_sheet_sha256,
        browser_receipt_sha256=browser_receipt_sha256,
    )

    if pending_path.read_bytes() != pending_bytes:
        raise SystemExit("magicfit_acceptance_pending_contract_changed")
    observed_manifest_sha256 = _sha256_bytes(manifest_path.read_bytes())
    if observed_manifest_sha256 != active_manifest_sha256:
        raise SystemExit("magicfit_acceptance_manifest_changed")
    if _sha256_file(video_path) != video_sha256:
        raise SystemExit("magicfit_acceptance_video_changed")

    reviewed_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    accepted: dict[str, object] = {
        "contract_name": DELIVERY_CONTRACT,
        "provider": "magicfit",
        "provider_key": "magicfit",
        "provider_backend_key": "magicfit",
        "render_status": "completed",
        "status": "delivery_accepted",
        "acceptance_status": "accepted",
        "launch_eligible": True,
        "video_relpath": video_relpath,
        "video_sha256": video_sha256,
        "source_receipt_sha256": source_receipt_sha256,
        "generated_at": pending["generated_at"],
        "review": {
            "contract_name": REVIEW_CONTRACT,
            "reviewed_at": reviewed_at,
            "reviewer_authority_sha256": authority_sha256,
            "evidence_sha256": _sha256_bytes(evidence_bytes),
            "subject": {
                "tour_slug": slug,
                "provider": "magicfit",
                "delivery_contract_name": DELIVERY_CONTRACT,
                "source_receipt_sha256": source_receipt_sha256,
                "video_relpath": video_relpath,
                "video_sha256": video_sha256,
            },
            "checklist": checklist,
        },
    }

    # Activation ordering is the safety property: digest-unique media first,
    # its private accepted review second, and the public manifest last as the
    # sole visibility commit point.  Every pre-commit crash leaves the prior
    # accepted manifest and bytes intact; a post-commit crash leaves a complete
    # new bundle and only a stale private pending pointer to clean up.
    final_video_path = _activate_video(
        bundle_dir=bundle_dir,
        staged_video_relpath=staged_video_relpath,
        final_video_relpath=video_relpath,
        video_sha256=video_sha256,
    )
    _activation_failpoint("after_final_video")

    accepted_sidecar_path = _safe_delivery_destination(
        bundle_dir,
        accepted_sidecar_relpath,
        required_prefix=".magicfit-deliveries",
        directory_mode=0o700,
    )
    _write_private_json(accepted_sidecar_path, accepted)
    accepted_sidecar_bytes = accepted_sidecar_path.read_bytes()
    _activation_failpoint("after_sidecar")

    committed_now = False
    current_manifest_sha256 = _sha256_bytes(manifest_path.read_bytes())
    if current_manifest_sha256 == base_manifest_sha256:
        staged_manifest_path = _local_file(bundle_dir, staged_manifest_relpath)
        if (
            staged_manifest_path is None
            or _sha256_file(staged_manifest_path) != staged_manifest_sha256
        ):
            raise SystemExit("magicfit_acceptance_staged_manifest_changed")
        staged_manifest_path.chmod(0o644)
        staged_manifest_path.replace(manifest_path)
        manifest_path.chmod(0o644)
        _fsync_directory(bundle_dir)
        committed_now = True
    elif current_manifest_sha256 != staged_manifest_sha256:
        raise SystemExit("magicfit_acceptance_manifest_changed")

    _activation_failpoint("after_manifest")

    try:
        if (
            _sha256_file(manifest_path) != staged_manifest_sha256
            or _sha256_file(final_video_path) != video_sha256
            or accepted_sidecar_path.read_bytes() != accepted_sidecar_bytes
        ):
            raise SystemExit("magicfit_acceptance_subject_changed")
    except BaseException:
        if committed_now:
            _write_bytes_atomic(manifest_path, manifest_bytes, mode=0o644)
        raise

    if pending_path.read_bytes() == pending_bytes:
        pending_path.unlink()
        _fsync_directory(bundle_dir)

    print(
        json.dumps(
            {
                "status": "delivery_accepted",
                "slug": slug,
                "video_relpath": video_relpath,
                "video_sha256": video_sha256,
                "source_receipt_sha256": source_receipt_sha256,
                "evidence_sha256": _sha256_bytes(evidence_bytes),
                "reviewer_authority_sha256": authority_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Accept an exact staged MagicFit delivery using closed local evidence."
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument("--source-receipt", required=True)
    parser.add_argument("--evidence-receipt", required=True)
    parser.add_argument("--contact-sheet", required=True)
    parser.add_argument("--browser-receipt", required=True)
    parser.add_argument("--reviewer-authority", required=True)
    args = parser.parse_args()

    slug = _canonical_relpath(args.slug)
    if not slug or "/" in slug:
        raise SystemExit("magicfit_acceptance_slug_invalid")
    root = Path(
        os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours"
    ).expanduser().resolve()
    bundle_dir = root / slug
    if root not in bundle_dir.resolve().parents or bundle_dir.is_symlink():
        raise SystemExit("magicfit_acceptance_bundle_invalid")
    with _activation_lock(bundle_dir):
        return _accept_locked(args=args, slug=slug, bundle_dir=bundle_dir)


if __name__ == "__main__":
    raise SystemExit(main())
