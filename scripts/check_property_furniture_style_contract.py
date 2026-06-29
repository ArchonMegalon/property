#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_STYLES = {
    "warm_scandi": ("Warm Scandinavian", "warm Scandinavian staging"),
    "ikea_practical": ("IKEA practical", "IKEA-inspired practical modular furniture"),
    "urban_jungle": ("Urban jungle", "urban jungle interior"),
    "landhaus": ("Landhaus", "Austrian Landhaus"),
    "gilded_penthouse": ("Trump gold", "Trump-style gold maximalist penthouse staging"),
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def build_furniture_style_contract_receipt() -> dict[str, object]:
    failures: list[str] = []
    view_models = _read("ea/app/api/routes/landing_view_models.py")
    billing = _read("ea/app/services/property_billing.py")
    workbench = _read("ea/app/templates/app/property_decision_workbench.html")
    workbench_script = _read("ea/app/templates/app/_property_workbench_script.html")
    research_detail = _read("ea/app/templates/app/property_research_detail.html")
    service = _read("ea/app/product/service.py")

    for value, (label, prompt_token) in REQUIRED_STYLES.items():
        if f'"value": "{value}"' not in view_models:
            failures.append(f"furniture style catalog missing value {value}")
        if label not in view_models:
            failures.append(f"furniture style catalog missing label {label}")
        if prompt_token not in view_models:
            failures.append(f"furniture style catalog missing prompt token for {value}")
    for token in ("example_tone", "example_caption"):
        if token not in view_models:
            failures.append(f"furniture style catalog missing {token}")
    if "return 5" not in billing:
        failures.append("property_furniture_style_cap must allow every tier to choose all request-time styles")
    for token in ("furniture_style_limit=5",):
        if token not in billing:
            failures.append(f"plan catalog missing {token}")
    for token in ('name="furniture_style"', "data-furniture-style-select", "data-furniture-style-card", "field.name == 'furniture_style'"):
        if token not in workbench:
            continue
        failures.append(f"search brief must not render furniture style filter token {token}")
    for token in ("furniture_style_catalog", "chooseFurnitureStyleForVisualRequest", "data-pqx-visual-style-dialog", "diorama_style_hint: dioramaStyleHint"):
        if token not in workbench_script:
            failures.append(f"workbench script style handoff missing {token}")
    for token in ("data-prd-visual-style-dialog", "data-prd-style-option", "data-pw-visual-style-required", "chooseVisualStyleForRequest", "diorama_style_hint: dioramaStyleHint"):
        if token not in research_detail:
            failures.append(f"research detail request-time style chooser missing {token}")
    service_tokens = (
        "styling_hint: str = \"\"",
        "normalized_style = compact_text",
        "candidate_rows = [",
        "styling_hint=styling_hint",
        "requested furniture style:",
        "normalized_diorama_style_hint",
    )
    for token in service_tokens:
        if token not in service:
            failures.append(f"MagicFit/furnished-scene style-aware cache wiring missing {token}")

    return {
        "schema": "propertyquarry.furniture_style_contract_receipt.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "pass" if not failures else "fail",
        "style_count": len(REQUIRED_STYLES),
        "style_values": sorted(REQUIRED_STYLES),
        "plan_caps": {"free": 5, "plus": 5, "agent": 5},
        "failure_count": len(failures),
        "failures": failures,
        "note": "Verifies furniture-style catalog, request-time 3D-tour and walkthrough style choice, UI handoff, and style-aware rendered-scene cache reuse.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check PropertyQuarry furnished-style variant contract.")
    parser.add_argument("--write", default="", help="Optional path for a JSON receipt.")
    args = parser.parse_args()

    receipt = build_furniture_style_contract_receipt()
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failures = list(receipt.get("failures") or [])
    if failures:
        print("property furniture style contract check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property furniture style contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
