from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_RELEASE_GATE.json"
TRUTH_PLANE_PATH = ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_TRUTH_PLANE.md"
IMPLEMENTATION_SCOPE_PATH = ROOT / ".codex-design" / "repo" / "IMPLEMENTATION_SCOPE.md"
GENERATED_GATE_PATH = ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json"
RELEASE_CHECKLIST_PATH = ROOT / "RELEASE_CHECKLIST.md"
PRODUCT_RELEASE_CHECKLIST_PATH = ROOT / "PRODUCT_RELEASE_CHECKLIST.md"
README_PATH = ROOT / "README.md"
RUNBOOK_PATH = ROOT / "RUNBOOK.md"
CLOSEOUT_PLAN_PATH = ROOT / "FLAGSHIP_CLOSEOUT_PLAN.md"
VERIFY_RELEASE_ASSETS_PATH = ROOT / "scripts" / "verify_release_assets.sh"


def test_flagship_truth_plane_seed_points_at_browser_workflow_proof() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))

    assert gate["product"] == "propertyquarry"
    assert gate["surface"] == "propertyquarry_flagship_release_control"
    assert gate["truth_plane"]["source"] == ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md"
    assert gate["truth_plane"]["legacy_history"] == "MILESTONE.json"

    browser_proof = gate["browser_workflow_proof"]["evidence_sources"]
    evidence_index = {entry["file"]: set(entry["cases"]) for entry in browser_proof}

    assert gate["browser_workflow_proof"]["proof_target"] == "propertyquarry"
    assert "tests/test_propertyquarry_workspace_redesign.py" in evidence_index
    assert "tests/e2e/test_propertyquarry_greenfield_browser.py" in evidence_index
    assert (
        "test_propertyquarry_workspace_routes_render_greenfield_surfaces"
        in evidence_index["tests/test_propertyquarry_workspace_redesign.py"]
    )
    assert (
        "test_propertyquarry_failed_run_stays_on_activity_surface"
        in evidence_index["tests/test_propertyquarry_workspace_redesign.py"]
    )
    assert (
        "test_propertyquarry_greenfield_workspace_in_real_browser"
        in evidence_index["tests/e2e/test_propertyquarry_greenfield_browser.py"]
    )
    assert (
        "test_propertyquarry_greenfield_workspace_is_mobile_usable"
        in evidence_index["tests/e2e/test_propertyquarry_greenfield_browser.py"]
    )

    conditions = gate["release_claim"]["required_conditions"]
    assert any("EA product surface canon exists" in condition for condition in conditions)
    assert any("PropertyQuarry" in condition for condition in conditions)
    assert any("release asset verification" in condition for condition in conditions)
    assert any("MILESTONE green" in condition or "MILESTONE" in condition for condition in conditions)
    assert not any("parity-oracle" in condition for condition in conditions)
    assert not any("noise-auditor" in condition for condition in conditions)

    expected_signals = gate["browser_workflow_proof"]["expected_browser_signals"]
    assert any("/app/properties" in signal for signal in expected_signals)
    assert any("ranked" in signal.lower() for signal in expected_signals)
    assert any("/app/research/" in signal for signal in expected_signals)
    assert any("mobile" in signal.lower() for signal in expected_signals)

    canon = gate["ea_product_canon"]
    assert canon["source_root"] == ".codex-design/ea"
    assert canon["scope_label"] == "EA product surface canon"
    assert ".codex-design/ea/START_HERE.md" in canon["required_docs"]
    assert ".codex-design/ea/SURFACE_DESIGN_SYSTEM.md" in canon["required_docs"]
    assert ".codex-design/ea/LTD_INTEGRATION_MAP.md" in canon["required_docs"]


def test_flagship_release_docs_cite_the_truth_plane_instead_of_milestone_as_oracle() -> None:
    truth_plane = TRUTH_PLANE_PATH.read_text(encoding="utf-8")
    implementation_scope = IMPLEMENTATION_SCOPE_PATH.read_text(encoding="utf-8")
    release_checklist = RELEASE_CHECKLIST_PATH.read_text(encoding="utf-8")
    product_release_checklist = PRODUCT_RELEASE_CHECKLIST_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in truth_plane
    assert "tests/test_propertyquarry_workspace_redesign.py" in truth_plane
    assert "tests/e2e/test_propertyquarry_greenfield_browser.py" in truth_plane
    assert "legacy assistant browser files are intentionally skipped" in truth_plane
    assert ".codex-design/ea/START_HERE.md" in truth_plane
    assert "MILESTONE.json" in truth_plane
    assert ".codex-design/ea/*" in implementation_scope
    assert "EA product surface canon under `.codex-design/ea/*`" in implementation_scope
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in release_checklist
    assert ".codex-design/ea/START_HERE.md" in release_checklist
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in product_release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in product_release_checklist
    assert ".codex-design/ea/START_HERE.md" in product_release_checklist
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in product_release_checklist
    assert ".codex-design/ea/START_HERE.md" in readme
    assert ".codex-design/ea/SURFACE_DESIGN_SYSTEM.md" in readme
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in readme
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in readme
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in readme
    assert "scripts/materialize_ea_flagship_release_gate.py" in readme
    assert ".codex-design/ea/START_HERE.md" in runbook
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in runbook
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in runbook
    assert "scripts/materialize_ea_flagship_release_gate.py" in runbook


def test_flagship_release_receipt_is_materialized_or_expected_to_materialize() -> None:
    assert GENERATED_GATE_PATH.exists()
    receipt = json.loads(GENERATED_GATE_PATH.read_text(encoding="utf-8"))

    assert receipt["readiness_scope"] == "source_and_browser_proof"
    assert receipt["live_readiness"] == {
        "status": "not_evaluated",
        "authority": "_completion/property_gold_status/release-gate.json",
        "required_profile": "launch",
    }
    assert "final live readiness is not evaluated" in receipt["operator_summary"].lower()


def test_flagship_closeout_claim_is_scoped_to_the_proven_propertyquarry_surface() -> None:
    closeout = CLOSEOUT_PLAN_PATH.read_text(encoding="utf-8")

    assert "# Standalone PropertyQuarry Flagship Closeout Plan" in closeout
    assert "cannot establish Executive Assistant core eligibility" in closeout
    assert "tests/test_propertyquarry_workspace_redesign.py" in closeout
    assert "tests/e2e/test_propertyquarry_greenfield_browser.py" in closeout
    assert "Executive Assistant core is flagship-release eligible" not in closeout


def test_release_asset_verifier_binds_generated_receipts_to_current_propertyquarry_seed() -> None:
    verifier = VERIFY_RELEASE_ASSETS_PATH.read_text(encoding="utf-8")

    assert 'assert gate["product"] == "propertyquarry"' in verifier
    assert 'assert gate["surface"] == "propertyquarry_flagship_release_control"' in verifier
    assert 'browser_receipt_pass_blockers(browser_receipt, gate)' in verifier
    assert 'assert browser_receipt["product"] == gate["product"]' in verifier
    assert 'assert flagship_receipt["product"] == gate["product"]' in verifier
    assert 'assert flagship_receipt["readiness_scope"] == "source_and_browser_proof"' in verifier
    assert '"authority": "_completion/property_gold_status/release-gate.json"' in verifier
    assert '"required_profile": "launch"' in verifier
    assert '"docs/PROPERTYQUARRY_RELEASE_MANIFEST.md",' in verifier
