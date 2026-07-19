from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"
    spec = importlib.util.spec_from_file_location("merge_scene_video_provider_accounts_env", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _accounts(prefix: str, count: int) -> list[dict[str, str]]:
    return [{"email": f"{prefix}{index}@example.test", "password": f"pw-{index}"} for index in range(count)]


def test_scene_video_provider_accounts_env_merge_writes_only_allowlisted_provider_keys(tmp_path: Path) -> None:
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ONEMIN_AI_API_KEY='keep-this'",
                "PROPERTYQUARRY_ONEMIN_I2V_MODEL=veo3",
                "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = module.merge_accounts_env(
        env_file=env_file,
        magicfit_accounts=_accounts("magicfit", 3),
        omagic_accounts=_accounts("omagic", 8),
        expected_magicfit_count=3,
        expected_omagic_count=8,
        magicfit_account_index=0,
        write_magic_alias=True,
        write=True,
    )
    rendered_env = env_file.read_text(encoding="utf-8")
    rendered_receipt = json.dumps(receipt)

    assert receipt["status"] == "pass"
    assert receipt["dry_run"] is False
    assert receipt["backup_path"]
    assert receipt["provider_account_counts"] == {"magicfit": 3, "magic_alias_written": True, "omagic": 8}
    assert set(receipt["updated_keys"]) == {
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
        "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON",
    }
    assert "ONEMIN_AI_API_KEY='keep-this'" in rendered_env
    assert "PROPERTYQUARRY_ONEMIN_I2V_MODEL=veo3" in rendered_env
    assert "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON=" in rendered_env
    assert "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON=" in rendered_env
    assert "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON=" in rendered_env
    assert "magicfit0@example.test" in rendered_env
    assert "omagic7@example.test" in rendered_env
    assert "magicfit0@example.test" not in rendered_receipt
    assert "omagic7@example.test" not in rendered_receipt
    assert receipt["protected_keys_touched"] == []
    assert receipt["protected_line_count"] == 2
    backup_path = Path(receipt["backup_path"])
    assert backup_path.exists()
    assert "ONEMIN_AI_API_KEY='keep-this'" in backup_path.read_text(encoding="utf-8")
    assert "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old'" in backup_path.read_text(encoding="utf-8")
    assert receipt["secure_file_mode"] == "0o600"
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert backup_path.stat().st_mode & 0o777 == 0o600


def test_scene_video_provider_accounts_env_merge_dry_run_preserves_file(tmp_path: Path) -> None:
    module = _load_script()
    env_file = tmp_path / ".env"
    original = "ONEMIN_AI_API_KEY='keep-this'\n"
    env_file.write_text(original, encoding="utf-8")

    receipt = module.merge_accounts_env(
        env_file=env_file,
        magicfit_accounts=_accounts("magicfit", 3),
        omagic_accounts=[],
        expected_magicfit_count=3,
        expected_omagic_count=None,
        magicfit_account_index=None,
        write_magic_alias=True,
        write=False,
    )

    assert receipt["status"] == "pass"
    assert receipt["dry_run"] is True
    assert receipt["backup_path"] == ""
    assert receipt["secure_file_mode"] == "0o600"
    assert receipt["protected_line_count"] == 1
    assert env_file.read_text(encoding="utf-8") == original


def test_scene_video_provider_accounts_env_merge_writes_file_env_targets(tmp_path: Path) -> None:
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    account_dir = tmp_path / "state" / "scene_video_provider_accounts"

    receipt = module.merge_accounts_env(
        env_file=env_file,
        magicfit_accounts=_accounts("magicfit", 3),
        omagic_accounts=_accounts("omagic", 8),
        expected_magicfit_count=3,
        expected_omagic_count=8,
        magicfit_account_index=1,
        write_magic_alias=True,
        write_file_env=True,
        account_file_dir=account_dir,
        write=True,
    )

    rendered_env = env_file.read_text(encoding="utf-8")
    rendered_receipt = json.dumps(receipt)
    magicfit_target = account_dir / "magicfit-accounts.json"
    omagic_target = account_dir / "omagic-accounts.json"

    assert receipt["status"] == "pass"
    assert receipt["write_mode"] == "file_env"
    assert receipt["account_file_dir"] == str(account_dir)
    assert receipt["planned_account_files"] == [str(magicfit_target), str(omagic_target)]
    assert receipt["written_account_files"] == [str(magicfit_target), str(omagic_target)]
    assert receipt["env_account_file_values"] == {
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE": str(magicfit_target),
        "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON_FILE": str(omagic_target),
        "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON_FILE": str(omagic_target),
    }
    assert magicfit_target.exists()
    assert omagic_target.exists()
    assert magicfit_target.stat().st_mode & 0o777 == 0o600
    assert omagic_target.stat().st_mode & 0o777 == 0o600
    assert "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE=" in rendered_env
    assert "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON_FILE=" in rendered_env
    assert "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON_FILE=" in rendered_env
    assert "magicfit0@example.test" not in rendered_receipt
    assert "omagic0@example.test" not in rendered_receipt
    assert json.loads(magicfit_target.read_text(encoding="utf-8"))[0]["email"] == "magicfit0@example.test"
    assert json.loads(omagic_target.read_text(encoding="utf-8"))[0]["email"] == "omagic0@example.test"


def test_scene_video_provider_accounts_env_merge_default_file_env_targets_bridge_runtime_mount(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.delenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    (tmp_path / "docker-compose.property.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    receipt = module.merge_accounts_env(
        env_file=env_file,
        magicfit_accounts=_accounts("magicfit", 3),
        omagic_accounts=[],
        expected_magicfit_count=3,
        expected_omagic_count=None,
        magicfit_account_index=1,
        write_magic_alias=True,
        write_file_env=True,
        write=True,
    )

    account_dir = (tmp_path / "state" / "incoming_property_tours" / "_operator-import-lane" / "scene_video_provider_accounts").resolve()
    host_target = account_dir / "magicfit-accounts.json"
    runtime_target = "/data/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/magicfit-accounts.json"
    rendered_env = env_file.read_text(encoding="utf-8")

    assert receipt["status"] == "pass"
    assert receipt["write_mode"] == "file_env"
    assert receipt["account_file_dir"] == str(account_dir)
    assert receipt["planned_account_files"] == [str(host_target)]
    assert receipt["written_account_files"] == [str(host_target)]
    assert receipt["env_account_file_values"] == {
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE": runtime_target,
    }
    assert host_target.exists()
    assert runtime_target in rendered_env
    assert str(host_target) not in rendered_env


def test_scene_video_provider_accounts_env_merge_file_env_dry_run_reports_targets_without_writing(tmp_path: Path) -> None:
    module = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    account_dir = tmp_path / "state" / "scene_video_provider_accounts"

    receipt = module.merge_accounts_env(
        env_file=env_file,
        magicfit_accounts=_accounts("magicfit", 3),
        omagic_accounts=[],
        expected_magicfit_count=3,
        expected_omagic_count=None,
        magicfit_account_index=None,
        write_magic_alias=True,
        write_file_env=True,
        account_file_dir=account_dir,
        write=False,
    )

    assert receipt["status"] == "pass"
    assert receipt["write_mode"] == "file_env"
    assert receipt["planned_account_files"] == [str(account_dir / "magicfit-accounts.json")]
    assert receipt["written_account_files"] == []
    assert receipt["env_account_file_values"] == {
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE": str(account_dir / "magicfit-accounts.json"),
    }
    assert not (account_dir / "magicfit-accounts.json").exists()
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_refuses_onemin_updates() -> None:
    module = _load_script()

    try:
        module.merge_env_text("", {"ONEMIN_AI_API_KEY": "bad"})
    except ValueError as exc:
        assert "unsupported env keys" in str(exc)
    else:
        raise AssertionError("expected ONEMIN update to be rejected")


def test_scene_video_provider_accounts_env_merge_refuses_duplicate_existing_provider_key() -> None:
    module = _load_script()

    try:
        module.merge_env_text(
            "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old-a'\nPROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old-b'\n",
            {"PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON": "new"},
        )
    except ValueError as exc:
        assert str(exc) == "duplicate provider account env keys in target env: PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"
    else:
        raise AssertionError("expected duplicate provider account env key to be rejected")


def test_scene_video_provider_accounts_env_merge_preserves_existing_export_prefix() -> None:
    module = _load_script()

    rendered, updated_keys = module.merge_env_text(
        "export PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old'\n",
        {"PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON": "new"},
    )

    assert rendered == "export PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='new'\n"
    assert updated_keys == ["PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"]


def test_scene_video_provider_accounts_env_merge_refuses_protected_line_mutation() -> None:
    module = _load_script()

    try:
        module._ensure_protected_env_lines_preserved(
            "ONEMIN_AI_API_KEY='keep-this'\nPROPERTYQUARRY_ONEMIN_I2V_MODEL=veo3\n",
            "ONEMIN_AI_API_KEY='changed'\nPROPERTYQUARRY_ONEMIN_I2V_MODEL=veo3\n",
        )
    except ValueError as exc:
        assert "protected ONEMIN env lines changed" in str(exc)
    else:
        raise AssertionError("expected protected ONEMIN line mutation to be rejected")


def test_scene_video_provider_accounts_env_merge_rejects_magicfit_account_index_without_accounts() -> None:
    module = _load_script()

    try:
        module.build_updates(
            magicfit_accounts=[],
            omagic_accounts=[],
            magicfit_account_index=0,
            write_magic_alias=True,
        )
    except ValueError as exc:
        assert "requires MagicFit accounts" in str(exc)
    else:
        raise AssertionError("expected missing MagicFit accounts to be rejected")


def test_scene_video_provider_accounts_env_merge_rejects_magicfit_account_index_outside_range() -> None:
    module = _load_script()

    try:
        module.build_updates(
            magicfit_accounts=_accounts("magicfit", 3),
            omagic_accounts=[],
            magicfit_account_index=3,
            write_magic_alias=True,
        )
    except ValueError as exc:
        assert "outside available account range 0..2" in str(exc)
    else:
        raise AssertionError("expected out-of-range MagicFit account index to be rejected")


def test_scene_video_provider_accounts_env_merge_cli_rejects_wrong_expected_count(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 2)), encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "does not match expected 3" in stdout["blockers"][0]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_writes_file_env_targets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    account_dir = tmp_path / "state" / "scene_video_provider_accounts"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 3)), encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--magicfit-account-index",
            "1",
            "--write-file-env",
            "--account-file-dir",
            str(account_dir),
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)
    target = account_dir / "magicfit-accounts.json"

    assert result.returncode == 0, result.stderr
    assert stdout["status"] == "pass"
    assert stdout["write_mode"] == "file_env"
    assert stdout["planned_account_files"] == [str(target)]
    assert stdout["written_account_files"] == [str(target)]
    assert stdout["env_account_file_values"] == {
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE": str(target),
    }
    assert target.exists()
    assert target.stat().st_mode & 0o777 == 0o600
    assert "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE=" in env_file.read_text(encoding="utf-8")


def test_scene_video_provider_accounts_env_merge_cli_rejects_duplicate_emails_without_leaking_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(
        json.dumps(
            [
                {"email": "duplicate@example.test", "password": "pw-0"},
                {"email": "DUPLICATE@example.test", "password": "pw-1"},
                {"email": "unique@example.test", "password": "pw-2"},
            ]
        ),
        encoding="utf-8",
    )
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)
    rendered = json.dumps(stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "duplicates an earlier account email" in stdout["blockers"][0]
    assert "duplicate@example.test" not in rendered.lower()
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_insecure_account_json_file_before_write(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 3)), encoding="utf-8")
    accounts_file.chmod(0o644)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "must have mode 0o600 before merge" in stdout["blockers"][0]
    assert "current mode is 0o644" in stdout["blockers"][0]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_insecure_account_json_file_in_dry_run(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 3)), encoding="utf-8")
    accounts_file.chmod(0o644)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "must have mode 0o600 before merge" in stdout["blockers"][0]
    assert "current mode is 0o644" in stdout["blockers"][0]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_duplicate_existing_provider_key_before_write(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    original = (
        "ONEMIN_AI_API_KEY='keep-this'\n"
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old-a'\n"
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON='old-b'\n"
    )
    env_file.write_text(original, encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 3)), encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert stdout["blockers"] == ["duplicate provider account env keys in target env: PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"]
    assert "old-a" not in result.stdout
    assert "old-b" not in result.stdout
    assert env_file.read_text(encoding="utf-8") == original


def test_scene_video_provider_accounts_env_merge_cli_rejects_missing_account_json_file_with_stable_error(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "missing-magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert stdout["blockers"] == [f"{accounts_file} account JSON file not found"]
    assert "Errno" not in result.stdout
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_invalid_json_without_echoing_contents(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text("{not-json and not a credential}", encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert stdout["blockers"] == [f"{accounts_file} account JSON file is not valid JSON"]
    assert "not-json" not in result.stdout
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_missing_file_when_expected_count_is_set(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--expected-omagic-count",
            "8",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "omagic account count 0 does not match expected 8" in stdout["blockers"][0]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_noop_write(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert stdout["blockers"] == ["no provider account updates supplied for --write"]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_omagic_without_magic_alias(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "omagic.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("omagic", 8)), encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--omagic-accounts-json-file",
            str(accounts_file),
            "--expected-omagic-count",
            "8",
            "--no-magic-alias",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert stdout["blockers"] == ["magic alias account env is required when OMagic accounts are supplied"]
    assert "omagic0@example.test" not in json.dumps(stdout)
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"


def test_scene_video_provider_accounts_env_merge_cli_rejects_negative_magicfit_account_index(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    accounts_file = tmp_path / "magicfit.json"
    env_file.write_text("ONEMIN_AI_API_KEY='keep-this'\n", encoding="utf-8")
    accounts_file.write_text(json.dumps(_accounts("magicfit", 3)), encoding="utf-8")
    accounts_file.chmod(0o600)
    script = ROOT / "scripts" / "merge_scene_video_provider_accounts_env.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            str(env_file),
            "--magicfit-accounts-json-file",
            str(accounts_file),
            "--expected-magicfit-count",
            "3",
            "--magicfit-account-index",
            "-1",
            "--write",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = json.loads(result.stdout)

    assert result.returncode == 1
    assert stdout["status"] == "fail"
    assert "outside available account range 0..2" in stdout["blockers"][0]
    assert env_file.read_text(encoding="utf-8") == "ONEMIN_AI_API_KEY='keep-this'\n"
