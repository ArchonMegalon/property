from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, sync_playwright

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


def _write_floorplan_png(path: Path) -> None:
    image = Image.new("RGB", (1280, 900), (248, 246, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1200, 820), outline=(42, 42, 42), width=8)
    draw.line((420, 80, 420, 820), fill=(58, 58, 58), width=6)
    draw.line((80, 410, 1200, 410), fill=(58, 58, 58), width=6)
    draw.rectangle((450, 120, 1110, 360), outline=(148, 68, 48), width=6)
    draw.rectangle((110, 120, 380, 360), outline=(73, 108, 170), width=6)
    draw.rectangle((110, 450, 380, 770), outline=(73, 108, 170), width=6)
    draw.rectangle((450, 450, 1110, 770), outline=(148, 68, 48), width=6)
    draw.text((150, 210), "Entry", fill=(30, 30, 30))
    draw.text((690, 220), "Living", fill=(30, 30, 30))
    draw.text((160, 600), "Bath", fill=(30, 30, 30))
    draw.text((720, 600), "Bedroom", fill=(30, 30, 30))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_cube_face_png(path: Path, *, label: str, fill: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (1024, 1024), fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((36, 36, 988, 988), outline=(248, 245, 240), width=14)
    draw.text((84, 104), "PropertyQuarry", fill=(255, 255, 255))
    draw.text((84, 180), label, fill=(250, 247, 242))
    draw.rectangle((120, 280, 904, 760), outline=(255, 255, 255), width=10)
    draw.rectangle((180, 340, 500, 720), fill=(235, 231, 224))
    draw.rectangle((548, 340, 840, 720), fill=(198, 166, 122))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_h264_flythrough(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=#d8d0c4:s=1280x720:d=3",
        "-vf",
        (
            "drawbox=x=0:y=0:w=iw:h=110:color=#181a1dcc:t=fill,"
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            "text='PropertyQuarry Flythrough':fontcolor=white:fontsize=34:x=48:y=40,"
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
            "text='Interior route':fontcolor=#ece6df:fontsize=20:x=52:y=82,"
            "drawbox=x='120+220*t':y='250+30*sin(t*2)':w=820:h=210:color=#a46842:t=6,"
            "drawbox=x='170+220*t':y='300+28*sin(t*2)':w=330:h=110:color=#5a7bb2:t=fill,"
            "drawbox=x='560+220*t':y='300+20*sin(t*2)':w=250:h=110:color=#e7e3dc:t=fill,"
            "drawbox=x='845+220*t':y='300+14*sin(t*2)':w=90:h=110:color=#88a36f:t=fill"
        ),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _video_frame_brightness(page) -> float:
    return float(
        page.evaluate(
            """() => {
                const video = document.getElementById('flythrough-video');
                if (!video || !video.videoWidth || !video.videoHeight) return 0;
                const canvas = document.createElement('canvas');
                canvas.width = Math.min(video.videoWidth, 160);
                canvas.height = Math.min(video.videoHeight, 90);
                const ctx = canvas.getContext('2d');
                if (!ctx) return 0;
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                let total = 0;
                for (let index = 0; index < data.length; index += 4) {
                    total += (data[index] + data[index + 1] + data[index + 2]) / 3;
                }
                return total / (data.length / 4);
            }"""
        )
    )


@pytest.fixture()
def public_tour_browser_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "real-browser-floorplan-tour"
    bundle_dir = bundle_root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write_floorplan_png(bundle_dir / "floorplan-01.png")
    _write_h264_flythrough(bundle_dir / "tour.mp4")
    cube_faces: dict[str, str] = {}
    for face, label, fill in (
        ("f", "Living room", (108, 82, 59)),
        ("r", "Kitchen view", (86, 114, 148)),
        ("b", "Hall view", (110, 98, 124)),
        ("l", "Bedroom view", (124, 92, 72)),
        ("u", "Ceiling", (154, 164, 180)),
        ("d", "Floor", (86, 78, 64)),
    ):
        filename = f"cube-{face}.png"
        _write_cube_face_png(bundle_dir / filename, label=label, fill=fill)
        cube_faces[face] = filename
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Real Browser Floorplan Tour",
                "display_title": "Real Browser Floorplan Tour",
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "brand_name": "PropertyQuarry",
                "scene_strategy": "pure_360_cube",
                "creation_mode": "hosted_floorplan_tour",
                "video_relpath": "tour.mp4",
                "scenes": [
                    {
                        "scene_id": "panorama-1",
                        "name": "Living room anchor",
                        "role": "pure_360",
                        "cube_faces": cube_faces,
                        "image_url": "cube-f.png",
                    },
                    {
                        "scene_id": "floorplan-1",
                        "name": "Main floorplan",
                        "role": "floorplan",
                        "asset_relpath": "floorplan-01.png",
                        "mime_type": "image/png",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(bundle_root))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_API_TOKEN", raising=False)

    app = create_app()
    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    local_base_url = f"http://127.0.0.1:{port}"
    browser_base_url = f"http://propertyquarry.com:{port}"
    _wait_for_http(local_base_url)
    try:
        yield {"base_url": browser_base_url, "slug": slug}
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--host-resolver-rules=MAP propertyquarry.com 127.0.0.1",
                "--no-proxy-server",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        try:
            yield browser
        finally:
            browser.close()


def _new_context(browser: Browser, *, mobile: bool = False) -> BrowserContext:
    return browser.new_context(
        viewport={"width": 430 if mobile else 1440, "height": 932 if mobile else 1000},
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
            if mobile
            else None
        ),
    )


def test_public_tour_panorama_lane_opens_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}"

    page.goto(url, wait_until="networkidle")
    page.locator("h1").wait_for()
    assert "PropertyQuarry" in page.locator("body").inner_text()
    page.wait_for_timeout(1500)
    status_text = page.locator("#tour-status").inner_text()
    assert "Panorama" in status_text or "fallback" in status_text.lower()
    cube = page.locator("#cube")
    cube.wait_for()
    assert cube.is_visible()
    has_canvas_or_fallback = bool(
        page.evaluate(
            """() => {
                const cube = document.getElementById('cube');
                if (!cube) return false;
                return Boolean(cube.querySelector('canvas, .viewer-empty'));
            }"""
        )
    )
    assert has_canvas_or_fallback
    assert not [
        message
        for message in console_errors
        if "failed to load resource" in message.lower()
        or "refused" in message.lower()
        or "propertyquarry panorama init failed" in message.lower()
    ]
    context.close()


def test_public_tour_floorplan_lane_renders_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}?pane=floorplan-pane"

    page.goto(url, wait_until="networkidle")
    expect_title = page.locator("h1")
    expect_title.wait_for()
    assert "PropertyQuarry" in page.locator("body").inner_text()
    assert page.locator("#floorplan-pane").is_visible()
    floorplan_image = page.locator("#floorplan-image")
    floorplan_image.wait_for()
    assert floorplan_image.is_visible()
    natural_width = page.evaluate("() => document.getElementById('floorplan-image')?.naturalWidth || 0")
    assert natural_width >= 1000
    status_text = page.locator("#tour-status").inner_text()
    assert "Floorplan" in status_text
    assert not [message for message in console_errors if "Failed to load resource" in message or "Refused" in message]
    context.close()


def test_public_tour_flythrough_video_decodes_and_advances_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}?pane=flythrough-pane&autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#flythrough-video")
    video.wait_for()
    assert video.is_visible()
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('flythrough-video');
            return video ? {
                currentTime: video.currentTime,
                duration: video.duration,
                readyState: video.readyState,
                videoWidth: video.videoWidth,
                paused: video.paused,
            } : null;
        }"""
    )
    assert state is not None
    assert state["readyState"] >= 2
    assert state["videoWidth"] >= 640
    assert state["currentTime"] > 0.2
    assert state["duration"] >= 2.5
    assert _video_frame_brightness(page) > 10.0
    assert "Flythrough" in page.locator("#tour-status").inner_text()
    assert not [message for message in console_errors if "MEDIA" in message.upper() or "decode" in message.lower()]
    context.close()


def test_public_tour_flythrough_video_decodes_on_mobile_viewport(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser, mobile=True)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}?pane=flythrough-pane&autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#flythrough-video")
    video.wait_for()
    assert video.is_visible()
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('flythrough-video');
            return video ? {
                currentTime: video.currentTime,
                readyState: video.readyState,
                videoWidth: video.videoWidth,
            } : null;
        }"""
    )
    assert state is not None
    assert state["readyState"] >= 2
    assert state["videoWidth"] >= 640
    assert state["currentTime"] > 0.2
    assert _video_frame_brightness(page) > 10.0
    assert not [
        message
        for message in console_errors
        if "decode" in message.lower() or "media" in message.lower() or "refused" in message.lower()
    ]
    context.close()
