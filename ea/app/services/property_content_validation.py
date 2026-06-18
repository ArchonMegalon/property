from __future__ import annotations

import re
from datetime import datetime, timezone

from app.domain.property.content_source_packet import (
    CONTENT_MODE_PROPERTY_DOSSIER,
    CONTENT_MODE_TOUR_NARRATION,
    CONTENT_SOURCE_PACKET_CONTRACT,
    PROPERTY_BOUND_CONTENT_MODES,
    SUPPORTED_CONTENT_MODES,
    packet_text_index,
    source_packet_sha256,
)
from app.services.property_content_privacy import validate_property_content_privacy


FINANCIAL_BLOCK_PHRASES = (
    "guaranteed return",
    "risk-free",
    "safe investment",
    "sure appreciation",
    "perfect rental investment",
    "undervalued",
)
LEGAL_BLOCK_PHRASES = (
    "legally compliant",
    "no tenancy risk",
    "contract is safe",
    "zoning is approved",
    "no title problem",
)
FAIR_HOUSING_BLOCK_PHRASES = (
    "not suitable for foreigners",
    "avoid immigrants",
    "christian neighbourhood",
    "muslim neighbourhood",
    "white neighbourhood",
    "family-only neighbourhood",
    "no disabled people",
)
RANKING_BLOCK_PHRASES = (
    "objectively the best",
    "best property",
    "perfect fit",
    "dream home",
    "hidden gem",
)
SCRIPT_FACT_TERMS = (
    "air conditioning",
    "balcony",
    "garage",
    "garden",
    "lift",
    "parking",
    "pool",
    "sauna",
    "terrace",
)


def _contains_any(text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in phrases if phrase in lowered]


def _pass_fail(condition: bool) -> str:
    return "pass" if condition else "fail"


def _parse_iso(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _packet_mode(packet: dict[str, object]) -> str:
    return str(packet.get("content_mode") or "").strip().upper()


def validate_property_content_source_packet(packet: dict[str, object]) -> dict[str, object]:
    checks: dict[str, str] = {}
    findings: list[dict[str, str]] = []
    mode = _packet_mode(packet)
    checks["contract"] = _pass_fail(packet.get("contract_name") == CONTENT_SOURCE_PACKET_CONTRACT)
    checks["content_mode"] = _pass_fail(mode in SUPPORTED_CONTENT_MODES)
    checks["human_review"] = _pass_fail(bool(packet.get("human_review_required")) is True)
    checks["publication_gate"] = _pass_fail(not bool(packet.get("publication_allowed")))
    checks["production_gate"] = _pass_fail(not bool(packet.get("production_allowed")))
    checks["source_packet_hash"] = _pass_fail(str(packet.get("source_packet_sha256") or "") == source_packet_sha256(packet))
    privacy = validate_property_content_privacy(packet)
    checks["privacy"] = str(privacy["status"])
    findings.extend({"code": str(item.get("code")), "path": str(item.get("path")), "detail": str(item.get("detail"))} for item in privacy["findings"])
    if mode in PROPERTY_BOUND_CONTENT_MODES:
        snapshot = packet.get("property_snapshot") if isinstance(packet.get("property_snapshot"), dict) else {}
        checks["property_snapshot"] = _pass_fail(bool(snapshot.get("run_id")) and bool(snapshot.get("candidate_ref")) and bool(snapshot.get("snapshot_sha256")))
        checks["source_binding"] = _pass_fail(bool(packet.get("sources")) and str(packet.get("research_policy") or "") == "provided_sources_only")
        checks["unknowns_explicit"] = _pass_fail(isinstance(packet.get("unknowns"), list))
    else:
        checks["property_snapshot"] = "pass"
        checks["source_binding"] = _pass_fail(str(packet.get("research_policy") or "") in {"approved_sources_only", "provided_sources_only"})
        checks["unknowns_explicit"] = "pass"
    expires = _parse_iso(packet.get("expires_at"))
    checks["freshness"] = _pass_fail(expires is not None and expires > datetime.now(timezone.utc))
    canonical = packet_text_index(packet)
    for code, phrases in (
        ("financial_language", FINANCIAL_BLOCK_PHRASES),
        ("legal_language", LEGAL_BLOCK_PHRASES),
        ("fair_housing", FAIR_HOUSING_BLOCK_PHRASES),
    ):
        matches = _contains_any(canonical, phrases)
        checks[code] = _pass_fail(not matches)
        for match in matches:
            findings.append({"code": f"{code}_blocked", "path": "$", "detail": match})
    status = "pass" if all(value == "pass" for value in checks.values()) else "fail"
    return {"status": status, "checks": checks, "findings": findings}


def evaluate_property_content_freshness(
    packet: dict[str, object],
    *,
    current_snapshot_sha256: str = "",
    current_fit_score: int | None = None,
    listing_status: str = "",
) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    snapshot = packet.get("property_snapshot") if isinstance(packet.get("property_snapshot"), dict) else {}
    if current_snapshot_sha256 and current_snapshot_sha256 != str(snapshot.get("snapshot_sha256") or ""):
        findings.append({"code": "snapshot_changed", "detail": "listing snapshot hash changed"})
    if str(listing_status or "").strip().lower() in {"removed", "deleted", "inactive", "expired"}:
        findings.append({"code": "listing_removed", "detail": "listing is no longer active"})
    fit = packet.get("fit") if isinstance(packet.get("fit"), dict) else {}
    if current_fit_score is not None and fit.get("fit_score") not in {None, "", current_fit_score}:
        findings.append({"code": "fit_score_changed", "detail": "fit score changed"})
    return {"status": "SOURCE_STALE" if findings else "CURRENT", "findings": findings}


def validate_property_content_script(packet: dict[str, object], markdown: str) -> dict[str, object]:
    text = str(markdown or "")
    lowered = text.lower()
    checks: dict[str, str] = {}
    findings: list[dict[str, str]] = []
    privacy = validate_property_content_privacy(text)
    checks["privacy"] = str(privacy["status"])
    findings.extend({"code": str(item.get("code")), "path": "$script", "detail": str(item.get("detail"))} for item in privacy["findings"])
    source_index = packet_text_index(packet)
    forbidden_claims = [str(item or "").strip() for item in packet.get("forbidden_claims") or [] if str(item or "").strip()]
    forbidden_matches = [claim for claim in forbidden_claims if claim.lower() in lowered]
    for claim in forbidden_matches:
        findings.append({"code": "forbidden_claim_present", "path": "$script", "detail": claim})
    checks["forbidden_claims"] = _pass_fail(not forbidden_matches)
    for code, phrases in (
        ("financial_language", FINANCIAL_BLOCK_PHRASES),
        ("legal_language", LEGAL_BLOCK_PHRASES),
        ("fair_housing", FAIR_HOUSING_BLOCK_PHRASES),
        ("ranking_integrity", RANKING_BLOCK_PHRASES),
    ):
        matches = _contains_any(text, phrases)
        checks[code] = _pass_fail(not matches)
        for match in matches:
            findings.append({"code": f"{code}_blocked", "path": "$script", "detail": match})
    unsupported_terms = [term for term in SCRIPT_FACT_TERMS if term in lowered and term not in source_index]
    checks["listing_facts"] = _pass_fail(not unsupported_terms)
    for term in unsupported_terms:
        findings.append({"code": "script_fact_absent_from_source", "path": "$script", "detail": term})
    unknowns = [str(item or "").strip().lower() for item in packet.get("unknowns") or [] if str(item or "").strip()]
    unknown_failures = []
    for unknown in unknowns:
        compact_unknown = re.sub(r"[^a-z0-9]+", " ", unknown).strip()
        match = re.search(
            rf"\b{re.escape(compact_unknown)}\b.{{0,40}}\b(confirmed|available|known|verified)\b",
            lowered,
        )
        if compact_unknown and match:
            snippet = match.group(0)
            if any(marker in snippet for marker in ("unknown", "missing", "not available", "should be verified", "verify before")):
                continue
            unknown_failures.append(unknown)
    checks["unknowns_preserved"] = _pass_fail(not unknown_failures)
    for item in unknown_failures:
        findings.append({"code": "unknown_turned_positive", "path": "$script", "detail": item})
    if _packet_mode(packet) in {CONTENT_MODE_PROPERTY_DOSSIER, CONTENT_MODE_TOUR_NARRATION}:
        checks["source_binding"] = _pass_fail("source" in lowered or "observed" in lowered or "dossier" in lowered)
    else:
        checks["source_binding"] = "pass"
    status = "pass" if all(value == "pass" for value in checks.values()) else "fail"
    return {"status": status, "checks": checks, "findings": findings}


def script_receipt_validation(packet: dict[str, object], markdown: str) -> dict[str, str]:
    packet_report = validate_property_content_source_packet(packet)
    script_report = validate_property_content_script(packet, markdown)
    checks = {
        "listing_facts": script_report["checks"].get("listing_facts", "pass"),
        "unknowns_preserved": script_report["checks"].get("unknowns_preserved", "pass"),
        "ranking_integrity": script_report["checks"].get("ranking_integrity", "pass"),
        "source_binding": script_report["checks"].get("source_binding", "pass"),
        "freshness": packet_report["checks"].get("freshness", "fail"),
        "privacy": "pass" if packet_report["checks"].get("privacy") == "pass" and script_report["checks"].get("privacy") == "pass" else "fail",
        "fair_housing": "pass" if packet_report["checks"].get("fair_housing") == "pass" and script_report["checks"].get("fair_housing") == "pass" else "fail",
        "financial_language": "pass"
        if packet_report["checks"].get("financial_language") == "pass"
        and script_report["checks"].get("financial_language") == "pass"
        else "fail",
        "legal_language": "pass"
        if packet_report["checks"].get("legal_language") == "pass" and script_report["checks"].get("legal_language") == "pass"
        else "fail",
        "media_rights": "pass" if not bool(dict(packet.get("media_rights") or {}).get("listing_images_allowed_for_video")) else "review_required",
        "brand_voice": "pass",
    }
    return checks
