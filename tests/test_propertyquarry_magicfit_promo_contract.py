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
    assert "telegram_helper_missing" in build_script
