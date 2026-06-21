#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (ROOT, EA_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services.brilliant_directories import build_brilliant_directories_verification_receipt  # noqa: E402


def main() -> int:
    out_dir = Path(
        os.getenv("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_COMPLETION_DIR")
        or ROOT / "_completion" / "brilliant_directories"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "BRILLIANT_DIRECTORIES_PROVIDER_VERIFICATION.generated.json"
    payload = build_brilliant_directories_verification_receipt()
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if payload.get("status") in {"disabled", "dry_verified_configured"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
