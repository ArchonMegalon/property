from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_SCENE_VIDEO_RUNTIME_INCOMING_ROOT = Path("/data/incoming_property_tours")
_SCENE_VIDEO_BLOCKED_ENV_PREFIXES = ("CHUMMER_EA_",)


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


def _scene_video_blocked_env_name(name: str) -> bool:
    return any(str(name or "").startswith(prefix) for prefix in _SCENE_VIDEO_BLOCKED_ENV_PREFIXES)


def _scene_video_matching_env_names(*names: str) -> list[str]:
    configured: list[str] = []
    seen: set[str] = set()
    normalized_names = [str(name or "").strip() for name in names if str(name or "").strip()]
    for name in normalized_names:
        if str(os.getenv(name) or "").strip() and name not in seen:
            configured.append(name)
            seen.add(name)
    for env_name, raw_value in sorted(os.environ.items()):
        if _scene_video_blocked_env_name(env_name):
            continue
        if not str(raw_value or "").strip():
            continue
        if env_name in seen:
            continue
        if any(env_name.endswith(f"_{suffix}") for suffix in normalized_names):
            configured.append(env_name)
            seen.add(env_name)
    return configured


def _scene_video_is_runtime_incoming_path(path: Path) -> bool:
    normalized = str(path).strip()
    runtime_root = str(_SCENE_VIDEO_RUNTIME_INCOMING_ROOT)
    return normalized == runtime_root or normalized.startswith(f"{runtime_root}/")


def _scene_video_host_incoming_root() -> Path:
    configured = str(
        os.getenv("PROPERTYQUARRY_TOUR_EXPORT_INCOMING_DIR")
        or os.getenv("PROPERTYQUARRY_TOUR_EXPORT_DROP_DIR")
        or ""
    ).strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if not _scene_video_is_runtime_incoming_path(configured_path):
            return configured_path
    repo_root = Path(
        os.getenv("PROPERTYQUARRY_REPO_ROOT")
        or os.getenv("PROPERTYQUARRY_ROOT")
        or os.getenv("EA_REPO_ROOT")
        or "/docker/property"
    ).expanduser()
    return repo_root / "state" / "incoming_property_tours"


def _scene_video_resolve_accounts_json_file_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_file() or not _scene_video_is_runtime_incoming_path(path):
        return path
    try:
        relative = path.relative_to(_SCENE_VIDEO_RUNTIME_INCOMING_ROOT)
    except ValueError:
        return path
    return _scene_video_host_incoming_root() / relative


def _scene_video_account_rows_from_sources(
    *,
    inline_env_names: tuple[str, ...],
    file_env_names: tuple[str, ...],
) -> list[tuple[str, int, dict[str, object]]]:
    rows: list[tuple[str, int, dict[str, object]]] = []
    seen_sources: set[tuple[str, int]] = set()

    def _append_rows(source_env_name: str, raw_accounts: str) -> None:
        if not raw_accounts:
            return
        try:
            loaded_accounts = json.loads(raw_accounts)
        except Exception:
            return
        if not isinstance(loaded_accounts, list):
            return
        for index, row in enumerate(loaded_accounts, start=1):
            if not isinstance(row, dict):
                continue
            source_key = (source_env_name, index)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            rows.append((source_env_name, index, row))

    for env_name in _scene_video_matching_env_names(*file_env_names):
        file_path = _scene_video_resolve_accounts_json_file_path(str(os.getenv(env_name) or "").strip())
        if not file_path.is_file():
            continue
        try:
            raw_accounts = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        _append_rows(env_name, raw_accounts)

    for env_name in _scene_video_matching_env_names(*inline_env_names):
        _append_rows(env_name, str(os.getenv(env_name) or "").strip())

    return rows


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


def _scene_video_provider_ledger_dir() -> Path:
    raw_path = str(
        os.getenv("EA_RESPONSES_PROVIDER_LEDGER_DIR")
        or os.getenv("PROPERTYQUARRY_PROVIDER_LEDGER_DIR")
        or "/data/provider-ledger"
    ).strip()
    return Path(raw_path or "/data/provider-ledger").expanduser()


def _scene_video_magicfit_credit_marker_path() -> Path:
    return _scene_video_provider_ledger_dir() / "scene_video_magicfit_readiness.json"


def _scene_video_magicfit_runtime_account_pairs() -> tuple[dict[str, str], ...]:
    pairs: list[dict[str, str]] = []
    seen_emails: set[str] = set()

    def _add_pair(*, email_value: object, email_env_name: str, password_env_name: str, password_value: object = None) -> None:
        email_text = str(email_value or "").strip()
        if not email_text:
            return
        if password_value is None:
            password_text = str(os.getenv(password_env_name) or "").strip()
        else:
            password_text = str(password_value or "").strip()
        if not password_env_name or not password_text:
            return
        email_key = email_text.lower()
        if email_key in seen_emails:
            return
        seen_emails.add(email_key)
        pairs.append(
            {
                "email_env_name": email_env_name,
                "password_env_name": password_env_name,
            }
        )

    for accounts_env_name, index, row in _scene_video_account_rows_from_sources(
        inline_env_names=(
            "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
            "MAGICFIT_ACCOUNTS_JSON",
        ),
        file_env_names=(
            "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON_FILE",
            "MAGICFIT_ACCOUNTS_JSON_FILE",
        ),
    ):
        email_env_name = str(row.get("email_env_name") or f"{accounts_env_name}[{index}].email").strip()
        password_env_name = str(row.get("password_env_name") or f"{accounts_env_name}[{index}].password").strip()
        _add_pair(
            email_value=row.get("email") or row.get("username"),
            email_env_name=email_env_name,
            password_env_name=password_env_name,
            password_value=row.get("password"),
        )

    for email_env_name, raw_email in sorted(os.environ.items()):
        if _scene_video_blocked_env_name(email_env_name):
            continue
        if (
            email_env_name not in {"MAGICFIT_EMAIL", "PROPERTYQUARRY_MAGICFIT_EMAIL"}
            and not email_env_name.endswith("_MAGICFIT_EMAIL")
            and "_MAGICFIT_" not in email_env_name
            and not email_env_name.startswith("MAGICFIT_")
        ):
            continue
        if not (email_env_name.endswith("_EMAIL") or "_EMAIL_" in email_env_name):
            continue
        password_env_name = f"{email_env_name[:-len('_EMAIL')]}_PASSWORD" if email_env_name.endswith("_EMAIL") else email_env_name.replace("_EMAIL_", "_PASSWORD_", 1)
        _add_pair(email_value=raw_email, email_env_name=email_env_name, password_env_name=password_env_name)
    return tuple(pairs)


def _scene_video_omagic_runtime_account_pairs() -> tuple[dict[str, str], ...]:
    pairs: list[dict[str, str]] = []
    seen_emails: set[str] = set()

    def _add_pair(*, email_value: object, email_env_name: str, password_env_name: str, password_value: object = None) -> None:
        email_text = str(email_value or "").strip()
        if not email_text:
            return
        if password_value is None:
            password_text = str(os.getenv(password_env_name) or "").strip()
        else:
            password_text = str(password_value or "").strip()
        if not password_env_name or not password_text:
            return
        email_key = email_text.lower()
        if email_key in seen_emails:
            return
        seen_emails.add(email_key)
        pairs.append(
            {
                "email_env_name": email_env_name,
                "password_env_name": password_env_name,
            }
        )

    for accounts_env_name, index, row in _scene_video_account_rows_from_sources(
        inline_env_names=(
            "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON",
            "OMAGIC_ACCOUNTS_JSON",
            "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON",
            "MAGIC_ACCOUNTS_JSON",
        ),
        file_env_names=(
            "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON_FILE",
            "OMAGIC_ACCOUNTS_JSON_FILE",
            "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON_FILE",
            "MAGIC_ACCOUNTS_JSON_FILE",
        ),
    ):
        email_env_name = str(row.get("email_env_name") or f"{accounts_env_name}[{index}].email").strip()
        password_env_name = str(row.get("password_env_name") or f"{accounts_env_name}[{index}].password").strip()
        _add_pair(
            email_value=row.get("email") or row.get("username") or row.get("login"),
            email_env_name=email_env_name,
            password_env_name=password_env_name,
            password_value=row.get("password") or row.get("pass"),
        )

    explicit_email_env_names = {
        "OMAGIC_EMAIL",
        "PROPERTYQUARRY_OMAGIC_EMAIL",
        "MAGIC_EMAIL",
        "PROPERTYQUARRY_MAGIC_EMAIL",
    }
    for email_env_name, raw_email in sorted(os.environ.items()):
        if _scene_video_blocked_env_name(email_env_name):
            continue
        if (
            email_env_name not in explicit_email_env_names
            and not email_env_name.endswith("_OMAGIC_EMAIL")
            and not email_env_name.endswith("_MAGIC_EMAIL")
            and "_OMAGIC_" not in email_env_name
            and "_MAGIC_" not in email_env_name
            and not email_env_name.startswith("OMAGIC_")
            and not email_env_name.startswith("MAGIC_")
        ):
            continue
        if not (email_env_name.endswith("_EMAIL") or "_EMAIL_" in email_env_name):
            continue
        password_env_name = f"{email_env_name[:-len('_EMAIL')]}_PASSWORD" if email_env_name.endswith("_EMAIL") else email_env_name.replace("_EMAIL_", "_PASSWORD_", 1)
        _add_pair(email_value=raw_email, email_env_name=email_env_name, password_env_name=password_env_name)
    return tuple(pairs)


def _scene_video_truthy_env(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _scene_video_configured_env_names(*names: str) -> list[str]:
    return _scene_video_matching_env_names(*names)


def record_scene_video_magicfit_failure(reason: object, detail: object = "") -> dict[str, object] | None:
    combined = f"{reason or ''} {detail or ''}".lower()
    if "magicfit_not_enough_credits" not in combined and "not enough credit" not in combined:
        return None
    observed_at = datetime.now(timezone.utc).isoformat()
    marker = {
        "provider_key": "magicfit",
        "status": "blocked",
        "blocker": "magicfit_insufficient_credits",
        "reason": "magicfit_not_enough_credits",
        "source": "render_failure",
        "observed_at": observed_at,
    }
    marker_path = _scene_video_magicfit_credit_marker_path()
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = marker_path.with_name(f"{marker_path.name}.tmp")
        tmp_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
        tmp_path.replace(marker_path)
    except Exception:
        return None
    return {**marker, "marker_path": str(marker_path)}


def _scene_video_magicfit_credit_readiness(*, runtime_account_count: int = 0) -> dict[str, object]:
    marker_path = _scene_video_magicfit_credit_marker_path()
    base = {
        "credit_probe_source": "render_failure_marker",
        "credit_marker_path": str(marker_path),
    }
    if _scene_video_truthy_env("PROPERTYQUARRY_MAGICFIT_IGNORE_CREDIT_MARKER"):
        return {**base, "credit_state": "ignored"}
    if not marker_path.exists():
        return {**base, "credit_state": "unprobed"}
    try:
        loaded = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "credit_state": "unverified",
            "credit_probe_error": str(exc or exc.__class__.__name__)[:240],
        }
    if not isinstance(loaded, dict):
        return {**base, "credit_state": "unverified", "credit_probe_error": "invalid_marker"}
    blocker = str(loaded.get("blocker") or "").strip()
    reason = str(loaded.get("reason") or "").strip()
    if blocker == "magicfit_insufficient_credits" or "magicfit_not_enough_credits" in reason.lower():
        if runtime_account_count > 1:
            return {
                **base,
                "credit_state": "constrained",
                "blocked_account_count": 1,
                "unverified_account_count": max(0, runtime_account_count - 1),
                "last_failure_at": loaded.get("observed_at"),
                "last_failure_reason": reason[:160] or "magicfit_not_enough_credits",
            }
        return {
            **base,
            "credit_state": "insufficient",
            "last_failure_at": loaded.get("observed_at"),
            "last_failure_reason": reason[:160] or "magicfit_not_enough_credits",
        }
    return {
        **base,
        "credit_state": "unverified",
        "last_failure_at": loaded.get("observed_at"),
        "last_failure_reason": reason[:160],
    }


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


def _scene_video_docker_daemon_readiness(docker_cli_path: str) -> tuple[bool, str]:
    normalized_path = str(docker_cli_path or "").strip()
    if not normalized_path:
        return False, "docker_cli_missing"
    try:
        completed = subprocess.run(
            [normalized_path, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc or exc.__class__.__name__)[:240]
    detail = str(completed.stdout or completed.stderr or "").strip()
    return int(completed.returncode or 0) == 0, detail[:240]


def _scene_video_docker_socket_readiness() -> tuple[bool, str, str]:
    docker_host = str(os.getenv("DOCKER_HOST") or "").strip()
    if docker_host and not docker_host.startswith("unix://"):
        return True, docker_host, "docker_host_configured"
    socket_path = docker_host.removeprefix("unix://") if docker_host.startswith("unix://") else "/var/run/docker.sock"
    if not socket_path:
        socket_path = "/var/run/docker.sock"
    ready = Path(socket_path).exists()
    return ready, socket_path, "docker_socket_ready" if ready else "docker_socket_missing"


def scene_video_provider_runtime_readiness(provider_key: object) -> dict[str, object]:
    contract_provider_key = normalize_scene_video_contract_provider(provider_key, default="mootion")
    backend_provider_key = normalize_scene_video_backend_provider(provider_key, default="mootion")
    checks: dict[str, object] = {}
    blockers: list[str] = []
    if contract_provider_key == "magicfit":
        script_path = resolve_scene_video_script_path("render_magicfit_property_flythrough.py")
        runtime_account_pairs = _scene_video_magicfit_runtime_account_pairs()
        credentials_ready = bool(runtime_account_pairs)
        credit_readiness = _scene_video_magicfit_credit_readiness(runtime_account_count=len(runtime_account_pairs))
        checks = {
            "script_path": str(script_path),
            "script_exists": script_path.exists(),
            "credentials_configured": credentials_ready,
            "runtime_account_count": len(runtime_account_pairs),
            "runtime_account_email_env_names": [row["email_env_name"] for row in runtime_account_pairs],
            **credit_readiness,
        }
        if not checks["script_exists"]:
            blockers.append("magicfit_script_missing")
        if not credentials_ready:
            blockers.append("magicfit_credentials_missing")
        if credit_readiness.get("credit_state") == "insufficient":
            blockers.append("magicfit_insufficient_credits")
    elif contract_provider_key == "omagic":
        script_path = resolve_scene_video_script_path("render_omagic_property_model_walkthrough.py")
        runtime_account_pairs = _scene_video_omagic_runtime_account_pairs()
        adapter_enabled = _scene_video_truthy_env("PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED")
        endpoint_env_names = _scene_video_configured_env_names(
            "PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT",
            "OMAGIC_RENDER_ENDPOINT",
            "PROPERTYQUARRY_MAGIC_RENDER_ENDPOINT",
            "MAGIC_RENDER_ENDPOINT",
        )
        command_env_names = _scene_video_configured_env_names(
            "PROPERTYQUARRY_OMAGIC_RENDER_COMMAND",
            "OMAGIC_RENDER_COMMAND",
            "PROPERTYQUARRY_MAGIC_RENDER_COMMAND",
            "MAGIC_RENDER_COMMAND",
        )
        adapter_target_configured = bool(endpoint_env_names or command_env_names)
        api_key_env_names = _scene_video_matching_env_names(
            "PROPERTYQUARRY_OMAGIC_API_KEY",
            "OMAGIC_API_KEY",
            "PROPERTYQUARRY_MAGIC_API_KEY",
            "MAGIC_API_KEY",
        )
        credentials_ready = bool(runtime_account_pairs or api_key_env_names)
        account_config_env_names = (
            "OMAGIC_ACCOUNTS_JSON",
            "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON",
            "MAGIC_ACCOUNTS_JSON",
            "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON",
            "OMAGIC_ACCOUNTS_JSON_FILE",
            "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON_FILE",
            "MAGIC_ACCOUNTS_JSON_FILE",
            "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON_FILE",
        )
        checks = {
            "public_provider_key": "omagic",
            "backend_adapter_key": "omagic",
            "account_config_scope": "omagic_only_config",
            "script_path": str(script_path),
            "script_exists": script_path.exists(),
            "credentials_configured": credentials_ready,
            "runtime_account_count": len(runtime_account_pairs),
            "runtime_account_email_env_names": [row["email_env_name"] for row in runtime_account_pairs],
            "runtime_api_key_env_names": api_key_env_names,
            "account_config_env_names": _scene_video_matching_env_names(*account_config_env_names),
            "model_upload_adapter_enabled": adapter_enabled,
            "model_upload_endpoint_env_names": endpoint_env_names,
            "model_upload_command_env_names": command_env_names,
            "model_upload_adapter_target_configured": adapter_target_configured,
            "model_upload_supported": script_path.exists() and adapter_enabled and adapter_target_configured,
        }
        if not checks["script_exists"]:
            blockers.append("omagic_model_upload_adapter_missing")
        else:
            if not adapter_enabled:
                blockers.append("omagic_model_upload_adapter_disabled")
            if not adapter_target_configured:
                blockers.append("omagic_model_upload_endpoint_missing")
        if not credentials_ready:
            blockers.append("omagic_credentials_missing")
    elif contract_provider_key == "onemin_i2v":
        key_ready = _scene_video_env_has_any("ONEMIN_AI_API_KEY", "ONEMIN_DIRECT_API_KEYS_JSON", "ONEMIN_DIRECT_API_KEYS_JSON_FILE") or any(
            key.startswith("ONEMIN_AI_API_KEY_FALLBACK_") and str(value or "").strip()
            for key, value in os.environ.items()
        )
        credit_readiness = _scene_video_onemin_credit_readiness() if key_ready else {
            "credit_state": "unprobed",
            "minimum_required_credits": _scene_video_onemin_i2v_min_required_credits(),
        }
        checks = {
            "public_provider_key": "onemin_i2v",
            "backend_adapter_key": "onemin_i2v",
            "account_config_scope": "read_only_existing_onemin_config",
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
        docker_daemon_ready, docker_daemon_detail = _scene_video_docker_daemon_readiness(docker_cli_path)
        docker_socket_ready, docker_socket_path, docker_socket_detail = _scene_video_docker_socket_readiness()
        checks = {
            "script_path": str(script_path),
            "script_exists": script_path.exists(),
            "docker_cli_configured": bool(docker_cli_path),
            "docker_cli_path": docker_cli_path,
            "docker_socket_configured": docker_socket_ready,
            "docker_socket_path": docker_socket_path,
            "docker_socket_detail": docker_socket_detail,
            "docker_daemon_ready": docker_daemon_ready,
            "docker_daemon_detail": docker_daemon_detail,
        }
        if not checks["script_exists"]:
            blockers.append("mootion_worker_script_missing")
        if not docker_socket_ready:
            blockers.append("mootion_docker_socket_missing")
        if not docker_cli_path:
            blockers.append("mootion_docker_cli_missing")
        elif not docker_daemon_ready:
            blockers.append("mootion_docker_daemon_unavailable")
    ready = not blockers
    readiness = {
        "provider_key": contract_provider_key,
        "provider_backend_key": backend_provider_key,
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "blockers": blockers,
        "checks": checks,
    }
    for receipt_key in (
        "public_provider_key",
        "backend_adapter_key",
        "account_config_scope",
        "credit_state",
        "minimum_required_credits",
        "runtime_account_count",
    ):
        if receipt_key in checks:
            readiness[receipt_key] = checks[receipt_key]
    return readiness


def resolve_property_walkthrough_runtime_provider(
    value: object,
    *,
    allow_non_final_fallback: bool = False,
) -> dict[str, object]:
    explicit_token = _normalized_provider_token(value)
    explicit_requested = bool(explicit_token)
    checked: list[dict[str, object]] = []

    def _record(provider_key: str) -> dict[str, object]:
        readiness = scene_video_provider_runtime_readiness(provider_key)
        checked.append(
            {
                "provider_key": provider_key,
                "ready": bool(readiness.get("ready")),
                "status": str(readiness.get("status") or ""),
                "blockers": list(readiness.get("blockers") or []),
            }
        )
        return readiness

    if explicit_requested:
        resolved_provider = normalize_scene_video_backend_provider(value, default="mootion")
        readiness = _record(resolved_provider)
        return {
            "provider_key": str(readiness.get("provider_key") or normalize_scene_video_contract_provider(resolved_provider)),
            "provider_backend_key": str(readiness.get("provider_backend_key") or resolved_provider),
            "runtime_readiness_json": readiness,
            "checked": checked,
            "selected_via": "explicit_request",
            "explicit_requested": True,
        }

    final_candidates = ("omagic", "magicfit", "onemin_i2v")
    for candidate in final_candidates:
        readiness = _record(candidate)
        if bool(readiness.get("ready")):
            return {
                "provider_key": str(readiness.get("provider_key") or normalize_scene_video_contract_provider(candidate)),
                "provider_backend_key": str(readiness.get("provider_backend_key") or candidate),
                "runtime_readiness_json": readiness,
                "checked": checked,
                "selected_via": "auto_final_ready",
                "explicit_requested": False,
            }

    if allow_non_final_fallback:
        for candidate in ("onemin_i2v", "mootion"):
            readiness = _record(candidate)
            if bool(readiness.get("ready")):
                return {
                    "provider_key": str(readiness.get("provider_key") or normalize_scene_video_contract_provider(candidate)),
                    "provider_backend_key": str(readiness.get("provider_backend_key") or candidate),
                    "runtime_readiness_json": readiness,
                    "checked": checked,
                    "selected_via": "auto_fallback_ready",
                    "explicit_requested": False,
                }

    fallback_provider = "magicfit"
    fallback_readiness = next(
        (
            scene_video_provider_runtime_readiness(entry.get("provider_key") or "")
            for entry in checked
            if str(entry.get("provider_key") or "").strip() == fallback_provider
        ),
        None,
    )
    if not isinstance(fallback_readiness, dict):
        fallback_readiness = scene_video_provider_runtime_readiness(fallback_provider)
    return {
        "provider_key": str(fallback_readiness.get("provider_key") or normalize_scene_video_contract_provider(fallback_provider)),
        "provider_backend_key": str(fallback_readiness.get("provider_backend_key") or fallback_provider),
        "runtime_readiness_json": fallback_readiness,
        "checked": checked,
        "selected_via": "auto_no_ready_provider",
        "explicit_requested": False,
    }


def normalize_scene_video_contract_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic"}:
        return "omagic"
    if normalized in {"1min", "one_min", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if normalized in {"magicfit", "magic_fit"}:
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic"}:
        return "omagic"
    if fallback in {"1min", "one_min", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if fallback in {"magicfit", "magic_fit"}:
        return "magicfit"
    return fallback or "mootion"


def normalize_scene_video_backend_provider(value: object, *, default: str = "mootion") -> str:
    normalized = _normalized_provider_token(value)
    if normalized in {"magic", "omagic"}:
        return "omagic"
    if normalized in {"1min", "one_min", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if normalized in {"magicfit", "magic_fit"}:
        return "magicfit"
    if normalized == "mootion":
        return "mootion"
    fallback = _normalized_provider_token(default)
    if fallback in {"magic", "omagic"}:
        return "omagic"
    if fallback in {"1min", "one_min", "onemin", "onemin_i2v"}:
        return "onemin_i2v"
    if fallback in {"magicfit", "magic_fit"}:
        return "magicfit"
    return fallback or "mootion"
