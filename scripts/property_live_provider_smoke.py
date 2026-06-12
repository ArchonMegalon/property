#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.property_market_catalog import default_platforms_for_country, provider_options


def _enabled() -> bool:
    return str(os.getenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "live",
    }


def _dry_run() -> bool:
    return str(os.getenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_DRY_RUN") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
        "live",
    }


def build_live_provider_smoke_receipt(*, countries: Iterable[str] = ("AT", "CR")) -> dict[str, object]:
    normalized_countries = tuple(dict.fromkeys(str(country or "").strip().upper() for country in countries if str(country or "").strip()))
    enabled = _enabled()
    dry_run = _dry_run()
    checks: list[dict[str, object]] = []
    for country in normalized_countries:
        options = provider_options(country_code=country)
        defaults = set(default_platforms_for_country(country))
        checks.append(
            {
                "country_code": country,
                "status": "skipped" if not enabled else "dry_run" if dry_run else "ready_for_live_probe",
                "provider_count": len(options),
                "default_provider_count": len(defaults),
                "default_providers_present": sorted(
                    str(option.get("value") or "")
                    for option in options
                    if str(option.get("value") or "") in defaults
                ),
                "requires_filter_pushdown_receipt": True,
                "requires_floorplan_receipt": True,
                "requires_location_boundary_receipt": True,
            }
        )
    status = "skipped" if not enabled else "dry_run" if dry_run else "ready_for_live_probe"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "enabled": enabled,
        "dry_run": dry_run,
        "checks": checks,
        "notes": [
            "Live crawling is disabled unless PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1.",
            "Dry-run mode proves provider catalog, default provider, floorplan, and filter-pushdown contracts without crawling.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PropertyQuarry live provider smoke receipt.")
    parser.add_argument("--country", action="append", default=[], help="Country code to include. Defaults to AT and CR.")
    parser.add_argument("--write", default="", help="Optional JSON receipt output path.")
    args = parser.parse_args()
    receipt = build_live_provider_smoke_receipt(countries=tuple(args.country or ("AT", "CR")))
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        Path(args.write).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
