from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "property_scene_video_readiness_report.py"
    spec = importlib.util.spec_from_file_location("property_scene_video_readiness_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scene_video_readiness_report_is_secret_safe_and_preserves_provider_keys(monkeypatch) -> None:
    module = _load_script()

    def fake_readiness(provider: str) -> dict[str, object]:
        if provider == "magic":
            return {
                "provider_key": "omagic",
                "provider_backend_key": "omagic",
                "ready": False,
                "status": "blocked",
                "blockers": ["omagic_model_upload_adapter_missing"],
                "runtime_account_count": 8,
                "checks": {
                    "runtime_account_email_env_names": ["MAGIC_ACCOUNTS_JSON[1].email"],
                    "runtime_api_key_env_names": ["MAGIC_API_KEY"],
                    "secret_value": "forbidden-secret",
                },
            }
        return {
            "provider_key": provider,
            "provider_backend_key": provider,
            "ready": True,
            "status": "ready",
            "blockers": [],
            "checks": {"script_exists": True},
        }

    monkeypatch.setattr(module, "scene_video_provider_runtime_readiness", fake_readiness)
    monkeypatch.setenv("PROPERTYQUARRY_TELEGRAM_BOT_TOKEN", "forbidden-token")
    monkeypatch.setenv("PROPERTYQUARRY_TELEGRAM_CHAT_ID", "forbidden-chat")

    report = module.build_report(providers=("magic", "magicfit"))
    rendered = json.dumps(report)

    assert report["contract_name"] == "propertyquarry.scene_video_readiness.v1"
    assert report["providers"][0]["provider_key"] == "omagic"
    assert report["providers"][0]["provider_backend_key"] == "omagic"
    assert report["providers"][0]["runtime_account_count"] == 8
    assert report["providers"][0]["checks"]["runtime_account_email_env_names"] == ["MAGIC_ACCOUNTS_JSON[1].email"]
    assert report["telegram_delivery_readiness"]["status"] == "ready"
    assert "forbidden-secret" not in rendered
    assert "forbidden-token" not in rendered
    assert "forbidden-chat" not in rendered


def test_scene_video_readiness_report_accepts_default_principal_telegram_route(monkeypatch) -> None:
    module = _load_script()
    for key in (
        "PROPERTYQUARRY_TELEGRAM_CHAT_ID",
        "TELEGRAM_CHAT_ID",
        "EA_TELEGRAM_CHAT_ID",
        "EA_TELEGRAM_DEFAULT_CHAT_ID",
        "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID",
        "EA_TELEGRAM_BOT_REGISTRY_JSON",
        "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "forbidden-token")
    monkeypatch.setenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "principal-1")

    readiness = module.telegram_delivery_readiness()
    rendered = json.dumps(readiness)

    assert readiness["status"] == "ready"
    assert readiness["route_env_names"] == ["EA_TELEGRAM_DEFAULT_PRINCIPAL_ID"]
    assert "forbidden-token" not in rendered
    assert "principal-1" not in rendered


def test_scene_video_readiness_report_promotes_mootion_when_browseract_bridge_ready(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "scene_video_provider_runtime_readiness",
        lambda provider: {
            "provider_key": "mootion",
            "provider_backend_key": "mootion",
            "ready": False,
            "status": "blocked",
            "blockers": ["mootion_docker_socket_missing", "mootion_docker_cli_missing"],
            "checks": {"script_exists": True, "docker_socket_configured": False, "docker_cli_configured": False},
        },
    )
    monkeypatch.setattr(
        module,
        "mootion_browseract_bridge_readiness",
        lambda: {
            "ready": True,
            "status": "ready",
            "target_count": 1,
            "targets": [
                {
                    "binding_id": "binding-1",
                    "external_account_ref": "mootion-scene-video-bridge",
                    "status": "enabled",
                    "workflow_configured": True,
                    "run_url_configured": False,
                }
            ],
        },
    )

    report = module.build_report(providers=("mootion",))
    row = report["providers"][0]

    assert row["ready"] is True
    assert row["status"] == "ready"
    assert row["blockers"] == []
    assert row["execution_lane"] == "browseract_remote"
    assert row["checks"]["mootion_local_worker_blockers"] == [
        "mootion_docker_socket_missing",
        "mootion_docker_cli_missing",
    ]
    assert row["checks"]["mootion_browseract_remote"]["target_count"] == 1
    assert report["summary"]["ready_count"] == 1


def test_scene_video_readiness_report_records_expected_account_visibility_gaps(monkeypatch) -> None:
    module = _load_script()

    def fake_readiness(provider: str) -> dict[str, object]:
        if provider == "magicfit":
            return {
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "ready": False,
                "status": "blocked",
                "blockers": ["magicfit_insufficient_credits"],
                "runtime_account_count": 1,
                "checks": {"runtime_account_count": 1},
            }
        return {
            "provider_key": "omagic",
            "provider_backend_key": "omagic",
            "ready": False,
            "status": "blocked",
            "blockers": ["omagic_credentials_missing"],
            "runtime_account_count": 0,
            "checks": {"runtime_account_count": 0},
        }

    monkeypatch.setattr(module, "scene_video_provider_runtime_readiness", fake_readiness)
    monkeypatch.setenv(
        "PROPERTYQUARRY_SCENE_VIDEO_EXPECTED_ACCOUNT_COUNTS_JSON",
        json.dumps({"magicfit": 3, "omagic": 8}),
    )

    report = module.build_report(providers=("magicfit", "magic"))
    magicfit, magic = report["providers"]

    assert magicfit["account_inventory"] == {
        "expected_account_count": 3,
        "runtime_account_count": 1,
        "visible_account_gap": 2,
        "status": "gap",
        "source_ref": "PROPERTYQUARRY_SCENE_VIDEO_EXPECTED_ACCOUNT_COUNTS_JSON",
        "source_kind": "env",
    }
    assert magic["account_inventory"] == {
        "expected_account_count": 8,
        "runtime_account_count": 0,
        "visible_account_gap": 8,
        "status": "gap",
        "source_ref": "PROPERTYQUARRY_SCENE_VIDEO_EXPECTED_ACCOUNT_COUNTS_JSON",
        "source_kind": "env",
    }
    reasons = {(row["provider"], row["reason"]) for row in report["next_actions"]}
    assert ("magicfit", "provider_account_visibility_gap") in reasons
    assert ("magic", "provider_account_visibility_gap") in reasons
    assert ("magicfit", "magicfit_insufficient_credits") in reasons
    assert ("omagic", "omagic_credentials_missing") in reasons
    rendered_actions = json.dumps(report["next_actions"])
    assert "ONEMIN_*" in rendered_actions
    assert "forbidden-secret" not in rendered_actions


def test_scene_video_readiness_report_reads_expected_account_counts_from_inventory_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    inventory = tmp_path / "scene_video_provider_inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "providers": {
                    "magicfit": {"expected_account_count": 3},
                    "omagic": {"expected_account_count": 8, "aliases": ["magic"]},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PROPERTYQUARRY_SCENE_VIDEO_EXPECTED_ACCOUNT_COUNTS_JSON", raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_INVENTORY_FILE", str(inventory))

    assert module.expected_account_count_for_provider(requested_provider="magicfit", provider_key="magicfit") == (
        3,
        str(inventory),
    )
    assert module.expected_account_count_for_provider(requested_provider="magic", provider_key="omagic") == (
        8,
        str(inventory),
    )


def test_scene_video_readiness_report_cli_writes_receipt(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    script = ROOT / "scripts" / "property_scene_video_readiness_report.py"

    result = subprocess.run(
        [sys.executable, str(script), "--providers", "magic,onemin_i2v", "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout)
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert stdout["status"] == "pass"
    assert stdout["output"] == str(output)
    assert receipt["summary"]["provider_count"] == 2
    assert [row["requested_provider"] for row in receipt["providers"]] == ["magic", "onemin_i2v"]
    assert receipt["secret_boundary"].startswith("This receipt records env variable names")
