from __future__ import annotations

import json
from pathlib import Path

from scripts import propertyquarry_notify_gold_status as notify_gold_status


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gold_notification_receipt_path_prefers_canonical_latest_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    canonical = _write_json(
        tmp_path / "_completion" / "property_gold_status" / "latest.json",
        {"status": "pass"},
    )
    legacy = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        {"status": "blocked"},
    )

    resolved = notify_gold_status._resolve_receipt_path("_completion/property_gold_status/latest.json")

    assert resolved == canonical.resolve()
    assert resolved != legacy.resolve()


def test_gold_notification_receipt_path_falls_back_to_legacy_latest_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    legacy = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        {"status": "pass"},
    )

    resolved = notify_gold_status._resolve_receipt_path("_completion/property_gold_status/latest.json")

    assert resolved == legacy.resolve()


def test_gold_notification_skips_blocked_receipt(tmp_path: Path) -> None:
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        {"status": "blocked", "generated_at": "2026-06-27T08:14:13Z"},
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"

    report = notify_gold_status.build_notification_report(
        payload={"status": "blocked", "generated_at": "2026-06-27T08:14:13Z"},
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["skipped_reason"] == "receipt_status_blocked"
    assert not state_path.exists()


def test_gold_notification_sends_for_new_pass_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}, {"area": "billing_handoff"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    sent: dict[str, object] = {}

    class _Receipt:
        message_ids = ("3097",)

    monkeypatch.setattr(notify_gold_status, "build_tool_runtime", lambda: object())
    monkeypatch.setattr(
        notify_gold_status,
        "send_telegram_message_for_principal",
        lambda runtime, **kwargs: sent.update(kwargs) or _Receipt(),
    )

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "principal_binding"
    assert report["message_ids"] == ["3097"]
    assert report["ready_for_notification"] is True
    assert sent["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    assert sent["url_buttons"] == [[("Open PropertyQuarry", "https://propertyquarry.com")]]
    assert "PropertyQuarry gold receipt is green." in str(sent["text"])
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "principal_binding"
    assert state_payload["last_notified_status"] == "pass"
    assert state_payload["message_ids"] == ["3097"]


def test_gold_notification_falls_back_to_direct_chat_when_binding_missing(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    sent: dict[str, object] = {}

    monkeypatch.setattr(notify_gold_status, "build_tool_runtime", lambda: object())
    monkeypatch.setattr(
        notify_gold_status,
        "send_telegram_message_for_principal",
        lambda runtime, **kwargs: (_ for _ in ()).throw(RuntimeError("telegram_binding_not_found")),
    )
    monkeypatch.setenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", "1354554303")
    monkeypatch.setattr(
        notify_gold_status,
        "_send_direct_telegram_message",
        lambda **kwargs: sent.update(kwargs) or {"message_ids": ["4201"], "chat_id": kwargs["chat_id"]},
    )

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "direct_chat_fallback"
    assert report["message_ids"] == ["4201"]
    assert sent["chat_id"] == "1354554303"
    assert sent["url_buttons"] == [[("Open PropertyQuarry", "https://propertyquarry.com")]]
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "direct_chat_fallback"
    assert state_payload["message_ids"] == ["4201"]


def test_gold_notification_falls_back_to_direct_chat_when_runtime_bootstrap_fails(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "billing_handoff"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    sent: dict[str, object] = {}

    monkeypatch.setattr(
        notify_gold_status,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("failed to resolve host 'ea-db'")),
    )
    monkeypatch.setattr(
        notify_gold_status,
        "_send_container_runtime_telegram_message",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("container runtime unavailable")),
    )
    monkeypatch.setenv("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID", "1354554303")
    monkeypatch.setattr(
        notify_gold_status,
        "_send_direct_telegram_message",
        lambda **kwargs: sent.update(kwargs) or {"message_ids": ["4202"], "chat_id": kwargs["chat_id"]},
    )

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "direct_chat_fallback"
    assert report["message_ids"] == ["4202"]
    assert report["runtime_error"] == "RuntimeError: failed to resolve host 'ea-db'"
    assert report["container_runtime_error"] == "RuntimeError: container runtime unavailable"
    assert sent["chat_id"] == "1354554303"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "direct_chat_fallback"
    assert state_payload["message_ids"] == ["4202"]


def test_gold_notification_falls_back_to_container_runtime_when_host_runtime_bootstrap_fails(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "billing_handoff"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        notify_gold_status,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("failed to resolve host 'ea-db'")),
    )
    monkeypatch.setattr(
        notify_gold_status,
        "_send_container_runtime_telegram_message",
        lambda **kwargs: observed.update(kwargs) or {"message_ids": ["4301"], "container_name": "propertyquarry-api"},
    )

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "container_runtime_fallback"
    assert report["message_ids"] == ["4301"]
    assert report["runtime_error"] == "RuntimeError: failed to resolve host 'ea-db'"
    assert observed["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    assert observed["url_buttons"] == [[("Open PropertyQuarry", "https://propertyquarry.com")]]
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "container_runtime_fallback"
    assert state_payload["message_ids"] == ["4301"]


def test_gold_notification_dedupes_same_pass_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    digest = notify_gold_status._payload_digest(receipt_payload)
    _write_json(
        state_path,
        {
            "last_notified_digest": digest,
            "last_notified_status": "pass",
        },
    )
    monkeypatch.setattr(notify_gold_status, "build_tool_runtime", lambda: (_ for _ in ()).throw(AssertionError("should not build runtime")))

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["skipped_reason"] == "already_notified_same_digest"


def test_gold_notification_dedupes_same_pass_semantics_across_generated_at_changes(tmp_path: Path, monkeypatch) -> None:
    prior_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}],
    }
    current_payload = {
        "status": "pass",
        "ready_for_notification": True,
        "generated_at": "2026-06-27T09:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        current_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    digest = notify_gold_status._payload_digest(prior_payload)
    _write_json(
        state_path,
        {
            "last_notified_digest": digest,
            "last_notified_status": "pass",
        },
    )
    monkeypatch.setattr(
        notify_gold_status,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("should not build runtime")),
    )

    report = notify_gold_status.build_notification_report(
        payload=current_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["skipped_reason"] == "already_notified_same_digest"


def test_gold_notification_skips_pass_receipt_without_explicit_ready_flag(tmp_path: Path, monkeypatch) -> None:
    receipt_payload = {
        "status": "pass",
        "generated_at": "2026-06-27T08:14:13Z",
        "pass_areas": [{"area": "live_mobile_surfaces"}],
    }
    receipt_path = _write_json(
        tmp_path / "_completion" / "propertyquarry-gold-status-latest.json",
        receipt_payload,
    )
    state_path = tmp_path / "_completion" / "propertyquarry-gold-notification-state.json"
    monkeypatch.setattr(
        notify_gold_status,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("should not build runtime")),
    )

    report = notify_gold_status.build_notification_report(
        payload=receipt_payload,
        receipt_path=receipt_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["ready_for_notification"] is False
    assert report["skipped_reason"] == "receipt_not_ready_for_notification"
    assert not state_path.exists()
