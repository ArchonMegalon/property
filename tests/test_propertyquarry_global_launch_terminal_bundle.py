from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import build_propertyquarry_global_launch_terminal_bundle as builder
from scripts import propertyquarry_global_launch_terminal as terminal


def test_production_capacity_v2_schema_is_closed_and_packaged() -> None:
    schema_path = terminal.CAPACITY_RECEIPT_CONTRACT_PATH
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema"]["const"] == terminal.CAPACITY_RECEIPT_SCHEMA
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schema",
        "contract_sha256",
        "status",
        "evidence_level",
        "deployment_id",
        "observed_at",
        "release_identity",
        "measurement_window",
        "summary",
        "resources",
    }
    assert not {"capacity_ready", "headroom_verified", "limits_verified"}.intersection(
        schema["properties"]
    )
    resource_schema = schema["$defs"]["resource"]
    assert resource_schema["additionalProperties"] is False
    assert len(resource_schema["allOf"]) == len(terminal.CAPACITY_RESOURCE_KINDS)
    assert len(schema["properties"]["resources"]["allOf"]) == len(
        terminal.CAPACITY_RESOURCE_KINDS
    )
    assert (
        terminal.CAPACITY_RECEIPT_CONTRACT_BUNDLE_RELATIVE_PATH
        in terminal.MANDATORY_BUNDLE_RELATIVE_PATHS
    )
    assert builder.CANONICAL_GOLD_STATIC_SOURCES[
        Path(terminal.CAPACITY_RECEIPT_CONTRACT_BUNDLE_RELATIVE_PATH)
    ] == schema_path


def test_bundle_builder_materializes_reproducible_pinned_tree_without_installing(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "bundle-one"
    second_root = tmp_path / "bundle-two"
    installed_before = terminal.INSTALLED_ENTRYPOINT.exists()

    first = builder.build_bundle(first_root)
    second = builder.build_bundle(second_root)

    assert first == second
    assert first["schema"] == terminal.INSTALLED_BUNDLE_SCHEMA
    assert first["install_root"] == str(terminal.INSTALLED_ENTRYPOINT.parent)
    assert first["python"]["path"] == str(terminal.INSTALLED_PYTHON_PATH)
    assert first["artifact_set_sha256"] == builder.artifact_set_sha256(
        first["files"]
    )
    assert terminal.MANDATORY_BUNDLE_RELATIVE_PATHS.issubset(first["files"])
    bundled_monitoring_and_overlay = {
        str(relative)
        for relative in builder._source_map()
        if str(relative).startswith("runtime/config/monitoring/")
        or str(relative)
        == "runtime/docs/PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json"
    }
    assert bundled_monitoring_and_overlay
    assert bundled_monitoring_and_overlay.issubset(
        terminal.MANDATORY_BUNDLE_RELATIVE_PATHS
    )
    assert terminal.INSTALLED_ENTRYPOINT.exists() is installed_before

    for relative, expected_sha256 in first["files"].items():
        path = first_root / relative
        assert path.is_file()
        assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
        assert not stat.S_IMODE(path.stat().st_mode) & 0o022
    assert stat.S_IMODE(
        (first_root / builder.ENTRYPOINT_RELATIVE).stat().st_mode
    ) == 0o555
    assert stat.S_IMODE(first_root.stat().st_mode) == 0o555

    for relative, source in builder.CANONICAL_GOLD_STATIC_SOURCES.items():
        installed_relative = str(relative)
        assert installed_relative in first["files"]
        assert (
            "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
            == first["files"][installed_relative]
        )

    manifest_path = first_root / builder.BUNDLE_MANIFEST_RELATIVE
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == first
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o444


def test_materialized_entrypoint_keeps_invalid_cli_structured_and_silent_on_stderr(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    builder.build_bundle(bundle_root)
    entrypoint = bundle_root / builder.ENTRYPOINT_RELATIVE

    completed = subprocess.run(
        [str(entrypoint), "--manifest"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "schema": terminal.RESULT_SCHEMA,
        "status": "blocked",
        "phase": "manifest_validation",
        "gold_invoked": False,
        "blockers": [
            {"code": "terminal_arguments_invalid", "field": "terminal_invocation"}
        ],
    }


def test_materialized_gold_fd_bootstrap_imports_only_from_the_verified_tree(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    builder.build_bundle(bundle_root)
    gold_path = bundle_root / "runtime/scripts/propertyquarry_gold_status.py"
    descriptor = os.open(
        gold_path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        completed = subprocess.run(
            [
                str(terminal.INSTALLED_PYTHON_PATH),
                "-I",
                "-c",
                terminal._gold_fd_bootstrap(bundle_root / "runtime"),
                f"/proc/self/fd/{descriptor}",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONNOUSERSITE": "1",
            },
            pass_fds=(descriptor,),
        )
    finally:
        os.close(descriptor)

    assert completed.returncode == 0, completed.stderr
    assert "PropertyQuarry" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


def test_bundle_builder_rejects_existing_or_symlink_output(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(builder.BundleBuildError):
        builder.build_bundle(existing)

    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "linked-output"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(builder.BundleBuildError):
        builder.build_bundle(symlink)
