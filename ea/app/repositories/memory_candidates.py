from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import MemoryCandidate, now_utc_iso


class MemoryCandidateRepository(Protocol):
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
        ...

    def get(self, candidate_id: str) -> MemoryCandidate | None:
        ...

    def list_candidates(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        principal_id: str | None = None,
    ) -> list[MemoryCandidate]:
        ...

    def review(
        self,
        candidate_id: str,
        *,
        status: str,
        reviewer: str,
        promoted_item_id: str = "",
    ) -> MemoryCandidate | None:
        ...


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


class InMemoryMemoryCandidateRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, MemoryCandidate] = {}
        self._order: List[str] = []

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
        self._rows[row.candidate_id] = row
        self._order.append(row.candidate_id)
        return row

    def get(self, candidate_id: str) -> MemoryCandidate | None:
        return self._rows.get(str(candidate_id or ""))

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
        rows = [self._rows[cid] for cid in reversed(self._order) if cid in self._rows]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        if principal_filter:
            rows = [row for row in rows if row.principal_id == principal_filter]
        return rows[:n]

    def review(
        self,
        candidate_id: str,
        *,
        status: str,
        reviewer: str,
        promoted_item_id: str = "",
    ) -> MemoryCandidate | None:
        key = str(candidate_id or "")
        row = self._rows.get(key)
        if not row:
            return None
        reviewed_status = _normalize_status(status)
        updated = MemoryCandidate(
            candidate_id=row.candidate_id,
            principal_id=row.principal_id,
            category=row.category,
            summary=row.summary,
            fact_json=row.fact_json,
            source_session_id=row.source_session_id,
            source_event_id=row.source_event_id,
            source_step_id=row.source_step_id,
            confidence=row.confidence,
            sensitivity=row.sensitivity,
            status=reviewed_status,
            created_at=row.created_at,
            reviewed_at=now_utc_iso(),
            reviewer=str(reviewer or "").strip(),
            promoted_item_id=str(promoted_item_id or "").strip(),
        )
        self._rows[key] = updated
        return updated
