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

from app.services.id_austria_oidc import id_austria_provider_readiness  # noqa: E402


def build_id_austria_verification_receipt() -> dict[str, object]:
    readiness = id_austria_provider_readiness()
    receipt = {
        "contract_name": "propertyquarry.id_austria_provider_verification.v1",
        "provider": "id_austria",
        "status": readiness.get("id_austria_sign_in_status", "disabled"),
        "required": readiness.get("id_austria_sign_in_required") == "true",
        "configured": readiness.get("id_austria_sign_in_configured") == "true",
        "missing_env": [
            value
            for value in str(readiness.get("id_austria_sign_in_missing_env") or "").split(",")
            if value
        ],
        "error": readiness.get("id_austria_sign_in_error", ""),
        "issuer": readiness.get("id_austria_issuer", ""),
        "authorization_endpoint": readiness.get("id_austria_authorization_endpoint", ""),
        "token_endpoint": readiness.get("id_austria_token_endpoint", ""),
        "jwks_uri": readiness.get("id_austria_jwks_uri", ""),
        "redirect_uri": readiness.get("id_austria_redirect_uri", ""),
    }
    return receipt


def main() -> int:
    out_dir = Path(os.getenv("PROPERTYQUARRY_ID_AUSTRIA_COMPLETION_DIR") or ROOT / "_completion" / "id_austria")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ID_AUSTRIA_PROVIDER_VERIFICATION.generated.json"
    payload = build_id_austria_verification_receipt()
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if payload.get("status") in {"disabled", "dry_verified_configured"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
