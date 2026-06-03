-- v0_20: communication policies kernel seed

CREATE TABLE IF NOT EXISTS communication_policies (
    policy_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    preferred_channel TEXT NOT NULL,
    tone TEXT NOT NULL,
    max_length INTEGER NOT NULL,
    quiet_hours_json JSONB NOT NULL,
    escalation_json JSONB NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comm_policies_principal_status
ON communication_policies(principal_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_comm_policies_principal_scope
ON communication_policies(principal_id, scope);
