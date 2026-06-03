-- Task-contract kernel baseline
-- Stores typed task contracts for intent compilation and planning.

CREATE TABLE IF NOT EXISTS task_contracts (
    task_key TEXT PRIMARY KEY,
    deliverable_type TEXT NOT NULL,
    default_risk_class TEXT NOT NULL,
    default_approval_class TEXT NOT NULL,
    allowed_tools_json JSONB NOT NULL,
    evidence_requirements_json JSONB NOT NULL,
    memory_write_policy TEXT NOT NULL,
    budget_policy_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_contracts_updated
ON task_contracts(updated_at DESC);
