from __future__ import annotations

import math


# Lightweight request/storage contract for the distance-fact catalog.  Keep
# this module dependency-free so API models and storage normalization can load
# it while the product package is still being initialized.
PROPERTY_DISTANCE_RADIUS_KEY_GROUPS: tuple[tuple[str, ...], ...] = (
    ("max_distance_to_supermarket_m",),
    ("max_distance_to_playground_m",),
    ("max_distance_to_pharmacy_m",),
    ("max_distance_to_medical_care_m",),
    ("max_distance_to_subway_m", "max_distance_to_underground_m"),
    ("max_distance_to_university_m",),
    ("max_distance_to_kindergarten_m",),
    ("max_distance_to_ganztags_volksschule_m",),
    ("max_distance_to_halbtags_volksschule_m",),
    ("max_distance_to_library_m",),
    ("max_distance_to_zoo_m",),
    ("max_distance_to_market_m",),
    ("max_distance_to_hardware_store_m",),
    ("max_distance_to_shopping_center_m",),
    ("max_distance_to_shopping_street_m",),
    ("max_distance_to_theatre_m",),
    ("max_distance_to_public_pool_m",),
    ("max_distance_to_starbucks_m",),
    ("max_distance_to_fitness_center_m",),
    ("max_distance_to_cinema_m",),
    ("max_distance_to_bouldering_m",),
    ("max_distance_to_dog_park_m",),
    ("max_distance_to_good_cafe_m",),
)


def property_distance_preference_keys(
    *,
    canonical_only: bool = False,
) -> tuple[str, ...]:
    """Return canonical catalog radius keys and bounded compatibility aliases."""
    return tuple(
        key
        for group in PROPERTY_DISTANCE_RADIUS_KEY_GROUPS
        for key in (group[:1] if canonical_only else group)
    )


def property_distance_importance_key(preference_key: object) -> str:
    """Return the importance companion for one registry radius key."""
    normalized = str(preference_key or "").strip()
    if not normalized:
        return ""
    if normalized.endswith("_m"):
        return f"{normalized[:-2]}_importance"
    return f"{normalized}_importance"


def normalize_property_distance_importance(
    value: object,
    *,
    default: str = "nice_to_have",
) -> str:
    """Canonicalize the four search/detail distance-importance states."""
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"must", "required", "hard", "strict", "must_have"}:
        return "must_have"
    if normalized in {"important", "high", "strong", "strong_wish"}:
        return "strong_wish"
    if normalized in {"nice", "low", "soft", "lazy", "optional", "nice_to_have"}:
        return "nice_to_have"
    if normalized in {"avoid", "aversion"}:
        return "avoid"
    return default


def normalize_property_distance_preference_pairs(
    preferences: dict[str, object] | None,
    *,
    default_active_importance: str = "nice_to_have",
) -> dict[str, object]:
    """Keep importance only beside an active registered radius.

    Compatibility aliases in one key group share an importance value.  An
    active radius with no explicit importance gets the lazy/default state;
    orphan importance never turns a neutral row into an active preference.
    """
    payload = dict(preferences or {})
    normalized_default = normalize_property_distance_importance(
        default_active_importance,
        default="nice_to_have",
    )
    for group in PROPERTY_DISTANCE_RADIUS_KEY_GROUPS:
        active_keys: list[str] = []
        for radius_key in group:
            value = payload.get(radius_key)
            if isinstance(value, bool) or value in (None, ""):
                continue
            try:
                numeric_value = float(str(value).strip())
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric_value) and numeric_value > 0:
                active_keys.append(radius_key)
        importance_keys = tuple(
            property_distance_importance_key(radius_key)
            for radius_key in group
        )
        importance = next(
            (
                normalized
                for importance_key in importance_keys
                if (
                    normalized := normalize_property_distance_importance(
                        payload.get(importance_key),
                        default="",
                    )
                )
            ),
            normalized_default,
        )
        for importance_key in importance_keys:
            payload.pop(importance_key, None)
        for radius_key in active_keys:
            payload[property_distance_importance_key(radius_key)] = importance
    return payload
