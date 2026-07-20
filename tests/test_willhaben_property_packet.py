from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from PIL import Image


def _load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "willhaben_property_packet.py"
    spec = importlib.util.spec_from_file_location("willhaben_property_packet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _jpeg_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(64, 96, 128)).save(buffer, format="JPEG")
    return buffer.getvalue()


_FETCH_HTML_IMPORT_PROBE = """
import importlib.util
import sys

script = sys.argv[1]
spec = importlib.util.spec_from_file_location("willhaben_property_packet_subprocess", script)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from app.product import outbound_url_security

class Response:
    text = "ok"

    def raise_for_status(self):
        return None

outbound_url_security.request_get_with_guarded_redirects = lambda *args, **kwargs: Response()
assert module.fetch_html("https://www.willhaben.at/iad/immobilien/d/test-1") == "ok"
"""


def _assert_fetch_html_imports_app(*, script: Path, cwd: Path) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"}
    }

    completed = subprocess.run(
        [sys.executable, "-c", _FETCH_HTML_IMPORT_PROBE, str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_fetch_html_bootstraps_app_import_from_non_repo_cwd(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "willhaben_property_packet.py"

    _assert_fetch_html_imports_app(script=script, cwd=tmp_path)


def test_fetch_html_bootstraps_packaged_app_import_from_non_repo_cwd(tmp_path: Path) -> None:
    image_root = tmp_path / "app"
    script_dir = image_root / "scripts"
    product_dir = image_root / "app" / "product"
    outside_cwd = tmp_path / "outside"
    script_dir.mkdir(parents=True)
    product_dir.mkdir(parents=True)
    outside_cwd.mkdir()
    script = script_dir / "willhaben_property_packet.py"
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "willhaben_property_packet.py",
        script,
    )
    (product_dir.parent / "__init__.py").write_text("", encoding="utf-8")
    (product_dir / "__init__.py").write_text("", encoding="utf-8")
    (product_dir / "outbound_url_security.py").write_text(
        "def request_get_with_guarded_redirects(*args, **kwargs):\n"
        "    raise AssertionError('probe must replace this function')\n",
        encoding="utf-8",
    )

    _assert_fetch_html_imports_app(script=script, cwd=outside_cwd)


def test_main_reports_expired_listing_with_stable_error(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "fetch_html",
        lambda _url: (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(
                {
                    "props": {
                        "pageProps": {
                            "fromExpiredAdId": "123456789",
                            "searchResult": {"advertSummaryList": []},
                        }
                    }
                }
            )
            + "</script>"
        ),
    )

    result = module.main(["https://www.willhaben.at/iad/immobilien/d/expired-listing-123456789"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err == "willhaben_listing_expired\n"


def test_inspect_panorama_signal_accepts_wide_two_to_one_images(monkeypatch) -> None:
    module = _load_module()

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _Response(_jpeg_bytes(4000, 2000)))

    result = module.inspect_panorama_signal("https://cdn.example.com/pano.jpg", "")

    assert result["panorama_candidate"] is True
    assert result["panorama_reason"] == "wide_2_to_1"
    assert result["width"] == 4000
    assert result["height"] == 2000


def test_best_image_url_prefers_source_reference_over_main_thumbnail() -> None:
    module = _load_module()

    result = module.best_image_url(
        {
            "mainImageUrl": "https://cache.willhaben.at/mmo/1/2/3/4_hoved.jpg",
            "referenceImageUrl": "https://cache.willhaben.at/mmo/1/2/3/4.jpg",
            "thumbnailImageUrl": "https://cache.willhaben.at/mmo/1/2/3/4_thumb.jpg",
        }
    )

    assert result == "https://cache.willhaben.at/mmo/1/2/3/4.jpg"


def test_extract_media_surfaces_panorama_candidates_separately(monkeypatch) -> None:
    module = _load_module()

    responses = {
        "https://cdn.example.com/pano.jpg": _jpeg_bytes(4000, 2000),
        "https://cdn.example.com/flat.jpg": _jpeg_bytes(1600, 1200),
    }

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **kwargs: _Response(responses[str(url)]),
    )

    advert = {
        "advertImageList": {
            "advertImage": [
                {"mainImageUrl": "https://cdn.example.com/pano.jpg", "description": "Wohnzimmer 360 Panorama"},
                {"mainImageUrl": "https://cdn.example.com/flat.jpg", "description": "Kueche"},
            ]
        }
    }

    photos, floorplans, assets, panoramas = module.extract_media(advert)

    assert len(photos) == 2
    assert not floorplans
    assert len(assets) == 2
    assert [entry["url"] for entry in panoramas] == ["https://cdn.example.com/pano.jpg"]


def test_extract_media_promotes_plan_like_document_image_to_floorplan(monkeypatch) -> None:
    module = _load_module()

    def _document_bytes(*, line_plan: bool = False, colorful: bool = False) -> bytes:
        image = Image.new("RGB", (283, 400), color=(255, 255, 255))
        if line_plan:
            for x in range(35, 240):
                image.putpixel((x, 45), (70, 70, 70))
                image.putpixel((x, 260), (70, 70, 70))
            for y in range(45, 261):
                image.putpixel((35, y), (70, 70, 70))
                image.putpixel((239, y), (70, 70, 70))
            for x in range(110, 200):
                image.putpixel((x, 150), (90, 90, 90))
            for y in range(150, 260):
                image.putpixel((110, y), (90, 90, 90))
        if colorful:
            for x in range(20, 260):
                for y in range(20, 55):
                    image.putpixel((x, y), (70, 180, 80))
            for x in range(20, 260):
                for y in range(310, 340):
                    image.putpixel((x, y), (240, 210, 60))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return buffer.getvalue()

    responses = {
        "https://cdn.example.com/floorplan.jpg": _document_bytes(line_plan=True),
        "https://cdn.example.com/energy-cert.jpg": _document_bytes(colorful=True),
    }

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **kwargs: _Response(responses[str(url)]),
    )

    advert = {
        "advertImageList": {
            "advertImage": [
                {"mainImageUrl": "https://cdn.example.com/floorplan.jpg", "description": "Bild"},
                {"mainImageUrl": "https://cdn.example.com/energy-cert.jpg", "description": "Bild"},
            ]
        }
    }

    photos, floorplans, assets, panoramas = module.extract_media(advert)

    assert not panoramas
    assert [entry["url"] for entry in floorplans] == ["https://cdn.example.com/floorplan.jpg"]
    assert [entry["url"] for entry in photos] == ["https://cdn.example.com/energy-cert.jpg"]
    assert assets[0]["floorplan_candidate"] is True
    assert assets[0]["floorplan_reason"] == "plan_like_document_image"


def test_inspect_panorama_signal_does_not_treat_numeric_ids_as_360_markers(monkeypatch) -> None:
    module = _load_module()

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _Response(_jpeg_bytes(400, 292)))

    result = module.inspect_panorama_signal(
        "https://cache.willhaben.at/mmo/2/107/115/5412_-287382360_n_hoved.jpg",
        "Wohnbereich",
    )

    assert result["panorama_candidate"] is False
    assert result["panorama_reason"] == ""


def test_summarize_listing_promotes_external_virtual_tour_to_panorama_mode(monkeypatch) -> None:
    module = _load_module()

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _Response(_jpeg_bytes(1600, 1200)))
    advert = {
        "id": "listing-360-link-1",
        "uuid": "uuid-360-link-1",
        "description": "Gersthof flat with live 360 tour",
        "attributes": {
            "attribute": [
                {
                    "name": "INFOLINK/URL",
                    "values": [
                        "https://360.kalandra.at/view/portal/id/VVSCT",
                    ],
                }
            ]
        },
        "advertImageList": {
            "advertImage": [
                {"mainImageUrl": "https://cdn.example.com/flat.jpg", "description": "Wohnzimmer"},
            ]
        },
    }
    monkeypatch.setattr(
        module,
        "fetch_html",
        lambda url: (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"advertDetails": advert}}})
            + "</script>"
        ),
    )

    result = module.summarize_listing("https://www.willhaben.at/test-360-link")

    assert result["source_virtual_tour_url"] == "https://360.kalandra.at/view/portal/id/VVSCT"
    assert result["panorama_source"] == "feelestate_kalandra"
    assert result["property_facts_json"]["tour_media_mode"] == "panorama_360"


def test_build_variants_rewrites_layout_first_as_decision_reasoning() -> None:
    module = _load_module()

    variants = module.build_variants(
        title="Waehring family apartment",
        floorplan_count=1,
        photo_count=9,
        facts={
            "headline_hook": "Etagenheizung Gasheizung in Waehring",
            "rooms_label": "4 Zimmer",
            "area_label": "106 m²",
            "total_rent_eur": 2490.0,
            "availability": "ab sofort",
            "postal_name": "Wien, 18. Bezirk, Waehring",
            "address_lines": ["Wien, 18. Bezirk, Waehring"],
            "attribute_map": {
                "GENERAL_TEXT_ADVERT/Ausstattung": ["Balkon, Lift, Wohnkueche"],
                "HEIZUNGSART": ["Gasheizung"],
            },
        },
    )

    layout_first = next(entry for entry in variants if entry["variant_key"] == "layout_first")
    shortlist = next(entry for entry in variants if entry["variant_key"] == "shortlist_comparison")

    assert "good fit" in layout_first["creative_brief"]
    assert "bad fit" in layout_first["creative_brief"]
    assert "unknown" in layout_first["creative_brief"]
    assert "shortlist recommendation" in layout_first["creative_brief"]
    assert "Gasheizung" in layout_first["creative_brief"]
    assert "EUR 2.490" in layout_first["creative_brief"]
    assert "Decide whether to shortlist, book a viewing, or reject this listing." == layout_first["call_to_action"]
    assert "strongest reasons to rent or buy" in shortlist["creative_brief"]
    assert "unknowns" in shortlist["creative_brief"]
    assert shortlist["call_to_action"] == "Compare the tradeoffs, then shortlist, view, or reject."


def test_build_variants_uses_generic_decision_fallbacks_when_facts_are_sparse() -> None:
    module = _load_module()

    variants = module.build_variants(
        title="Sparse listing",
        floorplan_count=0,
        photo_count=3,
        facts={},
    )

    layout_first = next(entry for entry in variants if entry["variant_key"] == "layout_first")
    assert "the room count" in layout_first["creative_brief"]
    assert "the overall size" in layout_first["creative_brief"]
    assert "the total monthly burden" in layout_first["creative_brief"]
    assert "the micro-location" in layout_first["creative_brief"]


def test_decision_signals_surface_pros_cons_unknowns_and_recommendation() -> None:
    module = _load_module()

    result = module.decision_signals(
        {
            "rooms": 4.0,
            "rooms_label": "4 Zimmer",
            "area_sqm": 106.0,
            "area_label": "106 m²",
            "total_rent_eur": 2490.0,
            "availability": "ab sofort",
            "postal_name": "Wien, 18. Bezirk, Waehring",
            "address_lines": ["Wien, 18. Bezirk, Waehring"],
            "floorplan_count": 1,
            "tour_media_mode": "panorama_360",
            "livability_snapshot": {
                "nearest_pharmacy_m": 350,
                "nearest_supermarket_m": 280,
                "nearest_bakery_m": 180,
                "nearest_bicycle_parking_m": 90,
                "nearest_cycleway_m": 220,
                "nearest_transit_m": 220,
                "nearest_running_m": 650,
                "nearest_playground_m": 500,
                "nearest_school_m": 900,
            },
            "attribute_map": {
                "HEIZUNGSART": ["Gasheizung"],
                "ESTATE_PREFERENCE": ["Einbauküche", "Keller", "Garage", "Fahrstuhl"],
            },
        }
    )

    assert result["recommendation"] == "shortlist"
    assert any("floor plan" in entry for entry in result["good_fit_reasons"])
    assert any("360" in entry for entry in result["good_fit_reasons"])
    assert any("supermarket" in entry for entry in result["good_fit_reasons"])
    assert any("Bicycle parking" in entry for entry in result["good_fit_reasons"])
    assert any("Cycleway access" in entry for entry in result["good_fit_reasons"])
    assert any("Public transit" in entry for entry in result["good_fit_reasons"])
    assert any("Lift access" in entry for entry in result["good_fit_reasons"])
    assert any("Gasheizung" in entry for entry in result["bad_fit_reasons"])
    assert any("noise" in entry for entry in result["unknowns"])
    assert result["livability_snapshot"]["nearest_running_m"] == 650


def test_summarize_listing_includes_decision_summary(monkeypatch) -> None:
    module = _load_module()

    class _Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _Response(_jpeg_bytes(4000, 2000)))
    monkeypatch.setattr(
        module,
        "geocode_listing_location",
        lambda **kwargs: {"lat": 48.235, "lon": 16.318, "display_name": "Waehring"},
    )
    monkeypatch.setattr(
        module,
        "nearby_livability_snapshot",
        lambda lat, lon: {
            "nearest_pharmacy_m": 320,
            "nearest_supermarket_m": 190,
            "nearest_bakery_m": 220,
            "nearest_bicycle_parking_m": 120,
            "nearest_cycleway_m": 260,
            "nearest_playground_m": 640,
            "nearest_school_m": 980,
            "nearest_transit_m": 260,
            "nearest_running_m": 780,
        },
    )
    advert = {
        "id": "listing-decision-1",
        "uuid": "uuid-decision-1",
        "description": "Bright 4-room apartment",
        "attributes": {
            "attribute": [
                {"name": "NUMBER_OF_ROOMS", "values": ["4"]},
                {"name": "ESTATE_SIZE/LIVING_AREA", "values": ["106 m²"]},
                {"name": "RENTAL_PRICE/TOTAL_ENCUMBRANCE", "values": ["2490"]},
                {"name": "HEIZUNGSART", "values": ["Gasheizung"]},
                {"name": "AVAILABLE_NOW", "values": ["ab sofort"]},
                {"name": "ESTATE_PREFERENCE", "values": ["Einbauküche", "Keller", "Garage", "Fahrstuhl"]},
            ]
        },
        "advertImageList": {
            "advertImage": [
                {"mainImageUrl": "https://cdn.example.com/pano.jpg", "description": "Wohnzimmer 360 Panorama"},
            ]
        },
        "advertAttachmentList": {
            "advertAttachment": [
                {"url": "https://cdn.example.com/grundriss.pdf", "description": "Grundriss"},
            ]
        },
        "advertAddressDetails": {
            "addressLines": ["Wien, 18. Bezirk, Waehring"],
            "postalName": "Wien, 18. Bezirk, Waehring",
        },
    }
    monkeypatch.setattr(
        module,
        "fetch_html",
        lambda url: (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"advertDetails": advert}}})
            + "</script>"
        ),
    )

    result = module.summarize_listing("https://www.willhaben.at/test-decision-summary")
    decision_summary = result["property_facts_json"]["decision_summary"]

    assert decision_summary["recommendation"] == "shortlist"
    assert decision_summary["good_fit_reasons"]
    assert decision_summary["bad_fit_reasons"]
    assert decision_summary["unknowns"]
    assert decision_summary["livability_snapshot"]["nearest_supermarket_m"] == 190
    assert decision_summary["livability_snapshot"]["nearest_cycleway_m"] == 260
    assert result["property_facts_json"]["livability_snapshot"]["nearest_transit_m"] == 260


def test_nearby_livability_snapshot_falls_back_when_overpass_is_unavailable(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_overpass_json", lambda query: (_ for _ in ()).throw(RuntimeError("down")))

    fallback_map = {
        "pharmacy": 420,
        "supermarket": 180,
        "bakery": 210,
        "bicycle parking": 130,
        "playground": 630,
        "school": 910,
        "park": 560,
    }
    monkeypatch.setattr(module, "_nominatim_nearest_distance", lambda lat, lon, *, query: fallback_map.get(query))
    monkeypatch.setattr(module, "_nominatim_nearest_distance_any", lambda lat, lon, *, queries: 240)

    result = module.nearby_livability_snapshot(48.23245, 16.322895)

    assert result["nearest_pharmacy_m"] == 420
    assert result["nearest_supermarket_m"] == 180
    assert result["nearest_bicycle_parking_m"] == 130
    assert result["nearest_transit_m"] == 240
    assert result["nearest_playground_m"] == 630
    assert result["nearest_running_m"] == 560
    assert result["nearest_bakery_m"] is None
    assert result["nearest_school_m"] is None


def test_nearby_livability_snapshot_uses_cache_when_available(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    cache_file = tmp_path / "livability-cache.json"
    cache_key = module._livability_cache_key(48.23245, 16.322895)
    cache_file.write_text(
        json.dumps(
            {
                cache_key: {
                    "cached_at": 9999999999,
                    "snapshot": {
                        "nearest_pharmacy_m": 111,
                        "nearest_supermarket_m": 222,
                        "nearest_bicycle_parking_m": 77,
                        "nearest_cycleway_m": 88,
                        "nearest_playground_m": 333,
                        "nearest_running_m": 444,
                    },
                }
            }
        )
    )
    monkeypatch.setenv("EA_PROPERTY_LIVABILITY_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(module, "_overpass_json", lambda query: (_ for _ in ()).throw(RuntimeError("should_not_call")))
    monkeypatch.setattr(module, "_nominatim_nearest_distance", lambda lat, lon, *, query: (_ for _ in ()).throw(RuntimeError("should_not_call")))
    monkeypatch.setattr(module, "_nominatim_nearest_distance_any", lambda lat, lon, *, queries: (_ for _ in ()).throw(RuntimeError("should_not_call")))

    result = module.nearby_livability_snapshot(48.23245, 16.322895)

    assert result["nearest_pharmacy_m"] == 111
    assert result["nearest_supermarket_m"] == 222
    assert result["nearest_bicycle_parking_m"] == 77
    assert result["nearest_cycleway_m"] == 88
    assert result["nearest_playground_m"] == 333
    assert result["nearest_running_m"] == 444


def test_livability_cache_prunes_stale_and_limits_size(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("EA_PROPERTY_LIVABILITY_CACHE_TTL_SECONDS", "3600")
    monkeypatch.setenv("EA_PROPERTY_LIVABILITY_CACHE_MAX_ENTRIES", "2")
    current_time = 2_000_000.0
    monkeypatch.setattr(module.time, "time", lambda: current_time)

    payload = {
        "a": {"cached_at": current_time - 10, "snapshot": {"nearest_supermarket_m": 100}},
        "b": {"cached_at": current_time - 20, "snapshot": {"nearest_supermarket_m": 200}},
        "c": {"cached_at": current_time - 30, "snapshot": {"nearest_supermarket_m": 300}},
        "stale": {"cached_at": current_time - 7200, "snapshot": {"nearest_supermarket_m": 999}},
    }

    result = module._prune_livability_cache(payload)

    assert set(result.keys()) == {"a", "b"}
    assert "stale" not in result


def test_store_livability_snapshot_merges_existing_cache(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    cache_file = tmp_path / "livability-cache.json"
    monkeypatch.setenv("EA_PROPERTY_LIVABILITY_CACHE_FILE", str(cache_file))
    current_time = 2_000_000.0
    monkeypatch.setattr(module.time, "time", lambda: current_time)

    module._store_livability_snapshot(48.23245, 16.322895, {"nearest_supermarket_m": 111})
    module._store_livability_snapshot(48.21001, 16.35555, {"nearest_supermarket_m": 222})

    payload = json.loads(cache_file.read_text())
    assert module._livability_cache_key(48.23245, 16.322895) in payload
    assert module._livability_cache_key(48.21001, 16.35555) in payload
