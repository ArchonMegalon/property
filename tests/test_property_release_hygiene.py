from __future__ import annotations

import subprocess

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
            ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
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
        ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
        ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
        ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ]


def test_release_manifest_runtime_sha_reads_canonical_json_authority(monkeypatch) -> None:
    expected = "a" * 40
    observed_paths = []

    def fake_load(path):
        observed_paths.append(path)
        return {"release_commit_sha": expected}

    monkeypatch.setattr(release_hygiene, "load_release_manifest", fake_load)

    assert release_hygiene.release_manifest_runtime_sha() == expected
    assert observed_paths == [
        release_hygiene.ROOT / "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"
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


def test_manifest_release_binding_accepts_safe_synthetic_merge_parent(monkeypatch) -> None:
    manifest_sha = "runtime-sha"
    head_sha = "synthetic-merge-sha"
    base_parent_sha = "base-parent-sha"
    feature_parent_sha = "feature-parent-sha"

    monkeypatch.setattr(
        release_hygiene,
        "git_commit_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant)
        in {
            (manifest_sha, head_sha),
            (manifest_sha, feature_parent_sha),
        },
    )
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda ancestor, descendant: ["docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"],
    )
    monkeypatch.setattr(
        release_hygiene,
        "tree_paths_between",
        lambda parent, head: [] if parent == feature_parent_sha and head == head_sha else None,
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        manifest_sha,
        head_sha,
        [base_parent_sha, feature_parent_sha],
    )
    detailed_accepted, detailed_paths, binding_parent = (
        release_hygiene._manifest_release_binding(
            manifest_sha,
            head_sha,
            [base_parent_sha, feature_parent_sha],
        )
    )

    assert accepted is True
    assert descendant_paths == ["docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"]
    assert (detailed_accepted, detailed_paths) == (accepted, descendant_paths)
    assert binding_parent == feature_parent_sha


def test_release_hygiene_receipt_reports_safe_synthetic_merge_parent(monkeypatch) -> None:
    manifest_sha = "a" * 40
    head_sha = "b" * 40
    base_parent_sha = "c" * 40
    feature_parent_sha = "d" * 40
    monkeypatch.setattr(release_hygiene, "release_manifest_runtime_sha", lambda: manifest_sha)
    monkeypatch.setattr(release_hygiene, "git_head_sha", lambda: head_sha)
    monkeypatch.setattr(
        release_hygiene,
        "git_commit_parent_shas",
        lambda commit: [base_parent_sha, feature_parent_sha],
    )
    monkeypatch.setattr(
        release_hygiene,
        "git_commit_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant)
        in {
            (manifest_sha, head_sha),
            (manifest_sha, feature_parent_sha),
        },
    )
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda ancestor, descendant: list(release_hygiene.RELEASE_METADATA_DESCENDANT_PATHS),
    )
    monkeypatch.setattr(release_hygiene, "tree_paths_between", lambda parent, head: [])
    monkeypatch.setattr(release_hygiene, "_git_status_rows", lambda: [])
    monkeypatch.setattr(release_hygiene, "tracked_paths", lambda: [])

    receipt = release_hygiene.build_release_hygiene_receipt()

    assert receipt["status"] == "pass"
    assert receipt["parent_commit"] == feature_parent_sha
    assert "parent_commits" not in receipt
    assert set(receipt) == {
        "schema",
        "generated_at",
        "status",
        "required_checks",
        "failure_count",
        "failures",
        "manifest_runtime_commit",
        "head_commit",
        "parent_commit",
        "manifest_descendant_paths",
        "manifest_metadata_only_ancestor",
        "tracked_dirty_path_count",
        "untracked_release_source_count",
        "note",
    }


def test_manifest_release_binding_rejects_merge_parent_with_source_delta_from_manifest(monkeypatch) -> None:
    manifest_sha = "runtime-sha"
    head_sha = "synthetic-merge-sha"
    base_parent_sha = "base-parent-sha"
    unrelated_parent_sha = "unrelated-parent-sha"

    monkeypatch.setattr(
        release_hygiene,
        "git_commit_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant)
        in {
            (manifest_sha, head_sha),
            (manifest_sha, base_parent_sha),
        },
    )
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda ancestor, descendant: ["ea/app/api/routes/landing.py"],
    )
    monkeypatch.setattr(
        release_hygiene,
        "tree_paths_between",
        lambda parent, head: (_ for _ in ()).throw(AssertionError("unsafe parent tree must not be trusted")),
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        manifest_sha,
        head_sha,
        [base_parent_sha, unrelated_parent_sha],
    )

    assert accepted is False
    assert descendant_paths == ["ea/app/api/routes/landing.py"]


def test_manifest_release_binding_rejects_merge_resolution_source_delta(monkeypatch) -> None:
    manifest_sha = "runtime-sha"
    head_sha = "synthetic-merge-sha"
    feature_parent_sha = "feature-parent-sha"
    unrelated_parent_sha = "unrelated-parent-sha"

    monkeypatch.setattr(
        release_hygiene,
        "git_commit_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant)
        in {
            (manifest_sha, head_sha),
            (manifest_sha, feature_parent_sha),
        },
    )
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda ancestor, descendant: ["docs/PROPERTYQUARRY_RELEASE_MANIFEST.md"],
    )
    monkeypatch.setattr(
        release_hygiene,
        "tree_paths_between",
        lambda parent, head: ["ea/app/api/routes/landing.py"],
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        manifest_sha,
        head_sha,
        [feature_parent_sha, unrelated_parent_sha],
    )

    assert accepted is False
    assert descendant_paths == [
        "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
        "ea/app/api/routes/landing.py",
    ]


def test_manifest_release_binding_preserves_ordinary_commit_history_audit(monkeypatch) -> None:
    monkeypatch.setattr(release_hygiene, "git_commit_is_ancestor", lambda manifest, head: True)
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda manifest, head: [
            "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
            "ea/app/api/routes/landing.py",
        ],
    )
    monkeypatch.setattr(
        release_hygiene,
        "tree_paths_between",
        lambda parent, head: (_ for _ in ()).throw(AssertionError("ordinary history must use commit audit")),
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        "runtime-sha",
        "ordinary-head-sha",
        ["ordinary-parent-sha"],
    )

    assert accepted is False
    assert descendant_paths == [
        "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
        "ea/app/api/routes/landing.py",
    ]


def test_committed_paths_since_keeps_reverted_runtime_change_visible(monkeypatch, tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "release-hygiene@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Release Hygiene"], cwd=tmp_path, check=True)
    runtime_path = tmp_path / "ea/app/api/routes/landing.py"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", runtime_path.relative_to(tmp_path).as_posix()], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=tmp_path, check=True)
    baseline_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    runtime_path.write_text("temporary runtime change\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "change runtime"], cwd=tmp_path, check=True)
    runtime_path.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "revert runtime"], cwd=tmp_path, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.setattr(release_hygiene, "ROOT", tmp_path)

    descendant_paths = release_hygiene.committed_paths_since(baseline_sha, head_sha)

    assert descendant_paths == ["ea/app/api/routes/landing.py"]


def test_committed_paths_since_does_not_split_newline_filename(monkeypatch) -> None:
    class GitResult:
        returncode = 0
        stdout = (
            b"docs/PROPERTYQUARRY_RELEASE_MANIFEST.md\n"
            b".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json\0"
        )

    monkeypatch.setattr(release_hygiene.subprocess, "run", lambda *args, **kwargs: GitResult())

    descendant_paths = release_hygiene.committed_paths_since("candidate-sha", "head-sha")

    assert descendant_paths == [
        "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md\n"
        ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
    ]
    assert descendant_paths[0] not in release_hygiene.RELEASE_METADATA_DESCENDANT_PATHS


def test_manifest_release_binding_audits_direct_parent_commit_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        release_hygiene,
        "git_commit_is_ancestor",
        lambda manifest, head: True,
    )
    monkeypatch.setattr(
        release_hygiene,
        "committed_paths_since",
        lambda manifest, head: ["ea/app/api/routes/landing.py"],
    )

    accepted, descendant_paths = release_hygiene.manifest_release_binding(
        "runtime-sha",
        "envelope-sha",
        "runtime-sha",
    )

    assert accepted is False
    assert descendant_paths == ["ea/app/api/routes/landing.py"]
