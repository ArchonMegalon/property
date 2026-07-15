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


def test_scene_video_readiness_report_requires_principal_scoped_mootion_binding(monkeypatch) -> None:
    module = _load_script()
    import socket

    for env_name in module.MOOTION_BROWSERACT_PRINCIPAL_ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)

    missing = module.mootion_browseract_bridge_readiness()

    assert missing["ready"] is False
    assert missing["reason"] == "mootion_browseract_principal_scope_missing"
    assert missing["principal_scope_configured"] is False

    monkeypatch.setenv("PROPERTYQUARRY_SCENE_VIDEO_PRINCIPAL_ID", "principal-property-launch")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "different-generic-default")
    monkeypatch.setenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS", "cdn.example")
    monkeypatch.setattr(
        "app.mootion_remote_asset_policy.socket.getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )
    binding = type(
        "BindingStub",
        (),
        {
            "binding_id": "binding-property-launch",
            "principal_id": "principal-property-launch",
            "connector_name": "browseract",
            "external_account_ref": "mootion-property-bridge",
            "scope_json": {"services": ["mootion", "propertyquarry"]},
            "auth_metadata_json": {
                "mootion_browseract_bridge": True,
                "service_key": "mootion_movie",
                "mootion_movie_workflow_id": "wf-property-launch",
            },
            "status": "enabled",
        },
    )()

    class _RuntimeStub:
        def list_connector_bindings(self, principal_id: str, limit: int = 500):
            assert principal_id == "principal-property-launch"
            assert limit == 500
            return [binding]

    monkeypatch.setattr("app.services.tool_runtime.build_tool_runtime", lambda: _RuntimeStub())
    ready = module.mootion_browseract_bridge_readiness()
    rendered = json.dumps(ready)

    assert ready["ready"] is True
    assert ready["target_count"] == 1
    assert ready["principal_env_names"] == ["PROPERTYQUARRY_SCENE_VIDEO_PRINCIPAL_ID", "EA_DEFAULT_PRINCIPAL_ID"]
    assert ready["selected_principal_env_name"] == "PROPERTYQUARRY_SCENE_VIDEO_PRINCIPAL_ID"
    assert "principal-property-launch" not in rendered

    monkeypatch.delenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS")
    host_policy_missing = module.mootion_browseract_bridge_readiness()
    assert host_policy_missing["ready"] is False
    assert host_policy_missing["reason"] == "mootion_remote_asset_host_allowlist_missing"
    assert host_policy_missing["target_count"] == 1

    monkeypatch.setenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS", "https://cdn.example")
    malformed_host_policy = module.mootion_browseract_bridge_readiness()
    assert malformed_host_policy["ready"] is False
    assert malformed_host_policy["reason"] == "mootion_remote_asset_host_allowlist_invalid"

    monkeypatch.setenv("PROPERTYQUARRY_MOOTION_REMOTE_VIDEO_ALLOWED_HOSTS", "private.example")
    monkeypatch.setattr(
        "app.mootion_remote_asset_policy.socket.getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    private_host_policy = module.mootion_browseract_bridge_readiness()
    assert private_host_policy["ready"] is False
    assert private_host_policy["reason"] == "mootion_remote_asset_host_allowlist_invalid"


def test_scene_video_readiness_report_promotes_mootion_when_browseract_bridge_ready(monkeypatch) -> None:
    module = _load_script()
    remote_bridge = {
        "ready": True,
        "status": "ready",
        "reason": "",
        "principal_scope_configured": True,
        "principal_env_names": ["PROPERTYQUARRY_SCENE_VIDEO_PRINCIPAL_ID"],
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
    }
    monkeypatch.setattr(module, "mootion_browseract_bridge_readiness", lambda: dict(remote_bridge))
    monkeypatch.setattr(
        module,
        "scene_video_provider_runtime_readiness",
        lambda provider: {
            "provider_key": "mootion",
            "provider_backend_key": "mootion",
            "ready": True,
            "status": "ready",
            "blockers": [],
            "execution_lane": "browseract_remote",
            "checks": {
                "script_exists": True,
                "docker_socket_configured": False,
                "docker_cli_configured": False,
                "mootion_local_worker_blockers": ["mootion_docker_socket_missing", "mootion_docker_cli_missing"],
                "mootion_execution_lane": "browseract_remote",
                "mootion_browseract_remote": dict(remote_bridge),
            },
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


def test_scene_video_readiness_report_blocks_missing_mootion_remote_lane(monkeypatch) -> None:
    module = _load_script()
    remote_bridge = {
        "ready": False,
        "status": "unavailable",
        "target_count": 0,
        "targets": [],
    }
    monkeypatch.setattr(module, "mootion_browseract_bridge_readiness", lambda: dict(remote_bridge))
    monkeypatch.setattr(
        module,
        "scene_video_provider_runtime_readiness",
        lambda provider: {
            "provider_key": "mootion",
            "provider_backend_key": "mootion",
            "ready": True,
            "status": "ready",
            "blockers": [],
            "checks": {
                "script_exists": True,
                "docker_socket_configured": True,
                "docker_cli_configured": True,
                "mootion_browseract_remote": dict(remote_bridge),
            },
        },
    )

    report = module.build_report(providers=("mootion",))
    row = report["providers"][0]
    reasons = {(action["provider"], action["reason"]) for action in report["next_actions"]}

    assert row["ready"] is False
    assert row["status"] == "blocked"
    assert row["blockers"] == [
        "mootion_browseract_remote_lane_missing",
        "mootion_browseract_bridge_not_ready",
    ]
    assert "execution_lane" not in row
    assert report["summary"] == {
        "provider_count": 1,
        "ready_count": 0,
        "blocked_count": 1,
        "blocked_providers": ["mootion"],
    }
    assert ("mootion", "mootion_browseract_remote_lane_missing") in reasons
    assert ("mootion", "mootion_browseract_bridge_not_ready") in reasons
    lane_action = next(
        action
        for action in report["next_actions"]
        if action["provider"] == "mootion" and action["reason"] == "mootion_browseract_remote_lane_missing"
    )
    assert lane_action["current_execution_lane"] == "local_worker_or_unset"


def test_scene_video_readiness_report_blocks_requested_mootion_with_invalid_runtime_identity(monkeypatch) -> None:
    module = _load_script()
    remote_bridge = {
        "ready": False,
        "status": "blocked",
        "target_count": 0,
        "targets": [],
    }
    monkeypatch.setattr(module, "mootion_browseract_bridge_readiness", lambda: dict(remote_bridge))

    for runtime_provider_key in (None, "unexpected-provider"):
        monkeypatch.setattr(
            module,
            "scene_video_provider_runtime_readiness",
            lambda provider, key=runtime_provider_key: {
                "provider_key": key,
                "provider_backend_key": key,
                "ready": True,
                "status": "ready",
                "blockers": [],
                "checks": {
                    "mootion_browseract_remote": dict(remote_bridge),
                },
            },
        )

        report = module.build_report(providers=("mootion",))
        row = report["providers"][0]
        reasons = {(action["provider"], action["reason"]) for action in report["next_actions"]}

        assert row["ready"] is False
        assert row["status"] == "blocked"
        assert row["blockers"] == [
            "mootion_browseract_remote_lane_missing",
            "mootion_browseract_bridge_not_ready",
        ]
        assert report["summary"]["ready_count"] == 0
        assert report["summary"]["blocked_providers"] == ["mootion"]
        assert ("mootion", "mootion_browseract_remote_lane_missing") in reasons
        assert ("mootion", "mootion_browseract_bridge_not_ready") in reasons


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


def test_scene_video_readiness_report_actions_missing_omagic_adapter_target(monkeypatch) -> None:
    module = _load_script()

    def fake_readiness(provider: str) -> dict[str, object]:
        return {
            "provider_key": "omagic",
            "provider_backend_key": "omagic",
            "ready": False,
            "status": "blocked",
            "blockers": ["omagic_model_upload_endpoint_missing"],
            "runtime_account_count": 8,
            "checks": {
                "model_upload_adapter_enabled": True,
                "model_upload_adapter_target_configured": False,
                "model_upload_endpoint_env_names": [],
                "model_upload_command_env_names": [],
                "secret_value": "forbidden-secret",
            },
        }

    monkeypatch.setattr(module, "scene_video_provider_runtime_readiness", fake_readiness)
    report = module.build_report(providers=("magic",))

    row = report["providers"][0]
    reasons = {(action["provider"], action["reason"]) for action in report["next_actions"]}
    rendered = json.dumps(report)
    assert row["checks"]["model_upload_adapter_target_configured"] is False
    assert ("omagic", "omagic_model_upload_endpoint_missing") in reasons
    assert "forbidden-secret" not in rendered


def test_scene_video_readiness_report_actions_disabled_omagic_adapter_with_missing_target(monkeypatch) -> None:
    module = _load_script()

    def fake_readiness(provider: str) -> dict[str, object]:
        return {
            "provider_key": "omagic",
            "provider_backend_key": "omagic",
            "ready": False,
            "status": "blocked",
            "blockers": [
                "omagic_model_upload_adapter_disabled",
                "omagic_model_upload_endpoint_missing",
            ],
            "runtime_account_count": 8,
            "checks": {
                "script_exists": True,
                "model_upload_adapter_enabled": False,
                "model_upload_adapter_target_configured": False,
                "model_upload_endpoint_env_names": [],
                "model_upload_command_env_names": [],
            },
        }

    monkeypatch.setattr(module, "scene_video_provider_runtime_readiness", fake_readiness)

    report = module.build_report(providers=("omagic",))
    reasons = {(action["provider"], action["reason"]) for action in report["next_actions"]}

    assert ("omagic", "omagic_model_upload_adapter_disabled") in reasons
    assert ("omagic", "omagic_model_upload_endpoint_missing") in reasons


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


def test_scene_video_readiness_report_records_tracked_inventory_and_magicfit_credit_constraint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    inventory = tmp_path / "scene_video_provider_inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "providers": {
                    "magicfit": {
                        "expected_account_count": 2,
                        "tracked_account_count": 3,
                        "unavailable_account_count": 1,
                        "availability_reason": "one_account_depleted",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_INVENTORY_FILE", str(inventory))
    monkeypatch.delenv("PROPERTYQUARRY_SCENE_VIDEO_EXPECTED_ACCOUNT_COUNTS_JSON", raising=False)
    monkeypatch.setattr(
        module,
        "scene_video_provider_runtime_readiness",
        lambda provider: {
            "provider_key": "magicfit",
            "provider_backend_key": "magicfit",
            "ready": True,
            "status": "ready",
            "blockers": [],
            "runtime_account_count": 2,
            "credit_state": "constrained",
            "checks": {
                "runtime_account_count": 2,
                "credit_state": "constrained",
            },
        },
    )

    report = module.build_report(providers=("magicfit",))
    row = report["providers"][0]
    reasons = {(action["provider"], action["reason"]) for action in report["next_actions"]}

    assert row["account_inventory"] == {
        "expected_account_count": 2,
        "runtime_account_count": 2,
        "tracked_account_count": 3,
        "unavailable_account_count": 1,
        "availability_reason": "one_account_depleted",
        "visible_account_gap": 0,
        "status": "ready",
        "source_ref": str(inventory),
        "source_kind": "file",
    }
    assert ("magicfit", "provider_account_visibility_gap") not in reasons
    assert ("magicfit", "magicfit_credit_constrained") in reasons


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
