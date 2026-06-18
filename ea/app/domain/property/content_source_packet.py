from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any


CONTENT_SOURCE_PACKET_CONTRACT = "propertyquarry.video_source_packet.v1"

CONTENT_MODE_PRODUCT_TUTORIAL = "PRODUCT_TUTORIAL"
CONTENT_MODE_MARKET_EDUCATION = "MARKET_EDUCATION"
CONTENT_MODE_LOCATION_GUIDE = "LOCATION_GUIDE"
CONTENT_MODE_PROPERTY_DOSSIER = "PROPERTY_DOSSIER"
CONTENT_MODE_TOUR_NARRATION = "TOUR_NARRATION"
CONTENT_MODE_INVESTMENT_EDUCATION = "INVESTMENT_EDUCATION"
CONTENT_MODE_MARKETING_RESEARCH = "MARKETING_RESEARCH"
CONTENT_MODE_PRIVATE_SHORTLIST_VIDEO_BETA = "PRIVATE_SHORTLIST_VIDEO_BETA"

PUBLIC_CONTENT_MODES = frozenset(
    {
        CONTENT_MODE_PRODUCT_TUTORIAL,
        CONTENT_MODE_MARKET_EDUCATION,
        CONTENT_MODE_LOCATION_GUIDE,
        CONTENT_MODE_INVESTMENT_EDUCATION,
        CONTENT_MODE_MARKETING_RESEARCH,
    }
)
PROPERTY_BOUND_CONTENT_MODES = frozenset({CONTENT_MODE_PROPERTY_DOSSIER, CONTENT_MODE_TOUR_NARRATION})
SUPPORTED_CONTENT_MODES = PUBLIC_CONTENT_MODES | PROPERTY_BOUND_CONTENT_MODES
DISABLED_CONTENT_MODES = frozenset({CONTENT_MODE_PRIVATE_SHORTLIST_VIDEO_BETA})

SUBSCRIBR_CHANNELS_BY_MODE = {
    CONTENT_MODE_PRODUCT_TUTORIAL: "propertyquarry-academy",
    CONTENT_MODE_MARKET_EDUCATION: "propertyquarry-renters-eu",
    CONTENT_MODE_LOCATION_GUIDE: "propertyquarry-relocation",
    CONTENT_MODE_PROPERTY_DOSSIER: "propertyquarry-dossier-lab",
    CONTENT_MODE_TOUR_NARRATION: "propertyquarry-dossier-lab",
    CONTENT_MODE_INVESTMENT_EDUCATION: "propertyquarry-investment-education",
    CONTENT_MODE_MARKETING_RESEARCH: "propertyquarry-content-lab",
}

DEFAULT_FORBIDDEN_CLAIMS = (
    "This is objectively the best property.",
    "This is a guaranteed investment.",
    "The neighbourhood is safe.",
    "The property has no hidden problems.",
    "The asking price is fair.",
)


class PropertyContentPacketError(ValueError):
    """Raised when a PropertyQuarry content packet cannot be normalized."""


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_expires_at(*, days: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_text(value: object, *, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_content_mode(value: object) -> str:
    normalized = compact_text(value, limit=80).upper().replace("-", "_").replace(" ", "_")
    if normalized in DISABLED_CONTENT_MODES:
        raise PropertyContentPacketError("private_shortcode_video_beta_disabled")
    if normalized not in SUPPORTED_CONTENT_MODES:
        raise PropertyContentPacketError("unsupported_property_content_mode")
    return normalized


def default_subscribr_channel_for_mode(content_mode: object) -> str:
    mode = normalize_content_mode(content_mode)
    return SUBSCRIBR_CHANNELS_BY_MODE[mode]


def canonical_json(value: object) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_packet_sha256(packet: dict[str, object]) -> str:
    body = dict(packet)
    body.pop("source_packet_sha256", None)
    return sha256_json(body)


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _clean_list(value: object, *, limit: int = 20, item_limit: int = 500) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = compact_text(item, limit=item_limit)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _clean_mapping(value: object, *, max_bytes: int = 16_000) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    cleaned = _jsonable(value)
    if not isinstance(cleaned, dict):
        return {}
    encoded = canonical_json(cleaned)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise PropertyContentPacketError("property_content_packet_section_too_large")
    return cleaned


def build_property_content_source_packet(
    *,
    packet_id: str,
    content_mode: str,
    title: str,
    language: str = "en",
    jurisdiction: str = "",
    audience: str = "prospective home seeker",
    target_words: int = 750,
    subscribr_channel_key: str = "",
    property_snapshot: dict[str, object] | None = None,
    facts: dict[str, object] | None = None,
    fit: dict[str, object] | None = None,
    ooda: dict[str, object] | None = None,
    risks: list[object] | None = None,
    unknowns: list[object] | None = None,
    sources: list[object] | None = None,
    allowed_claims: list[object] | None = None,
    forbidden_claims: list[object] | None = None,
    media_rights: dict[str, object] | None = None,
    privacy: dict[str, object] | None = None,
    research_policy: str = "",
    human_review_required: bool = True,
    publication_allowed: bool = False,
    production_allowed: bool = False,
    expires_at: str = "",
    observed_at: str = "",
) -> dict[str, object]:
    mode = normalize_content_mode(content_mode)
    packet_ref = compact_text(packet_id, limit=180)
    if not packet_ref:
        raise PropertyContentPacketError("property_content_packet_id_required")
    title_text = compact_text(title, limit=240)
    if not title_text:
        raise PropertyContentPacketError("property_content_title_required")
    clean_snapshot = _clean_mapping(property_snapshot or {}, max_bytes=12_000)
    clean_facts = _clean_mapping(facts or {}, max_bytes=20_000)
    clean_fit = _clean_mapping(fit or {}, max_bytes=12_000)
    clean_ooda = _clean_mapping(ooda or {}, max_bytes=12_000)
    clean_media_rights = {
        "listing_images_allowed_for_video": False,
        "synthetic_visuals_allowed": False,
        **_clean_mapping(media_rights or {}, max_bytes=4_000),
    }
    clean_privacy = {
        "classification": "public_safe_projection",
        "user_identity_included": False,
        "private_profile_included": False,
        **_clean_mapping(privacy or {}, max_bytes=4_000),
    }
    source_items = []
    if isinstance(sources, (list, tuple)):
        for source in sources[:20]:
            if isinstance(source, dict):
                source_items.append(_clean_mapping(source, max_bytes=4_000))
    claims = _clean_list(allowed_claims or [], limit=40)
    forbidden = tuple(_clean_list(forbidden_claims or [], limit=60)) or DEFAULT_FORBIDDEN_CLAIMS
    packet: dict[str, object] = {
        "contract_name": CONTENT_SOURCE_PACKET_CONTRACT,
        "packet_id": packet_ref,
        "content_mode": mode,
        "subscribr_channel_key": compact_text(subscribr_channel_key, limit=120)
        or default_subscribr_channel_for_mode(mode),
        "language": compact_text(language, limit=40) or "en",
        "jurisdiction": compact_text(jurisdiction, limit=40),
        "audience": compact_text(audience, limit=160) or "prospective home seeker",
        "title": title_text,
        "target_words": max(120, min(2500, int(target_words or 750))),
        "property_snapshot": clean_snapshot,
        "facts": clean_facts,
        "fit": clean_fit,
        "ooda": clean_ooda,
        "risks": [
            _clean_mapping(item, max_bytes=2_000) if isinstance(item, dict) else {"finding": compact_text(item, limit=400)}
            for item in list(risks or [])[:20]
        ],
        "unknowns": _clean_list(unknowns or [], limit=40),
        "sources": source_items,
        "allowed_claims": claims,
        "forbidden_claims": list(forbidden),
        "media_rights": clean_media_rights,
        "privacy": clean_privacy,
        "research_policy": compact_text(research_policy, limit=80)
        or ("provided_sources_only" if mode in PROPERTY_BOUND_CONTENT_MODES else "approved_sources_only"),
        "human_review_required": bool(human_review_required),
        "production_allowed": bool(production_allowed),
        "publication_allowed": bool(publication_allowed),
        "observed_at": compact_text(observed_at, limit=40) or now_utc_iso(),
        "expires_at": compact_text(expires_at, limit=40) or default_expires_at(days=2),
    }
    packet["source_packet_sha256"] = source_packet_sha256(packet)
    return packet


def packet_text_index(packet: dict[str, object]) -> str:
    return canonical_json(packet).lower()

