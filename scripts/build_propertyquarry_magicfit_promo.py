#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path("/docker/property")
OUT = ROOT / "_completion" / "propertyquarry_magicfit_promo_20260606"
CLIPS = OUT / "magicfit_clips"
FINAL = OUT / "PropertyQuarry_Hero_87s_16x9_4K_DE.mp4"
TELEGRAM_FINAL = OUT / "PropertyQuarry_Hero_87s_16x9_Telegram_720p_DE.mp4"
SILENT = OUT / "PropertyQuarry_Hero_87s_16x9_4K_DE.silent.mp4"
AUDIO = OUT / "PropertyQuarry_Hero_87s_16x9_4K_DE.aac"
SRT = OUT / "PropertyQuarry_Hero_87s_16x9_4K_DE.srt"
RECEIPT = OUT / "PROPERTYQUARRY_MAGICFIT_PROMO.generated.json"
TELEGRAM_RECEIPT = OUT / "PROPERTYQUARRY_MAGICFIT_PROMO.telegram.receipt.json"
PACKET = ROOT / "docs" / "PROPERTYQUARRY_PROMO_VIDEO_PACKET.json"
UNMIXR_API_URL = "https://unmixr.com/api/v1/short-tts/"
TARGET_SECONDS = 87.0
TRANSITION_SECONDS = 0.45
FPS = 24
MAGICFIT_TIMELINE = [
    ("01_chaos_am_tisch", 7.0),
    ("02_die_frage", 8.0),
    ("03_search_brief", 10.0),
    ("04_market_scan", 11.0),
    ("05_dossier", 12.0),
    ("06_tour_tradeoff", 12.0),
    ("07_packet_share", 10.0),
    ("08_agent_brief", 10.0),
    ("09_cta", 7.0),
]


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(*command: str) -> None:
    subprocess.run(command, check=True)


def probe(path: Path) -> dict[str, Any]:
    return json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
    )


def duration(path: Path) -> float:
    return float((probe(path).get("format") or {}).get("duration") or 0.0)


def parse_timecode(token: str) -> float:
    parts = token.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"invalid_timecode:{token}")


def parse_voice_line(raw: str) -> tuple[float, str]:
    match = re.match(r"^\[(?P<ts>[^\]]+)\]\s*(?P<text>.+)$", raw.strip())
    if not match:
        raise ValueError(f"invalid_voice_line:{raw}")
    return parse_timecode(match.group("ts")), match.group("text").strip()


def unmixr_config() -> dict[str, str]:
    api_key = os.environ.get("UNMIXR_API_KEY", "").strip()
    voice_id = os.environ.get("UNMIXR_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        raise RuntimeError("unmixr_not_configured")
    return {
        "api_key": api_key,
        "voice_id": voice_id,
        "language": os.environ.get("PROPERTYQUARRY_UNMIXR_LANGUAGE", "de-DE").strip() or "de-DE",
        "speaking_rate": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_RATE", "medium").strip() or "medium",
        "speaking_pitch": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_PITCH", "low").strip() or "low",
        "speaking_volume": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_VOLUME", "medium").strip() or "medium",
    }


def render_unmixr_tts(text: str, output: Path) -> bool:
    config = unmixr_config()
    payload = json.dumps(
        {
            "text": text,
            "voice_id": config["voice_id"],
            "language": config["language"],
            "speaking_rate": config["speaking_rate"],
            "speaking_pitch": config["speaking_pitch"],
            "speaking_volume": config["speaking_volume"],
            "output_type": output.suffix.lstrip(".") or "mp3",
            "response_type": "url",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        UNMIXR_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
        audio_url = str(body.get("audio_url") or "").strip()
        if not audio_url:
            return False
        with urllib.request.urlopen(audio_url, timeout=180) as audio_response:
            output.write_bytes(audio_response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    return output.exists() and output.stat().st_size > 0


def fit_audio_to_window(input_path: Path, output_path: Path, *, target_seconds: float) -> Path:
    current = max(0.1, duration(input_path))
    if current <= target_seconds:
        output_path.write_bytes(input_path.read_bytes())
        return output_path
    ratio = current / max(target_seconds, 0.1)
    factors: list[float] = []
    while ratio > 2.0:
        factors.append(2.0)
        ratio /= 2.0
    factors.append(max(0.5, min(2.0, ratio)))
    filter_chain = ",".join(f"atempo={factor:.5f}" for factor in factors)
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-filter:a",
        filter_chain,
        "-c:a",
        "mp3",
        str(output_path),
    )
    return output_path


def write_srt(entries: list[tuple[float, float, str]]) -> None:
    def stamp(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, remainder = divmod(millis, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        secs, ms = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    lines: list[str] = []
    for index, (start, end, text) in enumerate(entries, start=1):
        lines.extend([str(index), f"{stamp(start)} --> {stamp(end)}", text, ""])
    SRT.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def build_silent_video(scene_paths: list[Path], requested_durations: list[float]) -> None:
    if len(scene_paths) != len(requested_durations):
        raise RuntimeError("scene_path_duration_mismatch")
    if abs(sum(requested_durations) - TARGET_SECONDS) > 0.01:
        raise RuntimeError(f"invalid_timeline_seconds:{sum(requested_durations):.3f}")
    clip_durations: list[float] = []
    for index, requested in enumerate(requested_durations):
        overlap_pad = TRANSITION_SECONDS
        if index == 0 or index == len(requested_durations) - 1:
            overlap_pad = TRANSITION_SECONDS / 2
        clip_durations.append(requested + overlap_pad)
    inputs: list[str] = []
    filters: list[str] = []
    for index, scene in enumerate(scene_paths):
        media = probe(scene)
        clip_duration = float(dict(media.get("format") or {}).get("duration") or 0.0)
        if clip_duration <= 0:
            raise RuntimeError(f"invalid_clip_duration:{scene}")
        target_duration = clip_durations[index]
        stretch = target_duration / clip_duration
        inputs.extend(["-i", str(scene)])
        filters.append(
            f"[{index}:v]scale=3840:2160:force_original_aspect_ratio=increase,"
            f"crop=3840:2160,setsar=1,setpts={stretch:.8f}*PTS,"
            f"trim=duration={target_duration:.6f},setpts=PTS-STARTPTS,"
            f"fps={FPS},format=yuv420p[v{index}]"
        )
    chain = "[v0]"
    chain_duration = clip_durations[0]
    for index in range(1, len(scene_paths)):
        out = f"[x{index}]"
        offset = chain_duration - TRANSITION_SECONDS
        filters.append(
            f"{chain}[v{index}]xfade=transition=fade:duration={TRANSITION_SECONDS:.3f}:offset={offset:.6f}{out}"
        )
        chain = out
        chain_duration += clip_durations[index] - TRANSITION_SECONDS
    run(
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        chain,
        "-t",
        f"{TARGET_SECONDS:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(SILENT),
    )


def build_audio(lines: list[str]) -> list[dict[str, Any]]:
    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    parsed = [parse_voice_line(line) for line in lines]
    clips: list[dict[str, Any]] = []
    subtitle_entries: list[tuple[float, float, str]] = []
    for index, (start, text) in enumerate(parsed):
        next_start = parsed[index + 1][0] if index + 1 < len(parsed) else TARGET_SECONDS
        max_window = max(1.2, next_start - start - 0.18)
        raw_path = audio_dir / f"vo-{index:02d}.mp3"
        if not render_unmixr_tts(text, raw_path):
            raise RuntimeError(f"unmixr_render_failed:{index}")
        fitted_path = audio_dir / f"vo-{index:02d}.fit.mp3"
        fit_audio_to_window(raw_path, fitted_path, target_seconds=max_window)
        clip_duration = min(duration(fitted_path), max_window)
        clips.append({"path": fitted_path, "start": start, "duration": clip_duration, "text": text})
        subtitle_entries.append((start, min(TARGET_SECONDS, start + clip_duration), text))
    write_srt(subtitle_entries)
    inputs = []
    filters = []
    for index, clip in enumerate(clips):
        inputs.extend(["-i", str(clip["path"])])
        delay = int(round(float(clip["start"]) * 1000))
        filters.append(f"[{index}:a]adelay={delay}|{delay},volume=1.0[a{index}]")
    mix_inputs = "".join(f"[a{index}]" for index in range(len(clips)))
    filters.append(f"{mix_inputs}amix=inputs={len(clips)}:normalize=0,atrim=0:{TARGET_SECONDS:.3f},aresample=48000[outa]")
    run(
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outa]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(AUDIO),
    )
    return clips


def mux() -> None:
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(SILENT),
        "-i",
        str(AUDIO),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(FINAL),
    )


def build_telegram_video() -> None:
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(FINAL),
        "-vf",
        "scale=-2:720",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(TELEGRAM_FINAL),
    )


def send_telegram() -> dict[str, Any]:
    run(
        "python3",
        "/docker/chummercomplete/chummer.run-services/scripts/send_promo_video_telegram_via_ea.py",
        str(TELEGRAM_FINAL),
        "--caption",
        "PropertyQuarry hero trailer. MagicFit scene render with premium Unmixr narration. Telegram delivery encode; 4K master retained locally.",
        "--receipt-name",
        "propertyquarry_magicfit_promo.telegram.receipt.json",
    )
    return json.loads((Path("/docker/chummercomplete/_completion/telegram_promo_delivery") / "propertyquarry_magicfit_promo.telegram.receipt.json").read_text(encoding="utf-8"))


def main() -> int:
    load_env(ROOT / ".env")
    load_env(Path("/docker/EA/.env"))
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    scene_paths = [CLIPS / f"{scene_id}.mp4" for scene_id, _duration in MAGICFIT_TIMELINE]
    sidecar_paths = [CLIPS / f"{scene_id}.magicfit.json" for scene_id, _duration in MAGICFIT_TIMELINE]
    missing = [str(path) for path in scene_paths if not path.is_file()]
    if missing:
        raise SystemExit("missing_magicfit_clips:\n" + "\n".join(missing))
    missing_sidecars = [str(path) for path in sidecar_paths if not path.is_file()]
    if missing_sidecars:
        raise SystemExit("missing_magicfit_receipts:\n" + "\n".join(missing_sidecars))
    OUT.mkdir(parents=True, exist_ok=True)
    build_silent_video(scene_paths, [duration for _scene_id, duration in MAGICFIT_TIMELINE])
    clips = build_audio(list(packet.get("voiceover_lines") or []))
    mux()
    build_telegram_video()
    telegram_receipt = send_telegram()
    scene_receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sidecar_paths]
    receipt = {
        "generated_at_utc": utc_now(),
        "status": "published",
        "render_mode": "magicfit_per_scene_with_unmixr_narration",
        "provider_claim": "MagicFit",
        "magicfit_claim_allowed": True,
        "source_scene_count": len(scene_paths),
        "timeline_seconds": [{"scene_id": scene_id, "seconds": seconds} for scene_id, seconds in MAGICFIT_TIMELINE],
        "video_path": str(FINAL),
        "telegram_video_path": str(TELEGRAM_FINAL),
        "silent_video_path": str(SILENT),
        "audio_path": str(AUDIO),
        "subtitle_path": str(SRT),
        "duration_seconds": duration(FINAL),
        "voice_id": os.environ.get("UNMIXR_VOICE_ID", "").strip(),
        "voice_clip_count": len(clips),
        "magicfit_scene_receipts": [str(path) for path in sidecar_paths],
        "magicfit_video_output_urls": [str(receipt.get("video_output_url") or "") for receipt in scene_receipts],
        "telegram_receipt_path": str(Path("/docker/chummercomplete/_completion/telegram_promo_delivery") / "propertyquarry_magicfit_promo.telegram.receipt.json"),
        "telegram_message_ids": list(telegram_receipt.get("message_ids") or []),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    TELEGRAM_RECEIPT.write_text(json.dumps(telegram_receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(FINAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
