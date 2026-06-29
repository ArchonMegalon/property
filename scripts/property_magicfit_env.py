from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


_MAGICFIT_SUFFIX_ALIASES = {
    "MAGICFIT_EMAIL": ("PROPERTYQUARRY_MAGICFIT_EMAIL", "MAGICFIT_EMAIL"),
    "MAGICFIT_PASSWORD": ("PROPERTYQUARRY_MAGICFIT_PASSWORD", "MAGICFIT_PASSWORD"),
    "MAGICFIT_TIER": ("PROPERTYQUARRY_MAGICFIT_TIER", "MAGICFIT_TIER"),
    "MAGICFIT_ACCOUNTS_JSON": ("PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON", "MAGICFIT_ACCOUNTS_JSON"),
}


def default_magicfit_env_files() -> tuple[Path, ...]:
    property_root = Path(os.environ.get("PROPERTYQUARRY_ROOT") or "/docker/property").expanduser()
    ea_root = Path(os.environ.get("PROPERTYQUARRY_EA_ROOT") or "/docker/EA").expanduser()
    return (
        property_root / ".env",
        Path("/app/.env"),
        Path("/app/config/.env"),
        ea_root / ".env.local",
        ea_root / ".env",
    )


def _normalize_env_value(raw: str) -> str:
    return raw.strip().strip("'").strip('"')


def _selected_account_index(values: dict[str, str]) -> int:
    for key in ("PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX", "MAGICFIT_ACCOUNT_INDEX"):
        raw = str(values.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = int(raw)
        except Exception:
            continue
        if parsed > 0:
            return parsed - 1
    return 0


def _apply_accounts_json_defaults(values: dict[str, str], sources: dict[str, str]) -> None:
    if values.get("PROPERTYQUARRY_MAGICFIT_EMAIL") and values.get("PROPERTYQUARRY_MAGICFIT_PASSWORD"):
        return
    raw_accounts = values.get("PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON") or values.get("MAGICFIT_ACCOUNTS_JSON") or ""
    if not raw_accounts:
        return
    try:
        loaded = json.loads(raw_accounts)
    except Exception:
        return
    if not isinstance(loaded, list):
        return
    credentialed_accounts: list[dict[str, object]] = []
    for row in loaded:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or row.get("username") or row.get("login") or "").strip()
        password = str(row.get("password") or row.get("pass") or "").strip()
        if email and password:
            credentialed_accounts.append(row)
    if not credentialed_accounts:
        return
    selected_index = min(_selected_account_index(values), len(credentialed_accounts) - 1)
    account = credentialed_accounts[selected_index]
    email = str(account.get("email") or account.get("username") or account.get("login") or "").strip()
    password = str(account.get("password") or account.get("pass") or "").strip()
    source_key = (
        "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"
        if values.get("PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON")
        else "MAGICFIT_ACCOUNTS_JSON"
    )
    source_label = f"{sources.get(source_key, 'process_env')}#{source_key}[{selected_index + 1}]"
    for key in ("PROPERTYQUARRY_MAGICFIT_EMAIL", "MAGICFIT_EMAIL"):
        values.setdefault(key, email)
        sources.setdefault(key, source_label)
    for key in ("PROPERTYQUARRY_MAGICFIT_PASSWORD", "MAGICFIT_PASSWORD"):
        values.setdefault(key, password)
        sources.setdefault(key, source_label)


def discover_magicfit_env(
    env_files: Iterable[Path] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    files = tuple(env_files or default_magicfit_env_files())
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for normalized_key, raw_value in os.environ.items():
        normalized_value = _normalize_env_value(str(raw_value or ""))
        if not normalized_key or not normalized_value:
            continue
        values.setdefault(normalized_key, normalized_value)
        sources.setdefault(normalized_key, "process_env")
        for suffix, aliases in _MAGICFIT_SUFFIX_ALIASES.items():
            if normalized_key == suffix or normalized_key.endswith(f"_{suffix}"):
                for alias in aliases:
                    values.setdefault(alias, normalized_value)
                    sources.setdefault(alias, "process_env")
    for path in files:
        if not path.exists():
            continue
        resolved = str(path.resolve())
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            normalized_value = _normalize_env_value(value)
            if not normalized_key or not normalized_value:
                continue
            values.setdefault(normalized_key, normalized_value)
            sources.setdefault(normalized_key, resolved)
            for suffix, aliases in _MAGICFIT_SUFFIX_ALIASES.items():
                if normalized_key == suffix or normalized_key.endswith(f"_{suffix}"):
                    for alias in aliases:
                        values.setdefault(alias, normalized_value)
                        sources.setdefault(alias, resolved)
    _apply_accounts_json_defaults(values, sources)
    return values, sources


def load_magicfit_env(env_files: Iterable[Path] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    values, sources = discover_magicfit_env(env_files)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values, sources
