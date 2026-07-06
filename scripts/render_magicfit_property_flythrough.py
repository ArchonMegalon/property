#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from property_magicfit_env import load_magicfit_env

MAGICFIT_HOME_URL = "https://magicfit.pushowl.com/home"
MAGICFIT_VIDEO_URL = "https://magicfit.pushowl.com/agents/generate?mode=video"
VIDEO_URL_RE = re.compile(r"https://(?:cdn\.pushowl\.com|media\.powlcdn\.com)/magicfit/[^\"'\s<>]+?\.(?:mp4|webm)(?:[^\"'\s<>]*)?")
NEGATIVE = ", ".join(
    [
        "no storyboard",
        "no slideshow",
        "no empty unfurnished flat",
        "no abrupt cut before final 240 degree sweep",
        "no ending cut before sweep completes",
        "no fade-out before final sweep",
        "no cartoon",
        "no toy diorama",
        "no visible text",
        "no watermark",
        "no broken geometry",
        "no sterile showroom look",
    ]
)
def load_env() -> None:
    load_magicfit_env()


def arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a MagicFit property flythrough clip.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--aspect-label", default="Landscape (16:9)")
    parser.add_argument("--timeout-minutes", type=int, default=18)
    parser.add_argument("--model-label", default="")
    parser.add_argument("--state-json", default="")
    parser.add_argument("--first-frame", default="", help="Optional image file to upload as MagicFit first-frame reference.")
    parser.add_argument("--extend-session-url", default="", help="Optional MagicFit session URL whose newest visible video should be continued.")
    parser.add_argument("--property-slug", default="", help="PropertyQuarry tour/property slug this walkthrough is being rendered for.")
    parser.add_argument("--property-title", default="", help="Human property title this walkthrough is being rendered for.")
    parser.add_argument("--property-url", default="", help="Source or hosted property URL this walkthrough is being rendered for.")
    return parser


def magicfit_duration(seconds: int) -> int:
    allowed = [4, 6, 8, 10, 12, 15]
    return min(allowed, key=lambda candidate: (abs(candidate - seconds), -candidate))


def collect_video_urls(text: str) -> list[str]:
    return list(dict.fromkeys(url.replace("\\u0026", "&").rstrip("),]") for url in VIDEO_URL_RE.findall(text or "")))


def url_timestamp(url: str) -> int:
    match = re.search(r"/magicfit/(\d+)-", url)
    if match is None:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def choose_newest_video(urls: set[str], baseline: set[str], submitted_at_ms: int) -> str:
    candidates: list[tuple[int, str]] = []
    for url in urls:
        if url in baseline:
            continue
        if "/ik-thumbnail." in url:
            continue
        timestamp = url_timestamp(url)
        if timestamp and timestamp < submitted_at_ms - 120000:
            continue
        candidates.append((timestamp, url))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else ""


def download(url: str, out_path: Path) -> None:
    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                handle.write(chunk)


def maybe_login(page) -> None:
    print("magicfit: open home", flush=True)
    page.goto(MAGICFIT_HOME_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(4000)
    body = page.locator("body").inner_text(timeout=10000)
    if not re.search(r"login|sign in|email|password", body, re.I):
        print("magicfit: already logged in", flush=True)
        return
    email = (os.environ.get("PROPERTYQUARRY_MAGICFIT_EMAIL") or os.environ.get("MAGICFIT_EMAIL") or "").strip()
    password = (os.environ.get("PROPERTYQUARRY_MAGICFIT_PASSWORD") or os.environ.get("MAGICFIT_PASSWORD") or "").strip()
    if not email or not password:
        raise RuntimeError("magicfit_credentials_missing")
    email_field = page.locator("input[type=email], input[name*=email i], input[placeholder*=email i]").first
    if email_field.count():
        email_field.fill(email)
    password_field = page.locator("input[type=password]").first
    if password_field.count():
        password_field.fill(password)
    submit = page.get_by_role("button", name=re.compile(r"sign in|login|continue|submit", re.I)).first
    if submit.count():
        submit.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(8000)
    print("magicfit: login submitted", flush=True)


def select_button(page, current_text: str, option_text: str) -> None:
    try:
        page.get_by_role("button", name=current_text).last.click(timeout=10000)
        page.wait_for_timeout(500)
        page.get_by_text(option_text, exact=True).last.click(timeout=10000)
        page.wait_for_timeout(500)
    except PlaywrightTimeoutError:
        pass


def select_option_from_known_current(page, *, current_options: list[str], option_text: str) -> bool:
    for current_text in current_options:
        try:
            page.get_by_role("button", name=current_text, exact=True).last.click(timeout=4000)
            page.wait_for_timeout(500)
            page.get_by_text(option_text, exact=True).last.click(timeout=8000)
            page.wait_for_timeout(800)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def fill_prompt(page, prompt: str) -> None:
    box = page.locator('[contenteditable="true"][role="textbox"]').first
    box.wait_for(timeout=10000)
    box.evaluate(
        """(node) => {
            node.scrollIntoView({ block: 'center', inline: 'nearest' });
            node.focus();
            node.textContent = '';
        }"""
    )
    page.wait_for_timeout(200)
    box.click(timeout=10000, force=True)
    page.keyboard.type(prompt, delay=1)
    page.wait_for_timeout(800)


def upload_first_frame(page, image_path: Path) -> None:
    if not image_path.is_file():
        raise RuntimeError(f"magicfit_first_frame_missing:{image_path}")
    before_images = 0
    with contextlib.suppress(Exception):
        before_images = int(page.locator("img").count())
    try:
        page.get_by_role("button", name=re.compile(r"first frame", re.I)).first.click(timeout=5000, force=True)
        page.wait_for_timeout(500)
    except PlaywrightTimeoutError:
        pass
    uploaded = False
    try:
        with page.expect_file_chooser(timeout=4000) as chooser_info:
            page.get_by_role("button", name=re.compile(r"first frame|upload", re.I)).first.click(timeout=4000, force=True)
        chooser_info.value.set_files(str(image_path))
        uploaded = True
    except Exception:
        file_input = page.locator("input[type=file][accept*='image']").first
        if not file_input.count():
            page.get_by_text("Upload", exact=True).first.click(timeout=10000, force=True)
            page.wait_for_timeout(1000)
            file_input = page.locator("input[type=file][accept*='image']").first
        file_input.set_input_files(str(image_path))
        uploaded = True
    page.wait_for_timeout(8000)
    remove_visible = False
    after_images = before_images
    with contextlib.suppress(Exception):
        remove_visible = bool(page.get_by_role("button", name=re.compile(r"remove", re.I)).first.is_visible(timeout=1500))
    with contextlib.suppress(Exception):
        after_images = int(page.locator("img").count())
    body = ""
    with contextlib.suppress(Exception):
        body = page.locator("body").inner_text(timeout=3000)
    if not uploaded or (not remove_visible and after_images <= before_images and "First Frame" not in body):
        raise RuntimeError("magicfit_first_frame_upload_unverified")


def load_session_video_for_extend(page, session_url: str) -> None:
    page.goto(session_url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(6000)
    videos = page.locator("video")
    selected = False
    for index in range(videos.count()):
        candidate = videos.nth(index)
        box = candidate.bounding_box()
        if box and box.get("width", 0) > 50 and box.get("height", 0) > 50:
            candidate.click(timeout=10000, force=True)
            page.wait_for_timeout(1500)
            selected = True
            break
    if not selected:
        raise RuntimeError("magicfit_extend_source_video_not_visible")
    try:
        page.get_by_role("button", name=re.compile(r"^Tweak$", re.I)).last.click(timeout=10000, force=True)
        page.wait_for_timeout(5000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("magicfit_extend_tweak_unavailable") from exc
    # Tweak opens the selected MagicFit result in the composer with the existing
    # source attached. For video outputs it exposes First Frame / Last Frame
    # controls; keep that state instead of switching to the top-level Extend tab,
    # which expects a separate source selection.


def collect_visible_video_urls(page) -> set[str]:
    urls: set[str] = set()
    html = page.content()
    urls.update(collect_video_urls(html))
    try:
        video_urls = page.locator("video").evaluate_all("(nodes) => nodes.map((v) => v.currentSrc || v.src).filter(Boolean)")
    except Exception:
        video_urls = []
    for url in list(video_urls or []):
        if "magicfit" in str(url):
            urls.add(str(url))
    return urls


def write_debug_snapshot(page, *, poll_count: int, label: str = "poll") -> None:
    debug_dir_raw = str(os.environ.get("MAGICFIT_DEBUG_DIR") or "").strip()
    if not debug_dir_raw:
        return
    debug_dir = Path(debug_dir_raw).expanduser()
    debug_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{label}-{poll_count:03d}"
    with contextlib.suppress(Exception):
        page.screenshot(path=str(debug_dir / f"{prefix}.png"), full_page=True, timeout=10000)
    with contextlib.suppress(Exception):
        body_text = page.locator("body").inner_text(timeout=5000)
        (debug_dir / f"{prefix}.txt").write_text(body_text, encoding="utf-8", errors="replace")
    with contextlib.suppress(Exception):
        (debug_dir / f"{prefix}.url.txt").write_text(str(page.url or ""), encoding="utf-8")


def visible_body_text(page) -> str:
    with contextlib.suppress(Exception):
        return str(page.locator("body").inner_text(timeout=5000) or "")
    return ""


def raise_if_credit_blocked(page) -> None:
    body_text = visible_body_text(page)
    if re.search(r"\bnot enough credits\b|\bbuy credits\b", body_text, flags=re.IGNORECASE):
        raise RuntimeError("magicfit_not_enough_credits")


def run() -> int:
    load_env()
    args = arg_parser().parse_args()
    out_path = Path(args.out).resolve()
    state_path = Path(args.state_json).resolve() if args.state_json else None
    first_frame_path = Path(args.first_frame).expanduser().resolve() if args.first_frame else None
    prompt = f"{args.prompt.strip()} Global constraints: {NEGATIVE}."
    provider_duration = magicfit_duration(int(args.duration or 10))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
        page = context.new_page()
        try:
            maybe_login(page)
            if args.extend_session_url:
                print("magicfit: open extend source session", flush=True)
                load_session_video_for_extend(page, args.extend_session_url)
            else:
                print("magicfit: open video generator", flush=True)
                page.goto(MAGICFIT_VIDEO_URL, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(5000)
            baseline = collect_visible_video_urls(page)
            print(f"magicfit: baseline urls={len(baseline)}", flush=True)
            select_option_from_known_current(
                page,
                current_options=["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "Portrait (9:16)", "Landscape (16:9)"],
                option_text=args.aspect_label,
            )
            duration_selected = select_option_from_known_current(
                page,
                current_options=["4s", "5s", "6s", "7s", "8s", "9s", "10s", "11s", "12s", "13s", "14s", "15s"],
                option_text=f"{provider_duration}s",
            )
            print(f"magicfit: duration_target={provider_duration}s selected={duration_selected}", flush=True)
            if args.model_label:
                model_selected = select_option_from_known_current(
                    page,
                    current_options=[
                        "Seedance 2.0 Fast",
                        "Seedance 2.0",
                        "Kling 3.0",
                        "Kling 2.6 Pro",
                        "Kling O1",
                        "VEO 3.1 Fast",
                        "VEO 3.1",
                        "Veo 3.1 Fast",
                        "Veo 3.1",
                    ],
                    option_text=args.model_label,
                )
                print(f"magicfit: model_target={args.model_label} selected={model_selected}", flush=True)
            if first_frame_path is not None:
                print("magicfit: upload first frame", flush=True)
                upload_first_frame(page, first_frame_path)
            fill_prompt(page, prompt)
            events: list[dict[str, object]] = []
            seen_urls: set[str] = set()

            def handle_response(response) -> None:
                url = response.url
                if "magicfit" not in url and "pushowl" not in url:
                    return
                item = {
                    "method": response.request.method,
                    "status": response.status,
                    "url": url,
                    "content_type": response.headers.get("content-type", ""),
                }
                events.append(item)
                if re.search(r"(?:cdn\.pushowl\.com|media\.powlcdn\.com)/magicfit/.*\.(mp4|webm)(?:$|\?)", url):
                    seen_urls.add(url)
                try:
                    body = response.text() if re.search(r"json|script|text", item["content_type"], re.I) else ""
                except Exception:
                    body = ""
                if body:
                    seen_urls.update(collect_video_urls(body))

            page.on("response", handle_response)
            submitted_at_ms = int(time.time() * 1000)
            submit = page.locator("form button").last
            print("magicfit: submit job", flush=True)
            submit.click(timeout=30000)
            page.wait_for_timeout(3000)
            write_debug_snapshot(page, poll_count=0, label="submitted")
            raise_if_credit_blocked(page)
            deadline = time.time() + max(int(args.timeout_minutes or 18), 1) * 60
            video_url = ""
            poll_count = 0
            while time.time() < deadline and not video_url:
                page.wait_for_timeout(10000)
                poll_count += 1
                raise_if_credit_blocked(page)
                seen_urls.update(collect_visible_video_urls(page))
                video_url = choose_newest_video(seen_urls, baseline, submitted_at_ms)
                print(f"magicfit: poll={poll_count} seen_urls={len(seen_urls)} found={bool(video_url)}", flush=True)
                if poll_count <= 3 or poll_count % 12 == 0:
                    write_debug_snapshot(page, poll_count=poll_count)
            if not video_url:
                write_debug_snapshot(page, poll_count=poll_count, label="failed")
                raise RuntimeError("magicfit_video_url_not_found")
            print("magicfit: download clip", flush=True)
            download(video_url, out_path)
            payload = {
                "provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "render_status": "completed",
                "video_output_url": video_url,
                "hosted_walkthrough_video_url": video_url,
                "output_file": str(out_path),
                "target_slug": str(args.property_slug or "").strip(),
                "property_slug": str(args.property_slug or "").strip(),
                "property_title": str(args.property_title or "").strip(),
                "property_url": str(args.property_url or "").strip(),
                "duration_seconds_requested": int(args.duration or 10),
                "duration_seconds_magicfit": provider_duration,
                "aspect_label": args.aspect_label,
                "prompt": prompt,
                "page_url": page.url,
                "events_tail": events[-80:],
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            if state_path is not None:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(json.dumps(payload))
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(run())
