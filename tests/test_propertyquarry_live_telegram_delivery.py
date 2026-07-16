from __future__ import annotations

import json

from scripts.propertyquarry_live_telegram_delivery import build_live_telegram_delivery_receipt


SHA = "8" * 40
BOT_TOKEN = "123456789:protected-telegram-bot-token"
CHAT_ID = "-1001234567890"


def _success_result(*, chat_id: str = CHAT_ID, message_id: int = 4417) -> dict[str, object]:
    return {
        "status_code": 200,
        "duration_ms": 37,
        "body": json.dumps(
            {
                "ok": True,
                "result": {
                    "message_id": message_id,
                    "date": 1_789_000_000,
                    "chat": {"id": int(chat_id), "type": "private"},
                    "text": "PropertyQuarry protected release check",
                },
            }
        ).encode("utf-8"),
    }


def _build(*, sender) -> dict[str, object]:
    return build_live_telegram_delivery_receipt(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        release_commit_sha=SHA,
        sender=sender,
    )


def test_live_telegram_delivery_passes_on_bound_nonzero_message_receipt() -> None:
    observed: dict[str, object] = {}

    def sender(url, payload, timeout):  # type: ignore[no-untyped-def]
        observed.update(url=url, payload=payload, timeout=timeout)
        return _success_result()

    receipt = _build(sender=sender)
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    assert receipt["provider"] == "telegram"
    assert receipt["delivery"]["message_id"] == 4417  # type: ignore[index]
    assert receipt["delivery"]["chat_id_sha256"]  # type: ignore[index]
    assert observed["url"] == f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    assert observed["payload"]["chat_id"] == CHAT_ID  # type: ignore[index]
    assert observed["payload"]["disable_notification"] is True  # type: ignore[index]
    assert BOT_TOKEN not in rendered
    assert CHAT_ID not in rendered


def test_live_telegram_delivery_blocks_wrong_chat_or_zero_message_id() -> None:
    wrong_chat = _build(sender=lambda *_args: _success_result(chat_id="-1009876543210"))
    zero_message = _build(sender=lambda *_args: _success_result(message_id=0))

    assert wrong_chat["status"] == "blocked"
    assert "telegram_chat_binding_matches" in {
        row["name"] for row in wrong_chat["checks"] if row["ok"] is False  # type: ignore[index]
    }
    assert zero_message["status"] == "blocked"
    assert "telegram_message_id_present" in {
        row["name"] for row in zero_message["checks"] if row["ok"] is False  # type: ignore[index]
    }


def test_live_telegram_delivery_missing_inputs_never_sends() -> None:
    called = False

    def sender(*_args):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return _success_result()

    receipt = build_live_telegram_delivery_receipt(
        bot_token="",
        chat_id=CHAT_ID,
        release_commit_sha=SHA,
        sender=sender,
    )

    assert receipt["status"] == "blocked"
    assert called is False


def test_live_telegram_delivery_redacts_provider_error() -> None:
    def sender(*_args):  # type: ignore[no-untyped-def]
        return {
            "status_code": 400,
            "body": json.dumps(
                {"ok": False, "description": f"token {BOT_TOKEN} rejected for chat {CHAT_ID}"}
            ).encode("utf-8"),
        }

    receipt = _build(sender=sender)
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "blocked"
    assert "[redacted-secret]" in receipt["error"]
    assert BOT_TOKEN not in rendered
    assert CHAT_ID not in rendered
