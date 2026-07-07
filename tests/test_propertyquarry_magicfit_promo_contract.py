from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def test_propertyquarry_magicfit_promo_packet_fails_closed() -> None:
    packet = json.loads((ROOT / "docs" / "PROPERTYQUARRY_PROMO_VIDEO_PACKET.json").read_text(encoding="utf-8"))
    strategy = dict(packet.get("render_strategy") or {})
    policy = "\n".join(str(item) for item in strategy.get("policy") or [])

    assert strategy["provider_target"] == "magicfit_only"
    assert strategy["fail_closed_fallback"] == "none"
    assert "Do not use storyboard cards" in policy
    assert "non-MagicFit fallback video generation" in policy
    assert "stop and report the blocker" in policy


def test_propertyquarry_magicfit_promo_brief_matches_fail_closed_lane() -> None:
    brief = (ROOT / "docs" / "PROPERTYQUARRY_PROMO_VIDEO_BRIEF.md").read_text(encoding="utf-8")

    assert "PropertyQuarry promo-video rendering is **MagicFit only**" in brief
    assert "- no storyboard fallback video" in brief
    assert "- no SVG motion-card fallback" in brief
    assert "- no deterministic slide-video replacement" in brief
    assert "stop and report the blocker instead of substituting another render path" in brief


def test_propertyquarry_magicfit_materializers_are_path_configurable() -> None:
    build_script = (ROOT / "scripts" / "build_propertyquarry_magicfit_promo.py").read_text(encoding="utf-8")
    render_script = (ROOT / "scripts" / "magicfit_render_propertyquarry_promo.cjs").read_text(encoding="utf-8")

    assert 'Path("/docker/property")' not in build_script
    assert "'/docker/property" not in render_script
    assert '"/docker/property' not in render_script
    assert "PROPERTYQUARRY_ROOT" in build_script
    assert "PROPERTYQUARRY_ROOT" in render_script
    assert "PROPERTYQUARRY_PROMO_OUT_DIR" in build_script
    assert "PROPERTYQUARRY_MAGICFIT_CLIPS_DIR" in render_script
    assert "PROPERTYQUARRY_PROMO_PACKET" in build_script
    assert "PROPERTYQUARRY_PROMO_TELEGRAM_HELPER" in build_script
    assert "telegram_helper_required:PROPERTYQUARRY_PROMO_TELEGRAM_HELPER" in build_script
    assert "telegram_helper_missing" in build_script
    assert "PROPERTYQUARRY_PROMO_VARIANT" in build_script
    assert "VARIANT = safe_variant" in build_script
    assert "PROPERTYQUARRY_PROMO_SILENT_VIDEO" in build_script
    assert "PROPERTYQUARRY_UNMIXR_VOICE_ID" in build_script
    assert "invalid_propertyquarry_unmixr_intensity" in build_script
    assert "/docker/chummercomplete" not in build_script
    assert "chummer.run-services" not in build_script
    assert "_completion/telegram_promo_delivery" not in build_script


def test_propertyquarry_magicfit_renderer_fails_fast_on_credit_blocker() -> None:
    render_script = (ROOT / "scripts" / "render_magicfit_property_flythrough.py").read_text(encoding="utf-8")

    assert "magicfit_not_enough_credits" in render_script
    assert "Not enough credits" not in render_script
    assert "not enough credits" in render_script
    assert "/docker/chummercomplete" not in render_script
    assert "CHUMMER_EA_MAGICFIT" not in render_script
    assert "PROPERTYQUARRY_MAGICFIT_EMAIL" in render_script
    assert "PROPERTYQUARRY_MAGICFIT_PASSWORD" in render_script
    assert "MAGICFIT_DEBUG_DIR" in render_script
    assert "write_debug_snapshot(page" in render_script


def test_propertyquarry_magicfit_renderer_receipt_binds_to_property_slug() -> None:
    render_script = (ROOT / "scripts" / "render_magicfit_property_flythrough.py").read_text(encoding="utf-8")

    assert "--property-slug" in render_script
    assert "--property-title" in render_script
    assert "--property-url" in render_script
    assert '"target_slug": str(args.property_slug or "").strip()' in render_script
    assert '"property_slug": str(args.property_slug or "").strip()' in render_script
    assert '"provider_backend_key": "magicfit"' in render_script
    assert '"render_status": "completed"' in render_script
    assert '"hosted_walkthrough_video_url": video_url' in render_script


def _load_magicfit_env_helper() -> ModuleType:
    path = ROOT / "scripts" / "property_magicfit_env.py"
    spec = importlib.util.spec_from_file_location("property_magicfit_env", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_propertyquarry_magicfit_env_selects_account_json_without_chummer_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_magicfit_env_helper()
    for key in (
        "PROPERTYQUARRY_MAGICFIT_EMAIL",
        "PROPERTYQUARRY_MAGICFIT_PASSWORD",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
        "MAGICFIT_EMAIL",
        "MAGICFIT_PASSWORD",
        "MAGICFIT_ACCOUNTS_JSON",
        "MAGICFIT_ACCOUNT_INDEX",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAGICFIT_ACCOUNT_INDEX=2\n"
        "MAGICFIT_ACCOUNTS_JSON="
        + json.dumps(
            [
                {"email": "magicfit-one@example.test", "password": "secret-one"},
                {"email": "magicfit-two@example.test", "password": "secret-two"},
                {"email": "magicfit-three@example.test", "password": "secret-three"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    values, sources = module.discover_magicfit_env([env_file])

    assert values["PROPERTYQUARRY_MAGICFIT_EMAIL"] == "magicfit-two@example.test"
    assert values["PROPERTYQUARRY_MAGICFIT_PASSWORD"] == "secret-two"
    assert values["MAGICFIT_EMAIL"] == "magicfit-two@example.test"
    assert values["MAGICFIT_PASSWORD"] == "secret-two"
    assert "MAGICFIT_ACCOUNTS_JSON[2]" in sources["PROPERTYQUARRY_MAGICFIT_EMAIL"]


def test_propertyquarry_magicfit_env_selects_account_json_file_without_chummer_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_magicfit_env_helper()
    for key in (
        "PROPERTYQUARRY_MAGICFIT_EMAIL",
        "PROPERTYQUARRY_MAGICFIT_PASSWORD",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
        "MAGICFIT_EMAIL",
        "MAGICFIT_PASSWORD",
        "MAGICFIT_ACCOUNTS_JSON",
        "MAGICFIT_ACCOUNTS_JSON_FILE",
        "MAGICFIT_ACCOUNT_INDEX",
    ):
        monkeypatch.delenv(key, raising=False)
    accounts_file = tmp_path / "magicfit-accounts.json"
    accounts_file.write_text(
        json.dumps(
            [
                {"email": "magicfit-one@example.test", "password": "secret-one"},
                {"email": "magicfit-two@example.test", "password": "secret-two"},
                {"email": "magicfit-three@example.test", "password": "secret-three"},
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAGICFIT_ACCOUNT_INDEX=3\n"
        f"MAGICFIT_ACCOUNTS_JSON_FILE={accounts_file}\n",
        encoding="utf-8",
    )

    values, sources = module.discover_magicfit_env([env_file])

    assert values["PROPERTYQUARRY_MAGICFIT_EMAIL"] == "magicfit-three@example.test"
    assert values["PROPERTYQUARRY_MAGICFIT_PASSWORD"] == "secret-three"
    assert values["MAGICFIT_EMAIL"] == "magicfit-three@example.test"
    assert values["MAGICFIT_PASSWORD"] == "secret-three"
    assert "MAGICFIT_ACCOUNTS_JSON_FILE[3]" in sources["PROPERTYQUARRY_MAGICFIT_EMAIL"]


def test_propertyquarry_magicfit_env_prefers_account_json_file_over_inline_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_magicfit_env_helper()
    for key in (
        "PROPERTYQUARRY_MAGICFIT_EMAIL",
        "PROPERTYQUARRY_MAGICFIT_PASSWORD",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
        "MAGICFIT_EMAIL",
        "MAGICFIT_PASSWORD",
        "MAGICFIT_ACCOUNTS_JSON",
        "MAGICFIT_ACCOUNTS_JSON_FILE",
        "MAGICFIT_ACCOUNT_INDEX",
    ):
        monkeypatch.delenv(key, raising=False)
    accounts_file = tmp_path / "magicfit-accounts.json"
    accounts_file.write_text(json.dumps([{"email": "file@example.test", "password": "secret-file"}]), encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAGICFIT_ACCOUNT_INDEX=1\n"
        "MAGICFIT_ACCOUNTS_JSON="
        + json.dumps([{"email": "inline@example.test", "password": "secret-inline"}])
        + "\n"
        + f"MAGICFIT_ACCOUNTS_JSON_FILE={accounts_file}\n",
        encoding="utf-8",
    )

    values, sources = module.discover_magicfit_env([env_file])

    assert values["PROPERTYQUARRY_MAGICFIT_EMAIL"] == "file@example.test"
    assert values["PROPERTYQUARRY_MAGICFIT_PASSWORD"] == "secret-file"
    assert "MAGICFIT_ACCOUNTS_JSON_FILE[1]" in sources["PROPERTYQUARRY_MAGICFIT_EMAIL"]


def test_propertyquarry_magicfit_env_resolves_runtime_mount_accounts_json_file_on_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_magicfit_env_helper()
    for key in (
        "PROPERTYQUARRY_MAGICFIT_EMAIL",
        "PROPERTYQUARRY_MAGICFIT_PASSWORD",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE",
        "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
        "MAGICFIT_EMAIL",
        "MAGICFIT_PASSWORD",
        "MAGICFIT_ACCOUNTS_JSON",
        "MAGICFIT_ACCOUNTS_JSON_FILE",
        "MAGICFIT_ACCOUNT_INDEX",
        "PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR",
        "PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_ROOT", str(tmp_path))
    accounts_file = (
        tmp_path
        / "state"
        / "incoming_property_tours"
        / "_operator-import-lane"
        / "scene_video_provider_accounts"
        / "magicfit-accounts.json"
    )
    accounts_file.parent.mkdir(parents=True, exist_ok=True)
    accounts_file.write_text(
        json.dumps(
            [
                {"email": "magicfit-one@example.test", "password": "secret-one"},
                {"email": "magicfit-two@example.test", "password": "secret-two"},
                {"email": "magicfit-three@example.test", "password": "secret-three"},
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAGICFIT_ACCOUNT_INDEX=2\n"
        "MAGICFIT_ACCOUNTS_JSON_FILE=/data/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts/magicfit-accounts.json\n",
        encoding="utf-8",
    )

    values, sources = module.discover_magicfit_env([env_file])

    assert values["PROPERTYQUARRY_MAGICFIT_EMAIL"] == "magicfit-two@example.test"
    assert values["PROPERTYQUARRY_MAGICFIT_PASSWORD"] == "secret-two"
    assert values["MAGICFIT_EMAIL"] == "magicfit-two@example.test"
    assert values["MAGICFIT_PASSWORD"] == "secret-two"
    assert "MAGICFIT_ACCOUNTS_JSON_FILE[2]" in sources["PROPERTYQUARRY_MAGICFIT_EMAIL"]


def test_propertyquarry_magicfit_helpers_do_not_read_chummer_credentials() -> None:
    helper_paths = [
        ROOT / "scripts" / "property_magicfit_env.py",
        ROOT / "scripts" / "render_magicfit_property_flythrough.py",
        ROOT / "scripts" / "diagnose_magicfit_video_ui.py",
        ROOT / "scripts" / "inspect_magicfit_session_assets.py",
        ROOT / "scripts" / "diagnose_magicfit_extend_ui.py",
        ROOT / "scripts" / "magicfit_render_propertyquarry_promo.cjs",
        ROOT / "scripts" / "materialize_magicfit_provider_completion.py",
        ROOT / "scripts" / "verify_magicfit_provider.py",
        ROOT / "scripts" / "render_onemin_property_i2v_segment.py",
    ]
    for path in helper_paths:
        body = path.read_text(encoding="utf-8")
        assert "CHUMMER_EA_MAGICFIT" not in body, str(path)
        assert "chummer.run-services/.env" not in body, str(path)


def test_propertyquarry_magicfit_helpers_do_not_default_to_real_account_emails() -> None:
    helper_paths = [
        ROOT / "scripts" / "property_magicfit_env.py",
        ROOT / "scripts" / "render_magicfit_property_flythrough.py",
        ROOT / "scripts" / "diagnose_magicfit_video_ui.py",
        ROOT / "scripts" / "inspect_magicfit_session_assets.py",
        ROOT / "scripts" / "diagnose_magicfit_extend_ui.py",
        ROOT / "scripts" / "materialize_magicfit_provider_completion.py",
        ROOT / "scripts" / "verify_magicfit_provider.py",
    ]
    forbidden = (
        "tibor.girschele@gmail.com",
        "the.girscheles@gmail.com",
    )
    for path in helper_paths:
        body = path.read_text(encoding="utf-8")
        for account in forbidden:
            assert account not in body, str(path)


def test_propertyquarry_release_gates_include_magicfit_promo_contract() -> None:
    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")

    assert "tests/test_propertyquarry_magicfit_promo_contract.py" in release_gate
