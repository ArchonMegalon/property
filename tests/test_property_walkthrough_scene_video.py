from __future__ import annotations

import json
from types import SimpleNamespace

from app.product import service as product_service
from app.product.service import ProductService


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


def test_run_scene_video_skill_uses_principal_context_and_scrubs_payload_principal() -> None:
    captured_request = None

    class _FakeOrchestrator:
        def execute_task_artifact(self, request):
            nonlocal captured_request
            captured_request = request
            return SimpleNamespace(
                structured_output_json={
                    "deliverable_type": "scene_video_packet",
                    "provider_key": "magicfit",
                    "render_status": "completed",
                    "video_url": "https://cdn.example/property/walkthrough.mp4",
                },
                content="",
            )

    service = ProductService(
        SimpleNamespace(
            orchestrator=_FakeOrchestrator(),
            preference_profiles=SimpleNamespace(),
        )
    )

    result = service._run_scene_video_skill(
        title="Sample Flat",
        actor="property-worker",
        provider_key="magicfit",
        task_principal_id="cf-email:operator@example.test",
        input_json={
            "principal_id": "should-not-leak",
            "context_kind": "property_walkthrough",
            "tour_url": "/tours/sample-flat",
        },
    )

    assert result["provider_key"] == "magicfit"
    assert captured_request.principal_id == "cf-email:operator@example.test"
    assert captured_request.input_json["provider_key"] == "magicfit"
    assert "principal_id" not in captured_request.input_json


def test_hosted_property_visual_progress_snapshot_roundtrip(tmp_path, monkeypatch) -> None:
    public_dir = tmp_path / "public_tours"
    bundle_dir = public_dir / "sample-flat"
    bundle_dir.mkdir(parents=True)
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(public_dir))

    product_service._write_hosted_property_visual_progress(
        tour_url="/tours/sample-flat",
        request_kind="flythrough",
        status="processing",
        progress_pct=44,
        detail="Rendering walkthrough segment 2 of 4.",
        reason="",
        provider_key="magicfit",
        step_index=2,
        step_total=4,
        updated_at="2026-06-29T10:15:00+00:00",
    )

    snapshot = product_service._hosted_property_visual_progress_snapshot(
        "/tours/sample-flat",
        request_kind="flythrough",
    )

    assert snapshot["status"] == "processing"
    assert snapshot["progress_pct"] == 44
    assert snapshot["detail"] == "Rendering walkthrough segment 2 of 4."
    assert snapshot["provider_key"] == "magicfit"
    assert snapshot["step_index"] == 2
    assert snapshot["step_total"] == 4
    assert product_service._hosted_property_visual_progress_stage_label(snapshot) == "segment 2 of 4"
