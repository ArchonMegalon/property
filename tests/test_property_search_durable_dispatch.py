from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from types import SimpleNamespace

import pytest

from app.product import service as product_service
from app.product.property_search_work_queue import (
    PropertySearchWorkEnqueueResult,
    PropertySearchWorkJob,
)
from app.product.service import ProductService


def _job(
    *,
    run_id: str,
    principal_id: str,
    attempt_count: int = 0,
    max_attempts: int = 3,
    status: str = "queued",
) -> PropertySearchWorkJob:
    now = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
    return PropertySearchWorkJob(
        job_id="job-1",
        principal_id=principal_id,
        run_id=run_id,
        idempotency_key="queue-key",
        payload_json={"actor": "api-actor", "force_refresh": False},
        status=status,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=now,
        created_at=now,
        updated_at=now,
    )


def _bare_service(monkeypatch: pytest.MonkeyPatch) -> ProductService:
    service = object.__new__(ProductService)
    monkeypatch.setattr(ProductService, "_open_property_market_bootstrap", lambda self, **_kwargs: None)
    monkeypatch.setattr(
        ProductService,
        "_resolve_property_search_run_preferences",
        lambda self, **kwargs: (
            tuple(kwargs.get("selected_platforms") or ()),
            dict(kwargs.get("property_preferences") or {}),
            kwargs.get("max_results_per_source"),
        ),
    )
    monkeypatch.setattr(ProductService, "_best_effort_propertyquarry_teable_sync", lambda self, **_kwargs: None)
    monkeypatch.setattr(product_service, "enforce_property_plan_limits", lambda **_kwargs: None)
    monkeypatch.setattr(product_service, "_prune_property_search_runs", lambda: None)
    return service


def test_prod_start_atomically_enqueues_before_return_and_never_starts_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _bare_service(monkeypatch)
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")
    captured: dict[str, object] = {}

    class _Repository:
        def enqueue_run(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            record = dict(kwargs["run_record"])
            return PropertySearchWorkEnqueueResult(
                job=_job(run_id=str(record["run_id"]), principal_id=str(record["principal_id"])),
                created=True,
            )

    monkeypatch.setattr(product_service, "_property_search_work_queue_repository", lambda: _Repository())

    class _ForbiddenThread:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("production start must not create an execution thread")

    monkeypatch.setattr(product_service.threading, "Thread", _ForbiddenThread)

    result = service.start_property_search_run(
        principal_id="principal-prod",
        actor="api-actor",
        selected_platforms=("willhaben",),
        property_search_preferences={"country_code": "AT"},
        dispatch_only=True,
        idempotency_key="client-request-1",
    )

    assert captured
    assert dict(captured["run_record"])["run_id"] == result["run_id"]
    assert dict(captured["payload_json"])["run_id"] == result["run_id"]
    assert result["status"] == "queued"
    assert result["summary"]["durable_queue"] is True
    assert result["summary"]["worker_start_mode"] == "durable_queue"
    assert result["summary"]["worker_started"] is False


def test_prod_start_fails_closed_and_removes_undurable_registry_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _bare_service(monkeypatch)
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")
    before = set(product_service._PROPERTY_SEARCH_RUN_REGISTRY)

    class _Repository:
        def enqueue_run(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(product_service, "_property_search_work_queue_repository", lambda: _Repository())

    with pytest.raises(RuntimeError, match="property_search_work_enqueue_failed"):
        service.start_property_search_run(
            principal_id="principal-prod-failure",
            actor="api-actor",
            selected_platforms=("willhaben",),
            property_search_preferences={"country_code": "AT"},
            dispatch_only=True,
        )

    assert set(product_service._PROPERTY_SEARCH_RUN_REGISTRY) == before


def test_durable_job_execution_is_synchronous_and_retries_only_failed_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ProductService)
    job = _job(
        run_id="run-retry",
        principal_id="principal-retry",
        attempt_count=2,
        max_attempts=3,
        status="leased",
    )
    monkeypatch.setattr(
        product_service,
        "_load_property_search_run_record",
        lambda **_kwargs: {
            "run_id": job.run_id,
            "principal_id": job.principal_id,
            "status": "failed",
        },
    )
    captured: dict[str, object] = {}

    def _pickup(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"status": "completed", "run_id": job.run_id}

    monkeypatch.setattr(ProductService, "_pick_up_property_search_run_execution", _pickup)

    result = service.execute_property_search_work_job(job)

    assert result["status"] == "completed"
    assert captured["synchronous"] is True
    assert captured["allow_failed_retry"] is True
    assert captured["terminal_on_failure"] is False
    assert captured["force_refresh"] is False


def test_prod_stale_recovery_requeues_instead_of_starting_a_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ProductService)
    monkeypatch.setenv("EA_RUNTIME_MODE", "prod")
    record = {
        "run_id": "run-stale",
        "principal_id": "principal-stale",
        "status": "in_progress",
        "created_at": "2026-07-13T08:00:00+00:00",
        "updated_at": "2026-07-13T08:00:00+00:00",
    }

    class _Repository:
        def enqueue_run(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["run_record"] == record
            return PropertySearchWorkEnqueueResult(
                job=_job(run_id="run-stale", principal_id="principal-stale"),
                created=True,
            )

    monkeypatch.setattr(product_service, "_property_search_work_queue_repository", lambda: _Repository())

    class _ForbiddenThread:
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("production recovery must not create an execution thread")

    monkeypatch.setattr(product_service.threading, "Thread", _ForbiddenThread)

    result = service._pick_up_property_search_run_execution(
        record=record,
        actor="scheduler",
        reason="startup_checkpoint_stale",
    )

    assert result["status"] == "queued"
    assert result["durable_queue"] is True
    assert result["job_created"] is True


def test_worker_role_processes_property_job_on_main_execution_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import runner
    from app.product import property_search_work_queue as queue_module

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-unit-test")
    job = _job(
        run_id="run-worker",
        principal_id="principal-worker",
        attempt_count=1,
        status="leased",
    )
    calls: list[tuple[str, str]] = []

    class _Repository:
        def __init__(self, _database_url: str) -> None:
            pass

        def claim(self, *, lease_owner: str, lease_seconds: int):  # type: ignore[no-untyped-def]
            calls.append(("claim", lease_owner))
            return job

        def heartbeat(self, **_kwargs) -> bool:  # type: ignore[no-untyped-def]
            calls.append(("heartbeat", ""))
            return True

        def complete(self, *, job_id: str, lease_owner: str):  # type: ignore[no-untyped-def]
            calls.append(("complete", lease_owner))
            return _job(
                run_id=job.run_id,
                principal_id=job.principal_id,
                attempt_count=1,
                status="completed",
            )

        def fail(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("success path must not fail the job")

    execution_threads: list[threading.Thread] = []

    class _Service:
        def execute_property_search_work_job(self, claimed_job):  # type: ignore[no-untyped-def]
            assert claimed_job is job
            execution_threads.append(threading.current_thread())
            return {"status": "completed"}

    monkeypatch.setattr(queue_module, "PostgresPropertySearchWorkQueue", _Repository)
    monkeypatch.setattr(product_service, "build_product_service", lambda _container: _Service())

    result = runner._run_property_search_work_once(
        SimpleNamespace(),
        role="worker",
        log=logging.getLogger("test.property-search-worker"),
    )

    assert result["completed"] is True
    assert result["status"] == "completed"
    assert execution_threads == [threading.current_thread()]
    assert [name for name, _value in calls] == ["claim", "complete"]
