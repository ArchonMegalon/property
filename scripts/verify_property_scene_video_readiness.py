#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CONTRACT_NAME = "propertyquarry.scene_video_readiness.v1"
DEFAULT_RECEIPT = Path("/data/artifacts/property-scene-video-readiness.generated.json")
FALLBACK_RECEIPT = Path(__file__).resolve().parents[1] / "_completion" / "scene_video_readiness" / "PROPERTY_SCENE_VIDEO_READINESS.generated.json"
REQUIRED_PROVIDERS = ("mootion", "magicfit", "magic", "omagic", "onemin_i2v")
ONEMIN_PROTECTED_ACTION_REASONS = {
    "provider_account_visibility_gap",
    "magicfit_insufficient_credits",
    "omagic_credentials_missing",
}


def _default_receipt_path() -> Path:
    return DEFAULT_RECEIPT if DEFAULT_RECEIPT.exists() else FALLBACK_RECEIPT


def _row_by_provider(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in list(receipt.get("providers") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("requested_provider") or "").strip()
        if key:
            rows[key] = row
    return rows


def _actions_by_provider_reason(receipt: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for action in list(receipt.get("next_actions") or []):
        if not isinstance(action, dict):
            continue
        provider = str(action.get("provider") or "").strip()
        reason = str(action.get("reason") or "").strip()
        if provider and reason:
            pairs.add((provider, reason))
    return pairs


def _actions_for_reason(receipt: dict[str, Any], reason: str) -> list[dict[str, Any]]:
    return [
        action
        for action in list(receipt.get("next_actions") or [])
        if isinstance(action, dict) and str(action.get("reason") or "").strip() == reason
    ]


def _inventory_gap(row: dict[str, Any]) -> int:
    inventory = dict(row.get("account_inventory") or {})
    try:
        return max(0, int(inventory.get("visible_account_gap") or 0))
    except Exception:
        return 0


def _require_action(blockers: list[str], receipt: dict[str, Any], provider: str, reason: str) -> None:
    if (provider, reason) not in _actions_by_provider_reason(receipt):
        blockers.append(f"next_action_missing:{provider}:{reason}")


def validate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if receipt.get("contract_name") != CONTRACT_NAME:
        blockers.append("contract_name_mismatch")
    rows = _row_by_provider(receipt)
    for provider in REQUIRED_PROVIDERS:
        if provider not in rows:
            blockers.append(f"provider_row_missing:{provider}")

    telegram = dict(receipt.get("telegram_delivery_readiness") or {})
    if telegram.get("status") != "ready":
        blockers.append("telegram_not_ready")

    mootion = rows.get("mootion") or {}
    if mootion.get("ready") is not True:
        blockers.append("mootion_not_ready")
    if str(mootion.get("execution_lane") or "").strip() != "browseract_remote":
        blockers.append("mootion_browseract_remote_lane_missing")
    mootion_remote = dict(dict(mootion.get("checks") or {}).get("mootion_browseract_remote") or {})
    if mootion_remote.get("ready") is not True:
        blockers.append("mootion_browseract_bridge_not_ready")

    onemin = rows.get("onemin_i2v") or {}
    if onemin.get("ready") is not True:
        blockers.append("onemin_i2v_not_ready")
    if str(onemin.get("provider_backend_key") or "").strip() != "onemin_i2v":
        blockers.append("onemin_i2v_backend_mismatch")

    magicfit = rows.get("magicfit") or {}
    if str(magicfit.get("provider_backend_key") or "").strip() != "magicfit":
        blockers.append("magicfit_backend_mismatch")
    if _inventory_gap(magicfit) > 0:
        _require_action(blockers, receipt, "magicfit", "provider_account_visibility_gap")
    if "magicfit_insufficient_credits" in list(magicfit.get("blockers") or []):
        _require_action(blockers, receipt, "magicfit", "magicfit_insufficient_credits")

    for requested in ("magic", "omagic"):
        row = rows.get(requested) or {}
        if str(row.get("provider_key") or "").strip() != "omagic":
            blockers.append(f"{requested}_provider_key_mismatch")
        if str(row.get("provider_backend_key") or "").strip() != "omagic":
            blockers.append(f"{requested}_backend_mismatch")
        if _inventory_gap(row) > 0:
            _require_action(blockers, receipt, requested, "provider_account_visibility_gap")
        row_blockers = list(row.get("blockers") or [])
        if "omagic_credentials_missing" in row_blockers:
            _require_action(blockers, receipt, "omagic", "omagic_credentials_missing")
        if "omagic_model_upload_adapter_missing" in row_blockers:
            _require_action(blockers, receipt, "omagic", "omagic_model_upload_adapter_missing")

    for reason in ONEMIN_PROTECTED_ACTION_REASONS:
        for action in _actions_for_reason(receipt, reason):
            protected = [str(value or "").strip() for value in list(action.get("do_not_touch") or [])]
            if "ONEMIN_*" not in protected:
                blockers.append(f"onemin_boundary_missing:{action.get('provider')}:{reason}")

    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "provider_count": len(rows),
        "checked_providers": list(REQUIRED_PROVIDERS),
    }


def _emit_result(result: dict[str, Any], output_path: str = "") -> None:
    rendered = json.dumps(result, sort_keys=True)
    print(rendered)
    if output_path:
        path = Path(output_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the PropertyQuarry scene-video readiness receipt invariants.")
    parser.add_argument("--receipt", default=str(_default_receipt_path()))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    receipt_path = Path(args.receipt).expanduser()
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        result = {"status": "fail", "blockers": [f"receipt_unreadable:{exc}"], "receipt": str(receipt_path)}
        _emit_result(result, args.output)
        return 1
    if not isinstance(receipt, dict):
        result = {"status": "fail", "blockers": ["receipt_not_object"], "receipt": str(receipt_path)}
        _emit_result(result, args.output)
        return 1
    result = {**validate_receipt(receipt), "receipt": str(receipt_path)}
    _emit_result(result, args.output)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
