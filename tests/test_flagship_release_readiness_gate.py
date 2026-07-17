from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_flagship_release_readiness.py"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _passing_browser_proof() -> dict[str, object]:
    return json.loads(
        (ROOT / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json").read_text(
            encoding="utf-8"
        )
    )


def _passing_flagship_receipt() -> dict[str, object]:
    return json.loads(
        (ROOT / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json").read_text(
            encoding="utf-8"
        )
    )


def _passing_pulse(*, journey_path: Path | None = None) -> dict[str, object]:
    pulse = json.loads(
        (ROOT / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json").read_text(
            encoding="utf-8"
        )
    )
    if journey_path is not None:
        source = journey_path.as_posix()
        pulse["journey_gate_source"] = source
        pulse["supporting_signals"]["journey_gate_source"] = source
    return pulse


def test_flagship_release_readiness_gate_repository_defaults_share_product_identity() -> None:
    seed = json.loads(
        (ROOT / ".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json").read_text(encoding="utf-8")
    )
    browser = json.loads(
        (ROOT / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = json.loads(
        (ROOT / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json").read_text(
            encoding="utf-8"
        )
    )
    pulse = json.loads(
        (ROOT / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json").read_text(
            encoding="utf-8"
        )
    )

    expected_product = seed["product"]
    assert expected_product == "propertyquarry"
    implementation_scope = (
        ROOT / ".codex-design/repo/IMPLEMENTATION_SCOPE.md"
    ).read_text(encoding="utf-8")
    assert implementation_scope.splitlines()[0] == "# PropertyQuarry implementation scope"
    assert browser["product"] == expected_product
    assert browser["proof_target"] == seed["browser_workflow_proof"]["proof_target"]
    assert browser["release_claim_summary"] == seed["release_claim"]["summary"]
    assert browser["expected_browser_signals"] == seed["browser_workflow_proof"]["expected_browser_signals"]
    assert receipt["product"] == expected_product
    assert "Executive Assistant" not in json.dumps(pulse)


def test_flagship_release_readiness_gate_keeps_external_fleet_journey_non_authoritative(
    tmp_path: Path,
) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    pulse_payload = _passing_pulse()
    pulse_payload["journey_gate_health"]["state"] = "blocked"
    pulse_payload["journey_gate_health"]["blocked_count"] = 1
    _write_json(pulse, pulse_payload)
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    _write_json(journey, {"summary": {"overall_state": "blocked", "blocked_count": 1}})
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout


def test_flagship_release_readiness_gate_passes_when_receipts_and_journeys_are_clear(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    _write_json(pulse, _passing_pulse())
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout


def test_flagship_release_readiness_gate_rejects_false_green_all_skipped_browser_proof(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    _write_json(pulse, _passing_pulse())
    _write_json(receipt, _passing_flagship_receipt())
    false_green_browser = _passing_browser_proof()
    false_green_browser["real_browser_e2e_proof"] = {
        "status": "pass",
        "test_file": "tests/e2e/test_propertyquarry_greenfield_browser.py",
        "cases": [
            "test_propertyquarry_greenfield_workspace_in_real_browser",
            "test_propertyquarry_greenfield_workspace_is_mobile_usable",
        ],
        "exit_code": 0,
        "output_excerpt": ["1 skipped, 20 deselected in 0.79s"],
        "limitations": ["real browser E2E did not run to completion"],
    }
    _write_json(browser, false_green_browser)
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "browser workflow proof is internally inconsistent" in result.stdout
    assert "published pass lacks completed real browser E2E proof" in result.stdout


def test_flagship_release_readiness_gate_accepts_committed_journey_snapshot_when_external_receipt_is_absent(
    tmp_path: Path,
) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    _write_json(pulse, _passing_pulse(journey_path=journey))
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert '"status": "pass"' in result.stdout


def test_flagship_release_readiness_gate_fails_when_external_receipt_and_snapshot_are_absent(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    pulse_payload = _passing_pulse(journey_path=journey)
    pulse_payload.pop("journey_gate_health", None)
    _write_json(pulse, pulse_payload)
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "journey gates summary missing or invalid" in result.stdout


def test_flagship_release_readiness_gate_rejects_unsourced_journey_snapshot_when_external_receipt_is_absent(
    tmp_path: Path,
) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "missing" / "journey.json"
    scope = tmp_path / "scope.md"
    _write_json(pulse, _passing_pulse())
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    scope.write_text("EA product surface canon under `.codex-design/ea/*`\nmirrored `.codex-design/ea/*`\n", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "journey gates summary missing or invalid" in result.stdout


def test_flagship_release_readiness_gate_rejects_chummer_pulse_and_wrong_product_scope(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.json"
    receipt = tmp_path / "receipt.json"
    browser = tmp_path / "browser.json"
    journey = tmp_path / "journey.json"
    scope = tmp_path / "scope.md"
    pulse_payload = _passing_pulse()
    pulse_payload["contract_name"] = "chummer.weekly_product_pulse"
    pulse_payload["scorecard_source"] = "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml"
    pulse_payload["release_truth_source"] = ""
    _write_json(pulse, pulse_payload)
    _write_json(receipt, _passing_flagship_receipt())
    _write_json(browser, _passing_browser_proof())
    _write_json(journey, {"summary": {"overall_state": "ready", "blocked_count": 0}})
    scope.write_text(
        "# Executive Assistant implementation scope\n\nmirrored `.codex-design/product/*`\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--pulse",
            str(pulse),
            "--flagship-receipt",
            str(receipt),
            "--browser-proof",
            str(browser),
            "--journey-gates",
            str(journey),
            "--implementation-scope",
            str(scope),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode == 1
    assert "expected ea.weekly_product_pulse" in result.stdout
    assert "products/chummer/PRODUCT_HEALTH_SCORECARD.yaml" in result.stdout
    assert "implementation scope no longer requires mirrored .codex-design/ea/* canon" in result.stdout
    assert "implementation scope explicitly names a different product" in result.stdout
