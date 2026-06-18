#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a PropertyQuarry Subscribr script receipt.")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    validation = receipt.get("validation") if isinstance(receipt, dict) else {}
    failures = {
        key: value
        for key, value in dict(validation or {}).items()
        if value not in {"pass", "review_required"}
    }
    if receipt.get("contract_name") != "propertyquarry.subscribr_script_draft.v1":
        failures["contract_name"] = "invalid"
    if receipt.get("publication_allowed") is not False or receipt.get("production_allowed") is not False:
        failures["publication_gate"] = "invalid"
    if receipt.get("human_review", {}).get("status") != "pending":
        failures["human_review"] = "invalid"
    print(json.dumps({"status": "pass" if not failures else "fail", "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

