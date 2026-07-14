from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app.api.dependencies import get_container, require_runtime_metrics_auth
from app.container import AppContainer
from app.observability import get_runtime_metrics


router = APIRouter(tags=["system"])


@router.get(
    "/internal/metrics",
    response_class=PlainTextResponse,
    include_in_schema=False,
    dependencies=[Depends(require_runtime_metrics_auth)],
)
async def runtime_metrics(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> PlainTextResponse:
    ready, _reason = container.readiness.check()
    payload = get_runtime_metrics(request.app).render_prometheus(readiness_ready=bool(ready))
    return PlainTextResponse(
        payload,
        media_type="text/plain; version=0.0.4",
        headers={"Cache-Control": "no-store"},
    )
