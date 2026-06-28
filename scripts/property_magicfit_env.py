from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


_MAGICFIT_SUFFIX_ALIASES = {
    "MAGICFIT_EMAIL": ("PROPERTYQUARRY_MAGICFIT_EMAIL", "MAGICFIT_EMAIL"),
    "MAGICFIT_PASSWORD": ("PROPERTYQUARRY_MAGICFIT_PASSWORD", "MAGICFIT_PASSWORD"),
    "MAGICFIT_TIER": ("PROPERTYQUARRY_MAGICFIT_TIER", "MAGICFIT_TIER"),
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


def discover_magicfit_env(
    env_files: Iterable[Path] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    files = tuple(env_files or default_magicfit_env_files())
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
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
    return values, sources


def load_magicfit_env(env_files: Iterable[Path] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    values, sources = discover_magicfit_env(env_files)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values, sources
