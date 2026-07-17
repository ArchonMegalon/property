from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.public_url_safety import safe_public_http_url


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "docs" / "PROPERTYQUARRY_EVIDENCE_OVERLAY_REGISTRY.json"
DEFAULT_ROLLUP_PATH = Path("/data/artifacts/property-evidence-overlay-rollups.json")
REQUIRED_UI_STATES = {"unavailable", "stale", "verified"}
READ_MODEL_MODES = {"auto", "postgres", "file"}
EVIDENCE_OVERLAY_CACHE_MAX_AGE_HOURS = 48.0
_REFERENCE_PERIOD_PART = r"[0-9]{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12][0-9]|3[01]))?)?"
REFERENCE_PERIOD_PATTERN = re.compile(
    rf"^(?:{_REFERENCE_PERIOD_PART})(?:/(?:{_REFERENCE_PERIOD_PART}))?$"
)


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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _reference_period_point(value: str) -> datetime | None:
    try:
        if len(value) == 4:
            return datetime(int(value), 1, 1, tzinfo=timezone.utc)
        if len(value) == 7:
            year, month = value.split("-", 1)
            return datetime(int(year), int(month), 1, tzinfo=timezone.utc)
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return None


def _valid_reference_period(value: object) -> bool:
    text = _string(value)
    if not REFERENCE_PERIOD_PATTERN.fullmatch(text):
        return False
    start_text, separator, end_text = text.partition("/")
    start = _reference_period_point(start_text)
    end = _reference_period_point(end_text) if separator else start
    return start is not None and end is not None and start <= end


def _string(value: object) -> str:
    return str(value or "").strip()


def _explicit_positive_signal(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError):
            return False
        return math.isfinite(numeric) and numeric == 1.0
    return _string(value).casefold().replace("-", "_").replace(" ", "_") in {
        "1",
        "confirmed",
        "present",
        "positive",
        "true",
        "yes",
    }


def _meaningful_evidence_text(value: object) -> str:
    text = _string(value)
    if text.casefold() in {
        "0",
        "false",
        "n/a",
        "na",
        "nan",
        "no",
        "none",
        "null",
        "unavailable",
        "unknown",
    }:
        return ""
    return text


def _normalized_heat_risk(value: object) -> str:
    if value is True:
        return "high"
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
        except (OverflowError, TypeError, ValueError):
            return ""
        return "high" if math.isfinite(numeric) and numeric == 1.0 else ""
    normalized = _string(value).casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"very_high", "high", "severe", "extreme"}:
        return "high"
    if normalized in {"moderate", "medium", "elevated"}:
        return "moderate"
    if normalized in {"very_low", "low", "cool", "good", "minimal"}:
        return "low"
    if normalized == "clear":
        return "clear"
    return ""


def _sentence(value: object) -> str:
    text = " ".join(_string(value).split())
    if not text:
        return ""
    return text if text[-1:] in ".!?" else f"{text}."


def _safe_public_http_url(value: object) -> str:
    return safe_public_http_url(value)


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
    if payload.get("contract_name") != "propertyquarry.evidence_overlay_registry.v2":
        return {"contract_name": "propertyquarry.evidence_overlay_registry.v2", "layers": []}
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
    exact_listing_keys = {"candidate_ref", "property_url", "source_ref"}
    exact_checks = {
        key: expected
        for key, expected in checks.items()
        if key in exact_listing_keys
    }
    if exact_checks:
        return all(lookup_values.get(key) == expected for key, expected in exact_checks.items())
    for key, expected in checks.items():
        actual = lookup_values.get(key)
        if actual and actual == expected:
            return True
    return False


def _state_and_temporal_reason_for_rollup(
    row: dict[str, object],
    *,
    stale_after_days: int,
    layer: dict[str, object] | None = None,
) -> tuple[str, str]:
    explicit = _string(row.get("ui_state") or row.get("state")).casefold()
    if explicit not in REQUIRED_UI_STATES:
        return "unavailable", "invalid_ui_state"
    if explicit == "unavailable":
        return "unavailable", "source_unavailable"
    cache_updated_at = _parse_datetime(row.get("cache_updated_at"))
    if cache_updated_at is None:
        return "unavailable", "cache_timestamp_missing"
    now = _now()
    if cache_updated_at > now + timedelta(minutes=5):
        return "unavailable", "cache_timestamp_invalid"
    try:
        requested_cache_max_age_hours = float(stale_after_days) * 24.0
    except (TypeError, ValueError, OverflowError):
        requested_cache_max_age_hours = 0.0
    if (
        not math.isfinite(requested_cache_max_age_hours)
        or requested_cache_max_age_hours <= 0
    ):
        requested_cache_max_age_hours = 0.0
    cache_max_age_hours = min(
        requested_cache_max_age_hours,
        EVIDENCE_OVERLAY_CACHE_MAX_AGE_HOURS,
    )
    cache_copy_expired = now - cache_updated_at > timedelta(
        hours=cache_max_age_hours
    )
    if layer is None and cache_copy_expired:
        return "stale", "cache_copy_expired"
    if layer is None:
        return explicit, "source_marked_stale" if explicit == "stale" else "verified"

    temporalities = {
        _string(value).casefold()
        for value in list(layer.get("allowed_source_temporalities") or [])
        if _string(value)
    }
    source_temporality = _string(row.get("source_temporality")).casefold()
    source_updated_at = _parse_datetime(row.get("source_updated_at"))
    source_checked_at = _parse_datetime(row.get("source_checked_at"))
    if not temporalities or source_temporality not in temporalities:
        return "unavailable", "source_temporality_missing"
    if (
        source_updated_at is None
        or source_updated_at > now + timedelta(minutes=5)
        or cache_updated_at < source_updated_at
    ):
        return "unavailable", "source_timestamp_invalid"
    if (
        not _string(row.get("source_name"))
        or not _safe_public_http_url(row.get("source_url"))
        or not _string(row.get("uncertainty_label"))
    ):
        return "unavailable", "source_provenance_missing"
    reference_period = _string(row.get("reference_period"))
    if source_temporality == "reference":
        if not _valid_reference_period(reference_period):
            return "unavailable", "reference_period_missing"
    elif reference_period:
        return "unavailable", "reference_period_invalid"
    if source_temporality == "current_feed":
        if (
            source_checked_at is None
            or source_checked_at > now + timedelta(minutes=5)
            or source_checked_at > cache_updated_at
            or source_checked_at < source_updated_at
        ):
            return "unavailable", "source_check_timestamp_invalid"
    elif _string(row.get("source_checked_at")):
        return "unavailable", "source_check_timestamp_invalid"
    source_age_policy = (
        dict(layer.get("source_max_age_hours_by_temporality") or {})
        if isinstance(layer.get("source_max_age_hours_by_temporality"), dict)
        else {}
    )
    source_sla_expired = False
    raw_source_max_age = source_age_policy.get(source_temporality)
    if raw_source_max_age is not None:
        try:
            source_max_age_hours = float(raw_source_max_age)
        except (TypeError, ValueError):
            return "unavailable", "source_age_policy_invalid"
        if not math.isfinite(source_max_age_hours) or source_max_age_hours <= 0:
            return "unavailable", "source_age_policy_invalid"
        sla_timestamp_fields = (
            dict(layer.get("source_sla_timestamp_field_by_temporality") or {})
            if isinstance(
                layer.get("source_sla_timestamp_field_by_temporality"), dict
            )
            else {}
        )
        sla_timestamp_field = _string(
            sla_timestamp_fields.get(source_temporality)
        )
        source_sla_at = (
            source_checked_at
            if sla_timestamp_field == "source_checked_at"
            else (
                source_updated_at
                if sla_timestamp_field == "source_updated_at"
                else None
            )
        )
        if source_sla_at is None:
            return "unavailable", "source_age_policy_invalid"
        source_sla_expired = now - source_sla_at > timedelta(
            hours=source_max_age_hours
        )
    layer_key = _string(layer.get("layer_key"))
    for score_field in ("property_scoring", "person_scoring"):
        if score_field in row and row.get(score_field) is not False:
            return "unavailable", "scoring_claim_invalid"
        if layer_key != "official_safety_context" and score_field in row:
            return "unavailable", "scoring_claim_invalid"
    if layer_key != "media_attention" and any(
        field in row
        for field in ("article_url", "independent_press", "media_source_class")
    ):
        return "unavailable", "media_classification_invalid"
    if layer_key != "official_safety_context" and any(
        field in row for field in ("geographic_scope", "rights_caveat")
    ):
        return "unavailable", "safety_claim_boundary_invalid"
    if layer_key == "media_attention":
        media_source_class = _string(row.get("media_source_class")).casefold()
        independent_press = row.get("independent_press")
        allowed_media_classes = {
            _string(value).casefold()
            for value in list(layer.get("allowed_media_source_classes") or [])
            if _string(value)
        }
        if (
            media_source_class not in allowed_media_classes
            or not isinstance(independent_press, bool)
            or (media_source_class == "municipal_rss" and independent_press)
            or (media_source_class == "independent_press" and not independent_press)
            or not _safe_public_http_url(row.get("article_url"))
        ):
            return "unavailable", "media_classification_invalid"
    if layer_key == "official_safety_context":
        allowed_scopes = {
            _string(value).casefold()
            for value in list(layer.get("allowed_geographic_scopes") or [])
            if _string(value)
        }
        if (
            _string(row.get("geographic_scope")).casefold() not in allowed_scopes
            or not _string(row.get("rights_caveat"))
            or row.get("property_scoring") is not False
            or row.get("person_scoring") is not False
        ):
            return "unavailable", "safety_claim_boundary_invalid"
    if source_sla_expired:
        return "stale", "source_sla_expired"
    if cache_copy_expired:
        return "stale", "cache_copy_expired"
    if explicit == "stale":
        return "stale", "source_marked_stale"
    return "verified", "verified_source_period"


def _state_for_rollup(
    row: dict[str, object],
    *,
    stale_after_days: int,
    layer: dict[str, object] | None = None,
) -> str:
    state, _reason = _state_and_temporal_reason_for_rollup(
        row,
        stale_after_days=stale_after_days,
        layer=layer,
    )
    return state


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
        "source_checked_at": "",
        "source_temporality": "",
        "source_cadence_class": _string(layer.get("source_cadence_class")),
        "reference_period": "",
        "temporal_status": "source_unavailable",
        "uncertainty_label": "not available",
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
        "read_model_source": "postgres_cached_rollup_unavailable"
        if evidence_overlay_read_model_mode() == "postgres"
        else "file_rollup_unavailable",
    }


def _overlay_from_rollup(layer: dict[str, object], row: dict[str, object], *, stale_after_days: int) -> dict[str, object]:
    state, temporal_reason = _state_and_temporal_reason_for_rollup(
        row,
        stale_after_days=stale_after_days,
        layer=layer,
    )
    tag = {"verified": "Ready", "stale": "Stale", "unavailable": "Unavailable"}.get(state, "Unavailable")
    source_name = _public_source_name(
        row.get("source_name") or layer.get("source_registry"),
        fallback="Local area source",
    )
    source_url = _safe_public_http_url(row.get("source_url"))
    summary = _string(row.get("summary") or row.get("value_label") or row.get("headline"))
    fallback_summary = "This layer is not available for this address yet."
    if state == "verified":
        fallback_summary = "This area layer is available for its declared source period."
    elif state == "stale" and temporal_reason == "cache_copy_expired":
        fallback_summary = "The cached copy has expired and needs a refresh."
    elif state == "stale" and temporal_reason == "source_sla_expired":
        fallback_summary = "The live or current-feed source update is overdue."
    elif state == "stale":
        fallback_summary = "This area layer is marked stale by its source steward."
    uncertainty = _string(row.get("uncertainty_label")) or {
        "verified": "area context for the declared source period",
        "stale": "update pending",
        "unavailable": "not available",
    }[state]
    display_summary = fallback_summary if state == "unavailable" else (summary or fallback_summary)
    detail_parts = [
        _sentence(display_summary),
        _sentence(f"From {source_name}"),
        _sentence(f"Coverage: {uncertainty}"),
    ]
    source_temporality = _string(row.get("source_temporality")).casefold()
    reference_period = _string(row.get("reference_period"))
    if state != "unavailable" and source_temporality == "reference":
        detail_parts.append(_sentence(f"Reference period: {reference_period}"))
    elif (
        state != "unavailable"
        and source_temporality == "current_feed"
        and _string(row.get("source_updated_at"))
    ):
        detail_parts.append(
            _sentence(
                f"Source item published: {_string(row.get('source_updated_at'))}"
            )
        )
        detail_parts.append(
            _sentence(f"Feed checked: {_string(row.get('source_checked_at'))}")
        )
    elif state != "unavailable" and _string(row.get("source_updated_at")):
        detail_parts.append(
            _sentence(f"Source updated: {_string(row.get('source_updated_at'))}")
        )
    if temporal_reason == "cache_copy_expired":
        detail_parts.append(
            "Cached-copy expiry does not establish source freshness or staleness."
        )
    elif state == "stale":
        detail_parts.append("Update pending.")
    media_source_class = _string(row.get("media_source_class")).casefold()
    if (
        _string(layer.get("layer_key")) == "media_attention"
        and media_source_class == "municipal_rss"
        and state != "unavailable"
    ):
        detail_parts.append(
            "Municipal RSS is first-party municipal notice material, not independent press."
        )
    if (
        _string(layer.get("layer_key")) == "official_safety_context"
        and state != "unavailable"
    ):
        detail_parts.append(_sentence(_string(row.get("rights_caveat"))))
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or _string(layer.get("layer_key")).replace("_", " ").title(),
        "ui_state": state,
        "tag": tag,
        "detail": " ".join(part for part in detail_parts if part),
        "source_name": source_name,
        "source_url": source_url,
        "article_url": _safe_public_http_url(row.get("article_url")),
        "cache_updated_at": _string(row.get("cache_updated_at")),
        "source_updated_at": _string(row.get("source_updated_at")),
        "source_checked_at": _string(row.get("source_checked_at")),
        "source_temporality": source_temporality,
        "source_cadence_class": _string(layer.get("source_cadence_class")),
        "reference_period": reference_period,
        "temporal_status": temporal_reason,
        "uncertainty_label": uncertainty,
        "teable_table": _string(layer.get("teable_table")),
        "read_model": _string(layer.get("read_model")),
        "search_policy": _string(layer.get("search_policy")),
        "read_model_source": _string(row.get("read_model_source")) or "file_cached_rollup",
    }


def _first_verified_official_source(facts: dict[str, object], risk_keys: set[str]) -> dict[str, object]:
    official = (
        dict(facts.get("official_risk_evidence") or {})
        if isinstance(facts.get("official_risk_evidence"), dict)
        else {}
    )
    for row in list(official.get("sources") or []):
        if not isinstance(row, dict):
            continue
        risk_key = _string(row.get("risk_key") or row.get("key")).casefold()
        verification_state = _string(row.get("verification_state")).casefold()
        if risk_key in risk_keys and verification_state in {"verified", "confirmed", "cleared"}:
            return dict(row)
    return {}


def _derived_summer_heat_overlay(layer: dict[str, object], facts: dict[str, object]) -> dict[str, object] | None:
    merged_facts = _facts_with_snapshot(dict(facts or {}))
    cooling_summary = _meaningful_evidence_text(merged_facts.get("cooling_corridor_summary"))
    raw_cooling_signal = _string(merged_facts.get("cooling_corridor_signal")).casefold()
    cooling_signal = raw_cooling_signal if raw_cooling_signal in {"strong", "moderate", "weak"} else ""
    heat_risk = next(
        (
            normalized
            for normalized in (
                _normalized_heat_risk(merged_facts.get("heat_resilience_risk")),
                _normalized_heat_risk(merged_facts.get("urban_heat_risk")),
                _normalized_heat_risk(merged_facts.get("summer_heat_risk")),
            )
            if normalized
        ),
        "",
    )
    official_source = _first_verified_official_source(merged_facts, {"heat_resilience", "cooling_corridor"})
    official_summary = _meaningful_evidence_text(official_source.get("summary"))
    has_shade_signal = _explicit_positive_signal(merged_facts.get("tree_shade_signal")) or _explicit_positive_signal(
        merged_facts.get("green_shade_signal")
    )
    if not any((cooling_summary, cooling_signal, heat_risk, official_summary, has_shade_signal)):
        return None
    summary = (
        cooling_summary
        or official_summary
        or (
            "Nearby tree or courtyard shade can soften summer heat for this address."
            if has_shade_signal
            else (
                f"Summer heat risk is reported as {heat_risk} for this address."
                if heat_risk
                else "Summer heat context is attached for this address."
            )
        )
    )
    uncertainty = "attached climate context"
    if cooling_signal in {"strong", "moderate", "weak"}:
        uncertainty = f"microclimate hint ({cooling_signal})"
    source_name = (
        _string(official_source.get("source_label"))
        or _string(official_source.get("provider"))
        or "Property facts"
    )
    detail_parts = [_sentence(summary), _sentence(f"From {source_name}"), _sentence(f"Signal: {uncertainty}")]
    return {
        "layer_key": _string(layer.get("layer_key")),
        "title": _string(layer.get("title")) or "Summer heat",
        "ui_state": "verified",
        "tag": "Ready",
        "detail": " ".join(part for part in detail_parts if part),
        "source_name": source_name,
        "source_url": _safe_public_http_url(official_source.get("source_url")),
        "article_url": "",
        "cache_updated_at": "",
        "source_updated_at": "",
        "source_checked_at": "",
        "source_temporality": "",
        "source_cadence_class": _string(layer.get("source_cadence_class")),
        "reference_period": "",
        "temporal_status": "derived_non_production",
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
    stale_after_days: float = EVIDENCE_OVERLAY_CACHE_MAX_AGE_HOURS / 24.0,
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
