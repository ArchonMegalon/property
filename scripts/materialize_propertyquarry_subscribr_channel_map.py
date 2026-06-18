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

from app.domain.property.content_source_packet import SUBSCRIBR_CHANNELS_BY_MODE, now_utc_iso, sha256_json  # noqa: E402


DEFAULT_CHANNEL_MAP = {
    "propertyquarry-official": 201,
    "propertyquarry-academy": 202,
    "propertyquarry-renters-eu": 203,
    "propertyquarry-buyers-eu": 204,
    "propertyquarry-investment-education": 205,
    "propertyquarry-relocation": 206,
    "propertyquarry-at-de": 207,
    "propertyquarry-de-de": 208,
    "propertyquarry-ch-de": 209,
    "propertyquarry-uk-en": 210,
    "propertyquarry-us-en": 211,
    "propertyquarry-dossier-lab": 212,
    "propertyquarry-content-lab": 213,
}


def main() -> int:
    raw = str(os.getenv("SUBSCRIBR_PROPERTY_CHANNEL_MAP_JSON") or "").strip()
    channel_map = DEFAULT_CHANNEL_MAP
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise SystemExit("SUBSCRIBR_PROPERTY_CHANNEL_MAP_JSON must be an object")
        channel_map = {str(key): value for key, value in parsed.items()}
    required = set(SUBSCRIBR_CHANNELS_BY_MODE.values()) | {"propertyquarry-official", "propertyquarry-buyers-eu"}
    missing = sorted(required - set(channel_map.keys()))
    payload = {
        "contract_name": "propertyquarry.subscribr_channel_map.v1",
        "generated_at": now_utc_iso(),
        "status": "pass" if not missing else "missing_channels",
        "missing_channels": missing,
        "channel_map": channel_map,
        "channel_map_sha256": sha256_json(channel_map),
        "direct_publish_enabled": False,
    }
    out_dir = Path(os.getenv("PROPERTYQUARRY_SUBSCRIBR_COMPLETION_DIR") or ROOT / "_completion" / "subscribr")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "SUBSCRIBR_CHANNEL_MAP.generated.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

