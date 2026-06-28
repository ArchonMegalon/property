from __future__ import annotations


def _normalized_provider_token(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return " ".join(normalized.split()).replace(" ", "_")


def normalize_scene_video_contract_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic", "onemin", "onemin_i2v"}:
        return "omagic"
    if normalized == "magicfit":
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic", "onemin", "onemin_i2v"}:
        return "omagic"
    if fallback == "magicfit":
        return "magicfit"
    return fallback or "mootion"


def normalize_scene_video_backend_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if normalized == "magicfit":
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if fallback == "magicfit":
        return "magicfit"
    return fallback or "mootion"
