from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_property_tour_controls import build_property_tour_control_receipt


def _write_tour(root: Path, slug: str, payload: dict[str, object], files: dict[str, str | bytes] | None = None) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    body = {"slug": slug, "title": slug, **payload}
    (bundle / "tour.json").write_text(json.dumps(body), encoding="utf-8")
    for relpath, content in (files or {}).items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def test_property_tour_control_verifier_accepts_private_receipt_matterport_without_url_leak(tmp_path: Path) -> None:
    _write_tour(tmp_path, "private-matterport", {})
    private_receipt = tmp_path / "private-matterport" / "tour.private.json"
    private_receipt.write_text(
        json.dumps({"matterport_url": "https://my.matterport.com/show/?m=PRIVATE123"}),
        encoding="utf-8",
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "pass"
    assert receipt["provider_counts"]["matterport"] == 1
    assert receipt["ready_provider_modes"] == ["matterport"]
    assert "PRIVATE123" not in json.dumps(receipt)


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
        {"walkthrough.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"},
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


def test_property_tour_control_verifier_rejects_magicfit_placeholder_video(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "magicfit-placeholder",
        {"video_provider": "magicfit", "video_relpath": "walkthrough.mp4"},
        {"walkthrough.mp4": "video"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["magicfit"] == 0
    assert receipt["tours"][0]["blocked_reason"] == "missing_verified_provider_control"


def test_property_tour_control_verifier_rejects_placeholder_local_3d_exports(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "placeholder-3dvista",
        {"three_d_vista_entry_relpath": "3dvista/index.html"},
        {"3dvista/index.html": "<html><body>Coming soon</body></html>"},
    )
    _write_tour(
        tmp_path,
        "placeholder-pano2vr",
        {"pano2vr_entry_relpath": "pano/index.html"},
        {"pano/index.html": "<html><body>Static placeholder</body></html>"},
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["provider_counts"]["3dvista"] == 0
    assert receipt["provider_counts"]["pano2vr"] == 0
    assert {tour["blocked_reason"] for tour in receipt["tours"]} == {"missing_verified_provider_control"}


def test_property_tour_control_verifier_blocks_when_no_verified_controls(tmp_path: Path) -> None:
    _write_tour(tmp_path, "fallback-tour", {"scene_strategy": "pure_360_cube"})

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    assert receipt["status"] == "blocked_missing_verified_controls"
    assert receipt["ready_provider_modes"] == []
    assert receipt["tours"][0]["status"] == "blocked_missing_verified_controls"
    assert receipt["tours"][0]["blocked_reason"] == "generated_cube_not_verified_3d"
    assert set(receipt["missing_provider_modes"]) == {"matterport", "3dvista", "pano2vr", "krpano", "magicfit"}


def test_property_tour_control_verifier_marks_photo_gallery_as_not_3d(tmp_path: Path) -> None:
    _write_tour(
        tmp_path,
        "gallery-tour",
        {
            "creation_mode": "hosted_photo_gallery_tour",
            "scene_strategy": "photo_gallery_hosted",
            "scenes": [{"asset_relpath": "photo-01.jpg", "role": "photo"}],
        },
        {"photo-01.jpg": "image"},
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
    assert receipt["tours"][0]["blocked_reason"] == "gallery_only_not_3d"
    assert receipt["tours"][0]["controls"] == []
    assert {row["provider"] for row in receipt["tours"][0]["missing_evidence"]} == {
        "matterport",
        "3dvista",
        "pano2vr",
        "krpano",
        "magicfit",
    }
    assert {row["provider"] for row in receipt["next_required_actions"]} == {
        "matterport",
        "3dvista",
        "pano2vr",
        "krpano",
        "magicfit",
    }


def test_property_tour_control_verifier_reports_actionable_missing_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRPANO_LICENSE_DOMAIN", raising=False)
    monkeypatch.delenv("KRPANO_LICENSE_KEY", raising=False)
    _write_tour(
        tmp_path,
        "partial-provider-tour",
        {
            "matterport_url": "https://tracker.example/show/?m=abc",
            "three_d_vista_entry_relpath": "3dvista/index.html",
            "pano2vr_entry_relpath": "pano/index.html",
            "video_provider": "stock",
            "video_relpath": "walkthrough.mp4",
            "walkable_scene": {"rooms": []},
        },
        {
            "3dvista/index.html": "<html><body>placeholder</body></html>",
            "pano/index.html": "<html><body>placeholder</body></html>",
            "walkthrough.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
        },
    )

    receipt = build_property_tour_control_receipt(tour_root=tmp_path)

    missing = {row["provider"]: row for row in receipt["tours"][0]["missing_evidence"]}
    assert missing["matterport"]["reason"] == "matterport_url_not_allowlisted_or_invalid"
    assert missing["3dvista"]["reason"] == "3dvista_entry_missing_or_not_verified"
    assert missing["pano2vr"]["reason"] == "pano2vr_entry_missing_or_not_verified"
    assert missing["krpano"]["reason"] == "missing_krpano_license_environment"
    assert missing["magicfit"]["reason"] == "walkthrough_provider_not_magicfit"
    assert "tracker.example" not in json.dumps(receipt)


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
