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
        temporalities = set(layer["allowed_source_temporalities"])
        if "current_feed" in temporalities:
            fields["source_temporality"] = "current_feed"
            fields["source_checked_at"] = generated_at
        elif "live" in temporalities:
            fields["source_temporality"] = "live"
        else:
            fields["source_temporality"] = "reference"
            fields["reference_period"] = "2025"
        if layer_key == "media_attention":
            fields["article_url"] = "https://news.example.com/article"
            fields["media_source_class"] = "independent_press"
            fields["independent_press"] = True
        if layer_key == "official_safety_context":
            fields["geographic_scope"] = "district_aggregate"
            fields["rights_caveat"] = "Reuse subject to the official source terms."
            fields["property_scoring"] = False
            fields["person_scoring"] = False
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


def _layer_fields(
    export: dict[str, object],
    registry: dict[str, object],
    layer_key: str,
) -> dict[str, object]:
    layer = next(
        row
        for row in overlay._registry_layers(registry)
        if row["layer_key"] == layer_key
    )
    tables = export["tables"]
    assert isinstance(tables, dict)
    rows = tables[str(layer["teable_table"])]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    fields = rows[0]["fields"]
    assert isinstance(fields, dict)
    return fields


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


def test_registry_and_receipt_versions_expose_temporal_contract_break() -> None:
    registry = _registry()

    assert registry["contract_name"] == "propertyquarry.evidence_overlay_registry.v2"
    assert overlay.RECEIPT_SCHEMA == "propertyquarry.evidence_overlay_read_model_receipt.v3"
    assert registry["gold_policy"]["launch_receipt_schema"] == overlay.RECEIPT_SCHEMA


def test_reference_dataset_uses_period_not_universal_source_age() -> None:
    registry = _registry()
    export = _valid_export(registry)
    fields = _layer_fields(export, registry, "summer_heat")
    fields["source_updated_at"] = "2020-06-15T00:00:00+00:00"
    fields["reference_period"] = "2019-06/2020-08"

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "pass", plan["failures"]
    evidence = plan["source_temporal_evidence_by_layer"]["summer_heat"]
    assert evidence["source_max_age_hours_by_temporality"] == {}
    assert evidence["reference_periods"] == ["2019-06/2020-08"]


@pytest.mark.parametrize(
    "reference_period",
    ["", "2026-02-31", "2026-12/2026-01", "calendar-year-2025"],
)
def test_reference_period_requires_real_ordered_calendar_values(
    reference_period: str,
) -> None:
    registry = _registry()
    export = _valid_export(registry)
    _layer_fields(export, registry, "traffic_noise")[
        "reference_period"
    ] = reference_period

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    assert any("reference_period" in failure for failure in plan["failures"])


def test_live_source_sla_fails_even_when_cache_is_recent() -> None:
    registry = _registry()
    export = _valid_export(registry)
    fields = _layer_fields(export, registry, "environmental_quality")
    fields["source_updated_at"] = "2026-07-14T00:00:00+00:00"

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    assert any("source_updated_at" in failure and "source-check SLA" in failure for failure in plan["failures"])


@pytest.mark.parametrize(
    ("layer_key", "timestamp_field"),
    [
        ("summer_heat", "cache_updated_at"),
        ("environmental_quality", "source_updated_at"),
        ("media_attention", "source_checked_at"),
    ],
)
def test_temporal_provenance_rejects_timezone_naive_timestamps(
    layer_key: str,
    timestamp_field: str,
) -> None:
    registry = _registry()
    export = _valid_export(registry)
    _layer_fields(export, registry, layer_key)[timestamp_field] = "2026-07-16T11:00:00"

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    assert any(timestamp_field in failure for failure in plan["failures"])


def test_current_feed_sla_checks_poll_time_not_article_publication_time() -> None:
    registry = _registry()
    export = _valid_export(registry)
    fields = _layer_fields(export, registry, "media_attention")
    fields["source_updated_at"] = "2026-04-17T12:00:00+00:00"

    current = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )
    assert current["status"] == "pass", current["failures"]

    fields["source_checked_at"] = "2026-07-13T12:00:00+00:00"
    stale_check = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )
    assert stale_check["status"] == "fail"
    assert any("source_checked_at" in failure and "source-check SLA" in failure for failure in stale_check["failures"])


def test_scoring_flags_are_rejected_globally_and_layer_claim_fields_are_scoped() -> None:
    registry = _registry()
    export = _valid_export(registry)
    fields = _layer_fields(export, registry, "summer_heat")
    fields["property_scoring"] = True

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    failures = "\n".join(plan["failures"])
    assert "property_scoring must never be enabled" in failures
    assert "only valid as an explicit safety-layer denial" in failures


@pytest.mark.parametrize(
    "claim_field",
    ["summary", "uncertainty_label", "value_label"],
)
def test_municipal_rss_cannot_claim_independent_press(claim_field: str) -> None:
    registry = _registry()
    export = _valid_export(registry)
    fields = _layer_fields(export, registry, "media_attention")
    fields["media_source_class"] = "municipal_rss"
    fields["independent_press"] = True
    fields[claim_field] = "Independent reporting from the municipal feed"

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    failures = "\n".join(plan["failures"])
    assert "municipal RSS cannot be classified as independent press" in failures
    assert "municipal RSS copy cannot claim independent reporting" in failures


def test_ingestion_plan_rejects_missing_ui_state() -> None:
    registry = _registry()
    export = _valid_export(registry)
    _layer_fields(export, registry, "summer_heat").pop("ui_state")

    plan = overlay.build_ingestion_plan(
        export=export,
        registry=registry,
        candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        now=NOW,
    )

    assert plan["status"] == "fail"
    assert any(
        "ui_state is required and must be stale or verified" in failure
        for failure in plan["failures"]
    )


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
    receipt["temporal_evidence"]["cache_max_age_policy_hours"] = math.nan
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

    assert "evidence overlay receipt cache-age policy is invalid" in failures
    assert (
        "evidence overlay receipt query budget exceeds the launch maximum" in failures
    )
    assert "evidence overlay receipt exceeds its query performance budget" in failures


def test_receipt_never_equates_cache_recency_with_source_freshness() -> None:
    receipt, _repository = _staged_receipt()

    assert "freshness" not in receipt
    assert (
        receipt["temporal_evidence"][
            "cache_updated_at_proves_source_freshness"
        ]
        is False
    )
    assert set(receipt["temporal_evidence"]["source_by_layer"]) == overlay.REQUIRED_LAYER_KEYS

    receipt["temporal_evidence"][
        "cache_updated_at_proves_source_freshness"
    ] = True
    failures = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )
    assert (
        "evidence overlay receipt must not represent cache recency as source freshness"
        in failures
    )


def test_receipt_record_count_must_equal_all_table_rows() -> None:
    receipt, _repository = _staged_receipt()
    receipt["ingestion"]["record_count"] += 1

    failures = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )

    assert (
        "evidence overlay receipt record count must equal the sum of Teable table counts"
        in failures
    )


def test_receipt_temporal_counts_must_cover_table_and_postgres_rows() -> None:
    receipt, _repository = _staged_receipt()
    registry = _registry()
    layer = next(
        row for row in registry["layers"] if row["layer_key"] == "summer_heat"
    )
    table_name = str(layer["teable_table"])
    receipt["ingestion"]["table_counts"][table_name] = 2
    receipt["ingestion"]["record_count"] += 1
    receipt["source_evidence"]["tables"][table_name]["record_count"] = 2
    coverage = next(
        row
        for row in receipt["read_model"]["coverage"]
        if row["layer_key"] == "summer_heat"
    )
    coverage["record_count"] = 2

    failures = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )

    assert (
        "evidence overlay layer summer_heat source temporality counts are invalid"
        in failures
    )
    assert (
        "evidence overlay layer summer_heat table, Postgres, and temporal row counts do not match"
        in failures
    )


@pytest.mark.parametrize(
    ("layer_key", "count_field", "expected_failure"),
    [
        (
            "summer_heat",
            "source_updated_at_row_counts_by_temporality",
            "source timestamp row coverage is incomplete",
        ),
        (
            "environmental_quality",
            "source_sla_at_row_counts_by_temporality",
            "source SLA row coverage is incomplete",
        ),
        (
            "summer_heat",
            "reference_period_row_counts",
            "lacks valid reference-period evidence",
        ),
    ],
)
def test_receipt_rejects_incomplete_per_row_temporal_evidence(
    layer_key: str,
    count_field: str,
    expected_failure: str,
) -> None:
    receipt, _repository = _staged_receipt()
    source = receipt["temporal_evidence"]["source_by_layer"][layer_key]
    source[count_field] = {}

    failures = overlay.verify_receipt(
        receipt,
        expected_candidate_sha=CANDIDATE_SHA,
        max_age_hours=48.0,
        expected_teable_origin=EXPECTED_ORIGIN,
        expected_teable_base_id_sha256=EXPECTED_BASE_ID_SHA256,
        expected_phase="staged",
        now=NOW,
    )

    assert any(expected_failure in failure for failure in failures)


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
