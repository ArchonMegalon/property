from __future__ import annotations

import base64
import hashlib
import hmac
import os
import urllib.parse
from uuid import uuid4

from app.domain.models import now_utc_iso
from app.repositories.property_packet_publications import PropertyPacketPublicationRepository
from app.services.dadan.adapter import DadanAdapter, EnvDadanAdapter


_REQUEST_KINDS = {
    "agent_missing_fact",
    "seller_walkthrough",
    "family_review",
    "advisor_review",
    "investment_question",
    "viewing_followup",
    "support_onboarding",
    "public_testimonial",
}

_SAFE_METADATA_KEYS = {
    "property_ref_hash",
    "request_kind",
    "audience_type",
    "packet_kind",
    "privacy_mode",
    "source_ref_hash",
}


def _clean(value: object, *, limit: int = 1000) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _safe_metadata(value: dict[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, raw in dict(value or {}).items():
        normalized_key = _clean(key, limit=80)
        if not normalized_key or normalized_key not in _SAFE_METADATA_KEYS:
            continue
        if isinstance(raw, (str, int, float, bool)) or raw is None:
            safe[normalized_key] = raw if not isinstance(raw, str) else _clean(raw, limit=500)
    return safe


def _hash_ref(value: object) -> str:
    normalized = _clean(value, limit=1000)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _safe_dadan_recording_url(value: object) -> str:
    normalized = _clean(value, limit=1000)
    if not normalized:
        return ""
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return ""
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    allowed_hosts = ("dadan.io", "app.dadan.io", "www.dadan.io")
    if host not in allowed_hosts and not host.endswith(".dadan.io"):
        return ""
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def _default_agent_missing_fact_instructions(title: str) -> str:
    return (
        "Please record a short 2-3 minute walkthrough. Cover: "
        "1. Show or confirm the heating type. "
        "2. Show the room layout and floorplan if available. "
        "3. Confirm whether bedrooms face street or courtyard. "
        "4. Mention the latest operating-cost statement and recurring extras. "
        "5. Show visible renovation or maintenance concerns. "
        "Do not include private buyer information."
    )


class DadanVideoRequestService:
    def __init__(
        self,
        *,
        repo: PropertyPacketPublicationRepository,
        adapter: DadanAdapter | None = None,
    ) -> None:
        self._repo = repo
        self._adapter = adapter or EnvDadanAdapter()

    def create_recording_request(
        self,
        *,
        principal_id: str,
        property_ref: str,
        property_url: str = "",
        request_kind: str = "agent_missing_fact",
        audience_type: str = "agent",
        title: str = "",
        instructions: str = "",
        metadata: dict[str, object] | None = None,
        actor: str = "browser",
    ) -> dict[str, object]:
        normalized_kind = _clean(request_kind, limit=80) or "agent_missing_fact"
        if normalized_kind not in _REQUEST_KINDS:
            raise ValueError("invalid_dadan_video_request_kind")
        normalized_title = _clean(title, limit=240) or f"PropertyQuarry video request: {_clean(property_ref, limit=120)}"
        normalized_instructions = _clean(instructions, limit=4000) or _default_agent_missing_fact_instructions(normalized_title)
        safe_meta = _safe_metadata(metadata)
        created = self._adapter.create_recording_request(
            title=normalized_title,
            instructions=normalized_instructions,
            metadata={
                **safe_meta,
                "property_ref_hash": _hash_ref(property_ref),
                "request_kind": normalized_kind,
                "audience_type": _clean(audience_type, limit=80) or "agent",
            },
        )
        request_id = f"dadan_req_{uuid4().hex}"
        payload = {
            "request_id": request_id,
            "principal_id": _clean(principal_id, limit=240),
            "property_ref": _clean(property_ref, limit=500),
            "property_url": _clean(property_url, limit=1000),
            "request_kind": normalized_kind,
            "audience_type": _clean(audience_type, limit=80) or "agent",
            "dadan_request_code": created.request_code,
            "dadan_request_url": created.request_url,
            "title": normalized_title,
            "instructions": normalized_instructions,
            "metadata_json": safe_meta,
            "status": created.status,
            "trust_state": "operator_requested",
            "created_at": now_utc_iso(),
            "updated_at": now_utc_iso(),
            "raw_response_json": created.raw_response_json,
        }
        event = self._repo.record_event(
            {
                "publication_id": "",
                "principal_id": principal_id,
                "event_type": "property_video_request_created",
                "actor": actor,
                "payload_json": payload,
            }
        )
        return {"status": "created", "request": payload, "event_id": str(event.get("event_id") or "")}

    def request_by_code(self, request_code: str) -> dict[str, object] | None:
        code = _clean(request_code, limit=160)
        if not code:
            return None
        for event in self._repo.list_events(event_type="property_video_request_created", limit=500):
            payload = dict(event.get("payload_json") or {})
            if _clean(payload.get("dadan_request_code"), limit=160) == code:
                return payload
        return None

    def ingest_recording_submitted_webhook(
        self,
        *,
        payload: dict[str, object],
        actor: str = "dadan_webhook",
        secret_mode: str = "",
    ) -> dict[str, object]:
        request_code = _clean(payload.get("requestCode") or payload.get("request_code") or payload.get("code"), limit=160)
        raw_recording_url = payload.get("recordingUrl") or payload.get("recording_url") or payload.get("url")
        recording_url = _safe_dadan_recording_url(raw_recording_url)
        if not request_code:
            raise ValueError("dadan_webhook_request_code_missing")
        if not recording_url:
            raise ValueError("dadan_webhook_recording_url_invalid")
        submitted_at = _clean(payload.get("submittedAt") or payload.get("submitted_at"), limit=120)
        title = _clean(payload.get("recordingTitle") or payload.get("title"), limit=240)
        request = self.request_by_code(request_code) if request_code else None
        response_payload = {
            "response_id": f"dadan_resp_{uuid4().hex}",
            "request_id": _clean((request or {}).get("request_id"), limit=160),
            "principal_id": _clean((request or {}).get("principal_id"), limit=240),
            "property_ref": _clean((request or {}).get("property_ref"), limit=500),
            "dadan_request_code": request_code,
            "dadan_recording_url": recording_url,
            "recording_title": title,
            "submitted_at": submitted_at,
            "transcript_json": {},
            "summary_json": {},
            "trust_state": "untrusted_external",
            "review_state": "pending_owner_review",
            "secret_mode": secret_mode,
            "created_at": now_utc_iso(),
        }
        event = self._repo.record_event(
            {
                "publication_id": "",
                "principal_id": str(response_payload["principal_id"]),
                "event_type": "property_video_response_received",
                "actor": actor,
                "payload_json": response_payload,
            }
        )
        return {
            "status": "accepted" if request else "accepted_unmatched",
            "trust": "untrusted_external",
            "review_state": "pending_owner_review",
            "event_id": str(event.get("event_id") or ""),
            "request_id": str(response_payload["request_id"]),
        }


def verify_dadan_webhook_secret(*, headers: dict[str, str], query_secret: str = "") -> str:
    expected = str(os.getenv("DADAN_WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise PermissionError("dadan_webhook_secret_not_configured")
    header = str(headers.get("x-propertyquarry-webhook-secret") or headers.get("x-dadan-webhook-secret") or "").strip()
    if header:
        if not hmac.compare_digest(header, expected):
            raise PermissionError("dadan_webhook_secret_invalid")
        return "header"
    if str(query_secret or "").strip():
        raise PermissionError("dadan_webhook_query_secret_disabled")
    if str(os.getenv("PROPERTYQUARRY_DADAN_WEBHOOK_ALLOW_BASIC_AUTH") or "0").strip().lower() in {"1", "true", "yes", "on"}:
        auth = str(headers.get("authorization") or "").strip()
        if auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8", "ignore")
            except Exception as exc:
                raise PermissionError("dadan_webhook_basic_auth_invalid") from exc
            _, _, password = decoded.partition(":")
            if hmac.compare_digest(password, expected):
                return "basic"
    raise PermissionError("dadan_webhook_secret_invalid")
