from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import propertyquarry_jurisdiction_privacy_rights_gate as gate


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "compliance" / "propertyquarry_jurisdiction_privacy_rights.v1.json"
ENVELOPE = ROOT / "docs" / "propertyquarry_global_market_envelope.v1.json"
COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
EVIDENCE = "sha256:" + "c" * 64


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _approval(*, now: datetime, suffix: str) -> dict[str, object]:
    return {
        "status": "pass",
        "observed_at": (now - timedelta(days=3)).isoformat(),
        "expires_at": (now + timedelta(days=180)).isoformat(),
        "evidence_digest": EVIDENCE,
        "reviewer_ref": f"counsel:{suffix}:reviewer",
        "approval_ref": f"legal:{suffix}:approval",
    }


def _live_receipt(*, now: datetime) -> dict[str, object]:
    markets = []
    inventory = []
    languages = {"AT": "de-AT", "DE": "de-DE", "CR": "es-CR"}
    provider_for_market = {"AT": "provider:at:one", "DE": "provider:de:one", "CR": "provider:cr:one"}
    for country_code in gate.REQUIRED_MARKETS:
        local_approval = {
            **_approval(now=now, suffix=f"{country_code.lower()}:local"),
            "independent_of_implementation": True,
            "reviewer_qualification_ref": f"qualification:{country_code.lower()}:privacy-consumer",
        }
        markets.append(
            {
                "country_code": country_code,
                "launch_approved": True,
                "notice_language": languages[country_code],
                "controller_legal_entity_ref": "entity:propertyquarry:controller",
                "data_residency_decision_ref": f"residency:{country_code.lower()}:decision",
                "privacy_notice_url": f"https://propertyquarry.com/{country_code.lower()}/privacy",
                "cookie_notice_url": f"https://propertyquarry.com/{country_code.lower()}/cookies",
                "terms_url": f"https://propertyquarry.com/{country_code.lower()}/terms",
                "dsar_url": f"https://propertyquarry.com/{country_code.lower()}/privacy-request",
                "hosting_regions": ["hosting:eu-central", "backup:eu-central"],
                "local_legal_approval": local_approval,
                "controls": {
                    control: _approval(now=now, suffix=f"{country_code.lower()}:{control}")
                    for control in gate.REQUIRED_CONTROLS
                },
            }
        )
        inventory.append(
            {
                "country_code": country_code,
                "inventory_digest": EVIDENCE,
                "providers": [
                    {
                        "provider_id": provider_for_market[country_code],
                        "enabled_capabilities": [
                            "automated_access",
                            "cache_normalized_facts",
                            "display_source_attributed_excerpt",
                        ],
                    }
                ],
            }
        )
    rights = []
    permitted = {
        "automated_access",
        "cache_normalized_facts",
        "display_source_attributed_excerpt",
    }
    for country_code, provider_id in provider_for_market.items():
        prohibited = set(gate.PROVIDER_CAPABILITIES) - permitted
        rights.append(
            {
                "provider_id": provider_id,
                "country_codes": [country_code],
                "permitted_capabilities": sorted(permitted),
                "prohibited_capabilities": sorted(prohibited),
                "terms_and_rights_review": _approval(now=now, suffix=f"provider:{country_code.lower()}"),
                "technical_enforcement": {
                    "status": "pass",
                    "observed_at": (now - timedelta(minutes=10)).isoformat(),
                    "evidence_digest": EVIDENCE,
                    "enforced_prohibitions": sorted(prohibited),
                },
            }
        )
    return {
        "schema": gate.LIVE_RECEIPT_SCHEMA,
        "profile": "launch",
        "claim_scope": "core",
        "generated_at": (now - timedelta(minutes=5)).isoformat(),
        "contract_sha256": _digest(CONTRACT),
        "market_envelope_sha256": _digest(ENVELOPE),
        "release_identity": {"commit_sha": COMMIT, "image_digest": IMAGE},
        "market_compliance": markets,
        "market_provider_inventory": inventory,
        "provider_rights": rights,
        "attestation_verification": {
            "status": "pass",
            "observed_at": (now - timedelta(minutes=2)).isoformat(),
            "evidence_digest": EVIDENCE,
            "authority": "independent_compliance_controller",
            "independent_of_implementation": True,
            "workflow_run_ref": "controller:compliance:run:12345",
            "subject_commit_sha": COMMIT,
            "subject_image_digest": IMAGE,
        },
    }


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_jurisdiction_source_contract_is_complete_but_never_live_approval() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert gate.validate_source_contract(contract) == []

    receipt = gate.build_gate(contract_path=CONTRACT, market_envelope_path=ENVELOPE)

    assert receipt["status"] == "blocked"
    assert receipt["source_contract"]["status"] == "pass"
    assert receipt["market_envelope"]["status"] == "pass"
    assert "fresh independently attested live jurisdiction/privacy/provider-rights receipt is required" in receipt["blockers"]

    weakened = dict(contract)
    weakened["market_requirements"] = {
        key: dict(value)
        for key, value in contract["market_requirements"].items()
    }
    weakened["market_requirements"]["DE"]["requires_eu_transfer_assessment"] = False
    assert "jurisdiction/privacy/rights market requirement is incomplete: DE" in gate.validate_source_contract(weakened)


def test_jurisdiction_gate_accepts_exact_current_independent_market_and_provider_approvals(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    live = _write(tmp_path / "live.json", _live_receipt(now=now))

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        market_envelope_path=ENVELOPE,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=now,
    )

    assert receipt["status"] == "pass"
    assert receipt["blockers"] == []
    assert receipt["required_markets"] == ["AT", "DE", "CR"]


def test_jurisdiction_gate_rejects_expired_legal_review_and_unapproved_provider_use(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    payload = _live_receipt(now=now)
    at = payload["market_compliance"][0]  # type: ignore[index]
    at["local_legal_approval"]["expires_at"] = (now - timedelta(minutes=1)).isoformat()  # type: ignore[index]
    provider = payload["market_provider_inventory"][0]["providers"][0]  # type: ignore[index]
    provider["enabled_capabilities"].append("public_packet_republication")  # type: ignore[union-attr]
    payload["provider_rights"][0]["technical_enforcement"]["observed_at"] = (  # type: ignore[index]
        now - timedelta(hours=30)
    ).isoformat()
    live = _write(tmp_path / "bad.json", payload)

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        market_envelope_path=ENVELOPE,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=now,
    )

    assert receipt["status"] == "blocked"
    assert "market AT lacks current independent qualified local legal approval" in receipt["blockers"]
    assert "provider provider:at:one enables an unapproved capability in AT" in receipt["blockers"]
    assert "provider provider:at:one lacks exact technical enforcement for prohibited capabilities" in receipt["blockers"]


def test_jurisdiction_gate_rejects_placeholder_urls_stale_receipt_and_identity_mismatch(tmp_path: Path) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    payload = _live_receipt(now=now)
    payload["generated_at"] = (now - timedelta(hours=30)).isoformat()
    payload["release_identity"]["commit_sha"] = "d" * 40  # type: ignore[index]
    payload["market_compliance"][2]["terms_url"] = "https://terms.example/placeholder"  # type: ignore[index]
    live = _write(tmp_path / "bad.json", payload)

    receipt = gate.build_gate(
        contract_path=CONTRACT,
        market_envelope_path=ENVELOPE,
        live_receipt_path=live,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=now,
    )

    assert receipt["status"] == "blocked"
    assert "live jurisdiction/privacy/provider-rights receipt is stale or future-dated" in receipt["blockers"]
    assert "live jurisdiction/privacy/provider-rights receipt commit does not match the expected release" in receipt["blockers"]
    assert "market CR lacks a safe live terms_url" in receipt["blockers"]

    copied_envelope = tmp_path / "copied-envelope.json"
    copied_envelope.write_bytes(ENVELOPE.read_bytes())
    copied_receipt = gate.build_gate(
        contract_path=CONTRACT,
        market_envelope_path=copied_envelope,
        expected_release_sha=COMMIT,
        expected_image_digest=IMAGE,
        now=now,
    )
    assert "market envelope path does not match the governed source contract" in copied_receipt["blockers"]
