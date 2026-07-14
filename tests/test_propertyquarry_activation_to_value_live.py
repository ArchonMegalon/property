from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from scripts import propertyquarry_activation_to_value_live as activation


ROOT = Path(__file__).resolve().parents[1]


def _valid_config(tmp_path: Path, **overrides) -> activation.ActivationJourneyConfig:
    values = {
        "base_url": "https://staging.propertyquarry.com",
        "persona_id": "activation-persona-01",
        "persona_email": "activation@example.com",
        "run_key": "activation-run-20260713-01",
        "auth_mode": "google",
        "provider_password": "provider-password-secret",
        "state_path": tmp_path / "activation-state.json",
        "live_authorized": True,
    }
    values.update(overrides)
    return activation.ActivationJourneyConfig(**values)


def _passing_result() -> dict[str, object]:
    return {
        "browser_engine": "chromium",
        "cleanup_ok": True,
        "steps": [
            {"name": name, "ok": True}
            for name in activation.REQUIRED_JOURNEY_STEPS
        ],
    }


def test_activation_journey_blocks_local_or_unconfirmed_runs_before_runner(tmp_path: Path) -> None:
    called = False

    def forbidden_runner(_config):
        nonlocal called
        called = True
        raise AssertionError("local blocked run must never reach browser or providers")

    config = _valid_config(
        tmp_path,
        base_url="http://127.0.0.1:8097",
        live_authorized=False,
    )
    receipt = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=forbidden_runner,
    )

    assert receipt["status"] == "blocked"
    assert called is False
    assert config.state_path.exists() is False
    reasons = {row["reason"] for row in receipt["checks"]}
    assert "activation_live_base_url_must_be_https" in reasons
    assert "activation_live_run_not_explicitly_authorized" in reasons


def test_activation_journey_rejects_unapproved_external_host_before_runner(tmp_path: Path) -> None:
    called = False

    def forbidden_runner(_config):
        nonlocal called
        called = True
        raise AssertionError("unapproved host must never reach browser or providers")

    receipt = activation.build_activation_to_value_receipt(
        config=_valid_config(tmp_path, base_url="https://example.com"),
        journey_runner=forbidden_runner,
    )

    assert receipt["status"] == "blocked"
    assert called is False
    assert any(
        row["reason"] == "activation_live_host_not_explicitly_allowed"
        for row in receipt["checks"]
    )


def test_activation_journey_mock_boundary_builds_secret_safe_passing_receipt(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    receipt = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=lambda observed: _passing_result(),
    )
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "pass"
    assert receipt["failed_count"] == 0
    assert receipt["proof_mode"] == "contract_mock"
    assert [row["name"] for row in receipt["steps"]] == list(activation.REQUIRED_JOURNEY_STEPS)
    assert receipt["live_contract"] == {
        "explicit_persona": True,
        "principal_headers_forbidden": True,
        "session_injection_forbidden": True,
        "provider_response_mocking_forbidden": False,
        "local_execution_forbidden": True,
        "deployed_playwright_runner": False,
    }
    assert config.persona_id not in serialized
    assert config.persona_email not in serialized
    assert config.provider_password not in serialized
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "pass"
    assert state["persona_digest"] == config.persona_digest


def test_activation_journey_run_key_is_fail_closed_against_duplicate_external_actions(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    first = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=lambda _config: _passing_result(),
    )
    called = False

    def duplicate_runner(_config):
        nonlocal called
        called = True
        return _passing_result()

    second = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=duplicate_runner,
    )

    assert first["status"] == "pass"
    assert second["status"] == "blocked"
    assert called is False
    assert second["checks"][0]["name"] == "idempotent_run_reservation"
    assert "activation_run_key_already_used" in second["checks"][0]["reason"]


def test_activation_journey_run_key_cannot_be_reused_for_a_different_persona(tmp_path: Path) -> None:
    first_config = _valid_config(tmp_path)
    activation.build_activation_to_value_receipt(
        config=first_config,
        journey_runner=lambda _config: _passing_result(),
    )
    called = False

    def duplicate_runner(_config):
        nonlocal called
        called = True
        return _passing_result()

    second = activation.build_activation_to_value_receipt(
        config=_valid_config(
            tmp_path,
            persona_id="activation-persona-02",
            persona_email="activation-two@example.com",
        ),
        journey_runner=duplicate_runner,
    )

    assert second["status"] == "blocked"
    assert called is False
    assert "activation_run_key_already_used" in second["checks"][0]["reason"]


def test_activation_journey_corrupt_idempotency_state_fails_closed(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.state_path.write_text("not-json", encoding="utf-8")
    called = False

    def forbidden_runner(_config):
        nonlocal called
        called = True
        return _passing_result()

    receipt = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=forbidden_runner,
    )

    assert receipt["status"] == "blocked"
    assert called is False
    assert "activation_run_state_invalid" in receipt["checks"][0]["reason"]


def test_activation_journey_rejects_missing_value_step_even_when_mock_runner_claims_cleanup(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    result = _passing_result()
    result["steps"] = [
        row for row in result["steps"]
        if row["name"] != "walkthrough_ready"
    ]

    receipt = activation.build_activation_to_value_receipt(
        config=config,
        journey_runner=lambda _config: result,
    )

    assert receipt["status"] == "fail"
    matrix = next(row for row in receipt["checks"] if row["name"] == "activation_step_matrix_complete")
    assert matrix["missing_steps"] == ["walkthrough_ready"]


def test_activation_journey_only_allows_preprovisioned_persona_until_account_cleanup_exists(tmp_path: Path) -> None:
    config = _valid_config(
        tmp_path,
        expected_account_state="new",
        allow_account_create=True,
    )

    failures = activation.validate_live_config(config)

    assert failures == ["activation_new_account_cleanup_not_supported_use_preprovisioned_persona"]


def test_activation_email_link_parser_accepts_only_fresh_same_origin_token_link() -> None:
    message = EmailMessage()
    message["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content(
        "Ignore https://evil.example/sign-in?token=wrong\n"
        "Open https://staging.propertyquarry.com/workspace/sign-in?token=real-token"
    )

    link = activation._extract_same_origin_sign_in_link(
        message.as_bytes(),
        base_url="https://staging.propertyquarry.com",
        not_before=datetime.now(timezone.utc),
    )

    assert link == "https://staging.propertyquarry.com/workspace/sign-in?token=real-token"


def test_activation_email_link_parser_rejects_message_without_verifiable_fresh_date() -> None:
    message = EmailMessage()
    message.set_content("https://staging.propertyquarry.com/workspace/sign-in?token=unverifiable")

    assert activation._extract_same_origin_sign_in_link(
        message.as_bytes(),
        base_url="https://staging.propertyquarry.com",
        not_before=datetime.now(timezone.utc),
    ) == ""


def test_activation_walkthrough_readiness_rejects_placeholder_links() -> None:
    assert activation._walkthrough_href_ready("") is False
    assert activation._walkthrough_href_ready("#") is False
    assert activation._walkthrough_href_ready("javascript:void(0)") is False
    assert activation._walkthrough_href_ready("/public/tours/ready") is True
    assert activation._walkthrough_href_ready("https://tour-provider.example/ready") is True


def test_activation_live_source_forbids_test_auth_and_provider_mock_boundaries() -> None:
    source = (ROOT / "scripts/propertyquarry_activation_to_value_live.py").read_text(encoding="utf-8")

    assert "X-EA-Principal-ID" not in source
    assert "extra_http_headers" not in source
    assert ".add_cookies(" not in source
    assert "storage_state" not in source
    assert "route.fulfill" not in source
    assert "request_workspace_sign_in_email_links" not in source


def test_activation_workflow_is_contract_only_by_default_and_live_only_by_explicit_approval() -> None:
    source = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(encoding="utf-8")
    contract_job = source.split("  propertyquarry-activation-contracts:", 1)[1].split(
        "  propertyquarry-live-release-gates:", 1
    )[0]
    live_job = source.split("  propertyquarry-live-activation-to-value:", 1)[1].split(
        "  smoke-runtime-postgres:", 1
    )[0]

    assert "tests/test_propertyquarry_activation_to_value_live.py" in contract_job
    assert "PROPERTYQUARRY_ACTIVATION_PERSONA_EMAIL" not in contract_job
    assert "github.event_name == 'workflow_dispatch'" in live_job
    assert "inputs.run_activation_journey == true" in live_job
    assert "name: propertyquarry-production" in live_job
    assert "needs: propertyquarry-flagship-security" in live_job
    assert "PROPERTYQUARRY_ACTIVATION_LIVE_RUN: \"1\"" in live_job
    assert "PROPERTYQUARRY_ACTIVATION_ALLOW_ACCOUNT_CREATE: \"0\"" in live_job
    assert "--confirm-live" in live_job
    assert "actions/cache/restore@v4" in live_job
    assert "actions/cache/save@v4" in live_job
    assert "X-EA-Principal-ID" not in live_job
    assert "PROPERTYQUARRY_LIVE_PRINCIPAL_ID" not in live_job
    assert "  propertyquarry-flagship-security:" in source
    assert "  propertyquarry-live-release-gates:\n    needs: propertyquarry-flagship-security" in source
