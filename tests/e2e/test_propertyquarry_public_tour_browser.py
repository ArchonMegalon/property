from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, sync_playwright

Config = uvicorn.Config
Server = uvicorn.Server

from app.api.app import create_app
from scripts import generate_property_reconstruction as reconstruction_script


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


def _wait_for_url(url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"url {url} did not become ready in time")


def _play_tour_video_without_waiting(page) -> bool:
    return bool(
        page.evaluate(
            """() => {
                const video = document.getElementById('tour-video');
                if (!video) return false;
                const playPromise = video.play();
                if (playPromise && typeof playPromise.catch === 'function') {
                    playPromise.catch(() => null);
                }
                return true;
            }"""
        )
    )


class _SilentStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _disable_public_tour_fixture_startup_prewarm(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import app as app_module

    async def _skip_startup_prewarm() -> None:
        return

    # These browser fixtures verify the public tour surfaces, not the property-search shell cache.
    # Skip unrelated startup prewarm work so the local ASGI server becomes ready deterministically.
    monkeypatch.setattr(app_module, "_prewarm_property_search_surface_cache", _skip_startup_prewarm)
    monkeypatch.setattr(app_module, "_prewarm_provider_health_cache", _skip_startup_prewarm)


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


def _reconstruction_generation_timeout_seconds(*, skip_video: bool) -> int:
    raw_timeout = str(
        os.getenv("PROPERTYQUARRY_E2E_RECONSTRUCTION_TIMEOUT_SECONDS")
        or os.getenv("PROPERTYQUARRY_RECONSTRUCTION_TIMEOUT_SECONDS")
        or ""
    ).strip()
    try:
        requested_timeout = int(float(raw_timeout)) if raw_timeout else 0
    except Exception:
        requested_timeout = 0
    minimum_timeout = 180 if skip_video else 600
    return max(minimum_timeout, requested_timeout)


def _generate_reconstruction_bundle(
    *,
    bundle_root: Path,
    slug: str,
    skip_video: bool = True,
    room_labels: tuple[str, ...] | list[str] | None = ("entry/hall", "living room", "bedroom"),
    photo_specs: tuple[tuple[str, tuple[int, int, int]], ...] | list[tuple[str, tuple[int, int, int]]] | None = None,
    manifest_patch: dict[str, object] | None = None,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    bundle_dir = bundle_root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "slug": slug,
        "title": "Generated Reconstruction Browser Tour",
        "display_title": "Generated Reconstruction Browser Tour",
        "hosted_url": f"https://propertyquarry.com/tours/{slug}",
        "public_url": f"https://propertyquarry.com/tours/{slug}",
    }
    if manifest_patch:
        manifest.update(manifest_patch)
    (bundle_dir / "tour.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    source_dir = bundle_dir / "_generator-source"
    source_dir.mkdir(parents=True, exist_ok=True)
    floorplan_path = source_dir / "floorplan.jpg"
    _write_floorplan_png(floorplan_path)
    normalized_photo_specs = list(photo_specs or [("Living reference", (112, 86, 62)), ("Bedroom reference", (84, 104, 122))])
    photo_paths: list[Path] = []
    for index, (label, fill) in enumerate(normalized_photo_specs, start=1):
        photo_path = source_dir / f"photo-{index:02d}.jpg"
        _write_photo_panel(photo_path, label=label, fill=fill)
        photo_paths.append(photo_path)
    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(bundle_root)
    command = [
        sys.executable,
        str(repo_root / "scripts" / "generate_property_reconstruction.py"),
        "--slug",
        slug,
        "--floorplan",
        str(floorplan_path),
    ]
    for photo_path in photo_paths:
        command.extend(["--photo", str(photo_path)])
    for room_label in list(room_labels or []):
        command.extend(["--room-label", str(room_label)])
    if skip_video:
        command.append("--skip-video")
    subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_reconstruction_generation_timeout_seconds(skip_video=skip_video),
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


def _unexpected_console_errors(messages: list[str]) -> list[str]:
    filtered: list[str] = []
    for message in messages:
        normalized = str(message or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if "cross-origin-opener-policy header has been ignored" in lowered and "origin was untrustworthy" in lowered:
            continue
        if "failed to load resource: the server responded with a status of 404" in lowered:
            continue
        filtered.append(normalized)
    return filtered


def _assert_generated_reconstruction_public_launch_shell(
    page: Page,
    *,
    slug: str,
    min_route_actions: int,
    min_media_cards: int,
    expect_video: bool,
) -> None:
    body_text = page.locator("body").inner_text().lower()
    assert "generated reconstruction" in body_text
    assert "room route" in body_text
    assert "reference deck" in body_text
    assert "tour unavailable" not in body_text
    assert page.title().endswith(" | PropertyQuarry")
    assert page.locator(".btn.primary").get_attribute("href") == "#walkthrough"
    assert page.locator(".btn.secondary").get_attribute("href") == "#reference-focus"
    _wait_for_page_condition(
        page,
        """() => Boolean(document.querySelector('#lead-preview-panel'))""",
    )
    assert _selector_count(page, "#lead-preview-panel") == 1
    assert _selector_text(page, "#lead-preview-badge").lower() == "generated diorama"
    assert _selector_text(page, "#lead-preview-copy")
    assert _selector_count(page, "#lead-preview-image") == 1
    assert _selector_count(page, "#lead-preview-stats .lead-preview-stat") == 3
    assert "diorama-preview" in str(page.locator("#lead-preview-image").get_attribute("src") or "")
    assert _selector_count(page, "#reference-shell") == 1
    assert _selector_count(page, "#reference-focus-kind") == 1
    assert _selector_count(page, ".route-action") >= min_route_actions
    assert _selector_count(page, "#media-grid .media-card") >= min_media_cards
    assert _selector_count(page, "#walkthrough-progress-track") == 1
    assert _selector_count(page, "#walkthrough-progress-fill") == 1
    assert _selector_text(page, "#walkthrough-route-summary")
    assert _selector_count(page, "#route-prev") == 1
    assert _selector_count(page, "#route-next") == 1
    assert _selector_count(page, "#layout-viewer") == 1
    assert _selector_count(page, "#layout-viewer-poster") == 1
    assert _selector_count(page, "#layout-viewer-frame") == 1
    frame_src = str(page.locator("#layout-viewer-frame").get_attribute("src") or "")
    parsed_frame_src = urllib.parse.urlparse(frame_src)
    assert parsed_frame_src.path.endswith(f"/tours/files/{slug}/generated-reconstruction/viewer.html")
    frame_query = urllib.parse.parse_qs(parsed_frame_src.query)
    assert frame_query.get("embed") == ["1"]
    assert "guided" not in frame_query
    assert _selector_count(page, "#layout-viewer-open") == 1
    assert str(page.locator("#layout-viewer-open").get_attribute("href") or "").endswith(
        f"/tours/files/{slug}/generated-reconstruction/viewer.html"
    )
    if expect_video:
        assert page.locator("#tour-video").count() == 1
        assert page.locator("#tour-video source").get_attribute("src").endswith(f"/tours/{slug}/walkthrough")
    else:
        assert page.locator("#tour-video").count() == 0


def _embedded_layout_viewer_frame(page, *, timeout_seconds: float = 15.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for frame in page.frames:
            if "/generated-reconstruction/viewer.html" in str(getattr(frame, "url", "") or ""):
                return frame
        page.wait_for_timeout(100)
    raise AssertionError("embedded generated reconstruction viewer frame did not become available in time")


def _wait_for_embedded_layout_viewer_route(page, *, route_index: int | None = None, timeout: int = 30000) -> dict[str, object]:
    frame = _embedded_layout_viewer_frame(page, timeout_seconds=max(1.0, timeout / 1000))
    deadline = time.time() + (max(1, timeout) / 1000)
    last_metrics: dict[str, object] | None = None
    while time.time() < deadline:
        try:
            metrics = frame.evaluate(
                """() => {
                    const debug = window.__pqReconstructionDebug;
                    if (!debug || typeof debug.getRenderMetrics !== 'function') {
                        return null;
                    }
                    return debug.getRenderMetrics();
                }"""
            )
        except Exception:
            metrics = None
        if isinstance(metrics, dict):
            last_metrics = dict(metrics)
            if (
                bool(last_metrics.get("ready"))
                and int(last_metrics.get("frameCount") or 0) >= 2
                and int(last_metrics.get("renderCalls") or 0) > 0
                and int(last_metrics.get("renderTriangles") or 0) > 0
                and (route_index is None or int(last_metrics.get("activeRouteIndex") or -1) == route_index)
            ):
                return last_metrics
        page.wait_for_timeout(120)
    raise AssertionError(
        f"embedded layout viewer did not reach route index {route_index}: {last_metrics!r}"
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


def _canvas_visual_metrics(page, selector: str) -> dict[str, object]:
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
        "route_stop_count": float(metrics.get("routeStopCount") or 0),
        "active_route_index": float(0 if metrics.get("activeRouteIndex") is None else metrics.get("activeRouteIndex")),
        "view_mode": str(metrics.get("viewMode") or ""),
        "is_transitioning": bool(metrics.get("isTransitioning")),
        "transition_progress_pct": float(metrics.get("transitionProgressPct") or 0),
        "transition_target_route_index": float(
            -1 if metrics.get("transitionTargetRouteIndex") is None else metrics.get("transitionTargetRouteIndex")
        ),
        "transition_duration_ms": float(metrics.get("transitionDurationMs") or 0),
        "transition_target_view_mode": str(metrics.get("transitionTargetViewMode") or ""),
        "wall_opacity": float(metrics.get("wallOpacity") or 0),
        "wall_height_scale": float(metrics.get("wallHeightScale") or 0),
        "photo_panel_group_visible": bool(metrics.get("photoPanelGroupVisible")),
        "hotspot_count": float(metrics.get("hotspotCount") or 0),
        "visible_hotspot_count": float(metrics.get("visibleHotspotCount") or 0),
        "photo_panel_count": float(metrics.get("photoPanelCount") or 0),
        "loaded_photo_texture_count": float(metrics.get("loadedPhotoTextureCount") or 0),
        "visible_photo_panel_count": float(metrics.get("visiblePhotoPanelCount") or 0),
        "scene_child_count": float(metrics.get("sceneChildCount") or 0),
        "projected_coverage_pct": float(metrics.get("projectedCoveragePct") or 0),
        "projected_photo_coverage_pct": float(metrics.get("projectedPhotoCoveragePct") or 0),
        "max_projected_wall_pct": float(metrics.get("maxProjectedWallPct") or 0),
        "render_calls": float(metrics.get("renderCalls") or 0),
        "render_triangles": float(metrics.get("renderTriangles") or 0),
        "width": float(metrics.get("sampleWidth") or 0),
        "height": float(metrics.get("sampleHeight") or 0),
        "camera_position": dict(metrics.get("cameraPosition") or {}),
    }


def _wait_for_reconstruction_viewer_ready(page, *, timeout: int = 30000) -> None:
    _wait_for_page_condition(
        page,
        """() => {
            const canvas = document.querySelector('#viewport canvas');
            const debug = window.__pqReconstructionDebug;
            if (!canvas || !debug || typeof debug.getRenderMetrics !== 'function') {
                return false;
            }
            const metrics = debug.getRenderMetrics();
            return Boolean(
                metrics?.ready &&
                Number(metrics?.frameCount || 0) >= 2 &&
                Number(metrics?.renderCalls || 0) > 0 &&
                Number(metrics?.renderTriangles || 0) > 0
            );
        }""",
        timeout=timeout,
    )


def _click_viewer_control(page, selector: str) -> None:
    clicked = page.evaluate(
        """(selector) => {
            const node = document.querySelector(selector);
            if (!node) return { ok: false, reason: 'missing' };
            const rect = node.getBoundingClientRect();
            if (!(rect.width > 0 && rect.height > 0)) {
                return { ok: false, reason: 'hidden' };
            }
            if (typeof node.click === 'function') {
                node.click();
            } else {
                node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            }
            return { ok: true };
        }""",
        selector,
    )
    assert clicked == {"ok": True}, f"viewer control click failed: {selector} -> {clicked}"


def _scroll_selector_into_view(page, selector: str) -> None:
    page.evaluate(
        """(selector) => {
            const node = document.querySelector(selector);
            if (node) {
                node.scrollIntoView({ block: "center", inline: "nearest" });
            }
        }""",
        selector,
    )
    page.wait_for_timeout(150)


def _selector_text(page, selector: str) -> str:
    value = page.evaluate(
        """(selector) => {
            const node = document.querySelector(selector);
            return node ? String(node.textContent || '').trim() : null;
        }""",
        selector,
    )
    assert value is not None, f"missing selector text: {selector}"
    return str(value)


def _selector_texts(page, selector: str) -> list[str]:
    values = page.evaluate(
        """(selector) => Array.from(document.querySelectorAll(selector)).map((node) => String(node.textContent || '').trim())""",
        selector,
    )
    return [str(value) for value in list(values or [])]


def _selector_count(page, selector: str) -> int:
    value = page.evaluate(
        """(selector) => document.querySelectorAll(selector).length""",
        selector,
    )
    return int(value or 0)


def _wait_for_page_condition(page, expression: str, *, timeout: int = 30000, poll_ms: int = 100) -> None:
    deadline = time.time() + (max(1, timeout) / 1000)
    last_value = None
    while time.time() < deadline:
        last_value = page.evaluate(expression)
        if last_value:
            return
        page.wait_for_timeout(poll_ms)
    raise AssertionError(f"page condition did not become truthy before timeout: {expression} -> {last_value!r}")


def _run_generated_reconstruction_viewer_browser_probe(viewer_url: str) -> dict[str, object]:
    probe_script = """
import json
import os
import time

from playwright.sync_api import sync_playwright


def _debug_metrics(page):
    metrics = page.evaluate(
        '''() => {
            const debug = window.__pqReconstructionDebug;
            if (!debug || typeof debug.getRenderMetrics !== "function") {
                return null;
            }
            return debug.getRenderMetrics();
        }'''
    )
    if not isinstance(metrics, dict):
        raise AssertionError(f"missing reconstruction debug metrics: {metrics!r}")
    return dict(metrics)


def _normalized_metrics(metrics):
    return {
        "ready": bool(metrics.get("ready")),
        "frame_count": float(metrics.get("frameCount") or 0),
        "wall_rect_count": float(metrics.get("wallRectCount") or 0),
        "wall_mesh_count": float(metrics.get("wallMeshCount") or 0),
        "visible_wall_count": float(metrics.get("visibleWallCount") or 0),
        "route_stop_count": float(metrics.get("routeStopCount") or 0),
        "active_route_index": float(0 if metrics.get("activeRouteIndex") is None else metrics.get("activeRouteIndex")),
        "view_mode": str(metrics.get("viewMode") or ""),
        "is_transitioning": bool(metrics.get("isTransitioning")),
        "transition_progress_pct": float(metrics.get("transitionProgressPct") or 0),
        "transition_target_route_index": float(
            -1 if metrics.get("transitionTargetRouteIndex") is None else metrics.get("transitionTargetRouteIndex")
        ),
        "transition_duration_ms": float(metrics.get("transitionDurationMs") or 0),
        "transition_target_view_mode": str(metrics.get("transitionTargetViewMode") or ""),
        "wall_opacity": float(metrics.get("wallOpacity") or 0),
        "wall_height_scale": float(metrics.get("wallHeightScale") or 0),
        "photo_panel_group_visible": bool(metrics.get("photoPanelGroupVisible")),
        "hotspot_count": float(metrics.get("hotspotCount") or 0),
        "visible_hotspot_count": float(metrics.get("visibleHotspotCount") or 0),
        "photo_panel_count": float(metrics.get("photoPanelCount") or 0),
        "loaded_photo_texture_count": float(metrics.get("loadedPhotoTextureCount") or 0),
        "visible_photo_panel_count": float(metrics.get("visiblePhotoPanelCount") or 0),
        "scene_child_count": float(metrics.get("sceneChildCount") or 0),
        "projected_coverage_pct": float(metrics.get("projectedCoveragePct") or 0),
        "projected_photo_coverage_pct": float(metrics.get("projectedPhotoCoveragePct") or 0),
        "max_projected_wall_pct": float(metrics.get("maxProjectedWallPct") or 0),
        "render_calls": float(metrics.get("renderCalls") or 0),
        "render_triangles": float(metrics.get("renderTriangles") or 0),
        "width": float(metrics.get("sampleWidth") or 0),
        "height": float(metrics.get("sampleHeight") or 0),
        "camera_position": dict(metrics.get("cameraPosition") or {}),
    }


def _wait_for_metrics(page, predicate, *, timeout_ms=30000, poll_ms=40):
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_metrics = None
    while time.monotonic() < deadline:
        last_metrics = _debug_metrics(page)
        if predicate(last_metrics):
            return last_metrics
        page.wait_for_timeout(poll_ms)
    raise AssertionError(f"timed out waiting for metrics predicate: {last_metrics!r}")


def _capture_transition_metrics(page, *, route_index, timeout_ms=2500, poll_ms=40):
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        metrics = _debug_metrics(page)
        if bool(metrics.get("isTransitioning")) and int(metrics.get("transitionTargetRouteIndex") or -1) == route_index:
            return metrics
        if not bool(metrics.get("isTransitioning")) and int(metrics.get("activeRouteIndex") or -1) == route_index:
            return None
        page.wait_for_timeout(poll_ms)
    return None


def _viewer_dom_click(page, selector):
    result = page.evaluate(
        '''(selector) => {
            const node = document.querySelector(selector);
            if (!node) return { ok: false, reason: "missing" };
            const rect = node.getBoundingClientRect();
            if (!(rect.width > 0 && rect.height > 0)) {
                return { ok: false, reason: "hidden" };
            }
            if (typeof node.click === "function") {
                node.click();
            } else {
                node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
            }
            return { ok: true };
        }''',
        selector,
    )
    if result != {"ok": True}:
        raise AssertionError(f"viewer control click failed: {selector} -> {result!r}")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    console_errors = []
    page_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    response = page.goto(os.environ["PROPERTYQUARRY_VIEWER_URL"], wait_until="domcontentloaded")
    if response is None or not response.ok:
        raise AssertionError(f"viewer navigation failed: {response!r}")

    initial_dom = dict(
        page.evaluate(
            '''() => ({
                title: document.title,
                h1: String(document.querySelector("h1")?.textContent || "").trim(),
                routeButtonTexts: Array.from(document.querySelectorAll(".route-button")).map((node) => String(node.textContent || "").trim().toLowerCase()),
                dollhouseLabel: String(document.getElementById("view-dollhouse")?.textContent || "").trim(),
                floorplanStopTexts: Array.from(document.querySelectorAll(".floorplan-stop .floorplan-stop-label")).map((node) => String(node.textContent || "").trim().toLowerCase()),
                routeButtonCount: document.querySelectorAll(".route-button").length,
                floorplanStopCount: document.querySelectorAll(".floorplan-stop").length,
                routeHotspotCount: document.querySelectorAll(".route-hotspot").length,
            })'''
        )
        or {}
    )

    overview_raw_metrics = _wait_for_metrics(
        page,
        lambda metrics: bool(metrics.get("ready"))
        and float(metrics.get("frameCount") or 0) >= 2
        and float(metrics.get("renderCalls") or 0) > 0
        and float(metrics.get("renderTriangles") or 0) > 0
        and float(metrics.get("photoPanelCount") or 0) >= 2
        and float(metrics.get("loadedPhotoTextureCount") or 0) >= 2,
    )

    _viewer_dom_click(page, "#view-dollhouse")
    dollhouse_raw_metrics = _wait_for_metrics(
        page,
        lambda metrics: str(metrics.get("viewMode") or "") == "dollhouse"
        and not bool(metrics.get("isTransitioning"))
        and float(metrics.get("wallHeightScale") or 0) < 0.8,
    )

    _viewer_dom_click(page, "#view-inside")
    inside_raw_metrics = _wait_for_metrics(
        page,
        lambda metrics: int(metrics.get("activeRouteIndex") or 0) == 0
        and str(metrics.get("viewMode") or "") == "room"
        and not bool(metrics.get("isTransitioning")),
    )

    _viewer_dom_click(page, ".route-buttons .route-button:nth-child(2)")
    route1_transition_raw_metrics = _capture_transition_metrics(page, route_index=1)
    route1_raw_metrics = _wait_for_metrics(
        page,
        lambda metrics: int(metrics.get("activeRouteIndex") or -1) == 1
        and str(metrics.get("viewMode") or "") == "room"
        and not bool(metrics.get("isTransitioning")),
    )

    page.evaluate(
        '''() => {
            const node = document.querySelector(".floorplan-map");
            if (node) {
                node.scrollIntoView({ block: "center", inline: "nearest" });
            }
        }'''
    )
    page.wait_for_timeout(150)
    _viewer_dom_click(page, '.floorplan-stop[data-route-index="2"]')
    route2_transition_raw_metrics = _capture_transition_metrics(page, route_index=2)
    route2_raw_metrics = _wait_for_metrics(
        page,
        lambda metrics: int(metrics.get("activeRouteIndex") or -1) == 2
        and str(metrics.get("viewMode") or "") == "room"
        and not bool(metrics.get("isTransitioning")),
    )

payload = {
    "initial_dom": initial_dom,
    "overview_metrics": _normalized_metrics(overview_raw_metrics),
    "dollhouse_metrics": _normalized_metrics(dollhouse_raw_metrics),
    "inside_metrics": _normalized_metrics(inside_raw_metrics),
    "route1_transition_metrics": None
    if route1_transition_raw_metrics is None
    else _normalized_metrics(route1_transition_raw_metrics),
    "route1_metrics": _normalized_metrics(route1_raw_metrics),
    "route2_transition_metrics": None
    if route2_transition_raw_metrics is None
    else _normalized_metrics(route2_transition_raw_metrics),
    "route2_metrics": _normalized_metrics(route2_raw_metrics),
    "page_errors": list(page_errors),
    "unexpected_console_errors": [
        message
        for message in console_errors
        if "failed to resolve module specifier" in message.lower()
        or "cannot use import statement" in message.lower()
        or "webgl" in message.lower()
        or "failed to load resource" in message.lower()
    ],
}
print(json.dumps(payload))
os._exit(0)
"""
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-u", "-c", probe_script],
        capture_output=True,
        check=False,
        cwd=str(repo_root),
        env={**os.environ, "PROPERTYQUARRY_VIEWER_URL": str(viewer_url)},
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "generated reconstruction viewer probe failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert stdout_lines, "generated reconstruction viewer probe did not emit a result payload"
    payload = json.loads(stdout_lines[-1])
    assert isinstance(payload, dict), payload
    return dict(payload)


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
    _disable_public_tour_fixture_startup_prewarm(monkeypatch)

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
    raw_port = _free_port()
    static_server = ThreadingHTTPServer(
        ("127.0.0.1", raw_port),
        partial(_SilentStaticHandler, directory=str(bundle_root)),
    )
    static_thread = threading.Thread(target=static_server.serve_forever, daemon=True)
    static_thread.start()
    generated_reconstruction_viewer_url = (
        f"http://127.0.0.1:{raw_port}/{generated_reconstruction_slug}/generated-reconstruction/viewer.html"
    )
    _wait_for_url(generated_reconstruction_viewer_url)
    try:
        yield {
            "base_url": browser_base_url,
            "slug": slug,
            "video_slug": video_slug,
            "generated_reconstruction_slug": generated_reconstruction_slug,
            "generated_reconstruction_viewer_url": generated_reconstruction_viewer_url,
        }
    finally:
        static_server.shutdown()
        static_server.server_close()
        static_thread.join(timeout=10.0)
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def generated_reconstruction_walkthrough_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "generated-reconstruction-walkthrough-browser-tour"
    _generate_reconstruction_bundle(bundle_root=bundle_root, slug=slug, skip_video=False)
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(bundle_root))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_API_TOKEN", raising=False)
    _disable_public_tour_fixture_startup_prewarm(monkeypatch)

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
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


def _write_generated_reconstruction_public_shell_bundle(
    *,
    bundle_root: Path,
    slug: str,
    title: str,
    route_labels: list[str],
    walkthrough_route_labels: list[str],
    walkable_scene: dict[str, object],
    photo_specs: list[tuple[str, tuple[int, int, int]]],
    coverage_segments: list[dict[str, object]],
) -> None:
    bundle_dir = bundle_root / slug
    reconstruction_dir = bundle_dir / "generated-reconstruction"
    reconstruction_dir.mkdir(parents=True, exist_ok=True)

    _write_floorplan_png(reconstruction_dir / "source-floorplan.png")
    for index, (label, fill) in enumerate(photo_specs, start=1):
        _write_photo_panel(reconstruction_dir / f"photo-{index:02d}.jpg", label=label, fill=fill)
    _write_cube_face_png(bundle_dir / "diorama-preview.png", label="Generated diorama", fill=(128, 98, 76))
    _write_h264_flythrough(reconstruction_dir / "generated-walkthrough.mp4")

    coverage_proof = {
        "status": "pass",
        "segments_expected": walkthrough_route_labels,
        "segments_visited": walkthrough_route_labels,
        "coverage_segments": coverage_segments,
    }
    (reconstruction_dir / "generated-walkthrough.quality.json").write_text(
        json.dumps(
            {
                "route_labels": walkthrough_route_labels,
                "covered_route_labels": walkthrough_route_labels,
                "walkthrough_coverage_proof": coverage_proof,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (reconstruction_dir / "reconstruction.json").write_text(
        json.dumps(
            {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "room_dimensions_m": {"width": 8.0, "depth": 5.5, "height": 2.8},
                "geometry": {"wall_rect_count": 8},
                "walkable_scene": walkable_scene,
                "route_labels": route_labels,
                "viewer": {
                    "relpath": "viewer.html",
                    "version": "propertyquarry_3d_tour_viewer_v3",
                },
                "walkthrough_route_labels": walkthrough_route_labels,
                "walkthrough": {
                    "status": "generated",
                    "coverage_proof": coverage_proof,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (reconstruction_dir / "viewer.html").write_text(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Layout preview</title>
  </head>
  <body>
    <h1>Layout preview</h1>
    <script>
      let activeRouteIndex = 0;
      window.__pqReconstructionDebug = {{
        setRouteView(index) {{
          const numeric = Number(index);
          activeRouteIndex = Number.isFinite(numeric)
            ? Math.max(0, Math.min({len(route_labels) - 1}, numeric))
            : activeRouteIndex;
        }},
        getRenderMetrics() {{
          return {{
            ready: true,
            frameCount: 3,
            renderCalls: 1,
            renderTriangles: 1,
            routeStopCount: {len(route_labels)},
            activeRouteIndex,
            viewMode: 'room',
          }};
        }},
      }};
    </script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    scenes = [
        {
            "scene_id": "floorplan-1",
            "name": "Route floorplan",
            "role": "floorplan",
            "asset_relpath": "generated-reconstruction/source-floorplan.png",
            "mime_type": "image/png",
        }
    ]
    scenes.extend(
        {
            "scene_id": f"photo-{index}",
            "name": label,
            "role": "photo",
            "asset_relpath": f"generated-reconstruction/photo-{index:02d}.jpg",
            "mime_type": "image/jpeg",
        }
        for index, (label, _fill) in enumerate(photo_specs, start=1)
    )
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": title,
                "display_title": title,
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "diorama_preview_relpath": "diorama-preview.png",
                "preview_relpath": "diorama-preview.png",
                "photo_count": len(photo_specs),
                "media": {"source_photos": {"count": len(photo_specs)}},
                "generated_reconstruction": {
                    "provider": "propertyquarry_generated_reconstruction",
                    "viewer_version": "propertyquarry_3d_tour_viewer_v3",
                    "viewer_relpath": "generated-reconstruction/viewer.html",
                    "manifest_relpath": "generated-reconstruction/reconstruction.json",
                    "floorplan_relpath": "generated-reconstruction/source-floorplan.png",
                    "photo_relpaths": [
                        f"generated-reconstruction/photo-{index:02d}.jpg"
                        for index in range(1, len(photo_specs) + 1)
                    ],
                    "route_labels": route_labels,
                    "room_stop_count": len(route_labels),
                    "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                    "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                    "walkthrough_route_labels": walkthrough_route_labels,
                    "walkthrough_stop_count": len(walkthrough_route_labels),
                    "walkthrough_coverage_proof": coverage_proof,
                    "walkable_scene": walkable_scene,
                    "verified_provider_capture": False,
                    "satisfies_verified_tour_gate": False,
                },
                "video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                "video_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                "video_provider": "propertyquarry_generated_reconstruction",
                "video_provider_key": "propertyquarry_generated_reconstruction",
                "video_coverage_proof": "boundary_verified_frame_continuation",
                "scenes": scenes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def generated_reconstruction_viewer_server(
    tmp_path: Path,
) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "generated-reconstruction-viewer-browser-tour"
    bundle_dir = bundle_root / slug
    reconstruction_dir = bundle_dir / "generated-reconstruction"
    reconstruction_dir.mkdir(parents=True, exist_ok=True)
    floorplan_path = reconstruction_dir / "source-floorplan.png"
    photo_paths = [
        reconstruction_dir / "photo-01.jpg",
        reconstruction_dir / "photo-02.jpg",
    ]
    _write_floorplan_png(floorplan_path)
    _write_photo_panel(photo_paths[0], label="Living reference", fill=(112, 86, 62))
    _write_photo_panel(photo_paths[1], label="Bedroom reference", fill=(84, 104, 122))
    geometry = reconstruction_script._extract_floorplan_geometry(floorplan_path)
    geometry_content_size = dict(geometry.get("content_size_px") or {})
    width_m, depth_m, height_m = reconstruction_script._room_dimensions(
        int(geometry_content_size.get("width") or 1280),
        int(geometry_content_size.get("height") or 900),
        max_width_m=10.0,
    )
    wall_rectangles = reconstruction_script._wall_rectangles_from_mask(
        list(geometry.get("wall_mask") or []),
        width_m=width_m,
        depth_m=depth_m,
    )
    route_labels = ["entry/hall", "living room", "bedroom"]
    walkable_scene = reconstruction_script._reconstruction_walkable_scene(
        route_labels=route_labels,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
    )
    photo_rows = []
    for path in photo_paths:
        photo_rows.append(
            {
                "relpath": path.name,
                **reconstruction_script._image_metadata(path),
            }
        )
    photo_reference_panels = reconstruction_script._generated_reconstruction_photo_reference_panels(
        photos=photo_rows,
        walkable_scene=walkable_scene,
        width_m=width_m,
        depth_m=depth_m,
        height_m=height_m,
    )
    manifest = {
        "provider": "propertyquarry_generated_reconstruction",
        "room_dimensions_m": {"width": width_m, "depth": depth_m, "height": height_m},
        "geometry": {
            "content_bbox_px": dict(geometry.get("content_bbox_px") or {}),
            "content_size_px": geometry_content_size,
            "mask_size_cells": dict(geometry.get("mask_size_cells") or {}),
            "wall_rectangles": wall_rectangles,
            "wall_rect_count": len(wall_rectangles),
        },
        "floorplan": {
            "relpath": floorplan_path.name,
            **reconstruction_script._image_metadata(floorplan_path),
        },
        "photos": photo_rows,
        "walkable_scene": walkable_scene,
        "photo_reference_panels": photo_reference_panels,
        "route_labels": route_labels,
        "walkthrough_route_labels": route_labels,
        "style_label": "warm scandinavian",
        "viewer": {
            "relpath": "viewer.html",
            "version": reconstruction_script.VIEWER_VERSION,
            "photo_reference_panel_count": len(photo_reference_panels),
        },
    }
    (reconstruction_dir / "reconstruction.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (reconstruction_dir / "viewer.html").write_text(
        reconstruction_script._viewer_html(manifest=manifest),
        encoding="utf-8",
    )
    raw_port = _free_port()
    static_server = ThreadingHTTPServer(
        ("127.0.0.1", raw_port),
        partial(_SilentStaticHandler, directory=str(bundle_root)),
    )
    static_thread = threading.Thread(target=static_server.serve_forever, daemon=True)
    static_thread.start()
    viewer_url = f"http://127.0.0.1:{raw_port}/{slug}/generated-reconstruction/viewer.html"
    _wait_for_url(viewer_url)
    try:
        yield {
            "slug": slug,
            "viewer_url": viewer_url,
        }
    finally:
        static_server.shutdown()
        static_server.server_close()
        static_thread.join(timeout=10.0)


@pytest.fixture()
def generated_reconstruction_shell_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "generated-reconstruction-shell-browser-tour"
    bundle_dir = bundle_root / slug
    reconstruction_dir = bundle_dir / "generated-reconstruction"
    reconstruction_dir.mkdir(parents=True, exist_ok=True)

    _write_floorplan_png(reconstruction_dir / "source-floorplan.png")
    _write_photo_panel(reconstruction_dir / "photo-01.jpg", label="Living reference", fill=(122, 88, 72))
    _write_photo_panel(reconstruction_dir / "photo-02.jpg", label="Bedroom reference", fill=(84, 104, 122))
    _write_cube_face_png(bundle_dir / "diorama-preview.png", label="Generated diorama", fill=(128, 98, 76))
    _write_h264_flythrough(reconstruction_dir / "generated-walkthrough.mp4")

    route_labels = ["entry/hall", "living room", "bedroom"]
    walkthrough_route_labels = ["entry/hall", "living room", "bedroom"]
    walkable_scene = {
        "kind": "generated_reconstruction_layout",
        "route": [
            {
                "label": "entry/hall",
                "room": "entry/hall",
                "name": "entry/hall",
                "kind": "entry",
                "sequence": 1,
                "focus": {"x": -0.8, "y": 1.4, "z": 0.9},
                "camera": {"x": -0.2, "y": 1.6, "z": 1.5},
            },
            {
                "label": "living room",
                "room": "living room",
                "name": "living room",
                "kind": "living",
                "sequence": 2,
                "focus": {"x": 0.4, "y": 1.4, "z": 0.1},
                "camera": {"x": -0.1, "y": 1.6, "z": 0.8},
            },
            {
                "label": "bedroom",
                "room": "bedroom",
                "name": "bedroom",
                "kind": "bedroom",
                "sequence": 3,
                "focus": {"x": 0.7, "y": 1.4, "z": -0.7},
                "camera": {"x": -0.05, "y": 1.6, "z": -0.1},
            },
        ],
        "rooms": [
            {
                "label": "entry/hall",
                "name": "entry/hall",
                "kind": "entry",
                "sequence": 1,
                "position": {"x": -0.8, "y": 0.0, "z": 0.9},
                "focus": {"x": -0.8, "y": 1.4, "z": 0.9},
            },
            {
                "label": "living room",
                "name": "living room",
                "kind": "living",
                "sequence": 2,
                "position": {"x": 0.4, "y": 0.0, "z": 0.1},
                "focus": {"x": 0.4, "y": 1.4, "z": 0.1},
            },
            {
                "label": "bedroom",
                "name": "bedroom",
                "kind": "bedroom",
                "sequence": 3,
                "position": {"x": 0.7, "y": 0.0, "z": -0.7},
                "focus": {"x": 0.7, "y": 1.4, "z": -0.7},
            },
        ],
    }
    (reconstruction_dir / "generated-walkthrough.quality.json").write_text(
        json.dumps(
            {
                "route_labels": walkthrough_route_labels,
                "covered_route_labels": walkthrough_route_labels,
                "walkthrough_coverage_proof": {
                    "status": "pass",
                    "segments_expected": walkthrough_route_labels,
                    "segments_visited": walkthrough_route_labels,
                    "coverage_segments": [
                        {"segment": "entry/hall", "index": 1, "start": 0.0, "end": 1.0},
                        {"segment": "living room", "index": 2, "start": 1.0, "end": 2.0},
                        {"segment": "bedroom", "index": 3, "start": 2.0, "end": 3.0},
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (reconstruction_dir / "reconstruction.json").write_text(
        json.dumps(
            {
                "provider": "propertyquarry_generated_reconstruction",
                "verified_provider_capture": False,
                "satisfies_verified_tour_gate": False,
                "room_dimensions_m": {"width": 8.0, "depth": 5.5, "height": 2.8},
                "geometry": {"wall_rect_count": 8},
                "walkable_scene": walkable_scene,
                "route_labels": route_labels,
                "viewer": {
                    "relpath": "viewer.html",
                    "version": "propertyquarry_3d_tour_viewer_v3",
                },
                "walkthrough_route_labels": walkthrough_route_labels,
                "walkthrough": {
                    "status": "generated",
                    "coverage_proof": {
                        "status": "pass",
                        "segments_expected": walkthrough_route_labels,
                        "segments_visited": walkthrough_route_labels,
                        "coverage_segments": [
                            {"segment": "entry/hall", "index": 1, "start": 0.0, "end": 1.0},
                            {"segment": "living room", "index": 2, "start": 1.0, "end": 2.0},
                            {"segment": "bedroom", "index": 3, "start": 2.0, "end": 3.0},
                        ],
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (reconstruction_dir / "viewer.html").write_text(
        """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Layout preview</title>
  </head>
  <body>
    <h1>Layout preview</h1>
    <script>
      let activeRouteIndex = 0;
      window.__pqReconstructionDebug = {
        setRouteView(index) {
          const numeric = Number(index);
          activeRouteIndex = Number.isFinite(numeric) ? numeric : activeRouteIndex;
        },
        getRenderMetrics() {
          return {
            ready: true,
            frameCount: 3,
            renderCalls: 1,
            renderTriangles: 1,
            activeRouteIndex,
            viewMode: 'room',
          };
        },
      };
    </script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Generated Reconstruction Shell Browser Tour",
                "display_title": "Generated Reconstruction Shell Browser Tour",
                "hosted_url": f"https://propertyquarry.com/tours/{slug}",
                "public_url": f"https://propertyquarry.com/tours/{slug}",
                "diorama_preview_relpath": "diorama-preview.png",
                "preview_relpath": "diorama-preview.png",
                "generated_reconstruction": {
                    "provider": "propertyquarry_generated_reconstruction",
                    "viewer_version": "propertyquarry_3d_tour_viewer_v3",
                    "viewer_relpath": "generated-reconstruction/viewer.html",
                    "manifest_relpath": "generated-reconstruction/reconstruction.json",
                    "floorplan_relpath": "generated-reconstruction/source-floorplan.png",
                    "photo_relpaths": [
                        "generated-reconstruction/photo-01.jpg",
                        "generated-reconstruction/photo-02.jpg",
                    ],
                    "route_labels": route_labels,
                    "room_stop_count": len(route_labels),
                    "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                    "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                    "walkthrough_route_labels": walkthrough_route_labels,
                    "walkthrough_stop_count": len(walkthrough_route_labels),
                    "walkthrough_coverage_proof": {
                        "status": "pass",
                        "segments_expected": walkthrough_route_labels,
                        "segments_visited": walkthrough_route_labels,
                        "coverage_segments": [
                            {"segment": "entry/hall", "index": 1, "start": 0.0, "end": 1.0},
                            {"segment": "living room", "index": 2, "start": 1.0, "end": 2.0},
                            {"segment": "bedroom", "index": 3, "start": 2.0, "end": 3.0},
                        ],
                    },
                    "walkable_scene": walkable_scene,
                    "verified_provider_capture": False,
                    "satisfies_verified_tour_gate": False,
                },
                "video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                "video_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                "video_provider": "propertyquarry_generated_reconstruction",
                "video_provider_key": "propertyquarry_generated_reconstruction",
                "video_coverage_proof": "boundary_verified_frame_continuation",
                "scenes": [
                    {
                        "scene_id": "floorplan-1",
                        "name": "Route floorplan",
                        "role": "floorplan",
                        "asset_relpath": "generated-reconstruction/source-floorplan.png",
                        "mime_type": "image/png",
                    },
                    {
                        "scene_id": "photo-1",
                        "name": "Living room",
                        "role": "photo",
                        "asset_relpath": "generated-reconstruction/photo-01.jpg",
                        "mime_type": "image/jpeg",
                    },
                    {
                        "scene_id": "photo-2",
                        "name": "Bedroom",
                        "role": "photo",
                        "asset_relpath": "generated-reconstruction/photo-02.jpg",
                        "mime_type": "image/jpeg",
                    },
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
    _disable_public_tour_fixture_startup_prewarm(monkeypatch)

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
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def generated_reconstruction_matterport_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "generated-reconstruction-matterport-browser-tour"
    _generate_reconstruction_bundle(bundle_root=bundle_root, slug=slug, skip_video=True)
    ((bundle_root / slug) / "tour.private.json").write_text(
        json.dumps({"source_virtual_tour_url": "https://my.matterport.com/show/?m=MIXEDPREVIEW1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(bundle_root))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_API_TOKEN", raising=False)
    _disable_public_tour_fixture_startup_prewarm(monkeypatch)

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
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def generated_reconstruction_expanded_walkthrough_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    bundle_root = tmp_path / "public_tours"
    slug = "generated-reconstruction-expanded-walkthrough-browser-tour"
    route_labels = ["entry/hall", "living room", "bedroom", "balcony"]
    walkthrough_route_labels = list(route_labels)
    walkable_scene = {
        "kind": "generated_reconstruction_layout",
        "route": [
            {
                "label": "entry/hall",
                "room": "entry/hall",
                "name": "entry/hall",
                "kind": "entry",
                "sequence": 1,
                "focus": {"x": -0.9, "y": 1.4, "z": 1.0},
                "camera": {"x": -0.25, "y": 1.6, "z": 1.7},
            },
            {
                "label": "living room",
                "room": "living room",
                "name": "living room",
                "kind": "living",
                "sequence": 2,
                "focus": {"x": 0.35, "y": 1.4, "z": 0.25},
                "camera": {"x": -0.05, "y": 1.6, "z": 0.95},
            },
            {
                "label": "bedroom",
                "room": "bedroom",
                "name": "bedroom",
                "kind": "bedroom",
                "sequence": 3,
                "focus": {"x": 0.8, "y": 1.4, "z": -0.55},
                "camera": {"x": 0.1, "y": 1.6, "z": -0.05},
            },
            {
                "label": "balcony",
                "room": "balcony",
                "name": "balcony",
                "kind": "balcony",
                "sequence": 4,
                "focus": {"x": 1.25, "y": 1.35, "z": 0.9},
                "camera": {"x": 0.7, "y": 1.58, "z": 0.5},
            },
        ],
        "rooms": [
            {
                "label": "entry/hall",
                "name": "entry/hall",
                "kind": "entry",
                "sequence": 1,
                "position": {"x": -0.9, "y": 0.0, "z": 1.0},
                "focus": {"x": -0.9, "y": 1.4, "z": 1.0},
            },
            {
                "label": "living room",
                "name": "living room",
                "kind": "living",
                "sequence": 2,
                "position": {"x": 0.35, "y": 0.0, "z": 0.25},
                "focus": {"x": 0.35, "y": 1.4, "z": 0.25},
            },
            {
                "label": "bedroom",
                "name": "bedroom",
                "kind": "bedroom",
                "sequence": 3,
                "position": {"x": 0.8, "y": 0.0, "z": -0.55},
                "focus": {"x": 0.8, "y": 1.4, "z": -0.55},
            },
            {
                "label": "balcony",
                "name": "balcony",
                "kind": "balcony",
                "sequence": 4,
                "position": {"x": 1.25, "y": 0.0, "z": 0.9},
                "focus": {"x": 1.25, "y": 1.35, "z": 0.9},
            },
        ],
    }
    photo_specs = [
        ("entry/hall", (90, 94, 108)),
        ("living room", (122, 88, 72)),
        ("bedroom", (84, 104, 122)),
        ("balcony", (112, 122, 84)),
        ("living detail", (138, 104, 84)),
    ]
    coverage_segments = [
        {"segment": "entry/hall", "index": 1, "start": 0.0, "end": 0.75},
        {"segment": "living room", "index": 2, "start": 0.75, "end": 1.5},
        {"segment": "bedroom", "index": 3, "start": 1.5, "end": 2.25},
        {"segment": "balcony", "index": 4, "start": 2.25, "end": 3.0},
    ]
    _write_generated_reconstruction_public_shell_bundle(
        bundle_root=bundle_root,
        slug=slug,
        title="Generated Reconstruction Expanded Browser Tour",
        route_labels=route_labels,
        walkthrough_route_labels=walkthrough_route_labels,
        walkable_scene=walkable_scene,
        photo_specs=photo_specs,
        coverage_segments=coverage_segments,
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(bundle_root))
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_API_TOKEN", raising=False)
    _disable_public_tour_fixture_startup_prewarm(monkeypatch)

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

    page.goto(url, wait_until="domcontentloaded")
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
    assert _play_tour_video_without_waiting(page) is True
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


def test_public_tour_flythrough_video_autoplay_without_pane_decodes_and_advances_in_real_browser(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['video_slug']}?autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#tour-video")
    video.wait_for()
    assert video.is_visible()
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


def test_public_tour_provider_access_shell_autoplay_without_pane_decodes_and_uses_sanitized_walkthrough_route(
    public_tour_browser_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    _stub_matterport_provider(context)
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    url = f"{public_tour_browser_server['base_url']}/tours/{public_tour_browser_server['slug']}?autoplay=1"

    page.goto(url, wait_until="networkidle")
    video = page.locator("#tour-video")
    video.wait_for()
    assert video.is_visible()
    assert page.locator("#tour-video source").get_attribute("src").endswith(
        f"/tours/{public_tour_browser_server['slug']}/walkthrough"
    )
    page_markup = page.content()
    assert f"/tours/{public_tour_browser_server['slug']}/walkthrough" in page_markup
    assert f"/tours/files/{public_tour_browser_server['slug']}/tour.mp4" not in page_markup
    if page.locator(".provider-frame").count():
        assert page.locator(".provider-frame").get_attribute("src") == "https://my.matterport.com/show/?m=REALBROWSER123"
    walkthrough_links = page.get_by_role("link", name="Open walkthrough")
    if walkthrough_links.count():
        hrefs = [
            walkthrough_links.nth(index).get_attribute("href")
            for index in range(walkthrough_links.count())
        ]
        assert all(
            str(href or "").endswith(f"/tours/{public_tour_browser_server['slug']}/walkthrough")
            for href in hrefs
        )
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('tour-video');
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
    assert page.locator(".badge").inner_text().lower() == "matterport control"
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
    assert _play_tour_video_without_waiting(page) is True
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


def test_generated_reconstruction_walkthrough_asset_decodes_in_browser(
    generated_reconstruction_walkthrough_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    slug = str(generated_reconstruction_walkthrough_server["slug"])
    video_url = (
        f"{generated_reconstruction_walkthrough_server['base_url']}"
        f"/tours/files/{slug}/generated-reconstruction/generated-walkthrough.mp4"
    )
    page.goto(str(generated_reconstruction_walkthrough_server["base_url"]), wait_until="domcontentloaded")
    page.set_content(
        f"""
        <!doctype html>
        <html lang="en">
          <body style="margin:0;background:#111;display:grid;place-items:center;min-height:100vh">
            <video id="tour-video" controls autoplay muted playsinline preload="auto" style="max-width:100vw;max-height:100vh">
              <source src="{video_url}" type="video/mp4">
            </video>
          </body>
        </html>
        """
    )
    video = page.locator("#tour-video")
    video.wait_for()
    assert video.is_visible()
    source = page.locator("#tour-video source").get_attribute("src")
    assert str(source or "").endswith(f"/tours/files/{slug}/generated-reconstruction/generated-walkthrough.mp4")
    assert _play_tour_video_without_waiting(page) is True
    page.wait_for_timeout(1800)
    state = page.evaluate(
        """() => {
            const video = document.getElementById('flythrough-video') || document.getElementById('tour-video');
            return video ? {
                currentTime: video.currentTime,
                duration: video.duration,
                readyState: video.readyState,
                videoWidth: video.videoWidth,
            } : null;
        }"""
    )
    assert state is not None
    assert state["readyState"] >= 2
    assert state["videoWidth"] >= 640
    assert state["currentTime"] > 0.2
    assert state["duration"] >= 14.0
    assert _video_frame_brightness(page) > 10.0
    profile = _video_playback_profile(page)
    assert len(profile["times"]) == 5
    assert all(later >= earlier for earlier, later in zip(profile["times"], profile["times"][1:])), profile
    assert profile["times"][-1] - profile["times"][0] >= 0.6, profile
    assert len(profile["frameSignatures"]) == 5
    assert len(set(profile["frameSignatures"])) >= 2, profile
    assert not page_errors
    assert not [
        message
        for message in console_errors
        if "decode" in message.lower()
        or "media" in message.lower()
        or "failed to load resource" in message.lower()
    ]
    context.close()


def test_generated_reconstruction_launch_page_renders_honest_public_shell(
    generated_reconstruction_shell_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    slug = str(generated_reconstruction_shell_server["slug"])
    launch_url = f"{generated_reconstruction_shell_server['base_url']}/tours/{slug}"

    response = page.goto(launch_url, wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200
    _assert_generated_reconstruction_public_launch_shell(
        page,
        slug=slug,
        min_route_actions=3,
        min_media_cards=3,
        expect_video=True,
    )
    initial_embedded_metrics = _wait_for_embedded_layout_viewer_route(page)
    assert initial_embedded_metrics["viewMode"] == "room"
    assert page.evaluate(
        """() => Boolean(document.querySelector('.layout-viewer-shell')?.classList.contains('is-ready'))"""
    )
    page.evaluate(
        """() => {
            const nodes = Array.from(document.querySelectorAll('.route-action'));
            const node = nodes[1];
            if (node && typeof node.click === 'function') {
                node.click();
            }
        }"""
    )
    synced_second_route_metrics = _wait_for_embedded_layout_viewer_route(page, route_index=1)
    assert synced_second_route_metrics["viewMode"] == "room"
    assert page.locator(".route-action.is-active").count() == 1
    assert page.locator("#reference-focus-name").inner_text().strip()
    context.close()


def test_generated_reconstruction_layout_preview_redirects_to_live_matterport_when_available(
    generated_reconstruction_matterport_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    slug = str(generated_reconstruction_matterport_server["slug"])
    launch_url = f"{generated_reconstruction_matterport_server['base_url']}/tours/{slug}"

    response = page.goto(launch_url, wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200
    assert page.url.endswith(f"/tours/{slug}/control/matterport")
    assert "matterport control" in page.inner_text("body").lower()

    preview_page = context.new_page()
    layout_response = preview_page.goto(
        f"{generated_reconstruction_matterport_server['base_url']}/tours/{slug}/layout-preview",
        wait_until="domcontentloaded",
    )
    assert layout_response is not None
    assert layout_response.status == 200
    assert preview_page.url.endswith(f"/tours/{slug}/control/matterport")
    assert "matterport control" in preview_page.inner_text("body").lower()
    context.close()


def test_generated_reconstruction_expanded_walkthrough_public_shell_is_interactive(
    generated_reconstruction_expanded_walkthrough_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    try:
        page = context.new_page()
        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        slug = str(generated_reconstruction_expanded_walkthrough_server["slug"])
        launch_url = f"{generated_reconstruction_expanded_walkthrough_server['base_url']}/tours/{slug}?autoplay=1"

        response = page.goto(launch_url, wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200
        _assert_generated_reconstruction_public_launch_shell(
            page,
            slug=slug,
            min_route_actions=4,
            min_media_cards=6,
            expect_video=True,
        )
        initial_stop_name = page.locator("#walkthrough-stop-name").inner_text()
        _wait_for_embedded_layout_viewer_route(page)
        assert page.evaluate(
            """() => Boolean(document.querySelector('.layout-viewer-shell')?.classList.contains('is-ready'))"""
        )
        route_actions = page.locator(".route-action")
        assert route_actions.count() >= 2
        page.evaluate(
            """() => {
                const nodes = Array.from(document.querySelectorAll('.route-action'));
                const node = nodes[1];
                if (node && typeof node.click === 'function') {
                    node.click();
                }
            }"""
        )
        page.wait_for_timeout(200)
        synced_second_route_metrics = _wait_for_embedded_layout_viewer_route(page, route_index=1)
        assert synced_second_route_metrics["viewMode"] == "room"
        assert page.locator(".route-action.is-active").count() == 1
        assert page.locator("#walkthrough-stop-name").inner_text() != initial_stop_name
        assert page.locator("#reference-focus-name").inner_text().strip()
        assert page.locator(".walkthrough-progress-marker").count() >= 4
        mid_stop_name = page.locator("#walkthrough-stop-name").inner_text()
        route_next = page.locator("#route-next")
        assert route_next.is_enabled()
        page.evaluate(
            """() => {
                const node = document.getElementById('route-next');
                if (node && typeof node.click === 'function') {
                    node.click();
                }
            }"""
        )
        page.wait_for_timeout(200)
        synced_third_route_metrics = _wait_for_embedded_layout_viewer_route(page, route_index=2)
        assert synced_third_route_metrics["viewMode"] == "room"
        assert page.locator("#walkthrough-stop-name").inner_text() != mid_stop_name
        progress_state = page.evaluate(
            """() => ({
                fillWidth: parseFloat(document.getElementById('walkthrough-progress-fill')?.style.width || '0'),
                activeMarkers: document.querySelectorAll('.walkthrough-progress-marker.is-active').length,
                timeLabel: String(document.getElementById('walkthrough-progress-time')?.textContent || ''),
            })"""
        )
        assert progress_state["fillWidth"] > 0.0
        assert progress_state["activeMarkers"] == 1
        assert " / " in progress_state["timeLabel"]

        assert not page_errors
        assert not _unexpected_console_errors(console_errors), console_errors
    finally:
        context.close()


def test_generated_reconstruction_viewer_renders_routeable_layout_in_real_browser(
    generated_reconstruction_viewer_server: dict[str, str],
) -> None:
    probe = _run_generated_reconstruction_viewer_browser_probe(
        str(generated_reconstruction_viewer_server["viewer_url"])
    )
    initial_dom = dict(probe["initial_dom"])
    assert initial_dom["title"] == "Layout preview | PropertyQuarry"
    assert initial_dom["h1"] == "Layout preview"
    assert initial_dom["routeButtonCount"] == 3
    assert initial_dom["routeButtonTexts"] == ["entry/hall", "living room", "bedroom"]
    assert initial_dom["dollhouseLabel"] == "Dollhouse"
    assert initial_dom["floorplanStopCount"] == 3
    assert initial_dom["routeHotspotCount"] == 3
    assert initial_dom["floorplanStopTexts"] == ["entry/hall", "living room", "bedroom"]

    overview_metrics = dict(probe["overview_metrics"])
    assert overview_metrics["ready"] is True
    assert overview_metrics["frame_count"] >= 2
    assert overview_metrics["wall_rect_count"] >= 4
    assert overview_metrics["wall_mesh_count"] == overview_metrics["wall_rect_count"]
    assert overview_metrics["visible_wall_count"] >= 1
    assert overview_metrics["route_stop_count"] == 3
    assert overview_metrics["active_route_index"] == 0
    assert overview_metrics["view_mode"] == "overview"
    assert overview_metrics["wall_opacity"] >= 0.99
    assert overview_metrics["wall_height_scale"] == 1.0
    assert overview_metrics["photo_panel_group_visible"] is True
    assert overview_metrics["hotspot_count"] == 3
    assert overview_metrics["visible_hotspot_count"] >= 1
    assert overview_metrics["photo_panel_count"] == 2
    assert overview_metrics["loaded_photo_texture_count"] == overview_metrics["photo_panel_count"]
    assert overview_metrics["visible_photo_panel_count"] >= 1
    assert overview_metrics["scene_child_count"] >= overview_metrics["wall_mesh_count"] + 4
    assert overview_metrics["projected_coverage_pct"] >= 0.5
    assert overview_metrics["projected_photo_coverage_pct"] >= 0.1
    assert overview_metrics["max_projected_wall_pct"] >= 0.1
    assert overview_metrics["render_calls"] > 0
    assert overview_metrics["render_triangles"] > 0
    assert overview_metrics["width"] >= 320
    assert overview_metrics["height"] >= 420

    dollhouse_metrics = dict(probe["dollhouse_metrics"])
    assert dollhouse_metrics["view_mode"] == "dollhouse"
    assert dollhouse_metrics["is_transitioning"] is False
    assert dollhouse_metrics["wall_opacity"] < 0.6
    assert dollhouse_metrics["wall_height_scale"] < 0.8
    assert dollhouse_metrics["photo_panel_group_visible"] is False
    assert dollhouse_metrics["visible_wall_count"] >= 1
    assert dollhouse_metrics["visible_hotspot_count"] >= 1
    assert dollhouse_metrics["camera_position"]["y"] > overview_metrics["camera_position"]["y"]

    inside_metrics = dict(probe["inside_metrics"])
    assert inside_metrics["view_mode"] == "room"
    assert inside_metrics["is_transitioning"] is False
    assert inside_metrics["wall_height_scale"] == 1.0
    assert inside_metrics["photo_panel_group_visible"] is True
    assert inside_metrics["camera_position"] != overview_metrics["camera_position"]
    assert inside_metrics["projected_coverage_pct"] >= 0.5

    route1_transition_metrics = probe["route1_transition_metrics"]
    if route1_transition_metrics is not None:
        route1_transition_metrics = dict(route1_transition_metrics)
        assert route1_transition_metrics["is_transitioning"] is True
        assert route1_transition_metrics["transition_target_route_index"] == 1
        assert route1_transition_metrics["transition_target_view_mode"] == "room"
        assert 0 <= route1_transition_metrics["transition_progress_pct"] < 100
        assert route1_transition_metrics["transition_duration_ms"] >= 650
    route1_metrics = dict(probe["route1_metrics"])
    assert route1_metrics["active_route_index"] == 1
    assert route1_metrics["view_mode"] == "room"
    assert route1_metrics["is_transitioning"] is False
    assert route1_metrics["transition_target_route_index"] == 1
    assert route1_metrics["transition_target_view_mode"] == "room"
    assert route1_metrics["transition_duration_ms"] >= 650
    assert route1_metrics["camera_position"] != inside_metrics["camera_position"]
    assert route1_metrics["projected_coverage_pct"] >= 0.5
    assert route1_metrics["projected_photo_coverage_pct"] >= 0.1

    route2_transition_metrics = probe["route2_transition_metrics"]
    if route2_transition_metrics is not None:
        route2_transition_metrics = dict(route2_transition_metrics)
        assert route2_transition_metrics["is_transitioning"] is True
        assert route2_transition_metrics["transition_target_route_index"] == 2
        assert route2_transition_metrics["transition_target_view_mode"] == "room"
        assert 0 <= route2_transition_metrics["transition_progress_pct"] < 100
        assert route2_transition_metrics["transition_duration_ms"] >= 650
    route2_metrics = dict(probe["route2_metrics"])
    assert route2_metrics["active_route_index"] == 2
    assert route2_metrics["view_mode"] == "room"
    assert route2_metrics["is_transitioning"] is False
    assert route2_metrics["transition_target_route_index"] == 2
    assert route2_metrics["transition_target_view_mode"] == "room"
    assert route2_metrics["transition_duration_ms"] >= 650
    assert route2_metrics["camera_position"] != route1_metrics["camera_position"]
    assert route2_metrics["projected_coverage_pct"] >= 0.5

    assert not probe["page_errors"]
    assert not probe["unexpected_console_errors"]


def test_generated_reconstruction_ready_viewer_route_renders_in_real_browser(
    generated_reconstruction_shell_server: dict[str, str],
    browser: Browser,
) -> None:
    context = _new_context(browser)
    page = context.new_page()
    slug = str(generated_reconstruction_shell_server["slug"])
    response = page.goto(
        f"{generated_reconstruction_shell_server['base_url']}/tours/files/{slug}/generated-reconstruction/viewer.html",
        wait_until="domcontentloaded",
    )
    assert response is not None
    assert response.status == 200
    assert page.url.endswith(f"/tours/files/{slug}/generated-reconstruction/viewer.html")
    assert page.title() == "Layout preview"
    assert page.locator("h1").inner_text().strip() == "Layout preview"
    initial_metrics = page.evaluate(
        """() => window.__pqReconstructionDebug?.getRenderMetrics?.() || null"""
    )
    assert isinstance(initial_metrics, dict)
    assert initial_metrics["ready"] is True
    assert initial_metrics["activeRouteIndex"] == 0
    page.evaluate("""() => window.__pqReconstructionDebug?.setRouteView?.(2)""")
    page.wait_for_function(
        """() => (window.__pqReconstructionDebug?.getRenderMetrics?.()?.activeRouteIndex ?? -1) === 2"""
    )
    updated_metrics = page.evaluate(
        """() => window.__pqReconstructionDebug?.getRenderMetrics?.() || null"""
    )
    assert isinstance(updated_metrics, dict)
    assert updated_metrics["activeRouteIndex"] == 2
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

    response = page.goto(url, wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 404
    assert page.url.endswith(f"/tours/{slug}")
    body_text = page.locator("body").inner_text()
    assert "This tour link is no longer available." in body_text
    assert "This link points to a generated layout reconstruction, not a published 3D tour." in body_text
    assert page.locator("canvas").count() == 0
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

    response = page.goto(url, wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 404
    assert page.url.endswith(f"/tours/{slug}")
    _assert_no_horizontal_overflow(page)
    body_text = page.locator("body").inner_text()
    assert "This tour link is no longer available." in body_text
    assert "This link points to a generated layout reconstruction, not a published 3D tour." in body_text
    assert page.locator("canvas").count() == 0
    assert "generated-reconstruction/viewer.html" not in body_text
    assert not page_errors
    assert not [
        message
        for message in console_errors
        if "failed to resolve module specifier" in message.lower()
        or "cannot use import statement" in message.lower()
    ]
    context.close()
