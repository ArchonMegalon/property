from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
import pytest

from app.api.app import PropertyQuarryReleaseIdentityMiddleware
from app.api.dependencies import get_container
from app.api.routes import health


COMMIT_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + ("b" * 64)
DEPLOYMENT_ID = "propertyquarry-governed-deploy-aaaaaaaaaaaa"
MANIFEST_SHA256 = "c" * 64
REPLICA_ID = "propertyquarry-api-7f489d8d5d-k9r2p"
IDENTITY = {
    "release_commit_sha": COMMIT_SHA,
    "release_image_digest": IMAGE_DIGEST,
    "release_deployment_id": DEPLOYMENT_ID,
    "release_manifest_status": "complete",
    "release_manifest_sha256": MANIFEST_SHA256,
    "replica_id": REPLICA_ID,
}
IDENTITY_HEADERS = {
    header_name.lower(): IDENTITY[field]
    for field, header_name in health.RELEASE_IDENTITY_RESPONSE_HEADERS
}


def _identity_headers(response: Response) -> dict[str, str]:
    return {
        name.lower(): value
        for name, value in response.headers.items()
        if name.lower().startswith("x-propertyquarry-")
    }


def _middleware_client() -> TestClient:
    app = FastAPI()

    @app.api_route("/app/search", methods=["GET", "HEAD"])
    async def search() -> Response:
        # The middleware must replace, rather than append to, a downstream
        # identity assertion so one response has one authoritative envelope.
        return Response(
            content="search",
            media_type="text/plain",
            headers={"X-PropertyQuarry-Release-Commit": "forged"},
        )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        PropertyQuarryReleaseIdentityMiddleware,
        identity_provider=lambda: dict(IDENTITY),
    )
    return TestClient(app)


@pytest.mark.parametrize("method", ("GET", "HEAD"))
def test_search_document_carries_exact_release_identity_headers(method: str) -> None:
    response = _middleware_client().request(method, "/app/search")

    assert response.status_code == 200
    assert _identity_headers(response) == IDENTITY_HEADERS
    assert len(_identity_headers(response)) == 6


def test_release_identity_headers_are_not_attached_to_other_routes() -> None:
    response = _middleware_client().get("/health")

    assert response.status_code == 200
    assert _identity_headers(response) == {}


def test_release_runtime_identity_returns_the_exact_bounded_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "runtime_build_identity",
        lambda: {
            "release_commit_sha": "runtime-must-not-authorize-commit",
            "release_image_digest": IMAGE_DIGEST,
            "replica_id": REPLICA_ID,
        },
    )
    monkeypatch.setattr(
        health,
        "_release_manifest",
        lambda: {
            "release_commit_sha": COMMIT_SHA,
            "release_deployment_id": DEPLOYMENT_ID,
            "release_manifest_status": "complete",
            "release_manifest_sha256": MANIFEST_SHA256,
        },
    )

    assert health.release_runtime_identity() == IDENTITY


@pytest.mark.parametrize(
    ("source", "field", "unsafe_value", "bounded_field", "bounded_value"),
    (
        ("manifest", "release_commit_sha", "A" * 40, "release_commit_sha", ""),
        ("manifest", "release_commit_sha", True, "release_commit_sha", ""),
        (
            "runtime",
            "release_image_digest",
            "sha256:" + ("B" * 64),
            "release_image_digest",
            "",
        ),
        ("runtime", "release_image_digest", True, "release_image_digest", ""),
        (
            "manifest",
            "release_deployment_id",
            "production\r\nX-Injected: yes",
            "release_deployment_id",
            "",
        ),
        ("manifest", "release_deployment_id", "d" * 129, "release_deployment_id", ""),
        ("manifest", "release_deployment_id", True, "release_deployment_id", ""),
        ("runtime", "replica_id", "replica id", "replica_id", ""),
        ("runtime", "replica_id", "r" * 129, "replica_id", ""),
        ("runtime", "replica_id", True, "replica_id", ""),
        (
            "manifest",
            "release_manifest_status",
            "complete\r\nX-Injected: yes",
            "release_manifest_status",
            "invalid",
        ),
        (
            "manifest",
            "release_manifest_sha256",
            "C" * 64,
            "release_manifest_sha256",
            "",
        ),
        (
            "manifest",
            "release_manifest_sha256",
            True,
            "release_manifest_sha256",
            "",
        ),
    ),
)
def test_release_runtime_identity_fails_closed_for_invalid_or_unsafe_values(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    field: str,
    unsafe_value: object,
    bounded_field: str,
    bounded_value: str,
) -> None:
    runtime: dict[str, object] = {
        "release_image_digest": IMAGE_DIGEST,
        "replica_id": REPLICA_ID,
    }
    manifest: dict[str, object] = {
        "release_commit_sha": COMMIT_SHA,
        "release_deployment_id": DEPLOYMENT_ID,
        "release_manifest_status": "complete",
        "release_manifest_sha256": MANIFEST_SHA256,
    }
    target = runtime if source == "runtime" else manifest
    target[field] = unsafe_value
    monkeypatch.setattr(health, "runtime_build_identity", lambda: runtime)
    monkeypatch.setattr(health, "_release_manifest", lambda: manifest)

    identity = health.release_runtime_identity()

    assert set(identity) == set(IDENTITY)
    assert all(isinstance(value, str) for value in identity.values())
    assert identity[bounded_field] == bounded_value


def test_version_reuses_the_exact_bounded_runtime_identity_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health,
        "runtime_build_identity",
        lambda: {
            "release_commit_sha": "runtime-must-not-authorize-commit",
            "release_image_digest": IMAGE_DIGEST,
            "replica_id": REPLICA_ID,
        },
    )
    monkeypatch.setattr(
        health,
        "_release_manifest",
        lambda: {
            "release_commit_sha": COMMIT_SHA,
            "release_deployment_id": DEPLOYMENT_ID,
            "release_manifest_status": "complete",
            "release_manifest_sha256": MANIFEST_SHA256,
        },
    )
    monkeypatch.setattr(health, "property_search_run_retention_policy", lambda: {})
    monkeypatch.setattr(health, "id_austria_provider_readiness", lambda: {})

    container = SimpleNamespace(
        settings=SimpleNamespace(
            app_name="PropertyQuarry",
            app_version="flagship-test",
            role="api",
            storage_backend="memory",
        )
    )
    app = FastAPI()
    app.include_router(health.router)
    app.dependency_overrides[get_container] = lambda: container

    response = TestClient(app).get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert {field: payload[field] for field in IDENTITY} == IDENTITY
