#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import os
import socket

import requests


API_BASE = "https://api.cloudflare.com/client/v4"
EA_ENV_PATH = Path("/docker/EA/.env")
PROPERTY_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _effective_env() -> dict[str, str]:
    env = _load_env_file(EA_ENV_PATH)
    env.update(_load_env_file(PROPERTY_ENV_PATH))
    for key, value in os.environ.items():
        if value:
            env[key] = value
    return env


def _cf_headers(env: dict[str, str]) -> dict[str, str]:
    email = str(env.get("CLOUDFLARE_EMAIL") or "").strip()
    api_key = str(env.get("CLOUDFLARE_GLOBAL_API_KEY") or "").strip()
    api_token = str(env.get("CLOUDFLARE_API_TOKEN") or env.get("CF_API_TOKEN") or "").strip()
    if api_token:
        return {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    if email and api_key:
        return {
            "X-Auth-Email": email,
            "X-Auth-Key": api_key,
            "Content-Type": "application/json",
        }
    raise SystemExit("Cloudflare credentials missing. Set CLOUDFLARE_API_TOKEN or CLOUDFLARE_EMAIL + CLOUDFLARE_GLOBAL_API_KEY.")


def _cf_request(method: str, path: str, *, headers: dict[str, str], payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.request(method, f"{API_BASE}{path}", headers=headers, json=payload, params=params, timeout=30)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise SystemExit(f"Cloudflare API error for {path}: {json.dumps(body.get('errors') or body, ensure_ascii=True)}")
    return body


def _discover_account_id(*, headers: dict[str, str], env: dict[str, str]) -> str:
    configured = str(env.get("PROPERTYQUARRY_CF_ACCOUNT_ID") or env.get("EA_CF_ACCOUNT_ID") or "").strip()
    if configured:
        return configured
    body = _cf_request("GET", "/accounts", headers=headers)
    accounts = list(body.get("result") or [])
    if len(accounts) != 1:
        summary = ", ".join(f"{item.get('name')}:{item.get('id')}" for item in accounts[:10])
        raise SystemExit(
            f"Could not uniquely determine Cloudflare account. Set PROPERTYQUARRY_CF_ACCOUNT_ID. Visible accounts: {summary}"
        )
    return str(accounts[0].get("id") or "").strip()


def _discover_zone_id(*, account_id: str, headers: dict[str, str], zone_name: str) -> str:
    body = _cf_request(
        "GET",
        "/zones",
        headers=headers,
        params={"name": zone_name, "account.id": account_id, "per_page": 100},
    )
    zones = list(body.get("result") or [])
    if not zones:
        raise SystemExit(f"Cloudflare zone {zone_name!r} not found for account {account_id}")
    return str(zones[0].get("id") or "").strip()


def _ensure_record(
    *,
    zone_id: str,
    headers: dict[str, str],
    host: str,
    target: str,
    dry_run: bool,
    skip_target_check: bool = False,
    proxied: bool = False,
    ttl: int = 1,
) -> dict[str, object]:
    normal_host = str(host or "").strip().lower().rstrip(".")
    normal_target = str(target or "").strip().lower().rstrip(".")
    if not normal_host:
        raise SystemExit("DNS record host is required.")
    if not normal_target:
        raise SystemExit("DNS record target is required.")
    if normal_host.endswith("."):
        normal_host = normal_host.rstrip(".")
    if normal_target.endswith("."):
        normal_target = normal_target.rstrip(".")

    if not skip_target_check:
        try:
            socket.getaddrinfo(normal_target, 443)
        except OSError:
            raise SystemExit(
                f"DNS target {normal_target!r} is not resolvable from this runtime. Confirm the Brilliant Directories white-label CNAME target in Domain Manager."
            )

    query = _cf_request(
        "GET",
        f"/zones/{zone_id}/dns_records",
        headers=headers,
        params={"type": "CNAME", "name": normal_host, "per_page": 100},
    )
    existing_records = list(query.get("result") or [])
    existing = None
    for record in existing_records:
        if str(record.get("type") or "").strip().upper() == "CNAME" and str(record.get("name") or "").strip().lower().rstrip(".") == normal_host:
            existing = record
            break

    desired = {
        "type": "CNAME",
        "name": normal_host,
        "content": normal_target,
        "ttl": ttl,
        "proxied": proxied,
    }

    changed = False
    action = "noop"
    if existing is None:
        action = "create"
        changed = True
        if not dry_run:
            body = _cf_request("POST", f"/zones/{zone_id}/dns_records", headers=headers, payload=desired)
            existing = body.get("result")
    else:
        existing_content = str(existing.get("content") or "").strip().lower().rstrip(".")
        existing_proxied = bool(existing.get("proxied"))
        existing_ttl = int(existing.get("ttl") or 1)
        if existing_content != normal_target or existing_proxied != proxied or existing_ttl != ttl:
            action = "update"
            changed = True
            existing["content"] = normal_target
            existing["proxied"] = proxied
            existing["ttl"] = ttl
            if not dry_run:
                body = _cf_request(
                    "PUT",
                    f"/zones/{zone_id}/dns_records/{existing.get('id')}",
                    headers=headers,
                    payload=existing,
                )
                existing = body.get("result")
        else:
            action = "already_ok"
            existing = existing

    return {
        "action": action,
        "changed": changed,
        "host": normal_host,
        "target": normal_target,
        "record": existing or {},
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure billing CNAME exists for a public billing white-label host in Cloudflare DNS."
    )
    parser.add_argument("--zone-name", default="propertyquarry.com", help="Root zone to update (default: propertyquarry.com).")
    parser.add_argument("--host", default="billing.propertyquarry.com", help="Billing CNAME host (default: billing.propertyquarry.com).")
    parser.add_argument(
        "--target",
        default="",
        help="DNS target for the billing CNAME (e.g. Brilliant Directories Domain Manager target). Required unless PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET is set.",
    )
    parser.add_argument("--ttl", type=int, default=1, help="TTL (default: 1 / Auto).")
    parser.add_argument(
        "--skip-target-check",
        action="store_true",
        help="Write the CNAME record even if the target does not currently resolve from this runtime.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve account/zone and compute action without writing DNS.")
    args = parser.parse_args()

    env = _effective_env()
    headers = _cf_headers(env)
    account_id = _discover_account_id(headers=headers, env=env)
    zone_id = _discover_zone_id(account_id=account_id, headers=headers, zone_name=args.zone_name.strip())
    target = args.target or str(env.get("PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET") or "").strip()
    if not target:
        raise SystemExit("Set --target or PROPERTYQUARRY_BRILLIANT_DIRECTORIES_BILLING_DNS_TARGET before running this script.")

    result = _ensure_record(
        zone_id=zone_id,
        headers=headers,
        host=args.host,
        target=target,
        dry_run=args.dry_run,
        skip_target_check=args.skip_target_check,
        ttl=args.ttl,
        proxied=False,
    )

    print(json.dumps(
        {
            "account_id": account_id,
            "zone_name": args.zone_name.strip(),
            "zone_id": zone_id,
            "result": result,
        },
        ensure_ascii=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
