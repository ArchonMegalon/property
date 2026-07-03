from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

from app.services.tool_runtime import ToolRuntimeService

HEYY_WHATSAPP_CONNECTOR = "whatsapp_heyy"


def heyy_enabled() -> bool:
    return str(os.getenv("PROPERTYQUARRY_HEYY_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def require_heyy_enabled() -> None:
    if not heyy_enabled():
        raise RuntimeError("heyy_disabled")


def heyy_base_url() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_BASE_URL") or "https://api.heyy.io/api/v2.0").strip().rstrip("/")


def heyy_api_key() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_API_KEY") or "").strip()


def heyy_channel_id() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_WHATSAPP_CHANNEL_ID") or "").strip()


def heyy_webhook_secret() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_WEBHOOK_SECRET") or "").strip()


def heyy_daily_template_budget() -> int:
    try:
        return max(0, int(str(os.getenv("PROPERTYQUARRY_HEYY_MAX_TEMPLATE_MESSAGES_PER_DAY") or "5").strip()))
    except Exception:
        return 5


def heyy_property_match_template_id() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_TEMPLATE_PROPERTY_MATCH") or "").strip()


def heyy_property_alert_review_template_id() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_TEMPLATE_PROPERTY_ALERT_REVIEW") or heyy_property_match_template_id()).strip()


def heyy_search_agent_digest_template_id() -> str:
    return str(os.getenv("PROPERTYQUARRY_HEYY_TEMPLATE_SEARCH_AGENT_DIGEST") or "").strip()


def verify_heyy_webhook_secret(*, headers: dict[str, str], query_secret: str = "") -> str:
    expected = heyy_webhook_secret()
    if not expected:
        raise PermissionError("heyy_webhook_secret_not_configured")
    header = str(headers.get("x-propertyquarry-heyy-secret") or headers.get("x-heyy-webhook-secret") or "").strip()
    if header:
        if not hmac.compare_digest(header, expected):
            raise PermissionError("heyy_webhook_secret_invalid")
        return "header"
    if str(query_secret or "").strip():
        raise PermissionError("heyy_webhook_query_secret_disabled")
    raise PermissionError("heyy_webhook_secret_invalid")


def _normalize_phone_number_for_hash(phone_number: object) -> str:
    normalized = str(phone_number or "").strip()
    if not normalized:
        return ""
    digits = "".join(ch for ch in normalized if ch.isdigit())
    return f"+{digits}" if len(digits) >= 7 else normalized


def _phone_e164_hash(phone_number: object) -> str:
    normalized = _normalize_phone_number_for_hash(phone_number)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def redact_phone_number(phone_number: object) -> dict[str, str]:
    normalized = _normalize_phone_number_for_hash(phone_number)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    return {
        "phone_e164_hash": _phone_e164_hash(normalized),
        "phone_last4": digits[-4:] if len(digits) >= 4 else digits,
    }


def _safe_heyy_payload(payload: dict[str, object]) -> dict[str, object]:
    message = dict(payload.get("message") or {}) if isinstance(payload.get("message"), dict) else {}
    contact = dict(payload.get("contact") or {}) if isinstance(payload.get("contact"), dict) else {}
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}
    raw_text = str(message.get("text") or payload.get("text") or "").strip()
    normalized_upper = raw_text.upper()
    opt_command = normalized_upper if normalized_upper in {"STOP", "START", "HELP", "PAUSE"} else ""
    phone_meta = redact_phone_number(contact.get("phoneNumber") or payload.get("phoneNumber"))
    return {
        "event_type": str(payload.get("type") or payload.get("eventType") or payload.get("event_type") or "").strip(),
        "message_id": str(message.get("id") or payload.get("messageId") or payload.get("message_id") or "").strip(),
        "status": str(message.get("status") or payload.get("status") or "").strip(),
        "direction": str(message.get("direction") or payload.get("direction") or "").strip(),
        **phone_meta,
        "contact_id": str(contact.get("id") or payload.get("contactId") or "").strip(),
        "channel_id": str(payload.get("channelId") or payload.get("channel_id") or "").strip(),
        "text_present": bool(raw_text),
        "text_char_count": len(raw_text),
        "opt_command": opt_command,
        "principal_id": str(payload.get("principal_id") or metadata.get("principal_id") or "").strip(),
        "property_ref": str(payload.get("property_ref") or metadata.get("property_ref") or "").strip(),
        "search_agent_id": str(payload.get("search_agent_id") or metadata.get("search_agent_id") or "").strip(),
        "template_key": str(payload.get("template_key") or metadata.get("template_key") or "").strip(),
    }


def parse_heyy_webhook(payload: dict[str, object]) -> dict[str, object]:
    safe = _safe_heyy_payload(payload)
    raw_type = str(safe.get("event_type") or "").strip().lower()
    if raw_type in {"message.received", "whatsapp.message.received"}:
        normalized_type = "heyy_whatsapp_message_received"
    elif raw_type in {"message.sent", "message.updated", "whatsapp.message.status", "whatsapp.message.updated"}:
        normalized_type = "heyy_whatsapp_message_status"
    else:
        normalized_type = "heyy_whatsapp_webhook_received"
    return {
        "event_type": normalized_type,
        "principal_id": str(safe.get("principal_id") or "").strip(),
        "payload": safe,
    }


def _request(method: str, path: str, *, payload: dict[str, object] | None = None) -> dict[str, object]:
    api_key = heyy_api_key()
    if not api_key:
        raise RuntimeError("heyy_api_key_missing")
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{heyy_base_url()}/{path.lstrip('/')}",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"heyy_http_{exc.code}:{detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"heyy_unreachable:{exc.reason}") from exc
    parsed = json.loads(raw or "{}")
    return parsed if isinstance(parsed, dict) else {"items": parsed}


class HeyyWhatsAppBridgeService:
    def __init__(self, *, tool_runtime: ToolRuntimeService) -> None:
        self._tool_runtime = tool_runtime

    def plan_channel_binding(
        self,
        *,
        principal_id: str,
        channel_id: str,
        phone_number: str = "",
        label: str = "",
    ):
        normalized_channel_id = str(channel_id or "").strip() or heyy_channel_id()
        if not normalized_channel_id:
            raise ValueError("heyy_channel_id_required")
        return self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=HEYY_WHATSAPP_CONNECTOR,
            external_account_ref=str(phone_number or normalized_channel_id).strip() or normalized_channel_id,
            scope_json={"channel_id": normalized_channel_id},
            auth_metadata_json={
                "label": str(label or "").strip(),
                "provider": "heyy",
                "status": "planned_heyy_bridge",
            },
            status="planned",
        )

    def verify_channel(self, *, channel_id: str = "") -> dict[str, object]:
        normalized_channel_id = str(channel_id or "").strip() or heyy_channel_id()
        if not normalized_channel_id:
            raise ValueError("heyy_channel_id_required")
        channel = _request("GET", f"channels/{normalized_channel_id}")
        channel_data = channel.get("data") if isinstance(channel.get("data"), dict) else channel
        return {
            "status": "ready",
            "provider": "heyy",
            "channel_id": normalized_channel_id,
            "channel_type": str(channel_data.get("type") or "").strip(),
            "channel_status": str(channel_data.get("status") or "").strip(),
            "raw": channel,
        }

    def list_templates(self) -> dict[str, object]:
        payload = _request("GET", "message_templates")
        rows = list(payload.get("items") or payload.get("data") or payload.get("templates") or [])
        templates: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            templates.append(
                {
                    "template_id": str(row.get("id") or "").strip(),
                    "name": str(row.get("name") or "").strip(),
                    "status": str(row.get("status") or "").strip(),
                    "category": str(row.get("category") or "").strip(),
                    "language": str(row.get("language") or "").strip(),
                }
            )
        return {"status": "ready", "provider": "heyy", "templates": templates, "raw": payload}

    def send_template(
        self,
        *,
        phone_number: str,
        template_id: str,
        variables: list[dict[str, object]] | None = None,
        channel_id: str = "",
    ) -> dict[str, object]:
        require_heyy_enabled()
        normalized_channel_id = str(channel_id or "").strip() or heyy_channel_id()
        if not normalized_channel_id:
            raise ValueError("heyy_channel_id_required")
        normalized_phone = str(phone_number or "").strip()
        normalized_template_id = str(template_id or "").strip()
        if not normalized_phone:
            raise ValueError("heyy_phone_number_required")
        if not normalized_template_id:
            raise ValueError("heyy_template_id_required")
        payload = _request(
            "POST",
            f"{normalized_channel_id}/whatsapp_messages/send",
            payload={
                "phoneNumber": normalized_phone,
                "type": "TEMPLATE",
                "messageTemplateId": normalized_template_id,
                "variables": list(variables or []),
            },
        )
        message_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return {
            "status": "sent",
            "provider": "heyy",
            "channel_id": normalized_channel_id,
            "message_id": str(message_data.get("id") or message_data.get("messageId") or "").strip(),
            "delivery_status": str(message_data.get("status") or "").strip(),
            **redact_phone_number(normalized_phone),
            "raw": payload,
        }
