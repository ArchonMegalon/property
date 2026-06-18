from __future__ import annotations

from dataclasses import dataclass, field


CONTENT_JOB_STATES = (
    "SOURCE_PACKET_DRAFT",
    "SOURCE_PACKET_VALIDATED",
    "SOURCE_PACKET_APPROVED",
    "PROVIDER_JOB_CREATED",
    "PROVIDER_GENERATING",
    "DRAFT_RECEIVED",
    "PROPERTY_VALIDATION",
    "HUMAN_REVIEW_REQUIRED",
    "APPROVED_SCRIPT",
    "PRODUCTION_REQUESTED",
    "RENDER_CANDIDATE_READY",
    "FINAL_PUBLICATION_REVIEW",
    "PUBLISHED",
)

CONTENT_JOB_FAILURE_STATES = (
    "SOURCE_REJECTED",
    "SOURCE_STALE",
    "LISTING_REMOVED",
    "PRIVACY_BLOCKED",
    "RIGHTS_BLOCKED",
    "FAIR_HOUSING_BLOCKED",
    "MARKET_CLAIM_BLOCKED",
    "INVESTMENT_CLAIM_BLOCKED",
    "PROVIDER_FAILED",
    "EXPORT_FAILED",
    "EDITORIAL_REJECTED",
    "PUBLICATION_BLOCKED",
)


@dataclass(frozen=True)
class PropertyContentJob:
    packet_id: str
    content_mode: str
    channel_key: str
    status: str = "SOURCE_PACKET_DRAFT"
    provider: str = "subscribr"
    provider_channel_id: str = ""
    provider_idea_id: str = ""
    provider_script_id: str = ""
    source_packet_sha256: str = ""
    script_sha256: str = ""
    validation_status: str = "pending"
    human_review_status: str = "pending"
    production_allowed: bool = False
    publication_allowed: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "packet_id": self.packet_id,
            "content_mode": self.content_mode,
            "channel_key": self.channel_key,
            "status": self.status,
            "provider": self.provider,
            "provider_channel_id": self.provider_channel_id,
            "provider_idea_id": self.provider_idea_id,
            "provider_script_id": self.provider_script_id,
            "source_packet_sha256": self.source_packet_sha256,
            "script_sha256": self.script_sha256,
            "validation_status": self.validation_status,
            "human_review_status": self.human_review_status,
            "production_allowed": self.production_allowed,
            "publication_allowed": self.publication_allowed,
            "metadata": dict(self.metadata),
        }

