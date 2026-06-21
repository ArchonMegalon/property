from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.services.property_content_packet_builder import (
    build_product_tutorial_source_packet,
    build_synthetic_dossier_source_packet,
)
from app.services.property_content_studio import PropertyContentStudio
from app.services.property_content_validation import validate_property_content_source_packet


authenticated_router = APIRouter(tags=["property-content-studio"])
public_router = APIRouter(prefix="/internal/providers/subscribr", tags=["subscribr"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
_SUBSCRIBR_SCRIPT_COMPLETION_EVENTS = frozenset({"script.generated", "export.completed"})


class ContentPacketValidateIn(BaseModel):
    packet: dict[str, object] = Field(default_factory=dict)


class TutorialPacketIn(BaseModel):
    title: str = Field(default="How to Read a PropertyQuarry Dossier", min_length=3, max_length=240)
    language: str = Field(default="en", max_length=40)
    jurisdiction: str = Field(default="GLOBAL", max_length=40)


class ScriptReceiptIn(BaseModel):
    packet: dict[str, object] = Field(default_factory=dict)
    markdown: str = Field(default="", max_length=80_000)
    provider_channel_id: str = Field(default="", max_length=120)
    provider_idea_id: str = Field(default="", max_length=120)
    provider_script_id: str = Field(default="", max_length=120)


def _studio() -> PropertyContentStudio:
    return PropertyContentStudio()


def _signature_header(request: Request) -> str:
    return str(
        request.headers.get("x-subscribr-signature")
        or request.headers.get("x-subcribr-signature")
        or request.headers.get("subscribr-signature")
        or ""
    ).strip()


def _event_id(payload: dict[str, object]) -> str:
    return str(
        payload.get("id")
        or payload.get("event_id")
        or payload.get("eventId")
        or payload.get("webhook_event_id")
        or payload.get("webhookEventId")
        or ""
    ).strip()


def _event_type(payload: dict[str, object]) -> str:
    return str(payload.get("type") or payload.get("event") or payload.get("event_type") or "").strip()


def _verify_subscribr_signature(*, raw_body: bytes, signature: str, timestamp: str = "") -> None:
    secret = str(os.getenv("SUBSCRIBR_PROPERTY_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="subscribr_webhook_secret_not_configured")
    if timestamp:
        try:
            delta = abs(time.time() - float(timestamp))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="subscribr_webhook_timestamp_invalid") from exc
        if delta > 600:
            raise HTTPException(status_code=401, detail="subscribr_webhook_timestamp_stale")
    expected_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    normalized = signature
    if normalized.startswith("sha256="):
        normalized = normalized.split("=", 1)[1]
    if not normalized or not hmac.compare_digest(normalized, expected_hex):
        raise HTTPException(status_code=401, detail="subscribr_webhook_signature_invalid")


@authenticated_router.get("/admin/property/content-studio", response_class=HTMLResponse)
def property_content_studio_home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/property_content_studio.html",
        {"request": request, "studio": _studio().studio_snapshot()},
    )


@authenticated_router.get("/admin/property/content-studio/jobs/{packet_id}", response_class=HTMLResponse)
def property_content_studio_job(request: Request, packet_id: str) -> HTMLResponse:
    job = _studio().ledger.get_job(packet_id)
    if not job:
        raise HTTPException(status_code=404, detail="property_content_job_not_found")
    return templates.TemplateResponse(request, "admin/property_content_job.html", {"request": request, "job": job})


@authenticated_router.post("/app/api/property/content/source-packets/validate")
def validate_property_content_packet(body: ContentPacketValidateIn) -> dict[str, object]:
    return validate_property_content_source_packet(body.packet)


@authenticated_router.post("/app/api/property/content/source-packets/product-tutorial")
def create_product_tutorial_packet(body: TutorialPacketIn) -> dict[str, object]:
    packet = build_product_tutorial_source_packet(title=body.title, language=body.language, jurisdiction=body.jurisdiction)
    job = _studio().prepare_source_packet(packet)
    return {"packet": packet, "job": job, "validation": validate_property_content_source_packet(packet)}


@authenticated_router.post("/app/api/property/content/source-packets/synthetic-dossier")
def create_synthetic_dossier_packet() -> dict[str, object]:
    packet = build_synthetic_dossier_source_packet()
    job = _studio().prepare_source_packet(packet)
    return {"packet": packet, "job": job, "validation": validate_property_content_source_packet(packet)}


@authenticated_router.post("/app/api/property/content/subscribr/request-script")
def request_subscribr_script(body: ContentPacketValidateIn) -> dict[str, object]:
    job = _studio().request_subscribr_script(body.packet)
    return {"job": job}


@authenticated_router.post("/app/api/property/content/subscribr/script-receipt")
def materialize_subscribr_script_receipt(body: ScriptReceiptIn) -> dict[str, object]:
    return _studio().materialize_script_receipt(
        packet=body.packet,
        markdown=body.markdown,
        provider_channel_id=body.provider_channel_id,
        provider_idea_id=body.provider_idea_id,
        provider_script_id=body.provider_script_id,
    )


@public_router.post("/webhook")
async def subscribr_webhook(request: Request) -> dict[str, object]:
    raw_body = await request.body()
    if len(raw_body) > 256_000:
        raise HTTPException(status_code=413, detail="subscribr_webhook_payload_too_large")
    _verify_subscribr_signature(
        raw_body=raw_body,
        signature=_signature_header(request),
        timestamp=str(request.headers.get("x-subscribr-timestamp") or ""),
    )
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="subscribr_webhook_invalid_json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="subscribr_webhook_object_required")
    event_id = _event_id(payload)
    if not event_id:
        raise HTTPException(status_code=422, detail="subscribr_webhook_event_id_required")
    event_type = _event_type(payload)
    studio = _studio()
    if studio.ledger.webhook_seen(event_id):
        return {"status": "duplicate_ignored", "event_id": event_id}
    studio.ledger.record_webhook_event(
        event_id=event_id,
        payload=payload,
        status="received",
        extra={
            "raw_body_sha256": hashlib.sha256(raw_body).hexdigest(),
            "signature_status": "verified",
            "timestamp": str(request.headers.get("x-subscribr-timestamp") or "").strip(),
        },
    )
    if event_type and event_type not in _SUBSCRIBR_SCRIPT_COMPLETION_EVENTS:
        return {
            "status": "received",
            "event_id": event_id,
            "event_type": event_type,
            "next": "wait_for_script_generated_or_export_completed",
            "publication_allowed": False,
        }
    packet_id = str(payload.get("packet_id") or payload.get("packetId") or "").strip()
    inline_packet = payload.get("packet") if isinstance(payload.get("packet"), dict) else {}
    if not packet_id and inline_packet:
        packet_id = str(inline_packet.get("packet_id") or "").strip()
    row = studio.ledger.get_job(packet_id) if packet_id else None
    packet = dict(row.get("source_packet_json") or {}) if isinstance(row, dict) else {}
    markdown = str(payload.get("markdown") or payload.get("script_markdown") or payload.get("export_markdown") or "")
    if packet and markdown:
        receipt = studio.ingest_completed_script(packet=packet, event_payload=payload, markdown=markdown)
        return {"status": "review_required", "event_id": event_id, "receipt": receipt}
    if markdown and not packet:
        return {
            "status": "received",
            "event_id": event_id,
            "next": "await_local_source_packet",
            "publication_allowed": False,
        }
    return {
        "status": "received",
        "event_id": event_id,
        "next": "export_script_and_validate",
        "publication_allowed": False,
    }
