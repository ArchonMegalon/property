from __future__ import annotations

import copy
import json
from datetime import datetime


PROPERTY_EVIDENCE_OVERLAY_SCHEMA_VERSION = 2
_ACTIVATION_LOCK_KEY = "property_evidence_overlay_snapshot_activation"


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "").strip()


class PostgresPropertyEvidenceOverlayRepository:
    """Persistent, Teable-fed read model used by customer search/research pages.

    This repository never calls a source provider. Async ingestion writes an
    isolated candidate snapshot; request-time lookups stay pinned to the active
    pointer until a validated candidate is atomically activated.
    """

    def __init__(self, database_url: str, *, ensure_schema: bool = False) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError(
                "database_url is required for PostgresPropertyEvidenceOverlayRepository"
            )
        if ensure_schema:
            self.ensure_schema()

    def _connect(self, *, autocommit: bool = True):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised by runtime image contracts
            raise RuntimeError(
                "psycopg is required for the property evidence overlay read model"
            ) from exc
        return psycopg.connect(
            self._database_url, autocommit=autocommit, connect_timeout=5
        )

    @staticmethod
    def _json_value(value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(copy.deepcopy(value))

    def ensure_schema(self) -> None:
        from app.product.property_search_schema import (
            require_property_search_schema_ready,
        )

        require_property_search_schema_ready(self._database_url)

    def active_snapshot_id(self) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT snapshot_id
                    FROM property_evidence_overlay_active_snapshot
                    WHERE pointer_key = 'active'
                    """
                )
                row = cur.fetchone()
        return str(row[0] or "").strip() if row else ""

    def stage_snapshot(
        self,
        *,
        snapshot_id: str,
        source_schema: str,
        source_generated_at: str,
        ingested_at: str,
        candidate_sha: str,
        payload_sha256: str,
        records: list[dict[str, object]],
        table_counts: dict[str, int],
    ) -> None:
        layer_keys = {
            str(row.get("layer_key") or "").strip()
            for row in records
            if str(row.get("layer_key") or "").strip()
        }
        normalized_table_counts = {
            str(key or "").strip(): int(value)
            for key, value in dict(table_counts or {}).items()
            if str(key or "").strip()
        }
        if len(layer_keys) != 8 or len(normalized_table_counts) != 8:
            raise ValueError(
                "property evidence overlay snapshot requires exactly eight layers and tables"
            )
        if any(value < 1 for value in normalized_table_counts.values()):
            raise ValueError(
                "property evidence overlay snapshot requires a positive count for every table"
            )
        expanded_records: list[tuple[object, ...]] = []
        for row in records:
            match = dict(row.get("match") or {})
            if not match:
                raise ValueError("property evidence overlay record has no match keys")
            payload = dict(row.get("payload") or {})
            for match_key, match_value in sorted(match.items()):
                normalized_key = str(match_key or "").strip()
                normalized_value = str(match_value or "").strip()
                if not normalized_key or not normalized_value:
                    raise ValueError(
                        "property evidence overlay record has an empty match key or value"
                    )
                expanded_records.append(
                    (
                        snapshot_id,
                        str(row.get("layer_key") or ""),
                        str(row.get("record_key") or ""),
                        normalized_key,
                        normalized_value,
                        str(row.get("teable_table") or ""),
                        str(row.get("teable_record_id") or ""),
                        str(row.get("source_updated_at") or ""),
                        str(row.get("cache_updated_at") or ""),
                        ingested_at,
                        str(row.get("payload_sha256") or ""),
                        payload,
                    )
                )
        with self._connect(autocommit=False) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (_ACTIVATION_LOCK_KEY,),
                    )
                    cur.execute(
                        """
                        INSERT INTO property_evidence_overlay_snapshots (
                            snapshot_id, source_schema, source_generated_at, ingested_at,
                            candidate_sha, payload_sha256, table_counts_json, schema_version, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'staged')
                        """,
                        (
                            snapshot_id,
                            source_schema,
                            source_generated_at,
                            ingested_at,
                            candidate_sha,
                            payload_sha256,
                            self._json_value(normalized_table_counts),
                            PROPERTY_EVIDENCE_OVERLAY_SCHEMA_VERSION,
                        ),
                    )
                    for record in expanded_records:
                        cur.execute(
                            """
                            INSERT INTO property_evidence_overlay_rollups (
                                snapshot_id, layer_key, record_key, match_key, match_value,
                                teable_table, teable_record_id, source_updated_at,
                                cache_updated_at, ingested_at, payload_sha256, payload_json
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (*record[:-1], self._json_value(record[-1])),
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def discard_staged_snapshot(self, snapshot_id: str) -> None:
        with self._connect(autocommit=False) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (_ACTIVATION_LOCK_KEY,),
                    )
                    cur.execute(
                        """
                        DELETE FROM property_evidence_overlay_snapshots
                        WHERE snapshot_id = %s AND status = 'staged'
                        """,
                        (snapshot_id,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def activate_snapshot(
        self,
        *,
        snapshot_id: str,
        activated_at: str,
        expected_previous_snapshot_id: str,
    ) -> str:
        with self._connect(autocommit=False) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (_ACTIVATION_LOCK_KEY,),
                    )
                    cur.execute(
                        """
                        SELECT status, table_counts_json
                        FROM property_evidence_overlay_snapshots
                        WHERE snapshot_id = %s
                        FOR UPDATE
                        """,
                        (snapshot_id,),
                    )
                    snapshot_row = cur.fetchone()
                    if not snapshot_row or str(snapshot_row[0] or "") != "staged":
                        raise ValueError(
                            "property evidence overlay candidate is not staged"
                        )
                    expected_value = snapshot_row[1]
                    if isinstance(expected_value, str):
                        expected_value = json.loads(expected_value)
                    expected_counts = {
                        str(key): int(value)
                        for key, value in dict(expected_value or {}).items()
                    }
                    cur.execute(
                        """
                        SELECT layer_key, teable_table, COUNT(DISTINCT record_key)
                        FROM property_evidence_overlay_rollups
                        WHERE snapshot_id = %s
                        GROUP BY layer_key, teable_table
                        ORDER BY layer_key, teable_table
                        """,
                        (snapshot_id,),
                    )
                    staged_rows = list(cur.fetchall() or [])
                    staged_layers = {str(row[0] or "") for row in staged_rows}
                    observed_counts = {
                        str(row[1] or ""): int(row[2] or 0) for row in staged_rows
                    }
                    if (
                        len(staged_layers) != 8
                        or len(staged_rows) != 8
                        or len(expected_counts) != 8
                        or observed_counts != expected_counts
                        or any(value < 1 for value in expected_counts.values())
                    ):
                        raise ValueError(
                            "property evidence overlay staged snapshot is incomplete"
                        )
                    cur.execute(
                        """
                        SELECT snapshot_id
                        FROM property_evidence_overlay_active_snapshot
                        WHERE pointer_key = 'active'
                        FOR UPDATE
                        """
                    )
                    active_row = cur.fetchone()
                    previous_snapshot_id = (
                        str(active_row[0] or "") if active_row else ""
                    )
                    if previous_snapshot_id != expected_previous_snapshot_id:
                        raise ValueError(
                            "property evidence overlay active snapshot changed before activation"
                        )
                    cur.execute(
                        """
                        UPDATE property_evidence_overlay_snapshots
                        SET status = 'retired'
                        WHERE status = 'active' AND snapshot_id <> %s
                        """,
                        (snapshot_id,),
                    )
                    cur.execute(
                        """
                        UPDATE property_evidence_overlay_snapshots
                        SET status = 'active', activated_at = %s
                        WHERE snapshot_id = %s AND status = 'staged'
                        """,
                        (activated_at, snapshot_id),
                    )
                    if cur.rowcount != 1:
                        raise ValueError(
                            "property evidence overlay candidate activation lost its lease"
                        )
                    cur.execute(
                        """
                        INSERT INTO property_evidence_overlay_active_snapshot (
                            pointer_key, snapshot_id, activated_at
                        ) VALUES ('active', %s, %s)
                        ON CONFLICT (pointer_key) DO UPDATE
                        SET snapshot_id = EXCLUDED.snapshot_id,
                            activated_at = EXCLUDED.activated_at
                        """,
                        (snapshot_id, activated_at),
                    )
                conn.commit()
                return previous_snapshot_id
            except Exception:
                conn.rollback()
                raise

    def restore_active_snapshot(
        self,
        *,
        failed_snapshot_id: str,
        restore_snapshot_id: str,
        restored_at: str,
    ) -> bool:
        with self._connect(autocommit=False) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (_ACTIVATION_LOCK_KEY,),
                    )
                    cur.execute(
                        """
                        SELECT snapshot_id
                        FROM property_evidence_overlay_active_snapshot
                        WHERE pointer_key = 'active'
                        FOR UPDATE
                        """
                    )
                    active_row = cur.fetchone()
                    active_snapshot_id = str(active_row[0] or "") if active_row else ""
                    already_restored = (
                        active_snapshot_id == restore_snapshot_id
                        if restore_snapshot_id
                        else not active_snapshot_id
                    )
                    if already_restored:
                        conn.commit()
                        return False
                    if active_snapshot_id != failed_snapshot_id:
                        raise ValueError(
                            "property evidence overlay rollback lost active-snapshot ownership"
                        )
                    if restore_snapshot_id:
                        cur.execute(
                            """
                            SELECT status
                            FROM property_evidence_overlay_snapshots
                            WHERE snapshot_id = %s
                            FOR UPDATE
                            """,
                            (restore_snapshot_id,),
                        )
                        restore_row = cur.fetchone()
                        if not restore_row or str(restore_row[0] or "") != "retired":
                            raise ValueError(
                                "property evidence overlay rollback target is not retired"
                            )
                    cur.execute(
                        """
                        UPDATE property_evidence_overlay_snapshots
                        SET status = 'retired'
                        WHERE snapshot_id = %s AND status = 'active'
                        """,
                        (failed_snapshot_id,),
                    )
                    if cur.rowcount != 1:
                        raise ValueError(
                            "property evidence overlay failed snapshot is not active"
                        )
                    if restore_snapshot_id:
                        cur.execute(
                            """
                            UPDATE property_evidence_overlay_snapshots
                            SET status = 'active', activated_at = %s
                            WHERE snapshot_id = %s AND status = 'retired'
                            """,
                            (restored_at, restore_snapshot_id),
                        )
                        if cur.rowcount != 1:
                            raise ValueError(
                                "property evidence overlay rollback target activation failed"
                            )
                        cur.execute(
                            """
                            UPDATE property_evidence_overlay_active_snapshot
                            SET snapshot_id = %s, activated_at = %s
                            WHERE pointer_key = 'active'
                            """,
                            (restore_snapshot_id, restored_at),
                        )
                    else:
                        cur.execute(
                            """
                            DELETE FROM property_evidence_overlay_active_snapshot
                            WHERE pointer_key = 'active' AND snapshot_id = %s
                            """,
                            (failed_snapshot_id,),
                        )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def lookup(
        self,
        lookup_values: dict[str, str],
        *,
        snapshot_id: str = "",
    ) -> list[dict[str, object]]:
        pairs = sorted(
            {
                (str(key or "").strip(), str(value or "").strip().casefold())
                for key, value in dict(lookup_values or {}).items()
                if str(key or "").strip() and str(value or "").strip()
            }
        )
        if not pairs:
            return []
        predicates = " OR ".join("(match_key = %s AND match_value = %s)" for _ in pairs)
        pair_params: list[str] = []
        for key, value in pairs:
            pair_params.extend((key, value))
        with self._connect() as conn:
            with conn.cursor() as cur:
                if snapshot_id:
                    cur.execute(
                        f"""
                        SELECT DISTINCT ON (rollups.layer_key, rollups.record_key)
                               rollups.layer_key, rollups.record_key, rollups.payload_json,
                               rollups.cache_updated_at, rollups.source_updated_at,
                               rollups.teable_table, rollups.teable_record_id,
                               rollups.payload_sha256
                        FROM property_evidence_overlay_rollups AS rollups
                        WHERE rollups.snapshot_id = %s AND ({predicates})
                        ORDER BY rollups.layer_key, rollups.record_key,
                                 rollups.cache_updated_at DESC
                        """,  # nosec B608 - predicates contain only fixed placeholders
                        (snapshot_id, *pair_params),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT DISTINCT ON (rollups.layer_key, rollups.record_key)
                               rollups.layer_key, rollups.record_key, rollups.payload_json,
                               rollups.cache_updated_at, rollups.source_updated_at,
                               rollups.teable_table, rollups.teable_record_id,
                               rollups.payload_sha256
                        FROM property_evidence_overlay_rollups AS rollups
                        INNER JOIN property_evidence_overlay_active_snapshot AS active
                            ON active.pointer_key = 'active'
                           AND active.snapshot_id = rollups.snapshot_id
                        WHERE {predicates}
                        ORDER BY rollups.layer_key, rollups.record_key,
                                 rollups.cache_updated_at DESC
                        """,  # nosec B608 - predicates contain only fixed placeholders
                        tuple(pair_params),
                    )
                rows = list(cur.fetchall() or [])
        result: list[dict[str, object]] = []
        for row in rows:
            payload_value = row[2]
            if isinstance(payload_value, str):
                try:
                    payload_value = json.loads(payload_value)
                except json.JSONDecodeError:
                    payload_value = {}
            payload = (
                dict(payload_value or {}) if isinstance(payload_value, dict) else {}
            )
            payload.update(
                {
                    "layer_key": str(row[0] or ""),
                    "record_key": str(row[1] or ""),
                    "cache_updated_at": _iso(row[3]),
                    "source_updated_at": _iso(row[4]),
                    "teable_table": str(row[5] or ""),
                    "teable_record_id": str(row[6] or ""),
                    "payload_sha256": str(row[7] or ""),
                    "read_model_source": "postgres_cached_rollup",
                }
            )
            result.append(payload)
        return result

    def benchmark_samples(
        self,
        *,
        snapshot_id: str,
    ) -> list[tuple[str, dict[str, str]]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (layer_key)
                           layer_key, match_key, match_value
                    FROM property_evidence_overlay_rollups
                    WHERE snapshot_id = %s
                    ORDER BY layer_key, record_key, match_key, match_value
                    """,
                    (snapshot_id,),
                )
                rows = list(cur.fetchall() or [])
        return [
            (
                str(row[0] or ""),
                {str(row[1] or ""): str(row[2] or "")},
            )
            for row in rows
        ]

    def coverage(self, *, snapshot_id: str = "") -> list[dict[str, object]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if snapshot_id:
                    cur.execute(
                        """
                        SELECT layer_key, teable_table, COUNT(DISTINCT record_key),
                               MAX(cache_updated_at), MAX(ingested_at)
                        FROM property_evidence_overlay_rollups
                        WHERE snapshot_id = %s
                        GROUP BY layer_key, teable_table
                        ORDER BY layer_key
                        """,
                        (snapshot_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT rollups.layer_key, rollups.teable_table,
                               COUNT(DISTINCT rollups.record_key),
                               MAX(rollups.cache_updated_at), MAX(rollups.ingested_at)
                        FROM property_evidence_overlay_rollups AS rollups
                        INNER JOIN property_evidence_overlay_active_snapshot AS active
                            ON active.pointer_key = 'active'
                           AND active.snapshot_id = rollups.snapshot_id
                        GROUP BY rollups.layer_key, rollups.teable_table
                        ORDER BY rollups.layer_key
                        """
                    )
                rows = list(cur.fetchall() or [])
        return [
            {
                "layer_key": str(row[0] or ""),
                "teable_table": str(row[1] or ""),
                "record_count": int(row[2] or 0),
                "latest_cache_updated_at": _iso(row[3]),
                "latest_ingested_at": _iso(row[4]),
            }
            for row in rows
        ]
