from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.propertyquarry_release_receipt_binding import ReleaseBindingError
from scripts.propertyquarry_release_receipt_binding import build_source_binding


SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
SOURCE_CASES = (
    Path("tests/test_propertyquarry_workspace_redesign.py"),
    Path("tests/e2e/test_propertyquarry_greenfield_browser.py"),
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(root: Path, path: Path | str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _initialize_repository(root: Path) -> tuple[list[dict[str, object]], str]:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Receipt Test")
    _git(root, "config", "user.email", "receipt@example.test")
    evidence_sources = [
        {"file": path.as_posix(), "cases": [f"case_{index}"]}
        for index, path in enumerate(SOURCE_CASES, start=1)
    ]
    _write(
        root,
        SEED,
        json.dumps({"browser_workflow_proof": {"evidence_sources": evidence_sources}}) + "\n",
    )
    for path in SOURCE_CASES:
        _write(root, path, f"# {path.name}\n")
    _write(root, "app.txt", "source-v1\n")
    return evidence_sources, _commit(root, "initial source")


def _binding(root: Path, evidence_sources: list[dict[str, object]]) -> dict[str, object]:
    return build_source_binding(
        root,
        seed_path=SEED,
        evidence_sources=evidence_sources,
    )


def test_source_binding_walks_consecutive_metadata_only_refresh_commits(tmp_path: Path) -> None:
    evidence_sources, initial = _initialize_repository(tmp_path)
    assert _binding(tmp_path, evidence_sources)["code_commit"] == initial

    _write(tmp_path, "app.txt", "source-v2\n")
    source_commit = _commit(tmp_path, "change source")
    assert _binding(tmp_path, evidence_sources)["code_commit"] == source_commit

    metadata_paths = (
        ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
        ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
        ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
        "docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",
    )
    for path in metadata_paths:
        _write(tmp_path, path, f"metadata for {source_commit}\n")
    metadata_commit = _commit(tmp_path, "refresh release metadata")
    assert _binding(tmp_path, evidence_sources)["code_commit"] == source_commit
    assert build_source_binding(
        tmp_path,
        seed_path=SEED,
        evidence_sources=evidence_sources,
        code_commit=metadata_commit,
    )["code_commit"] == metadata_commit

    _write(tmp_path, metadata_paths[1], "second metadata refresh\n")
    _commit(tmp_path, "refresh pulse metadata")
    assert _binding(tmp_path, evidence_sources)["code_commit"] == source_commit


def test_source_binding_does_not_hide_evidence_changes_in_metadata_commit(tmp_path: Path) -> None:
    evidence_sources, _initial = _initialize_repository(tmp_path)
    _write(tmp_path, SOURCE_CASES[0], "# changed evidence source\n")
    _write(
        tmp_path,
        ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
        "metadata refresh\n",
    )
    evidence_commit = _commit(tmp_path, "change evidence and metadata")

    binding = _binding(tmp_path, evidence_sources)
    assert binding["code_commit"] == evidence_commit
    assert binding["required_test_sources"][0]["git_blob_oid"] == _git(
        tmp_path,
        "rev-parse",
        f"{evidence_commit}:{SOURCE_CASES[0].as_posix()}",
    )


def test_source_binding_rejects_shallow_metadata_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    evidence_sources, source_commit = _initialize_repository(source)
    _write(
        source,
        ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
        f"metadata for {source_commit}\n",
    )
    _commit(source, "refresh release metadata")

    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "--depth", "1", source.resolve().as_uri(), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ReleaseBindingError, match="ancestry is shallow"):
        _binding(checkout, evidence_sources)
