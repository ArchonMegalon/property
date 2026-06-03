from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.models import MemoryCandidate, now_utc_iso


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _clamp_confidence(value: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 0.5
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"pending", "promoted", "rejected"}:
        return raw
    return "pending"


class PostgresMemoryCandidateRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresMemoryCandidateRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres memory-candidate backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_candidates (
                        candidate_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        fact_json JSONB NOT NULL,
                        source_session_id TEXT NOT NULL DEFAULT '',
                        source_event_id TEXT NOT NULL DEFAULT '',
                        source_step_id TEXT NOT NULL DEFAULT '',
                        confidence DOUBLE PRECISION NOT NULL,
                        sensitivity TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        reviewed_at TIMESTAMPTZ NULL,
                        reviewer TEXT NOT NULL DEFAULT '',
                        promoted_item_id TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS source_session_id TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS source_event_id TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS source_step_id TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5"
                )
                cur.execute(
                    "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS sensitivity TEXT NOT NULL DEFAULT 'internal'"
                )
                cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'")
                cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL")
                cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS reviewer TEXT NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS promoted_item_id TEXT NOT NULL DEFAULT ''")
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_candidates_status_created
                    ON memory_candidates(status, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_candidates_principal_created
                    ON memory_candidates(principal_id, created_at DESC)
                    """
                )

    def _from_row(self, row: tuple[Any, ...]) -> MemoryCandidate:
        (
            candidate_id,
            principal_id,
            category,
            summary,
            fact_json,
            source_session_id,
            source_event_id,
            source_step_id,
            confidence,
            sensitivity,
            status,
            created_at,
            reviewed_at,
            reviewer,
            promoted_item_id,
        ) = row
        return MemoryCandidate(
            candidate_id=str(candidate_id),
            principal_id=str(principal_id),
            category=str(category),
            summary=str(summary),
            fact_json=dict(fact_json or {}),
            source_session_id=str(source_session_id or ""),
            source_event_id=str(source_event_id or ""),
            source_step_id=str(source_step_id or ""),
            confidence=float(confidence or 0.0),
            sensitivity=str(sensitivity or "internal"),
            status=str(status or "pending"),
            created_at=_to_iso(created_at),
            reviewed_at=_to_iso(reviewed_at) if reviewed_at else None,
            reviewer=str(reviewer or ""),
            promoted_item_id=str(promoted_item_id or ""),
        )

    def create_candidate(
        self,
        *,
        principal_id: str,
        category: str,
        summary: str,
        fact_json: dict[str, object] | None = None,
        source_session_id: str = "",
        source_event_id: str = "",
        source_step_id: str = "",
        confidence: float = 0.5,
        sensitivity: str = "internal",
    ) -> MemoryCandidate:
        row = MemoryCandidate(
            candidate_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            category=str(category or "fact").strip() or "fact",
            summary=str(summary or "").strip(),
            fact_json=dict(fact_json or {}),
            source_session_id=str(source_session_id or "").strip(),
            source_event_id=str(source_event_id or "").strip(),
            source_step_id=str(source_step_id or "").strip(),
            confidence=_clamp_confidence(confidence),
            sensitivity=str(sensitivity or "internal").strip() or "internal",
            status="pending",
            created_at=now_utc_iso(),
            reviewed_at=None,
            reviewer="",
            promoted_item_id="",
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_candidates
                    (candidate_id, principal_id, category, summary, fact_json,
                     source_session_id, source_event_id, source_step_id, confidence, sensitivity,
                     status, created_at, reviewed_at, reviewer, promoted_item_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING candidate_id, principal_id, category, summary, fact_json,
                              source_session_id, source_event_id, source_step_id, confidence, sensitivity,
                              status, created_at, reviewed_at, reviewer, promoted_item_id
                    """,
                    (
                        row.candidate_id,
                        row.principal_id,
                        row.category,
                        row.summary,
                        self._json_value(row.fact_json),
                        row.source_session_id,
                        row.source_event_id,
                        row.source_step_id,
                        row.confidence,
                        row.sensitivity,
                        row.status,
                        row.created_at,
                        row.reviewed_at,
                        row.reviewer,
                        row.promoted_item_id,
                    ),
                )
                out = cur.fetchone()
        if not out:
            return row
        return self._from_row(out)

    def get(self, candidate_id: str) -> MemoryCandidate | None:
        key = str(candidate_id or "")
        if not key:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT candidate_id, principal_id, category, summary, fact_json,
                           source_session_id, source_event_id, source_step_id, confidence, sensitivity,
                           status, created_at, reviewed_at, reviewer, promoted_item_id
                    FROM memory_candidates
                    WHERE candidate_id = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_candidates(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        principal_id: str | None = None,
    ) -> list[MemoryCandidate]:
        n = max(1, min(500, int(limit or 100)))
        status_filter = str(status or "").strip().lower()
        principal_filter = str(principal_id or "").strip()
        where: list[str] = []
        params: list[object] = []
        if status_filter:
            where.append("status = %s")
            params.append(status_filter)
        if principal_filter:
            where.append("principal_id = %s")
            params.append(principal_filter)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT candidate_id, principal_id, category, summary, fact_json, "
            "source_session_id, source_event_id, source_step_id, confidence, sensitivity, "
            "status, created_at, reviewed_at, reviewer, promoted_item_id "
            "FROM memory_candidates "
            f"{where_sql} "
            "ORDER BY created_at DESC, candidate_id DESC LIMIT %s"
        )
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [self._from_row(row) for row in rows]

    def review(
        self,
        candidate_id: str,
        *,
        status: str,
        reviewer: str,
        promoted_item_id: str = "",
    ) -> MemoryCandidate | None:
        key = str(candidate_id or "")
        if not key:
            return None
        status_value = _normalize_status(status)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memory_candidates
                    SET status = %s,
                        reviewed_at = %s,
                        reviewer = %s,
                        promoted_item_id = %s
                    WHERE candidate_id = %s
                    RETURNING candidate_id, principal_id, category, summary, fact_json,
                              source_session_id, source_event_id, source_step_id, confidence, sensitivity,
                              status, created_at, reviewed_at, reviewer, promoted_item_id
                    """,
                    (
                        status_value,
                        now_utc_iso(),
                        str(reviewer or "").strip(),
                        str(promoted_item_id or "").strip(),
                        key,
                    ),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._from_row(row)
