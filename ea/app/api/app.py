from __future__ import annotations

from functools import lru_cache
from importlib import import_module

from fastapi import APIRouter, Depends, FastAPI

from app.api.dependencies import require_request_auth
from app.api.errors import install_error_handlers
from app.api.threadpool_compat import inline_sync_handlers_enabled, install_inline_threadpool_compat
from app.container import build_container
from app.settings import get_settings, validate_startup_settings


async def _prewarm_provider_health_cache() -> None:
    try:
        from app.api.routes.responses import prewarm_provider_health_snapshot_cache

        await prewarm_provider_health_snapshot_cache(lightweight=True)
    except Exception:
        return


def _include_public_routes(
    app: FastAPI,
    *,
    settings,
    public_documents_router: APIRouter,
    landing_setup_router: APIRouter,
    landing_actions_router: APIRouter,
    landing_channel_router: APIRouter,
    landing_objects_router: APIRouter,
    landing_workspace_router: APIRouter,
    landing_router: APIRouter,
    fliplink_public_router: APIRouter,
    dadan_public_router: APIRouter,
    heyy_public_router: APIRouter,
    health_router: APIRouter,
    register_router: APIRouter,
) -> None:
    app.include_router(public_documents_router)
    app.include_router(landing_setup_router)
    app.include_router(landing_actions_router)
    app.include_router(landing_channel_router)
    app.include_router(landing_objects_router)
    app.include_router(landing_workspace_router)
    app.include_router(landing_router)
    app.include_router(fliplink_public_router)
    app.include_router(dadan_public_router)
    app.include_router(heyy_public_router)
    if settings.public_results_enabled:
        from app.api.routes.public_results import router as public_results_router

        app.include_router(public_results_router)
    if settings.public_tours_enabled:
        from app.api.routes.public_tours import router as public_tours_router

        app.include_router(public_tours_router)
    if settings.public_memorials_enabled:
        from app.api.routes.public_memorials import router as public_memorials_router

        app.include_router(public_memorials_router)
    app.include_router(health_router)
    app.include_router(register_router)


def _include_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    onboarding_router: APIRouter,
    images_router: APIRouter,
    google_oauth_router: APIRouter,
    channels_router: APIRouter,
    memory_router: APIRouter,
    product_api_delivery_router: APIRouter,
    product_api_workspace_router: APIRouter,
    product_api_router: APIRouter,
    fliplink_authenticated_router: APIRouter,
    policy_router: APIRouter,
    providers_router: APIRouter,
    plans_router: APIRouter,
    rewrite_router: APIRouter,
    runtime_router: APIRouter,
) -> None:
    app.include_router(onboarding_router, dependencies=auth_dependency)
    app.include_router(images_router, dependencies=auth_dependency)
    app.include_router(google_oauth_router)
    app.include_router(channels_router, dependencies=auth_dependency)
    app.include_router(memory_router, dependencies=auth_dependency)
    app.include_router(product_api_delivery_router, dependencies=auth_dependency)
    app.include_router(product_api_workspace_router, dependencies=auth_dependency)
    app.include_router(product_api_router, dependencies=auth_dependency)
    app.include_router(fliplink_authenticated_router, dependencies=auth_dependency)
    app.include_router(policy_router, dependencies=auth_dependency)
    app.include_router(providers_router, dependencies=auth_dependency)
    app.include_router(plans_router, dependencies=auth_dependency)
    app.include_router(rewrite_router, dependencies=auth_dependency)
    app.include_router(runtime_router, dependencies=auth_dependency)


def _router_without_paths(router: APIRouter, *, excluded_paths: set[str]) -> APIRouter:
    filtered = APIRouter()
    for route in router.routes:
        if getattr(route, "path", "") in excluded_paths:
            continue
        filtered.routes.append(route)
    return filtered


def _include_legacy_authenticated_routes(
    app: FastAPI,
    *,
    auth_dependency: list,
    channels_router: APIRouter,
    human_router: APIRouter,
    memory_router: APIRouter,
    evidence_router: APIRouter,
    observations_router: APIRouter,
    delivery_router: APIRouter,
    connectors_router: APIRouter,
    policy_router: APIRouter,
    providers_router: APIRouter,
    ltd_runtime_router: APIRouter,
    plans_router: APIRouter,
    skills_router: APIRouter,
    task_contracts_router: APIRouter,
    tools_router: APIRouter,
    responses_router: APIRouter,
) -> None:
    app.include_router(channels_router, dependencies=auth_dependency)
    app.include_router(human_router, dependencies=auth_dependency)
    app.include_router(memory_router, dependencies=auth_dependency)
    app.include_router(evidence_router, dependencies=auth_dependency)
    app.include_router(observations_router, dependencies=auth_dependency)
    app.include_router(delivery_router, dependencies=auth_dependency)
    app.include_router(connectors_router, dependencies=auth_dependency)
    app.include_router(policy_router, dependencies=auth_dependency)
    app.include_router(providers_router, dependencies=auth_dependency)
    app.include_router(ltd_runtime_router, dependencies=auth_dependency)
    app.include_router(plans_router, dependencies=auth_dependency)
    app.include_router(skills_router, dependencies=auth_dependency)
    app.include_router(task_contracts_router, dependencies=auth_dependency)
    app.include_router(tools_router, dependencies=auth_dependency)
    app.include_router(responses_router, dependencies=auth_dependency)


@lru_cache(maxsize=1)
def _load_core_route_modules() -> dict[str, object]:
    modules = {
        "fliplink_integration": import_module("app.api.routes.fliplink_integration"),
        "dadan_integration": import_module("app.api.routes.dadan_integration"),
        "heyy_integration": import_module("app.api.routes.heyy_integration"),
        "google_oauth": import_module("app.api.routes.google_oauth"),
        "health": import_module("app.api.routes.health"),
        "images": import_module("app.api.routes.images"),
        "landing_actions": import_module("app.api.routes.landing_actions"),
        "landing_channel": import_module("app.api.routes.landing_channel"),
        "public_documents": import_module("app.api.routes.public_documents"),
        "landing": import_module("app.api.routes.landing"),
        "landing_objects": import_module("app.api.routes.landing_objects"),
        "landing_setup": import_module("app.api.routes.landing_setup"),
        "landing_workspace": import_module("app.api.routes.landing_workspace"),
        "memory": import_module("app.api.routes.memory"),
        "observations": import_module("app.api.routes.observations"),
        "onboarding": import_module("app.api.routes.onboarding"),
        "plans": import_module("app.api.routes.plans"),
        "policy": import_module("app.api.routes.policy"),
        "providers": import_module("app.api.routes.providers"),
        "product_api": import_module("app.api.routes.product_api"),
        "product_api_delivery": import_module("app.api.routes.product_api_delivery"),
        "product_api_workspace": import_module("app.api.routes.product_api_workspace"),
        "rewrite": import_module("app.api.routes.rewrite"),
        "runtime": import_module("app.api.routes.runtime"),
    }
    return modules


@lru_cache(maxsize=1)
def _load_legacy_route_modules() -> dict[str, object]:
    modules = {
        "connectors": import_module("app.api.routes.connectors"),
        "delivery": import_module("app.api.routes.delivery"),
        "evidence": import_module("app.api.routes.evidence"),
        "human": import_module("app.api.routes.human"),
        "ltd_runtime": import_module("app.api.routes.ltd_runtime"),
        "responses": import_module("app.api.routes.responses"),
        "skills": import_module("app.api.routes.skills"),
        "task_contracts": import_module("app.api.routes.task_contracts"),
        "tools": import_module("app.api.routes.tools"),
    }
    return modules


def preload_non_channel_route_modules(*, include_legacy: bool = False) -> None:
    _load_core_route_modules()
    if include_legacy:
        _load_legacy_route_modules()


def create_app() -> FastAPI:
    s = get_settings()
    validate_startup_settings(s)
    if inline_sync_handlers_enabled():
        install_inline_threadpool_compat()
    from app.api.routes.channels import router as channels_router

    route_modules = _load_core_route_modules()
    fliplink_authenticated_router = route_modules["fliplink_integration"].authenticated_router
    fliplink_public_router = route_modules["fliplink_integration"].public_router
    dadan_public_router = route_modules["dadan_integration"].router
    heyy_public_router = route_modules["heyy_integration"].router
    google_oauth_router = route_modules["google_oauth"].router
    health_router = route_modules["health"].router
    images_router = route_modules["images"].router
    landing_actions_router = route_modules["landing_actions"].router
    landing_channel_router = route_modules["landing_channel"].router
    public_documents_router = route_modules["public_documents"].router
    landing_router = route_modules["landing"].router
    landing_objects_router = route_modules["landing_objects"].router
    landing_setup_router = route_modules["landing_setup"].router
    landing_workspace_router = route_modules["landing_workspace"].router
    observations_router = route_modules["observations"].router
    memory_router = route_modules["memory"].router
    register_router = route_modules["onboarding"].register_router
    onboarding_router = route_modules["onboarding"].router
    plans_router = route_modules["plans"].router
    policy_router = route_modules["policy"].router
    providers_router = route_modules["providers"].router
    product_api_router = route_modules["product_api"].router
    product_api_delivery_router = route_modules["product_api_delivery"].router
    product_api_workspace_router = route_modules["product_api_workspace"].router
    rewrite_router = route_modules["rewrite"].router
    runtime_router = route_modules["runtime"].router
    app = FastAPI(title=s.app_name, version=s.app_version, docs_url="/api/docs", redoc_url="/api/redoc")
    install_error_handlers(app)
    app.state.container = build_container(settings=s)
    if s.legacy_runtime_surfaces_enabled:
        app.router.on_startup.append(_prewarm_provider_health_cache)
    _include_public_routes(
        app,
        settings=s,
        public_documents_router=public_documents_router,
        landing_setup_router=landing_setup_router,
        landing_actions_router=landing_actions_router,
        landing_channel_router=landing_channel_router,
        landing_objects_router=landing_objects_router,
        landing_workspace_router=landing_workspace_router,
        landing_router=landing_router,
        fliplink_public_router=fliplink_public_router,
        dadan_public_router=dadan_public_router,
        heyy_public_router=heyy_public_router,
        health_router=health_router,
        register_router=register_router,
    )
    auth_dependency = [Depends(require_request_auth)]
    _include_authenticated_routes(
        app,
        auth_dependency=auth_dependency,
        onboarding_router=onboarding_router,
        images_router=images_router,
        google_oauth_router=google_oauth_router,
        channels_router=_router_without_paths(channels_router, excluded_paths={"/v1/channels/telegram/ingest"}),
        memory_router=memory_router,
        product_api_delivery_router=product_api_delivery_router,
        product_api_workspace_router=product_api_workspace_router,
        product_api_router=product_api_router,
        fliplink_authenticated_router=fliplink_authenticated_router,
        policy_router=policy_router,
        providers_router=(
            providers_router
            if s.legacy_runtime_surfaces_enabled
            else _router_without_paths(providers_router, excluded_paths={"/v1/providers/registry"})
        ),
        plans_router=plans_router,
        rewrite_router=rewrite_router,
        runtime_router=runtime_router,
    )
    if s.legacy_runtime_surfaces_enabled:
        legacy_route_modules = _load_legacy_route_modules()
        connectors_router = legacy_route_modules["connectors"].router
        delivery_router = legacy_route_modules["delivery"].router
        evidence_router = legacy_route_modules["evidence"].router
        human_router = legacy_route_modules["human"].router
        ltd_runtime_router = legacy_route_modules["ltd_runtime"].router
        responses_router = legacy_route_modules["responses"].router
        skills_router = legacy_route_modules["skills"].router
        task_contracts_router = legacy_route_modules["task_contracts"].router
        tools_router = legacy_route_modules["tools"].router

        _include_legacy_authenticated_routes(
            app,
            auth_dependency=auth_dependency,
            channels_router=channels_router,
            human_router=human_router,
            memory_router=memory_router,
            evidence_router=evidence_router,
            observations_router=observations_router,
            delivery_router=delivery_router,
            connectors_router=connectors_router,
            policy_router=policy_router,
            providers_router=providers_router,
            ltd_runtime_router=ltd_runtime_router,
            plans_router=plans_router,
            skills_router=skills_router,
            task_contracts_router=task_contracts_router,
            tools_router=tools_router,
            responses_router=responses_router,
        )
    return app
