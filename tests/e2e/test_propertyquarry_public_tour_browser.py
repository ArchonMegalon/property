from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
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


def _write_photo_panel(path: Path, *, label: str, fill: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (960, 720), fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((44, 44, 916, 676), outline=(248, 245, 240), width=10)
    draw.rectangle((108, 160, 452, 612), fill=(236, 232, 226))
    draw.rectangle((520, 160, 852, 612), fill=(196, 168, 128))
    draw.text((88, 88), label, fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=92)


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


def _generate_reconstruction_bundle(*, bundle_root: Path, slug: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    bundle_dir = bundle_root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Generated Reconstruction Browser Tour",
                "display_title": "Generated Reconstruction Browser Tour",
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    source_dir = bundle_dir / "_generator-source"
    source_dir.mkdir(parents=True, exist_ok=True)
    floorplan_path = source_dir / "floorplan.jpg"
    photo_one_path = source_dir / "photo-01.jpg"
    photo_two_path = source_dir / "photo-02.jpg"
    _write_floorplan_png(floorplan_path)
    _write_photo_panel(photo_one_path, label="Living reference", fill=(112, 86, 62))
    _write_photo_panel(photo_two_path, label="Bedroom reference", fill=(84, 104, 122))
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(bundle_root)
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "generate_property_reconstruction.py"),
            "--slug",
            slug,
            "--floorplan",
            str(floorplan_path),
            "--photo",
            str(photo_one_path),
            "--photo",
            str(photo_two_path),
            "--skip-video",
        ],
        cwd=repo_root,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )


def _video_frame_brightness(page) -> float:
    return float(
        page.evaluate(
            """() => {
                const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
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


def _video_playback_profile(page) -> dict[str, list[float]]:
    return dict(
        page.evaluate(
            """async () => {
                const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
                if (!video || !video.videoWidth || !video.videoHeight) {
                    return { times: [], presentedFrames: [], droppedFrames: [], frameSignatures: [] };
                }
                const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
                const canvas = document.createElement('canvas');
                canvas.width = Math.min(video.videoWidth, 96);
                canvas.height = Math.min(video.videoHeight, 54);
                const ctx = canvas.getContext('2d');
                const frameSignature = () => {
                    if (!ctx) return 0;
                    try {
                        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                        let total = 0;
                        const stride = Math.max(4, Math.floor(data.length / 120));
                        for (let index = 0; index < data.length; index += stride) {
                            total = (total + (data[index] || 0) * 3 + (data[index + 1] || 0) * 5 + (data[index + 2] || 0) * 7) % 1000003;
                        }
                        return total;
                    } catch (_error) {
                        return 0;
                    }
                };
                const sample = () => {
                    const quality = typeof video.getVideoPlaybackQuality === 'function'
                        ? video.getVideoPlaybackQuality()
                        : null;
                    return {
                        time: Number(video.currentTime || 0),
                        presentedFrames: Number(quality?.totalVideoFrames || 0),
                        droppedFrames: Number(quality?.droppedVideoFrames || 0),
                        frameSignature: Number(frameSignature() || 0),
                    };
                };
                if (Number(video.duration || 0) > 0.8) {
                    try {
                        video.currentTime = 0.2;
                        await wait(120);
                    } catch (_error) {
                        /* keep going if headless seek behaves differently */
                    }
                }
                await video.play().catch(() => null);
                const captures = [sample()];
                for (let index = 0; index < 4; index += 1) {
                    await wait(320);
                    captures.push(sample());
                }
                return {
                    times: captures.map((capture) => capture.time),
                    presentedFrames: captures.map((capture) => capture.presentedFrames),
                    droppedFrames: captures.map((capture) => capture.droppedFrames),
                    frameSignatures: captures.map((capture) => capture.frameSignature),
                };
            }"""
        )
    )


def _canvas_visual_metrics(page, selector: str) -> dict[str, float]:
    _ = selector
    metrics = dict(
        page.evaluate(
            """() => {
                const debug = window.__pqReconstructionDebug;
                if (!debug || typeof debug.getRenderMetrics !== 'function') {
                    return { ready: false, reason: 'debug_hook_missing' };
                }
                return debug.getRenderMetrics();
            }"""
        )
        or {}
    )
    return {
        "ready": bool(metrics.get("ready")),
        "frame_count": float(metrics.get("frameCount") or 0),
        "wall_rect_count": float(metrics.get("wallRectCount") or 0),
        "wall_mesh_count": float(metrics.get("wallMeshCount") or 0),
        "visible_wall_count": float(metrics.get("visibleWallCount") or 0),
        "scene_child_count": float(metrics.get("sceneChildCount") or 0),
        "projected_coverage_pct": float(metrics.get("projectedCoveragePct") or 0),
        "max_projected_wall_pct": float(metrics.get("maxProjectedWallPct") or 0),
        "render_calls": float(metrics.get("renderCalls") or 0),
        "render_triangles": float(metrics.get("renderTriangles") or 0),
        "width": float(metrics.get("sampleWidth") or 0),
        "height": float(metrics.get("sampleHeight") or 0),
    }


def _wait_for_reconstruction_viewer_ready(page, *, timeout: int = 30000) -> None:
    page.wait_for_function(
        """() => {
            const canvas = document.querySelector('#viewport canvas');
            const debug = window.__pqReconstructionDebug;
            if (!canvas || !debug || typeof debug.getRenderMetrics !== 'function') {
                return false;
            }
            const metrics = debug.getRenderMetrics();
            return Boolean(metrics?.ready && Number(metrics?.frameCount || 0) >= 2);
        }""",
        timeout=timeout,
    )


def _click_viewer_control(page, selector: str) -> None:
    box = page.evaluate(
        """(selector) => {
            const node = document.querySelector(selector);
            if (!node) return null;
            const rect = node.getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        }""",
        selector,
    )
    assert box is not None, f"missing viewer control: {selector}"
    assert box["width"] > 0 and box["height"] > 0, f"hidden viewer control: {selector}"
    page.mouse.click(box["x"] + (box["width"] / 2), box["y"] + (box["height"] / 2))


@pytest.fixture()
def public_tour_browser_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "real-browser-floorplan-tour"
    bundle_dir = bundle_root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write_floorplan_png(bundle_dir / "floorplan-01.png")
    _write_h264_flythrough(bundle_dir / "tour.mp4")
    _write_cube_face_png(bundle_dir / "scene-01.png", label="Living room", fill=(108, 82, 59))
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Real Browser Floorplan Tour",
                "display_title": "Real Browser Floorplan Tour",
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "matterport_url": "https://my.matterport.com/show/?m=REALBROWSER123",
                "brand_name": "PropertyQuarry",
                "scene_strategy": "layout_first",
                "creation_mode": "hosted_floorplan_tour",
                "video_relpath": "tour.mp4",
                "scenes": [
                    {
                        "scene_id": "panorama-1",
                        "name": "Living room anchor",
                        "role": "photo",
                        "asset_relpath": "scene-01.png",
                        "image_url": "scene-01.png",
                        "mime_type": "image/png",
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
    video_slug = "real-browser-video-tour"
    video_bundle_dir = bundle_root / video_slug
    video_bundle_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_dir / "floorplan-01.png", video_bundle_dir / "floorplan-01.png")
    shutil.copy2(bundle_dir / "tour.mp4", video_bundle_dir / "tour.mp4")
    shutil.copy2(bundle_dir / "scene-01.png", video_bundle_dir / "scene-01.png")
    (video_bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": video_slug,
                "title": "Real Browser Video Tour",
                "display_title": "Real Browser Video Tour",
                "hosted_url": f"https://propertyquarry.com/tours/{video_slug}",
                "public_url": f"https://propertyquarry.com/tours/{video_slug}",
                "brand_name": "PropertyQuarry",
                "scene_strategy": "layout_first",
                "creation_mode": "hosted_floorplan_tour",
                "video_relpath": "tour.mp4",
                "scenes": [
                    {
                        "scene_id": "panorama-1",
                        "name": "Living room anchor",
                        "role": "photo",
                        "asset_relpath": "scene-01.png",
                        "image_url": "scene-01.png",
                        "mime_type": "image/png",
                    },
                    {
                        "scene_id": "floorplan-1",
                        "name": "Main floorplan",
                        "role": "floorplan",
                        "asset_relpath": "floorplan-01.png",
                        "mime_type": "image/png",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    generated_reconstruction_slug = "generated-reconstruction-browser-tour"
    _generate_reconstruction_bundle(bundle_root=bundle_root, slug=generated_reconstruction_slug)
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
        yield {
            "base_url": browser_base_url,
            "slug": slug,
            "video_slug": video_slug,
            "generated_reconstruction_slug": generated_reconstruction_slug,
        }
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


def _stub_matterport_provider(context: BrowserContext) -> None:
    context.route(
        "**://my.matterport.com/**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=(
                "<!doctype html><html><body style='margin:0;background:#f5f0e8;"
                "display:grid;place-items:center;font:16px ui-sans-serif,sans-serif;color:#3c3124'>"
                "Matterport provider stub"
                "</body></html>"
            ),
        ),
    )


def _assert_no_horizontal_overflow(page) -> None:
    overflow = page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
        })"""
    )
    assert overflow["scrollWidth"] <= overflow["innerWidth"] + 1, overflow
    assert overflow["bodyScrollWidth"] <= overflow["innerWidth"] + 1, overflow


def _assert_visible_controls_meet_mobile_target_floor(page, *, floor_px: int = 44) -> None:
    undersized = page.evaluate(
        """(floorPx) => Array.from(document.querySelectorAll('button, a[href]'))
          .filter((node) => {
            const style = window.getComputedStyle(node);
            const box = node.getBoundingClientRect();
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && !node.hidden
              && box.width > 0
              && box.height > 0;
          })
          .map((node) => {
            const box = node.getBoundingClientRect();
            return {
              text: (node.textContent || node.getAttribute('aria-label') || '').trim(),
              width: box.width,
              height: box.height,
            };
          })
          .filter((item) => item.height < floorPx || item.width < floorPx)
        """,
        floor_px,
    )
    assert undersized == []


def test_public_tour_panorama_lane_opens_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}"

    page.goto(url, wait_until="networkidle")
    page.locator("h1").wait_for()
    assert "Property Tour" not in page.locator("body").inner_text()
    page.wait_for_timeout(1500)
    viewer = page.locator("#viewer")
    viewer.wait_for()
    assert viewer.is_visible()
    assert page.locator("#stage-role").inner_text().lower() == "photo"
    assert page.locator("#stage-image").is_visible()
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
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}?pane=floorplan-pane"

    page.goto(url, wait_until="networkidle")
    expect_title = page.locator("h1")
    expect_title.wait_for()
    assert "Property Tour" not in page.locator("body").inner_text()
    page.locator('#role-filter button[data-role="floorplan"]').click()
    assert page.locator("#stage-role").inner_text().lower() == "floorplan"
    floorplan_image = page.locator("#stage-image")
    assert floorplan_image.is_visible()
    page.wait_for_function(
        """() => {
            const image = document.getElementById('stage-image');
            return Boolean(image && image.naturalWidth >= 1000);
        }"""
    )
    natural_width = page.evaluate("() => document.getElementById('stage-image')?.naturalWidth || 0")
    assert natural_width >= 1000
    assert not [message for message in console_errors if "Failed to load resource" in message or "Refused" in message]
    context.close()


def test_public_tour_flythrough_video_decodes_and_advances_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['video_slug']}?pane=flythrough-pane&autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#tour-video")
    video.wait_for()
    assert video.is_visible()
    page.evaluate("() => document.getElementById('tour-video')?.play()?.catch(() => null)")
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
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
    profile = _video_playback_profile(page)
    assert len(profile["times"]) == 5
    assert all(later >= earlier for earlier, later in zip(profile["times"], profile["times"][1:])), profile
    assert profile["times"][-1] - profile["times"][0] >= 0.6, profile
    assert len(profile["presentedFrames"]) == 5
    assert all(
        later >= earlier for earlier, later in zip(profile["presentedFrames"], profile["presentedFrames"][1:])
    ), profile
    presented_delta = profile["presentedFrames"][-1] - profile["presentedFrames"][0]
    assert len(profile["frameSignatures"]) == 5
    assert len(profile["droppedFrames"]) == 5
    dropped_delta = profile["droppedFrames"][-1] - profile["droppedFrames"][0]
    if presented_delta > 0:
        assert presented_delta >= 6, profile
        assert dropped_delta < presented_delta, profile
        assert dropped_delta <= max(16, presented_delta * 0.8), profile
    else:
        distinct_signatures = len(set(profile["frameSignatures"]))
        assert distinct_signatures >= 2, profile
        assert profile["frameSignatures"][-1] != profile["frameSignatures"][0], profile
        assert dropped_delta <= 16, profile
    assert page.locator("#tour-video source").get_attribute("type") == "video/mp4"
    assert not [message for message in console_errors if "MEDIA" in message.upper() or "decode" in message.lower()]
    context.close()


def test_public_tour_provider_control_is_mobile_safe_and_opens_vendor_immediately(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser, mobile=True)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = (
        f"{public_tour_browser_server['base_url']}/tours/"
        f"{public_tour_browser_server['slug']}/control/matterport?pane=floorplan-pane"
    )

    page.goto(url, wait_until="networkidle")
    page.locator("h1").wait_for()
    assert "Property Tour" not in page.locator("body").inner_text()
    assert page.locator(".badge").inner_text().lower() == "3d tour"
    assert "Matterport control" not in page.locator("body").inner_text()
    assert "MagicFit" not in page.locator("body").inner_text()
    assert page.locator("#load-provider").count() == 0
    assert page.locator(".provider-frame").get_attribute("src") == "https://my.matterport.com/show/?m=REALBROWSER123"
    assert page.locator(".provider-frame").get_attribute("data-src") == "https://my.matterport.com/show/?m=REALBROWSER123"
    assert page.locator("#tour-video").count() == 0
    assert page.get_by_role("link", name="Open walkthrough").is_visible()
    assert page.get_by_role("link", name="Open walkthrough").get_attribute("href").endswith(
        f"/tours/{public_tour_browser_server['slug']}/walkthrough"
    )
    assert page.locator("#stage-role").inner_text().lower() == "floorplan"
    floorplan_image = page.locator("#stage-image")
    assert floorplan_image.is_visible()
    page.wait_for_function(
        """() => {
            const image = document.getElementById('stage-image');
            return Boolean(image && image.naturalWidth >= 1000);
        }"""
    )
    natural_width = page.evaluate("() => document.getElementById('stage-image')?.naturalWidth || 0")
    assert natural_width >= 1000
    _assert_no_horizontal_overflow(page)
    _assert_visible_controls_meet_mobile_target_floor(page)
    assert not [
        message
        for message in console_errors
        if "failed to load resource" in message.lower()
        or "refused" in message.lower()
        or "decode" in message.lower()
        or "media" in message.lower()
    ]
    context.close()


def test_public_tour_flythrough_video_decodes_on_mobile_viewport(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser, mobile=True)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['video_slug']}?pane=flythrough-pane&autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#tour-video")
    video.wait_for()
    assert video.is_visible()
    page.evaluate("() => document.getElementById('tour-video')?.play()?.catch(() => null)")
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
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
    profile = _video_playback_profile(page)
    assert len(profile["times"]) == 5
    assert all(later >= earlier for earlier, later in zip(profile["times"], profile["times"][1:])), profile
    assert profile["times"][-1] - profile["times"][0] >= 0.6, profile
    assert len(profile["presentedFrames"]) == 5
    assert all(
        later >= earlier for earlier, later in zip(profile["presentedFrames"], profile["presentedFrames"][1:])
    ), profile
    presented_delta = profile["presentedFrames"][-1] - profile["presentedFrames"][0]
    assert len(profile["frameSignatures"]) == 5
    assert len(profile["droppedFrames"]) == 5
    dropped_delta = profile["droppedFrames"][-1] - profile["droppedFrames"][0]
    if presented_delta > 0:
        assert presented_delta >= 6, profile
        assert dropped_delta < presented_delta, profile
        assert dropped_delta <= max(16, presented_delta * 0.8), profile
    else:
        distinct_signatures = len(set(profile["frameSignatures"]))
        assert distinct_signatures >= 2, profile
        assert profile["frameSignatures"][-1] != profile["frameSignatures"][0], profile
        assert dropped_delta <= 16, profile
    assert not [
        message
        for message in console_errors
        if "decode" in message.lower() or "media" in message.lower() or "refused" in message.lower()
    ]
    context.close()


def test_generated_reconstruction_viewer_routes_to_clean_unavailable_shell(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    slug = str(public_tour_browser_server["generated_reconstruction_slug"])
    url = f"{public_tour_browser_server['base_url']}/tours/files/{slug}/generated-reconstruction/viewer.html"

    response = page.goto(url, wait_until="networkidle")
    assert response is not None
    assert response.status == 404
    assert page.url.endswith(f"/tours/{slug}")
    body_text = page.locator("body").inner_text()
    assert "This tour link is no longer available." in body_text
    assert "This old link no longer opens as a 3D tour." in body_text
    assert page.locator("canvas").count() == 0
    assert "Layout preview" not in body_text
    assert "generated-reconstruction/viewer.html" not in body_text
    assert not page_errors
    assert not [
        message
        for message in console_errors
        if "failed to resolve module specifier" in message.lower()
        or "cannot use import statement" in message.lower()
        or ("webgl" in message.lower() and "context lost" in message.lower())
    ]
    context.close()


def test_generated_reconstruction_viewer_mobile_routes_to_clean_unavailable_shell(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser, mobile=True)
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    slug = str(public_tour_browser_server["generated_reconstruction_slug"])
    url = f"{public_tour_browser_server['base_url']}/tours/files/{slug}/generated-reconstruction/viewer.html"

    response = page.goto(url, wait_until="networkidle")
    assert response is not None
    assert response.status == 404
    assert page.url.endswith(f"/tours/{slug}")
    _assert_no_horizontal_overflow(page)
    _assert_visible_controls_meet_mobile_target_floor(page)
    body_text = page.locator("body").inner_text()
    assert "This tour link is no longer available." in body_text
    assert "This old link no longer opens as a 3D tour." in body_text
    assert page.locator("canvas").count() == 0
    assert "Layout preview" not in body_text
    assert "generated-reconstruction/viewer.html" not in body_text
    assert not page_errors
    assert not [
        message
        for message in console_errors
        if "failed to resolve module specifier" in message.lower()
        or "cannot use import statement" in message.lower()
    ]
    context.close()
