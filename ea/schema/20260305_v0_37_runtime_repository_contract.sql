-- Canonical runtime repository schema
--
-- Production API, worker, scheduler, and render roles never run repository
-- startup DDL.  Keep every relation that was historically bootstrapped by a
-- repository constructor in the privileged migration lane instead.

CREATE TABLE IF NOT EXISTS evidence_objects (
    evidence_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    claims_json JSONB NOT NULL,
    evidence_refs_json JSONB NOT NULL,
    open_questions_json JSONB NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    citation_handle TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_objects_principal_created
ON evidence_objects(principal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_objects_session_created
ON evidence_objects(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_objects_refs_gin
ON evidence_objects USING GIN (evidence_refs_json);

CREATE TABLE IF NOT EXISTS onboarding_states (
    onboarding_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL UNIQUE,
    workspace_name TEXT NOT NULL DEFAULT '',
    workspace_mode TEXT NOT NULL DEFAULT 'personal',
    region TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT '',
    selected_channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    property_search_preferences_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_preferences_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    channel_preferences_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    brief_preview_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE onboarding_states
ADD COLUMN IF NOT EXISTS property_search_preferences_json
JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_onboarding_states_updated
ON onboarding_states(updated_at DESC);

CREATE TABLE IF NOT EXISTS person_profiles (
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    profile_scope TEXT NOT NULL DEFAULT 'personal',
    consent_mode TEXT NOT NULL DEFAULT 'explicit_only',
    learning_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    high_stakes_domains_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE person_profiles DROP CONSTRAINT IF EXISTS person_profiles_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_person_profiles_principal_person
ON person_profiles(principal_id, person_id);

CREATE TABLE IF NOT EXISTS preference_nodes (
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    strength TEXT NOT NULL DEFAULT 'medium',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    source_mode TEXT NOT NULL DEFAULT 'explicit',
    status TEXT NOT NULL DEFAULT 'active',
    decay_policy TEXT NOT NULL DEFAULT 'reinforce_only',
    last_confirmed_at TEXT NOT NULL DEFAULT '',
    last_observed_at TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE preference_nodes DROP CONSTRAINT IF EXISTS preference_nodes_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_nodes_principal_person_node
ON preference_nodes(principal_id, person_id, node_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_nodes_identity
ON preference_nodes(principal_id, person_id, domain, category, key);

CREATE TABLE IF NOT EXISTS preference_evidence_events (
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    event_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    raw_signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    interpreted_signal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    signal_strength DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    reversible BOOLEAN NOT NULL DEFAULT TRUE,
    recorded_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE preference_evidence_events
DROP CONSTRAINT IF EXISTS preference_evidence_events_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_evidence_events_principal_person_event
ON preference_evidence_events(principal_id, person_id, event_id);

CREATE TABLE IF NOT EXISTS preference_decision_assessments (
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    fit_score DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    predicted_reaction TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    match_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    mismatch_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    unknowns_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocking_constraints_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    assessment_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE preference_decision_assessments
DROP CONSTRAINT IF EXISTS preference_decision_assessments_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_decision_assessments_principal_person_assessment
ON preference_decision_assessments(principal_id, person_id, assessment_id);

CREATE TABLE IF NOT EXISTS preference_profile_corrections (
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    correction_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    old_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    corrected_by TEXT NOT NULL DEFAULT '',
    corrected_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE preference_profile_corrections
DROP CONSTRAINT IF EXISTS preference_profile_corrections_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS idx_preference_profile_corrections_principal_person_correction
ON preference_profile_corrections(principal_id, person_id, correction_id);

CREATE TABLE IF NOT EXISTS onemin_accounts (
    account_id TEXT PRIMARY KEY,
    provider_key TEXT NOT NULL,
    account_label TEXT NOT NULL,
    owner_email TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    browseract_binding_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    remaining_credits DOUBLE PRECISION NULL,
    max_credits DOUBLE PRECISION NULL,
    core_floor_credits DOUBLE PRECISION NULL,
    image_spendable_credits DOUBLE PRECISION NULL,
    reserve_credits DOUBLE PRECISION NULL,
    slot_count INTEGER NOT NULL,
    ready_slot_count INTEGER NOT NULL,
    last_billing_snapshot_at TIMESTAMPTZ NULL,
    last_member_reconciliation_at TIMESTAMPTZ NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS onemin_credentials (
    credential_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    slot_name TEXT NOT NULL,
    secret_env_name TEXT NOT NULL,
    owner_email TEXT NOT NULL,
    active_role TEXT NOT NULL,
    state TEXT NOT NULL,
    remaining_credits DOUBLE PRECISION NULL,
    max_credits DOUBLE PRECISION NULL,
    last_probe_at TIMESTAMPTZ NULL,
    last_success_at TIMESTAMPTZ NULL,
    last_error TEXT NOT NULL,
    quarantine_until TIMESTAMPTZ NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS onemin_allocation_leases (
    lease_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    capability TEXT NOT NULL,
    account_id TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    estimated_credits INTEGER NULL,
    actual_credits_delta INTEGER NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    error TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_onemin_credentials_account
ON onemin_credentials(account_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_onemin_leases_status_account
ON onemin_allocation_leases(status, account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS property_decision_ledger (
    decision_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL DEFAULT 'self',
    property_ref TEXT NOT NULL,
    decision_state TEXT NOT NULL,
    reason_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    supersedes_decision_id TEXT NOT NULL DEFAULT '',
    learning_applied BOOLEAN NOT NULL DEFAULT FALSE,
    aggregate_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_property_decision_ledger_principal_property_created
ON property_decision_ledger(principal_id, property_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS property_evidence_claims (
    claim_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL DEFAULT 'self',
    property_ref TEXT NOT NULL,
    decision_id TEXT NOT NULL DEFAULT '',
    claim_type TEXT NOT NULL,
    text TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'propertyquarry',
    source_ref TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium',
    verification_state TEXT NOT NULL DEFAULT 'unclear',
    privacy_class TEXT NOT NULL DEFAULT 'owner_private',
    allowed_outputs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_property_evidence_claims_principal_property_created
ON property_evidence_claims(principal_id, property_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS property_agent_question_tasks (
    task_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL DEFAULT 'self',
    property_ref TEXT NOT NULL,
    decision_id TEXT NOT NULL DEFAULT '',
    question_text TEXT NOT NULL,
    reason_key TEXT NOT NULL DEFAULT '',
    source_claim_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'drafted',
    answer_source TEXT NOT NULL DEFAULT '',
    updated_claim_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_property_agent_question_tasks_principal_property_created
ON property_agent_question_tasks(principal_id, property_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS property_documents (
    document_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL DEFAULT 'self',
    property_ref TEXT NOT NULL,
    decision_id TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    privacy_class TEXT NOT NULL DEFAULT 'owner_private',
    verification_state TEXT NOT NULL DEFAULT 'missing',
    extracted_claims_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_pages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    redaction_state TEXT NOT NULL DEFAULT 'not_started',
    linked_risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_property_documents_principal_property_created
ON property_documents(principal_id, property_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS property_packet_publications (
    publication_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    person_id TEXT NOT NULL DEFAULT 'self',
    property_ref TEXT NOT NULL,
    search_run_id TEXT NOT NULL DEFAULT '',
    packet_kind TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    fliplink_format TEXT NOT NULL,
    source_packet_ref TEXT NOT NULL,
    source_pdf_artifact_ref TEXT NOT NULL,
    source_pdf_sha256 TEXT NOT NULL,
    source_pdf_size_bytes INTEGER NOT NULL,
    redaction_policy_version TEXT NOT NULL,
    fliplink_publication_id TEXT NOT NULL DEFAULT '',
    fliplink_url TEXT NOT NULL DEFAULT '',
    fliplink_custom_domain_url TEXT NOT NULL DEFAULT '',
    fliplink_embed_code TEXT NOT NULL DEFAULT '',
    fliplink_qr_url TEXT NOT NULL DEFAULT '',
    lead_capture_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    password_required BOOLEAN NOT NULL DEFAULT FALSE,
    sale_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    archived_at TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_detail TEXT NOT NULL DEFAULT '',
    recommended_title TEXT NOT NULL DEFAULT '',
    recommended_format TEXT NOT NULL DEFAULT '',
    artifact_download_path TEXT NOT NULL DEFAULT '',
    receipt_artifact_ref TEXT NOT NULL DEFAULT '',
    redaction_receipt_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    packet_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_property_packet_publications_principal_updated
ON property_packet_publications(principal_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_property_packet_publications_fliplink_url
ON property_packet_publications(fliplink_url);

CREATE TABLE IF NOT EXISTS property_packet_publication_events (
    event_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_property_packet_publication_events_publication_created
ON property_packet_publication_events(publication_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_property_packet_publication_events_principal_type_created
ON property_packet_publication_events(principal_id, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS property_packet_schema_versions (
    schema_name TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

INSERT INTO property_packet_schema_versions
    (schema_name, schema_version, updated_at)
VALUES ('property_packet_publications', 2, NOW())
ON CONFLICT (schema_name) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    updated_at = EXCLUDED.updated_at;

CREATE TABLE IF NOT EXISTS response_records (
    response_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    response_json JSONB NOT NULL,
    input_items_json JSONB NOT NULL,
    history_items_json JSONB NOT NULL,
    background_job_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE response_records
ADD COLUMN IF NOT EXISTS background_job_json JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_response_records_principal_created
ON response_records(principal_id, created_at DESC);
