from __future__ import annotations

from app.services.scene_video_contract import (
    normalize_scene_video_backend_provider,
    normalize_scene_video_contract_provider,
)


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
