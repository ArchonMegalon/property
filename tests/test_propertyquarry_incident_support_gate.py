from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import propertyquarry_incident_support_gate as gate


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "monitoring" / "propertyquarry_incident_support.v1.json"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE = "sha256:89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567"
EVIDENCE = "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"


def _live_receipt(*, generated_at: datetime) -> dict[str, object]:
    contract_digest = "sha256:" + hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    evidence = {
        "status": "pass",
        "observed_at": generated_at.isoformat(),
        "evidence_digest": EVIDENCE,
        "workflow_ref": "workflow:incident-support:run:8f27c4",
    }
    receipt = {
        "schema": gate.LIVE_RECEIPT_SCHEMA,
        "profile": "launch",
        "claim_scope": "core",
        "generated_at": generated_at.isoformat(),
        "contract_sha256": contract_digest,
        "release_identity": {"commit_sha": COMMIT, "image_digest": IMAGE},
        "roles": {
            role: {
                "primary_operator_ref": f"ops:{role}:primary",
                "backup_operator_ref": f"ops:{role}:backup",
            }
            for role in gate.REQUIRED_ROLES
        },
        "endpoints": {
            "paging": "https://paging.ops.propertyquarry.com/incidents",
            "status_page": "https://status.propertyquarry.com",
            "support_case_system": "https://support.ops.propertyquarry.com/cases",
            "security_intake": "https://security.ops.propertyquarry.com/intake",
        },
        "launch_market_support": [
            {
                "country_code": country_code,
                "staffed": True,
                "timezone": details["timezone"],
                "support_window": f"08:00-20:00 {details['timezone']}",
                "languages": sorted(details["required_languages"]),
                "primary_owner_ref": f"support:{country_code.lower()}:primary",
                "backup_owner_ref": f"support:{country_code.lower()}:backup",
            }
            for country_code, details in gate.REQUIRED_MARKETS.items()
        ],
        "drills": [{"drill_id": drill_id, **evidence} for drill_id in gate.REQUIRED_DRILLS],
        "approvals": [
            {"control": control, "reviewer_ref": f"review:{control}:owner", **evidence}
            for control in gate.REQUIRED_APPROVALS
        ],
        "attestation_verification": {
            "authority": "independent_release_controller",
            "workflow_run_ref": "github:propertyquarry:run:12345",
            "subject_commit_sha": COMMIT,
            "subject_image_digest": IMAGE,
            **evidence,
        },
    }
    receipt["attestation_verification"]["subject_payload_digest"] = gate._attested_payload_digest(receipt)
    return receipt


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_incident_support_source_contract_is_complete_but_not_live_proof() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert gate.validate_source_contract(contract) == []

    receipt = gate.build_gate(contract_path=CONTRACT)

    assert receipt["status"] == "blocked"
    assert receipt["source_contract"]["status"] == "pass"
    assert "fresh independently attested live incident/support receipt is required" in receipt["blockers"]
    assert "expected exact non-placeholder 40-character release SHA is required" in receipt["blockers"]


def test_incident_support_gate_accepts_fresh_exact_release_attested_coverage(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    live = _write(tmp_path / "live.json", _live_receipt(generated_at=now - timedelta(minutes=5)))

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        required_markets=("AT", "DE", "CR"),
        now=now,
    )

    assert receipt["status"] == "pass"
    assert receipt["blockers"] == []
    assert receipt["required_markets"] == ["AT", "DE", "CR"]


def test_incident_support_gate_rejects_stale_unstaffed_or_unattested_claims(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    payload = _live_receipt(generated_at=now - timedelta(hours=30))
    payload["launch_market_support"][0]["staffed"] = False  # type: ignore[index]
    payload["attestation_verification"]["authority"] = "local_self_attestation"  # type: ignore[index]
    live = _write(tmp_path / "bad-live.json", payload)

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        required_markets=("AT", "DE", "CR"),
        now=now,
    )

    assert receipt["status"] == "blocked"
    assert "live incident/support receipt is stale or future-dated" in receipt["blockers"]
    assert "launch market AT lacks complete staffed support coverage" in receipt["blockers"]
    assert any("drill is not proved" in blocker for blocker in receipt["blockers"])
    assert "live incident/support receipt lacks independent exact-release attestation verification" in receipt["blockers"]


def test_incident_support_gate_rejects_payload_tampering_stale_evidence_and_relaxed_age(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    payload = _live_receipt(generated_at=now - timedelta(minutes=5))
    payload["launch_market_support"][2]["languages"] = ["en"]  # type: ignore[index]
    payload["drills"][0]["observed_at"] = (now - timedelta(hours=25)).isoformat()  # type: ignore[index]
    live = _write(tmp_path / "tampered-live.json", payload)

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        required_markets=("AT", "DE", "CR"),
        max_age_hours=float("inf"),
        now=now,
    )

    assert receipt["status"] == "blocked"
    assert receipt["maximum_age_hours"] == 24
    assert "maximum evidence age must be finite and greater than zero" in receipt["blockers"]
    assert "launch market CR lacks complete staffed support coverage" in receipt["blockers"]
    assert any("drill is not proved" in blocker for blocker in receipt["blockers"])
    assert "live incident/support receipt lacks independent exact-release attestation verification" in receipt["blockers"]


def test_incident_support_gate_requires_exact_market_envelope_and_nonplaceholder_identity(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    live = _write(tmp_path / "live.json", _live_receipt(generated_at=now - timedelta(minutes=5)))
    receipt = gate.build_gate(
        contract_path=CONTRACT,
        live_receipt_path=live,
        expected_release_sha="a" * 40,
        expected_image_digest="sha256:" + "b" * 64,
        required_markets=("AT",),
        now=now,
    )
    assert receipt["status"] == "blocked"
    assert any("non-placeholder" in blocker for blocker in receipt["blockers"])
    assert "required markets must be the exact ordered AT, DE, and CR launch envelope" in receipt["blockers"]
