from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _client(
    *,
    principal_id: str = "exec-app-factory",
    public_results_enabled: bool = False,
    public_tours_enabled: bool = False,
    public_memorials_enabled: bool = False,
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_RESULTS"] = "1" if public_results_enabled else "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_TOURS"] = "1" if public_tours_enabled else "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_MEMORIALS"] = "1" if public_memorials_enabled else "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_SIDE_SURFACES"] = "1" if (public_results_enabled or public_tours_enabled or public_memorials_enabled) else "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_MEMORIALS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "0"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_app_factory_uses_helper_mount_functions() -> None:
    source = (REPO_ROOT / "ea/app/api/app.py").read_text(encoding="utf-8")

    assert "def _include_public_routes(" in source
    assert "def _include_authenticated_routes(" in source
    assert "_include_public_routes(" in source
    assert "_include_authenticated_routes(" in source


def test_app_factory_omits_optional_public_routes_by_default() -> None:
    client = _client()
    route_paths = {route.path for route in client.app.routes}

    assert "/results/{slug}" not in route_paths
    assert "/results/{slug}.json" not in route_paths
    assert "/tours/{slug}.json" not in route_paths
    assert "/tours/files/{slug}/{asset_path:path}" not in route_paths
    assert "/memorials/{slug}" not in route_paths
    assert "/memorials/files/{slug}/{asset_path:path}" not in route_paths


def test_app_factory_mounts_optional_public_routes_when_enabled() -> None:
    client = _client(public_results_enabled=True, public_tours_enabled=True, public_memorials_enabled=True)
    route_paths = {route.path for route in client.app.routes}

    assert "/results/{slug}" in route_paths
    assert "/results/{slug}.json" in route_paths
    assert "/results/files/{slug}/{asset_path:path}" in route_paths
    assert "/tours/{slug}.json" in route_paths
    assert "/tours/files/{slug}/{asset_path:path}" in route_paths
    assert "/memorials/{slug}" in route_paths
    assert "/memorials/{slug}.json" in route_paths
    assert "/memorials/files/{slug}/{asset_path:path}" in route_paths


def test_app_factory_propertyquarry_flags_win_over_ea_public_surface_flags() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "1"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "1"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "1"
    os.environ["EA_ENABLE_PUBLIC_MEMORIALS"] = "1"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_SIDE_SURFACES"] = "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_TOURS"] = "0"
    os.environ["PROPERTYQUARRY_ENABLE_PUBLIC_MEMORIALS"] = "0"

    from app.api.app import create_app

    client = TestClient(create_app())
    route_paths = {route.path for route in client.app.routes}
    assert "/results/{slug}" not in route_paths
    assert "/tours/{slug}.json" not in route_paths
    assert "/memorials/{slug}" not in route_paths


def test_app_factory_omits_legacy_authenticated_runtime_routes_by_default() -> None:
    client = _client()
    route_paths = {route.path for route in client.app.routes}

    assert "/v1/responses" not in route_paths
    assert "/v1/human/tasks" not in route_paths
    assert "/v1/channels/telegram/ingest" not in route_paths
    assert "/v1/providers/registry" not in route_paths
    assert "/v1/memory/candidates" in route_paths


def test_app_factory_mounts_legacy_authenticated_runtime_routes_when_enabled() -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = ""
    os.environ["PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES"] = "1"
    from app.api.app import create_app

    client = TestClient(create_app())
    route_paths = {route.path for route in client.app.routes}
    assert "/v1/responses" in route_paths
    assert "/v1/human/tasks" in route_paths
    assert "/v1/channels/telegram/ingest" in route_paths
    assert "/v1/providers/registry" in route_paths
    assert "/v1/memory/entities" in route_paths


def test_channels_route_lazy_loads_responses_module() -> None:
    source = (REPO_ROOT / "ea/app/api/routes/channels.py").read_text(encoding="utf-8")

    assert "def _responses_route_module():" in source
    assert 'return import_module("app.api.routes.responses")' in source
    assert "preload_non_channel_route_modules()" not in source
