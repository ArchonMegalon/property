#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

if __package__:
    from scripts.propertyquarry_strict_json import load_strict_json_object_snapshot
else:
    from propertyquarry_strict_json import load_strict_json_object_snapshot


CONTRACT_SCHEMA = "propertyquarry.jurisdiction_privacy_rights.v1"
LIVE_RECEIPT_SCHEMA = "propertyquarry.jurisdiction_privacy_rights_live_receipt.v1"
GATE_SCHEMA = "propertyquarry.jurisdiction_privacy_rights_gate.v1"
MARKET_ENVELOPE_SCHEMA = "propertyquarry.global_market_envelope.v1"
DEFAULT_CONTRACT = Path("config/compliance/propertyquarry_jurisdiction_privacy_rights.v1.json")
REQUIRED_MARKETS = ("AT", "DE", "CR")
REQUIRED_CONTROLS = (
    "controller_processor_roles",
    "processing_purpose_and_lawful_basis",
    "consent_withdrawal_and_preference_evidence",
    "localized_privacy_cookie_and_terms_notices",
    "dsar_identity_export_correction_deletion_and_restriction",
    "retention_tombstone_and_legal_hold",
    "subprocessor_inventory_dpa_and_security_review",
    "international_transfer_mechanism_and_assessment",
    "hosting_backup_logging_and_support_residency",
    "security_breach_detection_and_notification",
    "automated_ranking_explanation_and_human_review",
    "marketing_communications_and_tracking_consent",
    "minors_sensitive_data_and_fairness_policy",
    "consumer_terms_pricing_refunds_and_complaints",
)
PROVIDER_CAPABILITIES = (
    "automated_access",
    "cache_normalized_facts",
    "display_source_attributed_excerpt",
    "store_source_media",
    "generate_media_derivatives",
    "public_packet_republication",
)
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
OPAQUE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{5,199}")


def _load_json(path: Path) -> dict[str, Any]:
    payload, _raw, _digest = load_strict_json_object_snapshot(
        path,
        field="jurisdiction privacy rights artifact",
    )
    return payload


def _load_json_with_sha256(path: Path) -> tuple[dict[str, Any], str]:
    payload, _raw, digest = load_strict_json_object_snapshot(
        path,
        field="jurisdiction privacy rights artifact",
    )
    return payload, f"sha256:{digest}"


def _timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _opaque_ref(value: object) -> bool:
    raw = str(value or "").strip()
    return bool(OPAQUE_REF_RE.fullmatch(raw)) and not any(
        token in raw.casefold()
        for token in ("unconfigured", "unassigned", "placeholder", "example", "sample", "todo", "tbd")
    )


def _safe_https_url(value: object) -> bool:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    hostname = str(parsed.hostname or "").casefold()
    return (
        parsed.scheme == "https"
        and bool(hostname)
        and parsed.username is None
        and parsed.password is None
        and hostname not in {"localhost", "127.0.0.1", "::1"}
        and not hostname.endswith((".localhost", ".test", ".example", ".invalid"))
        and not any(token in raw.casefold() for token in ("placeholder", "unconfigured", "todo", "tbd"))
    )


def _proof_record(value: object, *, now: datetime) -> bool:
    if not isinstance(value, Mapping):
        return False
    observed_at = _timestamp(value.get("observed_at"))
    return (
        str(value.get("status") or "").strip().casefold() == "pass"
        and observed_at is not None
        and observed_at <= now
        and bool(DIGEST_RE.fullmatch(str(value.get("evidence_digest") or "").strip().casefold()))
    )


def _approval_record(value: object, *, now: datetime) -> bool:
    if not _proof_record(value, now=now) or not isinstance(value, Mapping):
        return False
    observed_at = _timestamp(value.get("observed_at"))
    expires_at = _timestamp(value.get("expires_at"))
    return (
        observed_at is not None
        and expires_at is not None
        and observed_at <= now < expires_at
        and expires_at > observed_at
        and (expires_at - observed_at).total_seconds() <= 400 * 24 * 3600
        and _opaque_ref(value.get("reviewer_ref"))
        and _opaque_ref(value.get("approval_ref"))
    )


def _recent_proof_record(
    value: object,
    *,
    now: datetime,
    max_age_hours: float,
) -> bool:
    if not _proof_record(value, now=now) or not isinstance(value, Mapping):
        return False
    observed_at = _timestamp(value.get("observed_at"))
    return (
        observed_at is not None
        and 0 <= (now - observed_at).total_seconds() <= max_age_hours * 3600
    )


def validate_source_contract(contract: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("service") != "propertyquarry":
        blockers.append("jurisdiction/privacy/rights source contract has the wrong schema or service")
    if contract.get("source_contract_status") != "defined":
        blockers.append("jurisdiction/privacy/rights source contract is not defined")
    if contract.get("market_envelope_path") != "docs/propertyquarry_global_market_envelope.v1.json":
        blockers.append("jurisdiction/privacy/rights contract is not bound to the governed market-envelope path")
    if contract.get("required_markets") != list(REQUIRED_MARKETS):
        blockers.append("jurisdiction/privacy/rights required markets are incomplete or out of order")
    if contract.get("required_controls") != list(REQUIRED_CONTROLS):
        blockers.append("jurisdiction/privacy/rights required controls are incomplete or out of order")
    if contract.get("provider_capabilities") != list(PROVIDER_CAPABILITIES):
        blockers.append("jurisdiction/privacy/rights provider capabilities are incomplete or out of order")

    requirements = contract.get("market_requirements")
    expected_languages = {"AT": "de-AT", "DE": "de-DE", "CR": "es-CR"}
    expected_eu_transfer_assessment = {"AT": True, "DE": True, "CR": False}
    if not isinstance(requirements, Mapping) or list(requirements) != list(REQUIRED_MARKETS):
        blockers.append("jurisdiction/privacy/rights market requirements are incomplete or out of order")
    else:
        for country_code, language in expected_languages.items():
            row = requirements.get(country_code)
            if (
                not isinstance(row, Mapping)
                or row.get("notice_language") != language
                or row.get("requires_local_privacy_counsel") is not True
                or row.get("requires_local_consumer_counsel") is not True
                or row.get("requires_eu_transfer_assessment")
                is not expected_eu_transfer_assessment[country_code]
            ):
                blockers.append(f"jurisdiction/privacy/rights market requirement is incomplete: {country_code}")

    policy = contract.get("launch_policy")
    required_policy_flags = (
        "independent_qualified_review_required",
        "exact_release_and_image_binding_required",
        "current_market_envelope_binding_required",
        "provider_permissions_must_cover_only_enabled_capabilities",
        "technical_enforcement_required_for_prohibited_capabilities",
        "source_contract_is_not_legal_approval",
    )
    if not isinstance(policy, Mapping) or any(policy.get(key) is not True for key in required_policy_flags):
        blockers.append("jurisdiction/privacy/rights fail-closed launch policy is incomplete")
    return list(dict.fromkeys(blockers))


def _market_envelope_blockers(envelope: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if envelope.get("schema") != MARKET_ENVELOPE_SCHEMA:
        blockers.append("governed market envelope has the wrong schema")
    markets = envelope.get("markets")
    codes = [
        str(row.get("country_code") or "").strip().upper()
        for row in markets or []
        if isinstance(row, Mapping)
    ] if isinstance(markets, list) else []
    if codes != list(REQUIRED_MARKETS):
        blockers.append("governed market envelope does not define exact AT/DE/CR scope")
    return blockers


def build_gate(
    *,
    contract_path: Path,
    market_envelope_path: Path,
    live_receipt_path: Path | None = None,
    expected_release_sha: str = "",
    expected_image_digest: str = "",
    max_age_hours: float = 24.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract, contract_digest = _load_json_with_sha256(contract_path)
    envelope, envelope_digest = _load_json_with_sha256(market_envelope_path)
    source_blockers = validate_source_contract(contract)
    envelope_blockers = _market_envelope_blockers(envelope)
    governed_envelope_path = (
        contract_path.resolve().parents[2]
        / str(contract.get("market_envelope_path") or "")
    ).resolve()
    if market_envelope_path.resolve() != governed_envelope_path:
        envelope_blockers.append(
            "market envelope path does not match the governed source contract"
        )
    blockers = [*source_blockers, *envelope_blockers]
    expected_release_sha = str(expected_release_sha or "").strip().casefold()
    expected_image_digest = str(expected_image_digest or "").strip().casefold()
    live: dict[str, Any] | None = None
    age_seconds: float | None = None

    if not SHA_RE.fullmatch(expected_release_sha):
        blockers.append("expected exact 40-character release SHA is required")
    if not DIGEST_RE.fullmatch(expected_image_digest):
        blockers.append("expected immutable sha256 image digest is required")
    if live_receipt_path is None:
        blockers.append("fresh independently attested live jurisdiction/privacy/provider-rights receipt is required")
    else:
        try:
            live = _load_json(live_receipt_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(f"live jurisdiction/privacy/provider-rights receipt is unreadable: {type(exc).__name__}")

    if live is not None:
        if live.get("schema") != LIVE_RECEIPT_SCHEMA:
            blockers.append("live jurisdiction/privacy/provider-rights receipt has the wrong schema")
        if live.get("profile") != "launch" or live.get("claim_scope") != "core":
            blockers.append("live jurisdiction/privacy/provider-rights receipt is not launch-tier Core evidence")
        generated_at = _timestamp(live.get("generated_at"))
        if generated_at is None:
            blockers.append("live jurisdiction/privacy/provider-rights receipt has no timezone-aware generated_at")
        else:
            age_seconds = (now - generated_at).total_seconds()
            if age_seconds < 0 or age_seconds > max_age_hours * 3600:
                blockers.append("live jurisdiction/privacy/provider-rights receipt is stale or future-dated")
        if str(live.get("contract_sha256") or "").strip().casefold() != contract_digest:
            blockers.append("live jurisdiction/privacy/provider-rights receipt is not bound to the current source contract")
        if str(live.get("market_envelope_sha256") or "").strip().casefold() != envelope_digest:
            blockers.append("live jurisdiction/privacy/provider-rights receipt is not bound to the current market envelope")
        identity = live.get("release_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        if str(identity.get("commit_sha") or "").strip().casefold() != expected_release_sha:
            blockers.append("live jurisdiction/privacy/provider-rights receipt commit does not match the expected release")
        if str(identity.get("image_digest") or "").strip().casefold() != expected_image_digest:
            blockers.append("live jurisdiction/privacy/provider-rights receipt image does not match the expected release")

        requirements = contract.get("market_requirements")
        requirements = requirements if isinstance(requirements, Mapping) else {}
        market_rows = live.get("market_compliance")
        market_index = {
            str(row.get("country_code") or "").strip().upper(): row
            for row in market_rows or []
            if isinstance(row, Mapping) and str(row.get("country_code") or "").strip()
        } if isinstance(market_rows, list) else {}
        if set(market_index) != set(REQUIRED_MARKETS) or len(market_rows or []) != len(REQUIRED_MARKETS):
            blockers.append("live compliance receipt does not contain exactly one AT, DE, and CR market row")
        for country_code in REQUIRED_MARKETS:
            row = market_index.get(country_code)
            requirement = requirements.get(country_code)
            if not isinstance(row, Mapping) or not isinstance(requirement, Mapping):
                blockers.append(f"live compliance market row is missing: {country_code}")
                continue
            if row.get("launch_approved") is not True:
                blockers.append(f"market {country_code} lacks explicit launch approval")
            if row.get("notice_language") != requirement.get("notice_language"):
                blockers.append(f"market {country_code} notice language does not match the governed contract")
            for key in ("controller_legal_entity_ref", "data_residency_decision_ref"):
                if not _opaque_ref(row.get(key)):
                    blockers.append(f"market {country_code} lacks a governed {key}")
            for key in ("privacy_notice_url", "cookie_notice_url", "terms_url", "dsar_url"):
                if not _safe_https_url(row.get(key)):
                    blockers.append(f"market {country_code} lacks a safe live {key}")
            hosting_regions = row.get("hosting_regions")
            if not isinstance(hosting_regions, list) or not hosting_regions or any(not _opaque_ref(item) for item in hosting_regions):
                blockers.append(f"market {country_code} lacks governed hosting and backup regions")
            legal_approval = row.get("local_legal_approval")
            if (
                not _approval_record(legal_approval, now=now)
                or not isinstance(legal_approval, Mapping)
                or legal_approval.get("independent_of_implementation") is not True
                or not _opaque_ref(legal_approval.get("reviewer_qualification_ref"))
            ):
                blockers.append(f"market {country_code} lacks current independent qualified local legal approval")
            controls = row.get("controls")
            if not isinstance(controls, Mapping) or set(controls) != set(REQUIRED_CONTROLS):
                blockers.append(f"market {country_code} compliance controls are incomplete")
            else:
                for control in REQUIRED_CONTROLS:
                    if not _approval_record(controls.get(control), now=now):
                        blockers.append(f"market {country_code} control is not currently approved: {control}")

        inventory_rows = live.get("market_provider_inventory")
        inventory_index = {
            str(row.get("country_code") or "").strip().upper(): row
            for row in inventory_rows or []
            if isinstance(row, Mapping) and str(row.get("country_code") or "").strip()
        } if isinstance(inventory_rows, list) else {}
        if set(inventory_index) != set(REQUIRED_MARKETS) or len(inventory_rows or []) != len(REQUIRED_MARKETS):
            blockers.append("live provider inventory does not contain exactly one AT, DE, and CR row")
        enabled_by_provider: dict[str, dict[str, set[str]]] = {}
        for country_code in REQUIRED_MARKETS:
            inventory = inventory_index.get(country_code)
            if not isinstance(inventory, Mapping):
                blockers.append(f"live provider inventory is missing: {country_code}")
                continue
            if not DIGEST_RE.fullmatch(str(inventory.get("inventory_digest") or "").strip().casefold()):
                blockers.append(f"market {country_code} provider inventory lacks an immutable digest")
            providers = inventory.get("providers")
            if not isinstance(providers, list) or not providers:
                blockers.append(f"market {country_code} provider inventory is empty")
                continue
            seen: set[str] = set()
            for provider in providers:
                provider = provider if isinstance(provider, Mapping) else {}
                provider_id = str(provider.get("provider_id") or "").strip()
                capabilities = {
                    str(item or "").strip()
                    for item in provider.get("enabled_capabilities") or []
                    if str(item or "").strip()
                } if isinstance(provider.get("enabled_capabilities"), list) else set()
                if not _opaque_ref(provider_id) or provider_id in seen:
                    blockers.append(f"market {country_code} provider inventory has an invalid or duplicate provider")
                    continue
                seen.add(provider_id)
                if not capabilities or not capabilities.issubset(set(PROVIDER_CAPABILITIES)):
                    blockers.append(f"market {country_code} provider {provider_id} has invalid enabled capabilities")
                enabled_by_provider.setdefault(provider_id, {})[country_code] = capabilities

        rights_rows = live.get("provider_rights")
        rights_index = {
            str(row.get("provider_id") or "").strip(): row
            for row in rights_rows or []
            if isinstance(row, Mapping) and str(row.get("provider_id") or "").strip()
        } if isinstance(rights_rows, list) else {}
        if set(rights_index) != set(enabled_by_provider) or len(rights_rows or []) != len(enabled_by_provider):
            blockers.append("provider-rights rows do not exactly cover the launch provider inventory")
        all_capabilities = set(PROVIDER_CAPABILITIES)
        for provider_id, market_usage in enabled_by_provider.items():
            rights = rights_index.get(provider_id)
            if not isinstance(rights, Mapping):
                blockers.append(f"provider rights are missing: {provider_id}")
                continue
            approved_markets = {
                str(item or "").strip().upper()
                for item in rights.get("country_codes") or []
                if str(item or "").strip()
            } if isinstance(rights.get("country_codes"), list) else set()
            permitted = {
                str(item or "").strip()
                for item in rights.get("permitted_capabilities") or []
                if str(item or "").strip()
            } if isinstance(rights.get("permitted_capabilities"), list) else set()
            prohibited = {
                str(item or "").strip()
                for item in rights.get("prohibited_capabilities") or []
                if str(item or "").strip()
            } if isinstance(rights.get("prohibited_capabilities"), list) else set()
            if approved_markets != set(market_usage):
                blockers.append(f"provider {provider_id} rights do not match its exact market use")
            if permitted & prohibited or permitted | prohibited != all_capabilities:
                blockers.append(f"provider {provider_id} rights do not partition every governed capability")
            for country_code, enabled in market_usage.items():
                if not enabled.issubset(permitted):
                    blockers.append(f"provider {provider_id} enables an unapproved capability in {country_code}")
            if not _approval_record(rights.get("terms_and_rights_review"), now=now):
                blockers.append(f"provider {provider_id} lacks a current terms and rights approval")
            enforcement = rights.get("technical_enforcement")
            if (
                not _recent_proof_record(
                    enforcement,
                    now=now,
                    max_age_hours=max_age_hours,
                )
                or not isinstance(enforcement, Mapping)
                or set(enforcement.get("enforced_prohibitions") or []) != prohibited
            ):
                blockers.append(f"provider {provider_id} lacks exact technical enforcement for prohibited capabilities")

        attestation = live.get("attestation_verification")
        if (
            not _recent_proof_record(
                attestation,
                now=now,
                max_age_hours=max_age_hours,
            )
            or not isinstance(attestation, Mapping)
            or attestation.get("authority") != "independent_compliance_controller"
            or attestation.get("independent_of_implementation") is not True
            or not _opaque_ref(attestation.get("workflow_run_ref"))
            or str(attestation.get("subject_commit_sha") or "").strip().casefold() != expected_release_sha
            or str(attestation.get("subject_image_digest") or "").strip().casefold() != expected_image_digest
        ):
            blockers.append("live compliance receipt lacks independent exact-release attestation verification")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": GATE_SCHEMA,
        "status": "blocked" if blockers else "pass",
        "generated_at": now.isoformat(),
        "source_contract": {
            "path": contract_path.as_posix(),
            "sha256": contract_digest,
            "status": "pass" if not source_blockers else "blocked",
        },
        "market_envelope": {
            "path": market_envelope_path.as_posix(),
            "sha256": envelope_digest,
            "status": "pass" if not envelope_blockers else "blocked",
        },
        "live_receipt_path": live_receipt_path.as_posix() if live_receipt_path else "",
        "release_identity": {
            "commit_sha": expected_release_sha,
            "image_digest": expected_image_digest,
        },
        "required_markets": list(REQUIRED_MARKETS),
        "live_receipt_age_seconds": age_seconds,
        "blockers": blockers,
    }


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify PropertyQuarry jurisdiction, privacy-residency, and provider-rights launch evidence."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--market-envelope", type=Path)
    parser.add_argument("--live-receipt", type=Path)
    parser.add_argument("--expected-release-sha", default="")
    parser.add_argument("--expected-image-digest", default="")
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()
    contract = _load_json(args.contract)
    market_envelope_path = args.market_envelope or Path(str(contract.get("market_envelope_path") or ""))
    receipt = build_gate(
        contract_path=args.contract,
        market_envelope_path=market_envelope_path,
        live_receipt_path=args.live_receipt,
        expected_release_sha=args.expected_release_sha,
        expected_image_digest=args.expected_image_digest,
        max_age_hours=args.max_age_hours,
    )
    if args.output:
        _atomic_write(args.output, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 1 if args.fail_on_blocked and receipt["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
