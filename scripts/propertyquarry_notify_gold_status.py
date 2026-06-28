#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.telegram_delivery import (
    _chunk_telegram_text,
    _telegram_bot_registry,
    _telegram_html_with_titled_links,
    _telegram_send_json,
    _telegram_visible_button_label,
    send_telegram_message_for_principal,
)
from app.services.tool_runtime import build_tool_runtime

ROOT = Path(__file__).resolve().parents[1]
_FALLBACK_ENV_PATHS = (
    ROOT / ".env",
    Path("/docker/EA/.env"),
)
_CANONICAL_GOLD_RECEIPT_PATHS = (
    "_completion/property_gold_status/latest.json",
    "_completion/propertyquarry-gold-status-latest.json",
)
_DIRECT_CHAT_ENV_KEYS = (
    "PROPERTYQUARRY_GOLD_NOTIFY_TELEGRAM_CHAT_ID",
    "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID",
    "EA_TELEGRAM_DEFAULT_CHAT_ID",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("json_root_not_object")
    return payload


def _payload_digest(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("generated_at", None)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_dotenv_defaults(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _load_local_env_defaults() -> None:
    for path in _FALLBACK_ENV_PATHS:
        _load_dotenv_defaults(path)


def _direct_chat_id() -> str:
    for key in _DIRECT_CHAT_ENV_KEYS:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_receipt_path(raw_path: str) -> Path:
    requested = Path(str(raw_path or "").strip() or _CANONICAL_GOLD_RECEIPT_PATHS[0]).expanduser().resolve()
    if requested.is_file():
        return requested
    canonical_targets = {Path(path).expanduser().resolve() for path in _CANONICAL_GOLD_RECEIPT_PATHS}
    if requested in canonical_targets:
        for candidate_raw in _CANONICAL_GOLD_RECEIPT_PATHS:
            candidate = Path(candidate_raw).expanduser().resolve()
            if candidate.is_file():
                return candidate
    return requested


def _send_direct_telegram_message(
    *,
    chat_id: str,
    text: str,
    url_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    config = dict(_telegram_bot_registry().get("default") or {})
    token = str(config.get("token") or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    message_ids: list[str] = []
    rendered_text = _telegram_html_with_titled_links(text)
    for chunk in _chunk_telegram_text(rendered_text):
        payload: dict[str, object] = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
        keyboard_rows: list[list[dict[str, str]]] = []
        for row in list(url_buttons or []):
            buttons = [
                {"text": _telegram_visible_button_label(str(label or ""), url=str(url or "")), "url": str(url or "").strip()}
                for label, url in row
                if (str(label or "").strip() or str(url or "").strip()) and str(url or "").strip()
            ]
            if buttons:
                keyboard_rows.append(buttons)
        if keyboard_rows:
            payload["reply_markup"] = {"inline_keyboard": keyboard_rows}
        result = _telegram_send_json(
            token=token,
            method="sendMessage",
            payload=payload,
        )
        message_ids.append(str(result.get("message_id") or ""))
    return {
        "bot_handle": str(config.get("handle") or "").strip(),
        "bot_key": "default",
        "chat_id": chat_id,
        "message_ids": [value for value in message_ids if value],
    }


def _build_message(*, payload: dict[str, Any], receipt_path: Path, base_url: str) -> str:
    generated_at = str(payload.get("generated_at") or "").strip() or _utc_now_iso()
    pass_areas = list(payload.get("pass_areas") or [])
    pass_area_count = len(pass_areas)
    lines = [
        "PropertyQuarry gold receipt is green.",
        f"Site: {base_url}",
        f"Generated: {generated_at}",
        f"Pass areas: {pass_area_count}",
        f"Receipt: {receipt_path}",
    ]
    return "\n".join(lines)


def _receipt_ready_for_notification(payload: dict[str, Any]) -> bool:
    return payload.get("ready_for_notification") is True


def build_notification_report(
    *,
    payload: dict[str, Any],
    receipt_path: Path,
    state_path: Path,
    principal_id: str,
    base_url: str,
    force: bool,
) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip().lower()
    generated_at = str(payload.get("generated_at") or "").strip()
    ready_for_notification = _receipt_ready_for_notification(payload)
    digest = _payload_digest(payload)
    report: dict[str, Any] = {
        "receipt_path": str(receipt_path),
        "state_path": str(state_path),
        "principal_id": principal_id,
        "base_url": base_url,
        "status": status,
        "generated_at": generated_at,
        "ready_for_notification": ready_for_notification,
        "receipt_digest": digest,
        "sent": False,
        "skipped_reason": "",
        "message_ids": [],
        "checked_at": _utc_now_iso(),
        "delivery_mode": "",
    }
    if status != "pass":
        report["skipped_reason"] = f"receipt_status_{status or 'missing'}"
        return report
    if not ready_for_notification:
        report["skipped_reason"] = "receipt_not_ready_for_notification"
        return report

    if not force and state_path.is_file():
        try:
            prior = _load_json(state_path)
        except Exception:
            prior = {}
        if str(prior.get("last_notified_digest") or "").strip() == digest:
            report["skipped_reason"] = "already_notified_same_digest"
            return report

    message = _build_message(payload=payload, receipt_path=receipt_path, base_url=base_url)
    url_buttons = [[("Open PropertyQuarry", base_url)]]
    runtime_error = ""
    try:
        runtime = build_tool_runtime()
        receipt = send_telegram_message_for_principal(
            runtime,
            principal_id=principal_id,
            text=message,
            url_buttons=url_buttons,
        )
        report["delivery_mode"] = "principal_binding"
        report["message_ids"] = list(receipt.message_ids)
    except Exception as exc:
        runtime_error = f"{type(exc).__name__}: {exc}"
        chat_id = _direct_chat_id()
        if not chat_id:
            raise
        receipt = _send_direct_telegram_message(
            chat_id=chat_id,
            text=message,
            url_buttons=url_buttons,
        )
        report["delivery_mode"] = "direct_chat_fallback"
        report["message_ids"] = list(receipt.get("message_ids") or [])
    if runtime_error:
        report["runtime_error"] = runtime_error
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_notified_at": _utc_now_iso(),
                "last_notified_digest": digest,
                "last_notified_status": status,
                "last_receipt_path": str(receipt_path),
                "last_generated_at": generated_at,
                "principal_id": principal_id,
                "base_url": base_url,
                "message_ids": list(report["message_ids"]),
                "delivery_mode": report["delivery_mode"],
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
    _load_local_env_defaults()
    parser = argparse.ArgumentParser(
        description="Send a Telegram message when the PropertyQuarry gold receipt is green."
    )
    parser.add_argument(
        "--receipt",
        default="_completion/property_gold_status/latest.json",
        help="Gold receipt path to inspect.",
    )
    parser.add_argument(
        "--state-file",
        default="_completion/propertyquarry-gold-notification-state.json",
        help="Deduplication state file path.",
    )
    parser.add_argument(
        "--principal-id",
        default="cf-email:tibor.girschele@gmail.com",
        help="Principal id whose Telegram binding should receive the notification.",
    )
    parser.add_argument(
        "--base-url",
        default="https://propertyquarry.com",
        help="Public site URL to include in the message and button.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send even if the same receipt digest was already notified.",
    )
    parser.add_argument(
        "--write",
        default="",
        help="Optional JSON report path.",
    )
    args = parser.parse_args(argv)

    receipt_path = _resolve_receipt_path(str(args.receipt or ""))
    state_path = Path(args.state_file).expanduser().resolve()
    if not receipt_path.is_file():
        raise SystemExit(
            "Gold receipt not found: "
            f"{receipt_path} "
            f"(checked canonical aliases: {', '.join(_CANONICAL_GOLD_RECEIPT_PATHS)})"
        )

    payload = _load_json(receipt_path)
    report = build_notification_report(
        payload=payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id=str(args.principal_id or "").strip() or "cf-email:tibor.girschele@gmail.com",
        base_url=str(args.base_url or "").strip() or "https://propertyquarry.com",
        force=bool(args.force),
    )
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
