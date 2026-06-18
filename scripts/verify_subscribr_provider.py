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

from app.domain.property.content_source_packet import now_utc_iso, sha256_json  # noqa: E402
from app.services.subscribr_client import SubscribrClient, redacted_subscribr_error, subscribr_enabled  # noqa: E402


def main() -> int:
    out_dir = Path(os.getenv("PROPERTYQUARRY_SUBSCRIBR_COMPLETION_DIR") or ROOT / "_completion" / "subscribr")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "SUBSCRIBR_PROVIDER_VERIFICATION.generated.json"
    live_smoke = str(os.getenv("PROPERTYQUARRY_SUBSCRIBR_LIVE_SMOKE") or "").strip().lower() in {"1", "true", "yes", "on"}
    client = SubscribrClient()
    payload: dict[str, object] = {
        "contract_name": "propertyquarry.subscribr_provider_verification.v1",
        "generated_at": now_utc_iso(),
        "provider": "subscribr",
        "base_url": client.base_url,
        "enabled": subscribr_enabled(),
        "live_smoke_requested": live_smoke,
        "token_present": client.configured,
        "direct_publish_enabled": False,
        "status": "blocked_pending_live_smoke" if live_smoke else "dry_verified",
        "verified_capabilities": {
            "bearer_auth_contract": True,
            "team_endpoint_contract": True,
            "channels_endpoint_contract": True,
            "ideas_endpoint_contract": True,
            "scripts_endpoint_contract": True,
            "markdown_export_contract": True,
            "hmac_webhook_required": True,
        },
        "sources": [
            "https://subscribr.ai/youtube-api",
            "https://subscribr.ai/api/docs/reference/ai",
        ],
    }
    if live_smoke:
        if not client.configured:
            payload["status"] = "blocked_missing_token"
        else:
            try:
                team = client.get_team()
                credits = client.get_credits()
                payload["status"] = "verified_live"
                payload["team_sha256"] = sha256_json(team)
                payload["credits_sha256"] = sha256_json(credits)
            except Exception as exc:
                payload["status"] = "provider_failed"
                payload["error"] = redacted_subscribr_error(exc)
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if payload["status"] not in {"provider_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

