from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "property_scene_video_runtime_status.py"
    spec = importlib.util.spec_from_file_location("property_scene_video_runtime_status", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scene_video_runtime_status_normalizes_provider_rows() -> None:
    module = _load_script()
    report = {
        "contract_name": "propertyquarry.scene_video_readiness.v1",
        "generated_at": "2026-07-07T01:30:00Z",
        "providers": [
            {
                "requested_provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "ready": False,
                "status": "blocked",
                "runtime_account_count": 0,
                "credit_state": "unverified",
                "blockers": ["magicfit_credentials_missing"],
                "account_inventory": {
                    "expected_account_count": 3,
                    "runtime_account_count": 0,
                    "visible_account_gap": 3,
                    "status": "gap",
                },
            },
            {
                "requested_provider": "mootion",
                "provider_key": "mootion",
                "provider_backend_key": "mootion",
                "ready": True,
                "status": "ready",
                "runtime_account_count": 0,
                "blockers": [],
                "execution_lane": "browseract_remote",
            },
        ],
        "telegram_delivery_readiness": {
            "configured": True,
            "status": "ready",
            "blockers": [],
        },
        "next_actions": [
            {
                "provider": "magicfit",
                "reason": "provider_account_visibility_gap",
                "severity": "high",
                "action": "Expose the expected provider accounts to the runtime secret/config layer, then regenerate the scene-video readiness receipt.",
            }
        ],
    }

    status = module.build_runtime_status(report, source_kind="receipt_file", source_ref="/tmp/scene-video.json")

    assert status["contract_name"] == "propertyquarry.scene_video_runtime_status.v1"
    assert status["source_contract_name"] == "propertyquarry.scene_video_readiness.v1"
    assert status["summary"] == {
        "provider_count": 2,
        "ready_count": 1,
        "blocked_count": 1,
        "blocked_providers": ["magicfit"],
        "action_required_count": 1,
        "action_required_providers": ["magicfit"],
        "delivery_ready": True,
    }
    magicfit, mootion = status["providers"]
    assert magicfit["provider"] == "magicfit"
    assert magicfit["status"] == "blocked"
    assert magicfit["execution_lane"] == "magicfit"
    assert magicfit["expected_account_count"] == 3
    assert magicfit["visible_account_gap"] == 3
    assert magicfit["blocking_reason"] == "magicfit_credentials_missing"
    assert magicfit["next_action_reason"] == "provider_account_visibility_gap"
    assert magicfit["next_action_severity"] == "high"
    assert magicfit["updated_at"] == "2026-07-07T01:30:00Z"
    assert mootion["provider"] == "mootion"
    assert mootion["ready"] is True
    assert mootion["execution_lane"] == "browseract_remote"


def test_scene_video_runtime_status_operator_output_is_factual() -> None:
    module = _load_script()
    status = {
        "generated_at": "2026-07-07T01:30:00Z",
        "source_kind": "live_runtime",
        "source_ref": "property_scene_video_readiness_report.build_report",
        "summary": {
            "ready_count": 2,
            "provider_count": 5,
            "blocked_count": 3,
            "action_required_count": 4,
        },
        "delivery": {
            "status": "blocked",
            "blocking_reason": "telegram_route_missing",
            "next_action_reason": "telegram_delivery_not_ready",
        },
        "providers": [
            {
                "provider": "magicfit",
                "status": "blocked",
                "execution_lane": "magicfit",
                "runtime_account_count": 0,
                "expected_account_count": 3,
                "visible_account_gap": 3,
                "credit_state": "unverified",
                "blocking_reason": "magicfit_credentials_missing",
                "next_action_reason": "provider_account_visibility_gap",
            },
            {
                "provider": "mootion",
                "status": "ready",
                "execution_lane": "browseract_remote",
                "runtime_account_count": 0,
            },
        ],
    }

    rendered = module.render_operator_status(status)

    assert "Scene-video runtime status @ 2026-07-07T01:30:00Z" in rendered
    assert "Source: live_runtime property_scene_video_readiness_report.build_report" in rendered
    assert "Summary: ready 2/5 | blocked 3 | action_required 4" in rendered
    assert "telegram | blocked | blocker=telegram_route_missing | next=telegram_delivery_not_ready" in rendered
    assert "magicfit | blocked | lane=magicfit | accounts=0/3 | gap=3 | credit=unverified | blocker=magicfit_credentials_missing | next=provider_account_visibility_gap" in rendered
    assert "mootion | ready | lane=browseract_remote | accounts=0" in rendered


def test_scene_video_runtime_status_cli_reads_receipt_and_prints_operator_view(tmp_path: Path) -> None:
    receipt = tmp_path / "scene-video-readiness.json"
    receipt.write_text(
        json.dumps(
            {
                "contract_name": "propertyquarry.scene_video_readiness.v1",
                "generated_at": "2026-07-07T01:30:00Z",
                "providers": [
                    {
                        "requested_provider": "omagic",
                        "provider_key": "omagic",
                        "provider_backend_key": "omagic",
                        "ready": False,
                        "status": "blocked",
                        "runtime_account_count": 0,
                        "blockers": ["omagic_credentials_missing"],
                        "account_inventory": {
                            "expected_account_count": 8,
                            "runtime_account_count": 0,
                            "visible_account_gap": 8,
                            "status": "gap",
                        },
                    }
                ],
                "telegram_delivery_readiness": {"configured": True, "status": "ready", "blockers": []},
                "next_actions": [
                    {
                        "provider": "omagic",
                        "reason": "omagic_credentials_missing",
                        "severity": "high",
                        "action": "Configure OMagic/Magic credentials in the OMagic/Magic runtime secret layer.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    script = ROOT / "scripts" / "property_scene_video_runtime_status.py"

    result = subprocess.run(
        [sys.executable, str(script), "--receipt", str(receipt), "--format", "operator"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Scene-video runtime status @ 2026-07-07T01:30:00Z" in result.stdout
    assert f"Source: receipt_file {receipt}" in result.stdout
    assert "omagic | blocked | lane=omagic | accounts=0/8 | gap=8 | blocker=omagic_credentials_missing | next=omagic_credentials_missing" in result.stdout


def test_scene_video_runtime_status_renders_tracked_inventory_for_credit_constrained_magicfit() -> None:
    module = _load_script()
    report = {
        "contract_name": "propertyquarry.scene_video_readiness.v1",
        "generated_at": "2026-07-07T09:26:08Z",
        "providers": [
            {
                "requested_provider": "magicfit",
                "provider_key": "magicfit",
                "provider_backend_key": "magicfit",
                "ready": True,
                "status": "ready",
                "runtime_account_count": 2,
                "credit_state": "constrained",
                "blockers": [],
                "account_inventory": {
                    "expected_account_count": 2,
                    "tracked_account_count": 3,
                    "unavailable_account_count": 1,
                    "availability_reason": "one_account_depleted",
                    "runtime_account_count": 2,
                    "visible_account_gap": 0,
                    "status": "ready",
                },
            }
        ],
        "telegram_delivery_readiness": {"configured": True, "status": "ready", "blockers": []},
        "next_actions": [
            {
                "provider": "magicfit",
                "reason": "magicfit_credit_constrained",
                "severity": "high",
                "action": "Select a funded MagicFit account or refresh credits, then clear the failure marker only after a successful provider render proof.",
            }
        ],
    }

    status = module.build_runtime_status(report, source_kind="receipt_file", source_ref="/tmp/scene-video.json")
    rendered = module.render_operator_status(status)

    assert status["providers"][0]["tracked_account_count"] == 3
    assert status["providers"][0]["unavailable_account_count"] == 1
    assert "magicfit | ready | lane=magicfit | accounts=2/2 | tracked=3 | unavailable=1 | credit=constrained | next=magicfit_credit_constrained" in rendered


def test_scene_video_runtime_status_cli_auto_loads_shared_env_for_live_runtime(tmp_path: Path) -> None:
    shared_env = tmp_path / "property_scene_video_shared.env"
    shared_env.write_text(
        "\n".join(
            [
                "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='[{\"email\":\"magicfit@example.test\",\"password\":\"magicfit-pass\"}]'",
                "EA_TELEGRAM_BOT_TOKEN='tg-bot-token'",
                "EA_TELEGRAM_DEFAULT_PRINCIPAL_ID='cf-email:test@example.test'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "scene_video_provider_inventory.json"
    inventory.write_text(
        json.dumps({"providers": {"magicfit": {"expected_account_count": 1}}}),
        encoding="utf-8",
    )
    script = ROOT / "scripts" / "property_scene_video_runtime_status.py"

    env = dict(os.environ)
    env["PROPERTYQUARRY_SCENE_VIDEO_SHARED_ENV_FILE"] = str(shared_env)
    env["PROPERTYQUARRY_SCENE_VIDEO_PROVIDER_INVENTORY_FILE"] = str(inventory)

    result = subprocess.run(
        [sys.executable, str(script), "--providers", "magicfit", "--format", "operator"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Source: live_runtime property_scene_video_readiness_report.build_report" in result.stdout
    assert "Summary: ready 1/1 | blocked 0 | action_required 0" in result.stdout
    assert "telegram | ready" in result.stdout
    assert "magicfit | ready | lane=magicfit | accounts=1/1 | credit=unprobed" in result.stdout
