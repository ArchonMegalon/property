from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_container
from app.container import AppContainer
from app.repositories.property_packet_publications import build_property_packet_publication_repository
from app.services.dadan import DadanVideoRequestService, verify_dadan_webhook_secret


router = APIRouter(prefix="/v1/integrations/dadan", tags=["dadan"])


def _http_status_for_dadan_webhook_error(detail: str) -> int:
    if detail == "dadan_webhook_secret_not_configured":
        return 503
    if detail.endswith("_invalid") or detail.endswith("_disabled"):
        return 401
    return 400


@router.post("/webhooks/recording-submitted")
async def dadan_recording_submitted_webhook(
    request: Request,
    secret: str = "",
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    body = await request.body()
    if len(body) > 64_000:
        raise HTTPException(status_code=413, detail="dadan_webhook_body_too_large")
    try:
        secret_mode = verify_dadan_webhook_secret(headers=dict(request.headers), query_secret=secret)
    except PermissionError as exc:
        detail = str(exc or "dadan_webhook_secret_invalid")
        raise HTTPException(status_code=_http_status_for_dadan_webhook_error(detail), detail=detail) from exc
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="dadan_webhook_invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="dadan_webhook_invalid_payload")
    service = DadanVideoRequestService(repo=build_property_packet_publication_repository(container.settings))
    return service.ingest_recording_submitted_webhook(
        payload=payload,
        actor="dadan_webhook",
        secret_mode=secret_mode,
    )
