from __future__ import annotations

import json

from app.product import service as product_service


def test_property_walkthrough_scene_video_context_collects_verified_controls_and_route_labels(tmp_path, monkeypatch) -> None:
    public_dir = tmp_path / "public_tours"
    bundle_dir = public_dir / "sample-flat"
    export_dir = bundle_dir / "3dvista"
    export_dir.mkdir(parents=True)
    (export_dir / "index.htm").write_text("<script src='lib/tdvplayer.js'></script>", encoding="utf-8")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "title": "Sample Flat",
                "display_title": "Sample Flat",
                "control_mode": "3dvista",
                "scene_strategy": "walkable_3d",
                "scene_count": 3,
                "source_virtual_tour_url": "https://example.3dvista.com/tour/sample-flat",
                "three_d_vista_entry_relpath": "3dvista/index.htm",
                "walkable_scene": {
                    "route": [
                        {"label": "Entry"},
                        {"label": "Kitchen"},
                        {"label": "Balcony"},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_dir))

    context = product_service._property_walkthrough_scene_video_context("/tours/sample-flat")

    assert context["tour_url"] == "/tours/sample-flat"
    assert context["verified_provider"] == "3dvista"
    assert context["verified_open_url"].endswith("/tours/sample-flat/control/3dvista")
    assert context["control_urls"]["3dvista"].endswith("/tours/sample-flat/control/3dvista")
    assert context["provider_exports"] == ["3dvista"]
    assert context["route_labels"] == ["Entry", "Kitchen", "Balcony"]


def test_render_property_flythrough_does_not_silent_fallback_from_magicfit(monkeypatch) -> None:
    monkeypatch.setattr(
        product_service,
        "_render_magicfit_property_flythrough_into_hosted_tour",
        lambda **kwargs: {
            "status": "failed",
            "reason": "magicfit_segment_render_failed",
            "provider_key": "magicfit",
        },
    )
    monkeypatch.setattr(
        product_service,
        "_render_onemin_property_flythrough_into_hosted_tour",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected_onemin_fallback")),
    )

    result = product_service._render_property_flythrough_into_hosted_tour(
        tour_url="/tours/sample-flat",
        title="Sample Flat",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "magicfit_segment_render_failed"
    assert result["media_route_provider_key"] == "magicfit"
    assert "media_route_fallback_provider_key" not in result
