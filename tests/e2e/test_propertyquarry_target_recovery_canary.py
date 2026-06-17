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
from app.services.property_market_catalog import PROVIDERS, PropertyProviderSpec
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


def _synthesize_search_preferences(case: TargetListing, *, loosen_level: int = 0) -> dict[str, object]:
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


def _print_watch_banner(case: TargetListing, principal: PrincipalContext, run_id: str) -> None:
    sys.stderr.write(
        "\n".join(
            [
                "",
                f"[target-recovery] principal={principal.principal_id}",
                f"[target-recovery] provider={case.provider}",
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


def _matching_repair_tasks(
    tasks: list[dict[str, object]],
    case: TargetListing,
    *,
    baseline_task_ids: set[str],
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    normalized_target_url = _normalize_url(case.canonical_url)
    for task in tasks:
        task_id = str(task.get("human_task_id") or "").strip()
        if task_id in baseline_task_ids:
            continue
        if str(task.get("task_type") or "").strip() != "property_provider_repair_ooda":
            continue
        input_json = dict(task.get("input_json") or {}) if isinstance(task.get("input_json"), dict) else {}
        property_url = _normalize_url(input_json.get("property_url") or input_json.get("source_url"))
        source_platform = str(input_json.get("source_platform") or "").strip()
        if normalized_target_url and property_url and normalized_target_url == property_url:
            matches.append(task)
            continue
        if case.source_ref and str(input_json.get("source_ref") or "").strip() == case.source_ref:
            matches.append(task)
            continue
        if case.title and _normalize_text(input_json.get("title")) == _normalize_text(case.title):
            matches.append(task)
            continue
        if case.provider and source_platform and case.provider == source_platform:
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


def _write_report(tmp_path: Path, report: RecoveryReport) -> None:
    artifact_dir = tmp_path / "target_recovery_reports"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / f"{report.case_key}.json"
    target.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")


def _case_key(case: TargetListing) -> str:
    basis = f"{case.country_code}-{case.provider}-{case.title}".lower()
    cleaned = "".join(char if char.isalnum() else "-" for char in basis)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:120] or "target-recovery"


def _provider_seed_text() -> str:
    return str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_SEED") or "tibor-watch").strip()


def _country_codes() -> tuple[str, ...]:
    raw = str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_COUNTRIES") or "AT").strip()
    values = tuple(str(item or "").strip().upper() for item in raw.split(",") if str(item or "").strip())
    return values or ("AT",)


def _provider_include_filter() -> set[str]:
    raw = str(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PROVIDERS") or "").strip()
    return {
        str(item or "").strip().lower()
        for item in raw.split(",")
        if str(item or "").strip()
    }


def _provider_specs() -> list[PropertyProviderSpec]:
    countries = set(_country_codes())
    include = _provider_include_filter()
    rows = [spec for spec in PROVIDERS if spec.country_code in countries]
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
    start_index = _stable_pick_index(f"{seed}|{spec.country_code}|{spec.key}|{len(urls)}", len(urls))
    ordered_urls = urls[start_index:] + urls[:start_index]
    max_probe = min(len(ordered_urls), max(int(os.environ.get("PROPERTYQUARRY_TARGET_RECOVERY_PROBE_LIMIT") or 8), 1))
    chosen_url = ""
    chosen_preview: dict[str, object] = {}
    for candidate_url in ordered_urls[:max_probe]:
        try:
            preview = property_service_module._property_scout_page_preview_with_timeout(candidate_url, prefer_fast=True)
        except Exception:
            continue
        if _preview_is_probe_usable(property_url=candidate_url, preview=preview, source_label=str(source_spec.get("label") or "").strip()):
            chosen_url = candidate_url
            chosen_preview = dict(preview)
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
        picked_index=start_index,
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

    for case in cases:
        final_report: RecoveryReport | None = None
        rank_threshold = _rank_threshold()
        max_attempts = 5
        for attempt_index in range(max_attempts):
            baseline_task_ids = {
                str(task.get("human_task_id") or "").strip()
                for task in _list_repair_tasks(client)
                if str(task.get("human_task_id") or "").strip()
            }
            brief = _synthesize_search_preferences(case, loosen_level=attempt_index)
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
            assert started.status_code == 200, started.text
            started_body = started.json()
            run_id = str(started_body.get("run_id") or "").strip()
            assert run_id, f"{case.title}: run_id missing from start response"
            _print_watch_banner(case, principal, run_id)

            last_status: dict[str, object] = {}
            first_target_match = IdentityMatch(matched=False)
            repair_trace = RepairTrace()
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                status_response = client.get(f"/app/api/property/search-runs/{run_id}")
                assert status_response.status_code == 200, status_response.text
                last_status = status_response.json()
                summary = dict(last_status.get("summary") or {}) if isinstance(last_status.get("summary"), dict) else {}
                media_counters = _assert_no_generated_media(summary)
                repair_trace.repair_needed = repair_trace.repair_needed or _repair_needed(last_status)

                candidates = _candidate_rows(last_status)
                if not first_target_match.matched:
                    for candidate in candidates:
                        match = _match_candidate(candidate, case)
                        if match.matched:
                            first_target_match = match
                            break

                tasks = _matching_repair_tasks(_list_repair_tasks(client), case, baseline_task_ids=baseline_task_ids)
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
            candidates = _candidate_rows(last_status)
            if not first_target_match.matched:
                for candidate in candidates:
                    match = _match_candidate(candidate, case)
                    if match.matched:
                        first_target_match = match
                        break
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
                case_key=_case_key(case),
                principal_id=principal.principal_id,
                run_id=run_id,
                watch_url=_watch_url(run_id),
                provider=case.provider,
                target_title=case.title,
                target_url=case.canonical_url,
                pool_size=case.pool_size,
                picked_index=case.picked_index,
                run_status=status_value,
                target_found=first_target_match.matched,
                target_match_tier=first_target_match.tier,
                target_rank=first_target_match.rank,
                repair=repair_trace,
                generated_media_counters=media_counters,
                negative_hits=negative_hits,
                ranked_count=len(candidates),
                attempt_index=attempt_index,
                source_count=len(_source_rows(last_status)),
                event_count=len(list(last_status.get("events") or [])),
                synthesized_brief=brief,
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

            if first_target_match.matched and first_target_match.tier in MATCH_TIERS and not forbidden_hits and 0 < first_target_match.rank <= rank_threshold:
                break
        assert final_report is not None
        assert final_report.target_found, f"{case.title}: target listing not recovered after adaptive retries"
        assert final_report.target_match_tier in MATCH_TIERS, f"{case.title}: unsupported target match tier"
        assert 0 < final_report.target_rank <= rank_threshold, (
            f"{case.title}: target recovered but not ranked highly enough "
            f"(rank={final_report.target_rank}, threshold={rank_threshold})"
        )
        forbidden_hits = [row for row in final_report.negative_hits if bool(row.get('must_not_rank', True))]
        assert not forbidden_hits, f"{case.title}: near-miss impostors survived ranking: {forbidden_hits}"
