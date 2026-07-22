from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Sequence


SCHEMA_COMPONENT = "ea_kernel"
SCHEMA_LEDGER_TABLE = "ea_kernel_schema_migrations"
SCHEMA_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"ea:kernel:migrations:v1").digest()[:8],
    byteorder="big",
    signed=True,
)
DEFAULT_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schema"


@dataclass(frozen=True)
class KernelMigrationSpec:
    version: int
    name: str
    filename: str


@dataclass(frozen=True)
class KernelMigration:
    version: int
    name: str
    filename: str
    sql: str

    @property
    def checksum(self) -> str:
        payload = (
            f"{SCHEMA_COMPONENT}\0{self.version}\0{self.name}\0{self.sql.strip()}\n"
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class KernelSchemaStatus:
    ready: bool
    reason: str
    current_version: int
    required_version: int
    applied_versions: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "component": SCHEMA_COMPONENT,
            "ready": self.ready,
            "reason": self.reason,
            "current_version": self.current_version,
            "required_version": self.required_version,
            "applied_versions": list(self.applied_versions),
        }


@dataclass(frozen=True)
class KernelMigrationResult:
    previous_version: int
    current_version: int
    applied_versions: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "component": SCHEMA_COMPONENT,
            "previous_version": self.previous_version,
            "current_version": self.current_version,
            "applied_versions": list(self.applied_versions),
        }


class KernelSchemaError(RuntimeError):
    """Base failure for the privileged EA kernel schema boundary."""


class KernelSchemaDriftError(KernelSchemaError):
    """The immutable migration ledger and checked-in schema no longer agree."""


class KernelSchemaNotReadyError(KernelSchemaError):
    """A runtime schema probe failed after the deploy migration completed."""


KERNEL_MIGRATION_SPECS: tuple[KernelMigrationSpec, ...] = (
    KernelMigrationSpec(
        2, "execution_ledger_kernel", "20260305_v0_2_execution_ledger_kernel.sql"
    ),
    KernelMigrationSpec(
        3, "channel_runtime_kernel", "20260305_v0_3_channel_runtime_kernel.sql"
    ),
    KernelMigrationSpec(
        4, "policy_decisions_kernel", "20260305_v0_4_policy_decisions_kernel.sql"
    ),
    KernelMigrationSpec(5, "artifacts_kernel", "20260305_v0_5_artifacts_kernel.sql"),
    KernelMigrationSpec(
        6, "execution_ledger_v2", "20260305_v0_6_execution_ledger_v2.sql"
    ),
    KernelMigrationSpec(7, "approvals_kernel", "20260305_v0_7_approvals_kernel.sql"),
    KernelMigrationSpec(
        8,
        "channel_runtime_reliability",
        "20260305_v0_8_channel_runtime_reliability.sql",
    ),
    KernelMigrationSpec(
        9, "tool_connector_kernel", "20260305_v0_9_tool_connector_kernel.sql"
    ),
    KernelMigrationSpec(
        10, "task_contracts_kernel", "20260305_v0_10_task_contracts_kernel.sql"
    ),
    KernelMigrationSpec(11, "memory_kernel", "20260305_v0_11_memory_kernel.sql"),
    KernelMigrationSpec(
        12,
        "entities_relationships_kernel",
        "20260305_v0_12_entities_relationships_kernel.sql",
    ),
    KernelMigrationSpec(
        13, "commitments_kernel", "20260305_v0_13_commitments_kernel.sql"
    ),
    KernelMigrationSpec(
        14, "authority_bindings_kernel", "20260305_v0_14_authority_bindings_kernel.sql"
    ),
    KernelMigrationSpec(
        15,
        "delivery_preferences_kernel",
        "20260305_v0_15_delivery_preferences_kernel.sql",
    ),
    KernelMigrationSpec(
        16, "follow_ups_kernel", "20260305_v0_16_follow_ups_kernel.sql"
    ),
    KernelMigrationSpec(
        17, "deadline_windows_kernel", "20260305_v0_17_deadline_windows_kernel.sql"
    ),
    KernelMigrationSpec(
        18, "stakeholders_kernel", "20260305_v0_18_stakeholders_kernel.sql"
    ),
    KernelMigrationSpec(
        19, "decision_windows_kernel", "20260305_v0_19_decision_windows_kernel.sql"
    ),
    KernelMigrationSpec(
        20,
        "communication_policies_kernel",
        "20260305_v0_20_communication_policies_kernel.sql",
    ),
    KernelMigrationSpec(
        21, "follow_up_rules_kernel", "20260305_v0_21_follow_up_rules_kernel.sql"
    ),
    KernelMigrationSpec(
        22,
        "interruption_budgets_kernel",
        "20260305_v0_22_interruption_budgets_kernel.sql",
    ),
    KernelMigrationSpec(
        23, "execution_queue_kernel", "20260305_v0_23_execution_queue_kernel.sql"
    ),
    KernelMigrationSpec(
        24, "human_tasks_kernel", "20260305_v0_24_human_tasks_kernel.sql"
    ),
    KernelMigrationSpec(
        25, "human_task_resume_kernel", "20260305_v0_25_human_task_resume_kernel.sql"
    ),
    KernelMigrationSpec(
        26,
        "human_task_assignment_state",
        "20260305_v0_26_human_task_assignment_state.sql",
    ),
    KernelMigrationSpec(
        27,
        "human_task_review_contract",
        "20260305_v0_27_human_task_review_contract.sql",
    ),
    KernelMigrationSpec(
        28, "operator_profiles_kernel", "20260305_v0_28_operator_profiles_kernel.sql"
    ),
    KernelMigrationSpec(
        29,
        "human_task_assignment_source",
        "20260305_v0_29_human_task_assignment_source.sql",
    ),
    KernelMigrationSpec(
        30,
        "human_task_assignment_provenance",
        "20260305_v0_30_human_task_assignment_provenance.sql",
    ),
    KernelMigrationSpec(
        31, "artifact_principal_scope", "20260305_v0_31_artifact_principal_scope.sql"
    ),
    KernelMigrationSpec(
        32, "provider_bindings_kernel", "20260305_v0_32_provider_bindings_kernel.sql"
    ),
    KernelMigrationSpec(
        33,
        "task_contract_runtime_policy",
        "20260305_v0_33_task_contract_runtime_policy.sql",
    ),
    KernelMigrationSpec(
        34,
        "assistant_onboarding_canonical_schema",
        "20260305_v0_34_assistant_onboarding_canonical_schema.sql",
    ),
    KernelMigrationSpec(
        35,
        "execution_ledger_legacy_compat",
        "20260305_v0_35_execution_ledger_legacy_compat.sql",
    ),
    KernelMigrationSpec(
        36,
        "propertyquarry_property_passport",
        "20260305_v0_36_propertyquarry_property_passport.sql",
    ),
    KernelMigrationSpec(
        37,
        "runtime_repository_contract",
        "20260305_v0_37_runtime_repository_contract.sql",
    ),
    KernelMigrationSpec(
        38,
        "operator_profile_principal_scope",
        "20260305_v0_38_operator_profile_principal_scope.sql",
    ),
)
LATEST_KERNEL_SCHEMA_VERSION = KERNEL_MIGRATION_SPECS[-1].version


_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_LEDGER_TABLE} (
    component TEXT NOT NULL,
    version INTEGER NOT NULL,
    migration_name TEXT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (component, version),
    CHECK (version > 0),
    CHECK (checksum_sha256 ~ '^[0-9a-f]{{64}}$')
)
"""
_CREATE_TABLE_PATTERN = re.compile(
    r"\bCREATE\s+TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)?)",
    re.IGNORECASE,
)
_VERSION_IN_FILENAME_PATTERN = re.compile(r"_v0_(?P<version>[0-9]+)_")


def _validate_manifest_specs() -> None:
    versions = tuple(spec.version for spec in KERNEL_MIGRATION_SPECS)
    expected = tuple(range(2, LATEST_KERNEL_SCHEMA_VERSION + 1))
    if versions != expected:
        raise KernelSchemaError("kernel_migration_manifest_version_gap")
    filenames = tuple(spec.filename for spec in KERNEL_MIGRATION_SPECS)
    if len(set(filenames)) != len(filenames):
        raise KernelSchemaError("kernel_migration_manifest_duplicate_file")
    for spec in KERNEL_MIGRATION_SPECS:
        matched = _VERSION_IN_FILENAME_PATTERN.search(spec.filename)
        if matched is None or int(matched.group("version")) != spec.version:
            raise KernelSchemaError(
                f"kernel_migration_manifest_filename_version_mismatch:{spec.version}"
            )


def load_kernel_migrations(
    schema_root: Path | str = DEFAULT_SCHEMA_ROOT,
) -> tuple[KernelMigration, ...]:
    _validate_manifest_specs()
    root = Path(schema_root)
    if not root.is_dir():
        raise KernelSchemaError("kernel_schema_root_missing")
    expected_files = {spec.filename for spec in KERNEL_MIGRATION_SPECS}
    actual_files = {
        path.name
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() == ".sql"
    }
    missing = sorted(expected_files - actual_files)
    if missing:
        raise KernelSchemaError(f"kernel_migration_file_missing:{missing[0]}")
    untracked = sorted(actual_files - expected_files)
    if untracked:
        raise KernelSchemaError(f"kernel_migration_manifest_untracked:{untracked[0]}")
    return tuple(
        KernelMigration(
            version=spec.version,
            name=spec.name,
            filename=spec.filename,
            sql=(root / spec.filename).read_text(encoding="utf-8"),
        )
        for spec in KERNEL_MIGRATION_SPECS
    )


def required_kernel_relations(
    migrations: Sequence[KernelMigration],
) -> tuple[str, ...]:
    relations: set[str] = set()
    for migration in migrations:
        sql = re.sub(r"--[^\n]*", "", migration.sql)
        relations.update(
            match.group("name") for match in _CREATE_TABLE_PATTERN.finditer(sql)
        )
    relations.add(SCHEMA_LEDGER_TABLE)
    return tuple(sorted(relations))


def _migration_by_version(
    migrations: Sequence[KernelMigration],
) -> dict[int, KernelMigration]:
    return {migration.version: migration for migration in migrations}


def _validate_applied_rows(
    rows: Sequence[Sequence[object]],
    migrations: Sequence[KernelMigration],
) -> tuple[int, ...]:
    expected = _migration_by_version(migrations)
    observed: dict[int, tuple[str, str]] = {}
    for row in rows:
        version = int(row[0])
        name = str(row[1] or "")
        checksum = str(row[2] or "").strip().lower()
        if version in observed:
            raise KernelSchemaDriftError(
                f"duplicate_kernel_migration_version:{version}"
            )
        observed[version] = (name, checksum)
    for version, (name, checksum) in sorted(observed.items()):
        migration = expected.get(version)
        if migration is None:
            raise KernelSchemaDriftError(f"kernel_schema_ahead:{version}")
        if name != migration.name or checksum != migration.checksum:
            raise KernelSchemaDriftError(f"kernel_migration_checksum_drift:{version}")
    versions = tuple(sorted(observed))
    if versions and versions != tuple(range(2, versions[-1] + 1)):
        raise KernelSchemaDriftError("kernel_migration_gap")
    return versions


def _connect(database_url: str, *, autocommit: bool):  # type: ignore[no-untyped-def]
    import psycopg

    return psycopg.connect(
        database_url,
        autocommit=autocommit,
        connect_timeout=5,
    )


def migrate_kernel_schema(
    database_url: str,
    *,
    applied_by: str = "deploy",
    connect: Callable[..., object] | None = None,
    schema_root: Path | str = DEFAULT_SCHEMA_ROOT,
) -> KernelMigrationResult:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        raise KernelSchemaError("database_url_required")
    migrations = load_kernel_migrations(schema_root)
    connector = connect or _connect
    conn = connector(normalized_url, autocommit=False)
    try:
        with conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
            cur.execute(_LEDGER_DDL)
            cur.execute(
                f"""
                SELECT version, migration_name, checksum_sha256
                FROM {SCHEMA_LEDGER_TABLE}
                WHERE component = %s
                ORDER BY version
                """,
                (SCHEMA_COMPONENT,),
            )
            before = _validate_applied_rows(cur.fetchall(), migrations)
            before_set = set(before)
            applied: list[int] = []
            for migration in migrations:
                if migration.version in before_set:
                    continue
                cur.execute(migration.sql)
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA_LEDGER_TABLE}
                        (component, version, migration_name, checksum_sha256, applied_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        SCHEMA_COMPONENT,
                        migration.version,
                        migration.name,
                        migration.checksum,
                        str(applied_by or "deploy").strip()[:120] or "deploy",
                    ),
                )
                applied.append(migration.version)
        conn.commit()  # type: ignore[attr-defined]
    except Exception:
        conn.rollback()  # type: ignore[attr-defined]
        raise
    finally:
        conn.close()  # type: ignore[attr-defined]
    return KernelMigrationResult(
        previous_version=before[-1] if before else 0,
        current_version=LATEST_KERNEL_SCHEMA_VERSION,
        applied_versions=tuple(applied),
    )


def inspect_kernel_schema_cursor(
    cur,  # type: ignore[no-untyped-def]
    migrations: Sequence[KernelMigration],
) -> KernelSchemaStatus:
    cur.execute("SELECT to_regclass(%s)", (SCHEMA_LEDGER_TABLE,))
    ledger_row = cur.fetchone()
    if not ledger_row or ledger_row[0] is None:
        return KernelSchemaStatus(
            False,
            "migration_ledger_missing",
            0,
            LATEST_KERNEL_SCHEMA_VERSION,
            (),
        )
    cur.execute(
        f"""
        SELECT version, migration_name, checksum_sha256
        FROM {SCHEMA_LEDGER_TABLE}
        WHERE component = %s
        ORDER BY version
        """,
        (SCHEMA_COMPONENT,),
    )
    try:
        versions = _validate_applied_rows(cur.fetchall(), migrations)
    except KernelSchemaDriftError as exc:
        return KernelSchemaStatus(
            False,
            str(exc),
            0,
            LATEST_KERNEL_SCHEMA_VERSION,
            (),
        )
    current = versions[-1] if versions else 0
    if current != LATEST_KERNEL_SCHEMA_VERSION:
        return KernelSchemaStatus(
            False,
            "migration_pending",
            current,
            LATEST_KERNEL_SCHEMA_VERSION,
            versions,
        )
    for relation in required_kernel_relations(migrations):
        cur.execute("SELECT to_regclass(%s)", (relation,))
        relation_row = cur.fetchone()
        if not relation_row or relation_row[0] is None:
            return KernelSchemaStatus(
                False,
                f"required_relation_missing:{relation}",
                current,
                LATEST_KERNEL_SCHEMA_VERSION,
                versions,
            )
    return KernelSchemaStatus(
        True,
        "schema_ready",
        current,
        LATEST_KERNEL_SCHEMA_VERSION,
        versions,
    )


def inspect_kernel_schema(
    database_url: str,
    *,
    connect: Callable[..., object] | None = None,
    schema_root: Path | str = DEFAULT_SCHEMA_ROOT,
) -> KernelSchemaStatus:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        return KernelSchemaStatus(
            False,
            "database_url_missing",
            0,
            LATEST_KERNEL_SCHEMA_VERSION,
            (),
        )
    try:
        migrations = load_kernel_migrations(schema_root)
    except KernelSchemaError as exc:
        return KernelSchemaStatus(
            False,
            str(exc),
            0,
            LATEST_KERNEL_SCHEMA_VERSION,
            (),
        )
    connector = connect or _connect
    try:
        conn = connector(normalized_url, autocommit=True)
        try:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                return inspect_kernel_schema_cursor(cur, migrations)
        finally:
            conn.close()  # type: ignore[attr-defined]
    except Exception as exc:
        return KernelSchemaStatus(
            False,
            f"schema_probe_failed:{exc.__class__.__name__}",
            0,
            LATEST_KERNEL_SCHEMA_VERSION,
            (),
        )


def require_kernel_schema_ready(
    database_url: str,
    *,
    connect: Callable[..., object] | None = None,
    schema_root: Path | str = DEFAULT_SCHEMA_ROOT,
) -> None:
    status = inspect_kernel_schema(
        database_url,
        connect=connect,
        schema_root=schema_root,
    )
    if not status.ready:
        raise KernelSchemaNotReadyError(f"kernel_schema_not_ready:{status.reason}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Governed EA kernel schema migration boundary."
    )
    parser.add_argument("operation", choices=("migrate", "check"))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--applied-by", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    database_url = str(
        args.database_url or os.environ.get("DATABASE_URL") or ""
    ).strip()
    if not database_url:
        print(json.dumps({"status": "failed", "reason": "database_url_missing"}))
        return 2
    if args.operation == "migrate":
        try:
            result = migrate_kernel_schema(
                database_url,
                applied_by=(
                    str(args.applied_by or "").strip()
                    or str(
                        os.environ.get("PROPERTYQUARRY_RELEASE_COMMIT_SHA") or ""
                    ).strip()
                    or str(os.environ.get("EA_ROLE") or "deploy").strip()
                    or "deploy"
                ),
            )
            require_kernel_schema_ready(database_url)
        except KernelSchemaError as exc:
            print(json.dumps({"status": "failed", "reason": str(exc)}))
            return 2
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "reason": f"migration_failed:{exc.__class__.__name__}",
                    }
                )
            )
            return 2
        print(json.dumps({"status": "migrated", **result.as_dict()}, sort_keys=True))
        return 0
    status = inspect_kernel_schema(database_url)
    print(
        json.dumps(
            {"status": "ready" if status.ready else "not_ready", **status.as_dict()},
            sort_keys=True,
        )
    )
    return 0 if status.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
