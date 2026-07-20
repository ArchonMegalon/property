#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "ea" if (ROOT / "ea" / "app").is_dir() else ROOT
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.product.property_tour_ai_panorama_intake import (  # noqa: E402
    AI_PANORAMA_INSTALL_RECEIPT_CONTRACT,
    AiPanoramaIntakeError,
    install_sealed_ai_panorama_bundle,
    load_private_ai_panorama_install_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or atomically install a sealed first-party AI panorama tour "
            "from a private 0600 request."
        )
    )
    parser.add_argument(
        "--request",
        required=True,
        help="Absolute path to the current-EUID-owned 0600/0400 install request JSON.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the exact hash-bound source. Omit for the default read-only dry-run.",
    )
    args = parser.parse_args()
    try:
        request = load_private_ai_panorama_install_request(Path(args.request))
        receipt = install_sealed_ai_panorama_bundle(request, apply=bool(args.apply))
    except AiPanoramaIntakeError as exc:
        print(
            json.dumps(
                {
                    "contract": AI_PANORAMA_INSTALL_RECEIPT_CONTRACT,
                    "status": "failed",
                    "mode": "apply" if args.apply else "dry_run",
                    "error": exc.code,
                    "private_values_redacted": True,
                },
                sort_keys=True,
            )
        )
        return 2
    except Exception:
        # Never let a runtime/filesystem exception serialize the private
        # request, principal, listing URL, or source identity into logs.
        print(
            json.dumps(
                {
                    "contract": AI_PANORAMA_INSTALL_RECEIPT_CONTRACT,
                    "status": "failed",
                    "mode": "apply" if args.apply else "dry_run",
                    "error": "ai_panorama_intake_failed",
                    "private_values_redacted": True,
                },
                sort_keys=True,
            )
        )
        return 3
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
