from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence


PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION = "propertyquarry.fact-enrichment.v1"
PROPERTY_FACT_SCORE_ALGORITHM_VERSION = "propertyquarry.fact-score-state.v1"
PROPERTY_FACT_GEO_BUNDLE_KIND = "optional-geo-v1"


_GEO_FACT_SPECS: tuple[dict[str, object], ...] = (
    {
        "key": "nearest_supermarket_m",
        "aliases": ("nearest_supermarket_m", "distance_supermarket_m"),
        "label": "Supermarket distance",
        "preference_keys": ("max_distance_to_supermarket_m", "prefer_supermarket_nearby"),
        "required_preference_keys": ("max_distance_to_supermarket_m",),
    },
    {
        "key": "nearest_playground_m",
        "aliases": ("nearest_playground_m", "distance_playground_m"),
        "label": "Playground distance",
        "preference_keys": ("max_distance_to_playground_m", "prefer_playgrounds_nearby"),
        "required_preference_keys": ("max_distance_to_playground_m",),
    },
    {
        "key": "nearest_pharmacy_m",
        "aliases": ("nearest_pharmacy_m", "distance_pharmacy_m"),
        "label": "Pharmacy distance",
        "preference_keys": ("max_distance_to_pharmacy_m", "prefer_pharmacy_nearby"),
        "required_preference_keys": ("max_distance_to_pharmacy_m",),
    },
    {
        "key": "nearest_medical_care_m",
        "aliases": ("nearest_medical_care_m",),
        "label": "Medical-care distance",
        "preference_keys": ("max_distance_to_medical_care_m", "prefer_medical_care_nearby"),
        "required_preference_keys": ("max_distance_to_medical_care_m",),
    },
    {
        "key": "nearest_subway_m",
        "aliases": ("nearest_subway_m", "nearest_transit_m", "distance_underground_m"),
        "label": "Underground distance",
        "preference_keys": ("max_distance_to_subway_m", "prefer_subway_nearby"),
        "required_preference_keys": ("max_distance_to_subway_m",),
    },
)


def _normalized_text(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _active_preference(value: object) -> bool:
    if value in (None, "", False, (), [], {}):
        return False
    if isinstance(value, str):
        return _normalized_text(value) not in {
            "0",
            "0.0",
            "false",
            "off",
            "none",
            "null",
            "neutral",
            "any",
        }
    if isinstance(value, (int, float)):
        return float(value) > 0.0
    return True


def _bounded_positive_distance(value: object) -> int | None:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= 5_000_000 else None


def property_fact_value(
    facts: Mapping[str, object],
    aliases: Sequence[str],
) -> tuple[int | None, str]:
    for alias in aliases:
        value = _bounded_positive_distance(facts.get(alias))
        if value is not None:
            return value, alias
    return None, ""


def property_fact_candidate_ref(candidate: Mapping[str, object]) -> str:
    explicit = str(candidate.get("candidate_ref") or candidate.get("research_candidate_ref") or "").strip()
    if explicit:
        return explicit
    raw = "|".join(
        str(candidate.get(key) or "").strip()
        for key in ("title", "property_url", "review_url", "source_ref", "source_label")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _explicit_priority_keys(preferences: Mapping[str, object], priority: str) -> set[str]:
    keys: set[str] = set()
    list_keys = {
        "required": (
            "required_fact_keys",
            "must_have_fact_keys",
            "avoid_fact_keys",
            "strong_wish_fact_keys",
        ),
        "lazy": ("nice_to_have_fact_keys", "lazy_fact_keys"),
    }
    for list_key in list_keys.get(priority, ()):
        raw_values = preferences.get(list_key)
        values = raw_values if isinstance(raw_values, (list, tuple, set)) else str(raw_values or "").split(",")
        keys.update(_normalized_text(value) for value in values if _normalized_text(value))
    raw_priorities = preferences.get("fact_priorities")
    if isinstance(raw_priorities, Mapping):
        keys.update(
            _normalized_text(key)
            for key, value in raw_priorities.items()
            if _normalized_text(value) == priority
        )
    return keys


def _node_priority(
    *,
    preference_keys: Sequence[str],
    nodes: Sequence[Mapping[str, object]],
) -> str:
    normalized_keys = {_normalized_text(key) for key in preference_keys}
    for node in nodes:
        key = _normalized_text(node.get("key") or node.get("preference_key") or node.get("name"))
        node_value = node.get("value") if "value" in node else node.get("value_json", True)
        if key not in normalized_keys or not _active_preference(node_value):
            continue
        category = _normalized_text(node.get("category") or node.get("kind") or node.get("type"))
        strength = _normalized_text(node.get("strength") or node.get("priority") or node.get("weight"))
        if category in {"constraint", "must_have", "must", "aversion", "avoid"}:
            return "required"
        if category in {"soft_preference", "preference", "wish"} and strength in {
            "high",
            "strong",
            "critical",
            "must",
            "3",
        }:
            return "required"
    return "lazy"


def _explicit_importance_priority(
    *,
    preference_keys: Sequence[str],
    preferences: Mapping[str, object],
) -> str | None:
    """Map the current request's importance selector before stored-profile defaults."""
    required_importance = {
        "avoid",
        "critical",
        "high",
        "must",
        "must_have",
        "required",
        "strong",
        "strong_wish",
        "3",
    }
    lazy_importance = {
        "lazy",
        "low",
        "nice",
        "nice_to_have",
        "optional",
        "1",
    }
    for preference_key in preference_keys:
        if not _active_preference(preferences.get(preference_key)):
            continue
        importance_keys = [f"{preference_key}_importance"]
        if preference_key.endswith("_m"):
            importance_keys.insert(0, f"{preference_key[:-2]}_importance")
        for importance_key in importance_keys:
            if importance_key not in preferences:
                continue
            importance = _normalized_text(preferences.get(importance_key))
            if importance in required_importance:
                return "required"
            if importance in lazy_importance:
                return "lazy"
    return None


def _fact_priority(
    *,
    spec: Mapping[str, object],
    preferences: Mapping[str, object],
    nodes: Sequence[Mapping[str, object]],
) -> str:
    canonical_key = _normalized_text(spec.get("key"))
    aliases = tuple(str(value) for value in tuple(spec.get("aliases") or ()))
    preference_keys = tuple(str(value) for value in tuple(spec.get("preference_keys") or ()))
    all_keys = {canonical_key, *(_normalized_text(value) for value in aliases), *(_normalized_text(value) for value in preference_keys)}
    required_keys = _explicit_priority_keys(preferences, "required")
    lazy_keys = _explicit_priority_keys(preferences, "lazy")
    if required_keys.intersection(all_keys):
        return "required"
    if lazy_keys.intersection(all_keys):
        return "lazy"
    importance_priority = _explicit_importance_priority(
        preference_keys=preference_keys,
        preferences=preferences,
    )
    if importance_priority is not None:
        return importance_priority
    for preference_key in tuple(spec.get("required_preference_keys") or ()):
        if _active_preference(preferences.get(str(preference_key))):
            return "required"
    strength_map = preferences.get("preference_strengths")
    if isinstance(strength_map, Mapping):
        for preference_key in preference_keys:
            if _active_preference(preferences.get(preference_key)) and _normalized_text(strength_map.get(preference_key)) in {
                "high",
                "strong",
                "critical",
                "must",
                "3",
            }:
                return "required"
    return _node_priority(preference_keys=preference_keys, nodes=nodes)


def _evidence_for_fact(facts: Mapping[str, object], key: str) -> dict[str, object]:
    evidence_map = facts.get("property_fact_evidence")
    if not isinstance(evidence_map, Mapping):
        return {}
    raw = evidence_map.get(key)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _evidence_is_stale(evidence: Mapping[str, object]) -> bool:
    expires_at = str(evidence.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return expires <= datetime.now(timezone.utc)


def _required_evidence_is_fresh(evidence: Mapping[str, object]) -> bool:
    if (
        evidence.get("coordinate_exact") is not True
        or not str(evidence.get("provider") or "").strip()
        or not str(evidence.get("source_fingerprint") or "").startswith("sha256:")
    ):
        return False
    observed_at = str(evidence.get("observed_at") or "").strip()
    expires_at = str(evidence.get("expires_at") or "").strip()
    if not observed_at or not expires_at:
        return False
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or expires.tzinfo is None:
            return False
    except (TypeError, ValueError):
        return False
    now = datetime.now(timezone.utc)
    return observed <= now < expires


def _distance_is_coordinate_estimate(
    facts: Mapping[str, object],
    evidence: Mapping[str, object],
) -> bool:
    if "coordinate_exact" in evidence:
        return evidence.get("coordinate_exact") is not True
    precision = _normalized_text(facts.get("map_location_precision"))
    source = str(facts.get("map_location_source") or "").strip().casefold()
    if precision in {"address", "building", "exact", "parcel", "property", "rooftop"}:
        return False
    return bool(
        precision in {
            "area",
            "centroid",
            "city",
            "district",
            "locality",
            "postal",
            "postal_area",
            "postcode",
            "region",
        }
        or "postal area" in source
        or "centroid" in source
        or "estimate" in source
    )


def property_fact_requirement_plan(
    *,
    facts: Mapping[str, object],
    preferences: Mapping[str, object] | None = None,
    preference_nodes: Sequence[Mapping[str, object]] = (),
    include_resolved: bool = True,
) -> list[dict[str, object]]:
    normalized_preferences = dict(preferences or {})
    plan: list[dict[str, object]] = []
    for spec in _GEO_FACT_SPECS:
        aliases = tuple(str(value) for value in tuple(spec.get("aliases") or ()))
        value, source_key = property_fact_value(facts, aliases)
        key = str(spec.get("key") or "").strip()
        evidence = _evidence_for_fact(facts, key)
        priority = _fact_priority(
            spec=spec,
            preferences=normalized_preferences,
            nodes=preference_nodes,
        )
        state = "resolved" if value is not None else "unknown"
        if (
            value is not None
            and priority == "required"
            and not _required_evidence_is_fresh(evidence)
        ):
            state = "stale"
        elif value is not None and _distance_is_coordinate_estimate(facts, evidence):
            state = "stale"
        elif value is not None and evidence and _evidence_is_stale(evidence):
            state = "stale"
        if not include_resolved and state == "resolved":
            continue
        plan.append(
            {
                "key": key,
                "aliases": list(aliases),
                "label": str(spec.get("label") or key).strip(),
                "state": state,
                "priority": priority,
                "affects_score": True,
                "value": value,
                "display_value": f"{value:,} m".replace(",", " ") if value is not None else "",
                "source_key": source_key,
                "provenance": evidence,
                "error": {},
            }
        )
    return plan


def property_fact_score_state(plan: Sequence[Mapping[str, object]]) -> str:
    unresolved = [row for row in plan if str(row.get("state") or "unknown") != "resolved"]
    if any(str(row.get("priority") or "lazy") == "required" for row in unresolved):
        return "evaluating"
    if any(bool(row.get("affects_score")) for row in unresolved):
        return "provisional"
    return "final"


def _score_value(candidate: Mapping[str, object]) -> float | None:
    assessment = candidate.get("assessment")
    values = (
        candidate.get("fit_score"),
        candidate.get("score"),
        assessment.get("fit_score") if isinstance(assessment, Mapping) else None,
    )
    for raw in values:
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            continue
        if 0.0 <= parsed <= 100.0:
            return round(parsed, 2)
    return None


def property_fact_input_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def property_fact_score_projection(
    *,
    candidate: Mapping[str, object],
    plan: Sequence[Mapping[str, object]],
    preferences: Mapping[str, object] | None = None,
    previous_score: float | None = None,
    changed_reasons: Sequence[str] = (),
) -> dict[str, object]:
    state = property_fact_score_state(plan)
    raw_score = _score_value(candidate)
    current = None if state == "evaluating" else raw_score
    previous = previous_score
    if previous is None:
        prior_projection = candidate.get("score_projection")
        if isinstance(prior_projection, Mapping):
            try:
                previous = float(prior_projection.get("current"))
            except (TypeError, ValueError):
                previous = None
    if previous is None and current is not None:
        previous = current
    delta = round(current - previous, 2) if current is not None and previous is not None else None
    fact_digest_payload = [
        {
            "key": row.get("key"),
            "state": row.get("state"),
            "value": row.get("value"),
            "priority": row.get("priority"),
            "observed_at": dict(row.get("provenance") or {}).get("observed_at")
            if isinstance(row.get("provenance"), Mapping)
            else "",
        }
        for row in plan
    ]
    return {
        "state": state,
        "previous": previous,
        "current": current,
        "delta": delta,
        "changed_reasons": [str(value).strip() for value in changed_reasons if str(value).strip()][:8],
        "ranking_eligible": state != "evaluating" and current is not None,
        "algorithm_version": PROPERTY_FACT_SCORE_ALGORITHM_VERSION,
        "facts_digest": property_fact_input_digest(fact_digest_payload),
        "preference_digest": property_fact_input_digest(dict(preferences or {})),
    }


def property_fact_job_id(
    *,
    principal_id: str,
    run_id: str,
    candidate_ref: str,
    source_fingerprint: str,
    request_digest: str = "",
) -> str:
    raw = "|".join(
        (
            str(principal_id or "").strip(),
            str(run_id or "").strip(),
            str(candidate_ref or "").strip(),
            PROPERTY_FACT_GEO_BUNDLE_KIND,
            str(source_fingerprint or "").strip(),
            str(request_digest or "").strip(),
            PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION,
        )
    )
    return "pfe_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def property_fact_expiry(*, observed_at: datetime | None = None, hours: int = 24) -> str:
    observed = observed_at or datetime.now(timezone.utc)
    return (observed + timedelta(hours=max(1, min(int(hours), 168)))).isoformat()
