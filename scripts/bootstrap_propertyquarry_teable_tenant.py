#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))

from app.services.propertyquarry_teable_projection import (  # noqa: E402
    PROPERTYQUARRY_TEABLE_TABLE_FIELDS,
    PROPERTYQUARRY_TEABLE_TABLE_NAMES,
    propertyquarry_teable_tenant_key,
    propertyquarry_teable_tenant_name,
)


DEFAULT_ENV_FILES = (
    Path("/docker/property/.env"),
    Path("/docker/EA/.env"),
)


def _load_env_files(*paths: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in loaded:
                continue
            loaded[key] = value.strip().strip("'").strip('"')
    return loaded


def _env_value(name: str, defaults: dict[str, str], fallback: str = "") -> str:
    return str(os.environ.get(name) or defaults.get(name) or fallback).strip()


def parse_args() -> argparse.Namespace:
    defaults = _load_env_files(*DEFAULT_ENV_FILES)
    parser = argparse.ArgumentParser(description="Bootstrap the PropertyQuarry Teable tenant/base and table mapping.")
    parser.add_argument("--base-url", default=_env_value("TEABLE_BASE_URL", defaults, "https://app.teable.ai"))
    parser.add_argument("--api-key", default=_env_value("TEABLE_API_KEY", defaults))
    parser.add_argument("--space-id", default=_env_value("PROPERTYQUARRY_TEABLE_SPACE_ID", defaults) or _env_value("TEABLE_SPACE_ID", defaults))
    parser.add_argument("--base-id", default=_env_value("PROPERTYQUARRY_TEABLE_BASE_ID", defaults))
    parser.add_argument("--base-name", default=_env_value("PROPERTYQUARRY_TEABLE_TENANT_NAME", defaults, propertyquarry_teable_tenant_name()))
    parser.add_argument("--tenant-key", default=_env_value("PROPERTYQUARRY_TEABLE_TENANT_KEY", defaults, propertyquarry_teable_tenant_key()))
    parser.add_argument("--create-base", action="store_true")
    parser.add_argument("--create-tables", action="store_true")
    parser.add_argument("--write-env", action="store_true")
    parser.add_argument("--env-file", default="/docker/property/.env")
    return parser.parse_args()


def _request_json(
    *,
    method: str,
    url: str,
    api_key: str,
    body: dict[str, object] | None = None,
) -> object:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://app.teable.ai",
            "Referer": "https://app.teable.ai/",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:1000]
        raise SystemExit(f"HTTP {exc.code} from Teable: {detail}") from exc
    except Exception as exc:
        raise SystemExit(f"Teable request failed: {exc}") from exc
    if not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except Exception as exc:
        raise SystemExit(f"Teable returned invalid JSON: {exc}") from exc


def _extract_id(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("id", "baseId", "tableId"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        for key in ("base", "table", "data"):
            nested = payload.get(key)
            nested_id = _extract_id(nested)
            if nested_id:
                return nested_id
    return ""


def _table_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("tables", "data", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _space_items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("spaces", "data", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]
    return []


def _resolve_space_id(*, base_url: str, api_key: str) -> str:
    payload = _request_json(
        method="GET",
        url=f"{base_url}/api/space",
        api_key=api_key,
    )
    writable = [
        item
        for item in _space_items(payload)
        if str(item.get("role") or "").strip().lower() in {"owner", "creator", "editor"}
        and str(item.get("id") or "").strip()
    ]
    if len(writable) == 1:
        return str(writable[0].get("id") or "").strip()
    if not writable:
        raise SystemExit("missing PROPERTYQUARRY_TEABLE_SPACE_ID and Teable returned no writable spaces")
    names = ", ".join(str(item.get("name") or item.get("id") or "").strip() for item in writable[:5])
    raise SystemExit(f"missing PROPERTYQUARRY_TEABLE_SPACE_ID; multiple writable Teable spaces are available: {names}")


def _list_tables(*, base_url: str, api_key: str, base_id: str) -> dict[str, str]:
    payload = _request_json(
        method="GET",
        url=f"{base_url}/api/base/{urllib.parse.quote(base_id)}/table",
        api_key=api_key,
    )
    tables: dict[str, str] = {}
    for item in _table_items(payload):
        name = str(item.get("name") or item.get("tableName") or "").strip()
        table_id = str(item.get("id") or item.get("tableId") or "").strip()
        if name and table_id:
            tables[name] = table_id
    return tables


def _create_base(*, base_url: str, api_key: str, space_id: str, base_name: str) -> str:
    payload = _request_json(
        method="POST",
        url=f"{base_url}/api/base",
        api_key=api_key,
        body={
            "spaceId": space_id,
            "name": base_name,
        },
    )
    base_id = _extract_id(payload)
    if not base_id:
        raise SystemExit("Teable create-base response did not include a base id")
    return base_id


def _create_table(*, base_url: str, api_key: str, base_id: str, table_name: str) -> str:
    fields = []
    for raw_field in PROPERTYQUARRY_TEABLE_TABLE_FIELDS[table_name]:
        field = dict(raw_field)
        field.pop("notNull", None)
        fields.append(field)
    payload = _request_json(
        method="POST",
        url=f"{base_url}/api/base/{urllib.parse.quote(base_id)}/table/",
        api_key=api_key,
        body={
            "name": table_name,
            "fields": fields,
            "fieldKeyType": "name",
        },
    )
    table_id = _extract_id(payload)
    if not table_id:
        raise SystemExit(f"Teable create-table response did not include a table id for {table_name}")
    return table_id


def _write_env_mapping(
    *,
    env_file: Path,
    base_id: str,
    tenant_key: str,
    tenant_name: str,
    mapping: dict[str, dict[str, str]],
) -> None:
    updates = {
        "PROPERTYQUARRY_TEABLE_BASE_ID": base_id,
        "PROPERTYQUARRY_TEABLE_TENANT_KEY": tenant_key,
        "PROPERTYQUARRY_TEABLE_TENANT_NAME": tenant_name,
        "PROPERTYQUARRY_TEABLE_TABLE_SYNC_CONFIG_JSON": json.dumps(mapping, ensure_ascii=True, separators=(",", ":")),
        "PROPERTYQUARRY_TEABLE_AUTO_SYNC": "1",
    }
    existing = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for raw in existing:
        key = raw.split("=", 1)[0].strip() if "=" in raw else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(raw)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    env_file.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _mapping_for_tables(table_ids: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        table_name: {
            "table_id": table_ids[table_name],
            "key_field": "projection_id",
            "field_key_type": "name",
        }
        for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
        if str(table_ids.get(table_name) or "").strip()
    }


def main() -> int:
    args = parse_args()
    base_url = str(args.base_url or "https://app.teable.ai").strip().rstrip("/")
    base_id = str(args.base_id or "").strip()
    space_id = str(args.space_id or "").strip()
    tenant_key = str(args.tenant_key or "propertyquarry").strip() or "propertyquarry"
    tenant_name = str(args.base_name or "PropertyQuarry").strip() or "PropertyQuarry"
    api_key = str(args.api_key or "").strip()

    if not args.create_base and not args.create_tables:
        print(
            json.dumps(
                {
                    "status": "preview",
                    "base_url": base_url,
                    "tenant_key": tenant_key,
                    "tenant_name": tenant_name,
                    "base_id": base_id or "<required-for-create-tables>",
                    "space_id": space_id or "<required-for-create-base>",
                    "tables": PROPERTYQUARRY_TEABLE_TABLE_FIELDS,
                    "mapping_preview": {
                        table_name: {
                            "table_id": f"<{table_name}_id>",
                            "key_field": "projection_id",
                            "field_key_type": "name",
                        }
                        for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES
                    },
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    if not api_key:
        raise SystemExit("missing TEABLE_API_KEY")
    if args.create_base:
        if base_id:
            raise SystemExit("refusing to create a new base while PROPERTYQUARRY_TEABLE_BASE_ID/--base-id is already set")
        if not space_id:
            space_id = _resolve_space_id(base_url=base_url, api_key=api_key)
        base_id = _create_base(base_url=base_url, api_key=api_key, space_id=space_id, base_name=tenant_name)
    if args.create_tables:
        if not base_id:
            raise SystemExit("missing PROPERTYQUARRY_TEABLE_BASE_ID or --base-id for table creation")
        existing_tables = _list_tables(base_url=base_url, api_key=api_key, base_id=base_id)
        table_ids = dict(existing_tables)
        created: list[str] = []
        reused: list[str] = []
        for table_name in PROPERTYQUARRY_TEABLE_TABLE_NAMES:
            if table_ids.get(table_name):
                reused.append(table_name)
                continue
            table_ids[table_name] = _create_table(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name)
            created.append(table_name)
        mapping = _mapping_for_tables(table_ids)
        if len(mapping) != len(PROPERTYQUARRY_TEABLE_TABLE_NAMES):
            missing = [name for name in PROPERTYQUARRY_TEABLE_TABLE_NAMES if name not in mapping]
            raise SystemExit(f"missing Teable table ids after bootstrap: {','.join(missing)}")
        if args.write_env:
            _write_env_mapping(
                env_file=Path(args.env_file),
                base_id=base_id,
                tenant_key=tenant_key,
                tenant_name=tenant_name,
                mapping=mapping,
            )
        print(
            json.dumps(
                {
                    "status": "ready",
                    "base_url": base_url,
                    "base_id": base_id,
                    "tenant_key": tenant_key,
                    "tenant_name": tenant_name,
                    "created_tables": created,
                    "reused_tables": reused,
                    "mapping": mapping,
                    "wrote_env": bool(args.write_env),
                    "env_file": str(Path(args.env_file)),
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    print(json.dumps({"status": "ready", "base_id": base_id, "tenant_key": tenant_key}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
