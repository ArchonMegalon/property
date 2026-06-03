-- v0_15: delivery preferences kernel seed

CREATE TABLE IF NOT EXISTS delivery_preferences (
    preference_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient_ref TEXT NOT NULL,
    cadence TEXT NOT NULL,
    quiet_hours_json JSONB NOT NULL,
    format_json JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_preferences_identity_unique
ON delivery_preferences(principal_id, channel, recipient_ref);

CREATE INDEX IF NOT EXISTS idx_delivery_preferences_principal_status
ON delivery_preferences(principal_id, status, updated_at DESC);
