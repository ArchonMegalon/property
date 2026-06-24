from __future__ import annotations

import copy
from datetime import datetime
import threading
from typing import Any

from app.services.property_decision_loop import (
    AgentQuestionTask,
    PropertyDecisionLedgerEntry,
    PropertyDecisionLoopSnapshot,
    PropertyDocumentRecord,
    PropertyEvidenceClaim,
)


_SCHEMA_READY_LOCK = threading.Lock()
_SCHEMA_READY_DATABASE_URLS: set[str] = set()


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class PostgresPropertyDecisionLoopRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresPropertyDecisionLoopRepository")
        if self._database_url not in _SCHEMA_READY_DATABASE_URLS:
            with _SCHEMA_READY_LOCK:
                if self._database_url not in _SCHEMA_READY_DATABASE_URLS:
                    self._ensure_schema()
                    _SCHEMA_READY_DATABASE_URLS.add(self._database_url)

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for postgres property decision loop backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: object):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(copy.deepcopy(value))

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_decision_ledger (
                        decision_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        person_id TEXT NOT NULL DEFAULT 'self',
                        property_ref TEXT NOT NULL,
                        decision_state TEXT NOT NULL,
                        reason_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        source TEXT NOT NULL,
                        actor TEXT NOT NULL DEFAULT '',
                        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
                        supersedes_decision_id TEXT NOT NULL DEFAULT '',
                        learning_applied BOOLEAN NOT NULL DEFAULT FALSE,
                        aggregate_candidate BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_decision_ledger_principal_property_created
                    ON property_decision_ledger(principal_id, property_ref, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_evidence_claims (
                        claim_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        person_id TEXT NOT NULL DEFAULT 'self',
                        property_ref TEXT NOT NULL,
                        decision_id TEXT NOT NULL DEFAULT '',
                        claim_type TEXT NOT NULL,
                        text TEXT NOT NULL,
                        source_type TEXT NOT NULL DEFAULT 'propertyquarry',
                        source_ref TEXT NOT NULL DEFAULT '',
                        confidence TEXT NOT NULL DEFAULT 'medium',
                        verification_state TEXT NOT NULL DEFAULT 'unclear',
                        privacy_class TEXT NOT NULL DEFAULT 'owner_private',
                        allowed_outputs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        expires_at TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_evidence_claims_principal_property_created
                    ON property_evidence_claims(principal_id, property_ref, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_agent_question_tasks (
                        task_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        person_id TEXT NOT NULL DEFAULT 'self',
                        property_ref TEXT NOT NULL,
                        decision_id TEXT NOT NULL DEFAULT '',
                        question_text TEXT NOT NULL,
                        reason_key TEXT NOT NULL DEFAULT '',
                        source_claim_id TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'drafted',
                        answer_source TEXT NOT NULL DEFAULT '',
                        updated_claim_id TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_agent_question_tasks_principal_property_created
                    ON property_agent_question_tasks(principal_id, property_ref, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS property_documents (
                        document_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        person_id TEXT NOT NULL DEFAULT 'self',
                        property_ref TEXT NOT NULL,
                        decision_id TEXT NOT NULL DEFAULT '',
                        document_type TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT '',
                        privacy_class TEXT NOT NULL DEFAULT 'owner_private',
                        verification_state TEXT NOT NULL DEFAULT 'missing',
                        extracted_claims_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        missing_pages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        redaction_state TEXT NOT NULL DEFAULT 'not_started',
                        linked_risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_documents_principal_property_created
                    ON property_documents(principal_id, property_ref, created_at DESC)
                    """
                )

    def persist_snapshot(
        self,
        *,
        principal_id: str,
        person_id: str,
        snapshot: PropertyDecisionLoopSnapshot,
    ) -> dict[str, object]:
        principal = str(principal_id or "").strip()
        person = str(person_id or "self").strip() or "self"
        if not principal:
            raise ValueError("principal_id is required")
        decision = snapshot.decision
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO property_decision_ledger (
                        decision_id, principal_id, person_id, property_ref, decision_state,
                        reason_keys_json, source, actor, confidence, supersedes_decision_id,
                        learning_applied, aggregate_candidate, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (decision_id) DO UPDATE
                    SET decision_state = EXCLUDED.decision_state,
                        reason_keys_json = EXCLUDED.reason_keys_json,
                        learning_applied = EXCLUDED.learning_applied,
                        aggregate_candidate = EXCLUDED.aggregate_candidate
                    """,
                    (
                        decision.decision_id,
                        principal,
                        person,
                        decision.property_ref,
                        decision.decision_state,
                        self._json_value(list(decision.reason_keys)),
                        decision.source,
                        decision.actor,
                        decision.confidence,
                        decision.supersedes_decision_id,
                        decision.learning_applied,
                        decision.aggregate_candidate,
                        decision.created_at,
                    ),
                )
                for claim in snapshot.evidence_claims:
                    cur.execute(
                        """
                        INSERT INTO property_evidence_claims (
                            claim_id, principal_id, person_id, property_ref, decision_id, claim_type,
                            text, source_type, source_ref, confidence, verification_state, privacy_class,
                            allowed_outputs_json, expires_at, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (claim_id) DO UPDATE
                        SET text = EXCLUDED.text,
                            verification_state = EXCLUDED.verification_state,
                            allowed_outputs_json = EXCLUDED.allowed_outputs_json
                        """,
                        (
                            claim.claim_id,
                            principal,
                            person,
                            claim.property_ref,
                            decision.decision_id,
                            claim.claim_type,
                            claim.text,
                            claim.source_type,
                            claim.source_ref,
                            claim.confidence,
                            claim.verification_state,
                            claim.privacy_class,
                            self._json_value(list(claim.allowed_outputs)),
                            claim.expires_at,
                            claim.created_at,
                        ),
                    )
                for task in snapshot.agent_question_tasks:
                    cur.execute(
                        """
                        INSERT INTO property_agent_question_tasks (
                            task_id, principal_id, person_id, property_ref, decision_id, question_text,
                            reason_key, source_claim_id, status, answer_source, updated_claim_id, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (task_id) DO UPDATE
                        SET question_text = EXCLUDED.question_text,
                            status = EXCLUDED.status,
                            updated_claim_id = EXCLUDED.updated_claim_id
                        """,
                        (
                            task.task_id,
                            principal,
                            person,
                            task.property_ref,
                            decision.decision_id,
                            task.question_text,
                            task.reason_key,
                            task.source_claim_id,
                            task.status,
                            task.answer_source,
                            task.updated_claim_id,
                            task.created_at,
                        ),
                    )
                for document in snapshot.document_records:
                    cur.execute(
                        """
                        INSERT INTO property_documents (
                            document_id, principal_id, person_id, property_ref, decision_id, document_type,
                            source, privacy_class, verification_state, extracted_claims_json,
                            missing_pages_json, redaction_state, linked_risks_json, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (document_id) DO UPDATE
                        SET verification_state = EXCLUDED.verification_state,
                            extracted_claims_json = EXCLUDED.extracted_claims_json,
                            redaction_state = EXCLUDED.redaction_state,
                            linked_risks_json = EXCLUDED.linked_risks_json
                        """,
                        (
                            document.document_id,
                            principal,
                            person,
                            document.property_ref,
                            decision.decision_id,
                            document.document_type,
                            document.source,
                            document.privacy_class,
                            document.verification_state,
                            self._json_value(list(document.extracted_claims)),
                            self._json_value(list(document.missing_pages)),
                            document.redaction_state,
                            self._json_value(list(document.linked_risks)),
                            document.created_at,
                        ),
                    )
        return {
            "decision_id": decision.decision_id,
            "persisted": True,
            "evidence_claims": len(snapshot.evidence_claims),
            "agent_question_tasks": len(snapshot.agent_question_tasks),
            "document_records": len(snapshot.document_records),
        }

    def list_decisions(
        self,
        *,
        principal_id: str,
        property_ref: str = "",
        limit: int = 50,
    ) -> list[PropertyDecisionLedgerEntry]:
        n = max(1, min(int(limit or 50), 200))
        params: list[object] = [str(principal_id or "").strip()]
        where = ["principal_id = %s"]
        if str(property_ref or "").strip():
            where.append("property_ref = %s")
            params.append(str(property_ref or "").strip())
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT decision_id, property_ref, decision_state, reason_keys_json, source, actor,
                           confidence, created_at, supersedes_decision_id, learning_applied, aggregate_candidate
                    FROM property_decision_ledger
                    WHERE {' AND '.join(where)}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        out: list[PropertyDecisionLedgerEntry] = []
        for row in rows:
            out.append(
                PropertyDecisionLedgerEntry(
                    decision_id=str(row[0]),
                    property_ref=str(row[1]),
                    decision_state=str(row[2]),  # type: ignore[arg-type]
                    reason_keys=[str(item) for item in list(row[3] or []) if str(item).strip()],
                    source=str(row[4]),  # type: ignore[arg-type]
                    actor=str(row[5] or ""),
                    confidence=float(row[6] or 0.0),
                    created_at=_to_iso(row[7]),
                    supersedes_decision_id=str(row[8] or ""),
                    learning_applied=bool(row[9]),
                    aggregate_candidate=bool(row[10]),
                )
            )
        return out

    def latest_decision_states_for_property_refs(
        self,
        *,
        principal_id: str,
        property_refs: list[str] | tuple[str, ...],
        limit: int = 200,
    ) -> dict[str, str]:
        principal = str(principal_id or "").strip()
        if not principal:
            return {}
        n = max(1, min(int(limit or 200), 1000))
        refs = tuple(
            dict.fromkeys(
                str(ref or "").strip()
                for ref in list(property_refs or [])
                if str(ref or "").strip()
            )
        )[:n]
        if not refs:
            return {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (property_ref) property_ref, decision_state
                    FROM property_decision_ledger
                    WHERE principal_id = %s
                      AND property_ref = ANY(%s)
                    ORDER BY property_ref, created_at DESC
                    """,
                    (principal, list(refs)),
                )
                rows = cur.fetchall()
        return {
            str(row[0] or "").strip(): str(row[1] or "").strip().lower()
            for row in rows
            if str(row[0] or "").strip()
        }

    def export_teable_projection_rows(
        self,
        *,
        principal_id: str,
        limit: int = 200,
    ) -> dict[str, list[dict[str, object]]]:
        principal = str(principal_id or "").strip()
        if not principal:
            return {
                "propertyquarry_decision_ledger": [],
                "propertyquarry_evidence_claims": [],
                "propertyquarry_agent_questions": [],
                "propertyquarry_documents": [],
            }
        n = max(1, min(int(limit or 200), 1000))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision_id, principal_id, person_id, property_ref, decision_state,
                           reason_keys_json, source, actor, confidence, supersedes_decision_id,
                           learning_applied, aggregate_candidate, created_at
                    FROM property_decision_ledger
                    WHERE principal_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                decision_rows = [
                    {
                        "decision_id": str(row[0] or ""),
                        "principal_id": str(row[1] or ""),
                        "person_id": str(row[2] or ""),
                        "property_ref": str(row[3] or ""),
                        "decision_state": str(row[4] or ""),
                        "reason_keys_json": list(row[5] or []),
                        "source": str(row[6] or ""),
                        "actor": str(row[7] or ""),
                        "confidence": float(row[8] or 0.0),
                        "supersedes_decision_id": str(row[9] or ""),
                        "learning_applied": bool(row[10]),
                        "aggregate_candidate": bool(row[11]),
                        "created_at": _to_iso(row[12]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT claim_id, principal_id, person_id, property_ref, decision_id, claim_type,
                           text, source_type, source_ref, confidence, verification_state, privacy_class,
                           allowed_outputs_json, expires_at, created_at
                    FROM property_evidence_claims
                    WHERE principal_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                evidence_rows = [
                    {
                        "claim_id": str(row[0] or ""),
                        "principal_id": str(row[1] or ""),
                        "person_id": str(row[2] or ""),
                        "property_ref": str(row[3] or ""),
                        "decision_id": str(row[4] or ""),
                        "claim_type": str(row[5] or ""),
                        "text": str(row[6] or ""),
                        "source_type": str(row[7] or ""),
                        "source_ref": str(row[8] or ""),
                        "confidence": str(row[9] or ""),
                        "verification_state": str(row[10] or ""),
                        "privacy_class": str(row[11] or ""),
                        "allowed_outputs_json": list(row[12] or []),
                        "expires_at": str(row[13] or ""),
                        "created_at": _to_iso(row[14]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT task_id, principal_id, person_id, property_ref, decision_id, question_text,
                           reason_key, source_claim_id, status, answer_source, updated_claim_id, created_at
                    FROM property_agent_question_tasks
                    WHERE principal_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                agent_question_rows = [
                    {
                        "task_id": str(row[0] or ""),
                        "principal_id": str(row[1] or ""),
                        "person_id": str(row[2] or ""),
                        "property_ref": str(row[3] or ""),
                        "decision_id": str(row[4] or ""),
                        "question_text": str(row[5] or ""),
                        "reason_key": str(row[6] or ""),
                        "source_claim_id": str(row[7] or ""),
                        "status": str(row[8] or ""),
                        "answer_source": str(row[9] or ""),
                        "updated_claim_id": str(row[10] or ""),
                        "created_at": _to_iso(row[11]),
                    }
                    for row in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT document_id, principal_id, person_id, property_ref, decision_id, document_type,
                           source, privacy_class, verification_state, extracted_claims_json,
                           missing_pages_json, redaction_state, linked_risks_json, created_at
                    FROM property_documents
                    WHERE principal_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                document_rows = [
                    {
                        "document_id": str(row[0] or ""),
                        "principal_id": str(row[1] or ""),
                        "person_id": str(row[2] or ""),
                        "property_ref": str(row[3] or ""),
                        "decision_id": str(row[4] or ""),
                        "document_type": str(row[5] or ""),
                        "source": str(row[6] or ""),
                        "privacy_class": str(row[7] or ""),
                        "verification_state": str(row[8] or ""),
                        "extracted_claims_json": list(row[9] or []),
                        "missing_pages_json": list(row[10] or []),
                        "redaction_state": str(row[11] or ""),
                        "linked_risks_json": list(row[12] or []),
                        "created_at": _to_iso(row[13]),
                    }
                    for row in cur.fetchall()
                ]
        return {
            "propertyquarry_decision_ledger": decision_rows,
            "propertyquarry_evidence_claims": evidence_rows,
            "propertyquarry_agent_questions": agent_question_rows,
            "propertyquarry_documents": document_rows,
        }

    def update_agent_question_task(
        self,
        *,
        principal_id: str,
        task_id: str,
        status: str,
        answer_source: str = "",
    ) -> dict[str, object]:
        principal = str(principal_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        normalized_status = str(status or "").strip()
        if not principal or not normalized_task_id or not normalized_status:
            raise ValueError("principal_id, task_id, and status are required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE property_agent_question_tasks
                    SET status = %s,
                        answer_source = CASE WHEN %s <> '' THEN %s ELSE answer_source END
                    WHERE principal_id = %s AND task_id = %s
                    RETURNING task_id, principal_id, person_id, property_ref, decision_id, question_text,
                              reason_key, source_claim_id, status, answer_source, updated_claim_id, created_at
                    """,
                    (normalized_status, str(answer_source or "").strip(), str(answer_source or "").strip(), principal, normalized_task_id),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("property_agent_question_task_not_found")
        return {
            "task_id": str(row[0] or ""),
            "principal_id": str(row[1] or ""),
            "person_id": str(row[2] or ""),
            "property_ref": str(row[3] or ""),
            "decision_id": str(row[4] or ""),
            "question_text": str(row[5] or ""),
            "reason_key": str(row[6] or ""),
            "source_claim_id": str(row[7] or ""),
            "status": str(row[8] or ""),
            "answer_source": str(row[9] or ""),
            "updated_claim_id": str(row[10] or ""),
            "created_at": _to_iso(row[11]),
        }

    def update_document_record(
        self,
        *,
        principal_id: str,
        document_id: str,
        verification_state: str,
    ) -> dict[str, object]:
        principal = str(principal_id or "").strip()
        normalized_document_id = str(document_id or "").strip()
        normalized_state = str(verification_state or "").strip()
        if not principal or not normalized_document_id or not normalized_state:
            raise ValueError("principal_id, document_id, and verification_state are required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE property_documents
                    SET verification_state = %s
                    WHERE principal_id = %s AND document_id = %s
                    RETURNING document_id, principal_id, person_id, property_ref, decision_id, document_type,
                              source, privacy_class, verification_state, extracted_claims_json,
                              missing_pages_json, redaction_state, linked_risks_json, created_at
                    """,
                    (normalized_state, principal, normalized_document_id),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("property_document_not_found")
        return {
            "document_id": str(row[0] or ""),
            "principal_id": str(row[1] or ""),
            "person_id": str(row[2] or ""),
            "property_ref": str(row[3] or ""),
            "decision_id": str(row[4] or ""),
            "document_type": str(row[5] or ""),
            "source": str(row[6] or ""),
            "privacy_class": str(row[7] or ""),
            "verification_state": str(row[8] or ""),
            "extracted_claims_json": list(row[9] or []),
            "missing_pages_json": list(row[10] or []),
            "redaction_state": str(row[11] or ""),
            "linked_risks_json": list(row[12] or []),
            "created_at": _to_iso(row[13]),
        }
