from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import urllib.error

import pytest

from app.repositories.delivery_outbox import InMemoryDeliveryOutboxRepository
from app.repositories.observation import InMemoryObservationEventRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services import registration_email
from app.services import telegram_delivery


_NOW = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)


def _enqueue(
    repository: InMemoryDeliveryOutboxRepository,
    *,
    idempotent_provider: bool,
    key: str = "morning-memo:principal:2026-07-13",
):
    return repository.enqueue(
        channel="email" if idempotent_provider else "telegram",
        recipient="principal@example.com" if idempotent_provider else "principal-1",
        content=json.dumps({"digest_key": "memo"}),
        metadata={
            "principal_id": "principal-1",
            "provider_idempotency_supported": idempotent_provider,
            "max_attempts": 3,
        },
        principal_id="principal-1",
        idempotency_key=key,
    )


def test_two_scheduler_replicas_cannot_claim_the_same_delivery() -> None:
    repository = InMemoryDeliveryOutboxRepository()
    row = _enqueue(repository, idempotent_provider=True)
    barrier = threading.Barrier(3)
    claims: list[object] = []

    def claim(owner: str) -> None:
        barrier.wait()
        claims.append(
            repository.claim(
                row.delivery_id,
                lease_owner=owner,
                lease_seconds=60,
                now=_NOW,
            )
        )

    threads = [
        threading.Thread(target=claim, args=("scheduler-a",)),
        threading.Thread(target=claim, args=("scheduler-b",)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert winners[0].lease_owner in {"scheduler-a", "scheduler-b"}
    assert repository.get(row.delivery_id, principal_id="principal-1").status == "leased"


def test_email_crash_after_provider_send_reclaims_with_same_outbox_identity() -> None:
    repository = InMemoryDeliveryOutboxRepository()
    row = _enqueue(repository, idempotent_provider=True)
    first_claim = repository.claim(
        row.delivery_id,
        lease_owner="scheduler-a",
        lease_seconds=60,
        now=_NOW,
    )
    assert first_claim is not None
    first_attempt = repository.begin_attempt(
        row.delivery_id,
        principal_id="principal-1",
        lease_owner="scheduler-a",
        now=_NOW,
    )
    assert first_attempt is not None
    assert first_attempt.status == "dispatching"
    assert first_attempt.attempt_count == 1

    # Simulate provider acceptance followed by process death before mark_sent.
    recovered_at = _NOW + timedelta(seconds=61)
    recovered = repository.claim(
        row.delivery_id,
        lease_owner="scheduler-b",
        lease_seconds=60,
        now=recovered_at,
    )
    assert recovered is not None
    assert recovered.idempotency_key == row.idempotency_key
    second_attempt = repository.begin_attempt(
        row.delivery_id,
        principal_id="principal-1",
        lease_owner="scheduler-b",
        now=recovered_at,
    )
    assert second_attempt is not None
    assert second_attempt.attempt_count == 2
    sent = repository.mark_sent(
        row.delivery_id,
        principal_id="principal-1",
        receipt_json={"provider_message_id": "emailit-1"},
        lease_owner="scheduler-b",
    )
    assert sent is not None
    assert sent.status == "sent"
    assert _enqueue(repository, idempotent_provider=True).delivery_id == row.delivery_id


def test_non_idempotent_provider_crash_dead_letters_instead_of_resending() -> None:
    repository = InMemoryDeliveryOutboxRepository()
    row = _enqueue(repository, idempotent_provider=False)
    assert repository.claim(
        row.delivery_id,
        lease_owner="scheduler-a",
        lease_seconds=60,
        now=_NOW,
    ) is not None
    assert repository.begin_attempt(
        row.delivery_id,
        principal_id="principal-1",
        lease_owner="scheduler-a",
        now=_NOW,
    ) is not None

    assert repository.claim(
        row.delivery_id,
        lease_owner="scheduler-b",
        lease_seconds=60,
        now=_NOW + timedelta(seconds=61),
    ) is None
    dead = repository.get(row.delivery_id, principal_id="principal-1")
    assert dead is not None
    assert dead.status == "dead_lettered"
    assert dead.last_error == "delivery_outcome_unknown_after_lease_expiry"
    assert dead.attempt_count == 1


def test_bounded_attempts_end_in_dead_letter() -> None:
    repository = InMemoryDeliveryOutboxRepository()
    row = _enqueue(repository, idempotent_provider=True)
    observed_at = _NOW
    for attempt_number in range(1, 4):
        claim = repository.claim(
            row.delivery_id,
            lease_owner=f"scheduler-{attempt_number}",
            lease_seconds=60,
            now=observed_at,
        )
        assert claim is not None
        attempt = repository.begin_attempt(
            row.delivery_id,
            principal_id="principal-1",
            lease_owner=f"scheduler-{attempt_number}",
            now=observed_at,
        )
        assert attempt is not None
        assert attempt.attempt_count == attempt_number
        failed = repository.mark_failed(
            row.delivery_id,
            principal_id="principal-1",
            error="synthetic_provider_failure",
            next_attempt_at=(observed_at + timedelta(minutes=5)).isoformat(),
            dead_letter=attempt_number >= 3,
            lease_owner=f"scheduler-{attempt_number}",
        )
        assert failed is not None
        observed_at += timedelta(minutes=5)

    assert failed.status == "dead_lettered"
    assert failed.attempt_count == 3
    assert failed.next_attempt_at is None


def test_emailit_uses_explicit_stable_provider_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAILIT_API_KEY", "test-only")
    requests = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self) -> bytes:
            return b'{"id":"emailit-message-1"}'

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        requests.append(request)
        return _Response()

    monkeypatch.setattr(registration_email.urllib.request, "urlopen", fake_urlopen)
    for delivery_url in ("https://property.test/first", "https://property.test/rebuilt"):
        receipt = registration_email.send_channel_digest_email(
            recipient_email="principal@example.com",
            digest_key="memo",
            headline="Morning memo",
            preview_text="Preview",
            delivery_url=delivery_url,
            plain_text="Open the memo",
            idempotency_key="stable-schedule-key",
        )
        assert receipt.message_id == "emailit-message-1"

    keys = [request.get_header("Idempotency-key") for request in requests]
    assert len(keys) == 2
    assert keys[0] == keys[1]
    assert keys[0].startswith("ea-mail-")


def test_scheduled_telegram_provider_attempt_is_single_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    def fail_urlopen(request, timeout=0):  # noqa: ANN001
        attempts.append(request)
        raise urllib.error.URLError("synthetic network ambiguity")

    monkeypatch.setattr(telegram_delivery.urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(telegram_delivery.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="telegram_sendmessage_failed"):
        telegram_delivery._telegram_send_json(
            token="test-only",
            method="sendMessage",
            payload={"chat_id": "1", "text": "memo"},
            max_attempts=1,
        )
    assert len(attempts) == 1


def test_scheduler_crash_after_email_send_reuses_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import runner

    runtime = ChannelRuntimeService(
        InMemoryObservationEventRepository(),
        InMemoryDeliveryOutboxRepository(),
    )
    provider_calls: list[str] = []
    provider_acceptances: set[str] = set()

    class _Service:
        def issue_channel_digest_delivery(self, **kwargs):
            key = str(kwargs.get("idempotency_key") or "")
            provider_calls.append(key)
            provider_acceptances.add(key)
            return {
                "delivery_id": "digest-email-1",
                "digest_key": "memo",
                "email_delivery_status": "sent",
                "email_provider": "emailit",
                "email_message_id": "emailit-message-1",
            }

    monkeypatch.setattr(runner, "_scheduler_morning_memo_lease_seconds", lambda: 60)
    original_mark_sent = runtime.mark_delivery_sent

    def crash_before_commit(*args, **kwargs):  # noqa: ANN002, ANN003
        raise SystemExit("synthetic crash after provider acceptance")

    monkeypatch.setattr(runtime, "mark_delivery_sent", crash_before_commit)
    with pytest.raises(SystemExit, match="synthetic crash"):
        runner._dispatch_scheduled_morning_memo(
            container=type("Container", (), {"channel_runtime": runtime})(),
            service=_Service(),
            observed_at=_NOW,
            principal_id="principal-1",
            schedule_key="pref-1",
            local_day="2026-07-13",
            digest_key="memo",
            recipient_email="principal@example.com",
            role="principal",
            display_name="Principal",
            delivery_channel="email",
            retry_after_minutes=5,
            max_attempts=3,
        )

    monkeypatch.setattr(runtime, "mark_delivery_sent", original_mark_sent)
    recovered = runner._dispatch_scheduled_morning_memo(
        container=type("Container", (), {"channel_runtime": runtime})(),
        service=_Service(),
        observed_at=_NOW + timedelta(seconds=61),
        principal_id="principal-1",
        schedule_key="pref-1",
        local_day="2026-07-13",
        digest_key="memo",
        recipient_email="principal@example.com",
        role="principal",
        display_name="Principal",
        delivery_channel="email",
        retry_after_minutes=5,
        max_attempts=3,
    )

    assert recovered["outcome"] == "sent"
    assert len(provider_calls) == 2
    assert len(provider_acceptances) == 1
    assert provider_calls[0] == provider_calls[1]


def test_scheduler_crash_after_telegram_send_dead_letters_without_second_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import runner

    runtime = ChannelRuntimeService(
        InMemoryObservationEventRepository(),
        InMemoryDeliveryOutboxRepository(),
    )
    provider_calls = []

    class _Service:
        def issue_channel_digest_delivery(self, **kwargs):
            provider_calls.append(str(kwargs.get("idempotency_key") or ""))
            return {
                "delivery_id": "digest-telegram-1",
                "digest_key": "assistant_nudge",
                "telegram_delivery_status": "sent",
                "telegram_message_ids": ["42"],
            }

    monkeypatch.setattr(runner, "_scheduler_morning_memo_lease_seconds", lambda: 60)

    def crash_before_commit(*args, **kwargs):  # noqa: ANN002, ANN003
        raise SystemExit("synthetic crash after provider acceptance")

    monkeypatch.setattr(runtime, "mark_delivery_sent", crash_before_commit)
    with pytest.raises(SystemExit, match="synthetic crash"):
        runner._dispatch_scheduled_morning_memo(
            container=type("Container", (), {"channel_runtime": runtime})(),
            service=_Service(),
            observed_at=_NOW,
            principal_id="principal-1",
            schedule_key="pref-telegram-1",
            local_day="2026-07-13",
            digest_key="assistant_nudge",
            recipient_email="principal-1",
            role="principal",
            display_name="Principal",
            delivery_channel="telegram",
            retry_after_minutes=5,
            max_attempts=3,
        )

    recovered = runner._dispatch_scheduled_morning_memo(
        container=type("Container", (), {"channel_runtime": runtime})(),
        service=_Service(),
        observed_at=_NOW + timedelta(seconds=61),
        principal_id="principal-1",
        schedule_key="pref-telegram-1",
        local_day="2026-07-13",
        digest_key="assistant_nudge",
        recipient_email="principal-1",
        role="principal",
        display_name="Principal",
        delivery_channel="telegram",
        retry_after_minutes=5,
        max_attempts=3,
    )

    assert recovered["outcome"] == "dead_lettered"
    assert len(provider_calls) == 1


def test_postgres_outbox_runtime_is_claim_only_and_never_migrates() -> None:
    source = Path("ea/app/repositories/delivery_outbox_postgres.py").read_text(encoding="utf-8")
    upper = source.upper()
    assert "PG_TRY_ADVISORY_XACT_LOCK" in upper
    assert "FOR UPDATE SKIP LOCKED" in upper
    assert "CREATE TABLE" not in upper
    assert "ALTER TABLE" not in upper
    assert "CREATE INDEX" not in upper
