from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable
import urllib.parse

import requests

from app.services.property_governed_consent import (
    EXTERNAL_PROCESSING_CONSENT_AUTHORITY,
    EXTERNAL_PROCESSING_CONSENT_VERSION,
    PROPERTY_APARTMENT_VIDEO_CAPABILITY,
    consume_governed_render_consent_receipt,
    governed_property_video_locale,
    governed_property_video_work_item_id,
    governed_render_consent_runtime_readiness,
    issue_governed_render_consent_receipt,
)


GOVERNED_RENDER_CONTRACT = "chummer6-hub.horizon_governed_render_request.v1"
GOVERNED_RENDER_CONTRACT_VERSION = "2026-06-30"
GOVERNED_RENDER_LANE = "ea_governed_render"
_DEFAULT_ENDPOINT_PATH = "/api/internal/propertyquarry/apartment-videos/artifact-requests"
_STABLE_TOKEN = re.compile(r"\A[A-Za-z0-9._:-]+\Z")
_PROPERTY_SLUG = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?\Z")
_LOCALE = re.compile(r"\A[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?\Z")
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_SECRET_BYTES = 4096
_MIN_API_TOKEN_BYTES = 32
_SHA256_HEX = re.compile(r"\A[a-f0-9]{64}\Z")
_RECEIPT_PROJECTION_STRING_FIELDS = (
    "request_id",
    "status",
    "contract_name",
    "contract_version",
    "horizon_id",
    "capability_id",
    "orchestration_lane",
    "visibility",
    "receipt_sha256",
)


def _allowlisted_receipt_projection(receipt: dict[str, object]) -> dict[str, object]:
    projection: dict[str, object] = {}
    for field in _RECEIPT_PROJECTION_STRING_FIELDS:
        value = receipt.get(field)
        if isinstance(value, str) and value:
            if field != "receipt_sha256" or _SHA256_HEX.fullmatch(value):
                projection[field] = value
    for field in ("quota_tracked", "consume_quota"):
        value = receipt.get(field)
        if type(value) is bool:
            projection[field] = value
    artifact_ids = receipt.get("artifact_ids")
    if isinstance(artifact_ids, list) and all(
        isinstance(value, str)
        and len(value) <= 120
        and _STABLE_TOKEN.fullmatch(value) is not None
        for value in artifact_ids
    ):
        projection["artifact_ids"] = list(artifact_ids)
    return projection


@dataclass(frozen=True)
class GovernedPropertyVideoRequestResult:
    status: str
    reason: str
    request_id: str = ""
    provider_key: str = ""
    receipt: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "reason": self.reason,
            "provider_key": self.provider_key,
            "execution_lane": GOVERNED_RENDER_LANE,
            "public_ready": False,
            "launch_eligible": False,
            "video_url": "",
            "flythrough_url": "",
        }
        if self.request_id:
            payload["governed_render_request_id"] = self.request_id
        if self.receipt is not None:
            payload["governed_render_receipt"] = _allowlisted_receipt_projection(
                self.receipt
            )
        return payload


def _first_nonblank_env(*names: str) -> str:
    for name in names:
        if name in os.environ:
            value = str(os.environ.get(name) or "").strip()
            if value:
                return value
    return ""


def _read_small_secret_file(raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 4096:
            return ""
        value = os.read(descriptor, 4097)
        if len(value) > 4096:
            return ""
        return value.decode("utf-8").strip()
    finally:
        os.close(descriptor)


def governed_render_api_token() -> str:
    inline = _first_nonblank_env("PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN")
    if inline:
        return (
            inline
            if _MIN_API_TOKEN_BYTES <= len(inline.encode("utf-8")) <= _MAX_SECRET_BYTES
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in inline)
            else ""
        )
    secret_file = _first_nonblank_env("PROPERTYQUARRY_GOVERNED_RENDER_API_TOKEN_FILE")
    if not secret_file:
        return ""
    try:
        token = _read_small_secret_file(secret_file)
        return (
            token
            if token
            and len(token.encode("utf-8")) >= _MIN_API_TOKEN_BYTES
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in token)
            else ""
        )
    except (OSError, UnicodeError):
        return ""


def governed_render_api_url() -> str:
    return _first_nonblank_env("PROPERTYQUARRY_GOVERNED_RENDER_API_URL")


def governed_render_allowed_origin() -> str:
    return _first_nonblank_env("PROPERTYQUARRY_GOVERNED_RENDER_ALLOWED_ORIGIN")


def _canonical_origin(value: str, *, allow_path: bool) -> str:
    if not value or len(value) > 2048:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        return ""
    is_loopback = hostname in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        return ""
    if not allow_path and parsed.path not in {"", "/"}:
        return ""
    default_port = 443 if parsed.scheme == "https" else 80
    authority_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = authority_host if port in {None, default_port} else f"{authority_host}:{port}"
    return f"{parsed.scheme}://{authority}"


def _valid_internal_endpoint(value: str) -> bool:
    allowed_origin = _canonical_origin(governed_render_allowed_origin(), allow_path=False)
    endpoint_origin = _canonical_origin(value, allow_path=True)
    if not allowed_origin or not endpoint_origin:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return parsed.path == _DEFAULT_ENDPOINT_PATH and hmac.compare_digest(
        endpoint_origin,
        allowed_origin,
    )


def governed_property_video_runtime_readiness() -> dict[str, object]:
    endpoint = governed_render_api_url()
    allowed_origin = governed_render_allowed_origin()
    token_ready = bool(governed_render_api_token())
    endpoint_ready = bool(endpoint and _valid_internal_endpoint(endpoint))
    allowed_origin_ready = bool(
        allowed_origin and _canonical_origin(allowed_origin, allow_path=False)
    )
    locale = governed_property_video_locale()
    locale_ready = bool(locale)
    consent_readiness = governed_render_consent_runtime_readiness()
    blockers: list[str] = []
    if not endpoint:
        blockers.append("governed_render_endpoint_missing")
    elif not endpoint_ready:
        blockers.append("governed_render_endpoint_invalid")
    if not allowed_origin:
        blockers.append("governed_render_allowed_origin_missing")
    elif not allowed_origin_ready:
        blockers.append("governed_render_allowed_origin_invalid")
    if not token_ready:
        blockers.append("governed_render_internal_token_missing")
    if not locale_ready:
        blockers.append("governed_render_locale_invalid")
    blockers.extend(
        str(value)
        for value in consent_readiness.get("blockers", [])
        if str(value)
    )
    consent_checks = dict(consent_readiness.get("checks") or {})
    return {
        "provider_key": "governed_render",
        "provider_backend_key": "governed_render",
        "execution_lane": GOVERNED_RENDER_LANE,
        "ready": not blockers,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "checks": {
            "endpoint_configured": bool(endpoint),
            "endpoint_valid": endpoint_ready,
            "allowed_origin_configured": bool(allowed_origin),
            "allowed_origin_valid": allowed_origin_ready,
            "endpoint_origin_allowlisted": endpoint_ready,
            "internal_token_configured": token_ready,
            "locale_configured": locale_ready,
            "locale": locale,
            "contract_name": GOVERNED_RENDER_CONTRACT,
            "contract_version": GOVERNED_RENDER_CONTRACT_VERSION,
            "capability_id": PROPERTY_APARTMENT_VIDEO_CAPABILITY,
            "provider_execution_in_web_process": False,
            **consent_checks,
        },
    }


def _stable_actor_token(value: object) -> str:
    raw = str(value or "").strip()
    if raw and _STABLE_TOKEN.fullmatch(raw):
        return raw[:120]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"propertyquarry.subject.{digest}"


def _bounded_timeout_seconds() -> float:
    raw = str(os.getenv("PROPERTYQUARRY_GOVERNED_RENDER_TIMEOUT_SECONDS") or "10").strip()
    try:
        parsed = float(raw)
    except ValueError:
        parsed = 10.0
    return max(1.0, min(parsed, 30.0))


def _request_body(
    *,
    slug: str,
    principal_id: object,
    actor: object,
    preferred_provider_key: object,
    property_id: str,
    tour_revision: str,
    locale: str,
    external_processing_consent: dict[str, object],
) -> dict[str, object]:
    provider = str(preferred_provider_key or "").strip().lower() or "magicai"
    account_ref = hashlib.sha256(str(principal_id or "").strip().encode("utf-8")).hexdigest()[:24]
    work_item_id = governed_property_video_work_item_id(
        slug=slug,
        provider_key=provider,
        tour_revision=tour_revision,
    )
    versioned_packet_ref = (
        f"propertyquarry:property-packet:{slug}:revision:{tour_revision}"
    )
    versioned_property_ref = f"propertyquarry:{slug}:revision:{tour_revision}"
    versioned_continuity_ref = (
        f"propertyquarry:property-continuity:{slug}:revision:{tour_revision}"
    )
    artifact_payload = json.dumps(
        {
            "contract_name": "propertyquarry.apartment_video_input.v1",
            "property_slug": slug,
            "prompt_ref": versioned_packet_ref,
            "account_route_ref": f"propertyquarry:account-route:{account_ref}",
            "continuity_ref": versioned_continuity_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    consent_id = str(external_processing_consent["consent_id"])
    return {
        "userId": _stable_actor_token(principal_id),
        "propertyId": property_id,
        "workItemId": work_item_id,
        "requestedBy": _stable_actor_token(actor or "ea.propertyquarry"),
        "visibility": "private",
        "externalProcessingConsent": external_processing_consent["granted"],
        "preferredProvider": provider,
        "consumeQuota": True,
        # Titles frequently contain an exact street address. The governed lane
        # resolves the private property packet through refs instead of copying
        # customer-facing title text across the service boundary.
        "subject": "PropertyQuarry apartment video request",
        "audience": "property-reviewer",
        "locale": locale,
        "truthRefs": [
            versioned_property_ref,
            versioned_packet_ref,
        ],
        "evidenceRefs": [
            f"propertyquarry:account-route:{account_ref}",
            versioned_continuity_ref,
            f"propertyquarry:external-processing-consent:{consent_id}",
            f"propertyquarry:tour-revision:{tour_revision}",
        ],
        "artifacts": [
            {
                "artifactId": "walkthrough",
                "role": "walkthrough",
                "category": "propertyquarry/apartment-video/walkthrough",
                "payload": artifact_payload,
                "outputFormat": "mp4",
                "deduplicationKey": f"{work_item_id}:walkthrough",
                "aspectRatio": "16:9",
                "durationProfile": "short",
                "maxBytes": 64 * 1024 * 1024,
                "requiresApproval": True,
                "persistOnApproval": True,
                "allowPersistentPinning": True,
            }
        ],
    }


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("governed_render_response_duplicate_key")
        payload[key] = value
    return payload


def _reject_nonfinite_json_constant(_value: str) -> None:
    raise ValueError("governed_render_response_nonfinite_number")


def _response_json(response: requests.Response) -> dict[str, object]:
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks: list[bytes] = []
        total = 0
        for chunk in iterator(chunk_size=64 * 1024):
            body = bytes(chunk or b"")
            total += len(body)
            if total > _MAX_RESPONSE_BYTES:
                raise ValueError("governed_render_response_too_large")
            chunks.append(body)
        content = b"".join(chunks)
    else:
        content = bytes(response.content or b"")
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ValueError("governed_render_response_too_large")
    payload = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_nonfinite_json_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("governed_render_response_invalid")
    return payload


def _accepted_receipt_valid(
    *,
    payload: dict[str, object],
    receipt: dict[str, object],
    body: dict[str, object],
) -> bool:
    request_id = str(receipt.get("requestId") or "").strip()
    source_ref = (
        "propertyquarry:apartment-video:"
        f"{body['propertyId']}:{body['workItemId']}"
    )
    bridge_payload = payload.get("payload")
    bridge = dict(bridge_payload) if isinstance(bridge_payload, dict) else {}
    contract_value = receipt.get("governedRenderRequest")
    contract = dict(contract_value) if isinstance(contract_value, dict) else {}
    truth_refs = contract.get("truthRefs")
    evidence_refs = contract.get("evidenceRefs")
    artifacts = contract.get("artifacts")
    expected_truth_refs = body.get("truthRefs")
    expected_evidence_refs = body.get("evidenceRefs")
    expected_artifacts = body.get("artifacts")
    if not (
        str(receipt.get("status") or "").strip().lower() == "accepted"
        and bool(request_id)
        and len(request_id) <= 160
        and _STABLE_TOKEN.fullmatch(request_id) is not None
        and receipt.get("horizonId") == "propertyquarry"
        and receipt.get("capabilityId") == PROPERTY_APARTMENT_VIDEO_CAPABILITY
        and receipt.get("sourceRef") == source_ref
        and receipt.get("requestedByUserId") == body["userId"]
        and receipt.get("visibility") == "private"
        and receipt.get("externalProcessingConsent") is True
        and receipt.get("blockedReasons") == []
        and receipt.get("quotaTracked") is True
        and isinstance(receipt.get("quota"), dict)
        and bridge.get("consumeQuota") is True
        and contract.get("contractName") == GOVERNED_RENDER_CONTRACT
        and contract.get("contractVersion") == GOVERNED_RENDER_CONTRACT_VERSION
        and contract.get("orchestrationLane") == GOVERNED_RENDER_LANE
        and contract.get("horizonId") == "propertyquarry"
        and contract.get("capabilityId") == PROPERTY_APARTMENT_VIDEO_CAPABILITY
        and contract.get("sourceRef") == source_ref
        and contract.get("workItemId") == body["workItemId"]
        and contract.get("requestedBy") == body["requestedBy"]
        and contract.get("subject") == body["subject"]
        and contract.get("audience") == body["audience"]
        and contract.get("locale") == body["locale"]
        and contract.get("preferredProvider") == body["preferredProvider"]
        and isinstance(truth_refs, list)
        and all(isinstance(item, str) for item in truth_refs)
        and isinstance(expected_truth_refs, list)
        and all(isinstance(item, str) for item in expected_truth_refs)
        and truth_refs == expected_truth_refs
        and isinstance(evidence_refs, list)
        and all(isinstance(item, str) for item in evidence_refs)
        and isinstance(expected_evidence_refs, list)
        and all(isinstance(item, str) for item in expected_evidence_refs)
        and evidence_refs == expected_evidence_refs
        and isinstance(artifacts, list)
        and isinstance(expected_artifacts, list)
        and len(artifacts) == len(expected_artifacts) == 1
    ):
        return False
    received_artifact = artifacts[0]
    expected_artifact = expected_artifacts[0]
    if not isinstance(received_artifact, dict) or not isinstance(
        expected_artifact, dict
    ):
        return False
    return received_artifact == expected_artifact


def _receipt_projection(
    *,
    payload: dict[str, object],
    receipt: dict[str, object],
) -> dict[str, object]:
    contract_value = receipt.get("governedRenderRequest")
    contract = dict(contract_value) if isinstance(contract_value, dict) else {}
    artifacts_value = contract.get("artifacts")
    artifacts = list(artifacts_value) if isinstance(artifacts_value, list) else []
    bridge_value = payload.get("payload")
    bridge = dict(bridge_value) if isinstance(bridge_value, dict) else {}
    canonical_receipt = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _allowlisted_receipt_projection(
        {
            "request_id": str(receipt["requestId"]),
            "status": "accepted",
            "contract_name": str(contract["contractName"]),
            "contract_version": str(contract["contractVersion"]),
            "horizon_id": str(receipt["horizonId"]),
            "capability_id": str(receipt["capabilityId"]),
            "orchestration_lane": str(contract["orchestrationLane"]),
            "visibility": str(receipt["visibility"]),
            "quota_tracked": receipt["quotaTracked"] is True,
            "consume_quota": bridge.get("consumeQuota") is True,
            "artifact_ids": [
                str(artifact["artifactId"])
                for artifact in artifacts
                if isinstance(artifact, dict)
            ],
            "receipt_sha256": hashlib.sha256(canonical_receipt).hexdigest(),
        }
    )


def submit_governed_property_video_request(
    *,
    slug: object,
    title: object,
    principal_id: object,
    actor: object,
    preferred_provider_key: object = "magicai",
    property_id: object = "",
    tour_revision: object = "",
    locale: object = "",
    external_processing_consent_receipt: object = "",
    post: Callable[..., requests.Response] | None = None,
) -> GovernedPropertyVideoRequestResult:
    normalized_slug = str(slug or "").strip().lower()
    if not _PROPERTY_SLUG.fullmatch(normalized_slug):
        return GovernedPropertyVideoRequestResult("blocked", "governed_render_property_slug_invalid")
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        return GovernedPropertyVideoRequestResult(
            "blocked", "governed_render_principal_missing"
        )
    normalized_provider = str(preferred_provider_key or "").strip().lower() or "magicai"
    if (
        len(normalized_provider) > 64
        or _STABLE_TOKEN.fullmatch(normalized_provider) is None
    ):
        return GovernedPropertyVideoRequestResult(
            "blocked", "governed_render_provider_invalid"
        )
    normalized_property_id = str(property_id or "").strip()
    if (
        not normalized_property_id
        or len(normalized_property_id) > 160
        or _STABLE_TOKEN.fullmatch(normalized_property_id) is None
    ):
        return GovernedPropertyVideoRequestResult(
            "blocked", "governed_render_property_id_invalid"
        )
    normalized_revision = str(tour_revision or "").strip().lower()
    if _SHA256_HEX.fullmatch(normalized_revision) is None:
        return GovernedPropertyVideoRequestResult(
            "blocked", "governed_render_tour_revision_invalid"
        )
    normalized_locale = str(locale or "").strip()
    if _LOCALE.fullmatch(normalized_locale) is None:
        return GovernedPropertyVideoRequestResult(
            "blocked", "governed_render_locale_invalid"
        )
    readiness = governed_property_video_runtime_readiness()
    if readiness.get("ready") is not True:
        blockers = [str(item) for item in readiness.get("blockers", []) if str(item)]
        return GovernedPropertyVideoRequestResult(
            "blocked",
            blockers[0] if blockers else "governed_render_unavailable",
        )
    work_item_id = governed_property_video_work_item_id(
        slug=normalized_slug,
        provider_key=normalized_provider,
        tour_revision=normalized_revision,
    )
    consent_evidence, consent_error = consume_governed_render_consent_receipt(
        token=str(external_processing_consent_receipt or "").strip(),
        principal_id=normalized_principal,
        property_slug=normalized_slug,
        property_id=normalized_property_id,
        tour_revision=normalized_revision,
        provider_key=normalized_provider,
        work_item_id=work_item_id,
        locale=normalized_locale,
    )
    if consent_evidence is None:
        return GovernedPropertyVideoRequestResult("blocked", consent_error)
    body = _request_body(
        slug=normalized_slug,
        principal_id=normalized_principal,
        actor=actor,
        preferred_provider_key=normalized_provider,
        property_id=normalized_property_id,
        tour_revision=normalized_revision,
        locale=normalized_locale,
        external_processing_consent=consent_evidence,
    )
    session: requests.Session | None = None
    if post is None:
        session = requests.Session()
        # Internal bearer authority must never be forwarded through ambient
        # HTTP(S)_PROXY or netrc configuration inherited by the web process.
        session.trust_env = False
        sender = session.post
    else:
        sender = post
    try:
        try:
            response = sender(
                governed_render_api_url(),
                json=body,
                headers={
                    "Authorization": f"Bearer {governed_render_api_token()}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=_bounded_timeout_seconds(),
                allow_redirects=False,
                stream=True,
            )
            try:
                if int(response.status_code) != 200:
                    return GovernedPropertyVideoRequestResult(
                        "blocked",
                        f"governed_render_request_rejected_{int(response.status_code)}",
                    )
                payload = _response_json(response)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except Exception:
            return GovernedPropertyVideoRequestResult("blocked", "governed_render_request_failed")
    finally:
        if session is not None:
            session.close()

    receipt = payload.get("artifactRequestReceipt")
    receipt_payload = dict(receipt) if isinstance(receipt, dict) else {}
    request_id = str(receipt_payload.get("requestId") or "").strip()
    if not _accepted_receipt_valid(
        payload=payload,
        receipt=receipt_payload,
        body=body,
    ):
        return GovernedPropertyVideoRequestResult("blocked", "governed_render_receipt_invalid")
    return GovernedPropertyVideoRequestResult(
        status="pending",
        reason="governed_render_request_accepted",
        request_id=request_id,
        provider_key=str(body["preferredProvider"]),
        receipt=_receipt_projection(payload=payload, receipt=receipt_payload),
    )
