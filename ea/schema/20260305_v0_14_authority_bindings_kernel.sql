-- v0_14: authority bindings kernel seed

CREATE TABLE IF NOT EXISTS authority_bindings (
    binding_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    action_scope TEXT NOT NULL,
    approval_level TEXT NOT NULL,
    channel_scope_json JSONB NOT NULL,
    policy_json JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_authority_bindings_identity_unique
ON authority_bindings(principal_id, subject_ref, action_scope);

CREATE INDEX IF NOT EXISTS idx_authority_bindings_principal_status
ON authority_bindings(principal_id, status, updated_at DESC);
