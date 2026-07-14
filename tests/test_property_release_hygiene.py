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


def test_manifest_release_binding_accepts_only_named_metadata_descendants(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "git_commit_is_ancestor", lambda manifest, head: True)
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda manifest, head: [
            "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
            ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
        ],
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        "candidate-sha",
        "metadata-closeout-sha",
        "pulse-sha",
    )

    assert accepted is True
    assert descendant_paths == [
        "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
        ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ]


def test_manifest_release_binding_rejects_runtime_descendant(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "git_commit_is_ancestor", lambda manifest, head: True)
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda manifest, head: [
            "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
            "ea/app/api/routes/landing.py",
        ],
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        "candidate-sha",
        "changed-runtime-sha",
        "manifest-sha",
    )

    assert accepted is False
    assert "ea/app/api/routes/landing.py" in descendant_paths


def test_manifest_release_binding_rejects_non_ancestor(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "git_commit_is_ancestor", lambda manifest, head: False)

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        "unknown-sha",
        "current-sha",
        "parent-sha",
    )

    assert accepted is False
    assert descendant_paths == []
