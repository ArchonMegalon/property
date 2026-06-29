from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def test_3d_browser_gate_treats_csp_and_frame_blockers_as_failures() -> None:
    from scripts import propertyquarry_3d_browser_gate as gate

    blockers = gate._bad_console_messages(
        [
            {
                "type": "pageerror",
                "text": "WebAssembly.instantiate(): violates the following Content Security Policy directive",
            },
            {
                "type": "error",
                "text": "Refused to display 'https://discover.matterport.com/' in a frame because it set X-Frame-Options",
            },
            {"type": "warning", "text": "A harmless preload warning"},
        ]
    )

    assert len(blockers) == 2


def test_3d_browser_gate_requires_real_canvas_and_no_loading_state() -> None:
    from scripts import propertyquarry_3d_browser_gate as gate

    assert gate._provider_rendered_ok(
        "3dvista",
        {
            "provider_frame_url": "https://propertyquarry.com/tours/demo/3dvista/index.htm",
            "visible_canvas_count": 2,
            "frame_text": "",
        },
    )
    assert not gate._provider_rendered_ok(
        "3dvista",
        {
            "provider_frame_url": "https://propertyquarry.com/tours/demo/3dvista/index.htm",
            "visible_canvas_count": 2,
            "frame_text": "Loading virtual tour. Please wait...",
        },
    )
    assert not gate._provider_rendered_ok(
        "pano2vr",
        {
            "provider_frame_url": "https://propertyquarry.com/tours/demo/pano2vr/index.html",
            "visible_canvas_count": 0,
            "frame_text": "",
        },
    )


def test_3d_browser_gate_requires_matterport_embeddable_show_url() -> None:
    from scripts import propertyquarry_3d_browser_gate as gate

    assert gate._provider_rendered_ok(
        "matterport",
        {
            "provider_frame_url": "https://my.matterport.com/show/?m=uoRT7VqgY7E",
            "external_embedded_target_ok": True,
        },
    )
    assert not gate._provider_rendered_ok(
        "matterport",
        {
            "provider_frame_url": "https://discover.matterport.com/space/uoRT7VqgY7E",
            "external_embedded_target_ok": False,
        },
    )


def test_3d_browser_gate_ignores_noncritical_external_provider_asset_failures() -> None:
    from scripts import propertyquarry_3d_browser_gate as gate

    failures = gate._bad_request_failures(
        [
            {
                "url": "https://cdn-2.matterport.com/model/preview.jpg",
                "resource_type": "image",
                "failure": "net::ERR_BLOCKED_BY_ORB",
            },
            {
                "url": "http://propertyquarry.com:8097/app.js",
                "resource_type": "script",
                "failure": "net::ERR_FAILED",
            },
            {
                "url": "https://my.matterport.com/show/?m=demo",
                "resource_type": "document",
                "failure": "net::ERR_BLOCKED_BY_RESPONSE",
            },
        ],
        browser_base_url="http://propertyquarry.com:8097",
    )

    assert [row["resource_type"] for row in failures] == ["script", "document"]


def test_walkthrough_quality_gate_fails_without_room_coverage_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts import propertyquarry_walkthrough_quality_gate as gate

    slug = "demo"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "walkthrough.mp4").write_bytes(b"not-a-real-video")
    (bundle / "tour.json").write_text(
        json.dumps({"slug": slug, "video_relpath": "walkthrough.mp4"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_video_metadata", lambda _path: {"format": {"duration": "45"}})
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda _path: {"ok": True, "sampled_frame_count": 20, "delta_count": 19, "max_delta": 12.0},
    )

    receipt = gate.build_walkthrough_quality_receipt(
        tour_root=str(tmp_path),
        demo_slug=slug,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
    )

    assert receipt["status"] == "fail"
    failed = {row["name"] for row in receipt["checks"] if not row["ok"]}
    assert "walkthrough_room_coverage_receipt_present" in failed
    assert "walkthrough_room_coverage_complete" in failed


def test_walkthrough_quality_gate_accepts_complete_scene_segment_coverage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts import propertyquarry_walkthrough_quality_gate as gate

    slug = "demo"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "walkthrough.mp4").write_bytes(b"not-a-real-video")
    (bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "walkthrough.mp4",
                "walkthrough_coverage_proof": {
                    "status": "pass",
                    "segments_expected": ["entry", "living", "kitchen", "bathroom"],
                    "segments_visited": ["entry", "living", "kitchen", "bathroom"],
                    "coverage_segments": [
                        {"segment": "entry", "start": 0, "end": 8},
                        {"segment": "living", "start": 8, "end": 18},
                        {"segment": "kitchen", "start": 18, "end": 30},
                        {"segment": "bathroom", "start": 30, "end": 42},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_video_metadata", lambda _path: {"format": {"duration": "45"}})
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda _path: {"ok": True, "sampled_frame_count": 20, "delta_count": 19, "max_delta": 12.0},
    )

    receipt = gate.build_walkthrough_quality_receipt(
        tour_root=str(tmp_path),
        demo_slug=slug,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
    )

    assert receipt["status"] == "pass"


def test_walkthrough_quality_gate_reads_magicfit_sidecar_route_coverage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts import propertyquarry_walkthrough_quality_gate as gate

    slug = "demo"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "walkthrough.mp4").write_bytes(b"not-a-real-video")
    (bundle / "tour.magicfit.json").write_text(
        json.dumps(
            {
                "provider": "MagicFit",
                "route_labels": ["entry", "living", "kitchen"],
                "covered_route_labels": ["entry", "living", "kitchen"],
            }
        ),
        encoding="utf-8",
    )
    (bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "walkthrough.mp4",
                "video_sidecar_relpath": "tour.magicfit.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_video_metadata", lambda _path: {"format": {"duration": "45"}})
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda _path: {"ok": True, "sampled_frame_count": 20, "delta_count": 19, "max_delta": 12.0},
    )

    receipt = gate.build_walkthrough_quality_receipt(
        tour_root=str(tmp_path),
        demo_slug=slug,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
    )

    assert receipt["status"] == "pass"


def test_walkthrough_quality_gate_can_select_generated_reconstruction_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts import propertyquarry_walkthrough_quality_gate as gate

    slug = "demo"
    bundle = tmp_path / slug
    generated_dir = bundle / "generated-reconstruction"
    generated_dir.mkdir(parents=True)
    (bundle / "stale-magicfit.mp4").write_bytes(b"not-a-real-video")
    (generated_dir / "generated-walkthrough.mp4").write_bytes(b"not-a-real-video")
    (generated_dir / "generated-walkthrough.quality.json").write_text(
        json.dumps(
            {
                "route_labels": ["floorplan overview", "source photo 01"],
                "covered_route_labels": ["floorplan overview", "source photo 01"],
            }
        ),
        encoding="utf-8",
    )
    (bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "stale-magicfit.mp4",
                "generated_reconstruction": {
                    "provider": "propertyquarry_generated_reconstruction",
                    "verified_provider_capture": False,
                    "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
                    "walkthrough_sidecar_relpath": "generated-reconstruction/generated-walkthrough.quality.json",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_video_metadata", lambda _path: {"format": {"duration": "45"}})
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda _path: {"ok": True, "sampled_frame_count": 20, "delta_count": 19, "max_delta": 12.0},
    )

    receipt = gate.build_walkthrough_quality_receipt(
        tour_root=str(tmp_path),
        demo_slug=slug,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
    )

    assert receipt["status"] == "pass"
    assert receipt["walkthrough_candidate"] == "generated_reconstruction"
    assert receipt["video_relpath"] == "generated-reconstruction/generated-walkthrough.mp4"


def test_walkthrough_quality_gate_passes_with_complete_coverage_and_continuity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from scripts import propertyquarry_walkthrough_quality_gate as gate

    slug = "demo"
    bundle = tmp_path / slug
    bundle.mkdir()
    (bundle / "walkthrough.mp4").write_bytes(b"not-a-real-video")
    (bundle / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "video_relpath": "walkthrough.mp4",
                "walkthrough_coverage_proof": {
                    "status": "pass",
                    "rooms_expected": ["entry", "bathroom", "kitchen"],
                    "rooms_visited": ["entry", "bathroom", "kitchen"],
                    "room_segments": [
                        {"room": "entry", "start": 0, "end": 8},
                        {"room": "bathroom", "start": 8, "end": 18},
                        {"room": "kitchen", "start": 18, "end": 35},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_video_metadata", lambda _path: {"format": {"duration": "45"}})
    monkeypatch.setattr(
        gate,
        "_frame_delta_stats",
        lambda _path: {"ok": True, "sampled_frame_count": 20, "delta_count": 19, "max_delta": 12.0},
    )

    receipt = gate.build_walkthrough_quality_receipt(
        tour_root=str(tmp_path),
        demo_slug=slug,
        max_jump_delta=42.0,
        min_duration_seconds=30.0,
    )

    assert receipt["status"] == "pass"
    assert all(row["ok"] for row in receipt["checks"])


def test_map_preview_flagship_gate_rejects_harsh_raw_overlay(tmp_path: Path) -> None:
    from scripts import propertyquarry_map_preview_flagship_gate as gate

    image = Image.new("RGB", (640, 368), (238, 232, 222))
    draw = ImageDraw.Draw(image, "RGBA")
    for index in range(0, 640, 24):
        draw.line([(index, 0), (index + 180, 368)], fill=(185, 180, 172, 180), width=5)
    harsh = [(70, 52), (570, 36), (606, 290), (104, 326)]
    draw.polygon(harsh, fill=(215, 22, 28, 170))
    draw.line(harsh + [harsh[0]], fill=(112, 18, 24, 255), width=8)
    path = tmp_path / "harsh.png"
    image.save(path, format="PNG", compress_level=0)

    receipt = gate.build_map_preview_flagship_receipt(
        base_url="http://localhost",
        host_header="",
        api_token="",
        principal_id="",
        image_urls=[path.as_uri()],
        discover_routes=[],
        timeout_seconds=1.0,
        settle_seconds=0.0,
        min_preview_count=1,
    )

    assert receipt["status"] == "fail"
    failed_names = {
        check["name"]
        for result in receipt["preview_results"]
        for check in result["checks"]
        if not check["ok"]
    }
    assert "red_overlay_not_aggressive" in failed_names
    assert "border_noise_not_heavy" in failed_names


def test_map_preview_flagship_gate_accepts_calm_premium_thumbnail(tmp_path: Path) -> None:
    from scripts import propertyquarry_map_preview_flagship_gate as gate

    image = Image.new("RGB", (640, 368), (232, 226, 215))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.polygon([(0, 24), (210, 0), (640, 80), (640, 128), (260, 104), (0, 120)], fill=(194, 211, 188, 118))
    draw.polygon([(0, 280), (190, 248), (412, 286), (640, 264), (640, 368), (0, 368)], fill=(188, 208, 214, 112))
    for index in range(-160, 720, 90):
        draw.line([(index, 0), (index + 260, 368)], fill=(198, 190, 181, 140), width=9)
        draw.line([(index, 0), (index + 260, 368)], fill=(255, 253, 247, 110), width=3)
    for y in range(56, 360, 74):
        draw.line([(0, y), (640, y - 28)], fill=(202, 194, 184, 120), width=8)
    selected = [(190, 90), (455, 72), (524, 184), (450, 292), (216, 288), (128, 190)]
    draw.polygon(selected, fill=(218, 150, 150, 92))
    draw.line(selected + [selected[0]], fill=(255, 250, 242, 155), width=4)
    draw.line(selected + [selected[0]], fill=(132, 30, 36, 150), width=2)
    path = tmp_path / "calm.png"
    image.save(path, format="PNG", compress_level=0)

    receipt = gate.build_map_preview_flagship_receipt(
        base_url="http://localhost",
        host_header="",
        api_token="",
        principal_id="",
        image_urls=[path.as_uri()],
        discover_routes=[],
        timeout_seconds=1.0,
        settle_seconds=0.0,
        min_preview_count=1,
    )

    assert receipt["status"] == "pass"
    assert receipt["preview_results"][0]["metrics"]["strong_red_ratio"] < 0.20


def test_deploy_and_release_scripts_wire_3d_walkthrough_and_map_preview_as_exit_gates() -> None:
    deploy = (ROOT / "scripts" / "deploy_propertyquarry.sh").read_text(encoding="utf-8")
    release = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")

    assert "if ! PYTHONPATH=ea python3 scripts/propertyquarry_3d_browser_gate.py" in deploy
    assert "if ! PYTHONPATH=ea python3 scripts/propertyquarry_walkthrough_quality_gate.py" in deploy
    assert "if ! EA_API_TOKEN=\"${api_token}\" PYTHONPATH=ea python3 scripts/propertyquarry_map_preview_flagship_gate.py" in deploy
    assert "--map-preview-flagship-receipt _completion/smoke/property-live-map-preview-flagship-latest.json" in deploy
    assert "--browser-3d-gate-receipt _completion/smoke/property-live-3d-browser-gate-latest.json" in deploy
    assert "--walkthrough-quality-receipt _completion/smoke/property-live-walkthrough-quality-latest.json" in deploy
    assert "scripts/propertyquarry_3d_browser_gate.py" in release
    assert "scripts/propertyquarry_walkthrough_quality_gate.py" in release
    assert "scripts/propertyquarry_map_preview_flagship_gate.py" in release
    assert "--map-preview-flagship-receipt _completion/smoke/property-live-map-preview-flagship-release-gate.json" in release
    assert "--browser-3d-gate-receipt _completion/smoke/property-live-3d-browser-gate-release-gate.json" in release
    assert "--walkthrough-quality-receipt _completion/smoke/property-live-walkthrough-quality-release-gate.json" in release
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED" in deploy
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED_not_set" in deploy
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED" in release
    assert "PROPERTYQUARRY_GOLD_NOTIFICATION_ENABLED_not_set" in release
