from __future__ import annotations

from pathlib import Path

import pytest

from app.services import provider_registry


def test_optional_onemin_manifest_ignores_inaccessible_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = Path("/app/config/onemin_api_keys.local.json")
    monkeypatch.setenv("ONEMIN_DIRECT_API_KEYS_JSON_FILE", str(manifest_path))
    original_is_file = Path.is_file

    def guarded_is_file(path: Path) -> bool:
        if path == manifest_path:
            raise PermissionError("optional manifest is not readable by this runtime")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)

    assert provider_registry._onemin_manifest_path() is None
    assert provider_registry._onemin_manifest_account_names() == ()
