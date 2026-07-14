from __future__ import annotations

import json
from pathlib import Path

from scripts import propertyquarry_scene_video_balance_probe as probe


def test_magicfit_credit_snapshot_reads_balance_adjacent_to_buy_credits() -> None:
    snapshot = probe._magicfit_credit_snapshot("Video generator\n6,400\nBUY CREDITS\nAccount")

    assert snapshot == {
        "credit_state": "funded",
        "remaining": 6400,
        "unit": "credits",
        "credit_ui_present": True,
    }


def test_magicfit_credit_snapshot_fails_closed_when_balance_is_not_visible() -> None:
    snapshot = probe._magicfit_credit_snapshot("Video generator\nAccount")

    assert snapshot == {
        "credit_state": "unprobed",
        "remaining": None,
        "unit": "credits",
        "credit_ui_present": False,
    }


def test_magicfit_credit_snapshot_reads_explicit_credit_label() -> None:
    snapshot = probe._magicfit_credit_snapshot("Available balance: 6,340 credits")

    assert snapshot["credit_state"] == "funded"
    assert snapshot["remaining"] == 6340


def test_balance_probe_receipt_is_explicitly_no_render_and_secret_safe(tmp_path: Path, monkeypatch) -> None:
    shared_env = tmp_path / "shared.env"
    shared_env.write_text(
        "PROPERTYQUARRY_MAGICFIT_PASSWORD=magicfit-secret\n"
        "PROPERTYQUARRY_OMAGIC_API_KEY=omagic-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        probe,
        "_probe_magicfit",
        lambda _values: {
            "provider": "magicfit",
            "status": "pass",
            "accounts": [{"account_label": "account-1", "remaining": 6400, "unit": "credits"}],
        },
    )
    monkeypatch.setattr(
        probe,
        "_probe_omagic",
        lambda _values: {
            "provider": "omagic",
            "status": "pass",
            "template_variant_id": "299",
            "model_argument_name": "UserObject",
        },
    )

    receipt = probe.build_balance_probe_receipt(
        providers=("magicfit", "omagic"),
        shared_env_file=shared_env,
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["status"] == "pass"
    assert receipt["render_submitted"] is False
    assert receipt["quota_consumed"] is False
    assert "magicfit-secret" not in serialized
    assert "omagic-secret" not in serialized
