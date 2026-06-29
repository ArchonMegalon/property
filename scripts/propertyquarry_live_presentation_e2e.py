#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from scripts.propertyquarry_live_mobile_surface_smoke import seed_research_detail_fixture


DEFAULT_DEMO_SLUG = "luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557"
DEFAULT_PROVIDER_RECEIPT = "_completion/smoke/property-live-provider-latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _visible_text(text: str) -> str:
    without_hidden = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_hidden)
    return re.sub(r"\s+", " ", without_tags).strip()


def _fetch(
    url: str,
    *,
    timeout_seconds: float,
    host_header: str = "",
    api_token: str = "",
    principal_id: str = "",
    method: str = "GET",
) -> dict[str, Any]:
    headers = {
        "User-Agent": "PropertyQuarry-live-presentation-e2e/1.0",
        "Accept": "text/html,application/json,video/*,*/*",
    }
    if host_header:
        headers["Host"] = host_header
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        headers["X-EA-API-Token"] = api_token
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = b"" if method == "HEAD" else response.read(1_500_000)
            return {
                "status_code": int(response.status),
                "final_url": str(response.geturl()),
                "headers": dict(response.headers.items()),
                "body": body.decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as exc:
        body = b"" if method == "HEAD" else exc.read(1_500_000)
        return {
            "status_code": int(exc.code),
            "final_url": str(exc.geturl()),
            "headers": dict(exc.headers.items()),
            "body": body.decode("utf-8", errors="replace"),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "final_url": url,
            "headers": {},
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _header(headers: dict[str, object], name: str) -> str:
    normalized = name.lower()
    for key, value in headers.items():
        if str(key).lower() == normalized:
            return str(value or "").strip()
    return ""


def _load_json(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _check(name: str, ok: bool, **extra: object) -> dict[str, object]:
    return {"name": name, "ok": bool(ok), **extra}


def build_live_presentation_e2e_receipt(
    *,
    base_url: str,
    host_header: str,
    api_token: str,
    principal_id: str,
    provider_receipt_path: str,
    demo_slug: str,
    timeout_seconds: float,
    seed_research_detail: bool,
) -> dict[str, Any]:
    base = str(base_url or "http://localhost:8097").strip().rstrip("/")
    slug = str(demo_slug or DEFAULT_DEMO_SLUG).strip()
    checks: list[dict[str, object]] = []

    provider_receipt = _load_json(provider_receipt_path)
    provider_summary = provider_receipt.get("targeted_search_matrix_summary")
    provider_summary = dict(provider_summary) if isinstance(provider_summary, dict) else {}
    checks.append(
        _check(
            "search_provider_matrix_executed",
            provider_receipt.get("status") == "pass"
            and provider_receipt.get("targeted_search_matrix_executed") is True
            and provider_receipt.get("targeted_search_matrix_status") == "pass",
            receipt_path=provider_receipt_path,
            count=provider_receipt.get("targeted_search_matrix_count"),
            status_counts=provider_summary.get("status_counts"),
        )
    )

    home = _fetch(
        f"{base}/?home=1",
        timeout_seconds=timeout_seconds,
        host_header=host_header,
    )
    home_body = str(home.get("body") or "")
    checks.extend(
        [
            _check("hero_route_ok", int(home.get("status_code") or 0) == 200, status_code=home.get("status_code")),
            _check("hero_demo_listing_visible", "Danube Flats demo" in home_body),
            _check("hero_demo_link_points_to_public_tour", f'href="/tours/{slug}"' in home_body),
            _check("hero_3dvista_chip_visible", "3DVista ready" in home_body and f"/tours/{slug}/control/3dvista" in home_body),
            _check("hero_walkthrough_chip_visible", "Walkthrough ready" in home_body and f"/tours/files/{slug}/" in home_body),
        ]
    )

    demo_path = f"/tours/{urllib.parse.quote(slug, safe='')}"
    demo = _fetch(f"{base}{demo_path}", timeout_seconds=timeout_seconds, host_header=host_header)
    demo_body = str(demo.get("body") or "")
    checks.extend(
        [
            _check("demo_tour_route_ok", int(demo.get("status_code") or 0) == 200, status_code=demo.get("status_code")),
            _check("demo_tour_is_propertyquarry_presentation", "PropertyQuarry Spatial Review" in demo_body),
            _check("demo_tour_has_matterport", "Open Matterport" in demo_body and f"{demo_path}/control/matterport" in demo_body),
            _check("demo_tour_has_3dvista", "Open 3DVista" in demo_body and f"{demo_path}/control/3dvista" in demo_body),
            _check("demo_tour_has_pano2vr", "Open Pano2VR" in demo_body and f"{demo_path}/control/pano2vr" in demo_body),
            _check("demo_tour_has_magicfit_walkthrough", "Open Fly-through" in demo_body and "magicfit-walkthrough.mp4" in demo_body),
            _check("demo_tour_no_generated_cube_fallback", "generated 3d cube fallback has been removed" in _visible_text(demo_body).lower()),
        ]
    )

    for provider, marker in (
        ("3dvista", "3DVista Control"),
        ("matterport", "Matterport Control"),
        ("pano2vr", "Pano2VR Control"),
    ):
        route = f"{demo_path}/control/{provider}"
        response = _fetch(f"{base}{route}", timeout_seconds=timeout_seconds, host_header=host_header)
        body = str(response.get("body") or "")
        checks.extend(
            [
                _check(f"{provider}_control_route_ok", int(response.get("status_code") or 0) == 200, route=route, status_code=response.get("status_code")),
                _check(f"{provider}_control_marker_visible", marker in body, route=route),
            ]
        )

    walkthrough_path = f"/tours/files/{urllib.parse.quote(slug, safe='')}/magicfit-walkthrough.mp4"
    video = _fetch(f"{base}{walkthrough_path}", timeout_seconds=timeout_seconds, host_header=host_header, method="HEAD")
    content_type = _header(dict(video.get("headers") or {}), "Content-Type").lower()
    content_length = _header(dict(video.get("headers") or {}), "Content-Length")
    try:
        video_bytes = int(content_length or "0")
    except Exception:
        video_bytes = 0
    checks.extend(
        [
            _check("magicfit_walkthrough_route_ok", int(video.get("status_code") or 0) == 200, status_code=video.get("status_code")),
            _check("magicfit_walkthrough_is_video", content_type.startswith("video/"), content_type=content_type),
            _check("magicfit_walkthrough_not_stub", video_bytes > 1_000_000, content_length=video_bytes),
        ]
    )

    seeded_route = ""
    if seed_research_detail:
        try:
            seeded_route = seed_research_detail_fixture(
                base_url=base,
                api_token=api_token,
                principal_id=principal_id,
                host_header=host_header,
            )
        except Exception as exc:
            checks.append(_check("app_research_detail_seeded", False, error=f"{type(exc).__name__}: {exc}"))
    if seeded_route:
        checks.append(_check("app_research_detail_seeded", True, route=seeded_route))
        detail = _fetch(
            f"{base}{seeded_route}",
            timeout_seconds=timeout_seconds,
            host_header=host_header,
            api_token=api_token,
            principal_id=principal_id,
        )
        detail_body = str(detail.get("body") or "")
        checks.extend(
            [
                _check("app_research_detail_route_ok", int(detail.get("status_code") or 0) == 200, status_code=detail.get("status_code")),
                _check("app_research_detail_visual_controls", 'data-pw-visual-request="tour"' in detail_body and 'data-pw-visual-request="flythrough"' in detail_body),
                _check("app_research_detail_magicfit_only_walkthrough", 'data-pw-walkthrough-provider="magicfit"' in detail_body),
            ]
        )

    failed = [row for row in checks if not row.get("ok")]
    return {
        "contract_name": "propertyquarry.live_presentation_e2e.v1",
        "generated_at": _utc_now(),
        "status": "pass" if not failed else "fail",
        "base_url": base,
        "host_header": host_header,
        "principal_id": principal_id,
        "demo_slug": slug,
        "demo_url": f"https://propertyquarry.com{demo_path}",
        "seeded_research_detail_route": seeded_route,
        "provider_receipt_path": provider_receipt_path,
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
        "notes": [
            "This receipt composes the latest provider search E2E matrix with live presentation and media probes.",
            "It is not a browser-click-through from a newly submitted search; it fails if the provider matrix is not an executed pass.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live PropertyQuarry presentation E2E receipt.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_LIVE_BASE_URL", "http://localhost:8097"))
    parser.add_argument("--host-header", default=os.getenv("PROPERTYQUARRY_LIVE_HOST_HEADER", "propertyquarry.com"))
    parser.add_argument("--api-token", default=os.getenv("EA_API_TOKEN", ""))
    parser.add_argument("--principal-id", default=os.getenv("EA_PRINCIPAL_ID", "cf-email:tibor.girschele@gmail.com"))
    parser.add_argument("--provider-receipt", default=DEFAULT_PROVIDER_RECEIPT)
    parser.add_argument("--demo-slug", default=DEFAULT_DEMO_SLUG)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--no-seed-research-detail", action="store_true")
    parser.add_argument("--write", default="_completion/smoke/property-live-presentation-e2e-latest.json")
    args = parser.parse_args()

    receipt = build_live_presentation_e2e_receipt(
        base_url=args.base_url,
        host_header=args.host_header,
        api_token=args.api_token,
        principal_id=args.principal_id,
        provider_receipt_path=args.provider_receipt,
        demo_slug=args.demo_slug,
        timeout_seconds=max(1.0, float(args.timeout_seconds or 20.0)),
        seed_research_detail=not bool(args.no_seed_research_detail),
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
