-- Execution ledger kernel baseline
-- Mirrors the auto-create schema used by PostgresExecutionLedgerRepository.

CREATE TABLE IF NOT EXISTS execution_sessions (
    session_id TEXT PRIMARY KEY,
    intent_json JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_events_session_created
ON execution_events(session_id, created_at);
