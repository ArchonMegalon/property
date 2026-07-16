from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs" / "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json"
DEFAULT_ROLLUP_PATH = Path("/data/artifacts/property-evidence-overlay-rollups.json")
REQUIRED_UI_STATES = {"unavailable", "stale", "verified"}
READ_MODEL_MODES = {"auto", "postgres", "file"}


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


def _sentence(value: object) -> str:
    text = " ".join(_string(value).split())
    if not text:
        return ""
    return text if text[-1:] in ".!?" else f"{text}."


def _public_source_name(value: object, *, fallback: str) -> str:
    text = " ".join(_string(value).split())
    if not text:
        return fallback
    cleaned = text
    for prefix in ("Terms" + "-safe", "terms" + "-safe"):
        cleaned = cleaned.replace(prefix, "")
    cleaned = cleaned.strip(" -")
    if cleaned[:1].islower():
        cleaned = f"{cleaned[:1].upper()}{cleaned[1:]}"
    return cleaned or fallback


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


def evidence_overlay_read_model_mode() -> str:
    configured = _string(os.getenv("PROPERTYQUARRY_EVIDENCE_OVERLAY_READ_MODEL")).casefold() or "auto"
    if configured not in READ_MODEL_MODES:
        return "postgres" if _string(os.getenv("EA_RUNTIME_MODE")).casefold() == "prod" else "file"
    if _string(os.getenv("EA_RUNTIME_MODE")).casefold() == "prod":
        return "postgres"
    if configured == "auto":
        return "postgres" if _string(os.getenv("DATABASE_URL")) else "file"
    return configured


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


def _postgres_rollup_rows(lookup_values: dict[str, str]) -> list[dict[str, object]]:
    database_url = _string(os.getenv("DATABASE_URL"))
    if not database_url or not lookup_values:
        return []
    try:
        from app.repositories.property_evidence_overlays_postgres import (
            PostgresPropertyEvidenceOverlayRepository,
        )

        return PostgresPropertyEvidenceOverlayRepository(database_url).lookup(lookup_values)
    except Exception:
        # Customer pages degrade to explicit unavailable states. Readiness and
        # launch Gold fail closed on missing/broken persistent read-model proof.
        return []


def _facts_with_snapshot(facts: dict[str, object]) -> dict[str, object]:
    snapshot = (
        dict(facts.get("listing_research_snapshot") or {})
        if isinstance(facts.get("listing_research_snapshot"), dict)
        else {}
    )
    return {**snapshot, **dict(facts or {})}


def _candidate_lookup_values(facts: dict[str, object], candidate: dict[str, object]) -> dict[str, str]:
    merged_facts = _facts_with_snapshot(dict(facts or {}))
    values: dict[str, str] = {}
    for key in ("candidate_ref", "property_url", "source_ref", "source_url"):
        value = _string(candidate.get(key) or merged_facts.get(key))
        if value:
            values[key] = value.casefold()
    for key in (
        "postal_code",
        "postal_name",
        "district",
        "district_polygon",
        "neighborhood",
        "school_catchment",
        "street",
        "street_address",
        "address",
    ):
        value = _string(merged_facts.get(key) or candidate.get(key))
        if value:
            values[key] = value.casefold()
    lat = _string(
        merged_facts.get("map_lat")
        or merged_facts.get("lat")
        or merged_facts.get("latitude")
        or candidate.get("map_lat")
        or candidate.get("lat")
        or candidate.get("latitude")
    )
    lon = _string(
        merged_facts.get("map_lng")
        or merged_facts.get("lon")
        or merged_facts.get("lng")
        or merged_facts.get("longitude")
        or candidate.get("map_lng")
        or candidate.get("lon")
        or candidate.get("lng")
        or candidate.get("longitude")
    )
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
        "detail": "This layer is not available for this address yet.",
        "source_name": _string(layer.get("source_registry")) or "Layer pending",
        "source_url": "",
        "article_url": "",
        "cache_updated_at": "",
        "source_updated_at": "",
        "uncertainty_label": "not available",
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
        "read_model_source": "postgres_cached_rollup_unavailable"
        if evidence_overlay_read_model_mode() == "postgres"
        else "file_rollup_unavailable",
    }


def _overlay_from_rollup(layer: dict[str, object], row: dict[str, object], *, stale_after_days: int) -> dict[str, object]:
    state = _state_for_rollup(row, stale_after_days=stale_after_days)
    tag = {"verified": "Ready", "stale": "Stale", "unavailable": "Unavailable"}.get(state, "Unavailable")
    source_name = _public_source_name(
        row.get("source_name") or layer.get("source_registry"),
        fallback="Local area source",
    )
    source_url = _string(row.get("source_url"))
    summary = _string(row.get("summary") or row.get("value_label") or row.get("headline"))
    uncertainty = _string(row.get("uncertainty_label")) or ("current area layer" if state == "verified" else "update pending")
    detail_parts = [
        _sentence(summary or "This area layer is available for the address."),
        _sentence(f"From {source_name}"),
        _sentence(f"Coverage: {uncertainty}"),
    ]
    if state == "stale":
        detail_parts.append("Update pending.")
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or _string(layer.get("layer_key")).replace("_", " ").title(),
        "ui_state": state,
        "tag": tag,
        "detail": " ".join(part for part in detail_parts if part),
        "source_name": source_name,
        "source_url": source_url,
        "article_url": _string(row.get("article_url")),
        "cache_updated_at": _string(row.get("cache_updated_at")),
        "source_updated_at": _string(row.get("source_updated_at")),
        "uncertainty_label": uncertainty,
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
        "read_model_source": _string(row.get("read_model_source")) or "file_cached_rollup",
    }


def _first_official_source(facts: dict[str, object], risk_keys: set[str]) -> dict[str, object]:
    official = (
        dict(facts.get("official_risk_evidence") or {})
        if isinstance(facts.get("official_risk_evidence"), dict)
        else {}
    )
    for row in list(official.get("sources") or []):
        if not isinstance(row, dict):
            continue
        risk_key = _string(row.get("risk_key") or row.get("key")).casefold()
        if risk_key in risk_keys:
            return dict(row)
    return {}


def _derived_summer_heat_overlay(layer: dict[str, object], facts: dict[str, object]) -> dict[str, object] | None:
    merged_facts = _facts_with_snapshot(dict(facts or {}))
    cooling_summary = _string(merged_facts.get("cooling_corridor_summary"))
    cooling_signal = _string(merged_facts.get("cooling_corridor_signal")).casefold()
    heat_risk = _string(
        merged_facts.get("heat_resilience_risk")
        or merged_facts.get("urban_heat_risk")
        or merged_facts.get("summer_heat_risk")
    ).casefold()
    official_source = _first_official_source(merged_facts, {"heat_resilience", "cooling_corridor"})
    official_summary = _string(official_source.get("summary"))
    if not any((cooling_summary, cooling_signal, heat_risk, official_summary, merged_facts.get("tree_shade_signal"), merged_facts.get("green_shade_signal"))):
        return None
    summary = (
        cooling_summary
        or official_summary
        or (
            "Nearby tree or courtyard shade can soften summer heat for this address."
            if bool(merged_facts.get("tree_shade_signal") or merged_facts.get("green_shade_signal"))
            else "Summer heat context is attached for this address."
        )
    )
    uncertainty = "attached climate context"
    if cooling_signal in {"strong", "moderate", "weak"}:
        uncertainty = f"microclimate hint ({cooling_signal})"
    source_name = (
        _string(official_source.get("source_label"))
        or _string(official_source.get("provider"))
        or "Climate context"
    )
    detail_parts = [_sentence(summary), _sentence(f"From {source_name}"), _sentence(f"Signal: {uncertainty}")]
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or "Summer heat",
        "ui_state": "verified",
        "tag": "Ready",
        "detail": " ".join(part for part in detail_parts if part),
        "source_name": source_name,
        "source_url": _string(official_source.get("source_url")),
        "article_url": "",
        "cache_updated_at": "",
        "source_updated_at": "",
        "uncertainty_label": uncertainty,
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
        "read_model_source": "derived_candidate_facts_non_production",
    }


def _derived_overlay_for_layer(layer: dict[str, object], facts: dict[str, object]) -> dict[str, object] | None:
    layer_key = _string(layer.get("layer_key"))
    if layer_key == "summer_heat":
        return _derived_summer_heat_overlay(layer, facts)
    return None


def build_property_evidence_overlay_rows(
    *,
    facts: dict[str, object],
    candidate: dict[str, object] | None = None,
    rollup_path: Path | None = None,
    stale_after_days: int = 45,
) -> list[dict[str, object]]:
    registry = evidence_overlay_registry()
    layers = [dict(layer) for layer in list(registry.get("layers") or []) if isinstance(layer, dict)]
    lookup_values = _candidate_lookup_values(dict(facts or {}), dict(candidate or {}))
    read_model_mode = evidence_overlay_read_model_mode()
    if read_model_mode == "postgres":
        rollups = _postgres_rollup_rows(lookup_values)
    else:
        rollup_payload = _load_json(rollup_path or evidence_overlay_rollup_path())
        rollups = _rollup_rows(rollup_payload)
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
            derived = None if read_model_mode == "postgres" else _derived_overlay_for_layer(layer, facts)
            rows.append(derived or _unavailable_overlay(layer))
    return rows
