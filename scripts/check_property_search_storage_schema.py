#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

STORAGE_SOURCE = ROOT / "ea" / "app" / "product" / "property_search_storage.py"
QUEUE_SOURCE = ROOT / "ea" / "app" / "product" / "property_search_work_queue.py"
SCHEMA_SOURCE = ROOT / "ea" / "app" / "product" / "property_search_schema.py"
DELIVERY_OUTBOX_SOURCE = ROOT / "ea" / "app" / "repositories" / "delivery_outbox_postgres.py"
CONTENT_LEDGER_SOURCE = ROOT / "ea" / "app" / "services" / "property_content_job_ledger.py"
SERVICE_SOURCE = ROOT / "ea" / "app" / "product" / "service.py"


def _check_source_contracts() -> None:
    storage = STORAGE_SOURCE.read_text(encoding="utf-8")
    queue = QUEUE_SOURCE.read_text(encoding="utf-8")
    schema = SCHEMA_SOURCE.read_text(encoding="utf-8")
    delivery_outbox = DELIVERY_OUTBOX_SOURCE.read_text(encoding="utf-8")
    content_ledger = CONTENT_LEDGER_SOURCE.read_text(encoding="utf-8")
    service = SERVICE_SOURCE.read_text(encoding="utf-8")

    required_storage_fragments = (
        "ON CONFLICT (principal_id, run_id) DO UPDATE",
        "WHERE run_id = %s AND principal_id = %s",
        "DELETE FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
        "payload_retention_status",
        "compact_only",
        "UPDATE property_search_runs AS runs",
        "COALESCE(NULLIF(compact_json, '{{}}'::jsonb)",
        "if not normalized_principal_id and not admin:\n        return ()",
        "def _require_property_search_run_schema()",
        "require_property_search_schema_ready(database_url)",
    )
    for fragment in required_storage_fragments:
        if fragment not in storage:
            raise RuntimeError(f"missing_storage_contract:{fragment[:80]}")

    forbidden_storage_fragments = (
        "ON CONFLICT (run_id)",
        "SET principal_id = EXCLUDED.principal_id",
        "SELECT payload_json FROM property_search_runs WHERE run_id = %s\"",
        "DELETE FROM property_search_runs WHERE run_id = %s\"",
        "(payload_json->>'status') = ANY(%s)",
    )
    for fragment in forbidden_storage_fragments:
        if fragment in storage:
            raise RuntimeError(f"forbidden_storage_contract:{fragment}")

    for forbidden_ddl in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX"):
        if (
            forbidden_ddl in storage.upper()
            or forbidden_ddl in queue.upper()
            or forbidden_ddl in delivery_outbox.upper()
            or forbidden_ddl in content_ledger.upper()
        ):
            raise RuntimeError(f"runtime_schema_ddl_forbidden:{forbidden_ddl}")

    required_queue_fragments = (
        "class PostgresPropertySearchWorkQueue",
        "require_property_search_schema_ready(self._database_url)",
        "FOR UPDATE SKIP LOCKED",
        "property_search_work_jobs",
    )
    for fragment in required_queue_fragments:
        if fragment not in queue:
            raise RuntimeError(f"missing_queue_contract:{fragment[:80]}")

    required_schema_fragments = (
        "SCHEMA_LEDGER_TABLE = \"propertyquarry_schema_migrations\"",
        "pg_advisory_xact_lock",
        "checksum_sha256",
        "PropertySearchMigration(1, \"property_search_runs_tenant_schema\"",
        "PropertySearchMigration(2, \"property_search_durable_work_queue\"",
        "PropertySearchMigration(3, \"property_source_listing_cache\"",
        "PropertySearchMigration(4, \"replica_safe_delivery_outbox\"",
        "PropertySearchMigration(5, \"durable_property_content_job_ledger\"",
        "property_search_migration_checksum_drift",
        "required_relation_missing",
    )
    for fragment in required_schema_fragments:
        if fragment not in schema:
            raise RuntimeError(f"missing_migration_contract:{fragment[:80]}")

    for fragment in (
        "pg_try_advisory_xact_lock",
        "FOR UPDATE SKIP LOCKED",
        "status = 'dispatching'",
        "delivery_outcome_unknown_after_lease_expiry",
        "require_property_search_schema_ready(self._database_url)",
    ):
        if fragment not in delivery_outbox:
            raise RuntimeError(f"missing_delivery_outbox_contract:{fragment[:80]}")

    for fragment in (
        "class _PostgresPropertyContentRepository",
        "require_property_search_schema_ready(self.database_url)",
        "pg_try_advisory_xact_lock",
        "FOR UPDATE SKIP LOCKED",
        "property_content_webhook_events",
        "PropertyContentLedgerCorruptionError",
        "fcntl.flock",
    ):
        if fragment not in content_ledger:
            raise RuntimeError(f"missing_content_ledger_contract:{fragment[:80]}")

    required_service_fragments = (
        "def list_property_search_runs(",
        "if not normalized_principal:\n            return []",
        "str(record.get(\"principal_id\") or \"\").strip() != normalized_principal",
        "def clear_property_search_runs(",
    )
    for fragment in required_service_fragments:
        if fragment not in service:
            raise RuntimeError(f"missing_service_contract:{fragment[:80]}")


def main() -> int:
    _check_source_contracts()
    database_url = str(os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("property search storage source contracts look ready; DATABASE_URL is not set, skipping live schema check.")
        return 0

    from app.product.property_search_schema import inspect_property_search_schema

    status = inspect_property_search_schema(database_url)
    if not status.ready:
        raise RuntimeError(f"property_search_schema_not_ready:{status.reason}")

    print(
        "property search storage schema looks ready "
        f"at version {status.current_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
