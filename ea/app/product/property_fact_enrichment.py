from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping, Sequence


PROPERTY_FACT_ENRICHMENT_SCHEMA_VERSION = "propertyquarry.fact-enrichment.v1"
PROPERTY_FACT_SCORE_ALGORITHM_VERSION = "propertyquarry.fact-score-state.v1"
PROPERTY_FACT_GEO_BUNDLE_KIND = "optional-geo-v1"


def _distance_fact_spec(
    *,
    key: str,
    aliases: Sequence[str],
    label: str,
    search_label: str,
    preference_keys: Sequence[str] = (),
    poi_keys: Sequence[str] = (),
    provider: str = "openstreetmap_overpass",
    evidence_providers: Sequence[str] = (),
    strict_evidence_provider: bool = False,
    default_lazy: bool = False,
    search_supported: bool = True,
) -> Mapping[str, object]:
    """Build one immutable row in the shared distance-fact registry."""
    normalized_preferences = tuple(str(value) for value in preference_keys)
    required_preferences = tuple(
        value for value in normalized_preferences if value.startswith("max_distance_to_")
    )
    return MappingProxyType(
        {
            "key": key,
            "aliases": tuple(dict.fromkeys((key, *(str(value) for value in aliases)))),
            "label": label,
            "search_label": search_label,
            "preference_keys": normalized_preferences,
            "required_preference_keys": required_preferences,
            "poi_keys": tuple(str(value) for value in poi_keys),
            "provider": provider,
            "evidence_providers": tuple(str(value) for value in evidence_providers),
            "strict_evidence_provider": bool(strict_evidence_provider),
            "default_lazy": bool(default_lazy),
            "search_supported": bool(search_supported),
        }
    )


# Canonical distance-fact registry shared by detail enrichment and search-time
# gating. Keep provider keys here so a new distance preference cannot silently
# become rankable without a corresponding fact source.
PROPERTY_FACT_DISTANCE_SPECS: tuple[Mapping[str, object], ...] = (
    _distance_fact_spec(
        key="nearest_supermarket_m",
        aliases=("distance_supermarket_m",),
        label="Supermarket distance",
        search_label="supermarket",
        preference_keys=("max_distance_to_supermarket_m", "prefer_supermarket_nearby"),
        poi_keys=("shop=supermarket", "shop=convenience", "shop=greengrocer"),
        default_lazy=True,
    ),
    _distance_fact_spec(
        key="nearest_playground_m",
        aliases=("distance_playground_m",),
        label="Playground distance",
        search_label="playground",
        preference_keys=("max_distance_to_playground_m", "prefer_playgrounds_nearby"),
        poi_keys=("leisure=playground",),
        default_lazy=True,
    ),
    _distance_fact_spec(
        key="nearest_pharmacy_m",
        aliases=("distance_pharmacy_m",),
        label="Pharmacy distance",
        search_label="pharmacy",
        preference_keys=("max_distance_to_pharmacy_m", "prefer_pharmacy_nearby"),
        poi_keys=("amenity=pharmacy",),
        default_lazy=True,
    ),
    _distance_fact_spec(
        key="nearest_medical_care_m",
        aliases=("distance_medical_care_m",),
        label="Medical-care distance",
        search_label="medical care",
        preference_keys=("max_distance_to_medical_care_m", "prefer_medical_care_nearby"),
        poi_keys=("amenity=doctors", "amenity=clinic", "amenity=hospital"),
        default_lazy=True,
    ),
    _distance_fact_spec(
        key="nearest_subway_m",
        aliases=("nearest_transit_m", "distance_underground_m", "distance_subway_m"),
        label="Underground distance",
        search_label="underground",
        preference_keys=("max_distance_to_subway_m", "prefer_subway_nearby"),
        poi_keys=("railway=subway_entrance",),
        default_lazy=True,
    ),
    _distance_fact_spec(
        key="nearest_kindergarten_m",
        aliases=("nearest_school_m", "distance_kindergarten_m"),
        label="Kindergarten distance",
        search_label="kindergarten",
        preference_keys=("max_distance_to_kindergarten_m",),
        poi_keys=("schoolatlas=kindergarten",),
        provider="schoolatlas",
        evidence_providers=("schoolatlas",),
        strict_evidence_provider=True,
    ),
    _distance_fact_spec(
        key="nearest_full_day_primary_school_m",
        aliases=("nearest_school_m", "distance_full_day_primary_school_m"),
        label="Full-day primary-school distance",
        search_label="full-day primary school",
        preference_keys=("max_distance_to_ganztags_volksschule_m",),
        poi_keys=("schoolatlas=full_day_primary_school",),
        provider="schoolatlas",
        evidence_providers=("schoolatlas",),
        strict_evidence_provider=True,
    ),
    _distance_fact_spec(
        key="nearest_half_day_primary_school_m",
        aliases=("nearest_school_m", "distance_half_day_primary_school_m"),
        label="Half-day primary-school distance",
        search_label="half-day primary school",
        preference_keys=("max_distance_to_halbtags_volksschule_m",),
        poi_keys=("schoolatlas=half_day_primary_school",),
        provider="schoolatlas",
        evidence_providers=("schoolatlas",),
        strict_evidence_provider=True,
    ),
    _distance_fact_spec(
        key="nearest_library_m",
        aliases=("distance_library_m",),
        label="Library distance",
        search_label="library",
        preference_keys=("max_distance_to_library_m", "prefer_libraries_nearby"),
        poi_keys=("amenity=library",),
    ),
    _distance_fact_spec(
        key="nearest_zoo_m",
        aliases=("distance_zoo_m",),
        label="Zoo distance",
        search_label="zoo",
        preference_keys=("max_distance_to_zoo_m", "prefer_zoo_nearby"),
        poi_keys=("tourism=zoo",),
    ),
    _distance_fact_spec(
        key="nearest_market_m",
        aliases=("distance_market_m",),
        label="Market distance",
        search_label="market",
        preference_keys=("max_distance_to_market_m", "prefer_markets_nearby"),
        poi_keys=("amenity=marketplace",),
    ),
    _distance_fact_spec(
        key="nearest_hardware_store_m",
        aliases=("nearest_baumarkt_m", "distance_hardware_store_m"),
        label="Hardware-store distance",
        search_label="hardware store",
        preference_keys=("max_distance_to_hardware_store_m", "prefer_hardware_store_nearby"),
        poi_keys=("shop=doityourself", "shop=hardware"),
    ),
    _distance_fact_spec(
        key="nearest_shopping_center_m",
        aliases=("nearest_shopping_centre_m", "distance_shopping_center_m"),
        label="Shopping-center distance",
        search_label="shopping center",
        preference_keys=("max_distance_to_shopping_center_m", "prefer_shopping_center_nearby"),
        poi_keys=("shop=mall",),
    ),
    _distance_fact_spec(
        key="nearest_shopping_street_m",
        aliases=("distance_shopping_street_m",),
        label="Shopping-street distance",
        search_label="shopping street",
        preference_keys=("max_distance_to_shopping_street_m", "prefer_shopping_street_nearby"),
        poi_keys=("highway=pedestrian",),
    ),
    _distance_fact_spec(
        key="nearest_theatre_m",
        aliases=("nearest_theater_m", "distance_theatre_m", "distance_theater_m"),
        label="Theatre distance",
        search_label="theatre",
        preference_keys=("max_distance_to_theatre_m", "prefer_theatre_nearby"),
        poi_keys=("amenity=theatre",),
    ),
    _distance_fact_spec(
        key="nearest_public_pool_m",
        aliases=("nearest_swimming_pool_m", "distance_public_pool_m"),
        label="Public-pool distance",
        search_label="public pool",
        preference_keys=("max_distance_to_public_pool_m", "prefer_public_pool_nearby"),
        poi_keys=("leisure=swimming_pool",),
    ),
    _distance_fact_spec(
        key="nearest_starbucks_m",
        aliases=("distance_starbucks_m",),
        label="Starbucks distance",
        search_label="Starbucks",
        preference_keys=("max_distance_to_starbucks_m", "prefer_starbucks_nearby"),
        poi_keys=("brand=starbucks", "name~=starbucks"),
    ),
    _distance_fact_spec(
        key="nearest_fitness_center_m",
        aliases=("nearest_fitness_centre_m", "nearest_gym_m", "distance_fitness_center_m"),
        label="Fitness-center distance",
        search_label="fitness center",
        preference_keys=("max_distance_to_fitness_center_m", "prefer_fitness_center_nearby"),
        poi_keys=("leisure=fitness_centre", "amenity=gym", "sport=fitness"),
    ),
    _distance_fact_spec(
        key="nearest_cinema_m",
        aliases=("distance_cinema_m",),
        label="Cinema distance",
        search_label="cinema",
        preference_keys=("max_distance_to_cinema_m", "prefer_cinema_nearby"),
        poi_keys=("amenity=cinema",),
    ),
    _distance_fact_spec(
        key="nearest_bouldering_m",
        aliases=("nearest_climbing_m", "distance_bouldering_m"),
        label="Bouldering distance",
        search_label="bouldering",
        preference_keys=("max_distance_to_bouldering_m", "prefer_bouldering_nearby"),
        poi_keys=("sport=climbing", "sport=bouldering", "name~=boulder"),
    ),
    _distance_fact_spec(
        key="nearest_dog_park_m",
        aliases=("distance_dog_park_m",),
        label="Dog-park distance",
        search_label="dog park",
        preference_keys=("max_distance_to_dog_park_m", "prefer_dog_park_nearby"),
        poi_keys=("leisure=dog_park", "amenity=dog_park"),
    ),
    _distance_fact_spec(
        key="nearest_good_cafe_m",
        aliases=("nearest_cafe_m", "distance_good_cafe_m"),
        label="Quality-verified café distance",
        search_label="quality-verified café",
        preference_keys=("max_distance_to_good_cafe_m", "prefer_good_cafe_nearby"),
        poi_keys=("amenity=cafe+independent_quality_evidence",),
        provider="quality_verified_cafe_source",
        evidence_providers=("quality_verified_cafe_source",),
        strict_evidence_provider=True,
    ),
    _distance_fact_spec(
        key="nearest_tram_bus_m",
        aliases=("nearest_surface_transit_m", "distance_tram_bus_m"),
        label="Tram/bus distance",
        search_label="tram or bus",
        poi_keys=("railway=tram_stop", "highway=bus_stop"),
        search_supported=False,
    ),
    _distance_fact_spec(
        key="nearest_flowing_water_m",
        aliases=("distance_flowing_water_m",),
        label="Flowing-water distance",
        search_label="flowing water",
        poi_keys=("waterway~=river|riverbank|canal|stream|brook", "natural=water"),
        search_supported=False,
    ),
)


def property_fact_distance_specs(
    *,
    search_supported_only: bool = False,
) -> tuple[dict[str, object], ...]:
    """Return defensive copies of the shared bounded distance-fact registry."""
    return tuple(
        {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in spec.items()
        }
        for spec in PROPERTY_FACT_DISTANCE_SPECS
        if not search_supported_only or bool(spec.get("search_supported"))
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


def _fact_spec_is_relevant(
    *,
    spec: Mapping[str, object],
    facts: Mapping[str, object],
    preferences: Mapping[str, object],
    nodes: Sequence[Mapping[str, object]],
) -> bool:
    """Limit detail work to baseline facts plus facts selected by the user."""
    if bool(spec.get("default_lazy")):
        return True
    canonical_key = _normalized_text(spec.get("key"))
    aliases = tuple(str(value) for value in tuple(spec.get("aliases") or ()))
    preference_keys = tuple(str(value) for value in tuple(spec.get("preference_keys") or ()))
    if property_fact_value(facts, aliases)[0] is not None:
        return True
    all_keys = {
        canonical_key,
        *(_normalized_text(value) for value in aliases),
        *(_normalized_text(value) for value in preference_keys),
    }
    if _explicit_priority_keys(preferences, "required").intersection(all_keys):
        return True
    if _explicit_priority_keys(preferences, "lazy").intersection(all_keys):
        return True
    if any(_active_preference(preferences.get(key)) for key in preference_keys):
        return True
    for node in nodes:
        node_key = _normalized_text(
            node.get("key") or node.get("preference_key") or node.get("name")
        )
        node_value = node.get("value") if "value" in node else node.get("value_json", True)
        if node_key in all_keys and _active_preference(node_value):
            return True
    return False


def _evidence_for_fact(
    facts: Mapping[str, object],
    key: str,
    aliases: Sequence[str] = (),
) -> dict[str, object]:
    evidence_map = facts.get("property_fact_evidence")
    if not isinstance(evidence_map, Mapping):
        return {}
    for evidence_key in tuple(dict.fromkeys((key, *(str(value) for value in aliases)))):
        raw = evidence_map.get(evidence_key)
        if isinstance(raw, Mapping):
            return dict(raw)
    return {}


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


def _evidence_provider_is_allowed(
    evidence: Mapping[str, object],
    spec: Mapping[str, object],
) -> bool:
    allowed = {
        _normalized_text(value)
        for value in tuple(spec.get("evidence_providers") or ())
        if _normalized_text(value)
    }
    return not allowed or _normalized_text(evidence.get("provider")) in allowed


def _required_evidence_is_fresh(
    evidence: Mapping[str, object],
    spec: Mapping[str, object],
) -> bool:
    if (
        evidence.get("coordinate_exact") is not True
        or not str(evidence.get("provider") or "").strip()
        or not str(evidence.get("source_fingerprint") or "").startswith("sha256:")
        or not _evidence_provider_is_allowed(evidence, spec)
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
    for spec in PROPERTY_FACT_DISTANCE_SPECS:
        if not _fact_spec_is_relevant(
            spec=spec,
            facts=facts,
            preferences=normalized_preferences,
            nodes=preference_nodes,
        ):
            continue
        aliases = tuple(str(value) for value in tuple(spec.get("aliases") or ()))
        value, source_key = property_fact_value(facts, aliases)
        key = str(spec.get("key") or "").strip()
        evidence = _evidence_for_fact(facts, key, aliases)
        priority = _fact_priority(
            spec=spec,
            preferences=normalized_preferences,
            nodes=preference_nodes,
        )
        state = "resolved" if value is not None else "unknown"
        if (
            value is not None
            and priority == "required"
            and not _required_evidence_is_fresh(evidence, spec)
        ):
            state = "stale"
        elif (
            value is not None
            and bool(spec.get("strict_evidence_provider"))
            and not _evidence_provider_is_allowed(evidence, spec)
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
