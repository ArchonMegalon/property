from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.logging_utils import RedactingJsonFormatter
from app.observability import RuntimeMetrics


def _app(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("EA_RUNTIME_MODE", "dev")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "metrics-test-token")
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "metrics-scraper")
    monkeypatch.setenv("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", "1")
    monkeypatch.setenv("EA_ALLOW_LOOPBACK_NO_AUTH", "0")
    monkeypatch.delenv("EA_CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("EA_CF_ACCESS_AUD", raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES", "0")
    from app.api.app import create_app

    return create_app()


def _metrics_headers() -> dict[str, str]:
    return {
        "Authorization": " ".join(("Bearer", "metrics-test-token")),
        "X-EA-Principal-ID": "metrics-scraper",
    }


def test_json_logging_redacts_structured_fields_message_and_exception_stack() -> None:
    authorization_scheme = "Bearer"
    try:
        raise RuntimeError(
            f"Authorization: {authorization_scheme} top-secret "
            "DATABASE_URL=postgresql://user:db-pass@db/property"
        )
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.api.errors",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request failed api_token=plain-secret Cookie: session=private-cookie",
        args=(),
        exc_info=exc_info,
    )
    record.propertyquarry_fields = {
        "event": "unhandled_exception",
        "correlation_id": "corr-redaction-1",
        "error_detail": {
            "password": "hidden-password",
            "note": "Bearer another-secret",
        },
    }

    rendered = RedactingJsonFormatter().format(record)
    payload = json.loads(rendered)

    assert "top-secret" not in rendered
    assert "plain-secret" not in rendered
    assert "private-cookie" not in rendered
    assert "hidden-password" not in rendered
    assert "another-secret" not in rendered
    assert "db-pass" not in rendered
    assert payload["correlation_id"] == "corr-redaction-1"
    assert payload["error_detail"]["password"] == "***"
    assert payload["exception"]["type"] == "RuntimeError"
    assert "Traceback" in payload["exception"]["stack"]
    assert "Bearer ***" in rendered
    assert "DATABASE_URL=***" in rendered


def test_registry_exports_bounded_request_error_latency_and_readiness_metrics(tmp_path: Path) -> None:
    registry = RuntimeMetrics()
    registry.record_request(method="GET", route="/items/{item_id}", status_code=200, duration_seconds=0.2)
    registry.record_request(method="GET", route="/items/{item_id}", status_code=500, duration_seconds=0.7)
    registry.record_content_ledger_event(outcome="claimed")
    registry.record_content_ledger_event(outcome="recovered")
    registry.record_content_ledger_event(outcome="unbounded-provider-value")
    metrics = registry.render_prometheus(
        readiness_ready=False,
        environ={
            "EA_WORKER_HEARTBEAT_PATH": str(tmp_path / "missing-worker.json"),
            "EA_SCHEDULER_HEARTBEAT_PATH": str(tmp_path / "missing-scheduler.json"),
        },
        now_epoch=1_000.0,
    )

    assert 'propertyquarry_http_requests_total{method="GET",route="/items/{item_id}",status_class="2xx"} 1' in metrics
    assert 'propertyquarry_http_requests_total{method="GET",route="/items/{item_id}",status_class="5xx"} 1' in metrics
    assert 'propertyquarry_http_request_errors_total{method="GET",route="/items/{item_id}",status_class="5xx"} 1' in metrics
    assert 'propertyquarry_http_request_duration_seconds_bucket{method="GET",route="/items/{item_id}",le="1"} 2' in metrics
    assert 'propertyquarry_http_request_duration_seconds_count{method="GET",route="/items/{item_id}"} 2' in metrics
    assert 'propertyquarry_http_request_duration_seconds_sum{method="GET",route="/items/{item_id}"} 0.9' in metrics
    assert 'propertyquarry_content_ledger_events_total{outcome="claimed"} 1' in metrics
    assert 'propertyquarry_content_ledger_events_total{outcome="recovered"} 1' in metrics
    assert 'propertyquarry_content_ledger_events_total{outcome="failed"} 1' in metrics
    assert 'propertyquarry_content_ledger_events_total{outcome="duplicate"} 0' in metrics
    assert "unbounded-provider-value" not in metrics
    assert "propertyquarry_readiness 0" in metrics
    assert "propertyquarry_expected_api_replicas 1" in metrics


def test_metrics_endpoint_requires_system_auth_and_reuses_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch)
    client = TestClient(app)

    health = client.get("/health", headers={"X-Correlation-ID": "release-check-123"})
    assert health.status_code == 200
    assert health.headers["x-correlation-id"] == "release-check-123"

    unauthenticated = client.get("/internal/metrics")
    assert unauthenticated.status_code == 401
    wrong_token = client.get(
        "/internal/metrics",
        headers={"Authorization": "Bearer wrong", "X-EA-Principal-ID": "metrics-scraper"},
    )
    assert wrong_token.status_code == 401

    scrape = client.get("/internal/metrics", headers=_metrics_headers())
    assert scrape.status_code == 200
    assert scrape.headers["cache-control"] == "no-store"
    assert scrape.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert 'propertyquarry_http_requests_total{method="GET",route="/health",status_class="2xx"} 1' in scrape.text
    assert "propertyquarry_readiness 1" in scrape.text
    assert "/internal/metrics" not in client.get("/openapi.json").json()["paths"]


def test_error_counter_and_latency_are_recorded_by_real_request_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch)

    @app.get("/_test/observability-http-error")
    async def _http_error() -> None:
        raise HTTPException(status_code=500, detail="test_failure")

    client = TestClient(app)
    response = client.get("/_test/observability-http-error")
    assert response.status_code == 500

    scrape = client.get("/internal/metrics", headers=_metrics_headers())
    assert scrape.status_code == 200
    assert (
        'propertyquarry_http_request_errors_total{method="GET",route="/_test/observability-http-error",status_class="5xx"} 1'
        in scrape.text
    )
    assert (
        'propertyquarry_http_request_duration_seconds_count{method="GET",route="/_test/observability-http-error"} 1'
        in scrape.text
    )


def test_unhandled_exception_log_has_stack_and_correlation_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(monkeypatch)

    @app.get("/_test/observability-unhandled")
    async def _unhandled() -> None:
        raise RuntimeError(
            "api_token=never-log-me postgresql://user:never-log-db-password@db/property"
        )

    with caplog.at_level(logging.ERROR, logger="app.api.errors"):
        response = TestClient(app, raise_server_exceptions=False).get(
            "/_test/observability-unhandled",
            headers={"X-Correlation-ID": "corr-unhandled-456"},
        )

    assert response.status_code == 500
    assert response.headers["x-correlation-id"] == "corr-unhandled-456"
    records = [record for record in caplog.records if record.getMessage() == "unhandled_exception"]
    assert len(records) == 1
    rendered = RedactingJsonFormatter().format(records[0])
    payload = json.loads(rendered)
    assert payload["correlation_id"] == "corr-unhandled-456"
    assert payload["exception"]["type"] == "RuntimeError"
    assert "Traceback" in payload["exception"]["stack"]
    assert "never-log-me" not in rendered
    assert "never-log-db-password" not in rendered


def test_stale_and_missing_role_heartbeat_metrics_fail_closed(tmp_path: Path) -> None:
    worker_path = tmp_path / "worker.json"
    scheduler_path = tmp_path / "scheduler.json"
    worker_path.write_text(
        json.dumps({"role": "worker", "epoch": 995.0, "pid": 10}),
        encoding="utf-8",
    )
    scheduler_path.write_text(
        json.dumps(
            {
                "role": "scheduler",
                "epoch": 800.0,
                "pid": 11,
                "delivery_outbox": {
                    "queued": 7,
                    "claimed": 6,
                    "sent": 5,
                    "retried": 1,
                    "dead_lettered": 1,
                    "claim_conflicts": 2,
                    "failed": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    registry = RuntimeMetrics()
    metrics = registry.render_prometheus(
        readiness_ready=True,
        environ={
            "EA_WORKER_HEARTBEAT_PATH": str(worker_path),
            "EA_WORKER_HEARTBEAT_MAX_AGE_SECONDS": "30",
            "EA_SCHEDULER_HEARTBEAT_PATH": str(scheduler_path),
            "EA_SCHEDULER_HEARTBEAT_MAX_AGE_SECONDS": "60",
        },
        now_epoch=1_000.0,
    )

    assert 'propertyquarry_runtime_heartbeat_age_seconds{role="worker"} 5' in metrics
    assert 'propertyquarry_runtime_heartbeat_required{role="worker"} 0' in metrics
    assert 'propertyquarry_runtime_heartbeat_required{role="scheduler"} 1' in metrics
    assert 'propertyquarry_runtime_heartbeat_stale{role="worker"} 0' in metrics
    assert 'propertyquarry_runtime_heartbeat_age_seconds{role="scheduler"} 200' in metrics
    assert 'propertyquarry_runtime_heartbeat_stale{role="scheduler"} 1' in metrics
    assert 'propertyquarry_scheduler_delivery_outbox_events_total{outcome="sent"} 5' in metrics
    assert 'propertyquarry_scheduler_delivery_outbox_events_total{outcome="dead_lettered"} 1' in metrics
    assert 'propertyquarry_scheduler_delivery_outbox_events_total{outcome="claim_conflicts"} 2' in metrics

    three_replicas = registry.render_prometheus(
        readiness_ready=True,
        environ={
            "EA_WORKER_HEARTBEAT_PATH": str(worker_path),
            "EA_SCHEDULER_HEARTBEAT_PATH": str(scheduler_path),
            "PROPERTYQUARRY_EXPECTED_API_REPLICAS": "3",
        },
        now_epoch=1_000.0,
    )
    assert "propertyquarry_expected_api_replicas 3" in three_replicas

    explicitly_required = registry.render_prometheus(
        readiness_ready=True,
        environ={
            "EA_WORKER_HEARTBEAT_PATH": str(worker_path),
            "EA_SCHEDULER_HEARTBEAT_PATH": str(scheduler_path),
            "PROPERTYQUARRY_WORKER_HEARTBEAT_REQUIRED": "1",
        },
        now_epoch=1_000.0,
    )
    assert 'propertyquarry_runtime_heartbeat_required{role="worker"} 1' in explicitly_required

    scheduler_path.unlink()
    missing = registry.render_prometheus(
        readiness_ready=True,
        environ={
            "EA_WORKER_HEARTBEAT_PATH": str(worker_path),
            "EA_SCHEDULER_HEARTBEAT_PATH": str(scheduler_path),
        },
        now_epoch=1_000.0,
    )
    assert 'propertyquarry_runtime_heartbeat_present{role="scheduler"} 0' in missing
    assert 'propertyquarry_runtime_heartbeat_age_seconds{role="scheduler"} NaN' in missing
    assert 'propertyquarry_runtime_heartbeat_stale{role="scheduler"} 1' in missing
