from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scripts.property_tour_publication_lock import (
    property_tour_publication_lock_directory,
)
from tests.propertyquarry_phase_helpers import (
    install_property_run,
    property_client_with_workspace,
    seed_property_search_preferences,
)


def test_property_client_owns_public_tour_parent_before_lock_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper_environment_names = (
        "EA_STORAGE_BACKEND",
        "EA_ARTIFACTS_DIR",
        "EA_PUBLIC_TOUR_DIR",
        "PROPERTYQUARRY_LEGACY_PDF_RENDERER_ALLOW",
    )
    original_helper_environment = {
        name: os.environ[name]
        for name in helper_environment_names
        if name in os.environ
    }
    missing_public_tour_dir = (
        tmp_path / "missing-parent" / "state" / "public_property_tours"
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(missing_public_tour_dir))

    client = None
    try:
        client = property_client_with_workspace(
            principal_id="pq-phase-helper-tour-lock",
            tmp_path=tmp_path,
        )
        public_tour_dir = tmp_path / "public_property_tours"

        assert Path(os.environ["EA_PUBLIC_TOUR_DIR"]) == public_tour_dir
        assert public_tour_dir.is_dir() and not public_tour_dir.is_symlink()
        assert stat.S_IMODE(public_tour_dir.stat().st_mode) == 0o700
        assert not missing_public_tour_dir.parent.exists()

        seed_property_search_preferences(client)
        install_property_run(
            monkeypatch,
            property_url="https://example.com/phase-helper-tour-lock",
        )
        response = client.get(
            "/app/properties",
            params={"run_id": "run-phase-helper"},
        )

        assert response.status_code == 200
        lock_dir = property_tour_publication_lock_directory(public_tour_dir)
        assert lock_dir.is_dir() and not lock_dir.is_symlink()
        assert stat.S_IMODE(lock_dir.stat().st_mode) == 0o700
        assert lock_dir.stat().st_uid == os.geteuid()
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            for name in helper_environment_names:
                if name in original_helper_environment:
                    os.environ[name] = original_helper_environment[name]
                else:
                    os.environ.pop(name, None)
