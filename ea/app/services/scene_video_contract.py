from __future__ import annotations

import importlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _normalized_provider_token(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return " ".join(normalized.split()).replace(" ", "_")


def resolve_scene_video_script_path(script_name: object) -> Path:
    safe_name = Path(str(script_name or "").strip()).name
    if not safe_name:
        return Path("/docker/property/scripts")
    roots: list[Path] = []
    for raw_root in (os.getenv("EA_REPO_ROOT"), os.getenv("PROPERTYQUARRY_REPO_ROOT"), "/app", "/docker/property"):
        value = str(raw_root or "").strip()
        if value:
            roots.append(Path(value).expanduser())
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts").exists():
            roots.append(parent)
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        candidate = (root / "scripts" / safe_name).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path("/docker/property/scripts") / safe_name


def _scene_video_env_has_any(*names: str) -> bool:
    return any(str(os.getenv(name) or "").strip() for name in names)


def _scene_video_float(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _scene_video_timestamp(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        pass
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _scene_video_onemin_i2v_min_required_credits() -> int:
    for name in ("EA_SCENE_VIDEO_ONEMIN_I2V_MIN_REQUIRED_CREDITS", "PROPERTYQUARRY_SCENE_VIDEO_ONEMIN_I2V_MIN_REQUIRED_CREDITS"):
        raw = str(os.getenv(name) or "").strip()
        if not raw:
            continue
        try:
            parsed = int(float(raw))
        except Exception:
            continue
        if parsed > 0:
            return parsed
    return 450000


def _scene_video_onemin_slot_remaining(slot: dict[str, object]) -> tuple[float | None, str]:
    error_remaining = _scene_video_float(slot.get("remaining_credits"))
    billing_remaining = None if bool(slot.get("billing_team_mismatch")) else _scene_video_float(slot.get("billing_remaining_credits"))
    estimated_remaining = _scene_video_float(slot.get("estimated_remaining_credits"))
    failure_at = _scene_video_timestamp(slot.get("last_failure_at"))
    billing_at = _scene_video_timestamp(slot.get("last_billing_snapshot_at"))
    if error_remaining is not None and (
        billing_remaining is None
        or (
            failure_at is not None
            and (billing_at is None or failure_at >= billing_at)
        )
    ):
        return error_remaining, "observed_error"
    if billing_remaining is not None:
        return billing_remaining, "actual_billing"
    if error_remaining is not None:
        return error_remaining, "observed_error"
    if estimated_remaining is not None:
        return estimated_remaining, str(slot.get("estimated_credit_basis") or "estimated")
    return None, "unknown"


def _scene_video_onemin_credit_readiness() -> dict[str, object]:
    minimum_required_credits = _scene_video_onemin_i2v_min_required_credits()
    try:
        upstream = importlib.import_module("app.services.responses_upstream")
        provider_health = upstream._provider_health_report(lightweight=True)
    except Exception as exc:  # noqa: BLE001
        return {
            "credit_state": "unverified",
            "credit_probe_source": "provider_health_error",
            "minimum_required_credits": minimum_required_credits,
            "credit_probe_error": str(exc or exc.__class__.__name__)[:240],
        }
    provider = dict(((provider_health.get("providers") or {}).get("onemin") or {}))
    raw_slots = provider.get("slots") or []
    configured_slots = [
        dict(slot)
        for slot in raw_slots
        if isinstance(slot, dict) and slot.get("configured") is not False
    ]
    slot_summaries: list[dict[str, object]] = []
    funded_slot_count = 0
    known_balance_slot_count = 0
    for slot in configured_slots:
        remaining_credits, remaining_basis = _scene_video_onemin_slot_remaining(slot)
        if remaining_credits is not None:
            known_balance_slot_count += 1
            if remaining_credits >= minimum_required_credits:
                funded_slot_count += 1
        slot_summaries.append(
            {
                "slot": str(slot.get("slot") or slot.get("slot_name") or "").strip(),
                "account_name": str(slot.get("account_name") or "").strip(),
                "state": str(slot.get("state") or "").strip(),
                "remaining_credits": remaining_credits,
                "remaining_basis": remaining_basis,
                "required_credits": slot.get("required_credits"),
                "credit_subject": str(slot.get("credit_subject") or "").strip(),
                "last_failure_at": slot.get("last_failure_at"),
                "last_billing_snapshot_at": slot.get("last_billing_snapshot_at"),
                "billing_next_topup_at": slot.get("billing_next_topup_at"),
            }
        )
    unknown_balance_slot_count = max(0, len(configured_slots) - known_balance_slot_count)
    if funded_slot_count > 0:
        credit_state = "funded"
    elif configured_slots and known_balance_slot_count == len(configured_slots):
        credit_state = "insufficient"
    elif known_balance_slot_count > 0:
        credit_state = "constrained"
    else:
        credit_state = "unprobed"
    return {
        "credit_state": credit_state,
        "credit_probe_source": "provider_health",
        "minimum_required_credits": minimum_required_credits,
        "configured_slot_count": len(configured_slots),
        "known_balance_slot_count": known_balance_slot_count,
        "unknown_balance_slot_count": unknown_balance_slot_count,
        "funded_slot_count": funded_slot_count,
        "live_dispatchable_slot_count": provider.get("live_dispatchable_slot_count"),
        "estimated_remaining_credits_total": provider.get("estimated_remaining_credits_total"),
        "actual_remaining_credits_total": provider.get("actual_remaining_credits_total"),
        "hard_dispatchable_required_credits": provider.get("hard_dispatchable_required_credits"),
        "slots": slot_summaries[:8],
    }


def scene_video_provider_runtime_readiness(provider_key: object) -> dict[str, object]:
    contract_provider_key = normalize_scene_video_contract_provider(provider_key, default="mootion")
    backend_provider_key = normalize_scene_video_backend_provider(provider_key, default="mootion")
    checks: dict[str, object] = {}
    blockers: list[str] = []
    if contract_provider_key == "magicfit":
        script_path = resolve_scene_video_script_path("render_magicfit_property_flythrough.py")
        credentials_ready = _scene_video_env_has_any("PROPERTYQUARRY_MAGICFIT_EMAIL", "MAGICFIT_EMAIL") and _scene_video_env_has_any(
            "PROPERTYQUARRY_MAGICFIT_PASSWORD",
            "MAGICFIT_PASSWORD",
        )
        checks = {
            "script_path": str(script_path),
            "script_exists": script_path.exists(),
            "credentials_configured": credentials_ready,
        }
        if not checks["script_exists"]:
            blockers.append("magicfit_script_missing")
        if not credentials_ready:
            blockers.append("magicfit_credentials_missing")
    elif contract_provider_key == "omagic":
        key_ready = _scene_video_env_has_any("ONEMIN_AI_API_KEY", "ONEMIN_DIRECT_API_KEYS_JSON", "ONEMIN_DIRECT_API_KEYS_JSON_FILE") or any(
            key.startswith("ONEMIN_AI_API_KEY_FALLBACK_") and str(value or "").strip()
            for key, value in os.environ.items()
        )
        credit_readiness = _scene_video_onemin_credit_readiness() if key_ready else {
            "credit_state": "unprobed",
            "minimum_required_credits": _scene_video_onemin_i2v_min_required_credits(),
        }
        checks = {
            "api_key_configured": key_ready,
            **credit_readiness,
        }
        if not key_ready:
            blockers.append("onemin_i2v_api_key_missing")
        if credit_readiness.get("credit_state") == "insufficient":
            blockers.append("onemin_i2v_insufficient_credits")
    elif contract_provider_key == "mootion":
        script_path = resolve_scene_video_script_path("mootion_movie_worker.py")
        docker_cli_path = shutil.which("docker") or ""
        checks = {
            "script_path": str(script_path),
            "script_exists": script_path.exists(),
            "docker_cli_configured": bool(docker_cli_path),
            "docker_cli_path": docker_cli_path,
        }
        if not checks["script_exists"]:
            blockers.append("mootion_worker_script_missing")
        if not docker_cli_path:
            blockers.append("mootion_docker_cli_missing")
    ready = not blockers
    return {
        "provider_key": contract_provider_key,
        "provider_backend_key": backend_provider_key,
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "blockers": blockers,
        "checks": checks,
    }


def normalize_scene_video_contract_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic", "one_min", "onemin", "onemin_i2v", "1min", "1min_ai"}:
        return "omagic"
    if normalized in {"magicfit", "magic_fit"}:
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic", "one_min", "onemin", "onemin_i2v", "1min", "1min_ai"}:
        return "omagic"
    if fallback in {"magicfit", "magic_fit"}:
        return "magicfit"
    return fallback or "mootion"


def normalize_scene_video_backend_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic", "one_min", "onemin", "onemin_i2v", "1min", "1min_ai"}:
        return "onemin_i2v"
    if normalized in {"magicfit", "magic_fit"}:
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic", "one_min", "onemin", "onemin_i2v", "1min", "1min_ai"}:
        return "onemin_i2v"
    if fallback in {"magicfit", "magic_fit"}:
        return "magicfit"
    return fallback or "mootion"
