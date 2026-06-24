from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_property_tour_controls import build_property_tour_control_receipt


def _write_tour(root: Path, slug: str, payload: dict[str, object], files: dict[str, str] | None = None) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    body = {"slug": slug, "title": slug, **payload}
    (bundle / "tour.json").write_text(json.dumps(body), encoding="utf-8")
    for relpath, content in (files or {}).items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_property_tour_control_verifier_reports_all_verified_provider_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KRPANO_LICENSE_DOMAIN", "propertyquarry.com")
    monkeypatch.setenv("KRPANO_LICENSE_KEY", "licensed")
    _write_tour(tmp_path, "matterport-tour", {"matterport_url": "https://my.matterport.com/show/?m=abc"})
    _write_tour(
        tmp_path,
        "3dvista-tour",
        {"three_d_vista_entry_relpath": "3dvista/index.html"},
        {"3dvista/index.html": "<html>3DVista</html>"},
    )
    _write_tour(
        tmp_path,
        "pano2vr-tour",
        {"pano2vr_entry_relpath": "pano/index.html"},
        {"pano/index.html": "<html>Pano2VR</html>"},
    )
    _write_tour(tmp_path, "krpano-tour", {"walkable_scene": {"rooms": []}})
    _write_tour(
        tmp_path,
        "magicfit-tour",
        {"video_provider": "magicfit", "video_relpath": "walkthrough.mp4"},
        {"walkthrough.mp4": "video"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"] == {
        "matterport": 1,
        "3dvista": 1,
        "pano2vr": 1,
        "krpano": 1,
        "magicfit": 1,
    }
    assert receipt["missing_provider_modes"] == []
    assert all("matterport.com/show" not in json.dumps(tour) for tour in receipt["tours"])


def test_property_tour_control_verifier_blocks_when_no_verified_controls(tmp_path: Path) -> None:
    _write_tour(tmp_path, "fallback-tour", {"scene_strategy": "pure_360_cube"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["ready_provider_modes"] == []
    assert receipt["tours"][0]["status"] == "blocked_missing_verified_controls"
    assert set(receipt["missing_provider_modes"]) == {"matterport", "3dvista", "pano2vr", "krpano", "magicfit"}


def test_property_tour_control_verifier_does_not_treat_private_or_missing_assets_as_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("KRPANO_LICENSE_DOMAIN", raising=False)
    monkeypatch.delenv("KRPANO_LICENSE_KEY", raising=False)
    _write_tour(
        tmp_path,
        "unsafe-tour",
        {
            "matterport_url": "https://tracker.example/show/?m=abc",
            "three_d_vista_entry_relpath": "../private/index.html",
            "pano2vr_entry_relpath": "missing/index.html",
            "video_provider": "magicfit",
            "video_relpath": "private.txt",
            "walkable_scene": {"rooms": []},
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"] == {
        "matterport": 0,
        "3dvista": 0,
        "pano2vr": 0,
        "krpano": 0,
        "magicfit": 0,
    }
