from __future__ import annotations

from dataclasses import dataclass
import os


def _env_enabled(*names: str) -> bool:
    return any(str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"} for name in names)


@dataclass(frozen=True)
class PropertyIntegrationLane:
    provider_key: str
    title: str
    priority: int
    product_lane: str
    rollout_state: str
    allowed_use: str
    forbidden_use: str
    source_of_truth: str
    allowed_inputs: tuple[str, ...]
    forbidden_inputs: tuple[str, ...]
    allowed_data_classes: tuple[str, ...]
    exact_address_allowed: bool
    private_documents_allowed: bool
    enabled_env: tuple[str, ...]
    kill_switch_env: tuple[str, ...]
    verification_required: tuple[str, ...]
    fail_closed_rule: str

    @property
    def enabled(self) -> bool:
        return _env_enabled(*self.enabled_env) and not _env_enabled(*self.kill_switch_env)

    def as_row(self) -> dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "title": self.title,
            "priority": self.priority,
            "product_lane": self.product_lane,
            "rollout_state": self.rollout_state,
            "enabled": self.enabled,
            "allowed_data_classes": list(self.allowed_data_classes),
            "exact_address_allowed": self.exact_address_allowed,
            "private_documents_allowed": self.private_documents_allowed,
            "fail_closed_rule": self.fail_closed_rule,
        }


_COMMON_FORBIDDEN_INPUTS = (
    "raw_provider_payload",
    "portal_credentials",
    "payment_identifiers",
    "private_preference_profile",
    "private_feedback_history",
    "seller_or_agent_contact_data",
    "unredacted_household_or_medical_notes",
)


def property_integration_governance_lanes() -> tuple[PropertyIntegrationLane, ...]:
    return (
        PropertyIntegrationLane(
            provider_key="metasurvey",
            title="MetaSurvey",
            priority=1,
            product_lane="post_viewing_and_rejection_intelligence",
            rollout_state="integrate_next_disabled",
            allowed_use="Extended post-viewing surveys and rejection-reason research after PropertyQuarry records the canonical decision.",
            forbidden_use="Cannot own Yes/Maybe/No decisions, rewrite property facts, or publish cross-customer free text.",
            source_of_truth="PropertyQuarry owns decisions, normalized feedback observations, ranking, and aggregation thresholds.",
            allowed_inputs=("property_ref", "decision_state", "normalized_rejection_choices", "redacted_survey_context"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS,
            allowed_data_classes=("feedback_observation", "survey_receipt", "normalized_rejection_reason"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_METASURVEY_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_METASURVEY_DISABLED",),
            verification_required=("survey_roundtrip", "webhook_or_export_receipt", "privacy_projection", "cohort_threshold_policy"),
            fail_closed_rule="Survey output may create feedback observations only; it must never mutate listing truth automatically.",
        ),
        PropertyIntegrationLane(
            provider_key="lunacal",
            title="Lunacal",
            priority=1,
            product_lane="consultation_and_viewing_scheduling",
            rollout_state="integrate_next_disabled",
            allowed_use="Consultation, viewing-request, advisor-review, and demo scheduling with PropertyQuarry outcome events.",
            forbidden_use="Cannot expose private exact addresses in public booking titles or own viewing outcome truth.",
            source_of_truth="PropertyQuarry owns appointment outcome events, permission checks, and property references.",
            allowed_inputs=("property_reference_label", "appointment_type", "time_window", "redacted_attendee_context"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS,
            allowed_data_classes=("appointment_request", "appointment_receipt", "viewing_outcome_event"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_LUNACAL_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_LUNACAL_DISABLED",),
            verification_required=("booking_roundtrip", "calendar_receipt", "address_redaction", "reschedule_cancel_receipts"),
            fail_closed_rule="Bookings must be recorded as pending outcome events until PropertyQuarry verifies the callback or receipt.",
        ),
        PropertyIntegrationLane(
            provider_key="apixdrive",
            title="ApiX-Drive",
            priority=2,
            product_lane="agent_crm_outbound_connector",
            rollout_state="agent_beta_disabled",
            allowed_use="Outbound Agent-plan events to CRM, spreadsheet, notification, and task destinations selected by the customer.",
            forbidden_use="No inbound automation may mutate property truth, decisions, entitlements, schedules, or provider credentials.",
            source_of_truth="PropertyQuarry owns the event outbox, delivery receipts, customer identity, and all property state.",
            allowed_inputs=("outbox_event", "redacted_property_summary", "destination_configuration_ref"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS,
            allowed_data_classes=("outbound_event", "delivery_receipt", "destination_mapping"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_APIXDRIVE_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_APIXDRIVE_DISABLED",),
            verification_required=("outbox_idempotency", "delivery_receipt", "destination_opt_in", "inbound_mutation_block"),
            fail_closed_rule="Connector failures must stay in the outbox and never mark the PropertyQuarry event complete without a receipt.",
        ),
        PropertyIntegrationLane(
            provider_key="invoiless",
            title="Invoiless",
            priority=2,
            product_lane="invoice_and_vat_document_lifecycle",
            rollout_state="commercial_ops_disabled",
            allowed_use="Invoice, credit-note, VAT, receipt, and billing-document generation after internal payment verification.",
            forbidden_use="Cannot own payment verification, entitlement truth, cancellation, refund decisions, or plan state.",
            source_of_truth="PropertyQuarry owns payments, entitlements, renewal/cancellation state, and refund status.",
            allowed_inputs=("billing_profile", "verified_payment_receipt", "invoice_line_items", "tax_region"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS,
            allowed_data_classes=("invoice_document", "credit_note", "billing_document_receipt"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_INVOILESS_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_INVOILESS_DISABLED",),
            verification_required=("api_or_export_proof", "vat_workflow_proof", "document_download_receipt", "refund_credit_note_receipt"),
            fail_closed_rule="Entitlements activate only from PropertyQuarry payment truth, never from invoice-document creation.",
        ),
        PropertyIntegrationLane(
            provider_key="documentation_ai",
            title="Documentation.AI",
            priority=3,
            product_lane="public_help_center_and_market_docs",
            rollout_state="docs_publishing_disabled",
            allowed_use="Publish reviewed public help-centre and market documentation generated from curated Markdown.",
            forbidden_use="Cannot ingest the whole repository, private packets, run payloads, security docs, credentials, or customer data.",
            source_of_truth="PropertyQuarry owns docs source, review status, freshness, and publication approval.",
            allowed_inputs=("reviewed_public_markdown", "docs_freshness_manifest", "public_help_taxonomy"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS + ("operator_runbooks", "internal_prompts", "security_architecture"),
            allowed_data_classes=("public_documentation", "docs_publication_receipt", "freshness_manifest"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_DOCUMENTATION_AI_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_DOCUMENTATION_AI_DISABLED",),
            verification_required=("workspace_verification", "reviewed_markdown_export", "public_url_receipt", "freshness_gate"),
            fail_closed_rule="Unreviewed or stale docs must remain unpublished and cannot answer customer support flows.",
        ),
        PropertyIntegrationLane(
            provider_key="paperguide",
            title="Paperguide",
            priority=4,
            product_lane="controlled_document_research_pilot",
            rollout_state="redacted_public_docs_only",
            allowed_use="Secondary document research with citations for public or explicitly redacted property documents.",
            forbidden_use="Cannot receive private documents, rewrite facts directly, or answer without page-level evidence receipts.",
            source_of_truth="PropertyQuarry owns document vault records, extracted claims, verification state, and deletion status.",
            allowed_inputs=("redacted_document", "document_question", "citation_request"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS + ("unredacted_private_document",),
            allowed_data_classes=("document_claim_candidate", "citation_receipt", "provider_deletion_receipt"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_PAPERGUIDE_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_PAPERGUIDE_DISABLED",),
            verification_required=("retention_policy", "delete_workspace_proof", "citation_roundtrip", "training_use_review"),
            fail_closed_rule="Returned claims stay unverified until PropertyQuarry stores a citation-backed evidence claim.",
        ),
        PropertyIntegrationLane(
            provider_key="internxt",
            title="Internxt",
            priority=4,
            product_lane="encrypted_offsite_recovery",
            rollout_state="backup_pilot_disabled",
            allowed_use="Encrypted off-site backup packages, checksum manifests, and restore-drill artifacts.",
            forbidden_use="Not live storage, not primary database, not a public artifact host, and not a direct document vault.",
            source_of_truth="PropertyQuarry owns live storage, retention, backup manifests, restore status, and deletion decisions.",
            allowed_inputs=("encrypted_backup_package", "checksum_manifest", "restore_drill_receipt"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS + ("unencrypted_database_dump", "unencrypted_document_bundle"),
            allowed_data_classes=("encrypted_backup", "backup_manifest", "restore_receipt"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_INTERNXT_BACKUP_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_INTERNXT_BACKUP_DISABLED",),
            verification_required=("client_side_encryption", "upload_receipt", "restore_drill", "delete_verification"),
            fail_closed_rule="Only encrypted packages with checksum manifests may leave the PropertyQuarry storage boundary.",
        ),
        PropertyIntegrationLane(
            provider_key="approvethis",
            title="ApproveThis",
            priority=5,
            product_lane="agent_plan_external_approval",
            rollout_state="agent_plan_pilot_disabled",
            allowed_use="Optional Agent-plan approvals for branded dossiers, outbound reports, broker-question sets, and public content.",
            forbidden_use="Cannot replace PropertyQuarry policy, human-review authority, or ordinary buyer decisions.",
            source_of_truth="PropertyQuarry owns approval ledger, required authority, and action execution.",
            allowed_inputs=("approval_request_summary", "redacted_action_context", "review_role"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS,
            allowed_data_classes=("external_approval_request", "approval_receipt", "approval_audit_event"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_APPROVETHIS_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_APPROVETHIS_DISABLED",),
            verification_required=("signed_result", "replay_block", "role_mapping", "internal_ledger_receipt"),
            fail_closed_rule="External approval is advisory until PropertyQuarry verifies and records it in the internal approval ledger.",
        ),
        PropertyIntegrationLane(
            provider_key="unmixr",
            title="Unmixr",
            priority=6,
            product_lane="accessible_audio_briefing_prototype",
            rollout_state="optional_prototype_disabled",
            allowed_use="Audio briefings generated only from redacted compiled dossiers or public educational scripts.",
            forbidden_use="Cannot narrate raw provider payloads, private preferences, unpublished documents, or source-of-truth claims.",
            source_of_truth="PropertyQuarry owns dossier text, disclosures, voice rights checks, and audio publication approval.",
            allowed_inputs=("redacted_compiled_dossier", "approved_public_script", "voice_profile_ref"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS + ("raw_listing_html", "unapproved_script"),
            allowed_data_classes=("audio_candidate", "voice_render_receipt", "transcript_receipt"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_UNMIXR_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_UNMIXR_DISABLED",),
            verification_required=("commercial_voice_rights", "delete_receipt", "transcript_match", "human_review"),
            fail_closed_rule="Audio remains a candidate artifact until transcript, disclosure, rights, and human-review gates pass.",
        ),
        PropertyIntegrationLane(
            provider_key="deftform",
            title="Deftform",
            priority=6,
            product_lane="public_intake_only",
            rollout_state="optional_intake_disabled",
            allowed_use="Public intake forms for submitted properties, due-diligence requests, beta interest, and inaccuracy reports.",
            forbidden_use="Cannot act as canonical private document vault, decision system, or authenticated workflow.",
            source_of_truth="PropertyQuarry owns intake references, identity handoff, sensitive uploads, and follow-up state.",
            allowed_inputs=("public_intake_submission", "redacted_contact_reference", "submission_category"),
            forbidden_inputs=_COMMON_FORBIDDEN_INPUTS + ("private_document_upload",),
            allowed_data_classes=("public_intake_receipt", "submission_reference", "handoff_event"),
            exact_address_allowed=False,
            private_documents_allowed=False,
            enabled_env=("PROPERTYQUARRY_DEFTFORM_ENABLED",),
            kill_switch_env=("PROPERTYQUARRY_DEFTFORM_DISABLED",),
            verification_required=("form_submission_receipt", "authenticated_handoff", "sensitive_upload_block", "spam_controls"),
            fail_closed_rule="Sensitive material must move into an authenticated PropertyQuarry flow before processing.",
        ),
    )


def property_integration_governance_rows() -> tuple[dict[str, object], ...]:
    return tuple(lane.as_row() for lane in sorted(property_integration_governance_lanes(), key=lambda lane: (lane.priority, lane.provider_key)))


def required_property_integration_receipts() -> tuple[dict[str, str], ...]:
    return (
        {
            "title": "Provider verification",
            "detail": "Every integration needs account/API proof, a health check, and a redacted configuration receipt before it can leave disabled mode.",
            "tag": "Required",
        },
        {
            "title": "Privacy projection",
            "detail": "Allowed data classes, exact-address posture, private-document posture, and deletion/retention proof must be explicit per provider.",
            "tag": "Required",
        },
        {
            "title": "PropertyQuarry source of truth",
            "detail": "External tools may transport or draft; PropertyQuarry keeps decisions, property facts, ranking, billing, publication, and approvals canonical.",
            "tag": "Required",
        },
        {
            "title": "Kill switch",
            "detail": "Every integration needs an env-level off switch and fail-closed behavior when receipts, permissions, or provider health are missing.",
            "tag": "Required",
        },
    )
