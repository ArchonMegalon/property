from __future__ import annotations

import sys
import types

from app.services.scene_video_contract import (
    normalize_scene_video_backend_provider,
    normalize_scene_video_contract_provider,
    resolve_scene_video_script_path,
    scene_video_provider_runtime_readiness,
)


def test_scene_video_provider_aliases_are_whitespace_tolerant() -> None:
    assert normalize_scene_video_contract_provider(" magic ") == "omagic"
    assert normalize_scene_video_backend_provider(" one min ") == "onemin_i2v"
    assert normalize_scene_video_contract_provider("magic fit") == "magicfit"
    assert normalize_scene_video_backend_provider("mootion") == "mootion"


def test_scene_video_script_resolver_uses_runtime_repo_root(tmp_path, monkeypatch) -> None:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    expected = script_dir / "render_magicfit_property_flythrough.py"
    expected.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))

    assert resolve_scene_video_script_path("render_magicfit_property_flythrough.py") == expected.resolve()
    assert resolve_scene_video_script_path("../render_magicfit_property_flythrough.py") == expected.resolve()


def test_scene_video_runtime_readiness_reports_provider_blockers(tmp_path, monkeypatch) -> None:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "render_magicfit_property_flythrough.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("EA_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("MAGICFIT_EMAIL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_MAGICFIT_EMAIL", raising=False)
    monkeypatch.delenv("MAGICFIT_PASSWORD", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_MAGICFIT_PASSWORD", raising=False)

    blocked = scene_video_provider_runtime_readiness("magicfit")

    assert blocked["provider_key"] == "magicfit"
    assert blocked["status"] == "blocked"
    assert "magicfit_credentials_missing" in blocked["blockers"]
    assert blocked["checks"]["script_exists"] is True

    monkeypatch.setenv("MAGICFIT_EMAIL", "operator@example.test")
    monkeypatch.setenv("MAGICFIT_PASSWORD", "secret")

    ready = scene_video_provider_runtime_readiness("magic fit")

    assert ready["provider_key"] == "magicfit"
    assert ready["status"] == "ready"
    assert ready["blockers"] == []


def test_scene_video_runtime_readiness_blocks_known_omagic_credit_exhaustion(monkeypatch) -> None:
    fake_upstream = types.ModuleType("app.services.responses_upstream")

    def fake_provider_health_report(*, lightweight: bool = False) -> dict[str, object]:
        assert lightweight is True
        return {
            "providers": {
                "onemin": {
                    "configured_slots": 1,
                    "estimated_remaining_credits_total": 19,
                    "actual_remaining_credits_total": 19,
                    "live_dispatchable_slot_count": 0,
                    "slots": [
                        {
                            "slot": "ONEMIN_AI_API_KEY",
                            "configured": True,
                            "account_name": "Elvira Fortunato team",
                            "state": "quarantine",
                            "remaining_credits": 19,
                            "required_credits": 750000,
                            "credit_subject": "Elvira Fortunato team",
                            "last_failure_at": 1782724200.0,
                        }
                    ],
                }
            }
        }

    fake_upstream._provider_health_report = fake_provider_health_report
    monkeypatch.setitem(sys.modules, "app.services.responses_upstream", fake_upstream)
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "test-key")

    readiness = scene_video_provider_runtime_readiness("magic")

    assert readiness["provider_key"] == "omagic"
    assert readiness["status"] == "blocked"
    assert "onemin_i2v_insufficient_credits" in readiness["blockers"]
    assert readiness["checks"]["credit_state"] == "insufficient"
    assert readiness["checks"]["minimum_required_credits"] == 450000
    assert readiness["checks"]["slots"][0]["remaining_credits"] == 19


def test_normalize_scene_video_contract_provider_canonicalizes_public_values() -> None:
    assert normalize_scene_video_contract_provider("mootion") == "mootion"
    assert normalize_scene_video_contract_provider("magicfit") == "magicfit"
    assert normalize_scene_video_contract_provider("magic") == "omagic"
    assert normalize_scene_video_contract_provider("omagic") == "omagic"
    assert normalize_scene_video_contract_provider("onemin") == "omagic"
    assert normalize_scene_video_contract_provider("onemin_i2v") == "omagic"


def test_normalize_scene_video_contract_provider_uses_default_when_blank() -> None:
    assert normalize_scene_video_contract_provider("", default="magicfit") == "magicfit"
    assert normalize_scene_video_contract_provider(None, default="omagic") == "omagic"


def test_normalize_scene_video_backend_provider_canonicalizes_runtime_values() -> None:
    assert normalize_scene_video_backend_provider("mootion") == "mootion"
    assert normalize_scene_video_backend_provider("magicfit") == "magicfit"
    assert normalize_scene_video_backend_provider("magic") == "onemin_i2v"
    assert normalize_scene_video_backend_provider("omagic") == "onemin_i2v"
    assert normalize_scene_video_backend_provider("onemin") == "onemin_i2v"
    assert normalize_scene_video_backend_provider("onemin_i2v") == "onemin_i2v"


def test_normalize_scene_video_backend_provider_uses_default_when_blank() -> None:
    assert normalize_scene_video_backend_provider("", default="magicfit") == "magicfit"
    assert normalize_scene_video_backend_provider(None, default="omagic") == "onemin_i2v"
