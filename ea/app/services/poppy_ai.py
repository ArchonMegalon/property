from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_DEFAULT_POPPY_API_BASE_URL = "https://api.getpoppy.ai"


_DEFAULT_POPPY_BASE_URL = "https://docs.getpoppy.ai"


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def poppy_base_url() -> str:
    return str(os.getenv("POPPY_AI_BASE_URL") or _DEFAULT_POPPY_BASE_URL).strip() or _DEFAULT_POPPY_BASE_URL


def poppy_api_base_url() -> str:
    return str(os.getenv("POPPY_AI_API_BASE_URL") or _DEFAULT_POPPY_API_BASE_URL).strip() or _DEFAULT_POPPY_API_BASE_URL


def poppy_api_key() -> str:
    return str(os.getenv("POPPY_AI_API_KEY") or "").strip()


def poppy_account_email() -> str:
    return str(os.getenv("POPPY_AI_ACCOUNT_EMAIL") or "").strip()


def poppy_provider_enabled() -> bool:
    return _env_flag("EA_POPPY_PROVIDER_ENABLED", default=False)


def poppy_api_enabled() -> bool:
    return _env_flag("EA_POPPY_API_ENABLED", default=False)


def poppy_chatbot_enabled() -> bool:
    return _env_flag("EA_POPPY_CHATBOT_ENABLED", default=False)


def poppy_manual_boards_enabled() -> bool:
    return _env_flag("EA_POPPY_EA_MANUAL_BOARDS_ENABLED", default=True)


@dataclass(frozen=True)
class PoppyProviderPosture:
    provider_enabled: bool
    api_enabled: bool
    chatbot_enabled: bool
    manual_boards_enabled: bool
    api_key_present: bool
    account_email: str
    base_url: str
    verification_status: str
    runtime_status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_enabled": self.provider_enabled,
            "api_enabled": self.api_enabled,
            "chatbot_enabled": self.chatbot_enabled,
            "manual_boards_enabled": self.manual_boards_enabled,
            "api_key_present": self.api_key_present,
            "account_email": self.account_email,
            "base_url": self.base_url,
            "verification_status": self.verification_status,
            "runtime_status": self.runtime_status,
        }


def poppy_provider_posture() -> PoppyProviderPosture:
    provider_enabled = poppy_provider_enabled()
    api_enabled = poppy_api_enabled()
    api_key_present = bool(poppy_api_key())
    verification_status = "verified" if provider_enabled and api_enabled and api_key_present else "pending"
    runtime_status = "api_ready" if verification_status == "verified" else ("manual_board_only" if poppy_manual_boards_enabled() else "disabled")
    return PoppyProviderPosture(
        provider_enabled=provider_enabled,
        api_enabled=api_enabled,
        chatbot_enabled=poppy_chatbot_enabled(),
        manual_boards_enabled=poppy_manual_boards_enabled(),
        api_key_present=api_key_present,
        account_email=poppy_account_email(),
        base_url=poppy_base_url(),
        verification_status=verification_status,
        runtime_status=runtime_status,
    )


def poppy_verify_account() -> dict[str, object]:
    posture = poppy_provider_posture()
    return {
        "service": "Poppy AI",
        "status": posture.verification_status,
        "runtime_status": posture.runtime_status,
        "api_enabled": posture.api_enabled,
        "api_key_present": posture.api_key_present,
        "chatbot_enabled": posture.chatbot_enabled,
        "manual_boards_enabled": posture.manual_boards_enabled,
        "account_email": posture.account_email,
        "base_url": posture.base_url,
        "reason": "" if posture.verification_status == "verified" else "poppy_api_not_verified",
    }


def poppy_build_board_url(board_id: str) -> str:
    normalized = str(board_id or "").strip().strip("/")
    if not normalized:
        return ""
    base = poppy_base_url().rstrip("/")
    return f"{base}/boards/{normalized}"


class PoppyApiError(RuntimeError):
    pass


def _poppy_headers() -> dict[str, str]:
    api_key = poppy_api_key()
    if not api_key:
        raise PoppyApiError("poppy_api_key_missing")
    return {
        "api_key": api_key,
        "Accept": "application/json",
    }


def _poppy_request(*, method: str, path: str, query: dict[str, object] | None = None) -> dict[str, object]:
    normalized_path = "/" + str(path or "").lstrip("/")
    params = {str(key): value for key, value in dict(query or {}).items() if value is not None and str(value) != ""}
    url = poppy_api_base_url().rstrip("/") + normalized_path
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers=_poppy_headers(), method=method.upper())
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise PoppyApiError("poppy_invalid_response")
    return payload


def poppy_list_boards() -> dict[str, object]:
    payload = _poppy_request(method="GET", path="/api/boards")
    boards: list[dict[str, str]] = []
    for item in list(payload.get("data") or []):
        if not isinstance(item, dict):
            continue
        board_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not board_id:
            continue
        boards.append(
            {
                "id": board_id,
                "name": name,
                "board_url": poppy_build_board_url(board_id),
            }
        )
    return {
        "status": "ok",
        "boards": boards,
    }


def poppy_list_chats(*, board_id: str) -> dict[str, object]:
    normalized_board_id = str(board_id or "").strip()
    if not normalized_board_id:
        raise PoppyApiError("poppy_board_id_required")
    payload = _poppy_request(method="GET", path="/api/chats", query={"board_id": normalized_board_id})
    chats: list[dict[str, object]] = []
    for item in list(payload.get("data") or []):
        if not isinstance(item, dict):
            continue
        chat_id = str(item.get("id") or "").strip()
        if not chat_id:
            continue
        conversations = []
        for conversation in list(item.get("conversations") or []):
            if not isinstance(conversation, dict):
                continue
            conversation_id = str(conversation.get("id") or "").strip()
            if not conversation_id:
                continue
            conversations.append(
                {
                    "id": conversation_id,
                    "name": str(conversation.get("name") or "").strip(),
                }
            )
        chats.append(
            {
                "id": chat_id,
                "conversations": conversations,
            }
        )
    return {
        "status": "ok",
        "board_id": normalized_board_id,
        "chats": chats,
    }


def poppy_ask_knowledge_base(
    *,
    board_id: str,
    chat_id: str,
    prompt: str,
    model: str = "",
    additional_context: str = "",
    plaintext: bool = True,
) -> dict[str, object]:
    normalized_board_id = str(board_id or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_prompt = str(prompt or "").strip()
    if not normalized_board_id:
        raise PoppyApiError("poppy_board_id_required")
    if not normalized_chat_id:
        raise PoppyApiError("poppy_chat_id_required")
    if not normalized_prompt:
        raise PoppyApiError("poppy_prompt_required")
    query: dict[str, object] = {
        "board_id": normalized_board_id,
        "chat_id": normalized_chat_id,
        "prompt": normalized_prompt,
    }
    if model:
        query["model"] = str(model).strip()
    if additional_context:
        query["additional_context"] = str(additional_context).strip()
    if plaintext:
        query["plaintext"] = "true"
    payload = _poppy_request(method="GET", path="/api/conversation", query=query)
    return {
        "status": "ok",
        "board_id": normalized_board_id,
        "chat_id": normalized_chat_id,
        "text": str(payload.get("text") or "").strip(),
        "credits_used": payload.get("credits_used"),
        "credits_remaining": payload.get("credits_remaining"),
    }
