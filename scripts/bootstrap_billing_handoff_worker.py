#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

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


def _cf_headers(env: dict[str, str], *, content_type: str = "application/json") -> dict[str, str]:
    email = str(env.get("CLOUDFLARE_EMAIL") or "").strip()
    api_key = str(env.get("CLOUDFLARE_GLOBAL_API_KEY") or "").strip()
    api_token = str(env.get("CLOUDFLARE_API_TOKEN") or env.get("CF_API_TOKEN") or "").strip()
    if api_token:
        return {"Authorization": f"Bearer {api_token}", "Content-Type": content_type}
    if email and api_key:
        return {
            "X-Auth-Email": email,
            "X-Auth-Key": api_key,
            "Content-Type": content_type,
        }
    raise SystemExit("Cloudflare credentials missing. Set CLOUDFLARE_API_TOKEN or CLOUDFLARE_EMAIL + CLOUDFLARE_GLOBAL_API_KEY.")


def _cf_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    data: bytes | str | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{API_BASE}{path}",
        headers=headers,
        json=payload,
        params=params,
        data=data,
        timeout=30,
    )
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


def _worker_source(*, target_base_url: str) -> str:
    normalized_target = str(target_base_url or "").strip().rstrip("/")
    if not normalized_target.startswith("https://"):
        raise SystemExit("target_base_url must be an https:// URL")
    return (
        "export default {\n"
        "  async fetch(request) {\n"
        f"    const targetBase = {json.dumps(normalized_target)};\n"
        "    const incoming = new URL(request.url);\n"
        "    const destination = new URL(incoming.pathname + incoming.search, targetBase + '/');\n"
        "    return Response.redirect(destination.toString(), 302);\n"
        "  },\n"
        "};\n"
    )


def _upsert_worker_script(
    *,
    account_id: str,
    headers: dict[str, str],
    script_name: str,
    source: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"action": "deploy_script", "script_name": script_name, "dry_run": True}
    response = requests.put(
        f"{API_BASE}/accounts/{account_id}/workers/scripts/{script_name}",
        headers={key: value for key, value in headers.items() if key.lower() != "content-type"},
        files={
            "metadata": (None, json.dumps({"main_module": "worker.mjs"}), "application/json"),
            "worker.mjs": ("worker.mjs", source, "application/javascript+module"),
        },
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise SystemExit(
            f"Cloudflare API error for /accounts/{account_id}/workers/scripts/{script_name}: "
            f"{json.dumps(body.get('errors') or body, ensure_ascii=True)}"
        )
    result = dict(body.get("result") or {})
    return {
        "action": "deploy_script",
        "script_name": script_name,
        "etag": str(result.get("etag") or ""),
        "size": int(result.get("size") or 0),
    }


def _upsert_worker_route(
    *,
    zone_id: str,
    headers: dict[str, str],
    route_pattern: str,
    script_name: str,
    dry_run: bool,
) -> dict[str, Any]:
    route_body = _cf_request(
        "GET",
        f"/zones/{zone_id}/workers/routes",
        headers=headers,
        params={"per_page": 100},
    )
    existing_routes = list(route_body.get("result") or [])
    current = next((row for row in existing_routes if str(row.get("pattern") or "").strip() == route_pattern), None)
    desired = {"pattern": route_pattern, "script": script_name}
    if current is None:
        if dry_run:
            return {"action": "create_route", "pattern": route_pattern, "script": script_name, "dry_run": True}
        body = _cf_request("POST", f"/zones/{zone_id}/workers/routes", headers=headers, payload=desired)
        return {"action": "create_route", "route": body.get("result") or {}}
    current_script = str(current.get("script") or "").strip()
    if current_script == script_name:
        return {"action": "already_ok", "route": current}
    route_id = str(current.get("id") or "").strip()
    if not route_id:
        raise SystemExit(f"Existing worker route for {route_pattern} is missing an id.")
    if dry_run:
        return {"action": "update_route", "pattern": route_pattern, "script": script_name, "dry_run": True}
    body = _cf_request("PUT", f"/zones/{zone_id}/workers/routes/{route_id}", headers=headers, payload=desired)
    return {"action": "update_route", "route": body.get("result") or {}}


def _ensure_dns_record_proxied(
    *,
    zone_id: str,
    headers: dict[str, str],
    host: str,
    target: str,
    dry_run: bool,
) -> dict[str, Any]:
    query = _cf_request(
        "GET",
        f"/zones/{zone_id}/dns_records",
        headers=headers,
        params={"type": "CNAME", "name": host, "per_page": 100},
    )
    existing_records = list(query.get("result") or [])
    current = next(
        (
            row
            for row in existing_records
            if str(row.get("name") or "").strip().lower() == host
            and str(row.get("type") or "").strip().upper() == "CNAME"
        ),
        None,
    )
    desired = {
        "type": "CNAME",
        "name": host,
        "content": target,
        "ttl": 1,
        "proxied": True,
        "comment": "PropertyQuarry Brilliant Directories billing edge handoff",
    }
    if current is None:
        if dry_run:
            return {"action": "create_dns", "host": host, "target": target, "dry_run": True}
        body = _cf_request("POST", f"/zones/{zone_id}/dns_records", headers=headers, payload=desired)
        return {"action": "create_dns", "record": body.get("result") or {}}
    current_content = str(current.get("content") or "").strip().lower().rstrip(".")
    if current_content == target and bool(current.get("proxied")):
        return {"action": "already_ok", "record": current}
    updated = dict(current)
    updated.update(desired)
    record_id = str(current.get("id") or "").strip()
    if not record_id:
        raise SystemExit(f"Existing DNS record for {host} is missing an id.")
    if dry_run:
        return {"action": "update_dns", "host": host, "target": target, "dry_run": True}
    body = _cf_request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", headers=headers, payload=updated)
    return {"action": "update_dns", "record": body.get("result") or {}}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Front billing.propertyquarry.com with a Cloudflare Worker that redirects to the external Brilliant Directories account lane."
    )
    parser.add_argument("--zone-name", default="propertyquarry.com", help="Cloudflare zone to update (default: propertyquarry.com).")
    parser.add_argument("--host", default="billing.propertyquarry.com", help="Billing host to front with the worker.")
    parser.add_argument("--target-host", default="propertyquarry.directoryup.com", help="Current Brilliant Directories host to receive the redirect.")
    parser.add_argument("--script-name", default="propertyquarry-billing-handoff", help="Cloudflare Worker script name.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing Cloudflare state.")
    args = parser.parse_args()

    host = str(args.host or "").strip().lower().rstrip(".")
    target_host = str(args.target_host or "").strip().lower().rstrip(".")
    if not host or not target_host:
        raise SystemExit("Both --host and --target-host are required.")
    route_pattern = f"{host}/*"
    target_base_url = f"https://{target_host}"

    env = _effective_env()
    headers = _cf_headers(env)
    account_id = _discover_account_id(headers=headers, env=env)
    zone_id = _discover_zone_id(account_id=account_id, headers=headers, zone_name=str(args.zone_name or "").strip())
    source = _worker_source(target_base_url=target_base_url)

    script_result = _upsert_worker_script(
        account_id=account_id,
        headers=headers,
        script_name=str(args.script_name or "").strip(),
        source=source,
        dry_run=args.dry_run,
    )
    route_result = _upsert_worker_route(
        zone_id=zone_id,
        headers=headers,
        route_pattern=route_pattern,
        script_name=str(args.script_name or "").strip(),
        dry_run=args.dry_run,
    )
    dns_result = _ensure_dns_record_proxied(
        zone_id=zone_id,
        headers=headers,
        host=host,
        target=target_host,
        dry_run=args.dry_run,
    )

    print(
        json.dumps(
            {
                "account_id": account_id,
                "zone_name": str(args.zone_name or "").strip(),
                "zone_id": zone_id,
                "host": host,
                "route_pattern": route_pattern,
                "target_base_url": target_base_url,
                "script_result": script_result,
                "route_result": route_result,
                "dns_result": dns_result,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
