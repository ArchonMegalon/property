from __future__ import annotations

import json
import pytest

from app.services import poppy_ai


def test_poppy_provider_posture_defaults_to_manual_board_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_POPPY_PROVIDER_ENABLED", raising=False)
    monkeypatch.delenv("EA_POPPY_API_ENABLED", raising=False)
    monkeypatch.delenv("EA_POPPY_CHATBOT_ENABLED", raising=False)
    monkeypatch.delenv("EA_POPPY_EA_MANUAL_BOARDS_ENABLED", raising=False)
    monkeypatch.delenv("POPPY_AI_API_KEY", raising=False)
    monkeypatch.delenv("POPPY_AI_ACCOUNT_EMAIL", raising=False)
    monkeypatch.delenv("POPPY_AI_BASE_URL", raising=False)

    posture = poppy_ai.poppy_provider_posture()

    assert posture.provider_enabled is False
    assert posture.api_enabled is False
    assert posture.chatbot_enabled is False
    assert posture.manual_boards_enabled is True
    assert posture.api_key_present is False
    assert posture.verification_status == "pending"
    assert posture.runtime_status == "manual_board_only"
    assert posture.base_url == "https://docs.getpoppy.ai"


def test_poppy_verify_account_becomes_verified_when_api_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_POPPY_PROVIDER_ENABLED", "1")
    monkeypatch.setenv("EA_POPPY_API_ENABLED", "1")
    monkeypatch.setenv("EA_POPPY_CHATBOT_ENABLED", "1")
    monkeypatch.setenv("POPPY_AI_API_KEY", "poppy-key-test")
    monkeypatch.setenv("POPPY_AI_ACCOUNT_EMAIL", "the.girscheles@gmail.com")
    monkeypatch.setenv("POPPY_AI_BASE_URL", "https://app.poppy.ai")

    body = poppy_ai.poppy_verify_account()

    assert body["service"] == "Poppy AI"
    assert body["status"] == "verified"
    assert body["runtime_status"] == "api_ready"
    assert body["api_enabled"] is True
    assert body["api_key_present"] is True
    assert body["chatbot_enabled"] is True
    assert body["account_email"] == "the.girscheles@gmail.com"
    assert body["base_url"] == "https://app.poppy.ai"
    assert body["reason"] == ""


def test_poppy_build_board_url_uses_configured_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_AI_BASE_URL", "https://app.poppy.ai")

    assert poppy_ai.poppy_build_board_url("board-123") == "https://app.poppy.ai/boards/board-123"
    assert poppy_ai.poppy_build_board_url("") == ""


def test_poppy_list_boards_uses_api_key_and_returns_board_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_AI_API_KEY", "poppy-key-test")
    monkeypatch.setenv("POPPY_AI_API_BASE_URL", "https://api.getpoppy.ai")
    monkeypatch.setenv("POPPY_AI_BASE_URL", "https://app.poppy.ai")

    seen: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"data": [{"id": "board-1", "name": "Property Dossier Board"}]}).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        seen["url"] = request.full_url
        seen["headers"] = {str(key).lower(): value for key, value in request.header_items()}
        return _Response()

    monkeypatch.setattr(poppy_ai, "urlopen", _fake_urlopen)

    body = poppy_ai.poppy_list_boards()

    assert seen["url"] == "https://api.getpoppy.ai/api/boards"
    assert seen["headers"]["api_key"] == "poppy-key-test"
    assert body["status"] == "ok"
    assert body["boards"] == [
        {
            "id": "board-1",
            "name": "Property Dossier Board",
            "board_url": "https://app.poppy.ai/boards/board-1",
        }
    ]


def test_poppy_list_chats_and_ask_knowledge_base_use_documented_query_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPY_AI_API_KEY", "poppy-key-test")
    monkeypatch.setenv("POPPY_AI_API_BASE_URL", "https://api.getpoppy.ai")

    seen: list[str] = []

    class _Response:
        def __init__(self, body: dict[str, object]) -> None:
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self._body).encode("utf-8")

    def _fake_urlopen(request, timeout=30):
        seen.append(request.full_url)
        if "/api/chats" in request.full_url:
            return _Response({"data": [{"id": "chat-1", "conversations": [{"id": "conv-1", "name": "Main"}]}]})
        return _Response({"text": "Draft summary from Poppy", "credits_used": 2, "credits_remaining": 9998})

    monkeypatch.setattr(poppy_ai, "urlopen", _fake_urlopen)

    chats = poppy_ai.poppy_list_chats(board_id="board-1")
    answer = poppy_ai.poppy_ask_knowledge_base(board_id="board-1", chat_id="chat-1", prompt="Summarize this property board")

    assert seen[0] == "https://api.getpoppy.ai/api/chats?board_id=board-1"
    assert "https://api.getpoppy.ai/api/conversation?board_id=board-1&chat_id=chat-1&prompt=Summarize+this+property+board&plaintext=true" == seen[1]
    assert chats["chats"][0]["conversations"] == [{"id": "conv-1", "name": "Main"}]
    assert answer["status"] == "ok"
    assert answer["text"] == "Draft summary from Poppy"
    assert answer["credits_used"] == 2
    assert answer["credits_remaining"] == 9998
