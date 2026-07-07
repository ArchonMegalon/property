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
    assert readiness["blockers"] == [
        "omagic_model_upload_adapter_disabled",
        "omagic_model_upload_endpoint_missing",
    ]


def test_scene_video_omagic_readiness_counts_suffix_magic_accounts_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "TEAM_MAGIC_ACCOUNTS_JSON",
        json.dumps(
            [
                {"email": f"magic-{index}@example.com", "password": "secret"}
                for index in range(1, 9)
            ]
        ),
    )

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["runtime_account_count"] == 8
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "TEAM_MAGIC_ACCOUNTS_JSON[1].email"
    assert readiness["checks"]["account_config_env_names"] == ["TEAM_MAGIC_ACCOUNTS_JSON"]
    assert readiness["blockers"] == [
        "omagic_model_upload_adapter_disabled",
        "omagic_model_upload_endpoint_missing",
    ]


def test_scene_video_omagic_readiness_counts_magic_accounts_json_file(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    accounts_path = tmp_path / "omagic-accounts.json"
    accounts_path.write_text(
        json.dumps(
            [
                {"email": f"magic-{index}@example.com", "password": "secret"}
                for index in range(1, 9)
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MAGIC_ACCOUNTS_JSON_FILE", str(accounts_path))

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["runtime_account_count"] == 8
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "MAGIC_ACCOUNTS_JSON_FILE[1].email"
    assert readiness["checks"]["account_config_env_names"] == ["MAGIC_ACCOUNTS_JSON_FILE"]
    assert readiness["blockers"] == [
        "omagic_model_upload_adapter_disabled",
        "omagic_model_upload_endpoint_missing",
    ]


def test_scene_video_omagic_readiness_resolves_runtime_accounts_json_file_to_host_incoming_root(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    incoming_root = tmp_path / "state" / "incoming_property_tours"
    accounts_path = incoming_root / "_operator-import-lane" / "scene_video_provider_accounts" / "omagic-accounts.json"
    accounts_path.parent.mkdir(parents=True, exist_ok=True)
    accounts_path.write_text(
        json.dumps(
            [
                {"email": f"magic-{index}@example.com", "password": "secret"}
                for index in range(1, 9)
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR", str(incoming_root))
    monkeypatch.setenv(
        "MAGIC_ACCOUNTS_JSON_FILE",
        "/data/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/omagic-accounts.json",
    )

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["runtime_account_count"] == 8
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "MAGIC_ACCOUNTS_JSON_FILE[1].email"
    assert readiness["checks"]["account_config_env_names"] == ["MAGIC_ACCOUNTS_JSON_FILE"]
    assert readiness["blockers"] == [
        "omagic_model_upload_adapter_disabled",
        "omagic_model_upload_endpoint_missing",
    ]


def test_scene_video_omagic_readiness_prefers_accounts_json_file_over_inline_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    accounts_path = tmp_path / "omagic-accounts.json"
    accounts_path.write_text(
        json.dumps([{"email": "file@example.com", "password": "secret"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MAGIC_ACCOUNTS_JSON", json.dumps([{"email": "inline@example.com", "password": "secret"}]))
    monkeypatch.setenv("MAGIC_ACCOUNTS_JSON_FILE", str(accounts_path))

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["runtime_account_count"] == 2
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "MAGIC_ACCOUNTS_JSON_FILE[1].email"


def test_scene_video_omagic_readiness_requires_adapter_target_when_enabled(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_API_KEY", "secret")

    readiness = service.scene_video_provider_runtime_readiness("omagic")

    assert readiness["ready"] is False
    assert readiness["checks"]["model_upload_adapter_target_configured"] is False
    assert readiness["checks"]["model_upload_supported"] is False
    assert readiness["blockers"] == ["omagic_model_upload_endpoint_missing"]


def test_scene_video_omagic_readiness_passes_with_enabled_adapter_target_and_credentials(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_omagic_property_model_walkthrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED", "1")
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_API_KEY", "secret")
    monkeypatch.setenv("PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT", "https://omagic.example/render")

    readiness = service.scene_video_provider_runtime_readiness("magic")

    assert readiness["ready"] is True
    assert readiness["checks"]["model_upload_adapter_target_configured"] is True
    assert readiness["checks"]["model_upload_endpoint_env_names"] == ["PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT"]
    assert readiness["checks"]["model_upload_supported"] is True
    assert readiness["blockers"] == []


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


def test_scene_video_magicfit_readiness_counts_suffix_accounts_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_magicfit_property_flythrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_MAGICFIT_IGNORE_CREDIT_MARKER", "1")
    monkeypatch.setenv(
        "TEAM_MAGICFIT_ACCOUNTS_JSON",
        json.dumps(
            [
                {"email": f"magicfit-{index}@example.com", "password": "secret"}
                for index in range(1, 4)
            ]
        ),
    )

    readiness = service.scene_video_provider_runtime_readiness("magicfit")

    assert readiness["provider_key"] == "magicfit"
    assert readiness["ready"] is True
    assert readiness["runtime_account_count"] == 3
    assert readiness["checks"]["runtime_account_email_env_names"] == [
        "TEAM_MAGICFIT_ACCOUNTS_JSON[1].email",
        "TEAM_MAGICFIT_ACCOUNTS_JSON[2].email",
        "TEAM_MAGICFIT_ACCOUNTS_JSON[3].email",
    ]


def test_scene_video_magicfit_readiness_counts_accounts_json_file(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_magicfit_property_flythrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    accounts_path = tmp_path / "magicfit-accounts.json"
    accounts_path.write_text(
        json.dumps(
            [
                {"email": f"magicfit-{index}@example.com", "password": "secret"}
                for index in range(1, 4)
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_MAGICFIT_IGNORE_CREDIT_MARKER", "1")
    monkeypatch.setenv("MAGICFIT_ACCOUNTS_JSON_FILE", str(accounts_path))

    readiness = service.scene_video_provider_runtime_readiness("magicfit")

    assert readiness["provider_key"] == "magicfit"
    assert readiness["ready"] is True
    assert readiness["runtime_account_count"] == 3
    assert readiness["checks"]["runtime_account_email_env_names"] == [
        "MAGICFIT_ACCOUNTS_JSON_FILE[1].email",
        "MAGICFIT_ACCOUNTS_JSON_FILE[2].email",
        "MAGICFIT_ACCOUNTS_JSON_FILE[3].email",
    ]


def test_scene_video_magicfit_readiness_prefers_accounts_json_file_over_inline_json(monkeypatch, tmp_path: Path) -> None:
    _clear_scene_video_provider_env(monkeypatch)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_magicfit_property_flythrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    accounts_path = tmp_path / "magicfit-accounts.json"
    accounts_path.write_text(
        json.dumps([{"email": "file@example.com", "password": "secret"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYQUARRY_MAGICFIT_IGNORE_CREDIT_MARKER", "1")
    monkeypatch.setenv("MAGICFIT_ACCOUNTS_JSON", json.dumps([{"email": "inline@example.com", "password": "secret"}]))
    monkeypatch.setenv("MAGICFIT_ACCOUNTS_JSON_FILE", str(accounts_path))

    readiness = service.scene_video_provider_runtime_readiness("magicfit")

    assert readiness["runtime_account_count"] == 2
    assert readiness["checks"]["runtime_account_email_env_names"][0] == "MAGICFIT_ACCOUNTS_JSON_FILE[1].email"


def test_property_walkthrough_runtime_provider_prefers_magicfit_when_omagic_is_blocked(monkeypatch) -> None:
    def _fake_readiness(provider_key):
        provider_key = str(provider_key or "").strip()
        if provider_key == "omagic":
            return {
                "provider_key": "omagic",
                "provider_backend_key": "omagic",
                "ready": False,
                "status": "blocked",
                "blockers": ["omagic_model_upload_adapter_missing"],
                "checks": {},
            }
        if provider_key == "magicfit":
            return {
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "ready": True,
                "status": "ready",
                "blockers": [],
                "checks": {},
            }
        return {
            "provider_key": provider_key,
            "provider_backend_key": provider_key,
            "ready": False,
            "status": "blocked",
            "blockers": [f"{provider_key}_blocked"],
            "checks": {},
        }

    monkeypatch.setattr(service, "scene_video_provider_runtime_readiness", _fake_readiness)

    resolution = service.resolve_property_walkthrough_runtime_provider("")

    assert resolution["provider_backend_key"] == "magicfit"
    assert resolution["selected_via"] == "auto_final_ready"
    assert resolution["checked"][0]["provider_key"] == "omagic"
    assert resolution["checked"][1]["provider_key"] == "magicfit"


def test_property_walkthrough_runtime_provider_falls_back_to_onemin_when_final_primary_lanes_are_blocked(monkeypatch) -> None:
    def _fake_readiness(provider_key):
        provider_key = str(provider_key or "").strip()
        if provider_key == "onemin_i2v":
            return {
                "provider_key": "onemin_i2v",
                "provider_backend_key": "onemin_i2v",
                "ready": True,
                "status": "ready",
                "blockers": [],
                "checks": {},
            }
        return {
            "provider_key": provider_key,
            "provider_backend_key": provider_key,
            "ready": False,
            "status": "blocked",
            "blockers": [f"{provider_key}_blocked"],
            "checks": {},
        }

    monkeypatch.setattr(service, "scene_video_provider_runtime_readiness", _fake_readiness)

    resolution = service.resolve_property_walkthrough_runtime_provider("")

    assert resolution["provider_backend_key"] == "onemin_i2v"
    assert resolution["selected_via"] == "auto_final_ready"
    assert [entry["provider_key"] for entry in resolution["checked"]] == ["omagic", "magicfit", "onemin_i2v"]
