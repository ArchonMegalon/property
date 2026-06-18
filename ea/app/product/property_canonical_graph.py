from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable


_CLAIM_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("total_rent_eur", ("total_rent_eur", "rent_eur", "price_eur")),
    ("purchase_price_eur", ("purchase_price_eur", "buy_price_eur", "purchase_price", "price_eur")),
    ("operating_costs_eur", ("operating_costs_eur", "betriebskosten_eur", "monthly_operating_costs_eur")),
    ("area_sqm", ("area_sqm", "living_area_sqm", "area", "wohnflaeche_sqm")),
    ("rooms", ("rooms", "room_count", "zimmer")),
    ("postal_name", ("postal_name", "postal_code", "district", "location")),
    ("property_type", ("property_type", "asset_type")),
    ("has_floorplan", ("has_floorplan", "floorplan_available")),
    ("has_360", ("has_360", "source_virtual_tour_available")),
)


@dataclass(frozen=True)
class PropertyEntity:
    property_id: str
    identity_key: str
    title: str = ""
    country_code: str = ""
    postal_name: str = ""
    area_sqm: object = None
    rooms: object = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    listing_count: int = 0


@dataclass(frozen=True)
class ListingInstance:
    listing_instance_id: str
    property_id: str
    provider: str = ""
    listing_url: str = ""
    listing_id: str = ""
    title: str = ""
    first_seen_run_id: str = ""
    last_seen_run_id: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""


@dataclass(frozen=True)
class PropertyClaim:
    claim_id: str
    property_id: str
    field: str
    value: object
    source_type: str = "listing"
    source_ref: str = ""
    observed_at: str = ""
    run_id: str = ""
    confidence: str = "provider_only"
    verification_state: str = "provider_only"


@dataclass(frozen=True)
class PropertyEvent:
    event_id: str
    property_id: str
    event_type: str
    field: str = ""
    previous_value: object = None
    current_value: object = None
    observed_at: str = ""
    run_id: str = ""
    source_ref: str = ""


@dataclass(frozen=True)
class PropertyPassportSnapshot:
    principal_id: str
    generated_at: str
    properties: tuple[PropertyEntity, ...] = ()
    listing_instances: tuple[ListingInstance, ...] = ()
    claims: tuple[PropertyClaim, ...] = ()
    change_events: tuple[PropertyEvent, ...] = ()

    def as_public_dict(self, *, property_limit: int = 100, listing_limit: int = 200, claim_limit: int = 500, change_limit: int = 100) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "generated_at": self.generated_at,
            "property_count": len(self.properties),
            "listing_instance_count": len(self.listing_instances),
            "claim_count": len(self.claims),
            "change_event_count": len(self.change_events),
            "properties": [asdict(row) for row in self.properties[:property_limit]],
            "listing_instances": [asdict(row) for row in self.listing_instances[:listing_limit]],
            "claims": [asdict(row) for row in self.claims[:claim_limit]],
            "recent_changes": [asdict(row) for row in self.change_events[:change_limit]],
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: object, *, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _hash_text(value: object, *, prefix: str) -> str:
    normalized = _clean_text(value, limit=4000)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:18]
    return f"{prefix}_{digest}"


def _normalized_url(value: object) -> str:
    raw = _clean_text(value, limit=2000)
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def _hostname(value: object) -> str:
    url = _normalized_url(value)
    if not url:
        return ""
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def _facts(candidate: dict[str, object]) -> dict[str, object]:
    for key in ("property_facts", "property_facts_json", "facts"):
        value = candidate.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_fact(facts: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = facts.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _json_key(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _run_timestamp(run: dict[str, object]) -> str:
    for key in ("updated_at", "generated_at", "completed_at", "created_at", "started_at"):
        value = _clean_text(run.get(key), limit=120)
        if value:
            return value
    return _now_iso()


def _candidate_sources(run: dict[str, object]) -> Iterable[tuple[dict[str, object], dict[str, object]]]:
    summary = dict(run.get("summary") or {}) if isinstance(run.get("summary"), dict) else {}
    run_level_sources = list(run.get("sources") or summary.get("sources") or [])
    for source in run_level_sources:
        if not isinstance(source, dict):
            continue
        for key in ("top_candidates", "ranked_candidates", "review_candidates", "candidates", "filtered_candidates"):
            for candidate in list(source.get(key) or []):
                if isinstance(candidate, dict):
                    yield dict(candidate), dict(source)
    for key in ("top_candidates", "ranked_candidates", "review_candidates", "candidates", "shortlist"):
        for candidate in list(run.get(key) or summary.get(key) or []):
            if isinstance(candidate, dict):
                yield dict(candidate), {}


def _property_identity_key(candidate: dict[str, object], facts: dict[str, object], listing_url: str) -> str:
    country = _clean_text(_first_fact(facts, "country_code", "country"), limit=20).lower()
    postal = _clean_text(_first_fact(facts, "postal_name", "postal_code", "district", "location"), limit=160).lower()
    address = _clean_text(
        _first_fact(facts, "exact_address", "street_address", "address", "address_line", "formatted_address"),
        limit=240,
    ).lower()
    area = _clean_text(_first_fact(facts, "area_sqm", "living_area_sqm", "area"), limit=40)
    rooms = _clean_text(_first_fact(facts, "rooms", "room_count", "zimmer"), limit=40)
    if country or postal or address:
        if address and (area or rooms):
            return f"address:{country}:{postal}:{address}:{area}:{rooms}"
        title = _clean_text(candidate.get("title"), limit=160).lower()
        if postal and title and (area or rooms):
            return f"fuzzy:{country}:{postal}:{title}:{area}:{rooms}"
    return f"listing:{listing_url or _clean_text(candidate.get('listing_id') or candidate.get('source_ref') or candidate.get('title'), limit=500).lower()}"


def build_property_passport_snapshot(
    *,
    principal_id: str,
    runs: Iterable[dict[str, object]],
) -> PropertyPassportSnapshot:
    properties: dict[str, dict[str, object]] = {}
    listings: dict[str, dict[str, object]] = {}
    claims: dict[str, PropertyClaim] = {}
    observations: list[dict[str, object]] = []

    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = _clean_text(run.get("run_id"), limit=160)
        observed_at = _run_timestamp(run)
        for candidate, source in _candidate_sources(run):
            facts = _facts(candidate)
            listing_url = _normalized_url(candidate.get("property_url") or candidate.get("listing_url") or candidate.get("source_url"))
            if not listing_url and not candidate.get("title"):
                continue
            identity_key = _property_identity_key(candidate, facts, listing_url)
            property_id = _hash_text(identity_key, prefix="property")
            provider = _clean_text(candidate.get("source_label") or source.get("source_label") or source.get("label") or _hostname(listing_url), limit=160)
            listing_id_raw = _clean_text(candidate.get("listing_id") or candidate.get("external_id") or listing_url or candidate.get("source_ref"), limit=500)
            listing_instance_id = _hash_text(f"{provider}:{listing_id_raw or listing_url}", prefix="listing")
            title = _clean_text(candidate.get("title") or _first_fact(facts, "title"), limit=240)

            current = properties.setdefault(
                property_id,
                {
                    "property_id": property_id,
                    "identity_key": identity_key,
                    "title": title,
                    "country_code": _clean_text(_first_fact(facts, "country_code", "country"), limit=20),
                    "postal_name": _clean_text(_first_fact(facts, "postal_name", "postal_code", "district", "location"), limit=160),
                    "area_sqm": _first_fact(facts, "area_sqm", "living_area_sqm", "area"),
                    "rooms": _first_fact(facts, "rooms", "room_count", "zimmer"),
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                    "listing_ids": set(),
                },
            )
            if not current.get("title") and title:
                current["title"] = title
            current["last_seen_at"] = max(str(current.get("last_seen_at") or ""), observed_at)
            current["listing_ids"].add(listing_instance_id)

            listing = listings.setdefault(
                listing_instance_id,
                {
                    "listing_instance_id": listing_instance_id,
                    "property_id": property_id,
                    "provider": provider,
                    "listing_url": listing_url,
                    "listing_id": listing_id_raw,
                    "title": title,
                    "first_seen_run_id": run_id,
                    "last_seen_run_id": run_id,
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                },
            )
            listing["last_seen_run_id"] = run_id or listing.get("last_seen_run_id")
            listing["last_seen_at"] = max(str(listing.get("last_seen_at") or ""), observed_at)

            source_ref = _clean_text(candidate.get("source_ref") or listing_id_raw or listing_url, limit=500)
            for field, aliases in _CLAIM_FIELD_ALIASES:
                value = _first_fact(facts, *aliases)
                if value in (None, "", [], {}):
                    continue
                claim_id = _hash_text(f"{property_id}:{field}:{_json_key(value)}:{source_ref}", prefix="claim")
                claims[claim_id] = PropertyClaim(
                    claim_id=claim_id,
                    property_id=property_id,
                    field=field,
                    value=value,
                    source_ref=source_ref,
                    observed_at=observed_at,
                    run_id=run_id,
                )
                observations.append(
                    {
                        "property_id": property_id,
                        "field": field,
                        "value": value,
                        "observed_at": observed_at,
                        "run_id": run_id,
                        "source_ref": source_ref,
                    }
                )

    events: list[PropertyEvent] = []
    previous_by_property_field: dict[tuple[str, str], dict[str, object]] = {}
    for observation in sorted(observations, key=lambda row: (str(row.get("observed_at") or ""), str(row.get("run_id") or ""))):
        key = (str(observation["property_id"]), str(observation["field"]))
        previous = previous_by_property_field.get(key)
        if previous is not None and _json_key(previous.get("value")) != _json_key(observation.get("value")):
            events.append(
                PropertyEvent(
                    event_id=_hash_text(
                        f"{key}:{_json_key(previous.get('value'))}:{_json_key(observation.get('value'))}:{observation.get('observed_at')}",
                        prefix="event",
                    ),
                    property_id=str(observation["property_id"]),
                    event_type=f"{observation['field']}_changed",
                    field=str(observation["field"]),
                    previous_value=previous.get("value"),
                    current_value=observation.get("value"),
                    observed_at=str(observation.get("observed_at") or ""),
                    run_id=str(observation.get("run_id") or ""),
                    source_ref=str(observation.get("source_ref") or ""),
                )
            )
        previous_by_property_field[key] = observation

    property_rows = tuple(
        PropertyEntity(
            property_id=str(row["property_id"]),
            identity_key=str(row["identity_key"]),
            title=str(row.get("title") or ""),
            country_code=str(row.get("country_code") or ""),
            postal_name=str(row.get("postal_name") or ""),
            area_sqm=row.get("area_sqm"),
            rooms=row.get("rooms"),
            first_seen_at=str(row.get("first_seen_at") or ""),
            last_seen_at=str(row.get("last_seen_at") or ""),
            listing_count=len(row.get("listing_ids") or []),
        )
        for row in sorted(properties.values(), key=lambda item: (str(item.get("last_seen_at") or ""), str(item.get("title") or "")), reverse=True)
    )
    listing_rows = tuple(ListingInstance(**row) for row in sorted(listings.values(), key=lambda item: str(item.get("last_seen_at") or ""), reverse=True))
    claim_rows = tuple(sorted(claims.values(), key=lambda item: (item.observed_at, item.field), reverse=True))
    event_rows = tuple(sorted(events, key=lambda item: item.observed_at, reverse=True))
    return PropertyPassportSnapshot(
        principal_id=_clean_text(principal_id, limit=240),
        generated_at=_now_iso(),
        properties=property_rows,
        listing_instances=listing_rows,
        claims=claim_rows,
        change_events=event_rows,
    )
