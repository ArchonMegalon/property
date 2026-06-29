import json
import os
from pathlib import Path

from app.services import scene_video_contract as service


def _clear_scene_video_provider_env(monkeypatch) -> None:
    for key in list(os.environ):
        if (
            "MAGICFIT" in key
            or "OMAGIC" in key
            or key.startswith("MAGIC_")
            or key.startswith("PROPERTYQUARRY_MAGIC_")
            or key.startswith("ONEMIN_")
        ):
            monkeypatch.delenv(key, raising=False)


def test_scene_video_magic_and_omagic_normalize_to_omagic_not_onemin() -> None:
    assert service.normalize_scene_video_contract_provider("magic") == "omagic"
    assert service.normalize_scene_video_contract_provider("omagic") == "omagic"
    assert service.normalize_scene_video_backend_provider("magic") == "omagic"
    assert service.normalize_scene_video_backend_provider("omagic") == "omagic"


def test_scene_video_omagic_readiness_ignores_onemin_credentials(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "not-an-omagic-credential")

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["provider_backend_key"] == "omagic"
    assert readiness["checks"]["account_config_scope"] == "omagic_only_config"
    assert readiness["runtime_account_count"] == 0
    assert "omagic_credentials_missing" in readiness["blockers"]
    assert "onemin_i2v_api_key_missing" not in readiness["blockers"]


def test_scene_video_omagic_readiness_counts_magic_accounts_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "MAGIC_ACCOUNTS_JSON",
        json.dumps(
            [
                {"email": f"magic-{index}@example.com", "password": "secret"}
                for index in range(1, 9)
            ]
        ),
    )

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["provider_backend_key"] == "omagic"
    assert readiness["ready"] is False
    assert readiness["runtime_account_count"] == 8
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "MAGIC_ACCOUNTS_JSON[1].email"
    assert readiness["checks"]["model_upload_adapter_enabled"] is False
    assert readiness["blockers"] == ["omagic_model_upload_adapter_disabled"]


def test_scene_video_magicfit_readiness_counts_three_accounts_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_magicfit_property_flythrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_MAGICFIT_IGNORE_CREDIT_MARKER", "1")
    monkeypatch.setenv(
        "MAGICFIT_ACCOUNTS_JSON",
        json.dumps(
            [
                {"email": f"magicfit-{index}@example.com", "password": "secret"}
                for index in range(1, 4)
            ]
        ),
    )

    readiness = service.scene_video_provider_runtime_readiness("magicfit")

    assert readiness["provider_key"] == "magicfit"
    assert readiness["provider_backend_key"] == "magicfit"
    assert readiness["ready"] is True
    assert readiness["runtime_account_count"] == 3
    assert readiness["checks"]["runtime_account_email_env_names"] == [
        "MAGICFIT_ACCOUNTS_JSON[1].email",
        "MAGICFIT_ACCOUNTS_JSON[2].email",
        "MAGICFIT_ACCOUNTS_JSON[3].email",
    ]
