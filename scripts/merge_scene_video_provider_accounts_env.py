#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any


ALLOWED_UPDATE_KEYS = {
    "PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON",
    "PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX",
    "PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON",
    "PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON",
}
PROTECTED_KEY_PREFIXES = ("ONEMIN_", "PROPERTYQUARRY_ONEMIN_")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECURE_FILE_MODE = 0o600


def _load_accounts(path: str) -> list[dict[str, str]]:
    if not path:
        return []
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ValueError(f"{path} account JSON file not found")
    try:
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} account JSON file is not valid JSON") from exc
    if not isinstance(loaded, list):
        raise ValueError(f"{path} must contain a JSON array")
    accounts: list[dict[str, str]] = []
    seen_emails: set[str] = set()
    for index, row in enumerate(loaded):
        if not isinstance(row, dict):
            raise ValueError(f"{path}[{index}] must be an object")
        allowed = {"email", "password", "label", "tier"}
        extra = sorted(str(key) for key in row if str(key) not in allowed)
        if extra:
            raise ValueError(f"{path}[{index}] has unsupported keys: {', '.join(extra)}")
        email = str(row.get("email") or "").strip()
        password = str(row.get("password") or "")
        if not EMAIL_RE.match(email):
            raise ValueError(f"{path}[{index}] has invalid email")
        email_key = email.lower()
        if email_key in seen_emails:
            raise ValueError(f"{path}[{index}] duplicates an earlier account email")
        seen_emails.add(email_key)
        if not password:
            raise ValueError(f"{path}[{index}] has empty password")
        account: dict[str, str] = {"email": email, "password": password}
        for optional in ("label", "tier"):
            value = str(row.get(optional) or "").strip()
            if value:
                account[optional] = value
        accounts.append(account)
    return accounts


def _require_secure_account_json_file(path: str) -> None:
    if not path:
        return
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ValueError(f"{path} account JSON file not found")
    mode = file_path.stat().st_mode & 0o777
    if mode != SECURE_FILE_MODE:
        raise ValueError(f"{path} must have mode 0o600 before merge; current mode is {oct(mode)}")


def _compact_accounts_json(accounts: list[dict[str, str]]) -> str:
    return json.dumps(accounts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _line_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return ""
    key = stripped.split("=", 1)[0].strip()
    if key.startswith("export "):
        key = key[len("export ") :].strip()
    return key


def _line_assignment_prefix(line: str) -> str:
    stripped = line.strip()
    return "export " if stripped.startswith("export ") else ""


def _validate_updates(updates: dict[str, str]) -> None:
    forbidden = sorted(key for key in updates if key not in ALLOWED_UPDATE_KEYS)
    if forbidden:
        raise ValueError(f"refusing unsupported env keys: {', '.join(forbidden)}")
    protected = sorted(
        key
        for key in updates
        if any(key.startswith(prefix) for prefix in PROTECTED_KEY_PREFIXES)
    )
    if protected:
        raise ValueError(f"refusing protected env keys: {', '.join(protected)}")


def _protected_env_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if any(_line_key(line).startswith(prefix) for prefix in PROTECTED_KEY_PREFIXES)
    ]


def _ensure_protected_env_lines_preserved(existing: str, merged: str) -> None:
    if _protected_env_lines(existing) != _protected_env_lines(merged):
        raise ValueError("protected ONEMIN env lines changed during merge")


def _ensure_no_duplicate_update_keys(existing: str, update_keys: set[str]) -> None:
    counts: dict[str, int] = {}
    for line in existing.splitlines():
        key = _line_key(line)
        if key in update_keys:
            counts[key] = counts.get(key, 0) + 1
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate provider account env keys in target env: {', '.join(duplicates)}")


def merge_env_text(existing: str, updates: dict[str, str]) -> tuple[str, list[str]]:
    _validate_updates(updates)
    _ensure_no_duplicate_update_keys(existing, set(updates))
    updated_keys: list[str] = []
    seen: set[str] = set()
    output: list[str] = []
    for line in existing.splitlines():
        key = _line_key(line)
        if key in updates:
            output.append(f"{_line_assignment_prefix(line)}{key}={_shell_quote(updates[key])}")
            updated_keys.append(key)
            seen.add(key)
        else:
            output.append(line)
    for key in sorted(updates):
        if key not in seen:
            output.append(f"{key}={_shell_quote(updates[key])}")
            updated_keys.append(key)
    rendered = "\n".join(output).rstrip() + "\n"
    return rendered, updated_keys


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(text)
        tmp_path = Path(handle.name)
    tmp_path.chmod(SECURE_FILE_MODE)
    tmp_path.replace(path)
    path.chmod(SECURE_FILE_MODE)


def _next_backup_path(path: Path) -> Path:
    base = path.with_name(f"{path.name}.scene-video-provider-accounts.bak")
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.scene-video-provider-accounts.bak.{index}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"too many existing backup files for {path}")


def _write_backup(path: Path, existing: str) -> str:
    if not path.exists():
        return ""
    backup_path = _next_backup_path(path)
    backup_path.write_text(existing, encoding="utf-8")
    backup_path.chmod(SECURE_FILE_MODE)
    return str(backup_path)


def build_updates(
    *,
    magicfit_accounts: list[dict[str, str]],
    omagic_accounts: list[dict[str, str]],
    magicfit_account_index: int | None,
    write_magic_alias: bool,
) -> dict[str, str]:
    updates: dict[str, str] = {}
    if magicfit_accounts:
        updates["PROPERTYQUARRY_MAGICFIT_ACCOUNTS_JSON"] = _compact_accounts_json(magicfit_accounts)
        if magicfit_account_index is not None:
            if magicfit_account_index < 0 or magicfit_account_index >= len(magicfit_accounts):
                raise ValueError(
                    f"magicfit account index {magicfit_account_index} is outside available account range 0..{len(magicfit_accounts) - 1}"
                )
            updates["PROPERTYQUARRY_MAGICFIT_ACCOUNT_INDEX"] = str(magicfit_account_index)
    elif magicfit_account_index is not None:
        raise ValueError("magicfit account index requires MagicFit accounts")
    if omagic_accounts:
        if not write_magic_alias:
            raise ValueError("magic alias account env is required when OMagic accounts are supplied")
        omagic_json = _compact_accounts_json(omagic_accounts)
        updates["PROPERTYQUARRY_OMAGIC_ACCOUNTS_JSON"] = omagic_json
        updates["PROPERTYQUARRY_MAGIC_ACCOUNTS_JSON"] = omagic_json
    _validate_updates(updates)
    return updates


def merge_accounts_env(
    *,
    env_file: Path,
    magicfit_accounts: list[dict[str, str]],
    omagic_accounts: list[dict[str, str]],
    expected_magicfit_count: int | None,
    expected_omagic_count: int | None,
    magicfit_account_index: int | None,
    write_magic_alias: bool,
    write: bool,
) -> dict[str, Any]:
    if expected_magicfit_count is not None and len(magicfit_accounts) != expected_magicfit_count:
        raise ValueError(f"magicfit account count {len(magicfit_accounts)} does not match expected {expected_magicfit_count}")
    if expected_omagic_count is not None and len(omagic_accounts) != expected_omagic_count:
        raise ValueError(f"omagic account count {len(omagic_accounts)} does not match expected {expected_omagic_count}")
    updates = build_updates(
        magicfit_accounts=magicfit_accounts,
        omagic_accounts=omagic_accounts,
        magicfit_account_index=magicfit_account_index,
        write_magic_alias=write_magic_alias,
    )
    if write and not updates:
        raise ValueError("no provider account updates supplied for --write")
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    merged, updated_keys = merge_env_text(existing, updates)
    _ensure_protected_env_lines_preserved(existing, merged)
    backup_path = ""
    if write and updates:
        backup_path = _write_backup(env_file, existing)
        _atomic_write(env_file, merged)
    return {
        "status": "pass",
        "dry_run": not write,
        "env_file": str(env_file),
        "backup_path": backup_path,
        "secure_file_mode": oct(SECURE_FILE_MODE),
        "updated_keys": updated_keys,
        "provider_account_counts": {
            "magicfit": len(magicfit_accounts),
            "omagic": len(omagic_accounts),
            "magic_alias_written": bool(omagic_accounts and write_magic_alias),
        },
        "protected_key_prefixes": list(PROTECTED_KEY_PREFIXES),
        "protected_keys_touched": [],
        "protected_line_count": len(_protected_env_lines(existing)),
        "secret_values_in_receipt": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely merge MagicFit and OMagic scene-video provider accounts into an env file.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--magicfit-accounts-json-file", default="")
    parser.add_argument("--omagic-accounts-json-file", default="")
    parser.add_argument("--expected-magicfit-count", type=int, default=None)
    parser.add_argument("--expected-omagic-count", type=int, default=None)
    parser.add_argument("--magicfit-account-index", type=int, default=None)
    parser.add_argument("--no-magic-alias", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    try:
        _require_secure_account_json_file(args.magicfit_accounts_json_file)
        _require_secure_account_json_file(args.omagic_accounts_json_file)
        receipt = merge_accounts_env(
            env_file=Path(args.env_file).expanduser(),
            magicfit_accounts=_load_accounts(args.magicfit_accounts_json_file),
            omagic_accounts=_load_accounts(args.omagic_accounts_json_file),
            expected_magicfit_count=args.expected_magicfit_count,
            expected_omagic_count=args.expected_omagic_count,
            magicfit_account_index=args.magicfit_account_index,
            write_magic_alias=not args.no_magic_alias,
            write=args.write,
        )
    except Exception as exc:  # noqa: BLE001
        receipt = {
            "status": "fail",
            "blockers": [str(exc)],
            "protected_key_prefixes": list(PROTECTED_KEY_PREFIXES),
            "protected_keys_touched": [],
            "secret_values_in_receipt": False,
        }
        print(json.dumps(receipt, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
