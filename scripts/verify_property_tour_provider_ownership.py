#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


def _presence(value: str) -> dict[str, object]:
    return {
        "present": bool(value),
        "length": len(value),
        "hash": _hash(value),
    }


def build_property_tour_provider_ownership_receipt(
    *,
    three_dvista_invoice_ids: tuple[str, ...] = ("60076", "60074"),
    pano2vr_order_id: str = "38984",
    pano2vr_product_id: str = "nferpd44",
) -> dict[str, Any]:
    three_dvista_email = _env("THREEDVISTA_LOGIN_EMAIL") or _env("THREEDVISTA_LICENSE_EMAIL")
    three_dvista_password = _env("THREEDVISTA_LOGIN_PASSWORD")
    pano2vr_email = _env("PANO2VR_EMAIL")
    pano2vr_license = _env("PANO2VR_LICENSE_KEY")
    providers = {
        "3dvista": {
            "status": "owned_configured" if three_dvista_email and three_dvista_password and three_dvista_invoice_ids else "missing_config",
            "account_email_hash": _hash(three_dvista_email),
            "login_email_present": bool(three_dvista_email),
            "password_present": bool(three_dvista_password),
            "invoice_ids": list(three_dvista_invoice_ids),
            "owned_products": ["3DVista VT Pro", "Branded Pack"],
            "login_verified": False,
            "export_verified": False,
            "private_viewer_verified": False,
            "next_action": "verify control-panel login, complete branded/private viewer setup, and import a real 3DVista export or allowlisted hosted 3DVista URL",
        },
        "pano2vr": {
            "status": "owned_configured" if pano2vr_email and pano2vr_license and pano2vr_order_id and pano2vr_product_id else "missing_config",
            "account_email_hash": _hash(pano2vr_email),
            "account_email_present": bool(pano2vr_email),
            "license_key": _presence(pano2vr_license),
            "order_id": pano2vr_order_id,
            "product_id": pano2vr_product_id,
            "owned_products": ["Pano2VR 8 Pro"],
            "account_verified": False,
            "export_verified": False,
            "next_action": "open Pano2VR, create a real export, and import the complete output folder or zip into the verified tour drop",
        },
    }
    required = ("3dvista", "pano2vr")
    missing = [
        provider
        for provider in required
        if providers[provider]["status"] != "owned_configured"
    ]
    return {
        "generated_at": _utc_now(),
        "status": "pass" if not missing else "blocked_missing_config",
        "providers": providers,
        "missing_providers": missing,
        "privacy": {
            "secrets_in_receipt": False,
            "omitted": [
                "passwords",
                "raw license keys",
                "invoice signatures",
                "private invoice links",
                "reset tokens",
                "cookies",
            ],
        },
        "notes": [
            "This receipt proves ownership/config readiness only.",
            "It does not satisfy gold tour readiness without verified 3DVista/Pano2VR exports or allowlisted hosted controls.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local 3DVista/Pano2VR ownership/config readiness without leaking secrets.")
    parser.add_argument("--write", default="_completion/property_tour_ownership/release-gate.json")
    parser.add_argument("--three-dvista-invoice-id", action="append", default=[], help="Non-secret 3DVista invoice id to record.")
    parser.add_argument("--pano2vr-order-id", default="38984")
    parser.add_argument("--pano2vr-product-id", default="nferpd44")
    args = parser.parse_args()
    receipt = build_property_tour_provider_ownership_receipt(
        three_dvista_invoice_ids=tuple(args.three_dvista_invoice_id or ("60076", "60074")),
        pano2vr_order_id=str(args.pano2vr_order_id),
        pano2vr_product_id=str(args.pano2vr_product_id),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
