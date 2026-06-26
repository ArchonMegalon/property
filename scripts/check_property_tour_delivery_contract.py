#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_MODES = ("matterport", "3dvista", "pano2vr", "krpano", "magicfit")
REQUIRED_CONTRACT_KEYS = (
    "schema",
    "provider",
    "status",
    "ready_payload",
    "blocked_reason",
    "required_to_send",
    "white_label_contract",
    "notes",
)
FORBIDDEN_PUBLIC_SAFE_TOKENS = (
    "source_virtual_tour_url",
    "my.matterport.com/show",
    "crezlo_public_url",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "missing", "path": str(path)}
    except Exception as exc:
        return {"status": "invalid", "path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    return payload if isinstance(payload, dict) else {"status": "invalid", "path": str(path), "error": "json_root_not_object"}


def _latest_receipt_path() -> Path:
    candidates: list[Path] = []
    for pattern in (
        "_completion/tours/property-tour-controls*.json",
        "_completion/property_tour_controls/*.json",
    ):
        candidates.extend(path for path in ROOT.glob(pattern) if path.is_file())
    if not candidates:
        return ROOT / "_completion/tours/property-tour-controls-live-container-current.json"

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            payload = _load_json(path)
            raw = str(payload.get("generated_at") or "").strip()
            if raw.endswith("Z"):
                raw = f"{raw[:-1]}+00:00"
            generated_at = datetime.fromisoformat(raw).timestamp() if raw else 0.0
        except Exception:
            generated_at = 0.0
        return (generated_at or path.stat().st_mtime, path.as_posix())

    return max(candidates, key=sort_key)


def _contract_blob(contract: dict[str, Any]) -> str:
    return json.dumps(contract, sort_keys=True, ensure_ascii=False).lower()


def _check_white_label_contract(provider: str, contract: dict[str, Any], failures: list[str]) -> None:
    white_label = contract.get("white_label_contract")
    if not isinstance(white_label, dict):
        failures.append(f"{provider} white_label_contract must be an object")
        return
    if white_label.get("schema") != "propertyquarry.tour_white_label_contract.v1":
        failures.append(f"{provider} white_label_contract schema mismatch")
    if white_label.get("provider") != provider:
        failures.append(f"{provider} white_label_contract provider mismatch")
    if white_label.get("source_project") != "propertyquarry":
        failures.append(f"{provider} white_label_contract must declare source_project=propertyquarry")
    status = str(white_label.get("status") or "").strip()
    if status not in {"ready", "blocked", "review_required"}:
        failures.append(f"{provider} white_label_contract status must be ready, blocked, or review_required")
    requirements = list(white_label.get("required_to_white_label") or [])
    if status == "ready" and requirements:
        failures.append(f"{provider} ready white_label_contract must not require extra white-label actions")
    if status != "ready" and not requirements:
        failures.append(f"{provider} blocked/review white_label_contract must explain required white-label actions")
    if provider == "3dvista" and "Chummer RunSite/Horizon" not in str(white_label.get("cross_project_warning") or ""):
        failures.append("3dvista white_label_contract must preserve Chummer RunSite/Horizon separation warning")


def _check_ready_contract(provider: str, contract: dict[str, Any], failures: list[str]) -> None:
    if contract.get("status") != "ready":
        failures.append(f"{provider} ready provider mode must have delivery status=ready")
    if str(contract.get("blocked_reason") or "").strip():
        failures.append(f"{provider} ready provider mode must have empty blocked_reason")
    if list(contract.get("required_to_send") or []):
        failures.append(f"{provider} ready provider mode must have empty required_to_send")
    ready_payload = contract.get("ready_payload")
    if not isinstance(ready_payload, dict):
        failures.append(f"{provider} ready_payload must be an object")
        return
    if ready_payload.get("provider") != provider:
        failures.append(f"{provider} ready_payload provider mismatch")
    if int(ready_payload.get("ready_count") or 0) <= 0:
        failures.append(f"{provider} ready_payload must prove at least one ready control")
    sample_controls = [row for row in list(ready_payload.get("sample_controls") or []) if isinstance(row, dict)]
    if not sample_controls:
        failures.append(f"{provider} ready_payload must include public-safe sample_controls")
    for row in sample_controls[:5]:
        control_path = str(row.get("control_path") or "").strip()
        if provider == "magicfit":
            if not control_path.startswith("/tours/files/"):
                failures.append("magicfit sample control must use a hosted /tours/files/ playback path")
        elif control_path and not control_path.endswith(f"/control/{provider}"):
            failures.append(f"{provider} sample control path must end with /control/{provider}")
        if not str(row.get("evidence") or "").strip():
            failures.append(f"{provider} sample control must expose public-safe evidence label")


def _check_blocked_contract(provider: str, contract: dict[str, Any], failures: list[str]) -> None:
    if contract.get("status") != "blocked":
        failures.append(f"{provider} missing provider mode must have delivery status=blocked")
    if not str(contract.get("blocked_reason") or "").strip():
        failures.append(f"{provider} blocked contract must expose blocked_reason")
    if not list(contract.get("required_to_send") or []):
        failures.append(f"{provider} blocked contract must expose required_to_send")


def build_tour_delivery_contract_receipt(tour_control_receipt_path: Path | None = None) -> dict[str, object]:
    receipt_path = (tour_control_receipt_path or _latest_receipt_path()).resolve()
    tour_control = _load_json(receipt_path)
    failures: list[str] = []
    contracts = tour_control.get("delivery_contracts")
    if not isinstance(contracts, dict):
        failures.append("tour control receipt must expose delivery_contracts")
        contracts = {}

    ready_modes = {
        str(provider or "").strip().lower()
        for provider in list(tour_control.get("ready_provider_modes") or [])
        if str(provider or "").strip()
    }
    missing_modes = {
        str(provider or "").strip().lower()
        for provider in list(tour_control.get("missing_provider_modes") or [])
        if str(provider or "").strip()
    }

    for provider in PROVIDER_MODES:
        contract = contracts.get(provider)
        if not isinstance(contract, dict):
            failures.append(f"delivery_contracts missing provider {provider}")
            continue
        for key in REQUIRED_CONTRACT_KEYS:
            if key not in contract:
                failures.append(f"{provider} delivery contract missing key {key}")
        if contract.get("schema") != "propertyquarry.tour_delivery_contract.v1":
            failures.append(f"{provider} delivery contract schema mismatch")
        if contract.get("provider") != provider:
            failures.append(f"{provider} delivery contract provider mismatch")
        notes = " ".join(str(item) for item in list(contract.get("notes") or []))
        if "PropertyQuarry remains source of truth" not in notes:
            failures.append(f"{provider} delivery contract must preserve source-of-truth separation note")
        for forbidden in FORBIDDEN_PUBLIC_SAFE_TOKENS:
            if forbidden in _contract_blob(contract):
                failures.append(f"{provider} public-safe delivery contract leaks forbidden token {forbidden}")
        _check_white_label_contract(provider, contract, failures)
        if provider in ready_modes:
            _check_ready_contract(provider, contract, failures)
        if provider in missing_modes:
            _check_blocked_contract(provider, contract, failures)

    matterport = contracts.get("matterport") if isinstance(contracts.get("matterport"), dict) else {}
    matterport_payload = matterport.get("ready_payload") if isinstance(matterport, dict) else {}
    if "matterport" not in ready_modes:
        failures.append("Matterport must remain a first-class ready provider mode")
    elif int(dict(matterport_payload or {}).get("ready_count") or 0) <= 0:
        failures.append("Matterport must prove at least one ready hosted control")

    return {
        "schema": "propertyquarry.tour_delivery_contract_shape_receipt.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "pass" if not failures else "fail",
        "tour_control_receipt_path": str(receipt_path),
        "required_providers": list(PROVIDER_MODES),
        "ready_provider_modes": sorted(ready_modes),
        "missing_provider_modes": sorted(missing_modes),
        "matterport_ready_count": int(dict(matterport_payload or {}).get("ready_count") or 0),
        "failure_count": len(failures),
        "failures": failures,
        "note": "Verifies public-safe tour delivery contracts, Chummer-derived ready/blocker vocabulary, white-label separation, and first-class Matterport readiness.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check PropertyQuarry tour delivery contract shape.")
    parser.add_argument("--tour-control-receipt", default="", help="Tour-control receipt to inspect.")
    parser.add_argument("--write", default="", help="Optional path for a JSON receipt.")
    args = parser.parse_args()

    receipt = build_tour_delivery_contract_receipt(
        Path(args.tour_control_receipt) if args.tour_control_receipt else None
    )
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failures = list(receipt.get("failures") or [])
    if failures:
        print("property tour delivery contract check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property tour delivery contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
