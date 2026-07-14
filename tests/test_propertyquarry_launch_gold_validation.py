from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

import scripts.propertyquarry_gold_status as gold
from propertyquarry_evidence_test_support import (
    CanonicalMonitoringTestIdentity,
    install_test_canonical_monitoring_identity,
)


CANONICAL: CanonicalMonitoringTestIdentity


@pytest.fixture(autouse=True)
def _canonical_monitoring_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global CANONICAL
    CANONICAL = install_test_canonical_monitoring_identity(
        monkeypatch,
        directory=tmp_path / "canonical-monitoring",
    )


def _canonical_slo() -> dict[str, Any]:
    return {
        "status": "pass",
        "gate_passed": True,
        "inputs": {"metrics_snapshot": {"sha256": "1" * 64}},
        "probe": {"credential_persisted": False},
        "metrics": {"current_slos": {"availability": {"status": "pass"}}, "integrity": {}},
        "rules": {"sha256": "2" * 64},
        "monitoring_config": {"prometheus": {"sha256": "3" * 64}},
        "promtool": {"version_pinned": True},
        "amtool": {"routing_check_passed": True},
        "authenticated_evidence": {
            "policy_hashes": gold.evidence_contract.canonical_policy_hashes(),
        },
        "canonical_monitoring_identity": dict(CANONICAL.payload["identity"]),
        "monitoring_tools": dict(CANONICAL.payload["monitoring_tools"]),
    }


def _canonical_observability() -> dict[str, Any]:
    return {
        "schema_version": "propertyquarry.observability-receipt-verification.v2",
        "producer": "propertyquarry-observability-receipt-verifier",
        "status": "verified",
        "release": {"commit_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64},
        "replica_ids": ["replica-1"],
        "receipts": {
            "prometheus_range_response": {"file_sha256": "4" * 64, "series_sha256": "5" * 64}
        },
        "cross_receipt_links_verified": True,
        "policy_hashes": gold.evidence_contract.canonical_policy_hashes(),
        "canonical_monitoring_identity": dict(CANONICAL.payload["identity"]),
        "monitoring_tools": dict(CANONICAL.payload["monitoring_tools"]),
        "payload_sha256": "6" * 64,
    }


def test_gold_launch_runner_invokes_both_canonical_validators_from_raw_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_slo(*, config):  # type: ignore[no-untyped-def]
        calls["slo_config"] = config
        receipt = {
            **_canonical_slo(),
            "shared_input_hashes": dict(config.shared_input_hashes),
        }
        config.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return receipt, 0

    def fake_observability(**kwargs):  # type: ignore[no-untyped-def]
        calls["observability"] = kwargs
        return {
            **_canonical_observability(),
            "shared_input_hashes": dict(kwargs["expected_input_hashes"]),
        }

    monkeypatch.setattr(gold, "run_evidence_gate", fake_slo)
    monkeypatch.setattr(gold, "verify_receipt_bundle", fake_observability)

    paths = {
        name: tmp_path / name
        for name in ("metrics", "probe", "monitoring", "range", "response", "alert")
    }
    paths["metrics"].write_text('{"replicas":[]}', encoding="utf-8")
    paths["probe"].write_text('{"replicas":[]}', encoding="utf-8")
    for name in ("monitoring", "range", "response", "alert"):
        paths[name].write_text("fixture", encoding="utf-8")
    original_bytes = {name: path.read_bytes() for name, path in paths.items()}
    slo, observability, slo_path, observability_path, errors = gold._run_canonical_launch_validators(
        release_commit_sha="a" * 40,
        release_image_digest="sha256:" + "b" * 64,
        metrics_snapshot_path=paths["metrics"],
        metrics_probe_path=paths["probe"],
        monitoring_receipt_path=paths["monitoring"],
        prometheus_range_receipt_path=paths["range"],
        prometheus_range_response_path=paths["response"],
        alert_delivery_receipt_path=paths["alert"],
        output_directory=tmp_path / "verified",
        _test_allow_insecure_inputs=True,
    )

    assert errors == []
    assert slo["gate_passed"] is True
    assert observability["status"] == "verified"
    assert calls["slo_config"].metrics_snapshot_path != paths["metrics"]
    assert calls["slo_config"].metrics_snapshot_path.read_bytes() == original_bytes["metrics"]
    assert calls["slo_config"].metrics_probe_path.read_bytes() == original_bytes["probe"]
    assert calls["slo_config"].metrics_snapshot_path.parent.name == "pinned-inputs"
    assert calls["slo_config"].flagship is True
    assert (
        calls["observability"]["prometheus_range_response_path"].read_bytes()
        == original_bytes["response"]
    )
    assert calls["slo_config"].shared_input_hashes == calls["observability"][
        "expected_input_hashes"
    ]
    assert slo_path.is_file()
    assert observability_path.is_file()
    assert stat.S_IMODE(observability_path.stat().st_mode) == 0o600


def test_gold_embeds_recomputed_launch_fields_and_blocks_any_validator_failure(tmp_path: Path) -> None:
    receipt: dict[str, Any] = {
        "status": "pass",
        "ready_for_notification": True,
        "blockers": [],
        "pass_areas": [],
        "next_required_actions": [],
        "notes": [],
    }
    gold._apply_canonical_launch_evidence(
        receipt,
        slo_receipt=_canonical_slo(),
        observability_receipt=_canonical_observability(),
        slo_receipt_path=tmp_path / "slo.json",
        observability_receipt_path=tmp_path / "observability.json",
        validation_errors=[],
    )

    assert receipt["status"] == "pass"
    launch = receipt["canonical_launch_evidence"]
    assert launch["slo"]["metrics"]["current_slos"]
    assert launch["slo"]["promtool"]["version_pinned"] is True
    assert launch["slo"]["amtool"]["routing_check_passed"] is True
    assert launch["observability"]["receipts"]["prometheus_range_response"]["file_sha256"]

    failed = {
        "status": "pass",
        "ready_for_notification": True,
        "blockers": [],
        "pass_areas": [],
        "next_required_actions": [],
        "notes": [],
    }
    gold._apply_canonical_launch_evidence(
        failed,
        slo_receipt=_canonical_slo(),
        observability_receipt={},
        slo_receipt_path=tmp_path / "slo.json",
        observability_receipt_path=tmp_path / "observability.json",
        validation_errors=["range response hash mismatch"],
    )

    assert failed["status"] == "blocked"
    assert failed["ready_for_notification"] is False
    assert failed["blockers"][-1]["area"] == "canonical_launch_evidence"

    arbitrary_identity = _canonical_observability()
    arbitrary_identity["canonical_monitoring_identity"] = {
        **arbitrary_identity["canonical_monitoring_identity"],
        "topology_contract_sha256": "f" * 64,
    }
    identity_failed = {
        "status": "pass",
        "ready_for_notification": True,
        "blockers": [],
        "pass_areas": [],
        "next_required_actions": [],
        "notes": [],
    }
    gold._apply_canonical_launch_evidence(
        identity_failed,
        slo_receipt=_canonical_slo(),
        observability_receipt=arbitrary_identity,
        slo_receipt_path=tmp_path / "slo.json",
        observability_receipt_path=tmp_path / "observability.json",
        validation_errors=[],
    )
    assert identity_failed["status"] == "blocked"
    assert "monitoring" in identity_failed["canonical_launch_evidence"][
        "validation_errors"
    ][0]


def test_gold_status_writes_private_atomic_release_receipts(tmp_path: Path) -> None:
    output = tmp_path / "gold.json"
    gold._write_gold_status_output(output, '{"status":"pass"}')

    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_launch_input_snapshot_rejects_symlink_and_replacement_race(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b'{"value":"original"}')
    source.chmod(0o400)
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(source)

    with pytest.raises(ValueError, match="non-symlink regular file"):
        gold._secure_launch_input_bytes(
            symlink,
            field="launch input",
            _test_allow_insecure=True,
        )

    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b'{"value":"attacker"}')
    replacement.chmod(0o400)
    original_read = gold.os.read
    replaced = False

    def replacing_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        raw = original_read(fd, size)
        if not replaced:
            replaced = True
            source.unlink()
            replacement.rename(source)
        return raw

    monkeypatch.setattr(gold.os, "read", replacing_read)
    with pytest.raises(ValueError, match="changed while it was snapshotted"):
        gold._secure_launch_input_bytes(
            source,
            field="launch input",
            _test_allow_insecure=True,
        )


def test_launch_input_snapshot_rejects_writable_mode(tmp_path: Path) -> None:
    source = tmp_path / "writable.json"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o620)

    with pytest.raises(ValueError, match="ownership, mode, or size is unsafe"):
        gold._secure_launch_input_bytes(
            source,
            field="launch input",
            _test_allow_insecure=True,
        )


def test_launch_validator_rejects_policy_path_override_before_reading_inputs(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="policy path override is forbidden"):
        gold._run_canonical_launch_validators(
            release_commit_sha="a" * 40,
            release_image_digest="sha256:" + "b" * 64,
            metrics_snapshot_path=missing,
            metrics_probe_path=missing,
            monitoring_receipt_path=missing,
            prometheus_range_receipt_path=missing,
            prometheus_range_response_path=missing,
            alert_delivery_receipt_path=missing,
            output_directory=tmp_path / "output",
            slo_path=tmp_path / "lax-slo.yml",
            _test_allow_insecure_inputs=True,
        )
    assert not (tmp_path / "output").exists()


def test_flagship_profile_requires_all_raw_launch_inputs(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["propertyquarry_gold_status.py", "--profile", "flagship", "--write", ""],
    )
    with pytest.raises(SystemExit) as exc_info:
        gold.main()
    assert exc_info.value.code == 2
