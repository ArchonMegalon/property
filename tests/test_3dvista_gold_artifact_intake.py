from __future__ import annotations

from pathlib import Path

from scripts import intake_3dvista_gold_artifact as intake


def test_3dvista_gold_intake_reports_waiting_when_no_importable_export(monkeypatch, tmp_path: Path) -> None:
    def fake_run_command(cmd: list[str], *, timeout_seconds: int) -> dict[str, object]:
        assert "discover_property_tour_exports.py" in " ".join(cmd)
        return {"cmd": cmd, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}

    def fake_load_json(path: Path) -> dict[str, object]:
        return {
            "status": "blocked_no_verified_exports",
            "import_count": 0,
            "rejected_count": 1,
            "rejected": [
                {
                    "provider": "3dvista",
                    "slug": "demo",
                    "reason": "3dvista_trial_branding_present",
                    "action": "replace the trial-branded 3DVista export with a licensed 3DVista VT Pro export",
                    "drop_path": "/drop/demo/3dvista",
                }
            ],
            "import_manifest": {"imports": []},
        }

    monkeypatch.setattr(intake, "_run_command", fake_run_command)
    monkeypatch.setattr(intake, "_load_json", fake_load_json)

    receipt = intake.build_3dvista_intake_receipt(
        drop_dir=tmp_path / "incoming",
        public_tour_dir=tmp_path / "public",
        slug="demo",
        completion_dir=tmp_path / "completion",
    )

    assert receipt["status"] == "blocked_waiting_for_artifact"
    assert receipt["total_import_count"] == 0
    assert receipt["3dvista_import_count"] == 0
    assert receipt["rejected_3dvista_reasons"] == [
        {
            "slug": "demo",
            "reason": "3dvista_trial_branding_present",
            "action": "replace the trial-branded 3DVista export with a licensed 3DVista VT Pro export",
            "drop_path": "/drop/demo/3dvista",
        }
    ]
    assert "licensed non-trial 3DVista export" in receipt["next_action"]


def test_3dvista_gold_intake_dry_run_stops_before_import_when_row_is_ready(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run_command(cmd: list[str], *, timeout_seconds: int) -> dict[str, object]:
        calls.append(cmd)
        return {"cmd": cmd, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}

    def fake_load_json(path: Path) -> dict[str, object]:
        return {
            "status": "ready",
            "import_count": 1,
            "rejected_count": 0,
            "rejected": [],
            "import_manifest": {
                "imports": [
                    {
                        "provider": "3dvista",
                        "slug": "demo",
                        "export_dir": str(tmp_path / "incoming" / "demo" / "3dvista"),
                    }
                ]
            },
        }

    monkeypatch.setattr(intake, "_run_command", fake_run_command)
    monkeypatch.setattr(intake, "_load_json", fake_load_json)

    receipt = intake.build_3dvista_intake_receipt(
        drop_dir=tmp_path / "incoming",
        public_tour_dir=tmp_path / "public",
        slug="demo",
        completion_dir=tmp_path / "completion",
        dry_run=True,
    )

    assert receipt["status"] == "ready_to_import"
    assert receipt["total_import_count"] == 1
    assert receipt["3dvista_import_count"] == 1
    assert receipt["next_action"] == "Rerun without --dry-run to import verified 3DVista rows."
    assert len(calls) == 1
    assert "discover_property_tour_exports.py" in " ".join(calls[0])
