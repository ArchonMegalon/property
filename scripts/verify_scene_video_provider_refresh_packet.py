#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_PACKET = Path("/data/artifacts/property-scene-video-provider-refresh-packet.generated.json")
FALLBACK_PACKET = ROOT / "_completion" / "scene_video_readiness" / "provider-refresh-packet.json"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:_\*)?$|^ONEMIN_\*$")
SENSITIVE_PATH_RE = re.compile(r"(api[_-]?key|cookie|password|secret|session|token)", re.IGNORECASE)
SAFE_ACCOUNT_MERGE_SCRIPT_NAME = "merge_scene_video_provider_accounts_env.py"
ACCOUNT_JSON_MODE_GUIDANCE = "0o600"
REQUIRED_EXPECTED_ACCOUNT_COUNTS = {"magicfit": 3, "omagic": 8}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_packet_path() -> Path:
    return DEFAULT_RUNTIME_PACKET if DEFAULT_RUNTIME_PACKET.exists() else FALLBACK_PACKET


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _providers_by_name(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers: dict[str, dict[str, Any]] = {}
    for row in list(packet.get("providers") or []):
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip().lower()
        if provider:
            providers[provider] = row
    return providers


def _int_value(row: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(row.get(key) or 0))
    except Exception:
        return 0


def _has_onemin_boundary(row: dict[str, Any]) -> bool:
    return "ONEMIN_*" in {str(value or "").strip() for value in list(row.get("do_not_touch") or [])}


def _looks_like_safe_reference(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return True
    if ENV_NAME_RE.fullmatch(stripped):
        return True
    return False


def _secret_value_blockers(value: Any, *, path: str = "$") -> list[str]:
    blockers: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            blockers.extend(_secret_value_blockers(child, path=f"{path}.{key}"))
        return blockers
    if isinstance(value, list):
        for index, child in enumerate(value):
            blockers.extend(_secret_value_blockers(child, path=f"{path}[{index}]"))
        return blockers
    if not isinstance(value, str):
        return blockers

    if EMAIL_RE.search(value):
        blockers.append(f"packet_contains_real_email:{path}")
    if re.search(r"\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", value, re.IGNORECASE):
        blockers.append(f"packet_contains_auth_header:{path}")
    if path.endswith(".secret_boundary"):
        return blockers
    if SENSITIVE_PATH_RE.search(path) and value and not _looks_like_safe_reference(value):
        blockers.append(f"packet_contains_secret_value:{path}")
    return blockers


def _validate_gap(provider: str, row: dict[str, Any]) -> list[str]:
    expected = _int_value(row, "expected_account_count")
    runtime = _int_value(row, "runtime_account_count")
    visible_gap = _int_value(row, "visible_account_gap")
    calculated_gap = max(0, expected - runtime)
    if visible_gap != calculated_gap:
        return [f"{provider}_visible_account_gap_mismatch"]
    return []


def _post_refresh_guidance(row: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in list(row.get("post_refresh_checks") or [])
    )


def _has_safe_account_merge_guidance(row: dict[str, Any]) -> bool:
    guidance = _post_refresh_guidance(row)
    return SAFE_ACCOUNT_MERGE_SCRIPT_NAME in guidance and "--write" in guidance


def _has_secure_account_json_guidance(row: dict[str, Any]) -> bool:
    guidance = _post_refresh_guidance(row)
    return ACCOUNT_JSON_MODE_GUIDANCE in guidance and "before merge" in guidance


def _merge_guidance_blockers(provider: str, row: dict[str, Any]) -> list[str]:
    guidance = _post_refresh_guidance(row)
    blockers: list[str] = []
    if provider == "magicfit":
        if "--magicfit-accounts-json-file" not in guidance:
            blockers.append("magicfit_account_json_file_flag_missing")
        expected_flag = f"--expected-magicfit-count {_int_value(row, 'expected_account_count')}"
        if expected_flag not in guidance:
            blockers.append("magicfit_expected_account_count_guard_missing")
    if provider == "omagic":
        if "--omagic-accounts-json-file" not in guidance:
            blockers.append("omagic_account_json_file_flag_missing")
        expected_flag = f"--expected-omagic-count {_int_value(row, 'expected_account_count')}"
        if expected_flag not in guidance:
            blockers.append("omagic_expected_account_count_guard_missing")
    return blockers


def _safe_account_merge_script_path() -> Path:
    return ROOT / "scripts" / SAFE_ACCOUNT_MERGE_SCRIPT_NAME


def verify_packet(packet: dict[str, Any], *, packet_path: str | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    if packet.get("contract_name") != "propertyquarry.scene_video_provider_refresh_packet.v1":
        blockers.append("invalid_contract_name")

    safe_merge_script_path = _safe_account_merge_script_path()
    if not safe_merge_script_path.is_file():
        blockers.append("safe_env_merge_script_missing")

    blockers.extend(_secret_value_blockers(packet))

    rendered = json.dumps(packet, sort_keys=True)
    if "ONEMIN_AI_API_KEY" not in rendered or "ONEMIN_DIRECT_API_KEYS_JSON" not in rendered:
        blockers.append("global_onemin_no_touch_keys_missing")

    providers = _providers_by_name(packet)
    for provider in ("magicfit", "omagic"):
        row = providers.get(provider)
        if not row:
            blockers.append(f"{provider}_provider_missing")
            continue
        if not _has_onemin_boundary(row):
            blockers.append(f"{provider}_onemin_boundary_missing")
        if not _has_safe_account_merge_guidance(row):
            blockers.append(f"{provider}_safe_env_merge_guidance_missing")
        if not _has_secure_account_json_guidance(row):
            blockers.append(f"{provider}_secure_account_json_mode_guidance_missing")
        if _int_value(row, "expected_account_count") < REQUIRED_EXPECTED_ACCOUNT_COUNTS[provider]:
            blockers.append(f"{provider}_expected_account_count_below_required")
        blockers.extend(_merge_guidance_blockers(provider, row))
        blockers.extend(_validate_gap(provider, row))

    magicfit = providers.get("magicfit") or {}
    magicfit_contract = magicfit.get("credential_contract") if isinstance(magicfit.get("credential_contract"), dict) else {}
    if magicfit_contract.get("preferred_accounts_json_env") != "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON":
        blockers.append("magicfit_preferred_accounts_env_missing")
    if magicfit_contract.get("fallback_accounts_json_env") != "MAGICFIT_ACCOUNTS_JSON":
        blockers.append("magicfit_fallback_accounts_env_missing")
    if magicfit_contract.get("account_selector_env") != "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX":
        blockers.append("magicfit_account_selector_env_missing")

    omagic = providers.get("omagic") or {}
    aliases = {str(value or "").strip().lower() for value in list(omagic.get("aliases") or [])}
    omagic_contract = omagic.get("credential_contract") if isinstance(omagic.get("credential_contract"), dict) else {}
    adapter_contract = omagic.get("adapter_contract") if isinstance(omagic.get("adapter_contract"), dict) else {}
    if "magic" not in aliases:
        blockers.append("omagic_magic_alias_missing")
    if omagic_contract.get("preferred_accounts_json_env") != "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON":
        blockers.append("omagic_preferred_accounts_env_missing")
    if omagic_contract.get("alias_accounts_json_env") != "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON":
        blockers.append("omagic_magic_alias_accounts_env_missing")
    if adapter_contract.get("enable_flag") != "PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED":
        blockers.append("omagic_enable_flag_missing")

    status = "fail" if blockers else "pass"
    receipt: dict[str, Any] = {
        "generated_at": _utc_now(),
        "status": status,
        "blockers": blockers,
        "checked_providers": sorted(providers),
        "provider_count": len(providers),
        "safe_env_merge_script": str(safe_merge_script_path),
    }
    if packet_path:
        receipt["packet"] = packet_path
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a secret-safe scene-video provider refresh packet.")
    parser.add_argument("--packet", default=str(_default_packet_path()))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    packet_path = Path(args.packet).expanduser()
    try:
        packet = _load_json(packet_path)
        receipt = verify_packet(packet, packet_path=str(packet_path))
    except Exception as exc:
        receipt = {
            "generated_at": _utc_now(),
            "status": "fail",
            "blockers": [f"packet_load_failed:{exc.__class__.__name__}"],
            "checked_providers": [],
            "provider_count": 0,
            "packet": str(packet_path),
        }

    rendered = json.dumps(receipt, sort_keys=True)
    print(rendered)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
