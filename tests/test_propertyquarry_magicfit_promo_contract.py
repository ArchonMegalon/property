from __future__ import annotations

import json
from pathlib import Path


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


def test_propertyquarry_magicfit_helpers_do_not_read_chummer_credentials() -> None:
    helper_paths = [
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


def test_propertyquarry_release_gates_include_magicfit_promo_contract() -> None:
    release_gate = (ROOT / "scripts" / "property_release_gates.sh").read_text(encoding="utf-8")

    assert "tests/test_propertyquarry_magicfit_promo_contract.py" in release_gate
