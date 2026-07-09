#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from property_tour_runtime_paths import preferred_public_tour_root, running_container_public_tour_dir


DEFAULT_DEMO_SLUG = "luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557"
DEFAULT_RUNTIME_CONTAINER = "propertyquarry-api"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check(name: str, ok: bool, **extra: object) -> dict[str, object]:
    return {"name": name, "ok": bool(ok), **extra}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _run_json(command: list[str], *, timeout_seconds: float | None = None) -> dict[str, Any]:
    resolved_timeout = _timeout_seconds(timeout_seconds)
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=resolved_timeout,
        )
        payload = json.loads(completed.stdout or "{}")
    except subprocess.TimeoutExpired:
        timeout_label = int(resolved_timeout) if resolved_timeout and float(resolved_timeout).is_integer() else resolved_timeout
        return {
            "_error": f"subprocess_timeout:{timeout_label}s",
            "_timeout_seconds": resolved_timeout,
        }
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _video_metadata(path: Path, *, timeout_seconds: float | None = None) -> dict[str, object]:
    return _run_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_frames,r_frame_rate,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        timeout_seconds=timeout_seconds,
    )


def _frame_delta_stats(
    path: Path,
    *,
    fps: float = 2.0,
    max_sampled_frames: int = 8,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception as exc:
        return {"ok": False, "error": f"PIL unavailable: {exc}"}
    duration_seconds = 0.0
    metadata = _video_metadata(path, timeout_seconds=timeout_seconds)
    try:
        format_payload = dict(metadata.get("format") or {}) if isinstance(metadata.get("format"), dict) else {}
        streams = list(metadata.get("streams") or []) if isinstance(metadata.get("streams"), list) else []
        stream = dict(streams[0]) if streams and isinstance(streams[0], dict) else {}
        duration_seconds = float(format_payload.get("duration") or stream.get("duration") or 0.0)
    except Exception:
        duration_seconds = 0.0
    effective_fps = float(fps)
    if duration_seconds > 0.0 and max_sampled_frames > 0:
        effective_fps = min(effective_fps, max(0.2, float(max_sampled_frames) / duration_seconds))
    resolved_timeout = _timeout_seconds(timeout_seconds)
    with tempfile.TemporaryDirectory(prefix="pq-walkthrough-frames-") as tmp:
        frames: list[Path] = []
        try:
            if duration_seconds > 0.0:
                sample_count = max(6, min(max_sampled_frames, int(round(duration_seconds / 8.0)) + 1))
                timestamps = [
                    round((duration_seconds * index) / max(sample_count - 1, 1), 3)
                    for index in range(sample_count)
                ]
                for index, timestamp in enumerate(timestamps):
                    frame_path = Path(tmp) / f"frame-{index:04d}.jpg"
                    completed = subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-ss",
                            f"{timestamp:.3f}",
                            "-i",
                            str(path),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=160:-1",
                            str(frame_path),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=None,
                    )
                    if completed.returncode != 0:
                        return {
                            "ok": False,
                            "error": "ffmpeg_frame_sampling_failed",
                            "returncode": completed.returncode,
                            "stderr": (completed.stderr or "").strip()[:400],
                        }
                    if frame_path.is_file():
                        frames.append(frame_path)
            else:
                frame_pattern = str(Path(tmp) / "frame-%04d.jpg")
                completed = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(path),
                        "-vf",
                        f"fps={effective_fps:.4f},scale=160:-1",
                        frame_pattern,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=resolved_timeout,
                )
                if completed.returncode != 0:
                    return {
                        "ok": False,
                        "error": "ffmpeg_frame_sampling_failed",
                        "returncode": completed.returncode,
                        "stderr": (completed.stderr or "").strip()[:400],
                    }
                frames = sorted(Path(tmp).glob("frame-*.jpg"))
        except subprocess.TimeoutExpired:
            timeout_label = int(resolved_timeout) if resolved_timeout and float(resolved_timeout).is_integer() else resolved_timeout
            return {
                "ok": False,
                "error": f"ffmpeg_frame_sampling_timeout:{timeout_label}s",
                "timeout_seconds": resolved_timeout,
            }
        deltas: list[float] = []
        previous = None
        for frame in frames:
            try:
                image = Image.open(frame).convert("RGB")
            except Exception:
                continue
            if previous is not None:
                diff = ImageChops.difference(previous, image)
                stat = ImageStat.Stat(diff)
                deltas.append(round(sum(stat.mean) / len(stat.mean), 3))
            previous = image
        return {
            "ok": bool(frames),
            "sampling_fps": round(effective_fps, 4),
            "source_duration_seconds": round(duration_seconds, 3),
            "sampled_frame_count": len(frames),
            "delta_count": len(deltas),
            "max_delta": max(deltas) if deltas else 0.0,
            "mean_delta": round(sum(deltas) / len(deltas), 3) if deltas else 0.0,
            "top_deltas": sorted(deltas, reverse=True)[:8],
        }


def _coverage_from_payload(payload: dict[str, Any], *, bundle: Path | None = None) -> dict[str, Any]:
    for key in (
        "walkthrough_coverage_proof",
        "magicfit_walkthrough_coverage",
        "walkthrough_quality_receipt",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    magicfit = payload.get("magicfit_import")
    if isinstance(magicfit, dict):
        for key in ("coverage_proof", "walkthrough_coverage_proof", "quality_receipt"):
            value = magicfit.get(key)
            if isinstance(value, dict):
                return dict(value)
    sidecar_relpath = str(payload.get("video_sidecar_relpath") or "").strip().lstrip("/")
    if bundle is not None and sidecar_relpath:
        sidecar_path = bundle / sidecar_relpath
        sidecar = _load_json(sidecar_path) if sidecar_path.is_file() else {}
        for key in (
            "walkthrough_coverage_proof",
            "magicfit_walkthrough_coverage",
            "walkthrough_quality_receipt",
        ):
            value = sidecar.get(key)
            if isinstance(value, dict):
                return dict(value)
        route_labels = sidecar.get("route_labels") or sidecar.get("covered_route_labels") or []
        covered = sidecar.get("covered_route_labels") or sidecar.get("route_labels") or []
        if isinstance(route_labels, list) and isinstance(covered, list) and route_labels and covered:
            expected = [str(item).strip() for item in route_labels if str(item).strip()]
            visited = [str(item).strip() for item in covered if str(item).strip()]
            return {
                "status": "pass" if set(expected).issubset(set(visited)) else "fail",
                "source": "video_sidecar_route_labels",
                "segments_expected": expected,
                "segments_visited": visited,
                "coverage_segments": [
                    {"segment": label, "index": index + 1}
                    for index, label in enumerate(visited)
                ],
            }
    return {}


def _coverage_ok(coverage: dict[str, Any]) -> tuple[bool, dict[str, object]]:
    expected = (
        coverage.get("rooms_expected")
        or coverage.get("expected_rooms")
        or coverage.get("segments_expected")
        or coverage.get("expected_segments")
        or []
    )
    visited = (
        coverage.get("rooms_visited")
        or coverage.get("visited_rooms")
        or coverage.get("segments_visited")
        or coverage.get("visited_segments")
        or []
    )
    if isinstance(expected, str):
        expected = [expected]
    if isinstance(visited, str):
        visited = [visited]
    expected_set = {str(item).strip().lower() for item in expected if str(item).strip()}
    visited_set = {str(item).strip().lower() for item in visited if str(item).strip()}
    missing = sorted(expected_set - visited_set)
    status = str(coverage.get("status") or coverage.get("result") or "").strip().lower()
    raw_segments = (
        coverage.get("room_segments")
        or coverage.get("scene_segments")
        or coverage.get("coverage_segments")
        or coverage.get("segments")
        or []
    )
    segment_count = len([row for row in list(raw_segments) if isinstance(row, dict)])
    ok = status == "pass" and bool(expected_set) and not missing and segment_count >= len(expected_set)
    return ok, {
        "status": status,
        "rooms_expected": sorted(expected_set),
        "rooms_visited": sorted(visited_set),
        "missing_rooms": missing,
        "room_segment_count": segment_count,
    }


def _candidate_has_publish_signal(payload: dict[str, Any]) -> bool:
    provider_key = str(
        payload.get("video_provider")
        or payload.get("video_provider_key")
        or payload.get("video_render_provider")
        or ""
    ).strip().lower()
    coverage = _coverage_from_payload(payload)
    generated_video_providers = {
        "magicfit",
        "onemin_i2v",
        "ea_one_manager_onemin_i2v",
        "poppy_ai",
        "propertyquarry_generated_reconstruction",
    }
    if provider_key in generated_video_providers:
        return bool(coverage)
    if provider_key:
        return True
    if str(payload.get("video_coverage_proof") or "").strip():
        return True
    return bool(coverage)


def _selected_walkthrough_payload(
    payload: dict[str, Any],
    *,
    force_generated_reconstruction: bool = False,
) -> dict[str, Any]:
    active = dict(payload)
    generated = payload.get("generated_reconstruction")
    generated_candidate: dict[str, Any] = {}
    if isinstance(generated, dict):
        generated_video_relpath = str(generated.get("walkthrough_video_relpath") or "").strip()
        if generated_video_relpath:
            generated_candidate = {
                **active,
                "_walkthrough_candidate": "generated_reconstruction",
                "video_relpath": generated_video_relpath,
                "video_provider": "propertyquarry_generated_reconstruction",
                "video_sidecar_relpath": str(generated.get("walkthrough_sidecar_relpath") or "").strip(),
                "video_coverage_proof": "boundary_verified_frame_continuation",
            }
            coverage = generated.get("walkthrough_coverage_proof")
            if isinstance(coverage, dict):
                generated_candidate["walkthrough_coverage_proof"] = dict(coverage)
    if force_generated_reconstruction and generated_candidate:
        return generated_candidate
    active["_walkthrough_candidate"] = "published_video"
    if generated_candidate and (not str(active.get("video_relpath") or "").strip() or not _candidate_has_publish_signal(active)):
        return generated_candidate
    return active


def _service_generated_reconstruction_slug(receipt: dict[str, Any]) -> str:
    for key in ("slug", "demo_slug"):
        value = str(receipt.get(key) or "").strip()
        if value:
            return value
    details = dict(receipt.get("details") or {}) if isinstance(receipt.get("details"), dict) else {}
    for key in ("slug", "demo_slug"):
        value = str(details.get(key) or "").strip()
        if value:
            return value
    for key in ("tour_url", "viewer_url"):
        raw_url = str(receipt.get(key) or details.get(key) or "").strip()
        if not raw_url:
            continue
        parsed = urllib.parse.urlparse(raw_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "tours":
            return urllib.parse.unquote(parts[1]).strip()
    return ""


def _selected_walkthrough_slug(
    *,
    requested_slug: str,
    service_generated_reconstruction_receipt: dict[str, Any],
) -> tuple[str, str, str]:
    requested = str(requested_slug or "").strip()
    service_slug = _service_generated_reconstruction_slug(service_generated_reconstruction_receipt)
    if service_slug and (not requested or requested == DEFAULT_DEMO_SLUG):
        return service_slug, service_slug, "service_generated_reconstruction_receipt"
    if requested:
        return requested, service_slug, ("requested_demo_slug" if requested != DEFAULT_DEMO_SLUG else "default_demo_slug")
    if service_slug:
        return service_slug, service_slug, "service_generated_reconstruction_receipt"
    return DEFAULT_DEMO_SLUG, "", "default_demo_slug"


def _resolve_walkthrough_tour_root(
    configured_root: str,
    *,
    slug: str,
    force_generated_reconstruction: bool = False,
) -> Path:
    configured_path = Path(configured_root or "state/public_property_tours").expanduser()
    repo_root = Path(__file__).resolve().parents[1]
    preferred_root = preferred_public_tour_root(
        configured_root=configured_path,
        repo_root=repo_root,
        runtime_container=str(os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or "").strip(),
    )
    runtime_volume_root = running_container_public_tour_dir(str(os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or "").strip())
    candidates: list[Path] = []
    for candidate in (configured_path, runtime_volume_root, preferred_root):
        if candidate is None:
            continue
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved not in candidates:
            candidates.append(resolved)
    scored: list[tuple[int, float, int, Path]] = []
    for index, candidate_root in enumerate(candidates):
        manifest_path = candidate_root / slug / "tour.json"
        if not manifest_path.is_file():
            continue
        payload = _selected_walkthrough_payload(
            _load_json(manifest_path),
            force_generated_reconstruction=force_generated_reconstruction,
        )
        video_relpath = str(payload.get("video_relpath") or "").strip()
        video_path = (candidate_root / slug / video_relpath).resolve() if video_relpath else candidate_root / "__missing__"
        has_video = int(bool(video_relpath) and video_path.is_file())
        try:
            manifest_mtime = float(manifest_path.stat().st_mtime)
        except OSError:
            manifest_mtime = 0.0
        scored.append((has_video, manifest_mtime, -index, candidate_root))
    if scored:
        return max(scored)[3]
    return preferred_root.resolve()


def _copy_runtime_bundle_to_temp_root(slug: str, *, container_name: str = "") -> tempfile.TemporaryDirectory[str] | None:
    docker_bin = shutil.which("docker")
    if not docker_bin or not slug:
        return None
    normalized_container = str(
        container_name or os.getenv("PROPERTYQUARRY_RUNTIME_CONTAINER") or DEFAULT_RUNTIME_CONTAINER
    ).strip()
    if not normalized_container:
        return None
    tmp_root = tempfile.TemporaryDirectory(prefix="pq-walkthrough-runtime-bundle-")
    destination_root = Path(tmp_root.name)
    completed = subprocess.run(
        [
            docker_bin,
            "cp",
            f"{normalized_container}:/data/public_property_tours/{slug}",
            str(destination_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    copied_manifest = destination_root / slug / "tour.json"
    if completed.returncode != 0 or not copied_manifest.is_file():
        tmp_root.cleanup()
        return None
    return tmp_root


def build_walkthrough_quality_receipt(
    *,
    tour_root: str,
    demo_slug: str,
    max_jump_delta: float,
    min_duration_seconds: float,
    ffprobe_timeout_seconds: float = 20.0,
    frame_sample_timeout_seconds: float = 45.0,
    service_generated_reconstruction_receipt_path: str = "",
) -> dict[str, object]:
    service_receipt_path = Path(str(service_generated_reconstruction_receipt_path or "").strip()) if str(service_generated_reconstruction_receipt_path or "").strip() else None
    service_receipt = _load_json(service_receipt_path) if service_receipt_path is not None and service_receipt_path.is_file() else {}
    requested_slug = str(demo_slug or DEFAULT_DEMO_SLUG).strip()
    slug, service_slug, selection_source = _selected_walkthrough_slug(
        requested_slug=requested_slug,
        service_generated_reconstruction_receipt=service_receipt,
    )
    temp_root: tempfile.TemporaryDirectory[str] | None = None
    force_generated_reconstruction = bool(service_slug) and slug == service_slug
    root = _resolve_walkthrough_tour_root(
        tour_root,
        slug=slug,
        force_generated_reconstruction=force_generated_reconstruction,
    )
    bundle = root / slug
    manifest_payload = _load_json(bundle / "tour.json")
    payload = _selected_walkthrough_payload(
        manifest_payload,
        force_generated_reconstruction=force_generated_reconstruction,
    )
    initial_video_relpath = str(payload.get("video_relpath") or "").strip()
    initial_video_path = (bundle / initial_video_relpath).resolve() if initial_video_relpath else bundle / "__missing__"
    if (not manifest_payload or not initial_video_relpath or not initial_video_path.is_file()) and slug:
        temp_root = _copy_runtime_bundle_to_temp_root(slug)
        if temp_root is not None:
            root = Path(temp_root.name)
            bundle = root / slug
            manifest_payload = _load_json(bundle / "tour.json")
            payload = _selected_walkthrough_payload(
                manifest_payload,
                force_generated_reconstruction=force_generated_reconstruction,
            )
    checks: list[dict[str, object]] = []
    if service_receipt_path is not None:
        checks.append(
            _check(
                "service_generated_reconstruction_receipt_present",
                bool(service_receipt),
                receipt_path=str(service_receipt_path),
            )
        )
        checks.append(
            _check(
                "service_generated_reconstruction_bundle_selected",
                bool(service_slug) and slug == service_slug,
                service_generated_reconstruction_slug=service_slug,
                selected_slug=slug,
                selection_source=selection_source,
            )
        )
    video_relpath = str(payload.get("video_relpath") or "").strip()
    video_path = bundle / video_relpath if video_relpath else Path()
    checks.append(_check("tour_manifest_present", bool(payload), manifest=str(bundle / "tour.json")))
    if service_receipt_path is not None:
        checks.append(
            _check(
                "walkthrough_candidate_matches_service_generated_reconstruction",
                str(payload.get("_walkthrough_candidate") or "").strip() == "generated_reconstruction",
                walkthrough_candidate=str(payload.get("_walkthrough_candidate") or "").strip(),
            )
        )
    checks.append(_check("walkthrough_video_declared", bool(video_relpath), video_relpath=video_relpath))
    checks.append(_check("walkthrough_video_file_present", bool(video_path and video_path.is_file()), video_path=str(video_path)))

    metadata = (
        _video_metadata(video_path, timeout_seconds=ffprobe_timeout_seconds)
        if video_path and video_path.is_file()
        else {}
    )
    format_payload = dict(metadata.get("format") or {}) if isinstance(metadata.get("format"), dict) else {}
    streams = list(metadata.get("streams") or []) if isinstance(metadata.get("streams"), list) else []
    stream = dict(streams[0]) if streams and isinstance(streams[0], dict) else {}
    metadata_error = str(metadata.get("_error") or "").strip()
    checks.append(
        _check(
            "walkthrough_video_metadata_available",
            bool(metadata) and not metadata_error,
            metadata_error=metadata_error,
        )
    )
    try:
        duration = float(format_payload.get("duration") or stream.get("duration") or 0)
    except Exception:
        duration = 0.0
    checks.append(
        _check(
            "walkthrough_duration_floor",
            duration >= min_duration_seconds,
            duration_seconds=round(duration, 3),
            min_duration_seconds=min_duration_seconds,
        )
    )

    coverage = _coverage_from_payload(payload, bundle=bundle)
    coverage_ok, coverage_summary = _coverage_ok(coverage)
    checks.append(_check("walkthrough_room_coverage_receipt_present", bool(coverage), coverage=coverage_summary))
    checks.append(_check("walkthrough_room_coverage_complete", coverage_ok, coverage=coverage_summary))

    delta_stats = (
        _frame_delta_stats(
            video_path,
            timeout_seconds=frame_sample_timeout_seconds,
        )
        if video_path and video_path.is_file()
        else {"ok": False}
    )
    max_delta = float(delta_stats.get("max_delta") or 0)
    checks.append(_check("walkthrough_frame_samples_available", bool(delta_stats.get("ok")), frame_delta_stats=delta_stats))
    checks.append(
        _check(
            "walkthrough_frame_jump_limit",
            bool(delta_stats.get("ok")) and max_delta <= max_jump_delta,
            frame_delta_stats=delta_stats,
            max_jump_delta=max_jump_delta,
        )
    )
    failed = [row for row in checks if not row.get("ok")]
    try:
        return {
            "contract_name": "propertyquarry.walkthrough_quality_gate.v1",
            "generated_at": _utc_now(),
            "status": "pass" if not failed else "fail",
            "tour_root": str(root),
            "demo_slug": slug,
            "requested_demo_slug": requested_slug,
            "selection_source": selection_source,
            "service_generated_reconstruction_slug": service_slug,
            "service_generated_reconstruction_receipt_path": str(service_receipt_path) if service_receipt_path is not None else "",
            "video_relpath": video_relpath,
            "walkthrough_candidate": str(payload.get("_walkthrough_candidate") or "").strip(),
            "check_count": len(checks),
            "failed_count": len(failed),
            "checks": checks,
            "notes": [
                "A video file alone is not walkthrough readiness.",
                "Gold requires explicit room coverage proof and a frame-delta continuity check.",
            ],
        }
    finally:
        if temp_root is not None:
            temp_root.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard walkthrough quality gate for PropertyQuarry.")
    parser.add_argument("--tour-root", default=os.getenv("EA_PUBLIC_TOUR_DIR", "state/public_property_tours"))
    parser.add_argument("--demo-slug", default=DEFAULT_DEMO_SLUG)
    parser.add_argument("--max-jump-delta", type=float, default=42.0)
    parser.add_argument("--min-duration-seconds", type=float, default=30.0)
    parser.add_argument(
        "--ffprobe-timeout-seconds",
        type=float,
        default=float(os.getenv("PROPERTYQUARRY_WALKTHROUGH_QUALITY_FFPROBE_TIMEOUT_SECONDS", "20") or 20),
    )
    parser.add_argument(
        "--frame-sample-timeout-seconds",
        type=float,
        default=float(os.getenv("PROPERTYQUARRY_WALKTHROUGH_QUALITY_FRAME_SAMPLE_TIMEOUT_SECONDS", "45") or 45),
    )
    parser.add_argument("--service-generated-reconstruction-receipt", default="")
    parser.add_argument("--write", default="_completion/smoke/property-live-walkthrough-quality-latest.json")
    args = parser.parse_args()
    receipt = build_walkthrough_quality_receipt(
        tour_root=args.tour_root,
        demo_slug=args.demo_slug,
        max_jump_delta=max(1.0, float(args.max_jump_delta or 42.0)),
        min_duration_seconds=max(1.0, float(args.min_duration_seconds or 30.0)),
        ffprobe_timeout_seconds=max(1.0, float(args.ffprobe_timeout_seconds or 20.0)),
        frame_sample_timeout_seconds=max(1.0, float(args.frame_sample_timeout_seconds or 45.0)),
        service_generated_reconstruction_receipt_path=str(args.service_generated_reconstruction_receipt or "").strip(),
    )
    output = json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
