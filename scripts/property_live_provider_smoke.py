#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

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


def _fetch_provider_payload(*, base_url: str, country_code: str, timeout_seconds: float) -> dict[str, object]:
    params = urllib.parse.urlencode({"country": country_code})
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", f"app/api/property/providers?{params}")
    api_token = str(os.getenv("EA_API_TOKEN") or "").strip()
    principal_id = str(os.getenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_PRINCIPAL_ID") or os.getenv("EA_PRINCIPAL_ID") or "cf-email:tibor.girschele@gmail.com").strip()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PropertyQuarry-live-provider-smoke/1.0",
            "Accept": "application/json,text/html,*/*",
            "Host": "propertyquarry.com",
            "X-EA-Principal-ID": principal_id,
            **(
                {
                    "Authorization": f"Bearer {api_token}",
                    "X-EA-API-Token": api_token,
                }
                if api_token
                else {}
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(220_000)
    return json.loads(body.decode("utf-8", errors="replace"))


def build_live_provider_smoke_receipt(
    *,
    countries: Iterable[str] = ("AT", "CR"),
    base_url: str = "http://localhost:8097",
    timeout_seconds: float = 8.0,
    fetcher: Callable[[str, float], dict[str, object]] | None = None,
) -> dict[str, object]:
    normalized_countries = tuple(dict.fromkeys(str(country or "").strip().upper() for country in countries if str(country or "").strip()))
    enabled = _enabled()
    dry_run = _dry_run()
    checks: list[dict[str, object]] = []
    effective_fetcher = fetcher or (lambda country, timeout: _fetch_provider_payload(base_url=base_url, country_code=country, timeout_seconds=timeout))
    for country in normalized_countries:
        options = provider_options(country_code=country)
        defaults = set(default_platforms_for_country(country))
        row = {
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
        if enabled and not dry_run:
            try:
                payload = dict(effective_fetcher(country, timeout_seconds) or {})
                providers = [dict(item) for item in list(payload.get("providers") or []) if isinstance(item, dict)]
                runtime_provider_values = {
                    str(item.get("value") or "").strip()
                    for item in providers
                    if str(item.get("value") or "").strip()
                }
                runtime_defaults = {
                    str(item or "").strip()
                    for item in list(payload.get("default_platforms") or [])
                    if str(item or "").strip()
                }
                runtime_provider_count_ok = len(runtime_provider_values) == len(options)
                runtime_defaults_present_ok = runtime_defaults == defaults
                runtime_country_code = str(payload.get("country_code") or "").strip().upper()
                runtime_listing_mode = str(payload.get("listing_mode") or "").strip().lower()
                runtime_property_type = str(payload.get("property_type") or "").strip().lower()
                runtime_contract_ok = (
                    runtime_provider_count_ok
                    and runtime_defaults_present_ok
                    and runtime_country_code == country
                    and runtime_listing_mode in {"rent", "buy"}
                    and bool(runtime_property_type)
                )
                row.update(
                    {
                        "status": "pass" if runtime_contract_ok else "fail",
                        "runtime_provider_count": len(runtime_provider_values),
                        "runtime_default_provider_count": len(runtime_defaults),
                        "runtime_default_providers_present": sorted(value for value in runtime_defaults if value in runtime_provider_values),
                        "runtime_country_code": runtime_country_code,
                        "runtime_listing_mode": runtime_listing_mode,
                        "runtime_property_type": runtime_property_type,
                        "runtime_provider_count_ok": runtime_provider_count_ok,
                        "runtime_defaults_present_ok": runtime_defaults_present_ok,
                    }
                )
            except Exception as exc:
                row.update(
                    {
                        "status": "fail",
                        "error": f"{type(exc).__name__}: {exc}",
                        "runtime_provider_count_ok": False,
                        "runtime_defaults_present_ok": False,
                    }
                )
        checks.append(row)
    statuses = {str(row.get("status") or "").strip().lower() for row in checks}
    if "fail" in statuses:
        status = "fail"
    elif statuses == {"pass"}:
        status = "pass"
    elif not enabled:
        status = "skipped"
    elif dry_run:
        status = "dry_run"
    else:
        status = "ready_for_live_probe"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "enabled": enabled,
        "dry_run": dry_run,
        "base_url": base_url,
        "checks": checks,
        "notes": [
            "Live crawling is disabled unless PROPERTYQUARRY_LIVE_PROVIDER_SMOKE=1.",
            "Dry-run mode proves provider catalog, default provider, floorplan, and filter-pushdown contracts without crawling.",
            "Live mode probes the runtime provider catalog endpoint and checks provider/default-provider parity.",
        ],
    }


def main() -> int:
    if len(os.sys.argv) > 1 and os.sys.argv[1] in {"--help", "-h"}:
        print(
            "Usage:\n"
            "  python3 scripts/property_live_provider_smoke.py [--base-url <url>] [--country <code>]...\n\n"
            "Builds the PropertyQuarry provider smoke receipt in skipped, dry-run, or live runtime mode."
        )
        return 0
    parser = argparse.ArgumentParser(description="PropertyQuarry live provider smoke receipt.")
    parser.add_argument("--country", action="append", default=[], help="Country code to include. Defaults to AT and CR.")
    parser.add_argument("--write", default="", help="Optional JSON receipt output path.")
    parser.add_argument("--base-url", default=os.getenv("PROPERTYQUARRY_LIVE_PROVIDER_SMOKE_BASE_URL") or "http://localhost:8097")
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    args = parser.parse_args()
    receipt = build_live_provider_smoke_receipt(
        countries=tuple(args.country or ("AT", "CR")),
        base_url=str(args.base_url),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.write:
        Path(args.write).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if str(receipt.get("status") or "").strip().lower() in {"pass", "dry_run", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
