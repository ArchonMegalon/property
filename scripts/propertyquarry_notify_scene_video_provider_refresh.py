#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "ea", ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from scripts import propertyquarry_notify_gold_status as gold_notify


_CANONICAL_PACKET_PATHS = (
    "_completion/scene_video_readiness/provider-refresh-packet.json",
    "_completion/scene_video_readiness/property-scene-video-provider-refresh-packet.json",
)
_CANONICAL_VERIFIER_PATHS = (
    "_completion/scene_video_readiness/provider-refresh-packet-verifier.json",
    "_completion/scene_video_readiness/property-scene-video-provider-refresh-packet-verifier.json",
)
_CANONICAL_RUNTIME_STATUS_PATHS = (
    "_completion/scene_video_readiness/runtime-status.json",
)
_DEFAULT_STATE_PATH = "_completion/scene_video_readiness/provider-refresh-telegram-state.json"
_DEFAULT_REPORT_PATH = "_completion/scene_video_readiness/provider-refresh-telegram-report.json"
_DEFAULT_BASE_URL = "https://propertyquarry.com"
_DEFAULT_PRINCIPAL_ID = "cf-email:tibor.girschele@gmail.com"
_ACCOUNT_FILE_TARGET = "state/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("json_root_not_object")
    return payload


def _resolve_alias_path(raw_path: str, aliases: tuple[str, ...]) -> Path:
    requested = Path(str(raw_path or "").strip() or aliases[0]).expanduser().resolve()
    if requested.is_file():
        return requested
    canonical_targets = {Path(path).expanduser().resolve() for path in aliases}
    if requested in canonical_targets:
        for candidate_raw in aliases:
            candidate = Path(candidate_raw).expanduser().resolve()
            if candidate.is_file():
                return candidate
    return requested


def _positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _provider_label(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "magicfit":
        return "MagicFit"
    if normalized in {"omagic", "magic"}:
        return "OMagic/Magic"
    return str(value or "unknown").strip() or "unknown"


def _merge_command(row: dict[str, Any]) -> str:
    for entry in list(row.get("post_refresh_checks") or []):
        text = str(entry or "").strip()
        if "merge_scene_video_provider_accounts_env.py" in text:
            return text
    return ""


def _provider_summary_lines(row: dict[str, Any]) -> list[str]:
    provider = str(row.get("provider") or "").strip().lower()
    expected = _positive_int(row.get("expected_account_count"))
    tracked = _positive_int(row.get("tracked_account_count"))
    unavailable = _positive_int(row.get("unavailable_account_count"))
    runtime = _positive_int(row.get("runtime_account_count"))
    visible_gap = _positive_int(row.get("visible_account_gap"))
    credit_state = str(row.get("credit_state") or "").strip()
    blockers = [
        str(value or "").strip()
        for value in list(row.get("runtime_blockers") or [])
        if str(value or "").strip()
    ]
    lines = [f"{_provider_label(provider)} accounts visible: {runtime}/{expected}."]
    if visible_gap > 0:
        lines[0] = f"{_provider_label(provider)} accounts visible: {runtime}/{expected} ({visible_gap} missing)."
    if tracked > expected:
        tracked_line = f"Tracked inventory: {tracked}."
        if unavailable > 0:
            tracked_line = f"Tracked inventory: {tracked} ({unavailable} unavailable)."
        lines.append(tracked_line)
    if credit_state and credit_state != "funded":
        lines.append(f"Credit state: {credit_state}.")
    if blockers:
        lines.append(f"Blockers: {', '.join(blockers)}.")
    command = _merge_command(row)
    if command:
        lines.append(f"Merge: {command}")
    if provider == "magicfit":
        lines.append(
            "Then set PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX to a funded account and run a MagicFit proof render before clearing the credit marker."
        )
    if provider == "omagic":
        lines.append(
            "Also configure PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT or PROPERTYQUARRY_OMAGIC_RENDER_COMMAND, run a real model-input proof render, then enable PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED=1 only after success."
        )
    return lines


def _actionable_providers(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_row in list(packet.get("providers") or []):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        credit_refresh_required = row.get("credit_refresh_required") is True
        credit_state = str(row.get("credit_state") or "").strip().lower()
        if (
            _positive_int(row.get("visible_account_gap")) > 0
            or list(row.get("runtime_blockers") or [])
            or credit_refresh_required
            or credit_state in {"constrained", "insufficient"}
        ):
            rows.append(row)
    return rows


def _combined_digest(packet: dict[str, Any], verifier: dict[str, Any], runtime_status: dict[str, Any]) -> str:
    payload = {
        "packet_digest": gold_notify._payload_digest(packet),
        "verifier_digest": gold_notify._payload_digest(verifier),
        "runtime_status_digest": gold_notify._payload_digest(runtime_status),
    }
    return gold_notify._payload_digest(payload)


def _build_message(
    *,
    packet: dict[str, Any],
    packet_path: Path,
    runtime_status: dict[str, Any],
) -> str:
    lines = ["PropertyQuarry scene-video provider runtime is still blocked."]
    summary = dict(runtime_status.get("summary") or {})
    provider_count = _positive_int(summary.get("provider_count"))
    if provider_count > 0:
        lines.append(
            "Current runtime: "
            f"ready {_positive_int(summary.get('ready_count'))}/{provider_count}, "
            f"blocked {_positive_int(summary.get('blocked_count'))}, "
            f"action required {_positive_int(summary.get('action_required_count'))}."
        )
    lines.append(f"Target account-file folder: {_ACCOUNT_FILE_TARGET}")
    for row in _actionable_providers(packet):
        lines.append("")
        lines.extend(_provider_summary_lines(row))
    lines.append("")
    lines.append(
        "Verify after refresh: python3 scripts/property_scene_video_readiness_report.py && python3 scripts/verify_property_scene_video_readiness.py"
    )
    lines.append(f"Packet: {packet_path}")
    return "\n".join(lines)


def build_notification_report(
    *,
    packet: dict[str, Any],
    packet_path: Path,
    verifier: dict[str, Any],
    verifier_path: Path,
    runtime_status: dict[str, Any],
    runtime_status_path: Path,
    state_path: Path,
    principal_id: str,
    base_url: str,
    force: bool,
) -> dict[str, Any]:
    verifier_status = str(verifier.get("status") or "").strip().lower()
    actionable_rows = _actionable_providers(packet)
    digest = _combined_digest(packet, verifier, runtime_status)
    report: dict[str, Any] = {
        "packet_path": str(packet_path),
        "verifier_path": str(verifier_path),
        "runtime_status_path": str(runtime_status_path),
        "state_path": str(state_path),
        "principal_id": principal_id,
        "base_url": base_url,
        "verifier_status": verifier_status,
        "actionable_provider_count": len(actionable_rows),
        "packet_generated_at": str(packet.get("generated_at") or "").strip(),
        "runtime_generated_at": str(runtime_status.get("generated_at") or "").strip(),
        "packet_digest": digest,
        "sent": False,
        "skipped_reason": "",
        "message_ids": [],
        "delivery_mode": "",
        "checked_at": gold_notify._utc_now_iso(),
    }
    if verifier_status != "pass":
        report["skipped_reason"] = f"packet_verifier_status_{verifier_status or 'missing'}"
        return report
    if not actionable_rows:
        report["skipped_reason"] = "no_actionable_provider_refresh"
        return report

    if not force and state_path.is_file():
        try:
            prior = _load_json(state_path)
        except Exception:
            prior = {}
        if str(prior.get("last_notified_digest") or "").strip() == digest:
            report["skipped_reason"] = "already_notified_same_digest"
            return report

    message = _build_message(packet=packet, packet_path=packet_path, runtime_status=runtime_status)
    url_buttons = [[("Open PropertyQuarry", base_url)]]
    delivery = gold_notify.deliver_notification_for_principal(
        principal_id=principal_id,
        text=message,
        url_buttons=url_buttons,
    )
    report["delivery_mode"] = str(delivery.get("delivery_mode") or "").strip()
    report["message_ids"] = [str(value) for value in list(delivery.get("message_ids") or []) if str(value or "").strip()]
    if delivery.get("runtime_error"):
        report["runtime_error"] = str(delivery.get("runtime_error") or "").strip()
    if delivery.get("container_runtime_error"):
        report["container_runtime_error"] = str(delivery.get("container_runtime_error") or "").strip()

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_notified_at": gold_notify._utc_now_iso(),
                "last_notified_digest": digest,
                "last_packet_path": str(packet_path),
                "last_verifier_path": str(verifier_path),
                "last_runtime_status_path": str(runtime_status_path),
                "message_ids": list(report["message_ids"]),
                "delivery_mode": report["delivery_mode"],
                "principal_id": principal_id,
                "base_url": base_url,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report["sent"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    gold_notify._load_local_env_defaults()
    parser = argparse.ArgumentParser(
        description="Send the current PropertyQuarry scene-video provider refresh ask to Telegram."
    )
    parser.add_argument("--packet", default=_CANONICAL_PACKET_PATHS[0])
    parser.add_argument("--verifier", default=_CANONICAL_VERIFIER_PATHS[0])
    parser.add_argument("--runtime-status", default=_CANONICAL_RUNTIME_STATUS_PATHS[0])
    parser.add_argument("--state-file", default=_DEFAULT_STATE_PATH)
    parser.add_argument("--principal-id", default=_DEFAULT_PRINCIPAL_ID)
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--write", default=_DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    packet_path = _resolve_alias_path(str(args.packet or ""), _CANONICAL_PACKET_PATHS)
    verifier_path = _resolve_alias_path(str(args.verifier or ""), _CANONICAL_VERIFIER_PATHS)
    runtime_status_path = _resolve_alias_path(str(args.runtime_status or ""), _CANONICAL_RUNTIME_STATUS_PATHS)
    if not packet_path.is_file():
        raise SystemExit(f"Scene-video provider refresh packet not found: {packet_path}")
    if not verifier_path.is_file():
        raise SystemExit(f"Scene-video provider refresh verifier not found: {verifier_path}")
    if not runtime_status_path.is_file():
        raise SystemExit(f"Scene-video runtime status receipt not found: {runtime_status_path}")

    report = build_notification_report(
        packet=_load_json(packet_path),
        packet_path=packet_path,
        verifier=_load_json(verifier_path),
        verifier_path=verifier_path,
        runtime_status=_load_json(runtime_status_path),
        runtime_status_path=runtime_status_path,
        state_path=Path(args.state_file).expanduser().resolve(),
        principal_id=str(args.principal_id or "").strip() or _DEFAULT_PRINCIPAL_ID,
        base_url=str(args.base_url or "").strip() or _DEFAULT_BASE_URL,
        force=bool(args.force),
    )
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
