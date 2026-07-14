from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from app.product import service as property_service_module
from app.product.service import ProductService
from app.services.property_market_catalog import CUSTOMER_SEARCH_COUNTRY_ORDER, PROVIDERS, PropertyProviderSpec
from tests.product_test_helpers import build_property_client, start_workspace


TERMINAL_RUN_STATUSES = {"processed", "completed_partial", "failed", "cancelled"}
MATCH_TIERS = ("external_id", "property_url", "source_ref", "title_scope")
INVALID_SOURCE_FETCH_REPAIR_RESOLUTIONS = {
    "suppressed_missing_location",
    "suppressed_location_scope",
    "suppressed_missing_price",
}
GENERATED_MEDIA_COUNTER_KEYS = (
    "tour_created_total",
    "pending_tour_total",
    "ready_tour_total",
    "flythrough_rendered_total",
    "flythrough_existing_total",
    "flythrough_failed_total",
)


@dataclass(slots=True)
class PrincipalContext:
    principal_id: str
    workspace_name: str = "PropertyQuarry Canary"


@dataclass(slots=True)
class NegativeControl:
    canonical_url: str = ""
    external_id: str = ""
    source_ref: str = ""
    title: str = ""
    district_hint: str = ""
    must_not_rank: bool = True


@dataclass(slots=True)
class TargetListing:
    provider: str
    country_code: str
    canonical_url: str
    title: str
    listing_mode: str
    property_type: str
    location_query: str
    external_id: str = ""
    source_ref: str = ""
    district_hint: str = ""
    postal_hint: str = ""
    price_eur: float = 0.0
    area_m2: float = 0.0
    rooms: float = 0.0
    selected_platforms: tuple[str, ...] = ()
    selected_districts: tuple[str, ...] = ()
    soft_preferences: dict[str, object] = field(default_factory=dict)
    negatives: tuple[NegativeControl, ...] = ()
    pool_size: int = 1
    picked_index: int = 0


@dataclass(slots=True)
class IdentityMatch:
    matched: bool
    tier: str = ""
    candidate_ref: str = ""
    property_url: str = ""
    title: str = ""
    rank: int = 0


@dataclass(slots=True)
class RepairTrace:
    repair_needed: bool = False
    repair_triggered: bool = False
    repair_executed: bool = False
    task_ids: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    resolutions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecoveryReport:
    case_key: str
    principal_id: str
    run_id: str
    watch_url: str
    provider: str
    target_title: str
    target_url: str
    pool_size: int
    picked_index: int
    run_status: str
    target_found: bool
    target_match_tier: str
    target_rank: int
    repair: RepairTrace
    generated_media_counters: dict[str, int]
    negative_hits: list[dict[str, object]]
    ranked_count: int
    attempt_index: int
    source_count: int
    event_count: int
    synthesized_brief: dict[str, object]
    provider_volatility: bool = False
    variant: str = "targeted"


def _manifest_path() -> Path:
    raw = str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_MANIFEST") or "").strip()
    if not raw:
        pytest.skip("PROPERTYQUARRY_TARGET_RECOVERY_MANIFEST not set")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"target-recovery manifest not found: {path}")
    return path


def _normalize_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (key, item)
        for key, item in query
        if str(key or "").strip().lower() not in {"utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"}
    ]
    normalized_query = urllib.parse.urlencode(sorted(filtered_query))
    return urllib.parse.urlunsplit((scheme, host, path, normalized_query, ""))


def _willhaben_ad_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=False))
    ad_id = str(query.get("adId") or query.get("adid") or "").strip()
    if ad_id:
        return ad_id
    match = re.search(r"-(\d{6,})/?$", parsed.path)
    if match:
        return str(match.group(1) or "").strip()
    return ""


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _coerce_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _load_cases() -> list[TargetListing]:
    if "PROPERTYQUARRY_TARGET_RECOVERY_MANIFEST" not in os.environ:
        return []
    payload = json.loads(_manifest_path().read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise AssertionError("PROPERTYQUARRY_TARGET_RECOVERY_MANIFEST must contain a list")
    cases: list[TargetListing] = []
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise AssertionError(f"manifest entry {index} must be an object")
        cases.append(_materialize_case_from_manifest_row(row, row_index=index))
    return cases


def _stable_pick_index(seed_basis: str, count: int) -> int:
    normalized = str(seed_basis or "").strip()
    if count <= 1:
        return 0
    total = 0
    for character in normalized:
        total = (total * 131 + ord(character)) % 2147483647
    return total % count


def _negative_controls(raw_items: object) -> tuple[NegativeControl, ...]:
    return tuple(
        NegativeControl(
            canonical_url=str(item.get("canonical_url") or "").strip(),
            external_id=str(item.get("external_id") or "").strip(),
            source_ref=str(item.get("source_ref") or "").strip(),
            title=str(item.get("title") or "").strip(),
            district_hint=str(item.get("district_hint") or "").strip(),
            must_not_rank=bool(item.get("must_not_rank", True)),
        )
        for item in list(raw_items or [])
        if isinstance(item, dict)
    )


def _target_listing_from_payload(
    payload: dict[str, object],
    *,
    provider: str,
    country_code: str,
    selected_platforms: tuple[str, ...],
    pool_size: int,
    picked_index: int,
) -> TargetListing:
    return TargetListing(
        provider=provider,
        country_code=country_code,
        canonical_url=str(payload.get("canonical_url") or "").strip(),
        title=str(payload.get("title") or "").strip(),
        listing_mode=str(payload.get("listing_mode") or "").strip().lower(),
        property_type=str(payload.get("property_type") or "").strip().lower(),
        location_query=str(payload.get("location_query") or "").strip(),
        external_id=str(payload.get("external_id") or "").strip(),
        source_ref=str(payload.get("source_ref") or "").strip(),
        district_hint=str(payload.get("district_hint") or "").strip(),
        postal_hint=str(payload.get("postal_hint") or "").strip(),
        price_eur=_coerce_float(payload.get("price_eur")),
        area_m2=_coerce_float(payload.get("area_m2")),
        rooms=_coerce_float(payload.get("rooms")),
        selected_platforms=selected_platforms,
        selected_districts=tuple(
            str(value or "").strip()
            for value in list(payload.get("selected_districts") or [])
            if str(value or "").strip()
        ),
        soft_preferences=dict(payload.get("soft_preferences") or {}) if isinstance(payload.get("soft_preferences"), dict) else {},
        negatives=_negative_controls(payload.get("negatives")),
        pool_size=pool_size,
        picked_index=picked_index,
    )


def _materialize_case_from_manifest_row(row: dict[str, object], *, row_index: int) -> TargetListing:
    provider = str(row.get("provider") or "").strip()
    country_code = str(row.get("country_code") or "").strip().upper()
    selected_platforms = tuple(
        str(value or "").strip()
        for value in list(row.get("selected_platforms") or [provider])
        if str(value or "").strip()
    )
    candidates = [dict(item) for item in list(row.get("candidates") or []) if isinstance(item, dict)]
    if not candidates:
        return _target_listing_from_payload(
            row,
            provider=provider,
            country_code=country_code,
            selected_platforms=selected_platforms,
            pool_size=1,
            picked_index=0,
        )
    seed = str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_SEED") or "tibor-watch").strip()
    pick_basis = f"{seed}|{country_code}|{provider}|{row_index}|{len(candidates)}"
    picked_index = _stable_pick_index(pick_basis, len(candidates))
    picked = dict(candidates[picked_index])
    if "soft_preferences" not in picked and isinstance(row.get("soft_preferences"), dict):
        picked["soft_preferences"] = dict(row.get("soft_preferences") or {})
    if "selected_districts" not in picked and isinstance(row.get("selected_districts"), list):
        picked["selected_districts"] = list(row.get("selected_districts") or [])
    if "negatives" not in picked and isinstance(row.get("negatives"), list):
        picked["negatives"] = list(row.get("negatives") or [])
    if not str(picked.get("listing_mode") or "").strip() and str(row.get("listing_mode") or "").strip():
        picked["listing_mode"] = row.get("listing_mode")
    if not str(picked.get("property_type") or "").strip() and str(row.get("property_type") or "").strip():
        picked["property_type"] = row.get("property_type")
    return _target_listing_from_payload(
        picked,
        provider=provider,
        country_code=country_code,
        selected_platforms=selected_platforms,
        pool_size=len(candidates),
        picked_index=picked_index,
    )


def _rank_threshold() -> int:
    try:
        return max(1, int(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_TARGET_RANK_MAX") or 5))
    except Exception:
        return 5


def _target_provider_matrix_enabled() -> bool:
    return str(os.environ.get("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "full",
    }


def _default_soft_filter_preferences(case: TargetListing) -> dict[str, object]:
    preferences: dict[str, object] = {
        "max_distance_to_library_m": 500,
        "max_distance_to_library_importance": "nice_to_have",
        "max_distance_to_playground_m": 500,
        "max_distance_to_playground_importance": "nice_to_have",
        "max_distance_to_shopping_center_m": 500,
        "max_distance_to_shopping_center_importance": "avoid",
        "max_distance_to_supermarket_m": 300,
        "max_distance_to_supermarket_importance": "nice_to_have",
        "prefer_good_air_quality": True,
        "prefer_low_crime_area": True,
        "require_parking_pressure_check": True,
    }
    if str(case.country_code or "").strip().upper() != "AT":
        preferences.pop("max_distance_to_playground_m", None)
        preferences.pop("max_distance_to_playground_importance", None)
    return preferences


def _synthesize_search_preferences(
    case: TargetListing,
    *,
    loosen_level: int = 0,
    soft_filters: bool = True,
    default_soft_filters: bool = False,
) -> dict[str, object]:
    if not case.country_code or not case.listing_mode or not case.property_type or not case.location_query:
        raise AssertionError(f"{case.provider or case.title}: manifest entry is missing required target facts")
    selected_platforms = list(case.selected_platforms or ((case.provider,) if case.provider else ()))
    if not selected_platforms:
        raise AssertionError(f"{case.title}: selected_platforms missing")
    try:
        max_results_per_source = max(
            1,
            min(10, int(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_MAX_RESULTS_PER_SOURCE") or 5)),
        )
    except Exception:
        max_results_per_source = 5
    preferences: dict[str, object] = {
        "country_code": case.country_code,
        "language_code": "de" if case.country_code == "AT" else "en",
        "listing_mode": case.listing_mode,
        "property_type": case.property_type if case.property_type in {"apartment", "house", "land", "office"} else "any",
        "location_query": case.location_query,
        "selected_platforms": selected_platforms,
        "property_search_enabled": True,
        "property_commercial": {
            "active_plan_key": str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PLAN_KEY") or "agent").strip().lower() or "agent",
            "status": "active",
            "active_until": "2999-01-01T00:00:00+00:00",
        },
        "max_results_per_source": max_results_per_source,
        "search_goal": "home",
        "investment_research_mode": "off",
        "search_mode": "discovery",
        "include_public_housing_signals": False,
        "include_developer_project_signals": False,
        "include_distressed_sale_signals": False,
        "use_stored_feedback_preferences": False,
        "preference_person_id": "self",
        "full_region_scope": False,
        "selected_districts": list(case.selected_districts),
    }
    if case.price_eur > 0:
        if case.listing_mode == "rent":
            multiplier = (1.03, 1.06, 1.10, 1.15, 1.20)[min(loosen_level, 4)]
        else:
            multiplier = (1.05, 1.08, 1.12, 1.18, 1.25)[min(loosen_level, 4)]
        preferences["max_price_eur"] = round(case.price_eur * multiplier, 2)
    if case.area_m2 > 0 and loosen_level <= 1:
        preferences["min_area_m2"] = max(1, int(case.area_m2 * 0.95))
    if case.rooms > 0 and loosen_level == 0:
        rounded_rooms = int(case.rooms) if float(case.rooms).is_integer() else 0
        if rounded_rooms > 0:
            preferences["min_rooms"] = rounded_rooms
    if loosen_level >= 3:
        preferences["property_type"] = "any"
    if soft_filters:
        if default_soft_filters:
            preferences.update(_default_soft_filter_preferences(case))
        for key, value in case.soft_preferences.items():
            preferences[str(key)] = value
    return preferences


def _assert_brief_satisfies_target(case: TargetListing, brief: dict[str, object]) -> None:
    max_price = _coerce_float(brief.get("max_price_eur"))
    if case.price_eur > 0 and max_price > 0 and case.price_eur > max_price:
        raise AssertionError(f"{case.title}: synthesized brief excludes target price")
    min_area = _coerce_float(brief.get("min_area_m2"))
    if case.area_m2 > 0 and min_area > 0 and case.area_m2 < min_area:
        raise AssertionError(f"{case.title}: synthesized brief excludes target area")
    min_rooms = _coerce_float(brief.get("min_rooms"))
    if case.rooms > 0 and min_rooms > 0 and case.rooms < min_rooms:
        raise AssertionError(f"{case.title}: synthesized brief excludes target room count")


def _watch_url(run_id: str) -> str:
    return f"/app/properties?run_id={urllib.parse.quote(run_id, safe='')}"


def _print_watch_banner(case: TargetListing, principal: PrincipalContext, run_id: str, *, variant: str = "targeted") -> None:
    sys.stderr.write(
        "\n".join(
            [
                "",
                f"[target-recovery] principal={principal.principal_id}",
                f"[target-recovery] provider={case.provider}",
                f"[target-recovery] variant={variant}",
                f"[target-recovery] target={case.title}",
                f"[target-recovery] run_id={run_id}",
                f"[target-recovery] watch={_watch_url(run_id)}",
                "",
            ]
        )
    )
    sys.stderr.flush()


def _candidate_rows(status_payload: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(status_payload.get("summary") or {}) if isinstance(status_payload.get("summary"), dict) else {}
    ranked = [dict(row) for row in list(summary.get("ranked_candidates") or []) if isinstance(row, dict)]
    if ranked:
        return ranked
    synthesized: list[dict[str, object]] = []
    for source in [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]:
        for candidate in [dict(row) for row in list(source.get("top_candidates") or []) if isinstance(row, dict)]:
            candidate.setdefault("source_label", str(source.get("source_label") or source.get("label") or "").strip())
            synthesized.append(candidate)
    synthesized.sort(key=lambda item: float(item.get("fit_score") or 0.0), reverse=True)
    for index, candidate in enumerate(synthesized, start=1):
        candidate.setdefault("rank", index)
    return synthesized


def _source_rows(status_payload: dict[str, object]) -> list[dict[str, object]]:
    summary = dict(status_payload.get("summary") or {}) if isinstance(status_payload.get("summary"), dict) else {}
    return [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]


def _title_scope_match(candidate: dict[str, object], case: TargetListing) -> bool:
    candidate_title = _normalize_text(candidate.get("title"))
    if candidate_title and candidate_title == _normalize_text(case.title):
        candidate_facts = dict(candidate.get("property_facts") or {}) if isinstance(candidate.get("property_facts"), dict) else {}
        combined_scope = " ".join(
            _normalize_text(value)
            for value in (
                candidate.get("source_scope_location"),
                candidate_facts.get("source_scope_location"),
                candidate_facts.get("postal_name"),
                candidate_facts.get("district"),
                case.location_query,
            )
            if str(value or "").strip()
        )
        return _normalize_text(case.location_query) in combined_scope or _normalize_text(case.district_hint) in combined_scope
    return False


def _match_candidate(candidate: dict[str, object], case: TargetListing) -> IdentityMatch:
    candidate_external_id = str(candidate.get("external_id") or candidate.get("listing_id") or "").strip()
    if case.external_id and candidate_external_id and case.external_id == candidate_external_id:
        return IdentityMatch(
            matched=True,
            tier="external_id",
            candidate_ref=str(candidate.get("candidate_ref") or "").strip(),
            property_url=str(candidate.get("property_url") or "").strip(),
            title=str(candidate.get("title") or "").strip(),
            rank=int(candidate.get("rank") or 0),
        )
    candidate_url = _normalize_url(candidate.get("property_url") or candidate.get("review_url") or candidate.get("packet_url"))
    if case.canonical_url and candidate_url and _normalize_url(case.canonical_url) == candidate_url:
        return IdentityMatch(
            matched=True,
            tier="property_url",
            candidate_ref=str(candidate.get("candidate_ref") or "").strip(),
            property_url=str(candidate.get("property_url") or "").strip(),
            title=str(candidate.get("title") or "").strip(),
            rank=int(candidate.get("rank") or 0),
        )
    case_willhaben_ad_id = _willhaben_ad_id(case.canonical_url)
    candidate_willhaben_ad_id = _willhaben_ad_id(candidate_url)
    if case_willhaben_ad_id and candidate_willhaben_ad_id and case_willhaben_ad_id == candidate_willhaben_ad_id:
        return IdentityMatch(
            matched=True,
            tier="property_url",
            candidate_ref=str(candidate.get("candidate_ref") or "").strip(),
            property_url=str(candidate.get("property_url") or "").strip(),
            title=str(candidate.get("title") or "").strip(),
            rank=int(candidate.get("rank") or 0),
        )
    candidate_source_ref = str(candidate.get("source_ref") or "").strip()
    if case.source_ref and candidate_source_ref and case.source_ref == candidate_source_ref:
        return IdentityMatch(
            matched=True,
            tier="source_ref",
            candidate_ref=str(candidate.get("candidate_ref") or "").strip(),
            property_url=str(candidate.get("property_url") or "").strip(),
            title=str(candidate.get("title") or "").strip(),
            rank=int(candidate.get("rank") or 0),
        )
    if _title_scope_match(candidate, case):
        return IdentityMatch(
            matched=True,
            tier="title_scope",
            candidate_ref=str(candidate.get("candidate_ref") or "").strip(),
            property_url=str(candidate.get("property_url") or "").strip(),
            title=str(candidate.get("title") or "").strip(),
            rank=int(candidate.get("rank") or 0),
        )
    return IdentityMatch(matched=False)


def _match_ranked_target(candidates: list[dict[str, object]], case: TargetListing) -> IdentityMatch:
    for candidate in candidates:
        match = _match_candidate(candidate, case)
        if match.matched:
            return match
    return IdentityMatch(matched=False)


def _match_negative(candidate: dict[str, object], control: NegativeControl) -> bool:
    if control.external_id:
        candidate_external_id = str(candidate.get("external_id") or candidate.get("listing_id") or "").strip()
        if candidate_external_id == control.external_id:
            return True
    if control.canonical_url:
        candidate_url = _normalize_url(candidate.get("property_url") or candidate.get("review_url") or candidate.get("packet_url"))
        if candidate_url and candidate_url == _normalize_url(control.canonical_url):
            return True
    if control.source_ref and str(candidate.get("source_ref") or "").strip() == control.source_ref:
        return True
    if control.title and _normalize_text(candidate.get("title")) == _normalize_text(control.title):
        return True
    return False


def _generated_media_counters(summary: dict[str, object]) -> dict[str, int]:
    counters: dict[str, int] = {}
    for key in GENERATED_MEDIA_COUNTER_KEYS:
        try:
            counters[key] = int(summary.get(key) or 0)
        except Exception:
            counters[key] = 0
    return counters


def _assert_no_generated_media(summary: dict[str, object]) -> dict[str, int]:
    counters = _generated_media_counters(summary)
    leaking = {key: value for key, value in counters.items() if value > 0}
    if leaking:
        raise AssertionError(
            "target-recovery canary triggered generated media side effects: "
            + ", ".join(f"{key}={value}" for key, value in sorted(leaking.items()))
        )
    return counters


def _list_repair_tasks(client, *, limit: int = 200) -> list[dict[str, object]]:
    response = client.get("/v1/human/tasks", params={"limit": limit})
    assert response.status_code == 200, response.text
    payload = response.json()
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _normalize_human_task_id(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized.removeprefix("human_task:")


def _current_run_repair_task_ids(status_payload: dict[str, object], *, run_id: str) -> set[str]:
    normalized_run_id = str(run_id or "").strip()
    status_run_id = str(status_payload.get("run_id") or "").strip()
    if not normalized_run_id or status_run_id != normalized_run_id:
        return set()
    summary = dict(status_payload.get("summary") or {}) if isinstance(status_payload.get("summary"), dict) else {}
    task_rows = [
        dict(row)
        for row in list(summary.get("provider_repair_tasks") or [])
        if isinstance(row, dict)
    ]
    for source in [dict(row) for row in list(summary.get("sources") or []) if isinstance(row, dict)]:
        task_rows.extend(
            dict(row)
            for row in list(source.get("provider_repair_tasks") or [])
            if isinstance(row, dict)
        )
    task_ids = {
        normalized
        for row in task_rows
        for normalized in (
            _normalize_human_task_id(
                row.get("human_task_id") or row.get("task_id") or row.get("queue_item_ref")
            ),
        )
        if normalized
    }
    for row in [dict(item) for item in list(summary.get("repair_receipts") or []) if isinstance(item, dict)]:
        if str(row.get("run_id") or "").strip() != normalized_run_id:
            continue
        normalized = _normalize_human_task_id(
            row.get("human_task_id") or row.get("task_id") or row.get("queue_item_ref")
        )
        if normalized:
            task_ids.add(normalized)
    return task_ids


def _matching_repair_tasks(
    tasks: list[dict[str, object]],
    case: TargetListing,
    *,
    baseline_task_ids: set[str],
    run_id: str = "",
    status_payload: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    normalized_target_url = _normalize_url(case.canonical_url)
    normalized_run_id = str(run_id or "").strip()
    normalized_baseline_task_ids = {
        _normalize_human_task_id(task_id)
        for task_id in baseline_task_ids
        if _normalize_human_task_id(task_id)
    }
    current_run_task_ids = _current_run_repair_task_ids(
        dict(status_payload or {}),
        run_id=normalized_run_id,
    )
    for task in tasks:
        task_id = str(task.get("human_task_id") or "").strip()
        if str(task.get("task_type") or "").strip() != "property_provider_repair_ooda":
            continue
        normalized_task_id = _normalize_human_task_id(task_id)
        if normalized_task_id and normalized_task_id in current_run_task_ids:
            matches.append(task)
            continue
        if normalized_task_id in normalized_baseline_task_ids:
            continue
        input_json = dict(task.get("input_json") or {}) if isinstance(task.get("input_json"), dict) else {}
        task_run_id = str(input_json.get("run_id") or "").strip()
        if normalized_run_id and task_run_id and task_run_id == normalized_run_id:
            matches.append(task)
            continue
        property_url = _normalize_url(input_json.get("property_url") or input_json.get("source_url"))
        if normalized_target_url and property_url and normalized_target_url == property_url:
            matches.append(task)
            continue
        if case.source_ref and str(input_json.get("source_ref") or "").strip() == case.source_ref:
            matches.append(task)
            continue
        if case.title and _normalize_text(input_json.get("title")) == _normalize_text(case.title):
            matches.append(task)
    return matches


def _repair_needed(status_payload: dict[str, object]) -> bool:
    summary = dict(status_payload.get("summary") or {}) if isinstance(status_payload.get("summary"), dict) else {}
    if int(summary.get("provider_repair_task_opened_total") or 0) > 0:
        return True
    for source in _source_rows(status_payload):
        if str(source.get("error") or "").strip():
            return True
        if str(source.get("repair_status") or "").strip():
            return True
        if list(source.get("provider_repair_tasks") or []):
            return True
    return False


def _apply_repair_receipts_to_trace(repair_trace: RepairTrace, summary: dict[str, object], *, run_id: str) -> None:
    receipts = [
        dict(row)
        for row in list(summary.get("repair_receipts") or [])
        if isinstance(row, dict)
        and (not str(run_id or "").strip() or str(row.get("run_id") or "").strip() == str(run_id or "").strip())
    ]
    if not receipts:
        return
    repair_trace.repair_needed = True
    repair_trace.repair_triggered = True
    repair_trace.repair_executed = True
    repair_trace.task_ids = [
        str(row.get("human_task_id") or "").strip()
        for row in receipts
        if str(row.get("human_task_id") or "").strip()
    ] or repair_trace.task_ids
    repair_trace.statuses = ["returned" for _ in receipts]
    repair_trace.resolutions = [
        str(row.get("resolution") or "").strip()
        for row in receipts
        if str(row.get("resolution") or "").strip()
    ] or repair_trace.resolutions


def _write_report(tmp_path: Path, report: RecoveryReport) -> None:
    artifact_dir = tmp_path / "target_recovery_reports"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / f"{report.case_key}.json"
    target.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")


def _case_key(case: TargetListing, *, variant: str = "targeted") -> str:
    basis = f"{case.country_code}-{case.provider}-{variant}-{case.title}".lower()
    cleaned = "".join(char if char.isalnum() else "-" for char in basis)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:120] or "target-recovery"


def _provider_seed_text() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_SEED") or "tibor-watch").strip()


def _provider_probe_limit() -> int:
    try:
        return max(1, int(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PROBE_LIMIT") or 8))
    except Exception:
        return 8


def _provider_pick_window_size(total: int) -> int:
    if total <= 0:
        return 0
    default_window = max(_provider_probe_limit() * 2, 12)
    try:
        configured = int(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PICK_WINDOW") or default_window)
    except Exception:
        configured = default_window
    return max(1, min(total, configured))


def _ordered_probe_candidates(urls: list[str], *, seed_basis: str) -> list[tuple[int, str]]:
    if not urls:
        return []
    pick_window = _provider_pick_window_size(len(urls))
    start_index = _stable_pick_index(seed_basis, pick_window)
    indexed_window = list(enumerate(urls[:pick_window]))
    rotated = indexed_window[start_index:] + indexed_window[:start_index]
    return rotated[: min(len(rotated), _provider_probe_limit())]


def _country_codes() -> tuple[str, ...]:
    raw = str(
        os.environ.get("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX_COUNTRIES")
        or os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_COUNTRIES")
        or ""
    ).strip()
    if not raw and _target_provider_matrix_enabled():
        return tuple(
            code
            for code in CUSTOMER_SEARCH_COUNTRY_ORDER
            if any(
                str(spec.country_code or "").strip().upper() == code
                and bool(spec.search_ready)
                for spec in PROVIDERS
            )
        )
    if not raw:
        raw = "AT"
    values = tuple(str(item or "").strip().upper() for item in raw.split(",") if str(item or "").strip())
    return values or ("AT",)


def _provider_include_filter() -> set[str]:
    raw = str(
        os.environ.get("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX_PROVIDERS")
        or os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PROVIDERS")
        or ""
    ).strip()
    return {
        str(item or "").strip().lower()
        for item in raw.split(",")
        if str(item or "").strip()
    }


def _target_recovery_variants() -> tuple[str, ...]:
    raw = str(
        os.environ.get("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX_VARIANTS")
        or os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_VARIANTS")
        or ""
    ).strip()
    if raw:
        values = tuple(
            value
            for value in (
                str(item or "").strip().lower()
                for item in raw.split(",")
                if str(item or "").strip()
            )
            if value in {"targeted", "strict", "soft"}
        )
        if values:
            return tuple(dict.fromkeys(values))
    if _target_provider_matrix_enabled():
        return ("strict", "soft")
    return ("targeted",)


def _variant_soft_filter_mode(variant: str) -> tuple[bool, bool]:
    normalized = str(variant or "").strip().lower()
    if normalized == "strict":
        return False, False
    if normalized == "soft":
        return True, True
    return True, False


def _provider_specs() -> list[PropertyProviderSpec]:
    countries = set(_country_codes())
    include = _provider_include_filter()
    rows = [spec for spec in PROVIDERS if spec.country_code in countries and bool(spec.search_ready)]
    if include:
        rows = [spec for spec in rows if spec.key in include]
    return rows


def _provider_listing_mode(spec: PropertyProviderSpec) -> str:
    modes = tuple(str(item or "").strip().lower() for item in spec.supported_listing_modes if str(item or "").strip())
    if "rent" in modes:
        return "rent"
    if modes:
        return modes[0]
    return "buy"


def _provider_source_spec(spec: PropertyProviderSpec, *, listing_mode: str) -> dict[str, object]:
    source_url = str(spec.search_urls.get(listing_mode) or next(iter(spec.search_urls.values()), "")).strip()
    return {
        "url": source_url,
        "label": f"{spec.label} | {spec.country_code} | {listing_mode.title()}",
        "platform": spec.key,
        "provider_family": spec.family,
        "provider_trust_tier": spec.trust_tier,
        "country_code": spec.country_code,
        "search_url": source_url,
    }


def _preview_price_eur(facts: dict[str, object]) -> float:
    for key in ("price_eur", "rent_eur", "purchase_price_eur", "kaufpreis_eur"):
        value = _coerce_float(facts.get(key))
        if value > 0:
            return value
    return 0.0


def _preview_area_m2(facts: dict[str, object]) -> float:
    for key in ("area_m2", "area_sqm", "living_area_sqm", "wohnflaeche_m2", "living_area_m2"):
        value = _coerce_float(facts.get(key))
        if value > 0:
            return value
    return 0.0


def _preview_rooms(facts: dict[str, object]) -> float:
    for key in ("rooms", "room_count", "zimmer"):
        value = _coerce_float(facts.get(key))
        if value > 0:
            return value
    return 0.0


def _preview_location_query(facts: dict[str, object], *, source_label: str) -> str:
    for key in ("postal_name", "district", "location", "street_address", "source_scope_location"):
        value = str(facts.get(key) or "").strip()
        if value:
            return value
    return ""


def _title_location_hint(*, title: str, summary: str, property_url: str) -> tuple[str, str, str]:
    for blob in (str(title or "").strip(), str(summary or "").strip(), urllib.parse.unquote(str(property_url or "").strip())):
        if not blob:
            continue
        postal_match = re.search(r"\((\d{4}\s+[^\)]+)\)", blob)
        if postal_match:
            location = " ".join(str(postal_match.group(1) or "").split()).strip()
            postal_code = location.split(" ", 1)[0] if " " in location else ""
            district_hint = location.split(" ", 1)[1].strip() if " " in location else location
            return location, district_hint, postal_code
    return "", "", ""


def _preview_property_type(facts: dict[str, object], *, title: str, summary: str) -> str:
    normalized = str(facts.get("property_type") or "").strip().lower()
    if normalized in {"apartment", "house", "land", "office"}:
        return normalized
    blob = _normalize_text(" ".join([title, summary, normalized]))
    if re.search(r"\b(reihenhaus|einfamilienhaus|haus|house)\b", blob):
        return "house"
    if re.search(r"\b(baugrund|grundstück|grundstueck|plot of land|land for sale)\b", blob):
        return "land"
    if re.search(r"\b(büro|buero|office|gewerbe)\b", blob):
        return "office"
    return "apartment"


def _preview_title_is_generic_portal(title: str, *, source_label: str) -> bool:
    normalized = _normalize_text(title)
    if not normalized:
        return True
    source = _normalize_text(source_label)
    generic_fragments = (
        "portal obwieszczeń",
        "portal obwieszczen",
        "portal obwieszczen i licytacji",
        "portal obwieszczeń i licytacji",
        "real estate search",
        "property search",
        "suchergebnisse",
        "immobiliensuche",
    )
    if any(fragment in normalized for fragment in generic_fragments):
        return True
    if "portal" in normalized and ("licytac" in normalized or "obwieszc" in normalized):
        return True
    source_tokens = {token for token in source.split() if len(token) >= 5}
    title_tokens = {token for token in normalized.split() if len(token) >= 5}
    if source_tokens and title_tokens and title_tokens.issubset(source_tokens):
        return True
    return False


def _preview_is_probe_usable(*, property_url: str, preview: dict[str, object], source_label: str) -> bool:
    title = str(preview.get("title") or "").strip()
    summary = str(preview.get("summary") or "").strip()
    facts = dict(preview.get("property_facts_json") or {}) if isinstance(preview.get("property_facts_json"), dict) else {}
    location_query = _preview_location_query(facts, source_label=source_label)
    if not location_query:
        location_query, _district_hint, _postal_hint = _title_location_hint(
            title=title,
            summary=summary,
            property_url=property_url,
        )
    if not title or title == property_url:
        return False
    compact_title = re.sub(r"[^a-z0-9äöüß]+", "", title.lower())
    if len(compact_title) < 8:
        return False
    normalized_title = _normalize_text(title)
    normalized_source_label = _normalize_text(source_label)
    if normalized_title == normalized_source_label:
        return False
    if _preview_title_is_generic_portal(title, source_label=source_label):
        return False
    title_tokens = {token for token in normalized_title.split() if len(token) >= 4}
    source_tokens = {token for token in normalized_source_label.split() if len(token) >= 4}
    if title_tokens and source_tokens and title_tokens.issubset(source_tokens):
        return False
    if not location_query:
        return False
    if _normalize_text(location_query) == _normalize_text(source_label):
        return False
    if _preview_price_eur(facts) <= 0 and _preview_area_m2(facts) <= 0 and not summary:
        return False
    return True


def _discover_target_case_for_provider(
    service: ProductService,
    spec: PropertyProviderSpec,
    *,
    manifest_override: dict[str, object] | None,
) -> TargetListing | None:
    listing_mode = _provider_listing_mode(spec)
    source_spec = _provider_source_spec(spec, listing_mode=listing_mode)
    source_url = str(source_spec.get("url") or "").strip()
    if not source_url:
        return None
    try:
        listing_urls, _cache_state = property_service_module._property_scout_listing_urls_for_source(
            source_url=source_url,
            source_spec=source_spec,
            force_refresh=False,
        )
    except Exception:
        return None
    urls = [str(item or "").strip() for item in listing_urls if str(item or "").strip()]
    if not urls:
        return None
    seed = _provider_seed_text()
    ordered_candidates = _ordered_probe_candidates(
        urls,
        seed_basis=f"{seed}|{spec.country_code}|{spec.key}|{len(urls)}",
    )
    if not ordered_candidates:
        return None
    chosen_url = ""
    chosen_preview: dict[str, object] = {}
    chosen_pool_index = 0
    for candidate_index, candidate_url in ordered_candidates:
        try:
            preview = property_service_module._property_scout_page_preview_with_timeout(candidate_url, prefer_fast=True)
        except Exception:
            continue
        if _preview_is_probe_usable(property_url=candidate_url, preview=preview, source_label=str(source_spec.get("label") or "").strip()):
            chosen_url = candidate_url
            chosen_preview = dict(preview)
            chosen_pool_index = candidate_index
            break
    if not chosen_url or not chosen_preview:
        return None
    facts = dict(chosen_preview.get("property_facts_json") or {}) if isinstance(chosen_preview.get("property_facts_json"), dict) else {}
    source_label = str(source_spec.get("label") or "").strip()
    location_query = _preview_location_query(facts, source_label=source_label)
    title_location_query, title_district_hint, title_postal_hint = _title_location_hint(
        title=str(chosen_preview.get("title") or "").strip(),
        summary=str(chosen_preview.get("summary") or "").strip(),
        property_url=chosen_url,
    )
    if not location_query:
        location_query = title_location_query
    payload: dict[str, object] = {
        "canonical_url": chosen_url,
        "title": str(chosen_preview.get("title") or "").strip(),
        "listing_mode": listing_mode,
        "property_type": _preview_property_type(
            facts,
            title=str(chosen_preview.get("title") or "").strip(),
            summary=str(chosen_preview.get("summary") or "").strip(),
        ),
        "location_query": location_query,
        "external_id": str(chosen_preview.get("listing_id") or facts.get("listing_id") or "").strip(),
        "source_ref": str(chosen_preview.get("listing_id") or chosen_url).strip(),
        "district_hint": str(facts.get("district") or title_district_hint or "").strip(),
        "postal_hint": str(facts.get("postal_name") or title_postal_hint or "").strip(),
        "price_eur": _preview_price_eur(facts),
        "area_m2": _preview_area_m2(facts),
        "rooms": _preview_rooms(facts),
        "soft_preferences": {},
        "selected_districts": [],
        "negatives": [],
    }
    if isinstance(manifest_override, dict):
        for key in ("soft_preferences", "selected_districts", "negatives"):
            if key in manifest_override and key not in payload:
                payload[key] = manifest_override[key]
        if isinstance(manifest_override.get("soft_preferences"), dict):
            payload["soft_preferences"] = dict(manifest_override.get("soft_preferences") or {})
        if isinstance(manifest_override.get("selected_districts"), list):
            payload["selected_districts"] = list(manifest_override.get("selected_districts") or [])
        if isinstance(manifest_override.get("negatives"), list):
            payload["negatives"] = list(manifest_override.get("negatives") or [])
    return _target_listing_from_payload(
        payload,
        provider=spec.key,
        country_code=spec.country_code,
        selected_platforms=(spec.key,),
        pool_size=len(urls),
        picked_index=chosen_pool_index,
    )


def _discover_cases_from_catalog(client) -> tuple[list[TargetListing], list[str]]:
    service = ProductService(client.app.state.container)
    overrides = {
        case.provider: case
        for case in _load_cases()
        if case.provider
    }
    discovered: list[TargetListing] = []
    skipped: list[str] = []
    for spec in _provider_specs():
        override_case = overrides.get(spec.key)
        override_payload = asdict(override_case) if override_case is not None else {}
        case = _discover_target_case_for_provider(service, spec, manifest_override=override_payload)
        if case is None:
            skipped.append(spec.key)
            continue
        discovered.append(case)
    return discovered, skipped


def _provider_still_lists_target(service: ProductService, case: TargetListing) -> bool:
    spec = next(
        (
            item
            for item in PROVIDERS
            if str(item.key or "").strip().lower() == str(case.provider or "").strip().lower()
            and str(item.country_code or "").strip().upper() == str(case.country_code or "").strip().upper()
        ),
        None,
    )
    if spec is None:
        return True
    source_spec = _provider_source_spec(spec, listing_mode=case.listing_mode or _provider_listing_mode(spec))
    source_url = str(source_spec.get("url") or "").strip()
    if not source_url:
        return True
    try:
        listing_urls, _cache_state = property_service_module._property_scout_listing_urls_for_source(
            source_url=source_url,
            source_spec=source_spec,
            force_refresh=True,
        )
    except Exception:
        return True
    normalized_target_url = _normalize_url(case.canonical_url)
    target_willhaben_ad_id = _willhaben_ad_id(case.canonical_url)
    for item in listing_urls:
        current_url = _normalize_url(item)
        if normalized_target_url and current_url and normalized_target_url == current_url:
            return True
        if target_willhaben_ad_id and _willhaben_ad_id(current_url) == target_willhaben_ad_id:
            return True
    return False


def _provider_search_still_surfaces_target(case: TargetListing, brief: dict[str, object]) -> bool:
    try:
        specs = property_service_module.generated_property_source_specs(
            preferences=brief,
            selected_platforms=tuple(case.selected_platforms or ((case.provider,) if case.provider else ())),
            principal_id="propertyquarry-target-recovery-volatility-probe",
            default_person_id="self",
            max_results=int(brief.get("max_results_per_source") or 5),
        )
    except Exception:
        return True
    for spec in specs:
        source_url = str(spec.get("url") or "").strip()
        if not source_url:
            continue
        try:
            html = property_service_module._property_scout_fetch_html(source_url)
            listing_urls = property_service_module._property_scout_extract_listing_urls(
                source_url=source_url,
                html=html,
                source_spec=dict(spec),
            )
        except Exception:
            return True
        normalized_target_url = _normalize_url(case.canonical_url)
        target_willhaben_ad_id = _willhaben_ad_id(case.canonical_url)
        for item in listing_urls:
            current_url = _normalize_url(item)
            if normalized_target_url and current_url and normalized_target_url == current_url:
                return True
            if target_willhaben_ad_id and _willhaben_ad_id(current_url) == target_willhaben_ad_id:
                return True
    return False


def test_property_target_recovery_canary_under_tibor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    principal = PrincipalContext(
        principal_id=str(
            os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PRINCIPAL_ID")
            or "cf-email:tibor.girschele@gmail.com"
        ).strip()
    )
    monkeypatch.setenv(
        "PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_CONCURRENCY",
        str(os.environ.get("PROPERTYQUARRY_SEARCH_PROVIDER_WORKER_CONCURRENCY") or "8"),
    )
    monkeypatch.setattr(
        ProductService,
        "_maybe_auto_create_property_scout_tour",
        lambda self, **kwargs: {"status": "skipped", "reason": "target_recovery_canary_media_disabled", "tour_url": "", "blocked_reason": "target_recovery_canary_media_disabled"},
    )
    monkeypatch.setattr(
        ProductService,
        "_maybe_render_property_scout_flythrough",
        lambda self, **kwargs: {"status": "skipped", "reason": "target_recovery_canary_media_disabled", "video_url": ""},
    )
    client = build_property_client(principal_id=principal.principal_id)
    start_workspace(client, mode="personal", workspace_name=principal.workspace_name)
    cases, skipped_providers = _discover_cases_from_catalog(client)
    if skipped_providers:
        sys.stderr.write(
            "[target-recovery] skipped provider probes: "
            + ", ".join(sorted(skipped_providers))
            + "\n"
        )
        sys.stderr.flush()
    if not cases:
        pytest.skip("no unattended provider probes produced a usable target listing")
    timeout_seconds = max(float(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_TIMEOUT_SECONDS") or 180.0), 10.0)
    poll_interval = max(float(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_POLL_SECONDS") or 1.0), 0.1)

    ProductService(client.app.state.container).update_property_alert_policy(
        principal_id=principal.principal_id,
        actor="target_recovery_canary",
        auto_generate_tour_for_good_fit=False,
    )
    service = ProductService(client.app.state.container)
    successful_case_total = 0
    volatility_skipped_total = 0
    variants = _target_recovery_variants()

    for case, variant in [(case, variant) for case in cases for variant in variants]:
        final_report: RecoveryReport | None = None
        soft_filters, default_soft_filters = _variant_soft_filter_mode(variant)
        rank_threshold = _rank_threshold()
        max_attempts = 5
        for attempt_index in range(max_attempts):
            baseline_task_ids = {
                str(task.get("human_task_id") or "").strip()
                for task in _list_repair_tasks(client)
                if str(task.get("human_task_id") or "").strip()
            }
            brief = _synthesize_search_preferences(
                case,
                loosen_level=attempt_index,
                soft_filters=soft_filters,
                default_soft_filters=default_soft_filters,
            )
            _assert_brief_satisfies_target(case, brief)
            stored = client.post("/v1/onboarding/property-search/preferences", json=brief)
            assert stored.status_code == 200, stored.text

            started = client.post(
                "/app/api/property/search-runs",
                json={
                    "selected_platforms": list(case.selected_platforms),
                    "property_preferences": brief,
                    "force_refresh": False,
                    "max_results_per_source": int(brief.get("max_results_per_source") or 2),
                },
            )
            assert started.status_code == 202, started.text
            started_body = started.json()
            run_id = str(started_body.get("run_id") or "").strip()
            assert run_id, f"{case.title}: run_id missing from start response"
            _print_watch_banner(case, principal, run_id, variant=variant)

            last_status: dict[str, object] = {}
            target_match = IdentityMatch(matched=False)
            repair_trace = RepairTrace()
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                status_response = client.get(f"/app/api/property/search-runs/{run_id}")
                assert status_response.status_code == 200, status_response.text
                last_status = status_response.json()
                summary = dict(last_status.get("summary") or {}) if isinstance(last_status.get("summary"), dict) else {}
                media_counters = _assert_no_generated_media(summary)
                repair_trace.repair_needed = repair_trace.repair_needed or _repair_needed(last_status)
                _apply_repair_receipts_to_trace(repair_trace, summary, run_id=run_id)

                candidates = _candidate_rows(last_status)
                target_match = _match_ranked_target(candidates, case)

                tasks = _matching_repair_tasks(
                    _list_repair_tasks(client),
                    case,
                    baseline_task_ids=baseline_task_ids,
                    run_id=run_id,
                    status_payload=last_status,
                )
                if tasks:
                    repair_trace.repair_triggered = True
                    repair_trace.task_ids = [str(task.get("human_task_id") or "") for task in tasks]
                    repair_trace.statuses = [str(task.get("status") or "").strip() for task in tasks]
                    repair_trace.resolutions = [str(task.get("resolution") or "").strip() for task in tasks]
                    repair_trace.repair_executed = any(
                        str(task.get("status") or "").strip().lower() in {"returned", "completed"}
                        for task in tasks
                    )

                if str(last_status.get("status") or "").strip().lower() in TERMINAL_RUN_STATUSES:
                    break
                time.sleep(poll_interval)

            status_value = str(last_status.get("status") or "").strip().lower()
            assert status_value in TERMINAL_RUN_STATUSES, f"{case.title}: run did not reach terminal status before timeout"
            assert status_value != "failed", f"{case.title}: run failed unrepaired"

            summary = dict(last_status.get("summary") or {}) if isinstance(last_status.get("summary"), dict) else {}
            media_counters = _assert_no_generated_media(summary)
            _apply_repair_receipts_to_trace(repair_trace, summary, run_id=run_id)
            candidates = _candidate_rows(last_status)
            target_match = _match_ranked_target(candidates, case)
            negative_hits: list[dict[str, object]] = []
            for control in case.negatives:
                for candidate in candidates:
                    if _match_negative(candidate, control):
                        negative_hits.append(
                            {
                                "title": str(candidate.get("title") or "").strip(),
                                "property_url": str(candidate.get("property_url") or "").strip(),
                                "rank": int(candidate.get("rank") or 0),
                                "control_title": control.title,
                                "must_not_rank": control.must_not_rank,
                            }
                        )

            final_report = RecoveryReport(
                case_key=_case_key(case, variant=variant),
                principal_id=principal.principal_id,
                run_id=run_id,
                watch_url=_watch_url(run_id),
                provider=case.provider,
                target_title=case.title,
                target_url=case.canonical_url,
                pool_size=case.pool_size,
                picked_index=case.picked_index,
                run_status=status_value,
                target_found=target_match.matched,
                target_match_tier=target_match.tier,
                target_rank=target_match.rank,
                repair=repair_trace,
                generated_media_counters=media_counters,
                negative_hits=negative_hits,
                ranked_count=len(candidates),
                attempt_index=attempt_index,
                source_count=len(_source_rows(last_status)),
                event_count=len(list(last_status.get("events") or [])),
                synthesized_brief=brief,
                variant=variant,
            )
            _write_report(tmp_path, final_report)

            forbidden_hits = [row for row in negative_hits if bool(row.get("must_not_rank", True))]
            if repair_trace.repair_needed:
                assert repair_trace.repair_triggered, f"{case.title}: repair was needed but no Fleet repair task opened"
                assert repair_trace.repair_executed, f"{case.title}: Fleet repair task never executed"
                bad_source_fetch_resolutions = [
                    resolution
                    for resolution in repair_trace.resolutions
                    if str(resolution or "").strip().lower() in INVALID_SOURCE_FETCH_REPAIR_RESOLUTIONS
                ]
                assert not bad_source_fetch_resolutions, (
                    f"{case.title}: Fleet returned a semantically wrong source-fetch repair resolution: "
                    f"{bad_source_fetch_resolutions}"
                )

            if target_match.matched and target_match.tier in MATCH_TIERS and not forbidden_hits and 0 < target_match.rank <= rank_threshold:
                successful_case_total += 1
                break
        assert final_report is not None
        if not final_report.target_found and (
            not _provider_still_lists_target(service, case)
            or not _provider_search_still_surfaces_target(case, final_report.synthesized_brief)
        ):
            final_report.provider_volatility = True
            _write_report(tmp_path, final_report)
            volatility_skipped_total += 1
            sys.stderr.write(
                f"[target-recovery] skipped volatile target for {case.provider}: {case.title}\n"
            )
            sys.stderr.flush()
            continue
        assert final_report.target_found, f"{case.title}: target listing not recovered after adaptive retries"
        assert final_report.target_match_tier in MATCH_TIERS, f"{case.title}: unsupported target match tier"
        assert 0 < final_report.target_rank <= rank_threshold, (
            f"{case.title}: target recovered but not ranked highly enough "
            f"(rank={final_report.target_rank}, threshold={rank_threshold})"
        )
        forbidden_hits = [row for row in final_report.negative_hits if bool(row.get('must_not_rank', True))]
        assert not forbidden_hits, f"{case.title}: near-miss impostors survived ranking: {forbidden_hits}"
    if successful_case_total <= 0 and volatility_skipped_total > 0:
        pytest.skip("all target-recovery cases became provider-volatile before recovery validation")
    assert successful_case_total > 0, "no target-recovery case completed successfully"


def test_ordered_probe_candidates_stays_within_fresh_pick_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_TARGET_RECOVERY_PROBE_LIMIT", "4")
    monkeypatch.setenv("PROPERTYQUARRY_TARGET_RECOVERY_PICK_WINDOW", "6")
    urls = [f"https://example.test/{index}" for index in range(12)]
    ordered = _ordered_probe_candidates(urls, seed_basis="AT|willhaben|demo")
    assert len(ordered) == 4
    assert all(index < 6 for index, _url in ordered)
    assert len({index for index, _url in ordered}) == 4


def test_provider_pick_window_size_scales_from_probe_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPERTYQUARRY_TARGET_RECOVERY_PICK_WINDOW", raising=False)
    monkeypatch.setenv("PROPERTYQUARRY_TARGET_RECOVERY_PROBE_LIMIT", "5")
    assert _provider_pick_window_size(40) == 12
    assert _provider_pick_window_size(7) == 7


def test_target_provider_matrix_expands_to_all_search_ready_countries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX", "1")
    monkeypatch.delenv("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX_COUNTRIES", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_TARGET_RECOVERY_COUNTRIES", raising=False)
    countries = _country_codes()
    expected = tuple(
        code
        for code in CUSTOMER_SEARCH_COUNTRY_ORDER
        if any(
            str(spec.country_code or "").strip().upper() == code
            and bool(spec.search_ready)
            for spec in PROVIDERS
        )
    )
    assert countries == expected
    assert _target_recovery_variants() == ("strict", "soft")


def test_target_provider_matrix_synthesizes_strict_and_soft_briefs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYQUARRY_TARGET_PROVIDER_MATRIX", "1")
    case = TargetListing(
        provider="willhaben",
        country_code="AT",
        canonical_url="https://www.willhaben.at/iad/object?adId=123",
        title="Target flat",
        listing_mode="rent",
        property_type="apartment",
        location_query="1020 Vienna",
        price_eur=1500.0,
        area_m2=80.0,
        rooms=3.0,
        selected_platforms=("willhaben",),
        soft_preferences={"max_distance_to_theatre_m": 700, "max_distance_to_theatre_importance": "nice_to_have"},
    )
    strict_soft_filters, strict_default_soft_filters = _variant_soft_filter_mode("strict")
    soft_soft_filters, soft_default_soft_filters = _variant_soft_filter_mode("soft")

    strict = _synthesize_search_preferences(
        case,
        soft_filters=strict_soft_filters,
        default_soft_filters=strict_default_soft_filters,
    )
    soft = _synthesize_search_preferences(
        case,
        soft_filters=soft_soft_filters,
        default_soft_filters=soft_default_soft_filters,
    )

    assert strict["selected_platforms"] == ["willhaben"]
    assert soft["selected_platforms"] == ["willhaben"]
    assert "max_distance_to_theatre_m" not in strict
    assert "max_distance_to_library_m" not in strict
    assert soft["max_distance_to_theatre_m"] == 700
    assert soft["max_distance_to_library_importance"] == "nice_to_have"
    assert soft["max_distance_to_shopping_center_importance"] == "avoid"


def test_preview_probe_usable_rejects_provider_label_junk_target() -> None:
    preview = {
        "title": "| Gesiba",
        "summary": "Wohnung in Wien.",
        "property_facts_json": {
            "postal_name": "1100 Wien",
            "area_m2": 63,
        },
    }
    assert _preview_is_probe_usable(
        property_url="https://example.test/gesiba/123",
        preview=preview,
        source_label="GESIBA | Austria | Rent | Vienna",
    ) is False


def test_preview_probe_usable_rejects_generic_auction_portal_target() -> None:
    preview = {
        "title": "Licytacja komornicza - Portal Obwieszczeń i Licytacji Komorniczych",
        "summary": "Portal page instead of a listing-detail extract.",
        "property_facts_json": {
            "postal_name": "00-031 Warszawa",
        },
    }

    assert _preview_is_probe_usable(
        property_url="https://elicytacje.komornik.pl/licytacje/76353/1-8-niewydzielona-czesc-nieruchomosci",
        preview=preview,
        source_label="Komornik e-Licytacje | PL | Buy",
    ) is False


def test_matching_repair_tasks_prefers_run_id_over_provider_broad_match() -> None:
    case = TargetListing(
        provider="willhaben",
        country_code="AT",
        canonical_url="https://www.willhaben.at/iad/object?adId=123",
        title="Target flat",
        listing_mode="rent",
        property_type="apartment",
        location_query="1010 Vienna",
    )
    tasks = [
        {
            "human_task_id": "human_task:other",
            "task_type": "property_provider_repair_ooda",
            "input_json": {
                "run_id": "run-other",
                "source_platform": "willhaben",
                "title": "Different flat",
                "property_url": "https://www.willhaben.at/iad/object?adId=999",
            },
        },
        {
            "human_task_id": "human_task:current",
            "task_type": "property_provider_repair_ooda",
            "input_json": {
                "run_id": "run-123",
                "source_platform": "willhaben",
                "source_url": "https://www.willhaben.at/iad/immobilien/mietwohnungen/wien",
            },
        },
    ]
    matches = _matching_repair_tasks(tasks, case, baseline_task_ids=set(), run_id="run-123")
    assert [str(task.get("human_task_id") or "") for task in matches] == ["human_task:current"]


def test_match_ranked_target_uses_the_current_snapshot_rank() -> None:
    case = TargetListing(
        provider="willhaben",
        country_code="AT",
        canonical_url="https://www.willhaben.at/iad/object?adId=123",
        title="Target flat",
        listing_mode="rent",
        property_type="apartment",
        location_query="1010 Vienna",
        external_id="123",
    )

    early_match = _match_ranked_target([{"external_id": "123", "rank": 6}], case)
    terminal_match = _match_ranked_target([{"external_id": "123", "rank": 4}], case)

    assert early_match.rank == 6
    assert terminal_match.rank == 4


def test_matching_repair_tasks_accepts_reused_baseline_task_only_with_current_run_evidence() -> None:
    case = TargetListing(
        provider="willhaben",
        country_code="AT",
        canonical_url="https://www.willhaben.at/iad/object?adId=123",
        title="Target flat",
        listing_mode="rent",
        property_type="apartment",
        location_query="1010 Vienna",
    )
    tasks = [
        {
            "human_task_id": "reused",
            "task_type": "property_provider_repair_ooda",
            "status": "returned",
            "resolution": "patched_provider_extractor",
            "input_json": {"run_id": "run-original"},
        },
        {
            "human_task_id": "unrelated",
            "task_type": "property_provider_repair_ooda",
            "status": "returned",
            "resolution": "patched_other_provider",
            "input_json": {"run_id": "run-other"},
        },
    ]
    status_payload = {
        "run_id": "run-current",
        "summary": {
            "sources": [
                {
                    "provider_repair_tasks": [
                        {"human_task_id": "human_task:reused", "status": "returned"},
                    ],
                }
            ]
        },
    }

    matches = _matching_repair_tasks(
        tasks,
        case,
        baseline_task_ids={"reused", "unrelated"},
        run_id="run-current",
        status_payload=status_payload,
    )
    without_current_run_evidence = _matching_repair_tasks(
        tasks,
        case,
        baseline_task_ids={"reused", "unrelated"},
        run_id="run-current",
        status_payload={"run_id": "run-other", "summary": status_payload["summary"]},
    )

    assert [str(task.get("human_task_id") or "") for task in matches] == ["reused"]
    assert without_current_run_evidence == []
