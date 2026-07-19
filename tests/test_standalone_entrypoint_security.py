from __future__ import annotations

import asyncio
from contextlib import contextmanager
import http.client
import inspect
import json
from pathlib import Path
import threading
from typing import Iterator

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from scripts import ea_responses_proxy as responses_proxy
from scripts import property_reconstruction_render_bridge as render_bridge
from app.services.admission_control import (
    AdmissionBackendUnavailable,
    ConcurrencyDimension,
    MemoryAdmissionBackend,
)
from app.observability import (
    current_runtime_trace_context,
    outbound_observability_headers,
    parse_traceparent,
)


def _memory_admission() -> MemoryAdmissionBackend:
    return MemoryAdmissionBackend()


class _UnavailableAdmission:
    backend_name = "postgres"

    def consume(self, charge):  # noqa: ANN001
        raise AdmissionBackendUnavailable("database unavailable")

    def probe(self) -> None:
        raise AdmissionBackendUnavailable("database unavailable")


def test_responses_proxy_imports_the_repository_local_runtime() -> None:
    expected_runtime_root = Path(__file__).resolve().parents[1] / "ea"
    assert responses_proxy.EA_RUNTIME_ROOT == expected_runtime_root
    request_context_path = Path(inspect.getfile(responses_proxy.RequestContext)).resolve()
    assert request_context_path.is_relative_to(expected_runtime_root.resolve())


@contextmanager
def _running_server(server: object) -> Iterator[tuple[str, int]]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)  # type: ignore[attr-defined]
    thread.start()
    try:
        host, port = server.server_address[:2]  # type: ignore[attr-defined]
        yield str(host), int(port)
    finally:
        server.shutdown()  # type: ignore[attr-defined]
        server.server_close()  # type: ignore[attr-defined]
        thread.join(timeout=2)


def _request(
    address: tuple[str, int],
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection(*address, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8"))
    finally:
        connection.close()


def _request_with_headers(
    address: tuple[str, int],
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    connection = http.client.HTTPConnection(*address, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        return (
            response.status,
            json.loads(raw.decode("utf-8")),
            {str(key).lower(): str(value) for key, value in response.getheaders()},
        )
    finally:
        connection.close()


def test_standalone_boundaries_continue_trace_and_override_spoofed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incoming = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    captured_proxy: dict[str, object] = {}

    def _fake_response(payload: dict[str, object], **_kwargs: object) -> JSONResponse:
        captured_proxy["payload"] = payload
        captured_proxy["trace"] = current_runtime_trace_context()
        captured_proxy["headers"] = outbound_observability_headers()
        return JSONResponse({"status": "ok"})

    monkeypatch.setattr(responses_proxy, "_run_response", _fake_response)
    proxy_config = responses_proxy.ProxyConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
    )
    proxy_server = responses_proxy.ResponsesProxyServer(
        (proxy_config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=proxy_config,
        admission_backend=_memory_admission(),
    )
    with _running_server(proxy_server) as address:
        status, _payload, response_headers = _request_with_headers(
            address,
            "POST",
            "/v1/responses",
            body=b'{"input":"hello","metadata":{"ea_traceparent":"spoofed"}}',
            headers={
                "x-ea-api-token": "correct-secret",
                "Content-Type": "application/json",
                "Traceparent": incoming,
                "X-Correlation-ID": "boundary-check-1",
            },
        )

    assert status == 200
    response_trace = parse_traceparent(response_headers["traceparent"])
    assert response_trace is not None
    assert response_trace[0] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert response_trace[1] != "00f067aa0ba902b7"
    assert response_headers["x-correlation-id"] == "boundary-check-1"
    metadata = dict(dict(captured_proxy["payload"])["metadata"])
    assert metadata["ea_traceparent"] == response_headers["traceparent"]
    assert metadata["ea_correlation_id"] == "boundary-check-1"
    assert captured_proxy["headers"] == {
        "traceparent": response_headers["traceparent"],
        "x-correlation-id": "boundary-check-1",
    }

    captured_render: dict[str, object] = {}

    def _fake_generation(
        payload: dict[str, object], *, config: render_bridge.BridgeConfig | None = None
    ) -> dict[str, object]:
        captured_render["payload"] = payload
        captured_render["trace"] = current_runtime_trace_context()
        captured_render["headers"] = outbound_observability_headers()
        return {"status": "generated", "result": {}}

    monkeypatch.setattr(render_bridge, "run_generation_request", _fake_generation)
    render_config = render_bridge.BridgeConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
    )
    render_server = render_bridge.ReconstructionRenderBridgeServer(
        (render_config.host, 0),
        render_bridge._Handler,
        config=render_config,
        admission_backend=_memory_admission(),
    )
    with _running_server(render_server) as address:
        render_status, _render_payload, render_headers = _request_with_headers(
            address,
            "POST",
            "/generate-reconstruction",
            body=b'{"slug":"safe-slug"}',
            headers={
                "Authorization": "Bearer correct-secret",
                "Content-Type": "application/json",
                "Traceparent": incoming,
                "X-Correlation-ID": "render-check-1",
            },
        )

    assert render_status == 200
    render_trace = parse_traceparent(render_headers["traceparent"])
    assert render_trace is not None
    assert render_trace[0] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert render_headers["x-correlation-id"] == "render-check-1"
    assert captured_render["headers"] == {
        "traceparent": render_headers["traceparent"],
        "x-correlation-id": "render-check-1",
    }


def test_responses_proxy_startup_is_loopback_and_fails_closed_without_auth(monkeypatch) -> None:
    monkeypatch.delenv("EA_RESPONSES_PROXY_HOST", raising=False)
    monkeypatch.delenv("EA_RESPONSES_PROXY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EA_RESPONSES_PROXY_DEV_MODE", raising=False)
    monkeypatch.setattr(responses_proxy, "AUTH_TOKEN", "")
    loaded = responses_proxy._load_proxy_config()
    assert loaded.host == "127.0.0.1"
    assert loaded.auth_token == ""
    assert loaded.dev_mode is False
    with pytest.raises(RuntimeError, match="auth_token_required"):
        responses_proxy._validate_proxy_config(loaded)
    responses_proxy._validate_proxy_config(
        responses_proxy.ProxyConfig(host="127.0.0.1", dev_mode=True)
    )
    with pytest.raises(RuntimeError, match="dev_mode_requires_loopback"):
        responses_proxy._validate_proxy_config(
            responses_proxy.ProxyConfig(host="0.0.0.0", dev_mode=True)
        )
    responses_proxy._validate_proxy_config(
        responses_proxy.ProxyConfig(host="0.0.0.0", auth_token="production-secret")
    )


def test_responses_proxy_auth_uses_constant_time_comparison(monkeypatch) -> None:
    original_compare = responses_proxy.hmac.compare_digest
    compared: list[tuple[bytes, bytes]] = []

    def _compare(provided: bytes, expected: bytes) -> bool:
        compared.append((provided, expected))
        return original_compare(provided, expected)

    monkeypatch.setattr(responses_proxy.hmac, "compare_digest", _compare)
    monkeypatch.setattr(
        responses_proxy,
        "_run_response",
        lambda *args, **kwargs: JSONResponse({"status": "ok"}),
    )
    config = responses_proxy.ProxyConfig(host="127.0.0.1", port=0, auth_token="correct-secret")
    server = responses_proxy.ResponsesProxyServer(
        (config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=config,
        admission_backend=_memory_admission(),
    )
    with _running_server(server) as address:
        status, payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"input":"hello"}',
            headers={"x-ea-api-token": "wrong-secret", "Content-Type": "application/json"},
        )

    assert status == 401
    assert payload["error"]["code"] == "auth_required"  # type: ignore[index]
    assert compared == [(b"wrong-secret", b"correct-secret")]


def test_responses_proxy_bounds_body_cost_rate_and_concurrency(monkeypatch) -> None:
    invoked: list[dict[str, object]] = []

    def _fake_response(payload: dict[str, object], **kwargs: object) -> JSONResponse:
        invoked.append(payload)
        return JSONResponse({"status": "ok"})

    monkeypatch.setattr(responses_proxy, "_run_response", _fake_response)
    config = responses_proxy.ProxyConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
        max_body_bytes=64,
        max_output_tokens=10,
        rate_limit_requests=3,
        max_concurrency=1,
    )
    server = responses_proxy.ResponsesProxyServer(
        (config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=config,
        admission_backend=_memory_admission(),
    )
    auth_headers = {"x-ea-api-token": "correct-secret", "Content-Type": "application/json"}
    with _running_server(server) as address:
        oversized_status, _ = _request(
            address,
            "POST",
            "/v1/responses",
            body=b"{}",
            headers={**auth_headers, "Content-Length": "65"},
        )
        cost_status, cost_payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"max_output_tokens":11}',
            headers=auth_headers,
        )
        busy_lease = server.admission_backend.acquire(
            (
                ConcurrencyDimension(
                    key="responses_proxy:concurrency:global",
                    limit=1,
                    dimension="global",
                ),
            ),
            lease_seconds=60,
        )
        assert busy_lease.allowed
        try:
            busy_status, busy_payload = _request(
                address,
                "POST",
                "/v1/responses",
                body=b'{"max_output_tokens":10}',
                headers=auth_headers,
            )
        finally:
            server.admission_backend.release(busy_lease.lease_id)
        rate_status, rate_payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"max_output_tokens":10}',
            headers=auth_headers,
        )

    assert oversized_status == 413
    assert cost_status == 422
    assert cost_payload["error"]["code"] == "request_cost_limit"  # type: ignore[index]
    assert busy_status == 503
    assert busy_payload["error"]["code"] == "concurrency_limit"  # type: ignore[index]
    assert rate_status == 429
    assert rate_payload["error"]["code"] == "rate_limit_exceeded"  # type: ignore[index]
    assert invoked == []


@pytest.mark.parametrize(
    ("renew_allowed", "expected_status", "expected_code"),
    (
        (True, 200, ""),
        (False, 503, "admission_lease_lost"),
    ),
)
def test_responses_proxy_renews_lease_through_request_completion_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    renew_allowed: bool,
    expected_status: int,
    expected_code: str,
) -> None:
    class _RenewingAdmission(MemoryAdmissionBackend):
        def __init__(self) -> None:
            super().__init__()
            self.renewal_attempted = threading.Event()

        def renew(self, lease_id: str, *, lease_seconds: int) -> bool:
            self.renewal_attempted.set()
            if not renew_allowed:
                return False
            return super().renew(lease_id, lease_seconds=lease_seconds)

    admission = _RenewingAdmission()

    def _fake_response(*_args: object, **_kwargs: object) -> JSONResponse:
        assert admission.renewal_attempted.wait(timeout=1)
        return JSONResponse({"status": "ok"})

    monkeypatch.setattr(responses_proxy, "_run_response", _fake_response)
    monkeypatch.setattr(
        responses_proxy,
        "_lease_renew_interval_seconds",
        lambda _lease_seconds: 0.01,
    )
    config = responses_proxy.ProxyConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
        request_timeout_seconds=1,
    )
    server = responses_proxy.ResponsesProxyServer(
        (config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=config,
        admission_backend=admission,
    )
    with _running_server(server) as address:
        status, payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"input":"hello"}',
            headers={
                "x-ea-api-token": "correct-secret",
                "Content-Type": "application/json",
            },
        )

    assert status == expected_status
    assert admission.renewal_attempted.is_set()
    if expected_code:
        assert payload["error"]["code"] == expected_code  # type: ignore[index]
    else:
        assert payload == {"status": "ok"}


def test_responses_proxy_keeps_renewing_until_stream_body_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StreamingAdmission(MemoryAdmissionBackend):
        def __init__(self) -> None:
            super().__init__()
            self.renewal_attempted = threading.Event()

        def renew(self, lease_id: str, *, lease_seconds: int) -> bool:
            renewed = super().renew(lease_id, lease_seconds=lease_seconds)
            self.renewal_attempted.set()
            return renewed

    admission = _StreamingAdmission()

    def _fake_response(*_args: object, **_kwargs: object) -> StreamingResponse:
        async def body():  # type: ignore[no-untyped-def]
            for _index in range(100):
                if admission.renewal_attempted.is_set():
                    break
                await asyncio.sleep(0.01)
            assert admission.renewal_attempted.is_set()
            yield b'{"status":"streamed"}'

        return StreamingResponse(body(), media_type="application/json")

    monkeypatch.setattr(responses_proxy, "_run_response", _fake_response)
    monkeypatch.setattr(
        responses_proxy,
        "_lease_renew_interval_seconds",
        lambda _lease_seconds: 0.01,
    )
    config = responses_proxy.ProxyConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
        request_timeout_seconds=1,
    )
    server = responses_proxy.ResponsesProxyServer(
        (config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=config,
        admission_backend=admission,
    )
    with _running_server(server) as address:
        status, payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"input":"hello"}',
            headers={
                "x-ea-api-token": "correct-secret",
                "Content-Type": "application/json",
            },
        )

    assert status == 200
    assert payload == {"status": "streamed"}
    assert admission.renewal_attempted.is_set()


def test_responses_proxy_readiness_fails_when_model_catalog_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(responses_proxy, "list_response_models", lambda: [])
    config = responses_proxy.ProxyConfig(host="127.0.0.1", port=0, auth_token="correct-secret")
    server = responses_proxy.ResponsesProxyServer(
        (config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=config,
        admission_backend=_memory_admission(),
    )
    with _running_server(server) as address:
        status, payload = _request(address, "GET", "/health/ready")

    assert status == 503
    assert payload["reason"] == "responses_proxy_model_catalog_empty"


def test_responses_proxy_readiness_requires_a_ready_provider(monkeypatch) -> None:
    monkeypatch.setattr(responses_proxy, "list_response_models", lambda: [{"id": "test-model"}])
    monkeypatch.setattr(
        responses_proxy,
        "_provider_health_snapshot",
        lambda **kwargs: {"providers": {"test-provider": {"state": "unavailable"}}},
    )
    config = responses_proxy.ProxyConfig(host="127.0.0.1", auth_token="correct-secret")

    ready, payload = responses_proxy._proxy_readiness(
        config,
        admission_backend=_memory_admission(),
    )

    assert ready is False
    assert payload["reason"] == "responses_proxy_provider_unavailable"


def test_standalone_services_fail_closed_when_admission_store_is_unavailable() -> None:
    proxy_config = responses_proxy.ProxyConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
    )
    proxy_server = responses_proxy.ResponsesProxyServer(
        (proxy_config.host, 0),
        responses_proxy.ResponsesProxyHandler,
        config=proxy_config,
        admission_backend=_UnavailableAdmission(),
    )
    with _running_server(proxy_server) as address:
        proxy_status, proxy_payload = _request(
            address,
            "POST",
            "/v1/responses",
            body=b'{"input":"hello"}',
            headers={"x-ea-api-token": "correct-secret", "Content-Type": "application/json"},
        )

    render_config = render_bridge.BridgeConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
    )
    render_server = render_bridge.ReconstructionRenderBridgeServer(
        (render_config.host, 0),
        render_bridge._Handler,
        config=render_config,
        admission_backend=_UnavailableAdmission(),
    )
    with _running_server(render_server) as address:
        render_status, render_payload = _request(
            address,
            "POST",
            "/generate-reconstruction",
            body=b'{"slug":"safe-slug"}',
            headers={"Authorization": "Bearer correct-secret", "Content-Type": "application/json"},
        )

    assert proxy_status == 503
    assert proxy_payload["error"]["code"] == "admission_unavailable"  # type: ignore[index]
    assert render_status == 503
    assert render_payload["reason"] == "admission_backend_unavailable"


def test_render_bridge_startup_is_loopback_and_fails_closed_without_auth(monkeypatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_HOST", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_RECONSTRUCTION_RENDER_DEV_MODE", raising=False)
    loaded = render_bridge._load_bridge_config()
    assert loaded.host == "127.0.0.1"
    assert loaded.auth_token == ""
    assert loaded.dev_mode is False
    with pytest.raises(RuntimeError, match="bridge_token_required"):
        render_bridge._validate_bridge_config(loaded)
    render_bridge._validate_bridge_config(
        render_bridge.BridgeConfig(host="127.0.0.1", dev_mode=True)
    )
    with pytest.raises(RuntimeError, match="dev_mode_requires_loopback"):
        render_bridge._validate_bridge_config(
            render_bridge.BridgeConfig(host="0.0.0.0", dev_mode=True)
        )
    render_bridge._validate_bridge_config(
        render_bridge.BridgeConfig(host="0.0.0.0", auth_token="production-secret")
    )


def test_render_bridge_auth_uses_constant_time_comparison(monkeypatch) -> None:
    original_compare = render_bridge.hmac.compare_digest
    compared: list[tuple[bytes, bytes]] = []

    def _compare(provided: bytes, expected: bytes) -> bool:
        compared.append((provided, expected))
        return original_compare(provided, expected)

    monkeypatch.setattr(render_bridge.hmac, "compare_digest", _compare)
    config = render_bridge.BridgeConfig(host="127.0.0.1", port=0, auth_token="correct-secret")
    server = render_bridge.ReconstructionRenderBridgeServer(
        (config.host, 0),
        render_bridge._Handler,
        config=config,
        admission_backend=_memory_admission(),
    )
    with _running_server(server) as address:
        status, payload = _request(
            address,
            "POST",
            "/generate-reconstruction",
            body=b'{"slug":"safe-slug"}',
            headers={"Authorization": "Bearer wrong-secret", "Content-Type": "application/json"},
        )

    assert status == 401
    assert payload["reason"] == "invalid_bridge_token"
    assert compared == [(b"wrong-secret", b"correct-secret")]


def test_render_bridge_bounds_body_cost_rate_and_concurrency(monkeypatch) -> None:
    invoked: list[dict[str, object]] = []

    def _fake_generation(
        payload: dict[str, object], *, config: render_bridge.BridgeConfig | None = None
    ) -> dict[str, object]:
        invoked.append(payload)
        return {"status": "generated", "result": {}}

    monkeypatch.setattr(render_bridge, "run_generation_request", _fake_generation)
    config = render_bridge.BridgeConfig(
        host="127.0.0.1",
        port=0,
        auth_token="correct-secret",
        max_body_bytes=64,
        max_room_count=1,
        rate_limit_requests=3,
        max_concurrency=1,
    )
    server = render_bridge.ReconstructionRenderBridgeServer(
        (config.host, 0),
        render_bridge._Handler,
        config=config,
        admission_backend=_memory_admission(),
    )
    auth_headers = {"Authorization": "Bearer correct-secret", "Content-Type": "application/json"}
    with _running_server(server) as address:
        oversized_status, _ = _request(
            address,
            "POST",
            "/generate-reconstruction",
            body=b"{}",
            headers={**auth_headers, "Content-Length": "65"},
        )
        cost_status, cost_payload = _request(
            address,
            "POST",
            "/generate-reconstruction",
            body=b'{"slug":"safe-slug","room_count":2}',
            headers=auth_headers,
        )
        busy_lease = server.admission_backend.acquire(
            (
                ConcurrencyDimension(
                    key="reconstruction_render:concurrency:global",
                    limit=1,
                    dimension="global",
                ),
            ),
            lease_seconds=60,
        )
        assert busy_lease.allowed
        try:
            busy_status, busy_payload = _request(
                address,
                "POST",
                "/generate-reconstruction",
                body=b'{"slug":"safe-slug"}',
                headers=auth_headers,
            )
        finally:
            server.admission_backend.release(busy_lease.lease_id)
        rate_status, rate_payload = _request(
            address,
            "POST",
            "/generate-reconstruction",
            body=b'{"slug":"safe-slug"}',
            headers=auth_headers,
        )

    assert oversized_status == 413
    assert cost_status == 422
    assert cost_payload["reason"] == "room_count_exceeds_limit"
    assert busy_status == 503
    assert busy_payload["reason"] == "generation_concurrency_limit"
    assert rate_status == 429
    assert rate_payload["reason"] == "request_rate_limit_exceeded"
    assert invoked == []


def test_render_bridge_readiness_checks_generator_and_storage(tmp_path: Path, monkeypatch) -> None:
    public_tour_dir = tmp_path / "public-tours"
    public_tour_dir.mkdir()
    script_path = tmp_path / "generate_property_reconstruction.py"
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(render_bridge, "_public_tour_dir", lambda: public_tour_dir)
    monkeypatch.setattr(render_bridge, "_script_path", lambda: script_path)
    config = render_bridge.BridgeConfig(host="127.0.0.1", auth_token="correct-secret")

    ready, payload = render_bridge._bridge_readiness(
        config,
        admission_backend=_memory_admission(),
    )
    assert ready is True
    assert payload["reason"] == "bridge_ready"

    script_path.unlink()
    ready, payload = render_bridge._bridge_readiness(
        config,
        admission_backend=_memory_admission(),
    )
    assert ready is False
    assert payload["reason"] == "generator_script_unavailable"
