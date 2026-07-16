from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import property_evidence_overlay_read_model as overlay


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
CANDIDATE_SHA = "a" * 40
OLD_SNAPSHOT_ID = "b" * 64
EXPECTED_ORIGIN = "https://teable.example.com"
EXPECTED_BASE_ID_SHA256 = "d" * 64
WORKFLOW_HEAD_SHA = "c" * 40
WORKFLOW_RUN_ID = "123"
WORKFLOW_RUN_ATTEMPT = "2"
ACTIVATION_AUTHORITY_SHA256 = "e" * 64
STAGED_RECEIPT_SHA256 = "f" * 64


def _activation_binding() -> dict[str, object]:
    return {
        "activation_authority_sha256": ACTIVATION_AUTHORITY_SHA256,
        "staged_receipt_sha256": STAGED_RECEIPT_SHA256,
        "authorized_workflow": {
            "head_sha": WORKFLOW_HEAD_SHA,
            "run_id": WORKFLOW_RUN_ID,
            "run_attempt": WORKFLOW_RUN_ATTEMPT,
        },
    }


def _activation_authority(
    staged: dict[str, object],
    *,
    staged_receipt_sha256: str,
    generated_at: datetime,
) -> dict[str, object]:
    return {
        "schema": overlay.ACTIVATION_AUTHORITY_SCHEMA,
        "status": "pass",
        "generated_at": generated_at.isoformat(),
        "authority_phase": "preactivation",
        "candidate_sha": CANDIDATE_SHA,
        "workflow": {
            "head_sha": WORKFLOW_HEAD_SHA,
            "run_id": WORKFLOW_RUN_ID,
            "run_attempt": WORKFLOW_RUN_ATTEMPT,
        },
        "teable_authority": {
            "origin": EXPECTED_ORIGIN,
            "base_id_sha256": EXPECTED_BASE_ID_SHA256,
            "supplied_independently": True,
        },
        "activation_scope": {
            "snapshot_id": staged["snapshot_id"],
            "staged_overlay_receipt_sha256": staged_receipt_sha256,
            "activation_authority_sha256": "",
        },
        "inputs": {"overlay": {"sha256": staged_receipt_sha256}},
        "checks": [{"name": "all_current_run_evidence", "ok": True}],
        "failures": [],
        "activation_authorized": True,
        "launch_authorized": False,
        "notification_authorized": False,
    }


def _registry() -> dict[str, object]:
    return json.loads(overlay.REGISTRY_PATH.read_text(encoding="utf-8"))


def _valid_export(registry: dict[str, object]) -> dict[str, object]:
    generated_at = NOW.isoformat()
    tables: dict[str, list[dict[str, object]]] = {}
    evidence: dict[str, dict[str, object]] = {}
    for index, layer in enumerate(overlay._registry_layers(registry)):
        table_name = str(layer["teable_table"])
        layer_key = str(layer["layer_key"])
        fields: dict[str, object] = {
            "match": {"postal_code": f"10{index:02d}"},
            "summary": f"Verified {layer_key} context",
            "source_name": "Launch source",
            "source_url": f"https://source.example.com/{layer_key}",
            "source_updated_at": generated_at,
            "cache_updated_at": generated_at,
            "uncertainty_label": "area-level context",
            "ui_state": "verified",
        }
        if layer_key == "media_attention":
            fields["article_url"] = "https://news.example.com/article"
        tables[table_name] = [{"id": f"record-{index}", "fields": fields}]
        evidence[table_name] = {
            "table_id_sha256": f"{index:064x}",
            "record_count": 1,
            "page_count": 1,
            "pages": [
                {
                    "status_code": 200,
                    "response_sha256": f"{index + 20:064x}",
                    "size_bytes": 100,
                }
            ],
        }
    return {
        "schema": overlay.EXPORT_SCHEMA,
        "generated_at": generated_at,
        "tables": tables,
        "source_evidence": {
            "mode": "authenticated_teable_api",
            "auth_kind": "bearer_api_key",
            "secret_in_export": False,
            "base_origin": EXPECTED_ORIGIN,
            "base_id_sha256": EXPECTED_BASE_ID_SHA256,
            "redirects_followed": False,
            "table_discovery": {
                "status_code": 200,
                "response_sha256": "e" * 64,
                "size_bytes": 100,
            },
            "tables": evidence,
        },
    }


def _valid_plan() -> dict[str, object]:
    registry = _registry()
    plan = overlay.build_ingestion_plan(
        export=_valid_export(registry),
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )
    assert plan["status"] == "pass", plan["failures"]
    return plan


class _FakeRepository:
    def __init__(self, plan: dict[str, object]) -> None:
        self.plan = plan
        self.active_id = OLD_SNAPSHOT_ID
        self.staged_id = ""
        self.calls: list[str] = []
        self.break_candidate_coverage = False
        self.break_active_coverage = False

    def ensure_schema(self) -> None:
        self.calls.append("ensure_schema")

    def active_snapshot_id(self) -> str:
        self.calls.append("active_snapshot_id")
        return self.active_id

    def stage_snapshot(self, **kwargs: object) -> None:
        self.calls.append("stage_snapshot")
        self.staged_id = str(kwargs["snapshot_id"])

    def _coverage(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record in list(self.plan["records"]):
            row = dict(record)
            rows.append(
                {
                    "layer_key": row["layer_key"],
                    "teable_table": row["teable_table"],
                    "record_count": 1,
                    "latest_cache_updated_at": row["cache_updated_at"],
                    "latest_ingested_at": NOW.isoformat(),
                }
            )
        return rows

    def coverage(self, *, snapshot_id: str = "") -> list[dict[str, object]]:
        self.calls.append(f"coverage:{snapshot_id or 'active'}")
        if snapshot_id and self.break_candidate_coverage:
            return self._coverage()[:-1]
        if not snapshot_id and self.break_active_coverage:
            return []
        return self._coverage()

    def lookup(
        self,
        lookup_values: dict[str, str],
        *,
        snapshot_id: str = "",
    ) -> list[dict[str, object]]:
        self.calls.append(f"lookup:{snapshot_id}")
        for record in list(self.plan["records"]):
            row = dict(record)
            match = dict(row["match"])
            if any(match.get(key) == value for key, value in lookup_values.items()):
                return [{"layer_key": row["layer_key"]}]
        return []

    def benchmark_samples(
        self,
        *,
        snapshot_id: str,
    ) -> list[tuple[str, dict[str, str]]]:
        self.calls.append(f"benchmark_samples:{snapshot_id}")
        return [
            (str(row["layer_key"]), dict(row["match"]))
            for row in (dict(record) for record in list(self.plan["records"]))
        ]

    def discard_staged_snapshot(self, snapshot_id: str) -> None:
        self.calls.append("discard_staged_snapshot")
        assert snapshot_id == self.staged_id
        self.staged_id = ""

    def activate_snapshot(
        self,
        *,
        snapshot_id: str,
        activated_at: str,
        expected_previous_snapshot_id: str,
    ) -> str:
        del activated_at
        self.calls.append("activate_snapshot")
        assert expected_previous_snapshot_id == self.active_id
        previous = self.active_id
        self.active_id = snapshot_id
        return previous

    def restore_active_snapshot(
        self,
        *,
        failed_snapshot_id: str,
        restore_snapshot_id: str,
        restored_at: str,
    ) -> bool:
        del restored_at
        self.calls.append("restore_active_snapshot")
        if self.active_id == restore_snapshot_id:
            return False
        assert self.active_id == failed_snapshot_id
        self.active_id = restore_snapshot_id
        return True


def _staged_receipt() -> tuple[dict[str, object], _FakeRepository]:
    plan = _valid_plan()
    repository = _FakeRepository(plan)
    receipt = overlay.execute_ingestion(
        plan=plan,
        repository=repository,
        candidate_sha=CANDIDATE_SHA,
        max_query_ms=100.0,
        stage_only=True,
        observed_at=NOW,
    )
    assert receipt["status"] == "pass", receipt["failures"]
    return receipt, repository


def test_failed_candidate_validation_discards_stage_and_preserves_active() -> None:
    plan = _valid_plan()
    repository = _FakeRepository(plan)
    repository.break_candidate_coverage = True

    receipt = overlay.execute_ingestion(
        plan=plan,
        repository=repository,
        candidate_sha=CANDIDATE_SHA,
        max_query_ms=100.0,
        stage_only=True,
        observed_at=NOW,
    )

    assert receipt["status"] == "fail"
    assert repository.active_id == OLD_SNAPSHOT_ID
    assert "activate_snapshot" not in repository.calls
    assert repository.calls[-1] == "discard_staged_snapshot"
    assert receipt["activation"]["candidate_discarded"] is True
    assert receipt["activation"]["active_snapshot_preserved_on_failure"] is True


def test_stage_only_benchmarks_candidate_without_switching_active() -> None:
    receipt, repository = _staged_receipt()

    assert repository.active_id == OLD_SNAPSHOT_ID
    assert "activate_snapshot" not in repository.calls
    assert "discard_staged_snapshot" not in repository.calls
    assert len([call for call in repository.calls if call.startswith("lookup:")]) == 24
    assert receipt["activation"]["phase"] == "staged"
    assert receipt["activation"]["activation_performed"] is False
    assert receipt["activation"]["active_snapshot_unchanged"] is True


def test_ingestion_cannot_switch_active_without_explicit_authority() -> None:
    plan = _valid_plan()
    repository = _FakeRepository(plan)

    receipt = overlay.execute_ingestion(
        plan=plan,
        repository=repository,
        candidate_sha=CANDIDATE_SHA,
        max_query_ms=100.0,
        stage_only=False,
        observed_at=NOW,
    )

    assert receipt["status"] == "fail"
    assert repository.active_id == OLD_SNAPSHOT_ID
    assert repository.calls == []
    assert any("preactivation authority" in item for item in receipt["failures"])


def test_explicit_activation_is_receipt_bound_and_revalidates_active_snapshot() -> None:
    staged, repository = _staged_receipt()

    active = overlay.activate_staged_receipt(
        receipt=staged,
        repository=repository,
        snapshot_id=str(staged["snapshot_id"]),
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        **_activation_binding(),
        now=NOW,
    )

    assert active["status"] == "pass", active["failures"]
    assert repository.active_id == staged["snapshot_id"]
    assert active["activation"]["phase"] == "active"
    assert active["activation"]["activation_performed"] is True
    assert active["activation"]["active_revalidation_performed"] is True
    assert active["activation"]["active_revalidation_query_sample_count"] == 24
    assert (
        active["activation"]["activation_authority_sha256"]
        == ACTIVATION_AUTHORITY_SHA256
    )
    assert active["activation"]["staged_receipt_sha256"] == STAGED_RECEIPT_SHA256
    assert active["activation"]["authorized_workflow"] == _activation_binding()[
        "authorized_workflow"
    ]
    assert repository.calls.index("activate_snapshot") > max(
        index
        for index, call in enumerate(repository.calls)
        if call.startswith(f"lookup:{staged['snapshot_id']}")
    )


def test_failed_active_revalidation_restores_previous_pointer() -> None:
    staged, repository = _staged_receipt()
    repository.break_active_coverage = True

    failed = overlay.activate_staged_receipt(
        receipt=staged,
        repository=repository,
        snapshot_id=str(staged["snapshot_id"]),
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        **_activation_binding(),
        now=NOW,
    )

    assert failed["status"] == "fail"
    assert repository.active_id == OLD_SNAPSHOT_ID
    assert repository.calls[-1] == "restore_active_snapshot"
    assert failed["activation"]["rollback_performed"] is True
    assert failed["activation"]["active_snapshot_preserved_on_failure"] is True


def test_rollback_token_compare_restore_is_idempotent_and_refuses_lost_pointer() -> (
    None
):
    staged, repository = _staged_receipt()
    active = overlay.activate_staged_receipt(
        receipt=staged,
        repository=repository,
        snapshot_id=str(staged["snapshot_id"]),
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        **_activation_binding(),
        now=NOW,
    )
    token = overlay.build_activation_rollback_token(
        staged_receipt=staged,
        expected_candidate_sha=CANDIDATE_SHA,
        **_activation_binding(),
        now=NOW,
    )
    token["status"] = "armed"
    token["active_receipt_sha256"] = overlay._sha256(active)

    restored = overlay.restore_activation_from_token(
        token=token,
        repository=repository,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_activated_snapshot_id=str(staged["snapshot_id"]),
        now=NOW,
    )
    repeated = overlay.restore_activation_from_token(
        token=restored,
        repository=repository,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_activated_snapshot_id=str(staged["snapshot_id"]),
        now=NOW,
    )

    assert restored["status"] == "restored"
    assert restored["restore_performed"] is True
    assert repeated["status"] == "restored"
    assert repeated["restore_idempotent_noop"] is True
    assert repository.active_id == OLD_SNAPSHOT_ID

    repository.active_id = "e" * 64
    refused = overlay.restore_activation_from_token(
        token=token,
        repository=repository,
        expected_candidate_sha=CANDIDATE_SHA,
        expected_activated_snapshot_id=str(staged["snapshot_id"]),
        now=NOW,
    )
    assert refused["status"] == "fail"
    assert repository.active_id == "e" * 64


def test_atomic_receipts_are_mode_600(tmp_path: Path) -> None:
    path = tmp_path / "rollback.json"

    overlay._atomic_write(path, {"schema": overlay.ROLLBACK_TOKEN_SCHEMA})

    assert path.stat().st_mode & 0o777 == 0o600


def test_restore_cli_needs_no_teable_secret_or_authority_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staged, repository = _staged_receipt()
    active = overlay.activate_staged_receipt(
        receipt=staged,
        repository=repository,
        snapshot_id=str(staged["snapshot_id"]),
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        **_activation_binding(),
        now=NOW,
    )
    token = overlay.build_activation_rollback_token(
        staged_receipt=staged,
        expected_candidate_sha=CANDIDATE_SHA,
        **_activation_binding(),
        now=NOW,
    )
    token["status"] = "armed"
    token["active_receipt_sha256"] = overlay._sha256(active)
    token_path = tmp_path / "rollback.json"
    output_path = tmp_path / "restore.json"
    overlay._atomic_write(token_path, token)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/property")
    monkeypatch.delenv("PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN", raising=False)
    monkeypatch.delenv(
        "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256",
        raising=False,
    )
    monkeypatch.setattr(
        overlay,
        "PostgresPropertyEvidenceOverlayRepository",
        lambda _database_url: repository,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "property_evidence_overlay_read_model.py",
            "--candidate-sha",
            CANDIDATE_SHA,
            "--restore-activation",
            str(staged["snapshot_id"]),
            "--rollback-receipt",
            str(token_path),
            "--write",
            str(output_path),
        ],
    )

    assert overlay.main() == 0
    assert repository.active_id == OLD_SNAPSHOT_ID
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "restored"
    assert token_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("authority_case", ["missing", "wrong", "stale"])
def test_activation_cli_refuses_missing_wrong_or_stale_preauthority_without_switch(
    authority_case: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    staged, repository = _staged_receipt()
    staged_path = tmp_path / "staged.json"
    authority_path = tmp_path / "activation-authority.json"
    rollback_path = tmp_path / "rollback.json"
    output_path = tmp_path / "active.json"
    overlay._atomic_write(staged_path, staged)
    staged_receipt_sha256 = overlay._sha256_bytes(staged_path.read_bytes())
    current = datetime.now(timezone.utc)
    if authority_case != "missing":
        generated_at = (
            current - timedelta(seconds=overlay.MAX_ACTIVATION_AUTHORITY_AGE_SECONDS + 1)
            if authority_case == "stale"
            else current
        )
        authority = _activation_authority(
            staged,
            staged_receipt_sha256=staged_receipt_sha256,
            generated_at=generated_at,
        )
        if authority_case == "wrong":
            authority["activation_scope"]["staged_overlay_receipt_sha256"] = "0" * 64
        overlay._atomic_write(authority_path, authority)

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/property")
    monkeypatch.setenv("PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN", EXPECTED_ORIGIN)
    monkeypatch.setenv(
        "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256",
        EXPECTED_BASE_ID_SHA256,
    )
    monkeypatch.setattr(
        overlay,
        "PostgresPropertyEvidenceOverlayRepository",
        lambda _database_url: repository,
    )
    argv = [
        "property_evidence_overlay_read_model.py",
        "--candidate-sha",
        CANDIDATE_SHA,
        "--activate-snapshot",
        str(staged["snapshot_id"]),
        "--staged-receipt",
        str(staged_path),
        "--rollback-receipt",
        str(rollback_path),
        "--workflow-head-sha",
        WORKFLOW_HEAD_SHA,
        "--workflow-run-id",
        WORKFLOW_RUN_ID,
        "--workflow-run-attempt",
        WORKFLOW_RUN_ATTEMPT,
        "--write",
        str(output_path),
    ]
    if authority_case != "missing":
        argv.extend(["--activation-authority", str(authority_path)])
    monkeypatch.setattr(sys, "argv", argv)

    assert overlay.main() == 1
    assert repository.active_id == OLD_SNAPSHOT_ID
    assert "activate_snapshot" not in repository.calls
    assert not rollback_path.exists()


def test_verifier_requires_independent_origin_and_base_identity() -> None:
    receipt, _repository = _staged_receipt()

    wrong_origin = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin="https://other.example.com",
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )
    wrong_base = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256="f" * 64,
        expected_phase="staged",
        now=NOW,
    )

    assert any("origin" in failure for failure in wrong_origin)
    assert any("base identity" in failure for failure in wrong_base)


@pytest.mark.parametrize("invalid_age", [math.nan, math.inf, -math.inf])
def test_ingestion_plan_rejects_non_finite_age_threshold(invalid_age: float) -> None:
    registry = _registry()

    plan = overlay.build_ingestion_plan(
        export=_valid_export(registry),
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=invalid_age,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    assert "max_age_hours must be a positive finite number" in plan["failures"]


@pytest.mark.parametrize("invalid_query", [math.nan, math.inf, -math.inf])
def test_execute_rejects_non_finite_query_budget_before_staging(
    invalid_query: float,
) -> None:
    plan = _valid_plan()
    repository = _FakeRepository(plan)

    receipt = overlay.execute_ingestion(
        plan=plan,
        repository=repository,
        candidate_sha=CANDIDATE_SHA,
        max_query_ms=invalid_query,
        stage_only=True,
        observed_at=NOW,
    )

    assert receipt["status"] == "fail"
    assert repository.calls == []
    assert "max_query_ms must be a positive finite number" in receipt["failures"]


def test_verifier_rejects_non_finite_receipt_thresholds() -> None:
    receipt, _repository = _staged_receipt()
    receipt["freshness"]["max_age_policy_hours"] = math.nan
    receipt["read_model"]["query_p95_ms"] = math.inf
    receipt["read_model"]["query_budget_ms"] = math.nan

    failures = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )

    assert "evidence overlay receipt freshness policy is invalid" in failures
    assert (
        "evidence overlay receipt query budget exceeds the launch maximum" in failures
    )
    assert "evidence overlay receipt exceeds its query performance budget" in failures


def test_launch_cli_rejects_prefetched_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "receipt.json"
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/property")
    monkeypatch.setenv("PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN", EXPECTED_ORIGIN)
    monkeypatch.setenv(
        "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256",
        EXPECTED_BASE_ID_SHA256,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "property_evidence_overlay_read_model.py",
            "--candidate-sha",
            CANDIDATE_SHA,
            "--stage-only",
            "--teable-export",
            str(fixture),
            "--write",
            str(output),
        ],
    )

    assert overlay.main() == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "fail"


def test_launch_cli_rejects_teable_origin_before_authenticated_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "receipt.json"
    fetch_called = False
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/property")
    monkeypatch.setenv("TEABLE_BASE_URL", "https://untrusted.example.com")
    monkeypatch.setenv("TEABLE_API_KEY", "protected-test-key")
    monkeypatch.setenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_TEABLE_BASE_ID", "base-id")
    monkeypatch.setenv("PROPERTYQUARRY_EXPECTED_TEABLE_ORIGIN", EXPECTED_ORIGIN)
    monkeypatch.setenv(
        "PROPERTYQUARRY_EXPECTED_TEABLE_BASE_ID_SHA256",
        EXPECTED_BASE_ID_SHA256,
    )
    monkeypatch.setattr(
        overlay,
        "PostgresPropertyEvidenceOverlayRepository",
        lambda _database_url: _FakeRepository(_valid_plan()),
    )

    def unexpected_fetch(**_kwargs: object) -> dict[str, object]:
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("authenticated fetch must not run for a mismatched origin")

    monkeypatch.setattr(overlay, "fetch_teable_export", unexpected_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "property_evidence_overlay_read_model.py",
            "--candidate-sha",
            CANDIDATE_SHA,
            "--stage-only",
            "--write",
            str(output),
        ],
    )

    assert overlay.main() == 1
    assert fetch_called is False
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "fail"


def test_runtime_repository_has_no_ddl_or_destructive_active_replace() -> None:
    source = Path(
        "ea/app/repositories/property_evidence_overlays_postgres.py"
    ).read_text(encoding="utf-8")
    normalized = source.upper()

    assert "CREATE TABLE" not in normalized
    assert "ALTER TABLE" not in normalized
    assert "CREATE INDEX" not in normalized
    assert "DELETE FROM PROPERTY_EVIDENCE_OVERLAY_ROLLUPS" not in normalized
    assert "INNER JOIN PROPERTY_EVIDENCE_OVERLAY_ACTIVE_SNAPSHOT" in normalized
