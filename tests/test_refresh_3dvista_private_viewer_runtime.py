from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.import_3dvista_export import _entry_has_3dvista_markers, _export_has_trial_branding


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_3dvista_private_viewer_runtime_replaces_runtime_and_removes_trial_markup(tmp_path: Path) -> None:
    slug = "private-viewer-refresh"
    public_root = tmp_path / "public_tours"
    bundle_dir = public_root / slug
    export_root = bundle_dir / "3dvista"
    lib_dir = export_root / "lib"
    lib_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "display_title": "Refresh target",
                "three_d_vista_entry_relpath": "3dvista/index.htm",
                "three_d_vista_export_root_relpath": "3dvista",
                "three_d_vista_import": {"source_project": "propertyquarry"},
                "three_d_vista_white_label_proof": {"source_project": "propertyquarry"},
            }
        ),
        encoding="utf-8",
    )
    (export_root / "index.htm").write_text(
        (
            "<!doctype html><html><head>"
            "<script src='lib/tdvplayer.js?v=1'></script>"
            "</head><body>"
            "<div>3DVista export shell</div>"
            "<div><span>created with the trial of 3DVista VT Pro</span></div>"
            "<div><a href='https://www.3dvista.com'>www.3DVista.com</a></div>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    (lib_dir / "tdvplayer.js").write_text("window.TDVPlayer = { version: 2345 };", encoding="utf-8")
    (lib_dir / "tdvplayer.json").write_text('{"version":{"major":0,"minor":2345}}', encoding="utf-8")

    local_store_dir = tmp_path / "local_store"
    local_store_dir.mkdir()
    (local_store_dir / "tdvplayer.js").write_text("window.TDVPlayer = { version: 2347 };", encoding="utf-8")
    (local_store_dir / "tdvplayer.json").write_text('{"version":{"major":0,"minor":2347}}', encoding="utf-8")

    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(public_root)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "refresh_3dvista_private_viewer_runtime.py"),
            "--slug",
            slug,
            "--local-store-dir",
            str(local_store_dir),
            "--vendor-delivered-date",
            "2026-06-26",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "refreshed"
    assert body["player_runtime_version_before"] == 2345
    assert body["player_runtime_version_after"] == 2347

    manifest = json.loads((bundle_dir / "tour.json").read_text(encoding="utf-8"))
    proof = manifest["three_d_vista_white_label_proof"]
    assert proof["private_viewer_verified"] is True
    assert proof["non_trial_export_verified"] is True
    assert proof["trial_branding_present"] is False
    assert proof["private_viewer_delivered_date"] == "2026-06-26"
    assert proof["player_runtime_version_before"] == 2345
    assert proof["player_runtime_version_after"] == 2347
    assert manifest["three_d_vista_import"]["source"] == "3dvista_private_viewer_runtime_refresh"

    refreshed_entry = (export_root / "index.htm").read_text(encoding="utf-8")
    assert "created with the trial" not in refreshed_entry.lower()
    assert "www.3dvista.com" not in refreshed_entry.lower()
    assert "https://www.3dvista.com" not in refreshed_entry.lower()
    assert "version: 2347" in (lib_dir / "tdvplayer.js").read_text(encoding="utf-8")
    assert '"minor":2347' in (lib_dir / "tdvplayer.json").read_text(encoding="utf-8")
    assert _entry_has_3dvista_markers(export_root, export_root / "index.htm") is True
    assert _export_has_trial_branding(export_root, export_root / "index.htm") is False


def test_refresh_3dvista_private_viewer_runtime_can_mirror_refreshed_bundle(tmp_path: Path) -> None:
    slug = "private-viewer-refresh-mirror"
    source_root = tmp_path / "source_public_tours"
    mirror_root = tmp_path / "runtime_volume"
    bundle_dir = source_root / slug
    export_root = bundle_dir / "3dvista"
    lib_dir = export_root / "lib"
    lib_dir.mkdir(parents=True)
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "display_title": "Mirror target",
                "three_d_vista_entry_relpath": "3dvista/index.htm",
                "three_d_vista_export_root_relpath": "3dvista",
            }
        ),
        encoding="utf-8",
    )
    (export_root / "index.htm").write_text(
        (
            "<!doctype html><html><head>"
            "<script src='lib/tdvplayer.js?v=1'></script>"
            "</head><body>"
            "<div>3DVista export shell</div>"
            "<div><span>created with the trial of 3DVista VT Pro</span></div>"
            "<div><a href='https://www.3dvista.com'>www.3DVista.com</a></div>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    (lib_dir / "tdvplayer.js").write_text("window.TDVPlayer = { version: 2345 };", encoding="utf-8")
    (lib_dir / "tdvplayer.json").write_text('{"version":{"major":0,"minor":2345}}', encoding="utf-8")

    stale_mirror_dir = mirror_root / slug / "3dvista" / "lib"
    stale_mirror_dir.mkdir(parents=True)
    ((mirror_root / slug) / "tour.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    ((mirror_root / slug) / "3dvista" / "index.htm").write_text(
        "<div>created with the trial of 3DVista VT Pro</div>",
        encoding="utf-8",
    )
    (stale_mirror_dir / "tdvplayer.js").write_text("window.TDVPlayer = { version: 1000 };", encoding="utf-8")
    (stale_mirror_dir / "tdvplayer.json").write_text('{"version":{"major":0,"minor":1000}}', encoding="utf-8")

    local_store_dir = tmp_path / "local_store"
    local_store_dir.mkdir()
    (local_store_dir / "tdvplayer.js").write_text("window.TDVPlayer = { version: 2347 };", encoding="utf-8")
    (local_store_dir / "tdvplayer.json").write_text('{"version":{"major":0,"minor":2347}}', encoding="utf-8")

    env = dict(os.environ)
    env["EA_PUBLIC_TOUR_DIR"] = str(source_root)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "refresh_3dvista_private_viewer_runtime.py"),
            "--slug",
            slug,
            "--local-store-dir",
            str(local_store_dir),
            "--mirror-target-root",
            str(mirror_root),
            "--vendor-delivered-date",
            "2026-06-26",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert str(mirror_root.resolve()) in body["mirrored_roots"]
    assert body["mirrored_file_counts"][str(mirror_root.resolve())] >= 4

    mirrored_bundle_dir = mirror_root / slug
    mirrored_manifest = json.loads((mirrored_bundle_dir / "tour.json").read_text(encoding="utf-8"))
    assert mirrored_manifest["three_d_vista_white_label_proof"]["private_viewer_verified"] is True
    assert mirrored_manifest["three_d_vista_white_label_proof"]["trial_branding_present"] is False
    assert '"minor":2347' in (mirrored_bundle_dir / "3dvista" / "lib" / "tdvplayer.json").read_text(encoding="utf-8")
    mirrored_entry = (mirrored_bundle_dir / "3dvista" / "index.htm").read_text(encoding="utf-8")
    assert "created with the trial" not in mirrored_entry.lower()
    assert _entry_has_3dvista_markers(mirrored_bundle_dir / "3dvista", mirrored_bundle_dir / "3dvista" / "index.htm") is True
    assert _export_has_trial_branding(mirrored_bundle_dir / "3dvista", mirrored_bundle_dir / "3dvista" / "index.htm") is False
