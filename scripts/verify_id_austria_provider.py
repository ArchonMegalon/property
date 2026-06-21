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

from app.services.id_austria_oidc import load_id_austria_oidc_config  # noqa: E402


_CONFIG_KEYS = (
    "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_ID",
    "PROPERTYQUARRY_ID_AUSTRIA_CLIENT_SECRET",
    "PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI",
    "PROPERTYQUARRY_ID_AUSTRIA_STATE_SECRET",
)


def _env_truth(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def build_id_austria_verification_receipt() -> dict[str, object]:
    required = _env_truth("PROPERTYQUARRY_ID_AUSTRIA_REQUIRED")
    missing = tuple(key for key in _CONFIG_KEYS if not str(os.getenv(key) or "").strip())
    try:
        config = load_id_austria_oidc_config()
    except RuntimeError as exc:
        return {
            "contract_name": "propertyquarry.id_austria_provider_verification.v1",
            "provider": "id_austria",
            "status": "blocked_missing_configuration" if required else "disabled",
            "required": required,
            "configured": False,
            "missing_env": list(missing),
            "error": str(exc or "id_austria_not_configured"),
            "redirect_uri": str(os.getenv("PROPERTYQUARRY_ID_AUSTRIA_REDIRECT_URI") or "").strip(),
        }
    return {
        "contract_name": "propertyquarry.id_austria_provider_verification.v1",
        "provider": "id_austria",
        "status": "dry_verified_configured",
        "required": required,
        "configured": True,
        "missing_env": [],
        "issuer": config.issuer,
        "authorization_endpoint": config.authorization_endpoint,
        "token_endpoint": config.token_endpoint,
        "jwks_uri": config.jwks_uri,
        "redirect_uri": config.redirect_uri,
    }


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
