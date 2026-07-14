from __future__ import annotations

from functools import lru_cache
import pathlib
import re
import os

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_container
from app.container import AppContainer
from app.observability import runtime_build_identity
from app.product.property_search_storage import property_search_run_retention_policy
from app.services.id_austria_oidc import id_austria_provider_readiness

router = APIRouter(tags=["system"])


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _release_manifest() -> dict[str, str]:
    manifest_values = _load_release_manifest_values()
    public_origin = (
        _env_value("PROPERTYQUARRY_RELEASE_PUBLIC_ORIGIN")
        or _env_value("PROPERTYQUARRY_PUBLIC_BASE_URL")
        or _env_value("EA_PUBLIC_APP_BASE_URL")
    ).rstrip("/")
    payload = {
        "release_repository": _env_value("PROPERTYQUARRY_RELEASE_REPOSITORY") or manifest_values.get("release_repository", ""),
        "release_branch": _env_value("PROPERTYQUARRY_RELEASE_BRANCH") or manifest_values.get("release_branch", ""),
        "release_commit_sha": _env_value("PROPERTYQUARRY_RELEASE_COMMIT_SHA") or manifest_values.get("release_commit_sha", ""),
        "release_deployment_id": _env_value("PROPERTYQUARRY_RELEASE_DEPLOYMENT_ID") or manifest_values.get("release_deployment_id", ""),
        "release_public_origin": public_origin or manifest_values.get("release_public_origin", ""),
        "release_artifact_set": _env_value("PROPERTYQUARRY_RELEASE_ARTIFACT_SET") or manifest_values.get("release_artifact_set", ""),
        "release_label": _env_value("PROPERTYQUARRY_RELEASE_LABEL") or manifest_values.get("release_label", ""),
        "release_generated_at": _env_value("PROPERTYQUARRY_RELEASE_GENERATED_AT") or manifest_values.get("release_generated_at", ""),
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


@lru_cache(maxsize=1)
def _load_release_manifest_values() -> dict[str, str]:
    manifest_values: dict[str, str] = {}
    manifest_path = (
        pathlib.Path(__file__).resolve().parents[3]
        / "docs"
        / "PROPERTYQUARRY_RELEASE_MANIFEST.md"
    )
    if not manifest_path.exists():
        return manifest_values

    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return manifest_values

    for line in text.splitlines():
        parsed = _release_manifest_line_to_key_value(line)
        if parsed is None:
            continue
        key, value = parsed
        manifest_values[key] = value
    return manifest_values


def _release_manifest_line_to_key_value(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\|\s*([^|]+?)\s*\|\s*`([^`]*)`\s*\|$", line.strip())
    if not match:
        return None
    label = match.group(1).strip().lower()
    value = match.group(2).strip()
    mapping = {
        "product": "release_repository",
        "product repository": "release_repository",
        "release label": "release_label",
        "branch": "release_branch",
        "runtime commit sha": "release_commit_sha",
        "deployment id": "release_deployment_id",
        "public origin": "release_public_origin",
        "artifact set": "release_artifact_set",
    }
    key = mapping.get(label)
    if not key:
        return None
    return key, value


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
    payload.update(runtime_build_identity())
    payload.update(property_search_run_retention_policy())
    payload.update(id_austria_provider_readiness())
    return payload
