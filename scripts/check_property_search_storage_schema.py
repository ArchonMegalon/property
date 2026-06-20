#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def main() -> int:
    database_url = str(os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("DATABASE_URL is not set; skipping property search storage schema check.")
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
