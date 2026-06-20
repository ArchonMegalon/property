#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
STORAGE_SOURCE = ROOT / "ea" / "app" / "product" / "property_search_storage.py"
SERVICE_SOURCE = ROOT / "ea" / "app" / "product" / "service.py"


def _check_source_contracts() -> None:
    storage = STORAGE_SOURCE.read_text(encoding="utf-8")
    service = SERVICE_SOURCE.read_text(encoding="utf-8")

    required_storage_fragments = (
        "PRIMARY KEY (principal_id, run_id)",
        "ALTER TABLE property_search_runs ADD PRIMARY KEY (principal_id, run_id)",
        "ON CONFLICT (principal_id, run_id) DO UPDATE",
        "WHERE run_id = %s AND principal_id = %s",
        "DELETE FROM property_search_runs WHERE run_id = %s AND principal_id = %s",
        "if not normalized_principal_id and not admin:\n        return ()",
    )
    for fragment in required_storage_fragments:
        if fragment not in storage:
            raise RuntimeError(f"missing_storage_contract:{fragment[:80]}")

    forbidden_storage_fragments = (
        "ON CONFLICT (run_id)",
        "SET principal_id = EXCLUDED.principal_id",
        "SELECT payload_json FROM property_search_runs WHERE run_id = %s\"",
        "DELETE FROM property_search_runs WHERE run_id = %s\"",
    )
    for fragment in forbidden_storage_fragments:
        if fragment in storage:
            raise RuntimeError(f"forbidden_storage_contract:{fragment}")

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

    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('property_search_runs', 'property_source_listing_cache')
                ORDER BY table_name
                """
            )
            tables = {row[0] for row in cur.fetchall()}
            missing_tables = {"property_search_runs", "property_source_listing_cache"} - tables
            if missing_tables:
                raise RuntimeError(f"missing_tables:{','.join(sorted(missing_tables))}")

            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'property_search_runs'
                """
            )
            run_indexes = {row[0] for row in cur.fetchall()}
            if "idx_property_search_runs_updated" not in run_indexes:
                raise RuntimeError("missing_index:idx_property_search_runs_updated")
            if "idx_property_search_runs_principal_updated" not in run_indexes:
                raise RuntimeError("missing_index:idx_property_search_runs_principal_updated")

            cur.execute(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN unnest(i.indkey) WITH ORDINALITY AS key_columns(attnum, ordinal) ON TRUE
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_columns.attnum
                WHERE n.nspname = 'public'
                  AND t.relname = 'property_search_runs'
                  AND i.indisprimary
                ORDER BY key_columns.ordinal
                """
            )
            run_primary_key = tuple(str(row[0]) for row in cur.fetchall())
            if run_primary_key != ("principal_id", "run_id"):
                raise RuntimeError(
                    "invalid_primary_key:property_search_runs:"
                    + ",".join(run_primary_key or ("missing",))
                )

            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'property_source_listing_cache'
                """
            )
            cache_indexes = {row[0] for row in cur.fetchall()}
            if "idx_property_source_listing_cache_stored_at" not in cache_indexes:
                raise RuntimeError("missing_index:idx_property_source_listing_cache_stored_at")

    print("property search storage schema looks ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
