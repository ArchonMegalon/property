from __future__ import annotations

import json
import urllib.parse

from scripts import propertyquarry_operator_telegram_notify as notify


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeOpener:
    def __init__(self) -> None:
        self.sent_payloads: list[dict[str, object]] = []

    def open(self, request, timeout: float = 0):  # noqa: ANN001
        url = str(request.full_url)
        parsed = urllib.parse.urlparse(url)
        if parsed.path.endswith("/api/base/bse-env/table"):
            return _FakeResponse(
                [
                    {"id": "tbl-other", "name": "other"},
                    {"id": "tbl-telegram", "name": "ea_telegram_conversation_messages"},
                ]
            )
        if parsed.path.endswith("/api/table/tbl-telegram/record"):
            query = urllib.parse.parse_qs(parsed.query)
            skip = int(query.get("skip", ["0"])[0])
            if skip:
                return _FakeResponse({"records": []})
            return _FakeResponse(
                {
                    "records": [
                        {
                            "fields": {
                                "principal_id": "cf-email:tibor.girschele@gmail.com",
                                "chat_ref": "111111",
                                "message_timestamp": "2026-06-01T10:00:00Z",
                            }
                        },
                        {
                            "fields": {
                                "principal_id": "cf-email:tibor.girschele@gmail.com",
                                "chat_ref": "1234567890",
                                "message_timestamp": "2026-06-24T10:00:00Z",
                            }
                        },
                        {
                            "fields": {
                                "principal_id": "someone-else",
                                "chat_ref": "9999999999",
                                "message_timestamp": "2026-06-24T11:00:00Z",
                            }
                        },
                    ]
                }
            )
        if parsed.netloc == "api.telegram.org" and parsed.path.endswith("/getChat"):
            query = urllib.parse.parse_qs(parsed.query)
            chat_id = query.get("chat_id", [""])[0]
            return _FakeResponse({"ok": chat_id == "1234567890", "result": {"type": "private"}})
        if parsed.netloc == "api.telegram.org" and parsed.path.endswith("/sendMessage"):
            self.sent_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse({"ok": True, "result": {"message_id": 42}})
        raise AssertionError(url)


def test_operator_telegram_notify_resolves_teable_chat_and_dry_run_redacts_chat() -> None:
    opener = _FakeOpener()

    receipt = notify.build_notification_receipt(
        principal_id="cf-email:tibor.girschele@gmail.com",
        text="Need BD billing handoff config.",
        dry_run=True,
        env_files=[],
        teable_base_url="https://app.teable.ai",
        teable_api_key="teable-secret",
        teable_base_id="bse-env",
        teable_table_id="",
        teable_table_name="ea_telegram_conversation_messages",
        bot_token="telegram-secret",
        opener=opener,
    )

    assert receipt["status"] == "ready"
    assert receipt["teable"]["table_id_present"] is True
    assert receipt["telegram"]["selected_chat_hash"]
    assert receipt["telegram"]["selected_chat_record_count"] == 1
    serialized = json.dumps(receipt)
    assert "1234567890" not in serialized
    assert "111111" not in serialized
    assert opener.sent_payloads == []


def test_operator_telegram_notify_sends_to_reachable_teable_chat() -> None:
    opener = _FakeOpener()

    receipt = notify.build_notification_receipt(
        principal_id="cf-email:tibor.girschele@gmail.com",
        text="Need BD billing handoff config.",
        dry_run=False,
        env_files=[],
        teable_base_url="https://app.teable.ai",
        teable_api_key="teable-secret",
        teable_base_id="bse-env",
        teable_table_id="",
        teable_table_name="ea_telegram_conversation_messages",
        bot_token="telegram-secret",
        opener=opener,
    )

    assert receipt["status"] == "sent"
    assert receipt["telegram"]["sent"] is True
    assert receipt["telegram"]["message_id_present"] is True
    assert len(opener.sent_payloads) == 1
    assert opener.sent_payloads[0]["chat_id"] == "1234567890"
    assert opener.sent_payloads[0]["disable_web_page_preview"] is True
