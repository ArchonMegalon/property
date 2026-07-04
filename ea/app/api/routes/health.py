from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_container
from app.container import AppContainer
from app.product.property_search_storage import property_search_run_retention_policy
from app.services.id_austria_oidc import id_austria_provider_readiness

router = APIRouter(tags=["system"])


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _release_manifest() -> dict[str, str]:
    public_origin = (
        _env_value("PROPERTYQUARRY_RELEASE_PUBLIC_ORIGIN")
        or _env_value("PROPERTYQUARRY_PUBLIC_BASE_URL")
        or _env_value("EA_PUBLIC_APP_BASE_URL")
    ).rstrip("/")
    payload = {
        "release_repository": _env_value("PROPERTYQUARRY_RELEASE_REPOSITORY"),
        "release_branch": _env_value("PROPERTYQUARRY_RELEASE_BRANCH"),
        "release_commit_sha": _env_value("PROPERTYQUARRY_RELEASE_COMMIT_SHA"),
        "release_deployment_id": _env_value("PROPERTYQUARRY_RELEASE_DEPLOYMENT_ID"),
        "release_public_origin": public_origin,
        "release_artifact_set": _env_value("PROPERTYQUARRY_RELEASE_ARTIFACT_SET"),
        "release_label": _env_value("PROPERTYQUARRY_RELEASE_LABEL"),
        "release_generated_at": _env_value("PROPERTYQUARRY_RELEASE_GENERATED_AT"),
    }
    required = (
        "release_repository",
        "release_branch",
        "release_commit_sha",
        "release_deployment_id",
        "release_public_origin",
        "release_artifact_set",
        "release_label",
    )
    payload["release_manifest_status"] = "complete" if all(payload.get(key) for key in required) else "incomplete"
    return payload


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return await health()


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready(container: AppContainer = Depends(get_container)) -> dict[str, str]:
    ready, reason = container.readiness.check()
    if not ready:
        raise HTTPException(status_code=503, detail=f"not_ready:{reason}")
    return {"status": "ready", "reason": reason}


@router.get("/version")
async def version(container: AppContainer = Depends(get_container)) -> dict[str, str]:
    payload = {
        "app_name": container.settings.app_name,
        "version": container.settings.app_version,
        "role": container.settings.role,
        "storage_backend": container.settings.storage_backend,
    }
    payload.update(_release_manifest())
    payload.update(property_search_run_retention_policy())
    payload.update(id_austria_provider_readiness())
    return payload
