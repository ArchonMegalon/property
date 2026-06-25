from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs" / "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json"
DEFAULT_ROLLUP_PATH = Path("/data/artifacts/property-evidence-overlay-rollups.json")
REQUIRED_UI_STATES = {"unavailable", "stale", "verified"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _string(value: object) -> str:
    return str(value or "").strip()


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def evidence_overlay_registry(path: Path = REGISTRY_PATH) -> dict[str, object]:
    payload = _load_json(path)
    if payload.get("contract_name") != "propertyquarry.evidence_overlay_registry.v1":
        return {"contract_name": "propertyquarry.evidence_overlay_registry.v1", "layers": []}
    return payload


def evidence_overlay_rollup_path() -> Path:
    configured = _string(os.getenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_ROLLUP_PATH"))
    return Path(configured).expanduser() if configured else DEFAULT_ROLLUP_PATH


def _rollup_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, dict)]
    layers = payload.get("layers")
    if isinstance(layers, dict):
        flattened: list[dict[str, object]] = []
        for layer_key, layer_rows in layers.items():
            for row in layer_rows if isinstance(layer_rows, list) else []:
                if isinstance(row, dict):
                    flattened.append({"layer_key": str(layer_key), **dict(row)})
        return flattened
    return []


def _candidate_lookup_values(facts: dict[str, object], candidate: dict[str, object]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in ("candidate_ref", "property_url", "source_ref", "source_url"):
        value = _string(candidate.get(key) or facts.get(key))
        if value:
            values[key] = value.casefold()
    for key in ("postal_code", "postal_name", "district", "neighborhood", "street", "street_address", "address"):
        value = _string(facts.get(key) or candidate.get(key))
        if value:
            values[key] = value.casefold()
    lat = _string(facts.get("lat") or facts.get("latitude") or candidate.get("lat") or candidate.get("latitude"))
    lon = _string(facts.get("lon") or facts.get("lng") or facts.get("longitude") or candidate.get("lon") or candidate.get("lng") or candidate.get("longitude"))
    if lat and lon:
        values["property_coordinate"] = f"{lat},{lon}".casefold()
    return values


def _row_matches_candidate(row: dict[str, object], lookup_values: dict[str, str]) -> bool:
    match = row.get("match")
    if isinstance(match, dict):
        checks = {str(key): _string(value).casefold() for key, value in match.items() if _string(value)}
    else:
        checks = {key: _string(row.get(key)).casefold() for key in lookup_values if _string(row.get(key))}
    if not checks:
        return False
    for key, expected in checks.items():
        actual = lookup_values.get(key)
        if actual and actual == expected:
            return True
    return False


def _state_for_rollup(row: dict[str, object], *, stale_after_days: int) -> str:
    explicit = _string(row.get("ui_state") or row.get("state")).casefold()
    if explicit in REQUIRED_UI_STATES:
        return explicit
    cache_updated_at = _parse_datetime(row.get("cache_updated_at"))
    if cache_updated_at is not None and (_now() - cache_updated_at).days > stale_after_days:
        return "stale"
    return "verified"


def _unavailable_overlay(layer: dict[str, object]) -> dict[str, object]:
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or _string(layer.get("layer_key")).replace("_", " ").title(),
        "ui_state": "unavailable",
        "tag": "Unavailable",
        "detail": "No verified cached rollup is available yet. Search did not crawl or index this source inline.",
        "source_name": _string(layer.get("source_registry")) or "Source registry pending",
        "source_url": "",
        "article_url": "",
        "cache_updated_at": "",
        "source_updated_at": "",
        "uncertainty_label": "not indexed",
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
    }


def _overlay_from_rollup(layer: dict[str, object], row: dict[str, object], *, stale_after_days: int) -> dict[str, object]:
    state = _state_for_rollup(row, stale_after_days=stale_after_days)
    tag = {"verified": "Verified", "stale": "Stale", "unavailable": "Unavailable"}.get(state, "Unavailable")
    source_name = _string(row.get("source_name")) or _string(layer.get("source_registry")) or "Cached source"
    source_url = _string(row.get("source_url"))
    summary = _string(row.get("summary") or row.get("value_label") or row.get("headline"))
    uncertainty = _string(row.get("uncertainty_label")) or ("fresh cached rollup" if state == "verified" else "needs refresh")
    detail_parts = [summary or "Cached geographic evidence is available for this area.", f"source: {source_name}", f"uncertainty: {uncertainty}"]
    if state == "stale":
        detail_parts.append("refresh recommended")
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or _string(layer.get("layer_key")).replace("_", " ").title(),
        "ui_state": state,
        "tag": tag,
        "detail": " | ".join(part for part in detail_parts if part),
        "source_name": source_name,
        "source_url": source_url,
        "article_url": _string(row.get("article_url")),
        "cache_updated_at": _string(row.get("cache_updated_at")),
        "source_updated_at": _string(row.get("source_updated_at")),
        "uncertainty_label": uncertainty,
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
    }


def build_property_evidence_overlay_rows(
    *,
    facts: dict[str, object],
    candidate: dict[str, object] | None = None,
    rollup_path: Path | None = None,
    stale_after_days: int = 45,
) -> list[dict[str, object]]:
    registry = evidence_overlay_registry()
    layers = [dict(layer) for layer in list(registry.get("layers") or []) if isinstance(layer, dict)]
    rollup_payload = _load_json(rollup_path or evidence_overlay_rollup_path())
    rollups = _rollup_rows(rollup_payload)
    lookup_values = _candidate_lookup_values(dict(facts or {}), dict(candidate or {}))
    rows: list[dict[str, object]] = []
    for layer in layers:
        layer_key = _string(layer.get("layer_key"))
        matched = next(
            (
                row
                for row in rollups
                if _string(row.get("layer_key")) == layer_key and _row_matches_candidate(row, lookup_values)
            ),
            None,
        )
        if matched:
            rows.append(_overlay_from_rollup(layer, matched, stale_after_days=stale_after_days))
        else:
            rows.append(_unavailable_overlay(layer))
    return rows
