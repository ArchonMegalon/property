-- Channel runtime kernel baseline
-- Generic observation event intake + channel-agnostic delivery outbox.

CREATE TABLE IF NOT EXISTS observation_events (
    observation_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_observation_events_created
ON observation_events(created_at DESC);

CREATE TABLE IF NOT EXISTS delivery_outbox (
    delivery_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_status_created
ON delivery_outbox(status, created_at DESC);
