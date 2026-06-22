from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.container import AppContainer
from app.domain.property_preference_events import (
    FLIPLINK_FEEDBACK_SOURCE,
    PREFERENCE_EVENT_FEEDBACK_ACCEPTED,
    PREFERENCE_OBJECT_FEEDBACK,
    PROPERTY_PACKET_FEEDBACK_SOURCE,
    PROPERTY_PREFERENCE_DOMAIN,
)
from app.product.property_score_methodology import (
    build_property_score_methodology,
    build_property_score_methodology_pdf_source,
    resolve_property_score_methodology_language,
)
from app.product.service import build_product_service
from app.settings import get_settings, resolve_signing_secret
from app.services.fliplink import build_fliplink_packet_service
from app.services.fliplink.models import FlipLinkFormat, PacketPrivacyMode, PropertyPacketKind
from app.services.fliplink.pdf_renderer import render_property_packet_pdf, render_property_packet_pdf_legacy
from app.services.public_branding import request_brand


authenticated_router = APIRouter(tags=["fliplink"])
public_router = APIRouter(prefix="/v1/integrations/fliplink", tags=["fliplink"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))


PacketKindLiteral = Literal[
    "owner_review",
    "family_review",
    "agent_brief",
    "shortlist_brochure",
    "paid_market_report",
    "open_house_qr",
]
FlipLinkFormatLiteral = Literal["smart_document", "flipbook_3d"]
PacketPrivacyLiteral = Literal["owner_private", "family_review", "agent_share", "anonymous_public", "paid_customer"]
FeedbackReviewAction = Literal[
    "accept_as_preference_signal",
    "accept_as_viewing_question",
    "dismiss",
    "block_reviewer",
    "convert_to_hard_rule",
]
_REVOKED_PACKET_STATUSES = {"archived", "revoked", "deleted"}


def _score_methodology_pdf_response(
    *,
    container: AppContainer,
    country_code: str,
    language_code: str,
    accept_language: str = "",
) -> FileResponse:
    source_payload = build_property_score_methodology_pdf_source(
        language_code=language_code,
        country_code=country_code,
        accept_language=accept_language,
    )
    methodology = (
        dict(source_payload.get("score_methodology") or {})
        if isinstance(source_payload.get("score_methodology"), dict)
        else {}
    )
    resolved_language = str(methodology.get("language_code") or "en").strip().lower() or "en"
    artifact_root = Path(str(container.settings.storage.artifacts_dir)).resolve()
    rendered = render_property_packet_pdf_legacy(
        artifact_root=artifact_root,
        publication_id=f"score-methodology-{resolved_language}",
        principal_id="propertyquarry-score-methodology",
        source=source_payload,
        packet_kind=PropertyPacketKind.FAMILY_REVIEW,
        privacy_mode=PacketPrivacyMode.ANONYMOUS_PUBLIC,
        fliplink_format=FlipLinkFormat.SMART_DOCUMENT,
        include_exact_address=False,
        include_floorplan=False,
        include_photos=False,
    )
    pdf_path = Path(str(rendered.get("pdf_path") or "")).resolve()
    if (pdf_path != artifact_root and artifact_root not in pdf_path.parents) or not pdf_path.is_file():
        raise HTTPException(status_code=500, detail="property_score_methodology_pdf_not_available")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="propertyquarry-score-methodology-{resolved_language}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "X-PropertyQuarry-Renderer": "fliplink-legacy-score",
        },
    )


class PropertyPacketRenderIn(BaseModel):
    packet_kind: PacketKindLiteral = "owner_review"
    privacy_mode: PacketPrivacyLiteral | None = None
    fliplink_format: FlipLinkFormatLiteral | None = None
    person_id: str = Field(default="self", max_length=120)
    search_run_id: str = Field(default="", max_length=160)
    include_floorplan: bool = True
    include_photos: bool = True
    include_exact_address: bool = False
    property_payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("property_payload")
    @classmethod
    def _payload_size_guard(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(value, separators=(",", ":"), default=str)
        except TypeError as exc:
            raise ValueError("property_payload_must_be_json_serializable") from exc
        if len(encoded.encode("utf-8")) > 100_000:
            raise ValueError("property_payload_too_large")
        return value


class ManualFlipLinkPublicationIn(BaseModel):
    fliplink_url: str = Field(min_length=8, max_length=500)
    fliplink_format: FlipLinkFormatLiteral | None = None
    embed_code: str = Field(default="", max_length=4000)
    qr_url: str = Field(default="", max_length=500)
    lead_capture_enabled: bool = False
    password_required: bool = False
    sale_mode_enabled: bool = False


class FlipLinkFeedbackReviewIn(BaseModel):
    action: FeedbackReviewAction
    note: str = Field(default="", max_length=1000)


class FlipLinkArchivePublicationIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class BrowserActFlipLinkPublishIn(BaseModel):
    lead_capture_enabled: bool = True
    password_required: bool = False


class BrowserActFlipLinkPublishCompleteIn(BaseModel):
    fliplink_url: str = Field(min_length=8, max_length=500)
    embed_code: str = Field(default="", max_length=4000)
    qr_url: str = Field(default="", max_length=500)
    screenshot_proof_ref: str = Field(default="", max_length=500)
    lead_capture_enabled: bool = True
    password_required: bool = False
    sale_mode_enabled: bool = False


class FlipLinkAnalyticsSnapshotIn(BaseModel):
    views: int | None = Field(default=None, ge=0, le=10_000_000)
    unique_visitors: int | None = Field(default=None, ge=0, le=10_000_000)
    average_time_seconds: int | None = Field(default=None, ge=0, le=10_000_000)
    top_pages: list[dict[str, object]] = Field(default_factory=list, max_length=20)
    referral_sources: list[dict[str, object]] = Field(default_factory=list, max_length=20)
    device_breakdown: dict[str, int] = Field(default_factory=dict)
    geography_breakdown: dict[str, int] = Field(default_factory=dict)
    source: Literal["manual", "browseract", "api"] = "manual"
    screenshot_proof_ref: str = Field(default="", max_length=500)
    captured_from_url: str = Field(default="", max_length=500)


class PacketShareRecipientIn(BaseModel):
    name: str = Field(default="", max_length=160)
    email: str = Field(default="", max_length=240)
    relationship: str = Field(default="", max_length=120)
    role_label: str = Field(default="", max_length=120)


class PacketShareCreateIn(BaseModel):
    audience_type: str = Field(default="family", max_length=80)
    channel: str = Field(default="link", max_length=80)
    variant_key: str = Field(default="default", max_length=120)
    cover_note: str = Field(default="", max_length=1000)
    recipients: list[PacketShareRecipientIn] = Field(default_factory=list, max_length=25)


class PacketEngagementEventIn(BaseModel):
    share_id: str = Field(min_length=1, max_length=160)
    recipient_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(min_length=1, max_length=80)
    event_value: str = Field(default="", max_length=240)
    metadata_json: dict[str, object] = Field(default_factory=dict)


class PacketVariantCreateIn(BaseModel):
    audience_type: str = Field(default="family", max_length=80)
    base_variant_key: str = Field(default="default", max_length=120)
    title_override: str = Field(default="", max_length=200)


class PacketAttachSummaryIn(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=160)


class PacketOptimizationAckIn(BaseModel):
    recommendation_id: str = Field(min_length=1, max_length=160)


def _actor(context: RequestContext) -> str:
    return str(context.operator_id or context.access_email or context.principal_id or "browser").strip()


def _publication_out(
    row: dict[str, object],
    *,
    analytics: dict[str, object] | None = None,
    engagement: dict[str, object] | None = None,
    share_journey: dict[str, object] | None = None,
    structured_feedback: list[dict[str, object]] | None = None,
    attached_summaries: list[dict[str, object]] | None = None,
    optimization: list[dict[str, object]] | None = None,
    feedback_summary: dict[str, object] | None = None,
    change_log: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    summary = dict(row.get("packet_summary_json") or {}) if isinstance(row.get("packet_summary_json"), dict) else {}
    status = str(row.get("status") or "").strip().lower()
    public_pdf_path = ""
    if status not in _REVOKED_PACKET_STATUSES:
        public_pdf_path = _public_packet_pdf_path(
            publication_id=str(row.get("publication_id") or ""),
            source_pdf_sha256=str(row.get("source_pdf_sha256") or ""),
        )
    analytics_out = {
        "views": None,
        "unique_visitors": None,
        "average_time_seconds": None,
        "captured_at": "",
        **dict(analytics or {}),
    }
    return {
        "publication_id": str(row.get("publication_id") or ""),
        "principal_id": str(row.get("principal_id") or ""),
        "person_id": str(row.get("person_id") or "self"),
        "property_ref": str(row.get("property_ref") or ""),
        "search_run_id": str(row.get("search_run_id") or ""),
        "packet_kind": str(row.get("packet_kind") or ""),
        "privacy_mode": str(row.get("privacy_mode") or ""),
        "fliplink_format": str(row.get("fliplink_format") or ""),
        "source_pdf_sha256": str(row.get("source_pdf_sha256") or ""),
        "source_pdf_size_bytes": int(row.get("source_pdf_size_bytes") or 0),
        "redaction_policy_version": str(row.get("redaction_policy_version") or ""),
        "fliplink_url": str(row.get("fliplink_url") or ""),
        "fliplink_custom_domain_url": str(row.get("fliplink_custom_domain_url") or ""),
        "fliplink_embed_code": str(row.get("fliplink_embed_code") or ""),
        "fliplink_qr_url": str(row.get("fliplink_qr_url") or ""),
        "lead_capture_enabled": bool(row.get("lead_capture_enabled")),
        "password_required": bool(row.get("password_required")),
        "sale_mode_enabled": bool(row.get("sale_mode_enabled")),
        "status": str(row.get("status") or ""),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "published_at": str(row.get("published_at") or ""),
        "recommended_title": str(row.get("recommended_title") or ""),
        "recommended_format": str(row.get("recommended_format") or ""),
        "artifact_download_path": "" if status in _REVOKED_PACKET_STATUSES else (public_pdf_path or str(row.get("artifact_download_path") or "")),
        "public_pdf_path": public_pdf_path,
        "recommended_folder": str(summary.get("recommended_folder") or ""),
        "recommended_custom_domain": str(summary.get("recommended_custom_domain") or ""),
        "renderer_version": str(summary.get("renderer_version") or ""),
        "packet_summary_json": summary,
        "analytics": analytics_out,
        "engagement": dict(engagement or {"summary": {}, "shares": [], "recipients": [], "followups": []}),
        "share_journey": dict(share_journey or {}),
        "structured_feedback": list(structured_feedback or []),
        "attached_summaries": list(attached_summaries or []),
        "optimization": list(optimization or []),
        "feedback_summary": dict(feedback_summary or {}),
        "change_log": list(change_log or []),
    }


def _property_decision_summary(
    service,
    *,
    principal_id: str,
    property_ref: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    property_token = str(property_ref or "").strip()
    if not property_token:
        return {}, []
    feedback_summary = service.feedback_summary(principal_id=principal_id, property_ref=property_token)
    household_review = dict(feedback_summary.get("household_review") or {})
    clusters = list(feedback_summary.get("clusters") or [])
    risk_signals = list(feedback_summary.get("risk_signal_candidates") or [])
    top_blockers = [
        {
            "theme": str(item.get("theme") or "general"),
            "severity": str(item.get("severity") or "medium"),
            "summary": str(item.get("summary") or "").strip() or str(item.get("theme") or "General concern").strip(),
        }
        for item in clusters[:3]
        if isinstance(item, dict)
    ]
    next_best_question = str(household_review.get("next_best_question") or "").strip()
    if not next_best_question:
        next_best_question = next(
            (
                str(item.get("text") or "").strip()
                for item in list(feedback_summary.get("recent_feedback") or [])
                if isinstance(item, dict)
                and str(item.get("category") or "").strip().lower() == "question"
                and str(item.get("text") or "").strip()
            ),
            "",
        )
    summary = {
        **feedback_summary,
        "top_blockers": top_blockers,
        "next_best_question": next_best_question,
        "risk_signals_visible": [
            {
                "theme": str(item.get("theme") or "general"),
                "privacy_state": str(item.get("privacy_state") or "suppressed"),
                "confidence": str(item.get("confidence") or "low"),
                "summary": str(item.get("summary") or "").strip() or str(item.get("theme") or "General concern").strip(),
            }
            for item in risk_signals[:3]
            if isinstance(item, dict)
        ],
    }
    return summary, service.property_change_log(principal_id=principal_id, property_ref=property_token)[:3]


def _feedback_text(*, custom_fields: dict[str, object], note: str = "") -> str:
    parts = [str(note or "")]
    for key in ("reaction", "question", "intent", "viewer_role"):
        parts.append(str(custom_fields.get(key) or ""))
    return " ".join(" ".join(part.split()) for part in parts if str(part or "").strip()).strip().lower()


def _feedback_preference_hints(*, custom_fields: dict[str, object], action: str, note: str = "") -> list[dict[str, object]]:
    text = _feedback_text(custom_fields=custom_fields, note=note)
    hard = str(action or "").strip() == "convert_to_hard_rule"
    strength = "high" if hard else "medium"
    source_mode = "explicit_correction" if hard else "explicit_feedback"
    hints: list[dict[str, object]] = []

    def add(category: str, key: str, value_json: object, *, merge_mode: str = "replace") -> None:
        hint = {
            "domain": PROPERTY_PREFERENCE_DOMAIN,
            "category": category,
            "key": key,
            "value_json": value_json,
            "strength": strength,
            "confidence": 0.95 if hard else 0.75,
            "source_mode": source_mode,
        }
        if merge_mode != "replace":
            hint["merge_mode"] = merge_mode
        if hint not in hints:
            hints.append(hint)

    if any(marker in text for marker in ("floorplan", "floor plan", "grundriss", "plan")):
        add("constraint" if hard else "soft_preference", "require_floorplan" if hard else "requires_floorplan_for_remote_review", True)
    if any(marker in text for marker in ("360", "tour", "virtual")):
        add("constraint" if hard else "soft_preference", "require_360" if hard else "prefer_360_for_remote_review", True)
    if any(marker in text for marker in ("lift", "elevator", "aufzug")):
        add("constraint" if hard else "soft_preference", "require_lift" if hard else "prefer_lift", True)
    if any(marker in text for marker in ("quiet", "noise", "noisy", "traffic", "street noise", "laerm", "lärm", "ruhig")):
        add("constraint" if hard else "soft_preference", "require_quiet_micro_location" if hard else "prefer_quiet_micro_location", True)
    if any(marker in text for marker in ("balcony", "terrace", "garden", "outdoor", "balkon", "terrasse", "garten")):
        add("soft_preference", "prefer_outdoor_space", True)
    if any(marker in text for marker in ("playground", "spielplatz")):
        add("soft_preference", "prefer_playgrounds_nearby", True)
    if any(marker in text for marker in ("supermarket", "grocery", "supermarkt")):
        add("soft_preference", "prefer_supermarket_nearby", True)
    if any(marker in text for marker in ("pharmacy", "apotheke")):
        add("soft_preference", "prefer_pharmacy_nearby", True)
    if any(marker in text for marker in ("subway", "underground", "metro", "u-bahn", "tube")):
        add("soft_preference", "prefer_subway_nearby", True)
    if any(marker in text for marker in ("gas heating", "gasheizung", "gas heater", "gas boiler")):
        add("aversion", "avoid_heating_types", ["Gasheizung"], merge_mode="append_unique")
    return hints


def _apply_feedback_preferences(
    *,
    container: AppContainer,
    context: RequestContext,
    event_id: str,
    review_event: dict[str, object],
    action: str,
    note: str,
    actor: str,
) -> dict[str, object]:
    payload = dict(review_event.get("payload_json") or {})
    target_payload = dict(payload.get("target_payload") or {})
    custom_fields = dict(target_payload.get("custom_fields") or {})
    hints = _feedback_preference_hints(custom_fields=custom_fields, action=action, note=note)
    interpreted: dict[str, object] = {
        "trust": "owner_reviewed",
        "accepted_as": action,
        "feedback_source": PROPERTY_PACKET_FEEDBACK_SOURCE,
        "external_source": FLIPLINK_FEEDBACK_SOURCE,
    }
    if hints:
        interpreted["preference_hints"] = hints
    evidence = container.preference_profiles.record_evidence_event(
        principal_id=context.principal_id,
        person_id="self",
        domain=PROPERTY_PREFERENCE_DOMAIN,
        event_type=PREFERENCE_EVENT_FEEDBACK_ACCEPTED,
        object_type=PREFERENCE_OBJECT_FEEDBACK,
        object_id=event_id,
        source_ref=f"fliplink:event:{event_id}",
        raw_signal_json={
            "event_id": event_id,
            "action": action,
            "note": note,
            "property_ref": str(target_payload.get("property_ref") or ""),
            "packet_kind": str(target_payload.get("packet_kind") or ""),
            "privacy_mode": str(target_payload.get("privacy_mode") or ""),
            "custom_fields": custom_fields,
        },
        interpreted_signal_json=interpreted,
        signal_strength=0.7 if action == "accept_as_preference_signal" else 0.9,
        reversible=True,
    )
    application: dict[str, object] = {
        "evidence_event_id": str(dict(evidence.get("event") or {}).get("event_id") or ""),
        "applied_nodes": list(evidence.get("applied_nodes") or []),
    }
    if action == "convert_to_hard_rule":
        if not hints:
            raise ValueError("fliplink_feedback_no_supported_hard_rule_candidate")
        primary = hints[0]
        correction = container.preference_profiles.apply_correction(
            principal_id=context.principal_id,
            person_id="self",
            domain=str(primary.get("domain") or PROPERTY_PREFERENCE_DOMAIN),
            category=str(primary.get("category") or "soft_preference"),
            key=str(primary.get("key") or ""),
            value_json=primary.get("value_json"),
            strength="high",
            reason=str(note or f"Converted FlipLink feedback {event_id} into an owner-confirmed property rule.").strip(),
            corrected_by=actor,
        )
        application["hard_rule_node"] = dict(correction.get("node") or {})
        application["correction"] = dict(correction.get("correction") or {})
    return application


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _packet_pdf_secret() -> str:
    return resolve_signing_secret(get_settings(), purpose="property-packet-pdf")


def _sign_public_packet_pdf_token(*, publication_id: str, source_pdf_sha256: str, expires_at: datetime | None = None) -> str:
    normalized_publication_id = str(publication_id or "").strip()
    normalized_sha = str(source_pdf_sha256 or "").strip().lower()
    if not normalized_publication_id or not normalized_sha:
        return ""
    expiry = expires_at or (datetime.now(timezone.utc) + timedelta(days=30))
    payload = {
        "kind": "property_packet_pdf",
        "publication_id": normalized_publication_id,
        "source_pdf_sha256": normalized_sha,
        "expires_at": expiry.astimezone(timezone.utc).isoformat(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(_packet_pdf_secret().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_public_packet_pdf_token(token: str) -> dict[str, object] | None:
    normalized = str(token or "").strip()
    if not normalized or "." not in normalized:
        return None
    payload_b64, signature = normalized.rsplit(".", 1)
    expected = hmac.new(_packet_pdf_secret().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(f"{payload_b64}{padding}".encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or str(payload.get("kind") or "").strip() != "property_packet_pdf":
        return None
    expires_raw = str(payload.get("expires_at") or "").strip()
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
    return payload


def _public_packet_pdf_path(*, publication_id: str, source_pdf_sha256: str) -> str:
    token = _sign_public_packet_pdf_token(
        publication_id=publication_id,
        source_pdf_sha256=source_pdf_sha256,
    )
    if not token:
        return ""
    return f"/v1/integrations/fliplink/documents/property-packets/{token}"


@authenticated_router.get("/app/properties/packets", response_class=HTMLResponse)
def property_packets_dashboard(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    service = build_fliplink_packet_service(container)
    raw_rows = service.list_publications(principal_id=context.principal_id, limit=limit)
    analytics = service.analytics_by_publication(
        principal_id=context.principal_id,
        publication_ids=[str(row.get("publication_id") or "") for row in raw_rows],
    )
    rows = []
    for row in raw_rows:
        publication_id = str(row.get("publication_id") or "")
        property_ref = str(row.get("property_ref") or "")
        feedback_summary, change_log = _property_decision_summary(
            service,
            principal_id=context.principal_id,
            property_ref=property_ref,
        )
        rows.append(
            _publication_out(
                row,
                analytics=analytics.get(publication_id, {}),
                engagement=service.engagement_snapshot(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                share_journey=service.share_journey(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                structured_feedback=service.list_structured_feedback(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                )[:6],
                attached_summaries=service.attached_summaries(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                optimization=service.optimization_recommendations(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                feedback_summary=feedback_summary,
                change_log=change_log,
            )
        )
    inbox = service.feedback_inbox(principal_id=context.principal_id, limit=100)
    capacity = service.capacity_status(principal_id=context.principal_id)
    published_total = sum(1 for row in rows if str(row.get("status") or "").strip().lower() == "published")
    share_total = sum(1 for row in rows if list(dict(row.get("engagement") or {}).get("shares") or []))
    optimization_open_total = sum(
        1
        for row in rows
        for item in list(row.get("optimization") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() not in {"acknowledged", "resolved", "done"}
    )
    followup_open_total = sum(
        1
        for row in rows
        for item in list(dict(row.get("engagement") or {}).get("followups") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() not in {"completed", "resolved", "done", "dismissed"}
    )
    feedback_pending_total = sum(
        1
        for item in list(inbox.get("items") or [])
        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() not in {"reviewed", "dismissed", "blocked"}
    )
    webhook_url = f"{str(request.base_url).rstrip('/')}/v1/integrations/fliplink/webhook"
    return templates.TemplateResponse(
        request,
        "app/property_packets.html",
        {
            "brand": request_brand(request),
            "workspace_label": "PropertyQuarry account",
            "current_nav": "packets",
            "publications": rows,
            "fliplink_capacity": capacity,
            "feedback_items": list(inbox.get("items") or []),
            "feedback_total": int(inbox.get("total") or 0),
            "dashboard_summary": {
                "published_total": published_total,
                "share_total": share_total,
                "optimization_open_total": optimization_open_total,
                "followup_open_total": followup_open_total,
                "feedback_pending_total": feedback_pending_total,
            },
            "fliplink_webhook_url": webhook_url,
            "lead_capture_schema": {
                "property_ref": "<property_ref>",
                "packet_kind": "<packet_kind>",
                "privacy_mode": "<privacy_mode>",
                "viewer_role": "family",
                "reaction": "maybe",
                "question": "",
                "intent": "review",
            },
        },
    )


@authenticated_router.get("/app/api/properties/packets")
def list_property_packets(
    limit: int = Query(default=50, ge=1, le=150),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    raw_rows = service.list_publications(principal_id=context.principal_id, limit=limit)
    analytics = service.analytics_by_publication(
        principal_id=context.principal_id,
        publication_ids=[str(row.get("publication_id") or "") for row in raw_rows],
    )
    rows = []
    for row in raw_rows:
        publication_id = str(row.get("publication_id") or "")
        property_ref = str(row.get("property_ref") or "")
        feedback_summary, change_log = _property_decision_summary(
            service,
            principal_id=context.principal_id,
            property_ref=property_ref,
        )
        rows.append(
            _publication_out(
                row,
                analytics=analytics.get(publication_id, {}),
                engagement=service.engagement_snapshot(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                share_journey=service.share_journey(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                structured_feedback=service.list_structured_feedback(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                )[:6],
                attached_summaries=service.attached_summaries(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                optimization=service.optimization_recommendations(
                    principal_id=context.principal_id,
                    publication_id=publication_id,
                ),
                feedback_summary=feedback_summary,
                change_log=change_log,
            )
        )
    return {"items": rows, "total": len(rows), "capacity": service.capacity_status(principal_id=context.principal_id)}


@authenticated_router.get("/app/api/properties/packets/feedback-inbox")
def property_packet_feedback_inbox(
    limit: int = Query(default=100, ge=1, le=300),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    return build_fliplink_packet_service(container).feedback_inbox(principal_id=context.principal_id, limit=limit)


@authenticated_router.post("/app/api/properties/packets/feedback/{event_id}/review")
def review_property_packet_feedback(
    event_id: str,
    body: FlipLinkFeedbackReviewIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        event = service.review_feedback(
            principal_id=context.principal_id,
            event_id=event_id,
            action=body.action,
            note=body.note,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    preference_application: dict[str, object] = {}
    if body.action in {"accept_as_preference_signal", "convert_to_hard_rule"}:
        try:
            preference_application = _apply_feedback_preferences(
                container=container,
                context=context,
                event_id=event_id,
                review_event=event,
                action=body.action,
                note=body.note,
                actor=_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "reviewed",
        "event": dict(event),
        "preference_application": preference_application,
        "viewing_question_event": dict(event.get("viewing_question_event") or {}),
        "block_event": dict(event.get("block_event") or {}),
    }


@authenticated_router.get("/app/api/properties/packets/{publication_id}/pdf")
def download_property_packet_pdf(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FileResponse:
    service = build_fliplink_packet_service(container)
    row = service.get_publication(publication_id=publication_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="property_packet_publication_not_found")
    artifact_root = Path(str(container.settings.storage.artifacts_dir)).resolve()
    pdf_path = Path(str(row.get("source_pdf_artifact_ref") or "")).resolve()
    if (pdf_path != artifact_root and artifact_root not in pdf_path.parents) or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    expected_sha = str(row.get("source_pdf_sha256") or "").strip().lower()
    if expected_sha and _sha256_file(pdf_path) != expected_sha:
        raise HTTPException(status_code=409, detail="property_packet_pdf_hash_mismatch")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"{publication_id}.pdf",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@authenticated_router.get("/app/api/properties/score-methodology/pdf")
def download_property_score_methodology_pdf(
    language: str = Query(default="", max_length=16),
    country: str = Query(default="", max_length=8),
    request: Request = None,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> FileResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {}) if isinstance(status.get("workspace"), dict) else {}
    country_code = str(country or workspace.get("country_code") or workspace.get("region") or "AT").strip() or "AT"
    accept_language = str(request.headers.get("accept-language") or "").strip() if request is not None else ""
    language_code = resolve_property_score_methodology_language(
        language_code=language or "",
        country_code=country_code,
        accept_language=accept_language,
        fallback_language_code=workspace.get("language") or "",
    )
    return _score_methodology_pdf_response(
        container=container,
        country_code=country_code,
        language_code=language_code,
        accept_language=accept_language,
    )


@public_router.get("/documents/score-methodology.pdf")
def public_property_score_methodology_pdf(
    language: str = Query(default="", max_length=16),
    country: str = Query(default="", max_length=8),
    request: Request = None,
    container: AppContainer = Depends(get_container),
) -> FileResponse:
    country_code = str(country or "AT").strip() or "AT"
    accept_language = str(request.headers.get("accept-language") or "").strip() if request is not None else ""
    language_code = resolve_property_score_methodology_language(
        language_code=language or "",
        country_code=country_code,
        accept_language=accept_language,
    )
    return _score_methodology_pdf_response(
        container=container,
        country_code=country_code,
        language_code=language_code,
        accept_language=accept_language,
    )


@public_router.get("/documents/property-packets/{token}")
def download_public_property_packet_pdf(
    token: str,
    container: AppContainer = Depends(get_container),
) -> FileResponse:
    payload = _verify_public_packet_pdf_token(token)
    if payload is None:
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    publication_id = str(payload.get("publication_id") or "").strip()
    expected_sha = str(payload.get("source_pdf_sha256") or "").strip().lower()
    if not publication_id or not expected_sha:
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    service = build_fliplink_packet_service(container)
    row = service.get_publication(publication_id=publication_id, principal_id=None)
    if row is None:
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    if str(row.get("status") or "").strip().lower() in _REVOKED_PACKET_STATUSES:
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    actual_sha = str(row.get("source_pdf_sha256") or "").strip().lower()
    if not actual_sha or not hmac.compare_digest(actual_sha, expected_sha):
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    artifact_root = Path(str(container.settings.storage.artifacts_dir)).resolve()
    pdf_path = Path(str(row.get("source_pdf_artifact_ref") or "")).resolve()
    if (pdf_path != artifact_root and artifact_root not in pdf_path.parents) or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="property_packet_pdf_not_found")
    if _sha256_file(pdf_path) != expected_sha:
        raise HTTPException(status_code=409, detail="property_packet_pdf_hash_mismatch")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"{publication_id}.pdf",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@authenticated_router.get("/app/api/properties/packets/{publication_id}")
def get_property_packet_publication(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    row = service.get_publication(publication_id=publication_id, principal_id=context.principal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="property_packet_publication_not_found")
    events = service.list_events(publication_id=publication_id, principal_id=context.principal_id, limit=100)
    feedback_summary, change_log = _property_decision_summary(
        service,
        principal_id=context.principal_id,
        property_ref=str(row.get("property_ref") or ""),
    )
    return {
        "publication": _publication_out(
            row,
            analytics=service.latest_analytics_snapshot(principal_id=context.principal_id, publication_id=publication_id),
            engagement=service.engagement_snapshot(principal_id=context.principal_id, publication_id=publication_id),
            share_journey=service.share_journey(principal_id=context.principal_id, publication_id=publication_id),
            structured_feedback=service.list_structured_feedback(
                principal_id=context.principal_id,
                publication_id=publication_id,
            )[:10],
            attached_summaries=service.attached_summaries(principal_id=context.principal_id, publication_id=publication_id),
            optimization=service.optimization_recommendations(principal_id=context.principal_id, publication_id=publication_id),
            feedback_summary=feedback_summary,
            change_log=change_log,
        ),
        "events": [dict(event) for event in events],
    }


@authenticated_router.post("/app/api/properties/packets/{publication_id}/shares")
def create_property_packet_share(
    publication_id: str,
    body: PacketShareCreateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        share = service.create_share(
            principal_id=context.principal_id,
            publication_id=publication_id,
            audience_type=body.audience_type,
            channel=body.channel,
            variant_key=body.variant_key,
            cover_note=body.cover_note,
            recipients=[item.model_dump() for item in body.recipients],
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"share": share}


@authenticated_router.get("/app/api/properties/packets/{publication_id}/engagement")
def get_property_packet_engagement(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    return service.engagement_snapshot(principal_id=context.principal_id, publication_id=publication_id)


@authenticated_router.post("/app/api/properties/packets/{publication_id}/engagement-events")
def record_property_packet_engagement_event(
    publication_id: str,
    body: PacketEngagementEventIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        event = service.record_engagement_event(
            principal_id=context.principal_id,
            publication_id=publication_id,
            share_id=body.share_id,
            recipient_id=body.recipient_id,
            event_type=body.event_type,
            event_value=body.event_value,
            metadata_json=body.metadata_json,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"event": dict(event), "engagement": service.engagement_snapshot(principal_id=context.principal_id, publication_id=publication_id)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/manual-link")
def record_manual_fliplink_publication(
    publication_id: str,
    body: ManualFlipLinkPublicationIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.record_manual_link(
            principal_id=context.principal_id,
            publication_id=publication_id,
            fliplink_url=body.fliplink_url,
            fliplink_format=body.fliplink_format,
            embed_code=body.embed_code,
            qr_url=body.qr_url,
            lead_capture_enabled=body.lead_capture_enabled,
            password_required=body.password_required,
            sale_mode_enabled=body.sale_mode_enabled,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/archive")
def archive_property_packet_publication(
    publication_id: str,
    body: FlipLinkArchivePublicationIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.archive_publication(
            principal_id=context.principal_id,
            publication_id=publication_id,
            note=body.note,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/browseract-publish")
def request_browseract_fliplink_publication(
    publication_id: str,
    body: BrowserActFlipLinkPublishIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.request_browseract_publish(
            principal_id=context.principal_id,
            publication_id=publication_id,
            lead_capture_enabled=body.lead_capture_enabled,
            password_required=body.password_required,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/browseract-complete")
def complete_browseract_fliplink_publication(
    publication_id: str,
    body: BrowserActFlipLinkPublishCompleteIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.complete_browseract_publish(
            principal_id=context.principal_id,
            publication_id=publication_id,
            fliplink_url=body.fliplink_url,
            embed_code=body.embed_code,
            qr_url=body.qr_url,
            screenshot_proof_ref=body.screenshot_proof_ref,
            lead_capture_enabled=body.lead_capture_enabled,
            password_required=body.password_required,
            sale_mode_enabled=body.sale_mode_enabled,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/fliplink/analytics-snapshot")
def record_fliplink_analytics_snapshot(
    publication_id: str,
    body: FlipLinkAnalyticsSnapshotIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.record_analytics_snapshot(
            principal_id=context.principal_id,
            publication_id=publication_id,
            views=body.views,
            unique_visitors=body.unique_visitors,
            average_time_seconds=body.average_time_seconds,
            top_pages=body.top_pages,
            referral_sources=body.referral_sources,
            device_breakdown=body.device_breakdown,
            geography_breakdown=body.geography_breakdown,
            source=body.source,
            screenshot_proof_ref=body.screenshot_proof_ref,
            captured_from_url=body.captured_from_url,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@authenticated_router.post("/app/api/properties/packets/{publication_id}/variants")
def create_property_packet_variant(
    publication_id: str,
    body: PacketVariantCreateIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.create_variant(
            principal_id=context.principal_id,
            publication_id=publication_id,
            audience_type=body.audience_type,
            base_variant_key=body.base_variant_key,
            title_override=body.title_override,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"variant": _publication_out(row)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/republish")
def republish_property_packet(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        row = service.republish_publication(
            principal_id=context.principal_id,
            publication_id=publication_id,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"publication": _publication_out(row), "share_journey": service.share_journey(principal_id=context.principal_id, publication_id=publication_id)}


@authenticated_router.get("/app/api/properties/packets/{publication_id}/share-journey")
def get_property_packet_share_journey(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.share_journey(principal_id=context.principal_id, publication_id=publication_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@authenticated_router.post("/app/api/properties/packets/{publication_id}/attach-summary")
def attach_property_summary_to_packet(
    publication_id: str,
    body: PacketAttachSummaryIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    try:
        return service.attach_summary_to_packet(
            principal_id=context.principal_id,
            publication_id=publication_id,
            artifact_id=body.artifact_id,
            actor=_actor(context),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@authenticated_router.get("/app/api/properties/packets/{publication_id}/optimization")
def get_property_packet_optimization(
    publication_id: str,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    return {"items": service.optimization_recommendations(principal_id=context.principal_id, publication_id=publication_id)}


@authenticated_router.post("/app/api/properties/packets/{publication_id}/optimization/ack")
def acknowledge_property_packet_optimization(
    publication_id: str,
    body: PacketOptimizationAckIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    event = service.acknowledge_optimization(
        principal_id=context.principal_id,
        publication_id=publication_id,
        recommendation_id=body.recommendation_id,
        actor=_actor(context),
    )
    return {"event": dict(event), "items": service.optimization_recommendations(principal_id=context.principal_id, publication_id=publication_id)}


@authenticated_router.post("/app/api/properties/{property_ref:path}/packets/render")
def render_property_packet(
    property_ref: str,
    body: PropertyPacketRenderIn,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> dict[str, object]:
    service = build_fliplink_packet_service(container)
    product_service = build_product_service(container)
    source_payload = dict(body.property_payload or {})
    latest_scene = product_service.latest_property_magic_fit_scene(
        principal_id=context.principal_id,
        property_ref=property_ref,
    )
    if latest_scene and bool(latest_scene.get("share_with_packet_pdf")):
        source_payload["magic_fit_scene"] = dict(latest_scene)
    facts = dict(source_payload.get("property_facts") or {}) if isinstance(source_payload.get("property_facts"), dict) else {}
    country_code = str(
        source_payload.get("country_code")
        or facts.get("country_code")
        or facts.get("market_country_code")
        or ""
    ).strip()
    language_code = str(source_payload.get("language_code") or facts.get("language_code") or "").strip()
    if not isinstance(source_payload.get("score_methodology"), dict):
        source_payload["score_methodology"] = build_property_score_methodology(
            language_code=language_code,
            country_code=country_code,
            candidate=source_payload,
        )
    try:
        row = service.render_packet(
            principal_id=context.principal_id,
            person_id=body.person_id,
            property_ref=property_ref,
            packet_kind=PropertyPacketKind(body.packet_kind),
            privacy_mode=PacketPrivacyMode(body.privacy_mode) if body.privacy_mode else "",
            fliplink_format=FlipLinkFormat(body.fliplink_format) if body.fliplink_format else "",
            search_run_id=body.search_run_id,
            include_exact_address=body.include_exact_address,
            include_floorplan=body.include_floorplan,
            include_photos=body.include_photos,
            source_payload=source_payload,
            actor=_actor(context),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"publication": _publication_out(row), "capacity": service.capacity_status(principal_id=context.principal_id)}


@public_router.post("/webhook")
async def fliplink_webhook(
    request: Request,
    secret: str = Query(default=""),
    container: AppContainer = Depends(get_container),
) -> dict[str, object]:
    content_length = int(request.headers.get("content-length") or 0)
    if content_length > 64_000:
        raise HTTPException(status_code=413, detail="fliplink_webhook_payload_too_large")
    service = build_fliplink_packet_service(container)
    try:
        secret_mode = service.verify_webhook_secret(
            provided_header=str(request.headers.get("x-propertyquarry-webhook-secret") or ""),
            provided_query=secret,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        raw_body = await request.body()
        if len(raw_body) > 64_000:
            raise HTTPException(status_code=413, detail="fliplink_webhook_payload_too_large")
        payload = json.loads(raw_body)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail="invalid_fliplink_webhook_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="fliplink_webhook_object_required")
    return service.ingest_lead_webhook(payload=payload, secret_mode=secret_mode)
