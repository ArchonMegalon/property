from __future__ import annotations

from scripts import check_property_release_hygiene as release_hygiene


def test_release_hygiene_fails_when_tracked_worktree_is_dirty(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "release_manifest_runtime_sha", lambda: "ad4dd937")
    monkeypatch.setattr(release_hygiene, "git_head_sha", lambda: "ad4dd9372ae36543e1c36a8ed7a01092e2cc96c5")
    monkeypatch.setattr(release_hygiene, "git_head_parent_sha", lambda: "24ccb9c92331f446aa7f6f5e9f22213e6c42cd36")
    monkeypatch.setattr(release_hygiene, "_git_status_rows", lambda: [" M ea/app/product/service.py", "?? state/receipts/foo.json"])
    monkeypatch.setattr(release_hygiene, "tracked_paths", lambda: [])

    receipt = release_hygiene.build_release_hygiene_receipt()

    assert receipt["status"] == "fail"
    assert receipt["tracked_dirty_path_count"] == 1
    assert receipt["untracked_release_source_count"] == 0
    assert any("tracked worktree must be clean before release" in failure for failure in receipt["failures"])
    assert all("state/receipts/foo.json" not in failure for failure in receipt["failures"])


def test_release_hygiene_flags_untracked_release_sources_but_ignores_runtime_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "release_manifest_runtime_sha", lambda: "ad4dd937")
    monkeypatch.setattr(release_hygiene, "git_head_sha", lambda: "ad4dd9372ae36543e1c36a8ed7a01092e2cc96c5")
    monkeypatch.setattr(release_hygiene, "git_head_parent_sha", lambda: "24ccb9c92331f446aa7f6f5e9f22213e6c42cd36")
    monkeypatch.setattr(
        release_hygiene,
        "_git_status_rows",
        lambda: [
            "?? scripts/property_provider_matrix_stage_runner.py",
            "?? state/receipts/propertyquarry_gold_status_current.json",
            "?? _completion/property_gold_status/latest.json",
            "?? _tmp_live_shots/research.png",
        ],
    )
    monkeypatch.setattr(release_hygiene, "tracked_paths", lambda: [])

    receipt = release_hygiene.build_release_hygiene_receipt()

    assert receipt["status"] == "fail"
    assert receipt["tracked_dirty_path_count"] == 0
    assert receipt["untracked_release_source_count"] == 1
    assert any(
        "untracked release source files forbidden before release: scripts/property_provider_matrix_stage_runner.py" in failure
        for failure in receipt["failures"]
    )
