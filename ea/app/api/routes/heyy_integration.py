from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.container import AppContainer
from app.api.dependencies import get_container
from app.services.fliplink.service import build_fliplink_packet_service
from app.services.heyy_whatsapp_service import parse_heyy_webhook, verify_heyy_webhook_secret

router = APIRouter(prefix="/v1/integrations/heyy", tags=["heyy"])


def _http_status_for_heyy_webhook_error(detail: str) -> int:
    if detail == "heyy_webhook_secret_not_configured":
        return 503
    if detail in {"heyy_webhook_secret_invalid", "heyy_webhook_query_secret_disabled"}:
        return 403
    return 400


@router.post("/whatsapp/webhook")
async def heyy_whatsapp_webhook(
    request: Request,
    secret: str = "",
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    try:
        secret_mode = verify_heyy_webhook_secret(headers=dict(request.headers), query_secret=secret)
    except PermissionError as exc:
        detail = str(exc or "heyy_webhook_secret_invalid")
        raise HTTPException(status_code=_http_status_for_heyy_webhook_error(detail), detail=detail) from exc
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="heyy_webhook_invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="heyy_webhook_invalid_payload")
    parsed = parse_heyy_webhook(payload)
    packet_service = build_fliplink_packet_service(container)
    event = packet_service._repo.record_event(  # noqa: SLF001
        {
            "publication_id": "",
            "principal_id": str(parsed.get("principal_id") or "").strip(),
            "event_type": str(parsed.get("event_type") or "heyy_whatsapp_webhook_received").strip(),
            "actor": "heyy_webhook",
            "payload_json": {
                **dict(parsed.get("payload") or {}),
                "secret_mode": secret_mode,
            },
        }
    )
    return {
        "status": "accepted",
        "event_id": str(event.get("event_id") or ""),
        "event_type": str(parsed.get("event_type") or "").strip(),
    }
