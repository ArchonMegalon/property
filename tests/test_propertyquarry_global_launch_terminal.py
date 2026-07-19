from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import propertyquarry_evidence_contract as evidence_contract
from scripts import propertyquarry_global_launch_terminal as terminal
from scripts import propertyquarry_release_preflight_policy as preflight_policy


ROOT = Path(__file__).resolve().parents[1]
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
IMAGE_DIGEST = "sha256:" + "0123456789abcdef" * 4
RELEASE_IDENTITY = {
    "commit_sha": COMMIT_SHA,
    "image_digest": IMAGE_DIGEST,
}
PRODUCT_DATA = {
    "public_origin": "https://propertyquarry.at",
    "teable_origin": "https://data.propertyquarry.at",
    "teable_base_id_sha256": "0123456789abcdef" * 4,
    "rybbit_origin": "https://analytics.propertyquarry.at",
    "rybbit_site_id_sha256": "fedcba9876543210" * 4,
    "evidence_overlay_phase": "active",
}
FLAGSHIP_OPERATIONS_SHA256 = hashlib.sha256(
    terminal.FLAGSHIP_OPERATIONS_POLICY_PATH.read_bytes()
).hexdigest()
CAPACITY_CONTRACT_SHA256 = "sha256:" + hashlib.sha256(
    terminal.CAPACITY_RECEIPT_CONTRACT_PATH.read_bytes()
).hexdigest()
CONTROLLER_BROWSER_EXECUTABLE_PATH = str(Path(sys.executable).resolve(strict=True))
CONTROLLER_BROWSER_EXECUTABLE_SHA256 = "sha256:" + hashlib.sha256(
    Path(CONTROLLER_BROWSER_EXECUTABLE_PATH).read_bytes()
).hexdigest()
CONTROLLER_BROWSER_POLICY = {
    "engine": "chromium",
    "executable_path": CONTROLLER_BROWSER_EXECUTABLE_PATH,
    "executable_sha256": CONTROLLER_BROWSER_EXECUTABLE_SHA256,
}
CONTROLLER_RELEASE_MANIFEST_SHA256 = "sha256:" + "89abcdef01234567" * 4


def _write_json(path: Path, payload: object, *, mode: int = 0o400) -> bytes:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(mode)
    return raw


def _descriptor(
    path: Path,
    payload: object | bytes,
    *,
    release_identity: dict[str, str] | None = None,
    mode: int = 0o400,
) -> dict[str, object]:
    if isinstance(payload, bytes):
        raw = payload
        if path.exists():
            path.chmod(0o600)
        path.write_bytes(raw)
        path.chmod(mode)
    else:
        raw = _write_json(path, payload, mode=mode)
    return {
        "path": str(path.resolve()),
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "release_identity": dict(release_identity or RELEASE_IDENTITY),
    }


def _write_bytes(path: Path, raw: bytes, *, mode: int = 0o400) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        path.chmod(0o600)
        path.unlink()
    path.write_bytes(raw)
    path.chmod(mode)


def _with_payload_hash(payload: dict[str, object]) -> dict[str, object]:
    normalized = deepcopy(payload)
    normalized["payload_sha256"] = hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return normalized


def _bundle_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _rewrite_descriptor_bytes(descriptor: dict[str, object], raw: bytes) -> None:
    path = Path(str(descriptor["path"]))
    _write_bytes(path, raw)
    descriptor["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()


def _raw_observability_descriptors(tmp_path: Path) -> dict[str, object]:
    start_path = tmp_path / "propertyquarry-api-1-start.prom"
    end_path = tmp_path / "propertyquarry-api-1-end.prom"
    replica_probe_path = tmp_path / "propertyquarry-api-1-probe.json"
    start_raw = b"# TYPE propertyquarry_readiness gauge\npropertyquarry_readiness 1\n"
    end_raw = b"# TYPE propertyquarry_readiness gauge\npropertyquarry_readiness 1\n# end\n"
    replica_probe_raw = b'{"schema":"propertyquarry.metrics_probe.v2","status":"captured"}\n'
    for path, raw in (
        (start_path, start_raw),
        (end_path, end_raw),
        (replica_probe_path, replica_probe_raw),
    ):
        _write_bytes(path, raw)

    snapshot = _with_payload_hash(
        {
            "schema": terminal.SLO_SNAPSHOT_BUNDLE_SCHEMA,
            "capture_tool": terminal.SLO_CAPTURE_TOOL,
            "release_commit_sha": COMMIT_SHA,
            "release_image_digest": IMAGE_DIGEST,
            "window_start": "2026-07-19T10:00:00Z",
            "window_end": "2026-07-19T10:01:00Z",
            "window_seconds": 60.0,
            "replica_count": 1,
            "replicas": [
                {
                    "container_id": "01" * 32,
                    "container_image_id": IMAGE_DIGEST,
                    "replica_id": "propertyquarry-api-1",
                    "release_commit_sha": COMMIT_SHA,
                    "release_image_digest": IMAGE_DIGEST,
                    "docker_inspect_sha256": "12" * 32,
                    "start": {
                        "captured_at": "2026-07-19T10:00:00Z",
                        "path": start_path.name,
                        "sha256": hashlib.sha256(start_raw).hexdigest(),
                        "bytes": len(start_raw),
                    },
                    "end": {
                        "captured_at": "2026-07-19T10:01:00Z",
                        "path": end_path.name,
                        "sha256": hashlib.sha256(end_raw).hexdigest(),
                        "bytes": len(end_raw),
                    },
                }
            ],
        }
    )
    snapshot_raw = _bundle_bytes(snapshot)
    snapshot_descriptor = _descriptor(
        tmp_path / "raw--slo_metrics_snapshot.json",
        snapshot_raw,
    )
    probe = _with_payload_hash(
        {
            "schema": terminal.SLO_PROBE_BUNDLE_SCHEMA,
            "capture_tool": terminal.SLO_CAPTURE_TOOL,
            "captured_at": "2026-07-19T10:01:00Z",
            "release_commit_sha": COMMIT_SHA,
            "release_image_digest": IMAGE_DIGEST,
            "replica_count": 1,
            "snapshot_bundle_sha256": hashlib.sha256(snapshot_raw).hexdigest(),
            "snapshot_bundle_bytes": len(snapshot_raw),
            "replicas": [
                {
                    "replica_id": "propertyquarry-api-1",
                    "container_id": "01" * 32,
                    "path": replica_probe_path.name,
                    "sha256": hashlib.sha256(replica_probe_raw).hexdigest(),
                    "bytes": len(replica_probe_raw),
                }
            ],
            "credential_persisted": False,
        }
    )
    raw_observability = {
        name: _descriptor(
            tmp_path / f"raw--{name}.json",
            json.dumps(
                {"source": name, "release_identity": RELEASE_IDENTITY},
                sort_keys=True,
            ).encode("utf-8"),
        )
        for name in terminal.RAW_OBSERVABILITY_FLAGS
        if name not in terminal.RAW_OBSERVABILITY_COMPANION_BUNDLES
    }
    raw_observability["slo_metrics_snapshot"] = snapshot_descriptor
    raw_observability["slo_metrics_probe"] = _descriptor(
        tmp_path / "raw--slo_metrics_probe.json",
        _bundle_bytes(probe),
    )
    return raw_observability


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    _write_json(path, payload, mode=0o600)


def _invocation_contract(outputs: dict[str, str]) -> dict[str, object]:
    runtime_artifacts = {
        name: {
            "path": path,
            "sha256": "sha256:" + f"{index + 1:x}{index + 2:x}" * 32,
        }
        for index, (name, path) in enumerate(
            terminal.INSTALLED_RUNTIME_ARTIFACT_PATHS.items()
        )
    }
    runtime_artifacts["flagship_operations_policy"]["sha256"] = (
        "sha256:" + FLAGSHIP_OPERATIONS_SHA256
    )
    artifact_set_sha256 = "sha256:" + hashlib.sha256(
        json.dumps(
            runtime_artifacts,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": terminal.INVOCATION_CONTRACT_SCHEMA,
        "terminal_command": terminal.GLOBAL_LAUNCH_TERMINAL_COMMAND,
        "profile": "launch",
        "claim_scope": "core",
        "required_browser_engines": ["chromium", "firefox", "webkit"],
        "performance_browser_policy": dict(CONTROLLER_BROWSER_POLICY),
        "release_manifest_sha256": CONTROLLER_RELEASE_MANIFEST_SHA256,
        "output_paths": dict(outputs),
        "gold_argv_contract_sha256": terminal.GOLD_ARGV_CONTRACT_SHA256,
        "runtime_artifacts": runtime_artifacts,
        "runtime_artifact_set_sha256": artifact_set_sha256,
    }


def _base_manifest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    receipts = {
        name: _descriptor(
            tmp_path / f"receipt--{name}.json",
            {
                "schema": f"propertyquarry.synthetic-{name}.v1",
                "status": "blocked",
                "release_identity": RELEASE_IDENTITY,
            },
        )
        for name in terminal.CORE_RECEIPT_FLAGS
    }
    receipts["performance"] = _descriptor(
        tmp_path / "receipt--performance.json",
        {
            "schema": "propertyquarry.authenticated_performance.v2",
            "status": "blocked",
            "release_identity": RELEASE_IDENTITY,
            "constrained_client_evidence": {
                "engine_rows": [
                    {
                        "identity": {
                            "executable_path": CONTROLLER_BROWSER_EXECUTABLE_PATH,
                            "executable_sha256": CONTROLLER_BROWSER_EXECUTABLE_SHA256.removeprefix(
                                "sha256:"
                            ),
                        }
                    }
                ]
            },
        },
    )
    raw_observability = _raw_observability_descriptors(tmp_path)
    outputs = {
        "pinned_artifact_directory": str((tmp_path / "pinned").resolve()),
        "launch_evidence_directory": str((tmp_path / "launch-evidence").resolve()),
        "gold_status_receipt": str((tmp_path / "gold-status.json").resolve()),
        "terminal_status_receipt": str(
            (tmp_path / "global-terminal-status.json").resolve()
        ),
    }
    manifest: dict[str, object] = {
        "schema": terminal.MANIFEST_SCHEMA,
        "version": 1,
        "release_identity": dict(RELEASE_IDENTITY),
        "product_data": dict(PRODUCT_DATA),
        "receipts": receipts,
        "raw_observability": raw_observability,
        "terminal_authority": {
            "release_preflight": None,
            "disaster_recovery": None,
            "capacity": None,
            "observability_operations": None,
            "controller_attestation": None,
        },
        "outputs": outputs,
        "invocation_contract": _invocation_contract(outputs),
    }
    manifest_path = tmp_path / "global-launch-manifest.json"
    _write_manifest(manifest_path, manifest)
    return manifest_path, manifest


def _authority_payloads() -> dict[str, dict[str, object]]:
    observed_moment = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at = observed_moment.isoformat().replace("+00:00", "Z")
    capacity_ended = observed_moment - timedelta(seconds=1)
    capacity_started = capacity_ended - timedelta(seconds=600)
    capacity_window = {
        "started_at": capacity_started.isoformat().replace("+00:00", "Z"),
        "ended_at": capacity_ended.isoformat().replace("+00:00", "Z"),
        "duration_seconds": 600,
    }
    preflight = {
        "schema": terminal.PREFLIGHT_DECISION_SCHEMA,
        "status": "pass",
        "disposition": preflight_policy.READY,
        "required_check_set_digest": preflight_policy.REQUIRED_CHECK_SET_DIGEST,
        "passed_checks": list(preflight_policy.REQUIRED_CHECK_IDS),
        "failed_checks": [],
        "indeterminate_checks": [],
        "release_identity": dict(RELEASE_IDENTITY),
    }
    disaster_recovery = {
        "schema": terminal.DISASTER_RECOVERY_RECEIPT_SCHEMA,
        "operation": "release_gate",
        "status": "pass",
        "release": {
            "git_commit_sha": COMMIT_SHA,
            "image_digest": IMAGE_DIGEST,
        },
        "verification": {
            name: True
            for name in (
                "release_identity_exact",
                "encrypted_backup",
                "off_host_object_exact",
                "off_host_retrieval_exact",
                "disposable_restore",
                "rpo_met",
                "rto_met",
                "critical_data_exact_match",
                "evidence_fresh",
            )
        },
    }
    capacity_resources = []
    for index, resource in enumerate(terminal.CAPACITY_RESOURCE_KINDS):
        observed_peak = 100 + index
        forecast_peak = 120 + index
        required_peak = max(observed_peak, forecast_peak)
        operational_limit = required_peak * 2
        headroom_absolute = operational_limit - required_peak
        attempted_over_limit = 10 + index
        capacity_resources.append(
            {
                "resource": resource,
                "unit": terminal.CAPACITY_RESOURCE_UNITS[resource],
                "window": {**capacity_window, "sample_count": 60 + index},
                "demand": {
                    "observed_peak": observed_peak,
                    "forecast_peak": forecast_peak,
                    "required_peak": required_peak,
                },
                "capacity": {
                    "verified_sustainable_capacity": operational_limit + 50,
                    "operational_limit": operational_limit,
                    "headroom_absolute": headroom_absolute,
                    "headroom_basis_points": (
                        headroom_absolute * 10_000 // required_peak
                    ),
                    "sustainable_capacity_evidence_sha256": "sha256:"
                    + hashlib.sha256(
                        f"capacity:{resource}:sustainable".encode("utf-8")
                    ).hexdigest(),
                },
                "limit_test": {
                    "configured_limit": operational_limit,
                    "attempted_over_limit": attempted_over_limit,
                    "accepted_over_limit": 0,
                    "controlled_over_limit": attempted_over_limit,
                    "evidence_sha256": "sha256:"
                    + hashlib.sha256(
                        f"capacity:{resource}:limit".encode("utf-8")
                    ).hexdigest(),
                },
                "backpressure_test": {
                    "offered_at_saturation": operational_limit + 20,
                    "admitted_at_saturation": operational_limit,
                    "deferred": 10,
                    "rejected": 10,
                    "uncontrolled_failures": 0,
                    "accepted_work_lost": 0,
                    "recovery_seconds": index + 1,
                    "evidence_sha256": "sha256:"
                    + hashlib.sha256(
                        f"capacity:{resource}:backpressure".encode("utf-8")
                    ).hexdigest(),
                },
                "telemetry_evidence_sha256": "sha256:"
                + hashlib.sha256(
                    f"capacity:{resource}:telemetry".encode("utf-8")
                ).hexdigest(),
            }
        )
    capacity = {
        "schema": terminal.CAPACITY_RECEIPT_SCHEMA,
        "contract_sha256": CAPACITY_CONTRACT_SHA256,
        "status": "pass",
        "evidence_level": "protected_production",
        "deployment_id": terminal.PRODUCTION_DEPLOYMENT_ID,
        "observed_at": observed_at,
        "release_identity": dict(RELEASE_IDENTITY),
        "measurement_window": capacity_window,
        "summary": {
            "resource_count": len(capacity_resources),
            "total_sample_count": sum(
                row["window"]["sample_count"] for row in capacity_resources
            ),
            "minimum_headroom_basis_points": min(
                row["capacity"]["headroom_basis_points"]
                for row in capacity_resources
            ),
            "maximum_recovery_seconds": max(
                row["backpressure_test"]["recovery_seconds"]
                for row in capacity_resources
            ),
        },
        "resources": capacity_resources,
    }
    observability_operations = {
        "schema": terminal.OBSERVABILITY_OPERATIONS_RECEIPT_SCHEMA,
        "status": "pass",
        "observed_at": observed_at,
        "flagship_operations_sha256": FLAGSHIP_OPERATIONS_SHA256,
        "release_identity": dict(RELEASE_IDENTITY),
        "authenticated_live_receipts": [
            {
                "kind": kind,
                "schema": schema,
                "captured_at": observed_at,
                "sha256": "sha256:" + f"{index + 1:x}{index + 2:x}" * 32,
                "authentication_scheme": "Ed25519",
                "authentication_key_id": "propertyquarry-observability-authority",
                "authentication_receipt_sha256": (
                    "sha256:" + f"{index + 5:x}{index + 6:x}" * 32
                ),
                "release_filters": {
                    "release_commit_sha": COMMIT_SHA,
                    "release_image_digest": IMAGE_DIGEST,
                    "replica_id": "propertyquarry-api-1",
                },
            }
            for index, (kind, schema) in enumerate(
                terminal.OBSERVABILITY_LIVE_RECEIPT_SCHEMAS.items()
            )
        ],
        "log_ingestion": {
            "status": "pass",
            "correlation_id_sha256": "sha256:" + "01" * 32,
            "ingestion_receipt_sha256": "sha256:" + "12" * 32,
            "query_receipt_sha256": "sha256:" + "23" * 32,
            "matched_record_count": 4,
        },
        "trace_continuity": {
            "status": "pass",
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
            "boundaries": list(terminal.OBSERVABILITY_TRACE_BOUNDARIES),
            "span_evidence_sha256": "sha256:" + "34" * 32,
        },
        "dashboards": [
            {
                "scope": scope,
                "status": "pass",
                "dashboard_id": f"propertyquarry/{scope}/v1",
                "version_sha256": "sha256:" + f"{index + 4:x}{index + 5:x}" * 32,
                "availability_receipt_sha256": "sha256:"
                + f"{index + 5:x}{index + 6:x}" * 32,
            }
            for index, scope in enumerate(terminal.OBSERVABILITY_DASHBOARD_SCOPES)
        ],
        "alert_delivery": {
            "status": "pass",
            "delivered_at": observed_at,
            "delivery_receipt_sha256": "sha256:" + "78" * 32,
            "route_config_sha256": "sha256:" + "89" * 32,
        },
        "runbooks": [
            {
                "operation": operation,
                "immutable_uri": (
                    "https://operations.propertyquarry.at/runbooks/"
                    f"{COMMIT_SHA}/{operation}.md"
                ),
                "sha256": "sha256:" + f"{index + 9:x}{index + 10:x}" * 32,
            }
            for index, operation in enumerate(terminal.OBSERVABILITY_RUNBOOK_OPERATIONS)
        ],
    }
    return {
        "release_preflight": preflight,
        "disaster_recovery": disaster_recovery,
        "capacity": capacity,
        "observability_operations": observability_operations,
    }


def _complete_manifest(
    tmp_path: Path,
    *,
    authentication: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    manifest_path, manifest = _base_manifest(tmp_path)
    authority = manifest["terminal_authority"]
    assert isinstance(authority, dict)
    for name, payload in _authority_payloads().items():
        authority[name] = _descriptor(tmp_path / f"authority--{name}.json", payload)
    _write_manifest(manifest_path, manifest)
    loaded_without_controller = terminal.load_manifest(manifest_path)
    attestation: dict[str, object] = {
        "schema": terminal.CONTROLLER_ATTESTATION_SCHEMA,
        "deployment_id": "propertyquarry-production",
        "challenge_nonce": "0123456789abcdef0123456789abcdef",
        "release_identity": dict(RELEASE_IDENTITY),
        "product_data": dict(PRODUCT_DATA),
        "invocation_contract": loaded_without_controller.invocation_contract,
        "artifact_digests": loaded_without_controller.attested_artifact_digests(),
        "decisions": {
            "release_preflight": "pass",
            "disaster_recovery": "pass",
            "capacity": "pass",
            "observability_operations": "pass",
        },
        "authentication": authentication
        or {
            "scheme": "Ed25519",
            "key_id": "propertyquarry-release-control",
            "challenge_sha256": "ab" * 32,
            "signature": base64.urlsafe_b64encode(b"\0" * 64)
            .decode("ascii")
            .rstrip("="),
        },
    }
    authority["controller_attestation"] = _descriptor(
        tmp_path / "authority--controller-attestation.json",
        attestation,
    )
    _write_manifest(manifest_path, manifest)
    return manifest_path, manifest, attestation


def _run_main(
    manifest_path: Path,
    capsys: pytest.CaptureFixture[str],
    **kwargs: object,
) -> tuple[int, dict[str, object], str]:
    code = terminal.main(["--manifest", str(manifest_path.resolve())], **kwargs)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def _alternate_controller_browser_policy() -> dict[str, str]:
    executable_path = Path("/bin/true").resolve(strict=True)
    return {
        "engine": "chromium",
        "executable_path": str(executable_path),
        "executable_sha256": "sha256:"
        + hashlib.sha256(executable_path.read_bytes()).hexdigest(),
    }


def _pinned_gold_inputs() -> dict[str, dict[str, str]]:
    return {
        "receipts": {
            name: f"/run/propertyquarry/pinned/receipt--{name}"
            for name in terminal.CORE_RECEIPT_FLAGS
        },
        "raw_observability": {
            name: f"/run/propertyquarry/pinned/raw--{name}"
            for name in terminal.RAW_OBSERVABILITY_FLAGS
        },
    }


def test_documented_terminal_command_returns_structured_blocked_for_valid_manifest(
    tmp_path: Path,
) -> None:
    manifest_path, _manifest = _base_manifest(tmp_path)
    argv = shlex.split(terminal.GLOBAL_LAUNCH_TERMINAL_COMMAND)
    assert argv == [
        str(terminal.INSTALLED_ENTRYPOINT),
        "--manifest",
        terminal.GLOBAL_LAUNCH_MANIFEST_PATH,
    ]
    argv[-1] = str(manifest_path.resolve())
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/propertyquarry_global_launch_terminal.py"),
            *argv[1:],
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["schema"] == terminal.RESULT_SCHEMA
    assert result["status"] == "blocked"
    assert result["phase"] == "terminal_authority"
    assert result["gold_invoked"] is False
    assert {row["code"] for row in result["blockers"]} == {
        "release_preflight_evidence_missing",
        "disaster_recovery_evidence_missing",
        "capacity_evidence_missing",
        "observability_operations_evidence_missing",
        "controller_attestation_evidence_missing",
    }


def test_incomplete_manifest_fails_closed_without_argparse_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    receipts = manifest["receipts"]
    assert isinstance(receipts, dict)
    del receipts["performance"]
    _write_manifest(manifest_path, manifest)

    code, result, stderr = _run_main(manifest_path, capsys)

    assert code == 2
    assert stderr == ""
    assert result["phase"] == "manifest_validation"
    assert result["blockers"] == [
        {"code": "closed_schema_mismatch", "field": "receipts"}
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_field"),
    (
        (
            "missing",
            "closed_schema_mismatch",
            "invocation_contract",
        ),
        (
            "extra",
            "closed_schema_mismatch",
            "invocation_contract.performance_browser_policy",
        ),
        (
            "wrong_engine",
            "invocation_contract_mismatch",
            "invocation_contract.performance_browser_policy",
        ),
        (
            "relative_path",
            "path_not_canonical_absolute",
            "invocation_contract.performance_browser_policy.executable_path",
        ),
        (
            "unprefixed_sha256",
            "sha256_invalid",
            "invocation_contract.performance_browser_policy.executable_sha256",
        ),
    ),
)
def test_invocation_contract_rejects_unattested_or_malformed_browser_policy(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
    expected_field: str,
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    invocation_contract = manifest["invocation_contract"]
    assert isinstance(invocation_contract, dict)
    policy = invocation_contract.get("performance_browser_policy")
    assert isinstance(policy, dict)
    if mutation == "missing":
        del invocation_contract["performance_browser_policy"]
    elif mutation == "extra":
        policy["trusted"] = True
    elif mutation == "wrong_engine":
        policy["engine"] = "firefox"
    elif mutation == "relative_path":
        policy["executable_path"] = "controller-browser/chromium/chrome"
    else:
        policy["executable_sha256"] = CONTROLLER_BROWSER_EXECUTABLE_SHA256.removeprefix(
            "sha256:"
        )
    _write_manifest(manifest_path, manifest)

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal.load_manifest(manifest_path)

    assert rejected.value.code == expected_code
    assert rejected.value.field == expected_field


def test_controller_attestation_binds_performance_browser_policy(
    tmp_path: Path,
) -> None:
    manifest_path, manifest, attestation = _complete_manifest(tmp_path)
    invocation_contract = manifest["invocation_contract"]
    assert isinstance(invocation_contract, dict)
    policy = invocation_contract["performance_browser_policy"]
    assert isinstance(policy, dict)
    policy["executable_sha256"] = "sha256:" + "12" * 32
    _write_manifest(manifest_path, manifest)

    loaded = terminal.load_manifest(manifest_path)
    assert attestation["invocation_contract"] != loaded.invocation_contract
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._verify_controller_attestation(loaded)

    assert rejected.value.code == "controller_invocation_contract_mismatch"


@pytest.mark.parametrize(
    ("value", "expected_code"),
    (
        (None, "closed_schema_mismatch"),
        ("89abcdef01234567" * 4, "sha256_invalid"),
        ("sha256:" + "a" * 64, "sha256_placeholder"),
    ),
)
def test_invocation_contract_requires_independent_release_manifest_digest(
    tmp_path: Path,
    value: str | None,
    expected_code: str,
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    invocation_contract = manifest["invocation_contract"]
    assert isinstance(invocation_contract, dict)
    if value is None:
        del invocation_contract["release_manifest_sha256"]
    else:
        invocation_contract["release_manifest_sha256"] = value
    _write_manifest(manifest_path, manifest)

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal.load_manifest(manifest_path)

    assert rejected.value.code == expected_code
    assert rejected.value.field in {
        "invocation_contract",
        "invocation_contract.release_manifest_sha256",
    }


def test_controller_attestation_binds_release_manifest_digest(
    tmp_path: Path,
) -> None:
    manifest_path, manifest, _attestation = _complete_manifest(tmp_path)
    invocation_contract = manifest["invocation_contract"]
    assert isinstance(invocation_contract, dict)
    invocation_contract["release_manifest_sha256"] = "sha256:" + "12" * 32
    _write_manifest(manifest_path, manifest)

    loaded = terminal.load_manifest(manifest_path)
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._verify_controller_attestation(loaded)

    assert rejected.value.code == "controller_invocation_contract_mismatch"


def test_gold_argv_uses_controller_policy_not_forged_observed_browser_identity(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    invocation_contract = manifest["invocation_contract"]
    assert isinstance(invocation_contract, dict)
    controller_policy = _alternate_controller_browser_policy()
    invocation_contract["performance_browser_policy"] = controller_policy
    _write_manifest(manifest_path, manifest)
    loaded = terminal.load_manifest(manifest_path)

    performance = loaded.receipts["performance"].payload
    assert isinstance(performance, dict)
    observed_identity = performance["constrained_client_evidence"]["engine_rows"][0][
        "identity"
    ]
    forged_path = str((tmp_path / "forged" / "chromium" / "chrome").resolve())
    forged_sha256 = "34" * 32
    observed_identity["executable_path"] = forged_path
    observed_identity["executable_sha256"] = forged_sha256

    argv = terminal.build_gold_argv(loaded, _pinned_gold_inputs())

    assert loaded.invocation_contract["performance_browser_policy"] == controller_policy
    assert (
        argv[argv.index("--expected-performance-chromium-executable-path") + 1]
        == controller_policy["executable_path"]
    )
    assert (
        argv[argv.index("--expected-performance-chromium-executable-sha256") + 1]
        == controller_policy["executable_sha256"].removeprefix("sha256:")
    )
    assert forged_path not in argv
    assert forged_sha256 not in argv


@pytest.mark.parametrize(
    "invalid_origin",
    (
        "https://service.internal",
        "https://flagship.onion",
        "https://release.corp",
        "https://a.b",
        "https://service.notarealtld",
        "https://co.uk",
        "https://router.home.arpa",
        "https://host.localdomain",
        "https://host.private",
    ),
)
def test_terminal_origin_rejects_nonpublic_or_unsupported_registry(
    invalid_origin: str,
) -> None:
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._origin(invalid_origin, field="product_data.public_origin")

    assert rejected.value.code == "origin_invalid_or_placeholder"


def test_terminal_public_hostname_policy_is_bounded_and_explicit() -> None:
    assert terminal._supported_public_hostname("propertyquarry.at") is True
    assert terminal._supported_public_hostname("data.propertyquarry.at") is True
    assert terminal._supported_public_hostname("app.teable.io") is True
    assert terminal._supported_public_hostname("app.teable.ai") is True
    assert terminal._supported_public_hostname("app.rybbit.io") is True
    assert terminal._supported_public_hostname(
        ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 58, "com"))
    ) is False


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda manifest, _tmp: manifest["product_data"].__setitem__(
                "public_origin", "https://example.com"
            ),
            "origin_invalid_or_placeholder",
        ),
        (
            lambda manifest, _tmp: manifest["product_data"].__setitem__(
                "public_origin", "https://127.0.0.1"
            ),
            "origin_invalid_or_placeholder",
        ),
        (
            lambda manifest, _tmp: manifest["product_data"].__setitem__(
                "public_origin", "https://10.0.0.1"
            ),
            "origin_invalid_or_placeholder",
        ),
        (
            lambda manifest, _tmp: manifest["product_data"].__setitem__(
                "public_origin", "https://evil .com"
            ),
            "origin_invalid",
        ),
        (
            lambda manifest, _tmp: manifest["product_data"].__setitem__(
                "public_origin", "https://propertyquarry.at:"
            ),
            "origin_invalid_or_placeholder",
        ),
        (
            lambda manifest, _tmp: manifest["receipts"]["performance"].__setitem__(
                "sha256", "sha256:" + "10" * 32
            ),
            "artifact_digest_mismatch",
        ),
        (
            lambda manifest, _tmp: manifest["receipts"]["performance"].__setitem__(
                "release_identity",
                {
                    "commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
                    "image_digest": IMAGE_DIGEST,
                },
            ),
            "artifact_release_identity_mismatch",
        ),
    ),
)
def test_manifest_rejects_placeholder_digest_and_identity_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: Callable[[dict[str, object], Path], object],
    expected_code: str,
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    mutation(manifest, tmp_path)
    _write_manifest(manifest_path, manifest)

    code, result, _stderr = _run_main(manifest_path, capsys)

    assert code == 2
    assert result["blockers"][0]["code"] == expected_code


def test_manifest_rejects_symlinked_and_world_writable_receipts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    receipts = manifest["receipts"]
    assert isinstance(receipts, dict)
    performance = receipts["performance"]
    assert isinstance(performance, dict)
    original = Path(str(performance["path"]))
    symlink = tmp_path / "symlinked-receipt.json"
    symlink.symlink_to(original)
    performance["path"] = str(symlink)
    _write_manifest(manifest_path, manifest)

    code, result, _stderr = _run_main(manifest_path, capsys)
    assert code == 2
    assert result["blockers"][0]["code"] == "path_symlink_rejected"

    performance["path"] = str(original)
    original.chmod(0o666)
    _write_manifest(manifest_path, manifest)
    code, result, _stderr = _run_main(manifest_path, capsys)
    assert code == 2
    assert result["blockers"][0]["code"] == "file_metadata_unsafe"


def test_raw_observability_companions_are_attested_retained_and_pinned(
    tmp_path: Path,
) -> None:
    manifest_path, _manifest = _base_manifest(tmp_path)
    loaded = terminal.load_manifest(manifest_path)

    assert {
        name
        for artifacts in loaded.raw_observability_companions.values()
        for name in artifacts
    } == {
        "propertyquarry-api-1-start.prom",
        "propertyquarry-api-1-end.prom",
        "propertyquarry-api-1-probe.json",
    }
    captured = loaded.raw_observability_companions["slo_metrics_snapshot"][
        "propertyquarry-api-1-start.prom"
    ]
    assert (
        loaded.attested_artifact_digests()[
            "raw_observability.slo_metrics_snapshot.companions."
            "propertyquarry-api-1-start.prom"
        ]
        == captured.sha256
    )

    source = Path(captured.path)
    source.chmod(0o600)
    source.write_bytes(b"post-validation source drift must not enter Gold\n")
    source.chmod(0o400)
    pinned_paths = terminal._pin_manifest_artifacts(loaded)

    pinned = Path(loaded.outputs["pinned_artifact_directory"]) / source.name
    assert pinned.read_bytes() == captured.raw
    assert stat.S_IMODE(pinned.stat().st_mode) == 0o400
    for bundle_name, artifacts in loaded.raw_observability_companions.items():
        for name, artifact in artifacts.items():
            target = Path(loaded.outputs["pinned_artifact_directory"]) / name
            assert target.read_bytes() == artifact.raw, bundle_name
    snapshot_bundle = json.loads(
        Path(pinned_paths["raw_observability"]["slo_metrics_snapshot"]).read_bytes()
    )
    probe_bundle = json.loads(
        Path(pinned_paths["raw_observability"]["slo_metrics_probe"]).read_bytes()
    )
    referenced_names = {
        snapshot_bundle["replicas"][0]["start"]["path"],
        snapshot_bundle["replicas"][0]["end"]["path"],
        probe_bundle["replicas"][0]["path"],
    }
    assert all(
        (Path(loaded.outputs["pinned_artifact_directory"]) / name).is_file()
        for name in referenced_names
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("digest", "companion_digest_mismatch"),
        ("size", "companion_size_mismatch"),
        ("missing", "file_unavailable"),
        ("symlink", "path_symlink_rejected"),
    ),
)
def test_raw_observability_companion_tamper_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    manifest_path, _manifest = _base_manifest(tmp_path)
    baseline = terminal.load_manifest(manifest_path)
    artifact = baseline.raw_observability_companions["slo_metrics_snapshot"][
        "propertyquarry-api-1-start.prom"
    ]
    source = Path(artifact.path)
    source.chmod(0o600)
    if mutation == "digest":
        changed = bytearray(artifact.raw)
        changed[0] ^= 1
        source.write_bytes(changed)
        source.chmod(0o400)
    elif mutation == "size":
        source.write_bytes(artifact.raw + b"x")
        source.chmod(0o400)
    elif mutation == "missing":
        source.unlink()
    else:
        source.unlink()
        target = tmp_path / "symlink-target.prom"
        _write_bytes(target, artifact.raw)
        source.symlink_to(target)

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal.load_manifest(manifest_path)
    assert rejected.value.code == expected_code


@pytest.mark.parametrize(
    ("referenced_path", "expected_code"),
    (
        ("../outside.prom", "companion_path_invalid"),
        ("propertyquarry-api-1-start.prom", "companion_name_collision"),
    ),
)
def test_probe_companion_paths_reject_traversal_and_cross_bundle_collisions(
    tmp_path: Path,
    referenced_path: str,
    expected_code: str,
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    raw_values = manifest["raw_observability"]
    assert isinstance(raw_values, dict)
    probe_descriptor = raw_values["slo_metrics_probe"]
    assert isinstance(probe_descriptor, dict)
    probe = json.loads(Path(str(probe_descriptor["path"])).read_bytes())
    probe_reference = probe["replicas"][0]
    probe_reference["path"] = referenced_path
    if expected_code == "companion_name_collision":
        snapshot_descriptor = raw_values["slo_metrics_snapshot"]
        assert isinstance(snapshot_descriptor, dict)
        snapshot = json.loads(Path(str(snapshot_descriptor["path"])).read_bytes())
        start_reference = snapshot["replicas"][0]["start"]
        probe_reference["sha256"] = start_reference["sha256"]
        probe_reference["bytes"] = start_reference["bytes"]
    probe.pop("payload_sha256")
    _rewrite_descriptor_bytes(
        probe_descriptor,
        _bundle_bytes(_with_payload_hash(probe)),
    )
    _write_manifest(manifest_path, manifest)

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal.load_manifest(manifest_path)
    assert rejected.value.code == expected_code


def test_installed_tree_inventory_rejects_shadow_files_and_symlinks(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    scripts = installed / "runtime/scripts"
    scripts.mkdir(parents=True)
    expected = {
        "propertyquarry-global-launch-terminal",
        "global-launch-terminal-bundle.v1.json",
        "runtime/scripts/propertyquarry_gold_status.py",
    }
    for relative in expected:
        _write_bytes(installed / relative, relative.encode("utf-8"), mode=0o444)
    (installed / "propertyquarry-global-launch-terminal").chmod(0o555)
    scripts.chmod(0o555)
    (installed / "runtime").chmod(0o555)
    installed.chmod(0o555)

    terminal._verify_installed_tree_inventory(
        installed,
        expected_relative_files=expected,
        expected_uid=os.geteuid(),
    )

    scripts.chmod(0o755)
    shadow = scripts / "json.py"
    _write_bytes(shadow, b"raise RuntimeError('shadowed')\n")
    scripts.chmod(0o555)
    with pytest.raises(terminal.TerminalManifestError) as unexpected:
        terminal._verify_installed_tree_inventory(
            installed,
            expected_relative_files=expected,
            expected_uid=os.geteuid(),
        )
    assert unexpected.value.code == "installed_bundle_unexpected_files"

    scripts.chmod(0o755)
    shadow.chmod(0o600)
    shadow.unlink()
    namespace_shadow = scripts / "json"
    namespace_shadow.mkdir(mode=0o555)
    scripts.chmod(0o555)
    with pytest.raises(terminal.TerminalManifestError) as unexpected_directory:
        terminal._verify_installed_tree_inventory(
            installed,
            expected_relative_files=expected,
            expected_uid=os.geteuid(),
        )
    assert unexpected_directory.value.code == "installed_bundle_unexpected_files"

    scripts.chmod(0o755)
    namespace_shadow.rmdir()
    shadow.symlink_to(scripts / "propertyquarry_gold_status.py")
    scripts.chmod(0o555)
    with pytest.raises(terminal.TerminalManifestError) as unsafe:
        terminal._verify_installed_tree_inventory(
            installed,
            expected_relative_files=expected,
            expected_uid=os.geteuid(),
        )
    assert unsafe.value.code == "installed_tree_unsafe"


def test_manifest_rejects_boolean_version_type_confusion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, manifest = _base_manifest(tmp_path)
    manifest["version"] = True
    _write_manifest(manifest_path, manifest)

    code, result, stderr = _run_main(manifest_path, capsys)

    assert code == 2
    assert stderr == ""
    assert result["blockers"] == [
        {"code": "manifest_schema_invalid", "field": "manifest"}
    ]


def _validate_capacity_fixture(
    payload: dict[str, object],
    *,
    now: datetime | None = None,
) -> None:
    checked_at = now or datetime.fromisoformat(
        str(payload["observed_at"]).replace("Z", "+00:00")
    )
    terminal._validate_capacity(
        payload,
        RELEASE_IDENTITY,
        now=checked_at,
        contract_sha256=CAPACITY_CONTRACT_SHA256,
    )


def test_capacity_v2_fixture_is_numeric_closed_and_independently_recomputed() -> None:
    capacity = _authority_payloads()["capacity"]

    _validate_capacity_fixture(capacity)

    serialized = json.dumps(capacity, sort_keys=True)
    assert "capacity_ready" not in serialized
    assert "headroom_verified" not in serialized
    assert "limits_verified" not in serialized
    assert capacity["summary"] == {
        "resource_count": len(terminal.CAPACITY_RESOURCE_KINDS),
        "total_sample_count": sum(range(60, 60 + len(terminal.CAPACITY_RESOURCE_KINDS))),
        "minimum_headroom_basis_points": 10_000,
        "maximum_recovery_seconds": len(terminal.CAPACITY_RESOURCE_KINDS),
    }


def test_capacity_v1_status_and_boolean_claims_cannot_establish_authority() -> None:
    legacy = {
        "schema": "propertyquarry.capacity_readiness_receipt.v1",
        "status": "pass",
        "release_identity": dict(RELEASE_IDENTITY),
        "capacity_ready": True,
        "headroom_verified": True,
        "limits_verified": True,
        "resources": [
            {
                "resource": resource,
                "status": "pass",
                "measured": True,
                "limit_enforced": True,
                "backpressure_verified": True,
            }
            for resource in terminal.CAPACITY_RESOURCE_KINDS
        ],
    }

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._validate_capacity(
            legacy,
            RELEASE_IDENTITY,
            now=datetime.now(timezone.utc),
            contract_sha256=CAPACITY_CONTRACT_SHA256,
        )

    assert rejected.value.code == "closed_schema_mismatch"


@pytest.mark.parametrize("resource", terminal.CAPACITY_RESOURCE_KINDS)
def test_capacity_v2_recomputes_headroom_for_every_required_resource(
    resource: str,
) -> None:
    capacity = _authority_payloads()["capacity"]
    row = next(item for item in capacity["resources"] if item["resource"] == resource)
    row["capacity"]["headroom_absolute"] += 1

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        _validate_capacity_fixture(capacity)

    assert rejected.value.code == "capacity_numeric_evidence_invalid"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("contract", "capacity_contract_mismatch"),
        ("local_evidence_level", "capacity_not_ready"),
        ("wrong_deployment", "capacity_not_ready"),
        ("wrong_release", "capacity_not_ready"),
        ("wrong_unit", "capacity_resource_inventory_invalid"),
        ("boolean_sample", "capacity_numeric_evidence_invalid"),
        ("limit_accepts", "capacity_numeric_evidence_invalid"),
        ("backpressure_loses_work", "capacity_numeric_evidence_invalid"),
        ("reused_digest", "capacity_evidence_digest_reused"),
        ("summary", "capacity_numeric_evidence_invalid"),
        ("added_boolean", "closed_schema_mismatch"),
    ),
)
def test_capacity_v2_rejects_uncheckable_or_inconsistent_claims(
    mutation: str,
    expected_code: str,
) -> None:
    capacity = _authority_payloads()["capacity"]
    first = capacity["resources"][0]
    if mutation == "contract":
        capacity["contract_sha256"] = "sha256:" + "12" * 32
    elif mutation == "local_evidence_level":
        capacity["evidence_level"] = "bounded_local"
    elif mutation == "wrong_deployment":
        capacity["deployment_id"] = "propertyquarry-staging"
    elif mutation == "wrong_release":
        capacity["release_identity"]["commit_sha"] = (
            "89abcdef0123456789abcdef0123456789abcdef"
        )
    elif mutation == "wrong_unit":
        first["unit"] = "requests_per_second_x"
    elif mutation == "boolean_sample":
        first["window"]["sample_count"] = True
    elif mutation == "limit_accepts":
        first["limit_test"]["accepted_over_limit"] = 1
    elif mutation == "backpressure_loses_work":
        first["backpressure_test"]["accepted_work_lost"] = 1
    elif mutation == "reused_digest":
        capacity["resources"][1]["telemetry_evidence_sha256"] = first[
            "telemetry_evidence_sha256"
        ]
    elif mutation == "summary":
        capacity["summary"]["total_sample_count"] += 1
    else:
        capacity["capacity_ready"] = True

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        _validate_capacity_fixture(capacity)

    assert rejected.value.code == expected_code


def test_capacity_v2_receipt_and_measurement_window_are_freshness_bound() -> None:
    capacity = _authority_payloads()["capacity"]
    observed_at = datetime.fromisoformat(
        str(capacity["observed_at"]).replace("Z", "+00:00")
    )

    with pytest.raises(terminal.TerminalManifestError) as rejected:
        _validate_capacity_fixture(
            capacity,
            now=observed_at
            + timedelta(seconds=terminal.CAPACITY_MAXIMUM_AGE_SECONDS + 1),
        )

    assert rejected.value.code == "capacity_evidence_stale"


def test_capacity_duplicate_and_stale_observability_authorities_fail_closed(
    tmp_path: Path,
) -> None:
    manifest_path, manifest, _attestation = _complete_manifest(tmp_path)
    authority = manifest["terminal_authority"]
    assert isinstance(authority, dict)
    capacity = _authority_payloads()["capacity"]
    capacity["resources"].append(dict(capacity["resources"][0]))
    authority["capacity"] = _descriptor(
        tmp_path / "authority--capacity.json",
        capacity,
    )
    _write_manifest(manifest_path, manifest)
    with pytest.raises(terminal.TerminalManifestError) as duplicate:
        terminal.load_manifest(manifest_path)
    assert duplicate.value.code == "capacity_resource_inventory_invalid"

    capacity = _authority_payloads()["capacity"]
    authority["capacity"] = _descriptor(
        tmp_path / "authority--capacity.json",
        capacity,
    )
    observability = _authority_payloads()["observability_operations"]
    observability["observed_at"] = "2020-01-01T00:00:00Z"
    observability["alert_delivery"]["delivered_at"] = "2020-01-01T00:00:00Z"
    authority["observability_operations"] = _descriptor(
        tmp_path / "authority--observability_operations.json",
        observability,
    )
    _write_manifest(manifest_path, manifest)
    with pytest.raises(terminal.TerminalManifestError) as stale:
        terminal.load_manifest(manifest_path)
    assert stale.value.code == "observability_operations_not_ready"


def test_checkout_execution_cannot_substitute_for_installed_authority(
    tmp_path: Path,
) -> None:
    manifest_path, _manifest, _attestation = _complete_manifest(tmp_path)
    loaded = terminal.load_manifest(manifest_path)
    runner_called = False

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[object]:
        nonlocal runner_called
        runner_called = True
        raise AssertionError("Gold must not run")

    code, result = terminal.execute_terminal(
        loaded,
        runner=runner,
        authority_verifier=lambda _manifest: None,
        effective_uid=0,
    )

    assert code == 2
    assert runner_called is False
    assert result["phase"] == "installed_authority"
    assert result["blockers"][0]["code"] == "installed_entrypoint_required"


def test_complete_manifest_invokes_only_fixed_gold_argv_and_redacts_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, manifest_payload, _attestation = _complete_manifest(tmp_path)
    observed: dict[str, object] = {}

    def fake_runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = list(argv)
        observed["kwargs"] = kwargs
        gold_payload = {
            "schema": terminal.GOLD_STATUS_SCHEMA,
            "release_identity": dict(RELEASE_IDENTITY),
            "status": "blocked",
            "readiness_profile": "launch",
            "evidence_tier": "launch",
            "claim_scope": "core",
            "core_gold_status": "blocked",
            "ready_for_notification": False,
            "blockers": ["synthetic Gold blocker"],
        }
        gold_path = Path(argv[argv.index("--write") + 1])
        _write_json(gold_path, gold_payload, mode=0o600)
        return subprocess.CompletedProcess(
            argv,
            2,
            stdout="ignored-and-discarded",
            stderr="DO-NOT-LOG-controller-secret",
        )

    code, result, stderr = _run_main(
        manifest_path,
        capsys,
        runner=fake_runner,
        authority_verifier=lambda _manifest: None,
        installed_verifier=lambda _manifest: None,
        effective_uid=0,
    )

    assert code == 2
    assert result["status"] == "blocked"
    assert result["schema"] == terminal.RESULT_SCHEMA
    assert result["gold_invoked"] is True
    assert result["gold_result"]["schema"] == terminal.GOLD_STATUS_SCHEMA
    assert stderr == ""
    assert "DO-NOT-LOG" not in json.dumps(result)
    argv = observed["argv"]
    kwargs = observed["kwargs"]
    assert isinstance(argv, list)
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["timeout"] == terminal.GOLD_TIMEOUT_SECONDS
    assert kwargs["env"] == {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert argv[:7] == [
        sys.executable,
        str(ROOT / "scripts/propertyquarry_gold_status.py"),
        "--profile",
        "launch",
        "--claim-scope",
        "core",
        "--required-browser-engines",
    ]
    for flag in (*terminal.CORE_RECEIPT_FLAGS.values(), *terminal.RAW_OBSERVABILITY_FLAGS.values()):
        assert argv.count(flag) == 1
        assert str(argv[argv.index(flag) + 1]).startswith(
            str((tmp_path / "pinned").resolve()) + "/"
        )
    for name in terminal.GLOBAL_GOVERNANCE_RECEIPT_KEYS:
        assert terminal.CORE_RECEIPT_FLAGS[name] in argv
    assert argv[argv.index("--expected-release-sha") + 1] == COMMIT_SHA
    assert argv[argv.index("--expected-image-digest") + 1] == IMAGE_DIGEST
    assert (
        argv[argv.index("--expected-release-deployment-id") + 1]
        == terminal.RUNTIME_DEPLOYMENT_ID_PREFIX + COMMIT_SHA[:12]
    )
    assert (
        argv[argv.index("--expected-release-manifest-sha256") + 1]
        == CONTROLLER_RELEASE_MANIFEST_SHA256.removeprefix("sha256:")
    )
    assert (
        argv[
            argv.index("--expected-performance-chromium-executable-path") + 1
        ]
        == CONTROLLER_BROWSER_EXECUTABLE_PATH
    )
    assert (
        argv[
            argv.index("--expected-performance-chromium-executable-sha256") + 1
        ]
        == CONTROLLER_BROWSER_EXECUTABLE_SHA256.removeprefix("sha256:")
    )
    for key, flag in (
        ("public_origin", "--expected-public-origin"),
        ("teable_origin", "--expected-teable-origin"),
        ("teable_base_id_sha256", "--expected-teable-base-id-sha256"),
        ("rybbit_origin", "--expected-rybbit-origin"),
        ("rybbit_site_id_sha256", "--expected-rybbit-site-id-sha256"),
        ("evidence_overlay_phase", "--expected-evidence-overlay-phase"),
    ):
        assert argv[argv.index(flag) + 1] == PRODUCT_DATA[key]
    original_paths = {
        str(descriptor["path"])
        for group_name in ("receipts", "raw_observability", "terminal_authority")
        for descriptor in manifest_payload[group_name].values()
        if isinstance(descriptor, dict)
    }
    assert original_paths.isdisjoint(argv)


def test_gold_exit_status_inconsistency_becomes_wrapper_blocked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _manifest, _attestation = _complete_manifest(tmp_path)

    def inconsistent_runner(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[object]:
        gold_path = Path(argv[argv.index("--write") + 1])
        _write_json(
            gold_path,
            {
                "schema": terminal.GOLD_STATUS_SCHEMA,
                "release_identity": dict(RELEASE_IDENTITY),
                "status": "pass",
                "readiness_profile": "launch",
                "evidence_tier": "launch",
                "claim_scope": "core",
                "core_gold_status": "pass",
                "ready_for_notification": True,
                "blockers": [],
            },
            mode=0o600,
        )
        return subprocess.CompletedProcess(argv, 2)

    code, result, _stderr = _run_main(
        manifest_path,
        capsys,
        runner=inconsistent_runner,
        authority_verifier=lambda _manifest: None,
        installed_verifier=lambda _manifest: None,
        effective_uid=0,
    )

    assert code == 2
    assert result["phase"] == "gold_verification"
    assert result["gold_invoked"] is True
    assert result["blockers"] == [
        {"code": "gold_result_exit_status_mismatch", "field": "gold_result"}
    ]


def test_pass_revalidates_controller_and_writes_bound_terminal_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, manifest_payload, _attestation = _complete_manifest(tmp_path)
    authority_calls = 0

    def authority_verifier(_manifest: terminal.LaunchManifest) -> None:
        nonlocal authority_calls
        authority_calls += 1

    def passing_runner(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[object]:
        _write_json(
            Path(argv[argv.index("--write") + 1]),
            {
                "schema": terminal.GOLD_STATUS_SCHEMA,
                "release_identity": dict(RELEASE_IDENTITY),
                "status": "pass",
                "readiness_profile": "launch",
                "evidence_tier": "launch",
                "claim_scope": "core",
                "core_gold_status": "pass",
                "ready_for_notification": True,
                "blockers": [],
            },
            mode=0o600,
        )
        return subprocess.CompletedProcess(argv, 0)

    code, result, stderr = _run_main(
        manifest_path,
        capsys,
        runner=passing_runner,
        authority_verifier=authority_verifier,
        installed_verifier=lambda _manifest: None,
        effective_uid=0,
    )

    assert code == 0
    assert stderr == ""
    assert authority_calls == 2
    assert result["schema"] == terminal.RESULT_SCHEMA
    assert result["status"] == "pass"
    assert result["gold_invoked"] is True
    assert result["release_identity"] == RELEASE_IDENTITY
    for key in (
        "controller_attestation_sha256",
        "attested_artifact_map_sha256",
        "invocation_contract_sha256",
        "gold_result_sha256",
    ):
        assert terminal.SHA256_RE.fullmatch(result[key])
    terminal_receipt_path = Path(
        manifest_payload["outputs"]["terminal_status_receipt"]
    )
    assert json.loads(terminal_receipt_path.read_text(encoding="utf-8")) == result
    assert stat.S_IMODE(terminal_receipt_path.stat().st_mode) == 0o400


def test_gold_timeout_is_bounded_and_structured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _manifest, _attestation = _complete_manifest(tmp_path)

    def timeout_runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[object]:
        raise subprocess.TimeoutExpired(argv, terminal.GOLD_TIMEOUT_SECONDS)

    code, result, stderr = _run_main(
        manifest_path,
        capsys,
        runner=timeout_runner,
        authority_verifier=lambda _manifest: None,
        installed_verifier=lambda _manifest: None,
        effective_uid=0,
    )

    assert code == 2
    assert stderr == ""
    assert result["gold_invoked"] is True
    assert result["blockers"] == [
        {"code": "gold_execution_timeout", "field": "terminal_invocation"}
    ]


def test_controller_attestation_requires_real_active_challenge_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    checked_at = datetime.now(timezone.utc)
    challenge = evidence_contract.EvidenceChallenge(
        key_id="propertyquarry-release-control",
        deployment_id="propertyquarry-production",
        nonce="0123456789abcdef0123456789abcdef",
        issued_at=checked_at - timedelta(seconds=30),
        expires_at=checked_at + timedelta(minutes=5),
        release_commit_sha=COMMIT_SHA,
        release_image_digest=IMAGE_DIGEST,
        artifact_sha256="ab" * 32,
        policy_hashes={
            "flagship_operations_sha256": FLAGSHIP_OPERATIONS_SHA256,
        },
    )
    anchor = evidence_contract.TrustAnchor(
        key_id=challenge.key_id,
        public_key=public_key,
        file_sha256="cd" * 32,
        device=1,
        inode=1,
    )
    manifest_path, manifest_payload, attestation = _complete_manifest(tmp_path)
    unsigned = deepcopy(attestation)
    unsigned["authentication"] = {
        "scheme": evidence_contract.AUTH_SCHEME,
        "key_id": anchor.key_id,
        "challenge_sha256": challenge.artifact_sha256,
    }
    signature = private_key.sign(
        evidence_contract.authenticated_signature_message(
            terminal.CONTROLLER_ATTESTATION_DOMAIN,
            unsigned,
        )
    )
    signed = deepcopy(unsigned)
    signed["authentication"]["signature"] = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    authority = manifest_payload["terminal_authority"]
    assert isinstance(authority, dict)
    attestation_path = tmp_path / "authority--controller-attestation.json"
    authority["controller_attestation"] = _descriptor(attestation_path, signed)
    _write_manifest(manifest_path, manifest_payload)
    monkeypatch.setattr(
        evidence_contract,
        "load_evidence_challenge",
        lambda **_kwargs: (anchor, challenge),
    )

    loaded = terminal.load_manifest(manifest_path)
    terminal._verify_controller_attestation(loaded, now=checked_at)

    with pytest.raises(terminal.TerminalManifestError) as stale_operations:
        terminal._verify_controller_attestation(
            loaded,
            now=checked_at + timedelta(seconds=1_000),
        )
    assert stale_operations.value.code == "observability_operations_not_ready"

    bad_signature = Ed25519PrivateKey.generate().sign(b"wrong signed message")
    signed["authentication"]["signature"] = (
        base64.urlsafe_b64encode(bad_signature).decode("ascii").rstrip("=")
    )
    authority["controller_attestation"] = _descriptor(attestation_path, signed)
    _write_manifest(manifest_path, manifest_payload)
    tampered = terminal.load_manifest(manifest_path)
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._verify_controller_attestation(tampered, now=checked_at)
    assert rejected.value.code == "controller_cryptographic_verification_failed"


def test_controller_attestation_rejects_nonproduction_deployment_before_crypto(
    tmp_path: Path,
) -> None:
    manifest_path, manifest_payload, attestation = _complete_manifest(tmp_path)
    attestation["deployment_id"] = "propertyquarry-staging"
    authority = manifest_payload["terminal_authority"]
    assert isinstance(authority, dict)
    authority["controller_attestation"] = _descriptor(
        tmp_path / "authority--controller-attestation.json",
        attestation,
    )
    _write_manifest(manifest_path, manifest_payload)

    loaded = terminal.load_manifest(manifest_path)
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._verify_controller_attestation(loaded)
    assert rejected.value.code == "controller_deployment_mismatch"


def test_controller_signature_binds_product_data_and_every_referenced_digest(
    tmp_path: Path,
) -> None:
    manifest_path, manifest_payload, _attestation = _complete_manifest(tmp_path)
    loaded = terminal.load_manifest(manifest_path)
    attestation = loaded.terminal_authority["controller_attestation"]
    assert attestation is not None
    assert attestation.payload is not None
    assert attestation.payload["product_data"] == PRODUCT_DATA
    assert attestation.payload["artifact_digests"] == loaded.attested_artifact_digests()
    expected_keys = {
        *(f"receipts.{name}" for name in terminal.CORE_RECEIPT_FLAGS),
        *(f"raw_observability.{name}" for name in terminal.RAW_OBSERVABILITY_FLAGS),
        *(
            f"raw_observability.{bundle_name}.companions.{name}"
            for bundle_name, artifacts in loaded.raw_observability_companions.items()
            for name in artifacts
        ),
        "terminal_authority.release_preflight",
        "terminal_authority.disaster_recovery",
        "terminal_authority.capacity",
        "terminal_authority.observability_operations",
    }
    assert set(attestation.payload["artifact_digests"]) == expected_keys

    product = manifest_payload["product_data"]
    assert isinstance(product, dict)
    product["public_origin"] = "https://changed.propertyquarry.at"
    _write_manifest(manifest_path, manifest_payload)
    changed = terminal.load_manifest(manifest_path)
    with pytest.raises(terminal.TerminalManifestError) as rejected:
        terminal._verify_controller_attestation(changed)
    assert rejected.value.code == "controller_product_data_mismatch"


def test_fd_pinned_gold_uses_isolated_fixed_runtime_bootstrap(tmp_path: Path) -> None:
    manifest_path, _manifest, _attestation = _complete_manifest(tmp_path)
    loaded = terminal.load_manifest(manifest_path)
    pinned = {
        "receipts": {
            name: f"/run/propertyquarry/pinned/receipt--{name}"
            for name in terminal.CORE_RECEIPT_FLAGS
        },
        "raw_observability": {
            name: f"/run/propertyquarry/pinned/raw--{name}"
            for name in terminal.RAW_OBSERVABILITY_FLAGS
        },
    }

    argv = terminal.build_gold_argv(
        loaded,
        pinned,
        gold_path="/proc/self/fd/17",
    )

    assert argv[:5] == [
        str(terminal.INSTALLED_PYTHON_PATH),
        "-I",
        "-c",
        terminal.GOLD_FD_BOOTSTRAP,
        "/proc/self/fd/17",
    ]
    assert argv[5:11] == [
        "--profile",
        "launch",
        "--claim-scope",
        "core",
        "--required-browser-engines",
        "chromium,firefox,webkit",
    ]
    assert str(terminal.INSTALLED_RUNTIME_ROOT) in terminal.GOLD_FD_BOOTSTRAP
    assert str(terminal.INSTALLED_RUNTIME_ROOT / "scripts") in terminal.GOLD_FD_BOOTSTRAP


def test_installed_entrypoint_accepts_only_fixed_manifest_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(terminal, "SOURCE_PATH", terminal.INSTALLED_ENTRYPOINT)

    code = terminal.main(["--manifest", str(tmp_path / "alternate.json")])
    result = json.loads(capsys.readouterr().out)

    assert code == 2
    assert result["blockers"] == [
        {"code": "fixed_manifest_path_required", "field": "terminal_invocation"}
    ]
