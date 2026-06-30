#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat


DEFAULT_DISCOVER_ROUTES = ("/app/search",)
PREVIEW_RE = re.compile(r"""(?P<url>(?:https?://[^"'\s<>]+)?/app/api/property/map-previews/[0-9a-f]{40}\.png)""")
ARTIFACT_PATTERNS = (
    b"xterm.js",
    b"created with the trial",
    b"traceback",
    b"debug toolbar",
    b"localhost:",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check(name: str, ok: bool, **extra: object) -> dict[str, object]:
    return {"name": name, "ok": bool(ok), **extra}


def _headers(*, host_header: str = "", api_token: str = "", principal_id: str = "", accept: str = "*/*") -> dict[str, str]:
    headers = {"User-Agent": "PropertyQuarry-map-preview-flagship-gate/1.0", "Accept": accept}
    if host_header:
        headers["Host"] = host_header
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    return headers


def _fetch(
    url: str,
    *,
    timeout_seconds: float,
    host_header: str = "",
    api_token: str = "",
    principal_id: str = "",
    accept: str = "*/*",
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=_headers(host_header=host_header, api_token=api_token, principal_id=principal_id, accept=accept),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(2_500_000)
            return {
                "status_code": int(response.status),
                "final_url": str(response.geturl()),
                "headers": dict(response.headers.items()),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        return {
            "status_code": int(exc.code),
            "final_url": str(exc.geturl()),
            "headers": dict(exc.headers.items()),
            "body": exc.read(200_000),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "final_url": url,
            "headers": {},
            "body": b"",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _header(headers: dict[str, object], name: str) -> str:
    normalized = name.lower()
    for key, value in headers.items():
        if str(key).lower() == normalized:
            return str(value or "").strip()
    return ""


def _absolute_url(base_url: str, value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        return raw
    if re.match(r"^https?://", raw, flags=re.IGNORECASE):
        return raw
    return urllib.parse.urljoin(str(base_url or "").rstrip("/") + "/", raw.lstrip("/"))


def _discover_preview_urls(
    *,
    base_url: str,
    routes: list[str],
    timeout_seconds: float,
    host_header: str,
    api_token: str,
    principal_id: str,
    discovery_results: list[dict[str, object]] | None = None,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for route in routes:
        route_url = _absolute_url(base_url, route)
        started = time.monotonic()
        response = _fetch(
            route_url,
            timeout_seconds=timeout_seconds,
            host_header=host_header,
            api_token=api_token,
            principal_id=principal_id,
            accept="text/html,*/*",
        )
        elapsed_ms = int(round((time.monotonic() - started) * 1000))
        body = bytes(response.get("body") or b"").decode("utf-8", errors="replace")
        before_count = len(urls)
        for match in PREVIEW_RE.finditer(body):
            url = _absolute_url(base_url, match.group("url"))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        if discovery_results is not None:
            discovery_results.append(
                {
                    "route": route,
                    "url": route_url,
                    "status_code": int(response.get("status_code") or 0),
                    "elapsed_ms": elapsed_ms,
                    "body_bytes": len(bytes(response.get("body") or b"")),
                    "preview_count": len(urls) - before_count,
                    "error": str(response.get("error") or "").strip(),
                }
            )
    return urls


def _read_image(url: str, *, timeout_seconds: float, host_header: str) -> dict[str, Any]:
    if url.startswith("file://"):
        path = Path(urllib.parse.urlparse(url).path)
        body = path.read_bytes() if path.is_file() else b""
        return {
            "status_code": 200 if body else 404,
            "final_url": url,
            "headers": {"Content-Type": "image/png", "X-Property-Map-Preview-State": "ready"},
            "body": body,
        }
    return _fetch(url, timeout_seconds=timeout_seconds, host_header=host_header, accept="image/png,*/*")


def _image_metrics(body: bytes) -> dict[str, object]:
    image = Image.open(BytesIO(body)).convert("RGB")
    width, height = image.size
    if hasattr(image, "get_flattened_data"):
        pixels = list(image.get_flattened_data())
    else:
        pixels = list(image.getdata())
    count = max(len(pixels), 1)
    stat = ImageStat.Stat(image)
    channel_stddev = list(stat.stddev)
    red_dominant = sum(1 for r, g, b in pixels if r > g * 1.18 and r > b * 1.18 and r > 120) / count
    strong_red = sum(1 for r, g, b in pixels if r > 150 and r - g > 35 and r - b > 35) / count
    hot_red = sum(1 for r, g, b in pixels if r > 160 and g < 120 and b < 120) / count
    dark_red_edge = sum(1 for r, g, b in pixels if 80 < r < 170 and g < 70 and b < 80) / count
    dark = sum(1 for r, g, b in pixels if max(r, g, b) < 80) / count
    very_dark = sum(1 for r, g, b in pixels if max(r, g, b) < 50) / count
    near_white = sum(1 for r, g, b in pixels if min(r, g, b) > 235) / count
    saturated = sum(1 for r, g, b in pixels if max(r, g, b) - min(r, g, b) > 90) / count
    thumbnail = image.resize((160, 92))
    edge_image = thumbnail.convert("L").filter(ImageFilter.FIND_EDGES)
    if hasattr(edge_image, "get_flattened_data"):
        edge_pixels = list(edge_image.get_flattened_data())
    else:
        edge_pixels = list(edge_image.getdata())
    edge_count = max(len(edge_pixels), 1)
    thumbnail_edge_mean = sum(edge_pixels) / edge_count
    thumbnail_edge_ratio = sum(1 for value in edge_pixels if value > 32) / edge_count
    return {
        "width": width,
        "height": height,
        "byte_count": len(body),
        "stddev_mean": sum(channel_stddev) / max(len(channel_stddev), 1),
        "red_dominant_ratio": red_dominant,
        "strong_red_ratio": strong_red,
        "hot_red_ratio": hot_red,
        "dark_red_edge_ratio": dark_red_edge,
        "dark_ratio": dark,
        "very_dark_ratio": very_dark,
        "near_white_ratio": near_white,
        "saturated_ratio": saturated,
        "thumbnail_edge_mean": thumbnail_edge_mean,
        "thumbnail_edge_ratio": thumbnail_edge_ratio,
    }


def _artifact_hits(body: bytes) -> list[str]:
    lowered = body.lower()
    return [pattern.decode("utf-8", errors="replace") for pattern in ARTIFACT_PATTERNS if pattern in lowered]


def _evaluate_preview(url: str, *, timeout_seconds: float, host_header: str, settle_seconds: float = 0.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, float(settle_seconds or 0.0))
    response = _read_image(url, timeout_seconds=timeout_seconds, host_header=host_header)
    while True:
        preview_state = _header(dict(response.get("headers") or {}), "X-Property-Map-Preview-State").lower()
        if preview_state != "pending" or time.monotonic() >= deadline:
            break
        time.sleep(0.5)
        response = _read_image(url, timeout_seconds=timeout_seconds, host_header=host_header)
    headers = dict(response.get("headers") or {})
    body = bytes(response.get("body") or b"")
    content_type = _header(headers, "Content-Type").lower()
    preview_state = _header(headers, "X-Property-Map-Preview-State").lower()
    checks: list[dict[str, object]] = [
        _check("http_200", int(response.get("status_code") or 0) == 200, status_code=response.get("status_code")),
        _check("content_type_png", content_type.startswith("image/png"), content_type=content_type),
        _check("preview_ready", preview_state in {"ready", ""}, preview_state=preview_state),
        _check("no_embedded_artifact_text", not _artifact_hits(body), artifact_hits=_artifact_hits(body)),
    ]
    metrics: dict[str, object] = {}
    if body:
        try:
            metrics = _image_metrics(body)
        except Exception as exc:
            checks.append(_check("png_decodes", False, error=f"{type(exc).__name__}: {exc}"))
        else:
            checks.extend(
                [
                    _check("png_decodes", True),
                    _check("flagship_dimensions", metrics["width"] == 640 and metrics["height"] == 368, width=metrics["width"], height=metrics["height"]),
                    _check("not_placeholder_sized", int(metrics["byte_count"]) >= 18_000, byte_count=metrics["byte_count"]),
                    _check("not_blank", float(metrics["stddev_mean"]) >= 10.0, stddev_mean=metrics["stddev_mean"]),
                    _check("map_backdrop_visible", float(metrics["stddev_mean"]) >= 18.0, stddev_mean=metrics["stddev_mean"], thumbnail_edge_ratio=metrics["thumbnail_edge_ratio"]),
                    _check("not_mostly_empty_canvas", float(metrics["near_white_ratio"]) <= 0.55, near_white_ratio=metrics["near_white_ratio"]),
                    _check("thumbnail_detail_not_noisy", float(metrics["thumbnail_edge_ratio"]) <= 0.34 and float(metrics["thumbnail_edge_mean"]) <= 34.0, thumbnail_edge_ratio=metrics["thumbnail_edge_ratio"], thumbnail_edge_mean=metrics["thumbnail_edge_mean"]),
                    _check("red_overlay_not_aggressive", float(metrics["strong_red_ratio"]) <= 0.14 and float(metrics["red_dominant_ratio"]) <= 0.18, strong_red_ratio=metrics["strong_red_ratio"], red_dominant_ratio=metrics["red_dominant_ratio"]),
                    _check("hot_red_not_dominant", float(metrics["hot_red_ratio"]) <= 0.075, hot_red_ratio=metrics["hot_red_ratio"]),
                    _check("border_noise_not_heavy", float(metrics["dark_red_edge_ratio"]) <= 0.014, dark_red_edge_ratio=metrics["dark_red_edge_ratio"]),
                    _check("dark_noise_not_heavy", float(metrics["very_dark_ratio"]) <= 0.018, very_dark_ratio=metrics["very_dark_ratio"]),
                    _check("color_density_controlled", float(metrics["saturated_ratio"]) <= 0.30, saturated_ratio=metrics["saturated_ratio"]),
                ]
            )
    failed = [row for row in checks if not row.get("ok")]
    return {
        "url": url,
        "status": "pass" if not failed else "fail",
        "failed_count": len(failed),
        "checks": checks,
        "metrics": metrics,
    }


def build_map_preview_flagship_receipt(
    *,
    base_url: str,
    host_header: str,
    api_token: str,
    principal_id: str,
    image_urls: list[str],
    discover_routes: list[str],
    timeout_seconds: float,
    settle_seconds: float,
    min_preview_count: int,
) -> dict[str, Any]:
    base = str(base_url or "http://localhost:8097").strip().rstrip("/")
    urls: list[str] = []
    seen: set[str] = set()
    discovery_results: list[dict[str, object]] = []
    for image_url in image_urls:
        absolute = _absolute_url(base, image_url)
        if absolute and absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    if not urls:
        for discovered in _discover_preview_urls(
            base_url=base,
            routes=discover_routes,
            timeout_seconds=timeout_seconds,
            host_header=host_header,
            api_token=api_token,
                principal_id=principal_id,
                discovery_results=discovery_results,
            ):
            if discovered not in seen:
                seen.add(discovered)
                urls.append(discovered)
    preview_results = [
        _evaluate_preview(url, timeout_seconds=timeout_seconds, host_header=host_header, settle_seconds=settle_seconds)
        for url in urls
    ]
    checks: list[dict[str, object]] = [
        _check("preview_count", len(preview_results) >= min_preview_count, count=len(preview_results), min_count=min_preview_count)
    ]
    for index, result in enumerate(preview_results, start=1):
        checks.append(
            _check(
                f"preview_{index}_flagship",
                result.get("status") == "pass",
                url=result.get("url"),
                failed_count=result.get("failed_count"),
                metrics=result.get("metrics") or {},
            )
        )
    failed = [row for row in checks if not row.get("ok")]
    return {
        "contract_name": "propertyquarry.map_preview_flagship_gate.v1",
        "generated_at": _utc_now(),
        "status": "pass" if not failed else "fail",
        "base_url": base,
        "host_header": host_header,
        "discover_routes": discover_routes,
        "discovery_results": discovery_results,
        "preview_count": len(preview_results),
        "failed_count": len(failed),
        "checks": checks,
        "preview_results": preview_results,
        "notes": [
            "This is a visual-asset gate. A PNG route being available is not enough.",
            "The gate rejects pending placeholders, blank canvases, excessive red overlays, heavy dark border noise, and embedded artifact/debug text.",
            "The gate also requires enough map texture to keep streets and labels visible beneath the selected-area overlay.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate PropertyQuarry map previews against a flagship visual standard.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_LIVE_BASE_URL", "http://localhost:8097"))
    parser.add_argument("--host-header", default=os.getenv("PROPERTYQUARRY_LIVE_HOST_HEADER", "propertyquarry.com"))
    parser.add_argument("--api-token", default=os.getenv("EA_API_TOKEN", ""))
    parser.add_argument("--principal-id", default=os.getenv("EA_PRINCIPAL_ID", "pq-map-preview-gate"))
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--discover-route", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--settle-seconds", type=float, default=6.0)
    parser.add_argument("--min-preview-count", type=int, default=1)
    parser.add_argument("--write", default="_completion/smoke/property-live-map-preview-flagship-latest.json")
    args = parser.parse_args()
    env_urls = [
        item.strip()
        for item in str(os.getenv("PROPERTYQUARRY_MAP_PREVIEW_GATE_URLS") or "").split(",")
        if item.strip()
    ]
    receipt = build_map_preview_flagship_receipt(
        base_url=args.base_url,
        host_header=args.host_header,
        api_token=args.api_token,
        principal_id=args.principal_id,
        image_urls=list(args.image_url or []) + env_urls,
        discover_routes=list(args.discover_route or DEFAULT_DISCOVER_ROUTES),
        timeout_seconds=max(1.0, float(args.timeout_seconds or 12.0)),
        settle_seconds=max(0.0, float(args.settle_seconds or 0.0)),
        min_preview_count=max(1, int(args.min_preview_count or 1)),
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
