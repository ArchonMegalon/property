#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DEMO_SLUG = "luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557"


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


def _run_json(command: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _video_metadata(path: Path) -> dict[str, object]:
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
        ]
    )


def _frame_delta_stats(path: Path, *, fps: float = 2.0) -> dict[str, object]:
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception as exc:
        return {"ok": False, "error": f"PIL unavailable: {exc}"}
    with tempfile.TemporaryDirectory(prefix="pq-walkthrough-frames-") as tmp:
        frame_pattern = str(Path(tmp) / "frame-%04d.jpg")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vf",
                f"fps={fps},scale=160:-1",
                frame_pattern,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        frames = sorted(Path(tmp).glob("frame-*.jpg"))
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


def _selected_walkthrough_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
    active["_walkthrough_candidate"] = "published_video"
    if generated_candidate and (not str(active.get("video_relpath") or "").strip() or not _candidate_has_publish_signal(active)):
        return generated_candidate
    return active


def build_walkthrough_quality_receipt(
    *,
    tour_root: str,
    demo_slug: str,
    max_jump_delta: float,
    min_duration_seconds: float,
) -> dict[str, object]:
    root = Path(tour_root or "state/public_property_tours")
    slug = str(demo_slug or DEFAULT_DEMO_SLUG).strip()
    bundle = root / slug
    manifest_payload = _load_json(bundle / "tour.json")
    payload = _selected_walkthrough_payload(manifest_payload)
    checks: list[dict[str, object]] = []
    video_relpath = str(payload.get("video_relpath") or "").strip()
    video_path = bundle / video_relpath if video_relpath else Path()
    checks.append(_check("tour_manifest_present", bool(payload), manifest=str(bundle / "tour.json")))
    checks.append(_check("walkthrough_video_declared", bool(video_relpath), video_relpath=video_relpath))
    checks.append(_check("walkthrough_video_file_present", bool(video_path and video_path.is_file()), video_path=str(video_path)))

    metadata = _video_metadata(video_path) if video_path and video_path.is_file() else {}
    format_payload = dict(metadata.get("format") or {}) if isinstance(metadata.get("format"), dict) else {}
    streams = list(metadata.get("streams") or []) if isinstance(metadata.get("streams"), list) else []
    stream = dict(streams[0]) if streams and isinstance(streams[0], dict) else {}
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

    delta_stats = _frame_delta_stats(video_path) if video_path and video_path.is_file() else {"ok": False}
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
    return {
        "contract_name": "propertyquarry.walkthrough_quality_gate.v1",
        "generated_at": _utc_now(),
        "status": "pass" if not failed else "fail",
        "tour_root": str(root),
        "demo_slug": slug,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard walkthrough quality gate for PropertyQuarry.")
    parser.add_argument("--tour-root", default=os.getenv("EA_PUBLIC_TOUR_DIR", "state/public_property_tours"))
    parser.add_argument("--demo-slug", default=DEFAULT_DEMO_SLUG)
    parser.add_argument("--max-jump-delta", type=float, default=42.0)
    parser.add_argument("--min-duration-seconds", type=float, default=30.0)
    parser.add_argument("--write", default="_completion/smoke/property-live-walkthrough-quality-latest.json")
    args = parser.parse_args()
    receipt = build_walkthrough_quality_receipt(
        tour_root=args.tour_root,
        demo_slug=args.demo_slug,
        max_jump_delta=max(1.0, float(args.max_jump_delta or 42.0)),
        min_duration_seconds=max(1.0, float(args.min_duration_seconds or 30.0)),
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
