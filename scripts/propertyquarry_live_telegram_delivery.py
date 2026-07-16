#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.propertyquarry_live_http_security import redact_secret_values


MAX_RESPONSE_BYTES = 128_000


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _send_message(
    url: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler)
    started = monotonic()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return {
                "status_code": int(response.status),
                "body": response.read(MAX_RESPONSE_BYTES),
                "duration_ms": int((monotonic() - started) * 1000),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status_code": int(exc.code),
            "body": exc.read(MAX_RESPONSE_BYTES),
            "duration_ms": int((monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "body": b"",
            "duration_ms": int((monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _json_payload(result: dict[str, object]) -> dict[str, object]:
    raw = result.get("body")
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_error(result: dict[str, object], payload: dict[str, object], *, secrets: tuple[str, ...]) -> str:
    description = payload.get("description") or result.get("error") or ""
    compact = re.sub(r"\s+", " ", str(description or "")).strip()[:240]
    return redact_secret_values(compact, secrets=secrets)


def build_live_telegram_delivery_receipt(
    *,
    bot_token: str,
    chat_id: str,
    release_commit_sha: str,
    timeout_seconds: float = 15.0,
    sender: Callable[[str, dict[str, object], float], dict[str, object]] = _send_message,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    normalized_token = str(bot_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_sha = str(release_commit_sha or "").strip().lower()
    checks: list[dict[str, object]] = []
    input_checks = (
        ("bot_token_present", len(normalized_token) >= 20),
        ("chat_id_present", bool(normalized_chat_id)),
        ("release_commit_sha_valid", bool(re.fullmatch(r"[0-9a-f]{40}", normalized_sha))),
    )
    checks.extend({"name": name, "ok": ok} for name, ok in input_checks)
    if not all(ok for _, ok in input_checks):
        return {
            "contract_name": "propertyquarry.live_notification_delivery",
            "version": 1,
            "product": "PropertyQuarry",
            "kind": "live_delivery_receipt",
            "generated_at": generated_at,
            "status": "blocked",
            "failed_count": sum(1 for _, ok in input_checks if not ok),
            "release_commit_sha": normalized_sha,
            "provider": "telegram",
            "checks": checks,
            "delivery": {},
            "notes": ["The Telegram probe did not send because protected inputs were incomplete."],
        }

    message_text = (
        "PropertyQuarry protected release check\n"
        f"Candidate: {normalized_sha[:12]}\n"
        "No action needed."
    )
    result = sender(
        f"https://api.telegram.org/bot{normalized_token}/sendMessage",
        {
            "chat_id": normalized_chat_id,
            "text": message_text,
            "disable_notification": True,
            "link_preview_options": {"is_disabled": True},
        },
        timeout_seconds,
    )
    payload = _json_payload(result)
    message = dict(payload.get("result") or {}) if isinstance(payload.get("result"), dict) else {}
    response_chat = dict(message.get("chat") or {}) if isinstance(message.get("chat"), dict) else {}
    status_code = int(result.get("status_code") or 0)
    message_id = int(message.get("message_id") or 0)
    sent_at = int(message.get("date") or 0)
    response_chat_id = str(response_chat.get("id") or "").strip()
    response_checks = (
        ("telegram_http_success", 200 <= status_code < 300),
        ("telegram_response_json", bool(payload)),
        ("telegram_api_ok", payload.get("ok") is True),
        ("telegram_message_id_present", message_id > 0),
        ("telegram_sent_at_present", sent_at > 0),
        ("telegram_chat_binding_matches", response_chat_id == normalized_chat_id),
    )
    checks.extend({"name": name, "ok": ok} for name, ok in response_checks)
    failed_count = sum(1 for check in checks if check.get("ok") is not True)
    chat_id_hash = hashlib.sha256(normalized_chat_id.encode("utf-8")).hexdigest()
    receipt = {
        "contract_name": "propertyquarry.live_notification_delivery",
        "version": 1,
        "product": "PropertyQuarry",
        "kind": "live_delivery_receipt",
        "generated_at": generated_at,
        "status": "pass" if failed_count == 0 else "blocked",
        "failed_count": failed_count,
        "release_commit_sha": normalized_sha,
        "provider": "telegram",
        "proof_scope": "provider_accepted_external_delivery",
        "checks": checks,
        "delivery": {
            "transport": "telegram",
            "message_id": message_id,
            "sent_at": sent_at,
            "chat_id_sha256": chat_id_hash,
            "duration_ms": int(result.get("duration_ms") or 0),
        },
        "error": _safe_error(
            result,
            payload,
            secrets=(normalized_token, normalized_chat_id),
        )
        if failed_count
        else "",
        "notes": [
            "This receipt performs one real Telegram Bot API send and never uses a mock or fixture.",
            "Pass requires Telegram to return a non-zero message id bound to the protected target chat.",
        ],
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one protected PropertyQuarry Telegram release check.")
    parser.add_argument("--release-commit-sha", default=_env("PROPERTYQUARRY_EXPECTED_RELEASE_COMMIT_SHA"))
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--write", default="")
    args = parser.parse_args()

    receipt = build_live_telegram_delivery_receipt(
        bot_token=_env("PROPERTYQUARRY_LIVE_TELEGRAM_BOT_TOKEN"),
        chat_id=_env("PROPERTYQUARRY_LIVE_TELEGRAM_CHAT_ID"),
        release_commit_sha=str(args.release_commit_sha),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.write:
        write_path = Path(args.write)
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
