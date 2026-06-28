from __future__ import annotations

import io

from app.product import property_listing_extractors as extractors
from PIL import Image, ImageDraw


def test_property_scout_extract_detail_media_urls_keeps_transformed_gallery_images() -> None:
    source_url = "https://immobilien.derstandard.at/detail/15087506"
    favicon_url = "https://immobilien.derstandard.at/static/icons/favicon-96x96.png"
    gallery_variant_avif = (
        "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
        "storage.justimmo.at/thumb/abc123/fm_h1080_w1920/photo-1.jpg/~/token-a/"
        "format:avif/background:ffffff/rs:fill:1370:1060:1"
    )
    gallery_variant_jpg = (
        "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
        "storage.justimmo.at/thumb/abc123/fm_h1080_w1920/photo-1.jpg/~/token-b/"
        "format:jpg/background:ffffff/rs:fill:920:613:1"
    )
    second_gallery_jpg = (
        "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
        "storage.justimmo.at/thumb/def456/fm_h1080_w1920/photo-2.jpg/~/token-c/"
        "format:jpg/background:ffffff/rs:fill:920:613:1"
    )
    html = f"""
    <html>
      <head>
        <meta property="og:image" content="{favicon_url}">
      </head>
      <body>
        <img src="{gallery_variant_avif}" />
        <img src="{second_gallery_jpg}" />
        <img src="{gallery_variant_jpg}" />
      </body>
    </html>
    """

    media_urls = extractors._property_scout_extract_detail_media_urls(source_url=source_url, html=html)

    assert gallery_variant_jpg in media_urls
    assert gallery_variant_avif not in media_urls
    assert second_gallery_jpg in media_urls
    assert favicon_url in media_urls
    assert media_urls.index(gallery_variant_jpg) < media_urls.index(favicon_url)
    assert media_urls.index(second_gallery_jpg) < media_urls.index(favicon_url)
    assert len([url for url in media_urls if "/thumb/abc123/" in url]) == 1


def test_property_scout_extract_gallery_floorplan_urls_prefers_listing_media_over_site_icons(monkeypatch) -> None:
    source_url = "https://immobilien.derstandard.at/detail/15087506"
    icon_urls = tuple(
        f"https://immobilien.derstandard.at/static/icons/favicon-{size}.png"
        for size in ("16x16", "32x32", "96x96", "192x192")
    )
    gallery_urls = tuple(
        (
            "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
            f"storage.justimmo.at/thumb/gallery-{index}/fm_h1080_w1920/photo-{index}.jpg/~/token-{index}/"
            "format:jpg/background:ffffff/rs:fill:920:613:1"
        )
        for index in range(1, 8)
    )
    floorplan_url = (
        "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
        "storage.justimmo.at/thumb/media-9/fm_h1080_w1920/asset-9.jpg/~/token-9/"
        "format:jpg/background:ffffff/rs:fill:920:613:1"
    )
    business_card_url = (
        "https://i.prod.mp-dst.onyx60.com/plain/immoimporte/justimmo2/"
        "storage.justimmo.at/thumb/card-10/fm_h1080_w1920/card-10.jpg/~/token-10/"
        "format:jpg/background:ffffff/rs:fill:920:613:1"
    )
    media_urls = (*icon_urls, *gallery_urls, floorplan_url, business_card_url)

    def _fake_download(url: str, *, timeout_seconds: float = 12.0, max_bytes: int = 0) -> tuple[bytes, str]:
        return url.encode("utf-8"), "image/jpeg"

    def _fake_classifier(payload: bytes) -> tuple[bool, dict[str, object]]:
        url = payload.decode("utf-8")
        return (url == floorplan_url), {"status": "classified", "url": url}

    monkeypatch.setattr(extractors, "_property_scout_download_bytes", _fake_download)
    monkeypatch.setattr(extractors, "_property_scout_image_looks_like_floorplan", _fake_classifier)

    floorplan_urls, diagnostics = extractors._property_scout_extract_gallery_floorplan_urls(
        source_url=source_url,
        html="",
        media_urls=media_urls,
        resolve_images=True,
    )

    checked_urls = [str(row.get("url") or "") for row in diagnostics["visual_checks"]]
    assert floorplan_urls == (floorplan_url,)
    assert floorplan_url in checked_urls
    assert not any(url in checked_urls for url in icon_urls)
    assert diagnostics["visual_check_total"] == 8


def _light_scan_plan_bytes() -> bytes:
    image = Image.new("RGB", (920, 613), color=(252, 252, 252))
    draw = ImageDraw.Draw(image)
    wall = (100, 100, 100)
    divider = (150, 150, 150)
    for box in [((50, 40), (360, 560)), ((360, 40), (620, 280)), ((360, 280), (620, 560)), ((620, 40), (880, 560))]:
        draw.rectangle(box, outline=wall, width=3)
    for y in (120, 200, 280, 360, 440, 520):
        draw.line(((50, y), (880, y)), fill=divider, width=1)
    for x in (120, 200, 280, 360, 440, 520, 620, 700, 780):
        draw.line(((x, 40), (x, 560)), fill=divider, width=1)
    for box in [((90, 90), (180, 160)), ((250, 110), (330, 180)), ((430, 90), (550, 190)), ((680, 100), (820, 220)), ((680, 320), (830, 470))]:
        draw.rectangle(box, outline=(160, 160, 160), width=1)
    for points in [((360, 150), (420, 210)), ((620, 150), (680, 210)), ((360, 400), (420, 460)), ((620, 400), (680, 460))]:
        draw.line(points, fill=(120, 120, 120), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _wide_card_bytes() -> bytes:
    image = Image.new("RGB", (920, 180), color=(250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle(((20, 20), (280, 70)), fill=(210, 210, 210))
    draw.rectangle(((20, 100), (900, 145)), fill=(235, 235, 235))
    for y in (40, 70, 100):
        draw.line(((330, y), (870, y)), fill=(120, 120, 120), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_property_scout_image_looks_like_floorplan_accepts_light_scan_plan_and_rejects_wide_card() -> None:
    looks_like_plan, plan_diag = extractors._property_scout_image_looks_like_floorplan(_light_scan_plan_bytes())
    looks_like_card, card_diag = extractors._property_scout_image_looks_like_floorplan(_wide_card_bytes())

    assert looks_like_plan is True
    assert plan_diag["edge_mean"] >= 13
    assert plan_diag["light_ratio"] >= 0.78
    assert looks_like_card is False
    assert card_diag["height"] == 180
