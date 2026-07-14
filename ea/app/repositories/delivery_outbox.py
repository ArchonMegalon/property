from __future__ import annotations

import uuid
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Protocol

from app.domain.models import DeliveryOutboxItem, now_utc_iso


def _as_utc(value: datetime | str | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)
        except ValueError:
            parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _due(next_attempt_at: str | None, *, now: datetime | None = None) -> bool:
    raw = str(next_attempt_at or "").strip()
    if not raw:
        return True
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _as_utc(now)


def _lease_expired(row: DeliveryOutboxItem, *, now: datetime) -> bool:
    raw = str(row.lease_expires_at or "").strip()
    if not raw:
        return True
    return _as_utc(raw) <= now


def _provider_idempotency_supported(row: DeliveryOutboxItem) -> bool:
    value = row.metadata.get("provider_idempotency_supported")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class DeliveryOutboxRepository(Protocol):
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
        ...

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
        lease_owner: str = "",
    ) -> DeliveryOutboxItem | None:
        ...

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
        ...

    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        ...

    def get(self, delivery_id: str, *, principal_id: str = "") -> DeliveryOutboxItem | None:
        ...

    def claim(
        self,
        delivery_id: str,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        ...

    def begin_attempt(
        self,
        delivery_id: str,
        *,
        principal_id: str,
        lease_owner: str,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        ...

    def list_for_principal(self, principal_id: str, *, limit: int = 5000) -> list[DeliveryOutboxItem]:
        ...

    def erase_principal(self, principal_id: str) -> int:
        ...


class InMemoryDeliveryOutboxRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: Dict[str, DeliveryOutboxItem] = {}
        self._order: List[str] = []
        self._idempotency_to_id: Dict[tuple[str, str], str] = {}

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
        with self._lock:
            if idem:
                found_id = self._idempotency_to_id.get((principal, idem))
                if found_id and found_id in self._rows:
                    return self._rows[found_id]
            row = DeliveryOutboxItem(
                delivery_id=str(uuid.uuid4()),
                principal_id=principal,
                channel=str(channel or "unknown").strip(),
                recipient=str(recipient or "").strip(),
                content=str(content or ""),
                status="queued",
                metadata=dict(metadata or {}),
                created_at=now_utc_iso(),
                sent_at=None,
                idempotency_key=idem,
                attempt_count=0,
                next_attempt_at=None,
                last_error="",
                receipt_json={},
                dead_lettered_at=None,
            )
            self._rows[row.delivery_id] = row
            self._order.append(row.delivery_id)
            if idem:
                self._idempotency_to_id[(principal, idem)] = row.delivery_id
            return row

    def mark_sent(
        self,
        delivery_id: str,
        *,
        principal_id: str = "",
        receipt_json: dict[str, object] | None = None,
        lease_owner: str = "",
    ) -> DeliveryOutboxItem | None:
        with self._lock:
            found = self._rows.get(str(delivery_id or ""))
            if not found or found.principal_id != str(principal_id or "").strip():
                return None
            owner = str(lease_owner or "").strip()
            if owner and (found.status != "dispatching" or found.lease_owner != owner):
                return None
            updated = replace(
                found,
                status="sent",
                sent_at=now_utc_iso(),
                receipt_json=dict(receipt_json or found.receipt_json),
                last_error="",
                next_attempt_at=None,
                dead_lettered_at=None,
                lease_owner="",
                lease_expires_at=None,
            )
            self._rows[updated.delivery_id] = updated
            return updated

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
        with self._lock:
            found = self._rows.get(str(delivery_id or ""))
            if not found or found.principal_id != str(principal_id or "").strip():
                return None
            owner = str(lease_owner or "").strip()
            if owner and (found.status != "dispatching" or found.lease_owner != owner):
                return None
            status = "dead_lettered" if dead_letter else "retry"
            updated = replace(
                found,
                status=status,
                attempt_count=(
                    max(0, int(found.attempt_count))
                    if owner
                    else max(0, int(found.attempt_count)) + 1
                ),
                last_error=str(error or "")[:500],
                next_attempt_at=None if dead_letter else str(next_attempt_at or ""),
                dead_lettered_at=now_utc_iso() if dead_letter else None,
                lease_owner="",
                lease_expires_at=None,
            )
            self._rows[updated.delivery_id] = updated
            return updated

    def list_pending(self, limit: int = 50, *, principal_id: str | None = None) -> list[DeliveryOutboxItem]:
        n = max(1, min(500, int(limit or 50)))
        normalized_principal = str(principal_id or "").strip()
        with self._lock:
            pending_ids = [
                i
                for i in self._order
                if self._rows.get(i)
                and (not normalized_principal or self._rows[i].principal_id == normalized_principal)
                and self._rows[i].status in {"queued", "retry"}
                and _due(self._rows[i].next_attempt_at)
            ]
            ids = list(reversed(pending_ids[-n:]))
            return [self._rows[i] for i in ids if i in self._rows]

    def get(self, delivery_id: str, *, principal_id: str = "") -> DeliveryOutboxItem | None:
        with self._lock:
            row = self._rows.get(str(delivery_id or "").strip())
            principal = str(principal_id or "").strip()
            if row is None or (principal and row.principal_id != principal):
                return None
            return row

    def claim(
        self,
        delivery_id: str,
        *,
        lease_owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        owner = str(lease_owner or "").strip()
        if not owner:
            raise ValueError("lease_owner is required")
        observed_at = _as_utc(now)
        with self._lock:
            row = self._rows.get(str(delivery_id or "").strip())
            if row is None:
                return None
            expired = _lease_expired(row, now=observed_at)
            if row.status == "dispatching" and expired and not _provider_idempotency_supported(row):
                self._rows[row.delivery_id] = replace(
                    row,
                    status="dead_lettered",
                    last_error="delivery_outcome_unknown_after_lease_expiry",
                    next_attempt_at=None,
                    dead_lettered_at=observed_at.isoformat(),
                    lease_owner="",
                    lease_expires_at=None,
                )
                return None
            eligible = (
                (row.status == "queued")
                or (row.status == "retry" and _due(row.next_attempt_at, now=observed_at))
                or (row.status == "leased" and expired)
                or (row.status == "dispatching" and expired and _provider_idempotency_supported(row))
            )
            if not eligible:
                return None
            claimed = replace(
                row,
                status="leased",
                lease_owner=owner,
                lease_expires_at=(observed_at + timedelta(seconds=max(1, int(lease_seconds or 1)))).isoformat(),
                claimed_at=observed_at.isoformat(),
                last_error=(
                    "delivery_retry_after_uncertain_outcome"
                    if row.status == "dispatching"
                    else row.last_error
                ),
            )
            self._rows[row.delivery_id] = claimed
            return claimed

    def begin_attempt(
        self,
        delivery_id: str,
        *,
        principal_id: str,
        lease_owner: str,
        now: datetime | None = None,
    ) -> DeliveryOutboxItem | None:
        observed_at = _as_utc(now)
        with self._lock:
            row = self._rows.get(str(delivery_id or "").strip())
            if (
                row is None
                or row.principal_id != str(principal_id or "").strip()
                or row.status != "leased"
                or row.lease_owner != str(lease_owner or "").strip()
                or _lease_expired(row, now=observed_at)
            ):
                return None
            dispatching = replace(
                row,
                status="dispatching",
                attempt_count=max(0, int(row.attempt_count)) + 1,
                dispatch_started_at=observed_at.isoformat(),
            )
            self._rows[row.delivery_id] = dispatching
            return dispatching

    def list_for_principal(self, principal_id: str, *, limit: int = 5000) -> list[DeliveryOutboxItem]:
        principal = str(principal_id or "").strip()
        n = max(1, min(50_000, int(limit or 5000)))
        if not principal:
            return []
        with self._lock:
            return [
                self._rows[delivery_id]
                for delivery_id in reversed(self._order)
                if delivery_id in self._rows and self._rows[delivery_id].principal_id == principal
            ][:n]

    def erase_principal(self, principal_id: str) -> int:
        principal = str(principal_id or "").strip()
        if not principal:
            return 0
        with self._lock:
            removed_ids = {
                delivery_id
                for delivery_id, row in self._rows.items()
                if row.principal_id == principal
            }
            for delivery_id in removed_ids:
                self._rows.pop(delivery_id, None)
            self._order = [delivery_id for delivery_id in self._order if delivery_id not in removed_ids]
            self._idempotency_to_id = {
                key: delivery_id
                for key, delivery_id in self._idempotency_to_id.items()
                if delivery_id not in removed_ids
            }
            return len(removed_ids)
