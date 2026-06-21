from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.id_austria_oidc import id_austria_provider_readiness
from scripts.verify_id_austria_provider import build_id_austria_verification_receipt


ROOT = Path(__file__).resolve().parents[1]


def _clear_id_austria_env(monkeypatch) -> None:
    for key in (
        "PROPERTYQUARRY_ID_AUSTRIA_REQUIRED",
        "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID",
        "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET",
        "PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI",
        "PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET",
        "PROPERTYQUARRY_ID_AUSTRIA_ENVIRONMENT",
        "PROPERTYQUARRY_ID_AUSTRIA_ISSUER",
        "PROPERTYQUARRY_ID_AUSTRIA_AUTHORIZATION_ENDPOINT",
        "PROPERTYQUARRY_ID_AUSTRIA_TOKEN_ENDPOINT",
        "PROPERTYQUARRY_ID_AUSTRIA_JWKS_URI",
        "PROPERTYQUARRY_ID_AUSTRIA_COMPLETION_DIR",
    ):
        monkeypatch.delenv(key, raising=False)


def _configure_id_austria_env(monkeypatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET", "id-austria-secret")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI", "https://propertyquarry.com/id-austria/callback")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET", "id-austria-state-secret")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_ENVIRONMENT", "production")


def test_id_austria_verifier_is_disabled_when_credentials_are_absent(monkeypatch) -> None:
    _clear_id_austria_env(monkeypatch)

    receipt = build_id_austria_verification_receipt()

    assert receipt["provider"] == "id_austria"
    assert receipt["status"] == "disabled"
    assert receipt["configured"] is False
    assert "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID" in receipt["missing_env"]


def test_id_austria_verifier_fails_when_required_credentials_are_absent(monkeypatch) -> None:
    _clear_id_austria_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_REQUIRED", "1")

    receipt = build_id_austria_verification_receipt()

    assert receipt["status"] == "blocked_missing_configuration"
    assert receipt["required"] is True
    assert receipt["configured"] is False


def test_id_austria_runtime_readiness_is_safe_for_version_payload(monkeypatch) -> None:
    _clear_id_austria_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_REQUIRED", "1")

    readiness = id_austria_provider_readiness()

    assert readiness["id_austria_sign_in_status"] == "blocked_missing_configuration"
    assert readiness["id_austria_sign_in_required"] == "true"
    assert readiness["id_austria_sign_in_configured"] == "false"
    assert "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID" in readiness["id_austria_sign_in_missing_env"]
    assert "PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI" not in readiness["id_austria_sign_in_missing_env"]
    assert "id_austria_client_id_missing" == readiness["id_austria_sign_in_error"]
    assert readiness["id_austria_redirect_uri"] == "https://propertyquarry.com/id-austria/callback"


def test_id_austria_requires_its_own_state_secret(monkeypatch) -> None:
    _clear_id_austria_env(monkeypatch)
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID", "https://propertyquarry.com")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET", "id-austria-secret")
    monkeypatch.setenv("PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI", "https://propertyquarry.com/id-austria/callback")
    monkeypatch.setenv("EA_GOOGLE_OAUTH_STATE_SECRET", "generic-google-state-secret")
    monkeypatch.setenv("EA_PROVIDER_SECRET_KEY", "generic-provider-secret")
    monkeypatch.setenv("EA_SIGNING_SECRET", "generic-signing-secret")

    receipt = build_id_austria_verification_receipt()

    assert receipt["status"] == "disabled"
    assert receipt["configured"] is False
    assert receipt["error"] == "id_austria_state_secret_missing"
    assert "PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET" in receipt["missing_env"]


def test_id_austria_verifier_accepts_configured_oidc_contract(monkeypatch) -> None:
    _clear_id_austria_env(monkeypatch)
    _configure_id_austria_env(monkeypatch)

    receipt = build_id_austria_verification_receipt()
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "dry_verified_configured"
    assert receipt["configured"] is True
    assert receipt["issuer"] == "https://idp.id-austria.gv.at"
    assert receipt["redirect_uri"] == "https://propertyquarry.com/id-austria/callback"
    assert "id-austria-secret" not in serialized
    assert "id-austria-state-secret" not in serialized

    readiness = id_austria_provider_readiness()
    readiness_serialized = json.dumps(readiness, sort_keys=True)
    assert readiness["id_austria_sign_in_status"] == "dry_verified_configured"
    assert readiness["id_austria_sign_in_configured"] == "true"
    assert readiness["id_austria_sign_in_missing_env"] == ""
    assert "id-austria-secret" not in readiness_serialized
    assert "id-austria-state-secret" not in readiness_serialized


def test_id_austria_verifier_script_writes_receipt(monkeypatch, tmp_path: Path) -> None:
    _clear_id_austria_env(monkeypatch)
    env = {
        **os.environ,
        "PYTHONPATH": "ea",
        "PROPERTYQUARRY_ID_AUSTRIA_COMPLETION_DIR": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_id_austria_provider.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    receipt_path = Path(result.stdout.strip())
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt_path == tmp_path / "ID_AUSTRIA_PROVIDER_VERIFICATION.generated.json"
    assert payload["status"] == "disabled"
