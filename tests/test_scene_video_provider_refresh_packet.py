from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "materialize_scene_video_provider_refresh_packet.py"
    spec = importlib.util.spec_from_file_location("materialize_scene_video_provider_refresh_packet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_verifier() -> ModuleType:
    path = ROOT / "scripts" / "verify_scene_video_provider_refresh_packet.py"
    spec = importlib.util.spec_from_file_location("verify_scene_video_provider_refresh_packet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt() -> dict[str, object]:
    return {
        "providers": [
            {
                "requested_provider": "magicfit",
                "status": "blocked",
                "blockers": ["magicfit_insufficient_credits"],
                "runtime_account_count": 1,
                "account_inventory": {
                    "expected_account_count": 3,
                    "runtime_account_count": 1,
                    "visible_account_gap": 2,
                },
            },
            {
                "requested_provider": "omagic",
                "provider_key": "omagic",
                "provider_backend_key": "omagic",
                "status": "blocked",
                "blockers": ["omagic_model_upload_adapter_missing", "omagic_credentials_missing"],
                "runtime_account_count": 0,
                "account_inventory": {
                    "expected_account_count": 8,
                    "runtime_account_count": 0,
                    "visible_account_gap": 8,
                },
            },
        ]
    }


def test_scene_video_provider_refresh_packet_names_env_contracts_without_secrets(tmp_path: Path) -> None:
    module = _load_script()

    packet = module.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    rendered = json.dumps(packet)
    providers = {row["provider"]: row for row in packet["providers"]}

    assert providers["magicfit"]["visible_account_gap"] == 2
    assert providers["magicfit"]["credential_contract"]["preferred_accounts_json_env"] == "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"
    assert providers["magicfit"]["credential_contract"]["account_selector_env"] == "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX"
    assert providers["magicfit"]["credit_refresh_required"] is True
    assert providers["magicfit"]["proof_contract"]["proof_render_required"] is True
    assert providers["magicfit"]["proof_contract"]["credit_marker"] == "magicfit_insufficient_credits"
    assert providers["magicfit"]["proof_contract"]["account_selector_env"] == "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX"
    assert providers["omagic"]["visible_account_gap"] == 8
    assert providers["omagic"]["credential_contract"]["preferred_accounts_json_env"] == "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON"
    assert providers["omagic"]["adapter_contract"]["enable_flag"] == "PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED"
    assert "PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT" in providers["omagic"]["adapter_contract"]["render_endpoint_envs"]
    assert "OMAGIC_RENDER_ENDPOINT" in providers["omagic"]["adapter_contract"]["render_endpoint_envs"]
    assert "PROPERTYQUARRY_OMAGIC_RENDER_COMMAND" in providers["omagic"]["adapter_contract"]["render_command_envs"]
    assert "OMAGIC_RENDER_COMMAND" in providers["omagic"]["adapter_contract"]["render_command_envs"]
    assert providers["omagic"]["adapter_contract"]["proof_render_required"] is True
    assert "set provider account JSON file mode to 0o600 before merge" in rendered
    assert "merge_scene_video_provider_accounts_env.py" in rendered
    assert "--magicfit-accounts-json-file <magicfit-accounts.json> --expected-magicfit-count 3 --write" in rendered
    assert "--omagic-accounts-json-file <omagic-accounts.json> --expected-omagic-count 8 --write" in rendered
    assert "provider_backend_key=magicfit" in rendered
    assert "playable hosted walkthrough video" in rendered
    assert "clear MagicFit credit marker only after" in rendered
    assert "model_input_consumed=true" in rendered
    assert "provider_backend_key=omagic" in rendered
    assert "PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED=1 only after" in rendered
    assert "ONEMIN_*" in rendered
    assert "ONEMIN_AI_API_KEY" in rendered
    assert "forbidden-password" not in rendered.lower()
    assert "@gmail.com" not in rendered
    assert "<magicfit-account-password>" in rendered


def test_scene_video_provider_refresh_packet_cli_writes_packet(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    output_path = tmp_path / "packet.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")
    script = ROOT / "scripts" / "materialize_scene_video_provider_refresh_packet.py"

    result = subprocess.run(
        [sys.executable, str(script), "--receipt", str(receipt_path), "--output", str(output_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout)
    packet = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout["status"] == "pass"
    assert stdout["provider_count"] == 2
    assert packet["source_receipt"] == str(receipt_path)


def test_scene_video_provider_refresh_packet_verifier_passes_generated_packet(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "pass"
    assert receipt["generated_at"].endswith("Z")
    assert receipt["blockers"] == []
    assert receipt["checked_providers"] == ["magicfit", "omagic"]
    assert receipt["provider_count"] == 2
    assert receipt["safe_env_merge_script"].endswith("scripts/merge_scene_video_provider_accounts_env.py")


def test_scene_video_provider_refresh_packet_verifier_rejects_secrets_and_missing_onemin_boundary(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["magicfit"]["credential_contract"]["json_shape"][0]["email"] = "operator@example.com"
    providers["magicfit"]["do_not_touch"] = []

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "packet_contains_real_email:$.providers[0].credential_contract.json_shape[0].email" in receipt["blockers"]
    assert "magicfit_onemin_boundary_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_missing_safe_merge_guidance(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["omagic"]["post_refresh_checks"] = ["manually edit .env"]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "omagic_safe_env_merge_guidance_missing" in receipt["blockers"]
    assert "omagic_secure_account_json_mode_guidance_missing" in receipt["blockers"]
    assert "omagic_account_json_file_flag_missing" in receipt["blockers"]
    assert "omagic_expected_account_count_guard_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_missing_secure_json_mode_guidance(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["magicfit"]["post_refresh_checks"] = [
        "merge provider-only MagicFit account JSON with merge_scene_video_provider_accounts_env.py --magicfit-accounts-json-file <magicfit-accounts.json> --expected-magicfit-count 3 --write"
    ]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "magicfit_secure_account_json_mode_guidance_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_missing_magicfit_account_selector_env(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["magicfit"]["credential_contract"].pop("account_selector_env")

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "magicfit_account_selector_env_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_magicfit_proof_gaps(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    proof = providers["magicfit"]["proof_contract"]
    proof["proof_render_required"] = False
    proof["credit_marker"] = ""
    proof["account_selector_env"] = ""
    proof["credit_marker_policy"] = "clear marker manually"
    proof["proof_render_checks"] = []
    providers["magicfit"]["post_refresh_checks"] = [
        "set provider account JSON file mode to 0o600 before merge",
        "merge provider-only MagicFit account JSON with merge_scene_video_provider_accounts_env.py --magicfit-accounts-json-file <magicfit-accounts.json> --expected-magicfit-count 3 --write",
    ]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "magicfit_proof_render_required_missing" in receipt["blockers"]
    assert "magicfit_credit_marker_contract_missing" in receipt["blockers"]
    assert "magicfit_proof_account_selector_env_missing" in receipt["blockers"]
    assert "magicfit_credit_marker_policy_proof_missing" in receipt["blockers"]
    assert "magicfit_selected_account_proof_check_missing" in receipt["blockers"]
    assert "magicfit_backend_proof_check_missing" in receipt["blockers"]
    assert "magicfit_account_selection_guidance_missing" in receipt["blockers"]
    assert "magicfit_credit_marker_after_proof_guidance_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_omagic_adapter_proof_gaps(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    adapter = providers["omagic"]["adapter_contract"]
    adapter["render_endpoint_envs"] = []
    adapter["render_command_envs"] = []
    adapter["proof_render_required"] = False
    adapter["proof_render_checks"] = []
    providers["omagic"]["post_refresh_checks"] = [
        "set provider account JSON file mode to 0o600 before merge",
        "merge provider-only OMagic/Magic account JSON with merge_scene_video_provider_accounts_env.py --omagic-accounts-json-file <omagic-accounts.json> --expected-omagic-count 8 --write",
    ]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "omagic_primary_render_endpoint_env_missing" in receipt["blockers"]
    assert "omagic_primary_render_command_env_missing" in receipt["blockers"]
    assert "omagic_proof_render_required_missing" in receipt["blockers"]
    assert "omagic_model_input_consumption_check_missing" in receipt["blockers"]
    assert "omagic_endpoint_config_guidance_missing" in receipt["blockers"]
    assert "omagic_enable_after_proof_guidance_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_weakened_expected_account_counts(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["magicfit"]["expected_account_count"] = 2
    providers["magicfit"]["visible_account_gap"] = 1
    providers["magicfit"]["post_refresh_checks"] = [
        str(value).replace("--expected-magicfit-count 3", "--expected-magicfit-count 2")
        for value in providers["magicfit"]["post_refresh_checks"]
    ]
    providers["omagic"]["expected_account_count"] = 7
    providers["omagic"]["visible_account_gap"] = 7
    providers["omagic"]["post_refresh_checks"] = [
        str(value).replace("--expected-omagic-count 8", "--expected-omagic-count 7")
        for value in providers["omagic"]["post_refresh_checks"]
    ]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "magicfit_expected_account_count_below_required" in receipt["blockers"]
    assert "omagic_expected_account_count_below_required" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_missing_expected_count_guard(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    providers = {row["provider"]: row for row in packet["providers"]}
    providers["magicfit"]["post_refresh_checks"] = [
        "merge provider-only MagicFit account JSON with merge_scene_video_provider_accounts_env.py --magicfit-accounts-json-file <magicfit-accounts.json> --write"
    ]

    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "magicfit_expected_account_count_guard_missing" in receipt["blockers"]


def test_scene_video_provider_refresh_packet_verifier_rejects_missing_safe_merge_script(tmp_path: Path) -> None:
    materializer = _load_script()
    verifier = _load_verifier()

    packet = materializer.build_packet(_receipt(), receipt_path=tmp_path / "receipt.json")
    verifier.ROOT = tmp_path
    receipt = verifier.verify_packet(packet, packet_path=str(tmp_path / "packet.json"))

    assert receipt["status"] == "fail"
    assert "safe_env_merge_script_missing" in receipt["blockers"]
    assert receipt["safe_env_merge_script"] == str(tmp_path / "scripts" / "merge_scene_video_provider_accounts_env.py")


def test_scene_video_provider_refresh_packet_verifier_cli_fails_invalid_packet(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps({"providers": []}), encoding="utf-8")
    script = ROOT / "scripts" / "verify_scene_video_provider_refresh_packet.py"

    result = subprocess.run(
        [sys.executable, str(script), "--packet", str(packet_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    stdout = json.loads(result.stdout)
    assert stdout["status"] == "fail"
    assert "invalid_contract_name" in stdout["blockers"]
    assert "magicfit_provider_missing" in stdout["blockers"]
    assert "omagic_provider_missing" in stdout["blockers"]
