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


def safe_variant(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-_")[:48]


ROOT = Path(os.environ.get("PROPERTYQUARRY_ROOT") or Path(__file__).resolve().parents[1]).resolve()
EA_ROOT = Path(os.environ.get("PROPERTYQUARRY_EA_ROOT") or "/docker/EA").resolve()
OUT = Path(
    os.environ.get("PROPERTYQUARRY_PROMO_OUT_DIR")
    or ROOT / "_completion" / "propertyquarry_magicfit_promo_20260606"
).resolve()
VARIANT = safe_variant(os.environ.get("PROPERTYQUARRY_PROMO_VARIANT", ""))
VARIANT_TAG = f"_{VARIANT}" if VARIANT else ""
CLIPS = Path(os.environ.get("PROPERTYQUARRY_MAGICFIT_CLIPS_DIR") or OUT / "magicfit_clips").resolve()
FINAL = OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.mp4"
TELEGRAM_FINAL = OUT / f"PropertyQuarry_Hero_87s_16x9_Telegram_720p_DE{VARIANT_TAG}.mp4"
SILENT = Path(
    os.environ.get("PROPERTYQUARRY_PROMO_SILENT_VIDEO")
    or OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.silent.mp4"
).resolve()
VOICE_AUDIO = OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.voice.aac"
SOUNDTRACK = OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.soundtrack.wav"
AUDIO = OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.aac"
SRT = OUT / f"PropertyQuarry_Hero_87s_16x9_4K_DE{VARIANT_TAG}.srt"
RECEIPT = OUT / f"PROPERTYQUARRY_MAGICFIT_PROMO{VARIANT_TAG}.generated.json"
TELEGRAM_RECEIPT = OUT / f"PROPERTYQUARRY_MAGICFIT_PROMO{VARIANT_TAG}.telegram.receipt.json"
PACKET = Path(
    os.environ.get("PROPERTYQUARRY_PROMO_PACKET")
    or ROOT / "docs" / "PROPERTYQUARRY_PROMO_VIDEO_PACKET.json"
).resolve()
UNMIXR_API_URL = "https://unmixr.com/api/v1/short-tts/"
UNMIXR_SMOOTHER_DE_VOICE_ID = "9827708d-c40a-48a4-b8a3-7b878f3e4185"
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

SMOOTHER_SALES_VOICEOVER_LINES = [
    "[00:00.8] Zu viele Wohnungen sind nicht das Problem.",
    "[00:03.2] Das Problem ist der Moment, in dem alles gut aussieht - und du trotzdem nicht weisst, ob es stimmt.",
    "[00:08.5] Genau hier beginnt PropertyQuarry.",
    "[00:11.0] Nicht mit noch mehr Tabs. Sondern mit Klarheit, die verkauft, was wirklich zaehlt: eine bessere Entscheidung.",
    "[00:16.0] Du sagst, was dir wichtig ist: Lage, Grundriss, Heizung, Lift, Aussenflaeche, Risiko.",
    "[00:23.8] PropertyQuarry baut daraus einen Search Brief, der den Markt fuer dich denkt.",
    "[00:29.2] Schwache Treffer fallen raus. Fehlende Grundrisse werden sichtbar. Offene Fragen bleiben nicht versteckt.",
    "[00:36.4] Aus jedem Listing wird ein Dossier.",
    "[00:39.8] Mit Fit Score, Confidence, Empfehlung, Risiken und den Fragen, die du vor der Besichtigung stellen solltest.",
    "[00:48.2] Eine Tour zeigt dir den Raum.",
    "[00:51.0] PropertyQuarry zeigt dir den Tradeoff.",
    "[00:54.0] Was stark ist. Was fehlt. Und was dich spaeter teuer ueberraschen koennte.",
    "[01:00.2] Dann wird aus dem Dossier ein teilbares Packet.",
    "[01:03.7] Fuer Familie, Partner, Agenten - und fuer Feedback, das endlich strukturiert zurueckkommt.",
    "[01:10.2] So gehst du nicht nervoes in die Besichtigung.",
    "[01:13.8] Du gehst vorbereitet hinein. Mit besseren Fragen. Mit weniger Druck. Mit mehr Kontrolle.",
    "[01:20.0] Stop browsing. Start deciding.",
    "[01:23.0] PropertyQuarry.",
    "[01:24.8] The decision layer for your next home.",
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
    voice_id = os.environ.get("PROPERTYQUARRY_UNMIXR_VOICE_ID", "").strip()
    if not voice_id and VARIANT:
        voice_id = UNMIXR_SMOOTHER_DE_VOICE_ID
    voice_id = voice_id or os.environ.get("UNMIXR_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        raise RuntimeError("unmixr_not_configured")
    config = {
        "api_key": api_key,
        "voice_id": voice_id,
        "language": os.environ.get("PROPERTYQUARRY_UNMIXR_LANGUAGE", "de-DE").strip() or "de-DE",
        "speaking_rate": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_RATE", "+8%" if VARIANT else "medium").strip() or "medium",
        "speaking_pitch": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_PITCH", "medium" if VARIANT else "low").strip() or "low",
        "speaking_volume": os.environ.get("PROPERTYQUARRY_UNMIXR_SPEAKING_VOLUME", "loud" if VARIANT else "medium").strip() or "medium",
    }
    intensity = os.environ.get("PROPERTYQUARRY_UNMIXR_INTENSITY", "28" if VARIANT else "").strip()
    if intensity:
        try:
            config["intensity"] = str(max(0, min(100, int(intensity))))
        except ValueError as exc:
            raise RuntimeError("invalid_propertyquarry_unmixr_intensity") from exc
    return config


def render_unmixr_tts(text: str, output: Path) -> bool:
    config = unmixr_config()
    request_payload = {
        "text": text,
        "voice_id": config["voice_id"],
        "language": config["language"],
        "speaking_rate": config["speaking_rate"],
        "speaking_pitch": config["speaking_pitch"],
        "speaking_volume": config["speaking_volume"],
        "output_type": output.suffix.lstrip(".") or "mp3",
        "response_type": "url",
    }
    if config.get("intensity"):
        request_payload["intensity"] = int(config["intensity"])
    payload = json.dumps(request_payload).encode("utf-8")
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
    audio_dir = OUT / f"audio{VARIANT_TAG}"
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
        str(VOICE_AUDIO if VARIANT else AUDIO),
    )
    return clips


def build_soundtrack() -> None:
    if not VARIANT:
        return
    sfx_times = [7.0, 15.0, 25.0, 36.0, 48.0, 60.0, 70.0, 80.0]
    hit_times = [15.5, 25.5, 36.5, 60.5, 70.5, 80.6]
    inputs = [
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=55:sample_rate=48000:duration={TARGET_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=110:sample_rate=48000:duration={TARGET_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:sample_rate=48000:duration={TARGET_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=48000:duration={TARGET_SECONDS}",
    ]
    filters = [
        "[0:a]volume=0.035,lowpass=f=180,afade=t=in:st=0:d=1.2[a0]",
        "[1:a]volume=0.024,lowpass=f=360,afade=t=in:st=0:d=2.0[a1]",
        "[2:a]volume=0.012,highpass=f=120,afade=t=in:st=0:d=2.8[a2]",
        "[3:a]volume=0.010,lowpass=f=1200,highpass=f=180,tremolo=f=2.2:d=0.35[noise]",
    ]
    labels = ["[a0]", "[a1]", "[a2]", "[noise]"]
    input_index = 4
    for effect_index, start in enumerate(sfx_times):
        inputs.extend(["-f", "lavfi", "-i", "anoisesrc=color=white:sample_rate=48000:duration=0.55"])
        delay = int(round(start * 1000))
        filters.append(
            f"[{input_index}:a]volume=0.020,highpass=f=900,lowpass=f=4200,"
            f"afade=t=in:st=0:d=0.05,afade=t=out:st=0.34:d=0.21,"
            f"adelay={delay}|{delay}[sfx{effect_index}]"
        )
        labels.append(f"[sfx{effect_index}]")
        input_index += 1
    for hit_index, start in enumerate(hit_times):
        inputs.extend(["-f", "lavfi", "-i", "sine=frequency=1320:sample_rate=48000:duration=0.10"])
        delay = int(round(start * 1000))
        filters.append(
            f"[{input_index}:a]volume=0.030,highpass=f=500,"
            f"afade=t=out:st=0.03:d=0.07,adelay={delay}|{delay}[hit{hit_index}]"
        )
        labels.append(f"[hit{hit_index}]")
        input_index += 1
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
        f"afade=t=out:st={TARGET_SECONDS - 2.2:.3f}:d=2.2,alimiter=limit=0.65[out]"
    )
    run(
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        str(SOUNDTRACK),
    )


def mix_voice_with_soundtrack() -> None:
    if not VARIANT:
        return
    run(
        "ffmpeg",
        "-y",
        "-i",
        str(VOICE_AUDIO),
        "-i",
        str(SOUNDTRACK),
        "-filter_complex",
        f"[0:a]volume=1.08,aformat=channel_layouts=stereo[voice];"
        f"[1:a]volume=0.70,aformat=channel_layouts=stereo[bed];"
        f"[voice][bed]amix=inputs=2:weights='1.0 0.55':normalize=0,"
        f"atrim=0:{TARGET_SECONDS:.3f},alimiter=limit=0.92[outa]",
        "-map",
        "[outa]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(AUDIO),
    )


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


def telegram_helper_path() -> Path:
    raw = os.environ.get("PROPERTYQUARRY_PROMO_TELEGRAM_HELPER", "").strip()
    if not raw:
        raise RuntimeError("telegram_helper_required:PROPERTYQUARRY_PROMO_TELEGRAM_HELPER")
    return Path(raw).expanduser().resolve()


def telegram_receipt_root() -> Path:
    raw = os.environ.get("PROPERTYQUARRY_PROMO_TELEGRAM_RECEIPT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (OUT / "telegram_delivery_receipts").resolve()


def send_telegram() -> dict[str, Any]:
    telegram_helper = telegram_helper_path()
    if not telegram_helper.is_file():
        raise RuntimeError(f"telegram_helper_missing:{telegram_helper}")
    receipt_name = f"propertyquarry_magicfit_promo{VARIANT_TAG}.telegram.receipt.json"
    caption = (
        "PropertyQuarry hero trailer V2. MagicFit scene render with smoother premium Unmixr narration, earlier voice entry, and music/SFX mix."
        if VARIANT
        else "PropertyQuarry hero trailer. MagicFit scene render with premium Unmixr narration. Telegram delivery encode; 4K master retained locally."
    )
    run(
        "python3",
        str(telegram_helper),
        str(TELEGRAM_FINAL),
        "--caption",
        caption,
        "--receipt-name",
        receipt_name,
    )
    receipt_root = telegram_receipt_root()
    receipt_path = receipt_root / receipt_name
    if not receipt_path.is_file():
        raise RuntimeError(f"telegram_receipt_missing:{receipt_path}")
    return json.loads(receipt_path.read_text(encoding="utf-8"))


def main() -> int:
    load_env(ROOT / ".env")
    load_env(EA_ROOT / ".env")
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
    if not SILENT.is_file():
        build_silent_video(scene_paths, [duration for _scene_id, duration in MAGICFIT_TIMELINE])
    voiceover_lines = (
        SMOOTHER_SALES_VOICEOVER_LINES
        if VARIANT in {"v2", "smoother_sales_v2", "audio_v2"}
        else list(packet.get("voiceover_lines") or [])
    )
    clips = build_audio(voiceover_lines)
    if VARIANT:
        build_soundtrack()
        mix_voice_with_soundtrack()
    mux()
    build_telegram_video()
    telegram_receipt = send_telegram()
    scene_receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sidecar_paths]
    receipt = {
        "generated_at_utc": utc_now(),
        "status": "published",
        "render_mode": "magicfit_per_scene_with_unmixr_narration",
        "audio_variant": VARIANT or "original",
        "provider_claim": "MagicFit",
        "magicfit_claim_allowed": True,
        "source_scene_count": len(scene_paths),
        "timeline_seconds": [{"scene_id": scene_id, "seconds": seconds} for scene_id, seconds in MAGICFIT_TIMELINE],
        "video_path": str(FINAL),
        "telegram_video_path": str(TELEGRAM_FINAL),
        "silent_video_path": str(SILENT),
        "voice_audio_path": str(VOICE_AUDIO if VARIANT else AUDIO),
        "soundtrack_path": str(SOUNDTRACK) if VARIANT else "",
        "audio_path": str(AUDIO),
        "subtitle_path": str(SRT),
        "duration_seconds": duration(FINAL),
        "voice_id": unmixr_config()["voice_id"],
        "voice_name": "Seraphina (Express)" if VARIANT else "",
        "voice_language": unmixr_config()["language"],
        "voice_style_request": "smoother, warmer, more emotional, lightly excited sales narration" if VARIANT else "",
        "voice_clip_count": len(clips),
        "magicfit_scene_receipts": [str(path) for path in sidecar_paths],
        "magicfit_video_output_urls": [str(receipt.get("video_output_url") or "") for receipt in scene_receipts],
        "telegram_receipt_path": str(telegram_receipt_root() / f"propertyquarry_magicfit_promo{VARIANT_TAG}.telegram.receipt.json"),
        "telegram_message_ids": list(telegram_receipt.get("message_ids") or []),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    TELEGRAM_RECEIPT.write_text(json.dumps(telegram_receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(FINAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
