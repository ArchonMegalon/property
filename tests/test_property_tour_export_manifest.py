from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.materialize_property_tour_export_manifest import build_export_manifest


ROOT = Path(__file__).resolve().parents[1]


def _write_base_tour(root: Path, slug: str) -> None:
    bundle = root / slug
    bundle.mkdir(parents=True)
    (bundle / "tour.json").write_text(json.dumps({"slug": slug, "display_title": slug}), encoding="utf-8")


def test_materialize_property_tour_export_manifest_writes_operator_drop_paths(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    _write_base_tour(tour_root, "needs-exports")

    manifest = build_export_manifest(tour_root=tour_root, incoming_root=incoming_root, limit_per_provider=1)

    assert manifest["status"] == "ready_for_exports"
    assert manifest["tour_root"] == str(tour_root.resolve())
    assert manifest["incoming_root"] == str(incoming_root.resolve())
    assert set(manifest["providers"]) == {"3dvista", "pano2vr"}
    assert manifest["import_count"] == 2
    imports = {(row["provider"], row["slug"]): row for row in manifest["imports"]}
    assert imports[("3dvista", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "3dvista")
    assert imports[("pano2vr", "needs-exports")]["export_dir"] == str(incoming_root.resolve() / "needs-exports" / "pano2vr")
    assert "import_property_tour_exports.py" in manifest["next_command"]


def test_materialize_property_tour_export_manifest_cli_writes_receipt(tmp_path: Path) -> None:
    tour_root = tmp_path / "public_tours"
    incoming_root = tmp_path / "incoming"
    output = tmp_path / "manifest.json"
    _write_base_tour(tour_root, "cli-needs-exports")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_property_tour_export_manifest.py"),
            "--tour-root",
            str(tour_root),
            "--incoming-root",
            str(incoming_root),
            "--write",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["status"] == "ready_for_exports"
    assert manifest["import_count"] == 2
    assert "cli-needs-exports" in result.stdout
