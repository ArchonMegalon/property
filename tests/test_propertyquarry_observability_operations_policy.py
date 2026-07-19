from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.observability import RuntimeMetrics
from scripts import propertyquarry_evidence_contract as contract


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/monitoring/propertyquarry_flagship_operations.v1.json"


def test_flagship_operations_policy_is_canonical_and_complete() -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "propertyquarry.flagship-operations.v1"
    assert payload["service"] == "propertyquarry"
    assert payload["editable"] is False
    assert payload["release_filters"] == [
        "release_commit_sha",
        "release_image_digest",
        "replica_id",
    ]
    live = payload["required_live_receipts"]
    assert live == {
        "max_age_seconds": 900,
        "kinds": [
            "dashboard_render",
            "structured_log_query",
            "distributed_trace_query",
            "alert_delivery",
        ],
        "exact_release_binding": True,
        "independent_authentication": True,
    }

    panels = {row["id"]: row for row in payload["panels"]}
    assert set(panels) == {
        "availability_error_budget",
        "latency",
        "release_replica_readiness",
        "runtime_roles",
        "distributed_admission",
        "admission_capacity",
        "durable_work_queues",
        "provider_health",
        "content_and_delivery_integrity",
        "correlated_logs",
        "distributed_trace_continuity",
    }
    assert len(panels) == len(payload["panels"])
    capacity = panels["admission_capacity"]
    assert capacity["thresholds"] == {
        "contract_valid_minimum": 1,
        "required_capacity_keys": ["lease", "quota"],
        "hard_limits": {"quota": 1_000_000, "lease": 100_000},
        "warning_utilization_ratio": 0.8,
        "critical_utilization_ratio": 0.95,
    }
    assert all(
        'backend="postgres"' in query
        for query in capacity["queries"]
    )
    assert panels["correlated_logs"]["query_contract"]["private_payload_allowed"] is False
    trace_contract = panels["distributed_trace_continuity"]["query_contract"]
    assert trace_contract["propagation_format"] == "W3C traceparent v00"
    assert trace_contract["required_boundaries"] == [
        "customer_api",
        "durable_search_worker",
        "provider_or_render_boundary",
    ]
    for panel in panels.values():
        runbook = ROOT / str(panel["runbook"]).split("#", 1)[0]
        assert runbook.is_file()


def test_flagship_operations_policy_is_bound_into_release_challenge() -> None:
    expected = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()

    assert contract.CANONICAL_POLICY_PATHS["flagship_operations_sha256"] == POLICY_PATH
    assert contract.canonical_policy_hashes()["flagship_operations_sha256"] == expected


def test_runtime_metrics_expose_only_validated_shared_capacity_samples() -> None:
    rendered = RuntimeMetrics().render_prometheus(
        readiness_ready=True,
        admission_backend="postgres",
        admission_capacity_rows=(
            ("lease", 12, 100_000),
            ("quota", 345, 1_000_000),
        ),
        admission_capacity_valid=True,
        environ={},
        now_epoch=0,
    )

    assert (
        'propertyquarry_admission_capacity_contract_valid{backend="postgres"} 1'
        in rendered
    )
    assert (
        'propertyquarry_admission_capacity_row_count{backend="postgres",capacity_key="lease"} 12'
        in rendered
    )
    assert (
        'propertyquarry_admission_capacity_limit{backend="postgres",capacity_key="quota"} 1000000'
        in rendered
    )

    development = RuntimeMetrics().render_prometheus(
        readiness_ready=True,
        admission_backend="memory",
        admission_capacity_valid=False,
        environ={},
        now_epoch=0,
    )
    assert (
        'propertyquarry_admission_capacity_contract_valid{backend="memory"} 0'
        in development
    )
    assert "capacity_key=" not in development

    invalid = RuntimeMetrics().render_prometheus(
        readiness_ready=True,
        admission_backend="postgres",
        admission_capacity_rows=(
            ("lease", 12, 100_000),
            ("quota", 345, 999_999),
        ),
        admission_capacity_valid=True,
        environ={},
        now_epoch=0,
    )
    assert (
        'propertyquarry_admission_capacity_contract_valid{backend="postgres"} 0'
        in invalid
    )
    assert "capacity_key=" not in invalid
