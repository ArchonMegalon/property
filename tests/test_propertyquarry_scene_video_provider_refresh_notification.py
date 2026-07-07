from __future__ import annotations

import json
from pathlib import Path

from scripts import propertyquarry_notify_scene_video_provider_refresh as notify_refresh


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _packet(*, generated_at: str = "2026-07-07T05:01:00Z") -> dict[str, object]:
    return {
        "contract_name": "propertyquarry.scene_video_provider_refresh_packet.v1",
        "generated_at": generated_at,
        "providers": [
            {
                "provider": "magicfit",
                "expected_account_count": 3,
                "runtime_account_count": 0,
                "visible_account_gap": 3,
                "runtime_blockers": ["magicfit_credentials_missing"],
                "post_refresh_checks": [
                    "merge provider-only MagicFit account JSON with merge_scene_video_provider_accounts_env.py --magicfit-accounts-json-file <magicfit-accounts.json> --expected-magicfit-count 3 --write-file-env --write"
                ],
            },
            {
                "provider": "omagic",
                "expected_account_count": 8,
                "runtime_account_count": 0,
                "visible_account_gap": 8,
                "runtime_blockers": [
                    "omagic_model_upload_adapter_disabled",
                    "omagic_model_upload_endpoint_missing",
                    "omagic_credentials_missing",
                ],
                "post_refresh_checks": [
                    "merge provider-only OMagic/Magic account JSON with merge_scene_video_provider_accounts_env.py --omagic-accounts-json-file <omagic-accounts.json> --expected-omagic-count 8 --write-file-env --write"
                ],
            },
        ],
    }


def _verifier(*, status: str = "pass", generated_at: str = "2026-07-07T05:02:00Z") -> dict[str, object]:
    return {"status": status, "generated_at": generated_at}


def _runtime_status(*, generated_at: str = "2026-07-07T05:03:00Z") -> dict[str, object]:
    return {
        "generated_at": generated_at,
        "summary": {
            "provider_count": 5,
            "ready_count": 2,
            "blocked_count": 3,
            "action_required_count": 3,
        },
    }


def test_scene_video_provider_refresh_notification_skips_when_verifier_fails(tmp_path: Path) -> None:
    packet_path = _write_json(tmp_path / "packet.json", _packet())
    verifier_path = _write_json(tmp_path / "verifier.json", _verifier(status="fail"))
    runtime_status_path = _write_json(tmp_path / "runtime.json", _runtime_status())
    state_path = tmp_path / "state.json"

    report = notify_refresh.build_notification_report(
        packet=_packet(),
        packet_path=packet_path,
        verifier=_verifier(status="fail"),
        verifier_path=verifier_path,
        runtime_status=_runtime_status(),
        runtime_status_path=runtime_status_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["skipped_reason"] == "packet_verifier_status_fail"
    assert not state_path.exists()


def test_scene_video_provider_refresh_notification_sends_actionable_packet(tmp_path: Path, monkeypatch) -> None:
    packet = _packet()
    verifier = _verifier()
    runtime_status = _runtime_status()
    packet_path = _write_json(tmp_path / "packet.json", packet)
    verifier_path = _write_json(tmp_path / "verifier.json", verifier)
    runtime_status_path = _write_json(tmp_path / "runtime.json", runtime_status)
    state_path = tmp_path / "state.json"
    sent: dict[str, object] = {}

    class _Receipt:
        message_ids = ("5091",)

    monkeypatch.setattr(notify_refresh.gold_notify, "build_tool_runtime", lambda: object())
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "send_telegram_message_for_principal",
        lambda runtime, **kwargs: sent.update(kwargs) or _Receipt(),
    )

    report = notify_refresh.build_notification_report(
        packet=packet,
        packet_path=packet_path,
        verifier=verifier,
        verifier_path=verifier_path,
        runtime_status=runtime_status,
        runtime_status_path=runtime_status_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "principal_binding"
    assert report["message_ids"] == ["5091"]
    assert sent["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    assert sent["url_buttons"] == [[("Open PropertyQuarry", "https://propertyquarry.com")]]
    text = str(sent["text"])
    assert "PropertyQuarry scene-video provider runtime is still blocked." in text
    assert "Current runtime: ready 2/5, blocked 3, action required 3." in text
    assert "state/incoming_property_tours/_operator-import-lane/scene_video_provider_accounts" in text
    assert "--magicfit-accounts-json-file <magicfit-accounts.json>" in text
    assert "--omagic-accounts-json-file <omagic-accounts.json>" in text
    assert "PROPERTYQUARRY_OMAGIC_RENDER_ENDPOINT or PROPERTYQUARRY_OMAGIC_RENDER_COMMAND" in text
    assert "PROPERTYQUARRY_OMAGIC_MODEL_UPLOAD_ENABLED=1 only after success" in text
    assert "python3 scripts/property_scene_video_readiness_report.py" in text
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "principal_binding"
    assert state_payload["message_ids"] == ["5091"]


def test_scene_video_provider_refresh_notification_falls_back_to_direct_chat(tmp_path: Path, monkeypatch) -> None:
    packet = _packet()
    verifier = _verifier()
    runtime_status = _runtime_status()
    packet_path = _write_json(tmp_path / "packet.json", packet)
    verifier_path = _write_json(tmp_path / "verifier.json", verifier)
    runtime_status_path = _write_json(tmp_path / "runtime.json", runtime_status)
    state_path = tmp_path / "state.json"
    sent: dict[str, object] = {}

    monkeypatch.setattr(notify_refresh.gold_notify, "build_tool_runtime", lambda: object())
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "send_telegram_message_for_principal",
        lambda runtime, **kwargs: (_ for _ in ()).throw(RuntimeError("telegram_binding_not_found")),
    )
    monkeypatch.setattr(notify_refresh.gold_notify, "_direct_chat_id", lambda: "1354554303")
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "_send_direct_telegram_message",
        lambda **kwargs: sent.update(kwargs) or {"message_ids": ["5092"], "chat_id": kwargs["chat_id"]},
    )

    report = notify_refresh.build_notification_report(
        packet=packet,
        packet_path=packet_path,
        verifier=verifier,
        verifier_path=verifier_path,
        runtime_status=runtime_status,
        runtime_status_path=runtime_status_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "direct_chat_fallback"
    assert report["message_ids"] == ["5092"]
    assert sent["chat_id"] == "1354554303"


def test_scene_video_provider_refresh_notification_prefers_container_runtime_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    packet = _packet()
    verifier = _verifier()
    runtime_status = _runtime_status()
    packet_path = _write_json(tmp_path / "packet.json", packet)
    verifier_path = _write_json(tmp_path / "verifier.json", verifier)
    runtime_status_path = _write_json(tmp_path / "runtime.json", runtime_status)
    state_path = tmp_path / "state.json"
    observed: dict[str, object] = {}

    monkeypatch.setenv("PROPERTYQUARRY_NOTIFICATION_PREFER_CONTAINER_RUNTIME", "1")
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("should not build runtime")),
    )
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "_send_container_runtime_telegram_message",
        lambda **kwargs: observed.update(kwargs) or {"message_ids": ["5093"], "container_name": "propertyquarry-api"},
    )

    report = notify_refresh.build_notification_report(
        packet=packet,
        packet_path=packet_path,
        verifier=verifier,
        verifier_path=verifier_path,
        runtime_status=runtime_status,
        runtime_status_path=runtime_status_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is True
    assert report["delivery_mode"] == "container_runtime_preferred"
    assert report["message_ids"] == ["5093"]
    assert observed["principal_id"] == "cf-email:tibor.girschele@gmail.com"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["delivery_mode"] == "container_runtime_preferred"
    assert state_payload["message_ids"] == ["5093"]


def test_scene_video_provider_refresh_notification_dedupes_semantically_identical_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prior_packet = _packet(generated_at="2026-07-07T05:01:00Z")
    current_packet = _packet(generated_at="2026-07-07T06:01:00Z")
    prior_verifier = _verifier(generated_at="2026-07-07T05:02:00Z")
    current_verifier = _verifier(generated_at="2026-07-07T06:02:00Z")
    prior_runtime = _runtime_status(generated_at="2026-07-07T05:03:00Z")
    current_runtime = _runtime_status(generated_at="2026-07-07T06:03:00Z")
    packet_path = _write_json(tmp_path / "packet.json", current_packet)
    verifier_path = _write_json(tmp_path / "verifier.json", current_verifier)
    runtime_status_path = _write_json(tmp_path / "runtime.json", current_runtime)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_notified_digest": notify_refresh._combined_digest(
                    prior_packet,
                    prior_verifier,
                    prior_runtime,
                )
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        notify_refresh.gold_notify,
        "build_tool_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    report = notify_refresh.build_notification_report(
        packet=current_packet,
        packet_path=packet_path,
        verifier=current_verifier,
        verifier_path=verifier_path,
        runtime_status=current_runtime,
        runtime_status_path=runtime_status_path,
        state_path=state_path,
        principal_id="cf-email:tibor.girschele@gmail.com",
        base_url="https://propertyquarry.com",
        force=False,
    )

    assert report["sent"] is False
    assert report["skipped_reason"] == "already_notified_same_digest"
