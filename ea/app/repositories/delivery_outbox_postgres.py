from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.models import DeliveryOutboxItem, now_utc_iso


_ADVISORY_LOCK_SEED = 0x50514F42
_DELIVERY_COLUMNS = """
    delivery_id, principal_id, channel, recipient, content, status, metadata_json,
    created_at, sent_at, idempotency_key, attempt_count, next_attempt_at,
    last_error, receipt_json, dead_lettered_at, lease_owner, lease_expires_at,
    claimed_at, dispatch_started_at
"""
_OUTBOX_DELIVERY_COLUMNS = ", ".join(
    f"outbox.{column.strip()}"
    for column in _DELIVERY_COLUMNS.split(",")
    if column.strip()
)


def _to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _as_utc(value: datetime | None = None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc)


def _as_delivery(row: tuple[Any, ...]) -> DeliveryOutboxItem:
    (
        delivery_id,
        principal_id,
        channel,
        recipient,
        content,
        status,
        metadata_json,
        created_at,
        sent_at,
        idempotency_key,
        attempt_count,
        next_attempt_at,
        last_error,
        receipt_json,
        dead_lettered_at,
        lease_owner,
        lease_expires_at,
        claimed_at,
        dispatch_started_at,
    ) = row
    return DeliveryOutboxItem(
        delivery_id=str(delivery_id),
        principal_id=str(principal_id or ""),
        channel=str(channel),
        recipient=str(recipient),
        content=str(content),
        status=str(status),
        metadata=dict(metadata_json or {}),
        created_at=_to_iso(created_at),
        sent_at=_to_iso(sent_at) if sent_at else None,
        idempotency_key=str(idempotency_key or ""),
        attempt_count=int(attempt_count or 0),
        next_attempt_at=_to_iso(next_attempt_at) if next_attempt_at else None,
        last_error=str(last_error or ""),
        receipt_json=dict(receipt_json or {}),
        dead_lettered_at=_to_iso(dead_lettered_at) if dead_lettered_at else None,
        lease_owner=str(lease_owner or ""),
        lease_expires_at=_to_iso(lease_expires_at) if lease_expires_at else None,
        claimed_at=_to_iso(claimed_at) if claimed_at else None,
        dispatch_started_at=_to_iso(dispatch_started_at) if dispatch_started_at else None,
    )


class PostgresDeliveryOutboxRepository:
    """Claim-owned delivery outbox. Schema changes only run in the deploy migration."""

    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresDeliveryOutboxRepository")
        from app.product.property_search_schema import require_property_search_schema_ready

        require_property_search_schema_ready(self._database_url)

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: dict[str, Any]):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def enqueue(
        self,
        channel: str,
        recipient: str,
        content: str,
        metadata: dict[str, object] | None = None,
        *,
        principal_id: str = "",
        idempotency_key: str = "",
    ) -> DeliveryOutboxItem:
        principal = str(principal_id or "").strip()
        idem = str(idempotency_key or "").strip()
        delivery_id = str(uuid.uuid4())
        created_at = now_utc_iso()
        values = (
            delivery_id,
            principal,
            str(channel or "unknown").strip(),
            str(recipient or "").strip(),
            str(content or ""),
            "queued",
            self._json_value(dict(metadata or {})),
            created_at,
            None,
            idem,
            0,
            None,
            "",
            self._json_value({}),
            None,
            "",
            None,
            None,
            None,
            created_at,
        )
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if idem:
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                            (f"{principal}:{idem}", _ADVISORY_LOCK_SEED),
                        )
                    conflict = (
                        "ON CONFLICT (principal_id, idempotency_key) WHERE idempotency_key <> '' DO NOTHING"
                        if idem
                        else ""
                    )
                    cur.execute(
                        f"""
                        INSERT INTO delivery_outbox
                            ({_DELIVERY_COLUMNS}, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        {conflict}
                        RETURNING {_DELIVERY_COLUMNS}
                        """,
                        values,
                    )
                    row = cur.fetchone()
                    if row is None and idem:
                        cur.execute(
                            f"""
                            SELECT {_DELIVERY_COLUMNS}
                            FROM delivery_outbox
                            WHERE principal_id = %s AND idempotency_key = %s
                            LIMIT 1
                            """,
                            (principal, idem),
                        )
                        row = cur.fetchone()
        if row is None:  # pragma: no cover - defensive database contract
            raise RuntimeError("delivery_outbox_enqueue_failed")
        return _as_delivery(row)

    def get(self, delivery_id: str, *, principal_id: str = "") -> DeliveryOutboxItem | None:
        did = str(delivery_id or "").strip()
        if not did:
            return None
        principal = str(principal_id or "").strip()
        query = f"SELECT {_DELIVERY_COLUMNS} FROM delivery_outbox WHERE delivery_id = %s"
        params: list[object] = [did]
        if principal:
            query += " AND principal_id = %s"
            params.append(principal)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                row = cur.fetchone()
        return _as_delivery(row) if row else None

    def claim(
        self,
        delivery_id: str,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        did = str(delivery_id or "").strip()
        owner = str(lease_owner or "").strip()
        if not did or not owner:
            raise ValueError("delivery_id and lease_owner are required")
        observed_at = _as_utc(now)
        lease_expires_at = observed_at + timedelta(seconds=max(1, int(lease_seconds or 1)))
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE delivery_outbox
                        SET status = 'dead_lettered',
                            last_error = 'delivery_outcome_unknown_after_lease_expiry',
                            next_attempt_at = NULL,
                            dead_lettered_at = %s,
                            lease_owner = '',
                            lease_expires_at = NULL,
                            updated_at = %s
                        WHERE delivery_id = %s
                          AND status = 'dispatching'
                          AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                          AND lower(COALESCE(metadata_json->>'provider_idempotency_supported', 'false'))
                              NOT IN ('1', 'true', 'yes', 'on')
                        """,
                        (observed_at, observed_at, did, observed_at),
                    )
                    cur.execute(
                        f"""
                        WITH candidate AS (
                            SELECT delivery_id
                            FROM delivery_outbox
                            WHERE delivery_id = %s
                              AND (
                                  status = 'queued'
                                  OR (status = 'retry' AND (next_attempt_at IS NULL OR next_attempt_at <= %s))
                                  OR (status = 'leased' AND (lease_expires_at IS NULL OR lease_expires_at <= %s))
                                  OR (
                                      status = 'dispatching'
                                      AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                                      AND lower(COALESCE(metadata_json->>'provider_idempotency_supported', 'false'))
                                          IN ('1', 'true', 'yes', 'on')
                                  )
                              )
                              AND pg_try_advisory_xact_lock(
                                  hashtextextended(
                                      principal_id || ':' || COALESCE(NULLIF(idempotency_key, ''), delivery_id),
                                      %s
                                  )
                              )
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE delivery_outbox AS outbox
                        SET status = 'leased',
                            lease_owner = %s,
                            lease_expires_at = %s,
                            claimed_at = %s,
                            last_error = CASE
                                WHEN outbox.status = 'dispatching' THEN 'delivery_retry_after_uncertain_outcome'
                                ELSE outbox.last_error
                            END,
                            updated_at = %s
                        FROM candidate
                        WHERE outbox.delivery_id = candidate.delivery_id
                        RETURNING {_OUTBOX_DELIVERY_COLUMNS}
                        """,
                        (
                            did,
                            observed_at,
                            observed_at,
                            observed_at,
                            _ADVISORY_LOCK_SEED,
                            owner,
                            lease_expires_at,
                            observed_at,
                            observed_at,
                        ),
                    )
                    row = cur.fetchone()
        return _as_delivery(row) if row else None

    def begin_attempt(
        self,
        delivery_id: str,
        *,
        principal_id: str,
        lease_owner: str,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        observed_at = _as_utc(now)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE delivery_outbox
                    SET status = 'dispatching',
                        attempt_count = attempt_count + 1,
                        dispatch_started_at = %s,
                        updated_at = %s
                    WHERE delivery_id = %s
                      AND principal_id = %s
                      AND status = 'leased'
                      AND lease_owner = %s
                      AND lease_expires_at > %s
                    RETURNING {_DELIVERY_COLUMNS}
                    """,
                    (
                        observed_at,
                        observed_at,
                        str(delivery_id or "").strip(),
                        str(principal_id or "").strip(),
                        str(lease_owner or "").strip(),
                        observed_at,
                    ),
                )
                row = cur.fetchone()
        return _as_delivery(row) if row else None

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
        lease_owner: str = "",
    ) -> DeliveryOutboxItem | None:
        did = str(delivery_id or "").strip()
        principal = str(principal_id or "").strip()
        if not did:
            return None
        conditions = "delivery_id = %s AND principal_id = %s"
        params: list[object] = [
            now_utc_iso(),
            self._json_value(dict(receipt_json or {})),
            now_utc_iso(),
            did,
            principal,
        ]
        owner = str(lease_owner or "").strip()
        if owner:
            conditions += " AND status = 'dispatching' AND lease_owner = %s"
            params.append(owner)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE delivery_outbox
                    SET status = 'sent', sent_at = %s, receipt_json = %s,
                        last_error = '', next_attempt_at = NULL, dead_lettered_at = NULL,
                        lease_owner = '', lease_expires_at = NULL, updated_at = %s
                    WHERE {conditions}
                    RETURNING {_DELIVERY_COLUMNS}
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
        return _as_delivery(row) if row else None

    def mark_failed(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        error: str,
        next_attempt_at: str | None = None,
        dead_letter: bool = False,
        lease_owner: str = "",
    ) -> DeliveryOutboxItem | None:
        did = str(delivery_id or "").strip()
        principal = str(principal_id or "").strip()
        if not did:
            return None
        status = "dead_lettered" if dead_letter else "retry"
        conditions = "delivery_id = %s AND principal_id = %s"
        params: list[object] = [
            status,
            None if dead_letter else next_attempt_at,
            str(error or "")[:500],
            now_utc_iso() if dead_letter else None,
            now_utc_iso(),
            did,
            principal,
        ]
        owner = str(lease_owner or "").strip()
        if owner:
            conditions += " AND status = 'dispatching' AND lease_owner = %s"
            params.append(owner)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE delivery_outbox
                    SET status = %s,
                        attempt_count = attempt_count + CASE WHEN %s = '' THEN 1 ELSE 0 END,
                        next_attempt_at = %s,
                        last_error = %s,
                        dead_lettered_at = %s,
                        lease_owner = '', lease_expires_at = NULL, updated_at = %s
                    WHERE {conditions}
                    RETURNING {_DELIVERY_COLUMNS}
                    """,
                    tuple([params[0], owner, *params[1:]]),
                )
                row = cur.fetchone()
        return _as_delivery(row) if row else None

    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        n = max(1, min(500, int(limit or 50)))
        normalized_principal = str(principal_id or "").strip()
        query = f"""
            SELECT {_DELIVERY_COLUMNS}
            FROM delivery_outbox
            WHERE status IN ('queued', 'retry')
              AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
        """
        params: list[Any] = []
        if normalized_principal:
            query += " AND principal_id = %s"
            params.append(normalized_principal)
        query += " ORDER BY created_at DESC, delivery_id DESC LIMIT %s"
        params.append(n)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
        return [_as_delivery(row) for row in rows]

    def list_for_principal(self, principal_id: str, *, limit: int = 5000) -> list[DeliveryOutboxItem]:
        principal = str(principal_id or "").strip()
        n = max(1, min(50_000, int(limit or 5000)))
        if not principal:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {_DELIVERY_COLUMNS}
                    FROM delivery_outbox
                    WHERE principal_id = %s
                    ORDER BY created_at DESC, delivery_id DESC
                    LIMIT %s
                    """,
                    (principal, n),
                )
                rows = cur.fetchall()
        return [_as_delivery(row) for row in rows]

    def erase_principal(self, principal_id: str) -> int:
        principal = str(principal_id or "").strip()
        if not principal:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM delivery_outbox WHERE principal_id = %s", (principal,))
                return int(cur.rowcount or 0)
