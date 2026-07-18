from __future__ import annotations

import io
import json
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from scripts import generate_property_reconstruction as reconstruction


def _box(box_type: bytes, payload: bytes, *, extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, box_type, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _mvhd(*, version: int, timescale: int, duration: int) -> bytes:
    if version == 0:
        payload = struct.pack(">B3xIIII", 0, 0, 0, timescale, duration)
    elif version == 1:
        payload = struct.pack(">B3xQQIQ", 1, 0, 0, timescale, duration)
    else:
        raise AssertionError(version)
    return _box(b"mvhd", payload + (b"\x00" * 80))


@pytest.mark.parametrize(
    ("version", "timescale", "duration", "expected"),
    [
        (0, 1_000, 12_500, 12.5),
        (1, 90_000, 1_125_000, 12.5),
    ],
)
def test_mp4_duration_parser_reads_mvhd_without_ffprobe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
    timescale: int,
    duration: int,
    expected: float,
) -> None:
    path = tmp_path / "walkthrough.mp4"
    path.write_bytes(
        _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
        + _box(b"moov", _mvhd(version=version, timescale=timescale, duration=duration))
        + _box(b"mdat", b"payload", extended=True)
    )
    monkeypatch.setattr(
        reconstruction.shutil,
        "which",
        lambda _command: pytest.fail("duration parsing must not resolve ffprobe"),
    )

    assert reconstruction._video_duration_seconds(path) == expected


def test_mp4_duration_parser_fails_closed_on_malformed_box(tmp_path: Path) -> None:
    path = tmp_path / "malformed.mp4"
    path.write_bytes(struct.pack(">I4s", 100, b"moov") + b"short")

    assert reconstruction._video_duration_seconds(path) == 0.0


def test_mp4_duration_parser_rejects_non_faststart_layout(tmp_path: Path) -> None:
    path = tmp_path / "non-faststart.mp4"
    path.write_bytes(
        _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
        + _box(b"mdat", b"payload")
        + _box(b"moov", _mvhd(version=0, timescale=1_000, duration=5_000))
    )

    assert reconstruction._video_duration_seconds(path) == 0.0


def test_rgb24_frame_payload_has_exact_order_and_size(tmp_path: Path) -> None:
    red = tmp_path / "red.png"
    Image.new("RGB", (2, 2), (255, 0, 0)).save(red)

    assert reconstruction._rgb24_frame_bytes(red, frame_size=(2, 2)) == (
        bytes((255, 0, 0)) * 4
    )

    with pytest.raises(ValueError, match="raw_video_frame_size_invalid"):
        reconstruction._rgb24_frame_bytes(red, frame_size=(3, 2))

    with pytest.raises(SystemExit, match="source_image_invalid"):
        reconstruction._copy_normalized_image(
            red,
            tmp_path / "external-source-normalized.png",
        )


def test_encoder_contract_exposes_only_rawvideo_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "walkthrough.mp4"
    observed: dict[str, object] = {}
    monkeypatch.setattr(reconstruction.shutil, "which", lambda command: f"/narrow/{command}")

    class CapturedInput(io.BytesIO):
        def close(self) -> None:
            observed["stdin"] = self.getvalue()
            super().close()

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            observed["command"] = command
            observed["kwargs"] = kwargs
            self.stdin: CapturedInput | None = CapturedInput()
            self.returncode: int | None = None
            Path(command[-1]).write_bytes(
                _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
                + _box(b"moov", _mvhd(version=0, timescale=1_000, duration=10_000))
                + _box(b"mdat", b"payload")
            )

        def communicate(self) -> tuple[None, bytes]:
            if self.returncode is None:
                self.returncode = 0
            return None, b""

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(reconstruction.subprocess, "Popen", FakeProcess)
    red = Image.new("RGB", (2, 2), (255, 0, 0))
    blue = Image.new("RGB", (2, 2), (0, 0, 255))

    try:
        result = reconstruction._encode_rgb24_mp4(
            frames=(red, blue),
            target=target,
            frame_size=(2, 2),
            input_fps=1.2,
            output_fps=12,
            expected_input_frame_count=2,
            expected_frame_count=120,
            crf=18,
            timeout_seconds=120,
        )
    finally:
        red.close()
        blue.close()

    command = observed["command"]
    assert isinstance(command, list)
    assert result.returncode == 0
    assert observed["stdin"] == (bytes((255, 0, 0)) * 4) + (bytes((0, 0, 255)) * 4)
    assert command[0] == "/narrow/ffmpeg"
    assert command[command.index("-i") + 1] == "pipe:0"
    assert command[command.index("-pixel_format") + 1] == "rgb24"
    assert command[command.index("-f") + 1] == "rawvideo"
    assert command[-2] == "mp4"
    assert Path(command[-1]).name.startswith(f".{target.name}.")
    assert target.is_file()
    assert "libx264" in command
    assert "fps=12,format=yuv420p" in command
    assert command[command.index("-frames:v") + 1] == "120"
    assert not any("jpg" in argument or "image2" in argument for argument in command)


def test_encoder_nonzero_exit_removes_temporary_output_and_preserves_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "walkthrough.mp4"
    target.write_bytes(b"previous-video")
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")

    class FakeProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            self.stdin: io.BytesIO | None = io.BytesIO()
            self.returncode: int | None = None
            Path(command[-1]).write_bytes(b"partial-video")

        def communicate(self) -> tuple[None, bytes]:
            if self.returncode is None:
                self.returncode = 23
            return None, b"bounded encoder rejected input"

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(reconstruction.subprocess, "Popen", FakeProcess)
    frame = Image.new("RGB", (2, 2), (255, 0, 0))
    try:
        result = reconstruction._encode_rgb24_mp4(
            frames=(frame,),
            target=target,
            frame_size=(2, 2),
            input_fps=1.0,
            output_fps=1,
            expected_input_frame_count=1,
            expected_frame_count=1,
            crf=20,
            timeout_seconds=120,
        )
    finally:
        frame.close()

    assert result.returncode == 23
    assert result.stderr == b"bounded encoder rejected input"
    assert target.read_bytes() == b"previous-video"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_encoder_short_input_kills_process_and_removes_temporary_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "walkthrough.mp4"
    target.write_bytes(b"previous-video")
    observed: dict[str, bool] = {}
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")

    class FakeProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            self.stdin: io.BytesIO | None = io.BytesIO()
            self.returncode: int | None = None
            Path(command[-1]).write_bytes(b"partial-video")

        def communicate(self) -> tuple[None, bytes]:
            return None, b""

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            observed["killed"] = True
            self.returncode = -9

    monkeypatch.setattr(reconstruction.subprocess, "Popen", FakeProcess)

    with pytest.raises(ValueError, match="raw_video_input_frame_count_invalid"):
        reconstruction._encode_rgb24_mp4(
            frames=(),
            target=target,
            frame_size=(2, 2),
            input_fps=1.0,
            output_fps=1,
            expected_input_frame_count=1,
            expected_frame_count=1,
            crf=20,
            timeout_seconds=120,
        )

    assert observed == {"killed": True}
    assert target.read_bytes() == b"previous-video"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_encoder_timeout_kills_process_and_removes_temporary_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "walkthrough.mp4"
    target.write_bytes(b"previous-video")
    observed: dict[str, bool] = {}
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")

    class FakeProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            self.stdin: io.BytesIO | None = io.BytesIO()
            self.returncode: int | None = None
            Path(command[-1]).write_bytes(b"partial-video")

        def communicate(self) -> tuple[None, bytes]:
            return None, b""

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            observed["killed"] = True
            self.returncode = -9

    class ImmediateTimer:
        daemon = False

        def __init__(self, _seconds: int, callback: object) -> None:
            self.callback = callback

        def start(self) -> None:
            assert callable(self.callback)
            self.callback()

        def cancel(self) -> None:
            observed["timer_cancelled"] = True

    monkeypatch.setattr(reconstruction.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(reconstruction.threading, "Timer", ImmediateTimer)
    frame = Image.new("RGB", (2, 2), (255, 0, 0))
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            reconstruction._encode_rgb24_mp4(
                frames=(frame,),
                target=target,
                frame_size=(2, 2),
                input_fps=1.0,
                output_fps=1,
                expected_input_frame_count=1,
                expected_frame_count=1,
                crf=20,
                timeout_seconds=120,
            )
    finally:
        frame.close()

    assert observed == {"killed": True, "timer_cancelled": True}
    assert target.read_bytes() == b"previous-video"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_encoder_broken_pipe_cleanup_survives_communicate_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "walkthrough.mp4"
    target.write_bytes(b"previous-video")
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")

    class BrokenInput(io.BytesIO):
        def write(self, _payload: bytes) -> int:
            raise BrokenPipeError("encoder closed input")

    class FakeProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            self.stdin: BrokenInput | None = BrokenInput()
            self.returncode: int | None = None
            self.communicate_count = 0
            Path(command[-1]).write_bytes(b"partial-video")

        def communicate(self) -> tuple[None, bytes]:
            self.communicate_count += 1
            if self.communicate_count == 1:
                raise OSError("stderr pipe interrupted")
            return None, b""

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(reconstruction.subprocess, "Popen", FakeProcess)
    frame = Image.new("RGB", (2, 2), (255, 0, 0))
    try:
        with pytest.raises(OSError, match="stderr pipe interrupted"):
            reconstruction._encode_rgb24_mp4(
                frames=(frame,),
                target=target,
                frame_size=(2, 2),
                input_fps=1.0,
                output_fps=1,
                expected_input_frame_count=1,
                expected_frame_count=1,
                crf=20,
                timeout_seconds=120,
            )
    finally:
        frame.close()

    assert target.read_bytes() == b"previous-video"
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_ffmpeg_failure_receipt_hashes_private_diagnostic_without_reflecting_it(
    tmp_path: Path,
) -> None:
    diagnostic = f"failed to open {tmp_path}/operator-private/source.rgb24".encode()
    result = reconstruction._ffmpeg_failure_receipt(
        subprocess.CompletedProcess(
            ["ffmpeg"],
            23,
            stdout=b"",
            stderr=diagnostic,
        )
    )

    assert result["status"] == "failed"
    assert result["reason"] == "ffmpeg_exit_nonzero"
    assert result["returncode"] == 23
    assert result["diagnostic_size_bytes"] == len(diagnostic)
    assert len(str(result["diagnostic_sha256"])) == 64
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)


def test_stop_card_walkthrough_discards_encoder_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(source)
    target = tmp_path / "walkthrough.mp4"
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")
    monkeypatch.setattr(
        reconstruction,
        "_encode_rgb24_mp4",
        lambda **_kwargs: (_ for _ in ()).throw(
            OSError(f"failed under {tmp_path}/operator-private")
        ),
    )

    result = reconstruction._write_stop_card_walkthrough(
        target,
        [source],
        route_labels=["Living room"],
    )

    assert result == {"status": "failed", "reason": "raw_video_failed"}
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)


def test_stop_card_walkthrough_enforces_duration_budget_and_clears_stale_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(source)
    target = tmp_path / "walkthrough.mp4"
    sidecar = target.with_suffix(".quality.json")
    target.write_bytes(b"stale-video")
    sidecar.write_text("stale-sidecar", encoding="utf-8")
    monkeypatch.setattr(reconstruction.shutil, "which", lambda _command: "/narrow/ffmpeg")
    monkeypatch.setenv(
        "PROPERTYQUARRY_RECONSTRUCTION_WALKTHROUGH_SECONDS_PER_STOP",
        "5",
    )

    result = reconstruction._write_stop_card_walkthrough(
        target,
        [source],
        route_labels=[f"Room {index}" for index in range(49)],
    )

    assert result == {
        "status": "failed",
        "reason": "walkthrough_duration_limit_exceeded",
    }
    assert not target.exists()
    assert not sidecar.exists()
    assert not list(tmp_path.rglob("*.rgb24"))
