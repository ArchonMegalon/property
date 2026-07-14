from __future__ import annotations

import ipaddress
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from app.api.dependencies import RequestContext, get_request_context, require_runtime_metrics_auth
from app.api.errors import install_error_handlers
from app.api.principal_identity import (
    PRINCIPAL_ASSERTION_AUDIENCE_HEADER,
    PRINCIPAL_ASSERTION_NONCE_HEADER,
    PRINCIPAL_ASSERTION_SIGNATURE_HEADER,
    PRINCIPAL_ASSERTION_TIMESTAMP_HEADER,
    PRINCIPAL_ID_HEADER,
    VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY,
    PrincipalIdentityMiddleware,
    PrincipalIdentityPolicy,
    VerifiedPrincipalAssertion,
    principal_assertion_signature,
)
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.settings import RuntimeProfile


_NOW = 1_800_000_000
_ASSERTION_SECRET = "edge-assertion-secret-that-is-separate-0001"
_ASSERTION_AUDIENCE = "propertyquarry-api"
_LOOPBACK_NETWORKS = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"))


def _container(*, mode: str, api_token: str = "shared-token") -> SimpleNamespace:
    auth_mode = "token" if api_token else "anonymous_dev"
    principal_source = "verified_identity" if mode == "prod" else "caller_header_or_default"
    settings = SimpleNamespace(
        auth=SimpleNamespace(
            api_token=api_token,
            default_principal_id="safe-default",
            signing_secret="workspace-signing-secret",
            allow_loopback_no_auth=False,
            cf_access_team_domain="",
            cf_access_audiences=(),
            cf_access_certs_url="",
        ),
        runtime=SimpleNamespace(mode=mode),
        storage=SimpleNamespace(backend="memory", database_url=""),
        database_url="",
    )
    profile = RuntimeProfile(
        mode=mode,
        storage_backend="postgres" if mode == "prod" else "memory",
        durability="durable" if mode == "prod" else "ephemeral",
        auth_mode=auth_mode,
        principal_source=principal_source,
        database_required=mode == "prod",
        database_configured=mode == "prod",
        source_backend="postgres" if mode == "prod" else "memory",
    )
    return SimpleNamespace(settings=settings, runtime_profile=profile)


def _policy(
    *,
    mode: str = "prod",
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = _LOOPBACK_NETWORKS,
    assertions_enabled: bool = True,
) -> PrincipalIdentityPolicy:
    return PrincipalIdentityPolicy(
        runtime_mode=mode,
        trusted_proxy_cidrs=networks,
        assertion_secret=_ASSERTION_SECRET if assertions_enabled else "",
        assertion_audience=_ASSERTION_AUDIENCE if assertions_enabled else "",
        assertion_max_age_seconds=120,
        assertion_future_skew_seconds=15,
        assertion_nonce_capacity=256,
    )


def _identity_app(
    *,
    mode: str = "prod",
    api_token: str = "shared-token",
    policy: PrincipalIdentityPolicy | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.container = _container(mode=mode, api_token=api_token)
    app.add_middleware(
        PrincipalIdentityMiddleware,
        policy=policy or _policy(mode=mode),
        clock=lambda: float(_NOW),
    )
    install_error_handlers(app)

    @app.get("/who")
    def who(
        request: Request,
        context: RequestContext = Depends(get_request_context),
    ) -> dict[str, object]:
        return {
            "principal_id": context.principal_id,
            "auth_source": context.auth_source,
            "operator_id": context.operator_id,
            "stripped": list(getattr(request.state, "identity_headers_stripped", ())),
        }

    @app.get("/system", dependencies=[Depends(require_runtime_metrics_auth)])
    def system() -> dict[str, bool]:
        return {"ok": True}

    return app


def _assertion_headers(
    *,
    principal_id: str,
    nonce: str,
    timestamp: int = _NOW,
    audience: str = _ASSERTION_AUDIENCE,
    method: str = "GET",
    path: str = "/who",
    query_string: str = "",
) -> dict[str, str]:
    signature = principal_assertion_signature(
        secret=_ASSERTION_SECRET,
        method=method,
        path=path,
        query_string=query_string,
        principal_id=principal_id,
        timestamp=timestamp,
        nonce=nonce,
        audience=audience,
    )
    return {
        PRINCIPAL_ID_HEADER: principal_id,
        PRINCIPAL_ASSERTION_TIMESTAMP_HEADER: str(timestamp),
        PRINCIPAL_ASSERTION_NONCE_HEADER: nonce,
        PRINCIPAL_ASSERTION_AUDIENCE_HEADER: audience,
        PRINCIPAL_ASSERTION_SIGNATURE_HEADER: signature,
    }


def _request(*, headers: dict[str, str], state: dict[str, object] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/who",
            "query_string": b"",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
            "client": ("127.0.0.1", 50000),
            "state": dict(state or {}),
        }
    )


def test_shared_production_bearer_cannot_select_or_cross_tenants_with_headers() -> None:
    app = _identity_app(policy=_policy(assertions_enabled=False))
    client = TestClient(app, client=("127.0.0.1", 50000))

    for attempted_principal in ("tenant-a", "tenant-b"):
        response = client.get(
            "/who",
            headers={
                "Authorization": "Bearer shared-token",
                "X-EA-Principal-ID": attempted_principal,
                "X-Principal-ID": attempted_principal,
                "X-EA-Tenant-ID": attempted_principal,
                "X-EA-Operator-ID": "spoofed-operator",
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "principal_required"

    system_response = client.get(
        "/system",
        headers={
            "Authorization": "Bearer shared-token",
            "X-EA-Principal-ID": "tenant-b",
        },
    )
    assert system_response.status_code == 200
    assert system_response.json() == {"ok": True}


def test_valid_edge_assertion_wins_over_related_spoof_headers_and_is_stripped() -> None:
    app = _identity_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = _assertion_headers(
        principal_id="tenant-a",
        nonce="nonce-edge-tenant-a-0001",
    )
    headers.update(
        {
            "Authorization": "Bearer shared-token",
            "X-Principal-ID": "tenant-b",
            "X-EA-Tenant-ID": "tenant-b",
            "X-EA-Operator-ID": "spoofed-operator",
        }
    )

    response = client.get("/who", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["principal_id"] == "tenant-a"
    assert body["auth_source"] == "edge_principal_assertion"
    assert body["operator_id"] == ""
    assert "x-ea-principal-id" in body["stripped"]
    assert "x-principal-id" in body["stripped"]
    assert "x-ea-operator-id" in body["stripped"]


def test_edge_assertion_nonce_replay_is_rejected_with_security_envelope() -> None:
    app = _identity_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = _assertion_headers(
        principal_id="tenant-replay",
        nonce="nonce-replay-guard-0001",
    )

    assert client.get("/who", headers=headers).status_code == 200
    replay = client.get("/who", headers=headers)

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "principal_assertion_invalid"
    assert replay.json()["error"]["details"]["reason"] == "nonce_replayed_or_capacity_exhausted"
    assert replay.headers["x-content-type-options"] == "nosniff"
    assert replay.headers["x-correlation-id"] == replay.json()["error"]["correlation_id"]


@pytest.mark.parametrize(
    ("header_updates", "expected_reason"),
    [
        ({PRINCIPAL_ASSERTION_AUDIENCE_HEADER: "wrong-audience"}, "audience_invalid"),
        ({PRINCIPAL_ASSERTION_TIMESTAMP_HEADER: str(_NOW - 121)}, "timestamp_expired"),
        ({PRINCIPAL_ASSERTION_SIGNATURE_HEADER: "0" * 64}, "signature_invalid"),
    ],
)
def test_edge_assertion_rejects_bad_audience_timestamp_and_signature(
    header_updates: dict[str, str],
    expected_reason: str,
) -> None:
    app = _identity_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = _assertion_headers(
        principal_id="tenant-invalid",
        nonce=f"nonce-invalid-{expected_reason}-0001",
    )
    headers.update(header_updates)

    response = client.get("/who", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["details"]["reason"] == expected_reason


def test_edge_assertion_signature_is_bound_to_query_string() -> None:
    app = _identity_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = _assertion_headers(
        principal_id="tenant-query-bound",
        nonce="nonce-query-bound-0001",
        query_string="",
    )

    response = client.get("/who?view=other", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["details"]["reason"] == "signature_invalid"


def test_cloudflare_access_and_workspace_session_precede_edge_assertion() -> None:
    edge = VerifiedPrincipalAssertion(
        principal_id="edge-tenant",
        audience=_ASSERTION_AUDIENCE,
        nonce_hash="nonce-hash",
        issued_at=_NOW,
    )
    cloudflare = CloudflareAccessIdentity(
        principal_id="cf-tenant",
        email="user@example.com",
        subject="subject-1",
        display_name="User",
        issuer="https://example.cloudflareaccess.com",
        idp_name="google",
        audiences=("cf-audience",),
        claims={},
    )
    container = _container(mode="prod")

    access_context = get_request_context(
        _request(
            headers={},
            state={
                VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY: edge,
                "cloudflare_access_identity": cloudflare,
            },
        ),
        container=container,
    )
    session_context = get_request_context(
        _request(
            headers={},
            state={
                VERIFIED_PRINCIPAL_ASSERTION_STATE_KEY: edge,
                "workspace_access_session_payload": {
                    "principal_id": "session-tenant",
                    "role": "principal",
                    "email": "session@example.com",
                },
            },
        ),
        container=container,
    )

    assert access_context.principal_id == "cf-tenant"
    assert access_context.auth_source == "cloudflare_access"
    assert session_context.principal_id == "session-tenant"
    assert session_context.auth_source == "workspace_access_session"


def test_proxy_chain_cannot_make_untrusted_peer_authoritative() -> None:
    trusted_networks = (ipaddress.ip_network("10.0.0.0/8"),)
    policy = _policy(networks=trusted_networks)
    headers = _assertion_headers(
        principal_id="proxy-tenant",
        nonce="nonce-proxy-chain-0001",
    )
    headers["X-Forwarded-For"] = "198.51.100.4, 10.0.0.3"

    untrusted = TestClient(
        _identity_app(policy=policy),
        client=("203.0.113.9", 50000),
    ).get("/who", headers=headers)
    trusted_headers = _assertion_headers(
        principal_id="proxy-tenant",
        nonce="nonce-proxy-chain-0002",
    )
    trusted_headers["X-Forwarded-For"] = "198.51.100.4, 10.0.0.3"
    trusted = TestClient(
        _identity_app(policy=policy),
        client=("10.0.0.4", 50000),
    ).get("/who", headers=trusted_headers)

    assert untrusted.status_code == 401
    assert untrusted.json()["error"]["details"]["reason"] == "untrusted_proxy_peer"
    assert trusted.status_code == 200
    assert trusted.json()["principal_id"] == "proxy-tenant"


@pytest.mark.parametrize(
    "legacy_env_name",
    (
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER",
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER",
    ),
)
def test_legacy_trust_flags_cannot_restore_prod_override_but_dev_loopback_remains(
    monkeypatch: pytest.MonkeyPatch,
    legacy_env_name: str,
) -> None:
    monkeypatch.setenv(legacy_env_name, "1")
    container = _container(mode="prod")
    with pytest.raises(HTTPException, match="principal_required"):
        get_request_context(
            _request(
                headers={
                    "Authorization": "Bearer shared-token",
                    "X-EA-Principal-ID": "legacy-spoof",
                }
            ),
            container=container,
        )

    dev_app = _identity_app(
        mode="dev",
        api_token="",
        policy=_policy(mode="dev", assertions_enabled=False),
    )
    loopback = TestClient(dev_app, client=("127.0.0.1", 50000)).get(
        "/who",
        headers={"X-EA-Principal-ID": "dev-loopback"},
    )
    remote = TestClient(dev_app, client=("203.0.113.7", 50000)).get(
        "/who",
        headers={"X-EA-Principal-ID": "remote-spoof"},
    )

    assert loopback.status_code == 200
    assert loopback.json()["principal_id"] == "dev-loopback"
    assert remote.status_code == 200
    assert remote.json()["principal_id"] == "safe-default"


def test_main_app_orders_identity_sanitization_before_ingress_context_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RUNTIME_MODE", "dev")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.delenv("EA_EDGE_PRINCIPAL_ASSERTION_SECRET", raising=False)
    monkeypatch.delenv("EA_EDGE_PRINCIPAL_ASSERTION_AUDIENCE", raising=False)
    from app.api.app import create_app

    app = create_app()
    middleware_classes = [middleware.cls for middleware in app.user_middleware]

    assert middleware_classes.index(PrincipalIdentityMiddleware) < next(
        index
        for index, middleware_class in enumerate(middleware_classes)
        if middleware_class.__name__ == "IngressAbuseMiddleware"
    )


def test_edge_assertion_configuration_requires_separate_complete_secret() -> None:
    with pytest.raises(RuntimeError, match="configuration_incomplete"):
        PrincipalIdentityPolicy.from_environ(
            runtime_mode="prod",
            trusted_proxy_cidrs=_LOOPBACK_NETWORKS,
            environ={"EA_EDGE_PRINCIPAL_ASSERTION_SECRET": _ASSERTION_SECRET},
        )
    with pytest.raises(RuntimeError, match="must_be_separate"):
        PrincipalIdentityPolicy.from_environ(
            runtime_mode="prod",
            trusted_proxy_cidrs=_LOOPBACK_NETWORKS,
            environ={
                "EA_EDGE_PRINCIPAL_ASSERTION_SECRET": _ASSERTION_SECRET,
                "EA_EDGE_PRINCIPAL_ASSERTION_AUDIENCE": _ASSERTION_AUDIENCE,
                "EA_API_TOKEN": _ASSERTION_SECRET,
            },
        )
