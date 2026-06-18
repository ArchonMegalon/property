from __future__ import annotations

import hashlib
import json
import os

from app.domain.property.content_source_packet import canonical_json, now_utc_iso, sha256_json, source_packet_sha256
from app.services.property_content_job_ledger import PropertyContentJobLedger
from app.services.property_content_validation import (
    script_receipt_validation,
    validate_property_content_script,
    validate_property_content_source_packet,
)
from app.services.subscribr_client import SubscribrClient, redacted_subscribr_error, subscribr_enabled


def script_markdown_sha256(markdown: str) -> str:
    return hashlib.sha256(str(markdown or "").encode("utf-8")).hexdigest()


class PropertyContentStudio:
    def __init__(
        self,
        *,
        ledger: PropertyContentJobLedger | None = None,
        client: SubscribrClient | None = None,
    ) -> None:
        self._ledger = ledger or PropertyContentJobLedger()
        self._client = client or SubscribrClient()

    @property
    def ledger(self) -> PropertyContentJobLedger:
        return self._ledger

    def validate_source_packet(self, packet: dict[str, object]) -> dict[str, object]:
        return validate_property_content_source_packet(packet)

    def prepare_source_packet(self, packet: dict[str, object]) -> dict[str, object]:
        report = self.validate_source_packet(packet)
        status = "SOURCE_PACKET_APPROVED" if report["status"] == "pass" else "SOURCE_REJECTED"
        return self._ledger.upsert_job(
            packet,
            status=status,
            extra={
                "validation_status": str(report["status"]),
                "validation_report": report,
                "provider_status": "not_requested",
            },
        )

    def request_subscribr_script(self, packet: dict[str, object], *, channel_id: str | int = "") -> dict[str, object]:
        existing = self._ledger.get_job(str(packet.get("packet_id") or ""))
        if existing and str(existing.get("provider_script_id") or ""):
            return {**existing, "idempotent": True}
        report = self.validate_source_packet(packet)
        if report["status"] != "pass":
            return self._ledger.upsert_job(
                packet,
                status="SOURCE_REJECTED",
                extra={"validation_status": "fail", "validation_report": report, "provider_status": "blocked"},
            )
        if not subscribr_enabled():
            return self._ledger.upsert_job(
                packet,
                status="SOURCE_PACKET_APPROVED",
                extra={
                    "validation_status": "pass",
                    "validation_report": report,
                    "provider_status": "disabled",
                    "provider_disabled_reason": "PROPERTYQUARRY_SUBSCRIBR_ENABLED and PROPERTYQUARRY_SUBSCRIBR_API_ENABLED are required",
                },
            )
        if not self._client.configured:
            return self._ledger.upsert_job(
                packet,
                status="PROVIDER_FAILED",
                extra={
                    "validation_status": "pass",
                    "validation_report": report,
                    "provider_status": "blocked",
                    "provider_error": {"detail": "subscribr_token_not_configured"},
                },
            )
        try:
            idea = self._client.create_idea(
                channel_id=channel_id or str(packet.get("subscribr_channel_key") or ""),
                payload={"title": str(packet.get("title") or ""), "description": canonical_json(packet)[:8000]},
            )
            script = self._client.create_script(
                channel_id=channel_id or str(packet.get("subscribr_channel_key") or ""),
                payload={
                    "title": str(packet.get("title") or ""),
                    "brief": canonical_json(packet),
                    "target_words": packet.get("target_words") or 750,
                },
            )
            script_id = script.get("id") or script.get("script_id") or dict(script.get("script") or {}).get("id")
            idea_id = idea.get("id") or idea.get("idea_id") or dict(idea.get("idea") or {}).get("id")
            if script_id:
                self._client.generate_script(script_id=script_id, payload={"research": False})
            job = self._ledger.upsert_job(
                packet,
                status="PROVIDER_GENERATING",
                extra={"validation_status": "pass", "validation_report": report, "provider_status": "generating"},
            )
            return self._ledger.record_provider_ids(
                packet_id=str(packet.get("packet_id") or ""),
                provider_channel_id=channel_id or str(packet.get("subscribr_channel_key") or ""),
                provider_idea_id=idea_id,
                provider_script_id=script_id,
                status=str(job.get("status") or "PROVIDER_GENERATING"),
            )
        except Exception as exc:
            return self._ledger.upsert_job(
                packet,
                status="PROVIDER_FAILED",
                extra={"validation_status": "pass", "validation_report": report, "provider_error": redacted_subscribr_error(exc)},
            )

    def materialize_script_receipt(
        self,
        *,
        packet: dict[str, object],
        markdown: str,
        provider_channel_id: object = "",
        provider_idea_id: object = "",
        provider_script_id: object = "",
    ) -> dict[str, object]:
        source_report = validate_property_content_source_packet(packet)
        script_report = validate_property_content_script(packet, markdown)
        receipt = {
            "contract_name": "propertyquarry.subscribr_script_draft.v1",
            "status": "review_required" if source_report["status"] == "pass" and script_report["status"] == "pass" else "validation_failed",
            "provider": "subscribr",
            "account_tier": "AppSumo Tier 7 / Scale 3",
            "packet_id": str(packet.get("packet_id") or ""),
            "content_mode": str(packet.get("content_mode") or ""),
            "jurisdiction": str(packet.get("jurisdiction") or ""),
            "channel_key": str(packet.get("subscribr_channel_key") or ""),
            "provider_channel_id": provider_channel_id,
            "provider_idea_id": provider_idea_id,
            "provider_script_id": provider_script_id,
            "source_packet_sha256": str(packet.get("source_packet_sha256") or source_packet_sha256(packet)),
            "listing_snapshot_sha256": str(dict(packet.get("property_snapshot") or {}).get("snapshot_sha256") or ""),
            "research_packet_sha256": sha256_json(packet.get("sources") or []),
            "run_id": str(dict(packet.get("property_snapshot") or {}).get("run_id") or ""),
            "candidate_ref": str(dict(packet.get("property_snapshot") or {}).get("candidate_ref") or ""),
            "export_format": "markdown",
            "script_sha256": script_markdown_sha256(markdown),
            "validation": script_receipt_validation(packet, markdown),
            "validation_report": {"source": source_report, "script": script_report},
            "human_review": {"status": "pending", "reviewer": "", "reviewed_at": ""},
            "production_allowed": False,
            "publication_allowed": False,
            "created_at": now_utc_iso(),
        }
        path = self._ledger.write_receipt(packet_id=str(packet.get("packet_id") or ""), receipt=receipt)
        self._ledger.upsert_job(
            packet,
            status="HUMAN_REVIEW_REQUIRED" if receipt["status"] == "review_required" else "PROPERTY_VALIDATION",
            extra={
                "script_sha256": receipt["script_sha256"],
                "receipt_path": str(path),
                "validation_status": receipt["status"],
                "validation_report": receipt["validation_report"],
                "provider_channel_id": provider_channel_id,
                "provider_idea_id": provider_idea_id,
                "provider_script_id": provider_script_id,
            },
        )
        return {**receipt, "receipt_path": str(path)}

    def studio_snapshot(self) -> dict[str, object]:
        data = self._ledger._load()
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        rows = sorted((dict(row) for row in jobs.values() if isinstance(row, dict)), key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return {
            "enabled": subscribr_enabled(),
            "operator_ui_enabled": str(os.getenv("PROPERTYQUARRY_SUBSCRIBR_OPERATOR_UI_ENABLED") or "").strip().lower()
            in {"1", "true", "yes", "on"},
            "jobs": rows[:100],
            "ledger_path": str(self._ledger.path),
            "job_count": len(rows),
        }

    def ingest_completed_script(self, *, packet: dict[str, object], event_payload: dict[str, object], markdown: str) -> dict[str, object]:
        return self.materialize_script_receipt(
            packet=packet,
            markdown=markdown,
            provider_channel_id=event_payload.get("channel_id") or event_payload.get("channelId") or "",
            provider_idea_id=event_payload.get("idea_id") or event_payload.get("ideaId") or "",
            provider_script_id=event_payload.get("script_id") or event_payload.get("scriptId") or "",
        )

